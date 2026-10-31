"""The pages of the sales: a sale recorded from the phone on one page, reached from the item found in the list, and
what it left: its real margin, and the actions on the channels where the item is still offered."""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import channels, exposure, items, listing_pages, manual_channels, sales, stock
from cards_warehouse.exposure import NoPrice, NothingToSell
from cards_warehouse.items import Kind
from cards_warehouse.money import parse_euros
from cards_warehouse.pages import copies, templates
from cards_warehouse.sales import AlreadyCancelled, Cancellation, NotEnoughCopies, Sale

# What the pages call the cause of a cancellation.
templates.env.globals["cancellation_causes"] = {
    Cancellation.RETURN: "Reso",
    Cancellation.ORDER_CANCELLED: "Ordine cancellato",
}

router = APIRouter()


class SaleForm(BaseModel):
    """The fields of a sale, as typed: they go back into the page when something must be fixed."""

    channel: str = ""
    quantity: str = "1"
    # Of the bulk, whose cards are counted roughly: all those it has, whatever the number typed.
    everything: str = ""
    # What the buyer paid for all the copies.
    price: str = ""
    # Empty: the fee of the channel's rule.
    fee: str = ""
    shipping: str = ""
    # The number of the lot within the item. Empty: the oldest first.
    lot: str = ""
    note: str = ""


class CancellationForm(BaseModel):
    cause: str = ""
    note: str = ""


class PutBackForm(BaseModel):
    channel: list[int] = []


class _Refused(Exception):
    """What Manuel typed cannot be saved: the message tells him why."""


@router.get("/items/{item_id}/sale")
def sale_page(request: Request, item_id: int):
    return _page(request, item_id, SaleForm())


@router.post("/items/{item_id}/sales")
def record_sale(request: Request, item_id: int, form: Annotated[SaleForm, Form()]):
    try:
        with request.app.state.engine.begin() as connection:
            item = items.find(connection, item_id)
            sale = _read(form, item_id, stock.lots(connection, item_id))
            sale_id = sales.record(connection, sale, request.app.state.channel_operations)
    except _Refused as refusal:
        error = str(refusal)
    except NotEnoughCopies as refusal:
        if form.lot:
            error = f"Il lotto {form.lot} ha {copies(refusal.available)}: non puoi venderne {form.quantity}."
        else:
            # As the page says what is left.
            left = "Carte nel bulk" if item and item.kind == Kind.BULK else "Copie disponibili"
            error = f"{left}: {refusal.available}. Non puoi venderne {form.quantity}."
    else:
        return RedirectResponse(f"/sales/{sale_id}", status_code=303)
    return _page(request, item_id, form, error=error, status_code=422)


@router.get("/sales/{sale_id}")
def sold_page(request: Request, sale_id: int):
    return _sold_page(request, sale_id, CancellationForm())


@router.post("/sales/{sale_id}/cancellation")
def cancel_sale(request: Request, sale_id: int, form: Annotated[CancellationForm, Form()]):
    if form.cause not in Cancellation:
        return _sold_page(request, sale_id, form, error="Scegli la causa dell'annullamento.", status_code=422)
    with request.app.state.engine.begin() as connection:
        if sales.one(connection, sale_id) is None:
            raise HTTPException(status_code=404)
        try:
            sales.cancel(connection, sale_id, Cancellation(form.cause), form.note.strip())
        # Cancelled twice, as with a double tap: its copies went back the first time.
        except AlreadyCancelled:
            pass
    return RedirectResponse(f"/sales/{sale_id}", status_code=303)


@router.post("/sales/{sale_id}/put-back")
def put_back(request: Request, sale_id: int, form: Annotated[PutBackForm, Form()]):
    try:
        with request.app.state.engine.begin() as connection:
            sale = sales.one(connection, sale_id)
            if sale is None:
                raise HTTPException(status_code=404)
            exposure.put_back(connection, sale.item_id, form.channel, request.app.state.channel_operations)
    except (NothingToSell, NoPrice) as refusal:
        return listing_pages.refused(request, sale.item_id, refusal)
    return RedirectResponse(f"/sales/{sale_id}", status_code=303)


def _sold_page(request: Request, sale_id: int, form: CancellationForm, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        sale = sales.one(connection, sale_id)
        if sale is None:
            raise HTTPException(status_code=404)
        item = items.get(connection, sale.item_id)
        actions = manual_channels.of_item(connection, sale.item_id)
        # Once cancelled: where its copies, back in the stock, may go on sale again.
        to_put_back = exposure.to_put_back(connection, sale.item_id) if sale.cancelled else []
    return templates.TemplateResponse(
        request,
        "sold.html",
        {
            "sale": sale,
            "name": item.name,
            "bulk": item.kind == Kind.BULK,
            "actions": actions,
            "to_put_back": to_put_back,
            "form": form,
            "error": error,
        },
        status_code=status_code,
    )


def _read(form: SaleForm, item_id: int, lots: list[stock.Lot]) -> Sale:
    if not form.channel.isdigit():
        raise _Refused("Scegli il canale della vendita.")
    lot_id = None
    if form.lot:
        lot_id = next((lot.id for lot in lots if str(lot.number) == form.lot), None)
        if lot_id is None:
            raise _Refused("Scegli il lotto della vendita.")
    price = _euros(form.price, "il prezzo")
    if price < 1:
        raise _Refused("Il prezzo vale almeno 0,01 €.")
    if form.everything:
        quantity = sum(lot.available for lot in lots)
        # Sent twice, as with a double tap: the first took every card.
        if not quantity:
            raise _Refused("Il bulk non ha più carte da vendere.")
    else:
        quantity = _quantity(form.quantity)
    return Sale(
        item_id,
        int(form.channel),
        quantity,
        price,
        fee_cents=_euros(form.fee, "la commissione") if form.fee.strip() else None,
        shipping_cents=_euros(form.shipping, "la spedizione") if form.shipping.strip() else 0,
        lot_id=lot_id,
        note=form.note.strip(),
    )


def _quantity(text: str) -> int:
    try:
        quantity = int(text)
    except ValueError:
        quantity = 0
    if quantity < 1:
        raise _Refused("Le copie sono almeno 1.")
    return quantity


def _euros(text: str, what: str) -> int:
    try:
        return parse_euros(text)
    except ValueError:
        raise _Refused(f"Scrivi {what} in euro, con al massimo due decimali: per esempio 12,50.") from None


def _page(request: Request, item_id: int, form: SaleForm, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        item = items.find(connection, item_id)
        if item is None:
            raise HTTPException(status_code=404)
        every = channels.every(connection)
        # A choice only when there is one to make. Never of the bulk, whose cards go from the oldest lot.
        lots = [lot for lot in stock.lots(connection, item_id) if lot.available]
        chosen = lots if len(lots) > 1 and item.kind != Kind.BULK else []
    return templates.TemplateResponse(
        request,
        "sale.html",
        {"item": item, "channels": every, "lots": chosen, "form": form, "error": error},
        status_code=status_code,
    )
