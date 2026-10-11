"""
Environment Adapter Registry
Maintains an extensible registry of specialized application adapters.
Dispatches observation requests to the most specific matching adapter.

Priority system (two-pass):
  1. EXPLICIT APP_NAME mapping (highest priority, prevents BrowserAdapter from
     stealing Electron-based apps like VS Code that share Chrome window classes)
  2. can_handle() poll through ordered adapter list (fallback)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.environment.adapters.base_adapter import BaseEnvironmentAdapter
from core.environment.adapters.browser_adapter import BrowserEnvironmentAdapter
from core.environment.adapters.calculator_adapter import CalculatorEnvironmentAdapter
from core.environment.adapters.document_adapter import DocumentEnvironmentAdapter
from core.environment.adapters.explorer_adapter import ExplorerEnvironmentAdapter
from core.environment.adapters.generic_adapter import GenericEnvironmentAdapter
from core.environment.adapters.ide_adapter import IDEEnvironmentAdapter
from core.environment.adapters.media_adapter import MediaEnvironmentAdapter
from core.environment.adapters.terminal_adapter import TerminalEnvironmentAdapter
from core.environment.models import EnvironmentState

logger = logging.getLogger(__name__)

# ── Explicit app_name → adapter name mapping ──────────────────────────────────
# Prevents Electron apps (VSCode, Cursor, Obsidian, etc.) that share
# Chrome_WidgetWin_1 class names from being caught by BrowserAdapter.
# Keys should be lowercase normalized app names as returned by
# ContinuousEnvironmentObserver._infer_app_name().
_APP_NAME_TO_ADAPTER: Dict[str, str] = {
    # IDE / code editors
    "vscode": "ide",
    "code": "ide",
    "cursor": "ide",
    "pycharm": "ide",
    "intellij": "ide",
    "webstorm": "ide",
    "rider": "ide",
    "clion": "ide",
    "devenv": "ide",
    "sublime": "ide",
    "sublime_text": "ide",
    "notepad++": "ide",
    "atom": "ide",
    "eclipse": "ide",
    "obsidian": "ide",
    # Media
    "spotify": "media",
    "vlc": "media",
    "wmplayer": "media",
    "itunes": "media",
    "groove": "media",
    "musicbee": "media",
    "aimp": "media",
    # Browsers — explicit helps when app_name is set precisely
    "chrome": "browser",
    "brave": "browser",
    "msedge": "browser",
    "edge": "browser",
    "firefox": "browser",
    "opera": "browser",
    "vivaldi": "browser",
    "arc": "browser",
    "chromium": "browser",
    # YouTube (app_name may be normalized to 'youtube' by observer)
    "youtube": "browser",
    # File manager
    "explorer": "file_manager",
    "files": "file_manager",
    # Terminal
    "powershell": "terminal",
    "cmd": "terminal",
    "windowsterminal": "terminal",
    "wt": "terminal",
    "bash": "terminal",
    "conhost": "terminal",
    # Documents
    "acrobat": "document",
    "sumatrapdf": "document",
    "winword": "document",
    "excel": "document",
    "powerpnt": "document",
    "libreoffice": "document",
    "evince": "document",
    # Utilities
    "calculator": "calculator",
    "calc": "calculator",
}


class EnvironmentAdapterRegistry:
    """
    Registry for managing environment observation adapters.

    Two-pass dispatch:
      Pass 1: Check explicit app_name→adapter name map (prevents class-name conflicts)
      Pass 2: Fall through can_handle() ordered list
      Fallback: GenericEnvironmentAdapter
    """

    def __init__(self):
        self._adapters: List[BaseEnvironmentAdapter] = [
            # Ordered by specificity: more specific before more general
            IDEEnvironmentAdapter(),        # before browser — Electron apps share Chrome class
            MediaEnvironmentAdapter(),      # before browser — Spotify shares Chrome class on some setups
            DocumentEnvironmentAdapter(),
            ExplorerEnvironmentAdapter(),
            TerminalEnvironmentAdapter(),
            CalculatorEnvironmentAdapter(),
            BrowserEnvironmentAdapter(),    # broad — last in chain, after all specifics
        ]
        self._fallback_adapter = GenericEnvironmentAdapter()

        # Build name→instance map for O(1) explicit dispatch
        self._adapter_by_name: Dict[str, BaseEnvironmentAdapter] = {
            a.name: a for a in self._adapters
        }
        self._adapter_by_name["file_manager"] = self._adapters[4]  # ExplorerAdapter

    def register_adapter(self, adapter: BaseEnvironmentAdapter, prepend: bool = True):
        """Register a new custom or application-specific adapter."""
        if prepend:
            self._adapters.insert(0, adapter)
        else:
            self._adapters.append(adapter)
        self._adapter_by_name[adapter.name] = adapter

    def find_adapter(self, app_name: str, window_info: Dict[str, Any]) -> BaseEnvironmentAdapter:
        """
        Find the most appropriate adapter for the given application and window.

        Pass 1: Explicit app_name dispatch (prevents class-name collisions).
        Pass 2: can_handle() poll through ordered adapter list.
        """
        clean_app = (app_name or "").lower().strip()

        # Pass 1: explicit app_name map
        mapped_type = _APP_NAME_TO_ADAPTER.get(clean_app)
        if mapped_type and mapped_type in self._adapter_by_name:
            return self._adapter_by_name[mapped_type]

        # Pass 2: can_handle() poll
        for adapter in self._adapters:
            try:
                if adapter.can_handle(app_name, window_info):
                    return adapter
            except Exception as e:
                logger.debug("Adapter %s error during can_handle: %s", adapter.name, e)

        return self._fallback_adapter

    def extract_rich_state(
        self,
        app_name: str,
        window_info: Dict[str, Any],
        hierarchy_level: int = 1,
    ) -> EnvironmentState:
        """
        Extract rich environment state using the best matching adapter.
        Guaranteed to never fail or return None.
        """
        adapter = self.find_adapter(app_name, window_info)
        try:
            state = adapter.extract_state(window_info, hierarchy_level=hierarchy_level)
            if state is not None:
                return state
        except Exception as e:
            logger.warning("Adapter %s failed to extract state: %s", adapter.name, e)

        # Fallback to generic adapter
        try:
            return self._fallback_adapter.extract_state(window_info, hierarchy_level=hierarchy_level) or EnvironmentState()
        except Exception:
            return EnvironmentState(
                application=app_name or "unknown",
                window_title=window_info.get("title", ""),
                window_hwnd=window_info.get("hwnd", 0),
                window_pid=window_info.get("pid", 0),
            )


# Global singleton registry
adapter_registry = EnvironmentAdapterRegistry()


def get_adapter_registry() -> EnvironmentAdapterRegistry:
    return adapter_registry
