"""Monitor orchestrator: runs all monitor modules, aggregates status.

This is the entry point for the monitor phase. Each module's collect()
is called; results are combined into one snapshot dict.
"""

from __future__ import annotations

from typing import Any

import structlog

from ipracticom_sweeper import audit
from ipracticom_sweeper.config import load_rules
from ipracticom_sweeper.monitor import aws, cpu, disk, http_check, logs, memory, network, processes, security, services, uptime, health

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

    logger.info(
        "monitor_complete",
        overall=worst,
        modules=list(snapshot["modules"].keys()),
    )

    return snapshot


if __name__ == "__main__":
    import json

    snap = run_all()
    print(json.dumps(snap, indent=2, default=str))