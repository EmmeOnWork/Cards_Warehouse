"""The copies sold in a live, entered at its end row by row, and the sale on Tilt each row became once confirmed.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Copies sold at different prices, as at an auction, are on rows of their own. In the order they were entered,
    # which the id keeps.
    op.create_table(
        "live_sales",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("inventory_id", sa.Integer, sa.ForeignKey("live_inventories.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        # What the buyer paid for each copy: in a live, each copy is a Tilt order of its own.
        sa.Column("unit_price_cents", sa.Integer, nullable=False),
        # NULL until the row is confirmed: a row entered and not yet confirmed is kept, to finish the entry later.
        # Once set, the row is never sold again.
        sa.Column("sale_id", sa.Integer, sa.ForeignKey("sales.id"), unique=True),
        sa.CheckConstraint("quantity >= 1", name="live_sale_of_one_copy_at_least"),
        sa.CheckConstraint("unit_price_cents >= 1", name="live_sale_price_at_least_one_cent"),
    )
