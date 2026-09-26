"""Tests for framework adapters (CrewAI, AutoGen, OpenAI Agents SDK, Google ADK).

All tests use mock objects so they run without the framework installed.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

from provena.models import ContextSource
from provena.trail import ContextTrail


class MockSender:
    def __init__(self, name: str = "agent1"):
        self.name = name


class MockRecipient:
    def __init__(self, name: str = "agent2"):
        self.name = name


class TestAutoGenHook:
    def test_process_message_string(self, memory_trail):
        from provena.integrations.autogen import ProvenaAutoGenHook

        hook = ProvenaAutoGenHook(trail=memory_trail)
        sender = MockSender("planner")
        recipient = MockRecipient("executor")
        msg = hook.process_message(sender, "do the task", recipient, False)
        assert msg == "do the task"
        assert memory_trail.summary()["total"] == 1
        records = memory_trail.query()
        assert records[0]["source"] == "agent"
        assert records[0]["source_name"] == "autogen:planner"

    def test_process_message_dict(self, memory_trail):
        from provena.integrations.autogen import ProvenaAutoGenHook

        hook = ProvenaAutoGenHook(trail=memory_trail)
        message = {"content": "hello", "role": "assistant"}
        result = hook.process_message(MockSender(), message, MockRecipient(), False)
        assert result is message
        records = memory_trail.query()
        assert len(records) == 1

    def test_process_message_preserves_chain(self, memory_trail):
        from provena.integrations.autogen import ProvenaAutoGenHook

        hook = ProvenaAutoGenHook(trail=memory_trail)
        for i in range(5):
            hook.process_message(
                MockSender(f"agent{i}"), f"msg {i}", MockRecipient(), False
            )
        verdict = memory_trail.verify_chain()
        assert verdict.intact
        assert verdict.total_records == 5


class TestADKCallback:
    def test_after_tool_call(self, memory_trail):
        from provena.integrations.google_adk import ProvenaADKCallback

        callback = ProvenaADKCallback(trail=memory_trail)

        class MockTool:
            name = "web_search"

        result = callback.after_tool_call(
            tool=MockTool(),
            args={"query": "test"},
            tool_context=None,
            tool_response="search results here",
        )
        assert result is None
        assert memory_trail.summary()["total"] == 1
        records = memory_trail.query()
        assert records[0]["source"] == "tool"
        assert records[0]["source_name"] == "adk:web_search"

    def test_after_tool_call_none_response(self, memory_trail):
        from provena.integrations.google_adk import ProvenaADKCallback

        callback = ProvenaADKCallback(trail=memory_trail)

        class MockTool:
            name = "empty_tool"

        result = callback.after_tool_call(
            tool=MockTool(), args={}, tool_context=None, tool_response=None
        )
        assert result is None
        assert memory_trail.summary()["total"] == 0

    def test_after_tool_call_function_tool(self, memory_trail):
        from provena.integrations.google_adk import ProvenaADKCallback

        callback = ProvenaADKCallback(trail=memory_trail)

        def my_function():
            pass

        callback.after_tool_call(
            tool=my_function, args={}, tool_context=None, tool_response="output"
        )
        records = memory_trail.query()
        assert records[0]["source_name"] == "adk:my_function"

    def test_chain_integrity(self, memory_trail):
        from provena.integrations.google_adk import ProvenaADKCallback

        callback = ProvenaADKCallback(trail=memory_trail)

        class MockTool:
            name = "tool"

        for i in range(10):
            callback.after_tool_call(
                tool=MockTool(),
                args={"i": i},
                tool_context=None,
                tool_response=f"result {i}",
            )
        verdict = memory_trail.verify_chain()
        assert verdict.intact
        assert verdict.total_records == 10


_has_crewai = False
try:
    import crewai  # noqa: F401

    _has_crewai = True
except ImportError:
    pass


class TestCrewAIImportError:
    @pytest.mark.skipif(_has_crewai, reason="crewai IS installed")
    def test_raises_import_error(self):
        from provena.integrations.crewai import ProvenaCrewListener

        with pytest.raises(ImportError, match="crewai"):
            ProvenaCrewListener(trail=ContextTrail(backend="memory"))


class _FakeEventBus:
    """Stands in for crewai_event_bus: records handlers by event type and
    lets a test fire one exactly the way CrewAI's real bus would."""

    def __init__(self) -> None:
        self.handlers: dict[type, object] = {}

    def on(self, event_type):
        def decorator(handler):
            self.handlers[event_type] = handler
            return handler

        return decorator

    def emit(self, source, event) -> None:
        handler = self.handlers.get(type(event))
        if handler is None:
            raise AssertionError(f"no handler registered for {type(event)}")
        handler(source, event)


