"""The fields of each kind of item: set, number, variant, condition and grading for a single card, product type
and set for a sealed, none of them for a magazine. And the values already typed, suggested again.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html
import re

import pytest

from tests.pages import suggestions, table_rows

CHARIZARD = {
    "kind": "single_card",
    "game": "Pokémon",
    "name": "Charizard ex",
    "language": "it",
    "quantity": "1",
    "total_cost": "120,00",
    "set_name": "Ossidiana Infuocata",
    "number": "223/197",
    "variant": "Special Illustration Rare",
}
UNGRADED_CARD = {**CHARIZARD, "condition": "near_mint"}
GRADED_CARD = {**CHARIZARD, "graded": "on", "grader": "PSA", "grade": "10"}
SEALED_BOX = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Booster box Ossidiana Infuocata",
    "language": "ja",
    "quantity": "3",
    "total_cost": "95,00",
    "product_type": "Booster box",
    "set_name": "Ossidiana Infuocata",
}


# The slab says what state the card is in: the grade takes the place of the condition.
def test_a_graded_card_is_listed_with_its_grader_and_grade(signed_in_client):
    signed_in_client.post("/items", data=GRADED_CARD)

    rows = table_rows(signed_in_client.get("/items").text)

    name_cell = "Charizard ex Ossidiana Infuocata · 223/197 · Special Illustration Rare · PSA 10"
    assert rows == [[name_cell, "Carta singola", "Pokémon", "1"]]


def test_a_sealed_is_listed_with_its_product_type_and_set(signed_in_client):
    signed_in_client.post("/items", data=SEALED_BOX)

    rows = table_rows(signed_in_client.get("/items").text)

    assert rows == [["Booster box Ossidiana Infuocata Booster box · Ossidiana Infuocata", "Sealed", "Pokémon", "3"]]


def test_a_grade_in_half_points_is_read_with_the_comma(signed_in_client):
    signed_in_client.post("/items", data={**GRADED_CARD, "grader": "BGS", "grade": "9.5"})

    name_cell = table_rows(signed_in_client.get("/items").text)[0][0]

    assert name_cell.endswith(" · BGS 9,5")


def test_a_card_not_graded_is_listed_with_its_set_number_variant_and_condition(signed_in_client):
    signed_in_client.post("/items", data=UNGRADED_CARD)

    name_cell = table_rows(signed_in_client.get("/items").text)[0][0]

    assert name_cell == "Charizard ex Ossidiana Infuocata · 223/197 · Special Illustration Rare · Near Mint"


# A card in another state is another item, with a price of its own: its copies are never counted together.
def test_the_same_card_in_two_conditions_is_two_items_with_their_own_stock(signed_in_client):
    signed_in_client.post("/items", data={**UNGRADED_CARD, "quantity": "3"})
    signed_in_client.post("/items", data={**UNGRADED_CARD, "condition": "light_played"})

    rows = table_rows(signed_in_client.get("/items").text)

    assert [(row[0].rsplit(" · ", 1)[1], row[3]) for row in rows] == [("Light Played", "1"), ("Near Mint", "3")]


# The page hides the fields of the other kinds, but the browser still sends them: Manuel may have typed in them
# before changing his mind. Only the fields of the kind chosen, and of the state of the card, are saved.
@pytest.mark.parametrize(
    ("form", "name_cell"),
    [
        (
            {**UNGRADED_CARD, **SEALED_BOX, "kind": "magazine", "name": "Pokémon Magazine 12", "grade": "10"},
            "Pokémon Magazine 12",
        ),
        (
            {**SEALED_BOX, "number": "223/197", "variant": "Reverse", "condition": "mint", "grader": "PSA"},
            "Booster box Ossidiana Infuocata Booster box · Ossidiana Infuocata",
        ),
        (
            {**UNGRADED_CARD, "product_type": "Booster box", "grader": "PSA", "grade": "10"},
            "Charizard ex Ossidiana Infuocata · 223/197 · Special Illustration Rare · Near Mint",
        ),
        (
            {**GRADED_CARD, "condition": "poor"},
            "Charizard ex Ossidiana Infuocata · 223/197 · Special Illustration Rare · PSA 10",
        ),
    ],
    ids=["magazine", "sealed", "card-not-graded", "card-graded"],
)
def test_the_fields_not_asked_for_are_not_saved(signed_in_client, form, name_cell):
    signed_in_client.post("/items", data=form)

    assert table_rows(signed_in_client.get("/items").text)[0][0] == name_cell


GRADE_FROM_1_TO_10 = "Il voto va da 1 a 10, a mezzi punti: per esempio 9,5."


# No condition is chosen for him: a field forgotten must not pass for Near Mint.
@pytest.mark.parametrize(
    ("form", "reason"),
    [
        (CHARIZARD, "Scegli la condizione della carta, oppure spunta «Carta gradata»."),
        ({**GRADED_CARD, "grader": " "}, "Scrivi l'ente che ha gradato la carta: per esempio PSA."),
        ({**GRADED_CARD, "grade": ""}, GRADE_FROM_1_TO_10),
        ({**GRADED_CARD, "grade": "dieci"}, GRADE_FROM_1_TO_10),
        ({**GRADED_CARD, "grade": "9,3"}, GRADE_FROM_1_TO_10),
        ({**GRADED_CARD, "grade": "0,5"}, GRADE_FROM_1_TO_10),
        ({**GRADED_CARD, "grade": "10,5"}, GRADE_FROM_1_TO_10),
    ],
    ids=["no-condition", "no-grader", "no-grade", "grade-in-words", "grade-not-in-half-points", "under-1", "over-10"],
)
def test_a_card_that_cannot_be_saved_is_refused_with_its_reason(signed_in_client, form, reason):
    response = signed_in_client.post("/items", data=form)

    assert response.status_code == 422
    assert reason in html.unescape(response.text)
    assert table_rows(signed_in_client.get("/items").text) == []


# On the phone he fixes the grade, and does not type the set, the number and the grader again.
def test_a_card_refused_comes_back_with_its_fields_as_typed(signed_in_client):
    response = signed_in_client.post("/items", data={**GRADED_CARD, "grade": "9,3"})

    page = html.unescape(response.text)
    for typed in ("Ossidiana Infuocata", "223/197", "Special Illustration Rare", "PSA", "9,3"):
        assert f'value="{typed}"' in page
    assert re.search(r'<input[^>]*name="graded"[^>]*checked', page)


# Typed once, then picked: the set is written the same way every time, and only among the sets of its game.
def test_a_set_already_used_is_suggested_in_its_game_only(signed_in_client):
    signed_in_client.post("/items", data=UNGRADED_CARD)
    signed_in_client.post("/items", data={**SEALED_BOX, "set_name": "Evoluzioni a Paldea"})
    signed_in_client.post("/items", data={**SEALED_BOX, "game": "One Piece", "set_name": "Romance Dawn"})

    sets = suggestions(signed_in_client.get("/items/new").text, "set_name")

    assert sets == {"One Piece": ["Romance Dawn"], "Pokémon": ["Evoluzioni a Paldea", "Ossidiana Infuocata"]}


# PSA grades the cards of every game: the grader typed for a Pokémon card is offered for One Piece too.
def test_variant_and_product_type_are_suggested_in_their_game_and_the_grader_in_every_game(signed_in_client):
    signed_in_client.post("/items", data=GRADED_CARD)
    signed_in_client.post("/items", data=SEALED_BOX)

    page = signed_in_client.get("/items/new").text

    assert suggestions(page, "variant") == {"Pokémon": ["Special Illustration Rare"]}
    assert suggestions(page, "product_type") == {"Pokémon": ["Booster box"]}
    assert suggestions(page, "grader") == {"": ["PSA"]}
