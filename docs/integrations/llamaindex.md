# LlamaIndex

Provena integrates with LlamaIndex through a node postprocessor that logs every
retrieved node to your audit trail without altering query results.

## Installation

```bash
pip install provena[llamaindex]
```

This installs `llama-index-core>=0.10` as a dependency.

## Quick start

```python
from provena import ContextTrail
from provena.integrations.llamaindex import ProvenaPostprocessor

trail = ContextTrail()
postprocessor = ProvenaPostprocessor(trail=trail)

query_engine = index.as_query_engine(
    node_postprocessors=[postprocessor],
)
```

## How it works

`ProvenaPostprocessor` extends LlamaIndex's `BaseNodePostprocessor`. It
implements the `_postprocess_nodes` method, which is called after retrieval
and before the response synthesizer.

### Pass-through behavior

The postprocessor returns nodes unchanged. It observes and logs each node
but never modifies content, scores, or ordering. Your query results are
identical whether Provena is attached or not.

```python
def _postprocess_nodes(self, nodes, query_bundle=None):
    for node_with_score in nodes:
        node = node_with_score.node
        content = node.text                               # (1)!
        provenance = _extract_llamaindex_provenance(node)  # (2)!

        metadata = {}
        if node_with_score.score is not None:
            metadata["score"] = node_with_score.score      # (3)!
        if query_bundle:
            metadata["query"] = query_bundle.query_str     # (4)!

        self.trail.log(
            content=content,
            source=ContextSource.RETRIEVER,
            source_name="llamaindex",
            provenance=provenance,
            metadata=metadata,
        )
    return nodes  # unchanged
```

1. Each node's `text` attribute is captured as the logged content.
2. Provenance metadata is auto-extracted from `node.metadata` (see below).
3. The retrieval similarity score is stored in the record's metadata.
4. The original query string is also captured when available.

!!! info "Score and query tracking"
    Each trail record's metadata includes the retrieval `score` (float) and
    the `query` string that triggered the retrieval. This lets you audit
    not just *what* was retrieved but *why* and *how relevant* it was.

## Provenance auto-extraction

Provena automatically extracts provenance metadata from each node's
`metadata` dictionary:

| Node metadata key | Provena field | Notes |
|---|---|---|
| `source` | `source_url` | Checked first |
| `file_path` | `source_url` | Fallback if `source` is absent |
| `author` | `author` | Mapped directly |

```python
# A node with this metadata:
node = TextNode(
    text="...",
    metadata={
        "file_path": "/data/contracts/agreement_v2.pdf",
        "author": "Legal Department",
    },
)

# Produces this ProvenanceMetadata:
# ProvenanceMetadata(
#     source_url="/data/contracts/agreement_v2.pdf",
#     author="Legal Department",
# )
```

!!! tip "Provenance validation"
    Nodes that include `source`, `file_path`, or `author` in their metadata
    will receive `VALID` or `INCOMPLETE` provenance status. Nodes with no
    origin metadata are marked `MISSING`, making gaps visible in your
    compliance reports.

## Full working example

```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.llms.openai import OpenAI

from provena import ContextTrail
from provena.integrations.llamaindex import ProvenaPostprocessor

# --- Load and index documents ---
documents = SimpleDirectoryReader("./data").load_data()
index = VectorStoreIndex.from_documents(documents)

# --- Create the Provena trail and postprocessor ---
trail = ContextTrail(storage_path="rag_audit.db")
postprocessor = ProvenaPostprocessor(trail=trail)

# --- Build the query engine with governance ---
query_engine = index.as_query_engine(
    llm=OpenAI(model="gpt-4o"),
    similarity_top_k=3,
    node_postprocessors=[postprocessor],
)

# --- Run a query ---
response = query_engine.query("What are the key terms of the agreement?")
print(response)
```

## Verifying the trail

After running a query, inspect and verify the audit trail:

```python
# Check what was logged
summary = trail.summary()
print(f"Total records: {summary['total']}")
print(f"Sources: {summary['sources']}")
print(f"Provenance: {summary['provenance']}")

# Verify hash chain integrity
verdict = trail.verify_chain()
assert verdict.intact, f"Chain broken: {verdict.details}"
print(f"Chain intact: {verdict.total_records} records verified")

# Inspect individual records with scores
records = trail.query(source="retriever", limit=10)
for r in records:
    meta = r.get("metadata_json", "{}")
    print(
        f"  [{r['provenance_status']}] {r['source_name']}"
        f" - score={r.get('metadata', {}).get('score', 'N/A')}"
    )

trail.close()
```

Expected output:

```text
Total records: 3
Sources: {'retriever': 3}
Provenance: {'VALID': 2, 'MISSING': 1}
Chain intact: 3 records verified
  [VALID] llamaindex - score=0.92
  [VALID] llamaindex - score=0.87
  [MISSING] llamaindex - score=0.81
```

## Combining with other postprocessors

`ProvenaPostprocessor` can be stacked with other LlamaIndex postprocessors.
Place it last in the list so it logs the final set of nodes that reach the
response synthesizer:

```python
from llama_index.core.postprocessor import SimilarityPostprocessor

query_engine = index.as_query_engine(
    node_postprocessors=[
        SimilarityPostprocessor(similarity_cutoff=0.7),  # filter first
        ProvenaPostprocessor(trail=trail),                # then log
    ],
)
```

## Context manager pattern

Use the trail as a context manager so the database is always closed:

```python
with ContextTrail(storage_path="audit.db") as trail:
    postprocessor = ProvenaPostprocessor(trail=trail)
    query_engine = index.as_query_engine(
        node_postprocessors=[postprocessor],
    )

    response = query_engine.query("Summarize the compliance requirements")

    verdict = trail.verify_chain()
    print(f"Chain intact: {verdict.intact}")
# trail.close() is called automatically
```
