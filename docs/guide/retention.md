# Retention Policy

AI audit trails can grow rapidly over time. However, managing the lifecycle of an
audit trail is challenging: in a cryptographic hash chain, simply deleting old
rows breaks the hash chain for all subsequent records.

Provena provides a dedicated **Retention Engine** (`RetentionEngine`) that enforces
regulatory data retention minimums, exports records to cold storage prior to
deletion, and uses **cryptographic tombstones** to purge sensitive context while
keeping the hash chain fully intact.

---

## Regulatory Minimums (EU AI Act 180-Day Rule)

Under the EU AI Act (Regulation 2024/1689), high-risk AI system deployers and
providers must retain automated logs for a period appropriate to the system's
purpose:

- **Article 12 & Article 26**: Mandate log retention for **at least six months**
  (180 days) unless applicable Union or national law requires otherwise.

To prevent inadvertent non-compliance, Provena enforces a hard safety floor
through the constant `EU_AI_ACT_MINIMUM_DAYS = 180`.

```python
from provena.retention import EU_AI_ACT_MINIMUM_DAYS

print(EU_AI_ACT_MINIMUM_DAYS)  # 180
```

If you attempt to configure a retention period below 180 days, `RetentionEngine`
raises a `ValueError`:

```python
from provena import ContextTrail
from provena.retention import RetentionEngine

trail = ContextTrail(backend="memory")

# This raises ValueError: retention_days (90) must be >= min_retention_days (180) for EU AI Act compliance
engine = RetentionEngine(trail, retention_days=90)
```

!!! warning "Legal compliance floor"
    The 180-day threshold is an EU legal minimum. Organizations subject to
    sector-specific regulations (such as financial services, healthcare, or
    defense) should configure a longer retention period (e.g., 365 or 730 days).

---

## Using `RetentionEngine` in Python

### Initialization and Configuration

Initialize `RetentionEngine` with an active `ContextTrail` instance:

```python
from provena import ContextTrail
from provena.retention import RetentionEngine

trail = ContextTrail(storage_path="audit.db")

# Default retention: 365 days (with a 180-day minimum floor)
engine = RetentionEngine(trail)

print(engine.retention_days)      # 365
print(engine.min_retention_days)  # 180

# Custom retention period (e.g., 2 years)
long_term_engine = RetentionEngine(trail, retention_days=730)
```

### Previewing Expired Records

Before executing a purge, use `preview()` or `find_expired()` to inspect what
records have exceeded the retention threshold:

```python
# Preview counts and governance breakdown
preview = engine.preview()

print(f"Records to delete: {preview['would_delete']}")
print(f"Retention threshold: {preview['retention_days']} days")
print(f"Provenance breakdown: {preview['provenance']}")
print(f"Freshness breakdown: {preview['freshness']}")

# Or retrieve the raw expired records directly
expired_records = engine.find_expired()
for record in expired_records:
    print(record["id"], record["source"], record["timestamp"])
```

### Dry-Run Execution

To safely simulate policy execution without modifying any stored data, pass
`dry_run=True` to `execute()`:

```python
result = engine.execute(dry_run=True)

print(result.deleted)   # 0
print(result.archived)  # 0
print(result.details)   # "Dry run: 142 records would be deleted" (or "No records exceed the retention period" if none exist)
```

The returned `RetentionResult` dataclass contains:

| Attribute | Type | Description |
|---|---|---|
| `archived` | `int` | Number of records exported to archive storage |
| `deleted` | `int` | Number of records purged / tombstoned |
| `archive_path` | `str \| None` | File path of the export archive, if created |
| `details` | `str` | Human-readable execution summary |

---

## Archive Before Delete

In compliant architectures, records that age out of active operational storage
must often be preserved in durable cold storage (e.g., an S3 Glacier bucket or
read-only archive) for forensic auditability.

Specify `archive_path` during execution to export expired records into a JSON
archive before purging them:

```python
result = engine.execute(archive_path="archives/audit_2025_purge.json")

print(f"Archived: {result.archived} records")
print(f"Purged:   {result.deleted} records")
print(f"Location: {result.archive_path}")
```

### Archive Structure

The exported JSON archive preserves the complete record payload, including any
human oversight annotations attached to the records:

