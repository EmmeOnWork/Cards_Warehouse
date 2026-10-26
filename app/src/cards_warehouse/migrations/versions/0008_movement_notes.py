"""A note on a stock movement: why a copy left without a sale, or how a count was found wrong.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Empty when not given, as the notes of an item: the movements already there have none.
    op.add_column("stock_movements", sa.Column("note", sa.Text, nullable=False, server_default=""))
