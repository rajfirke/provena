# OWASP ASI06: Context Poisoning

OWASP ASI06 -- Memory & Context Poisoning -- is identified as a top-10 risk in
the OWASP Top 10 for Agentic AI Systems (2026). It addresses the class of attacks
where adversaries manipulate the context, memory, or state information that AI
agents rely on for decision-making. Provena provides the technical controls
needed to detect, prevent, and audit context poisoning attacks.

!!! warning "Impact of context poisoning"

    Research on agentic AI systems demonstrates that context poisoning propagates
    rapidly and silently:

    - A single poisoned context entry corrupts 87% of downstream decisions
      within 4 hours
    - 48% of co-running agents are compromised during a single context injection
    - 40% of multi-agent system failures trace to state synchronization issues

---

## The Threat

Agentic AI systems retrieve, store, and share context across multiple components
and execution cycles. Unlike traditional prompt injection -- which targets a
single inference call -- context poisoning targets the persistent state layer
that agents depend on for continuity, memory, and multi-step reasoning.

The consequences are severe because poisoned context is treated as trusted input
by downstream components. An agent that retrieves a tampered document, stores a
manipulated memory, or receives corrupted state from a peer agent will
incorporate that poisoned context into all subsequent decisions without any
indication that the input was compromised.

---

## Attack Vectors

ASI06 identifies three primary attack vectors. Provena addresses each with
specific technical controls.

### 1. Context Poisoning

**The attack.** An adversary injects fabricated or manipulated content into the
context sources that an agent retrieves from. This includes poisoning vector
store entries, modifying documents in retrieval corpora, or injecting malicious
content through tool responses.

**How Provena detects it.** The `ProvenanceValidator` requires every context
input to carry verifiable origin metadata -- source URL, author, creation date,
and version. Inputs from unknown or unverified sources are flagged with a
provenance status of `MISSING` or `INCOMPLETE`:

```python
from provena import ContextTrail

trail = ContextTrail(
    required_fields=["source_url", "author", "created_at"],
    strict_mode=True,  # Raise on internal governance errors
)

# Context from a verified source -- accepted
record = trail.log(
    content=verified_document,
    source="retriever",
    provenance=ProvenanceMetadata(
        source_url="https://docs.internal.com/policy-v3",
        author="policy-team",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        version="3.0",
    ),
)
# record.provenance_result.status -> "VALID"

# Context from an unknown source -- flagged
record = trail.log(
    content=suspicious_content,
    source="retriever",
    # No provenance metadata provided
)
# record.provenance_result.status -> "MISSING"
# The record is still logged -- provenance status flags the gap for review
```

### 2. Memory Integrity Attacks

**The attack.** An adversary modifies context entries after they have been
validated and stored. This includes tampering with database records, altering
cached retrieval results, or manipulating serialized agent state between
execution cycles.

**How Provena detects it.** The `ChainHasher` implements a Merkle-style hash
chain using SHA-256 (or HMAC-SHA256 with a signing key). Each record's chain
hash incorporates the previous record's hash, the content hash, the source type,
and the timestamp. Modifying any record -- even a single byte -- invalidates all
subsequent chain hashes:

```python
# Verify the entire chain at any time
verdict = trail.verify_chain()

if not verdict.intact:
    print(f"Tampering detected at record {verdict.broken_at}")
    print(f"Chain broken after {verdict.total_records} records verified")
```

!!! note "HMAC signing for stronger guarantees"

    For environments where an attacker might attempt to recompute the hash chain
    after tampering, enable HMAC-SHA256 signing. This requires knowledge of the
    signing key to produce valid chain hashes:

    ```python
    trail = ContextTrail(signing_key="your-secret-key")
    # Or via environment variable: PROVENA_SIGNING_KEY
    ```

### 3. Multi-Agent Contamination

**The attack.** In multi-agent systems, a compromised agent shares poisoned
context with peer agents through shared memory, message passing, or tool
outputs. A single point of compromise can cascade across the entire agent
network.

**How Provena addresses it.** Provena's governance is framework-agnostic. The
same `ContextTrail` instance (or separate instances sharing a storage backend)
can govern context inputs across LangChain, LlamaIndex, CrewAI, and custom agent
frameworks. Every context input -- regardless of which agent or framework
produced it -- passes through the same validation pipeline:

