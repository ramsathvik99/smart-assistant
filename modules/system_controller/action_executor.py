"""
Action Executor for Nova System Controller
Authoritative structured executor for system operations with three-condition security gate
(Consent, Privilege, Authorization), verification, multi-step plan execution, and audit trail.
"""

from __future__ import annotations

import logging
import json
import time
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple, Union

from .folder_manager import create_folder, delete_folder, list_folders
from .file_manager import (
    open_file, get_file_info, list_files, copy_file, move_file,
    rename_file, safe_delete_file, create_text_file
)
from .app_launcher import launch_application, get_running_applications
from core.capability_consent_manager import (
    get_capability_consent_manager,
    CapabilityCategory,
    OPERATION_TO_CAPABILITY,
    resolve_operation_capability
)

logger = logging.getLogger("SystemActionExecutor")


@dataclass
class SystemActionResult:
    """Standardized result of a system controller action execution."""
    success: bool
    status: str  # "success", "verified", "failed", "blocked", "confirmation_required", "consent_required", "privilege_required"
    action: str
    target: str = ""
    message: str = ""
    verified: bool = False
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    requires_confirmation: bool = False
    requires_consent: bool = False
    requires_elevation: bool = False
    recovery_available: bool = False
    started_at: float = field(default_factory=time.time)
    completed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


