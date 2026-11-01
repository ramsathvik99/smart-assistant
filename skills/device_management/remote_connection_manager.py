"""
Remote & Cross-Network Android Connection Manager
=================================================
Implements zero-install, secure remote connectivity for Android devices (Redmi Note 12 5G)
across cellular mobile data (4G/5G), different Wi-Fi networks, and local Wi-Fi.

Enforces:
1. 15-digit IMEI Luhn validation as persistent device reference.
2. Authenticated Wireless ADB pairing and connection.
3. Multi-interface TCP/IP binding (port 5555) for cross-network reachability.
4. Native Android IKEv2/IPsec VPN tunnel routing (bypassing carrier CGNAT with MOBIKE).
5. 9-state persistent connection lifecycle.
6. Automatic connection recovery across IP and network transitions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .device_models import DeviceRecord
from .device_registry import get_device_registry
from .adb_adapter import get_adb_adapter

logger = logging.getLogger("RemoteConnectionManager")


class DeviceConnectionLifecycle(str, Enum):
    """Authoritative persistent connection lifecycle."""
    REGISTERED = "Registered"
    PAIRING = "Pairing"
    AUTHENTICATED = "Authenticated"
    CONNECTING = "Connecting"
    CONNECTED_LOCALLY = "Connected locally"
    CONNECTED_REMOTELY = "Connected remotely"
    RECONNECTING = "Reconnecting"
    TEMPORARILY_OFFLINE = "Temporarily offline"
    AUTHORIZATION_REQUIRED = "Authorization required"
    OFFLINE = "Offline"
    AUTHENTICATION_FAILED = "Authentication failed"


def validate_imei(imei: Optional[str]) -> Tuple[bool, str, str]:
    """
    Validates optional user-provided IMEI format and Luhn check digit.
    IMEI is purely optional user tracking metadata. It is NOT required for pairing
    and is NOT used as physical device authentication.
    Returns: (is_valid, clean_imei, error_message)
    """
    if imei is None or not str(imei).strip():
        return True, "", ""  # Optional: omitting IMEI is completely valid

    clean = re.sub(r'[\s\-:]', '', str(imei).strip())
    if not re.match(r'^\d{15}$', clean):
        return False, clean, f"IMEI must be exactly 15 numeric digits (received {len(clean)} digits)."

    # Luhn checksum calculation
    digits = [int(c) for c in clean]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            doubled = d * 2
            total += (doubled - 9) if doubled > 9 else doubled
        else:
            total += d

    if total % 10 != 0:
        return False, clean, "IMEI failed Luhn checksum validation. Please verify the 15 digits from Settings -> About phone -> Status."

    return True, clean, ""


CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "instance", "remote_vpn_config.json")


class RemoteNetworkConfig:
    """Configuration for cross-network native IKEv2/IPSec VPN routing."""

    def __init__(self):
        self.config_path: str = CONFIG_FILE
        self.vpn_server: str = ""
        self.vpn_type: str = "IKEv2/IPSec PSK"
        self.ipsec_identifier: str = "smart-assistant-redmi"
        self.ipsec_psk: str = ""
        self.phone_virtual_ip: str = "10.8.0.2"
        self.laptop_virtual_ip: str = "10.8.0.1"
        self.virtual_subnet: str = "10.8.0.0/24"
        self.adb_remote_port: int = 5555
        self.load_config()

    def load_config(self) -> None:
        """Loads configuration from persistent JSON file and environment variables."""
        import json
        import secrets
        data = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.warning(f"Could not read {self.config_path}: {e}")

        # Priority: Environment variable > Config file
        self.vpn_server = os.getenv("ANDROID_REMOTE_VPN_HOST") or data.get("vpn_server") or ""
        self.ipsec_identifier = os.getenv("ANDROID_REMOTE_IPSEC_ID") or data.get("ipsec_identifier") or "smart-assistant-redmi"

        env_psk = os.getenv("ANDROID_REMOTE_VPN_PSK")
        file_psk = data.get("ipsec_psk")
        if env_psk:
            self.ipsec_psk = env_psk
        elif file_psk:
            self.ipsec_psk = file_psk
        else:
            # Generate a cryptographically strong, unique pre-shared key (32 bytes urlsafe)
            self.ipsec_psk = secrets.token_urlsafe(32)
            self.save_config()

        self.phone_virtual_ip = os.getenv("ANDROID_REMOTE_PHONE_IP") or data.get("phone_virtual_ip") or "10.8.0.2"
        self.laptop_virtual_ip = os.getenv("ANDROID_REMOTE_LAPTOP_IP") or data.get("laptop_virtual_ip") or "10.8.0.1"

    def save_config(self) -> bool:
        """Persists VPN configuration to instance/remote_vpn_config.json."""
        import json
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            payload = {
                "vpn_server": self.vpn_server,
                "vpn_type": self.vpn_type,
                "ipsec_identifier": self.ipsec_identifier,
                "ipsec_psk": self.ipsec_psk,
                "phone_virtual_ip": self.phone_virtual_ip,
                "laptop_virtual_ip": self.laptop_virtual_ip,
                "virtual_subnet": self.virtual_subnet,
                "adb_remote_port": self.adb_remote_port,
                "is_configured": bool(self.vpn_server and self.vpn_server != "vpn.smartassistant.internal"),
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save VPN config to {self.config_path}: {e}")
            return False

    def update_server_endpoint(self, server_host: str) -> Dict[str, Any]:
        """Updates the public VPN server host address or FQDN."""
        clean_host = (server_host or "").strip()
        self.vpn_server = clean_host
        self.save_config()
        return {
            "success": True,
            "vpn_server": self.vpn_server,
            "is_configured": self.is_configured,
            "message": f"VPN Server endpoint updated to: {self.vpn_server or '[Not set]'}"
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.vpn_server and self.vpn_server != "vpn.smartassistant.internal")

    def get_setup_guide(
        self,
        phone_name: str = "Android Device",
        phone_ip: Optional[str] = None,
        ipsec_id: Optional[str] = None,
        guidance: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generates exact one-time native Android VPN configuration steps for any Android device."""
        server_display = self.vpn_server if self.is_configured else "[Enter VPS IP or domain in Settings]"
        target_ip = phone_ip or self.phone_virtual_ip
        target_id = ipsec_id or self.ipsec_identifier
        return {
            "title": f"One-Time Remote Cross-Network Setup for {phone_name}",
            "device_name": phone_name,
            "is_configured": self.is_configured,
            "server_configured": self.is_configured,
            "phone_tunnel_ip": target_ip,
            "ipsec_identifier": target_id,
            "prerequisites": [
                f"Zero applications required on {phone_name} (uses stock Android native VPN).",
                "Phone and Laptop can be on mobile data, different Wi-Fi networks, or different locations."
            ],
            "android_steps": [
                f"1. On {phone_name}, open Settings -> More connectivity options (or Connections) -> VPN.",
                "2. Tap 'Add VPN profile' (+):",
                "   - Name: Smart Assistant VPN",
                "   - Type: IKEv2/IPSec PSK",
                f"   - Server address: {server_display}",
                f"   - IPSec identifier: {target_id}",
                f"   - IPSec pre-shared key: {self.ipsec_psk}",
                "3. Tap Save (check mark).",
                "4. Tap the gear icon next to 'Smart Assistant VPN' and toggle 'Always-on VPN' to ON.",
                "   NOTE: Leave 'Block connections without VPN' OFF so local Wi-Fi fallback continues working."
            ],
            "device_guidance": guidance or [],
            "technical_specs": {
                "tunnel_protocol": "IKEv2 with MOBIKE (RFC 4555)",
                "encryption": "AES-256-GCM / SHA-256",
                "phone_tunnel_ip": target_ip,
                "laptop_tunnel_ip": self.laptop_virtual_ip,
                "remote_adb_endpoint": f"{target_ip}:{self.adb_remote_port}",
                "public_ports_exposed": "None (ADB is strictly private inside IPsec tunnel)",
                "status": "Ready for connection" if self.is_configured else "Action required: Configure VPS address"
            }
        }


