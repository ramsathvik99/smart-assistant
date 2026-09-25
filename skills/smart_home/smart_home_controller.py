"""
Smart Home Conversational Controller
Parses natural language smart home commands and dispatches to SmartHomeService with active device tracking.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .service import SmartHomeService, get_smart_home_service
from .smart_device_manager import SmartDeviceManager, get_smart_device_manager


class SmartHomeController:
    def __init__(
        self,
        service: Optional[SmartHomeService] = None,
        context_mgr: Optional[SmartDeviceManager] = None
    ):
        self.service = service or get_smart_home_service()
        self.context_mgr = context_mgr or get_smart_device_manager()

    def handle_command(self, user_input: str, user_id: int) -> dict[str, Any]:
        text = user_input.strip()
        text_low = text.lower()

        devices = self.service.list_devices(user_id)
        dev_dicts = [d.to_dict() for d in devices]

        # Resolve context pronouns (e.g. "turn it off" -> "turn Living Room Light off")
        resolved_text = self.context_mgr.resolve_target_device_name(text, user_id, dev_dicts)
        resolved_low = resolved_text.lower()

        # 1. Discovery / Platforms
        if any(w in resolved_low for w in ["discover smart devices", "find smart devices", "scan smart devices", "search for smart devices"]):
            discovered_all = []
            for p in ["atomberg", "kasa", "hue", "daikin", "tuya"]:
                found = self.service.discover_devices(user_id, p)
                discovered_all.extend(found)
            count = len(discovered_all)
            return {
                "success": True,
                "status": "discovery_complete",
                "count": count,
                "devices": discovered_all,
                "message": f"Discovery complete. Found and registered {count} smart device(s)."
            }

        # 2. List devices
        if any(w in resolved_low for w in ["show my smart devices", "list smart devices", "show smart devices", "what smart devices", "smart home devices", "smart devices"]):
            if not devices:
                return {
                    "success": True,
                    "status": "no_devices",
                    "devices": [],
                    "message": "You don't have any smart home devices connected yet. Say 'discover smart devices' to find nearby devices."
                }
            lines = [f"{d.name} ({d.room}) - {'ON' if d.is_on else 'OFF'}" for d in devices]
            return {
                "success": True,
                "status": "success",
                "devices": [d.to_dict() for d in devices],
                "message": f"You have {len(devices)} smart device(s): {', '.join(lines)}."
            }

        # 3. Status check
        if any(w in resolved_low for w in ["status of", "is the", "how is the", "check the"]):
            m = re.search(r"(?:status of|check (?:the )?|is (?:the )?)(.+?)(?:\s+on|\s+off|\s+working|\?|$)", resolved_low)
            if m:
                target = m.group(1).strip()
                res = self.service.get_status(user_id, target)
                if res.get("success"):
                    dev = self.service.get_device(user_id, target)
                    if dev:
                        self.context_mgr.set_active_device(user_id, dev.device_id, dev.name)
                return res

        # 4. Power commands (turn on / off / toggle)
        m_on = re.search(r"(?:turn|switch|power)\s+on\s+(?:the\s+)?(.+)", resolved_low) or \
               re.search(r"(?:turn|switch|power)\s+(?:the\s+)?(.+?)\s+on\b", resolved_low)
        if m_on:
            target = m_on.group(1).strip()
            res = self.service.set_power(user_id, target, True)
            if res.get("success"):
                dev = self.service.get_device(user_id, target)
                if dev:
                    self.context_mgr.set_active_device(user_id, dev.device_id, dev.name)
            return res

        m_off = re.search(r"(?:turn|switch|power)\s+off\s+(?:the\s+)?(.+)", resolved_low) or \
                re.search(r"(?:turn|switch|power)\s+(?:the\s+)?(.+?)\s+off\b", resolved_low)
        if m_off:
            target = m_off.group(1).strip()
            res = self.service.set_power(user_id, target, False)
            if res.get("success"):
                dev = self.service.get_device(user_id, target)
                if dev:
                    self.context_mgr.set_active_device(user_id, dev.device_id, dev.name)
            return res

        # 5. Trait commands (speed, temperature, brightness)
        m_speed = re.search(r"set\s+(?:the\s+)?(.+?)\s+speed\s+to\s+(\d+)", resolved_low)
        if m_speed:
            target = m_speed.group(1).strip()
            val = int(m_speed.group(2))
            res = self.service.set_trait(user_id, target, "speed", val)
            return res

        m_temp = re.search(r"set\s+(?:the\s+)?(.+?)\s+(?:temperature|temp)\s+to\s+(\d+)", resolved_low)
        if m_temp:
            target = m_temp.group(1).strip()
            val = int(m_temp.group(2))
            res = self.service.set_trait(user_id, target, "temperature", val)
            return res

        m_bright = re.search(r"set\s+(?:the\s+)?(.+?)\s+brightness\s+to\s+(\d+)", resolved_low)
        if m_bright:
            target = m_bright.group(1).strip()
            val = int(m_bright.group(2))
            res = self.service.set_trait(user_id, target, "brightness", val)
            return res

        # Fallback to listing devices
        return self.handle_command("show smart devices", user_id)


_controller_instance: Optional[SmartHomeController] = None


def get_smart_home_controller() -> SmartHomeController:
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = SmartHomeController()
    return _controller_instance
