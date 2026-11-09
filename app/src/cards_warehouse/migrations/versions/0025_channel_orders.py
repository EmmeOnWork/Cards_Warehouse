"""The sales the app read from a channel's orders, such as eBay's: each from the line of an order it came from. And how
the reads of the orders go.

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The channel's own of the line, which it never gives to another: NULL on a sale Manuel recorded.
    op.add_column("sales", sa.Column("order_line", sa.Text))
    # An order read again is the same sale: one sale at most for each line. A sale of more copies than were left is
    # two, both with the line: it counts once, by its double part.
    op.create_index(
        "one_sale_per_order_line",
        "sales",
        ["channel_id", "order_line"],
        unique=True,
        postgresql_where=sa.text("order_line IS NOT NULL AND double_part_id IS NULL"),
    )
    # The reads of each channel's orders.
    op.create_table(
        "order_reads",
        sa.Column("channel_id", sa.Integer, sa.ForeignKey("channels.id"), primary_key=True),
        # When the last one that worked started: the next asks for the orders made since then. NULL before the first.
        sa.Column("read_at", sa.DateTime(timezone=True)),
        # Since when they fail, and why the last one did: NULL once one works.
        sa.Column("failing_since", sa.DateTime(timezone=True)),
        sa.Column("problem", sa.Text),
    )