class SystemActionExecutor:
    """Safe executor for system actions with capability gates, verification, and audit trail."""

    def __init__(self):
        self.action_log: List[Dict[str, Any]] = []
        self.require_confirmation = [
            "delete_folder", "delete_file", "terminate_process",
            "shutdown", "restart", "sign_out", "uninstall_software", "install_software"
        ]
        self.consent_manager = get_capability_consent_manager()

    def log_action(self, action: str, data: Any, result: Any, success: bool = True):
        """Log system action for in-memory and persistent audit trail."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "data": data,
            "result": str(result),
            "success": success
        }
        self.action_log.append(log_entry)
        if len(self.action_log) > 200:
            self.action_log = self.action_log[-200:]
        logger.info(f"[SYSTEM_ACTION] {action}: success={success} - {result}")

    def execute_action(
        self,
        action_data: Union[Dict[str, Any], str],
        parameters: Optional[Dict[str, Any]] = None,
        confirm: bool = False,
        user_id: int = 1
    ) -> Dict[str, Any]:
        """
        Execute a system action through the 3-condition capability and permission boundary.
        Supports both execute_action({"action": "...", ...}) and execute_action("action_name", {...}).
        """
        t0 = time.time()
        # Support execute_action("create_file", {"file_path": ...})
        if isinstance(action_data, str) and not action_data.strip().startswith("{"):
            merged = {"action": action_data}
            if isinstance(parameters, dict):
                merged.update(parameters)
            action_data = merged
        elif isinstance(action_data, str):
            try:
                action_data = json.loads(action_data)
            except Exception:
                return {
                    "success": False,
                    "status": "error",
                    "message": "Invalid action specification: expected dictionary or JSON string."
                }
        elif isinstance(action_data, dict) and isinstance(parameters, dict):
            merged = dict(action_data)
            merged.update(parameters)
            action_data = merged

        action = action_data.get("action")
        if not action:
            return {"success": False, "status": "error", "message": "No action specified"}

        target = str(action_data.get("name") or action_data.get("path") or action_data.get("app") or action_data.get("target") or "")
        risk_level = "DESTRUCTIVE" if action in self.require_confirmation else "LOW_RISK"

        # ── 1. THREE-CONDITION SECURITY GATE ─────────────────────────────────
        gate = self.consent_manager.evaluate_operation_gate(
            user_id=user_id,
            operation=action,
            target=target,
            risk_level=risk_level,
            params=action_data,
            confirmed_by_user=confirm,
        )

        logger.info(
            f"[ACTION_EXECUTOR_GATE] uid={user_id} action={action} target='{target}' "
            f"gate_status={gate.status} allowed={gate.allowed} requires_elevation={gate.requires_elevation}"
        )

        if not gate.allowed:
            # Check if Condition A (Consent) was granted, but Condition B (OS Elevation) is required
            if gate.status == "privilege_required" and gate.requires_elevation:
                # If high-risk or confirmation required, verify confirmation first
                if (action in self.require_confirmation or risk_level in ("DESTRUCTIVE", "PRIVILEGED", "HIGH")) and not confirm:
                    logger.info(
                        f"[ELEVATION_DECISION] uid={user_id} action={action} target='{target}' "
                        f"decision=requires_user_confirmation requires_elevation=True"
                    )
                    return {
                        "success": False,
                        "status": "confirmation_required",
                        "action": action,
                        "target": target,
                        "message": f"Action '{action}' on '{target}' requires confirmation before requesting administrator elevation.",
                        "requires_confirmation": True,
                        "data": action_data
                    }

                # Condition A (Consent) and Condition C (Confirmation) satisfied -> Trigger on-demand UAC elevation!
                logger.info(
                    f"[ELEVATION_DECISION] uid={user_id} action={action} target='{target}' "
                    f"decision=trigger_on_demand_uac requires_elevation=True"
                )
                from core.permission_manager import get_permission_elevation_manager
                pm = get_permission_elevation_manager()
                elev_res = pm.execute_privileged_operation(action, action_data, user_id=user_id)

                success = elev_res.get("status") in ("success", "verified") or elev_res.get("success", False)
                status = elev_res.get("status", "error")
                msg = elev_res.get("message") or elev_res.get("error") or ""
                verified = elev_res.get("verified", success)

                logger.info(
                    f"[ACTION_EXECUTOR_OUTCOME] uid={user_id} action={action} success={success} "
                    f"verified={verified} status={status} exit_code={elev_res.get('exit_code')}"
                )
                self.log_action(action, action_data, msg, success=success)
                return {
                    "success": success,
                    "status": "verified" if (success and verified) else status,
                    "action": action,
                    "target": target,
                    "message": msg,
                    "verified": verified,
                    "requires_elevation": True,
                    "data": action_data,
                    "details": elev_res
                }

            self.log_action(action, action_data, gate.reason, success=False)
            return {
                "success": False,
                "status": gate.status,
                "action": action,
                "target": target,
                "message": gate.reason,
                "requires_consent": gate.requires_consent,
                "requires_elevation": gate.requires_elevation,
                "requires_confirmation": gate.requires_confirmation,
                "suggested_action": gate.suggested_action,
                "data": action_data
            }

        # ── 2. CAPABILITY DISPATCH ──────────────────────────────────────────
        result = None
        success = True
        verified = False
        error_msg = None

        try:
            # ── Folder operations ──
            if action == "create_folder":
                folder_name = action_data.get("name")
                location = action_data.get("location", "desktop")
                if not folder_name:
                    return {"success": False, "status": "error", "message": "Folder name required"}
                result = create_folder(folder_name, location)
                success = not str(result).startswith("Error")
                verified = success

            elif action == "delete_folder":
                folder_name = action_data.get("name")
                location = action_data.get("location", "desktop")
                if not folder_name:
                    return {"success": False, "status": "error", "message": "Folder name required"}
                result = delete_folder(folder_name, location, confirm=True)
                success = not str(result).startswith("Error")
                verified = success

            elif action == "list_folders":
                location = action_data.get("location", "desktop")
                result = list_folders(location)
                success = True
                verified = True

            # ── File operations ──
            elif action == "open_file":
                file_path = action_data.get("path")
                if not file_path:
                    return {"success": False, "status": "error", "message": "File path required"}
                result = open_file(file_path)
                success = not str(result).startswith("Error")
                verified = success

            elif action == "get_file_info":
                file_path = action_data.get("path")
                if not file_path:
                    return {"success": False, "status": "error", "message": "File path required"}
                result = get_file_info(file_path)
                success = result.get("success", False) if isinstance(result, dict) else True
                verified = success

            elif action == "list_files":
                directory_path = action_data.get("directory")
                result = list_files(directory_path)
                success = True
                verified = True

            elif action == "copy_file":
                src = action_data.get("src") or action_data.get("source", "")
                dst = action_data.get("dst") or action_data.get("destination", "")
                res = copy_file(src, dst)
                success = res.get("success", False)
                result = res.get("message", "File copied.")
                verified = success

            elif action == "move_file":
                src = action_data.get("src") or action_data.get("source", "")
                dst = action_data.get("dst") or action_data.get("destination", "")
                res = move_file(src, dst)
                success = res.get("success", False)
                result = res.get("message", "File moved.")
                verified = success

            elif action == "rename_file":
                path = action_data.get("path", "")
                new_name = action_data.get("new_name", "")
                res = rename_file(path, new_name)
                success = res.get("success", False)
                result = res.get("message", "File renamed.")
                verified = success

            elif action == "safe_delete_file":
                path = action_data.get("path", "")
                perm = action_data.get("permanent", False)
                res = safe_delete_file(path, use_trash=not perm)
                success = res.get("success", False)
                result = res.get("message", "File deleted.")
                verified = success

            elif action in ("create_text_file", "create_file"):
                path = action_data.get("path") or action_data.get("file_path", "")
                content = action_data.get("content", "")
                overwrite = action_data.get("overwrite", False)
                res = create_text_file(path, content=content, overwrite=overwrite)
                success = res.get("success", False)
                result = res.get("message", "File created.")
                verified = success

            # ── Application operations ──
            elif action == "launch_app":
                app_name = action_data.get("app") or action_data.get("name", "")
                if not app_name:
                    return {"success": False, "status": "error", "message": "Application name required"}
                args = action_data.get("args", [])
                launch_res = launch_application(app_name, args)
                success = launch_res.get("success", True) if hasattr(launch_res, "get") else not str(launch_res).startswith("Error")
                result = str(launch_res)
                verified = getattr(launch_res, "verified", False)

            elif action == "list_running_apps":
                result = get_running_applications()
                success = True
                verified = True

            # ── UI Automation and App-Specific Workflows ──
            elif action in ("ui_action", "whatsapp_workflow", "excel_workflow", "vscode_workflow", "app_interact"):
                from .universal_app_controller import get_universal_app_controller
                uac = get_universal_app_controller()
                app_name = action_data.get("app") or action_data.get("target", "")
                sub_action = action_data.get("sub_action") or action_data.get("operation", "focus")
                interact_res = uac.execute_app_action(
                    app_name=app_name,
                    action=sub_action,
                    params=action_data,
                    confirmed_by_user=confirm
                )
                success = interact_res.success
                result = interact_res.message
                verified = interact_res.verified
                if interact_res.requires_confirmation:
                    return {
                        "success": False,
                        "status": "confirmation_required",
                        "action": action,
                        "message": interact_res.message,
                        "requires_confirmation": True,
                        "data": action_data
                    }

            # ── Process Control ──
            elif action == "terminate_process":
                from .system_controller import terminate_process
                pid = action_data.get("pid")
                proc_name = action_data.get("process_name") or action_data.get("name")
                t_res = terminate_process(pid=pid, name=proc_name)
                success = t_res.get("success", False)
                result = t_res.get("message", "Process terminated.")
                verified = success

            # ── System Power ──
            elif action in ("shutdown", "restart", "lock", "sleep", "sign_out"):
                from .system_controller import initiate_system_power
                delay = action_data.get("delay", 0)
                p_res = initiate_system_power(action, delay_seconds=delay, confirmed_by_user=confirm)
                success = p_res.get("success", False)
                result = p_res.get("message", f"Power action '{action}' initiated.")
                verified = success

            # ── Privileged / Software Management Operations (when already elevated) ──
            elif action in ("install_software", "uninstall_software", "service_control", "elevated_command", "test_elevation", "elevation", "request_elevation"):
                from core.permission_manager import get_permission_elevation_manager
                pm = get_permission_elevation_manager()
                elev_res = pm.execute_privileged_operation(action, action_data, user_id=user_id)
                verified = bool(elev_res.get("verified", False))
                success = verified and bool(elev_res.get("status") in ("success", "verified") or elev_res.get("success", False))
                result = elev_res.get("message") or elev_res.get("error") or "Operation completed."
                logger.info(
                    f"[ACTION_EXECUTOR_OUTCOME] uid={user_id} action={action} (already_elevated) "
                    f"success={success} verified={verified} status={elev_res.get('status')}"
                )

            else:
                return {"success": False, "status": "unsupported", "message": f"Invalid action: {action}"}

            t1 = time.time()
            self.log_action(action, action_data, result, success)

            return {
                "success": success,
                "status": "verified" if (success and verified) else ("success" if success else "error"),
                "message": result,
                "verified": verified,
                "action": action,
                "target": target,
                "duration_ms": round((t1 - t0) * 1000, 2),
                "data": action_data
            }

        except Exception as e:
            error_msg = f"Error executing action '{action}': {str(e)}"
            logger.error(error_msg)
            self.log_action(action, action_data, error_msg, False)

            return {
                "success": False,
                "status": "error",
                "message": error_msg,
                "verified": False,
                "action": action,
                "target": target,
                "error": str(e),
                "data": action_data
            }

    # ── 3. MULTI-STEP PLAN EXECUTION WITH INTEGRATED RECOVERY ────────────────

    def execute_plan(
        self,
        steps: List[Dict[str, Any]],
        user_id: int = 1,
        confirm: bool = False
    ) -> Dict[str, Any]:
        """
        Executes a sequence of steps closed-loop:
        Checks preconditions -> evaluates consent before each step -> executes step ->
        verifies outcome -> halts immediately if a step fails or consent is revoked.
        """
        completed_steps = []
        failed_step = None

        for idx, step in enumerate(steps):
            step_action = step.get("action", f"step_{idx+1}")

            # Re-verify consent before every single step: handles mid-plan revocation
            cat = resolve_operation_capability(step_action)
            if not self.consent_manager.is_consent_granted(user_id, cat):
                msg = f"Plan stopped at step {idx+1} ('{step_action}'): capability consent for '{cat.value}' was revoked."
                logger.warning(msg)
                return {
                    "success": False,
                    "status": "consent_revoked",
                    "completed_steps": completed_steps,
                    "failed_step": {"index": idx, "action": step_action, "reason": msg},
                    "message": msg
                }

            res = self.execute_action(step, confirm=confirm, user_id=user_id)
            if not res.get("success"):
                failed_step = {"index": idx, "action": step_action, "result": res}
                msg = f"Multi-step task stopped at step {idx+1} ('{step_action}'): {res.get('message')}"
                return {
                    "success": False,
                    "status": "step_failed",
                    "completed_steps": completed_steps,
                    "failed_step": failed_step,
                    "message": msg
                }

            completed_steps.append({"index": idx, "action": step_action, "result": res})

        return {
            "success": True,
            "status": "completed",
            "completed_steps": completed_steps,
            "total_steps": len(steps),
            "message": f"Successfully executed and verified all {len(steps)} steps."
        }

    def get_action_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent in-memory action history."""
        return self.action_log[-limit:] if self.action_log else []

    def clear_action_log(self) -> Dict[str, Any]:
        """Clear the in-memory action log."""
        self.action_log.clear()
        return {"success": True, "message": "Action log cleared"}


# Global executor instance
_executor = SystemActionExecutor()


def execute_action(
    action_data: Union[Dict[str, Any], str],
    parameters: Optional[Dict[str, Any]] = None,
    confirm: bool = False,
    user_id: int = 1
) -> Dict[str, Any]:
    """Convenience function for executing actions through the global executor."""
    return _executor.execute_action(action_data, parameters=parameters, confirm=confirm, user_id=user_id)


def execute_plan(steps: List[Dict[str, Any]], user_id: int = 1, confirm: bool = False) -> Dict[str, Any]:
    """Convenience function for executing multi-step plans through the global executor."""
    return _executor.execute_plan(steps, user_id=user_id, confirm=confirm)


def get_action_history(limit: int = 10) -> List[Dict[str, Any]]:
    return _executor.get_action_history(limit)


def clear_action_log() -> Dict[str, Any]:
    return _executor.clear_action_log()
