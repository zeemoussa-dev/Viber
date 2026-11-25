"""The memory graph, as in Second Brain: entities with aliases, dated relations between them, and facts about them.
An entity is found by name or alias; a name nobody has makes a new one. A relation that stops being true is
ended (valid_to), never deleted, so the graph keeps how things changed."""
from fastapi import HTTPException

from .atoms import RELATION_MAX


def _clean(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise HTTPException(422, "an entity needs a name")
    if len(name) > 200:
        raise HTTPException(422, "an entity name is at most 200 characters")
    return name


def _follow_merges(connection, entity: dict) -> dict:
    while entity["merged_into"]:
        entity = connection.execute("SELECT * FROM entity WHERE id = %s", (entity["merged_into"],)).fetchone()
    return entity


def find_entity(connection, project: dict, name: str) -> dict | None:
    name = _clean(name)
    row = connection.execute("SELECT * FROM entity WHERE project_id = %s AND lower(name) = lower(%s)", (project["id"], name)).fetchone()
    if not row:
        row = connection.execute(
            "SELECT e.* FROM entity_alias a JOIN entity e ON e.id = a.entity_id WHERE a.project_id = %s AND lower(a.alias) = lower(%s)",
            (project["id"], name)).fetchone()
    return _follow_merges(connection, row) if row else None


def entity_for(connection, project: dict, name: str, kind: str | None = None) -> dict:
    found = find_entity(connection, project, name)
    if found:
        return found
    return connection.execute("INSERT INTO entity (project_id, kind, name) VALUES (%s,%s,%s) RETURNING *",
                              (project["id"], kind or "thing", _clean(name))).fetchone()


def add_aliases(connection, project: dict, entity: dict, aliases: list[str]) -> None:
    for alias in aliases:
        alias = _clean(alias)
        if alias.lower() != entity["name"].lower():
            connection.execute("INSERT INTO entity_alias (project_id, entity_id, alias) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                               (project["id"], entity["id"], alias))


def link(connection, project: dict, subject: str, relation: str, obj: str, subject_kind: str | None = None,
         object_kind: str | None = None, source: str | None = None, source_ref: str | None = None) -> dict:
    relation = " ".join((relation or "").split()).lower()
    if not relation or len(relation) > RELATION_MAX:
        raise HTTPException(422, f"a relation is 1 to {RELATION_MAX} characters, for example 'depends on' or 'owned by'")
    a, b = entity_for(connection, project, subject, subject_kind), entity_for(connection, project, obj, object_kind)
    row = connection.execute(
        "INSERT INTO edge (project_id, subject_id, relation, object_id, source, source_ref) VALUES (%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT DO NOTHING RETURNING id", (project["id"], a["id"], relation, b["id"], source, source_ref)).fetchone()
    return {"subject": a["name"], "relation": relation, "object": b["name"], "created": bool(row)}


def unlink(connection, project: dict, subject: str, relation: str, obj: str) -> dict:
    a, b = find_entity(connection, project, subject), find_entity(connection, project, obj)
    if not a or not b:
        raise HTTPException(404, "no such entity")
    rows = connection.execute(
        "UPDATE edge SET valid_to = now() WHERE project_id = %s AND subject_id = %s AND object_id = %s AND lower(relation) = lower(%s) "
        "AND valid_to IS NULL RETURNING id", (project["id"], a["id"], b["id"], relation)).fetchall()
    return {"ended": len(rows)}


def link_fact(connection, project: dict, fact_id: str, names: list[str]) -> list[str]:
    linked = []
    for name in names:
        entity = entity_for(connection, project, name)
        connection.execute("INSERT INTO fact_entity (fact_id, entity_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (fact_id, entity["id"]))
        linked.append(entity["name"])
    return linked


def around(connection, project: dict, name: str, limit: int = 40) -> dict:
    entity = find_entity(connection, project, name)
    if not entity:
        raise HTTPException(404, f"no entity '{name}'")
    edges = connection.execute(
        "SELECT s.name AS subject, e.relation, o.name AS object, e.valid_from FROM edge e "
        "JOIN entity s ON s.id = e.subject_id JOIN entity o ON o.id = e.object_id "
        "WHERE e.project_id = %s AND e.valid_to IS NULL AND (e.subject_id = %s OR e.object_id = %s) ORDER BY e.valid_from DESC LIMIT %s",
        (project["id"], entity["id"], entity["id"], limit)).fetchall()
    facts = connection.execute(
        "SELECT f.text FROM fact_entity fe JOIN fact f ON f.id = fe.fact_id WHERE fe.entity_id = %s AND f.valid_to IS NULL "
        "ORDER BY f.created_at DESC LIMIT %s", (entity["id"], limit)).fetchall()
    aliases = [r["alias"] for r in connection.execute("SELECT alias FROM entity_alias WHERE entity_id = %s", (entity["id"],)).fetchall()]
    return {"entity": entity["name"], "kind": entity["kind"], "aliases": aliases, "edges": edges, "facts": [f["text"] for f in facts]}


def graph_text(result: dict) -> str:
    lines = [f"{result['entity']} ({result['kind']})" + (f", also {', '.join(result['aliases'])}" if result["aliases"] else "")]
    lines += [f"- {e['subject']} {e['relation']} {e['object']}" for e in result["edges"]]
    lines += [f"* {text}" for text in result["facts"]]
    return "\n".join(lines)
