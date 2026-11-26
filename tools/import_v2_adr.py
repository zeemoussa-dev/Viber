"""Load Second Brain v2's ADR.md into Viber as decisions (source tag v2-adr) plus supersedes/refines refs.

MODE=dry (default) | apply | verify.   Idempotent by key and by source+source_ref.
"""
import os
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
from v2_common import *  # noqa: F401,F403

SOURCE = "v2-adr"
# v2 keeps two decision files: ADR.md (ADR-NNN) and ADR-v2.md (ADR-v2.NNN). Same layout; run once for each.
FILE = os.environ.get("ADR_FILE", "Implementation/Architecture/ADR.md")
HEADING = re.compile(r"^## ADR-(\S+?): (.*)$")
LABEL = re.compile(r"^\*\*([^*\n]{1,90}?):\*\*\s*(.*)$")
CONTEXT_LABELS = {"context"}
DECISION_LABELS = {"decision"}
ALT_LABELS = {"alternatives considered", "alternatives", "rejected", "options considered"}
CONS_LABELS = {"consequences", "consequences and known gaps"}
REF_LABELS = {"builds on": ("refines", "builds on"), "extends": ("refines", "extends"), "amends": ("refines", "amends"),
              "supersedes": ("supersedes", "supersedes")}
ID = re.compile(r"ADR-(v\d+\.\d+|\d+)")


def parse(text: str):
    lines = text.split("\n")
    heads, in_comment, in_fence = [], False, False
    for number, line in enumerate(lines):
        if line.startswith("```"):
            in_fence = not in_fence
        if not in_fence:
            if "<!--" in line and "-->" not in line:
                in_comment = True
            if in_comment:
                if "-->" in line:
                    in_comment = False
                continue
            if "<!--" in line:
                continue
        if not in_fence and HEADING.match(line):
            heads.append(number)
    entries = []
    for position, start in enumerate(heads):
        end = heads[position + 1] if position + 1 < len(heads) else len(lines)
        entries.append((start + 1, lines[start:end]))
    return entries


def build(line_number: int, block: list, ordinal: dict):
    number, title = HEADING.match(block[0]).groups()
    heading_key = "ADR-" + number
    ordinal[heading_key] = ordinal.get(heading_key, 0) + 1
    duplicate = ordinal[heading_key] > 1
    key = heading_key + ("b" if duplicate else "")
    sections, order, current, in_fence = {}, [], None, False
    meta = {"status": "", "date": ""}
    for raw in block[1:]:
        if raw.startswith("```"):
            in_fence = not in_fence
        label = None if in_fence else LABEL.match(raw)
        if not in_fence and not label and re.match(r"^\*\*Decision \d+\b", raw):
            current = ("Decision", len(order))
            order.append(["Decision", [raw]])
            continue
        if label:
            name, rest = label.group(1).strip(), label.group(2)
            low = name.lower()
            if low == "status":
                meta["status"] = rest.strip(); current = ("status", None); continue
            if low == "date":
                meta["date"] = rest.strip(); current = ("date", None); continue
            current = (name, len(order))
            order.append([name, [rest]])
            continue
        if raw.strip() == "---" and not in_fence:
            current = current if current and current[0] in ("status", "date") else current
            continue
        if current is None:
            current = ("(lead)", len(order))
            order.append(["(lead)", []])
        if current[0] == "status":
            meta["status"] += "\n" + raw
        elif current[0] == "date":
            meta["date"] += "\n" + raw
        else:
            order[current[1]][1].append(raw)
    buckets = {"context": [], "decision": [], "alternatives": [], "consequences": []}
    refs = []
    for name, body in order:
        text = "\n".join(body).strip("\n")
        if not text.strip():
            continue
        low = name.lower()
        if low in DECISION_LABELS:
            buckets["decision"].append(text)
        elif low in ALT_LABELS:
            buckets["alternatives"].append(text if low == "alternatives considered" else f"{name}: {text}")
        elif low in CONS_LABELS:
            buckets["consequences"].append(text if low == "consequences" else f"{name}: {text}")
        elif low in CONTEXT_LABELS:
            buckets["context"].append(text)
        elif name == "(lead)":
            buckets["context"].append(text)
        else:
            buckets["context"].append(f"{name}: {text}")
            if low in REF_LABELS:
                refs.append((REF_LABELS[low], text.split("\n\n")[0]))
    status_text = " ".join(meta["status"].split())
    low = status_text.lower()
    superseded_by = None
    if low.startswith("superseded"):
        status = "Superseded"
        found = re.search(r"superseded by\s+`?ADR-(v\d+\.\d+|\d+)", status_text, re.I)
        superseded_by = "ADR-" + found.group(1) if found else None
    elif low.startswith("proposed"):
        status = "Proposed"
    elif low.startswith("rejected"):
        status = "Rejected"
    elif low.startswith("deprecated"):
        status = "Deprecated"
    elif low.startswith("accepted"):
        status = "Accepted"
    else:
        status = "Accepted"
    date = None
    for candidate in (meta["date"], status_text):
        found = re.search(r"\d{4}-\d{2}-\d{2}", candidate)
        if found:
            date = found.group(0)
            break
    data = {"status_text": status_text[:900], "heading_number": number, "line": line_number}
    if duplicate:
        data["duplicate_heading"] = heading_key
        data["note"] = f"second ADR in ADR.md that carries the heading {heading_key}; stored as {key}"
    record = {"key": key, "title": title.strip(), "status": status, "context": "\n".join(buckets["context"]),
              "decision": "\n\n".join(buckets["decision"]), "alternatives": "\n\n".join(buckets["alternatives"]),
              "consequences": "\n\n".join(buckets["consequences"]), "data": data,
              "source": SOURCE, "source_ref": key if not duplicate else f"{heading_key}#2"}
    if date:
        record["decided_on"] = date
    if superseded_by:
        record["superseded_by"] = superseded_by
    # everything between the heading and the next one, except Status/Date/--- , must be in a bucket
    sourced = sum(len(re.sub(r"\s+", "", line)) for line in block[1:] if line.strip() not in ("", "---")) \
        - len(re.sub(r"\s+", "", meta["status"])) - len(re.sub(r"\s+", "", meta["date"])) - 2 * 9
    kept = sum(len(re.sub(r"\s+", "", record[name])) for name in buckets)
    return record, refs, sourced, kept


