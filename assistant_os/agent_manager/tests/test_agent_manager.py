"""
assistant_os/agent_manager/tests/test_agent_manager.py
====================================================
NOVA OS - Agent Manager: Unit Tests

Coverage:
    TestModels         — AgentManifest, AgentRecord, ScheduledTask, HealthReport
    TestAgentRegistry  — register, deregister, lookup, state transitions,
                         heartbeat, discovery (mocked), summary
    TestAgentScheduler — schedule, assign, running, complete, fail,
                         retry, cancel, priority ordering, stats
    TestHealthMonitor  — single check, bulk check, summarize,
                         heartbeat timeout detection, overload detection
    TestAgentManager   — full integration: register→schedule→assign→complete,
                         fail/retry, cancel, approval gate, health report

Strategy:
    All tests are OFFLINE — no network, no DB, no actual agent execution.
    Time-sensitive heartbeat tests use datetime manipulation directly.
"""

from __future__ import annotations

import sys
import os
import time
import unittest
from datetime import datetime, timedelta

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from assistant_os.agent_manager.models import (
    AgentLifecycleState,
    AgentManifest,
    AgentManagerConfig,
    AgentRecord,
    HealthReport,
    ScheduledTask,
    TaskScheduleState,
)
from assistant_os.agent_manager.registry import AgentRegistry
from assistant_os.agent_manager.scheduler import AgentScheduler, QueueFullError
from assistant_os.agent_manager.health_monitor import HealthMonitor
from assistant_os.agent_manager.agent_manager import AgentManager
from assistant_os.planner.models import AgentType, RiskLevel, TaskNode, TaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_manifest(
    agent_type: AgentType = AgentType.CODING,
    display_name: str = "Coding Agent",
    max_concurrent: int = 2,
) -> AgentManifest:
    return AgentManifest(
        agent_type     = agent_type,
        display_name   = display_name,
        description    = f"Test {agent_type.value} agent.",
        capabilities   = ["test_cap"],
        intent_patterns= ["test"],
        max_concurrent = max_concurrent,
        requires_llm   = False,
    )


def make_task_node(
    agent_type: AgentType = AgentType.CODING,
    instruction: str = "Write a test function",
    requires_approval: bool = False,
    risk_level: RiskLevel = RiskLevel.LOW,
) -> TaskNode:
    node = TaskNode(
        agent_type        = agent_type,
        instruction       = instruction,
        risk_level        = risk_level,
        requires_approval = requires_approval,
        plan_id           = "plan-test-001",
    )
    return node


# ===========================================================================
# Model Tests
# ===========================================================================

class TestAgentManifestModel(unittest.TestCase):

    def test_defaults(self):
        m = make_manifest()
        self.assertEqual(m.agent_type, AgentType.CODING)
        self.assertEqual(m.version, "1.0.0")
        self.assertFalse(m.requires_network)

    def test_to_dict_keys(self):
        d = make_manifest().to_dict()
        for key in ("agent_type", "display_name", "capabilities",
                    "max_concurrent", "version"):
            self.assertIn(key, d)

    def test_agent_type_value_in_dict(self):
        d = make_manifest(AgentType.RESEARCH).to_dict()
        self.assertEqual(d["agent_type"], "RESEARCH")


class TestAgentRecordModel(unittest.TestCase):

    def test_is_available_idle_below_limit(self):
        record = AgentRecord(
            manifest = make_manifest(max_concurrent=2),
            state    = AgentLifecycleState.IDLE,
        )
        record.active_task_count = 1
        self.assertTrue(record.is_available)

    def test_is_available_busy_at_limit(self):
        record = AgentRecord(
            manifest = make_manifest(max_concurrent=2),
            state    = AgentLifecycleState.BUSY,
        )
        record.active_task_count = 2
        self.assertFalse(record.is_available)

    def test_is_available_unhealthy(self):
        record = AgentRecord(
            manifest = make_manifest(),
            state    = AgentLifecycleState.UNHEALTHY,
        )
        self.assertFalse(record.is_available)

    def test_agent_type_property(self):
        m = make_manifest(AgentType.RESEARCH)
        record = AgentRecord(manifest=m)
        self.assertEqual(record.agent_type, AgentType.RESEARCH)

    def test_to_dict_structure(self):
        d = AgentRecord(manifest=make_manifest()).to_dict()
        self.assertIn("state", d)
        self.assertIn("manifest", d)
        self.assertIn("active_task_count", d)


