# CrewAI

`ProvenaCrewListener` records CrewAI tool results and completed agent
executions on a Provena trail.

## Installation

```bash
pip install provena[crewai]
```

This installs `crewai>=1.0.0`.

## Quick start

```python
from provena import ContextTrail
from provena.integrations.crewai import ProvenaCrewListener

trail = ContextTrail()
listener = ProvenaCrewListener(trail=trail)
crew = Crew(agents=[...], tasks=[...])
crew.kickoff()
```

Construct the listener before `kickoff()`. CrewAI registers listeners that
exist when the crew runs.

## Events tracked

| Event | Trail source | `source_name` |
|---|---|---|
| `ToolUsageFinishedEvent` | `tool` | `crewai:<tool_name>` |
| `AgentExecutionCompletedEvent` | `agent` | `crewai:<agent role>` |

Empty outputs are ignored. Tool and agent text is stored with `str(output)`.

## Provenance

This adapter does not read document metadata, so logged rows have no
provenance unless you add it yourself. With the default required fields
those rows are `MISSING`.
