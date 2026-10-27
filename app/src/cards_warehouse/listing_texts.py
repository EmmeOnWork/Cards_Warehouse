"""The texts of a listing: the title and the description an item is offered with, the same on every channel.

`generate` makes them from the item's fields, and is only calculation. Manuel edits them to add a detail the fields
do not have: his texts are kept, and shown in their place.
"""

from dataclasses import dataclass

from sqlalchemy import Column, Connection, Integer, Table, Text, select
from sqlalchemy.dialects import postgresql

from cards_warehouse import channels, items
from cards_warehouse.database import metadata
from cards_warehouse.items import CONDITIONS, LANGUAGES, Condition, Grading, Item, Sealed, grade_text


@dataclass(frozen=True)
class Texts:
    title: str
    description: str


@dataclass(frozen=True)
class ItemTexts:
    """The texts an item is offered with."""

    texts: Texts
    # Edited by Manuel: they no longer follow the item's fields.
    edited: bool
    # The characters of the tightest title among the channels, or None when none sets a limit.
    title_limit: int | None


class TitleTooLong(Exception):
    def __init__(self, length: int, limit: int) -> None:
        super().__init__(f"{length} characters, at most {limit}")
        self.length = length
        self.limit = limit


edited_texts = Table(
    "listing_texts",
    metadata,
    Column("item_id", Integer, primary_key=True),
    Column("title", Text),
    Column("description", Text),
)


def of_item(connection: Connection, item_id: int) -> ItemTexts:
    """Manuel's texts where he edited them; elsewhere those made from the fields, the title in the tightest channel."""
    limit = channels.title_limit(connection)
    generated = generate(items.get(connection, item_id), limit)
    edited = connection.execute(select(edited_texts).where(edited_texts.c.item_id == item_id)).one_or_none()
    if edited is None:
        return ItemTexts(generated, False, limit)
    texts = Texts(edited.title or generated.title, edited.description or generated.description)
    return ItemTexts(texts, True, limit)


def edit(connection: Connection, item_id: int, texts: Texts) -> None:
    """Manuel's texts, kept from now on in place of those made from the fields. A text sent back as it was made
    keeps following them. TitleTooLong when the title does not fit the tightest channel: it goes on all of them."""
    limit = channels.title_limit(connection)
    if limit is not None and len(texts.title) > limit:
        raise TitleTooLong(len(texts.title), limit)
    generated = generate(items.get(connection, item_id), limit)
    title = None if texts.title == generated.title else texts.title
    description = None if texts.description == generated.description else texts.description
    if title is None and description is None:
        regenerate(connection, item_id)
        return
    new = postgresql.insert(edited_texts).values(item_id=item_id, title=title, description=description)
    connection.execute(
        new.on_conflict_do_update(
            index_elements=[edited_texts.c.item_id],
            set_={"title": new.excluded.title, "description": new.excluded.description},
        )
    )


def regenerate(connection: Connection, item_id: int) -> None:
    """Manuel's texts let go: the texts are made from the fields again, and follow them."""
    connection.execute(edited_texts.delete().where(edited_texts.c.item_id == item_id))


# In the title, short: as buyers search them, and as on Cardmarket for the conditions.
_LANGUAGE_CODES = {
    "it": "ITA",
    "en": "ENG",
    "ja": "JAP",
    "fr": "FRA",
    "de": "GER",
    "es": "ESP",
    "pt": "POR",
    "ko": "KOR",
    "zh": "CHN",
}
_CONDITION_CODES = {
    Condition.MINT: "MT",
    Condition.NEAR_MINT: "NM",
    Condition.EXCELLENT: "EX",
    Condition.GOOD: "GD",
    Condition.LIGHT_PLAYED: "LP",
    Condition.PLAYED: "PL",
    Condition.POOR: "PO",
}


# When a title is too long its parts go, whole, in their turn: game, variant, set. The others always stay: what
# tells the item apart and what makes its price.
_ALWAYS, _GAME, _VARIANT, _SET = 0, 1, 2, 3


def generate(item: Item, title_limit: int | None = None) -> Texts:
    """The texts of the item's listings. The title fits in `title_limit` characters, when there is one."""
    parts, lines = _fields(item)
    title = _title(parts) if title_limit is None else _fitted(parts, title_limit)
    description = "\n".join([item.name, ""] + [f"{label}: {value}" for label, value in lines if value])
    return Texts(title, description)


def _fitted(parts: list[tuple[str, int]], limit: int) -> str:
    """The title in `limit` characters: its parts go in their turn, then the name loses its last words."""
    title = _title(parts)
    for goes in (_GAME, _VARIANT, _SET):
        if len(title) <= limit:
            return title
        parts = [(part, turn) for part, turn in parts if turn != goes]
        title = _title(parts)
    if len(title) <= limit:
        return title
    # The name is the first part. What follows it can only get shorter once the name is cut.
    rest = _title(parts[1:])
    title = _title([(_cut(parts[0][0], limit - len(rest) - 1), _ALWAYS), *parts[1:]])
    # A limit too tight even for the parts that always stay.
    return title if len(title) <= limit else _cut(title, limit)


def _title(parts: list[tuple[str, int]]) -> str:
    title = ""
    for part, _ in parts:
        # The name of a sealed often says already what it is. Whole words: the set 151 is not in the number 151/165.
        if part and f" {part.casefold()} " not in f" {title.casefold()} ":
            title = f"{title} {part}".lstrip()
    return title


def _cut(text: str, room: int) -> str:
    """The first words of the text that fit in `room` characters. Half a word only when not even one fits."""
    cut = ""
    for word in text.split():
        if len(f"{cut} {word}".lstrip()) > room:
            break
        cut = f"{cut} {word}".lstrip()
    return cut or text[: max(room, 0)].strip()


def _fields(item: Item) -> tuple[list[tuple[str, int]], list[tuple[str, str]]]:
    """The parts of the title in their order, each with its turn to go, and the lines of the description."""
    language_code, language = _LANGUAGE_CODES[item.language], LANGUAGES[item.language]
    name, game = (item.name, _ALWAYS), (item.game, _GAME)
    details = item.details
    if isinstance(details, Sealed):
        parts = [name, (details.product_type, _ALWAYS), (details.set_name, _SET), (language_code, _ALWAYS), game]
        return parts, [
            ("Gioco", item.game),
            ("Tipo di prodotto", details.product_type),
            ("Set", details.set_name),
            ("Lingua", language),
        ]
    if details is None:
        return [name, (language_code, _ALWAYS), game], [("Gioco", item.game), ("Lingua", language)]
    if isinstance(details.state, Grading):
        grading = f"{details.state.grader} {grade_text(details.state.grade)}"
        state, state_line = grading, ("Gradazione", grading)
    else:
        state, state_line = _CONDITION_CODES[details.state], ("Condizione", CONDITIONS[details.state])
    parts = [
        name,
        (details.number, _ALWAYS),
        (details.set_name, _SET),
        (details.variant, _VARIANT),
        (language_code, _ALWAYS),
        (state, _ALWAYS),
        game,
    ]
    return parts, [
        ("Gioco", item.game),
        ("Set", details.set_name),
        ("Numero", details.number),
        ("Variante", details.variant),
        ("Lingua", language),
        state_line,
    ]
