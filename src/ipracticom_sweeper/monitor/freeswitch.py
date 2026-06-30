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

import shutil
import socket
import subprocess
import time
from typing import Any

DEFAULT_SIP_PORT = 5060  # FS-03
DEFAULT_SIPS_PORT = 5080  # FS-04
DEFAULT_CLI_TIMEOUT = 5  # FS-05, seconds


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

    overall = _worst(
        fs01["status"], fs02["status"], fs03["status"], fs04["status"], fs05["status"]
    )

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
    """All five must be ok. Any failure → crit (FS being down = phone system down).

    `rules` is accepted for symmetry with other modules but currently unused;
    future thresholds (e.g. "warn if fs_cli latency > 2s") can be added
    without changing the call signature.
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
