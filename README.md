# Provena

[![CI](https://github.com/rajfirke/provena/actions/workflows/ci.yml/badge.svg)](https://github.com/rajfirke/provena/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/provena)](https://pypi.org/project/provena/)
[![Downloads](https://img.shields.io/pypi/dm/provena)](https://pypi.org/project/provena/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

**Context governance for agentic AI systems.** (MVP)

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
- **Sub-1ms overhead** — Pure Python, no ML models, no ONNX, no model downloads
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

## Quick Start

```python
from provena import ContextTrail, ProvenanceMetadata
from datetime import datetime, timezone

trail = ContextTrail(storage_path="audit.db")

# Track any function that produces context
@trail.track(source="retriever")
def search(query):
    return retriever.search(query)

@trail.track(source="tool:pricing_api")
def get_price(product_id):
    return api.get(f"/price/{product_id}")

# Manual logging with provenance metadata
trail.log(
    content="The enterprise plan costs $499/month.",
    source="tool:pricing_api",
    provenance=ProvenanceMetadata(
        source_url="https://api.example.com/pricing",
        created_at=datetime.now(timezone.utc),
    ),
)

# Verify the audit trail hasn't been tampered with
verdict = trail.verify_chain()
print(f"Chain intact: {verdict.intact}")
print(f"Total records: {verdict.total_records}")
```

## CLI

Install with `pip install provena[cli]`, then:

```bash
# Verify hash chain integrity
provena --db audit.db verify
# PASS — Chain intact (42 records verified)

# Query the audit log
provena --db audit.db audit --source retriever --format json

# Generate a governance report
provena --db audit.db report --format text

# Quick summary
provena --db audit.db summary
```

For HMAC-signed trails, pass `--signing-key` or set `PROVENA_SIGNING_KEY`.

## Integrations

### LangChain

```python
from provena.integrations.langchain import ProvenaCallback

chain = RetrievalQA.from_chain_type(
    llm=llm,
    retriever=retriever,
    callbacks=[ProvenaCallback(trail=trail)],
)
```

### LlamaIndex

```python
from provena.integrations.llamaindex import ProvenaPostprocessor

query_engine = index.as_query_engine(
    node_postprocessors=[ProvenaPostprocessor(trail=trail)]
)
```

### OpenTelemetry

```python
trail = ContextTrail(
    storage_path="audit.db",
    otel_enabled=True,
    otel_service_name="my-agent",
)
# Every log() call now emits an OTel span with governance attributes
```

## Architecture

```
Your Application
│
│  Retriever ──┐
│  Tool Call ──┤
│  Agent Msg ──┼──► ContextTrail ──► LLM Context Window
│  Memory    ──┤        │
│  MCP       ──┘        │
│                  ┌─────┴──────────────┐
│                  │ ProvenanceValidator │
│                  │ FreshnessChecker    │
│                  │ HashChain (SHA-256) │
│                  │ SQLite Backend      │
│                  │ OTel Exporter       │
│                  └────────────────────┘
```

## Compliance

Provena maps directly to EU AI Act requirements (enforcement: August 2, 2026):

| Article | Requirement | Provena Feature |
|---------|------------|-----------------|
| Art. 10 | Data lineage | Provenance validation for every context input |
| Art. 12 | Tamper-evident logging | SHA-256 hash-chained audit trail with HMAC signing |
| Art. 13 | Transparency | `trail.summary()` and source tracking |
| Art. 14 | Human oversight | `trail.annotate()` for reviewer decisions |

Also addresses **OWASP ASI06** (Memory & Context Poisoning).

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, architecture guide, and PR process.

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before participating.

## License

[Apache 2.0](LICENSE)
