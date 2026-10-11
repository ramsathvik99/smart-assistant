"""
Universal OS Operations — Shell and Terminal Controller
Provides first-class execution and management of shells and command interpreters:
- PowerShell (Windows PowerShell & PowerShell Core)
- Command Prompt (CMD)
- Git Bash (where installed)
- WSL (where installed/configured)
- Python interpreter
- Interactive terminal launches and background process monitoring
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ShellExecutor:
    """
    Executes commands across supported shells with synchronous capture,
    asynchronous background process tracking, and terminal launching.
    """

    def __init__(self):
        self._background_processes: Dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def detect_available_shells(self) -> Dict[str, Optional[str]]:
        """Detect installed shells and interpreters."""
        shells: Dict[str, Optional[str]] = {
            "cmd": shutil.which("cmd.exe") or "cmd.exe",
            "powershell": shutil.which("powershell.exe") or "powershell.exe",
            "pwsh": shutil.which("pwsh.exe"),
            "python": sys.executable,
            "wsl": shutil.which("wsl.exe"),
            "git_bash": None,
            "windows_terminal": shutil.which("wt.exe"),
        }

        # Check typical Git Bash installation paths
        git_bash_paths = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
        ]
        for gp in git_bash_paths:
            if os.path.exists(gp):
                shells["git_bash"] = gp
                break

        return shells

    def execute_command(
        self,
        command: str,
        shell_type: str = "powershell",
        cwd: Optional[str] = None,
        timeout: float = 30.0,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Executes a command synchronously and captures stdout, stderr, exit code, and PID.
        """
        if not command or not command.strip():
            return {
                "success": False,
                "status": "error",
                "exit_code": -1,
                "stdout": "",
                "stderr": "Command is empty.",
                "message": "Empty command provided.",
            }

        cmd_clean = command.strip()
        shells = self.detect_available_shells()
        working_dir = cwd if cwd and os.path.isdir(cwd) else os.getcwd()

        effective_env = os.environ.copy()
        if env:
            effective_env.update(env)

        # Build execution args based on shell_type
        norm_shell = shell_type.lower()
        if norm_shell in ("powershell", "ps"):
            ps_exe = shells.get("pwsh") or shells.get("powershell") or "powershell.exe"
            args = [ps_exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd_clean]
        elif norm_shell == "cmd":
            cmd_exe = shells.get("cmd") or "cmd.exe"
            args = [cmd_exe, "/C", cmd_clean]
        elif norm_shell == "git_bash" or norm_shell == "bash":
            bash_exe = shells.get("git_bash") or shutil.which("bash.exe")
            if not bash_exe:
                return {
                    "success": False,
                    "status": "error",
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "Git Bash is not installed or not found in standard paths.",
                    "message": "Git Bash is not installed.",
                }
            args = [bash_exe, "-c", cmd_clean]
        elif norm_shell == "wsl":
            wsl_exe = shells.get("wsl")
            if not wsl_exe:
                return {
                    "success": False,
                    "status": "error",
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "WSL is not installed or enabled on this system.",
                    "message": "WSL is not available.",
                }
            args = [wsl_exe, "-e", "bash", "-c", cmd_clean]
        elif norm_shell == "python":
            py_exe = shells.get("python") or sys.executable
            args = [py_exe, "-c", cmd_clean]
        else:
            # Fallback to PowerShell
            ps_exe = shells.get("powershell") or "powershell.exe"
            args = [ps_exe, "-NoProfile", "-NonInteractive", "-Command", cmd_clean]

        start_time = time.time()
        try:
            proc = subprocess.Popen(
                args,
                cwd=working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=effective_env,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                return {
                    "success": False,
                    "status": "timeout",
                    "exit_code": -1,
                    "stdout": stdout or "",
                    "stderr": f"Command timed out after {timeout} seconds.",
                    "message": f"Command timed out after {timeout}s.",
                    "pid": proc.pid,
                    "duration": round(time.time() - start_time, 2),
                }

            is_success = (exit_code == 0)
            msg = f"Command executed successfully (exit code 0)." if is_success else f"Command failed with exit code {exit_code}."

            return {
                "success": is_success,
                "status": "success" if is_success else "error",
                "exit_code": exit_code,
                "stdout": stdout or "",
                "stderr": stderr or "",
                "pid": proc.pid,
                "duration": round(time.time() - start_time, 2),
                "shell": norm_shell,
                "cwd": working_dir,
                "message": msg,
            }

        except Exception as exc:
            logger.error(f"[SHELL_EXECUTOR] Execution error: {exc}")
            return {
                "success": False,
                "status": "error",
                "exit_code": -1,
                "stdout": "",
                "stderr": str(exc),
                "message": f"Failed to execute command: {exc}",
                "cwd": working_dir,
            }

    def run_command(
        self,
        command: str,
        shell_type: str = "powershell",
        cwd: Optional[str] = None,
        timeout: float = 30.0,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Alias for execute_command matching test conventions."""
        return self.execute_command(command=command, shell_type=shell_type, cwd=cwd, timeout=timeout, env=env)

    def start_background_process(
        self,
        command: str,
        process_id_key: str,
        shell_type: str = "powershell",
        cwd: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Starts a long-running process in the background and tracks it.
        """
        working_dir = cwd if cwd and os.path.isdir(cwd) else os.getcwd()
        shells = self.detect_available_shells()

        if shell_type.lower() == "cmd":
            args = [shells.get("cmd") or "cmd.exe", "/C", command]
        else:
            ps_exe = shells.get("powershell") or "powershell.exe"
            args = [ps_exe, "-NoProfile", "-Command", command]

        try:
            proc = subprocess.Popen(
                args,
                cwd=working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )

            with self._lock:
                self._background_processes[process_id_key] = proc

            return {
                "success": True,
                "status": "running",
                "pid": proc.pid,
                "process_key": process_id_key,
                "cwd": working_dir,
                "message": f"Started background process '{process_id_key}' (PID: {proc.pid}).",
            }
        except Exception as exc:
            return {
                "success": False,
                "status": "error",
                "error": str(exc),
                "message": f"Failed to start background process: {exc}",
            }

    def terminate_background_process(self, process_id_key: str) -> Dict[str, Any]:
        """Terminates a previously started background process."""
        with self._lock:
            proc = self._background_processes.get(process_id_key)
            if not proc:
                return {
                    "success": False,
                    "status": "error",
                    "message": f"No background process found with key '{process_id_key}'.",
                }

            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

                del self._background_processes[process_id_key]
                return {
                    "success": True,
                    "status": "terminated",
                    "pid": proc.pid,
                    "message": f"Terminated process '{process_id_key}' (PID: {proc.pid}).",
                }
            except Exception as exc:
                return {
                    "success": False,
                    "status": "error",
                    "message": f"Could not terminate process '{process_id_key}': {exc}",
                }

    def open_terminal_window(
        self,
        cwd: Optional[str] = None,
        shell_type: str = "powershell",
        command_to_run: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Launches an interactive desktop terminal window for the user
        (Windows Terminal, PowerShell, or CMD).
        """
        working_dir = cwd if cwd and os.path.isdir(cwd) else os.getcwd()
        shells = self.detect_available_shells()

        # Try Windows Terminal (wt.exe) first
        wt_exe = shells.get("windows_terminal")
        if wt_exe:
            args = [wt_exe, "-d", working_dir]
            if command_to_run:
                args.extend(["powershell", "-NoExit", "-Command", command_to_run])
            try:
                subprocess.Popen(args)
                return {
                    "success": True,
                    "status": "opened",
                    "terminal": "Windows Terminal",
                    "cwd": working_dir,
                    "message": f"Opened Windows Terminal at {working_dir}.",
                }
            except Exception:
                pass

        # Fallback to standalone PowerShell or CMD window
        if shell_type.lower() == "cmd":
            args = ["cmd.exe", "/K"]
            if command_to_run:
                args.append(command_to_run)
        else:
            args = ["powershell.exe", "-NoExit"]
            if command_to_run:
                args.extend(["-Command", command_to_run])

        try:
            subprocess.Popen(
                args,
                cwd=working_dir,
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
            )
            return {
                "success": True,
                "status": "opened",
                "terminal": shell_type,
                "cwd": working_dir,
                "message": f"Opened {shell_type} at {working_dir}.",
            }
        except Exception as exc:
            return {
                "success": False,
                "status": "error",
                "message": f"Failed to open terminal window: {exc}",
            }


_shell_executor: Optional[ShellExecutor] = None


def get_shell_executor() -> ShellExecutor:
    global _shell_executor
    if _shell_executor is None:
        _shell_executor = ShellExecutor()
    return _shell_executor
