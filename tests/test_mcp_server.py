"""Tests for the MCP governance server."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from provena import ContextTrail, ProvenanceMetadata
from provena.mcp_server import configure, create_server, get_trail


@pytest.fixture
def trail_with_data():
    trail = ContextTrail(backend="memory")
    prov = ProvenanceMetadata(
        source_url="https://example.com",
        created_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    trail.log("fresh data", source="retriever", source_name="docs", provenance=prov)
    trail.log("no provenance", source="tool", source_name="api")
    trail.log("agent message", source="agent", source_name="planner")
    configure(trail)
    yield trail
    trail.close()


@pytest.fixture
def trail_empty():
    trail = ContextTrail(backend="memory")
    configure(trail)
    yield trail
    trail.close()


@pytest.fixture
def trail_summary_data():
    trail = ContextTrail(backend="memory")
    now = datetime.now(timezone.utc)
    for index in range(3):
        trail.log(
            f"valid record {index}",
            source="retriever",
            source_name=f"docs-{index}",
            provenance=ProvenanceMetadata(
                source_url="https://example.com",
                created_at=now - timedelta(days=index + 1),
            ),
        )
    trail.log("missing provenance", source="tool", source_name="api")
    trail.log(
        "incomplete provenance",
        source="agent",
        source_name="planner",
        provenance=ProvenanceMetadata(source_url="https://example.com"),
    )
    configure(trail)
    yield trail
    trail.close()


@pytest.fixture
def trail_all_valid():
    trail = ContextTrail(backend="memory")
    now = datetime.now(timezone.utc)
    for index in range(2):
        trail.log(
            f"valid record {index}",
            source="retriever",
            source_name=f"docs-{index}",
            provenance=ProvenanceMetadata(
                source_url="https://example.com",
                created_at=now - timedelta(days=index + 1),
            ),
        )
    configure(trail)
    yield trail
    trail.close()


@pytest.fixture
def trail_all_violations():
    trail = ContextTrail(backend="memory")
    trail.log(
        "Data as of 2000-01-01",
        source="mcp",
        source_name="stale-missing",
    )
    trail.log(
        "partial provenance",
        source="tool",
        source_name="partial",
        provenance=ProvenanceMetadata(source_url="https://example.com"),
    )
    configure(trail)
    yield trail
    trail.close()


_has_fastmcp = False
try:
    import fastmcp  # noqa: F401

    _has_fastmcp = True
except ImportError:
    pass


def _call_tool(
    server: Any,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(name, arguments or {}))
    assert not result.is_error
    assert result.content
    return json.loads(result.content[0].text)


class TestMCPServerCreation:
    @pytest.mark.skipif(not _has_fastmcp, reason="fastmcp not installed")
    def test_create_server(self, trail_with_data):
        server = create_server()
        assert server is not None

    @pytest.mark.skipif(_has_fastmcp, reason="fastmcp IS installed")
    def test_create_server_import_error(self):
        with pytest.raises(ImportError, match="fastmcp"):
            create_server()


class TestConfigureAndGetTrail:
    def test_configure_sets_trail(self):
        trail = ContextTrail(backend="memory")
        configure(trail)
        assert get_trail() is trail
        trail.close()

    def test_get_trail_creates_default(self, tmp_path, monkeypatch):
        import provena.mcp_server as mod

        mod._trail = None
        monkeypatch.setenv("PROVENA_DB", str(tmp_path / "test.db"))
        t = get_trail()
        assert t is not None
        t.close()
        mod._trail = None


class TestMCPToolFunctions:
    """Test the tool functions directly (without FastMCP transport)."""

    @pytest.mark.skipif(not _has_fastmcp, reason="fastmcp not installed")
    def test_list_violations_deduplicates_records(self):
        trail = ContextTrail(backend="memory")
        trail.log(
            "Data as of 2000-01-01",
            source="mcp",
            source_name="stale-missing",
        )
        trail.log(
            "partial provenance",
            source="tool",
            source_name="partial",
            provenance=ProvenanceMetadata(source_url="https://example.com"),
        )
        configure(trail)
        try:
            result = _call_tool(create_server(), "list_violations")
        finally:
            trail.close()

        assert result["total_violations"] == 2
        assert len(result["violations"]) == 2
        assert len({item["id"] for item in result["violations"]}) == 2
        assert {
            (item["provenance_status"], item["freshness_status"])
            for item in result["violations"]
        } == {("MISSING", "STALE"), ("INCOMPLETE", "UNKNOWN")}

    @pytest.mark.skipif(not _has_fastmcp, reason="fastmcp not installed")
    def test_get_summary_reports_percentages(self, trail_summary_data):
        result = _call_tool(create_server(), "get_summary")

        assert result["total"] == 5
        assert result["provenance"] == {"VALID": 3, "MISSING": 1, "INCOMPLETE": 1}
        assert result["freshness"] == {"FRESH": 3, "UNKNOWN": 2}
        assert result["provenance_valid_pct"] == 60
        assert result["freshness_fresh_pct"] == 60
        assert result["recommendation"] == "60% provenance valid, 60% fresh."

    @pytest.mark.skipif(not _has_fastmcp, reason="fastmcp not installed")
    def test_check_freshness_filters_and_reports_stale_entries(self):
        trail = ContextTrail(backend="memory")
        now = datetime.now(timezone.utc)
        trail.log(
            "old data",
            source="retriever",
            source_name="old-docs",
            provenance=ProvenanceMetadata(
                source_url="https://example.com/old",
                created_at=now - timedelta(days=180),
            ),
        )
        trail.log(
            "fresh data",
            source="retriever",
            source_name="new-docs",
            provenance=ProvenanceMetadata(
                source_url="https://example.com/new",
                created_at=now - timedelta(days=1),
            ),
        )
        trail.log("other source", source="tool", source_name="api")
        configure(trail)
        try:
            result = _call_tool(
                create_server(),
                "check_freshness",
                {"source": "retriever", "limit": 10},
            )
        finally:
            trail.close()

        assert result["total_checked"] == 2
        assert result["fresh"] == 1
        assert result["stale"] == 1
        assert result["unknown"] == 0
        assert result["stale_entries"] == [
            {"id": 1, "source": "retriever", "source_name": "old-docs"}
        ]
        assert "1 stale entries detected" in result["recommendation"]

    @pytest.mark.skipif(not _has_fastmcp, reason="fastmcp not installed")
    def test_check_provenance_filters_and_counts_statuses(self):
        trail = ContextTrail(backend="memory")
        now = datetime.now(timezone.utc)
        trail.log(
            "valid tool data",
            source="tool",
            source_name="api-valid",
            provenance=ProvenanceMetadata(
                source_url="https://example.com",
                created_at=now,
            ),
        )
        trail.log("missing tool data", source="tool", source_name="api-missing")
        trail.log(
            "incomplete retriever data",
            source="retriever",
            source_name="docs-partial",
            provenance=ProvenanceMetadata(source_url="https://example.com"),
        )
        configure(trail)
        try:
            result = _call_tool(
                create_server(),
                "check_provenance",
                {"source": "tool", "limit": 10},
            )
        finally:
            trail.close()

        assert result == {
            "total_checked": 2,
            "valid": 1,
            "missing": 1,
            "incomplete": 0,
            "recommendation": "1 missing, 0 incomplete — attach provenance metadata.",
        }

    def test_check_freshness(self, trail_with_data):
        from provena.mcp_server import create_server

        if not _has_fastmcp:
            pytest.skip("fastmcp not installed")

        server = create_server()
        tools = {t.name: t for t in asyncio.run(server.list_tools())}
        assert "check_freshness" in tools

    def test_check_freshness_logic(self, trail_with_data):
        trail = get_trail()
        records = trail.query(limit=10)
        stale = [r for r in records if r.get("freshness_status") == "STALE"]
        fresh = [r for r in records if r.get("freshness_status") == "FRESH"]
        assert len(records) == 3
        assert len(fresh) == 1
        assert len(stale) == 0

    def test_verify_chain_logic(self, trail_with_data):
        trail = get_trail()
        verdict = trail.verify_chain()
        assert verdict.intact
        assert verdict.total_records == 3

    def test_summary_logic(self, trail_with_data):
        trail = get_trail()
        s = trail.summary()
        assert s["total"] == 3
        assert "VALID" in s["provenance"] or "MISSING" in s["provenance"]

    def test_violations_logic(self, trail_with_data):
        trail = get_trail()
        missing = trail.query(provenance_status="MISSING")
        assert len(missing) == 2

    def test_provenance_check_logic(self, trail_with_data):
        trail = get_trail()
        records = trail.query(limit=10)
        valid = [r for r in records if r.get("provenance_status") == "VALID"]
        missing = [r for r in records if r.get("provenance_status") == "MISSING"]
        assert len(valid) == 1
        assert len(missing) == 2

    def test_empty_trail(self, trail_empty):
        trail = get_trail()
        assert trail.summary()["total"] == 0
        assert trail.verify_chain().intact

    @pytest.mark.skipif(not _has_fastmcp, reason="fastmcp not installed")
    def test_empty_tool_responses(self, trail_empty):
        server = create_server()

        assert _call_tool(server, "list_violations")["total_violations"] == 0
        assert _call_tool(server, "get_summary")["recommendation"] == (
            "No records in the audit trail."
        )
        assert _call_tool(server, "check_freshness") == {
            "total_checked": 0,
            "fresh": 0,
            "stale": 0,
            "unknown": 0,
            "recommendation": "All context is fresh.",
        }
        assert _call_tool(server, "check_provenance") == {
            "total_checked": 0,
            "valid": 0,
            "missing": 0,
            "incomplete": 0,
            "recommendation": "All entries have valid provenance.",
        }

    @pytest.mark.skipif(not _has_fastmcp, reason="fastmcp not installed")
    def test_all_valid_tool_responses(self, trail_all_valid):
        server = create_server()

        assert _call_tool(server, "list_violations")["total_violations"] == 0
        summary = _call_tool(server, "get_summary")
        assert summary["provenance_valid_pct"] == 100
        assert summary["freshness_fresh_pct"] == 100
        assert _call_tool(server, "check_freshness")["stale"] == 0
        assert _call_tool(server, "check_provenance") == {
            "total_checked": 2,
            "valid": 2,
            "missing": 0,
            "incomplete": 0,
            "recommendation": "All entries have valid provenance.",
        }

    @pytest.mark.skipif(not _has_fastmcp, reason="fastmcp not installed")
    def test_all_violation_tool_responses(self, trail_all_violations):
        server = create_server()

        violations = _call_tool(server, "list_violations")
        assert violations["total_violations"] == 2
        assert "2 violations" in violations["recommendation"]
        summary = _call_tool(server, "get_summary")
        assert summary["provenance_valid_pct"] == 0
        freshness = _call_tool(server, "check_freshness")
        assert freshness["stale"] == 1
        assert freshness["unknown"] == 1
        provenance = _call_tool(server, "check_provenance")
        assert provenance["missing"] == 1
        assert provenance["incomplete"] == 1


class TestMCPCLI:
    @pytest.mark.skipif(not _has_fastmcp, reason="fastmcp not installed")
    def test_mcp_serve_with_fastmcp(self, monkeypatch):
        import fastmcp
        from click.testing import CliRunner

        from provena.cli.main import cli

        # Prevent FastMCP from taking over stdio streams during CLI testing
        monkeypatch.setattr(fastmcp.FastMCP, "run", lambda self, transport=None: None)

        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "serve"])
        assert result.exit_code == 0

    def test_mcp_help(self):
        from click.testing import CliRunner

        from provena.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "--help"])
        assert result.exit_code == 0
        assert "serve" in result.output


class TestMCPResources:
    """Test all MCP resource endpoints (health, summary, chain status)."""

    @staticmethod
    def _read_resource_json(server, uri: str):
        import asyncio
        import json

        async def read_res(uri: str):
            res = await server.read_resource(uri)

            if hasattr(res, "contents"):
                res = res.contents

            if isinstance(res, list):
                if not res:
                    return {}
                item = res[0]
                content = getattr(item, "content", item)
            elif hasattr(res, "content"):
                content = res.content
            else:
                content = res

            if isinstance(content, (bytes, bytearray)):
                content = content.decode("utf-8")

            if isinstance(content, str):
                return json.loads(content)
            return content

        return asyncio.run(read_res(uri))

    @pytest.mark.skipif(not _has_fastmcp, reason="fastmcp not installed")
    def test_mcp_server_resources(self, trail_with_data):
        server = create_server()

        # 1. Verify provena://health
        health_data = self._read_resource_json(server, "provena://health")
        assert health_data["healthy"] is True

        # 2. Verify provena://summary (Populated Trail)
        summary_data = self._read_resource_json(server, "provena://summary")
        assert summary_data["total"] == 3

        # 3. Verify provena://chain/status (Intact)
        chain_data = self._read_resource_json(server, "provena://chain/status")
        assert chain_data["intact"] is True
        assert chain_data["total_records"] == 3

    @pytest.mark.skipif(not _has_fastmcp, reason="fastmcp not installed")
    def test_mcp_resources_empty_trail(self, trail_empty):
        server = create_server()

        # Summary with empty trail
        summary_data = self._read_resource_json(server, "provena://summary")
        assert summary_data["total"] == 0

        # Chain status with empty trail
        chain_data = self._read_resource_json(server, "provena://chain/status")
        assert chain_data["intact"] is True
        assert chain_data["total_records"] == 0
