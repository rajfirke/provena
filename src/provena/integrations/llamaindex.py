from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from provena.models import ContextSource, ProvenanceMetadata, parse_isoformat

if TYPE_CHECKING:
    from provena.trail import ContextTrail

try:
    from llama_index.core.postprocessor.types import BaseNodePostprocessor
    from llama_index.core.schema import NodeWithScore, QueryBundle
    from pydantic import ConfigDict

    class ProvenaPostprocessor(BaseNodePostprocessor):
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
            if not isinstance(nodes, list):
                nodes = list(nodes)
            for node_with_score in nodes:
                node = node_with_score.node
                content = getattr(node, "text", None)
                if content is None:
                    content = str(node)
                provenance = _extract_llamaindex_provenance(node)
                metadata: dict[str, Any] = {}
                if getattr(node_with_score, "score", None) is not None:
                    metadata["score"] = node_with_score.score
                if query_bundle:
                    query_str = getattr(query_bundle, "query_str", None)
                    if query_str is not None:
                        metadata["query"] = query_str
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

    created_at_val = None
    for key in ("created_at", "date", "last_modified_date", "creation_date"):
        if meta.get(key) is not None:
            created_at_val = meta.get(key)
            break

    source_val = None
    for key in ("source", "file_path"):
        if meta.get(key) is not None:
            source_val = meta.get(key)
            break

    return ProvenanceMetadata(
        source_url=source_val,
        author=meta.get("author"),
        created_at=_parse_datetime(created_at_val),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return parse_isoformat(value)
        except ValueError:
            return None
    return None
