"""Double sales: a sale that came for copies sold already elsewhere, kept with no copies taken from the stock, and the
cancellation of a sale for that cause.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sales", sa.Column("double_sale", sa.Boolean, nullable=False, server_default=sa.false()))
    # On a sale of more copies than were left: the double sale of those that were not, in the same order.
    op.add_column("sales", sa.Column("double_part_id", sa.Integer, sa.ForeignKey("sales.id")))
    # A sale cancelled because its copies were sold already elsewhere, apart from a return and an order cancelled.
    op.drop_constraint("sale_cancellation_cause_known", "sales")
    op.create_check_constraint(
        "sale_cancellation_cause_known", "sales", "cancellation_cause IN ('return', 'order_cancelled', 'double_sale')"
    )
