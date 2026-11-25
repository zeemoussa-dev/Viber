import os
from hmac import compare_digest

from fastapi import Header, HTTPException


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected_token = os.environ.get("VIBER_TOKEN", "")
    if not expected_token:
        return
    supplied_token = (authorization or "").removeprefix("Bearer ").strip()
    if not compare_digest(supplied_token, expected_token):
        raise HTTPException(401, "missing or wrong bearer token")


def actor_name(x_viber_actor: str | None = Header(default=None)) -> str:
    return x_viber_actor or "api"
