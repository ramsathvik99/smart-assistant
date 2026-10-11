"""
Base Adapter Interface for Environment Observation
All application-specific adapters implement this interface to extract
rich contextual state from active software and windows.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

from core.environment.models import EnvironmentState


class BaseEnvironmentAdapter(ABC):
    """
    Abstract base class for environment adapters.
    Adapters decode application-specific context using a preferred hierarchy:
    1. Application / API data
    2. Accessibility / UI tree
    3. Integration / Title decomposition
    4. OS / Window information
    5. Vision / OCR (optional fallback)
    """

    name: str = "base"
    app_category: str = "general"

    @abstractmethod
    def can_handle(self, app_name: str, window_info: Dict[str, Any]) -> bool:
        """Return True if this adapter can extract specialized state for the application."""
        pass

    @abstractmethod
    def extract_state(self, window_info: Dict[str, Any], hierarchy_level: int = 1) -> Optional[EnvironmentState]:
        """
        Extract rich EnvironmentState from the active window.
        hierarchy_level: 1 (API/Accessibility) to 4 (Basic OS/Window title).
        """
        pass

    def detect_action(
        self,
        before: EnvironmentState,
        after: EnvironmentState,
    ) -> Tuple[str, str, str]:
        """
        Detect meaningful action between two states of this application.
        Returns: (change_type, user_action, transition_summary)
        """
        if before.application != after.application:
            return (
                "APP_SWITCH",
                f"Switched application to {after.application.capitalize()}",
                f"Switched from {before.application} to {after.application}",
            )
        if before.window_title != after.window_title:
            return (
                "CONTENT_UPDATE",
                "Updated active window content",
                f"Content changed from '{before.window_title}' to '{after.window_title}'",
            )
        return (
            "NO_CHANGE",
            "No active change",
            "Environment state remained stable",
        )
