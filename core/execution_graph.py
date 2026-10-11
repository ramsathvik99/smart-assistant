"""
Execution Graph Abstraction & Dependency Engine
Provides structured representation for multi-step goals with explicit dependencies,
preconditions, expected verification outcomes, and cascading failure containment.

Adheres strictly to AGENTS.md permanent architecture freeze.
Does not automatically execute nodes; executor/planner executes nodes explicitly.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ============================================================================
# Status Enumerations
# ============================================================================

class GraphStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class NodeStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


# ============================================================================
# Execution Node Model
# ============================================================================

@dataclass
class ExecutionNode:
    """
    Individual execution unit inside an ExecutionGraph.
    Tracks execution method, inputs, preconditions, expected result,
    verification outcome, and dependency links.
    """
    node_id: str = field(default_factory=lambda: f"node_{uuid.uuid4().hex[:10]}")
    goal_id: str = ""
    graph_id: str = ""
    parent_node_id: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)  # IDs of predecessor nodes

    capability: str = "filesystem"
    operation: str = "READ_FILE"
    inputs: Dict[str, Any] = field(default_factory=dict)
    preconditions: Dict[str, Any] = field(default_factory=dict)
    expected_result: Dict[str, Any] = field(default_factory=dict)
    execution_method: str = "native_api"

    status: NodeStatus = NodeStatus.PENDING
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    actual_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    verification_method: str = "state_inspection"
    verification_result: Optional[Dict[str, Any]] = None

    retry_count: int = 0
    max_retries: int = 2
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        """True if the node has finished execution in any state."""
        return self.status in (NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.SKIPPED, NodeStatus.CANCELLED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "goal_id": self.goal_id,
            "graph_id": self.graph_id,
            "parent_node_id": self.parent_node_id,
            "dependencies": list(self.dependencies),
            "capability": self.capability,
            "operation": self.operation,
            "inputs": dict(self.inputs),
            "preconditions": dict(self.preconditions),
            "expected_result": dict(self.expected_result),
            "execution_method": self.execution_method,
            "status": self.status.value if isinstance(self.status, Enum) else str(self.status),
            "start_time": self.start_time,
            "end_time": self.end_time,
            "actual_result": self.actual_result,
            "error": self.error,
            "verification_method": self.verification_method,
            "verification_result": self.verification_result,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionNode:
        st_val = data.get("status", NodeStatus.PENDING)
        if isinstance(st_val, str):
            try:
                st = NodeStatus(st_val.upper())
            except ValueError:
                st = NodeStatus.PENDING
        else:
            st = st_val

        return cls(
            node_id=str(data.get("node_id") or f"node_{uuid.uuid4().hex[:10]}"),
            goal_id=str(data.get("goal_id") or ""),
            graph_id=str(data.get("graph_id") or ""),
            parent_node_id=data.get("parent_node_id"),
            dependencies=list(data.get("dependencies") or []),
            capability=str(data.get("capability") or "filesystem"),
            operation=str(data.get("operation") or "READ_FILE"),
            inputs=dict(data.get("inputs") or {}),
            preconditions=dict(data.get("preconditions") or {}),
            expected_result=dict(data.get("expected_result") or {}) if isinstance(data.get("expected_result"), dict) else data.get("expected_result", {}),
            execution_method=str(data.get("execution_method") or "native_api"),
            status=st,
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            actual_result=data.get("actual_result"),
            error=data.get("error"),
            verification_method=str(data.get("verification_method") or "state_inspection"),
            verification_result=data.get("verification_result"),
            retry_count=int(data.get("retry_count") or 0),
            max_retries=int(data.get("max_retries") or 2),
            metadata=dict(data.get("metadata") or {}),
        )


# ============================================================================
# Execution Graph Model
# ============================================================================

class ExecutionGraph:
    """
    Reusable DAG (Directed Acyclic Graph) of dependent execution nodes.
    Supports sequential chains, fan-out/fan-in dependencies, truthful verification
    recording, and failure cascading.
    """

    def __init__(
        self,
        graph_id: Optional[str] = None,
        goal_id: str = "",
        user_id: int = 1,
        title: str = "Execution Graph",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.graph_id = graph_id or f"graph_{uuid.uuid4().hex[:10]}"
        self.goal_id = goal_id
        self.user_id = user_id
        self.title = title
        self.status = GraphStatus.PENDING
        self.nodes: Dict[str, ExecutionNode] = {}
        self.created_at = time.time()
        self.updated_at = time.time()
        self.metadata = metadata or {}

    # ------------------------------------------------------------------------
    # Node & Dependency Management
    # ------------------------------------------------------------------------

    def add_node(self, node: ExecutionNode) -> str:
        """Add an execution node to the graph and attach graph/goal identifiers."""
        node.graph_id = self.graph_id
        if self.goal_id and not node.goal_id:
            node.goal_id = self.goal_id
        self.nodes[node.node_id] = node
        self.updated_at = time.time()
        return node.node_id

    def add_dependency(self, child_node_id: str, depends_on_node_id: str) -> None:
        """Declare that child_node_id depends on successful completion of depends_on_node_id."""
        if child_node_id not in self.nodes:
            raise KeyError(f"Child node '{child_node_id}' not found in graph.")
        if depends_on_node_id not in self.nodes:
            raise KeyError(f"Dependency node '{depends_on_node_id}' not found in graph.")

        node = self.nodes[child_node_id]
        if depends_on_node_id not in node.dependencies:
            node.dependencies.append(depends_on_node_id)
        if node.parent_node_id is None:
            node.parent_node_id = depends_on_node_id
        self.updated_at = time.time()

    def get_node(self, node_id: str) -> Optional[ExecutionNode]:
        """Retrieve node by ID."""
        return self.nodes.get(node_id)

    def get_ready_nodes(self) -> List[ExecutionNode]:
        """
        Returns all nodes currently ready to execute:
        - Node status is PENDING
        - All predecessor dependencies are COMPLETED
        """
        ready: List[ExecutionNode] = []
        for node in self.nodes.values():
            if node.status != NodeStatus.PENDING:
                continue

            # Check if all dependencies are completed
            deps_satisfied = True
            for dep_id in node.dependencies:
                dep_node = self.nodes.get(dep_id)
                if not dep_node or dep_node.status != NodeStatus.COMPLETED:
                    deps_satisfied = False
                    break

            if deps_satisfied:
                ready.append(node)
        return ready

    def get_dependent_nodes(self, node_id: str) -> List[ExecutionNode]:
        """Find all direct dependents of a node."""
        return [n for n in self.nodes.values() if node_id in n.dependencies]

    # ------------------------------------------------------------------------
    # State Transitions & Failure Containment
    # ------------------------------------------------------------------------

    def mark_node_running(self, node_id: str) -> None:
        """Mark a node as RUNNING and record start time."""
        node = self.nodes.get(node_id)
        if not node:
            return
        node.status = NodeStatus.RUNNING
        node.start_time = time.time()
        self.status = GraphStatus.RUNNING
        self.updated_at = time.time()

    def mark_node_completed(
        self,
        node_id: str,
        actual_result: Dict[str, Any],
        verification_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mark node COMPLETED with verification result and update graph status if done."""
        node = self.nodes.get(node_id)
        if not node:
            return
        node.status = NodeStatus.COMPLETED
        node.end_time = time.time()
        node.actual_result = actual_result
        node.verification_result = verification_result
        self.updated_at = time.time()

        # Check if entire graph is completed
        all_terminal = all(n.is_terminal for n in self.nodes.values())
        if all_terminal:
            any_failed = any(n.status == NodeStatus.FAILED for n in self.nodes.values())
            self.status = GraphStatus.FAILED if any_failed else GraphStatus.COMPLETED

    def mark_node_failed(
        self,
        node_id: str,
        error: str,
        actual_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Mark node FAILED, preserve its error, preserve previous successful nodes,
        and stop dependent nodes by marking them SKIPPED.
        """
        node = self.nodes.get(node_id)
        if not node:
            return
        node.status = NodeStatus.FAILED
        node.end_time = time.time()
        node.error = error
        if actual_result is not None:
            node.actual_result = actual_result
        self.updated_at = time.time()

        # Cascade SKIPPED status to all downstream dependent nodes
        self._cascade_skip(node_id, reason=f"Dependency '{node_id}' failed.")

        # Update overall graph status
        self.status = GraphStatus.FAILED

    def mark_node_skipped(self, node_id: str, reason: str = "") -> None:
        """Explicitly skip a node and record reason in metadata."""
        node = self.nodes.get(node_id)
        if not node:
            return
        node.status = NodeStatus.SKIPPED
        node.end_time = time.time()
        node.metadata["skip_reason"] = reason
        node.actual_result = {"skip_reason": reason}
        self.updated_at = time.time()

    def mark_node_cancelled(self, node_id: str, reason: str = "") -> None:
        """Cancel an individual node."""
        node = self.nodes.get(node_id)
        if not node:
            return
        node.status = NodeStatus.CANCELLED
        node.end_time = time.time()
        node.metadata["cancel_reason"] = reason
        self.updated_at = time.time()

    def cancel_graph(self, reason: str = "User cancelled") -> None:
        """Cancel the entire graph and all remaining non-terminal nodes."""
        self.status = GraphStatus.CANCELLED
        self.metadata["cancel_reason"] = reason
        self.updated_at = time.time()
        for node in self.nodes.values():
            if not node.is_terminal:
                node.status = NodeStatus.CANCELLED
                node.metadata["cancel_reason"] = reason
                node.end_time = time.time()

    def _cascade_skip(self, failed_node_id: str, reason: str) -> None:
        """Transitively mark all downstream dependent nodes as SKIPPED."""
        to_process = [failed_node_id]
        while to_process:
            curr_id = to_process.pop(0)
            for node in self.nodes.values():
                if curr_id in node.dependencies and node.status == NodeStatus.PENDING:
                    node.status = NodeStatus.SKIPPED
                    node.metadata["skip_reason"] = reason
                    node.actual_result = {"skip_reason": reason}
                    node.end_time = time.time()
                    to_process.append(node.node_id)

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "goal_id": self.goal_id,
            "user_id": self.user_id,
            "title": self.title,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionGraph:
        st_val = data.get("status", GraphStatus.PENDING)
        st = GraphStatus(st_val) if isinstance(st_val, str) else st_val

        graph = cls(
            graph_id=str(data.get("graph_id") or f"graph_{uuid.uuid4().hex[:10]}"),
            goal_id=str(data.get("goal_id") or ""),
            user_id=int(data.get("user_id") or 1),
            title=str(data.get("title") or "Execution Graph"),
            metadata=dict(data.get("metadata") or {}),
        )
        graph.status = st
        graph.created_at = float(data.get("created_at") or time.time())
        graph.updated_at = float(data.get("updated_at") or time.time())

        raw_nodes = data.get("nodes", {})
        if isinstance(raw_nodes, dict):
            for nid, ndata in raw_nodes.items():
                node = ExecutionNode.from_dict(ndata)
                graph.nodes[node.node_id] = node
        elif isinstance(raw_nodes, list):
            for ndata in raw_nodes:
                node = ExecutionNode.from_dict(ndata)
                graph.nodes[node.node_id] = node

        return graph