def main():
    text = fix_mojibake(read_text(FILE))
    entries = parse(text)
    ordinal, records, refs_by_key, lost = {}, [], {}, []
    for line_number, block in entries:
        record, refs, sourced, kept = build(line_number, block, ordinal)
        records.append(record)
        refs_by_key[record["key"]] = refs
        if kept < sourced * 0.93:
            lost.append((record["key"], line_number, sourced, kept))
    keys = {r["key"] for r in records}
    by_number = {}
    for record in records:
        by_number.setdefault(record["data"]["heading_number"], record["key"])  # first heading wins for a duplicated number
    # supersedes field on the superseding side
    for record in records:
        if record.get("superseded_by"):
            target = by_number.get(record["superseded_by"].replace("ADR-", ""))
            for other in records:
                if other["key"] == target and not other.get("supersedes"):
                    other["supersedes"] = record["key"]
    statuses = {}
    for record in records:
        statuses[record["status"]] = statuses.get(record["status"], 0) + 1
    say(f"ADR headings parsed: {len(records)} (template heading skipped); statuses {statuses}")
    say("duplicate headings:", [r["key"] + " (line %d)" % r["data"]["line"] for r in records if "duplicate_heading" in r["data"]])
    say("sections possibly losing text:", lost or "none")
    no_decision = [r["key"] for r in records if not r["decision"]]
    say("ADRs with no Decision section:", no_decision or "none")
    oversize = [r["key"] for r in records if len(r["title"]) > 400]
    say("titles over 400:", oversize or "none")

    if MODE in ("dry", "apply"):
        totals = import_batches("decisions", SOURCE, records, size=10)
        say(f"decisions: sent {totals['sent']} created {totals['created']} skipped {totals['skipped']} invalid {len(totals['invalid'])}")
        for problem in totals["invalid"]:
            say("  INVALID", problem)

    # refs ---------------------------------------------------------------------------------------------
    wanted, unmapped = [], []
    exists_cache = {}

    def exists(key):
        if key in keys:
            return True
        if key not in exists_cache:
            exists_cache[key] = call("GET", f"/v1/projects/{PROJECT}/adr/{key}", ok_404=True)[0] == 200
        return exists_cache[key]

    for record in records:
        if record.get("superseded_by"):
            target = by_number.get(record["superseded_by"].replace("ADR-", ""), record["superseded_by"])
            wanted.append((target, "supersedes", record["key"], "Status line: Superseded by " + record["superseded_by"]))
        for (relation, label), text in refs_by_key[record["key"]]:
            for found in dict.fromkeys(ID.findall(text)):
                target = by_number.get(found, "ADR-" + found) if found.isdigit() else "ADR-" + found
                if target == record["key"]:
                    continue
                if not exists(target):
                    unmapped.append((record["key"], label, "ADR-" + found))
                    continue
                if relation == "supersedes":
                    wanted.append((record["key"], "supersedes", target, "Supersedes: line (may be partial; read the ADR)"))
                else:
                    wanted.append((record["key"], "refines", target, label))
    seen, final = set(), []
    for item in wanted:
        if item[:3] not in seen:
            seen.add(item[:3]); final.append(item)
    say(f"refs wanted: {len(final)}  (supersedes {sum(1 for f in final if f[1]=='supersedes')}, refines {sum(1 for f in final if f[1]=='refines')});"
        f" references with no ADR row in Viber: {len(unmapped)}")
    if MODE == "apply":
        made = skipped = failed = 0
        for source_key, relation, target, note in final:
            status, answer = call("POST", f"/v1/projects/{PROJECT}/refs", {
                "from_type": "decision", "from_key": source_key, "relation": relation, "to_type": "decision", "to_key": target,
                "note": note[:200], "source": SOURCE, "source_ref": f"{source_key}|{relation}|{target}"})
            if status in (200, 201):
                if answer.get("created"):
                    made += 1
                else:
                    skipped += 1
            else:
                failed += 1
                say("  REF FAILED", source_key, relation, target, status, answer)
        say(f"refs: created {made} skipped {skipped} failed {failed}")
    if unmapped:
        grouped = {}
        for source_key, label, target in unmapped:
            grouped.setdefault(target, []).append(source_key)
        say("unresolvable references (target not in ADR.md or Viber):", {k: v[:4] for k, v in sorted(grouped.items())})

    # verification -------------------------------------------------------------------------------------
    if MODE in ("verify", "apply"):
        missing, thin = [], []
        for record in records:
            status, view = call("GET", f"/v1/projects/{PROJECT}/adr/{record['key']}", ok_404=True)
            if status != 200:
                missing.append(record["key"]); continue
            stored = sum(len(re.sub(r"\s+", "", p)) for name in ("context", "decision", "alternatives", "consequences") for p in view[name])
            wantedlen = sum(len(re.sub(r"\s+", "", record[name])) for name in ("context", "decision", "alternatives", "consequences"))
            if stored < wantedlen * 0.9:
                thin.append((record["key"], stored, wantedlen))
        say(f"VERIFY decisions: in file {len(records)}, found in Viber {len(records) - len(missing)}, missing {missing or 'none'}; thinner than source {thin or 'none'}")


main()
