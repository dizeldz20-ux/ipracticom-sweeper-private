"""FreeSWITCH Tier 1 — service health checks (FS-01..FS-05).

Read-only heartbeat for the FreeSWITCH PBX. Every check returns a
{status, values} dict in the same shape as other monitor modules so it can
slot into monitor.checks.run_all + the snapshot stream.

Checks:
  FS-01  process running       — ps for 'freeswitch' command
  FS-02  systemd unit active   — systemctl is-active freeswitch
  FS-03  port 5060 listening   — SIP signaling port (UDP)
  FS-04  port 5080 listening   — SIP over TLS port (UDP)
  FS-05  fs_cli reachable      — `fs_cli -x status` returns within 5s

Additive module for v0.5.0 Sprint 2 (slice 2.1). End-to-end validation will
happen on the iPracticom AWS POC box; this file uses mocks in tests.

Does NOT restart, reload, or otherwise mutate the service. Repair belongs to
the repair subsystem (separate from monitor).
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from typing import Any

DEFAULT_SIP_PORT = 5060  # FS-03
DEFAULT_SIPS_PORT = 5080  # FS-04
DEFAULT_CLI_TIMEOUT = 5  # FS-05, seconds
DEFAULT_RTP_PORT_LOW = 16384  # FS-09 RTP range low
DEFAULT_RTP_PORT_HIGH = 32768  # FS-09 RTP range high
DEFAULT_REGISTRATIONS_MIN = 1  # FS-07: anything below 1 registered = crit

# Tier-3 (slice 2.3) thresholds
DEFAULT_FS_CLI_LATENCY_WARN_MS = 500   # FS-10
DEFAULT_FS_CLI_LATENCY_CRIT_MS = 2000  # FS-10
DEFAULT_ACTIVE_CALLS_WARN = 100        # FS-11
DEFAULT_ACTIVE_CALLS_CRIT = 500        # FS-11
DEFAULT_ACTIVE_CHANNELS_WARN = 200     # FS-12
DEFAULT_ACTIVE_CHANNELS_CRIT = 1000    # FS-12
DEFAULT_LOG_DISK_PCT_WARN = 80         # FS-13
DEFAULT_LOG_DISK_PCT_CRIT = 95         # FS-13
DEFAULT_CONFIG_DRIFT_DAYS_WARN = 60    # FS-14
DEFAULT_CONFIG_DRIFT_DAYS_CRIT = 180   # FS-14
DEFAULT_BASELINE_DRIFT_FACTOR_WARN = 2.0  # FS-15: 2× baseline = warn
DEFAULT_BASELINE_DRIFT_FACTOR_CRIT = 4.0  # FS-15: 4× baseline = crit


# --- Low-level helpers ------------------------------------------------------


def _run(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    """Subprocess.run with timeout + uniform error envelope.

    Returns (rc, stdout, stderr). Never raises for normal failures.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "command not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def _port_listening(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """Return True if a UDP socket can be opened on (host, port)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        # Try to *bind* to confirm presence; if something else has the port we
        # get EADDRINUSE. Connecting on UDP is a poor signal.
        try:
            sock.bind((host, port))
            # We managed to bind → nothing was listening.
            sock.close()
            return False
        except OSError:
            # EADDRINUSE → port is held by another process.
            return True
    finally:
        try:
            sock.close()
        except Exception:
            pass


# --- FS-01..05 individual checks -------------------------------------------


def check_fs01_process_running() -> dict[str, Any]:
    """FS-01: a `freeswitch` process is visible in `ps`.

    Uses `ps -eo comm` to scan for the literal process name. Missing ps or
    no process → status=crit.
    """
    rc, out, _ = _run(["ps", "-eo", "comm"], timeout=3)
    if rc != 0:
        return {
            "status": "crit",
            "values": {
                "fs01_ps_rc": rc,
                "fs01_running": False,
                "fs01_pids": [],
            },
        }
    pids: list[int] = []
    target = "freeswitch"
    rc2, out2, _ = _run(["pgrep", "-x", target], timeout=3)
    if rc2 == 0 and out2.strip():
        for tok in out2.split():
            if tok.strip().isdigit():
                pids.append(int(tok))
    running = bool(pids)
    return {
        "status": "ok" if running else "crit",
        "values": {
            "fs01_ps_rc": rc,
            "fs01_running": running,
            "fs01_pids": pids,
        },
    }


