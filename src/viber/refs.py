"""Plans and the one links table. A plan is a row whose content is what is linked to it. Every relation between
two things is a dated row in `ref`; an obsolete relation is ended, never deleted."""
from fastapi import HTTPException

from .db import record_audit

TYPES = ("plan", "spec", "item", "decision", "component", "version", "fact", "release", "entity")
RELATIONS = ("contains", "applies_to", "supersedes", "about", "found_in", "fixed_in", "implements", "verifies",
             "refines", "blocks", "depends_on", "replaces", "mentions")
PLAN_STATUSES = ("Draft", "Active", "Done", "Dropped")

# How each type is found and described: (SQL returning the canonical key and a one-line description, key parameter).
LOOKUP = {
    "plan": "SELECT key, title AS text FROM plan WHERE project_id = %s AND lower(key) = lower(%s)",
    "spec": "SELECT key, statement AS text FROM spec WHERE project_id = %s AND lower(key) = lower(%s)",
    "item": "SELECT key, title AS text FROM item WHERE project_id = %s AND lower(key) = lower(%s)",
    "decision": "SELECT key, title AS text FROM decision WHERE project_id = %s AND lower(key) = lower(%s)",
    "component": "SELECT key, key AS text FROM component WHERE project_id = %s AND lower(key) = lower(%s)",
    "release": "SELECT name AS key, name AS text FROM release WHERE project_id = %s AND lower(name) = lower(%s)",
    "fact": "SELECT id::text AS key, text FROM fact WHERE project_id = %s AND id::text = %s",
    "entity": "SELECT name AS key, name AS text FROM entity WHERE project_id = %s AND merged_into IS NULL AND lower(name) = lower(%s)",
}


def resolve(connection, project: dict, kind: str, key: str) -> dict:
    """The canonical key and description of a thing, or a 404 that names what was not found."""
    if kind not in TYPES:
        raise HTTPException(422, f"type is one of {', '.join(TYPES)}")
    key = (key or "").strip()
    if kind == "version":
        component, _, semver = key.partition("@")
        row = connection.execute(
            "SELECT c.key || '@' || v.semver AS key, c.key || ' ' || v.semver AS text FROM version v JOIN component c ON c.id = v.component_id "
            "WHERE c.project_id = %s AND lower(c.key) = lower(%s) AND v.semver = %s", (project["id"], component, semver)).fetchone()
    else:
        row = connection.execute(LOOKUP[kind], (project["id"], key)).fetchone()
    if not row:
        raise HTTPException(404, f"{kind} '{key}' not found")
    return {"type": kind, "key": row["key"], "text": row["text"]}


def add(connection, project: dict, from_type: str, from_key: str, relation: str, to_type: str, to_key: str,
        version_range: str | None = None, seq: int | None = None, note: str | None = None,
        source: str | None = None, source_ref: str | None = None, actor: str = "api") -> dict:
    relation = " ".join((relation or "").split()).lower().replace(" ", "_")
    if relation not in RELATIONS:
        raise HTTPException(422, f"relation is one of {', '.join(RELATIONS)}")
    a, b = resolve(connection, project, from_type, from_key), resolve(connection, project, to_type, to_key)
    if (a["type"], a["key"]) == (b["type"], b["key"]):
        raise HTTPException(422, "a thing cannot be related to itself")
    row = connection.execute(
        "INSERT INTO ref (project_id, from_type, from_key, relation, to_type, to_key, version_range, seq, note, source, source_ref) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
        (project["id"], a["type"], a["key"], relation, b["type"], b["key"], version_range, seq, note, source, source_ref)).fetchone()
    if row:
        record_audit(connection, actor, "link", "ref", str(row["id"]), project["id"], {"from": a["key"], "relation": relation, "to": b["key"]})
    return {"from": f"{a['type']}:{a['key']}", "relation": relation, "to": f"{b['type']}:{b['key']}", "created": bool(row)}


def end(connection, project: dict, from_type: str, from_key: str, relation: str, to_type: str, to_key: str, actor: str = "api") -> dict:
    a, b = resolve(connection, project, from_type, from_key), resolve(connection, project, to_type, to_key)
    relation = " ".join((relation or "").split()).lower().replace(" ", "_")
    rows = connection.execute(
        "UPDATE ref SET valid_to = now() WHERE project_id = %s AND from_type = %s AND from_key = %s AND lower(relation) = %s "
        "AND to_type = %s AND to_key = %s AND valid_to IS NULL RETURNING id", (project["id"], a["type"], a["key"], relation, b["type"], b["key"])).fetchall()
    if rows:
        record_audit(connection, actor, "unlink", "ref", str(rows[0]["id"]), project["id"], {"from": a["key"], "relation": relation, "to": b["key"]})
    return {"ended": len(rows)}


def _describe(connection, project: dict, kind: str, key: str) -> str:
    try:
        return resolve(connection, project, kind, key)["text"]
    except HTTPException:
        return "(missing)"


