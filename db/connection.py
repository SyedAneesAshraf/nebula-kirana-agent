"""SQLite connection helper: WAL mode, busy-timeout, and an explicit
BEGIN IMMEDIATE transaction context manager used by every domain module
that needs an atomic read-check-write (stock, khata, bill finalize)."""

import contextlib
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


@contextlib.contextmanager
def immediate_transaction(conn: sqlite3.Connection):
    """Acquire the write lock immediately (rather than at first write) so
    concurrent writers serialize predictably instead of racing to upgrade
    a deferred transaction.

    Reentrant: SQLite has no nested BEGIN, but domain functions compose
    (finalize_bill calls charge_to_credit for a credit-mode sale). If a
    transaction is already open, join it instead of nesting -- the
    outermost caller owns commit/rollback, so a failure anywhere still
    rolls back the whole composed operation atomically."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
