"""The channels with their fee rules, the target margin, and the price each channel proposes for an item.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import html

import pytest

from tests.pages import links, table_rows

BOOSTER_BOX = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Booster box Evoluzioni a Paldea",
    "language": "it",
    "quantity": "1",
    "total_cost": "100",
}


# The fees checked on 2026-10-25. On Vinted a listing is one copy, and closes when it is sold (tasks 20, 21, 22).
def test_the_app_starts_with_vinted_tilt_and_ebay_and_their_fees(signed_in_client):
    assert table_rows(signed_in_client.get("/channels").text) == [
        ["Vinted", "0 %", "no"],
        ["Tilt", "2 % + 0,50 €", "sì"],
        ["eBay", "0 %", "sì"],
    ]


# The PRD's example: the platform keeps 13,33 of 133,34, and 120,01 is left, the cost plus 20%.
def test_with_cost_100_target_20_and_a_fee_of_10_percent_the_price_proposed_is_133_34(signed_in_client):
    tilt = links(signed_in_client.get("/channels").text)["Tilt"]
    signed_in_client.post(tilt, data={"fee_percent": "10", "fee_fixed": "0"})
    signed_in_client.post("/items", data=BOOSTER_BOX)

    prices = _prices(signed_in_client, BOOSTER_BOX["name"])

    assert prices["Tilt"] == "133,34 €"


# With no cost there is no target net: any price proposed would be a guess.
def test_for_an_item_whose_cost_is_not_known_no_price_is_proposed_and_the_page_says_why(signed_in_client):
    signed_in_client.post("/items", data={**BOOSTER_BOX, "total_cost": "", "unknown_cost": "on"})

    item_page = links(signed_in_client.get("/items").text)[BOOSTER_BOX["name"]]
    response = signed_in_client.get(item_page)

    assert table_rows(response.text) == []
    assert "Costo sconosciuto: l'app non propone prezzi." in html.unescape(response.text)


# A platform Manuel starts using one day, without a change to the code. 120 / 0,95 is 126,315…
def test_a_manual_channel_added_from_the_app_appears_in_the_prices_proposed(signed_in_client):
    cardmarket = {"name": "Cardmarket", "fee_percent": "5", "fee_fixed": "0", "multi_copy_listings": "on"}
    signed_in_client.post("/channels", data=cardmarket)
    signed_in_client.post("/items", data=BOOSTER_BOX)

    assert _prices(signed_in_client, BOOSTER_BOX["name"])["Cardmarket"] == "126,32 €"
    assert table_rows(signed_in_client.get("/channels").text)[-1] == ["Cardmarket", "5 %", "sì"]


# One setting for every channel: at 30% the net is 130, and Tilt's 2% + 0,50 makes 130,50 / 0,98 = 133,163…
def test_changing_the_target_margin_in_one_place_changes_every_price_proposed(signed_in_client):
    signed_in_client.post("/items", data=BOOSTER_BOX)

    signed_in_client.post("/target-margin", data={"target_margin": "30"})

    prices = _prices(signed_in_client, BOOSTER_BOX["name"])
    assert prices == {"Vinted": "130,00 €", "Tilt": "133,17 €", "eBay": "130,00 €"}


# At 100% no price would leave anything. The page comes back with the reason, and the rule stays as it was.
@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"fee_percent": "100"}, "La commissione va da 0 a 99,99 %."),
        (
            {"fee_percent": "dieci"},
            "Scrivi la commissione in percentuale, con al massimo due decimali: per esempio 12,9.",
        ),
        ({"fee_fixed": "0,505"}, "Scrivi la parte fissa in euro, con al massimo due decimali: per esempio 0,35."),
    ],
)
def test_a_fee_that_cannot_be_saved_is_refused_with_its_reason(signed_in_client, fields, reason):
    tilt = links(signed_in_client.get("/channels").text)["Tilt"]

    response = signed_in_client.post(tilt, data={"fee_percent": "10", "fee_fixed": "0", **fields})

    assert response.status_code == 422
    assert reason in html.unescape(response.text)
    assert ["Tilt", "2 % + 0,50 €", "sì"] in table_rows(signed_in_client.get("/channels").text)


# Two channels with one name could not be told apart in the prices, nor later in the listings.
@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"name": " "}, "Scrivi il nome del canale."),
        ({"name": "Vinted"}, "Il canale Vinted c'è già."),
        ({"fee_percent": "100"}, "La commissione va da 0 a 99,99 %."),
    ],
)
def test_a_new_channel_that_cannot_be_saved_is_refused_with_its_reason(signed_in_client, fields, reason):
    cardmarket = {"name": "Cardmarket", "fee_percent": "5", "fee_fixed": "0", **fields}

    response = signed_in_client.post("/channels", data=cardmarket)

    assert response.status_code == 422
    assert reason in html.unescape(response.text)
    assert len(table_rows(signed_in_client.get("/channels").text)) == 3


@pytest.mark.parametrize("target_margin", ["venti", "-5", "1000"])
def test_a_target_margin_that_is_not_a_percentage_is_refused_and_the_prices_stay(signed_in_client, target_margin):
    signed_in_client.post("/items", data=BOOSTER_BOX)

    response = signed_in_client.post("/target-margin", data={"target_margin": target_margin})

    assert response.status_code == 422
    reason = "Scrivi l'obiettivo in percentuale, da 0 a 999,99, con al massimo due decimali: per esempio 20."
    assert reason in html.unescape(response.text)
    assert _prices(signed_in_client, BOOSTER_BOX["name"])["Vinted"] == "120,00 €"


def _prices(client, item_name: str) -> dict[str, str]:
    """The price proposed on each channel, as the item's page shows it."""
    item_page = links(client.get("/items").text)[item_name]
    return dict(table_rows(client.get(item_page).text))
