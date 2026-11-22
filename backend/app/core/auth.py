from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings


bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: str


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user_id: str, *, expires_in: int | None = None) -> str:
    settings = get_settings()
    payload = {
        "sub": user_id,
        "exp": int(time.time()) + (expires_in or settings.auth_token_ttl_seconds),
        "v": 1,
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(
        settings.auth_token_secret.encode(), encoded.encode(), hashlib.sha256
    ).digest()
    return f"{encoded}.{_encode(signature)}"


def verify_access_token(token: str) -> CurrentUser:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(
            get_settings().auth_token_secret.encode(), encoded.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _decode(supplied_signature)):
            raise ValueError("signature")
        payload = json.loads(_decode(encoded))
        user_id = str(payload["sub"]).strip()
        if not user_id or int(payload["exp"]) <= int(time.time()):
            raise ValueError("expired")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return CurrentUser(id=user_id)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_access_token(credentials.credentials)


def assert_user(user_id: str, current_user: CurrentUser) -> None:
    if user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Authenticated user does not match request user")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a local signed API bearer token")
    parser.add_argument("user_id")
    parser.add_argument("--expires-in", type=int)
    args = parser.parse_args()
    print(create_access_token(args.user_id, expires_in=args.expires_in))


if __name__ == "__main__":
    main()
