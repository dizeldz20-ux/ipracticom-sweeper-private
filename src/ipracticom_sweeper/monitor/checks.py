"""Monitor orchestrator: runs all monitor modules, aggregates status.

This is the entry point for the monitor phase. Each module's collect()
is called; results are combined into one snapshot dict.
"""

from __future__ import annotations

from typing import Any
import shutil
import time
from pathlib import Path

import structlog

from ipracticom_sweeper import audit
from ipracticom_sweeper.config import load_rules
from ipracticom_sweeper.monitor import aide_check, aws, cpu, disk, fd_check, http_check, iostat, kernel_errors, logs, memory, network, process_tracker, processes, security, services, smart_check, ssl_check, uptime, health

logger = structlog.get_logger()


def run_all(rules: dict | None = None) -> dict[str, Any]:
    """Run every monitor module; return aggregated snapshot."""
    rules = rules or load_rules()
    snapshot: dict[str, Any] = {"modules": {}}

    # CPU
    cpu_values = cpu.collect()
    cpu_status = cpu.evaluate(cpu_values, rules)
    snapshot["modules"]["cpu"] = {"values": cpu_values, "status": cpu_status}
    audit.monitor_event("cpu", cpu_values, cpu_status)

    # Memory
    mem_values = memory.collect()
    mem_status = memory.evaluate(mem_values, rules)
    snapshot["modules"]["memory"] = {"values": mem_values, "status": mem_status}
    audit.monitor_event("memory", mem_values, mem_status)

    # Disk
    disk_values = disk.collect()
    disk_status = disk.evaluate(disk_values, rules)
    snapshot["modules"]["disk"] = {"values": disk_values, "status": disk_status}
    audit.monitor_event("disk", disk_values, disk_status)

    # Network
    net_values = network.collect()
    net_status = network.evaluate(net_values, rules)
    snapshot["modules"]["network"] = {"values": net_values, "status": net_status}
    audit.monitor_event("network", net_values, net_status)

    # Services
    svc_values = services.collect(rules["services"].get("critical_list", []))
    svc_status = services.evaluate(svc_values, rules)
    snapshot["modules"]["services"] = {"values": svc_values, "status": svc_status}
    audit.monitor_event("services", svc_values, svc_status)

    # Logs
    log_values = logs.collect(rules)
    log_status = logs.evaluate(log_values, rules)
    snapshot["modules"]["logs"] = {"values": log_values, "status": log_status}
    audit.monitor_event("logs", log_values, log_status)

    # Processes
    proc_values = processes.collect()
    proc_status = processes.evaluate(proc_values, rules)
    snapshot["modules"]["processes"] = {"values": proc_values, "status": proc_status}
    audit.monitor_event("processes", proc_values, proc_status)

    # Security
    sec_values = security.collect(rules)
    sec_status = security.evaluate(sec_values, rules)
    snapshot["modules"]["security"] = {"values": sec_values, "status": sec_status}
    audit.monitor_event("security", sec_values, sec_status)

    # AWS
    aws_values = aws.collect()
    aws_status = aws.evaluate(aws_values, rules)
    snapshot["modules"]["aws"] = {"values": aws_values, "status": aws_status}
    # Only audit AWS if data is available
    if aws_values.get("available"):
        audit.monitor_event("aws", aws_values, aws_status)

    # HTTP endpoints (graceful if no endpoints configured)
    http_endpoints = rules.get("http", {}).get("endpoints", [])
    if http_endpoints:
        http_results = http_check.collect_http_endpoints(http_endpoints)
        http_values = {"endpoints": [r.to_dict() for r in http_results]}
        http_status = http_check.evaluate(http_values, rules)
        snapshot["modules"]["http"] = {"values": http_values, "status": http_status}
        audit.monitor_event("http", http_values, http_status)

    # SSL cert expiry (graceful if no hosts configured)
    ssl_hosts = rules.get("ssl", {}).get("hosts", [])
    if ssl_hosts:
        ssl_results = ssl_check.collect_ssl_certs(ssl_hosts)
        ssl_values = {"certificates": [r.to_dict() for r in ssl_results]}
        ssl_status = ssl_check.evaluate(ssl_values, rules)
        snapshot["modules"]["ssl"] = {"values": ssl_values, "status": ssl_status}
        audit.monitor_event("ssl", ssl_values, ssl_status)

    # SMART disk health (graceful if smartctl missing or no devices)
    smart_devices = rules.get("smart", {}).get("devices", [])
    if smart_devices:
        smart_results = smart_check.collect_smart_health(smart_devices)
        if smart_results:
            smart_values = {"disks": [r.to_dict() for r in smart_results]}
            smart_status = smart_check.evaluate(smart_values, rules)
            snapshot["modules"]["smart"] = {"values": smart_values, "status": smart_status}
            audit.monitor_event("smart", smart_values, smart_status)

    # Kernel errors (Oops, MCE, segfaults) — always on, low cost
    kernel_window = rules.get("kernel", {}).get("window_minutes", 5)
    kernel_values = kernel_errors.collect_kernel_errors(window_minutes=kernel_window)
    kernel_status = kernel_errors.evaluate(kernel_values, rules)
    snapshot["modules"]["kernel"] = {"values": kernel_values, "status": kernel_status}
    audit.monitor_event("kernel", kernel_values, kernel_status)

    # I/O latency per device (iostat) — graceful if binary missing
    if shutil.which("iostat"):
        io_devices = iostat.collect_iostat()
        if io_devices:
            io_values = {"devices": [d.to_dict() for d in io_devices]}
            io_status = iostat.evaluate(io_values, rules)
            snapshot["modules"]["iostat"] = {"values": io_values, "status": io_status}
            audit.monitor_event("iostat", io_values, io_status)

    # Process tracker: top-N resource hogs + service restart counter
    pt_window = rules.get("process_tracker", {}).get("window_minutes", 60)
    pt_top_n = rules.get("process_tracker", {}).get("top_n", 10)
    pt_top = process_tracker.get_top_processes(top_n=pt_top_n)
    pt_restarts = process_tracker.collect_service_restarts(window_minutes=pt_window)
    pt_values = {
        "top_processes": [p.to_dict() for p in pt_top],
        "service_restarts": [r.to_dict() for r in pt_restarts],
        "window_minutes": pt_window,
    }
    pt_status = process_tracker.evaluate(pt_values, rules)
    snapshot["modules"]["process_tracker"] = {"values": pt_values, "status": pt_status}
    audit.monitor_event("process_tracker", pt_values, pt_status)

    # File descriptor monitor — system-wide + top-N consumers
    fd_top_n = rules.get("fd_check", {}).get("top_n", 5)
    fd_values = {
        "system": fd_check.collect_fd_system().to_dict(),
        "top_processes": fd_check.collect_top_fd_processes(top_n=fd_top_n),
    }
    fd_status = fd_check.evaluate(fd_values, rules)
    snapshot["modules"]["fd_check"] = {"values": fd_values, "status": fd_status}
    audit.monitor_event("fd_check", fd_values, fd_status)

    # AIDE file integrity (graceful if not installed or no baseline)
    if shutil.which("aide"):
        aide_report = aide_check.collect_aide_report()
        aide_values = aide_report.to_dict()
        aide_status = aide_check.evaluate(aide_values, rules)
        snapshot["modules"]["aide"] = {"values": aide_values, "status": aide_status}
        audit.monitor_event("aide", aide_values, aide_status)

    # Uptime / boot time
    up_values = uptime.collect()
    up_status = uptime.evaluate(up_values, rules)
    snapshot["modules"]["uptime"] = {"values": up_values, "status": up_status}
    audit.monitor_event("uptime", up_values, up_status)

    # Agent self-health (heartbeat)
    # The heartbeat is written AFTER this run completes, so on the first run
    # we'll see "missing" — that's expected and we record it but don't alert.
    health_values = health.collect()
    health_status = health.evaluate(health_values, rules)
    # Don't alert "missing" on the first ever run — that's the agent itself.
    if health_values.get("state") == "missing" and health_values.get("last_run_ts") is None:
        # Suppress first-run noise; record as ok so overall isn't degraded
        health_status = "ok"
    snapshot["modules"]["health"] = {"values": health_values, "status": health_status}
    audit.monitor_event("health", health_values, health_status)

    # Compute overall status (worst wins)
    rank = {"ok": 0, "warn": 1, "crit": 2}
    worst = "ok"
    for mod_data in snapshot["modules"].values():
        worst = mod_data["status"] if rank[mod_data["status"]] > rank[worst] else worst
    snapshot["overall_status"] = worst

    # Persist numeric metrics to local time-series DB (graceful if disabled)
    _persist_to_timeseries(snapshot, rules)

    logger.info(
        "monitor_complete",
        overall=worst,
        modules=list(snapshot["modules"].keys()),
    )

    return snapshot


