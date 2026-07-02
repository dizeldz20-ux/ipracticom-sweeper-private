# Changelog — iPracticom AWS Linux Sweeper

All notable changes are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [1.4.0] — 2026-07-02 — Suppression Engine & Dashboard API

### Added
- **Suppression engine** (Slice 3) — public CRUD on top of per-host YAML
  - `add_suppression(name, rule, *, until=None, reason="")`
    auto-creates the host; re-adding the same (host, rule) replaces
    the existing entry (no duplicate stacking)
  - `remove_suppression(name, rule) -> bool` (idempotent)
  - `list_active_suppressions(name)` — lazy filter, expired are hidden
  - `cleanup_expired_suppressions() -> int` — bulk, mtime-preserving
  - 13 new tests in `test_host_config.py`
- **Dashboard routes** (Slice 4) — REST surface for the slice 1+2+3
  work, auth + rate-limit gated like the rest of the agent API
  - `GET    /api/hosts`
  - `GET    /api/hosts/<name>`
  - `POST   /api/hosts/<name>/suppressions`   (201)
  - `GET    /api/hosts/<name>/suppressions`   (filters expired)
  - `DELETE /api/hosts/<name>/suppressions/<rule>`  (204 / 404)
  - `POST   /api/hosts/_cleanup-suppressions` (returns count removed)
  - `GET    /api/modules`  with `?kind=&tag=&risk=&available_only=`
  - `GET    /api/modules/<kind>/<name>`
  - 18 new tests in `test_dashboard_v14_routes.py`
- **Audit events** — `suppression.add` and `suppression.remove` are
  emitted via `audit.logger.emit`; `cleanup_expired_suppressions` is
  deliberately silent (housekeeping, not an operator decision)

### Changed
- `__init__.py` + `pyproject.toml` bumped from 1.3.0 to 1.4.0
- `Suppression` and `HostConfig.is_suppressed()` were already
  present in v1.3.0 (data shape); the runtime API and persistence
  behaviour is what this version adds

### Hardening
- Path-traversal and whitespace host names return 400 on every
  per-host route, mirroring the existing `_host_yaml_path` sanitizer
- The detail route distinguishes "unknown host" (404) from
  "default config" (which `load_host` returns) by checking
  `_host_yaml_path(name).exists()` before serializing

### Deferred (to v1.5.0)
- **Dashboard refactor** (1945 lines → split by route group)
- **Remaining 44 silent except blocks** (audit/rotation.py, otel.py, formatter.py)
- **Prediction class merge** (2 duplicates in `predict/`)
- **Logging unification** (stdlib → structlog)
- **Frontend SPA** — the new REST routes are JSON-only; the HTML
  dashboard / SPA still needs to be wired to consume them

## [1.3.0] — 2026-07-02 — Per-Host Configuration & Module Registry

### Added
- **`config/host_config.py`** — per-host config (Slice 1)
  - `HostConfig` dataclass: monitors / repairs / runbooks / suppressions / enabled / description
  - YAML at `$STATE_DIR/hosts/<name>.yaml` — git-friendly source of truth
  - SQLite cache at `$STATE_DIR/hosts.db` — read-cache for the dashboard
  - Atomic YAML write (tmp + rename); invalidate-then-populate cache
  - Host name sanitization `[a-zA-Z0-9_.-]`; path-traversal rejected
  - `Suppression` dataclass (reason, until); permanent when `until=None`
  - 16 tests in `test_host_config.py`
- **`config/module_catalog.yaml`** — bilingual, version-controlled catalog (Slice 2)
  - 37 monitors, 15 repairs, 5 runbooks
  - Each entry: `title_en` / `title_he`, description, params, tags, risk
  - Catalog is metadata source of truth; code is runtime source
- **`config/module_registry.py`** — discover + filter + default-config (Slice 2)
  - `discover_modules()` cross-checks catalog ↔ code (strict mode raises on drift)
  - `filter_modules(kind=, tag=, risk=, available_only=)` for the dashboard
  - `get_module(name, kind=)` lookup helper
  - `default_host_config(name)` builds a safe-by-default `HostConfig`
    (high-risk monitors disabled, medium/high repairs require approval)
  - `_MONITOR_ALIASES` lets catalog names diverge from file stems
    (`fs_inode_check`, `freeswitch_health` → `monitor/freeswitch.py`)
  - Suffix conventions: `name_check` ↔ `name.py`, `name_runbook` /
    `name_recovery_runbook`
  - 17 tests in `test_module_registry.py`

