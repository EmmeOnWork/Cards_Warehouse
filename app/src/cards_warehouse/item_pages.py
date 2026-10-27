"""The pages of the items: the list, and the load of the items of a purchase, one piece after the other."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, NamedTuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import Connection

from cards_warehouse import channels, gradings, items, listing_texts, partners, photos, purchases, stock
from cards_warehouse.cost_split import TooSmallToSplit
from cards_warehouse.items import Card, Condition, Grading, Item, Kind, Sealed, grade_text
from cards_warehouse.money import format_euros, parse_euros
from cards_warehouse.pages import templates
from cards_warehouse.purchases import PaymentsNotTotal, Piece, Purchase, Share, SharesNotWhole

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
templates.env.globals["languages"] = items.LANGUAGES
templates.env.globals["conditions"] = items.CONDITIONS
# The condition of the list's filter that keeps the graded cards.
templates.env.globals["graded"] = items.GRADED


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
    return f"{state.grader} {grade_text(state.grade)}"


templates.env.filters["details_line"] = _details_line
templates.env.filters["card_state"] = _state

router = APIRouter()


class PieceForm(BaseModel):
    """The fields of a piece of a purchase, as typed: the item, its copies and, when the purchase has more than one
    piece, what a copy is estimated to be worth."""

    kind: str = ""
    game: str = ""
    new_game: str = ""
    name: str = ""
    language: str = ""
    quantity: str = "1"
    estimated_value: str = ""
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


class LoadForm(PieceForm):
    """The fields of the load page, as typed: they go back into the page when something must be fixed."""

    # The purchase the copies come from: what it cost, shipping apart, and when. A cost not known has none.
    total_cost: str = ""
    unknown_cost: bool = False
    shipping: str = ""
    purchased_on: str = ""
    purchase_note: str = ""
    # One row for each person who can share the purchase, Manuel first: who, the share in percent, what they paid.
    partner: list[str] = []
    percent: list[str] = []
    paid: list[str] = []
    # The pieces already added, each as the JSON of its fields: the page sends them back with the one being typed.
    pieces: list[str] = []
    # Pressed to add the piece typed and type another, or to take an added one away: nothing is saved yet.
    add_piece: bool = False
    remove_piece: int | None = None


class _Refused(Exception):
    """What Manuel typed cannot be saved: the message tells him why."""


@router.get("/items")
# The filters in the address, as the form sends them: back from an item, the list is filtered as it was.
def item_list(request: Request, filters: Annotated[items.Filters, Depends()], q: str = ""):
    with request.app.state.engine.connect() as connection:
        listed = items.search(connection, q, filters)
        games = items.game_names(connection)
    return templates.TemplateResponse(
        request,
        "items.html",
        {"listed": listed, "q": q, "filters": filters, "filtered": filters != items.UNFILTERED, "games": games},
    )


_ITALY = ZoneInfo("Europe/Rome")


@router.get("/items/new")
def load_page(request: Request):
    # Most loads are of something just bought: the date is today's, in Italy.
    return _load_page(request, LoadForm(purchased_on=_today().isoformat()))


@router.post("/items")
def load_item(request: Request, form: Annotated[LoadForm, Form()]):
    if form.remove_piece is not None:
        return _load_page(request, _without_piece(form, form.remove_piece))
    try:
        if form.add_piece:
            # Checked while it is on the screen: once added, a piece can only be taken away.
            _read_piece(form, estimated=not form.unknown_cost)
            return _load_page(request, _with_piece_added(form))
        pieces, purchase = _read(form)
        # The items and their lots together, or none: a purchase refused takes the items away with it.
        with request.app.state.engine.begin() as connection:
            item_ids = _load(connection, pieces, purchase)
    except _Refused as refusal:
        return _load_page(request, form, error=str(refusal), status_code=422)
    except (SharesNotWhole, PaymentsNotTotal, TooSmallToSplit) as refusal:
        return _load_page(request, form, error=_purchase_refusal(refusal), status_code=422)
    if len(item_ids) == 1:
        # On the new item's page, where its photos are added.
        return RedirectResponse(f"/items/{item_ids[0]}", status_code=303)
    # Where the split can be checked, with a link to the page of each item.
    return RedirectResponse("/items" if purchase is None else "/purchases", status_code=303)


class _ReadPiece(NamedTuple):
    item: Item
    quantity: int
    # Only when the piece splits a known cost with others.
    estimated_value_cents: int | None


def _load(connection: Connection, pieces: list[_ReadPiece], purchase: Purchase | None) -> list[int]:
    """The items of the pieces, and their lots: without a purchase for a cost not known, the cost in equal parts
    for one piece, in proportion to the estimated values for more."""
    item_ids = [items.add(connection, piece.item) for piece in pieces]
    if purchase is None:
        for item_id, piece in zip(item_ids, pieces, strict=True):
            stock.load(connection, item_id, piece.quantity, unit_cost_cents=None)
    elif len(pieces) == 1:
        purchases.record(connection, purchase, item_ids[0], pieces[0].quantity)
    else:
        mixed = [
            Piece(item_id, piece.quantity, piece.estimated_value_cents)
            for item_id, piece in zip(item_ids, pieces, strict=True)
        ]
        purchases.record_mixed(connection, purchase, mixed)
    return item_ids


def _read(form: LoadForm) -> tuple[list[_ReadPiece], Purchase | None]:
    """The pieces, the ones added first and the one typed last, and the purchase they come from: None for a cost
    not known. Each piece is an item, its copies and what a copy is estimated to be worth: read only when it
    splits a known cost with other pieces."""
    typed = [*(PieceForm.model_validate_json(piece) for piece in form.pieces), form]
    estimated = len(typed) > 1 and not form.unknown_cost
    pieces = [_read_piece(piece, estimated) for piece in typed]
    if form.unknown_cost:
        return pieces, None
    total_cost = _known_cost(form.total_cost)
    shipping = _euros(form.shipping, "la spedizione") if form.shipping.strip() else 0
    purchase = Purchase(
        total_cost_cents=total_cost,
        shipping_cents=shipping,
        purchased_on=_date(form.purchased_on),
        note=form.purchase_note.strip(),
        shares=_shares(form, due=total_cost + shipping),
    )
    return pieces, purchase


def _read_piece(piece: PieceForm, estimated: bool) -> _ReadPiece:
    item = _read_item(piece)
    return _ReadPiece(item, _quantity(piece.quantity), _estimated_value(piece) if estimated else None)


def _estimated_value(piece: PieceForm) -> int:
    """What a copy of the piece is worth, to split the cost: at least a cent, so that no copy costs nothing."""
    text = piece.estimated_value.strip()
    cents = _euros(text, "il valore stimato") if text else 0
    if cents < 1:
        raise _Refused(
            f"Scrivi quanto vale una copia di «{piece.name.strip()}», almeno 0,01 €: "
            "il costo si divide in proporzione ai valori stimati."
        )
    return cents


def _with_piece_added(form: LoadForm) -> LoadForm:
    """The page once the piece typed is added: in the list, with its fields empty for the next one but for the
    kind, the game and the language, which the next piece most likely shares."""
    piece = PieceForm.model_validate(form.model_dump())
    next_piece = PieceForm(kind=form.kind, game=form.game, new_game=form.new_game, language=form.language)
    added = [*form.pieces, piece.model_dump_json()]
    return form.model_copy(update={**next_piece.model_dump(), "pieces": added, "add_piece": False})


def _without_piece(form: LoadForm, index: int) -> LoadForm:
    pieces = [piece for position, piece in enumerate(form.pieces) if position != index]
    return form.model_copy(update={"pieces": pieces, "remove_piece": None})


def _read_item(form: PieceForm) -> Item:
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


def _details(form: PieceForm) -> Card | Sealed | None:
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


def _grading(form: PieceForm) -> Grading:
    grader = form.grader.strip()
    if not grader:
        raise _Refused("Scrivi l'ente che ha gradato la carta: per esempio PSA.")
    return Grading(grader, _grade(form.grade))


def _grade(text: str) -> Decimal:
    try:
        return items.parse_grade(text)
    except ValueError:
        raise _Refused("Il voto va da 1 a 10, a mezzi punti: per esempio 9,5.") from None


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
    added = [PieceForm.model_validate_json(piece) for piece in form.pieces]
    return templates.TemplateResponse(
        request,
        "load.html",
        {"form": form, "added": added, "error": error, "shares": shares, **choices},
        status_code=status_code,
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
        prices = {"proposal": channels.proposal(connection, item_id), "reference": items.reference(connection, item_id)}
        shown = photos.of_item(connection, request.app.state.photos, item_id)
        texts = listing_texts.of_item(connection, item_id)
        grading = {"at_grader": gradings.at_grader(connection, item_id), "graded": gradings.back(connection, item_id)}
    # A card in its condition can be graded; a graded card has its grade already.
    gradable = isinstance(item.details, Card) and isinstance(item.details.state, Condition)
    return templates.TemplateResponse(
        request,
        "item.html",
        {"item": item, "photos": shown, "texts": texts, "gradable": gradable, **prices, **grading},
    )


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
            fields |= {"graded": True, "grader": card.state.grader, "grade": grade_text(card.state.grade)}
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
