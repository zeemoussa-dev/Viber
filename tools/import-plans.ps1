<#
.SYNOPSIS
  Turns the plan files into plan rows and links them to what they contain.
.DESCRIPTION
  1. Each Plans/*.md becomes a plan row (title from its heading, one-line goal); the file's text is not stored.
  2. Decisions whose ADR names a plan file ("Plan: `Plans/x.md`") are linked into that plan.
  3. Specs and gap items that belong to today's plans are linked into them.
  4. A decision whose text names a component (sb-fleet) is linked "applies_to" that component, noted as inferred
     so it can be confirmed or ended. Every step is idempotent; re-running adds nothing twice.
  Images next to the plans are not imported; a plan row can point at them in its goal or a note.
#>
param(
    [string] $Project = "sbos",
    [string] $ViberUrl = "http://localhost:8088",
    [string] $Token = $env:VIBER_TOKEN,
    [string] $PlansDir = "E:\MyWorx\sbos-v3\sb-orchestration\Plans",
    [string] $AdrFile = "E:\MyWorx\sbos-v3\sb-orchestration\Implementation\Architecture\ADR.md"
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if (-not $Token) { throw "Set VIBER_TOKEN or pass -Token" }
$headers = @{ Authorization = "Bearer $Token"; "X-Viber-Actor" = "import-plans" }
$base = "$ViberUrl/v1/projects/$Project"

function Send([string] $Path, $Body, [string] $Method = "Post") {
    $json = $Body | ConvertTo-Json -Depth 6 -Compress
    try { Invoke-RestMethod -Method $Method -Uri "$base$Path" -Headers $headers -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($json)) }
    catch { throw "POST $Path failed: $($_.Exception.Message). Body: $($json.Substring(0, [Math]::Min(300, $json.Length)))" }
}
function Get-Rows([string] $Path) { Invoke-RestMethod -Uri "$base$Path" -Headers $headers }

# 1. plan rows ------------------------------------------------------------------------------------------
$planKeyByFile = @{}
foreach ($f in Get-ChildItem $PlansDir -Filter *.md | Sort-Object Name) {
    $text = Get-Content $f.FullName -Raw -Encoding UTF8
    $title = if ($text -match '(?m)^#\s+(.+)$') { $Matches[1].Trim() } else { $f.BaseName }
    $goal = ""
    foreach ($para in ($text -split '(\r?\n){2,}')) {
        $p = ($para -replace '\s+', ' ').Trim()
        if ($p -and $p -notmatch '^(#|\||```|-|\*|>)' -and $p.Length -gt 40) { $goal = $p; break }
    }
    if ($goal.Length -gt 297) { $goal = $goal.Substring(0, 296).TrimEnd() + "…" }
    if ($title.Length -gt 200) { $title = $title.Substring(0, 199) }
    $key = "PLAN-" + ($f.BaseName -replace '^(\d{4}-\d{2}-\d{2})-', '$1-')
    $r = Send "/plans" @{ key = $key; title = $title; goal = $goal; status = "Active"; source = "sbos-plans"; source_ref = $f.Name }
    $planKeyByFile[$f.Name] = $key
    "{0,-60} {1}" -f $key, $(if ($r.created) { "new" } else { "already there" })
}

# 2. decisions that name a plan file --------------------------------------------------------------------
$adr = Get-Content $AdrFile -Raw -Encoding UTF8
$decisionKeys = @()
foreach ($block in ([regex]::Split($adr, '(?m)^(?=## ADR-)') | Where-Object { $_ -match '^## ADR-' })) {
    $key = ([regex]::Match($block, '^## (ADR-[\w\.\-]+)')).Groups[1].Value
    $decisionKeys += $key
    foreach ($m in [regex]::Matches($block, 'Plans/([\w\-\.]+\.md)')) {
        $plan = $planKeyByFile[$m.Groups[1].Value]
        if ($plan) { [void](Send "/plans/$plan/members" @{ members = @(@{ type = "decision"; key = $key }) }); "{0} -> {1}" -f $key, $plan }
    }
}

# 3. today's specs and gap items -> their plans ----------------------------------------------------------
$specs = Invoke-RestMethod -Uri "$base/specs?limit=500" -Headers $headers
function Add-Specs([string] $PlanFile, [string[]] $Groups) {
    $plan = $planKeyByFile[$PlanFile]; if (-not $plan) { return }
    $members = New-Object System.Collections.ArrayList
    foreach ($s in $specs) {
        foreach ($g in $Groups) {
            if ([string]$s.source_ref -like "$g#*") { [void]$members.Add(@{ type = "spec"; key = [string]$s.key }); break }
        }
    }
    if ($members.Count) { [void](Send "/plans/$plan/members" @{ members = @($members) }); "{0}: {1} specs" -f $plan, $members.Count }
}
Add-Specs "2026-11-25-settings-split-and-edition-defaults.md" @("sbos-settings", "sbos-settings-todo", "sbos-editions")
Add-Specs "2026-11-25-live-update-plan.md" @("sbos-live-update", "sbos-signing-todo")
Add-Specs "2026-11-23-v3-console-and-billing.md" @("sbos-billing", "sbos-billing-todo")
Add-Specs "2026-11-25-v2-under-the-control-plane.md" @("sbos-process")
$gapMembers = New-Object System.Collections.ArrayList
foreach ($i in (Invoke-RestMethod -Uri "$base/items?limit=500" -Headers $headers)) {
    if ($i.area -eq "release-2606") { [void]$gapMembers.Add(@{ type = "item"; key = [string]$i.key }) }
}
$livePlan = $planKeyByFile["2026-11-25-live-update-plan.md"]
if ($livePlan -and $gapMembers.Count) { [void](Send "/plans/$livePlan/members" @{ members = @($gapMembers) }); "{0}: {1} gap items" -f $livePlan, $gapMembers.Count }

# 4. decisions that name a component ----------------------------------------------------------------------
$components = New-Object System.Collections.ArrayList
foreach ($c in (Invoke-RestMethod -Uri "$base/components?limit=500" -Headers $headers)) { if ([string]$c.key -match '^sb-') { [void]$components.Add([string]$c.key) } }
$linked = 0
foreach ($key in $decisionKeys) {
    $d = Invoke-RestMethod -Uri "$base/adr/$key" -Headers $headers
    $body = (@($d.title) + $d.context + $d.decision + $d.alternatives + $d.consequences) -join " "
    foreach ($c in $components) {
        if ($body -match "(?<![\w-])$([regex]::Escape($c))(?![\w-])") {
            $r = Send "/refs" @{ from_type = "decision"; from_key = $key; relation = "applies_to"; to_type = "component"; to_key = $c
                                 note = "inferred: the ADR names this component; confirm or end"; source = "sbos-plans"; source_ref = "mention" }
            if ($r.created) { $linked++ }
        }
    }
}
"{0} decision -> component links (inferred from mentions)" -f $linked
