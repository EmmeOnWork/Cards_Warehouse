"""The bulk: the cards of a game and a language not worth a listing, kept together and counted roughly. Its lots
have no unit cost, since a cent does not divide among their cards: their cost moves with their movements.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The cost that came or went with the cards, on the movements of a lot of the bulk: its cost is their sum, as its
    # quantity is the sum of their changes. NULL on every other movement, and on the bulk of a cost not known.
    op.add_column("stock_movements", sa.Column("cost_cents", sa.Integer))
    # One bulk for each game and language: every opening adds a lot to it.
    op.create_index(
        "one_bulk_per_game_and_language",
        "items",
        ["game_id", "language"],
        unique=True,
        postgresql_where=sa.text("kind = 'bulk'"),
    )
