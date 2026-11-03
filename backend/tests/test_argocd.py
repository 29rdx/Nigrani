import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import FakeProm
from nigrani.api import create_app
from nigrani.argocd import ArgoCD, ArgoCDError, app_view, parse
from nigrani.config import ArgoCDCfg, ConfigError, load_config
from nigrani.prom import PromQueryError

TOKEN = "argo-token"
H = {"X-Requested-With": "nigrani"}


def run(coro):
    return asyncio.run(coro)


def app(name, project="default", sync="Synced", health="Healthy", phase="Succeeded", ns="prod", conditions=None, history=None,
        revision="a1b2c3d4e5f6", auto=True):
    """An Application as Argo CD's /api/v1/applications returns it (the fields Nigrani reads)."""
    return {
        "metadata": {"name": name, "namespace": "argocd"},
        "spec": {"project": project, "source": {"repoURL": "https://git.test/acme/deploy.git", "path": f"apps/{name}", "targetRevision": "main"},
                 "destination": {"server": "https://kubernetes.default.svc", "namespace": ns},
                 "syncPolicy": {"automated": {"prune": True}} if auto else {}},
        "status": {"sync": {"status": sync, "revision": revision}, "health": {"status": health, "message": "" if health == "Healthy" else "1 pod is crash-looping"},
                   "operationState": {"phase": phase, "message": "successfully synced" if phase == "Succeeded" else "one or more objects failed to apply",
                                      "finishedAt": "2026-11-03T08:00:00Z", "startedAt": "2026-11-03T07:59:50Z"},
                   "history": history if history is not None else [
                       {"id": 0, "revision": "0000000aaaa", "deployedAt": "2026-11-02T10:00:00Z"},
                       {"id": 1, "revision": revision, "deployedAt": "2026-11-03T08:00:00Z"}],
                   "conditions": conditions or []},
    }


class Server:
    def __init__(self, apps=None):
        self.apps = apps if apps is not None else []
        self.requests: list[httpx.Request] = []
        self.status = 200

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "x"})
        if req.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"error": "invalid session"})
        if req.url.path == "/api/v1/applications":
            return httpx.Response(200, json={"metadata": {"resourceVersion": "1"}, "items": self.apps or None})
        return httpx.Response(404, text="not found")


def client(server, **cfg):
    return ArgoCD(ArgoCDCfg(url="https://argocd.test", token=TOKEN, **cfg), client=httpx.AsyncClient(transport=httpx.MockTransport(server.handler)))


FLEET = [app("web"), app("api", sync="OutOfSync"), app("worker", health="Degraded"), app("jobs", project="data", health="Progressing"),
         app("billing", project="payments", phase="Failed"),
         app("search", conditions=[{"type": "ComparisonError", "message": "rpc error: repository not found"},
                                   {"type": "OrphanedResourceWarning", "message": "ignored"}])]


def names(series):
    return sorted(s["labels"]["name"] for s in series)


def test_parse_rejects_typos_with_the_valid_choices():
    assert parse("out_of_sync project=payments app=api-*") == ("out_of_sync", {"project": "payments", "app": "api-*"})
    with pytest.raises(PromQueryError, match="out_of_sync"):
        parse("outofsync")
    with pytest.raises(PromQueryError, match="unknown filter"):
        parse("degraded team=x")


def test_each_metric_returns_only_applications_in_trouble():
    s = Server(FLEET)
    c = client(s)
    assert names(run(c.instant("out_of_sync"))) == ["api"]
    assert names(run(c.instant("degraded"))) == ["worker"]
    assert names(run(c.instant("progressing"))) == ["jobs"]
    assert names(run(c.instant("sync_failed"))) == ["billing"]
    assert names(run(c.instant("sync_error"))) == ["search"]           # warnings (Orphaned...) are not errors
    assert all(r["value"] == 1.0 for r in run(c.instant("degraded")))


def test_missing_counts_as_degraded_and_filters_narrow_it():
    s = Server([app("a", health="Missing"), app("b", project="data", health="Degraded"), app("ab-1", health="Degraded", ns="stage")])
    c = client(s)
    assert names(run(c.instant("degraded"))) == ["a", "ab-1", "b"]
    assert names(run(c.instant("degraded project=data"))) == ["b"]
    assert names(run(c.instant("degraded app=ab-*"))) == ["ab-1"]
    assert names(run(c.instant("degraded namespace=stage"))) == ["ab-1"]


def test_an_empty_install_answers_items_null():
    c = client(Server([]))
    assert run(c.instant("out_of_sync")) == [] and run(c.healthy()) is True


