"""The listings of the items on the channels, and the actions the manual channels leave to Manuel.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "listings",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("channel_id", sa.Integer, sa.ForeignKey("channels.id"), nullable=False),
        # To publish until it is on the channel, then active there, at its link.
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=False),
        # The copies it offers: one on a channel where a listing is one copy, such as Vinted.
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("link", sa.Text),
        sa.CheckConstraint("status IN ('to_publish', 'active')", name="listing_status_known"),
        sa.CheckConstraint("price_cents >= 1", name="listing_price_at_least_one_cent"),
        sa.CheckConstraint("quantity >= 1", name="listing_offers_one_copy_at_least"),
        sa.CheckConstraint("(status = 'active') = (link IS NOT NULL)", name="listing_active_at_its_link"),
        # Two listings of an item on one channel would offer its copies twice there.
        sa.UniqueConstraint("item_id", "channel_id", name="one_listing_per_item_and_channel"),
    )
    # What the app cannot do on a channel with no API, and asks of Manuel.
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("listing_id", sa.Integer, sa.ForeignKey("listings.id"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Empty until Manuel ticks it: then it leaves the list.
        sa.Column("done_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('publish')", name="action_kind_known"),
    )
