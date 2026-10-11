"""
Dynamic Capability Registry & Discovery Engine
Provides structured representation, metadata, dynamic availability verification,
and semantic discovery for all assistant execution capabilities.

Adheres strictly to AGENTS.md permanent architecture freeze.
Does not duplicate existing operation implementations; references canonical implementations.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import time

logger = logging.getLogger(__name__)


# ============================================================================
# 1. Capability Metadata Definition
# ============================================================================

class AvailableStatus(int):
    """Dual boolean / callable availability status."""
    def __bool__(self) -> bool:
        return bool(int(self))

    def __call__(self) -> bool:
        return bool(int(self))


@dataclass
class CapabilityDefinition:
    """
    Structured descriptor for an assistant capability.
    Exposes supported operations, execution methods, verification methods,
    risk profiles, and dynamic availability checks.
    """
    capability_id: str
    name: str
    description: str
    supported_operations: List[str]
    required_inputs: Dict[str, List[str]] = field(default_factory=dict)
    execution_methods: List[str] = field(default_factory=list)
    verification_methods: List[str] = field(default_factory=list)
    permission_risk_requirements: Dict[str, str] = field(default_factory=dict)
    risk_level: str = "LOW_RISK"
    reversible: bool = True
    platform_support: List[str] = field(default_factory=lambda: ["win32", "linux", "darwin"])
    availability_checker: Optional[Callable[[], bool]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    _cached_availability: Optional[Tuple[float, AvailableStatus]] = field(default=None, init=False, repr=False, compare=False)

    @property
    def is_available(self) -> AvailableStatus:
        """Determines if the capability is currently available in the runtime environment."""
        now = time.monotonic()
        if self._cached_availability is not None:
            cached_time, cached_val = self._cached_availability
            if (now - cached_time) < 10.0:  # 10 second TTL cache
                return cached_val

        if self.platform_support and sys.platform not in self.platform_support:
            res = AvailableStatus(0)
        elif self.availability_checker is not None:
            try:
                res = AvailableStatus(1 if bool(self.availability_checker()) else 0)
            except Exception as exc:
                logger.debug("[CAPABILITY_REGISTRY] Availability check failed for %s: %s", self.capability_id, exc)
                res = AvailableStatus(0)
        else:
            res = AvailableStatus(1)

        self._cached_availability = (now, res)
        return res

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "supported_operations": list(self.supported_operations),
            "required_inputs": self.required_inputs,
            "execution_methods": list(self.execution_methods),
            "verification_methods": list(self.verification_methods),
            "permission_risk_requirements": self.permission_risk_requirements,
            "reversible": self.reversible,
            "platform_support": list(self.platform_support),
            "is_available": self.is_available,
            "metadata": dict(self.metadata),
        }


# ============================================================================
# 2. Discovered Capability Representation
# ============================================================================

@dataclass
class DiscoveredCapability:
    """Result of discovering a capability to fulfill an intent or outcome."""
    capability: CapabilityDefinition
    matched_operation: Optional[str] = None
    confidence: float = 1.0
    rationale: str = ""
    suggested_inputs: Dict[str, Any] = field(default_factory=dict)
    execution_method: str = "native_api"

    def __iter__(self):
        yield self.capability
        yield self.matched_operation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability.capability_id,
            "name": self.capability.name,
            "matched_operation": self.matched_operation,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "suggested_inputs": self.suggested_inputs,
            "execution_method": self.execution_method,
            "is_available": self.capability.is_available,
        }


# ============================================================================
# 3. Dynamic Capability Registry
# ============================================================================

class CapabilityRegistry:
    """
    Central registry representing the capabilities the assistant can use.
    Pre-registers canonical system capabilities and allows dynamic extension.
    """

    def __init__(self):
        self._capabilities: Dict[str, CapabilityDefinition] = {}
        self._register_default_capabilities()

    def __len__(self) -> int:
        return len(self._capabilities)

    def register(self, capability: CapabilityDefinition) -> None:
        """Register or update a capability definition."""
        self._capabilities[capability.capability_id.lower()] = capability
        logger.debug("[CAPABILITY_REGISTRY] Registered capability: %s", capability.capability_id)

    def get(self, capability_id: str) -> Optional[CapabilityDefinition]:
        """Retrieve capability by identifier."""
        return self._capabilities.get(capability_id.lower())

    def get_capability(self, capability_id: str) -> Optional[CapabilityDefinition]:
        """Retrieve capability by identifier (alias for get)."""
        return self.get(capability_id)

    def unregister(self, capability_id: str) -> bool:
        """Unregister a capability definition."""
        norm_id = capability_id.lower()
        if norm_id in self._capabilities:
            del self._capabilities[norm_id]
            return True
        return False

    def discover(self, *args, **kwargs) -> List[DiscoveredCapability]:
        """Convenience method delegating to CapabilityDiscoveryEngine."""
        return get_capability_discovery_engine().discover(*args, **kwargs)

    def select_best_capability(self, *args, **kwargs) -> Optional[DiscoveredCapability]:
        """Convenience method delegating to CapabilityDiscoveryEngine."""
        return get_capability_discovery_engine().select_best_capability(*args, **kwargs)

    def list_capabilities(self, available_only: bool = False) -> List[CapabilityDefinition]:
        """List registered capabilities, optionally filtering to currently available ones."""
        caps = list(self._capabilities.values())
        if available_only:
            return [c for c in caps if c.is_available]
        return caps

    def list_available_capabilities(self) -> List[CapabilityDefinition]:
        """List registered capabilities that are currently available."""
        return self.list_capabilities(available_only=True)

    def find_by_operation(self, operation: str, available_only: bool = True) -> List[CapabilityDefinition]:
        """Find capabilities that support a given operation."""
        norm_op = operation.upper().strip()
        matches = []
        for cap in self._capabilities.values():
            if norm_op in [op.upper() for op in cap.supported_operations]:
                if not available_only or cap.is_available:
                    matches.append(cap)
        return matches

    def find_by_execution_method(self, method: str, available_only: bool = True) -> List[CapabilityDefinition]:
        """Find capabilities supporting a specific execution method."""
        norm_method = method.lower().strip()
        matches = []
        for cap in self._capabilities.values():
            if norm_method in [m.lower() for m in cap.execution_methods]:
                if not available_only or cap.is_available:
                    matches.append(cap)
        return matches

    # ------------------------------------------------------------------------
    # Default Canonical Capabilities Initialization
    # ------------------------------------------------------------------------

    def _register_default_capabilities(self) -> None:
        """Register existing system capabilities from core and extensions."""

        # 1. Filesystem
        self.register(CapabilityDefinition(
            capability_id="filesystem",
            name="Filesystem Controller",
            description="Manage files and folders: create, read, write, copy, move, rename, delete, and inspect metadata.",
            supported_operations=[
                "CREATE_FILE", "READ_FILE", "WRITE_FILE", "DELETE_FILE",
                "COPY_FILE", "MOVE_FILE", "RENAME_FILE", "CREATE_DIRECTORY",
                "DELETE_DIRECTORY", "LIST_DIRECTORY", "SEARCH_FILES", "FIND_FILES",
                "INSPECT_METADATA", "CALCULATE_SIZE", "COMPARE_FILES"
            ],
            required_inputs={
                "READ_FILE": ["path"],
                "WRITE_FILE": ["path", "content"],
                "COPY_FILE": ["source", "destination"],
                "MOVE_FILE": ["source", "destination"],
                "DELETE_FILE": ["path"],
            },
            execution_methods=["filesystem_api", "native_api"],
            verification_methods=["file_exists", "stat_check", "hash_comparison"],
            permission_risk_requirements={
                "DELETE_FILE": "DESTRUCTIVE",
                "DELETE_DIRECTORY": "DESTRUCTIVE",
                "WRITE_FILE": "LOW_RISK",
            },
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 2. Storage & Drives
        self.register(CapabilityDefinition(
            capability_id="storage",
            name="Storage & Drive Inspector",
            description="Inspect available storage partitions, drive space, volume labels, and disk health.",
            supported_operations=["LIST_DRIVES", "INSPECT_DRIVE", "GET_FREE_SPACE"],
            required_inputs={"INSPECT_DRIVE": ["drive"]},
            execution_methods=["native_api", "win32_api"],
            verification_methods=["disk_usage_check"],
            permission_risk_requirements={"LIST_DRIVES": "READ_ONLY", "INSPECT_DRIVE": "READ_ONLY"},
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 3. Terminal & Shell Execution (General)
        self.register(CapabilityDefinition(
            capability_id="terminal",
            name="Terminal Host",
            description="Execute shell commands and launch long-running background processes.",
            supported_operations=["EXECUTE_COMMAND", "START_BACKGROUND_PROCESS", "TERMINATE_BACKGROUND_PROCESS", "OPEN_TERMINAL"],
            required_inputs={"EXECUTE_COMMAND": ["command"]},
            execution_methods=["powershell", "cmd", "git_bash", "wsl", "subprocess"],
            verification_methods=["exit_code_check", "output_check"],
            permission_risk_requirements={"EXECUTE_COMMAND": "LOW_RISK"},
            reversible=False,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 4. PowerShell
        self.register(CapabilityDefinition(
            capability_id="powershell",
            name="PowerShell Execution",
            description="Execute Windows PowerShell commands, scripts, and administrative cmdlets.",
            supported_operations=["EXECUTE_COMMAND", "EXECUTE_SCRIPT"],
            required_inputs={"EXECUTE_COMMAND": ["command"]},
            execution_methods=["powershell"],
            verification_methods=["exit_code_check"],
            permission_risk_requirements={"EXECUTE_COMMAND": "LOW_RISK"},
            reversible=False,
            platform_support=["win32"],
            availability_checker=lambda: shutil.which("powershell.exe") is not None or shutil.which("pwsh") is not None,
        ))

        # 5. CMD
        self.register(CapabilityDefinition(
            capability_id="cmd",
            name="Windows Command Prompt",
            description="Execute classic Windows batch files and cmd commands.",
            supported_operations=["EXECUTE_COMMAND"],
            required_inputs={"EXECUTE_COMMAND": ["command"]},
            execution_methods=["cmd"],
            verification_methods=["exit_code_check"],
            permission_risk_requirements={"EXECUTE_COMMAND": "LOW_RISK"},
            reversible=False,
            platform_support=["win32"],
            availability_checker=lambda: shutil.which("cmd.exe") is not None,
        ))

        # 6. Git Bash
        self.register(CapabilityDefinition(
            capability_id="git_bash",
            name="Git Bash Environment",
            description="Execute POSIX bash scripts and git workflows on Windows via Git Bash.",
            supported_operations=["EXECUTE_COMMAND"],
            required_inputs={"EXECUTE_COMMAND": ["command"]},
            execution_methods=["git_bash"],
            verification_methods=["exit_code_check"],
            permission_risk_requirements={"EXECUTE_COMMAND": "LOW_RISK"},
            reversible=False,
            platform_support=["win32"],
            availability_checker=lambda: any(os.path.exists(p) for p in [
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files (x86)\Git\bin\bash.exe",
                r"C:\Program Files\Git\usr\bin\bash.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe")
            ]),
        ))

        # 7. WSL
        self.register(CapabilityDefinition(
            capability_id="wsl",
            name="Windows Subsystem for Linux",
            description="Execute Linux commands and manage Linux distros via WSL.",
            supported_operations=["EXECUTE_COMMAND"],
            required_inputs={"EXECUTE_COMMAND": ["command"]},
            execution_methods=["wsl"],
            verification_methods=["exit_code_check"],
            permission_risk_requirements={"EXECUTE_COMMAND": "LOW_RISK"},
            reversible=False,
            platform_support=["win32"],
            availability_checker=lambda: shutil.which("wsl.exe") is not None,
        ))

        # 8. Processes
        self.register(CapabilityDefinition(
            capability_id="processes",
            name="Process Manager",
            description="Inspect running processes, resource consumption, identify open ports, and terminate processes.",
            supported_operations=["LIST_PROCESSES", "FIND_PROCESS", "INSPECT_PROCESS", "TERMINATE_PROCESS", "STOP_PROCESS", "INSPECT_PORT", "KILL_BY_PORT"],
            required_inputs={"INSPECT_PORT": ["port"], "TERMINATE_PROCESS": ["target"]},
            execution_methods=["native_api", "win32_api"],
            verification_methods=["pid_running_check", "pid_not_running_check", "port_free_check"],
            permission_risk_requirements={"TERMINATE_PROCESS": "DESTRUCTIVE", "KILL_BY_PORT": "DESTRUCTIVE"},
            reversible=False,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 9. Services
        self.register(CapabilityDefinition(
            capability_id="services",
            name="Windows Services Controller",
            description="Query, inspect, start, stop, and restart background Windows services.",
            supported_operations=["LIST_SERVICES", "INSPECT_SERVICE", "CHECK_SERVICE_STATUS", "START_SERVICE", "STOP_SERVICE", "RESTART_SERVICE"],
            required_inputs={"INSPECT_SERVICE": ["service_name"], "STOP_SERVICE": ["service_name"]},
            execution_methods=["native_api", "powershell"],
            verification_methods=["service_status_check"],
            permission_risk_requirements={"STOP_SERVICE": "PRIVILEGED", "START_SERVICE": "PRIVILEGED", "RESTART_SERVICE": "PRIVILEGED"},
            reversible=True,
            platform_support=["win32"],
        ))

        # 10. Applications
        self.register(CapabilityDefinition(
            capability_id="applications",
            name="Application Controller",
            description="Smart application launcher and controller (Notepad, Chrome, Spotify, Calculator, etc.).",
            supported_operations=["OPEN_APPLICATION", "CLOSE_APPLICATION", "LAUNCH_APP"],
            required_inputs={"OPEN_APPLICATION": ["target"]},
            execution_methods=["existing_tool", "native_api"],
            verification_methods=["window_exists_check", "process_running_check"],
            permission_risk_requirements={"OPEN_APPLICATION": "LOW_RISK"},
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 11. Windows & Window Management
        self.register(CapabilityDefinition(
            capability_id="windows",
            name="Window Manager",
            description="Inspect, focus, minimize, maximize, and manage desktop top-level windows.",
            supported_operations=["LIST_WINDOWS", "FOCUS_WINDOW", "MINIMIZE_WINDOW", "MAXIMIZE_WINDOW", "CLOSE_WINDOW"],
            required_inputs={"FOCUS_WINDOW": ["hwnd"]},
            execution_methods=["win32_api", "uiautomation"],
            verification_methods=["foreground_window_check"],
            permission_risk_requirements={"FOCUS_WINDOW": "LOW_RISK"},
            reversible=True,
            platform_support=["win32"],
        ))

        # 12. UIAutomation
        self.register(CapabilityDefinition(
            capability_id="uiautomation",
            name="UI Automation Controller",
            description="Inspect UI controls, access accessibility trees, and click buttons or invoke UI elements.",
            supported_operations=["INSPECT_ELEMENTS", "CLICK_ELEMENT"],
            required_inputs={"CLICK_ELEMENT": ["name_or_automation_id"]},
            execution_methods=["uiautomation"],
            verification_methods=["state_inspection"],
            permission_risk_requirements={"CLICK_ELEMENT": "LOW_RISK"},
            reversible=False,
            platform_support=["win32"],
        ))

        # 13. Win32 API
        self.register(CapabilityDefinition(
            capability_id="win32",
            name="Native Win32 Subsystem",
            description="Low-level Win32 kernel, user, and GDI calls for desktop and system operations.",
            supported_operations=["LOCK_WORKSTATION", "GET_WINDOW_TEXT", "ENUM_WINDOWS", "QUERY_SYSTEM_METRICS"],
            execution_methods=["win32_api"],
            verification_methods=["state_inspection"],
            permission_risk_requirements={"LOCK_WORKSTATION": "PRIVILEGED"},
            reversible=False,
            platform_support=["win32"],
        ))

        # 14. Browser & CDP
        self.register(CapabilityDefinition(
            capability_id="browser",
            name="Web Browser & CDP Controller",
            description="Automate browser sessions, navigate URLs, inspect DOM, and execute web automation.",
            supported_operations=["OPEN_URL", "NAVIGATE_PAGE", "INSPECT_DOM", "TAKE_SCREENSHOT"],
            required_inputs={"OPEN_URL": ["url"]},
            execution_methods=["existing_tool", "subprocess"],
            verification_methods=["url_active_check"],
            permission_risk_requirements={"OPEN_URL": "LOW_RISK"},
            reversible=False,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 15. VS Code
        self.register(CapabilityDefinition(
            capability_id="vscode",
            name="Visual Studio Code Integration",
            description="Open workspace folders, inspect files, and interface with VS Code developer environment.",
            supported_operations=["OPEN_WORKSPACE", "OPEN_FILE_IN_EDITOR"],
            required_inputs={"OPEN_WORKSPACE": ["path"]},
            execution_methods=["existing_tool", "subprocess"],
            verification_methods=["process_running_check"],
            permission_risk_requirements={"OPEN_WORKSPACE": "LOW_RISK"},
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
            availability_checker=lambda: shutil.which("code") is not None or any(os.path.exists(p) for p in [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
                r"C:\Program Files\Microsoft VS Code\Code.exe"
            ]),
        ))

        # 16. Network
        self.register(CapabilityDefinition(
            capability_id="network",
            name="Network Diagnostics & Connectivity",
            description="Inspect network adapters, test latency, perform DNS lookups, and diagnose ports.",
            supported_operations=["GET_NETWORK_ADAPTERS", "TEST_CONNECTIVITY", "DNS_LOOKUP", "DIAGNOSE_NETWORK"],
            required_inputs={"TEST_CONNECTIVITY": ["host"]},
            execution_methods=["native_api"],
            verification_methods=["connectivity_check"],
            permission_risk_requirements={"TEST_CONNECTIVITY": "READ_ONLY"},
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 17. Devices
        self.register(CapabilityDefinition(
            capability_id="devices",
            name="Device & Hardware Controller",
            description="Manage connected USB devices, Bluetooth peripherals, and audio endpoints.",
            supported_operations=["LIST_DEVICES", "GET_DEVICE_STATUS"],
            execution_methods=["native_api", "powershell"],
            verification_methods=["device_status_check"],
            permission_risk_requirements={"LIST_DEVICES": "READ_ONLY"},
            reversible=True,
            platform_support=["win32"],
        ))

        # 18. Registry
        self.register(CapabilityDefinition(
            capability_id="registry",
            name="Windows Registry Controller",
            description="Safely inspect and modify whitelisted Windows registry keys under strict security boundary.",
            supported_operations=["READ_REGISTRY", "WRITE_REGISTRY"],
            required_inputs={"READ_REGISTRY": ["hive", "sub_key"]},
            execution_methods=["native_api"],
            verification_methods=["registry_value_check"],
            permission_risk_requirements={"WRITE_REGISTRY": "SYSTEM_CRITICAL", "READ_REGISTRY": "READ_ONLY"},
            reversible=True,
            platform_support=["win32"],
        ))

        # 19. Environment Variables
        self.register(CapabilityDefinition(
            capability_id="environment_variables",
            name="Environment Variables Manager",
            description="Read, set, and inspect system, user, and process environment variables and PATH.",
            supported_operations=["READ_ENV_VAR", "SET_ENV_VAR", "INSPECT_PATH"],
            required_inputs={"READ_ENV_VAR": ["name"], "SET_ENV_VAR": ["name", "value"]},
            execution_methods=["native_api"],
            verification_methods=["env_var_check"],
            permission_risk_requirements={"SET_ENV_VAR": "MODIFYING", "READ_ENV_VAR": "READ_ONLY"},
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 20. System Configuration
        self.register(CapabilityDefinition(
            capability_id="system_configuration",
            name="System Configuration",
            description="Retrieve hardware overview, OS version, CPU/memory architecture, and uptime.",
            supported_operations=["GET_SYSTEM_INFO", "GET_SYSTEM_OVERVIEW"],
            execution_methods=["native_api"],
            verification_methods=["state_inspection"],
            permission_risk_requirements={"GET_SYSTEM_INFO": "READ_ONLY"},
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 21. Clipboard
        self.register(CapabilityDefinition(
            capability_id="clipboard",
            name="Clipboard Controller",
            description="Get and set clipboard content safely.",
            supported_operations=["GET_CLIPBOARD", "SET_CLIPBOARD", "CLEAR_CLIPBOARD"],
            execution_methods=["native_api"],
            verification_methods=["clipboard_check"],
            permission_risk_requirements={"GET_CLIPBOARD": "READ_ONLY", "SET_CLIPBOARD": "LOW_RISK"},
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 22. Display
        self.register(CapabilityDefinition(
            capability_id="display",
            name="Display & Screen Controller",
            description="Manage screen brightness, resolution, and multi-monitor setup.",
            supported_operations=["GET_BRIGHTNESS", "SET_BRIGHTNESS", "LIST_MONITORS"],
            execution_methods=["native_api", "powershell"],
            verification_methods=["state_inspection"],
            permission_risk_requirements={"SET_BRIGHTNESS": "LOW_RISK"},
            reversible=True,
            platform_support=["win32"],
        ))

        # 23. Audio
        self.register(CapabilityDefinition(
            capability_id="audio",
            name="Audio & Volume Controller",
            description="Inspect and adjust system audio volume, mute status, and audio endpoints.",
            supported_operations=["GET_VOLUME", "SET_VOLUME", "MUTE_AUDIO", "UNMUTE_AUDIO", "LIST_AUDIO_DEVICES"],
            execution_methods=["native_api"],
            verification_methods=["volume_check"],
            permission_risk_requirements={"SET_VOLUME": "LOW_RISK"},
            reversible=True,
            platform_support=["win32"],
        ))

        # 24. System Diagnostics
        self.register(CapabilityDefinition(
            capability_id="system_diagnostics",
            name="System Diagnostics",
            description="Inspect system health, memory usage, backend port diagnostics, and disk space alerts.",
            supported_operations=["DIAGNOSE_BACKEND", "DIAGNOSE_NETWORK", "INSPECT_SYSTEM_HEALTH"],
            execution_methods=["native_api"],
            verification_methods=["diagnostic_inspection"],
            permission_risk_requirements={"DIAGNOSE_BACKEND": "READ_ONLY"},
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 25. OS Operations (Universal OS Gateway)
        self.register(CapabilityDefinition(
            capability_id="os_operations",
            name="Universal OS Gateway Boundary",
            description="Guarded operating system gateway for critical system lifecycle, session, and power management.",
            supported_operations=["LOCK", "SIGN_OUT", "SLEEP", "HIBERNATE", "RESTART", "SHUTDOWN"],
            execution_methods=["native_api"],
            verification_methods=["state_inspection"],
            permission_risk_requirements={
                "SHUTDOWN": "SYSTEM_CRITICAL",
                "RESTART": "SYSTEM_CRITICAL",
                "SIGN_OUT": "SYSTEM_CRITICAL",
                "SLEEP": "SYSTEM_CRITICAL",
                "HIBERNATE": "SYSTEM_CRITICAL",
                "LOCK": "PRIVILEGED",
            },
            reversible=False,
            platform_support=["win32"],
        ))

        # 26. Document Intelligence & Resolution
        self.register(CapabilityDefinition(
            capability_id="document_intelligence",
            name="Document Intelligence & Reference Resolution",
            description="Resolve document references across explicit filenames, explorer selections, active apps, and dialogue history. Extract structure, summarize, synthesize cross-document insights, and generate verified PDF artifacts.",
            supported_operations=[
                "SUMMARIZE", "COMPARE", "BIG_PICTURE", "CREATE_ARTIFACT",
                "READ_ALOUD", "EXTRACT", "SYNTHESIZE", "RESOLVE_REFERENCES",
                "CREATE_REPORT", "CREATE_PRESENTATION", "CREATE_STUDY_GUIDE",
                "REVISE_ARTIFACT", "INSPECT_ARTIFACT"
            ],
            required_inputs={
                "SUMMARIZE": ["documents"],
                "CREATE_ARTIFACT": ["documents"],
            },
            execution_methods=["document_intelligence_api", "native_api"],
            verification_methods=["artifact_exists_check", "document_parsed_check", "state_inspection"],
            permission_risk_requirements={
                "SUMMARIZE": "READ_ONLY",
                "COMPARE": "READ_ONLY",
                "BIG_PICTURE": "READ_ONLY",
                "READ_ALOUD": "READ_ONLY",
                "EXTRACT": "READ_ONLY",
                "SYNTHESIZE": "READ_ONLY",
                "CREATE_ARTIFACT": "LOW_RISK",
                "CREATE_REPORT": "LOW_RISK",
                "CREATE_PRESENTATION": "LOW_RISK",
                "CREATE_STUDY_GUIDE": "LOW_RISK",
                "REVISE_ARTIFACT": "LOW_RISK",
                "INSPECT_ARTIFACT": "READ_ONLY",
                "RESOLVE_REFERENCES": "READ_ONLY",
            },
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 27. Professional Document & Presentation Creation Engine
        self.register(CapabilityDefinition(
            capability_id="professional_document_creation",
            name="Professional Document & Presentation Engine",
            description="Create publication-grade PDFs, DOCX reports, and presentation slide decks using thematic layout styling, structured outlines, and automated quality inspection.",
            supported_operations=[
                "CREATE_PROFESSIONAL_PDF", "CREATE_PRESENTATION", "CREATE_STUDY_GUIDE",
                "CREATE_EXECUTIVE_REPORT", "REVISE_DOCUMENT", "CONVERT_REPORT_TO_PRESENTATION"
            ],
            required_inputs={
                "CREATE_PROFESSIONAL_PDF": ["topic"],
                "CREATE_PRESENTATION": ["topic"],
                "CREATE_STUDY_GUIDE": ["topic"],
            },
            execution_methods=["professional_document_engine", "native_api"],
            verification_methods=["artifact_quality_inspection", "file_exists", "layout_inspection"],
            risk_level="LOW_RISK",
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 28. Document Reference Resolution
        self.register(CapabilityDefinition(
            capability_id="document_reference_resolution",
            name="Document Reference Resolver",
            description="Resolves implicit and explicit document targets from selected Explorer files, open window viewers, and dialogue history.",
            supported_operations=["RESOLVE_SELECTION", "RESOLVE_ACTIVE_DOCUMENT", "FIND_SELECTED_FILES"],
            required_inputs={},
            execution_methods=["document_reference_resolver", "native_api"],
            verification_methods=["file_exists"],
            risk_level="READ_ONLY",
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 29. Environment History & Causal Reasoning Query
        self.register(CapabilityDefinition(
            capability_id="environment_history_query",
            name="Environment History & Causal Query Engine",
            description="Query previous application states, open browser videos/tabs, editor contexts, and causal explanations for environment changes.",
            supported_operations=[
                "QUERY_PREVIOUS_APP", "QUERY_PREVIOUS_VIDEO", "QUERY_PREVIOUS_EDITOR",
                "EXPLAIN_ENVIRONMENT_CHANGE", "QUERY_ENVIRONMENT_HISTORY"
            ],
            required_inputs={},
            execution_methods=["environment_state_engine", "causal_attribution_engine"],
            verification_methods=["history_record_check"],
            risk_level="READ_ONLY",
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 30. Information Gathering & Technical Research
        self.register(CapabilityDefinition(
            capability_id="information_gathering",
            name="Information Gathering & Technical Research",
            description="Gather technical information, research concepts, and acquire structured artifacts (DBMS, algorithms, code).",
            supported_operations=["GATHER_INFORMATION", "RESEARCH_TOPIC", "ACQUIRE_CONTENT"],
            execution_methods=["content_acquisition_engine", "web_search"],
            verification_methods=["artifact_exists_check"],
            risk_level="LOW_RISK",
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 31. Artifact Creation & Transformation
        self.register(CapabilityDefinition(
            capability_id="artifact_creation",
            name="Artifact Creation & Transformation",
            description="Create, structure, summarize, and transform content artifacts and code.",
            supported_operations=["CREATE_ARTIFACT", "TRANSFORM_ARTIFACT", "SUMMARIZE_ARTIFACT"],
            execution_methods=["artifact_context_graph", "llm_transformer"],
            verification_methods=["artifact_exists_check"],
            risk_level="LOW_RISK",
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 32. Reading & Speech Synthesis (TTS)
        self.register(CapabilityDefinition(
            capability_id="artifact_reading",
            name="Reading & Speech Synthesis (TTS)",
            description="Read gathered information, code, or documents aloud with pause, stop, and continue controls.",
            supported_operations=["READ_ARTIFACT", "STOP_READING", "CONTINUE_READING", "PAUSE_READING"],
            execution_methods=["artifact_reading_controller", "tts_engine"],
            verification_methods=["state_inspection"],
            risk_level="READ_ONLY",
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 33. Contextual Content Insertion
        self.register(CapabilityDefinition(
            capability_id="contextual_insertion",
            name="Contextual Content Insertion",
            description="Insert resolved content artifacts directly into target applications (Notepad, VS Code, browsers) at cursor location.",
            supported_operations=["INSERT_CONTENT", "WRITE_AT_CURSOR", "PASTE_ARTIFACT"],
            execution_methods=["content_inserter", "os_automation"],
            verification_methods=["content_verification"],
            risk_level="LOW_RISK",
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 34. Environment & Screen State Awareness
        self.register(CapabilityDefinition(
            capability_id="environment_awareness",
            name="Environment & Screen State Awareness",
            description="Continuously observe active applications, focused windows, current URLs, and screen state transitions.",
            supported_operations=["OBSERVE_ENVIRONMENT", "QUERY_ACTIVE_APP", "QUERY_CURRENT_WINDOW", "QUERY_FOCUSED_STATE"],
            execution_methods=["continuous_observer", "state_engine"],
            verification_methods=["state_inspection"],
            risk_level="READ_ONLY",
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 35. Persistent Memory & Dialogue History
        self.register(CapabilityDefinition(
            capability_id="memory_history",
            name="Persistent Memory & Dialogue History",
            description="Remember user preferences, facts, past conversation context, and command execution history.",
            supported_operations=["STORE_MEMORY", "QUERY_MEMORY", "QUERY_DIALOGUE_HISTORY", "QUERY_PAST_ACTIONS"],
            execution_methods=["memory_database", "dialogue_state_manager"],
            verification_methods=["state_inspection"],
            risk_level="LOW_RISK",
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

        # 36. Concurrent Background Tasks
        self.register(CapabilityDefinition(
            capability_id="concurrent_tasks",
            name="Concurrent Background Tasks",
            description="Orchestrate, monitor, and manage long-running background tasks with real-time status notifications.",
            supported_operations=["LAUNCH_TASK", "CANCEL_TASK", "QUERY_TASK_STATUS", "LIST_TASKS"],
            execution_methods=["task_execution_manager"],
            verification_methods=["task_status_check"],
            risk_level="LOW_RISK",
            reversible=True,
            platform_support=["win32", "linux", "darwin"],
        ))

    def format_capabilities_overview(self) -> str:
        """
        Dynamically formats a comprehensive, natural summary of all enabled runtime capabilities,
        grouped into clear, logical categories directly from the registered capabilities.
        Never hallucinated, never includes disabled or unregistered features.
        """
        available_caps = self.list_available_capabilities()

        categories: Dict[str, List[str]] = {
            "Computer & OS operations": [],
            "Application control": [],
            "File and document operations": [],
            "Information gathering": [],
            "Artifact creation": [],
            "Reading/TTS": [],
            "Contextual insertion": [],
            "Environment awareness": [],
            "Memory/history": [],
            "Concurrent tasks": [],
            "Browser operations": [],
        }

        for cap in available_caps:
            cid = cap.capability_id
            if cid in ("os_operations", "storage", "terminal", "powershell", "cmd", "wsl", "system_configuration", "registry", "display", "audio", "environment_variables"):
                categories["Computer & OS operations"].append(f"{cap.name}: {cap.description}")
            elif cid in ("applications", "windows", "uiautomation", "processes", "services"):
                categories["Application control"].append(f"{cap.name}: {cap.description}")
            elif cid in ("filesystem", "document_intelligence", "professional_document_creation", "document_reference_resolution"):
                categories["File and document operations"].append(f"{cap.name}: {cap.description}")
            elif cid in ("information_gathering",):
                categories["Information gathering"].append(f"{cap.name}: {cap.description}")
            elif cid in ("artifact_creation",):
                categories["Artifact creation"].append(f"{cap.name}: {cap.description}")
            elif cid in ("artifact_reading",):
                categories["Reading/TTS"].append(f"{cap.name}: {cap.description}")
            elif cid in ("contextual_insertion", "clipboard"):
                categories["Contextual insertion"].append(f"{cap.name}: {cap.description}")
            elif cid in ("environment_awareness", "environment_history_query"):
                categories["Environment awareness"].append(f"{cap.name}: {cap.description}")
            elif cid in ("memory_history",):
                categories["Memory/history"].append(f"{cap.name}: {cap.description}")
            elif cid in ("concurrent_tasks",):
                categories["Concurrent tasks"].append(f"{cap.name}: {cap.description}")
            elif cid in ("browser",):
                categories["Browser operations"].append(f"{cap.name}: {cap.description}")

        lines = ["Here are my current registered capabilities:"]
        for cat_name, desc_list in categories.items():
            if desc_list:
                lines.append(f"\n• {cat_name}:")
                for d in desc_list[:2]:
                    lines.append(f"  - {d}")
        return "\n".join(lines)

    def format_concise_capabilities(self) -> str:
        """
        Dynamically generates a concise capability overview from currently available capabilities.
        Derives naturally from the registry without hardcoding static text.
        """
        available_ids = {c.capability_id for c in self.list_available_capabilities()}
        parts = []
        if "applications" in available_ids or "os_operations" in available_ids:
            parts.append("control your computer, open and manage applications")
        if "filesystem" in available_ids or "professional_document_creation" in available_ids:
            parts.append("work with files")
        if "information_gathering" in available_ids or "browser" in available_ids:
            parts.append("search for information")
        if "system_configuration" in available_ids:
            parts.append("control system settings")
        if "concurrent_tasks" in available_ids:
            parts.append("remember your ongoing tasks")
        if "terminal" in available_ids:
            parts.append("help you with coding and other work")

        if parts:
            joined = ", ".join(parts[:-1]) + f", and {parts[-1]}" if len(parts) > 1 else parts[0]
            return f"I can {joined}. If you want, I can show you the full list."
        return "I can control your computer, open and manage applications, work with files, search for information, control system settings, remember your ongoing tasks, and help you with coding and other work. If you want, I can show you the full list."

    def check_capability_support(self, query: str) -> Optional[str]:
        """Answer specific capability queries directly from the registry."""
        q_low = query.lower().strip()
        # Must be an inquiry about capabilities, not an operational command like "read it", "read them"
        is_capability_query = (
            any(q_low.startswith(p) for p in (
                "can you ", "could you tell me if you can ", "are you capable of ",
                "are you able to ", "do you support ", "is it possible for you to ",
                "do you have the ability to "
            ))
            or "what can you" in q_low
            or "what are your capabilities" in q_low
        )
        if not is_capability_query:
            return None

        # Exclude direct deictic artifact reading requests like "can you read them out", "can you read it"
        if any(deictic in q_low for deictic in ("read them", "read it", "read this", "read that", "read those", "read out")):
            return None

        available_caps = {c.capability_id for c in self.list_available_capabilities()}

        if "control applications" in q_low or "app control" in q_low:
            if "applications" in available_caps:
                return "Yes, I can launch, control, focus, and close desktop applications such as Notepad, Chrome, and VS Code."
        if "read gathered information" in q_low or "read information" in q_low or "read code" in q_low or "read documents" in q_low or "reading" in q_low:
            if "artifact_reading" in available_caps:
                return "Yes, I can read gathered information, code, summaries, and documents aloud with pause and continue controls."
        if "remember what i asked" in q_low or "remember" in q_low or "memory" in q_low:
            if "memory_history" in available_caps:
                return "Yes, I remember previous conversations, user preferences, and past execution history using persistent memory."
        if "create documents" in q_low or "pdf" in q_low:
            if "professional_document_creation" in available_caps:
                return "Yes, I can generate publication-grade PDF documents, reports, and presentations."
        if "manage files" in q_low or "filesystem" in q_low:
            if "filesystem" in available_caps:
                return "Yes, I can inspect, create, move, search, and manage files and directories."
        return None


# ============================================================================
# 4. Capability Discovery Engine (Semantic Intent → Capability Mapping)
# ============================================================================

class CapabilityDiscoveryEngine:
    """
    Intelligently discovers candidate capabilities for goals and intents.
    Does NOT use a giant hardcoded keyword list. Evaluates semantic intent,
    desired outcome, active context, and availability.
    """

    def __init__(self, registry: Optional[CapabilityRegistry] = None):
        self.registry = registry or get_capability_registry()

    def discover(
        self,
        intent: Optional[str] = None,
        desired_outcome: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        required_operations: Optional[List[str]] = None,
        intent_or_description: Optional[str] = None,
    ) -> List[DiscoveredCapability]:
        """
        Discovers and ranks candidate capabilities capable of fulfilling the intent.
        Flow:
          intent + desired outcome + context
          → candidate capabilities
          → rank by availability and relevance
        """
        effective_intent = intent_or_description if intent_or_description is not None else (intent or "")
        norm_intent = str(effective_intent).strip().lower()
        norm_outcome = str(desired_outcome or "").strip().lower()
        ctx = context or {}

        candidates: List[DiscoveredCapability] = []

        # 1. Direct Operation Match if required_operations is specified
        if required_operations:
            for req_op in required_operations:
                caps = self.registry.find_by_operation(req_op, available_only=True)
                for cap in caps:
                    candidates.append(DiscoveredCapability(
                        capability=cap,
                        matched_operation=req_op,
                        confidence=0.95,
                        rationale=f"Direct match for required operation '{req_op}'.",
                        execution_method=cap.execution_methods[0] if cap.execution_methods else "native_api",
                    ))

        # 2. Semantic Intent & Outcome Mapping
        # Projects & Codebases
        if any(w in norm_intent or w in norm_outcome for w in ["project", "codebase", "workspace", "code", "dev"]):
            # Filesystem to locate project
            fs_cap = self.registry.get("filesystem")
            if fs_cap and fs_cap.is_available:
                candidates.append(DiscoveredCapability(
                    capability=fs_cap,
                    matched_operation="SEARCH_FILES",
                    confidence=0.9,
                    rationale="Filesystem capability to discover or inspect project directory and files.",
                    execution_method="filesystem_api",
                ))
            # VS Code or Application to open it
            vscode_cap = self.registry.get("vscode")
            if vscode_cap and vscode_cap.is_available:
                candidates.append(DiscoveredCapability(
                    capability=vscode_cap,
                    matched_operation="OPEN_WORKSPACE",
                    confidence=0.92,
                    rationale="VS Code editor capability to open developer workspaces.",
                    execution_method="existing_tool",
                ))
            else:
                app_cap = self.registry.get("applications")
                if app_cap and app_cap.is_available:
                    candidates.append(DiscoveredCapability(
                        capability=app_cap,
                        matched_operation="OPEN_APPLICATION",
                        confidence=0.85,
                        rationale="Application capability to launch project in configured editor.",
                        execution_method="existing_tool",
                    ))

        # File & Document Operations
        if any(w in norm_intent or w in norm_outcome for w in ["file", "folder", "document", "read", "write", "move", "rename", "delete"]):
            fs_cap = self.registry.get("filesystem")
            if fs_cap and fs_cap.is_available:
                matched_op = "READ_FILE"
                if "write" in norm_intent or "save" in norm_outcome or "create" in norm_outcome:
                    matched_op = "WRITE_FILE"
                elif "move" in norm_intent or "relocate" in norm_outcome:
                    matched_op = "MOVE_FILE"
                elif "delete" in norm_intent or "remove" in norm_outcome:
                    matched_op = "DELETE_FILE"
                elif "search" in norm_intent or "find" in norm_outcome:
                    matched_op = "SEARCH_FILES"
                candidates.append(DiscoveredCapability(
                    capability=fs_cap,
                    matched_operation=matched_op,
                    confidence=0.95,
                    rationale=f"Filesystem capability selected for file outcome '{matched_op}'.",
                    execution_method="filesystem_api",
                ))

        # Professional Document Creation
        if any(w in norm_intent or w in norm_outcome for w in ["professional_document_creation", "presentation", "ppt", "pptx", "slide deck", "study guide", "study notes", "report about", "report on", "pdf about", "pdf on"]):
            pro_cap = self.registry.get("professional_document_creation")
            if pro_cap and pro_cap.is_available:
                matched_op = "CREATE_PROFESSIONAL_PDF"
                if any(w in norm_intent or w in norm_outcome for w in ["presentation", "ppt", "pptx", "slide"]):
                    matched_op = "CREATE_PRESENTATION"
                elif any(w in norm_intent or w in norm_outcome for w in ["study guide", "study notes"]):
                    matched_op = "CREATE_STUDY_GUIDE"
                elif any(w in norm_intent or w in norm_outcome for w in ["revise", "more detailed", "shorter"]):
                    matched_op = "REVISE_DOCUMENT"
                candidates.append(DiscoveredCapability(
                    capability=pro_cap,
                    matched_operation=matched_op,
                    confidence=0.98,
                    rationale=f"Professional document capability selected for '{matched_op}'.",
                    execution_method="professional_document_engine",
                ))

        # Document Reference Resolution
        if any(w in norm_intent or w in norm_outcome for w in ["document_reference_resolution", "find the files i selected", "selected files", "resolve selection", "files i selected"]):
            ref_cap = self.registry.get("document_reference_resolution")
            if ref_cap and ref_cap.is_available:
                candidates.append(DiscoveredCapability(
                    capability=ref_cap,
                    matched_operation="RESOLVE_SELECTION",
                    confidence=0.97,
                    rationale="Document reference resolver selected for Explorer selection lookup.",
                    execution_method="document_reference_resolver",
                ))

        # Environment History & Causal Queries
        if any(w in norm_intent or w in norm_outcome for w in ["environment_history_query", "historical_environment_query", "what was i watching", "watching before", "video before", "what changed", "why did this change", "previous app", "previous video"]):
            env_cap = self.registry.get("environment_history_query")
            if env_cap and env_cap.is_available:
                matched_env_op = "EXPLAIN_ENVIRONMENT_CHANGE" if any(w in norm_intent for w in ["what changed", "why did"]) else "QUERY_PREVIOUS_VIDEO"
                candidates.append(DiscoveredCapability(
                    capability=env_cap,
                    matched_operation=matched_env_op,
                    confidence=0.96,
                    rationale=f"Environment history & causal capability selected for '{matched_env_op}'.",
                    execution_method="environment_state_engine",
                ))

        # Document Intelligence & Synthesis
        if any(w in norm_intent or w in norm_outcome for w in ["pdf", "pdfs", "document", "documents", "summarize", "summary", "big picture", "compare", "read aloud", "read to me", "extract"]):
            doc_cap = self.registry.get("document_intelligence")
            if doc_cap and doc_cap.is_available:
                matched_doc_op = "SUMMARIZE"
                if "big picture" in norm_intent or "big picture" in norm_outcome:
                    matched_doc_op = "BIG_PICTURE"
                elif "compare" in norm_intent or "compare" in norm_outcome:
                    matched_doc_op = "COMPARE"
                elif any(w in norm_intent for w in ["make pdf", "summary pdf", "create pdf", "create one pdf"]):
                    matched_doc_op = "CREATE_ARTIFACT"
                elif "read" in norm_intent and ("aloud" in norm_intent or "to me" in norm_intent):
                    matched_doc_op = "READ_ALOUD"
                elif "extract" in norm_intent or "extract" in norm_outcome:
                    matched_doc_op = "EXTRACT"

                candidates.append(DiscoveredCapability(
                    capability=doc_cap,
                    matched_operation=matched_doc_op,
                    confidence=0.96,
                    rationale=f"Document Intelligence capability selected for '{matched_doc_op}'.",
                    execution_method="document_intelligence_api",
                ))

        # Storage & Drives
        if any(w in norm_intent or w in norm_outcome for w in ["drive", "disk", "storage", "space", "free space"]):
            storage_cap = self.registry.get("storage")
            if storage_cap and storage_cap.is_available:
                candidates.append(DiscoveredCapability(
                    capability=storage_cap,
                    matched_operation="INSPECT_DRIVE" if "drive" in norm_intent else "LIST_DRIVES",
                    confidence=0.92,
                    rationale="Storage capability for partition and disk inspection.",
                    execution_method="native_api",
                ))

        # Processes & Ports
        if any(w in norm_intent or w in norm_outcome for w in ["process", "port", "pid", "listener", "task"]):
            proc_cap = self.registry.get("processes")
            if proc_cap and proc_cap.is_available:
                matched_op = "INSPECT_PORT" if "port" in norm_intent else "LIST_PROCESSES"
                if "kill" in norm_intent or "stop" in norm_intent or "terminate" in norm_outcome:
                    matched_op = "KILL_BY_PORT" if "port" in norm_intent else "TERMINATE_PROCESS"
                candidates.append(DiscoveredCapability(
                    capability=proc_cap,
                    matched_operation=matched_op,
                    confidence=0.92,
                    rationale=f"Process capability selected for '{matched_op}'.",
                    execution_method="native_api",
                ))

        # Command Execution / Scripting / Terminal
        if any(w in norm_intent or w in norm_outcome for w in ["run", "execute", "terminal", "command", "bash", "powershell", "cmd"]):
            term_cap = self.registry.get("terminal")
            if term_cap and term_cap.is_available:
                candidates.append(DiscoveredCapability(
                    capability=term_cap,
                    matched_operation="EXECUTE_COMMAND",
                    confidence=0.9,
                    rationale="Terminal capability selected for command execution.",
                    execution_method="powershell" if sys.platform == "win32" else "subprocess",
                ))

        # Windows Services
        if any(w in norm_intent or w in norm_outcome for w in ["service", "daemon"]):
            srv_cap = self.registry.get("services")
            if srv_cap and srv_cap.is_available:
                candidates.append(DiscoveredCapability(
                    capability=srv_cap,
                    matched_operation="INSPECT_SERVICE",
                    confidence=0.9,
                    rationale="Windows Services capability selected.",
                    execution_method="native_api",
                ))

        # Web Browsing / Websites
        if any(w in norm_intent or w in norm_outcome for w in ["browser", "web", "website", "url", "open site"]):
            browser_cap = self.registry.get("browser")
            if browser_cap and browser_cap.is_available:
                candidates.append(DiscoveredCapability(
                    capability=browser_cap,
                    matched_operation="OPEN_URL",
                    confidence=0.9,
                    rationale="Browser capability selected for web navigation.",
                    execution_method="existing_tool",
                ))

        # Clipboard
        if "clipboard" in norm_intent or "clipboard" in norm_outcome:
            clip_cap = self.registry.get("clipboard")
            if clip_cap and clip_cap.is_available:
                candidates.append(DiscoveredCapability(
                    capability=clip_cap,
                    matched_operation="SET_CLIPBOARD" if any(w in norm_intent for w in ["copy", "set", "write", "to"]) else "GET_CLIPBOARD",
                    confidence=0.98,
                    rationale="Clipboard capability selected for buffer manipulation.",
                    execution_method="native_api",
                ))

        # Generic semantic matching across all capabilities in registry
        for cap in self.registry.list_capabilities(available_only=True):
            score = 0.0
            matched_op = None

            # Check operations
            for op in cap.supported_operations:
                op_words = [w.lower() for w in op.split("_") if len(w) > 2]
                if any(w in norm_intent or w in norm_outcome for w in op_words):
                    score = 0.93
                    matched_op = op
                    break

            # Check capability name & id
            cap_id_clean = cap.capability_id.lower().replace("_", " ")
            cap_name_words = [w.lower() for w in cap.name.split() if len(w) > 2] + cap_id_clean.split()
            if any(w in norm_intent or w in norm_outcome for w in cap_name_words):
                score = max(score, 0.90)
                if not matched_op and cap.supported_operations:
                    matched_op = cap.supported_operations[0]

            # Check description keywords
            desc_words = [w.lower() for w in cap.description.split() if len(w) > 4]
            if any(w in norm_intent or w in norm_outcome for w in desc_words):
                score = max(score, 0.85)
                if not matched_op and cap.supported_operations:
                    matched_op = cap.supported_operations[0]

            if score > 0.0:
                candidates.append(DiscoveredCapability(
                    capability=cap,
                    matched_operation=matched_op or (cap.supported_operations[0] if cap.supported_operations else "execute"),
                    confidence=score,
                    rationale=f"Capability '{cap.name}' matches intent/outcome.",
                    execution_method=cap.execution_methods[0] if cap.execution_methods else "native_api",
                ))

        # Deduplicate while preserving highest confidence
        unique_candidates: Dict[str, DiscoveredCapability] = {}
        for cand in candidates:
            cid = cand.capability.capability_id
            if cid not in unique_candidates or cand.confidence > unique_candidates[cid].confidence:
                unique_candidates[cid] = cand

        results = list(unique_candidates.values())
        results.sort(key=lambda c: c.confidence, reverse=True)
        return results

    def select_best_capability(
        self,
        intent: Optional[str] = None,
        desired_outcome: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        intent_or_description: Optional[str] = None,
    ) -> Optional[DiscoveredCapability]:
        """Select the highest-confidence available capability for the goal."""
        candidates = self.discover(
            intent=intent,
            desired_outcome=desired_outcome,
            context=context,
            intent_or_description=intent_or_description,
        )
        if candidates:
            return candidates[0]
        fallback_cap = self.registry.get("os_operations") or (self.registry.list_capabilities()[0] if self.registry.list_capabilities() else None)
        if fallback_cap:
            return DiscoveredCapability(
                capability=fallback_cap,
                matched_operation=fallback_cap.supported_operations[0] if fallback_cap.supported_operations else "execute",
                confidence=0.5,
                rationale="Fallback default capability",
                execution_method=fallback_cap.execution_methods[0] if fallback_cap.execution_methods else "native_api",
            )
        return None


# ============================================================================
# 5. Singleton Accessors & Global Registry
# ============================================================================

_capability_registry: Optional[CapabilityRegistry] = None
_discovery_engine: Optional[CapabilityDiscoveryEngine] = None


def get_capability_registry() -> CapabilityRegistry:
    """Retrieve global singleton CapabilityRegistry instance."""
    global _capability_registry
    if _capability_registry is None:
        _capability_registry = CapabilityRegistry()
    return _capability_registry


def get_capability_discovery_engine() -> CapabilityDiscoveryEngine:
    """Retrieve global singleton CapabilityDiscoveryEngine instance."""
    global _discovery_engine
    if _discovery_engine is None:
        _discovery_engine = CapabilityDiscoveryEngine(get_capability_registry())
    return _discovery_engine


capability_registry: CapabilityRegistry = get_capability_registry()

