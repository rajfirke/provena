from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from provena.models import (
    ChainVerdict,
    ContextEntry,
    ContextSource,
    FreshnessResult,
    ProvenanceMetadata,
    TrailRecord,
    ValidationResult,
    _parse_source,
    _prepare_content,
)


class TestContextSource:
    def test_enum_values(self):
        assert ContextSource.RETRIEVER == "retriever"
        assert ContextSource.TOOL == "tool"
        assert ContextSource.AGENT == "agent"
        assert ContextSource.MEMORY == "memory"
        assert ContextSource.MCP == "mcp"
        assert ContextSource.CUSTOM == "custom"

    def test_string_comparison(self):
        assert ContextSource.RETRIEVER == "retriever"
        assert ContextSource("tool") == ContextSource.TOOL


class TestProvenanceMetadata:
    def test_empty(self):
        pm = ProvenanceMetadata()
        assert pm.source_url is None
        assert pm.author is None
        assert pm.created_at is None
        assert pm.version is None
        assert pm.extra == {}

    def test_full(self):
        now = datetime.now(timezone.utc)
        pm = ProvenanceMetadata(
            source_url="https://example.com",
            author="Alice",
            created_at=now,
            version="1.0",
            extra={"tag": "test"},
        )
        assert pm.source_url == "https://example.com"
        assert pm.created_at == now

    def test_to_dict_round_trip(self):
        now = datetime.now(timezone.utc)
        pm = ProvenanceMetadata(
            source_url="https://example.com",
            author="Bob",
            created_at=now,
            version="2.0",
        )
        d = pm.to_dict()
        assert d["source_url"] == "https://example.com"
        assert d["author"] == "Bob"

        restored = ProvenanceMetadata.from_dict(d)
        assert restored.source_url == pm.source_url
        assert restored.author == pm.author
        assert restored.version == pm.version

    def test_to_dict_empty_fields_omitted(self):
        pm = ProvenanceMetadata()
        d = pm.to_dict()
        assert d == {}

    def test_frozen(self):
        pm = ProvenanceMetadata(source_url="https://example.com")
        import pytest

        with pytest.raises(AttributeError):
            pm.source_url = "other"  # type: ignore[misc]


class TestValidationResult:
    def test_valid(self):
        vr = ValidationResult(status="VALID")
        assert vr.status == "VALID"
        assert vr.missing_fields == ()

    def test_missing(self):
        vr = ValidationResult(
            status="MISSING",
            missing_fields=("source_url", "created_at"),
            details="No provenance",
        )
        assert vr.missing_fields == ("source_url", "created_at")


class TestContextEntry:
    def test_create_string(self):
        entry = ContextEntry.create(
            content="Hello world",
            source=ContextSource.RETRIEVER,
            source_name="my_retriever",
        )
        expected_hash = hashlib.sha256(b"Hello world").hexdigest()
        assert entry.content_hash == expected_hash
        assert entry.source == ContextSource.RETRIEVER
        assert entry.source_name == "my_retriever"
        assert entry.content_type == "str"
        assert not entry.truncated

    def test_create_bytes(self):
        data = b"\x00\x01\x02\x03"
        entry = ContextEntry.create(
            content=data,
            source=ContextSource.TOOL,
            source_name="binary_tool",
        )
        expected_hash = hashlib.sha256(data).hexdigest()
        assert entry.content_hash == expected_hash
        assert entry.content_type == "bytes"

    def test_create_with_string_source(self):
        entry = ContextEntry.create(
            content="test",
            source="retriever",
            source_name="my_ret",
        )
        assert entry.source == ContextSource.RETRIEVER
        assert entry.source_name == "my_ret"

    def test_create_with_colon_source(self):
        entry = ContextEntry.create(
            content="test",
            source="tool:pricing_api",
        )
        assert entry.source == ContextSource.TOOL
        assert entry.source_name == "pricing_api"

    def test_create_unknown_source(self):
        entry = ContextEntry.create(
            content="test",
            source="unknown_source",
        )
        assert entry.source == ContextSource.CUSTOM
        assert entry.source_name == "unknown_source"

    def test_truncation(self):
        content = "x" * 200
        entry = ContextEntry.create(
            content=content,
            source=ContextSource.RETRIEVER,
            source_name="test",
            max_content_bytes=100,
        )
        assert entry.truncated
        expected_hash = hashlib.sha256(b"x" * 100).hexdigest()
        assert entry.content_hash == expected_hash

    def test_no_truncation_under_limit(self):
        content = "short"
        entry = ContextEntry.create(
            content=content,
            source=ContextSource.RETRIEVER,
            source_name="test",
            max_content_bytes=100,
        )
        assert not entry.truncated

    def test_with_provenance(self):
        prov = ProvenanceMetadata(source_url="https://api.example.com")
        entry = ContextEntry.create(
            content="data",
            source=ContextSource.TOOL,
            source_name="api",
            provenance=prov,
        )
        assert entry.provenance is not None
        assert entry.provenance.source_url == "https://api.example.com"

    def test_with_metadata(self):
        entry = ContextEntry.create(
            content="data",
            source=ContextSource.RETRIEVER,
            source_name="test",
            metadata={"score": 0.95},
        )
        assert entry.metadata["score"] == 0.95

    def test_to_dict(self):
        entry = ContextEntry.create(
            content="hello",
            source=ContextSource.RETRIEVER,
            source_name="test",
        )
        d = entry.to_dict()
        assert d["content_hash"] == entry.content_hash
        assert d["source"] == "retriever"
        assert d["source_name"] == "test"
        assert "timestamp" in d

    def test_deterministic_hash(self):
        content = "deterministic test"
        h1 = ContextEntry.create(
            content=content, source="retriever", source_name="a"
        ).content_hash
        h2 = ContextEntry.create(
            content=content, source="retriever", source_name="b"
        ).content_hash
        assert h1 == h2

    def test_frozen(self):
        entry = ContextEntry.create(content="test", source="retriever")
        import pytest

        with pytest.raises(AttributeError):
            entry.content_hash = "tampered"  # type: ignore[misc]


