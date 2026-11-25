<#
.SYNOPSIS
  Restores a Viber backup file into a database.
.DESCRIPTION
  By default it restores into a separate database called viber_restored, which is safe: it touches nothing live, so you can
  look at the result. To replace the live database pass -Database viber and -Yes; the API is stopped while it is replaced
  and started again afterwards, and the meaning vectors are rebuilt by the background sync.
.EXAMPLE
  .\tools\restore-backup.ps1 -File backups\viber-20261126-101500.dump
  .\tools\restore-backup.ps1 -File backups\viber-20261126-101500.dump -Database viber -Yes
#>
param(
    [Parameter(Mandatory)] [string] $File,
    [string] $Database = "viber_restored",
    [switch] $Yes
)
$ErrorActionPreference = "Continue"   # Windows PowerShell 5.1 turns a native command's progress text into errors; the exit code decides instead
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path $File)) { throw "No such backup file: $File" }
if ($Database -eq "viber" -and -not $Yes) { throw "This replaces the live database. Add -Yes to confirm, or restore into another database first (the default)." }
if ($Database -notmatch '^[a-z_][a-z0-9_]*$') { throw "Database names are lowercase letters, digits and underscores." }

function Invoke-Step([string] $What, [scriptblock] $Command) {
    & $Command 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -and $_ -notmatch '^\s*(viber-db-1\s+Copying|Container )' } | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}

$live = $Database -eq "viber"
$full = (Resolve-Path $File).Path
try {
    Invoke-Step "Copying the backup into the database container" { docker compose cp $full db:/tmp/restore.dump }
    if ($live) { Invoke-Step "Stopping the API" { docker compose stop api } }
    Invoke-Step "Making a fresh database" { docker compose exec -T db psql -U viber -d postgres -c "DROP DATABASE IF EXISTS $Database WITH (FORCE)" -c "CREATE DATABASE $Database" }
    Invoke-Step "Restoring" { docker compose exec -T db pg_restore -U viber -d $Database --no-owner --exit-on-error /tmp/restore.dump }
    Invoke-Step "Counting" { docker compose exec -T db psql -U viber -d $Database -t -A -c "select 'restored: ' || (select count(*) from item) || ' items, ' || (select count(*) from fact) || ' facts, ' || (select count(*) from decision) || ' decisions, ' || (select count(*) from spec) || ' specs'" }
} finally {
    docker compose exec -T db rm -f /tmp/restore.dump 2>&1 | Out-Null
    if ($live) { docker compose start api 2>&1 | Out-Null }
}
if (-not $live) { Write-Host "Restored into the separate database '$Database'. Drop it when you are done: docker compose exec -T db psql -U viber -d postgres -c `"DROP DATABASE $Database`"" }
