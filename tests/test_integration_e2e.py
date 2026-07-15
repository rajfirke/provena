"""End-to-end integration test simulating a real multi-source AI agent pipeline.

Scenario:
    An orchestrator agent retrieves documents via RAG, calls a pricing API tool,
    and delegates a sub-task to a specialist agent.  Provena governs every piece
    of context that flows through the system -- this test proves the governance
    chain stays intact, provenance and freshness are correctly classified, and
    the audit trail is queryable, exportable, and verifiable from both the
    library API and the CLI.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

from click.testing import CliRunner

from provena.cli.main import cli
from provena.models import ContextSource, ProvenanceMetadata
from provena.trail import ContextTrail

# ---------------------------------------------------------------------------
# Realistic content fixtures
# ---------------------------------------------------------------------------

RAG_DOC_FRESH = (
    "Kubernetes 1.30 introduces structured authorization configuration as a "
    "stable feature.  CEL-based admission policies graduate to GA.  Node memory "
    "swap support is now beta.  Updated July 2026.  See https://kubernetes.io/"
    "blog/2026/07/01/kubernetes-v1-30-release/ for the full changelog."
)

RAG_DOC_STALE = (
    "As of 2023, the recommended container runtime for production clusters is "
    "containerd 1.6.x.  CRI-O 1.24 remains supported but receives only "
    "security patches.  Docker Engine (via dockershim) was removed in "
    "Kubernetes 1.24 released in May 2022."
)

RAG_DOC_NO_PROVENANCE = (
    "Horizontal Pod Autoscaler can target custom metrics exposed through the "
    "metrics.k8s.io aggregation layer.  Configure minReplicas and maxReplicas "
    "to bound the scaling range.  Use behavior.scaleDown.stabilizationWindowSeconds "
    "to dampen flapping under spiky load patterns."
)

TOOL_PRICING_RESPONSE = json.dumps(
    {
        "provider": "aws",
        "service": "eks",
        "region": "us-east-1",
        "instance_type": "m7g.xlarge",
        "on_demand_hourly_usd": 0.1632,
        "spot_hourly_usd": 0.0612,
        "reserved_1yr_hourly_usd": 0.1027,
        "currency": "USD",
        "effective_date": "2026-07-01",
        "source_api": "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEKS/current/us-east-1/index.json",
    }
)

AGENT_MESSAGE = (
    "TASK RESULT from cost-estimator-agent:\n"
    "Based on the EKS pricing data for us-east-1, a 5-node m7g.xlarge cluster "
    "running 24/7 would cost approximately $587.52/month on-demand or "
    "$220.32/month using spot instances (62% savings).  The 1-year reserved "
    "pricing comes to $369.72/month.  Recommendation: use a mix of 2 on-demand "
    "nodes for baseline + 3 spot nodes for burst capacity, yielding an estimated "
    "$509.76/month with improved availability over pure-spot."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_provenance() -> ProvenanceMetadata:
    """Provenance for a document updated within the last week."""
    return ProvenanceMetadata(
        source_url="https://kubernetes.io/blog/2026/07/01/kubernetes-v1-30-release/",
        author="Kubernetes Release Team",
        created_at=datetime.now(timezone.utc) - timedelta(days=5),
        version="v1.30",
    )


def _stale_provenance() -> ProvenanceMetadata:
    """Provenance with a creation date older than 90 days."""
    return ProvenanceMetadata(
        source_url="https://kubernetes.io/docs/setup/production-environment/container-runtimes/",
        author="Kubernetes Documentation Contributors",
        created_at=datetime(2023, 3, 15, tzinfo=timezone.utc),
        version="v1.24",
    )


def _tool_provenance() -> ProvenanceMetadata:
    """Provenance for an API tool call with a recent effective date."""
    return ProvenanceMetadata(
        source_url="https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEKS/current/us-east-1/index.json",
        author="AWS Pricing API",
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        version="2026-07-01",
    )


def _populate_trail(trail: ContextTrail) -> list:
    """Feed the full agent scenario into a trail and return the records."""
    records = []

    # -- Step 1: RAG retriever returns 3 documents --
    r = trail.log(
        RAG_DOC_FRESH,
        source=ContextSource.RETRIEVER,
        source_name="k8s-docs-vectordb",
        provenance=_fresh_provenance(),
        metadata={"similarity_score": 0.94, "chunk_id": "k8s-v130-release-0042"},
    )
    records.append(r)

    r = trail.log(
        RAG_DOC_STALE,
        source=ContextSource.RETRIEVER,
        source_name="k8s-docs-vectordb",
        provenance=_stale_provenance(),
        metadata={"similarity_score": 0.87, "chunk_id": "container-runtimes-0017"},
    )
    records.append(r)

    r = trail.log(
        RAG_DOC_NO_PROVENANCE,
        source=ContextSource.RETRIEVER,
        source_name="k8s-docs-vectordb",
        metadata={"similarity_score": 0.81, "chunk_id": "hpa-custom-metrics-0003"},
    )
    records.append(r)

    # -- Step 2: Tool call returns pricing data --
    r = trail.log(
        TOOL_PRICING_RESPONSE,
        source=ContextSource.TOOL,
        source_name="aws-pricing-api",
        provenance=_tool_provenance(),
        metadata={"latency_ms": 342, "cache_hit": False},
    )
    records.append(r)

    # -- Step 3: Agent-to-agent message --
    r = trail.log(
        AGENT_MESSAGE,
        source=ContextSource.AGENT,
        source_name="cost-estimator-agent",
        metadata={"agent_model": "claude-sonnet-4", "tokens_used": 487},
    )
    records.append(r)

    return records


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestMultiSourceAgentPipeline:
    """Integration test covering a full multi-source agent governance flow."""

    # ---- 1. RAG retriever with mixed provenance/freshness ----

    def test_rag_fresh_document_governance(self):
        with ContextTrail(backend="memory") as trail:
            record = trail.log(
                RAG_DOC_FRESH,
                source=ContextSource.RETRIEVER,
                source_name="k8s-docs-vectordb",
                provenance=_fresh_provenance(),
            )
            assert record is not None
            assert record.provenance_result.status == "VALID"
            assert record.freshness_result.status == "FRESH"
            assert record.entry.source == ContextSource.RETRIEVER

    def test_rag_stale_document_governance(self):
        with ContextTrail(backend="memory") as trail:
            record = trail.log(
                RAG_DOC_STALE,
                source=ContextSource.RETRIEVER,
                source_name="k8s-docs-vectordb",
                provenance=_stale_provenance(),
            )
            assert record is not None
            assert record.provenance_result.status == "VALID"
            assert record.freshness_result.status == "STALE"

    def test_rag_no_provenance_document(self):
        with ContextTrail(backend="memory") as trail:
            record = trail.log(
                RAG_DOC_NO_PROVENANCE,
                source=ContextSource.RETRIEVER,
                source_name="k8s-docs-vectordb",
            )
            assert record is not None
            assert record.provenance_result.status == "MISSING"
            # No provenance created_at and no temporal markers in content
            assert record.freshness_result.status == "UNKNOWN"

    # ---- 2. Tool call with provenance ----

    def test_tool_call_with_provenance(self):
        with ContextTrail(backend="memory") as trail:
            record = trail.log(
                TOOL_PRICING_RESPONSE,
                source=ContextSource.TOOL,
                source_name="aws-pricing-api",
                provenance=_tool_provenance(),
                metadata={"latency_ms": 342, "cache_hit": False},
            )
            assert record is not None
            assert record.provenance_result.status == "VALID"
            assert record.freshness_result.status == "FRESH"
            assert record.entry.source == ContextSource.TOOL
            assert record.entry.metadata["latency_ms"] == 342

    # ---- 3. Agent-to-agent message ----

    def test_agent_message_governance(self):
        with ContextTrail(backend="memory") as trail:
            record = trail.log(
                AGENT_MESSAGE,
                source=ContextSource.AGENT,
                source_name="cost-estimator-agent",
                metadata={"agent_model": "claude-sonnet-4", "tokens_used": 487},
            )
            assert record is not None
            assert record.entry.source == ContextSource.AGENT
            assert record.entry.source_name == "cost-estimator-agent"
            # Agent messages have no provenance by default
            assert record.provenance_result.status == "MISSING"

    # ---- 4. Full hash chain integrity ----

    def test_full_chain_integrity(self):
        with ContextTrail(backend="memory") as trail:
            records = _populate_trail(trail)
            assert all(r is not None for r in records)

            verdict = trail.verify_chain()
            assert verdict.intact is True
            assert verdict.total_records == 5
            assert verdict.broken_at is None

            # Verify sequential linking: each record's previous_hash matches
            # the prior record's chain_hash
            for i in range(1, len(records)):
                assert records[i].previous_hash == records[i - 1].chain_hash, (
                    f"Chain link broken between record {i - 1} and {i}"
                )

    # ---- 5. Query by source type ----

    def test_query_by_source_type_counts(self):
        with ContextTrail(backend="memory") as trail:
            _populate_trail(trail)

            retriever_records = trail.query(source=ContextSource.RETRIEVER)
            assert len(retriever_records) == 3

            tool_records = trail.query(source=ContextSource.TOOL)
            assert len(tool_records) == 1

            agent_records = trail.query(source=ContextSource.AGENT)
            assert len(agent_records) == 1

            all_records = trail.query()
            assert len(all_records) == 5

    # ---- 6. Summary provenance/freshness breakdowns ----

    def test_summary_breakdowns(self):
        with ContextTrail(backend="memory") as trail:
            _populate_trail(trail)
            s = trail.summary()

            assert s["total"] == 5

            # Provenance: fresh doc + stale doc + tool = 3 VALID, no-prov doc + agent = 2 MISSING
            assert s["provenance"]["VALID"] == 3
            assert s["provenance"]["MISSING"] == 2

            # Freshness: fresh doc + tool = 2 FRESH, stale doc = 1 STALE,
            # no-prov doc + agent msg = 2 UNKNOWN
            assert s["freshness"]["FRESH"] == 2
            assert s["freshness"]["STALE"] == 1
            assert s["freshness"]["UNKNOWN"] == 2

            # Source breakdown
            assert s["sources"]["retriever"] == 3
            assert s["sources"]["tool"] == 1
            assert s["sources"]["agent"] == 1

            assert s["signed"] is False

    # ---- 7. Export to JSON ----

    def test_export_json_valid(self):
        with ContextTrail(backend="memory") as trail:
            _populate_trail(trail)
            exported = trail.export(format="json")

            data = json.loads(exported)
            assert isinstance(data, list)
            assert len(data) == 5

            # Every record must have the core governance fields
            required_fields = {
                "id",
                "content_hash",
                "source",
                "source_name",
                "timestamp",
                "chain_hash",
                "previous_hash",
                "provenance_status",
                "freshness_status",
            }
            for record in data:
                assert required_fields.issubset(record.keys()), (
                    f"Record {record.get('id')} missing fields: "
                    f"{required_fields - record.keys()}"
                )

            # Verify source values
            sources_in_export = [r["source"] for r in data]
            assert sources_in_export.count("retriever") == 3
            assert sources_in_export.count("tool") == 1
            assert sources_in_export.count("agent") == 1

    # ---- 8. HMAC signing produces different but verifiable chain ----

    def test_hmac_signing_different_hashes(self):
        unsigned_trail = ContextTrail(backend="memory")
        signed_trail = ContextTrail(
            backend="memory", signing_key="agent-governance-secret-key-2026"
        )

        assert not unsigned_trail.is_signed
        assert signed_trail.is_signed

        # Log the same content to both trails
        content = RAG_DOC_FRESH
        prov = _fresh_provenance()

        r_unsigned = unsigned_trail.log(
            content,
            source=ContextSource.RETRIEVER,
            source_name="test",
            provenance=prov,
        )
        r_signed = signed_trail.log(
            content,
            source=ContextSource.RETRIEVER,
            source_name="test",
            provenance=prov,
        )

        assert r_unsigned is not None
        assert r_signed is not None

        # Content hashes are the same (SHA-256 of the content)
        assert r_unsigned.entry.content_hash == r_signed.entry.content_hash

        # Chain hashes MUST differ (HMAC vs plain SHA-256)
        assert r_unsigned.chain_hash != r_signed.chain_hash

        # Both chains must independently verify
        assert unsigned_trail.verify_chain().intact is True
        assert signed_trail.verify_chain().intact is True

        # Signed summary reflects signing
        assert signed_trail.summary()["signed"] is True
        assert unsigned_trail.summary()["signed"] is False

        unsigned_trail.close()
        signed_trail.close()

    def test_hmac_signed_multi_record_chain(self):
        """Full pipeline with HMAC signing still produces a verifiable chain."""
        with ContextTrail(backend="memory", signing_key="hmac-test-key") as trail:
            records = _populate_trail(trail)
            assert all(r is not None for r in records)

            verdict = trail.verify_chain()
            assert verdict.intact is True
            assert verdict.total_records == 5
            assert trail.is_signed is True

    # ---- 9. InMemoryBackend and SQLiteBackend produce identical results ----

    def test_backend_equivalence(self):
        """Both backends must produce the same governance verdicts for identical input."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            memory_trail = ContextTrail(backend="memory")
            sqlite_trail = ContextTrail(storage_path=db_path)

            # Feed identical content to both
            for trail in (memory_trail, sqlite_trail):
                trail.log(
                    RAG_DOC_FRESH,
                    source=ContextSource.RETRIEVER,
                    source_name="k8s-docs-vectordb",
                    provenance=_fresh_provenance(),
                    metadata={"similarity_score": 0.94},
                )
                trail.log(
                    RAG_DOC_STALE,
                    source=ContextSource.RETRIEVER,
                    source_name="k8s-docs-vectordb",
                    provenance=_stale_provenance(),
                    metadata={"similarity_score": 0.87},
                )
                trail.log(
                    RAG_DOC_NO_PROVENANCE,
                    source=ContextSource.RETRIEVER,
                    source_name="k8s-docs-vectordb",
                )
                trail.log(
                    TOOL_PRICING_RESPONSE,
                    source=ContextSource.TOOL,
                    source_name="aws-pricing-api",
                    provenance=_tool_provenance(),
                )
                trail.log(
                    AGENT_MESSAGE,
                    source=ContextSource.AGENT,
                    source_name="cost-estimator-agent",
                )

            # Both chains must be intact
            mem_verdict = memory_trail.verify_chain()
            sql_verdict = sqlite_trail.verify_chain()
            assert mem_verdict.intact is True
            assert sql_verdict.intact is True
            assert mem_verdict.total_records == sql_verdict.total_records == 5

            # Summaries must have identical governance breakdowns
            mem_summary = memory_trail.summary()
            sql_summary = sqlite_trail.summary()
            assert mem_summary["total"] == sql_summary["total"]
            assert mem_summary["provenance"] == sql_summary["provenance"]
            assert mem_summary["freshness"] == sql_summary["freshness"]
            assert mem_summary["sources"] == sql_summary["sources"]

            # Exported JSON must parse to the same structure (ignoring id/timestamp drift)
            mem_export = json.loads(memory_trail.export())
            sql_export = json.loads(sqlite_trail.export())
            assert len(mem_export) == len(sql_export)

            for mem_rec, sql_rec in zip(mem_export, sql_export, strict=True):
                # Content hashes are deterministic on the same input
                assert mem_rec["content_hash"] == sql_rec["content_hash"]
                assert mem_rec["source"] == sql_rec["source"]
                assert mem_rec["source_name"] == sql_rec["source_name"]
                assert mem_rec["provenance_status"] == sql_rec["provenance_status"]
                assert mem_rec["freshness_status"] == sql_rec["freshness_status"]
                # Chain hashes may differ due to per-call timestamp differences,
                # but both chains must be independently intact (verified above).
                # Verify structural properties instead: non-empty and hex format.
                assert len(mem_rec["chain_hash"]) == 64
                assert len(sql_rec["chain_hash"]) == 64

            # Queries by source must return the same counts
            for src in (
                ContextSource.RETRIEVER,
                ContextSource.TOOL,
                ContextSource.AGENT,
            ):
                mem_q = memory_trail.query(source=src)
                sql_q = sqlite_trail.query(source=src)
                assert len(mem_q) == len(sql_q), (
                    f"Source {src.value}: memory={len(mem_q)}, sqlite={len(sql_q)}"
                )

            memory_trail.close()
            sqlite_trail.close()
        finally:
            os.unlink(db_path)

    # ---- 10. CLI verify command reports PASS ----

    def test_cli_verify_pass(self):
        """The CLI `provena verify` command must report PASS on a valid trail."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            trail = ContextTrail(storage_path=db_path)
            _populate_trail(trail)
            trail.close()

            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "verify"])
            assert result.exit_code == 0
            assert "PASS" in result.output
            assert "5 records" in result.output
        finally:
            os.unlink(db_path)

    def test_cli_report_matches_api_summary(self):
        """The CLI report must agree with the programmatic summary."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            trail = ContextTrail(storage_path=db_path)
            _populate_trail(trail)
            api_summary = trail.summary()
            trail.close()

            runner = CliRunner()
            result = runner.invoke(cli, ["--db", db_path, "report", "--format", "json"])
            assert result.exit_code == 0

            report = json.loads(result.output)
            assert report["total_records"] == api_summary["total"]
            assert report["chain_integrity"]["status"] == "INTACT"
            assert report["provenance"] == api_summary["provenance"]
            assert report["freshness"] == api_summary["freshness"]
            assert report["sources"] == api_summary["sources"]
        finally:
            os.unlink(db_path)


