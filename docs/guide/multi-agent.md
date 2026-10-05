# Multi-Agent Aggregation

`TrailAggregator` governs several agents that each keep their own
`ContextTrail`. Every trail has an independent hash chain. The aggregator
adds a shared summary, query, verification, handoff log, timeline, and
evidence-gap report.

## Register named trails

```python
from provena import ContextTrail
from provena.aggregator import TrailAggregator

planner = ContextTrail(backend="memory")
executor = ContextTrail(backend="memory")
reviewer = ContextTrail(backend="memory")

agg = TrailAggregator()
agg.add("planner", planner)
agg.add("executor", executor)
agg.add("reviewer", reviewer)
```

`add` raises `ValueError` if the label is already registered. Use the
aggregator as a context manager to close every registered trail on exit.

## Summary, query, and verification

```python
summary = agg.summary()
# summary["total"], summary["per_trail"], summary["handoffs"], summary["all_signed"]

rows = agg.query(source="tool", limit=50)
# each row includes "_trail" with the agent label

verdict = agg.verify_chain()
verdict.all_intact
verdict.total_records
```

`query(trail_label="executor")` limits the search to one agent. `run_id`
keeps only records that participate in a handoff tagged with that id.

## Handoffs

`record_handoff` links an output record on one trail to an input record on
another. Both ids must already be persisted (`>= 1`). In buffered mode, call
`flush()` and read the stored id before recording the handoff.

```python
plan = planner.log("Use a rolling update", source="tool", source_name="planner")
action = executor.log("kubectl apply -f deployment.yaml", source="tool")

agg.record_handoff(
    "planner",
    plan.id,
    "executor",
    action.id,
    run_id="deploy-001",
)

agg.handoffs_for_run("deploy-001")
```

## Timeline

`timeline()` merges records from every trail in timestamp order and inserts
handoff edges as synthetic entries with `_type="handoff"`.

```python
for event in agg.timeline():
    print(event.get("_type", "record"), event.get("_trail"), event.get("timestamp"))
```

## Evidence gaps

`detect_gaps()` reports broken chains, stale records, missing provenance,
and handoffs that point at a missing trail or record.

```python
for gap in agg.detect_gaps():
    print(gap.trail, gap.gap_type, gap.record_id, gap.details)
```

## Planner, executor, reviewer

```python
from datetime import datetime, timezone

from provena import ContextTrail
from provena.aggregator import TrailAggregator
from provena.models import ProvenanceMetadata

with TrailAggregator() as agg:
    planner = ContextTrail(backend="memory")
    executor = ContextTrail(backend="memory")
    reviewer = ContextTrail(backend="memory")
    agg.add("planner", planner)
    agg.add("executor", executor)
    agg.add("reviewer", reviewer)

    prov = ProvenanceMetadata(
        source_url="https://docs.example.com/deploy",
        created_at=datetime.now(timezone.utc),
    )
    planner.log("Deploy with 3 replicas", source="retriever", provenance=prov)
    plan = planner.log("Use a rolling update", source="tool", source_name="planner")
    action = executor.log(
        "kubectl apply -f deployment.yaml",
        source="tool",
        source_name="kubectl",
    )
    review = reviewer.log(
        "Deployment verified: 3/3 pods running",
        source="agent",
        source_name="verifier",
    )

    agg.record_handoff("planner", plan.id, "executor", action.id, "deploy-001")
    agg.record_handoff("executor", action.id, "reviewer", review.id, "deploy-001")

    assert agg.summary()["total"] == 4
    assert agg.verify_chain().all_intact
    gaps = agg.detect_gaps()
    # The tool and agent rows above have no provenance metadata.
    assert any(gap.gap_type == "missing_provenance" for gap in gaps)
```