def check_fs02_systemd_active(unit: str = "freeswitch") -> dict[str, Any]:
    """FS-02: systemd reports the FreeSWITCH unit as `active`.

    Returns the raw systemctl output for operator diagnosis.
    """
    rc, out, _ = _run(["systemctl", "is-active", "--quiet", f"{unit}.service"], timeout=5)
    active = rc == 0
    return {
        "status": "ok" if active else "crit",
        "values": {
            "fs02_unit": unit,
            "fs02_active": active,
            "fs02_systemctl_rc": rc,
        },
    }


def check_fs03_sip_port(port: int = DEFAULT_SIP_PORT) -> dict[str, Any]:
    """FS-03: UDP/5060 (SIP) is held by a process."""
    listening = _port_listening(port)
    return {
        "status": "ok" if listening else "crit",
        "values": {
            "fs03_port": port,
            "fs03_listening": listening,
        },
    }


def check_fs04_sips_port(port: int = DEFAULT_SIPS_PORT) -> dict[str, Any]:
    """FS-04: UDP/5080 (SIP over TLS) is held by a process."""
    listening = _port_listening(port)
    return {
        "status": "ok" if listening else "crit",
        "values": {
            "fs04_port": port,
            "fs04_listening": listening,
        },
    }


def check_fs05_cli_reachable(timeout: int = DEFAULT_CLI_TIMEOUT) -> dict[str, Any]:
    """FS-05: `fs_cli -x 'status'` returns successfully within `timeout` sec.

    If `fs_cli` is not on PATH we report crit with a clear reason (operators
    need to know whether the failure is "FS is sick" or "FS isn't installed").
    """
    if shutil.which("fs_cli") is None:
        return {
            "status": "crit",
            "values": {
                "fs05_cli_path": None,
                "fs05_cli_rc": 127,
                "fs05_reachable": False,
                "fs05_reason": "fs_cli not on PATH",
            },
        }
    rc, out, err = _run(["fs_cli", "-x", "status"], timeout=timeout)
    reachable = rc == 0
    return {
        "status": "ok" if reachable else "crit",
        "values": {
            "fs05_cli_rc": rc,
            "fs05_reachable": reachable,
            "fs05_elapsed_ms": None,  # populated by snapshot if needed
            "fs05_output_excerpt": out.strip()[:120],
        },
    }


# --- FS-06..09 network integrity (Sprint 2 slice 2.2) ---------------------


def _run_fscli(command: str, timeout: int = DEFAULT_CLI_TIMEOUT) -> dict[str, Any]:
    """Invoke `fs_cli -x <command>` and return a uniform dict.

    Reads the rc, stdout, stderr. If fs_cli is not on PATH, returns
    rc=127 with a clear reason; callers should treat that as "could not
    inspect" rather than "FS is broken".
    """
    if shutil.which("fs_cli") is None:
        return {"rc": 127, "stdout": "", "stderr": "fs_cli not on PATH"}
    rc, out, err = _run(["fs_cli", "-x", command], timeout=timeout)
    return {"rc": rc, "stdout": out, "stderr": err}


def _parse_int_from_fscli(out: str, last_token: bool = True) -> int | None:
    """Best-effort int extractor for fs_cli output.

    Strategy: take the *last* whitespace-separated token that looks like an
    int. Many fs_cli `show ... count` commands return "<N> total." or
    "<N> entries." — we want that number, not the leading label words.

    Returns None when no numeric token is found.
    """
    if not out:
        return None
    for tok in reversed(out.split()):
        tok = tok.strip(".,")
        if tok.isdigit():
            return int(tok)
    return None


