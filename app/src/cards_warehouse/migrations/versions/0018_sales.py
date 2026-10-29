"""The sales: copies sold on a channel at a real price, and the movements that took them from their lots. And what a
sale leaves to do on the listings: an update where they offer more copies than are left.

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("channel_id", sa.Integer, sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        # What the buyer paid for all the copies, shipping apart.
        sa.Column("price_cents", sa.Integer, nullable=False),
        # What the channel really kept: the one of its rule, or the one Manuel corrected it to.
        sa.Column("fee_cents", sa.Integer, nullable=False),
        # The shipping left on Manuel.
        sa.Column("shipping_cents", sa.Integer, nullable=False),
        # What the copies sold cost, from the unit cost of the lots they left: NULL when one of them is not known.
        sa.Column("cost_cents", sa.Integer),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity >= 1", name="sale_of_one_copy_at_least"),
        sa.CheckConstraint("price_cents >= 1", name="sale_price_at_least_one_cent"),
        sa.CheckConstraint("fee_cents >= 0", name="sale_fee_not_negative"),
        sa.CheckConstraint("shipping_cents >= 0", name="sale_shipping_not_negative"),
    )
    # On the movements that took the copies sold, one for each lot: the cost of the sale, and what a cancellation
    # gives back to each lot.
    op.add_column("stock_movements", sa.Column("sale_id", sa.Integer, sa.ForeignKey("sales.id")))
    # On the channel, which still shows copies the listing no longer has, or offers what is gone; and off it.
    op.drop_constraint("listing_status_known", "listings")
    op.create_check_constraint(
        "listing_status_known", "listings", "status IN ('to_publish', 'active', 'to_update', 'to_close', 'closed')"
    )
    # A listing on its channel is at its link. One closed may never have got there.
    op.drop_constraint("listing_active_at_its_link", "listings")
    op.create_check_constraint(
        "listing_on_its_channel_at_its_link",
        "listings",
        "status = 'closed' OR (status = 'to_publish') = (link IS NULL)",
    )
    # A listing on Vinted closes with its copy sold, and the next copy gets a new one: of the listings of an item on a
    # channel, one at most is open.
    op.drop_constraint("one_listing_per_item_and_channel", "listings")
    op.create_index(
        "one_open_listing_per_item_and_channel",
        "listings",
        ["item_id", "channel_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'closed'"),
    )
    op.drop_constraint("action_kind_known", "pending_actions")
    op.create_check_constraint("action_kind_known", "pending_actions", "kind IN ('publish', 'update', 'close')")
