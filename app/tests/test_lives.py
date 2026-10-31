"""The lives module: the copies sold in a live, entered row by row, become sales on Tilt.

On a real PostgreSQL, through the module's functions, with every channel a manual one.
"""

from decimal import Decimal

from cards_warehouse import channels, exposure, items, lives, manual_channels, sales, stock
from cards_warehouse.items import Item, Kind, Sealed
from cards_warehouse.manual_channels import ActionKind
from cards_warehouse.pricing import Margin


# Three copies at 10,00 each, sold in three Tilt orders: 3 × (0,20 + 0,50) = 2,10 kept, not the 1,10 of one order of
# 30,00.
def test_a_row_confirmed_is_a_sale_on_tilt_of_its_copies_with_tilts_fee_on_each_copy(connection):
    pack = a_pack(connection, copies=3, unit_cost_cents=500)
    inventory = lives.start(connection)
    lives.add(connection, inventory, pack)
    lives.sold(connection, inventory, pack, quantity=3, unit_price_cents=1000)

    (sale_id,) = lives.confirm(connection, inventory, manual_channels.MANUAL)

    sale = sales.one(connection, sale_id)
    assert (sale.channel, sale.quantity, sale.price_cents, sale.fee_cents) == ("Tilt", 3, 3000, 210)


# Two bustas at 5,00 each sold at 10,00 each, and one of a cost not known at 8,00. That busta is in the takings and in
# the fees, 2 × 0,70 + 0,66, but no margin can be told of it: the margin is of the other two, 20,00 - 1,40 - 10,00,
# and the report says one sale is left out of it.
def test_the_margin_of_a_live_leaves_out_the_sales_whose_cost_is_not_known_and_counts_them(connection):
    pack = a_pack(connection, copies=2, unit_cost_cents=500)
    not_known = a_pack(connection, copies=1, unit_cost_cents=None)
    inventory = lives.start(connection)
    lives.sold(connection, inventory, pack, quantity=2, unit_price_cents=1000)
    lives.sold(connection, inventory, not_known, quantity=1, unit_price_cents=800)
    lives.confirm(connection, inventory, manual_channels.MANUAL)

    report = lives.report(connection, inventory)

    assert (report.takings_cents, report.fees_cents, report.margin, report.cost_not_known) == (
        2800,
        206,
        Margin(860, Decimal("86")),
        1,
    )


# The last busta, sold in the live: Tilt closed its listing by itself, the others are to close, as after any sale.
def test_the_last_copy_sold_in_a_live_leaves_the_listings_on_the_other_channels_to_close(connection):
    pack = a_pack(connection, copies=1, unit_cost_cents=500)
    on_sale = [channels.named(connection, name).id for name in ("Vinted", "Tilt", "eBay")]
    exposure.put_on_sale(connection, pack, on_sale, manual_channels.MANUAL)
    for action in manual_channels.of_item(connection, pack):
        manual_channels.done(connection, action.id, link=f"https://manual.test/{action.listing.id}")
    inventory = lives.start(connection)
    lives.sold(connection, inventory, pack, quantity=1, unit_price_cents=800)

    lives.confirm(connection, inventory, manual_channels.MANUAL)

    assert [(action.kind, action.listing.channel) for action in manual_channels.of_item(connection, pack)] == [
        (ActionKind.CLOSE, "Vinted"),
        (ActionKind.CLOSE, "eBay"),
    ]


def a_pack(connection, copies: int, unit_cost_cents: int | None) -> int:
    pack = Item(kind=Kind.SEALED, game="Pokémon", name="Busta 151", language="it", details=Sealed("Busta", "151"))
    item = items.add(connection, pack)
    stock.load(connection, item, quantity=copies, unit_cost_cents=unit_cost_cents)
    return item
