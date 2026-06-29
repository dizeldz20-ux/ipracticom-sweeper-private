"""Async HTTP client for the iPracticom Sweeper agent_api.

Thin wrapper around httpx: attaches bearer token, parses JSON, and
turns non-2xx responses into `AgentAPIError`. The bot's handlers
catch this and turn it into a friendly "agent unavailable" message.

Endpoints used (v0.4.2):
  GET  /healthz
  GET  /api/snapshot
  GET  /api/history            list available metrics + hosts
  GET  /api/history/{metric}   time-series for one metric
  GET  /api/predictions
  GET  /api/evidence/export
  GET  /api/approvals          pending repair proposals
  POST /api/approvals/{id}/approve   execute the repair now
  POST /api/approvals/{id}/reject    archive as rejected
  GET  /api/fleet              host list (connectors + heartbeat)
  GET  /api/fleet/{host}       one host's details
  POST /api/run                trigger a sweep
"""
from __future__ import annotations

from typing import Any

import httpx


class AgentAPIError(RuntimeError):
    """Raised when the agent_api returns non-2xx or times out."""

    def __init__(self, status_code: int | None, message: str):
        super().__init__(message)
        self.status_code = status_code


class AgentClient:
    """Async client for the iPracticom Sweeper agent_api."""

    def __init__(
        self,
        base_url: str,
        token: str = "",
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    async def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            resp = await self._http.get(self._url(path), params=params, headers=self._headers())
        except httpx.HTTPError as e:
            raise AgentAPIError(None, f"agent_api request failed: {e}") from e
        if not (200 <= resp.status_code < 300):
            raise AgentAPIError(resp.status_code, f"agent_api {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except Exception as e:
            raise AgentAPIError(resp.status_code, f"agent_api returned invalid JSON: {e}") from e

    async def _post(self, path: str, json_body: dict | None = None) -> Any:
        try:
            resp = await self._http.post(
                self._url(path),
                json=json_body or {},
                headers=self._headers(),
            )
        except httpx.HTTPError as e:
            raise AgentAPIError(None, f"agent_api request failed: {e}") from e
        if not (200 <= resp.status_code < 300):
            raise AgentAPIError(resp.status_code, f"agent_api {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except Exception as e:
            raise AgentAPIError(resp.status_code, f"agent_api returned invalid JSON: {e}") from e

    async def healthz(self) -> bool:
        """Return True if /healthz returns 200."""
        try:
            resp = await self._http.get(self._url("/healthz"), headers=self._headers())
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def get_snapshot(self) -> dict:
        """GET /api/snapshot — current system snapshot."""
        return await self._get("/api/snapshot")

    async def get_history_catalog(self) -> dict:
        """GET /api/history — list available metrics + hosts + sample counts."""
        return await self._get("/api/history")

    async def get_history(self, metric: str, hours: int = 24, host: str | None = None) -> dict:
        """GET /api/history/{metric}?hours=...&host=... — historical samples.

        v0.4.2 returns a richer envelope: {"host", "metric", "samples", "count", "hours"}.
        Older callers expected a bare list; the wrapper unpacks both shapes.
        """
        params: dict = {"hours": hours}
        if host:
            params["host"] = host
        out = await self._get(f"/api/history/{metric}", params=params)
        # Backwards-compat: if the server returned a bare list, return it.
        if isinstance(out, list):
            return {"metric": metric, "samples": out, "count": len(out), "hours": hours}
        if isinstance(out, dict) and "samples" in out:
            return out
        # Unknown shape — wrap defensively.
        return {"metric": metric, "samples": out or [], "count": 0, "hours": hours}

    async def get_predictions(self) -> dict:
        """GET /api/predictions — predicted DEFCON + confidence."""
        return await self._get("/api/predictions")

    async def export_evidence(self, hours: int = 24) -> dict:
        """GET /api/evidence/export?hours=... — signed evidence bundle."""
        return await self._get("/api/evidence/export", params={"hours": hours})

    async def list_approvals(self) -> dict:
        """GET /api/approvals — pending repair proposals awaiting decision."""
        return await self._get("/api/approvals")

    async def approve_repair(self, proposal_id: str) -> dict:
        """POST /api/approvals/{id}/approve — execute the repair now, return result."""
        return await self._post(f"/api/approvals/{proposal_id}/approve")

    async def reject_repair(self, proposal_id: str) -> dict:
        """POST /api/approvals/{id}/reject — archive as rejected."""
        return await self._post(f"/api/approvals/{proposal_id}/reject")

    async def list_fleet(self) -> dict:
        """GET /api/fleet — fleet summary (hosts + heartbeat + connectors)."""
        return await self._get("/api/fleet")

    async def get_fleet_host(self, host: str) -> dict:
        """GET /api/fleet/{host} — one host's details."""
        return await self._get(f"/api/fleet/{host}")

    async def trigger_run(self) -> dict:
        """POST /api/run — trigger a fresh sweep, return the new snapshot."""
        return await self._post("/api/run")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()