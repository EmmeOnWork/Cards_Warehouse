"""A sale undone, for a return or an order cancelled: it stays, known as cancelled, with why and when.

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL while the sale stands.
    op.add_column("sales", sa.Column("cancellation_cause", sa.Text))
    op.add_column("sales", sa.Column("cancellation_note", sa.Text, nullable=False, server_default=""))
    op.add_column("sales", sa.Column("cancelled_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "sale_cancellation_cause_known", "sales", "cancellation_cause IN ('return', 'order_cancelled')"
    )
    op.create_check_constraint(
        "sale_cancelled_with_a_cause", "sales", "(cancellation_cause IS NULL) = (cancelled_at IS NULL)"
    )
