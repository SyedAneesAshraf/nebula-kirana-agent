"""Terminal REPL for exercising the full agent loop (including document
generation) against the real Gemini API without needing Telegram running.
Generated files are printed as local paths instead of being sent to a chat.
Run: python -m scripts.repl [chat_id]"""

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")

import config
from agent.session_manager import SessionManager
from agent.tool_registry import ToolRegistry
from db.connection import get_connection, init_db
from db.seed import seed as seed_db
from tools import analytics_tools, billing_tools, document_tools, inventory_tools, khata_tools, preference_tools


async def _print_document(chat_id: int, path: str, caption: str) -> None:
    print(f"[document] {caption} -> {path}")


def build_registry() -> ToolRegistry:
    specs = [
        *inventory_tools.TOOLS,
        *billing_tools.TOOLS,
        *khata_tools.TOOLS,
        *analytics_tools.TOOLS,
        *preference_tools.TOOLS,
        *document_tools.build_tools(_print_document),
    ]
    return ToolRegistry(specs)


async def main() -> None:
    if not config.GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set -- add it to .env first.")
        return

    chat_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    conn = get_connection(config.DB_PATH)
    init_db(conn)
    seed_db(conn)

    manager = SessionManager(build_registry())

    print(f"Chat REPL -- chat_id={chat_id}. Type /new to reset, /exit to quit.")
    while True:
        try:
            user_text = input("you> ").strip()
        except EOFError:
            break
        if not user_text:
            continue
        if user_text == "/exit":
            break
        if user_text == "/new":
            manager.start_new_chat(conn, chat_id)
            print("(new chat started -- transcript cleared, preferences unaffected)")
            continue
        reply = await manager.handle_message(conn, chat_id, user_text)
        print(f"bot> {reply}")


if __name__ == "__main__":
    asyncio.run(main())
