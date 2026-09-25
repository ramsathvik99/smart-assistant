"""
Smart Home Models
Defines device data structures, traits, and provider field models with user isolation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class ProviderField:
    key: str
    label: str
    placeholder: str = ""
    secret: bool = False


@dataclass
class SmartDevice:
    device_id: str
    user_id: int
    provider_key: str
    external_id: str
    name: str
    manufacturer: str
    room: str
    device_type: str  # "light", "plug", "switch", "fan", "ac", "thermostat", "sensor", "generic"
    image_key: str
    is_on: bool = False
    traits: dict[str, Any] = field(default_factory=dict)
    online: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "user_id": self.user_id,
            "provider_key": self.provider_key,
            "external_id": self.external_id,
            "name": self.name,
            "manufacturer": self.manufacturer,
            "room": self.room,
            "device_type": self.device_type,
            "image_key": self.image_key,
            "is_on": self.is_on,
            "traits": dict(self.traits),
            "online": self.online,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SmartDevice:
        return cls(
            device_id=data.get("device_id") or data.get("id", ""),
            user_id=int(data.get("user_id", 1)),
            provider_key=data.get("provider_key", "base"),
            external_id=str(data.get("external_id", "")),
            name=data.get("name", "Smart Device"),
            manufacturer=data.get("manufacturer", "Generic"),
            room=data.get("room", "Living Room"),
            device_type=data.get("device_type", "generic"),
            image_key=data.get("image_key", "device"),
            is_on=bool(data.get("is_on", False)),
            traits=dict(data.get("traits") or {}),
            online=bool(data.get("online", True)),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )
