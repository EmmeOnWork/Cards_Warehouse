"""Partners: the people who share the cost and the takings of a purchase with Manuel. Data, edited from the app."""

from dataclasses import dataclass

from sqlalchemy import Column, Connection, Integer, Table, Text, select, update
from sqlalchemy.dialects import postgresql

from cards_warehouse.database import metadata

partners = Table("partners", metadata, Column("id", Integer, primary_key=True), Column("name", Text))


@dataclass(frozen=True)
class Partner:
    id: int
    name: str


def every(connection: Connection) -> list[Partner]:
    """In alphabetical order."""
    return [Partner(*row) for row in connection.execute(select(partners).order_by(partners.c.name))]


def one(connection: Connection, partner_id: int) -> Partner | None:
    row = connection.execute(select(partners).where(partners.c.id == partner_id)).one_or_none()
    return None if row is None else Partner(*row)


def rename(connection: Connection, partner_id: int, name: str) -> bool:
    """False when the name is another partner's. The purchases the partner shares follow the new name."""
    taken = select(partners.c.id).where(partners.c.name == name, partners.c.id != partner_id)
    if connection.execute(taken).first() is not None:
        return False
    connection.execute(update(partners).where(partners.c.id == partner_id).values(name=name))
    return True


def add(connection: Connection, name: str) -> int | None:
    """None when the name is taken: two partners with one name could not be told apart on a purchase."""
    return connection.execute(
        postgresql.insert(partners)
        .values(name=name)
        .on_conflict_do_nothing(index_elements=[partners.c.name])
        .returning(partners.c.id)
    ).scalar_one_or_none()
