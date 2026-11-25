"""Link each imported story to the requirement it names (idempotent; re-run until nothing is missing). --apply writes.

REQ-SB-NN in a story's requirement_ids  -> ref: item(story) implements spec(REQ-SB-NN)
BUG-N   in a story's requirement_ids    -> ref: item(story) implements item(BUG-NNN)   (bug-fix stories)
Prints the stories whose requirement does not exist in Viber yet. Cross-checks reports/backlog-links.json when present.
"""
import json
import os
import re

import v2lib as L

SOURCE = "v2-stories"


def main():
    names = L.list_files("UserStories")[0]
    wanted, missing, made, already = [], [], 0, 0
    cache = {}

    def exists(kind, key):
        if (kind, key) not in cache:
            path = f"/v1/projects/{L.PROJECT}/" + ("specs/" if kind == "spec" else "items/") + key
            cache[(kind, key)] = L.call("GET", path)[0] == 200
        return cache[(kind, key)]

    for name in names:
        meta, _ = L.read_file("UserStories", name)
        for rid in meta.get("requirement_ids") or []:
            bug = re.fullmatch(r"BUG-(\d+)", rid)
            if bug:
                kind, key = "item", f"BUG-{int(bug.group(1)):03d}"
            else:
                kind, key = "spec", rid
            wanted.append((meta["id"], name, kind, key, rid))
    print(f"stories: {len(names)}, requirement references: {len(wanted)}")
    for story, name, kind, key, rid in wanted:
        if not exists(kind, key):
            missing.append((story, rid))
            continue
        if L.APPLY:
            status, result = L.post_ref("item", story, "implements", kind, key, SOURCE, f"{name}#implements:{rid}")
            if status == 201:
                made += result.get("created", False)
                already += not result.get("created", False)
            else:
                print("   ref failed", story, key, status, str(result)[:160])
    print(f"[implements links] {'APPLIED' if L.APPLY else 'DRY RUN'}: created {made}, already there {already}, requirement missing {len(missing)}")
    for story, rid in missing:
        print("   missing:", story, "->", rid)
    report = "/work/Viber/tools/reports/backlog-links.json"
    if os.path.exists(report):
        with open(report, encoding="utf-8") as handle:
            data = json.load(handle)["requirements"]
        files = {L.read_file("UserStories", n)[0]["id"] for n in names}
        listed = {s for r in data.values() for s in r.get("stories", [])}
        print("backlog-links.json: stories listed there with no story file:", sorted(listed - files) or "none")
        print("backlog-links.json: story files not listed there:", sorted(files - listed) or "none")


if __name__ == "__main__":
    main()
