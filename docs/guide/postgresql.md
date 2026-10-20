# PostgreSQL

The PostgreSQL backend stores the same trail as SQLite and is the backend to
use when more than one process appends to the same trail. Each `append` takes
`pg_advisory_xact_lock` and, when the in-memory previous hash is stale,
recomputes the tip from the last stored row before writing.

SQLite does not do that. One SQLite file should have one `ContextTrail`.

## Install

```bash
pip install provena[postgres]
```

This installs `psycopg[pool]>=3.1`.

## Connect

Pass a `postgresql://` or `postgres://` URL as `storage_path`. A URL selects
the PostgreSQL backend even when `backend` is left at its default.

```python
from provena import ContextTrail

trail = ContextTrail(
    storage_path="postgresql://provena:provena@localhost:5432/provena",
)
```

Or set it in a config file:

```toml
[storage]
backend = "postgresql"
path = "postgresql://provena:provena@localhost:5432/provena"
pool_size = 5
```

```python
trail = ContextTrail(config="provena.toml")
```

`pool_size` is the maximum size of the `psycopg_pool` connection pool
(default 5). The schema (`trail`, `annotations`, `provena_meta`) is created
on first connect.

## Migrate from SQLite

```bash
provena migrate \
  --from audit.db \
  --to "postgresql://provena:provena@localhost:5432/provena"
```

`provena migrate` copies records and annotations, then runs `verify_chain()`
on the destination. See the [CLI reference](../integrations/cli.md).
