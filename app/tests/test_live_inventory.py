"""The live inventories: the items Manuel shows in a live on Tilt, and the presets he saves them as, to start
the next live from.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html
from datetime import datetime

import pytest

from cards_warehouse.backups import LOCAL_TIME
from tests.pages import buttons, links, table_rows

# Two at 100,00 € each.
BOOSTER_BOX = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Booster box Evoluzioni a Paldea",
    "language": "it",
    "quantity": "2",
    "total_cost": "200",
}
ETB = {**BOOSTER_BOX, "name": "ETB Evoluzioni a Paldea", "quantity": "1", "total_cost": "50"}


# A preset keeps the items, not their copies: an item sold out since the preset was saved comes back in the new
# inventory, flagged, so Manuel takes it off or loads more before going live.
def test_an_inventory_started_from_a_preset_has_its_items_and_flags_those_sold_out(signed_in_client):
    signed_in_client.post("/items", data=BOOSTER_BOX)
    etb_page = signed_in_client.post("/items", data=ETB).url.path
    inventory = _new_inventory(signed_in_client)
    _add(signed_in_client, inventory, BOOSTER_BOX["name"])
    _add(signed_in_client, inventory, ETB["name"])
    _save_as_preset(signed_in_client, inventory, "Venerdì")
    movements = links(signed_in_client.get(etb_page).text)["Movimenti e rettifiche"]
    signed_in_client.post(movements, data={"lot": "1", "cause": "lost", "quantity": "1"})

    started = _start_from(signed_in_client, "Venerdì")

    rows = table_rows(signed_in_client.get(started).text)
    assert [row[:2] for row in rows] == [
        ["Booster box Evoluzioni a Paldea", "2"],
        ["ETB Evoluzioni a Paldea esaurito", "0"],
    ]


# A part of the name, in any case, finds the item. Tapped twice, it is still one row.
def test_an_item_found_by_part_of_its_name_is_added_once_even_if_added_twice(signed_in_client):
    signed_in_client.post("/items", data=BOOSTER_BOX)
    inventory = _new_inventory(signed_in_client)
    found = signed_in_client.get(inventory, params={"q": "booster BOX"}).text
    address, sent = buttons(found)["Aggiungi Booster box Evoluzioni a Paldea"]

    signed_in_client.post(address, data=sent)
    signed_in_client.post(address, data=sent)

    assert [row[0] for row in table_rows(signed_in_client.get(inventory).text)] == [BOOSTER_BOX["name"]]


# Tilt keeps 2% + 0,50 €: 120,50 / 0,98 = 122,959…, the price that leaves the cost of 100,00 € plus 20%.
def test_each_item_shows_the_copies_available_and_its_price_on_tilt(signed_in_client):
    signed_in_client.post("/items", data=BOOSTER_BOX)
    inventory = _new_inventory(signed_in_client)
    _add(signed_in_client, inventory, BOOSTER_BOX["name"])

    (row,) = table_rows(signed_in_client.get(inventory).text)

    assert row[1:3] == ["2", "122,96 €"]


# With no cost there is no target net, and any price would be a guess.
def test_an_item_whose_cost_is_not_known_has_no_price_on_tilt_and_the_row_says_why(signed_in_client):
    signed_in_client.post("/items", data={**BOOSTER_BOX, "total_cost": "", "unknown_cost": "on"})
    inventory = _new_inventory(signed_in_client)
    _add(signed_in_client, inventory, BOOSTER_BOX["name"])

    (row,) = table_rows(signed_in_client.get(inventory).text)

    assert row[2] == "costo sconosciuto"


def test_an_inventory_saved_as_a_preset_with_a_name_is_offered_to_start_the_next_live_from(signed_in_client):
    signed_in_client.post("/items", data=BOOSTER_BOX)
    inventory = _new_inventory(signed_in_client)
    _add(signed_in_client, inventory, BOOSTER_BOX["name"])

    _save_as_preset(signed_in_client, inventory, "Venerdì")

    assert "Parti da Venerdì" in buttons(signed_in_client.get("/lives").text)


# Two presets with one name could not be told apart. To change a preset, Manuel saves it with a new name.
@pytest.mark.parametrize(
    ("name", "reason"),
    [(" ", "Scrivi il nome della configurazione."), ("Venerdì", "La configurazione Venerdì c'è già.")],
)
def test_a_preset_that_cannot_be_saved_is_refused_with_its_reason(signed_in_client, name, reason):
    inventory = _new_inventory(signed_in_client)
    _save_as_preset(signed_in_client, inventory, "Venerdì")

    response = _save_as_preset(signed_in_client, inventory, name)

    assert response.status_code == 422
    assert reason in html.unescape(response.text)
    assert len(_presets(signed_in_client)) == 1


def test_an_item_taken_off_the_inventory_is_no_longer_in_it(signed_in_client):
    signed_in_client.post("/items", data=BOOSTER_BOX)
    signed_in_client.post("/items", data=ETB)
    inventory = _new_inventory(signed_in_client)
    _add(signed_in_client, inventory, BOOSTER_BOX["name"])
    _add(signed_in_client, inventory, ETB["name"])

    _take_off(signed_in_client, inventory, ETB["name"])

    assert [row[0] for row in table_rows(signed_in_client.get(inventory).text)] == [BOOSTER_BOX["name"]]


# The preset started from keeps the items it was saved with, whatever is done to the inventory born from it.
def test_changing_an_inventory_started_from_a_preset_leaves_the_preset_as_it_was(signed_in_client):
    signed_in_client.post("/items", data=BOOSTER_BOX)
    signed_in_client.post("/items", data=ETB)
    first = _new_inventory(signed_in_client)
    _add(signed_in_client, first, BOOSTER_BOX["name"])
    _save_as_preset(signed_in_client, first, "Venerdì")

    started = _start_from(signed_in_client, "Venerdì")
    _take_off(signed_in_client, started, BOOSTER_BOX["name"])
    _add(signed_in_client, started, ETB["name"])

    again = _start_from(signed_in_client, "Venerdì")
    assert [row[0] for row in table_rows(signed_in_client.get(again).text)] == [BOOSTER_BOX["name"]]
    assert [row[0] for row in table_rows(signed_in_client.get(started).text)] == [ETB["name"]]


# Where the inventory of the coming live is found again: the newest first, with its day and its items.
def test_the_inventories_are_listed_on_the_page_of_the_lives_the_newest_first(signed_in_client):
    signed_in_client.post("/items", data=BOOSTER_BOX)
    _new_inventory(signed_in_client)
    newest = _new_inventory(signed_in_client)
    _add(signed_in_client, newest, BOOSTER_BOX["name"])

    today = f"{datetime.now(LOCAL_TIME):%d/%m/%Y}"
    assert table_rows(signed_in_client.get("/lives").text) == [[today, "1"], [today, "0"]]


def _presets(client) -> list[str]:
    return [label for label in buttons(client.get("/lives").text) if label.startswith("Parti da ")]


def _take_off(client, inventory: str, name: str) -> None:
    address, sent = buttons(client.get(inventory).text)[f"Togli {name}"]
    client.post(address, data=sent)


def _new_inventory(client) -> str:
    address, sent = buttons(client.get("/lives").text)["Nuovo inventario"]
    return client.post(address, data=sent).url.path


def _add(client, inventory: str, name: str) -> None:
    """The item found by its name, and added to the inventory."""
    found = client.get(inventory, params={"q": name}).text
    address, sent = buttons(found)[f"Aggiungi {name}"]
    client.post(address, data=sent)


def _save_as_preset(client, inventory: str, name: str):
    address, sent = buttons(client.get(inventory).text)["Salva come configurazione"]
    return client.post(address, data={**sent, "name": name})


def _start_from(client, preset: str) -> str:
    address, sent = buttons(client.get("/lives").text)[f"Parti da {preset}"]
    return client.post(address, data=sent).url.path
