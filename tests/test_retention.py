"""Tests for the retention policy engine."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from provena import ContextTrail
from provena.retention import EU_AI_ACT_MINIMUM_DAYS, RetentionEngine


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

    def test_delete_expired(self, trail_with_old_records):
        engine = RetentionEngine(trail_with_old_records, retention_days=180)
        result = engine.execute()
        assert result.deleted == 5
        remaining = trail_with_old_records.summary()["total"]
        assert remaining == 4

    def test_archive_before_delete(self, trail_with_old_records, tmp_path):
        archive = str(tmp_path / "archive.json")
        engine = RetentionEngine(trail_with_old_records, retention_days=180)
        result = engine.execute(archive_path=archive)
        assert result.archived == 5
        assert result.deleted == 5
        assert result.archive_path == archive

        with open(archive) as f:
            data = json.load(f)
        assert data["record_count"] == 5
        assert len(data["records"]) == 5

    def test_nothing_to_delete(self, memory_trail):
        memory_trail.log("recent", source="retriever")
        engine = RetentionEngine(memory_trail, retention_days=365)
        result = engine.execute()
        assert result.deleted == 0
        assert "No records" in result.details

    def test_retention_action_logged(self, trail_with_old_records):
        engine = RetentionEngine(trail_with_old_records, retention_days=180)
        engine.execute()
        records = trail_with_old_records.query(source="custom", limit=10)
        retention_logs = [
            r for r in records if r.get("source_name") == "provena:retention"
        ]
        assert len(retention_logs) == 1


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
