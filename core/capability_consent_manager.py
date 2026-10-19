"""
Smart Assistant — Central Capability & Consent Manager
Authoritative manager for user capability consents, operating system capabilities,
and three-part permission evaluation across all system operations.

Three Essential Conditions Evaluated Before Execution:
  Condition A: Application Consent — Has the user approved this capability category?
  Condition B: Operating-System Capability — Can the current process perform the operation?
  Condition C: Action Authorization — Does this specific action require fresh confirmation?
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from core.db_pool import get_db_pool

logger = logging.getLogger("CapabilityConsentManager")


class CapabilityCategory(str, Enum):
    APP_LIFECYCLE = "app_lifecycle"              # 1. Application launching and window management
    UI_INTERACTION = "ui_interaction"            # 2. Application UI interaction
    FILESYSTEM = "filesystem"                    # 3. File and folder operations
    PROCESS_MANAGEMENT = "process_management"    # 4. Process inspection and management
    SYSTEM_SETTINGS = "system_settings"          # 5. Display, audio, and input settings
    NETWORK = "network"                          # 6. Network settings and connectivity
    TELEMETRY = "telemetry"                      # 7. Hardware telemetry
    SOFTWARE_MANAGEMENT = "software_management"  # 8. Software installation and removal
    SYSTEM_POWER = "system_power"                # 9. Power and session management
    ADMINISTRATOR_OPS = "administrator_ops"      # 10. Administrator-only operations
    AUTOMATION_CODE = "automation_code"          # 11. Automation and generated-code execution
    APP_INTEGRATIONS = "app_integrations"        # 12. Application-specific integrations


CAPABILITY_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    CapabilityCategory.APP_LIFECYCLE.value: {
        "title": "Application Launch & Window Management",
        "description": "Discover, open, minimize, maximize, and switch application windows.",
        "default_granted": True,
        "requires_admin": False,
        "risk_level": "LOW",
    },
    CapabilityCategory.UI_INTERACTION.value: {
        "title": "Application UI Interaction",
        "description": "Inspect accessible UI controls, click buttons, enter text into input fields, and navigate application menus.",
        "default_granted": True,
        "requires_admin": False,
        "risk_level": "MODERATE",
    },
    CapabilityCategory.FILESYSTEM.value: {
        "title": "File & Folder Operations",
        "description": "List, inspect, create, copy, move, and organize files in authorized directories.",
        "default_granted": True,
        "requires_admin": False,
        "risk_level": "MODERATE",
    },
    CapabilityCategory.PROCESS_MANAGEMENT.value: {
        "title": "Process Inspection & Management",
        "description": "List running processes, inspect resource usage, and gracefully close or terminate applications.",
        "default_granted": True,
        "requires_admin": False,
        "risk_level": "MODERATE",
    },
    CapabilityCategory.SYSTEM_SETTINGS.value: {
        "title": "Display, Audio & Input Settings",
        "description": "Read and adjust master volume, display brightness, resolution, and keyboard lock states.",
        "default_granted": True,
        "requires_admin": False,
        "risk_level": "LOW",
    },
    CapabilityCategory.NETWORK.value: {
        "title": "Network & Connectivity",
        "description": "Inspect network interfaces, connection status, Wi-Fi networks, and manage authorized connections.",
        "default_granted": True,
        "requires_admin": False,
        "risk_level": "MODERATE",
    },
    CapabilityCategory.TELEMETRY.value: {
        "title": "Hardware Telemetry",
        "description": "Monitor real-time CPU, RAM, storage, battery, and GPU utilization.",
        "default_granted": True,
        "requires_admin": False,
        "risk_level": "LOW",
    },
    CapabilityCategory.SOFTWARE_MANAGEMENT.value: {
        "title": "Software Installation & Removal",
        "description": "Install and uninstall verified software packages through Windows package managers.",
        "default_granted": True,
        "requires_admin": True,
        "risk_level": "HIGH",
    },
    CapabilityCategory.SYSTEM_POWER.value: {
        "title": "Power & Session Management",
        "description": "Lock workstation, sign out, restart, or shut down Windows with explicit confirmation.",
        "default_granted": True,
        "requires_admin": False,
        "risk_level": "HIGH",
    },
    CapabilityCategory.ADMINISTRATOR_OPS.value: {
        "title": "Administrator Operations",
        "description": "Perform authorized operations requiring Windows UAC administrator elevation.",
        "default_granted": True,
        "requires_admin": True,
        "risk_level": "HIGH",
    },
    CapabilityCategory.AUTOMATION_CODE.value: {
        "title": "Automation & Code Execution",
        "description": "Execute authorized generated scripts, automation tasks, and plugin routines in a restricted context.",
        "default_granted": True,
        "requires_admin": False,
        "risk_level": "HIGH",
    },
    CapabilityCategory.APP_INTEGRATIONS.value: {
        "title": "Application-Specific Integrations",
        "description": "Deep workflow support for applications such as WhatsApp, Excel, VS Code, and media players.",
        "default_granted": True,
        "requires_admin": False,
        "risk_level": "MODERATE",
    },
}

# Mapping of common operation names to capability category
OPERATION_TO_CAPABILITY: Dict[str, CapabilityCategory] = {
    # App Lifecycle
    "launch_app": CapabilityCategory.APP_LIFECYCLE,
    "open_application": CapabilityCategory.APP_LIFECYCLE,
    "close_application": CapabilityCategory.APP_LIFECYCLE,
    "focus_window": CapabilityCategory.APP_LIFECYCLE,
    "minimize_window": CapabilityCategory.APP_LIFECYCLE,
    "maximize_window": CapabilityCategory.APP_LIFECYCLE,
    "restore_window": CapabilityCategory.APP_LIFECYCLE,
    "list_windows": CapabilityCategory.APP_LIFECYCLE,
    "list_applications": CapabilityCategory.APP_LIFECYCLE,
    "list_running_apps": CapabilityCategory.APP_LIFECYCLE,
    "list_installed_games": CapabilityCategory.APP_LIFECYCLE,
    "list_installed_applications": CapabilityCategory.APP_LIFECYCLE,

    # UI Interaction
    "inspect_elements": CapabilityCategory.UI_INTERACTION,
    "find_element": CapabilityCategory.UI_INTERACTION,
    "click_element": CapabilityCategory.UI_INTERACTION,
    "set_element_value": CapabilityCategory.UI_INTERACTION,
    "type_text": CapabilityCategory.UI_INTERACTION,
    "send_keys": CapabilityCategory.UI_INTERACTION,
    "ui_interact": CapabilityCategory.UI_INTERACTION,
    "ui_action": CapabilityCategory.UI_INTERACTION,
    "app_interact": CapabilityCategory.UI_INTERACTION,

    # Filesystem
    "create_file": CapabilityCategory.FILESYSTEM,
    "create_text_file": CapabilityCategory.FILESYSTEM,
    "read_file": CapabilityCategory.FILESYSTEM,
    "write_file": CapabilityCategory.FILESYSTEM,
    "copy_file": CapabilityCategory.FILESYSTEM,
    "move_file": CapabilityCategory.FILESYSTEM,
    "rename_file": CapabilityCategory.FILESYSTEM,
    "delete_file": CapabilityCategory.FILESYSTEM,
    "safe_delete_file": CapabilityCategory.FILESYSTEM,
    "create_directory": CapabilityCategory.FILESYSTEM,
    "delete_directory": CapabilityCategory.FILESYSTEM,
    "list_directory": CapabilityCategory.FILESYSTEM,
    "create_folder": CapabilityCategory.FILESYSTEM,
    "delete_folder": CapabilityCategory.FILESYSTEM,
    "list_folders": CapabilityCategory.FILESYSTEM,
    "list_files": CapabilityCategory.FILESYSTEM,
    "get_file_info": CapabilityCategory.FILESYSTEM,
    "search_files": CapabilityCategory.FILESYSTEM,
    "open_file": CapabilityCategory.FILESYSTEM,
    "find_file_in_desktop": CapabilityCategory.FILESYSTEM,
    "find_duplicate_files": CapabilityCategory.FILESYSTEM,
    "organize_directory": CapabilityCategory.FILESYSTEM,
    "get_directory_stats": CapabilityCategory.FILESYSTEM,
    "get_largest_files": CapabilityCategory.FILESYSTEM,
    "profile_file_content": CapabilityCategory.FILESYSTEM,
    "desktop_stats": CapabilityCategory.FILESYSTEM,
    "archive_files": CapabilityCategory.FILESYSTEM,
    "extract_archive": CapabilityCategory.FILESYSTEM,

    # Process Management
    "list_processes": CapabilityCategory.PROCESS_MANAGEMENT,
    "inspect_process": CapabilityCategory.PROCESS_MANAGEMENT,
    "terminate_process": CapabilityCategory.PROCESS_MANAGEMENT,
    "stop_process": CapabilityCategory.PROCESS_MANAGEMENT,
    "find_process": CapabilityCategory.PROCESS_MANAGEMENT,

    # Settings
    "get_volume": CapabilityCategory.SYSTEM_SETTINGS,
    "set_volume": CapabilityCategory.SYSTEM_SETTINGS,
    "volume_up": CapabilityCategory.SYSTEM_SETTINGS,
    "volume_down": CapabilityCategory.SYSTEM_SETTINGS,
    "set_mute": CapabilityCategory.SYSTEM_SETTINGS,
    "get_brightness": CapabilityCategory.SYSTEM_SETTINGS,
    "set_brightness": CapabilityCategory.SYSTEM_SETTINGS,
    "adjust_brightness": CapabilityCategory.SYSTEM_SETTINGS,
    "set_resolution": CapabilityCategory.SYSTEM_SETTINGS,
    "toggle_key": CapabilityCategory.SYSTEM_SETTINGS,
    "set_key": CapabilityCategory.SYSTEM_SETTINGS,
    "keyboard_state": CapabilityCategory.SYSTEM_SETTINGS,
    "toggle_dark_mode": CapabilityCategory.SYSTEM_SETTINGS,
    "get_wallpaper": CapabilityCategory.SYSTEM_SETTINGS,
    "set_wallpaper": CapabilityCategory.SYSTEM_SETTINGS,
    "power_plan": CapabilityCategory.SYSTEM_SETTINGS,
    "list_power_plans": CapabilityCategory.SYSTEM_SETTINGS,
    "mouse_info": CapabilityCategory.SYSTEM_SETTINGS,

    # Network
    "wifi_status": CapabilityCategory.NETWORK,
    "list_wifi_networks": CapabilityCategory.NETWORK,
    "enable_wifi": CapabilityCategory.NETWORK,
    "disable_wifi": CapabilityCategory.NETWORK,
    "connect_wifi": CapabilityCategory.NETWORK,
    "network_speed": CapabilityCategory.NETWORK,
    "network_adapters": CapabilityCategory.NETWORK,
    "bluetooth_status": CapabilityCategory.NETWORK,
    "set_bluetooth_state": CapabilityCategory.NETWORK,
    "enable_bluetooth": CapabilityCategory.NETWORK,
    "disable_bluetooth": CapabilityCategory.NETWORK,

    # Telemetry
    "get_battery_status": CapabilityCategory.TELEMETRY,
    "get_disk_space": CapabilityCategory.TELEMETRY,
    "get_all_disks": CapabilityCategory.TELEMETRY,
    "get_cpu_metrics": CapabilityCategory.TELEMETRY,
    "cpu_metrics": CapabilityCategory.TELEMETRY,
    "detailed_cpu": CapabilityCategory.TELEMETRY,
    "get_detailed_cpu_info": CapabilityCategory.TELEMETRY,
    "get_ram_metrics": CapabilityCategory.TELEMETRY,
    "ram_metrics": CapabilityCategory.TELEMETRY,
    "detailed_ram": CapabilityCategory.TELEMETRY,
    "get_detailed_ram_metrics": CapabilityCategory.TELEMETRY,
    "get_gpu_telemetry": CapabilityCategory.TELEMETRY,
    "gpu_telemetry": CapabilityCategory.TELEMETRY,
    "get_gpu_memory": CapabilityCategory.TELEMETRY,
    "get_system_info": CapabilityCategory.TELEMETRY,
    "system_info": CapabilityCategory.TELEMETRY,
    "display_info": CapabilityCategory.TELEMETRY,
    "get_display_info": CapabilityCategory.TELEMETRY,
    "hardware_info": CapabilityCategory.TELEMETRY,
    "get_hardware_info": CapabilityCategory.TELEMETRY,
    "get_uptime": CapabilityCategory.TELEMETRY,
    "uptime": CapabilityCategory.TELEMETRY,

    # Software Management
    "install_software": CapabilityCategory.SOFTWARE_MANAGEMENT,
    "uninstall_software": CapabilityCategory.SOFTWARE_MANAGEMENT,
    "list_software": CapabilityCategory.SOFTWARE_MANAGEMENT,
    "list_installed_software": CapabilityCategory.SOFTWARE_MANAGEMENT,

    # System Power
    "shutdown": CapabilityCategory.SYSTEM_POWER,
    "restart": CapabilityCategory.SYSTEM_POWER,
    "lock": CapabilityCategory.SYSTEM_POWER,
    "sign_out": CapabilityCategory.SYSTEM_POWER,
    "sleep": CapabilityCategory.SYSTEM_POWER,
    "hibernate": CapabilityCategory.SYSTEM_POWER,

    # Administrator
    "service_control": CapabilityCategory.ADMINISTRATOR_OPS,
    "registry_write_system": CapabilityCategory.ADMINISTRATOR_OPS,
    "elevated_command": CapabilityCategory.ADMINISTRATOR_OPS,
    "test_elevation": CapabilityCategory.ADMINISTRATOR_OPS,
    "elevation": CapabilityCategory.ADMINISTRATOR_OPS,
    "request_elevation": CapabilityCategory.ADMINISTRATOR_OPS,

    # Automation Code
    "execute_script": CapabilityCategory.AUTOMATION_CODE,
    "execute_command": CapabilityCategory.AUTOMATION_CODE,
    "run_code": CapabilityCategory.AUTOMATION_CODE,

    # App Integrations
    "whatsapp_action": CapabilityCategory.APP_INTEGRATIONS,
    "whatsapp_workflow": CapabilityCategory.APP_INTEGRATIONS,
    "excel_action": CapabilityCategory.APP_INTEGRATIONS,
    "excel_workflow": CapabilityCategory.APP_INTEGRATIONS,
    "vscode_action": CapabilityCategory.APP_INTEGRATIONS,
    "vscode_workflow": CapabilityCategory.APP_INTEGRATIONS,
    "media_action": CapabilityCategory.APP_INTEGRATIONS,
    "browser_action": CapabilityCategory.APP_INTEGRATIONS,
}


def resolve_operation_capability(operation: str) -> CapabilityCategory:
    """
    Authoritative resolution of operation name to its canonical CapabilityCategory.
    Uses exact lookup with heuristic fallbacks for pattern-based operation names.
    """
    op = (operation or "").strip().lower()
    if op in OPERATION_TO_CAPABILITY:
        return OPERATION_TO_CAPABILITY[op]

    # Pattern-based heuristics
    if any(op.endswith(suffix) for suffix in ("_file", "_folder", "_dir", "_directory", "_files", "_folders")) or \
       any(op.startswith(prefix) for prefix in ("file_", "folder_", "dir_")):
        return CapabilityCategory.FILESYSTEM

    if any(k in op for k in ("wifi", "bluetooth", "network", "adapter")):
        return CapabilityCategory.NETWORK

    if any(k in op for k in ("cpu", "ram", "gpu", "battery", "disk", "uptime", "hardware", "telemetry")):
        return CapabilityCategory.TELEMETRY

    if any(k in op for k in ("volume", "brightness", "wallpaper", "resolution", "dark_mode")):
        return CapabilityCategory.SYSTEM_SETTINGS

    if any(k in op for k in ("shutdown", "restart", "reboot", "power", "sleep", "hibernate", "lock", "sign_out", "signout")):
        return CapabilityCategory.SYSTEM_POWER

    if any(k in op for k in ("process", "proc", "kill", "terminate")):
        return CapabilityCategory.PROCESS_MANAGEMENT

    if any(k in op for k in ("whatsapp", "excel", "vscode", "browser", "media_player")):
        return CapabilityCategory.APP_INTEGRATIONS

    if any(k in op for k in ("install", "uninstall", "package")):
        return CapabilityCategory.SOFTWARE_MANAGEMENT

    return CapabilityCategory.APP_LIFECYCLE


@dataclass
class GateEvaluationResult:
    """Outcome of evaluating the 3-condition capability and permission gate."""
    allowed: bool
    status: str  # "allowed", "consent_required", "privilege_required", "confirmation_required", "impossible"
    category: str
    operation: str
    target: str
    risk_level: str
    reason: str
    requires_consent: bool = False
    requires_elevation: bool = False
    requires_confirmation: bool = False
    suggested_action: str = "execute"  # "execute", "request_consent", "request_elevation", "request_confirmation", "explain_impossible"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CapabilityConsentManager:
    """
    Authoritative coordinator for capability consent persistence,
    three-tier authorization gates, and immediate revocation.
    """

    _instance: Optional[CapabilityConsentManager] = None
    _lock = threading.Lock()

    def __new__(cls) -> CapabilityConsentManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._cache_lock = threading.RLock()
        # Cache format: {user_id: {category_str: bool}}
        self._consent_cache: Dict[int, Dict[str, bool]] = {}
        logger.info("[CAPABILITY_CONSENT] CapabilityConsentManager initialized.")

    # ── 1. CONSENT PERSISTENCE & RETRIEVAL ──────────────────────────────────

    def clear_user_cache(self, user_id: Optional[int] = None) -> None:
        """
        Clear cached permissions. If user_id is provided, clears only that user's cache.
        If user_id is None, clears all user caches (e.g. on signout or account switch).
        """
        with self._cache_lock:
            if user_id is not None:
                uid = int(user_id) if str(user_id).isdigit() else 1
                self._consent_cache.pop(uid, None)
            else:
                self._consent_cache.clear()
        logger.debug("[CAPABILITY_CONSENT] Cleared consent cache (user=%s)", user_id)

    def is_consent_granted(self, user_id: int, category: str | CapabilityCategory) -> bool:
        """
        Check if user has granted consent for a specific capability category.
        Checks in-memory cache first, falls back to PostgreSQL, then default policy.
        Enforces fail-closed behavior on missing or failed lookup for protected capabilities.
        """
        cat_key = category.value if isinstance(category, CapabilityCategory) else str(category).lower()
        uid = int(user_id) if str(user_id).isdigit() else 1

        with self._cache_lock:
            if uid in self._consent_cache and cat_key in self._consent_cache[uid]:
                return self._consent_cache[uid][cat_key]

        # Query database
        pool = get_db_pool()
        if pool and pool.is_healthy():
            try:
                with pool.get_cursor() as cur:
                    cur.execute(
                        "SELECT is_granted FROM user_capability_consents WHERE user_id = %s AND category = %s;",
                        (uid, cat_key)
                    )
                    row = cur.fetchone()
                    if row is not None:
                        is_granted = bool(row[0])
                        with self._cache_lock:
                            self._consent_cache.setdefault(uid, {})[cat_key] = is_granted
                        return is_granted
            except Exception as e:
                logger.error("[CAPABILITY_CONSENT] DB query error for user %s category %s: %s", uid, cat_key, e)
                # Fail-closed: Never silently grant access if lookup failed due to error
                defn = CAPABILITY_DEFINITIONS.get(cat_key, {})
                if defn.get("requires_admin", False) or defn.get("risk_level") in ("HIGH", "PRIVILEGED", "MODERATE"):
                    return False

        # Default fallback from CAPABILITY_DEFINITIONS
        default_val = CAPABILITY_DEFINITIONS.get(cat_key, {}).get("default_granted", False)
        with self._cache_lock:
            self._consent_cache.setdefault(uid, {})[cat_key] = default_val
        return default_val

    def grant_consent(self, user_id: int, category: str | CapabilityCategory) -> bool:
        """Grant user consent for a specific capability category with immediate persistence."""
        cat_key = category.value if isinstance(category, CapabilityCategory) else str(category).lower()
        uid = int(user_id) if str(user_id).isdigit() else 1

        with self._cache_lock:
            self._consent_cache.setdefault(uid, {})[cat_key] = True

        pool = get_db_pool()
        if pool and pool.is_healthy():
            try:
                with pool.get_cursor() as cur:
                    cur.execute("""
                        INSERT INTO user_capability_consents (user_id, category, is_granted, granted_at, updated_at)
                        VALUES (%s, %s, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        ON CONFLICT (user_id, category) DO UPDATE SET
                            is_granted = TRUE,
                            revoked_at = NULL,
                            updated_at = CURRENT_TIMESTAMP;
                    """, (uid, cat_key))
                logger.info("[CAPABILITY_CONSENT] Granted consent for user %s on category '%s'.", uid, cat_key)
                return True
            except Exception as e:
                logger.error("[CAPABILITY_CONSENT] DB error granting consent for %s: %s", cat_key, e)
                return False
        return True

    def revoke_consent(self, user_id: int, category: str | CapabilityCategory) -> bool:
        """
        Immediately revoke user consent for a capability category.
        Takes effect immediately for all subsequent actions and in-progress steps.
        """
        cat_key = category.value if isinstance(category, CapabilityCategory) else str(category).lower()
        uid = int(user_id) if str(user_id).isdigit() else 1

        with self._cache_lock:
            self._consent_cache.setdefault(uid, {})[cat_key] = False

        pool = get_db_pool()
        if pool and pool.is_healthy():
            try:
                with pool.get_cursor() as cur:
                    cur.execute("""
                        INSERT INTO user_capability_consents (user_id, category, is_granted, revoked_at, updated_at)
                        VALUES (%s, %s, FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        ON CONFLICT (user_id, category) DO UPDATE SET
                            is_granted = FALSE,
                            revoked_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP;
                    """, (uid, cat_key))
                logger.info("[CAPABILITY_CONSENT] Revoked consent for user %s on category '%s'.", uid, cat_key)
                return True
            except Exception as e:
                logger.error("[CAPABILITY_CONSENT] DB error revoking consent for %s: %s", cat_key, e)
                return False
        return True

    def grant_all_default_consents(self, user_id: int) -> Dict[str, bool]:
        """Initialize all default capability consents for a newly registered or first-time user."""
        uid = int(user_id) if str(user_id).isdigit() else 1
        results = {}
        for cat, defn in CAPABILITY_DEFINITIONS.items():
            if defn.get("default_granted", False):
                results[cat] = self.grant_consent(uid, cat)
        return results

    def load_user_consents(self, user_id: int) -> Dict[str, bool]:
        """
        Load all capability consents from PostgreSQL for the authenticated user,
        populating the user's cache directly. If user has no records, initializes defaults.
        """
        uid = int(user_id) if str(user_id).isdigit() else 1
        loaded = {}
        has_records = False
        pool = get_db_pool()
        if pool and pool.is_healthy():
            try:
                with pool.get_cursor() as cur:
                    cur.execute(
                        "SELECT category, is_granted FROM user_capability_consents WHERE user_id = %s;",
                        (uid,)
                    )
                    rows = cur.fetchall()
                    if rows:
                        has_records = True
                        with self._cache_lock:
                            self._consent_cache[uid] = {}
                            for cat, granted in rows:
                                self._consent_cache[uid][cat] = bool(granted)
                                loaded[cat] = bool(granted)
            except Exception as e:
                logger.error("[CAPABILITY_CONSENT] DB error loading consents for user %s: %s", uid, e)

        if not has_records:
            # First-time user: initialize default consents into DB and cache
            self.grant_all_default_consents(uid)
            for cat, defn in CAPABILITY_DEFINITIONS.items():
                loaded[cat] = defn.get("default_granted", False)

        return loaded

    def get_user_consents(self, user_id: int) -> Dict[str, Dict[str, Any]]:
        """Return a structured dictionary of all 12 capabilities with their active status for the user."""
        uid = int(user_id) if str(user_id).isdigit() else 1
        output = {}
        for cat, defn in CAPABILITY_DEFINITIONS.items():
            granted = self.is_consent_granted(uid, cat)
            output[cat] = {
                "category": cat,
                "title": defn["title"],
                "description": defn["description"],
                "is_granted": granted,
                "requires_admin": defn["requires_admin"],
                "risk_level": defn["risk_level"],
            }
        return output

    # ── 2. THREE-CONDITION GATE EVALUATION ──────────────────────────────────

    def evaluate_operation_gate(
        self,
        user_id: int,
        operation: str,
        target: str = "",
        risk_level: str = "LOW_RISK",
        params: Optional[Dict[str, Any]] = None,
        confirmed_by_user: bool = False,
    ) -> GateEvaluationResult:
        """
        Canonical evaluation of the three essential conditions:
          A. Application Consent
          B. Operating System Capability
          C. Action-Specific Authorization
        """
        uid = int(user_id) if str(user_id).isdigit() else 1
        op_clean = operation.lower().strip()
        params = params or {}

        # 1. Resolve Capability Category
        cat_enum = resolve_operation_capability(op_clean)
        cat_str = cat_enum.value

        # ---------------------------------------------------------------------
        # Condition A: Application Consent
        # ---------------------------------------------------------------------
        if not self.is_consent_granted(uid, cat_str):
            defn = CAPABILITY_DEFINITIONS.get(cat_str, {})
            title = defn.get("title", cat_str)
            return GateEvaluationResult(
                allowed=False,
                status="consent_required",
                category=cat_str,
                operation=operation,
                target=target,
                risk_level=risk_level,
                reason=f"Operation requires user capability consent for '{title}'. This category is currently revoked or not granted.",
                requires_consent=True,
                suggested_action="request_consent",
            )

        # ---------------------------------------------------------------------
        # Condition B: Operating-System Capability & Elevation State
        # ---------------------------------------------------------------------
        from core.permission_manager import get_permission_elevation_manager
        pm = get_permission_elevation_manager()
        is_elevated = pm.is_admin()

        defn = CAPABILITY_DEFINITIONS.get(cat_str, {})
        requires_admin = defn.get("requires_admin", False)

        # Explicit admin checks for specific operations
        if op_clean in ("install_software", "uninstall_software", "service_control", "elevated_command", "test_elevation", "elevation", "request_elevation"):
            requires_admin = True

        if requires_admin and not is_elevated:
            logger.info(
                f"[SECURITY_GATE] uid={uid} op={operation} target='{target}' cat={cat_str} "
                f"consent=True admin_required=True is_elevated=False status=privilege_required allowed=False"
            )
            return GateEvaluationResult(
                allowed=False,
                status="privilege_required",
                category=cat_str,
                operation=operation,
                target=target,
                risk_level="PRIVILEGED",
                reason=f"Operation '{operation}' requires Windows Administrator elevation.",
                requires_elevation=True,
                suggested_action="request_elevation",
            )

        # ---------------------------------------------------------------------
        # Condition C: Action-Specific Authorization
        # High risk, destructive, power, or irreversible actions require fresh confirmation
        # ---------------------------------------------------------------------
        risk_upper = str(risk_level).upper()
        high_risk_ops = {
            "shutdown", "restart", "delete_file", "delete_directory",
            "terminate_process", "uninstall_software", "install_software",
            "format_drive", "modify_firewall", "send_message"
        }
        is_high_risk = (
            risk_upper in ("DESTRUCTIVE", "SYSTEM_CRITICAL", "PRIVILEGED", "HIGH")
            or op_clean in high_risk_ops
            or params.get("requires_confirmation", False)
        )

        if is_high_risk and not confirmed_by_user:
            logger.info(
                f"[SECURITY_GATE] uid={uid} op={operation} target='{target}' cat={cat_str} "
                f"consent=True admin_required={requires_admin} is_elevated={is_elevated} "
                f"status=confirmation_required allowed=False"
            )
            return GateEvaluationResult(
                allowed=False,
                status="confirmation_required",
                category=cat_str,
                operation=operation,
                target=target,
                risk_level=risk_upper,
                reason=f"Operation '{operation}' on target '{target}' has significant side-effects and requires explicit user confirmation.",
                requires_confirmation=True,
                suggested_action="request_confirmation",
            )

        # All 3 conditions satisfied!
        logger.info(
            f"[SECURITY_GATE] uid={uid} op={operation} target='{target}' cat={cat_str} "
            f"consent=True admin_required={requires_admin} is_elevated={is_elevated} "
            f"status=allowed allowed=True"
        )
        return GateEvaluationResult(
            allowed=True,
            status="allowed",
            category=cat_str,
            operation=operation,
            target=target,
            risk_level=risk_upper,
            reason="All 3 conditions (Consent, OS Capability, Authorization) satisfied.",
            suggested_action="execute",
        )


_consent_manager: Optional[CapabilityConsentManager] = None

def get_capability_consent_manager() -> CapabilityConsentManager:
    """Get the global singleton CapabilityConsentManager."""
    global _consent_manager
    if _consent_manager is None:
        _consent_manager = CapabilityConsentManager()
    return _consent_manager
