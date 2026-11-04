"""New Relic (NerdGraph GraphQL API) read-only data source.

It plugs into the same interface as Prometheus for alert rules: an `expr` is an NRQL query that returns numbers
(`SELECT average(cpuPercent) FROM SystemSample FACET hostname`) and every resulting facet is one alert.
"""
from __future__ import annotations

import re
import time
from typing import Any

import httpx

from .config import NewRelicCfg
from .prom import PromQueryError, PromUnavailable

NERDGRAPH_US = "https://api.newrelic.com/graphql"
NERDGRAPH_EU = "https://api.eu.newrelic.com/graphql"


class NewRelicError(PromUnavailable):
    """New Relic could not be reached, refused the API key, or returned an unexpected answer."""


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def extract_facet_keys(query: str) -> list[str]:
    """Extract facet attribute names from an NRQL query string."""
    m = re.search(r"\bFACET\s+([a-zA-Z0-9_,\s]+?)(?:\s+(?:LIMIT|SINCE|UNTIL|TIMESERIES|COMPARE|WITH|ORDER)\b|$)", query, re.IGNORECASE)
    if not m:
        return []
    return [k.strip() for k in m.group(1).split(",") if k.strip()]


def labels_of_row(row: dict[str, Any], facet_keys: list[str] | None = None) -> tuple[dict[str, str], float | None]:
    """Extracts facet labels and the numeric metric value from a single NerdGraph NRQL result row."""
    labels: dict[str, str] = {}
    val: float | None = None

    if "facet" in row:
        f = row["facet"]
        keys = facet_keys or []
        if isinstance(f, list):
            for idx, item in enumerate(f):
                key = keys[idx] if idx < len(keys) else f"facet_{idx}"
                labels[key] = str(item)
        elif isinstance(f, dict):
            for k, v in f.items():
                labels[str(k)] = str(v)
        else:
            key = keys[0] if len(keys) == 1 else "facet"
            labels[key] = str(f)

    for k, v in row.items():
        if k in ("facet", "beginTimeSeconds", "endTimeSeconds", "timestamp"):
            continue
        num_v = _num(v)
        if num_v is not None and val is None:
            val = num_v
        elif isinstance(v, (str, bool)) and "facet" not in row:
            labels[k] = str(v)

    if not labels:
        labels = {"metric": "value"}

    return labels, val


class NewRelic:
    def __init__(self, cfg: NewRelicCfg, timeout: float = 10.0, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self.last_error: str | None = None

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def api_url(self) -> str:
        if self.cfg.url:
            return self.cfg.url
        return NERDGRAPH_EU if str(self.cfg.region).lower() == "eu" else NERDGRAPH_US

    async def _post(self, nrql: str) -> list[dict[str, Any]]:
        query = """
        query($accountId: Int!, $nrql: Nrql!) {
          actor {
            account(id: $accountId) {
              nrql(query: $nrql) {
                results
              }
            }
          }
        }
        """
        payload = {
            "query": query,
            "variables": {
                "accountId": int(self.cfg.account_id),
                "nrql": nrql
            }
        }
        headers = {
            "API-Key": self.cfg.api_key,
            "Content-Type": "application/json"
        }
        try:
            r = await self._client.post(self.api_url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            self.last_error = f"New Relic could not be reached ({type(e).__name__})"
            raise NewRelicError(self.last_error) from e

        if r.status_code in (401, 403):
            self.last_error = f"New Relic refused the API key (HTTP {r.status_code}); check newrelic.api_key and account permissions"
            raise NewRelicError(self.last_error)
        if r.status_code == 429:
            self.last_error = "New Relic is rate limiting these keys; try again shortly"
            raise NewRelicError(self.last_error)
        if r.status_code >= 500:
            self.last_error = f"New Relic returned HTTP {r.status_code}"
            raise NewRelicError(self.last_error)

        try:
            body = r.json()
        except ValueError:
            self.last_error = "New Relic returned something that is not JSON (wrong region or URL?)"
            raise NewRelicError(self.last_error)

        if not isinstance(body, dict):
            self.last_error = "New Relic returned an unexpected answer"
            raise NewRelicError(self.last_error)

        if "errors" in body and body["errors"]:
            err_msg = "; ".join([str(e.get("message", "GraphQL Error")) for e in body["errors"] if isinstance(e, dict)])
            raise PromQueryError(f"New Relic rejected the query: {err_msg}")

        actor = body.get("data", {}).get("actor")
        if not actor or not actor.get("account"):
            self.last_error = f"New Relic account {self.cfg.account_id} not found or inaccessible"
            raise NewRelicError(self.last_error)

        nrql_data = actor["account"].get("nrql", {})
        results = nrql_data.get("results")
        if results is None or not isinstance(results, list):
            self.last_error = "New Relic returned an unexpected payload structure"
            raise NewRelicError(self.last_error)

        self.last_error = None
        return results

    async def instant(self, expr: str, at: float | None = None) -> list[dict[str, Any]]:
        facet_keys = extract_facet_keys(expr)
        results = await self._post(expr)
        series_map: dict[str, dict[str, Any]] = {}
        for row in results:
            if not isinstance(row, dict):
                continue
            labels, val = labels_of_row(row, facet_keys)
            if val is None:
                continue
            key = str(sorted(labels.items()))
            series_map[key] = {"labels": labels, "value": val}

        return list(series_map.values())

    async def range(self, query: str, start: float, end: float, step: float = 0) -> list[dict[str, Any]]:
        facet_keys = extract_facet_keys(query)
        time_clause = f" SINCE {int(start)} UNTIL {int(end)}"
        nrql = query
        if "SINCE" not in query.upper() and "UNTIL" not in query.upper():
            nrql += time_clause
        if "TIMESERIES" not in query.upper():
            nrql += " TIMESERIES"
            if step > 0:
                nrql += f" {int(step)} seconds"

        results = await self._post(nrql)
        series_map: dict[str, dict[str, Any]] = {}
        for row in results:
            if not isinstance(row, dict):
                continue
            labels, val = labels_of_row(row, facet_keys)
            ts = row.get("endTimeSeconds") or row.get("beginTimeSeconds") or row.get("timestamp")
            if ts is not None:
                ts_sec = float(ts) if float(ts) < 1e11 else float(ts) / 1000.0
            else:
                ts_sec = time.time()

            key = str(sorted(labels.items()))
            if key not in series_map:
                series_map[key] = {"labels": labels, "points": []}
            series_map[key]["points"].append([ts_sec, val])

        return list(series_map.values())

    async def healthy(self) -> bool:
        query = """
        query($accountId: Int!) {
          actor {
            account(id: $accountId) {
              id
            }
          }
        }
        """
        payload = {
            "query": query,
            "variables": {
                "accountId": int(self.cfg.account_id)
            }
        }
        headers = {
            "API-Key": self.cfg.api_key,
            "Content-Type": "application/json"
        }
        try:
            r = await self._client.post(self.api_url, json=payload, headers=headers)
            if r.status_code != 200:
                return False
            data = r.json().get("data", {}).get("actor", {}).get("account")
            return data is not None and data.get("id") is not None
        except Exception:
            return False
