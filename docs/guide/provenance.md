# Provenance Validation

Provenance metadata records where a piece of context came from -- its origin
URL, author, creation date, and version. Provena validates this metadata on
every logged entry and assigns a verdict that tells you whether the context has
a trustworthy lineage.

## ProvenanceMetadata

The `ProvenanceMetadata` dataclass carries origin information for a context
input:

```python
from provena import ProvenanceMetadata
from datetime import datetime, timezone

provenance = ProvenanceMetadata(
    source_url="https://docs.example.com/api/v2",
    author="Platform Team",
    created_at=datetime(2025, 3, 15, tzinfo=timezone.utc),
    version="2.1.0",
    extra={"department": "engineering", "review_status": "approved"},
)
```

| Field        | Type                  | Description                              |
|--------------|-----------------------|------------------------------------------|
| `source_url` | `str` or `None`       | URL where the content was retrieved       |
| `author`     | `str` or `None`       | Author or creator of the content          |
| `created_at` | `datetime` or `None`  | When the content was originally published |
| `version`    | `str` or `None`       | Version identifier                        |
| `extra`      | `dict[str, Any]`      | Arbitrary additional metadata             |

## Validation Verdicts

Every logged entry receives one of three provenance verdicts:

| Verdict        | Meaning                                                      |
|----------------|--------------------------------------------------------------|
| **VALID**      | All required fields are present and non-empty                 |
| **MISSING**    | No `ProvenanceMetadata` was attached at all                   |
| **INCOMPLETE** | Metadata was attached but one or more required fields are absent |

```python
from provena import ContextTrail, ProvenanceMetadata
from datetime import datetime, timezone

trail = ContextTrail(backend="memory")

# MISSING -- no provenance provided
trail.log(content="Some text", source="retriever")

# INCOMPLETE -- source_url present but created_at is missing
trail.log(
    content="Some text",
    source="retriever",
    provenance=ProvenanceMetadata(source_url="https://example.com"),
)

# VALID -- both default required fields present
trail.log(
    content="Some text",
    source="retriever",
    provenance=ProvenanceMetadata(
        source_url="https://example.com",
        created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    ),
)

summary = trail.summary()
print(summary["provenance"])
# {'MISSING': 1, 'INCOMPLETE': 1, 'VALID': 1}
```

## Default Required Fields

By default, Provena requires two fields for a VALID verdict:

- `source_url` -- where the content was retrieved
- `created_at` -- when the content was created or published

If either is `None` or an empty string, the verdict is INCOMPLETE.

## Custom Required Fields

Override the defaults by passing `required_fields` to `ContextTrail`:

```python
trail = ContextTrail(
    backend="memory",
    required_fields=["source_url", "author", "version"],
)

# INCOMPLETE -- author and version are missing
record = trail.log(
    content="API response payload",
    source="tool:api",
    provenance=ProvenanceMetadata(
        source_url="https://api.example.com/v2/data",
    ),
)

# VALID -- all three custom fields present
record = trail.log(
    content="API response payload",
    source="tool:api",
    provenance=ProvenanceMetadata(
        source_url="https://api.example.com/v2/data",
        author="data-service",
        version="2.4.1",
    ),
)
```

## Attaching Provenance to trail.log()

Pass a `ProvenanceMetadata` instance to the `provenance` parameter:

```python
from provena import ContextTrail, ProvenanceMetadata
from datetime import datetime, timezone

trail = ContextTrail(backend="memory")

record = trail.log(
    content="Kubernetes 1.30 deprecates PodSecurityPolicy.",
    source="retriever",
    source_name="changelog_db",
    provenance=ProvenanceMetadata(
        source_url="https://kubernetes.io/blog/2024/k8s-1.30",
        author="Kubernetes Release Team",
        created_at=datetime(2024, 4, 17, tzinfo=timezone.utc),
        version="1.30",
    ),
)

print(record.provenance_result.status)  # "VALID"
```

## Auto-extraction from LangChain Documents

When using `@trail.track()` with objects that have a `.metadata` dictionary,
Provena automatically builds `ProvenanceMetadata` from recognized keys:

```python
class Document:
    def __init__(self, page_content: str, metadata: dict):
        self.page_content = page_content
        self.metadata = metadata

@trail.track(source="retriever")
def retrieve(query: str) -> Document:
    return Document(
        page_content="Horizontal pod autoscaling adjusts replica count.",
        metadata={
            "source": "https://k8s.io/docs/hpa",
            "author": "SIG Autoscaling",
        },
    )

doc = retrieve("autoscaling")
```

The following `.metadata` keys are mapped automatically:

| Document metadata key  | ProvenanceMetadata field |
|------------------------|--------------------------|
| `source` or `source_url` | `source_url`           |
| `author`                | `author`                |
| `version`               | `version`               |

!!! tip "LlamaIndex nodes"
    LlamaIndex nodes follow the same pattern. The `metadata` dict keys
    `source`, `file_path`, and `author` are extracted automatically when
    using the `ProvenaPostprocessor` integration.

## Auto-extraction from LlamaIndex Nodes

The `ProvenaPostprocessor` extracts provenance from LlamaIndex node metadata:

```python
from provena import ContextTrail
from provena.integrations.llamaindex import ProvenaPostprocessor

trail = ContextTrail(backend="memory")
postprocessor = ProvenaPostprocessor(trail=trail)

# Nodes with metadata like {"source": "...", "author": "..."}
# will have ProvenanceMetadata created automatically.
```

| Node metadata key        | ProvenanceMetadata field |
|--------------------------|--------------------------|
| `source` or `file_path`  | `source_url`            |
| `author`                 | `author`                |

## Checking Provenance in trail.summary()

The `summary()` method provides an aggregate breakdown of provenance verdicts
across all records:

```python
summary = trail.summary()
print(summary["provenance"])
# Example output:
# {'VALID': 42, 'INCOMPLETE': 3, 'MISSING': 7}
```

Use this to monitor governance health over time. A high MISSING count
indicates that context sources are not providing origin metadata.

## Serialization

`ProvenanceMetadata` supports round-trip serialization:

```python
from provena import ProvenanceMetadata
from datetime import datetime, timezone

original = ProvenanceMetadata(
    source_url="https://example.com/doc",
    author="Engineering",
    created_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
    version="3.0",
    extra={"classification": "internal"},
)

# Serialize to dict
data = original.to_dict()
print(data)
# {
#     'source_url': 'https://example.com/doc',
#     'author': 'Engineering',
#     'created_at': '2025-01-15T00:00:00+00:00',
#     'version': '3.0',
#     'extra': {'classification': 'internal'}
# }

# Deserialize back
restored = ProvenanceMetadata.from_dict(data)
assert restored.source_url == original.source_url
assert restored.created_at == original.created_at
```

!!! tip "Storage format"
    Provena stores provenance as JSON in the audit database. The `to_dict()`
    method omits fields that are `None`, keeping storage compact. The
    `from_dict()` class method handles ISO-format datetime strings
    automatically.
