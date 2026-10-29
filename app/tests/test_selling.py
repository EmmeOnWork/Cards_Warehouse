"""Selling an item: a sale recorded from one page, the copies it takes from the stock, the real margin it leaves, and
what it leaves to do on the channels where the item is still offered.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html

import pytest

from cards_warehouse import stock
from cards_warehouse.database import create_database_engine
from tests.pages import buttons, checkboxes, form_fields, links, sections, select_options, table_rows, text
from tests.test_putting_on_sale import BOOSTER_BOX

MEW = {
    "kind": "single_card",
    "game": "Pokémon",
    "name": "Mew ex",
    "language": "it",
    "quantity": "1",
    "total_cost": "50",
    "set_name": "151",
    "number": "151/165",
    "condition": "near_mint",
}


# Sold on Tilt, which keeps 2% + 0,50 of the price: 1,70 of 60,00. With 3,00 of shipping on Manuel and a cost of 50,00,
# 5,30 are left, 10,6% of the cost. It was the only copy: Tilt closed its listing by itself, the others are to close.
def test_a_sale_of_the_last_copy_shows_its_real_margin_and_the_listings_to_close_on_the_other_channels(
    signed_in_client,
):
    item_page = _published(signed_in_client, MEW, "Vinted", "Tilt", "eBay")

    sold = _sell(signed_in_client, item_page, channel="Tilt", quantity="1", price="60", fee="", shipping="3")

    shown = sections(sold.text)
    assert text(shown["Vendita"]) == (
        "Vendita Canale Tilt Copie 1 Prezzo 60,00 € Commissione 1,70 € Spedizione 3,00 € Costo 50,00 € "
        "Margine 5,30 € · 10,6 %"
    )
    assert list(links(shown["Da fare"])) == ["Chiudi su Vinted", "Chiudi su eBay"]


# One of five boxes sold on Vinted, where its listing closed with the sale: the next box needs a listing of its own
# there. Tilt and eBay offer five, one more than are left.
def test_a_sale_on_vinted_with_copies_left_leaves_a_listing_to_publish_there_and_the_others_to_update(
    signed_in_client,
):
    item_page = _published(signed_in_client, BOOSTER_BOX, "Vinted", "Tilt", "eBay")

    sold = _sell(signed_in_client, item_page, channel="Vinted", quantity="1", price="120", fee="", shipping="")

    assert list(links(sections(sold.text)["Da fare"])) == ["Pubblica su Vinted", "Aggiorna su Tilt", "Aggiorna su eBay"]
    assert table_rows(sections(signed_in_client.get(item_page).text)["Annunci"]) == [
        ["Vinted", "da pubblicare", "120,00 €", "1", ""],
        ["Tilt", "da aggiornare", "122,96 €", "4", "https://tilt.test/listing"],
        ["eBay", "da aggiornare", "120,00 €", "4", "https://ebay.test/listing"],
    ]


# From the sale's page Manuel opens each action, does it in the channel's app and ticks it, with no link to paste:
# Tilt down to the copy left, then off Tilt once that one sold too.
def test_the_actions_a_sale_leaves_are_ticked_without_a_link_and_the_listings_follow(signed_in_client):
    item_page = _published(signed_in_client, {**MEW, "quantity": "2", "total_cost": "100"}, "Tilt", "eBay")
    sold = _sell(signed_in_client, item_page, channel="eBay", quantity="1", price="60", fee="", shipping="")

    to_update = signed_in_client.get(links(sections(sold.text)["Da fare"])["Aggiorna su Tilt"])
    assert "Porta l'annuncio a 1 copia a 61,74 €." in text(to_update.text)
    updated, _ = buttons(to_update.text)["Aggiornato"]
    signed_in_client.post(updated)

    assert table_rows(sections(signed_in_client.get(item_page).text)["Annunci"]) == [
        ["Tilt", "attivo", "61,74 €", "1", "https://tilt.test/listing"],
        ["eBay", "attivo", "60,00 €", "1", "https://ebay.test/listing"],
    ]
    sold = _sell(signed_in_client, item_page, channel="eBay", quantity="1", price="60", fee="", shipping="")
    to_close = signed_in_client.get(links(sections(sold.text)["Da fare"])["Chiudi su Tilt"])
    closed, _ = buttons(to_close.text)["Chiuso"]
    signed_in_client.post(closed)
    assert "Non è in vendita su nessun canale." in text(signed_in_client.get(item_page).text)


# Typed as zero, or as not an amount: the page comes back with what he typed, and nothing is sold.
@pytest.mark.parametrize(
    ("price", "reason"),
    [("0", "Il prezzo vale almeno 0,01 €."), ("dieci", "Scrivi il prezzo in euro, con al massimo due decimali")],
)
def test_a_sale_without_a_price_of_one_cent_at_least_is_refused_with_what_manuel_typed(signed_in_client, price, reason):
    item_page = signed_in_client.post("/items", data=MEW).url.path

    response = _sell(signed_in_client, item_page, channel="Tilt", quantity="1", price=price, shipping="3", note="Luca")

    assert response.status_code == 422
    assert reason in html.unescape(response.text)
    typed = form_fields(response.text)
    assert (typed["price"], typed["shipping"], typed["note"]) == ([price], ["3"], ["Luca"])
    assert "Copie disponibili 1" in text(signed_in_client.get(item_page).text)


# Until the double sales (task 24): the stock would go below zero.
def test_a_sale_of_more_copies_than_are_left_is_refused_and_says_how_many_there_are(signed_in_client):
    item_page = signed_in_client.post("/items", data=MEW).url.path

    response = _sell(signed_in_client, item_page, channel="Tilt", quantity="2", price="120")

    assert response.status_code == 422
    assert "Copie disponibili: 1. Non puoi venderne 2." in html.unescape(response.text)


# Two copies of Mew ex bought at different times: Manuel sold the one of the second lot, at 40,00. With one lot the
# page asks nothing, and the oldest is the one sold.
def test_with_two_lots_the_sale_page_lets_manuel_choose_the_one_he_sold(signed_in_client):
    # A lot of another item first: the lots of Mew ex are its 1 and 2, not the database's.
    signed_in_client.post("/items", data=BOOSTER_BOX)
    item_page = signed_in_client.post("/items", data=MEW).url.path
    with create_database_engine().begin() as connection:
        stock.load(connection, int(item_page.rsplit("/", 1)[1]), quantity=1, unit_cost_cents=4000)

    form = signed_in_client.get(links(signed_in_client.get(item_page).text)["Vendi"])
    sold = _sell(signed_in_client, item_page, channel="Vinted", quantity="1", price="60", lot="2")

    assert select_options(form.text, "lot") == [
        "Dal più vecchio",
        "Lotto 1 · 1 copia · 50,00 €",
        "Lotto 2 · 1 copia · 40,00 €",
    ]
    assert "Costo 40,00 €" in text(sections(sold.text)["Vendita"])


def _published(client, item: dict, *channels: str) -> str:
    """The page of an item loaded, put on sale on those channels and published on each, as Manuel does it."""
    item_page = client.post("/items", data=item)
    put_on_sale, _ = buttons(item_page.text)["Metti in vendita"]
    offered = checkboxes(item_page.text, "channel")
    client.post(put_on_sale, data={"channel": [offered[channel] for channel in channels]})
    for channel in channels:
        action = client.get(links(sections(client.get("/actions").text)[channel])[f"Pubblica {item['name']}"])
        published, _ = buttons(action.text)["Pubblicato"]
        client.post(published, data={"link": f"https://{channel.lower()}.test/listing"})
    return item_page.url.path


def _sell(client, item_page: str, channel: str, **fields: str):
    """The page of a sale recorded from the item's page, with what Manuel types in the form."""
    form = client.get(links(client.get(item_page).text)["Vendi"])
    record, _ = buttons(form.text)["Registra la vendita"]
    return client.post(record, data={"channel": checkboxes(form.text, "channel")[channel], **fields})
