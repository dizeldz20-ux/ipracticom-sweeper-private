"""Tests for the audit/logger module — emit() and helper event types."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ipracticom_sweeper.audit import logger as audit_logger
from ipracticom_sweeper.audit.logger import (
    emit,
    monitor_event,
    alert_event,
    repair_event,
    _iso_now,
)
from pathlib import Path as _PathAlias  # noqa: E402


@pytest.fixture
def tmp_audit_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the audit log to a tmp file via env var."""
    audit_file = tmp_path / "audit.jsonl"
    # Patch the module-level constants
    monkeypatch.setattr(audit_logger, "AUDIT_LOG_DIR", tmp_path)
    monkeypatch.setattr(audit_logger, "AUDIT_LOG_FILE", audit_file)
    return audit_file


def _read_lines(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


# ============= emit() ======================================================

def test_emit_writes_jsonl(tmp_audit_dir: Path) -> None:
    emit("test.event", {"a": 1})
    lines = _read_lines(tmp_audit_dir)
    assert len(lines) == 1
    assert lines[0]["event"] == "test.event"
    assert lines[0]["payload"] == {"a": 1}


def test_emit_record_has_required_fields(tmp_audit_dir: Path) -> None:
    emit("x", {"k": "v"})
    rec = _read_lines(tmp_audit_dir)[0]
    assert "ts" in rec
    assert "ts_iso" in rec
    assert "server" in rec
    assert "event" in rec
    assert "severity" in rec
    assert "payload" in rec


def test_emit_appends_not_overwrites(tmp_audit_dir: Path) -> None:
    emit("first", {})
    emit("second", {})
    lines = _read_lines(tmp_audit_dir)
    assert len(lines) == 2
    assert lines[0]["event"] == "first"
    assert lines[1]["event"] == "second"


def test_emit_severity_default_is_info(tmp_audit_dir: Path) -> None:
    emit("x", {})
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["severity"] == "info"


def test_emit_severity_explicit(tmp_audit_dir: Path) -> None:
    emit("x", {}, severity="critical")
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["severity"] == "critical"


def test_emit_uses_utc_iso_timestamp(tmp_audit_dir: Path) -> None:
    emit("x", {})
    rec = _read_lines(tmp_audit_dir)[0]
    iso = rec["ts_iso"]
    # Should end with +00:00 (UTC) or Z
    assert iso.endswith("+00:00") or iso.endswith("Z")


def test_emit_handles_non_serializable_payload(tmp_audit_dir: Path) -> None:
    """Non-JSON-serializable payload is swallowed (logger.error, no crash)."""
    class BadObj:
        pass
    # Should NOT raise — emit() catches the JSON error in its write block
    emit("x", {"obj": BadObj()})
    # Nothing was written to the audit log
    assert not tmp_audit_dir.exists() or tmp_audit_dir.read_text() == ""


# ============= monitor_event ===============================================

def test_monitor_event_ok_severity_debug(tmp_audit_dir: Path) -> None:
    monitor_event("cpu", {"value": 50}, "ok")
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["event"] == "monitor.cpu"
    assert rec["severity"] == "debug"
    assert rec["payload"]["status"] == "ok"


def test_monitor_event_warn_severity(tmp_audit_dir: Path) -> None:
    monitor_event("mem", {"pct": 85}, "warn")
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["severity"] == "warn"


def test_monitor_event_crit_severity(tmp_audit_dir: Path) -> None:
    monitor_event("disk", {"pct": 95}, "crit")
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["severity"] == "error"


def test_monitor_event_unknown_status_is_info(tmp_audit_dir: Path) -> None:
    monitor_event("x", {}, "weird_status")
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["severity"] == "info"


# ============= alert_event =================================================

def test_alert_event_default_critical(tmp_audit_dir: Path) -> None:
    alert_event("slack", {"msg": "hi"})
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["event"] == "alert.slack"
    assert rec["severity"] == "critical"


def test_alert_event_explicit_severity(tmp_audit_dir: Path) -> None:
    alert_event("telegram", {"x": 1}, severity="warn")
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["severity"] == "warn"


# ============= repair_event ================================================

def test_repair_event_success_is_info(tmp_audit_dir: Path) -> None:
    repair_event("drop_caches", "level=3", "success")
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["event"] == "repair.drop_caches"
    assert rec["severity"] == "info"
    assert rec["payload"]["result"] == "success"


def test_repair_event_failed_is_warn(tmp_audit_dir: Path) -> None:
    repair_event("service_restart", "unit=x", "failed")
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["severity"] == "warn"


def test_repair_event_target_in_payload(tmp_audit_dir: Path) -> None:
    repair_event("drop_caches", "level=2", "success")
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["payload"]["target"] == "level=2"


def test_repair_event_details_default_empty_dict(tmp_audit_dir: Path) -> None:
    repair_event("x", "y", "success")
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["payload"]["details"] == {}


def test_repair_event_explicit_details(tmp_audit_dir: Path) -> None:
    repair_event("x", "y", "success", details={"k": "v"})
    rec = _read_lines(tmp_audit_dir)[0]
    assert rec["payload"]["details"] == {"k": "v"}


# ============= _iso_now ====================================================

def test_iso_now_is_string() -> None:
    assert isinstance(_iso_now(), str)


def test_iso_now_has_t_separator() -> None:
    iso = _iso_now()
    # ISO 8601 has 'T' between date and time
    assert "T" in iso


# ============= PermissionError fallback =====================================

def test_emit_falls_back_on_permission_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the primary open fails with OSError, emit() doesn't crash."""
    # Set the primary path to a known file we can target
    monkeypatch.setattr(audit_logger, "AUDIT_LOG_FILE", Path("/nonexistent/audit.jsonl"))
    # Should not raise — emit() catches OSError and falls back or logs
    emit("test.event", {"x": 1})