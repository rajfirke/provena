"""Google ADK integration for logging tool outputs to a Provena trail."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from provena.models import ContextSource

if TYPE_CHECKING:
    from provena.trail import ContextTrail


class ProvenaADKCallback:
    """Google ADK callback that logs tool outputs to a Provena trail.

    Use as ``after_tool_callback`` on an ADK Agent.

    Usage::

        from provena import ContextTrail
        from provena.integrations.google_adk import ProvenaADKCallback

        trail = ContextTrail()
        callback = ProvenaADKCallback(trail=trail)

        agent = Agent(
            name="my-agent",
            after_tool_callback=callback.after_tool_call,
        )
    """

    def __init__(self, trail: ContextTrail) -> None:
        self._trail = trail

    def after_tool_call(
        self,
        tool: Any,
        args: dict[str, Any],
        tool_context: Any,
        tool_response: Any,
    ) -> Any | None:
        """Log the tool response and return None (pass-through)."""
        tool_name = getattr(tool, "name", None) or getattr(tool, "__name__", "unknown")
        content = str(tool_response) if tool_response is not None else ""
        if content:
            self._trail.log(
                content=content,
                source=ContextSource.TOOL,
                source_name=f"adk:{tool_name}",
                metadata={"args": args} if args else {},
            )
        return None
