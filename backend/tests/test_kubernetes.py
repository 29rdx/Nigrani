import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import FakeProm
from nigrani.api import create_app
from nigrani.config import KubernetesCfg, load_config
from nigrani.kubernetes import Kubernetes, KubernetesError, deployment_view, node_view, parse, pod_view
from nigrani.prom import PromQueryError, series_key

NOW = 1_800_000_000.0


def iso(ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - ago))


def pod(name, ns="shop", phase="Running", ready=True, waiting=None, restarts=0, last_end=None, terminated=None, deleted=False, created=7200, node="n1"):
    cs = {"name": "c", "ready": ready, "restartCount": restarts, "state": {"running": {}}, "lastState": {}}
    if waiting:
        cs["state"] = {"waiting": {"reason": waiting}}
    if terminated:
        cs["state"] = {"terminated": {"reason": terminated}}
    if last_end is not None:
        cs["lastState"] = {"terminated": {"finishedAt": iso(last_end), "reason": "Error"}}
    meta = {"name": name, "namespace": ns, "creationTimestamp": iso(created)}
    if deleted:
        meta["deletionTimestamp"] = iso(1)
    return {"metadata": meta, "spec": {"nodeName": node, "containers": [{"name": "c"}]},
            "status": {"phase": phase, "containerStatuses": [cs],
                       "conditions": [{"type": "Ready", "status": "True" if ready else "False", "lastTransitionTime": iso(600)}]}}


def node(name, ready=True, pressure=()):
    conds = [{"type": "Ready", "status": "True" if ready else "False"}] + [{"type": t, "status": "True"} for t in pressure]
    return {"metadata": {"name": name}, "status": {"conditions": conds, "nodeInfo": {"kubeletVersion": "v1.31.5", "osImage": "Linux"}}}


def deployment(name, want, avail, ns="shop"):
    return {"metadata": {"name": name, "namespace": ns}, "spec": {"replicas": want}, "status": {"availableReplicas": avail, "readyReplicas": avail}}


class Cluster:
    def __init__(self):
        self.pods = [pod("web-1"), pod("web-2"), pod("api-1", ns="prod", waiting="CrashLoopBackOff", ready=False, restarts=7, last_end=60),
                     pod("pay-1", waiting="ImagePullBackOff", ready=False), pod("job-1", phase="Succeeded", ready=False, terminated="Completed"),
                     pod("old-1", ns="prod", phase="Failed", ready=False), pod("flaky-1", restarts=4, last_end=100)]
        self.nodes = [node("n1"), node("n2", ready=False)]
        self.deployments = [deployment("web", 2, 2), deployment("reports", 3, 1)]
        self.status = 200
        self.requests: list[httpx.Request] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "x"})
        if req.headers.get("authorization") != "Bearer tok":
            return httpx.Response(401, json={})
        path, ns = req.url.path, None
        if "/namespaces/" in path:
            ns = path.split("/namespaces/")[1].split("/")[0]
        items = {"pods": self.pods, "nodes": self.nodes, "deployments": self.deployments}[path.rsplit("/", 1)[1]] if path.rsplit("/", 1)[1] in ("pods", "nodes", "deployments") else None
        if items is None:
            return httpx.Response(200, json={"gitVersion": "v1.31.5"})
        if ns:
            items = [i for i in items if i["metadata"].get("namespace") == ns]
        return httpx.Response(200, json={"items": items, "metadata": {}})


def make(cluster=None, **kw):
    cluster = cluster or Cluster()
    cfg = KubernetesCfg(url="https://k8s.test", token="tok", **kw)
    return Kubernetes(cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(cluster.handler))), cluster


def run(c):
    return asyncio.run(c)


def labels(rows):
    return {(r["labels"].get("pod") or r["labels"].get("deployment") or r["labels"].get("node")): r["value"] for r in rows}


def test_pod_status_follows_what_kubectl_shows():
    v = lambda p: pod_view(p, NOW)  # noqa: E731
    assert v(pod("a"))["status"] == "Running" and v(pod("a"))["ready"] is True
    assert v(pod("a", waiting="CrashLoopBackOff", ready=False))["status"] == "CrashLoopBackOff"
    assert v(pod("a", waiting="ContainerCreating", ready=False))["status"] == "ContainerCreating"
    assert v(pod("a", phase="Pending", ready=False))["status"] == "Pending"
    assert v(pod("a", terminated="OOMKilled", ready=False))["status"] == "OOMKilled"
    assert v(pod("a", deleted=True))["status"] == "Terminating"
    done = v(pod("j", phase="Succeeded", ready=False, terminated="Completed"))
    assert done["status"] == "Succeeded" and done["not_ready_minutes"] == 0


def test_crashloop_covers_the_running_moments_between_restarts():
    assert pod_view(pod("a", restarts=5, last_end=30), NOW)["crashloop"] is True       # Running again, but just crashed
    assert pod_view(pod("a", restarts=5, last_end=4000), NOW)["crashloop"] is False    # old restarts
    assert pod_view(pod("a", restarts=1, last_end=30), NOW)["crashloop"] is False      # one restart is not a loop
    assert pod_view(pod("a", restarts=5, last_end=4000), NOW)["restarts_1h"] == 0
    assert pod_view(pod("a", restarts=5, last_end=100), NOW)["restarts_1h"] == 5


