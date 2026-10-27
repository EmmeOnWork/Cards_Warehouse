"""The link between the two sides of an opening: the movements of what came out of a copy opened, such as the packs
of a box, point to the movement that took that copy from its lot.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL on every other movement, the copy opened included: it is the one pointed to.
    op.add_column(
        "stock_movements", sa.Column("opening_id", sa.Integer, sa.ForeignKey("stock_movements.id"), index=True)
    )
