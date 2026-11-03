"""Demo mode (NIGRANI_DEMO=1): a stand-in for Prometheus that answers the built-in presets' queries with believable,
deterministic sample data, so Nigrani can be tried (or shown) without any monitoring stack.

It does not evaluate PromQL. It recognises the queries the `core` and `django` presets and the container/host pages
send, by the metric names inside them, and returns a series for each. A query it does not know returns no data.

Every 90 minutes a 15 minute "bad spell" hits the sample app (5xx errors and slow responses), so real alerts fire and
resolve through the normal engine while someone is looking."""
from __future__ import annotations

import math
import re
import time
import zlib
from typing import Any, Callable

from .checks import result_id
from .store import Store

Fn = Callable[[float], "float | None"]
Series = tuple[dict[str, str], Fn]

GIB = 1024 ** 3
PERIOD = 5400          # a bad spell every 90 minutes ...
SPELL = 900            # ... lasting 15
CONTAINERS = ["api", "worker", "nginx", "redis", "postgres"]
VIEWS = ["accounts.list", "orders.create", "orders.detail", "search", "healthz"]
METRICS = [
    "up", "node_cpu_seconds_total", "node_memory_MemAvailable_bytes", "node_memory_MemTotal_bytes",
    "node_filesystem_avail_bytes", "node_filesystem_size_bytes", "node_load1", "node_network_receive_bytes_total",
    "container_cpu_usage_seconds_total", "container_memory_working_set_bytes", "container_start_time_seconds",
    "django_http_requests_total_by_method_total", "django_http_responses_total_by_status_total",
    "django_http_requests_latency_seconds_by_view_method_bucket", "django_db_execute_total",
]


def _noise(key: str, t: float) -> float:
    """Repeatable jitter in [-1, 1], constant within a 30 second bucket."""
    return zlib.crc32(f"{key}:{int(t // 30)}".encode()) / 2 ** 31 - 1


def _wave(t: float, period: float, phase: float = 0.0) -> float:
    return math.sin(2 * math.pi * t / period + phase)


