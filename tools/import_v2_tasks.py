"""Import Second Brain v2 Tasks/*.md into Viber (idempotent). Dry run by default; --apply writes.

Per task file: item kind=task, key = task id as written, source v2-tasks, source_ref = file name,
body = first paragraph of the Objective, details = the whole file body (one source line per statement for tables and
code, paragraphs kept together), status mapped, area = task type (backend/frontend/...), gate and gate_reason kept.
Refs: task `refines` its parent story (item -> item); task `depends_on` each task named in depends_on.
Run import_v2_stories.py first so the stories exist.
"""
import re

import v2lib as L

SOURCE = "v2-tasks"


def parse_task(name: str):
    meta, body = L.read_file("Tasks", name)
    objective = next((t for h, t in L.sections(body) if h.startswith("## Objective")), "")
    summary = L.first_paragraph(objective) or L.first_paragraph(body)
    depends = meta.get("depends_on") or []
    record = {
        "kind": "task", "key": meta["id"], "title": meta["title"][:400], "body": L.one_line(summary, 500),
        "details": L.to_details(body), "status": L.story_status(meta.get("status", "")), "lane": "standard",
        "area": meta.get("type") or None, "gate": meta.get("gate") if meta.get("gate") in ("clear", "flagged") else "clear",
        "gate_reason": meta.get("gate_reason") or None, "found_on": L.date_or_none(meta.get("created")),
        "source": SOURCE, "source_ref": name,
        "data": L.clean_data(v2_status=meta.get("status"), parent_story=meta.get("parent_story"),
                             requirement_id=meta.get("requirement_id"), type=meta.get("type"), depends_on=depends,
                             phase=meta.get("phase"), sprint=meta.get("sprint"), created=meta.get("created"),
                             updated=meta.get("updated"), file=name),
    }
    return {"meta": meta, "record": record, "parent": meta.get("parent_story"), "depends": depends}


def main():
    real, templates = L.list_files("Tasks")
    print(f"Tasks: {len(real)} task files, templates skipped: {templates}")
    parsed = [parse_task(name) for name in real]
    ids = [p["record"]["key"] for p in parsed]
    print("duplicate ids:", sorted({i for i in ids if ids.count(i) > 1}) or "none")
    truncated = [p["record"]["key"] for p in parsed if len(p["meta"]["title"]) > 400]
    print("titles truncated to 400:", truncated or "none")
    file_stories = {L.read_file("UserStories", n)[0]["id"] for n in L.list_files("UserStories")[0]}
    orphans = [(p["record"]["key"], p["parent"]) for p in parsed if p["parent"] not in file_stories]
    print("orphan tasks (parent story has no file):", orphans or "none")
    missing_dep = [(p["record"]["key"], d) for p in parsed for d in p["depends"] if d not in set(ids)]
    print("depends_on naming no task file:", missing_dep or "none")
    L.bulk_items(SOURCE, [p["record"] for p in parsed], "tasks")
    if not L.APPLY:
        print("dry run: no refs written (use --apply)")
        return
    made = {"refines": 0, "depends_on": 0}
    failed = 0
    for p in parsed:
        key, ref = p["record"]["key"], p["record"]["source_ref"]
        wanted = [("refines", p["parent"], f"{ref}#refines")] + [("depends_on", d, f"{ref}#depends:{d}") for d in p["depends"]]
        for relation, target, source_ref in wanted:
            if not target:
                continue
            status, result = L.post_ref("item", key, relation, "item", target, SOURCE, source_ref)
            if status == 201:
                made[relation] += result.get("created", False)
            else:
                failed += 1
                print("   ref failed", key, relation, target, status, str(result)[:160])
    print(f"[task links] created {made}, failed {failed}")


if __name__ == "__main__":
    main()
