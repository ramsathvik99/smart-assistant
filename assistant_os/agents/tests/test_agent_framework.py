"""
assistant_os/agents/tests/test_agent_framework.py
=============================================
NOVA OS - Agent Framework: Unit Tests

Coverage:
    - BaseAgent & AgentClassRegistry subclass auto-registration.
    - AgentTask & AgentResult validation and properties.
    - Template execution pipeline (run(), execute(), pre/post-run hooks).
    - Tool invocation and error handling within agents.
"""

import sys
import os
import unittest
from typing import Dict, Any

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from assistant_os.planner.models import AgentType, RiskLevel
from assistant_os.agent_manager.models import AgentManifest
from assistant_os.agents.models import (
    AgentOutputType,
    AgentResult,
    AgentStatus,
    AgentTask,
    ContextPackage,
)
from assistant_os.agents.base_agent import BaseAgent, AgentClassRegistry


# ---------------------------------------------------------------------------
# Example / Mock Agent for Testing
# ---------------------------------------------------------------------------

class MockCodingAgent(BaseAgent):
    """A mock agent implementing the BaseAgent contract for testing."""

    AGENT_MANIFEST = AgentManifest(
        agent_type=AgentType.CODING,
        display_name="Mock Coding Agent",
        description="Used for unit testing the Agent Framework.",
        capabilities=["write_code", "run_tests"],
        intent_patterns=["code", "program"],
    )

    def __init__(self, tools=None):
        super().__init__(tools)
        self.pre_run_called = False
        self.post_run_called = False

    def _pre_run(self, task: AgentTask) -> None:
        self.pre_run_called = True

    def _post_run(self, task: AgentTask, result: AgentResult) -> None:
        self.post_run_called = True

    def execute(self, task: AgentTask) -> AgentResult:
        if "fail" in task.instruction:
            return self._failure(task, "Instructed to fail.")
        if "skip" in task.instruction:
            return self._skipped(task, "Instructed to skip.")
        if "call_tool" in task.instruction:
            try:
                res = self._call_tool("test_tool", "data")
                return self._success(task, f"Tool response: {res}", AgentOutputType.TEXT)
            except Exception as e:
                return self._failure(task, f"Tool error: {e}")

        # Default success
        return self._success(task, "Code generated successfully.", AgentOutputType.CODE, {"language": "python"})


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

class TestAgentClassRegistry(unittest.TestCase):

    def setUp(self):
        # Backup registry and clean it for testing
        self._backup = AgentClassRegistry._registry.copy()
        AgentClassRegistry._registry.clear()

    def tearDown(self):
        # Restore backup
        AgentClassRegistry._registry = self._backup

    def test_auto_registration(self):
        # Re-defining or registering subclass triggers registration
        AgentClassRegistry.register(AgentType.CODING, MockCodingAgent)
        self.assertTrue(AgentClassRegistry.is_registered(AgentType.CODING))
        self.assertEqual(AgentClassRegistry.get(AgentType.CODING), MockCodingAgent)

    def test_instantiate(self):
        AgentClassRegistry.register(AgentType.CODING, MockCodingAgent)
        agent = AgentClassRegistry.instantiate(AgentType.CODING)
        self.assertIsInstance(agent, MockCodingAgent)
        self.assertEqual(agent.manifest.agent_type, AgentType.CODING)

    def test_deregister(self):
        AgentClassRegistry.register(AgentType.CODING, MockCodingAgent)
        self.assertTrue(AgentClassRegistry.deregister(AgentType.CODING))
        self.assertFalse(AgentClassRegistry.is_registered(AgentType.CODING))


class TestAgentExecution(unittest.TestCase):

    def setUp(self):
        self.agent = MockCodingAgent()

    def test_run_success(self):
        task = AgentTask(
            agent_type=AgentType.CODING,
            instruction="Write a hello world function",
        )
        result = self.agent.run(task)
        self.assertTrue(result.is_success)
        self.assertEqual(result.status, AgentStatus.SUCCESS)
        self.assertEqual(result.output_type, AgentOutputType.CODE)
        self.assertEqual(result.content, "Code generated successfully.")
        self.assertTrue(self.agent.pre_run_called)
        self.assertTrue(self.agent.post_run_called)
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_run_failure_outcome(self):
        task = AgentTask(
            agent_type=AgentType.CODING,
            instruction="Please fail now",
        )
        result = self.agent.run(task)
        self.assertTrue(result.is_failure)
        self.assertEqual(result.status, AgentStatus.FAILED)
        self.assertEqual(result.error, "Instructed to fail.")

    def test_run_skipped_outcome(self):
        task = AgentTask(
            agent_type=AgentType.CODING,
            instruction="Please skip this",
        )
        result = self.agent.run(task)
        self.assertEqual(result.status, AgentStatus.SKIPPED)
        self.assertFalse(result.is_success)

    def test_run_invalid_agent_type(self):
        task = AgentTask(
            agent_type=AgentType.RESEARCH,
            instruction="Research AI trends",
        )
        result = self.agent.run(task)
        self.assertEqual(result.status, AgentStatus.FAILED)
        self.assertIn("does not match this agent's type", result.error)


class TestAgentTools(unittest.TestCase):

    def test_tool_execution(self):
        tools = {"test_tool": lambda x: f"hello {x}"}
        agent = MockCodingAgent(tools=tools)

        task = AgentTask(
            agent_type=AgentType.CODING,
            instruction="call_tool please",
        )
        result = agent.run(task)
        self.assertTrue(result.is_success)
        self.assertEqual(result.content, "Tool response: hello data")

    def test_missing_tool_error(self):
        agent = MockCodingAgent(tools={})  # Empty tools
        task = AgentTask(
            agent_type=AgentType.CODING,
            instruction="call_tool please",
        )
        result = agent.run(task)
        self.assertEqual(result.status, AgentStatus.FAILED)
        self.assertIn("Tool 'test_tool' is not available", result.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
