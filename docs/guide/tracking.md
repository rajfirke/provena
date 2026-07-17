# Tracking Context

Provena tracks every piece of context that flows into your AI agent. The primary
interface is the `@trail.track()` decorator, which automatically logs function
return values to the audit trail. For cases where a decorator does not fit,
`trail.log()` provides equivalent functionality as a direct call.

## Basic Usage

Decorate any function whose return value should be governed. The decorator
passes the return value through unchanged -- your application logic is not
affected.

```python
from provena import ContextTrail

trail = ContextTrail(backend="memory")

@trail.track(source="retriever")
def search_docs(query: str) -> str:
    return "OpenShift 4.16 supports single-node deployments for edge."

result = search_docs("edge deployment")
print(result)  # "OpenShift 4.16 supports single-node deployments for edge."
```

The decorator hashes the content, validates provenance, checks freshness, and
appends a hash-chained record to storage -- all before returning the original
value to the caller.

## Tracking List Returns

When a function returns a list, each item is logged as a separate record. This
is the natural fit for retriever functions that return multiple documents.

```python
@trail.track(source="retriever")
def search(query: str) -> list[str]:
    return [
        "Minimum requirements: 8 vCPUs, 32 GB RAM.",
        "Single-node deployments are supported for edge.",
    ]

results = search("requirements")
# Two separate records are created in the audit trail
print(trail.summary()["total"])  # 2
```

## Tracking Dict Returns

Dictionary return values are JSON-serialized and logged as a single record.

```python
@trail.track(source="tool:weather_api")
def get_weather(city: str) -> dict:
    return {"city": city, "temp_c": 22, "conditions": "partly cloudy"}

weather = get_weather("Toronto")
# Logged as: '{"city": "Toronto", "temp_c": 22, "conditions": "partly cloudy"}'
```

## Custom Content Extractor

When a function returns a complex object, use `content_extractor` to tell
Provena how to extract the loggable content.

```python
from dataclasses import dataclass

@dataclass
class SearchResult:
    text: str
    score: float
    metadata: dict

@trail.track(
    source="retriever",
    content_extractor=lambda r: r.text,
)
def ranked_search(query: str) -> SearchResult:
    return SearchResult(
        text="Pod scheduling uses node affinity rules.",
        score=0.95,
        metadata={"source": "k8s-docs"},
    )

result = ranked_search("scheduling")
# Only result.text is logged to the trail
```

The extractor can also return a list to create multiple records from one call:

```python
@trail.track(
    source="retriever",
    content_extractor=lambda results: [r.text for r in results],
)
def batch_search(query: str) -> list[SearchResult]:
    return [
        SearchResult(text="First result", score=0.9, metadata={}),
        SearchResult(text="Second result", score=0.8, metadata={}),
    ]
```

## Async Function Support

The decorator works transparently with `async` functions. No additional
configuration is needed.

```python
import asyncio

@trail.track(source="tool:api_name")
async def fetch_data(url: str) -> str:
    # In a real application, use aiohttp or httpx here
    await asyncio.sleep(0.01)
    return "Response payload from external API"

result = asyncio.run(fetch_data("https://api.example.com/data"))
```

## Source Types

The `source` parameter identifies where the context came from. Use the string
format `"type:name"` for specificity:

| Source String           | Use Case                                     |
|-------------------------|----------------------------------------------|
| `"retriever"`           | Vector store or document retrieval            |
| `"tool:api_name"`       | External API tool calls                       |
| `"agent:planner"`       | Output from a sub-agent                       |
| `"memory:long_term"`    | Long-term memory retrieval                    |
| `"mcp:filesystem"`      | Model Context Protocol server                 |
| `"custom"`              | Anything that does not fit the above           |

The part before the colon maps to a `ContextSource` enum value. The part after
the colon becomes the `source_name` in the audit record.

```python
@trail.track(source="mcp:filesystem")
def read_config(path: str) -> str:
    with open(path) as f:
        return f.read()

@trail.track(source="agent:planner")
def plan_next_step(state: dict) -> str:
    return "Retrieve the latest deployment manifest."
```

## None Returns Are Skipped

If a tracked function returns `None`, no record is created. This prevents empty
entries from cluttering the audit trail.

```python
@trail.track(source="retriever")
def maybe_search(query: str) -> str | None:
    if not query.strip():
        return None  # No record logged
    return "Found a relevant document."

maybe_search("")   # Nothing logged
maybe_search("k8s")  # One record logged
```

## LangChain Document Support

Objects with a `.page_content` attribute (such as LangChain `Document`
instances) are handled automatically. The `page_content` string is extracted
and logged.

```python
class Document:
    """Minimal LangChain-compatible document."""
    def __init__(self, page_content: str, metadata: dict | None = None):
        self.page_content = page_content
        self.metadata = metadata or {}

@trail.track(source="retriever")
def langchain_retriever(query: str) -> list[Document]:
    return [
        Document(
            page_content="Pod disruption budgets protect availability.",
            metadata={"source": "https://k8s.io/docs/pdb"},
        ),
    ]

docs = langchain_retriever("availability")
# Logged content: "Pod disruption budgets protect availability."
```

!!! tip "Provenance auto-extraction"
    When the return value has a `.metadata` dict with `source` or `source_url`
    keys, Provena automatically creates `ProvenanceMetadata` from it. See the
    [Provenance Validation](provenance.md) guide for details.

## Manual Logging with trail.log()

When a decorator does not fit your workflow, use `trail.log()` directly:

```python
from provena import ContextTrail, ProvenanceMetadata
from datetime import datetime, timezone

trail = ContextTrail(backend="memory")

# Log a retrieval result with full provenance
record = trail.log(
    content="Service mesh reduces inter-service latency by 40%.",
    source="retriever",
    source_name="knowledge_base",
    provenance=ProvenanceMetadata(
        source_url="https://docs.example.com/mesh",
        author="Platform Team",
        created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    ),
)

print(record.chain_hash[:16])  # First 16 chars of the chain hash
```

`trail.log()` returns a `TrailRecord` on success, or `None` if a non-strict
error occurred.

!!! tip "Choosing between track() and log()"
    Use `@trail.track()` when you control the function definition and want
    zero-touch logging. Use `trail.log()` when you receive content from
    callbacks, event handlers, or third-party code where a decorator cannot
    be applied.
