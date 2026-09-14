"""Generic idempotency-key cache used by every mutating domain function.
A repeated call with the same (tool_name, key) returns the cached result
of the original successful call instead of re-executing the mutation --
this is what makes a Telegram-redelivered 'finalize the bill' safe."""

import json
import sqlite3
from typing import Optional


def get_cached(conn: sqlite3.Connection, tool_name: str, key: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT result_json FROM idempotency_keys WHERE tool_name = ? AND key = ?",
        (tool_name, key),
    ).fetchone()
    return json.loads(row["result_json"]) if row else None


def store_cached(conn: sqlite3.Connection, tool_name: str, key: str, result: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO idempotency_keys (tool_name, key, result_json) VALUES (?, ?, ?)",
        (tool_name, key, json.dumps(result, default=str)),
    )
