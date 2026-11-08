"""People who sign in to the web app, each in one organisation.

    uv run --env-file .env python -m shipready.users add --email rahul@example.com --name "Rahul"

The password is asked for without echoing it, or read from standard input with
--password-stdin (for scripts). Emails are kept lowercase, so sign-in ignores their case.
"""

import argparse
import getpass
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shipready.db.models import Organization, User
from shipready.db.seed import DEMO_ORG_ID
from shipready.db.session import make_engine
from shipready.passwords import hash_password


def normalise_email(email: str) -> str:
    return email.strip().casefold()


def add_user(session: Session, org_id: uuid.UUID, email: str, name: str, password: str) -> User:
    """Store a new user; a malformed or taken email, an unknown organisation or a short
    password is an error with the reason."""
    address = normalise_email(email)
    local, _, domain = address.partition("@")
    if not local or "." not in domain or " " in address:
        raise ValueError(f"{email!r} is not an email address")
    if not name.strip():
        raise ValueError("a user needs a name")
    if session.get(Organization, org_id) is None:
        raise ValueError(f"no organisation {org_id}")
    user = User(
        org_id=org_id, email=address, name=name.strip(), password_hash=hash_password(password)
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ValueError(f"{address} already has an account") from None
    return user


def find_user(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == normalise_email(email)))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Manage the people who sign in.")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="create a user")
    add.add_argument("--email", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--org", type=uuid.UUID, default=DEMO_ORG_ID, help="organisation ID")
    add.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    args = parser.parse_args(argv)

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Password again: ") != password:
            parser.error("the passwords differ")
    engine = make_engine()
    try:
        with Session(engine) as session:
            user = add_user(session, args.org, args.email, args.name, password)
            print(f"added {user.email} to organisation {user.org_id}")
    except ValueError as error:
        parser.error(str(error))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
