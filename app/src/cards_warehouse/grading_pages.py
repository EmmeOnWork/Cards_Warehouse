"""The grading of a card, from the item's page: sent to a grader with its cost, then back with its grade."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import exposure, gradings, items, partners, stock
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.gradings import AlreadyBack, Sending
from cards_warehouse.money import parse_euros
from cards_warehouse.pages import templates

router = APIRouter()


class SendingForm(BaseModel):
    """The fields of a card sent for grading, as typed: they go back into the page when something must be fixed."""

    lot: str = "1"
    sent_on: str = ""
    grader: str = ""
    cost: str = ""
    # A partner's id, or "" for Manuel.
    paid_by: str = ""


class ReturnForm(BaseModel):
    grade: str = ""
    returned_on: str = ""


class _Refused(Exception):
    """What Manuel typed cannot be saved: the message says why."""


@router.get("/items/{item_id}/grading")
def sending_page(request: Request, item_id: int):
    return _sending_page(request, item_id, SendingForm(sent_on=_today().isoformat()))


@router.post("/items/{item_id}/grading")
def send(request: Request, item_id: int, form: Annotated[SendingForm, Form()]):
    try:
        with request.app.state.engine.begin() as connection:
            lot = next((lot for lot in stock.lots(connection, item_id) if str(lot.number) == form.lot), None)
            if lot is None:
                raise _Refused("Scegli il lotto della carta da gradare.")
            gradings.send(connection, lot.id, _sending(form))
            exposure.align(connection, item_id, request.app.state.channel_operations)
    except _Refused as refusal:
        error = str(refusal)
    except stock.NotEnoughStock:
        error = f"Il lotto {lot.number} non ha copie da mandare a gradare."
    else:
        return RedirectResponse(f"/items/{item_id}", status_code=303)
    return _sending_page(request, item_id, form, error=error, status_code=422)


def _sending(form: SendingForm) -> Sending:
    if not (grader := form.grader.strip()):
        raise _Refused("Scrivi l'ente che grada la carta: per esempio PSA.")
    return Sending(
        sent_on=_day(form.sent_on, "la data della spedizione"),
        grader=grader,
        cost_cents=_cost(form.cost),
        paid_by=int(form.paid_by) if form.paid_by else None,
    )


def _cost(text: str) -> int:
    try:
        cents = parse_euros(text)
    except ValueError:
        cents = 0
    if cents < 1:
        raise _Refused("Scrivi il costo della gradazione in euro, almeno 0,01 €: per esempio 15,00.")
    return cents


@router.get("/gradings/{grading_id}")
def return_page(request: Request, grading_id: int):
    return _return_page(request, grading_id, ReturnForm(returned_on=_today().isoformat()))


@router.post("/gradings/{grading_id}")
def card_back(request: Request, grading_id: int, form: Annotated[ReturnForm, Form()]):
    try:
        grade = _grade(form.grade)
        returned_on = _day(form.returned_on, "la data del ritorno")
        with request.app.state.engine.begin() as connection:
            item_id = gradings.receive(connection, grading_id, returned_on, grade)
    except _Refused as refusal:
        return _return_page(request, grading_id, form, error=str(refusal), status_code=422)
    except AlreadyBack as back:
        # The page sent twice: the card is the one that came back the first time.
        item_id = back.item_id
    # On the graded card's page, where the photos of its slab are added.
    return RedirectResponse(f"/items/{item_id}", status_code=303)


def _grade(text: str) -> Decimal:
    try:
        return items.parse_grade(text)
    except ValueError:
        raise _Refused("Il voto va da 1 a 10, a mezzi punti: per esempio 9,5.") from None


def _day(text: str, what: str) -> date:
    """A day as the date field sends it: today, in Italy, when the field was emptied."""
    if not text.strip():
        return _today()
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise _Refused(f"Scrivi {what}, per esempio 2026-10-27.") from None


def _today() -> date:
    return datetime.now(LOCAL_TIME).date()


def _sending_page(request: Request, item_id: int, form: SendingForm, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        item = items.find(connection, item_id)
        if item is None:
            raise HTTPException(status_code=404)
        context = {
            "item": item,
            "lots": stock.lots(connection, item_id),
            "partners": partners.every(connection),
            "graders": items.graders(connection),
        }
    return templates.TemplateResponse(
        request, "grading.html", {**context, "form": form, "error": error}, status_code=status_code
    )


def _return_page(request: Request, grading_id: int, form: ReturnForm, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        sent = gradings.one(connection, grading_id)
    if sent is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request, "grading_return.html", {"sent": sent, "form": form, "error": error}, status_code=status_code
    )
