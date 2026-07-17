"""OpenTelemetry span exporter for governance events."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from provena.models import TrailRecord

try:
    from opentelemetry import trace

    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False


class OTelExporter:
    """Emits OpenTelemetry spans for each context governance event.

    Requires the ``opentelemetry-api`` package. When disabled or when OTel
    is not installed, all methods are safe no-ops.
    """

    def __init__(
        self,
        enabled: bool = True,
        service_name: str = "provena",
        version: str = "",
        tracer: Any = None,
    ) -> None:
        self._enabled = enabled and _HAS_OTEL
        self._tracer: Any = tracer
        if self._enabled and self._tracer is None:
            self._tracer = trace.get_tracer(service_name, version or None)

    @property
    def enabled(self) -> bool:
        """Whether OTel export is active."""
        return self._enabled

    def emit(self, record: TrailRecord) -> None:
        """Emit a span for the given trail record."""
        if not self._enabled or self._tracer is None:
            return

        entry = record.entry
        attributes: dict[str, str | int | bool] = {
            "provena.source": entry.source.value,
            "provena.source_name": entry.source_name,
            "provena.content_hash": entry.content_hash,
            "provena.chain_hash": record.chain_hash,
            "provena.timestamp": entry.timestamp.isoformat(),
            "provena.content_type": entry.content_type,
            "provena.truncated": entry.truncated,
        }

        if record.provenance_result:
            attributes["provena.provenance_status"] = record.provenance_result.status
        if record.freshness_result:
            attributes["provena.freshness_status"] = record.freshness_result.status

        span = self._tracer.start_span(
            name=f"provena.track.{entry.source_name}",
            attributes=attributes,
        )
        import contextlib

        with contextlib.suppress(Exception):
            span.end()
