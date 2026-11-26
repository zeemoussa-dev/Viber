"""Timed facts: what is true only for now. "Run unattended tonight" or "don't touch billing until Friday" is not a rule
and must not live on after its time. A timed fact is a normal fact with an end: sessions see it first, under "For now",
until it expires or someone ends it; then it is history.

Authority matters, because such a fact often grants permission to act. Only a person with the review or admin role (the
dashboard) can record one as set by the operator. One recorded by a session says so, and a session cannot end the
operator's."""
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from .atoms import FACT_MAX
from .db import insert_idempotent, record_audit, transaction

MIN_LENGTH = timedelta(minutes=5)
MAX_LENGTH = timedelta(days=90)
_DURATION = re.compile(r"^\s*(\d+)\s*(m|min|h|hour|hours|d|day|days|w|week|weeks)\s*$", re.I)
_UNIT = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_expiry(duration: str | None = None, until: str | None = None, now: datetime | None = None) -> datetime | None:
    """'8h', '2d', '90m', '1w', or an ISO time with its offset. None when neither is given."""
    now = now or datetime.now(timezone.utc)
    if duration and until:
        raise HTTPException(422, "give how long it lasts, or when it ends, not both")
    if duration:
        match = _DURATION.match(duration)
        if not match:
            raise HTTPException(422, f"'{duration}' is not a length of time; use for example 90m, 12h, 2d or 1w")
        end = now + timedelta(**{_UNIT[match[2][0].lower()]: int(match[1])})
    elif until:
        try:
            end = datetime.fromisoformat(until.strip().replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, f"'{until}' is not a time; use for example 2026-11-27T08:00+04:00")
        if end.tzinfo is None:
            raise HTTPException(422, "say the time zone, for example 2026-11-27T08:00+04:00")
    else:
        return None
    if not MIN_LENGTH - timedelta(seconds=5) <= end - now <= MAX_LENGTH:
        raise HTTPException(422, "a temporary fact lasts at least 5 minutes and at most 90 days; for longer, store a fact or a rule")
    return end


def expire_due(connection) -> int:
    """End every timed fact whose time has passed. Cheap, and called before anything reads memory for a session."""
    return len(connection.execute("UPDATE fact SET valid_to = expires_at WHERE valid_to IS NULL AND expires_at <= now() RETURNING id").fetchall())


def left(end: datetime) -> str:
    seconds = (end - datetime.now(timezone.utc)).total_seconds()
    if seconds < 3600:
        return f"{max(1, round(seconds / 60))} min left"
    if seconds < 48 * 3600:
        return f"{round(seconds / 3600)} h left"
    return f"{round(seconds / 86400)} days left"


def stamp(end: datetime) -> str:
    return end.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def add(connection, project: dict, text: str, end: datetime, by_operator: bool, scope: str = "project", actor: str = "api") -> dict:
    """Record a timed fact. Saying the same thing again moves its end; it does not make a second row."""
    text = " ".join((text or "").split())
    if not text or len(text) > FACT_MAX:
        raise HTTPException(422, f"one short statement of 1 to {FACT_MAX} characters")
    expire_due(connection)
    same = connection.execute("SELECT id::text AS id, expires_at, set_by_operator FROM fact WHERE project_id = %s AND scope = %s "
                              "AND lower(text) = lower(%s) AND valid_to IS NULL", (project["id"], scope, text)).fetchone()
    if same:
        if same["expires_at"] is None:
            raise HTTPException(409, "this is already a permanent fact; end it first if it should now be temporary")
        if same["set_by_operator"] and not by_operator:
            raise HTTPException(403, "the operator set this; a session cannot change when it ends")
        connection.execute("UPDATE fact SET expires_at = %s, set_by_operator = %s WHERE id::text = %s", (end, by_operator, same["id"]))
        record_audit(connection, actor, "extend", "fact", same["id"], project["id"], {"until": stamp(end)})
        return {"id": same["id"], "expires_at": end, "created": False}
    fact_id, _ = insert_idempotent(connection, "fact", {"project_id": project["id"], "text": text, "scope": scope,
                                                        "trust": "person" if by_operator else "agent", "expires_at": end, "set_by_operator": by_operator})
    record_audit(connection, actor, "create", "fact", fact_id, project["id"], {"until": stamp(end), "by_operator": by_operator})
    return {"id": fact_id, "expires_at": end, "created": True}


def live(connection, project: dict, scopes: list[str] | None = None) -> list[dict]:
    expire_due(connection)
    return connection.execute(
        "SELECT id::text AS id, text, scope, expires_at, set_by_operator, created_at FROM fact WHERE project_id = %s AND valid_to IS NULL "
        "AND expires_at IS NOT NULL AND (%s::text[] IS NULL OR scope = ANY(%s)) ORDER BY set_by_operator DESC, expires_at",
        (project["id"], scopes, scopes)).fetchall()


def ended(connection, project: dict, hours: int = 48) -> list[dict]:
    return connection.execute(
        "SELECT id::text AS id, text, scope, expires_at, valid_to, set_by_operator FROM fact WHERE project_id = %s AND expires_at IS NOT NULL "
        "AND valid_to IS NOT NULL AND valid_to > now() - make_interval(hours => %s) ORDER BY valid_to DESC LIMIT 20",
        (project["id"], hours)).fetchall()


def end_now(connection, project: dict, fact_id: str, may_end_operators: bool, actor: str = "api") -> dict:
    expire_due(connection)
    row = connection.execute("SELECT set_by_operator FROM fact WHERE project_id = %s AND id::text = %s AND expires_at IS NOT NULL "
                             "AND valid_to IS NULL", (project["id"], fact_id)).fetchone()
    if not row:
        raise HTTPException(404, "no live temporary fact with that id")
    if row["set_by_operator"] and not may_end_operators:
        raise HTTPException(403, "the operator set this; only the operator can end it")
    connection.execute("UPDATE fact SET valid_to = now() WHERE id::text = %s", (fact_id,))
    record_audit(connection, actor, "end", "fact", fact_id, project["id"])
    return {"id": fact_id, "ended": True}


def line(fact: dict) -> str:
    who = "set by the operator" if fact["set_by_operator"] else "recorded by a session; if it lets you act without asking, confirm it with the operator"
    return f"- {fact['text']} (until {stamp(fact['expires_at'])}, {left(fact['expires_at'])}; {who}) [id {fact['id']}]"


def start_sweeper(every_s: float = 30.0) -> None:
    import threading
    import time

    def loop():
        while True:
            try:
                with transaction() as connection:
                    expire_due(connection)
            except Exception:
                pass
            time.sleep(every_s)
    threading.Thread(target=loop, name="viber-expiry", daemon=True).start()
