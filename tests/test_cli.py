from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner

from provena.cli.main import cli
from provena.models import ProvenanceMetadata
from provena.trail import ContextTrail


def _create_trail_db(num_records: int = 3) -> str:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    trail = ContextTrail(storage_path=db_path)
    for i in range(num_records):
        trail.log(f"context entry {i}", source="retriever", source_name=f"src_{i}")
    trail.close()
    return db_path


@pytest.mark.parametrize("command", ["audit", "verify", "report", "retain", "summary"])
def test_missing_config_error_is_clean(command: str, tmp_path):
    config_path = tmp_path / "missing.toml"

    result = CliRunner().invoke(cli, ["--config", str(config_path), command])

    assert result.exit_code == 1
    assert result.output == f"Config file not found: {config_path}\n"
    assert "Traceback" not in result.output


@pytest.mark.parametrize("command", ["audit", "verify", "report", "retain", "summary"])
def test_malformed_yaml_config_error_is_clean(command: str, tmp_path):
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text("storage: [")

    result = CliRunner().invoke(cli, ["--config", str(config_path), command])

    assert result.exit_code == 1
    assert result.output == f"Invalid YAML config: {config_path}\n"
    assert "Traceback" not in result.output


def test_unsupported_config_error_is_clean(tmp_path):
    config_path = tmp_path / "invalid.txt"
    config_path.write_text("not a supported config")

    result = CliRunner().invoke(cli, ["--config", str(config_path), "audit"])

    assert result.exit_code == 1
    assert "Unsupported config file format: '.txt'" in result.output
    assert "Traceback" not in result.output


