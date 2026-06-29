"""Config subsystem: hot-reload, secrets, token rotation, legacy rules."""
from .loader import ConfigLoader
from .secrets import load_token, TokenInfo
from .validator import validate, is_valid, SCHEMA
from . import legacy
from . import connectors as _connectors
from .connectors import (
    Connector,
    load_all as load_connectors,
    save_all as save_connectors,
    add as add_connector,
    update as update_connector,
    remove as remove_connector,
    get_by_name as get_connector,
    mark_collected as mark_connector_collected,
    mark_error as mark_connector_error,
    connectors_file,
    state_dir,
)

# Re-export legacy functions for backward compatibility
get_server_id = legacy.get_server_id
load_rules = legacy.load_rules
slack_webhook_url = legacy.slack_webhook_url
telegram_bot_token = legacy.telegram_bot_token
telegram_chat_id = legacy.telegram_chat_id
notifications_enabled = legacy.notifications_enabled
DEFCON_LEVELS = legacy.DEFCON_LEVELS

__all__ = [
    "ConfigLoader",
    "load_token",
    "TokenInfo",
    "validate",
    "is_valid",
    "SCHEMA",
    "get_server_id",
    "load_rules",
    "slack_webhook_url",
    "telegram_bot_token",
    "telegram_chat_id",
    "notifications_enabled",
    "DEFCON_LEVELS",
]