class TestScheduledTaskModel(unittest.TestCase):

    def _make_task(self, retries=2):
        return ScheduledTask(
            task_id    = "tid-001",
            plan_id    = "plan-001",
            agent_type = AgentType.CODING,
            instruction= "Write a test",
            max_retries= retries,
        )

    def test_initial_state(self):
        t = self._make_task()
        self.assertEqual(t.state, TaskScheduleState.QUEUED)
        self.assertFalse(t.is_terminal)
        self.assertTrue(t.can_retry)

    def test_terminal_completed(self):
        t = self._make_task()
        t.state = TaskScheduleState.COMPLETED
        self.assertTrue(t.is_terminal)

    def test_terminal_aborted(self):
        t = self._make_task()
        t.state = TaskScheduleState.ABORTED
        self.assertTrue(t.is_terminal)

    def test_cannot_retry_at_max(self):
        t = self._make_task(retries=2)
        t.retry_count = 2
        self.assertFalse(t.can_retry)

    def test_to_dict_serializable(self):
        import json
        t = self._make_task()
        json.dumps(t.to_dict())  # Must not raise


# ===========================================================================
# Registry Tests
# ===========================================================================

class TestAgentRegistry(unittest.TestCase):

    def setUp(self):
        self.registry = AgentRegistry(auto_idle_on_register=True)

    def test_register_returns_record(self):
        m = make_manifest()
        record = self.registry.register(m)
        self.assertIsInstance(record, AgentRecord)
        self.assertEqual(record.agent_type, AgentType.CODING)

    def test_auto_idle_on_register(self):
        record = self.registry.register(make_manifest())
        self.assertEqual(record.state, AgentLifecycleState.IDLE)

    def test_register_no_auto_idle(self):
        registry = AgentRegistry(auto_idle_on_register=False)
        record = registry.register(make_manifest())
        self.assertEqual(record.state, AgentLifecycleState.REGISTERED)

    def test_get_registered(self):
        self.registry.register(make_manifest(AgentType.RESEARCH))
        record = self.registry.get(AgentType.RESEARCH)
        self.assertIsNotNone(record)
        self.assertEqual(record.agent_type, AgentType.RESEARCH)

    def test_get_unregistered_returns_none(self):
        self.assertIsNone(self.registry.get(AgentType.BROWSER))

    def test_deregister(self):
        self.registry.register(make_manifest(AgentType.CODING))
        result = self.registry.deregister(AgentType.CODING)
        self.assertTrue(result)
        self.assertIsNone(self.registry.get(AgentType.CODING))

    def test_deregister_unknown_returns_false(self):
        self.assertFalse(self.registry.deregister(AgentType.STUDY))

    def test_list_all(self):
        self.registry.register(make_manifest(AgentType.CODING))
        self.registry.register(make_manifest(AgentType.RESEARCH, "Research"))
        self.assertEqual(len(self.registry.list_all()), 2)

    def test_list_idle(self):
        self.registry.register(make_manifest(AgentType.CODING))
        self.registry.register(make_manifest(AgentType.RESEARCH, "Research"))
        self.registry.update_state(AgentType.RESEARCH, AgentLifecycleState.BUSY)
        idle = self.registry.list_idle()
        self.assertEqual(len(idle), 1)
        self.assertEqual(idle[0].agent_type, AgentType.CODING)

    def test_update_state(self):
        self.registry.register(make_manifest())
        self.registry.update_state(AgentType.CODING, AgentLifecycleState.UNHEALTHY)
        record = self.registry.get(AgentType.CODING)
        self.assertEqual(record.state, AgentLifecycleState.UNHEALTHY)

    def test_update_heartbeat_clears_unhealthy(self):
        self.registry.register(make_manifest())
        self.registry.update_state(AgentType.CODING, AgentLifecycleState.UNHEALTHY)
        self.registry.update_heartbeat(AgentType.CODING)
        record = self.registry.get(AgentType.CODING)
        self.assertEqual(record.state, AgentLifecycleState.IDLE)
        self.assertIsNotNone(record.last_heartbeat)

    def test_increment_decrement_active(self):
        self.registry.register(make_manifest())
        self.registry.increment_active(AgentType.CODING)
        record = self.registry.get(AgentType.CODING)
        self.assertEqual(record.active_task_count, 1)
        self.assertEqual(record.state, AgentLifecycleState.BUSY)
        self.registry.decrement_active(AgentType.CODING, success=True)
        self.assertEqual(record.active_task_count, 0)
        self.assertEqual(record.state, AgentLifecycleState.IDLE)
        self.assertEqual(record.total_tasks_completed, 1)

    def test_hot_reload_updates_manifest(self):
        m1 = make_manifest(AgentType.CODING, display_name="v1")
        m2 = make_manifest(AgentType.CODING, display_name="v2")
        self.registry.register(m1)
        self.registry.register(m2)
        record = self.registry.get(AgentType.CODING)
        self.assertEqual(record.manifest.display_name, "v2")
        # Only one record exists
        self.assertEqual(len(self.registry.list_all()), 1)

    def test_get_available_returns_none_when_unhealthy(self):
        self.registry.register(make_manifest())
        self.registry.update_state(AgentType.CODING, AgentLifecycleState.UNHEALTHY)
        self.assertIsNone(self.registry.get_available(AgentType.CODING))

    def test_discover_agents_missing_dir(self):
        count = self.registry.discover_agents("/nonexistent/path")
        self.assertEqual(count, 0)

    def test_summary_structure(self):
        self.registry.register(make_manifest(AgentType.CODING))
        s = self.registry.summary()
        self.assertIn("total_registered", s)
        self.assertIn("agents", s)
        self.assertEqual(s["total_registered"], 1)