```python
from provena import ContextTrail, ContextSource

# Single trail governing multiple agent types
trail = ContextTrail(storage_path="shared-governance.db")

# LangChain retriever output
trail.log(content=langchain_result, source=ContextSource.RETRIEVER)

# LlamaIndex query response
trail.log(content=llamaindex_response, source=ContextSource.RETRIEVER)

# CrewAI agent tool output
trail.log(content=crewai_tool_result, source=ContextSource.AGENT)

# MCP server response
trail.log(content=mcp_response, source=ContextSource.MCP)
```

The `@trail.track()` decorator provides automatic governance for any function
that returns context, supporting both synchronous and asynchronous execution:

```python
@trail.track(source=ContextSource.TOOL, source_name="market-data-api")
async def fetch_market_data(symbol: str) -> dict:
    """Every return value is automatically logged and validated."""
    return await api.get_quote(symbol)
```

---

## How Provena Addresses ASI06

The following summarizes Provena's defense-in-depth approach to each ASI06
concern:

**Provenance validation catches context from unknown or unverified sources.**
The `ProvenanceValidator` enforces configurable metadata requirements on every
context input. Sources that cannot provide origin metadata (URL, author, creation
date) are flagged before they enter the agent's decision-making process. In
`strict_mode`, unverified context is rejected entirely.

**Freshness checking catches stale injections.** Context poisoning frequently
involves injecting outdated information that contradicts current data. The
`FreshnessChecker` detects stale inputs through both metadata timestamps and
regex-based temporal pattern detection in content text. A poisoned entry
referencing "Q1 2023" data when the threshold is 90 days will be flagged as
`STALE`.

**Hash chain detects tampering.** The SHA-256 hash chain provides
cryptographic evidence of whether any record has been modified after creation.
The `verify_chain()` method performs a full chain walk from the genesis hash
forward, identifying the exact record where integrity was broken.

**Framework-agnostic design works across all agent types.** Provena governs
context at the data layer, not the framework layer. It integrates with
LangChain (via callback handlers), LlamaIndex (via node postprocessors), and any
custom framework through the direct `trail.log()` and `@trail.track()` APIs.
This ensures consistent governance even in heterogeneous multi-agent deployments.

---

## OWASP Compliance Mapping

| Requirement | Standard | Provena Feature |
|---|---|---|
| Validate context source authenticity | ASI06-01 | `ProvenanceValidator` with configurable required fields (`source_url`, `author`, `created_at`) |
| Detect unauthorized context modifications | ASI06-02 | SHA-256 / HMAC-SHA256 hash chain with `verify_chain()` full-chain integrity verification |
| Prevent stale data injection | ASI06-03 | `FreshnessChecker` with metadata timestamp validation and temporal pattern detection |
| Maintain audit trail of context inputs | ASI06-04 | `TrailRecord` with content hash, provenance status, freshness status, and chain hash |
| Enable forensic analysis of context flow | ASI06-05 | `trail.query()` with filtering by source, time range, provenance status, and freshness status |
| Support human review of flagged inputs | ASI06-06 | `trail.annotate()` for attaching reviewer decisions and notes to records |
| Cross-framework context governance | ASI06-07 | Framework-agnostic design with LangChain, LlamaIndex, and direct API integrations |
| Cryptographic integrity verification | ASI06-08 | Merkle-style chain with constant-time comparison (`hmac.compare_digest`) to prevent timing attacks |
| Export governance data for external analysis | ASI06-09 | `trail.export()` in JSON and CSV formats; OTel span export for centralized monitoring |
| Operational health monitoring | ASI06-10 | `trail.health()` returns backend status, record count, signing state, and error count |

---

## Next Steps

- [EU AI Act Compliance](eu-ai-act.md) -- Regulatory mapping for high-risk AI
  systems under European law
- [Chain Verification Guide](../guide/verification.md) -- Detailed guide to
  hash chain configuration and verification
- [Provenance Validation Guide](../guide/provenance.md) -- Configuring
  provenance requirements for your deployment
