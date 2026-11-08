"""Sign-in: an email and password for a bearer token (PLAN.md Section 13; Decision.md D-36).

The token is the same signed JWT every endpoint already checks, naming the user by email, so
approvals record who decided. An unknown email and a wrong password get the same answer and take
the same time, so the API does not reveal which emails have accounts.
"""

from datetime import UTC, datetime, timedelta
from functools import cache

from fastapi import APIRouter, HTTPException, status

from shipready.api.auth import issue, secret
from shipready.api.deps import SessionDep
from shipready.api.schemas import LoginIn, LoginOut, UserOut
from shipready.passwords import check_password, hash_password
from shipready.users import find_user

router = APIRouter(prefix="/auth", tags=["auth"])
# A working day, or a month on a device the person asked to stay signed in on.
SESSION_LIFETIME = timedelta(hours=12)
REMEMBERED_LIFETIME = timedelta(days=30)
WRONG_CREDENTIALS = "that email and password don't match"


@router.post("/login")
def login(body: LoginIn, session: SessionDep) -> LoginOut:
    user = find_user(session, body.email)
    # An unknown email is checked against a stand-in hash, so it costs the same time.
    matches = check_password(body.password, user.password_hash if user else _stand_in())
    if user is None or not matches:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, WRONG_CREDENTIALS, headers={"WWW-Authenticate": "Bearer"}
        )
    lifetime = REMEMBERED_LIFETIME if body.remember else SESSION_LIFETIME
    return LoginOut(
        access_token=issue(user.email, user.org_id, lifetime, secret()),
        expires_at=datetime.now(UTC) + lifetime,
        user=UserOut.model_validate(user),
    )


@cache
def _stand_in() -> str:
    return hash_password("stand-in password for unknown emails")
