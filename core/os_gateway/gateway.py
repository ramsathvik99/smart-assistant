"""
Universal OS Operations — Central OS Gateway
The unified security boundary and execution coordinator for computer control.
Pipelines:
  Goal / Semantic Input
    ↓
  Structured OSOperation
    ↓
  Contextual Reference Resolution
    ↓
  Risk Assessment & Policy Validation
    ↓
  Capability Execution
    ↓
  Outcome Verification
    ↓
  State Engine & Environment Synchronization
    ↓
  Action History Memory (PostgreSQL)
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from core.os_gateway.action_history import get_os_action_history
from core.os_gateway.context_resolver import get_context_resolver
from core.os_gateway.environment_ops import inspect_path, read_env_var, set_env_var
from core.os_gateway.filesystem_ops import (
    calculate_size,
    compare_files,
    copy_file,
    create_directory,
    create_file,
    delete_directory,
    delete_file,
    inspect_metadata,
    list_directory,
    move_file,
    open_file_or_folder,
    read_file,
    rename_file,
    search_files,
    write_file,
    create_archive,
    extract_archive,
)
from core.os_gateway.gui_automation import click_button_by_name, inspect_window_controls
from core.os_gateway.network_ops import (
    diagnose_backend_issue,
    dns_lookup,
    get_network_adapters,
    test_connectivity,
)
from core.os_gateway.operation_model import (
    OSCapability,
    OSExecutionMethod,
    OSOperation,
    OSOperationResult,
    OSOperationType,
    OSRiskLevel,
)
from core.os_gateway.process_ops import (
    find_process,
    inspect_port,
    inspect_process,
    kill_by_port,
    list_processes,
    start_process,
    terminate_process,
)
from core.os_gateway.registry_ops import read_registry, write_registry
from core.os_gateway.service_ops import (
    inspect_service,
    list_services,
    restart_service,
    start_service,
    stop_service,
)
import core.os_gateway.service_ops as _service_ops
import core.os_gateway.system_ops as _system_ops
from core.os_gateway.shell_executor import get_shell_executor
from core.os_gateway.storage_ops import inspect_drive, list_accessible_drives
from core.os_gateway.system_ops import (
    get_system_overview,
    hibernate_system,
    lock_workstation,
    restart_system,
    shutdown_system,
    sign_out,
    sleep_system,
)
from core.os_gateway.verifier import get_os_verifier

logger = logging.getLogger(__name__)


class OSGateway:
    """
    Central operating system capability router, security boundary,
    and verification executor.
    """

    def __init__(self):
        self.context_resolver = get_context_resolver()
        self.verifier = get_os_verifier()
        self.action_history = get_os_action_history()
        self.shell_executor = get_shell_executor()

    def execute(
        self,
        operation: OSOperation,
        user_id: Any = 1,
        confirmed_by_user: bool = False,
        raw_query: str = "",
    ) -> OSOperationResult:
        """
        Executes a structured OSOperation through validation, capability selection,
        risk gates, verification, and history recording.
        """
        operation.user_id = user_id

        # 1. Capture before-state where relevant
        before_state = self._capture_before_state(operation)
        operation.before_state = before_state

        # Record intended action in PersistentExecutionRecordsManager (Section 4)
        intended_record_id: Optional[str] = None
        try:
            from core.persistent_execution_records import get_persistent_execution_records_manager
            records_mgr = get_persistent_execution_records_manager()
            intended_record_id = records_mgr.record_intended_action(
                operation=operation,
                user_id=user_id,
                execution_node_id=getattr(operation, "execution_node_id", None),
                goal_id=getattr(operation, "goal_id", None) or operation.original_goal,
                before_state=before_state,
            )
        except Exception as rec_err:
            logger.debug("[OS_GATEWAY] Failed to record intended action: %s", rec_err)

        # 2. Risk Evaluation & Policy Gate
        classified_risk = self._classify_risk(operation)
        risk_priority = {
            OSRiskLevel.READ_ONLY: 1,
            OSRiskLevel.LOW_RISK: 2,
            OSRiskLevel.MODIFYING: 3,
            OSRiskLevel.DESTRUCTIVE: 4,
            OSRiskLevel.PRIVILEGED: 5,
            OSRiskLevel.SYSTEM_CRITICAL: 6,
        }
        current_pri = risk_priority.get(operation.risk_level, 0)
        class_pri = risk_priority.get(classified_risk, 0)
        risk = classified_risk if class_pri >= current_pri else operation.risk_level
        operation.risk_level = risk

        if risk in (OSRiskLevel.DESTRUCTIVE, OSRiskLevel.PRIVILEGED, OSRiskLevel.SYSTEM_CRITICAL):
            operation.requires_confirmation = True
            if not confirmed_by_user:
                # FAIL CLOSED: If confirmation is needed and not provided, NEVER reach dispatch
                try:
                    from core.confirmation_manager import get_confirmation_manager
                    from core.risk_policy_engine import (
                        PolicyEvaluation, RiskLevel, PolicyDecision, ConfirmationRequest,
                        RiskAssessment, Reversibility, ExternalEffect
                    )
                    cm = get_confirmation_manager()
                    uid_int = int(user_id) if str(user_id).isdigit() else 1

                    risk_level = RiskLevel.CRITICAL if risk == OSRiskLevel.SYSTEM_CRITICAL else (
                        RiskLevel.HIGH if risk in (OSRiskLevel.DESTRUCTIVE, OSRiskLevel.PRIVILEGED) else RiskLevel.MEDIUM
                    )
                    assessment = RiskAssessment(
                        risk_level=risk_level,
                        reversibility=Reversibility.IRREVERSIBLE if risk in (OSRiskLevel.SYSTEM_CRITICAL, OSRiskLevel.DESTRUCTIVE) else Reversibility.PARTIALLY_REVERSIBLE,
                        external_effect=ExternalEffect.LOCAL_CHANGE,
                        confirmation_required=True,
                        rationale=f"Operation '{operation.operation_type.value}' on target '{operation.target}' is classified as {risk.value}.",
                    )
                    policy_eval = PolicyEvaluation(
                        decision=PolicyDecision.ALLOWED_WITH_CONFIRMATION,
                        assessment=assessment,
                        action_signature=f"os_gateway:{operation.capability.value}:{operation.operation_type.value}",
                        policy_rules_applied=["POL-OS-GATEWAY"],
                        rationale=f"Operation '{operation.operation_type.value}' on target '{operation.target}' is classified as {risk.value}.",
                        requires_confirmation=True,
                        confirmation_request=ConfirmationRequest(
                            action=operation.operation_type.value,
                            target=str(operation.target or ""),
                            effect="system_state_change",
                            risk_level=risk.value,
                            reason=f"Operation requires explicit user confirmation (classified as {risk.value}).",
                        ),
                        user_id=uid_int,
                    )

                    conf_req = cm.create_pending_confirmation(
                        user_id=uid_int,
                        intent=operation.capability.value,
                        original_command=operation.original_goal or str(operation.operation_type.value),
                        policy_evaluation=policy_eval,
                    )
                    conf_res = OSOperationResult(
                        success=False,
                        status="waiting_for_user",
                        message=(
                            f"Action '{operation.operation_type.value}' on target '{operation.target}' "
                            f"is classified as {risk.value}. Explicit confirmation required."
                        ),
                        data={"confirmation_id": conf_req.confirmation_id, "operation": operation.to_dict()},
                        operation_id=operation.operation_id,
                        capability=operation.capability.value,
                        operation_type=operation.operation_type.value,
                    )
                    if intended_record_id:
                        try:
                            records_mgr.update_action_record(
                                record_id=intended_record_id,
                                result=conf_res,
                                status="waiting_for_user",
                                verified=False
                            )
                        except Exception:
                            pass
                    return conf_res
                except Exception as exc:
                    logger.error("[OS_GATEWAY] Confirmation registration failed for %s; failing closed: %s", operation.operation_type, exc)
                    # FAIL CLOSED: Any exception during confirmation validation must BLOCK execution
                    block_res = OSOperationResult(
                        success=False,
                        status="blocked",
                        message=f"Action '{operation.operation_type.value}' blocked: confirmation evaluation failed ({exc}).",
                        error=str(exc),
                        operation_id=operation.operation_id,
                        capability=operation.capability.value,
                        operation_type=operation.operation_type.value,
                    )
                    if intended_record_id:
                        try:
                            records_mgr.update_action_record(
                                record_id=intended_record_id,
                                result=block_res,
                                status="blocked",
                                error=str(exc),
                                verified=False
                            )
                        except Exception:
                            pass
                    return block_res

        # HARD SAFETY BARRIER: Unconfirmed high-risk operations MUST NEVER reach dispatch
        if operation.requires_confirmation and not confirmed_by_user:
            hard_block_res = OSOperationResult(
                success=False,
                status="blocked",
                message=f"Action '{operation.operation_type.value}' blocked: explicit confirmation required.",
                operation_id=operation.operation_id,
                capability=operation.capability.value,
                operation_type=operation.operation_type.value,
            )
            if intended_record_id:
                try:
                    records_mgr.update_action_record(
                        record_id=intended_record_id,
                        result=hard_block_res,
                        status="blocked",
                        verified=False
                    )
                except Exception:
                    pass
            return hard_block_res

        # Mark operation as explicitly authorized for dispatch
        operation._dispatch_authorized = True

        # 3. Capability Dispatch
        raw_res: Dict[str, Any] = {}
        try:
            raw_res = self._dispatch_operation(operation)
        except Exception as exc:
            raw_res = {
                "success": False,
                "status": "error",
                "error": str(exc),
                "message": f"Execution error: {exc}",
            }

        # 4. Post-Execution Verification
        is_verified = False
        verif_msg = ""
        verif_details: Dict[str, Any] = {}
        if raw_res.get("success", False):
            is_verified, verif_msg, verif_details = self.verifier.verify_operation(operation, raw_res)
        else:
            verif_msg = raw_res.get("message", "Operation failed.")

        # 5. Build Final Result
        final_success = raw_res.get("success", False) and is_verified
        after_state = self._capture_after_state(operation, raw_res)
        operation.after_state = after_state

        result = OSOperationResult(
            success=final_success,
            status=raw_res.get("status", "success" if final_success else "error"),
            message=raw_res.get("message") or verif_msg or "Completed.",
            verified=is_verified,
            data=raw_res,
            error=raw_res.get("error"),
            verification_details=verif_details,
            operation_id=operation.operation_id,
            capability=operation.capability.value if hasattr(operation.capability, "value") else str(operation.capability),
            operation_type=operation.operation_type.value if hasattr(operation.operation_type, "value") else str(operation.operation_type),
            execution_method=operation.execution_method.value if hasattr(operation.execution_method, "value") else str(operation.execution_method),
        )

        # 6. Record to Persistent Action History & Update Action Record
        self.action_history.record_operation(
            operation=operation,
            result=result,
            before_state=before_state,
            after_state=after_state,
        )
        if intended_record_id:
            try:
                from core.persistent_execution_records import get_persistent_execution_records_manager
                get_persistent_execution_records_manager().update_action_record(
                    record_id=intended_record_id,
                    result=result,
                    after_state=after_state,
                    error=result.error or (result.data.get("error") if result.data else None),
                    verified=result.verified,
                    verification_details=verif_details,
                    affected_resource=str(operation.target or "")
                )
            except Exception as rec_upd_err:
                logger.debug("[OS_GATEWAY] Failed to update action record: %s", rec_upd_err)

        # 7. Sync with Environment State Engine
        self._sync_environment_state(operation, result)

        return result

    def _dispatch_operation(self, operation: OSOperation) -> Dict[str, Any]:
        """Routes operation to the appropriate underlying capability handler."""
        op_type = operation.operation_type
        target = operation.target or ""
        params = operation.parameters or {}

        # ── FAIL-CLOSED AUTHORIZATION BARRIER ──
        # Dangerous system power, session, and privileged operations MUST NEVER dispatch unauthorized
        if op_type in (
            OSOperationType.SHUTDOWN,
            OSOperationType.RESTART,
            OSOperationType.SIGN_OUT,
            OSOperationType.SLEEP,
            OSOperationType.HIBERNATE,
            OSOperationType.LOCK,
        ) and not getattr(operation, "_dispatch_authorized", False):
            logger.error("[OS_GATEWAY] Unauthorized dispatch attempt blocked for %s", op_type)
            return {
                "success": False,
                "status": "blocked",
                "message": f"Operation '{op_type.value}' is blocked: unauthorized dispatch without verified confirmation.",
            }

        # ── FILESYSTEM ──
        if op_type == OSOperationType.CREATE_FILE:
            return create_file(target, content=params.get("content", ""))
        elif op_type == OSOperationType.READ_FILE:
            return read_file(target, max_bytes=params.get("max_bytes", 1000000))
        elif op_type == OSOperationType.WRITE_FILE:
            return write_file(target, content=params.get("content", ""), mode=params.get("mode", "w"))
        elif op_type == OSOperationType.COPY_FILE:
            dest = params.get("destination") or params.get("dest") or ""
            return copy_file(target, dest)
        elif op_type == OSOperationType.MOVE_FILE:
            dest = params.get("destination") or params.get("dest") or ""
            return move_file(target, dest)
        elif op_type == OSOperationType.RENAME_FILE:
            new_name = params.get("new_name") or params.get("name") or ""
            return rename_file(target, new_name)
        elif op_type == OSOperationType.DELETE_FILE:
            perm = params.get("permanent", False)
            return delete_file(target, permanent=perm)
        elif op_type == OSOperationType.CREATE_DIRECTORY:
            return create_directory(target)
        elif op_type == OSOperationType.DELETE_DIRECTORY:
            perm = params.get("permanent", False)
            return delete_directory(target, permanent=perm)
        elif op_type == OSOperationType.LIST_DIRECTORY:
            limit = params.get("max_items", 100)
            return list_directory(target or os.getcwd(), max_items=limit)
        elif op_type in (OSOperationType.SEARCH_FILES, OSOperationType.FIND_FILES):
            return search_files(
                root_path=target or params.get("root", "C:\\"),
                pattern=params.get("pattern", "*"),
                extension=params.get("extension"),
                min_size_mb=params.get("min_size_mb"),
                max_size_mb=params.get("max_size_mb"),
                max_results=params.get("max_results", 50),
            )
        elif op_type in (OSOperationType.OPEN_FILE, OSOperationType.OPEN_DIRECTORY):
            return open_file_or_folder(target)
        elif op_type == OSOperationType.INSPECT_METADATA:
            return inspect_metadata(target)
        elif op_type == OSOperationType.CALCULATE_SIZE:
            return calculate_size(target)
        elif op_type == OSOperationType.COMPARE_FILES:
            file_b = params.get("file_b") or params.get("target_b") or ""
            return compare_files(target, file_b)
        elif op_type == OSOperationType.ARCHIVE_FILES:
            sources = params.get("sources") or [target]
            archive_path = params.get("archive_path") or target
            return create_archive(sources, archive_path)
        elif op_type == OSOperationType.EXTRACT_ARCHIVE:
            extract_dir = params.get("extract_dir") or params.get("destination") or "."
            return extract_archive(target, extract_dir)

        # ── STORAGE / DRIVES ──
        elif op_type == OSOperationType.LIST_DRIVES:
            drives = list_accessible_drives()
            return {"success": True, "status": "listed", "drives": drives, "message": f"Found {len(drives)} accessible drives."}
        elif op_type in (OSOperationType.INSPECT_DRIVE, OSOperationType.GET_FREE_SPACE):
            return inspect_drive(target)

        # ── SHELL / TERMINAL ──
        elif op_type == OSOperationType.EXECUTE_COMMAND:
            return self.shell_executor.execute_command(
                command=target or params.get("command", ""),
                shell_type=params.get("shell_type", "powershell"),
                cwd=params.get("cwd"),
                timeout=params.get("timeout", 30.0),
            )
        elif op_type == OSOperationType.START_BACKGROUND_PROCESS:
            return self.shell_executor.start_background_process(
                command=params.get("command", target),
                process_id_key=params.get("process_key", target),
                shell_type=params.get("shell_type", "powershell"),
                cwd=params.get("cwd"),
            )
        elif op_type == OSOperationType.TERMINATE_BACKGROUND_PROCESS:
            return self.shell_executor.terminate_background_process(target)

        # ── PROCESS MANAGEMENT ──
        elif op_type == OSOperationType.LIST_PROCESSES:
            return list_processes(
                sort_by=params.get("sort_by", "memory"),
                limit=params.get("limit", 25),
                name_filter=params.get("filter") or target,
            )
        elif op_type == OSOperationType.FIND_PROCESS:
            return find_process(target)
        elif op_type == OSOperationType.INSPECT_PROCESS:
            pid = int(target) if str(target).isdigit() else 0
            return inspect_process(pid)
        elif op_type == OSOperationType.START_PROCESS:
            return start_process(target, args=params.get("args"))
        elif op_type in (OSOperationType.STOP_PROCESS, OSOperationType.TERMINATE_PROCESS):
            force = params.get("force", False)
            return terminate_process(target, force=force)
        elif op_type == OSOperationType.INSPECT_PORT:
            port = int(target) if str(target).isdigit() else params.get("port", 8000)
            return inspect_port(port)
        elif op_type == OSOperationType.KILL_BY_PORT:
            port = int(target) if str(target).isdigit() else params.get("port", 8000)
            force = params.get("force", False)
            return kill_by_port(port, force=force)

        # ── WINDOWS SERVICES ──
        elif op_type == OSOperationType.LIST_SERVICES:
            return _service_ops.list_services(name_filter=target or params.get("filter"))
        elif op_type in (OSOperationType.INSPECT_SERVICE, OSOperationType.CHECK_SERVICE_STATUS):
            return _service_ops.inspect_service(target)
        elif op_type == OSOperationType.START_SERVICE:
            return _service_ops.start_service(target)
        elif op_type == OSOperationType.STOP_SERVICE:
            return _service_ops.stop_service(target)
        elif op_type == OSOperationType.RESTART_SERVICE:
            return _service_ops.restart_service(target)

        # ── ENVIRONMENT VARIABLES ──
        elif op_type == OSOperationType.READ_ENV_VAR:
            return read_env_var(target, scope=params.get("scope", "process"))
        elif op_type == OSOperationType.SET_ENV_VAR:
            return set_env_var(target, value=params.get("value", ""), scope=params.get("scope", "process"))
        elif op_type == OSOperationType.INSPECT_PATH:
            return inspect_path()

        # ── NETWORK DIAGNOSTICS ──
        elif op_type == OSOperationType.GET_NETWORK_ADAPTERS:
            return get_network_adapters()
        elif op_type == OSOperationType.TEST_CONNECTIVITY:
            return test_connectivity(target or params.get("host", "8.8.8.8"))
        elif op_type == OSOperationType.DNS_LOOKUP:
            return dns_lookup(target)
        elif op_type == OSOperationType.DIAGNOSE_NETWORK:
            port = int(target) if str(target).isdigit() else params.get("port", 8000)
            return diagnose_backend_issue(port=port)

        # ── REGISTRY ──
        elif op_type == OSOperationType.READ_REGISTRY:
            return read_registry(
                hive_name=params.get("hive", "HKCU"),
                sub_key=target or params.get("sub_key", ""),
                value_name=params.get("value_name"),
            )
        elif op_type == OSOperationType.WRITE_REGISTRY:
            return write_registry(
                hive_name=params.get("hive", "HKCU"),
                sub_key=target or params.get("sub_key", ""),
                value_name=params.get("value_name", ""),
                value_data=params.get("value_data", ""),
                value_type=params.get("value_type", "REG_SZ"),
            )

        # ── GUI AUTOMATION ──
        elif op_type == OSOperationType.INSPECT_ELEMENTS:
            hwnd = int(target) if str(target).isdigit() else None
            return inspect_window_controls(hwnd=hwnd)
        elif op_type == OSOperationType.CLICK_ELEMENT:
            return click_button_by_name(target)
        elif op_type == OSOperationType.FOCUS_WINDOW:
            try:
                import win32gui
                hwnd = int(target) if str(target).isdigit() else 0
                if not hwnd:
                    t_low = str(target).lower()
                    def _find_cb(h, extra):
                        if win32gui.IsWindowVisible(h) and t_low in win32gui.GetWindowText(h).lower():
                            extra.append(h)
                    matched = []
                    win32gui.EnumWindows(_find_cb, matched)
                    hwnd = matched[0] if matched else 0
                if hwnd:
                    import win32con
                    win32gui.ShowWindow(hwnd, 9)
                    win32gui.SetForegroundWindow(hwnd)
                    return {"success": True, "status": "focused", "hwnd": hwnd, "message": f"Focused window '{target}'."}
                return {"success": False, "status": "not_found", "message": f"Window '{target}' not found."}
            except Exception as e:
                return {"success": False, "status": "error", "message": str(e)}
        elif op_type == OSOperationType.SET_ELEMENT_VALUE:
            try:
                from core.target_resolver import get_target_resolver
                from core.content_inserter import get_content_inserter
                from core.artifact_graph import ContentArtifact
                text = str(target or params.get("text", ""))
                tgt = get_target_resolver().resolve_current_target()
                art = ContentArtifact(
                    artifact_id=f"art_direct_{int(time.time()*1000)}",
                    content=text,
                    topic="gateway_insertion",
                    content_type="text",
                    user_id=user_id or 1,
                )
                res = get_content_inserter().insert(art, tgt, user_id=user_id or 1)
                return {"success": res.get("success", False), "status": "inserted" if res.get("success") else "error", "result": res}
            except Exception as e:
                return {"success": False, "status": "error", "message": str(e)}

        # ── SYSTEM OPERATIONS ──
        elif op_type == OSOperationType.LOCK:
            return _system_ops.lock_workstation()
        elif op_type == OSOperationType.SIGN_OUT:
            return _system_ops.sign_out()
        elif op_type == OSOperationType.SLEEP:
            return _system_ops.sleep_system()
        elif op_type == OSOperationType.HIBERNATE:
            return _system_ops.hibernate_system()
        elif op_type == OSOperationType.RESTART:
            return _system_ops.restart_system(delay_seconds=params.get("delay", 0))
        elif op_type == OSOperationType.SHUTDOWN:
            return _system_ops.shutdown_system(delay_seconds=params.get("delay", 0))
        elif op_type == OSOperationType.GET_SYSTEM_INFO:
            return _system_ops.get_system_overview()

        # ── APPLICATION CONTROL ──
        elif op_type == OSOperationType.OPEN_APPLICATION:
            from extensions.system.smart_opener import smart_opener
            return smart_opener.smart_open(target)
        elif op_type == OSOperationType.CLOSE_APPLICATION:
            if isinstance(target, int) or (isinstance(target, str) and str(target).isdigit()):
                hwnd = int(target)
                try:
                    import win32gui, win32con
                    if win32gui.IsWindow(hwnd):
                        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                        return {"success": True, "status": "closed", "message": f"Closed window {hwnd}."}
                except Exception as e:
                    return {"success": False, "status": "error", "message": str(e)}
            from legacy.actions import close_app
            msg = close_app(str(target))
            return {"success": True, "status": "closed", "message": msg}

        return {"success": False, "status": "unsupported", "message": f"Operation '{op_type}' is not recognized."}

    def execute_natural_goal(
        self,
        goal_text: str,
        user_id: Any = 1,
        context: Optional[Dict[str, Any]] = None,
        confirmed: bool = False,
    ) -> Dict[str, Any]:
        """
        Main natural-language entry point for Universal OS operations.
        Deconstructs goals into structured operations and executes them.
        """
        raw = goal_text.strip()
        low = raw.lower()

        # 1. Past action queries ("What did you do?", "What was the last command?", "Undo that")
        if re.search(r'\b(?:what\s+did\s+you\s+do|what\s+command\s+did\s+you\s+run|what\s+did\s+you\s+close|where\s+did\s+you\s+put\s+that\s+file)\b', low):
            actions = self.action_history.get_recent_actions(user_id=user_id, limit=3)
            if not actions:
                return {"success": True, "status": "success", "response": "I haven't executed any OS operations yet in this session."}
            last = actions[0]
            op_t = last.get("operation_type")
            tgt = last.get("target")
            res_msg = last.get("result_message")
            return {
                "success": True,
                "status": "success",
                "response": f"Recently I performed {op_t} on '{tgt}': {res_msg}",
                "last_action": last,
            }

        # 2. Storage inspection: "How much space is left on D?", "check space on D drive"
        if any(w in low for w in ["all drives", "list drives", "show drives", "show me all drives", "what drives"]):
            op = OSOperation(
                capability=OSCapability.STORAGE,
                operation_type=OSOperationType.LIST_DRIVES,
                target="all",
                original_goal=raw,
            )
            res = self.execute(op, user_id=user_id, confirmed_by_user=confirmed)
            return {"success": res.success, "status": res.status, "response": res.message, "data": res.data}

        m_space = re.search(r'\b(?:space\s+(?:is\s+)?left\s+on|disk\s+space\s+(?:on|for)|check\s+space\s+on)\s+([a-zA-Z])(?:\s+drive|\s*:)?\b', low)
        if m_space or low in ("how much space is left on d?", "how much space is left on d", "space on d", "how much space is left on c drive?"):
            drive_letter = m_space.group(1).upper() if m_space else ("C" if "c" in low else "D")
            op = OSOperation(
                capability=OSCapability.STORAGE,
                operation_type=OSOperationType.INSPECT_DRIVE,
                target=f"{drive_letter}:",
                original_goal=raw,
            )
            res = self.execute(op, user_id=user_id, confirmed_by_user=confirmed)
            return {"success": res.success, "status": res.status, "response": res.message, "data": res.data}

        # 3. Port & Process inspection: "Check what's using port 8000 and stop it", "What's using port 8000?"
        m_port_kill = re.search(r'\b(?:check\s+what(?:\'s|\s+is)\s+using\s+port\s+(\d+)\s+and\s+(?:stop|kill)\s+it|kill\s+process\s+on\s+port\s+(\d+)|stop\s+what(?:\'s|\s+is)\s+using\s+port\s+(\d+))\b', low)
        if m_port_kill:
            p_num = int(m_port_kill.group(1) or m_port_kill.group(2) or m_port_kill.group(3))
            op = OSOperation(
                capability=OSCapability.PROCESS,
                operation_type=OSOperationType.KILL_BY_PORT,
                target=str(p_num),
                parameters={"port": p_num, "force": True},
                risk_level=OSRiskLevel.MODIFYING,
                original_goal=raw,
            )
            res = self.execute(op, user_id=user_id, confirmed_by_user=confirmed)
            return {"success": res.success, "status": res.status, "response": res.message, "data": res.data}

        m_port_check = re.search(r'\b(?:what(?:\'s|\s+is)\s+using\s+port\s+(\d+)|check\s+port\s+(\d+)|who\s+is\s+using\s+port\s+(\d+))\b', low)
        if m_port_check:
            p_num = int(m_port_check.group(1) or m_port_check.group(2) or m_port_check.group(3))
            op = OSOperation(
                capability=OSCapability.PROCESS,
                operation_type=OSOperationType.INSPECT_PORT,
                target=str(p_num),
                parameters={"port": p_num},
                risk_level=OSRiskLevel.READ_ONLY,
                original_goal=raw,
            )
            res = self.execute(op, user_id=user_id, confirmed_by_user=confirmed)
            return {"success": res.success, "status": res.status, "response": res.message, "data": res.data}

        # 4. Process termination: "Kill that process", "Stop that process"
        if re.search(r'\b(?:kill|stop|terminate)\s+(?:that\s+process|the\s+process|it)\b', low):
            proc_target = self.context_resolver.resolve_target("that process", user_id=user_id, entity_hint="PROCESS", context=context)
            if not proc_target:
                return {"success": False, "status": "clarification_needed", "response": "Which process would you like me to stop?"}

            op = OSOperation(
                capability=OSCapability.PROCESS,
                operation_type=OSOperationType.TERMINATE_PROCESS,
                target=proc_target,
                risk_level=OSRiskLevel.MODIFYING,
                original_goal=raw,
            )
            res = self.execute(op, user_id=user_id, confirmed_by_user=confirmed)
            return {"success": res.success, "status": res.status, "response": res.message, "data": res.data}

        # 5. Move file across drives: "Put this file in my D drive project folder", "Move this there"
        m_move = re.search(r'\b(?:put|move)\s+(this(?:\s+file)?|that(?:\s+file)?|the\s+file|[^\s]+?\.[a-zA-Z0-9]+)\s+(?:in|into|to|on)\s+(.+)', low)
        if m_move:
            src_str = m_move.group(1).strip()
            dest_str = m_move.group(2).strip()

            src_resolved = self.context_resolver.resolve_target(src_str, user_id=user_id, entity_hint="FILE", context=context)
            dest_resolved = self.context_resolver.resolve_destination(dest_str, source_path=src_resolved)

            if not src_resolved or not os.path.exists(src_resolved):
                return {"success": False, "status": "not_found", "response": f"I could not locate the file to move ({src_str})."}

            op = OSOperation(
                capability=OSCapability.FILESYSTEM,
                operation_type=OSOperationType.MOVE_FILE,
                target=src_resolved,
                parameters={"destination": dest_resolved},
                risk_level=OSRiskLevel.MODIFYING,
                original_goal=raw,
            )
            res = self.execute(op, user_id=user_id, confirmed_by_user=confirmed)
            return {"success": res.success, "status": res.status, "response": res.message, "data": res.data}

        # 6. File search across drives: "Find every Python file larger than 100 MB", "Find all pdfs on D:"
        if "larger than" in low or "files larger" in low:
            m_size = re.search(r'(\d+)\s*(?:mb|megabytes?)', low)
            size_mb = float(m_size.group(1)) if m_size else 100.0
            ext = None
            if "python" in low or ".py" in low:
                ext = ".py"
            elif "pdf" in low:
                ext = ".pdf"

            root = "D:\\" if "d:" in low or "on d" in low else ("C:\\" if "c:" in low else os.getcwd())
            op = OSOperation(
                capability=OSCapability.FILESYSTEM,
                operation_type=OSOperationType.SEARCH_FILES,
                target=root,
                parameters={"extension": ext, "min_size_mb": size_mb},
                risk_level=OSRiskLevel.READ_ONLY,
                original_goal=raw,
            )
            res = self.execute(op, user_id=user_id, confirmed_by_user=confirmed)
            return {"success": res.success, "status": res.status, "response": res.message, "data": res.data}

        # 7. Network diagnostics: "Why isn't my backend accessible?"
        if any(w in low for w in ["why isn't my backend", "backend not accessible", "backend accessible", "why is port 8000 not working"]):
            op = OSOperation(
                capability=OSCapability.NETWORK,
                operation_type=OSOperationType.DIAGNOSE_NETWORK,
                target="8000",
                parameters={"port": 8000},
                risk_level=OSRiskLevel.READ_ONLY,
                original_goal=raw,
            )
            res = self.execute(op, user_id=user_id, confirmed_by_user=confirmed)
            return {"success": res.success, "status": res.status, "response": res.message, "data": res.data}

        # 8. Terminal / backend goal: "Open my project, start a terminal there and run the backend"
        if ("start a terminal" in low or "open a terminal" in low or "open terminal" in low) and ("run the backend" in low or "run backend" in low):
            proj_dir = self.context_resolver.resolve_target("the project", user_id=user_id) or os.getcwd()
            # Launch terminal
            term_res = self.shell_executor.open_terminal_window(cwd=proj_dir, command_to_run="python app.py")
            return {
                "success": term_res.get("success", True),
                "status": "success",
                "response": f"Opened terminal at {proj_dir} and initiated backend process.",
                "data": term_res,
            }

        # 9. Direct command execution: "Run `python app.py`", "execute command..."
        # Guard: questions, game queries, and phrases where 'run' is part of a question are NOT shell execution commands
        if not re.search(r'\b(?:what|which|games?|can\s+i|compatible|download\s+and|hernia|area\s+of)\b', low):
            m_run_cmd = re.search(r'^(?:please\s+)?(?:run|execute)\s+[`"\']?([^`"\']+)[\'"`]?(?:\s+in\s+(.+))?', raw, re.IGNORECASE)
            if not m_run_cmd and ("`" in raw or "'" in raw or '"' in raw):
                m_run_cmd = re.search(r'\b(?:run|execute)\s+[`"\']([^`"\']+)[\'"`](?:\s+in\s+(.+))?', raw, re.IGNORECASE)
            if m_run_cmd:
                cmd = m_run_cmd.group(1).strip()
                if not cmd.lower().startswith(("in this", "on this", "on my", "on a")):
                    in_dir = m_run_cmd.group(2).strip() if m_run_cmd.group(2) else None
                    resolved_cwd = self.context_resolver.resolve_target(in_dir) if in_dir else os.getcwd()

                    op = OSOperation(
                        capability=OSCapability.SHELL,
                        operation_type=OSOperationType.EXECUTE_COMMAND,
                        target=cmd,
                        parameters={"command": cmd, "cwd": resolved_cwd},
                        risk_level=OSRiskLevel.LOW_RISK,
                        original_goal=raw,
                    )
                    res = self.execute(op, user_id=user_id, confirmed_by_user=confirmed)
                    return {"success": res.success, "status": res.status, "response": res.message, "data": res.data}

        # 10. Application launch: "Get Chrome running", "Bring up Notepad"
        m_app = re.search(r'\b(?:get|bring)\s+([a-zA-Z0-9_\s]+?)\s+(?:running|up|open)\b', low)
        if m_app:
            app_target = m_app.group(1).strip()
            op = OSOperation(
                capability=OSCapability.APPLICATION,
                operation_type=OSOperationType.OPEN_APPLICATION,
                target=app_target,
                risk_level=OSRiskLevel.LOW_RISK,
                original_goal=raw,
            )
            res = self.execute(op, user_id=user_id, confirmed_by_user=confirmed)
            return {"success": res.success, "status": res.status, "response": res.message, "data": res.data}

        # Fallback to system info query
        if "system info" in low or "system telemetry" in low or "computer status" in low:
            op = OSOperation(
                capability=OSCapability.SYSTEM_API,
                operation_type=OSOperationType.GET_SYSTEM_INFO,
                risk_level=OSRiskLevel.READ_ONLY,
                original_goal=raw,
            )
            res = self.execute(op, user_id=user_id, confirmed_by_user=confirmed)
            return {"success": res.success, "status": res.status, "response": res.message, "data": res.data}

        return {
            "success": False,
            "status": "unhandled",
            "response": f"I understood your request ('{raw}'), but could not map it to an execution mechanism.",
        }

    def _classify_risk(self, operation: OSOperation) -> OSRiskLevel:
        """Determines the safety risk tier of an operation."""
        op_t = operation.operation_type

        # Read-only
        if op_t in (
            OSOperationType.READ_FILE, OSOperationType.LIST_DIRECTORY,
            OSOperationType.SEARCH_FILES, OSOperationType.FIND_FILES,
            OSOperationType.INSPECT_METADATA, OSOperationType.CALCULATE_SIZE,
            OSOperationType.COMPARE_FILES, OSOperationType.LIST_DRIVES,
            OSOperationType.INSPECT_DRIVE, OSOperationType.GET_FREE_SPACE,
            OSOperationType.LIST_PROCESSES, OSOperationType.FIND_PROCESS,
            OSOperationType.INSPECT_PROCESS, OSOperationType.INSPECT_PORT,
            OSOperationType.LIST_SERVICES, OSOperationType.INSPECT_SERVICE,
            OSOperationType.CHECK_SERVICE_STATUS, OSOperationType.READ_ENV_VAR,
            OSOperationType.INSPECT_PATH, OSOperationType.GET_NETWORK_ADAPTERS,
            OSOperationType.TEST_CONNECTIVITY, OSOperationType.DNS_LOOKUP,
            OSOperationType.DIAGNOSE_NETWORK, OSOperationType.READ_REGISTRY,
            OSOperationType.INSPECT_ELEMENTS, OSOperationType.GET_SYSTEM_INFO,
            OSOperationType.GET_UPTIME,
        ):
            return OSRiskLevel.READ_ONLY

        # Destructive (data loss, process kill)
        if op_t in (
            OSOperationType.DELETE_FILE,
            OSOperationType.DELETE_DIRECTORY,
            OSOperationType.DELETE_REGISTRY_VALUE,
            OSOperationType.TERMINATE_PROCESS,
            OSOperationType.STOP_PROCESS,
            OSOperationType.KILL_BY_PORT,
        ):
            return OSRiskLevel.DESTRUCTIVE

        # Privileged / Critical Power & System Operations
        if op_t in (
            OSOperationType.SHUTDOWN,
            OSOperationType.RESTART,
            OSOperationType.SIGN_OUT,
            OSOperationType.SLEEP,
            OSOperationType.HIBERNATE,
            OSOperationType.WRITE_REGISTRY,
        ):
            return OSRiskLevel.SYSTEM_CRITICAL

        # Privileged system settings & services
        if op_t in (
            OSOperationType.LOCK,
            OSOperationType.START_SERVICE,
            OSOperationType.STOP_SERVICE,
            OSOperationType.RESTART_SERVICE,
        ):
            return OSRiskLevel.PRIVILEGED

        return OSRiskLevel.MODIFYING

    def _capture_before_state(self, operation: OSOperation) -> Dict[str, Any]:
        """Captures real-world pre-state snapshot."""
        try:
            target = operation.target or ""
            if operation.capability == OSCapability.FILESYSTEM and target:
                p = Path(target)
                if p.exists():
                    return {"exists": True, "size": p.stat().st_size, "modified": p.stat().st_mtime}
                return {"exists": False}
            elif operation.capability == OSCapability.PROCESS and target.isdigit():
                return {"pid_exists": psutil.pid_exists(int(target))}
        except Exception:
            pass
        return {}

    def _capture_after_state(self, operation: OSOperation, result: Dict[str, Any]) -> Dict[str, Any]:
        """Captures real-world post-state snapshot."""
        try:
            target = operation.target or ""
            if operation.capability == OSCapability.FILESYSTEM and target:
                p = Path(result.get("path") or result.get("destination") or target)
                if p.exists():
                    return {"exists": True, "size": p.stat().st_size, "modified": p.stat().st_mtime}
                return {"exists": False}
            elif operation.capability == OSCapability.PROCESS and target.isdigit():
                return {"pid_exists": psutil.pid_exists(int(target))}
        except Exception:
            pass
        return {}

    def _sync_environment_state(self, operation: OSOperation, result: OSOperationResult) -> None:
        """Synchronizes execution outcome with continuous observer and state engine."""
        try:
            from core.environment import get_state_engine
            engine = get_state_engine()
            # If application opened/closed, update active application
            if operation.operation_type == OSOperationType.OPEN_APPLICATION:
                engine.update_active_application(str(operation.user_id), operation.target)
        except Exception:
            pass


_os_gateway: Optional[OSGateway] = None


def get_os_gateway() -> OSGateway:
    global _os_gateway
    if _os_gateway is None:
        _os_gateway = OSGateway()
    return _os_gateway
