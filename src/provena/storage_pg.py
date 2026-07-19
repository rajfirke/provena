"""PostgreSQL storage backend for the context audit trail."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

SCHEMA_VERSION = 1

_CREATE_TRAIL = """\
CREATE TABLE IF NOT EXISTS trail (
    id                BIGSERIAL PRIMARY KEY,
    content_hash      TEXT NOT NULL,
    source            TEXT NOT NULL,
    source_name       TEXT NOT NULL,
    timestamp         TIMESTAMPTZ NOT NULL,
    provenance_json   JSONB,
    provenance_status TEXT NOT NULL DEFAULT 'MISSING',
    missing_fields    TEXT NOT NULL DEFAULT '',
    freshness_status  TEXT NOT NULL DEFAULT 'UNKNOWN',
    chain_hash        TEXT NOT NULL,
    previous_hash     TEXT NOT NULL,
    config_hash       TEXT NOT NULL DEFAULT '',
    metadata_json     JSONB NOT NULL DEFAULT '{}',
    content_type      TEXT NOT NULL DEFAULT 'str',
    truncated         BOOLEAN NOT NULL DEFAULT FALSE
);
"""

_CREATE_ANNOTATIONS = """\
CREATE TABLE IF NOT EXISTS annotations (
    id          BIGSERIAL PRIMARY KEY,
    record_id   BIGINT NOT NULL REFERENCES trail(id),
    note        TEXT NOT NULL,
    reviewer    TEXT NOT NULL DEFAULT '',
    timestamp   TIMESTAMPTZ NOT NULL
);
"""

_CREATE_INDEXES = """\
CREATE INDEX IF NOT EXISTS idx_trail_source ON trail(source);
CREATE INDEX IF NOT EXISTS idx_trail_timestamp ON trail(timestamp);
CREATE INDEX IF NOT EXISTS idx_trail_provenance_status ON trail(provenance_status);
CREATE INDEX IF NOT EXISTS idx_trail_freshness_status ON trail(freshness_status);
CREATE INDEX IF NOT EXISTS idx_annotations_record_id ON annotations(record_id);
"""

_SCHEMA_VERSION_TABLE = """\
CREATE TABLE IF NOT EXISTS provena_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class PostgreSQLBackend:
    """PostgreSQL-based storage backend with connection pooling.

    Uses psycopg v3 with ``psycopg_pool.ConnectionPool`` for concurrent
    access. Chain hash ordering is enforced via ``pg_advisory_xact_lock``.
    """

    def __init__(
        self,
        conninfo: str,
        pool_size: int = 5,
        min_pool_size: int = 1,
    ) -> None:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError:
            raise ImportError(
                "psycopg is required for the PostgreSQL backend. "
                "Install with: pip install provena[postgres]"
            ) from None

        self._pool: Any = ConnectionPool(
            conninfo,
            min_size=min_pool_size,
            max_size=pool_size,
            open=True,
        )
        self._init_schema()

    def _init_schema(self) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA_VERSION_TABLE)
                cur.execute(_CREATE_TRAIL)
                cur.execute(_CREATE_ANNOTATIONS)
                for stmt in _CREATE_INDEXES.strip().split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        cur.execute(stmt)
                cur.execute(
                    "INSERT INTO provena_meta (key, value) VALUES ('schema_version', %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (str(SCHEMA_VERSION),),
                )
            conn.commit()

    def append(self, record: dict[str, Any]) -> int:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(1)")
                cur.execute(
                    "INSERT INTO trail "
                    "(content_hash, source, source_name, timestamp, "
                    "provenance_json, provenance_status, missing_fields, "
                    "freshness_status, "
                    "chain_hash, previous_hash, config_hash, "
                    "metadata_json, content_type, truncated) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "RETURNING id",
                    (
                        record["content_hash"],
                        record["source"],
                        record["source_name"],
                        record["timestamp"],
                        record.get("provenance_json"),
                        record.get("provenance_status", "MISSING"),
                        record.get("missing_fields", ""),
                        record.get("freshness_status", "UNKNOWN"),
                        record["chain_hash"],
                        record["previous_hash"],
                        record.get("config_hash", ""),
                        record.get("metadata_json", "{}"),
                        record.get("content_type", "str"),
                        bool(record.get("truncated")),
                    ),
                )
                row = cur.fetchone()
                assert row is not None
                record_id: int = row[0]
            conn.commit()
        return record_id

    def get(self, record_id: int) -> dict[str, Any] | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM trail WHERE id = %s", (record_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return _row_to_dict(cur, row)

    def get_last(self) -> dict[str, Any] | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM trail ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row is None:
                return None
            return _row_to_dict(cur, row)

    def count(self) -> int:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trail")
            row = cur.fetchone()
            assert row is not None
            return int(row[0])

    def all_records(self) -> list[dict[str, Any]]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM trail ORDER BY id ASC")
            return [_row_to_dict(cur, r) for r in cur.fetchall()]

    def query(
        self,
        *,
        source: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        provenance_status: str | None = None,
        freshness_status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if source is not None:
            clauses.append("source = %s")
            params.append(source)
        if start is not None:
            clauses.append("timestamp >= %s")
            params.append(start.isoformat())
        if end is not None:
            clauses.append("timestamp <= %s")
            params.append(end.isoformat())
        if provenance_status is not None:
            clauses.append("provenance_status = %s")
            params.append(provenance_status)
        if freshness_status is not None:
            clauses.append("freshness_status = %s")
            params.append(freshness_status)

        where = " AND ".join(clauses) if clauses else "TRUE"
        sql = f"SELECT * FROM trail WHERE {where} ORDER BY id ASC LIMIT %s"
        params.append(limit)

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return [_row_to_dict(cur, r) for r in cur.fetchall()]

    def add_annotation(
        self, record_id: int, note: str, reviewer: str, timestamp: str
    ) -> int:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO annotations (record_id, note, reviewer, timestamp) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (record_id, note, reviewer, timestamp),
                )
                row = cur.fetchone()
                assert row is not None
                ann_id: int = row[0]
            conn.commit()
        return ann_id

    def get_annotations(self, record_id: int) -> list[dict[str, Any]]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, record_id, note, reviewer, timestamp "
                "FROM annotations WHERE record_id = %s ORDER BY id ASC",
                (record_id,),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None


def _row_to_dict(cursor: Any, row: tuple[Any, ...]) -> dict[str, Any]:
    cols = [desc[0] for desc in cursor.description]
    d = dict(zip(cols, row, strict=True))
    if "truncated" in d:
        d["truncated"] = 1 if d["truncated"] else 0
    ts = d.get("timestamp")
    if ts is not None and not isinstance(ts, str):
        d["timestamp"] = ts.isoformat()
    for json_field in ("provenance_json", "metadata_json"):
        val = d.get(json_field)
        if val is not None and not isinstance(val, str):
            d[json_field] = json.dumps(val)
    return d
