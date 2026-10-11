"""
Terminal & Command Line Environment Adapter
Specialized observer for terminal shells (PowerShell, CMD, Windows Terminal, Git Bash, WSL).
Extracts shell type, administrative privilege, working directory, and running command.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional, Tuple

from core.environment.adapters.base_adapter import BaseEnvironmentAdapter
from core.environment.models import EnvironmentState


class TerminalEnvironmentAdapter(BaseEnvironmentAdapter):
    """
    Adapter for command-line shells and terminals.
    Extracts shell type, privilege level, and working context.
    """

    name = "terminal"
    app_category = "terminal"

    SHELL_APPS = {
        "powershell", "pwsh", "cmd", "windowsterminal", "wt",
        "bash", "git-bash", "mintty", "conhost", "wsl"
    }

    def can_handle(self, app_name: str, window_info: Dict[str, Any]) -> bool:
        clean_app = (app_name or "").lower().strip()
        cls_name = (window_info.get("class_name") or "").lower()
        title = (window_info.get("title") or "").lower()

        if any(s in clean_app for s in self.SHELL_APPS):
            return True
        if cls_name in ("consolewindowclass", "cascadia_windowing_host_windowclass", "mintty"):
            return True
        if any(s in title for s in ("powershell", "command prompt", "cmd.exe", "mingw64", "wsl")):
            return True
        return False

    def extract_state(self, window_info: Dict[str, Any], hierarchy_level: int = 1) -> Optional[EnvironmentState]:
        title = (window_info.get("title") or "").strip()
        cls_name = window_info.get("class_name", "")
        pid = window_info.get("pid", 0)
        hwnd = window_info.get("hwnd", 0)
        t_low = title.lower()

        is_admin = "administrator:" in t_low or "[administrator]" in t_low
        clean_title = re.sub(r'^(?:administrator:\s*|\[administrator\]\s*)', '', title, flags=re.IGNORECASE).strip()

        shell_type = "terminal"
        if "powershell" in t_low or "pwsh" in t_low:
            shell_type = "powershell"
        elif "command prompt" in t_low or "cmd" in t_low:
            shell_type = "cmd"
        elif "mingw" in t_low or "bash" in t_low:
            shell_type = "bash"
        elif "wsl" in t_low or "ubuntu" in t_low:
            shell_type = "wsl"
        else:
            shell_type = "terminal"

        entities: Dict[str, Any] = {
            "shell_type": shell_type,
            "is_admin": is_admin,
            "raw_title": title,
            "window_title": clean_title,
        }

        # Try to extract current command or directory if in title
        if ": " in clean_title:
            entities["current_command"] = clean_title.split(": ", 1)[-1]

        admin_str = " (Admin)" if is_admin else ""
        content_ctx = f"Active {shell_type.upper()}{admin_str} shell session: '{clean_title}'"

        return EnvironmentState(
            timestamp=time.time(),
            application=shell_type,
            window_title=title,
            window_hwnd=hwnd,
            window_pid=pid,
            process_name=f"{shell_type}.exe",
            app_category="terminal",
            active_entities=entities,
            content_context=content_ctx,
            visible_text=clean_title,
            user_action_summary=f"Using {shell_type.upper()}",
            source_tier="os_window",
            metadata={"shell_type": shell_type, "is_admin": is_admin},
        )

    def detect_action(
        self,
        before: EnvironmentState,
        after: EnvironmentState,
    ) -> Tuple[str, str, str]:
        if before.application != after.application:
            return (
                "APP_SWITCH",
                f"Switched to {after.application.upper()}",
                f"Switched from {before.application} to {after.application}",
            )

        if before.window_title != after.window_title:
            return (
                "COMMAND_EXECUTED",
                f"Ran command in {after.application.upper()}",
                f"Terminal title changed to '{after.window_title}'",
            )

        return ("NO_CHANGE", "No change", "Terminal session remained stable")
