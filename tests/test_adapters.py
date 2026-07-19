"""Tests for framework adapters (CrewAI, AutoGen, OpenAI Agents SDK, Google ADK).

All tests use mock objects so they run without the framework installed.
"""

from __future__ import annotations

import pytest

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


_has_openai_agents = False
try:
    import agents  # noqa: F401

    _has_openai_agents = True
except ImportError:
    pass


class TestOpenAIAgentsImportError:
    @pytest.mark.skipif(_has_openai_agents, reason="openai-agents IS installed")
    def test_raises_import_error(self):
        from provena.integrations.openai_agents import ProvenaRunHooks

        with pytest.raises(ImportError, match="openai-agents"):
            ProvenaRunHooks(trail=ContextTrail(backend="memory"))
