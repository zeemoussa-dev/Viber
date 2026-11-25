<#
.SYNOPSIS
  Claude Code hook that connects a session to Viber. Never blocks or fails a session: if Viber is
  unreachable it exits 0 silently.
.DESCRIPTION
  SessionStart  -> registers the session, injects the context pack (rules, handoffs, other sessions, bugs, ...)
  PostToolUse   -> records edited files; warns when another active session touched the same file
  Stop          -> heartbeat (session idle)
  SessionEnd    -> marks the session ended
  Configuration (environment): VIBER_URL (default http://localhost:8088), VIBER_PROJECT (required), VIBER_TOKEN
  Optional: VIBER_PARENT_SESSION (external id of the session this one was forked from)
#>
param([Parameter(Mandatory)] [ValidateSet("SessionStart", "PostToolUse", "Stop", "SessionEnd")] [string] $Event)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ViberUrl = if ($env:VIBER_URL) { $env:VIBER_URL.TrimEnd("/") } else { "http://localhost:8088" }
$Project = $env:VIBER_PROJECT
if (-not $Project) { exit 0 }

function Invoke-Viber([string] $Method, [string] $Path, $Body) {
    $headers = @{ "X-Viber-Actor" = "claude-hook" }
    if ($env:VIBER_TOKEN) { $headers["Authorization"] = "Bearer $($env:VIBER_TOKEN)" }
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

try {
    $raw = [Console]::In.ReadToEnd()
    if (-not $raw) { exit 0 }
    $hookInput = $raw | ConvertFrom-Json
    $sessionId = $hookInput.session_id
    $cwd = $hookInput.cwd
    if (-not $sessionId) { exit 0 }

    switch ($Event) {
        "SessionStart" {
            $remote = Get-Git $cwd @("remote", "get-url", "origin")
            $repo = if ($remote -match "github\.com[:/]+([^/]+/[^/]+?)(\.git)?$") { $Matches[1] } else { $null }
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
            $root = Get-Git $cwd @("rev-parse", "--show-toplevel")
            $relative = if ($root -and $path.Replace("\", "/").StartsWith($root.Replace("\", "/") + "/", [StringComparison]::OrdinalIgnoreCase)) {
                $path.Replace("\", "/").Substring($root.Length + 1) } else { $path }
            $touch = Invoke-Viber Post "/sessions/$sessionId/touch" @{ path = $relative; tool = $hookInput.tool_name }
            if (@($touch.overlaps).Count -gt 0) {
                $who = (@($touch.overlaps) | ForEach-Object { if ($_.goal) { "$($_.tag) ($($_.goal))" } else { "$($_.tag)" } }) -join ", "
                Write-HookContext "PostToolUse" "Viber: another active session also edited $relative recently: $who. Check with viber_sessions before continuing; avoid conflicting edits."
            }
        }
        "Stop" { Invoke-Viber Post "/sessions/$sessionId/heartbeat?state=idle" $null | Out-Null }
        "SessionEnd" { Invoke-Viber Post "/sessions/$sessionId/end" @{} | Out-Null }
    }
} catch {
    # Viber being down or slow must never affect the session. Set VIBER_DEBUG=1 to see why one failed.
    if ($env:VIBER_DEBUG) { [Console]::Error.WriteLine("viber-hook $Event failed: $($_.Exception.Message)") }
    exit 0
}

