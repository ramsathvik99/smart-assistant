"""
assistant_os/agent_manager/models.py
==================================
NOVA OS - Agent Manager Data Models

All dataclass definitions for the Agent Manager.  No business logic here.

Model Hierarchy:
    AgentManifest      — What an agent declares about itself (static)
    AgentRecord        — A registered agent at runtime (dynamic state)
    ScheduledTask      — A TaskNode that has entered the scheduling system
    HealthReport       — Result of a single health check on one agent
    AgentManagerConfig — Runtime tuning parameters for AgentManager

Relationship to Planner Models:
    ScheduledTask wraps a TaskNode:
        TaskNode (from assistant_os.planner.models)
            └── converted to → ScheduledTask (in this module)
    AgentType is imported FROM assistant_os.planner.models — NOT redefined here.
    This enforces a single source of truth for agent type enumeration.

SDD References:
    Section 13   (Agent Manager)
    Section 13.2 (Agent Lifecycle)
    Section 25   (Data Models)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

# Import AgentType from Planner — single source of truth.
from assistant_os.planner.models import AgentType, RiskLevel


# ---------------------------------------------------------------------------
# Agent Lifecycle Enumerations
# ---------------------------------------------------------------------------

class AgentLifecycleState(str, Enum):
    """
    Lifecycle state of a registered agent process/instance.

    Transitions (from SDD Section 13.2):

        REGISTERED → IDLE       (agent becomes available)
        IDLE       → BUSY       (task assigned)
        BUSY       → IDLE       (task completed)
        BUSY       → UNHEALTHY  (heartbeat timeout or crash)
        UNHEALTHY  → IDLE       (agent self-recovered)
        ANY        → DEREGISTERED (explicit removal)

    The Agent Manager transitions states; it does not execute agents.
    """
    REGISTERED   = "REGISTERED"   # Just added to registry, not yet verified
    IDLE         = "IDLE"         # Healthy and available for tasks
    BUSY         = "BUSY"         # Currently running ≥1 task
    UNHEALTHY    = "UNHEALTHY"    # Heartbeat missed or health check failed
    DEREGISTERED = "DEREGISTERED" # Permanently removed from registry


class TaskScheduleState(str, Enum):
    """
    Lifecycle state of a ScheduledTask within the scheduler.

    Transitions (from SDD Section 13.2):

        QUEUED → ASSIGNED → RUNNING → COMPLETED
                               ↓
                           FAILED → RETRYING → ABORTED
                               ↓
                           CANCELLED (user or system cancel)

    The Planner produces TaskNodes with status=PENDING.
    The Scheduler converts them to ScheduledTasks with state=QUEUED.
    Transitions past ASSIGNED are driven by agent heartbeat signals
    (future implementation).
    """
    QUEUED     = "QUEUED"      # Waiting for agent assignment
    ASSIGNED   = "ASSIGNED"    # Agent selected; task handed off
    RUNNING    = "RUNNING"     # Agent is actively processing
    COMPLETED  = "COMPLETED"   # Success
    FAILED     = "FAILED"      # Error; may retry
    RETRYING   = "RETRYING"    # Scheduled for re-attempt
    ABORTED    = "ABORTED"     # Max retries exceeded or cancelled
    CANCELLED  = "CANCELLED"   # Explicitly cancelled by Brain/user


# ---------------------------------------------------------------------------
# Agent Manifest (static declaration by agent author)
# ---------------------------------------------------------------------------

@dataclass
class AgentManifest:
    """
    Static self-description declared by an agent at registration time.

    An agent class should expose a class-level MANIFEST attribute of
    this type.  The AgentRegistry reads this without instantiating
    the agent.

    Attributes:
        agent_type      : The AgentType this manifest represents.
        display_name    : Human-readable name (e.g. "Coding Agent").
        description     : One-line purpose description.
        capabilities    : List of named capabilities (e.g. ["run_python"]).
        intent_patterns : Keyword phrases that route to this agent.
        max_concurrent  : Max parallel task slots for this agent type.
        requires_llm    : Whether this agent needs an LLM connection.
        requires_network: Whether this agent needs outbound internet.
        version         : Semantic version string.
        module_path     : Dotted Python module path (for auto-discovery).
        class_name      : Class name within the module (for auto-discovery).
    """
    agent_type:       AgentType
    display_name:     str
    description:      str
    capabilities:     List[str]      = field(default_factory=list)
    intent_patterns:  List[str]      = field(default_factory=list)
    max_concurrent:   int            = 1
    requires_llm:     bool           = True
    requires_network: bool           = False
    version:          str            = "1.0.0"
    module_path:      str            = ""
    class_name:       str            = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_type":       self.agent_type.value,
            "display_name":     self.display_name,
            "description":      self.description,
            "capabilities":     self.capabilities,
            "intent_patterns":  self.intent_patterns,
            "max_concurrent":   self.max_concurrent,
            "requires_llm":     self.requires_llm,
            "requires_network": self.requires_network,
            "version":          self.version,
            "module_path":      self.module_path,
            "class_name":       self.class_name,
        }


# ---------------------------------------------------------------------------
# Agent Record (runtime state of a registered agent)
# ---------------------------------------------------------------------------

@dataclass
class AgentRecord:
    """
    Runtime entry in the AgentRegistry for one agent type.

    Combines the static AgentManifest with dynamic runtime state.

    Attributes:
        manifest             : Static agent declaration.
        state                : Current lifecycle state.
        registered_at        : UTC timestamp of registration.
        last_heartbeat       : UTC timestamp of last heartbeat signal.
        active_task_count    : Number of tasks currently assigned.
        total_tasks_completed: Cumulative completed tasks (lifetime).
        total_tasks_failed   : Cumulative failed tasks (lifetime).
        metadata             : Arbitrary extension data.
    """
    manifest:              AgentManifest
    state:                 AgentLifecycleState = AgentLifecycleState.REGISTERED
    registered_at:         datetime             = field(default_factory=datetime.utcnow)
    last_heartbeat:        Optional[datetime]   = None
    active_task_count:     int                  = 0
    total_tasks_completed: int                  = 0
    total_tasks_failed:    int                  = 0
    metadata:              Dict[str, Any]       = field(default_factory=dict)

    @property
    def agent_type(self) -> AgentType:
        """Convenience accessor for the agent type."""
        return self.manifest.agent_type

    @property
    def is_available(self) -> bool:
        """
        True if the agent can accept a new task right now.

        Conditions:
            - State is IDLE (healthy and not at capacity)
            - active_task_count < max_concurrent
        """
        return (
            self.state == AgentLifecycleState.IDLE
            and self.active_task_count < self.manifest.max_concurrent
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_type":            self.agent_type.value,
            "state":                 self.state.value,
            "registered_at":         self.registered_at.isoformat(),
            "last_heartbeat":        self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "active_task_count":     self.active_task_count,
            "total_tasks_completed": self.total_tasks_completed,
            "total_tasks_failed":    self.total_tasks_failed,
            "manifest":              self.manifest.to_dict(),
        }


# ---------------------------------------------------------------------------
# Scheduled Task (TaskNode promoted into the scheduler)
# ---------------------------------------------------------------------------

@dataclass
class ScheduledTask:
    """
    A TaskNode that has entered the Agent Manager's scheduling system.

    Created by AgentScheduler.schedule(task_node).

    Attributes:
        task_id           : From TaskNode.task_id (UUID).
        plan_id           : From TaskNode.plan_id (UUID).
        agent_type        : Target agent type from TaskNode.
        instruction       : Natural language instruction from TaskNode.
        risk_level        : Risk classification from TaskNode.
        requires_approval : Whether user approval is pending.
        state             : Current scheduling lifecycle state.
        assigned_agent_key: agent_type.value of the assigned agent.
        scheduled_at      : UTC timestamp when task entered the queue.
        assigned_at       : UTC timestamp when task was assigned to agent.
        started_at        : UTC timestamp when agent began processing.
        completed_at      : UTC timestamp when task finished (success/fail).
        retry_count       : Number of retries attempted so far.
        max_retries       : Maximum allowed retries before ABORTED.
        priority          : Scheduling priority (higher = more urgent).
        error_message     : Last error message if state is FAILED/ABORTED.
        metadata          : Arbitrary extension data.
    """
    task_id:            str
    plan_id:            str
    agent_type:         AgentType
    instruction:        str
    risk_level:         RiskLevel              = RiskLevel.LOW
    requires_approval:  bool                   = False
    state:              TaskScheduleState      = TaskScheduleState.QUEUED
    assigned_agent_key: Optional[str]          = None
    scheduled_at:       datetime               = field(default_factory=datetime.utcnow)
    assigned_at:        Optional[datetime]     = None
    started_at:         Optional[datetime]     = None
    completed_at:       Optional[datetime]     = None
    retry_count:        int                    = 0
    max_retries:        int                    = 2
    priority:           int                    = 0
    error_message:      Optional[str]          = None
    metadata:           Dict[str, Any]         = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        """True when the task has reached a final state (no further transitions)."""
        return self.state in (
            TaskScheduleState.COMPLETED,
            TaskScheduleState.ABORTED,
            TaskScheduleState.CANCELLED,
        )

    @property
    def can_retry(self) -> bool:
        """True if the task is eligible for retry."""
        return self.retry_count < self.max_retries

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id":            self.task_id,
            "plan_id":            self.plan_id,
            "agent_type":         self.agent_type.value,
            "instruction":        self.instruction,
            "risk_level":         self.risk_level.value,
            "requires_approval":  self.requires_approval,
            "state":              self.state.value,
            "assigned_agent_key": self.assigned_agent_key,
            "scheduled_at":       self.scheduled_at.isoformat(),
            "assigned_at":        self.assigned_at.isoformat() if self.assigned_at else None,
            "started_at":         self.started_at.isoformat() if self.started_at else None,
            "completed_at":       self.completed_at.isoformat() if self.completed_at else None,
            "retry_count":        self.retry_count,
            "max_retries":        self.max_retries,
            "priority":           self.priority,
            "error_message":      self.error_message,
        }


# ---------------------------------------------------------------------------
# Health Report (result of one health check cycle)
# ---------------------------------------------------------------------------

@dataclass
class HealthReport:
    """
    Snapshot of an agent's health at a point in time.

    Produced by HealthMonitor.check(agent_record).

    Attributes:
        agent_type       : Which agent was checked.
        is_healthy       : Overall pass/fail verdict.
        state            : Agent's current lifecycle state at check time.
        active_tasks     : Number of active tasks at check time.
        max_concurrent   : Maximum slots declared in manifest.
        last_heartbeat   : Most recent heartbeat timestamp.
        heartbeat_age_sec: Seconds since last heartbeat (None if never seen).
        issues           : Human-readable list of detected problems.
        checked_at       : UTC timestamp of this check.
    """
    agent_type:        AgentType
    is_healthy:        bool
    state:             AgentLifecycleState
    active_tasks:      int
    max_concurrent:    int
    last_heartbeat:    Optional[datetime]
    heartbeat_age_sec: Optional[float]
    issues:            List[str]            = field(default_factory=list)
    checked_at:        datetime             = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_type":        self.agent_type.value,
            "is_healthy":        self.is_healthy,
            "state":             self.state.value,
            "active_tasks":      self.active_tasks,
            "max_concurrent":    self.max_concurrent,
            "last_heartbeat":    self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "heartbeat_age_sec": self.heartbeat_age_sec,
            "issues":            self.issues,
            "checked_at":        self.checked_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class AgentManagerConfig:
    """
    Runtime configuration for the AgentManager.

    Attributes:
        heartbeat_timeout_sec : Seconds after last heartbeat before an
                                agent is considered UNHEALTHY.
        max_queue_depth       : Max ScheduledTasks allowed in QUEUED state
                                before new submissions are rejected.
        auto_idle_on_register : If True, agents transition REGISTERED→IDLE
                                immediately on registration (no explicit
                                ready() call required). Useful for built-in
                                agents known to be always available.
        agents_discovery_dir  : Filesystem path to scan for agent modules.
        default_max_retries   : Default retry limit applied to ScheduledTasks
                                when not explicitly set by the caller.
    """
    heartbeat_timeout_sec:  int   = 30
    max_queue_depth:        int   = 200
    auto_idle_on_register:  bool  = True
    agents_discovery_dir:   str   = ""   # Set to assistant_os/agents/ path at runtime
    default_max_retries:    int   = 2
