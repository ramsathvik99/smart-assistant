"""
Generic Environment Adapter (Universal Fallback)
Handles any observable application, software, game, or utility without a specialized adapter.
Extracts window hierarchy, cleaned titles, process information, and basic entities.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Optional, Tuple

from core.environment.adapters.base_adapter import BaseEnvironmentAdapter
from core.environment.models import EnvironmentState


class GenericEnvironmentAdapter(BaseEnvironmentAdapter):
    """
    Universal fallback adapter for any application.
    Extracts the most useful available state from window metadata and process info.
    """

    name = "generic"
    app_category = "general"

    def can_handle(self, app_name: str, window_info: Dict[str, Any]) -> bool:
        # Generic adapter can handle ANY window
        return True

    def extract_state(self, window_info: Dict[str, Any], hierarchy_level: int = 1) -> Optional[EnvironmentState]:
        title = (window_info.get("title") or "").strip()
        cls_name = (window_info.get("class_name") or "unknown").strip()
        pid = window_info.get("pid", 0)
        hwnd = window_info.get("hwnd", 0)

        # Infer readable application name
        app_name = "unknown"
        if " - " in title:
            # Many Windows apps format as "<Document/Page> - <Application Name>"
            parts = title.split(" - ")
            app_candidate = parts[-1].strip()
            if len(app_candidate) > 1 and not re.search(r'\.(exe|dll)$', app_candidate, re.IGNORECASE):
                app_name = app_candidate.lower()
        if app_name == "unknown" and cls_name:
            # Strip standard Windows class prefixes
            clean_cls = re.sub(r'^(?:windows\.|hwn_|wndclass_|class_)', '', cls_name, flags=re.IGNORECASE)
            app_name = clean_cls.split("_")[0].lower() if clean_cls else "unknown"

        entities: Dict[str, Any] = {
            "window_title": title,
            "class_name": cls_name,
            "raw_title": title,
        }

        # Sub-entity extraction
        if " - " in title:
            entities["sub_entity"] = title.split(" - ")[0].strip()

        if title and app_name and app_name != "unknown":
            content_ctx = f"Working in '{title}' ({app_name.capitalize()})"
        elif title:
            content_ctx = f"Active window: '{title}'"
        else:
            content_ctx = f"Application '{app_name}' is in the foreground"

        return EnvironmentState(
            timestamp=time.time(),
            application=app_name,
            window_title=title,
            window_hwnd=hwnd,
            window_pid=pid,
            process_name=f"{app_name}.exe",
            app_category="general",
            active_entities=entities,
            content_context=content_ctx,
            visible_text=title,
            user_action_summary=f"Interacting with {app_name.capitalize()}",
            source_tier="os_window",
            metadata={"class_name": cls_name},
        )

    def detect_action(
        self,
        before: EnvironmentState,
        after: EnvironmentState,
    ) -> Tuple[str, str, str]:
        if before.application != after.application:
            return (
                "APP_SWITCH",
                f"Switched application to {after.application.capitalize()}",
                f"Switched from {before.application} to {after.application}",
            )

        if before.window_title != after.window_title:
            return (
                "CONTENT_UPDATE",
                f"Switched view to '{after.window_title}'",
                f"Window title changed from '{before.window_title}' to '{after.window_title}'",
            )

        return ("NO_CHANGE", "No change", "Application state remained stable")
