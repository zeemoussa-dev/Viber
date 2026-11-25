"""Coverage check for the v2 stories / tasks / sprints import. Read-only. Prints per folder: files, rows in Viber, missing,
fidelity (stored text vs sent text vs source text), links.
Run: docker run --rm -v E:\\MyWorx:/work:ro python:3.12-slim python /work/Viber/tools/verify_v2_work_import.py
"""
import re

import import_v2_sprints as SP
import import_v2_stories as ST
import import_v2_tasks as TK
import v2lib as L


def alnum(text: str) -> int:
    return len(re.findall(r"[^\W_]", text, re.UNICODE))


def item(key):
    status, row = L.call("GET", f"/v1/projects/{L.PROJECT}/items/{key}")
    return row if status == 200 else None


def fidelity(label, expected):
    """expected: {key: (sent_details, source_alnum, extra_alnum_held_elsewhere)}"""
    gone, bad = [], []
    for key, (sent, source_total, extra) in expected.items():
        row = item(key)
        if not row:
            gone.append(key)
            continue
        stored = alnum("\n".join(row["points"]))
        # the server drops list markers ("1." / "2)") when it splits statements, so ignore those digits on the sent side
        sent_count = alnum(re.sub(r"(?m)^\s*\d+[.)]\s+", "", sent))
        if stored != sent_count:
            bad.append((key, "sent", sent_count, "stored", stored))
        elif source_total - (stored + extra) > 40:  # source text that is neither stored nor held as an acceptance spec
            bad.append((key, "source", source_total, "stored+specs", stored + extra))
    print(f"[{label}] items missing: {len(gone)} {gone[:5]}; text mismatches: {len(bad)} {bad[:6]}")


def main():
    real, tpl = L.list_files("UserStories")
    parsed = [ST.parse_story(n) for n in real]
    have = {r["key"] for r in L.call("GET", f"/v1/projects/{L.PROJECT}/items?kind=story&limit=1000")[1] if r["source"] == "v2-stories"}
    want = {p["record"]["key"] for p in parsed}
    print(f"UserStories: files {len(real) + len(tpl)} (templates skipped {tpl}) -> stories expected {len(want)}, in Viber {len(have & want)}, missing {sorted(want - have)}")
    expected, ac_bad, verifies_missing, impl = {}, [], [], 0
    for p in parsed:
        r = p["record"]
        _, body = L.read_file("UserStories", r["source_ref"])
        ac_text = next((t for h, t in L.sections(body) if h.startswith("## Acceptance Criteria")), "")
        extra = alnum(" ".join(f"{s['heading']} " + " ".join(s["gherkin"]) for s in ST.split_scenarios(ac_text)[1]))
        expected[r["key"]] = (r["details"], alnum(body), extra)
        for row in p["ac"]:
            status, spec = L.call("GET", f"/v1/projects/{L.PROJECT}/specs/{row['key']}")
            if status != 200 or spec["statement"] != " ".join(row["statement"].split()):
                ac_bad.append(row["key"])
        status, links = L.call("GET", f"/v1/projects/{L.PROJECT}/refs?type=item&key={r['key']}")
        ver = {l["key"] for l in links["links_in"] if l["relation"] == "verifies"}
        verifies_missing += [row["key"] for row in p["ac"] if row["parent_key"] is None and row["key"] not in ver]
        impl += sum(1 for l in links["links_out"] if l["relation"] == "implements")
    print(f"  acceptance specs expected {sum(len(p['ac']) for p in parsed)} ({sum(p['scenarios'] for p in parsed)} scenarios), "
          f"missing/different {len(ac_bad)} {ac_bad[:5]}; verifies links missing {len(verifies_missing)}; implements links present {impl}")
    fidelity("story text", expected)

    real, tpl = L.list_files("Tasks")
    parsed = [TK.parse_task(n) for n in real]
    have = {r["key"] for r in L.call("GET", f"/v1/projects/{L.PROJECT}/items?kind=task&limit=1000")[1] if r["source"] == "v2-tasks"}
    want = {p["record"]["key"] for p in parsed}
    print(f"Tasks: files {len(real) + len(tpl)} (templates skipped {tpl}) -> tasks expected {len(want)}, in Viber {len(have & want)}, missing {sorted(want - have)}")
    refine_missing, dep_missing, expected = [], [], {}
    for p in parsed:
        r = p["record"]
        _, body = L.read_file("Tasks", r["source_ref"])
        expected[r["key"]] = (r["details"], alnum(body), 0)
        status, links = L.call("GET", f"/v1/projects/{L.PROJECT}/refs?type=item&key={r['key']}")
        out = {(l["relation"], l["key"]) for l in links["links_out"]}
        if ("refines", p["parent"]) not in out:
            refine_missing.append(r["key"])
        dep_missing += [(r["key"], d) for d in p["depends"] if ("depends_on", d) not in out]
    print(f"  refines links missing {len(refine_missing)} {refine_missing[:5]}; depends_on links missing {len(dep_missing)} {dep_missing[:5]}")
    fidelity("task text", expected)

    real, tpl = L.list_files("Sprints")
    parsed = [SP.parse_sprint(n) for n in real]
    have = {r["key"] for r in L.call("GET", f"/v1/projects/{L.PROJECT}/plans")[1]}
    want = {p["plan"]["key"] for p in parsed}
    print(f"Sprints: files {len(real) + len(tpl)} (templates skipped {tpl}) -> plans expected {len(want)}, in Viber {len(have & want)}, missing {sorted(want - have)}")
    expected, short, total = {}, [], 0
    for p in parsed:
        _, body = L.read_file("Sprints", p["plan"]["source_ref"])
        expected[p["notes"]["key"]] = (p["notes"]["details"], alnum(body), 0)
        status, view = L.call("GET", f"/v1/projects/{L.PROJECT}/plans/{p['plan']['key']}")
        n = len(view.get("item", [])) if status == 200 else 0
        total += n
        if n < 1 + len(p["table"]):
            short.append((p["plan"]["key"], n))
    print(f"  plan members in total {total}; plans with fewer members than their stories table implies: {short[:5]}")
    fidelity("sprint text", expected)


if __name__ == "__main__":
    main()
