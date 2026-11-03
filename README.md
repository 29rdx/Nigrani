# Nigrani

**Self-hosted monitoring and alerting dashboard for Docker projects.** One container that sits on top of Prometheus and
Loki, adds Sentry, Kubernetes, AWS CloudWatch, Datadog and Azure Monitor as alert sources, and tells you on Slack, Microsoft
Teams, Telegram, email, WhatsApp, Discord or a webhook when something breaks.

[![CI](https://github.com/nikhilrai-tech/Nigrani/actions/workflows/ci.yml/badge.svg)](https://github.com/nikhilrai-tech/Nigrani/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/nikhilrai-tech/Nigrani?sort=semver)](https://github.com/nikhilrai-tech/Nigrani/releases)
[![Docker image](https://img.shields.io/badge/ghcr.io-nigrani-2496ed?logo=docker&logoColor=white)](https://github.com/nikhilrai-tech/Nigrani/pkgs/container/nigrani)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**[Live demo](https://nigrani-demo-nesu.onrender.com/)** (sample data, read-only, no login; it sleeps when idle, so the first load can take a minute) ·
[Status page example](https://nigrani-demo-nesu.onrender.com/#/status)

*Nigrani* (निगरानी) is Hindi for "watchful oversight".

```bash
docker run -d --name nigrani -p 8080:8080 \
  -e NIGRANI_PASSWORD=change-me -e NIGRANI_PROMETHEUS_URL=http://your-prometheus:9090 \
  -v nigrani-data:/data ghcr.io/nikhilrai-tech/nigrani:latest
# open http://localhost:8080   (no Prometheus yet? see "Try it in two minutes" below)
```

Just want to look around first? Demo mode needs no Prometheus and no login: it runs on sample data (with alerts that
fire and resolve on their own) and is read-only.

```bash
docker run --rm -p 8080:8080 -e NIGRANI_DEMO=1 ghcr.io/nikhilrai-tech/nigrani:latest
```

![Overview](docs/screenshots/overview-dark.png)

## Why

Grafana is great for exploring metrics but it won't tell you "the disk fills in 1.4 days" or page you when a container
silently stops. Nigrani answers the operational questions directly:

- **Is everything OK right now?** One status banner. Every tile shows its warn/critical thresholds on the bar.
- **What is about to break?** Disk-full forecast, crash-loop detection, scrape targets that went down.
- **Tell me when it does.** An alert engine with `pending → firing → resolved`, de-duplication, reminders, silences,
  quiet hours, and automatic retry if a channel is down.
- **Why?** Per-container CPU/memory/network, live logs (Loki), and deploy markers on the charts so you can see
  that the spike started right after a release.

### Is it for you?

- **Good fit:** you run Docker (Compose or a few servers) with Prometheus, you want alerts and an answer to "is it OK?"
  without building Grafana dashboards and alert rules by hand, and you want errors from Sentry, cloud metrics from
  AWS, Azure or Datadog, and your cluster in the same place.
- **It works alongside** Prometheus, Loki and Grafana rather than replacing them: it reads from them, and links back
  into your Grafana dashboards.

## Features

| | |
|---|---|
| **Overview** | Status banner, key tiles with thresholds, CPU/memory trend, active alerts, uptime checks |
| **Containers** | Every container: status, CPU, memory (vs limit), restarts, uptime, network. Click for charts and logs. Auto-detects stopped containers |
| **Host** | CPU, memory, load, network, disk I/O, per-filesystem usage with **days-until-full forecast** |
| **Sentry** | Unresolved, new and fatal issues on their own page, alert rules over Sentry searches, and the matching issues on an incident's page |
| **AWS CloudWatch** | Alert rules straight on CloudWatch metrics (RDS, EC2, ELB, SQS, anything), one alert per database or instance, with the metric charted on the incident page. No exporter needed |
| **Kubernetes** | Nodes, pods and deployments on their own page, and alert rules for crash-looping or failed pods, stuck or restarting pods, unready nodes and deployments missing replicas. Read-only, no agent in the cluster |
| **GPUs and LLM serving** | Presets for NVIDIA GPUs (dcgm-exporter), vLLM and Triton: utilization, memory, temperature, queue depth, KV cache, time to first token and tokens per second, with alerts for a full GPU, overheating, XID errors, a backed-up request queue and slow first tokens. Auto-discovery switches them on when it sees the metrics |
| **Argo CD** | The state of your GitOps applications on their own page (health, sync, revision, errors), alert rules for applications that are out of sync, degraded, stuck progressing or failing to sync, and every sync as a deploy marker on the incident page. Read-only, with a token that can only `get` |
| **Datadog** | Alert rules straight on Datadog metric queries (one alert per host or tag), the metric charted on the incident page, and a page of monitors that are alerting, warning or have no data |
| **Azure Monitor** | Alert rules straight on Azure Monitor metrics (VMs, PostgreSQL, SQL, App Service...), one alert per resource, with the metric charted on the incident page |
| **Grafana links** | "Open in Grafana" from an alert, a rule or the Logs page (Explore with the same query and time range), plus links to your own dashboards from the incident, container, host and overview screens |
| **Service pages** | Traffic (Django), Redis, Postgres, AWS RDS, MQTT, Celery out of the box. Add your own pages in YAML |
| **Incident page** | Click any alert for everything around it: lifecycle timeline, the metric with thresholds, the container's CPU/memory and logs, deploys and restarts just before it started, and other alerts that fired at the same time ("What changed?") |
| **Auto-discovery** | Nigrani reads the metric names in Prometheus and says "Redis found: turn on its dashboard and alert rules?". One click, no restart, no config file |
| **SLOs** | Say "99.9% of requests succeed over 30 days" and Nigrani tracks the error budget and alerts when it burns too fast, with the multi-window burn-rate method from the Google SRE workbook (quick to fire, quick to clear, quiet about blips) |
| **Alerts** | Rules editable in the UI (thresholds, duration, PromQL with live preview), silences, and an **incident timeline** showing when each alert started, how long it lasted and what its peak was |
| **Integrations** | Slack, Teams, Discord, Telegram, Email, WhatsApp (Twilio), signed webhook. Per-channel severity + quiet hours, "send test" button |
| **Uptime** | HTTP / TCP / TLS-certificate-expiry checks with 30-day uptime |
| **Status page** | A public, login-free page with 90 days of daily uptime per service, and updates you post (incidents, planned maintenance, notices) |
| **AI assistant** *(optional)* | "Explain this incident" (what happened, likely cause, what to check) and "describe a rule in plain English", with your own Anthropic API key. Off by default |
| **Demo mode** | `NIGRANI_DEMO=1`: sample data and a read-only UI, to try or show Nigrani without any monitoring stack |
| **Deploys** | GitHub Actions runs (pull-request and Dependabot runs are ignored), shown as dashed markers on charts |
| **Digest** | A daily or weekly summary message |
| **Users and roles** | Several people with viewer / editor / admin roles, password or single sign-on (Google, Microsoft, Okta, Keycloak... any OpenID Connect provider), and an audit log of sign-ins and changes |
| **Backup** | Export and restore rules, channels and silences as one JSON file, with a dry-run before anything changes |
| **Multiple servers** | Watch production and staging (or any number of environments) from one dashboard, with an all-servers view and per-server routing of alerts |
| **UI** | Light/dark, responsive, keyboard accessible, no external fonts or CDNs |

<p>
  <img src="docs/screenshots/containers.png" width="49%" alt="Containers" />
  <img src="docs/screenshots/host.png" width="49%" alt="Host" />
</p>
<p>
  <img src="docs/screenshots/alert-rules.png" width="49%" alt="Alert rules" />
  <img src="docs/screenshots/overview-light.png" width="49%" alt="Light theme" />
</p>
<p>
  <img src="docs/screenshots/fleet.png" width="49%" alt="All servers" />
  <img src="docs/screenshots/incident-timeline.png" width="49%" alt="Incident timeline" />
</p>
<p>
  <img src="docs/screenshots/sentry.png" width="49%" alt="Sentry issues" />
  <img src="docs/screenshots/users.png" width="49%" alt="Users and roles" />
</p>
<p>
  <img src="docs/screenshots/kubernetes.png" width="49%" alt="Kubernetes pods and deployments" />
  <img src="docs/screenshots/datadog.png" width="49%" alt="Datadog monitors" />
</p>
<p>
  <img src="docs/screenshots/rule-cloudwatch.png" width="49%" alt="CloudWatch alert rule with live preview" />
  <img src="docs/screenshots/incident-cloudwatch.png" width="49%" alt="Incident for an RDS database" />
</p>

## Quick start

### A. Try it in two minutes (everything included)

Starts Prometheus, node-exporter, cAdvisor, Loki, Promtail and Nigrani, and monitors the machine it runs on.

```bash
git clone https://github.com/nikhilrai-tech/Nigrani.git && cd Nigrani
cp .env.example .env            # set NIGRANI_PASSWORD
docker compose -f docker-compose.full.yml up -d --build
# open http://localhost:8080  (user: admin)
```

Give it about a minute for Prometheus to collect its first samples.

### B. Add Nigrani to the stack you already have

1. Copy [nigrani.example.yaml](nigrani.example.yaml) to `nigrani.yaml`; point `datasources.prometheus` at your Prometheus
   and pick the `presets` that match the exporters you run.
2. Add the service from [examples/add-to-existing-compose.yml](examples/add-to-existing-compose.yml) to your
   `docker-compose.yml` (or run [docker-compose.yml](docker-compose.yml) from this repo, joining your network).
3. Set `NIGRANI_PASSWORD` in your `.env` and `docker compose up -d`.

### C. Plain `docker run`

The image is public and built for amd64 and arm64.

```bash
docker run -d --name nigrani -p 8080:8080 \
  -e NIGRANI_PASSWORD=... -e NIGRANI_PROMETHEUS_URL=http://your-prometheus:9090 \
  -v nigrani-data:/data ghcr.io/nikhilrai-tech/nigrani:latest
```

Without a config file Nigrani runs with the `core` preset and these environment variables:
`NIGRANI_PASSWORD` (required), `NIGRANI_USERNAME`, `NIGRANI_PROMETHEUS_URL`, `NIGRANI_LOKI_URL`, `NIGRANI_SECRET`
(session-signing key; set it so logins survive restarts), `NIGRANI_DATA_DIR`, `NIGRANI_CONFIG`.

### D. Kubernetes (Helm)

The chart is in [deploy/helm/nigrani](deploy/helm/nigrani). From a clone of this repository:

```bash
helm install nigrani ./deploy/helm/nigrani -n monitoring --create-namespace \
  --set config.datasources.prometheus=http://prometheus-server.monitoring.svc.cluster.local:9090

kubectl -n monitoring port-forward svc/nigrani 8080:8080        # then open http://localhost:8080
kubectl -n monitoring get secret nigrani -o jsonpath='{.data.NIGRANI_PASSWORD}' | base64 -d   # the admin password
```

Without `auth.password` the chart generates a password once and keeps it across upgrades. The settings you will use most
(all in [values.yaml](deploy/helm/nigrani/values.yaml)):

```yaml
auth: {existingSecret: nigrani-admin}            # or password: ... ; the Secret key is NIGRANI_PASSWORD
config:                                          # this is nigrani.yaml, verbatim
  datasources: {prometheus: http://prometheus-server.monitoring.svc.cluster.local:9090}
  presets: [core, argocd]
  kubernetes: {}                                 # watch this cluster (needs rbac.create)
  argocd: {url: http://argocd-server.argocd.svc.cluster.local, token: "${ARGOCD_TOKEN}"}
extraEnvFrom: [{secretRef: {name: nigrani-secrets}}]   # ARGOCD_TOKEN, SLACK_WEBHOOK_URL ... referred to as ${NAME} above
rbac: {create: true}                             # read-only ClusterRole: pods, nodes, deployments
ingress:
  enabled: true
  className: nginx
  hosts: [{host: nigrani.example.com, paths: [{path: /, pathType: Prefix}]}]
  tls: [{secretName: nigrani-tls, hosts: [nigrani.example.com]}]
persistence: {size: 1Gi, storageClass: ""}       # keep it on: the database holds your rules and incident history
```

Details worth knowing: there is always exactly one replica (one SQLite file) with the `Recreate` strategy; the pod runs as a
non-root user with a read-only root filesystem; a change to `config` restarts the pod; with `rbac.create: false` (the default)
the pod gets no service account token at all; `helm uninstall` keeps the data volume; `helm test nigrani` checks the health
endpoint; `--set demo=true` installs the demo (sample data, read-only) instead.

## Monitoring several servers (prod + staging)

Add a `servers:` list. Each server has its own Prometheus and, optionally, its own Loki, `services`, uptime `checks`
and GitHub repo; anything you leave out is inherited from the top level. See
[examples/multi-server.yaml](examples/multi-server.yaml).

```yaml
servers:
  - { id: prod,    name: Production, datasources: { prometheus: "http://10.0.1.20:9090" } }
  - { id: staging, name: Staging,    datasources: { prometheus: "http://10.0.2.20:9090" } }
channels:
  - { id: oncall, name: On-call, type: teams, settings: { webhook_url: "${TEAMS_WEBHOOK_URL}" }, servers: [prod] }
```

- A **server switcher** in the header and an **All servers** screen showing each environment's health at a glance.
- Every rule is evaluated against every server's Prometheus; each server alerts **independently** (the same disk
  alert can be firing on prod and resolved on staging). Notifications are tagged `[Production]` / `[Staging]`.
- Scope a rule with `servers: [staging]` (for example a looser threshold) and a channel with `servers: [prod]`
  (so staging noise never pages on-call). Both can also be set from the UI.
- Silences can target one server. Alert history and the timeline show all servers, filterable by server.
- Nigrani only needs to *reach* each Prometheus: same network, VPN, private IP or an SSH tunnel. Keep them off the
  public internet.
- Without `servers:` everything works as a single implicit server, and existing databases upgrade in place.
  (If you add `servers:` to an existing setup, open incidents from the old implicit server are closed on startup.)

## What Nigrani needs from your stack

Nigrani only reads from Prometheus/Loki. Which pages light up depends on which exporters are being scraped:

| Preset | Needs | You get |
|---|---|---|
| `core` (default) | [node-exporter](https://github.com/prometheus/node_exporter), [cAdvisor](https://github.com/google/cadvisor) | Host, Containers, host/disk/restart alerts |
| `django` | [django-prometheus](https://github.com/korfuri/django-prometheus) | Traffic page, 5xx + latency alerts |
| `redis` | [redis_exporter](https://github.com/oliver006/redis_exporter) | Redis page, memory alerts |
| `postgres` | [postgres_exporter](https://github.com/prometheus-community/postgres_exporter) | Postgres page, connection alerts |
| `rds` | [yet-another-cloudwatch-exporter](https://github.com/prometheus-community/yet-another-cloudwatch-exporter) | AWS RDS page, CPU/storage alerts |
| `mqtt` | a Mosquitto exporter | MQTT page |
| `celery` | [celery-exporter](https://github.com/danihodovic/celery-exporter) | Celery page, queue/worker alerts |
| `gpu` | NVIDIA [dcgm-exporter](https://github.com/NVIDIA/dcgm-exporter) | GPUs page, memory, temperature and XID-error alerts |
| `vllm` | a [vLLM](https://github.com/vllm-project/vllm) server (its `/metrics`) | LLM serving page, queue, KV cache and time-to-first-token alerts |
| `triton` | [NVIDIA Triton](https://github.com/triton-inference-server/server) (metrics on port 8002) | Triton page, failure-rate and queue-time alerts |
| `logs` | Loki (`datasources.loki`) | A log-based alert: error spike per container |

A page whose metrics are missing shows which exporter to add, instead of empty charts.

The `django`, `redis`, `postgres`, `mqtt` and `celery` presets are checked against the real exporters in
[dev/lab](dev/lab) (versions listed there); `core` is checked against node-exporter + cAdvisor. The `gpu`, `vllm` and
`triton` presets use the metric names from the projects' own documentation and were run against a stand-in that serves
those names to a real Prometheus; they have not been run on GPU hardware.
Logs need Loki with a container-name label (see [deploy/promtail.yml](deploy/promtail.yml)).

> **Docker 29+ and cAdvisor:** cAdvisor older than v0.53 can't talk to the Docker 29 API, so container names are
> missing and the Containers page stays empty. Use `ghcr.io/google/cadvisor:v0.53.0` or newer.

## Configuration

Everything is in one YAML file; see the commented [nigrani.example.yaml](nigrani.example.yaml). Highlights:

```yaml
presets: [core, django, redis, celery]

checks:
  - { id: api, name: API, type: http, target: "https://api.example.com/health/" }

channels:
  - id: slack-ops
    name: "Slack #ops"
    type: slack
    settings: { webhook_url: "${SLACK_WEBHOOK_URL}" }   # read from the environment when sending
    min_severity: warning

pages:                       # your own dashboard page
  - id: devices
    title: Devices
    requires: devices_online
    panels:
      - { title: Devices online, kind: area, expr: "sum(devices_online)", legend: online }
```

- Unknown keys are rejected at startup, so typos fail loudly.
- `${VAR}` and `${VAR:-default}` are expanded from the environment. Channel secrets are expanded at **send time**
  and never written to the database.
- Rules, channels and silences created in the UI live in SQLite (`/data/nigrani.db`). Preset rules are seeded once,
  so edits made in the UI survive restarts and upgrades.

### Alert rules

A rule is a PromQL expression plus thresholds. Every returned series is evaluated on its own (one alert per
container, per mount point, ...).

```yaml
rules:
  - id: queue-depth
    name: Job queue backing up
    expr: sum(celery_queue_length)
    warn: 100
    crit: 500
    for_seconds: 300      # must stay breached for 5 minutes before alerting
    direction: above      # or "below"
```

Use `unit: ratio` for queries returning fractions: `0.75` displays as `75.0%` in the UI and notifications.
Keep thresholds in query units (`warn: 0.8` displays as `80.0%`); no query scaling is needed.
Use `unit: percent` when the query already returns values on a 0–100 scale.

**Log-based rules.** A rule can read from Loki instead of Prometheus (`datasource: loki`). The expression is a LogQL
*metric* query, so it returns numbers and goes through the same thresholds, de-duplication, silences and channels:

```yaml
rules:
  - id: payment-errors
    name: Payment errors
    datasource: loki
    expr: sum(count_over_time({container="api"} |= "PaymentError" [5m]))
    crit: 10
    for_seconds: 0
```

On the Logs page, *Create alert from this search* builds one of these rules from the container, level and text you
are filtering on.

Servers without Loki skip log rules. The rule editor offers the data source when any server has Loki.
For a log rule, a series that disappears means "no matching lines", so the alert resolves on the next cycle instead of
after `alerts.absent_grace`. If Loki itself is down the rule shows a query error and nothing is resolved.

Behaviour worth knowing:

- **Pending → firing:** nothing is sent until the condition holds for `for_seconds`.
- **De-duplicated:** one message when it starts, one when it's resolved. Reminders every `alerts.repeat_interval`.
- **Preset rules stay current.** Preset rules are written to the database once so you can tune them. A fix shipped in a
  later release reaches rules you have **not** edited (it is applied on startup and logged); a rule whose expression or
  thresholds you changed is never overwritten.
- **Escalation:** warning → critical sends a new message.
- **Acknowledge:** on the Alerts page, *Acknowledge* (with an optional note, for 1h / 4h / 24h or until it resolves)
  tells your channels "✋ X is on it" once and pauses that alert's reminders. If it gets worse (warning to critical)
  or the time is up you are notified again; the resolved message credits who acknowledged it.
- **Delivery failures are retried** on the following evaluation cycles; failures are shown on the channel.
- **Restart-safe:** open incidents are reloaded, so a restart doesn't re-page you.
- **Silences** suppress messages but the incident is still recorded.
- **Meta alert:** if Nigrani itself can't reach Prometheus for 3 cycles you get a critical alert.
- **Containers:** configured `services` (and any container that ran for 10+ minutes) raise *Container down* when
  they stop. Stop tracking one from its drawer in the UI.

### Notification channels

| Type | Settings |
|---|---|
| `slack` | `webhook_url` (incoming webhook) |
| `teams` | `webhook_url` (a Teams *Workflows* webhook; Adaptive Card) |
| `discord` | `webhook_url` |
| `telegram` | `bot_token`, `chat_id` |
| `email` | `host`, `port`, `username`, `password`, `from`, `to` |
| `whatsapp` | `account_sid`, `auth_token`, `from_number`, `to_number` (via Twilio) |
| `webhook` | `url`, optional `secret` (adds an `X-Nigrani-Signature: sha256=<hmac>` header) |

Each channel has a minimum severity and optional quiet hours (critical alerts always come through).

**Custom messages.** Each channel can have its own title and body template, for example a runbook link in Slack and a
short line in Telegram. Leave them empty for the default text. The editor shows a live preview on a sample alert and
rejects unknown placeholders.

```yaml
channels:
  - id: slack-ops
    name: "Slack #ops"
    type: slack
    settings: { webhook_url: "${SLACK_WEBHOOK_URL}" }
    title_template: "{emoji} {rule} on {server}: {value}"
    body_template: "{series} for {duration}. {summary} Runbook: https://wiki.example.com/{rule}"
```

Placeholders: `{emoji}` `{status}` `{severity}` `{rule}` `{series}` `{value}` `{threshold}` `{server}` `{environment}`
`{duration}` `{summary}` `{link}` `{started_at}` `{kind}` `{acknowledged_by}` `{note}`, plus `{title}` and `{body}` for the default text (so you can
extend it instead of replacing it). Digests are not templated.

## Sentry

Show application errors next to your infrastructure metrics. Nigrani reads issues from the Sentry API (sentry.io or self-hosted);
it never writes to Sentry.

```yaml
sentry:
  url: https://sentry.io              # self-hosted: your Sentry address
  org: my-org                         # organization slug
  token: ${SENTRY_TOKEN}              # internal integration or user token with project:read and event:read
  projects: [api, worker]             # optional; empty = every project
```

- **Sentry page** lists issues with a search box (any [Sentry search](https://docs.sentry.io/concepts/search/), for example
  `is:unresolved level:error`), sort order and tiles for unresolved, new in 1h, new in 24h and fatal.
- **Rules**: choose the *sentry* data source and write a Sentry search as the expression. The value is the number of
  matching issues per project, so "critical above 0" means "any". The `sentry` preset adds *New errors in Sentry*
  (`is:unresolved firstSeen:-1h`, warning at 1, critical above 10) and *Fatal errors in Sentry*.
- An alert resolves when no issue matches any more. If Sentry cannot be reached or refuses the token, the rule shows that
  reason and no alert is resolved or raised because of it.
- The **incident page** of a Sentry alert lists the matching issues with a link to the same search in Sentry.
- With `servers:` each server can have its own `sentry:` block.

## AWS CloudWatch

Alert on AWS metrics without running an exporter. Nigrani calls CloudWatch directly (read-only) and signs requests itself,
so there is no AWS SDK in the image.

```yaml
cloudwatch:
  region: ap-south-1
  access_key_id: ${AWS_ACCESS_KEY_ID}        # optional: see "Credentials"
  secret_access_key: ${AWS_SECRET_ACCESS_KEY}
presets: [core, cloudwatch]                  # RDS CPU / storage, EC2 CPU / status check
```

A rule's data source is *cloudwatch* and its expression names a metric:

```
AWS/RDS CPUUtilization{DBInstanceIdentifier="*"} stat=Maximum period=300
```

- `Namespace MetricName`, then optional `{Dimension="value"}` pairs, then `stat=` (Average, Sum, Minimum, Maximum,
  SampleCount or a percentile such as `p99`) and `period=` (seconds, a multiple of 60; default `Average` and 300).
- `"*"` as a dimension value means every one that exists: one rule covers every database, and each gets its own alert.
  Give the exact dimension names the metric is published with (a metric is matched by its full set of dimensions).
  At most 50 series per rule.
- The value is the latest datapoint. An alert resolves when the metric recovers, or when the resource has had no
  datapoint for `absent_grace`.
- **Credentials**, first match wins: the keys above, the `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` /
  `AWS_SESSION_TOKEN` environment variables, then the EC2 instance role (IMDSv2), refreshed automatically. Prefer the
  role on AWS. The identity needs only `cloudwatch:GetMetricData` and `cloudwatch:ListMetrics`.
- If AWS refuses the credentials or CloudWatch is unavailable, the rule shows the reason and no alert is raised or
  resolved because of it.
- With `servers:` each server can have its own `cloudwatch:` block (for example another region or account).
- `endpoint_url` points at a VPC endpoint if you use one.

## Kubernetes

Watch a cluster without installing anything in it. Nigrani reads pods, nodes and deployments from the Kubernetes API
(read-only).

```yaml
kubernetes:
  url: https://my-cluster.example.com:6443
  token: ${KUBERNETES_TOKEN}          # a service account token, see examples/kubernetes-rbac.yaml
  ca_file: /config/k8s-ca.crt         # the API server's CA certificate (or verify_tls: false for a lab)
  namespaces: []                      # empty = every namespace
presets: [core, kubernetes]
```

- Inside the cluster, leave `url` empty: Nigrani uses the pod's service account and CA automatically.
- `examples/kubernetes-rbac.yaml` creates a service account that can only `get` and `list` pods, nodes and deployments.
- The **Kubernetes page** shows nodes ready, pods and how many are unhealthy, restarts in the last hour, deployments
  missing replicas, and a pod table with problems first and the same status words as `kubectl`.
- **Rules** use the *kubernetes* data source and name a metric, optionally narrowed with `namespace=` and `pod=` (a glob):

  | Metric | One alert per | Value |
  |---|---|---|
  | `crashloop` | pod | 1 while a container is in CrashLoopBackOff, ImagePullBackOff... or has just restarted repeatedly |
  | `restarts_1h` | pod | restarts of a pod whose last restart was within the hour |
  | `not_ready_minutes` | pod | minutes Pending or not Ready |
  | `pod_failed` | pod | 1 for a pod in phase Failed (for example evicted) |
  | `node_not_ready` | node | 1 for a node that is not Ready |
  | `deployment_unavailable` | deployment | replicas wanted but not available |

  Only series in trouble exist, so an alert resolves as soon as the pod recovers or is deleted. The `kubernetes` preset
  adds a rule for each. If the API is unreachable or refuses the token the rule shows why and nothing is raised or
  resolved because of it.
- With `servers:` each server can point at its own cluster.

## GPUs and LLM serving

![The GPUs page](docs/screenshots/gpus.png)

Three presets for machine-learning infrastructure. They need nothing but the exporter being scraped: with
[auto-discovery](#auto-discovery) Nigrani suggests each one as soon as its metrics show up in Prometheus (or add them to `presets:`).

| Preset | Page | Alert rules |
|---|---|---|
| `gpu` ([dcgm-exporter](https://github.com/NVIDIA/dcgm-exporter)) | GPUs: utilization, memory, temperature and power per GPU | memory almost full (92% / 98%), running hot (83 / 90 °C), an XID error on a GPU (critical); *GPU sitting idle* for an hour exists but is **off by default** |
| `vllm` | LLM serving: requests running and waiting, KV cache used, time to first token, end-to-end latency, tokens per second | request queue backing up (10 / 50 waiting), KV cache almost full (90% / 97%), slow time to first token (p95 over 2 s / 5 s) |
| `triton` | Triton: requests and failures per second, queue time, pending requests, GPU utilization | requests failing (1% / 5%), queue time high (100 ms / 500 ms) |

![LLM serving page](docs/screenshots/llm-serving.png)

Alerts are per GPU (`gpu-node-1 GPU 0`) or per model, so you see which one. The screenshots show sample data.

## Argo CD

![The Argo CD page](docs/screenshots/argocd.png)

Nigrani reads your applications from the Argo CD API (read-only): an **Argo CD** page with health, sync status, revision and
the error Argo reports for each one, alert rules per application, and every sync shown as a deploy marker on incident
pages and in the Deploys list. That answers "did a sync change something right before this broke?".

```yaml
argocd:
  url: https://argocd.example.com    # include the root path if you set one
  token: ${ARGOCD_TOKEN}
  # projects: [payments, data]       # default: every project the token can see
  # verify_tls: false                # for a lab with a self-signed certificate
  # ca_file: /certs/ca.crt

presets: [core, argocd]              # five rules, below
```

**Create a token that can only read.** In `argocd-cm` add an account with an API key, in `argocd-rbac-cm` let it `get`
applications, then generate the token:

```bash
kubectl -n argocd patch cm argocd-cm --type merge -p '{"data":{"accounts.nigrani":"apiKey"}}'
kubectl -n argocd patch cm argocd-rbac-cm --type merge -p '{"data":{"policy.csv":"p, nigrani, applications, get, */*, allow\n"}}'
argocd account generate-token --account nigrani        # use this as ARGOCD_TOKEN
```

If your Argo CD already has a `policy.csv`, add the `p, nigrani, ...` line to it instead of replacing it. Syncing or deleting
with this token is refused by Argo CD (HTTP 403).

Rule expressions name a metric, optionally narrowed with `app=<glob>`, `project=<name>` and `namespace=<name>`. The value is `1` for each
application in trouble, so a rule alerts once per application and resolves when it is healthy again. Use the rule's *for* to
say how long it may stay that way.

| Metric | Application that... | `argocd` preset |
|---|---|---|
| `out_of_sync` | differs from Git | warning after 15 min |
| `degraded` | is Degraded or Missing | critical after 5 min |
| `sync_failed` | failed its last sync, or Argo is retrying one that keeps failing | critical after 1 min |
| `sync_error` | has an error condition: cannot reach the repository, manifests do not render | warning after 5 min |
| `progressing` | is still Progressing | warning after 30 min (a rollout that never finishes) |

## Datadog

Use Datadog as a data source, and see its failing monitors next to everything else. Read-only.

```yaml
datadog:
  site: datadoghq.com                 # datadoghq.eu, us3.datadoghq.com, us5.datadoghq.com, ap1.datadoghq.com ...
  api_key: ${DD_API_KEY}
  app_key: ${DD_APP_KEY}              # an application key; scopes timeseries_query and monitors_read
presets: [core, datadog]              # host CPU, memory and disk rules from the Datadog Agent's metrics
```

- A rule's data source is *datadog* and its expression is a Datadog metric query, for example
  `avg:system.cpu.user{env:prod} by {host}` (arithmetic works too, `... * 100`). Each series, such as each host in
  `by {host}`, is its own alert and uses its latest value from the last ten minutes. Datadog's tags become the alert's
  labels.
- The **Datadog page** counts monitors by state and lists the ones that are Alert, Warn or No Data, worst first, linking to
  each in Datadog.
- The metric is charted on the incident page like any other.
- If Datadog refuses the keys or is unreachable the rule shows why and nothing is raised or resolved because of it.
- With `servers:` each server can have its own `datadog:` block (another site or organization).

## Azure Monitor

Alert on Azure metrics without an exporter. Nigrani signs in as a Microsoft Entra ID service principal and reads metrics
(read-only).

```yaml
azure:
  tenant_id: ${AZURE_TENANT_ID}
  client_id: ${AZURE_CLIENT_ID}
  client_secret: ${AZURE_CLIENT_SECRET}      # the secret's value, not its id
  subscription_id: ${AZURE_SUBSCRIPTION_ID}
  resource_groups: []                        # empty = the whole subscription
presets: [core, azure]                       # VM, PostgreSQL, SQL and App Service plan rules
```

Create the service principal and let it read metrics (it needs nothing else):

```bash
az ad sp create-for-rbac --name nigrani --role "Monitoring Reader" --scopes /subscriptions/<subscription id>
```

A rule's data source is *azure* and its expression names a resource type and a metric. It covers every resource of that
type, each with its own alert:

```
Microsoft.DBforPostgreSQL/flexibleServers cpu_percent aggregation=Maximum interval=PT5M
Microsoft.Compute/virtualMachines "Percentage CPU" resourcegroup=prod-rg resource=web-*
```

- Quote a metric name that has spaces. `aggregation=` is Average (default), Minimum, Maximum, Total or Count;
  `interval=` is PT1M, PT5M, PT15M, PT30M, PT1H, PT6H, PT12H or P1D; `resourcegroup=` and `resource=` (a glob) narrow
  the set. At most 50 resources per rule.
- The value is the latest datapoint. Metric names are the ones in the Azure portal's metric picker (or
  `az monitor metrics list-definitions`).
- If Azure refuses the credentials or is unreachable the rule shows why and nothing is raised or resolved because of it.
- Sovereign clouds: set `authority_url` and `management_url`. With `servers:` each server can have its own `azure:` block.

## Grafana links

Already have Grafana dashboards? Nigrani can link to them. It never talks to Grafana; it only builds URLs for your browser.

```yaml
grafana:
  url: https://grafana.example.com           # the address your browser uses
  prometheus_datasource: <datasource UID>    # Connections > Data sources > the UID in the URL
  loki_datasource: <datasource UID>
  dashboards:
    - title: Container dashboard
      url: /d/abc123/containers?var-container={container}&from={from}&to={to}
      where: [incident, container]           # incident | container | host | overview
    - { title: Host, url: /d/xyz789/node-exporter, where: [host, overview] }
```

- **Open in Grafana** (incident page, rule editor, Logs page) opens Explore (Grafana 10+) with the exact query and,
  for an incident, the time range around it.
- **Dashboard links** appear where you list them. Placeholders `{container}` `{server}` `{rule}` `{series}` `{from}`
  `{to}` (milliseconds) are URL-encoded; a link that needs a value the place doesn't have (a container on the host
  page) is left out. Relative URLs are joined to `grafana.url`.
- With `servers:` each server can have its own `grafana:` block.

## Auto-discovery

![Nigrani suggesting presets it found in Prometheus](docs/screenshots/discovery.png)

Start with nothing but a Prometheus URL and Nigrani looks at the metric names Prometheus already has. Anything it
recognises (Redis, PostgreSQL, Django, Celery, an MQTT broker, AWS RDS through YACE, host and container metrics) shows
up on the Overview as *Found in your Prometheus*, with what it would add: dashboard pages, tiles and alert rules. Press
**Turn on** and it is live straight away, with no restart and no edit to `nigrani.yaml`. The same list, with a switch for
each, is on the **Integrations** page.

- What you turn on here is remembered (it lives in the data volume) and can be turned off again, which also removes the
  preset's alert rules. Presets listed under `presets:` in `nigrani.yaml` stay under the file's control.
- Anything you defined yourself with the same id (a tile, a page or an edited rule) wins over the preset.
- Detection looks for one telling metric per preset, for example `redis_up` or `pg_up`. If your exporter exposes it
  under another name, use *Turn on anyway*.
- Editors and admins can turn presets on and off; viewers see the suggestions.

## SLOs and burn-rate alerts

![The SLOs page](docs/screenshots/slos.png)

A threshold alert says "errors are high right now". An SLO says how much unreliability you can afford: 99.9% over 30 days
leaves an **error budget** of 0.1%, about 43 minutes. Nigrani tracks how much of it is left and alerts on the **burn rate**,
how fast it is being spent compared with an even spend (1× uses exactly the budget over the window).

```yaml
slos:
  - id: web-availability
    name: Web availability
    target: 99.9                 # percent
    window_days: 30              # 1-90
    total:  sum(rate(django_http_responses_total_by_status_total[{{window}}]))
    errors: sum(rate(django_http_responses_total_by_status_total{status=~"5.."}[{{window}}]))

  - id: fast-responses           # latency: the share of requests answered within 500 ms
    name: Responses under 500 ms
    target: 99
    total: sum(rate(django_http_requests_latency_seconds_by_view_method_count[{{window}}]))
    good:  sum(rate(django_http_requests_latency_seconds_by_view_method_bucket{le="0.5"}[{{window}}]))

  - id: website-uptime           # no Prometheus needed: use one of your uptime checks
    name: Website uptime
    target: 99.5
    check: web                   # the id of a check under `checks:`
```

- The SLI is `total` plus either `errors` or `good` (queries that return a rate or a count; several series are summed), or an
  uptime check. Write `{{window}}` where the range goes: Nigrani fills in `5m`, `1h`, `6h`... as it needs them.
- Alerts use two windows each, so they fire only while it is real *and* still happening, and clear soon after it stops. With a
  30-day window:

| Alert | Fires when the burn rate is over... | Severity | Meaning |
|---|---|---|---|
| Fast burn | 14.4× in the last 1 h **and** 5 min | critical | 2% of the budget gone in an hour |
| Slow burn | 6× in 6 h **and** 30 min | critical | 5% gone in six hours |
| Steady burn | 3× in 1 d **and** 2 h | warning | 10% gone in a day |
| Gradual burn | 1× in 3 d **and** 6 h | warning | on course to use the whole budget |
| Budget exhausted | the SLI is under the target for the whole window | critical | |

  The factors scale with `window_days` (a 7-day SLO alerts at lower factors) and windows longer than the SLO window are left out.
- The **SLOs** page shows the current SLI, how much budget is left (in percent and as minutes of equivalent downtime) and every
  alert tier with its burn rate right now.
- No traffic yet shows "No data yet" and raises nothing. If Prometheus cannot be queried, open alerts stay open: an outage
  is not a recovery. `servers: [prod]` limits an SLO to some servers.

## Status page

![Status page](docs/screenshots/status-page.png)

A public page for your users, at `/#/status`, with no login. It shows each uptime check with **90 days of daily uptime**
(one bar per day: green, amber for a few failed checks, red for an outage), the last 7 days of check incidents, and the
updates you post. Internal alert names never appear on it.

```yaml
status_page:
  enabled: true
  title: Acme status
  days: 90                       # 7-365
```

Post an update from **Uptime → Status page updates** (editors and admins): an *incident* you are working on, *planned
maintenance* with a start and end (it shows as scheduled until it begins, and the banner reads "Scheduled maintenance"
while it runs), or a plain *notice*. Mark it resolved when it is over. The same data is available as JSON at
`/api/public/status`.

## AI assistant

![AI explanation of an incident](docs/screenshots/ai-explain.png)

Optional, off by default. With an [Anthropic API key](https://console.anthropic.com/) Nigrani can:

- **Explain an incident.** The incident page gets an *Explain this incident* button. The answer has three parts: what
  happened (with the numbers), the likely cause, and what to check next. It is saved, so opening the page again costs
  nothing; *Regenerate* asks again.
- **Draft a rule from a sentence.** In *New alert rule*, type "tell me when the disk is more than 85% full" and press
  *Draft*. The form is filled in, the query is run against your Prometheus so you see its current value, and nothing is
  saved until you press Save.

```yaml
ai:
  enabled: true
  api_key: ${ANTHROPIC_API_KEY}
  model: claude-opus-5-5         # any Anthropic model id
  effort: low                    # low | medium | high: higher thinks longer and costs more
```

Nothing is sent in the background. A request goes out only when someone presses one of those buttons, and it carries the
data of that incident (metric values, container CPU and memory, restarts, deploys, related alert names, Sentry issue
titles) or the sentence typed for the rule, plus your Prometheus metric names for rule drafts. Only editors and admins
can press the buttons; viewers can read an explanation that already exists. Everything the model reads is treated as
untrusted data, its answer is shown as plain text, and a drafted rule is validated like any other before you can save it.
Calls are logged in the audit log (`ai.explain`, `ai.rule`).

## Demo mode

```bash
docker run --rm -p 8080:8080 -e NIGRANI_DEMO=1 ghcr.io/nikhilrai-tech/nigrani:latest
```

Open `http://localhost:8080`. There is no login. Instead of Prometheus, Nigrani generates believable sample data for the
`core` and `django` presets (a host, five containers, a web app), starts with a few finished incidents and 90 days of
uptime history, and every 90 minutes a 15 minute bad spell makes the sample app throw 5xx errors and slow down, so
alerts really fire and resolve. The AI buttons work with a labelled, canned example. The UI is read-only: nothing can be
created, changed or sent, so it is safe to host publicly as a live demo.

Settings in a config file you mount (`NIGRANI_CONFIG`) still apply on top, for example `app.name` or `status_page`.

**Host your own live demo** on Render's free tier (it pulls the public image, nothing to build):

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/nikhilrai-tech/Nigrani)

The button reads [render.yaml](render.yaml). Free services sleep after 15 minutes without visitors and wake in under a minute
on the next request.

## Backup and restore

The **Backup** page (or `GET /api/backup`) exports everything you configured in the UI (alert rules, notification
channels and active silences) as one JSON file; use it to move to a new server or recover from a mistake. Incident
history is not included.

- **Credentials are left out by default.** Webhook URLs and tokens are exported as `null`; values that reference an
  environment variable (`${SLACK_URL}`) are kept because they are not secrets. *Include credentials* produces a file
  with working secrets: treat it like a password and never commit it.
- **Restore shows a dry run first.** Choosing a file lists what would be created, overwritten or skipped. If anything
  in the file is invalid (an unknown server, inverted thresholds, a typo in a message template...) nothing is imported.
- **Nothing is ever deleted.** *merge* keeps existing rules and channels that have the same id; *overwrite* replaces them.
  A credential missing from the file never erases the one already stored.
- A channel whose credentials were not in the file is created **disabled** and listed, so it cannot fail silently.

The API equivalent is `POST /api/backup/import?mode=merge|overwrite&dry_run=true|false` (dry run is the default).

## Users, roles and single sign-on

The account in `auth.username` / `auth.password` is the **configured administrator**: it always works, is always an
admin and cannot be edited in the UI, so you can never lock yourself out. Everyone else is added on the **Users** page
(admins only) or signs in with single sign-on.

| Role | Can |
|---|---|
| **viewer** | Look at everything: dashboards, alerts, incident pages, logs. Change nothing. |
| **editor** | Also acknowledge and silence alerts, create/edit rules and channels, send test messages, export a backup. |
| **admin** | Also manage users, restore backups, export credentials, read the audit log. |

Role changes and disabling an account apply to open sessions within seconds. Passwords are stored as scrypt hashes
(at least 10 characters). The **Audit log** records sign-ins (including failed and refused ones) and every change, with
who did it and from where.

**Single sign-on** works with any OpenID Connect provider. For Google: create an OAuth client (type *Web application*)
in Google Cloud Console, add `https://nigrani.example.com/api/auth/oidc/callback` as an authorised redirect URI, then:

```yaml
app: { public_url: "https://nigrani.example.com" }
auth:
  oidc:
    issuer: https://accounts.google.com
    client_id: <client id>
    client_secret: ${GOOGLE_CLIENT_SECRET}
    label: Sign in with Google
    allowed_domains: [example.com]      # any verified address at this domain...
    allowed_emails: []                  # ...or these specific addresses
    admin_emails: [you@example.com]     # first sign-in creates an admin
    editor_emails: []
    default_role: viewer                # for everyone else who is allowed in
```

Nigrani refuses to start with SSO configured but nobody allowed (otherwise every account at the provider could sign
in). The first sign-in creates the user with a role from those lists; after that the role is whatever an admin sets on the
Users page. Only verified e-mail addresses are accepted. Users and the audit log are not part of a backup.

## Security

- The UI and API require a login, and every change is checked against the signed-in person's role. Nigrani refuses to start without a password
  (`NIGRANI_ALLOW_NO_AUTH=1` exists for local development only).
- Login is rate-limited, sessions are signed `HttpOnly` cookies, and state-changing requests need a custom header
  (CSRF protection). Secrets are masked in API responses.
- **Serve it over HTTPS** (a reverse proxy such as Caddy/Traefik/nginx, or a VPN) when exposed to the internet.
- **Keep Prometheus, Loki and the exporters private.** Nigrani is the only thing that needs to be reachable. In
  particular don't publish Prometheus' port to the internet; it has no authentication.
- Never commit `.env` or your real `nigrani.yaml` (both are in `.gitignore`).
- Run **one** Nigrani per database (`/data`). Two instances sharing a SQLite file would each raise their own copy of every alert.

## Architecture

```
Prometheus ─┐
Loki ───────┼─►  Nigrani backend (FastAPI)  ──►  Slack / Teams / Telegram / email / webhook ...
GitHub API ─┤    rules · incidents · checks
HTTP/TCP ───┘    SQLite (/data)
                       ▲
                       └──  React UI (served by the same container)
```

One container, one SQLite file, no extra services. Backend in [backend/nigrani](backend/nigrani), UI in
[frontend/src](frontend/src), built-in dashboards in [backend/nigrani/presets](backend/nigrani/presets).

## Development

```bash
# backend
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt pytest
(cd backend && python -m pytest -q)
NIGRANI_ALLOW_NO_AUTH=1 NIGRANI_PROMETHEUS_URL=http://localhost:9090 NIGRANI_DATA_DIR=./data \
  uvicorn nigrani.main:app --app-dir backend --port 8080

# frontend (proxies /api to :8080)
cd frontend && npm install && npm run dev
```

Presets are PromQL against third-party metric names, so they are tested against real exporters: see
[dev/lab/README.md](dev/lab/README.md) (`docker compose up`, `./traffic.sh`, `python3 verify.py`).

To add a preset, drop a YAML file with `tiles`, `pages` and `rules` into `backend/nigrani/presets/` (see
`redis.yaml` for the shape); it is picked up by name.

## Community

Questions and ideas go in [Discussions](https://github.com/nikhilrai-tech/Nigrani/discussions); bugs and feature requests
in [Issues](https://github.com/nikhilrai-tech/Nigrani/issues). Pull requests are welcome, start with
[CONTRIBUTING.md](CONTRIBUTING.md) (a new data source such as GCP Cloud Monitoring or New Relic follows the shape of
`backend/nigrani/datadog.py`). If Nigrani saves you time, a star helps other people find it.

## License

MIT. See [LICENSE](LICENSE).
