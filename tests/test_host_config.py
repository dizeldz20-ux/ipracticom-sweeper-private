"""Sprint v1.3.0 Slice 1 — HostConfig schema + YAML + SQLite cache."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from ipracticom_sweeper.config import host_config as hc
from ipracticom_sweeper.config.host_config import (
    HostConfig, MonitorConfig, RepairConfig, RunbookConfig, Suppression,
    load_host, save_host, get_host, list_hosts, list_all_hosts, delete_host,
)
from ipracticom_sweeper.config.paths import ROOT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    """Point every paths.* helper at a tmp dir for the duration of the test."""
    monkeypatch.setenv("IPRACTICOM_SWEEPER_STATE_DIR", str(tmp_path))
    ROOT.cache_clear()
    # Also blow away the module-level SQLite path cache
    hc._DB_PATH = None
    yield tmp_path
    ROOT.cache_clear()
    hc._DB_PATH = None


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------

def test_30_1_save_then_load_round_trip():
    cfg = HostConfig(
        name="fs-prod-1",
        description="primary",
        monitors=[MonitorConfig(name="disk_check", enabled=True,
                                interval_sec=30, settings={"threshold_pct": 85})],
        repairs=[RepairConfig(name="drop_caches", enabled=True,
                              require_approval=False)],
        runbooks=[RunbookConfig(name="cpu_saturation", enabled=True)],
        suppressions=[Suppression(rule="ntp_check", until=None,
                                  reason="isolated VLAN")],
    )
    path = save_host(cfg)
    assert path.exists()
    loaded = load_host("fs-prod-1")
    assert loaded.name == "fs-prod-1"
    assert loaded.description == "primary"
    assert loaded.monitor("disk_check").settings["threshold_pct"] == 85
    assert loaded.monitor("disk_check").interval_sec == 30
    assert loaded.repair("drop_caches").require_approval is False
    assert loaded.runbook("cpu_saturation").enabled is True
    assert loaded.is_suppressed("ntp_check")[0] is True
    assert loaded.is_suppressed("disk_check")[0] is False


def test_30_1_load_missing_returns_default():
    cfg = load_host("never-configured")
    assert cfg.name == "never-configured"
    assert cfg.monitors == []
    assert cfg.repairs == []
    assert cfg.enabled is True


def test_30_1_invalid_host_name_rejected():
    with pytest.raises(ValueError):
        _host_path = hc._host_yaml_path("../etc/passwd")
        # If the sanitize logic ever loosens, this should fail loud
        assert ".." in _host_path.name or "/" in str(_host_path)


def test_30_1_save_is_atomic(tmp_path):
    """Save should not leave .tmp files behind on success."""
    cfg = HostConfig(name="atomic-test", monitors=[
        MonitorConfig(name="disk_check"),
    ])
    path = save_host(cfg)
    assert path.exists()
    assert not path.with_suffix(".yaml.tmp").exists()


def test_30_1_yaml_is_human_readable():
    cfg = HostConfig(
        name="readable",
        monitors=[MonitorConfig(name="disk_check", enabled=False)],
    )
    save_host(cfg)
    text = (ROOT() / "hosts" / "readable.yaml").read_text()
    # Should be readable plain YAML, not JSON
    assert "name: readable" in text
    assert "monitors:" in text
    # Re-parse and compare
    parsed = yaml.safe_load(text)
    assert parsed["host"]["name"] == "readable"
    assert parsed["monitors"][0]["name"] == "disk_check"


# ---------------------------------------------------------------------------
# Suppression semantics
# ---------------------------------------------------------------------------

def test_30_1_suppression_permanent_when_until_none():
    s = Suppression(rule="x", until=None, reason="r")
    assert s.is_active() is True


def test_30_1_suppression_expires_in_past():
    s = Suppression(rule="x", until="2020-01-01T00:00:00+00:00", reason="r")
    assert s.is_active() is False


def test_30_1_suppression_expires_in_future():
    future = "2099-01-01T00:00:00+00:00"
    s = Suppression(rule="x", until=future, reason="r")
    assert s.is_active() is True


def test_30_1_suppression_naive_timestamp_assumed_utc():
    s = Suppression(rule="x", until="2099-01-01T00:00:00", reason="r")
    assert s.is_active() is True


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

def test_30_1_get_host_populates_cache_on_first_read():
    # Save to YAML first
    cfg = HostConfig(name="cached",
                     monitors=[MonitorConfig(name="disk_check", enabled=False)])
    save_host(cfg)
    # Wipe cache by deleting rows
    conn = hc._db_conn()
    conn.execute("DELETE FROM hosts WHERE name='cached'")
    conn.execute("DELETE FROM host_monitors WHERE host='cached'")
    # Now read — should populate
    loaded = get_host("cached")
    assert loaded.monitor("disk_check").enabled is False
    # And SQLite should have the row
    row = conn.execute(
        "SELECT name FROM hosts WHERE name='cached'"
    ).fetchone()
    assert row is not None


def test_30_1_save_invalidates_cache():
    cfg = HostConfig(name="invalidated",
                     monitors=[MonitorConfig(name="disk_check", enabled=True)])
    save_host(cfg)
    # Read once to warm cache
    get_host("invalidated")
    # Rewrite with different value
    cfg.monitors[0].enabled = False
    save_host(cfg)
    # Read again — must see the new value (cache was invalidated)
    fresh = get_host("invalidated")
    assert fresh.monitor("disk_check").enabled is False


def test_30_1_list_all_hosts_includes_yamls_without_cache():
    save_host(HostConfig(name="a-host"))
    save_host(HostConfig(name="b-host"))
    # Wipe cache for both
    conn = hc._db_conn()
    conn.execute("DELETE FROM hosts")
    conn.execute("DELETE FROM host_monitors")
    conn.execute("DELETE FROM host_repairs")
    conn.execute("DELETE FROM host_runbooks")
    conn.execute("DELETE FROM host_suppressions")
    # list_all_hosts should still find them via YAML directory
    all_cfg = list_all_hosts()
    names = sorted(c.name for c in all_cfg)
    assert "a-host" in names
    assert "b-host" in names


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_30_1_delete_removes_yaml_and_clears_cache():
    save_host(HostConfig(name="doomed"))
    get_host("doomed")  # warm cache
    assert delete_host("doomed") is True
    # Second delete is a no-op
    assert delete_host("doomed") is False
    # And loading returns the default (no monitors)
    assert load_host("doomed").monitors == []


# ---------------------------------------------------------------------------
# Default safety
# ---------------------------------------------------------------------------

def test_30_1_repair_default_requires_approval():
    """A repair with no explicit require_approval should default to True."""
    cfg = HostConfig(name="safe",
                     repairs=[RepairConfig(name="service_restart")])
    assert cfg.repair("service_restart").require_approval is True


def test_30_1_monitor_default_enabled():
    cfg = HostConfig(name="m",
                     monitors=[MonitorConfig(name="x")])
    assert cfg.monitor("x").enabled is True


def test_30_1_runbook_default_enabled():
    cfg = HostConfig(name="r",
                     runbooks=[RunbookConfig(name="rb")])
    assert cfg.runbook("rb").enabled is True
