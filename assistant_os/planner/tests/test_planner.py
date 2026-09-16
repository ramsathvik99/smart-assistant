"""
assistant_os/planner/tests/test_planner.py
=======================================
NOVA OS - Planner Module: Unit Tests

Coverage:
    - models.py          : BrainOutput, TaskNode, TaskPlan, TaskStatus, AgentType
    - dependency_resolver: Kahn sort, cycle detection, parallel group detection
    - intent_classifier  : Keyword heuristics (no LLM calls in tests)
    - goal_decomposer    : Fallback single-step behaviour (no LLM/external deps)
    - planner.py         : Full create_plan() integration tests (offline mode)

Strategy:
    All tests run OFFLINE (use_llm=False, no network/DB required).
    LLM-dependent branches are validated separately via explicit mock tests.
    No patches of existing extensions are needed — the offline flag
    disables external calls cleanly.
"""

from __future__ import annotations

import sys
import os
import unittest

# Ensure assistant_os package is importable without installing it.
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from assistant_os.planner.models import (
    AgentType,
    BrainOutput,
    PlannerConfig,
    RiskLevel,
    TaskNode,
    TaskPlan,
    TaskStatus,
)
from assistant_os.planner.dependency_resolver import (
    CyclicDependencyError,
    DependencyResolver,
    UnknownDependencyError,
)
from assistant_os.planner.intent_classifier import IntentClassifier
from assistant_os.planner.planner import Planner


# ===========================================================================
# Model Tests
# ===========================================================================

class TestBrainOutputModel(unittest.TestCase):
    """Verify BrainOutput defaults and field assignments."""

    def test_defaults(self):
        bo = BrainOutput(goal="Do something", raw_input="Do something")
        self.assertEqual(bo.goal, "Do something")
        self.assertEqual(bo.modality, "text")
        self.assertIsInstance(bo.session_id, str)
        self.assertIsNone(bo.user_id)
        self.assertEqual(bo.attachments, [])
        self.assertEqual(bo.context, {})

    def test_custom_fields(self):
        bo = BrainOutput(
            goal="Research AI",
            raw_input="Research AI please",
            user_id=42,
            modality="voice",
            attachments=["file.pdf"],
        )
        self.assertEqual(bo.user_id, 42)
        self.assertEqual(bo.modality, "voice")
        self.assertIn("file.pdf", bo.attachments)


class TestTaskNodeModel(unittest.TestCase):
    """Verify TaskNode defaults and field behaviour."""

    def test_defaults(self):
        node = TaskNode()
        self.assertEqual(node.status, TaskStatus.PENDING)
        self.assertEqual(node.agent_type, AgentType.UNKNOWN)
        self.assertFalse(node.can_run_parallel)
        self.assertFalse(node.requires_approval)
        self.assertEqual(node.dependencies, [])
        self.assertIsInstance(node.task_id, str)
        self.assertTrue(len(node.task_id) == 36)  # UUID4 format

    def test_unique_ids(self):
        n1 = TaskNode()
        n2 = TaskNode()
        self.assertNotEqual(n1.task_id, n2.task_id)


