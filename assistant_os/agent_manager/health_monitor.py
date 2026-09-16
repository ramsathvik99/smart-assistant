"""
assistant_os/agent_manager/health_monitor.py
=========================================
NOVA OS - Agent Manager: Health Monitor

Architecture:
    The HealthMonitor inspects AgentRecord objects from the Registry
    and produces HealthReport snapshots.  It applies configurable
    heuristic rules to determine whether each agent is healthy.

    Responsibilities:
        ✓ Check individual agents against health criteria.
        ✓ Check all registered agents in one pass.
        ✓ Mark UNHEALTHY agents in the Registry when heartbeats lapse.
        ✓ Produce a system-wide health summary.

    Health Criteria (checked in order):
        1. Agent state is not DEREGISTERED.
        2. Heartbeat received within heartbeat_timeout_sec.
           (Agents that have NEVER sent a heartbeat are given a grace
           period equal to heartbeat_timeout_sec — they are new.)
        3. active_task_count does not exceed max_concurrent.
           (Overloaded agents are flagged UNHEALTHY.)

    The HealthMonitor does NOT:
        ✗ Execute agents
        ✗ Restart agents
        ✗ Schedule tasks
        ✗ Do network I/O

    Periodic Checks:
        Callers (AgentManager) are responsible for scheduling periodic
        invocations.  The HealthMonitor is stateless between calls.

SDD Reference: Section 13 (Agent Manager — Health Monitoring).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from assistant_os.agent_manager.models import (
    AgentLifecycleState,
    AgentRecord,
    HealthReport,
)
from assistant_os.agent_manager.registry import AgentRegistry
from assistant_os.planner.models import AgentType

logger = logging.getLogger("assistant_os.agent_manager.health_monitor")


class HealthMonitor:
    """
    Evaluates the health of registered agents against a set of
    configurable criteria and reports findings.

    Usage:
        monitor = HealthMonitor(heartbeat_timeout_sec=30)
        report  = monitor.check(agent_record)
        reports = monitor.check_all(registry)
        summary = monitor.summarize(reports)
    """

    def __init__(
        self,
        heartbeat_timeout_sec: int = 30,
        auto_mark_unhealthy: bool = True,
    ):
        """
        Args:
            heartbeat_timeout_sec: Seconds after last heartbeat before
                                   an agent is considered UNHEALTHY.
            auto_mark_unhealthy:   When True, check() calls
                                   registry.update_state() to transition
                                   timed-out agents to UNHEALTHY automatically.
                                   Pass registry to check_all() for this.
        """
        self.heartbeat_timeout_sec = heartbeat_timeout_sec
        self.auto_mark_unhealthy   = auto_mark_unhealthy

    # ------------------------------------------------------------------
    # Single-Agent Check
    # ------------------------------------------------------------------

    def check(
        self,
        record: AgentRecord,
        registry: Optional[AgentRegistry] = None,
    ) -> HealthReport:
        """
        Evaluate the health of one agent.

        Args:
            record:   The AgentRecord to inspect.
            registry: If provided and auto_mark_unhealthy is True,
                      unhealthy agents are marked in the registry.

        Returns:
            HealthReport with is_healthy flag and issue list.
        """
        issues: List[str] = []
        now               = datetime.utcnow()

        # ── Rule 1: Agent must not be DEREGISTERED ────────────────────
        if record.state == AgentLifecycleState.DEREGISTERED:
            issues.append("Agent is DEREGISTERED.")
            return self._build_report(record, issues, now)

        # ── Rule 2: Heartbeat freshness ───────────────────────────────
        heartbeat_age: Optional[float] = None
        if record.last_heartbeat is not None:
            heartbeat_age = (now - record.last_heartbeat).total_seconds()
            if heartbeat_age > self.heartbeat_timeout_sec:
                issues.append(
                    f"Heartbeat stale: {heartbeat_age:.1f}s "
                    f"(timeout={self.heartbeat_timeout_sec}s)."
                )
                if self.auto_mark_unhealthy and registry:
                    registry.update_state(
                        record.agent_type, AgentLifecycleState.UNHEALTHY
                    )
                    logger.warning(
                        f"[HealthMonitor] {record.agent_type.value} marked UNHEALTHY — "
                        f"heartbeat stale by {heartbeat_age:.1f}s."
                    )
        else:
            # Never sent a heartbeat.  Only an issue if the agent is BUSY
            # (it should be sending heartbeats when running tasks).
            if record.state == AgentLifecycleState.BUSY:
                issues.append(
                    "Agent is BUSY but has never sent a heartbeat."
                )

        # ── Rule 3: Concurrency overload ─────────────────────────────
        if record.active_task_count > record.manifest.max_concurrent:
            issues.append(
                f"Overloaded: active_tasks={record.active_task_count} "
                f"> max_concurrent={record.manifest.max_concurrent}."
            )

        return self._build_report(record, issues, now, heartbeat_age)

    # ------------------------------------------------------------------
    # Bulk Check
    # ------------------------------------------------------------------

    def check_all(
        self,
        registry: AgentRegistry,
    ) -> List[HealthReport]:
        """
        Run a health check against every agent in the registry.

        Args:
            registry: The AgentRegistry to inspect.

        Returns:
            List of HealthReport, one per registered agent.
        """
        reports = []
        for record in registry.list_all():
            report = self.check(record, registry=registry)
            reports.append(report)

        healthy_count   = sum(1 for r in reports if r.is_healthy)
        unhealthy_count = len(reports) - healthy_count

        logger.info(
            f"[HealthMonitor] Check complete: "
            f"{healthy_count} healthy, {unhealthy_count} unhealthy "
            f"(of {len(reports)} total)."
        )
        return reports

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summarize(self, reports: List[HealthReport]) -> Dict[str, object]:
        """
        Produce a compact, JSON-serializable health summary from a
        list of HealthReports.

        Args:
            reports: Output of check_all().

        Returns:
            Dict with overall status, counts, and per-agent summaries.
        """
        if not reports:
            return {"status": "NO_AGENTS", "total": 0, "healthy": 0, "unhealthy": 0, "agents": []}

        healthy   = [r for r in reports if r.is_healthy]
        unhealthy = [r for r in reports if not r.is_healthy]
        status    = "HEALTHY" if not unhealthy else (
            "DEGRADED" if healthy else "CRITICAL"
        )

        return {
            "status":    status,
            "total":     len(reports),
            "healthy":   len(healthy),
            "unhealthy": len(unhealthy),
            "checked_at": datetime.utcnow().isoformat(),
            "agents": [
                {
                    "agent_type": r.agent_type.value,
                    "is_healthy": r.is_healthy,
                    "state":      r.state.value,
                    "issues":     r.issues,
                }
                for r in reports
            ],
        }

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_report(
        record: AgentRecord,
        issues: List[str],
        now: datetime,
        heartbeat_age: Optional[float] = None,
    ) -> HealthReport:
        """Construct a HealthReport from collected data."""
        is_healthy = len(issues) == 0
        return HealthReport(
            agent_type        = record.agent_type,
            is_healthy        = is_healthy,
            state             = record.state,
            active_tasks      = record.active_task_count,
            max_concurrent    = record.manifest.max_concurrent,
            last_heartbeat    = record.last_heartbeat,
            heartbeat_age_sec = heartbeat_age,
            issues            = issues,
            checked_at        = now,
        )