def check_fs06_sip_peers(min_peers: int = 1) -> dict[str, Any]:
    """FS-06: `show endpoints count` returns >= `min_peers`.

    We measure *configured* SIP endpoints. Zero configured endpoints = the
    PBX is online but useless → warn (operators may be migrating). A
    negative read (CLI ok but parsing empty) → warn (we don't know).
    """
    res = _run_fscli("show endpoints count")
    if res["rc"] != 0:
        return {
            "status": "warn",
            "values": {
                "fs06_cli_rc": res["rc"],
                "fs06_endpoint_count": None,
                "fs06_min_peers": min_peers,
                "fs06_reason": "cli failed",
            },
        }
    n = _parse_int_from_fscli(res["stdout"])
    if n is None:
        return {
            "status": "warn",
            "values": {
                "fs06_cli_rc": res["rc"],
                "fs06_endpoint_count": None,
                "fs06_min_peers": min_peers,
                "fs06_reason": "could not parse count",
            },
        }
    ok = n >= min_peers
    return {
        "status": "ok" if ok else "warn",
        "values": {
            "fs06_cli_rc": res["rc"],
            "fs06_endpoint_count": n,
            "fs06_min_peers": min_peers,
        },
    }


def check_fs07_sip_registrations(min_registrations: int = DEFAULT_REGISTRATIONS_MIN) -> dict[str, Any]:
    """FS-07: at least one SIP registration is active.

    Zero registrations on an otherwise-healthy PBX is a hard crit — phones
    cannot place/receive calls. CLI failure is warn (don't page on infra).
    """
    res = _run_fscli("show registrations count")
    if res["rc"] != 0:
        return {
            "status": "warn",
            "values": {
                "fs07_cli_rc": res["rc"],
                "fs07_registration_count": None,
                "fs07_min_registrations": min_registrations,
                "fs07_reason": "cli failed",
            },
        }
    n = _parse_int_from_fscli(res["stdout"])
    if n is None:
        return {
            "status": "warn",
            "values": {
                "fs07_cli_rc": res["rc"],
                "fs07_registration_count": None,
                "fs07_min_registrations": min_registrations,
                "fs07_reason": "could not parse count",
            },
        }
    ok = n >= min_registrations
    return {
        "status": "ok" if ok else "crit",
        "values": {
            "fs07_cli_rc": res["rc"],
            "fs07_registration_count": n,
            "fs07_min_registrations": min_registrations,
        },
    }


def check_fs08_gateway_status() -> dict[str, Any]:
    """FS-08: at least one SIP gateway is in `REGED`/`UP` state.

    `sofia status` prints a table; we use `sofia status gateway` and look
    for `REGED` in the output. If the operator runs a single-gateway setup,
    zero working gateways = warn (degraded call quality / failover only).
    """
    res = _run_fscli("sofia status gateway")
    if res["rc"] != 0:
        return {
            "status": "warn",
            "values": {
                "fs08_cli_rc": res["rc"],
                "fs08_gateway_count": None,
                "fs08_gateway_up": None,
                "fs08_reason": "cli failed",
            },
        }
    out = res["stdout"].upper()
    gateway_up = out.count("REGED") + out.count(" UP ")
    has_any_gateway = ("REGED" in out or "NOREG" in out or
                       " UNREGED" in out or "UP" in out)
    if not has_any_gateway and not gateway_up:
        return {
            "status": "warn",
            "values": {
                "fs08_cli_rc": res["rc"],
                "fs08_gateway_count": 0,
                "fs08_gateway_up": 0,
                "fs08_reason": "no gateway block in output",
            },
        }
    return {
        "status": "ok" if gateway_up > 0 else "warn",
        "values": {
            "fs08_cli_rc": res["rc"],
            "fs08_gateway_count": max(gateway_up, 1),
            "fs08_gateway_up": gateway_up,
        },
    }


def check_fs09_rtp_ports_open(
    low: int = DEFAULT_RTP_PORT_LOW, high: int = DEFAULT_RTP_PORT_HIGH
) -> dict[str, Any]:
    """FS-09: at least one UDP port in the RTP range is bound by FS.

    We can't reliably bind-check the entire range without permissions; instead
    we spot-check three anchors (low/mid/high). If any of them is held, FS
    has at least claimed an RTP port. If all three are free AND FS is
    otherwise healthy (FS-01 ok), we treat this as a soft warn so we don't
    page on a transient race.
    """
    anchors = (low, (low + high) // 2, high)

    def _held(port: int) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("127.0.0.1", port))
            return False  # succeeded → port was free
        except OSError:
            return True  # EADDRINUSE → held by something (very likely FS)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    results = {p: _held(p) for p in anchors}
    held_count = sum(1 for v in results.values() if v)
    ok = held_count >= 1

    return {
        "status": "ok" if ok else "warn",
        "values": {
            "fs09_port_range": [low, high],
            "fs09_anchors_checked": list(anchors),
            "fs09_anchors_held": results,
            "fs09_anchors_held_count": held_count,
        },
    }


