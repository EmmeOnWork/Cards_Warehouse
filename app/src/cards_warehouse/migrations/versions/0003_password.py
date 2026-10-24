"""The password set from the app, which takes the place of the hash in Infisical.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_password",
        # One row at most: the app has one user.
        sa.Column("id", sa.Integer, sa.CheckConstraint("id = 1"), primary_key=True),
        sa.Column("hash", sa.Text, nullable=False),
        # The fingerprint of the hash in Infisical when this one was set: a new hash there, put
        # with make password-hash after this, wins. So a password forgotten can still be reset from the PC.
        sa.Column("replaces", sa.Text, nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