```json
{
  "archived_at": "2026-10-10T12:00:00+00:00",
  "retention_days": 365,
  "record_count": 2,
  "records": [
    {
      "id": 101,
      "content_hash": "a1b2c3d4e5f6...",
      "source": "retriever",
      "source_name": "knowledge_base",
      "timestamp": "2025-08-10T10:00:00+00:00",
      "provenance_status": "VALID",
      "freshness_status": "FRESH",
      "chain_hash": "f6a7b8c9d0e1...",
      "previous_hash": "e1f2a3b4c5d6...",
      "_annotations": [
        {
          "id": 12,
          "record_id": 101,
          "note": "Approved by compliance reviewer",
          "reviewer": "auditor@example.com",
          "timestamp": "2025-08-10T11:00:00+00:00"
        }
      ]
    }
  ]
}
```

---

## Tombstone Architecture & Chain Integrity

### The Hash Chain Challenge

In Provena, each record's `chain_hash` depends on the previous record's
`chain_hash`:

```text
Record N-1 [chain_hash: A] ──> Record N [prev: A, chain_hash: B] ──> Record N+1 [prev: B]
```

If Record $N$ were deleted with a standard `DELETE FROM trail WHERE id = N`, the
chain link between $N-1$ and $N+1$ would be severed, causing all future calls to
`trail.verify_chain()` to fail with a broken chain error.

### How Provena Solves This

Provena uses a **tombstone pattern**:

1. **Hash Chain Maintained**: The database row for the expired record remains in
   storage with its sequential `id`, `chain_hash`, `previous_hash`, `content_hash`,
   and `timestamp` intact.
2. **Context and Metadata Scrubbed**:
   - `provenance_json` is set to `NULL`.
   - `missing_fields` is cleared to `""`.
   - `source_name` is changed to `"retained"`.
   - `metadata_json` is replaced with `{"_tombstone": true}`.
   - Corresponding rows in the `annotations` table are deleted.
3. **Audit Logged**: Provena automatically appends a new audit record to the
   trail documenting the purge action itself:
   ```json
   {
     "action": "retention_purge",
     "deleted": 142,
     "archived": 142,
     "archive_path": "archives/audit_2025_purge.json",
     "retention_days": 365
   }
   ```
   with `source="custom"` and `source_name="provena:retention"`.

After retention execution, **full chain verification remains valid**:

```python
verdict = trail.verify_chain()
assert verdict.intact is True
```

---

## Command-Line Interface (`provena retain`)

You can manage audit trail retention directly from the command line using the
`provena retain` CLI command.

### Command Syntax

```bash
provena [GLOBAL_OPTIONS] retain [OPTIONS]
```

### Options

| Option | Default | Description |
|---|---|---|
| `--max-age INT` | `365` | Purge records older than this many days (minimum `180`) |
| `--archive PATH` | *(none)* | Export expired records to a JSON file before purging |
| `--dry-run` | *(disabled)* | Preview what would be deleted without making changes |

### Examples

#### 1. Dry Run (Preview Purge)

```bash
provena --db audit.db retain --dry-run
```

Output:
```text
Dry run: 45 records would be deleted
```

#### 2. Enforcing Minimum Retention Rules

Attempting to purge records below the 180-day legal minimum will be blocked:

```bash
provena --db audit.db retain --max-age 90
```

Output:
```text
retention_days (90) must be >= min_retention_days (180) for EU AI Act compliance
```
The command terminates with exit code `1`.

#### 3. Archive and Purge

Export expired records older than 180 days to an archive file and apply tombstones:

```bash
provena --db /var/data/provena.db retain --max-age 180 --archive /backup/audit_expired.json
```

Output:
```text
Archived 45 records to /backup/audit_expired.json
DONE -- Deleted 45 records older than 180 days
```

#### 4. Automated CronJob

In production environments, schedule `provena retain` as a periodic maintenance
task (e.g., a daily or monthly cron job):

```bash
#!/bin/bash
set -euo pipefail

DATE=$(date +%Y%m%d)
ARCHIVE_DIR="/var/backups/provena"
mkdir -p "$ARCHIVE_DIR"

provena --db /var/data/provena.db retain \
  --max-age 365 \
  --archive "${ARCHIVE_DIR}/provena_archive_${DATE}.json"
```

---

## Next Steps

- [Compliance Reports Guide](reports.md) -- Generate EU AI Act compliance reports
- [Chain Verification Guide](verification.md) -- Cryptographic integrity verification
- [CLI Reference](../integrations/cli.md) -- Full command-line options
