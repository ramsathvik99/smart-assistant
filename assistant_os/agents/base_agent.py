"""
assistant_os/agents/base_agent.py
===============================
NOVA OS - Agent Framework: BaseAgent + AgentClassRegistry

Architecture:
    This module defines the CONTRACT and CLASS-LEVEL REGISTRY for all
    NOVA OS agents.

    ┌──────────────────────────────────────────────────────────────────┐
    │                     Agent Execution Pipeline                     │
    │                                                                  │
    │  AgentTask ──► BaseAgent.run() ──► AgentResult                  │
    │                      │                                           │
    │              ┌───────┴───────┐                                   │
    │              │               │                                   │
    │         _pre_run()    _post_run()                                │
    │              │               │                                   │
    │         execute()  ◄─────────┘    ← SUBCLASS implements this    │
    └──────────────────────────────────────────────────────────────────┘

    BaseAgent responsibilities:
        ✓ Enforce the AgentTask → AgentResult contract.
        ✓ Wrap execute() with timing, logging, and error handling.
        ✓ Validate that the incoming task matches the agent's type.
        ✓ Provide helpers for building success/partial/failure results.
        ✓ Auto-register subclasses in AgentClassRegistry on class definition.

    BaseAgent does NOT:
        ✗ Call any tools directly (agents use self.tools which is an injected dict)
        ✗ Access Memory, Brain, or Agent Manager
        ✗ Block on I/O in __init__

    AgentClassRegistry (this module):
        Maps AgentType → BaseAgent SUBCLASS (Python class object).
        Purpose: Allows the AgentManager to instantiate the correct class
                 given an AgentType, without scanning the filesystem.

    Distinct from agent_manager.registry.AgentRegistry:
        agent_manager.AgentRegistry:   AgentType → AgentRecord (runtime state)
        agents.AgentClassRegistry:     AgentType → BaseAgent CLASS (for new())

    Subclassing Contract:
        Every concrete agent MUST:
            1. Set class attribute AGENT_MANIFEST: ClassVar[AgentManifest]
            2. Implement: def execute(self, task: AgentTask) → AgentResult
            3. NOT override run() — only override execute()

SDD Reference: Section 26 (Agent Design), Section 10 (Core Components).
"""

from __future__ import annotations

import abc
import logging
import time
import threading
from typing import Any, Callable, ClassVar, Dict, Optional, Type

from assistant_os.agent_manager.models import AgentManifest
from assistant_os.agents.models import (
    AgentOutputType,
    AgentResult,
    AgentStatus,
    AgentTask,
)
from assistant_os.planner.models import AgentType


# ---------------------------------------------------------------------------
# AgentClassRegistry
# ---------------------------------------------------------------------------

