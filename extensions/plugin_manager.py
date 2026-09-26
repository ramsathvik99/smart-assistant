"""
Plugin Manager for Nova Assistant Extensions.
Provides standardized plugin registration, metadata validation, parameter checking,
isolated execution, and database auditing (plugin_logs / decision_logs).
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_DEFAULT_PARAMS = {"type": "OBJECT", "properties": {}, "required": []}


@dataclass
class PluginMetadata:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=lambda: dict(_DEFAULT_PARAMS))
    handler: Optional[Callable] = None
    file_path: str = ""
    is_valid: bool = False
    is_enabled: bool = True
    error_message: str = ""
    behavior: Optional[str] = None
    scheduling: Optional[str] = None


class PluginManager:
    """
    Central plugin manager supporting isolated execution and database logging.
    """

    def __init__(self, db_manager=None):
        self.db_manager = db_manager
        self._lock = threading.RLock()
        self._plugins: Dict[str, PluginMetadata] = {}

    def register_plugin(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        parameters: Optional[dict] = None,
        behavior: Optional[str] = None,
        scheduling: Optional[str] = None,
        file_path: str = "",
    ) -> bool:
        """Register an in-memory or loaded plugin handler."""
        if not _NAME_RE.match(name):
            logger.error(f"[PLUGIN_MANAGER] Invalid plugin name: '{name}'")
            return False

        params = parameters or dict(_DEFAULT_PARAMS)
        meta = PluginMetadata(
            name=name,
            description=description,
            parameters=params,
            handler=handler,
            file_path=file_path,
            is_valid=True,
            is_enabled=True,
            behavior=behavior,
            scheduling=scheduling,
        )

        with self._lock:
            self._plugins[name] = meta
        logger.info(f"[PLUGIN_MANAGER] Registered plugin '{name}'")
        return True

    def load_plugin_from_file(self, file_path: Path | str) -> Optional[PluginMetadata]:
        """Dynamically load and validate a plugin file conforming to the standard schema."""
        p = Path(file_path).resolve()
        if not p.is_file() or p.name.startswith("_") or not p.name.endswith(".py"):
            return None

        mod_name = f"nova_ext_plugin_{p.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, p)
            if not spec or not spec.loader:
                return None
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
        except Exception as e:
            logger.error(f"[PLUGIN_MANAGER] Failed to load plugin {p}: {e}")
            return None

        plugin_dict = getattr(mod, "PLUGIN", None)
        run_fn = getattr(mod, "run", None)

        if not isinstance(plugin_dict, dict) or not callable(run_fn):
            logger.warning(f"[PLUGIN_MANAGER] {p} missing 'PLUGIN' dict or 'run' function.")
            return None

        name = str(plugin_dict.get("name", p.stem)).strip()
        description = str(plugin_dict.get("description", "")).strip()
        parameters = plugin_dict.get("parameters", dict(_DEFAULT_PARAMS))

        meta = PluginMetadata(
            name=name,
            description=description,
            parameters=parameters,
            handler=run_fn,
            file_path=str(p),
            is_valid=True,
            is_enabled=True,
            behavior=plugin_dict.get("behavior"),
            scheduling=plugin_dict.get("scheduling"),
        )

        with self._lock:
            self._plugins[name] = meta
        return meta

    def discover_plugins(self, directory: Path | str) -> int:
        """Scan directory and load all valid plugins."""
        dir_path = Path(directory).resolve()
        if not dir_path.is_dir():
            return 0
        loaded = 0
        for py_file in dir_path.glob("*.py"):
            if not py_file.name.startswith("_"):
                if self.load_plugin_from_file(py_file):
                    loaded += 1
        return loaded

    def set_enabled(self, name: str, enabled: bool) -> bool:
        with self._lock:
            if name in self._plugins:
                self._plugins[name].is_enabled = bool(enabled)
                return True
        return False

    def is_enabled(self, name: str) -> bool:
        with self._lock:
            meta = self._plugins.get(name)
            return bool(meta and meta.is_valid and meta.is_enabled)

    def get_declarations(self) -> List[dict]:
        """Return tool declarations for active plugins."""
        with self._lock:
            decls = []
            for name, meta in self._plugins.items():
                if meta.is_valid and meta.is_enabled:
                    decls.append({
                        "name": meta.name,
                        "description": meta.description,
                        "parameters": meta.parameters,
                    })
            return decls

    def execute_plugin(
        self,
        name: str,
        parameters: Optional[dict] = None,
        user_id: Optional[int] = None,
        context: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Execute plugin handler with parameter validation, error containment,
        and database activity logging.
        """
        params = dict(parameters or {})
        with self._lock:
            meta = self._plugins.get(name)

        if not meta or not meta.is_valid:
            return {
                "success": False,
                "status": "not_found",
                "error": f"Plugin '{name}' is not registered or valid.",
                "result": None,
            }

        if not meta.is_enabled:
            return {
                "success": False,
                "status": "disabled",
                "error": f"Plugin '{name}' is currently disabled.",
                "result": None,
            }

        start_time = time.time()
        try:
            handler = meta.handler
            sig = inspect.signature(handler)
            kwargs = {}
            if "parameters" in sig.parameters:
                kwargs["parameters"] = params
            elif "params" in sig.parameters:
                kwargs["params"] = params
            elif "args" in sig.parameters:
                kwargs["args"] = params
            else:
                for p_name in sig.parameters:
                    if p_name in params:
                        kwargs[p_name] = params[p_name]

            if "context" in sig.parameters:
                kwargs["context"] = context or {}
            if "user_id" in sig.parameters:
                kwargs["user_id"] = user_id

            if not kwargs and len(sig.parameters) == 1:
                res = handler(params)
            else:
                res = handler(**kwargs)

            result_str = str(res) if res is not None else "Success"
            elapsed = time.time() - start_time

            # Log to DB if available
            if self.db_manager and user_id:
                try:
                    self.db_manager.log_command(
                        user_id=user_id,
                        command=f"plugin:{name}",
                        intent="PLUGIN_EXECUTION",
                        skill=name,
                        success=True,
                        response=result_str[:500],
                    )
                except Exception:
                    pass

            return {
                "success": True,
                "status": "executed",
                "result": res,
                "result_str": result_str,
                "elapsed_seconds": round(elapsed, 4),
            }

        except Exception as e:
            elapsed = time.time() - start_time
            err_msg = str(e)
            logger.error(f"[PLUGIN_MANAGER] Error executing plugin '{name}': {e}\n{traceback.format_exc()}")

            if self.db_manager and user_id:
                try:
                    self.db_manager.log_command(
                        user_id=user_id,
                        command=f"plugin:{name}",
                        intent="PLUGIN_EXECUTION",
                        skill=name,
                        success=False,
                        response=f"Error: {err_msg}"[:500],
                    )
                except Exception:
                    pass

            return {
                "success": False,
                "status": "error",
                "error": err_msg,
                "result": None,
                "elapsed_seconds": round(elapsed, 4),
            }


# Singleton instance
_plugin_manager = None

def get_plugin_manager(db_manager=None) -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager(db_manager=db_manager)
    return _plugin_manager
