"""Flask dashboard for iPracticom AWS Sweeper.

Routes:
  GET  /                          → main dashboard (latest snapshot)
  GET  /history                   → list of recent runs
  GET  /run                       → JSON of latest pipeline result
  GET  /run/now                   → trigger a fresh pipeline run, return JSON
  GET  /api/snapshot              → raw JSON snapshot (last cached)
  POST /api/notify/test           → send a test notification (dev convenience)
  GET  /healthz                   → simple liveness check

Design goals:
  - "Classic & refined, professional" — serif headings (Cormorant Garamond),
    sans body (Inter), neutral palette with one accent color.
  - All data on one screen (no scroll walls) — operators should see DEFCON +
    modules + problems + repairs at a glance.
  - Server-rendered HTML (Jinja2) — no React/build pipeline. Fast to render,
    accessible, and editable.
  - Pure HTML/CSS — no JS framework, just a tiny sprinkle for auto-refresh.

The dashboard reads cached pipeline results from disk (written by the sweeper
after each run) — it does NOT trigger its own runs. Use `sweeper` CLI /
systemd timer to populate data, then visit the dashboard to view it.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, render_template, request

from ipracticom_sweeper.agent_client import AgentClient, AgentError
from ipracticom_sweeper.config import (
    Connector,
    get_server_id,
    load_rules,
    load_connectors,
    add_connector,
    update_connector,
    remove_connector,
)
from ipracticom_sweeper.pipeline import run_pipeline

# --- Paths -------------------------------------------------------------------

CACHE_DIR = Path("/var/lib/ipracticom-sweeper/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
LAST_RESULT_FILE = CACHE_DIR / "last-result.json"


# --- Flask app ---------------------------------------------------------------

app = Flask(__name__)


# --- Chat routes (v0.5.0 slice 3.1) -------------------------------------------

try:
    from ipracticom_sweeper.chat import register_chat_routes as _register_chat
    _register_chat(app)
except Exception as _chat_exc:  # pragma: no cover -- optional dep path
    # Log so dashboard still boots if flask-sock missing.
    import sys
    print(f"[chat] chat routes disabled: {_chat_exc}", file=sys.stderr)


# --- Jinja filters (Hebrew translation) ---------------------------------------

_DEFCON_HE = {"green": "תקין", "yellow": "אזהרה", "orange": "חמור", "red": "קריטי", "black": "אסון"}
_MODULE_STATUS_HE = {"ok": "תקין", "warn": "אזהרה", "crit": "קריטי"}
_SEVERITY_HE = {"warn": "אזהרה", "crit": "קריטי"}


@app.template_filter("defcon_label_hebrew")
def _defcon_label_hebrew(label: str) -> str:
    return _DEFCON_HE.get((label or "").lower(), label or "")


@app.template_filter("module_status_hebrew")
def _module_status_hebrew(status: str) -> str:
    return _MODULE_STATUS_HE.get((status or "").lower(), status or "")


@app.template_filter("severity_hebrew")
def _severity_hebrew(sev: str) -> str:
    return _SEVERITY_HE.get((sev or "").lower(), sev or "")


# --- HTTP Basic auth (gated by DASHBOARD_USER / DASHBOARD_PASS env) ---------
_DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "")
_DASHBOARD_PASS = os.environ.get("DASHBOARD_PASS", "")


@app.before_request
def _require_basic_auth():
    """Gate every dashboard route with HTTP Basic auth.

    /healthz is always open (used by cloudflared liveness probes).
    When DASHBOARD_USER/DASHBOARD_PASS are unset, dashboard stays open — caller
    should bind to 127.0.0.1 only.
    """
    if not (_DASHBOARD_USER and _DASHBOARD_PASS):
        return None  # open mode
    if request.path == "/healthz":
        return None  # liveness probe
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:].strip(), validate=True).decode("utf-8")
            user, _, pwd = decoded.partition(":")
            if hmac.compare_digest(user, _DASHBOARD_USER) and hmac.compare_digest(pwd, _DASHBOARD_PASS):
                return None
        except Exception:
            pass
    resp = jsonify({"error": "unauthorized", "reason": "missing or invalid Basic credentials"})
    resp.status_code = 401
    resp.headers["WWW-Authenticate"] = 'Basic realm="sweeper-dashboard"'
    return resp


# --- Cache management --------------------------------------------------------


def _read_last_result() -> dict[str, Any] | None:
    """Read the most recent pipeline result from disk cache."""
    if not LAST_RESULT_FILE.exists():
        return None
    try:
        with open(LAST_RESULT_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_last_result(result_dict: dict[str, Any]) -> None:
    """Write a pipeline result to disk cache (atomic via tmp+rename)."""
    tmp = LAST_RESULT_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(result_dict, f, indent=2, default=str)
    tmp.rename(LAST_RESULT_FILE)


def trigger_pipeline_run(force_notify: bool = False) -> dict[str, Any]:
    """Execute the pipeline in-process and cache the result.

    We invoke the pipeline function directly (not via subprocess) so we get
    a fresh, in-process result. For long-running cron-style execution use
    the sweeper CLI via systemd timer instead.
    """
    rules = load_rules()
    result = run_pipeline(
        rules,
        auto_repair=True,
        dry_run=False,
    )
    d = result.to_dict()
    d["server"] = get_server_id()
    d["notified"] = force_notify
    _write_last_result(d)
    return d


# --- Mode resolution ---------------------------------------------------------


def _remote_url() -> str | None:
    """Return the configured remote agent URL, or None for local mode."""
    return os.environ.get("SWEEPER_REMOTE_URL")


def _remote_token() -> str | None:
    return os.environ.get("SWEEPER_REMOTE_TOKEN")


def _is_remote_mode() -> bool:
    return bool(_remote_url())


def _get_agent() -> AgentClient | None:
    """Build a remote agent client if remote mode is configured."""
    url = _remote_url()
    if not url:
        return None
    return AgentClient(url, token=_remote_token())


def _fetch_snapshot() -> dict[str, Any] | None:
    """Get the latest snapshot, from remote agent if configured, else local cache."""
    if _is_remote_mode():
        try:
            return _get_agent().get_snapshot()
        except AgentError as e:
            # Log and fall back to local cache if remote fails
            app.logger.warning("remote_snapshot_failed", error=str(e))
    return _read_last_result()


def _fetch_identity() -> dict[str, Any]:
    """Get identity info for display: local server_id or remote agent."""
    if _is_remote_mode():
        try:
            return _get_agent().remote_identity()
        except AgentError:
            return {"kind": "remote", "base_url": _remote_url(), "error": "unreachable"}
    return AgentClient.local_identity()


def _fetch_rules_summary() -> dict:
    """Get rules summary. Local only — remote agent uses its own rules."""
    if _is_remote_mode():
        # Remote agent has its own rules; show a placeholder
        return {"_remote": True}
    return _summarize_rules(load_rules())


def _fetch_heartbeat():
    """Read the heartbeat from the local agent (none for remote dashboards)."""
    if _is_remote_mode():
        return None
    try:
        from ipracticom_sweeper.monitor.health import check_health
        return check_health(expected_interval_seconds=300.0)
    except Exception as e:
        app.logger.warning("heartbeat_fetch_failed", error=str(e))
        return None


# --- Notification settings (Telegram + Slack) ----------------------------

NOTIFICATIONS_ENV_FILE = Path("/etc/ipracticom-sweeper/notifications.env")


def _read_notifications_env() -> dict[str, str]:
    """Read /etc/ipracticom-sweeper/notifications.env. Never raises."""
    if not NOTIFICATIONS_ENV_FILE.exists():
        return {}
    out: dict[str, str] = {}
    try:
        for raw in NOTIFICATIONS_ENV_FILE.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError as e:
        app.logger.warning("notifications_env_read_failed", error=str(e))
    return out


def _write_notifications_env(values: dict[str, str]) -> tuple[bool, str | None]:
    """Atomically replace the env file. Returns (ok, error_message)."""
    if not NOTIFICATIONS_ENV_FILE.parent.exists():
        try:
            NOTIFICATIONS_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return False, f"cannot create dir: {e}"

    allowed = {"SLACK_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"}
    lines = [
        "# iPracticom Sweeper notifications config",
        "# Edited via the dashboard at /settings. Hand-edits are preserved between",
        "# automatic sections. The systemd service picks these up on next run.",
        "",
    ]
    # Group by key
    slack = values.get("SLACK_WEBHOOK_URL", "").strip()
    bot = values.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = values.get("TELEGRAM_CHAT_ID", "").strip()

    lines.append("# --- Slack (optional) ---")
    if slack:
        lines.append(f'SLACK_WEBHOOK_URL="{slack}"')
    else:
        lines.append("# SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T000/B000/XXX")
    lines.append("")
    lines.append("# --- Telegram (optional, both required together) ---")
    if bot:
        lines.append(f'TELEGRAM_BOT_TOKEN="{bot}"')
    else:
        lines.append("# TELEGRAM_BOT_TOKEN=123456....")
    if chat:
        lines.append(f'TELEGRAM_CHAT_ID="{chat}"')
    else:
        lines.append("# TELEGRAM_CHAT_ID=-100123456789")
    lines.append("")

    content = "\n".join(lines)
    tmp = NOTIFICATIONS_ENV_FILE.with_suffix(".env.tmp")
    try:
        tmp.write_text(content)
        tmp.chmod(0o600)
        tmp.replace(NOTIFICATIONS_ENV_FILE)
    except OSError as e:
        return False, f"cannot write: {e}"
    return True, None


def _test_telegram(bot_token: str, chat_id: str) -> tuple[bool, str]:
    """Send a test message via Telegram Bot API. Returns (ok, message)."""
    import urllib.request
    import urllib.parse

    if not bot_token or not chat_id:
        return False, "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is empty"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": "iPracticom Sweeper: test notification from dashboard",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", errors="replace")
            if '"ok":true' in body:
                return True, "Telegram OK"
            return False, f"Telegram rejected: {body[:200]}"
    except Exception as e:
        return False, f"Telegram error: {e}"


def _test_slack(webhook_url: str) -> tuple[bool, str]:
    """Send a test message via Slack incoming webhook. Returns (ok, message)."""
    import urllib.request
    import json as _json

    if not webhook_url:
        return False, "SLACK_WEBHOOK_URL is empty"
    payload = _json.dumps({"text": "iPracticom Sweeper: test notification from dashboard"}).encode("utf-8")
    try:
        req = urllib.request.Request(
            webhook_url, data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status == 200:
                return True, "Slack OK"
            return False, f"Slack returned HTTP {r.status}"
    except Exception as e:
        return False, f"Slack error: {e}"


# --- Routes ------------------------------------------------------------------


@app.route("/")
def index():
    """Main dashboard — single-page view of the latest sweep."""
    result = _fetch_snapshot()
    identity = _fetch_identity()
    rules_summary = _fetch_rules_summary()
    heartbeat = _fetch_heartbeat()

    return render_template(
        "dashboard.html",
        result=result,
        identity=identity,
        is_remote=_is_remote_mode(),
        rules_summary=rules_summary,
        heartbeat=heartbeat,
        now_iso=datetime.now(timezone.utc).isoformat(),
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    """Notification configuration (Telegram + Slack). Local-only."""
    if _is_remote_mode():
        return render_template("error.html", message="הגדרות זמינות רק במצב מקומי"), 403

    saved_message = None
    error_message = None
    if request.method == "POST":
        # Save action
        values = {
            "SLACK_WEBHOOK_URL": request.form.get("slack_webhook_url", ""),
            "TELEGRAM_BOT_TOKEN": request.form.get("telegram_bot_token", ""),
            "TELEGRAM_CHAT_ID": request.form.get("telegram_chat_id", ""),
        }
        ok, err = _write_notifications_env(values)
        if ok:
            saved_message = "ההגדרות נשמרו. הסוכן יטען אותן בריצה הבאה (עד 5 דקות)."
        else:
            error_message = err or "שגיאה לא ידועה בכתיבה"

    current = _read_notifications_env()
    return render_template(
        "settings.html",
        identity=_fetch_identity(),
        is_remote=_is_remote_mode(),
        current=current,
        saved_message=saved_message,
        error_message=error_message,
    )


@app.route("/settings/test", methods=["POST"])
def settings_test():
    """Test the current (or just-saved) notification channels. Returns JSON."""
    if _is_remote_mode():
        return jsonify({"ok": False, "error": "settings are local-only"}), 403
    current = _read_notifications_env()
    channel = request.form.get("channel", "")
    if channel == "telegram":
        ok, msg = _test_telegram(
            current.get("TELEGRAM_BOT_TOKEN", ""),
            current.get("TELEGRAM_CHAT_ID", ""),
        )
    elif channel == "slack":
        ok, msg = _test_slack(current.get("SLACK_WEBHOOK_URL", ""))
    else:
        return jsonify({"ok": False, "error": "unknown channel"}), 400
    return jsonify({"ok": ok, "message": msg})


@app.route("/history")
def history():
    """List recent sweep results + repairs + proposals. In remote mode, fetches from agent."""
    runs = _load_history_runs()
    repairs = _load_history_repairs()
    proposals = _load_history_proposals()

    return render_template(
        "history.html",
        runs=runs,
        repairs=repairs,
        proposals=proposals,
        identity=_fetch_identity(),
        is_remote=_is_remote_mode(),
        now_iso=datetime.now(timezone.utc).isoformat(),
    )


@app.route("/run")
def run_view():
    """JSON view of the latest pipeline result (cached)."""
    result = _read_last_result()
    if not result:
        return jsonify({"error": "no cached result"}), 404
    return jsonify(result)


@app.route("/run/now", methods=["GET", "POST"])
def run_now():
    """Trigger a fresh sweep. In remote mode, asks the remote agent.

    Returns JSON by default; redirects to dashboard when called from the UI
    (?ui=1 or Accept: text/html).
    """
    wants_html = (
        request.args.get("ui") == "1"
        or "text/html" in request.headers.get("Accept", "")
    )

    if _is_remote_mode():
        try:
            result = _get_agent().trigger_run()
        except AgentError as e:
            if wants_html:
                return render_template("error.html", message=str(e)), 502
            return jsonify({"error": str(e)}), 502
        if wants_html:
            return _redirect_to_dashboard()
        return jsonify(result)

    try:
        result = trigger_pipeline_run()
    except Exception as e:
        app.logger.exception("run_now_failed")
        if wants_html:
            return render_template("error.html", message=str(e)), 500
        return jsonify({"error": str(e)}), 500

    if wants_html:
        return _redirect_to_dashboard()
    return jsonify(result)


def _redirect_to_dashboard():
    from flask import redirect, url_for
    return redirect(url_for("index"))


@app.route("/api/snapshot")
def api_snapshot():
    """Same as /run — alias for consistency with agent API."""
    return run_view()


@app.route("/api/notify/test", methods=["POST"])
def api_notify_test():
    """Send a test notification. In remote mode, asks the remote agent."""
    if _is_remote_mode():
        try:
            return jsonify(_get_agent().send_test_notify())
        except AgentError as e:
            return jsonify({"error": str(e)}), 502

    import asyncio
    from ipracticom_sweeper.notify import notify_pipeline_result

    result = _read_last_result()
    if not result:
        return jsonify({"error": "no cached result to use as template"}), 404

    try:
        sent = asyncio.run(notify_pipeline_result(result, force=True))
        return jsonify({"sent": sent})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/approvals")
def approvals_view():
    """List all pending repair proposals awaiting operator approval."""
    if _is_remote_mode():
        return render_template("error.html", message="אישורים זמינים רק במצב מקומי"), 403

    from ipracticom_sweeper.repair.pending import list_pending, cleanup_stale_pending
    cleanup_stale_pending()

    return render_template(
        "approvals.html",
        identity=_fetch_identity(),
        is_remote=_is_remote_mode(),
        pending=list_pending(),
        now_iso=datetime.now(timezone.utc).isoformat(),
    )


@app.route("/approvals/<pid>")
def approval_detail(pid):
    """Single-proposal detail view with full context."""
    if _is_remote_mode():
        return render_template("error.html", message="אישורים זמינים רק במצב מקומי"), 403

    from ipracticom_sweeper.repair.pending import get_proposal
    p = get_proposal(pid)
    if p is None:
        return render_template("error.html", message=f"בקשה {pid} לא נמצאה"), 404
    return render_template(
        "approval_detail.html",
        identity=_fetch_identity(),
        is_remote=_is_remote_mode(),
        proposal=p,
        now_iso=datetime.now(timezone.utc).isoformat(),
    )


@app.route("/approvals/<pid>/approve", methods=["POST"])
def approval_approve(pid):
    """Approve a pending repair: run it, log the action, archive the proposal."""
    if _is_remote_mode():
        return render_template("error.html", message="אישורים זמינים רק במצב מקומי"), 403

    from ipracticom_sweeper.repair import execute_repair
    from ipracticom_sweeper.repair.pending import (
        archive, get_proposal, log_audit, set_status,
    )

    p = get_proposal(pid)
    if p is None:
        return render_template("error.html", message=f"בקשה {pid} לא נמצאה"), 404
    if p.status != "pending":
        return render_template("error.html", message=f"הבקשה כבר {p.status}"), 409

    actor = request.form.get("actor") or os.environ.get("DASHBOARD_USER") or "operator"
    log_audit({
        "kind": "repair_approved",
        "actor": actor,
        "proposal_id": pid,
        "action": p.action,
        "kwargs": p.kwargs,
    })

    try:
        result = execute_repair(p.action, **p.kwargs)
        set_status(pid, "executed")
        archive(pid, "approved")
        log_audit({
            "kind": "repair_executed",
            "actor": actor,
            "proposal_id": pid,
            "action": result.action,
            "target": result.target,
            "success": result.success,
            "duration_ms": result.duration_ms,
            "snapshot_id": result.snapshot_id,
            "error": result.error,
            "message": result.message,
        })
        return _redirect_to_dashboard()
    except Exception as e:
        app.logger.exception("approval_execute_failed")
        set_status(pid, "failed")
        log_audit({
            "kind": "repair_failed",
            "actor": actor,
            "proposal_id": pid,
            "action": p.action,
            "kwargs": p.kwargs,
            "error": str(e),
        })
        return render_template("error.html", message=f"שגיאה בביצוע: {e}"), 500


@app.route("/approvals/<pid>/reject", methods=["POST"])
def approval_reject(pid):
    """Reject a pending repair: archive, log, do not execute."""
    if _is_remote_mode():
        return render_template("error.html", message="אישורים זמינים רק במצב מקומי"), 403

    from ipracticom_sweeper.repair.pending import (
        archive, get_proposal, log_audit, set_status,
    )

    p = get_proposal(pid)
    if p is None:
        return render_template("error.html", message=f"בקשה {pid} לא נמצאה"), 404
    if p.status != "pending":
        return render_template("error.html", message=f"הבקשה כבר {p.status}"), 409

    actor = request.form.get("actor") or os.environ.get("DASHBOARD_USER") or "operator"
    reason = request.form.get("reason", "")

    set_status(pid, "rejected")
    archive(pid, "rejected")
    log_audit({
        "kind": "repair_rejected",
        "actor": actor,
        "proposal_id": pid,
        "action": p.action,
        "kwargs": p.kwargs,
        "reason": reason,
    })
    return _redirect_to_dashboard()


@app.route("/healthz")
def healthz():
    """Liveness check. In remote mode, proxies to remote agent."""
    if _is_remote_mode():
        try:
            remote = _get_agent().healthz()
            remote["mode"] = "remote"
            remote["dashboard_id"] = get_server_id()
            return jsonify(remote)
        except AgentError as e:
            return jsonify({
                "ok": False,
                "mode": "remote",
                "remote_url": _remote_url(),
                "error": str(e),
            }), 503
    return jsonify({
        "ok": True,
        "mode": "local",
        "server_id": get_server_id(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "last_result_age_sec": _last_result_age_sec(),
    })


# --- Helpers -----------------------------------------------------------------


# --- History loaders -------------------------------------------------------


def _load_history_runs() -> list[dict]:
    """Load recent sweep results from the monitor audit log."""
    if _is_remote_mode():
        try:
            raw_events = _get_agent().get_audit_events()
            runs = []
            for line in raw_events:
                try:
                    ev = json.loads(line)
                    runs.append({
                        "ts": ev.get("ts", ""),
                        "module": ev.get("module", ""),
                        "status": ev.get("status", ""),
                    })
                except json.JSONDecodeError:
                    continue
            return runs
        except AgentError:
            return []

    audit_log = Path("/var/lib/ipracticom-sweeper/audit/monitor.jsonl")
    if not audit_log.exists():
        return []
    runs = []
    try:
        with open(audit_log) as f:
            lines = f.readlines()[-100:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                runs.append({
                    "ts": ev.get("ts", ""),
                    "module": ev.get("module", ""),
                    "status": ev.get("status", ""),
                })
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return runs


def _load_history_repairs() -> list[dict]:
    """Load recent repair events from the repairs audit log.

    Returns list of dicts sorted newest-first, each with:
      ts, kind (proposed/approved/executed/failed/rejected), action, target,
      actor (auto/operator), success, message, error, proposal_id, duration_ms
    """
    audit_log = Path("/var/lib/ipracticom-sweeper/audit/repairs.jsonl")
    if not audit_log.exists():
        return []
    out = []
    try:
        with open(audit_log) as f:
            lines = f.readlines()[-200:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append({
                "ts": ev.get("logged_at", ""),
                "kind": ev.get("kind", ""),
                "action": ev.get("action", ""),
                "target": ev.get("target") or (ev.get("kwargs") or {}).get("unit", ""),
                "actor": ev.get("actor", "?"),
                "proposal_id": ev.get("proposal_id", ""),
                "success": ev.get("success"),
                "duration_ms": ev.get("duration_ms"),
                "message": ev.get("message", ""),
                "error": ev.get("error", ""),
                "reason": ev.get("reason", ""),
            })
    except OSError:
        pass
    out.sort(key=lambda x: x.get("ts") or "", reverse=True)
    return out


def _load_history_proposals() -> list[dict]:
    """Load all repair proposals (pending + approved + rejected) for the
    proposals table. Newest first.
    """
    out = []
    try:
        from ipracticom_sweeper.repair.pending import PENDING_DIR, APPROVED_DIR, REJECTED_DIR
        for subdir, status in (
            (PENDING_DIR, "pending"),
            (APPROVED_DIR, "approved"),
            (REJECTED_DIR, "rejected"),
        ):
            if not subdir.exists():
                continue
            for p in subdir.glob("*.json"):
                try:
                    data = json.loads(p.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                out.append({
                    "id": data.get("id", p.stem),
                    "action": data.get("action", ""),
                    "kwargs": data.get("kwargs", {}),
                    "reason": data.get("reason", ""),
                    "created_at": data.get("created_at", ""),
                    "status": data.get("status", status),
                })
    except Exception:
        pass
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out


def _last_result_age_sec() -> int | None:
    if not LAST_RESULT_FILE.exists():
        return None
    age = time.time() - LAST_RESULT_FILE.stat().st_mtime
    return int(age)


def _summarize_rules(rules: dict) -> dict[str, dict]:
    """Compact summary of thresholds for the sidebar."""
    summary = {}
    for module in ("cpu", "memory", "disk", "services", "security"):
        section = rules.get(module, {})
        # Take only the warn/crit thresholds
        summary[module] = {
            k: v for k, v in section.items()
            if "warn" in k or "crit" in k or "list" in k
        }
    return summary


# --- Fleet view --------------------------------------------------------------


def _fleet_urls() -> list[str]:
    """Read SWEEPER_FLEET_URLS env var (comma-separated)."""
    import os

    raw = os.environ.get("SWEEPER_FLEET_URLS", "")
    return [u.strip() for u in raw.split(",") if u.strip()]


def _fetch_fleet_snapshots() -> list[dict[str, Any]]:
    """Fetch snapshots from all configured fleet agents.

    In local mode (no SWEEPER_FLEET_URLS), returns the local snapshot as a
    single-host fleet.
    """
    urls = _fleet_urls()
    if not urls:
        local = _fetch_snapshot()
        return [local] if local else []

    snapshots = []
    for url in urls:
        try:
            client = AgentClient(url, token=_remote_token())
            snap = client.get_snapshot()
            if snap:
                snapshots.append(snap)
        except Exception as e:
            # One bad agent shouldn't break the whole fleet view
            print(f"[dashboard] fleet fetch failed for {url}: {e}")
    return snapshots


@app.route("/fleet")
def fleet_view():
    """Multi-host overview — shows one card per configured connector.

    Reads per-host snapshots from $IPRACTICOM_SWEEPER_STATE_DIR/fleet/snapshots/
    (written by the collector loop). Falls back to legacy SWEEPER_FLEET_URLS
    behavior when no connectors are configured.

    Empty state: link to /settings/connectors.
    """
    from ipracticom_sweeper.fleet import aggregate, load_all_snapshots

    connectors = load_connectors()
    snapshots_raw = load_all_snapshots()  # list of {name, collected_at, snapshot}

    # Convert raw snapshots → aggregator format. We build a HostSnapshot-shaped
    # object on the fly because load_all_snapshots stores the dict form already.
    converted = []
    raw_by_name = {s["name"]: s for s in snapshots_raw}
    for conn in connectors:
        if conn.name not in raw_by_name:
            # No data yet for this connector — show as unavailable
            from ipracticom_sweeper.fleet.aws_connector import HostSnapshot
            converted.append(
                _ssm_unavailable(conn.name, "no data yet — waiting for first collection")
            )
            continue
        entry = raw_by_name[conn.name]
        snap_dict = entry.get("snapshot", {})
        if not snap_dict.get("available", False):
            converted.append(_ssm_unavailable(conn.name, snap_dict.get("reason", "unknown")))
            continue
        # Reconstruct a HostSnapshot-ish object for the adapter
        class _Snap:
            pass
        s = _Snap()
        s.available = True
        s.data = snap_dict.get("data") or {}
        s.reason = ""
        converted.append(
            __import__("ipracticom_sweeper.fleet", fromlist=["ssm_to_aggregator_format"])
            .ssm_to_aggregator_format(conn.name, s)
        )

    summary = aggregate(converted)
    identity = _fetch_identity()
    return render_template(
        "fleet.html",
        summary=summary,
        snapshots=converted,
        connectors=connectors,
        raw_snapshots=snapshots_raw,
        identity=identity,
        now_iso=datetime.now(timezone.utc).isoformat(),
    )


def _ssm_unavailable(name: str, reason: str) -> dict[str, Any]:
    """Build an aggregator-format dict representing 'we couldn't reach this host'."""
    return {
        "server": name,
        "defcon": 1,
        "defcon_label": "red",
        "problems_found": 1,
        "ts": 0.0,
        "modules": {"ssm": "crit"},
        "_reason": reason,
    }


