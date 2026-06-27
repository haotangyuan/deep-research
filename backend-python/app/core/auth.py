from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Header, HTTPException

from app.core.config import get_settings


def generate_token(user_id: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiration_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
        return int(payload.get("sub"))
    except Exception:
        return None


async def current_user_id(authorization: str | None = Header(default=None, alias="Authorization")) -> int:
    if authorization and authorization.startswith("Bearer "):
        user_id = decode_token(authorization[7:])
        if user_id is not None:
            return user_id
    raise HTTPException(status_code=401)
