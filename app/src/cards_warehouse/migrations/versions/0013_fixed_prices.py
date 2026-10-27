"""The price Manuel fixes on an item after his market research, in place of the one made from the target margin,
and the reference price he based it on.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Empty when not fixed: the price on each channel is then made from the cost and the target margin.
    op.add_column(
        "items",
        sa.Column(
            "fixed_price_cents",
            sa.Integer,
            sa.CheckConstraint("fixed_price_cents >= 1", name="fixed_price_at_least_one_cent"),
        ),
    )
    # One reference at a time, a new one in place of the old: the price found, the day, and where.
    op.add_column(
        "items",
        sa.Column(
            "reference_price_cents",
            sa.Integer,
            sa.CheckConstraint("reference_price_cents >= 1", name="reference_price_at_least_one_cent"),
        ),
    )
    op.add_column("items", sa.Column("reference_price_on", sa.Date))
    op.add_column("items", sa.Column("reference_price_source", sa.Text))
    op.create_check_constraint(
        "reference_price_with_its_date_and_source",
        "items",
        "num_nulls(reference_price_cents, reference_price_on, reference_price_source) IN (0, 3)",
    )
