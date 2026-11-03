import pytest
from fastapi.testclient import TestClient

from conftest import FakeProm
from nigrani.api import create_app
from nigrani.config import load_config, preset_catalog, preset_items

H = {"X-Requested-With": "nigrani"}
ML = {"gpu": ("DCGM_FI_DEV_GPU_UTIL", {"gpu-memory-full", "gpu-hot", "gpu-xid-error", "gpu-idle"}),
      "vllm": ("vllm:num_requests_running", {"vllm-queue-backlog", "vllm-kv-cache-full", "vllm-slow-first-token"}),
      "triton": ("nv_inference_request_success", {"triton-failures", "triton-queue-slow"})}


def balanced(expr: str) -> bool:
    depth = 0
    for ch in expr:
        depth += ch == "(" or ch == "["
        depth -= ch == ")" or ch == "]"
        if depth < 0:
            return False
    return depth == 0


@pytest.mark.parametrize("name", ML)
def test_each_preset_describes_itself_and_ships_its_rules(name):
    detect, rule_ids = ML[name]
    entry = next(c for c in preset_catalog() if c["name"] == name)
    assert entry["detect"] == [detect] and entry["title"] and entry["about"]
    tiles, pages, rules = preset_items(name)
    assert {r.id for r in rules} == rule_ids
    assert pages and all(p.requires == detect for p in pages)                # the page lights up on the same metric discovery looks for
    for expr in [t.query for t in tiles] + [r.expr for r in rules] + [q.expr for p in pages for pn in p.panels for q in pn.queries]:
        assert expr.strip() and balanced(expr), expr


def test_fractions_use_the_ratio_unit_so_thresholds_stay_fractions():
    _, pages, rules = preset_items("vllm")
    by = {r.id: r for r in rules}
    assert by["vllm-kv-cache-full"].unit == "ratio" and by["vllm-kv-cache-full"].warn == 0.9
    assert by["vllm-kv-cache-full"].crit == 0.97
    assert {r.id: r.unit for r in preset_items("gpu")[2]}["gpu-memory-full"] == "ratio"
    assert {r.id: r.unit for r in preset_items("triton")[2]}["triton-failures"] == "ratio"


def test_alerts_name_the_gpu_or_the_model_not_just_the_host():
    for r in preset_items("gpu")[2]:
        assert 'label_join(' in r.expr and '"name"' in r.expr, r.id           # series show as "<host> GPU <n>"
    for r in preset_items("vllm")[2]:
        assert "model_name" in r.expr, r.id
    for r in preset_items("triton")[2]:
        assert "by (model)" in r.expr, r.id


def test_the_idle_gpu_rule_is_off_until_someone_turns_it_on(tmp_path):
    cfg = load_config(None)
    cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    prom = FakeProm()
    prom.metrics = {"DCGM_FI_DEV_GPU_UTIL"}
    with TestClient(create_app(cfg, prom=prom)) as c:
        assert c.post("/api/login", json={"username": "admin", "password": "pw"}, headers=H).status_code == 200
        assert {p["name"]: p["status"] for p in c.get("/api/discovery").json()["presets"]}["gpu"] == "found"
        assert c.post("/api/discovery/gpu/enable", headers=H).status_code == 200
        rules = {r["id"]: r for r in c.get("/api/rules").json()}
        assert rules["gpu-idle"]["enabled"] is False and rules["gpu-hot"]["enabled"] is True
        assert "gpus" in [p["id"] for p in c.get("/api/pages").json()]
