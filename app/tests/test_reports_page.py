"""The reports page: the margin of each month against the target, for Manuel to tell whether he keeps to his rule of
20%, and the capital idle in the warehouse.

Through the app's HTTP routes, on a real PostgreSQL.
"""

import csv
from datetime import datetime, timedelta

from cards_warehouse.backups import LOCAL_TIME
from tests import test_partner_balances
from tests.pages import buttons, form_fields, links, sections, table_rows, text
from tests.test_bulk_selling import bulk_of_two_lots
from tests.test_purchase_loading import BOXES, add_partner
from tests.test_selling import MEW, sell

MONTHS = (
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
)


# Mew ex cost 100,00 and sold on eBay, which keeps nothing, at 110,00: 10,00 left, 10%. A Pikachu of 1,00 sold at
# 2,00: 1,00 left, 100%. The month made 11,00 on 101,00, 10,89%, below the target of 20%: not the 55% the mean of the
# two percentages would tell.
def test_the_margin_of_the_month_is_its_total_margin_on_the_total_cost_of_the_copies_sold(signed_in_client):
    mew = signed_in_client.post("/items", data={**MEW, "total_cost": "100"}).url.path
    sell(signed_in_client, mew, channel="eBay", price="110")
    pikachu = signed_in_client.post("/items", data={**MEW, "name": "Pikachu", "total_cost": "1"}).url.path
    sell(signed_in_client, pikachu, channel="eBay", price="2")

    page = signed_in_client.get(links(signed_in_client.get("/").text)["Conti"])

    months = sections(page.text)["Margine del mese"]
    assert table_rows(months) == [[this_month(), "2", "11,00 €", "10,89 % sotto l'obiettivo"]]
    assert "Obiettivo 20 % sul costo." in text(months)
    assert "il margine in euro delle sue vendite diviso il costo delle copie vendute" in text(months)


# A Pikachu bought long ago, at a cost not known, is the only sale of the month: it is told apart, and no margin can be
# told, but the month had a sale.
def test_a_month_of_sales_of_a_cost_not_known_alone_has_no_margin_and_tells_them_apart(signed_in_client):
    pikachu = {**MEW, "name": "Pikachu", "total_cost": "", "unknown_cost": "on"}
    sell(signed_in_client, signed_in_client.post("/items", data=pikachu).url.path, channel="eBay", price="30")

    months = sections(signed_in_client.get("/reports").text)["Margine del mese"]

    assert table_rows(months) == [[this_month(), "0 +1 a costo sconosciuto", "non calcolabile"]]


# Mew ex of 100,00 sold today at 125,00: in a period from today to today, both days in, with its 25%; not in the day
# before.
def test_the_margin_of_any_period_is_shown_from_its_first_day_to_its_last(signed_in_client):
    mew = signed_in_client.post("/items", data={**MEW, "total_cost": "100"}).url.path
    sell(signed_in_client, mew, channel="eBay", price="125")
    show, _ = buttons(signed_in_client.get("/reports").text)["Mostra"]
    today = datetime.now(LOCAL_TIME).date()
    yesterday = today - timedelta(days=1)

    of_today = signed_in_client.get(show, params={"first_day": f"{today}", "last_day": f"{today}"})
    of_yesterday = signed_in_client.get(show, params={"first_day": f"{yesterday}", "last_day": f"{yesterday}"})

    assert table_rows(sections(of_today.text)["Periodo"]) == [
        [f"{today:%d/%m/%Y} – {today:%d/%m/%Y}", "1", "25,00 €", "25 %"]
    ]
    assert table_rows(sections(of_yesterday.text)["Periodo"]) == [
        [f"{yesterday:%d/%m/%Y} – {yesterday:%d/%m/%Y}", "0", "nessuna vendita"]
    ]


