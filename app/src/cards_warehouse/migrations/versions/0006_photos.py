"""The photos of the items: where each one is in the bucket, and its place in the item's order.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "item_photos",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False, index=True),
        # The photo itself lives in S3, under this key: the database restored from a backup finds it there.
        sa.Column("key", sa.Text, nullable=False, unique=True),
        # The photos of an item go in the order of their places, the first is the cover. A deleted photo
        # leaves a gap, which changes no order.
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
