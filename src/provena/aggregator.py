"""Multi-trail aggregation for governing multi-agent systems."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from provena.models import ChainVerdict, ContextSource


@dataclass(frozen=True, slots=True)
class HandoffEdge:
    """A tracked context handoff between two agents' trails.

    Attributes:
        from_trail: Label of the source trail.
        from_record_id: Record ID in the source trail.
        to_trail: Label of the destination trail.
        to_record_id: Record ID in the destination trail.
        run_id: Optional workflow/task run identifier grouping this handoff.
    """

    from_trail: str
    from_record_id: int
    to_trail: str
    to_record_id: int
    run_id: str = ""


@dataclass(frozen=True, slots=True)
class TrailVerdict:
    """Per-trail chain verification result within an aggregation.

    Attributes:
        label: The trail's label in the aggregator.
        verdict: The ChainVerdict from verifying that trail.
    """

    label: str
    verdict: ChainVerdict


@dataclass(frozen=True, slots=True)
class AggregateVerdict:
    """Aggregate chain verification across all trails.

    Attributes:
        all_intact: True only if every trail's chain is intact.
        trail_verdicts: Per-trail verification results.
        total_records: Sum of records across all trails.
    """

    all_intact: bool
    trail_verdicts: tuple[TrailVerdict, ...]
    total_records: int


@dataclass(frozen=True, slots=True)
class EvidenceGap:
    """A detected governance gap in the multi-agent pipeline.

    Attributes:
        trail: Label of the trail where the gap was found.
        gap_type: Category of gap (broken_chain, stale_context,
            missing_provenance, unlinked_handoff).
        details: Human-readable description.
        record_id: Optional record ID related to this gap.
    """

    trail: str
    gap_type: str
    details: str
    record_id: int | None = None


class TrailAggregator:
    """Aggregates governance data across multiple ContextTrail instances.

    Each trail maintains its own independent hash chain. The aggregator
    provides unified querying, summary, verification, handoff tracking,
    and evidence gap detection across all trails.
    """

    def __init__(self) -> None:
        from provena.trail import ContextTrail

        self._trails: dict[str, ContextTrail] = {}
        self._handoffs: list[HandoffEdge] = []

    def add(self, label: str, trail: Any) -> None:
        """Register a named trail.

        Args:
            label: Unique label identifying this trail (e.g. agent name).
            trail: The ContextTrail instance.

        Raises:
            ValueError: If the label is already registered.
        """
        if label in self._trails:
            raise ValueError(f"Trail '{label}' is already registered")
        self._trails[label] = trail

    def remove(self, label: str) -> None:
        """Remove a trail by label."""
        self._trails.pop(label, None)

    @property
    def labels(self) -> tuple[str, ...]:
        """Return the registered trail labels."""
        return tuple(self._trails.keys())

    @property
    def trail_count(self) -> int:
        """Number of registered trails."""
        return len(self._trails)

    def get_trail(self, label: str) -> Any:
        """Return the trail for a given label, or None."""
        return self._trails.get(label)

    def record_handoff(
        self,
        from_trail: str,
        from_record_id: int,
        to_trail: str,
        to_record_id: int,
        run_id: str = "",
    ) -> HandoffEdge:
        """Record a context handoff between two agents' trails.

        Args:
            from_trail: Label of the source agent's trail.
            from_record_id: Record ID of the output in the source trail.
            to_trail: Label of the destination agent's trail.
            to_record_id: Record ID of the input in the destination trail.
            run_id: Optional workflow/task identifier.

        Returns:
            The created HandoffEdge.
        """
        edge = HandoffEdge(
            from_trail=from_trail,
            from_record_id=from_record_id,
            to_trail=to_trail,
            to_record_id=to_record_id,
            run_id=run_id,
        )
        self._handoffs.append(edge)
        return edge

    @property
    def handoffs(self) -> tuple[HandoffEdge, ...]:
        """Return all recorded handoff edges."""
        return tuple(self._handoffs)

    def summary(self) -> dict[str, Any]:
        """Aggregate summary across all trails.

        Returns:
            A dictionary with per-trail and aggregate counts for
            provenance, freshness, and source breakdowns.
        """
        agg_total = 0
        agg_prov: dict[str, int] = {}
        agg_fresh: dict[str, int] = {}
        agg_sources: dict[str, int] = {}
        per_trail: dict[str, dict[str, Any]] = {}

        for label, trail in self._trails.items():
            s = trail.summary()
            per_trail[label] = s
            agg_total += s["total"]
            for status, count in s.get("provenance", {}).items():
                agg_prov[status] = agg_prov.get(status, 0) + count
            for status, count in s.get("freshness", {}).items():
                agg_fresh[status] = agg_fresh.get(status, 0) + count
            for src, count in s.get("sources", {}).items():
                agg_sources[src] = agg_sources.get(src, 0) + count

        return {
            "total": agg_total,
            "trail_count": len(self._trails),
            "provenance": agg_prov,
            "freshness": agg_fresh,
            "sources": agg_sources,
            "handoffs": len(self._handoffs),
            "per_trail": per_trail,
        }

    def query(
        self,
        *,
        trail_label: str | None = None,
        source: ContextSource | str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        provenance_status: str | None = None,
        freshness_status: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query across all trails with optional filters.

        Each returned record includes a ``_trail`` field with the trail label.

        Args:
            trail_label: Restrict to a single trail by label.
            source: Filter by context source type.
            start: Include only records at or after this timestamp.
            end: Include only records at or before this timestamp.
            provenance_status: Filter by provenance validation status.
            freshness_status: Filter by freshness check status.
            run_id: Filter by run_id (matches records involved in
                handoffs tagged with this run_id).
            limit: Maximum total records to return.

        Returns:
            A list of record dicts, each tagged with ``_trail``.
        """
        source_str = source.value if isinstance(source, ContextSource) else source

        targets = (
            {trail_label: self._trails[trail_label]}
            if trail_label and trail_label in self._trails
            else self._trails
        )

        results: list[dict[str, Any]] = []
        per_trail_limit = max(1, limit // max(len(targets), 1))

        for label, trail in targets.items():
            records = trail.query(
                source=source_str,
                start=start,
                end=end,
                provenance_status=provenance_status,
                freshness_status=freshness_status,
                limit=per_trail_limit,
            )
            for r in records:
                r["_trail"] = label
            results.extend(records)

        results.sort(key=lambda r: r.get("timestamp", ""))

        if run_id:
            run_record_keys: set[tuple[str, int]] = set()
            for h in self._handoffs:
                if h.run_id == run_id:
                    run_record_keys.add((h.from_trail, h.from_record_id))
                    run_record_keys.add((h.to_trail, h.to_record_id))
            results = [
                r
                for r in results
                if (r.get("_trail", ""), r.get("id", -1)) in run_record_keys
            ]

        return results[:limit]

    def verify_chain(self) -> AggregateVerdict:
        """Verify chain integrity of every registered trail.

        Returns:
            An AggregateVerdict with per-trail results.
        """
        verdicts: list[TrailVerdict] = []
        total = 0
        all_intact = True

        for label, trail in self._trails.items():
            v = trail.verify_chain()
            verdicts.append(TrailVerdict(label=label, verdict=v))
            total += v.total_records
            if not v.intact:
                all_intact = False

        return AggregateVerdict(
            all_intact=all_intact,
            trail_verdicts=tuple(verdicts),
            total_records=total,
        )

    def timeline(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Merged chronological view across all trails.

        Returns records sorted by timestamp, each tagged with ``_trail``.
        Handoff edges are interleaved as synthetic ``_handoff`` entries.
        """
        records = self.query(start=start, end=end, limit=limit)

        for h in self._handoffs:
            handoff_entry: dict[str, Any] = {
                "_type": "handoff",
                "_trail": f"{h.from_trail} -> {h.to_trail}",
                "from_trail": h.from_trail,
                "from_record_id": h.from_record_id,
                "to_trail": h.to_trail,
                "to_record_id": h.to_record_id,
                "run_id": h.run_id,
            }
            from_record = self._find_record(h.from_trail, h.from_record_id)
            if from_record:
                handoff_entry["timestamp"] = from_record.get("timestamp", "")
            records.append(handoff_entry)

        records.sort(key=lambda r: r.get("timestamp", ""))
        return records[:limit]

    def detect_gaps(self) -> list[EvidenceGap]:
        """Detect governance gaps across all trails.

        Checks for:
        - Broken hash chains
        - Stale context entries
        - Missing provenance
        - Unlinked handoffs (referencing non-existent records/trails)

        Returns:
            A list of EvidenceGap instances.
        """
        gaps: list[EvidenceGap] = []

        for label, trail in self._trails.items():
            verdict = trail.verify_chain()
            if not verdict.intact:
                gaps.append(
                    EvidenceGap(
                        trail=label,
                        gap_type="broken_chain",
                        details=f"Chain broken at record {verdict.broken_at}",
                        record_id=verdict.broken_at,
                    )
                )

            records = trail.query(freshness_status="STALE", limit=1000)
            for r in records:
                gaps.append(
                    EvidenceGap(
                        trail=label,
                        gap_type="stale_context",
                        details=f"Stale content from source '{r.get('source_name', '?')}'",
                        record_id=r.get("id"),
                    )
                )

            records = trail.query(provenance_status="MISSING", limit=1000)
            for r in records:
                gaps.append(
                    EvidenceGap(
                        trail=label,
                        gap_type="missing_provenance",
                        details=f"No provenance metadata on '{r.get('source_name', '?')}'",
                        record_id=r.get("id"),
                    )
                )

        for h in self._handoffs:
            if h.from_trail not in self._trails:
                gaps.append(
                    EvidenceGap(
                        trail=h.from_trail,
                        gap_type="unlinked_handoff",
                        details=f"Source trail '{h.from_trail}' not registered",
                    )
                )
            elif self._trails[h.from_trail]._backend.get(h.from_record_id) is None:
                gaps.append(
                    EvidenceGap(
                        trail=h.from_trail,
                        gap_type="unlinked_handoff",
                        details=f"Record {h.from_record_id} not found in '{h.from_trail}'",
                        record_id=h.from_record_id,
                    )
                )
            if h.to_trail not in self._trails:
                gaps.append(
                    EvidenceGap(
                        trail=h.to_trail,
                        gap_type="unlinked_handoff",
                        details=f"Destination trail '{h.to_trail}' not registered",
                    )
                )
            elif self._trails[h.to_trail]._backend.get(h.to_record_id) is None:
                gaps.append(
                    EvidenceGap(
                        trail=h.to_trail,
                        gap_type="unlinked_handoff",
                        details=f"Record {h.to_record_id} not found in '{h.to_trail}'",
                        record_id=h.to_record_id,
                    )
                )

        return gaps

    def handoffs_for_run(self, run_id: str) -> tuple[HandoffEdge, ...]:
        """Return all handoff edges for a specific run/task ID."""
        return tuple(h for h in self._handoffs if h.run_id == run_id)

    def close(self) -> None:
        """Close all registered trails."""
        for trail in self._trails.values():
            trail.close()

    def __enter__(self) -> TrailAggregator:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _find_record(self, trail_label: str, record_id: int) -> dict[str, Any] | None:
        trail = self._trails.get(trail_label)
        if trail is None:
            return None
        return trail._backend.get(record_id)