def test_other_views():
    assert node_view(node("n", pressure=("DiskPressure",)))["pressure"] == ["DiskPressure"] and not node_view(node("n", ready=False))["ready"]
    assert deployment_view(deployment("d", 3, 1)) == {"namespace": "shop", "name": "d", "desired": 3, "available": 1, "ready": 1}


def test_parse():
    assert parse("crashloop") == ("crashloop", {}) and parse("restarts_1h namespace=prod pod=api-*") == ("restarts_1h", {"namespace": "prod", "pod": "api-*"})
    for bad in ("", "cpu", "crashloop zone=a", "crashloop namespace="):
        with pytest.raises(PromQueryError):
            parse(bad)


def test_every_metric_returns_only_what_is_in_trouble(monkeypatch):
    c, _ = make()
    monkeypatch.setattr("time.time", lambda: NOW)
    assert labels(run(c.instant("crashloop"))) == {"api-1": 1.0, "pay-1": 1.0, "flaky-1": 1.0}
    assert labels(run(c.instant("restarts_1h"))) == {"api-1": 7.0, "flaky-1": 4.0}
    assert set(labels(run(c.instant("not_ready_minutes")))) == {"api-1", "pay-1"}          # succeeded jobs and ready pods are left out
    assert labels(run(c.instant("pod_failed"))) == {"old-1": 1.0}
    assert labels(run(c.instant("node_not_ready"))) == {"n2": 1.0}
    assert labels(run(c.instant("deployment_unavailable"))) == {"reports": 2.0}


def test_filters_and_namespace_scoping():
    c, cl = make()
    assert labels(run(c.instant("crashloop namespace=prod"))) == {"api-1": 1.0}
    assert labels(run(c.instant("crashloop pod=pay-*"))) == {"pay-1": 1.0}
    c2, cl2 = make(namespaces=["prod"])
    assert set(labels(run(c2.instant("crashloop")))) == {"api-1"}
    assert all("/namespaces/prod/" in r.url.path for r in cl2.requests)


def test_pagination_is_followed():
    pages = {"": ({"items": [pod("a")], "metadata": {"continue": "t2"}}), "t2": ({"items": [pod("b")], "metadata": {}})}
    seen = []

    def h(req):
        tok = req.url.params.get("continue", "")
        seen.append(tok)
        return httpx.Response(200, json=pages[tok])
    c = Kubernetes(KubernetesCfg(url="https://k8s.test", token="tok"), client=httpx.AsyncClient(transport=httpx.MockTransport(h)))
    assert [p["name"] for p in run(c.pods())] == ["a", "b"] and seen == ["", "t2"]


@pytest.mark.parametrize("status,word", [(401, "refused the token"), (403, "refused the token"), (404, "kubernetes.url"), (500, "HTTP 500")])
def test_failures_are_readable_infrastructure_errors(status, word):
    c, cl = make()
    cl.status = status
    with pytest.raises(KubernetesError, match=word):
        run(c.instant("crashloop"))
    assert word in c.last_error


def test_certificate_problems_say_what_to_set():
    def h(req):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate")
    c = Kubernetes(KubernetesCfg(url="https://k8s.test", token="tok"), client=httpx.AsyncClient(transport=httpx.MockTransport(h)))
    with pytest.raises(KubernetesError, match="ca_file"):
        run(c.instant("crashloop"))


def mount_service_account(monkeypatch, tmp_path, ca=False):
    sa = tmp_path / "sa"
    sa.mkdir()
    (sa / "token").write_text("sa-token\n")
    if ca:
        (sa / "ca.crt").write_text("not a real certificate")
    monkeypatch.setattr("nigrani.config.K8S_SA_DIR", sa)
    return sa


def test_in_cluster_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT", "443")
    mount_service_account(monkeypatch, tmp_path)
    cfg = KubernetesCfg()
    assert cfg.enabled
    k = Kubernetes(cfg, client=httpx.AsyncClient())
    assert k.base == "https://10.0.0.1:443"
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST")
    assert not KubernetesCfg().enabled and KubernetesCfg(url="https://x").enabled


def test_config_per_server(tmp_path):
    f = tmp_path / "n.yaml"
    f.write_text("kubernetes: {url: 'https://a.test', token: x}\nservers:\n  - {id: a}\n  - {id: b, kubernetes: {url: 'https://b.test'}}\n")
    v = {s.id: s for s in load_config(str(f)).server_views()}
    assert v["a"].kubernetes.url == "https://a.test" and v["b"].kubernetes.url == "https://b.test"
    with pytest.raises(ValueError):
        KubernetesCfg(url="ftp://x")


