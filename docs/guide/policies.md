# Policy Engine

Policies are optional checks that run after a record is written. Attach them
to a `ContextTrail` when you want a stale, unsigned, or out-of-policy input
to be logged, warned, or blocked. A `BLOCK` decision still leaves the record
in the trail: EU AI Act Article 12 asks for a record of what the system saw,
including inputs you later reject.

## Enforcement levels

| Level | Behavior |
|---|---|
| `LOG` | Record the failure on the evaluation. Logging continues and `log()` returns the record. |
| `WARN` | Same as `LOG`, plus a warning on the `provena` logger. |
| `BLOCK` | The record is persisted, then `log()` raises `PolicyViolation`. |

`PolicyViolation.record` is the row that was just written, so a caller can
inspect the blocked input without losing it from the audit log.

## Built-in checks

```python
from provena import ContextTrail
from provena.policy import (
    EnforcementLevel,
    freshness_check,
    provenance_check,
    require_signing,
    source_allowlist,
)

trail = ContextTrail(
    backend="memory",
    signing_key="governance-key",
    policies=[
        freshness_check(status="STALE", enforcement=EnforcementLevel.BLOCK),
        provenance_check(status="MISSING", enforcement=EnforcementLevel.WARN),
        require_signing(enforcement=EnforcementLevel.BLOCK),
        source_allowlist(
            allowed=["retriever", "tool", "agent"],
            enforcement=EnforcementLevel.BLOCK,
        ),
    ],
)
```

| Check | Fails when |
|---|---|
| `freshness_check(status="STALE")` | The record's freshness status equals `status`. |
| `provenance_check(status="MISSING")` | The record's provenance status equals `status`. |
| `require_signing()` | The trail has no HMAC signing key. |
| `source_allowlist(allowed=[...])` | `record.entry.source` is not in `allowed`. |

`ContextTrail(signing_key=...)` wires `require_signing` to the trail's real
signing state. A `PolicyEngine` built on its own needs the same wiring via
`from_config(..., _signed_ref=...)`.

## TOML config

```toml
[hash_chain]
signing_key_env = "PROVENA_SIGNING_KEY"

[[policies]]
check = "freshness"
status = "STALE"
enforcement = "block"

[[policies]]
check = "provenance"
status = "MISSING"
enforcement = "warn"

[[policies]]
check = "require_signing"
enforcement = "block"

[[policies]]
check = "source_allowlist"
sources = ["retriever", "tool", "agent"]
enforcement = "block"
```

```python
trail = ContextTrail(config="provena.toml")
```

Config check names are `freshness`, `provenance`, `require_signing`, and
`source_allowlist`. An unknown check or enforcement level is skipped with a
warning.

## Per-decorator override

`@trail.track(policies=[...])` replaces the trail-level policy list for that
function. Pass an empty list to log through the decorator with no checks.

```python
from provena.policy import EnforcementLevel, provenance_check

@trail.track(
    source="tool:search",
    policies=[
        provenance_check(status="INCOMPLETE", enforcement=EnforcementLevel.BLOCK),
    ],
)
def search(query: str) -> str:
    return f"result for {query}"
```
