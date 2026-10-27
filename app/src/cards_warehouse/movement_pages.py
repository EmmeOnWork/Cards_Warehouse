"""The movements of an item: the history of its lots, and the adjustments that change them without a sale."""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import items, openings, stock
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.pages import templates
from cards_warehouse.stock import Cause

# What the history calls each cause.
templates.env.globals["causes"] = {
    Cause.LOAD: "Carico",
    Cause.SALE: "Vendita",
    Cause.CANCELLATION: "Annullamento",
    Cause.LOST: "Smarrito",
    Cause.DAMAGED: "Danneggiato",
    Cause.GIVEN_AWAY: "Regalato",
    Cause.MISCOUNT: "Errore di conteggio",
    Cause.OPENING: "Apertura",
    Cause.SENT_FOR_GRADING: "Spedita a gradare",
    Cause.GRADED: "Tornata gradata",
}
# The choices of an adjustment: its cause, and which way it changes the lot. The number pad of a phone often has
# no minus sign, so the way is in the choice and the copies are always at least 1.
ADJUSTMENTS = {
    "lost": ("Smarrito", Cause.LOST, -1),
    "damaged": ("Danneggiato", Cause.DAMAGED, -1),
    "given_away": ("Regalato", Cause.GIVEN_AWAY, -1),
    "count_fewer": ("Errore di conteggio: ne ho in meno", Cause.MISCOUNT, -1),
    "count_more": ("Errore di conteggio: ne ho in più", Cause.MISCOUNT, 1),
}
templates.env.globals["adjustments"] = {choice: label for choice, (label, _, _) in ADJUSTMENTS.items()}
# The day of a movement, in Italy.
templates.env.filters["day"] = lambda at: f"{at.astimezone(LOCAL_TIME):%d/%m/%Y}"


def _copies(count: int) -> str:
    return "1 copia" if count == 1 else f"{count} copie"


templates.env.filters["copies"] = _copies

router = APIRouter()


class AdjustmentForm(BaseModel):
    """The fields of an adjustment, as typed: they go back into the page when something must be fixed."""

    lot: str = "1"
    cause: str = ""
    quantity: str = "1"
    note: str = ""


class _Refused(Exception):
    """What Manuel typed cannot be saved: the message tells him why."""


@router.get("/items/{item_id}/movements")
def movements_page(request: Request, item_id: int):
    return _page(request, item_id, AdjustmentForm())


@router.post("/items/{item_id}/movements")
def adjust(request: Request, item_id: int, form: Annotated[AdjustmentForm, Form()]):
    with request.app.state.engine.begin() as connection:
        try:
            lot, cause, change = _read(form, stock.lots(connection, item_id))
            stock.adjust(connection, lot.id, change, cause, form.note.strip())
        except _Refused as refusal:
            error = str(refusal)
        except stock.NotEnoughStock:
            error = f"Il lotto {lot.number} ha {_copies(lot.available)}: non puoi toglierne {-change}."
        else:
            return RedirectResponse(f"/items/{item_id}/movements", status_code=303)
    return _page(request, item_id, form, error=error, status_code=422)


def _read(form: AdjustmentForm, lots: list[stock.Lot]) -> tuple[stock.Lot, Cause, int]:
    if form.cause not in ADJUSTMENTS:
        raise _Refused("Scegli la causa della rettifica.")
    lot = next((lot for lot in lots if str(lot.number) == form.lot), None)
    if lot is None:
        raise _Refused("Scegli il lotto della rettifica.")
    _, cause, way = ADJUSTMENTS[form.cause]
    return lot, cause, way * _quantity(form.quantity)


def _quantity(text: str) -> int:
    try:
        quantity = int(text)
    except ValueError:
        quantity = 0
    if quantity < 1:
        raise _Refused("Le copie sono almeno 1.")
    return quantity


def _page(request: Request, item_id: int, form: AdjustmentForm, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        item = items.find(connection, item_id)
        if item is None:
            raise HTTPException(status_code=404)
        history = stock.history(connection, item_id)
        # What each opening in the history came from, or went into.
        counterparts = openings.counterparts(connection, item_id)
        lots = stock.lots(connection, item_id)
    return templates.TemplateResponse(
        request,
        "movements.html",
        {"item": item, "history": history, "counterparts": counterparts, "lots": lots, "form": form, "error": error},
        status_code=status_code,
    )
