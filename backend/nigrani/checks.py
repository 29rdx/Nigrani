"""Synthetic uptime checks: HTTP, TCP and TLS certificate expiry."""
from __future__ import annotations

import asyncio
import logging
import ssl
import time
from datetime import datetime, timezone

import httpx

from .config import CheckCfg, Config, ServerView
from .engine import Engine, Signal
from .store import Store

log = logging.getLogger("nigrani.checks")


async def run_check(c: CheckCfg) -> tuple[bool, float | None, str]:
    t0 = time.perf_counter()
    try:
        if c.type == "http":
            async with httpx.AsyncClient(timeout=c.timeout, verify=c.verify_tls, follow_redirects=True) as cl:
                r = await cl.get(c.target)
            ms = (time.perf_counter() - t0) * 1000
            ok = (r.status_code == c.expect_status) if c.expect_status else r.status_code < 400
            return ok, ms, f"HTTP {r.status_code}"
        host, _, port = c.target.rpartition(":")
        if c.type == "tcp":
            _, w = await asyncio.wait_for(asyncio.open_connection(host, int(port)), c.timeout)
            w.close()
            return True, (time.perf_counter() - t0) * 1000, "connected"
        if c.type == "ssl":
            if not host:  # allow bare hostname
                host, port = c.target, "443"
            ctx = ssl.create_default_context()
            _, w = await asyncio.wait_for(asyncio.open_connection(host, int(port), ssl=ctx, server_hostname=host), c.timeout)
            cert = w.get_extra_info("peercert")
            w.close()
            exp = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), timezone.utc)
            days = (exp - datetime.now(timezone.utc)).days
            return days > c.warn_days, (time.perf_counter() - t0) * 1000, f"{days} days left"
    except (OSError, asyncio.TimeoutError, httpx.HTTPError, ssl.SSLError, ValueError, KeyError) as e:
        return False, None, f"{type(e).__name__}: {e}"[:200]
    return False, None, "unsupported check"


def result_id(server_id: str, check_id: str) -> str:
    return check_id if server_id == "default" else f"{server_id}/{check_id}"


class CheckRunner:
    """Runs one server's uptime checks. Results are stored under "<server>/<check id>" (just "<check id>" for the
    implicit single server, so databases from before multi-server keep their history)."""

    def __init__(self, cfg: Config, store: Store, engine: Engine, server: ServerView | None = None):
        self.cfg, self.store, self.engine = cfg, store, engine
        self.server = server or cfg.server_views()[0]
        self.checks = self.server.checks
        self._fails: dict[str, int] = {}
        self._last_run: dict[str, float] = {}

    async def run_once(self, only_due: bool = True) -> None:
        now = time.time()
        for c in self.checks:
            if only_due and now - self._last_run.get(c.id, 0) < c.interval:
                continue
            self._last_run[c.id] = now
            ok, ms, detail = await run_check(c)
            self.store.add_check_result(self._rid(c.id), now, ok, ms, detail)
            self._fails[c.id] = 0 if ok else self._fails.get(c.id, 0) + 1
        sigs = []
        for c in self.checks:
            if not c.critical:
                continue
            last = self.store.last_check_result(self._rid(c.id))
            failing = self._fails.get(c.id, 0) >= 2  # two consecutive failures avoid one-off blips
            sigs.append(Signal(
                source_id=f"check:{c.id}", rule_name=f"Check failing: {c.name}", series=c.target, series_key=c.id,
                severity="critical" if failing else None,
                summary=(last["detail"] if last else "") or "Check failed", for_seconds=0,
            ))
        await self.engine.sync_external("check:", sigs, server=self.server.id)

    async def run(self) -> None:
        if self.cfg.demo:
            await asyncio.sleep(3)        # the demo's checks look at Nigrani itself: let the server start listening first
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("check cycle failed")
            await asyncio.sleep(5)

    def _rid(self, check_id: str) -> str:
        return result_id(self.server.id, check_id)

    def summary(self) -> list[dict]:
        since = time.time() - 30 * 86400
        out = []
        for c in self.checks:
            rid = self._rid(c.id)
            last = self.store.last_check_result(rid)
            up, n = self.store.check_uptime(rid, since)
            out.append({
                "id": c.id, "name": c.name, "type": c.type, "target": c.target,
                "ok": bool(last["ok"]) if last else None, "latency_ms": last["latency_ms"] if last else None,
                "detail": last["detail"] if last else "", "checked_at": last["ts"] if last else None,
                "uptime_30d": (up / n * 100) if n else None,
                "history": self.store.check_history(rid, time.time() - 6 * 3600, 90),
            })
        return out
