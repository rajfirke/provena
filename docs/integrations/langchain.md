# LangChain

Provena integrates with LangChain through a callback handler that automatically
logs retriever results and tool outputs to your audit trail.

## Installation

```bash
pip install provena[langchain]
```

This installs `langchain-core>=0.2` as a dependency. If you already have
LangChain installed, the extra ensures version compatibility.

## Quick start

```python
from provena import ContextTrail
from provena.integrations.langchain import ProvenaCallback

trail = ContextTrail()
callback = ProvenaCallback(trail=trail)

# Attach to any LangChain chain
chain = RetrievalQA.from_chain_type(
    llm=llm,
    retriever=retriever,
    callbacks=[callback],
)
```

## How it works

`ProvenaCallback` extends LangChain's `BaseCallbackHandler` and hooks into two
lifecycle events:

### `on_retriever_end` -- retrieved documents

When a retriever returns documents, the callback logs each document's
`page_content` as a separate trail entry with source type `RETRIEVER`:

```python
def on_retriever_end(self, documents, *, run_id, **kwargs):
    for doc in documents:
        content = doc.page_content      # (1)!
        provenance = _extract_langchain_provenance(doc)  # (2)!
        self._trail.log(
            content=content,
            source=ContextSource.RETRIEVER,
            source_name="langchain",
            provenance=provenance,
            metadata={"run_id": str(run_id)},
        )
```

1. Each document's `page_content` attribute is captured as the logged content.
2. Provenance metadata is auto-extracted from `doc.metadata` (see below).

### `on_tool_end` -- tool outputs

When a tool completes, the callback logs its output as a trail entry with
source type `TOOL`:

```python
def on_tool_end(self, output, *, run_id, **kwargs):
    content = str(output)
    self._trail.log(
        content=content,
        source=ContextSource.TOOL,
        source_name="langchain",
        metadata={"run_id": str(run_id)},
    )
```

!!! info "Run ID tracking"
    Both hooks capture the LangChain `run_id` in the record's metadata,
    letting you correlate audit trail entries back to specific chain
    executions.

## Provenance auto-extraction

Provena automatically extracts provenance metadata from each document's
`metadata` dictionary:

| Document metadata key | Provena field | Notes |
|---|---|---|
| `source` | `source_url` | Checked first |
| `source_url` | `source_url` | Fallback if `source` is absent |
| `author` | `author` | Mapped directly |

```python
# A document with this metadata:
doc = Document(
    page_content="...",
    metadata={
        "source": "https://docs.example.com/api.html",
        "author": "Engineering Team",
    }
)

# Produces this ProvenanceMetadata:
# ProvenanceMetadata(
#     source_url="https://docs.example.com/api.html",
#     author="Engineering Team",
# )
```

!!! tip "Provenance validation"
    The auto-extraction sets `source_url` and `author` but not `created_at`.
    Since the default required fields are `source_url` and `created_at`,
    records will be marked `INCOMPLETE` (missing `created_at`). To get
    `VALID` status, either set `created_at` in your document metadata or
    configure `required_fields=["source_url"]` on the trail. Documents
    without any origin metadata will be marked `MISSING`.

## Full working example

```python
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import FAISS
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain.chains import RetrievalQA

from provena import ContextTrail
from provena.integrations.langchain import ProvenaCallback

# --- Set up a retrieval chain ---
loader = TextLoader("knowledge_base.txt")
docs = loader.load()
vectorstore = FAISS.from_documents(docs, OpenAIEmbeddings())
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

llm = ChatOpenAI(model="gpt-4o")

# --- Create the Provena trail and callback ---
trail = ContextTrail(storage_path="rag_audit.db")
callback = ProvenaCallback(trail=trail)

# --- Run the chain with governance ---
chain = RetrievalQA.from_chain_type(
    llm=llm,
    retriever=retriever,
    callbacks=[callback],
)

answer = chain.invoke({"query": "What is the refund policy?"})
print(answer["result"])
```

## Verifying the trail

After chain execution, inspect and verify the audit trail:

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

# Query specific records
records = trail.query(source="retriever", limit=10)
for r in records:
    print(f"  [{r['provenance_status']}] {r['source_name']} - {r['content_hash'][:12]}")

trail.close()
```

Expected output:

```text
Total records: 3
Sources: {'retriever': 3}
Provenance: {'INCOMPLETE': 3}
Chain intact: 3 records verified
  [INCOMPLETE] langchain - a1b2c3d4e5f6
  [INCOMPLETE] langchain - b2c3d4e5f6a7
  [INCOMPLETE] langchain - c3d4e5f6a7b8
```

## Using with other chain types

The callback works with any LangChain component that fires retriever or tool
events:

```python
# With an agent that uses tools
from langchain.agents import AgentExecutor

agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    callbacks=[ProvenaCallback(trail=trail)],
)

# Tool calls are automatically logged as TOOL source entries
result = agent_executor.invoke({"input": "Look up the current price of ACME stock"})
```

## Context manager pattern

Use the trail as a context manager so the database is always closed:

```python
with ContextTrail(storage_path="audit.db") as trail:
    callback = ProvenaCallback(trail=trail)
    chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        callbacks=[callback],
    )
    chain.invoke({"query": "Summarize the Q3 earnings report"})

    verdict = trail.verify_chain()
    print(f"Chain intact: {verdict.intact}")
# trail.close() is called automatically
```
