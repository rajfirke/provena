# Guide for Compliance Teams

This page is for reviewers who need to read a Provena trail without writing
integration code. Developers can follow the linked guides for setup details.

## What a governance report contains

`provena report` scores four checks, each 25% of the total:

1. Hash chain intact (`verify_chain().intact`)
2. Every record has `VALID` provenance
3. At most 10% of records are `STALE`
4. The trail uses an HMAC signing key

Failed checks appear under `ISSUES` in the JSON and text reports. The EU AI
Act section of the report uses these rules:

| Article | Report status | What the report emits |
|---|---|---|
| Art. 10 Data Governance | `PASS` or `REVIEW` | `PASS` only when the trail is non-empty and every record has `VALID` provenance. Otherwise `REVIEW`. |
| Art. 12 Record-Keeping | `PASS` or `FAIL` | `PASS` when the hash chain is intact. `FAIL` when it is broken. |
| Art. 13 Transparency | `PASS` or `REVIEW` | `PASS` when the trail has at least one sourced record. Otherwise `REVIEW`. |
| Art. 14 Human Oversight | `PRESENT` | Always `PRESENT`, because `trail.annotate()` is available for reviewer notes. |

See [Compliance reports](../guide/reports.md) for scoring, JSON shape, and
PDF output.

## Verify the chain

```bash
provena --db audit.db verify
```

`PASS` means every stored link still matches its predecessor. `FAIL` names
the first record id where the chain breaks. The process exits `1` on
failure, so a pipeline can block on a broken log.

Verification covers the hash-chain fields (`previous_hash`, `content_hash`,
source, and timestamp). It is the check to run before treating an export as
an unaltered log.

## How to read a row

**Provenance** (`provenance_status`):

| Status | Meaning |
|---|---|
| `VALID` | Every required origin field is present. Defaults are source URL and created time. |
| `INCOMPLETE` | Some required origin fields are present and some are missing. |
| `MISSING` | No origin metadata was supplied. |

**Freshness** (`freshness_status`):

| Status | Meaning |
|---|---|
| `FRESH` | Provenance `created_at`, or a date found in the text, is within the max age (90 days by default). Metadata wins when both exist. |
| `STALE` | That date is older than the max age. |
| `UNKNOWN` | No provenance timestamp and no date in the text. |

Source type tells you where the context came from: retriever, tool, agent,
memory, MCP, or a custom label.

## Human oversight

Annotations are reviewer notes attached to an existing record id. They are
the Article 14 trail: the system keeps the original context, and a person
records the decision next to it.

```python
trail.annotate(record_id=42, note="Approved for production use", reviewer="alice")
```

From a review workflow, use the record id printed by `provena audit`, not a
guess. Buffered logging can show a placeholder id until the row is flushed;
annotate the persisted id.

## Retention

High-risk logging under the EU AI Act is expected to be kept for at least
180 days. Provena refuses a shorter retention window.

```bash
provena --db audit.db retain --max-age 365 --dry-run
provena --db audit.db retain --max-age 365 --archive backup.json
```

`--dry-run` only counts rows that would be tombstoned. The row stays in the
hash chain: provenance is cleared, `source_name` becomes `retained`, and its
annotations are removed, so `provena verify` still passes. `--archive` writes
those rows to JSON before that update. A purge record is appended after the
tombstone. Details are in [Retention](../guide/retention.md).
