"""Purchases: the origin of the lots, with what they cost, who shares them and who paid what.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html

import pytest

from tests.pages import buttons, form_fields, links, table_rows, text

BOXES = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Booster box Evoluzioni a Paldea",
    "language": "it",
    "quantity": "3",
    "total_cost": "100,00",
    "shipping": "4,00",
    "purchased_on": "2026-10-20",
    "purchase_note": "Dal negozio di Milano",
}


# 104,00 € in three is 34,666…: two copies take the cent left over, and the three add up to the purchase again.
def test_a_purchase_of_3_boxes_shared_with_a_partner_who_paid_it_all_is_read_back_whole(signed_in_client):
    luca = add_partner(signed_in_client, "Luca")

    signed_in_client.post(
        "/items", data={**BOXES, "partner": ["", luca], "percent": ["50", "50"], "paid": ["0", "104,00"]}
    )

    assert table_rows(signed_in_client.get("/purchases").text) == [
        [
            "20/10/2026 Booster box Evoluzioni a Paldea × 3 Dal negozio di Milano",
            "100,00 € + spedizione 4,00 € per copia 34,67 € × 2 34,66 € × 1",
            "Manuel 50 % · pagato 0,00 € Luca 50 % · pagato 104,00 €",
        ]
    ]


# A column left empty is all Manuel's: with no share typed he has 100%, with no payment typed he paid it all.
@pytest.mark.parametrize(
    ("percent", "shares"),
    [
        (["", ""], "Manuel 100 % · pagato 104,00 €"),
        (["50", "50"], "Manuel 50 % · pagato 104,00 € Luca 50 % · pagato 0,00 €"),
    ],
)
def test_with_no_payment_typed_manuel_paid_it_all(signed_in_client, percent, shares):
    luca = add_partner(signed_in_client, "Luca")

    signed_in_client.post("/items", data={**BOXES, "partner": ["", luca], "percent": percent, "paid": ["", ""]})

    assert table_rows(signed_in_client.get("/purchases").text)[0][2] == shares


# The page comes back with the reason and with what Manuel typed, so on the phone he fixes one field, not all.
@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"percent": ["40", "50"], "paid": ["", ""]}, "Le quote fanno 90 %: devono fare 100 %."),
        (
            {"percent": ["50", "50"], "paid": ["0", "100,00"]},
            "I pagamenti fanno 100,00 €: devono fare 104,00 €, il costo più la spedizione.",
        ),
        (
            {"total_cost": "0,02", "shipping": ""},
            "Il costo totale, spedizione compresa, non basta a dare 0,01 € a ogni copia.",
        ),
        ({"percent": ["50", "metà"], "paid": ["", ""]}, "Scrivi le quote in percentuali intere, da 0 a 100"),
    ],
)
def test_a_purchase_that_cannot_be_saved_is_refused_with_its_reason_and_nothing_is_loaded(
    signed_in_client, fields, reason
):
    luca = add_partner(signed_in_client, "Luca")

    every_row = {"partner": ["", luca], "percent": ["", ""], "paid": ["", ""]}
    response = signed_in_client.post("/items", data={**BOXES, **every_row, **fields})

    assert response.status_code == 422
    page = html.unescape(response.text)
    assert reason in page
    assert 'value="Dal negozio di Milano"' in page
    assert table_rows(signed_in_client.get("/purchases").text) == []
    assert table_rows(signed_in_client.get("/items").text) == []


CHARIZARD = {
    "kind": "single_card",
    "game": "Pokémon",
    "name": "Charizard ex",
    "language": "it",
    "condition": "near_mint",
    "quantity": "1",
}
PIKACHU = {**CHARIZARD, "name": "Pikachu", "condition": "excellent"}
CARDS_AT_THE_FAIR = {
    "total_cost": "100,00",
    "shipping": "1,00",
    "purchased_on": "2026-10-20",
    "purchase_note": "Alla fiera di Verona",
}


# A card worth 200 € and one worth 2 €, bought together for 101 €: the first costs 100 € and the second 1 €, not
# 50,50 € each. Typed on the phone one after the other, and loaded together: the page sends back what it shows.
def test_a_mixed_purchase_typed_piece_by_piece_splits_its_cost_by_the_estimated_values(signed_in_client):
    with_one_piece = added_piece(signed_in_client, {**CHARIZARD, "estimated_value": "200,00", **CARDS_AT_THE_FAIR})

    second = {**PIKACHU, "estimated_value": "2,00"}
    loaded = signed_in_client.post("/items", data={**form_fields(with_one_piece), **second})

    assert loaded.url.path == "/purchases"
    assert table_rows(loaded.text) == [
        [
            "20/10/2026 Charizard ex × 1 Pikachu × 1 Alla fiera di Verona",
            "100,00 € + spedizione 1,00 € per copia Charizard ex 100,00 € × 1 Pikachu 1,00 € × 1",
            "Manuel 100 % · pagato 101,00 €",
        ]
    ]


# Without a value, or at nothing, the cost cannot be split: the page says which piece, and keeps what was typed.
@pytest.mark.parametrize("estimated_value", ["", "0,00"])
def test_a_piece_of_a_mixed_purchase_estimated_below_a_cent_or_not_at_all_is_refused(signed_in_client, estimated_value):
    with_one_piece = added_piece(signed_in_client, {**CHARIZARD, "estimated_value": "200,00", **CARDS_AT_THE_FAIR})

    second = {**PIKACHU, "estimated_value": estimated_value}
    response = signed_in_client.post("/items", data={**form_fields(with_one_piece), **second})

    assert response.status_code == 422
    page = html.unescape(response.text)
    assert "Scrivi quanto vale una copia di «Pikachu», almeno 0,01 €" in page
    assert 'value="Pikachu"' in page
    assert "Charizard ex × 1 · stimata 200,00 €" in text(page)
    assert table_rows(signed_in_client.get("/purchases").text) == []
    assert table_rows(signed_in_client.get("/items").text) == []


# Checked as it is added, while it is still on the screen: once added, it can only be taken away.
def test_a_piece_added_without_its_estimated_value_is_refused_at_once(signed_in_client):
    load_page = signed_in_client.get("/items/new").text
    _, add_piece = buttons(load_page)["Aggiungi un altro pezzo"]

    response = signed_in_client.post("/items", data={**form_fields(load_page), **CHARIZARD, **add_piece})

    assert response.status_code == 422
    assert "Scrivi quanto vale una copia di «Charizard ex»" in html.unescape(response.text)


# Charizard was added by mistake: taken away, Pikachu, half typed, stays on the screen, and is loaded on its own.
def test_a_piece_added_by_mistake_is_taken_away_and_the_one_being_typed_stays(signed_in_client):
    with_one_piece = added_piece(signed_in_client, {**CHARIZARD, "estimated_value": "200,00", **CARDS_AT_THE_FAIR})
    _, take_away = buttons(with_one_piece)["Togli Charizard ex"]

    without = signed_in_client.post("/items", data={**form_fields(with_one_piece), **PIKACHU, **take_away})
    assert 'value="Pikachu"' in without.text
    signed_in_client.post("/items", data=form_fields(without.text))

    assert [row[0] for row in table_rows(signed_in_client.get("/purchases").text)] == [
        "20/10/2026 Pikachu × 1 Alla fiera di Verona"
    ]


# The keyboard's Enter, or Go on the phone, presses the first button of a form: it loads, and takes nothing away.
def test_enter_on_the_load_page_loads_even_with_pieces_added(signed_in_client):
    with_one_piece = added_piece(signed_in_client, {**CHARIZARD, "estimated_value": "200,00", **CARDS_AT_THE_FAIR})

    load_form = [label for label, (address, _) in buttons(with_one_piece).items() if address == "/items"]
    assert load_form[0] == "Carica"


# A cost not known has nothing to split: no value is asked, and each item is loaded with its cost not known.
def test_pieces_of_a_cost_not_known_are_loaded_without_a_cost_and_without_a_value(signed_in_client):
    with_one_piece = added_piece(signed_in_client, {**CHARIZARD, "unknown_cost": "on"})

    loaded = signed_in_client.post("/items", data={**form_fields(with_one_piece), **PIKACHU})

    assert loaded.url.path == "/items"
    assert sorted(row[0] for row in table_rows(loaded.text)) == [
        "Charizard ex costo sconosciuto Near Mint",
        "Pikachu costo sconosciuto Excellent",
    ]
    assert table_rows(signed_in_client.get("/purchases").text) == []


def added_piece(client, fields: dict) -> str:
    """The load page once a piece is added to it, as the phone shows it to type the next."""
    load_page = client.get("/items/new").text
    _, add_piece = buttons(load_page)["Aggiungi un altro pezzo"]
    return client.post("/items", data={**form_fields(load_page), **fields, **add_piece}).text


def add_partner(client, name: str) -> str:
    """The partner added from the app, and the id the load page sends for that partner."""
    client.post("/partners", data={"name": name})
    return links(client.get("/partners").text)[name].removeprefix("/partners/")
