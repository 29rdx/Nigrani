# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **A new look.** The navy-and-blue palette is replaced by neutral graphite (dark) and warm paper (light), with the accent colour chosen under **Appearance** in the
  account menu: Ember (the default; the warning colour is a clear yellow so the two stay apart), Violet, Emerald, Rose or Mono, each with its own light and dark tones, plus mode (system, light,
  dark) and spacing. The choice is remembered, applied before the first paint (no flash), can be previewed with `?accent=ember&theme=light`, and recolours the charts, the
  logo and the favicon. Status colours (green, amber, red) are the same in every accent. Contrast was checked for every accent in both modes (Lighthouse accessibility 100).
- **UI, second pass.** Charts: drag to zoom (every chart on the page together, "Reset zoom" or double-click to undo), one shared crosshair, a legend that highlights on hover and
  hides a series on click, and a y axis that fits the data (a 6% error rate is readable instead of a flat line on 0-100). Sortable columns on Containers, Active alerts and Rules;
  Active alerts get a severity filter and search; the tab title and favicon show how many alerts are firing; copy-link and copy-summary on an incident, with a breadcrumb;
  a compact-spacing option in the account menu; and a setup checklist on the Overview for new installs (notifications, suggested dashboards, uptime checks).
- **A production-grade UI.** A command palette (`Ctrl/Cmd K` or `/`: pages, alerts, rules, containers, actions), keyboard shortcuts (`g` then `o a c h u i d s`, `?`
  for help), an account menu, toasts that confirm every action and report failures instead of failing silently, an error boundary so one broken page
  does not blank the app, a "can't reach Nigrani" banner, skeleton loading instead of "Loading…", and Inter bundled with the app (works offline).
- Faster: page code is split and fetched ahead of time (the first script went from 101 kB to 58 kB gzipped), and the page no longer jumps while it loads
  (layout shift 0.16 to 0). Accessibility fixes found by Lighthouse (contrast, heading order, table headers, landmarks, focus trapping and restoring in dialogs):
  100 on every page. A new logo, favicon, web app manifest and meta tags; the login page is redesigned.

### Fixed
- Chart tooltips put series names (which come from monitored systems) into HTML unescaped; they are now escaped.
- Demo mode showed every container metric as the same few bytes/seconds (the demo answered all container queries with the age query).

## [0.6.0] - 2026-11-03

### Added
- **MCP server** (`mcp: {enabled: true}` / `NIGRANI_MCP=1`, on in demo mode): Nigrani serves read-only tools at `/mcp` (status, incidents, one incident in
  detail, PromQL queries, rules, containers, SLOs, deploys, Argo CD) so Claude Code and other MCP clients can investigate alerts. The tools use the
  caller's token against Nigrani's own API.
- **API tokens** (Users page, admin): long-lived bearer tokens (`nig_...`, viewer or editor, optional expiry, stored hashed, shown once) for scripts
  and assistants, plus read-only `GET /api/query` and `/api/query_range`.
- **GPU and LLM serving presets**: `gpu` (NVIDIA dcgm-exporter), `vllm` and `triton`, each with a page, tiles and alert rules
  (GPU memory, temperature and XID errors; request queue, KV cache and time to first token; failure rate and queue time). They describe
  themselves for auto-discovery. `gpu-idle` is off by default.

## [0.5.0] - 2026-11-03

### Added
- **SLOs and burn-rate alerts** (`slos:` config): a target and window, an SLI from two PromQL expressions (`total` with `good` or `errors`) or
  from an uptime check, an SLOs page with the error budget left and the burn rate of every alert tier, and multi-window, multi-burn-rate alerts
  (fast, slow, steady and gradual burn, plus budget exhausted) that scale with the window.
- **Helm chart** ([deploy/helm/nigrani](deploy/helm/nigrani)): Deployment (one replica, Recreate), Service, optional Ingress, PersistentVolumeClaim
  (kept on uninstall), ConfigMap from `config:`, generated or existing admin Secret (stable across upgrades), optional read-only RBAC for the
  Kubernetes integration, non-root with a read-only root filesystem, `helm test`, and `demo: true`.
- **Argo CD** (`argocd:` config, read-only): an Argo CD page (health, sync, revision and errors per application), an `argocd`
  data source for alert rules (`out_of_sync`, `degraded`, `progressing`, `sync_failed`, `sync_error`, narrowed with `app=`,
  `project=`, `namespace=`), an `argocd` preset, and every sync as a deploy marker on the incident page and in Deploys. Works with a
  token that can only `get` applications.
