"""Entrypoint: wires the tool registry + agent + Telegram bot together and
runs long-polling. `python run.py`"""

import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

import config
from agent.session_manager import SessionManager
from agent.tool_registry import ToolRegistry
from db.connection import get_connection, init_db
from db.seed import seed as seed_db
from telegram_bot import handlers
from tools import analytics_tools, billing_tools, inventory_tools, khata_tools, preference_tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx (used internally by python-telegram-bot) logs full request URLs at
# INFO level, which includes the bot token as a URL path segment -- keep it
# at WARNING so the token never lands in logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def build_registry() -> ToolRegistry:
    return ToolRegistry([
        *inventory_tools.TOOLS,
        *billing_tools.TOOLS,
        *khata_tools.TOOLS,
        *analytics_tools.TOOLS,
        *preference_tools.TOOLS,
    ])


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set -- add it to .env first.")
    if not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY is not set -- add it to .env first.")

    conn = get_connection(config.DB_PATH)
    init_db(conn)
    seed_db(conn)
    conn.close()

    manager = SessionManager(build_registry())
    handlers.set_session_manager(manager)

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handlers.on_start))
    app.add_handler(CommandHandler("new", handlers.on_new))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_message))

    logger.info("Starting bot (long polling)...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
