"""Password hashing with scrypt from Python's standard library (Decision.md D-36).

Each hash carries its own random salt and the scrypt settings it was made with, so the settings
can be raised later without making older hashes unreadable. Hashes are compared in constant time.
"""

import base64
import hashlib
import hmac
import secrets

# One of OWASP's equally strong scrypt settings: 2^15 blocks of 8 in 3 lanes. Its 32 MiB per
# sign-in suits a small API server better than the 128 MiB of 2^17 in one lane (1.3 s against
# 1.7 s on a development laptop).
COST, BLOCK_SIZE, PARALLELISM = 2**15, 8, 3
SALT_BYTES, KEY_BYTES = 16, 32
# Kept short at the user's request for demo logins (Decision.md D-39); revisit before a public URL.
MIN_PASSWORD_CHARS = 4
SCHEME = "scrypt"


def hash_password(password: str) -> str:
    """The stored form of `password`: scheme, settings, salt and key, separated by $."""
    if len(password) < MIN_PASSWORD_CHARS:
        raise ValueError(f"a password needs at least {MIN_PASSWORD_CHARS} characters")
    salt = secrets.token_bytes(SALT_BYTES)
    key = _scrypt(password, salt, COST, BLOCK_SIZE, PARALLELISM)
    return "$".join([SCHEME, str(COST), str(BLOCK_SIZE), str(PARALLELISM), _b64(salt), _b64(key)])


def check_password(password: str, stored: str) -> bool:
    """Whether `password` is the one `stored` was made from. A stored value of another shape is
    an error, never a quiet "no": it means the users table is damaged."""
    try:
        scheme, cost, block_size, parallelism, salt, key = stored.split("$")
        if scheme != SCHEME:
            raise ValueError(f"unknown scheme {scheme!r}")
        expected = base64.b64decode(key, validate=True)
        actual = _scrypt(
            password,
            base64.b64decode(salt, validate=True),
            int(cost),
            int(block_size),
            int(parallelism),
        )
    except ValueError as error:
        raise ValueError(f"not a stored password: {error}") from error
    return hmac.compare_digest(actual, expected)


def _scrypt(password: str, salt: bytes, cost: int, block_size: int, parallelism: int) -> bytes:
    return hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=cost,
        r=block_size,
        p=parallelism,
        # scrypt needs 128 * cost * block_size bytes; Python's default ceiling is 32 MiB.
        maxmem=256 * cost * block_size,
        dklen=KEY_BYTES,
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()
