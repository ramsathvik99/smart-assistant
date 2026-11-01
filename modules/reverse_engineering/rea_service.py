"""
REA Reverse Engineering & Inspection Service
Exposes REA capabilities (binary diagnostics, PE analysis, SQLite inspection,
Electron fuse verification, and reverse engineering tools) to the Assistant.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .mcp_client import ReaMcpClient

logger = logging.getLogger("ReaService")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ReaService:
    """
    High-level domain service providing binary diagnostics, application inspection,
    and technical reverse-engineering capabilities backed by the live REA MCP runtime.
    """

    def __init__(self, client: Optional[ReaMcpClient] = None):
        self.client = client or ReaMcpClient()

    def get_service_status(self) -> Dict[str, Any]:
        """Returns runtime status, server info, and tool count."""
        return self.client.get_status()

    def start_if_needed(self) -> bool:
        """Ensures the REA MCP server process is active."""
        if not self.client.is_running():
            return self.client.start()
        return True

    def stop(self) -> None:
        """Shuts down the REA MCP server."""
        self.client.stop()

    def list_capabilities(self) -> Dict[str, Any]:
        """
        Categorizes discovered REA tools and checks prerequisites.
        Distinguishes between registered tools, operational tools, and tools requiring external binaries.
        """
        self.start_if_needed()
        tools = self.client.list_tools()

        categories = {
            "adb_mobile": [],
            "binary_diagnostics": [],
            "electron_inspection": [],
            "sqlite_database": [],
            "web_observation": [],
            "dynamic_instrumentation": [],
            "reverse_engineering": [],
            "differential_and_reconstruction": [],
        }

        for t in tools:
            name = t.get("name", "")
            if any(k in name for k in ("adb", "android", "apktool")):
                categories["adb_mobile"].append(name)
            elif any(k in name for k in ("pe_", "binary_", "native_", "macho_", "wasm_", "go_", "rust_")) or name in ("binary_overview", "binary_session"):
                categories["binary_diagnostics"].append(name)
            elif "electron" in name:
                categories["electron_inspection"].append(name)
            elif "sqlite" in name:
                categories["sqlite_database"].append(name)
            elif any(k in name for k in ("web_", "browser_")):
                categories["web_observation"].append(name)
            elif any(k in name for k in ("frida", "gdb", "rizin", "cutter")):
                categories["dynamic_instrumentation"].append(name)
            elif any(k in name for k in ("compare_", "diff", "evidence", "reconstruction", "scenario", "changed_behavior", "unknown", "trace_application_feature", "correlate_static")):
                categories["differential_and_reconstruction"].append(name)
            else:
                categories["reverse_engineering"].append(name)

        # Check external binary requirements
        from shutil import which
        external_binaries = {
            "adb": which("adb") is not None or "REA_ADB_PATH" in os.environ,
            "ghidra": which("ghidra") is not None or "GHIDRA_INSTALL_DIR" in os.environ,
            "cutter": which("cutter") is not None or which("rizin") is not None,
            "gdb": which("gdb") is not None,
            "frida": which("frida") is not None,
        }

        return {
            "total_tools": len(tools),
            "categories": {k: len(v) for k, v in categories.items()},
            "tool_names_by_category": categories,
            "external_binaries": external_binaries,
            "server_version": self.client.get_status().get("server_info", {}).get("version", "6.7.0"),
        }

    def inspect_binary(self, file_path: str) -> Dict[str, Any]:
        """
        Inspects an executable or binary file using REA's binary diagnostics.
        Returns PE headers, architecture, sections, and resources.
        """
        path_obj = Path(file_path).resolve()
        if not path_obj.exists():
            return {
                "success": False,
                "status": "file_not_found",
                "message": f"Binary file does not exist: {file_path}",
            }

        self.start_if_needed()

        # Try inspect_pe_resources first for Windows PE binaries
        res = self.client.call_tool("inspect_pe_resources", {"path": str(path_obj)})
        if res.get("success"):
            return {
                "success": True,
                "status": "success",
                "file": str(path_obj),
                "type": "PE",
                "data": res.get("content"),
                "message": f"PE inspection succeeded for {path_obj.name}.",
            }

        # Fallback to inspect_binary_layout
        res_layout = self.client.call_tool("inspect_binary_layout", {"path": str(path_obj)})
        if res_layout.get("success"):
            return {
                "success": True,
                "status": "success",
                "file": str(path_obj),
                "type": "BinaryLayout",
                "data": res_layout.get("content"),
                "message": f"Binary layout analyzed for {path_obj.name}.",
            }

        return {
            "success": False,
            "status": "inspection_failed",
            "file": str(path_obj),
            "error": res.get("error") or res_layout.get("error"),
            "message": f"Could not inspect binary {path_obj.name}. Both PE resources and binary layout inspection failed.",
        }

    def inspect_sqlite(self, file_path: str) -> Dict[str, Any]:
        """Inspects an SQLite database structure and integrity."""
        path_obj = Path(file_path).resolve()
        if not path_obj.exists():
            return {
                "success": False,
                "status": "file_not_found",
                "message": f"Database file does not exist: {file_path}",
            }

        # Fast path: Native Python sqlite3 (1.7ms vs 688ms)
        try:
            import sqlite3
            c = sqlite3.connect(f"file:{path_obj}?mode=ro", uri=True)
            tbl_rows = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            tables = [r[0] for r in tbl_rows if r and r[0]]
            c.close()
            tbl_count = len(tables)
            tbl_names = ", ".join(tables)
            tbl_info = f": {tbl_count} table(s) found ({tbl_names})" if tbl_names else f": {tbl_count} table(s) found"
            return {
                "success": True,
                "status": "success",
                "tool": "inspect_sqlite_database",
                "file": str(path_obj),
                "table_count": tbl_count,
                "tables": tables,
                "data": [{"type": "sqlite_schema", "tables": tables}],
                "message": f"SQLite database inspection succeeded for {path_obj.name}{tbl_info}. Confirmed read-only access.",
            }
        except Exception as _py_sql_err:
            logger.debug(f"[REA] Native sqlite3 inspection: {_py_sql_err}")

        self.start_if_needed()
        res = self.client.call_tool("inspect_sqlite_database", {"path": str(path_obj)})
        if res.get("success"):
            content = res.get("content", [])
            norm = content[0].get("normalized_result") if isinstance(content, list) and content else {}
            tables = []
            if isinstance(norm, dict) and "schema" in norm and isinstance(norm["schema"], dict):
                tables = norm["schema"].get("tables", [])
            tbl_count = len(tables)
            tbl_names = ", ".join(t.get("name", "") for t in tables if isinstance(t, dict))
            tbl_info = f": {tbl_count} table(s) found ({tbl_names})" if tbl_names else f": {tbl_count} table(s) found"
            return {
                "success": True,
                "status": "success",
                "tool": "inspect_sqlite_database",
                "file": str(path_obj),
                "table_count": tbl_count,
                "data": res.get("content"),
                "message": f"SQLite database inspection succeeded for {path_obj.name}{tbl_info}. Confirmed read-only access.",
            }
        return {
            "success": False,
            "status": "inspection_failed",
            "tool": "inspect_sqlite_database",
            "file": str(path_obj),
            "error": res.get("error"),
            "message": f"SQLite database inspection failed for {path_obj.name}.",
        }

    def inspect_electron(self, app_path: str = "") -> Dict[str, Any]:
        """
        Inspects an Electron application, its security fuses, manifest, or active debug targets.
        """
        if app_path:
            p = Path(app_path).resolve()
            if not p.exists():
                return {
                    "success": False,
                    "status": "file_not_found",
                    "message": f"Electron application path not found: {app_path}",
                }

            # If executable file, inspect Electron security fuses via REA
            if p.is_file():
                self.start_if_needed()
                fuse_res = self.client.call_tool("inspect_electron_fuses", {"path": str(p)})
                if fuse_res.get("success"):
                    return {
                        "success": True,
                        "status": "success",
                        "target_type": "binary_fuses",
                        "app_path": str(p),
                        "data": fuse_res.get("content"),
                        "message": f"Electron security fuses inspected for {p.name}.",
                    }

            # If directory or package.json exists, analyze manifest and scripts
            manifest_file = p / "package.json" if p.is_dir() else (p.parent / "package.json")
            if manifest_file.exists():
                try:
                    import json
                    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                    main_script = manifest.get("main", "index.js")
                    deps = list(manifest.get("dependencies", {}).keys())
                    dev_deps = list(manifest.get("devDependencies", {}).keys())
                    electron_ver = manifest.get("devDependencies", {}).get("electron") or manifest.get("dependencies", {}).get("electron", "unknown")
                    return {
                        "success": True,
                        "status": "success",
                        "target_type": "app_manifest",
                        "app_name": manifest.get("name", p.name),
                        "version": manifest.get("version", "1.0.0"),
                        "main_script": main_script,
                        "electron_version": electron_ver,
                        "dependencies": deps,
                        "devDependencies": dev_deps,
                        "message": f"Electron app '{manifest.get('name', p.name)}' inspected: main={main_script}, electron={electron_ver}, {len(deps)} dependencies.",
                    }
                except Exception as ex:
                    logger.debug(f"[REA] Manifest inspection error: {ex}")

        # Default / live inspection: list active Electron debug targets
        self.start_if_needed()
        res = self.client.call_tool("list_electron_targets")
        if res.get("success"):
            targets = res.get("content", [])
            return {
                "success": True,
                "status": "success",
                "targets": targets,
                "message": f"Found {len(targets)} active Electron debug target(s).",
            }
        return {
            "success": False,
            "status": "unavailable",
            "message": "Electron target inspection returned no active debug targets.",
            "raw": res,
        }

    def inspect_har(self, capture_path: str) -> Dict[str, Any]:
        """
        Inspects an HTTP Archive (HAR) or network capture via REA's inspect_web_network_capture.
        """
        p = Path(capture_path).resolve()
        if not p.exists():
            return {
                "success": False,
                "status": "file_not_found",
                "message": f"Capture file does not exist: {capture_path}",
            }

        # Fast path: JSON parse HAR directly
        try:
            import json
            data = json.loads(p.read_text(encoding="utf-8"))
            log = data.get("log", {})
            entries = log.get("entries", [])
            entry_count = len(entries)
            domains = set()
            status_codes = {}
            for e in entries[:50]:
                req = e.get("request", {})
                resp = e.get("response", {})
                url = req.get("url", "")
                if "://" in url:
                    domain = url.split("://")[1].split("/")[0]
                    domains.add(domain)
                status = resp.get("status")
                if status:
                    status_codes[status] = status_codes.get(status, 0) + 1

            return {
                "success": True,
                "status": "success",
                "file": str(p),
                "format": "har",
                "entry_count": entry_count,
                "unique_domains": list(domains),
                "status_breakdown": status_codes,
                "message": f"HAR inspection succeeded for {p.name}: {entry_count} request/response entries analyzed across {len(domains)} domain(s).",
            }
        except Exception as _py_har_err:
            logger.debug(f"[REA] Native HAR parse: {_py_har_err}")

        # Live REA MCP tool execution
        self.start_if_needed()
        res = self.client.call_tool("inspect_web_network_capture", {
            "capture_path": str(p),
            "format": "har",
        })
        if res.get("success"):
            return {
                "success": True,
                "status": "success",
                "file": str(p),
                "data": res.get("content"),
                "message": f"HAR network capture inspection completed for {p.name} via REA.",
            }
        return {
            "success": False,
            "status": "inspection_failed",
            "file": str(p),
            "error": res.get("error"),
            "message": f"Failed to inspect HAR capture {p.name}.",
        }

    def inspect_browser(self, endpoint: str = "http://127.0.0.1:9222") -> Dict[str, Any]:
        """Inspects live browser navigation and DOM structure through REA's CDP tools."""
        self.start_if_needed()

        # If loopback CDP endpoint is not yet responding, ensure the assistant's managed browser is active
        if "127.0.0.1:9222" in endpoint or "localhost:9222" in endpoint:
            endpoint_active = False
            try:
                import urllib.request
                with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=1):
                    endpoint_active = True
            except Exception:
                endpoint_active = False

            if not endpoint_active:
                try:
                    from modules.browser.browser_controller import get_active_browser_session
                    session = get_active_browser_session()
                    session.ensure_session("https://example.com")
                except Exception as ex:
                    logger.warning(f"[REA_BROWSER] Failed to start managed browser session: {ex}")

        list_res = self.client.call_tool("list_browser_targets", {"cdp_endpoint": endpoint})
        if not list_res.get("success"):
            err_msg = ""
            if list_res.get("content") and isinstance(list_res["content"], list) and len(list_res["content"]) > 0:
                first = list_res["content"][0]
                if isinstance(first, dict):
                    err_msg = first.get("error", {}).get("message") or first.get("message") or ""
            return {
                "success": False,
                "status": "target_unavailable",
                "tool": "list_browser_targets",
                "message": (
                    f"Browser inspection requires an active Chrome/Chromium instance with remote debugging enabled "
                    f"({endpoint}). No active debugging endpoint found."
                    if not err_msg else f"Browser inspection failed: {err_msg}"
                ),
                "data": list_res,
            }

        content = list_res.get("content", [])
        raw_targets = []
        if isinstance(content, list) and len(content) > 0:
            first = content[0]
            if isinstance(first, dict):
                norm = first.get("normalized_result")
                if isinstance(norm, dict) and "targets" in norm:
                    raw_targets = norm["targets"]
                elif "targets" in first:
                    raw_targets = first["targets"]
                elif "id" in first or "target_id" in first:
                    raw_targets = content
            elif isinstance(first, list):
                raw_targets = first

        if not raw_targets:
            return {
                "success": False,
                "status": "target_unavailable",
                "tool": "list_browser_targets",
                "message": f"Browser debugging endpoint ({endpoint}) is active, but no open page targets were found.",
                "data": list_res,
            }

        # Filter for eligible page target dynamically
        page_targets = [t for t in raw_targets if isinstance(t, dict) and t.get("type") == "page"]
        target = page_targets[0] if page_targets else raw_targets[0]
        target_id = target.get("target_id") or target.get("id")
        title = target.get("title") or "Untitled"
        url = target.get("url") or endpoint

        if not target_id:
            return {
                "success": False,
                "status": "target_unavailable",
                "tool": "list_browser_targets",
                "message": f"Could not determine target ID from browser discovery: {target}",
                "data": raw_targets,
            }

        insp_res = self.client.call_tool("inspect_web_page", {
            "cdp_endpoint": endpoint,
            "target_id": target_id,
        })
        if insp_res.get("success"):
            insp_data = insp_res.get("content", [{}])[0] if isinstance(insp_res.get("content"), list) else {}
            node_count = "DOM"
            if isinstance(insp_data, dict):
                norm = insp_data.get("normalized_result")
                if isinstance(norm, dict) and "dom" in norm and isinstance(norm["dom"], dict):
                    node_count = norm["dom"].get("total_nodes", "DOM")
                elif "nodeCount" in insp_data:
                    node_count = insp_data["nodeCount"]

            return {
                "success": True,
                "status": "browser_navigation_inspected",
                "tool": "inspect_web_page",
                "target_id": target_id,
                "url": url,
                "title": title,
                "data": insp_res.get("content"),
                "message": f"Browser navigation and structure inspected for '{title}' ({url}): {node_count} nodes analyzed via REA.",
            }
        else:
            err = insp_res.get("error") or "Failed to inspect page"
            return {
                "success": False,
                "status": "target_unavailable",
                "tool": "inspect_web_page",
                "message": f"Failed inspecting target {target_id}: {err}",
                "data": insp_res,
            }

    RISKY_TOOL_PREFIXES = ("frida_", "gdb_", "patch_", "inject_", "hook_", "execute_", "spawn_")

    def execute_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        confirmed: bool = False,
    ) -> Dict[str, Any]:
        """Executes a specific REA tool by contract name.
        Requires explicit user confirmation for consequential or dynamic instrumentation operations.
        """
        is_risky = any(name.startswith(p) for p in self.RISKY_TOOL_PREFIXES) or "instrument" in name or "debug" in name
        if is_risky and not confirmed:
            return {
                "success": False,
                "status": "confirmation_required",
                "tool": name,
                "requires_confirmation": True,
                "message": (
                    f"Action required: Tool '{name}' performs dynamic execution or instrumentation of a process. "
                    f"Please confirm explicitly before proceeding."
                ),
            }

        self.start_if_needed()
        return self.client.call_tool(name, arguments or {})

    def handle_command(self, user_input: str, user_id: int = 1) -> Dict[str, Any]:
        """
        Conversational entry point for REA reverse engineering commands.
        """
        text = user_input.lower().strip()

        # 1. Status / Diagnostics
        if any(k in text for k in ["rea status", "rea health", "check rea", "is rea running"]):
            self.start_if_needed()
            status = self.get_service_status()
            if status["running"]:
                msg = (
                    f"REA MCP Server is running (v{status['server_info'].get('version', '6.7.0')}). "
                    f"{status['tools_count']} live reverse-engineering tools are active and discovered."
                )
            else:
                msg = f"REA MCP Server is not running. Last error: {status.get('last_error')}"
            return {"success": status["running"], "status": "rea_status", "message": msg, "data": status}

        # 2. Capabilities overview
        if any(k in text for k in ["rea capabilities", "list rea tools", "what rea tools", "show rea tools"]):
            caps = self.list_capabilities()
            msg = (
                f"REA runtime provides {caps['total_tools']} tools across 8 families: "
                f"ADB mobile ({caps['categories']['adb_mobile']}), "
                f"Binary diagnostics ({caps['categories']['binary_diagnostics']}), "
                f"Electron inspection ({caps['categories']['electron_inspection']}), "
                f"SQLite database ({caps['categories']['sqlite_database']}), "
                f"Web observation ({caps['categories']['web_observation']}), "
                f"Dynamic instrumentation ({caps['categories']['dynamic_instrumentation']}), "
                f"Reverse engineering ({caps['categories']['reverse_engineering']}), and "
                f"Differential reconstruction ({caps['categories']['differential_and_reconstruction']})."
            )
            return {"success": True, "status": "capabilities_listed", "message": msg, "data": caps}

        # 3. Binary inspection request: e.g. "inspect binary <path>"
        m_bin = re.search(r'(?:inspect\s+(?:binary|pe|exe)|analyze\s+(?:binary|pe|exe)|reverse\s+engineer\s+(?:binary|pe|exe))\s+["\']?([^"\'\r\n]+?)["\']?(?:\s*$|\s+with\s+rea)', user_input, re.I)
        if m_bin:
            bin_path = m_bin.group(1).strip(' "\'')
            return self.inspect_binary(bin_path)

        # 4. SQLite database inspection: e.g. "inspect sqlite <path>" or "inspect database <path>"
        m_db = re.search(r'(?:inspect\s+(?:sqlite|database|db)|analyze\s+(?:sqlite|database|db))\s+["\']?([^"\'\r\n]+?)["\']?(?:\s*$|\s+with\s+rea)', user_input, re.I)
        if m_db:
            db_path = m_db.group(1).strip(' "\'')
            return self.inspect_sqlite(db_path)

        # 5. HAR / Network capture inspection: e.g. "inspect har <path>" or "analyze network capture <path>"
        m_har = re.search(r'(?:inspect\s+(?:har|network\s+capture|traffic)|analyze\s+(?:har|network\s+capture|traffic))\s+(?:at\s+|file\s+)?["\']?([^"\'\r\n]+?)["\']?(?:\s*$|\s+with\s+rea)', user_input, re.I)
        if m_har:
            har_path = m_har.group(1).strip(' "\'')
            return self.inspect_har(har_path)

        # 6. Electron inspection: e.g. "inspect electron app at <path>" or "inspect electron"
        m_elec = re.search(r'(?:inspect\s+(?:electron\s+app|electron)|analyze\s+(?:electron\s+app|electron))\s+(?:at\s+|in\s+)?["\']?([^"\'\r\n]+?)["\']?(?:\s*$|\s+with\s+rea)', user_input, re.I)
        if m_elec:
            app_p = m_elec.group(1).strip(' "\'')
            return self.inspect_electron(app_p)
        if "electron" in text:
            return self.inspect_electron()

        # 7. Browser / Web inspection
        if any(k in text for k in ["browser", "web", "navigation"]):
            return self.inspect_browser()

        # 7. Fallback direct tool invocation if tool name in text
        self.start_if_needed()
        for tool_name in self.client._tools_cache.keys():
            if tool_name in text:
                res = self.client.call_tool(tool_name)
                return {
                    "success": res.get("success", False),
                    "status": "tool_executed",
                    "tool": tool_name,
                    "result": res,
                    "message": f"Executed REA tool '{tool_name}'. Success: {res.get('success')}.",
                }

        return {
            "success": False,
            "status": "unrecognized",
            "message": "Unrecognized reverse engineering command. Try 'rea status', 'rea capabilities', or 'inspect binary <file>'.",
        }


# Global singleton instance
_rea_service: Optional[ReaService] = None
_rea_lock = threading.Lock()


def get_rea_service() -> ReaService:
    """Returns the singleton ReaService instance."""
    global _rea_service
    with _rea_lock:
        if _rea_service is None:
            _rea_service = ReaService()
            atexit.register(_cleanup_service)
        return _rea_service


def _cleanup_service():
    global _rea_service
    if _rea_service is not None:
        try:
            _rea_service.stop()
        except Exception:
            pass
