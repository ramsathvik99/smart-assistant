"""
assistant_os/agents/models.py
==========================
NOVA OS - Agent Framework: Execution Data Models

This file defines the data models that cross the boundary between the
Agent Manager and a running BaseAgent subclass:

    AgentTask    → What the Agent Manager sends INTO an agent.
    AgentResult  → What an agent sends BACK to the Agent Manager.
    AgentStatus  → Execution outcome (distinct from lifecycle state).
    AgentOutputType → Describes the content type of AgentResult.content.
    ContextPackage  → Memory-assembled context provided with each task.

Design Rules:
    1. AgentType is imported from assistant_os.planner.models — never redefined.
    2. AgentStatus is DISTINCT from:
       - TaskStatus (Planner's per-node status)
       - TaskScheduleState (Scheduler's lifecycle state)
       - AgentLifecycleState (Agent Manager's agent-process state)
       AgentStatus describes the RESULT of a single run() call.
    3. ContextPackage is a simplified forward-declaration.
       It will be populated by the Memory Manager in a future module.
       It is defined here so agents can depend on it without circular imports.

SDD Reference: Section 25 (Data Models), Section 26 (Agent Design).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from assistant_os.planner.models import AgentType, RiskLevel


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AgentStatus(str, Enum):
    """
    The execution outcome of a single agent.run() call.

    This is NOT the same as AgentLifecycleState (which tracks the
    process state of the registered agent) or TaskScheduleState
    (which tracks the scheduling lifecycle of a ScheduledTask).

    AgentStatus answers: "What happened when this specific run() was called?"

    SUCCESS : Agent completed the task and returned usable output.
    PARTIAL : Agent completed partially; output is included but incomplete.
    FAILED  : Agent failed entirely; no usable output produced.
    SKIPPED : Agent determined the task was not applicable and skipped it.
    TIMEOUT : Agent did not complete within the allowed time window.
    """
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED  = "FAILED"
    SKIPPED = "SKIPPED"
    TIMEOUT = "TIMEOUT"


class AgentOutputType(str, Enum):
    """
    Describes the semantic type of AgentResult.content.

    Used by the Response Generator to select the correct formatter/renderer.

    TEXT       : Plain prose text (most common).
    CODE       : A code block (language specified in metadata["language"]).
    TABLE      : Tabular data — content is a List[Dict] or CSV string.
    STRUCTURED : A JSON-serializable dict (structured report, API result).
    IMAGE_PATH : A filesystem path to a generated image.
    MARKDOWN   : Rich text with markdown formatting.
    NONE       : No content produced (e.g., SKIPPED or FAILED result).
    """
    TEXT       = "TEXT"
    CODE       = "CODE"
    TABLE      = "TABLE"
    STRUCTURED = "STRUCTURED"
    IMAGE_PATH = "IMAGE_PATH"
    MARKDOWN   = "MARKDOWN"
    NONE       = "NONE"


# ---------------------------------------------------------------------------
# Context Package (forward declaration — populated by Memory Manager later)
# ---------------------------------------------------------------------------

@dataclass
class ContextPackage:
    """
    Assembled context provided to an agent alongside its instruction.

    In the current implementation, this is a simple container.
    When the Memory Manager module is implemented, it will populate
    all fields before passing to agents.

    Attributes:
        session_history   : Last N conversation turns (role, content pairs).
        relevant_memories : Facts retrieved from episodic/semantic memory.
        user_preferences  : Key-value preference store for the user.
        active_plan_id    : UUID of the TaskPlan this task belongs to.
        custom            : Arbitrary extension data from other modules.
    """
    session_history:    List[Dict[str, str]] = field(default_factory=list)
    relevant_memories:  List[Dict[str, Any]] = field(default_factory=list)
    user_preferences:   Dict[str, str]       = field(default_factory=dict)
    active_plan_id:     Optional[str]        = None
    custom:             Dict[str, Any]       = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "ContextPackage":
        """Return an empty ContextPackage for agents that need no context."""
        return cls()


# ---------------------------------------------------------------------------
# AgentTask — Input to an agent's run() method
# ---------------------------------------------------------------------------

@dataclass
class AgentTask:
    """
    The complete input package delivered to a BaseAgent by the Agent Manager.

    AgentTask is the EXECUTION interface.  It is distinct from:
        TaskNode       — Planner's planning unit (no context, no permissions)
        ScheduledTask  — Scheduler's tracking unit (has state, not context)
        AgentTask      — THIS: the agent receives this to actually work with.

    Attributes:
        task_id        : UUID matching the originating TaskNode.task_id.
        plan_id        : UUID of the parent TaskPlan.
        agent_type     : Which AgentType should handle this task (for validation).
        instruction    : Natural language instruction for the agent.
        context        : Assembled context from the Memory Manager.
        tools_allowed  : Names of tools this agent is permitted to call.
                         Enforced by the Tool Manager and Security Layer.
        session_id     : UUID of the current user session.
        user_id        : Database user ID (for memory/preference scoping).
        risk_level     : Risk classification from the Planner.
        timeout_sec    : Max seconds the agent may run before TIMEOUT.
        metadata       : Arbitrary key-value pairs for extensibility.
    """
    task_id:       str                      = field(default_factory=lambda: str(uuid.uuid4()))
    plan_id:       str                      = ""
    agent_type:    AgentType                = AgentType.UNKNOWN
    instruction:   str                      = ""
    context:       ContextPackage           = field(default_factory=ContextPackage.empty)
    tools_allowed: List[str]               = field(default_factory=list)
    session_id:    str                      = field(default_factory=lambda: str(uuid.uuid4()))
    user_id:       Optional[int]            = None
    risk_level:    RiskLevel               = RiskLevel.LOW
    timeout_sec:   int                      = 60
    metadata:      Dict[str, Any]          = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dictionary (for logging)."""
        return {
            "task_id":      self.task_id,
            "plan_id":      self.plan_id,
            "agent_type":   self.agent_type.value,
            "instruction":  self.instruction[:120],   # Truncated for log safety
            "session_id":   self.session_id,
            "user_id":      self.user_id,
            "risk_level":   self.risk_level.value,
            "timeout_sec":  self.timeout_sec,
            "tools_allowed":self.tools_allowed,
        }


