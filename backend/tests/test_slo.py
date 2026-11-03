import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from conftest import FakeProm
from nigrani.api import create_app
from nigrani.config import ConfigError, SloCfg, load_config
from nigrani.slo import burn, tiers_for

H = {"X-Requested-With": "nigrani"}
NOW = 1_800_000_000.0
DAY = 86400
WINDOWS = [300, 1800, 3600, 7200, 21600, 86400, 259200, 30 * DAY]


def run(coro):
    return asyncio.run(coro)


def slo_cfg(**over):
    base = dict(id="api", name="API availability", target=99.9, total="sum(rate(req[{{window}}]))", errors="sum(rate(err[{{window}}]))")
    return SloCfg(**{**base, **over})


def feed(prom, ratios, total=100.0, errors_expr="err", total_expr="req"):
    """ratios: {window seconds: error ratio}. Fills the answers Prometheus would give for each expanded query."""
    for w, r in ratios.items():
        prom.values[f"sum(rate({total_expr}[{w}s]))"] = [({}, total)]
        prom.values[f"sum(rate({errors_expr}[{w}s]))"] = [({}, total * r)]


def uniform(r):
    return {w: r for w in WINDOWS}


def make_app(tmp_path, yaml_slos, prom=None, extra=""):
    f = tmp_path / "n.yaml"
    f.write_text(f"slos:\n{yaml_slos}\n{extra}")
    cfg = load_config(str(f), explicit=True)
    cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    return create_app(cfg, prom=prom or FakeProm())


API = """  - id: api
    name: API availability
    target: 99.9
    total: sum(rate(req[{{window}}]))
    errors: sum(rate(err[{{window}}]))
"""


def login(c):
    assert c.post("/api/login", json={"username": "admin", "password": "pw"}, headers=H).status_code == 200


def firing(c):
    return sorted(i["rule_name"] for i in c.get("/api/incidents?status=firing").json() if i["source_id"].startswith("slo:"))


# ---- configuration ----
def test_the_two_ways_to_define_an_sli_and_their_mistakes():
    assert slo_cfg().target == 99.9
    assert slo_cfg(errors="", good="sum(rate(ok[{{window}}]))").good
    assert SloCfg(id="up", name="Uptime", target=99.5, check="web").check == "web"
    for bad in (dict(errors="", good=""), dict(good="sum(rate(ok[{{window}}]))"), dict(total=""),
                dict(errors="sum(rate(err[5m]))"), dict(check="web")):
        with pytest.raises(ValueError):
            slo_cfg(**bad)
    with pytest.raises(ValueError):
        SloCfg(id="u", name="U", target=99, check="web", total="x[{{window}}]")
    for t in (0, 100, 150):
        with pytest.raises(ValueError):
            slo_cfg(target=t)
    with pytest.raises(ValueError):
        slo_cfg(id="Bad Id")
    with pytest.raises(ValueError):
        slo_cfg(window_days=0)


def test_duplicate_ids_and_unknown_servers_are_rejected(tmp_path):
    f = tmp_path / "n.yaml"
    f.write_text("slos:\n" + API + API)
    with pytest.raises(ConfigError, match="duplicate id"):
        load_config(str(f), explicit=True)
    f.write_text("slos:\n" + API + "    servers: [nope]\n")
    with pytest.raises(ConfigError, match="unknown server"):
        load_config(str(f), explicit=True)


# ---- the maths ----
def test_burn_factors_follow_the_sre_workbook_for_30_days_and_scale_with_the_window():
    t = {x["name"]: x["factor"] for x in tiers_for(30 * DAY)}
    assert t == {"fast": 14.4, "slow": 6.0, "daily": 3.0, "trend": 1.0}
    assert [x["name"] for x in tiers_for(2 * DAY)] == ["fast", "slow", "daily"]          # 3 day tier does not fit in 2 days
    assert {x["name"]: x["factor"] for x in tiers_for(7 * DAY)}["fast"] == 3.36
    assert burn(0.001, 99.9) == pytest.approx(1.0) and burn(None, 99.9) is None and burn(0.0144, 99.9) == pytest.approx(14.4)


def evaluate(slo, prom, now=NOW):
    from nigrani.slo import SloEngine

    class Rt:
        pass

    rt = Rt()
    rt.prom = prom
    rt.view = type("V", (), {"id": "default", "name": "prod"})()
    eng = SloEngine(load_config(None), None, None, {"default": rt})
    return run(eng.evaluate(slo, rt, now)), eng, rt


