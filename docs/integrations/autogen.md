# AutoGen

`ProvenaAutoGenHook` logs agent messages before they are sent.

## Installation

```bash
pip install provena[autogen]
```

This installs `autogen-agentchat>=0.4`.

## Quick start

```python
from provena import ContextTrail
from provena.integrations.autogen import ProvenaAutoGenHook

trail = ContextTrail()
hook = ProvenaAutoGenHook(trail=trail)
agent.register_hook("process_message_before_send", hook.process_message)
```

`process_message` returns the original message unchanged.

## Events tracked

Each hooked send becomes one trail row:

- **Source:** `agent`
- **source_name:** `autogen:<sender name>`
- **Content:** `message["content"]` when the message is a dict, otherwise `str(message)`
- **Metadata:** `recipient` set to the recipient agent's name

## Provenance

The hook does not extract provenance. Rows are `MISSING` under the default
required fields unless the surrounding application passes provenance through
another `log()` call.
