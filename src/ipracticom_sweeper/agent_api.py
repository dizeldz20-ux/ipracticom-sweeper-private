"""Agent HTTP API.

Exposes the sweeper state over HTTP so that remote dashboards (or any
HTTP client) can read the current state without shell access. This is
the same API the dashboard already exposes locally — but packaged as
a standalone, auth-protected service.

Routes (all return JSON):
  GET  /healthz                  liveness + identity
  GET  /api/snapshot             latest cached pipeline result
  GET  /api/notify/test          (admin only) send a test notification
  POST /api/run                  (admin only) trigger a fresh sweep

Auth: bearer token via env var AGENT_API_TOKEN. If unset, the API
runs in OPEN mode (intended for local-only deployments behind a
firewall; the bind address defaults to 127.0.0.1).

Usage:
  AGENT_API_TOKEN=secret python -m ipracticom_sweeper.agent_api --port 8787

This service is independent of the dashboard — it does not render
HTML. The dashboard, when configured with `remote_url`, will fetch
from this service instead of running the pipeline locally.
"""

from __future__ import annotations

import argparse
import hmac
import os
from datetime import datetime, timezone
from functools import wraps
from typing import Any

from flask import Flask, abort, jsonify, request

from ipracticom_sweeper.config import (
    Connector,
    add_connector,
    get_connector,
    get_server_id,
    load_connectors,
    load_rules,
    mark_connector_collected,
    mark_connector_error,
    remove_connector,
    update_connector,
)
from ipracticom_sweeper.dashboard import (
    CACHE_DIR,
    LAST_RESULT_FILE,
    _read_last_result,
    _write_last_result,
)
from ipracticom_sweeper.pipeline import run_pipeline
from ipracticom_sweeper.slack_actions.endpoint import SlackEndpoint
from ipracticom_sweeper.slack_actions.commands import SlackCommandHandler


def _read_heartbeat(state_dir) -> dict[str, Any] | None:
    """Read /heartbeat.json if it exists, else return None.

    Heartbeat is written by the pipeline loop after every sweep — it's
    the cheapest way to know "is this host alive" without running the
    whole pipeline again.
    """
    import json as _json
    path = state_dir / "heartbeat.json"
    if not path.exists():
        return None
    try:
        return _json.loads(path.read_text())
    except Exception:
        return None


def _local_status(heartbeat: dict[str, Any] | None) -> str:
    """Classify the local host's status from its heartbeat.

    Rules:
      - no heartbeat / very old heartbeat → "unknown" or "stale"
      - defcon <= 3 → "warn" / "crit"
      - problems_found > 0 → "warn"
      - else → "ok"
    """
    if heartbeat is None:
        return "unknown"
    try:
        defcon = int(heartbeat.get("defcon", 5))
    except (TypeError, ValueError):
        defcon = 5
    if defcon <= 2:
        return "crit"
    if defcon == 3 or int(heartbeat.get("problems_found") or 0) > 0:
        return "warn"
    return "ok"


