import pytest

from shipready import passwords

PASSWORD = "correct horse battery staple"


def test_passwords_are_salted_and_checked() -> None:
    first, second = passwords.hash_password(PASSWORD), passwords.hash_password(PASSWORD)
    assert first != second  # a salt of its own each time
    assert first.startswith("scrypt$32768$8$3$")
    assert PASSWORD not in first
    assert passwords.check_password(PASSWORD, first)
    assert not passwords.check_password("correct horse battery stapler", first)


def test_short_passwords_are_refused() -> None:
    with pytest.raises(ValueError, match="at least 4 characters"):
        passwords.hash_password("abc")
    assert passwords.check_password("abcd", passwords.hash_password("abcd"))


@pytest.mark.parametrize("stored", ["", "bcrypt$1$2$3$a$b", "scrypt$x$8$1$AAAA$AAAA", "a$b"])
def test_a_damaged_stored_password_is_an_error(stored: str) -> None:
    with pytest.raises(ValueError, match="not a stored password"):
        passwords.check_password(PASSWORD, stored)
