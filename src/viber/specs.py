"""Specifications as rows: one requirement, constraint, interface or acceptance criterion each, never a document."""
from fastapi import HTTPException

from .atoms import SPEC_MAX, split_lines
from .db import record_audit

KINDS = {"requirement": "REQ", "constraint": "CON", "interface": "IF", "acceptance": "AC", "nfr": "NFR", "question": "Q"}
STATUSES = ("Draft", "Agreed", "Built", "Verified", "Dropped")


def create(connection, project: dict, statement: str, kind: str = "requirement", component_key: str | None = None,
           parent_key: str | None = None, key: str | None = None, status: str = "Draft", source: str | None = None,
           source_ref: str | None = None, actor: str = "api") -> dict:
    statement = " ".join((statement or "").split())
    if not statement or len(statement) > SPEC_MAX:
        raise HTTPException(422, f"a spec row is one statement of 1 to {SPEC_MAX} characters; split longer text into several rows")
    if kind not in KINDS:
        raise HTTPException(422, f"kind is one of {', '.join(KINDS)}")
    if status not in STATUSES:
        raise HTTPException(422, f"status is one of {', '.join(STATUSES)}")
    if not key:
        counter = connection.execute(
            "INSERT INTO counter (project_id, name, value) VALUES (%s,%s,1) ON CONFLICT (project_id, name) "
            "DO UPDATE SET value = counter.value + 1 RETURNING value", (project["id"], "spec-" + KINDS[kind])).fetchone()
        key = f"{KINDS[kind]}-{counter['value']:03d}"
    row = connection.execute(
        "INSERT INTO spec (project_id, key, kind, component_key, parent_key, statement, status, source, source_ref) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *",
        (project["id"], key, kind, component_key, parent_key, statement, status, source, source_ref)).fetchone()
    if not row:
        return {"key": key, "created": False}
    record_audit(connection, actor, "create", "spec", str(row["id"]), project["id"], {"key": key})
    return {"key": key, "created": True}


def create_from_text(connection, project: dict, text: str, **fields) -> list[dict]:
    """Turn a pasted block (one requirement per line or sentence) into rows."""
    return [create(connection, project, atom, **fields) for atom in split_lines(text, SPEC_MAX)]


def read(connection, project: dict, key: str) -> dict:
    row = connection.execute("SELECT key, kind, component_key, parent_key, statement, status, updated_at FROM spec "
                             "WHERE project_id = %s AND lower(key) = lower(%s)", (project["id"], key)).fetchone()
    if not row:
        raise HTTPException(404, f"spec '{key}' not found")
    row["children"] = [r["key"] for r in connection.execute(
        "SELECT key FROM spec WHERE project_id = %s AND parent_key = %s ORDER BY key", (project["id"], row["key"])).fetchall()]
    return row


def list_specs(connection, project: dict, component_key: str | None = None, kind: str | None = None,
               status: str | None = None, query: str | None = None, limit: int = 100) -> list[dict]:
    sql = ("SELECT key, kind, component_key, parent_key, statement, status FROM spec WHERE project_id = %s "
           "AND (%s::text IS NULL OR component_key = %s) AND (%s::text IS NULL OR kind = %s) AND (%s::text IS NULL OR status = %s) ")
    params: list = [project["id"], component_key, component_key, kind, kind, status, status]
    if query:
        sql += "AND tsv @@ websearch_to_tsquery('english', %s) "
        params.append(query)
    return connection.execute(sql + "ORDER BY key LIMIT %s", params + [min(limit, 500)]).fetchall()


def update(connection, project: dict, key: str, statement: str | None, status: str | None, actor: str) -> dict:
    current = read(connection, project, key)
    if status is not None and status not in STATUSES:
        raise HTTPException(422, f"status is one of {', '.join(STATUSES)}")
    if statement is not None:
        statement = " ".join(statement.split())
        if not statement or len(statement) > SPEC_MAX:
            raise HTTPException(422, f"a spec row is one statement of 1 to {SPEC_MAX} characters")
    connection.execute("UPDATE spec SET statement = COALESCE(%s, statement), status = COALESCE(%s, status), updated_at = now() "
                       "WHERE project_id = %s AND key = %s", (statement, status, project["id"], current["key"]))
    record_audit(connection, actor, "update", "spec", current["key"], project["id"], {"status": status})
    return read(connection, project, key)
