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
Can you verify it was still current when the LLM saw it?

Provena adds tamper-evident audit trails to any AI agent's context pipeline — in one decorator:

```python
from provena import ContextTrail

trail = ContextTrail(storage_path="audit.db")

@trail.track(source="retriever")
def search(query):
    return retriever.search(query)
```

Every call to `search()` is now logged with a SHA-256 content hash, provenance validation,
freshness check, and a hash-chained audit trail that detects tampering.

## Why Provena?

> **AGT governs what agents DO. Guardrails AI governs what agents SAY. Provena governs what agents KNOW.**

No existing tool governs the context input layer — the data your agent retrieves and acts on.
Provena fills this gap:

| | Provena | LangSmith | Guardrails AI | OpenTelemetry |
|---|---|---|---|---|
| Context tamper detection | ✅ | ❌ | ❌ | ❌ |
| Provenance validation | ✅ | ❌ | ❌ | ❌ |
| Freshness checking | ✅ | ❌ | ❌ | ❌ |
| EU AI Act compliance reports | ✅ | ❌ | ❌ | ❌ |
| Policy enforcement (block/warn) | ✅ | ❌ | ✅ (output) | ❌ |
| Multi-agent handoff tracking | ✅ | ✅ | ❌ | ❌ |
| Zero core dependencies | ✅ | ❌ | ❌ | ❌ |

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

@trail.track(source="retriever")
def search(query):
    return retriever.search(query)

@trail.track(source="tool:pricing_api")
def get_price(product_id):
    return api.get(f"/price/{product_id}")

# Manual logging with full provenance
trail.log(
    content="The enterprise plan costs $499/month.",
    source="tool:pricing_api",
    provenance=ProvenanceMetadata(
        source_url="https://api.example.com/pricing",
        created_at=datetime.now(timezone.utc),
    ),
)

# Verify the chain hasn't been tampered with
verdict = trail.verify_chain()
# ChainVerdict(intact=True, total_records=3, broken_links=0)

# Get a governance summary
print(trail.summary())
# {
#   "total": 3,
#   "sources": {"retriever": 1, "tool:pricing_api": 2},
#   "provenance": {"VALID": 2, "MISSING": 1},
#   "freshness": {"FRESH": 2, "UNKNOWN": 1},
#   "chain_intact": True,
#   "signed": False
# }
```

## End-to-End: RAG Pipeline with Governance

A complete example showing a multi-source retrieval pipeline where one source gets flagged:

```python
from provena import (
    ContextTrail,
    ProvenanceMetadata,
    freshness_check,
    provenance_check,
    EnforcementLevel,
    PolicyViolation,
)
from datetime import datetime, timedelta, timezone

trail = ContextTrail(
    storage_path="audit.db",
    policies=[
        provenance_check(status="MISSING", enforcement=EnforcementLevel.WARN),
        freshness_check(status="STALE", enforcement=EnforcementLevel.BLOCK),
    ],
)

@trail.track(source="retriever")
def fetch_docs(query):
    # Returns a list — Provena extracts provenance per document
    return vector_db.search(query)

@trail.track(source="tool:web_search")
def web_search(query):
    return search_api.get(query)

# --- Run the pipeline ---

# Fresh doc with full provenance — passes all checks
doc = fetch_docs("enterprise pricing")

try:
    # Stale result triggers BLOCK policy
    old_result = web_search("competitor pricing")
except PolicyViolation as e:
    print(f"Blocked: {e}")
    # Blocked: freshness_check failed — STALE context blocked before reaching LLM

# The blocked entry is still logged for the compliance record
verdict = trail.verify_chain()
print(f"Chain intact: {verdict.intact}, records: {verdict.total_records}")
# Chain intact: True, records: 2

# Generate a compliance report
trail.export(format="json")  # or "csv", "json_with_annotations"
```

### What the CLI shows

```bash
$ provena --db audit.db audit --format table

 ID  Source            Provenance  Freshness  Content Hash
  1  retriever         VALID       FRESH      a3f9c1...
  2  tool:web_search   VALID       STALE      b2e4d7...

$ provena --db audit.db verify
PASS — Chain intact (2 records verified)

$ provena --db audit.db summary
Total records : 2
Sources       : retriever=1, tool:web_search=1
Provenance    : VALID=2
Freshness     : FRESH=1  STALE=1
Chain         : intact
Signed        : no
```

## Policy Enforcement

Three enforcement levels give you full control over the governance posture:

```python
from provena import ContextTrail, freshness_check, provenance_check, require_signing

