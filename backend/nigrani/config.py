"""Config loading: nigrani.yaml + presets, validated strictly so typos fail loudly."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .templates import validate as validate_templates

PRESET_DIR = Path(__file__).parent / "presets"
_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

Direction = Literal["above", "below"]


class ConfigError(Exception):
    pass


def expand_env(text: str) -> str:
    """Replace ${VAR} / ${VAR:-default} from the environment."""
    return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) if m.group(2) is not None else ""), text)


def _expand(obj: Any) -> Any:
    if isinstance(obj, str):
        return expand_env(obj)
    if isinstance(obj, list):
        return [_expand(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _expand(v) for k, v in obj.items()}
    return obj


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppCfg(_M):
    name: str = "Nigrani"
    environment: str = "production"
    timezone: str = "UTC"
    public_url: str = ""  # used for links inside notifications


class OidcCfg(_M):
    """Single sign-on with any OpenID Connect provider (Google, Microsoft Entra, Okta, Keycloak, Dex...)."""
    issuer: str  # e.g. https://accounts.google.com (its /.well-known/openid-configuration is used)
    client_id: str
    client_secret: str
    label: str = "Sign in with SSO"
    scopes: list[str] = Field(default_factory=lambda: ["openid", "email", "profile"])
    allowed_domains: list[str] = Field(default_factory=list)  # e.g. ["example.com"]: any verified address there
    allowed_emails: list[str] = Field(default_factory=list)
    admin_emails: list[str] = Field(default_factory=list)  # signing in with these creates an admin
    editor_emails: list[str] = Field(default_factory=list)
    default_role: Literal["viewer", "editor", "admin"] = "viewer"  # for first-time users who are allowed in

    @model_validator(mode="after")
    def _someone_is_allowed(self) -> "OidcCfg":
        if not (self.allowed_domains or self.allowed_emails or self.admin_emails or self.editor_emails):
            raise ValueError("set allowed_domains, allowed_emails, admin_emails or editor_emails: without one of them "
                             "every account at the provider could sign in")
        return self


class AuthCfg(_M):
    username: str = "admin"
    password: str = ""
    secret: str = ""
    session_hours: int = 24
    oidc: OidcCfg | None = None


class DatasourcesCfg(_M):
    prometheus: str = "http://prometheus:9090"
    loki: str = ""
    loki_container_label: str = "container"
    timeout: float = 10.0


class HostCfg(_M):
    fstype_exclude: str = "tmpfs|overlay|squashfs|devtmpfs|devfs|iso9660|nsfs|fuse.*"
    mountpoint_exclude: str = (
        "^/(proc|sys|dev|run)($|/.*)|.*/docker/(overlay2|containers|plugins|volumes).*"
        "|.*/snapshots/.*|^/etc/.*"
    )


class ContainersCfg(_M):
    label: str = "name"  # cAdvisor label holding the container name
    stale_seconds: int = 90  # cAdvisor last_seen older than this = not running
    learn_after_seconds: int = 600  # auto-track containers that stayed up this long
    auto_track: bool = True
    exclude: list[str] = Field(default_factory=list)  # regexes of container names to ignore (other projects, noise)


class ServiceCfg(_M):
    name: str
    container: str = ""
    group: str = ""
    critical: bool = True


class TileCfg(_M):
    id: str
    title: str
    query: str
    unit: str = "short"  # ratio displays fractions as percentages; thresholds stay in query units
    direction: Direction = "above"
    warn: float | None = None
    crit: float | None = None
    description: str = ""


class QueryCfg(_M):
    expr: str
    legend: str = ""  # e.g. "{status}" -> label value


class PanelCfg(_M):
    title: str
    queries: list[QueryCfg]
    unit: str = "short"  # ratio displays fractions as percentages; thresholds stay in query units
    kind: Literal["line", "area", "stat"] = "line"
    wide: bool = False
    description: str = ""
    max_series: int = 12

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, v: Any) -> Any:
        if isinstance(v, dict) and "expr" in v and "queries" not in v:
            v = dict(v)
            v["queries"] = [{"expr": v.pop("expr"), "legend": v.pop("legend", "")}]
        return v


class PageCfg(_M):
    id: str
    title: str
    icon: str = "chart"
    requires: str = ""  # metric name that must exist for the page to be "available"
    hint: str = ""  # shown when the metric is missing (which exporter to run)
    panels: list[PanelCfg]


class RuleCfg(_M):
    id: str
    name: str
    expr: str
    direction: Direction = "above"
    warn: float | None = None
    crit: float | None = None
    for_seconds: int = 300
    unit: str = "short"  # ratio displays fractions as percentages; thresholds stay in query units
    summary: str = ""
    enabled: bool = True
    servers: list[str] = Field(default_factory=list)  # empty = evaluate on every server
    datasource: Literal["prometheus", "loki", "sentry", "cloudwatch", "kubernetes", "datadog", "azure", "argocd"] = "prometheus"  # loki: LogQL metric query; sentry: a Sentry search


ChannelType = Literal["slack", "teams", "discord", "telegram", "email", "webhook", "whatsapp"]


class ChannelCfg(_M):
    id: str
    name: str
    type: ChannelType
    settings: dict[str, Any] = Field(default_factory=dict)
    min_severity: Literal["info", "warning", "critical"] = "warning"
    quiet_hours: list[int] | None = None  # [start_hour, end_hour] local; critical still sent
    enabled: bool = True
    servers: list[str] = Field(default_factory=list)  # empty = alerts from every server
    title_template: str | None = None  # e.g. "{emoji} {rule} on {server}: {value}"; see templates.PLACEHOLDERS
    body_template: str | None = None

    @model_validator(mode="after")
    def _templates_ok(self) -> "ChannelCfg":
        err = validate_templates(self.title_template, self.body_template)
        if err:
            raise ValueError(f"channel '{self.id}': {err}")
        return self


class CheckCfg(_M):
    id: str
    name: str
    type: Literal["http", "tcp", "ssl"]
    target: str
    interval: int = 60
    timeout: float = 10.0
    expect_status: int | None = None
    warn_days: int = 14
    critical: bool = True
    verify_tls: bool = True


class GithubCfg(_M):
    repo: str = ""
    token: str = ""
    workflow: str = ""
    branch: str = ""
    limit: int = 15


class DigestCfg(_M):
    enabled: bool = False
    hour: int = 9
    weekday: int | None = None  # 0=Mon; None = daily
    channels: list[str] = Field(default_factory=list)


class AlertsCfg(_M):
    eval_interval: int = 30
    repeat_interval: int = 4 * 3600
    absent_grace: int = 300


class StatusPageCfg(_M):
    enabled: bool = False
    title: str = "System status"
    days: int = Field(90, ge=7, le=365)  # how many days of daily uptime the page shows


class AiCfg(_M):
    """Optional assistant that explains incidents and drafts alert rules with the Anthropic API.

    Off by default. When on, the data of the incident you ask about (metric values, container stats, alert names) is
    sent to Anthropic; nothing is sent in the background."""
    enabled: bool = False
    api_key: str = ""  # use ${ANTHROPIC_API_KEY}
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high"] = "low"  # how hard the model thinks: higher is slower and costs more
    max_tokens: int = Field(2000, ge=256, le=16000)
    base_url: str = ""  # optional: an Anthropic-compatible gateway or proxy


class SloCfg(_M):
    """A service level objective with multi-window burn-rate alerts (the Google SRE workbook method).

    The SLI is either two PromQL expressions that use `{{window}}` inside their range selectors (`total` plus `good` or
    `errors`), or one of Nigrani's uptime checks (`check`)."""
    id: str
    name: str
    target: float = Field(gt=0, lt=100)  # percent, e.g. 99.9
    window_days: int = Field(30, ge=1, le=90)
    description: str = ""
    total: str = ""   # e.g. sum(rate(http_requests_total[{{window}}]))
    good: str = ""    # e.g. sum(rate(http_requests_total{status!~"5.."}[{{window}}]))
    errors: str = ""  # alternative to `good`
    check: str = ""   # an uptime check id: the SLI is the share of successful checks
    servers: list[str] = Field(default_factory=list)  # empty = every server

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", v):
            raise ValueError("id must be lowercase letters, digits, - or _ (max 40)")
        return v

    @model_validator(mode="after")
    def _sli(self) -> "SloCfg":
        if self.check:
            if self.total or self.good or self.errors:
                raise ValueError("use either `check`, or `total` with `good` or `errors`, not both")
            return self
        if not self.total or bool(self.good) == bool(self.errors):
            raise ValueError("an SLO needs `check`, or `total` plus exactly one of `good` / `errors`")
        for field in ("total", "good", "errors"):
            expr = getattr(self, field)
            if expr and "{{window}}" not in expr:
                raise ValueError(f"`{field}` must use {{{{window}}}} in its range selector, e.g. rate(x[{{{{window}}}}])")
        return self