class TestTaskPlanModel(unittest.TestCase):
    """Verify TaskPlan computed fields and helper methods."""

    def _make_plan(self, n_tasks=3):
        nodes = [
            TaskNode(agent_type=AgentType.RESEARCH, instruction=f"Step {i}")
            for i in range(n_tasks)
        ]
        return TaskPlan(goal="Test goal", tasks=nodes)

    def test_total_tasks_computed(self):
        plan = self._make_plan(4)
        self.assertEqual(plan.total_tasks, 4)

    def test_has_approvals_false(self):
        plan = self._make_plan(2)
        self.assertFalse(plan.has_approvals)

    def test_has_approvals_true(self):
        nodes = [TaskNode(requires_approval=True), TaskNode()]
        plan = TaskPlan(goal="risky", tasks=nodes)
        self.assertTrue(plan.has_approvals)

    def test_get_task_found(self):
        plan = self._make_plan(3)
        target = plan.tasks[1]
        result = plan.get_task(target.task_id)
        self.assertEqual(result, target)

    def test_get_task_not_found(self):
        plan = self._make_plan(2)
        self.assertIsNone(plan.get_task("nonexistent-id"))

    def test_get_ready_tasks_initial(self):
        """With no dependencies and PENDING status, all tasks are ready."""
        nodes = [TaskNode(instruction=f"Step {i}") for i in range(3)]
        plan = TaskPlan(goal="parallel test", tasks=nodes)
        ready = plan.get_ready_tasks()
        self.assertEqual(len(ready), 3)

    def test_get_ready_tasks_with_dependency(self):
        """A task with a PENDING dependency is NOT ready."""
        n1 = TaskNode(instruction="step 1")
        n2 = TaskNode(instruction="step 2", dependencies=[n1.task_id])
        plan = TaskPlan(goal="sequential", tasks=[n1, n2])
        ready = plan.get_ready_tasks()
        # Only n1 is ready; n2 depends on n1 which is still PENDING
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].task_id, n1.task_id)

    def test_get_ready_tasks_after_completion(self):
        """After n1 is DONE, n2 becomes ready."""
        n1 = TaskNode(instruction="step 1")
        n2 = TaskNode(instruction="step 2", dependencies=[n1.task_id])
        plan = TaskPlan(goal="sequential", tasks=[n1, n2])
        n1.status = TaskStatus.DONE
        ready = plan.get_ready_tasks()
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].task_id, n2.task_id)

    def test_to_dict_structure(self):
        plan = self._make_plan(2)
        d = plan.to_dict()
        self.assertIn("plan_id", d)
        self.assertIn("tasks", d)
        self.assertEqual(len(d["tasks"]), 2)
        self.assertIn("agent_type", d["tasks"][0])


# ===========================================================================
# DependencyResolver Tests
# ===========================================================================

class TestDependencyResolver(unittest.TestCase):
    """Verify Kahn's algorithm, cycle detection, and group computation."""

    def setUp(self):
        self.resolver = DependencyResolver()

    def _nodes(self, n=3):
        return [TaskNode(instruction=f"Task {i}") for i in range(n)]

    def test_empty_input(self):
        nodes, groups = self.resolver.resolve([])
        self.assertEqual(nodes, [])
        self.assertEqual(groups, [])

    def test_single_node(self):
        nodes = self._nodes(1)
        sorted_nodes, groups = self.resolver.resolve(nodes)
        self.assertEqual(len(sorted_nodes), 1)
        self.assertEqual(len(groups), 1)
        self.assertFalse(sorted_nodes[0].can_run_parallel)

    def test_sequential_chain(self):
        """A → B → C must produce 3 separate execution waves."""
        a, b, c = self._nodes(3)
        b.dependencies = [a.task_id]
        c.dependencies = [b.task_id]
        sorted_nodes, groups = self.resolver.resolve([a, b, c])
        self.assertEqual(len(sorted_nodes), 3)
        self.assertEqual(len(groups), 3)
        # All in their own wave — none can run in parallel
        for node in sorted_nodes:
            self.assertFalse(node.can_run_parallel)

    def test_parallel_detection(self):
        """B and C both depend only on A — they should be in the same wave."""
        a, b, c = self._nodes(3)
        b.dependencies = [a.task_id]
        c.dependencies = [a.task_id]
        _, groups = self.resolver.resolve([a, b, c])
        # Wave 0: [a], Wave 1: [b, c]
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[1]), 2)

    def test_parallel_flag_set(self):
        """Nodes in a multi-member wave must have can_run_parallel=True."""
        a, b, c = self._nodes(3)
        b.dependencies = [a.task_id]
        c.dependencies = [a.task_id]
        sorted_nodes, _ = self.resolver.resolve([a, b, c])
        node_map = {n.task_id: n for n in sorted_nodes}
        self.assertFalse(node_map[a.task_id].can_run_parallel)
        self.assertTrue(node_map[b.task_id].can_run_parallel)
        self.assertTrue(node_map[c.task_id].can_run_parallel)

    def test_position_assigned(self):
        """Positions should be assigned 0, 1, 2 in topological order."""
        a, b, c = self._nodes(3)
        b.dependencies = [a.task_id]
        c.dependencies = [b.task_id]
        sorted_nodes, _ = self.resolver.resolve([a, b, c])
        positions = [n.position for n in sorted_nodes]
        self.assertEqual(positions, [0, 1, 2])

    def test_cycle_detection(self):
        """A cycle must raise CyclicDependencyError."""
        a, b = self._nodes(2)
        a.dependencies = [b.task_id]
        b.dependencies = [a.task_id]
        with self.assertRaises(CyclicDependencyError):
            self.resolver.resolve([a, b])

    def test_unknown_dependency(self):
        """Reference to non-existent task_id must raise UnknownDependencyError."""
        a = TaskNode(instruction="lone wolf", dependencies=["ghost-id-000"])
        with self.assertRaises(UnknownDependencyError):
            self.resolver.resolve([a])

    def test_diamond_dependency(self):
        """
        Diamond: A→B, A→C, B→D, C→D
        Waves: [A], [B,C], [D]
        """
        a, b, c, d = [TaskNode(instruction=f"Task {i}") for i in range(4)]
        b.dependencies = [a.task_id]
        c.dependencies = [a.task_id]
        d.dependencies = [b.task_id, c.task_id]
        _, groups = self.resolver.resolve([a, b, c, d])
        self.assertEqual(len(groups), 3)
        self.assertEqual(len(groups[0]), 1)  # [A]
        self.assertEqual(len(groups[1]), 2)  # [B, C]
        self.assertEqual(len(groups[2]), 1)  # [D]


