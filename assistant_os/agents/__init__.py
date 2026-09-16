"""
assistant_os/agents/__init__.py
============================
NOVA OS - Agents Package

Architecture Position:
    This package defines the CONTRACT that every NOVA OS agent must fulfill.
    It sits between the Agent Manager (upstream) and concrete agent
    implementations (downstream).

    Agent Manager  →  [AgentTask]  →  BaseAgent.run()  →  [AgentResult]

    This package contains:
        BaseAgent        — Abstract base class all agents must inherit from.
        AgentClassRegistry — Maps AgentType → BaseAgent subclass (class-level).
        AgentTask        — Input model given to an agent to execute.
        AgentResult      — Output model returned by an agent after execution.
        AgentStatus      — Execution outcome enum.
        AgentOutputType  — Content type enum for structured agent output.

    This package does NOT contain:
        ✗ Any real agent implementations (those live in separate submodules)
        ✗ Any runtime lifecycle state (that is agent_manager.registry's job)
        ✗ Any tool implementations (that is tools.tool_manager's job)

Boundary Clarification (no duplication):
    agent_manager.registry.AgentRegistry:
        Maps AgentType → AgentRecord  (runtime lifecycle, health, task counts)
    agents.base_agent.AgentClassRegistry:
        Maps AgentType → BaseAgent subclass  (Python class for instantiation)

SDD Reference: Section 26 (Agent Design).
"""

from assistant_os.agents.models import (
    AgentOutputType,
    AgentStatus,
    AgentTask,
    AgentResult,
    ContextPackage,
)
from assistant_os.agents.base_agent import BaseAgent, AgentClassRegistry

__all__ = [
    # Core framework
    "BaseAgent",
    "AgentClassRegistry",
    # Data models
    "AgentTask",
    "AgentResult",
    "AgentStatus",
    "AgentOutputType",
    "ContextPackage",
]
