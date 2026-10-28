"""Issue a development token for the API, until the web app's login exists (Phase 17).

uv run --env-file .env python -m shipready.api.token [--org UUID] [--user NAME] [--hours N]
"""

import argparse
import uuid
from datetime import timedelta

from shipready.api.auth import issue, secret
from shipready.db.seed import DEMO_ORG_ID


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Print a bearer token for the ShipReady API.")
    parser.add_argument("--org", type=uuid.UUID, default=DEMO_ORG_ID, help="organisation ID")
    parser.add_argument("--user", default="developer", help="user name to put in the token")
    parser.add_argument("--hours", type=float, default=8, help="how long the token is valid")
    args = parser.parse_args(argv)
    if not 0 < args.hours <= 24 * 30:
        parser.error("--hours must be between 0 and 720")
    print(issue(args.user, args.org, timedelta(hours=args.hours), secret()))


if __name__ == "__main__":
    main()
