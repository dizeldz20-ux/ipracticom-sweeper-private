"""Structured JSONL audit logger.

Every monitor, diagnostic, repair, and verify action emits one JSONL line.
Output goes to a file and optionally to CloudWatch (TODO: hook in boto3).
"""

import json
import os
import socket
import time
from pathlib import Path
from typing import Any, Optional

import structlog

from ..config import get_server_id

logger = structlog.get_logger()

# --- Audit log path ----------------------------------------------------------

AUDIT_LOG_DIR = Path("/var/log/ipracticom-sweeper")
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "audit.jsonl"


def _ensure_log_dir() -> None:
    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)


# --- Core emit ---------------------------------------------------------------


def emit(
    event_type: str,
    payload: dict[str, Any],
    severity: str = "info",
) -> None:
    """Emit one audit record.

    event_type: "monitor.cpu", "diagnose.rule", "repair.disk_cleanup",
                "verify.post_check", "alert.slack", etc.
    payload: event-specific data
    severity: "debug" | "info" | "warn" | "error" | "critical"
    """
    record = {
        "ts": time.time(),
        "ts_iso": _iso_now(),
        "server": get_server_id(),
        "event": event_type,
        "severity": severity,
        "payload": payload,
    }

    # JSONL to file
    try:
        _ensure_log_dir()
        with open(AUDIT_LOG_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except PermissionError:
        # Fallback to user-local dir
        fallback = Path.home() / ".ipracticom-sweeper" / "audit.jsonl"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        with open(fallback, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        logger.error("audit_log_write_failed", error=str(e))

    # Also log via structlog for local visibility
    getattr(logger, severity if severity != "critical" else "critical")(
        event_type, **payload
    )


def _iso_now() -> str:
    """Return ISO8601 UTC timestamp."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# --- Helpers ----------------------------------------------------------------


def monitor_event(metric: str, values: dict[str, Any], threshold_status: str) -> None:
    """Emit a monitor event with threshold status.

    threshold_status: "ok" | "warn" | "crit"
    """
    severity = {
        "ok": "debug",
        "warn": "warn",
        "crit": "error",
    }.get(threshold_status, "info")

    emit(
        f"monitor.{metric}",
        {"values": values, "status": threshold_status},
        severity=severity,
    )


def alert_event(channel: str, payload: dict[str, Any], severity: str = "critical") -> None:
    """Emit an alert sent event."""
    emit(f"alert.{channel}", payload, severity=severity)


def repair_event(
    action: str,
    target: str,
    result: str,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Emit a repair action result.

    result: "success" | "failed" | "skipped" | "dry_run"
    """
    severity = "warn" if result == "failed" else "info"
    emit(
        f"repair.{action}",
        {"target": target, "result": result, "details": details or {}},
        severity=severity,
    )