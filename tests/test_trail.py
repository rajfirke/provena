from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from provena.models import ContextSource, ProvenanceMetadata
from provena.trail import ContextTrail


class TestContextTrailLog:
    def test_log_basic(self, memory_trail):
        record = memory_trail.log("hello world", source="retriever")
        assert record is not None
        assert record.entry.content_hash
        assert record.entry.source == ContextSource.RETRIEVER
        assert record.chain_hash
        assert record.provenance_result is not None
        assert record.provenance_result.status == "MISSING"

    def test_log_with_provenance(self, memory_trail):
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc),
        )
        record = memory_trail.log(
            "data",
            source="tool:api",
            source_name="pricing",
            provenance=prov,
        )
        assert record is not None
        assert record.provenance_result.status == "VALID"

    def test_log_with_metadata(self, memory_trail):
        record = memory_trail.log(
            "data",
            source="retriever",
            source_name="rag",
            metadata={"score": 0.95},
        )
        assert record is not None
        assert record.entry.metadata["score"] == 0.95

    def test_log_bytes(self, memory_trail):
        record = memory_trail.log(b"\x00\x01\x02", source="tool:binary")
        assert record is not None
        assert record.entry.content_type == "bytes"

    def test_sequential_chain_hashes(self, memory_trail):
        r1 = memory_trail.log("first", source="retriever")
        r2 = memory_trail.log("second", source="retriever")
        assert r1 is not None and r2 is not None
        assert r1.chain_hash != r2.chain_hash
        assert r2.previous_hash == r1.chain_hash

    def test_log_increments_ids(self, memory_trail):
        r1 = memory_trail.log("a", source="retriever")
        r2 = memory_trail.log("b", source="retriever")
        r3 = memory_trail.log("c", source="retriever")
        assert r1.id == 1
        assert r2.id == 2
        assert r3.id == 3


