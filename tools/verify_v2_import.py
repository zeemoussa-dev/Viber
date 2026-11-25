"""Coverage check for the v2 importers: what the files contain vs what Viber holds.

Needs tools/out/v2-memory-manifest.json (written by import_v2_memory.py) and tools/out/db-dump.json (dump-v2-rows.ps1).
Run: docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v E:\\MyWorx:/work:ro python:3.12-slim python /work/Viber/tools/verify_v2_import.py
"""
import collections
import json
import sys

import v2_import_lib as lib
import import_v2_changelog as changelog

OUT = f"{lib.WORK}/Viber/tools/out"
db = json.load(open(f"{OUT}/db-dump.json", encoding="utf-8"))
manifest = json.load(open(f"{OUT}/v2-memory-manifest.json", encoding="utf-8"))
problems = 0

# --- changelog ----------------------------------------------------------------------------------------------
lines, entries, dropped, anomalies = changelog.parse()
records = changelog.build(entries)
in_db = {c["ref"]: c for c in db["changes"]}
missing = [r["source_ref"] for r in records if r["source_ref"] not in in_db]
extra = sorted(set(in_db) - {r["source_ref"] for r in records})
points = sum(len(lib.atoms.split_atoms(r["details"], lib.atoms.POINT_MAX)) for r in records)
print(f"CHANGELOG.md: entries in file {len(records)} | in Viber {len(in_db)} | missing {len(missing)} | change_point rows {db['change_points']} (expected {points})")
problems += len(missing) + (db["change_points"] != points)

# --- memory-type files --------------------------------------------------------------------------------------
texts_by_kind = {"fact": collections.defaultdict(list), "rule": collections.defaultdict(list)}
for kind, key in (("fact", "facts"), ("rule", "rules")):
    for row in db[key]:
        texts_by_kind[kind][row["text"].lower()].append(row)
for source, info in manifest.items():
    ours = {"fact": {r["ref"]: r for r in db["facts"] if r["source"] == source},
            "rule": {r["ref"]: r for r in db["rules"] if r["source"] == source}}
    exp_rules, exp_facts = info["rules"], info["facts"]
    line = f"{info['file']}: statements {info['statements']} -> expected rules {len(exp_rules)} facts {len(exp_facts)} | in Viber rules {len(ours['rule'])} facts {len(ours['fact'])}"
    shortfalls = []
    for kind, group in (("rule", exp_rules), ("fact", exp_facts)):
        for record in group:
            if record["source_ref"] in ours[kind]:
                if ours[kind][record["source_ref"]]["text"] != record["text"]:
                    shortfalls.append((record["line"], kind, "TEXT DIFFERS", record["text"][:60]))
                continue
            holders = texts_by_kind[kind].get(record["text"].lower(), [])
            if holders:
                h = holders[0]
                shortfalls.append((record["line"], kind, f"identical text already stored by source '{h['source']}' ref {h['ref']}", record["text"][:60]))
            else:
                shortfalls.append((record["line"], kind, "MISSING", record["text"][:60]))
    real = [s for s in shortfalls if s[2] in ("MISSING", "TEXT DIFFERS")]
    problems += len(real)
    print(line)
    print(f"   not stored as a separate row because identical text exists: {len(shortfalls) - len(real)}; missing or different: {len(real)}; unaccounted lines in file: {info['uncovered_lines']}")
    for s in shortfalls:
        print("     ", s)
    if source in ("v2-memory", "v2-claude-md", "v2-pipeline"):
        status = collections.Counter(r["status"] for r in db["rules"] if r["source"] == source)
        print(f"   rule status: {dict(status)}")
print("PROBLEMS:", problems)
sys.exit(1 if problems else 0)
