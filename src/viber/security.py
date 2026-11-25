"""Who is calling, what they may do, and which projects they may touch.

Four roles, each including the ones before it:
  read    searches and reads everything (recall, specs, plans, views); changes nothing
  write   also records work: facts, episodes, bugs, items, specs, plans, links, handoffs, proposals
  review  also decides what only a human should: accepts or rejects rules and decisions, retires, supersedes
  admin   also makes projects and access tokens

A token can also be limited to some projects. Memory is per project: every query already filters by project, and a limited
token is refused (403) for any other project, so a session working on one project cannot read or write another's.

The master token (VIBER_TOKEN) is admin on every project. Other tokens are made on the System page or POST /v1/tokens, carry
a name that becomes the actor in the audit log, and can be revoked. With no VIBER_TOKEN set Viber is open (local development only)."""
import hashlib
import json
import os
import re
from hmac import compare_digest

from fastapi import Header, HTTPException, Request

RANK = {"read": 0, "write": 1, "review": 2, "admin": 3}
# MCP tools that only read. Every other tool records something.
READ_TOOLS = {"viber_recall", "viber_context", "viber_sessions", "viber_get_adr", "viber_spec_get", "viber_graph", "viber_refs",
              "viber_stale", "viber_duplicates", "viber_episodes_pending", "viber_component_digest", "viber_prompt", "viber_view"}
REVIEW_TOOLS = {"viber_retire"}
REVIEW_PATHS = re.compile(r"/(accept|reject|retire|supersede)(/|$)|/memory/rules/[^/]+/(accept|retire)$")
ADMIN_PATHS = re.compile(r"^/v1/(tokens(/|$)|projects$)")
PROJECT_PATH = re.compile(r"^/v1/projects/([^/]+)")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _lookup(token: str) -> dict | None:
    from .db import transaction
    with transaction() as connection:
        row = connection.execute("SELECT id, name, role, project_keys, last_used_at < now() - interval '1 minute' OR last_used_at IS NULL AS stale "
                                 "FROM api_token WHERE token_hash = %s AND revoked_at IS NULL", (hash_token(token),)).fetchone()
        if row and row["stale"]:
            connection.execute("UPDATE api_token SET last_used_at = now() WHERE id = %s", (row["id"],))
    return row


async def _inspect(request: Request) -> tuple[str, str | None]:
    """The role this request needs and the project it is about (None when it is about none)."""
    path, method = request.url.path, request.method
    project = (PROJECT_PATH.match(path) or [None, None])[1]
    if ADMIN_PATHS.match(path) and (method != "GET" or path.startswith("/v1/tokens")):
        return "admin", project
    if path == "/mcp" and method == "POST":
        try:
            message = json.loads(await request.body() or b"{}")
        except ValueError:
            return "read", None
        if message.get("method") != "tools/call":
            return "read", None
        params = message.get("params") or {}
        tool = params.get("name", "")
        project = (params.get("arguments") or {}).get("project")
        return ("read" if tool in READ_TOOLS else "review" if tool in REVIEW_TOOLS else "write"), project
    if method in ("GET", "HEAD", "OPTIONS"):
        return "read", project
    if REVIEW_PATHS.search(path):
        return "review", project
    return "write", project


async def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    master = os.environ.get("VIBER_TOKEN", "")
    request.state.role, request.state.token_name, request.state.project_keys = "admin", None, None
    if not master:
        return
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if supplied and compare_digest(supplied, master):
        return
    row = _lookup(supplied) if supplied else None
    if not row:
        raise HTTPException(401, "missing or wrong bearer token")
    request.state.role, request.state.token_name, request.state.project_keys = row["role"], row["name"], row["project_keys"]
    needed, project = await _inspect(request)
    if RANK[row["role"]] < RANK[needed]:
        raise HTTPException(403, f"this token has the '{row['role']}' role; this needs '{needed}'")
    if row["project_keys"] is not None and project and project not in row["project_keys"]:
        raise HTTPException(403, f"this token is limited to the project(s) {', '.join(row['project_keys']) or '(none)'}, not '{project}'")


def actor_name(request: Request, x_viber_actor: str | None = Header(default=None)) -> str:
    """A named token is its own actor in the audit log; the master token may say who it is acting for."""
    return getattr(request.state, "token_name", None) or x_viber_actor or "api"


def visible_projects(request: Request) -> list[str] | None:
    """The projects this caller may see, or None for all of them."""
    return getattr(request.state, "project_keys", None)