class TestCLIAudit:
    def test_audit_table_output(self):
        db_path = _create_trail_db()
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "audit"])
            assert result.exit_code == 0
            assert "src_0" in result.output
            assert "Audit Trail" in result.output
        finally:
            os.unlink(db_path)

    def test_audit_json_output(self):
        db_path = _create_trail_db()
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "audit", "--format", "json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 3
            assert data[0]["source"] == "retriever"
        finally:
            os.unlink(db_path)

    def test_audit_filter_by_source(self):
        db_path = _create_trail_db(0)
        trail = ContextTrail(storage_path=db_path)
        trail.log("ret1", source="retriever")
        trail.log("tool1", source="tool:api")
        trail.log("ret2", source="retriever")
        trail.close()

        try:
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["--db", db_path, "audit", "--source", "retriever", "--format", "json"],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 2
            assert all(r["source"] == "retriever" for r in data)
        finally:
            os.unlink(db_path)

    def test_audit_limit(self):
        db_path = _create_trail_db(10)
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli, ["--db", db_path, "audit", "--limit", "3", "--format", "json"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 3
        finally:
            os.unlink(db_path)

    @pytest.mark.parametrize("bad_limit", ["0", "-1"])
    def test_audit_rejects_nonpositive_limit(self, bad_limit):
        db_path = _create_trail_db(3)
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli, ["--db", db_path, "audit", "--limit", bad_limit]
            )
            assert result.exit_code != 0
            assert "Invalid value for '--limit'" in result.output
        finally:
            os.unlink(db_path)

    def _governance_db(self) -> str:
        """Trail with one record per provenance status.

        No provenance -> MISSING, source_url only -> INCOMPLETE, and both
        required fields -> VALID. None of the three carry a usable timestamp
        except the VALID one, which is created now and so reads as FRESH.
        """
        db_path = _create_trail_db(0)
        trail = ContextTrail(storage_path=db_path)
        trail.log("ungoverned", source="retriever")
        trail.log(
            "partial",
            source="retriever",
            provenance=ProvenanceMetadata(source_url="https://example.com/a"),
        )
        trail.log(
            "governed",
            source="retriever",
            provenance=ProvenanceMetadata(
                source_url="https://example.com/b",
                created_at=datetime.now(timezone.utc),
            ),
        )
        trail.close()
        return db_path

    def test_audit_filter_by_provenance_status(self):
        db_path = self._governance_db()
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--db",
                    db_path,
                    "audit",
                    "--provenance-status",
                    "MISSING",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 1
            assert data[0]["provenance_status"] == "MISSING"
        finally:
            os.unlink(db_path)

    def test_audit_filter_by_freshness_status(self):
        db_path = self._governance_db()
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--db",
                    db_path,
                    "audit",
                    "--freshness-status",
                    "FRESH",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 1
            assert data[0]["freshness_status"] == "FRESH"
        finally:
            os.unlink(db_path)

    def test_audit_status_filters_are_case_insensitive(self):
        # Stored statuses are uppercase and the backend matches exactly, so a
        # lowercase value would silently return nothing without normalization.
        db_path = self._governance_db()
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--db",
                    db_path,
                    "audit",
                    "--provenance-status",
                    "missing",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 1
            assert data[0]["provenance_status"] == "MISSING"
        finally:
            os.unlink(db_path)

    def test_audit_combines_status_filters(self):
        db_path = self._governance_db()
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--db",
                    db_path,
                    "audit",
                    "--provenance-status",
                    "VALID",
                    "--freshness-status",
                    "FRESH",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 1
            assert data[0]["provenance_status"] == "VALID"
            assert data[0]["freshness_status"] == "FRESH"
        finally:
            os.unlink(db_path)

    @pytest.mark.parametrize(
        ("option", "bad_value"),
        [
            ("--provenance-status", "MISSNG"),
            ("--freshness-status", "STALLE"),
        ],
    )
    def test_audit_rejects_unknown_status(self, option, bad_value):
        # A typo must not look like a clean audit: without validation the
        # backend matches nothing and the CLI prints "No records found."
        db_path = self._governance_db()
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "audit", option, bad_value])
            assert result.exit_code != 0
            assert f"Invalid value for '{option}'" in result.output
            assert "No records found" not in result.output
        finally:
            os.unlink(db_path)

    def test_audit_from_date(self):
        db_path = _create_trail_db()
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--db",
                    db_path,
                    "audit",
                    "--from",
                    "2020-01-01",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 3
        finally:
            os.unlink(db_path)

    def test_audit_to_date(self):
        db_path = _create_trail_db()
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--db",
                    db_path,
                    "audit",
                    "--to",
                    "2020-01-01",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0
            assert "No records found." in result.output
        finally:
            os.unlink(db_path)

    def test_audit_date_range(self):
        db_path = _create_trail_db()
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--db",
                    db_path,
                    "audit",
                    "--from",
                    "2020-01-01",
                    "--to",
                    "2030-01-01",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data) == 3
        finally:
            os.unlink(db_path)

    def test_audit_invalid_date(self):
        db_path = _create_trail_db()
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["--db", db_path, "audit", "--from", "not-a-date"],
            )
            assert result.exit_code != 0
            assert "Invalid value for '--from'" in result.output
        finally:
            os.unlink(db_path)

    def test_audit_empty_db(self):
        db_path = _create_trail_db(0)
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "audit"])
            assert result.exit_code == 0
            assert "No records" in result.output
        finally:
            os.unlink(db_path)

    def test_audit_missing_db(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", "/nonexistent/path.db", "audit"])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestCLIVerify:
    def test_verify_intact_chain(self):
        db_path = _create_trail_db()
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "verify"])
            assert result.exit_code == 0
            assert "PASS" in result.output
            assert "3 records" in result.output
        finally:
            os.unlink(db_path)

    def test_verify_tampered_chain(self):
        db_path = _create_trail_db(5)
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE trail SET content_hash = 'TAMPERED' WHERE id = 3")
        conn.commit()
        conn.close()

        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "verify"])
            assert result.exit_code != 0
            assert "FAIL" in result.output
            assert "record 3" in result.output
        finally:
            os.unlink(db_path)

    def test_verify_empty_db(self):
        db_path = _create_trail_db(0)
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "verify"])
            assert result.exit_code == 0
            assert "EMPTY" in result.output
        finally:
            os.unlink(db_path)

    def test_verify_missing_db(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", "/nonexistent/path.db", "verify"])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestCLIReport:
    def test_report_json(self):
        db_path = _create_trail_db()
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "report"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["total_records"] == 3
            assert data["chain_integrity"]["status"] == "INTACT"
            assert "provenance" in data
            assert "freshness" in data
            assert "sources" in data
        finally:
            os.unlink(db_path)

    def test_report_text(self):
        db_path = _create_trail_db()
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "report", "--format", "text"])
            assert result.exit_code == 0
            assert "PROVENA GOVERNANCE REPORT" in result.output
            assert "Chain Integrity" in result.output
            assert "INTACT" in result.output
        finally:
            os.unlink(db_path)

    def test_report_to_file(self):
        db_path = _create_trail_db()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(
                cli, ["--db", db_path, "report", "--output", out_path]
            )
            assert result.exit_code == 0
            assert "written to" in result.output

            with open(out_path) as f:
                data = json.loads(f.read())
            assert data["total_records"] == 3
        finally:
            os.unlink(db_path)
            os.unlink(out_path)

    def test_report_csv_to_file(self):
        db_path = _create_trail_db()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            out_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--db",
                    db_path,
                    "report",
                    "--format",
                    "csv",
                    "--output",
                    out_path,
                ],
            )
            assert result.exit_code == 0
            assert "written to" in result.output

            with open(out_path) as f:
                content = f.read()

            assert "id,timestamp,source,source_name,content_hash" in content
            assert "src_0" in content
        finally:
            os.unlink(db_path)
            os.unlink(out_path)

    def test_report_missing_db(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", "/nonexistent/path.db", "report"])
        assert result.exit_code != 0


class TestCLIExport:
    def test_export_json(self):
        db_path = _create_trail_db()
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "export"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert isinstance(data, list)
            assert len(data) == 3
        finally:
            os.unlink(db_path)

    def test_export_csv(self):
        db_path = _create_trail_db()
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "export", "--format", "csv"])
            assert result.exit_code == 0
            assert "id,timestamp,source,source_name,content_hash" in result.output
            assert "src_0" in result.output
        finally:
            os.unlink(db_path)

    def test_export_to_file(self):
        db_path = _create_trail_db()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out_path = f.name
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli, ["--db", db_path, "export", "--output", out_path]
            )
            assert result.exit_code == 0
            assert "Exported to" in result.output

            with open(out_path) as f:
                data = json.loads(f.read())
            assert isinstance(data, list)
            assert len(data) == 3
        finally:
            os.unlink(db_path)
            os.unlink(out_path)

    def test_export_missing_db(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", "/nonexistent/path.db", "export"])
        assert result.exit_code != 0


class TestCLISummary:
    def test_summary(self):
        db_path = _create_trail_db()
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "summary"])
            assert result.exit_code == 0
            assert "Records:" in result.output
            assert "3" in result.output
            assert "Provenance:" in result.output
            assert "Sources:" in result.output
        finally:
            os.unlink(db_path)

    def test_summary_empty(self):
        db_path = _create_trail_db(0)
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "summary"])
            assert result.exit_code == 0
            assert "Records:" in result.output
            assert "0" in result.output
        finally:
            os.unlink(db_path)

    def test_summary_missing_db(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", "/nonexistent/path.db", "summary"])
        assert result.exit_code != 0

    def _mixed_source_db(self, retriever: int = 3, tool: int = 2) -> str:
        db_path = _create_trail_db(0)
        trail = ContextTrail(storage_path=db_path)
        for i in range(retriever):
            trail.log(f"ret {i}", source="retriever")
        for i in range(tool):
            trail.log(f"tool {i}", source="tool:api")
        trail.close()
        return db_path

    def test_summary_filter_by_source(self):
        db_path = self._mixed_source_db()
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli, ["--db", db_path, "summary", "--source", "retriever"]
            )
            assert result.exit_code == 0
            assert "Records:    3" in result.output
            assert "retriever" in result.output
            assert "tool" not in result.output
        finally:
            os.unlink(db_path)

    def test_summary_filter_by_source_short_flag(self):
        db_path = self._mixed_source_db()
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "summary", "-s", "tool"])
            assert result.exit_code == 0
            assert "Records:    2" in result.output
            assert "retriever" not in result.output
        finally:
            os.unlink(db_path)

    def test_summary_without_source_is_unchanged(self):
        db_path = self._mixed_source_db()
        try:
            runner = CliRunner()
            unfiltered = runner.invoke(cli, ["--db", db_path, "summary"])
            assert unfiltered.exit_code == 0
            assert "Records:    5" in unfiltered.output
            assert "retriever" in unfiltered.output
            assert "tool" in unfiltered.output
        finally:
            os.unlink(db_path)

    def test_summary_filter_counts_beyond_one_query_page(self):
        # trail.query() caps at 100 rows by default, so a naive implementation
        # would report 100 here instead of 150. The filtered path pages.
        db_path = self._mixed_source_db(retriever=150, tool=20)
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli, ["--db", db_path, "summary", "--source", "retriever"]
            )
            assert result.exit_code == 0
            assert "Records:    150" in result.output
            assert "MISSING      150" in result.output
        finally:
            os.unlink(db_path)

    def test_summary_filter_unknown_source_is_empty(self):
        db_path = self._mixed_source_db()
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli, ["--db", db_path, "summary", "--source", "nope"]
            )
            assert result.exit_code == 0
            assert "Records:    0" in result.output
        finally:
            os.unlink(db_path)


