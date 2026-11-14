"""Tests for the retention policy engine."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from provena import ContextTrail
from provena.retention import EU_AI_ACT_MINIMUM_DAYS, RetentionEngine

_pg_conninfo = os.environ.get("PROVENA_TEST_PG_URL", "")
try:
    import psycopg  # noqa: F401

    _pg_importable = True
except ImportError:
    _pg_importable = False


def _capture_retention_log_content(trail, monkeypatch):
    original_log = trail.log
    captured = []

    def capture(content, source, source_name="", **kwargs):
        if source_name == "provena:retention":
            captured.append(content)
        return original_log(content, source, source_name, **kwargs)

    monkeypatch.setattr(trail, "log", capture)
    return captured


@pytest.fixture
def trail_with_old_records():
    trail = ContextTrail(backend="memory")
    now = datetime.now(timezone.utc)
    for i in range(5):
        trail.log(
            f"old record {i}",
            source="retriever",
            metadata={"age": "old"},
        )
    for record in trail._backend._records:
        record["timestamp"] = (now - timedelta(days=400)).isoformat()

    for i in range(3):
        trail.log(f"recent record {i}", source="tool")

    yield trail
    trail.close()


class TestRetentionEngineConfig:
    def test_default_retention(self, memory_trail):
        engine = RetentionEngine(memory_trail)
        assert engine.retention_days == 365
        assert engine.min_retention_days == EU_AI_ACT_MINIMUM_DAYS

    def test_custom_retention(self, memory_trail):
        engine = RetentionEngine(memory_trail, retention_days=270)
        assert engine.retention_days == 270

    def test_below_minimum_raises(self, memory_trail):
        with pytest.raises(ValueError, match="EU AI Act"):
            RetentionEngine(memory_trail, retention_days=90)

    def test_exactly_minimum(self, memory_trail):
        engine = RetentionEngine(memory_trail, retention_days=180)
        assert engine.retention_days == 180


class TestRetentionPreview:
    def test_preview_with_expired(self, trail_with_old_records):
        engine = RetentionEngine(trail_with_old_records, retention_days=180)
        preview = engine.preview()
        assert preview["would_delete"] == 5
        assert preview["retention_days"] == 180

    def test_preview_nothing_expired(self, memory_trail):
        memory_trail.log("fresh", source="retriever")
        engine = RetentionEngine(memory_trail, retention_days=365)
        preview = engine.preview()
        assert preview["would_delete"] == 0


class TestRetentionExecution:
    def test_dry_run(self, trail_with_old_records):
        engine = RetentionEngine(trail_with_old_records, retention_days=180)
        result = engine.execute(dry_run=True)
        assert result.deleted == 0
        assert "5 records would be deleted" in result.details
        assert trail_with_old_records.summary()["total"] == 8

    def test_tombstone_expired(self, trail_with_old_records):
        engine = RetentionEngine(trail_with_old_records, retention_days=180)
        result = engine.execute()
        assert result.deleted == 5
        remaining = trail_with_old_records.summary()["total"]
        assert remaining == 9  # 8 original + 1 retention log (tombstoned, not deleted)

    def test_archive_before_delete(self, trail_with_old_records, tmp_path, monkeypatch):
        archive = str(tmp_path / "archive.json")
        engine = RetentionEngine(trail_with_old_records, retention_days=180)
        captured = _capture_retention_log_content(trail_with_old_records, monkeypatch)
        result = engine.execute(archive_path=archive)
        assert result.archived == 5
        assert result.deleted == 5
        assert result.archive_path == archive

        with open(archive) as f:
            data = json.load(f)
        assert data["record_count"] == 5
        assert len(data["records"]) == 5
        purge_record = json.loads(captured[0])
        with open(archive, "rb") as f:
            archive_bytes = f.read()
        assert (
            purge_record["archive_sha256"] == hashlib.sha256(archive_bytes).hexdigest()
        )
        assert purge_record["archive_hmac_sha256"] is None

    def test_archive_digest_and_signature_detect_tampering(self, tmp_path, monkeypatch):
        trail = ContextTrail(backend="memory", signing_key="archive-key")
        trail.log("expired", source="retriever")
        record = trail._backend._records[0]
        record["timestamp"] = (
            datetime.now(timezone.utc) - timedelta(days=400)
        ).isoformat()
        archive = tmp_path / "archive.json"
        captured = _capture_retention_log_content(trail, monkeypatch)

        try:
            RetentionEngine(trail, retention_days=180).execute(
                archive_path=str(archive)
            )
            archive_bytes = archive.read_bytes()
            purge_record = json.loads(captured[0])

            assert (
                purge_record["archive_sha256"]
                == hashlib.sha256(archive_bytes).hexdigest()
            )
            assert trail.verify_payload_signature(
                archive_bytes, purge_record["archive_hmac_sha256"]
            )
            assert purge_record["purged_record_ids"] == [record["id"]]

            tampered_archive = archive_bytes + b" "
            assert (
                purge_record["archive_sha256"]
                != hashlib.sha256(tampered_archive).hexdigest()
            )
            assert not trail.verify_payload_signature(
                tampered_archive, purge_record["archive_hmac_sha256"]
            )
        finally:
            trail.close()

    def test_nothing_to_delete(self, memory_trail):
        memory_trail.log("recent", source="retriever")
        engine = RetentionEngine(memory_trail, retention_days=365)
        result = engine.execute()
        assert result.deleted == 0
        assert "No records" in result.details

    def test_retention_action_logged(self, trail_with_old_records, monkeypatch):
        engine = RetentionEngine(trail_with_old_records, retention_days=180)
        expired = engine.find_expired()
        captured = _capture_retention_log_content(trail_with_old_records, monkeypatch)
        engine.execute()
        records = trail_with_old_records.query(source="custom", limit=10)
        retention_logs = [
            r for r in records if r.get("source_name") == "provena:retention"
        ]
        assert len(retention_logs) == 1
        assert len(captured) == 1
        audit_content = captured[0]
        audit = json.loads(audit_content)
        expired_ids = sorted(record["id"] for record in expired)
        chain_hash_pairs = sorted(
            ([record["id"], record["chain_hash"]] for record in expired),
            key=lambda pair: pair[0],
        )
        assert audit["deleted"] == len(expired_ids)
        assert audit["archive_sha256"] is None
        assert audit["archive_hmac_sha256"] is None
        assert audit["purged_record_ids"] == expired_ids
        assert audit["purged_record_ids_truncated"] is False
        assert (
            audit["purged_record_ids_sha256"]
            == hashlib.sha256(
                json.dumps(expired_ids, separators=(",", ":")).encode()
            ).hexdigest()
        )
        assert (
            audit["purged_chain_hashes_sha256"]
            == hashlib.sha256(
                json.dumps(chain_hash_pairs, separators=(",", ":")).encode()
            ).hexdigest()
        )
        assert (
            retention_logs[0]["content_hash"]
            == hashlib.sha256(audit_content.encode()).hexdigest()
        )

    def test_signed_chain_verifies_after_retention(self):
        trail = ContextTrail(backend="memory", signing_key="chain-key")
        for index in range(3):
            trail.log(f"record {index}", source="retriever")

        try:
            result = RetentionEngine(trail, retention_days=180).execute(
                now=datetime.now(timezone.utc) + timedelta(days=400)
            )

            assert result.deleted == 3
            assert trail.verify_chain().intact
        finally:
            trail.close()

    def test_retention_audit_uses_ids_updated_in_sqlite(self, tmp_path, monkeypatch):
        trail = ContextTrail(storage_path=str(tmp_path / "retention.db"))
        now = datetime.now(timezone.utc)
        trail.log("old record", source="retriever")
        record = trail._backend.all_records()[0]
        trail._backend._conn.execute(
            "UPDATE trail SET timestamp = ? WHERE id = ?",
            ((now - timedelta(days=400)).isoformat(), record["id"]),
        )
        trail._backend._conn.commit()

        try:
            engine = RetentionEngine(trail, retention_days=180)
            expired = engine.find_expired()
            captured = _capture_retention_log_content(trail, monkeypatch)
            result = engine.execute()

            assert result.deleted == 1
            assert json.loads(captured[0])["purged_record_ids"] == [record["id"]]
            audit_log = next(
                row
                for row in trail.query(source="custom", limit=10)
                if row.get("source_name") == "provena:retention"
            )
            assert (
                audit_log["content_hash"]
                == hashlib.sha256(captured[0].encode()).hexdigest()
            )
            assert expired[0]["chain_hash"] == record["chain_hash"]
        finally:
            trail.close()

    def test_retention_audit_bounds_ids_but_hashes_all_purged_records(
        self, monkeypatch
    ):
        trail = ContextTrail(backend="memory")
        now = datetime.now(timezone.utc)
        for i in range(103):
            trail.log(f"old record {i}", source="retriever")
        for record in trail._backend._records:
            record["timestamp"] = (now - timedelta(days=400)).isoformat()

        try:
            engine = RetentionEngine(trail, retention_days=180)
            expired = engine.find_expired()
            expired_ids = sorted(record["id"] for record in expired)
            chain_hash_pairs = sorted(
                ([record["id"], record["chain_hash"]] for record in expired),
                key=lambda pair: pair[0],
            )
            captured = _capture_retention_log_content(trail, monkeypatch)
            result = engine.execute()
            assert len(captured) == 1
            audit_content = captured[0]
            audit = json.loads(audit_content)
            retention_log = next(
                record
                for record in trail.query(source="custom", limit=10)
                if record.get("source_name") == "provena:retention"
            )

            assert result.deleted == len(expired_ids)
            assert len(audit["purged_record_ids"]) < len(expired_ids)
            assert audit["purged_record_ids_truncated"] is True
            assert (
                audit["purged_record_ids_sha256"]
                == hashlib.sha256(
                    json.dumps(expired_ids, separators=(",", ":")).encode()
                ).hexdigest()
            )
            assert (
                audit["purged_chain_hashes_sha256"]
                == hashlib.sha256(
                    json.dumps(chain_hash_pairs, separators=(",", ":")).encode()
                ).hexdigest()
            )
            assert (
                retention_log["content_hash"]
                == hashlib.sha256(audit_content.encode()).hexdigest()
            )
        finally:
            trail.close()

    def test_retention_rerun_reports_zero_and_no_duplicate_purge_log(
        self, trail_with_old_records, monkeypatch
    ):
        """Regression test for #268: retention re-runs must not re-report tombstones."""
        captured = _capture_retention_log_content(trail_with_old_records, monkeypatch)
        engine = RetentionEngine(trail_with_old_records, retention_days=180)

        # Run 1: purges 5 expired records
        res1 = engine.execute()
        assert res1.deleted == 5
        assert len(captured) == 1
        assert trail_with_old_records.summary()["total"] == 9

        # Preview reflects that no records remain to be deleted
        preview = engine.preview()
        assert preview["would_delete"] == 0
        assert preview["provenance"] == {}
        assert preview["freshness"] == {}

        # Run 2: must report 0 deleted and log no duplicate purge event
        res2 = engine.execute()
        assert res2.deleted == 0
        assert res2.archived == 0
        assert "No records" in res2.details
        assert len(captured) == 1  # No second purge event logged
        assert trail_with_old_records.summary()["total"] == 9  # Total unchanged

    def test_retention_rerun_sqlite(self, tmp_path, monkeypatch):
        """Regression test for #268 on SQLite: second run reports deleted=0."""
        db_path = str(tmp_path / "sqlite_retention.db")
        trail = ContextTrail(storage_path=db_path)
        now = datetime.now(timezone.utc)
        captured = _capture_retention_log_content(trail, monkeypatch)

        try:
            for i in range(5):
                trail.log(f"old record {i}", source="retriever")
            for i in range(3):
                trail.log(f"recent record {i}", source="tool")

            # Age the first 5 records in SQLite
            for rid in range(1, 6):
                trail._backend._conn.execute(
                    "UPDATE trail SET timestamp = ? WHERE id = ?",
                    ((now - timedelta(days=400)).isoformat(), rid),
                )
            trail._backend._conn.commit()

            engine = RetentionEngine(trail, retention_days=180)
            res1 = engine.execute()
            assert res1.deleted == 5
            assert len(captured) == 1

            # Preview on SQLite
            assert engine.preview()["would_delete"] == 0

            # Second run on SQLite
            res2 = engine.execute()
            assert res2.deleted == 0
            assert res2.archived == 0
            assert len(captured) == 1

            records = trail._backend.all_records()
            retention_logs = [
                r for r in records if r.get("source_name") == "provena:retention"
            ]
            assert len(retention_logs) == 1
        finally:
            trail.close()

    def test_retention_rerun_incremental_expiry(self, monkeypatch):
        """Verifies that subsequent runs purge only newly-expired records."""
        trail = ContextTrail(backend="memory")
        captured = _capture_retention_log_content(trail, monkeypatch)
        now = datetime.now(timezone.utc)

        try:
            for i in range(5):
                trail.log(f"batch1 record {i}", source="retriever")
            for record in trail._backend._records:
                record["timestamp"] = (now - timedelta(days=400)).isoformat()
            for i in range(3):
                trail.log(f"batch2 record {i}", source="tool")

            engine = RetentionEngine(trail, retention_days=180)
            res1 = engine.execute()
            assert res1.deleted == 5
            assert len(captured) == 1
            payload1 = json.loads(captured[0])
            assert payload1["purged_record_ids"] == [1, 2, 3, 4, 5]

            # Immediate rerun: nothing expired
            res2 = engine.execute()
            assert res2.deleted == 0
            assert len(captured) == 1

            # Now age 2 of the batch2 records
            trail._backend._records[5]["timestamp"] = (
                now - timedelta(days=300)
            ).isoformat()
            trail._backend._records[6]["timestamp"] = (
                now - timedelta(days=300)
            ).isoformat()

            assert engine.preview()["would_delete"] == 2

            # Third run: purges only the 2 newly expired records
            res3 = engine.execute()
            assert res3.deleted == 2
            assert len(captured) == 2
            payload2 = json.loads(captured[1])
            assert payload2["purged_record_ids"] == [6, 7]
            assert (
                payload2["purged_record_ids_sha256"]
                != payload1["purged_record_ids_sha256"]
            )
        finally:
            trail.close()

    def test_delete_expired_excludes_tombstoned_records(self):
        """Direct test: _delete_expired ignores already-tombstoned records."""
        trail = ContextTrail(backend="memory")
        try:
            trail.log("record 0", source="retriever")
            trail.log("record 1", source="retriever")
            engine = RetentionEngine(trail, retention_days=180)

            records = trail._backend.all_records()
            deleted_first = engine._delete_expired(records)
            assert deleted_first == [1, 2]

            # Passing already tombstoned records returns empty
            tombstoned_records = trail._backend.all_records()
            deleted_second = engine._delete_expired(tombstoned_records)
            assert deleted_second == []
        finally:
            trail.close()

    @pytest.mark.skipif(
        not (_pg_importable and _pg_conninfo),
        reason="PostgreSQL not available (set PROVENA_TEST_PG_URL and install psycopg)",
    )
    def test_retention_rerun_postgres(self, monkeypatch):
        """PostgreSQL test: rerun retention does not duplicate purge events."""
        from provena.storage_pg import PostgreSQLBackend

        backend = PostgreSQLBackend(conninfo=_pg_conninfo, pool_size=2)
        with backend._pool.connection() as conn:
            conn.execute("TRUNCATE trail, annotations RESTART IDENTITY CASCADE")

        trail = ContextTrail(storage_path=_pg_conninfo)
        captured = _capture_retention_log_content(trail, monkeypatch)
        now = datetime.now(timezone.utc)

        try:
            for i in range(3):
                trail.log(f"old pg record {i}", source="retriever")

            with backend._pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE trail SET timestamp = %s WHERE id IN (1, 2, 3)",
                    ((now - timedelta(days=400)).isoformat(),),
                )
                conn.commit()

            engine = RetentionEngine(trail, retention_days=180)
            res1 = engine.execute()
            assert res1.deleted == 3
            assert len(captured) == 1

            assert engine.preview()["would_delete"] == 0

            res2 = engine.execute()
            assert res2.deleted == 0
            assert len(captured) == 1
        finally:
            trail.close()
            backend.close()


