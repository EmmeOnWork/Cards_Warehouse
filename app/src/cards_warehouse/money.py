"""Amounts of money: euros, kept as a whole number of cents, never as a float."""

import re

# Up to 9.999.999,99 €, so the cents fit the database's integer columns. At most two decimals, after a comma or
# a dot. No thousands separator: in "1.234" it would be a guess.
_EUROS = re.compile(r"([0-9]{1,7})(?:[.,]([0-9]{1,2}))?")


def parse_euros(text: str) -> int:
    """The cents of an amount as a person types it: "19,99" is 1999."""
    match = _EUROS.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"not an amount in euros: {text!r}")
    whole, decimals = match.groups()
    return int(whole) * 100 + int((decimals or "0").ljust(2, "0"))
