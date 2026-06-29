"""Repair layer — execute and audit repair actions.

Public API:
    execute_repair(action, **kwargs) -> RepairResult
    list_available_repairs() -> list[str]
"""

from ipracticom_sweeper.repair.actions import (
    REPAIRS,
    RepairResult,
    Snapshot,
    execute_repair,
    list_available_repairs,
    repair_drop_caches,
    repair_log_truncate_journald,
    repair_notify_human,
    repair_service_restart,
    repair_top_processes_snapshot,
)

__all__ = [
    "REPAIRS",
    "RepairResult",
    "Snapshot",
    "execute_repair",
    "list_available_repairs",
    "repair_drop_caches",
    "repair_log_truncate_journald",
    "repair_notify_human",
    "repair_service_restart",
    "repair_top_processes_snapshot",
]