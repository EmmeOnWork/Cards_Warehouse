"""The live inventories: the items Manuel shows in a live on Tilt. And the presets he saves them as, to start the
next live from.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_inventories",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # The items, not their copies: how many there are is the stock's, when the inventory is shown.
    # In the order they were added, which the id keeps.
    op.create_table(
        "live_inventory_items",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("inventory_id", sa.Integer, sa.ForeignKey("live_inventories.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        # An item is shown once in a live.
        sa.UniqueConstraint("inventory_id", "item_id"),
    )

    # A copy of an inventory's items, not a link to it: changing either leaves the other as it is.
    op.create_table(
        "live_presets",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        # Two presets with one name could not be told apart when starting a live.
        sa.Column("name", sa.Text, nullable=False, unique=True),
    )
    op.create_table(
        "live_preset_items",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("preset_id", sa.Integer, sa.ForeignKey("live_presets.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.UniqueConstraint("preset_id", "item_id"),
    )