class ArgoCDCfg(_M):
    """Argo CD applications through its REST API (read-only). Create the token with `argocd account generate-token` for an
    account (or project role) that may `get` applications."""
    url: str = ""  # the Argo CD server, e.g. https://argocd.example.com (include the root path if you set one)
    token: str = ""  # use ${ARGOCD_TOKEN}
    verify_tls: bool = True
    ca_file: str = ""
    projects: list[str] = Field(default_factory=list)  # empty = every project the token can see

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if v and not re.match(r"^https?://[^\s]+$", v):
            raise ValueError("must start with http:// or https://")
        return v.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.url)


class AzureCfg(_M):
    """Azure Monitor metrics through a Microsoft Entra ID service principal that has the Monitoring Reader role."""
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    subscription_id: str = ""
    resource_groups: list[str] = Field(default_factory=list)  # empty = the whole subscription
    authority_url: str = "https://login.microsoftonline.com"  # sovereign clouds differ
    management_url: str = "https://management.azure.com"

    @field_validator("authority_url", "management_url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not re.match(r"^https?://[^\s]+$", v):
            raise ValueError("must start with http:// or https://")
        return v.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret and self.subscription_id)


class DatadogCfg(_M):
    """Datadog: metric queries become alert rules and monitors that are not OK get their own page."""
    site: str = "datadoghq.com"  # datadoghq.eu, us3.datadoghq.com, us5.datadoghq.com, ap1.datadoghq.com, ddog-gov.com
    api_key: str = ""
    app_key: str = ""  # an application key whose owner may read metrics and monitors
    url: str = ""  # only for a proxy or a test double

    @field_validator("site")
    @classmethod
    def _site(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]+", v):
            raise ValueError("must look like datadoghq.com or datadoghq.eu")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if v and not re.match(r"^https?://[^\s]+$", v):
            raise ValueError("must start with http:// or https://")
        return v.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.app_key)


