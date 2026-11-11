"""
Comprehensive test coverage for MCP and MEMORY context sources.
What the following tests aim to cover:
    1. Provenance validation with MCP & MEMORY
    2. Freshness checking
    3. Chain integrity with mixed sources
    4. Export formats with metadata
    5. Annotations & reviewer comments
    6. Metadata preservation
    7. Oversize-content threshold edge cases
    8. Policy enforcement (BLOCK/WARN)
    9. Multi-source query filters
    10. Summary filters by source type
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from provena.models import ContextSource, ProvenanceMetadata
from provena.policy import provenance_check
from provena.trail import ContextTrail, EnforcementLevel, PolicyViolation


class TestMcpMemoryProvenanceValidation:
    """Provenance validation with MCP & MEMORY sources"""

    def test_log_mcp_with_valid_provenance(self, memory_trail):
        """Test logging MCP entry with complete provenance metadata"""
        provenance = ProvenanceMetadata(
            source_url="https://github.com/search/code",
            author="github-bot",
            created_at=datetime.now(timezone.utc),
            version="v1.0",
            extra={"search_query": "python errors"},
        )
        record = memory_trail.log(
            content="github search result",
            source="mcp:github_search",
            provenance=provenance,
        )
        assert record is not None
        assert record.entry.source == ContextSource.MCP
        assert record.entry.source_name == "github_search"
        assert record.provenance_result is not None
        assert record.provenance_result.status == "VALID"

    def test_log_mcp_with_missing_provenance(self, memory_trail):
        """Test logging MCP entry without provenance shows MISSING status"""
        record = memory_trail.log(
            content="mcp tool output",
            source="mcp:filesystem",
        )
        assert record is not None
        assert record.provenance_result is not None
        assert record.provenance_result.status == "MISSING"
        assert "source_url" in record.provenance_result.missing_fields

    def test_log_memory_with_valid_provenance(self, memory_trail):
        """Test logging MEMORY entry with complete provenance"""
        provenance = ProvenanceMetadata(
            source_url="memory://agent_recall",
            author="agent_01",
            created_at=datetime.now(timezone.utc),
            version="recall_v2",
            extra={"memory_type": "long_term", "confidence": 0.92},
        )
        record = memory_trail.log(
            content="recalled context from agent memory",
            source="memory:long_term",
            provenance=provenance,
        )
        assert record is not None
        assert record.entry.source == ContextSource.MEMORY
        assert record.entry.source_name == "long_term"
        assert record.provenance_result is not None
        assert record.provenance_result.status == "VALID"

    def test_log_memory_with_incomplete_provenance(self, memory_trail):
        """Test logging MEMORY entry with partial provenance"""
        provenance = ProvenanceMetadata(
            # Missing source_url
            author="system",
            created_at=datetime.now(timezone.utc),
        )
        record = memory_trail.log(
            content="memory data",
            source="memory:short_term",
            provenance=provenance,
        )
        assert record is not None
        assert record.provenance_result is not None
        # May be VALID if author + created_at are sufficient, or INCOMPLETE
        assert record.provenance_result.status in ["VALID", "INCOMPLETE"]

    def test_query_mcp_by_provenance_status(self, memory_trail):
        """Test querying MCP records by provenance status"""
        # Log one with valid provenance
        memory_trail.log(
            "mcp result valid",
            source="mcp:api",
            provenance=ProvenanceMetadata(
                source_url="https://api.example.com",
                created_at=datetime.now(timezone.utc),
            ),
        )
        # Log one without provenance
        memory_trail.log("mcp result missing", source="mcp:filesystem")

        # Query all MCP records
        mcp_records = memory_trail.query(source="mcp")
        assert len(mcp_records) == 2

        # Verify statuses in records
        statuses = {r.get("provenance_status") for r in mcp_records}
        assert "VALID" in statuses
        assert "MISSING" in statuses


class TestMcpMemoryFreshnessChecking:
    """Freshness checking with MCP & MEMORY sources"""

    def test_mcp_freshness_fresh_data(self, memory_trail):
        """Test MCP data created recently is marked FRESH"""
        recent_time = datetime.now(timezone.utc)
        provenance = ProvenanceMetadata(
            source_url="https://api.example.com",
            created_at=recent_time,
        )
        record = memory_trail.log(
            content="fresh mcp result",
            source="mcp:api",
            provenance=provenance,
        )
        assert record is not None
        assert record.freshness_result is not None
        assert record.freshness_result.status == "FRESH"

    def test_mcp_freshness_stale_data(self, memory_trail):
        """Test MCP data older than threshold is marked STALE"""
        # Create data that's older than max_age_days (default 90 days)
        old_time = datetime.now(timezone.utc) - timedelta(days=100)
        provenance = ProvenanceMetadata(
            source_url="https://api.example.com",
            created_at=old_time,
        )
        record = memory_trail.log(
            content="stale mcp result",
            source="mcp:api",
            provenance=provenance,
        )
        assert record is not None
        assert record.freshness_result is not None
        assert record.freshness_result.status == "STALE"

    def test_mcp_freshness_without_timestamp(self, memory_trail):
        """Test MCP data without timestamp shows UNKNOWN freshness"""
        provenance = ProvenanceMetadata(
            source_url="https://api.example.com",
            # No created_at timestamp
        )
        record = memory_trail.log(
            content="mcp result no timestamp",
            source="mcp:api",
            provenance=provenance,
        )
        assert record is not None
        assert record.freshness_result is not None
        assert record.freshness_result.status == "UNKNOWN"

    def test_memory_freshness_fresh_recall(self, memory_trail):
        """Test MEMORY data created recently is marked FRESH"""
        recent_time = datetime.now(timezone.utc)
        provenance = ProvenanceMetadata(
            created_at=recent_time,
        )
        record = memory_trail.log(
            content="fresh memory recall",
            source="memory:short_term",
            provenance=provenance,
        )
        assert record is not None
        assert record.freshness_result is not None
        assert record.freshness_result.status == "FRESH"

    def test_memory_freshness_stale_recall(self, memory_trail):
        """Test MEMORY data older than threshold is marked STALE"""
        old_time = datetime.now(timezone.utc) - timedelta(days=100)
        provenance = ProvenanceMetadata(
            created_at=old_time,
        )
        record = memory_trail.log(
            content="stale memory recall",
            source="memory:long_term",
            provenance=provenance,
        )
        assert record is not None
        assert record.freshness_result is not None
        assert record.freshness_result.status == "STALE"


class TestMcpMemoryChainIntegrity:
    """Chain integrity with mixed sources"""

    def test_verify_chain_with_mixed_sources(self, memory_trail):
        """Test chain integrity verification across all source types"""
        # Log entries from different sources
        r1 = memory_trail.log("retriever doc", source="retriever")
        r2 = memory_trail.log("tool result", source="tool:api")
        r3 = memory_trail.log("agent message", source="agent")
        r4 = memory_trail.log("mcp filesystem", source="mcp:filesystem")
        r5 = memory_trail.log("memory recall", source="memory:agent")

        # All should have chain hashes
        assert all(r.chain_hash for r in [r1, r2, r3, r4, r5])

        # Chain should maintain order - each record's previous_hash should
        # match previous record's chain_hash
        # (except first record, which may have empty or genesis hash)
        assert r2.previous_hash == r1.chain_hash
        assert r3.previous_hash == r2.chain_hash
        assert r4.previous_hash == r3.chain_hash
        assert r5.previous_hash == r4.chain_hash

        # Verify chain is intact
        verdict = memory_trail.verify_chain()
        assert verdict.intact is True
        assert verdict.total_records == 5
        assert verdict.broken_at is None

    def test_mixed_sources_in_summary(self, memory_trail):
        """Test summary reflects all source types"""
        memory_trail.log("retriever result", source="retriever")
        memory_trail.log("tool result", source="tool:api")
        memory_trail.log("mcp result", source="mcp:github")
        memory_trail.log("memory result", source="memory:long_term")

        summary = memory_trail.summary()
        sources = summary.get("sources", {})

        assert sources.get("retriever") == 1
        assert sources.get("tool") == 1
        assert sources.get("mcp") == 1
        assert sources.get("memory") == 1
        assert summary.get("total") == 4


class TestMcpMemoryExportFormats:
    """CSV & JSON export formats with metadata"""

    def test_json_export_with_mcp_memory(self, memory_trail):
        """Test JSON export includes MCP and MEMORY with metadata"""
        memory_trail.log(
            "mcp result",
            source="mcp:filesystem",
            metadata={"file_path": "/etc/hosts"},
        )
        memory_trail.log(
            "memory result",
            source="memory:long_term",
            metadata={"confidence": 0.95},
        )

        json_export = memory_trail.export(format="json")
        data = json.loads(json_export)

        assert len(data) == 2
        assert data[0]["source"] == "mcp"
        # Metadata is in metadata_json field
        metadata_0 = json.loads(data[0].get("metadata_json", "{}"))
        assert metadata_0.get("file_path") == "/etc/hosts"
        assert data[1]["source"] == "memory"
        metadata_1 = json.loads(data[1].get("metadata_json", "{}"))
        assert metadata_1.get("confidence") == 0.95

    def test_json_with_annotations_mcp_memory(self, memory_trail):
        """Test JSON with annotations preserves MCP/MEMORY entries"""
        r1 = memory_trail.log("mcp result", source="mcp:api")
        memory_trail.log("memory result", source="memory:agent")

        # Add annotations
        if r1 and r1.id > 0:
            memory_trail.annotate(
                record_id=r1.id, note="Verified", reviewer="alice@example.com"
            )

        json_export = memory_trail.export(format="json_with_annotations")
        # json_with_annotations returns a string, not parsed JSON
        # Just verify both MCP and MEMORY are in the export
        assert "mcp" in json_export
        assert "memory" in json_export

    def test_csv_export_with_mcp_memory(self, memory_trail):
        """Test CSV export includes MCP and MEMORY sources"""
        memory_trail.log(
            "mcp result",
            source="mcp:filesystem",
            source_name="fs_scan",
        )
        memory_trail.log(
            "memory result",
            source="memory:short_term",
            source_name="recall",
        )

        csv_export = memory_trail.export(format="csv")
        csv_file = io.StringIO(csv_export)
        reader = csv.DictReader(csv_file)
        rows = list(reader)

        assert len(rows) == 2
        assert rows[0]["source"] == "mcp"
        assert rows[0]["source_name"] == "fs_scan"
        assert rows[1]["source"] == "memory"
        assert rows[1]["source_name"] == "recall"


class TestMcpMemoryMetadataPreservation:
    """Metadata preservation through lifecycle"""

    def test_mcp_metadata_preserved_in_query(self, memory_trail):
        """Test MCP metadata is preserved when querying"""
        memory_trail.log(
            "mcp output",
            source="mcp:api",
            metadata={
                "api_version": "v2",
                "response_code": 200,
                "execution_time_ms": 145,
            },
        )

        queried = memory_trail.query(source="mcp")
        assert len(queried) == 1
        # Metadata is stored in metadata_json field
        metadata = json.loads(queried[0].get("metadata_json", "{}"))
        assert metadata["api_version"] == "v2"
        assert metadata["response_code"] == 200
        assert metadata["execution_time_ms"] == 145

    def test_memory_metadata_preserved_in_export(self, memory_trail):
        """Test MEMORY metadata is preserved in export"""
        memory_trail.log(
            "memory data",
            source="memory:long_term",
            metadata={
                "recall_type": "episodic",
                "confidence_score": 0.88,
                "tags": ["important", "verified"],
            },
        )

        json_export = memory_trail.export(format="json")
        data = json.loads(json_export)
        record = data[0]

        metadata = json.loads(record.get("metadata_json", "{}"))
        assert metadata["recall_type"] == "episodic"
        assert metadata["confidence_score"] == 0.88
        assert metadata["tags"] == ["important", "verified"]

    def test_metadata_with_special_types(self, memory_trail):
        """Test metadata with various Python types is preserved"""
        metadata = {
            "string": "value",
            "integer": 42,
            "float": 3.14,
            "boolean": True,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
            "null": None,
        }
        memory_trail.log(
            "test data",
            source="mcp:test",
            metadata=metadata,
        )

        queried = memory_trail.query(source="mcp")
        assert len(queried) == 1
        retrieved_metadata = json.loads(queried[0].get("metadata_json", "{}"))
        assert retrieved_metadata["string"] == "value"
        assert retrieved_metadata["integer"] == 42
        assert retrieved_metadata["float"] == 3.14
        assert retrieved_metadata["boolean"] is True
        assert retrieved_metadata["list"] == [1, 2, 3]
        assert retrieved_metadata["dict"]["nested"] == "value"
        # JSON null becomes None in Python
        assert retrieved_metadata.get("null") is None


class TestMcpMemoryContentTruncation:
    """Oversize-content threshold edge cases."""

    def test_mcp_content_truncation(self, memory_trail):
        """Test large MCP content is marked as over the configured threshold."""
        # Create a trail with small max_content_bytes
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            small_trail = ContextTrail(
                storage_path=f.name,
                max_content_bytes=1000,
            )
            large_content = "x" * 10000  # 10KB
            record = small_trail.log(
                large_content,
                source="mcp:large_output",
            )
            assert record is not None
            assert record.entry.truncated is True
            assert record.entry.content_hash is not None
            small_trail.close()

    def test_memory_content_truncation(self, memory_trail):
        """Test large MEMORY content is marked as over the configured threshold."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            small_trail = ContextTrail(
                storage_path=f.name,
                max_content_bytes=1000,
            )
            large_content = "y" * 10000  # 10KB
            record = small_trail.log(
                large_content,
                source="memory:large_recall",
            )
            assert record is not None
            assert record.entry.truncated is True
            small_trail.close()

    def test_truncated_content_query(self, memory_trail):
        """Test the over-threshold flag is preserved in queries."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            small_trail = ContextTrail(
                storage_path=f.name,
                max_content_bytes=1000,
            )
            large_content = "z" * 10000
            small_trail.log(
                large_content,
                source="mcp:test",
            )

            records = small_trail.query(source="mcp")
            assert len(records) == 1
            # truncated is stored as integer (0 or 1) not boolean
            assert records[0]["truncated"] in (True, 1)
            small_trail.close()


class TestMcpMemoryPolicyEnforcement:
    """Policy enforcement (BLOCK/WARN)"""

    def test_mcp_policy_block_missing_provenance(self):
        """Test BLOCK policy on MCP with missing provenance"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            trail = ContextTrail(
                storage_path=f.name,
                policies=[
                    provenance_check(
                        status="MISSING", enforcement=EnforcementLevel.BLOCK
                    ),
                ],
            )

            # Should raise PolicyViolation when logging MCP without provenance
            with pytest.raises(PolicyViolation):
                trail.log("mcp data", source="mcp:api")
            trail.close()

    def test_mcp_policy_log_enforcement(self):
        """Test LOG policy records violations but continues"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            trail = ContextTrail(
                storage_path=f.name,
                policies=[
                    provenance_check(
                        status="MISSING", enforcement=EnforcementLevel.LOG
                    ),
                ],
            )

            # Should not raise, just log
            record = trail.log("mcp data", source="mcp:api")
            assert record is not None
            assert record.entry.source == ContextSource.MCP
            trail.close()


class TestMcpMemoryQueryFilters:
    """Multi-source query filters"""

    def test_query_by_source(self, memory_trail):
        """Test querying by source type"""
        memory_trail.log("mcp fs 1", source="mcp:filesystem")
        memory_trail.log("mcp fs 2", source="mcp:filesystem")
        memory_trail.log("mcp github", source="mcp:github")
        memory_trail.log("memory short", source="memory:short_term")

        # Query only MCP
        mcp_records = memory_trail.query(source="mcp")
        assert len(mcp_records) == 3

        # Query only MEMORY
        memory_records = memory_trail.query(source="memory")
        assert len(memory_records) == 1

    def test_query_memory_by_source(self, memory_trail):
        """Test querying MEMORY by source type"""
        memory_trail.log("short recall 1", source="memory:short_term")
        memory_trail.log("short recall 2", source="memory:short_term")
        memory_trail.log("long recall", source="memory:long_term")

        # Query all memory
        memory_records = memory_trail.query(source="memory")
        assert len(memory_records) == 3

        # Verify they're all memory source
        assert all(r["source"] == "memory" for r in memory_records)

    def test_query_mixed_sources_separate(self, memory_trail):
        """Test querying different source types separately"""
        memory_trail.log("mcp fs", source="mcp:filesystem")
        memory_trail.log("mcp github", source="mcp:github")
        memory_trail.log("memory short", source="memory:short_term")
        memory_trail.log("memory long", source="memory:long_term")

        # Query only MCP
        mcp_all = memory_trail.query(source="mcp")
        assert len(mcp_all) == 2
        assert all(r["source"] == "mcp" for r in mcp_all)

        # Query only MEMORY
        mem_all = memory_trail.query(source="memory")
        assert len(mem_all) == 2
        assert all(r["source"] == "memory" for r in mem_all)


class TestMcpMemorySummaryFilters:
    """Summary filters by source type"""

    def test_summary_includes_mcp(self, memory_trail):
        """Test summary includes MCP metrics"""
        memory_trail.log("mcp result 1", source="mcp:api")
        memory_trail.log("mcp result 2", source="mcp:filesystem")
        memory_trail.log("retriever result", source="retriever")

        global_summary = memory_trail.summary()
        assert global_summary.get("total") == 3

        sources = global_summary.get("sources", {})
        assert sources.get("mcp") == 2
        assert sources.get("retriever") == 1

    def test_summary_includes_memory(self, memory_trail):
        """Test summary includes MEMORY metrics"""
        memory_trail.log("memory short", source="memory:short_term")
        memory_trail.log("memory long", source="memory:long_term")
        memory_trail.log("tool result", source="tool:api")

        global_summary = memory_trail.summary()
        assert global_summary.get("total") == 3

        sources = global_summary.get("sources", {})
        assert sources.get("memory") == 2
        assert sources.get("tool") == 1

    def test_summary_provenance_by_source(self, memory_trail):
        """Test summary shows provenance status breakdown"""
        # Valid MCP provenance
        memory_trail.log(
            "mcp with prov",
            source="mcp:api",
            provenance=ProvenanceMetadata(
                source_url="https://example.com",
                created_at=datetime.now(timezone.utc),
            ),
        )
        # Missing MCP provenance
        memory_trail.log("mcp without prov", source="mcp:filesystem")

        summary = memory_trail.summary()
        provenance_stats = summary.get("provenance", {})

        # Should show mix of VALID and MISSING
        assert provenance_stats.get("VALID", 0) >= 1
        assert provenance_stats.get("MISSING", 0) >= 1


# Additional integration tests


class TestMcpMemoryIntegration:
    """Integration tests across multiple gaps"""

    def test_end_to_end_mcp_governance(self, memory_trail):
        """E2E test - log, validate, query, verify MCP data"""
        provenance = ProvenanceMetadata(
            source_url="https://github.com/api",
            author="github-bot",
            created_at=datetime.now(timezone.utc),
            extra={"search": "security"},
        )

        record = memory_trail.log(
            content="github search result",
            source="mcp:github",
            source_name="security_search",
            provenance=provenance,
            metadata={"results_count": 42},
        )

        assert record.entry.source == ContextSource.MCP
        assert record.provenance_result.status == "VALID"
        assert record.freshness_result.status == "FRESH"

        # Query and verify
        queried = memory_trail.query(source="mcp")
        assert len(queried) == 1
        metadata = json.loads(queried[0].get("metadata_json", "{}"))
        assert metadata["results_count"] == 42

        # Export and verify
        json_data = json.loads(memory_trail.export(format="json"))
        assert json_data[0]["source"] == "mcp"

        # Verify chain
        verdict = memory_trail.verify_chain()
        assert verdict.intact

    def test_end_to_end_memory_governance(self, memory_trail):
        """E2E test - log, validate, query, verify MEMORY data"""
        provenance = ProvenanceMetadata(
            source_url="memory://agent_recall",
            created_at=datetime.now(timezone.utc),
            extra={"memory_format": "vector_embedding"},
        )

        record = memory_trail.log(
            content="agent long-term memory recall",
            source="memory:long_term",
            source_name="knowledge_base",
            provenance=provenance,
            metadata={"embedding_model": "ada", "similarity": 0.89},
        )

        assert record.entry.source == ContextSource.MEMORY
        assert record.provenance_result.status == "VALID"
        assert record.freshness_result.status == "FRESH"

        # Query and verify
        queried = memory_trail.query(source="memory")
        assert len(queried) == 1
        metadata = json.loads(queried[0].get("metadata_json", "{}"))
        assert metadata["similarity"] == 0.89

        # Summary
        summary = memory_trail.summary()
        assert summary["sources"]["memory"] == 1

    def test_full_lifecycle_mixed_sources(self, memory_trail):
        """Test full lifecycle with all source types mixed"""
        # Create diverse entries
        memory_trail.log("retriever doc", source="retriever")
        memory_trail.log("tool api call", source="tool:weather_api")
        memory_trail.log("agent message", source="agent")
        memory_trail.log("mcp filesystem", source="mcp:filesystem")
        memory_trail.log("memory recall", source="memory:long_term")

        # Verify all appear in summary
        summary = memory_trail.summary()
        assert summary["total"] == 5
        sources = summary["sources"]
        assert sources["retriever"] == 1
        assert sources["tool"] == 1
        assert sources["agent"] == 1
        assert sources["mcp"] == 1
        assert sources["memory"] == 1

        # Verify chain is intact
        verdict = memory_trail.verify_chain()
        assert verdict.intact
        assert verdict.total_records == 5

        # Verify export includes all
        json_data = json.loads(memory_trail.export(format="json"))
        assert len(json_data) == 5
        exported_sources = {d["source"] for d in json_data}
        assert exported_sources == {"retriever", "tool", "agent", "mcp", "memory"}


# Fixtures (if not already defined)


@pytest.fixture
def memory_trail():
    """Fixture providing an in-memory ContextTrail for testing"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        trail = ContextTrail(storage_path=f.name)
        yield trail
        trail.close()
