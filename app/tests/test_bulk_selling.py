"""Selling the bulk, all of it or a part, by weight or by lot, as Manuel does it from the phone: a sale like any other,
of a number of cards counted roughly, which take their cost from the bulk's oldest lots.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import pytest

from tests.pages import buttons, checkboxes, links, sections, select_options, table_rows, text
from tests.test_cards_opening import OWN_PACK, SHARED_PACKS, add_partner
from tests.test_selling import sell


# A pack of 6,00 €, half Luca's, opened all into 2 cards of bulk; then a pack of 6,00 €, all Manuel's, into 9. Five
# cards sold on Vinted for 10,00 € take the 2 of the first lot, the oldest, with its 6,00 €, and 3 of the 9 of the
# second, with a third of its 6,00 €: they cost 8,00 €, and leave 2,00 €, 25 %. The bulk keeps 6 cards and 4,00 €.
def test_a_sale_of_part_of_the_bulk_takes_its_cards_and_their_cost_from_the_oldest_lots(signed_in_client):
    bulk = bulk_of_two_lots(signed_in_client)

    sold = sell(signed_in_client, bulk, channel="Vinted", quantity="5", price="10", note="A peso: 50 g")

    assert text(sections(sold.text)["Vendita"]) == (
        "Vendita Canale Vinted Carte 5 Prezzo 10,00 € Commissione 0,00 € Spedizione 0,00 € Costo 8,00 € "
        "Margine 2,00 € · 25 % Nota A peso: 50 g"
    )
    bulk_page = signed_in_client.get(bulk).text
    assert "Carte 6 Costo 4,00 €" in text(bulk_page)
    assert table_rows(bulk_page) == [["2", "6", "4,00 €", "Manuel 100 %"]]
    history = signed_in_client.get(links(bulk_page)["Movimenti e rettifiche"]).text
    assert [row[1:] for row in table_rows(history)][2:] == [["Vendita", "1", "-2"], ["Vendita", "2", "-3"]]


# The 11 cards of the bulk sold in one go, with «Tutto il bulk»: the 15 Manuel counted by eye do not matter. The sale
# takes both lots, with their 12,00 €, and the bulk is left with no cards and no cost. The lot is never chosen.
def test_all_the_bulk_sold_in_one_go_leaves_it_with_no_cards_and_no_cost(signed_in_client):
    bulk = bulk_of_two_lots(signed_in_client)
    form = signed_in_client.get(links(signed_in_client.get(bulk).text)["Vendi"]).text
    assert "Carte nel bulk: 11" in text(form)
    assert select_options(form, "lot") == []

    sold = sell(signed_in_client, bulk, channel="Vinted", quantity="15", everything="yes", price="15")

    assert "Carte 11 Prezzo 15,00 € Commissione 0,00 € Spedizione 0,00 € Costo 12,00 €" in text(sold.text)
    bulk_page = signed_in_client.get(bulk).text
    assert "Carte 0 Costo 0,00 €" in text(bulk_page)
    assert "Vendi" not in links(bulk_page)


# Sent twice, as with a double tap: the first sale took every card, and the second has none to sell. More cards than
# the bulk has are refused, as copies are, with what it has.
@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"quantity": "1", "everything": "yes"}, "Il bulk non ha più carte da vendere."),
        ({"quantity": "15"}, "Carte nel bulk: 0. Non puoi venderne 15."),
    ],
)
def test_a_bulk_with_no_cards_left_refuses_a_sale(signed_in_client, fields, reason):
    bulk = bulk_of_two_lots(signed_in_client)
    form = signed_in_client.get(links(signed_in_client.get(bulk).text)["Vendi"])
    record, _ = buttons(form.text)["Registra la vendita"]
    vinted = checkboxes(form.text, "channel")["Vinted"]
    signed_in_client.post(record, data={"channel": vinted, "quantity": "11", "price": "15"})

    response = signed_in_client.post(record, data={"channel": vinted, "price": "15", **fields})

    assert response.status_code == 422
    assert reason in text(response.text)


def bulk_of_two_lots(client) -> str:
    """The page of the bulk, made of two lots: a pack of 6,00 €, half Luca's, opened all into 2 cards of bulk, and
    a pack of 6,00 €, all Manuel's, into 9."""
    luca = add_partner(client, "Luca")
    shared = {**SHARED_PACKS, "partner": ["", luca], "percent": ["50", "50"], "paid": ["30,00", "30,00"]}
    bulk = ""
    for packs, bulk_cards in ((shared, "2"), (OWN_PACK, "9")):
        packs_page = client.post("/items", data=packs).url.path
        opening = links(client.get(packs_page).text)["Apri in carte"]
        all_bulk = {"lot": "1", "copies": "1", "bulk_cards": bulk_cards, "bulk_value": "1,00"}
        bulk = links(client.post(opening, data=all_bulk).text)["Bulk Pokémon Italiano"]
    return bulk
