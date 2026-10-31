"""The pages of the live inventories: what Manuel shows in a live on Tilt, and the presets he starts one from."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import items, lives
from cards_warehouse.money import parse_euros
from cards_warehouse.pages import copies, templates

router = APIRouter()


class SoldForm(BaseModel):
    """A row of copies sold in the live, as typed: it goes back into the page when something must be fixed."""

    item_id: str = ""
    quantity: str = "1"
    # What the buyer paid for each copy.
    price: str = ""


class _Refused(Exception):
    """What was typed cannot be saved: the message says why."""


@router.get("/lives")
def live_list(request: Request):
    with request.app.state.engine.connect() as connection:
        inventories = lives.inventories(connection)
        presets = lives.presets(connection)
    return templates.TemplateResponse(request, "lives.html", {"inventories": inventories, "presets": presets})


# Empty, or with the items of the preset chosen.
@router.post("/lives")
def new_inventory(request: Request, preset: Annotated[int | None, Form()] = None):
    with request.app.state.engine.begin() as connection:
        inventory_id = lives.start(connection, preset)
    return RedirectResponse(f"/lives/{inventory_id}", status_code=303)


# The items found by the search are offered under the inventory, to add them with a tap.
@router.get("/lives/{inventory_id}")
def inventory_page(request: Request, inventory_id: int, q: str = ""):
    return _inventory_page(request, inventory_id, q)


@router.post("/lives/{inventory_id}/items")
def add_item(request: Request, inventory_id: int, item_id: Annotated[int, Form()]):
    with request.app.state.engine.begin() as connection:
        lives.add(connection, inventory_id, item_id)
    return RedirectResponse(f"/lives/{inventory_id}", status_code=303)


@router.post("/lives/{inventory_id}/remove")
def remove_item(request: Request, inventory_id: int, item_id: Annotated[int, Form()]):
    with request.app.state.engine.begin() as connection:
        lives.remove(connection, inventory_id, item_id)
    return RedirectResponse(f"/lives/{inventory_id}", status_code=303)


# At the end of the live: copies sold at different prices, as at an auction, go on rows of their own.
@router.post("/lives/{inventory_id}/sold")
def add_sold(request: Request, inventory_id: int, form: Annotated[SoldForm, Form()]):
    try:
        quantity, price = _quantity(form.quantity), _price(form.price)
    except _Refused as refusal:
        return _inventory_page(request, inventory_id, sold_form=form, sold_error=str(refusal), status_code=422)
    with request.app.state.engine.begin() as connection:
        lives.sold(connection, inventory_id, int(form.item_id), quantity, price)
    return RedirectResponse(f"/lives/{inventory_id}", status_code=303)


@router.post("/lives/{inventory_id}/unsold")
def remove_sold(request: Request, inventory_id: int, row_id: Annotated[int, Form()]):
    with request.app.state.engine.begin() as connection:
        lives.unsold(connection, inventory_id, row_id)
    return RedirectResponse(f"/lives/{inventory_id}", status_code=303)


# All the rows, or none: one refused leaves them all to confirm, once fixed.
@router.post("/lives/{inventory_id}/confirm")
def confirm(request: Request, inventory_id: int):
    try:
        with request.app.state.engine.begin() as connection:
            lives.confirm(connection, inventory_id, request.app.state.channel_operations)
    except lives.NotEnoughCopies as refusal:
        error = f"{refusal.name} ha {copies(refusal.available)}: non puoi venderne {refusal.quantity}."
        return _inventory_page(request, inventory_id, sold_error=error, status_code=422)
    return RedirectResponse(f"/lives/{inventory_id}", status_code=303)


# On the page of the lives, where the preset is offered from then on.
@router.post("/lives/{inventory_id}/preset")
def save_as_preset(request: Request, inventory_id: int, name: Annotated[str, Form()]):
    try:
        if not name.strip():
            raise _Refused("Scrivi il nome della configurazione.")
        with request.app.state.engine.begin() as connection:
            if lives.save_as_preset(connection, inventory_id, name.strip()) is None:
                raise _Refused(f"La configurazione {name.strip()} c'è già.")
    except _Refused as refusal:
        return _inventory_page(request, inventory_id, preset_name=name, error=str(refusal), status_code=422)
    return RedirectResponse("/lives", status_code=303)


def _quantity(text: str) -> int:
    try:
        quantity = int(text)
    except ValueError:
        quantity = 0
    if quantity < 1:
        raise _Refused("Le copie sono almeno 1.")
    return quantity


def _price(text: str) -> int:
    try:
        price = parse_euros(text)
    except ValueError:
        raise _Refused(
            "Scrivi il prezzo di una copia in euro, con al massimo due decimali: per esempio 8,50."
        ) from None
    if price < 1:
        raise _Refused("Il prezzo vale almeno 0,01 €.")
    return price


def _inventory_page(
    request: Request,
    inventory_id: int,
    q: str = "",
    preset_name: str = "",
    error: str = "",
    sold_form: SoldForm | None = None,
    sold_error: str = "",
    status_code: int = 200,
):
    with request.app.state.engine.connect() as connection:
        rows = lives.rows(connection, inventory_id)
        found = items.search(connection, q) if q.strip() else []
        entered = lives.entered(connection, inventory_id)
        report = lives.report(connection, inventory_id)
    return templates.TemplateResponse(
        request,
        "live.html",
        {
            "inventory_id": inventory_id,
            "rows": rows,
            "q": q,
            "found": found,
            "entered": entered,
            "report": report,
            "sold_form": sold_form or SoldForm(),
            "sold_error": sold_error,
            "preset_name": preset_name,
            "error": error,
        },
        status_code=status_code,
    )
