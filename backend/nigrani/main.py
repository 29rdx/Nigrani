"""ASGI entrypoint: `uvicorn nigrani.main:app`."""
from __future__ import annotations

import logging
import os

from .api import create_app
from .config import Config, load_config


def apply_env_overrides(cfg: Config) -> Config:
    """Let a bare `docker run -e ...` work without a config file."""
    env = os.environ
    if env.get("NIGRANI_PASSWORD") and not cfg.auth.password:
        cfg.auth.password = env["NIGRANI_PASSWORD"]
    if env.get("NIGRANI_USERNAME"):
        cfg.auth.username = env["NIGRANI_USERNAME"]
    if env.get("NIGRANI_PROMETHEUS_URL"):
        cfg.datasources.prometheus = env["NIGRANI_PROMETHEUS_URL"]
    if env.get("NIGRANI_LOKI_URL"):
        cfg.datasources.loki = env["NIGRANI_LOKI_URL"]
    if env.get("NIGRANI_DATA_DIR"):
        cfg.data_dir = env["NIGRANI_DATA_DIR"]
    return cfg


def build() -> "object":
    logging.basicConfig(level=os.environ.get("NIGRANI_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per PromQL query is too noisy
    path = os.environ.get("NIGRANI_CONFIG", "/config/nigrani.yaml")
    demo = os.environ.get("NIGRANI_DEMO", "").lower() in ("1", "true", "yes")
    cfg = apply_env_overrides(load_config(path, explicit="NIGRANI_CONFIG" in os.environ, demo=demo))
    return create_app(cfg)


app = build()
