"""The channels where items are sold, with their fee rules, and the target margin the prices are made from.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Data, not a list in the code: Manuel adds a channel, and changes a fee when the platform does, from the app.
    channels = op.create_table(
        "channels",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        # A percentage of the price, exact to the hundredth. At 100% no price would leave anything.
        sa.Column("fee_percent", sa.Numeric(4, 2), nullable=False),
        sa.Column("fee_fixed_cents", sa.Integer, nullable=False),
        # Whether a listing there offers several copies, or one copy and closes when it is sold.
        sa.Column("multi_copy_listings", sa.Boolean, nullable=False),
        sa.CheckConstraint("fee_percent >= 0 AND fee_percent < 100", name="fee_percent_from_0_to_below_100"),
        sa.CheckConstraint("fee_fixed_cents >= 0", name="fee_fixed_part_not_negative"),
    )
    # Checked on 2026-10-25: Vinted charges the buyer, not the seller; Tilt keeps from 2% plus 0,50 € a sale;
    # eBay charges nothing to a private seller in Italy.
    op.bulk_insert(
        channels,
        [
            {"name": "Vinted", "fee_percent": 0, "fee_fixed_cents": 0, "multi_copy_listings": False},
            {"name": "Tilt", "fee_percent": 2, "fee_fixed_cents": 50, "multi_copy_listings": True},
            {"name": "eBay", "fee_percent": 0, "fee_fixed_cents": 0, "multi_copy_listings": True},
        ],
    )

    settings = op.create_table(
        "settings",
        # One row at most: the settings of the whole app.
        sa.Column("id", sa.Integer, sa.CheckConstraint("id = 1"), primary_key=True),
        # On the cost: 20% of a cost of 100 is 20.
        sa.Column("target_margin_percent", sa.Numeric(5, 2), nullable=False),
        sa.CheckConstraint("target_margin_percent >= 0", name="target_margin_not_negative"),
    )
    op.bulk_insert(settings, [{"id": 1, "target_margin_percent": 20}])