@pytest.fixture
def crew_listener_class(monkeypatch):
    module_name = "provena.integrations.crewai"
    previous_module = sys.modules.pop(module_name, None)

    crewai_mod = ModuleType("crewai")
    events_mod = ModuleType("crewai.events")

    class ToolUsageFinishedEvent:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class AgentExecutionCompletedEvent:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    fake_bus = _FakeEventBus()

    class BaseEventListener:
        def __init__(self, **kwargs):
            self.setup_listeners(fake_bus)

    events_mod.BaseEventListener = BaseEventListener
    events_mod.ToolUsageFinishedEvent = ToolUsageFinishedEvent
    events_mod.AgentExecutionCompletedEvent = AgentExecutionCompletedEvent

    monkeypatch.setitem(sys.modules, "crewai", crewai_mod)
    monkeypatch.setitem(sys.modules, "crewai.events", events_mod)

    from provena.integrations.crewai import ProvenaCrewListener

    yield SimpleNamespace(
        listener_class=ProvenaCrewListener,
        bus=fake_bus,
        ToolUsageFinishedEvent=ToolUsageFinishedEvent,
        AgentExecutionCompletedEvent=AgentExecutionCompletedEvent,
    )

    # Cleanup
    sys.modules.pop(module_name, None)
    if previous_module is not None:
        sys.modules[module_name] = previous_module


class TestCrewAIListener:
    def test_on_tool_usage_finished(self, crew_listener_class, memory_trail):
        import hashlib

        ctx = crew_listener_class
        ctx.listener_class(trail=memory_trail)
        event = ctx.ToolUsageFinishedEvent(tool_name="web_search", output="found data")
        ctx.bus.emit(source=None, event=event)

        records = memory_trail.query()
        assert len(records) == 1
        assert records[0]["source"] == ContextSource.TOOL.value
        assert records[0]["source_name"] == "crewai:web_search"
        expected_hash = hashlib.sha256(b"found data").hexdigest()
        assert records[0]["content_hash"] == expected_hash

    def test_on_agent_execution_completed(self, crew_listener_class, memory_trail):
        import hashlib

        ctx = crew_listener_class
        ctx.listener_class(trail=memory_trail)
        agent = SimpleNamespace(role="researcher")
        event = ctx.AgentExecutionCompletedEvent(agent=agent, output="task complete")
        ctx.bus.emit(source=None, event=event)

        records = memory_trail.query()
        assert len(records) == 1
        assert records[0]["source"] == ContextSource.AGENT.value
        assert records[0]["source_name"] == "crewai:researcher"
        expected_hash = hashlib.sha256(b"task complete").hexdigest()
        assert records[0]["content_hash"] == expected_hash

    def test_ignores_empty_output(self, crew_listener_class, memory_trail):
        ctx = crew_listener_class
        ctx.listener_class(trail=memory_trail)

        # Output is None -> Should not log anything
        tool_event = ctx.ToolUsageFinishedEvent(tool_name="web_search", output=None)
        agent = SimpleNamespace(role="researcher")
        agent_event = ctx.AgentExecutionCompletedEvent(agent=agent, output=None)

        ctx.bus.emit(source=None, event=tool_event)
        ctx.bus.emit(source=None, event=agent_event)

        assert len(memory_trail.query()) == 0

    def test_missing_name_fallback(self, crew_listener_class, memory_trail):
        ctx = crew_listener_class
        ctx.listener_class(trail=memory_trail)

        # Tool event has no tool_name; agent has no role (and no agent at all).
        tool_event = ctx.ToolUsageFinishedEvent(output="tool data")
        agent_event = ctx.AgentExecutionCompletedEvent(agent=None, output="agent data")

        ctx.bus.emit(source=None, event=tool_event)
        ctx.bus.emit(source=None, event=agent_event)

        records = memory_trail.query()
        assert len(records) == 2
        assert records[0]["source_name"] == "crewai:unknown"
        assert records[1]["source_name"] == "crewai:unknown"

    def test_non_string_output_conversion(self, crew_listener_class, memory_trail):
        import hashlib

        ctx = crew_listener_class
        ctx.listener_class(trail=memory_trail)

        # Pass a dict instead of a string
        complex_output = {"status": "success", "count": 42}
        event = ctx.ToolUsageFinishedEvent(tool_name="api", output=complex_output)
        ctx.bus.emit(source=None, event=event)

        records = memory_trail.query()
        assert len(records) == 1

        # Verify it was safely coerced to a string before hashing
        expected_content = str(complex_output)
        expected_hash = hashlib.sha256(expected_content.encode("utf-8")).hexdigest()
        assert records[0]["content_hash"] == expected_hash

    def test_multi_step_chain_integrity(self, crew_listener_class, memory_trail):
        ctx = crew_listener_class
        ctx.listener_class(trail=memory_trail)

        # Simulate a full agent task cycle
        tool1 = ctx.ToolUsageFinishedEvent(tool_name="search", output="result A")
        tool2 = ctx.ToolUsageFinishedEvent(tool_name="calculator", output="result B")
        agent = SimpleNamespace(role="analyst")
        agent_event = ctx.AgentExecutionCompletedEvent(
            agent=agent, output="final report"
        )

        ctx.bus.emit(source=None, event=tool1)
        ctx.bus.emit(source=None, event=tool2)
        ctx.bus.emit(source=None, event=agent_event)

        verdict = memory_trail.verify_chain()
        assert verdict.intact is True
        assert verdict.total_records == 3


_has_openai_agents = False
try:
    import agents  # noqa: F401

    _has_openai_agents = True
except ImportError:
    pass


@pytest.fixture
def openai_run_hooks(monkeypatch):
    module_name = "provena.integrations.openai_agents"
    previous_module = sys.modules.pop(module_name, None)

    agents_module = ModuleType("agents")
    lifecycle_module = ModuleType("agents.lifecycle")

    class MockRunHooks:
        def __class_getitem__(cls, item):
            return cls

    agents_module.RunHooks = MockRunHooks
    lifecycle_module.RunHooksContext = object
    monkeypatch.setitem(sys.modules, "agents", agents_module)
    monkeypatch.setitem(sys.modules, "agents.lifecycle", lifecycle_module)

    from provena.integrations.openai_agents import ProvenaRunHooks

    yield ProvenaRunHooks

    sys.modules.pop(module_name, None)
    if previous_module is not None:
        sys.modules[module_name] = previous_module


class BlockingTrail:
    def __init__(self):
        self.release = threading.Event()
        self.calls = []

    def log(self, **kwargs):
        self.release.wait(timeout=0.5)
        self.calls.append(kwargs)


async def assert_hook_does_not_block(coroutine, trail, expected_call):
    task = asyncio.create_task(coroutine)
    await asyncio.sleep(0)

    try:
        assert not task.done(), "hook blocked the event loop until log() returned"
    finally:
        trail.release.set()
        await task

    assert trail.calls == [expected_call]


