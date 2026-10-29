"""The daily check: the thresholds it judges by, among the settings of the app, and what it found each time.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # In whole days, which Manuel changes from the app: an action left longer than this is forgotten.
    op.add_column(
        "settings",
        sa.Column(
            "stale_action_days",
            sa.Integer,
            sa.CheckConstraint("stale_action_days >= 1", name="stale_action_days_at_least_one"),
            nullable=False,
            server_default="3",
        ),
    )
    # Likewise for an item with no sale: its price is to review.
    op.add_column(
        "settings",
        sa.Column(
            "unsold_item_days",
            sa.Integer,
            sa.CheckConstraint("unsold_item_days >= 1", name="unsold_item_days_at_least_one"),
            nullable=False,
            server_default="60",
        ),
    )
    # The app shows the last one. What it found is kept as it was then, names included: a snapshot, not a link to
    # rows that change after it.
    op.create_table(
        "daily_checks",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", postgresql.JSONB, nullable=False),
    )
