"""Multi-channel notifier: Slack + Telegram.

Triggered when overall_status is warn/crit. Each channel is opt-in via env:
- SLACK_WEBHOOK_URL
- TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import structlog

from ipracticom_sweeper.audit import alert_event

logger = structlog.get_logger()


# --- Formatters --------------------------------------------------------------


def _status_icon(status: str) -> str:
    return {"ok": "✅", "warn": "⚠️", "crit": "🔴"}.get(status, "❓")


def _defcon_icon(defcon_label: str) -> str:
    return {
        "green": "✅",
        "yellow": "⚠️",
        "orange": "🟠",
        "red": "🔴",
        "black": "🚨",
    }.get(defcon_label, "❓")


def format_slack_message(snapshot_or_result: dict[str, Any]) -> dict[str, Any]:
    """Format snapshot OR PipelineResult as Slack Block Kit message."""
    is_pipeline = "defcon" in snapshot_or_result and "defcon_label" in snapshot_or_result

    if is_pipeline:
        defcon = snapshot_or_result["defcon"]
        defcon_label = snapshot_or_result["defcon_label"]
        icon = _defcon_icon(defcon_label)
        header = f"{icon} Sweeper DEFCON {defcon} ({defcon_label})"
        problems = snapshot_or_result.get("problems_found", 0)
        repairs_ok = snapshot_or_result.get("repairs_succeeded", 0)
        repairs_total = snapshot_or_result.get("repairs_attempted", 0)
        server = snapshot_or_result.get("server", "unknown")
        summary = snapshot_or_result.get("diagnosis", {}).get("summary", "")

        body = [f"*Server*: `{server}`"]
        body.append(f"*Status*: {header}")
        body.append(f"*Summary*: {summary}")
        body.append(f"*Repairs*: {repairs_ok}/{repairs_total} succeeded")

        problems_list = snapshot_or_result.get("diagnosis", {}).get("problems", [])
        if problems_list:
            body.append("")
            body.append("*Problems:*")
            for p in problems_list[:10]:
                body.append(
                    f"  • `{p.get('kind')}` ({p.get('severity')}): {p.get('detail')}"
                )

        return {
            "text": header,
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": header}},
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(body)},
                },
            ],
        }

    overall = snapshot_or_result["overall_status"]
    icon = {"warn": ":warning:", "crit": ":rotating_light:"}.get(overall, ":white_check_mark:")

    lines = []
    for mod, data in snapshot_or_result["modules"].items():
        mod_status = data["status"]
        mod_icon = {x: y for x, y in [("ok", ":white_check_mark:"), ("warn", ":warning:"), ("crit", ":rotating_light:")]}[mod_status]
        lines.append(f"{mod_icon} *{mod}*: {mod_status}")

    server = snapshot_or_result.get("server", "unknown")

    return {
        "text": f"{icon} iPracticom Sweeper: {overall.upper()}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{icon} Sweeper: {overall.upper()}"}
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Server: *{server}*"}
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(lines)}
            }
        ],
    }


def format_telegram_message(snapshot_or_result: dict[str, Any]) -> str:
    """Format snapshot OR PipelineResult as plain text for Telegram (Markdown)."""
    is_pipeline = "defcon" in snapshot_or_result and "defcon_label" in snapshot_or_result

    if is_pipeline:
        defcon = snapshot_or_result["defcon"]
        defcon_label = snapshot_or_result["defcon_label"]
        icon = _defcon_icon(defcon_label)
        server = snapshot_or_result.get("server", "unknown")
        summary = snapshot_or_result.get("diagnosis", {}).get("summary", "")
        repairs_ok = snapshot_or_result.get("repairs_succeeded", 0)
        repairs_total = snapshot_or_result.get("repairs_attempted", 0)
        needs_human = snapshot_or_result.get("needs_human", 0)

        lines = [
            f"{icon} *iPracticom Sweeper* — DEFCON {defcon} ({defcon_label})",
            f"Server: `{server}`",
            "",
            f"_{summary}_",
            f"Repairs: {repairs_ok}/{repairs_total} succeeded",
        ]
        if needs_human:
            lines.append(f"⚠️ Needs human attention: {needs_human}")

        problems_list = snapshot_or_result.get("diagnosis", {}).get("problems", [])
        if problems_list:
            lines.append("")
            lines.append("*Problems:*")
            for p in problems_list[:10]:
                sev_emoji = {"warn": "⚠️", "crit": "🔴"}.get(p.get("severity"), "•")
                lines.append(f"  {sev_emoji} `{p.get('kind')}` — {p.get('detail')}")
        return "\n".join(lines)

    overall = snapshot_or_result["overall_status"]
    icon = {"warn": "⚠️", "crit": "🔴"}.get(overall, "✅")

    lines = [
        f"{icon} *iPracticom Sweeper*: {overall.upper()}",
        f"Server: `{snapshot_or_result.get('server', 'unknown')}`",
        "",
    ]
    for mod, data in snapshot_or_result["modules"].items():
        mod_icon = _status_icon(data["status"])
        lines.append(f"  {mod_icon} {mod}: {data['status']}")
    return "\n".join(lines)


# --- Channel senders ---------------------------------------------------------


async def _send_slack(message: dict[str, Any]) -> bool:
    from ipracticom_sweeper import config as _cfg
    url = _cfg.slack_webhook_url()
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=message)
        success = resp.status_code == 200
        alert_event("slack", {"status_code": resp.status_code}, "info" if success else "error")
        return success
    except Exception as e:
        alert_event("slack", {"error": str(e)}, "error")
        logger.error("slack_send_failed", error=str(e))
        return False


async def _send_telegram(text: str) -> bool:
    from ipracticom_sweeper import config as _cfg
    token = _cfg.telegram_bot_token()
    chat_id = _cfg.telegram_chat_id()
    if not (token and chat_id):
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_notification": False,
            })
        success = resp.status_code == 200
        alert_event("telegram", {"status_code": resp.status_code}, "info" if success else "error")
        return success
    except Exception as e:
        alert_event("telegram", {"error": str(e)}, "error")
        logger.error("telegram_send_failed", error=str(e))
        return False


# --- Top-level ---------------------------------------------------------------


async def notify(snapshot: dict[str, Any], force: bool = False) -> dict[str, bool]:
    """Send notification to all configured channels.

    force=True: send even if status is ok (for periodic "still alive" pings).
    Returns dict of {channel: success}.
    """
    overall = snapshot["overall_status"]
    if not force and overall == "ok":
        return {}

    from ipracticom_sweeper import config as _cfg
    if not _cfg.notifications_enabled():
        logger.warning("notifications_enabled_but_no_channels")
        return {}

    results = {}
    tasks = []

    if _cfg.slack_webhook_url():
        msg = format_slack_message(snapshot)
        tasks.append(("slack", _send_slack(msg)))

    if _cfg.telegram_bot_token() and _cfg.telegram_chat_id():
        msg = format_telegram_message(snapshot)
        tasks.append(("telegram", _send_telegram(msg)))

    for channel, coro in tasks:
        try:
            results[channel] = await coro
        except Exception as e:
            results[channel] = False
            logger.error(f"{channel}_notify_failed", error=str(e))

    return results


async def notify_pipeline_result(result_dict: dict[str, Any], force: bool = False) -> dict[str, bool]:
    """Send notification for a PipelineResult (newer shape with DEFCON).

    Skips when DEFCON >= 5 (green) unless force=True.
    Skips entirely if no channels configured.
    """
    defcon = result_dict.get("defcon", 5)
    if not force and defcon >= 5:
        return {}

    from ipracticom_sweeper import config as _cfg
    if not _cfg.notifications_enabled():
        logger.debug("no_notification_channels_configured")
        return {}

    results = {}
    if _cfg.slack_webhook_url():
        msg = format_slack_message(result_dict)
        results["slack"] = await _send_slack(msg)
    if _cfg.telegram_bot_token() and _cfg.telegram_chat_id():
        msg = format_telegram_message(result_dict)
        results["telegram"] = await _send_telegram(msg)
    return results


if __name__ == "__main__":
    import sys
    snapshot = json.loads(sys.stdin.read())
    result = asyncio.run(notify(snapshot))
    print(json.dumps(result))
