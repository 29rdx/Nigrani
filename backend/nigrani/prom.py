"""Thin async Prometheus HTTP API client."""
from __future__ import annotations

import math
import time
from typing import Any

import httpx


class PromError(Exception):
    pass


class PromUnavailable(PromError):
    """Prometheus could not be reached / returned a server error."""


class PromQueryError(PromError):
    """Prometheus rejected the query (bad PromQL, timeout in evaluation...)."""


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


class Prom:
    def __init__(self, base_url: str, timeout: float = 10.0, client: httpx.AsyncClient | None = None):
        self.base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self.last_error: str | None = None
        self.last_ok: float | None = None

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            r = await self._client.get(self.base + path, params=params)
        except httpx.HTTPError as e:
            self.last_error = f"{type(e).__name__}: {e}"
            raise PromUnavailable(self.last_error) from e
        try:
            body = r.json()
        except ValueError:
            body = None
        if r.status_code in (400, 422) and isinstance(body, dict):
            raise PromQueryError(body.get("error", f"HTTP {r.status_code}"))
        if r.status_code >= 400 or not isinstance(body, dict):
            self.last_error = f"HTTP {r.status_code}"
            raise PromUnavailable(self.last_error)
        if body.get("status") != "success":
            raise PromQueryError(body.get("error", "query failed"))
        self.last_error = None
        self.last_ok = time.time()
        return body["data"]

    async def instant(self, query: str, at: float | None = None) -> list[dict[str, Any]]:
        """-> [{"labels": {...}, "value": float|None}]  (evaluated at `at`, default now)"""
        params: dict[str, Any] = {"query": query}
        if at is not None:
            params["time"] = at
        data = await self._get("/api/v1/query", params)
        out = []
        for r in data.get("result", []):
            if "value" in r:
                out.append({"labels": r["metric"], "value": _num(r["value"][1])})
        return out

    async def range(self, query: str, start: float, end: float, step: float) -> list[dict[str, Any]]:
        """-> [{"labels": {...}, "points": [[ts, value|None], ...]}]"""
        data = await self._get(
            "/api/v1/query_range", {"query": query, "start": start, "end": end, "step": step}
        )
        return [
            {"labels": r["metric"], "points": [[float(t), _num(v)] for t, v in r["values"]]}
            for r in data.get("result", [])
        ]

    async def has_metric(self, name: str) -> bool:
        try:
            r = await self.instant(f'count({{__name__="{name}"}})')
        except PromError:
            return False
        return bool(r) and (r[0]["value"] or 0) > 0

    async def metric_names(self) -> list[str]:
        data = await self._get("/api/v1/label/__name__/values", {})
        return [n for n in data if isinstance(n, str)]

    async def healthy(self) -> bool:
        try:
            await self.instant("vector(1)")
            return True
        except PromError:
            return False


def series_key(labels: dict[str, str]) -> str:
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()) if k != "__name__")


_DISPLAY = ("name", "container", "mountpoint", "queue_name", "view", "instance", "job", "device")


def series_label(labels: dict[str, str]) -> str:
    for k in _DISPLAY:
        if labels.get(k):
            return labels[k]
    vals = [v for k, v in sorted(labels.items()) if k != "__name__"]
    return " ".join(vals)