K8S_SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")


def in_cluster() -> bool:
    """True inside a pod that has a service account mounted. The environment variable alone is not enough: platforms that
    run containers on Kubernetes (Render, for one) set it without giving the container any credentials."""
    return bool(os.environ.get("KUBERNETES_SERVICE_HOST")) and (K8S_SA_DIR / "token").is_file()


class KubernetesCfg(_M):
    """A Kubernetes cluster (read-only). Inside a cluster, leave `url` empty: the pod's service account is used."""
    url: str = ""  # API server, e.g. https://10.0.0.1:6443; empty = Kubernetes not configured (unless running in a cluster)
    token: str = ""  # a service account token that may get/list pods, nodes and deployments (use ${K8S_TOKEN})
    ca_file: str = ""  # CA certificate of the API server
    verify_tls: bool = True
    namespaces: list[str] = Field(default_factory=list)  # empty = every namespace

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if v and not re.match(r"^https?://[^\s]+$", v):
            raise ValueError("must start with http:// or https://")
        return v.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.url) or in_cluster()


class CloudWatchCfg(_M):
    """AWS CloudWatch metrics. Credentials: these keys, else the AWS_* variables, else the EC2 instance role."""
    region: str = ""  # e.g. ap-south-1; empty = CloudWatch not configured
    access_key_id: str = ""
    secret_access_key: str = ""
    session_token: str = ""
    endpoint_url: str = ""  # only for a VPC endpoint or a test double

    @field_validator("region")
    @classmethod
    def _region(cls, v: str) -> str:
        if v and not re.fullmatch(r"[a-z]{2}(-[a-z]+)+-\d", v):
            raise ValueError("must look like ap-south-1")
        return v

    @field_validator("endpoint_url")
    @classmethod
    def _endpoint(cls, v: str) -> str:
        if v and not re.match(r"^https?://[^\s]+$", v):
            raise ValueError("must start with http:// or https://")
        return v.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.region)


