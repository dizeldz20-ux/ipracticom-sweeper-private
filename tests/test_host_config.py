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
    add_suppression, remove_suppression, list_active_suppressions,
    cleanup_expired_suppressions,
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


# ---------------------------------------------------------------------------
# Slice 3 — Suppression engine
# ---------------------------------------------------------------------------
#
# API:
#   add_suppression(host, rule, until=None, reason="") -> Suppression
#       Persist a new suppression for ``host`` (auto-creates the host
#       if it does not yet exist). Returns the stored Suppression.
#       Re-adding the same (host, rule) updates the existing one.
#
#   remove_suppression(host, rule) -> bool
#       Remove the active suppression for (host, rule). Idempotent:
#       returns False if nothing was removed.
#
#   list_active_suppressions(host) -> list[Suppression]
#       All currently-active suppressions for ``host`` (expired are
#       filtered out automatically).
#
#   cleanup_expired_suppressions() -> int
#       Scan every host YAML, drop expired suppressions from each,
#       rewrite the file. Returns the number of entries removed.
# ---------------------------------------------------------------------------


def test_30_3_add_suppression_persists_to_yaml(tmp_path):
    """Adding a suppression on a fresh host auto-creates the host and
    writes the YAML; subsequent load_host returns the suppression."""
    add_suppression("host-a", "fs_inode_check",
                    until="2099-01-01T00:00:00+00:00",
                    reason="known issue, FS-2026-001")
    cfg = load_host("host-a")
    assert len(cfg.suppressions) == 1
    s = cfg.suppressions[0]
    assert s.rule == "fs_inode_check"
    assert s.reason.startswith("known issue")
    assert s.until.startswith("2099-01-01")
    # YAML file actually exists on disk
    assert (_hosts_dir_for_test(tmp_path) / "host-a.yaml").exists()


def test_30_3_add_suppression_duplicate_updates_existing(tmp_path):
    """Re-adding the same (host, rule) replaces the entry instead of
    stacking duplicates."""
    add_suppression("host-b", "cpu_check", until=None, reason="first")
    add_suppression("host-b", "cpu_check", until="2030-01-01T00:00:00+00:00",
                    reason="second")
    cfg = load_host("host-b")
    assert len(cfg.suppressions) == 1
    s = cfg.suppressions[0]
    assert s.reason == "second"
    assert s.until is not None


def test_30_3_add_suppression_invalid_host_rejected():
    """Path-traversal / sanitization applies to the new API too."""
    with pytest.raises(ValueError):
        add_suppression("../etc/passwd", "x", reason="nope")
    with pytest.raises(ValueError):
        add_suppression("bad name with spaces", "x", reason="nope")


def test_30_3_remove_suppression_returns_true_when_present():
    add_suppression("host-c", "disk_check", reason="x")
    assert remove_suppression("host-c", "disk_check") is True
    cfg = load_host("host-c")
    assert cfg.suppressions == []


def test_30_3_remove_suppression_idempotent():
    """Removing a rule that has no suppression is a no-op, not an error."""
    assert remove_suppression("never-existed", "anything") is False
    add_suppression("host-d", "memory_check", reason="x")
    assert remove_suppression("host-d", "memory_check") is True
    # second remove: nothing left
    assert remove_suppression("host-d", "memory_check") is False


def test_30_3_list_active_filters_expired():
    """list_active_suppressions returns only currently-active entries."""
    # permanent
    add_suppression("host-e", "rule_perm", until=None, reason="permanent")
    # future-expiry
    add_suppression("host-e", "rule_future",
                    until="2099-12-31T00:00:00+00:00", reason="future")
    # already expired (yesterday)
    add_suppression("host-e", "rule_past",
                    until="2020-01-01T00:00:00+00:00", reason="past")
    active = list_active_suppressions("host-e")
    rules = {s.rule for s in active}
    assert rules == {"rule_perm", "rule_future"}


def test_30_3_list_active_unknown_host_returns_empty():
    assert list_active_suppressions("never-existed") == []


def test_30_3_cleanup_expired_removes_only_expired(tmp_path):
    """The bulk cleanup touches every host YAML and drops only expired
    suppressions, leaving permanent and future ones intact."""
    add_suppression("h1", "perm", until=None, reason="p")
    add_suppression("h1", "future", until="2099-01-01T00:00:00+00:00",
                    reason="f")
    add_suppression("h1", "past", until="2020-01-01T00:00:00+00:00",
                    reason="x")
    add_suppression("h2", "past-only", until="2020-01-01T00:00:00+00:00",
                    reason="x")

    removed = cleanup_expired_suppressions()
    assert removed == 2  # one in h1, one in h2

    h1 = load_host("h1")
    h1_rules = {s.rule for s in h1.suppressions}
    assert h1_rules == {"perm", "future"}
    h2 = load_host("h2")
    assert h2.suppressions == []


def test_30_3_cleanup_returns_zero_when_nothing_expired():
    add_suppression("h3", "perm", until=None, reason="p")
    assert cleanup_expired_suppressions() == 0
    cfg = load_host("h3")
    assert len(cfg.suppressions) == 1


def test_30_3_cleanup_writes_yaml_for_unchanged_hosts_only_if_needed(tmp_path):
    """Cleanup must not rewrite host files that have no expired entries
    (preserves mtime/inode for the audit trail)."""
    add_suppression("h4", "perm", until=None, reason="p")
    path = _hosts_dir_for_test(tmp_path) / "h4.yaml"
    mtime_before = path.stat().st_mtime
    # ensure clock tick is observable on coarse filesystems
    time.sleep(0.05)
    cleanup_expired_suppressions()
    # file should not be rewritten (mtime unchanged or equal)
    assert path.stat().st_mtime == mtime_before


def test_30_3_add_emits_audit_event(monkeypatch, tmp_path):
    """add_suppression writes an audit record of the action."""
    captured = []
    from ipracticom_sweeper.audit import logger as audit_logger
    monkeypatch.setattr(audit_logger, "emit",
                        lambda ev, payload, severity="info": captured.append((ev, payload, severity)))
    add_suppression("audit-host", "rule_x", reason="because")
    assert any(ev == "suppression.add" for ev, _, _ in captured)


def test_30_3_remove_emits_audit_event(monkeypatch):
    captured = []
    from ipracticom_sweeper.audit import logger as audit_logger
    monkeypatch.setattr(audit_logger, "emit",
                        lambda ev, payload, severity="info": captured.append((ev, payload, severity)))
    add_suppression("audit-host2", "rule_y", reason="r")
    captured.clear()
    remove_suppression("audit-host2", "rule_y")
    assert any(ev == "suppression.remove" for ev, _, _ in captured)


def test_30_3_is_suppressed_helper_uses_is_active():
    """HostConfig.is_suppressed() now uses Suppression.is_active() and
    returns the matching entry only when it is still active."""
    cfg = HostConfig(name="z", suppressions=[
        Suppression(rule="r1", until="2020-01-01T00:00:00+00:00"),  # expired
        Suppression(rule="r2", until=None),                        # permanent
    ])
    is_sup, hit = cfg.is_suppressed("r1")
    assert is_sup is False
    assert hit is None
    is_sup, hit = cfg.is_suppressed("r2")
    assert is_sup is True
    assert hit is not None and hit.rule == "r2"


# ---------------------------------------------------------------------------
# Helpers (test-local)
# ---------------------------------------------------------------------------

def _hosts_dir_for_test(tmp_path: Path) -> Path:
    return Path(tmp_path) / "hosts"