# --- Aggregator -------------------------------------------------------------


def _worst(*statuses: str) -> str:
    order = {"ok": 0, "warn": 1, "crit": 2}
    return max(statuses, key=lambda s: order.get(s, 0))


def collect_all() -> dict[str, Any]:
    """Run FS-01..05 and return merged `values` for the snapshot module.

    A single `freeswitch` module in the snapshot carries all five flags so
    downstream UI can highlight the specific subsystem that is down.
    """
    fs01 = check_fs01_process_running()
    fs02 = check_fs02_systemd_active()
    fs03 = check_fs03_sip_port()
    fs04 = check_fs04_sips_port()
    fs05 = check_fs05_cli_reachable()

    return {
        "fs01_process_running": fs01["values"]["fs01_running"],
        "fs02_systemd_active": fs02["values"]["fs02_active"],
        "fs03_sip_port_5060": fs03["values"]["fs03_listening"],
        "fs04_sips_port_5080": fs04["values"]["fs04_listening"],
        "fs05_cli_reachable": fs05["values"]["fs05_reachable"],
        "fs05_cli_reason": fs05["values"].get("fs05_reason"),
        "fs01_pids": fs01["values"]["fs01_pids"],
    }


def evaluate(values: dict[str, Any], rules: dict | None = None) -> str:
    """Tier-1 evaluate: FS-01..05 liveness.

    All five must be ok. Any failure → crit (FS being down = phone system down).
    Kept as a separate function so Tier-2 checks (FS-06..09) can have their own
    softer evaluation.
    """
    if not values.get("fs01_process_running"):
        return "crit"
    if not values.get("fs02_systemd_active"):
        return "crit"
    if not values.get("fs03_sip_port_5060"):
        return "crit"
    if not values.get("fs04_sips_port_5080"):
        return "crit"
    if not values.get("fs05_cli_reachable"):
        return "crit"
    return "ok"


# --- FS-10..15 operational + baseline drift (Sprint 2 slice 2.3) --------


def check_fs10_cli_latency(
    warn_ms: int = DEFAULT_FS_CLI_LATENCY_WARN_MS,
    crit_ms: int = DEFAULT_FS_CLI_LATENCY_CRIT_MS,
) -> dict[str, Any]:
    """FS-10: time a `fs_cli -x status` round-trip.

    Slow CLI is usually a sign of disk pressure or an under-resourced VM.
    Misses to call fs_cli (PATH) → status=warn with explicit reason.
    """
    import time as _time

    if shutil.which("fs_cli") is None:
        return {
            "status": "warn",
            "values": {
                "fs10_cli_rc": 127,
                "fs10_elapsed_ms": None,
                "fs10_warn_ms": warn_ms,
                "fs10_crit_ms": crit_ms,
                "fs10_reason": "fs_cli not on PATH",
            },
        }
    started = _time.monotonic()
    rc, _, _ = _run(["fs_cli", "-x", "status"], timeout=10)
    elapsed_ms = int((_time.monotonic() - started) * 1000)
    if rc != 0:
        return {
            "status": "warn",
            "values": {
                "fs10_cli_rc": rc,
                "fs10_elapsed_ms": elapsed_ms,
                "fs10_warn_ms": warn_ms,
                "fs10_crit_ms": crit_ms,
                "fs10_reason": "cli error",
            },
        }
    if elapsed_ms >= crit_ms:
        status = "crit"
    elif elapsed_ms >= warn_ms:
        status = "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "values": {
            "fs10_cli_rc": rc,
            "fs10_elapsed_ms": elapsed_ms,
            "fs10_warn_ms": warn_ms,
            "fs10_crit_ms": crit_ms,
        },
    }


