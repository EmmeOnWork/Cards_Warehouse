"""The texts of the listings: how long a title can be on each channel, and the texts Manuel edited.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # In characters. Empty for a channel that sets none: the title of every listing fits the tightest of the others.
    op.add_column(
        "channels",
        sa.Column("title_limit", sa.Integer, sa.CheckConstraint("title_limit > 0", name="title_limit_positive")),
    )
    # Checked on 2026-10-27: eBay takes 80 characters, spaces included (Item.Title in its developer documentation).
    op.execute("UPDATE channels SET title_limit = 80 WHERE name = 'eBay'")

    # Only the items whose texts Manuel edited. A text he left as it was made is empty: it follows the fields.
    op.create_table(
        "listing_texts",
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), primary_key=True),
        sa.Column("title", sa.Text),
        sa.Column("description", sa.Text),
        sa.CheckConstraint("title IS NOT NULL OR description IS NOT NULL", name="one_text_edited_at_least"),
    )