def _persist_to_timeseries(snapshot: dict, rules: dict) -> None:
    """Write key numeric metrics to the local time-series DB.

    Extracts a small set of high-signal scalars (defcon, CPU%, memory%,
    disk% per mount, FD%, overall_status as numeric) and appends them
    to the SQLite store. The agent_api /api/history endpoint reads
    from the same store.

    Storage path comes from IPRACTICOM_SWEEPER_STATE_DIR env var
    (default /var/lib/ipracticom-sweeper), consistent with other state.
    """
    storage_cfg = rules.get("storage", {})
    if not storage_cfg.get("enabled", True):
        return
    retention_days = storage_cfg.get("retention_days", 30)

    import os
    from ipracticom_sweeper.storage import TimeSeriesDB
    state_dir = Path(os.environ.get(
        "IPRACTICOM_SWEEPER_STATE_DIR",
        "/var/lib/ipracticom-sweeper",
    ))
    try:
        db = TimeSeriesDB(state_dir / "metrics.db", retention_days=retention_days)
    except (OSError, PermissionError) as e:
        # No write permission (e.g. dev env) — skip silently
        logger.debug("timeseries_init_skipped", error=str(e))
        return

    host = os.environ.get("IPRACTICOM_SWEEPER_HOST_ID", "localhost")
    now = int(time.time())

    # Overall defcon → store as int 1-5
    defcon = _defcon_to_int(snapshot.get("overall_status", "ok"))
    try:
        db.write(host=host, metric="agent.defcon", value=defcon, ts=now)
    except Exception as e:
        logger.debug("timeseries_write_skipped", metric="agent.defcon", error=str(e))

    # Per-module numeric metrics
    metrics_to_persist = [
        ("cpu", "cpu.idle_percent"),
        ("cpu", "cpu.load_5min"),
        ("memory", "memory.used_percent"),
        ("disk", "disk.used_percent"),
        ("fd_check", "fd_check.used_percent"),
        ("process_tracker", "process_tracker.cpu_top"),
        ("process_tracker", "process_tracker.mem_top"),
    ]
    for module_key, metric_name in metrics_to_persist:
        mod_data = snapshot.get("modules", {}).get(module_key)
        if not mod_data:
            continue
        value = _extract_scalar_metric(mod_data.get("values", {}), metric_name)
        if value is None:
            continue
        try:
            db.write(host=host, metric=metric_name, value=float(value), ts=now)
        except Exception as e:
            logger.debug("timeseries_write_skipped", metric=metric_name, error=str(e))

    # Per-mount disk% (one row per mount)
    disk_data = snapshot.get("modules", {}).get("disk", {}).get("values", {})
    for mount in disk_data.get("mounts", []) or []:
        mountpoint = mount.get("mountpoint") or mount.get("target")
        used = mount.get("used_percent")
        if not mountpoint or used is None:
            continue
        try:
            db.write(
                host=host,
                metric=f"disk.used_percent.{mountpoint}",
                value=float(used),
                ts=now,
            )
        except Exception as e:
            logger.debug("timeseries_write_skipped", metric=f"disk.{mountpoint}", error=str(e))

    db.close()


def _defcon_to_int(overall: str) -> int:
    """Map overall status string to a numeric 1-5 (lower = worse)."""
    return {"ok": 5, "warn": 4, "crit": 2}.get(overall, 3)


def _extract_scalar_metric(values: dict, dotted_key: str) -> float | None:
    """Pull a scalar numeric value out of a module's values dict.

    dotted_key uses dots for nested access. Returns None if not found
    or not numeric.
    """
    cur = values
    for part in dotted_key.split(".")[1:]:  # skip module prefix
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    try:
        return float(cur)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    import json

    snap = run_all()
    print(json.dumps(snap, indent=2, default=str))