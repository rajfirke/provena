"""Retention policy engine for automatic record lifecycle management."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

_logger = logging.getLogger("provena.retention")

EU_AI_ACT_MINIMUM_DAYS = 180


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


class RetentionEngine:
    """Manages record lifecycle with configurable retention policies.

    Enforces EU AI Act minimum retention (180 days by default) and
    supports export-before-delete for compliance archival.
    """

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

        Args:
            now: Override the current time for testing.

        Returns:
            List of record dicts that have exceeded retention.
        """
        reference = now or datetime.now(timezone.utc)
        cutoff = reference - timedelta(days=self._retention_days)
        return self._trail.query(end=cutoff, limit=10000)

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

            with open(archive_path, "w") as f:
                json.dump(archive_data, f, indent=2, default=str)
            archived_count = len(expired)
            _logger.info("Archived %d records to %s", archived_count, archive_path)

        deleted_count = self._delete_expired(expired)

        self._trail.log(
            content=json.dumps(
                {
                    "action": "retention_purge",
                    "deleted": deleted_count,
                    "archived": archived_count,
                    "archive_path": archive_path,
                    "retention_days": self._retention_days,
                }
            ),
            source="custom",
            source_name="provena:retention",
        )

        return RetentionResult(
            archived=archived_count,
            deleted=deleted_count,
            archive_path=archive_path,
            details=f"Retained {deleted_count} records older than {self._retention_days} days",
        )

    def _delete_expired(self, expired: list[dict[str, Any]]) -> int:
        backend = self._trail._backend
        expired_ids = [r["id"] for r in expired if "id" in r]

        if not expired_ids:
            return 0

        tombstone_meta = json.dumps({"_tombstone": True})

        if hasattr(backend, "_conn") and backend._conn is not None:
            placeholders = ",".join("?" * len(expired_ids))
            with backend._lock:
                backend._conn.execute(
                    f"DELETE FROM annotations WHERE record_id IN ({placeholders})",
                    expired_ids,
                )
                for rid in expired_ids:
                    backend._conn.execute(
                        "UPDATE trail SET provenance_json = NULL, "
                        "missing_fields = '', metadata_json = ?, "
                        "source_name = 'retained' WHERE id = ?",
                        (tombstone_meta, rid),
                    )
                backend._conn.commit()
            return len(expired_ids)

        if hasattr(backend, "_records"):
            id_set = set(expired_ids)
            count = 0
            with backend._lock:
                for r in backend._records:
                    if r.get("id") in id_set:
                        r["provenance_json"] = None
                        r["missing_fields"] = ""
                        r["metadata_json"] = tombstone_meta
                        r["source_name"] = "retained"
                        count += 1
                backend._annotations = [
                    a for a in backend._annotations if a.get("record_id") not in id_set
                ]
            return count

        if hasattr(backend, "_pool"):
            with backend._pool.connection() as conn:
                with conn.cursor() as cur:
                    for rid in expired_ids:
                        cur.execute(
                            "DELETE FROM annotations WHERE record_id = %s",
                            (rid,),
                        )
                        cur.execute(
                            "UPDATE trail SET provenance_json = NULL, "
                            "missing_fields = '', metadata_json = %s, "
                            "source_name = 'retained' WHERE id = %s",
                            (tombstone_meta, rid),
                        )
                conn.commit()
            return len(expired_ids)

        _logger.warning("Backend does not support retention")
        return 0