# ---------------------------------------------------------------------------
# AgentResult — Output from an agent's run() method
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """
    The output package returned by a BaseAgent after executing a task.

    Returned by BaseAgent.run() and consumed by the Agent Manager, which
    forwards it to the Brain, which forwards it to the Response Generator.

    Attributes:
        task_id      : UUID matching the AgentTask that produced this result.
        agent_type   : Which agent produced this result.
        status       : Execution outcome (SUCCESS, PARTIAL, FAILED, etc.).
        output_type  : Semantic content type (TEXT, CODE, TABLE, etc.).
        content      : The actual output. Type depends on output_type:
                           TEXT/CODE/MARKDOWN → str
                           TABLE              → List[Dict] or str (CSV)
                           STRUCTURED         → Dict[str, Any]
                           IMAGE_PATH         → str (absolute file path)
                           NONE               → None
        error        : Human-readable error message if status is FAILED.
        duration_ms  : Wall-clock execution time in milliseconds.
        token_usage  : Optional LLM token count for billing/monitoring.
        metadata     : Arbitrary extension data (e.g., sources, citations).
    """
    task_id:     str                   = field(default_factory=lambda: str(uuid.uuid4()))
    agent_type:  AgentType             = AgentType.UNKNOWN
    status:      AgentStatus           = AgentStatus.FAILED
    output_type: AgentOutputType       = AgentOutputType.NONE
    content:     Any                   = None
    error:       Optional[str]         = None
    duration_ms: int                   = 0
    token_usage: Optional[int]         = None
    metadata:    Dict[str, Any]        = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """True for SUCCESS or PARTIAL outcomes."""
        return self.status in (AgentStatus.SUCCESS, AgentStatus.PARTIAL)

    @property
    def is_failure(self) -> bool:
        """True for FAILED or TIMEOUT outcomes."""
        return self.status in (AgentStatus.FAILED, AgentStatus.TIMEOUT)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dictionary."""
        return {
            "task_id":     self.task_id,
            "agent_type":  self.agent_type.value,
            "status":      self.status.value,
            "output_type": self.output_type.value,
            "content":     self.content if isinstance(self.content, (str, int, float, list, dict, type(None))) else str(self.content),
            "error":       self.error,
            "duration_ms": self.duration_ms,
            "token_usage": self.token_usage,
        }