class SentryCfg(_M):
    """Sentry (sentry.io or self-hosted): its issues become a page, and a Sentry search can drive an alert rule."""
    url: str = "https://sentry.io"
    org: str = ""  # organization slug; empty = Sentry not configured
    token: str = ""  # an auth token with the project:read and event:read scopes (use ${SENTRY_TOKEN})
    projects: list[str] = Field(default_factory=list)  # project slugs to limit to; empty = the whole organization

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not re.match(r"^https?://[^\s]+$", v):
            raise ValueError("must start with http:// or https://")
        return v.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.org and self.token)


class DashboardLink(_M):
    title: str
    url: str  # absolute, or relative to grafana.url; may use {container} {server} {rule} {series} {from} {to}
    where: list[Literal["incident", "container", "host", "overview"]] = Field(default_factory=lambda: ["incident"])

    @field_validator("url")
    @classmethod
    def _known_placeholders(cls, v: str) -> str:
        unknown = sorted(set(re.findall(r"\{(\w+)\}", v)) - {"container", "server", "rule", "series", "from", "to"})
        if unknown:
            raise ValueError("unknown placeholder(s) " + ", ".join("{" + u + "}" for u in unknown) +
                             "; available: {container} {server} {rule} {series} {from} {to}")
        return v


class GrafanaCfg(_M):
    url: str = ""  # e.g. https://grafana.example.com ; empty = no Grafana links anywhere
    prometheus_datasource: str = ""  # datasource UID, used by "Open in Grafana" for metric queries
    loki_datasource: str = ""  # datasource UID, used for log queries
    dashboards: list[DashboardLink] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if v and not re.match(r"^https?://[^\s]+$", v):
            raise ValueError("must start with http:// or https://")
        return v


class ServerCfg(_M):
    """One monitored environment (e.g. production, staging). Unset fields fall back to the top-level values."""
    id: str
    name: str = ""
    environment: str = ""
    datasources: DatasourcesCfg | None = None
    services: list[ServiceCfg] | None = None
    checks: list[CheckCfg] | None = None
    github: GithubCfg | None = None
    grafana: GrafanaCfg | None = None
    sentry: SentryCfg | None = None
    cloudwatch: CloudWatchCfg | None = None
    kubernetes: KubernetesCfg | None = None
    datadog: DatadogCfg | None = None
    azure: AzureCfg | None = None
    argocd: ArgoCDCfg | None = None

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", v):
            raise ValueError("server id must be lowercase letters, digits, - or _")
        return v


@dataclass
class ServerView:
    """A server with every inherited default resolved."""
    id: str
    name: str
    environment: str
    datasources: DatasourcesCfg
    services: list[ServiceCfg]
    checks: list[CheckCfg]
    github: GithubCfg
    grafana: GrafanaCfg
    sentry: SentryCfg
    cloudwatch: CloudWatchCfg
    kubernetes: KubernetesCfg
    datadog: DatadogCfg
    azure: AzureCfg
    argocd: ArgoCDCfg


