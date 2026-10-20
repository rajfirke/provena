from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


def _make_backend_with_mock_pool():
    """Create a PostgreSQLBackend with a fully mocked connection pool,
    so no real database or psycopg install is needed."""
    from provena.storage_pg import PostgreSQLBackend

    backend = PostgreSQLBackend.__new__(PostgreSQLBackend)
    backend._hasher = None

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None  # simulate the "no row" case
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.__exit__.return_value = False

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = False

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn

    backend._pool = mock_pool
    return backend


def test_append_raises_runtime_error_when_no_row_returned():
    backend = _make_backend_with_mock_pool()
    record = {
        "content_hash": "abc",
        "source": "retriever",
        "source_name": "test",
        "timestamp": "2026-01-01T00:00:00Z",
        "chain_hash": "chainhash",
        "previous_hash": "prevhash",
    }
    with pytest.raises(RuntimeError, match="INSERT did not return an id"):
        backend.append(record)


def test_count_raises_runtime_error_when_no_row_returned():
    backend = _make_backend_with_mock_pool()
    with pytest.raises(RuntimeError, match="did not return a row"):
        backend.count()


def test_add_annotation_raises_runtime_error_when_no_row_returned():
    backend = _make_backend_with_mock_pool()
    with pytest.raises(RuntimeError, match="INSERT did not return an id"):
        backend.add_annotation(1, "note", "reviewer", "2026-01-01T00:00:00Z")


def test_row_to_dict_converts_aware_timestamp_to_utc():
    # The chain hash covers the timestamp string, and ContextTrail hashes the
    # +00:00 form produced by datetime.now(timezone.utc).isoformat(). psycopg
    # renders timestamptz in the session TimeZone, so a non-UTC offset here
    # hashes differently and reports an untouched trail as broken.
    from provena.storage_pg import _row_to_dict

    cursor = MagicMock()
    cursor.description = [("id",), ("timestamp",)]
    eastern = timezone(timedelta(hours=-5))
    row = (1, datetime(2026, 1, 1, 9, 30, tzinfo=eastern))

    d = _row_to_dict(cursor, row)

    assert d["timestamp"] == "2026-01-01T14:30:00+00:00"


def test_row_to_dict_leaves_naive_timestamp_alone():
    # timestamptz always reads back aware, so the naive branch is defensive.
    # It must not invent a zone for a value whose offset is unknown.
    from provena.storage_pg import _row_to_dict

    cursor = MagicMock()
    cursor.description = [("id",), ("timestamp",)]
    row = (1, datetime(2026, 1, 1, 9, 30))

    d = _row_to_dict(cursor, row)

    assert d["timestamp"] == "2026-01-01T09:30:00"