def show(connection, project: dict, kind: str, key: str, include_ended: bool = False) -> dict:
    """Everything linked to a thing, both ways, with a one-line description of each end."""
    me = resolve(connection, project, kind, key)
    live = "" if include_ended else "AND valid_to IS NULL "
    out = connection.execute(
        "SELECT relation, to_type AS type, to_key AS key, version_range, seq, note, valid_to FROM ref "
        "WHERE project_id = %s AND from_type = %s AND from_key = %s " + live + "ORDER BY relation, seq NULLS LAST, id",
        (project["id"], me["type"], me["key"])).fetchall()
    into = connection.execute(
        "SELECT relation, from_type AS type, from_key AS key, version_range, seq, note, valid_to FROM ref "
        "WHERE project_id = %s AND to_type = %s AND to_key = %s " + live + "ORDER BY relation, seq NULLS LAST, id",
        (project["id"], me["type"], me["key"])).fetchall()
    for row in out + into:
        row["text"] = _describe(connection, project, row["type"], row["key"])
    return {"thing": me, "links_out": out, "links_in": into}


def show_text(result: dict) -> str:
    t = result["thing"]
    lines = [f"{t['type']} {t['key']}: {t['text']}"]
    for row in result["links_out"]:
        lines.append(f"-> {row['relation']} {row['type']} {row['key']}" + (f" ({row['version_range']})" if row["version_range"] else "")
                     + f": {row['text'][:120]}" + (" [ended]" if row["valid_to"] else ""))
    for row in result["links_in"]:
        lines.append(f"<- {row['type']} {row['key']} {row['relation']} this" + (f" ({row['version_range']})" if row["version_range"] else "")
                     + f": {row['text'][:120]}" + (" [ended]" if row["valid_to"] else ""))
    return "\n".join(lines)


# ---- plans -------------------------------------------------------------------------------------------

def create_plan(connection, project: dict, key: str | None, title: str, goal: str = "", status: str = "Draft",
                source: str | None = None, source_ref: str | None = None, actor: str = "api") -> dict:
    if status not in PLAN_STATUSES:
        raise HTTPException(422, f"status is one of {', '.join(PLAN_STATUSES)}")
    if len(title) > 200 or len(goal) > 300:
        raise HTTPException(422, "a plan has a title of at most 200 characters and a one-line goal of at most 300; put the content in linked rows")
    if not key:
        row = connection.execute("INSERT INTO counter (project_id, name, value) VALUES (%s,'plan',1) ON CONFLICT (project_id, name) "
                                 "DO UPDATE SET value = counter.value + 1 RETURNING value", (project["id"],)).fetchone()
        key = f"PLAN-{row['value']:03d}"
    row = connection.execute(
        "INSERT INTO plan (project_id, key, title, goal, status, source, source_ref) VALUES (%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT DO NOTHING RETURNING id", (project["id"], key, title, goal, status, source, source_ref)).fetchone()
    if row:
        record_audit(connection, actor, "create", "plan", str(row["id"]), project["id"], {"key": key})
    return {"key": key, "created": bool(row)}


def add_to_plan(connection, project: dict, plan_key: str, members: list[tuple[str, str]], actor: str = "api") -> dict:
    plan = resolve(connection, project, "plan", plan_key)
    seq = connection.execute("SELECT coalesce(max(seq), 0) AS n FROM ref WHERE project_id = %s AND from_type = 'plan' AND from_key = %s "
                             "AND relation = 'contains'", (project["id"], plan["key"])).fetchone()["n"]
    added = []
    for kind, key in members:
        seq += 1
        result = add(connection, project, "plan", plan["key"], "contains", kind, key, seq=seq, actor=actor)
        added.append(result["to"])
    connection.execute("UPDATE plan SET updated_at = now() WHERE project_id = %s AND key = %s", (project["id"], plan["key"]))
    return {"plan": plan["key"], "added": added}


def update_plan(connection, project: dict, plan_key: str, title: str | None, goal: str | None, actor: str = "api") -> dict:
    plan = resolve(connection, project, "plan", plan_key)
    if (title is not None and not 0 < len(title) <= 200) or (goal is not None and len(goal) > 300):
        raise HTTPException(422, "a plan has a title of 1 to 200 characters and a one-line goal of at most 300")
    connection.execute("UPDATE plan SET title = COALESCE(%s, title), goal = COALESCE(%s, goal), updated_at = now() "
                       "WHERE project_id = %s AND key = %s", (title, goal, project["id"], plan["key"]))
    record_audit(connection, actor, "update", "plan", plan["key"], project["id"])
    return {"key": plan["key"]}


def set_plan_status(connection, project: dict, plan_key: str, status: str, actor: str = "api") -> dict:
    if status not in PLAN_STATUSES:
        raise HTTPException(422, f"status is one of {', '.join(PLAN_STATUSES)}")
    plan = resolve(connection, project, "plan", plan_key)
    connection.execute("UPDATE plan SET status = %s, updated_at = now() WHERE project_id = %s AND key = %s", (status, project["id"], plan["key"]))
    record_audit(connection, actor, "status", "plan", plan["key"], project["id"], {"status": status})
    return {"key": plan["key"], "status": status}


