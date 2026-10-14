"""Food source (FNDDS or SR Legacy) and recipe usage counts.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("food", sa.Column("source", sa.String(16), nullable=False,
                                    server_default="fndds"))
    op.add_column("food", sa.Column("recipe_uses", sa.Integer(), nullable=False,
                                    server_default="0"))
    op.create_check_constraint("food_source", "food", "source IN ('fndds', 'sr_legacy')")


def downgrade() -> None:
    op.drop_constraint("food_source", "food", type_="check")
    op.drop_column("food", "recipe_uses")
    op.drop_column("food", "source")