### Changed
- Three previously orphaned monitors (`health`, `healthz_probe`, `processes`)
  promoted into the catalog with bilingual entries — they were already shipped
  in code but not visible to the dashboard
- `monitor:checks` (the orchestrator, not a leaf monitor) removed from catalog
- Two catalog entries (`fs_inode_check`, `freeswitch_health`) now resolve
  to the consolidated `monitor/freeswitch.py` via `_MONITOR_ALIASES`
- Reverse-drift detector recognises `name_check` / `name_health` suffix
  conventions so catalog↔code cross-check is correct

### Hardening
- `test_30_2_no_catalog_only_entries_except_ignored` and
  `test_30_2_strict_mode_raises_on_any_drift` introduced as gate tests so
  future catalog drift fails CI rather than silently degrading the dashboard

### Deferred (to v1.4.0)
- **Suppression engine** — runtime evaluation of `Suppression` entries
  (UI controls, time-based cleanup, audit trail)
- **Dashboard routes** — web UI bindings for `host_config` + `module_registry`
- **Dashboard refactor** (1945 lines → split by route group)
- **Remaining 44 silent except blocks** (audit/rotation.py, otel.py, formatter.py)
- **Prediction class merge** (2 duplicates in `predict/`)
- **Logging unification** (stdlib → structlog)

## [1.2.0] — 2026-07-01 — QA Foundation: paths + log + API hardening

### Added
- **`config/paths` module** — single source of truth for `$IPRACTICOM_SWEEPER_STATE_DIR`
  - `ROOT()`, `maintenance_dir()`, `fleet_snapshots()`, `connectors_file()`,
    `pending_repairs()`, `approved_repairs()`, `rejected_repairs()`, `audit_log()`,
    `ntp_history()`, `token_health()` — all cached, all env-overridable
  - 12 new tests in `test_paths_centralization.py`
- **`_log.log_suppressed()` helper** — replaces 5 silent `except: pass` blocks
  in `fleet/aws_connector.py` with structured WARNING lines + DEBUG traceback
  - 6 new tests in `test_log_suppressed.py`
- **Built-in rate limiting** (no `flask-limiter` dependency)
  - Per-IP sliding window: 100/min default for `/api/*`, 600/min for `/healthz`
  - Returns 429 + `Retry-After: 60` on overage, `X-RateLimit-Remaining` on success
  - Per-IP buckets respect `X-Forwarded-For` (first hop)
  - Disable with `AGENT_API_RATELIMIT=0`
  - 10 new tests in `test_rate_limit_cors.py`
- **Localhost-only CORS** (no `flask-cors` dependency)
  - Default allowlist: `http://localhost`, `http://localhost:5000`, `http://127.0.0.1`, `http://127.0.0.1:5000`
  - Extend via `AGENT_API_CORS_ORIGINS=csv`
  - No wildcard ever set; external origins return no `ACAO` header
  - `after_request` hook attaches `Vary: Origin`, `ACAM`, `ACAH`, `ACMA`

### Changed
- **Version bump**: `pyproject.toml` and `__init__.py` updated to 1.2.0
- **Test fixtures updated** for v1.2.0 (version assertions, vault session glob)

### Deferred (to v1.3.0)
- **Dashboard refactor** (1945 lines → split by route group)
- **Per-host module selection UI** (QA Dashboard)
- **Suppression / silencing** per host + per module
- **Remaining 44 silent except blocks** (audit/rotation.py, otel.py, formatter.py)
- **Prediction class merge** (2 duplicates in `predict/`)
- **Logging unification** (stdlib → structlog)

## [1.1.1] — 2026-07-01 — Sprint 15 repairs + install hardening

### Added
- **Sprint 15 repair coverage**: 5 new repair actions registered in `actions_extra.py`
  - `repair_rotate_nginx_logs`: rotate nginx access/error logs and reload
  - `repair_drop_freeswitch_cache`: drop FreeSWITCH mod_sofia/db caches
  - `repair_reload_freeswitch_config`: reload FreeSWITCH XML config (`fs_cli reloadxml`)
  - `repair_vm_lock_clear`: clear stale VM heartbeat locks
  - `repair_pg_vacuum`: per-table VACUUM with explicit table-name validation
