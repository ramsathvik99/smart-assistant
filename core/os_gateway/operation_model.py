"""
Universal OS Operations — Structured Operation Model
Defines the canonical operation representation, capability types, risk levels,
execution methods, and verification contracts.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OSCapability(str, Enum):
    FILESYSTEM = "FILESYSTEM"
    STORAGE = "STORAGE"
    SHELL = "SHELL"
    PROCESS = "PROCESS"
    SERVICE = "SERVICE"
    ENVIRONMENT_VARIABLE = "ENVIRONMENT_VARIABLE"
    ENVIRONMENT = "ENVIRONMENT_VARIABLE"
    SYSTEM_API = "SYSTEM_API"
    SYSTEM_POWER = "SYSTEM_API"
    REGISTRY = "REGISTRY"
    NETWORK = "NETWORK"
    DEVICE = "DEVICE"
    GUI_AUTOMATION = "GUI_AUTOMATION"
    APPLICATION = "APPLICATION"


class OSOperationType(str, Enum):
    # Filesystem operations
    CREATE_FILE = "CREATE_FILE"
    READ_FILE = "READ_FILE"
    WRITE_FILE = "WRITE_FILE"
    DELETE_FILE = "DELETE_FILE"
    COPY_FILE = "COPY_FILE"
    MOVE_FILE = "MOVE_FILE"
    RENAME_FILE = "RENAME_FILE"
    CREATE_DIRECTORY = "CREATE_DIRECTORY"
    DELETE_DIRECTORY = "DELETE_DIRECTORY"
    LIST_DIRECTORY = "LIST_DIRECTORY"
    SEARCH_FILES = "SEARCH_FILES"
    FIND_FILES = "FIND_FILES"
    OPEN_FILE = "OPEN_FILE"
    OPEN_DIRECTORY = "OPEN_DIRECTORY"
    INSPECT_METADATA = "INSPECT_METADATA"
    CALCULATE_SIZE = "CALCULATE_SIZE"
    COMPARE_FILES = "COMPARE_FILES"
    CREATE_LINK = "CREATE_LINK"
    CREATE_SYMLINK = "CREATE_SYMLINK"
    ARCHIVE_FILES = "ARCHIVE_FILES"
    EXTRACT_ARCHIVE = "EXTRACT_ARCHIVE"

    # Storage operations
    LIST_DRIVES = "LIST_DRIVES"
    INSPECT_DRIVE = "INSPECT_DRIVE"
    GET_FREE_SPACE = "GET_FREE_SPACE"

    # Shell operations
    EXECUTE_COMMAND = "EXECUTE_COMMAND"
    EXECUTE_SCRIPT = "EXECUTE_SCRIPT"
    START_BACKGROUND_PROCESS = "START_BACKGROUND_PROCESS"
    TERMINATE_BACKGROUND_PROCESS = "TERMINATE_BACKGROUND_PROCESS"
    GET_PROCESS_OUTPUT = "GET_PROCESS_OUTPUT"

    # Process operations
    LIST_PROCESSES = "LIST_PROCESSES"
    FIND_PROCESS = "FIND_PROCESS"
    INSPECT_PROCESS = "INSPECT_PROCESS"
    START_PROCESS = "START_PROCESS"
    STOP_PROCESS = "STOP_PROCESS"
    TERMINATE_PROCESS = "TERMINATE_PROCESS"
    WAIT_FOR_PROCESS = "WAIT_FOR_PROCESS"
    MONITOR_PROCESS = "MONITOR_PROCESS"
    INSPECT_PORT = "INSPECT_PORT"
    FIND_BY_PORT = "FIND_BY_PORT"
    KILL_BY_PORT = "KILL_BY_PORT"

    # Service operations
    LIST_SERVICES = "LIST_SERVICES"
    INSPECT_SERVICE = "INSPECT_SERVICE"
    START_SERVICE = "START_SERVICE"
    STOP_SERVICE = "STOP_SERVICE"
    RESTART_SERVICE = "RESTART_SERVICE"
    CHECK_SERVICE_STATUS = "CHECK_SERVICE_STATUS"

    # Environment variable operations
    READ_ENV_VAR = "READ_ENV_VAR"
    SET_ENV_VAR = "SET_ENV_VAR"
    REMOVE_ENV_VAR = "REMOVE_ENV_VAR"
    INSPECT_PATH = "INSPECT_PATH"
    UPDATE_PATH = "UPDATE_PATH"

    # Registry operations
    READ_REGISTRY = "READ_REGISTRY"
    WRITE_REGISTRY = "WRITE_REGISTRY"
    DELETE_REGISTRY_VALUE = "DELETE_REGISTRY_VALUE"

    # Network operations
    GET_NETWORK_ADAPTERS = "GET_NETWORK_ADAPTERS"
    GET_IP_CONFIG = "GET_IP_CONFIG"
    TEST_CONNECTIVITY = "TEST_CONNECTIVITY"
    DNS_LOOKUP = "DNS_LOOKUP"
    INSPECT_PORTS = "INSPECT_PORTS"
    DIAGNOSE_NETWORK = "DIAGNOSE_NETWORK"

    # GUI / UIAutomation operations
    INSPECT_ELEMENTS = "INSPECT_ELEMENTS"
    FIND_ELEMENT = "FIND_ELEMENT"
    CLICK_ELEMENT = "CLICK_ELEMENT"
    SET_ELEMENT_VALUE = "SET_ELEMENT_VALUE"
    FOCUS_WINDOW = "FOCUS_WINDOW"
    GET_WINDOW_TREE = "GET_WINDOW_TREE"

    # System operations
    LOCK = "LOCK"
    SIGN_OUT = "SIGN_OUT"
    SLEEP = "SLEEP"
    HIBERNATE = "HIBERNATE"
    RESTART = "RESTART"
    SHUTDOWN = "SHUTDOWN"
    GET_SYSTEM_INFO = "GET_SYSTEM_INFO"
    GET_UPTIME = "GET_UPTIME"
    SCREENSHOT = "SCREENSHOT"
    CLIPBOARD = "CLIPBOARD"

    # Application operations
    OPEN_APPLICATION = "OPEN_APPLICATION"
    CLOSE_APPLICATION = "CLOSE_APPLICATION"


class OSRiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    LOW_RISK = "LOW_RISK"
    MODIFYING = "MODIFYING"
    DESTRUCTIVE = "DESTRUCTIVE"
    PRIVILEGED = "PRIVILEGED"
    SYSTEM_CRITICAL = "SYSTEM_CRITICAL"


class OSExecutionMethod(str, Enum):
    NATIVE_API = "native_api"
    FILESYSTEM_API = "filesystem_api"
    WIN32_API = "win32_api"
    UIAUTOMATION = "uiautomation"
    POWERSHELL = "powershell"
    CMD = "cmd"
    GIT_BASH = "git_bash"
    WSL = "wsl"
    PYTHON = "python"
    SUBPROCESS = "subprocess"
    EXISTING_TOOL = "existing_tool"


@dataclass
class OSOperation:
    """
    First-class structured representation of any OS or Computer Control operation.
    """
    operation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    capability: OSCapability = OSCapability.SYSTEM_API
    operation_type: OSOperationType = OSOperationType.GET_SYSTEM_INFO
    target: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    prerequisites: List[str] = field(default_factory=list)
    execution_method: OSExecutionMethod = OSExecutionMethod.NATIVE_API
    risk_level: OSRiskLevel = OSRiskLevel.LOW_RISK
    requires_confirmation: bool = False
    verification_method: str = "state_inspection"
    user_id: Any = 1
    original_goal: str = ""
    execution_node_id: Optional[str] = None
    goal_id: Optional[str] = None
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED, BLOCKED, WAITING_FOR_USER
    verified: bool = False
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    before_state: Dict[str, Any] = field(default_factory=dict)
    after_state: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "capability": self.capability.value if isinstance(self.capability, Enum) else str(self.capability),
            "operation_type": self.operation_type.value if isinstance(self.operation_type, Enum) else str(self.operation_type),
            "target": self.target,
            "parameters": self.parameters,
            "context": self.context,
            "prerequisites": self.prerequisites,
            "execution_method": self.execution_method.value if isinstance(self.execution_method, Enum) else str(self.execution_method),
            "risk_level": self.risk_level.value if isinstance(self.risk_level, Enum) else str(self.risk_level),
            "requires_confirmation": self.requires_confirmation,
            "verification_method": self.verification_method,
            "user_id": self.user_id,
            "original_goal": self.original_goal,
            "execution_node_id": self.execution_node_id,
            "goal_id": self.goal_id,
            "status": self.status,
            "verified": self.verified,
            "result": self.result,
            "error": self.error,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "created_at": self.created_at,
        }


@dataclass
class OSOperationResult:
    """
    Execution outcome and verification response.
    """
    success: bool
    status: str  # "success", "error", "blocked", "waiting_for_user"
    message: str
    verified: bool = False
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    verification_details: Dict[str, Any] = field(default_factory=dict)
    operation_id: Optional[str] = None
    capability: Optional[str] = None
    operation_type: Optional[str] = None
    execution_method: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "verified": self.verified,
            "data": self.data,
            "error": self.error,
            "verification_details": self.verification_details,
            "operation_id": self.operation_id,
            "capability": self.capability,
            "operation_type": self.operation_type,
            "execution_method": self.execution_method,
        }