def check_fs11_active_calls(
    warn: int = DEFAULT_ACTIVE_CALLS_WARN,
    crit: int = DEFAULT_ACTIVE_CALLS_CRIT,
) -> dict[str, Any]:
    """FS-11: count of in-progress calls from `show calls count`.

    Thresholds are advisory — a busy contact-center may legitimately exceed
    `warn`. The number is what matters for dashboards + diffs over time.
    """
    res = _run_fscli("show calls count")
    if res["rc"] != 0:
        return {
            "status": "warn",
            "values": {
                "fs11_cli_rc": res["rc"],
                "fs11_active_calls": None,
                "fs11_warn": warn,
                "fs11_crit": crit,
                "fs11_reason": "cli failed",
            },
        }
    n = _parse_int_from_fscli(res["stdout"])
    if n is None:
        return {
            "status": "warn",
            "values": {
                "fs11_cli_rc": res["rc"],
                "fs11_active_calls": None,
                "fs11_warn": warn,
                "fs11_crit": crit,
                "fs11_reason": "could not parse count",
            },
        }
    if n >= crit:
        status = "crit"
    elif n >= warn:
        status = "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "values": {
            "fs11_cli_rc": res["rc"],
            "fs11_active_calls": n,
            "fs11_warn": warn,
            "fs11_crit": crit,
        },
    }


def check_fs12_active_channels(
    warn: int = DEFAULT_ACTIVE_CHANNELS_WARN,
    crit: int = DEFAULT_ACTIVE_CHANNELS_CRIT,
) -> dict[str, Any]:
    """FS-12: count of open channels (== calls × legs usually).

    High channel count vs. low calls count = media not being torn down,
    possible leak.
    """
    res = _run_fscli("show channels count")
    if res["rc"] != 0:
        return {
            "status": "warn",
            "values": {
                "fs12_cli_rc": res["rc"],
                "fs12_active_channels": None,
                "fs12_warn": warn,
                "fs12_crit": crit,
                "fs12_reason": "cli failed",
            },
        }
    n = _parse_int_from_fscli(res["stdout"])
    if n is None:
        return {
            "status": "warn",
            "values": {
                "fs12_cli_rc": res["rc"],
                "fs12_active_channels": None,
                "fs12_warn": warn,
                "fs12_crit": crit,
                "fs12_reason": "could not parse count",
            },
        }
    if n >= crit:
        status = "crit"
    elif n >= warn:
        status = "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "values": {
            "fs12_cli_rc": res["rc"],
            "fs12_active_channels": n,
            "fs12_warn": warn,
            "fs12_crit": crit,
        },
    }


def check_fs13_log_disk_usage(
    log_path: str = "/var/log/freeswitch",
    warn_pct: int = DEFAULT_LOG_DISK_PCT_WARN,
    crit_pct: int = DEFAULT_LOG_DISK_PCT_CRIT,
) -> dict[str, Any]:
    """FS-13: disk usage of the FS log directory as a % of its parent FS.

    We don't have `du` semantics in pure Python without scanning — we use
    `shutil.disk_usage` on the directory's mount point as an approximation.
    For an exact measurement, install logs.shutil.disk_usage would need an
    extra recursion step which we defer. The approximation is fine for
    *trend* alerts because errors of a few GB don't change the alert tone.
    """
    try:
        usage = shutil.disk_usage(log_path)
        used_pct = round(usage.used * 100.0 / usage.total, 1)
    except (FileNotFoundError, OSError) as e:
        return {
            "status": "warn",
            "values": {
                "fs13_path": log_path,
                "fs13_used_pct": None,
                "fs13_warn_pct": warn_pct,
                "fs13_crit_pct": crit_pct,
                "fs13_reason": str(e),
            },
        }
    if used_pct >= crit_pct:
        status = "crit"
    elif used_pct >= warn_pct:
        status = "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "values": {
            "fs13_path": log_path,
            "fs13_used_pct": used_pct,
            "fs13_warn_pct": warn_pct,
            "fs13_crit_pct": crit_pct,
        },
    }


