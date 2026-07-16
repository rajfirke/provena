from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile

from click.testing import CliRunner

from provena.cli.main import cli
from provena.trail import ContextTrail


def _create_trail_db(num_records: int = 3) -> str:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    trail = ContextTrail(storage_path=db_path)
    for i in range(num_records):
        trail.log(f"context entry {i}", source="retriever", source_name=f"src_{i}")
    trail.close()
    return db_path


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


class TestCLIVersion:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.5.0" in result.output

    def test_python_module_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "provena", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "0.5.0" in result.stdout


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
