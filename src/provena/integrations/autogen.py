"""AutoGen integration for logging agent messages to a Provena trail."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from provena.models import ContextSource

if TYPE_CHECKING:
    from provena.trail import ContextTrail


class ProvenaAutoGenHook:
    """AutoGen hook that logs agent messages to a Provena trail.

    Register via ``agent.register_hook("process_message_before_send", ...)``.

    Usage::

        from provena import ContextTrail
        from provena.integrations.autogen import ProvenaAutoGenHook

        trail = ContextTrail()
        hook = ProvenaAutoGenHook(trail=trail)
        agent.register_hook(
            "process_message_before_send", hook.process_message
        )
    """

    def __init__(self, trail: ContextTrail) -> None:
        self._trail = trail

    def process_message(
        self, sender: Any, message: Any, recipient: Any, silent: bool
    ) -> Any:
        """Log the message content and return it unchanged."""
        if isinstance(message, dict):
            content = message.get("content", str(message))
        else:
            content = str(message)

        sender_name = getattr(sender, "name", "unknown")
        recipient_name = getattr(recipient, "name", "unknown")

        self._trail.log(
            content=content,
            source=ContextSource.AGENT,
            source_name=f"autogen:{sender_name}",
            metadata={"recipient": recipient_name},
        )
        return message
