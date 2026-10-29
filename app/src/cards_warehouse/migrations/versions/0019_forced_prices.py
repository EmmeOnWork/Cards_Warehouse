"""The prices forced on one channel, such as for a promotion there, and one action at most left on a listing.

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Over the price fixed on the item and the one made from the target, on that channel only. Taken away by deleting
    # its row.
    op.create_table(
        "forced_prices",
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), primary_key=True),
        sa.Column("channel_id", sa.Integer, sa.ForeignKey("channels.id"), primary_key=True),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.CheckConstraint("price_cents >= 1", name="forced_price_at_least_one_cent"),
    )
    # A change before Manuel did the action left on a listing changes that action: he does only what is left.
    op.create_index(
        "one_action_left_per_listing",
        "pending_actions",
        ["listing_id"],
        unique=True,
        postgresql_where=sa.text("done_at IS NULL"),
    )
