"""AWS SSM connector — collect health snapshots from remote EC2 instances.

Why this exists
---------------
The sweeper normally runs *on* the host it monitors. For a fleet of EC2
instances (production: tens or hundreds), we don't want to install the
agent on each box. Instead, the agent runs once on the operator's box
("Claude's box") and uses AWS Systems Manager (SSM) to run commands on
remote hosts and pull back the results.

What it does
------------
For each EC2 instance returned by `list_instances`:
  1. Ships a small embedded Python script via SSM `SendCommand`
  2. The script (a) collects the same signals as `monitor/health.py`,
     (b) prints them as a single JSON line on stdout
  3. We poll SSM `GetCommandInvocation` until the command finishes
  4. We parse stdout into a HostSnapshot dict

The connector is decoupled from the rest of the sweeper: it only knows
how to talk to SSM. The fleet aggregator decides which instances to
poll and merges results.

Security
--------
- No SSH keys. SSM uses IAM roles attached to each EC2.
- The connector assumes the calling host has AWS credentials available
  (env, ~/.aws/credentials, IAM instance role, etc.).
- The remote script is read-only: it never touches `/proc/sys/vm`,
  never restarts services, never modifies state. Repairs are dispatched
  separately via SSM `SendCommand` with explicit action + params.

Rate limits
-----------
SSM `SendCommand` has a quota of 100 concurrent commands per account.
We serialize with a bounded semaphore (default 5 in flight) to stay
well under the limit and avoid throttling on large fleets.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# --- Embedded remote collection script --------------------------------------
# This runs on each remote EC2. It is intentionally read-only.
# We inline it as a single string instead of shipping a separate .py file
# so SSM SendCommand has exactly one payload to ship.

REMOTE_COLLECT_SCRIPT = r'''
import json, os, shutil, socket, subprocess, sys


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return default


def _cmd(*args, timeout=10):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def collect():
    out = {
        "host": socket.gethostname(),
        "collected_at": _cmd("date", "-u", "+%Y-%m-%dT%H:%M:%SZ"),
        "uptime_seconds": 0,
        "load": {"1m": 0.0, "5m": 0.0, "15m": 0.0},
        "memory": {"total_kb": 0, "available_kb": 0, "used_percent": 0.0},
        "disk": {"used_percent": 0.0, "path": "/"},
        "top_processes": [],
        "failed_units": [],
        "kernel": _read("/proc/sys/kernel/osrelease", "unknown").strip(),
        "boot_id": _read("/proc/sys/kernel/random/boot_id", "").strip(),
    }

    # --- uptime -----------------------------------------------------------
    try:
        with open("/proc/uptime") as f:
            out["uptime_seconds"] = int(float(f.read().split()[0]))
    except Exception:
        pass

    # --- load average -----------------------------------------------------
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            out["load"]["1m"] = float(parts[0])
            out["load"]["5m"] = float(parts[1])
            out["load"]["15m"] = float(parts[2])
    except Exception:
        pass

    # --- memory -----------------------------------------------------------
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k.strip()] = v.strip().split()[0]  # value in kB
        total = int(info.get("MemTotal", 0))
        avail = int(info.get("MemAvailable", info.get("MemFree", 0)))
        out["memory"]["total_kb"] = total
        out["memory"]["available_kb"] = avail
        if total > 0:
            out["memory"]["used_percent"] = round((total - avail) * 100.0 / total, 1)
    except Exception:
        pass

    # --- disk -------------------------------------------------------------
    try:
        u = shutil.disk_usage("/")
        out["disk"]["used_percent"] = round(u.used * 100.0 / u.total, 1)
        out["disk"]["path"] = "/"
    except Exception:
        pass

    # --- top 5 processes by CPU ------------------------------------------
    try:
        ps = _cmd("ps", "-eo", "pid,pcpu,pmem,comm", "--sort=-pcpu", "--no-headers").splitlines()[:5]
        for line in ps:
            parts = line.split(None, 3)
            if len(parts) >= 4:
                out["top_processes"].append({
                    "pid": int(parts[0]),
                    "cpu_percent": float(parts[1]),
                    "mem_percent": float(parts[2]),
                    "name": parts[3][:40],
                })
    except Exception:
        pass

    # --- failed systemd units --------------------------------------------
    try:
        units = _cmd("systemctl", "--failed", "--no-legend", "--no-pager").splitlines()
        for line in units[:20]:
            parts = line.split()
            if len(parts) >= 1:
                out["failed_units"].append(parts[0])
    except Exception:
        # No systemd or no permission — leave empty
        pass

    sys.stdout.write(json.dumps(out, separators=(",", ":")))
'''


# --- Dataclasses -------------------------------------------------------------


@dataclass
class HostSnapshot:
    """Health snapshot collected from one remote EC2 instance."""

    instance_id: str
    available: bool
    reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


# --- Exceptions --------------------------------------------------------------


class SsmError(Exception):
    """Raised when SSM operation fails (no credentials, throttling, etc.)."""


# --- Connector ---------------------------------------------------------------


class AwsSsmConnector:
    """Collects health snapshots from EC2 instances via SSM SendCommand.

    Usage:
        connector = AwsSsmConnector()              # reads AWS_* env / ~/.aws
        ids = connector.list_instances(tags={"env": ["prod"], "team": ["infra"]})
        snapshots = connector.collect_all(ids)
    """

    # SSM poll settings — be patient: SSM can take 30s+ to schedule + run
    POLL_INTERVAL_SEC = 2.0
    POLL_TIMEOUT_SEC = 90.0
    MAX_INFLIGHT = 5  # stay well under SSM 100-command quota

    def __init__(
        self,
        region: str | None = None,
        ssm_client: Any = None,
        ec2_client: Any = None,
    ):
        """Create connector. Region defaults to AWS_REGION / ~/.aws / boto3 default."""
        try:
            import boto3  # noqa: F401  (we may need this if no client injected)
        except ImportError as e:
            raise SsmError("boto3 not installed — run: pip install boto3") from e

        self._region = region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        if not self._region:
            # boto3 will pick up region from ~/.aws/config or env on its own
            self._region = None  # let boto3 default

        self._ssm = ssm_client
        self._ec2 = ec2_client
        self._owns_clients = ssm_client is None  # if we built them, we close them

    def _client(self, service: str):
        """Lazy boto3 client creation."""
        import boto3

        kwargs: dict[str, Any] = {}
        if self._region:
            kwargs["region_name"] = self._region
        return boto3.client(service, **kwargs)

    @property
    def ssm(self):
        if self._ssm is None:
            self._ssm = self._client("ssm")
        return self._ssm

    @property
    def ec2(self):
        if self._ec2 is None:
            self._ec2 = self._client("ec2")
        return self._ec2

    # --- Public API --------------------------------------------------------

    def list_instances(
        self,
        tags: dict[str, list[str]] | None = None,
        instance_ids: list[str] | None = None,
    ) -> list[str]:
        """Return instance IDs matching tag filters (AND across keys, OR within).

        Args:
            tags: dict like {"env": ["prod", "staging"], "team": ["infra"]}
                  Matched as: instance has (env=prod OR env=staging) AND team=infra
            instance_ids: explicit list overrides tags (skips EC2 API call)
        """
        if instance_ids:
            return list(instance_ids)

        filters: list[dict[str, Any]] = [
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
        if tags:
            for k, values in tags.items():
                filters.append({"Name": f"tag:{k}", "Values": list(values)})

        try:
            paginator = self.ec2.get_paginator("describe_instances")
            ids: list[str] = []
            for page in paginator.paginate(Filters=filters):
                for reservation in page.get("Reservations", []):
                    for inst in reservation.get("Instances", []):
                        iid = inst.get("InstanceId")
                        if iid:
                            ids.append(iid)
            return ids
        except Exception as e:
            raise SsmError(f"describe_instances failed: {e}") from e

    def collect_one(self, instance_id: str) -> HostSnapshot:
        """Collect a snapshot from a single instance. Blocks until done."""
        start = time.time()
        try:
            cmd_id = self._send_collect_command(instance_id)
            output = self._wait_for_output(instance_id, cmd_id)
            data = json.loads(output)
            return HostSnapshot(
                instance_id=instance_id,
                available=True,
                data=data,
                duration_ms=int((time.time() - start) * 1000),
            )
        except json.JSONDecodeError as e:
            return HostSnapshot(
                instance_id=instance_id,
                available=False,
                reason=f"invalid JSON from remote: {e}",
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return HostSnapshot(
                instance_id=instance_id,
                available=False,
                reason=str(e),
                duration_ms=int((time.time() - start) * 1000),
            )

    def collect_all(self, instance_ids: list[str]) -> list[HostSnapshot]:
        """Collect snapshots from many instances in parallel (bounded)."""
        if not instance_ids:
            return []
        results: list[HostSnapshot] = []
        with ThreadPoolExecutor(max_workers=self.MAX_INFLIGHT) as pool:
            futures = {
                pool.submit(self.collect_one, iid): iid for iid in instance_ids
            }
            for fut in as_completed(futures):
                results.append(fut.result())
        return results

    # --- Internal: SSM plumbing -------------------------------------------

    def _send_collect_command(self, instance_id: str) -> str:
        """Ship the collect script to the instance, return SSM CommandId."""
        try:
            resp = self.ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": [f"python3 -c '{REMOTE_COLLECT_SCRIPT}'"]},
                TimeoutSeconds=60,
                Comment="iPracticom sweeper — read-only health snapshot",
            )
        except Exception as e:
            raise SsmError(f"send_command failed for {instance_id}: {e}") from e

        commands = resp.get("Command", {}).get("CommandId")
        if not commands:
            raise SsmError(f"send_command returned no CommandId: {resp!r}")
        return commands

    def _wait_for_output(self, instance_id: str, cmd_id: str) -> str:
        """Poll GetCommandInvocation until the command finishes. Returns stdout."""
        deadline = time.time() + self.POLL_TIMEOUT_SEC
        last_status = None
        while time.time() < deadline:
            try:
                inv = self.ssm.get_command_invocation(
                    CommandId=cmd_id, InstanceId=instance_id
                )
            except Exception as e:
                # GetCommandInvocation may not be available instantly
                last_status = f"poll_error: {e}"
                time.sleep(self.POLL_INTERVAL_SEC)
                continue

            status = inv.get("Status", "")
            last_status = status
            if status in ("Success", "Failed", "Cancelled", "TimedOut"):
                if status != "Success":
                    err = inv.get("StandardErrorContent", "").strip() or status
                    raise SsmError(
                        f"command {status} on {instance_id}: {err[:300]}"
                    )
                stdout = inv.get("StandardOutputContent", "").strip()
                if not stdout:
                    raise SsmError(f"empty stdout from {instance_id}")
                return stdout
            time.sleep(self.POLL_INTERVAL_SEC)
        raise SsmError(
            f"timed out waiting for {instance_id} (cmd={cmd_id}, last_status={last_status})"
        )