class AgentClassRegistry:
    """
    Maps AgentType → BaseAgent subclass.

    This is a CLASS-LEVEL registry — it maps Python class objects, not
    runtime instances.  The AgentManager uses it to instantiate the
    correct agent class when it needs to run a task.

    Boundary (no duplication with agent_manager.AgentRegistry):
        AgentClassRegistry  →  AgentType → Python CLASS
        agent_manager.AgentRegistry → AgentType → AgentRecord (state/lifecycle)

    Auto-registration:
        Every subclass of BaseAgent is automatically registered when its
        class body is evaluated (via BaseAgent.__init_subclass__).
        You do NOT need to call register() manually.

    Manual registration is available for dynamic/plugin agents.

    Usage:
        # Get the class for a given AgentType:
        cls = AgentClassRegistry.get(AgentType.CODING)
        agent_instance = cls()

        # Check what's registered:
        AgentClassRegistry.list_all()

        # Manually register (e.g., for plugin agents):
        AgentClassRegistry.register(AgentType.CODING, CodingAgent)
    """

    _registry: Dict[str, Type["BaseAgent"]] = {}
    _lock = threading.Lock()

    @classmethod
    def register(cls, agent_type: AgentType, agent_class: Type["BaseAgent"]) -> None:
        """
        Register a BaseAgent subclass under an AgentType.

        Called automatically by BaseAgent.__init_subclass__.
        May also be called manually for plugin/dynamic agents.

        Args:
            agent_type:  The AgentType this class handles.
            agent_class: The BaseAgent subclass to register.
        """
        key = agent_type.value
        with cls._lock:
            if key in cls._registry:
                existing = cls._registry[key]
                if existing is not agent_class:
                    logging.getLogger("assistant_os.agents.registry").warning(
                        f"[AgentClassRegistry] Overwriting {key}: "
                        f"{existing.__name__} → {agent_class.__name__}"
                    )
            cls._registry[key] = agent_class

        logging.getLogger("assistant_os.agents.registry").info(
            f"[AgentClassRegistry] Registered: {agent_class.__name__} → {key}"
        )

    @classmethod
    def get(cls, agent_type: AgentType) -> Optional[Type["BaseAgent"]]:
        """
        Return the BaseAgent subclass registered for an AgentType.

        Args:
            agent_type: The agent type to look up.

        Returns:
            The BaseAgent subclass, or None if not registered.
        """
        return cls._registry.get(agent_type.value)

    @classmethod
    def instantiate(cls, agent_type: AgentType, **kwargs: Any) -> Optional["BaseAgent"]:
        """
        Create a new instance of the registered agent class.

        Args:
            agent_type: The agent type to instantiate.
            **kwargs:   Passed to the agent class constructor.

        Returns:
            A new BaseAgent instance, or None if type not registered.
        """
        agent_class = cls.get(agent_type)
        if agent_class is None:
            logging.getLogger("assistant_os.agents.registry").warning(
                f"[AgentClassRegistry] No class registered for: {agent_type.value}"
            )
            return None
        return agent_class(**kwargs)

    @classmethod
    def list_all(cls) -> Dict[str, str]:
        """
        Return a mapping of all registered AgentType values → class names.

        Returns:
            Dict[agent_type_value, class_name]
        """
        with cls._lock:
            return {k: v.__name__ for k, v in cls._registry.items()}

    @classmethod
    def is_registered(cls, agent_type: AgentType) -> bool:
        """Return True if an agent class is registered for the given type."""
        return agent_type.value in cls._registry

    @classmethod
    def deregister(cls, agent_type: AgentType) -> bool:
        """
        Remove an agent class from the registry.

        Useful for testing (reset between tests) and hot-reload scenarios.

        Args:
            agent_type: The type to deregister.

        Returns:
            True if found and removed, False if not present.
        """
        key = agent_type.value
        with cls._lock:
            if key in cls._registry:
                del cls._registry[key]
                return True
        return False

    @classmethod
    def clear(cls) -> None:
        """Remove ALL registered agents. Use only in tests."""
        with cls._lock:
            cls._registry.clear()


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------

