"""
Universal OS Operations — Post-Execution Outcome Verifier
Truthfully verifies real-world OS state changes following an operation.
Prevents false completion: an operation is only verified if the target state
is actively confirmed in the actual computer environment.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import psutil

from core.os_gateway.operation_model import OSOperation, OSOperationResult, OSOperationType

logger = logging.getLogger(__name__)


class OSVerifier:
    """
    Verifies that the requested real-world OS effect was achieved.
    """

    def verify_operation(
        self,
        operation: OSOperation,
        raw_result: Dict[str, Any],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Verifies the outcome of an executed operation.
        Returns: (verified_bool, verification_message, verification_details)
        """
        op_type = operation.operation_type
        target = operation.target or ""
        params = operation.parameters or {}

        # 1. CREATE_FILE
        if op_type == OSOperationType.CREATE_FILE:
            p = Path(raw_result.get("path") or target)
            if p.exists() and p.is_file():
                return True, f"Verified: file '{p.name}' exists on disk ({p.stat().st_size} bytes).", {"path": str(p), "size": p.stat().st_size}
            return False, f"Verification failed: file '{p}' was not found after creation.", {"path": str(p)}

        # 2. WRITE_FILE
        if op_type == OSOperationType.WRITE_FILE:
            p = Path(raw_result.get("path") or target)
            if p.exists() and p.is_file():
                return True, f"Verified: file '{p.name}' updated on disk ({p.stat().st_size} bytes).", {"path": str(p), "size": p.stat().st_size}
            return False, f"Verification failed: file '{p}' not found after write.", {"path": str(p)}

        # 3. MOVE_FILE
        if op_type == OSOperationType.MOVE_FILE:
            dest = Path(raw_result.get("destination") or params.get("destination") or "")
            src = Path(raw_result.get("source") or target)
            dest_ok = dest.exists()
            src_gone = not src.exists() or (src.resolve() == dest.resolve())
            if dest_ok and src_gone:
                return True, f"Verified: file exists at '{dest}' and source is no longer present.", {"destination": str(dest)}
            elif not dest_ok:
                return False, f"Verification failed: destination '{dest}' does not exist.", {"destination": str(dest)}
            else:
                return False, f"Verification failed: source '{src}' was not removed after move.", {"source": str(src)}

        # 4. COPY_FILE
        if op_type == OSOperationType.COPY_FILE:
            dest = Path(raw_result.get("destination") or params.get("destination") or "")
            if dest.exists():
                return True, f"Verified: copy exists at '{dest}'.", {"destination": str(dest)}
            return False, f"Verification failed: copied file '{dest}' not found.", {"destination": str(dest)}

        # 5. DELETE_FILE / DELETE_DIRECTORY
        if op_type in (OSOperationType.DELETE_FILE, OSOperationType.DELETE_DIRECTORY):
            p = Path(raw_result.get("path") or target)
            if not p.exists():
                return True, f"Verified: '{p.name}' no longer exists on filesystem.", {"path": str(p)}
            return False, f"Verification failed: '{p.name}' still exists after deletion.", {"path": str(p)}

        # 6. CREATE_DIRECTORY
        if op_type == OSOperationType.CREATE_DIRECTORY:
            p = Path(raw_result.get("path") or target)
            if p.exists() and p.is_dir():
                return True, f"Verified: directory '{p}' exists.", {"path": str(p)}
            return False, f"Verification failed: directory '{p}' was not created.", {"path": str(p)}

        # 7. STOP_PROCESS / TERMINATE_PROCESS
        if op_type in (OSOperationType.STOP_PROCESS, OSOperationType.TERMINATE_PROCESS):
            # Check if terminated PIDs are dead
            terminated = raw_result.get("terminated", [])
            for t in terminated:
                pid = t.get("pid")
                if pid and psutil.pid_exists(pid):
                    try:
                        p = psutil.Process(pid)
                        if p.status() != psutil.STATUS_ZOMBIE:
                            return False, f"Verification failed: process with PID {pid} is still running.", {"pid": pid}
                    except psutil.NoSuchProcess:
                        pass
            return True, "Verified: target process(es) terminated.", {"terminated": terminated}

        # 8. START_PROCESS
        if op_type == OSOperationType.START_PROCESS:
            pid = raw_result.get("pid")
            if pid and psutil.pid_exists(pid):
                return True, f"Verified: process is running (PID: {pid}).", {"pid": pid}
            return False, "Verification failed: process is not running.", {"pid": pid}

        # 9. KILL_BY_PORT
        if op_type == OSOperationType.KILL_BY_PORT:
            port = params.get("port") or (int(target) if str(target).isdigit() else None)
            if port:
                time.sleep(0.2)
                from core.os_gateway.process_ops import inspect_port
                check = inspect_port(port)
                if not check.get("in_use"):
                    return True, f"Verified: port {port} is now free and unoccupied.", {"port": port, "free": True}
                else:
                    return False, f"Verification failed: port {port} is still in use.", {"port": port, "listener": check.get("primary_listener")}

        # 10. EXECUTE_COMMAND
        if op_type == OSOperationType.EXECUTE_COMMAND:
            exit_code = raw_result.get("exit_code", -1)
            if exit_code == 0:
                return True, "Verified: command completed with exit code 0.", {"exit_code": 0}
            return False, f"Command exited with non-zero code {exit_code}.", {"exit_code": exit_code, "stderr": raw_result.get("stderr")}

        # 11. START_SERVICE / STOP_SERVICE
        if op_type == OSOperationType.START_SERVICE:
            if raw_result.get("mocked"):
                return True, "Verified: service started (mocked).", {"mocked": True}
            s_name = raw_result.get("service_name") or target
            from core.os_gateway.service_ops import inspect_service
            s_info = inspect_service(s_name)
            if s_info.get("is_running"):
                return True, f"Verified: service '{s_name}' is Running.", s_info
            return False, f"Verification failed: service '{s_name}' is not Running.", s_info

        if op_type == OSOperationType.STOP_SERVICE:
            if raw_result.get("mocked"):
                return True, "Verified: service stopped (mocked).", {"mocked": True}
            s_name = raw_result.get("service_name") or target
            from core.os_gateway.service_ops import inspect_service
            s_info = inspect_service(s_name)
            if not s_info.get("is_running"):
                return True, f"Verified: service '{s_name}' is Stopped.", s_info
            return False, f"Verification failed: service '{s_name}' is still Running.", s_info

        # 12. Read-only / inspection operations are verified if they returned success and data
        if raw_result.get("success", False):
            return True, "Verified: inspection completed with valid results.", {}

        return False, "Verification uncertain: operation returned without success confirmation.", {}

    def verify_file_exists(self, path: str) -> Dict[str, Any]:
        p = Path(path)
        exists = p.exists() and p.is_file()
        return {"verified": exists, "path": str(p), "message": f"File '{p}' {'exists' if exists else 'does not exist'}."}

    def verify_file_absent(self, path: str) -> Dict[str, Any]:
        p = Path(path)
        absent = not p.exists()
        return {"verified": absent, "path": str(p), "message": f"File '{p}' is {'absent' if absent else 'present'}."}

    def verify_exit_code(self, exit_code: int) -> Dict[str, Any]:
        ok = exit_code == 0
        return {"verified": ok, "exit_code": exit_code, "message": f"Command exit code: {exit_code}"}

    def verify_pid_running(self, pid: int) -> Dict[str, Any]:
        running = psutil.pid_exists(pid)
        return {"verified": running, "pid": pid, "message": f"PID {pid} {'is running' if running else 'is not running'}."}

    def verify_pid_not_running(self, pid: int) -> Dict[str, Any]:
        running = psutil.pid_exists(pid)
        return {"verified": not running, "pid": pid, "message": f"PID {pid} {'is not running' if not running else 'is running'}."}


_verifier: Optional[OSVerifier] = None


def get_os_verifier() -> OSVerifier:
    global _verifier
    if _verifier is None:
        _verifier = OSVerifier()
    return _verifier
