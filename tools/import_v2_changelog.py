"""Import Second Brain v2's CHANGELOG.md into Viber as changes (source `v2-changelog`).

One entry (a `## DATE - title` heading and its body) becomes one change. Dry-run by default; pass --apply to write.
Run: docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v E:\\MyWorx:/work:ro python:3.12-slim python /work/Viber/tools/import_v2_changelog.py [--apply]
"""
import collections
import re
import sys

import v2_import_lib as lib

SOURCE = "v2-changelog"
COMPONENT = "second_brain"
FILE = "CHANGELOG.md"

DATED = re.compile(r"^>?##\s+(\d{4}-\d\d-\d\d)\s*(.*)$")
SEPARATOR = re.compile(r"^(?:-{1,2}|[\u2013\u2014]|\u00e2\S*)\s*")  # "-", "--", an en/em dash (or a mangled one)
RELEASE = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s+--\s+(\d{4}-\d\d-\d\d)\s*(.*)$")
SUBDATE = re.compile(r"^###\s+(\d{4}-\d\d-\d\d)\s*$")
UNRELEASED = re.compile(r"^##\s+\[Unreleased\]\s*$")
KIND_PREFIX = re.compile(r"^\s*[-*]\s+(feat|fix|docs|refactor|chore)\b[^:\n]*:")
BUG = re.compile(r"\bBUG-\d+")


def parse():
    lines = lib.read_lines(FILE)
    entries, dropped, anomalies = [], [], []
    current = None
    last_date = None
    in_comment = False
    for number, line in enumerate(lines, start=1):
        if in_comment:
            dropped.append((number, "html-comment (format template)", line.strip()[:60]))
            in_comment = "-->" not in line
            continue
        if line.strip().startswith("<!--"):
            dropped.append((number, "html-comment (format template)", line.strip()[:60]))
            in_comment = "-->" not in line
            continue
        entry = None
        m = DATED.match(line)
        r = RELEASE.match(line)
        s = SUBDATE.match(line)
        if m:
            date, rest = m.group(1), m.group(2)
            had_separator = bool(SEPARATOR.match(rest))
            title = SEPARATOR.sub("", rest, count=1).strip()
            if not had_separator and rest:
                anomalies.append((number, "heading without a dash separator", line[:100]))
            if not title:
                anomalies.append((number, "dated heading with no title", line[:100]))
                title = f"Changes of {date}"
            entry = {"date": date, "title": title, "version": None, "kind_of_heading": "dated"}
            if line.startswith(">"):
                anomalies.append((number, "heading inside a blockquote (imported as an entry)", line[:100]))
        elif r:
            entry = {"date": r.group(2), "title": f"Release {r.group(1)} {r.group(3)}".strip(), "version": r.group(1),
                     "kind_of_heading": "release"}
            anomalies.append((number, "release heading, not a dated entry (version kept)", line[:100]))
        elif s:
            entry = {"date": s.group(1), "title": f"Changes recorded on {s.group(1)}", "version": None, "kind_of_heading": "subdate"}
            anomalies.append((number, "### date section inside the 0.1.0 entry (imported as its own entry)", line[:100]))
        elif UNRELEASED.match(line):
            entry = {"date": last_date, "title": "Unreleased", "version": None, "kind_of_heading": "unreleased"}
            anomalies.append((number, f"[Unreleased] heading has no date; dated {last_date} (the entry before it)", line[:100]))
        if entry:
            entry["line"] = number
            entry["body"] = []
            entries.append(entry)
            current = entry
            if entry["date"]:
                last_date = entry["date"]
            continue
        if line.startswith("## ") or line.startswith(">## "):
            anomalies.append((number, "level-2 heading not recognised as an entry (kept in the previous entry's body)", line[:100]))
        if current is None:
            dropped.append((number, "file preamble", line.strip()[:60]))
            continue
        if line.strip() == ">":
            dropped.append((number, "lone '>' line", ">"))
            continue
        current["body"].append(line)
    return lines, entries, dropped, anomalies


def build(entries):
    records, refs_seen = [], collections.Counter()
    for entry in entries:
        body = "\n".join(entry["body"]).strip("\n")
        kinds = {m.group(1) for line in entry["body"] if (m := KIND_PREFIX.match(line))}
        kind = kinds.pop() if len(kinds) == 1 else "change"
        title = entry["title"]
        base = f"{entry['date']}:{lib.short_hash(title)}"
        refs_seen[base] += 1
        ref = base if refs_seen[base] == 1 else f"{base}:{refs_seen[base]}"
        record = {"summary": title[:400], "occurred_on": entry["date"], "kind": kind, "details": body,
                  "component_key": COMPONENT, "source": SOURCE, "source_ref": ref}
        if entry["version"]:
            record["version"] = entry["version"]
        records.append(record)
    return records


def main():
    apply = "--apply" in sys.argv
    lines, entries, dropped, anomalies = parse()
    records = build(entries)
    expected_points = sum(len(lib.atoms.split_atoms(r["details"], lib.atoms.POINT_MAX)) for r in records)
    mojibake_left = [n for n, l in enumerate(lines, 1) if lib.has_mojibake(l)]
    cites = [e for e in entries if BUG.search(e["title"])]
    long_titles = [e["line"] for e in entries if len(e["title"]) > 400]
    print(f"file lines {len(lines)}  entries {len(entries)}  records {len(records)}  expected change_point rows {expected_points}")
    print(f"entries citing a BUG-NNN in the heading: {len(cites)}  (kept in the summary text)")
    print(f"summary > 400 chars: {long_titles}")
    print(f"empty-body entries: {[e['line'] for e in entries if not any(b.strip() for b in e['body'])]}")
    print(f"mojibake still present after repair (line numbers): {mojibake_left[:20]} total {len(mojibake_left)}")
    print("dropped lines (not part of any entry):")
    for item in dropped:
        print("  ", item)
    print("anomalies:")
    for item in anomalies:
        print("  ", item)
    totals = lib.send("changes", SOURCE, records, apply)
    print(f"{'APPLY' if apply else 'DRY-RUN'}: created {totals['created']} skipped {totals['skipped']} invalid {len(totals['invalid'])}")
    for index, error in totals["invalid"][:30]:
        print("  invalid", entries[index]["line"], error)


if __name__ == "__main__":
    main()
