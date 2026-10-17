"""
Universal OS Operations — Action History Memory
Stores structured records of assistant-executed OS operations in PostgreSQL
with an in-memory sliding window cache for resilience and fast retrieval.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import Any, Dict, List, Optional

from core.os_gateway.operation_model import OSOperation, OSOperationResult

logger = logging.getLogger(__name__)


class OSActionHistoryManager:
    """
    Manages persistent memory and auditing of OS operations.
    Enables historical queries such as:
    - "What did you do?"
    - "Where did you put that file?"
    - "What did you close?"
    - "What command did you run?"
    - "Undo what you just did"
    """

    def __init__(self, max_memory_records: int = 150):
        self._memory_cache: deque[Dict[str, Any]] = deque(maxlen=max_memory_records)

    def record_action(
        self,
        user_id: Any = 1,
        operation_type: str = "action",
        capability: str = "SYSTEM",
        target: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        execution_method: str = "direct",
        risk_level: str = "LOW",
        status: str = "SUCCESS",
        verified: bool = False,
        result_message: str = "",
        result_data: Optional[Dict[str, Any]] = None,
        error_message: str = "",
        before_state: Optional[Dict[str, Any]] = None,
        after_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Directly record an action with individual field parameters."""
        entry = {
            "operation_id": f"act_{int(time.time()*1000)}",
            "user_id": int(user_id) if str(user_id).isdigit() else 1,
            "capability": str(capability),
            "operation_type": str(operation_type),
            "target": str(target or ""),
            "parameters": parameters or {},
            "execution_method": str(execution_method),
            "risk_level": str(risk_level),
            "status": str(status),
            "verified": bool(verified),
            "result_message": str(result_message or ""),
            "result_data": result_data or {},
            "error_message": str(error_message or ""),
            "before_state": before_state or {},
            "after_state": after_state or {},
            "created_at": time.time(),
        }

        self._memory_cache.append(entry)

        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        INSERT INTO os_action_history (
                            operation_id, user_id, capability, operation_type,
                            target, parameters, execution_method, risk_level,
                            status, verified, result_message, result_data,
                            error_message, before_state, after_state, created_at
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, to_timestamp(%s)
                        );
                    """, (
                        entry["operation_id"],
                        entry["user_id"],
                        entry["capability"],
                        entry["operation_type"],
                        entry["target"],
                        json.dumps(entry["parameters"]),
                        entry["execution_method"],
                        entry["risk_level"],
                        entry["status"],
                        entry["verified"],
                        entry["result_message"],
                        json.dumps(entry["result_data"]),
                        entry["error_message"],
                        json.dumps(entry["before_state"]),
                        json.dumps(entry["after_state"]),
                        entry["created_at"],
                    ))
        except Exception:
            pass
        return True

    def record_operation(
        self,
        operation: OSOperation,
        result: OSOperationResult,
        before_state: Optional[Dict[str, Any]] = None,
        after_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Persists an executed OS operation to PostgreSQL and in-memory cache.
        """
        entry = {
            "operation_id": operation.operation_id,
            "user_id": int(operation.user_id) if str(operation.user_id).isdigit() else 1,
            "capability": operation.capability.value if hasattr(operation.capability, "value") else str(operation.capability),
            "operation_type": operation.operation_type.value if hasattr(operation.operation_type, "value") else str(operation.operation_type),
            "target": operation.target or "",
            "parameters": operation.parameters or {},
            "execution_method": operation.execution_method.value if hasattr(operation.execution_method, "value") else str(operation.execution_method),
            "risk_level": operation.risk_level.value if hasattr(operation.risk_level, "value") else str(operation.risk_level),
            "status": result.status,
            "verified": result.verified,
            "result_message": result.message,
            "result_data": result.data or {},
            "error_message": result.error or "",
            "before_state": before_state or operation.before_state or {},
            "after_state": after_state or operation.after_state or {},
            "created_at": time.time(),
        }

        # 1. In-memory append
        self._memory_cache.append(entry)

        # 2. PostgreSQL persistence
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        INSERT INTO os_action_history (
                            operation_id, user_id, capability, operation_type,
                            target, parameters, execution_method, risk_level,
                            status, verified, result_message, result_data,
                            error_message, before_state, after_state, created_at
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, to_timestamp(%s)
                        );
                    """, (
                        entry["operation_id"],
                        entry["user_id"],
                        entry["capability"],
                        entry["operation_type"],
                        entry["target"],
                        json.dumps(entry["parameters"]),
                        entry["execution_method"],
                        entry["risk_level"],
                        entry["status"],
                        entry["verified"],
                        entry["result_message"],
                        json.dumps(entry["result_data"]),
                        entry["error_message"],
                        json.dumps(entry["before_state"]),
                        json.dumps(entry["after_state"]),
                        entry["created_at"],
                    ))
                return True
        except Exception as exc:
            logger.debug("[OS_ACTION_HISTORY] Database write note: %s", exc)

        return True

    def get_recent_actions(
        self,
        user_id: Any = 1,
        limit: int = 10,
        capability: Optional[str] = None,
        operation_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves recent OS operations for a user, checking PostgreSQL first,
        falling back to in-memory cache.
        """
        uid = int(user_id) if str(user_id).isdigit() else 1
        results: List[Dict[str, Any]] = []

        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    query = """
                        SELECT operation_id, capability, operation_type, target,
                               parameters, execution_method, risk_level, status,
                               verified, result_message, result_data, error_message,
                               before_state, after_state, EXTRACT(EPOCH FROM created_at)
                        FROM os_action_history
                        WHERE user_id = %s
                    """
                    params: List[Any] = [uid]
                    if capability:
                        query += " AND capability = %s"
                        params.append(capability)
                    if operation_type:
                        query += " AND operation_type = %s"
                        params.append(operation_type)

                    query += " ORDER BY created_at DESC LIMIT %s;"
                    params.append(limit)

                    cur.execute(query, tuple(params))
                    for r in cur.fetchall():
                        results.append({
                            "operation_id": r[0],
                            "capability": r[1],
                            "operation_type": r[2],
                            "target": r[3],
                            "parameters": r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"),
                            "execution_method": r[5],
                            "risk_level": r[6],
                            "status": r[7],
                            "verified": bool(r[8]),
                            "result_message": r[9],
                            "result_data": r[10] if isinstance(r[10], dict) else json.loads(r[10] or "{}"),
                            "error_message": r[11],
                            "before_state": r[12] if isinstance(r[12], dict) else json.loads(r[12] or "{}"),
                            "after_state": r[13] if isinstance(r[13], dict) else json.loads(r[13] or "{}"),
                            "created_at": float(r[14]),
                        })
                    if results:
                        return results
        except Exception as exc:
            logger.debug("[OS_ACTION_HISTORY] Database read fallback: %s", exc)

        # Fallback to memory cache
        for entry in reversed(self._memory_cache):
            if entry["user_id"] == uid:
                if capability and entry["capability"] != capability:
                    continue
                if operation_type and entry["operation_type"] != operation_type:
                    continue
                results.append(entry)
                if len(results) >= limit:
                    break

        return results

    def record(self, operation: OSOperation, result: OSOperationResult, user_id: Any = 1, before_state: Optional[Dict[str, Any]] = None, after_state: Optional[Dict[str, Any]] = None) -> bool:
        """Alias for record_operation matching test conventions."""
        if user_id:
            operation.user_id = user_id
        return self.record_operation(operation, result, before_state=before_state, after_state=after_state)

    def get_recent(self, user_id: Any = 1, limit: int = 10, capability: Optional[str] = None, operation_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Alias for get_recent_actions matching test conventions."""
        return self.get_recent_actions(user_id=user_id, limit=limit, capability=capability, operation_type=operation_type)

    def get_last_action(self, user_id: Any = 1) -> Optional[Dict[str, Any]]:
        """Retrieve the single most recent operation."""
        actions = self.get_recent_actions(user_id=user_id, limit=1)
        return actions[0] if actions else None


_history_manager: Optional[OSActionHistoryManager] = None


def get_os_action_history() -> OSActionHistoryManager:
    global _history_manager
    if _history_manager is None:
        _history_manager = OSActionHistoryManager()
    return _history_manager
