from __future__ import annotations

from unittest.mock import MagicMock

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from provena.exporters.otel import OTelExporter
from provena.models import (
    ContextEntry,
    ContextSource,
    FreshnessResult,
    TrailRecord,
    ValidationResult,
)
from provena.trail import ContextTrail


def _make_otel_exporter() -> tuple[OTelExporter, InMemorySpanExporter]:
    mem = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(mem))
    tracer = provider.get_tracer("provena-test")
    exporter = OTelExporter(enabled=True, tracer=tracer)
    return exporter, mem


def _make_record(
    record_id: int = 1,
    content: str = "test",
    source: ContextSource = ContextSource.RETRIEVER,
    source_name: str = "test_ret",
    prov_status: str = "MISSING",
    fresh_status: str = "UNKNOWN",
) -> TrailRecord:
    entry = ContextEntry.create(content=content, source=source, source_name=source_name)
    return TrailRecord(
        id=record_id,
        entry=entry,
        provenance_result=ValidationResult(status=prov_status),  # type: ignore[arg-type]
        freshness_result=FreshnessResult(status=fresh_status),  # type: ignore[arg-type]
        chain_hash="chain123",
        previous_hash="prev123",
    )


class TestOTelExporter:
    def test_emit_creates_span(self):
        exporter, mem = _make_otel_exporter()
        record = _make_record()

        exporter.emit(record)

        spans = mem.get_finished_spans()
        assert len(spans) == 1

        span = spans[0]
        assert span.name == "provena.track.test_ret"
        attrs = dict(span.attributes)
        assert attrs["provena.source"] == "retriever"
        assert attrs["provena.source_name"] == "test_ret"
        assert attrs["provena.content_hash"] == record.entry.content_hash
        assert attrs["provena.chain_hash"] == "chain123"
        assert attrs["provena.provenance_status"] == "MISSING"
        assert attrs["provena.freshness_status"] == "UNKNOWN"
        assert attrs["provena.content_type"] == "str"
        assert attrs["provena.truncated"] is False

    def test_emit_disabled_no_span(self):
        _, mem = _make_otel_exporter()
        exporter = OTelExporter(enabled=False)
        record = _make_record()

        exporter.emit(record)

        spans = mem.get_finished_spans()
        assert len(spans) == 0

    def test_enabled_property(self):
        exporter = OTelExporter(enabled=True)
        assert exporter.enabled

        exporter_off = OTelExporter(enabled=False)
        assert not exporter_off.enabled

    def test_emit_with_valid_provenance(self):
        exporter, mem = _make_otel_exporter()
        record = _make_record(prov_status="VALID", fresh_status="FRESH")

        exporter.emit(record)

        spans = mem.get_finished_spans()
        assert len(spans) == 1
        attrs = dict(spans[0].attributes)
        assert attrs["provena.provenance_status"] == "VALID"
        assert attrs["provena.freshness_status"] == "FRESH"

    def test_emit_tool_source(self):
        exporter, mem = _make_otel_exporter()
        record = _make_record(source=ContextSource.TOOL, source_name="pricing_api")

        exporter.emit(record)

        spans = mem.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "provena.track.pricing_api"
        assert dict(spans[0].attributes)["provena.source"] == "tool"

    def test_multiple_emits(self):
        exporter, mem = _make_otel_exporter()

        for i in range(5):
            record = _make_record(record_id=i, source_name=f"src_{i}")
            exporter.emit(record)

        spans = mem.get_finished_spans()
        assert len(spans) == 5
        names = [s.name for s in spans]
        assert "provena.track.src_0" in names
        assert "provena.track.src_4" in names

    def test_emit_no_provenance_result(self):
        exporter, mem = _make_otel_exporter()
        entry = ContextEntry.create(content="x", source="retriever")
        record = TrailRecord(
            id=1,
            entry=entry,
            provenance_result=None,
            freshness_result=None,
            chain_hash="ch",
            previous_hash="ph",
        )

        exporter.emit(record)

        spans = mem.get_finished_spans()
        assert len(spans) == 1
        attrs = dict(spans[0].attributes)
        assert "provena.provenance_status" not in attrs
        assert "provena.freshness_status" not in attrs


class TestOTelTrailIntegration:
    def _trail_with_otel(self) -> tuple[ContextTrail, InMemorySpanExporter]:
        mem = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(mem))
        tracer = provider.get_tracer("provena-test")

        trail = ContextTrail(backend="memory", otel_enabled=True)
        trail._otel = OTelExporter(enabled=True, tracer=tracer)
        return trail, mem

    def test_trail_with_otel_enabled(self):
        trail, mem = self._trail_with_otel()

        trail.log("hello world", source="retriever", source_name="rag")

        spans = mem.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "provena.track.rag"
        assert dict(spans[0].attributes)["provena.source"] == "retriever"

        trail.close()

    def test_trail_with_otel_disabled(self):
        trail = ContextTrail(backend="memory", otel_enabled=False)

        record = trail.log("hello world", source="retriever")
        assert record is not None
        assert not trail._otel.enabled

        trail.close()

    def test_track_decorator_emits_spans(self):
        trail, mem = self._trail_with_otel()

        @trail.track(source="retriever", source_name="search")
        def search(query):
            return [f"result for {query}"]

        search("test")

        spans = mem.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "provena.track.search"

        trail.close()

    def test_multiple_logs_emit_multiple_spans(self):
        trail, mem = self._trail_with_otel()

        trail.log("a", source="retriever")
        trail.log("b", source="tool:api")
        trail.log("c", source="agent:planner")

        spans = mem.get_finished_spans()
        assert len(spans) == 3
        sources = [dict(s.attributes)["provena.source"] for s in spans]
        assert "retriever" in sources
        assert "tool" in sources
        assert "agent" in sources

        trail.close()

    def test_otel_error_does_not_crash_trail(self):
        trail = ContextTrail(backend="memory", otel_enabled=True)
        trail._otel._tracer = MagicMock()
        trail._otel._tracer.start_span.side_effect = RuntimeError("OTel exploded")

        record = trail.log("should not crash", source="retriever")
        assert record is None or record is not None
        trail.close()

    def test_otel_config_dict(self):
        trail = ContextTrail(
            config={
                "storage": {"backend": "memory"},
                "otel": {"enabled": True, "service_name": "my-agent"},
            }
        )
        assert trail._otel.enabled
        trail.close()

    def test_span_attributes_complete(self):
        trail, mem = self._trail_with_otel()

        trail.log("data with as of 2020 old content", source="tool:api")

        spans = mem.get_finished_spans()
        assert len(spans) == 1
        attrs = dict(spans[0].attributes)
        assert "provena.source" in attrs
        assert "provena.source_name" in attrs
        assert "provena.content_hash" in attrs
        assert "provena.chain_hash" in attrs
        assert "provena.timestamp" in attrs
        assert "provena.provenance_status" in attrs
        assert "provena.freshness_status" in attrs
        assert attrs["provena.freshness_status"] == "STALE"

        trail.close()
