import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from nigrani.config import Config, load_config
from nigrani.store import Store


class FakeProm:
    """Prometheus stand-in: `values[expr]` -> list of (labels, value)."""

    def __init__(self):
        self.values: dict[str, list[tuple[dict, float | None]]] = {}
        self.up = True
        self.last_error = None
        self.metrics: set[str] = set()

    async def instant(self, q, at=None):
        from nigrani.prom import PromUnavailable
        if not self.up:
            raise PromUnavailable("down")
        return [{"labels": l, "value": v} for l, v in self.values.get(q, [])]

    async def range(self, q, start, end, step):
        from nigrani.prom import PromUnavailable
        if not self.up:
            raise PromUnavailable("down")
        n = 5
        return [{"labels": l, "points": [[start + i * (end - start) / n, v] for i in range(n)]}
                for l, v in self.values.get(q, [])]

    async def metric_names(self):
        from nigrani.prom import PromUnavailable
        if not self.up:
            raise PromUnavailable("down")
        return sorted(self.metrics)

    async def has_metric(self, name):
        return name in self.metrics

    async def healthy(self):
        return self.up

    async def close(self):
        pass


class RecordingNotifier:
    def __init__(self):
        self.events = []

    async def send(self, ev, *, only=None, now=None):
        self.events.append(ev)

    @property
    def kinds(self):
        return [e["kind"] for e in self.events]


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = load_config(None)
    c.data_dir = str(tmp_path)
    c.auth.password = "pw"
    return c


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


@pytest.fixture
def prom() -> FakeProm:
    return FakeProm()
