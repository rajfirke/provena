# Google ADK

`ProvenaADKCallback` logs tool responses from a Google Agent Development Kit
agent.

## Installation

```bash
pip install provena[google-adk]
```

This installs `google-adk>=1.0`.

## Quick start

```python
from provena import ContextTrail
from provena.integrations.google_adk import ProvenaADKCallback

trail = ContextTrail()
callback = ProvenaADKCallback(trail=trail)

agent = Agent(
    name="my-agent",
    after_tool_callback=callback.after_tool_call,
)
```

`after_tool_call` returns `None`, so the tool response is passed through
unchanged.

## Events tracked

A non-empty tool response is logged as:

- **Source:** `tool`
- **source_name:** `adk:<tool name>`
- **Content:** `str(tool_response)`
- **Metadata:** the tool `args` dict, when it is non-empty

Empty responses are not logged.

## Provenance

The callback does not extract provenance from the tool response. Rows are
`MISSING` under the default required fields.
