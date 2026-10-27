"""Items: what a thing for sale is and how it looks. How many copies there are, and at what cost, is stock."""

import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from sqlalchemy import Column, Connection, Date, Integer, Numeric, Table, Text, func, insert, select
from sqlalchemy.dialects import postgresql

from cards_warehouse import stock
from cards_warehouse.database import metadata


class Kind(StrEnum):
    SINGLE_CARD = "single_card"
    SEALED = "sealed"
    # Promo cards are single cards: a magazine is the magazine, with whatever comes in it.
    MAGAZINE = "magazine"
    # The cards of a game not worth a listing, kept together and counted roughly. Born from an opening.
    BULK = "bulk"


class Condition(StrEnum):
    """The state of a card not graded, on the scale of Cardmarket: the one European buyers know."""

    MINT = "mint"
    NEAR_MINT = "near_mint"
    EXCELLENT = "excellent"
    GOOD = "good"
    LIGHT_PLAYED = "light_played"
    PLAYED = "played"
    POOR = "poor"


# In English, as on Cardmarket and as buyers write them.
CONDITIONS = {
    Condition.MINT: "Mint",
    Condition.NEAR_MINT: "Near Mint",
    Condition.EXCELLENT: "Excellent",
    Condition.GOOD: "Good",
    Condition.LIGHT_PLAYED: "Light Played",
    Condition.PLAYED: "Played",
    Condition.POOR: "Poor",
}

# A choice from a list, as the PRD wants, but not data like the games: a new language is a line here, and its
# short form in the titles of the listings.
LANGUAGES = {
    "it": "Italiano",
    "en": "Inglese",
    "ja": "Giapponese",
    "fr": "Francese",
    "de": "Tedesco",
    "es": "Spagnolo",
    "pt": "Portoghese",
    "ko": "Coreano",
    "zh": "Cinese",
}


@dataclass(frozen=True)
class Grading:
    """A card graded and sealed in its slab by a grader, such as PSA: a grade from 1 to 10, in half points."""

    grader: str
    grade: Decimal


def grade_text(grade: Decimal) -> str:
    """9,5 as Manuel writes it, and 10 rather than 10,0."""
    return f"{grade:.1f}".removesuffix(".0").replace(".", ",")


def parse_grade(text: str) -> Decimal:
    """A grade as a person types it, with a comma or a dot: "9,5" is 9.5. From 1 to 10, in half points, as eBay
    asks it of a graded card."""
    try:
        grade = Decimal(text.strip().replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"not a grade: {text!r}") from None
    # A NaN cannot be compared: it is refused before.
    if not grade.is_finite() or not 1 <= grade <= 10 or (grade * 2) % 1:
        raise ValueError(f"a grade goes from 1 to 10 in half points, not {text!r}")
    return grade


@dataclass(frozen=True)
class Card:
    """The fields of a single card. Two copies of a card in different states are two items."""

    # A card is in its condition, or graded: the grade takes the place of the condition.
    state: Condition | Grading
    set_name: str = ""
    number: str = ""
    variant: str = ""


@dataclass(frozen=True)
class Sealed:
    """The fields of a sealed product: a booster box, an ETB, a booster bundle."""

    product_type: str = ""
    set_name: str = ""


@dataclass(frozen=True)
class Item:
    kind: Kind
    game: str
    name: str
    language: str
    notes: str = ""
    location: str = ""
    # The fields of the kind. A magazine has none, and neither has a card loaded before they existed.
    details: Card | Sealed | None = None


games = Table("games", metadata, Column("id", Integer, primary_key=True), Column("name", Text))

items = Table(
    "items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("kind", Text),
    Column("game_id", Integer),
    Column("name", Text),
    Column("language", Text),
    Column("notes", Text),
    Column("location", Text),
    Column("set_name", Text),
    Column("card_number", Text),
    Column("variant", Text),
    Column("condition", Text),
    Column("grader", Text),
    Column("grade", Numeric(3, 1)),
    Column("product_type", Text),
    Column("fixed_price_cents", Integer),
    Column("reference_price_cents", Integer),
    Column("reference_price_on", Date),
    Column("reference_price_source", Text),
)


