from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

from provena.storage import SQLiteBackend


def _make_record(**overrides):
    base = {
        "content_hash": "abc123",
        "source": "retriever",
        "source_name": "test_retriever",
        "timestamp": "2026-07-13T00:00:00+00:00",
        "provenance_json": None,
        "provenance_status": "MISSING",
        "missing_fields": "source_url,created_at",
        "chain_hash": "chain_abc",
        "previous_hash": "prev_abc",
        "config_hash": "",
        "metadata_json": "{}",
        "content_type": "str",
        "truncated": False,
    }
    base.update(overrides)
    return base


class TestInMemoryBackend:
    def test_append_and_get(self, memory_backend):
        record_id = memory_backend.append(_make_record())
        assert record_id == 1

        stored = memory_backend.get(record_id)
        assert stored is not None
        assert stored["content_hash"] == "abc123"

    def test_get_nonexistent(self, memory_backend):
        assert memory_backend.get(999) is None

    def test_get_last_empty(self, memory_backend):
        assert memory_backend.get_last() is None

    def test_get_last(self, memory_backend):
        memory_backend.append(_make_record(chain_hash="first"))
        memory_backend.append(_make_record(chain_hash="second"))
        last = memory_backend.get_last()
        assert last is not None
        assert last["chain_hash"] == "second"

    def test_count(self, memory_backend):
        assert memory_backend.count() == 0
        memory_backend.append(_make_record())
        assert memory_backend.count() == 1
        memory_backend.append(_make_record())
        assert memory_backend.count() == 2

    def test_all_records(self, memory_backend):
        memory_backend.append(_make_record(content_hash="h1"))
        memory_backend.append(_make_record(content_hash="h2"))
        records = memory_backend.all_records()
        assert len(records) == 2
        assert records[0]["content_hash"] == "h1"
        assert records[1]["content_hash"] == "h2"

    def test_query_by_source(self, memory_backend):
        memory_backend.append(_make_record(source="retriever"))
        memory_backend.append(_make_record(source="tool"))
        memory_backend.append(_make_record(source="retriever"))

        results = memory_backend.query(source="retriever")
        assert len(results) == 2

        results = memory_backend.query(source="tool")
        assert len(results) == 1

    def test_query_by_time_range(self, memory_backend):
        memory_backend.append(_make_record(timestamp="2026-07-01T00:00:00+00:00"))
        memory_backend.append(_make_record(timestamp="2026-07-10T00:00:00+00:00"))
        memory_backend.append(_make_record(timestamp="2026-07-20T00:00:00+00:00"))

        start = datetime(2026, 7, 5, tzinfo=timezone.utc)
        end = datetime(2026, 7, 15, tzinfo=timezone.utc)
        results = memory_backend.query(start=start, end=end)
        assert len(results) == 1

    def test_query_limit(self, memory_backend):
        for i in range(10):
            memory_backend.append(_make_record(content_hash=f"h{i}"))
        results = memory_backend.query(limit=3)
        assert len(results) == 3

    def test_add_annotation(self, memory_backend):
        memory_backend.append(_make_record())
        ann_id = memory_backend.add_annotation(
            record_id=1,
            note="Reviewed",
            reviewer="alice",
            timestamp="2026-07-13T00:00:00",
        )
        assert ann_id == 1

    def test_sequential_ids(self, memory_backend):
        id1 = memory_backend.append(_make_record())
        id2 = memory_backend.append(_make_record())
        id3 = memory_backend.append(_make_record())
        assert id1 == 1
        assert id2 == 2
        assert id3 == 3


class TestSQLiteBackend:
    def test_append_and_get(self, sqlite_backend):
        record_id = sqlite_backend.append(_make_record())
        assert record_id == 1

        stored = sqlite_backend.get(record_id)
        assert stored is not None
        assert stored["content_hash"] == "abc123"

    def test_get_nonexistent(self, sqlite_backend):
        assert sqlite_backend.get(999) is None

    def test_get_last(self, sqlite_backend):
        sqlite_backend.append(_make_record(chain_hash="first"))
        sqlite_backend.append(_make_record(chain_hash="second"))
        last = sqlite_backend.get_last()
        assert last is not None
        assert last["chain_hash"] == "second"

    def test_count(self, sqlite_backend):
        assert sqlite_backend.count() == 0
        sqlite_backend.append(_make_record())
        assert sqlite_backend.count() == 1

    def test_all_records_ordered(self, sqlite_backend):
        sqlite_backend.append(_make_record(content_hash="h1"))
        sqlite_backend.append(_make_record(content_hash="h2"))
        sqlite_backend.append(_make_record(content_hash="h3"))
        records = sqlite_backend.all_records()
        assert [r["content_hash"] for r in records] == ["h1", "h2", "h3"]

    def test_query_by_source(self, sqlite_backend):
        sqlite_backend.append(_make_record(source="retriever"))
        sqlite_backend.append(_make_record(source="tool"))
        results = sqlite_backend.query(source="retriever")
        assert len(results) == 1
        assert results[0]["source"] == "retriever"

    def test_persistence(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            backend1 = SQLiteBackend(path=db_path)
            backend1.append(_make_record(content_hash="persistent"))
            backend1.close()

            backend2 = SQLiteBackend(path=db_path)
            assert backend2.count() == 1
            stored = backend2.get(1)
            assert stored is not None
            assert stored["content_hash"] == "persistent"
            backend2.close()
        finally:
            os.unlink(db_path)

    def test_schema_version(self, sqlite_backend):
        import sqlite3

        conn = sqlite3.connect(sqlite_backend._path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert version == 2

    def test_wal_mode(self, sqlite_backend):
        import sqlite3

        conn = sqlite3.connect(sqlite_backend._path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_add_annotation(self, sqlite_backend):
        sqlite_backend.append(_make_record())
        ann_id = sqlite_backend.add_annotation(
            record_id=1, note="Checked", reviewer="bob", timestamp="2026-07-13"
        )
        assert ann_id >= 1
