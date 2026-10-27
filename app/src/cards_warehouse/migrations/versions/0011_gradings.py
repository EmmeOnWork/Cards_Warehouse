"""The gradings of cards: a copy sent to a grader, such as PSA, with what the grading cost and who paid it.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gradings",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        # The lot the copy left when it was sent.
        sa.Column("from_lot_id", sa.Integer, sa.ForeignKey("stock_lots.id"), nullable=False),
        sa.Column("sent_on", sa.Date, nullable=False),
        sa.Column("grader", sa.Text, nullable=False),
        sa.Column("cost_cents", sa.Integer, nullable=False),
        # Who paid the grading, all of it: NULL is Manuel, as on the shares of a purchase.
        sa.Column("paid_by_partner_id", sa.Integer, sa.ForeignKey("partners.id")),
        # NULL while the card is at the grader. Back, it is the one copy of a lot of its own, in an item graded:
        # the grade is the item's.
        sa.Column("returned_on", sa.Date),
        sa.Column("lot_id", sa.Integer, sa.ForeignKey("stock_lots.id"), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("cost_cents >= 1", name="grading_cost_at_least_one_cent"),
        sa.CheckConstraint("(returned_on IS NULL) = (lot_id IS NULL)", name="returned_on_a_day_into_a_lot"),
    )
