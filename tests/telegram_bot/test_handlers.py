"""Tests for telegram_bot handlers.

Each handler is a thin async function: takes (update, context) like
python-telegram-bot, uses the bot_data['agent'] to talk to agent_api,
formats the response, and replies.

We test the handler's *return value* (a dict describing what to send)
rather than mocking the entire Telegram API. This keeps tests fast and
focused on the contract.
"""
import pytest
from types import SimpleNamespace

from ipracticom_sweeper.telegram_bot.config import BotConfig
from ipracticom_sweeper.telegram_bot.services.agent_client import AgentAPIError
from ipracticom_sweeper.telegram_bot.handlers import start, status, problems, history, security


# ---------- fakes ----------

def _update(chat_id: int = 42, callback_data: str | None = None):
    """Build a fake Update-like object with the right shape."""
    chat = SimpleNamespace(id=chat_id)
    if callback_data is None:
        return SimpleNamespace(effective_chat=chat, message=None, callback_query=None)
    cq = SimpleNamespace(data=callback_data, from_user=SimpleNamespace(id=chat_id), message=None)
    return SimpleNamespace(effective_chat=chat, callback_query=cq, message=None)


def _ctx(cfg: BotConfig, agent):
    """Build a fake Context with bot_data populated."""
    return SimpleNamespace(bot_data={"config": cfg, "agent": agent})


# ---------- start ----------

@pytest.mark.asyncio
async def test_start_returns_welcome():
    """start handler returns welcome text + main menu keyboard."""
    cfg = BotConfig(bot_token="t", allowed_chat_ids={42})
    ctx = _ctx(cfg, agent=None)
    update = _update(chat_id=42)
    result = await start(update, ctx)
    assert "ברוך הבא" in result["text"] or "sweeper" in result["text"].lower()
    assert "reply_markup" in result


# ---------- status ----------

@pytest.mark.asyncio
async def test_status_uses_snapshot():
    """status handler pulls /api/snapshot and formats it."""

    class FakeAgent:
        async def get_snapshot(self):
            return {"defcon": 3, "modules": {"cpu": {"status": "ok"}}}

    cfg = BotConfig(bot_token="t", allowed_chat_ids={42})
    ctx = _ctx(cfg, FakeAgent())
    update = _update(chat_id=42, callback_data="menu:status")
    result = await status(update, ctx)
    assert "DEFCON 3" in result["text"]


@pytest.mark.asyncio
async def test_status_handles_agent_error():
    """status handler returns Hebrew error when agent_api is down."""

    class BrokenAgent:
        async def get_snapshot(self):
            raise AgentAPIError(503, "service unavailable")

    cfg = BotConfig(bot_token="t", allowed_chat_ids={42})
    ctx = _ctx(cfg, BrokenAgent())
    update = _update(chat_id=42, callback_data="menu:status")
    result = await status(update, ctx)
    assert "שגיאה" in result["text"] or "error" in result["text"].lower()


# ---------- problems ----------

@pytest.mark.asyncio
async def test_problems_lists_active():
    """problems handler lists warn/crit modules only."""

    class FakeAgent:
        async def get_snapshot(self):
            return {
                "defcon": 2,
                "modules": {
                    "cpu": {"status": "ok"},
                    "disk": {"status": "warn", "details": "85% full"},
                    "memory": {"status": "crit", "details": "OOM risk"},
                },
            }

    cfg = BotConfig(bot_token="t", allowed_chat_ids={42})
    ctx = _ctx(cfg, FakeAgent())
    update = _update(chat_id=42, callback_data="menu:problems")
    result = await problems(update, ctx)
    assert "85% full" in result["text"]
    assert "OOM risk" in result["text"]


@pytest.mark.asyncio
async def test_problems_clean_state():
    """problems handler says 'all good' when no issues."""

    class FakeAgent:
        async def get_snapshot(self):
            return {"defcon": 5, "modules": {"cpu": {"status": "ok"}}}

    cfg = BotConfig(bot_token="t", allowed_chat_ids={42})
    ctx = _ctx(cfg, FakeAgent())
    update = _update(chat_id=42, callback_data="menu:problems")
    result = await problems(update, ctx)
    assert "אין בעיות" in result["text"] or "✅" in result["text"]


# ---------- history ----------

@pytest.mark.asyncio
async def test_history_for_metric():
    """history handler calls /api/history/{metric} with the right arg."""

    captured = {}

    class FakeAgent:
        async def get_history(self, metric, hours=24):
            captured["metric"] = metric
            captured["hours"] = hours
            return [
                {"ts": 1700000000, "value": 3.0},
                {"ts": 1700003600, "value": 4.0},
            ]

    cfg = BotConfig(bot_token="t", allowed_chat_ids={42})
    ctx = _ctx(cfg, FakeAgent())
    update = _update(chat_id=42, callback_data="hist:defcon")
    result = await history(update, ctx)
    assert captured["metric"] == "defcon"
    assert "defcon" in result["text"].lower()
    assert "2" in result["text"]  # 2 samples


@pytest.mark.asyncio
async def test_history_empty_data():
    """history handler handles empty history gracefully."""

    class FakeAgent:
        async def get_history(self, metric, hours=24):
            return []

    cfg = BotConfig(bot_token="t", allowed_chat_ids={42})
    ctx = _ctx(cfg, FakeAgent())
    update = _update(chat_id=42, callback_data="hist:cpu_percent")
    result = await history(update, ctx)
    assert "אין נתונים" in result["text"] or "no data" in result["text"].lower()


# ---------- security ----------

@pytest.mark.asyncio
async def test_security_renders_report():
    """security handler renders a security-baseline report."""

    class FakeAgent:
        async def get_snapshot(self):
            return {
                "defcon": 4,
                "modules": {
                    "security_baseline": {
                        "status": "ok",
                        "details": {
                            "ssh_drift": [],
                            "suid_changes": ["/usr/bin/new_suid"],
                            "ports": [{"port": 22, "service": "ssh"}],
                        },
                    }
                },
            }

    cfg = BotConfig(bot_token="t", allowed_chat_ids={42})
    ctx = _ctx(cfg, FakeAgent())
    update = _update(chat_id=42, callback_data="menu:security")
    result = await security(update, ctx)
    assert "SSH" in result["text"]
    assert "SUID" in result["text"] or "suid" in result["text"].lower()