def test_a_healthy_service_has_budget_left_and_nothing_fires():
    p = FakeProm()
    feed(p, uniform(0.0005))
    st, _, _ = evaluate(slo_cfg(), p)
    assert st["status"] == "ok" and round(st["sli"], 3) == 99.95
    assert st["budget_remaining"] == pytest.approx(0.5) and not any(t["firing"] for t in st["tiers"])
    assert st["budget_minutes"] == pytest.approx(43.2) and st["budget_used_minutes"] == pytest.approx(21.6)


def test_a_fast_burn_needs_both_windows_to_be_over_the_factor():
    p = FakeProm()
    ratios = uniform(0.0005)
    ratios.update({3600: 0.02, 300: 0.03})                   # 20x and 30x: over 14.4 in both
    feed(p, ratios)
    st, _, _ = evaluate(slo_cfg(), p)
    fast = next(t for t in st["tiers"] if t["name"] == "fast")
    assert fast["firing"] and fast["burn_long"] == pytest.approx(20) and st["status"] == "critical"
    assert not next(t for t in st["tiers"] if t["name"] == "slow")["firing"]      # 6h is only 0.0005

    ratios[300] = 0.0005                                      # it has stopped: the short window is clean again
    feed(p, ratios)
    slo = slo_cfg()
    st2, eng, rt = evaluate(slo, p, NOW + 600)               # (new engine, so no cached numbers)
    assert not next(t for t in st2["tiers"] if t["name"] == "fast")["firing"] and st2["status"] == "ok"


def test_a_slow_gradual_burn_is_a_warning_not_a_page():
    p = FakeProm()
    r = uniform(0.0005)
    r.update({86400: 0.004, 7200: 0.004})                    # 4x over a day and 2 hours: the daily tier (3x)
    feed(p, r)
    st, _, _ = evaluate(slo_cfg(), p)
    assert [t["name"] for t in st["tiers"] if t["firing"]] == ["daily"] and st["status"] == "warning"


def test_exhausted_budget_is_critical_even_when_the_burn_has_stopped():
    p = FakeProm()
    r = uniform(0.0)
    r[30 * DAY] = 0.002                                      # 2x the budget over the whole window
    feed(p, r)
    st, _, _ = evaluate(slo_cfg(), p)
    assert st["budget_remaining"] == pytest.approx(-1.0) and st["status"] == "critical"
    assert not any(t["firing"] for t in st["tiers"])


def test_no_traffic_means_no_data_not_100_percent():
    p = FakeProm()
    feed(p, uniform(0.0), total=0.0)
    st, _, _ = evaluate(slo_cfg(), p)
    assert st["status"] == "nodata" and st["sli"] is None and st["budget_remaining"] is None


def test_no_data_is_not_cached_but_real_numbers_are():
    p = FakeProm()
    feed(p, uniform(0.0), total=0.0)                             # nothing has happened yet
    st, eng, rt = evaluate(slo_cfg(), p)
    assert st["status"] == "nodata"
    feed(p, uniform(0.0005))                                     # traffic starts: the very next evaluation must see it
    assert run(eng.evaluate(slo_cfg(), rt, NOW + 5))["status"] == "ok"
    feed(p, uniform(0.5))                                        # changes within the cache lifetime are not seen (by design)
    assert run(eng.evaluate(slo_cfg(), rt, NOW + 10))["status"] == "ok"


def test_good_over_total_form_and_clamping():
    p = FakeProm()
    for w in WINDOWS:
        p.values[f"sum(rate(req[{w}s]))"] = [({}, 200.0)]
        p.values[f"sum(rate(ok[{w}s]))"] = [({}, 199.0)]              # 0.5% bad
    st, _, _ = evaluate(slo_cfg(errors="", good="sum(rate(ok[{{window}}]))"), p)
    assert round(100 - st["sli"], 2) == 0.5 and st["tiers"][0]["burn_long"] == pytest.approx(5.0)
    for w in WINDOWS:
        p.values[f"sum(rate(ok[{w}s]))"] = [({}, 250.0)]              # more "good" than total (a bad query): ratio stays 0
    st, _, _ = evaluate(slo_cfg(errors="", good="sum(rate(ok[{{window}}]))"), p)
    assert st["sli"] == 100.0


def test_several_series_are_summed():
    p = FakeProm()
    for w in WINDOWS:
        p.values[f"sum(rate(req[{w}s]))"] = [({"i": "a"}, 60.0), ({"i": "b"}, 40.0)]
        p.values[f"sum(rate(err[{w}s]))"] = [({"i": "a"}, 0.05), ({"i": "b"}, 0.05)]
    st, _, _ = evaluate(slo_cfg(), p)
    assert round(100 - st["sli"], 3) == 0.1


