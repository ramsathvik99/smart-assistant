"""
Device Management Skill Package
Enables secure mobile device pairing, LAN UDP discovery, remote RPC commands, and user-isolated device control.
"""

import sys
from pathlib import Path
_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from .config import DeviceGatewayConfig
from .device_auth import generate_pairing_code, generate_pairing_token
from .device_controller import DeviceController, get_device_controller
from .device_discovery import DeviceDiscoveryBeacon, get_discovery_beacon
from .device_dispatcher import RemoteDeviceDispatcher, get_device_dispatcher
from .device_models import DeviceRecord, PairingOffer, ProtocolTypes
from .device_pairing import DevicePairingManager, get_pairing_manager
from .device_registry import DeviceRegistry, get_device_registry

from .session_manager import (
    DeviceSessionManager,
    get_device_session_manager,
    DeviceTransportType,
    DeviceControllabilityState,
)
from .remote_connection_manager import (
    RemoteConnectionManager,
    get_remote_connection_manager,
    DeviceConnectionLifecycle,
    validate_imei,
)

from .file_transfer import save_user_uploaded_file, get_user_file_path, list_user_files
from .phone_audio import PhoneAudioStreamReceiver, get_phone_audio_receiver

from .platform_adapter import GadsPlatformAdapter, get_platform_adapter, PlatformSession
from .adb_adapter import AdbAdapter, get_adb_adapter

__all__ = [
    "DeviceGatewayConfig",
    "DeviceRecord",
    "PairingOffer",
    "ProtocolTypes",
    "DeviceRegistry",
    "get_device_registry",
    "DevicePairingManager",
    "get_pairing_manager",
    "DeviceDiscoveryBeacon",
    "get_discovery_beacon",
    "RemoteDeviceDispatcher",
    "get_device_dispatcher",
    "DeviceController",
    "get_device_controller",
    "GadsPlatformAdapter",
    "get_platform_adapter",
    "PlatformSession",
    "AdbAdapter",
    "get_adb_adapter",
    "save_user_uploaded_file",
    "get_user_file_path",
    "list_user_files",
    "PhoneAudioStreamReceiver",
    "DeviceSessionManager",
    "get_device_session_manager",
    "DeviceTransportType",
    "DeviceControllabilityState",
    "get_phone_audio_receiver",
    "RemoteConnectionManager",
    "get_remote_connection_manager",
    "DeviceConnectionLifecycle",
    "validate_imei",
]
