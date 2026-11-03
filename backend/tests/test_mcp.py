import asyncio
import threading
import time

import httpx
import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from conftest import FakeProm
from nigrani.api import create_app
from nigrani.auth import hash_token
from nigrani.config import load_config
from nigrani.passwords import hash_password
from nigrani.store import Store

H = {"X-Requested-With": "nigrani"}


def make_app(tmp_path, mcp=True, prom=None, demo=False):
    cfg = load_config(None, demo=demo)
    cfg.data_dir = str(tmp_path)
    if not demo:
        cfg.auth.password = "pw"
    cfg.mcp.enabled = mcp or demo
    return create_app(cfg, prom=prom)


def login(c, user="admin", pw="pw"):
    assert c.post("/api/login", json={"username": user, "password": pw}, headers=H).status_code == 200


def make_token(c, name="claude", role="viewer", **extra):
    r = c.post("/api/tokens", json={"name": name, "role": role, **extra}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


class Live:
    """The app on a real port in a thread, so a real MCP client can talk to it over HTTP."""

    def __init__(self, app):
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        end = time.time() + 15
        while not self.server.started and time.time() < end:
            time.sleep(0.05)
        self.url = f"http://127.0.0.1:{self.server.servers[0].sockets[0].getsockname()[1]}"
        return self

    def __exit__(self, *a):
        self.server.should_exit = True
        self.thread.join(10)


async def mcp_session(url, token=None):
    http = httpx2.AsyncClient(headers=bearer(token) if token else {})
    cm = streamable_http_client(url + "/mcp", http_client=http)
    streams = await cm.__aenter__()
    session = ClientSession(streams[0], streams[1])
    await session.__aenter__()
    await session.initialize()
    return session, cm, http


async def with_mcp(url, token, fn):
    session, cm, http = await mcp_session(url, token)
    try:
        return await fn(session)
    finally:
        await session.__aexit__(None, None, None)
        await cm.__aexit__(None, None, None)
        await http.aclose()


def text(result):
    return "".join(b.text for b in result.content)


# ---- API tokens ----
def test_a_token_is_shown_once_stored_hashed_and_works_as_a_bearer(tmp_path):
    with TestClient(make_app(tmp_path)) as c:
        login(c)
        r = c.post("/api/tokens", json={"name": "claude code", "role": "viewer"}, headers=H).json()
        token = r["token"]
        assert token.startswith("nig_") and len(token) > 40
        listed = c.get("/api/tokens").json()
        assert [t["name"] for t in listed] == ["claude code"] and token not in str(listed) and listed[0]["prefix"] == token[:8]
        row = c.app.state.store.find_api_token(hash_token(token))
        assert row and token not in str(row)                                  # only the hash is in the database
        anon = TestClient(c.app)                                              # a client with no session cookie
        me = anon.get("/api/me", headers=bearer(token)).json()
        assert me["user"] == "token:claude code" and me["role"] == "viewer" and me["provider"] == "token"
        assert anon.get("/api/overview", headers=bearer(token)).status_code == 200


def test_a_token_has_the_role_it_was_given_and_never_admin(tmp_path):
    with TestClient(make_app(tmp_path)) as c:
        login(c)
        viewer, editor = make_token(c, "v", "viewer"), make_token(c, "e", "editor")
        anon = TestClient(c.app)
        rule = {"name": "x", "expr": "up", "warn": 1}
        assert anon.post("/api/rules", json=rule, headers=bearer(viewer)).status_code == 403
        assert anon.post("/api/rules", json=rule, headers=bearer(editor)).status_code == 200
        for t in (viewer, editor):
            assert anon.get("/api/users", headers=bearer(t)).status_code == 403
            assert anon.get("/api/tokens", headers=bearer(t)).status_code == 403
            assert anon.post("/api/tokens", json={"name": "n"}, headers=bearer(t)).status_code == 403
        assert c.post("/api/tokens", json={"name": "a", "role": "admin"}, headers=H).status_code == 422


def test_bad_expired_and_revoked_tokens_are_refused(tmp_path):
    with TestClient(make_app(tmp_path)) as c:
        login(c)
        token = make_token(c, "short", days=1)
        anon = TestClient(c.app)
        assert anon.get("/api/me", headers=bearer("nig_notarealtoken")).status_code == 401
        assert anon.get("/api/me", headers=bearer("nope")).status_code == 401
        assert anon.get("/api/me", headers=bearer(token)).status_code == 200
        c.app.state.store._x("UPDATE api_tokens SET expires_at=?", (time.time() - 5,))
        assert anon.get("/api/me", headers=bearer(token)).status_code == 401           # expired
        token2 = make_token(c, "gone")
        tid = next(t["id"] for t in c.get("/api/tokens").json() if t["name"] == "gone")
        assert anon.get("/api/me", headers=bearer(token2)).status_code == 200
        assert c.delete(f"/api/tokens/{tid}", headers=H).status_code == 200
        assert anon.get("/api/me", headers=bearer(token2)).status_code == 401           # revoked


def test_only_admins_manage_tokens_and_it_is_audited(tmp_path):
    with TestClient(make_app(tmp_path)) as c:
        login(c)
        c.app.state.store.create_user(username="ed", role="editor", password_hash=hash_password("a-long-passphrase-1"))
        make_token(c, "audited")
        assert any(a["action"] == "token.create" for a in c.get("/api/audit").json())
        c.post("/api/logout", headers=H)
        login(c, "ed", "a-long-passphrase-1")
        assert c.post("/api/tokens", json={"name": "n"}, headers=H).status_code == 403


# ---- ad-hoc queries ----
def test_query_endpoints_are_read_only_summaries(tmp_path):
    prom = FakeProm()
    prom.values["up"] = [({"job": "a"}, 1.0), ({"job": "b"}, 0.0)]
    with TestClient(make_app(tmp_path, prom=prom)) as c:
        login(c)
        d = c.get("/api/query", params={"expr": "up"}).json()
        assert d["count"] == 2 and {s["labels"]["job"]: s["value"] for s in d["series"]} == {"a": 1.0, "b": 0.0}
        r = c.get("/api/query_range", params={"expr": "up", "minutes": 30}).json()
        assert r["count"] == 2 and r["series"][0]["first"] == 1.0 and {"min", "max", "last", "points"} <= set(r["series"][0])
        assert c.get("/api/query", params={"expr": "up", "datasource": "sentry"}).status_code == 400
        prom.up = False
        assert c.get("/api/query", params={"expr": "up"}).status_code == 502


# ---- the MCP server ----
def test_mcp_is_off_unless_enabled(tmp_path):
    with TestClient(make_app(tmp_path, mcp=False)) as c:
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert r.status_code in (404, 405)


def test_mcp_needs_a_valid_token(tmp_path):
    with TestClient(make_app(tmp_path)) as c:
        login(c)
        token = make_token(c)
        anon = TestClient(c.app)
        body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
        accept = {"Accept": "application/json, text/event-stream"}
        r = anon.post("/mcp", json=body, headers=accept)
        assert r.status_code == 401 and "Bearer" in r.headers["www-authenticate"] and "API token" in r.json()["detail"]
        assert anon.post("/mcp", json=body, headers={**accept, **bearer("nig_wrong")}).status_code == 401
        assert c.post("/mcp", json=body, headers=accept).status_code == 401              # a logged-in browser session is not enough
        assert anon.post("/mcp", json=body, headers={**accept, **bearer(token)}).status_code == 200


def test_a_real_mcp_client_can_investigate_an_alert(tmp_path):
    prom = FakeProm()
    prom.values["up"] = [({"job": "api"}, 1.0)]
    with TestClient(make_app(tmp_path, prom=prom)) as boot:      # create the data (an incident and a token) with a first instance
        login(boot)
        token = make_token(boot, "assistant")
        iid = boot.app.state.store.create_incident(source_id="r", series_key="a", rule_name="Disk filling up", series="/data", severity="critical",
                                                   started_at=time.time() - 900, value=93.0, threshold=90.0, unit="percent", summary="disk")
    with Live(make_app(tmp_path, prom=prom)) as live:           # a second instance on the same data directory serves the client
        async def go(s):
            tools = await s.list_tools()
            names = {t.name for t in tools.tools}
            assert {"nigrani_status", "nigrani_incidents", "nigrani_incident", "nigrani_query", "nigrani_query_range", "nigrani_slos"} <= names
            assert all(t.annotations.read_only_hint for t in tools.tools)                  # nothing here can change anything
            status = await s.call_tool("nigrani_status", {})
            assert not status.is_error and "Disk filling up" in text(status)
            inc = await s.call_tool("nigrani_incidents", {"status": "firing"})
            assert f'"id": {iid}' in text(inc) and '"count": 1' in text(inc)
            detail = await s.call_tool("nigrani_incident", {"incident_id": iid})
            assert "Rule: Disk filling up" in text(detail) and "critical" in text(detail)
            q = await s.call_tool("nigrani_query", {"expr": "up"})
            assert '"job": "api"' in text(q)
            missing = await s.call_tool("nigrani_incident", {"incident_id": 9999})
            assert missing.is_error and "unknown incident" in text(missing)
            nope = await s.call_tool("nigrani_argocd", {})
            assert nope.is_error and "not configured" in text(nope)
            return True
        assert asyncio.run(with_mcp(live.url, token, go))


def test_the_tools_run_with_the_callers_role_and_a_revoked_token_stops_working(tmp_path):
    with TestClient(make_app(tmp_path)) as boot:
        login(boot)
        token = make_token(boot, "temp")
        tid = boot.get("/api/tokens").json()[0]["id"]
    with Live(make_app(tmp_path)) as live:
        async def ok(s):
            return not (await s.call_tool("nigrani_servers", {})).is_error
        assert asyncio.run(with_mcp(live.url, token, ok))
        Store(str(tmp_path / "nigrani.db")).delete_api_token(tid)              # an admin revokes it (same database)
        with pytest.raises(Exception):
            asyncio.run(with_mcp(live.url, token, ok))
        assert httpx.post(live.url + "/mcp", json={}, headers={"Accept": "application/json, text/event-stream", **bearer(token)}).status_code == 401


def test_demo_mode_serves_mcp_without_a_token(tmp_path):
    app = make_app(tmp_path, demo=True)
    with Live(app) as live:
        async def go(s):
            r = await s.call_tool("nigrani_status", {})
            assert not r.is_error and "operational" in text(r)
            return len((await s.list_tools()).tools)
        assert asyncio.run(with_mcp(live.url, None, go)) >= 10
