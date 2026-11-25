"""Decision numbering and reading. A decision's statements live in decision_point rows."""
import re
from collections import Counter

from fastapi import HTTPException

from .atoms import POINT_MAX, split_atoms
from .db import record_audit

KEY = re.compile(r"^(?P<prefix>.*?)(?P<number>\d+)$")
POINT_KINDS = {"context": "context", "decision": "decision", "alternatives": "alternative", "consequences": "consequence"}


def default_prefix(connection, project: dict) -> str:
    """The prefix most decision keys use (ADR-v3. for sbos, ADR- when a project has none yet)."""
    keys = [row["key"] for row in connection.execute("SELECT key FROM decision WHERE project_id = %s", (project["id"],)).fetchall()]
    prefixes = Counter(m["prefix"] for m in (KEY.match(k) for k in keys) if m)
    return prefixes.most_common(1)[0][0] if prefixes else "ADR-"


def next_key(connection, project: dict, prefix: str | None, actor: str, session_tag: str | None = None) -> str:
    """Take the next number and reserve it with an empty row, so two sessions never get the same one."""
    connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("adr:" + str(project["id"]),))
    prefix = prefix or default_prefix(connection, project)
    highest, width = 0, 3
    for row in connection.execute("SELECT key FROM decision WHERE project_id = %s AND key LIKE %s", (project["id"], prefix + "%")).fetchall():
        m = KEY.match(row["key"])
        if m and m["prefix"] == prefix:
            highest = max(highest, int(m["number"]))
            width = max(width, len(m["number"]))
    key = f"{prefix}{highest + 1:0{width}d}"
    row = connection.execute(
        "INSERT INTO decision (project_id, key, title, status) VALUES (%s,%s,%s,'Reserved') RETURNING id",
        (project["id"], key, f"(reserved{' by ' + session_tag if session_tag else ''})")).fetchone()
    record_audit(connection, actor, "reserve", "decision", str(row["id"]), project["id"], {"key": key})
    return key


def write_points(connection, decision_id, sections: dict[str, str]) -> int:
    """Replace a decision's statements. sections maps context/decision/alternatives/consequences to text."""
    written = 0
    for field, kind in POINT_KINDS.items():
        text = sections.get(field)
        if text is None:
            continue
        connection.execute("DELETE FROM decision_point WHERE decision_id = %s AND kind = %s", (decision_id, kind))
        for seq, atom in enumerate(split_atoms(text, POINT_MAX), start=1):
            connection.execute("INSERT INTO decision_point (decision_id, kind, seq, text) VALUES (%s,%s,%s,%s)",
                               (decision_id, kind, seq, atom))
            written += 1
    return written


def find(connection, project: dict, reference: str) -> dict:
    """A decision by full key (ADR-v3.017) or by its number alone (17, 017)."""
    reference = reference.strip()
    row = connection.execute("SELECT * FROM decision WHERE project_id = %s AND lower(key) = lower(%s)", (project["id"], reference)).fetchone()
    if row:
        return row
    if reference.isdigit():
        wanted = int(reference)
        prefix = default_prefix(connection, project)
        for candidate in connection.execute("SELECT * FROM decision WHERE project_id = %s AND key LIKE %s", (project["id"], prefix + "%")).fetchall():
            m = KEY.match(candidate["key"])
            if m and m["prefix"] == prefix and int(m["number"]) == wanted:
                return candidate
    raise HTTPException(404, f"decision '{reference}' not found")


def read(connection, project: dict, reference: str) -> dict:
    row = find(connection, project, reference)
    points = connection.execute("SELECT kind, seq, text FROM decision_point WHERE decision_id = %s ORDER BY kind, seq", (row["id"],)).fetchall()
    return {"key": row["key"], "title": row["title"], "status": row["status"], "decided_on": row["decided_on"],
            "supersedes": row["supersedes"], "superseded_by": row["superseded_by"],
            "context": [p["text"] for p in points if p["kind"] == "context"],
            "decision": [p["text"] for p in points if p["kind"] == "decision"],
            "alternatives": [p["text"] for p in points if p["kind"] == "alternative"],
            "consequences": [p["text"] for p in points if p["kind"] == "consequence"]}


def as_text(adr: dict) -> str:
    lines = [f"{adr['key']}: {adr['title']} [{adr['status']}{', ' + str(adr['decided_on']) if adr['decided_on'] else ''}]"]
    for label, name in (("Context", "context"), ("Decision", "decision"), ("Alternatives", "alternatives"), ("Consequences", "consequences")):
        if adr[name]:
            lines.append(f"{label}:")
            lines += [f"- {p}" for p in adr[name]]
    if adr["supersedes"]:
        lines.append(f"Supersedes: {adr['supersedes']}")
    if adr["superseded_by"]:
        lines.append(f"Superseded by: {adr['superseded_by']}")
    return "\n".join(lines)
