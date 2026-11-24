"""Tests for the retention policy engine."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from provena import ContextTrail
from provena.retention import EU_AI_ACT_MINIMUM_DAYS, RetentionEngine


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
