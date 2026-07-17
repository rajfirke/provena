# Provena

**Context governance for agentic AI systems.**

Your AI agent just made a decision based on data from 6 different sources.
Can you tell me which ones? Can you prove the data wasn't tampered with?
Can you verify it was still current?

Provena adds tamper-evident audit trails to any AI agent's context pipeline — in 3 lines of Python.

```python
from provena import ContextTrail

trail = ContextTrail()

@trail.track(source="retriever")
def search(query):
    return retriever.search(query)
```

Every call to `search()` is now logged with a SHA-256 content hash, provenance validation,
and a hash-chained audit trail that detects tampering.

## Why Provena?

> **AGT governs what agents DO. Guardrails AI governs what agents SAY. Provena governs what agents KNOW.**

No existing tool governs the context input layer. Provena fills this gap with:

- **Tamper-evident audit trails** — SHA-256 hash-chained (Merkle-style) logging with optional HMAC signing
- **Provenance validation** — Verify that context carries proper source metadata (VALID / MISSING / INCOMPLETE)
- **Freshness checking** — Detect stale context via metadata timestamps and regex temporal detection (FRESH / STALE / UNKNOWN)
- **Any context source** — RAG retrievers, tool outputs, agent messages, memory recalls, MCP resources
- **Sub-1ms overhead** — Pure Python, no ML models, no downloads
- **Zero dependencies** — Core library uses only the Python standard library

## Install

```bash
pip install provena              # core (zero dependencies)
pip install provena[cli]         # + CLI tools (click, rich)
pip install provena[otel]        # + OpenTelemetry export
pip install provena[langchain]   # + LangChain adapter
pip install provena[llamaindex]  # + LlamaIndex adapter
pip install provena[all]         # everything
```

## Architecture

```
Your Application
|
|  Retriever ---+
|  Tool Call ---+
|  Agent Msg ---+---> ContextTrail ---> LLM Context Window
|  Memory    ---+        |
|  MCP       ---+        |
|                  +-----+------------------+
|                  | ProvenanceValidator     |
|                  | FreshnessChecker        |
|                  | HashChain (SHA-256)     |
|                  | SQLite Backend          |
|                  | OTel Exporter           |
|                  +------------------------+
```

## Compliance

Provena maps directly to EU AI Act requirements:

| Article | Requirement | Provena Feature |
|---------|------------|-----------------|
| Art. 10 | Data lineage | Provenance validation for every context input |
| Art. 12 | Tamper-evident logging | SHA-256 hash-chained audit trail with HMAC signing |
| Art. 13 | Transparency | `trail.summary()` and source tracking |
| Art. 14 | Human oversight | `trail.annotate()` for reviewer decisions |

Also addresses [OWASP ASI06](compliance/owasp-asi06.md) (Memory & Context Poisoning).

## Next Steps

- [Getting Started](getting-started.md) — Install, first trail, verify chain in 5 minutes
- [Guide](guide/tracking.md) — Deep-dive into tracking, provenance, freshness, and verification
- [Integrations](integrations/langchain.md) — LangChain, LlamaIndex, OpenTelemetry, CLI
- [API Reference](api/provena/index.md) — Auto-generated from docstrings
