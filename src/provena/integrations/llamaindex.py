from __future__ import annotations

from typing import TYPE_CHECKING, Any

from provena.models import ContextSource, ProvenanceMetadata

if TYPE_CHECKING:
    from provena.trail import ContextTrail

try:
    from llama_index.core.postprocessor.types import BaseNodePostprocessor
    from llama_index.core.schema import NodeWithScore, QueryBundle
    from pydantic import ConfigDict

    class ProvenaPostprocessor(BaseNodePostprocessor):  # type: ignore[misc]
        """LlamaIndex postprocessor that logs retrieved nodes to a Provena trail.

        Usage::

            from provena import ContextTrail
            from provena.integrations.llamaindex import ProvenaPostprocessor

            trail = ContextTrail()
            query_engine = index.as_query_engine(
                node_postprocessors=[ProvenaPostprocessor(trail=trail)]
            )
        """

        model_config = ConfigDict(arbitrary_types_allowed=True)
        trail: Any

        def __init__(self, trail: ContextTrail, **kwargs: Any) -> None:
            super().__init__(trail=trail, **kwargs)

        def _postprocess_nodes(
            self,
            nodes: list[NodeWithScore],
            query_bundle: QueryBundle | None = None,
        ) -> list[NodeWithScore]:
            for node_with_score in nodes:
                node = node_with_score.node
                content = getattr(node, "text", None)
                if content is None:
                    content = str(node)
                provenance = _extract_llamaindex_provenance(node)
                metadata: dict[str, Any] = {}
                if node_with_score.score is not None:
                    metadata["score"] = node_with_score.score
                if query_bundle:
                    metadata["query"] = query_bundle.query_str
                self.trail.log(
                    content=content,
                    source=ContextSource.RETRIEVER,
                    source_name="llamaindex",
                    provenance=provenance,
                    metadata=metadata,
                )
            return nodes

except ImportError:

    class ProvenaPostprocessor:  # type: ignore[no-redef]
        """Placeholder when llama-index-core is not installed."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "llama-index-core is required for LlamaIndex integration. "
                "Install with: pip install provena[llamaindex]"
            )


def _extract_llamaindex_provenance(node: Any) -> ProvenanceMetadata | None:
    meta = getattr(node, "metadata", None)
    if not isinstance(meta, dict):
        return None
    return ProvenanceMetadata(
        source_url=meta.get("source") or meta.get("file_path"),
        author=meta.get("author"),
    )
