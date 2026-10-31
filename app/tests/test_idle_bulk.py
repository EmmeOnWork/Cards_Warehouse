"""The capital idle in the bulk: what the cards of each bulk cost, and since when its oldest lot stands, for Manuel to
tell when it is worth selling it off.

Through the app's HTTP routes, on a real PostgreSQL, with the app's clock moved on.
"""

from datetime import UTC, datetime, timedelta

from cards_warehouse.backups import LOCAL_TIME
from tests.pages import links, table_rows
from tests.test_bulk_selling import bulk_of_two_lots, sell
from tests.test_cards_opening import OWN_PACK
from tests.test_daily_check_page import signed_in


# The Italian bulk of two lots, 12,00 €, after 5 cards sold from the oldest: 6 cards and 4,00 € stand still. The
# Japanese one, a pack of 6,00 € opened into 3 cards, all of them. 17 days on, the page says so, for each.
def test_the_capital_idle_in_each_bulk_shows_since_when_its_oldest_lot_stands(database):
    today = signed_in(now=datetime.now(UTC))
    italian = bulk_of_two_lots(today)
    sell(today, italian, channel="Vinted", quantity="5", price="10")
    japanese_pack = today.post("/items", data={**OWN_PACK, "language": "ja"}).url.path
    opening = links(today.get(japanese_pack).text)["Apri in carte"]
    today.post(opening, data={"lot": "1", "copies": "1", "bulk_cards": "3", "bulk_value": "1,00"})
    came = f"{datetime.now(LOCAL_TIME):%d/%m/%Y}"
    later = signed_in(now=datetime.now(UTC) + timedelta(days=17))

    page = later.get(links(later.get("/").text)["Bulk"])

    assert table_rows(page.text) == [
        ["Bulk Pokémon Italiano", "6", "4,00 €", came, "17"],
        ["Bulk Pokémon Giapponese", "3", "6,00 €", came, "17"],
    ]
    assert links(page.text)["Bulk Pokémon Italiano"] == italian