class DemoProm:
    """Same interface as `Prom` (instant / range / healthy / has_metric / close)."""

    def __init__(self, started: float | None = None):
        self.t0 = started if started is not None else time.time()
        self.last_error: str | None = None
        self.last_ok: float | None = time.time()
        self.base = "demo://prometheus"

    # ---- the scenario ----
    def spell(self, t: float) -> float:
        """0..1: how deep into a bad spell the sample app is at time t (1 minute ramps either side)."""
        ph = (t - self.t0 - 120) % PERIOD
        return 0.0 if ph >= SPELL else min(1.0, ph / 60, (SPELL - ph) / 60)

    def _cpu(self, t: float) -> float:
        return max(1.0, 22 + 8 * _wave(t, 3600) + 3 * _noise("cpu", t) + 30 * self.spell(t))

    def _mem_pct(self, t: float) -> float:
        return 55 + 4 * _wave(t, 7200, 1) + 1.5 * _noise("mem", t) + 6 * self.spell(t)

    def _rps(self, t: float) -> float:
        return max(1.0, 46 + 12 * _wave(t, 3600, 2) + 3 * _noise("rps", t))

    def _err_pct(self, t: float) -> float:
        return max(0.0, 0.2 + 0.1 * _noise("err", t) + 6.5 * self.spell(t))

    def _latency(self, q: float, t: float) -> float:
        base = {0.5: 0.04, 0.95: 0.12, 0.99: 0.3}.get(q, 0.12)
        return base * (1 + 0.15 * _noise(f"lat{q}", t)) + (3.6 * base / 0.12 * self.spell(t) if q >= 0.9 else 0.5 * base * self.spell(t))

    # ---- evaluation ----
    def _containers(self, expr: str) -> list[str]:
        named = re.findall(r'name="([^"]+)"', expr)
        return [n for n in CONTAINERS if n in named] if named else list(CONTAINERS)

    def _group(self, expr: str) -> str | None:
        m = re.search(r"by \(([\w, ]+)\)", expr)
        return m.group(1).split(",")[0].strip() if m else None

    def _container_series(self, expr: str, fn: Callable[[str, float], float], agg: str) -> list[Series]:
        names = self._containers(expr)
        label = self._group(expr)
        if label:
            return [({label: n}, (lambda t, n=n: fn(n, t))) for n in names]
        pick = sum if agg == "sum" else max
        return [({}, lambda t: pick(fn(n, t) for n in names))]

    def _series(self, expr: str) -> list[Series]:
        e = expr
        # --- Django ---
        if "histogram_quantile" in e and "django_http" in e:
            q = float("0." + re.search(r"histogram_quantile\(0\.(\d+)", e).group(1))
            if "by (le, view)" in e:
                return [({"view": v}, (lambda t, i=i: self._latency(q, t) * (0.6 + 0.3 * i))) for i, v in enumerate(VIEWS)]
            return [({}, lambda t: self._latency(q, t))]
        if "django_http_responses_total_by_status_total" in e:
            if "by (status)" in e:
                share = {"200": 0.8, "201": 0.08, "301": 0.05, "404": 0.05}
                out: list[Series] = [({"status": s}, (lambda t, k=k: self._rps(t) * k * (1 - self._err_pct(t) / 100)))
                                     for s, k in share.items()]
                return out + [({"status": "500"}, lambda t: self._rps(t) * self._err_pct(t) / 100)]
            return [({}, lambda t: self._err_pct(t))]
        if "django_http_requests_total_by_method_total" in e:
            return [({}, self._rps)]
        if "django_db_execute_total" in e:
            return [({}, lambda t: self._rps(t) * 2.6)]
        # --- host ---
        if "count by (cpu)" in e:
            return [({}, lambda t: 4.0)]
        if "node_cpu_seconds_total" in e:
            if "iowait" in e:
                return [({}, lambda t: max(0.0, 0.6 + 0.3 * _noise("iow", t)))]
            return [({}, self._cpu)]
        if "1 - sum(node_memory_MemAvailable_bytes)" in e:
            scale = 1.0 if "* 100" in e else 0.01          # the same expression as a 0-1 fraction when it is not times 100
            return [({}, lambda t: self._mem_pct(t) * scale)]
        if "node_memory_MemTotal_bytes" in e:
            return [({}, lambda t: 8.0 * GIB)]
        if "node_memory_MemAvailable_bytes" in e:
            return [({}, lambda t: 8.0 * GIB * (1 - self._mem_pct(t) / 100))]
        if "node_memory_SwapTotal_bytes" in e:
            return [({}, lambda t: 2.0 * GIB)]
        if "node_memory_SwapFree_bytes" in e:
            return [({}, lambda t: 1.9 * GIB)]
        if "node_load1" in e:
            return [({}, lambda t: max(0.1, self._cpu(t) / 25))]
        if "node_load5" in e or "node_load15" in e:
            return [({}, lambda t: max(0.1, self._cpu(t) / 30))]
        if "node_boot_time_seconds" in e:
            return [({}, lambda t: 12 * 86400 + (t - self.t0))]
        if "node_filesystem" in e:
            used = lambda t: 41 + (t - self.t0) / 86400 * 0.02            # noqa: E731  (creeps up a little)
            labels = {"device": "/dev/sda1", "mountpoint": "/"}
            if "deriv" in e:
                return [(labels, lambda t: 52.0)]
            if "node_filesystem_avail_bytes" in e and "node_filesystem_size_bytes" in e:
                return [({} if e.lstrip().startswith("max(") else labels, used)]
            if "node_filesystem_size_bytes" in e:
                return [(labels, lambda t: 80.0 * GIB)]
            return [(labels, lambda t: 80.0 * GIB * (1 - used(t) / 100))]
        if "node_network_receive_bytes_total" in e:
            return [({}, lambda t: 180_000 * (1 + 0.4 * _wave(t, 1800)) * (1 + self.spell(t)))]
        if "node_network_transmit_bytes_total" in e:
            return [({}, lambda t: 420_000 * (1 + 0.4 * _wave(t, 1800, 1)) * (1 + self.spell(t)))]
        if "node_disk_read_bytes_total" in e:
            return [({}, lambda t: 40_000 * (1 + _noise("dr", t) * 0.5))]
        if "node_disk_written_bytes_total" in e:
            return [({}, lambda t: 220_000 * (1 + _noise("dw", t) * 0.5))]
        # --- containers ---
        if "container_label_restartcount" in e:
            return self._container_series(e, lambda n, t: 2.0 if n == "worker" else 0.0, "max")
        if "container_last_seen" in e:
            return self._container_series(e, lambda n, t: 3.0 + 2 * abs(_noise("seen" + n, t)), "max")
        if "container_cpu_usage_seconds_total" in e:
            base = {"api": 16, "worker": 34, "nginx": 2.5, "redis": 3.5, "postgres": 11}
            gain = {"api": 40, "worker": 8, "postgres": 14}
            return self._container_series(
                e, lambda n, t: max(0.2, base[n] * (1 + 0.25 * _noise("c" + n, t)) + gain.get(n, 0.5) * self.spell(t)), "sum")
        if "container_memory_working_set_bytes" in e:
            size = {"api": 0.45, "worker": 0.55, "nginx": 0.03, "redis": 0.12, "postgres": 0.38}
            def mem(n: str, t: float) -> float:
                grow = 0.25 * (((t - self.t0) % 14400) / 14400) if n == "worker" else 0.0   # a slow leak, restarted every 4h
                return (size[n] + grow + 0.01 * _noise("m" + n, t)) * GIB
            return self._container_series(e, mem, "max")
        if "container_spec_memory_limit_bytes" in e:
            limit = {"api": 1.0, "worker": 1.0, "nginx": 0.25, "redis": 0.5, "postgres": 1.5}
            return self._container_series(e, lambda n, t: limit[n] * GIB, "max")
        if "container_start_time_seconds" in e:
            if "time() -" in e:
                return self._container_series(e, lambda n, t: t - self._started(n), "max")
            return self._container_series(e, lambda n, t: self._started(n), "max")
        if "container_network_receive_bytes_total" in e:
            return self._container_series(e, lambda n, t: 30_000 * (1 + 0.3 * _noise("rx" + n, t)), "sum")
        if "container_network_transmit_bytes_total" in e:
            return self._container_series(e, lambda n, t: 55_000 * (1 + 0.3 * _noise("tx" + n, t)), "sum")
        # --- targets ---
        if e.strip() == "up" or e.strip().startswith("up{"):
            jobs = [("node-exporter", "node-exporter:9100"), ("cadvisor", "cadvisor:8080"),
                    ("django-api", "api:8000"), ("django-ws", "ws:8001")]
            return [({"job": j, "instance": i}, lambda t: 1.0) for j, i in jobs]
        return []

    def _started(self, name: str) -> float:
        return self.t0 - (7200 if name == "worker" else 3 * 86400)

    def _eval(self, expr: str, t: float) -> list[dict[str, Any]]:
        out = []
        cmp = re.search(r"\)\s*>\s*(\d+(?:\.\d+)?)\s*$", expr)
        floor = float(cmp.group(1)) if cmp else None
        for labels, fn in self._series(expr):
            v = fn(t)
            if v is None or (floor is not None and v <= floor):
                continue
            out.append({"labels": labels, "value": float(v)})
        return out

    # ---- the Prom interface ----
    async def instant(self, query: str, at: float | None = None) -> list[dict[str, Any]]:
        return self._eval(query, at if at is not None else time.time())

    async def range(self, query: str, start: float, end: float, step: float) -> list[dict[str, Any]]:
        step = max(step, 1.0)
        series = self._series(query)
        n = int((end - start) // step) + 1
        return [{"labels": labels, "points": [[start + i * step, fn(start + i * step)] for i in range(n)]}
                for labels, fn in series]

    async def has_metric(self, name: str) -> bool:
        return name in METRICS

    async def metric_names(self) -> list[str]:
        return sorted(METRICS)

    async def healthy(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def seed_demo(store: Store, views: list[Any], now: float | None = None) -> None:
    """Give a fresh demo database some history: finished incidents and 90 days of uptime. Safe to call every start."""
    now = now or time.time()
    day = 86400
    for view in views:
        sid = view.id
        if not store.recent_incidents(1, now - 60 * day, server=sid):
            past = [
                ("django-5xx", "Elevated 5xx rate", "warning", 2.4, 2.0, "percent", 3 * day + 5000, 1380,
                 "5xx responses went up after a deploy; rolled back."),
                ("django-latency", "Slow responses (p95)", "critical", 3.4, 3.0, "seconds", 3 * day + 4900, 1500,
                 "p95 latency above 3s while the database was busy."),
                ("django-5xx", "Elevated 5xx rate", "critical", 6.1, 5.0, "percent", day + 30000, 840, ""),
            ]
            for rid, name, sev, val, thr, unit, ago, dur, note in past:
                started = now - ago
                iid = store.create_incident(
                    source_id=rid, series_key="", rule_name=name, series="", labels={}, severity=sev, started_at=started,
                    value=val, threshold=thr, unit=unit, summary=note, silenced=False, server=sid)
                store.add_event(iid, started, "fired", f"{sev}: {val}")
                store.add_event(iid, started + dur, "resolved", "back to normal")
                store.resolve_incident(iid, started + dur, val / 4)
        if not store.list_announcements(0):
            started = now - 3 * day + 5000
            aid = store.add_announcement(
                kind="incident", title="Elevated error rates on the API", by="demo", now=started, starts_at=started, ends_at=None,
                body="Some requests failed for about 25 minutes after a deploy. We rolled it back and are watching.")
            store.resolve_announcement(aid, started + 1500)
            store.add_announcement(
                kind="maintenance", title="Database upgrade", by="demo", now=now, starts_at=now + 2 * day,
                ends_at=now + 2 * day + 1800, body="The app stays up, but writes pause for a few minutes around the switchover.")
        for check in view.checks:
            rid = result_id(sid, check.id)
            if store.check_uptime(rid, 0)[1]:
                continue
            for d in range(90, 0, -1):
                ts = now - d * day
                bad = (d == 41 and check.id == "api") or (d in (17, 18) and check.id == "database")
                store.add_check_day(rid, ts, 0 if bad else 1440 - (3 if d % 11 == 0 else 0), 1440)
            for m in range(30, 7 * 24 * 60, 30):
                store.add_check_result(rid, now - m * 60, not (check.id == "api" and 3000 <= m <= 3060), 20.0 + (m % 7), "")


def demo_ai_text(kind: str) -> str:
    """Canned answers so the AI buttons work in demo mode without an API key. Clearly labelled where they are shown."""
    if kind == "rule":
        return ""
    return (
        "**What happened**\n"
        "5xx responses rose from about 0.2% to over 6% while p95 latency jumped from 0.12 s to several seconds. "
        "CPU on the api container climbed at the same time and the worker's memory kept growing.\n\n"
        "**Likely cause**\n"
        "The api is saturated: requests queue, time out and return 500. The timing fits a traffic burst or a slow "
        "dependency (database or a downstream call) rather than a crash, because no container restarted.\n\n"
        "**What to check next**\n"
        "- Compare the slowest views on the Traffic page with the database panel for the same window.\n"
        "- Look at the api logs around the start of the incident for timeouts.\n"
        "- If it repeats on a schedule, check what runs every 90 minutes (cron, batch jobs, deploys).")
