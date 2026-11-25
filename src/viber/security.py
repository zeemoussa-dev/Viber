"""Who is calling, and what they may do.

Four roles, each including the ones before it:
  read    searches and reads everything (recall, specs, plans, views); changes nothing
  write   also records work: facts, episodes, bugs, items, specs, plans, links, handoffs, proposals
  review  also decides what only a human should: accepts or rejects rules and decisions, retires, supersedes
  admin   also makes projects and access tokens

The master token (VIBER_TOKEN) is admin. Other tokens are made on the Viber page or POST /v1/tokens, carry a name that
becomes the actor in the audit log, and can be revoked. With no VIBER_TOKEN set Viber is open (local development only)."""
import hashlib
import json
import os
import re
from hmac import compare_digest

from fastapi import Header, HTTPException, Request

RANK = {"read": 0, "write": 1, "review": 2, "admin": 3}
# MCP tools that only read. Every other tool records something.
READ_TOOLS = {"viber_recall", "viber_context", "viber_sessions", "viber_get_adr", "viber_spec_get", "viber_graph", "viber_refs",
              "viber_stale", "viber_duplicates"}
REVIEW_TOOLS = {"viber_retire"}
REVIEW_PATHS = re.compile(r"/(accept|reject|retire|supersede)(/|$)|/memory/rules/[^/]+/(accept|retire)$")
ADMIN_PATHS = re.compile(r"^/v1/(tokens(/|$)|projects$)")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _lookup(token: str) -> dict | None:
    from .db import transaction
    with transaction() as connection:
        row = connection.execute("SELECT id, name, role, last_used_at < now() - interval '1 minute' OR last_used_at IS NULL AS stale "
                                 "FROM api_token WHERE token_hash = %s AND revoked_at IS NULL", (hash_token(token),)).fetchone()
        if row and row["stale"]:
            connection.execute("UPDATE api_token SET last_used_at = now() WHERE id = %s", (row["id"],))
    return row


async def _needed_role(request: Request) -> str:
    path, method = request.url.path, request.method
    if ADMIN_PATHS.match(path) and (method != "GET" or path.startswith("/v1/tokens")):
        return "admin"
    if path == "/mcp" and method == "POST":
        try:
            message = json.loads(await request.body() or b"{}")
        except ValueError:
            return "read"
        if message.get("method") != "tools/call":
            return "read"
        tool = (message.get("params") or {}).get("name", "")
        return "read" if tool in READ_TOOLS else "review" if tool in REVIEW_TOOLS else "write"
    if method in ("GET", "HEAD", "OPTIONS"):
        return "read"
    if REVIEW_PATHS.search(path):
        return "review"
    return "write"


async def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    master = os.environ.get("VIBER_TOKEN", "")
    request.state.role, request.state.token_name = "admin", None
    if not master:
        return
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if supplied and compare_digest(supplied, master):
        return
    row = _lookup(supplied) if supplied else None
    if not row:
        raise HTTPException(401, "missing or wrong bearer token")
    request.state.role, request.state.token_name = row["role"], row["name"]
    needed = await _needed_role(request)
    if RANK[row["role"]] < RANK[needed]:
        raise HTTPException(403, f"this token has the '{row['role']}' role; this needs '{needed}'")


def actor_name(request: Request, x_viber_actor: str | None = Header(default=None)) -> str:
    """A named token is its own actor in the audit log; the master token may say who it is acting for."""
    return getattr(request.state, "token_name", None) or x_viber_actor or "api"
