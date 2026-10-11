"""
Environment Awareness Data Models
Defines structured representations for current working environment states,
application-specific contexts, and meaningful state transitions.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class EnvironmentState:
    """
    Structured representation of the user's active environment at a specific moment.
    Captures active software, window, content, entities, and visible context.
    """
    timestamp: float = field(default_factory=time.time)
    application: str = "unknown"
    window_title: str = ""
    window_hwnd: int = 0
    window_pid: int = 0
    process_name: str = ""
    app_category: str = "general"   # browser, ide, media, document, file_manager, terminal, utility, general
    active_entities: Dict[str, Any] = field(default_factory=dict)
    content_context: str = ""
    visible_text: Optional[str] = None
    user_action_summary: Optional[str] = None
    source_tier: str = "os_window"   # api, accessibility, integration, os_window, vision
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EnvironmentState:
        """Construct state from dictionary."""
        valid_keys = {
            "timestamp", "application", "window_title", "window_hwnd", "window_pid",
            "process_name", "app_category", "active_entities", "content_context",
            "visible_text", "user_action_summary", "source_tier", "metadata"
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    def is_empty(self) -> bool:
        """Check if this represents an unobserved or empty state."""
        return self.application in ("unknown", "", "None") and not self.window_title

    def get_entity(self, key: str, default: Any = None) -> Any:
        """Safely retrieve an active entity."""
        return self.active_entities.get(key, default)

    def format_summary(self) -> str:
        """Generate a concise, human-readable summary of the current environment state."""
        if self.content_context:
            return self.content_context
        if self.application and self.application != "unknown":
            app_name = self.application.capitalize()
            if self.window_title:
                return f"{app_name}: '{self.window_title}'"
            return f"{app_name} is active"
        if self.window_title:
            return f"Active window: '{self.window_title}'"
        return "No active application observed"


@dataclass
class StateTransition:
    """
    Represents a meaningful transition between two environmental states.
    Records what changed, what the user did, and any assistant action correlation.
    """
    transition_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    before_state: Optional[EnvironmentState] = None
    after_state: Optional[EnvironmentState] = None
    change_type: str = "GENERAL_CHANGE"   # APP_SWITCH, TAB_SWITCH, VIDEO_CHANGE, FILE_CHANGE, DIRECTORY_CHANGE, MEDIA_TRACK_CHANGE, CONTENT_UPDATE
    transition_summary: str = ""
    user_action: str = ""
    assistant_action_correlation: Optional[str] = None
    entities_changed: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert transition to serializable dictionary."""
        return {
            "transition_id": self.transition_id,
            "timestamp": self.timestamp,
            "before_state": self.before_state.to_dict() if self.before_state else None,
            "after_state": self.after_state.to_dict() if self.after_state else None,
            "change_type": self.change_type,
            "transition_summary": self.transition_summary,
            "user_action": self.user_action,
            "assistant_action_correlation": self.assistant_action_correlation,
            "entities_changed": self.entities_changed,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StateTransition:
        """Construct transition from dictionary."""
        b_data = data.get("before_state")
        a_data = data.get("after_state")
        return cls(
            transition_id=data.get("transition_id", str(uuid.uuid4())[:8]),
            timestamp=data.get("timestamp", time.time()),
            before_state=EnvironmentState.from_dict(b_data) if isinstance(b_data, dict) else None,
            after_state=EnvironmentState.from_dict(a_data) if isinstance(a_data, dict) else None,
            change_type=data.get("change_type", "GENERAL_CHANGE"),
            transition_summary=data.get("transition_summary", ""),
            user_action=data.get("user_action", ""),
            assistant_action_correlation=data.get("assistant_action_correlation"),
            entities_changed=data.get("entities_changed", {}),
        )


@dataclass
class ComputerState:
    """
    Unified Computer State representing comprehensive Windows system, application,
    window, filesystem, and interaction state.
    """
    timestamp: float = field(default_factory=time.time)
    active_application: str = "unknown"
    active_window: str = ""
    active_process: Optional[Dict[str, Any]] = None
    active_browser: Optional[str] = None
    active_tab: Optional[str] = None
    current_url: Optional[str] = None
    current_page: Optional[str] = None
    current_video: Optional[str] = None
    current_document: Optional[str] = None
    current_file: Optional[str] = None
    current_project: Optional[str] = None
    current_terminal: Optional[str] = None
    terminal_cwd: Optional[str] = None
    cursor_context: Optional[str] = None
    selected_text: Optional[str] = None
    selected_files: List[str] = field(default_factory=list)
    visible_controls: List[Dict[str, Any]] = field(default_factory=list)
    open_applications: List[str] = field(default_factory=list)
    open_windows: List[Dict[str, Any]] = field(default_factory=list)
    running_processes: List[Dict[str, Any]] = field(default_factory=list)
    filesystem_context: Dict[str, Any] = field(default_factory=dict)
    system_context: Dict[str, Any] = field(default_factory=dict)
    network_context: Dict[str, Any] = field(default_factory=dict)
    device_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to serializable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ComputerState:
        """Construct from dictionary."""
        valid_keys = {
            "timestamp", "active_application", "active_window", "active_process",
            "active_browser", "active_tab", "current_url", "current_page",
            "current_video", "current_document", "current_file", "current_project",
            "current_terminal", "terminal_cwd", "cursor_context", "selected_text",
            "selected_files", "visible_controls", "open_applications", "open_windows",
            "running_processes", "filesystem_context", "system_context",
            "network_context", "device_context"
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    def to_environment_state(self) -> EnvironmentState:
        """Convert to canonical EnvironmentState for backward compatibility."""
        entities = {
            "url": self.current_url,
            "page_title": self.current_page,
            "video_title": self.current_video,
            "active_file": self.current_file,
            "document": self.current_document,
            "project": self.current_project,
            "workspace": self.current_project,
            "terminal": self.current_terminal,
            "terminal_cwd": self.terminal_cwd,
            "cursor_position": self.cursor_context,
            "selection": self.selected_text,
            "selected_files": self.selected_files,
        }
        clean_entities = {k: v for k, v in entities.items() if v}
        pid = (self.active_process or {}).get("pid", 0) if isinstance(self.active_process, dict) else 0
        return EnvironmentState(
            timestamp=self.timestamp,
            application=self.active_application,
            window_title=self.active_window,
            window_pid=pid,
            active_entities=clean_entities,
            content_context=f"{self.active_application.capitalize()}: {self.active_window}",
            metadata={
                "system": self.system_context,
                "network": self.network_context,
                "filesystem": self.filesystem_context,
                "device": self.device_context,
            }
        )

    @classmethod
    def from_environment_state(cls, env: EnvironmentState) -> ComputerState:
        """Construct from canonical EnvironmentState."""
        ents = env.active_entities or {}
        return cls(
            timestamp=env.timestamp,
            active_application=env.application,
            active_window=env.window_title,
            active_process={"pid": env.window_pid, "name": env.process_name} if env.window_pid else None,
            active_browser=env.application if env.app_category == "browser" else None,
            current_url=ents.get("url"),
            current_page=ents.get("page_title"),
            current_video=ents.get("video_title"),
            current_file=ents.get("active_file") or ents.get("file_name"),
            current_document=ents.get("document") or ents.get("active_file"),
            current_project=ents.get("project") or ents.get("workspace"),
            current_terminal=ents.get("terminal"),
            terminal_cwd=ents.get("terminal_cwd"),
            cursor_context=ents.get("cursor_position"),
            selected_text=ents.get("selection"),
            selected_files=ents.get("selected_files", []),
            filesystem_context=env.metadata.get("filesystem", {}),
            system_context=env.metadata.get("system", {}),
            network_context=env.metadata.get("network", {}),
            device_context=env.metadata.get("device", {}),
        )

