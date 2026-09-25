"""
Device Management Skill Package
Enables secure mobile device pairing, LAN UDP discovery, remote RPC commands, and user-isolated device control.
"""

from .config import DeviceGatewayConfig
from .device_auth import generate_pairing_code, generate_pairing_token
from .device_controller import DeviceController, get_device_controller
from .device_discovery import DeviceDiscoveryBeacon, get_discovery_beacon
from .device_dispatcher import RemoteDeviceDispatcher, get_device_dispatcher
from .device_models import DeviceRecord, PairingOffer, ProtocolTypes
from .device_pairing import DevicePairingManager, get_pairing_manager
from .device_registry import DeviceRegistry, get_device_registry

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
]