class TestOpenAIAgentsHooks:
    async def test_on_tool_end_does_not_block_event_loop(self, openai_run_hooks):
        trail = BlockingTrail()
        hook = openai_run_hooks(trail=trail)

        await assert_hook_does_not_block(
            hook.on_tool_end(
                None,
                SimpleNamespace(name="researcher"),
                SimpleNamespace(name="web_search"),
                "search results",
            ),
            trail,
            {
                "content": "search results",
                "source": ContextSource.TOOL,
                "source_name": "openai:web_search",
                "metadata": {"agent": "researcher"},
            },
        )

    async def test_on_handoff_does_not_block_event_loop(self, openai_run_hooks):
        trail = BlockingTrail()
        hook = openai_run_hooks(trail=trail)

        await assert_hook_does_not_block(
            hook.on_handoff(
                None,
                SimpleNamespace(name="researcher"),
                SimpleNamespace(name="writer"),
            ),
            trail,
            {
                "content": "Handoff from researcher to writer",
                "source": ContextSource.AGENT,
                "source_name": "openai:researcher",
                "metadata": {"to_agent": "writer"},
            },
        )

    async def test_on_tool_end_logs_to_trail(self, openai_run_hooks, memory_trail):
        hook = openai_run_hooks(trail=memory_trail)
        context = None
        agent = SimpleNamespace(name="researcher")
        tool = SimpleNamespace(name="web_search")

        await hook.on_tool_end(context, agent, tool, "search results")

        records = memory_trail.query()
        assert len(records) == 1
        assert records[0]["source"] == ContextSource.TOOL.value
        assert records[0]["source_name"] == "openai:web_search"

        import hashlib
        import json

        metadata = json.loads(records[0]["metadata_json"])
        assert metadata["agent"] == "researcher"

        expected_hash = hashlib.sha256(b"search results").hexdigest()
        assert records[0]["content_hash"] == expected_hash

    async def test_on_handoff_logs_to_trail(self, openai_run_hooks, memory_trail):
        hook = openai_run_hooks(trail=memory_trail)
        context = None
        from_agent = SimpleNamespace(name="researcher")
        to_agent = SimpleNamespace(name="writer")

        await hook.on_handoff(context, from_agent, to_agent)

        records = memory_trail.query()
        assert len(records) == 1
        assert records[0]["source"] == ContextSource.AGENT.value
        assert records[0]["source_name"] == "openai:researcher"

        import hashlib
        import json

        metadata = json.loads(records[0]["metadata_json"])
        assert metadata["to_agent"] == "writer"

        expected_hash = hashlib.sha256(b"Handoff from researcher to writer").hexdigest()
        assert records[0]["content_hash"] == expected_hash

    async def test_on_tool_end_missing_name_fallback(
        self, openai_run_hooks, memory_trail
    ):
        hook = openai_run_hooks(trail=memory_trail)
        # Using bare objects which have no .name attribute
        await hook.on_tool_end(None, object(), object(), "content")

        records = memory_trail.query()
        import json

        metadata = json.loads(records[0]["metadata_json"])
        assert records[0]["source_name"] == "openai:unknown"
        assert metadata["agent"] == "unknown"

    async def test_on_handoff_missing_name_fallback(
        self, openai_run_hooks, memory_trail
    ):
        hook = openai_run_hooks(trail=memory_trail)
        await hook.on_handoff(None, object(), object())

        records = memory_trail.query()
        import json

        metadata = json.loads(records[0]["metadata_json"])
        assert records[0]["source_name"] == "openai:unknown"
        assert metadata["to_agent"] == "unknown"

    async def test_multi_step_chain_integrity(self, openai_run_hooks, memory_trail):
        hook = openai_run_hooks(trail=memory_trail)
        agent1 = SimpleNamespace(name="researcher")
        agent2 = SimpleNamespace(name="writer")
        tool1 = SimpleNamespace(name="search")
        tool2 = SimpleNamespace(name="save_file")

        # Simulate workflow
        await hook.on_tool_end(None, agent1, tool1, "found data")
        await hook.on_handoff(None, agent1, agent2)
        await hook.on_tool_end(None, agent2, tool2, "file saved")

        # Verify the cryptographic chain
        verdict = memory_trail.verify_chain()
        assert verdict.intact is True
        assert verdict.total_records == 3


class TestOpenAIAgentsImportError:
    @pytest.mark.skipif(_has_openai_agents, reason="openai-agents IS installed")
    def test_raises_import_error(self):
        from provena.integrations.openai_agents import ProvenaRunHooks

        with pytest.raises(ImportError, match="openai-agents"):
            ProvenaRunHooks(trail=ContextTrail(backend="memory"))
