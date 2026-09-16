"""
assistant_os/agent_manager/registry.py
====================================
NOVA OS - Agent Manager: Agent Registry

Architecture:
    The AgentRegistry is the single source of truth for which agents
    are known to the system.  It is a pure in-memory store with NO
    external I/O dependencies.

    Responsibilities:
        ✓ Register new agents from an AgentManifest.
        ✓ Deregister agents gracefully.
        ✓ Look up agents by AgentType.
        ✓ List all agents, or only healthy/available ones.
        ✓ Auto-discover agents by scanning a directory for Python
          modules that expose a class-level AGENT_MANIFEST attribute.
        ✓ Track state transitions for each registered agent.
        ✓ Update heartbeat timestamps.

    The Registry does NOT:
        ✗ Execute agents
        ✗ Schedule tasks
        ✗ Perform health checks (that is HealthMonitor's job)

    Thread-safety:
        All mutating operations acquire a threading.Lock so the registry
        is safe for concurrent access from the Event Bus and from
        background health-check threads.

    Auto-Discovery:
        The registry scans a directory for Python files, imports each
        module, and looks for a class exposing `AGENT_MANIFEST: AgentManifest`.
        This mirrors the existing plugin_manager.py pattern (reused from
        extensions/plugin_manager.py) but without sandboxing, because
        these are trusted core agents — not user plugins.

SDD Reference: Section 13.1 (Agent Manager — Registry).
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import threading
from typing import Dict, List, Optional

from assistant_os.agent_manager.models import (
    AgentLifecycleState,
    AgentManifest,
    AgentRecord,
)
from assistant_os.planner.models import AgentType

logger = logging.getLogger("assistant_os.agent_manager.registry")


class AgentRegistry:
    """
    In-memory registry of all known NOVA OS agents.

    Usage:
        registry = AgentRegistry()
        registry.register(manifest)
        record = registry.get(AgentType.CODING)
        all_agents = registry.list_all()
    """

    def __init__(self, auto_idle_on_register: bool = True):
        """
        Args:
            auto_idle_on_register: When True, agents move directly from
                REGISTERED to IDLE on registration.  Set False when agents
                must explicitly signal readiness before accepting tasks.
        """
        self._auto_idle = auto_idle_on_register
        # Primary store: AgentType.value → AgentRecord
        self._store: Dict[str, AgentRecord] = {}
        self._lock  = threading.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, manifest: AgentManifest) -> AgentRecord:
        """
        Register an agent from its AgentManifest.

        If an agent of this type is already registered, the existing
        record is UPDATED with the new manifest (hot-reload support).

        Args:
            manifest: AgentManifest describing the agent.

        Returns:
            The created or updated AgentRecord.
        """
        key = manifest.agent_type.value

        with self._lock:
            if key in self._store:
                # Hot-reload: update manifest, preserve stats
                existing = self._store[key]
                existing.manifest = manifest
                logger.info(
                    f"[AgentRegistry] Updated existing agent: {key} "
                    f"(v{manifest.version})"
                )
                return existing

            initial_state = (
                AgentLifecycleState.IDLE
                if self._auto_idle
                else AgentLifecycleState.REGISTERED
            )
            record = AgentRecord(manifest=manifest, state=initial_state)
            self._store[key] = record

        logger.info(
            f"[AgentRegistry] Registered: {manifest.display_name} "
            f"({key}) — state={initial_state.value}, "
            f"max_concurrent={manifest.max_concurrent}"
        )
        return record

    def deregister(self, agent_type: AgentType) -> bool:
        """
        Remove an agent from the registry.

        Marks the record as DEREGISTERED before removing it so any
        references held by the Scheduler can detect removal.

        Args:
            agent_type: The agent type to remove.

        Returns:
            True if found and removed, False if not present.
        """
        key = agent_type.value
        with self._lock:
            record = self._store.get(key)
            if not record:
                logger.warning(
                    f"[AgentRegistry] Deregister called for unknown agent: {key}"
                )
                return False
            record.state = AgentLifecycleState.DEREGISTERED
            del self._store[key]

        logger.info(f"[AgentRegistry] Deregistered: {key}")
        return True

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, agent_type: AgentType) -> Optional[AgentRecord]:
        """
        Return the AgentRecord for a given AgentType, or None.

        Args:
            agent_type: The agent type to look up.
        """
        return self._store.get(agent_type.value)

    def get_available(self, agent_type: AgentType) -> Optional[AgentRecord]:
        """
        Return an AgentRecord only if the agent is currently available
        (IDLE and within concurrency limit).

        Returns:
            AgentRecord if available, None otherwise.
        """
        record = self.get(agent_type)
        if record and record.is_available:
            return record
        return None

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_all(self) -> List[AgentRecord]:
        """Return all registered AgentRecords (snapshot)."""
        with self._lock:
            return list(self._store.values())

    def list_by_state(self, state: AgentLifecycleState) -> List[AgentRecord]:
        """Return all agents currently in the given lifecycle state."""
        with self._lock:
            return [r for r in self._store.values() if r.state == state]

    def list_idle(self) -> List[AgentRecord]:
        """Shortcut: all IDLE agents."""
        return self.list_by_state(AgentLifecycleState.IDLE)

    def list_unhealthy(self) -> List[AgentRecord]:
        """Shortcut: all UNHEALTHY agents."""
        return self.list_by_state(AgentLifecycleState.UNHEALTHY)

    # ------------------------------------------------------------------
    # State Transitions
    # ------------------------------------------------------------------

    def update_state(
        self,
        agent_type: AgentType,
        new_state: AgentLifecycleState,
    ) -> bool:
        """
        Transition an agent to a new lifecycle state.

        Does nothing if agent is not found.

        Args:
            agent_type: Target agent.
            new_state:  Desired lifecycle state.

        Returns:
            True if state was updated, False if agent not found.
        """
        key = agent_type.value
        with self._lock:
            record = self._store.get(key)
            if not record:
                logger.warning(
                    f"[AgentRegistry] update_state: unknown agent {key}"
                )
                return False
            old_state   = record.state
            record.state = new_state

        logger.debug(
            f"[AgentRegistry] {key}: {old_state.value} → {new_state.value}"
        )
        return True

    def update_heartbeat(self, agent_type: AgentType) -> bool:
        """
        Record that an agent has sent a liveness heartbeat.

        Also transitions an UNHEALTHY agent back to IDLE.

        Args:
            agent_type: The agent that sent the heartbeat.

        Returns:
            True if the record was updated, False if not found.
        """
        from datetime import datetime
        key = agent_type.value

        with self._lock:
            record = self._store.get(key)
            if not record:
                return False
            record.last_heartbeat = datetime.utcnow()
            if record.state == AgentLifecycleState.UNHEALTHY:
                record.state = AgentLifecycleState.IDLE
                logger.info(
                    f"[AgentRegistry] {key}: recovered UNHEALTHY → IDLE "
                    f"via heartbeat."
                )

        return True

    def increment_active(self, agent_type: AgentType) -> None:
        """Increment the active task counter for an agent (task assigned)."""
        with self._lock:
            record = self._store.get(agent_type.value)
            if record:
                record.active_task_count += 1
                if record.state == AgentLifecycleState.IDLE:
                    record.state = AgentLifecycleState.BUSY

    def decrement_active(
        self,
        agent_type: AgentType,
        success: bool = True,
    ) -> None:
        """
        Decrement the active task counter for an agent (task finished).

        Args:
            agent_type: The agent whose task just finished.
            success:    True if the task completed successfully.
        """
        with self._lock:
            record = self._store.get(agent_type.value)
            if not record:
                return
            record.active_task_count = max(0, record.active_task_count - 1)
            if success:
                record.total_tasks_completed += 1
            else:
                record.total_tasks_failed += 1
            # If no more active tasks and agent is healthy → IDLE
            if (
                record.active_task_count == 0
                and record.state == AgentLifecycleState.BUSY
            ):
                record.state = AgentLifecycleState.IDLE

    # ------------------------------------------------------------------
    # Auto-Discovery
    # ------------------------------------------------------------------

    def discover_agents(self, directory: str) -> int:
        """
        Scan a directory for Python modules that expose an
        ``AGENT_MANIFEST: AgentManifest`` class attribute, and register
        each one automatically.

        Discovery Contract for Agent Modules:
            A module is eligible for auto-discovery if it exposes a
            module-level constant:

                AGENT_MANIFEST: AgentManifest = AgentManifest(...)

            OR a class named ``Agent`` with a class attribute:

                class Agent:
                    AGENT_MANIFEST: AgentManifest = AgentManifest(...)

        Args:
            directory: Absolute path to the agents directory.

        Returns:
            Number of agents successfully discovered and registered.
        """
        if not os.path.isdir(directory):
            logger.warning(
                f"[AgentRegistry] Discovery directory not found: {directory}"
            )
            return 0

        discovered = 0

        for filename in os.listdir(directory):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue

            module_name = filename[:-3]
            file_path   = os.path.join(directory, filename)

            try:
                manifest = self._load_manifest_from_file(module_name, file_path)
                if manifest:
                    self.register(manifest)
                    discovered += 1
                    logger.info(
                        f"[AgentRegistry] Auto-discovered: "
                        f"{manifest.display_name} from {filename}"
                    )
            except Exception as exc:
                logger.error(
                    f"[AgentRegistry] Failed to load agent from {filename}: {exc}"
                )

        logger.info(
            f"[AgentRegistry] Discovery complete: "
            f"{discovered} agent(s) from {directory}"
        )
        return discovered

    @staticmethod
    def _load_manifest_from_file(
        module_name: str,
        file_path: str,
    ) -> Optional[AgentManifest]:
        """
        Import a single Python file and extract its AgentManifest.

        Looks for:
            1. Module-level ``AGENT_MANIFEST`` variable.
            2. ``Agent.AGENT_MANIFEST`` class attribute.

        Returns:
            AgentManifest if found, None otherwise.
        """
        spec   = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)

        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            logger.debug(
                f"[AgentRegistry] Could not exec {module_name}: {exc}"
            )
            return None

        # Check module-level constant first
        manifest = getattr(module, "AGENT_MANIFEST", None)
        if isinstance(manifest, AgentManifest):
            return manifest

        # Check Agent class attribute
        agent_cls = getattr(module, "Agent", None)
        if agent_cls:
            manifest = getattr(agent_cls, "AGENT_MANIFEST", None)
            if isinstance(manifest, AgentManifest):
                return manifest

        return None

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, object]:
        """Return a JSON-serializable summary of the registry."""
        with self._lock:
            records = list(self._store.values())

        return {
            "total_registered": len(records),
            "idle":             sum(1 for r in records if r.state == AgentLifecycleState.IDLE),
            "busy":             sum(1 for r in records if r.state == AgentLifecycleState.BUSY),
            "unhealthy":        sum(1 for r in records if r.state == AgentLifecycleState.UNHEALTHY),
            "agents": [
                {
                    "agent_type":    r.agent_type.value,
                    "display_name":  r.manifest.display_name,
                    "state":         r.state.value,
                    "active_tasks":  r.active_task_count,
                    "completed":     r.total_tasks_completed,
                    "failed":        r.total_tasks_failed,
                }
                for r in records
            ],
        }