def plan_view(connection, project: dict, plan_key: str) -> dict:
    plan_ref = resolve(connection, project, "plan", plan_key)
    plan = connection.execute("SELECT key, title, goal, status FROM plan WHERE project_id = %s AND key = %s", (project["id"], plan_ref["key"])).fetchone()
    members = connection.execute("SELECT to_type, to_key FROM ref WHERE project_id = %s AND from_type = 'plan' AND from_key = %s "
                                 "AND relation = 'contains' AND valid_to IS NULL ORDER BY seq, id", (project["id"], plan["key"])).fetchall()
    sections: dict[str, list[dict]] = {"decision": [], "spec": [], "item": [], "other": []}
    for m in members:
        kind, key = m["to_type"], m["to_key"]
        if kind == "spec":
            row = connection.execute("SELECT key, kind, statement AS text, status FROM spec WHERE project_id = %s AND key = %s", (project["id"], key)).fetchone()
        elif kind == "item":
            row = connection.execute("SELECT key, kind, title AS text, status FROM item WHERE project_id = %s AND key = %s", (project["id"], key)).fetchone()
        elif kind == "decision":
            row = connection.execute("SELECT key, 'decision' AS kind, title AS text, status FROM decision WHERE project_id = %s AND key = %s", (project["id"], key)).fetchone()
        else:
            row = {"key": key, "kind": kind, "text": _describe(connection, project, kind, key), "status": ""}
        if row:
            sections[kind if kind in sections else "other"].append(row)
    done = {"Done", "Closed", "Fixed", "Built", "Verified", "Accepted", "Dropped"}
    everything = [r for rows in sections.values() for r in rows]
    return {**plan, "counts": {"total": len(everything), "settled": sum(1 for r in everything if r["status"] in done)}, **sections}


def plan_text(view: dict) -> str:
    lines = [f"{view['key']} [{view['status']}] {view['title']}"]
    if view["goal"]:
        lines.append(f"Goal: {view['goal']}")
    lines.append(f"Progress: {view['counts']['settled']} of {view['counts']['total']} settled")
    for label, name in (("Decisions", "decision"), ("Specs", "spec"), ("Work", "item"), ("Other", "other")):
        if view[name]:
            lines.append(f"{label}:")
            lines += [f"- {r['key']} [{r['status']}] {r['text'][:140]}" for r in view[name]]
    return "\n".join(lines)


def list_plans(connection, project: dict, status: str | None = None) -> list[dict]:
    return connection.execute(
        "SELECT p.key, p.title, p.status, (SELECT count(*) FROM ref r WHERE r.project_id = p.project_id AND r.from_type = 'plan' "
        "AND r.from_key = p.key AND r.relation = 'contains' AND r.valid_to IS NULL) AS members FROM plan p "
        "WHERE p.project_id = %s AND (%s::text IS NULL OR p.status = %s) ORDER BY p.created_at", (project["id"], status, status)).fetchall()


# ---- obsolete things ---------------------------------------------------------------------------------

def retire(connection, project: dict, kind: str, key: str, reason: str | None, actor: str = "api") -> dict:
    """Mark a thing obsolete without deleting it: a decision becomes Obsolete, a spec Dropped, a fact ends; its links end too."""
    thing = resolve(connection, project, kind, key)
    if kind == "decision":
        connection.execute("UPDATE decision SET status = 'Obsolete' WHERE project_id = %s AND key = %s", (project["id"], thing["key"]))
    elif kind == "spec":
        connection.execute("UPDATE spec SET status = 'Dropped', updated_at = now() WHERE project_id = %s AND key = %s", (project["id"], thing["key"]))
    elif kind == "fact":
        connection.execute("UPDATE fact SET valid_to = now() WHERE project_id = %s AND id::text = %s", (project["id"], thing["key"]))
    elif kind == "plan":
        connection.execute("UPDATE plan SET status = 'Dropped', updated_at = now() WHERE project_id = %s AND key = %s", (project["id"], thing["key"]))
    else:
        raise HTTPException(422, "only a decision, spec, fact or plan can be retired")
    ended = connection.execute(
        "UPDATE ref SET valid_to = now() WHERE project_id = %s AND valid_to IS NULL AND relation IN ('applies_to','about') "
        "AND from_type = %s AND from_key = %s RETURNING id", (project["id"], thing["type"], thing["key"])).fetchall()
    record_audit(connection, actor, "retire", kind, thing["key"], project["id"], {"reason": (reason or "")[:200]})
    return {"retired": f"{kind}:{thing['key']}", "links_ended": len(ended)}


def stale(connection, project: dict) -> list[dict]:
    """Live decisions, specs and facts still tied to a component or version that is deprecated or archived: the review list."""
    return connection.execute(
        "SELECT r.from_type AS type, r.from_key AS key, r.relation, c.key AS component, c.lifecycle FROM ref r "
        "JOIN component c ON c.project_id = r.project_id AND lower(c.key) = lower(split_part(r.to_key, '@', 1)) "
        "WHERE r.project_id = %s AND r.valid_to IS NULL AND r.to_type IN ('component','version') AND r.relation IN ('applies_to','about') "
        "AND c.lifecycle IN ('deprecated','archived') ORDER BY c.key, r.from_key", (project["id"],)).fetchall()
