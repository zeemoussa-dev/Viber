<#
.SYNOPSIS
  Scans GitHub repos with the gh CLI and posts their manifests to Viber (read-only on GitHub).
.DESCRIPTION
  For each repo: ensures a component exists (key = repo name), scans the default branch head,
  then scans up to -MaxTags tags as released versions. Only root-level pyproject.toml and
  package.json are read in this version; one component per repo.
.EXAMPLE
  .\tools\scan-github.ps1 -Project sbos -Owner zeemoussa-dev -Repos sb-core,sb-memory -MaxTags 3
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
$ManifestNames = @("pyproject.toml", "package.json")

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

function Get-ManifestFiles([string] $Repo, [string] $Ref) {
    $files = @{}
    foreach ($name in $ManifestNames) {
        $text = Get-RepoFile $Repo $name $Ref
        if ($null -ne $text) { $files[$name] = $text }
    }
    return $files
}

foreach ($repo in $Repos) {
    try {
        $info = gh api "repos/$Owner/$repo" | ConvertFrom-Json
        $headSha = (gh api "repos/$Owner/$repo/commits/$($info.default_branch)" | ConvertFrom-Json).sha
        $files = Get-ManifestFiles $repo $info.default_branch
        if ($files.Count -eq 0) { Write-Host "SKIP  $repo (no root pyproject.toml/package.json)"; continue }
        try {
            Invoke-Viber Post "/v1/projects/$Project/components" @{ key = $repo; repo = "$Owner/$repo"; kind = "service" } | Out-Null
        } catch { if ($_.Exception.Response.StatusCode.value__ -ne 409) { throw } }
        $head = Invoke-Viber Post "/v1/projects/$Project/components/$repo/scan" @{
            ref = $info.default_branch; commit_sha = $headSha; is_tag = $false; files = $files }
        Write-Host ("HEAD  {0,-34} {1,-10} deps={2,-3} manifest-links={3}" -f $repo, $head.semver, $head.dependencies, $head.links_from_manifests)
        $tags = gh api "repos/$Owner/$repo/tags" | ConvertFrom-Json | Select-Object -First $MaxTags
        foreach ($tag in $tags) {
            $tagFiles = Get-ManifestFiles $repo $tag.name
            if ($tagFiles.Count -eq 0) { Write-Host "  tag $($tag.name): no manifest"; continue }
            $scan = Invoke-Viber Post "/v1/projects/$Project/components/$repo/scan" @{
                ref = $tag.name; commit_sha = $tag.commit.sha; is_tag = $true; files = $tagFiles }
            Write-Host ("  TAG {0,-12} -> {1}" -f $tag.name, $scan.semver)
        }
    } catch {
        Write-Host "FAIL  $repo : $($_.Exception.Message)"
    }
}
