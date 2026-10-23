"""The pages of the items: the list, and the load of an item with its first lot."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import items, stock
from cards_warehouse.items import Item, Kind
from cards_warehouse.money import parse_euros
from cards_warehouse.pages import templates

# What the pages call each kind of item.
templates.env.globals["kinds"] = {
    Kind.SINGLE_CARD: "Carta singola",
    Kind.SEALED: "Sealed",
    Kind.MAGAZINE: "Rivista",
    Kind.BULK: "Bulk",
}
# The bulk is left out: it is born from an opening, with a rough count of its cards.
LOADABLE = (Kind.SINGLE_CARD, Kind.SEALED, Kind.MAGAZINE)
templates.env.globals["loadable"] = LOADABLE
# A choice from a list, as the PRD wants, but not data like the games: a new language is a line here.
templates.env.globals["languages"] = {
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

router = APIRouter()


class LoadForm(BaseModel):
    """The fields of the load page, as typed: they go back into the page when something must be fixed."""

    kind: str = ""
    game: str = ""
    new_game: str = ""
    name: str = ""
    language: str = ""
    quantity: str = "1"
    unit_cost: str = ""
    unknown_cost: bool = False
    notes: str = ""
    location: str = ""


class _Refused(Exception):
    """What Manuel typed cannot be saved: the message tells him why."""


@router.get("/items")
def item_list(request: Request):
    with request.app.state.engine.connect() as connection:
        listed = items.listing(connection)
    return templates.TemplateResponse(request, "items.html", {"listed": listed})


@router.get("/items/new")
def load_page(request: Request):
    return _load_page(request, LoadForm())


@router.post("/items")
def load_item(request: Request, form: Annotated[LoadForm, Form()]):
    try:
        item, quantity, unit_cost_cents = _read(form)
    except _Refused as refusal:
        return _load_page(request, form, error=str(refusal), status_code=422)
    # The item and its first lot together, or neither.
    with request.app.state.engine.begin() as connection:
        item_id = items.add(connection, item)
        stock.load(connection, item_id, quantity, unit_cost_cents)
    return RedirectResponse("/items", status_code=303)


def _read(form: LoadForm) -> tuple[Item, int, int | None]:
    if form.kind not in LOADABLE:
        raise _Refused("Scegli il tipo: carta singola, sealed o rivista.")
    item = Item(
        kind=Kind(form.kind),
        game=form.new_game.strip() or form.game,
        name=form.name.strip(),
        language=form.language,
        notes=form.notes.strip(),
        location=form.location.strip(),
    )
    return item, _quantity(form.quantity), None if form.unknown_cost else _known_cost(form.unit_cost)


def _quantity(text: str) -> int:
    try:
        quantity = int(text)
    except ValueError:
        quantity = 0
    if quantity < 1:
        raise _Refused("Le copie sono almeno 1.")
    return quantity


def _known_cost(text: str) -> int:
    if not text.strip():
        raise _Refused("Scrivi il costo di una copia, oppure spunta «Costo sconosciuto».")
    try:
        cents = parse_euros(text)
    except ValueError:
        raise _Refused("Scrivi il costo in euro, con al massimo due decimali: per esempio 12,50.") from None
    if cents < 1:
        raise _Refused("Il costo vale almeno 0,01 €: se non lo conosci, spunta «Costo sconosciuto».")
    return cents


def _load_page(request: Request, form: LoadForm, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        games = items.game_names(connection)
    return templates.TemplateResponse(
        request,
        "load.html",
        {"form": form, "games": games, "error": error},
        status_code=status_code,
    )
