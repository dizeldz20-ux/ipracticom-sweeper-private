# iPracticom AWS Linux Sweeper

> Server health monitor and safe auto-repair agent for AWS Linux fleets.
> Built for [iPracticom](https://github.com/dizeldz20-ux) production operations.

[![tests](https://img.shields.io/badge/tests-162%20passing-brightgreen)]()
[![python](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![license](https://img.shields.io/badge/license-internal-lightgrey)]()

## What it does

The sweeper runs every 5 minutes on each host (via systemd timer) and:

1. **Monitors** 9 subsystems (CPU, memory, disk, network, services, logs, processes, security, AWS metadata)
2. **Diagnoses** findings against threshold rules and assigns a DEFCON level (5=green, 1=black)
3. **Repairs** safe issues automatically (drop_caches, journald vacuum)
4. **Notifies** Slack and/or Telegram when DEFCON ≤ 4 or when a security issue is detected
5. **Audits** every action to an append-only JSONL log

All monitoring, diagnosis and repair is **deterministic, rules-based, and audit-able**. The agent never calls an LLM in the hot path.

## Architecture

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Monitor     │──▶│   Diagnose   │──▶│   Repair     │
│  9 modules   │   │   DEFCON     │   │  safe only   │
└──────────────┘   └──────────────┘   └──────────────┘
       │                  │                  │
       ▼                  ▼                  ▼
   /proc/*           Rules + RepairSafety   /proc/sys/vm
   journalctl        Worst-wins defcon      journalctl --vacuum
   systemctl         safe_repairs list     systemctl restart
```

Every repair is preceded by a snapshot (`/var/lib/ipracticom-sweeper/snapshots/<uuid>.json`) for rollback.

## Quick start

### One-shot run

```bash
pip install -e .[dev]  # or: /usr/bin/python3 -m pip install -e . --break-system-packages
python3 -m ipracticom_sweeper.sweeper --json
```

### As a systemd service (recommended)

```bash
sudo bash scripts/install-systemd.sh
```

This will:
- Install the package site-wide
- Create `/var/lib/ipracticom-sweeper/{audit,snapshots,cache}`
- Enable the timer to run every 5 minutes
- Trigger one initial run

```bash
journalctl -u ipracticom-sweeper -f           # follow logs
systemctl list-timers ipracticom-sweeper       # next runs
systemctl start ipracticom-sweeper.service     # manual run
sudo bash scripts/install-systemd.sh --uninstall  # remove
```

### Dashboard (local mode)

```bash
python3 -m ipracticom_sweeper.dashboard --port 8787
open http://127.0.0.1:8787/
```

### Agent API (for fleet / remote dashboards)

```bash
AGENT_API_TOKEN=your-secret-token \
    python3 -m ipracticom_sweeper.agent_api --port 8787 --host 0.0.0.0
```

Endpoints:
- `GET  /healthz` — liveness + identity
- `GET  /api/snapshot` — latest cached result (auth: `Bearer <token>` if token configured)
- `GET  /api/snapshot/raw` — last 100 audit events (JSONL)
- `POST /api/run` — trigger fresh sweep
- `POST /api/notify/test` — send a test notification

### Dashboard connecting to remote agent

```bash
SWEEPER_REMOTE_URL=http://10.0.0.5:8787 \
SWEEPER_REMOTE_TOKEN=your-secret-token \
    python3 -m ipracticom_sweeper.dashboard --port 8790
```

The dashboard auto-detects `SWEEPER_REMOTE_URL` and proxies all data through the agent. The UI shows a "REMOTE MODE" badge.

## Configuration

Threshold rules live in `rules/default.yaml`. The agent loads defaults if the file is missing:

```yaml
cpu:
  load_avg_5min_warn: 2.0
  load_avg_5min_crit: 5.0
memory:
  used_percent_warn: 80
  used_percent_crit: 95
disk:
  used_percent_warn: 80
  used_percent_crit: 95
  read_only_mounts: ["/"]  # which mounts must be RO
services:
  critical_list: [nginx, postgresql]  # must be running
```

CLI overrides:

```bash
python3 -m ipracticom_sweeper.sweeper --rules /etc/iprcticom/rules.yaml --json
```

## Notifications

Set these env vars on the agent host:

```bash
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
export TELEGRAM_BOT_TOKEN=123456:abc...
export TELEGRAM_CHAT_ID=-1001234567890
```

The agent sends notifications when:
- DEFCON ≤ 4 (yellow / orange / red / black)
- `force=True` (manual override for "still alive" pings)

Green runs are silent — no notification spam on healthy hosts.

## DEFCON levels

| Level | Label | Meaning | Auto-repair? |
|---|---|---|---|
| 5 | green | All healthy | n/a |
| 4 | yellow | Warning threshold tripped | No (log only) |
| 3 | orange | Critical threshold tripped | Yes if safe |
| 2 | red | Critical + persistent | Yes if GUARDED (with snapshot) |
| 1 | black | Unknown state / monitor crashed | No — alert humans |

## Repair actions

| Action | Safety | What it does |
|---|---|---|
| `drop_caches` | SAFE | Writes to `/proc/sys/vm/drop_caches` (level 1/2/3) |
| `log_truncate_journald` | GUARDED | `journalctl --vacuum-time=7d` |
| `service_restart` | GUARDED | `systemctl restart <unit>` (critical services only) |
| `top_processes_snapshot` | SAFE | Captures top-N by CPU for forensics |
| `notify_human` | SAFE | Sends to Slack/Telegram |

Snapshots are stored in `/var/lib/ipracticom-sweeper/snapshots/<uuid>.json`. Rollback commands are encoded in each snapshot.

## Testing

```bash
python3 -m pytest tests/ -v
```

Test count: **162 tests** across 9 modules.

## Architecture diagrams

The pipeline runs 5 steps:

1. **Monitor** → 9 modules collect from `/proc`, journalctl, systemctl, boto3
2. **Adapt** → normalize field names (e.g. `mount` → `mountpoint`)
3. **Diagnose** → 5 diagnosers (cpu/memory/disk/services/security) → DEFCON + safe_repairs + needs_human
4. **Repair** → iterate over safe_repairs, snapshot → execute → audit
5. **Notify** → DEFCON<5: send Slack/Telegram, else silent

## Security notes

- The agent API requires a bearer token (`AGENT_API_TOKEN`) for any operation beyond `/healthz`.
- Default bind is `127.0.0.1` — change to `0.0.0.0` only inside a trusted network or behind a reverse proxy with TLS.
- The dashboard exposes only cached data — no write access.
- Repair actions are tagged with safety levels. SECURITY-class actions always escalate to humans (`DANGEROUS`, never auto-executed).

## Files

```
src/ipracticom_sweeper/
├── sweeper.py          # CLI entry point
├── pipeline.py         # Orchestrator (5 steps)
├── config.py           # Rules + DEFCON levels
├── notify.py           # Slack + Telegram formatter
├── monitor/            # 9 collector modules
├── diagnose/           # DEFCON engine + adapter
├── repair/             # 5 repair actions + snapshot system
├── audit/              # JSONL event log
├── dashboard.py        # Flask UI (local + remote)
├── agent_api.py        # Standalone HTTP API
└── agent_client.py     # Typed HTTP client
tests/                  # 162 tests
systemd/                # service + timer units
scripts/                # install-systemd.sh
```

## License

Internal — iPracticom 2026.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).