# ---- through the alert engine ----
def test_burn_alerts_open_and_resolve_and_an_outage_does_not_resolve_them(tmp_path):
    prom = FakeProm()
    ratios = uniform(0.0005)
    ratios.update({3600: 0.02, 300: 0.03})
    feed(prom, ratios)
    with TestClient(make_app(tmp_path, API, prom)) as c:
        login(c)
        rt = c.app.state.runtimes["default"]
        eng = c.app.state.slo                                 # the loop evaluates on its own schedule: drive it by hand here
        eng._cache.clear()
        run(eng.refresh(rt, NOW))
        assert firing(c) == ["SLO burn rate: API availability (fast burn)"]
        inc = next(i for i in c.get("/api/incidents?status=firing").json() if i["source_id"].startswith("slo:"))
        assert inc["severity"] == "critical" and inc["threshold"] == 14.4 and "too fast" in inc["summary"]

        prom.up = False                                       # Prometheus goes away: the alert must stay
        eng._cache.clear()
        st = run(eng.refresh(rt, NOW + 120))
        assert st[0]["status"] == "error" and firing(c) == ["SLO burn rate: API availability (fast burn)"]

        prom.up = True
        ratios[300] = 0.0005                                  # the burn stopped
        feed(prom, ratios)
        eng._cache.clear()
        run(eng.refresh(rt, NOW + 400))
        assert firing(c) == []
        assert any(i["status"] == "resolved" for i in c.get("/api/incidents").json() if i["source_id"].startswith("slo:"))


def test_the_api_and_the_menu_flag(tmp_path):
    prom = FakeProm()
    feed(prom, uniform(0.0005))
    with TestClient(make_app(tmp_path, API, prom)) as c:
        login(c)
        assert c.get("/api/me").json()["servers"][0]["slo"] is True
        d = c.get("/api/slos").json()
        assert d["server"] == "default" and len(d["slos"]) == 1
        s = d["slos"][0]
        assert s["name"] == "API availability" and s["target"] == 99.9 and s["status"] in ("ok", "nodata")
        assert [t["name"] for t in s["tiers"]] == ["fast", "slow", "daily", "trend"]


def test_no_slos_means_no_menu_item_and_an_empty_list(tmp_path):
    cfg = load_config(None)
    cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    with TestClient(create_app(cfg, prom=FakeProm())) as c:
        login(c)
        assert c.get("/api/me").json()["servers"][0]["slo"] is False
        assert c.get("/api/slos").json()["slos"] == []


def test_an_slo_can_be_limited_to_some_servers(tmp_path):
    yaml = API + "    servers: [prod]\n"
    extra = "servers:\n  - {id: prod}\n  - {id: staging}\n"
    with TestClient(make_app(tmp_path, yaml, extra=extra, prom={"prod": FakeProm(), "staging": FakeProm()})) as c:
        login(c)
        assert len(c.get("/api/slos?server=prod").json()["slos"]) == 1
        assert c.get("/api/slos?server=staging").json()["slos"] == []
        me = {s["id"]: s["slo"] for s in c.get("/api/me").json()["servers"]}
        assert me == {"prod": True, "staging": False}


# ---- an uptime check as the SLI ----
def test_an_uptime_check_can_be_the_sli(tmp_path):
    yaml = "  - {id: web, name: Website uptime, target: 99, check: web}\n"
    extra = "checks:\n  - {id: web, name: Website, type: http, target: 'http://127.0.0.1:9/x', interval: 3600}\n"
    with TestClient(make_app(tmp_path, yaml, extra=extra)) as c:
        login(c)
        store = c.app.state.store
        now = time.time()
        for i in range(100):                                  # 5% of the last 30 minutes failed
            store.add_check_result("web", now - 1700 + i * 17, i % 20 != 0, 5.0, "")
        eng = c.app.state.slo
        eng._cache.clear()
        st = run(eng.refresh(c.app.state.runtimes["default"], now, sync=False))[0]
        assert st["source"] == "uptime check 'web'"
        fast = next(t for t in st["tiers"] if t["name"] == "fast")
        assert fast["burn_long"] > 4 and fast["burn_short"] > 4         # about 5% bad against a 1% budget (plus the live check)
        assert st["status"] in ("ok", "warning", "critical") and st["sli"] < 100
