# Configuration

Provena is configured through the `ContextTrail` constructor. Every parameter
has a sensible default, so the simplest setup is just `ContextTrail()`. This
page documents every parameter and shows how to use the `config` dict for
structured configuration.

## Constructor Parameters

### storage_path

Path to the SQLite database file.

- **Type**: `str`
- **Default**: `"provena.db"`

```python
from provena import ContextTrail

trail = ContextTrail(storage_path="governance/audit.db")
```

### backend

Storage backend type.

- **Type**: `str`
- **Default**: `"sqlite"`
- **Options**: `"sqlite"`, `"memory"`

```python
# Persistent storage (default)
trail = ContextTrail(backend="sqlite")

# In-memory storage for testing
trail = ContextTrail(backend="memory")
```

### required_fields

Provenance fields required for a VALID verdict. See the
[Provenance Validation](provenance.md) guide for details.

- **Type**: `list[str]` or `None`
- **Default**: `["source_url", "created_at"]`

```python
trail = ContextTrail(
    backend="memory",
    required_fields=["source_url", "author", "version"],
)
```

### max_age_days

Content older than this many days is marked STALE. See the
[Freshness Checking](freshness.md) guide.

- **Type**: `int`
- **Default**: `90`

```python
trail = ContextTrail(backend="memory", max_age_days=30)
```

Must be at least 1. Raises `ValueError` otherwise.

### temporal_detection

Enable regex-based date detection in content text when no metadata timestamp
is available.

- **Type**: `bool`
- **Default**: `True`

```python
trail = ContextTrail(backend="memory", temporal_detection=False)
```

### max_content_bytes

Maximum content size in bytes before truncation. Content exceeding this limit
is truncated and the record's `truncated` flag is set to `True`.

- **Type**: `int`
- **Default**: `65536` (64 KB)

```python
trail = ContextTrail(backend="memory", max_content_bytes=131072)  # 128 KB
```

Must be at least 1. Raises `ValueError` otherwise.

### signing_key

HMAC key for signed hash chains. When set, chain hashes use HMAC-SHA256
instead of plain SHA-256. See the [Chain Verification](verification.md)
guide.

- **Type**: `str`, `bytes`, or `None`
- **Default**: `None` (falls back to `PROVENA_SIGNING_KEY` env var)

```python
trail = ContextTrail(backend="memory", signing_key="my-secret-key")
```

### otel_enabled

Emit OpenTelemetry spans for each logged entry. Requires the
`opentelemetry-api` and `opentelemetry-sdk` packages.

- **Type**: `bool`
- **Default**: `False`

```python
trail = ContextTrail(backend="memory", otel_enabled=True)
```

### otel_service_name

Service name used in OpenTelemetry spans.

- **Type**: `str`
- **Default**: `"provena"`

```python
trail = ContextTrail(
    backend="memory",
    otel_enabled=True,
    otel_service_name="my-agent-service",
)
```

### strict_mode

When `True`, governance errors (provenance validation failures, storage
errors) propagate as exceptions instead of being silently logged.

- **Type**: `bool`
- **Default**: `False`

```python
# Non-strict (default): errors are logged, trail.log() returns None
trail = ContextTrail(backend="memory", strict_mode=False)

# Strict: errors raise exceptions
trail = ContextTrail(backend="memory", strict_mode=True)
```

!!! tip "Use strict mode in tests"
    Set `strict_mode=True` in your test suite to catch governance errors
    early. In production, the default non-strict mode prevents governance
    from blocking your agent's primary workflow.

### on_error

Optional callback invoked when a governance error occurs. Receives the
exception as its argument. Called regardless of `strict_mode`.

- **Type**: `Callable[[Exception], None]` or `None`
- **Default**: `None`

```python
errors = []

trail = ContextTrail(
    backend="memory",
    on_error=lambda exc: errors.append(exc),
)
```

### config

A dictionary that overrides all other constructor parameters. Useful for
loading configuration from files (YAML, JSON, TOML).

- **Type**: `dict[str, Any]` or `None`
- **Default**: `None`

When `config` is provided, all other parameters are ignored.

## Config Dict Structure

The `config` dict uses nested sections for organized configuration:

```python
from provena import ContextTrail

trail = ContextTrail(config={
    "storage": {
        "backend": "sqlite",
        "path": "governance/audit.db",
    },
    "provenance": {
        "required_fields": ["source_url", "created_at", "author"],
    },
    "freshness": {
        "max_age_days": 60,
        "temporal_detection": True,
    },
    "hash_chain": {
        "signing_key": "my-secret-key",
    },
    "otel": {
        "enabled": True,
        "service_name": "my-agent",
    },
    "max_content_bytes": 131072,
    "strict_mode": True,
})
```

### Config dict reference

| Section       | Key                  | Maps to parameter      | Default       |
|---------------|----------------------|------------------------|---------------|
| `storage`     | `backend`            | `backend`              | `"sqlite"`    |
| `storage`     | `path`               | `storage_path`         | `"provena.db"`|
| `provenance`  | `required_fields`    | `required_fields`      | `["source_url", "created_at"]` |
| `freshness`   | `max_age_days`       | `max_age_days`         | `90`          |
| `freshness`   | `temporal_detection` | `temporal_detection`   | `True`        |
| `hash_chain`  | `signing_key`        | `signing_key`          | `None`        |
| `otel`        | `enabled`            | `otel_enabled`         | `False`       |
| `otel`        | `service_name`       | `otel_service_name`    | `"provena"`   |
| *(top-level)* | `max_content_bytes`  | `max_content_bytes`    | `65536`       |
| *(top-level)* | `strict_mode`        | `strict_mode`          | `False`       |

### Loading from a YAML file

```python
import yaml
from provena import ContextTrail

with open("provena.yml") as f:
    config = yaml.safe_load(f)

trail = ContextTrail(config=config)
```

Example `provena.yml`:

```yaml
storage:
  backend: sqlite
  path: governance/audit.db

provenance:
  required_fields:
    - source_url
    - created_at

freshness:
  max_age_days: 60
  temporal_detection: true

hash_chain:
  signing_key: ${PROVENA_SIGNING_KEY}

otel:
  enabled: false
  service_name: my-agent

max_content_bytes: 65536
strict_mode: false
```

## Environment Variables

Provena reads these environment variables:

| Variable              | Purpose                                         | Default |
|-----------------------|-------------------------------------------------|---------|
| `PROVENA_SIGNING_KEY` | HMAC signing key for hash chains                 | *(none)* |
| `PROVENA_DISABLED`    | Set to `1`, `true`, or `yes` to disable governance entirely | *(none)* |
| `PROVENA_DB`          | Database path for the CLI                        | `"provena.db"` |

### PROVENA_SIGNING_KEY

Used as the HMAC key when no `signing_key` parameter is passed to the
constructor. The constructor parameter takes precedence.

```bash
export PROVENA_SIGNING_KEY="production-signing-key-2025"
```

### PROVENA_DISABLED

When set, all `@trail.track()` decorators become no-ops and the in-memory
backend is used regardless of the `backend` parameter. Useful for disabling
governance in development or CI environments where audit overhead is
unwanted.

```bash
export PROVENA_DISABLED=1
```

### PROVENA_DB

Sets the default database path for the CLI tool. The `--db` flag overrides
this.

```bash
export PROVENA_DB=/var/lib/provena/audit.db
provena verify  # Uses /var/lib/provena/audit.db
```
