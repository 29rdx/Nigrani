"""Service level objectives and burn-rate alerts.

An SLO says "99.9% of requests succeed over 30 days". That leaves an error budget (0.1%). The *burn rate* is how fast the
budget is being spent relative to an even spend: 1 uses exactly the budget over the window, 14.4 would use 2% of it in an hour.

Alerts follow the multi-window, multi-burn-rate method from the Google SRE workbook: a tier fires only when the burn rate is over
its factor in both a long window (it is real) and a short one (it is still happening), which makes alerts quick to fire,
quick to clear and quiet about blips. The factors are derived from the share of the budget each tier may spend, so they
scale with `window_days`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .config import Config, SloCfg
from .engine import Engine, Signal
from .prom import PromError

log = logging.getLogger("nigrani.slo")

# name, long window s, short window s, share of the budget the long window may spend, severity
TIERS = [
    ("fast", 3600, 300, 0.02, "critical"),
    ("slow", 21600, 1800, 0.05, "critical"),
    ("daily", 86400, 7200, 0.10, "warning"),
    ("trend", 259200, 21600, 0.10, "warning"),
]
LABEL = {"fast": "fast burn", "slow": "slow burn", "daily": "steady burn", "trend": "gradual burn"}


def human(seconds: int) -> str:
    return (f"{seconds // 86400}d" if seconds % 86400 == 0 else f"{seconds // 3600}h" if seconds % 3600 == 0
            else f"{seconds // 60}m")


def tiers_for(window_s: int) -> list[dict[str, Any]]:
    """The tiers that fit inside the SLO window, each with its burn-rate factor: (share of budget) x window / long window."""
    return [{"name": n, "long": lo, "short": sh, "factor": round(share * window_s / lo, 2), "severity": sev}
            for n, lo, sh, share, sev in TIERS if lo <= window_s]


def burn(error_ratio: float | None, target: float) -> float | None:
    return None if error_ratio is None else error_ratio / (1 - target / 100)


def is_applicable(slo: SloCfg, server_id: str) -> bool:
    return not slo.servers or server_id in slo.servers


class SloEngine:
    def __init__(self, cfg: Config, store: Any, engine: Engine, runtimes: dict[str, Any]):
        self.cfg, self.store, self.engine, self.runtimes = cfg, store, engine, runtimes
        self.state: dict[tuple[str, str], dict[str, Any]] = {}
        self._cache: dict[tuple, tuple[float, float | None]] = {}

    # ---- the SLI ----
    async def _query_sum(self, prom: Any, expr: str, window: int) -> float | None:
        res = await prom.instant(expr.replace("{{window}}", f"{window}s"))
        vals = [r["value"] for r in res if r["value"] is not None]
        return sum(vals) if vals else None

    async def error_ratio(self, slo: SloCfg, rt: Any, window: int, now: float) -> float | None:
        """Share of bad events in the last `window` seconds, or None when there was nothing to measure."""
        key = (rt.view.id, slo.id, window)
        hit = self._cache.get(key)
        ttl = 60 if window <= 86400 else 300
        if hit and now - hit[0] < ttl:
            return hit[1]
        if slo.check:
            ratio = self._check_ratio(slo, rt, window, now)
        else:
            total = await self._query_sum(rt.prom, slo.total, window)
            if not total:
                ratio = None
            elif slo.good:
                good = await self._query_sum(rt.prom, slo.good, window) or 0.0
                ratio = max(0.0, min(1.0, 1 - good / total))
            else:
                bad = await self._query_sum(rt.prom, slo.errors, window) or 0.0
                ratio = max(0.0, min(1.0, bad / total))
        if ratio is not None:                                # "no data yet" is not worth remembering: data may arrive any second
            self._cache[key] = (now, ratio)
        return ratio

    def _check_ratio(self, slo: SloCfg, rt: Any, window: int, now: float) -> float | None:
        from .checks import result_id
        rid = result_id(rt.view.id, slo.check)
        if window <= 3 * 86400:
            up, n = self.store.check_uptime(rid, now - window)
        else:                                                # long windows: the per-day totals, which are kept for longer
            days = self.store.check_days(rid, now - window)
            up, n = sum(d["up"] for d in days), sum(d["total"] for d in days)
        return None if not n else 1 - up / n

    # ---- one SLO on one server ----
    async def evaluate(self, slo: SloCfg, rt: Any, now: float | None = None) -> dict[str, Any]:
        now = now or time.time()
        window = slo.window_days * 86400
        budget = 1 - slo.target / 100
        tiers = tiers_for(window)
        wanted = sorted({window, *(t["long"] for t in tiers), *(t["short"] for t in tiers)})
        ratios = {w: await self.error_ratio(slo, rt, w, now) for w in wanted}      # PromError propagates to the caller
        spent = burn(ratios[window], slo.target)
        for t in tiers:
            t["burn_long"], t["burn_short"] = burn(ratios[t["long"]], slo.target), burn(ratios[t["short"]], slo.target)
            t["firing"] = (t["burn_long"] is not None and t["burn_short"] is not None
                           and t["burn_long"] > t["factor"] and t["burn_short"] > t["factor"])
        firing = [t for t in tiers if t["firing"]]
        remaining = None if spent is None else 1 - spent
        status = ("nodata" if spent is None else "critical" if (remaining <= 0 or any(t["severity"] == "critical" for t in firing))
                  else "warning" if firing else "ok")
        return {
            "id": slo.id, "name": slo.name, "description": slo.description, "server": rt.view.id, "target": slo.target,
            "window_days": slo.window_days, "sli": None if ratios[window] is None else (1 - ratios[window]) * 100,
            "budget_remaining": remaining, "budget_minutes": round(budget * window / 60, 1),
            "budget_used_minutes": None if spent is None else round(spent * budget * window / 60, 1),
            "tiers": tiers, "status": status, "error": None, "evaluated_at": now,
            "source": f"uptime check '{slo.check}'" if slo.check else "prometheus",
        }

    def signals(self, slo: SloCfg, st: dict[str, Any], multi: bool, server_name: str) -> list[Signal]:
        series = f"{server_name} · {slo.name}" if multi else slo.name
        out = []
        for t in st["tiers"]:
            bl, bs = t["burn_long"], t["burn_short"]
            out.append(Signal(
                source_id=f"slo:{slo.id}:{t['name']}", rule_name=f"SLO burn rate: {slo.name} ({LABEL[t['name']]})", series=series,
                series_key=f"{slo.id}", severity=t["severity"] if t["firing"] else None, value=bl, threshold=t["factor"],
                summary=(f"The {slo.window_days}-day error budget for {slo.target}% is being spent {bl:.1f}x too fast over the last "
                         f"{human(t['long'])} and {bs:.1f}x over the last {human(t['short'])} (alerts above {t['factor']}x). At that "
                         f"pace it is gone in {slo.window_days / bl:.1f} days." if t["firing"] else ""),
                labels={"slo": slo.id}))
        rem = st["budget_remaining"]
        out.append(Signal(
            source_id=f"slo:{slo.id}:exhausted", rule_name=f"SLO error budget exhausted: {slo.name}", series=series, series_key=slo.id,
            severity="critical" if rem is not None and rem <= 0 else None, value=None if st["sli"] is None else st["sli"],
            threshold=slo.target, unit="percent",
            summary=f"Over the last {slo.window_days} days the SLI is {st['sli']:.3f}%, below the {slo.target}% objective." if rem is not None and rem <= 0 else "",
            labels={"slo": slo.id}))
        return out

    # ---- all of them ----
    async def refresh(self, rt: Any, now: float | None = None, sync: bool = True) -> list[dict[str, Any]]:
        """Evaluate this server's SLOs, remember the numbers, and (when `sync`) open or resolve the alerts. If Prometheus
        cannot be queried nothing is resolved: an outage is not a recovery."""
        now = now or time.time()
        multi = len(self.runtimes) > 1
        out, sigs, failed = [], [], False
        for slo in self.cfg.slos:
            if not is_applicable(slo, rt.view.id):
                continue
            try:
                st = await self.evaluate(slo, rt, now)
            except PromError as e:
                failed = True
                st = {"id": slo.id, "name": slo.name, "description": slo.description, "server": rt.view.id, "target": slo.target,
                      "window_days": slo.window_days, "status": "error", "error": "Prometheus could not answer this SLO's queries",
                      "tiers": [], "sli": None, "budget_remaining": None, "evaluated_at": now, "detail": str(e)[:200]}
            else:
                sigs += self.signals(slo, st, multi, rt.view.name)
            st.pop("detail", None)
            self.state[(rt.view.id, slo.id)] = st
            out.append(st)
        if sync and not failed:
            await self.engine.sync_external("slo:", sigs, now, server=rt.view.id)
        return out

    async def snapshot(self, rt: Any, max_age: float = 60.0) -> list[dict[str, Any]]:
        """What the SLO page shows: the loop's latest numbers, evaluated now if they are stale or missing."""
        mine = [s for s in self.cfg.slos if is_applicable(s, rt.view.id)]
        have = [self.state.get((rt.view.id, s.id)) for s in mine]
        if all(have) and all(time.time() - h["evaluated_at"] < max_age for h in have):
            return have
        return await self.refresh(rt, sync=False)

    async def run(self) -> None:
        if not self.cfg.slos:
            return
        while True:
            for rt in list(self.runtimes.values()):
                try:
                    await self.refresh(rt)
                except Exception:  # noqa: BLE001
                    log.exception("SLO evaluation failed")
            await asyncio.sleep(60)
