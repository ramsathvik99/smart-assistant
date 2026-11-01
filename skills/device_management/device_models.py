"""
Device Models and Protocol Definitions
Defines standardized data models for remote device records, pairing offers, and protocol messages.
Extended with enrollment code, stable identity, auth token, location, and remote connection fields.
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
    enrollment_code: str = ""   # 16-char Crockford code for remote enrollment

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
            "enrollment_code": self.enrollment_code,
        }

    def to_qr_payload(self) -> dict[str, Any]:
        return {
            "type": "assistant_device_pairing",
            "version": "1.0",
            "offer_id": self.offer_id,
            "code": self.code,
            "token": self.token,
            "user_id": self.user_id,
            "enrollment_code": self.enrollment_code,
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

    # --- New fields for persistent enrollment and remote connectivity ---
    enrollment_code: str = ""           # 16-char Crockford code (XXXX-XXXX-XXXX-XXXX)
    stable_identity: str = ""           # SHA-256 of platform+name+hardware_seed
    auth_token_hash: str = ""           # SHA-256 of bearer token for remote sessions
    connection_mode: str = "local"      # "local" | "remote" | "offline"
    enrollment_state: str = "pending"   # "pending" | "enrolled" | "revoked"

    # Location data
    location: dict[str, Any] = field(default_factory=dict)
    location_history: list[dict[str, Any]] = field(default_factory=list)

    # Network / heartbeat info
    network_info: dict[str, Any] = field(default_factory=dict)

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
            # New fields
            "enrollment_code": self.enrollment_code,
            "stable_identity": self.stable_identity,
            "auth_token_hash": self.auth_token_hash,
            "connection_mode": self.connection_mode,
            "enrollment_state": self.enrollment_state,
            "location": dict(self.location),
            "location_history": list(self.location_history),
            "network_info": dict(self.network_info),
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
            # New fields
            enrollment_code=str(data.get("enrollment_code", "")),
            stable_identity=str(data.get("stable_identity", "")),
            auth_token_hash=str(data.get("auth_token_hash", "")),
            connection_mode=str(data.get("connection_mode", "local")),
            enrollment_state=str(data.get("enrollment_state", "pending")),
            location=dict(data.get("location") or {}),
            location_history=list(data.get("location_history") or []),
            network_info=dict(data.get("network_info") or {}),
        )
