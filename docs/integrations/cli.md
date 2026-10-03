# CLI Reference

Provena ships a command-line interface for querying, verifying, and reporting
on your audit trail. Install the CLI extra to get started:

```bash
pip install provena[cli]
```

This installs `click>=8.0` and `rich>=13.0` as dependencies. Rich provides
color-coded table output; if it is unavailable, a plain-text table is used
as a fallback.

## Global options

These options apply to all subcommands and must appear **before** the
subcommand name:

```text
provena [OPTIONS] COMMAND [ARGS]...
```

| Option | Default | Env var | Description |
|---|---|---|---|
| `--db PATH` | `provena.db` | `PROVENA_DB` | SQLite path, or a `postgresql://` URL |
| `--config PATH` | *(none)* | | `provena.toml` or `provena.yaml`. When set, storage and policies come from the file |
| `--signing-key TEXT` | *(none)* | `PROVENA_SIGNING_KEY` | HMAC signing key for hash chain verification |
| `--version` | | | Show the installed Provena version and exit |

```bash
# Use a custom database path
provena --db /var/data/audit.db audit

# Set the signing key via environment variable
export PROVENA_SIGNING_KEY="my-secret-key"
provena verify

# Check the installed version
provena --version
```

---

## `provena audit`

Query the context governance audit log with optional filters.

```text
provena audit [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `--source TEXT` | `-s` | *(all)* | Filter by source type (`retriever`, `tool`, `agent`, `memory`, `mcp`, `custom`) |
| `--limit INT` | `-n` | `20` | Maximum number of records to return |
| `--from DATE` | | *(none)* | Start date filter, format `YYYY-MM-DD` |
| `--to DATE` | | *(none)* | End date filter, format `YYYY-MM-DD` |
| `--format TEXT` | | `table` | Output format: `table` or `json` |

### Table output

The default `table` format uses Rich to render a color-coded table:

```bash
provena audit --limit 5
```

```text
               Provena Audit Trail
 ID   Timestamp             Source    Name       Hash          Provenance   Freshness
-----------------------------------------------------------------------------------------------
  1   2025-07-15T10:23:01   retriever rag        a1b2c3d4e5f6 VALID        FRESH
  2   2025-07-15T10:23:02   retriever rag        b2c3d4e5f6a7 VALID        FRESH
  3   2025-07-15T10:23:03   tool      pricing    c3d4e5f6a7b8 MISSING      UNKNOWN
  4   2025-07-15T10:23:04   agent     planner    d4e5f6a7b8c9 INCOMPLETE   STALE
  5   2025-07-15T10:23:05   retriever rag        e5f6a7b8c9d0 VALID        FRESH
```

!!! info "Color-coded verdicts"
    In terminal output, verdicts are color-coded for quick scanning:

    - **Green**: `VALID` provenance, `FRESH` freshness
    - **Red**: `MISSING` provenance, `STALE` freshness
    - **Yellow**: `INCOMPLETE` provenance
    - **Dim**: `UNKNOWN` freshness

### JSON output

```bash
provena audit --format json --limit 2
```

```json
[
  {
    "id": 1,
    "timestamp": "2025-07-15T10:23:01.123456+00:00",
    "source": "retriever",
    "source_name": "rag",
    "content_hash": "a1b2c3d4e5f6...",
    "provenance_status": "VALID",
    "freshness_status": "FRESH",
    "chain_hash": "f6a7b8c9d0e1..."
  },
  {
    "id": 2,
    "timestamp": "2025-07-15T10:23:02.234567+00:00",
    "source": "retriever",
    "source_name": "rag",
    "content_hash": "b2c3d4e5f6a7...",
    "provenance_status": "VALID",
    "freshness_status": "FRESH",
    "chain_hash": "a7b8c9d0e1f2..."
  }
]
```

### Filtering examples

```bash
# Only retriever entries
provena audit --source retriever

# Last 50 records
provena audit --limit 50

# Records from a date range
provena audit --from 2025-07-01 --to 2025-07-15

# Combine filters with JSON output
provena audit -s tool -n 10 --from 2025-07-01 --format json
```

---

## `provena verify`

Verify the integrity of the hash-chained audit trail. Recomputes every
chain hash from the genesis hash forward and compares each against the
stored value.

```text
provena verify
```

### Options

This command has no subcommand-specific options. Use global options
(`--db`, `--signing-key`) to target a specific database.

### Output

**Intact chain:**

```bash
provena verify
```

```text
PASS -- Chain intact (47 records verified)
```

**Tampered or corrupted chain:**

```bash
provena verify --db corrupted.db
```

```text
FAIL -- Chain broken at record 23
```

!!! warning "Exit codes"
    `provena verify` exits with code **0** on `PASS` and code **1** on
    `FAIL`. Use this in CI pipelines to gate deployments on audit trail
    integrity:

    ```bash
    provena verify --db production.db || echo "Audit trail compromised!"
    ```

**Empty trail:**

```bash
provena verify --db empty.db
```

```text
EMPTY -- No records in the audit trail.
```

---

## `provena report`

Generate a context governance compliance report with chain integrity
verification, provenance breakdowns, and freshness statistics.

```text
provena report [OPTIONS]
```

### Options

| Option | Short | Default | Description |
|---|---|---|---|
| `--format TEXT` | | `json` | Output format: `json`, `text`, or `csv` |
| `--output PATH` | `-o` | *(stdout)* | Write the report to a file instead of stdout |

### JSON report

```bash
provena report
```

```json
{
  "generated_at": "2025-07-15T14:30:00.123456+00:00",
  "database": "provena.db",
  "total_records": 47,
  "chain_integrity": {
    "status": "INTACT",
    "records_verified": 47,
    "broken_at": null
  },
  "provenance": {
    "VALID": 35,
    "MISSING": 8,
    "INCOMPLETE": 4
  },
  "freshness": {
    "FRESH": 40,
    "STALE": 5,
    "UNKNOWN": 2
  },
  "sources": {
    "retriever": 30,
    "tool": 12,
    "agent": 5
  },
  "signed": true
}
```

### Text report

```bash
provena report --format text
```

```text
==================================================
PROVENA GOVERNANCE REPORT
==================================================
Generated: 2025-07-15T14:30:00.123456+00:00
Database:  provena.db
Records:   47
Signed:    Yes