class TestFreshnessResult:
    def test_fresh(self):
        fr = FreshnessResult(status="FRESH", details="10 days old")
        assert fr.status == "FRESH"
        assert fr.detected_date is None

    def test_stale_with_date(self):
        dt = datetime(2023, 1, 15, tzinfo=timezone.utc)
        fr = FreshnessResult(status="STALE", details="old", detected_date=dt)
        assert fr.detected_date == dt

    def test_unknown(self):
        fr = FreshnessResult(status="UNKNOWN")
        assert fr.status == "UNKNOWN"


class TestTrailRecord:
    def test_to_dict(self):
        entry = ContextEntry.create(
            content="hello", source=ContextSource.RETRIEVER, source_name="test"
        )
        vr = ValidationResult(status="VALID")
        fr = FreshnessResult(status="FRESH", details="5 days old")
        record = TrailRecord(
            id=1,
            entry=entry,
            provenance_result=vr,
            freshness_result=fr,
            chain_hash="abc123",
            previous_hash="genesis",
        )
        d = record.to_dict()
        assert d["id"] == 1
        assert d["chain_hash"] == "abc123"
        assert d["provenance_result"]["status"] == "VALID"
        assert d["freshness_result"]["status"] == "FRESH"

    def test_to_dict_no_freshness(self):
        entry = ContextEntry.create(
            content="hello", source=ContextSource.RETRIEVER, source_name="test"
        )
        record = TrailRecord(
            id=1,
            entry=entry,
            provenance_result=None,
            freshness_result=None,
            chain_hash="abc123",
            previous_hash="genesis",
        )
        d = record.to_dict()
        assert "freshness_result" not in d
        assert "provenance_result" not in d


class TestChainVerdict:
    def test_intact(self):
        cv = ChainVerdict(intact=True, total_records=10)
        assert cv.intact
        assert cv.broken_at is None

    def test_broken(self):
        cv = ChainVerdict(intact=False, total_records=10, broken_at=5)
        assert not cv.intact
        assert cv.broken_at == 5


class TestParseSource:
    def test_enum_input(self):
        src, name = _parse_source(ContextSource.RETRIEVER, "my_ret")
        assert src == ContextSource.RETRIEVER
        assert name == "my_ret"

    def test_enum_no_name(self):
        src, name = _parse_source(ContextSource.TOOL, "")
        assert src == ContextSource.TOOL
        assert name == "tool"

    def test_string_simple(self):
        src, name = _parse_source("retriever", "")
        assert src == ContextSource.RETRIEVER
        assert name == "retriever"

    def test_string_with_colon(self):
        src, name = _parse_source("tool:weather_api", "")
        assert src == ContextSource.TOOL
        assert name == "weather_api"

    def test_string_with_colon_name_override(self):
        src, name = _parse_source("tool:weather_api", "custom_name")
        assert src == ContextSource.TOOL
        assert name == "custom_name"


class TestPrepareContent:
    def test_string(self):
        content_bytes, ctype, trunc = _prepare_content("hello", 65536)
        assert content_bytes == b"hello"
        assert ctype == "str"
        assert not trunc

    def test_bytes(self):
        content_bytes, ctype, _trunc = _prepare_content(b"\x00\x01", 65536)
        assert content_bytes == b"\x00\x01"
        assert ctype == "bytes"

    def test_truncation(self):
        content_bytes, _ctype, trunc = _prepare_content("x" * 200, 100)
        assert len(content_bytes) == 100
        assert trunc
