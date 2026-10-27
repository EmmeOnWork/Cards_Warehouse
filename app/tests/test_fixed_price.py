"""The price Manuel fixes on an item after his market research, the margin it leaves on each channel, and the
reference price he based it on.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html

import pytest

from tests.pages import buttons, links, table_rows

BOOSTER_BOX = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Booster box Evoluzioni a Paldea",
    "language": "it",
    "quantity": "1",
    "total_cost": "100",
}


# The same price on every channel, and a margin that changes with each one's fee: Tilt keeps 2% of 125 plus 0,50.
def test_with_a_fixed_price_every_channel_shows_it_with_its_margin_in_euros_and_percent(signed_in_client):
    item_page = _load(signed_in_client, BOOSTER_BOX)

    signed_in_client.post(f"{item_page}/fixed-price", data={"fixed_price": "125"})

    assert table_rows(signed_in_client.get(item_page).text) == [
        ["Vinted", "125,00 €", "25,00 €", "25 %"],
        ["Tilt", "125,00 €", "22,00 €", "22 %"],
        ["eBay", "125,00 €", "25,00 €", "25 %"],
    ]


# At 101 Vinted and eBay leave 1 on a cost of 100, below the 20% target. Tilt keeps 2,52: 98,48 is left, a loss.
def test_a_price_below_the_target_is_warned_of_and_a_price_at_a_loss_otherwise(signed_in_client):
    item_page = _load(signed_in_client, BOOSTER_BOX)

    signed_in_client.post(f"{item_page}/fixed-price", data={"fixed_price": "101"})

    assert table_rows(signed_in_client.get(item_page).text) == [
        ["Vinted", "101,00 €", "1,00 €", "1 % sotto l'obiettivo"],
        ["Tilt", "101,00 €", "-1,52 €", "-1,52 % in perdita"],
        ["eBay", "101,00 €", "1,00 €", "1 % sotto l'obiettivo"],
    ]


# A gift, or a box bought so long ago that its cost is lost: it still gets a price, and nothing is warned of.
def test_with_a_cost_not_known_a_price_can_be_fixed_and_its_margin_cannot_be_told(signed_in_client):
    item_page = _load(signed_in_client, {**BOOSTER_BOX, "total_cost": "", "unknown_cost": "on"})

    signed_in_client.post(f"{item_page}/fixed-price", data={"fixed_price": "125"})

    assert table_rows(signed_in_client.get(item_page).text) == [
        ["Vinted", "125,00 €", "non calcolabile"],
        ["Tilt", "125,00 €", "non calcolabile"],
        ["eBay", "125,00 €", "non calcolabile"],
    ]


# The page says why, and the prices stay those made from the target.
@pytest.mark.parametrize(
    ("fixed_price", "reason"),
    [
        ("0", "Il prezzo fissato vale almeno 0,01 €."),
        ("centoventi", "Scrivi il prezzo in euro, con al massimo due decimali: per esempio 125,00."),
    ],
)
def test_a_fixed_price_below_one_cent_or_not_in_euros_is_refused_with_its_reason(signed_in_client, fixed_price, reason):
    item_page = _load(signed_in_client, BOOSTER_BOX)

    response = signed_in_client.post(f"{item_page}/fixed-price", data={"fixed_price": fixed_price})

    assert response.status_code == 422
    assert reason in html.unescape(response.text)
    assert _prices(signed_in_client, item_page) == {"Vinted": "120,00 €", "Tilt": "122,96 €", "eBay": "120,00 €"}


# Back to the prices made from the cost and the target, as before the market research.
def test_taking_the_fixed_price_away_brings_back_the_prices_made_from_the_target(signed_in_client):
    item_page = _load(signed_in_client, BOOSTER_BOX)
    signed_in_client.post(f"{item_page}/fixed-price", data={"fixed_price": "125"})

    action, sent = buttons(signed_in_client.get(item_page).text)["Togli il prezzo fissato"]
    signed_in_client.post(action, data=sent)

    assert _prices(signed_in_client, item_page) == {"Vinted": "120,00 €", "Tilt": "122,96 €", "eBay": "120,00 €"}


# What Manuel based the price on, still there when he comes back to the item. One at a time: a new one replaces it.
def test_the_reference_price_is_kept_with_its_date_and_source_and_a_new_one_replaces_it(signed_in_client):
    item_page = _load(signed_in_client, BOOSTER_BOX)
    old = {"reference_price": "110", "reference_on": "2026-10-20", "reference_source": "Vinted, annunci simili"}
    signed_in_client.post(f"{item_page}/reference-price", data=old)

    new = {"reference_price": "118,50", "reference_on": "2026-10-26", "reference_source": "Cardmarket, tendenza"}
    signed_in_client.post(f"{item_page}/reference-price", data=new)

    page = html.unescape(signed_in_client.get(item_page).text)
    assert "Prezzo di riferimento: 118,50 € il 26/10/2026, da Cardmarket, tendenza" in page
    assert "Vinted, annunci simili" not in page


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"reference_source": " "}, "Scrivi dove hai trovato il prezzo: per esempio Cardmarket."),
        ({"reference_price": "0"}, "Il prezzo di riferimento vale almeno 0,01 €."),
        ({"reference_price": "tanto"}, "Scrivi il prezzo in euro, con al massimo due decimali: per esempio 125,00."),
        ({"reference_on": "ieri"}, "Scrivi il giorno in cui l'hai trovato, per esempio 2026-10-26."),
    ],
)
def test_a_reference_price_that_cannot_be_saved_is_refused_with_its_reason(signed_in_client, fields, reason):
    item_page = _load(signed_in_client, BOOSTER_BOX)
    found = {"reference_price": "118,50", "reference_on": "2026-10-26", "reference_source": "Cardmarket", **fields}

    response = signed_in_client.post(f"{item_page}/reference-price", data=found)

    assert response.status_code == 422
    assert reason in html.unescape(response.text)
    assert "Nessun prezzo di riferimento" in signed_in_client.get(item_page).text


def _prices(client, item_page: str) -> dict[str, str]:
    """The price on each channel, as the item's page shows it."""
    return {channel: price for channel, price, *_ in table_rows(client.get(item_page).text)}


def _load(client, item: dict[str, str]) -> str:
    """The item loaded, and the address of its page."""
    client.post("/items", data=item)
    return links(client.get("/items").text)[item["name"]]
