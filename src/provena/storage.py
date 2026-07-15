from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from typing import Any, Protocol

SCHEMA_VERSION = 2

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS trail (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash      TEXT NOT NULL,
    source            TEXT NOT NULL,
    source_name       TEXT NOT NULL,
    timestamp         TEXT NOT NULL,
    provenance_json   TEXT,
    provenance_status TEXT NOT NULL DEFAULT 'MISSING',
    missing_fields    TEXT NOT NULL DEFAULT '',
    freshness_status  TEXT NOT NULL DEFAULT 'UNKNOWN',
    chain_hash        TEXT NOT NULL,
    previous_hash     TEXT NOT NULL,
    config_hash       TEXT NOT NULL DEFAULT '',
    metadata_json     TEXT NOT NULL DEFAULT '{}',
    content_type      TEXT NOT NULL DEFAULT 'str',
    truncated         INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_ANNOTATIONS = """\
CREATE TABLE IF NOT EXISTS annotations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id   INTEGER NOT NULL,
    note        TEXT NOT NULL,
    reviewer    TEXT NOT NULL DEFAULT '',
    timestamp   TEXT NOT NULL,
    FOREIGN KEY (record_id) REFERENCES trail(id)
);
"""


class StorageBackend(Protocol):
    def append(self, record: dict[str, Any]) -> int: ...
    def get(self, record_id: int) -> dict[str, Any] | None: ...
    def get_last(self) -> dict[str, Any] | None: ...
    def count(self) -> int: ...
    def all_records(self) -> list[dict[str, Any]]: ...
    def query(
        self,
        *,
        source: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...
    def add_annotation(
        self, record_id: int, note: str, reviewer: str, timestamp: str
    ) -> int: ...
    def close(self) -> None: ...


class SQLiteBackend:
    def __init__(self, path: str = "provena.db") -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self._conn.executescript(
                f"PRAGMA user_version = {SCHEMA_VERSION};\n"
                + _CREATE_TABLE
                + _CREATE_ANNOTATIONS
            )
        elif version < SCHEMA_VERSION:
            self._migrate(version)

    def _migrate(self, from_version: int) -> None:
        if from_version < 2:
            self._conn.execute(
                "ALTER TABLE trail ADD COLUMN freshness_status "
                "TEXT NOT NULL DEFAULT 'UNKNOWN'"
            )
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.commit()

    def append(self, record: dict[str, Any]) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO trail "
                "(content_hash, source, source_name, timestamp, "
                "provenance_json, provenance_status, missing_fields, "
                "freshness_status, "
                "chain_hash, previous_hash, config_hash, "
                "metadata_json, content_type, truncated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    1 if record.get("truncated") else 0,
                ),
            )
            self._conn.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    def get(self, record_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM trail WHERE id = ?", (record_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_last(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM trail ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM trail").fetchone()
            return row[0]

    def all_records(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM trail ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def query(
        self,
        *,
        source: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start.isoformat())
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end.isoformat())

        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"SELECT * FROM trail WHERE {where} ORDER BY id ASC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def add_annotation(
        self, record_id: int, note: str, reviewer: str, timestamp: str
    ) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO annotations (record_id, note, reviewer, timestamp) "
                "VALUES (?, ?, ?, ?)",
                (record_id, note, reviewer, timestamp),
            )
            self._conn.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None  # type: ignore[assignment]


class InMemoryBackend:
    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._annotations: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def append(self, record: dict[str, Any]) -> int:
        with self._lock:
            record_id = len(self._records) + 1
            stored = {**record, "id": record_id}
            stored["truncated"] = 1 if record.get("truncated") else 0
            self._records.append(stored)
            return record_id

    def get(self, record_id: int) -> dict[str, Any] | None:
        if 1 <= record_id <= len(self._records):
            return {**self._records[record_id - 1]}
        return None

    def get_last(self) -> dict[str, Any] | None:
        return {**self._records[-1]} if self._records else None

    def count(self) -> int:
        return len(self._records)

    def all_records(self) -> list[dict[str, Any]]:
        return [{**r} for r in self._records]

    def query(
        self,
        *,
        source: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            results = list(self._records)
        if source is not None:
            results = [r for r in results if r["source"] == source]
        if start is not None:
            start_iso = start.isoformat()
            results = [r for r in results if r["timestamp"] >= start_iso]
        if end is not None:
            end_iso = end.isoformat()
            results = [r for r in results if r["timestamp"] <= end_iso]
        return [{**r} for r in results[:limit]]

    def add_annotation(
        self, record_id: int, note: str, reviewer: str, timestamp: str
    ) -> int:
        with self._lock:
            if not (1 <= record_id <= len(self._records)):
                raise ValueError(f"Record {record_id} does not exist")
            ann_id = len(self._annotations) + 1
            self._annotations.append(
                {
                    "id": ann_id,
                    "record_id": record_id,
                    "note": note,
                    "reviewer": reviewer,
                    "timestamp": timestamp,
                }
            )
            return ann_id

    def close(self) -> None:
        pass