- **Auto-discovery**: Nigrani reads the metric names in Prometheus and suggests the built-in presets that fit (Redis, PostgreSQL,
  Django, Celery, MQTT, AWS RDS, host and containers). *Turn on* applies the preset's page, tiles and alert rules immediately, without
  a restart or a config edit, and is remembered; *Turn off* removes them again. Suggestions on the Overview, the full list on
  Integrations. API: `GET /api/discovery`, `POST /api/discovery/{preset}/enable`, `DELETE /api/discovery/{preset}`.
- Presets describe themselves (`title`, `about`, `detect`) in their YAML.

## [0.4.1] - 2026-11-03

### Fixed
- Nigrani crashed at startup (`FileNotFoundError` on the Kubernetes CA file) on platforms that run containers on Kubernetes without
  mounting a service account, such as Render, because the `KUBERNETES_SERVICE_HOST` variable alone was taken to mean "running in a
  cluster". In-cluster mode now needs the mounted service account token as well. A `kubernetes.ca_file` that does not exist is
  reported as a configuration error naming the file.

## [0.4.0] - 2026-11-03

### Added
- **Demo mode** (`NIGRANI_DEMO=1`): sample data in place of Prometheus, a few finished incidents and 90 days of uptime history,
  and a bad spell every 90 minutes so alerts fire and resolve for real. No login; the UI is read-only, so it can be hosted
  publicly.
- **AI assistant** (optional, `ai:` config, uses the Anthropic API): *Explain this incident* on the incident page (saved, so it
  costs nothing to reopen) and *Draft* in the new-rule form, which turns a sentence into a rule checked against your
  Prometheus. Off by default; editors and admins only; recorded in the audit log.
- **Status page**: 90 days of daily uptime bars per service (`status_page.days`), and updates you post from the Uptime page:
  incidents, planned maintenance (with a "Scheduled maintenance" banner while it runs) and notices.
- `ratio` unit for fractional metrics, displayed as percentages in dashboards, alerts and notifications; thresholds remain in query units.
- Continuous integration now also runs ruff, CodeQL and dependency review, and Dependabot patch/minor updates merge themselves
  once checks pass.
- `/api/public/status` now includes `days`, `uptime_period`, `period_days` and `announcements`.

### Changed
- Uptime results are summed into daily totals that are kept for 400 days, so the status page can show a long history while
  raw check results are still pruned after `retention_days`.

## [0.3.0] - 2026-11-02

### Added
- **Azure Monitor** (`azure:` config, read-only): an `azure` data source for alert rules (`Microsoft.Compute/virtualMachines
  "Percentage CPU" aggregation=Maximum`), one alert per resource of a type, an `azure` preset (VM, PostgreSQL, SQL,
  App Service plan), and the metric charted on the incident page. Entra ID service principal sign-in; sovereign clouds
  supported.
- **Datadog** (`datadog:` config, read-only): a `datadog` data source for alert rules (a Datadog metric query, one alert per
  series), a Datadog page listing monitors that are Alert, Warn or No Data, a `datadog` preset (host CPU, memory, disk), and
  the metric charted on the incident page. Any Datadog site.
- **Kubernetes** (`kubernetes:` config, read-only): a Kubernetes page (nodes, pods, deployments missing replicas, restarts),
  a `kubernetes` data source for alert rules (`crashloop`, `restarts_1h`, `not_ready_minutes`, `pod_failed`,
  `node_not_ready`, `deployment_unavailable`, narrowed with `namespace=` / `pod=`), a `kubernetes` preset, an RBAC
  example, and automatic in-cluster credentials.

## [0.2.0] - 2026-11-02

### Added
- Several users with **roles** (viewer, editor, admin): a Users page for admins, scrypt-hashed passwords, role changes
  and disabling that apply to open sessions within seconds, and an **audit log** of sign-ins and changes.
  Every state-changing route needs at least `editor`; forgotten routes fail closed.
- **Single sign-on** with any OpenID Connect provider (Google, Microsoft, Okta, Keycloak, Dex...), authorization code
  flow with PKCE, verified e-mail only, restricted by `allowed_domains` / `allowed_emails`, roles from
  `admin_emails` / `editor_emails`. The configured administrator always works.
