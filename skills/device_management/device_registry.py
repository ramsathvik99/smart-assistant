"""
Device Registry
Manages user-isolated, persistent records of paired devices with thread-safe operations.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

from .device_auth import generate_device_id, generate_device_secret, hash_secret, constant_time_equals
from .device_models import DeviceRecord, now_iso

logger = logging.getLogger(__name__)


class DeviceRegistry:
    """
    Centralized registry of paired mobile/remote devices.
    Enforces strict user isolation: User A cannot query or access User B's devices.
    """

    def __init__(self, base_storage_dir: Optional[str] = None):
        self._lock = threading.RLock()
        if base_storage_dir:
            self.storage_dir = Path(base_storage_dir)
        else:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.storage_dir = project_root / "data" / "devices"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # In-memory index: device_id -> DeviceRecord
        self._devices: dict[str, DeviceRecord] = {}
        self._load_all()

    def _user_file(self, user_id: int) -> Path:
        return self.storage_dir / f"user_{user_id}_devices.json"

    def _load_all(self) -> None:
        with self._lock:
            self._devices.clear()
            for path in self.storage_dir.glob("user_*_devices.json"):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    devs = raw.get("devices", {})
                    for d_id, d_data in devs.items():
                        self._devices[d_id] = DeviceRecord.from_dict(d_data)
                except Exception as e:
                    logger.warning(f"Failed to load device file {path}: {e}")

    def _save_user(self, user_id: int) -> None:
        with self._lock:
            user_devs = {
                d_id: rec.to_dict()
                for d_id, rec in self._devices.items()
                if rec.user_id == user_id
            }
            path = self._user_file(user_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"user_id": user_id, "devices": user_devs}, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )

    def list_devices(self, user_id: int) -> list[DeviceRecord]:
        """List all devices owned by the given user_id."""
        with self._lock:
            user_devs = [
                rec for rec in self._devices.values()
                if rec.user_id == user_id and not rec.revoked
            ]
            return sorted(user_devs, key=lambda d: (not d.online, d.name.lower()))

    def get_device(self, user_id: int, device_id: str) -> Optional[DeviceRecord]:
        """Get a specific device owned by user_id."""
        with self._lock:
            rec = self._devices.get(device_id)
            if rec and rec.user_id == user_id and not rec.revoked:
                return rec
            return None

    def register_device(
        self,
        user_id: int,
        name: str,
        platform: str = "android",
        os_version: str = "",
        agent_version: str = "",
        ip: str = "",
        battery: Optional[int] = None,
        charging: bool = False,
        capabilities: Optional[list[str]] = None,
        permissions: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[DeviceRecord, str]:
        """
        Register a newly paired device bound to user_id.
        Returns (DeviceRecord, plaintext_secret).
        """
        with self._lock:
            device_id = generate_device_id(platform, name)
            secret = generate_device_secret()
            record = DeviceRecord(
                device_id=device_id,
                user_id=user_id,
                name=name.strip() or "Mobile Device",
                platform=(platform or "android").lower(),
                os_version=os_version,
                agent_version=agent_version,
                ip=ip,
                online=True,
                battery=battery,
                charging=charging,
                capabilities=list(capabilities or [
                    "battery", "flashlight", "launch_app", "open_url", "volume"
                ]),
                permissions=list(permissions or []),
                paired_at=now_iso(),
                last_seen=now_iso(),
                secret_hash=hash_secret(secret),
                revoked=False,
                metadata=dict(metadata or {}),
            )
            self._devices[device_id] = record
            self._save_user(user_id)
            logger.info(f"Registered new device '{record.name}' ({device_id}) for user {user_id}")
            return record, secret

    def authenticate(self, device_id: str, secret: str, ip: str = "") -> Optional[DeviceRecord]:
        """Verify device secret and mark device online."""
        with self._lock:
            record = self._devices.get(device_id)
            if record is None or record.revoked:
                return None
            if not constant_time_equals(record.secret_hash, hash_secret(secret)):
                return None
            record.online = True
            record.last_seen = now_iso()
            if ip:
                record.ip = ip
            self._save_user(record.user_id)
            return record

    def update_status(
        self,
        device_id: str,
        online: Optional[bool] = None,
        battery: Optional[int] = None,
        charging: Optional[bool] = None,
        capabilities: Optional[list[str]] = None,
    ) -> Optional[DeviceRecord]:
        """Update runtime state of a device."""
        with self._lock:
            record = self._devices.get(device_id)
            if not record:
                return None
            if online is not None:
                record.online = online
            if battery is not None:
                record.battery = battery
            if charging is not None:
                record.charging = charging
            if capabilities is not None:
                record.capabilities = list(capabilities)
            record.last_seen = now_iso()
            self._save_user(record.user_id)
            return record

    def rename_device(self, user_id: int, device_id: str, new_name: str) -> Optional[DeviceRecord]:
        """Rename a device belonging to user_id."""
        with self._lock:
            record = self.get_device(user_id, device_id)
            if not record:
                return None
            clean_name = new_name.strip()
            if clean_name:
                record.name = clean_name
                self._save_user(user_id)
            return record

    def revoke_device(self, user_id: int, device_id: str) -> bool:
        """Revoke pairing for a device belonging to user_id."""
        with self._lock:
            record = self.get_device(user_id, device_id)
            if not record:
                return False
            record.revoked = True
            record.online = False
            record.last_seen = now_iso()
            self._save_user(user_id)
            logger.info(f"Revoked device {device_id} for user {user_id}")
            return True

    def resolve_device(self, user_id: int, query: str = "") -> list[DeviceRecord]:
        """
        Find devices matching query (by name or ID) for the given user_id.
        If query is empty, returns all active devices.
        """
        with self._lock:
            all_user_devs = self.list_devices(user_id)
            clean = query.lower().strip()
            if not clean or clean in ("phone", "my phone", "device", "mobile"):
                return all_user_devs
            
            # Exact match first
            exact = [d for d in all_user_devs if d.name.lower() == clean or d.device_id.lower() == clean]
            if exact:
                return exact
            # Partial match
            return [d for d in all_user_devs if clean in d.name.lower() or clean in d.device_id.lower()]


# Global singleton
_registry_instance: Optional[DeviceRegistry] = None
_registry_lock = threading.Lock()


def get_device_registry() -> DeviceRegistry:
    global _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            _registry_instance = DeviceRegistry()
        return _registry_instance
