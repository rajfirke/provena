"""Tests for the PostgreSQL storage backend.

All tests are skipped when psycopg is not installed or PROVENA_TEST_PG_URL
is not set. To run these tests locally:

    export PROVENA_TEST_PG_URL="postgresql://localhost:5432/provena_test"
    pip install provena[postgres]
    pytest tests/test_storage_pg.py -v
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

_pg_conninfo = os.environ.get("PROVENA_TEST_PG_URL", "")

try:
    import psycopg  # noqa: F401

    _pg_importable = True
except ImportError:
    _pg_importable = False

pytestmark = pytest.mark.skipif(
    not (_pg_importable and _pg_conninfo),
    reason="PostgreSQL not available (set PROVENA_TEST_PG_URL and install psycopg)",
)


@pytest.fixture
def pg_backend():
    from provena.storage_pg import PostgreSQLBackend

    backend = PostgreSQLBackend(conninfo=_pg_conninfo, pool_size=2)
    with backend._pool.connection() as conn:
        conn.execute("TRUNCATE trail, annotations RESTART IDENTITY CASCADE")
        conn.commit()
    yield backend
    if backend._pool is not None:
        with backend._pool.connection() as conn:
            conn.execute("TRUNCATE trail, annotations RESTART IDENTITY CASCADE")
            conn.commit()
        backend.close()


def _make_record(**overrides):
    defaults = {
        "content_hash": "abc123",
        "source": "retriever",
        "source_name": "test",
        "timestamp": "2026-07-18T12:00:00+00:00",
        "provenance_json": None,
        "provenance_status": "MISSING",
        "missing_fields": "source_url,created_at",
        "freshness_status": "UNKNOWN",
        "chain_hash": "chainhash1",
        "previous_hash": "prevhash0",
        "config_hash": "",
        "metadata_json": "{}",
        "content_type": "str",
        "truncated": 0,
    }
    defaults.update(overrides)
    return defaults


def _advisory_lock_keys(backend, pid: int) -> list[int | tuple[int, int]]:
    """Read the advisory locks held by ``pid`` as normalized keys."""
    with backend._pool.connection() as conn:
        rows = conn.execute(
            "SELECT classid::bigint, objid::bigint, objsubid "
            "FROM pg_locks WHERE locktype = 'advisory' AND pid = %s",
            (pid,),
        ).fetchall()

    keys: list[int | tuple[int, int]] = []
    for classid, objid, objsubid in rows:
        if objsubid == 1:
            key = (int(classid) << 32) | int(objid)
            if key >= 1 << 63:
                key -= 1 << 64
            keys.append(key)
        else:
            keys.append((int(classid), int(objid)))
    return keys


class TestPostgreSQLBackendCRUD:
    def test_append_and_get(self, pg_backend):
        record = _make_record()
        record_id = pg_backend.append(record)
        assert record_id == 1
        fetched = pg_backend.get(record_id)
        assert fetched is not None
        assert fetched["content_hash"] == "abc123"
        assert fetched["source"] == "retriever"
        assert fetched["content_hash_version"] == 1

    def test_append_preserves_content_hash_version(self, pg_backend):
        pg_backend.append(_make_record(content_hash_version=2))
        fetched = pg_backend.get(1)
        assert fetched is not None
        assert fetched["content_hash_version"] == 2

    def test_get_nonexistent(self, pg_backend):
        assert pg_backend.get(9999) is None

    def test_get_last(self, pg_backend):
        pg_backend.append(_make_record(content_hash="first"))
        pg_backend.append(_make_record(content_hash="second"))
        last = pg_backend.get_last()
        assert last is not None
        assert last["content_hash"] == "second"

    def test_get_last_empty(self, pg_backend):
        assert pg_backend.get_last() is None

    def test_count(self, pg_backend):
        assert pg_backend.count() == 0
        pg_backend.append(_make_record())
        pg_backend.append(_make_record(content_hash="second"))
        assert pg_backend.count() == 2

    def test_all_records_ordered(self, pg_backend):
        pg_backend.append(_make_record(content_hash="a"))
        pg_backend.append(_make_record(content_hash="b"))
        pg_backend.append(_make_record(content_hash="c"))
        records = pg_backend.all_records()
        assert len(records) == 3
        assert records[0]["content_hash"] == "a"
        assert records[2]["content_hash"] == "c"

    def test_truncated_normalized_to_int(self, pg_backend):
        pg_backend.append(_make_record(truncated=True))
        record = pg_backend.get(1)
        assert record["truncated"] == 1


class TestPostgreSQLBackendQuery:
    def test_query_by_source(self, pg_backend):
        pg_backend.append(_make_record(source="retriever"))
        pg_backend.append(_make_record(source="tool"))
        results = pg_backend.query(source="retriever")
        assert len(results) == 1
        assert results[0]["source"] == "retriever"

    def test_query_by_provenance_status(self, pg_backend):
        pg_backend.append(_make_record(provenance_status="VALID"))
        pg_backend.append(_make_record(provenance_status="MISSING"))
        results = pg_backend.query(provenance_status="VALID")
        assert len(results) == 1

    def test_query_limit(self, pg_backend):
        for i in range(10):
            pg_backend.append(_make_record(content_hash=f"hash{i}"))
        results = pg_backend.query(limit=3)
        assert len(results) == 3


class TestPostgreSQLBackendAnnotations:
    @pytest.mark.parametrize("has_existing_record", [False, True])
    def test_add_annotation_nonexistent_record_raises_value_error(
        self, pg_backend, has_existing_record
    ):
        if has_existing_record:
            pg_backend.append(_make_record())

        with pytest.raises(ValueError, match=r"^Record 9999 does not exist$"):
            pg_backend.add_annotation(
                9999, "orphan", "reviewer", "2026-07-18T12:00:00Z"
            )

        with pg_backend._pool.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 0

    def test_add_and_get_annotations(self, pg_backend):
        pg_backend.append(_make_record())
        ann_id = pg_backend.add_annotation(
            1, "reviewed", "admin", "2026-07-18T12:00:00Z"
        )
        assert ann_id == 1
        anns = pg_backend.get_annotations(1)
        assert len(anns) == 1
        assert anns[0]["note"] == "reviewed"
        assert anns[0]["reviewer"] == "admin"

    def test_get_annotations_empty(self, pg_backend):
        pg_backend.append(_make_record())
        assert pg_backend.get_annotations(1) == []

    def test_multiple_annotations_ordered(self, pg_backend):
        pg_backend.append(_make_record())
        pg_backend.add_annotation(1, "first", "a", "2026-07-18T12:00:00Z")
        pg_backend.add_annotation(1, "second", "b", "2026-07-18T12:01:00Z")
        anns = pg_backend.get_annotations(1)
        assert len(anns) == 2
        assert anns[0]["note"] == "first"
        assert anns[1]["note"] == "second"


class TestPostgreSQLBackendSchema:
    def test_schema_idempotent(self, pg_backend):
        from provena.storage_pg import PostgreSQLBackend

        backend2 = PostgreSQLBackend(conninfo=_pg_conninfo, pool_size=1)
        backend2.append(_make_record())
        assert backend2.count() >= 1
        backend2.close()

    def test_close_and_reopen(self, pg_backend):
        pg_backend.append(_make_record())
        pg_backend.close()

        from provena.storage_pg import PostgreSQLBackend

        backend2 = PostgreSQLBackend(conninfo=_pg_conninfo, pool_size=1)
        assert backend2.count() == 1
        with backend2._pool.connection() as conn:
            conn.execute("TRUNCATE trail, annotations RESTART IDENTITY CASCADE")
            conn.commit()
        backend2.close()


class TestPostgreSQLAdvisoryLocks:
    def test_default_lock_key_is_one(self, pg_backend):
        with pg_backend._pool.connection() as lock_conn:
            pid = lock_conn.execute("SELECT pg_backend_pid()").fetchone()[0]
            sql, params = pg_backend._advisory_lock_sql()
            assert sql == "SELECT pg_advisory_xact_lock(%s)"
            assert params == (1,)

            lock_conn.execute(sql, params)
            assert _advisory_lock_keys(pg_backend, pid) == [1]

    def test_default_lock_key_serializes_with_pre_248_writers(self, pg_backend):
        import psycopg

        with psycopg.connect(_pg_conninfo) as lock_conn:
            lock_conn.execute("SELECT pg_advisory_xact_lock(1)")

            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                pg_backend.append, _make_record(content_hash="serialized")
            )
            try:
                time.sleep(0.5)
                assert not future.done()

                lock_conn.rollback()
                record_id = future.result(timeout=5)
            finally:
                executor.shutdown(wait=True, cancel_futures=True)

            assert record_id >= 1
            assert pg_backend.count() == 1

    def test_explicit_int_lock_key_is_used(self, pg_backend):
        from provena.storage_pg import PostgreSQLBackend

        backend = PostgreSQLBackend(
            conninfo=_pg_conninfo, pool_size=2, advisory_lock_key=424242
        )
        try:
            with backend._pool.connection() as lock_conn:
                pid = lock_conn.execute("SELECT pg_backend_pid()").fetchone()[0]
                sql, params = backend._advisory_lock_sql()
                assert params == (424242,)

                lock_conn.execute(sql, params)
                assert _advisory_lock_keys(backend, pid) == [424242]
        finally:
            backend.close()

    def test_explicit_pair_lock_key_is_used(self, pg_backend):
        from provena.storage_pg import PostgreSQLBackend

        backend = PostgreSQLBackend(
            conninfo=_pg_conninfo, pool_size=2, advisory_lock_key=(123, 456)
        )
        try:
            with backend._pool.connection() as lock_conn:
                pid = lock_conn.execute("SELECT pg_backend_pid()").fetchone()[0]
                sql, params = backend._advisory_lock_sql()
                assert params == (123, 456)
                assert "%s, %s" in sql

                lock_conn.execute(sql, params)
                assert _advisory_lock_keys(backend, pid) == [(123, 456)]
        finally:
            backend.close()

    def test_distinct_lock_keys_append_without_serializing(self, pg_backend):
        from provena.storage_pg import PostgreSQLBackend

        backend_a = PostgreSQLBackend(
            conninfo=_pg_conninfo, pool_size=1, advisory_lock_key=111111
        )
        backend_b = PostgreSQLBackend(
            conninfo=_pg_conninfo, pool_size=1, advisory_lock_key=222222
        )
        try:
            with backend_a._pool.connection() as lock_conn:
                lock_conn.execute("SELECT pg_advisory_xact_lock(%s)", (111111,))

                executor = ThreadPoolExecutor(max_workers=1)
                future = executor.submit(
                    backend_b.append, _make_record(content_hash="concurrent")
                )
                try:
                    record_id = future.result(timeout=5)
                finally:
                    # Release the lock so a serializing append cannot hang teardown.
                    lock_conn.rollback()
                    executor.shutdown(wait=True, cancel_futures=True)

            assert record_id >= 1
            assert backend_b.count() == 1
        finally:
            backend_a.close()
            backend_b.close()

    @pytest.mark.parametrize(
        "key",
        [
            True,
            1.5,
            "lock",
            (1,),
            (1, 2, 3),
            (1, "2"),
            (2**31, 0),
            2**63,
        ],
    )
    def test_invalid_lock_key_rejected(self, key):
        from provena.storage_pg import PostgreSQLBackend

        with pytest.raises(ValueError, match="advisory_lock_key"):
            PostgreSQLBackend(conninfo=_pg_conninfo, advisory_lock_key=key)


class TestPostgreSQLAdvisoryLockConfig:
    def test_context_trail_direct_key(self, pg_backend):
        from provena.trail import ContextTrail

        trail = ContextTrail(
            storage_path=_pg_conninfo,
            backend="postgresql",
            advisory_lock_key=777,
        )
        try:
            assert trail._backend._advisory_lock_key == 777
        finally:
            trail.close()

    def test_context_trail_config_key(self, pg_backend):
        from provena.trail import ContextTrail

        trail = ContextTrail(
            config={
                "storage": {
                    "backend": "postgresql",
                    "path": _pg_conninfo,
                    "advisory_lock_key": [12, 34],
                }
            }
        )
        try:
            assert trail._backend._advisory_lock_key == (12, 34)
        finally:
            trail.close()


class TestPostgreSQLImportError:
    @pytest.mark.skipif(_pg_importable, reason="psycopg IS installed")
    def test_import_error_message(self):
        from provena.storage_pg import PostgreSQLBackend

        with pytest.raises(ImportError, match="psycopg"):
            PostgreSQLBackend(conninfo="postgresql://localhost/test")


class TestPostgreSQLTipRepairReceipt:
    def test_returned_record_matches_stored_row_after_tip_repair(self, pg_backend):
        # Regression for #231. PostgreSQLBackend.append holds an advisory lock
        # and, when the submitted previous_hash is no longer the tip, recomputes
        # both hashes and stores the repaired pair. Those values used to stay
        # local to append(), so the TrailRecord handed back to the caller
        # described a link that is not in the row. The value log() returns is
        # the tamper-evident receipt, so a reviewer recomputing from it has to
        # land on what the database holds.
        from provena import ContextTrail

        writer_a = ContextTrail(storage_path=_pg_conninfo)
        writer_b = ContextTrail(storage_path=_pg_conninfo)
        try:
            writer_a.log("from writer A", source="retriever")

            # writer_b still holds the tip it read when it was constructed, so
            # this insert goes through the repair branch.
            record = writer_b.log("from writer B", source="retriever")
            stored = writer_b._backend.get(record.id)

            assert stored is not None
            assert record.chain_hash == stored["chain_hash"]
            assert record.previous_hash == stored["previous_hash"]

            # The writer that lost the race must not keep submitting the stale
            # tip on its next call.
            follow_up = writer_b.log("second from writer B", source="retriever")
            stored_follow_up = writer_b._backend.get(follow_up.id)

            assert stored_follow_up is not None
            assert follow_up.chain_hash == stored_follow_up["chain_hash"]
            assert follow_up.previous_hash == stored_follow_up["previous_hash"]
            assert writer_b.verify_chain().intact
        finally:
            writer_a.close()
            writer_b.close()


class TestPostgreSQLTimeZone:
    def test_verify_chain_intact_when_database_timezone_is_not_utc(self, pg_backend):
        # Regression for #230. The chain hash covers the timestamp string, and
        # psycopg renders timestamptz in the session TimeZone. Under a non-UTC
        # database default the readback offset changed, so verify_chain()
        # reported a break on a trail nobody had edited. The CI Postgres
        # service runs UTC, so the zone is forced here rather than relying on
        # whatever the host happens to be set to.
        import psycopg

        from provena import ContextTrail

        with psycopg.connect(_pg_conninfo) as conn:
            dbname = conn.execute("SELECT current_database()").fetchone()[0]

        with psycopg.connect(_pg_conninfo) as conn:
            conn.execute(
                f"ALTER DATABASE \"{dbname}\" SET TimeZone TO 'America/New_York'"
            )
            conn.commit()

        try:
            trail = ContextTrail(storage_path=_pg_conninfo)
            try:
                record = trail.log("logged under a non-UTC default", source="retriever")
                stored = trail.query(limit=1)[0]

                assert stored["timestamp"] == record.entry.timestamp.isoformat()
                assert stored["timestamp"].endswith("+00:00")
                assert trail.verify_chain().intact
            finally:
                trail.close()
        finally:
            with psycopg.connect(_pg_conninfo) as conn:
                conn.execute(f'ALTER DATABASE "{dbname}" RESET TimeZone')
                conn.commit()

    def test_dsn_options_survive_the_pool_configuration(self, pg_backend):
        # An earlier revision pinned UTC with kwargs={"options": "-c timezone=UTC"},
        # which replaces any options the caller set in their DSN: a connection
        # string carrying statement_timeout lost it silently. UTC is applied with
        # a configure callback instead, so both settings have to survive.
        from provena.storage_pg import PostgreSQLBackend

        separator = "&" if "?" in _pg_conninfo else "?"
        conninfo = f"{_pg_conninfo}{separator}options=-c%20statement_timeout%3D5000"

        backend = PostgreSQLBackend(conninfo=conninfo, pool_size=2)
        try:
            with backend._pool.connection() as conn:
                timeout = conn.execute("SHOW statement_timeout").fetchone()[0]
                tz = conn.execute("SHOW timezone").fetchone()[0]

            assert timeout == "5s"
            assert tz == "UTC"
        finally:
            backend.close()


def test_pg_query_order_desc_returns_newest_first(pg_backend):
    """PostgreSQLBackend.query(order='desc') returns newest records first."""
    for i in range(5):
        pg_backend.append(_make_record(source_name=f"item-{i}"))
    asc = pg_backend.query(limit=3)
    desc = pg_backend.query(limit=3, order="desc")
    assert [r["source_name"] for r in asc] == ["item-0", "item-1", "item-2"]
    assert [r["source_name"] for r in desc] == ["item-4", "item-3", "item-2"]
