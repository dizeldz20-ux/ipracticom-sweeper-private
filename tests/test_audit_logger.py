"""Tests for the audit logger module."""

import json
from pathlib import Path

import pytest

from ipracticom_sweeper.audit import emit, monitor_event, repair_event


@pytest.fixture
def tmp_audit_log(tmp_path, monkeypatch):
    """Redirect AUDIT_LOG_FILE to a temp path for isolation."""
    from ipracticom_sweeper.audit import logger as audit_logger

    log_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_logger, "AUDIT_LOG_FILE", log_path)
    return log_path


def test_emit_writes_jsonl_record(tmp_audit_log):
    emit("test.event", {"foo": "bar"}, "info")
    assert tmp_audit_log.exists()
    line = tmp_audit_log.read_text().strip()
    record = json.loads(line)
    assert record["event"] == "test.event"
    assert record["payload"] == {"foo": "bar"}
    assert record["severity"] == "info"
    assert "ts" in record
    assert "server" in record


def test_monitor_event_uses_correct_severity(tmp_audit_log):
    monitor_event("cpu", {"load": 1.0}, "warn")
    record = json.loads(tmp_audit_log.read_text().strip())
    assert record["severity"] == "warn"


def test_monitor_event_crit_maps_to_error_severity(tmp_audit_log):
    monitor_event("memory", {"used": 99}, "crit")
    record = json.loads(tmp_audit_log.read_text().strip())
    assert record["severity"] == "error"


def test_repair_event_success(tmp_audit_log):
    repair_event("disk_cleanup", "/var/log", "success", {"freed_mb": 100})
    record = json.loads(tmp_audit_log.read_text().strip())
    assert record["event"] == "repair.disk_cleanup"
    assert record["payload"]["result"] == "success"
    assert record["payload"]["details"]["freed_mb"] == 100


def test_repair_event_failed_is_warn_severity(tmp_audit_log):
    repair_event("service_restart", "nginx", "failed", {"error": "timeout"})
    record = json.loads(tmp_audit_log.read_text().strip())
    assert record["severity"] == "warn"