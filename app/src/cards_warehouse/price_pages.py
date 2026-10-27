"""The price of an item, fixed by Manuel on the item's page after his market research, and the reference price he
based it on."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import items
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.items import Reference
from cards_warehouse.money import parse_euros
from cards_warehouse.pages import templates
from cards_warehouse.pricing import MarginWarning

router = APIRouter()

# What the prices on the item's page warn of: a loss more than a margin below the target.
templates.env.globals["margin_warnings"] = {
    MarginWarning.BELOW_TARGET: ("sotto l'obiettivo", "tag"),
    MarginWarning.LOSS: ("in perdita", "tag loss"),
}


class FixedPriceForm(BaseModel):
    fixed_price: str = ""


class ReferenceForm(BaseModel):
    reference_price: str = ""
    reference_on: str = ""
    reference_source: str = ""


# The fields on the item's page: most references are found the day they are noted.
templates.env.globals["new_reference"] = lambda: ReferenceForm(reference_on=_today().isoformat())


class _Refused(Exception):
    """What Manuel typed cannot be saved: the message tells him why."""


@router.post("/items/{item_id}/fixed-price")
def fix_price(request: Request, item_id: int, form: Annotated[FixedPriceForm, Form()]):
    try:
        cents = _price(form.fixed_price, "Il prezzo fissato")
    except _Refused as refusal:
        return _refused(request, item_id, "fixed_price_form.html", form, refusal)
    with request.app.state.engine.begin() as connection:
        items.fix_price(connection, item_id, cents)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


# The prices are made from the cost and the target again.
@router.post("/items/{item_id}/fixed-price/delete")
def take_fixed_price_away(request: Request, item_id: int):
    with request.app.state.engine.begin() as connection:
        items.fix_price(connection, item_id, None)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/reference-price")
def note_reference(request: Request, item_id: int, form: Annotated[ReferenceForm, Form()]):
    try:
        reference = _reference(form)
    except _Refused as refusal:
        return _refused(request, item_id, "reference_price_form.html", form, refusal)
    with request.app.state.engine.begin() as connection:
        items.note_reference(connection, item_id, reference)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


def _reference(form: ReferenceForm) -> Reference:
    price = _price(form.reference_price, "Il prezzo di riferimento")
    try:
        found_on = date.fromisoformat(form.reference_on.strip())
    except ValueError:
        raise _Refused("Scrivi il giorno in cui l'hai trovato, per esempio 2026-10-26.") from None
    source = form.reference_source.strip()
    if not source:
        raise _Refused("Scrivi dove hai trovato il prezzo: per esempio Cardmarket.")
    return Reference(price, found_on, source)


def _price(text: str, what: str) -> int:
    try:
        cents = parse_euros(text)
    except ValueError:
        raise _Refused("Scrivi il prezzo in euro, con al massimo due decimali: per esempio 125,00.") from None
    if cents < 1:
        raise _Refused(f"{what} vale almeno 0,01 €.")
    return cents


def _today() -> date:
    return datetime.now(LOCAL_TIME).date()


def _refused(request: Request, item_id: int, form_page: str, typed: BaseModel, refusal: _Refused):
    """The reason, and the form again with what was typed, to fix it."""
    return templates.TemplateResponse(
        request,
        "price_refused.html",
        {"reason": str(refusal), "item_id": item_id, "form_page": form_page, "typed": typed},
        status_code=422,
    )
