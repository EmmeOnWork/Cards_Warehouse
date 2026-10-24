"""The hash of the password, never the password itself: in Infisical at first, in the database once changed in the app.

`python -m cards_warehouse.password` (make password-hash) asks for a password and prints its hash.
"""

import getpass
import hashlib
import sys

from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import Column, Engine, Integer, Table, Text, select
from sqlalchemy.dialects import postgresql

from cards_warehouse.database import metadata

# Argon2id with OWASP's 19 MiB profile. The library's default takes 64 MiB per login, too close
# to the pod's 128 MiB limit (chart/values.yaml) once a few attempts arrive together.
_hasher = PasswordHasher(memory_cost=19 * 1024, time_cost=2, parallelism=1)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def check_password_hash(password_hash: str) -> None:
    try:
        extract_parameters(password_hash)
    except InvalidHashError:
        # Without the value: it may be the password itself, and the message ends up in the pod's log.
        raise ValueError(
            "PASSWORD_HASH is not an Argon2 hash: put in Infisical what make password-hash prints"
        ) from None


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


app_password = Table(
    "app_password",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("hash", Text),
    Column("replaces", Text),
)


class StoredPassword:
    """The password that opens the app: the one changed from the app, or the hash in Infisical before any change."""

    def __init__(self, engine: Engine, *, infisical_hash: str) -> None:
        check_password_hash(infisical_hash)
        self._engine = engine
        self._infisical_hash = infisical_hash

    def verify(self, password: str) -> bool:
        return verify_password(self._current_hash(), password)

    def change(self, password: str) -> None:
        row = {"id": 1, "hash": hash_password(password), "replaces": _fingerprint(self._infisical_hash)}
        upsert = postgresql.insert(app_password).values(row)
        with self._engine.begin() as connection:
            connection.execute(upsert.on_conflict_do_update(index_elements=[app_password.c.id], set_=row))

    def _current_hash(self) -> str:
        with self._engine.connect() as connection:
            changed = connection.execute(select(app_password.c.hash, app_password.c.replaces)).first()
        # Changed from the app over the hash Infisical still holds: the newer one. Otherwise Infisical's hash
        # came after it, a reset from the PC.
        if changed and changed.replaces == _fingerprint(self._infisical_hash):
            return changed.hash
        return self._infisical_hash


# Not the hash itself: a database backup need not carry a copy of the hash in Infisical.
def _fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode()).hexdigest()


if __name__ == "__main__":
    # Not echoed, and asked twice: a typo here would lock Manuel out.
    password = getpass.getpass("New password: ")
    if getpass.getpass("Again: ") != password:
        sys.exit("The two passwords differ: nothing printed.")
    print(hash_password(password))
