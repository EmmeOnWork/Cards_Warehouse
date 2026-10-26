"""Purchases: the origin of the lots, with what they cost, who shares them and who paid what.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html

import pytest

from tests.pages import links, table_rows

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


def add_partner(client, name: str) -> str:
    """The partner added from the app, and the id the load page sends for that partner."""
    client.post("/partners", data={"name": name})
    return links(client.get("/partners").text)[name].removeprefix("/partners/")