def create_app() -> Flask:
    app = Flask(__name__)
    token = os.environ.get("AGENT_API_TOKEN", "")

    def require_auth(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not token:
                # OPEN mode (no token configured) — caller should bind to localhost
                return fn(*args, **kwargs)
            provided = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(provided, token):
                return jsonify({"error": "unauthorized"}), 401
            return fn(*args, **kwargs)
        return wrapper

    # --- Healthz -----------------------------------------------------------

    @app.route("/healthz")
    def healthz():
        return jsonify({
            "ok": True,
            "service": "ipracticom-sweeper-agent",
            "server_id": get_server_id(),
            "ts": datetime.now(timezone.utc).isoformat(),
            "auth": "token" if token else "open",
        })

    # --- Snapshot ----------------------------------------------------------

    @app.route("/api/snapshot")
    @require_auth
    def api_snapshot():
        result = _read_last_result()
        if not result:
            return jsonify({"error": "no cached snapshot"}), 404
        return jsonify(result)

    @app.route("/api/snapshot/raw")
    @require_auth
    def api_snapshot_raw():
        """Return the raw JSONL monitor events (audit log)."""
        log_path = "/var/lib/ipracticom-sweeper/audit/monitor.jsonl"
        events = []
        try:
            with open(log_path) as f:
                events = [line.strip() for line in f if line.strip()][-100:]
        except FileNotFoundError:
            return jsonify({"error": "no audit log yet", "events": []}), 200
        return jsonify({"events": events, "count": len(events)})

    # --- Run trigger -------------------------------------------------------

    @app.route("/api/run", methods=["POST", "GET"])
    @require_auth
    def api_run():
        """Trigger a fresh sweep, cache the result, return it."""
        try:
            from ipracticom_sweeper.config import load_rules

            rules = load_rules()
            result = run_pipeline(rules, auto_repair=True, dry_run=False)
            d = result.to_dict()
            d["server"] = get_server_id()
            _write_last_result(d)
            return jsonify(d)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # --- Notify (admin only, gated by token) -------------------------------

    @app.route("/api/notify/test", methods=["POST"])
    @require_auth
    def api_notify_test():
        import asyncio
        from ipracticom_sweeper.notify import notify_pipeline_result

        result = _read_last_result()
        if not result:
            return jsonify({"error": "no cached snapshot"}), 404
        try:
            sent = asyncio.run(notify_pipeline_result(result, force=True))
            return jsonify({"sent": sent})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # --- Slack Events endpoint -------------------------------------------
    # Receives button clicks from Slack (Approve / Silence / Run Repair).
    # Verifies the X-Slack-Signature using SLACK_SIGNING_SECRET, parses the
    # block_actions payload, and dispatches to SlackActionHandler.
    #
    # This endpoint is intentionally NOT gated by AGENT_API_TOKEN — Slack
    # authenticates via request signing, not bearer tokens. We *do* require
    # a valid signature (HMAC-SHA256) which is cryptographically stronger.

    @app.route("/slack/events", methods=["POST"])
    def slack_events():
        signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
        if not signing_secret:
            return jsonify({
                "error": "slack_not_configured",
                "reason": "SLACK_SIGNING_SECRET env var is empty",
            }), 503

        # Build the command handler lazily so imports stay fast for agents
        # that never receive Slack commands.
        command_handler = SlackCommandHandler()
        endpoint = SlackEndpoint()
        # Read raw body BEFORE Flask parses it (we need the exact bytes for HMAC)
        raw_body = request.get_data(cache=True) or b""
        response = endpoint.handle_request(
            body=raw_body,
            timestamp_header=request.headers.get("X-Slack-Request-Timestamp"),
            signature_header=request.headers.get("X-Slack-Signature"),
            signing_secret=signing_secret,
            command_handler=command_handler,
        )
        return jsonify(response.body), response.status_code

    # --- Connectors (AWS SSM) ----------------------------------------------
    # CRUD for remote hosts the operator wants the agent to monitor via SSM.
    # Stored in $IPRACTICOM_SWEEPER_STATE_DIR/connectors.yaml.

    @app.route("/api/connectors", methods=["GET"])
    @require_auth
    def api_connectors_list():
        """List all configured SSM connectors."""
        return jsonify([c.to_dict() for c in load_connectors()])

    @app.route("/api/connectors", methods=["POST"])
    @require_auth
    def api_connectors_create():
        """Create a new connector. Body: {name, instance_id, region?, tags?, enabled?}"""
        payload = request.get_json(silent=True) or {}
        try:
            connector = Connector.from_dict(payload)
        except (ValueError, TypeError) as e:
            return jsonify({"error": str(e)}), 400
        try:
            add_connector(connector)
        except ValueError as e:  # duplicate name
            return jsonify({"error": str(e)}), 409
        return jsonify(connector.to_dict()), 201

    @app.route("/api/connectors/<name>", methods=["GET"])
    @require_auth
    def api_connectors_get(name):
        """Get one connector by name."""
        c = get_connector(name)
        if c is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(c.to_dict())

    @app.route("/api/connectors/<name>", methods=["PATCH"])
    @require_auth
    def api_connectors_update(name):
        """Update fields on a connector. Body: any subset of mutable fields.

        Immutable: name (it's the identity), created_at.
        """
        payload = request.get_json(silent=True) or {}
        try:
            updated = update_connector(name, **payload)
        except KeyError:
            return jsonify({"error": "not_found"}), 404
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(updated.to_dict())

    @app.route("/api/connectors/<name>", methods=["DELETE"])
    @require_auth
    def api_connectors_delete(name):
        """Delete a connector. Returns 204 on success, 404 if not found."""
        if not remove_connector(name):
            return jsonify({"error": "not_found"}), 404
        return ("", 204)

    @app.route("/api/connectors/<name>/test", methods=["POST"])
    @require_auth
    def api_connectors_test(name):
        """Trigger a single SSM collection for one connector (sync, may take 5-30s).

        Used by the dashboard 'Test' button — gives operators immediate feedback
        whether their IAM/SSM setup works, instead of waiting for the next loop tick.
        """
        c = get_connector(name)
        if c is None:
            return jsonify({"error": "not_found"}), 404
        try:
            from ipracticom_sweeper.fleet import AwsSsmConnector, SsmError
            connector = AwsSsmConnector(region=c.region)
            snapshot = connector.collect_one(c.instance_id)
            mark_connector_collected(name)
            return jsonify({"ok": True, "snapshot": snapshot})
        except SsmError as e:
            mark_connector_error(name, str(e))
            return jsonify({"ok": False, "error": str(e)}), 502
        except Exception as e:
            mark_connector_error(name, str(e))
            return jsonify({"ok": False, "error": str(e)}), 500

    # URL verification handshake (Slack sends this once when registering the URL).
    # We reply with the challenge value to confirm we own this endpoint.
    @app.route("/slack/events", methods=["GET"])
    def slack_events_challenge():
        challenge = request.args.get("challenge", "")
        return challenge, 200, {"Content-Type": "text/plain"}

    # Time-series history endpoint — read scalar metrics collected over time
    @app.route("/api/history/<metric>", methods=["GET"])
    @require_auth
    def api_history(metric):
        """Return time-series samples for a single metric.

        Query params:
          host:   host id (default: current host)
          hours:  how far back to look (default 24, max 720)
          limit:  max samples (default 1000)
        """
        from pathlib import Path
        from ipracticom_sweeper.storage import TimeSeriesDB

        host = request.args.get("host") or os.environ.get(
            "IPRACTICOM_SWEEPER_HOST_ID", "localhost"
        )
        try:
            hours = min(int(request.args.get("hours", "24")), 720)
        except ValueError:
            hours = 24
        try:
            limit = min(int(request.args.get("limit", "1000")), 10000)
        except ValueError:
            limit = 1000

        state_dir = Path(os.environ.get(
            "IPRACTICOM_SWEEPER_STATE_DIR", "/var/lib/ipracticom-sweeper"
        ))
        db_path = state_dir / "metrics.db"
        if not db_path.exists():
            return jsonify({
                "host": host,
                "metric": metric,
                "samples": [],
                "note": "no data yet (db file missing)",
            })

        db = TimeSeriesDB(db_path)
        try:
            since_ts = int(time.time()) - (hours * 3600)
            samples = db.query(host=host, metric=metric, since_ts=since_ts, limit=limit)
            # Reverse so it's oldest-first (for charting)
            samples.reverse()
            return jsonify({
                "host": host,
                "metric": metric,
                "hours": hours,
                "count": len(samples),
                "samples": samples,
            })
        finally:
            db.close()

    # History catalog (v0.4.2) — list distinct metrics + hosts + per-metric counts.
    @app.route("/api/history", methods=["GET"])
    @require_auth
    def api_history_catalog():
        """Return the catalog of available time-series.

        Returns:
          metrics: sorted list of distinct metric names
          hosts:   sorted list of distinct host ids
          metrics_with_counts: [{metric, count, last_value, last_ts}] per metric
          hosts_with_counts:   [{host, count}] per host
          note: present if the metrics.db is missing
        """
        import sqlite3
        from pathlib import Path

        state_dir = Path(os.environ.get(
            "IPRACTICOM_SWEEPER_STATE_DIR", "/var/lib/ipracticom-sweeper"
        ))
        db_path = state_dir / "metrics.db"
        if not db_path.exists():
            return jsonify({
                "metrics": [],
                "hosts": [],
                "metrics_with_counts": [],
                "hosts_with_counts": [],
                "note": "no data yet (db file missing)",
            })

        try:
            conn = sqlite3.connect(str(db_path))
            try:
                conn.row_factory = sqlite3.Row
                # Sanity check the schema — if the table isn't there yet,
                # surface a clean empty response instead of 500.
                tables = {
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "samples" not in tables:
                    return jsonify({
                        "metrics": [],
                        "hosts": [],
                        "metrics_with_counts": [],
                        "hosts_with_counts": [],
                        "note": "no data yet (samples table missing)",
                    })

                metrics = sorted({
                    r[0] for r in conn.execute(
                        "SELECT DISTINCT metric FROM samples"
                    )
                })
                hosts = sorted({
                    r[0] for r in conn.execute(
                        "SELECT DISTINCT host FROM samples"
                    )
                })
                metrics_with_counts = [
                    dict(r) for r in conn.execute(
                        """
                        SELECT metric,
                               COUNT(*) AS count,
                               (SELECT value FROM samples s2
                                  WHERE s2.metric = s1.metric
                                  ORDER BY ts DESC LIMIT 1) AS last_value,
                               MAX(ts) AS last_ts
                          FROM samples s1
                         GROUP BY metric
                         ORDER BY metric
                        """
                    )
                ]
                hosts_with_counts = [
                    dict(r) for r in conn.execute(
                        """
                        SELECT host, COUNT(*) AS count, MAX(ts) AS last_ts
                          FROM samples
                         GROUP BY host
                         ORDER BY host
                        """
                    )
                ]
            finally:
                conn.close()
        except sqlite3.DatabaseError as e:
            return jsonify({
                "metrics": [],
                "hosts": [],
                "metrics_with_counts": [],
                "hosts_with_counts": [],
                "error": f"db error: {e}",
            }), 500

        return jsonify({
            "metrics": metrics,
            "hosts": hosts,
            "metrics_with_counts": metrics_with_counts,
            "hosts_with_counts": hosts_with_counts,
        })

    # Approvals (v0.4.2) — list pending repair proposals, approve, reject.
    @app.route("/api/approvals", methods=["GET"])
    @require_auth
    def api_approvals_list():
        """List all repair proposals awaiting operator decision."""
        from ipracticom_sweeper.repair.pending import list_pending

        pending = list_pending()
        return jsonify({
            "count": len(pending),
            "pending": [p.to_dict() for p in pending],
        })

    @app.route("/api/approvals/<pid>/approve", methods=["POST"])
    @require_auth
    def api_approvals_approve(pid):
        """Approve a pending proposal: execute the repair, archive as approved."""
        from ipracticom_sweeper.repair import pending as pending_mod
        from ipracticom_sweeper.repair import actions as actions_mod

        proposal = pending_mod.get_proposal(pid)
        if proposal is None or proposal.status != "pending":
            # We refuse to re-execute a proposal that's already been decided.
            # Check existence so we can return 404 vs 409 cleanly.
            if proposal is None:
                return jsonify({"error": "not_found"}), 404
            return jsonify({
                "error": "already_decided",
                "status": proposal.status,
            }), 409

        # Execute the repair. execute_repair returns RepairResult; we
        # log + archive regardless of success/failure so the operator
        # has an audit trail.
        try:
            result = actions_mod.execute_repair(
                proposal.action, **proposal.kwargs
            )
            result_dict = {
                "action": result.action,
                "target": result.target,
                "success": result.success,
                "message": result.message,
                "error": result.error,
                "rollback_available": result.rollback_available,
            }
            new_status = "executed" if result.success else "failed"
        except Exception as e:
            result_dict = {"action": proposal.action, "success": False, "error": str(e)}
            new_status = "failed"

        pending_mod.set_status(pid, new_status)
        pending_mod.archive(pid, "approved")
        pending_mod.log_audit({
            "kind": "repair_executed",
            "proposal_id": pid,
            "action": proposal.action,
            "kwargs": proposal.kwargs,
            "proposed_command": proposal.proposed_command,
            "status": new_status,
            "result": result_dict,
        })
        return jsonify({
            "ok": result_dict.get("success", False),
            "status": new_status,
            "result": result_dict,
        })

    @app.route("/api/approvals/<pid>/reject", methods=["POST"])
    @require_auth
    def api_approvals_reject(pid):
        """Reject a pending proposal: archive as rejected (no execution)."""
        from ipracticom_sweeper.repair import pending as pending_mod

        proposal = pending_mod.get_proposal(pid)
        if proposal is None:
            return jsonify({"error": "not_found"}), 404
        if proposal.status != "pending":
            return jsonify({
                "error": "already_decided",
                "status": proposal.status,
            }), 409

        pending_mod.set_status(pid, "rejected")
        pending_mod.archive(pid, "rejected")
        pending_mod.log_audit({
            "kind": "repair_rejected",
            "proposal_id": pid,
            "action": proposal.action,
            "kwargs": proposal.kwargs,
            "reason": proposal.reason,
        })
        return jsonify({"ok": True, "status": "rejected"})

    # Fleet (v0.4.2) — local host + every configured SSM connector.
    @app.route("/api/fleet", methods=["GET"])
    @require_auth
    def api_fleet_list():
        """Aggregate the local host + all enabled connectors into one view."""
        from ipracticom_sweeper.config import load_connectors
        from pathlib import Path

        state_dir = Path(os.environ.get(
            "IPRACTICOM_SWEEPER_STATE_DIR", "/var/lib/ipracticom-sweeper"
        ))
        local_heartbeat = _read_heartbeat(state_dir)

        hosts: list[dict[str, Any]] = []
        # The local host is always present.
        local_entry: dict[str, Any] = {
            "name": "local",
            "kind": "local",
            "status": _local_status(local_heartbeat),
        }
        if local_heartbeat:
            local_entry.update({
                "last_seen": local_heartbeat.get("ts_iso"),
                "defcon": local_heartbeat.get("defcon"),
                "problems_found": local_heartbeat.get("problems_found"),
            })
        hosts.append(local_entry)

        for c in load_connectors():
            last_err = c.last_error
            status = "error" if last_err else ("ok" if c.last_collected_at else "unknown")
            hosts.append({
                "name": c.name,
                "kind": "connector",
                "instance_id": c.instance_id,
                "region": c.region,
                "enabled": c.enabled,
                "tags": c.tags,
                "status": status,
                "last_collected_at": c.last_collected_at,
                "last_error": last_err,
            })

        return jsonify({
            "count": len(hosts),
            "hosts": hosts,
        })

    @app.route("/api/fleet/<host>", methods=["GET"])
    @require_auth
    def api_fleet_host(host):
        """Per-host details — local reads heartbeat; connectors read config + state."""
        from ipracticom_sweeper.config import get_connector, load_connectors
        from pathlib import Path

        state_dir = Path(os.environ.get(
            "IPRACTICOM_SWEEPER_STATE_DIR", "/var/lib/ipracticom-sweeper"
        ))

        if host == "local":
            hb = _read_heartbeat(state_dir)
            if hb is None:
                return jsonify({"error": "no heartbeat yet"}), 404
            return jsonify({
                "name": "local",
                "kind": "local",
                "status": _local_status(hb),
                "defcon": hb.get("defcon"),
                "problems_found": hb.get("problems_found"),
                "repairs_attempted": hb.get("repairs_attempted"),
                "last_seen": hb.get("ts_iso"),
                "last_seen_ts": hb.get("ts"),
                "extra": hb.get("extra") or {},
            })

        c = get_connector(host)
        if c is None:
            return jsonify({"error": "not_found"}), 404
        last_err = c.last_error
        status = "error" if last_err else ("ok" if c.last_collected_at else "unknown")
        return jsonify({
            "name": c.name,
            "kind": "connector",
            "instance_id": c.instance_id,
            "region": c.region,
            "enabled": c.enabled,
            "tags": c.tags,
            "status": status,
            "last_collected_at": c.last_collected_at,
            "last_error": last_err,
            "created_at": c.created_at,
        })

    # Predictions endpoint — read time-series, return threshold crossings
    @app.route("/api/predictions", methods=["GET"])
    @require_auth
    def api_predictions():
        """Return current predictions for all configured metrics."""
        from pathlib import Path
        from ipracticom_sweeper.predict.integration import collect_predictions
        from ipracticom_sweeper.config import load_rules

        state_dir = Path(os.environ.get(
            "IPRACTICOM_SWEEPER_STATE_DIR", "/var/lib/ipracticom-sweeper"
        ))
        db_path = state_dir / "metrics.db"
        if not db_path.exists():
            return jsonify({
                "predictions": [],
                "note": "no data yet (db file missing)",
            })

        host = os.environ.get("IPRACTICOM_SWEEPER_HOST_ID", "localhost")
        try:
            rules = load_rules()
        except Exception:
            rules = {}
        thresholds = rules.get("predict", {}).get("thresholds", None)
        preds = collect_predictions(db_path, host=host, thresholds=thresholds)
        return jsonify({
            "host": host,
            "count": len(preds),
            "predictions": [p.to_dict() for p in preds],
        })

    # Evidence export endpoint — build a signed bundle of audit + repairs
    @app.route("/api/evidence/export", methods=["GET"])
    @require_auth
    def api_evidence_export():
        """Build an evidence bundle (audit log + repairs + snapshot summary).

        Query params:
          hours: how far back to look (default 24)
          format: 'json' (default) or 'inline' (returns bundle inline)
        """
        from pathlib import Path
        from ipracticom_sweeper.evidence.bundle import (
            build_evidence_bundle, export_bundle_to_json, verify_bundle,
        )

        try:
            hours = min(int(request.args.get("hours", "24")), 720)
        except ValueError:
            hours = 24

        state_dir = Path(os.environ.get(
            "IPRACTICOM_SWEEPER_STATE_DIR", "/var/lib/ipracticom-sweeper"
        ))
        host = os.environ.get("IPRACTICOM_SWEEPER_HOST_ID", "localhost")
        audit_log = state_dir / "audit" / "repairs.jsonl"
        since_ts = time.time() - (hours * 3600)

        # Read audit log (best-effort)
        audit_entries: list = []
        if audit_log.exists():
            try:
                import json as _json
                cutoff = int(since_ts)
                with open(audit_log) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = _json.loads(line)
                            ts = entry.get("ts") or 0
                            if ts >= cutoff:
                                audit_entries.append(entry)
                        except _json.JSONDecodeError:
                            continue
            except (OSError, PermissionError):
                pass

        # Build bundle (repairs list will be inside audit_entries, filtered below)
        repair_entries = [e for e in audit_entries if e.get("kind") == "repair_executed"]

        bundle = build_evidence_bundle(
            host=host,
            agent_version="0.4.0",
            audit_entries=audit_entries,
            repair_entries=repair_entries,
            since_ts=since_ts,
            until_ts=time.time(),
        )

        # Optional: write to file and return path
        if request.args.get("format") == "file":
            out_path = state_dir / "evidence" / f"bundle-{int(time.time())}.json"
            export_bundle_to_json(bundle, out_path)
            return jsonify({
                "ok": True,
                "path": str(out_path),
                "verified": verify_bundle(bundle),
                "audit_entries": len(audit_entries),
                "repair_entries": len(repair_entries),
            })

        return jsonify(bundle.to_dict())

    return app


def main():
    parser = argparse.ArgumentParser(description="iPracticom Sweeper Agent API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()
    print(f"[agent_api] Starting on {args.host}:{args.port}")
    print(f"[agent_api] Auth: {'token' if os.environ.get('AGENT_API_TOKEN') else 'OPEN (localhost only)'}")

    # Start the fleet collector loop (no-op if there are no enabled connectors).
    # Imported lazily to keep cold-start fast for agents that don't use fleet mode.
    try:
        from ipracticom_sweeper.fleet import start_collector_loop
        start_collector_loop()
        print(f"[agent_api] Fleet collector loop started")
    except Exception as e:
        print(f"[agent_api] Fleet collector disabled: {e}")

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()