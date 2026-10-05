# Guide for Compliance Teams

This page is for reviewers who need to read a Provena trail without writing
integration code. Developers can follow the linked guides for setup details.

## What a governance report contains

`provena report` prints a compliance score out of four checks: hash-chain
integrity, provenance coverage, freshness (no more than 10% of rows stale),
and HMAC signing. The text and JSON forms list any failed check under
`ISSUES`. The EU AI Act section maps those results to articles:

| Article | What the report shows |
|---|---|
| Art. 10 Data governance | `PASS` only when every record has `VALID` provenance. Otherwise `REVIEW`. |
| Art. 12 Record-keeping | `PASS` when the hash chain is intact, `FAIL` when it is broken. |
| Art. 13 Transparency | `PASS` when the trail contains at least one sourced record. |
| Art. 14 Human oversight | `PRESENT`. Reviewers record decisions with `annotate` (below). |

See [Compliance reports](../guide/reports.md) for the scoring rules.

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

## Article map

| Article | Operational control |
|---|---|
| Art. 9 Risk management | Policy checks that warn or block stale, unsigned, or disallowed sources. Blocked inputs remain in the log. |
| Art. 10 Data lineage | Provenance status on every record, and the Article 10 line in the compliance report. |
| Art. 12 Logging | Hash-chained records, `provena verify`, and optional HMAC signing. |
| Art. 13 Transparency | Source labels, `provena summary`, and the compliance report. |
| Art. 14 Human oversight | `trail.annotate()` reviewer notes. |
| Art. 26 Retention | `provena retain` with a minimum of 180 days. |