# ===========================================================================
# Scheduler Tests
# ===========================================================================

class TestAgentScheduler(unittest.TestCase):

    def setUp(self):
        self.scheduler = AgentScheduler(max_queue_depth=10, default_max_retries=2)

    def _node(self, agent=AgentType.CODING):
        return make_task_node(agent_type=agent)

    def test_schedule_returns_scheduled_task(self):
        node = self._node()
        t = self.scheduler.schedule(node)
        self.assertIsInstance(t, ScheduledTask)
        self.assertEqual(t.state, TaskScheduleState.QUEUED)

    def test_schedule_idempotent(self):
        node = self._node()
        t1 = self.scheduler.schedule(node)
        t2 = self.scheduler.schedule(node)
        self.assertEqual(t1.task_id, t2.task_id)

    def test_assign_transitions_state(self):
        node = self._node()
        self.scheduler.schedule(node)
        result = self.scheduler.assign(node.task_id, AgentType.CODING)
        self.assertTrue(result)
        t = self.scheduler.get_task(node.task_id)
        self.assertEqual(t.state, TaskScheduleState.ASSIGNED)
        self.assertIsNotNone(t.assigned_at)

    def test_mark_running(self):
        node = self._node()
        self.scheduler.schedule(node)
        self.scheduler.assign(node.task_id, AgentType.CODING)
        self.scheduler.mark_running(node.task_id)
        t = self.scheduler.get_task(node.task_id)
        self.assertEqual(t.state, TaskScheduleState.RUNNING)

    def test_complete(self):
        node = self._node()
        self.scheduler.schedule(node)
        self.scheduler.assign(node.task_id, AgentType.CODING)
        self.scheduler.mark_running(node.task_id)
        self.scheduler.complete(node.task_id)
        t = self.scheduler.get_task(node.task_id)
        self.assertEqual(t.state, TaskScheduleState.COMPLETED)
        self.assertTrue(t.is_terminal)

    def test_fail_with_retries(self):
        node = self._node()
        self.scheduler.schedule(node)
        new_state = self.scheduler.fail(node.task_id, "Test error")
        self.assertEqual(new_state, TaskScheduleState.RETRYING)
        t = self.scheduler.get_task(node.task_id)
        self.assertEqual(t.retry_count, 1)

    def test_fail_max_retries_aborted(self):
        node = self._node()
        self.scheduler.schedule(node, max_retries=1)
        self.scheduler.fail(node.task_id, "err")  # retry_count → 1
        new_state = self.scheduler.fail(node.task_id, "err2")  # max reached
        self.assertEqual(new_state, TaskScheduleState.ABORTED)

    def test_cancel_queued_task(self):
        node = self._node()
        self.scheduler.schedule(node)
        result = self.scheduler.cancel(node.task_id, "User cancelled")
        self.assertTrue(result)
        t = self.scheduler.get_task(node.task_id)
        self.assertEqual(t.state, TaskScheduleState.CANCELLED)

    def test_cancel_terminal_fails(self):
        node = self._node()
        self.scheduler.schedule(node)
        self.scheduler.complete(node.task_id)
        result = self.scheduler.cancel(node.task_id, "Too late")
        self.assertFalse(result)

    def test_get_queued_sorted_by_priority(self):
        n1 = make_task_node(instruction="low prio")
        n2 = make_task_node(instruction="high prio")
        self.scheduler.schedule(n1, priority=0)
        self.scheduler.schedule(n2, priority=10)
        queued = self.scheduler.get_queued()
        # Higher priority should be first
        self.assertEqual(queued[0].task_id, n2.task_id)

    def test_queue_full_raises(self):
        sched = AgentScheduler(max_queue_depth=2)
        sched.schedule(make_task_node())
        sched.schedule(make_task_node())
        with self.assertRaises(QueueFullError):
            sched.schedule(make_task_node())

    def test_stats_structure(self):
        node = self._node()
        self.scheduler.schedule(node)
        stats = self.scheduler.stats()
        self.assertIn("QUEUED", stats)
        self.assertIn("total", stats)
        self.assertEqual(stats["QUEUED"], 1)

    def test_get_tasks_for_plan(self):
        n1 = make_task_node(instruction="step 1")
        n2 = make_task_node(instruction="step 2")
        n2.plan_id = "other-plan"
        self.scheduler.schedule(n1)
        self.scheduler.schedule(n2)
        tasks = self.scheduler.get_tasks_for_plan(n1.plan_id)
        self.assertEqual(len(tasks), 1)


