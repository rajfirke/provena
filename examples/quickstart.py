"""Provena quickstart — govern your AI agent's context in 15 lines."""

from provena import ContextTrail

trail = ContextTrail(backend="memory")


@trail.track(source="retriever")
def search(query: str) -> list[str]:
    return [
        "OpenShift 4.16 supports single-node deployments for edge.",
        "Minimum requirements: 8 vCPUs, 32 GB RAM, 120 GB storage.",
    ]


results = search("openshift edge deployment")
print(f"Search returned {len(results)} results")

verdict = trail.verify_chain()
print(f"Chain intact: {verdict.intact} ({verdict.total_records} records)")
print(f"Summary: {trail.summary()}")
