# Buffered Writes

`WriteBuffer` batches `log()` calls in memory and flushes them to the
backend on a background thread. Turn it on when a single process is logging
faster than one storage write per call.

```python
from provena import ContextTrail

trail = ContextTrail(
    storage_path="audit.db",
    buffered=True,
    buffer_size=500,
    flush_interval=1.0,
)
```

The same knobs live under `[storage]` in a TOML or YAML config:
`buffered`, `buffer_size` (default 500), and `flush_interval` (default 1
second). The buffer flushes when it reaches `buffer_size` or when the
interval elapses, whichever comes first.

## What stays in memory

`log()` returns as soon as the record is queued. In buffered mode that
record's `id` is the placeholder `-1` until `flush()` assigns a real row id.
`annotate()` and `TrailAggregator.record_handoff()` need the persisted id, so
call `flush()` first.

`query()`, `summary()`, `record_count`, and `verify_chain()` include rows
that are still queued. `verify_chain()` flushes before it reads.

`close()` stops the background thread and flushes what remains. The process
also flushes on interpreter shutdown and on `SIGTERM`.

```python
trail.log("queued", source="tool")
trail.flush()
trail.close()
```

## One writer, one buffer

The buffer lock serializes flushes inside one `ContextTrail`. It does not
coordinate two processes writing the same SQLite file. For several workers,
use the [PostgreSQL backend](postgresql.md) instead of sharing one `.db`.
