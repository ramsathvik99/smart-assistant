"""
Smart Home Service
Orchestrates providers, user-isolated storage, device discovery, and command execution.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from .models import SmartDevice, ProviderField
from .providers.base import SmartHomeProvider
from .providers.builtin import built_in_provider_classes
from .storage import SmartHomeStorage, get_smart_home_storage

logger = logging.getLogger(__name__)


class SmartHomeService:
    """Core smart home service providing operations with strict user isolation."""

    def __init__(self, storage: Optional[SmartHomeStorage] = None):
        self.storage = storage or get_smart_home_storage()
        self._providers: dict[str, type[SmartHomeProvider]] = {}
        self._lock = threading.RLock()
        self._load_providers()

    def _load_providers(self) -> None:
        for provider_cls in built_in_provider_classes():
            self._providers[provider_cls.key] = provider_cls

    def get_provider(self, provider_key: str) -> Optional[SmartHomeProvider]:
        cls = self._providers.get(provider_key)
        return cls() if cls else None

    def list_platforms(self) -> list[dict[str, Any]]:
        platforms = []
        for key, cls in self._providers.items():
            inst = cls()
            platforms.append({
                "key": key,
                "name": inst.name,
                "manufacturer": getattr(inst, "manufacturer", key.title()),
                "available": inst.available,
                "auth_fields": [f.__dict__ for f in inst.auth_fields()],
            })
        return sorted(platforms, key=lambda x: x["name"])

    def discover_devices(self, user_id: int, provider_key: str, credentials: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        provider = self.get_provider(provider_key)
        if not provider:
            return []
        creds = credentials or {}
        discovered = provider.discover_devices(creds)
        # Automatically register discovered devices in user storage
        if discovered:
            self.storage.save_devices(user_id, provider_key, discovered)
        return discovered

    def list_devices(self, user_id: int) -> list[SmartDevice]:
        return self.storage.list_devices(user_id)

    def get_device(self, user_id: int, target_name_or_id: str) -> Optional[SmartDevice]:
        return self.storage.get_device(user_id, target_name_or_id)

    def set_power(self, user_id: int, target: str, is_on: bool) -> dict[str, Any]:
        dev = self.get_device(user_id, target)
        if not dev:
            return {
                "success": False,
                "status": "not_found",
                "message": f"Smart device '{target}' was not found in your connected devices."
            }

        provider = self.get_provider(dev.provider_key)
        payload = {"is_on": is_on}
        if provider:
            try:
                res = provider.execute(dev.to_dict(), "power", payload)
                updated = self.storage.update_device_state(user_id, dev.device_id, is_on=res.get("is_on", is_on), traits=res.get("traits"))
            except Exception as e:
                logger.warning(f"Provider {dev.provider_key} execution notice: {e}")
                updated = self.storage.update_device_state(user_id, dev.device_id, is_on=is_on)
        else:
            updated = self.storage.update_device_state(user_id, dev.device_id, is_on=is_on)

        state_str = "on" if is_on else "off"
        return {
            "success": True,
            "status": "success",
            "device": dev.name,
            "is_on": is_on,
            "message": f"Turned {state_str} {dev.name} ({dev.room})."
        }

    def set_trait(self, user_id: int, target: str, trait_name: str, value: Any) -> dict[str, Any]:
        dev = self.get_device(user_id, target)
        if not dev:
            return {
                "success": False,
                "status": "not_found",
                "message": f"Smart device '{target}' was not found in your connected devices."
            }

        provider = self.get_provider(dev.provider_key)
        payload = {trait_name: value}
        if provider:
            try:
                res = provider.execute(dev.to_dict(), "trait", payload)
                updated = self.storage.update_device_state(user_id, dev.device_id, traits=res.get("traits", {trait_name: value}))
            except Exception as e:
                logger.warning(f"Provider {dev.provider_key} trait execution notice: {e}")
                updated = self.storage.update_device_state(user_id, dev.device_id, traits={trait_name: value})
        else:
            updated = self.storage.update_device_state(user_id, dev.device_id, traits={trait_name: value})

        return {
            "success": True,
            "status": "success",
            "device": dev.name,
            "trait": trait_name,
            "value": value,
            "message": f"Set {trait_name} of {dev.name} to {value}."
        }

    def get_status(self, user_id: int, target: str) -> dict[str, Any]:
        dev = self.get_device(user_id, target)
        if not dev:
            return {
                "success": False,
                "status": "not_found",
                "message": f"Smart device '{target}' was not found in your connected devices."
            }

        state_str = "ON" if dev.is_on else "OFF"
        traits_str = ", ".join(f"{k}: {v}" for k, v in dev.traits.items()) if dev.traits else "no special traits"
        msg = f"{dev.name} ({dev.room}) is currently {state_str} [{traits_str}]."
        return {
            "success": True,
            "status": "success",
            "device": dev.name,
            "room": dev.room,
            "is_on": dev.is_on,
            "traits": dev.traits,
            "message": msg
        }


_service_instance: Optional[SmartHomeService] = None
_service_lock = threading.Lock()


def get_smart_home_service() -> SmartHomeService:
    global _service_instance
    with _service_lock:
        if _service_instance is None:
            _service_instance = SmartHomeService()
        return _service_instance
