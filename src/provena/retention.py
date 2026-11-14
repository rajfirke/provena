"""Retention policy engine for automatic record lifecycle management."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

_logger = logging.getLogger("provena.retention")

EU_AI_ACT_MINIMUM_DAYS = 180


def _is_tombstone(record: dict[str, Any]) -> bool:
    """Return True if the record has already been tombstoned by retention."""
    if record.get("source_name") == "retained":
        return True
    meta = record.get("metadata_json")
    if meta:
        if isinstance(meta, dict):
            return meta.get("_tombstone") is True
        if isinstance(meta, str) and "_tombstone" in meta:
            try:
                parsed = json.loads(meta)
                if isinstance(parsed, dict) and parsed.get("_tombstone") is True:
                    return True
            except (json.JSONDecodeError, TypeError):
                pass
    return False


@dataclass(frozen=True, slots=True)
class RetentionResult:
    """Outcome of a retention policy execution.

    Attributes:
        archived: Number of records exported before deletion.
        deleted: Number of records actually deleted.
        archive_path: Path to the export archive file, if created.
        details: Human-readable summary.
    """

    archived: int
    deleted: int
    archive_path: str | None = None
    details: str = ""

    def __repr__(self) -> str:
        return f"RetentionResult(archived={self.archived}, deleted={self.deleted})"


class RetentionEngine:
    """Manages record lifecycle with configurable retention policies.

    Enforces EU AI Act minimum retention (180 days by default) and
    supports export-before-delete for compliance archival.
    """

    #: Page size used when scanning for expired records. Exposed as an
    #: attribute (rather than a hardcoded literal) so tests can shrink it to
    #: exercise the multi-batch pagination path without inserting 10k+ rows.
    _QUERY_BATCH_SIZE = 10000
    _AUDIT_RECORD_ID_LIMIT = 100

    def __init__(
        self,
        trail: Any,
        *,
        retention_days: int = 365,
        min_retention_days: int = EU_AI_ACT_MINIMUM_DAYS,
    ) -> None:
        if retention_days < min_retention_days:
            raise ValueError(
                f"retention_days ({retention_days}) must be >= "
                f"min_retention_days ({min_retention_days}) "
                f"for EU AI Act compliance"
            )
        self._trail = trail
        self._retention_days = retention_days
        self._min_retention_days = min_retention_days

    @property
    def retention_days(self) -> int:
        return self._retention_days

    @property
    def min_retention_days(self) -> int:
        return self._min_retention_days

    def find_expired(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Find records older than the retention period.

        Excludes records that have already been tombstoned by a previous
        retention run.

        Args:
            now: Override the current time for testing.

        Returns:
            List of record dicts that have exceeded retention.
        """
        reference = now or datetime.now(timezone.utc)
        cutoff = reference - timedelta(days=self._retention_days)
        batch = self._QUERY_BATCH_SIZE
        expired: list[dict[str, Any]] = []
        offset = 0
        while True:
            page: list[dict[str, Any]] = self._trail.query(
                end=cutoff, limit=batch, offset=offset
            )
            for record in page:
                if not _is_tombstone(record):
                    expired.append(record)
            if len(page) < batch:
                break
            offset += batch
        return expired

    def preview(self, now: datetime | None = None) -> dict[str, Any]:
        """Preview what a retention run would do without making changes.

        Returns:
            Dict with count of records that would be deleted and
            their provenance/freshness breakdown.
        """
        expired = self.find_expired(now=now)
        prov: dict[str, int] = {}
        fresh: dict[str, int] = {}
        for r in expired:
            s = r.get("provenance_status", "MISSING")
            prov[s] = prov.get(s, 0) + 1
            f = r.get("freshness_status", "UNKNOWN")
            fresh[f] = fresh.get(f, 0) + 1

        return {
            "would_delete": len(expired),
            "retention_days": self._retention_days,
            "provenance": prov,
            "freshness": fresh,
        }

    def execute(
        self,
        *,
        archive_path: str | None = None,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> RetentionResult:
        """Execute the retention policy.

        Args:
            archive_path: If provided, export expired records to this
                file before deleting them.
            dry_run: If True, only report what would happen.
            now: Override the current time for testing.

        Returns:
            A RetentionResult with counts of archived and deleted records.
        """
        expired = self.find_expired(now=now)

        if not expired:
            return RetentionResult(
                archived=0,
                deleted=0,
                details="No records exceed the retention period",
            )

        if dry_run:
            return RetentionResult(
                archived=0,
                deleted=0,
                details=f"Dry run: {len(expired)} records would be deleted",
            )

        archived_count = 0
        archive_sha256 = None
        archive_hmac_sha256 = None
        if archive_path:
            archive_data = {
                "archived_at": (now or datetime.now(timezone.utc)).isoformat(),
                "retention_days": self._retention_days,
                "record_count": len(expired),
                "records": expired,
            }
            for record in expired:
                record_id = record.get("id")
                if record_id is not None:
                    anns = self._trail.get_annotations(record_id)
                    if anns:
                        record["_annotations"] = anns

            archive_bytes = json.dumps(archive_data, indent=2, default=str).encode(
                "utf-8"
            )
            archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
            archive_hmac_sha256 = self._trail.sign_payload(archive_bytes)
            with open(archive_path, "wb") as f:
                f.write(archive_bytes)
            archived_count = len(expired)
            _logger.info("Archived %d records to %s", archived_count, archive_path)

        purged_ids = sorted(self._delete_expired(expired))
        records_by_id = {record["id"]: record for record in expired if "id" in record}
        chain_hash_pairs = [
            [record_id, records_by_id[record_id].get("chain_hash")]
            for record_id in purged_ids
        ]
        payload = {
            "action": "retention_purge",
            "deleted": len(purged_ids),
            "archived": archived_count,
            "archive_path": archive_path,
            "archive_sha256": archive_sha256,
            "archive_hmac_sha256": archive_hmac_sha256,
            "retention_days": self._retention_days,
            "purged_record_ids": purged_ids[: self._AUDIT_RECORD_ID_LIMIT],
            "purged_record_ids_truncated": len(purged_ids)
            > self._AUDIT_RECORD_ID_LIMIT,
            "purged_record_ids_sha256": hashlib.sha256(
                json.dumps(purged_ids, separators=(",", ":")).encode()
            ).hexdigest(),
            "purged_chain_hashes_sha256": hashlib.sha256(
                json.dumps(chain_hash_pairs, separators=(",", ":")).encode()
            ).hexdigest(),
        }

        self._trail.log(
            content=json.dumps(payload, separators=(",", ":")),
            source="custom",
            source_name="provena:retention",
        )

        return RetentionResult(
            archived=archived_count,
            deleted=len(purged_ids),
            archive_path=archive_path,
            details=f"Purged {len(purged_ids)} records older than {self._retention_days} days",
        )

    def _delete_expired(self, expired: list[dict[str, Any]]) -> list[int]:
        backend = self._trail._backend
        expired_ids = [
            r["id"]
            for r in expired
            if isinstance(r.get("id"), int) and r["id"] > 0 and not _is_tombstone(r)
        ]

        if not expired_ids:
            return []

        tombstone_meta = json.dumps({"_tombstone": True})

        if hasattr(backend, "_conn") and backend._conn is not None:
            deleted_ids: list[int] = []
            with backend._lock:
                for rid in expired_ids:
                    cursor = backend._conn.execute(
                        "UPDATE trail SET provenance_json = NULL, "
                        "missing_fields = '', metadata_json = ?, "
                        "source_name = 'retained' WHERE id = ? AND source_name != 'retained'",
                        (tombstone_meta, rid),
                    )
                    if cursor.rowcount:
                        deleted_ids.append(rid)
                if deleted_ids:
                    placeholders = ",".join("?" * len(deleted_ids))
                    backend._conn.execute(
                        f"DELETE FROM annotations WHERE record_id IN ({placeholders})",
                        deleted_ids,
                    )
                backend._conn.commit()
            return deleted_ids

        if hasattr(backend, "_records"):
            id_set = set(expired_ids)
            deleted_ids = []
            with backend._lock:
                for r in backend._records:
                    if r.get("id") in id_set and not _is_tombstone(r):
                        r["provenance_json"] = None
                        r["missing_fields"] = ""
                        r["metadata_json"] = tombstone_meta
                        r["source_name"] = "retained"
                        deleted_ids.append(r["id"])
                deleted_id_set = set(deleted_ids)
                backend._annotations = [
                    a
                    for a in backend._annotations
                    if a.get("record_id") not in deleted_id_set
                ]
            return deleted_ids

        if hasattr(backend, "_pool"):
            deleted_ids = []
            with backend._pool.connection() as conn:
                with conn.cursor() as cur:
                    for rid in expired_ids:
                        cur.execute(
                            "UPDATE trail SET provenance_json = NULL, "
                            "missing_fields = '', metadata_json = %s, "
                            "source_name = 'retained' WHERE id = %s AND source_name != 'retained'",
                            (tombstone_meta, rid),
                        )
                        if cur.rowcount:
                            deleted_ids.append(rid)
                            cur.execute(
                                "DELETE FROM annotations WHERE record_id = %s",
                                (rid,),
                            )
                conn.commit()
            return deleted_ids

        _logger.warning("Backend does not support retention")
        return []
