"""Tests for TrailAggregator multi-trail governance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from provena import ContextTrail, ProvenanceMetadata
from provena.aggregator import (
    AggregateVerdict,
    EvidenceGap,
    HandoffEdge,
    TrailAggregator,
)


@pytest.fixture
def two_agent_trails():
    planner = ContextTrail(backend="memory")
    executor = ContextTrail(backend="memory")
    yield planner, executor
    planner.close()
    executor.close()


@pytest.fixture
def populated_aggregator():
    agg = TrailAggregator()
    planner = ContextTrail(backend="memory")
    executor = ContextTrail(backend="memory")
    reviewer = ContextTrail(backend="memory")

    prov = ProvenanceMetadata(
        source_url="https://docs.example.com",
        created_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    planner.log("plan step 1", source="retriever", provenance=prov)
    planner.log("plan step 2", source="tool", source_name="search")

    executor.log("execute action", source="tool", source_name="api")
    executor.log("no provenance data", source="agent", source_name="worker")

    reviewer.log("review output", source="agent", source_name="reviewer")

    agg.add("planner", planner)
    agg.add("executor", executor)
    agg.add("reviewer", reviewer)

    yield agg
    agg.close()


class TestTrailAggregatorBasics:
    def test_add_and_labels(self, two_agent_trails):
        planner, executor = two_agent_trails
        agg = TrailAggregator()
        agg.add("planner", planner)
        agg.add("executor", executor)
        assert agg.labels == ("planner", "executor")
        assert agg.trail_count == 2

    def test_add_duplicate_raises(self, two_agent_trails):
        planner, executor = two_agent_trails
        agg = TrailAggregator()
        agg.add("planner", planner)
        with pytest.raises(ValueError, match="already registered"):
            agg.add("planner", executor)

    def test_remove(self, two_agent_trails):
        planner, executor = two_agent_trails
        agg = TrailAggregator()
        agg.add("planner", planner)
        agg.add("executor", executor)
        agg.remove("planner")
        assert agg.labels == ("executor",)

    def test_get_trail(self, two_agent_trails):
        planner, _executor = two_agent_trails
        agg = TrailAggregator()
        agg.add("planner", planner)
        assert agg.get_trail("planner") is planner
        assert agg.get_trail("nonexistent") is None

    def test_context_manager(self):
        with TrailAggregator() as agg:
            trail = ContextTrail(backend="memory")
            agg.add("test", trail)
            trail.log("data", source="retriever")
            assert agg.summary()["total"] == 1


class TestAggregatedSummary:
    def test_summary_totals(self, populated_aggregator):
        s = populated_aggregator.summary()
        assert s["total"] == 5
        assert s["trail_count"] == 3
        assert s["handoffs"] == 0

    def test_summary_per_trail(self, populated_aggregator):
        s = populated_aggregator.summary()
        assert s["per_trail"]["planner"]["total"] == 2
        assert s["per_trail"]["executor"]["total"] == 2
        assert s["per_trail"]["reviewer"]["total"] == 1

    def test_summary_aggregated_sources(self, populated_aggregator):
        s = populated_aggregator.summary()
        assert "retriever" in s["sources"]
        assert "tool" in s["sources"]
        assert "agent" in s["sources"]

    def test_summary_empty_aggregator(self):
        agg = TrailAggregator()
        s = agg.summary()
        assert s["total"] == 0
        assert s["trail_count"] == 0


class TestAggregatedQuery:
    def test_query_all(self, populated_aggregator):
        records = populated_aggregator.query()
        assert len(records) == 5
        for r in records:
            assert "_trail" in r

    def test_query_by_trail_label(self, populated_aggregator):
        records = populated_aggregator.query(trail_label="planner")
        assert len(records) == 2
        assert all(r["_trail"] == "planner" for r in records)

    def test_query_by_source(self, populated_aggregator):
        records = populated_aggregator.query(source="tool")
        assert len(records) >= 2

    def test_query_by_provenance_status(self, populated_aggregator):
        records = populated_aggregator.query(provenance_status="MISSING")
        assert len(records) >= 1

    def test_query_limit(self, populated_aggregator):
        records = populated_aggregator.query(limit=2)
        assert len(records) == 2

    def test_query_sorted_by_timestamp(self, populated_aggregator):
        records = populated_aggregator.query()
        timestamps = [r.get("timestamp", "") for r in records]
        assert timestamps == sorted(timestamps)


class TestChainVerification:
    def test_verify_all_intact(self, populated_aggregator):
        verdict = populated_aggregator.verify_chain()
        assert isinstance(verdict, AggregateVerdict)
        assert verdict.all_intact
        assert verdict.total_records == 5
        assert len(verdict.trail_verdicts) == 3

    def test_verify_per_trail(self, populated_aggregator):
        verdict = populated_aggregator.verify_chain()
        labels = {tv.label for tv in verdict.trail_verdicts}
        assert labels == {"planner", "executor", "reviewer"}
        for tv in verdict.trail_verdicts:
            assert tv.verdict.intact

    def test_verify_empty_aggregator(self):
        agg = TrailAggregator()
        verdict = agg.verify_chain()
        assert verdict.all_intact
        assert verdict.total_records == 0


class TestHandoffTracking:
    def test_record_handoff(self, populated_aggregator):
        edge = populated_aggregator.record_handoff(
            from_trail="planner",
            from_record_id=2,
            to_trail="executor",
            to_record_id=1,
            run_id="workflow-001",
        )
        assert isinstance(edge, HandoffEdge)
        assert edge.from_trail == "planner"
        assert edge.to_trail == "executor"
        assert edge.run_id == "workflow-001"
        assert len(populated_aggregator.handoffs) == 1

    def test_multiple_handoffs(self, populated_aggregator):
        populated_aggregator.record_handoff("planner", 2, "executor", 1, "run-1")
        populated_aggregator.record_handoff("executor", 2, "reviewer", 1, "run-1")
        assert len(populated_aggregator.handoffs) == 2

    def test_handoffs_for_run(self, populated_aggregator):
        populated_aggregator.record_handoff("planner", 2, "executor", 1, "run-1")
        populated_aggregator.record_handoff("executor", 2, "reviewer", 1, "run-1")
        populated_aggregator.record_handoff("planner", 1, "executor", 1, "run-2")

        run1 = populated_aggregator.handoffs_for_run("run-1")
        assert len(run1) == 2
        run2 = populated_aggregator.handoffs_for_run("run-2")
        assert len(run2) == 1

    def test_query_by_run_id(self, populated_aggregator):
        populated_aggregator.record_handoff("planner", 2, "executor", 1, "run-1")
        records = populated_aggregator.query(run_id="run-1")
        record_keys = {(r["_trail"], r["id"]) for r in records}
        assert ("planner", 2) in record_keys
        assert ("executor", 1) in record_keys

    def test_summary_includes_handoff_count(self, populated_aggregator):
        populated_aggregator.record_handoff("planner", 2, "executor", 1)
        s = populated_aggregator.summary()
        assert s["handoffs"] == 1


class TestTimeline:
    def test_timeline_sorted(self, populated_aggregator):
        timeline = populated_aggregator.timeline()
        timestamps = [e.get("timestamp", "") for e in timeline]
        assert timestamps == sorted(timestamps)

    def test_timeline_includes_handoffs(self, populated_aggregator):
        populated_aggregator.record_handoff("planner", 2, "executor", 1, "run-1")
        timeline = populated_aggregator.timeline()
        handoff_entries = [e for e in timeline if e.get("_type") == "handoff"]
        assert len(handoff_entries) == 1
        assert handoff_entries[0]["from_trail"] == "planner"
        assert handoff_entries[0]["to_trail"] == "executor"

    def test_timeline_limit(self, populated_aggregator):
        timeline = populated_aggregator.timeline(limit=3)
        assert len(timeline) <= 3


class TestEvidenceGapDetection:
    def test_no_gaps_in_clean_aggregator(self):
        agg = TrailAggregator()
        trail = ContextTrail(backend="memory")
        prov = ProvenanceMetadata(
            source_url="https://example.com",
            created_at=datetime.now(timezone.utc),
        )
        trail.log("clean data", source="retriever", provenance=prov)
        agg.add("clean", trail)
        gaps = agg.detect_gaps()
        assert len(gaps) == 0
        agg.close()

    def test_detects_missing_provenance(self, populated_aggregator):
        gaps = populated_aggregator.detect_gaps()
        missing = [g for g in gaps if g.gap_type == "missing_provenance"]
        assert len(missing) >= 1

    def test_detects_unlinked_handoff_bad_trail(self, populated_aggregator):
        populated_aggregator.record_handoff("ghost_agent", 1, "executor", 1)
        gaps = populated_aggregator.detect_gaps()
        unlinked = [g for g in gaps if g.gap_type == "unlinked_handoff"]
        assert any("ghost_agent" in g.details for g in unlinked)

    def test_detects_unlinked_handoff_bad_record(self, populated_aggregator):
        populated_aggregator.record_handoff("planner", 999, "executor", 1)
        gaps = populated_aggregator.detect_gaps()
        unlinked = [g for g in gaps if g.gap_type == "unlinked_handoff"]
        assert any("999" in g.details for g in unlinked)

    def test_gap_dataclass_fields(self):
        gap = EvidenceGap(
            trail="test",
            gap_type="broken_chain",
            details="Chain broken at 5",
            record_id=5,
        )
        assert gap.trail == "test"
        assert gap.gap_type == "broken_chain"
        assert gap.record_id == 5


class TestMultiAgentWorkflow:
    """End-to-end test simulating a real multi-agent pipeline."""

    def test_full_pipeline(self):
        with TrailAggregator() as agg:
            planner = ContextTrail(backend="memory")
            executor = ContextTrail(backend="memory")
            reviewer = ContextTrail(backend="memory")

            agg.add("planner", planner)
            agg.add("executor", executor)
            agg.add("reviewer", reviewer)

            prov = ProvenanceMetadata(
                source_url="https://docs.k8s.io",
                created_at=datetime.now(timezone.utc),
            )
            planner.log(
                "Deploy to k8s with 3 replicas",
                source="retriever",
                provenance=prov,
            )
            r2 = planner.log(
                "Use rolling update strategy",
                source="tool",
                source_name="planner_tool",
            )

            r3 = executor.log(
                "kubectl apply -f deployment.yaml",
                source="tool",
                source_name="kubectl",
            )
            agg.record_handoff("planner", r2.id, "executor", r3.id, "deploy-001")

            r4 = reviewer.log(
                "Deployment verified: 3/3 pods running",
                source="agent",
                source_name="verifier",
            )
            agg.record_handoff("executor", r3.id, "reviewer", r4.id, "deploy-001")

            s = agg.summary()
            assert s["total"] == 4
            assert s["trail_count"] == 3
            assert s["handoffs"] == 2

            verdict = agg.verify_chain()
            assert verdict.all_intact
            assert verdict.total_records == 4

            deploy_handoffs = agg.handoffs_for_run("deploy-001")
            assert len(deploy_handoffs) == 2

            deploy_records = agg.query(run_id="deploy-001")
            assert len(deploy_records) >= 2

            timeline = agg.timeline()
            assert len(timeline) >= 4

            gaps = agg.detect_gaps()
            missing_prov = [g for g in gaps if g.gap_type == "missing_provenance"]
            assert len(missing_prov) >= 1
