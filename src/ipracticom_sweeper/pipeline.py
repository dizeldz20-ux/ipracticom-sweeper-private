"""End-to-end pipeline: monitor → adapt → diagnose → execute repairs.

This is the orchestrator that ties all layers together. It:

  1. Runs monitor (read-only metrics)
  2. Adapts the snapshot for diagnose
  3. Runs diagnose to get a Diagnosis
  4. Iterates over Diagnosis.safe_repairs and executes them
  5. Sends notifications for problems that need_human
  6. Logs everything to audit

The pipeline is idempotent: running twice produces the same result given
the same host state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from ipracticom_sweeper.config import get_server_id, load_rules
from ipracticom_sweeper.diagnose import diagnose
from ipracticom_sweeper.diagnose.adapter import adapt_for_diagnose
from ipracticom_sweeper.monitor.checks import run_all as run_monitor
from ipracticom_sweeper.repair import execute_repair
from ipracticom_sweeper.repair.policy import load_policy, needs_approval
from ipracticom_sweeper.repair.pending import create_proposal, log_audit

logger = structlog.get_logger()


@dataclass
class PipelineResult:
    """Outcome of a full monitor→diagnose→repair cycle."""

    started_at: str
    finished_at: str
    duration_ms: int
    monitor_overall: str
    defcon: int
    defcon_label: str
    problems_found: int
    repairs_attempted: int
    repairs_succeeded: int
    repairs_failed: int
    needs_human: int
    repair_results: list[dict[str, Any]] = field(default_factory=list)
    diagnosis: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "monitor_overall": self.monitor_overall,
            "defcon": self.defcon,
            "defcon_label": self.defcon_label,
            "problems_found": self.problems_found,
            "repairs_attempted": self.repairs_attempted,
            "repairs_succeeded": self.repairs_succeeded,
            "repairs_failed": self.repairs_failed,
            "needs_human": self.needs_human,
            "repair_results": self.repair_results,
            "diagnosis": self.diagnosis,
            "errors": self.errors,
        }


def run_pipeline(
    rules: dict | None = None,
    *,
    auto_repair: bool = True,
    dry_run: bool = False,
) -> PipelineResult:
    """Execute the full sweep cycle.

    Args:
        rules: threshold rules (loads defaults if None)
        auto_repair: if True, execute SAFE/GUARDED repairs; if False, only diagnose
        dry_run: if True, don't actually execute repairs (log intent only)

    Returns:
        PipelineResult with full telemetry
    """
    rules = rules or load_rules()
    started_at = datetime.now(timezone.utc).isoformat()
    start_ts = time.time()
    errors: list[str] = []

    # --- Step 1: Monitor ---
    logger.info("pipeline_step", step="monitor")
    try:
        snap = run_monitor(rules)
        monitor_overall = snap.get("overall_status", "unknown")
    except Exception as e:
        logger.error("pipeline_monitor_failed", error=str(e))
        # v1.5.8 fix: write the heartbeat even on monitor failure so the
        # next check_health() doesn't falsely flag the agent as stale.
        # (Previously the heartbeat was only written on the success path.)
        try:
            from ipracticom_sweeper.monitor.health import record_run
            record_run(defcon=1, problems_found=0, repairs_attempted=0)
        except Exception as hb_exc:
            logger.warning("heartbeat_write_failed", error=str(hb_exc))
        return PipelineResult(
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int((time.time() - start_ts) * 1000),
            monitor_overall="error",
            defcon=1,  # unknown state = treat as black
            defcon_label="black",
            problems_found=0,
            repairs_attempted=0,
            repairs_succeeded=0,
            repairs_failed=0,
            needs_human=0,
            errors=[f"monitor_failed: {e}"],
        )

    # --- Step 2: Adapt ---
    logger.info("pipeline_step", step="adapt")
    findings = adapt_for_diagnose(snap)

    # Build a compact modules summary for dashboard consumption
    # (preserve status from monitor, not from diagnose).
    modules_summary = {}
    for mod_name, mod_data in snap.get("modules", {}).items():
        modules_summary[mod_name] = {
            "status": mod_data.get("status", "unknown"),
            "values": mod_data.get("values", {}),
        }

    # --- Step 3: Diagnose ---
    logger.info("pipeline_step", step="diagnose")
    diagnosis = diagnose(findings, rules)
    diagnosis_dict = diagnosis.to_dict()
    # Inject monitor modules status so dashboard can show them
    diagnosis_dict["modules"] = modules_summary

    # --- Step 4: Repairs ---
    repair_results: list[dict[str, Any]] = []
    repairs_attempted = 0
    repairs_succeeded = 0
    repairs_failed = 0

    if auto_repair and diagnosis.safe_repairs:
        policy = load_policy()
        for repair_action in diagnosis.safe_repairs:
            # Find the problem that suggested this repair (for context)
            problem_for_action = next(
                (p for p in diagnosis.problems if p.suggested_repair == repair_action),
                None,
            )

            # Extract kwargs from the problem if needed
            kwargs = _extract_repair_kwargs(repair_action, problem_for_action)

            logger.info(
                "pipeline_repair_start",
                action=repair_action,
                dry_run=dry_run,
                kwargs=kwargs,
            )

            if dry_run:
                repair_results.append({
                    "action": repair_action,
                    "dry_run": True,
                    "kwargs": kwargs,
                    "skipped_reason": "dry_run",
                })
                continue

            # Approval gate: write proposal for sensitive repairs instead of
            # executing immediately. The operator reviews and approves via
            # the /approvals UI.
            if needs_approval(repair_action, policy):
                try:
                    reason = (
                        problem_for_action.detail
                        if problem_for_action
                        else f"diagnose suggested {repair_action}"
                    )
                    problem_dict = (
                        {
                            "kind": problem_for_action.kind,
                            "severity": problem_for_action.severity,
                            "detail": problem_for_action.detail,
                            "metrics": problem_for_action.metrics,
                        }
                        if problem_for_action
                        else None
                    )
                    proposed_cmd = _render_repair_command(repair_action, kwargs)
                    proposal = create_proposal(
                        action=repair_action,
                        kwargs=kwargs,
                        reason=reason,
                        problem=problem_dict,
                        proposed_command=proposed_cmd,
                    )
                    repair_results.append({
                        "action": repair_action,
                        "dry_run": False,
                        "kwargs": kwargs,
                        "status": "awaiting_approval",
                        "proposal_id": proposal.id,
                        "reason": reason,
                        "proposed_command": proposed_cmd,
                    })
                    log_audit({
                        "kind": "repair_proposed",
                        "action": repair_action,
                        "kwargs": kwargs,
                        "proposal_id": proposal.id,
                        "reason": reason,
                    })
                except Exception as e:
                    errors.append(f"repair_{repair_action}_proposal_failed: {e}")
                    logger.error("pipeline_proposal_exception", action=repair_action, error=str(e))
                continue

            repairs_attempted += 1
            try:
                result = execute_repair(repair_action, **kwargs)
                repair_results.append({
                    "action": result.action,
                    "target": result.target,
                    "success": result.success,
                    "message": result.message,
                    "duration_ms": result.duration_ms,
                    "snapshot_id": result.snapshot_id,
                    "error": result.error,
                    "rollback_available": result.rollback_available,
                })
                if result.success:
                    repairs_succeeded += 1
                else:
                    repairs_failed += 1
                log_audit({
                    "kind": "repair_executed",
                    "actor": "auto",
                    "action": result.action,
                    "target": result.target,
                    "success": result.success,
                    "duration_ms": result.duration_ms,
                    "snapshot_id": result.snapshot_id,
                    "error": result.error,
                    "message": result.message,
                })
            except Exception as e:
                repairs_failed += 1
                errors.append(f"repair_{repair_action}_exception: {e}")
                logger.error("pipeline_repair_exception", action=repair_action, error=str(e))
                log_audit({
                    "kind": "repair_failed",
                    "actor": "auto",
                    "action": repair_action,
                    "kwargs": kwargs,
                    "error": str(e),
                })

    finished_at = datetime.now(timezone.utc).isoformat()
    duration_ms = int((time.time() - start_ts) * 1000)

    result = PipelineResult(
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        monitor_overall=monitor_overall,
        defcon=diagnosis.defcon,
        defcon_label=diagnosis.defcon_label,
        problems_found=len(diagnosis.problems),
        repairs_attempted=repairs_attempted,
        repairs_succeeded=repairs_succeeded,
        repairs_failed=repairs_failed,
        needs_human=len(diagnosis.needs_human),
        repair_results=repair_results,
        diagnosis=diagnosis_dict,
        errors=errors,
    )

    # --- Step 5: Notify (now that result exists) ---
    # Skip notify entirely when green and not forced. This keeps green runs quiet.
    notify_payload = _build_notify_payload(result)
    if notify_payload is not None and result.defcon < 5:
        try:
            import asyncio
            from ipracticom_sweeper.notify import notify_pipeline_result

            notify_results = asyncio.run(notify_pipeline_result(notify_payload))
            if notify_results:
                logger.info("pipeline_notified", channels=notify_results)
        except Exception as e:
            logger.warning("pipeline_notify_failed", error=str(e))

    # --- Step 6: Always log needs_human ---
    if diagnosis.needs_human:
        logger.warning(
            "pipeline_needs_human",
            count=len(diagnosis.needs_human),
            kinds=[p.kind for p in diagnosis.needs_human],
        )

    logger.info(
        "pipeline_complete",
        duration_ms=duration_ms,
        defcon=diagnosis.defcon,
        problems=len(diagnosis.problems),
        repairs=repairs_attempted,
        succeeded=repairs_succeeded,
    )

    # Record heartbeat so the next run can see we ran.
    # We do this even on monitor-failed returns so a partial run still counts.
    try:
        from ipracticom_sweeper.monitor.health import record_run
        record_run(
            defcon=diagnosis.defcon,
            problems_found=len(diagnosis.problems),
            repairs_attempted=repairs_attempted,
        )
    except Exception as e:
        logger.warning("heartbeat_write_failed", error=str(e))

    return result


def _build_notify_payload(result) -> dict | None:
    """Build the dict that gets sent to Slack/Telegram.

    Includes server identity. Returns None if no channels configured.
    """
    try:
        server_id = get_server_id()
    except Exception:
        server_id = "unknown"

    payload = result.to_dict()
    payload["server"] = server_id
    return payload


def _extract_repair_kwargs(action: str, problem) -> dict:
    """Extract kwargs for a repair action from its triggering problem.

    Currently uses sensible defaults — could be enriched with problem.metrics.
    """
    if action == "drop_caches":
        return {"level": 3}
    elif action == "log_truncate_journald":
        return {"max_age_days": 7}
    elif action == "service_restart" and problem and "unit" in problem.metrics:
        return {"unit": problem.metrics["unit"]}
    elif action == "service_restart":
        return {"unit": "nginx"}  # fallback
    elif action == "top_processes_snapshot":
        return {"top_n": 10}
    elif action == "notify_human":
        return {
            "channel": "all",
            "defcon": problem.defcon_at_least if problem else 4,
            "summary": problem.detail if problem else "issue detected",
        }
    return {}


def _render_repair_command(action: str, kwargs: dict) -> str:
    """Render a human-readable description of what an approved repair will do.

    Used in the /approvals UI so the operator can see the exact side effect
    before clicking "Approve". Not a shell command — a description.
    """
    if action == "service_restart":
        unit = kwargs.get("unit", "<unit>")
        return (
            f"systemctl restart {unit}\n"
            f"  → service '{unit}' will be briefly unavailable (~5-15s)\n"
            f"  → a snapshot of the unit state is taken beforehand (rollback available)"
        )
    if action == "drop_caches":
        level = kwargs.get("level", 3)
        scope = {1: "pagecache only", 2: "pagecache + dentries", 3: "pagecache + dentries + inodes"}.get(level, "all")
        return (
            f"echo {level} > /proc/sys/vm/drop_caches\n"
            f"  → drops {scope} from kernel reclaimable memory\n"
            f"  → SAFE: only frees reclaimable memory, does not destroy data"
        )
    if action == "log_truncate_journald":
        days = kwargs.get("max_age_days", 7)
        return (
            f"journalctl --vacuum-time={days}d\n"
            f"  → removes journal entries older than {days} days\n"
            f"  → IRREVERSIBLE: log data older than {days}d is deleted"
        )
    if action == "top_processes_snapshot":
        n = kwargs.get("top_n", 10)
        return f"ps aux --sort=-%cpu | head -{n + 1}\n  → READ-ONLY diagnostic snapshot"
    if action == "notify_human":
        channel = kwargs.get("channel", "all")
        return f"send notification to {channel} channels (Slack/Telegram)"
    return f"{action}({kwargs})"