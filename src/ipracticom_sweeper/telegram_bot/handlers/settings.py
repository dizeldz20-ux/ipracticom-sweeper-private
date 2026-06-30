"""Settings handler — webhook tests + server identity (v0.4.2).

Owns:
  - menu:settings: settings submenu
  - set:test:slack: send a Slack test notification (if configured)
  - set:test:tg: send a Telegram test message to the calling user
  - set:test:api: ping the agent_api /healthz
"""
from __future__ import annotations

from typing import Any

from ipracticom_sweeper.telegram_bot.keyboards import (
    back_to_main,
    settings_menu,
)
from ipracticom_sweeper.telegram_bot.services.agent_client import (
    AgentAPIError,
    AgentClient,
)


def _agent(context) -> AgentClient:
    return context.bot_data["agent"]


# ---------- menu:settings ----------

async def settings(update, context) -> dict[str, Any]:
    """Show the settings submenu + server identity."""
    cfg = context.bot_data.get("config")
    server_id = getattr(cfg, "bot_token", "")[:8] + "..." if cfg else "?"
    has_token = bool(cfg and getattr(cfg, "agent_api_token", ""))

    try:
        health = await _agent(context).healthz()
    except Exception:
        health = False

    text = (
        "⚙️ <b>הגדרות</b>\n\n"
        f"  server_id: <code>{server_id}</code>\n"
        f"  agent_api: {'✅ זמין' if health else '❌ לא זמין'}\n"
        f"  token: {'✅ מוגדר' if has_token else '⚠️ חסר (מצב OPEN)'}\n"
    )
    return {"text": text, "reply_markup": settings_menu(server_id, has_token)}


# ---------- set:test:api ----------

async def test_api(update, context) -> dict[str, Any]:
    """Ping the agent_api /healthz."""
    try:
        ok = await _agent(context).healthz()
    except AgentAPIError as e:
        return {"text": f"❌ Agent API: <i>{e}</i>", "reply_markup": back_to_main()}
    if ok:
        return {"text": "✅ <b>Agent API</b> זמין (/healthz → 200)", "reply_markup": back_to_main()}
    return {"text": "❌ <b>Agent API</b> לא זמין", "reply_markup": back_to_main()}


# ---------- set:test:tg ----------

async def test_tg(update, context) -> dict[str, Any]:
    """Send a test message back to the calling chat.

    This handler is itself the test — if you got a response, Telegram is
    working. We also try a getMe to confirm the bot token is valid.
    """
    try:
        me = await context.bot.get_me()
    except Exception as e:
        return {"text": f"❌ Telegram: <i>{e}</i>", "reply_markup": back_to_main()}
    return {
        "text": (
            "✅ <b>Telegram</b> זמין\n"
            f"  bot: <code>{me.username}</code> (id={me.id})\n"
            f"  זה ההודעה שקיבלת — אם קראת אותה, הכל תקין."
        ),
        "reply_markup": back_to_main(),
    }


# ---------- set:test:slack ----------

async def test_slack(update, context) -> dict[str, Any]:
    """Send a Slack test notification via the agent_api.

    Returns the result of POST /api/notify/test. If Slack isn't configured
    on the agent, the agent returns 503 — we surface that as a friendly
    Hebrew message instead of a raw error.
    """
    agent = _agent(context)
    try:
        result = await agent._post("/api/notify/test")  # type: ignore[attr-defined]
    except AgentAPIError as e:
        if e.status_code == 503:
            return {
                "text": "⚠️ Slack webhook לא מוגדר ב-agent_api.\n"
                        "<i>הגדר SLACK_WEBHOOK_URL ב-env כדי לאפשר התראות.</i>",
                "reply_markup": back_to_main(),
            }
        return {"text": f"❌ Slack: <i>{e}</i>", "reply_markup": back_to_main()}

    sent = int(result.get("sent", 0))
    if sent > 0:
        return {
            "text": f"✅ <b>Slack</b> נשלח ({sent} הודעות)",
            "reply_markup": back_to_main(),
        }
    return {
        "text": "⚠️ Slack לא שלח כלום — בדוק את SLACK_WEBHOOK_URL",
        "reply_markup": back_to_main(),
    }