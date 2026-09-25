"""
Smart Home Base Provider
Abstract base class for all smart home hardware and cloud integrations.
"""

from __future__ import annotations

from typing import Any
from ..models import ProviderField


class SmartHomeProvider:
    key = "base"
    name = "Base Provider"
    manufacturer = "Generic"
    available = True
    coming_soon = False

    def auth_fields(self) -> list[ProviderField]:
        return []

    def authenticate(self, credentials: dict[str, Any]) -> dict[str, Any]:
        return {"account_label": self.name, "credentials": credentials}

    def discover_devices(self, credentials: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def disconnect(self, credentials: dict[str, Any]) -> bool:
        return True

    def execute(self, device: dict[str, Any], action: str, payload: dict[str, Any]) -> dict[str, Any]:
        traits = dict(device.get("traits") or {})
        traits.update(payload)
        is_on = bool(payload.get("is_on", device.get("is_on", False)))
        if action == "power":
            is_on = bool(payload.get("is_on"))
            return {"is_on": is_on, "traits": traits, "detail": f"{device.get('name', 'Device')} power set to {is_on}."}
        return {"is_on": is_on, "traits": traits, "detail": f"{device.get('name', 'Device')} updated."}

    def get_status(self, device: dict[str, Any]) -> dict[str, Any]:
        return {"online": True, "detail": f"{device.get('name', 'Device')} is online and reachable."}