# ===========================================================================
# HealthMonitor Tests
# ===========================================================================

class TestHealthMonitor(unittest.TestCase):

    def setUp(self):
        self.monitor  = HealthMonitor(heartbeat_timeout_sec=10, auto_mark_unhealthy=False)
        self.registry = AgentRegistry(auto_idle_on_register=True)
        self.manifest = make_manifest()

    def _idle_record(self):
        return AgentRecord(manifest=self.manifest, state=AgentLifecycleState.IDLE)

    def test_healthy_idle_agent(self):
        record = self._idle_record()
        record.last_heartbeat = datetime.utcnow()
        report = self.monitor.check(record)
        self.assertTrue(report.is_healthy)
        self.assertEqual(len(report.issues), 0)

    def test_unhealthy_stale_heartbeat(self):
        record = self._idle_record()
        record.last_heartbeat = datetime.utcnow() - timedelta(seconds=60)
        report = self.monitor.check(record)
        self.assertFalse(report.is_healthy)
        self.assertTrue(any("stale" in issue for issue in report.issues))

    def test_unhealthy_overloaded(self):
        record = self._idle_record()
        record.last_heartbeat    = datetime.utcnow()
        record.active_task_count = 99  # Way over max_concurrent=2
        report = self.monitor.check(record)
        self.assertFalse(report.is_healthy)
        self.assertTrue(any("Overloaded" in issue for issue in report.issues))

    def test_deregistered_agent_unhealthy(self):
        record = AgentRecord(
            manifest = self.manifest,
            state    = AgentLifecycleState.DEREGISTERED,
        )
        report = self.monitor.check(record)
        self.assertFalse(report.is_healthy)

    def test_check_all_returns_all(self):
        self.registry.register(make_manifest(AgentType.CODING))
        self.registry.register(make_manifest(AgentType.RESEARCH, "Research"))
        reports = self.monitor.check_all(self.registry)
        self.assertEqual(len(reports), 2)

    def test_summarize_healthy(self):
        record = self._idle_record()
        record.last_heartbeat = datetime.utcnow()
        report  = self.monitor.check(record)
        summary = self.monitor.summarize([report])
        self.assertEqual(summary["status"], "HEALTHY")
        self.assertEqual(summary["healthy"], 1)

    def test_summarize_degraded(self):
        r1 = self._idle_record()
        r1.last_heartbeat = datetime.utcnow()
        r2 = self._idle_record()
        r2.last_heartbeat = datetime.utcnow() - timedelta(seconds=999)
        rep1 = self.monitor.check(r1)
        rep2 = self.monitor.check(r2)
        summary = self.monitor.summarize([rep1, rep2])
        self.assertEqual(summary["status"], "DEGRADED")

    def test_summarize_no_agents(self):
        summary = self.monitor.summarize([])
        self.assertEqual(summary["status"], "NO_AGENTS")

    def test_auto_mark_unhealthy_updates_registry(self):
        monitor = HealthMonitor(heartbeat_timeout_sec=10, auto_mark_unhealthy=True)
        self.registry.register(make_manifest(AgentType.CODING))
        record = self.registry.get(AgentType.CODING)
        record.last_heartbeat = datetime.utcnow() - timedelta(seconds=60)
        monitor.check(record, registry=self.registry)
        self.assertEqual(record.state, AgentLifecycleState.UNHEALTHY)


