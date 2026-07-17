# Testing

Provena is designed to be easy to test. The in-memory backend eliminates
filesystem dependencies, the `PROVENA_DISABLED` environment variable provides
a kill switch, and `strict_mode` surfaces governance errors as exceptions that
your test framework can catch.

## InMemoryBackend for Fast Tests

Use `backend="memory"` to run tests without creating database files. The
in-memory backend is functionally identical to SQLite but stores records in a
Python list.

```python
from provena import ContextTrail

def test_basic_logging():
    trail = ContextTrail(backend="memory")

    record = trail.log(content="Test content", source="retriever")

    assert record is not None
    assert record.entry.source.value == "retriever"
    assert trail.summary()["total"] == 1
```

No files are created, no cleanup is needed, and tests run fast.

## Disabling Governance with PROVENA_DISABLED

Set the `PROVENA_DISABLED` environment variable to `1` to disable all
governance. When disabled:

- All `@trail.track()` decorators become pass-through no-ops
- The in-memory backend is used regardless of configuration
- Decorated functions still execute and return their values normally

```python
import os

def test_with_governance_disabled(monkeypatch):
    monkeypatch.setenv("PROVENA_DISABLED", "1")

    # Import after setting the env var, or reload the module
    from provena import ContextTrail

    trail = ContextTrail()
    # Trail uses InMemoryBackend even though no backend="memory" was passed
```

!!! tip "When to disable"
    Use `PROVENA_DISABLED=1` in development environments or CI jobs where
    governance overhead is unwanted. In your test suite, prefer
    `backend="memory"` instead so you can still assert on governance behavior.

## Context Manager Pattern

Use `ContextTrail` as a context manager to ensure the storage backend is
closed after each test, even if the test fails:

```python
from provena import ContextTrail, ProvenanceMetadata
from datetime import datetime, timezone

def test_provenance_validation():
    with ContextTrail(backend="memory") as trail:
        record = trail.log(
            content="Governed content",
            source="retriever",
            provenance=ProvenanceMetadata(
                source_url="https://example.com",
                created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            ),
        )

        assert record.provenance_result.status == "VALID"
        assert record.freshness_result.status == "FRESH"
    # trail.close() is called automatically
```

This is especially important when using the SQLite backend in tests, where
unclosed connections can cause file-locking issues.

## Testing with strict_mode

Enable `strict_mode=True` to turn governance errors into exceptions. In
non-strict mode (the default), errors are logged and `trail.log()` returns
`None`, which can mask issues in tests.

```python
import pytest
from provena import ContextTrail

def test_strict_mode_catches_errors():
    trail = ContextTrail(backend="memory", strict_mode=True)

    # Valid usage works normally
    record = trail.log(content="Valid content", source="retriever")
    assert record is not None
```

With strict mode on, any internal governance error will raise rather than
returning `None`, giving you immediate feedback in your test output.

## Verifying Chain Integrity in Tests

After logging multiple entries, verify that the hash chain is intact:

```python
from provena import ContextTrail

def test_chain_integrity():
    trail = ContextTrail(backend="memory")

    for i in range(10):
        trail.log(content=f"Entry {i}", source="retriever")

    verdict = trail.verify_chain()

    assert verdict.intact is True
    assert verdict.total_records == 10
    assert verdict.broken_at is None
```

Test with HMAC signing to verify signed chains:

```python
def test_signed_chain():
    trail = ContextTrail(
        backend="memory",
        signing_key="test-signing-key",
    )

    trail.log(content="Signed entry 1", source="retriever")
    trail.log(content="Signed entry 2", source="tool:api")

    assert trail.is_signed is True

    verdict = trail.verify_chain()
    assert verdict.intact is True
```

## Checking Summary Counts in Assertions

The `summary()` method returns a dictionary you can assert against:

```python
from provena import ContextTrail, ProvenanceMetadata
from datetime import datetime, timezone

def test_summary_counts():
    trail = ContextTrail(backend="memory")

    # Log entries with different provenance states
    trail.log(content="No provenance", source="retriever")

    trail.log(
        content="With full provenance",
        source="retriever",
        provenance=ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        ),
    )

    trail.log(
        content="Incomplete provenance",
        source="tool:api",
        provenance=ProvenanceMetadata(source_url="https://example.com"),
    )

    summary = trail.summary()

    # Total count
    assert summary["total"] == 3

    # Provenance breakdown
    assert summary["provenance"]["MISSING"] == 1
    assert summary["provenance"]["VALID"] == 1
    assert summary["provenance"]["INCOMPLETE"] == 1

    # Source breakdown
    assert summary["sources"]["retriever"] == 2
    assert summary["sources"]["tool"] == 1

    # Freshness breakdown
    assert "freshness" in summary
```

## Using on_error for Test Assertions

The `on_error` callback lets you capture governance errors without raising
exceptions. This is useful when you want to verify that specific error
conditions are handled:

```python
from provena import ContextTrail

def test_error_callback():
    captured_errors = []

    trail = ContextTrail(
        backend="memory",
        on_error=lambda exc: captured_errors.append(exc),
    )

    # Normal operations should not trigger errors
    trail.log(content="Valid content", source="retriever")
    assert len(captured_errors) == 0

    # Verify the error count property
    assert trail.error_count == 0
```

Combine `on_error` with `strict_mode=False` (the default) to collect errors
without halting execution:

```python
def test_error_collection():
    errors = []

    trail = ContextTrail(
        backend="memory",
        strict_mode=False,
        on_error=lambda exc: errors.append(str(exc)),
    )

    # Log multiple entries and check that no errors accumulated
    for i in range(5):
        trail.log(content=f"Entry {i}", source="retriever")

    assert trail.error_count == 0
    assert len(errors) == 0
```

## Pytest Fixture Example

A reusable pytest fixture that provides a fresh in-memory trail for each test:

```python
import pytest
from provena import ContextTrail

@pytest.fixture
def trail():
    """Provide a fresh in-memory ContextTrail for each test."""
    with ContextTrail(backend="memory", strict_mode=True) as t:
        yield t

def test_tracking_decorator(trail):
    @trail.track(source="retriever")
    def search(query: str) -> list[str]:
        return ["Result one", "Result two"]

    results = search("test query")

    assert len(results) == 2
    assert trail.summary()["total"] == 2
    assert trail.verify_chain().intact is True

def test_provenance_required(trail):
    record = trail.log(content="No metadata", source="retriever")
    assert record.provenance_result.status == "MISSING"
```

!!! tip "Fixture with custom configuration"
    Parameterize the fixture for tests that need different settings:

    ```python
    @pytest.fixture
    def strict_trail():
        with ContextTrail(
            backend="memory",
            strict_mode=True,
            max_age_days=30,
            required_fields=["source_url", "author"],
        ) as t:
            yield t
    ```
