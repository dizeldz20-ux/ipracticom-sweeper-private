"""Configuration loader for the AWS Linux Sweeper.

Reads from environment variables and YAML config files.
Never stores secrets in code — only references env vars.
"""

import os
from pathlib import Path
from typing import Optional

import structlog
import yaml

from .._log import log_suppressed

logger = structlog.get_logger()

# --- Paths -------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
RULES_DIR = PROJECT_ROOT / "rules"
DEFAULT_RULES_FILE = RULES_DIR / "default.yaml"


# --- Server identity ---------------------------------------------------------


def get_server_id() -> str:
    """Return the EC2 instance ID, or hostname if not on AWS.

    Reads from EC2 metadata service (IMDSv2) when available, with a 1s
    timeout to fail fast outside AWS.
    """
    # Try IMDSv2 first
    try:
        import httpx

        # Get token
        token_resp = httpx.put(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
            timeout=1.0,
        )
        if token_resp.status_code == 200:
            token = token_resp.text
            id_resp = httpx.get(
                "http://169.254.169.254/latest/meta-data/instance-id",
                headers={"X-aws-ec2-metadata-token": token},
                timeout=1.0,
            )
            if id_resp.status_code == 200:
                return id_resp.text
    except Exception as e:
        log_suppressed("legacy_instance_id", e)

    # Fallback to hostname
    import socket

    return socket.gethostname()


# --- Thresholds --------------------------------------------------------------


def load_rules(path: Optional[Path] = None) -> dict:
    """Load threshold rules from YAML.

    Schema:
        cpu:
          load_avg_5min_warn: 2.0
          load_avg_5min_crit: 5.0
        memory:
          used_percent_warn: 80
          used_percent_crit: 95
        disk:
          used_percent_warn: 80
          used_percent_crit: 95
          inode_used_percent_warn: 80
        network:
          ...
        services:
          critical_list: [nginx, postgresql, redis]
    """
    path = path or DEFAULT_RULES_FILE
    if not path.exists():
        logger.warning("rules_file_not_found_using_defaults", path=str(path))
        return _default_rules()

    with open(path) as f:
        rules = yaml.safe_load(f) or {}

    # Merge with defaults so missing keys get sensible values
    defaults = _default_rules()
    merged = _deep_merge(defaults, rules)

    # Validate the merged rules. Don't raise — log and return what we have,
    # so a malformed config still runs (with safe defaults) instead of crash-looping.
    from ipracticom_sweeper.config.validator import validate
    errors = validate(merged)
    if errors:
        for err in errors:
            logger.warning("rules_validation_error", error=err, path=str(path))

    return merged


def _default_rules() -> dict:
    return {
        "cpu": {
            "load_avg_5min_warn": 2.0,
            "load_avg_5min_crit": 5.0,
            "iowait_percent_warn": 20.0,
            "steal_percent_warn": 10.0,
        },
        "memory": {
            "used_percent_warn": 80.0,
            "used_percent_crit": 95.0,
            "swap_used_percent_warn": 50.0,
        },
        "disk": {
            "used_percent_warn": 80.0,
            "used_percent_crit": 95.0,
            "inode_used_percent_warn": 80.0,
            "read_only_mounts": ["/"],
        },
        "network": {
            "dropped_packets_warn": 100,
            "tcp_retransmit_percent_warn": 5.0,
            "connections_close_wait_warn": 1000,
        },
        "services": {
            "critical_list": [],  # explicit list of must-be-up services
            "failed_units_window_min": 5,
        },
        "logs": {
            "error_rate_per_min_warn": 10,
            "oom_events_window_min": 60,
        },
        "processes": {
            "zombie_count_warn": 5,
            "stuck_proc_minutes_warn": 30,
        },
        "security": {
            "failed_ssh_per_min_warn": 5,
            "sudo_failures_per_hour_warn": 3,
        },
    }


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Merge overlay into base. Overlay values win; nested dicts recurse."""
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# --- Notification config -----------------------------------------------------


def slack_webhook_url() -> Optional[str]:
    return os.getenv("SLACK_WEBHOOK_URL")


def telegram_bot_token() -> Optional[str]:
    return os.getenv("TELEGRAM_BOT_TOKEN")


def telegram_chat_id() -> Optional[str]:
    return os.getenv("TELEGRAM_CHAT_ID")


def notifications_enabled() -> bool:
    """True if at least one channel is configured."""
    return bool(slack_webhook_url()) or (
        bool(telegram_bot_token()) and bool(telegram_chat_id())
    )


# --- DEFCON levels -----------------------------------------------------------

DEFCON_LEVELS = {
    5: "green",     # all good
    4: "yellow",    # warning thresholds tripped
    3: "orange",    # critical thresholds tripped, not yet persistent
    2: "red",       # critical thresholds persistent, auto-repair safe
    1: "black",     # something is on fire, alert humans
}