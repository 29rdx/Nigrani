import asyncio
import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import FakeProm
from nigrani.api import create_app
from nigrani.config import NewRelicCfg, load_config
from nigrani.newrelic import (
    NERDGRAPH_EU,
    NERDGRAPH_US,
    NewRelic,
    NewRelicError,
    extract_facet_keys,
    labels_of_row,
)
from nigrani.prom import PromQueryError, series_key

NOW = time.time()


class MockNewRelicServer:
    """Mock NerdGraph GraphQL API server."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.raw_response: Any = None
        self.results = [
            {"facet": "web-1", "average.cpuPercent": 91.5},
            {"facet": "web-2", "average.cpuPercent": 42.0},
            {"facet": "web-3", "average.cpuPercent": 15.5},
        ]
        self.timeseries_results = [
            {"beginTimeSeconds": int(NOW - 120), "endTimeSeconds": int(NOW - 60), "facet": "web-1", "average.cpuPercent": 85.0},
            {"beginTimeSeconds": int(NOW - 60), "endTimeSeconds": int(NOW), "facet": "web-1", "average.cpuPercent": 91.5},
            {"beginTimeSeconds": int(NOW - 120), "endTimeSeconds": int(NOW - 60), "facet": "web-2", "average.cpuPercent": 38.0},
            {"beginTimeSeconds": int(NOW - 60), "endTimeSeconds": int(NOW), "facet": "web-2", "average.cpuPercent": 42.0},
        ]

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self.status != 200:
            return httpx.Response(self.status, json={"errors": [{"message": f"HTTP {self.status}"}]})
        if self.raw_response is not None:
            if isinstance(self.raw_response, str):
                return httpx.Response(200, text=self.raw_response)
            return httpx.Response(200, json=self.raw_response)

        if req.headers.get("API-Key") != "valid-api-key":
            return httpx.Response(401, json={"errors": [{"message": "Invalid API key"}]})

        body = req.read().decode("utf-8")
        import json
        payload = json.loads(body)
        variables = payload.get("variables", {})
        account_id = variables.get("accountId")

        if account_id != 12345:
            return httpx.Response(200, json={"data": {"actor": {"account": None}}})

        nrql = variables.get("nrql", "")
        if "syntax_error" in nrql:
            return httpx.Response(200, json={"errors": [{"message": "Call to nrql query failed: Syntax error at line 1"}]})

        if "TIMESERIES" in nrql:
            results = self.timeseries_results
        else:
            results = self.results

        return httpx.Response(200, json={
            "data": {
                "actor": {
                    "account": {
                        "id": account_id,
                        "name": "Production Account",
                        "nrql": {
                            "results": results
                        }
                    }
                }
            }
        })


def make(server: MockNewRelicServer | None = None, **kwargs):
    server = server or MockNewRelicServer()
    cfg = NewRelicCfg(account_id=12345, api_key="valid-api-key", **kwargs)
    client = NewRelic(cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(server.handler)))
    return client, server


def run(coro):
    return asyncio.run(coro)


def test_extract_facet_keys():
    assert extract_facet_keys("SELECT average(cpuPercent) FROM SystemSample FACET hostname") == ["hostname"]
    assert extract_facet_keys("SELECT average(cpuPercent) FROM SystemSample FACET hostname, app") == ["hostname", "app"]
    assert extract_facet_keys("SELECT average(cpuPercent) FROM SystemSample FACET hostname SINCE 1 hour ago TIMESERIES") == ["hostname"]
    assert extract_facet_keys("SELECT average(cpuPercent) FROM SystemSample") == []


def test_labels_of_row():
    assert labels_of_row({"facet": "web-1", "average.cpuPercent": 91.5}, ["hostname"]) == ({"hostname": "web-1"}, 91.5)
    assert labels_of_row({"facet": ["web-1", "prod"], "average.cpuPercent": 91.5}, ["hostname", "env"]) == ({"hostname": "web-1", "env": "prod"}, 91.5)
    assert labels_of_row({"facet": "web-1", "average.cpuPercent": 91.5}) == ({"facet": "web-1"}, 91.5)
    assert labels_of_row({"average.cpuPercent": 50.0}) == ({"metric": "value"}, 50.0)
    assert labels_of_row({"host": "web-1", "average.cpuPercent": 50.0}) == ({"host": "web-1"}, 50.0)


def test_instant_executes_nrql_and_extracts_facets():
    c, s = make()
    rows = run(c.instant("SELECT average(cpuPercent) FROM SystemSample FACET hostname"))
    assert rows == [
        {"labels": {"hostname": "web-1"}, "value": 91.5},
        {"labels": {"hostname": "web-2"}, "value": 42.0},
        {"labels": {"hostname": "web-3"}, "value": 15.5},
    ]
    req = s.requests[-1]
    assert req.headers["API-Key"] == "valid-api-key"
    assert req.url.host == "api.newrelic.com"


def test_range_adds_timeseries_clause_and_converts_points():
    c, s = make()
    rows = run(c.range("SELECT average(cpuPercent) FROM SystemSample FACET hostname", NOW - 3600, NOW, step=60))
    assert len(rows) == 2
    web1 = next(r for r in rows if r["labels"] == {"hostname": "web-1"})
    assert [p[1] for p in web1["points"]] == [85.0, 91.5]
    assert abs(web1["points"][-1][0] - NOW) < 5


def test_region_and_url_selection():
    c_us, _ = make(region="us")
    assert c_us.api_url == NERDGRAPH_US

    c_eu, _ = make(region="eu")
    assert c_eu.api_url == NERDGRAPH_EU

    c_custom, _ = make(url="http://custom-proxy.internal/graphql")
    assert c_custom.api_url == "http://custom-proxy.internal/graphql"


@pytest.mark.parametrize("status,word", [
    (401, "refused the API key"),
    (403, "refused the API key"),
    (429, "rate limiting"),
    (502, "HTTP 502"),
])
def test_failures_are_infrastructure_errors(status, word):
    c, s = make()
    s.status = status
    with pytest.raises(NewRelicError, match=word):
        run(c.instant("SELECT average(cpuPercent) FROM SystemSample FACET hostname"))
    assert word in c.last_error


def test_graphql_errors_and_inaccessible_account():
    c, s = make()
    with pytest.raises(PromQueryError, match="Syntax error"):
        run(c.instant("SELECT average(cpuPercent) FROM SystemSample syntax_error"))

    bad_acc, s_bad = make()
    bad_acc.cfg.account_id = 99999
    with pytest.raises(NewRelicError, match="not found or inaccessible"):
        run(bad_acc.instant("SELECT average(cpuPercent) FROM SystemSample FACET hostname"))


def test_not_json_response():
    c, s = make()
    s.raw_response = "<html>Cloudflare Error</html>"
    with pytest.raises(NewRelicError, match="not JSON"):
        run(c.instant("SELECT average(cpuPercent) FROM SystemSample FACET hostname"))


def test_healthy_check():
    c, _ = make()
    assert run(c.healthy()) is True

    bad_key = NewRelic(NewRelicCfg(account_id=12345, api_key="wrong"),
                        client=httpx.AsyncClient(transport=httpx.MockTransport(MockNewRelicServer().handler)))
    assert run(bad_key.healthy()) is False


def test_config_validation(tmp_path):
    assert not NewRelicCfg(account_id=12345).enabled
    assert not NewRelicCfg(api_key="key").enabled
    assert NewRelicCfg(account_id=12345, api_key="key").enabled
    assert NewRelicCfg(account_id="12345", api_key="key").account_id == 12345

    with pytest.raises(ValueError):
        NewRelicCfg(account_id="not-an-int", api_key="key")
    with pytest.raises(ValueError):
        NewRelicCfg(account_id=123, api_key="key", url="ftp://bad-url")

    f = tmp_path / "n.yaml"
    f.write_text("""
