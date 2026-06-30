# Changelog — iPracticom AWS Linux Sweeper

All notable changes are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.5.0] — 2026-06-30 — FreeSWITCH coverage + Chat assistant

### Added
- **FreeSWITCH monitoring (FS-01..FS-25)** in `src/ipracticom_sweeper/monitor/freeswitch.py`. Four tiers, run via `monitor.checks.run_all({})`:
  - **Tier 1 (service health)** — FS-01..05: process running, systemd unit active, SIP/SIPS ports, fs_cli reachable.
  - **Tier 2 (network integrity)** — FS-06..09: SIP peers/registrations/gateway status, RTP port range 16384-32768.
  - **Tier 3 (operational + baseline drift)** — FS-10..15: fs_cli latency, active calls/channels, log disk %, config mtime drift, baseline calls/hour.
  - **Tier 4 (edge cases)** — FS-16..25: CDR backup freshness, recordings age, sofia packet loss/jitter, codec mismatch, process RSS/CPU, TCP retransmit %, fs_log error rate, fail2ban jail status.
- **Catalogue view** (`/catalogue`) — read-only inspection of every registered check module, exported from the catalogue registry into the dashboard.
- **Inspector view** (`/inspector/host/<name>`) — drill-down per host for the 15 base monitors.
- **Chat shell** (`/chat`, `/chat/sessions`, `/chat/ws`) — Flask Blueprint + flask-sock WebSocket. Hebrew UI, in-memory session store, demo seeding.
- **Hybrid retrieval** (`chat_rag.py`) — stdlib BM25Okapi + TF-IDF cosine with Hebrew-aware tokenization (NFKC + niqqud stripping). Lazy index over `docs/`.
- **LLM router** (`chat_llm.py`) — mock-by-default with regex-driven intents; switches to OpenAI or Anthropic when the matching `*_API_KEY` env var is present. Single-iteration tool-use loop in v0.5.
- **Tool surface** (`chat_tools.py`) — `list_fs_checks`, `get_fs_check`, `run_fs_tier(1..4)`, `run_full_pipeline` (gated by `ENABLE_HEAVY_TOOLS=1`). Hard wall-clock timeout (8s default) around every check.
- **RTL-aware chat CSS** — `text-align: start`, `border-inline-start`, mobile breakpoint at 768px. No LTR overrides inside the chat DOM.

### Changed
- `repair_policy.yaml`: unchanged from 0.4.7 (still default `needs_approval`).
- Dashboard nav: new `צ'אט` link next to `קטלוג` and `מפקח בדיקות`.

### Operator notes
- **Chat defaults to mock mode** — no user text leaves the box unless `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` is set. The mock replies surface the tool call the LLM *would* make, so the UI demonstrates the wiring without external calls.
- **`run_full_pipeline` is opt-in**: set `ENABLE_HEAVY_TOOLS=1` before invoking. The full pipeline still takes 30-60s on a real FS host.
- **RAG corpus**: defaults to `docs/` at the repo root. Missing directory = 0 docs, chat UI still boots cleanly with no RAG context until populated.

### Tests
- **996/996 passing** (+262 from v0.4.7):
  - `tests/test_monitor_freeswitch_tier1.py` — 18 (FS-01..05)
  - `tests/test_monitor_freeswitch_tier2.py` — 28 (FS-06..09)
  - `tests/test_monitor_freeswitch_tier3.py` — 32 (FS-10..15)
  - `tests/test_monitor_freeswitch_tier4.py` — 48 (FS-16..25)
  - `tests/test_monitor_freeswitch_integration.py` — 7 (smoke)
  - `tests/test_inspector.py` — 9
  - `tests/test_catalogue.py` — 14
  - `tests/test_chat.py` — 19 (slice 3.1)
  - `tests/test_chat_rag.py` — 40 (slice 3.2)
  - `tests/test_chat_llm.py` — 32 (slice 3.3)
  - `tests/test_rtl.py` — 8 (slice 4.1)

### Migration
- Pull the new tag, run `pip install -e .` again to pick up `flask-sock` (only runtime dep change in this release). All existing monitors and the repair pipeline continue to behave as in 0.4.7.

## [0.4.7] — 2026-06-30 — Fix: bot run_now times out on long sweeps

