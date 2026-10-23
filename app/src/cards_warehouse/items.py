"""Items: what a thing for sale is and how it looks. How many copies there are, and at what cost, is stock."""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Column, Connection, Integer, Table, Text, func, insert, select
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


@dataclass(frozen=True)
class Item:
    kind: Kind
    game: str
    name: str
    language: str
    notes: str = ""
    location: str = ""


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
)


@dataclass(frozen=True)
class Listed:
    name: str
    kind: Kind
    game: str
    available: int
    cost_unknown: bool


def listing(connection: Connection) -> list[Listed]:
    """Every item with its quantity available, the last loaded first."""
    stock_of = stock.of_items()
    rows = connection.execute(
        select(
            items.c.name,
            items.c.kind,
            games.c.name,
            func.coalesce(stock_of.c.available, 0),
            func.coalesce(stock_of.c.cost_unknown, False),
        )
        .join_from(items, games, items.c.game_id == games.c.id)
        .outerjoin(stock_of, stock_of.c.item_id == items.c.id)
        .order_by(items.c.id.desc())
    )
    return [
        Listed(name, Kind(kind), game, available, cost_unknown) for name, kind, game, available, cost_unknown in rows
    ]


def game_names(connection: Connection) -> list[str]:
    return list(connection.execute(select(games.c.name).order_by(games.c.name)).scalars())


def add(connection: Connection, item: Item) -> int:
    """The item, in its game. A game not seen before is added on the spot, and offered from then on."""
    new_game = postgresql.insert(games).values(name=item.game)
    # On a game that exists the update changes nothing, but makes RETURNING give its id.
    game = new_game.on_conflict_do_update(index_elements=[games.c.name], set_={"name": new_game.excluded.name})
    game_id = connection.execute(game.returning(games.c.id)).scalar_one()
    return connection.execute(
        insert(items)
        .values(
            kind=item.kind,
            game_id=game_id,
            name=item.name,
            language=item.language,
            notes=item.notes,
            location=item.location,
        )
        .returning(items.c.id)
    ).scalar_one()
