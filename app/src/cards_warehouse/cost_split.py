"""The split of a cost: only arithmetic, no database. Used by purchases, openings and extractions from the bulk.

The parts always add up to the amount, to the cent, and none is below a cent: a copy that cost nothing would have
no margin in percent.
"""


class TooSmallToSplit(ValueError):
    """An amount that cannot give a cent to each part."""


def equal_parts(amount_cents: int, parts: int) -> list[int]:
    """The amount in parts that differ by a cent at most: the cents left over go one each to the first ones."""
    if amount_cents < parts:
        raise TooSmallToSplit(f"{amount_cents} cents cannot give a cent to each of {parts} parts")
    share, left_over = divmod(amount_cents, parts)
    return [share + 1] * left_over + [share] * (parts - left_over)