def check_fs14_config_drift_days(
    config_path: str = "/etc/freeswitch/freeswitch.xml",
    warn_days: int = DEFAULT_CONFIG_DRIFT_DAYS_WARN,
    crit_days: int = DEFAULT_CONFIG_DRIFT_DAYS_CRIT,
) -> dict[str, Any]:
    """FS-14: age of the FS configuration in days.

    If nobody has touched the config in months, the instance likely fell
    off the upgrade cadence. Operators can use this to schedule reviews.
    """
    try:
        mtime = os.path.getmtime(config_path)
    except (FileNotFoundError, OSError) as e:
        return {
            "status": "warn",
            "values": {
                "fs14_path": config_path,
                "fs14_age_days": None,
                "fs14_warn_days": warn_days,
                "fs14_crit_days": crit_days,
                "fs14_reason": str(e),
            },
        }
    import time as _time
    age_days = int((_time.time() - mtime) / 86400)
    if age_days >= crit_days:
        status = "crit"
    elif age_days >= warn_days:
        status = "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "values": {
            "fs14_path": config_path,
            "fs14_age_days": age_days,
            "fs14_warn_days": warn_days,
            "fs14_crit_days": crit_days,
        },
    }


def check_fs15_baseline_calls_per_hour(
    baseline_calls_per_hour: float | None = None,
    warn_factor: float = DEFAULT_BASELINE_DRIFT_FACTOR_WARN,
    crit_factor: float = DEFAULT_BASELINE_DRIFT_FACTOR_CRIT,
) -> dict[str, Any]:
    """FS-15: calls-per-hour vs. a learned baseline.

    When the operator hasn't set a baseline yet (`baseline_calls_per_hour`
    is None), we report ok with `fs15_baseline_set=False` so the UI can
    hide this check rather than emit a spurious warning.
    """
    res = _run_fscli("show calls count")
    if res["rc"] != 0:
        return {
            "status": "warn",
            "values": {
                "fs15_cli_rc": res["rc"],
                "fs15_current_calls": None,
                "fs15_baseline": baseline_calls_per_hour,
                "fs15_reason": "cli failed",
            },
        }
    current = _parse_int_from_fscli(res["stdout"])
    if baseline_calls_per_hour is None or baseline_calls_per_hour <= 0:
        return {
            "status": "ok",
            "values": {
                "fs15_cli_rc": res["rc"],
                "fs15_current_calls": current,
                "fs15_baseline": None,
                "fs15_baseline_set": False,
            },
        }
    ratio = (current or 0) / baseline_calls_per_hour
    if ratio >= crit_factor:
        status = "crit"
    elif ratio >= warn_factor:
        status = "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "values": {
            "fs15_cli_rc": res["rc"],
            "fs15_current_calls": current,
            "fs15_baseline": baseline_calls_per_hour,
            "fs15_baseline_set": True,
            "fs15_drift_factor": round(ratio, 2),
            "fs15_warn_factor": warn_factor,
            "fs15_crit_factor": crit_factor,
        },
    }


# --- FS-06..09 aggregator (Tier 2 / network integrity) --------------------


def collect_network() -> dict[str, Any]:
    """Run FS-06..09 and return a parallel dict.

    Lives separately from collect_all() so the Tier-1 snapshot shape stays
    identical (additive). The pipeline can choose to merge both into the
    same `freeswitch` module or split them later.
    """
    fs06 = check_fs06_sip_peers()
    fs07 = check_fs07_sip_registrations()
    fs08 = check_fs08_gateway_status()
    fs09 = check_fs09_rtp_ports_open()

    return {
        "fs06_endpoint_count": fs06["values"]["fs06_endpoint_count"],
        "fs06_min_peers": fs06["values"]["fs06_min_peers"],
        "fs07_registration_count": fs07["values"]["fs07_registration_count"],
        "fs07_min_registrations": fs07["values"]["fs07_min_registrations"],
        "fs08_gateway_up": fs08["values"]["fs08_gateway_up"],
        "fs08_gateway_count": fs08["values"]["fs08_gateway_count"],
        "fs09_anchors_held_count": fs09["values"]["fs09_anchors_held_count"],
        "fs09_port_range": fs09["values"]["fs09_port_range"],
        # per-check status, useful for UI drilldown
        "fs06_status": fs06["status"],
        "fs07_status": fs07["status"],
        "fs08_status": fs08["status"],
        "fs09_status": fs09["status"],
    }


