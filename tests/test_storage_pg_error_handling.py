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
    # The existence check sees the trail row; the INSERT itself returns nothing.
    backend._pool.connection.return_value.cursor.return_value.fetchone.side_effect = [
        (1,),
        None,
    ]
    with pytest.raises(RuntimeError, match="INSERT did not return an id"):
        backend.add_annotation(1, "note", "reviewer", "2026-01-01T00:00:00Z")


def test_add_annotation_raises_value_error_when_record_missing():
    # The trail row does not exist: the same ValueError the in-memory and
    # SQLite backends raise, not a PostgreSQL foreign-key error (#229).
    backend = _make_backend_with_mock_pool()
    with pytest.raises(ValueError, match="Record 1 does not exist"):
        backend.add_annotation(1, "note", "reviewer", "2026-01-01T00:00:00Z")


def test_add_annotation_returns_id_when_record_exists():
    backend = _make_backend_with_mock_pool()
    mock_cursor = backend._pool.connection.return_value.cursor.return_value
    mock_cursor.fetchone.side_effect = [(1,), (42,)]

    ann_id = backend.add_annotation(1, "note", "reviewer", "2026-01-01T00:00:00Z")

    assert ann_id == 42
    insert_calls = [
        call for call in mock_cursor.execute.call_args_list if "INSERT INTO annotations" in call.args[0]
    ]
    assert len(insert_calls) == 1
    assert insert_calls[0].args[1] == (1, "note", "reviewer", "2026-01-01T00:00:00Z")
