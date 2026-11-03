"""Argo CD through its REST API (read-only).

It plugs into the same interface as Prometheus for alert rules. An `expr` names a metric, optionally narrowed:

    out_of_sync project=payments
    degraded app=api-*

and the value is per application. Only applications that are in trouble are returned, so an alert resolves the moment
the application is healthy and in sync again (or is deleted). Use the rule's `for` to say how long it may stay that way:
"out_of_sync for 15 minutes" is the usual way to catch a stuck rollout.

The same data feeds the Argo CD page and puts syncs on the incident page as deploy markers.
"""
from __future__ import annotations

import fnmatch
import ssl
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .config import ArgoCDCfg, ConfigError
from .prom import PromQueryError, PromUnavailable

METRICS = {
    "out_of_sync": "1 for an application whose live state differs from Git",
    "degraded": "1 for an application that is Degraded or Missing (something it deployed is broken or absent)",
    "progressing": "1 for an application that is still Progressing (use `for` to catch a rollout that never finishes)",
    "sync_failed": "1 for an application whose last sync failed or errored, or that Argo is retrying after a failure",
    "sync_error": "1 for an application with an error condition (cannot reach the repository, manifests do not render...)",
}
FAILED_PHASES = {"Failed", "Error"}


def sync_failing(v: dict[str, Any]) -> bool:
    """A sync that failed, or one that Argo is retrying after a failure (its phase stays Running, with a retry count)."""
    return v["op_phase"] in FAILED_PHASES or (v["op_phase"] == "Running" and v["retries"] > 0)


class ArgoCDError(PromUnavailable):
    """Argo CD could not be reached, refused the token, or answered something unexpected."""


