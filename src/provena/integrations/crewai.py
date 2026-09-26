"""CrewAI integration for logging agent and task outputs to a Provena trail."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from provena.models import ContextSource

if TYPE_CHECKING:
    from provena.trail import ContextTrail

try:
    from crewai.events import (
        AgentExecutionCompletedEvent,
        BaseEventListener,
        ToolUsageFinishedEvent,
    )

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
            self._trail = trail
            super().__init__(**kwargs)

        def setup_listeners(self, crewai_event_bus: Any) -> None:
            @crewai_event_bus.on(ToolUsageFinishedEvent)
            def _on_tool_usage_finished(
                source: Any, event: ToolUsageFinishedEvent
            ) -> None:
                self._log_tool_usage_finished(event)

            @crewai_event_bus.on(AgentExecutionCompletedEvent)
            def _on_agent_execution_completed(
                source: Any, event: AgentExecutionCompletedEvent
            ) -> None:
                self._log_agent_execution_completed(event)

        def _log_tool_usage_finished(self, event: ToolUsageFinishedEvent) -> None:
            output = getattr(event, "output", None)
            if output is None:
                return
            tool_name = getattr(event, "tool_name", "unknown")
            self._trail.log(
                content=str(output),
                source=ContextSource.TOOL,
                source_name=f"crewai:{tool_name}",
            )

        def _log_agent_execution_completed(
            self, event: AgentExecutionCompletedEvent
        ) -> None:
            output = getattr(event, "output", None)
            if output is None:
                return
            agent = getattr(event, "agent", None)
            agent_role = getattr(agent, "role", None) or "unknown"
            self._trail.log(
                content=str(output),
                source=ContextSource.AGENT,
                source_name=f"crewai:{agent_role}",
            )

except ImportError:

    class ProvenaCrewListener:  # type: ignore[no-redef]
        """Placeholder when crewai is not installed."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "crewai is required for CrewAI integration. "
                "Install with: pip install provena[crewai]"
            )
