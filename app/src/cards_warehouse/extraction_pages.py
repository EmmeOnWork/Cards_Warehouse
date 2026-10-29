"""The extractions, from the page of a bulk: a card of it taken out to be sold on its own, into a card that exists or
a new one. The card comes from the bulk's oldest lot, which Manuel does not choose."""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import exposure, items, openings, stock
from cards_warehouse.items import Card, Condition, Item, Kind
from cards_warehouse.pages import templates

router = APIRouter()


class ExtractionForm(BaseModel):
    """The card taken out, as typed: one that exists, or a new one by its name, set, number and condition. The fields
    go back into the page when something must be fixed."""

    # The id of the card's item, or "" for a new one.
    card: str = ""
    name: str = ""
    set_name: str = ""
    number: str = ""
    # A card worth taking out of the bulk is often just out of its pack.
    condition: str = Condition.NEAR_MINT


class _Refused(Exception):
    """What Manuel typed cannot be saved: the message says why."""


@router.get("/items/{item_id}/extraction")
def extraction_page(request: Request, item_id: int):
    return _page(request, item_id, ExtractionForm())


@router.post("/items/{item_id}/extraction")
def extract(request: Request, item_id: int, form: Annotated[ExtractionForm, Form()]):
    try:
        # The new card's item and the extraction together, or neither: a refusal takes the item away with it.
        with request.app.state.engine.begin() as connection:
            card = int(form.card) if form.card else _new_card(connection, item_id, form)
            openings.extract(connection, item_id, card)
            exposure.align(connection, card, request.app.state.channel_operations)
    except _Refused as refusal:
        error = str(refusal)
    except stock.NotEnoughStock:
        error = "Il bulk non ha più carte da estrarre."
    else:
        # On the card's page, where its photos and its price are added.
        return RedirectResponse(f"/items/{card}", status_code=303)
    return _page(request, item_id, form, error=error, status_code=422)


def _new_card(connection, bulk_item_id: int, form: ExtractionForm) -> int:
    """A new item for the card, of the bulk's game and language."""
    if not form.name.strip():
        raise _Refused("Scrivi il nome della carta nuova, oppure scegline una.")
    try:
        condition = Condition(form.condition)
    except ValueError:
        raise _Refused("Scegli la condizione della carta nuova.") from None
    bulk = items.get(connection, bulk_item_id)
    details = Card(condition, set_name=form.set_name.strip(), number=form.number.strip())
    return items.add(connection, Item(Kind.SINGLE_CARD, bulk.game, form.name.strip(), bulk.language, details=details))


def _page(request: Request, item_id: int, form: ExtractionForm, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        item = items.find(connection, item_id)
        if item is None or item.kind != Kind.BULK:
            raise HTTPException(status_code=404)
        # The cards it may go into: the single cards of its game and language.
        cards = items.listing(
            connection,
            items.items.c.kind == Kind.SINGLE_CARD,
            items.games.c.name == item.game,
            items.items.c.language == items.get(connection, item_id).language,
        )
    return templates.TemplateResponse(
        request,
        "extraction.html",
        {"item": item, "cards": cards, "form": form, "error": error},
        status_code=status_code,
    )
