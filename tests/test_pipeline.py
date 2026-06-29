"""Tests for the end-to-end pipeline."""

from unittest.mock import patch

import pytest

from ipracticom_sweeper.pipeline import _extract_repair_kwargs, run_pipeline


@pytest.fixture
def default_rules():
    return {
        "cpu": {
            "load_avg_5min_warn": 2.0,
            "load_avg_5min_crit": 5.0,
            "iowait_percent_warn": 20.0,
        },
        "memory": {
            "used_percent_warn": 80.0,
            "used_percent_crit": 95.0,
            "swap_used_percent_warn": 50.0,
        },
        "disk": {
            "used_percent_warn": 80.0,
            "used_percent_crit": 95.0,
            "read_only_mounts": [],
        },
        "services": {"critical_list": []},
        "security": {
            "failed_ssh_per_min_warn": 5,
            "sudo_failures_per_hour_warn": 3,
        },
    }


@pytest.fixture
def green_snapshot():
    """A snapshot that should produce DEFCON 5 (all good)."""
    return {
        "modules": {
            "cpu": {"values": {"load_5min": 0.5, "iowait_percent": 1.0}, "status": "ok"},
            "memory": {"values": {"ram_used_percent": 30.0, "swap_used_percent": 0.0}, "status": "ok"},
            "disk": {"values": {"mounts": [{"mount": "/", "used_percent": 50.0, "read_only": False}]}, "status": "ok"},
            "services": {"values": {"failed_units": [], "failed_count": 0}, "status": "ok"},
            "security": {"values": {"failed_ssh_per_minute": 0.0, "sudo_failures": 0}, "status": "ok"},
        },
        "overall_status": "ok",
    }


@pytest.fixture
def warn_memory_snapshot():
    """A snapshot where memory hits the warn threshold — triggers drop_caches (GUARDED)."""
    return {
        "modules": {
            "cpu": {"values": {"load_5min": 0.5, "iowait_percent": 1.0}, "status": "ok"},
            "memory": {"values": {"ram_used_percent": 85.0, "swap_used_percent": 0.0}, "status": "warn"},
            "disk": {"values": {"mounts": [{"mount": "/", "used_percent": 50.0, "read_only": False}]}, "status": "ok"},
            "services": {"values": {"failed_units": [], "failed_count": 0}, "status": "ok"},
            "security": {"values": {"failed_ssh_per_minute": 0.0, "sudo_failures": 0}, "status": "ok"},
        },
        "overall_status": "warn",
    }


# --- Dry-run pipeline (no actual repair) ------------------------------------


def test_pipeline_dry_run_no_repairs(default_rules, warn_memory_snapshot):
    """In dry-run mode, we should see suggested repairs but no execution."""
    with patch("ipracticom_sweeper.pipeline.run_monitor", return_value=warn_memory_snapshot):
        result = run_pipeline(default_rules, auto_repair=True, dry_run=True)

    assert result.monitor_overall == "warn"
    assert result.defcon == 4
    assert result.problems_found >= 1
    assert result.repairs_attempted == 0  # dry-run skips
    assert len(result.repair_results) >= 1
    assert all(r.get("dry_run") for r in result.repair_results)


def test_pipeline_auto_repair_off(default_rules, warn_memory_snapshot):
    """With auto_repair=False, no repairs attempted even if suggested."""
    with patch("ipracticom_sweeper.pipeline.run_monitor", return_value=warn_memory_snapshot):
        result = run_pipeline(default_rules, auto_repair=False, dry_run=False)

    assert result.defcon == 4
    assert result.repairs_attempted == 0


# --- Auto-repair path --------------------------------------------------------


def test_pipeline_auto_repair_executes_drop_caches(default_rules, warn_memory_snapshot):
    """When memory hits warn threshold, drop_caches should fire."""
    with patch("ipracticom_sweeper.pipeline.run_monitor", return_value=warn_memory_snapshot):
        with patch("ipracticom_sweeper.pipeline.execute_repair") as mock_execute:
            mock_execute.return_value.success = True
            mock_execute.return_value.action = "drop_caches"
            mock_execute.return_value.target = "level=3"
            mock_execute.return_value.message = "ok"
            mock_execute.return_value.duration_ms = 5
            mock_execute.return_value.snapshot_id = "snap-123"
            mock_execute.return_value.error = None
            mock_execute.return_value.rollback_available = False

            result = run_pipeline(default_rules, auto_repair=True, dry_run=False)

    assert result.repairs_attempted == 1
    assert result.repairs_succeeded == 1
    assert mock_execute.called
    assert mock_execute.call_args[0][0] == "drop_caches"


def test_pipeline_repair_failure_counted(default_rules, warn_memory_snapshot):
    """If a repair fails, we record the failure but don't abort."""
    with patch("ipracticom_sweeper.pipeline.run_monitor", return_value=warn_memory_snapshot):
        with patch("ipracticom_sweeper.pipeline.execute_repair") as mock_execute:
            mock_execute.return_value.success = False
            mock_execute.return_value.action = "drop_caches"
            mock_execute.return_value.target = "level=3"
            mock_execute.return_value.message = "permission denied"
            mock_execute.return_value.duration_ms = 1
            mock_execute.return_value.snapshot_id = None
            mock_execute.return_value.error = "PermissionError"
            mock_execute.return_value.rollback_available = False

            result = run_pipeline(default_rules, auto_repair=True, dry_run=False)

    assert result.repairs_attempted == 1
    assert result.repairs_succeeded == 0
    assert result.repairs_failed == 1


