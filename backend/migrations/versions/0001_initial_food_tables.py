"""Initial food, nutrient, portion, price and tag tables.

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "food",
        sa.Column("food_code", sa.Integer(), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
    )
    op.create_table(
        "nutrient",
        sa.Column("nutrient_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
    )
    op.create_table(
        "food_nutrient",
        sa.Column("food_code", sa.Integer(), sa.ForeignKey("food.food_code"), primary_key=True),
        sa.Column("nutrient_id", sa.Integer(), sa.ForeignKey("nutrient.nutrient_id"),
                  primary_key=True),
        sa.Column("amount_per_100g", sa.Numeric(12, 4), nullable=False),
    )
    op.create_table(
        "food_portion",
        sa.Column("portion_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("food_code", sa.Integer(), sa.ForeignKey("food.food_code"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("gram_weight", sa.Numeric(10, 3), nullable=False),
    )
    op.create_index("ix_food_portion_food_code", "food_portion", ["food_code"])
    op.create_table(
        "food_price",
        sa.Column("food_code", sa.Integer(), sa.ForeignKey("food.food_code"), primary_key=True),
        sa.Column("currency", sa.String(3), primary_key=True),
        sa.Column("amount_minor_per_100g", sa.Numeric(12, 4), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("price_period", sa.String(32), nullable=False),
    )
    op.create_table(
        "food_tag",
        sa.Column("food_code", sa.Integer(), sa.ForeignKey("food.food_code"), primary_key=True),
        sa.Column("tag", sa.String(64), primary_key=True),
        sa.Column("set_by", sa.String(16), nullable=False),
        sa.CheckConstraint("set_by IN ('rule', 'review')", name="food_tag_set_by"),
    )


def downgrade() -> None:
    op.drop_table("food_tag")
    op.drop_table("food_price")
    op.drop_index("ix_food_portion_food_code", table_name="food_portion")
    op.drop_table("food_portion")
    op.drop_table("food_nutrient")
    op.drop_table("nutrient")
    op.drop_table("food")
