from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from provena.models import ContextSource, ProvenanceMetadata, parse_isoformat

if TYPE_CHECKING:
    from provena.trail import ContextTrail

try:
    from langchain_core.callbacks.base import BaseCallbackHandler

    class ProvenaCallback(BaseCallbackHandler):
        """LangChain callback that logs retriever results and tool outputs to a Provena trail.

        Usage::

            from provena import ContextTrail
            from provena.integrations.langchain import ProvenaCallback

            trail = ContextTrail()
            chain = RetrievalQA.from_chain_type(
                llm=llm,
                retriever=retriever,
                callbacks=[ProvenaCallback(trail=trail)],
            )
        """

        def __init__(self, trail: ContextTrail, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._trail = trail

        def on_retriever_end(
            self,
            documents: Any,
            *,
            run_id: UUID,
            parent_run_id: UUID | None = None,
            **kwargs: Any,
        ) -> None:
            for doc in documents or ():
                content = getattr(doc, "page_content", None)
                if content is None:
                    content = str(doc)
                provenance = _extract_langchain_provenance(doc)
                self._trail.log(
                    content=content,
                    source=ContextSource.RETRIEVER,
                    source_name="langchain",
                    provenance=provenance,
                    metadata={"run_id": str(run_id)},
                )

        def on_tool_end(
            self,
            output: Any,
            *,
            run_id: UUID,
            parent_run_id: UUID | None = None,
            **kwargs: Any,
        ) -> None:
            content = str(output)
            self._trail.log(
                content=content,
                source=ContextSource.TOOL,
                source_name="langchain",
                metadata={"run_id": str(run_id)},
            )

except ImportError:

    class ProvenaCallback:  # type: ignore[no-redef]
        """Placeholder when langchain-core is not installed."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "langchain-core is required for LangChain integration. "
                "Install with: pip install provena[langchain]"
            )


def _first_str(meta: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Return the first string metadata value among ``keys``.

    Non-strings are skipped without calling ``__bool__``, so an ambiguous
    truthiness object cannot raise or hide a later usable string.
    """
    for key in keys:
        value = meta.get(key)
        if isinstance(value, str):
            return value
    return None


def _first_datetime(meta: dict[str, Any], keys: tuple[str, ...]) -> datetime | None:
    """Return the first metadata value among ``keys`` that parses as a datetime."""
    for key in keys:
        if key not in meta:
            continue
        parsed = _parse_datetime(meta[key])
        if parsed is not None:
            return parsed
    return None


def _extract_langchain_provenance(doc: Any) -> ProvenanceMetadata | None:
    meta = getattr(doc, "metadata", None)
    if not isinstance(meta, dict):
        return None
    return ProvenanceMetadata(
        source_url=_first_str(meta, ("source", "source_url")),
        author=meta.get("author") if isinstance(meta.get("author"), str) else None,
        created_at=_first_datetime(meta, ("created_at", "date", "last_modified")),
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
