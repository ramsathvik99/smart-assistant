"""
assistant_os/planner/dependency_resolver.py
========================================
NOVA OS - Planner: DAG Builder and Dependency Resolver

Architecture:
    This module is the pure graph-processing brain of the Planner.
    It takes a flat list of TaskNodes (already populated with
    agent_type and instruction) and:

        1. Validates that the dependency graph is a valid DAG
           (no cycles, no references to non-existent task_ids).
        2. Topologically sorts the nodes using Kahn's Algorithm.
        3. Computes parallel execution groups (wavefronts).
        4. Sets `can_run_parallel` on each node.
        5. Sets `position` (topological index) on each node.

    This module is STATELESS and PURE — it has no side effects,
    makes no LLM calls, and does not touch memory or agents.

Inputs:
    List[TaskNode] — nodes with dependencies already set.

Outputs:
    Tuple[List[TaskNode], List[List[str]]]
        — topologically sorted nodes with positions set,
        — execution_groups: parallel wavefronts as List[List[task_id]]

Raises:
    CyclicDependencyError  — if the graph contains a cycle.
    UnknownDependencyError — if a dependency references a missing task_id.

SDD Reference: Section 12.2 (Planning Steps — Dependency Analysis).
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple

from assistant_os.planner.models import TaskNode

logger = logging.getLogger("assistant_os.planner.dependency_resolver")


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class CyclicDependencyError(ValueError):
    """Raised when the dependency graph contains a cycle."""
    pass


class UnknownDependencyError(ValueError):
    """Raised when a task depends on a task_id not in the graph."""
    pass


# ---------------------------------------------------------------------------
# DependencyResolver
# ---------------------------------------------------------------------------

class DependencyResolver:
    """
    Converts a flat list of TaskNodes into a validated, topologically
    sorted DAG with parallel execution groups.

    Usage:
        resolver = DependencyResolver()
        sorted_nodes, groups = resolver.resolve(task_nodes)
    """

    def resolve(
        self,
        nodes: List[TaskNode],
    ) -> Tuple[List[TaskNode], List[List[str]]]:
        """
        Validate, topologically sort, and group nodes by parallel wavefront.

        Args:
            nodes: Flat list of TaskNode objects with dependencies set.

        Returns:
            A tuple of:
                - Sorted list of TaskNodes (position field updated).
                - execution_groups: List of lists of task_ids.
                  Each inner list represents one parallel execution wave.

        Raises:
            UnknownDependencyError: A dependency references an absent task_id.
            CyclicDependencyError:  The graph has a cycle (not a DAG).
        """
        if not nodes:
            logger.debug("[DependencyResolver] Empty node list — returning empty plan.")
            return [], []

        # Build task_id → TaskNode index
        node_index: Dict[str, TaskNode] = {n.task_id: n for n in nodes}

        # Step 1 — Validate all dependency references exist
        self._validate_references(node_index)

        # Step 2 — Topological sort using Kahn's Algorithm
        sorted_nodes, execution_groups = self._kahn_sort(nodes, node_index)

        # Step 3 — Annotate nodes with position and parallelism flag
        position = 0
        for wave_idx, wave in enumerate(execution_groups):
            is_parallel_wave = len(wave) > 1
            for task_id in wave:
                node = node_index[task_id]
                node.position = position
                node.can_run_parallel = is_parallel_wave
                position += 1

        logger.info(
            f"[DependencyResolver] Resolved {len(sorted_nodes)} tasks "
            f"into {len(execution_groups)} execution wave(s)."
        )
        return sorted_nodes, execution_groups

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _validate_references(self, node_index: Dict[str, TaskNode]) -> None:
        """Ensure every declared dependency points to a known task_id."""
        for node in node_index.values():
            for dep_id in node.dependencies:
                if dep_id not in node_index:
                    raise UnknownDependencyError(
                        f"Task '{node.task_id}' ({node.instruction[:40]!r}) "
                        f"depends on unknown task_id '{dep_id}'."
                    )

    def _kahn_sort(
        self,
        nodes: List[TaskNode],
        node_index: Dict[str, TaskNode],
    ) -> Tuple[List[TaskNode], List[List[str]]]:
        """
        Kahn's Algorithm for topological sort with wavefront grouping.

        A 'wavefront' (execution group) is the set of nodes whose
        in-degree becomes zero at the same step — these can all run
        in parallel.

        Raises:
            CyclicDependencyError: if the sort cannot complete (cycle exists).
        """
        # Build in-degree count and adjacency list (dependants)
        in_degree: Dict[str, int]        = defaultdict(int)
        dependants: Dict[str, List[str]] = defaultdict(list)  # task_id → tasks that depend on it

        for node in nodes:
            if node.task_id not in in_degree:
                in_degree[node.task_id] = 0  # Ensure every node is in the map
            for dep_id in node.dependencies:
                in_degree[node.task_id] += 1
                dependants[dep_id].append(node.task_id)

        # Start with all nodes that have no dependencies
        queue: deque[str] = deque(
            task_id for task_id, degree in in_degree.items() if degree == 0
        )

        sorted_nodes: List[TaskNode]   = []
        execution_groups: List[List[str]] = []

        while queue:
            # All nodes currently in the queue form one parallel wave
            current_wave: List[str] = list(queue)
            queue.clear()

            execution_groups.append(current_wave)

            for task_id in current_wave:
                sorted_nodes.append(node_index[task_id])
                # Reduce in-degree of all nodes that depended on this one
                for dependant_id in dependants[task_id]:
                    in_degree[dependant_id] -= 1
                    if in_degree[dependant_id] == 0:
                        queue.append(dependant_id)

        # If any nodes are unprocessed, a cycle exists
        if len(sorted_nodes) != len(nodes):
            cyclic_nodes = [
                n.task_id for n in nodes
                if n not in sorted_nodes
            ]
            raise CyclicDependencyError(
                f"Cyclic dependency detected among task(s): {cyclic_nodes}. "
                "The task graph must be a DAG with no circular references."
            )

        return sorted_nodes, execution_groups
