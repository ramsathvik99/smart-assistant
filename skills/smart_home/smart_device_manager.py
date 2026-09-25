"""
Smart Device Context Manager
Tracks the user's active device in conversation to resolve context-dependent commands ("turn it off", "set speed to 3").
"""

from __future__ import annotations

import re
import threading
from typing import Any, Optional


class SmartDeviceManager:
    """Manages active device context per user."""

    def __init__(self):
        self._lock = threading.RLock()
        # user_id -> (device_id, device_name)
        self._active_devices: dict[int, tuple[Optional[str], Optional[str]]] = {}

    def set_active_device(self, user_id: int, device_id: Optional[str], device_name: Optional[str] = None):
        with self._lock:
            self._active_devices[user_id] = (device_id, device_name)

    def get_active_device(self, user_id: int) -> tuple[Optional[str], Optional[str]]:
        with self._lock:
            return self._active_devices.get(user_id, (None, None))

    def resolve_target_device_name(self, text: str, user_id: int, available_devices: list[dict[str, Any]]) -> str:
        """
        If text does not mention any specific device name, but an active device exists for this user,
        rewrites the target to the active device name.
        """
        with self._lock:
            _, active_name = self.get_active_device(user_id)

        if not active_name:
            return text

        normalized = re.sub(r"\s+", " ", text.lower()).strip()

        # Check if text mentions any known device name
        for d in available_devices:
            d_name = d.get("name", "").lower()
            if d_name and d_name in normalized:
                return text

        # Check for pronouns or bare actions
        if any(pronoun in normalized for pronoun in [" it", " that", " the device", " the light", " the fan"]):
            return re.sub(r"\b(it|that|the device)\b", active_name, text, flags=re.IGNORECASE)

        return text


_manager_instance: Optional[SmartDeviceManager] = None
_manager_lock = threading.Lock()


def get_smart_device_manager() -> SmartDeviceManager:
    global _manager_instance
    with _manager_lock:
        if _manager_instance is None:
            _manager_instance = SmartDeviceManager()
        return _manager_instance
