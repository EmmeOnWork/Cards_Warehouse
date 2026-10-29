"""eBay through its API: the channels that publish by themselves, and why a listing could not be published.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Off for every channel: one is switched from its page, when the app has an adapter for its API.
    op.add_column(
        "channels",
        sa.Column("publishes_through_api", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    # What the channel answered the last time it refused the listing, for Manuel. Empty once it is published.
    op.add_column("listings", sa.Column("problem", sa.Text))
