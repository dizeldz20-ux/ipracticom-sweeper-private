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


# ---------------------------- v0.4.2 formatters ----------------------------

def format_dashboard(snap: dict) -> str:
    """Dashboard view: DEFCON + problems summary + run-now button.

    Output is identical to format_snapshot() but explicitly named so
    the dashboard handler has a clear intent.
    """
    return format_snapshot(snap)


def format_history_catalog(catalog: dict) -> str:
    """History overview: list metrics with sample counts."""
    metrics = catalog.get("metrics") or []
    hosts = catalog.get("hosts") or []
    if not metrics:
        return "📚 <b>היסטוריה</b>\n<i>אין מטריקות במאגר עדיין</i>"

    lines: list[str] = ["📚 <b>היסטוריה — מטריקות</b>", ""]
    lines.append(f"<i>{len(metrics)} מטריקות | {len(hosts)} מארחים</i>")
    lines.append("")
    for m in metrics[:20]:
        lines.append(f"  • <code>{escape_html(str(m))}</code>")
    if len(metrics) > 20:
        lines.append(f"  <i>...+{len(metrics) - 20} more</i>")
    return "\n".join(lines)


def format_approvals_list(pending: list[dict]) -> str:
    """Approvals overview: list of pending repair proposals."""
    if not pending:
        return "✅ <b>אין תיקונים הממתינים לאישור</b>\n<i>המערכת יציבה</i>"

    lines: list[str] = [f"📋 <b>{len(pending)} תיקונים ממתינים</b>", ""]
    for p in pending[:8]:
        pid = str(p.get("id", "?"))[:8]
        action = str(p.get("action", "?"))
        reason = str(p.get("reason", ""))
        lines.append(f"  • <code>{pid}</code> <b>{escape_html(action)}</b>")
        if reason:
            lines.append(f"    <i>{escape_html(reason[:80])}</i>")
    if len(pending) > 8:
        lines.append(f"  <i>...+{len(pending) - 8} more</i>")
    return "\n".join(lines)


def format_approval_result(result: dict) -> str:
    """Result of approve/reject: Hebrew confirmation."""
    ok = bool(result.get("ok", False))
    status = result.get("status", "?")
    if ok:
        emoji = "✅"
        verb = "בוצע בהצלחה"
    else:
        emoji = "❌"
        verb = "נכשל"
    msg = result.get("message") or result.get("error") or ""
    lines: list[str] = [f"{emoji} <b>תיקון {verb}</b>  [{escape_html(status)}]"]
    if msg:
        lines.append(f"<i>{escape_html(str(msg)[:200])}</i>")
    return "\n".join(lines)


def format_connectors_list(connectors: list[dict]) -> str:
    """Connectors overview: list with status emoji."""
    if not connectors:
        return "🔌 <b>מחברים</b>\n<i>אין מחברים מוגדרים. לחץ 'הוסף מחבר' כדי להתחיל.</i>"

    lines: list[str] = [f"🔌 <b>מחברים ({len(connectors)})</b>", ""]
    for c in connectors[:15]:
        name = str(c.get("name", "?"))
        iid = str(c.get("instance_id", "?"))
        region = str(c.get("region", "?"))
        status = c.get("status", "unknown")
        emoji = "✅" if status == "ok" else ("❌" if status == "error" else "❓")
        lines.append(f"  {emoji} <b>{escape_html(name)}</b> — <code>{escape_html(iid)}</code> ({escape_html(region)})")
    if len(connectors) > 15:
        lines.append(f"  <i>...+{len(connectors) - 15} more</i>")
    return "\n".join(lines)


def format_connector_detail(c: dict) -> str:
    """Per-connector detail view."""
    name = str(c.get("name", "?"))
    iid = str(c.get("instance_id", "?"))
    region = str(c.get("region", "?"))
    status = c.get("status", "unknown")
    tags = c.get("tags") or {}
    last_collected = c.get("last_collected_at")
    last_error = c.get("last_error")

    lines: list[str] = [f"🔌 <b>{escape_html(name)}</b>", ""]
    lines.append(f"  instance: <code>{escape_html(iid)}</code>")
    lines.append(f"  region: <code>{escape_html(region)}</code>")
    lines.append(f"  status: <b>{escape_html(str(status))}</b>")
    if last_collected:
        lines.append(f"  last_collected: <code>{escape_html(str(last_collected))}</code>")
    if last_error:
        lines.append(f"  last_error: <i>{escape_html(str(last_error)[:120])}</i>")
    if tags:
        tag_str = ", ".join(f"{k}={v}" for k, v in tags.items())
        lines.append(f"  tags: <i>{escape_html(tag_str)}</i>")
    return "\n".join(lines)


def format_fleet_list(hosts: list[dict]) -> str:
    """Fleet overview: every host with status."""
    if not hosts:
        return "🖥️ <b>צי</b>\n<i>אין מארחים</i>"

    lines: list[str] = [f"🖥️ <b>צי ({len(hosts)} מארחים)</b>", ""]
    for h in hosts[:15]:
        name = str(h.get("name", "?"))
        status = h.get("status", "unknown")
        kind = h.get("kind", "?")
        emoji = "✅" if status == "ok" else ("⚠️" if status == "warn" else (
            "🚨" if status == "crit" else "❓"
        ))
        lines.append(f"  {emoji} <b>{escape_html(name)}</b> <i>({escape_html(kind)})</i>")
    if len(hosts) > 15:
        lines.append(f"  <i>...+{len(hosts) - 15} more</i>")
    return "\n".join(lines)


def format_fleet_host(host: dict) -> str:
    """Per-host detail view (local reads heartbeat, connectors read config)."""
    name = str(host.get("name", "?"))
    kind = str(host.get("kind", "?"))
    status = host.get("status", "unknown")
    lines: list[str] = [f"🖥️ <b>{escape_html(name)}</b> ({escape_html(kind)})", ""]
    lines.append(f"  status: <b>{escape_html(str(status))}</b>")
    if "defcon" in host:
        lines.append(f"  defcon: {host.get('defcon')}")
    if "problems_found" in host:
        lines.append(f"  problems: {host.get('problems_found')}")
    if "repairs_attempted" in host:
        lines.append(f"  repairs attempted: {host.get('repairs_attempted')}")
    if "last_seen" in host and host["last_seen"]:
        lines.append(f"  last seen: <code>{escape_html(str(host['last_seen']))}</code>")
    if "last_error" in host and host["last_error"]:
        lines.append(f"  last error: <i>{escape_html(str(host['last_error'])[:120])}</i>")
    if "instance_id" in host:
        lines.append(f"  instance: <code>{escape_html(str(host['instance_id']))}</code>")
    if "region" in host:
        lines.append(f"  region: <code>{escape_html(str(host['region']))}</code>")
    return "\n".join(lines)