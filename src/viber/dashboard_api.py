"""Read models and review actions the dashboard needs. Everything here is also usable by other clients."""
from fastapi import APIRouter, Depends, HTTPException, Query

from . import links, service, sessions
from .constraints import highest
from .db import record_audit, transaction
from .security import actor_name, require_token

router = APIRouter(prefix="/v1/projects/{project_key}", dependencies=[Depends(require_token)])
CLOSED_ITEM_STATUSES = ["Closed", "Done", "Fixed", "Won't Fix"]


@router.get("/overview")
def overview(project_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        pid = project["id"]
        count = lambda sql, *args: connection.execute(sql, (pid, *args)).fetchone()["n"]
        link_check = links.check_links(connection, project)
        stats = sessions.session_stats(connection, project)
        return {
            "project": {"key": project["key"], "name": project["name"]},
            "counts": {
                "active_sessions": stats["sessions"]["active"],
                "open_bugs": count("SELECT count(*) AS n FROM item WHERE project_id=%s AND kind='bug' AND status <> ALL(%s)", CLOSED_ITEM_STATUSES),
                "open_items": count("SELECT count(*) AS n FROM item WHERE project_id=%s AND status <> ALL(%s)", CLOSED_ITEM_STATUSES),
                "awaiting_review": sum(review_counts(connection, pid).values()),
                "components": count("SELECT count(*) AS n FROM component WHERE project_id=%s"),
                "link_problems": len(link_check["problems"]),
                "facts": count("SELECT count(*) AS n FROM fact WHERE project_id=%s AND valid_to IS NULL"),
                "accepted_rules": count("SELECT count(*) AS n FROM rule WHERE project_id=%s AND status='accepted'"),
            },
            "session_stats": stats,
            "link_states": link_check["link_states"],
            "recent_changes": connection.execute(
                "SELECT occurred_on, kind, summary FROM change WHERE project_id=%s ORDER BY occurred_on DESC, created_at DESC LIMIT 8", (pid,)).fetchall(),
            "recent_handoffs": connection.execute(
                "SELECT e.content, e.occurred_at, s.tag FROM episode e LEFT JOIN session s ON s.id = e.session_id "
                "WHERE e.project_id=%s AND e.kind='handoff' ORDER BY e.occurred_at DESC LIMIT 5", (pid,)).fetchall(),
            "active_sessions": sessions.active_sessions(connection, project),
        }


def review_counts(connection, pid) -> dict:
    return connection.execute(
        "SELECT (SELECT count(*) FROM rule WHERE project_id=%s AND status='proposed') AS rules, "
        "(SELECT count(*) FROM decision WHERE project_id=%s AND status='Proposed') AS decisions, "
        "(SELECT count(*) FROM item WHERE project_id=%s AND gate='flagged') AS items", (pid, pid, pid)).fetchone()


@router.get("/review")
def review_queue(project_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        pid = project["id"]
        return {
            "counts": review_counts(connection, pid),
            "rules": connection.execute(
                "SELECT id::text, category, scope, text, proposed_by, created_at FROM rule WHERE project_id=%s AND status='proposed' "
                "ORDER BY created_at DESC", (pid,)).fetchall(),
            "decisions": connection.execute(
                "SELECT d.key, d.title, d.decided_on, "
                + ", ".join(
                    f"COALESCE((SELECT string_agg(p.text, E'\\n' ORDER BY p.seq) FROM decision_point p "
                    f"WHERE p.decision_id = d.id AND p.kind = '{kind}'), '') AS {name}"
                    for name, kind in (("context", "context"), ("decision", "decision"),
                                       ("alternatives", "alternative"), ("consequences", "consequence")))
                + " FROM decision d WHERE d.project_id=%s AND d.status='Proposed' ORDER BY d.created_at DESC", (pid,)).fetchall(),
            "items": connection.execute(
                "SELECT key, kind, title, gate_reason, status FROM item WHERE project_id=%s AND gate='flagged' ORDER BY created_at DESC",
                (pid,)).fetchall(),
        }


def set_decision_status(project_key: str, decision_key: str, status: str, actor: str) -> dict:
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        row = connection.execute(
            "UPDATE decision SET status=%s WHERE project_id=%s AND key=%s AND status='Proposed' RETURNING id",
            (status, project["id"], decision_key)).fetchone()
        if not row:
            raise HTTPException(404, f"no Proposed decision '{decision_key}'")
        record_audit(connection, actor, status.lower(), "decision", str(row["id"]), project["id"])
    return {"key": decision_key, "status": status}


@router.post("/decisions/{decision_key}/accept")
def accept_decision(project_key: str, decision_key: str, actor: str = Depends(actor_name)):
    return set_decision_status(project_key, decision_key, "Accepted", actor)


@router.post("/decisions/{decision_key}/reject")
def reject_decision(project_key: str, decision_key: str, actor: str = Depends(actor_name)):
    return set_decision_status(project_key, decision_key, "Rejected", actor)


@router.post("/memory/rules/{rule_id}/retire")
def retire_rule(project_key: str, rule_id: str, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        row = connection.execute("UPDATE rule SET status='retired' WHERE project_id=%s AND id=%s RETURNING id",
                                 (project["id"], rule_id)).fetchone()
        if not row:
            raise HTTPException(404, "rule not found")
        record_audit(connection, actor, "retire", "rule", rule_id, project["id"])
    return {"id": rule_id, "status": "retired"}


@router.get("/components/summary")
def component_summary(project_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        rows = connection.execute(
            "SELECT c.key, c.kind, c.repo, c.path, c.lifecycle, h.semver AS head_version, h.scanned_at AS scanned_at, "
            "(SELECT count(*) FROM version r WHERE r.component_id = c.id AND NOT r.is_head) AS releases, "
            "(SELECT count(*) FROM link l WHERE l.from_component_id = c.id) AS depends_on, "
            "(SELECT count(*) FROM link l WHERE l.to_component_id = c.id) AS dependents "
            "FROM component c LEFT JOIN version h ON h.id = c.current_version_id "
            "WHERE c.project_id = %s ORDER BY c.key", (project["id"],)).fetchall()
        for row in rows:
            released = [r["semver"] for r in connection.execute(
                "SELECT v.semver FROM version v JOIN component c ON c.id = v.component_id "
                "WHERE c.project_id=%s AND c.key=%s AND NOT v.is_head", (project["id"], row["key"]))]
            row["latest_release"] = highest(released)
        return rows


@router.get("/memory/facts")
def list_facts(project_key: str, limit: int = Query(100, le=500)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return connection.execute(
            "SELECT id::text, scope, subject, text, trust, valid_from FROM fact WHERE project_id=%s AND valid_to IS NULL "
            "ORDER BY created_at DESC LIMIT %s", (project["id"], limit)).fetchall()


@router.get("/changes")
def list_changes(project_key: str, limit: int = Query(100, le=500)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return connection.execute(
            "SELECT c.occurred_on, c.kind, c.summary, c.body, c.version, c.source, c.source_ref, k.key AS component FROM change c "
            "LEFT JOIN component k ON k.id = c.component_id WHERE c.project_id=%s "
            "ORDER BY c.occurred_on DESC, c.created_at DESC LIMIT %s", (project["id"], limit)).fetchall()


@router.get("/sessions/history")
def session_history(project_key: str, limit: int = Query(50, le=200)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        rows = connection.execute(
            "SELECT s.id, s.tag, s.goal, s.state, s.repo, s.branch, s.source, s.started_at, s.last_seen, s.ended_at, s.summary, "
            "p.tag AS parent_tag, k.key AS component, "
            "(s.ended_at IS NULL AND s.last_seen > now() - interval '30 minutes') AS active, "
            "(SELECT count(DISTINCT path) FROM file_touch f WHERE f.session_id = s.id) AS files_touched, "
            "(SELECT count(*) FROM episode e WHERE e.session_id = s.id AND e.kind='handoff') AS handoffs "
            "FROM session s LEFT JOIN session p ON p.id = s.parent_id LEFT JOIN component k ON k.id = s.component_id "
            "WHERE s.project_id=%s ORDER BY s.last_seen DESC LIMIT %s", (project["id"], limit)).fetchall()
        for row in rows:
            row["id"] = str(row["id"])
        return rows


@router.get("/sessions/{tag}/detail")
def session_detail(project_key: str, tag: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        session = connection.execute("SELECT * FROM session WHERE project_id=%s AND tag=%s", (project["id"], tag)).fetchone()
        if not session:
            raise HTTPException(404, f"session '{tag}' not found")
        files = connection.execute(
            "SELECT path, count(*) AS touches, max(at) AS last_touched FROM file_touch WHERE session_id=%s GROUP BY path "
            "ORDER BY max(at) DESC LIMIT 50", (session["id"],)).fetchall()
        handoffs = connection.execute(
            "SELECT content, occurred_at FROM episode WHERE session_id=%s AND kind='handoff' ORDER BY occurred_at DESC",
            (session["id"],)).fetchall()
        forks = connection.execute("SELECT tag FROM session WHERE parent_id=%s ORDER BY started_at", (session["id"],)).fetchall()
        return {"tag": session["tag"], "goal": session["goal"], "state": session["state"], "summary": session["summary"],
                "started_at": session["started_at"], "last_seen": session["last_seen"], "ended_at": session["ended_at"],
                "files": files, "handoffs": handoffs, "forks": [f["tag"] for f in forks]}