def evaluate_network(values: dict[str, Any], rules: dict | None = None) -> str:
    """Tier-2 evaluate: FS-06..09 network integrity.

    Semantics:
      - FS-07 (registrations == 0)        → crit (no phones registered)
      - any other check warn/crit         → warn

    `rules` is accepted for symmetry with other modules; future thresholds
    (e.g. "warn if endpoint_count < 5") will read from rules["freeswitch"].
    """
    if values.get("fs07_registration_count") is not None and \
            values["fs07_registration_count"] < values.get("fs07_min_registrations", 1):
        return "crit"
    statuses = [
        values.get("fs06_status", "warn"),
        values.get("fs08_status", "warn"),
        values.get("fs09_status", "warn"),
    ]
    order = {"ok": 0, "warn": 1, "crit": 2}
    worst = max(statuses, key=lambda s: order.get(s, 1))
    return worst


# --- FS-10..15 aggregator (Tier 3 / operational + baseline drift) -------


def collect_operational(
    fs_baseline_calls_per_hour: float | None = None,
) -> dict[str, Any]:
    """Run FS-10..15 and return a parallel dict for the snapshot module."""
    fs10 = check_fs10_cli_latency()
    fs11 = check_fs11_active_calls()
    fs12 = check_fs12_active_channels()
    fs13 = check_fs13_log_disk_usage()
    fs14 = check_fs14_config_drift_days()
    fs15 = check_fs15_baseline_calls_per_hour(
        baseline_calls_per_hour=fs_baseline_calls_per_hour
    )

    return {
        "fs10_elapsed_ms": fs10["values"]["fs10_elapsed_ms"],
        "fs10_warn_ms": fs10["values"]["fs10_warn_ms"],
        "fs10_crit_ms": fs10["values"]["fs10_crit_ms"],
        "fs11_active_calls": fs11["values"]["fs11_active_calls"],
        "fs11_warn": fs11["values"]["fs11_warn"],
        "fs11_crit": fs11["values"]["fs11_crit"],
        "fs12_active_channels": fs12["values"]["fs12_active_channels"],
        "fs12_warn": fs12["values"]["fs12_warn"],
        "fs12_crit": fs12["values"]["fs12_crit"],
        "fs13_used_pct": fs13["values"]["fs13_used_pct"],
        "fs13_path": fs13["values"]["fs13_path"],
        "fs14_age_days": fs14["values"]["fs14_age_days"],
        "fs14_warn_days": fs14["values"]["fs14_warn_days"],
        "fs14_crit_days": fs14["values"]["fs14_crit_days"],
        "fs15_current_calls": fs15["values"]["fs15_current_calls"],
        "fs15_baseline": fs15["values"]["fs15_baseline"],
        "fs15_baseline_set": fs15["values"].get("fs15_baseline_set", False),
        "fs15_drift_factor": fs15["values"].get("fs15_drift_factor"),
        "fs10_status": fs10["status"],
        "fs11_status": fs11["status"],
        "fs12_status": fs12["status"],
        "fs13_status": fs13["status"],
        "fs14_status": fs14["status"],
        "fs15_status": fs15["status"],
    }


def evaluate_operational(values: dict[str, Any], rules: dict | None = None) -> str:
    """Tier-3 evaluate: FS-10..15.

    Tier-3 checks are advisory — even a crit here means "investigate" rather
    than "phone system down". The evaluator returns the worst of the
    per-check statuses so the snapshot module still reflects severity.
    """
    statuses = [
        values.get("fs10_status", "warn"),
        values.get("fs11_status", "warn"),
        values.get("fs12_status", "warn"),
        values.get("fs13_status", "warn"),
        values.get("fs14_status", "warn"),
        values.get("fs15_status", "warn"),
    ]
    order = {"ok": 0, "warn": 1, "crit": 2}
    worst = max(statuses, key=lambda s: order.get(s, 1))
    return worst
