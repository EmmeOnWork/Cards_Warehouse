"""The pages of the items: the list, and the load of an item with the purchase its copies come from."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import channels, items, partners, photos, purchases, stock
from cards_warehouse.cost_split import TooSmallToSplit
from cards_warehouse.items import Card, Condition, Grading, Item, Kind, Sealed
from cards_warehouse.money import format_euros, parse_euros
from cards_warehouse.pages import templates
from cards_warehouse.purchases import PaymentsNotTotal, Purchase, Share, SharesNotWhole

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
# In English, as on Cardmarket and as buyers write them.
templates.env.globals["conditions"] = {
    Condition.MINT: "Mint",
    Condition.NEAR_MINT: "Near Mint",
    Condition.EXCELLENT: "Excellent",
    Condition.GOOD: "Good",
    Condition.LIGHT_PLAYED: "Light Played",
    Condition.PLAYED: "Played",
    Condition.POOR: "Poor",
}


def _details_line(details: Card | Sealed | None) -> str:
    """The fields of an item in one line, under its name in the list."""
    if details is None:
        return ""
    if isinstance(details, Sealed):
        parts = (details.product_type, details.set_name)
    else:
        parts = (details.set_name, details.number, details.variant, _state(details.state))
    return " · ".join(part for part in parts if part)


def _state(state: Condition | Grading) -> str:
    if isinstance(state, Condition):
        return templates.env.globals["conditions"][state]
    return f"{state.grader} {_grade_text(state.grade)}"


def _grade_text(grade: Decimal) -> str:
    # 9,5 as Manuel writes it, and 10 rather than 10,0.
    return f"{grade:.1f}".removesuffix(".0").replace(".", ",")


templates.env.filters["details_line"] = _details_line

router = APIRouter()


class LoadForm(BaseModel):
    """The fields of the load page, as typed: they go back into the page when something must be fixed."""

    kind: str = ""
    game: str = ""
    new_game: str = ""
    name: str = ""
    language: str = ""
    quantity: str = "1"
    # The purchase the copies come from: what it cost, shipping apart, and when. A cost not known has none.
    total_cost: str = ""
    unknown_cost: bool = False
    shipping: str = ""
    purchased_on: str = ""
    purchase_note: str = ""
    notes: str = ""
    location: str = ""
    set_name: str = ""
    number: str = ""
    variant: str = ""
    condition: str = ""
    graded: bool = False
    grader: str = ""
    grade: str = ""
    product_type: str = ""
    # One row for each person who can share the purchase, Manuel first: who, the share in percent, what they paid.
    partner: list[str] = []
    percent: list[str] = []
    paid: list[str] = []


class _Refused(Exception):
    """What Manuel typed cannot be saved: the message tells him why."""


@router.get("/items")
def item_list(request: Request):
    with request.app.state.engine.connect() as connection:
        listed = items.listing(connection)
    return templates.TemplateResponse(request, "items.html", {"listed": listed})


_ITALY = ZoneInfo("Europe/Rome")


@router.get("/items/new")
def load_page(request: Request):
    # Most loads are of something just bought: the date is today's, in Italy.
    return _load_page(request, LoadForm(purchased_on=_today().isoformat()))


@router.post("/items")
def load_item(request: Request, form: Annotated[LoadForm, Form()]):
    try:
        item, quantity, purchase = _read(form)
        # The item and its lots together, or neither: a purchase refused takes the item away with it.
        with request.app.state.engine.begin() as connection:
            item_id = items.add(connection, item)
            if purchase is None:
                stock.load(connection, item_id, quantity, unit_cost_cents=None)
            else:
                purchases.record(connection, purchase, item_id, quantity)
    except _Refused as refusal:
        return _load_page(request, form, error=str(refusal), status_code=422)
    except (SharesNotWhole, PaymentsNotTotal, TooSmallToSplit) as refusal:
        return _load_page(request, form, error=_purchase_refusal(refusal), status_code=422)
    # On the new item's page, where its photos are added.
    return RedirectResponse(f"/items/{item_id}", status_code=303)


def _read(form: LoadForm) -> tuple[Item, int, Purchase | None]:
    """The item, its copies, and the purchase they come from: None for a cost not known."""
    item = _read_item(form)
    quantity = _quantity(form.quantity)
    if form.unknown_cost:
        return item, quantity, None
    total_cost = _known_cost(form.total_cost)
    shipping = _euros(form.shipping, "la spedizione") if form.shipping.strip() else 0
    purchase = Purchase(
        total_cost_cents=total_cost,
        shipping_cents=shipping,
        purchased_on=_date(form.purchased_on),
        note=form.purchase_note.strip(),
        shares=_shares(form, due=total_cost + shipping),
    )
    return item, quantity, purchase


def _read_item(form: LoadForm) -> Item:
    """The item's own fields: the load and the edit share them. The copies and their cost are the lot's."""
    if form.kind not in LOADABLE:
        raise _Refused("Scegli il tipo: carta singola, sealed o rivista.")
    return Item(
        kind=Kind(form.kind),
        game=form.new_game.strip() or form.game,
        name=form.name.strip(),
        language=form.language,
        notes=form.notes.strip(),
        location=form.location.strip(),
        details=_details(form),
    )


def _details(form: LoadForm) -> Card | Sealed | None:
    if form.kind == Kind.SEALED:
        return Sealed(form.product_type.strip(), form.set_name.strip())
    if form.kind == Kind.SINGLE_CARD:
        state = _grading(form) if form.graded else _condition(form.condition)
        return Card(state, form.set_name.strip(), form.number.strip(), form.variant.strip())
    return None


def _condition(value: str) -> Condition:
    try:
        return Condition(value)
    except ValueError:
        raise _Refused("Scegli la condizione della carta, oppure spunta «Carta gradata».") from None


def _grading(form: LoadForm) -> Grading:
    grader = form.grader.strip()
    if not grader:
        raise _Refused("Scrivi l'ente che ha gradato la carta: per esempio PSA.")
    return Grading(grader, _grade(form.grade))


def _grade(text: str) -> Decimal:
    try:
        grade = Decimal(text.strip().replace(",", "."))
    except InvalidOperation:
        grade = Decimal(0)
    # A NaN cannot be compared: it is refused before.
    if not grade.is_finite() or not 1 <= grade <= 10 or (grade * 2) % 1:
        raise _Refused("Il voto va da 1 a 10, a mezzi punti: per esempio 9,5.")
    return grade


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
        raise _Refused("Scrivi il costo totale, oppure spunta «Costo sconosciuto».")
    cents = _euros(text, "il costo")
    if cents < 1:
        raise _Refused("Il costo totale vale almeno 0,01 €: se non lo conosci, spunta «Costo sconosciuto».")
    return cents


def _euros(text: str, what: str) -> int:
    try:
        return parse_euros(text)
    except ValueError:
        raise _Refused(f"Scrivi {what} in euro, con al massimo due decimali: per esempio 12,50.") from None


def _date(text: str) -> date:
    """The day of the purchase: today, in Italy, when the field was emptied."""
    if not text.strip():
        return _today()
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise _Refused("Scrivi la data dell'acquisto, per esempio 2026-10-20.") from None


def _today() -> date:
    return datetime.now(_ITALY).date()


def _shares(form: LoadForm, due: int) -> tuple[Share, ...]:
    """Who has what of the purchase, and who paid what. A column left empty is all Manuel's: with no share
    typed he has 100%, with no payment typed he paid it all. Otherwise an empty field is zero."""
    # The page sends the three fields of every row: lists of different lengths are not its form.
    rows = list(zip(form.partner, form.percent, form.paid, strict=True))
    no_percent = not any(percent.strip() for _, percent, _ in rows)
    no_payment = not any(paid.strip() for _, _, paid in rows)
    if no_percent and no_payment:
        return ()
    shares = []
    for partner, percent, paid in rows:
        manuel = partner == ""
        share = Share(
            partner_id=None if manuel else int(partner),
            percent=(100 if manuel else 0) if no_percent else _percent(percent),
            paid_cents=(due if manuel else 0) if no_payment else _paid(paid),
        )
        # Someone with no share who paid nothing is not in the purchase.
        if share.percent or share.paid_cents:
            shares.append(share)
    return tuple(shares)


def _percent(text: str) -> int:
    try:
        percent = int(text) if text.strip() else 0
    except ValueError:
        percent = -1
    if not 0 <= percent <= 100:
        raise _Refused("Scrivi le quote in percentuali intere, da 0 a 100: per esempio 50.")
    return percent


def _paid(text: str) -> int:
    return _euros(text, "quanto ha pagato ciascuno") if text.strip() else 0


def _purchase_refusal(refusal: Exception) -> str:
    if isinstance(refusal, SharesNotWhole):
        return f"Le quote fanno {refusal.percent} %: devono fare 100 %."
    if isinstance(refusal, PaymentsNotTotal):
        paid, due = format_euros(refusal.paid_cents), format_euros(refusal.due_cents)
        return f"I pagamenti fanno {paid} €: devono fare {due} €, il costo più la spedizione."
    return "Il costo totale, spedizione compresa, non basta a dare 0,01 € a ogni copia."


def _load_page(request: Request, form: LoadForm, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        choices = _choices(connection)
        shares = _share_rows(form, partners.every(connection))
    return templates.TemplateResponse(
        request, "load.html", {"form": form, "error": error, "shares": shares, **choices}, status_code=status_code
    )


def _share_rows(form: LoadForm, every: list[partners.Partner]) -> list[tuple[str, str, str, str]]:
    """Manuel and each partner, with what was typed for them: the partner's id, the name, the share, the payment."""
    typed = {
        partner: (percent, paid) for partner, percent, paid in zip(form.partner, form.percent, form.paid, strict=True)
    }
    people = [("", purchases.MANUEL)] + [(str(partner.id), partner.name) for partner in every]
    return [(partner, name, *typed.get(partner, ("", ""))) for partner, name in people]


