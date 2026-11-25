<#
.SYNOPSIS
  Wires Claude Code sessions in one repository into Viber: writes that repo's .claude/settings.local.json
  (git-ignored by Claude Code) with the Viber env and hooks, using this machine's paths.
.DESCRIPTION
  Merges into an existing settings.local.json instead of replacing it (the old file is kept as .bak the
  first time), and running it again changes nothing. Run it once per repository, on each machine.
  It does not touch your user-level Claude settings or any committed file.
.EXAMPLE
  .\hooks\install.ps1 -Repo E:\MyWorx\sbos-v3\sb-core -Project sbos -Token <token>
#>
param(
    [string] $Repo = (Get-Location).Path,
    [Parameter(Mandatory)] [string] $Project,
    [string] $ViberUrl = "http://localhost:8088",
    [string] $Token = ""
)

$ErrorActionPreference = "Stop"
$hookScript = (Join-Path $PSScriptRoot "viber-hook.ps1").Replace("\", "/")
$settingsDirectory = Join-Path $Repo ".claude"
$settingsFile = Join-Path $settingsDirectory "settings.local.json"
if (-not (Test-Path $Repo)) { throw "Repo folder not found: $Repo" }

# PowerShell unwraps one-item arrays on return and in `if` expressions; the leading comma and the explicit
# lists below stop that, otherwise a hook list with one entry is written back as an object and breaks.
function ConvertTo-Hashtable($Value) {
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $table = [ordered]@{}
        foreach ($property in $Value.PSObject.Properties) { $table[$property.Name] = ConvertTo-Hashtable $property.Value }
        return $table
    }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
        $list = [System.Collections.Generic.List[object]]::new()
        foreach ($item in $Value) { $list.Add((ConvertTo-Hashtable $item)) }
        return , $list.ToArray()
    }
    return $Value
}

$settings = [ordered]@{}
if (Test-Path $settingsFile) {
    if (-not (Test-Path "$settingsFile.bak")) { Copy-Item $settingsFile "$settingsFile.bak" }
    $settings = ConvertTo-Hashtable (Get-Content $settingsFile -Raw | ConvertFrom-Json)
}
if (-not $settings.Contains("env")) { $settings["env"] = [ordered]@{} }
$settings["env"]["VIBER_URL"] = $ViberUrl
$settings["env"]["VIBER_PROJECT"] = $Project
if ($Token) { $settings["env"]["VIBER_TOKEN"] = $Token }

$events = [ordered]@{ SessionStart = ""; PostToolUse = "Edit|Write|MultiEdit"; Stop = ""; SessionEnd = "" }
if (-not $settings.Contains("hooks")) { $settings["hooks"] = [ordered]@{} }
foreach ($event in $events.Keys) {
    $command = "powershell -NoProfile -ExecutionPolicy Bypass -File $hookScript -Event $event"
    $entries = [System.Collections.Generic.List[object]]::new()
    if ($settings["hooks"].Contains($event)) { foreach ($existing in $settings["hooks"][$event]) { $entries.Add($existing) } }
    $found = $false
    foreach ($entry in $entries) {
        foreach ($hook in $entry["hooks"]) {
            if ($hook["command"] -like "*viber-hook.ps1*-Event $event") {
                # Same hook, possibly another machine's path: point it at this one.
                $hook["command"] = $command
                $found = $true
            }
        }
    }
    if (-not $found) {
        $newHook = [ordered]@{ type = "command"; timeout = 10; command = $command }
        $newEntry = [ordered]@{}
        if ($events[$event]) { $newEntry["matcher"] = $events[$event] }
        $newEntry["hooks"] = [object[]]@($newHook)
        $entries.Add($newEntry)
    }
    $settings["hooks"][$event] = $entries.ToArray()
}

New-Item -ItemType Directory -Force $settingsDirectory | Out-Null
$settings | ConvertTo-Json -Depth 12 | Set-Content $settingsFile -Encoding utf8
Write-Host "Wrote $settingsFile"
Write-Host "  project=$Project url=$ViberUrl token=$(if ($Token) { 'set' } else { 'not set' })"
Write-Host ""
Write-Host "Last step, once per machine: add the MCP server so Claude can call the viber_* tools."
Write-Host "  Project scope: put this in <repo>\.mcp.json (Claude asks you to approve it on first use):"
$authHeader = if ($Token) { ', "headers": { "Authorization": "Bearer <token>" }' } else { '' }
Write-Host ('    {{ "mcpServers": {{ "viber": {{ "type": "http", "url": "{0}/mcp"{1} }} }} }}' -f $ViberUrl, $authHeader)
Write-Host "  Or in the Claude Code CLI:  claude mcp add --transport http viber $ViberUrl/mcp"
