"""File claims: a session says which files it is working on, and a second session is told before it edits them.

A claim is live until it is released, expires (default 30 minutes, renewed by every edit of that file) or its
session ends. Claims never block anything by themselves: the hook decides whether a refusal stops the edit."""
from .db import record_audit
from .sessions import normalize_path, session_by_external_id

DEFAULT_TTL_MINUTES = 30
MAX_TTL_MINUTES = 240


def _free_dead_claims(connection, project_id) -> None:
    """Release claims that expired or whose session ended, so they never block a new claim."""
    connection.execute(
        "UPDATE file_claim c SET released_at = now() WHERE c.project_id = %s AND c.released_at IS NULL "
        "AND (c.expires_at < now() OR EXISTS (SELECT 1 FROM session s WHERE s.id = c.session_id AND s.ended_at IS NOT NULL))",
        (project_id,))


def claim_files(connection, project: dict, external_id: str, paths: list[str], reason: str | None,
                ttl_minutes: int, actor: str) -> dict:
    session = session_by_external_id(connection, project, external_id)
    ttl = max(1, min(int(ttl_minutes or DEFAULT_TTL_MINUTES), MAX_TTL_MINUTES))
    # One claim decision at a time per project, so two sessions cannot both win the same file.
    connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(project["id"]),))
    _free_dead_claims(connection, project["id"])
    granted, blocked = [], []
    for raw in dict.fromkeys(normalize_path(p) for p in paths if p):
        held = connection.execute(
            "SELECT c.id, c.session_id, c.reason, c.claimed_at, s.tag, s.goal FROM file_claim c JOIN session s ON s.id = c.session_id "
            "WHERE c.project_id = %s AND c.path = %s AND c.released_at IS NULL", (project["id"], raw)).fetchone()
        if held and held["session_id"] != session["id"]:
            blocked.append({"path": raw, "held_by": held["tag"], "goal": held["goal"], "reason": held["reason"],
                            "since": held["claimed_at"]})
            continue
        if held:
            connection.execute("UPDATE file_claim SET expires_at = now() + make_interval(mins => %s), "
                               "reason = COALESCE(%s, reason) WHERE id = %s", (ttl, reason, held["id"]))
        else:
            connection.execute("INSERT INTO file_claim (project_id, session_id, path, reason, expires_at) "
                               "VALUES (%s,%s,%s,%s, now() + make_interval(mins => %s))",
                               (project["id"], session["id"], raw, reason, ttl))
        granted.append(raw)
    connection.execute("UPDATE session SET last_seen = now() WHERE id = %s", (session["id"],))
    if blocked:
        record_audit(connection, actor, "claim_blocked", "session", str(session["id"]), project["id"],
                     {"paths": [b["path"] for b in blocked], "by": sorted({b["held_by"] for b in blocked})})
    return {"tag": session["tag"], "granted": granted, "blocked": blocked, "ttl_minutes": ttl}


def release_files(connection, project: dict, external_id: str, paths: list[str] | None) -> dict:
    session = session_by_external_id(connection, project, external_id)
    if paths:
        wanted = [normalize_path(p) for p in paths]
        rows = connection.execute(
            "UPDATE file_claim SET released_at = now() WHERE session_id = %s AND released_at IS NULL AND path = ANY(%s) RETURNING path",
            (session["id"], wanted)).fetchall()
    else:
        rows = connection.execute(
            "UPDATE file_claim SET released_at = now() WHERE session_id = %s AND released_at IS NULL RETURNING path",
            (session["id"],)).fetchall()
    return {"tag": session["tag"], "released": [r["path"] for r in rows]}


def live_claims(connection, project: dict) -> list[dict]:
    _free_dead_claims(connection, project["id"])
    return connection.execute(
        "SELECT c.path, s.tag, s.goal, c.reason, c.claimed_at, c.expires_at FROM file_claim c JOIN session s ON s.id = c.session_id "
        "WHERE c.project_id = %s AND c.released_at IS NULL ORDER BY c.claimed_at", (project["id"],)).fetchall()
