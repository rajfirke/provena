# OpenTelemetry

Provena can emit OpenTelemetry spans for every context governance event,
letting you visualize and monitor your audit trail alongside the rest of
your application's distributed traces.

## Installation

```bash
pip install provena[otel]
```

This installs `opentelemetry-api>=1.20` as a dependency. You also need an
OpenTelemetry SDK and exporter for your backend (Jaeger, OTLP, etc.).

## Enabling OpenTelemetry

### Constructor parameters

```python
from provena import ContextTrail

trail = ContextTrail(
    otel_enabled=True,
    otel_service_name="my-agent",
)
```

### Config dict

```python
trail = ContextTrail(
    config={
        "storage": {"backend": "sqlite", "path": "audit.db"},
        "otel": {
            "enabled": True,
            "service_name": "my-agent",
        },
    }
)
```

## Span format

Each call to `trail.log()` (or each entry logged by an integration callback)
emits a single span with the following name pattern:

```text
provena.track.<source_name>
```

For example, a retriever source named `"rag"` produces the span name
`provena.track.rag`. A tool source named `"pricing_api"` produces
`provena.track.pricing_api`.

## Span attributes

Every span includes these attributes:

| Attribute | Type | Description |
|---|---|---|
| `provena.source` | `string` | Source type enum value (`retriever`, `tool`, `agent`, etc.) |
| `provena.source_name` | `string` | Human-readable source name |
| `provena.content_hash` | `string` | SHA-256 hex digest of the content |
| `provena.chain_hash` | `string` | This record's hash chain position |
| `provena.timestamp` | `string` | ISO 8601 timestamp of when the entry was recorded |
| `provena.content_type` | `string` | Content type (`str`, `bytes`, or `json`) |
| `provena.truncated` | `bool` | Whether the content was truncated to fit size limits |

These attributes are added conditionally when validation results are available:

| Attribute | Type | Description |
|---|---|---|
| `provena.provenance_status` | `string` | `VALID`, `MISSING`, or `INCOMPLETE` |
| `provena.freshness_status` | `string` | `FRESH`, `STALE`, or `UNKNOWN` |

## Example with Jaeger/OTLP exporter

A complete setup that sends Provena spans to a Jaeger instance via OTLP:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)

from provena import ContextTrail

# --- Configure the OTel SDK ---
resource = Resource.create({"service.name": "my-agent"})
provider = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter(
    endpoint="http://localhost:4317",  # Jaeger OTLP gRPC endpoint
    insecure=True,
)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)

# --- Create the trail with OTel enabled ---
trail = ContextTrail(
    storage_path="audit.db",
    otel_enabled=True,
    otel_service_name="my-agent",
)

# --- Log context entries (spans are emitted automatically) ---
trail.log("retrieved document content", source="retriever", source_name="rag")
trail.log("tool API response", source="tool:pricing_api")
trail.log("agent memory recall", source="agent:planner")

# --- Flush and clean up ---
trail.close()
provider.shutdown()
```

After running the above, you can view the spans in Jaeger at
`http://localhost:16686`, searching for service `my-agent`.

!!! tip "In-memory testing"
    For unit tests, use `InMemorySpanExporter` from the OTel SDK to capture
    and assert on emitted spans without a running collector:

    ```python
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    from provena.exporters.otel import OTelExporter

    mem = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(mem))
    tracer = provider.get_tracer("provena-test")

    exporter = OTelExporter(enabled=True, tracer=tracer)
    # ... emit records, then assert:
    spans = mem.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "provena.track.rag"
    ```

## Non-fatal error handling

OTel errors never crash the trail. If the OpenTelemetry SDK raises an
exception during span creation or export, Provena catches it silently and
continues logging to the audit database:

```python
trail = ContextTrail(backend="memory", otel_enabled=True)

# Even if OTel is misconfigured or the collector is down,
# trail.log() still succeeds and returns a valid record:
record = trail.log("important context", source="retriever")
assert record is not None
assert trail.summary()["total"] == 1
```

!!! warning "Silent failures"
    Because OTel errors are suppressed, check your OTel collector logs if
    spans are not appearing. Provena logs a debug-level message via the
    `provena` logger when an OTel emit fails.

## Combining with framework integrations

OTel works alongside the LangChain and LlamaIndex integrations. Enable OTel
on the trail, and every entry logged by `ProvenaCallback` or
`ProvenaPostprocessor` will also emit a span:

```python
from provena import ContextTrail
from provena.integrations.langchain import ProvenaCallback

trail = ContextTrail(
    storage_path="audit.db",
    otel_enabled=True,
    otel_service_name="rag-pipeline",
)

callback = ProvenaCallback(trail=trail)

# Every document retrieved by LangChain will:
# 1. Be logged to the SQLite audit trail
# 2. Emit an OTel span named "provena.track.langchain"
chain = RetrievalQA.from_chain_type(
    llm=llm,
    retriever=retriever,
    callbacks=[callback],
)
chain.invoke({"query": "What are our SLA commitments?"})

trail.close()
```

## OTel without the extra

If `opentelemetry-api` is not installed, the `OTelExporter` internally
marks itself as disabled and all `emit()` calls become no-ops. You can
safely set `otel_enabled=True` in environments where OTel is not available
--- no `ImportError` will be raised at runtime.
