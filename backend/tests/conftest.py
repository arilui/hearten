import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db import get_engine


@pytest.fixture(scope="session")
def db_engine():
    """The configured database, or a skip with instructions if it isn't running."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        # CI sets REQUIRE_DB, because there a skipped database test would hide a failure.
        if os.getenv("REQUIRE_DB") == "1":
            raise
        pytest.skip("Postgres isn't reachable. Check DATABASE_URL in your .env file.")
    return engine
