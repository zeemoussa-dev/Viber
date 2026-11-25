"""Access tokens with a role. Admin only (see security.py). The token is shown once, when it is made; only its hash is kept."""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .db import record_audit, transaction
from .security import RANK, actor_name, hash_token, require_token

router = APIRouter(prefix="/v1/tokens", dependencies=[Depends(require_token)])


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    role: str


@router.post("", status_code=201)
def make_token(payload: TokenIn, actor: str = Depends(actor_name)):
    if payload.role not in RANK:
        raise HTTPException(422, f"role is one of {', '.join(RANK)}")
    token = "vbr_" + secrets.token_urlsafe(32)
    with transaction() as connection:
        row = connection.execute("INSERT INTO api_token (name, role, token_hash, created_by) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
                                 (payload.name.strip(), payload.role, hash_token(token), actor)).fetchone()
        if not row:
            raise HTTPException(409, f"a live token named '{payload.name}' already exists; revoke it first or pick another name")
        record_audit(connection, actor, "create", "token", str(row["id"]), None, {"name": payload.name, "role": payload.role})
    return {"id": str(row["id"]), "name": payload.name.strip(), "role": payload.role, "token": token,
            "note": "Copy the token now. It is not shown again."}


@router.get("")
def list_tokens():
    with transaction() as connection:
        return connection.execute("SELECT id::text AS id, name, role, created_by, created_at, last_used_at, revoked_at FROM api_token "
                                  "ORDER BY revoked_at IS NOT NULL, created_at DESC").fetchall()


@router.delete("/{token_id}")
def revoke_token(token_id: str, actor: str = Depends(actor_name)):
    with transaction() as connection:
        row = connection.execute("UPDATE api_token SET revoked_at = now() WHERE id::text = %s AND revoked_at IS NULL RETURNING id, name", (token_id,)).fetchone()
        if not row:
            raise HTTPException(404, "no live token with that id")
        record_audit(connection, actor, "revoke", "token", str(row["id"]), None, {"name": row["name"]})
    return {"revoked": row["name"]}
