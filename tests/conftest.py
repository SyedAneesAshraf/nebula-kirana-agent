import sqlite3

import pytest

from db.connection import init_db
from db.seed import seed as seed_db


@pytest.fixture
def conn():
    """Fast in-memory DB for tests that don't need real file-level concurrency."""
    c = sqlite3.connect(":memory:", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def seeded_conn(conn):
    seed_db(conn)
    return conn
