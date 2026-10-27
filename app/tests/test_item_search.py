"""Finding an item in the list in a few seconds, from the phone too: filters by kind, game, language and condition,
and a search in free text. They combine.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import re

import pytest

from tests.pages import form_fields, links, select_options


def card(name: str, game: str = "Pokémon", language: str = "ja", condition: str = "near_mint", **fields) -> dict:
    return {
        "kind": "single_card",
        "game": game,
        "name": name,
        "language": language,
        "condition": condition,
        "quantity": "1",
        "total_cost": "10,00",
        **fields,
    }


# Each one differs from Charizard in one field only, apart from the box, which has no condition.
SHOP = [
    card("Charizard"),
    card("Pikachu", language="it"),
    card("Luffy", game="One Piece"),
    card("Mewtwo", condition="light_played"),
    {"kind": "sealed", "game": "Pokémon", "name": "Booster box", "language": "ja", "quantity": "1", "total_cost": "90"},
]


def load(client, *forms: dict) -> list[str]:
    """The address of each item loaded. Without going on to its page: only the list is under test."""
    responses = [client.post("/items", data=form, follow_redirects=False) for form in forms]
    assert [response.status_code for response in responses] == [303] * len(forms)
    return [response.headers["location"] for response in responses]


def names_listed(page: str) -> list[str]:
    """The names of the items in the list, in its order: the links to an item's page."""
    return [text for text, href in links(page).items() if re.fullmatch(r"/items/\d+", href)]


@pytest.mark.parametrize(
    ("filters", "found"),
    [
        ({"kind": "single_card"}, ["Mewtwo", "Luffy", "Pikachu", "Charizard"]),
        ({"kind": "single_card", "game": "Pokémon"}, ["Mewtwo", "Pikachu", "Charizard"]),
        ({"kind": "single_card", "game": "Pokémon", "language": "ja"}, ["Mewtwo", "Charizard"]),
        ({"kind": "single_card", "game": "Pokémon", "language": "ja", "condition": "near_mint"}, ["Charizard"]),
        ({"game": "Pokémon", "language": "ja"}, ["Booster box", "Mewtwo", "Charizard"]),
        ({"kind": "sealed", "language": "it"}, []),
    ],
    ids=["kind", "kind-game", "kind-game-language", "all-four", "game-language", "none-left"],
)
def test_the_filters_combine(signed_in_client, filters, found):
    load(signed_in_client, *SHOP)

    page = signed_in_client.get("/items", params=filters).text

    assert names_listed(page) == found


MAGAZINE = {"kind": "magazine", "game": "Pokémon", "name": "Pokémon Magazine 12", "language": "it", "quantity": "1"}


# Typed on the phone in a hurry: in lower case, and without the accent of Pokémon.
@pytest.mark.parametrize(
    ("text", "found"),
    [("chariz", ["Charizard"]), ("pokemon", ["Pokémon Magazine 12"]), ("POKÉMON", ["Pokémon Magazine 12"])],
    ids=["part-of-the-name", "without-the-accent", "in-capitals-with-the-accent"],
)
def test_the_search_finds_an_item_by_part_of_its_name_in_any_case_and_with_or_without_accents(
    signed_in_client, text, found
):
    load(signed_in_client, *SHOP, {**MAGAZINE, "unknown_cost": "on"})

    page = signed_in_client.get("/items", params={"q": text}).text

    assert names_listed(page) == found


@pytest.mark.parametrize(
    "text",
    ["ossidiana", "223/197", "raccoglitore blu"],
    ids=["set", "number", "notes"],
)
def test_the_search_finds_an_item_by_its_set_number_or_notes(signed_in_client, text):
    zard = card("Charizard ex", set_name="Ossidiana Infuocata", number="223/197", notes="Nel raccoglitore blu")
    load(signed_in_client, *SHOP, zard)

    page = signed_in_client.get("/items", params={"q": text}).text

    assert names_listed(page) == ["Charizard ex"]


