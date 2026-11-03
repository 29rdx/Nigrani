"""Request/storage shapes shared by the REST API and backup import, so both validate the same way."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class RuleIn(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    expr: str = Field(min_length=1, max_length=2000)
    direction: Literal["above", "below"] = "above"
    warn: float | None = None
    crit: float | None = None
    for_seconds: int = Field(300, ge=0, le=86400)
    unit: str = "short"
    summary: str = ""
    enabled: bool = True
    servers: list[str] = []
    datasource: Literal["prometheus", "loki", "sentry", "cloudwatch", "kubernetes", "datadog", "azure", "argocd"] = "prometheus"

    @field_validator("id")
    @classmethod
    def _id(cls, v: str | None) -> str | None:
        if v is not None and not ID_RE.match(v):
            raise ValueError("id must be lowercase letters, digits, - or _")
        return v


USERNAME_RE = re.compile(r"^[A-Za-z0-9._@+-]{3,64}$")


class UserIn(BaseModel):
    username: str
    name: str = Field("", max_length=100)
    email: str | None = Field(None, max_length=200)
    role: Literal["viewer", "editor", "admin"] = "viewer"
    password: str

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        if not USERNAME_RE.match(v):
            raise ValueError("username: 3-64 letters, digits or . _ @ + -")
        return v


class UserPatch(BaseModel):
    name: str | None = Field(None, max_length=100)
    email: str | None = Field(None, max_length=200)
    role: Literal["viewer", "editor", "admin"] | None = None
    disabled: bool | None = None
    password: str | None = None


def rule_problem(r: "RuleIn") -> str | None:
    """Thresholds must make sense; returns a message or None."""
    if r.warn is not None and r.crit is not None:
        if (r.direction == "above" and r.warn > r.crit) or (r.direction == "below" and r.warn < r.crit):
            return "warning threshold must be less severe than critical"
    if r.warn is None and r.crit is None:
        return "set at least one of warn / crit"
    return None


class ChannelIn(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=80)
    type: Literal["slack", "teams", "discord", "telegram", "email", "webhook", "whatsapp"]
    settings: dict[str, Any] = {}
    min_severity: Literal["info", "warning", "critical"] = "warning"
    quiet_start: int | None = Field(None, ge=0, le=23)
    quiet_end: int | None = Field(None, ge=0, le=23)
    enabled: bool = True
    servers: list[str] = []
    title_template: str | None = None
    body_template: str | None = None