class TestRetentionCLI:
    def test_retain_dry_run(self, tmp_path):
        from click.testing import CliRunner

        from provena.cli.main import cli

        db_path = str(tmp_path / "test.db")
        trail = ContextTrail(storage_path=db_path)
        now = datetime.now(timezone.utc)
        trail.log("old", source="retriever")
        for record in trail._backend.all_records():
            trail._backend._conn.execute(
                "UPDATE trail SET timestamp = ? WHERE id = ?",
                ((now - timedelta(days=400)).isoformat(), record["id"]),
            )
            trail._backend._conn.commit()
        trail.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["--db", db_path, "retain", "--dry-run"])
        assert result.exit_code == 0
        assert "would be deleted" in result.output

    def test_retain_below_minimum(self):
        from click.testing import CliRunner

        from provena.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["retain", "--max-age", "30"])
        assert result.exit_code == 1


class TestRetentionPagination:
    """Regression tests for #102: retention must not silently cap at one batch."""

    def _old_trail(self, count: int) -> ContextTrail:
        trail = ContextTrail(backend="memory")
        now = datetime.now(timezone.utc)
        for i in range(count):
            trail.log(f"old record {i}", source="retriever")
        for record in trail._backend._records:
            record["timestamp"] = (now - timedelta(days=400)).isoformat()
        return trail

    def test_find_expired_pages_beyond_one_batch(self):
        trail = self._old_trail(7)
        try:
            engine = RetentionEngine(trail, retention_days=180)
            engine._QUERY_BATCH_SIZE = 2
            expired = engine.find_expired()
            assert len(expired) == 7
            assert engine.preview()["would_delete"] == 7
        finally:
            trail.close()

    def test_execute_purges_all_beyond_one_batch(self):
        trail = self._old_trail(7)
        try:
            engine = RetentionEngine(trail, retention_days=180)
            engine._QUERY_BATCH_SIZE = 2
            result = engine.execute()
            assert result.deleted == 7
        finally:
            trail.close()

    def test_pagination_rerun_with_tombstones(self, monkeypatch):
        """Regression test: paginated scanning correctly skips tombstones on rerun."""
        trail = self._old_trail(7)
        captured = _capture_retention_log_content(trail, monkeypatch)
        try:
            engine = RetentionEngine(trail, retention_days=180)
            engine._QUERY_BATCH_SIZE = 2

            # Run 1: purges all 7 records across multiple pages
            res1 = engine.execute()
            assert res1.deleted == 7
            assert len(captured) == 1

            # Preview on paginated scan
            assert engine.preview()["would_delete"] == 0

            # Run 2: skips all tombstoned records across pages
            res2 = engine.execute()
            assert res2.deleted == 0
            assert len(captured) == 1
        finally:
            trail.close()
