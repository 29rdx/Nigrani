"""FastAPI app: REST API + static frontend."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import __version__
from .auth import COOKIE, Auth, Identity, make_authorizer
from .oidc import Oidc, OidcError, new_login
from .sentry import SORTS as SENTRY_SORTS
from .sentry import Sentry
from .argocd import ArgoCD, sync_failing
from .azure import Azure
from .cloudwatch import CloudWatch
from .datadog import Datadog
from .kubernetes import Kubernetes
from .passwords import hash_password, password_problem
from .ai import Ai, AiError
from .checks import CheckRunner, result_id
from .config import Config, ConfigError, ServerView, apply_presets, preset_catalog
from .containers import _fresh, collect_containers, collect_host, container_signals, forget_container, safe_name
from . import backup as backup_mod
from . import grafana as grafana_links
from .demo import DemoProm, seed_demo
from .digest import DigestScheduler
from .engine import Engine, classify
from .slo import SloEngine, is_applicable
from .format import build_event
from .github import GithubDeploys
from .notifiers import CHANNEL_FIELDS, Notifier, mask_settings
from .prom import Prom, PromError, PromUnavailable, series_key, series_label
from .legacy_presets import SHIPPED_IN_0_1_0
from .schemas import ChannelIn, RuleIn, UserIn, UserPatch, rule_problem
from .store import Store
from . import templates as msg_templates

log = logging.getLogger("nigrani.api")
RANGES = {"15m": 900, "1h": 3600, "3h": 10800, "6h": 21600, "24h": 86400, "7d": 604800}
MASK = "••••"


def _window(range_: str) -> tuple[float, float, float]:
    secs = RANGES.get(range_)
    if not secs:
        raise HTTPException(400, f"range must be one of {', '.join(RANGES)}")
    end = time.time()
    return end - secs, end, max(15, int(secs / 180))


def _last(points: list[list]) -> float | None:
    for _, v in reversed(points):
        if v is not None:
            return v
    return None


def _prom_guard(e: PromError) -> HTTPException:
    code = 502 if isinstance(e, PromUnavailable) else 400
    return HTTPException(code, str(e))




class PreviewIn(BaseModel):
    title_template: str | None = None
    body_template: str | None = None
    kind: Literal["firing", "resolved", "escalated", "reminder"] = "firing"


class AckIn(BaseModel):
    hours: float | None = Field(None, gt=0, le=24 * 30)   # None = until the incident resolves
    note: str = Field("", max_length=300)


class SilenceIn(BaseModel):
    server: str | None = None
    source_id: str | None = None
    match: str | None = None
    minutes: int = Field(60, ge=1, le=60 * 24 * 30)
    reason: str = ""


class AiRuleIn(BaseModel):
    description: str = Field(min_length=3, max_length=600)


class AnnouncementIn(BaseModel):
    kind: Literal["incident", "maintenance", "info"] = "info"
    title: str = Field(min_length=1, max_length=120)
    body: str = Field("", max_length=2000)
    starts_at: float | None = None      # default: now (a future time schedules it)
    ends_at: float | None = None


class LoginIn(BaseModel):
    username: str
    password: str


@dataclass
class Runtime:
    """Everything that belongs to one monitored server."""
    view: ServerView
    prom: Prom
    checks: CheckRunner
    github: GithubDeploys


def create_app(cfg: Config, prom: "Prom | dict[str, Prom] | None" = None,
               loki: "dict[str, Prom] | None" = None, sentry: "dict[str, Any] | None" = None,
               cloudwatch: "dict[str, Any] | None" = None, kubernetes: "dict[str, Any] | None" = None,
               datadog: "dict[str, Any] | None" = None, azure: "dict[str, Any] | None" = None, argocd: "dict[str, Any] | None" = None,
               ai: "Ai | None" = None) -> FastAPI:
    allow_no_auth = os.environ.get("NIGRANI_ALLOW_NO_AUTH") == "1"
    if not cfg.auth.password and not allow_no_auth and not cfg.demo:
        raise ConfigError("auth.password is empty. Set NIGRANI_PASSWORD (NIGRANI_ALLOW_NO_AUTH=1 is for local dev only).")

    store = Store(str(Path(cfg.data_dir) / "nigrani.db"))
    # Presets switched on from the UI (Discover) live in the database; the config file's own presets are the base.
    base_items = (list(cfg.tiles), list(cfg.pages), list(cfg.rules))
    file_presets = list(cfg.presets)
    known_presets = {c["name"] for c in preset_catalog()}

    def extra_presets() -> list[str]:
        return [n for n in (store.kv_get("presets:extra") or []) if n in known_presets and n not in file_presets]

    apply_presets(cfg, base_items, extra_presets())
    views = cfg.server_views()
    if isinstance(prom, dict):
        proms = prom
    elif prom is not None:
        proms = {views[0].id: prom}
    elif cfg.demo:
        proms = {v.id: DemoProm() for v in views}
    else:
        proms = {v.id: Prom(v.datasources.prometheus, v.datasources.timeout) for v in views}
    ai_client = ai if ai is not None else (Ai(cfg.ai, demo=cfg.demo and not cfg.ai.api_key) if (cfg.ai.enabled or cfg.demo) else None)
    notifier = Notifier(store, cfg.app.timezone)
    # Loki answers metric LogQL (rate / count_over_time) in the same shape as Prometheus, under /loki, so the same
    # client serves log-based alert rules.
    lokis = loki if loki is not None else {
        v.id: Prom(v.datasources.loki.rstrip("/") + "/loki", v.datasources.timeout) for v in views if v.datasources.loki}
    sentries = sentry if sentry is not None else {v.id: Sentry(v.sentry, v.datasources.timeout) for v in views if v.sentry.enabled}
    clouds = cloudwatch if cloudwatch is not None else {v.id: CloudWatch(v.cloudwatch, v.datasources.timeout) for v in views if v.cloudwatch.enabled}
    kubes = kubernetes if kubernetes is not None else {v.id: Kubernetes(v.kubernetes, v.datasources.timeout) for v in views if v.kubernetes.enabled}
    dogs = datadog if datadog is not None else {v.id: Datadog(v.datadog, v.datasources.timeout) for v in views if v.datadog.enabled}
    azures = azure if azure is not None else {v.id: Azure(v.azure, v.datasources.timeout) for v in views if v.azure.enabled}
    argos = argocd if argocd is not None else {v.id: ArgoCD(v.argocd, v.datasources.timeout) for v in views if v.argocd.enabled}
    engine = Engine(store, proms, notifier, cfg, lokis=lokis, sentries=sentries, clouds=clouds, kubes=kubes, dogs=dogs, azures=azures, argos=argos)

    def datasources_available() -> set[str]:
        return {"prometheus"} | ({"loki"} if lokis else set()) | ({"sentry"} if sentries else set()) | ({"cloudwatch"} if clouds else set()) | ({"kubernetes"} if kubes else set()) | ({"datadog"} if dogs else set()) | ({"azure"} if azures else set()) | ({"argocd"} if argos else set())

    def client_for(datasource: str, server_id: str, prom: Any) -> Any:
        return {"loki": lokis, "sentry": sentries, "cloudwatch": clouds, "kubernetes": kubes, "datadog": dogs, "azure": azures, "argocd": argos}.get(datasource, {server_id: prom}).get(server_id)
    runtimes: dict[str, Runtime] = {
        v.id: Runtime(v, proms[v.id], CheckRunner(cfg, store, engine, v), GithubDeploys(v.github))
        for v in views if v.id in proms
    }
    default_id = next(iter(runtimes))
    slo_engine = SloEngine(cfg, store, engine, runtimes)
    digest = DigestScheduler(cfg, store, [(rt.view, rt.prom) for rt in runtimes.values()], notifier)
    auth = Auth(cfg.auth.username, cfg.auth.password, cfg.auth.secret or os.environ.get("NIGRANI_SECRET", ""),
                cfg.auth.session_hours, enabled=bool(cfg.auth.password), store=store)
    authorize = make_authorizer(auth)
    oidc = Oidc(cfg.auth.oidc, cfg.app.public_url.rstrip("/") + "/api/auth/oidc/callback") if cfg.auth.oidc else None
    avail_cache: dict[tuple[str, str], tuple[float, bool]] = {}

    def srv(server: str | None = Query(None)) -> Runtime:
        rt = runtimes.get(server or default_id)
        if rt is None:
            raise HTTPException(404, f"unknown server '{server}'")
        return rt

    def _check_servers(ids: list[str]) -> None:
        bad = [i for i in ids if i not in runtimes]
        if bad:
            raise HTTPException(422, f"unknown server(s): {', '.join(bad)}")

    def seed() -> None:
        ids = {r.id for r in cfg.rules}
        for r in store.list_rules():
            if r["source"] == "preset" and r["id"] not in ids:
                engine.drop_rule(r["id"])
                store.delete_rule(r["id"])
        for r in cfg.rules:
            if store.sync_preset_rule(r.model_dump(), SHIPPED_IN_0_1_0) == "updated":
                log.info("preset rule %s was updated to the version shipped with this release", r.id)
        for rid in cfg.disable.get("rules", []):
            r = store.get_rule(rid)
            if r and r["enabled"]:
                store.save_rule({**r, "enabled": False})
        for c in cfg.channels:
            store.seed_channel(c.model_dump())
        if cfg.demo:
            seed_demo(store, views)

    async def containers_loop(rt: Runtime) -> None:
        while True:
            try:
                cs = await collect_containers(rt.prom, cfg, store, rt.view.services, rt.view.id)
                await engine.sync_external("svc:", container_signals(cs), server=rt.view.id)
            except PromError:
                pass
            except Exception:  # noqa: BLE001
                log.exception("container sync failed")
            await asyncio.sleep(30)

    async def housekeeping() -> None:
        while True:
            store.prune(cfg.retention_days)
            await asyncio.sleep(86400)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        seed()
        coros = [engine.run(), digest.run(), housekeeping(), slo_engine.run()]
        for rt in runtimes.values():
            coros += [rt.checks.run(), containers_loop(rt)]
        tasks = [asyncio.create_task(t) for t in coros]
        yield
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for p in [*proms.values(), *lokis.values(), *sentries.values(), *clouds.values(), *kubes.values(), *dogs.values(), *azures.values(), *argos.values()]:
            await p.close()

    app = FastAPI(title="Nigrani", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.engine, app.state.cfg, app.state.runtimes = store, engine, cfg, runtimes
    app.state.auth, app.state.oidc, app.state.slo = auth, oidc, slo_engine

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    DEMO_WRITES_OK = re.compile(r"^/api/(login|logout|rules/test|channels/preview|ai/rule|incidents/\d+/explain)$")

    @app.middleware("http")
    async def demo_read_only(request: Request, call_next):
        """The demo can be hosted publicly: nobody may change it (or make it send anything)."""
        if cfg.demo and request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/") \
                and not DEMO_WRITES_OK.match(request.url.path):
            return JSONResponse({"detail": "This is a read-only demo. Run your own Nigrani to change things."}, status_code=403)
        return await call_next(request)

    AUDIT_LABELS = [
        ("POST", r"^/api/rules$", "rule.create"), ("PUT", r"^/api/rules/[^/]+$", "rule.update"),
        ("DELETE", r"^/api/rules/[^/]+$", "rule.delete"), ("POST", r"^/api/channels$", "channel.save"),
        ("DELETE", r"^/api/channels/[^/]+$", "channel.delete"), ("POST", r"^/api/channels/[^/]+/test$", "channel.test"),
        ("POST", r"^/api/silences$", "silence.create"), ("DELETE", r"^/api/silences/\d+$", "silence.delete"),
        ("POST", r"^/api/incidents/\d+/ack$", "incident.ack"), ("DELETE", r"^/api/incidents/\d+/ack$", "incident.unack"),
        ("POST", r"^/api/digest/send$", "digest.send"), ("GET", r"^/api/backup$", "backup.export"),
        ("POST", r"^/api/backup/import$", "backup.import"), ("POST", r"^/api/users$", "user.create"),
        ("PUT", r"^/api/users/\d+$", "user.update"), ("DELETE", r"^/api/users/\d+$", "user.delete"),
        ("DELETE", r"^/api/containers/.+$", "container.forget"),
        ("POST", r"^/api/discovery/[a-z0-9_-]+/enable$", "preset.enable"), ("DELETE", r"^/api/discovery/[a-z0-9_-]+$", "preset.disable"),
        ("POST", r"^/api/incidents/\d+/explain$", "ai.explain"), ("POST", r"^/api/ai/rule$", "ai.rule"),
        ("POST", r"^/api/announcements$", "announcement.create"), ("POST", r"^/api/announcements/\d+/resolve$", "announcement.resolve"),
        ("DELETE", r"^/api/announcements/\d+$", "announcement.delete"),
    ]
    NOT_AUDITED = {"/api/rules/test", "/api/channels/preview", "/api/login", "/api/logout"}

    @app.middleware("http")
    async def audit_log(request: Request, call_next):
        resp = await call_next(request)
        path, method = request.url.path, request.method
        label = next((l for m, rx, l in AUDIT_LABELS if m == method and re.match(rx, path)), None)
        if (label is None and method in ("GET", "HEAD", "OPTIONS")) or not path.startswith("/api/") or path in NOT_AUDITED:
            return resp
        if path == "/api/backup/import" and request.query_params.get("dry_run", "true").lower() != "false":
            return resp                                           # a dry run changes nothing
        who = getattr(request.state, "identity", None)
        if resp.status_code == 401 or who is None:
            return resp
        denied = resp.status_code == 403
        detail = getattr(request.state, "audit_detail", "")
        store.add_audit(who.username, ("denied: " if denied else "") + (label or f"{method} {path}"), detail,
                        request.client.host if request.client else "", resp.status_code)
        return resp

    api = APIRouter(prefix="/api")
    secured = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    # ---------------- public ----------------
    @api.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @api.post("/login")
    async def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
        ip = request.client.host if request.client else "?"
        if auth.throttled(ip):
            raise HTTPException(429, "too many failed attempts, try again in a few minutes")
        who = auth.login(ip, body.username, body.password)
        if not who:
            store.add_audit(body.username[:100], "login.failed", ip=ip, status=401)
            raise HTTPException(401, "wrong username or password")
        store.add_audit(who.username, "login", ip=ip, status=200)
        response.set_cookie(COOKIE, auth.make_token(who.username, who.provider), max_age=auth.ttl, httponly=True,
                            samesite="lax", secure=request.url.scheme == "https")
        return {"user": who.username, "role": who.role}

    @api.post("/logout")
    async def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @api.get("/me")
    async def me(request: Request) -> dict[str, Any]:
        who = auth.identity_from(request)
        if not who:
            raise HTTPException(401, "not authenticated")
        return {
            "user": who.username, "name": who.name, "role": who.role, "provider": who.provider,
            "can": {"edit": who.can("editor"), "admin": who.can("admin")}, "app": cfg.app.name, "environment": cfg.app.environment, "version": __version__,
            "default_server": default_id, "ai": ai_client is not None, "demo": cfg.demo,
            "servers": [{"id": rt.view.id, "name": rt.view.name, "environment": rt.view.environment,
                         "logs": bool(rt.view.datasources.loki), "deploys": rt.github.enabled or rt.view.id in argos, "argocd": rt.view.id in argos, "slo": any(is_applicable(x, rt.view.id) for x in cfg.slos),
                         "grafana": bool(rt.view.grafana.url), "sentry": rt.view.id in sentries, "kubernetes": rt.view.id in kubes, "datadog": rt.view.id in dogs,
                         "datasources": ["prometheus"] + (["loki"] if rt.view.id in lokis else []) + (["sentry"] if rt.view.id in sentries else []) + (["cloudwatch"] if rt.view.id in clouds else []) + (["kubernetes"] if rt.view.id in kubes else []) + (["datadog"] if rt.view.id in dogs else []) + (["azure"] if rt.view.id in azures else []) + (["argocd"] if rt.view.id in argos else []),
                         "checks": bool(rt.view.checks)} for rt in runtimes.values()],
            "features": {"logs": any(rt.view.datasources.loki for rt in runtimes.values()),
                         "deploys": any(rt.github.enabled or rt.view.id in argos for rt in runtimes.values()),
                         "checks": any(rt.view.checks for rt in runtimes.values()),
                         "digest": cfg.digest.enabled, "auth": auth.enabled, "multi": len(runtimes) > 1},
        }

    # ---------------- single sign-on ----------------
    SSO_COOKIE = "nigrani_oidc"

    def _sso_failure(message: str, request: Request) -> RedirectResponse:
        resp = RedirectResponse("/?" + urlencode({"sso_error": message}), status_code=302)
        resp.delete_cookie(SSO_COOKIE)
        store.add_audit("-", "login.sso_failed", message, request.client.host if request.client else "", 403)
        return resp

    @api.get("/auth/config")
    async def auth_config() -> dict[str, Any]:
        return {"oidc": {"label": cfg.auth.oidc.label, "login_url": "/api/auth/oidc/login"} if oidc and cfg.auth.oidc else None}

    @api.get("/auth/oidc/login")
    async def oidc_login(request: Request):
        if not oidc:
            raise HTTPException(404, "single sign-on is not configured")
        state, nonce, verifier = new_login()
        try:
            url = await oidc.authorize_url(state, nonce, verifier)
        except OidcError as e:
            return _sso_failure(str(e), request)
        resp = RedirectResponse(url, status_code=302)
        resp.set_cookie(SSO_COOKIE, auth.sign_blob({"s": state, "n": nonce, "v": verifier}, 600), max_age=600,
                        httponly=True, samesite="lax", secure=request.url.scheme == "https")
        return resp

    @api.get("/auth/oidc/callback")
    async def oidc_callback(request: Request, code: str = "", state: str = "", error: str = ""):
        if not oidc:
            raise HTTPException(404, "single sign-on is not configured")
        pending = auth.read_blob(request.cookies.get(SSO_COOKIE))
        if error:
            return _sso_failure(f"the provider refused the sign-in ({error})", request)
        if not pending or not state or state != pending.get("s") or not code:
            return _sso_failure("the sign-in attempt expired or did not start here; please try again", request)
        try:
            claims = await oidc.finish(code, pending["v"], pending["n"])
        except OidcError as e:
            return _sso_failure(str(e), request)
        email = claims["email"].lower()
        if not oidc.allowed(email):
            return _sso_failure(f"{email} is not allowed to sign in here", request)
        user = store.get_user_by_name(email)
        if user and user["provider"] != "oidc":
            return _sso_failure(f"an account named {email} already exists with a password", request)
        if user and user["disabled"]:
            return _sso_failure("this account is disabled", request)
        if not user:
            user = store.create_user(username=email, name=claims.get("name") or email, email=email,
                                     role=oidc.role_for_new_user(email), provider="oidc")
        store.touch_login(user["id"])
        store.add_audit(user["username"], "login.sso", ip=request.client.host if request.client else "", status=200)
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie(COOKIE, auth.make_token(user["username"], "oidc"), max_age=auth.ttl, httponly=True,
                        samesite="lax", secure=request.url.scheme == "https")
        resp.delete_cookie(SSO_COOKIE)
        return resp

    def _announcement(a: dict[str, Any], now: float) -> dict[str, Any]:
        state = "resolved" if a["resolved_at"] else "scheduled" if a["starts_at"] > now else \
            "completed" if a["ends_at"] and a["ends_at"] < now else "active"
        return {"id": a["id"], "kind": a["kind"], "title": a["title"], "body": a["body"], "state": state,
                "starts_at": a["starts_at"], "ends_at": a["ends_at"], "resolved_at": a["resolved_at"]}

    def _day_bars(rid: str, days: int, now: float) -> list[dict[str, Any]]:
        """One entry per UTC day, oldest first: uptime % that day, or None when nothing was checked."""
        have = {d["day"]: d for d in store.check_days(rid, now - days * 86400)}
        out = []
        for n in range(days - 1, -1, -1):
            day = time.strftime("%Y-%m-%d", time.gmtime(now - n * 86400))
            d = have.get(day)
            out.append({"day": day, "pct": (d["up"] / d["total"] * 100) if d and d["total"] else None})
        return out

    @api.get("/public/status")
    async def public_status() -> dict[str, Any]:
        if not cfg.status_page.enabled:
            raise HTTPException(404, "status page disabled")
        now = time.time()
        multi = len(runtimes) > 1
        days = cfg.status_page.days
        check_rows = []
        for rt in runtimes.values():
            for c in rt.checks.summary():
                name = f"{rt.view.name} · {c['name']}" if multi else c["name"]
                bars = _day_bars(result_id(rt.view.id, c["id"]), days, now)
                known = [b["pct"] for b in bars if b["pct"] is not None]
                check_rows.append({"name": name, "ok": c["ok"], "uptime_30d": c["uptime_30d"], "days": bars,
                                   "uptime_period": (sum(known) / len(known)) if known else None})
        # Only uptime-check incidents are public: internal rule names (disks, containers...) stay private.
        public = [i for i in store.recent_incidents(100, now - 7 * 86400) if i["source_id"].startswith("check:")]
        notes = [_announcement(a, now) for a in store.list_announcements(now - 7 * 86400)]
        failing = [c for c in check_rows if c["ok"] is False]
        maintenance = any(n["kind"] == "maintenance" and n["state"] == "active" for n in notes)
        return {
            "title": cfg.status_page.title, "name": cfg.app.name, "period_days": days,
            "status": "major" if failing else "maintenance" if maintenance else "operational",
            "checks": check_rows,
            "announcements": [n for n in notes if n["state"] != "completed" or n["resolved_at"] is None],
            "incidents": [{"rule": i["rule_name"].removeprefix("Check failing: "), "severity": i["severity"],
                           "started_at": i["started_at"], "resolved_at": i["resolved_at"]} for i in public[:20]],
        }

    @secured.get("/announcements")
    async def list_announcements() -> list[dict[str, Any]]:
        now = time.time()
        return [_announcement(a, now) for a in store.list_announcements(now - 7 * 86400)]

    @secured.post("/announcements")
    async def add_announcement(body: AnnouncementIn, who: Identity = Depends(authorize)) -> dict[str, Any]:
        now = time.time()
        start = body.starts_at if body.starts_at is not None else now
        if body.ends_at is not None and body.ends_at <= start:
            raise HTTPException(422, "ends_at must be after starts_at")
        aid = store.add_announcement(kind=body.kind, title=body.title.strip(), body=body.body.strip(), starts_at=start,
                                     ends_at=body.ends_at, by=who.username, now=now)
        return _announcement(store.get_announcement(aid) or {}, now)

    @secured.post("/announcements/{announcement_id}/resolve")
    async def resolve_announcement(announcement_id: int) -> dict[str, Any]:
        if not store.get_announcement(announcement_id):
            raise HTTPException(404, "unknown announcement")
        store.resolve_announcement(announcement_id, time.time())
        return _announcement(store.get_announcement(announcement_id) or {}, time.time())

    @secured.delete("/announcements/{announcement_id}")
    async def delete_announcement(announcement_id: int) -> dict[str, bool]:
        store.delete_announcement(announcement_id)
        return {"ok": True}

    # ---------------- overview ----------------
    async def _overview(rt: Runtime) -> dict[str, Any]:
        prom = rt.prom
        now = time.time()
        prom_ok = await prom.healthy()

        async def tile(t) -> dict[str, Any]:
            base = {"id": t.id, "title": t.title, "unit": t.unit, "warn": t.warn, "crit": t.crit,
                    "direction": t.direction, "description": t.description, "value": None, "spark": [],
                    "status": "nodata", "error": None}
            try:
                res = await prom.range(t.query, now - 3600, now, 60)
            except PromError as e:
                return {**base, "error": str(e)}
            if not res:
                return base
            pick = (max if t.direction == "above" else min)(res, key=lambda r: _last(r["points"]) or 0)
            v = _last(pick["points"])
            sev = classify(v, t.direction, t.warn, t.crit)[0] if v is not None else None
            return {**base, "value": v, "spark": pick["points"],
                    "status": "nodata" if v is None else {"critical": "crit", "warning": "warn", None: "ok"}[sev]}

        tiles = list(await asyncio.gather(*(tile(t) for t in cfg.tiles)))

        cont: dict[str, Any] | None = None
        try:
            cs = await collect_containers(prom, cfg, store, rt.view.services, rt.view.id)
            cont = {"up": sum(1 for c in cs if c["up"]), "total": len(cs),
                    "down": [c["service"] or c["name"] for c in cs if not c["up"]]}
        except PromError:
            pass

        open_inc = [i for i in store.open_incidents() if i["server"] == rt.view.id]
        crit = sum(1 for i in open_inc if i["severity"] == "critical")
        warn = len(open_inc) - crit
        if not prom_ok:
            banner = {"status": "unknown", "title": "Can't reach Prometheus",
                      "detail": prom.last_error or "Metrics are unavailable, so health can't be determined."}
        elif crit:
            banner = {"status": "major", "title": f"{crit} critical issue{'s' if crit != 1 else ''}",
                      "detail": ", ".join(sorted({i['rule_name'] for i in open_inc if i['severity'] == 'critical'}))}
        elif warn:
            banner = {"status": "degraded", "title": f"{warn} warning{'s' if warn != 1 else ''}",
                      "detail": ", ".join(sorted({i['rule_name'] for i in open_inc}))}
        else:
            banner = {"status": "operational", "title": "All systems operational",
                      "detail": "No active alerts."}
        chk = rt.checks.summary()
        ups = [c["uptime_30d"] for c in chk if c["uptime_30d"] is not None]
        return {
            "server": {"id": rt.view.id, "name": rt.view.name, "environment": rt.view.environment},
            "banner": banner, "tiles": tiles, "containers": cont, "incidents": open_inc[:8],
            "incident_counts": {"critical": crit, "warning": warn},
            "checks": chk, "uptime_30d": (sum(ups) / len(ups)) if ups else None,
            "prometheus": {"ok": prom_ok, "error": prom.last_error}, "generated_at": now,
        }

    @secured.get("/overview")
    async def overview(rt: Runtime = Depends(srv)) -> dict[str, Any]:
        return await _overview(rt)

    @secured.get("/fleet")
    async def fleet() -> list[dict[str, Any]]:
        """Every server's overview at once, for the all-servers screen."""
        return list(await asyncio.gather(*(_overview(rt) for rt in runtimes.values())))

    # ---------------- containers / host ----------------
    @secured.get("/containers")
    async def containers(rt: Runtime = Depends(srv)) -> list[dict[str, Any]]:
        try:
            return await collect_containers(rt.prom, cfg, store, rt.view.services, rt.view.id)
        except PromError as e:
            raise _prom_guard(e) from e

    @secured.get("/containers/{name:path}/metrics")
    async def container_metrics(name: str, range: str = "1h", rt: Runtime = Depends(srv)) -> dict[str, Any]:
        try:
            name = safe_name(name)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        start, end, step = _window(range)
        sel = f'{cfg.containers.label}="{name}"'
        fresh = _fresh(sel, cfg.containers.stale_seconds)  # ignore stale series left by an earlier container of the same name
        qs = {
            "cpu": f"sum(rate(container_cpu_usage_seconds_total{{{sel}}}[2m]) and on (id) {fresh}) * 100",
            "mem": f"max(container_memory_working_set_bytes{{{sel}}} and on (id) {fresh})",
            "rx": f"sum(rate(container_network_receive_bytes_total{{{sel}}}[2m]) and on (id) {fresh})",
            "tx": f"sum(rate(container_network_transmit_bytes_total{{{sel}}}[2m]) and on (id) {fresh})",
        }
        try:
            res = await asyncio.gather(*(rt.prom.range(q, start, end, step) for q in qs.values()))
        except PromError as e:
            raise _prom_guard(e) from e
        return {k: (r[0]["points"] if r else []) for k, r in zip(qs, res)}

    @secured.delete("/containers/{name:path}")
    async def forget(name: str, rt: Runtime = Depends(srv)) -> dict[str, bool]:
        await forget_container(store, name, rt.view.id)
        return {"ok": True}

    @secured.get("/host")
    async def host(range: str = "1h", rt: Runtime = Depends(srv)) -> dict[str, Any]:
        start, end, step = _window(range)
        try:
            return await collect_host(rt.prom, cfg, start, end, step)
        except PromError as e:
            raise _prom_guard(e) from e

    # ---------------- discovery: which presets the metrics say you could use ----------------
    @secured.get("/discovery")
    async def discovery(rt: Runtime = Depends(srv)) -> dict[str, Any]:
        """Looks at the metric names in Prometheus and says which built-in dashboards and alert sets would work."""
        extra = extra_presets()
        error = None
        try:
            seen = set(await rt.prom.metric_names())
        except PromError:
            seen, error = set(), "Prometheus is not reachable, so nothing can be detected right now."
        out = []
        for c in preset_catalog():
            origin = "config" if c["name"] in file_presets else "ui" if c["name"] in extra else None
            found = all(m in seen for m in c["detect"])
            out.append({**c, "origin": origin, "status": "enabled" if origin else "found" if found else "missing"})
        rank = {"found": 0, "enabled": 1, "missing": 2}
        return {"presets": sorted(out, key=lambda x: rank[x["status"]]), "error": error}

    @secured.post("/discovery/{name}/enable")
    async def enable_preset(name: str) -> dict[str, Any]:
        if name not in known_presets:
            raise HTTPException(404, "unknown preset")
        if name in file_presets:
            raise HTTPException(409, "already enabled in the config file")
        names = extra_presets()
        if name not in names:
            names.append(name)
        store.kv_set("presets:extra", names)
        apply_presets(cfg, base_items, names)
        seed()                                            # the preset's alert rules join the engine's next cycle
        return {"ok": True, "enabled": names}

    @secured.delete("/discovery/{name}")
    async def disable_preset(name: str) -> dict[str, Any]:
        if name not in known_presets:
            raise HTTPException(404, "unknown preset")
        if name in file_presets:
            raise HTTPException(409, "enabled in the config file: remove it from `presets:` there")
        names = [n for n in extra_presets() if n != name]
        store.kv_set("presets:extra", names)
        apply_presets(cfg, base_items, names)
        seed()                                            # its rules are removed (a firing alert resolves)
        return {"ok": True, "enabled": names}

    # ---------------- dashboard pages (preset / user defined) ----------------
    async def _available(rt: Runtime, metric: str) -> bool:
        if not metric:
            return True
        hit = avail_cache.get((rt.view.id, metric))
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        ok = await rt.prom.has_metric(metric)
        avail_cache[(rt.view.id, metric)] = (time.time(), ok)
        return ok

    @secured.get("/pages")
    async def pages(rt: Runtime = Depends(srv)) -> list[dict[str, Any]]:
        oks = await asyncio.gather(*(_available(rt, p.requires) for p in cfg.pages))
        return [{"id": p.id, "title": p.title, "icon": p.icon, "available": ok, "hint": p.hint, "requires": p.requires}
                for p, ok in zip(cfg.pages, oks)]

    @secured.get("/pages/{page_id}")
    async def page(page_id: str, range: str = "1h", rt: Runtime = Depends(srv)) -> dict[str, Any]:
        p = next((x for x in cfg.pages if x.id == page_id), None)
        if not p:
            raise HTTPException(404, "unknown page")
        start, end, step = _window(range)
        available = await _available(rt, p.requires)

        async def panel(pn) -> dict[str, Any]:
            out: dict[str, Any] = {"title": pn.title, "unit": pn.unit, "kind": pn.kind, "wide": pn.wide,
                                   "description": pn.description, "series": [], "error": None}
            try:
                results = await asyncio.gather(*(rt.prom.range(q.expr, start, end, step) for q in pn.queries))
            except PromError as e:
                out["error"] = str(e)
                return out
            series = []
            for q, res in zip(pn.queries, results):
                for r in res:
                    name = q.legend
                    if name:
                        name = re.sub(r"\{(\w+)\}", lambda m: r["labels"].get(m.group(1), ""), name)
                    series.append({"name": name or series_label(r["labels"]) or pn.title, "points": r["points"]})
            series.sort(key=lambda s: -(_last(s["points"]) or 0))
            out["series"] = series[: pn.max_series]
            if pn.kind == "stat" and series:
                out["value"] = _last(series[0]["points"])
            return out

        panels = await asyncio.gather(*(panel(pn) for pn in p.panels)) if available else []
        return {"id": p.id, "title": p.title, "available": available, "hint": p.hint, "requires": p.requires,
                "panels": panels}

    # ---------------- alerts ----------------
    @secured.get("/rules")
    async def list_rules() -> list[dict[str, Any]]:
        return [{**r, "error": engine.rule_error(r["id"])} for r in store.list_rules()]

    def _validate_rule(r: RuleIn) -> None:
        _check_servers(r.servers)
        if r.datasource not in datasources_available():
            raise HTTPException(422, f"no server has {r.datasource} configured, so this rule can't be evaluated")
        problem = rule_problem(r)
        if problem:
            raise HTTPException(422, problem)

    @secured.post("/rules")
    async def create_rule(r: RuleIn, request: Request) -> dict[str, Any]:
        request.state.audit_detail = r.name
        _validate_rule(r)
        rid = r.id or re.sub(r"[^a-z0-9]+", "-", r.name.lower()).strip("-")[:60] or "rule"
        if store.get_rule(rid):
            rid = f"{rid}-{int(time.time()) % 100000}"
        return store.save_rule({**r.model_dump(), "id": rid, "source": "custom"})

    @secured.put("/rules/{rule_id}")
    async def update_rule(rule_id: str, r: RuleIn, request: Request) -> dict[str, Any]:
        request.state.audit_detail = f"{rule_id}: {r.name}"
        old = store.get_rule(rule_id)
        if not old:
            raise HTTPException(404, "unknown rule")
        _validate_rule(r)
        if not r.enabled:
            engine.drop_rule(rule_id)
        return store.save_rule({**r.model_dump(), "id": rule_id, "source": old["source"]})

    @secured.delete("/rules/{rule_id}")
    async def delete_rule(rule_id: str, request: Request) -> dict[str, bool]:
        request.state.audit_detail = rule_id
        engine.drop_rule(rule_id)
        store.delete_rule(rule_id)
        return {"ok": True}

    @secured.post("/rules/test")
    async def test_rule(r: RuleIn, rt: Runtime = Depends(srv)) -> dict[str, Any]:
        client = client_for(r.datasource, rt.view.id, rt.prom)
        if client is None:
            raise HTTPException(400, f"{rt.view.name} has no {r.datasource} configured")
        try:
            res = await client.instant(r.expr)
        except PromError as e:
            raise _prom_guard(e) from e
        rows = []
        for s in res[:50]:
            if s["value"] is None:
                continue
            sev, _ = classify(s["value"], r.direction, r.warn, r.crit)
            rows.append({"series": series_label(s["labels"]), "value": s["value"], "severity": sev})
        return {"count": len(res), "series": rows}

    @secured.get("/incidents")
    async def incidents(status: str = "all", limit: int = Query(100, le=500), days: float = Query(7, gt=0, le=60),
                        server: str | None = None) -> list[dict]:
        rows = store.recent_incidents(limit, time.time() - days * 86400, server=server)
        if status in ("firing", "resolved"):
            rows = [i for i in rows if i["status"] == status]
        return rows

    @secured.get("/incidents/{incident_id}")
    async def incident_detail(incident_id: int) -> dict[str, Any]:
        """Everything around one alert: lifecycle, the metric behind it, deploys, restarts, related alerts."""
        inc = store.get_incident(incident_id)
        if not inc:
            raise HTTPException(404, "unknown incident")
        rt = runtimes.get(inc["server"]) or next(iter(runtimes.values()))
        now = time.time()
        end = min(now, (inc["resolved_at"] or now) + 600)
        start = min(inc["started_at"] - 1200, end - 1800)
        step = max(15, int((end - start) / 160))
        problems: list[str] = []
        out: dict[str, Any] = {
            "incident": inc, "events": store.list_events(incident_id), "window": {"start": start, "end": end},
            "chart": None, "container": None, "restarts": [], "deploys": [], "related": [], "problems": problems,
        }

        rule = store.get_rule(inc["source_id"])
        if rule:
            client = client_for(rule["datasource"], inc["server"], rt.prom)
            if client is not None and rule["datasource"] not in ("sentry", "kubernetes"):
                try:
                    res = await client.range(rule["expr"], start, end, step)
                    pick = [r for r in res if series_key(r["labels"]) == inc["series_key"]] or res[:3]
                    out["chart"] = {
                        "name": rule["name"], "unit": rule["unit"], "direction": rule["direction"],
                        "warn": rule["warn"], "crit": rule["crit"],
                        "series": [{"name": series_label(r["labels"]) or rule["name"], "points": r["points"]} for r in pick]}
                except PromError as e:
                    problems.append(f"metric: {e}")

        label = cfg.containers.label
        cname = inc["labels"].get(label) or inc["labels"].get(rt.view.datasources.loki_container_label)
        if cname and re.fullmatch(r"[A-Za-z0-9_.\-/]+", cname):
            sel = f'{label}="{cname}"'
            fresh = _fresh(sel, cfg.containers.stale_seconds)
            try:
                cpu, mem = await asyncio.gather(
                    rt.prom.range(f"sum(rate(container_cpu_usage_seconds_total{{{sel}}}[2m]) and on (id) {fresh}) * 100", start, end, step),
                    rt.prom.range(f"max(container_memory_working_set_bytes{{{sel}}} and on (id) {fresh})", start, end, step))
                if cpu or mem:
                    out["container"] = {"name": cname, "cpu": cpu[0]["points"] if cpu else [],
                                        "mem": mem[0]["points"] if mem else []}
            except PromError as e:
                problems.append(f"container metrics: {e}")

        try:   # containers that (re)started shortly before or during the incident
            started = await rt.prom.instant(
                f'max by ({label}) (container_start_time_seconds{{{label}!=""}}) > {int(start - 3600)}', at=end)
            # other containers only if they started close to the incident, so a pile of long-running containers
            # does not drown the one that matters
            restarts = [{"container": r["labels"].get(label, ""), "ts": r["value"]} for r in started
                        if r["value"] and r["labels"].get(label) != cname and r["value"] >= inc["started_at"] - 600]
            if cname and re.fullmatch(r"[A-Za-z0-9_.\-/]+", cname):
                # The incident's own container: docker restarts it in place, which cAdvisor reports as a new series per
                # RestartCount. The first sample of each series is when that restart happened.
                runs = await rt.prom.range(f'container_start_time_seconds{{{label}="{cname}"}}', start, end, step)
                runs = sorted((r for r in runs if r["points"]), key=lambda r: r["points"][0][0])
                for n, r in enumerate(runs):
                    if n == 0 and r["points"][0][0] <= start + 2 * step:
                        continue                             # already running when the window began
                    restarts.append({"container": cname, "ts": r["points"][0][0],
                                     "count": r["labels"].get("container_label_restartcount")})
            out["restarts"] = sorted(restarts, key=lambda x: x["ts"])[-30:]
        except PromError as e:
            problems.append(f"restarts: {e}")

        deploys_seen: list[dict[str, Any]] = []
        if rt.github.enabled:
            deploys_seen += await rt.github.runs()
        argo = argos.get(rt.view.id)
        if argo is not None:                       # Argo CD syncs are deploys too
            try:
                deploys_seen += await argo.deploys()
            except PromError as e:
                problems.append(f"argo cd: {e}")
        out["deploys"] = sorted((r for r in deploys_seen if r.get("finished_at") and start - 3600 <= r["finished_at"] <= end),
                                key=lambda r: r["finished_at"])

        g = rt.view.grafana
        out["grafana"] = {
            "explore": grafana_links.explore_url(g, rule["datasource"], rule["expr"], start, end) if rule else None,
            "links": grafana_links.dashboard_links(g, "incident", container=cname, server=rt.view.id,
                                                   rule=inc["rule_name"], series=inc["series"],
                                                   **{"from": start, "to": end}),
        }
        sent = sentries.get(inc["server"])
        if rule and rule["datasource"] == "sentry" and sent is not None:
            query = rule["expr"] + (f' project:{inc["labels"]["project"]}' if inc["labels"].get("project") else "")
            try:
                out["sentry"] = {"issues": await sent.issues(query, limit=10, sort="date"), "search_url": sent.search_url(query)}
            except PromError as e:
                problems.append(f"sentry: {e}")
        out["related"] = [
            {k: i[k] for k in ("id", "rule_name", "series", "severity", "status", "started_at", "resolved_at", "server")}
            for i in store.recent_incidents(200, inc["started_at"] - 900)
            if i["id"] != incident_id and i["started_at"] <= inc["started_at"] + 900][:10]
        return out

    @secured.post("/incidents/{incident_id}/ack")
    async def ack_incident(incident_id: int, body: AckIn, who: Identity = Depends(authorize)) -> dict[str, Any]:
        """"I'm on it": pause this incident's reminders and tell the channels once."""
        inc = await engine.acknowledge(incident_id, who.name or who.username, body.note.strip(), body.hours)
        if inc is None:
            raise HTTPException(409, "only a firing incident can be acknowledged")
        return inc

    @secured.delete("/incidents/{incident_id}/ack")
    async def unack_incident(incident_id: int) -> dict[str, Any]:
        inc = engine.unacknowledge(incident_id)
        if inc is None:
            raise HTTPException(409, "only a firing incident can be un-acknowledged")
        return inc

    # ---------------- AI assistant (optional) ----------------
    def _need_ai() -> Ai:
        if ai_client is None:
            raise HTTPException(404, "the AI assistant is not enabled (set ai.enabled and ai.api_key)")
        return ai_client

    @secured.get("/incidents/{incident_id}/explain")
    async def get_explanation(incident_id: int) -> dict[str, Any]:
        """The saved explanation, if someone already asked for one: viewers can read it without spending anything."""
        _need_ai()
        return store.kv_get(f"ai:incident:{incident_id}") or {"text": None}

    @secured.post("/incidents/{incident_id}/explain")
    async def explain_incident(incident_id: int, refresh: bool = False) -> dict[str, Any]:
        client = _need_ai()
        saved = store.kv_get(f"ai:incident:{incident_id}")
        if saved and not refresh:
            return saved
        detail = await incident_detail(incident_id)
        try:
            out = await client.explain(detail)
        except AiError as e:
            raise HTTPException(502, str(e)) from e
        store.kv_set(f"ai:incident:{incident_id}", out)
        return out

    @secured.post("/ai/rule")
    async def ai_rule(body: AiRuleIn, rt: Runtime = Depends(srv)) -> dict[str, Any]:
        """Turn a sentence into a draft rule, checked against the real data. Nothing is saved."""
        client = _need_ai()
        try:
            names = await rt.prom.metric_names()
        except (PromError, AttributeError):
            names = []
        try:
            draft = await client.draft_rule(body.description.strip(), names)
        except AiError as e:
            raise HTTPException(502, str(e)) from e
        try:
            rule = RuleIn(**{**draft, "datasource": "prometheus"})
        except Exception as e:  # noqa: BLE001 pydantic ValidationError: the model's draft broke the rule schema
            raise HTTPException(502, f"the model's draft is not a valid rule: {e}") from e
        problem = rule_problem(rule)
        preview: dict[str, Any] = {"count": None, "series": [], "error": None}
        try:
            res = await rt.prom.instant(rule.expr)
            rows = []
            for s_ in res[:20]:
                if s_["value"] is not None:
                    sev, _ = classify(s_["value"], rule.direction, rule.warn, rule.crit)
                    rows.append({"series": series_label(s_["labels"]), "value": s_["value"], "severity": sev})
            preview.update(count=len(res), series=rows)
        except PromError as e:
            # a fixed message: the details are one click away (Preview in the editor) and need not travel in this response
            preview["error"] = "Prometheus is not reachable" if isinstance(e, PromUnavailable) else "Prometheus rejected this query"
        return {"rule": rule.model_dump(exclude={"id", "datasource", "servers", "enabled"}), "problem": problem, "preview": preview}

    # ---------------- users and audit log (admin) ----------------
    def _admin_count(excluding: int | None = None) -> int:
        return sum(1 for u in store.list_users() if u["role"] == "admin" and not u["disabled"] and u["id"] != excluding)

    def _public_user(u: dict[str, Any]) -> dict[str, Any]:
        return {k: u[k] for k in ("id", "username", "name", "email", "role", "provider", "disabled", "has_password",
                                  "created_at", "last_login")}

    @secured.get("/users")
    async def list_users() -> list[dict[str, Any]]:
        config_admin = {"id": None, "username": cfg.auth.username, "name": cfg.auth.username, "email": None,
                        "role": "admin", "provider": "config", "disabled": False, "has_password": True,
                        "created_at": None, "last_login": None}
        return [config_admin, *[_public_user(u) for u in store.list_users()]]

    @secured.post("/users")
    async def create_user(body: UserIn, request: Request) -> dict[str, Any]:
        problem = password_problem(body.password)
        if problem:
            raise HTTPException(422, problem)
        if body.username.lower() == cfg.auth.username.lower() or store.get_user_by_name(body.username):
            raise HTTPException(409, "that username is taken")
        request.state.audit_detail = f"{body.username} as {body.role}"
        return _public_user(store.create_user(username=body.username, name=body.name, email=body.email, role=body.role,
                                              password_hash=hash_password(body.password)))

    @secured.put("/users/{user_id}")
    async def update_user(user_id: int, body: UserPatch, request: Request, who: Identity = Depends(authorize)) -> dict[str, Any]:
        user = store.get_user(user_id)
        if not user:
            raise HTTPException(404, "unknown user")
        fields: dict[str, Any] = {k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "password"}
        if body.password is not None:
            if user["provider"] != "local":
                raise HTTPException(422, "this account signs in through single sign-on; it has no password")
            problem = password_problem(body.password)
            if problem:
                raise HTTPException(422, problem)
            fields["password_hash"] = hash_password(body.password)
        if user["username"] == who.username and (fields.get("disabled") or fields.get("role", "admin") != "admin"):
            raise HTTPException(409, "you can't lock yourself out: ask another administrator")
        loses_admin = user["role"] == "admin" and (fields.get("disabled") or fields.get("role", "admin") != "admin")
        if loses_admin and _admin_count(excluding=user_id) == 0 and who.provider != "config":
            raise HTTPException(409, "this is the last administrator")
        request.state.audit_detail = f"{user['username']}: " + ", ".join(k for k in fields if k != "password_hash") + (
            ", password" if "password_hash" in fields else "")
        return _public_user(store.update_user(user_id, **fields))  # type: ignore[arg-type]

    @secured.delete("/users/{user_id}")
    async def delete_user(user_id: int, request: Request, who: Identity = Depends(authorize)) -> dict[str, bool]:
        user = store.get_user(user_id)
        if not user:
            raise HTTPException(404, "unknown user")
        if user["username"] == who.username:
            raise HTTPException(409, "you can't delete your own account")
        request.state.audit_detail = user["username"]
        store.delete_user(user_id)
        return {"ok": True}

    @secured.get("/audit")
    async def audit_list(limit: int = Query(200, ge=1, le=1000), user: str | None = None, days: float = Query(30, gt=0, le=365)) -> list[dict[str, Any]]:
        return store.list_audit(limit, user=user, since=time.time() - days * 86400)

    @secured.get("/silences")
    async def silences() -> list[dict[str, Any]]:
        return store.list_silences()

    @secured.post("/silences")
    async def add_silence(s: SilenceIn, request: Request) -> dict[str, int]:
        request.state.audit_detail = f"{s.source_id or 'all rules'} {s.match or ''} for {s.minutes} min".strip()
        _check_servers([s.server] if s.server else [])
        return {"id": store.add_silence(s.source_id, s.match, time.time() + s.minutes * 60, s.reason, s.server)}

    @secured.delete("/silences/{silence_id}")
    async def del_silence(silence_id: int) -> dict[str, bool]:
        store.delete_silence(silence_id)
        return {"ok": True}

    # ---------------- channels ----------------
    def _public_channel(c: dict[str, Any]) -> dict[str, Any]:
        return {**c, "settings": mask_settings(c["type"], c["settings"])}

    @secured.get("/channel-types")
    async def channel_types() -> dict[str, Any]:
        return CHANNEL_FIELDS

    @secured.get("/channels")
    async def channels() -> list[dict[str, Any]]:
        return [_public_channel(c) for c in store.list_channels()]

    @secured.post("/channels")
    async def save_channel(c: ChannelIn, request: Request) -> dict[str, Any]:
        request.state.audit_detail = f"{c.name} ({c.type})"
        _check_servers(c.servers)
        bad = msg_templates.validate(c.title_template, c.body_template)
        if bad:
            raise HTTPException(422, bad)
        cid = c.id or re.sub(r"[^a-z0-9]+", "-", c.name.lower()).strip("-")[:60] or "channel"
        if not c.id and store.get_channel(cid):
            cid = f"{cid}-{int(time.time()) % 100000}"
        old = store.get_channel(cid)
        settings = dict(c.settings)
        if old:  # keep stored secrets when the UI sends back the masked placeholder
            for k, v in settings.items():
                if isinstance(v, str) and v.startswith(MASK):
                    settings[k] = old["settings"].get(k, "")
        saved = store.save_channel({**c.model_dump(), "id": cid, "settings": settings})
        return _public_channel(saved)

    @secured.get("/message-placeholders")
    async def message_placeholders() -> list[dict[str, str]]:
        return [{"name": k, "description": v} for k, v in msg_templates.PLACEHOLDERS.items()]

    @secured.post("/channels/preview")
    async def preview_message(p: PreviewIn) -> dict[str, Any]:
        """Render the templates against a sample alert, so they can be checked before saving."""
        bad = msg_templates.validate(p.title_template, p.body_template)
        if bad:
            raise HTTPException(422, bad)
        now = time.time()
        multi = len(runtimes) > 1
        ev = build_event(
            p.kind, severity="critical", rule_name="High CPU", series="web-1", value=93.4, threshold=90.0,
            unit="percent", summary="Check which container is busy on the Containers page.", started_at=now - 540,
            now=now, environment=cfg.app.environment, link=cfg.app.public_url or "https://nigrani.example.com",
            server=next(iter(runtimes.values())).view.name if multi else "")
        out = msg_templates.apply({"title_template": p.title_template, "body_template": p.body_template}, ev)
        return {"title": out["title"], "body": out["body"]}

    @secured.delete("/channels/{channel_id}")
    async def delete_channel(channel_id: str, request: Request) -> dict[str, bool]:
        request.state.audit_detail = channel_id
        store.delete_channel(channel_id)
        return {"ok": True}

    @secured.post("/channels/{channel_id}/test")
    async def test_channel(channel_id: str) -> dict[str, Any]:
        ch = store.get_channel(channel_id)
        if not ch:
            raise HTTPException(404, "unknown channel")
        now = time.time()
        ev = build_event("test", severity="info", rule_name="Test", series="", value=None, threshold=None,
                         unit="short", summary="If you can read this, the channel works.", started_at=now, now=now,
                         environment=cfg.app.environment, link=cfg.app.public_url)
        ev["body"] = "If you can read this, the channel works."
        err = await notifier.send_to(ch, ev)
        return {"ok": err is None, "error": err}

    @secured.post("/digest/send")
    async def send_digest() -> dict[str, Any]:
        ev = await digest.send_now()
        return {"title": ev["title"], "body": ev["body"]}

    # ---------------- logs / deploys / checks ----------------
    @secured.get("/logs")
    async def logs(container: str = "", q: str = "", level: str = "", limit: int = Query(200, le=1000),
                   since: str = "1h", start: float | None = None, end: float | None = None,
                   rt: Runtime = Depends(srv)) -> dict[str, Any]:
        ds = rt.view.datasources
        if not ds.loki:
            raise HTTPException(404, "Loki is not configured (datasources.loki)")
        label = ds.loki_container_label
        if container:
            try:
                safe_name(container)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            selector = f'{{{label}="{container}"}}'
        else:
            selector = f'{{{label}=~".+"}}'
        query = selector
        if level == "error":
            query += ' |~ "(?i)(error|exception|traceback|critical|fatal)"'
        elif level == "warn":
            query += ' |~ "(?i)(warn|error|exception|traceback|critical|fatal)"'
        if q:
            query += " |= " + _logql_str(q)
        secs = RANGES.get(since, 3600)
        end_ts = end if (start is not None and end) else time.time()
        start_ts = start if start is not None else end_ts - secs
        try:
            async with httpx.AsyncClient(timeout=15) as cl:
                r = await cl.get(ds.loki.rstrip("/") + "/loki/api/v1/query_range", params={
                    "query": query, "limit": limit, "direction": "backward",
                    "start": int(start_ts * 1e9), "end": int(end_ts * 1e9)})
            r.raise_for_status()
            streams = r.json()["data"]["result"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise HTTPException(502, f"Loki error: {e}") from e
        rows = []
        for s in streams:
            for ts, line in s["values"]:
                rows.append({"ts": int(ts) / 1e9, "line": line, "container": s["stream"].get(label, "")})
        rows.sort(key=lambda x: -x["ts"])
        return {"query": query, "label": label, "rows": rows[:limit]}

    @secured.get("/deploys")
    async def deploys(rt: Runtime = Depends(srv)) -> dict[str, Any]:
        runs = list(await rt.github.runs())
        error = rt.github.error
        argo = argos.get(rt.view.id)
        if argo is not None:
            try:
                runs += await argo.deploys()
            except PromError:
                error = error or argo.last_error or "Argo CD could not be read"
        runs.sort(key=lambda r: -(r.get("finished_at") or r.get("started_at") or 0))
        return {"enabled": rt.github.enabled or argo is not None, "error": error, "runs": runs}

    # ---------------- backup / restore ----------------
    @secured.get("/backup")
    async def backup(request: Request, include_secrets: bool = False) -> JSONResponse:
        request.state.audit_detail = "including credentials" if include_secrets else "credentials left out"
        data = backup_mod.export_backup(store, include_secrets=include_secrets, app_version=__version__)
        name = f"nigrani-backup-{time.strftime('%Y%m%d')}.json"
        return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @secured.post("/backup/import")
    async def backup_import(request: Request, mode: Literal["merge", "overwrite"] = "merge", dry_run: bool = True):
        """Validate (dry_run=true, the default) or apply (dry_run=false) a backup. All-or-nothing: if anything in the
        file is invalid nothing is changed, and the problems are listed."""
        if int(request.headers.get("content-length") or 0) > 2_000_000:
            raise HTTPException(413, "backup file is too large")
        try:
            data = await request.json()
        except ValueError as e:
            raise HTTPException(400, "the file is not valid JSON") from e
        plan = backup_mod.plan_import(store, data, mode=mode, server_ids=set(runtimes), datasources=datasources_available())
        if dry_run:
            return plan.view()
        if plan.errors:
            return JSONResponse({**plan.view(), "applied": False}, status_code=422)
        backup_mod.apply_import(store, plan, preset_rule_ids={r.id for r in cfg.rules}, drop_rule=engine.drop_rule)
        request.state.audit_detail = f"{mode}: " + ", ".join(f"{k} {v['create']} new/{v['update']} replaced" for k, v in plan.summary().items())
        return {**plan.view(), "applied": True}

    @secured.get("/grafana-links")
    async def get_grafana_links(context: Literal["container", "host", "overview", "incident"] = "overview",
                                container: str = "", expr: str = "", datasource: Literal["prometheus", "loki"] = "prometheus",
                                minutes: int = Query(60, ge=1, le=10080), rt: Runtime = Depends(srv)) -> dict[str, Any]:
        """Links into Grafana for a place in the UI. `expr` also returns an Explore link for that query."""
        if container:
            try:
                safe_name(container)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
        g, now = rt.view.grafana, time.time()
        return {
            "enabled": bool(g.url),
            "explore": grafana_links.explore_url(g, datasource, expr, now - minutes * 60, now) if expr else None,
            "links": grafana_links.dashboard_links(g, context, container=container or None, server=rt.view.id,
                                                   **{"from": now - minutes * 60, "to": now}),
        }

    # ---------------- sentry ----------------
    def _sentry(rt: Runtime) -> Sentry:
        s = sentries.get(rt.view.id)
        if s is None:
            raise HTTPException(404, f"Sentry is not configured for {rt.view.name} (sentry.org and sentry.token)")
        return s

    @secured.get("/sentry/issues")
    async def sentry_issues(query: str = Query("is:unresolved", max_length=500), sort: str = "date",
                            limit: int = Query(25, ge=1, le=100), rt: Runtime = Depends(srv)) -> dict[str, Any]:
        s = _sentry(rt)
        if sort not in SENTRY_SORTS:
            raise HTTPException(400, f"sort must be one of {', '.join(SENTRY_SORTS)}")
        try:
            issues = await s.issues(query, limit=limit, sort=sort)
        except PromError as e:
            raise _prom_guard(e) from e
        return {"issues": issues, "search_url": s.search_url(query), "org": s.cfg.org, "projects": s.cfg.projects}

    @secured.get("/sentry/summary")
    async def sentry_summary(rt: Runtime = Depends(srv)) -> dict[str, Any]:
        s = _sentry(rt)
        queries = {"unresolved": "is:unresolved", "new_1h": "is:unresolved firstSeen:-1h",
                   "new_24h": "is:unresolved firstSeen:-24h", "fatal": "is:unresolved level:fatal"}
        try:
            results = await asyncio.gather(*(s.issues(q, limit=100) for q in queries.values()))
        except PromError as e:
            raise _prom_guard(e) from e
        return {k: {"count": len(r), "capped": len(r) >= 100} for k, r in zip(queries, results)}

    # ---------------- kubernetes ----------------
    @secured.get("/kubernetes")
    async def kubernetes_overview(namespace: str = Query("", max_length=100), rt: Runtime = Depends(srv)) -> dict[str, Any]:
        k = kubes.get(rt.view.id)
        if k is None:
            raise HTTPException(404, f"Kubernetes is not configured for {rt.view.name} (kubernetes.url and kubernetes.token)")
        try:
            pods, nodes, deployments = await asyncio.gather(k.pods(), k.nodes(), k.deployments())
        except PromError as e:
            raise _prom_guard(e) from e
        namespaces = sorted({p["namespace"] for p in pods})
        if namespace:
            pods = [p for p in pods if p["namespace"] == namespace]
            deployments = [d for d in deployments if d["namespace"] == namespace]
        healthy = lambda p: p["phase"] in ("Succeeded",) or (p["phase"] == "Running" and p["ready"] and not p["crashloop"])  # noqa: E731
        pods.sort(key=lambda p: (healthy(p), -p["restarts_1h"], p["namespace"], p["name"]))
        return {
            "nodes": nodes, "namespaces": namespaces, "pods": pods[:500], "truncated": len(pods) > 500,
            "deployments": [d for d in deployments if d["available"] < d["desired"]],
            "summary": {"nodes": len(nodes), "nodes_ready": sum(n["ready"] for n in nodes), "pods": len(pods),
                        "pods_unhealthy": sum(not healthy(p) for p in pods), "restarts_1h": sum(p["restarts_1h"] for p in pods),
                        "deployments": len(deployments), "deployments_unavailable": sum(d["available"] < d["desired"] for d in deployments)},
        }

    # ---------------- slos ----------------
    @secured.get("/slos")
    async def slos(rt: Runtime = Depends(srv)) -> dict[str, Any]:
        return {"slos": await slo_engine.snapshot(rt), "server": rt.view.id}

    # ---------------- argo cd ----------------
    @secured.get("/argocd")
    async def argocd_overview(project: str = Query("", max_length=100), rt: Runtime = Depends(srv)) -> dict[str, Any]:
        a = argos.get(rt.view.id)
        if a is None:
            raise HTTPException(404, f"Argo CD is not configured for {rt.view.name} (argocd.url and argocd.token)")
        try:
            apps = await a.apps()
        except PromError as e:
            raise _prom_guard(e) from e
        projects = sorted({x["project"] for x in apps})
        if project:
            apps = [x for x in apps if x["project"] == project]
        ok = lambda x: x["sync"] == "Synced" and x["health"] == "Healthy" and not sync_failing(x) and not x["errors"]  # noqa: E731
        rank = lambda x: (ok(x), x["health"] == "Progressing", x["name"])  # noqa: E731
        return {
            "apps": sorted(apps, key=rank)[:500], "projects": projects, "truncated": len(apps) > 500, "url": a.base,
            "summary": {"total": len(apps), "healthy": sum(x["health"] == "Healthy" for x in apps),
                        "synced": sum(x["sync"] == "Synced" for x in apps), "out_of_sync": sum(x["sync"] == "OutOfSync" for x in apps),
                        "degraded": sum(x["health"] in ("Degraded", "Missing") for x in apps),
                        "progressing": sum(x["health"] == "Progressing" for x in apps),
                        "failed": sum(sync_failing(x) or bool(x["errors"]) for x in apps)},
        }

    # ---------------- datadog ----------------
    @secured.get("/datadog/monitors")
    async def datadog_monitors(rt: Runtime = Depends(srv)) -> dict[str, Any]:
        d = dogs.get(rt.view.id)
        if d is None:
            raise HTTPException(404, f"Datadog is not configured for {rt.view.name} (datadog.api_key and datadog.app_key)")
        try:
            return {**await d.monitors(), "app_url": d.app}
        except PromError as e:
            raise _prom_guard(e) from e

    @secured.get("/checks")
    async def get_checks(rt: Runtime = Depends(srv)) -> list[dict[str, Any]]:
        return rt.checks.summary()

    app.include_router(api)
    app.include_router(secured)

    # ---------------- static frontend ----------------
    static = Path(os.environ.get("NIGRANI_STATIC_DIR", Path(__file__).resolve().parents[2] / "frontend" / "dist"))

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        if static.is_dir():
            f = (static / path).resolve()
            if path and f.is_file() and static.resolve() in f.parents:
                return FileResponse(f)
            index = static / "index.html"
            if index.is_file():
                return FileResponse(index)
        return JSONResponse({"detail": "frontend not built; see README"}, status_code=404)

    return app


def _logql_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
