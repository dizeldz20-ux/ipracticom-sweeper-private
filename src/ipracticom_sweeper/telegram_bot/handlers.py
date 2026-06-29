"""Command and callback handlers for the iPracticom Sweeper Telegram bot.

Each handler returns a dict: `{"text": ..., "reply_markup": ...}` so the
caller (the dispatcher in `bot.py`) can send it. We don't import
python-telegram-bot here — handlers are pure async functions over
`(update, context)`. This keeps them trivially testable.
"""
from __future__ import annotations

from typing import Any

from ipracticom_sweeper.telegram_bot.config import BotConfig
from ipracticom_sweeper.telegram_bot.formatter import (
    format_error,
    format_history,
    format_problems,
    format_security,
    format_snapshot,
)
from ipracticom_sweeper.telegram_bot.keyboards import (
    history_menu,
    main_menu,
    status_menu,
)
from ipracticom_sweeper.telegram_bot.services.agent_client import (
    AgentAPIError,
    AgentClient,
)


def _config(context) -> BotConfig:
    return context.bot_data["config"]


def _agent(context) -> AgentClient:
    return context.bot_data["agent"]


# ---------- /start ----------

async def start(update, context) -> dict[str, Any]:
    """Welcome message + main menu."""
    return {
        "text": (
            "🛡️ <b>iPracticom Sweeper</b>\n"
            "\n"
            "ברוך הבא. בחר פעולה מהתפריט:\n"
            "<i>כל הנתונים נמשכים מה-agent_api המקומי</i>"
        ),
        "reply_markup": main_menu(),
    }


# ---------- menu:status ----------

async def status(update, context) -> dict[str, Any]:
    """Show current snapshot from /api/snapshot."""
    try:
        snap = await _agent(context).get_snapshot()
    except AgentAPIError as e:
        return {"text": format_error(str(e)), "reply_markup": main_menu()}
    return {
        "text": format_snapshot(snap),
        "reply_markup": status_menu(),
    }


# ---------- menu:problems ----------

async def problems(update, context) -> dict[str, Any]:
    """Show only active problems from the snapshot."""
    try:
        snap = await _agent(context).get_snapshot()
    except AgentAPIError as e:
        return {"text": format_error(str(e)), "reply_markup": main_menu()}
    return {
        "text": format_problems(snap),
        "reply_markup": main_menu(),
    }


# ---------- hist:{metric} ----------

async def history(update, context) -> dict[str, Any]:
    """Show time-series for a given metric. Metric name comes from callback data."""
    cq = getattr(update, "callback_query", None)
    data = getattr(cq, "data", "") or ""
    metric = data.split(":", 1)[1] if ":" in data else "defcon"
    try:
        samples = await _agent(context).get_history(metric, hours=24)
    except AgentAPIError as e:
        return {"text": format_error(str(e)), "reply_markup": history_menu()}
    return {
        "text": format_history(metric, samples),
        "reply_markup": history_menu(),
    }


# ---------- menu:security ----------

async def security(update, context) -> dict[str, Any]:
    """Show security-baseline report (SSH/SUID/ports)."""
    try:
        snap = await _agent(context).get_snapshot()
    except AgentAPIError as e:
        return {"text": format_error(str(e)), "reply_markup": main_menu()}

    sb = (snap.get("modules") or {}).get("security_baseline") or {}
    details = sb.get("details") if isinstance(sb, dict) else None
    if not isinstance(details, dict):
        details = {
            "ssh_drift": [],
            "suid_changes": [],
            "ports": [],
        }
    return {
        "text": format_security(details),
        "reply_markup": main_menu(),
    }