@dataclass(frozen=True)
class Reference:
    """A price Manuel found in his market research, the day he found it, and where: what a fixed price is based on."""

    price_cents: int
    found_on: date
    source: str


@dataclass(frozen=True)
class Listed:
    id: int
    name: str
    kind: Kind
    game: str
    available: int
    cost_unknown: bool
    details: Card | Sealed | None = None
    notes: str = ""


def find(connection: Connection, item_id: int) -> Listed | None:
    """The item, as the list shows it."""
    return next(iter(listing(connection, items.c.id == item_id)), None)


def listing(connection: Connection, *where) -> list[Listed]:
    """Every item with its quantity available, the last loaded first; only those matching `where`, if given."""
    stock_of = stock.of_items()
    rows = connection.execute(
        select(
            items,
            games.c.name.label("game"),
            func.coalesce(stock_of.c.available, 0).label("available"),
            func.coalesce(stock_of.c.cost_unknown, False).label("cost_unknown"),
        )
        .join_from(items, games, items.c.game_id == games.c.id)
        .outerjoin(stock_of, stock_of.c.item_id == items.c.id)
        .where(*where)
        .order_by(items.c.id.desc())
    )
    return [
        Listed(row.id, row.name, Kind(row.kind), row.game, row.available, row.cost_unknown, _details(row), row.notes)
        for row in rows
    ]


# The condition of the filters that keeps the graded cards, which have a grade in its place.
GRADED = "graded"


@dataclass(frozen=True)
class Filters:
    """What the list of items is narrowed to: a filter left empty keeps every item. The items sold out are left out,
    unless asked for."""

    kind: str = ""
    game: str = ""
    language: str = ""
    condition: str = ""
    sold_out: bool = False


# The list as it opens: every item with copies available.
UNFILTERED = Filters()


def search(connection: Connection, text: str, filters: Filters = UNFILTERED) -> list[Listed]:
    """The items with each word of the text in their name, set, number or notes, in any case and with or without
    accents, among those the filters keep. The words can be in different fields, and in any order."""
    # PostgreSQL ignores accents only with the unaccent extension: for a few hundred items, Python does it.
    words = _folded(text).split()
    return [
        item
        for item in listing(connection, *_kept_by(filters))
        if (item.available or filters.sold_out) and all(word in _searched(item) for word in words)
    ]


def _searched(item: Listed) -> str:
    """The fields the search looks in, folded. One per line: a text is not found across two of them."""
    fields = [item.name, item.notes]
    if isinstance(item.details, Card | Sealed):
        fields.append(item.details.set_name)
    if isinstance(item.details, Card):
        fields.append(item.details.number)
    return _folded("\n".join(fields))


def _folded(text: str) -> str:
    """The text as the search compares it, without case and accents: "Pokémon" is "pokemon"."""
    return "".join(char for char in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(char))


def _kept_by(filters: Filters):
    if filters.kind:
        yield items.c.kind == filters.kind
    if filters.game:
        yield games.c.name == filters.game
    if filters.language:
        yield items.c.language == filters.language
    if filters.condition == GRADED:
        yield items.c.grade.is_not(None)
    elif filters.condition:
        yield items.c.condition == filters.condition


def _details(row) -> Card | Sealed | None:
    if row.kind == Kind.SEALED:
        return Sealed(row.product_type, row.set_name)
    if row.kind != Kind.SINGLE_CARD:
        return None
    if row.grade is not None:
        state = Grading(row.grader, row.grade)
    elif row.condition is not None:
        state = Condition(row.condition)
    else:
        return None
    return Card(state, row.set_name, row.card_number, row.variant)


def game_names(connection: Connection) -> list[str]:
    return list(connection.execute(select(games.c.name).order_by(games.c.name)).scalars())


# The fields of free text whose values are suggested again in the same game: typed once, then picked, so that
# a set is written the same way every time. The sets of Pokémon are not offered for One Piece.
SUGGESTED = ("set_name", "variant", "product_type")