Chain Integrity:
  Status:   INTACT
  Verified: 47 records

Provenance:
  INCOMPLETE   4
  MISSING      8
  VALID        35

Freshness:
  FRESH        40
  STALE        5
  UNKNOWN      2

Sources:
  agent        5
  retriever    30
  tool         12
==================================================
```

### CSV report

```bash
provena report --format csv --output audit_export.csv
```

```text
Report written to audit_export.csv
```

The CSV file contains one row per trail record:

```csv
id,timestamp,source,source_name,content_hash,provenance_status,freshness_status,chain_hash
1,2025-07-15T10:23:01.123456+00:00,retriever,rag,a1b2c3d4...,VALID,FRESH,f6a7b8c9...
2,2025-07-15T10:23:02.234567+00:00,tool,pricing,b2c3d4e5...,MISSING,UNKNOWN,a7b8c9d0...
```

### Writing to a file

```bash
# JSON report to file
provena report --output compliance_report.json

# Text report to file
provena report --format text -o report.txt
```

---

## `provena summary`

Show a quick summary of the audit trail: record count, backend,
signing status, and breakdowns by provenance, freshness, and source.

```text
provena summary
```

### Options

This command has no subcommand-specific options. Use global options
(`--db`, `--signing-key`) to target a specific database.

### Output

```bash
provena summary
```

```text
Records:    47
Backend:    SQLiteBackend
Signed:     Yes

Provenance:
  INCOMPLETE   4
  MISSING      8
  VALID        35

Freshness:
  FRESH        40
  STALE        5
  UNKNOWN      2

Sources:
  agent        5
  retriever    30
  tool         12
```

**Empty trail:**

```bash
provena --db empty.db summary
```

```text
Records:    0
Backend:    SQLiteBackend
Signed:     No
```

---

## `provena stats`

Print one line for CI logs: record count, provenance counts, freshness
counts, chain status, and whether the trail is signed.

```bash
provena --db audit.db stats
```

```text
42 records | provenance: MISSING: 2 VALID: 40 | freshness: FRESH: 38 STALE: 4 | chain: INTACT | signed: yes
```

Empty provenance or freshness maps print `none`.

---

## `provena retain`

Delete records older than `--max-age` days. The minimum is 180. `--dry-run`
only reports what would be removed. `--archive` writes those rows to JSON
before deletion.

```bash
provena --db audit.db retain --max-age 365 --dry-run
provena --db audit.db retain --max-age 365 --archive backup.json
```

---

## `provena migrate`

Copy records and annotations from a SQLite file or a PostgreSQL URL to
another SQLite file or PostgreSQL URL, then verify the destination chain.
The source path must already exist. An empty source prints that there is
nothing to migrate.

```bash
provena migrate --from audit.db --to "postgresql://localhost:5432/provena"
provena migrate --from audit.db --to audit-copy.db --batch-size 500
```

PostgreSQL destinations need `pip install provena[postgres]`.

---

## `provena mcp serve`

Start the MCP governance server on stdio. Pass `--config` on the root
command when the trail should use a config file. An explicit root `--db`
is kept when `mcp serve --db` is omitted. A missing SQLite path is refused
instead of creating an empty file.

```bash
pip install "provena[mcp,cli]"
provena --db audit.db mcp serve
provena --config provena.toml mcp serve
```

`--transport` accepts `stdio`. Tool details are in the
[MCP governance server](mcp.md) guide.

---

## Environment variables

| Variable | Maps to | Description |
|---|---|---|
| `PROVENA_DB` | `--db` | Default database path |
| `PROVENA_SIGNING_KEY` | `--signing-key` | HMAC signing key for chain verification |

Environment variables are overridden by explicit command-line arguments:

```bash
# These are equivalent:
export PROVENA_DB=/var/data/audit.db
provena audit

provena --db /var/data/audit.db audit
```

## Typical CI/CD workflow

```bash
#!/bin/bash
set -e

# Verify the audit trail is intact
provena --db production.db verify

# Generate a compliance report
provena --db production.db report --format json --output report.json

# Quick summary for the build log
provena --db production.db summary

# One-line status for the build log
provena --db production.db stats
```
