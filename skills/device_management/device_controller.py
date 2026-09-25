"""
Device Controller Skill Interface
Provides the high-level conversational interface for device pairing, status checks, and remote commands.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from .config import DeviceGatewayConfig
from .device_discovery import get_local_ip
from .device_dispatcher import RemoteDeviceDispatcher, get_device_dispatcher
from .device_pairing import DevicePairingManager, get_pairing_manager
from .device_registry import DeviceRegistry, get_device_registry

logger = logging.getLogger(__name__)


class DeviceController:
    """
    Conversational controller for remote device capabilities.
    Integrates registry, pairing, and command dispatching with strict user isolation.
    """

    def __init__(
        self,
        registry: Optional[DeviceRegistry] = None,
        pairing_manager: Optional[DevicePairingManager] = None,
        dispatcher: Optional[RemoteDeviceDispatcher] = None,
    ):
        self.registry = registry or get_device_registry()
        self.pairing_manager = pairing_manager or get_pairing_manager()
        self.dispatcher = dispatcher or get_device_dispatcher()
        self.config = DeviceGatewayConfig.from_env()

    def pair_device(self, user_id: int) -> dict[str, Any]:
        """Generate a new pairing offer with a 6-digit PIN code."""
        ip = get_local_ip()
        offer = self.pairing_manager.create_offer(
            user_id=user_id,
            gateway_host=ip,
            gateway_port=self.config.port,
            ttl_seconds=self.config.pairing_ttl_seconds,
        )
        msg = (
            f"Ready to pair your mobile device. Enter pairing code: {offer.code} in the Assistant Connect app. "
            f"Gateway is available at {ip}:{self.config.port}. Code expires in 5 minutes."
        )
        return {
            "success": True,
            "status": "pairing_started",
            "code": offer.code,
            "offer_id": offer.offer_id,
            "token": offer.token,
            "gateway_host": ip,
            "gateway_port": self.config.port,
            "expires_at": offer.expires_at,
            "qr_payload": offer.to_qr_payload(),
            "message": msg,
        }

    def get_active_pairing_code(self, user_id: int) -> dict[str, Any]:
        """Retrieve active pairing code if an unexpired offer exists."""
        offer = self.pairing_manager.get_active_offer_for_user(user_id)
        if offer:
            try:
                exp = datetime.fromisoformat(offer.expires_at)
                now = datetime.now(timezone.utc)
                if exp > now:
                    remaining_mins = max(1, int((exp - now).total_seconds() / 60))
                    msg = f"Your active pairing code is {offer.code}. It expires in about {remaining_mins} minute(s)."
                    return {
                        "success": True,
                        "status": "pairing_code_active",
                        "code": offer.code,
                        "offer_id": offer.offer_id,
                        "expires_at": offer.expires_at,
                        "message": msg,
                    }
            except Exception:
                pass
        return {
            "success": False,
            "status": "no_active_pairing_code",
            "message": "There is no active pairing code. Say 'pair phone' to generate a new one.",
        }

    def list_devices(self, user_id: int) -> dict[str, Any]:
        """List all paired devices belonging to the user."""
        devices = self.registry.list_devices(user_id)
        if not devices:
            return {
                "success": True,
                "status": "no_devices",
                "count": 0,
                "devices": [],
                "message": "You don't have any mobile devices paired yet. Say 'pair phone' to connect a device.",
            }

        dev_summaries = []
        for d in devices:
            state = "online" if d.online else "offline"
            batt = f", battery {d.battery}%" if d.battery is not None else ""
            dev_summaries.append(f"{d.name} ({state}{batt})")

        msg = f"You have {len(devices)} paired device(s): {', '.join(dev_summaries)}."
        return {
            "success": True,
            "status": "success",
            "count": len(devices),
            "devices": [d.to_dict() for d in devices],
            "message": msg,
        }

    def get_battery(self, user_id: int, target: str = "") -> dict[str, Any]:
        """Check battery status of user's paired mobile device."""
        devices = self.registry.resolve_device(user_id, target)
        if not devices:
            return {
                "success": False,
                "status": "not_paired",
                "message": "No paired phone found. Say 'pair phone' to connect your device.",
            }

        dev = devices[0]
        # If online and connected via dispatcher, request live battery
        if dev.online and self.dispatcher.is_connected(dev.device_id):
            res = self.dispatcher.dispatch_command_sync(user_id, dev.name, "get_battery", timeout=5.0)
            if res.get("success") and isinstance(res.get("data"), dict):
                pct = res["data"].get("percentage", dev.battery)
                chg = res["data"].get("charging", dev.charging)
                chg_str = " (charging)" if chg else ""
                msg = f"Your {dev.name} battery is at {pct}%{chg_str}."
                return {"success": True, "status": "success", "battery": pct, "charging": chg, "message": msg}

        # If recorded in registry
        if dev.battery is not None:
            state = " (offline)" if not dev.online else ""
            chg_str = " and charging" if dev.charging else ""
            msg = f"Last reported battery for your {dev.name} was {dev.battery}%{chg_str}{state}."
            return {"success": True, "status": "cached", "battery": dev.battery, "charging": dev.charging, "message": msg}

        state_str = "online" if dev.online else "offline"
        return {
            "success": False,
            "status": "unavailable",
            "message": f"Your {dev.name} is {state_str}, but hasn't reported its battery level yet.",
        }

    def toggle_flashlight(self, user_id: int, enable: bool = True, target: str = "") -> dict[str, Any]:
        """Turn mobile flashlight on or off."""
        action = "flashlight_on" if enable else "flashlight_off"
        res = self.dispatcher.dispatch_command_sync(
            user_id,
            target or "phone",
            action,
            parameters={"required_capability": "flashlight"},
            timeout=5.0
        )
        if res.get("success"):
            state_str = "on" if enable else "off"
            dev_name = res.get("device", "phone")
            res["message"] = f"Turned {state_str} the flashlight on your {dev_name}."
        return res

    def launch_app(self, user_id: int, app_name: str, target: str = "") -> dict[str, Any]:
        """Launch an application on the user's paired mobile device."""
        if not app_name:
            return {"success": False, "status": "error", "message": "Please specify an app name to open on your phone."}

        res = self.dispatcher.dispatch_command_sync(
            user_id,
            target or "phone",
            "launch_app",
            parameters={"app_name": app_name, "required_capability": "launch_app"},
            timeout=5.0
        )
        if res.get("success"):
            dev_name = res.get("device", "phone")
            res["message"] = f"Opened {app_name} on your {dev_name}."
        return res

    def get_connection_status(self, user_id: int, target: str = "") -> dict[str, Any]:
        """Check online/connection status of user's paired mobile device(s)."""
        devices = self.registry.resolve_device(user_id, target)
        if not devices:
            return {
                "success": False,
                "status": "not_paired",
                "connected": False,
                "online": False,
                "message": "No paired phone found. Say 'pair my phone' to connect your device.",
            }

        dev = devices[0]
        # Check active live connection via dispatcher and registry online flag
        is_live = self.dispatcher.is_connected(dev.device_id)
        is_online = dev.online or is_live

        if is_live:
            msg = f"Your {dev.name} is connected and online."
            return {
                "success": True,
                "status": "connected",
                "connected": True,
                "online": True,
                "device": dev.to_dict(),
                "message": msg,
            }
        elif is_online:
            msg = f"Your {dev.name} is registered as online, but there is no active communication session."
            return {
                "success": True,
                "status": "idle",
                "connected": False,
                "online": True,
                "device": dev.to_dict(),
                "message": msg,
            }
        else:
            msg = f"Your {dev.name} is currently offline and not connected."
            return {
                "success": True,
                "status": "offline",
                "connected": False,
                "online": False,
                "device": dev.to_dict(),
                "message": msg,
            }

    def disconnect_device(self, user_id: int, target: str = "") -> dict[str, Any]:
        """Disconnect an active communication session for a user's paired device."""
        devices = self.registry.resolve_device(user_id, target)
        if not devices:
            return {
                "success": False,
                "status": "not_paired",
                "message": "No paired phone found to disconnect.",
            }
        dev = devices[0]
        if self.dispatcher.is_connected(dev.device_id):
            self.dispatcher.unregister_connection(dev.device_id)
            self.registry.update_status(dev.device_id, online=False)
            return {
                "success": True,
                "status": "disconnected",
                "message": f"Disconnected {dev.name}.",
            }
        return {
            "success": True,
            "status": "already_disconnected",
            "message": f"{dev.name} is not currently connected.",
        }

    def unpair_device(self, user_id: int, target: str = "") -> dict[str, Any]:
        """Revoke and unpair a device from the user's account."""
        devices = self.registry.resolve_device(user_id, target)
        if not devices:
            return {
                "success": False,
                "status": "not_paired",
                "message": "No paired device found to remove.",
            }
        dev = devices[0]
        self.dispatcher.unregister_connection(dev.device_id)
        self.registry.revoke_device(user_id, dev.device_id)
        return {
            "success": True,
            "status": "unpaired",
            "message": f"Successfully removed and unpaired {dev.name}.",
        }

    def handle_command(self, user_input: str, user_id: int) -> dict[str, Any]:
        """Parse natural language command and execute the appropriate device skill."""
        text = user_input.lower().strip()

        # 1. Pairing (natural variations: pair phone, pair my phone, connect phone, connect my phone, connect to my phone, etc.)
        if re.search(r'\b(?:pair|connect)\s+(?:to\s+)?(?:(?:my|a|a\s+new)\s+)?(?:phone|device|mobile)\b', text):
            return self.pair_device(user_id)

        # 1b. Pairing code inquiry / repeat (what's the code again, repeat the pairing code, etc.)
        if (
            re.search(r'\b(?:what(?:\'s|\s+is|\s+was)?\s+(?:the\s+)?(?:(?:phone|device)\s+)?(?:pairing\s+)?code(?:\s+again)?|repeat\s+(?:the\s+)?(?:(?:phone|device)\s+)?(?:pairing\s+)?code|show\s+(?:the\s+)?(?:(?:phone|device)\s+)?(?:pairing\s+)?code)\b', text)
            or any(k in text for k in [
                "what's the code again", "whats the code again", "what was the pairing code",
                "repeat the pairing code", "what is the phone pairing code", "what is the pairing code",
                "repeat the code", "what is the code again", "what was the code", "pairing code again", "the code again"
            ])
        ):
            return self.get_active_pairing_code(user_id)

        # 1c. Disconnect
        if re.search(r'\bdisconnect\s+(?:from\s+)?(?:(?:my|a)\s+)?(?:phone|device|mobile)\b', text):
            target = ""
            m = re.search(r'disconnect\s+(?:from\s+)?(?:(?:my|a)\s+)?([a-z0-9\s]+?)$', text)
            if m and m.group(1).strip() not in ["phone", "device", "mobile"]:
                target = m.group(1).strip()
            return self.disconnect_device(user_id, target)

        # 1d. Unpair / Remove device
        if re.search(r'\b(?:unpair|remove|forget|delete)\s+(?:(?:my|a)\s+)?(?:phone|device|mobile)\b', text):
            target = ""
            m = re.search(r'(?:unpair|remove|forget|delete)\s+(?:(?:my|a)\s+)?([a-z0-9\s]+?)$', text)
            if m and m.group(1).strip() not in ["phone", "device", "mobile"]:
                target = m.group(1).strip()
            return self.unpair_device(user_id, target)

        # 2. Connection status (is my phone connected, is my phone online, phone connection status, show device status, etc.)
        if (
            re.search(r'\b(?:is\s+(?:my\s+)?(?:phone|device|mobile)\s+(?:connected|online)|(?:phone|device|mobile)\s+connection(?:\s+status)?|check\s+(?:my\s+)?(?:phone|device|mobile)\s+connection)\b', text)
            or re.search(r'\b(?:(?:show|get|check)\s+(?:my\s+)?(?:device|phone|mobile)\s+status|(?:device|phone|mobile)\s+status)\b', text)
        ):
            target = ""
            m = re.search(r'(?:is\s+(?:my\s+)?|for\s+(?:my\s+)?)([a-z0-9\s]+?)\s+(?:connected|online)', text)
            if m:
                target = m.group(1).strip()
            return self.get_connection_status(user_id, target)

        # 3. List devices
        if any(k in text for k in [
            "list devices", "list my devices", "list paired devices", "list my paired devices",
            "what devices are connected", "show my devices", "show paired devices", "paired devices",
            "show my connected devices", "show connected devices", "what devices are paired", "what devices are available"
        ]):
            return self.list_devices(user_id)

        # 4. Battery status
        if any(k in text for k in ["battery", "battery level", "phone battery", "charge level"]):
            target = ""
            m = re.search(r'(?:on|for)\s+(?:my\s+)?([a-z0-9\s]+?)(?:\'s)?\s*(?:battery)?$', text)
            if m:
                target = m.group(1).strip()
            return self.get_battery(user_id, target)

        # 5. Flashlight
        if "flashlight" in text or "torch" in text:
            enable = not any(w in text for w in ["off", "disable", "stop"])
            return self.toggle_flashlight(user_id, enable=enable)

        # 6. Launch app on phone
        m_app = re.search(r'(?:open|launch|start)\s+(.+?)\s+on\s+(?:my\s+)?phone', text)
        if m_app:
            app_name = m_app.group(1).strip()
            return self.launch_app(user_id, app_name)

        return {
            "success": False,
            "status": "unrecognized",
            "message": f"Could not understand device command: '{user_input}'. Try 'list my paired devices', 'pair my phone', 'is my phone connected', or 'what is my phone battery'.",
        }


_controller_instance: Optional[DeviceController] = None
_ctrl_lock = threading.Lock()


def get_device_controller() -> DeviceController:
    global _controller_instance
    with _ctrl_lock:
        if _controller_instance is None:
            _controller_instance = DeviceController()
        return _controller_instance

