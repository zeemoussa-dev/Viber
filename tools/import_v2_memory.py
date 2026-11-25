"""Import Second Brain v2's standing knowledge into Viber as proposed rules and facts.

Files and their source tags:
  MEMORY.md                                        v2-memory                 rules (bullets/numbered with a normative cue), facts (the rest)
  CLAUDE.md                                        v2-claude-md              same
  Implementation/Pipeline.md                       v2-pipeline               same
  Implementation/Learnings.md                      v2-learnings              facts only (trust agent), one statement per bullet
  Implementation/Architecture/MEMORY-hermes-archive.md  v2-memory-hermes-archive   facts only (retired Hermes rules, kept for history)

A statement is a bullet, a numbered item, a table row (with its header names), a paragraph or a code block.
Long statements are packed by sentence (rule: first piece is the rule, the rest become facts).
Dry-run by default; --apply writes. If /out exists a manifest of expected rows is written there for verify_v2_import.py.
Run: docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v E:\\MyWorx:/work:ro -v E:\\MyWorx\\Viber\\tools\\out:/out python:3.12-slim python /work/Viber/tools/import_v2_memory.py [--apply]
"""
import collections
import json
import os
import re
import sys

import v2_import_lib as lib

FILES = [
    {"file": "MEMORY.md", "source": "v2-memory", "mode": "rules", "trust": "work", "label": "v2 MEMORY.md"},
    {"file": "CLAUDE.md", "source": "v2-claude-md", "mode": "rules", "trust": "work", "label": "v2 CLAUDE.md",
     "fact_sections": r"^(Project|Status|Commands|Roadmap Phases|Source Module Layout)\b"},
    {"file": "Implementation/Pipeline.md", "source": "v2-pipeline", "mode": "rules", "trust": "work", "label": "v2 Pipeline.md"},
    {"file": "Implementation/Learnings.md", "source": "v2-learnings", "mode": "facts", "trust": "agent", "label": "v2 Learnings.md"},
    {"file": "Implementation/Architecture/MEMORY-hermes-archive.md", "source": "v2-memory-hermes-archive", "mode": "facts",
     "trust": "agent", "label": "v2 MEMORY-hermes-archive.md"},
]

CUE = re.compile(r"\b(never|always|must|do not|don't|cannot|can't|may not|forbidden|refus\w*|only|requires?|required|should|avoid|"
                 r"prefer|ensure|before|use|keep|check|no|ask|update|read|create|record|put|write|name|add|run|set|make|"
                 r"take|treat|verify|wait|stop|start)\b|\bnot\b", re.I)
HARD = re.compile(r"\b(never|must|do not|don't|cannot|can't|may not|forbidden|refus\w*|always|not allowed|no one)\b", re.I)


def pack(text: str, limit: int) -> list[str]:
    """Sentence-pack a single-line statement into pieces of at most `limit` characters (the server splitter, minus bullets)."""
    if len(text) <= limit:
        return [text]
    pieces, current = [], ""
    for sentence in lib.atoms._SENTENCE_END.split(text):
        for piece in lib.atoms._wrap(sentence, limit):
            if current and len(current) + 1 + len(piece) > limit:
                pieces.append(current)
                current = piece
            else:
                current = f"{current} {piece}".strip()
    if current:
        pieces.append(current)
    return pieces


def subject_of(cfg, block) -> str:
    heading = [h for h in block["path"][1:]] or block["path"][:1]
    tail = " > ".join(heading[-2:]) if heading else ""
    label = cfg["file"].split("/")[-1]
    return f"{label}: {tail}"[:200] if tail else label


def prefix_of(cfg, block) -> str:
    """Learnings facts carry their sprint and section so a recalled row stands on its own."""
    if cfg["source"] != "v2-learnings":
        return ""
    path = block["path"]
    sprint = path[1] if len(path) > 1 else "Learnings"
    section = path[2].split("(")[0].strip() if len(path) > 2 else ""
    return f"[{sprint}{' / ' + section if section else ''}] "