def test_a_sync_that_argo_keeps_retrying_counts_as_failed():
    """Seen on a real Argo CD: with auto-sync a failing sync stays `Running` while it retries, with `retryCount` rising."""
    a = app("flaky", phase="Running")
    a["status"]["operationState"].update(retryCount=3, message='one or more objects failed to apply, reason: namespaces "x" not found. Retrying attempt #3')
    ok = app("busy", phase="Running")                                          # a normal first attempt is not a failure
    c = client(Server([a, ok]))
    assert names(run(c.instant("sync_failed"))) == ["flaky"]
    assert app_view(a)["retries"] == 3 and "not found" in app_view(a)["op_message"]


def test_the_application_view():
    v = app_view(app("api", project="payments", sync="OutOfSync", conditions=[{"type": "SyncError", "message": "boom"}]))
    assert (v["name"], v["project"], v["namespace"], v["sync"], v["revision"]) == ("api", "payments", "prod", "OutOfSync", "a1b2c3d")
    assert v["repo"].endswith("deploy.git") and v["path"] == "apps/api" and v["target"] == "main" and v["auto_sync"] is True
    assert v["errors"] == [{"type": "SyncError", "message": "boom"}] and len(v["history"]) == 2
    assert v["last_sync_at"] and v["op_phase"] == "Succeeded"
    assert app_view({"metadata": {"name": "bare"}})["sync"] == "Unknown"       # a half-filled application does not break the page


def test_helm_and_multi_source_applications():
    a = app("chart")
    a["spec"] = {"project": "default", "sources": [{"repoURL": "https://charts.test", "chart": "nginx", "targetRevision": "1.2.3"}], "destination": {"name": "prod-cluster"}}
    v = app_view(a)
    assert v["repo"] == "https://charts.test" and v["path"] == "nginx" and v["cluster"] == "prod-cluster"