class TestTrackDecoratorIntegration:
    """Test the @track decorator in a realistic agent-function scenario."""

    def test_tracked_retriever_function(self):
        with ContextTrail(backend="memory") as trail:

            @trail.track(
                source=ContextSource.RETRIEVER,
                source_name="vector-search",
                content_extractor=lambda results: [doc["text"] for doc in results],
            )
            def retrieve_documents(query: str) -> list[dict]:
                return [
                    {"text": RAG_DOC_FRESH, "score": 0.94},
                    {"text": RAG_DOC_STALE, "score": 0.87},
                    {"text": RAG_DOC_NO_PROVENANCE, "score": 0.81},
                ]

            docs = retrieve_documents("kubernetes container runtime")
            assert len(docs) == 3

            summary = trail.summary()
            assert summary["total"] == 3
            assert summary["sources"]["retriever"] == 3

            verdict = trail.verify_chain()
            assert verdict.intact is True

    def test_tracked_tool_function(self):
        with ContextTrail(backend="memory") as trail:

            @trail.track(source=ContextSource.TOOL, source_name="pricing-api")
            def get_pricing(service: str, region: str) -> dict:
                return {
                    "service": service,
                    "region": region,
                    "on_demand_hourly_usd": 0.1632,
                    "currency": "USD",
                }

            pricing = get_pricing("eks", "us-east-1")
            assert pricing["on_demand_hourly_usd"] == 0.1632

            summary = trail.summary()
            assert summary["total"] == 1
            assert summary["sources"]["tool"] == 1

    def test_full_tracked_pipeline(self):
        """Simulate a full pipeline where retriever, tool, and agent are all tracked."""
        with ContextTrail(backend="memory") as trail:

            @trail.track(
                source=ContextSource.RETRIEVER,
                source_name="kb-search",
                content_extractor=lambda r: r,
            )
            def search_kb(query: str) -> list[str]:
                return [RAG_DOC_FRESH, RAG_DOC_STALE]

            @trail.track(source=ContextSource.TOOL, source_name="pricing")
            def call_pricing_api() -> str:
                return TOOL_PRICING_RESPONSE

            @trail.track(source=ContextSource.AGENT, source_name="summarizer")
            def summarize(context: str) -> str:
                return AGENT_MESSAGE

            search_kb("k8s")
            call_pricing_api()
            summarize("all context")

            summary = trail.summary()
            assert summary["total"] == 4  # 2 retriever + 1 tool + 1 agent
            assert summary["sources"]["retriever"] == 2
            assert summary["sources"]["tool"] == 1
            assert summary["sources"]["agent"] == 1

            assert trail.verify_chain().intact is True