class Config(_M):
    app: AppCfg = AppCfg()
    auth: AuthCfg = AuthCfg()
    datasources: DatasourcesCfg = DatasourcesCfg()
    host: HostCfg = HostCfg()
    containers: ContainersCfg = ContainersCfg()
    presets: list[str] = Field(default_factory=lambda: ["core"])
    servers: list[ServerCfg] = Field(default_factory=list)
    services: list[ServiceCfg] = Field(default_factory=list)
    tiles: list[TileCfg] = Field(default_factory=list)
    pages: list[PageCfg] = Field(default_factory=list)
    rules: list[RuleCfg] = Field(default_factory=list)
    channels: list[ChannelCfg] = Field(default_factory=list)
    checks: list[CheckCfg] = Field(default_factory=list)
    github: GithubCfg = GithubCfg()
    grafana: GrafanaCfg = GrafanaCfg()
    sentry: SentryCfg = SentryCfg()
    cloudwatch: CloudWatchCfg = CloudWatchCfg()
    kubernetes: KubernetesCfg = KubernetesCfg()
    datadog: DatadogCfg = DatadogCfg()
    azure: AzureCfg = AzureCfg()
    argocd: ArgoCDCfg = ArgoCDCfg()
    digest: DigestCfg = DigestCfg()
    alerts: AlertsCfg = AlertsCfg()
    status_page: StatusPageCfg = StatusPageCfg()
    ai: AiCfg = AiCfg()
    slos: list[SloCfg] = Field(default_factory=list)
    demo: bool = False  # sample data and a read-only UI, for trying Nigrani without Prometheus (NIGRANI_DEMO=1)
    disable: dict[str, list[str]] = Field(default_factory=dict)  # {tiles|pages|rules: [ids]}
    data_dir: str = "/data"
    retention_days: int = 35

    @model_validator(mode="after")
    def _ai_needs_key(self) -> "Config":
        if self.ai.enabled and not self.ai.api_key and not self.demo:
            raise ValueError("ai.enabled needs ai.api_key (use api_key: ${ANTHROPIC_API_KEY})")
        return self

    def server_views(self) -> list[ServerView]:
        """Without `servers:` there is one implicit server built from the top-level settings."""
        if not self.servers:
            env = self.app.environment
            return [ServerView("default", env or self.app.name, env, self.datasources, self.services, self.checks,
                               self.github, self.grafana, self.sentry, self.cloudwatch, self.kubernetes, self.datadog, self.azure, self.argocd)]
        return [
            ServerView(
                s.id, s.name or s.id, s.environment or s.name or s.id,
                s.datasources or self.datasources,
                s.services if s.services is not None else self.services,
                s.checks if s.checks is not None else self.checks,
                s.github or self.github,
                s.grafana or self.grafana,
                s.sentry or self.sentry,
                s.cloudwatch or self.cloudwatch,
                s.kubernetes or self.kubernetes,
                s.datadog or self.datadog,
                s.azure or self.azure,
                s.argocd or self.argocd,
            )
            for s in self.servers
        ]

    def fs_selector(self) -> str:
        return f'fstype!~"{self.host.fstype_exclude}",mountpoint!~"{self.host.mountpoint_exclude}"'


def _merge_by_id(preset_items: list, user_items: list) -> list:
    out: dict[str, Any] = {}
    for item in [*preset_items, *user_items]:
        out[item.id] = item  # user entries replace preset entries with the same id
    return list(out.values())


def _subst_items(fs: str, tiles: list, pages: list, rules: list) -> None:
    def sub(s: str) -> str:
        return s.replace("{{fs}}", fs)

    for t in tiles:
        t.query = sub(t.query)
    for r in rules:
        r.expr = sub(r.expr)
    for p in pages:
        for panel in p.panels:
            for q in panel.queries:
                q.expr = sub(q.expr)


def _subst(cfg: Config) -> None:
    _subst_items(cfg.fs_selector(), cfg.tiles, cfg.pages, cfg.rules)


def read_preset(name: str) -> dict[str, Any]:
    f = PRESET_DIR / f"{name}.yaml"
    if not re.fullmatch(r"[a-z0-9_-]+", name) or not f.is_file():
        known = ", ".join(sorted(p.stem for p in PRESET_DIR.glob("*.yaml")))
        raise ConfigError(f"unknown preset '{name}' (available: {known})")
    return yaml.safe_load(f.read_text()) or {}


def preset_items(name: str) -> tuple[list[TileCfg], list[PageCfg], list[RuleCfg]]:
    data = read_preset(name)
    try:
        return ([TileCfg(**x) for x in data.get("tiles", [])], [PageCfg(**x) for x in data.get("pages", [])],
                [RuleCfg(**x) for x in data.get("rules", [])])
    except ValidationError as e:
        raise ConfigError(f"preset {name}: {e}") from e


def preset_catalog() -> list[dict[str, Any]]:
    """Presets Nigrani can recognise from Prometheus metrics: those whose YAML has `detect:` (the metrics that prove the
    exporter is being scraped), a `title` and an `about` line. The rest need a data source in the config instead."""
    out = []
    for f in sorted(PRESET_DIR.glob("*.yaml")):
        data = yaml.safe_load(f.read_text()) or {}
        if not data.get("detect"):
            continue
        out.append({"name": f.stem, "title": data.get("title", f.stem), "about": data.get("about", ""),
                    "detect": list(data["detect"]), "tiles": len(data.get("tiles", [])),
                    "pages": len(data.get("pages", [])), "rules": len(data.get("rules", []))})
    return out