def _epoch(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def app_view(a: dict[str, Any]) -> dict[str, Any]:
    meta, spec, st = a.get("metadata") or {}, a.get("spec") or {}, a.get("status") or {}
    sync, health, op = st.get("sync") or {}, st.get("health") or {}, st.get("operationState") or {}
    src = spec.get("source") or next(iter(spec.get("sources") or []), {}) or {}
    dest = spec.get("destination") or {}
    history = [{"id": h.get("id"), "revision": (h.get("revision") or "")[:7], "deployed_at": _epoch(h.get("deployedAt"))}
               for h in (st.get("history") or []) if isinstance(h, dict)]
    errors = [{"type": c.get("type", ""), "message": (c.get("message") or "")[:300]}
              for c in (st.get("conditions") or []) if str(c.get("type", "")).endswith("Error")]
    finished = _epoch(op.get("finishedAt"))
    last_deploy = max([h["deployed_at"] or 0 for h in history] or [0])
    return {
        "name": meta.get("name", ""), "project": spec.get("project", "default"),
        "namespace": dest.get("namespace", ""), "cluster": dest.get("name") or dest.get("server", ""),
        "sync": sync.get("status", "Unknown"), "health": health.get("status", "Unknown"),
        "health_message": (health.get("message") or "")[:300], "revision": (sync.get("revision") or "")[:7],
        "repo": src.get("repoURL", ""), "path": src.get("path") or src.get("chart", ""), "target": src.get("targetRevision", ""),
        "op_phase": op.get("phase", ""), "op_message": (op.get("message") or "")[:300], "retries": int(op.get("retryCount") or 0),
        "last_sync_at": finished or last_deploy or None, "errors": errors,
        "auto_sync": bool((spec.get("syncPolicy") or {}).get("automated")), "history": history[-10:],
    }


def parse(expr: str) -> tuple[str, dict[str, str]]:
    parts = (expr or "").split()
    if not parts or parts[0] not in METRICS:
        raise PromQueryError("write a metric (" + ", ".join(METRICS) + "), optionally followed by app=<glob>, project=<name> and namespace=<name>")
    filters: dict[str, str] = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        if k not in ("app", "project", "namespace") or not v:
            raise PromQueryError(f"unknown filter {p!r}: use app=<glob>, project=<glob> or namespace=<glob>")
        filters[k] = v
    return parts[0], filters


def trouble(metric: str, v: dict[str, Any]) -> bool:
    return {"out_of_sync": v["sync"] == "OutOfSync", "degraded": v["health"] in ("Degraded", "Missing"),
            "progressing": v["health"] == "Progressing", "sync_failed": sync_failing(v),
            "sync_error": bool(v["errors"])}[metric]


class ArgoCD:
    def __init__(self, cfg: ArgoCDCfg, timeout: float = 10.0, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self.base = cfg.url
        if client is None:
            if cfg.ca_file and not Path(cfg.ca_file).is_file():
                raise ConfigError(f"argocd.ca_file not found: {cfg.ca_file}")
            verify: Any = False if not cfg.verify_tls else (ssl.create_default_context(cafile=cfg.ca_file) if cfg.ca_file else True)
            client = httpx.AsyncClient(timeout=timeout, verify=verify)
        self._client = client
        self._cache: tuple[float, list[dict[str, Any]]] | None = None
        self.last_error: str | None = None

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            r = await self._client.get(self.base + path, params=params, headers={"Authorization": f"Bearer {self.cfg.token}"})
        except httpx.ConnectError as e:
            msg = "Argo CD could not be reached"
            if "CERTIFICATE" in str(e).upper() or "SSL" in str(e).upper():
                msg = "Argo CD's certificate is not trusted: set argocd.ca_file (or verify_tls: false for a lab)"
            self.last_error = msg
            raise ArgoCDError(msg) from e
        except httpx.HTTPError as e:
            self.last_error = f"Argo CD could not be reached ({type(e).__name__})"
            raise ArgoCDError(self.last_error) from e
        if r.status_code == 401:
            self.last_error = "Argo CD refused the token (HTTP 401): create one with `argocd account generate-token`"
            raise ArgoCDError(self.last_error)
        if r.status_code == 403:
            self.last_error = "Argo CD says this token may not read applications (HTTP 403)"
            raise ArgoCDError(self.last_error)
        if r.status_code == 404:
            self.last_error = "Argo CD answered 404: check argocd.url"
            raise ArgoCDError(self.last_error)
        if r.status_code >= 400:
            self.last_error = f"Argo CD returned HTTP {r.status_code}"
            raise ArgoCDError(self.last_error)
        try:
            data = r.json()
        except ValueError as e:
            self.last_error = "that address did not answer like Argo CD's API (wrong argocd.url?)"
            raise ArgoCDError(self.last_error) from e
        self.last_error = None
        return data

    async def apps(self) -> list[dict[str, Any]]:
        if self._cache and time.time() - self._cache[0] < 10:
            return self._cache[1]
        data = await self._get("/api/v1/applications", {"projects": self.cfg.projects} if self.cfg.projects else None)
        if not isinstance(data, dict):
            self.last_error = "Argo CD returned an unexpected answer"
            raise ArgoCDError(self.last_error)
        views = [app_view(a) for a in (data.get("items") or []) if isinstance(a, dict)]    # `items` is null when there are none
        self._cache = (time.time(), views)
        return views

    async def deploys(self, limit: int = 60) -> list[dict[str, Any]]:
        """Syncs as deploy markers, newest first: every revision in an application's history, and failed operations."""
        out = []
        for a in await self.apps():
            for h in a["history"]:
                if h["deployed_at"]:
                    out.append({"id": f"{a['name']}:{h['id']}", "name": a["name"], "sha": h["revision"], "finished_at": h["deployed_at"],
                                "conclusion": "success", "status": "completed", "source": "argocd"})
            if sync_failing(a) and a["last_sync_at"]:
                out.append({"id": f"{a['name']}:failed", "name": a["name"], "sha": a["revision"], "finished_at": a["last_sync_at"],
                            "conclusion": "failure", "status": "completed", "source": "argocd"})
        return sorted(out, key=lambda d: -d["finished_at"])[:limit]

    async def instant(self, expr: str, at: float | None = None) -> list[dict[str, Any]]:
        metric, f = parse(expr)
        match = lambda v, key: key not in f or fnmatch.fnmatchcase(v, f[key])  # noqa: E731
        return [{"labels": {"name": a["name"], "project": a["project"]}, "value": 1.0}
                for a in await self.apps()
                if trouble(metric, a) and match(a["name"], "app") and match(a["project"], "project") and match(a["namespace"], "namespace")]

    async def range(self, *_: Any, **__: Any) -> list[dict[str, Any]]:
        raise PromQueryError("Argo CD has no time series")

    async def healthy(self) -> bool:
        try:
            await self.apps()
            return True
        except ArgoCDError:
            return False
