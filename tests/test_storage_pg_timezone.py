"""The chain hash must survive a database session in a non-UTC TimeZone.

`verify_chain()` recomputes each link from the timestamp string; the trail was
hashed with its `+00:00` offset (issue #230). Two guards keep the string
stable: every pooled connection forces `timezone=UTC`, and `_row_to_dict()`
normalizes an aware timestamp to UTC before `isoformat()`. These tests need no
psycopg and no database.
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from provena.storage_pg import PostgreSQLBackend, _row_to_dict


class _FakeCursor:
    def __init__(self) -> None:
        self.description = [("timestamp",), ("content_hash",)]

    def execute(self, *args, **kwargs) -> None:  # pragma: no cover - schema no-ops
        pass

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args) -> bool:
        return False


class _FakeConn:
    def cursor(self) -> _FakeCursor:
        return _FakeCursor()

    def commit(self) -> None:
        pass

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *args) -> bool:
        return False


class _FakePool:
    """Records the kwargs ConnectionPool was constructed with."""

    init_kwargs: dict | None = None

    def __init__(self, conninfo: str, **kwargs) -> None:
        _FakePool.init_kwargs = kwargs

    @contextmanager
    def connection(self):
        yield _FakeConn()

    def close(self) -> None:
        pass


def test_row_to_dict_normalizes_a_non_utc_aware_timestamp_to_utc():
    # The same instant, read back in an Asia/Kolkata session.
    ts = datetime(2026, 10, 20, 19, 30, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    d = _row_to_dict(_FakeCursor(), (ts, "abc"))

    assert d["timestamp"] == "2026-10-20T14:00:00+00:00"


def test_row_to_dict_keeps_a_utc_timestamp_in_hashed_form():
    ts = datetime(2026, 10, 20, 14, 3, 1, 123456, tzinfo=timezone.utc)
    d = _row_to_dict(_FakeCursor(), (ts, "abc"))

    assert d["timestamp"] == "2026-10-20T14:03:01.123456+00:00"


def test_row_to_dict_leaves_string_timestamps_alone():
    d = _row_to_dict(_FakeCursor(), ("2026-10-20T14:03:01+00:00", "abc"))

    assert d["timestamp"] == "2026-10-20T14:03:01+00:00"


def test_pool_forces_utc_on_every_pooled_connection(monkeypatch):
    fake_module = types.ModuleType("psycopg_pool")
    fake_module.ConnectionPool = _FakePool
    monkeypatch.setitem(sys.modules, "psycopg_pool", fake_module)

    PostgreSQLBackend("dbname=whatever")  # pool is faked; schema is a no-op

    assert _FakePool.init_kwargs is not None
    assert _FakePool.init_kwargs["kwargs"]["options"] == "-c timezone=UTC"
