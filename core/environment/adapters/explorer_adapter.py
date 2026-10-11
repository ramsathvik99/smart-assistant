"""
File Explorer Environment Adapter
Specialized observer for Windows File Explorer.
Extracts active folder name, path, and navigation context.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

from core.environment.adapters.base_adapter import BaseEnvironmentAdapter
from core.environment.models import EnvironmentState


class ExplorerEnvironmentAdapter(BaseEnvironmentAdapter):
    """
    Adapter for Windows File Explorer.
    Extracts active directory and navigation context.
    """

    name = "explorer"
    app_category = "file_manager"

    def can_handle(self, app_name: str, window_info: Dict[str, Any]) -> bool:
        clean_app = (app_name or "").lower().strip()
        cls_name = (window_info.get("class_name") or "").lower()
        title = (window_info.get("title") or "").lower()

        if "explorer" in clean_app:
            return True
        if cls_name in ("cabinetwclass", "explorewclass"):
            return True
        if "file explorer" in title or "windows explorer" in title:
            return True
        return False

    def extract_state(self, window_info: Dict[str, Any], hierarchy_level: int = 1) -> Optional[EnvironmentState]:
        title = (window_info.get("title") or "").strip()
        cls_name = window_info.get("class_name", "")
        pid = window_info.get("pid", 0)
        hwnd = window_info.get("hwnd", 0)

        folder_name = title or "File Explorer"
        # If title is a full path, split into dir and folder name
        is_path = ":\\" in folder_name or folder_name.startswith("\\\\")
        dir_path = folder_name if is_path else window_info.get("current_folder")

        # Extract selected files and folders from window_info or COM inspection
        selected_files: List[str] = list(window_info.get("selected_files") or [])
        selected_folders: List[str] = list(window_info.get("selected_folders") or [])

        # If running on Windows and not provided, try safe COM inspection
        if not dir_path or (not selected_files and not selected_folders):
            try:
                from core.environment_observer import _inspect_explorer_windows_safe
                f_path, sel_items = _inspect_explorer_windows_safe(timeout_sec=0.4)
                if not dir_path and f_path:
                    dir_path = f_path
                    folder_name = os.path.basename(f_path) or f_path
                if not selected_files and sel_items:
                    for itm in sel_items:
                        if os.path.isdir(itm):
                            if itm not in selected_folders:
                                selected_folders.append(itm)
                        else:
                            if itm not in selected_files:
                                selected_files.append(itm)
            except Exception:
                pass

        drive = os.path.splitdrive(dir_path)[0] if dir_path else None
        supported_docs = [
            f for f in selected_files
            if os.path.splitext(f)[1].lower() in (".pdf", ".docx", ".pptx", ".txt", ".csv", ".xlsx", ".md")
        ]

        primary_file = selected_files[0] if selected_files else None
        file_type = os.path.splitext(primary_file)[1].lower().lstrip(".") if primary_file else None

        entities: Dict[str, Any] = {
            "folder_name": os.path.basename(dir_path) if dir_path else folder_name,
            "directory_path": dir_path,
            "current_directory": dir_path,
            "drive": drive,
            "selected_files": selected_files,
            "selected_folders": selected_folders,
            "selected_documents": supported_docs,
            "has_selection": bool(selected_files or selected_folders),
            "multiple_selection": (len(selected_files) + len(selected_folders)) > 1,
            "file_type": file_type,
            "raw_title": title,
        }

        sel_count = len(selected_files) + len(selected_folders)
        if sel_count > 0:
            content_ctx = f"Browsing folder '{entities['folder_name']}' in File Explorer with {sel_count} items selected"
            action_summary = f"Browsing folder '{entities['folder_name']}' ({sel_count} items selected)"
        else:
            content_ctx = f"Browsing folder '{entities['folder_name']}' in File Explorer"
            action_summary = f"Browsing folder '{entities['folder_name']}'"

        return EnvironmentState(
            timestamp=time.time(),
            application="explorer",
            window_title=title,
            window_hwnd=hwnd,
            window_pid=pid,
            process_name="explorer.exe",
            app_category="file_manager",
            active_entities=entities,
            content_context=content_ctx,
            visible_text=folder_name,
            user_action_summary=action_summary,
            source_tier="os_window",
            metadata={
                "folder_name": entities["folder_name"],
                "drive": drive,
                "selected_files": selected_files,
            },
        )

    def detect_action(
        self,
        before: EnvironmentState,
        after: EnvironmentState,
    ) -> Tuple[str, str, str]:
        if before.application != after.application:
            return (
                "APP_SWITCH",
                "Opened File Explorer",
                f"Switched from {before.application} to File Explorer",
            )

        b_folder = before.get_entity("folder_name")
        a_folder = after.get_entity("folder_name")

        if a_folder and b_folder and a_folder != b_folder:
            return (
                "DIRECTORY_CHANGE",
                f"Navigated to folder '{a_folder}'",
                f"File Explorer: navigated from '{b_folder}' to '{a_folder}'",
            )

        return ("NO_CHANGE", "No change", "File Explorer state remained stable")
