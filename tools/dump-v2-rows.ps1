<#
.SYNOPSIS  Dumps (read-only) the Viber rows the v2 importers wrote, plus all fact/rule texts, to tools\out\db-dump.json for verify_v2_import.py.
#>
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$OutputEncoding = New-Object Text.UTF8Encoding($false)
$out = "E:\MyWorx\Viber\tools\out\db-dump.json"
$sql = @'
select json_build_object(
 'facts', (select coalesce(json_agg(json_build_object('source',source,'ref',source_ref,'text',text)),'[]'::json) from fact),
 'rules', (select coalesce(json_agg(json_build_object('source',source,'ref',source_ref,'text',text,'status',status,'category',category)),'[]'::json) from rule),
 'changes', (select coalesce(json_agg(json_build_object('source',source,'ref',source_ref,'id',id,'on',occurred_on,'summary',summary)),'[]'::json) from change where source = 'v2-changelog'),
 'change_points', (select count(*) from change_point where change_id in (select id from change where source = 'v2-changelog'))
)
'@
$json = $sql | docker exec -i viber-db-1 psql -U viber -d viber -t -A -q
[IO.File]::WriteAllText($out, ($json -join "`n"), (New-Object Text.UTF8Encoding($false)))
"wrote $out ($((Get-Item $out).Length) bytes)"
