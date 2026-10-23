"""Items, the games they belong to, and their stock: lots and the movements of their copies.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Data, not a list in the code: Manuel adds a game from the app.
    games = op.create_table(
        "games",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
    )
    op.bulk_insert(games, [{"name": name} for name in ("Pokémon", "One Piece", "Magic", "Yu-Gi-Oh")])

    op.create_table(
        "items",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("game_id", sa.Integer, sa.ForeignKey("games.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("language", sa.Text, nullable=False),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("location", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Euro cents in an integer: an amount is exact, never a float. NULL is a cost not known, which is not zero.
    op.create_table(
        "stock_lots",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("unit_cost_cents", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("unit_cost_cents >= 1", name="known_cost_at_least_one_cent"),
    )

    # The available quantity is the sum of the changes: there is no quantity column to drift from them.
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("lot_id", sa.Integer, sa.ForeignKey("stock_lots.id"), nullable=False, index=True),
        sa.Column("change", sa.Integer, nullable=False),
        sa.Column("cause", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("change <> 0", name="movement_changes_something"),
    )
