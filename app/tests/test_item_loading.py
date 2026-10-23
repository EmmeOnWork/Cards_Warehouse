"""Loading an item with its first lot from the phone's form, and reading it back from the list.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html

import pytest

from tests.pages import select_options, table_rows

SEALED_BOX = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Booster box Evoluzioni a Paldea",
    "language": "it",
    "quantity": "1",
    "unit_cost": "89,90",
}


# Five identical boxes are one item with a lot of 5, not five items.
def test_a_sealed_in_5_identical_copies_is_listed_once_with_5_available(signed_in_client):
    signed_in_client.post("/items", data={**SEALED_BOX, "quantity": "5"})

    rows = table_rows(signed_in_client.get("/items").text)

    assert rows == [["Booster box Evoluzioni a Paldea", "Sealed", "Pokémon", "5"]]


# A cost forgotten is not a cost of zero: the margins will leave the item out, and the list shows which ones.
def test_a_cost_not_known_is_saved_as_such_and_marked_in_the_list(signed_in_client):
    long_ago = {**SEALED_BOX, "name": "Bought long ago", "unit_cost": "", "unknown_cost": "on"}
    signed_in_client.post("/items", data=long_ago)
    signed_in_client.post("/items", data={**SEALED_BOX, "name": "Bought last week"})

    last_week_row, long_ago_row = table_rows(signed_in_client.get("/items").text)

    assert long_ago_row[0] == "Bought long ago costo sconosciuto"
    assert last_week_row[0] == "Bought last week"


# The page comes back with the reason and with what Manuel typed, so on the phone he fixes one field, not all.
def test_a_known_cost_of_zero_is_refused_pointing_to_the_cost_not_known(signed_in_client):
    response = signed_in_client.post("/items", data={**SEALED_BOX, "unit_cost": "0"})

    assert response.status_code == 422
    page = html.unescape(response.text)
    assert "Il costo vale almeno 0,01 €: se non lo conosci, spunta «Costo sconosciuto»." in page
    assert 'value="Booster box Evoluzioni a Paldea"' in page
    assert table_rows(signed_in_client.get("/items").text) == []


# Topps is not among the first four games: Manuel adds it while he loads, and the next load offers it.
def test_a_new_game_typed_on_the_load_page_is_used_at_once(signed_in_client):
    signed_in_client.post("/items", data={**SEALED_BOX, "new_game": "Topps", "name": "Topps Chrome F1"})

    assert table_rows(signed_in_client.get("/items").text)[0][2] == "Topps"
    load_page = signed_in_client.get("/items/new").text
    assert select_options(load_page, "game") == ["Magic", "One Piece", "Pokémon", "Topps", "Yu-Gi-Oh"]


# The bulk of a game is born from an opening, with a rough count of its cards: not from this page.
def test_the_bulk_kind_is_neither_offered_nor_accepted_by_the_load_page(signed_in_client):
    assert select_options(signed_in_client.get("/items/new").text, "kind") == ["Carta singola", "Sealed", "Rivista"]

    response = signed_in_client.post("/items", data={**SEALED_BOX, "kind": "bulk"})

    assert response.status_code == 422
    assert table_rows(signed_in_client.get("/items").text) == []


# A cost left empty is not taken as unknown: that is said with the tick, so that a forgotten field is caught.
@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"unit_cost": ""}, "Scrivi il costo di una copia, oppure spunta «Costo sconosciuto»."),
        ({"unit_cost": "12,345"}, "Scrivi il costo in euro, con al massimo due decimali: per esempio 12,50."),
        ({"quantity": "0"}, "Le copie sono almeno 1."),
        ({"quantity": "due"}, "Le copie sono almeno 1."),
    ],
)
def test_a_lot_that_cannot_be_saved_is_refused_with_its_reason(signed_in_client, fields, reason):
    response = signed_in_client.post("/items", data={**SEALED_BOX, **fields})

    assert response.status_code == 422
    assert reason in html.unescape(response.text)
    assert table_rows(signed_in_client.get("/items").text) == []
