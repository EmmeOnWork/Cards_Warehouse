"""The openings, from the page of a sealed: a box into packs, one copy at a time, into packs that exist or a new
item; or packs and boxes into cards, one card after the other, with the rest into the bulk."""

from typing import Annotated, NamedTuple

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import Connection

from cards_warehouse import items, openings, stock
from cards_warehouse.cost_split import TooSmallToSplit
from cards_warehouse.items import Card, Condition, Item, Kind, Sealed
from cards_warehouse.money import format_euros, parse_euros
from cards_warehouse.openings import Pulled, Rest
from cards_warehouse.pages import copies, templates

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


class CardForm(BaseModel):
    """A card that came out of an opening, as typed: one that exists, or a new one by its name, number and condition;
    its copies, and what one of them is estimated to be worth."""

    # The id of the card's item, or "" for a new one.
    card: str = ""
    name: str = ""
    number: str = ""
    # Just out of the pack.
    condition: str = Condition.NEAR_MINT
    quantity: str = "1"
    estimated_value: str = ""


class CardsOpeningForm(CardForm):
    """The fields of an opening into cards, as typed: they go back into the page when something must be fixed."""

    lot: str = "1"
    copies: str = "1"
    # The cards already added, each as the JSON of its fields: the page sends them back with the one being typed.
    cards: list[str] = []
    # Pressed to add the card typed and type another, or to take an added one away: nothing is saved yet.
    add_card: bool = False
    remove_card: int | None = None
    bulk_cards: str = ""
    bulk_value: str = ""


class _ReadCard(NamedTuple):
    # None for a new card, made from its name, number and condition when the opening is saved.
    item_id: int | None
    name: str
    number: str
    condition: Condition
    copies: int
    estimated_value_cents: int


@router.get("/items/{item_id}/cards-opening")
def cards_opening_page(request: Request, item_id: int):
    return _cards_page(request, item_id, CardsOpeningForm())


@router.post("/items/{item_id}/cards-opening")
def open_into_cards(request: Request, item_id: int, form: Annotated[CardsOpeningForm, Form()]):
    if form.remove_card is not None:
        cards = [card for position, card in enumerate(form.cards) if position != form.remove_card]
        return _cards_page(request, item_id, form.model_copy(update={"cards": cards, "remove_card": None}))
    try:
        if form.add_card:
            # Checked while it is on the screen: once added, a card can only be taken away.
            _read_card(form)
            return _cards_page(request, item_id, _with_card_added(form))
        # The new cards' items and the opening together, or none: a refusal takes the items away with it.
        with request.app.state.engine.begin() as connection:
            lot = next((lot for lot in stock.lots(connection, item_id) if str(lot.number) == form.lot), None)
            if lot is None:
                raise _Refused("Scegli il lotto da aprire.")
            opened = _count(form.copies, "Le copie da aprire sono almeno 1.")
            typed = [*(CardForm.model_validate_json(card) for card in form.cards), form]
            # The card on the screen is left out when nothing of it was typed: an opening may be all bulk.
            read = [_read_card(card) for card in typed if card.card or card.name.strip() or card.estimated_value]
            rest = Rest(
                _count(form.bulk_cards, "Scrivi quante carte vanno nel bulk, anche a occhio: almeno 1."),
                _value(form.bulk_value, "Scrivi quanto vale il bulk, almeno 0,01 €"),
            )
            pulled = [_pulled(connection, item_id, card) for card in read]
            openings.into_cards(connection, lot.id, opened, pulled, rest)
    except _Refused as refusal:
        error = str(refusal)
    except stock.NotEnoughStock:
        error = f"Il lotto {lot.number} ha {copies(lot.available)}: non puoi aprirne {opened}."
    except TooSmallToSplit:
        cost = format_euros(lot.unit_cost_cents * opened)
        error = f"Il costo di ciò che apri, {cost} €, non basta a dare 0,01 € a ogni carta e al bulk."
    else:
        # Where the opening names every card that came out, and the bulk, with a link to each.
        return RedirectResponse(f"/items/{item_id}/movements", status_code=303)
    return _cards_page(request, item_id, form, error=error, status_code=422)


def _read_card(card: CardForm) -> _ReadCard:
    if not card.card and not card.name.strip():
        raise _Refused("Scrivi il nome della carta nuova, oppure scegline una.")
    try:
        condition = Condition(card.condition)
    except ValueError:
        raise _Refused("Scegli la condizione della carta nuova.") from None
    named = card.name.strip() or "la carta scelta"
    return _ReadCard(
        int(card.card) if card.card else None,
        card.name.strip(),
        card.number.strip(),
        condition,
        _count(card.quantity, "Le copie di una carta sono almeno 1."),
        _value(card.estimated_value, f"Scrivi quanto vale una copia di «{named}», almeno 0,01 €"),
    )


def _pulled(connection: Connection, opened_item_id: int, card: _ReadCard) -> Pulled:
    """The card as it came out: a new one is an item of the game, the language and the set of the item opened."""
    item_id = card.item_id
    if item_id is None:
        opened = items.get(connection, opened_item_id)
        set_name = opened.details.set_name if isinstance(opened.details, Sealed) else ""
        details = Card(card.condition, set_name=set_name, number=card.number)
        new = Item(Kind.SINGLE_CARD, opened.game, card.name, opened.language, details=details)
        item_id = items.add(connection, new)
    return Pulled(item_id, card.copies, card.estimated_value_cents)


def _with_card_added(form: CardsOpeningForm) -> CardsOpeningForm:
    """The page once the card typed is added: in the list, with its fields empty for the next one."""
    card = CardForm.model_validate(form.model_dump())
    added = [*form.cards, card.model_dump_json()]
    return form.model_copy(update={**CardForm().model_dump(), "cards": added, "add_card": False})


def _count(text: str, refusal: str) -> int:
    try:
        count = int(text)
    except ValueError:
        count = 0
    if count < 1:
        raise _Refused(refusal)
    return count


def _value(text: str, refusal: str) -> int:
    """What a card or the bulk is estimated to be worth, to split the cost: at least a cent, so that none of them
    costs nothing."""
    try:
        cents = parse_euros(text)
    except ValueError:
        cents = 0
    if cents < 1:
        raise _Refused(f"{refusal}: il costo si divide in proporzione ai valori stimati.")
    return cents


def _cards_page(request: Request, item_id: int, form: CardsOpeningForm, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        item = items.find(connection, item_id)
        if item is None:
            raise HTTPException(status_code=404)
        lots = stock.lots(connection, item_id)
        # The cards it may hold: the single cards of its game and language.
        cards = items.listing(
            connection,
            items.items.c.kind == Kind.SINGLE_CARD,
            items.games.c.name == item.game,
            items.items.c.language == items.get(connection, item_id).language,
        )
    # The cards added, as the list on the page shows them: one that exists by the name of its item.
    names = {str(card.id): card.name for card in cards}
    added = [CardForm.model_validate_json(card) for card in form.cards]
    return templates.TemplateResponse(
        request,
        "cards_opening.html",
        {"item": item, "lots": lots, "cards": cards, "names": names, "added": added, "form": form, "error": error},
        status_code=status_code,
    )