### Fixed
- **`run_now` button failed with "agent_api request failed"** even though `/api/run` returned 200. Root cause: the bot's httpx client had a 10s default timeout, but the actual pipeline sweep takes 30-45 seconds (it runs 15 monitors: cpu, memory, disk, services, security, network, logs, processes, aws, kernel, process_tracker, fd_check, security_baseline, uptime, health, plus diagnose + adapt phases). On slow hosts the 10s timeout fired before the pipeline returned, surfacing as the misleading "agent_api request failed" error to the operator.
- **`trigger_run()` now passes `timeout=120.0`** to `_post()` — overrides the client default just for the sweep endpoint.
- **`_post()` now accepts an optional `timeout` kwarg** — passes it through to httpx. Default is `None` (httpx uses the client's 10s default).

### Verified end-to-end
- Restarted bot, ran `trigger_run()` via direct httpx call with 120s timeout — got back `defcon=4` + full diagnosis (15 modules, 2 needing human: disk warn + logs warn).
- Verified the failure mode by checking the agent_api log: `POST /api/run HTTP/1.1 200` actually succeeded at the server side; the bot's client just gave up before getting the response.

### Tests
- **734/734 passing** (+3 new):
  - `test_trigger_run_passes_long_timeout` — verifies timeout=120 is forwarded.
  - `test_post_helper_accepts_timeout_override` — verifies the kwarg plumbing.
  - `test_post_helper_default_timeout_is_none` — verifies default behavior unchanged for other endpoints.

## [0.4.6] — 2026-06-30 — Approval gate is the new default + rich alerts

### Changed (per Daniel 2026-06-30)
- **`repair_policy.yaml`: default flipped from `auto` → `needs_approval`**. Daniel: "בשלב זה צריך רק להתריע ולבקש אישור לפני התיקון". All 5 registered repairs (drop_caches, log_truncate_journald, service_restart, top_processes_snapshot, notify_human) now require explicit operator approval via the ✅ Approvals menu before execution. To whitelist a specific repair as auto, uncomment its line in `/etc/ipracticom-sweeper/repair_policy.yaml`.
- **The 21 monitors under `monitor/` continue to run** (cpu, memory, disk, network, services, ssl, http, kernel_errors, security_baseline, smart, processes, fd, aws, uptime, fd_check, aide_check, iostat, ...). They are unchanged — only the action policy on the 5 repairs changed.

### Added
- **`format_approvals_list` surfaces the full problem context** (Daniel #5): each pending repair now shows severity emoji (🚨/⚠️/ℹ️), what was detected (`problem.detail`), the metrics that drove the decision (`problem.metrics`), and the exact command to be executed (`proposed_command`). Operator can decide approve/reject without drilling into a separate view.

### Fixed
- **Pipeline tests updated to reflect the new policy**: drop_caches no longer auto-executes — it creates a pending proposal with the full problem context. `auto_repair=True` still applies, but only to repairs not gated by `needs_approval`.

### Tests
- **731/731 passing** (+7 new from v0.4.5):
  - `tests/test_approvals_render.py` — verifies severity emoji, problem.detail, proposed_command, metrics, overflow indicator.
  - 3 pipeline tests rewritten to assert proposal creation instead of auto-execution.

### Operator workflow (after this change)
1. Sweeper runs every 5 minutes, scans all 21 monitors.
2. When a monitor detects an issue, the pipeline calls `notify_human` (which is now itself gated — it sends the alert via the Telegram bot and writes the proposal to disk).
3. Operator receives a Telegram alert in the ✅ Approvals menu: "🚨 service_restart — זוהה: HTTP probe...503 — תיקון מוצע: systemctl restart nginx".
4. Operator clicks ✅ Approve or ❌ Reject.
5. Only after approval does `execute_repair` actually run.

## [0.4.5] — 2026-06-30 — Bot: render real metrics + English connector prompts

### Fixed
- **`format_fleet_host` ignored the `extra` block** — the v0.4.4 endpoint was returning the psutil snapshot, but the formatter only printed defcon/problems/last_seen. Operators saw `🖥️ CPU: ❌ (אין נתונים)` on local hosts. v0.4.5 surfaces CPU% (with core count), memory (used/total MB + %), disk (used/total GB + %), network (MB sent/recv), uptime (Xd Yh Zm + booted_at) inline.
- **`fleet_host` handler was making a redundant `/api/snapshot` call** to fill in the same data `extra` already had. Removed the extra HTTP roundtrip — the host dict from `/api/fleet/local` is now sufficient.
- **`_format_local_metrics` now understands the v0.4.4 `extra` block** (cpu.percent / memory.percent / disk.percent / network.*) in addition to the legacy `modules.*.details.percent` shape from `/api/snapshot`. Backward-compatible.

### Changed
- **Connector form prompts are now in English** (operator requested English). The 4 steps (name, instance_id, region, tags) and all validation error messages now say exactly which value format is expected (`i-` prefix, AWS region examples, `key=value,key=value` for tags, etc.). The "❌ Cancel" button is also English.
- **`pyproject.toml`** → 0.4.5

### Tests
- **724/724 passing** (+10 from v0.4.4: `tests/test_fleet_metrics_render.py` covers the new formatter behaviour and the English prompt contract).
- Updated `tests/test_telegram_handlers_fleet.py::test_fleet_host_local_shows_live_metrics` to feed the `extra` block instead of the legacy `modules` shape.

## [0.4.4] — 2026-06-30 — Real local metrics (psutil) + seed connector cleanup

### Added
- **`collect_local_metrics()` in `monitor/health.py`** — uses `psutil` to snapshot CPU%, cores, memory (percent + used_mb + total_mb), disk (percent + used_gb + total_gb), network (bytes_sent + bytes_recv), uptime_seconds, and booted_at. Returns a graceful error dict if psutil fails (sandbox / permission issues) instead of crashing the pipeline.
- **`record_run()` now auto-attaches the local metrics snapshot to `heartbeat.extra`** when no `extra` is passed in. The next pipeline run will populate the field without any caller change.
- **`psutil>=5.9.0`** added to `pyproject.toml` runtime dependencies.
- **`tests/test_local_metrics.py`** — 9 new tests covering collector shape, graceful failure, `record_run` integration, and `/api/fleet/local` exposure of the metrics block.

### Fixed
- **`/api/fleet/local` was returning `extra: {}`**: the v0.4.3 endpoint already forwarded `extra` from the heartbeat, but the heartbeat itself never contained the snapshot. With v0.4.4, every pipeline run writes the psutil snapshot into `extra`, so the endpoint surfaces real CPU/memory/disk/network/uptime numbers.
- **v0.4.3 CHANGELOG claimed "Fleet host detail now shows live CPU/..."** — that promise was only partially wired (the forwarding existed, the data didn't). v0.4.4 closes the gap.

### Changed
- **`/var/lib/ipracticom-sweeper/connectors.yaml`** — seed connectors (`prod-web-1`, `prod-db-1`, `staging-web-1`) replaced with `connectors: []`. They were placeholder data with `Unable to locate credentials` errors that confused operators on first launch. Add real SSM connectors via the 🔌 Connectors menu in the bot.
- **`pyproject.toml`** → 0.4.4

### Tests
- **714/714 passing** (+9 from v0.4.3).

## [0.4.3] — 2026-06-30 — Bot Polish + Logs

### Changed (per user feedback 2026-06-29)
- **Settings**: only the Telegram connectivity test remains. Removed Slack/API/identity buttons — they were either operator-level concerns or duplicate info.
- **Connectors**: header now explains what a connector is + flags seed data explicitly. Operators no longer see "3 connectors" and wonder if they accidentally added servers.
- **Connector delete**: properly checks `resp.status_code` and surfaces 404/500/connection errors instead of silently "refreshing" the list.
- **pyproject.toml** → 0.4.3

### Added
- **2 new agent_api endpoints**:
  - `GET /api/logs` — list every available audit log with its tail (repairs/monitor/heartbeat/last_result)
  - `GET /api/logs/download?name=...` — download a single log (or all) as a text file with truncation cap
- **2 new agent_client methods**: `get_logs(tail=50)`, `get_logs_download_url(name="all")`
- **Fleet host detail** now shows live CPU/זיכרון/דיסק/רשת from the latest snapshot (local host only)
- **2 new buttons per host**: "📜 הצג לוגים" (inline tail) + "⬇️ הורד לוג כקובץ" (Telegram document)
- **Fleet download** handler fetches the log from agent_api and sends it as a `reply_document` to the calling user
- **`_send_result(None)`** — dispatcher now supports handlers that already sent a reply (e.g. document upload) and want the dispatcher to stay silent

### Tests
- **705/705 passing** (was 669 in v0.4.2, +36 new)
- `test_agent_api_logs.py` — 12 tests (catalog, download, truncation, auth, 404)
- `test_telegram_handlers_fleet.py` — 9 tests (host view, live metrics, log tail, format helper)
- `test_telegram_handlers_settings.py` — 3 tests (menu, test_tg, error path)
- `test_telegram_handlers_connectors.py` — 5 tests (seed detection, delete 200/404/500/network)
- `test_telegram_agent_client.py` — 5 new tests for the 2 new methods (tail param, URL with/without token)

## [0.4.2] — 2026-06-29 — Telegram Bot Dashboard Parity

### Added
- **6-section main menu** (`full_menu()`): Dashboard, History, Approvals, Connectors, Fleet, Settings
- **3 new agent_api endpoints**:
  - `GET /api/history` — catalog (distinct metrics + hosts + per-metric counts via SQL)
  - `GET /api/approvals` — list pending repair proposals
  - `POST /api/approvals/<id>/approve` — execute the repair now + archive as approved
  - `POST /api/approvals/<id>/reject` — archive as rejected
  - `GET /api/fleet` — local host + every configured SSM connector
  - `GET /api/fleet/<host>` — per-host details (local reads heartbeat; connectors read config)
- **6 handler modules** (`src/.../telegram_bot/handlers/`): dashboard, history, approvals, connectors, fleet, settings
- **Pager utility** (`services/pager.py`) — pagination for inline keyboards (8 rows/page, 64-byte callback limit, oversized callback truncation)
- **Conversation state** (`states.py`) — `ConnectorFormState` dataclass for the multi-step connector CRUD flow
- **5 new agent_client methods**: `get_history_catalog`, `approve_repair`, `reject_repair`, `list_approvals`, `list_fleet`, `get_fleet_host`, `trigger_run`
- **7 new keyboard builders**: `full_menu`, `dashboard_menu`, `history_overview_menu`, `history_metric_menu`, `approvals_menu`, `approval_action_kb`, `connectors_menu`, `connector_actions_kb`, `fleet_menu`, `settings_menu`, `confirm_kb`
- **5 new formatters**: `format_dashboard`, `format_history_catalog`, `format_approvals_list`, `format_approval_result`, `format_connectors_list`, `format_connector_detail`, `format_fleet_list`, `format_fleet_host`
- **Free-text message handler** for the connector form flow (4 steps: name → instance_id → region → tags)
- **Approve = immediate execute** (per user request — not just mark approved)

### Changed
- `bot.py` rewired end-to-end — 30+ callback patterns, all gated by `authorized_only`
- `keyboards.py` extended (backwards-compat: `main_menu()` still returns 4-button v0.4.1 menu)
- `formatter.py` extended (all v0.4.1 functions unchanged)
- `pyproject.toml` → 0.4.2

### Tests
- **669/669 passing** (was 595 in v0.4.1, +74 new)
- `test_telegram_pager.py` — 17 tests
- `test_telegram_states.py` — 7 tests
- `test_telegram_agent_client.py` — 15 tests
- `test_telegram_formatter.py` — 23 tests
- `test_telegram_keyboards.py` — 17 tests
- `test_agent_api_endpoints.py` — 13 tests (covers all 3 new endpoints + auth + 404/409 paths)
- `test_handlers.py` (rewritten) — 7 tests for the v0.4.2 dashboard + history flow

## [0.4.1] — 2026-06-29 — Hebrew Dashboard as Telegram Bot

### Added — 8 New Collectors (Slices 1.1–1.8)
- **HTTP healthcheck** (`monitor/http_check.py`) — endpoint probing, status/time/error, supports per-target thresholds
- **SSL cert expiry** (`monitor/ssl_check.py`) — cert parsing, days-to-expiry, self-signed detection, diagnose hook
- **SMART disk health** (`monitor/smart_check.py`) — ReallocatedSectors/PendingSectors/CriticalWarning, wraps `smartctl -A -H`, falls back to `smartctl -a`
- **Kernel Oops/MCE/segfault** (`monitor/kernel_errors.py`) — dmesg + journalctl scanning with 1h + 24h windows
- **iostat I/O latency** (`monitor/iostat.py`) — per-device `r_await`/`w_await`/`util` via sysstat
- **Process tracker** (`monitor/process_tracker.py`) — top-N by RSS, service restart counter from journalctl
- **File descriptor monitor** (`monitor/fd_check.py`) — system-wide FD usage, per-process top-N, `/proc/sys/fs/file-nr`
- **AIDE file integrity** (`monitor/aide_check.py`) — runs `aide --check`, parses summary + reports added/changed/removed

### Added — Storage & Integration (Slices 2.0–5.0)
- **SQLite TimeSeriesDB** (`storage/timeseries.py`) — 30-day retention, per-mount disk prefix queries, atomic batch writes
- **Time-series pipeline integration** — every pipeline run writes defcon + system metrics to DB
- **`/api/history/<metric>` endpoint** — query historical data for any metric, returns `[{ts, value}]`
- **Predict wire** (`predict/integration.py`) — bridges TimeSeriesDB to predict layer, adds `predictions[]` to snapshot
- **`/api/predictions` endpoint** — run predictions on demand, returns per-metric forecasts
- **Notify deduplicator** (`notify/pipeline.py`) — fingerprint-based dedup with kind+message+host, critical bypasses dedup
- **Evidence bundle** (`evidence/bundle.py`) — JSON snapshot + SHA-256 signature, no AWS dep, local-only
- **`/api/evidence/export` endpoint** — on-demand bundle export, returns signed JSON

### Added — Security & Docs (Slices 6.0–7.0)
- **Security baseline** (`monitor/security_baseline.py`) — sshd_config drift detection, SUID binary scanner, listening ports baseline
- **`/api/security` endpoint** — SSH/SUID/ports summary
- **`MONITORING_COVERAGE.md`** — authoritative list of all 20 modules, gaps, extension guide, thresholds cheat sheet
- **`repair_policy.yaml`** — defaults: auto for `drop_caches`/`log_truncate_journald`/`top_processes_snapshot`/`notify_human`, needs_approval for `service_restart`

### Added — Production Hardening (Slice 8.0)
- **bootstrap.sh** — added system deps: `smartmontools`, `sysstat`, `aide`, `python3-venv`, `python3-pip`
- **pyproject.toml** — bumped to v0.4.0, added `[test]` extras (`pytest`, `freezegun`, `pytest-asyncio`)
- **Editable install with extras** — `pip install -e ".[test]"` for test deps

### Added — Telegram Dashboard (v0.4.1)
- **Telegram bot** (`telegram_bot/`) — full Hebrew dashboard as a Telegram bot, no dashboard/domain needed
  - `config.py` — env-based `BotConfig` with `ALLOWED_CHAT_IDS` whitelist (fail-fast on missing)
  - `auth.py` — `@authorized_only` decorator; silent rejection on unauthorized
  - `services/agent_client.py` — async httpx wrapper for `/api/snapshot`, `/api/history/<m>`, `/api/predictions`, `/api/evidence/export`
  - `keyboards.py` — inline keyboards (main/status/history) with Hebrew labels + 🔙 back button
  - `formatter.py` — HTML formatting with DEFCON emoji, smart truncation, Hebrew error messages
  - `handlers.py` — `start`/`status`/`problems`/`history`/`security` returning `{"text", "reply_markup"}` dicts
  - `bot.py` — `python-telegram-bot` Application wiring + 8 handlers + global error handler
- **`scripts/install_telegram_bot.sh`** — creates `/etc/ipracticom-sweeper/telegram-bot.env` + systemd unit, with `--uninstall` flag
- **`bootstrap.sh`** — calls telegram bot installer (set `SKIP_TELEGRAM_BOT=1` to opt out)
- **Tests: 580** (531 → 580, +49 new, 0 failing)

### Tests
- **469 → 531** (+62 new tests, 0 failing)
- All new modules: 100% TDD (RED → GREEN → wire → commit)
- 3 new endpoint test suites (history/predictions/evidence)
- Sandbox-validated: clean clone → venv → `pip install -e ".[test]"` → 531 passed

### Changed
- Pipeline now writes to TimeSeriesDB on every run (auto-prune at 30 days)
- Snapshot payload includes `predictions[]` and `evidence_bundle` (optional)
- All 8 new collectors auto-invoke if their config is present
- pyproject.toml `version` 0.3.0 → 0.4.0

## [0.3.0] — 2026-06-28 — Week 3 complete

### Added
- **Dashboard (Flask)** — server-rendered UI with classical typography (Cormorant Garamond + Inter + JetBrains Mono), forest-green accent, DEFCON-aware banner, modules grid, problems list, repairs list, rules sidebar
- **Agent HTTP API** (`agent_api.py`) — standalone REST API exposing snapshot/run/notify operations, with bearer-token auth (`AGENT_API_TOKEN`)
- **Agent client** (`agent_client.py`) — typed HTTP client for remote dashboard mode, wraps httpx with explicit error handling
- **Remote dashboard mode** — `SWEEPER_REMOTE_URL` env var switches the dashboard to proxy through an agent; UI shows "REMOTE MODE" badge and remote banner
- **systemd service + timer** — `systemd/ipracticom-sweeper.{service,timer}`, runs every 5 minutes
- **`install-systemd.sh`** — one-shot installer with `--uninstall` flag
- **Modules dictionary in pipeline result** — dashboard can show all 9 module statuses, not just diagnose output
- **Tests: 162 total** — 19 dashboard tests, 20 agent API+client tests, 21 systemd tests, 12 notify-pipeline tests, 90 baseline (monitor/diagnose/repair/adapter/pipeline)

### Changed
- `notify.format_*` now accepts BOTH legacy snapshot shape AND new `PipelineResult` shape (auto-detect by `defcon` key)
- `pipeline.run_pipeline` now invokes `notify_pipeline_result` automatically when DEFCON < 5 (green runs are silent)
- `dashboard._fetch_snapshot/_identity/_rules_summary` — new helpers that route to remote or local based on env var
- Local imports in pipeline/dashboard moved to module-level for testability

### Fixed
- `m.get("options")` AttributeError on malformed disk mounts — guarded with `isinstance(m, dict)`
- structlog `level=N` keyword clash with built-in — renamed to `level_value`
- structlog writing to stdout polluted JSON output — configured stderr at import time in `__init__.py`
- systemd service marked warn/crit as "failed" — added `SuccessExitStatus=1 2 3`
- Flask template crashed on remote mode (rules_summary contained `_remote=True` sentinel) — template now branches with `{% if rules_summary.get('_remote') %}`

## [0.2.0] — 2026-06-28 — Diagnose + Repair

### Added
- **Diagnose engine** (`diagnose/engine.py`) — 5 diagnosers (cpu/memory/disk/services/security) → DEFCON + safe_repairs + needs_human
- **Adapter** (`diagnose/adapter.py`) — normalizes monitor field names for diagnose consumption
- **Repair actions** (`repair/actions.py`) — 5 actions with safety classification (SAFE/GUARDED/DANGEROUS/NEVER), snapshot system, registry pattern
- **Pipeline** (`pipeline.py`) — full 5-step orchestrator: monitor → adapt → diagnose → repair → notify
- **Tests: 77 total** — 26 diagnose, 11 adapter, 14 repair, 13 pipeline, 13 monitor (existing)

## [0.1.0] — 2026-06-28 — Initial Monitor

### Added
- **Monitor layer** — 9 collector modules: cpu, memory, disk, network, services, logs, processes, security, aws
- **Audit logger** (`audit/logger.py`) — JSONL event emitter, structlog-based
- **Config loader** (`config.py`) — YAML rules with deep-merge defaults, IMDSv2 server-id detection
- **Notifier** (`notify.py`) — Slack Block Kit + Telegram Markdown formatters, async httpx sender
- **CLI** (`sweeper.py`) — argparse, `--json`/`--quiet`/`--rules`, exit codes map to overall_status
- **Tests: 26** for monitor (cpu/disk/memory)

## [Unreleased]

### Planned
- Fleet dashboard view (multiple agents side-by-side)
- Prometheus /metrics endpoint
- Repair rollback CLI tool (`sweeper rollback <snapshot_id>`)
- AWS-specific modules (RDS connection check, ECS task health)