class TestCLIVersion:
    def test_version(self):
        from provena import __version__

        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_python_module_version(self):
        from provena import __version__

        result = subprocess.run(
            [sys.executable, "-m", "provena", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert __version__ in result.stdout


class TestCLIHelp:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Provena" in result.output
        assert "audit" in result.output
        assert "verify" in result.output
        assert "report" in result.output

    def test_audit_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["audit", "--help"])
        assert result.exit_code == 0
        assert "--source" in result.output
        assert "--format" in result.output


class TestCLIStats:
    def test_stats_basic_output(self):
        db_path = _create_trail_db(5)
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "stats"])
            assert result.exit_code == 0
            assert "5 records" in result.output
            assert "chain: INTACT" in result.output
            assert "signed: no" in result.output
        finally:
            os.unlink(db_path)

    def test_stats_with_governance(self):
        db_path = _create_trail_db(0)
        trail = ContextTrail(storage_path=db_path)
        trail.log(
            "governed",
            source="retriever",
            provenance=ProvenanceMetadata(
                source_url="https://example.com",
                created_at=datetime.now(timezone.utc),
            ),
        )
        trail.close()

        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "stats"])
            assert result.exit_code == 0
            assert "1 records" in result.output
            assert "VALID: 1" in result.output
            assert "FRESH: 1" in result.output
            assert "chain: INTACT" in result.output
        finally:
            os.unlink(db_path)

    def test_stats_one_line_format(self):
        # Verify it's truly one-line output for CI/monitoring use
        db_path = _create_trail_db(3)
        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "stats"])
            assert result.exit_code == 0
            lines = [line for line in result.output.strip().split("\n") if line]
            assert len(lines) == 1
        finally:
            os.unlink(db_path)
