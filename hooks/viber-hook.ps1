<#
.SYNOPSIS
  Claude Code hook that connects a session to Viber. Never blocks or fails a session: if Viber is
  unreachable it exits 0 silently.
.DESCRIPTION
  SessionStart  -> registers the session, injects the context pack (rules, handoffs, other sessions, bugs, ...)
  PreToolUse    -> claims the file before an edit; if another live session holds it, warns the session
                   (VIBER_CLAIMS=enforce refuses the edit instead; default is warn)
  PostToolUse   -> records edited files; warns when another active session touched the same file
  Stop          -> heartbeat (session idle)
  SessionEnd    -> marks the session ended (its claims are released with it)
  Configuration (environment): VIBER_URL (default http://localhost:8088), VIBER_PROJECT (required), VIBER_TOKEN
  Optional: VIBER_PARENT_SESSION (external id of the session this one was forked from),
            VIBER_CLAIMS = warn (default) | enforce | off
#>
param([Parameter(Mandatory)] [ValidateSet("SessionStart", "PreToolUse", "PostToolUse", "Stop", "SessionEnd")] [string] $Event)

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
        "PreToolUse" {
            $mode = if ($env:VIBER_CLAIMS) { $env:VIBER_CLAIMS } else { "warn" }
            $path = $hookInput.tool_input.file_path
            if ($mode -eq "off" -or -not $path) { exit 0 }
            # Claim key = repo + path inside it, so README.md in two repos never collides.
            $root = Get-Git $cwd @("rev-parse", "--show-toplevel")
            $remote = Get-Git $cwd @("remote", "get-url", "origin")
            $repoName = if ($remote -match "github\.com[:/]+([^/]+/[^/]+?)(\.git)?$") { $Matches[1] } elseif ($root) { Split-Path $root -Leaf } else { "" }
            $slash = $path.Replace("\", "/")
            $inside = if ($root -and $slash.StartsWith($root.Replace("\", "/") + "/", [StringComparison]::OrdinalIgnoreCase)) { $slash.Substring($root.Length + 1) } else { $slash }
            $key = if ($repoName -and $inside -ne $slash) { "$repoName`:$inside" } else { $slash }
            $result = Invoke-Viber Post "/sessions/$sessionId/claim" @{ paths = @($key); reason = $hookInput.tool_name; ttl_minutes = 30 }
            if (@($result.blocked).Count -gt 0) {
                $b = @($result.blocked)[0]
                $text = "Viber: $key is claimed by $($b.held_by)$(if ($b.goal) { " ($($b.goal))" }). Wait for them, pick another file, or ask the operator."
                if ($mode -eq "enforce") {
                    @{ hookSpecificOutput = @{ hookEventName = "PreToolUse"; permissionDecision = "deny"; permissionDecisionReason = $text } } | ConvertTo-Json -Depth 4 -Compress
                } else {
                    Write-HookContext "PreToolUse" ($text + " (warning only: VIBER_CLAIMS=warn)")
                }
            }
        }
        "PostToolUse" {
            $path = $hookInput.tool_input.file_path
            if (-not $path) { exit 0 }
            $root = Get-Git $cwd @("rev-parse", "--show-toplevel")
            $remote = Get-Git $cwd @("remote", "get-url", "origin")
            $repoName = if ($remote -match "github\.com[:/]+([^/]+/[^/]+?)(\.git)?$") { $Matches[1] } elseif ($root) { Split-Path $root -Leaf } else { "" }
            $slash = $path.Replace("\", "/")
            $inside = if ($root -and $slash.StartsWith($root.Replace("\", "/") + "/", [StringComparison]::OrdinalIgnoreCase)) { $slash.Substring($root.Length + 1) } else { $slash }
            $relative = if ($repoName -and $inside -ne $slash) { "$repoName`:$inside" } else { $slash }
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