- **Sentry** (`sentry:` config): a Sentry page (search, sort, unresolved / new / fatal tiles), a `sentry` data source for
  alert rules where the value is the number of matching issues per project, a `sentry` preset, and the matching issues
  on an incident's page. Works with sentry.io and self-hosted Sentry.
- **AWS CloudWatch** (`cloudwatch:` config): a `cloudwatch` data source for alert rules (`AWS/RDS CPUUtilization{DBInstanceIdentifier="*"} stat=Maximum period=300`),
  one alert per resource, a `cloudwatch` preset (RDS CPU and storage, EC2 CPU and status check), and the metric charted on
  the incident page. Credentials from the config, the environment or the EC2 instance role; no AWS SDK needed.
- Grafana links (`grafana:` config): "Open in Grafana" opens Explore with an alert's query and time range, and your own
  dashboards are linked from the incident, container, host and overview screens, with `{container}`, `{from}`, `{to}`
  and other placeholders.
- Incident page (`GET /api/incidents/{id}`, `#/incident/<id>`): lifecycle timeline, the rule's metric with thresholds,
  the container's CPU/memory and logs around the incident, deploys, restarts and related alerts, plus a "What changed?"
  summary. Every notification, escalation, acknowledgement, silence and resolution is now recorded per incident.
- `/api/logs` accepts an explicit `start` / `end` window.
- Acknowledge an alert (`POST /api/incidents/{id}/ack`): pauses its reminders for a chosen time or until it resolves, tells
  the channels who is on it, ends when the alert gets worse, and is credited in the resolved message. New
  `{acknowledged_by}` and `{note}` template placeholders.
- Backup and restore of rules, channels and silences (`GET /api/backup`, `POST /api/backup/import`, **Backup** page):
  credentials are omitted by default, import starts with a dry run, is all-or-nothing and never deletes.
- Custom message templates per notification channel (`title_template` / `body_template` with placeholders such as
  `{rule}`, `{series}`, `{value}`, `{server}`, `{duration}`), validated on save, with a live preview in the channel editor.
- Logs page: "Create alert from this search" turns the current container / level / text filter into a log-based alert
  rule, with the rule editor prefilled and a live preview.

### Fixed
- **Crash loops were not detected.** The *Container restarting* rule and the Containers page's "restarts" column counted
  changes of cAdvisor's start time, which Docker's in-place restarts never change. They now count the RestartCount
  incarnations cAdvisor reports, so a container stuck restarting is reported.
- Fixes to a preset rule now reach existing installs. Rules you have not edited are updated on startup; edited ones are
  left alone.

## [0.1.0] - 2026-11-01

First public release.

### Added
- Dashboard: overview with threshold-aware tiles, containers, host (with disk-full forecast), logs (Loki),
  uptime checks (HTTP/TCP/TLS expiry), deploy markers from GitHub Actions, optional public status page.
- Presets for `core` (node-exporter + cAdvisor), `django`, `redis`, `postgres`, `rds`, `mqtt` and `celery`;
  custom pages and rules in YAML.
- Alert engine: pending/firing/resolved with de-duplication, reminders, escalation, silences, quiet hours,
  retry on delivery failure; rules editable in the UI with live preview.
- Notification channels: Slack, Microsoft Teams, Discord, Telegram, email, WhatsApp (Twilio), signed webhook.
- Incident history with a visual timeline, and a daily/weekly digest.
- Multiple servers (for example production and staging) in one dashboard, with an all-servers view and
  per-server rule/channel/silence scoping.
- Login, rate-limited, signed cookie sessions, CSRF protection and security headers.
- Log-based alert rules: `datasource: loki` evaluates a LogQL metric query against a server's Loki. New `logs` preset
  with an "Error spike in logs" rule; the rule editor can choose the data source and preview LogQL.
- `dev/lab`: real exporters used to verify the presets (django, redis, postgres, mqtt, celery).
- GitHub deploy markers ignore pull-request and Dependabot runs.
- Release automation: a `vX.Y.Z` tag builds and publishes a multi-arch image to `ghcr.io/nikhilrai-tech/nigrani`.

### Fixed
- A "resolved" message sent after a restart keeps the rule name and series, and a series that no longer exists
  no longer shows its last firing value as "Now".
