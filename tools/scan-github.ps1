<#
.SYNOPSIS
  Scans GitHub repos with the gh CLI and posts their manifests to Viber (read-only on GitHub).
.DESCRIPTION
  For each repo: reads the file tree, asks Viber's /discover endpoint which components it holds
  (one per repo by default; a monorepo without a root manifest is split by directory), creates
  those components, scans each at the default branch head, then scans up to -MaxTags tags.
  Manifests read: pyproject.toml, package.json, plugin.json, Chart.yaml, VERSION (root only).
.EXAMPLE
  .\tools\scan-github.ps1 -Project sbos -Owner zeemoussa-dev -Repos sb-core,sb-platform -MaxTags 3
#>
param(
    [Parameter(Mandatory)] [string] $Project,
    [Parameter(Mandatory)] [string] $Owner,
    [Parameter(Mandatory)] [string[]] $Repos,
    [string] $ViberUrl = "http://localhost:8088",
    [string] $Token = $env:VIBER_TOKEN,
    [int] $MaxTags = 3
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Invoke-Viber([string] $Method, [string] $Path, $Body) {
    $headers = @{ "X-Viber-Actor" = "scan-github" }
    if ($Token) { $headers["Authorization"] = "Bearer $Token" }
    $uri = "$ViberUrl$Path"
    if ($null -eq $Body) { return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers }
    $json = $Body | ConvertTo-Json -Depth 8 -Compress
    return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($json))
}

function Get-RepoFile([string] $Repo, [string] $File, [string] $Ref) {
    # A missing manifest is a normal 404; stderr must not become a terminating error here.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = gh api "repos/$Owner/$Repo/contents/$File`?ref=$Ref" -H "Accept: application/vnd.github.raw" 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return ($lines -join "`n")
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Get-ComponentFiles([string] $Repo, $Component, [string] $Ref) {
    # Keys are relative to the component's own directory so the server sees one component's manifests.
    $files = @{}
    foreach ($manifestPath in $Component.manifests) {
        $text = Get-RepoFile $Repo $manifestPath $Ref
        if ($null -eq $text) { continue }
        $relative = if ($Component.path) { $manifestPath.Substring($Component.path.Length + 1) } else { $manifestPath }
        $files[$relative] = $text
    }
    return $files
}

function Invoke-ScanOrReport([string] $ComponentKey, [hashtable] $Body, [string] $Label) {
    try {
        return Invoke-Viber Post "/v1/projects/$Project/components/$ComponentKey/scan" $Body
    } catch {
        $detail = $_.ErrorDetails.Message
        Write-Host ("  {0}: not scanned ({1})" -f $Label, ($detail -replace "\s+", " ").Substring(0, [Math]::Min(110, $detail.Length)))
        return $null
    }
}

foreach ($repo in $Repos) {
    try {
        $info = gh api "repos/$Owner/$repo" | ConvertFrom-Json
        $branch = $info.default_branch
        $headSha = (gh api "repos/$Owner/$repo/commits/$branch" | ConvertFrom-Json).sha
        $tree = gh api "repos/$Owner/$repo/git/trees/$branch`?recursive=1" | ConvertFrom-Json
        $paths = @(($tree.tree | Where-Object { $_.type -eq "blob" }) | ForEach-Object { $_.path })
        $plan = Invoke-Viber Post "/v1/projects/$Project/discover" @{ repo = $repo; paths = $paths }
        $components = @($plan.components)
        if ($components.Count -eq 0) { Write-Host "SKIP  $repo (no manifests found)"; continue }
        $tags = @((gh api "repos/$Owner/$repo/tags" | ConvertFrom-Json) | Where-Object { $_.name } | Select-Object -First $MaxTags)
        foreach ($component in $components) {
            try {
                Invoke-Viber Post "/v1/projects/$Project/components" @{
                    key = $component.key; repo = "$Owner/$repo"; path = $component.path; kind = $component.kind } | Out-Null
            } catch { if ($_.Exception.Response.StatusCode.value__ -ne 409) { throw } }
            $headFiles = Get-ComponentFiles $repo $component $branch
            $head = Invoke-ScanOrReport $component.key @{ ref = $branch; commit_sha = $headSha; is_tag = $false; files = $headFiles } "head"
            if ($head) {
                Write-Host ("HEAD  {0,-40} {1,-10} {2,-7} deps={3,-3} links={4}" -f $component.key, $head.semver, $component.kind, $head.dependencies, $head.links_from_manifests)
            } else { Write-Host ("SKIP  {0,-40} {1}" -f $component.key, $component.kind) }
            foreach ($tag in $tags) {
                $tagFiles = Get-ComponentFiles $repo $component $tag.name
                if ($tagFiles.Count -eq 0) { continue }
                $scan = Invoke-ScanOrReport $component.key @{ ref = $tag.name; commit_sha = $tag.commit.sha; is_tag = $true; files = $tagFiles } "tag $($tag.name)"
                if ($scan) { Write-Host ("  TAG {0,-12} -> {1}" -f $tag.name, $scan.semver) }
            }
        }
        foreach ($skipped in @($plan.ignored)) { Write-Host ("  ignored {0} ({1})" -f $skipped.path, $skipped.reason) }
    } catch {
        Write-Host "FAIL  $repo : $($_.Exception.Message)"
    }
}
