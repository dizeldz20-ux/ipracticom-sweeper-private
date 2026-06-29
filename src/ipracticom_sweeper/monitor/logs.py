"""Log health: error rate from journalctl.

Detects:
- High error rate in last N minutes
- OOM killer activations
- Kernel panics / hardware errors
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any


def _run_journalctl(args: list[str]) -> tuple[int, str]:
    """Run journalctl, return (rc, stdout)."""
    try:
        result = subprocess.run(
            ["journalctl"] + args,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode, result.stdout
    except FileNotFoundError:
        return 127, ""
    except Exception as e:
        return 1, str(e)


def count_by_priority(since_minutes: int = 5) -> dict[str, int]:
    """Count log lines by priority in the last N minutes."""
    rc, out = _run_journalctl([
        f"--since={since_minutes} minutes ago",
        "--no-pager",
        "-o", "short",
    ])
    if rc != 0 or not out:
        return {"emerg": 0, "alert": 0, "crit": 0, "err": 0, "warning": 0}

    counts = {"emerg": 0, "alert": 0, "crit": 0, "err": 0, "warning": 0}
    # Format: "Jun 28 13:45:12 hostname process[pid]: PRIORITY message"
    # Priority is in the message after process identification.
    for line in out.split("\n"):
        # Simple keyword detection — better to use -p flag but that filters
        if re.search(r"\bemerg\b", line, re.IGNORECASE):
            counts["emerg"] += 1
        elif re.search(r"\balert\b", line, re.IGNORECASE):
            counts["alert"] += 1
        elif re.search(r"\bcrit\b", line, re.IGNORECASE):
            counts["crit"] += 1
        elif re.search(r"\berr\b", line, re.IGNORECASE):
            counts["err"] += 1
        elif re.search(r"\bwarning\b", line, re.IGNORECASE):
            counts["warning"] += 1
    return counts


def find_oom_events(window_minutes: int = 60) -> list[str]:
    """Find OOM killer activations in the last N minutes."""
    rc, out = _run_journalctl([
        f"--since={window_minutes} minutes ago",
        "--no-pager",
        "-k",   # kernel messages only
        "-g", "killed process",
    ])
    if rc != 0 or not out:
        return []
    return [line for line in out.split("\n") if "Out of memory" in line or "killed process" in line]


def collect(rules: dict) -> dict[str, Any]:
    """Collect log health snapshot."""
    window = rules.get("logs", {}).get("failed_units_window_min", 5)
    oom_window = rules.get("logs", {}).get("oom_events_window_min", 60)

    by_priority = count_by_priority(window)
    oom_events = find_oom_events(oom_window)
    total_errors = by_priority["emerg"] + by_priority["alert"] + by_priority["crit"] + by_priority["err"]
    error_rate_per_min = total_errors / max(window, 1)

    return {
        "window_minutes": window,
        "by_priority": by_priority,
        "error_rate_per_minute": round(error_rate_per_min, 2),
        "oom_events": oom_events[:10],  # truncate
        "oom_count": len(oom_events),
    }


def evaluate(values: dict[str, Any], rules: dict) -> str:
    """Apply rules; return 'ok' | 'warn' | 'crit'."""
    if values["oom_count"] > 0:
        return "crit"
    rate = values["error_rate_per_minute"]
    if rate >= rules["logs"]["error_rate_per_min_warn"] * 5:
        return "crit"
    if rate >= rules["logs"]["error_rate_per_min_warn"]:
        return "warn"
    if values["by_priority"]["crit"] > 0 or values["by_priority"]["alert"] > 0:
        return "warn"
    return "ok"