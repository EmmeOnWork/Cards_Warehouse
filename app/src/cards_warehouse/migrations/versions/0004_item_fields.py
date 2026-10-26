"""The fields of each kind of item: set, number, variant, condition and grading for a single card, product type and set
for a sealed.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Free text is empty when not given, as notes and location. The set is one column for cards and sealed:
    # the box and the cards that come out of it share it, and its suggestions.
    for name in ("set_name", "card_number", "variant", "product_type"):
        op.add_column("items", sa.Column(name, sa.Text, nullable=False, server_default=""))
    # A choice from a list, NULL when the item is not a card or the card is graded. Cards loaded before this
    # migration have none: no constraint asks a card for one.
    op.add_column("items", sa.Column("condition", sa.Text))
    op.add_column("items", sa.Column("grader", sa.Text))
    op.add_column("items", sa.Column("grade", sa.Numeric(3, 1)))
    op.create_check_constraint("graded_with_grader_and_grade", "items", "(grader IS NULL) = (grade IS NULL)")
    op.create_check_constraint(
        "grade_from_1_to_10_in_half_points", "items", "grade BETWEEN 1 AND 10 AND grade * 2 = trunc(grade * 2)"
    )
