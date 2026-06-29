"""HTML message formatting for the iPracticom Sweeper Telegram bot.

Follows the public `telegram-bot-builder` skill's patterns:
visual hierarchy (header → summary → details), smart truncation,
HTML escaping. Output is always Telegram-safe HTML.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

DEFCON_EMOJI: dict[int, str] = {
    1: "🚨",  # critical
    2: "🔴",  # high alert
    3: "🟡",  # warning
    4: "🔵",  # guarded
    5: "🟢",  # all clear
}


def escape_html(text: str) -> str:
    """Escape HTML metacharacters for Telegram HTML parse_mode."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _truncate_items(items: list[str], max_items: int = 5) -> tuple[list[str], int]:
    """Truncate a list, returning the visible slice and the count of the rest."""
    visible = items[:max_items]
    rest = len(items) - len(visible)
    return visible, rest


def _module_problems(modules: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Extract problem modules as (name, status, details) tuples."""
    out: list[tuple[str, str, str]] = []
    for name, info in modules.items():
        if not isinstance(info, dict):
            continue
        status = info.get("status", "ok")
        if status in ("ok", "healthy", "green"):
            continue
        details = info.get("details") or info.get("message") or ""
        out.append((name, status, str(details)))
    return out


def format_snapshot(snap: dict) -> str:
    """Format a /api/snapshot payload as a status summary.

    Visual hierarchy:
      1. DEFCON header (one line, bold, emoji)
      2. Optional problem summary (max 5)
      3. Truncation suffix if more
    """
    defcon = int(snap.get("defcon", 5))
    emoji = DEFCON_EMOJI.get(defcon, "❓")
    modules = snap.get("modules", {}) or {}
    problems = _module_problems(modules)

    lines: list[str] = [f"{emoji} <b>DEFCON {defcon}</b>"]
    if not problems:
        lines.append("✅ <i>הכל תקין — אין בעיות פעילות</i>")
        return "\n".join(lines)

    lines.append(f"<i>{len(problems)} בעיות פעילות:</i>")
    visible, rest = _truncate_items(
        [f"  • <b>{escape_html(n)}</b> [{escape_html(s)}] — {escape_html(d) or '—'}"
         for n, s, d in problems],
        max_items=5,
    )
    lines.extend(visible)
    if rest > 0:
        lines.append(f"  <i>...+{rest} more</i>")
    return "\n".join(lines)


def format_problems(snap: dict) -> str:
    """Format a snapshot as an active-problems list (only warn/crit)."""
    modules = snap.get("modules", {}) or {}
    problems = _module_problems(modules)
    if not problems:
        return "✅ <b>אין בעיות פעילות</b>\n<i>המערכת יציבה</i>"

    lines = [f"⚠️ <b>{len(problems)} בעיות פעילות</b>", ""]
    severity_emoji = {"crit": "🚨", "critical": "🚨", "warn": "⚠️", "warning": "⚠️"}
    for name, status, details in problems:
        e = severity_emoji.get(status, "•")
        lines.append(f"{e} <b>{escape_html(name)}</b> [{escape_html(status)}]")
        if details:
            lines.append(f"   <i>{escape_html(details)}</i>")
    return "\n".join(lines)


def format_history(metric: str, samples: list[dict]) -> str:
    """Format a time-series sample list as a Hebrew summary."""
    if not samples:
        return f"📈 <b>{escape_html(metric)}</b>\n<i>אין נתונים ב-24 השעות האחרונות</i>"

    values = [s.get("value") for s in samples if s.get("value") is not None]
    values = [v for v in values if isinstance(v, (int, float))]
    lines: list[str] = [f"📈 <b>{escape_html(metric)}</b> — {len(samples)} דגימות"]
    if values:
        try:
            vmin = min(values)
            vmax = max(values)
            vlast = values[-1]
            lines.append(
                f"<i>min: {vmin:.2f}  |  max: {vmax:.2f}  |  latest: {vlast:.2f}</i>"
            )
        except (TypeError, ValueError):
            pass
    # Show last 5 timestamps
    tail = samples[-5:]
    ts_lines = []
    for s in tail:
        try:
            ts = int(s.get("ts", 0))
            v = s.get("value")
            when = datetime.fromtimestamp(ts).strftime("%H:%M")
            ts_lines.append(f"  • {when} → {v}")
        except (TypeError, ValueError, OSError):
            continue
    if ts_lines:
        lines.append("")
        lines.append("<i>5 אחרונות:</i>")
        lines.extend(ts_lines)
    return "\n".join(lines)


def format_security(report: dict) -> str:
    """Format a security-baseline report."""
    drift = report.get("ssh_drift") or []
    suid = report.get("suid_changes") or []
    ports = report.get("ports") or []

    lines: list[str] = ["🔐 <b>אבטחה</b>", ""]

    lines.append(f"<b>SSH config drift:</b> {len(drift)} חריגות")
    for item in drift[:3]:
        lines.append(f"  • {escape_html(str(item))}")
    if len(drift) > 3:
        lines.append(f"  <i>...+{len(drift) - 3} more</i>")

    lines.append("")
    lines.append(f"<b>SUID changes:</b> {len(suid)} שינויים")
    for item in suid[:3]:
        lines.append(f"  • {escape_html(str(item))}")
    if len(suid) > 3:
        lines.append(f"  <i>...+{len(suid) - 3} more</i>")

    lines.append("")
    lines.append(f"<b>Listening ports:</b> {len(ports)}")
    for p in ports[:5]:
        if isinstance(p, dict):
            lines.append(
                f"  • port {p.get('port', '?')} — {escape_html(str(p.get('service', '?')))}"
            )
    if len(ports) > 5:
        lines.append(f"  <i>...+{len(ports) - 5} more</i>")
    return "\n".join(lines)


def format_error(reason: str = "") -> str:
    """Generic Hebrew error for user-facing messages."""
    suffix = f"\n<i>{escape_html(reason)}</i>" if reason else ""
    return f"❌ <b>שגיאה</b> — לא הצלחתי להביא נתונים{suffix}"
