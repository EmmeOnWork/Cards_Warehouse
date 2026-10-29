"""The price of an item, fixed by Manuel on the item's page after his market research, and the reference price he
based it on. And the price forced on one channel only, such as for a promotion there. The listings follow each."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import channels, exposure, items
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


class ForcedPriceForm(BaseModel):
    # By its name, as the item's page lists the channels.
    channel: str = ""
    forced_price: str = ""


templates.env.globals["new_forced_price"] = ForcedPriceForm


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
        exposure.align(connection, item_id, request.app.state.channel_operations)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


# The prices are made from the cost and the target again.
@router.post("/items/{item_id}/fixed-price/delete")
def take_fixed_price_away(request: Request, item_id: int):
    with request.app.state.engine.begin() as connection:
        items.fix_price(connection, item_id, None)
        exposure.align(connection, item_id, request.app.state.channel_operations)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/forced-prices")
def force_price(request: Request, item_id: int, form: Annotated[ForcedPriceForm, Form()]):
    try:
        cents = _price(form.forced_price, "Il prezzo forzato")
    except _Refused as refusal:
        return _refused(request, item_id, "forced_price_form.html", form, refusal)
    with request.app.state.engine.begin() as connection:
        channels.force_price(connection, item_id, _channel_id(connection, form.channel), cents)
        exposure.align(connection, item_id, request.app.state.channel_operations)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


# The promotion over: the channel is back at the price of the others.
@router.post("/items/{item_id}/forced-prices/delete")
def take_forced_price_away(request: Request, item_id: int, form: Annotated[ForcedPriceForm, Form()]):
    with request.app.state.engine.begin() as connection:
        channels.force_price(connection, item_id, _channel_id(connection, form.channel), None)
        exposure.align(connection, item_id, request.app.state.channel_operations)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


def _channel_id(connection, name: str) -> int:
    channel = next((channel for channel in channels.every(connection) if channel.name == name), None)
    if channel is None:
        raise HTTPException(status_code=404)
    return channel.id


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
    with request.app.state.engine.connect() as connection:
        # What the form of a forced price offers.
        channel_names = [channel.name for channel in channels.every(connection)]
    return templates.TemplateResponse(
        request,
        "price_refused.html",
        {
            "reason": str(refusal),
            "item_id": item_id,
            "form_page": form_page,
            "typed": typed,
            "channel_names": channel_names,
        },
        status_code=422,
    )
