"""Load Second Brain v2's ESCALATIONS.md and REVIEW-QUEUE.md into Viber as items (source tags v2-escalations, v2-review-queue).

MODE=dry (default) | apply | verify.   Idempotent by key and by source+source_ref.
ESC-NNN entries keep their key. Review-queue entries have no id: Viber allocates a key, the source_ref is a hash of the entry's first line.
Status Resolved is stored as Closed (the raw word is kept in data.source_status). gate is flagged only for entries that are still Open and say "flagged".
"""
import hashlib
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
from v2_common import *  # noqa: F401,F403

SPIKE_CATEGORIES = {"unclear-requirement", "adr-deviation", "new-dependency", "shared-interface-change"}
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def flag_reason(text: str):
    found = re.search(r"[^.\n]*\bflagged\b[^.\n]*", text, re.I)
    return " ".join(found.group(0).split())[:200] if found else None


def escalations():
    lines = fix_mojibake(read_text("ESCALATIONS.md")).split("\n")
    heads, in_comment = [], False
    for i, line in enumerate(lines):
        if "<!--" in line:
            in_comment = "-->" not in line
            continue
        if in_comment:
            in_comment = "-->" not in line
            continue
        if re.match(r"^## ESC-\d+:", line):
            heads.append(i)
    records = []
    for n, start in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        block = lines[start:end]
        while block and block[-1].strip() in ("", "---"):
            block.pop()
        head = re.match(r"^## (ESC-\d+):\s*(.*)$", block[0])
        key, title = head.group(1), head.group(2).strip()
        date = re.search(r"\s[—–-]\s*(\d{4}-\d{2}-\d{2})\s*$", title)
        found_on = date.group(1) if date else None
        if date:
            title = title[:date.start()].strip()
        text = "\n".join(block[1:]).strip("\n")
        category = re.search(r"^\*\*Category:\*\*\s*(\S+)", text, re.M)
        category = category.group(1).strip(" .,;") if category else None
        status_raw = re.search(r"^\*\*Status:\*\*\s*(.*)$", text, re.M)
        status_raw = status_raw.group(1).strip() if status_raw else ""
        resolved = status_raw.lower().startswith("resolved")
        details = ("Full title: " + head.group(2).strip() + "\n\n" if len(title) > 400 else "") + text
        record = {"kind": "spike" if category in SPIKE_CATEGORIES else "chore", "key": key, "title": title[:400], "lane": "standard",
                  "status": "Closed" if resolved else (status_raw.split()[0] if status_raw else "Open"), "details": details,
                  "data": {"source_status": status_raw[:200], "category": category, "line": start + 1},
                  "source": "v2-escalations", "source_ref": key}
        if category:
            record["area"] = category
        if found_on:
            record["found_on"] = found_on
        reason = flag_reason(text)
        if reason:
            record["data"]["says_flagged"] = True
            if not resolved:
                record["gate"], record["gate_reason"] = "flagged", reason
        records.append(record)
    return records


def review_queue():
    lines = fix_mojibake(read_text("REVIEW-QUEUE.md")).split("\n")
    heads, in_comment = [], False
    for i, line in enumerate(lines):
        if "<!--" in line:
            in_comment = "-->" not in line
            continue
        if in_comment:
            in_comment = "-->" not in line
            continue
        if re.match(r"^- \[[ xX]\]", line):
            heads.append(i)
    records, seen = [], {}
    for n, start in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        block = lines[start:end]
        while block and block[-1].strip() == "":
            block.pop()
        first = block[0]
        done = first[3].lower() == "x"
        match = re.match(r"^- \[[ xX]\]\s*(\d{4}-\d{2}-\d{2})?\s*·?\s*(?:\*\*(.+?)\*\*)?\s*·?\s*(.*)$", first)
        date, story, summary = match.group(1), (match.group(2) or "").strip("` "), " ".join(match.group(3).split())
        digest = hashlib.sha1(first.encode("utf-8")).hexdigest()[:10]
        seen[digest] = seen.get(digest, 0) + 1
        source_ref = f"RQ:{digest}" + (f"#{seen[digest]}" if seen[digest] > 1 else "")
        text = "\n".join(block)
        decision_like = re.search(r"\b(decide|decision|how should|which|approve|review)\b", summary, re.I)
        record = {"kind": "spike" if decision_like else "chore", "title": (summary or story or first)[:400], "lane": "standard",
                  "status": "Closed" if done else "Open", "area": story[:80] or None,
                  "details": ("Full summary: " + summary + "\n\n" if len(summary) > 400 else "") + text,
                  "data": {"source_status": "[x]" if done else "[ ]", "story": story, "line": start + 1},
                  "source": "v2-review-queue", "source_ref": source_ref}
        if not record["area"]:
            del record["area"]
        if date:
            record["found_on"] = date
        reason = flag_reason(text)
        if reason:
            record["data"]["says_flagged"] = True
            if not done:
                record["gate"], record["gate_reason"] = "flagged", reason
        records.append(record)
    return records


def verify(records, source):
    rows = [r for r in list_items() if r.get("source") == source]
    say(f"VERIFY {source}: in file {len(records)}, rows in Viber {len(rows)}")
    if source == "v2-escalations":
        missing = sorted({r["key"] for r in records} - {r["key"] for r in rows})
        say("  missing:", missing or "none")
    empty = []
    for row in rows:
        status, view = call("GET", f"/v1/projects/{PROJECT}/items/{row['key']}", ok_404=True)
        if status != 200 or not view.get("points"):
            empty.append(row["key"])
    say("  rows with no stored detail rows:", empty or "none")


def main():
    for source, records in (("v2-escalations", escalations()), ("v2-review-queue", review_queue())):
        flagged = sum(1 for r in records if r.get("gate") == "flagged")
        resolved = sum(1 for r in records if r["status"] == "Closed")
        say(f"{source}: entries {len(records)} (closed/resolved {resolved}, open {len(records) - resolved}, gate flagged {flagged}); "
            f"kinds { {k: sum(1 for r in records if r['kind'] == k) for k in ('chore', 'spike')} }")
        if MODE in ("dry", "apply"):
            totals = import_batches("items", source, records, size=10)
            say(f"  items: sent {totals['sent']} created {totals['created']} skipped {totals['skipped']} invalid {len(totals['invalid'])}")
            for problem in totals["invalid"]:
                say("  INVALID", problem)
        if MODE in ("verify", "apply"):
            verify(records, source)


main()
