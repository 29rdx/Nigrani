import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from conftest import FakeProm
from nigrani.api import create_app
from nigrani.config import load_config
from nigrani.passwords import hash_password
from nigrani.store import Store

H = {"X-Requested-With": "nigrani"}
YAML = """
status_page: {enabled: true, days: 30, title: Acme status}
checks:
  - {id: web, name: Website, type: http, target: "%s"}
"""


@pytest.fixture(scope="module")
def site():
    """A site that is up, so the real check runner has something healthy to look at."""
    class Ok(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("content-length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Ok)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/"
    srv.shutdown()


def make_client(tmp_path, site):
    f = tmp_path / "n.yaml"
    f.write_text(YAML % site)
    cfg = load_config(str(f), explicit=True)
    cfg.data_dir, cfg.auth.password = str(tmp_path), "pw"
    return TestClient(create_app(cfg, prom=FakeProm()))


def first_check_done(c):
    end = time.time() + 10
    while not c.app.state.store.last_check_result("web") and time.time() < end:
        time.sleep(0.05)
    assert c.app.state.store.last_check_result("web")


def login(c, user="admin", pw="pw"):
    assert c.post("/api/login", json={"username": user, "password": pw}, headers=H).status_code == 200


def test_daily_bars_cover_the_period_and_show_gaps_and_outages(tmp_path, site):
    with make_client(tmp_path, site) as c:
        store = c.app.state.store
        first_check_done(c)
        now = time.time()
        store.add_check_day("web", now - 3 * 86400, 1440, 1440)
        store.add_check_day("web", now - 2 * 86400, 1296, 1440)       # 90% that day
        d = c.get("/api/public/status").json()
        bars = d["checks"][0]["days"]
        assert len(bars) == 30 and d["period_days"] == 30
        assert bars[-4]["pct"] == 100 and round(bars[-3]["pct"]) == 90        # oldest first
        assert bars[0]["pct"] is None                                          # nothing recorded that long ago
        assert bars[-1]["pct"] == 100                                          # today: the running check is healthy
        assert round(d["checks"][0]["uptime_period"]) == 97


def test_every_check_result_adds_to_its_day(tmp_path):
    store = Store(":memory:")
    now = time.time()
    for ok in (True, True, False, True):
        store.add_check_result("a", now, ok, 5.0, "")
    day = store.check_days("a", now - 86400)
    assert day[-1]["up"] == 3 and day[-1]["total"] == 4


def test_daily_totals_are_built_for_databases_that_only_have_raw_results(tmp_path):
    p = str(tmp_path / "old.db")
    s = Store(p)
    now = time.time()
    s._x("INSERT INTO check_results(check_id,ts,ok,latency_ms,detail) VALUES('x',?,1,1,'')", (now,))
    s._x("INSERT INTO check_results(check_id,ts,ok,latency_ms,detail) VALUES('x',?,0,1,'')", (now,))
    s._x("DELETE FROM check_daily")
    s2 = Store(p)                                                      # next start
    assert s2.check_days("x", now - 86400)[-1] == {"day": time.strftime("%Y-%m-%d", time.gmtime(now)), "up": 1, "total": 2}


def test_announcements_are_public_and_editors_manage_them(tmp_path, site):
    with make_client(tmp_path, site) as c:
        login(c)
        r = c.post("/api/announcements", json={"kind": "incident", "title": "Slow logins", "body": "We are looking."}, headers=H)
        assert r.status_code == 200 and r.json()["state"] == "active"
        aid = r.json()["id"]
        pub = TestClient(c.app)                                         # a visitor with no session
        shown = pub.get("/api/public/status").json()["announcements"]
        assert [a["title"] for a in shown] == ["Slow logins"]
        assert pub.get("/api/announcements").status_code == 401           # managing needs a login
        c.post(f"/api/announcements/{aid}/resolve", headers=H)
        assert pub.get("/api/public/status").json()["announcements"][0]["state"] == "resolved"
        assert c.delete(f"/api/announcements/{aid}", headers=H).status_code == 200
        assert pub.get("/api/public/status").json()["announcements"] == []


def test_maintenance_window_changes_the_banner_only_while_it_runs(tmp_path, site):
    with make_client(tmp_path, site) as c:
        login(c)
        now = time.time()
        c.post("/api/announcements", json={"kind": "maintenance", "title": "Database upgrade",
                                           "starts_at": now + 3600, "ends_at": now + 7200}, headers=H)
        d = c.get("/api/public/status").json()
        assert d["announcements"][0]["state"] == "scheduled" and d["status"] != "maintenance"
        c.post("/api/announcements", json={"kind": "maintenance", "title": "Now", "starts_at": now - 60, "ends_at": now + 600}, headers=H)
        assert c.get("/api/public/status").json()["status"] == "maintenance"


def test_bad_announcements_are_rejected(tmp_path, site):
    with make_client(tmp_path, site) as c:
        login(c)
        now = time.time()
        assert c.post("/api/announcements", json={"title": ""}, headers=H).status_code == 422
        assert c.post("/api/announcements", json={"title": "x", "starts_at": now, "ends_at": now - 5}, headers=H).status_code == 422
        assert c.post("/api/announcements/999/resolve", headers=H).status_code == 404


def test_viewers_cannot_post_announcements(tmp_path, site):
    with make_client(tmp_path, site) as c:
        login(c)
        c.app.state.store.create_user(username="viewer1", role="viewer", password_hash=hash_password("a-long-passphrase-1"))
        c.post("/api/logout", headers=H)
        login(c, "viewer1", "a-long-passphrase-1")
        assert c.get("/api/announcements").status_code == 200
        assert c.post("/api/announcements", json={"title": "x"}, headers=H).status_code == 403


def test_a_failing_check_is_major_even_during_maintenance(tmp_path, site):
    with make_client(tmp_path, site) as c:
        login(c)
        now = time.time()
        c.post("/api/announcements", json={"kind": "maintenance", "title": "m", "starts_at": now - 60}, headers=H)
        c.app.state.store.add_check_result("web", now + 5, False, None, "down")
        assert c.get("/api/public/status").json()["status"] == "major"