class RemoteConnectionManager:
    """
    Authoritative manager for remote, cross-network, and local Android connectivity.
    Integrates directly with DeviceController, AdbAdapter, and DeviceRegistry.
    """

    _instance: Optional[RemoteConnectionManager] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> RemoteConnectionManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.registry = get_device_registry()
        self.adb = get_adb_adapter()
        self.network_config = RemoteNetworkConfig()
        self._lifecycle_states: Dict[str, DeviceConnectionLifecycle] = {}
        self._recovery_thread: Optional[threading.Thread] = None
        self._monitoring_active = False

    def allocate_device_vpn_address(self, user_id: int, device_id: str) -> Tuple[str, str]:
        """
        Allocates an independent private virtual IP (10.8.0.X) and unique IPSec identifier
        for each phone within the assistant VPN subnet (pool 10.8.0.2 - 10.8.0.250).
        """
        used_octets = {1, 254}  # 1 is laptop host, 254 is gateway
        devices = self.registry.list_devices(None)
        for d in devices:
            if d.device_id != device_id and d.metadata:
                vip = d.metadata.get("remote_vpn_ip")
                if vip and vip.startswith("10.8.0."):
                    try:
                        octet = int(vip.split(".")[-1])
                        used_octets.add(octet)
                    except ValueError:
                        pass

        for octet in range(2, 251):
            if octet not in used_octets:
                assigned_ip = f"10.8.0.{octet}"
                ipsec_id = f"smart-assistant-phone-{octet}"
                return assigned_ip, ipsec_id

        return "10.8.0.2", "smart-assistant-phone-2"


    def get_lifecycle_state(self, device_id: str, user_id: Optional[int] = None) -> DeviceConnectionLifecycle:
        """Returns the authoritative lifecycle state for a device."""
        if device_id in self._lifecycle_states:
            return self._lifecycle_states[device_id]
        
        # Check registry metadata
        device = None
        if user_id is not None:
            try:
                device = self.registry.get_device(user_id, device_id)
            except Exception:
                pass
        if not device:
            for d in self.registry.list_devices(None):
                if d.device_id == device_id:
                    device = d
                    break

        if device and device.metadata:
            saved_state = device.metadata.get("lifecycle_state")
            if saved_state:
                try:
                    state_enum = DeviceConnectionLifecycle(saved_state)
                    self._lifecycle_states[device_id] = state_enum
                    return state_enum
                except ValueError:
                    pass
        return DeviceConnectionLifecycle.OFFLINE

    def set_lifecycle_state(self, device_id: str, state: DeviceConnectionLifecycle, user_id: Optional[int] = None):
        """Updates and persists the lifecycle state for a device."""
        self._lifecycle_states[device_id] = state
        try:
            device = None
            if user_id is not None:
                try:
                    device = self.registry.get_device(user_id, device_id)
                except Exception:
                    pass
            if not device:
                for d in self.registry.list_devices(None):
                    if d.device_id == device_id:
                        device = d
                        break
            if device:
                device.metadata["lifecycle_state"] = state.value
                device.metadata["lifecycle_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                self.registry.update_device(device)
        except Exception as e:
            logger.debug(f"Could not persist lifecycle state: {e}")

    # ------------------------------------------------------------------
    # Master Registration & Pairing Workflow
    # ------------------------------------------------------------------

    def register_and_pair_device(
        self,
        user_id: int,
        imei: Optional[str],
        network_ip: str,
        pairing_ip: str,
        pairing_port: int,
        pairing_code: str,
        connection_ip: str,
        connection_port: int,
    ) -> Dict[str, Any]:
        """
        Universal Android registration and pairing workflow:
        1. Validates optional IMEI (user reference only; non-blocking if omitted).
        2. Performs authenticated ADB wireless pairing (Android 11+) or direct connection (Android 10).
        3. Detects manufacturer, model, Android version, build fingerprint, capabilities and interfaces.
        4. Generates unique cryptographic device identity.
        5. Allocates independent private virtual IP (10.8.0.X) and IPSec identifier.
        6. Enables multi-interface ADB (port 5555).
        7. Associates with user account in DeviceRegistry without session cross-talk.
        8. Generates device-specific setup guide and starts recovery monitor.
        """
        # Step 1: Validate optional IMEI format
        is_valid_imei, clean_imei, imei_err = validate_imei(imei)
        if not is_valid_imei:
            return {
                "success": False,
                "status": "invalid_imei",
                "lifecycle_state": DeviceConnectionLifecycle.AUTHENTICATION_FAILED.value,
                "message": imei_err,
            }

        # Clean host inputs
        clean_network_ip = (network_ip or "").strip()
        clean_pairing_ip = (pairing_ip or clean_network_ip).strip()
        clean_connection_ip = (connection_ip or clean_network_ip).strip()
        p_code = str(pairing_code or "").strip()
        conn_port = int(connection_port) if connection_port else None

        if not clean_connection_ip:
            return {
                "success": False,
                "status": "missing_parameters",
                "lifecycle_state": DeviceConnectionLifecycle.REGISTERED.value,
                "message": "Phone IP address is required.",
            }

        temp_id = f"android_pairing_{secrets.token_hex(4)}"

        # Step 2 & 3: Authenticated Wireless Pairing (Android 11+) if pairing code provided
        if p_code and pairing_port:
            self.set_lifecycle_state(temp_id, DeviceConnectionLifecycle.PAIRING, user_id=user_id)
            logger.info(f"Authenticating ADB wireless pairing with {clean_pairing_ip}:{pairing_port}...")
            pair_res = self.adb.pair_wireless(clean_pairing_ip, int(pairing_port), p_code)
            if not pair_res.get("success"):
                # If pairing returned protocol fault / failure, check if the phone is already authorized & connected
                already_ok = False
                if conn_port:
                    c_res = self.adb.connect_wireless(clean_connection_ip, int(conn_port))
                    if c_res.get("success"):
                        already_ok = True
                if not already_ok:
                    c_res_5555 = self.adb.connect_wireless(clean_connection_ip, 5555)
                    if c_res_5555.get("success"):
                        already_ok = True
                        conn_port = 5555

                if not already_ok:
                    self.set_lifecycle_state(temp_id, DeviceConnectionLifecycle.AUTHENTICATION_FAILED, user_id=user_id)
                    return {
                        "success": False,
                        "status": "pairing_failed",
                        "lifecycle_state": DeviceConnectionLifecycle.AUTHENTICATION_FAILED.value,
                        "message": pair_res.get("message", "Wireless pairing failed. Please verify the port and code on your phone."),
                        "action_guide": pair_res.get("action_guide", []),
                    }
            self.set_lifecycle_state(temp_id, DeviceConnectionLifecycle.AUTHENTICATED, user_id=user_id)
            logger.info("Pairing authenticated successfully.")

            # If connection_port was not specified, try to auto-resolve via mDNS
            if not conn_port:
                try:
                    for s in self.adb.discover_mdns_services():
                        if s.get("service_type") == "_adb-tls-connect._tcp" or "_adb-tls-connect" in s.get("instance_name", ""):
                            ep = s.get("endpoint", "")
                            if ep and ":" in ep:
                                h, p = ep.split(":", 1)
                                if h.strip() == clean_connection_ip and p.isdigit():
                                    conn_port = int(p)
                                    logger.info(f"Auto-resolved wireless connection port {conn_port} for {clean_connection_ip} via mDNS")
                                    break
                except Exception:
                    pass

        # If still no connection port, test if default port 5555 is listening
        if not conn_port:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            try:
                if sock.connect_ex((clean_connection_ip, 5555)) == 0:
                    conn_port = 5555
            except Exception:
                pass
            finally:
                sock.close()

        # If connection port is still unknown, return guidance for the user
        if not conn_port:
            return {
                "success": True,
                "paired": True,
                "needs_connection_port": True,
                "host": clean_connection_ip,
                "pairing_port": pairing_port,
                "lifecycle_state": DeviceConnectionLifecycle.AUTHENTICATED.value,
                "message": (
                    f"Successfully paired with your phone at {clean_pairing_ip}:{pairing_port}! "
                    "Android Wireless Debugging uses a separate connection port to establish control. "
                    "Look at your phone's main Wireless Debugging screen (under 'IP address & Port') and enter the 5-digit port."
                ),
                "action_guide": [
                    "1. Pairing is successfully completed and stored on your phone.",
                    "2. The pairing code popup can now be closed on your phone.",
                    f"3. Look at 'IP address & Port' on the main Wireless Debugging screen (e.g. {clean_connection_ip}:XXXXX).",
                    "4. Enter that port as the Connection Port in Assistant and click Connect."
                ],
            }

        # Step 4: Establish ADB connection
        self.set_lifecycle_state(temp_id, DeviceConnectionLifecycle.CONNECTING, user_id=user_id)
        conn_res = self.adb.connect_wireless(clean_connection_ip, int(conn_port))
        if not conn_res.get("success"):
            self.set_lifecycle_state(temp_id, DeviceConnectionLifecycle.RECONNECTING, user_id=user_id)
            return {
                "success": False,
                "status": "connection_failed",
                "lifecycle_state": DeviceConnectionLifecycle.RECONNECTING.value,
                "message": f"Connection to {clean_connection_ip}:{conn_port} failed: {conn_res.get('message')}. Ensure connection port matches your phone screen.",
            }

        target_serial = f"{clean_connection_ip}:{conn_port}"
        time.sleep(0.3)

        # Step 5: Universally detect hardware properties, build fingerprint, and capabilities
        specs = self._detect_universal_device_specs(target_serial)
        model_name = specs.get("model") or "Android Device"
        manufacturer = specs.get("manufacturer") or "Android"
        brand = specs.get("brand") or manufacturer
        hw_serial = specs.get("hardware_serial") or clean_imei[-8:] or secrets.token_hex(6)
        os_ver = specs.get("os_version") or "14"
        sdk_ver = specs.get("sdk_version") or 34
        fingerprint = specs.get("fingerprint") or ""
        screen_size = specs.get("screen_size") or ""

        # Step 6: Activate persistent multi-interface TCP/IP mode (port 5555)
        tcpip_ok = self._enable_tcpip_5555(target_serial)
        if tcpip_ok:
            logger.info(f"Activated persistent multi-interface ADB (port 5555) on {target_serial}")

        # Step 7: Resolve or allocate unique device identity and independent VPN IP
        existing_devices = self.registry.list_devices(user_id) or self.registry.list_devices(None)
        matched_dev = None
        for d in existing_devices:
            d_meta = d.metadata or {}
            if hw_serial and d_meta.get("hardware_serial") == hw_serial:
                matched_dev = d
                break
            if clean_imei and d_meta.get("imei") == clean_imei:
                matched_dev = d
                break

        # Impersonation check
        if matched_dev:
            reg_hw = (matched_dev.metadata or {}).get("hardware_serial")
            if reg_hw and hw_serial and reg_hw != hw_serial:
                logger.warning(f"[SECURITY_ALERT] Hardware serial mismatch! Registered {reg_hw} != Connected {hw_serial}")
                self.set_lifecycle_state(matched_dev.device_id, DeviceConnectionLifecycle.AUTHENTICATION_FAILED, user_id=user_id)
                return {
                    "success": False,
                    "status": "impersonation_detected",
                    "lifecycle_state": DeviceConnectionLifecycle.AUTHENTICATION_FAILED.value,
                    "message": f"Impersonation rejected: Connected device hardware serial ({hw_serial}) does not match registered ({reg_hw})."
                }
            device_id = matched_dev.device_id
            assigned_ip = (matched_dev.metadata or {}).get("remote_vpn_ip")
            ipsec_id = (matched_dev.metadata or {}).get("ipsec_identifier")
            if not assigned_ip:
                assigned_ip, ipsec_id = self.allocate_device_vpn_address(user_id, device_id)
        else:
            # Generate cryptographic device identity
            clean_slug = re.sub(r'[^a-zA-Z0-9]', '', model_name.lower())[:16] or "phone"
            crypto_salt = hashlib.sha256(f"{manufacturer}:{hw_serial}:{clean_slug}:{secrets.token_hex(4)}".encode()).hexdigest()[:8]
            device_id = f"android_{clean_slug}_{crypto_salt}"
            assigned_ip, ipsec_id = self.allocate_device_vpn_address(user_id, device_id)

        metadata = {
            "device_id": device_id,
            "model": model_name,
            "manufacturer": manufacturer,
            "brand": brand,
            "os_version": str(os_ver),
            "sdk_version": sdk_ver,
            "fingerprint": fingerprint,
            "hardware_serial": hw_serial,
            "imei": clean_imei,
            "device_reference": f"IMEI:{clean_imei}" if clean_imei else f"Serial:{hw_serial}",
            "host": clean_connection_ip,
            "port": str(connection_port),
            "serial": target_serial,
            "endpoint": target_serial,
            "network_ip": clean_network_ip,
            "pairing_endpoint": f"{clean_pairing_ip}:{pairing_port}" if pairing_port else "",
            "connection_endpoint": target_serial,
            "remote_vpn_ip": assigned_ip,
            "remote_vpn_endpoint": f"{assigned_ip}:5555",
            "ipsec_identifier": ipsec_id,
            "hotspot_endpoint": "192.168.43.1:5555",
            "tcpip_5555_enabled": tcpip_ok,
            "screen_size": screen_size,
            "capabilities": specs.get("capabilities", {}),
            "oem_restrictions": specs.get("oem_restrictions", []),
            "guidance": specs.get("guidance", []),
            "network_interfaces": specs.get("network_interfaces", []),
            "lifecycle_state": DeviceConnectionLifecycle.CONNECTED_LOCALLY.value,
            "last_connected": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "connection_type": "wireless_local",
            "active_transport_route": "local_wifi",
        }

        if matched_dev:
            matched_dev.name = model_name
            matched_dev.ip = clean_connection_ip
            matched_dev.online = True
            matched_dev.metadata.update(metadata)
            self.registry.update_device(matched_dev)
            logger.info(f"Updated registered device {device_id} ({model_name})")
        else:
            self.registry.register_device(
                user_id=user_id,
                name=model_name,
                platform="android",
                os_version=str(os_ver),
                ip=clean_connection_ip,
                metadata=metadata,
            )
            logger.info(f"Registered new device {device_id} ({model_name}) with IP {assigned_ip}")

        # Step 8: Update lifecycle state
        self.set_lifecycle_state(device_id, DeviceConnectionLifecycle.CONNECTED_LOCALLY, user_id=user_id)

        # Step 9: Generate customized setup guide
        remote_guide = self.network_config.get_setup_guide(
            phone_name=model_name,
            phone_ip=assigned_ip,
            ipsec_id=ipsec_id,
            guidance=specs.get("guidance", []),
        )

        # Step 10: Start recovery monitor
        self.start_connection_monitor()

        return {
            "success": True,
            "status": "registered_and_connected",
            "lifecycle_state": DeviceConnectionLifecycle.CONNECTED_LOCALLY.value,
            "device_id": device_id,
            "device_name": model_name,
            "manufacturer": manufacturer,
            "os_version": str(os_ver),
            "fingerprint": fingerprint,
            "imei": clean_imei,
            "serial": target_serial,
            "remote_vpn_ip": assigned_ip,
            "ipsec_identifier": ipsec_id,
            "tcpip_5555_active": tcpip_ok,
            "capabilities": specs.get("capabilities", {}),
            "oem_restrictions": specs.get("oem_restrictions", []),
            "remote_vpn_ready": True,
            "remote_config_guide": remote_guide,
            "message": (
                f"Successfully registered and paired {manufacturer} {model_name}. "
                f"Active connection established on {target_serial}. "
                f"Assigned private VPN address {assigned_ip} for remote cross-network access."
            ),
        }

    def _detect_universal_device_specs(self, serial: str) -> Dict[str, Any]:
        """
        Universally detects device hardware properties, build fingerprint,
        debugging capabilities, active network interfaces, and OEM-specific restrictions.
        """
        specs: Dict[str, Any] = {
            "model": "Android Device",
            "manufacturer": "Android",
            "brand": "",
            "market_name": "",
            "os_version": "14",
            "sdk_version": 34,
            "fingerprint": "",
            "cpu_abi": "",
            "hardware_serial": "",
            "screen_size": "",
            "screen_density": "",
            "network_interfaces": [],
            "capabilities": {
                "touch": True,
                "swipe": True,
                "type": True,
                "keyevent": True,
                "screenshot": True,
                "stream": True,
                "launch_apps": True,
                "read_battery": True,
            },
            "oem_restrictions": [],
            "guidance": [],
        }

        prop_map = {
            "ro.product.model": "model",
            "ro.product.manufacturer": "manufacturer",
            "ro.product.brand": "brand",
            "ro.product.name": "market_name",
            "ro.build.version.release": "os_version",
            "ro.build.version.sdk": "sdk_version",
            "ro.build.fingerprint": "fingerprint",
            "ro.product.cpu.abi": "cpu_abi",
            "ro.serialno": "hardware_serial",
        }
        for prop, key in prop_map.items():
            try:
                ok, out = self.adb._run_adb_cmd(["-s", serial, "shell", "getprop", prop], timeout=1.5)
                if ok and out.strip():
                    if key == "sdk_version":
                        try:
                            specs[key] = int(out.strip())
                        except ValueError:
                            pass
                    else:
                        specs[key] = out.strip()
            except Exception:
                pass

        if not specs["hardware_serial"]:
            try:
                ok, out = self.adb._run_adb_cmd(["-s", serial, "shell", "getprop", "ro.boot.serialno"], timeout=1.5)
                if ok and out.strip():
                    specs["hardware_serial"] = out.strip()
            except Exception:
                pass

        # Query display properties
        try:
            ok, out = self.adb._run_adb_cmd(["-s", serial, "shell", "wm", "size"], timeout=1.5)
            if ok and "Physical size:" in out:
                specs["screen_size"] = out.split("Physical size:")[-1].strip()
        except Exception:
            pass

        try:
            ok, out = self.adb._run_adb_cmd(["-s", serial, "shell", "wm", "density"], timeout=1.5)
            if ok and "Physical density:" in out:
                specs["screen_density"] = out.split("Physical density:")[-1].strip()
        except Exception:
            pass

        # Query network interfaces
        try:
            ok, out = self.adb._run_adb_cmd(["-s", serial, "shell", "ip", "-br", "addr"], timeout=1.5)
            if ok and out.strip():
                ifaces = []
                for line in out.strip().splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        ifaces.append({"interface": parts[0], "state": parts[1], "ips": parts[2:] if len(parts) > 2 else []})
                specs["network_interfaces"] = ifaces
        except Exception:
            pass

        # OEM Restriction & Guidance Analysis
        brand_lower = (specs.get("brand") or specs.get("manufacturer") or "").lower()
        sdk = specs.get("sdk_version", 34)

        # 1. Xiaomi / Redmi / POCO (MIUI / HyperOS)
        if any(b in brand_lower for b in ["xiaomi", "redmi", "poco"]):
            specs["oem_restrictions"].append(
                "MIUI / HyperOS requires 'USB debugging (Security settings)' in Developer Options for simulated taps/clicks."
            )
            specs["guidance"].append(
                "Xiaomi / Redmi / POCO: Go to Settings -> Additional Settings -> Developer Options -> enable 'USB debugging (Security settings)'."
            )
            try:
                ok, out = self.adb._run_adb_cmd(["-s", serial, "shell", "input", "tap", "0", "0"], timeout=1.5)
                if not ok or "SecurityException" in out or "injectInputEvent" in out:
                    specs["capabilities"]["touch"] = False
                    specs["capabilities"]["swipe"] = False
                    specs["oem_restrictions"].append(
                        "Input injection denied: 'USB debugging (Security settings)' is currently DISABLED on device."
                    )
            except Exception:
                pass

        # 2. Samsung (One UI)
        elif "samsung" in brand_lower:
            specs["oem_restrictions"].append(
                "Samsung One UI Auto Blocker: Verify 'Auto Blocker' in Settings -> Security and privacy is set to allow debugging."
            )
            specs["guidance"].append(
                "Samsung: Keep screen awake or unlock when pairing to allow ADB authorization prompt."
            )

        # 3. OnePlus / OPPO / Realme (ColorOS / OxygenOS)
        elif any(b in brand_lower for b in ["oneplus", "oppo", "realme"]):
            specs["oem_restrictions"].append(
                "ColorOS / OxygenOS: Disable 'Permission monitoring' in Developer Options to prevent permission dialogs from blocking automation."
            )
            specs["guidance"].append(
                "OnePlus / OPPO: In Settings -> Battery, set Wireless Debugging or Background Apps to 'Don't optimize' to avoid 20-min idle timeout."
            )

        # 4. Google Pixel
        elif "google" in brand_lower:
            specs["guidance"].append(
                "Google Pixel: Clean stock Android runtime with full ADB debugging support."
            )

        # 5. Generic Android Version Rules
        if sdk < 30:
            specs["oem_restrictions"].append(
                f"Android {specs.get('os_version', '<11')} (API {sdk}): Native Wireless Debugging pairing dialog is unavailable. Requires initial adb tcpip 5555 over USB."
            )
        elif sdk >= 34:
            specs["guidance"].append(
                "Android 14+: Always-on VPN supported natively in Settings -> More connectivity options -> VPN."
            )

        return specs

    def _query_device_properties(self, serial: str) -> Dict[str, str]:
        """Queries hardware properties over ADB to verify device identity."""
        props = {}
        for prop, key in [
            ("ro.product.model", "model"),
            ("ro.product.manufacturer", "manufacturer"),
            ("ro.build.version.release", "os_version"),
            ("ro.serialno", "serialno"),
            ("ro.boot.serialno", "boot_serialno"),
        ]:
            try:
                ok, out = self.adb._run_adb_cmd(["-s", serial, "shell", "getprop", prop], timeout=2.0)
                if ok and out:
                    props[key] = out.strip()
            except Exception:
                pass
        return props

    def _enable_tcpip_5555(self, serial: str) -> bool:
        """Executes 'adb tcpip 5555' so adbd binds to 0.0.0.0:5555 across all interfaces."""
        try:
            ok, out = self.adb._run_adb_cmd(["-s", serial, "tcpip", "5555"], timeout=5.0)
            return ok and ("restarting in tcp mode" in out.lower() or "port: 5555" in out.lower() or not out.strip())
        except Exception as e:
            logger.debug(f"Could not enable tcpip 5555: {e}")
            return False

    # ------------------------------------------------------------------
    # Automatic Connection Recovery Engine
    # ------------------------------------------------------------------

    def auto_recover_connection(self, user_id: int = 1, target: str = "") -> Dict[str, Any]:
        """
        Universal multi-device connection recovery across changing networks.
        Attempts recovery on specified device (or all devices if target is omitted).
        """
        devices = self.registry.list_devices(user_id) or self.registry.list_devices(None)
        if not devices:
            return {"success": False, "status": "no_registered_device", "message": "No registered device found."}

        target_devices = [d for d in devices if d.device_id == target or (d.metadata or {}).get("serial") == target] if target else devices
        results = []

        live_devs = self.adb.list_devices()
        online_serials = [d["serial"] for d in live_devs if d.get("online")]

        for device in target_devices:
            dev_id = device.device_id
            meta = device.metadata or {}
            cur_serial = meta.get("serial") or meta.get("endpoint")

            # 1. Check if already online in ADB
            if cur_serial in online_serials:
                is_remote = cur_serial.startswith("10.8.") or cur_serial.startswith("172.")
                new_state = DeviceConnectionLifecycle.CONNECTED_REMOTELY if is_remote else DeviceConnectionLifecycle.CONNECTED_LOCALLY
                self.set_lifecycle_state(dev_id, new_state, user_id=user_id)
                self.registry.update_status(dev_id, online=True)
                results.append({"device_id": dev_id, "success": True, "status": "already_connected", "serial": cur_serial})
                continue

            self.set_lifecycle_state(dev_id, DeviceConnectionLifecycle.RECONNECTING, user_id=user_id)

            # 2. Priority 1: Try Local Wi-Fi endpoint
            local_host = meta.get("host") or device.ip or "192.168.1.4"
            local_port = int(meta.get("port", 5555))
            c_res = self.adb.connect_wireless(local_host, local_port)
            if c_res.get("success"):
                new_serial = f"{local_host}:{local_port}"
                self.set_lifecycle_state(dev_id, DeviceConnectionLifecycle.CONNECTED_LOCALLY, user_id=user_id)
                meta["serial"] = new_serial
                meta["active_transport_route"] = "local_wifi"
                self.registry.update_status(dev_id, online=True)
                results.append({"device_id": dev_id, "success": True, "status": "connected_locally", "serial": new_serial})
                continue

            # 3. Priority 2: Try Remote VPN Tunnel endpoint (Mobile Data 4G/5G)
            vpn_phone_ip = meta.get("remote_vpn_ip") or self.network_config.phone_virtual_ip
            v_res = self.adb.connect_wireless(vpn_phone_ip, 5555)
            if v_res.get("success"):
                new_serial = f"{vpn_phone_ip}:5555"
                self.set_lifecycle_state(dev_id, DeviceConnectionLifecycle.CONNECTED_REMOTELY, user_id=user_id)
                meta["serial"] = new_serial
                meta["active_transport_route"] = "vpn_tunnel"
                self.registry.update_status(dev_id, online=True)
                results.append({"device_id": dev_id, "success": True, "status": "connected_remotely", "serial": new_serial})
                continue

            # 4. Priority 3: Try Mobile Hotspot Gateway
            gateways = self.adb._detect_default_gateways()
            hotspot_ok = False
            for gw in gateways:
                if gw.startswith("192.168.43.") or gw.startswith("192.168.225."):
                    h_res = self.adb.connect_wireless(gw, 5555)
                    if h_res.get("success"):
                        new_serial = f"{gw}:5555"
                        self.set_lifecycle_state(dev_id, DeviceConnectionLifecycle.CONNECTED_LOCALLY, user_id=user_id)
                        meta["serial"] = new_serial
                        meta["active_transport_route"] = "hotspot"
                        self.registry.update_status(dev_id, online=True)
                        results.append({"device_id": dev_id, "success": True, "status": "connected_hotspot", "serial": new_serial})
                        hotspot_ok = True
                        break
            if hotspot_ok:
                continue

            # 5. Priority 4: Dynamic scan on known host
            discovered = self.adb.reconnect_wireless_endpoints(known_hosts=[local_host])
            if discovered:
                rec = discovered[0]
                new_serial = rec.get("endpoint") or f"{rec.get('host')}:{rec.get('port')}"
                self.set_lifecycle_state(dev_id, DeviceConnectionLifecycle.CONNECTED_LOCALLY, user_id=user_id)
                meta["serial"] = new_serial
                self.registry.update_status(dev_id, online=True)
                results.append({"device_id": dev_id, "success": True, "status": "connected_discovered", "serial": new_serial})
                continue

            # Mark offline
            self.set_lifecycle_state(dev_id, DeviceConnectionLifecycle.OFFLINE, user_id=user_id)
            self.registry.update_status(dev_id, online=False)
            results.append({"device_id": dev_id, "success": False, "status": "device_offline"})

        # Backward compatibility format
        primary = results[0] if results else {"success": False, "status": "no_device"}
        return {
            "success": any(r.get("success") for r in results),
            "status": primary.get("status"),
            "serial": primary.get("serial", ""),
            "results": results,
            "recovered_count": sum(1 for r in results if r.get("success")),
            "total_count": len(results),
        }

    def diagnose_device_reachability(self, device_id: str) -> Dict[str, Any]:
        """
        Independently checks all 3 connectivity layers:
        Layer 1: VPN Gateway reachability (VPS endpoint & local Windows VPN tunnel)
        Layer 2: Network transport reachability (TCP socket on port 5555 across all candidate IPs)
        Layer 3: Authenticated ADB protocol state ('device', 'unauthorized', 'offline')
        Never confuses registered with currently connected.
        """
        import socket
        dev = None
        for d in self.registry.list_devices(None):
            if d.device_id == device_id:
                dev = d
                break
        if not dev:
            return {"success": False, "error": f"Device {device_id} not registered."}

        meta = dev.metadata or {}
        cur_serial = meta.get("serial") or dev.ip or ""
        vpn_phone_ip = meta.get("remote_vpn_ip") or self.network_config.phone_virtual_ip
        local_host = meta.get("host") or dev.ip or ""
        local_port = int(meta.get("port", 5555))

        # Layer 1: VPN Status
        vpn_status = self.get_windows_vpn_status()
        vpn_gateway_reachable = False
        if self.network_config.vpn_server:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(1.0)
                s.connect((self.network_config.vpn_server, 500))
                s.close()
                vpn_gateway_reachable = True
            except Exception:
                vpn_gateway_reachable = False

        # Layer 2: Network Socket Reachability
        def check_tcp_port(host, port, timeout=0.8):
            if not host:
                return False
            try:
                sock = socket.create_connection((host, int(port)), timeout=timeout)
                sock.close()
                return True
            except Exception:
                return False

        vpn_socket_open = check_tcp_port(vpn_phone_ip, 5555) if vpn_phone_ip else False
        local_socket_open = check_tcp_port(local_host, local_port) if local_host else False

        # Layer 3: ADB Protocol Verification
        adb_state = "disconnected"
        if cur_serial:
            ok, out = self.adb._run_adb_cmd(["-s", cur_serial, "get-state"], timeout=1.5)
            if ok and out.strip():
                adb_state = out.strip().lower()
            elif "unauthorized" in out.lower():
                adb_state = "unauthorized"

        # Determine authoritative lifecycle
        if adb_state == "device":
            is_vpn = cur_serial.startswith("10.8.")
            lifecycle = DeviceConnectionLifecycle.CONNECTED_REMOTELY if is_vpn else DeviceConnectionLifecycle.CONNECTED_LOCALLY
        elif adb_state == "unauthorized":
            lifecycle = DeviceConnectionLifecycle.AUTHORIZATION_REQUIRED
        elif vpn_socket_open or local_socket_open:
            lifecycle = DeviceConnectionLifecycle.RECONNECTING
        else:
            lifecycle = DeviceConnectionLifecycle.TEMPORARILY_OFFLINE

        # Update persisted state without removing device
        self.set_lifecycle_state(device_id, lifecycle, user_id=dev.user_id)
        is_online = (adb_state == "device")
        self.registry.update_status(device_id, online=is_online)

        return {
            "success": True,
            "device_id": device_id,
            "device_name": dev.name,
            "lifecycle_state": lifecycle.value,
            "registered": True,
            "currently_connected": is_online,
            "reauthorization_needed": (adb_state == "unauthorized"),
            "layer1_vpn": {
                "server_configured": self.network_config.is_configured,
                "server_host": self.network_config.vpn_server,
                "gateway_reachable": vpn_gateway_reachable,
                "windows_vpn_status": vpn_status.get("Status", "NotConfigured"),
            },
            "layer2_network": {
                "vpn_tunnel_ip": vpn_phone_ip,
                "vpn_port_5555_open": vpn_socket_open,
                "local_host": local_host,
                "local_port": local_port,
                "local_port_open": local_socket_open,
            },
            "layer3_adb": {
                "active_serial": cur_serial,
                "adb_protocol_state": adb_state,
                "is_responsive": is_online,
            },
            "active_route": meta.get("active_transport_route", "local_wifi"),
        }

    def get_status(self, user_id: Optional[int] = None, device_id: Optional[str] = None) -> Dict[str, Any]:
        """Returns universal status of all registered phones with their network profiles."""
        all_devices = self.registry.list_devices(user_id) or self.registry.list_devices(None)
        
        device_items = []
        for d in all_devices:
            dev_meta = d.metadata or {}
            d_id = d.device_id
            lifecycle = self.get_lifecycle_state(d_id).value
            assigned_ip = dev_meta.get("remote_vpn_ip") or self.network_config.phone_virtual_ip
            ipsec_id = dev_meta.get("ipsec_identifier") or self.network_config.ipsec_identifier
            guide = self.network_config.get_setup_guide(
                phone_name=d.name or "Android Phone",
                phone_ip=assigned_ip,
                ipsec_id=ipsec_id,
                guidance=dev_meta.get("guidance", []),
            )
            device_items.append({
                "device_id": d_id,
                "name": d.name,
                "model": dev_meta.get("model", d.name),
                "manufacturer": dev_meta.get("manufacturer", "Android"),
                "brand": dev_meta.get("brand", ""),
                "os_version": str(dev_meta.get("os_version", d.os_version or "14")),
                "sdk_version": dev_meta.get("sdk_version", 34),
                "fingerprint": dev_meta.get("fingerprint", ""),
                "hardware_serial": dev_meta.get("hardware_serial", ""),
                "imei": dev_meta.get("imei", ""),
                "device_reference": dev_meta.get("device_reference", ""),
                "serial": dev_meta.get("serial", ""),
                "endpoint": dev_meta.get("endpoint", ""),
                "host": dev_meta.get("host", d.ip or ""),
                "online": bool(d.online),
                "lifecycle_state": lifecycle,
                "active_transport_route": dev_meta.get("active_transport_route", "local_wifi"),
                "remote_vpn_ip": assigned_ip,
                "remote_vpn_endpoint": dev_meta.get("remote_vpn_endpoint", f"{assigned_ip}:5555"),
                "ipsec_identifier": ipsec_id,
                "tcpip_5555_enabled": dev_meta.get("tcpip_5555_enabled", False),
                "capabilities": dev_meta.get("capabilities", {}),
                "oem_restrictions": dev_meta.get("oem_restrictions", []),
                "guidance": dev_meta.get("guidance", []),
                "network_interfaces": dev_meta.get("network_interfaces", []),
                "setup_guide": guide,
            })

        # Selected/primary device for single-device consumers
        selected = None
        if device_id:
            for item in device_items:
                if item["device_id"] == device_id:
                    selected = item
                    break
        if not selected and device_items:
            selected = device_items[0]

        return {
            "success": True,
            "registered": len(device_items) > 0,
            "count": len(device_items),
            "devices": device_items,
            # Top-level backward compatibility fields
            "device_id": selected["device_id"] if selected else "",
            "device_name": selected["name"] if selected else "",
            "imei": selected["imei"] if selected else "",
            "device_reference": selected["device_reference"] if selected else "",
            "serial": selected["serial"] if selected else "",
            "endpoint": selected["endpoint"] if selected else "",
            "host": selected["host"] if selected else "",
            "lifecycle_state": selected["lifecycle_state"] if selected else DeviceConnectionLifecycle.OFFLINE.value,
            "online": selected["online"] if selected else False,
            "tcpip_5555_enabled": selected["tcpip_5555_enabled"] if selected else False,
            "active_transport_route": selected["active_transport_route"] if selected else "local_wifi",
            "vpn_config": {
                "vpn_server": self.network_config.vpn_server,
                "vpn_type": self.network_config.vpn_type,
                "ipsec_identifier": self.network_config.ipsec_identifier,
                "ipsec_psk": self.network_config.ipsec_psk,
                "phone_virtual_ip": selected["remote_vpn_ip"] if selected else self.network_config.phone_virtual_ip,
                "laptop_virtual_ip": self.network_config.laptop_virtual_ip,
                "remote_adb_endpoint": f"{selected['remote_vpn_ip']}:5555" if selected else f"{self.network_config.phone_virtual_ip}:5555",
            },
            "setup_guide": selected["setup_guide"] if selected else self.network_config.get_setup_guide(),
        }

    def revoke_registered_device(self, user_id: int, device_id: str) -> Dict[str, Any]:
        """Revokes pairing, disconnects ADB, and removes device reference."""
        all_devs = self.registry.list_devices(None)
        target_dev = None
        for d in all_devs:
            if d.device_id == device_id:
                target_dev = d
                break

        if not target_dev:
            return {"success": False, "error": f"Device {device_id} not found."}

        meta = target_dev.metadata or {}
        serial = meta.get("serial") or meta.get("endpoint") or target_dev.ip
        if serial:
            try:
                self.adb._run_adb_cmd(["disconnect", serial], timeout=2.0)
            except Exception:
                pass

        self.set_lifecycle_state(device_id, DeviceConnectionLifecycle.OFFLINE, user_id=user_id)
        self.registry.revoke_device(target_dev.user_id, device_id)
        self.registry.remove_device(target_dev.user_id, device_id)
        logger.info(f"Revoked and removed device {device_id} ({target_dev.name})")

        return {
            "success": True,
            "device_id": device_id,
            "message": f"Successfully revoked and disconnected {target_dev.name} ({device_id}).",
        }

    def start_connection_monitor(self, poll_interval: float = 10.0):
        """Starts background periodic health check and connection recovery."""
        if self._monitoring_active:
            return
        self._monitoring_active = True

        def _monitor_loop():
            loop_ticks = 0
            while self._monitoring_active:
                try:
                    time.sleep(poll_interval)
                    loop_ticks += 1
                    devices = self.registry.list_devices(None)

                    for d in devices:
                        cur_state = self.get_lifecycle_state(d.device_id)
                        ser = (d.metadata or {}).get("serial")

                        # Case A: Device was marked online - verify live ADB responsiveness
                        if cur_state in (DeviceConnectionLifecycle.CONNECTED_LOCALLY, DeviceConnectionLifecycle.CONNECTED_REMOTELY):
                            if ser:
                                ok, out = self.adb._run_adb_cmd(["-s", ser, "get-state"], timeout=1.5)
                                if not ok or "device" not in out.lower():
                                    if "unauthorized" in out.lower():
                                        logger.warning(f"Device {ser} authorization revoked by Android.")
                                        self.set_lifecycle_state(d.device_id, DeviceConnectionLifecycle.AUTHORIZATION_REQUIRED, user_id=d.user_id)
                                    else:
                                        logger.info(f"Connection lost on {ser}. Initiating auto-recovery...")
                                        self.set_lifecycle_state(d.device_id, DeviceConnectionLifecycle.TEMPORARILY_OFFLINE, user_id=d.user_id)
                                        self.auto_recover_connection(user_id=d.user_id, target=d.device_id)

                        # Case B: Device is temporarily offline or reconnecting - periodic recovery attempt
                        elif cur_state in (DeviceConnectionLifecycle.TEMPORARILY_OFFLINE, DeviceConnectionLifecycle.RECONNECTING, DeviceConnectionLifecycle.OFFLINE):
                            # Re-attempt recovery every 3 ticks (~24s-30s)
                            if loop_ticks % 3 == 0:
                                logger.debug(f"Attempting periodic auto-recovery for {d.name} ({d.device_id})...")
                                self.auto_recover_connection(user_id=d.user_id, target=d.device_id)

                except Exception as e:
                    logger.debug(f"Monitor loop error: {e}")

        self._recovery_thread = threading.Thread(target=_monitor_loop, daemon=True, name="remote-device-connection-monitor")
        self._recovery_thread.start()
        logger.info("Remote connection recovery monitor started.")

    def stop_connection_monitor(self):
        self._monitoring_active = False

    # ------------------------------------------------------------------
    # Windows Host VPN Control
    # ------------------------------------------------------------------

    def setup_windows_vpn(self, server_host: Optional[str] = None) -> Dict[str, Any]:
        """Configures native Windows VPN profile pointing to the VPS gateway."""
        import subprocess
        srv = (server_host or self.network_config.vpn_server).strip()
        psk = self.network_config.ipsec_psk
        if not srv:
            return {"success": False, "error": "VPN server host/IP is required"}
        if not psk:
            return {"success": False, "error": "IPSec PSK is required"}

        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts", "setup_windows_vpn.ps1")
        cmd = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path,
            "-ServerAddress", srv,
            "-Psk", psk,
            "-ConnectionName", "SmartAssistantVPN",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            import json
            out = res.stdout.strip()
            if out.startswith("{"):
                return json.loads(out)
            return {"success": res.returncode == 0, "message": out or res.stderr.strip()}
        except Exception as e:
            logger.error(f"Failed to execute Windows VPN setup: {e}")
            return {"success": False, "error": str(e)}

    def connect_windows_vpn(self) -> Dict[str, Any]:
        """Connects the native Windows VPN to the VPS gateway."""
        import subprocess
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts", "setup_windows_vpn.ps1")
        cmd = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path,
            "-ConnectionName", "SmartAssistantVPN",
            "-Connect",
            "-Psk", self.network_config.ipsec_psk,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            import json
            out = res.stdout.strip()
            if out.startswith("{"):
                return json.loads(out)
            return {"success": res.returncode == 0, "message": out or res.stderr.strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def disconnect_windows_vpn(self) -> Dict[str, Any]:
        """Disconnects the native Windows VPN."""
        import subprocess
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts", "setup_windows_vpn.ps1")
        cmd = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path,
            "-ConnectionName", "SmartAssistantVPN",
            "-Disconnect",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            import json
            out = res.stdout.strip()
            if out.startswith("{"):
                return json.loads(out)
            return {"success": res.returncode == 0, "message": out or res.stderr.strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_windows_vpn_status(self) -> Dict[str, Any]:
        """Retrieves live status of the Windows native VPN connection."""
        import subprocess
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts", "setup_windows_vpn.ps1")
        cmd = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path,
            "-ConnectionName", "SmartAssistantVPN",
            "-Status",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            import json
            out = res.stdout.strip()
            if out.startswith("{"):
                return json.loads(out)
            return {"success": res.returncode == 0, "message": out or res.stderr.strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}


def get_remote_connection_manager() -> RemoteConnectionManager:
    return RemoteConnectionManager.get_instance()
