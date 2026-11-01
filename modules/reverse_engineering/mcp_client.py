"""
REA MCP Client
Thread-safe JSON-RPC 2.0 stdio client for the original REA Node.js MCP server.
Provides process lifecycle management, dynamic tool discovery, and structured execution.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ReaMcpClient")

def _get_project_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent

PROJECT_ROOT = _get_project_root()
DEFAULT_RUNTIME_DIR = PROJECT_ROOT / "modules" / "reverse_engineering" / "rea_runtime"
DEFAULT_SCRIPT_PATH = DEFAULT_RUNTIME_DIR / "scripts" / "rea.mjs"


class ReaMcpClient:
    """
    Manages communication with the REA Node.js MCP server process.
    Supports lazy startup, synchronized request/response cycles, and clean shutdown.
    """

    def __init__(self, runtime_dir: Optional[Path] = None):
        self.runtime_dir = runtime_dir or (
            Path(sys._MEIPASS) / "modules" / "reverse_engineering" / "rea_runtime"
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
            else DEFAULT_RUNTIME_DIR
        )
        self.script_path = self.runtime_dir / "scripts" / "rea.mjs"
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._tools_cache: Dict[str, Dict[str, Any]] = {}
        self._server_info: Dict[str, Any] = {}
        self._protocol_version: str = ""
        self._initialized = False
        self._last_error: Optional[str] = None
        self._start_time: Optional[float] = None
        atexit.register(self.stop)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def _locate_node(self) -> str:
        """Locates a compatible Node.js 24.15+ or 26+ runtime."""
        custom_node = os.environ.get("REA_NODE_PATH")
        if custom_node and Path(custom_node).is_file():
            return custom_node

        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            mei_node = Path(sys._MEIPASS) / "modules" / "reverse_engineering" / "bin" / ("node.exe" if os.name == "nt" else "node")
            if mei_node.is_file():
                return str(mei_node)

        local_node = Path(__file__).parent / "bin" / ("node.exe" if os.name == "nt" else "node")
        if local_node.is_file():
            return str(local_node)

        return "node"

    def start(self) -> bool:
        """Starts the REA MCP server process and performs the initialization handshake."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return True

            if not self.script_path.exists():
                self._last_error = f"REA entry point not found at {self.script_path}"
                logger.error(self._last_error)
                return False

            compiled_entry = self.runtime_dir / "dist" / "mcp" / "main.js"
            if not compiled_entry.exists():
                self._last_error = f"Compiled REA runtime not found at {compiled_entry}"
                logger.error(self._last_error)
                return False

            try:
                logger.info(f"Starting REA MCP server from {self.runtime_dir}")
                proc_env = os.environ.copy()
                if "REA_ADB_PATH" not in proc_env:
                    from skills.device_management.adb_adapter import AdbAdapter
                    detected_adb = AdbAdapter()._adb_path
                    if detected_adb:
                        proc_env["REA_ADB_PATH"] = detected_adb

                node_bin = self._locate_node()
                self._proc = subprocess.Popen(
                    [node_bin, str(self.script_path), "--mcp"],
                    cwd=str(self.runtime_dir),
                    env=proc_env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self._start_time = time.time()
                self._initialized = False
                self._tools_cache.clear()

                # Step 1: Send initialize request
                init_id = self._next_id()
                init_payload = {
                    "jsonrpc": "2.0",
                    "id": init_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "SmartAssistant",
                            "version": "1.0.0",
                        },
                    },
                }
                self._write_message_locked(init_payload)
                resp = self._read_message_locked(timeout=10.0)
                if not resp or resp.get("id") != init_id:
                    self._last_error = f"Handshake failed: {resp}"
                    logger.error(self._last_error)
                    self._terminate_proc_locked()
                    return False

                result = resp.get("result", {})
                self._server_info = result.get("serverInfo", {})
                self._protocol_version = result.get("protocolVersion", "")

                # Step 2: Send initialized notification
                notif = {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }
                self._write_message_locked(notif)
                self._initialized = True

                # Step 3: Discover tools
                self._refresh_tools_locked()
                logger.info(
                    f"REA MCP server ready (v{self._server_info.get('version')}). Discovered {len(self._tools_cache)} tools."
                )
                return True

            except Exception as e:
                self._last_error = f"Failed to start REA process: {e}"
                logger.error(self._last_error, exc_info=True)
                self._terminate_proc_locked()
                return False

    def stop(self) -> None:
        """Stops the REA server process gracefully."""
        with self._lock:
            self._terminate_proc_locked()

    def _terminate_proc_locked(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        self._initialized = False

    def _write_message_locked(self, msg: Dict[str, Any]) -> None:
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("REA MCP stdin stream is not active")
        line = (json.dumps(msg) + "\n").encode("utf-8")
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

    def _read_message_locked(self, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        if not self._proc or not self._proc.stdout:
            raise RuntimeError("REA MCP stdout stream is not active")
        import queue
        line_queue: queue.Queue = queue.Queue()

        def _reader():
            try:
                line = self._proc.stdout.readline()
                line_queue.put(line)
            except Exception as ex:
                line_queue.put(ex)

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        try:
            res = line_queue.get(timeout=max(0.5, float(timeout)))
            if isinstance(res, Exception):
                logger.error(f"Error reading REA stdout: {res}")
                return None
            if not res:
                return None
            if isinstance(res, bytes):
                res = res.decode("utf-8", errors="replace")
            return json.loads(res.strip())
        except queue.Empty:
            logger.warning(f"REA MCP read timed out after {timeout:.1f}s")
            return None
        except Exception as e:
            logger.error(f"Error parsing REA JSON response: {e}")
            return None

    def _refresh_tools_locked(self) -> None:
        req_id = self._next_id()
        tools_req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/list",
            "params": {},
        }
        self._write_message_locked(tools_req)
        resp = self._read_message_locked(timeout=10.0)
        if resp and "result" in resp:
            tools = resp["result"].get("tools", [])
            self._tools_cache = {t["name"]: t for t in tools if "name" in t}

    def list_tools(self) -> List[Dict[str, Any]]:
        """Returns all tools discovered from the running server."""
        if not self.is_running():
            if not self.start():
                return []
        with self._lock:
            return list(self._tools_cache.values())

    def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        """Returns metadata for a specific tool if registered."""
        if not self.is_running():
            if not self.start():
                return None
        with self._lock:
            return self._tools_cache.get(name)

    def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """
        Calls an MCP tool by name with arguments.
        Returns structured results, content, and error state.
        """
        if not self.is_running():
            if not self.start():
                return {
                    "success": False,
                    "isError": True,
                    "error": {
                        "code": "server_not_running",
                        "message": f"REA runtime unavailable: {self._last_error}",
                    },
                }

        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {},
            },
        }

        with self._lock:
            try:
                self._write_message_locked(payload)
                resp = self._read_message_locked(timeout=timeout)
                if not resp:
                    return {
                        "success": False,
                        "isError": True,
                        "error": {
                            "code": "empty_response",
                            "message": "REA server returned empty response",
                        },
                    }

                if "error" in resp:
                    return {
                        "success": False,
                        "isError": True,
                        "error": resp["error"],
                    }

                result = resp.get("result", {})
                is_error = result.get("isError", False)

                parsed_content = []
                for item in result.get("content", []):
                    if item.get("type") == "text":
                        text = item.get("text", "")
                        try:
                            parsed_content.append(json.loads(text))
                        except Exception:
                            parsed_content.append(text)
                    else:
                        parsed_content.append(item)

                return {
                    "success": not is_error,
                    "isError": is_error,
                    "content": parsed_content,
                    "raw_result": result,
                }

            except Exception as e:
                logger.error(f"Error calling REA tool '{name}': {e}", exc_info=True)
                return {
                    "success": False,
                    "isError": True,
                    "error": {
                        "code": "execution_failed",
                        "message": str(e),
                    },
                }

    def get_status(self) -> Dict[str, Any]:
        """Returns client and process status."""
        running = self.is_running()
        return {
            "running": running,
            "initialized": self._initialized,
            "server_info": self._server_info,
            "protocol_version": self._protocol_version,
            "tools_count": len(self._tools_cache),
            "pid": self._proc.pid if self._proc else None,
            "uptime_seconds": round(time.time() - self._start_time, 1)
            if self._start_time and running
            else 0,
            "last_error": self._last_error,
        }
