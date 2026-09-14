"""Per-chat conversation state: loads/persists agent_messages scoped by
(chat_id, generation), and handles the /new reset. Business memory
(preferences) is untouched by any of this -- it lives in its own table and
is re-fetched fresh into the system prompt every turn regardless of
generation, which is what makes it survive a /new."""

import json
import sqlite3

from agent.gemini_client import GeminiAgent
from agent.system_prompt import build_system_prompt
from agent.tool_registry import ToolRegistry


class SessionManager:
    def __init__(self, registry: ToolRegistry):
        self._agent = GeminiAgent(registry)

    def _get_generation(self, conn: sqlite3.Connection, chat_id: int) -> int:
        row = conn.execute("SELECT generation FROM agent_sessions WHERE chat_id = ?", (chat_id,)).fetchone()
        if row:
            return row["generation"]
        conn.execute("INSERT INTO agent_sessions (chat_id, generation) VALUES (?, 1)", (chat_id,))
        return 1

    def start_new_chat(self, conn: sqlite3.Connection, chat_id: int) -> None:
        generation = self._get_generation(conn, chat_id)
        conn.execute(
            "UPDATE agent_sessions SET generation = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
            "WHERE chat_id = ?",
            (generation + 1, chat_id),
        )

    def _load_history(self, conn: sqlite3.Connection, chat_id: int, generation: int) -> list[dict]:
        rows = conn.execute(
            "SELECT role, parts_json FROM agent_messages WHERE chat_id = ? AND generation = ? ORDER BY id",
            (chat_id, generation),
        ).fetchall()
        return [{"role": r["role"], "parts": json.loads(r["parts_json"])} for r in rows]

    def _persist(self, conn: sqlite3.Connection, chat_id: int, generation: int, entry: dict) -> None:
        conn.execute(
            "INSERT INTO agent_messages (chat_id, generation, role, parts_json) VALUES (?, ?, ?, ?)",
            (chat_id, generation, entry["role"], json.dumps(entry["parts"])),
        )

    async def handle_message(self, conn: sqlite3.Connection, chat_id: int, user_text: str) -> str:
        generation = self._get_generation(conn, chat_id)
        history = self._load_history(conn, chat_id, generation)
        system_prompt = build_system_prompt(conn)

        reply_text, new_entries = await self._agent.run_turn(conn, chat_id, system_prompt, history, user_text)

        for entry in new_entries:
            self._persist(conn, chat_id, generation, entry)

        conn.execute(
            "UPDATE agent_sessions SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE chat_id = ?",
            (chat_id,),
        )
        return reply_text