# The name and the set, as he says them: each word is looked for on its own, in any field and in any order.
@pytest.mark.parametrize("text", ["charizard ossidiana", "ossidiana  charizard"])
def test_each_word_searched_can_be_in_a_different_field(signed_in_client, text):
    load(
        signed_in_client,
        card("Charizard ex", set_name="Ossidiana Infuocata"),
        card("Charizard V", set_name="Astri Lucenti"),
        card("Tyranitar", set_name="Ossidiana Infuocata"),
    )

    page = signed_in_client.get("/items", params={"q": text}).text

    assert names_listed(page) == ["Charizard ex"]


# The box of a set, not its cards.
def test_the_search_combines_with_the_filters(signed_in_client):
    box = {**SHOP[-1], "name": "Booster box Ossidiana Infuocata"}
    load(signed_in_client, box, card("Charizard ex", set_name="Ossidiana Infuocata"))

    page = signed_in_client.get("/items", params={"q": "ossidiana", "kind": "sealed"}).text

    assert names_listed(page) == ["Booster box Ossidiana Infuocata"]


# The last copy lost: the card is out of the way, until he asks for the items sold out too.
def test_the_items_sold_out_are_hidden_unless_asked_for(signed_in_client):
    pikachu, _ = load(signed_in_client, card("Pikachu"), card("Charizard"))
    lost = {"lot": "1", "cause": "lost", "quantity": "1"}
    assert signed_in_client.post(f"{pikachu}/movements", data=lost, follow_redirects=False).status_code == 303

    assert names_listed(signed_in_client.get("/items").text) == ["Charizard"]
    assert names_listed(signed_in_client.get("/items", params={"sold_out": "on"}).text) == ["Charizard", "Pikachu"]


# A graded card has no condition: the grade takes its place.
def test_the_condition_graded_keeps_the_graded_cards_only(signed_in_client):
    graded = card("Charizard PSA", condition="", graded="on", grader="PSA", grade="10")
    load(signed_in_client, graded, *SHOP)

    page = signed_in_client.get("/items", params={"condition": "graded"}).text

    assert names_listed(page) == ["Charizard PSA"]


# Back on the list with the search he made, to narrow it further or to take a filter away.
@pytest.mark.parametrize(
    "made",
    [
        {"q": "", "kind": "", "game": "", "language": "", "condition": ""},
        {
            "q": "chari",
            "kind": "single_card",
            "game": "Pokémon",
            "language": "ja",
            "condition": "graded",
            "sold_out": "on",
        },
    ],
    ids=["none", "every-field"],
)
def test_the_form_of_the_list_sent_as_it_is_makes_the_same_search(signed_in_client, made):
    page = signed_in_client.get("/items", params=made).text

    assert form_fields(page) == {field: [value] for field, value in made.items()}


def test_the_filters_offer_every_kind_game_language_and_condition(signed_in_client):
    page = signed_in_client.get("/items").text

    assert select_options(page, "kind") == ["Tutti i tipi", "Carta singola", "Sealed", "Rivista", "Bulk"]
    assert select_options(page, "game") == ["Tutti i giochi", "Magic", "One Piece", "Pokémon", "Yu-Gi-Oh"]
    assert select_options(page, "language")[:3] == ["Tutte le lingue", "Italiano", "Inglese"]
    assert select_options(page, "condition") == [
        "Tutte le condizioni",
        "Mint",
        "Near Mint",
        "Excellent",
        "Good",
        "Light Played",
        "Played",
        "Poor",
        "Gradata",
    ]


# The shop is not empty: the search is too narrow.
def test_a_search_that_finds_nothing_says_so(signed_in_client):
    load(signed_in_client, *SHOP)

    page = signed_in_client.get("/items", params={"q": "blastoise"}).text

    assert "Nessun articolo trovato." in page
