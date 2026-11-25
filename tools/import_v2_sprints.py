"""Import Second Brain v2 Sprints/*.md into Viber (idempotent). Dry run by default; --apply writes.

Per sprint file:
  plan  key = sprint id as written (SPRINT-026), title, goal = one line from "Sprint Goal", status mapped
        (Done->Done, Cancelled->Dropped, In Progress->Active, Draft/Ready->Draft), source v2-sprints
  item  kind=chore key <SPRINT>-NOTES: the whole sprint file (goal, rationale, stories table, retrospective, notes) as
        details, one statement per row; frontmatter fields (phase, sizing, dates, gate) in data and gate columns
  plan `contains`, in order: the NOTES item, then each story of the sprint (the "Stories in Scope" table, plus any story whose
        own frontmatter names the sprint) followed by its tasks (by id), then tasks that name the sprint themselves
  plan `depends_on` plan for depends_on_sprints
Run import_v2_stories.py and import_v2_tasks.py first so the members exist.
"""
import re

import v2lib as L

SOURCE = "v2-sprints"


def numeric_tail(key: str):
    return [int(n) for n in re.findall(r"\d+", key)] + [0]


def parse_sprint(name: str):
    meta, body = L.read_file("Sprints", name)
    goal_text = next((t for h, t in L.sections(body) if h.startswith("## Sprint Goal")), "")
    goal = L.one_line(L.first_paragraph(goal_text), 300)
    table_stories = []
    for heading, text in L.sections(body):
        if heading.startswith("## Stories in Scope"):
            table_stories = list(dict.fromkeys(re.findall(r"\[([A-Za-z0-9.-]+-US-\d+)\]", text)))
    status = meta.get("status", "")
    plan = {"key": meta["id"], "title": meta["title"][:200], "goal": goal, "status": L.plan_status(status),
            "source": SOURCE, "source_ref": name}
    notes = {
        "kind": "chore", "key": f"{meta['id']}-NOTES", "title": L.one_line(f"{meta['id']} notes and retrospective: {meta['title']}", 400),
        "body": L.one_line(goal_text and L.first_paragraph(goal_text) or meta["title"], 500), "details": L.to_details(body),
        "status": L.story_status(status), "lane": "standard", "area": meta.get("phase") or None,
        "gate": meta.get("gate") if meta.get("gate") in ("clear", "flagged") else "clear",
        "gate_reason": meta.get("gate_reason") or None, "found_on": L.date_or_none(meta.get("created")),
        "source": SOURCE, "source_ref": f"{name}#notes",
        "data": L.clean_data(sprint=meta["id"], v2_status=status, phase=meta.get("phase"), sizing_estimate=meta.get("sizing_estimate"),
                             depends_on_sprints=meta.get("depends_on_sprints"), created=meta.get("created"),
                             started=meta.get("started"), completed=meta.get("completed"), file=name),
    }
    return {"meta": meta, "plan": plan, "notes": notes, "table": table_stories, "goal_full": L.first_paragraph(goal_text)}


def main():
    real, templates = L.list_files("Sprints")
    print(f"Sprints: {len(real)} sprint files, templates skipped: {templates}")
    parsed = [parse_sprint(n) for n in real]
    ids = [p["plan"]["key"] for p in parsed]
    print("duplicate ids:", sorted({i for i in ids if ids.count(i) > 1}) or "none")
    print("titles cut to 200:", [p["plan"]["key"] for p in parsed if len(p["meta"]["title"]) > 200] or "none")
    print("goals cut to one line of 300:", sum(1 for p in parsed if len(p["goal_full"]) > 300), "of", len(parsed),
          "(the full goal text is in the NOTES item)")
    print("no goal found:", [p["plan"]["key"] for p in parsed if not p["goal_full"]] or "none")

    # who belongs to which sprint, from the story and task files themselves
    stories = {}
    for name in L.list_files("UserStories")[0]:
        meta, _ = L.read_file("UserStories", name)
        stories[meta["id"]] = meta.get("sprint") or ""
    tasks = {}
    for name in L.list_files("Tasks")[0]:
        meta, _ = L.read_file("Tasks", name)
        tasks[meta["id"]] = meta
    members = {}
    for p in parsed:
        sid = p["plan"]["key"]
        mine = list(p["table"]) + sorted((s for s, sp in stories.items() if sp == sid and s not in p["table"]), key=numeric_tail)
        unknown = [s for s in mine if s not in stories]
        if unknown:
            print(f"   {sid}: table names stories with no file: {unknown}")
        order = [p["notes"]["key"]]
        for story in (s for s in mine if s in stories):
            order.append(story)
            order += [t for t in sorted(tasks, key=numeric_tail) if tasks[t].get("parent_story") == story]
        order += [t for t in sorted(tasks, key=numeric_tail) if tasks[t].get("sprint") == sid and t not in order]
        members[sid] = list(dict.fromkeys(order))
    in_plan = {m for v in members.values() for m in v}
    print("stories in no sprint:", sorted(s for s in stories if s not in in_plan) or "none")
    print("tasks in no sprint (their story is in no sprint):", len([t for t in tasks if t not in in_plan]))
    multi = [s for s in stories if sum(1 for v in members.values() if s in v) > 1]
    print("stories in more than one sprint:", multi or "none")

    L.bulk_items(SOURCE, [p["notes"] for p in parsed], "sprint notes")
    if not L.APPLY:
        print("dry run: no plans, members or links written (use --apply)")
        return
    have = {k: set() for k in ("story", "task", "chore")}
    for kind in have:
        have[kind] = L.all_items(kind)
    item_keys = set().union(*have.values())
    created_plans = skipped_plans = added = failed = 0
    for p in parsed:
        status, result = L.call("POST", f"/v1/projects/{L.PROJECT}/plans", p["plan"])
        if status != 201:
            failed += 1
            print("   plan failed", p["plan"]["key"], status, str(result)[:200])
            continue
        created_plans += result["created"]
        skipped_plans += not result["created"]
        status, view = L.call("GET", f"/v1/projects/{L.PROJECT}/plans/{p['plan']['key']}")
        present = {r["key"] for r in view.get("item", [])} if status == 200 else set()
        todo = [{"type": "item", "key": k} for k in members[p["plan"]["key"]] if k in item_keys and k not in present]
        missing = [k for k in members[p["plan"]["key"]] if k not in item_keys]
        if missing:
            print(f"   {p['plan']['key']}: members not in Viber yet: {missing[:10]}")
        for start in range(0, len(todo), 100):
            status, result = L.call("POST", f"/v1/projects/{L.PROJECT}/plans/{p['plan']['key']}/members", {"members": todo[start:start + 100]})
            if status == 201:
                added += len(result["added"])
            else:
                failed += 1
                print("   members failed", p["plan"]["key"], status, str(result)[:200])
    print(f"[plans] created {created_plans}, already there {skipped_plans}, members added {added}, failures {failed}")
    deps = bad = 0
    for p in parsed:
        for dep in p["meta"].get("depends_on_sprints") or []:
            status, result = L.post_ref("plan", p["plan"]["key"], "depends_on", "plan", dep, SOURCE, f"{p['plan']['source_ref']}#depends:{dep}")
            if status == 201:
                deps += result.get("created", False)
            else:
                bad += 1
                print("   plan dependency failed", p["plan"]["key"], dep, status, str(result)[:160])
    print(f"[plan dependencies] created {deps}, failed {bad}")


if __name__ == "__main__":
    main()
