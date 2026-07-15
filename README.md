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
- **Provenance validation** — Verify that context carries proper source metadata
- **Any context source** — RAG retrievers, tool outputs, agent messages, memory, MCP resources
- **Sub-1ms overhead** — Pure Python, no ML models, no ONNX, no model downloads
- **Zero dependencies** — Core library uses only the Python standard library

## Install

```bash
pip install provena
```

## Quick Start

```python
from provena import ContextTrail, ProvenanceMetadata

trail = ContextTrail(storage_path="audit.db")

# Track any function that produces context
@trail.track(source="retriever")
def search(query):
    return retriever.search(query)

@trail.track(source="tool:pricing_api")
def get_price(product_id):
    return api.get(f"/price/{product_id}")

# Verify the audit trail hasn't been tampered with
verdict = trail.verify_chain()
print(f"Chain intact: {verdict.intact}")
print(f"Total records: {verdict.total_records}")
```

## Compliance

Provena maps directly to EU AI Act requirements:

| Article | Requirement | Provena Feature |
|---------|------------|-----------------|
| Art. 10 | Data lineage | Provenance validation |
| Art. 12 | Tamper-evident logging | SHA-256 hash-chained audit trail |
| Art. 13 | Transparency | Source tracking with `trail.explain()` |
| Art. 14 | Human oversight | `trail.annotate()` for reviewer decisions |

Also addresses **OWASP ASI06** (Memory & Context Poisoning).

## License

Apache 2.0
