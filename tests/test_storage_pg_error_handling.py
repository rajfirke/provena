from __future__ import annotations

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