# ===========================================================================
# AgentManager Integration Tests
# ===========================================================================

class TestAgentManager(unittest.TestCase):

    def setUp(self):
        config = AgentManagerConfig(
            heartbeat_timeout_sec = 30,
            auto_idle_on_register = True,
            default_max_retries   = 2,
        )
        self.manager = AgentManager(config=config)

    def _register_coding(self) -> AgentManifest:
        m = make_manifest(AgentType.CODING)
        self.manager.register_agent(m)
        return m

    def test_register_agent(self):
        m = self._register_coding()
        record = self.manager.get_registered_agent(AgentType.CODING)
        self.assertIsNotNone(record)
        self.assertEqual(record.agent_type, AgentType.CODING)

    def test_deregister_agent(self):
        self._register_coding()
        result = self.manager.deregister_agent(AgentType.CODING)
        self.assertTrue(result)
        self.assertIsNone(self.manager.get_registered_agent(AgentType.CODING))

    def test_schedule_task_returns_scheduled(self):
        self._register_coding()
        node = make_task_node()
        t = self.manager.schedule_task(node)
        self.assertIsInstance(t, ScheduledTask)

    def test_schedule_assigns_immediately_when_idle(self):
        """Task is immediately ASSIGNED when an idle agent is available."""
        self._register_coding()
        node = make_task_node()
        t = self.manager.schedule_task(node, auto_assign=True)
        self.assertEqual(t.state, TaskScheduleState.ASSIGNED)

    def test_schedule_stays_queued_no_agent(self):
        """Task stays QUEUED when no agent is registered."""
        node = make_task_node()
        t = self.manager.schedule_task(node, auto_assign=True)
        self.assertEqual(t.state, TaskScheduleState.QUEUED)

    def test_approval_gate_blocks_assignment(self):
        """Tasks requiring approval must NOT be auto-assigned."""
        self._register_coding()
        node = make_task_node(requires_approval=True)
        t = self.manager.schedule_task(node, auto_assign=True)
        self.assertEqual(t.state, TaskScheduleState.QUEUED)

    def test_approve_and_assign(self):
        self._register_coding()
        node = make_task_node(requires_approval=True)
        t = self.manager.schedule_task(node)
        self.assertEqual(t.state, TaskScheduleState.QUEUED)
        result = self.manager.approve_and_assign(node.task_id)
        self.assertTrue(result)
        t = self.manager.get_scheduled_task(node.task_id)
        self.assertEqual(t.state, TaskScheduleState.ASSIGNED)

    def test_complete_task_full_cycle(self):
        self._register_coding()
        node = make_task_node()
        self.manager.schedule_task(node)
        self.manager.mark_task_running(node.task_id)
        result = self.manager.complete_task(node.task_id)
        self.assertTrue(result)
        t = self.manager.get_scheduled_task(node.task_id)
        self.assertEqual(t.state, TaskScheduleState.COMPLETED)

    def test_fail_task_retries(self):
        self._register_coding()
        node = make_task_node()
        self.manager.schedule_task(node)
        new_state = self.manager.fail_task(node.task_id, "temporary error")
        self.assertEqual(new_state, TaskScheduleState.RETRYING)

    def test_fail_task_exhausts_retries(self):
        config = AgentManagerConfig(default_max_retries=1)
        manager = AgentManager(config=config)
        manager.register_agent(make_manifest())
        node = make_task_node()
        manager.schedule_task(node)
        manager.fail_task(node.task_id, "err1")  # → RETRYING (retry 1/1)
        new_state = manager.fail_task(node.task_id, "err2")  # → ABORTED
        self.assertEqual(new_state, TaskScheduleState.ABORTED)

    def test_cancel_task(self):
        self._register_coding()
        node = make_task_node()
        self.manager.schedule_task(node)
        result = self.manager.cancel_task(node.task_id, "user cancelled")
        self.assertTrue(result)
        t = self.manager.get_scheduled_task(node.task_id)
        self.assertEqual(t.state, TaskScheduleState.CANCELLED)

    def test_heartbeat(self):
        self._register_coding()
        result = self.manager.heartbeat(AgentType.CODING)
        self.assertTrue(result)
        record = self.manager.get_registered_agent(AgentType.CODING)
        self.assertIsNotNone(record.last_heartbeat)

    def test_heartbeat_unknown_agent(self):
        result = self.manager.heartbeat(AgentType.BROWSER)
        self.assertFalse(result)

    def test_get_health_report(self):
        self._register_coding()
        reports = self.manager.get_health_report()
        self.assertEqual(len(reports), 1)
        self.assertIsInstance(reports[0], HealthReport)

    def test_get_health_summary_structure(self):
        self._register_coding()
        summary = self.manager.get_health_summary()
        self.assertIn("status", summary)
        self.assertIn("healthy", summary)
        self.assertIn("agents", summary)

    def test_scheduler_stats(self):
        self._register_coding()
        node = make_task_node()
        self.manager.schedule_task(node)
        stats = self.manager.scheduler_stats()
        self.assertIn("total", stats)
        self.assertGreaterEqual(stats["total"], 1)

    def test_discover_agents_empty_dir(self):
        count = self.manager.discover_agents("/nonexistent/path")
        self.assertEqual(count, 0)

    def test_registry_summary(self):
        self._register_coding()
        s = self.manager.registry_summary()
        self.assertEqual(s["total_registered"], 1)

    def test_active_count_managed_on_complete(self):
        """active_task_count must be decremented when task completes."""
        self._register_coding()
        node = make_task_node()
        self.manager.schedule_task(node)
        self.manager.mark_task_running(node.task_id)
        record = self.manager.get_registered_agent(AgentType.CODING)
        # Count should be 1 (assigned)
        self.assertEqual(record.active_task_count, 1)
        self.manager.complete_task(node.task_id)
        self.assertEqual(record.active_task_count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
