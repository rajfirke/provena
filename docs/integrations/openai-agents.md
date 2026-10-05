# OpenAI Agents SDK

`ProvenaRunHooks` logs tool results and agent handoffs from the OpenAI
Agents SDK.

## Installation

```bash
pip install provena[openai-agents]
```

This installs `openai-agents>=0.1`.

## Quick start

```python
from provena import ContextTrail
from provena.integrations.openai_agents import ProvenaRunHooks

trail = ContextTrail()
result = Runner.run(agent, input="...", hooks=ProvenaRunHooks(trail))
```

## Events tracked

| Hook | Trail source | Content |
|---|---|---|
| `on_tool_end` | `tool` | The tool result string. `source_name` is `openai:<tool name>`. Metadata includes `agent`. |
| `on_handoff` | `agent` | `Handoff from <from> to <to>`. `source_name` is `openai:<from agent>`. Metadata includes `to_agent`. |

Both hooks call `trail.log()` from a worker thread via `asyncio.to_thread`.

## Provenance

Tool output and handoff text are logged without provenance metadata. Default
validation marks those rows `MISSING`.
