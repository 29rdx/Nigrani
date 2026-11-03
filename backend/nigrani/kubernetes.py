"""Kubernetes through its REST API (read-only).

It plugs into the same interface as Prometheus for alert rules. An `expr` names a metric, optionally narrowed:

    crashloop namespace=prod
    restarts_1h pod=api-*

and the value is per pod / node / deployment. Only series that are in trouble are returned, so an alert resolves the
moment the pod recovers or goes away.
"""
from __future__ import annotations

import fnmatch
import os
import ssl
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from . import config as config_mod
from .config import ConfigError, KubernetesCfg
from .prom import PromError, PromQueryError, PromUnavailable

PAGE = 500
BAD_WAITING = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError", "InvalidImageName",
               "CreateContainerError", "RunContainerError"}
METRICS = {
    "crashloop": "1 for a pod whose container is crash-looping or cannot start (CrashLoopBackOff, ImagePullBackOff...)",
    "restarts_1h": "container restarts of a pod whose last restart was within the hour",
    "not_ready_minutes": "minutes a pod has been Pending or Running without being Ready",
    "pod_failed": "1 for a pod in phase Failed (for example evicted)",
    "node_not_ready": "1 for a node that is not Ready",
    "deployment_unavailable": "replicas a Deployment wants but does not have available",
}


class KubernetesError(PromUnavailable):
    """The Kubernetes API could not be reached, refused the token, or answered something unexpected."""


