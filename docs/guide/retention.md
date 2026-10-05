# Retention

`RetentionEngine` tombstones trail records older than a retention window and
can archive them first. The row stays in the hash chain: provenance is
cleared, `source_name` becomes `retained`, and its annotations are removed.
`verify_chain()` still passes. The default floor is 180 days, the EU AI Act
minimum for the logs this engine is meant to keep. A shorter
`retention_days` raises `ValueError`.

## Programmatic use

```python
from provena import ContextTrail
from provena.retention import RetentionEngine

trail = ContextTrail(storage_path="audit.db")
engine = RetentionEngine(trail, retention_days=365)

engine.preview()
# {"would_delete": 12, "retention_days": 365, "provenance": {...}, "freshness": {...}}

result = engine.execute(archive_path="archive.json", dry_run=True)
result = engine.execute(archive_path="archive.json")
```

`would_delete` and `result.deleted` count rows that would be, or were,
tombstoned. `execute` writes those rows and their annotations to
`archive_path` before the update. After the tombstone, it appends a
`provena:retention` record describing the purge. `dry_run=True` reports the
count and does not archive or update anything.

`preview()` counts expired records and breaks them down by provenance and
freshness status without changing storage.

## CLI

```bash
pip install provena[cli]

provena --db audit.db retain --max-age 365 --dry-run
provena --db audit.db retain --max-age 365 --archive backup.json
```

`--max-age` is `retention_days`. Values below 180 are rejected. `--archive`
is the JSON file passed to `execute(archive_path=...)`. The command's own
text says "deleted"; the stored rows are tombstoned, as above.
