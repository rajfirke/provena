"""OpenAI Agents SDK integration for logging tool and agent outputs."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from provena.models import ContextSource

if TYPE_CHECKING:
    from provena.trail import ContextTrail

try:
    from agents import RunHooks
    from agents.lifecycle import RunHooksContext

    class ProvenaRunHooks(RunHooks[Any]):
        """OpenAI Agents SDK hooks that log tool and handoff events.

        Usage::

            from provena import ContextTrail
            from provena.integrations.openai_agents import ProvenaRunHooks

            trail = ContextTrail()
            result = Runner.run(agent, input="...", hooks=ProvenaRunHooks(trail))
        """

        def __init__(self, trail: ContextTrail) -> None:
            self._trail = trail

        async def on_tool_end(
            self,
            context: RunHooksContext[Any],
            agent: Any,
            tool: Any,
            result: str,
        ) -> None:
            tool_name = getattr(tool, "name", "unknown")
            agent_name = getattr(agent, "name", "unknown")
            await asyncio.to_thread(
                self._trail.log,
                content=result,
                source=ContextSource.TOOL,
                source_name=f"openai:{tool_name}",
                metadata={"agent": agent_name},
            )

        async def on_handoff(
            self,
            context: RunHooksContext[Any],
            from_agent: Any,
            to_agent: Any,
        ) -> None:
            from_name = getattr(from_agent, "name", "unknown")
            to_name = getattr(to_agent, "name", "unknown")
            await asyncio.to_thread(
                self._trail.log,
                content=f"Handoff from {from_name} to {to_name}",
                source=ContextSource.AGENT,
                source_name=f"openai:{from_name}",
                metadata={"to_agent": to_name},
            )

except ImportError:

    class ProvenaRunHooks:  # type: ignore[no-redef]
        """Placeholder when openai-agents is not installed."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "openai-agents is required for OpenAI Agents SDK integration. "
                "Install with: pip install provena[openai-agents]"
            )
