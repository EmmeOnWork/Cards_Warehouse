"""Who took the money of a sale: Manuel, or a partner who sold from their own account. The balance with each partner
follows it.

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL is Manuel, as on the shares of a purchase and on who paid a grading.
    op.add_column("sales", sa.Column("collected_by_partner_id", sa.Integer, sa.ForeignKey("partners.id")))
