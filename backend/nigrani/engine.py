"""Alert engine: evaluates rules against every server's Prometheus and runs the
OK -> Pending -> Firing -> Resolved state machine with dedupe, reminders and silences."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import Config
from .format import build_event, fmt_value
from .notifiers import Notifier
from .prom import Prom, PromError, series_key, series_label
from .store import Store

log = logging.getLogger("nigrani.engine")
SEV_RANK = {"warning": 1, "critical": 2}
MAX_RETRIES = 10

Key = tuple[str, str, str]  # (rule/source id, server id, series key)


@dataclass
class Signal:
    source_id: str  # rule id, or "svc:.." / "check:.." / "meta:.." for built-in signals
    rule_name: str
    series: str
    series_key: str
    severity: str | None  # None = healthy
    value: float | None = None
    threshold: float | None = None
    unit: str = "short"
    summary: str = ""
    for_seconds: int = 0
    labels: dict[str, str] = field(default_factory=dict)
    server: str = "default"


@dataclass
class SeriesState:
    pending_since: float
    last_seen: float
    firing: bool = False
    severity: str | None = None
    incident_id: int | None = None
    last_notified: float = 0.0
    value: float | None = None
    signal: Signal | None = None
    retry_kind: str | None = None  # notification kind to re-send because every channel failed
    retries: int = 0
    acked_at: float | None = None  # someone is on it: reminders pause (until ack_until, or until it resolves)
    ack_until: float | None = None
    acked_by: str = ""
    ack_note: str = ""


def classify(value: float, direction: str, warn: float | None, crit: float | None) -> tuple[str | None, float | None]:
    def breach(t: float) -> bool:
        return value > t if direction == "above" else value < t

    if crit is not None and breach(crit):
        return "critical", crit
    if warn is not None and breach(warn):
        return "warning", warn
    return None, None


class Engine:
    def __init__(self, store: Store, proms: dict[str, Prom] | Prom, notifier: Notifier, cfg: Config,
                 clock: Callable[[], float] = time.time, lokis: dict[str, Prom] | None = None,
                 sentries: dict[str, Any] | None = None, clouds: dict[str, Any] | None = None,
                 kubes: dict[str, Any] | None = None, dogs: dict[str, Any] | None = None, azures: dict[str, Any] | None = None, argos: dict[str, Any] | None = None):
        self.store, self.notifier, self.cfg, self.clock = store, notifier, cfg, clock
        self.lokis: dict[str, Prom] = lokis or {}  # server id -> Loki client (only servers that have Loki)
        self.azures: dict[str, Any] = azures or {}  # server id -> Azure Monitor client
        self.argos: dict[str, Any] = argos or {}  # server id -> Argo CD client
        self.dogs: dict[str, Any] = dogs or {}  # server id -> Datadog client
        self.kubes: dict[str, Any] = kubes or {}  # server id -> Kubernetes client
        self.clouds: dict[str, Any] = clouds or {}  # server id -> CloudWatch client
        self.sentries: dict[str, Any] = sentries or {}  # server id -> Sentry client (same interface as Prom)
        self.proms: dict[str, Prom] = proms if isinstance(proms, dict) else {"default": proms}
        views = {v.id: v for v in cfg.server_views()}
        self.names = {sid: views[sid].name if sid in views else sid for sid in self.proms}
        self.envs = {sid: views[sid].environment if sid in views else cfg.app.environment for sid in self.proms}
        self.multi = len(self.proms) > 1
        self.state: dict[Key, SeriesState] = {}
        self.rule_errors: dict[str, dict[str, str]] = {}  # rule id -> {server id: error}
        self._prom_failures: dict[str, int] = {sid: 0 for sid in self.proms}
        self.last_eval: float | None = None
        self.load_state()

    def load_state(self) -> None:
        """Rebuild firing state after a restart so open incidents don't re-notify."""
        now = self.clock()
        for inc in self.store.open_incidents():
            if inc["server"] not in self.proms:
                # server was removed/renamed in the config; nothing will ever evaluate or resolve this incident
                self.store.resolve_incident(inc["id"], now, inc["last_value"])
                continue
            key = (inc["source_id"], inc["server"], inc["series_key"])
            self.state[key] = SeriesState(
                pending_since=inc["started_at"], last_seen=now, firing=True, severity=inc["severity"],
                incident_id=inc["id"], last_notified=inc["last_notified"] or inc["started_at"], value=inc["last_value"],
                acked_at=inc.get("acked_at"), ack_until=inc.get("ack_until"), acked_by=inc.get("acked_by") or "",
                ack_note=inc.get("ack_note") or "",
                # rebuild what the messages need (rule name, series, unit...) so a "resolved" after a restart
                # reads like any other
                signal=Signal(
                    source_id=inc["source_id"], rule_name=inc["rule_name"], series=inc["series"],
                    series_key=inc["series_key"], severity=inc["severity"], value=inc["last_value"],
                    threshold=inc["threshold"], unit=inc["unit"], summary=inc["summary"], labels=inc["labels"],
                    server=inc["server"]),
            )

    # ---------- notification ----------
    def _link(self) -> str:
        return self.cfg.app.public_url.rstrip("/") + "/#/alerts" if self.cfg.app.public_url else ""

    async def _notify(self, kind: str, st: SeriesState, sig: Signal, now: float,
                      ack: tuple[str, str] | None = None) -> None:
        inc = self.store.get_incident(st.incident_id) if st.incident_id else None
        started = inc["started_at"] if inc else st.pending_since
        if self.store.is_silenced(sig.source_id, sig.series, now, sig.server):
            if st.incident_id:
                self.store.update_incident(st.incident_id, silenced=1)
                self.store.add_event(st.incident_id, now, "suppressed", f"{kind}: silenced, no message sent")
            return
        ev = build_event(
            kind, severity=st.severity or sig.severity or "warning", rule_name=sig.rule_name, series=sig.series,
            value=sig.value if sig.value is not None else st.value, threshold=sig.threshold, unit=sig.unit,
            summary=sig.summary, started_at=started, now=now,
            environment=self.envs.get(sig.server, self.cfg.app.environment),
            link=self._link(), incident_id=st.incident_id,
            server=self.names.get(sig.server, sig.server) if self.multi else "",
            ack_by=(ack[0] if ack else st.acked_by) if (ack or kind == "resolved") else "",
            ack_note=ack[1] if ack else "",
        )
        ev["server_id"] = sig.server
        st.last_notified = now
        if st.incident_id:
            self.store.update_incident(st.incident_id, last_notified=now)
        try:
            res = await self.notifier.send(ev, now=now)
        except Exception:  # noqa: BLE001 - never let a channel break evaluation
            log.exception("notification failed")
            res = {"wanted": 1, "ok": 0}
        if st.incident_id and res and res.get("wanted") is not None:
            self.store.add_event(
                st.incident_id, now, "notified",
                f"{kind}: no channel to notify" if res["wanted"] == 0
                else f"{kind}: sent to {res['ok']} of {res['wanted']} channel{'' if res['wanted'] == 1 else 's'}")
        # every wanted channel failed (webhook down, typo...): try again on the next cycles instead of going silent
        if res and res["wanted"] and not res["ok"] and kind not in ("resolved", "acknowledged") and st.retries < MAX_RETRIES:
            st.retry_kind, st.retries = kind, st.retries + 1
        else:
            st.retry_kind, st.retries = None, 0

    # ---------- state machine ----------
    async def process(self, sig: Signal, now: float | None = None) -> None:
        now = now or self.clock()
        key: Key = (sig.source_id, sig.server, sig.series_key)
        st = self.state.get(key)

        if sig.severity is None:
            if st is not None:
                await self._resolve(key, st, sig, now)
            return

        if st is None:
            st = self.state[key] = SeriesState(pending_since=now, last_seen=now)
        st.last_seen, st.value, st.signal = now, sig.value, sig

        if not st.firing:
            st.severity = sig.severity
            if now - st.pending_since >= sig.for_seconds:
                await self._fire(st, sig, now)
            return

        # already firing
        if sig.severity != st.severity:
            escalated = SEV_RANK[sig.severity] > SEV_RANK[st.severity or "warning"]
            self.store.add_event(st.incident_id, now, "severity", f"{st.severity} → {sig.severity} ({fmt_value(sig.value, sig.unit)})")
            st.severity = sig.severity
            self.store.update_incident(st.incident_id, severity=sig.severity, threshold=sig.threshold)
            if escalated:
                if st.acked_at is not None:      # it got worse: whoever acknowledged it needs to look again
                    self._clear_ack(st)
                    self.store.add_event(st.incident_id, now, "unacknowledged", "it got worse")
                await self._notify("escalated", st, sig, now)
        peak = self._peak(st.incident_id, sig)
        self.store.update_incident(st.incident_id, last_value=sig.value, peak_value=peak)
        if st.retry_kind:
            await self._notify(st.retry_kind, st, sig, now)
        elif now - st.last_notified >= self.cfg.alerts.repeat_interval and not self._is_acked(st, now):
            await self._notify("reminder", st, sig, now)

    @staticmethod
    def _is_acked(st: SeriesState, now: float) -> bool:
        return st.acked_at is not None and (st.ack_until is None or now < st.ack_until)

    def _clear_ack(self, st: SeriesState) -> None:
        st.acked_at = st.ack_until = None
        st.acked_by = st.ack_note = ""
        if st.incident_id:
            self.store.clear_ack(st.incident_id)

    def _find(self, incident_id: int) -> tuple[Key, SeriesState] | None:
        return next(((k, st) for k, st in self.state.items() if st.incident_id == incident_id and st.firing), None)

    async def acknowledge(self, incident_id: int, by: str, note: str = "", hours: float | None = None,
                          now: float | None = None) -> dict | None:
        """Mark a firing incident as being handled: its reminders pause (for `hours`, or until it resolves) and the
        channels are told once. Returns the incident, or None if it is not firing."""
        now = now or self.clock()
        inc = self.store.get_incident(incident_id)
        if not inc or inc["status"] != "firing":
            return None
        until = now + hours * 3600 if hours else None
        self.store.ack_incident(incident_id, by, note, until, now)
        self.store.add_event(incident_id, now, "acknowledged", f"{by}: {note}" if note else by)
        found = self._find(incident_id)
        if found:
            _, st = found
            st.acked_at, st.ack_until, st.acked_by, st.ack_note = now, until, by, note
            sig = st.signal or Signal(inc["source_id"], inc["rule_name"], inc["series"], inc["series_key"],
                                      inc["severity"], inc["last_value"], inc["threshold"], inc["unit"], inc["summary"],
                                      server=inc["server"])
            await self._notify("acknowledged", st, sig, now, ack=(by, note))
        return self.store.get_incident(incident_id)

    def unacknowledge(self, incident_id: int) -> dict | None:
        inc = self.store.get_incident(incident_id)
        if not inc or inc["status"] != "firing":
            return None
        found = self._find(incident_id)
        if found:
            self._clear_ack(found[1])
        else:
            self.store.clear_ack(incident_id)
        self.store.add_event(incident_id, self.clock(), "unacknowledged", "")
        return self.store.get_incident(incident_id)

    def _peak(self, incident_id: int | None, sig: Signal) -> float | None:
        inc = self.store.get_incident(incident_id) if incident_id else None
        old = inc["peak_value"] if inc else None
        if sig.value is None or old is None:
            return sig.value if sig.value is not None else old
        low_is_bad = sig.threshold is not None and sig.value < sig.threshold and old < sig.threshold
        return min(old, sig.value) if low_is_bad else max(old, sig.value)

    async def _fire(self, st: SeriesState, sig: Signal, now: float) -> None:
        st.firing = True
        st.incident_id = self.store.create_incident(
            source_id=sig.source_id, series_key=sig.series_key, rule_name=sig.rule_name, series=sig.series,
            labels=sig.labels, severity=sig.severity, started_at=now, value=sig.value, threshold=sig.threshold,
            unit=sig.unit, summary=sig.summary, server=sig.server,
        )
        detail = fmt_value(sig.value, sig.unit) if sig.value is not None else sig.summary
        if sig.threshold is not None and sig.value is not None:
            detail += f" (threshold {fmt_value(sig.threshold, sig.unit)})"
        self.store.add_event(st.incident_id, now, "firing", f"{sig.severity}: {detail}")
        await self._notify("firing", st, sig, now)

    async def _resolve(self, key: Key, st: SeriesState, sig: Signal, now: float) -> None:
        if st.firing and st.incident_id:
            self.store.resolve_incident(st.incident_id, now, sig.value)   # keeps the incident's last_value if None
            self.store.add_event(st.incident_id, now, "resolved",
                                 f"back to {fmt_value(sig.value, sig.unit)}" if sig.value is not None else "no longer reported")
            # keep the rule's identity from the firing signal but report the recovered value
            base = st.signal or sig
            sig_for_event = Signal(**{**base.__dict__, "value": sig.value})
            st.value = sig.value
            await self._notify("resolved", st, sig_for_event, now)
        self.state.pop(key, None)

    def _healthy(self, key: Key, st: SeriesState, fallback_name: str = "") -> Signal:
        base = st.signal or Signal(key[0], fallback_name or key[0], "", key[2], None, server=key[1])
        # the series is gone, so there is no current value to report (the last firing value would read as
        # "Now: <a value over the threshold>")
        return Signal(**{**base.__dict__, "severity": None, "value": None})

    # ---------- evaluation ----------
    def _client(self, datasource: str, server_id: str, prom: Prom) -> Any:
        if datasource == "loki":
            return self.lokis.get(server_id)
        if datasource == "sentry":
            return self.sentries.get(server_id)
        if datasource == "cloudwatch":
            return self.clouds.get(server_id)
        if datasource == "kubernetes":
            return self.kubes.get(server_id)
        if datasource == "datadog":
            return self.dogs.get(server_id)
        if datasource == "azure":
            return self.azures.get(server_id)
        if datasource == "argocd":
            return self.argos.get(server_id)
        return prom

    def drop_rule(self, rule_id: str, now: float | None = None, server: str | None = None) -> None:
        """Rule deleted/disabled/no longer scoped to `server`: close its open incidents quietly
        (nothing will ever resolve them otherwise)."""
        now = now or self.clock()
        for key in [k for k in self.state if k[0] == rule_id and (server is None or k[1] == server)]:
            st = self.state.pop(key)
            if st.firing and st.incident_id:
                self.store.resolve_incident(st.incident_id, now, st.value)
        if server is None:
            self.rule_errors.pop(rule_id, None)
        elif rule_id in self.rule_errors:
            self.rule_errors[rule_id].pop(server, None)

    def rule_error(self, rule_id: str) -> str | None:
        errs = self.rule_errors.get(rule_id)
        if not errs:
            return None
        if not self.multi:
            return next(iter(errs.values()))
        return "; ".join(f"{self.names.get(s, s)}: {e}" for s, e in errs.items())

    async def evaluate_rules(self, now: float | None = None) -> None:
        now = now or self.clock()
        rules = self.store.list_rules(enabled_only=True)
        for server_id, prom in self.proms.items():
            for rule in rules:
                if rule["servers"] and server_id not in rule["servers"]:
                    self.drop_rule(rule["id"], now, server_id)  # scope changed while incidents were open
                    continue
                client = self._client(rule.get("datasource", "prometheus"), server_id, prom)
                if client is None:
                    # a log rule on a server without Loki: nothing to evaluate there (and nothing left open)
                    self.drop_rule(rule["id"], now, server_id)
                    continue
                try:
                    samples = await client.instant(rule["expr"])
                except PromError as e:
                    self.rule_errors.setdefault(rule["id"], {})[server_id] = str(e)
                    continue
                if rule["id"] in self.rule_errors:
                    self.rule_errors[rule["id"]].pop(server_id, None)
                    if not self.rule_errors[rule["id"]]:
                        del self.rule_errors[rule["id"]]
                seen: set[Key] = set()
                for s in samples:
                    if s["value"] is None:
                        continue
                    skey = series_key(s["labels"])
                    seen.add((rule["id"], server_id, skey))
                    sev, thr = classify(s["value"], rule["direction"], rule["warn"], rule["crit"])
                    await self.process(Signal(
                        source_id=rule["id"], rule_name=rule["name"], series=series_label(s["labels"]),
                        series_key=skey, severity=sev, value=s["value"], threshold=thr, unit=rule["unit"],
                        summary=rule["summary"], for_seconds=rule["for_seconds"], labels=s["labels"],
                        server=server_id), now)
                # Series that vanished (container removed, exporter label change) resolve after a grace period.
                # For a log rule a missing series just means "no matching lines", i.e. healthy: resolve at once
                # (a Loki outage raises an error above instead, which never resolves anything).
                grace = 0 if rule.get("datasource", "prometheus") in ("loki", "sentry", "kubernetes", "argocd") else self.cfg.alerts.absent_grace
                for k in [k for k in self.state if k[0] == rule["id"] and k[1] == server_id and k not in seen]:
                    st = self.state[k]
                    if now - st.last_seen >= grace:
                        await self._resolve(k, st, self._healthy(k, st, rule["name"]), now)
        self.last_eval = now

    async def sync_external(self, prefix: str, signals: list[Signal], now: float | None = None,
                            server: str = "default") -> None:
        """Process a complete set of built-in signals for one server (services, uptime checks);
        ones no longer reported resolve."""
        now = now or self.clock()
        present: set[Key] = set()
        for sig in signals:
            sig.server = server
            present.add((sig.source_id, server, sig.series_key))
            await self.process(sig, now)
        for k in [k for k in self.state if k[0].startswith(prefix) and k[1] == server and k not in present]:
            await self._resolve(k, self.state[k], self._healthy(k, self.state[k]), now)

    async def prometheus_health(self, now: float | None = None) -> None:
        for server_id, prom in self.proms.items():
            ok = await prom.healthy()
            self._prom_failures[server_id] = 0 if ok else self._prom_failures.get(server_id, 0) + 1
            failing = self._prom_failures[server_id] >= 3
            await self.process(Signal(
                source_id="meta:prometheus", rule_name="Prometheus unreachable", series="", series_key="",
                severity="critical" if failing else None, server=server_id,
                summary=f"Nigrani cannot query Prometheus: {prom.last_error}",
            ), now)

    async def run(self) -> None:
        while True:
            try:
                await self.prometheus_health()
                await self.evaluate_rules()
            except Exception:  # noqa: BLE001
                log.exception("evaluation cycle failed")
            await asyncio.sleep(self.cfg.alerts.eval_interval)
