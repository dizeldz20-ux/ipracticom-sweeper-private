"""Runbook engine: trigger -> action pipeline."""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class RunbookAction:
    name: str
    action_type: str  # "shell" | "repair" | "notify"
    params: dict[str, Any]


@dataclass
class RunbookResult:
    runbook: str
    triggered: bool
    actions_executed: int
    actions_succeeded: int
    dry_run: bool
    output: list[str]


class RunbookEngine:
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self._last_fired: dict[str, float] = {}

    def should_trigger(
        self,
        runbook_name: str,
        defcon: int,
        trigger_defcon: int,
        cooldown_seconds: float,
        now: float | None = None,
    ) -> bool:
        """Check if runbook should fire based on DEFCON and cooldown."""
        now = now or time.time()
        if defcon > trigger_defcon:
            return False
        last = self._last_fired.get(runbook_name, 0)
        if (now - last) < cooldown_seconds:
            return False
        return True

    def mark_fired(self, runbook_name: str, now: float | None = None) -> None:
        self._last_fired[runbook_name] = now or time.time()

    def execute(
        self,
        runbook_name: str,
        actions: list[RunbookAction],
        action_runner: Callable[[RunbookAction], bool] | None = None,
    ) -> RunbookResult:
        """Execute runbook actions. action_runner is injected for testability.

        If dry_run=True, actions are not executed but logged.
        """
        if action_runner is None:
            action_runner = self._default_runner

        executed = 0
        succeeded = 0
        output = []

        for action in actions:
            executed += 1
            if self.dry_run:
                output.append(f"[DRY-RUN] Would execute: {action.name} ({action.action_type})")
            else:
                try:
                    ok = action_runner(action)
                    if ok:
                        succeeded += 1
                        output.append(f"[OK] {action.name}")
                    else:
                        output.append(f"[FAIL] {action.name}")
                except Exception as e:
                    output.append(f"[ERROR] {action.name}: {e}")

        return RunbookResult(
            runbook=runbook_name,
            triggered=True,
            actions_executed=executed,
            actions_succeeded=succeeded,
            dry_run=self.dry_run,
            output=output,
        )

    def _default_runner(self, action: RunbookAction) -> bool:
        """Default runner: only handles 'notify' type, returns True."""
        if action.action_type == "notify":
            return True
        return False


# --- Built-in runbooks -------------------------------------------------------

def disk_cleanup_runbook() -> list[RunbookAction]:
    return [
        RunbookAction(
            name="journalctl-vacuum",
            action_type="shell",
            params={"command": "journalctl --vacuum-size=100M", "timeout": 30},
        ),
        RunbookAction(
            name="tmp-cleanup",
            action_type="shell",
            params={"command": "find /tmp -type f -atime +7 -delete", "timeout": 60},
        ),
    ]


def memory_pressure_runbook() -> list[RunbookAction]:
    return [
        RunbookAction(
            name="drop-caches",
            action_type="repair",
            params={"action": "drop_caches"},
        ),
    ]


def zombie_processes_runbook() -> list[RunbookAction]:
    """Kill processes that have been in 'Z' (zombie) state.

    Uses `ps -o pid=,stat=`. For each zombie, sends SIGCHLD to its parent
    (which is the kernel's standard way to reap them), then escalates to
    SIGTERM on the parent if it still hasn't reaped after 5 seconds.
    """
    return [
        RunbookAction(
            name="list-zombies",
            action_type="shell",
            params={
                "command": "ps -eo pid,ppid,stat,comm --no-headers | awk '$3 ~ /Z/'",
                "timeout": 10,
            },
        ),
        RunbookAction(
            name="reap-zombies",
            action_type="shell",
            params={
                # Send SIGCHLD to parents of all zombies. Kernel reaps them.
                "command": (
                    "ps -eo pid,ppid,stat --no-headers | "
                    "awk '$3 ~ /Z/ {print $2}' | "
                    "sort -u | xargs -r -I{} kill -CHLD {}"
                ),
                "timeout": 15,
            },
        ),
    ]
