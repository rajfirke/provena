"""Multi-source RAG pipeline with provenance and freshness checking."""

import json
from datetime import datetime, timedelta, timezone

from provena import ContextSource, ContextTrail, ProvenanceMetadata

trail = ContextTrail(backend="memory", max_age_days=90)


# --- RAG retriever with fresh provenance ---
trail.log(
    "Kubernetes 1.30 introduces structured authorization configuration.",
    source=ContextSource.RETRIEVER,
    source_name="k8s_docs",
    provenance=ProvenanceMetadata(
        source_url="https://kubernetes.io/blog/2026/kubernetes-v1-30/",
        author="Kubernetes Release Team",
        created_at=datetime.now(timezone.utc) - timedelta(days=3),
    ),
)

# --- RAG retriever with stale content (detected via regex) ---
trail.log(
    "As of 2023, the recommended runtime is containerd 1.6.x.",
    source=ContextSource.RETRIEVER,
    source_name="old_docs",
)

# --- Tool call with API response ---
trail.log(
    json.dumps({"service": "eks", "price_hourly_usd": 0.10, "region": "us-east-1"}),
    source="tool:pricing_api",
    provenance=ProvenanceMetadata(
        source_url="https://pricing.aws.amazon.com/eks",
        created_at=datetime.now(timezone.utc),
    ),
)

# --- Agent-to-agent message ---
trail.log(
    "Based on pricing data, recommend spot instances for 60% cost savings.",
    source=ContextSource.AGENT,
    source_name="cost_advisor",
)

# --- Print governance summary ---
summary = trail.summary()
print("Provena Governance Summary")
print("=" * 40)
print(f"Total records:  {summary['total']}")
print(f"Provenance:     {summary['provenance']}")
print(f"Freshness:      {summary['freshness']}")
print(f"Sources:        {summary['sources']}")
print(f"Chain intact:   {trail.verify_chain().intact}")
