"""Telegram message/command handlers. Each update gets its own short-lived
SQLite connection (cheap to open; keeps connection state simple to reason
about across concurrently-interleaved async handlers for different chats --
domain-layer transactions never span an `await`, so this is safe).

update_id is deduped before any work happens: a Telegram-redelivered update
is a silent no-op here. This is the outer idempotency layer from the plan;
the inner layer is the per-tool idempotency key derived in agent/tool_registry.py."""

import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

import config
from agent.session_manager import SessionManager
from db.connection import get_connection

logger = logging.getLogger(__name__)

_manager: SessionManager | None = None


def set_session_manager(manager: SessionManager) -> None:
    global _manager
    _manager = manager


def _already_processed(conn, update_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM telegram_processed_updates WHERE update_id = ?", (update_id,)
    ).fetchone() is not None


def _mark_processed(conn, update_id: int, chat_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO telegram_processed_updates (update_id, chat_id) VALUES (?, ?)",
        (update_id, chat_id),
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    if not text:
        return

    logger.info("chat_id=%s update_id=%s you> %s", chat_id, update.update_id, text)

    conn = get_connection(config.DB_PATH)
    reply = None
    try:
        if _already_processed(conn, update.update_id):
            logger.info("Skipping already-processed update_id=%s", update.update_id)
            return
        _mark_processed(conn, update.update_id, chat_id)

        await update.message.chat.send_action(ChatAction.TYPING)
        try:
            reply = await _manager.handle_message(conn, chat_id, text)
        except Exception:
            logger.exception("Error handling message for chat_id=%s", chat_id)
            reply = "Sorry, something went wrong on my end -- please try that again."
    finally:
        conn.close()

    logger.info("chat_id=%s bot> %s", chat_id, reply)
    if reply:
        await update.message.reply_text(reply)


async def on_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    conn = get_connection(config.DB_PATH)
    try:
        _manager.start_new_chat(conn, chat_id)
    finally:
        conn.close()
    await update.message.reply_text(
        "Started a fresh chat -- conversation history is cleared, but your shop preferences are remembered."
    )


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hi! I'm your kirana store ops assistant. Tell me what's happening in plain language, e.g.:\n"
        "• \"50 packets of Maggi came in, cost 12, MRP 14\"\n"
        "• \"make a bill: 2kg sugar, 1 atta, UPI\"\n"
        "• \"what's Ramesh's balance?\"\n"
        "• \"today's sales?\"\n\n"
        "Send /new to start a fresh conversation (your shop preferences carry over)."
    )
