"""
assistant_os/planner/models.py
==========================
NOVA OS - Planner Data Models

All data models for the Planner module are defined here using
Python dataclasses. No business logic lives in this file.

Architecture Context:
    BrainOutput  →  [Planner]  →  TaskPlan
                                      │
                                      └── List[TaskNode]  (DAG)

Design Decisions:
    - UUIDs are used for all identifiers so task IDs are globally unique
      across sessions, restarts, and concurrent plan executions.
    - 'dependencies' uses string UUIDs (not object references) so
      TaskNodes are fully serializable without circular references.
    - 'can_run_parallel' is a computed field, resolved by the
      DependencyResolver — not set by the caller.
    - 'requires_approval' is set by the Planner for any task tagged
      as HIGH_RISK or IRREVERSIBLE by the risk heuristic engine.

SDD Reference: Section 12 (Planner Module), Section 25 (Data Models).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AgentType(str, Enum):
    """
    Identifies which NOVA OS agent should handle a TaskNode.

    All values mirror the agent roster defined in SDD Section 26.
    Using (str, Enum) so values are JSON-serializable by default.
    """
    CONVERSATION  = "CONVERSATION"
    CODING        = "CODING"
    RESEARCH      = "RESEARCH"
    BROWSER       = "BROWSER"
    RESUME        = "RESUME"
    STUDY         = "STUDY"
    AUTOMATION    = "AUTOMATION"
    MEMORY        = "MEMORY"
    PLANNER       = "PLANNER"
    UNKNOWN       = "UNKNOWN"


class TaskStatus(str, Enum):
    """
    Lifecycle states of a TaskNode.

    The Planner only ever produces PENDING nodes.
    Status transitions (RUNNING, DONE, FAILED) are managed by the
    Agent Manager — never by this Planner module.
    """
    PENDING   = "PENDING"
    RUNNING   = "RUNNING"
    DONE      = "DONE"
    FAILED    = "FAILED"
    SKIPPED   = "SKIPPED"   # Set when a dependency fails and skip_on_fail=True
    CANCELLED = "CANCELLED"


class RiskLevel(str, Enum):
    """
    Estimated risk of irreversibility for a task.

    Used by the Planner to set requires_approval on TaskNodes.
    HIGH and CRITICAL tasks pause execution pending user confirmation.
    """
    LOW      = "LOW"      # Read-only operations, chat, search
    MEDIUM   = "MEDIUM"   # File reads, web fetches
    HIGH     = "HIGH"     # File writes, email sending, code execution
    CRITICAL = "CRITICAL" # System shutdown, mass deletion, data wipe


# ---------------------------------------------------------------------------
# Input Models
# ---------------------------------------------------------------------------

@dataclass
class BrainOutput:
    """
    The Planner's sole input, produced by the NOVA OS Brain module.

    The Brain passes this object after it has:
        1. Received a normalized InputEvent from the Input Gateway.
        2. Decided the request requires multi-step planning.

    Attributes:
        goal        : The high-level user goal as plain English.
        raw_input   : Original user utterance before any processing.
        session_id  : UUID of the current user session.
        user_id     : Database user ID.
        context     : Key-value context bag from Memory Manager.
        modality    : Input modality ('voice', 'text', 'image', etc.)
        attachments : List of file paths attached to the request.
        metadata    : Arbitrary extra data for extensibility.
    """
    goal:        str
    raw_input:   str
    session_id:  str                         = field(default_factory=lambda: str(uuid.uuid4()))
    user_id:     Optional[int]               = None
    context:     Dict[str, Any]             = field(default_factory=dict)
    modality:    str                         = "text"
    attachments: List[str]                  = field(default_factory=list)
    metadata:    Dict[str, Any]             = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core Planning Models
# ---------------------------------------------------------------------------

@dataclass
class TaskNode:
    """
    A single atomic unit of work within a TaskPlan.

    Each TaskNode represents exactly one thing an agent must do.
    It carries enough information for the Agent Manager to:
        - Identify the correct agent (agent_type)
        - Provide the agent its instruction (instruction)
        - Resolve execution order (dependencies, can_run_parallel)
        - Enforce approval gates (requires_approval, risk_level)

    Attributes:
        task_id          : Globally unique identifier for this task.
        plan_id          : Parent TaskPlan's UUID.
        agent_type       : Which agent handles this task.
        instruction      : Natural language instruction for the agent.
        dependencies     : List of task_ids that must complete before this.
        can_run_parallel : True if no uncompleted dependencies exist.
        requires_approval: If True, the Brain must pause and ask the user.
        risk_level       : Estimated irreversibility of this task.
        status           : Lifecycle state (always PENDING from Planner).
        position         : Topological sort order (0-indexed).
        rationale        : Why the Planner assigned this agent/order.
        metadata         : Arbitrary extension data.
    """
    task_id:           str            = field(default_factory=lambda: str(uuid.uuid4()))
    plan_id:           str            = ""
    agent_type:        AgentType      = AgentType.UNKNOWN
    instruction:       str            = ""
    dependencies:      List[str]      = field(default_factory=list)   # List of task_id strings
    can_run_parallel:  bool           = False
    requires_approval: bool           = False
    risk_level:        RiskLevel      = RiskLevel.LOW
    status:            TaskStatus     = TaskStatus.PENDING
    position:          int            = 0
    rationale:         str            = ""
    metadata:          Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskPlan:
    """
    A directed acyclic graph (DAG) of TaskNodes produced by the Planner.

    The plan captures everything the Agent Manager needs to orchestrate
    the full execution of a complex user goal.

    Attributes:
        plan_id       : Globally unique plan identifier.
        session_id    : Session this plan belongs to.
        goal          : The original high-level user goal.
        tasks         : Ordered list of TaskNodes (topologically sorted).
        execution_groups: Tasks grouped by parallel execution wave.
                          Group 0 runs first, group 1 after group 0 finishes,
                          etc. Tasks within the same group run in parallel.
        total_tasks   : Convenience count of tasks.
        has_approvals : True if any task requires user approval.
        metadata      : Arbitrary extension data.
    """
    plan_id:           str                   = field(default_factory=lambda: str(uuid.uuid4()))
    session_id:        str                   = ""
    goal:              str                   = ""
    tasks:             List[TaskNode]        = field(default_factory=list)
    execution_groups:  List[List[str]]       = field(default_factory=list)  # List of lists of task_ids
    total_tasks:       int                   = 0
    has_approvals:     bool                  = False
    metadata:          Dict[str, Any]        = field(default_factory=dict)

    def __post_init__(self):
        """Sync computed fields after dataclass init."""
        self.total_tasks  = len(self.tasks)
        self.has_approvals = any(t.requires_approval for t in self.tasks)

    def get_task(self, task_id: str) -> Optional[TaskNode]:
        """Return a TaskNode by its task_id, or None if not found."""
        return next((t for t in self.tasks if t.task_id == task_id), None)

    def get_ready_tasks(self) -> List[TaskNode]:
        """
        Return all PENDING tasks whose dependencies are all DONE.
        Useful for the Agent Manager to know what can run now.
        """
        done_ids = {t.task_id for t in self.tasks if t.status == TaskStatus.DONE}
        return [
            t for t in self.tasks
            if t.status == TaskStatus.PENDING
            and all(dep in done_ids for dep in t.dependencies)
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the full plan to a JSON-safe dictionary."""
        return {
            "plan_id":          self.plan_id,
            "session_id":       self.session_id,
            "goal":             self.goal,
            "total_tasks":      self.total_tasks,
            "has_approvals":    self.has_approvals,
            "execution_groups": self.execution_groups,
            "tasks": [
                {
                    "task_id":           t.task_id,
                    "plan_id":           t.plan_id,
                    "agent_type":        t.agent_type.value,
                    "instruction":       t.instruction,
                    "dependencies":      t.dependencies,
                    "can_run_parallel":  t.can_run_parallel,
                    "requires_approval": t.requires_approval,
                    "risk_level":        t.risk_level.value,
                    "status":            t.status.value,
                    "position":          t.position,
                    "rationale":         t.rationale,
                }
                for t in self.tasks
            ],
        }


# ---------------------------------------------------------------------------
# Configuration Model
# ---------------------------------------------------------------------------

@dataclass
class PlannerConfig:
    """
    Runtime configuration for the Planner.

    Attributes:
        max_tasks         : Hard limit on tasks per plan (safety guard).
        use_llm           : Use LLMEngine for intelligent decomposition.
                            When False, rule-based fallback is used only.
        llm_timeout_sec   : Seconds to wait for LLM before fallback.
        min_confidence    : Minimum GoalInterpreter confidence to trust
                            a rule-based plan without LLM verification.
        auto_approve_low  : Automatically approve LOW-risk tasks
                            without surfacing to the user.
    """
    max_tasks:        int   = 20
    use_llm:          bool  = True
    llm_timeout_sec:  int   = 10
    min_confidence:   float = 0.75
    auto_approve_low: bool  = True
