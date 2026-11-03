"""SQLite persistence: rules, channels, incidents, silences, uptime checks, kv."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .fingerprint import fingerprint

SCHEMA = """
CREATE TABLE IF NOT EXISTS rules (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, expr TEXT NOT NULL,
  direction TEXT NOT NULL DEFAULT 'above', warn REAL, crit REAL,
  for_seconds INTEGER NOT NULL DEFAULT 300, unit TEXT NOT NULL DEFAULT 'short',
  summary TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL DEFAULT 'custom', updated_at REAL, servers TEXT NOT NULL DEFAULT '[]',
  datasource TEXT NOT NULL DEFAULT 'prometheus', preset_hash TEXT
);
CREATE TABLE IF NOT EXISTS channels (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, settings TEXT NOT NULL DEFAULT '{}',
  min_severity TEXT NOT NULL DEFAULT 'warning', quiet_start INTEGER, quiet_end INTEGER,
  enabled INTEGER NOT NULL DEFAULT 1, last_error TEXT, last_sent_at REAL, servers TEXT NOT NULL DEFAULT '[]',
  title_template TEXT, body_template TEXT
);
CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL, series_key TEXT NOT NULL,
  rule_name TEXT NOT NULL, series TEXT NOT NULL DEFAULT '', labels TEXT NOT NULL DEFAULT '{}',
  severity TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'firing',
  started_at REAL NOT NULL, resolved_at REAL, last_value REAL, peak_value REAL,
  threshold REAL, unit TEXT NOT NULL DEFAULT 'short', summary TEXT NOT NULL DEFAULT '',
  last_notified REAL, silenced INTEGER NOT NULL DEFAULT 0, server TEXT NOT NULL DEFAULT 'default',
  acked_at REAL, acked_by TEXT, ack_note TEXT, ack_until REAL
);
CREATE INDEX IF NOT EXISTS ix_incidents_status ON incidents(status, started_at);
CREATE TABLE IF NOT EXISTS silences (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT, match TEXT,
  until REAL NOT NULL, reason TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, server TEXT
);
CREATE TABLE IF NOT EXISTS check_results (
  check_id TEXT NOT NULL, ts REAL NOT NULL, ok INTEGER NOT NULL, latency_ms REAL, detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_checks ON check_results(check_id, ts);
CREATE TABLE IF NOT EXISTS incident_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL, ts REAL NOT NULL, kind TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_incident_events ON incident_events(incident_id, ts);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL DEFAULT '',
  email TEXT, role TEXT NOT NULL DEFAULT 'viewer', password_hash TEXT, provider TEXT NOT NULL DEFAULT 'local',
  disabled INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, last_login REAL
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, user TEXT NOT NULL, action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '', status INTEGER
);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit(ts);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS check_daily (
  check_id TEXT NOT NULL, day TEXT NOT NULL, up INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (check_id, day)
);
CREATE TABLE IF NOT EXISTS announcements (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL DEFAULT 'info', title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '', starts_at REAL NOT NULL, ends_at REAL, resolved_at REAL,
  created_by TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
);
"""


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)
            self._migrate()
            self._db.commit()

    def _migrate(self) -> None:
        """Add columns introduced after the first release to databases created by older versions."""
        wanted = {
            "rules": [("servers", "TEXT NOT NULL DEFAULT '[]'"), ("datasource", "TEXT NOT NULL DEFAULT 'prometheus'"),
                      ("preset_hash", "TEXT")],
            "channels": [("servers", "TEXT NOT NULL DEFAULT '[]'"), ("title_template", "TEXT"), ("body_template", "TEXT")],
            "incidents": [("server", "TEXT NOT NULL DEFAULT 'default'"), ("acked_at", "REAL"), ("acked_by", "TEXT"),
                      ("ack_note", "TEXT"), ("ack_until", "REAL")],
            "silences": [("server", "TEXT")],
        }
        for table, cols in wanted.items():
            have = {r["name"] for r in self._db.execute(f"PRAGMA table_info({table})")}
            for name, ddl in cols:
                if name not in have:
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        # daily uptime totals (they outlive the raw check results) for databases that only have the raw rows
        if not self._db.execute("SELECT 1 FROM check_daily LIMIT 1").fetchone():
            self._db.execute(
                "INSERT INTO check_daily(check_id, day, up, total) SELECT check_id, date(ts, 'unixepoch'), SUM(ok), COUNT(*) "
                "FROM check_results GROUP BY check_id, date(ts, 'unixepoch')")

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur.lastrowid or 0

    # ---- users ----
    @staticmethod
    def _user(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["disabled"] = bool(d["disabled"])
        d["has_password"] = bool(d.get("password_hash"))
        return d

    def create_user(self, *, username: str, role: str, name: str = "", email: str | None = None,
                    password_hash: str | None = None, provider: str = "local") -> dict[str, Any]:
        uid = self._x("INSERT INTO users(username,name,email,role,password_hash,provider,created_at) VALUES(?,?,?,?,?,?,?)",
                      (username, name or username, email, role, password_hash, provider, time.time()))
        return self.get_user(uid)  # type: ignore[return-value]

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM users WHERE id=?", (user_id,))
        return self._user(rows[0]) if rows else None

    def get_user_by_name(self, username: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM users WHERE username=?", (username,))
        return self._user(rows[0]) if rows else None

    def list_users(self) -> list[dict[str, Any]]:
        return [self._user(r) for r in self._q("SELECT * FROM users ORDER BY username")]

    def update_user(self, user_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {"name", "email", "role", "password_hash", "disabled"}
        fields = {k: (int(v) if k == "disabled" else v) for k, v in fields.items() if k in allowed}
        if fields:
            cols = ", ".join(f"{k}=?" for k in fields)
            self._x(f"UPDATE users SET {cols} WHERE id=?", (*fields.values(), user_id))
        return self.get_user(user_id)

    def delete_user(self, user_id: int) -> None:
        self._x("DELETE FROM users WHERE id=?", (user_id,))

    def touch_login(self, user_id: int) -> None:
        self._x("UPDATE users SET last_login=? WHERE id=?", (time.time(), user_id))

    # ---- audit log ----
    def add_audit(self, user: str, action: str, detail: str = "", ip: str = "", status: int | None = None) -> None:
        self._x("INSERT INTO audit(ts,user,action,detail,ip,status) VALUES(?,?,?,?,?,?)",
                (time.time(), user, action, detail[:500], ip, status))

    def list_audit(self, limit: int = 200, user: str | None = None, since: float | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM audit WHERE ts >= ?", [since or 0]
        if user:
            sql += " AND user=?"
            args.append(user)
        return [dict(r) for r in self._q(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))]

    # ---- kv ----
    def kv_get(self, key: str, default: Any = None) -> Any:
        rows = self._q("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def kv_set(self, key: str, value: Any) -> None:
        self._x("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))

    # ---- rules ----
    def seed_rule(self, r: dict[str, Any]) -> None:
        self._x(
            "INSERT OR IGNORE INTO rules(id,name,expr,direction,warn,crit,for_seconds,unit,summary,enabled,source,updated_at,servers,datasource)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["id"], r["name"], r["expr"], r["direction"], r.get("warn"), r.get("crit"), r["for_seconds"],
             r["unit"], r.get("summary", ""), int(r.get("enabled", True)), "preset", time.time(),
             json.dumps(r.get("servers") or []), r.get("datasource", "prometheus")),
        )

    def sync_preset_rule(self, r: dict[str, Any], legacy: frozenset[str] | set[str] = frozenset()) -> str:
        """Seed a preset rule, and carry a later fix to the preset over to rows nobody has edited.

        Returns "created", "updated" or "kept". `preset_hash` is the fingerprint of the definition last written from
        the preset; a row whose current fingerprint still equals it is unedited. Rows from before this existed have no
        hash and count as unedited only if they match something a released version shipped (`legacy`)."""
        shipped = fingerprint(r)
        row = self.get_rule(r["id"])
        if row is None:
            self.seed_rule(r)
            self._x("UPDATE rules SET preset_hash=? WHERE id=?", (shipped, r["id"]))
            return "created"
        if row["source"] != "preset":
            return "kept"
        current = fingerprint(row)
        unedited = (current == row["preset_hash"]) if row["preset_hash"] else (current in legacy)
        if not unedited:
            return "kept"
        if current == shipped:
            self._x("UPDATE rules SET preset_hash=? WHERE id=?", (shipped, r["id"]))
            return "kept"
        self._x(
            "UPDATE rules SET name=?, expr=?, direction=?, warn=?, crit=?, for_seconds=?, unit=?, summary=?, datasource=?,"
            " preset_hash=?, updated_at=? WHERE id=?",   # `enabled` and `servers` stay as the user set them
            (r["name"], r["expr"], r["direction"], r.get("warn"), r.get("crit"), r["for_seconds"], r["unit"],
             r.get("summary", ""), r.get("datasource", "prometheus"), shipped, time.time(), r["id"]))
        return "updated"

    def save_rule(self, r: dict[str, Any]) -> dict[str, Any]:
        self._x(
            "INSERT INTO rules(id,name,expr,direction,warn,crit,for_seconds,unit,summary,enabled,source,updated_at,servers,datasource)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, expr=excluded.expr,"
            " direction=excluded.direction, warn=excluded.warn, crit=excluded.crit, for_seconds=excluded.for_seconds,"
            " unit=excluded.unit, summary=excluded.summary, enabled=excluded.enabled, updated_at=excluded.updated_at,"
            " servers=excluded.servers, datasource=excluded.datasource",
            (r["id"], r["name"], r["expr"], r["direction"], r.get("warn"), r.get("crit"), r["for_seconds"],
             r["unit"], r.get("summary", ""), int(r.get("enabled", True)), r.get("source", "custom"), time.time(),
             json.dumps(r.get("servers") or []), r.get("datasource", "prometheus")),
        )
        return self.get_rule(r["id"])  # type: ignore[return-value]

    def list_rules(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM rules" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY source, name"
        return [self._rule(r) for r in self._q(sql)]

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM rules WHERE id=?", (rule_id,))
        return self._rule(rows[0]) if rows else None

    def delete_rule(self, rule_id: str) -> None:
        self._x("DELETE FROM rules WHERE id=?", (rule_id,))

    @staticmethod
    def _rule(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["enabled"] = bool(d["enabled"])
        d["servers"] = json.loads(d.get("servers") or "[]")
        return d

    # ---- channels ----
    def seed_channel(self, c: dict[str, Any]) -> None:
        qh = c.get("quiet_hours") or [None, None]
        self._x(
            "INSERT OR IGNORE INTO channels(id,name,type,settings,min_severity,quiet_start,quiet_end,enabled,servers,"
            "title_template,body_template) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (c["id"], c["name"], c["type"], json.dumps(c.get("settings", {})), c.get("min_severity", "warning"),
             qh[0], qh[1], int(c.get("enabled", True)), json.dumps(c.get("servers") or []),
             c.get("title_template") or None, c.get("body_template") or None),
        )

    def save_channel(self, c: dict[str, Any]) -> dict[str, Any]:
        self._x(
            "INSERT INTO channels(id,name,type,settings,min_severity,quiet_start,quiet_end,enabled,servers,"
            "title_template,body_template) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
            " type=excluded.type, settings=excluded.settings, min_severity=excluded.min_severity,"
            " quiet_start=excluded.quiet_start, quiet_end=excluded.quiet_end, enabled=excluded.enabled,"
            " servers=excluded.servers, title_template=excluded.title_template, body_template=excluded.body_template",
            (c["id"], c["name"], c["type"], json.dumps(c.get("settings", {})), c.get("min_severity", "warning"),
             c.get("quiet_start"), c.get("quiet_end"), int(c.get("enabled", True)), json.dumps(c.get("servers") or []),
             c.get("title_template") or None, c.get("body_template") or None),
        )
        return self.get_channel(c["id"])  # type: ignore[return-value]

    def list_channels(self) -> list[dict[str, Any]]:
        return [self._channel(r) for r in self._q("SELECT * FROM channels ORDER BY name")]

    def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM channels WHERE id=?", (channel_id,))
        return self._channel(rows[0]) if rows else None

    def delete_channel(self, channel_id: str) -> None:
        self._x("DELETE FROM channels WHERE id=?", (channel_id,))

    def channel_result(self, channel_id: str, error: str | None) -> None:
        self._x("UPDATE channels SET last_error=?, last_sent_at=? WHERE id=?", (error, time.time(), channel_id))

    @staticmethod
    def _channel(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["settings"] = json.loads(d["settings"] or "{}")
        d["enabled"] = bool(d["enabled"])
        d["servers"] = json.loads(d.get("servers") or "[]")
        return d

    # ---- incidents ----
    def create_incident(self, **f: Any) -> int:
        return self._x(
            "INSERT INTO incidents(source_id,series_key,rule_name,series,labels,severity,status,started_at,"
            "last_value,peak_value,threshold,unit,summary,last_notified,silenced,server) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f["source_id"], f["series_key"], f["rule_name"], f.get("series", ""), json.dumps(f.get("labels", {})),
             f["severity"], "firing", f["started_at"], f.get("value"), f.get("value"), f.get("threshold"),
             f.get("unit", "short"), f.get("summary", ""), f.get("last_notified"), int(f.get("silenced", False)),
             f.get("server", "default")),
        )

    def update_incident(self, incident_id: int, **f: Any) -> None:
        if not f:
            return
        cols = ", ".join(f"{k}=?" for k in f)
        self._x(f"UPDATE incidents SET {cols} WHERE id=?", (*f.values(), incident_id))

    def resolve_incident(self, incident_id: int, now: float, last_value: float | None) -> None:
        self._x("UPDATE incidents SET status='resolved', resolved_at=?, last_value=COALESCE(?, last_value) WHERE id=?",
                (now, last_value, incident_id))

    def add_event(self, incident_id: int, ts: float, kind: str, detail: str = "") -> None:
        self._x("INSERT INTO incident_events(incident_id,ts,kind,detail) VALUES(?,?,?,?)", (incident_id, ts, kind, detail))

    def list_events(self, incident_id: int) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q(
            "SELECT ts, kind, detail FROM incident_events WHERE incident_id=? ORDER BY ts, id", (incident_id,))]

    def ack_incident(self, incident_id: int, by: str, note: str, until: float | None, now: float) -> None:
        self._x("UPDATE incidents SET acked_at=?, acked_by=?, ack_note=?, ack_until=? WHERE id=? AND status='firing'",
                (now, by, note, until, incident_id))

    def clear_ack(self, incident_id: int) -> None:
        self._x("UPDATE incidents SET acked_at=NULL, acked_by=NULL, ack_note=NULL, ack_until=NULL WHERE id=?",
                (incident_id,))

    def get_incident(self, incident_id: int) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM incidents WHERE id=?", (incident_id,))
        return self._incident(rows[0]) if rows else None

    def open_incidents(self) -> list[dict[str, Any]]:
        return [self._incident(r) for r in self._q(
            "SELECT * FROM incidents WHERE status='firing' ORDER BY CASE severity WHEN 'critical' THEN 0 ELSE 1 END, started_at")]

    def recent_incidents(self, limit: int = 100, since: float | None = None,
                         server: str | None = None) -> list[dict[str, Any]]:
        if server:
            rows = self._q("SELECT * FROM incidents WHERE started_at >= ? AND server=? ORDER BY started_at DESC LIMIT ?",
                           (since or 0, server, limit))
        else:
            rows = self._q("SELECT * FROM incidents WHERE started_at >= ? ORDER BY started_at DESC LIMIT ?",
                           (since or 0, limit))
        return [self._incident(r) for r in rows]

    @staticmethod
    def _incident(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["labels"] = json.loads(d["labels"] or "{}")
        d["silenced"] = bool(d["silenced"])
        return d

    # ---- silences ----
    def add_silence(self, source_id: str | None, match: str | None, until: float, reason: str,
                    server: str | None = None) -> int:
        return self._x("INSERT INTO silences(source_id,match,until,reason,created_at,server) VALUES(?,?,?,?,?,?)",
                       (source_id or None, match or None, until, reason, time.time(), server or None))

    def list_silences(self, now: float | None = None) -> list[dict[str, Any]]:
        rows = self._q("SELECT * FROM silences WHERE until > ? ORDER BY until", (now or time.time(),))
        return [dict(r) for r in rows]

    def delete_silence(self, silence_id: int) -> None:
        self._x("DELETE FROM silences WHERE id=?", (silence_id,))

    def is_silenced(self, source_id: str, series: str, now: float, server: str = "default") -> bool:
        for s in self.list_silences(now):
            if s["source_id"] and s["source_id"] != source_id:
                continue
            if s.get("server") and s["server"] != server:
                continue
            if s["match"] and s["match"].lower() not in series.lower():
                continue
            return True
        return False

    # ---- uptime checks ----
    def add_check_result(self, check_id: str, ts: float, ok: bool, latency_ms: float | None, detail: str) -> None:
        self._x("INSERT INTO check_results(check_id,ts,ok,latency_ms,detail) VALUES(?,?,?,?,?)",
                (check_id, ts, int(ok), latency_ms, detail))
        self.add_check_day(check_id, ts, int(ok), 1)

    def add_check_day(self, check_id: str, ts: float, up: int, total: int) -> None:
        """Add to the UTC day's totals. These are kept for 400 days, so the status page can show a long history."""
        self._x("INSERT INTO check_daily(check_id, day, up, total) VALUES(?, date(?, 'unixepoch'), ?, ?) "
                "ON CONFLICT(check_id, day) DO UPDATE SET up = up + excluded.up, total = total + excluded.total",
                (check_id, ts, up, total))

    def check_days(self, check_id: str, since: float) -> list[dict[str, Any]]:
        rows = self._q("SELECT day, up, total FROM check_daily WHERE check_id=? AND day >= date(?, 'unixepoch') ORDER BY day",
                       (check_id, since))
        return [dict(r) for r in rows]

    # ---- status page announcements ----
    def add_announcement(self, *, kind: str, title: str, body: str, starts_at: float, ends_at: float | None,
                         by: str, now: float) -> int:
        return self._x("INSERT INTO announcements(kind,title,body,starts_at,ends_at,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
                       (kind, title, body, starts_at, ends_at, by, now))

    def get_announcement(self, announcement_id: int) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM announcements WHERE id=?", (announcement_id,))
        return dict(rows[0]) if rows else None

    def list_announcements(self, since: float, limit: int = 50) -> list[dict[str, Any]]:
        """Everything still relevant: unresolved, or resolved after `since`. Newest first."""
        rows = self._q("SELECT * FROM announcements WHERE resolved_at IS NULL OR resolved_at >= ? ORDER BY starts_at DESC LIMIT ?",
                       (since, limit))
        return [dict(r) for r in rows]

    def resolve_announcement(self, announcement_id: int, now: float) -> None:
        self._x("UPDATE announcements SET resolved_at=? WHERE id=? AND resolved_at IS NULL", (now, announcement_id))

    def delete_announcement(self, announcement_id: int) -> None:
        self._x("DELETE FROM announcements WHERE id=?", (announcement_id,))

    def check_uptime(self, check_id: str, since: float) -> tuple[int, int]:
        r = self._q("SELECT COALESCE(SUM(ok),0) AS up, COUNT(*) AS n FROM check_results WHERE check_id=? AND ts>=?",
                    (check_id, since))[0]
        return int(r["up"]), int(r["n"])

    def last_check_result(self, check_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM check_results WHERE check_id=? ORDER BY ts DESC LIMIT 1", (check_id,))
        return _row(rows[0]) if rows else None

    def check_history(self, check_id: str, since: float, limit: int = 120) -> list[dict[str, Any]]:
        rows = self._q("SELECT ts, ok, latency_ms FROM check_results WHERE check_id=? AND ts>=? ORDER BY ts DESC LIMIT ?",
                       (check_id, since, limit))
        return [dict(r) for r in reversed(rows)]

    def prune(self, retention_days: int) -> None:
        cutoff = time.time() - retention_days * 86400
        self._x("DELETE FROM check_results WHERE ts < ?", (cutoff,))
        self._x("DELETE FROM check_daily WHERE day < date(?, 'unixepoch')", (time.time() - 400 * 86400,))
        self._x("DELETE FROM announcements WHERE resolved_at IS NOT NULL AND resolved_at < ?", (cutoff,))
        self._x("DELETE FROM incidents WHERE status='resolved' AND resolved_at < ?", (cutoff,))
        self._x("DELETE FROM silences WHERE until < ?", (time.time() - 86400,))
        self._x("DELETE FROM incident_events WHERE incident_id NOT IN (SELECT id FROM incidents)")
        self._x("DELETE FROM audit WHERE ts < ?", (cutoff,))
