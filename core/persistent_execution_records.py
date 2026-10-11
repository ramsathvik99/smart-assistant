"""
Persistent Execution & Action Records System
Integrates execution graphs, execution nodes, and pre/post action records
with PostgreSQL persistence and resilient in-memory sliding cache fallback.

Adheres strictly to AGENTS.md permanent architecture freeze.
Reuses existing action-history infrastructure without duplication.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.execution_graph import ExecutionGraph, ExecutionNode, GraphStatus, NodeStatus

logger = logging.getLogger(__name__)


# ============================================================================
# Action Record Data Model
# ============================================================================

@dataclass
class ActionRecord:
    """
    Structured persistent record of an executed or intended assistant action.
    Captures intent, before/after states, verification, and graph link.
    """
    action_id: str = field(default_factory=lambda: f"act_{uuid.uuid4().hex[:12]}")
    operation_id: Optional[str] = None
    user_id: int = 1
    goal_id: Optional[str] = None
    execution_node_id: Optional[str] = None
    capability: str = "filesystem"
    operation: str = "READ_FILE"
    intended_action: str = ""
    target: Optional[str] = None
    affected_resource: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    execution_method: str = "native_api"
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED, BLOCKED, WAITING_FOR_USER
    actual_result: Dict[str, Any] = field(default_factory=dict)
    verified: bool = False
    verification_result: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    related_environment_state: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    @property
    def record_id(self) -> str:
        return self.action_id

    @property
    def operation_type(self) -> str:
        return self.operation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "record_id": self.action_id,
            "operation_id": self.operation_id,
            "user_id": self.user_id,
            "goal_id": self.goal_id,
            "execution_node_id": self.execution_node_id,
            "capability": self.capability,
            "operation": self.operation,
            "operation_type": self.operation,
            "intended_action": self.intended_action,
            "target": self.target,
            "affected_resource": self.affected_resource or self.target,
            "parameters": self.parameters,
            "execution_method": self.execution_method,
            "status": self.status,
            "actual_result": self.actual_result,
            "verified": self.verified,
            "verification_result": self.verification_result,
            "error_message": self.error_message,
            "related_environment_state": self.related_environment_state,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ActionRecord:
        return cls(
            action_id=str(data.get("action_id") or data.get("record_id") or f"act_{uuid.uuid4().hex[:12]}"),
            operation_id=data.get("operation_id"),
            user_id=int(data.get("user_id") or 1),
            goal_id=data.get("goal_id"),
            execution_node_id=data.get("execution_node_id"),
            capability=str(data.get("capability") or "filesystem"),
            operation=str(data.get("operation") or data.get("operation_type") or "READ_FILE"),
            intended_action=str(data.get("intended_action") or ""),
            target=data.get("target"),
            affected_resource=data.get("affected_resource"),
            parameters=dict(data.get("parameters") or {}),
            execution_method=str(data.get("execution_method") or "native_api"),
            status=str(data.get("status") or "PENDING"),
            actual_result=dict(data.get("actual_result") or {}),
            verified=bool(data.get("verified", False)),
            verification_result=dict(data.get("verification_result") or {}),
            error_message=data.get("error_message"),
            related_environment_state=dict(data.get("related_environment_state") or {}),
            created_at=float(data.get("created_at") or time.time()),
            completed_at=data.get("completed_at"),
        )


# ============================================================================
# Persistent Execution Records Manager
# ============================================================================

class PersistentExecutionRecordsManager:
    """
    Manages persistent storage and querying of:
    - Goals
    - Execution Graphs & Nodes
    - Action Records (Intended & Completed)
    Saves to PostgreSQL when pool is healthy, with in-memory fallback.
    """

    def __init__(self, max_memory_records: int = 200):
        self._action_cache: deque[ActionRecord] = deque(maxlen=max_memory_records)
        self._graph_cache: Dict[str, ExecutionGraph] = {}
        self._goal_cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------------
    # 1. Action Records (Pre-Execution & Post-Execution Lifecycle)
    # ------------------------------------------------------------------------

    def record_intended_action(
        self,
        intended_action: Optional[Any] = None,
        capability: Optional[str] = None,
        operation: Optional[Any] = None,
        user_id: int = 1,
        target: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        execution_method: str = "native_api",
        goal_id: Optional[str] = None,
        execution_node_id: Optional[str] = None,
        environment_state: Optional[Dict[str, Any]] = None,
        before_state: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        Record the intended action BEFORE execution begins.
        Accepts either an OSOperation object or individual descriptive arguments.
        Returns unique action_id to be updated post-execution.
        """
        op_obj = None
        if hasattr(intended_action, "operation_type") and hasattr(intended_action, "capability"):
            op_obj = intended_action
        elif hasattr(operation, "operation_type") and hasattr(operation, "capability"):
            op_obj = operation

        if op_obj is not None:
            op_cap = op_obj.capability.value if hasattr(op_obj.capability, "value") else str(op_obj.capability)
            op_name = op_obj.operation_type.value if hasattr(op_obj.operation_type, "value") else str(op_obj.operation_type)
            op_intent = str(op_obj.original_goal or f"{op_name} on {op_obj.target or ''}")
            op_target = str(op_obj.target or "")
            op_params = dict(op_obj.parameters or {})
            op_exec = op_obj.execution_method.value if hasattr(op_obj.execution_method, "value") else str(op_obj.execution_method)
            op_uid = int(getattr(op_obj, "user_id", None) or user_id or 1)
            op_gid = goal_id or getattr(op_obj, "goal_id", None) or op_obj.original_goal
            op_nid = execution_node_id or getattr(op_obj, "execution_node_id", None)
            op_env = before_state or environment_state or getattr(op_obj, "before_state", {})
            op_id = getattr(op_obj, "operation_id", None)

            rec = ActionRecord(
                operation_id=op_id,
                user_id=op_uid,
                goal_id=op_gid,
                execution_node_id=op_nid,
                capability=op_cap,
                operation=op_name,
                intended_action=op_intent,
                target=op_target,
                parameters=op_params,
                execution_method=op_exec,
                status="PENDING",
                related_environment_state=dict(op_env or {}),
                created_at=time.time(),
            )
        else:
            rec = ActionRecord(
                user_id=int(user_id or 1),
                goal_id=goal_id,
                execution_node_id=execution_node_id,
                capability=str(capability or "filesystem"),
                operation=str(operation or "READ_FILE"),
                intended_action=str(intended_action or ""),
                target=target,
                parameters=parameters or {},
                execution_method=execution_method,
                status="PENDING",
                related_environment_state=dict(before_state or environment_state or {}),
                created_at=time.time(),
            )

        # 1. Memory cache
        self._action_cache.append(rec)

        # 2. PostgreSQL persistence
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        INSERT INTO action_records (
                            action_id, user_id, goal_id, execution_node_id,
                            capability, operation, intended_action, target,
                            parameters, execution_method, status,
                            related_environment_state, created_at
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, to_timestamp(%s)
                        )
                    """, (
                        rec.action_id, rec.user_id, rec.goal_id, rec.execution_node_id,
                        rec.capability, rec.operation, rec.intended_action, rec.target,
                        json.dumps(rec.parameters), rec.execution_method, rec.status,
                        json.dumps(rec.related_environment_state), rec.created_at,
                    ))
        except Exception as exc:
            logger.debug("[PERSISTENT_RECORDS] Failed to write intended action to PostgreSQL: %s", exc)

        return rec.action_id

    def update_action_record(
        self,
        action_id: Optional[str] = None,
        status: Optional[str] = None,
        actual_result: Optional[Dict[str, Any]] = None,
        verified: Optional[bool] = None,
        verification_result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        affected_resource: Optional[str] = None,
        related_environment_state: Optional[Dict[str, Any]] = None,
        record_id: Optional[str] = None,
        result: Optional[Any] = None,
        after_state: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        verification_details: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> bool:
        """
        Update an action record AFTER execution with verified outcomes, timestamps, and state.
        Accepts both direct fields and OSOperationResult object.
        """
        act_id = action_id or record_id
        if not act_id:
            return False

        final_status = status
        final_actual_result = actual_result
        final_verified = verified
        final_error = error_message or error
        final_verif_res = verification_result or verification_details
        final_env_state = related_environment_state or after_state
        final_resource = affected_resource

        if result is not None:
            if hasattr(result, "status") and final_status is None:
                final_status = "COMPLETED" if getattr(result, "success", False) else ("FAILED" if result.status in ("error", "failed") else result.status.upper())
            if hasattr(result, "verified") and final_verified is None:
                final_verified = bool(result.verified)
            if hasattr(result, "data") and final_actual_result is None:
                final_actual_result = result.data if isinstance(result.data, dict) else {"data": result.data}
            if hasattr(result, "error") and not final_error:
                final_error = str(result.error)
            if hasattr(result, "verification_details") and not final_verif_res:
                final_verif_res = result.verification_details

        if final_status is None:
            final_status = "COMPLETED"
        if final_verified is None:
            final_verified = False

        completed_time = time.time()

        # 1. Update in-memory cache
        for rec in reversed(self._action_cache):
            if rec.action_id == act_id or rec.operation_id == act_id:
                rec.status = final_status
                rec.actual_result = final_actual_result or {}
                rec.verified = final_verified
                rec.verification_result = final_verif_res or {}
                rec.error_message = final_error
                if final_resource:
                    rec.affected_resource = final_resource
                    rec.target = final_resource
                if final_env_state:
                    rec.related_environment_state = final_env_state
                rec.completed_at = completed_time
                break

        # 2. Update PostgreSQL
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        UPDATE action_records
                        SET status = %s,
                            actual_result = %s,
                            verified = %s,
                            verification_result = %s,
                            error_message = %s,
                            target = COALESCE(%s, target),
                            related_environment_state = COALESCE(%s, related_environment_state),
                            completed_at = to_timestamp(%s)
                        WHERE action_id = %s
                    """, (
                        status,
                        json.dumps(actual_result or {}),
                        verified,
                        json.dumps(verification_result or {}),
                        error_message,
                        affected_resource,
                        json.dumps(related_environment_state) if related_environment_state else None,
                        completed_time,
                        action_id,
                    ))
                return True
        except Exception as exc:
            logger.debug("[PERSISTENT_RECORDS] Failed to update action record in PostgreSQL: %s", exc)

        return True

    def get_action_record(self, action_id: str, user_id: int = 1) -> Optional[ActionRecord]:
        """Retrieve an action record by ID."""
        for rec in reversed(self._action_cache):
            if rec.action_id == action_id and rec.user_id == user_id:
                return rec

        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        SELECT action_id, user_id, goal_id, execution_node_id,
                               capability, operation, intended_action, target,
                               parameters, execution_method, status, actual_result,
                               verified, verification_result, error_message,
                               related_environment_state,
                               EXTRACT(EPOCH FROM created_at),
                               EXTRACT(EPOCH FROM completed_at)
                        FROM action_records
                        WHERE action_id = %s AND user_id = %s
                    """, (action_id, user_id))
                    r = cur.fetchone()
                    if r:
                        return ActionRecord(
                            action_id=r[0],
                            user_id=r[1],
                            goal_id=r[2],
                            execution_node_id=r[3],
                            capability=r[4],
                            operation=r[5],
                            intended_action=r[6],
                            target=r[7],
                            parameters=r[8] if isinstance(r[8], dict) else json.loads(r[8] or "{}"),
                            execution_method=r[9],
                            status=r[10],
                            actual_result=r[11] if isinstance(r[11], dict) else json.loads(r[11] or "{}"),
                            verified=bool(r[12]),
                            verification_result=r[13] if isinstance(r[13], dict) else json.loads(r[13] or "{}"),
                            error_message=r[14],
                            related_environment_state=r[15] if isinstance(r[15], dict) else json.loads(r[15] or "{}"),
                            created_at=float(r[16]),
                            completed_at=float(r[17]) if r[17] else None,
                        )
        except Exception as exc:
            logger.debug("[PERSISTENT_RECORDS] DB read error in get_action_record: %s", exc)

        return None

    def get_recent_actions(
        self,
        user_id: int = 1,
        limit: int = 10,
        capability: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[ActionRecord]:
        """Retrieve recent action records for user."""
        results: List[ActionRecord] = []

        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    query = """
                        SELECT action_id, user_id, goal_id, execution_node_id,
                               capability, operation, intended_action, target,
                               parameters, execution_method, status, actual_result,
                               verified, verification_result, error_message,
                               related_environment_state,
                               EXTRACT(EPOCH FROM created_at),
                               EXTRACT(EPOCH FROM completed_at)
                        FROM action_records
                        WHERE user_id = %s
                    """
                    params: List[Any] = [user_id]
                    if capability:
                        query += " AND capability = %s"
                        params.append(capability)
                    if status:
                        query += " AND status = %s"
                        params.append(status)
                    query += " ORDER BY created_at DESC LIMIT %s"
                    params.append(limit)

                    cur.execute(query, tuple(params))
                    for r in cur.fetchall():
                        results.append(ActionRecord(
                            action_id=r[0],
                            user_id=r[1],
                            goal_id=r[2],
                            execution_node_id=r[3],
                            capability=r[4],
                            operation=r[5],
                            intended_action=r[6],
                            target=r[7],
                            parameters=r[8] if isinstance(r[8], dict) else json.loads(r[8] or "{}"),
                            execution_method=r[9],
                            status=r[10],
                            actual_result=r[11] if isinstance(r[11], dict) else json.loads(r[11] or "{}"),
                            verified=bool(r[12]),
                            verification_result=r[13] if isinstance(r[13], dict) else json.loads(r[13] or "{}"),
                            error_message=r[14],
                            related_environment_state=r[15] if isinstance(r[15], dict) else json.loads(r[15] or "{}"),
                            created_at=float(r[16]),
                            completed_at=float(r[17]) if r[17] else None,
                        ))
                    if results:
                        return results
        except Exception as exc:
            logger.debug("[PERSISTENT_RECORDS] DB read error in get_recent_actions: %s", exc)

        # Fallback to memory
        for rec in reversed(self._action_cache):
            if rec.user_id == user_id:
                if capability and rec.capability != capability:
                    continue
                if status and rec.status != status:
                    continue
                results.append(rec)
                if len(results) >= limit:
                    break

        return results

    # ------------------------------------------------------------------------
    # 2. Execution Graph & Node Persistence
    # ------------------------------------------------------------------------

    def save_graph(self, graph: ExecutionGraph) -> bool:
        """Persist complete ExecutionGraph and all its nodes."""
        self._graph_cache[graph.graph_id] = graph

        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        INSERT INTO execution_graphs (
                            graph_id, goal_id, user_id, title, status, metadata,
                            created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s,
                            to_timestamp(%s), to_timestamp(%s)
                        )
                        ON CONFLICT (graph_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            metadata = EXCLUDED.metadata,
                            updated_at = EXCLUDED.updated_at
                    """, (
                        graph.graph_id, graph.goal_id or None, graph.user_id,
                        graph.title, graph.status.value, json.dumps(graph.metadata),
                        graph.created_at, graph.updated_at,
                    ))

                    for node in graph.nodes.values():
                        cur.execute("""
                            INSERT INTO execution_nodes (
                                node_id, graph_id, goal_id, user_id, capability,
                                operation, parent_node_id, dependencies, inputs,
                                preconditions, expected_result, execution_method,
                                status, actual_result, error, verification_result,
                                retry_count, start_time, end_time, metadata, created_at
                            ) VALUES (
                                %s, %s, %s, %s, %s,
                                %s, %s, %s, %s,
                                %s, %s, %s,
                                %s, %s, %s, %s,
                                %s,
                                CASE WHEN %s::float IS NOT NULL THEN to_timestamp(%s::float) ELSE NULL END,
                                CASE WHEN %s::float IS NOT NULL THEN to_timestamp(%s::float) ELSE NULL END,
                                %s, to_timestamp(%s)
                            )
                            ON CONFLICT (node_id) DO UPDATE SET
                                status = EXCLUDED.status,
                                actual_result = EXCLUDED.actual_result,
                                error = EXCLUDED.error,
                                verification_result = EXCLUDED.verification_result,
                                retry_count = EXCLUDED.retry_count,
                                start_time = EXCLUDED.start_time,
                                end_time = EXCLUDED.end_time,
                                metadata = EXCLUDED.metadata
                        """, (
                            node.node_id, graph.graph_id, node.goal_id or None, graph.user_id,
                            node.capability, node.operation, node.parent_node_id,
                            json.dumps(node.dependencies), json.dumps(node.inputs),
                            json.dumps(node.preconditions), json.dumps(node.expected_result),
                            node.execution_method, node.status.value,
                            json.dumps(node.actual_result or {}), node.error,
                            json.dumps(node.verification_result or {}), node.retry_count,
                            node.start_time, node.start_time,
                            node.end_time, node.end_time,
                            json.dumps(node.metadata), time.time(),
                        ))
                return True
        except Exception as exc:
            logger.debug("[PERSISTENT_RECORDS] Failed to save graph to PostgreSQL: %s", exc)

        return True

    def get_graph(self, graph_id: str, user_id: int = 1) -> Optional[ExecutionGraph]:
        """Retrieve an ExecutionGraph by ID."""
        if graph_id in self._graph_cache:
            g = self._graph_cache[graph_id]
            if g.user_id == user_id:
                return g

        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        SELECT graph_id, goal_id, user_id, title, status, metadata,
                               EXTRACT(EPOCH FROM created_at), EXTRACT(EPOCH FROM updated_at)
                        FROM execution_graphs
                        WHERE graph_id = %s AND user_id = %s
                    """, (graph_id, user_id))
                    r = cur.fetchone()
                    if r:
                        graph = ExecutionGraph(
                            graph_id=r[0],
                            goal_id=r[1] or "",
                            user_id=r[2],
                            title=r[3],
                            metadata=r[5] if isinstance(r[5], dict) else json.loads(r[5] or "{}"),
                        )
                        graph.status = GraphStatus(r[4])
                        graph.created_at = float(r[6])
                        graph.updated_at = float(r[7])

                        # Load nodes
                        cur.execute("""
                            SELECT node_id, goal_id, capability, operation, parent_node_id,
                                   dependencies, inputs, preconditions, expected_result,
                                   execution_method, status, actual_result, error,
                                   verification_result, retry_count,
                                   EXTRACT(EPOCH FROM start_time),
                                   EXTRACT(EPOCH FROM end_time),
                                   metadata
                            FROM execution_nodes
                            WHERE graph_id = %s
                        """, (graph_id,))
                        for nr in cur.fetchall():
                            node = ExecutionNode(
                                node_id=nr[0],
                                goal_id=nr[1] or graph.goal_id,
                                graph_id=graph.graph_id,
                                capability=nr[2],
                                operation=nr[3],
                                parent_node_id=nr[4],
                                dependencies=nr[5] if isinstance(nr[5], list) else json.loads(nr[5] or "[]"),
                                inputs=nr[6] if isinstance(nr[6], dict) else json.loads(nr[6] or "{}"),
                                preconditions=nr[7] if isinstance(nr[7], dict) else json.loads(nr[7] or "{}"),
                                expected_result=nr[8] if isinstance(nr[8], dict) else json.loads(nr[8] or "{}"),
                                execution_method=nr[9],
                                status=NodeStatus(nr[10]),
                                actual_result=nr[11] if isinstance(nr[11], dict) else json.loads(nr[11] or "{}"),
                                error=nr[12],
                                verification_result=nr[13] if isinstance(nr[13], dict) else json.loads(nr[13] or "{}"),
                                retry_count=int(nr[14] or 0),
                                start_time=float(nr[15]) if nr[15] else None,
                                end_time=float(nr[16]) if nr[16] else None,
                                metadata=nr[17] if isinstance(nr[17], dict) else json.loads(nr[17] or "{}"),
                            )
                            graph.nodes[node.node_id] = node

                        self._graph_cache[graph.graph_id] = graph
                        return graph
        except Exception as exc:
            logger.debug("[PERSISTENT_RECORDS] Failed to load graph from PostgreSQL: %s", exc)

        return self._graph_cache.get(graph_id)

    # ------------------------------------------------------------------------
    # 3. Contextual Reference Resolution for Actions and Nodes
    # ------------------------------------------------------------------------

    def find_action_by_reference(self, reference: str, user_id: int = 1) -> Optional[ActionRecord]:
        """
        Resolves natural language references to actions:
        - "that operation", "what you just did", "the previous action"
        - "the failed step", "the failed action"
        - "the file you moved", "what you moved"
        """
        ref_low = reference.lower().strip()
        actions = self.get_recent_actions(user_id=user_id, limit=20)
        if not actions:
            return None

        # 1. Failed step
        if any(w in ref_low for w in ["failed step", "failed action", "what failed", "the error", "failure"]):
            for a in actions:
                if a.status in ("FAILED", "error") or a.error_message:
                    return a

        # 2. File move
        if any(w in ref_low for w in ["moved", "relocated", "transferred"]):
            for a in actions:
                if a.operation in ("MOVE_FILE", "RENAME_FILE") or "move" in a.intended_action.lower():
                    return a

        # 3. File write / delete
        if any(w in ref_low for w in ["deleted", "removed"]):
            for a in actions:
                if a.operation in ("DELETE_FILE", "DELETE_DIRECTORY") or "delete" in a.intended_action.lower():
                    return a

        # 4. Process kill / stop
        if any(w in ref_low for w in ["killed", "stopped process", "closed process"]):
            for a in actions:
                if a.operation in ("TERMINATE_PROCESS", "KILL_BY_PORT", "STOP_SERVICE"):
                    return a

        # 5. Default: "what you just did", "that operation", "the previous action"
        return actions[0]


# ============================================================================
# Singleton Accessor
# ============================================================================

_persistent_records_manager: Optional[PersistentExecutionRecordsManager] = None


def get_persistent_execution_records_manager() -> PersistentExecutionRecordsManager:
    """Retrieve global singleton PersistentExecutionRecordsManager instance."""
    global _persistent_records_manager
    if _persistent_records_manager is None:
        _persistent_records_manager = PersistentExecutionRecordsManager()
    return _persistent_records_manager