def suggestions(connection: Connection) -> dict[str, dict[str, list[str]]]:
    """For each game, the values already typed in each field of SUGGESTED, in alphabetical order."""
    by_game: dict[str, dict[str, list[str]]] = {}
    for field in SUGGESTED:
        typed = items.c[field]
        rows = connection.execute(
            select(games.c.name, typed)
            .distinct()
            .join_from(items, games, items.c.game_id == games.c.id)
            .where(typed != "")
            .order_by(games.c.name, typed)
        )
        for game, value in rows:
            by_game.setdefault(game, {}).setdefault(field, []).append(value)
    return by_game


def graders(connection: Connection) -> list[str]:
    """The graders already typed, in every game: PSA grades the cards of all of them."""
    typed = select(items.c.grader).distinct().where(items.c.grader.is_not(None)).order_by(items.c.grader)
    return list(connection.execute(typed).scalars())


def add(connection: Connection, item: Item) -> int:
    """The item, in its game. A game not seen before is added on the spot, and offered from then on."""
    return connection.execute(insert(items).values(_values(connection, item)).returning(items.c.id)).scalar_one()


def get(connection: Connection, item_id: int) -> Item | None:
    """The item as it was loaded or last edited, to edit it again."""
    row = connection.execute(
        select(items, games.c.name.label("game"))
        .join_from(items, games, items.c.game_id == games.c.id)
        .where(items.c.id == item_id)
    ).one_or_none()
    if row is None:
        return None
    return Item(Kind(row.kind), row.game, row.name, row.language, row.notes, row.location, _details(row))


def update(connection: Connection, item_id: int, item: Item) -> None:
    """The item's data, all of them, as `add` saves them. Its stock is not touched: copies change by movements."""
    connection.execute(items.update().values(_values(connection, item)).where(items.c.id == item_id))


def fix_price(connection: Connection, item_id: int, cents: int | None) -> None:
    """The price of the item on every channel, in place of the one made from the target. None takes it away."""
    connection.execute(items.update().values(fixed_price_cents=cents).where(items.c.id == item_id))


def fixed_price(connection: Connection, item_id: int) -> int | None:
    return connection.execute(select(items.c.fixed_price_cents).where(items.c.id == item_id)).scalar_one_or_none()


def note_reference(connection: Connection, item_id: int, reference: Reference) -> None:
    """The reference price of the item, in place of the one noted before."""
    connection.execute(
        items.update()
        .values(
            reference_price_cents=reference.price_cents,
            reference_price_on=reference.found_on,
            reference_price_source=reference.source,
        )
        .where(items.c.id == item_id)
    )


def reference(connection: Connection, item_id: int) -> Reference | None:
    row = connection.execute(
        select(items.c.reference_price_cents, items.c.reference_price_on, items.c.reference_price_source).where(
            items.c.id == item_id, items.c.reference_price_cents.is_not(None)
        )
    ).one_or_none()
    return None if row is None else Reference(*row)


def _values(connection: Connection, item: Item) -> dict:
    new_game = postgresql.insert(games).values(name=item.game)
    # On a game that exists the update changes nothing, but makes RETURNING give its id.
    game = new_game.on_conflict_do_update(index_elements=[games.c.name], set_={"name": new_game.excluded.name})
    return {
        "kind": item.kind,
        "game_id": connection.execute(game.returning(games.c.id)).scalar_one(),
        "name": item.name,
        "language": item.language,
        "notes": item.notes,
        "location": item.location,
        # A card turned into a sealed by an edit keeps none of its card's fields.
        **_NO_DETAILS,
        **_columns(item.details),
    }


_NO_DETAILS = {
    "set_name": "",
    "card_number": "",
    "variant": "",
    "product_type": "",
    "condition": None,
    "grader": None,
    "grade": None,
}


def _columns(details: Card | Sealed | None) -> dict:
    if isinstance(details, Sealed):
        return {"product_type": details.product_type, "set_name": details.set_name}
    if isinstance(details, Card):
        columns = {"set_name": details.set_name, "card_number": details.number, "variant": details.variant}
        if isinstance(details.state, Grading):
            return {**columns, "grader": details.state.grader, "grade": details.state.grade}
        return {**columns, "condition": details.state}
    return {}
