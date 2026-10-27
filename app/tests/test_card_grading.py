"""The grading of a card: sent to a grader, such as PSA, and back with its grade, as an item of its own whose cost
has the grading in it.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html

import pytest

from tests.pages import links, select_options, table_rows, text

CHARIZARD = {
    "kind": "single_card",
    "game": "Pokémon",
    "name": "Charizard ex",
    "language": "it",
    "set_name": "Ossidiana Infuocata",
    "number": "223/197",
    "condition": "near_mint",
    "quantity": "3",
    "total_cost": "100,00",
    "shipping": "4,00",
    "purchased_on": "2026-10-20",
}

# Sent on a day, at Manuel's cost: the form as the tests fill it in, and change one field of.
TO_PSA = {"lot": "1", "sent_on": "2026-10-27", "grader": "PSA", "cost": "15,00", "paid_by": ""}


# Three copies at 34,67 + 34,67 + 34,66 €, shared with Luca, who paid the purchase and the grading. The copy graded
# costs 34,67 + 15,00 €, and its prices are made from that: 49,67 € plus 20% is 59,604, rounded up to 59,61 €.
# On Tilt, (59,61 + 0,50) / 0,98 is 61,336… The other two copies stay where they were, at the cost they had.
def test_a_card_sent_for_grading_comes_back_as_an_item_of_its_own_with_the_grading_in_its_cost(signed_in_client):
    luca = add_partner(signed_in_client, "Luca")
    shared = {"partner": ["", luca], "percent": ["50", "50"], "paid": ["0", "104,00"]}
    raw_card = signed_in_client.post("/items", data={**CHARIZARD, **shared}).url.path

    sending = links(signed_in_client.get(raw_card).text)["Manda a gradare"]
    signed_in_client.post(sending, data={**TO_PSA, "paid_by": luca})
    back = links(signed_in_client.get(raw_card).text)["Tornata"]
    graded_card = signed_in_client.post(back, data={"grade": "9", "returned_on": "2027-01-15"}).url.path

    assert table_rows(signed_in_client.get("/items").text) == [
        ["Charizard ex Ossidiana Infuocata · 223/197 · PSA 9", "Carta singola", "Pokémon", "1"],
        ["Charizard ex Ossidiana Infuocata · 223/197 · Near Mint", "Carta singola", "Pokémon", "2"],
    ]
    graded_page = signed_in_client.get(graded_card).text
    assert "Costo 49,67 € · obiettivo 20 % · netto obiettivo 59,61 €" in text(graded_page)
    assert table_rows(graded_page) == [["Vinted", "59,61 €"], ["Tilt", "61,34 €"], ["eBay", "59,61 €"]]
    assert "PSA 9 · spedita il 27/10/2026 · tornata il 15/01/2027" in text(graded_page)
    assert "Costo della gradazione 15,00 €, pagato da Luca · quote Manuel 50 % · Luca 50 %" in text(graded_page)
    lots_left = links(signed_in_client.get(raw_card).text)["Movimenti e rettifiche"]
    assert select_lots(signed_in_client, lots_left) == ["Lotto 1 · 1 copia · 34,67 €", "Lotto 2 · 1 copia · 34,66 €"]


# The page comes back with the reason and with what Manuel typed, and the copy stays in its lot.
@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"grader": " "}, "Scrivi l'ente che grada la carta: per esempio PSA."),
        ({"cost": ""}, "Scrivi il costo della gradazione in euro, almeno 0,01 €: per esempio 15,00."),
        ({"cost": "0"}, "Scrivi il costo della gradazione in euro, almeno 0,01 €: per esempio 15,00."),
        ({"cost": "quindici"}, "Scrivi il costo della gradazione in euro, almeno 0,01 €: per esempio 15,00."),
        ({"sent_on": "ieri"}, "Scrivi la data della spedizione, per esempio 2026-10-27."),
    ],
)
def test_a_sending_that_cannot_be_saved_is_refused_with_its_reason_and_the_copy_stays(signed_in_client, fields, reason):
    raw_card = signed_in_client.post("/items", data=CHARIZARD).url.path
    sending = links(signed_in_client.get(raw_card).text)["Manda a gradare"]

    response = signed_in_client.post(sending, data={**TO_PSA, **fields})

    assert response.status_code == 422
    page = html.unescape(response.text)
    assert reason in page
    assert f'value="{fields.get("grader", "PSA")}"' in page
    assert table_rows(signed_in_client.get("/items").text)[0][3] == "3"


# One copy, sent already: the lot has none left to send, and the page says so.
def test_a_copy_cannot_be_sent_from_a_lot_with_none_left(signed_in_client):
    raw_card = signed_in_client.post("/items", data={**CHARIZARD, "quantity": "1"}).url.path
    sending = links(signed_in_client.get(raw_card).text)["Manda a gradare"]
    signed_in_client.post(sending, data=TO_PSA)

    response = signed_in_client.post(sending, data=TO_PSA)

    assert response.status_code == 422
    assert "Il lotto 1 non ha copie da mandare a gradare." in html.unescape(response.text)


# A grade the graders do not give: the card stays at the grader, and the page keeps what was typed.
def test_a_return_with_a_grade_not_from_1_to_10_in_half_points_is_refused(signed_in_client):
    raw_card, back = sent_for_grading(signed_in_client)

    response = signed_in_client.post(back, data={"grade": "9,3", "returned_on": "2027-01-15"})

    assert response.status_code == 422
    page = html.unescape(response.text)
    assert "Il voto va da 1 a 10, a mezzi punti: per esempio 9,5." in page
    assert 'value="9,3"' in page
    assert links(signed_in_client.get(raw_card).text)["Tornata"] == back


# A second tap on the phone: the page lands on the card that came back, and there is one of it.
def test_a_return_sent_twice_lands_on_the_one_card_that_came_back(signed_in_client):
    _, back = sent_for_grading(signed_in_client)

    first = signed_in_client.post(back, data={"grade": "9", "returned_on": "2027-01-15"})
    second = signed_in_client.post(back, data={"grade": "9", "returned_on": "2027-01-15"})

    assert second.url.path == first.url.path
    assert len(table_rows(signed_in_client.get("/items").text)) == 2


# A card is graded once, from its condition: a graded card, a sealed or a magazine is not offered it.
@pytest.mark.parametrize(
    "item",
    [
        {**CHARIZARD, "condition": "", "graded": "on", "grader": "PSA", "grade": "10"},
        {"kind": "sealed", "game": "Pokémon", "name": "Booster box", "language": "it", "total_cost": "100"},
    ],
)
def test_only_a_card_in_its_condition_can_be_sent_for_grading(signed_in_client, item):
    item_page = signed_in_client.post("/items", data=item).url.path

    assert "Manda a gradare" not in links(signed_in_client.get(item_page).text)


# The copy leaves one item and comes into another: each history tells its side, and adds up to its copies.
def test_the_history_of_each_item_tells_its_side_of_the_grading(signed_in_client):
    raw_card, back = sent_for_grading(signed_in_client)
    graded_card = signed_in_client.post(back, data={"grade": "9", "returned_on": "2027-01-15"}).url.path

    def history(item_page):
        movements = links(signed_in_client.get(item_page).text)["Movimenti e rettifiche"]
        return [(cause, change) for _, cause, _, change in table_rows(signed_in_client.get(movements).text)]

    assert history(raw_card) == [("Carico", "+2"), ("Carico", "+1"), ("Spedita a gradare", "-1")]
    assert history(graded_card) == [("Tornata gradata", "+1")]


def sent_for_grading(client) -> tuple[str, str]:
    """A copy of the card sent to PSA, as Manuel sends it from its page: the card's page, and where it comes back."""
    raw_card = client.post("/items", data=CHARIZARD).url.path
    client.post(links(client.get(raw_card).text)["Manda a gradare"], data=TO_PSA)
    return raw_card, links(client.get(raw_card).text)["Tornata"]


def add_partner(client, name: str) -> str:
    """The partner added from the app, and the id the pages send for that partner."""
    client.post("/partners", data={"name": name})
    return links(client.get("/partners").text)[name].removeprefix("/partners/")


def select_lots(client, movements: str) -> list[str]:
    """The lots of an item as its adjustments offer them: copies left and unit cost."""
    return select_options(client.get(movements).text, "lot")
