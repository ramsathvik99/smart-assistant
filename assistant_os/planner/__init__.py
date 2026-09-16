"""
assistant_os/planner/__init__.py
============================
NOVA OS - Planner Package

Architecture Note:
    This package is Phase 1 of the NOVA OS Brain pipeline.
    It receives a BrainOutput (a structured intent from the Brain)
    and returns a validated TaskPlan (a DAG of TaskNodes).

    This package does NOT:
        - Execute any tasks
        - Call any tools
        - Create any agents
        - Modify the Router

    Integration Point:
        Brain calls: plan = Planner().create_plan(brain_output)
        Brain then dispatches plan.tasks via the Agent Manager.

Public API:
    from assistant_os.planner import Planner, BrainOutput
    from assistant_os.planner.models import TaskPlan, TaskNode, AgentType, TaskStatus
"""

from assistant_os.planner.models import (
    TaskPlan,
    TaskNode,
    AgentType,
    TaskStatus,
    BrainOutput,
    PlannerConfig,
)
from assistant_os.planner.planner import Planner

__all__ = [
    "Planner",
    "BrainOutput",
    "TaskPlan",
    "TaskNode",
    "AgentType",
    "TaskStatus",
    "PlannerConfig",
]
