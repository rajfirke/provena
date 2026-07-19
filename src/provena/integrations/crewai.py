"""CrewAI integration for logging agent and task outputs to a Provena trail."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from provena.models import ContextSource

if TYPE_CHECKING:
    from provena.trail import ContextTrail

try:
    from crewai.utilities.events.agent_events import AgentExecutionCompletedEvent
    from crewai.utilities.events.base_event_listener import BaseEventListener
    from crewai.utilities.events.tool_usage_events import ToolUsageFinishedEvent

    class ProvenaCrewListener(BaseEventListener):
        """CrewAI event listener that logs tool and agent outputs to a Provena trail.

        Usage::

            from provena import ContextTrail
            from provena.integrations.crewai import ProvenaCrewListener

            trail = ContextTrail()
            listener = ProvenaCrewListener(trail=trail)
            crew = Crew(agents=[...], tasks=[...])
            crew.kickoff()
        """

        def __init__(self, trail: ContextTrail, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._trail = trail

        def on_tool_usage_finished(self, event: ToolUsageFinishedEvent) -> None:
            output = getattr(event, "output", None)
            if output is None:
                return
            tool_name = getattr(event, "tool_name", "unknown")
            self._trail.log(
                content=str(output),
                source=ContextSource.TOOL,
                source_name=f"crewai:{tool_name}",
            )

        def on_agent_execution_completed(
            self, event: AgentExecutionCompletedEvent
        ) -> None:
            output = getattr(event, "output", None)
            if output is None:
                return
            agent_name = getattr(event, "agent_name", "unknown")
            self._trail.log(
                content=str(output),
                source=ContextSource.AGENT,
                source_name=f"crewai:{agent_name}",
            )

except ImportError:

    class ProvenaCrewListener:  # type: ignore[no-redef]
        """Placeholder when crewai is not installed."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "crewai is required for CrewAI integration. "
                "Install with: pip install provena[crewai]"
            )
