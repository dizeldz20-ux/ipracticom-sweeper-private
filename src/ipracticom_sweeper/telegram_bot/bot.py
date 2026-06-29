"""iPracticom Sweeper Telegram bot — entry point.

This is the live wiring: load config, build the python-telegram-bot
Application, register handlers (gated by `authorized_only`), install
an error handler, and start polling.

Run it:
    TELEGRAM_BOT_TOKEN=... \\
    ALLOWED_CHAT_IDS=8351895620 \\
    AGENT_API_URL=http://127.0.0.1:8787 \\
    AGENT_API_TOKEN=... \\
    python -m ipracticom_sweeper.telegram_bot.bot
"""
from __future__ import annotations

import logging
import sys

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from ipracticom_sweeper.telegram_bot.auth import UnauthorizedError, authorized_only
from ipracticom_sweeper.telegram_bot.config import ConfigError, load_config
from ipracticom_sweeper.telegram_bot.handlers import (
    history as history_handler,
    problems as problems_handler,
    security as security_handler,
    start as start_handler,
    status as status_handler,
)
from ipracticom_sweeper.telegram_bot.services.agent_client import AgentClient

log = logging.getLogger(__name__)


async def _send_result(target, result: dict) -> None:
    """Send a handler result dict via the right Telegram method.

    `target` is either `update.message` or `update.callback_query`. We
    edit the message if it's a callback (so the inline keyboard updates
    in place) or send a new message if it's a command.
    """
    text = result.get("text", "")
    reply_markup = result.get("reply_markup")
    parse_mode = ParseMode.HTML

    cq = getattr(target, "callback_query", None)
    if cq is not None:
        # callback_query path: answer the toast + edit the message
        await cq.answer()
        try:
            await cq.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:  # message not modified, etc.
            pass
        return

    msg = getattr(target, "message", None) or target
    if hasattr(msg, "reply_text"):
        await msg.reply_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    elif hasattr(msg, "edit_message_text"):
        await msg.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)


def _on_command_sync(handler):
    """Wrap a handler as a CommandHandler callback (sync, returns the wrapped function)."""
    @authorized_only
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        result = await handler(update, context)
        await _send_result(update, result)
    return wrapped


def _on_callback_sync(handler):
    """Wrap a handler as a CallbackQueryHandler callback."""
    @authorized_only
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        result = await handler(update, context)
        await _send_result(update, result)
    return wrapped


async def _on_unauthorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Silent rejection: do not respond to unauthorized chat_ids.

    Per the public `telegram-bot-builder` skill's anti-pattern guidance:
    do not echo, do not error out, do not waste API calls.
    """
    chat = getattr(update, "effective_chat", None)
    cid = getattr(chat, "id", None)
    log.warning("unauthorized chat_id=%s", cid)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler: log, do not crash the polling loop."""
    log.exception("handler error: %s", context.error)


def build_application() -> Application:
    """Construct the PTB Application with all handlers wired."""
    cfg = load_config()
    agent = AgentClient(base_url=cfg.agent_api_url, token=cfg.agent_api_token)

    app = ApplicationBuilder().token(cfg.bot_token).build()
    app.bot_data["config"] = cfg
    app.bot_data["agent"] = agent

    # --- command handlers ---
    # We need the actual wrapped function, not a coroutine. The wrappers
    # above return a function when called — so we call them eagerly.
    start_wrapped = _on_command_sync(start_handler)
    status_wrapped = _on_callback_sync(status_handler)
    problems_wrapped = _on_callback_sync(problems_handler)
    history_wrapped = _on_callback_sync(history_handler)
    security_wrapped = _on_callback_sync(security_handler)
    main_wrapped = _on_callback_sync(start_handler)

    app.add_handler(CommandHandler("start", start_wrapped))
    app.add_handler(CommandHandler("help", start_wrapped))

    # --- callback query handlers (inline keyboard) ---
    # Map callback prefixes to handlers. The order matters: more specific first.
    app.add_handler(CallbackQueryHandler(history_wrapped, pattern=r"^hist:"))
    app.add_handler(CallbackQueryHandler(status_wrapped, pattern=r"^menu:status$"))
    app.add_handler(CallbackQueryHandler(problems_wrapped, pattern=r"^menu:problems$"))
    app.add_handler(CallbackQueryHandler(security_wrapped, pattern=r"^menu:security$"))
    app.add_handler(CallbackQueryHandler(main_wrapped, pattern=r"^menu:main$"))
    # Fallback: any other callback is unauthorized or unknown → no-op
    app.add_handler(CallbackQueryHandler(_on_unauthorized))

    # --- error handler ---
    app.add_error_handler(_on_error)

    return app


def main() -> int:
    """Entry point: build + run the bot until SIGINT/SIGTERM."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        app = build_application()
    except ConfigError as e:
        log.error("config error: %s", e)
        return 2

    log.info("starting Telegram bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