def app_with(tmp_path, kube):
    cfg = load_config(None)
    cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    return TestClient(create_app(cfg, prom=FakeProm(), kubernetes={"default": kube}))


def test_api_overview_rules_and_incident(tmp_path, monkeypatch):
    kube, _ = make()
    monkeypatch.setattr("time.time", lambda: NOW)
    H = {"X-Requested-With": "nigrani"}
    with app_with(tmp_path, kube) as c:
        c.post("/api/login", json={"username": "admin", "password": "pw"})
        me = c.get("/api/me").json()["servers"][0]
        assert me["kubernetes"] is True and me["datasources"] == ["prometheus", "kubernetes"]
        d = c.get("/api/kubernetes").json()
        assert d["summary"] == {"nodes": 2, "nodes_ready": 1, "pods": 7, "pods_unhealthy": 4, "restarts_1h": 11, "deployments": 2, "deployments_unavailable": 1}
        assert d["namespaces"] == ["prod", "shop"] and [x["name"] for x in d["deployments"]] == ["reports"]
        assert d["pods"][0]["crashloop"] is True and d["pods"][-1]["status"] in ("Running", "Succeeded")   # trouble first
        assert {p["namespace"] for p in c.get("/api/kubernetes?namespace=prod").json()["pods"]} == {"prod"}
        body = {"name": "Crash", "expr": "crashloop namespace=shop", "crit": 0, "datasource": "kubernetes"}
        prev = c.post("/api/rules/test", json=body, headers=H).json()
        assert {x["series"] for x in prev["series"]} == {"shop pay-1", "shop flaky-1"}
        assert c.post("/api/rules/test", json={**body, "expr": "cpu"}, headers=H).status_code in (400, 422)
        made = c.post("/api/rules", json=body, headers=H).json()
        labels_ = {"namespace": "shop", "pod": "pay-1"}
        iid = c.app.state.store.create_incident(source_id=made["id"], series_key=series_key(labels_), rule_name="Crash", series="pay-1",
                                                labels=labels_, severity="critical", started_at=NOW - 60, server="default")
        inc = c.get(f"/api/incidents/{iid}").json()
        assert inc["chart"] is None and inc["problems"] == []


def test_api_without_kubernetes(tmp_path):
    cfg = load_config(None)
    cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    with TestClient(create_app(cfg, prom=FakeProm())) as c:
        c.post("/api/login", json={"username": "admin", "password": "pw"})
        assert c.get("/api/kubernetes").status_code == 404
        r = c.post("/api/rules", json={"name": "K", "expr": "crashloop", "crit": 0, "datasource": "kubernetes"}, headers={"X-Requested-With": "nigrani"})
        assert r.status_code == 422 and "kubernetes" in r.json()["detail"]


def test_api_reports_an_unreachable_cluster(tmp_path):
    kube, cl = make()
    cl.status = 401
    with app_with(tmp_path, kube) as c:
        c.post("/api/login", json={"username": "admin", "password": "pw"})
        r = c.get("/api/kubernetes")
        assert r.status_code == 502 and "refused the token" in r.json()["detail"]


def test_the_kubernetes_preset_loads(tmp_path):
    f = tmp_path / "n.yaml"
    f.write_text("presets: [kubernetes]\n")
    rules = {r.id: r for r in load_config(str(f)).rules}
    assert set(rules) == {"k8s-crashloop", "k8s-restarts", "k8s-pod-not-ready", "k8s-pod-failed", "k8s-node-not-ready", "k8s-deployment-unavailable"}
    for r in rules.values():
        assert r.datasource == "kubernetes"
        parse(r.expr)


def test_the_environment_variable_alone_does_not_mean_in_cluster(monkeypatch, tmp_path):
    """Render (and other platforms on Kubernetes) set KUBERNETES_SERVICE_HOST but mount no service account: Nigrani must
    start normally, with Kubernetes simply not configured, instead of crashing on the missing CA file."""
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setattr("nigrani.config.K8S_SA_DIR", tmp_path / "nothing-here")
    assert not KubernetesCfg().enabled
    from fastapi.testclient import TestClient
    from nigrani.api import create_app
    cfg = load_config(None)
    cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    with TestClient(create_app(cfg, prom=FakeProm())) as c:
        assert c.get("/api/health").status_code == 200
        assert c.app.state.cfg.kubernetes.enabled is False


def test_token_without_ca_still_starts_and_ca_is_used_when_present(monkeypatch, tmp_path):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    mount_service_account(monkeypatch, tmp_path)
    assert KubernetesCfg().enabled
    Kubernetes(KubernetesCfg())                              # no ca.crt in the mount: falls back to the system certificates
    k = Kubernetes(KubernetesCfg(verify_tls=False))
    assert k._token() == "sa-token"


def test_a_missing_ca_file_is_a_clear_config_error(tmp_path):
    from nigrani.config import ConfigError
    with pytest.raises(ConfigError, match="ca_file not found: /nope/ca.crt"):
        Kubernetes(KubernetesCfg(url="https://k8s.test", ca_file="/nope/ca.crt"))