def _choices(connection) -> dict:
    """What the fields of an item offer: the games, and the values already typed."""
    return {
        "games": items.game_names(connection),
        "suggestions": items.suggestions(connection),
        "graders": items.graders(connection),
    }


# After /items/new, which is not an item.
@router.get("/items/{item_id}")
def item_page(request: Request, item_id: int):
    with request.app.state.engine.connect() as connection:
        item = items.find(connection, item_id)
        if item is None:
            raise HTTPException(status_code=404)
        proposal = channels.proposal(connection, item_id)
        shown = photos.of_item(connection, request.app.state.photos, item_id)
    return templates.TemplateResponse(request, "item.html", {"item": item, "proposal": proposal, "photos": shown})


@router.get("/items/{item_id}/edit")
def edit_page(request: Request, item_id: int):
    with request.app.state.engine.connect() as connection:
        item = items.get(connection, item_id)
    if item is None:
        raise HTTPException(status_code=404)
    return _edit_page(request, item_id, _form_of(item))


# The same fields as the load, but only those of the item: copies sent with them are not read.
@router.post("/items/{item_id}/edit")
def edit_item(request: Request, item_id: int, form: Annotated[LoadForm, Form()]):
    try:
        item = _read_item(form)
    except _Refused as refusal:
        return _edit_page(request, item_id, form, error=str(refusal), status_code=422)
    with request.app.state.engine.begin() as connection:
        items.update(connection, item_id, item)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


def _form_of(item: Item) -> LoadForm:
    """The item's fields as the page shows them, to start the edit from what was typed."""
    fields = {}
    if isinstance(item.details, Sealed):
        fields = {"product_type": item.details.product_type, "set_name": item.details.set_name}
    elif isinstance(item.details, Card):
        card = item.details
        fields = {"set_name": card.set_name, "number": card.number, "variant": card.variant}
        if isinstance(card.state, Grading):
            fields |= {"graded": True, "grader": card.state.grader, "grade": _grade_text(card.state.grade)}
        else:
            fields["condition"] = card.state
    return LoadForm(
        kind=item.kind,
        game=item.game,
        name=item.name,
        language=item.language,
        notes=item.notes,
        location=item.location,
        **fields,
    )


def _edit_page(request: Request, item_id: int, form: LoadForm, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        choices = _choices(connection)
    return templates.TemplateResponse(
        request, "edit.html", {"item_id": item_id, "form": form, "error": error, **choices}, status_code=status_code
    )
