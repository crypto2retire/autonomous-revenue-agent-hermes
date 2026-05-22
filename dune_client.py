"""Dune Analytics API client for on-chain data and query execution."""

from typing import Any, Dict, List, Optional

import httpx

from config import get_settings

settings = get_settings()

DUNE_BASE = "https://api.dune.com/api/v1"


class DuneClient:
    """Async Dune Analytics API client."""

    def __init__(self):
        self.api_key = settings.dune_api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Dune-API-Key"] = self.api_key.get_secret_value()
        return headers

    async def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a GET request to Dune API."""
        client = await self._get_client()
        url = f"{DUNE_BASE}{endpoint}"
        resp = await client.get(url, params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def _post(self, endpoint: str, json: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a POST request to Dune API."""
        client = await self._get_client()
        url = f"{DUNE_BASE}{endpoint}"
        resp = await client.post(url, json=json, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    # ── Query Execution ────────────────────────────────────────────────

    async def execute_query(self, query_id: int, parameters: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Execute a query by ID and return the execution ID."""
        payload = {}
        if parameters:
            payload["query_parameters"] = parameters
        return await self._post(f"/query/{query_id}/execute", payload)

    async def get_execution_status(self, execution_id: str) -> Dict[str, Any]:
        """Check the status of a query execution."""
        return await self._get(f"/execution/{execution_id}/status")

    async def get_execution_results(self, execution_id: str, limit: int = 1000) -> Dict[str, Any]:
        """Get results from a completed query execution."""
        return await self._get(f"/execution/{execution_id}/results", {"limit": limit})

    async def execute_and_wait(
        self,
        query_id: int,
        parameters: Optional[List[Dict]] = None,
        poll_interval: float = 2.0,
        max_wait: float = 120.0,
    ) -> Dict[str, Any]:
        """Execute a query and poll until complete."""
        import asyncio

        exec_resp = await self.execute_query(query_id, parameters)
        execution_id = exec_resp["execution_id"]

        waited = 0.0
        while waited < max_wait:
            status = await self.get_execution_status(execution_id)
            state = status.get("state", "")
            if state == "QUERY_STATE_COMPLETED":
                return await self.get_execution_results(execution_id)
            if state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED"):
                raise RuntimeError(f"Query failed with state: {state}")
            await asyncio.sleep(poll_interval)
            waited += poll_interval

        raise TimeoutError(f"Query execution timed out after {max_wait}s")

    # ── Tables ─────────────────────────────────────────────────────────

    async def get_tables(self, namespace: str = "dune") -> Dict[str, Any]:
        """List available tables."""
        return await self._get("/tables", {"namespace": namespace})

    # ── Teams & Credits ────────────────────────────────────────────────

    async def get_team_usage(self) -> Dict[str, Any]:
        """Get team credit usage."""
        return await self._get("/team/credit_usage")

    # ── Cleanup ────────────────────────────────────────────────────────

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Singleton
_dune_client: Optional[DuneClient] = None


def get_dune() -> DuneClient:
    global _dune_client
    if _dune_client is None:
        _dune_client = DuneClient()
    return _dune_client