def test_pipeline_repair_exception_caught(default_rules, warn_memory_snapshot):
    """If a repair raises, pipeline logs error and continues."""
    with patch("ipracticom_sweeper.pipeline.run_monitor", return_value=warn_memory_snapshot):
        with patch("ipracticom_sweeper.pipeline.execute_repair", side_effect=RuntimeError("boom")):
            result = run_pipeline(default_rules, auto_repair=True, dry_run=False)

    assert result.repairs_attempted == 1
    assert result.repairs_failed == 1
    assert any("boom" in e for e in result.errors)


# --- Green path --------------------------------------------------------------


def test_pipeline_all_green(default_rules, green_snapshot):
    """When everything is healthy, DEFCON 5 and no repairs."""
    with patch("ipracticom_sweeper.pipeline.run_monitor", return_value=green_snapshot):
        result = run_pipeline(default_rules, auto_repair=True, dry_run=False)

    assert result.defcon == 5
    assert result.defcon_label == "green"
    assert result.problems_found == 0
    assert result.repairs_attempted == 0


# --- Monitor failure ---------------------------------------------------------


def test_pipeline_monitor_failure_returns_defcon_1(default_rules):
    """If monitor itself crashes, we return DEFCON 1 with errors."""
    with patch("ipracticom_sweeper.pipeline.run_monitor", side_effect=RuntimeError("monitor down")):
        result = run_pipeline(default_rules)

    assert result.monitor_overall == "error"
    assert result.defcon == 1
    assert result.defcon_label == "black"
    assert len(result.errors) >= 1


# --- Needs-human path --------------------------------------------------------


def test_pipeline_security_triggers_needs_human(default_rules):
    """SSH brute force = defcon 2, never auto-repair, needs_human > 0."""
    snapshot = {
        "modules": {
            "cpu": {"values": {"load_5min": 0.5, "iowait_percent": 1.0}, "status": "ok"},
            "memory": {"values": {"ram_used_percent": 30.0, "swap_used_percent": 0.0}, "status": "ok"},
            "disk": {"values": {"mounts": [{"mount": "/", "used_percent": 50.0, "read_only": False}]}, "status": "ok"},
            "services": {"values": {"failed_units": [], "failed_count": 0}, "status": "ok"},
            "security": {"values": {"failed_ssh_per_minute": 50.0, "sudo_failures": 0}, "status": "crit"},
        },
        "overall_status": "crit",
    }
    with patch("ipracticom_sweeper.pipeline.run_monitor", return_value=snapshot):
        result = run_pipeline(default_rules, auto_repair=True, dry_run=False)

    assert result.defcon == 2
    assert result.needs_human >= 1
    assert result.repairs_attempted == 0  # security never auto-repair


# --- to_dict -----------------------------------------------------------------


def test_pipeline_result_to_dict(default_rules, green_snapshot):
    with patch("ipracticom_sweeper.pipeline.run_monitor", return_value=green_snapshot):
        result = run_pipeline(default_rules)

    d = result.to_dict()
    assert isinstance(d, dict)
    assert "started_at" in d
    assert "duration_ms" in d
    assert "defcon" in d
    assert "diagnosis" in d
    assert isinstance(d["repair_results"], list)


# --- _extract_repair_kwargs --------------------------------------------------


def test_extract_repair_kwargs_drop_caches():
    kwargs = _extract_repair_kwargs("drop_caches", None)
    assert kwargs == {"level": 3}


def test_extract_repair_kwargs_log_truncate():
    kwargs = _extract_repair_kwargs("log_truncate_journald", None)
    assert kwargs == {"max_age_days": 7}


def test_extract_repair_kwargs_service_restart_with_problem():
    from ipracticom_sweeper.diagnose.engine import Problem, RepairSafety
    problem = Problem(
        module="services",
        kind="service_failed",
        severity="crit",
        detail="nginx failed",
        metrics={"unit": "nginx"},
        suggested_repair="service_restart",
        repair_safety=RepairSafety.GUARDED,
        defcon_at_least=2,
    )
    kwargs = _extract_repair_kwargs("service_restart", problem)
    assert kwargs == {"unit": "nginx"}


def test_extract_repair_kwargs_notify_human():
    from ipracticom_sweeper.diagnose.engine import Problem, RepairSafety
    problem = Problem(
        module="memory",
        kind="memory_critical",
        severity="crit",
        detail="Memory at 96%",
        metrics={"used_percent": 96.0},
        suggested_repair="notify_human",
        repair_safety=RepairSafety.DANGEROUS,
        defcon_at_least=3,
    )
    kwargs = _extract_repair_kwargs("notify_human", problem)
    assert kwargs["channel"] == "all"
    assert kwargs["defcon"] == 3
    assert "Memory" in kwargs["summary"]