# ===========================================================================
# IntentClassifier Tests
# ===========================================================================

class TestIntentClassifier(unittest.TestCase):
    """Verify keyword heuristics with use_llm=False (offline)."""

    def setUp(self):
        self.clf = IntentClassifier(use_llm=False)

    def test_coding_intent(self):
        agent, _ = self.clf.classify("Write a Python function to sort a list")
        self.assertEqual(agent, AgentType.CODING)

    def test_research_intent(self):
        agent, _ = self.clf.classify("Research the latest AI trends and summarize")
        self.assertEqual(agent, AgentType.RESEARCH)

    def test_automation_intent(self):
        agent, _ = self.clf.classify("Open VS Code and launch the terminal")
        self.assertEqual(agent, AgentType.AUTOMATION)

    def test_conversation_intent(self):
        agent, _ = self.clf.classify("Tell me a joke please")
        self.assertEqual(agent, AgentType.CONVERSATION)

    def test_memory_intent(self):
        agent, _ = self.clf.classify("Remember that I prefer dark mode")
        self.assertEqual(agent, AgentType.MEMORY)

    def test_study_intent(self):
        agent, _ = self.clf.classify("Quiz me on Python decorators")
        self.assertEqual(agent, AgentType.STUDY)

    def test_browser_intent(self):
        agent, _ = self.clf.classify("Navigate to github.com and open my repo")
        self.assertEqual(agent, AgentType.BROWSER)

    def test_unknown_falls_back_offline(self):
        """With use_llm=False, unmatched instructions return UNKNOWN."""
        agent, _ = self.clf.classify("xyzzy plugh frobozz")
        self.assertEqual(agent, AgentType.UNKNOWN)

    def test_low_risk_for_chat(self):
        _, risk = self.clf.classify("Tell me a story")
        self.assertEqual(risk, RiskLevel.LOW)

    def test_high_risk_for_delete(self):
        _, risk = self.clf.classify("Delete all files in Downloads")
        self.assertEqual(risk, RiskLevel.HIGH)

    def test_medium_risk_for_automation(self):
        _, risk = self.clf.classify("Launch the terminal")
        self.assertEqual(risk, RiskLevel.MEDIUM)

    def test_critical_risk(self):
        _, risk = self.clf.classify("Delete all my data and format drive")
        self.assertEqual(risk, RiskLevel.CRITICAL)


# ===========================================================================
# Planner Integration Tests (Offline)
# ===========================================================================