class TestContextTrailVerify:
    def test_verify_empty(self, memory_trail):
        verdict = memory_trail.verify_chain()
        assert verdict.intact
        assert verdict.total_records == 0

    def test_verify_single(self, memory_trail):
        memory_trail.log("test", source="retriever")
        verdict = memory_trail.verify_chain()
        assert verdict.intact
        assert verdict.total_records == 1

    def test_verify_multiple(self, memory_trail):
        for i in range(10):
            memory_trail.log(f"entry_{i}", source="retriever")
        verdict = memory_trail.verify_chain()
        assert verdict.intact
        assert verdict.total_records == 10

    def test_verify_detects_tamper(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            trail = ContextTrail(storage_path=db_path)
            for i in range(5):
                trail.log(f"entry_{i}", source="retriever")

            verdict = trail.verify_chain()
            assert verdict.intact

            conn = sqlite3.connect(db_path)
            conn.execute("UPDATE trail SET content_hash = 'TAMPERED' WHERE id = 3")
            conn.commit()
            conn.close()

            verdict = trail.verify_chain()
            assert not verdict.intact
            assert verdict.broken_at == 3
            trail.close()
        finally:
            os.unlink(db_path)

    def test_verify_signed_chain_rejects_wrong_key(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            trail_a = ContextTrail(storage_path=db_path, signing_key="key-a")
            for i in range(5):
                trail_a.log(f"entry_{i}", source="retriever")

            assert trail_a.verify_chain().intact
            trail_a.close()

            trail_b = ContextTrail(storage_path=db_path, signing_key="key-b")
            verdict = trail_b.verify_chain()
            assert not verdict.intact
            assert verdict.total_records == 5
            assert verdict.broken_at == 1
            trail_b.close()
        finally:
            os.unlink(db_path)


class TestContextTrailTrack:
    def test_track_sync_function(self, memory_trail):
        @memory_trail.track(source="retriever", source_name="search")
        def search(query):
            return f"result for {query}"

        result = search("test")
        assert result == "result for test"

        summary = memory_trail.summary()
        assert summary["total"] == 1

    def test_track_returns_list(self, memory_trail):
        @memory_trail.track(source="retriever", source_name="multi")
        def multi_search(query):
            return ["result1", "result2", "result3"]

        results = multi_search("test")
        assert len(results) == 3

        summary = memory_trail.summary()
        assert summary["total"] == 3

    def test_track_returns_dict(self, memory_trail):
        @memory_trail.track(source="tool:api")
        def get_data():
            return {"price": 99.99, "currency": "USD"}

        data = get_data()
        assert data["price"] == 99.99

        summary = memory_trail.summary()
        assert summary["total"] == 1

    def test_track_returns_none(self, memory_trail):
        @memory_trail.track(source="tool:api")
        def no_result():
            return None

        result = no_result()
        assert result is None

        summary = memory_trail.summary()
        assert summary["total"] == 0

    def test_track_with_content_extractor(self, memory_trail):
        @memory_trail.track(
            source="retriever",
            content_extractor=lambda x: [item["text"] for item in x],
        )
        def search(query):
            return [{"text": "doc1", "score": 0.9}, {"text": "doc2", "score": 0.8}]

        results = search("test")
        assert len(results) == 2

        summary = memory_trail.summary()
        assert summary["total"] == 2

    def test_track_preserves_function_name(self, memory_trail):
        @memory_trail.track(source="retriever")
        def my_function():
            """My docstring."""
            return "hello"

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_track_with_page_content(self, memory_trail):
        class MockDocument:
            def __init__(self, text):
                self.page_content = text
                self.metadata = {"source": "test.pdf"}

        @memory_trail.track(source="retriever")
        def search(query):
            return MockDocument("LangChain document content")

        doc = search("test")
        assert doc.page_content == "LangChain document content"
        assert memory_trail.summary()["total"] == 1

    def test_track_async_function(self, memory_trail):
        @memory_trail.track(source="retriever", source_name="async_search")
        async def async_search(query):
            return f"async result for {query}"

        result = asyncio.run(async_search("test"))
        assert result == "async result for test"
        assert memory_trail.summary()["total"] == 1


class TestContextTrailErrorHandling:
    def test_governance_error_does_not_crash(self):
        trail = ContextTrail(backend="memory")
        trail._backend = MagicMock()
        trail._backend.append.side_effect = RuntimeError("Storage failed")
        trail._backend.get_last.return_value = None

        record = trail.log("test", source="retriever")
        assert record is None
        assert trail.error_count == 1

    def test_strict_mode_raises(self):
        trail = ContextTrail(backend="memory", strict_mode=True)
        trail._backend = MagicMock()
        trail._backend.append.side_effect = RuntimeError("Storage failed")
        trail._backend.get_last.return_value = None

        with pytest.raises(RuntimeError, match="Storage failed"):
            trail.log("test", source="retriever")

    def test_on_error_callback(self):
        errors = []
        trail = ContextTrail(backend="memory", on_error=errors.append)
        trail._backend = MagicMock()
        trail._backend.append.side_effect = RuntimeError("oops")
        trail._backend.get_last.return_value = None

        trail.log("test", source="retriever")
        assert len(errors) == 1
        assert str(errors[0]) == "oops"

    def test_track_decorator_error_does_not_crash(self, memory_trail):
        memory_trail._backend = MagicMock()
        memory_trail._backend.append.side_effect = RuntimeError("Storage failed")

        @memory_trail.track(source="retriever")
        def search(query):
            return f"result for {query}"

        result = search("test")
        assert result == "result for test"


class TestContextTrailQuery:
    def test_query_all(self, memory_trail):
        memory_trail.log("a", source="retriever")
        memory_trail.log("b", source="tool:api")
        memory_trail.log("c", source="retriever")

        results = memory_trail.query()
        assert len(results) == 3

    def test_query_by_source_enum(self, memory_trail):
        memory_trail.log("a", source="retriever")
        memory_trail.log("b", source="tool:api")

        results = memory_trail.query(source=ContextSource.RETRIEVER)
        assert len(results) == 1

    def test_query_by_source_string(self, memory_trail):
        memory_trail.log("a", source="retriever")
        memory_trail.log("b", source="tool:api")

        results = memory_trail.query(source="retriever")
        assert len(results) == 1

    def test_query_limit(self, memory_trail):
        for i in range(10):
            memory_trail.log(f"entry_{i}", source="retriever")

        results = memory_trail.query(limit=3)
        assert len(results) == 3

    def test_query_by_governance_status(self, memory_trail):
        memory_trail.log("missing", source="retriever")
        memory_trail.log(
            "valid and fresh",
            source="retriever",
            provenance=ProvenanceMetadata(
                source_url="https://example.com",
                created_at=datetime.now(timezone.utc),
            ),
        )

        missing = memory_trail.query(provenance_status="MISSING")
        assert len(missing) == 1
        assert missing[0]["provenance_status"] == "MISSING"

        fresh = memory_trail.query(freshness_status="FRESH")
        assert len(fresh) == 1
        assert fresh[0]["freshness_status"] == "FRESH"


class TestContextTrailAnnotate:
    def test_annotate_record(self, memory_trail):
        memory_trail.log("test", source="retriever")
        ann_id = memory_trail.annotate(
            record_id=1,
            note="Reviewed and confirmed current",
            reviewer="jane.doe@company.com",
        )
        assert ann_id >= 1


class TestContextTrailSummary:
    def test_summary_empty(self, memory_trail):
        s = memory_trail.summary()
        assert s["total"] == 0

    def test_summary_with_records(self, memory_trail):
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc),
        )
        memory_trail.log("a", source="retriever")
        memory_trail.log("b", source="retriever", provenance=prov)
        memory_trail.log("c", source="tool:api")

        s = memory_trail.summary()
        assert s["total"] == 3
        assert s["provenance"]["MISSING"] == 2
        assert s["provenance"]["VALID"] == 1
        assert s["sources"]["retriever"] == 2
        assert s["sources"]["tool"] == 1


