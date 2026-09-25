"""
Smart Home Storage & Credential Vault
Provides user-isolated persistence for smart home accounts and connected devices.
Enforces multi-tenant security: User A cannot see or manipulate User B's devices.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet
from .models import SmartDevice

logger = logging.getLogger(__name__)


class CredentialVault:
    """Safely encrypts and decrypts provider credentials per user."""

    def __init__(self, key_path: Optional[Path] = None):
        if key_path:
            self._key_path = Path(key_path)
        else:
            project_root = Path(__file__).resolve().parent.parent.parent
            self._key_path = project_root / "data" / "smart_home" / "vault.key"
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self._key_path.write_bytes(key)
        return key

    def encrypt_json(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        return self._fernet.encrypt(raw).decode("utf-8")

    def decrypt_json(self, payload: str | None) -> dict[str, Any]:
        if not payload:
            return {}
        try:
            data = self._fernet.decrypt(payload.encode("utf-8"))
            obj = json.loads(data.decode("utf-8"))
            return obj if isinstance(obj, dict) else {}
        except Exception as e:
            logger.warning(f"Failed to decrypt credential payload: {e}")
            return {}


class SmartHomeStorage:
    """
    User-isolated smart home storage repository.
    Persists data in data/smart_home/user_{user_id}_devices.json.
    """

    def __init__(self, storage_dir: Optional[str] = None):
        self._lock = threading.RLock()
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.storage_dir = project_root / "data" / "smart_home"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.vault = CredentialVault(self.storage_dir / "vault.key")
        # In-memory index: device_id -> SmartDevice
        self._devices: dict[str, SmartDevice] = {}
        # In-memory accounts: account_id -> dict
        self._accounts: dict[str, dict[str, Any]] = {}
        self._load_all()

    def _user_file(self, user_id: int) -> Path:
        return self.storage_dir / f"user_{int(user_id)}_devices.json"

    def _load_all(self) -> None:
        with self._lock:
            self._devices.clear()
            self._accounts.clear()
            for path in self.storage_dir.glob("user_*_devices.json"):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    u_id = int(raw.get("user_id", 1))
                    for d_id, d_data in raw.get("devices", {}).items():
                        d_data["user_id"] = u_id
                        self._devices[d_id] = SmartDevice.from_dict(d_data)
                    for a_id, a_data in raw.get("accounts", {}).items():
                        a_data["user_id"] = u_id
                        self._accounts[a_id] = a_data
                except Exception as e:
                    logger.warning(f"Failed to load smart home file {path}: {e}")

    def _save_user(self, user_id: int) -> None:
        with self._lock:
            user_devs = {
                d_id: dev.to_dict()
                for d_id, dev in self._devices.items()
                if dev.user_id == user_id
            }
            user_accs = {
                a_id: acc
                for a_id, acc in self._accounts.items()
                if acc.get("user_id") == user_id
            }
            path = self._user_file(user_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "user_id": user_id,
                "accounts": user_accs,
                "devices": user_devs,
                "updated_at": time.time(),
            }
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def save_provider_account(
        self,
        user_id: int,
        provider_key: str,
        account_label: str,
        credentials: dict[str, Any]
    ) -> str:
        with self._lock:
            account_id = f"acc_{uuid.uuid4().hex[:8]}"
            enc_creds = self.vault.encrypt_json(credentials)
            self._accounts[account_id] = {
                "id": account_id,
                "user_id": user_id,
                "provider_key": provider_key,
                "account_label": account_label,
                "credentials_encrypted": enc_creds,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self._save_user(user_id)
            return account_id

    def get_provider_account(self, user_id: int, account_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            acc = self._accounts.get(account_id)
            if not acc or acc.get("user_id") != user_id:
                return None
            creds = self.vault.decrypt_json(acc.get("credentials_encrypted"))
            res = dict(acc)
            res["credentials"] = creds
            return res

    def list_devices(self, user_id: int) -> list[SmartDevice]:
        with self._lock:
            return [d for d in self._devices.values() if d.user_id == user_id]

    def get_device(self, user_id: int, device_id: str) -> Optional[SmartDevice]:
        with self._lock:
            dev = self._devices.get(device_id)
            if dev and dev.user_id == user_id:
                return dev
            # Try matching by name or external_id
            for d in self._devices.values():
                if d.user_id == user_id and (d.name.lower() == device_id.lower() or d.external_id == device_id):
                    return d
            return None

    def save_devices(
        self,
        user_id: int,
        provider_key: str,
        devices_data: list[dict[str, Any]]
    ) -> list[SmartDevice]:
        saved = []
        with self._lock:
            for item in devices_data:
                dev_id = item.get("device_id") or f"{provider_key}_{uuid.uuid4().hex[:6]}"
                ext_id = str(item.get("external_id") or dev_id)
                # Check existing
                existing = None
                for d in self._devices.values():
                    if d.user_id == user_id and d.provider_key == provider_key and d.external_id == ext_id:
                        existing = d
                        break

                if existing:
                    existing.name = item.get("name", existing.name)
                    existing.room = item.get("room", existing.room)
                    existing.is_on = bool(item.get("is_on", existing.is_on))
                    existing.traits.update(item.get("traits") or {})
                    existing.updated_at = time.time()
                    saved.append(existing)
                else:
                    new_dev = SmartDevice(
                        device_id=dev_id,
                        user_id=user_id,
                        provider_key=provider_key,
                        external_id=ext_id,
                        name=item.get("name", "Smart Device"),
                        manufacturer=item.get("manufacturer", provider_key.title()),
                        room=item.get("room", "Living Room"),
                        device_type=item.get("device_type", "generic"),
                        image_key=item.get("image_key", item.get("device_type", "device")),
                        is_on=bool(item.get("is_on", False)),
                        traits=dict(item.get("traits") or {}),
                    )
                    self._devices[dev_id] = new_dev
                    saved.append(new_dev)

            self._save_user(user_id)
        return saved

    def update_device_state(
        self,
        user_id: int,
        device_id: str,
        is_on: Optional[bool] = None,
        traits: Optional[dict[str, Any]] = None,
    ) -> Optional[SmartDevice]:
        with self._lock:
            dev = self.get_device(user_id, device_id)
            if not dev:
                return None
            if is_on is not None:
                dev.is_on = bool(is_on)
            if traits:
                dev.traits.update(traits)
            dev.updated_at = time.time()
            self._save_user(user_id)
            return dev

    def delete_device(self, user_id: int, device_id: str) -> bool:
        with self._lock:
            dev = self.get_device(user_id, device_id)
            if not dev:
                return False
            self._devices.pop(dev.device_id, None)
            self._save_user(user_id)
            return True


_storage_instance: Optional[SmartHomeStorage] = None
_storage_lock = threading.Lock()


def get_smart_home_storage() -> SmartHomeStorage:
    global _storage_instance
    with _storage_lock:
        if _storage_instance is None:
            _storage_instance = SmartHomeStorage()
        return _storage_instance