class TestPlannerIntegration(unittest.TestCase):
    """
    End-to-end Planner tests using offline mode (use_llm=False).
    GoalInterpreter may or may not match; fallback single-task
    behaviour is guaranteed.
    """

    def setUp(self):
        config = PlannerConfig(use_llm=False, auto_approve_low=True)
        self.planner = Planner(config=config)

    def _brain(self, goal: str) -> BrainOutput:
        return BrainOutput(goal=goal, raw_input=goal)

    def test_returns_task_plan(self):
        plan = self.planner.create_plan(self._brain("Open VS Code"))
        self.assertIsInstance(plan, TaskPlan)

    def test_plan_has_at_least_one_task(self):
        plan = self.planner.create_plan(self._brain("Do something vague"))
        self.assertGreaterEqual(plan.total_tasks, 1)

    def test_all_nodes_are_pending(self):
        """Planner never sets status to anything other than PENDING."""
        plan = self.planner.create_plan(self._brain("Research and email results"))
        for task in plan.tasks:
            self.assertEqual(task.status, TaskStatus.PENDING)

    def test_plan_id_is_uuid(self):
        plan = self.planner.create_plan(self._brain("Do something"))
        self.assertEqual(len(plan.plan_id), 36)

    def test_node_plan_ids_match_plan(self):
        """Every node's plan_id must equal the parent plan's plan_id."""
        plan = self.planner.create_plan(self._brain("Research AI"))
        for task in plan.tasks:
            self.assertEqual(task.plan_id, plan.plan_id)

    def test_execution_groups_not_empty(self):
        plan = self.planner.create_plan(self._brain("Open browser and search"))
        self.assertGreater(len(plan.execution_groups), 0)

    def test_automation_goal_types(self):
        """'Open VS Code' should route to AUTOMATION agent."""
        plan = self.planner.create_plan(self._brain("Open VS Code"))
        agent_types = {t.agent_type for t in plan.tasks}
        self.assertIn(AgentType.AUTOMATION, agent_types)

    def test_high_risk_requires_approval(self):
        """A task involving 'delete' must have requires_approval=True."""
        plan = self.planner.create_plan(self._brain("Delete all downloads"))
        approval_tasks = [t for t in plan.tasks if t.requires_approval]
        self.assertGreater(len(approval_tasks), 0)

    def test_low_risk_auto_approved(self):
        """
        With auto_approve_low=True, a pure chat task should NOT
        require approval.
        """
        plan = self.planner.create_plan(self._brain("Tell me a joke"))
        approval_tasks = [t for t in plan.tasks if t.requires_approval]
        # May be empty if all tasks are LOW risk
        for t in plan.tasks:
            if t.risk_level == RiskLevel.LOW:
                self.assertFalse(t.requires_approval)

    def test_max_tasks_respected(self):
        """Planner must cap at config.max_tasks."""
        config = PlannerConfig(use_llm=False, max_tasks=2)
        planner = Planner(config=config)
        plan = planner.create_plan(
            self._brain("Step 1, Step 2, Step 3, Step 4, Step 5")
        )
        self.assertLessEqual(plan.total_tasks, 2)

    def test_session_id_carried_through(self):
        bo = BrainOutput(goal="Test", raw_input="Test", session_id="my-session-123")
        plan = self.planner.create_plan(bo)
        self.assertEqual(plan.session_id, "my-session-123")

    def test_to_dict_is_json_serializable(self):
        """TaskPlan.to_dict() must return a structure with no non-serializable types."""
        import json
        plan = self.planner.create_plan(self._brain("Research AI trends"))
        try:
            json.dumps(plan.to_dict())
        except (TypeError, ValueError) as exc:
            self.fail(f"TaskPlan.to_dict() is not JSON-serializable: {exc}")


# ===========================================================================
# Edge Case Tests
# ===========================================================================

class TestPlannerEdgeCases(unittest.TestCase):

    def setUp(self):
        config = PlannerConfig(use_llm=False)
        self.planner = Planner(config=config)

    def test_empty_goal_produces_plan(self):
        """An empty or whitespace goal must not crash — return a single fallback task."""
        bo = BrainOutput(goal="   ", raw_input="")
        plan = self.planner.create_plan(bo)
        self.assertGreaterEqual(plan.total_tasks, 1)

    def test_very_long_goal(self):
        """A very long goal string must be handled gracefully."""
        long_goal = "search " * 200
        bo = BrainOutput(goal=long_goal, raw_input=long_goal)
        plan = self.planner.create_plan(bo)
        self.assertIsInstance(plan, TaskPlan)

    def test_special_characters_in_goal(self):
        """Goals with special characters must not raise exceptions."""
        bo = BrainOutput(goal="Run: rm -rf /* and email results!", raw_input="...")
        plan = self.planner.create_plan(bo)
        self.assertIsInstance(plan, TaskPlan)


if __name__ == "__main__":
    unittest.main(verbosity=2)
