"""Tests for notify integration with PipelineResult."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from ipracticom_sweeper.notify import (
    format_slack_message,
    format_telegram_message,
    notify_pipeline_result,
)


# --- Pipeline result formatters ----------------------------------------------


def test_telegram_includes_defcon():
    fake = {
        "defcon": 3,
        "defcon_label": "orange",
        "monitor_overall": "crit",
        "problems_found": 1,
        "repairs_attempted": 1,
        "repairs_succeeded": 1,
        "repairs_failed": 0,
        "needs_human": 0,
        "server": "i-test",
        "diagnosis": {"summary": "test summary", "problems": []},
        "repair_results": [],
    }
    msg = format_telegram_message(fake)
    assert "DEFCON 3" in msg
    assert "orange" in msg
    assert "i-test" in msg
    assert "1/1 succeeded" in msg


def test_telegram_includes_problems():
    fake = {
        "defcon": 4,
        "defcon_label": "yellow",
        "monitor_overall": "warn",
        "problems_found": 2,
        "repairs_attempted": 0,
        "repairs_succeeded": 0,
        "repairs_failed": 0,
        "needs_human": 0,
        "server": "i-test",
        "diagnosis": {
            "summary": "2 warning(s)",
            "problems": [
                {"kind": "memory_warn", "severity": "warn", "detail": "Memory at 85%"},
                {"kind": "disk_warn", "severity": "warn", "detail": "Disk at 85%"},
            ],
        },
        "repair_results": [],
    }
    msg = format_telegram_message(fake)
    assert "memory_warn" in msg
    assert "disk_warn" in msg
    assert "Memory at 85%" in msg
    assert "Disk at 85%" in msg


def test_telegram_caps_problems_at_10():
    problems = [
        {"kind": f"p_{i}", "severity": "warn", "detail": f"detail {i}"}
        for i in range(20)
    ]
    fake = {
        "defcon": 3,
        "defcon_label": "orange",
        "problems_found": 20,
        "repairs_attempted": 0,
        "repairs_succeeded": 0,
        "repairs_failed": 0,
        "needs_human": 0,
        "server": "x",
        "diagnosis": {"summary": "many", "problems": problems},
        "repair_results": [],
    }
    msg = format_telegram_message(fake)
    # Should only show 10
    assert "p_0" in msg
    assert "p_9" in msg
    assert "p_10" not in msg


def test_slack_includes_defcon():
    fake = {
        "defcon": 2,
        "defcon_label": "red",
        "monitor_overall": "crit",
        "problems_found": 1,
        "repairs_attempted": 0,
        "repairs_succeeded": 0,
        "repairs_failed": 0,
        "needs_human": 1,
        "server": "i-12345",
        "diagnosis": {"summary": "FIRE", "problems": []},
        "repair_results": [],
    }
    msg = format_slack_message(fake)
    assert msg["text"] == "🔴 Sweeper DEFCON 2 (red)"
    assert msg["blocks"][0]["type"] == "header"


# --- Backward compat: legacy snapshot shape still works ----------------------


def test_telegram_handles_legacy_snapshot_shape():
    legacy = {
        "overall_status": "warn",
        "server": "legacy-host",
        "modules": {
            "cpu": {"status": "ok"},
            "memory": {"status": "warn"},
        },
    }
    msg = format_telegram_message(legacy)
    assert "WARN" in msg
    assert "legacy-host" in msg
    assert "memory" in msg


def test_slack_handles_legacy_snapshot_shape():
    legacy = {
        "overall_status": "crit",
        "server": "legacy-host",
        "modules": {
            "cpu": {"status": "crit"},
        },
    }
    msg = format_slack_message(legacy)
    assert ":rotating_light:" in msg["text"] or "CRIT" in msg["text"]


# --- notify_pipeline_result async function ----------------------------------


def test_notify_pipeline_skips_when_green():
    """DEFCON 5 (green) — no notification unless force=True."""
    fake = {
        "defcon": 5,
        "defcon_label": "green",
        "monitor_overall": "ok",
        "problems_found": 0,
        "repairs_attempted": 0,
        "repairs_succeeded": 0,
        "repairs_failed": 0,
        "needs_human": 0,
        "diagnosis": {"summary": "all good", "problems": []},
    }
    with patch("ipracticom_sweeper.notify.legacy._send_slack", new=AsyncMock()) as mock_slack:
        with patch("ipracticom_sweeper.notify.legacy._send_telegram", new=AsyncMock()) as mock_tg:
            result = asyncio.run(notify_pipeline_result(fake))
    assert result == {}
    mock_slack.assert_not_called()
    mock_tg.assert_not_called()


def test_notify_pipeline_force_green_sends():
    fake = {
        "defcon": 5,
        "defcon_label": "green",
        "monitor_overall": "ok",
        "problems_found": 0,
        "repairs_attempted": 0,
        "repairs_succeeded": 0,
        "repairs_failed": 0,
        "needs_human": 0,
        "diagnosis": {"summary": "all good", "problems": []},
    }
    fake_send = AsyncMock(return_value=True)
    with patch("ipracticom_sweeper.config.notifications_enabled", return_value=True):
        with patch("ipracticom_sweeper.config.slack_webhook_url", return_value="https://hook"):
            with patch("ipracticom_sweeper.config.telegram_bot_token", return_value=None):
                with patch("ipracticom_sweeper.config.telegram_chat_id", return_value=None):
                    with patch("ipracticom_sweeper.notify.legacy._send_slack", new=fake_send):
                        result = asyncio.run(notify_pipeline_result(fake, force=True))
    assert result == {"slack": True}
    fake_send.assert_called_once()


def test_notify_pipeline_no_channels_returns_empty():
    fake = {
        "defcon": 2,
        "defcon_label": "red",
        "monitor_overall": "crit",
        "problems_found": 1,
        "repairs_attempted": 0,
        "repairs_succeeded": 0,
        "repairs_failed": 0,
        "needs_human": 1,
        "diagnosis": {"summary": "FIRE", "problems": []},
    }
    with patch("ipracticom_sweeper.config.slack_webhook_url", return_value=None):
        with patch("ipracticom_sweeper.config.telegram_bot_token", return_value=None):
            result = asyncio.run(notify_pipeline_result(fake))
    assert result == {}


def test_notify_pipeline_calls_both_channels():
    fake = {
        "defcon": 3,
        "defcon_label": "orange",
        "monitor_overall": "crit",
        "problems_found": 1,
        "repairs_attempted": 1,
        "repairs_succeeded": 1,
        "repairs_failed": 0,
        "needs_human": 0,
        "server": "i-test",
        "diagnosis": {"summary": "auto-repair", "problems": []},
    }
    fake_slack = AsyncMock(return_value=True)
    fake_tg = AsyncMock(return_value=True)
    with patch("ipracticom_sweeper.config.notifications_enabled", return_value=True):
        with patch("ipracticom_sweeper.config.slack_webhook_url", return_value="https://hook"):
            with patch("ipracticom_sweeper.config.telegram_bot_token", return_value="token"):
                with patch("ipracticom_sweeper.config.telegram_chat_id", return_value="123"):
                    with patch("ipracticom_sweeper.notify.legacy._send_slack", new=fake_slack):
                        with patch("ipracticom_sweeper.notify.legacy._send_telegram", new=fake_tg):
                            result = asyncio.run(notify_pipeline_result(fake))
    assert result == {"slack": True, "telegram": True}
    fake_slack.assert_called_once()
    fake_tg.assert_called_once()


# --- Integration: pipeline.run_pipeline calls notify -------------------------


def test_pipeline_calls_notify_on_warn_state():
    """When pipeline ends at DEFCON 4 (warn), notify is attempted."""
    from ipracticom_sweeper.pipeline import run_pipeline

    # Fake a warn-level snapshot (memory warn, not crit — no auto-repair)
    warn_snap = {
        "modules": {
            "cpu": {"values": {"load_5min": 0.5, "iowait_percent": 1.0}, "status": "ok"},
            "memory": {"values": {"ram_used_percent": 85.0, "swap_used_percent": 0.0}, "status": "warn"},
            "disk": {"values": {"mounts": [{"mount": "/", "used_percent": 50.0, "read_only": False}]}, "status": "ok"},
            "services": {"values": {"failed_units": [], "failed_count": 0}, "status": "ok"},
            "security": {"values": {"failed_ssh_per_minute": 0.0, "sudo_failures": 0}, "status": "ok"},
        },
        "overall_status": "warn",
    }
    rules = {
        "cpu": {"load_avg_5min_warn": 2.0, "load_avg_5min_crit": 5.0, "iowait_percent_warn": 20.0},
        "memory": {"used_percent_warn": 80.0, "used_percent_crit": 95.0, "swap_used_percent_warn": 50.0},
        "disk": {"used_percent_warn": 80.0, "used_percent_crit": 95.0, "read_only_mounts": []},
        "services": {"critical_list": []},
        "security": {"failed_ssh_per_min_warn": 5, "sudo_failures_per_hour_warn": 3},
    }
    with patch("ipracticom_sweeper.pipeline.run_monitor", return_value=warn_snap):
        with patch("ipracticom_sweeper.notify.notify_pipeline_result", new=AsyncMock(return_value={})):
            result = run_pipeline(rules)

    assert result.defcon == 4  # warn
    # Memory at 85% → memory_warn → drop_caches (GUARDED)
    assert "drop_caches" in result.diagnosis.get("safe_repairs", [])


def test_pipeline_skips_notify_when_green():
    """DEFCON 5 (green) → no notify call (force=False default)."""
    from ipracticom_sweeper.pipeline import run_pipeline

    green_snap = {
        "modules": {
            "cpu": {"values": {"load_5min": 0.5, "iowait_percent": 1.0}, "status": "ok"},
            "memory": {"values": {"ram_used_percent": 30.0, "swap_used_percent": 0.0}, "status": "ok"},
            "disk": {"values": {"mounts": [{"mount": "/", "used_percent": 50.0, "read_only": False}]}, "status": "ok"},
            "services": {"values": {"failed_units": [], "failed_count": 0}, "status": "ok"},
            "security": {"values": {"failed_ssh_per_minute": 0.0, "sudo_failures": 0}, "status": "ok"},
        },
        "overall_status": "ok",
    }
    rules = {
        "cpu": {"load_avg_5min_warn": 2.0, "load_avg_5min_crit": 5.0, "iowait_percent_warn": 20.0},
        "memory": {"used_percent_warn": 80.0, "used_percent_crit": 95.0, "swap_used_percent_warn": 50.0},
        "disk": {"used_percent_warn": 80.0, "used_percent_crit": 95.0, "read_only_mounts": []},
        "services": {"critical_list": []},
        "security": {"failed_ssh_per_min_warn": 5, "sudo_failures_per_hour_warn": 3},
    }
    with patch("ipracticom_sweeper.pipeline.run_monitor", return_value=green_snap):
        mock_notify = AsyncMock(return_value={})
        with patch("ipracticom_sweeper.notify.notify_pipeline_result", new=mock_notify):
            result = run_pipeline(rules)

    assert result.defcon == 5
    # notify was NOT called (green + no force)
    mock_notify.assert_not_called()