newrelic:
  account_id: 11111
  api_key: key1
servers:
  - id: s1
  - id: s2
    newrelic:
      account_id: 22222
      api_key: key2
      region: eu
""")
    views = {s.id: s for s in load_config(str(f)).server_views()}
    assert views["s1"].newrelic.account_id == 11111 and views["s1"].newrelic.region == "us"
    assert views["s2"].newrelic.account_id == 22222 and views["s2"].newrelic.region == "eu"


def test_api_integration_rules_and_incident_chart(tmp_path):
    nr, _ = make()
    cfg = load_config(None)
    cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    headers = {"X-Requested-With": "nigrani"}

    with TestClient(create_app(cfg, prom=FakeProm(), newrelic={"default": nr})) as c:
        c.post("/api/login", json={"username": "admin", "password": "pw"})
        me = c.get("/api/me").json()["servers"][0]
        assert me["newrelic"] is True
        assert "newrelic" in me["datasources"]

        body = {
            "name": "High CPU",
            "expr": "SELECT average(cpuPercent) FROM SystemSample FACET hostname",
            "warn": 80,
            "crit": 90,
            "datasource": "newrelic",
        }
        prev = c.post("/api/rules/test", json=body, headers=headers).json()
        assert prev["series"] == [
            {"series": "web-1", "value": 91.5, "severity": "critical"},
            {"series": "web-2", "value": 42.0, "severity": None},
            {"series": "web-3", "value": 15.5, "severity": None},
        ]

        made = c.post("/api/rules", json=body, headers=headers).json()
        labels = {"hostname": "web-1"}
        iid = c.app.state.store.create_incident(
            source_id=made["id"],
            series_key=series_key(labels),
            rule_name="High CPU",
            series="web-1",
            labels=labels,
            severity="critical",
            started_at=time.time() - 60,
            server="default"
        )
        incident_data = c.get(f"/api/incidents/{iid}").json()
        assert incident_data["chart"]["series"][0]["name"] == "web-1"


def test_api_without_newrelic_refuses_rules(tmp_path):
    cfg = load_config(None)
    cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    with TestClient(create_app(cfg, prom=FakeProm())) as c:
        c.post("/api/login", json={"username": "admin", "password": "pw"})
        r = c.post(
            "/api/rules",
            json={"name": "NR Rule", "expr": "SELECT 1 FROM SystemSample", "crit": 1, "datasource": "newrelic"},
            headers={"X-Requested-With": "nigrani"}
        )
        assert r.status_code == 422
        assert "newrelic" in r.json()["detail"]


def test_the_newrelic_preset_loads(tmp_path):
    f = tmp_path / "n.yaml"
    f.write_text("presets: [newrelic]\n")
    rules = {r.id: r for r in load_config(str(f)).rules}
    assert set(rules) == {"nr-host-cpu", "nr-host-memory", "nr-host-disk"}
    assert all(r.datasource == "newrelic" for r in rules.values())
