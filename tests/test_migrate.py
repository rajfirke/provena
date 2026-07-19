"""Tests for the provena migrate CLI command."""

from __future__ import annotations

from click.testing import CliRunner

from provena import ContextTrail
from provena.cli.main import cli


class TestMigrateSQLiteToSQLite:
    def test_migrate_copies_records(self, tmp_path):
        src_path = str(tmp_path / "source.db")
        dst_path = str(tmp_path / "dest.db")

        trail = ContextTrail(storage_path=src_path)
        for i in range(5):
            trail.log(f"record {i}", source="retriever")
        trail.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["migrate", "--from", src_path, "--to", dst_path])
        assert result.exit_code == 0
        assert "5 records" in result.output
        assert "PASS" in result.output

    def test_migrate_chain_integrity(self, tmp_path):
        src_path = str(tmp_path / "source.db")
        dst_path = str(tmp_path / "dest.db")

        trail = ContextTrail(storage_path=src_path)
        for i in range(10):
            trail.log(f"record {i}", source="retriever")
        trail.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["migrate", "--from", src_path, "--to", dst_path])
        assert result.exit_code == 0

        dst_trail = ContextTrail(storage_path=dst_path)
        verdict = dst_trail.verify_chain()
        assert verdict.intact
        assert verdict.total_records == 10
        dst_trail.close()

    def test_migrate_empty_source(self, tmp_path):
        src_path = str(tmp_path / "empty.db")
        dst_path = str(tmp_path / "dest.db")

        trail = ContextTrail(storage_path=src_path)
        trail.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["migrate", "--from", src_path, "--to", dst_path])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()

    def test_migrate_preserves_metadata(self, tmp_path):
        src_path = str(tmp_path / "source.db")
        dst_path = str(tmp_path / "dest.db")

        trail = ContextTrail(storage_path=src_path)
        trail.log("data", source="tool:api", metadata={"key": "value"})
        trail.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["migrate", "--from", src_path, "--to", dst_path])
        assert result.exit_code == 0

        dst_trail = ContextTrail(storage_path=dst_path)
        records = dst_trail.query(source="tool")
        assert len(records) == 1
        assert records[0]["source_name"] == "api"
        dst_trail.close()

    def test_migrate_with_batch_size(self, tmp_path):
        src_path = str(tmp_path / "source.db")
        dst_path = str(tmp_path / "dest.db")

        trail = ContextTrail(storage_path=src_path)
        for i in range(20):
            trail.log(f"record {i}", source="retriever")
        trail.close()

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["migrate", "--from", src_path, "--to", dst_path, "--batch-size", "7"],
        )
        assert result.exit_code == 0
        assert "20 records" in result.output

    def test_migrate_copies_annotations(self, tmp_path):
        src_path = str(tmp_path / "source.db")
        dst_path = str(tmp_path / "dest.db")

        trail = ContextTrail(storage_path=src_path)
        trail.log("data", source="retriever")
        trail.annotate(1, "reviewed", reviewer="admin")
        trail.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["migrate", "--from", src_path, "--to", dst_path])
        assert result.exit_code == 0

        dst_trail = ContextTrail(storage_path=dst_path)
        anns = dst_trail.get_annotations(1)
        assert len(anns) == 1
        assert anns[0]["note"] == "reviewed"
        dst_trail.close()
