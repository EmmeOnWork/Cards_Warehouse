"""Amounts of money: euros, kept as a whole number of cents, never as a float. And the percentages taken of them."""

import re
from decimal import Decimal

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


def format_euros(cents: int) -> str:
    """An amount as a person reads it, and as parse_euros reads it back: 1999 is "19,99". A loss, never typed but
    shown, has a minus: -250 is "-2,50"."""
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100},{abs(cents) % 100:02d}"


# Up to 999,99%, as the database keeps it: a fee stays below 100, a target margin can be above it.
_PERCENT = re.compile(r"([0-9]{1,3})(?:[.,]([0-9]{1,2}))?")


def parse_percent(text: str) -> Decimal:
    """A percentage as a person types it: "2,5" is 2.5."""
    match = _PERCENT.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"not a percentage: {text!r}")
    whole, decimals = match.groups()
    return Decimal(f"{whole}.{decimals or 0}")


def format_percent(percent: Decimal) -> str:
    """A percentage as a person reads it, and as parse_percent reads it back: 2.50 is "2,5"."""
    return f"{percent.normalize():f}".replace(".", ",")
