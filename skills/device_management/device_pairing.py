"""
Device Pairing Manager
Coordinates pairing handshakes between mobile devices and the assistant using 6-digit PINs or QR codes.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from uuid import uuid4

from .device_auth import generate_pairing_code, generate_pairing_token
from .device_models import DeviceRecord, PairingOffer, now_iso
from .device_registry import DeviceRegistry, get_device_registry

logger = logging.getLogger(__name__)


class DevicePairingManager:
    """
    Manages active pairing sessions.
    Generates pairing offers (with 6-digit PIN and QR payload) with TTL expiration.
    """

    def __init__(self, registry: Optional[DeviceRegistry] = None):
        self.registry = registry or get_device_registry()
        self._lock = threading.RLock()
        self._offers: dict[str, PairingOffer] = {}  # offer_id -> PairingOffer
        self._code_index: dict[str, str] = {}      # code -> offer_id
        self._token_index: dict[str, str] = {}     # token -> offer_id

    def _prune(self) -> None:
        """Remove expired pairing offers."""
        now = datetime.now(timezone.utc)
        with self._lock:
            expired_ids = []
            for offer_id, offer in self._offers.items():
                try:
                    exp = datetime.fromisoformat(offer.expires_at)
                    if exp < now:
                        expired_ids.append(offer_id)
                except Exception:
                    expired_ids.append(offer_id)

            for o_id in expired_ids:
                offer = self._offers.pop(o_id, None)
                if offer:
                    self._code_index.pop(offer.code, None)
                    self._token_index.pop(offer.token, None)

    def create_offer(
        self,
        user_id: int,
        gateway_host: str = "0.0.0.0",
        gateway_port: int = 8765,
        ttl_seconds: int = 300,
    ) -> PairingOffer:
        """Create a new pairing offer with a 6-digit code and QR payload."""
        with self._lock:
            self._prune()
            offer_id = uuid4().hex[:12]
            code = generate_pairing_code()
            token = generate_pairing_token()
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()

            offer = PairingOffer(
                offer_id=offer_id,
                code=code,
                token=token,
                user_id=user_id,
                expires_at=expires_at,
                gateway_host=gateway_host,
                gateway_port=gateway_port,
            )
            self._offers[offer_id] = offer
            self._code_index[code] = offer_id
            self._token_index[token] = offer_id
            logger.info(f"Created pairing offer {offer_id} with code {code} for user {user_id}")
            return offer

    def get_offer_by_code(self, code: str) -> Optional[PairingOffer]:
        with self._lock:
            self._prune()
            offer_id = self._code_index.get(code.strip())
            return self._offers.get(offer_id) if offer_id else None

    def get_offer_by_token(self, token: str) -> Optional[PairingOffer]:
        with self._lock:
            self._prune()
            offer_id = self._token_index.get(token.strip())
            return self._offers.get(offer_id) if offer_id else None

    def get_active_offer_for_user(self, user_id: int) -> Optional[PairingOffer]:
        """Get the current active, unexpired, unapproved pairing offer for user if one exists."""
        now = datetime.now(timezone.utc)
        with self._lock:
            self._prune()
            for offer in self._offers.values():
                if offer.user_id == user_id and not offer.approved:
                    try:
                        exp = datetime.fromisoformat(offer.expires_at)
                        if exp > now:
                            return offer
                    except Exception:
                        continue
            return None

    def approve_pairing(
        self,
        offer_id: str,
        device_name: str,
        platform: str = "android",
        os_version: str = "",
        agent_version: str = "",
        ip: str = "",
        battery: Optional[int] = None,
        capabilities: Optional[list[str]] = None,
        permissions: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[Optional[DeviceRecord], Optional[str]]:
        """
        Approve pairing and register device in registry.
        Returns (DeviceRecord, plaintext_secret) or (None, None) if invalid offer.
        """
        with self._lock:
            self._prune()
            offer = self._offers.get(offer_id)
            if not offer:
                return None, None

            record, secret = self.registry.register_device(
                user_id=offer.user_id,
                name=device_name,
                platform=platform,
                os_version=os_version,
                agent_version=agent_version,
                ip=ip,
                battery=battery,
                capabilities=capabilities,
                permissions=permissions,
                metadata=metadata,
            )

            offer.approved = True
            offer.device_id = record.device_id

            # Clean up used offer
            self._offers.pop(offer_id, None)
            self._code_index.pop(offer.code, None)
            self._token_index.pop(offer.token, None)

            return record, secret

    def cancel_offer(self, offer_id: str) -> bool:
        with self._lock:
            offer = self._offers.pop(offer_id, None)
            if offer:
                self._code_index.pop(offer.code, None)
                self._token_index.pop(offer.token, None)
                return True
            return False


_pairing_manager_instance: Optional[DevicePairingManager] = None
_pm_lock = threading.Lock()


def get_pairing_manager() -> DevicePairingManager:
    global _pairing_manager_instance
    with _pm_lock:
        if _pairing_manager_instance is None:
            _pairing_manager_instance = DevicePairingManager()
        return _pairing_manager_instance
