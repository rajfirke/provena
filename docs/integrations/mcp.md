# MCP Governance Server

A `ContextTrail` is an audit log of information supplied to an agent, such as
retrieved text or a tool result. Your application writes entries to the trail.
Provena's MCP server lets an agent check those entries for provenance,
freshness, and hash-chain integrity. Connecting the server does not log the
agent's context automatically.

## Install and connect

Use Python 3.10 or newer and an MCP client that can start local `stdio` servers.

Install both extras to use the `provena` command and the MCP server:

```bash
pip install "provena[mcp,cli]"
```

The `mcp` extra installs FastMCP. The `cli` extra installs the dependencies
declared for the `provena` command.

Save this example as `seed.py` in the directory where you want `audit.db`:

```python
from datetime import datetime, timezone

from provena import ContextTrail, ProvenanceMetadata

trail = ContextTrail(storage_path="audit.db")
trail.log(
    "Example document content",
    source="retriever",
    source_name="setup_docs",
    provenance=ProvenanceMetadata(
        source_url="https://example.com/docs",
        created_at=datetime.now(timezone.utc),
    ),
)
trail.close()
```

From that directory, run `python seed.py` to create the database. The MCP
server command for that database is:

```bash
provena mcp serve --db audit.db
```

The server uses the `stdio` transport: an MCP client starts the command and
communicates with it over standard input and output. Add these fields to your
client's server entry, using the **absolute path** to the database written by
your application:

```json
{
  "command": "provena",
  "args": ["mcp", "serve", "--db", "/absolute/path/to/audit.db"]
}
```

If your client cannot find `provena`, use the absolute path to its installed
executable for `command`.

If your trail uses HMAC signing, provide the same `PROVENA_SIGNING_KEY` to the
server process. The CLI also accepts `--signing-key` as a global option before
`mcp`.

## Check the trail from an agent

Ask the connected agent to call `get_summary` to confirm it can see your
record. The result includes `total`, provenance and freshness breakdowns,
signing status, and percentages. The example above produces one record;
`get_summary` should report `total: 1` if the server opened the same database.

Before relying on recorded context, an agent can call `check_freshness`,
`check_provenance`, and `verify_chain`, then report any problem before
continuing. Provena also exposes an MCP prompt named `governance_check` that
instructs an agent to make these three checks. A passing result describes the
records inspected; it cannot prove that the application logged every context
input the agent used.

Check `get_summary.total` first. `verify_chain` reports `PASS` for an empty
trail, and `check_freshness` reports no stale entries when `total_checked` is
`0`. Also inspect `unknown`: those records have no usable date. Freshness is
evaluated when a record is logged, not when the MCP tool runs, so an old
`FRESH` verdict may no longer describe the source's current age.

### Tools

| Tool | What it returns | Arguments |
|---|---|---|
| `check_freshness` | Counts of `FRESH`, `STALE`, and `UNKNOWN` records, plus IDs and sources for stale entries | Optional `source`; `limit` defaults to `10` |
| `check_provenance` | Counts of `VALID`, `MISSING`, and `INCOMPLETE` records | Optional `source`; `limit` defaults to `10` |
| `verify_chain` | `PASS` or `FAIL`, record count, and the first broken record ID if verification fails | None |
| `list_violations` | Records marked `STALE`, `MISSING`, or `INCOMPLETE`, deduplicated by ID | Optional `source`; `limit` defaults to `20` |
| `get_summary` | Total records, breakdowns by source and status, signing status, and valid/fresh percentages | None |

`source` is an exact source-type filter, such as `retriever` or `tool`. The
tools return JSON text. For `check_freshness` and `check_provenance`, `limit`
selects the first matching records by ID, not the newest records.
`list_violations` also applies its limit while querying each violation type,
then returns at most `limit` deduplicated entries. Its `total_violations` counts
deduplicated matches from those limited queries before the final list is cut
down; it is not a trail-wide count. These tools are useful for spot checks; use
the [CLI](cli.md) when you need to inspect more of the trail.

### Resources

| URI | Content |
|---|---|
| `provena://health` | Trail health, backend, record count, signing state, and error count |
| `provena://summary` | Total records and provenance, freshness, and source breakdowns |
| `provena://chain/status` | Chain integrity, records verified, and the first broken record ID, if any |

Each resource returns JSON text from the same configured trail.

## Use an existing trail in Python

Use `configure(trail)` to bind a `ContextTrail` in the same Python process
before creating the MCP server:

```python
from provena import ContextTrail
from provena.mcp_server import configure, create_server

trail = ContextTrail(storage_path="audit.db")
try:
    configure(trail)
    create_server().run(transport="stdio")
finally:
    trail.close()
```

`configure()` sets the trail used by the server's tools and resources in this
process. It does not connect a separate `provena mcp serve` process to an
in-memory trail. For separate processes, write to a shared database and
point the server at that database.