trail = ContextTrail(
    storage_path="audit.db",
    policies=[
        provenance_check(status="MISSING", enforcement=EnforcementLevel.BLOCK),
        freshness_check(status="STALE", enforcement=EnforcementLevel.WARN),
        require_signing(enforcement=EnforcementLevel.LOG),
    ],
)
```

| Level | Behavior |
|-------|----------|
| `LOG` | Record the violation, continue |
| `WARN` | Call the warning callback, continue |
| `BLOCK` | Raise `PolicyViolation`, halt the call |

Blocked entries are **always persisted** to the audit trail — the record shows what was rejected and why, satisfying EU AI Act Art. 12.

## Multi-Agent Governance

Aggregate governance across a full agent pipeline with handoff tracking:

```python
from provena import ContextTrail, TrailAggregator

researcher = ContextTrail(storage_path="researcher.db")
writer = ContextTrail(storage_path="writer.db")

agg = TrailAggregator()
agg.add(researcher, label="researcher")
agg.add(writer, label="writer")

# Record context handoffs between agents
agg.record_handoff(from_label="researcher", to_label="writer", record_id=5)

# Cross-agent governance summary
print(agg.summary())
# {
#   "total_records": 12,
#   "trails": {"researcher": 7, "writer": 5},
#   "provenance": {"VALID": 10, "MISSING": 2},
#   "all_chains_intact": True,
#   "all_signed": False
# }

# Surface governance gaps across the full pipeline
gaps = agg.detect_gaps()
# [EvidenceGap(type="MISSING_PROVENANCE", trail="researcher", record_id=3),
#  EvidenceGap(type="UNLINKED_HANDOFF", trail="writer", record_id=1)]
```

## CLI

Install with `pip install provena[cli]`, then:

```bash
# Verify hash chain integrity
provena --db audit.db verify
# PASS — Chain intact (42 records verified)

# Query the audit log
provena --db audit.db audit --source retriever --format json
provena --db audit.db audit --provenance-status MISSING
provena --db audit.db audit --freshness-status STALE

# Governance summary (with optional source filter)
provena --db audit.db summary --source retriever

# One-line CI/CD status check
provena --db audit.db stats
# records=42 provenance=VALID:40,MISSING:2 freshness=FRESH:38,STALE:4 chain=intact signed=yes

# Retention management (EU AI Act 180-day minimum enforced)
provena --db audit.db retain --max-age 365 --dry-run
provena --db audit.db retain --max-age 365 --archive backup.json

# Generate a compliance report
provena --db audit.db report --format text
provena --db audit.db report --format pdf   # requires provena[pdf]

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
# Every log() call emits an OTel span with provenance, freshness, and chain attributes
```

### Configuration Files

```toml
# provena.toml
[storage]
path = "audit.db"
buffered = true

[hash_chain]
signing_key_env = "PROVENA_SIGNING_KEY"

[[policies]]
check = "freshness_check"
status = "STALE"
enforcement = "BLOCK"
```

```python
trail = ContextTrail(config="provena.toml")
```

## Architecture

```
Your Application
    │
    ├── Retriever ──┐
    ├── Tool Call ──┤
    ├── Agent Msg ──┤──► ContextTrail ──────────────► LLM Context Window
    ├── Memory    ──┤         │
    └── MCP       ──┘    ┌────┴───────────────────────┐
                         │ ProvenanceValidator         │
                         │ FreshnessChecker            │
                         │ PolicyEngine (block/warn)   │
                         │ HashChain (SHA-256 / HMAC)  │
                         │ WriteBuffer (10K+ writes/s) │
                         │ SQLite / PostgreSQL Backend │
                         │ OTel Exporter               │
                         └────────────────────────────┘
    │
    ├── TrailAggregator   — multi-agent cross-trail governance
    ├── RetentionEngine   — record lifecycle + EU AI Act 180-day minimum
    ├── ComplianceReport  — EU AI Act / OWASP article-by-article scoring
    └── MCP Server        — governance tools for agents via MCP protocol
```

## Compliance

Provena maps directly to EU AI Act requirements for high-risk AI systems:

| Article | Requirement | Provena Feature |
|---------|------------|-----------------|
| Art. 9  | Risk management | Policy engine with configurable enforcement |
| Art. 10 | Data lineage | Provenance validation for every context input |
| Art. 12 | Tamper-evident logging | SHA-256 hash-chained audit trail with HMAC signing |
| Art. 13 | Transparency | `trail.summary()`, source tracking, compliance reports |
| Art. 14 | Human oversight | `trail.annotate()` for reviewer decisions |
| Art. 26 | Log retention | Retention engine with 6-month minimum enforcement |

Also addresses **OWASP ASI06** (Memory & Context Poisoning).

Generate a PDF compliance report: `provena --db audit.db report --format pdf`

See the [full compliance documentation](https://rajfirke.github.io/provena/compliance/eu-ai-act/).

## Documentation

Full documentation at [rajfirke.github.io/provena](https://rajfirke.github.io/provena) — guides, API reference, integration docs, and compliance mapping.

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, architecture guide, and PR process.

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before participating.

## License

[Apache 2.0](LICENSE)