class TestContextTrailHealth:
    def test_health_healthy(self, memory_trail):
        h = memory_trail.health()
        assert h["status"] == "healthy"
        assert h["record_count"] == 0
        assert h["errors"] == 0

    def test_health_with_records(self, memory_trail):
        memory_trail.log("test", source="retriever")
        h = memory_trail.health()
        assert h["record_count"] == 1


class TestContextTrailExport:
    def test_export_json(self, memory_trail):
        memory_trail.log("test", source="retriever")
        exported = memory_trail.export(format="json")
        data = json.loads(exported)
        assert len(data) == 1
        assert data[0]["content_hash"]

    def test_export_csv(self, memory_trail):
        memory_trail.log("first", source="retriever", source_name="source_1")
        memory_trail.log("second", source="tool:api", source_name="source_2")

        exported = memory_trail.export(format="csv")
        rows = list(csv.reader(io.StringIO(exported)))

        assert rows[0] == [
            "id",
            "timestamp",
            "source",
            "source_name",
            "content_hash",
            "provenance_status",
            "freshness_status",
            "chain_hash",
        ]
        assert len(rows) == 3


class TestContextTrailSigning:
    def test_signed_trail(self):
        trail = ContextTrail(backend="memory", signing_key="test-secret")
        assert trail.is_signed

        trail.log("test", source="retriever")
        verdict = trail.verify_chain()
        assert verdict.intact

    def test_unsigned_trail(self, memory_trail):
        assert not memory_trail.is_signed

    def test_signing_key_from_env(self, monkeypatch):
        monkeypatch.setenv("PROVENA_SIGNING_KEY", "env-secret")
        trail = ContextTrail(backend="memory")
        assert trail.is_signed
        trail.close()


class TestContextTrailFreshness:
    def test_log_returns_freshness_result(self, memory_trail):
        record = memory_trail.log("hello world", source="retriever")
        assert record is not None
        assert record.freshness_result is not None
        assert record.freshness_result.status == "UNKNOWN"

    def test_fresh_content_with_provenance(self):
        trail = ContextTrail(backend="memory", max_age_days=90)
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        record = trail.log("data", source="retriever", provenance=prov)
        assert record is not None
        assert record.freshness_result.status == "FRESH"
        trail.close()

    def test_stale_content_with_provenance(self):
        trail = ContextTrail(backend="memory", max_age_days=30)
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        record = trail.log("data", source="retriever", provenance=prov)
        assert record is not None
        assert record.freshness_result.status == "STALE"
        trail.close()

    def test_stale_via_temporal_detection(self):
        trail = ContextTrail(backend="memory", max_age_days=90)
        record = trail.log(
            "This policy was last updated in January 2023.",
            source="retriever",
        )
        assert record is not None
        assert record.freshness_result.status == "STALE"
        trail.close()

    def test_freshness_in_summary(self):
        trail = ContextTrail(backend="memory", max_age_days=90)
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        trail.log("no provenance", source="retriever")
        trail.log("with provenance", source="retriever", provenance=prov)
        s = trail.summary()
        assert "freshness" in s
        assert s["freshness"].get("UNKNOWN", 0) >= 1
        assert s["freshness"].get("FRESH", 0) >= 1
        trail.close()

    def test_custom_max_age_days(self):
        trail = ContextTrail(backend="memory", max_age_days=7)
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        record = trail.log("data", source="retriever", provenance=prov)
        assert record is not None
        assert record.freshness_result.status == "STALE"
        trail.close()

    def test_config_dict_freshness(self):
        trail = ContextTrail(
            config={
                "storage": {"backend": "memory"},
                "freshness": {"max_age_days": 30, "temporal_detection": False},
            }
        )
        assert trail._freshness.max_age_days == 30
        trail.close()


class TestContextTrailConfig:
    def test_config_dict(self):
        trail = ContextTrail(
            config={
                "storage": {"backend": "memory"},
                "provenance": {"required_fields": ["author"]},
            }
        )
        assert trail._validator.required_fields == ("author",)
        trail.close()


class TestContextTrailContextManager:
    def test_context_manager(self):
        with ContextTrail(backend="memory") as trail:
            trail.log("test", source="retriever")
            assert trail.summary()["total"] == 1


class TestDisabledMode:
    def test_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("PROVENA_DISABLED", "1")
        from provena import trail as trail_module

        original = trail_module._DISABLED
        trail_module._DISABLED = True
        try:
            t = ContextTrail(storage_path="should_not_be_created.db")
            assert isinstance(t._backend, type(ContextTrail(backend="memory")._backend))
            t.close()
        finally:
            trail_module._DISABLED = original