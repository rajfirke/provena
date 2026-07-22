# Provena

[![CI](https://github.com/rajfirke/provena/actions/workflows/ci.yml/badge.svg)](https://github.com/rajfirke/provena/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/provena)](https://pypi.org/project/provena/)
[![Downloads](https://static.pepy.tech/badge/provena/month)](https://pepy.tech/projects/provena)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Docs](https://img.shields.io/badge/docs-rajfirke.github.io%2Fprovena-blue)](https://rajfirke.github.io/provena)

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
- **Policy enforcement** — Block, warn, or log governance violations with configurable rules
- **Multi-agent governance** — Aggregate and query across multiple agent trails with handoff tracking
- **Any context source** — RAG retrievers, tool outputs, agent messages, memory recalls, MCP resources
- **Sub-1ms overhead** — Pure Python, no ML models, no downloads
- **Zero core dependencies** — Core library uses only the Python standard library

## Install

```bash
pip install provena                # core (zero dependencies)
pip install provena[cli]           # + CLI tools (click, rich)
pip install provena[otel]          # + OpenTelemetry export
pip install provena[postgres]      # + PostgreSQL backend
pip install provena[mcp]           # + MCP server for governance-aware agents
pip install provena[pdf]           # + PDF compliance reports
pip install provena[yaml]          # + YAML config file support
pip install provena[all]           # core + cli + otel + postgres + mcp + pdf + yaml
```

Framework adapters (install individually):

```bash
pip install provena[langchain]     # LangChain callback
pip install provena[llamaindex]    # LlamaIndex postprocessor
pip install provena[crewai]        # CrewAI event listener
pip install provena[autogen]       # AutoGen hook
pip install provena[openai-agents] # OpenAI Agents SDK hooks
pip install provena[google-adk]    # Google ADK callbacks
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

## Policy Enforcement

Move from observe-only to enforce. Block stale or unverified context before it reaches the LLM:

```python
from provena import ContextTrail, freshness_check, provenance_check, EnforcementLevel

trail = ContextTrail(
    storage_path="audit.db",
    policies=[
        provenance_check(status="MISSING", enforcement=EnforcementLevel.BLOCK),
        freshness_check(status="STALE", enforcement=EnforcementLevel.WARN),
    ],
)
```

Three enforcement levels: `LOG` (record only), `WARN` (callback + pass through), `BLOCK` (raise `PolicyViolation`). Blocked entries are still logged for compliance — the audit trail shows what was rejected and why.

## Multi-Agent Governance

Aggregate governance across multiple agents with handoff tracking:

```python
from provena import ContextTrail, TrailAggregator

researcher = ContextTrail(storage_path="researcher.db")
writer = ContextTrail(storage_path="writer.db")

agg = TrailAggregator()
agg.add(researcher, label="researcher")
agg.add(writer, label="writer")

# Record agent-to-agent handoffs
agg.record_handoff(from_label="researcher", to_label="writer", record_id=5)

# Query across all agents
summary = agg.summary()
gaps = agg.detect_gaps()  # find missing provenance, broken chains, unlinked handoffs
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

# Retention management
provena --db audit.db retain --max-age 180 --dry-run

# Start MCP server for governance-aware agents
provena mcp serve --db audit.db

# Migrate between backends
provena migrate --from audit.db --to postgresql://localhost/provena
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

### CrewAI

```python
from provena.integrations.crewai import ProvenaCrewListener

listener = ProvenaCrewListener(trail=trail)
crew = Crew(agents=[...], tasks=[...])
crew.kickoff()
```

### OpenAI Agents SDK

```python
from provena.integrations.openai_agents import ProvenaRunHooks

result = Runner.run(agent, input="...", hooks=ProvenaRunHooks(trail))
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

### Configuration Files

```bash
# TOML (zero dependencies on Python 3.11+)
trail = ContextTrail(config="provena.toml")

# YAML (requires provena[yaml])
trail = ContextTrail(config="trail.yaml")
```

## Architecture

```
Your Application
|
|  Retriever ---+
|  Tool Call ---+
|  Agent Msg ---+---> ContextTrail ------> LLM Context Window
|  Memory    ---+        |
|  MCP       ---+        |
|                  +-----+----------------------+
|                  | ProvenanceValidator         |
|                  | FreshnessChecker            |
|                  | PolicyEngine (block/warn)   |
|                  | HashChain (SHA-256 / HMAC)  |
|                  | WriteBuffer (10K+ entries/s)|
|                  | SQLite / PostgreSQL Backend |
|                  | OTel Exporter              |
|                  +----------------------------+
|
|  TrailAggregator (multi-agent)
|  RetentionEngine (lifecycle)
|  ComplianceReport (EU AI Act / OWASP)
|  MCP Server (governance-aware agents)
```

## Compliance

Provena maps directly to EU AI Act requirements:

| Article | Requirement | Provena Feature |
|---------|------------|-----------------|
| Art. 9  | Risk management | Policy engine with configurable enforcement |
| Art. 10 | Data lineage | Provenance validation for every context input |
| Art. 12 | Tamper-evident logging | SHA-256 hash-chained audit trail with HMAC signing |
| Art. 13 | Transparency | `trail.summary()`, source tracking, compliance reports |
| Art. 14 | Human oversight | `trail.annotate()` for reviewer decisions |
| Art. 26 | Log retention | Retention engine with 6-month minimum enforcement |

Also addresses **OWASP ASI06** (Memory & Context Poisoning).

Generate compliance reports: `provena --db audit.db report --format pdf`

See the [full compliance documentation](https://rajfirke.github.io/provena/compliance/eu-ai-act/).

## Documentation

Full documentation at [rajfirke.github.io/provena](https://rajfirke.github.io/provena) — guides, API reference, integration docs, and compliance mapping.

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, architecture guide, and PR process.

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before participating.

## License

[Apache 2.0](LICENSE)
