"""Import Second Brain v2 UserStories/*.md into Viber (idempotent). Dry run by default; --apply writes.

Per story file:
  item kind=story, key = story id as written, source v2-stories, source_ref = file name
  body    = "As a <who>, I want <what>" (one line); details = the rest of the file, one source line per statement
  spec kind=acceptance per Gherkin scenario: key <story>-AC-NN (one row when it fits in 400 characters; otherwise the row
          holds the scenario title and children <story>-AC-NN.1, .2 ... hold the Given / When / Then groups, parent_key set)
  ref   spec(AC) verifies item(story)
Scenario text is the AC; any non-Gherkin text in the section goes to the story's details.
"""
import re
import sys

import v2lib as L

SOURCE = "v2-stories"
SPEC_MAX = 400


def wrap(text: str, limit: int):
    pieces, current = [], ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > limit:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        pieces.append(current)
    return pieces


def split_scenarios(ac_text: str):
    """[(heading, fenced gherkin lines, other text)] plus the text before the first scenario heading."""
    preface, scenarios, current, fenced = [], [], None, False
    for line in ac_text.split("\n"):
        is_fence = line.lstrip().startswith("```")
        if not fenced and line.startswith("### "):
            current = {"heading": line[4:].strip(), "gherkin": [], "other": []}
            scenarios.append(current)
        elif current is None:
            preface.append(line)
        elif is_fence:
            fenced = not fenced
        elif fenced:
            current["gherkin"].append(line.strip())
        else:
            current["other"].append(line)
    return "\n".join(preface), scenarios


def step_groups(lines):
    """Group Gherkin lines into Given / When / Then blocks (And / But stay with their block)."""
    groups = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"(Given|When|Then|Scenario|Background|Examples)\b", line) or not groups:
            groups.append(line)
        else:
            groups[-1] += " " + line
    return groups


def ac_rows(story_id: str, scenarios):
    """List of dicts: key, statement, parent_key, ref (source_ref suffix)."""
    rows = []
    for number, scenario in enumerate(scenarios, start=1):
        key = f"{story_id}-AC-{number:02d}"
        heading = " ".join(scenario["heading"].split())
        groups = step_groups(scenario["gherkin"])
        whole = " ".join([heading + "."] + groups).strip() if groups else heading
        if len(whole) <= SPEC_MAX:
            rows.append({"key": key, "statement": whole, "parent_key": None, "ref": f"AC-{number:02d}"})
            continue
        rows.append({"key": key, "statement": " ".join(wrap(heading, SPEC_MAX)[:1]), "parent_key": None, "ref": f"AC-{number:02d}"})
        child = 0
        for group in groups:
            for piece in wrap(group, SPEC_MAX):
                child += 1
                rows.append({"key": f"{key}.{child}", "statement": piece, "parent_key": key, "ref": f"AC-{number:02d}.{child}"})
        if len(wrap(heading, SPEC_MAX)) > 1:  # a heading longer than 400 characters: the rest becomes a child row
            for piece in wrap(heading, SPEC_MAX)[1:]:
                child += 1
                rows.append({"key": f"{key}.{child}", "statement": piece, "parent_key": key, "ref": f"AC-{number:02d}.{child}"})
    return rows


def parse_story(name: str):
    meta, body = L.read_file("UserStories", name)
    story_id = meta["id"]
    kept, ac_notes, scenarios = [], [], []
    for heading, text in L.sections(body):
        if heading.startswith("## Acceptance Criteria"):
            preface, scenarios = split_scenarios(text)
            if preface.strip():
                ac_notes.append(preface)
            for scenario in scenarios:
                if "\n".join(scenario["other"]).strip():
                    ac_notes.append(f"{scenario['heading']}: " + "\n".join(scenario["other"]))
            kept.append(heading + "\n" + (f"(The {len(scenarios)} scenarios of this section are stored as acceptance specs "
                                          f"{story_id}-AC-01 to {story_id}-AC-{len(scenarios):02d}.)" if scenarios else "")
                        + ("\n" + "\n".join(ac_notes) if ac_notes else ""))
        else:
            kept.append((heading + "\n" if heading else "") + text)
    details = L.to_details("\n".join(kept))
    story_section = next((t for h, t in L.sections(body) if h.startswith("## Story")), "")
    match = re.search(r"\*\*As an?\*\*\s*(.*?)\s*\*\*I want\*\*\s*(.*?)\s*\*\*So that\*\*", story_section, re.S)
    summary = (f"As a {L.one_line(match.group(1), 150)}, I want {L.one_line(match.group(2), 300)}" if match
               else L.first_paragraph(story_section))
    status = L.story_status(meta.get("status", ""))
    ids = meta.get("requirement_ids") or []
    record = {
        "kind": "story", "key": story_id, "title": meta["title"][:400], "body": summary[:500], "details": details,
        "status": status, "lane": "standard", "area": meta.get("phase") or None,
        "gate": meta.get("gate") if meta.get("gate") in ("clear", "flagged") else "clear",
        "gate_reason": meta.get("gate_reason") or None, "found_on": L.date_or_none(meta.get("created")),
        "source": SOURCE, "source_ref": name,
        "data": L.clean_data(v2_status=meta.get("status"), requirement_ids=ids, requirement_section=meta.get("requirement_section"),
                             phase=meta.get("phase"), sprint=meta.get("sprint"), created=meta.get("created"),
                             updated=meta.get("updated"), file=name),
    }
    return {"meta": meta, "record": record, "ac": ac_rows(story_id, scenarios), "scenarios": len(scenarios)}


def main():
    real, templates = L.list_files("UserStories")
    print(f"UserStories: {len(real)} story files, templates skipped: {templates}")
    parsed = [parse_story(name) for name in real]
    ids = [p["record"]["key"] for p in parsed]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    print("duplicate ids:", duplicates or "none")
    totals = L.bulk_items(SOURCE, [p["record"] for p in parsed], "stories")
    rows = [(p, r) for p in parsed for r in p["ac"]]
    too_long = [r["key"] for _, r in rows if len(r["statement"]) > SPEC_MAX or not r["statement"]]
    print(f"AC rows: {len(rows)} ({sum(p['scenarios'] for p in parsed)} scenarios), unusable rows: {too_long or 'none'}")
    if not L.APPLY:
        print("dry run: no specs or refs written (use --apply)")
        return
    made = skipped = failed = linked = 0
    for p, row in rows:
        story = p["record"]
        body = {"statement": row["statement"], "kind": "acceptance", "key": row["key"], "parent_key": row["parent_key"],
                "status": {"Done": "Built", "Dropped": "Dropped"}.get(story["status"], "Draft"),
                "source": SOURCE, "source_ref": f"{story['source_ref']}#{row['ref']}"}
        status, result = L.call("POST", f"/v1/projects/{L.PROJECT}/specs", body)
        if status == 201:
            made += result.get("created", False)
            skipped += not result.get("created", False)
        else:
            failed += 1
            print("   spec failed", row["key"], status, str(result)[:200])
            continue
        if row["parent_key"] is None:
            status, result = L.post_ref("spec", row["key"], "verifies", "item", story["key"], SOURCE, f"{story['source_ref']}#{row['ref']}")
            if status == 201:
                linked += result.get("created", False)
            else:
                print("   ref failed", row["key"], status, str(result)[:200])
    print(f"[acceptance specs] created {made}, already there {skipped}, failed {failed}; verifies links created {linked}")


if __name__ == "__main__":
    main()
