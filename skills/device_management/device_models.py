"""
Device Models and Protocol Definitions
Defines standardized data models for remote device records, pairing offers, and protocol messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


class ProtocolTypes:
    HELLO = "hello"
    PAIR_REQUEST = "pair_request"
    PAIR_APPROVED = "pair_approved"
    PAIR_REJECTED = "pair_rejected"
    AUTHENTICATE = "authenticate"
    DEVICE_ONLINE = "device_online"
    DEVICE_OFFLINE = "device_offline"
    CAPABILITIES = "capabilities"
    EXECUTE = "execute"
    RESULT = "result"
    EVENT = "event"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"
    FILE_TRANSFER = "file_transfer"
    SCREEN_CAPTURE = "screen_capture"
    CHAT_MESSAGE = "chat_message"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_request_id() -> str:
    return uuid4().hex


def build_message(
    message_type: str,
    payload: Optional[dict] = None,
    request_id: Optional[str] = None,
    timestamp: Optional[str] = None
) -> dict:
    return {
        "type": message_type,
        "request_id": request_id or new_request_id(),
        "timestamp": timestamp or now_iso(),
        "payload": payload or {},
    }


def validate_message(message: dict) -> tuple[bool, str]:
    if not isinstance(message, dict):
        return False, "Message must be a JSON object."
    for key in ("type", "request_id", "timestamp"):
        if not str(message.get(key, "")).strip():
            return False, f"Missing required field: {key}"
    return True, ""


@dataclass
class PairingOffer:
    offer_id: str
    code: str
    token: str
    user_id: int
    expires_at: str
    gateway_host: str
    gateway_port: int
    created_at: str = field(default_factory=now_iso)
    approved: bool = False
    device_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "code": self.code,
            "token": self.token,
            "user_id": self.user_id,
            "expires_at": self.expires_at,
            "gateway_host": self.gateway_host,
            "gateway_port": self.gateway_port,
            "created_at": self.created_at,
            "approved": self.approved,
            "device_id": self.device_id,
        }

    def to_qr_payload(self) -> dict[str, Any]:
        return {
            "type": "assistant_device_pairing",
            "version": "1.0",
            "offer_id": self.offer_id,
            "code": self.code,
            "token": self.token,
            "user_id": self.user_id,
            "gateway": {
                "host": self.gateway_host,
                "port": self.gateway_port,
            },
            "expires_at": self.expires_at,
        }


@dataclass
class DeviceRecord:
    device_id: str
    user_id: int
    name: str
    platform: str = "android"
    os_version: str = ""
    agent_version: str = ""
    ip: str = ""
    online: bool = False
    battery: Optional[int] = None
    charging: bool = False
    capabilities: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    paired_at: str = field(default_factory=now_iso)
    last_seen: str = field(default_factory=now_iso)
    secret_hash: str = ""
    revoked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "user_id": self.user_id,
            "name": self.name,
            "platform": self.platform,
            "os_version": self.os_version,
            "agent_version": self.agent_version,
            "ip": self.ip,
            "online": self.online,
            "battery": self.battery,
            "charging": self.charging,
            "capabilities": list(self.capabilities),
            "permissions": list(self.permissions),
            "paired_at": self.paired_at,
            "last_seen": self.last_seen,
            "secret_hash": self.secret_hash,
            "revoked": self.revoked,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceRecord":
        return cls(
            device_id=str(data.get("device_id", "")),
            user_id=int(data.get("user_id", 1)),
            name=str(data.get("name", "Unknown Device")),
            platform=str(data.get("platform", "android")),
            os_version=str(data.get("os_version", "")),
            agent_version=str(data.get("agent_version", "")),
            ip=str(data.get("ip", "")),
            online=bool(data.get("online", False)),
            battery=data.get("battery"),
            charging=bool(data.get("charging", False)),
            capabilities=list(data.get("capabilities", [])),
            permissions=list(data.get("permissions", [])),
            paired_at=str(data.get("paired_at", now_iso())),
            last_seen=str(data.get("last_seen", now_iso())),
            secret_hash=str(data.get("secret_hash", "")),
            revoked=bool(data.get("revoked", False)),
            metadata=dict(data.get("metadata", {})),
        )
