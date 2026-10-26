"""Purchases, the origin of the lots: what they cost with the shipping that brought them, the partners who share
them, and what each one paid.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Data, not a list in the code: Manuel adds a partner from the app. Manuel himself is not one.
    op.create_table(
        "partners",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
    )

    op.create_table(
        "purchases",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("total_cost_cents", sa.Integer, nullable=False),
        # What the seller charged to send it: part of the cost of the copies, and zero when it was free.
        sa.Column("shipping_cents", sa.Integer, nullable=False),
        sa.Column("purchased_on", sa.Date, nullable=False),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("total_cost_cents >= 1", name="purchase_cost_at_least_one_cent"),
        sa.CheckConstraint("shipping_cents >= 0", name="shipping_not_negative"),
    )
    # One row for each person in the purchase, Manuel's with no partner. The shares add up to 100, and the
    # payments to the cost plus the shipping: the code makes sure, since a check here sees one row at a time.
    op.create_table(
        "purchase_shares",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("purchase_id", sa.Integer, sa.ForeignKey("purchases.id"), nullable=False),
        sa.Column("partner_id", sa.Integer, sa.ForeignKey("partners.id")),
        # In whole percents: 50 and 50, or 34, 33 and 33.
        sa.Column("percent", sa.Integer, nullable=False),
        sa.Column("paid_cents", sa.Integer, nullable=False),
        sa.CheckConstraint("percent BETWEEN 0 AND 100", name="share_from_0_to_100_percent"),
        sa.CheckConstraint("paid_cents >= 0", name="payment_not_negative"),
        # Manuel once, too: two rows without a partner are not distinct.
        sa.UniqueConstraint("purchase_id", "partner_id", postgresql_nulls_not_distinct=True),
    )
    # NULL for the lots loaded before purchases existed, with their cost typed by hand: they are all Manuel's.
    # A cost not known has no purchase either.
    op.add_column("stock_lots", sa.Column("purchase_id", sa.Integer, sa.ForeignKey("purchases.id"), index=True))