@app.route("/fleet/host/<name>")
def fleet_host_detail(name: str):
    """Per-host detail (used by the modal in fleet.html).

    Returns a JSON object with: connector metadata, latest snapshot data,
    run history (from audit log), repair history (filtered by host), and
    pending approvals (filtered by host when metadata.host matches).
    """
    from ipracticom_sweeper.fleet import load_snapshot
    from ipracticom_sweeper.config import get_connector

    conn = get_connector(name)
    if conn is None:
        return jsonify({"error": "not_found", "name": name}), 404

    snap = load_snapshot(name) or {}
    raw = snap.get("snapshot", {}) if snap else {}

    # Run history: read the global audit log, filter by mentions of this host.
    # The local box audit log captures all runs; for SSM-collected hosts the
    # "runs" are the collector cycles. We return both as a unified timeline.
    audit_path = "/var/lib/ipracticom-sweeper/audit/repairs.jsonl"
    repairs = []
    try:
        import json
        with open(audit_path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Match if name appears in any field (best-effort for SSM hosts
                # where the host field might equal instance_id)
                if name in json.dumps(entry) or conn.instance_id in json.dumps(entry):
                    repairs.append(entry)
        repairs = repairs[-50:]
    except FileNotFoundError:
        pass

    # Pending approvals
    pending = []
    try:
        from ipracticom_sweeper.repair import pending as pending_mod
        for p in pending_mod.list_pending():
            if name in str(p) or conn.instance_id in str(p):
                pending.append(p)
    except Exception:
        pass

    return jsonify({
        "name": name,
        "connector": conn.to_dict(),
        "snapshot": raw,
        "snapshot_age_seconds": (time.time() - snap.get("collected_at", 0)) if snap else None,
        "repairs": repairs,
        "pending_approvals": pending,
    })


# --- Connectors settings (AWS SSM) -------------------------------------

@app.route("/settings/connectors", methods=["GET", "POST"])
def settings_connectors():
    """Manage AWS SSM connectors (remote hosts to monitor).

    Local mode: writes directly to connectors.yaml via config module.
    Remote mode: proxies through AgentClient to the remote agent API.
    """
    is_remote = _is_remote_mode()
    saved_message = None
    error_message = None

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "delete":
            name = (request.form.get("name") or "").strip()
            if not name:
                error_message = "חסר שם connector"
            else:
                try:
                    if is_remote:
                        _get_agent().delete_connector(name)
                    else:
                        if not remove_connector(name):
                            error_message = f"connector '{name}' לא נמצא"
                    if not error_message:
                        saved_message = f"connector '{name}' נמחק"
                except AgentError as e:
                    error_message = f"מחיקה נכשלה: {e}"

        elif action == "toggle":
            name = (request.form.get("name") or "").strip()
            enabled = request.form.get("enabled") == "1"
            if not name:
                error_message = "חסר שם connector"
            else:
                try:
                    if is_remote:
                        _get_agent().update_connector(name, {"enabled": enabled})
                    else:
                        update_connector(name, enabled=enabled)
                    saved_message = f"connector '{name}' עודכן"
                except (AgentError, KeyError, ValueError) as e:
                    error_message = f"עדכון נכשל: {e}"

        elif action == "test":
            name = (request.form.get("name") or "").strip()
            if not name:
                error_message = "חסר שם connector"
            else:
                try:
                    if is_remote:
                        result = _get_agent().test_connector(name)
                    else:
                        # Local: call the same logic the API uses
                        from ipracticom_sweeper.config import (
                            get_connector,
                            mark_connector_collected,
                            mark_connector_error,
                        )
                        from ipracticom_sweeper.fleet import AwsSsmConnector, SsmError
                        c = get_connector(name)
                        if c is None:
                            error_message = f"connector '{name}' לא נמצא"
                        else:
                            try:
                                ssm = AwsSsmConnector(region=c.region)
                                result = {"ok": True, "snapshot": ssm.collect_one(c.instance_id)}
                                mark_connector_collected(name)
                            except SsmError as e:
                                mark_connector_error(name, str(e))
                                error_message = f"SSM: {e}"
                except AgentError as e:
                    error_message = f"בדיקה נכשלה: {e}"

        elif action == "create":
            name = (request.form.get("name") or "").strip()
            instance_id = (request.form.get("instance_id") or "").strip()
            region = (request.form.get("region") or "il-central-1").strip()
            tags_raw = (request.form.get("tags") or "").strip()
            if not name or not instance_id:
                error_message = "חובה למלא שם ו-instance_id"
            else:
                tags = {}
                if tags_raw:
                    for pair in tags_raw.split(","):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            tags[k.strip()] = v.strip()
                try:
                    if is_remote:
                        _get_agent().create_connector({
                            "name": name, "instance_id": instance_id,
                            "region": region, "tags": tags, "enabled": True,
                        })
                    else:
                        add_connector(Connector(
                            name=name, instance_id=instance_id,
                            region=region, tags=tags, enabled=True,
                        ))
                    saved_message = f"connector '{name}' נוסף"
                except (AgentError, ValueError) as e:
                    error_message = f"הוספה נכשלה: {e}"

    # Reload connectors for display (post-mutation)
    try:
        if is_remote:
            connectors = _get_agent().list_connectors()
        else:
            connectors = [c.to_dict() for c in load_connectors()]
    except AgentError as e:
        connectors = []
        error_message = f"טעינה נכשלה: {e}"

    return render_template(
        "connectors.html",
        connectors=connectors,
        is_remote=is_remote,
        identity=_fetch_identity(),
        saved_message=saved_message,
        error_message=error_message,
    )


# --- Catalogue (read-only check registry) ---------------------------------


@app.route("/catalogue")
def catalogue_view():
    """Catalogue index — list of registered checks (v0.5.0 slice 1.2).

    Additive route. Shows every check we know about, with current threshold
    param counts loaded from rules.yaml. Read-only — operators inspect what
    exists; editing the live file is a future slice.
    """
    from ipracticom_sweeper.catalogue import render_catalogue
    from ipracticom_sweeper.config import load_rules

    try:
        rules = load_rules() or {}
    except Exception:
        rules = {}

    checks = render_catalogue(rules)

    return render_template(
        "catalogue.html",
        mode="index",
        checks=checks,
        identity=_fetch_identity(),
    )


@app.route("/catalogue/<module_key>")
def catalogue_module(module_key: str):
    """Per-check editor view (v0.5.0 slice 1.2).

    Additive route. Shows the rule_keys defined for a module and their current
    values from rules.yaml. Read-only — changing values requires a separate
    write/approval flow.
    """
    from ipracticom_sweeper.catalogue import render_check
    from ipracticom_sweeper.config import load_rules

    try:
        rules = load_rules() or {}
    except Exception:
        rules = {}

    data = render_check(module_key, rules)
    if data is None:
        return jsonify({"error": "unknown_module", "key": module_key}), 404

    return render_template(
        "catalogue.html",
        mode="module",
        module_key=module_key,
        entry=data["entry"],
        params=data["params"],
        all_current=data["all_current"],
        identity=_fetch_identity(),
    )


# --- Inspector (per-host check inspection) ---------------------------------


@app.route("/inspector")
def inspector_view():
    """Per-host check inspector — pick a host, see modules + their last status.

    Additive route for v0.5.0 slice 1.1. Renders the local host's last
    snapshot modules (cpu/memory/disk/...) and lists configured connectors so
    operators can pick a remote host to inspect via /inspector/host/<name>.

    Empty state: links to /settings/connectors if no hosts are configured.
    """
    from ipracticom_sweeper.config import load_connectors

    connectors = load_connectors()

    # Local snapshot (last pipeline result) — extract module summary
    local_snapshot = _read_last_result() or {}
    local_modules = []
    for module_key, module_data in (local_snapshot.get("modules") or {}).items():
        if not isinstance(module_data, dict):
            continue
        local_modules.append({
            "key": module_key,
            "status": module_data.get("status", "unknown"),
            "summary": _summarize_module(module_data),
        })
    local_modules.sort(key=lambda m: m["key"])

    return render_template(
        "inspector.html",
        host="localhost",
        module_kind="local",
        connectors=connectors,
        modules=local_modules,
        snapshot_age=_last_result_age_sec(),
        identity=_fetch_identity(),
    )


@app.route("/inspector/host/<name>")
def inspector_host(name: str):
    """Per-host inspector — shows the latest snapshot modules for a remote host.

    Additive route for v0.5.0 slice 1.1. Reads collector snapshot via fleet
    module, then drills into modules + their values for operator inspection.

    Empty state: 404 if the connector is not configured.
    """
    from ipracticom_sweeper.config import get_connector
    from ipracticom_sweeper.fleet import load_snapshot

    conn = get_connector(name)
    if conn is None:
        return jsonify({"error": "not_found", "name": name}), 404

    snap = load_snapshot(name) or {}
    raw = snap.get("snapshot", {}) if snap else {}
    modules_data = raw.get("modules") or {}

    modules = []
    for module_key, module_data in modules_data.items():
        if not isinstance(module_data, dict):
            continue
        modules.append({
            "key": module_key,
            "status": module_data.get("status", "unknown"),
            "summary": _summarize_module(module_data),
            "values": module_data.get("values", {}),
        })
    modules.sort(key=lambda m: m["key"])

    from ipracticom_sweeper.config import load_connectors
    connectors = load_connectors()

    return render_template(
        "inspector.html",
        host=name,
        module_kind="remote",
        connectors=connectors,
        modules=modules,
        snapshot_age=(time.time() - snap.get("collected_at", 0)) if snap else None,
        identity=_fetch_identity(),
    )


def _summarize_module(module_data: dict) -> str:
    """One-line Hebrew summary for a module dict.

    Additive helper for v0.5.0 slice 1.1. Looks for the first scalar numeric
    value or the first string in `values` and returns a short label. If nothing
    useful is found, returns the module status string.
    """
    values = module_data.get("values") or {}
    # Prefer a primary scalar if present
    for key in ("cpu.idle_percent", "memory.used_percent", "disk.used_percent"):
        v = values.get(key)
        if isinstance(v, (int, float)):
            if "cpu.idle" in key:
                return f"idle {v:.0f}%"
            if "memory.used" in key:
                return f"used {v:.0f}%"
            if "disk.used" in key:
                return f"used {v:.0f}%"
    # Fallback: first numeric or short string
    for k, v in values.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return f"{k}={v}"
        if isinstance(v, str) and 0 < len(v) <= 40:
            return f"{k}={v[:40]}"
        if isinstance(v, list) and v:
            return f"{k} ({len(v)})"
    return module_data.get("status", "unknown")


# --- CLI entry point ---------------------------------------------------------


def main():
    """Run the dashboard. Default 127.0.0.1:8787 (no auth — bind to localhost)."""
    import argparse

    parser = argparse.ArgumentParser(description="iPracticom Sweeper Dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()