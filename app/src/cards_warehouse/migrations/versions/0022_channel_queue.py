"""The queue of the operations a channel with an API did not answer, which the worker asks again.

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One operation at most waiting on a listing: a new one replaces it, so only the last one asked is ever sent.
    op.create_table(
        "queued_operations",
        sa.Column("listing_id", sa.Integer, sa.ForeignKey("listings.id"), primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        # How many times the channel was asked, and did not answer.
        sa.Column("tries", sa.Integer, nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('update', 'close')", name="queued_operation_kind"),
    )