- **Install hardening for installing agents**:
  - `pyproject.toml` now declares `[project.scripts]`: `ipracticom-sweeper`, `ipracticom-dashboard`, `ipracticom-agent-api`
  - `make verify` / `make doctor` runs `scripts/verify_install.py` (Python + pip + deps + entry points + tests)
  - `make install-all` adds `[telegram]` + `[test]` extras in one shot
  - `scripts/verify_install.py`: 6-check pre-flight, exit 0 only if all required pass

### Changed
- **Naming consistency**: `actions_extra.py` repairs now register without `repair_` prefix to match `actions.py`
- **`HIGH_RISK_ACTIONS` in `approvals_v2.py`**: aligned to real registry names (was dead code)
- **Auth fail-closed**: `agent_api.py` now exits 1 if `AGENT_API_TOKEN` is missing AND bind host is public (0.0.0.0/::)
- **Secret redaction in audit log**: `_redact_secrets()` helper scrubs `password`, `token`, `api_key`, `secret` from kwargs before logging
- **Reject reason required**: `POST /api/approvals/<id>/reject` returns 400 if `reason` is empty
- **Version bump**: `pyproject.toml` and `__init__.py` updated to 1.1.1

### Fixed
- **Command injection guard**: `service_restart` validates `unit` against `^[a-zA-Z0-9_.@-]+$`; `pg_vacuum` validates `table` against `^[a-zA-Z0-9_.]+$`
- **404 wins over 400** in reject route (unknown-id probes don't leak "reason required")

## [1.1.0] — 2026-07-01 — Deep Checks v2 + Approval Workflow v2

### Added
- **Sprint 12 (Network + Service Probes)**: 3 monitors, 31 tests
  - `healthz_probe`: HTTP healthz endpoint probe with timeout/SSL controls
  - `systemd_state`: masked/disabled/failed unit detector
  - `ntp_check`: chronyc/ntpq clock-skew with unit normalization (sec/ms/us)
- **Sprint 14 (PostgreSQL Deep)**: 5 monitors, 35 tests
  - `pg_long_query`: queries running >5min by default, classifies by count
  - `pg_replication_lag`: max replay_lag across replicas, disabled if stand-alone
  - `pg_locks`: blocked queries via `pg_blocking_pids()`, Lock wait_event
  - `pg_bloat`: dead-tuple ratio per table, reports top-N bloated
  - `pg_autovacuum`: lag since last_autovacuum, never-vacuumed → crit
- **Sprint 16 (Backups + Recovery)**: 3 monitors, 25 tests
  - `backup_fresh`: snapshot age vs configurable RPO
  - `backup_size`: size sanity check (delta vs prior)
  - `restore_test`: parse recent restore-test output for status
- **Sprint 18 (Approval Workflow v2)**: 5 capabilities, 25 tests
  - Expiry window — proposals expire after 24h default, background reaper
  - Two-operator quorum — high-risk actions need 2 distinct user_ids
  - Comment thread — operators can add comments, surfaced in Telegram + dashboard
  - Required rejection reason — POST /reject must include reason; optional `dry_run`
  - CSV export — `GET /api/approvals/export.csv` with UTF-8 BOM + date filter
- **Test gap closure (Level 1)**: 91 tests across audit_logger, self_disk,
  telegram_health, runbooks_engine — covers ENV-vars-at-import-time pitfalls
  and the actual dataclass field names that earlier tests got wrong
- **Sprint 15 (Additional Repairs)**: 5 actions, 25 tests
  - `repair_rotate_nginx_logs`: graceful nginx log rotation via SIGUSR1,
    keeps N rotations (configurable), reports `bytes_freed`
  - `repair_drop_freeswitch_cache`: `fs_cli cache flush`, pre-checks FS status
  - `repair_reload_freeswitch_config`: `fs_cli reloadxml`, captures syntax
    errors from stderr
  - `repair_clear_freeswitch_voicemail_locks`: removes stale `.lock` files
    older than `max_age_seconds`, preserves recent ones
  - `repair_pg_vacuum`: `VACUUM [ANALYZE]` via psql, `dry_run` mode,
    timeout, reports table names + duration

### Fixed
- `ntp_check.py` — ntpq parser now handles `*`/`+`/`#`/`o`/`-` tally codes via
  split-based parsing; regex previously skipped the selected peer
- `ntp_check.py` — `_parse_offset_seconds("microseconds")` now correctly
  recognizes the `microsec` prefix (was only matching `usec`)
- `pyproject.toml` — pinned `flask-sock>=0.7.0` dependency. Was previously
  silently failing at chat-blueprint import time, breaking 50+ dashboard
  tests (template `url_for('chat.chat_index')` raised BuildError).

### Tests
- **1606 → 1701 passing / 1701 collected** (+95 net after dependency fix,
  +207 from new sprints/gap-closure; 0 regressions across the suite)
- 12 files added, 5 files modified across 5 commits (`3c84c47`, `71100c3`,
  `4c597d5`, `5485fb1`, `33028a1`)

### Changed
- `pyproject.toml` `version` 1.0.0 → 1.1.0
- `src/ipracticom_sweeper/__init__.py` `__version__` 1.0.0 → 1.1.0

### Documentation
- This CHANGELOG section documents all 5 sprint deliveries

---

## [1.0.0] — 2026-07-01 — Self-Resilience + Deep Checks + Forecast v2

### Added
- **Sprint 8 (Self-Resilience)**: 5 features, 37 tests
  - External systemd watchdog (slice 8.1)
  - State-dir disk monitor (slice 8.2)
  - Telegram token health probe (slice 8.3)
  - Audit log rotation with size+time cascade (slice 8.4)
  - Self-monitor snapshot section (slice 8.5)
- **Sprint 9 (FreeSWITCH Deep)**: 15 checks, 89 tests
  - FS-26..FS-28: auth failures, call drops, NAT binding (slice 9.1–9.3)
  - FS-29..FS-40: silence, OPTIONS, parse errors, dialplan, conf, vm, mod, ESL, max-procs, CDR pool, license, TPS (slice 9.4–9.15)
- **Sprint 10 (Forecast v2)**: 5 primitives, 50 tests
  - `detect_trend`: OLS-based trend classifier with R²
  - `seasonal_decompose`: trend + seasonal + residual
  - `detect_anomaly`: MAD outlier detector
  - `confidence_bands`: p10/p50/p90 forecast intervals
  - `ensemble_forecast`: weighted blend of multiple models
  - `predict_at_horizon`: OLS extrapolation helper
- **Sprint 15 (Repairs + Runbooks)**: 5 repairs + 2 runbooks, 49 tests
  - `dns_cache_purge`, `fs_inode_warn_clear`, `rotate_audit_now`,
    `telegram_token_revalidate`, `self_healthz_ping`
  - `audit_pressure_runbook`, `self_health_recovery_runbook`
  - Policy engine: `load_policy` now returns `__default__` for unlisted actions

### Tests
- **1121 → 1297** (+176 new tests, 0 failing across all sprints)

### Changed
- `pyproject.toml` `version` 0.6.3 → 1.0.0
- `src/ipracticom_sweeper/__init__.py` `__version__` 0.6.1 → 1.0.0
- `install.sh` default `SWEEPER_BRANCH` v0.6.3 → v1.0.0

### Documentation
- `docs/COVERAGE_MATRIX.md` — 63 features × status × test reference table

---

## [0.6.2] — 2026-07-01 — SPA sidebar unification + tests

### Added
- **SPA sidebar unification** (commits `ff007dc`, `dbd6ebf`, `cf86eb3`): the legacy top-nav is now embedded into both SPA variants (`/spa/a` and `/spa/b`) so every navigation affordance lives in a single sidebar — 9 items (Dashboard, Live State, Modules, Problems, Repairs, Predictions, Evidence, Security, Audit) — instead of being split between a top-nav bar and a sidebar. Same `/api/snapshot` data, fewer competing UI surfaces.
- **Dashboard A/B screenshots** (`docs/dashboard-variant-a.png`, `docs/dashboard-variant-b.png`) — captured from the live `/api/snapshot` with real data for side-by-side peer review.

### Fixed
- `tests/test_dashboard.py`, `tests/test_v6_machines.py`, `tests/test_v6_sidebar.py` — caught and fixed latent failures that would have shipped red with the new SPA sidebar (sidebar items not matching the new shell, machine detail missing the actions panel, sidebar height regression).

### Tests
- **1083 → 1121** (+38 new tests, 0 failing). New SPA sidebar surface covered end-to-end.

### Changed
- `pyproject.toml` `version` 0.6.1 → 0.6.2
- `install.sh` / `bootstrap.sh` default `SWEEPER_BRANCH` v0.6.1 → v0.6.2

## [0.6.1] — 2026-07-01 — one-liner installer + agent_api + SPA A/B

### Added
- **`install.sh` one-liner** (root script): `curl -sSL .../install.sh | sudo bash` — detects OS family (apt/dnf/yum), installs OS deps, clones to `/opt/ipracticom-sweeper`, seeds `/etc/ipracticom-sweeper/agent.env` + `repair_policy.yaml`, enables systemd units, verifies `/healthz`. Supports `SWEEPER_BRANCH=` override and `--uninstall`.
- **Standalone `ipracticom-sweeper-api.service`** — runs the Flask dashboard (with v6 + SPA routes) on `127.0.0.1:8787` as a long-lived service, separated from the periodic sweeper. Bearer-token auth via `AGENT_API_TOKEN` (open mode if unset).
- **`scripts/update.sh`** with `--check` / `--version` / `--rollback`. Backs up `/etc/ipracticom-sweeper/` and operator state to `/var/lib/ipracticom-sweeper/.update_backup` before every pull.
- **SPA dashboard variants A/B** (commit `d79a535`): `/spa` chooser + `/spa/a` (Google AI Studio port, Tailwind+Inter+indigo) + `/spa/b` (impeccable polish, OKLCH+Heebo+motion). Both render the live `/api/snapshot`. New module `ipracticom_sweeper.spa_context` with pure `shape_spa_context` view-model. 11 new tests in `tests/test_spa_variants.py`.

### Fixed
- `test_rtl.py::test_chat_log_classes_use_logical_properties` false-positive: added a `/* --- end Chat shell */` delimiter so the test regex stops at the actual chat block instead of bleeding into v6 CSS. Zero visual change.

### Notes
- Total test count: **1083 passed** (from 1034 in v0.6.0). Full suite exits 0 in ~7 min.
- Skills applied in this cycle: `impeccable`, `emil-design-eng`, `israeli-ui-design-system`, `design-tasks-protocol`, `build-product`.

## [0.6.0] — 2026-07-01 — v6 dashboard rewrite (Sprints 5–7)

### Added — v6 dashboard surface (14 new routes, +3004 LOC, +38 tests)
- **Sprint 5 — Theme + layout (`0db2f9a`):** dark slate CSS theme, sidebar layout (`_v6_sidebar.html`), stats bar (`_v6_stats_bar.html`), `_v6_layout.html` shell, `v6_index.html`. Backwards-compatible with legacy dashboard.
- **Sprint 6 — Machine list + maintenance (`cc6f299`):** `/v6/machines` (table view of all hosts), `/v6/machines/<host>/action` (gated execute), `/v6/machines/<host>/maintenance` + `/maintenance/off` (snooze window for noise reduction).
- **Sprint 7 — Live alerts + log stream + heatmap/uptime (`482fc48`):**
  - `/v6/alerts` + `/v6/alerts/page` — JSON list + HTML wrapper, polled client-side every 5s. Category tabs (network / performance / security / system).
  - `/v6/alerts/<id>/snooze` — durations 15m / 1h / 24h, rejects bad input with 400. Remote mode refuses with 400.
  - `/v6/alerts/<id>/resolve` — same discipline as snooze.
  - `/v6/logs` + `/v6/logs/page` — tails latest 200 lines from `freeswitch.log` → `freeswitch.log.1`, falls back to sweeper audit log. Read-only; pause/play/clear/auto-scroll. POST/PUT/DELETE all rejected.
  - `/v6/metrics/events_heatmap` — 7×24 bucket grid from monitor audit log.
  - `/v6/metrics/uptime_30d` — 30 `{date, ratio}` entries (no-data = 1.0).
  - `/v6/metrics/page` — both above rendered as inline SVG (zero JS frameworks, zero Recharts).

### Safety invariants (held across all v6 writes)
- **Approve-before-mutate:** every v6 write surface (`alerts/snooze`, `alerts/resolve`, `machines/action`, `machines/maintenance`) writes a `RepairProposal`. None of them mutates host state without an explicit operator approval cycle.
- **Remote mode refuses:** the `RemediationClient` remote sentinel rejected at all v6 mutating routes — verified by tests.
- **Read-only enforcement:** all v6 read endpoints reject non-GET methods with 405.

### Tests
- **+38 v6 tests** on top of v0.5.0 baseline:
  - `tests/test_v6_theme.py` — 7 (CSS class wiring)
  - `tests/test_v6_sidebar.py` — 9 (template render + active-link)
  - `tests/test_v6_stats_bar.py` — 10 (badge count, JSON shape)
  - `tests/test_v6_machines.py` — 8 (table render, empty hosts handling)
  - `tests/test_v6_machine_actions.py` — 18 (gating: needs_approval, remote refusal, repair policy stub)
  - `tests/test_v6_alerts.py` — 16 (snooze/resolve happy + sad paths, remote refusal, valid durations)
  - `tests/test_v6_logs.py` — 13 (read-only verification, fallback when FS log missing)
  - `tests/test_v6_metrics.py` — 9 (heatmap bucket math, uptime no-data default = 1.0)
- Legacy dashboard smoke (`tests/test_sweeper.py` + `test_dashboard.py`) — 64/64 pass in 20.9s, **zero regressions**.

### Operator notes
- v6 routes live under `/v6/*`. Legacy `/dashboard`, `/inspector`, `/catalogue`, `/chat`, `/machines` all keep working — no URL was renamed or removed.
- All v6 templates are inline-SVG / vanilla JS — no new frontend dep was added.
- v6 routes inherit the same auth + remote-mode + repair-policy gating as the legacy dashboard.

### Migration
- Update your reverse proxy / dashboard nav if you want v6 as the default. Otherwise nothing changes — both UIs coexist on the same Flask process.


## [0.6.1] — 2026-07-01 — One-liner installer + agent_api service

### Added
- **`install.sh`** at repo root — single-file installer callable as `curl ... | sudo bash`. Detects apt vs dnf, clones to `/opt/ipracticom-sweeper`, installs OS + Python deps, lays out `/var/lib/ipracticom-sweeper/{audit,snapshots,cache,fleet,pending_repairs}`, seeds `/etc/ipracticom-sweeper/repair_policy.yaml` from `etc/`, hands off to `scripts/install-systemd.sh`, verifies `http://127.0.0.1:8787/`. Idempotent. Supports `--uninstall` and `SWEEPER_BRANCH=master`. Closes the gap where every fresh install previously required 4+ manual steps.
- **`systemd/ipracticom-sweeper-api.service`** — new long-running unit binds `python3 -m ipracticom_sweeper.dashboard --port 8787` so `scripts/update.sh --verify` (which hits `/healthz`) actually has a process to talk to. Before this, fresh installs passed `--check` (timer active) but failed `--verify` with `warn: agent_api /healthz not responding`.

### Changed
- **`scripts/install-systemd.sh`** rewritten: now installs ALL three units (sweeper.service, sweeper.timer, sweeper-api.service); seeds `repair_policy.yaml` from `etc/` (not the non-existent `rules/`); adds `--purge` to wipe `/var/lib/ipracticom-sweeper/` for clean re-installs; prints a verification banner.
- **`scripts/update.sh`** Step 8 now probes one `/v6/*` route so a v6 install that breaks the rewrite is caught at upgrade time (was: only `/healthz` check).
- **`sweeper.py`** `--version` flag (prints `ipracticom-sweeper 0.6.1`).
- **`Makefile`** `install` target adds `--break-system-packages` (PEP-668 safe on Debian 12 / RHEL 9). New `make test-v6` smoke target.

### Docs
- **`README.md`** corrected stale numbers: test count 162 → 1034+, monitor modules 9 → 23, added v6 dashboard table, added `version` badge.

### Migration
None for existing installs. New installs gain the API service automatically. Existing installs can manually enable the API with:
```bash
sudo cp systemd/ipracticom-sweeper-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ipracticom-sweeper-api.service
```
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