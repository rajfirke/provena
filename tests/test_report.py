"""Tests for the compliance report generator."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from provena import ContextTrail, ProvenanceMetadata
from provena.report import generate_pdf_report, generate_report


@pytest.fixture
def trail_with_data():
    trail = ContextTrail(backend="memory")
    prov = ProvenanceMetadata(
        source_url="https://example.com",
        created_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    trail.log("valid data", source="retriever", provenance=prov)
    trail.log("no provenance", source="tool")
    trail.log("agent msg", source="agent")
    yield trail
    trail.close()


@pytest.fixture
def signed_trail():
    trail = ContextTrail(backend="memory", signing_key="test-key")
    prov = ProvenanceMetadata(
        source_url="https://example.com",
        created_at=datetime.now(timezone.utc),
    )
    trail.log("signed data", source="retriever", provenance=prov)
    yield trail
    trail.close()


class TestReportJSON:
    def test_json_report_structure(self, trail_with_data):
        report = generate_report(trail_with_data, format="json")
        data = json.loads(report)
        assert "compliance_score" in data
        assert "chain_integrity" in data
        assert "eu_ai_act" in data
        assert "summary" in data
        assert "issues" in data

    def test_compliance_score(self, trail_with_data):
        report = json.loads(generate_report(trail_with_data, format="json"))
        assert 0 <= report["compliance_score"] <= 100

    def test_eu_ai_act_articles(self, trail_with_data):
        report = json.loads(generate_report(trail_with_data, format="json"))
        articles = report["eu_ai_act"]
        assert "article_10" in articles
        assert "article_12" in articles
        assert "article_13" in articles
        assert "article_14" in articles

    def test_chain_intact(self, trail_with_data):
        report = json.loads(generate_report(trail_with_data, format="json"))
        assert report["chain_integrity"]["status"] == "INTACT"

    def test_signed_trail_higher_score(self, signed_trail):
        report = json.loads(generate_report(signed_trail, format="json"))
        assert report["compliance_score"] >= 75


class TestReportText:
    def test_text_report_contains_sections(self, trail_with_data):
        report = generate_report(trail_with_data, format="text")
        assert "COMPLIANCE SCORE" in report
        assert "CHAIN INTEGRITY" in report
        assert "EU AI ACT" in report
        assert "SUMMARY" in report

    def test_text_report_shows_issues(self, trail_with_data):
        report = generate_report(trail_with_data, format="text")
        assert "ISSUES" in report


class TestReportPDF:
    def test_pdf_requires_fpdf2(self, trail_with_data, tmp_path):
        try:
            import fpdf  # noqa: F401

            path = str(tmp_path / "report.pdf")
            result = generate_pdf_report(trail_with_data, path)
            assert result == path
            with open(path, "rb") as f:
                header = f.read(5)
            assert header == b"%PDF-"
        except ImportError:
            with pytest.raises(ImportError, match="fpdf2"):
                generate_pdf_report(trail_with_data, str(tmp_path / "report.pdf"))

    def test_pdf_string_fallback(self, trail_with_data):
        report = generate_report(trail_with_data, format="pdf")
        assert "%PDF-" in report


class TestReportEmpty:
    def test_empty_trail(self):
        trail = ContextTrail(backend="memory")
        report = json.loads(generate_report(trail, format="json"))
        assert report["summary"]["total_records"] == 0
        assert report["compliance_score"] == 25
        trail.close()


class TestReportInvalidFormats:
    def test_invalid_format(self, trail_with_data):
        with pytest.raises(ValueError, match="Unsupported format"):
            generate_report(trail_with_data, format="html")