def apply_presets(cfg: Config, base: tuple[list, list, list], names: list[str]) -> None:
    """Set cfg's tiles, pages and rules to `base` (what the config file produced) plus these presets. Anything already in
    base wins over a preset with the same id, and `disable:` still applies."""
    tiles: list[TileCfg] = []
    pages: list[PageCfg] = []
    rules: list[RuleCfg] = []
    for name in names:
        t, p, r = preset_items(name)
        tiles += t
        pages += p
        rules += r
    _subst_items(cfg.fs_selector(), tiles, pages, rules)
    for kind, extra, mine in (("tiles", tiles, base[0]), ("pages", pages, base[1]), ("rules", rules, base[2])):
        merged = _merge_by_id(extra, mine)
        off = set(cfg.disable.get(kind, []))
        setattr(cfg, kind, [x for x in merged if x.id not in off] if off else merged)


def demo_defaults() -> dict[str, Any]:
    """What demo mode (NIGRANI_DEMO=1) sets up unless your config file says otherwise."""
    port = os.environ.get("NIGRANI_PORT", "8080")
    return {
        "app": {"name": "Nigrani", "environment": "demo"},
        "presets": ["core", "django"],
        "services": [
            {"name": "api", "container": "api", "group": "App"},
            {"name": "worker", "container": "worker", "group": "App"},
            {"name": "nginx", "container": "nginx", "group": "App"},
            {"name": "redis", "container": "redis", "group": "Data"},
            {"name": "postgres", "container": "postgres", "group": "Data"},
        ],
        # Nigrani checks itself, so the uptime page and the status page have real checks without any outside network.
        "checks": [
            {"id": "web", "name": "Web app", "type": "http", "target": f"http://127.0.0.1:{port}/api/health", "interval": 30},
            {"id": "api", "name": "API", "type": "http", "target": f"http://127.0.0.1:{port}/api/health", "interval": 30},
            {"id": "database", "name": "Database", "type": "tcp", "target": f"127.0.0.1:{port}", "interval": 30},
        ],
        "status_page": {"enabled": True, "title": "Acme status"},
        "demo": True,
    }


def load_config(path: str | None = None, *, explicit: bool = False, demo: bool = False) -> Config:
    raw: dict[str, Any] = {}
    if path and Path(path).is_file():
        raw = yaml.safe_load(Path(path).read_text()) or {}
    elif explicit and not demo:
        raise ConfigError(f"config file not found: {path}")
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")
    if demo:
        raw = {**demo_defaults(), **raw, "demo": True}

    # channel settings keep their ${VAR} references literally; they are expanded at send time
    channels = raw.pop("channels", [])
    raw = _expand(raw)
    raw["channels"] = channels
    try:
        cfg = Config(**raw)
    except ValidationError as e:
        raise ConfigError(str(e)) from e

    preset_tiles: list[TileCfg] = []
    preset_pages: list[PageCfg] = []
    preset_rules: list[RuleCfg] = []
    for name in cfg.presets:
        t, p, r = preset_items(name)
        preset_tiles += t
        preset_pages += p
        preset_rules += r

    ids = [x.id for x in cfg.servers]
    if len(ids) != len(set(ids)):
        raise ConfigError("duplicate server id in `servers:`")
    unknown = {sid for r in [*cfg.rules, *cfg.channels] for sid in r.servers} - set(ids) if ids else set()
    if unknown:
        raise ConfigError(f"rules/channels reference unknown server(s): {', '.join(sorted(unknown))}")

    slo_ids = [x.id for x in cfg.slos]
    if len(slo_ids) != len(set(slo_ids)):
        raise ConfigError("duplicate id in `slos:`")
    bad = {sid for x in cfg.slos for sid in x.servers} - set(ids) if ids else {sid for x in cfg.slos for sid in x.servers}
    if bad:
        raise ConfigError(f"slos reference unknown server(s): {', '.join(sorted(bad))}")

    if cfg.auth.oidc and not cfg.app.public_url:
        raise ConfigError("auth.oidc needs app.public_url: the provider redirects the browser back to it")

    cfg.tiles = _merge_by_id(preset_tiles, cfg.tiles)
    cfg.pages = _merge_by_id(preset_pages, cfg.pages)
    cfg.rules = _merge_by_id(preset_rules, cfg.rules)
    for kind in ("tiles", "pages", "rules"):
        off = set(cfg.disable.get(kind, []))
        if off:
            setattr(cfg, kind, [x for x in getattr(cfg, kind) if x.id not in off])
    _subst(cfg)
    return cfg