def convert(cfg, blocks):
    """Blocks -> list of record dicts {kind: rule|fact, ...record fields, _block: first line}."""
    records, per_ref = [], collections.Counter()
    for block in blocks:
        text = block["text"]
        if not text:
            continue
        base_ref = f"L{block['start']}:{lib.short_hash(text, 8)}"
        per_ref[base_ref] += 1
        subject = subject_of(cfg, block)
        heading = block["path"][-1] if block["path"] else ""
        is_rule = False
        if cfg["mode"] == "rules":
            in_fact_section = bool(cfg.get("fact_sections") and re.match(cfg["fact_sections"], heading))
            if block["kind"] == "numbered" and not in_fact_section:
                is_rule = True
            elif block["kind"] == "bullet" and not in_fact_section and CUE.search(text):
                is_rule = True
        if is_rule:
            pieces = pack(text, lib.atoms.RULE_MAX)
            category = "constraint" if HARD.search(pieces[0]) else "pattern"
            records.append({"kind": "rule", "text": pieces[0], "category": category, "scope": "project", "status": "proposed",
                            "proposed_by": "import", "source": cfg["source"], "source_ref": base_ref, "line": block["start"]})
            for n, extra in enumerate(pieces[1:], start=2):
                records.append({"kind": "fact", "text": extra, "subject": subject, "scope": "project", "trust": cfg["trust"],
                                "source": cfg["source"], "source_ref": f"{base_ref}#{n}", "line": block["start"]})
            continue
        prefix = prefix_of(cfg, block)
        pieces = pack(text, lib.atoms.FACT_MAX - len(prefix))
        for n, piece in enumerate(pieces, start=1):
            records.append({"kind": "fact", "text": prefix + piece, "subject": subject, "scope": "project", "trust": cfg["trust"],
                            "source": cfg["source"], "source_ref": base_ref if n == 1 else f"{base_ref}#{n}", "line": block["start"]})
    dup_refs = [r for r, c in per_ref.items() if c > 1]
    return records, dup_refs


def payload(record):
    return {k: v for k, v in record.items() if k not in ("kind", "line")}


def main():
    apply = "--apply" in sys.argv
    manifest = {}
    grand = collections.Counter()
    for cfg in FILES:
        lines = lib.read_lines(cfg["file"])
        blocks, skipped = lib.parse_blocks(lines)
        uncovered = lib.coverage(lines, blocks, skipped)
        records, dup_refs = convert(cfg, blocks)
        rules = [r for r in records if r["kind"] == "rule"]
        facts = [r for r in records if r["kind"] == "fact"]
        by_kind = collections.Counter(b["kind"] for b in blocks)
        by_section = collections.defaultdict(lambda: collections.Counter())
        for block in blocks:
            by_section[block["path"][1] if len(block["path"]) > 1 else (block["path"][0] if block["path"] else "(preamble)")][block["kind"]] += 1
        by_section_rows = collections.defaultdict(collections.Counter)
        line_to_section = {b["start"]: (b["path"][1] if len(b["path"]) > 1 else (b["path"][0] if b["path"] else "(preamble)")) for b in blocks}
        for record in records:
            by_section_rows[line_to_section[record["line"]]][record["kind"]] += 1
        skipped_kinds = collections.Counter(reason for _, reason, _ in skipped)
        print(f"\n=== {cfg['file']}  -> {cfg['source']}")
        print(f"lines {len(lines)}  statements {len(blocks)} {dict(by_kind)}  rows: rules {len(rules)} facts {len(facts)}")
        print(f"not statements (structure/comments): {dict(skipped_kinds)}; lines unaccounted for: {uncovered}")
        print(f"mojibake left: {[n for n, l in enumerate(lines, 1) if lib.has_mojibake(l)][:10]}  "
              f"longer than limits before packing: {sum(1 for b in blocks if len(b['text']) > 400)} over 400")
        if dup_refs:
            print(f"identical statements at the same line: {dup_refs}")
        texts = collections.Counter((r['kind'], r['text'].lower()) for r in records)
        dupes = [(k, t[:60]) for (k, t), c in texts.items() if c > 1]
        if dupes:
            print(f"statements repeated inside this file (the server stores one): {len(dupes)}  e.g. {dupes[:3]}")
        for section, counts in by_section_rows.items():
            print(f"   {section[:70]:70} rules {counts['rule']:3} facts {counts['fact']:3}")
        expected_rules = len({r["text"].lower() for r in rules})
        manifest[cfg["source"]] = {"file": cfg["file"], "statements": len(blocks), "rules": rules, "facts": facts,
                                   "uncovered_lines": uncovered}
        for kind, group, endpoint in (("rules", rules, "rules"), ("facts", facts, "facts")):
            totals = lib.send(endpoint, cfg["source"], [payload(r) for r in group], apply)
            print(f"   {'APPLY' if apply else 'DRY-RUN'} {kind}: sent {len(group)} created {totals['created']} skipped {totals['skipped']} invalid {len(totals['invalid'])}")
            for index, error in totals["invalid"][:10]:
                print("      invalid line", group[index]["line"], error[:200])
            grand[f"{kind} created"] += totals["created"]
            grand[f"{kind} skipped"] += totals["skipped"]
            grand[f"{kind} invalid"] += len(totals["invalid"])
    print("\nTOTAL", dict(grand))
    if os.path.isdir("/out"):
        with open("/out/v2-memory-manifest.json", "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False)
        print("manifest written to /out/v2-memory-manifest.json")


if __name__ == "__main__":
    main()
