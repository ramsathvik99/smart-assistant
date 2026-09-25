"""
Device Authentication and Cryptographic Utilities
Provides constant-time secret comparison, token generation, and secure hashing.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from uuid import uuid4


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_pairing_token() -> str:
    return secrets.token_urlsafe(32)


def generate_pairing_code() -> str:
    """Generate a human-friendly 6-digit numeric pairing code."""
    return f"{secrets.randbelow(900000) + 100000}"


def generate_device_secret() -> str:
    return secrets.token_hex(32)


def generate_device_id(platform: str = "android", name: str = "device") -> str:
    clean_platform = "".join(c for c in platform.lower() if c.isalnum()) or "device"
    clean_name = "".join(c for c in name.lower() if c.isalnum()) or "node"
    short_uuid = uuid4().hex[:8]
    return f"{clean_platform}_{clean_name}_{short_uuid}"


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
