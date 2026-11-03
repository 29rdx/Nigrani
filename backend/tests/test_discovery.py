import pytest
from fastapi.testclient import TestClient

from conftest import FakeProm
from nigrani.api import create_app
from nigrani.config import ConfigError, apply_presets, load_config, preset_catalog, preset_items, read_preset
from nigrani.passwords import hash_password

H = {"X-Requested-With": "nigrani"}


def make_app(tmp_path, prom=None, presets=None):
    cfg = load_config(None)
    cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    if presets is not None:
        f = tmp_path / "n.yaml"
        f.write_text(f"presets: {presets}\n")
        cfg = load_config(str(f), explicit=True)
        cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    return create_app(cfg, prom=prom or FakeProm())


def login(c, user="admin", pw="pw"):
    assert c.post("/api/login", json={"username": user, "password": pw}, headers=H).status_code == 200


def prom_with(*metrics):
    p = FakeProm()
    p.metrics = set(metrics)
    return p


def status_of(c):
    return {p["name"]: p["status"] for p in c.get("/api/discovery").json()["presets"]}


def test_every_detectable_preset_is_described_and_loads():
    catalog = preset_catalog()
    assert {c["name"] for c in catalog} >= {"core", "django", "redis", "postgres", "rds", "mqtt", "celery"}
    for c in catalog:
        assert c["title"] and c["about"] and c["detect"], c["name"]
        tiles, pages, rules = preset_items(c["name"])
        assert (len(tiles), len(pages), len(rules)) == (c["tiles"], c["pages"], c["rules"])
        # the metric that proves the exporter is there is the one the preset's own pages ask for
        for p in pages:
            if p.requires:
                assert p.requires in c["detect"], (c["name"], p.requires)


def test_unknown_or_hostile_preset_names_are_rejected():
    for bad in ("nope", "../core", "core/../x"):
        with pytest.raises(ConfigError):
            read_preset(bad)


def test_discovery_says_what_prometheus_has(tmp_path):
    with TestClient(make_app(tmp_path, prom_with("node_cpu_seconds_total", "redis_up", "pg_up"))) as c:
        login(c)
        st = status_of(c)
        assert st["core"] == "enabled"                       # the default preset
        assert st["redis"] == "found" and st["postgres"] == "found"
        assert st["django"] == "missing" and st["celery"] == "missing"
        d = c.get("/api/discovery").json()
        assert [p["status"] for p in d["presets"]][:2] == ["found", "found"]        # suggestions first
        assert d["error"] is None
        redis = next(p for p in d["presets"] if p["name"] == "redis")
        assert redis["rules"] >= 1 and redis["pages"] == 1 and redis["origin"] is None


def test_discovery_survives_an_unreachable_prometheus(tmp_path):
    prom = prom_with("redis_up")
    prom.up = False
    with TestClient(make_app(tmp_path, prom)) as c:
        login(c)
        d = c.get("/api/discovery").json()
        assert "not reachable" in d["error"] and all(p["status"] != "found" for p in d["presets"])


def test_turning_a_preset_on_adds_its_page_tiles_and_alert_rules_immediately(tmp_path):
    with TestClient(make_app(tmp_path, prom_with("redis_up"))) as c:
        login(c)
        assert "redis" not in [p["id"] for p in c.get("/api/pages").json()]
        assert not any(r["id"].startswith("redis") for r in c.get("/api/rules").json())
        assert c.post("/api/discovery/redis/enable", headers=H).status_code == 200
        assert "redis" in [p["id"] for p in c.get("/api/pages").json()]
        rules = [r for r in c.get("/api/rules").json() if r["id"].startswith("redis")]
        assert rules and all(r["source"] == "preset" and r["enabled"] for r in rules)
        assert status_of(c)["redis"] == "enabled"
        assert next(p for p in c.get("/api/discovery").json()["presets"] if p["name"] == "redis")["origin"] == "ui"


def test_it_stays_on_after_a_restart_and_can_be_turned_off(tmp_path):
    with TestClient(make_app(tmp_path)) as c:
        login(c)
        c.post("/api/discovery/redis/enable", headers=H)
    with TestClient(make_app(tmp_path)) as c:                # a new process on the same data directory
        login(c)
        assert "redis" in [p["id"] for p in c.get("/api/pages").json()]
        assert any(r["id"].startswith("redis") for r in c.get("/api/rules").json())
        assert c.delete("/api/discovery/redis", headers=H).status_code == 200
        assert "redis" not in [p["id"] for p in c.get("/api/pages").json()]
        assert not any(r["id"].startswith("redis") for r in c.get("/api/rules").json())
    with TestClient(make_app(tmp_path)) as c:
        login(c)
        assert "redis" not in [p["id"] for p in c.get("/api/pages").json()]


def test_presets_from_the_config_file_are_not_touched(tmp_path):
    with TestClient(make_app(tmp_path, presets="[core, redis]")) as c:
        login(c)
        assert c.post("/api/discovery/redis/enable", headers=H).status_code == 409
        assert c.delete("/api/discovery/redis", headers=H).status_code == 409
        assert next(p for p in c.get("/api/discovery").json()["presets"] if p["name"] == "redis")["origin"] == "config"
        assert c.post("/api/discovery/nope/enable", headers=H).status_code == 404
        assert c.delete("/api/discovery/nope", headers=H).status_code == 404


def test_a_rule_you_edited_keeps_your_version_when_a_preset_goes_off_and_on(tmp_path):
    with TestClient(make_app(tmp_path)) as c:
        login(c)
        c.post("/api/discovery/redis/enable", headers=H)
        rule = next(r for r in c.get("/api/rules").json() if r["id"].startswith("redis"))
        c.put(f"/api/rules/{rule['id']}", json={**rule, "warn": 12345.0}, headers=H)
        c.delete("/api/discovery/redis", headers=H)
        c.post("/api/discovery/redis/enable", headers=H)          # back on: the shipped version returns
        again = next(r for r in c.get("/api/rules").json() if r["id"] == rule["id"])
        assert again["source"] == "preset"


def test_viewers_can_look_but_not_change(tmp_path):
    with TestClient(make_app(tmp_path)) as c:
        login(c)
        c.app.state.store.create_user(username="viewer1", role="viewer", password_hash=hash_password("a-long-passphrase-1"))
        c.post("/api/logout", headers=H)
        login(c, "viewer1", "a-long-passphrase-1")
        assert c.get("/api/discovery").status_code == 200
        assert c.post("/api/discovery/redis/enable", headers=H).status_code == 403
        assert c.delete("/api/discovery/core", headers=H).status_code == 403


def test_user_settings_win_over_a_preset_turned_on_later():
    cfg = load_config(None)
    from nigrani.config import TileCfg
    mine = TileCfg(id="cpu", title="My CPU", query="up")
    base = (list(cfg.tiles) + [mine], list(cfg.pages), list(cfg.rules))
    cfg.tiles = [t for t in base[0]]
    apply_presets(cfg, base, ["django", "core"])
    assert next(t for t in cfg.tiles if t.id == "cpu").title == "My CPU"
    assert any(t.id == "django-rps" for t in cfg.tiles)


def test_demo_mode_shows_suggestions_but_is_read_only(tmp_path):
    cfg = load_config(None, demo=True)
    cfg.data_dir = str(tmp_path)
    with TestClient(create_app(cfg)) as c:
        st = status_of(c)
        assert st["core"] == "enabled" and st["django"] == "enabled" and st["redis"] == "found" and st["postgres"] == "found"
        r = c.post("/api/discovery/redis/enable", headers=H)
        assert r.status_code == 403 and "read-only demo" in r.json()["detail"]
