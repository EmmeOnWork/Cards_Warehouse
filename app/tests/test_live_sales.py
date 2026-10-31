"""The end of a live: the copies Manuel sold in it, entered row by row from its inventory, become sales on Tilt. And
the report of what the live left.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html

import pytest

from tests.pages import buttons, choices, form_fields, sections, table_rows, text
from tests.test_live_inventory import ETB, add_item, new_inventory

# Three at 5,00 € each.
BOOSTER_PACK = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Busta Evoluzioni a Paldea",
    "language": "it",
    "quantity": "3",
    "total_cost": "15",
}


# One busta sold at 8,00, one at auction for 6,00: each a Tilt order, which keeps 2% + 0,50 of it, 0,66 and 0,62. Of
# the 14,00 taken, with the two bustas at 5,00 each, 2,72 are left: 27,2% of the cost. A busta opened in the live for
# a buyer is one of these: the cards that came out of it are his, and never enter the warehouse.
def test_the_copies_sold_in_a_live_become_sales_on_tilt_and_its_report_shows_what_the_live_left(signed_in_client):
    item_page = signed_in_client.post("/items", data=BOOSTER_PACK).url.path
    inventory = new_inventory(signed_in_client)
    add_item(signed_in_client, inventory, BOOSTER_PACK["name"])

    _sold(signed_in_client, inventory, BOOSTER_PACK["name"], quantity="1", price="8")
    _sold(signed_in_client, inventory, BOOSTER_PACK["name"], quantity="1", price="6")
    _confirm(signed_in_client, inventory)

    report = sections(signed_in_client.get(inventory).text)["Resoconto"]
    assert "Incasso 14,00 € Commissioni 1,28 € Margine 2,72 € · 27,2 %" in text(report)
    assert table_rows(report) == [[BOOSTER_PACK["name"], "2", "14,00 €"]]
    assert "Copie disponibili 1" in text(signed_in_client.get(item_page).text)


# A busta entered and confirmed right after the live; the second, forgotten, entered the day after and confirmed by a
# tap that went through twice. The first is not sold again, and neither is the second.
def test_an_entry_left_halfway_is_finished_later_and_no_row_is_sold_twice(signed_in_client):
    item_page = signed_in_client.post("/items", data=BOOSTER_PACK).url.path
    inventory = new_inventory(signed_in_client)
    add_item(signed_in_client, inventory, BOOSTER_PACK["name"])
    _sold(signed_in_client, inventory, BOOSTER_PACK["name"], quantity="1", price="8")
    _confirm(signed_in_client, inventory)

    _sold(signed_in_client, inventory, BOOSTER_PACK["name"], quantity="1", price="6")
    address, sent = buttons(signed_in_client.get(inventory).text)["Conferma vendite"]
    signed_in_client.post(address, data=sent)
    signed_in_client.post(address, data=sent)

    assert table_rows(sections(signed_in_client.get(inventory).text)["Resoconto"]) == [
        [BOOSTER_PACK["name"], "2", "14,00 €"]
    ]
    assert "Copie disponibili 1" in text(signed_in_client.get(item_page).text)


# The ETB's cost is not known: the margin is the busta's alone, 8,00 - 0,66 - 5,00 = 2,34, 46,8% of its cost, and the
# report says the ETB is left out of it.
def test_the_report_says_how_many_sales_are_left_out_of_the_margin_for_a_cost_not_known(signed_in_client):
    signed_in_client.post("/items", data=BOOSTER_PACK)
    signed_in_client.post("/items", data={**ETB, "total_cost": "", "unknown_cost": "on"})
    inventory = new_inventory(signed_in_client)
    add_item(signed_in_client, inventory, BOOSTER_PACK["name"])
    add_item(signed_in_client, inventory, ETB["name"])
    _sold(signed_in_client, inventory, BOOSTER_PACK["name"], quantity="1", price="8")
    _sold(signed_in_client, inventory, ETB["name"], quantity="1", price="70")

    _confirm(signed_in_client, inventory)

    report = text(sections(signed_in_client.get(inventory).text)["Resoconto"])
    assert "Margine 2,34 € · 46,8 % 1 vendita a costo sconosciuto, esclusa dal margine." in report


# The second row entered by mistake, and taken off before confirming: it is not sold.
def test_a_row_taken_off_before_confirming_is_not_sold(signed_in_client):
    signed_in_client.post("/items", data=BOOSTER_PACK)
    inventory = new_inventory(signed_in_client)
    add_item(signed_in_client, inventory, BOOSTER_PACK["name"])
    _sold(signed_in_client, inventory, BOOSTER_PACK["name"], quantity="1", price="8")
    _sold(signed_in_client, inventory, BOOSTER_PACK["name"], quantity="2", price="8")

    address, sent = buttons(signed_in_client.get(inventory).text)["Togli la riga 2"]
    signed_in_client.post(address, data=sent)
    _confirm(signed_in_client, inventory)

    assert table_rows(sections(signed_in_client.get(inventory).text)["Resoconto"]) == [
        [BOOSTER_PACK["name"], "1", "8,00 €"]
    ]


# Two ETBs entered, but there is one: until the double sales (task 24), nothing is sold, not even the busta, and the
# page says which item has fewer copies than were entered.
def test_a_confirmation_of_more_copies_than_are_left_sells_nothing_and_says_of_which_item(signed_in_client):
    pack_page = signed_in_client.post("/items", data=BOOSTER_PACK).url.path
    signed_in_client.post("/items", data=ETB)
    inventory = new_inventory(signed_in_client)
    add_item(signed_in_client, inventory, BOOSTER_PACK["name"])
    add_item(signed_in_client, inventory, ETB["name"])
    _sold(signed_in_client, inventory, BOOSTER_PACK["name"], quantity="1", price="8")
    _sold(signed_in_client, inventory, ETB["name"], quantity="2", price="70")

    response = _confirm(signed_in_client, inventory)

    assert response.status_code == 422
    assert "ETB Evoluzioni a Paldea ha 1 copia: non puoi venderne 2." in html.unescape(response.text)
    assert "Resoconto" not in sections(signed_in_client.get(inventory).text)
    assert "Copie disponibili 3" in text(signed_in_client.get(pack_page).text)


# Typed wrong on the second item of the live: the page comes back with what he typed, that item still chosen, and no
# row is entered.
@pytest.mark.parametrize(
    ("quantity", "price", "reason"),
    [
        ("0", "8", "Le copie sono almeno 1."),
        ("1", "0", "Il prezzo vale almeno 0,01 €."),
        ("1", "dieci", "Scrivi il prezzo di una copia in euro, con al massimo due decimali: per esempio 8,50."),
    ],
)
def test_a_row_without_a_copy_or_a_price_of_one_cent_at_least_is_refused_with_what_manuel_typed(
    signed_in_client, quantity, price, reason
):
    signed_in_client.post("/items", data=BOOSTER_PACK)
    etb = signed_in_client.post("/items", data=ETB).url.path
    inventory = new_inventory(signed_in_client)
    add_item(signed_in_client, inventory, BOOSTER_PACK["name"])
    add_item(signed_in_client, inventory, ETB["name"])

    response = _sold(signed_in_client, inventory, ETB["name"], quantity=quantity, price=price)

    assert response.status_code == 422
    assert reason in html.unescape(response.text)
    entry = sections(response.text)["Venduto in live"]
    typed = form_fields(entry)
    assert (typed["item_id"], typed["quantity"], typed["price"]) == ([etb.rsplit("/", 1)[1]], [quantity], [price])
    assert table_rows(entry) == []


def _sold(client, inventory: str, name: str, quantity: str, price: str):
    """A row of the copies of an item sold in the live, at a price for each copy."""
    page = client.get(inventory).text
    address, _ = buttons(page)["Aggiungi riga"]
    return client.post(address, data={"item_id": choices(page, "item_id")[name], "quantity": quantity, "price": price})


def _confirm(client, inventory: str):
    address, sent = buttons(client.get(inventory).text)["Conferma vendite"]
    return client.post(address, data=sent)
