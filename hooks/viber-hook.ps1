<#
.SYNOPSIS
  Claude Code hook that connects a session to Viber. Never blocks or fails a session: if Viber is
  unreachable, or the session belongs to no known project, it exits 0 silently.
.DESCRIPTION
  SessionStart  -> works out the session's project, registers the session, injects the context pack
                   (rules, handoffs, other sessions, bugs, ...)
  PostToolUse   -> records edited files; warns when another active session touched the same file
  Stop          -> heartbeat (session idle)
  SessionEnd    -> marks the session ended
  The project is never assumed: Viber is asked (GET /v1/resolve) by the session's repository, then by the folder it works in
  (a project's settings.workspaces). A session in a place no project owns gets nothing and writes nothing, so one project's
  memory never reaches another's. VIBER_PROJECT, if set, overrides the lookup (use it only for a single-project machine).
  Configuration (environment): VIBER_URL (default http://localhost:8088), VIBER_TOKEN
  Optional: VIBER_PARENT_SESSION (external id of the session this one was forked from)
#>
param([Parameter(Mandatory)] [ValidateSet("SessionStart", "PostToolUse", "Stop", "SessionEnd")] [string] $Event)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ViberUrl = if ($env:VIBER_URL) { $env:VIBER_URL.TrimEnd("/") } else { "http://localhost:8088" }
$Project = $null

function Get-ViberHeaders {
    $headers = @{ "X-Viber-Actor" = "claude-hook" }
    if ($env:VIBER_TOKEN) { $headers["Authorization"] = "Bearer $($env:VIBER_TOKEN)" }
    return $headers
}

function Invoke-Viber([string] $Method, [string] $Path, $Body) {
    $headers = Get-ViberHeaders
    $uri = "$ViberUrl/v1/projects/$Project$Path"
    if ($null -eq $Body) { return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -TimeoutSec 4 }
    $json = $Body | ConvertTo-Json -Depth 6 -Compress
    return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -TimeoutSec 4 `
        -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($json))
}

function Get-Git([string] $Directory, [string[]] $Arguments) {
    try { $out = & git -C $Directory @Arguments 2>$null; if ($LASTEXITCODE -eq 0) { return ($out -join "`n").Trim() } } catch { }
    return $null
}

function Write-HookContext([string] $EventName, [string] $Text) {
    @{ hookSpecificOutput = @{ hookEventName = $EventName; additionalContext = $Text } } | ConvertTo-Json -Depth 4 -Compress
}

function Get-RepoName([string] $Directory) {
    $remote = Get-Git $Directory @("remote", "get-url", "origin")
    if ($remote -match "github\.com[:/]+([^/]+/[^/]+?)(\.git)?$") { return $Matches[1] }
    return $null
}

function Resolve-Project([string] $SessionId, [string] $Directory) {
    if ($env:VIBER_PROJECT) { return $env:VIBER_PROJECT }
    $cache = Join-Path ([IO.Path]::GetTempPath()) "viber-project-$SessionId.txt"
    if ($Event -ne "SessionStart" -and (Test-Path $cache)) { return ((Get-Content $cache -Raw).Trim()) }
    $query = @()
    $repo = Get-RepoName $Directory
    if ($repo) { $query += "repo=$([uri]::EscapeDataString($repo))" }
    if ($Directory) { $query += "cwd=$([uri]::EscapeDataString($Directory))" }
    $found = ""
    if ($query) {
        $answer = Invoke-RestMethod -Method Get -Uri "$ViberUrl/v1/resolve?$($query -join '&')" -Headers (Get-ViberHeaders) -TimeoutSec 4
        if ($answer.project) { $found = $answer.project }
    }
    Set-Content -Path $cache -Value $found -Encoding ascii
    return $found
}

function Get-FileKey([string] $Path, [string] $Directory) {
    # Key = repo + path inside it, so README.md in two repos never collides.
    $root = Get-Git $Directory @("rev-parse", "--show-toplevel")
    $repoName = Get-RepoName $Directory
    if (-not $repoName -and $root) { $repoName = Split-Path $root -Leaf }
    $slash = $Path.Replace("\", "/")
    $inside = if ($root -and $slash.StartsWith($root.Replace("\", "/") + "/", [StringComparison]::OrdinalIgnoreCase)) { $slash.Substring($root.Length + 1) } else { $slash }
    if ($repoName -and $inside -ne $slash) { return "$repoName`:$inside" }
    return $slash
}

try {
    $raw = [Console]::In.ReadToEnd()
    if (-not $raw) { exit 0 }
    $hookInput = $raw | ConvertFrom-Json
    $sessionId = $hookInput.session_id
    $cwd = $hookInput.cwd
    if (-not $sessionId) { exit 0 }
    $Project = Resolve-Project $sessionId $cwd
    if (-not $Project) { exit 0 }

    switch ($Event) {
        "SessionStart" {
            $repo = Get-RepoName $cwd
            $body = @{
                session_id = $sessionId; cwd = $cwd; repo = $repo; source = $hookInput.source
                subpath = (Get-Git $cwd @("rev-parse", "--show-prefix"))
                branch = (Get-Git $cwd @("branch", "--show-current")); host = $env:COMPUTERNAME
            }
            if ($env:VIBER_PARENT_SESSION) { $body["parent_session_id"] = $env:VIBER_PARENT_SESSION }
            $started = Invoke-Viber Post "/sessions/start" $body
            Write-HookContext "SessionStart" $started.context
        }
        "PostToolUse" {
            $path = $hookInput.tool_input.file_path
            if (-not $path) { exit 0 }
            $relative = Get-FileKey $path $cwd
            $touch = Invoke-Viber Post "/sessions/$sessionId/touch" @{ path = $relative; tool = $hookInput.tool_name }
            if (@($touch.overlaps).Count -gt 0) {
                $who = (@($touch.overlaps) | ForEach-Object { if ($_.goal) { "$($_.tag) ($($_.goal))" } else { "$($_.tag)" } }) -join ", "
                Write-HookContext "PostToolUse" "Viber: another active session also edited $relative recently: $who. Check with viber_sessions before continuing; avoid conflicting edits."
            }
        }
        "Stop" { Invoke-Viber Post "/sessions/$sessionId/heartbeat?state=idle" $null | Out-Null }
        "SessionEnd" {
            Invoke-Viber Post "/sessions/$sessionId/end" @{} | Out-Null
            Remove-Item (Join-Path ([IO.Path]::GetTempPath()) "viber-project-$sessionId.txt") -ErrorAction SilentlyContinue
        }
    }
} catch {
    # Viber being down or slow must never affect the session. Set VIBER_DEBUG=1 to see why one failed.
    if ($env:VIBER_DEBUG) { [Console]::Error.WriteLine("viber-hook $Event failed: $($_.Exception.Message)") }
    exit 0
}
