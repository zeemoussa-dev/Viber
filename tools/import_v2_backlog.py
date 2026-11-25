"""Load Second Brain v2's BACKLOG.md requirement tables into Viber as specs (kind requirement, source tag v2-backlog).

MODE=dry (default; nothing written, only checks) | apply | verify.
Key = Req ID as written (REQ-SB-01). source_ref = BACKLOG:<req>. Story and sprint ids go to
Viber/tools/reports/backlog-links.json (needs /work/Viber/tools/reports mounted read-write in apply mode, see REPORTS_DIR).
The '## Sprint Status', '## Bugs' and '## Security' tables are derived or not requirements and are skipped (counted).
"""
import json
import os
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
from v2_common import *  # noqa: F401,F403

SOURCE = "v2-backlog"
FILE = "BACKLOG.md"
REPORTS = os.environ.get("REPORTS_DIR", "/reports")


def spec_status(raw: str) -> str:
    text = re.sub(r"[*`]", "", raw).strip().lower()
    for prefix, status in (("done", "Built"), ("built", "Built"), ("closed", "Built"), ("superseded", "Dropped"), ("withdrawn", "Dropped"),
                           ("cancel", "Dropped"), ("locked", "Agreed"), ("ready", "Agreed")):
        if text.startswith(prefix):
            return status
    return "Draft"


def main():
    lines = fix_mojibake(read_text(FILE)).split("\n")
    section, rows, odd, skipped_tables = None, [], [], {}
    for number, line in enumerate(lines, start=1):
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if re.match(r"^REQ-[A-Z]+-\d+$", cells[0]):
            if len(cells) != 6:
                odd.append((number, len(cells), line[:80]))
                if len(cells) > 6:
                    # a `|` inside the Story Status text (code spans like `GET /x` | `PUT /x`) splits it; re-join it
                    cells = cells[:3] + ["|".join(cells[3:len(cells) - 2])] + cells[-2:]
                else:
                    cells += [""] * (6 - len(cells))
            rows.append((number, section, cells))
        elif not re.match(r"^[-: |]+$", line) and cells[0] not in ("Req ID", "Sprint", "ID"):
            skipped_tables[section] = skipped_tables.get(section, 0) + 1
    say(f"requirement rows: {len(rows)}; rows not 6 columns: {odd or 'none'}; skipped derived table rows by section: {skipped_tables}")
    ids = [c[0] for _, _, c in rows]
    say("duplicate Req IDs:", sorted({i for i in ids if ids.count(i) > 1}) or "none")
    by_section = {}
    for _, name, _ in rows:
        by_section[name] = by_section.get(name, 0) + 1
    say("by section:", by_section)

    records, links, long_rows = [], {}, []
    for number, name, cells in rows:
        req, description, story, story_status, sprint, sprint_status = cells
        statement = " ".join(description.split())
        if len(statement) > 400 or not statement:
            long_rows.append((req, number, len(statement)))
            statement = statement[:397] + "..." if statement else req
        records.append({"statement": statement, "kind": "requirement", "key": req, "status": spec_status(story_status),
                        "source": SOURCE, "source_ref": f"BACKLOG:{req}"})
        links[req] = {"priority": name, "line": number, "description": " ".join(description.split()),
                      "stories": list(dict.fromkeys(re.findall(r"\b[A-Z]+-[A-Z]*-?\d+-US-\d+\b|\bBUGFIX-\d+-US-\d+\b", story))),
                      "sprints": list(dict.fromkeys(re.findall(r"SPRINT-\d+", sprint))),
                      "story_cell": story, "story_status": story_status, "sprint_cell": sprint, "sprint_status": sprint_status,
                      "spec_status": spec_status(story_status)}
    say("statements over 400 chars (truncated in Viber, full text in the links file):", long_rows or "none")
    counts = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    say("status mapping:", counts, "| without any story id:", sum(1 for v in links.values() if not v["stories"]),
        "| without sprint:", sum(1 for v in links.values() if not v["sprints"]))

    created = skipped = failed = 0
    if MODE == "apply":
        for record in records:
            status, answer = call("POST", f"/v1/projects/{PROJECT}/specs", record)
            if status in (200, 201):
                created += 1 if answer.get("created") else 0
                skipped += 0 if answer.get("created") else 1
            else:
                failed += 1
                say("  SPEC FAILED", record["key"], status, answer)
        say(f"specs: created {created} skipped {skipped} failed {failed}")
        if os.path.isdir(REPORTS):
            with open(os.path.join(REPORTS, "backlog-links.json"), "w", encoding="utf-8") as handle:
                json.dump({"source": SOURCE, "source_file": FILE, "count": len(links), "requirements": links}, handle, ensure_ascii=False, indent=1)
            say("wrote", os.path.join(REPORTS, "backlog-links.json"))
        else:
            say("REPORTS_DIR not mounted; links file NOT written")
    else:
        clash = [r["key"] for r in records if call("GET", f"/v1/projects/{PROJECT}/specs/{r['key']}", ok_404=True)[0] == 200]
        say("dry run: validation only; keys already present in Viber:", clash or "none")

    if MODE in ("verify", "apply"):
        # GET /specs lists at most 500 rows ordered by key, so read each key (the single-row read has no source_ref)
        want = {r["key"]: r for r in records}
        mine, wrong = {}, []
        for key, record in want.items():
            status, row = call("GET", f"/v1/projects/{PROJECT}/specs/{key}", ok_404=True)
            if status == 200:
                mine[key] = row
                if row["statement"] != record["statement"] or row["status"] != record["status"]:
                    wrong.append(key)
        say(f"VERIFY specs: in file {len(want)}, found in Viber by key {len(mine)}, missing {sorted(set(want) - set(mine)) or 'none'}, "
            f"differing statement/status {wrong or 'none'}")


main()
