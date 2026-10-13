"""The migrations must create exactly the tables the models describe."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

import app.models  # noqa: F401
from app.db import Base

EXPECTED_TABLES = {"food", "nutrient", "food_nutrient", "food_portion", "food_price", "food_tag"}


def test_migrations_create_all_tables(db_engine):
    tables = set(inspect(db_engine).get_table_names())
    assert EXPECTED_TABLES <= tables


def test_models_match_migrations(db_engine):
    with db_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Models and migrations differ; add a migration: {diff}"