def test_projects_are_sent_to_argo_and_the_token_is_a_bearer():
    s = Server(FLEET)
    run(client(s, projects=["payments", "data"]).apps())
    q = s.requests[0].url.params.get_list("projects")
    assert q == ["payments", "data"] and s.requests[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_deploys_are_syncs_and_failures_newest_first():
    c = client(Server([app("web"), app("billing", phase="Failed", history=[{"id": 3, "revision": "feedface1", "deployedAt": "2026-11-03T09:00:00Z"}])]))
    d = run(c.deploys())
    assert [x["finished_at"] for x in d] == sorted((x["finished_at"] for x in d), reverse=True)
    assert {x["conclusion"] for x in d} == {"success", "failure"}
    assert any(x["name"] == "web" and x["sha"] == "0000000" for x in d)


@pytest.mark.parametrize("status, text", [(401, "refused the token"), (403, "may not read"), (404, "check argocd.url"), (500, "HTTP 500")])
def test_failures_say_what_to_fix(status, text):
    s = Server(FLEET)
    s.status = status
    with pytest.raises(ArgoCDError, match=text):
        run(client(s).apps())
    assert run(client(s).healthy()) is False


def test_the_wrong_address_is_recognised():
    c = ArgoCD(ArgoCDCfg(url="https://argocd.test", token=TOKEN),
               client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>Argo CD UI</html>"))))
    with pytest.raises(ArgoCDError, match="wrong argocd.url"):
        run(c.apps())


def test_unreachable_and_untrusted_certificates():
    def refuse(req):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate")
    c = ArgoCD(ArgoCDCfg(url="https://argocd.test", token=TOKEN), client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    with pytest.raises(ArgoCDError, match="ca_file"):
        run(c.apps())


def test_a_missing_ca_file_is_a_clear_config_error():
    with pytest.raises(ConfigError, match="ca_file not found: /nope.crt"):
        ArgoCD(ArgoCDCfg(url="https://argocd.test", token=TOKEN, ca_file="/nope.crt"))


def test_url_validation_and_enabled():
    assert not ArgoCDCfg().enabled and ArgoCDCfg(url="https://a.test/").enabled and ArgoCDCfg(url="https://a.test/").url == "https://a.test"
    with pytest.raises(ValueError):
        ArgoCDCfg(url="argocd.test")


def test_no_time_series():
    with pytest.raises(PromQueryError):
        run(client(Server()).range("degraded", 0, 1, 1))


def make_cfg(tmp_path):
    f = tmp_path / "n.yaml"
    f.write_text("presets: [core, argocd]\nargocd: {url: 'https://argocd.test', token: x}\n")
    cfg = load_config(str(f), explicit=True)
    cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    return cfg


def login(c):
    assert c.post("/api/login", json={"username": "admin", "password": "pw"}, headers=H).status_code == 200


def test_the_preset_loads_and_its_rules_alert_per_application(tmp_path):
    s = Server(FLEET)
    with TestClient(create_app(make_cfg(tmp_path), prom=FakeProm(), argocd={"default": client(s)})) as c:
        login(c)
        me = c.get("/api/me").json()
        assert "argocd" in me["servers"][0]["datasources"] and me["servers"][0]["argocd"] is True and me["servers"][0]["deploys"] is True
        rules = {r["id"]: r for r in c.get("/api/rules").json() if r["id"].startswith("argocd-")}
        assert set(rules) == {"argocd-out-of-sync", "argocd-degraded", "argocd-sync-failed", "argocd-sync-error", "argocd-stuck-progressing"}
        assert all(r["datasource"] == "argocd" for r in rules.values())
        # the rule editor's Preview works against it
        out = c.post("/api/rules/test", json={"name": "x", "expr": "degraded", "crit": 0, "datasource": "argocd"}, headers=H).json()
        assert out["series"] == [{"series": "worker", "value": 1.0, "severity": "critical"}]


def test_firing_and_resolving_through_the_engine(tmp_path):
    s = Server([app("web"), app("worker", health="Degraded")])
    cfg = make_cfg(tmp_path)
    with TestClient(create_app(cfg, prom=FakeProm(), argocd={"default": client(s)})) as c:
        login(c)
        eng = c.app.state.engine
        store = c.app.state.store
        rule = store.get_rule("argocd-degraded")
        store.save_rule({**rule, "for_seconds": 0})
        now = time.time()
        run(eng.evaluate_rules(now))
        firing = [i for i in c.get("/api/incidents?status=firing").json() if i["rule_name"] == "Application degraded"]
        assert len(firing) == 1 and firing[0]["series"] == "worker"
        s.apps = [app("web"), app("worker")]                       # fixed
        c.app.state.engine.argos["default"]._cache = None
        run(eng.evaluate_rules(now + 60))
        assert not [i for i in c.get("/api/incidents?status=firing").json() if i["rule_name"] == "Application degraded"]


def test_the_argocd_page_endpoint(tmp_path):
    s = Server(FLEET)
    with TestClient(create_app(make_cfg(tmp_path), prom=FakeProm(), argocd={"default": client(s)})) as c:
        login(c)
        d = c.get("/api/argocd").json()
        assert d["summary"] == {"total": 6, "healthy": 4, "synced": 5, "out_of_sync": 1, "degraded": 1, "progressing": 1, "failed": 2}
        assert d["apps"][-1]["name"] == "web" and d["apps"][0]["name"] != "web"          # trouble first, healthy last
        assert set(d["projects"]) == {"default", "data", "payments"}
        assert [a["name"] for a in c.get("/api/argocd?project=data").json()["apps"]] == ["jobs"]
        deploys = c.get("/api/deploys").json()
        assert deploys["enabled"] is True and any(r.get("source") == "argocd" for r in deploys["runs"])


def test_the_page_says_so_when_it_is_not_configured(tmp_path):
    cfg = load_config(None)
    cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    with TestClient(create_app(cfg, prom=FakeProm())) as c:
        login(c)
        assert c.get("/api/argocd").status_code == 404
        assert c.get("/api/me").json()["servers"][0]["argocd"] is False


def test_a_broken_token_is_reported_not_crashed(tmp_path):
    s = Server(FLEET)
    s.status = 401
    with TestClient(create_app(make_cfg(tmp_path), prom=FakeProm(), argocd={"default": client(s)})) as c:
        login(c)
        r = c.get("/api/argocd")
        assert r.status_code == 502 and "refused the token" in r.json()["detail"]


def test_syncs_appear_as_markers_on_the_incident_page(tmp_path):
    now = time.time()
    hist = [{"id": 1, "revision": "cafe1234abcd", "deployedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 300))}]
    s = Server([app("web", history=hist)])
    with TestClient(create_app(make_cfg(tmp_path), prom=FakeProm(), argocd={"default": client(s)})) as c:
        login(c)
        iid = c.app.state.store.create_incident(source_id="x", series_key="a", rule_name="Slow", series="", severity="critical", started_at=now - 60)
        d = c.get(f"/api/incidents/{iid}").json()
        assert [x["sha"] for x in d["deploys"]] == ["cafe123"] and d["deploys"][0]["source"] == "argocd"
