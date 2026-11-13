"""The history of the sales: those of a period and of a channel, with what the period took in, for Manuel to see how
he is doing. Sales cancelled and double sales are told apart, and left out of the totals.

Through the app's HTTP routes, on a real PostgreSQL.
"""

from datetime import datetime

from cards_warehouse.backups import LOCAL_TIME
from tests.pages import buttons, choices, form_fields, links, sections, table_rows, text
from tests.test_daily_check_page import signed_in
from tests.test_sale_cancellation import _cancel
from tests.test_selling import MEW, sell


# Mew ex of 50,00 sold on Tilt at 60,00, which keeps 1,70, with 3,00 of shipping on Manuel: 5,30 left, 10,6%. Then a
# Pikachu of 1,00 sold on eBay, which keeps nothing, at 2,00: 1,00 left, 100%. The month took in 62,00.
def test_the_sales_of_this_month_are_listed_newest_first_with_the_totals_of_the_period(signed_in_client):
    mew = sell(signed_in_client, signed_in_client.post("/items", data=MEW).url.path, "Tilt", price="60", shipping="3")
    pikachu = signed_in_client.post("/items", data={**MEW, "name": "Pikachu", "total_cost": "1"}).url.path
    sell(signed_in_client, pikachu, channel="eBay", price="2")

    page = signed_in_client.get(links(signed_in_client.get("/").text)["Vendite"])

    today = f"{datetime.now(LOCAL_TIME):%d/%m/%Y}"
    listed = sections(page.text)["Elenco"]
    assert table_rows(listed) == [
        [today, "Pikachu", "eBay", "1", "2,00 €", "0,00 €", "0,00 €", "1,00 € · 100 %"],
        [today, "Mew ex", "Tilt", "1", "60,00 €", "1,70 €", "3,00 €", "5,30 € · 10,6 %"],
    ]
    assert links(listed)["Mew ex"] == mew.url.path
    assert text(sections(page.text)["Totali"]) == "Totali Incasso 62,00 € Commissioni 1,70 € Margine 6,30 €"


# The same two sales, on eBay alone: Pikachu, with totals of its own. The channel stays chosen.
def test_the_sales_of_one_channel_are_listed_with_the_totals_of_that_channel(signed_in_client):
    sell(signed_in_client, signed_in_client.post("/items", data=MEW).url.path, "Tilt", price="60", shipping="3")
    pikachu = signed_in_client.post("/items", data={**MEW, "name": "Pikachu", "total_cost": "1"}).url.path
    sell(signed_in_client, pikachu, channel="eBay", price="2")
    page = signed_in_client.get("/sales").text
    show, _ = buttons(page)["Mostra"]
    ebay = choices(page, "channel")["eBay"]

    shown = signed_in_client.get(show, params={**form_fields(page), "channel": ebay}).text

    assert [row[1:3] for row in table_rows(sections(shown)["Elenco"])] == [["Pikachu", "eBay"]]
    assert text(sections(shown)["Totali"]) == "Totali Incasso 2,00 € Commissioni 0,00 € Margine 1,00 €"
    assert form_fields(shown)["channel"] == [ebay]


# On 15 January 2027, on eBay: the shortcuts show this month, the last one, December of the year before, and this year,
# each still on eBay.
def test_the_shortcuts_show_this_month_the_last_one_and_this_year_on_the_channel_chosen(database):
    client = signed_in(datetime(2027, 1, 15, 12, tzinfo=LOCAL_TIME))
    page = client.get("/sales").text
    show, _ = buttons(page)["Mostra"]
    ebay = choices(page, "channel")["eBay"]
    on_ebay = client.get(show, params={**form_fields(page), "channel": ebay}).text

    def shown(shortcut: str) -> dict[str, list[str]]:
        return form_fields(client.get(links(on_ebay)[shortcut]).text)

    assert shown("Questo mese") == {"first_day": ["2027-01-01"], "last_day": ["2027-01-31"], "channel": [ebay]}
    assert shown("Mese scorso") == {"first_day": ["2026-12-01"], "last_day": ["2026-12-31"], "channel": [ebay]}
    assert shown("Quest'anno") == {"first_day": ["2027-01-01"], "last_day": ["2027-12-31"], "channel": [ebay]}


# Two copies of Mew ex sold on eBay at 120,00, with one left: the one there was is sold at 60,00, the other is a double
# sale. A Pikachu sold at 2,00 came back. The month took in the 60,00 of Mew ex alone, which left 10,00.
def test_sales_cancelled_and_double_sales_are_told_apart_and_left_out_of_the_totals(signed_in_client):
    mew = signed_in_client.post("/items", data=MEW).url.path
    sell(signed_in_client, mew, channel="eBay", quantity="2", price="120")
    pikachu = signed_in_client.post("/items", data={**MEW, "name": "Pikachu", "total_cost": "1"}).url.path
    _cancel(signed_in_client, sell(signed_in_client, pikachu, channel="eBay", price="2").text, cause="Reso")

    page = signed_in_client.get("/sales").text

    today = f"{datetime.now(LOCAL_TIME):%d/%m/%Y}"
    assert table_rows(sections(page)["Elenco"]) == [
        [today, "Pikachu annullata · Reso", "eBay", "1", "2,00 €", "0,00 €", "0,00 €", "1,00 € · 100 %"],
        [today, "Mew ex", "eBay", "1", "60,00 €", "0,00 €", "0,00 €", "10,00 € · 20 %"],
        [today, "Mew ex doppia vendita", "eBay", "1", "60,00 €", "0,00 €", "0,00 €", "—"],
    ]
    assert text(sections(page)["Totali"]) == "Totali Incasso 60,00 € Commissioni 0,00 € Margine 10,00 €"


# Mew ex sold at 60,00 left 10,00. A Pikachu bought long ago, at a cost not known, sold at 30,00: it took in its 30,00,
# but may have left anything, and is out of the margin, told apart.
def test_a_sale_of_a_cost_not_known_is_left_out_of_the_margin_and_counted_apart(signed_in_client):
    sell(signed_in_client, signed_in_client.post("/items", data=MEW).url.path, channel="eBay", price="60")
    pikachu = {**MEW, "name": "Pikachu", "total_cost": "", "unknown_cost": "on"}
    sell(signed_in_client, signed_in_client.post("/items", data=pikachu).url.path, channel="eBay", price="30")

    page = signed_in_client.get("/sales").text

    assert [row[-1] for row in table_rows(sections(page)["Elenco"])] == ["non calcolabile", "10,00 € · 20 %"]
    assert text(sections(page)["Totali"]) == (
        "Totali Incasso 90,00 € Commissioni 0,00 € Margine 10,00 € +1 a costo sconosciuto"
    )


# The days come back in the form, for Manuel to fix the one he got wrong. No sale is listed.
def test_a_period_whose_first_day_comes_after_its_last_is_refused_with_the_days_typed(signed_in_client):
    sell(signed_in_client, signed_in_client.post("/items", data=MEW).url.path, channel="eBay", price="60")

    refused = signed_in_client.get("/sales", params={"first_day": "2026-10-31", "last_day": "2026-10-01"})

    assert refused.status_code == 422
    assert "Il primo giorno viene dopo l'ultimo." in text(refused.text)
    assert form_fields(refused.text) == {"first_day": ["2026-10-31"], "last_day": ["2026-10-01"], "channel": [""]}
    assert table_rows(refused.text) == []
