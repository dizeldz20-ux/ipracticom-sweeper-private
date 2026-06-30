"""Fleet handler — host list + per-host details (v0.4.2).

Owns:
  - menu:fleet: every host in the fleet
  - fleet:host:<name>: per-host details
"""
from __future__ import annotations

from typing import Any

from ipracticom_sweeper.telegram_bot.formatter import (
    format_error,
    format_fleet_host,
    format_fleet_list,
)
from ipracticom_sweeper.telegram_bot.keyboards import (
    back_to_main,
    fleet_menu,
)
from ipracticom_sweeper.telegram_bot.services.agent_client import (
    AgentAPIError,
    AgentClient,
)


def _agent(context) -> AgentClient:
    return context.bot_data["agent"]


# ---------- menu:fleet ----------

async def fleet(update, context) -> dict[str, Any]:
    """Show the fleet: local + every SSM connector."""
    try:
        data = await _agent(context).list_fleet()
    except AgentAPIError as e:
        return {"text": format_error(str(e)), "reply_markup": back_to_main()}

    hosts = data.get("hosts") or []
    return {
        "text": format_fleet_list(hosts),
        "reply_markup": fleet_menu(hosts),
    }


# ---------- fleet:host:<name> ----------

async def fleet_host(update, context) -> dict[str, Any]:
    """Show one host's details (local reads heartbeat, connectors read config)."""
    cq = getattr(update, "callback_query", None)
    data = (getattr(cq, "data", "") or "")
    name = data.split(":", 2)[2] if data.count(":") >= 2 else ""
    if not name:
        return {"text": "❌ שם מארח חסר", "reply_markup": back_to_main()}

    try:
        host = await _agent(context).get_fleet_host(name)
    except AgentAPIError as e:
        return {"text": format_error(str(e)), "reply_markup": back_to_main()}

    return {
        "text": format_fleet_host(host),
        "reply_markup": back_to_main(),
    }