"""Bearer tokens: signed JWTs that name the user and their organisation (PLAN.md Section 13).

Every request is scoped to the organisation in its token. Until the web app's login exists
(Phase 17), `python -m shipready.api.token` issues tokens for development.
"""

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ALGORITHM = "HS256"
AUDIENCE = "shipready-api"
SECRET_VARIABLE = "SHIPREADY_JWT_SECRET"
# HS256 is only as strong as its key; RFC 7518 asks for at least 256 bits.
MIN_SECRET_BYTES = 32


@dataclass(frozen=True)
class Principal:
    user: str
    org_id: uuid.UUID


class AuthError(ValueError):
    pass


def secret() -> str:
    value = os.environ.get(SECRET_VARIABLE, "")
    if len(value.encode()) < MIN_SECRET_BYTES:
        raise RuntimeError(
            f"{SECRET_VARIABLE} must be set to at least {MIN_SECRET_BYTES} bytes; "
            "see backend/.env.example"
        )
    return value


def issue(user: str, org_id: uuid.UUID, lifetime: timedelta, key: str) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": user,
        "org": str(org_id),
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + lifetime,
    }
    return jwt.encode(claims, key, algorithm=ALGORITHM)


def verify(token: str, key: str) -> Principal:
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            options={"require": ["sub", "org", "aud", "exp"]},
        )
        return Principal(user=str(claims["sub"]), org_id=uuid.UUID(str(claims["org"])))
    except (jwt.InvalidTokenError, ValueError) as error:
        raise AuthError(str(error)) from error


_bearer = HTTPBearer(auto_error=False)


def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify(credentials.credentials, secret())
    except AuthError:
        # The reason (expired, bad signature) stays out of the response.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
