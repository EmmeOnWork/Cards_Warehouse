"""The hash of the password: Infisical keeps it, never the password itself.

`python -m cards_warehouse.password` (make password-hash) asks for a password and prints its hash.
"""

import getpass
import sys

from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError

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


if __name__ == "__main__":
    # Not echoed, and asked twice: a typo here would lock Manuel out.
    password = getpass.getpass("New password: ")
    if getpass.getpass("Again: ") != password:
        sys.exit("The two passwords differ: nothing printed.")
    print(hash_password(password))
