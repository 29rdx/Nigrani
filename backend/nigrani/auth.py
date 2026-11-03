"""Sessions and roles.

Signed-cookie sessions. The account in the config (auth.username / auth.password) is the break-glass administrator: it
always works, always has the admin role and cannot be edited from the UI. Everyone else lives in the database (local
password or single sign-on) with a role: viewer (read), editor (change alerts, channels, silences) or admin (users,
restoring backups, credentials).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request

from .passwords import DUMMY_HASH, verify_password

if TYPE_CHECKING:
    from .store import Store

COOKIE = "nigrani_session"
TOKEN_PREFIX = "nig_"
ROLES = ("viewer", "editor", "admin")
RANK = {r: i for i, r in enumerate(ROLES)}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Identity:
    username: str
    name: str
    role: str
    provider: str  # config | local | oidc | token
    user_id: int | None = None

    def can(self, role: str) -> bool:
        return RANK[self.role] >= RANK[role]


# What a request needs. Read access is the default for GET; anything that changes state needs at least `editor`,
# so a new mutating route that is forgotten here fails closed instead of being open to viewers.
ADMIN_PREFIXES = ("/api/users", "/api/audit", "/api/backup/import", "/api/tokens")
VIEWER_POSTS = {"/api/rules/test", "/api/channels/preview"}  # previews: they only read


def required_role(method: str, path: str, query: dict[str, Any] | None = None) -> str:
    if path.startswith(ADMIN_PREFIXES):
        return "admin"
    if path == "/api/backup":  # the configuration, secrets only for admins
        return "admin" if str((query or {}).get("include_secrets", "")).lower() in ("1", "true") else "editor"
    if method in ("GET", "HEAD", "OPTIONS") or path in VIEWER_POSTS:
        return "viewer"
    return "editor"


class Auth:
    def __init__(self, username: str, password: str, secret: str, session_hours: int, enabled: bool = True,
                 store: "Store | None" = None):
        self.username, self.password = username, password
        self.secret = (secret or secrets.token_hex(32)).encode()
        self.ttl = session_hours * 3600
        self.enabled = enabled
        self.store = store
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    # ---- tokens ----
    def _sign(self, payload: bytes) -> str:
        return hmac.new(self.secret, payload, hashlib.sha256).hexdigest()

    def sign_blob(self, data: dict[str, Any], ttl: int) -> str:
        payload = base64.urlsafe_b64encode(json.dumps({**data, "exp": int(time.time()) + ttl}).encode())
        return payload.decode() + "." + self._sign(payload)

    def read_blob(self, token: str | None) -> dict[str, Any] | None:
        if not token or "." not in token:
            return None
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(payload.encode())):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(payload.encode()))
        except ValueError:
            return None
        return data if data.get("exp", 0) > time.time() else None

    def make_token(self, user: str, provider: str = "config") -> str:
        return self.sign_blob({"u": user, "p": provider}, self.ttl)

    def verify_token(self, token: str | None) -> str | None:
        data = self.read_blob(token)
        return data["u"] if data and "u" in data else None

    # ---- login ----
    def throttled(self, ip: str) -> bool:
        q = self._fails[ip]
        while q and q[0] < time.time() - 300:
            q.popleft()
        return len(q) >= 5

    def check_login(self, ip: str, username: str, password: str) -> bool:
        """The configured administrator only (kept for callers that don't need roles)."""
        ok = hmac.compare_digest(username, self.username) & hmac.compare_digest(password, self.password)
        if not ok:
            self._fails[ip].append(time.time())
        return bool(ok)

    def login(self, ip: str, username: str, password: str) -> Identity | None:
        if self.password and hmac.compare_digest(username, self.username) & hmac.compare_digest(password, self.password):
            return Identity(self.username, self.username, "admin", "config")
        user = self.store.get_user_by_name(username) if self.store else None
        if user and user["provider"] == "local" and user["password_hash"] and not user["disabled"]:
            if verify_password(password, user["password_hash"]):
                self.store.touch_login(user["id"])  # type: ignore[union-attr]
                return Identity(user["username"], user["name"], user["role"], "local", user["id"])
        elif not user:
            verify_password(password, DUMMY_HASH)  # a missing user must not be faster than a wrong password
        self._fails[ip].append(time.time())
        return None

    def identity_for(self, username: str, provider: str) -> Identity | None:
        """The live identity behind a session: roles and disabling apply at once, without a new login."""
        if provider == "config":
            return Identity(self.username, self.username, "admin", "config") if username == self.username else None
        user = self.store.get_user_by_name(username) if self.store else None
        if not user or user["disabled"] or user["provider"] != provider:
            return None
        return Identity(user["username"], user["name"], user["role"], provider, user["id"])

    def identity_from_bearer(self, token: str) -> Identity | None:
        """An API token (`nig_...`, created by an admin), or a signed session value used as a bearer."""
        if token.startswith(TOKEN_PREFIX):
            if self.store is None:
                return None
            row = self.store.find_api_token(hash_token(token))
            now = time.time()
            if not row or (row["expires_at"] and row["expires_at"] < now):
                return None
            if not row["last_used"] or now - row["last_used"] > 60:
                self.store.touch_api_token(row["id"], now)
            return Identity(f"token:{row['name']}", row["name"], row["role"], "token")
        data = self.read_blob(token)
        if not data or "u" not in data:
            return None
        return self.identity_for(data["u"], data.get("p", "config"))

    def identity_from(self, request: Request) -> Identity | None:
        if not self.enabled:
            return Identity("anonymous", "anonymous", "admin", "config")
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            return self.identity_from_bearer(header[7:].strip())
        token = request.cookies.get(COOKIE)
        data = self.read_blob(token)
        if not data or "u" not in data:
            return None
        return self.identity_for(data["u"], data.get("p", "config"))  # sessions from before roles were the admin

    def user_from(self, request: Request) -> str | None:
        who = self.identity_from(request)
        return who.username if who else None


def make_authorizer(auth: Auth):
    def authorize(request: Request) -> Identity:
        who = auth.identity_from(request)
        if not who:
            raise HTTPException(status_code=401, detail="not authenticated")
        request.state.identity = who
        # CSRF defence for cookie auth: state-changing calls must carry a custom header
        if request.method not in ("GET", "HEAD", "OPTIONS") and auth.enabled:
            if request.headers.get("x-requested-with") != "nigrani" and not request.headers.get("authorization"):
                raise HTTPException(status_code=403, detail="missing X-Requested-With header")
        need = required_role(request.method, request.url.path, dict(request.query_params))
        if not who.can(need):
            raise HTTPException(status_code=403, detail=f"this needs the {need} role (you are {who.role})")
        return who

    return authorize
