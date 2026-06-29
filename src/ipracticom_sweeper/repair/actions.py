"""Repair action framework.

Every repair must:
  1. Take a pre-action snapshot (for rollback)
  2. Be classified by safety (SAFE / GUARDED / DANGEROUS / NEVER)
  3. Be reversible (or have a rollback plan)
  4. Be auditable (every action logged with snapshot id)

Available repair actions:
  - drop_caches: clear pagecache (SAFE, always works)
  - log_truncate_journald: vacuum old journal (GUARDED)
  - service_restart: restart a failed service (GUARDED, only if critical)
  - top_processes_snapshot: just collect top-N (SAFE, read-only)
  - notify_human: send alert to Slack/Telegram (SAFE)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import structlog

logger = structlog.get_logger()


# --- Snapshot store ----------------------------------------------------------

# Snapshots live under the same configurable state root so tests can sandbox
# everything (pending, audit, snapshots) into a tmp dir via
# IPRACTICOM_SWEEPER_STATE_DIR.
import os as _os

_BASE_STATE = Path(
    _os.environ.get(
        "IPRACTICOM_SWEEPER_STATE_DIR", "/var/lib/ipracticom-sweeper"
    )
)
SNAPSHOT_DIR = _BASE_STATE / "snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Snapshot:
    """A pre-action snapshot for rollback."""

    id: str
    action: str
    target: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)
    rollback_command: str | None = None  # how to undo
    rollback_notes: str | None = None

    def save(self) -> Path:
        path = SNAPSHOT_DIR / f"{self.id}.json"
        with open(path, "w") as f:
            json.dump(self.__dict__, f, indent=2)
        logger.info("snapshot_saved", id=self.id, action=self.action, target=self.target)
        return path

    @classmethod
    def load(cls, snapshot_id: str) -> "Snapshot":
        path = SNAPSHOT_DIR / f"{snapshot_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Snapshot {snapshot_id} not found")
        with open(path) as f:
            data = json.load(f)
        return cls(**data)


def _new_snapshot(action: str, target: str, **metadata) -> Snapshot:
    return Snapshot(
        id=str(uuid.uuid4()),
        action=action,
        target=target,
        created_at=datetime.now(timezone.utc).isoformat(),
        metadata=metadata,
    )


# --- Result types ------------------------------------------------------------


@dataclass
class RepairResult:
    """The outcome of a repair attempt."""

    action: str
    target: str
    success: bool
    snapshot_id: str | None
    message: str
    duration_ms: int
    output: str = ""
    error: str | None = None
    rollback_available: bool = False


# --- Repair registry ---------------------------------------------------------


# Map action name → handler function
REPAIRS: dict[str, Callable[..., RepairResult]] = {}


def register(name: str):
    """Decorator to register a repair function."""

    def decorator(fn):
        REPAIRS[name] = fn
        logger.debug("repair_registered", name=name)
        return fn

    return decorator


# --- Built-in repair actions -------------------------------------------------


@register("drop_caches")
def repair_drop_caches(level: int = 3) -> RepairResult:
    """Drop pagecache, dentries, and inodes from kernel.

    SAFE: this only frees reclaimable memory, doesn't destroy data.
    Level 1: pagecache
    Level 2: + dentries + inodes
    Level 3: + slab objects (full drop)
    """
    if level not in (1, 2, 3):
        return RepairResult(
            action="drop_caches",
            target=f"level={level}",
            success=False,
            snapshot_id=None,
            message=f"Invalid level {level} (must be 1, 2, or 3)",
            duration_ms=0,
        )

    snap = _new_snapshot(
        action="drop_caches",
        target=f"level={level}",
        pre_meminfo=Path("/proc/meminfo").read_text()[:500],
    )
    snap.save()

    start = time.time()
    try:
        with open("/proc/sys/vm/drop_caches", "w") as f:
            f.write(f"{level}\n")
        duration = int((time.time() - start) * 1000)
        logger.info("repair_executed", action="drop_caches", level_value=level, snapshot=snap.id)
        return RepairResult(
            action="drop_caches",
            target=f"level={level}",
            success=True,
            snapshot_id=snap.id,
            message=f"drop_caches level={level} executed",
            duration_ms=duration,
            rollback_available=False,  # not reversible, but safe
        )
    except PermissionError as e:
        duration = int((time.time() - start) * 1000)
        return RepairResult(
            action="drop_caches",
            target=f"level={level}",
            success=False,
            snapshot_id=snap.id,
            message="Permission denied — need root",
            duration_ms=duration,
            error=str(e),
        )


@register("log_truncate_journald")
def repair_log_truncate_journald(max_age_days: int = 7) -> RepairResult:
    """Vacuum journald logs older than max_age_days.

    GUARDED: safe but irreversible (log data lost).
    """
    snap = _new_snapshot(
        action="log_truncate_journald",
        target=f"max_age_days={max_age_days}",
        pre_disk_usage=_disk_usage("/var/log/journal"),
    )
    snap.save()

    start = time.time()
    try:
        result = subprocess.run(
            ["journalctl", "--vacuum-time", f"{max_age_days}d"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        duration = int((time.time() - start) * 1000)
        success = result.returncode == 0
        logger.info(
            "repair_executed",
            action="log_truncate_journald",
            success=success,
            snapshot=snap.id,
            stdout_preview=result.stdout[:200],
        )
        return RepairResult(
            action="log_truncate_journald",
            target=f"max_age_days={max_age_days}",
            success=success,
            snapshot_id=snap.id,
            message=result.stdout.strip()[:200] if success else "vacuum failed",
            duration_ms=duration,
            output=result.stdout,
            error=result.stderr if not success else None,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        duration = int((time.time() - start) * 1000)
        return RepairResult(
            action="log_truncate_journald",
            target=f"max_age_days={max_age_days}",
            success=False,
            snapshot_id=snap.id,
            message=f"Repair failed: {type(e).__name__}",
            duration_ms=duration,
            error=str(e),
        )


@register("service_restart")
def repair_service_restart(unit: str) -> RepairResult:
    """Restart a systemd service. GUARDED — service goes down briefly.

    Only valid for services classified as critical in the rules.
    """
    snap = _new_snapshot(
        action="service_restart",
        target=unit,
        pre_state=_service_state(unit),
    )
    snap.save()

    start = time.time()
    try:
        result = subprocess.run(
            ["systemctl", "restart", unit],
            capture_output=True,
            text=True,
            timeout=60,
        )
        duration = int((time.time() - start) * 1000)
        success = result.returncode == 0
        return RepairResult(
            action="service_restart",
            target=unit,
            success=success,
            snapshot_id=snap.id,
            message=f"systemctl restart {unit} {'ok' if success else 'failed'}",
            duration_ms=duration,
            output=result.stdout,
            error=result.stderr if not success else None,
            rollback_available=False,  # restart isn't really reversible, but the snapshot has pre-state
        )
    except subprocess.TimeoutExpired:
        return RepairResult(
            action="service_restart",
            target=unit,
            success=False,
            snapshot_id=snap.id,
            message="systemctl restart timed out",
            duration_ms=60000,
            error="timeout after 60s",
        )


@register("top_processes_snapshot")
def repair_top_processes_snapshot(top_n: int = 10) -> RepairResult:
    """Capture top-N CPU-consuming processes. SAFE — pure read.

    Useful diagnostic companion to a high-load detection.
    """
    snap = _new_snapshot(
        action="top_processes_snapshot",
        target=f"top_n={top_n}",
        collected_at=datetime.now(timezone.utc).isoformat(),
    )

    start = time.time()
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,user,pcpu,pmem,comm", "--sort=-pcpu"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = result.stdout.strip().split("\n")[: top_n + 1]  # +1 for header
        duration = int((time.time() - start) * 1000)

        snap.metadata["top_processes"] = lines
        snap.save()

        return RepairResult(
            action="top_processes_snapshot",
            target=f"top_n={top_n}",
            success=True,
            snapshot_id=snap.id,
            message=f"Captured top {top_n} processes",
            duration_ms=duration,
            output="\n".join(lines),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        duration = int((time.time() - start) * 1000)
        return RepairResult(
            action="top_processes_snapshot",
            target=f"top_n={top_n}",
            success=False,
            snapshot_id=snap.id,
            message=f"ps failed: {e}",
            duration_ms=duration,
            error=str(e),
        )


@register("notify_human")
def repair_notify_human(channel: str = "all", defcon: int = 4, summary: str = "") -> RepairResult:
    """Send a notification to humans. SAFE — no system changes.

    channel: 'slack' | 'telegram' | 'all'
    """
    snap = _new_snapshot(
        action="notify_human",
        target=f"channel={channel}",
        defcon=defcon,
        summary=summary,
    )
    snap.save()

    # The actual delivery happens in the sweeper pipeline; this just records intent.
    duration = 0
    logger.info(
        "repair_notify_requested",
        channel=channel,
        defcon=defcon,
        snapshot=snap.id,
        summary=summary,
    )
    return RepairResult(
        action="notify_human",
        target=channel,
        success=True,
        snapshot_id=snap.id,
        message=f"Notification queued: defcon={defcon} summary={summary[:80]}",
        duration_ms=duration,
    )


# --- Helpers -----------------------------------------------------------------


def _disk_usage(path: str) -> str:
    """Best-effort disk usage of a path. Returns empty string if unavailable."""
    try:
        usage = shutil.disk_usage(path)
        return f"total={usage.total} used={usage.used} free={usage.free}"
    except (FileNotFoundError, OSError):
        return ""


def _service_state(unit: str) -> str:
    """Capture current state of a systemd unit for snapshot."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "unknown"


# --- Public API --------------------------------------------------------------


def execute_repair(action: str, **kwargs) -> RepairResult:
    """Execute a registered repair action.

    Args:
        action: name from REPAIRS registry
        **kwargs: passed to the repair function

    Returns:
        RepairResult with success/failure + snapshot info
    """
    if action not in REPAIRS:
        return RepairResult(
            action=action,
            target=str(kwargs),
            success=False,
            snapshot_id=None,
            message=f"Unknown repair action: {action}",
            duration_ms=0,
        )

    logger.info("repair_start", action=action, kwargs=kwargs)
    fn = REPAIRS[action]
    # Strip internal-only kwargs (dry_run, force) before calling the repair fn
    internal_kwargs = {"dry_run", "force"}
    fn_kwargs = {k: v for k, v in kwargs.items() if k not in internal_kwargs}
    return fn(**fn_kwargs)


def list_available_repairs() -> list[str]:
    return sorted(REPAIRS.keys())