class BaseAgent(abc.ABC):
    """
    Abstract base class that every NOVA OS agent must inherit from.

    ┌──────────────────────────────────────────────────────┐
    │  Subclassing Contract:                               │
    │                                                      │
    │  class MyAgent(BaseAgent):                           │
    │      AGENT_MANIFEST = AgentManifest(                 │
    │          agent_type    = AgentType.CODING,           │
    │          display_name  = "Coding Agent",             │
    │          description   = "Generates code.",          │
    │          capabilities  = ["run_python", "lint"],     │
    │          intent_patterns = ["write code", "debug"],  │
    │      )                                               │
    │                                                      │
    │      def execute(self, task: AgentTask) → AgentResult:│
    │          # Your implementation here.                 │
    │          return self._success(task, "Hello!")        │
    └──────────────────────────────────────────────────────┘

    Auto-Registration:
        When Python evaluates the class body of any BaseAgent subclass,
        __init_subclass__ fires and automatically registers the class
        in AgentClassRegistry — IF the class has AGENT_MANIFEST defined.

    Template Method Pattern:
        run()     → Public. Called by Agent Manager. DO NOT OVERRIDE.
        execute() → Abstract. Called by run(). MUST OVERRIDE.
        _pre_run()  → Hook called before execute(). Override to add setup.
        _post_run() → Hook called after execute(). Override to add cleanup.

    Attributes:
        AGENT_MANIFEST: ClassVar[AgentManifest]
            Every concrete subclass MUST define this as a class attribute.
        tools:
            Dict of callable tools injected by the Tool Manager at runtime.
            Access as: self.tools["tool_name"](args)
        logger:
            Pre-configured logger named "assistant_os.agents.<agent_type>".
    """

    # ── Class-level attributes — must be set by every subclass ───────────
    AGENT_MANIFEST: ClassVar[AgentManifest]

    # ── __init_subclass__: auto-register concrete subclasses ─────────────

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """
        Auto-register every concrete (non-abstract) BaseAgent subclass
        in AgentClassRegistry as soon as its class body is evaluated.

        Skips:
            - Abstract classes (those with unimplemented abstract methods).
            - Classes that do not define AGENT_MANIFEST.
        """
        super().__init_subclass__(**kwargs)

        # Skip if the class is still abstract (will be subclassed further)
        if abc.ABC in cls.__bases__:
            return

        manifest = getattr(cls, "AGENT_MANIFEST", None)
        if manifest is None:
            return  # No manifest — skip auto-registration

        if not isinstance(manifest, AgentManifest):
            logging.getLogger("assistant_os.agents").warning(
                f"[BaseAgent] {cls.__name__}.AGENT_MANIFEST is not an "
                f"AgentManifest instance — skipping auto-registration."
            )
            return

        AgentClassRegistry.register(manifest.agent_type, cls)

    # ── Constructor ───────────────────────────────────────────────────────

    def __init__(self, tools: Optional[Dict[str, Callable]] = None):
        """
        Initialise the base agent.

        Args:
            tools: Dict of tool callables injected by the Tool Manager.
                   Keys are tool names (str).  Values are callable functions.
                   If None, an empty dict is used (agent has no tools).
        """
        manifest = getattr(self.__class__, "AGENT_MANIFEST", None)
        if manifest is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must define AGENT_MANIFEST "
                f"as a class attribute."
            )

        self.manifest: AgentManifest             = manifest
        self.tools:    Dict[str, Callable]       = tools or {}
        self.logger:   logging.Logger            = logging.getLogger(
            f"assistant_os.agents.{manifest.agent_type.value.lower()}"
        )

    # ── Public entry point (DO NOT OVERRIDE) ─────────────────────────────

    def run(self, task: AgentTask) -> AgentResult:
        """
        Execute a task and return a result.

        This is the ONLY method the Agent Manager calls.
        DO NOT override this method in subclasses.

        Pipeline:
            1. Validate the task matches this agent's type.
            2. Call _pre_run() hook.
            3. Time and call execute(task).
            4. Call _post_run() hook.
            5. Handle any uncaught exceptions from execute().
            6. Return the AgentResult.

        Args:
            task: AgentTask from the Agent Manager.

        Returns:
            AgentResult — always returned, never raises.
        """
        self.logger.info(
            f"[{self.manifest.display_name}] Starting task={task.task_id[:8]} "
            f"| instruction={task.instruction[:80]!r}"
        )

        # Step 1: Validate
        validation_error = self._validate_task(task)
        if validation_error:
            self.logger.error(
                f"[{self.manifest.display_name}] Validation failed: "
                f"{validation_error}"
            )
            return self._failure(task, f"Validation failed: {validation_error}")

        # Step 2: Pre-run hook
        try:
            self._pre_run(task)
        except Exception as exc:
            self.logger.warning(
                f"[{self.manifest.display_name}] _pre_run raised: {exc}"
            )

        # Step 3: Execute with timing
        start_ms = time.monotonic()
        result: Optional[AgentResult] = None

        try:
            result = self.execute(task)
        except NotImplementedError:
            result = self._failure(task, "execute() is not implemented.")
        except Exception as exc:
            self.logger.exception(
                f"[{self.manifest.display_name}] Unhandled exception in execute(): {exc}"
            )
            result = self._failure(task, f"Unhandled exception: {exc}")

        # Ensure result is always an AgentResult
        if not isinstance(result, AgentResult):
            self.logger.error(
                f"[{self.manifest.display_name}] execute() returned "
                f"{type(result).__name__} instead of AgentResult."
            )
            result = self._failure(
                task,
                f"execute() returned {type(result).__name__} instead of AgentResult.",
            )

        # Stamp timing and task linkage
        result.duration_ms = int((time.monotonic() - start_ms) * 1000)
        result.task_id     = task.task_id
        result.agent_type  = self.manifest.agent_type

        # Step 4: Post-run hook
        try:
            self._post_run(task, result)
        except Exception as exc:
            self.logger.warning(
                f"[{self.manifest.display_name}] _post_run raised: {exc}"
            )

        self.logger.info(
            f"[{self.manifest.display_name}] Finished task={task.task_id[:8]} "
            f"| status={result.status.value} | duration={result.duration_ms}ms"
        )
        return result

    # ── Abstract method — MUST implement in every subclass ───────────────

    @abc.abstractmethod
    def execute(self, task: AgentTask) -> AgentResult:
        """
        Implement agent logic here.

        This method is called by run() after validation and timing setup.
        All exceptions raised here are caught by run() and converted to
        FAILED AgentResults.

        Args:
            task: The AgentTask to execute.

        Returns:
            AgentResult with status, output_type, and content populated.
        """

    # ── Lifecycle hooks — override optionally ────────────────────────────

    def _pre_run(self, task: AgentTask) -> None:
        """
        Called before execute().  Override for agent-specific setup.

        Examples: validate tool availability, warm up models, open files.
        """

    def _post_run(self, task: AgentTask, result: AgentResult) -> None:
        """
        Called after execute() completes (even on failure).
        Override for agent-specific cleanup.

        Examples: close file handles, flush caches, emit metrics.
        """

    # ── Protected result-building helpers ────────────────────────────────

    def _success(
        self,
        task: AgentTask,
        content: Any,
        output_type: AgentOutputType = AgentOutputType.TEXT,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """
        Build a SUCCESS AgentResult.

        Args:
            task:        The originating task.
            content:     The output content.
            output_type: The content type (default TEXT).
            metadata:    Optional extra data.

        Returns:
            AgentResult(status=SUCCESS, ...)
        """
        return AgentResult(
            task_id     = task.task_id,
            agent_type  = self.manifest.agent_type,
            status      = AgentStatus.SUCCESS,
            output_type = output_type,
            content     = content,
            metadata    = metadata or {},
        )

    def _partial(
        self,
        task: AgentTask,
        content: Any,
        output_type: AgentOutputType = AgentOutputType.TEXT,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """
        Build a PARTIAL AgentResult (output exists but is incomplete).

        Args:
            task:        The originating task.
            content:     The partial output content.
            output_type: The content type.
            reason:      Why the result is partial.
            metadata:    Optional extra data.

        Returns:
            AgentResult(status=PARTIAL, ...)
        """
        return AgentResult(
            task_id     = task.task_id,
            agent_type  = self.manifest.agent_type,
            status      = AgentStatus.PARTIAL,
            output_type = output_type,
            content     = content,
            error       = reason or "Partial result returned.",
            metadata    = metadata or {},
        )

    def _failure(
        self,
        task: AgentTask,
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """
        Build a FAILED AgentResult.

        Args:
            task:     The originating task.
            error:    Human-readable error description.
            metadata: Optional extra data.

        Returns:
            AgentResult(status=FAILED, output_type=NONE, content=None)
        """
        return AgentResult(
            task_id     = task.task_id,
            agent_type  = self.manifest.agent_type,
            status      = AgentStatus.FAILED,
            output_type = AgentOutputType.NONE,
            content     = None,
            error       = error,
            metadata    = metadata or {},
        )

    def _skipped(
        self,
        task: AgentTask,
        reason: str = "",
    ) -> AgentResult:
        """
        Build a SKIPPED AgentResult (task not applicable for this agent).

        Args:
            task:   The originating task.
            reason: Why the task was skipped.

        Returns:
            AgentResult(status=SKIPPED, ...)
        """
        return AgentResult(
            task_id     = task.task_id,
            agent_type  = self.manifest.agent_type,
            status      = AgentStatus.SKIPPED,
            output_type = AgentOutputType.NONE,
            content     = None,
            error       = reason or "Task skipped.",
        )

    # ── Private helpers ───────────────────────────────────────────────────

    def _validate_task(self, task: AgentTask) -> Optional[str]:
        """
        Validate that the incoming task is intended for this agent.

        Returns:
            None if valid, or a string error message if invalid.
        """
        if task.agent_type != self.manifest.agent_type:
            return (
                f"Task agent_type={task.agent_type.value} does not match "
                f"this agent's type={self.manifest.agent_type.value}."
            )
        if not task.instruction or not task.instruction.strip():
            return "Task instruction is empty."
        return None

    def _has_tool(self, tool_name: str) -> bool:
        """Check whether a tool is available to this agent."""
        return tool_name in self.tools

    def _call_tool(self, tool_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Safely invoke an injected tool by name.

        Args:
            tool_name: Name of the tool (must be in self.tools).
            *args, **kwargs: Passed to the tool callable.

        Returns:
            The tool's return value.

        Raises:
            KeyError:   If the tool is not available to this agent.
            ValueError: If the tool is not callable.
        """
        if tool_name not in self.tools:
            raise KeyError(
                f"Tool '{tool_name}' is not available to "
                f"{self.manifest.display_name}. "
                f"Available tools: {list(self.tools.keys())}"
            )
        tool = self.tools[tool_name]
        if not callable(tool):
            raise ValueError(f"Tool '{tool_name}' is not callable.")
        return tool(*args, **kwargs)

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"type={self.manifest.agent_type.value} "
            f"tools={list(self.tools.keys())}>"
        )
