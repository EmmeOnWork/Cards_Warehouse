"""The pages of the channels: their fee rules, and the target margin the prices are made from."""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import channels
from cards_warehouse.money import format_euros, format_percent, parse_euros, parse_percent
from cards_warehouse.pages import templates
from cards_warehouse.pricing import FeeRule


def _fee_text(fee: FeeRule) -> str:
    """A fee rule as the platform states it: "2 % + 0,50 €", or "10 %" without a fixed part."""
    text = f"{format_percent(fee.percent)} %"
    return f"{text} + {format_euros(fee.fixed_cents)} €" if fee.fixed_cents else text


templates.env.filters["fee"] = _fee_text

router = APIRouter()


class FeeForm(BaseModel):
    """The fields of a fee rule, as typed: they go back into the page when something must be fixed."""

    fee_percent: str = ""
    fee_fixed: str = ""

    @classmethod
    def of(cls, fee: FeeRule) -> "FeeForm":
        return cls(fee_percent=format_percent(fee.percent), fee_fixed=format_euros(fee.fixed_cents))


class NewChannelForm(FeeForm):
    name: str = ""
    multi_copy_listings: bool = False
    # Empty for a channel that sets no limit.
    title_limit: str = ""


class TargetMarginForm(BaseModel):
    target_margin: str = ""


class _Refused(Exception):
    """What was typed cannot be saved: the message says why."""


@router.get("/channels")
def channel_list(request: Request):
    return _channel_list(request)


@router.post("/channels")
def add_channel(request: Request, form: Annotated[NewChannelForm, Form()]):
    try:
        name = form.name.strip()
        if not name:
            raise _Refused("Scrivi il nome del canale.")
        fee = _read_fee(form)
        title_limit = _read_title_limit(form.title_limit)
        with request.app.state.engine.begin() as connection:
            if channels.add(connection, name, fee, form.multi_copy_listings, title_limit) is None:
                raise _Refused(f"Il canale {name} c'è già.")
    except _Refused as refusal:
        return _channel_list(request, new_channel=form, error=str(refusal), status_code=422)
    return RedirectResponse("/channels", status_code=303)


@router.post("/target-margin")
def change_target_margin(request: Request, form: Annotated[TargetMarginForm, Form()]):
    try:
        percent = parse_percent(form.target_margin)
    except ValueError:
        reason = "Scrivi l'obiettivo in percentuale, da 0 a 999,99, con al massimo due decimali: per esempio 20."
        return _channel_list(request, margin=form, error=reason, status_code=422)
    with request.app.state.engine.begin() as connection:
        channels.change_target_margin(connection, percent)
    return RedirectResponse("/channels", status_code=303)


@router.get("/channels/{channel_id}")
def channel_page(request: Request, channel_id: int):
    return _channel_page(request, channel_id)


@router.post("/channels/{channel_id}")
def change_fee(request: Request, channel_id: int, form: Annotated[FeeForm, Form()]):
    try:
        fee = _read_fee(form)
    except _Refused as refusal:
        return _channel_page(request, channel_id, form, error=str(refusal), status_code=422)
    with request.app.state.engine.begin() as connection:
        channels.change_fee(connection, channel_id, fee)
    return RedirectResponse("/channels", status_code=303)


def _read_fee(form: FeeForm) -> FeeRule:
    try:
        percent = parse_percent(form.fee_percent)
    except ValueError:
        raise _Refused("Scrivi la commissione in percentuale, con al massimo due decimali: per esempio 12,9.") from None
    # At 100% no price would leave anything.
    if percent >= 100:
        raise _Refused("La commissione va da 0 a 99,99 %.")
    try:
        fixed_cents = parse_euros(form.fee_fixed)
    except ValueError:
        raise _Refused("Scrivi la parte fissa in euro, con al massimo due decimali: per esempio 0,35.") from None
    return FeeRule(percent, fixed_cents)


def _read_title_limit(text: str) -> int | None:
    if not text.strip():
        return None
    try:
        limit = int(text)
    except ValueError:
        limit = 0
    if limit < 1:
        raise _Refused(
            "I caratteri del titolo sono un numero da 1 in su, per esempio 80: vuoto se il canale non ha limite."
        )
    return limit


def _channel_list(
    request: Request,
    margin: TargetMarginForm | None = None,
    new_channel: NewChannelForm | None = None,
    error: str = "",
    status_code: int = 200,
):
    with request.app.state.engine.connect() as connection:
        every = channels.every(connection)
        target_margin = channels.target_margin(connection)
    return templates.TemplateResponse(
        request,
        "channels.html",
        {
            "channels": every,
            "margin_form": margin or TargetMarginForm(target_margin=format_percent(target_margin)),
            "new_channel": new_channel or NewChannelForm(fee_percent="0", fee_fixed="0,00"),
            "error": error,
        },
        status_code=status_code,
    )


def _channel_page(
    request: Request, channel_id: int, form: FeeForm | None = None, error: str = "", status_code: int = 200
):
    with request.app.state.engine.connect() as connection:
        channel = channels.one(connection, channel_id)
    if channel is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "channel.html",
        {"channel": channel, "form": form or FeeForm.of(channel.fee), "error": error},
        status_code=status_code,
    )
