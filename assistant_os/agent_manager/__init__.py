"""
assistant_os/agent_manager/__init__.py
===================================
NOVA OS - Agent Manager Package

Architecture Position:
    The Agent Manager sits between the Planner (upstream) and the
    actual Agent implementations (downstream, not yet built).

    Planner → [TaskPlan] → AgentManager → [ScheduledTask] → Agent (future)

    This package owns three responsibilities:

        Registry      : Knowing WHICH agents exist and their capabilities.
        Scheduler     : Knowing WHAT work is queued and in what state.
        HealthMonitor : Knowing WHETHER agents are alive and available.

    The Agent Manager does NOT:
        ✗ Execute any agent logic
        ✗ Call any external tools or APIs
        ✗ Modify the Brain or Planner
        ✗ Access Memory or Database directly

Public API:
    from assistant_os.agent_manager import AgentManager
    from assistant_os.agent_manager.models import (
        AgentManifest, AgentRecord, ScheduledTask,
        AgentLifecycleState, TaskScheduleState, HealthReport
    )

SDD Reference: Section 13 (Agent Manager).
"""

from assistant_os.agent_manager.models import (
    AgentLifecycleState,
    AgentManifest,
    AgentRecord,
    AgentManagerConfig,
    HealthReport,
    ScheduledTask,
    TaskScheduleState,
)
from assistant_os.agent_manager.registry import AgentRegistry
from assistant_os.agent_manager.scheduler import AgentScheduler
from assistant_os.agent_manager.health_monitor import HealthMonitor
from assistant_os.agent_manager.agent_manager import AgentManager

__all__ = [
    # Top-level façade
    "AgentManager",
    # Sub-components (accessible for testing / advanced use)
    "AgentRegistry",
    "AgentScheduler",
    "HealthMonitor",
    # Models
    "AgentManifest",
    "AgentRecord",
    "AgentManagerConfig",
    "AgentLifecycleState",
    "ScheduledTask",
    "TaskScheduleState",
    "HealthReport",
]
