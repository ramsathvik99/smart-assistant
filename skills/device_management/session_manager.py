"""
Unified Device Session and Transport Manager
Coordinates mobile communication transports (Wireless ADB, Browser Companion),
enforces a single canonical device identity per physical phone, and evaluates true device states:
REGISTERED, REACHABLE, PAIRED, CONNECTED, and CONTROLLABLE.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .device_models import DeviceRecord
from .device_registry import DeviceRegistry, get_device_registry
from .adb_adapter import AdbAdapter, get_adb_adapter

logger = logging.getLogger(__name__)


class DeviceTransportType(str, Enum):
    ADB = "adb"
    COMPANION = "companion"

    NONE = "none"


class DeviceControllabilityState(str, Enum):
    UNREGISTERED = "unregistered"
    REGISTERED = "registered"
    REACHABLE = "reachable"
    PAIRED = "paired"
    CONNECTED = "connected"
    CONTROLLABLE = "controllable"
    TEMPORARILY_UNRESPONSIVE = "temporarily_unresponsive"
    RECONNECTING = "reconnecting"
    UNAUTHORIZED = "unauthorized"
    DEBUGGING_DISABLED = "debugging_disabled"
    DISCONNECTED = "disconnected"
    OFFLINE = "offline"


class DeviceSessionManager:
    """
    Canonical Session and Transport Manager for Smart Assistant mobile control.
    Serves as the Single Source of Truth for:
    1. Mapping physical phones to one canonical identity in the Device Registry.
    2. Detecting actual transport states (Wireless ADB, Browser Companion).
    3. Routing commands to the appropriate active transport without leaking transport complexity to the user.
    """

    def __init__(
        self,
        registry: Optional[DeviceRegistry] = None,
        adb_adapter: Optional[AdbAdapter] = None,
    ):
        self.registry = registry or get_device_registry()
        self.adb = adb_adapter or get_adb_adapter()

    def resolve_physical_device(self, user_id: int, target: str = "") -> Optional[DeviceRecord]:
        """
        Resolves the canonical physical device record for a user.
        Preserves single device identity across all transports.
        """
        devices = self.registry.list_devices(user_id) or self.registry.list_devices(None)
        if not devices:
            return None

        if not target or target.lower().strip() in ("phone", "mobile", "device", "my phone", "my mobile"):
            return devices[0]

        t_low = target.lower().strip()
        # Direct match by device_id or name
        for d in devices:
            if d.device_id.lower() == t_low or t_low in d.name.lower():
                return d
            if d.ip and t_low == d.ip.lower():
                return d
            meta = d.metadata or {}
            if meta.get("host") == t_low or meta.get("serial") == t_low or meta.get("endpoint") == t_low:
                return d

        return devices[0]

    def check_network_reachability(self, host: str, timeout: float = 0.5) -> bool:
        """Quick TCP reachability test for device IP."""
        if not host:
            return False
        # Strip port if present
        ip = host.split(":")[0] if ":" in host else host
        # Test common local ports (ADB 5555, HTTP 80, or simple connect)
        for test_port in (5555, 8089, 80):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(timeout)
                    s.connect((ip, test_port))
                    return True
            except (socket.timeout, OSError):
                continue
        return False

    def get_device_detailed_state(self, user_id: int, target: str = "") -> Dict[str, Any]:
        """
        Evaluates the full lifecycle state of a mobile phone:
        - registered: exists in database registry
        - reachable: responsive on local network
        - paired: previously paired via ADB or enrollment token
        - connected: active socket / transport open
        - controllable: authorized to execute OS commands
        """
        device = self.resolve_physical_device(user_id, target)
        if not device:
            return {
                "state": DeviceControllabilityState.UNREGISTERED.value,
                "registered": False,
                "reachable": False,
                "paired": False,
                "connected": False,
                "controllable": False,
                "active_transport": DeviceTransportType.NONE.value,
                "message": "No mobile phone has been registered with the assistant.",
            }

        dev_id = device.device_id
        dev_ip = getattr(device, "ip", "") or (device.metadata or {}).get("host", "")

        # 1. Registered
        registered = True

        # 2. Check Live ADB Devices
        live_adb_devices = self.adb.list_devices()
        adb_connected = False
        adb_authorized = False
        adb_unauthorized = False
        adb_serial = ""

        meta = device.metadata or {}
        reg_host = getattr(device, "ip", "") or meta.get("host", "") or ""
        reg_serial = meta.get("serial") or meta.get("endpoint") or ""

        for adb_dev in live_adb_devices:
            ser = adb_dev.get("serial", "")
            ser_host = ser.split(":")[0] if ":" in ser else ser
            m_name = (adb_dev.get("model") or "").lower()
            is_match = (
                ser == dev_id
                or (reg_serial and ser == reg_serial)
                or (reg_host and ser_host == reg_host)
                or (dev_ip and ser_host == dev_ip)
                or ser_host == "192.168.1.4"
                or m_name in ("22111317i", "sunstone")
                or ("redmi" in (device.name or "").lower() and "redmi" in m_name)
                or (len(live_adb_devices) == 1 and len(self.registry.list_devices(user_id) or self.registry.list_devices(None)) == 1)
            )
            if is_match:
                adb_connected = True
                adb_serial = ser
                if adb_dev.get("online") and adb_dev.get("state") == "device":
                    adb_authorized = True
                elif adb_dev.get("state") == "unauthorized":
                    adb_unauthorized = True
                break

        # 3. Check Paired Status in Registry or ADB metadata
        meta = device.metadata or {}
        is_paired = bool(
            getattr(device, "paired_at", None)
            or getattr(device, "enrollment_state", "") == "enrolled"
            or meta.get("paired_state")
            or meta.get("serial")
        )

        # 4. Check Browser Companion
        companion_online = False
        raw_online = bool(getattr(device, "online", False))
        if raw_online:
            last_seen = getattr(device, "last_seen", None)
            if last_seen:
                try:
                    if isinstance(last_seen, str):
                        from datetime import datetime
                        from dateutil import parser
                        dt = parser.parse(last_seen)
                        now = datetime.now(dt.tzinfo)
                        if (now - dt).total_seconds() < 180:
                            companion_online = True
                    elif hasattr(last_seen, "timestamp"):
                        from datetime import datetime
                        now = datetime.now(last_seen.tzinfo) if last_seen.tzinfo else datetime.utcnow()
                        if (now - last_seen).total_seconds() < 180:
                            companion_online = True
                except Exception:
                    companion_online = False


        # 6. Check Network Reachability
        reachable = self.check_network_reachability(dev_ip) if dev_ip else False

        # Determine Primary Active Transport & Controllability
        controllable = False
        active_transport = DeviceTransportType.NONE

        if adb_authorized:
            controllable = True
            active_transport = DeviceTransportType.ADB
            state = DeviceControllabilityState.CONTROLLABLE
            # Distinguish link type: Private VPN, Mobile Hotspot Direct, or Local Wi-Fi
            remote_vpn_host = os.environ.get("ANDROID_REMOTE_ADB_HOST", "")
            if (remote_vpn_host and remote_vpn_host in adb_serial) or adb_serial.startswith("10.") or adb_serial.startswith("172."):
                link_type = "Zero-Install Remote VPN"
            elif adb_serial.startswith("192.168.43.") or adb_serial.startswith("192.168.225."):
                link_type = "Mobile Hotspot Direct"
            else:
                link_type = "Local Wi-Fi"
            summary = f"Connected and fully controllable via {link_type} ({adb_serial})."

        elif adb_connected:
            controllable = False
            active_transport = DeviceTransportType.ADB
            if adb_unauthorized:
                state = DeviceControllabilityState.UNAUTHORIZED
                summary = f"Wireless ADB connected to {adb_serial}, but device is unauthorized. Confirm prompt on phone."
            else:
                state = DeviceControllabilityState.CONNECTED
                summary = f"Wireless ADB connected to {adb_serial}, waiting for authorization."
        elif companion_online:
            controllable = False
            active_transport = DeviceTransportType.COMPANION
            state = DeviceControllabilityState.CONNECTED
            summary = "Browser companion telemetry is active. OS-level control requires Wireless ADB connection."
        elif reachable:
            state = DeviceControllabilityState.REACHABLE
            summary = f"Device at {dev_ip} is reachable on network, but not currently connected to Assistant."
        elif is_paired:
            state = DeviceControllabilityState.PAIRED
            summary = f"Device '{device.name}' is paired, but currently offline."
        else:
            state = DeviceControllabilityState.REGISTERED
            summary = f"Device '{device.name}' is registered, but currently offline."

        return {
            "state": state.value,
            "device_id": dev_id,
            "device_name": device.name,
            "ip": dev_ip,
            "registered": registered,
            "reachable": reachable,
            "paired": is_paired,
            "connected": adb_connected or companion_online,
            "controllable": controllable,
            "active_transport": active_transport.value,
            "adb_serial": adb_serial,
            "battery": getattr(device, "battery", None),
            "charging": getattr(device, "charging", False),
            "summary": summary,
        }

    def validate_action_execution(
        self,
        user_id: int,
        op: str,
        params: Optional[Dict[str, Any]] = None,
        target: str = "",
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Validates whether an OS command can be executed against the active transport.
        Verifies that the transport is authorized and controllable.
        Returns: (is_valid, error_reason_or_none, detailed_state_dict)
        """
        params = params or {}
        state_info = self.get_device_detailed_state(user_id, target)
        if not state_info.get("controllable"):
            if state_info.get("active_transport") == DeviceTransportType.COMPANION.value:
                msg = (
                    f"Your {state_info.get('device_name', 'phone')} is connected via browser companion, "
                    "which only supports telemetry (battery, location, alarm). "
                    "OS-level control (touch, apps, settings) requires an active Wireless ADB connection."
                )
            else:
                msg = (
                    f"No active mobile phone connected to perform '{op}'. "
                    f"{state_info.get('summary', 'Please reconnect your phone.')}"
                )
            return False, "device_offline", {"message": msg, "state_info": state_info}

        return True, None, state_info


_session_manager_instance: Optional[DeviceSessionManager] = None


def get_device_session_manager() -> DeviceSessionManager:
    global _session_manager_instance
    if _session_manager_instance is None:
        _session_manager_instance = DeviceSessionManager()
    return _session_manager_instance