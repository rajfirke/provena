---
title: Provena
description: Context governance for agentic AI systems — tamper-evident audit trails in 3 lines of Python.
hide:
  - navigation
  - toc
---

# Provena

**Govern what your agents know.**

Your AI agent just made a decision based on data from 6 different sources.
Can you tell me which ones? Can you prove the data wasn't tampered with?
Can you verify it was still current when the LLM saw it?

Provena adds tamper-evident audit trails to any AI agent's context pipeline — in 3 lines of Python.

```python
from provena import ContextTrail

trail = ContextTrail()


@trail.track(source="retriever")
def search(query):
    return retriever.search(query)
```

Every call to `search()` is logged with a SHA-256 content hash, provenance validation,
freshness checking, and a hash-chained audit trail that detects tampering.

<div class="hero-actions" markdown>

[Get started](getting-started.md){ .md-button .md-button--primary }
[GitHub](https://github.com/rajfirke/provena){ .md-button }
[PyPI](https://pypi.org/project/provena/){ .md-button }

</div>

```bash
pip install provena
```

## Why Provena?

> **AGT governs what agents DO. Guardrails AI governs what agents SAY. Provena governs what agents KNOW.**

<div class="grid cards" markdown>

-   :material-shield-lock:{ .lg .middle } **Tamper-evident trails**

    ---

    SHA-256 hash-chained (Merkle-style) logging with optional HMAC signing.
    If a record is edited, the chain breaks.

    [:octicons-arrow-right-24: Chain verification](guide/verification.md)

-   :material-source-branch:{ .lg .middle } **Provenance validation**

    ---

    Verify that context carries source metadata.
    Statuses: `VALID` / `MISSING` / `INCOMPLETE`.

    [:octicons-arrow-right-24: Provenance guide](guide/provenance.md)

-   :material-clock-check:{ .lg .middle } **Freshness checking**

    ---

    Detect stale context from timestamps and temporal patterns.
    Statuses: `FRESH` / `STALE` / `UNKNOWN`.

    [:octicons-arrow-right-24: Freshness guide](guide/freshness.md)

-   :material-gavel:{ .lg .middle } **EU AI Act & ASI06**

    ---

    Maps to Articles 10, 12, 13, and 14, and covers
    [OWASP ASI06](compliance/owasp-asi06.md) context poisoning.

    [:octicons-arrow-right-24: EU AI Act mapping](compliance/eu-ai-act.md)

</div>

## How it compares

No existing tool governs the context input layer — the data your agent retrieves and acts on.

| | Provena | LangSmith | Guardrails AI | OpenTelemetry |
|---|---|---|---|---|
| Context tamper detection | ✅ | ❌ | ❌ | ❌ |
| Provenance validation | ✅ | ❌ | ❌ | ❌ |
| Freshness checking | ✅ | ❌ | ❌ | ❌ |
| EU AI Act compliance reports | ✅ | ❌ | ❌ | ❌ |
| Policy enforcement (block/warn) | ✅ | ❌ | ✅ (output) | ❌ |
| Multi-agent handoff tracking | ✅ | ✅ | ❌ | ❌ |
| Zero core dependencies | ✅ | ❌ | ❌ | ❌ |

## Architecture

```
Your Application
|
|  Retriever ---+
|  Tool Call ---+
|  Agent Msg ---+---> ContextTrail (observe/log) --> trail + optional PolicyViolation
|  Memory    ---+        |                              (after persist)
|  MCP       ---+        |
|                  +-----+------------------+
|                  | ProvenanceValidator     |
|                  | FreshnessChecker        |
|                  | HashChain (SHA-256)     |
|                  | SQLite Backend          |
|                  | OTel Exporter           |
|                  +------------------------+

The LLM path belongs to your application. Provena observes and logs
sources by default; a configured BLOCK policy raises PolicyViolation
after the record is written, not before the LLM is called.
```

Pure Python, sub-1ms overhead, no model downloads. The core library uses only the standard library.

## Next steps

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Getting started**

    ---

    Install, log a first trail, and verify the chain in 5 minutes.

    [:octicons-arrow-right-24: Start here](getting-started.md)

-   :material-book-open-variant:{ .lg .middle } **Guide**

    ---

    Tracking, provenance, freshness, verification, configuration, and testing.

    [:octicons-arrow-right-24: Read the guide](guide/tracking.md)

-   :material-puzzle:{ .lg .middle } **Integrations**

    ---

    LangChain, LlamaIndex, OpenTelemetry, MCP, and the CLI.

    [:octicons-arrow-right-24: Wire it in](integrations/langchain.md)

-   :material-code-braces:{ .lg .middle } **API reference**

    ---

    Auto-generated from the public Python API.

    [:octicons-arrow-right-24: Browse the API](api/provena/index.md)

</div>
