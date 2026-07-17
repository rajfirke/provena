# Chain Verification

Provena maintains a SHA-256 hash chain across all audit records, creating a
tamper-evident log. If any record is modified, deleted, or reordered after the
fact, the chain breaks and verification fails. This gives you cryptographic
proof that your governance trail has not been altered.

## How the Hash Chain Works

Each record's chain hash is computed from four inputs:

1. The **previous record's chain hash** (linking it to its predecessor)
2. The **content hash** (SHA-256 of the raw context bytes)
3. The **source type** string
4. The **timestamp** in ISO format

The computation follows a Merkle-style pattern:

```
chain_hash = SHA-256(previous_hash : content_hash : source : timestamp)
```

The very first record uses a deterministic **genesis hash** as its predecessor:

```python
import hashlib
GENESIS_HASH = hashlib.sha256(b"provena:genesis").hexdigest()
```

This anchors the chain to a known starting point.

## Verifying Chain Integrity

Call `trail.verify_chain()` to recompute every chain hash from the genesis
forward and compare against stored values:

```python
from provena import ContextTrail

trail = ContextTrail(backend="memory")

# Log some context
trail.log(content="First entry", source="retriever")
trail.log(content="Second entry", source="tool:api")
trail.log(content="Third entry", source="agent:planner")

# Verify the entire chain
verdict = trail.verify_chain()
print(verdict.intact)        # True
print(verdict.total_records)  # 3
print(verdict.broken_at)      # None
print(verdict.details)        # "Chain intact"
```

The `ChainVerdict` dataclass returned by `verify_chain()` contains:

| Field           | Type         | Description                                     |
|-----------------|--------------|-------------------------------------------------|
| `intact`        | `bool`       | `True` if every link in the chain is valid       |
| `total_records` | `int`        | Number of records that were checked              |
| `broken_at`     | `int | None` | Record ID where the chain first broke, or `None` |
| `details`       | `str`        | Human-readable summary of the verification       |

## HMAC Signing

For stronger integrity guarantees, enable HMAC-SHA256 signing. When a signing
key is provided, each chain hash is computed using HMAC instead of plain
SHA-256. This means an attacker cannot forge valid chain hashes without the key.

### Using the signing_key parameter

```python
trail = ContextTrail(
    backend="memory",
    signing_key="my-secret-governance-key",
)

trail.log(content="Signed entry", source="retriever")

verdict = trail.verify_chain()
print(verdict.intact)   # True
print(trail.is_signed)  # True
```

### Using the PROVENA_SIGNING_KEY environment variable

```bash
export PROVENA_SIGNING_KEY="my-secret-governance-key"
```

```python
import os
os.environ["PROVENA_SIGNING_KEY"] = "my-secret-governance-key"

trail = ContextTrail(backend="memory")
print(trail.is_signed)  # True
```

The environment variable is checked when no `signing_key` parameter is passed.
The parameter takes precedence over the environment variable.

!!! tip "Key management"
    Store the signing key in a secrets manager or environment variable. Do not
    hard-code it in application source. Rotate keys by creating a new trail
    with the new key -- existing trails remain verifiable with their original
    key.

## Tamper Detection Example

Here is what happens when stored data is modified outside of Provena:

```python
from provena import ContextTrail

trail = ContextTrail(backend="memory")

trail.log(content="Original entry one", source="retriever")
trail.log(content="Original entry two", source="retriever")
trail.log(content="Original entry three", source="retriever")

# Verify before tampering
verdict = trail.verify_chain()
assert verdict.intact is True

# Simulate tampering: modify the content_hash of the second record
records = trail._backend._records  # Access internal storage for demo
records[1]["content_hash"] = "tampered_hash_value"

# Verify after tampering
verdict = trail.verify_chain()
print(verdict.intact)        # False
print(verdict.broken_at)      # 2
print(verdict.details)        # "Chain broken at record 2"
```

The chain breaks at the tampered record because the recomputed hash no longer
matches the stored value. Every record after the tampered one would also fail
if checked individually, since each depends on its predecessor.

## CLI Verification

Verify a trail database from the command line:

```bash
# Verify with default database path
provena verify

# Verify a specific database
provena --db audit.db verify

# Verify with a signing key
provena --db audit.db --signing-key "my-secret-key" verify

# Using environment variables
export PROVENA_DB=audit.db
export PROVENA_SIGNING_KEY="my-secret-key"
provena verify
```

Output on success:

```
PASS -- Chain intact (147 records verified)
```

Output on failure:

```
FAIL -- Chain broken at record 42
```

The CLI exits with code 0 on success and code 1 on failure, making it suitable
for CI/CD pipelines and automated compliance checks.

## Performance

Chain verification is designed to be fast:

- **Hashing**: SHA-256 computation adds sub-millisecond overhead per record
- **HMAC signing**: HMAC-SHA256 adds negligible additional cost over plain SHA-256
- **Verification**: Full chain verification reads all records sequentially; for
  a trail with 10,000 records, expect verification to complete in under one
  second
- **Logging**: Each `trail.log()` call performs one hash computation and one
  database write -- the chain does not require re-reading previous records
  because the previous hash is cached in memory

!!! tip "Verification in CI/CD"
    Add `provena --db $TRAIL_DB verify` as a step in your deployment pipeline.
    This ensures that the governance trail has not been corrupted before
    promoting a build. The non-zero exit code on failure integrates naturally
    with CI systems.
