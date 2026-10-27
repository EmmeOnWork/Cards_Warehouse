"""The opening of a box into packs, from the item's page: one copy at a time, into packs that exist or a new item."""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import items, openings, stock
from cards_warehouse.cost_split import TooSmallToSplit
from cards_warehouse.items import Item, Kind, Sealed
from cards_warehouse.money import format_euros
from cards_warehouse.pages import templates

router = APIRouter()


class OpeningForm(BaseModel):
    """The fields of an opening, as typed: they go back into the page when something must be fixed."""

    lot: str = "1"
    packs: str = ""
    # The id of the packs' item, or "" for a new one, named by pack_name.
    pack: str = ""
    pack_name: str = ""


class _Refused(Exception):
    """What Manuel typed cannot be saved: the message says why."""


@router.get("/items/{item_id}/opening")
def opening_page(request: Request, item_id: int):
    return _page(request, item_id, OpeningForm())


@router.post("/items/{item_id}/opening")
def open_box(request: Request, item_id: int, form: Annotated[OpeningForm, Form()]):
    try:
        # The new packs' item and the opening together, or neither: a refusal takes the item away with it.
        with request.app.state.engine.begin() as connection:
            lot = next((lot for lot in stock.lots(connection, item_id) if str(lot.number) == form.lot), None)
            if lot is None:
                raise _Refused("Scegli il lotto da aprire.")
            packs = _packs(form.packs)
            packs_item = int(form.pack) if form.pack else _new_packs(connection, item_id, form.pack_name)
            openings.into_packs(connection, lot.id, packs_item, packs)
    except _Refused as refusal:
        error = str(refusal)
    except stock.NotEnoughStock:
        error = f"Il lotto {lot.number} non ha copie da aprire."
    except TooSmallToSplit:
        error = f"Il costo del lotto, {format_euros(lot.unit_cost_cents)} €, non basta a dare 0,01 € a ogni busta."
    else:
        # On the packs' page, where their photos are added.
        return RedirectResponse(f"/items/{packs_item}", status_code=303)
    return _page(request, item_id, form, error=error, status_code=422)


def _packs(text: str) -> int:
    try:
        packs = int(text)
    except ValueError:
        packs = 0
    if packs < 1:
        raise _Refused("Le buste sono almeno 1.")
    return packs


def _new_packs(connection, box_item_id: int, name: str) -> int:
    """A new item for the packs, typed only by its name: game, language and set are the box's."""
    if not name.strip():
        raise _Refused("Scrivi il nome della busta nuova, oppure scegline una.")
    box = items.get(connection, box_item_id)
    set_name = box.details.set_name if isinstance(box.details, Sealed) else ""
    packs = Item(Kind.SEALED, box.game, name.strip(), box.language, details=Sealed("Busta", set_name))
    return items.add(connection, packs)


def _page(request: Request, item_id: int, form: OpeningForm, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        item = items.find(connection, item_id)
        if item is None:
            raise HTTPException(status_code=404)
        lots = stock.lots(connection, item_id)
        # The packs it may go into: the other sealed items of its game.
        packs = items.listing(
            connection,
            items.items.c.kind == Kind.SEALED,
            items.games.c.name == item.game,
            items.items.c.id != item_id,
        )
    return templates.TemplateResponse(
        request,
        "opening.html",
        {"item": item, "lots": lots, "packs": packs, "form": form, "error": error},
        status_code=status_code,
    )
