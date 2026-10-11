"""
IDE & Code Editor Environment Adapter
Specialized observer for development environments (VS Code, Cursor, PyCharm,
IntelliJ, Sublime Text, Notepad++, etc.).
Extracts active workspace, project, active_file, language, unsaved_changes,
terminal, terminal_working_directory, git_branch, cursor_position, and selection.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

from core.environment.adapters.base_adapter import BaseEnvironmentAdapter
from core.environment.models import EnvironmentState
from core.environment.ui_tree import (
    try_get_vscode_status_bar,
    try_resolve_git_branch,
    try_resolve_vscode_workspace,
)

logger = logging.getLogger(__name__)

EXTENSION_TO_LANGUAGE = {
    "py": "python", "pyw": "python",
    "js": "javascript", "jsx": "react", "ts": "typescript", "tsx": "react_typescript",
    "html": "html", "htm": "html", "css": "css", "scss": "scss", "sass": "sass", "less": "less",
    "json": "json", "yaml": "yaml", "yml": "yaml", "toml": "toml", "xml": "xml",
    "md": "markdown", "rst": "restructuredtext", "txt": "plaintext",
    "sql": "sql", "sh": "bash", "bash": "bash", "zsh": "zsh", "ps1": "powershell", "bat": "batch", "cmd": "batch",
    "c": "c", "h": "c", "cpp": "cpp", "hpp": "cpp", "cc": "cpp", "cs": "csharp",
    "java": "java", "kt": "kotlin", "scala": "scala", "go": "go", "rs": "rust", "php": "php",
    "rb": "ruby", "swift": "swift", "dart": "dart", "r": "r", "lua": "lua",
}


class IDEEnvironmentAdapter(BaseEnvironmentAdapter):
    """
    Adapter for code editors and IDEs.
    Decodes active file, workspace, modified state, language, terminal,
    git branch, and editor context.
    """

    name = "ide"
    app_category = "ide"

    IDE_KEYWORDS = {
        "code", "visual studio code", "cursor", "pycharm", "intellij",
        "sublime", "sublime text", "notepad++", "atom", "clion",
        "webstorm", "rider", "devenv", "eclipse"
    }

    def can_handle(self, app_name: str, window_info: Dict[str, Any]) -> bool:
        clean_app = (app_name or "").lower().strip()
        cls_name = (window_info.get("class_name") or "").lower()
        title = (window_info.get("title") or "").lower()

        if any(k in clean_app for k in self.IDE_KEYWORDS):
            return True
        if any(k in cls_name for k in ("code", "cursor", "sunawtframe", "sublime", "notepad++")):
            return True
        if any(k in title for k in ("visual studio code", "sublime text", "notepad++", "pycharm", "intellij idea")):
            return True
        return False

    def extract_state(self, window_info: Dict[str, Any], hierarchy_level: int = 1) -> Optional[EnvironmentState]:
        title = (window_info.get("title") or "").strip()
        cls_name = window_info.get("class_name", "")
        pid = window_info.get("pid", 0)
        hwnd = window_info.get("hwnd", 0)
        t_low = title.lower()

        editor_name = "code"
        if "cursor" in t_low or "cursor" in cls_name.lower():
            editor_name = "cursor"
        elif "pycharm" in t_low:
            editor_name = "pycharm"
        elif "intellij" in t_low:
            editor_name = "intellij"
        elif "sublime" in t_low:
            editor_name = "sublime_text"
        elif "notepad++" in t_low:
            editor_name = "notepad++"
        else:
            editor_name = "vscode"

        # Check for unsaved/dirty indicator
        is_dirty = "●" in title or title.startswith("*") or window_info.get("unsaved_changes", False)
        clean_title = title.replace("●", "").strip()
        if clean_title.startswith("*"):
            clean_title = clean_title[1:].strip()

        # Strip editor suffixes
        clean_title = re.sub(
            r'\s*-\s*(?:Visual Studio Code|Cursor|Sublime Text|Notepad\+\+|PyCharm|IntelliJ IDEA)(?:\s*\[Administrator\])?$',
            '', clean_title, flags=re.IGNORECASE
        ).strip()

        # Parse file, project, and terminal
        active_file: Optional[str] = window_info.get("active_file")
        active_project: Optional[str] = window_info.get("project")
        terminal_name: Optional[str] = window_info.get("terminal")
        terminal_cwd: Optional[str] = window_info.get("terminal_working_directory")

        # Check title if not explicitly passed
        if not terminal_name and ("terminal" in clean_title.lower() or any(sh in clean_title.lower() for sh in ("pwsh", "powershell", "bash", "cmd.exe"))):
            # Format: "Terminal: pwsh - smart_assistant" or "1: bash - smart_assistant"
            m_term = re.search(r'(?:Terminal:\s*|^\d+:\s*)([a-zA-Z0-9_\-]+)', clean_title, re.IGNORECASE)
            if m_term:
                terminal_name = m_term.group(1).lower()
            elif "powershell" in clean_title.lower() or "pwsh" in clean_title.lower():
                terminal_name = "powershell"
            elif "bash" in clean_title.lower():
                terminal_name = "bash"
            elif "cmd" in clean_title.lower():
                terminal_name = "cmd"
            else:
                terminal_name = "terminal"

        file_subpath: Optional[str] = None
        if not active_file and not terminal_name:
            if " - " in clean_title:
                parts = [p.strip() for p in clean_title.split(" - ")]
                active_file = parts[0]
                if not active_project:
                    active_project = parts[-1]
                if len(parts) > 2:
                    file_subpath = "/".join(parts[1:-1])
            elif clean_title.lower() not in ("welcome", "untitled", "get started", ""):
                active_file = clean_title
            else:
                active_file = None

        if terminal_name and not active_project:
            if " - " in clean_title:
                active_project = clean_title.split(" - ")[-1].strip()

        # Resolve workspace folder and git branch
        workspace_folder: Optional[str] = window_info.get("workspace")
        git_branch: Optional[str] = window_info.get("git_branch")

        if active_project and (not workspace_folder or not git_branch):
            ws_meta = try_resolve_vscode_workspace(active_project)
            if ws_meta:
                workspace_folder = workspace_folder or ws_meta.get("folder")
            if not git_branch:
                git_branch = try_resolve_git_branch(
                    workspace_path=workspace_folder,
                    project_name=active_project
                )

        if not workspace_folder and active_project:
            workspace_folder = active_project

        # Terminal working directory resolution
        if terminal_name and not terminal_cwd:
            terminal_cwd = workspace_folder or os.getcwd()

        # Language inference
        language: Optional[str] = window_info.get("language")
        file_ext: Optional[str] = None
        if active_file and "." in active_file:
            file_ext = active_file.rsplit(".", 1)[-1].lower()
            if not language:
                language = EXTENSION_TO_LANGUAGE.get(file_ext, file_ext)

        # Status bar / cursor / selection inspection (Tier 2 Accessibility)
        cursor_pos = window_info.get("cursor_position")
        selection = window_info.get("selection")
        source_tier = "integration"

        if hierarchy_level <= 2 and hwnd and (cursor_pos is None or selection is None):
            try:
                sb_info = try_get_vscode_status_bar(hwnd)
                if sb_info:
                    cursor_pos = cursor_pos or sb_info.get("cursor_position")
                    selection = selection or sb_info.get("selection")
                    source_tier = "accessibility"
            except Exception:
                pass

        entities: Dict[str, Any] = {
            "editor": editor_name,
            "application": editor_name,
            "workspace": workspace_folder,
            "project": active_project,
            "project_name": active_project,  # legacy compatibility
            "active_file": active_file,
            "file_name": active_file,        # legacy compatibility
            "language": language,
            "file_extension": file_ext,      # legacy compatibility
            "unsaved_changes": is_dirty,
            "is_modified": is_dirty,         # legacy compatibility
            "terminal": terminal_name,
            "terminal_working_directory": terminal_cwd,
            "git_branch": git_branch,
            "cursor_position": cursor_pos,
            "selection": selection,
            "raw_title": title,
        }
        if file_subpath:
            entities["file_subpath"] = file_subpath

        # Human-readable content context
        if terminal_name:
            content_ctx = f"Using {terminal_name.upper()} terminal in project '{active_project or 'workspace'}'"
            if terminal_cwd:
                content_ctx += f" (at '{terminal_cwd}')"
        elif active_file and active_project:
            status_str = " (unsaved edits)" if is_dirty else ""
            branch_str = f" [{git_branch}]" if git_branch else ""
            content_ctx = f"Editing '{active_file}' in project '{active_project}'{branch_str} using {editor_name.upper()}{status_str}"
        elif active_file:
            status_str = " (unsaved edits)" if is_dirty else ""
            content_ctx = f"Editing '{active_file}' in {editor_name.upper()}{status_str}"
        elif active_project:
            content_ctx = f"Working in project '{active_project}' in {editor_name.upper()}"
        else:
            content_ctx = f"Code editor {editor_name.upper()} is active"

        return EnvironmentState(
            timestamp=time.time(),
            application=editor_name,
            window_title=title,
            window_hwnd=hwnd,
            window_pid=pid,
            process_name=f"{editor_name}.exe",
            app_category="ide",
            active_entities=entities,
            content_context=content_ctx,
            visible_text=clean_title,
            user_action_summary=f"Working in {editor_name.upper()}",
            source_tier=source_tier,
            metadata={
                "editor": editor_name,
                "is_dirty": is_dirty,
                "project": active_project,
                "git_branch": git_branch,
                "terminal": terminal_name,
            },
        )

    def detect_action(
        self,
        before: EnvironmentState,
        after: EnvironmentState,
    ) -> Tuple[str, str, str]:
        # App switch
        if before.application != after.application:
            return (
                "APP_SWITCH",
                f"Switched to {after.application.upper()}",
                f"Switched from {before.application} to {after.application}",
            )

        b_proj = before.get_entity("project") or before.get_entity("project_name")
        a_proj = after.get_entity("project") or after.get_entity("project_name")
        b_file = before.get_entity("active_file") or before.get_entity("file_name")
        a_file = after.get_entity("active_file") or after.get_entity("file_name")
        b_term = before.get_entity("terminal")
        a_term = after.get_entity("terminal")

        # Project switch
        if a_proj and b_proj and a_proj != b_proj:
            return (
                "PROJECT_SWITCH",
                f"Switched to project '{a_proj}'",
                f"IDE: switched workspace from '{b_proj}' to '{a_proj}'",
            )

        # Terminal switches
        if a_term and not b_term:
            return (
                "TERMINAL_SWITCH",
                f"Switched to integrated terminal '{a_term}'",
                f"IDE: switched from editor to integrated terminal '{a_term}'",
            )
        if not a_term and b_term:
            return (
                "TERMINAL_EXIT",
                f"Returned to file '{a_file}'",
                f"IDE: returned to file '{a_file}' from terminal",
            )
        if a_term and b_term and a_term != b_term:
            return (
                "TERMINAL_SWITCH",
                f"Switched terminal to '{a_term}'",
                f"IDE: switched terminal from '{b_term}' to '{a_term}'",
            )

        # File switches
        if a_file and b_file and a_file != b_file:
            return (
                "FILE_SWITCH",
                f"Switched to file '{a_file}'",
                f"IDE: switched active file from '{b_file}' to '{a_file}'",
            )

        if a_file and not b_file:
            return (
                "FILE_OPENED",
                f"Opened file '{a_file}'",
                f"IDE: opened file '{a_file}'",
            )

        # Dirty state
        b_dirty = before.get_entity("unsaved_changes")
        a_dirty = after.get_entity("unsaved_changes")
        if a_dirty and not b_dirty:
            return (
                "FILE_MODIFIED",
                f"Edited '{a_file or 'active file'}'",
                f"IDE: unsaved changes in '{a_file or 'active file'}'",
            )
        if not a_dirty and b_dirty:
            return (
                "FILE_SAVED",
                f"Saved '{a_file or 'active file'}'",
                f"IDE: saved '{a_file or 'active file'}'",
            )

        return ("NO_CHANGE", "No change", "IDE state remained stable")
