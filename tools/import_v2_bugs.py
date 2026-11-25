"""Load Second Brain v2's BUGS.md into Viber as items kind bug (source tag v2-bugs).

MODE=dry (default) | apply | verify.   Idempotent by key and by source+source_ref.
Index table rows give title/area/severity/status/found/fixed-by; the `### BUG-NNN` subsection goes whole into `details`.
A bug only in the details (no index row) is imported from the subsection's own bullet lines and reported.
"""
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
from v2_common import *  # noqa: F401,F403

SOURCE = "v2-bugs"
FILE = "BUGS.md"
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
STATUS_WORDS = ("In Sprint", "Won't Fix", "Wont Fix", "Closed", "Fixed", "Open", "Accepted")


def clean(cell: str) -> str:
    return cell.strip()


def parse_index(lines):
    rows = {}
    for number, line in enumerate(lines, start=1):
        if not re.match(r"^\|\s*BUG-\d+\s*\|", line):
            continue
        cells = line.strip().strip("|").split("|")
        if len(cells) > 7:
            cells = [cells[0], "|".join(cells[1:len(cells) - 5])] + cells[-5:]
        if len(cells) < 7:
            cells += [""] * (7 - len(cells))
        key = clean(cells[0])
        if key in rows:
            say("DUPLICATE index row", key, "lines", rows[key]["line"], number)
            continue
        rows[key] = {"line": number, "title": clean(cells[1]), "area": clean(cells[2]), "severity": clean(cells[3]),
                     "status": clean(cells[4]), "found": clean(cells[5]), "fixed_by": clean(cells[6])}
    return rows


def parse_details(lines):
    heads = [(i, re.match(r"^### (BUG-\d+)\s*(?:[—–-]+\s*)?(.*)$", line)) for i, line in enumerate(lines)]
    heads = [(i, m) for i, m in heads if m]
    out, duplicates = {}, []
    for position, (start, match) in enumerate(heads):
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].startswith("## ") or (position + 1 < len(heads) and j == heads[position + 1][0]):
                end = j
                break
        body = lines[start + 1:end]
        while body and body[-1].strip() in ("", "---"):
            body.pop()
        key = match.group(1)
        if key in out:
            duplicates.append(key)
            continue
        out[key] = {"line": start + 1, "heading": lines[start][4:].strip(), "title": match.group(2).strip(), "body": "\n".join(body).strip("\n")}
    return out, duplicates


def bullet(body: str, name: str) -> str:
    found = re.search(r"^- \*\*" + name + r":\*\*\s*(.*(?:\n(?!- \*\*|\S).*)*)", body, re.M)
    return " ".join(found.group(1).split()) if found else ""


def first_status(text: str) -> str:
    for word in STATUS_WORDS:
        if text.lower().startswith(word.lower()):
            return word if word != "Wont Fix" else "Won't Fix"
    return text.split(" — ")[0][:40]


def main():
    lines = fix_mojibake(read_text(FILE)).split("\n")
    index, details_dups = None, None
    index = parse_index(lines)
    details, details_dups = parse_details(lines)
    only_index = sorted(set(index) - set(details))
    only_details = sorted(set(details) - set(index))
    say(f"index rows {len(index)}, detail subsections {len(details)} (duplicate headings: {details_dups or 'none'})")
    say("in index but no detail subsection:", only_index or "none")
    say("in details but not in the index:", len(only_details), only_details)
    numbers = sorted(int(k[4:]) for k in set(index) | set(details))
    say("id range", numbers[0], "-", numbers[-1], "missing numbers:", [n for n in range(numbers[0], numbers[-1] + 1) if n not in numbers] or "none")

    records, notes = [], []
    for key in sorted(set(index) | set(details), key=lambda k: int(k[4:])):
        row, detail = index.get(key), details.get(key)
        body = detail["body"] if detail else ""
        title = row["title"] if row else detail["title"]
        area = (row["area"] if row else bullet(body, "Area")) or None
        severity = (row["severity"] if row else bullet(body, "Severity")) or None
        detail_status = bullet(body, "Status")
        status = row["status"] if row else first_status(detail_status) or "Open"
        found_text = row["found"] if row else bullet(body, "Found")
        found = DATE.search(found_text or "")
        fixed_by = row["fixed_by"] if row else ""
        if row and detail and detail_status and first_status(detail_status).lower() != status.lower():
            notes.append((key, "index status", status, "detail status", first_status(detail_status)))
        data = {"fixed_by": fixed_by, "in_index": bool(row), "has_detail": bool(detail), "found_text": found_text[:200]}
        if detail_status:
            data["detail_status"] = " ".join(detail_status.split())[:300]
        if detail:
            data["detail_line"] = detail["line"]
        if row:
            data["index_line"] = row["line"]
        details_text = (f"Heading in BUGS.md: {detail['heading']}\n\n" + body) if detail else f"No detail subsection in BUGS.md. Index row only (line {row['line']})."
        if len(title) > 400:
            details_text = "Full title: " + title + "\n\n" + details_text
            title = title[:397] + "..."
        record = {"kind": "bug", "key": key, "title": title, "status": status, "details": details_text, "data": data,
                  "source": SOURCE, "source_ref": key}
        if area:
            record["area"] = area
        if severity:
            record["severity"] = severity
        if fixed_by:
            record["body"] = ("Fixed by: " + fixed_by)[:500]
        if found:
            record["found_on"] = found.group(0)
        records.append(record)
    statuses = {}
    for record in records:
        statuses[record["status"]] = statuses.get(record["status"], 0) + 1
    say("bugs to import:", len(records), "statuses", statuses)
    say("index vs detail status differences:", len(notes), notes[:8])

    # BACKLOG.md '## Bugs' mirror for the cross-check
    mirror = set(re.findall(r"^\| (BUG-\d+) \|", fix_mojibake(read_text("BACKLOG.md")), re.M))
    say(f"BACKLOG.md Bugs mirror lists {len(mirror)} ids; not in BUGS.md at all: {sorted(mirror - set(index) - set(details)) or 'none'};"
        f" in BUGS.md but not in mirror: {len((set(index) | set(details)) - mirror)}")

    if MODE in ("dry", "apply"):
        totals = import_batches("items", SOURCE, records, size=10)
        say(f"items: sent {totals['sent']} created {totals['created']} skipped {totals['skipped']} invalid {len(totals['invalid'])}")
        for problem in totals["invalid"]:
            say("  INVALID", problem)
    if MODE in ("verify", "apply"):
        rows = list_items()
        mine = [r for r in rows if r.get("source") == SOURCE]
        have = {r["key"] for r in mine}
        want = {r["key"] for r in records}
        say(f"VERIFY bugs: in file {len(want)}, rows in Viber with source {SOURCE} {len(mine)}, missing {sorted(want - have) or 'none'}, extra {sorted(have - want) or 'none'}")
        empty = []
        for record in records:
            status, view = call("GET", f"/v1/projects/{PROJECT}/items/{record['key']}", ok_404=True)
            if status != 200 or not view.get("points"):
                empty.append(record["key"])
        say("VERIFY bugs with no stored detail rows:", empty or "none")


main()