def _epoch(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def pod_view(p: dict[str, Any], now: float) -> dict[str, Any]:
    meta, spec, st = p.get("metadata", {}), p.get("spec", {}), p.get("status", {})
    statuses = st.get("containerStatuses", []) + st.get("initContainerStatuses", [])
    waiting = next((s["state"]["waiting"].get("reason", "") for s in statuses
                    if "waiting" in s.get("state", {}) and s["state"]["waiting"].get("reason") in BAD_WAITING), "")
    any_waiting = next((s["state"]["waiting"].get("reason", "") for s in statuses if "waiting" in s.get("state", {})), "")
    terminated = next((s["state"]["terminated"].get("reason", "") for s in st.get("containerStatuses", [])
                       if "terminated" in s.get("state", {}) and s["state"]["terminated"].get("reason") not in ("Completed", None)), "")
    restarts = sum(int(s.get("restartCount", 0)) for s in st.get("containerStatuses", []))
    last_end = max([_epoch(s.get("lastState", {}).get("terminated", {}).get("finishedAt")) or 0
                    for s in st.get("containerStatuses", [])] or [0])
    recent = bool(last_end) and now - last_end < 3600
    phase = st.get("phase", "Unknown")
    ready = next((c.get("status") == "True" for c in st.get("conditions", []) if c.get("type") == "Ready"), False)
    since = _epoch(next((c.get("lastTransitionTime") for c in st.get("conditions", []) if c.get("type") == "Ready"), None)) \
        or _epoch(meta.get("creationTimestamp")) or now
    status = ("Terminating" if meta.get("deletionTimestamp") else waiting or any_waiting or terminated
              or st.get("reason") or phase)
    crash = bool(waiting) or (phase == "Running" and restarts >= 3 and last_end and now - last_end < 300)
    return {
        "namespace": meta.get("namespace", ""), "name": meta.get("name", ""), "node": spec.get("nodeName", ""),
        "phase": phase, "status": status, "ready": ready and phase == "Running", "restarts": restarts,
        "restarts_1h": restarts if recent else 0, "crashloop": crash,
        "not_ready_minutes": 0.0 if (phase in ("Succeeded", "Failed") or ready) else round((now - since) / 60, 1),
        "age": now - (_epoch(meta.get("creationTimestamp")) or now),
        "containers": len(spec.get("containers", [])),
    }


def node_view(n: dict[str, Any]) -> dict[str, Any]:
    conds = {c.get("type"): c.get("status") for c in n.get("status", {}).get("conditions", [])}
    info = n.get("status", {}).get("nodeInfo", {})
    pressure = [t for t in ("MemoryPressure", "DiskPressure", "PIDPressure") if conds.get(t) == "True"]
    return {"name": n.get("metadata", {}).get("name", ""), "ready": conds.get("Ready") == "True", "pressure": pressure,
            "version": info.get("kubeletVersion", ""), "os": info.get("osImage", "")}


def deployment_view(d: dict[str, Any]) -> dict[str, Any]:
    st = d.get("status", {})
    want = int(d.get("spec", {}).get("replicas", 1) or 0)
    return {"namespace": d["metadata"].get("namespace", ""), "name": d["metadata"].get("name", ""), "desired": want,
            "available": int(st.get("availableReplicas", 0) or 0), "ready": int(st.get("readyReplicas", 0) or 0)}


def parse(expr: str) -> tuple[str, dict[str, str]]:
    parts = (expr or "").split()
    if not parts or parts[0] not in METRICS:
        raise PromQueryError("write a metric (" + ", ".join(METRICS) + "), optionally followed by namespace=<name> and pod=<glob>")
    filters: dict[str, str] = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        if k not in ("namespace", "pod", "node", "deployment") or not v:
            raise PromQueryError(f"unknown filter {p!r}: use namespace=<name>, pod=<glob>, node=<glob> or deployment=<glob>")
        filters[k] = v
    return parts[0], filters


class Kubernetes:
    def __init__(self, cfg: KubernetesCfg, timeout: float = 10.0, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        in_cluster = not cfg.url and config_mod.in_cluster()
        self.base = cfg.url or (f"https://{os.environ['KUBERNETES_SERVICE_HOST']}:{os.environ.get('KUBERNETES_SERVICE_PORT', '443')}"
                                if in_cluster else "")
        ca = cfg.ca_file
        if ca and not Path(ca).is_file():
            raise ConfigError(f"kubernetes.ca_file not found: {ca}")
        if not ca and in_cluster and (config_mod.K8S_SA_DIR / "ca.crt").is_file():
            ca = str(config_mod.K8S_SA_DIR / "ca.crt")
        if client is None:
            verify: Any = False if not cfg.verify_tls else (ssl.create_default_context(cafile=ca) if ca else True)
            client = httpx.AsyncClient(timeout=timeout, verify=verify)
        self._client = client
        self._in_cluster = in_cluster
        self.last_error: str | None = None

    async def close(self) -> None:
        await self._client.aclose()

    def _token(self) -> str:
        if self.cfg.token:
            return self.cfg.token
        if self._in_cluster:
            try:
                return (config_mod.K8S_SA_DIR / "token").read_text().strip()
            except OSError:
                pass
        return ""

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            r = await self._client.get(self.base + path, params=params, headers={"Authorization": f"Bearer {self._token()}"})
        except httpx.ConnectError as e:
            msg = "Kubernetes could not be reached"
            if "CERTIFICATE" in str(e).upper() or "SSL" in str(e).upper():
                msg = "Kubernetes API certificate is not trusted: set kubernetes.ca_file (or verify_tls: false for a lab)"
            self.last_error = msg
            raise KubernetesError(msg) from e
        except httpx.HTTPError as e:
            self.last_error = f"Kubernetes could not be reached ({type(e).__name__})"
            raise KubernetesError(self.last_error) from e
        if r.status_code in (401, 403):
            self.last_error = (f"Kubernetes refused the token (HTTP {r.status_code}); it needs get/list on pods, nodes "
                               "and deployments")
            raise KubernetesError(self.last_error)
        if r.status_code == 404:
            self.last_error = "Kubernetes answered 404: check kubernetes.url"
            raise KubernetesError(self.last_error)
        if r.status_code >= 400:
            self.last_error = f"Kubernetes returned HTTP {r.status_code}"
            raise KubernetesError(self.last_error)
        try:
            data = r.json()
        except ValueError as e:
            self.last_error = "Kubernetes returned something that is not JSON (wrong kubernetes.url?)"
            raise KubernetesError(self.last_error) from e
        self.last_error = None
        return data

    async def _list(self, path: str, namespaced: bool) -> list[dict[str, Any]]:
        paths = ([path.replace("{ns}", ns) for ns in self.cfg.namespaces] if namespaced and self.cfg.namespaces
                 else [path.replace("/namespaces/{ns}", "")])
        out: list[dict[str, Any]] = []
        for p in paths:
            token = ""
            for _ in range(20):  # follow `continue` tokens, bounded
                data = await self._get(p, {"limit": PAGE, **({"continue": token} if token else {})})
                if not isinstance(data, dict) or "items" not in data:
                    self.last_error = "Kubernetes returned an unexpected answer"
                    raise KubernetesError(self.last_error)
                out += [i for i in data["items"] if isinstance(i, dict)]
                token = data.get("metadata", {}).get("continue", "")
                if not token:
                    break
        return out

    async def pods(self, now: float | None = None) -> list[dict[str, Any]]:
        now = now or time.time()
        return [pod_view(p, now) for p in await self._list("/api/v1/namespaces/{ns}/pods", True)]

    async def nodes(self) -> list[dict[str, Any]]:
        return [node_view(n) for n in await self._list("/api/v1/nodes", False)]

    async def deployments(self) -> list[dict[str, Any]]:
        return [deployment_view(d) for d in await self._list("/apis/apps/v1/namespaces/{ns}/deployments", True)]

    async def instant(self, expr: str, at: float | None = None) -> list[dict[str, Any]]:
        metric, f = parse(expr)
        match = lambda v, key: key not in f or fnmatch.fnmatchcase(v, f[key])  # noqa: E731
        if metric == "node_not_ready":
            return [{"labels": {"node": n["name"]}, "value": 1.0} for n in await self.nodes()
                    if not n["ready"] and match(n["name"], "node")]
        if metric == "deployment_unavailable":
            return [{"labels": {"namespace": d["namespace"], "deployment": d["name"]}, "value": float(d["desired"] - d["available"])}
                    for d in await self.deployments()
                    if d["desired"] > d["available"] and match(d["namespace"], "namespace") and match(d["name"], "deployment")]
        out = []
        for p in await self.pods(at):
            if not (match(p["namespace"], "namespace") and match(p["name"], "pod")):
                continue
            value = {"crashloop": 1.0 if p["crashloop"] else 0.0, "restarts_1h": float(p["restarts_1h"]),
                     "not_ready_minutes": p["not_ready_minutes"], "pod_failed": 1.0 if p["phase"] == "Failed" else 0.0}[metric]
            if value > 0:
                out.append({"labels": {"namespace": p["namespace"], "pod": p["name"]}, "value": value})
        return out

    async def range(self, *_: Any, **__: Any) -> list[dict[str, Any]]:
        raise PromQueryError("Kubernetes has no time series")

    async def healthy(self) -> bool:
        try:
            await self._get("/version")
            return True
        except PromError:
            return False
