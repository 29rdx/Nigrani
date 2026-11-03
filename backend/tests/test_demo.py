import asyncio
import time

from fastapi.testclient import TestClient

from nigrani.api import create_app
from nigrani.config import load_config
from nigrani.demo import DemoProm

H = {"X-Requested-With": "nigrani"}


def demo_cfg(tmp_path):
    cfg = load_config(None, demo=True)
    cfg.data_dir = str(tmp_path)
    return cfg


def run(coro):
    return asyncio.run(coro)


def test_every_preset_query_has_demo_data(tmp_path):
    """The demo must not show empty tiles: each query the presets send gets at least one numeric series."""
    cfg = demo_cfg(tmp_path)
    prom = DemoProm()
    queries = [t.query for t in cfg.tiles] + [r.expr for r in cfg.rules if r.datasource == "prometheus"]
    for p in cfg.pages:
        for panel in getattr(p, "panels", []):
            queries += [q.expr for q in panel.queries]
    assert len(queries) >= 12
    missing = []
    for q in queries:
        res = run(prom.instant(q))
        if not res or all(r["value"] is None for r in res):
            missing.append(q)
    assert missing == []


def test_a_bad_spell_raises_errors_and_latency_then_ends():
    t0 = 1_000_000.0
    prom = DemoProm(started=t0)
    err = 'sum(rate(django_http_responses_total_by_status_total{status=~"5.."}[5m])) / sum(rate(django_http_responses_total_by_status_total[5m])) * 100'
    p95 = "histogram_quantile(0.95, sum by (le) (rate(django_http_requests_latency_seconds_by_view_method_bucket[5m])))"
    val = lambda q, t: run(prom.instant(q, at=t))[0]["value"]            # noqa: E731
    assert val(err, t0 + 60) < 1 and val(p95, t0 + 60) < 0.5              # calm
    assert val(err, t0 + 400) > 5 and val(p95, t0 + 400) > 3              # inside the spell: over the critical thresholds
    assert val(err, t0 + 1200) < 1                                         # over
    assert val(err, t0 + 5400 + 400) > 5                                   # and it comes back every 90 minutes


def test_range_queries_return_a_point_per_step():
    prom = DemoProm()
    now = time.time()
    res = run(prom.range("node_load1", now - 600, now, 60))
    assert len(res) == 1 and len(res[0]["points"]) == 11 and all(v is not None for _, v in res[0]["points"])


def test_ratio_and_percent_forms_of_memory_agree():
    prom = DemoProm()
    pct = run(prom.instant("(1 - sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)) * 100"))[0]["value"]
    ratio = run(prom.instant("1 - sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)"))[0]["value"]
    assert 0 < ratio < 1 and abs(pct - ratio * 100) < 2


def test_unknown_queries_return_nothing_instead_of_failing():
    assert run(DemoProm().instant("some_metric_we_never_heard_of")) == []


def test_demo_app_needs_no_login_but_cannot_be_changed(tmp_path):
    with TestClient(create_app(demo_cfg(tmp_path))) as c:
        me = c.get("/api/me").json()
        assert me["demo"] is True and me["ai"] is True
        assert c.get("/api/overview").status_code == 200
        r = c.post("/api/silences", json={"minutes": 5}, headers=H)
        assert r.status_code == 403 and "read-only demo" in r.json()["detail"]
        assert c.post("/api/rules", json={"name": "x", "expr": "up", "warn": 1}, headers=H).status_code == 403
        assert c.delete("/api/rules/django-5xx", headers=H).status_code == 403
        assert c.post("/api/channels", json={"name": "x", "type": "webhook", "settings": {"url": "http://169.254.169.254"}},
                      headers=H).status_code == 403
        # looking things up and previewing still work
        assert c.post("/api/rules/test", json={"name": "x", "expr": "node_load1", "warn": 1}, headers=H).status_code == 200


def test_demo_starts_with_history_and_does_not_duplicate_it(tmp_path):
    for _ in range(2):                                   # a restart on the same data directory
        with TestClient(create_app(demo_cfg(tmp_path))) as c:
            inc = c.get("/api/incidents?days=10&status=resolved").json()
            assert [i["rule_name"] for i in inc].count("Elevated 5xx rate") == 2 and len(inc) == 3
            st = c.get("/api/public/status").json()
            assert st["title"] == "Acme status" and len(st["checks"]) == 3
            assert all(len(ch["days"]) == 90 and ch["uptime_period"] > 95 for ch in st["checks"])
            assert any(b["pct"] == 0 for ch in st["checks"] for b in ch["days"])         # the sample outage days
            assert sorted((a["kind"], a["state"]) for a in st["announcements"]) == [("incident", "resolved"), ("maintenance", "scheduled")]


def test_demo_ai_is_a_labelled_canned_example(tmp_path):
    with TestClient(create_app(demo_cfg(tmp_path))) as c:
        iid = c.get("/api/incidents?days=10").json()[0]["id"]
        out = c.post(f"/api/incidents/{iid}/explain", headers=H).json()
        assert "What happened" in out["text"] and "demo" in out["model"]
        draft = c.post("/api/ai/rule", json={"description": "memory over 80 percent"}, headers=H).json()
        assert draft["rule"]["unit"] == "ratio" and draft["preview"]["series"][0]["value"] < 1


def test_demo_defaults_yield_to_the_config_file(tmp_path):
    f = tmp_path / "n.yaml"
    f.write_text("app: {name: Mine}\nstatus_page: {enabled: false}\n")
    cfg = load_config(str(f), demo=True)
    assert cfg.app.name == "Mine" and cfg.status_page.enabled is False and cfg.demo is True


def test_demo_does_not_start_with_a_failed_check(tmp_path):
    """The demo's checks target Nigrani itself, so they must not run before it is up (which read as an outage)."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.listen()                                           # something is listening, as Nigrani would be
    cfg = demo_cfg(tmp_path)
    cfg.checks = [c for c in cfg.checks if c.id == "database"]
    cfg.checks[0].target = f"127.0.0.1:{port}"
    for v in cfg.server_views():
        v.checks[:] = cfg.checks
    started = time.time()
    with TestClient(create_app(cfg)) as c:
        store = c.app.state.store

        def latest():
            last = store.last_check_result("database")
            return last if last and last["ts"] >= started else None      # earlier rows are the seeded history

        time.sleep(0.5)
        assert latest() is None                                          # it waits a moment first
        end = time.time() + 8
        while latest() is None and time.time() < end:
            time.sleep(0.1)
        assert latest()["ok"] == 1
    s.close()
