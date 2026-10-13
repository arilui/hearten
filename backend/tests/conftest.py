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
        pytest.skip("Postgres isn't reachable. Start it with: docker compose up -d db")
    return engine