# Three boxes of 104,00 €, half Luca's: one sold by Manuel on Vinted, which keeps nothing, at 60,00 €. It cost 34,67 €
# and left 25,33 €, 73,06 %; of its net, 30,00 € are Manuel's and 30,00 € Luca's. The file opens in Excel set for
# Italy: a BOM for the accents, the columns split by a semicolon, the amounts with a decimal comma.
def test_the_sales_of_a_period_download_as_a_file_for_excel_with_the_part_of_each_partner(signed_in_client):
    luca = add_partner(signed_in_client, "Luca")
    shared = {**BOXES, "partner": ["", luca], "percent": ["50", "50"], "paid": ["0", "104,00"]}
    boxes = signed_in_client.post("/items", data=shared).url.path
    test_partner_balances.sell(
        signed_in_client, boxes, channel="Vinted", collected_by="Manuel", quantity="1", price="60"
    )
    today = datetime.now(LOCAL_TIME).date()
    shown = signed_in_client.get("/reports", params={"first_day": f"{today}", "last_day": f"{today}"})

    downloaded = signed_in_client.get(links(sections(shown.text)["Periodo"])["Scarica le vendite del periodo (CSV)"])

    assert downloaded.headers["content-type"] == "text/csv; charset=utf-8"
    assert downloaded.headers["content-disposition"] == f'attachment; filename="vendite-{today}-{today}.csv"'
    assert downloaded.content.startswith("\N{BYTE ORDER MARK}".encode())
    assert csv_lines(downloaded) == [
        [
            "Data",
            "Articolo",
            "Canale",
            "Quantità",
            "Prezzo",
            "Commissione",
            "Spedizione",
            "Costo",
            "Margine €",
            "Margine %",
            "Ha incassato",
            "Parte Manuel",
            "Parte Luca",
        ],
        [
            f"{today:%d/%m/%Y}",
            "Booster box Evoluzioni a Paldea",
            "Vinted",
            "1",
            "60,00",
            "0,00",
            "0,00",
            "34,67",
            "25,33",
            "73,06",
            "Manuel",
            "30,00",
            "30,00",
        ],
    ]


# A Pikachu bought long ago by Manuel alone, at a cost not known, sold on eBay at 30,00 €: no cost nor margin can be
# told, and Luca has no part of it. Those cells are empty, and Excel sums them as nothing.
def test_in_the_file_a_cost_not_known_and_a_partner_with_no_part_are_empty_cells(signed_in_client):
    add_partner(signed_in_client, "Luca")
    pikachu = {**MEW, "name": "Pikachu", "total_cost": "", "unknown_cost": "on"}
    sell(signed_in_client, signed_in_client.post("/items", data=pikachu).url.path, channel="eBay", price="30")
    today = datetime.now(LOCAL_TIME).date()

    downloaded = signed_in_client.get("/reports/sales.csv", params={"first_day": f"{today}", "last_day": f"{today}"})

    [_, line] = csv_lines(downloaded)
    assert line == [
        f"{today:%d/%m/%Y}",
        "Pikachu",
        "eBay",
        "1",
        "30,00",
        "0,00",
        "0,00",
        "",
        "",
        "",
        "Manuel",
        "30,00",
        "",
    ]


# The days come back in the form, for Manuel to fix the one he got wrong.
def test_a_period_whose_first_day_comes_after_its_last_is_refused_with_the_days_typed(signed_in_client):
    refused = signed_in_client.get("/reports", params={"first_day": "2026-10-31", "last_day": "2026-10-01"})

    assert refused.status_code == 422
    period = sections(refused.text)["Periodo"]
    assert "Il primo giorno viene dopo l'ultimo." in text(period)
    assert form_fields(period) == {"first_day": ["2026-10-31"], "last_day": ["2026-10-01"]}
    assert table_rows(period) == []


# Of two copies of Mew ex at 50,00, one sold: 50,00 stand still. A Pikachu bought long ago, at a cost not known, told
# apart. Of 11 packs of 6,00, two opened into 11 cards of bulk: their 12,00 are in the bulk, the 9 left are sealed.
def test_the_capital_idle_is_what_the_copies_available_cost_of_each_kind_and_all_together(signed_in_client):
    mew = signed_in_client.post("/items", data={**MEW, "quantity": "2", "total_cost": "100"}).url.path
    sell(signed_in_client, mew, channel="eBay", price="60")
    signed_in_client.post("/items", data={**MEW, "name": "Pikachu", "total_cost": "", "unknown_cost": "on"})
    bulk_of_two_lots(signed_in_client)

    capital = sections(signed_in_client.get("/reports").text)["Capitale fermo"]

    assert table_rows(capital) == [
        ["Carta singola", "1 +1 a costo sconosciuto", "50,00 €"],
        ["Sealed", "9", "54,00 €"],
        ["Bulk", "11", "12,00 €"],
        ["Totale", "21 +1 a costo sconosciuto", "116,00 €"],
    ]


# The link comes only with a period shown: an address typed by hand, with the days the wrong way round, makes no file.
def test_the_file_of_a_period_whose_first_day_comes_after_its_last_is_refused(signed_in_client):
    refused = signed_in_client.get("/reports/sales.csv", params={"first_day": "2026-10-31", "last_day": "2026-10-01"})

    assert refused.status_code == 422
    assert refused.text == "Il primo giorno viene dopo l'ultimo."


def csv_lines(downloaded) -> list[list[str]]:
    """The cells of each line of a file of sales, as Excel splits them: by the semicolon, past the BOM."""
    return list(csv.reader(downloaded.content.decode("utf-8-sig").splitlines(), delimiter=";"))


def this_month() -> str:
    """The month of Italy now, as the page names it."""
    now = datetime.now(LOCAL_TIME)
    return f"{MONTHS[now.month - 1]} {now.year}"
