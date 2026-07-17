# Getting Started

Get context governance running in under 5 minutes.

## Install

```bash
pip install provena
```

Zero dependencies. Python 3.10+.

## Step 1: Create an Audit Trail

```python
from provena import ContextTrail

trail = ContextTrail(backend="memory")

record = trail.log(
    content="Kubernetes supports rolling updates for Deployments.",
    source="retriever",
    source_name="k8s_docs",
)

print(f"Logged: {record.entry.source_name}")
print(f"Hash:   {record.entry.content_hash[:16]}...")
print(f"Provenance: {record.provenance_result.status}")
```

Output:

```
Logged: k8s_docs
Hash:   a1b2c3d4e5f6...
Provenance: MISSING
```

Provenance is `MISSING` because we didn't attach any source metadata. Let's fix that.

## Step 2: Track a RAG Pipeline

The `@trail.track()` decorator automatically logs function return values:

```python
trail = ContextTrail(backend="memory")

@trail.track(source="retriever")
def search(query):
    return [
        "Result 1: Pod scheduling uses the kube-scheduler.",
        "Result 2: Services provide stable networking for Pods.",
    ]

results = search("kubernetes networking")
# Both results are now logged as separate audit records
```

Each list item gets its own audit record with a content hash and chain link.

## Step 3: Add Provenance Metadata

Attach origin metadata to make provenance validation pass:

```python
from provena import ContextTrail, ProvenanceMetadata
from datetime import datetime, timezone

trail = ContextTrail(backend="memory", max_age_days=90)

record = trail.log(
    content="The enterprise plan costs $499/month.",
    source="tool:pricing_api",
    provenance=ProvenanceMetadata(
        source_url="https://api.example.com/pricing",
        created_at=datetime.now(timezone.utc),
    ),
)

print(f"Provenance: {record.provenance_result.status}")  # VALID
print(f"Freshness:  {record.freshness_result.status}")   # FRESH
```

## Step 4: Detect Stale Content

Provena detects stale content in two ways: metadata timestamps and regex temporal markers in the text itself.

```python
from datetime import datetime, timezone, timedelta

trail = ContextTrail(backend="memory", max_age_days=90)

# Stale via metadata
record = trail.log(
    content="API pricing document",
    source="retriever",
    provenance=ProvenanceMetadata(
        source_url="https://docs.example.com/pricing",
        created_at=datetime(2023, 1, 15, tzinfo=timezone.utc),
    ),
)
print(f"Freshness: {record.freshness_result.status}")   # STALE
print(f"Details:   {record.freshness_result.details}")

# Stale via temporal detection in content
record = trail.log(
    content="As of January 2023, the API supports 3 endpoints.",
    source="retriever",
)
print(f"Freshness: {record.freshness_result.status}")   # STALE
```

Temporal patterns detected include ISO dates (`2023-06-15`), month-year (`January 2024`),
quarters (`Q3 2024`), and contextual phrases (`as of 2023`, `last updated: March 2024`).

## Step 5: Verify Chain Integrity

Every record is hash-chained to its predecessor. Verify the entire chain:

```python
trail = ContextTrail(backend="memory")

trail.log("First context", source="retriever")
trail.log("Second context", source="tool")
trail.log("Third context", source="agent")

verdict = trail.verify_chain()
print(f"Chain intact: {verdict.intact}")       # True
print(f"Records:      {verdict.total_records}") # 3
```

For HMAC-signed chains (required for compliance):

```python
trail = ContextTrail(
    backend="memory",
    signing_key="my-secret-key",
)
```

Or via environment variable:

```bash
export PROVENA_SIGNING_KEY="my-secret-key"
```

## Step 6: View the Summary

```python
summary = trail.summary()
print(f"Total records: {summary['total']}")
print(f"Provenance:    {summary['provenance']}")
print(f"Freshness:     {summary['freshness']}")
print(f"Sources:       {summary['sources']}")
```

## Step 7: Use the CLI

Install the CLI extras:

```bash
pip install provena[cli]
```

```bash
# Verify chain integrity
provena --db audit.db verify
# PASS -- Chain intact (42 records verified)

# Query the audit log
provena --db audit.db audit --source retriever --limit 10

# Generate a compliance report
provena --db audit.db report --format text

# Quick summary
provena --db audit.db summary
```

## Next Steps

- [Tracking Context](guide/tracking.md) — Deep-dive into `@trail.track()`
- [Provenance Validation](guide/provenance.md) — Configure required metadata fields
- [Freshness Checking](guide/freshness.md) — Temporal detection patterns
- [Chain Verification](guide/verification.md) — HMAC signing and tamper detection
- [LangChain Integration](integrations/langchain.md) — Add governance to existing chains
- [CLI Reference](integrations/cli.md) — All commands and options
