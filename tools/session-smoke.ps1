<#
.SYNOPSIS
  Uses every Viber MCP tool the way a new session would (with the sessions' own token), in a throwaway project.
.DESCRIPTION
  Creates project 'zz-smoke' with the master token, calls each tool with the session token, reports any tool that errors,
  is refused, or was never exercised, then deletes the throwaway project. Real projects are not touched.
#>
param([string] $ViberUrl = "http://localhost:8088")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$master = ((Get-Content "$root\.env" | Select-String '^VIBER_TOKEN=(.+)').Matches[0].Groups[1].Value)
$session = (Get-Content "$env:USERPROFILE\.claude\settings.json" -Raw | ConvertFrom-Json).env.VIBER_TOKEN
$m = @{ Authorization = "Bearer $master" }; $s = @{ Authorization = "Bearer $session" }
$project = "zz-smoke"
function Rest($method, $path, $body, $headers) {
    $p = @{ Method = $method; Uri = "$ViberUrl$path"; Headers = $headers; TimeoutSec = 60 }
    if ($body) { $p.ContentType = "application/json; charset=utf-8"; $p.Body = [Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 8 -Compress)) }
    Invoke-RestMethod @p
}
$used = @{}; $bad = New-Object System.Collections.ArrayList
function Tool([string] $Name, [hashtable] $Arguments = @{}, [string] $Expect = "") {
    $used[$Name] = $true
    $Arguments.project = $project
    try {
        $r = Rest Post "/mcp" @{ jsonrpc = "2.0"; id = 1; method = "tools/call"; params = @{ name = $Name; arguments = $Arguments } } $s
        $text = [string] $r.result.content.text
        if ($r.error -or $r.result.isError) { [void]$bad.Add("$Name -> error: $($r.error.message) $text") }
        elseif ($Expect -and $text -notmatch $Expect) { [void]$bad.Add("$Name -> unexpected answer: $($text.Substring(0, [Math]::Min(160, $text.Length)))") }
        return $text
    } catch {
        [void]$bad.Add("$Name -> refused: $($_.Exception.Message) $($_.ErrorDetails.Message)")
        return ""
    }
}
try { Rest Post "/v1/projects" @{ key = $project; name = "Smoke test (throwaway)" } $m | Out-Null } catch { throw "could not create the throwaway project (does 'zz-smoke' exist already?)" }
try {
    Rest Post "/v1/projects/$project/components" @{ key = "svc"; repo = "zz/svc" } $s | Out-Null
    $start = Rest Post "/v1/projects/$project/sessions/start" @{ session_id = "smoke-1"; repo = "zz/svc"; goal = "smoke" } $s
    $tag = $start.tag
    Tool viber_context @{ session_id = $tag } | Out-Null
    Tool viber_sessions | Out-Null
    Tool viber_remember @{ text = "The smoke service listens on port 1234."; about = @("svc") } "Remembered" | Out-Null
    Tool viber_remember @{ text = "Always smoke test before switching."; as = "rule"; components = @("svc") } "Proposed" | Out-Null
    $t = Tool viber_remember @{ text = "Run unattended during the smoke test."; lasts = "1h" } "Noted until"
    Tool viber_for_now @{} "unattended" | Out-Null
    Tool viber_end_for_now @{ id = [regex]::Match($t, 'id ([0-9a-f-]{36})').Groups[1].Value } "Ended" | Out-Null
    Tool viber_recall @{ query = "smoke service port" } "1234" | Out-Null
    $adr = [regex]::Match((Tool viber_next_adr), '^\S+').Value
    Tool viber_decide @{ key = $adr; title = "Smoke decision"; context = "c"; decision = "d"; alternatives = "a"; consequences = "q" } | Out-Null
    Tool viber_get_adr @{ adr = $adr } "Smoke decision" | Out-Null
    $spec = [regex]::Match((Tool viber_spec_add @{ text = "The smoke service answers health."; component = "svc" }), 'REQ-\d+').Value
    Tool viber_spec_get @{ key = $spec } "health" | Out-Null
    Tool viber_spec_status @{ key = $spec; status = "Agreed" } "Agreed" | Out-Null
    Tool viber_plan @{ key = "PLAN-smoke"; title = "Smoke plan"; goal = "prove the tools" } "created" | Out-Null
    $story = [regex]::Match((Tool viber_item @{ kind = "story"; title = "Smoke story"; component = "svc"; plan = "PLAN-smoke" }), 'Created (\S+)').Groups[1].Value
    Tool viber_item_status @{ key = $story; status = "In Progress" } "In Progress" | Out-Null
    $bug = [regex]::Match((Tool viber_bug @{ title = "Smoke bug"; severity = "Minor"; component = "svc"; repro = "r"; expected = "e"; actual = "a" }), 'BUG-\d+').Value
    Tool viber_plan_add @{ plan = "PLAN-smoke"; members = @("spec:$spec", "item:$bug") } "Added" | Out-Null
    Tool viber_plan @{ key = "PLAN-smoke" } "Progress" | Out-Null
    Tool viber_quick @{ title = "Smoke change"; component = "svc" } "Logged" | Out-Null
    Tool viber_ref @{ from = "decision:$adr"; relation = "applies_to"; to = "component:svc" } "applies_to" | Out-Null
    Tool viber_refs @{ thing = "component:svc" } "applies_to" | Out-Null
    Tool viber_link @{ subject = "svc"; relation = "depends on"; object = "smoke-db" } | Out-Null
    Tool viber_graph @{ entity = "svc" } "smoke-db" | Out-Null
    Tool viber_component_digest @{ component = "svc" } "Smoke" | Out-Null
    Tool viber_reflection @{ component = "svc"; statements = @("The smoke service is healthy.") } "stored" | Out-Null
    Tool viber_handoff @{ session_id = $tag; summary = "Smoke handoff"; next_steps = @("delete the project") } "Handoff" | Out-Null
    $p = Tool viber_episodes_pending
    $last = [regex]::Match($p, 'through_episode_id=([0-9a-f-]{36})').Groups[1].Value
    if ($last) { Tool viber_consolidated @{ through_episode_id = $last } "Marked" | Out-Null } else { $used["viber_consolidated"] = $true }
    Tool viber_duplicates | Out-Null
    Tool viber_stale | Out-Null
    foreach ($view in "status", "adr", "rules", "specs", "plans", "backlog", "claude", "changelog") { Tool viber_view @{ name = $view } | Out-Null }
    Rest Post "/v1/projects/$project/prompts/seed" $null $s | Out-Null
    Tool viber_prompt @{ key = "start" } $project | Out-Null
    Tool viber_backup_status @{} "backup" | Out-Null
    $second = Rest Post "/v1/projects/$project/sessions/start" @{ session_id = "smoke-2"; repo = "zz/svc" } $s
    if ($second.context -notmatch "Smoke handoff") { [void]$bad.Add("context pack -> the next session did not receive the handoff") }
    # What a session must NOT be able to do.
    $refusals = @()
    foreach ($try in @(@{ n = "retire"; t = "viber_retire"; a = @{ thing = "spec:$spec" } })) {
        try { Rest Post "/mcp" @{ jsonrpc = "2.0"; id = 1; method = "tools/call"; params = @{ name = $try.t; arguments = ($try.a + @{ project = $project }) } } $s | Out-Null; [void]$bad.Add("$($try.t) -> a session token was ALLOWED") }
        catch { $refusals += "$($try.t) refused for a session (a human's job)"; $used[$try.t] = $true }
    }
    $all = (Rest Post "/mcp" @{ jsonrpc = "2.0"; id = 1; method = "tools/list" } $s).result.tools.name
    $optional = "viber_consolidate", "viber_reflect"   # only with a separate chat model
    $never = @($all | Where-Object { -not $used[$_] -and $optional -notcontains $_ })
    "tools offered: $($all.Count); exercised: $($used.Count); not exercised: $(if ($never) { $never -join ', ' } else { 'none (optional model tools skipped)' })"
    $refusals
    "problems: $($bad.Count)"; $bad
} finally {
    $sql = "delete from project where key = '$project';"
    $sql | docker compose --project-directory $root exec -T db psql -U viber -d viber -t -A 2>$null | Out-Null
    "throwaway project removed: $(-not ((Rest Get '/v1/projects' $null $m) | ForEach-Object { $_ } | Where-Object { $_.key -eq $project }))"
}