class TestEdgeCases:
    """Edge cases that matter in production agent deployments."""

    def test_large_content_truncation(self):
        """Content exceeding max_content_bytes is truncated but still governed."""
        with ContextTrail(backend="memory", max_content_bytes=256) as trail:
            large_content = "x" * 1000
            record = trail.log(large_content, source=ContextSource.RETRIEVER)
            assert record is not None
            assert record.entry.truncated is True
            assert trail.verify_chain().intact is True

    def test_binary_content_governance(self):
        """Binary content (e.g. embeddings or serialized data) is governed."""
        with ContextTrail(backend="memory") as trail:
            binary_data = bytes(range(256))
            record = trail.log(
                binary_data,
                source=ContextSource.TOOL,
                source_name="embedding-service",
            )
            assert record is not None
            assert record.entry.content_type == "bytes"
            assert trail.verify_chain().intact is True

    def test_string_source_parsing(self):
        """Source strings like 'tool:api' are parsed into ContextSource.TOOL."""
        with ContextTrail(backend="memory") as trail:
            record = trail.log("data", source="tool:pricing-api")
            assert record is not None
            assert record.entry.source == ContextSource.TOOL
            assert record.entry.source_name == "pricing-api"

    def test_annotations_on_governed_records(self):
        """Human reviewers can annotate governed records."""
        with ContextTrail(backend="memory") as trail:
            trail.log(
                RAG_DOC_STALE,
                source=ContextSource.RETRIEVER,
                source_name="k8s-docs",
                provenance=_stale_provenance(),
            )

            ann_id = trail.annotate(
                record_id=1,
                note="Confirmed stale -- container runtime docs need refresh for v1.30",
                reviewer="platform-eng@company.com",
            )
            assert ann_id >= 1
            # Annotation must not break the chain
            assert trail.verify_chain().intact is True

    def test_health_check(self):
        """Health endpoint reports correct state after a full pipeline run."""
        with ContextTrail(backend="memory") as trail:
            _populate_trail(trail)
            health = trail.health()

            assert health["status"] == "healthy"
            assert health["record_count"] == 5
            assert health["backend"] == "InMemoryBackend"
            assert health["signed"] is False
            assert health["errors"] == 0

    def test_context_manager_cleanup(self):
        """Using ContextTrail as a context manager properly closes resources."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            with ContextTrail(storage_path=db_path) as trail:
                _populate_trail(trail)
                assert trail.verify_chain().intact is True

            # After exiting the context manager, the db file should still
            # exist and be readable by a new trail instance
            trail2 = ContextTrail(storage_path=db_path)
            assert trail2.verify_chain().intact is True
            assert trail2.summary()["total"] == 5
            trail2.close()
        finally:
            os.unlink(db_path)
