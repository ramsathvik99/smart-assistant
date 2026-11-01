"""
Device Authentication and Cryptographic Utilities
Provides constant-time secret comparison, token generation, secure hashing,
enrollment code generation, stable identity derivation, and HMAC signing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from uuid import uuid4


# ---------------------------------------------------------------------------
# Crockford Base32 alphabet (human-friendly: no 0/O or I/L confusion)
# ---------------------------------------------------------------------------
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# Normalization map for common human typos when entering enrollment codes
_NORMALIZE_MAP = str.maketrans("OoIiLl", "000111")


def generate_enrollment_code() -> str:
    """
    Generate a 16-character Crockford Base32 enrollment code (~80 bits entropy).
    Format: XXXX-XXXX-XXXX-XXXX
    """
    random_bytes = secrets.token_bytes(10)  # 80 bits
    # Convert bytes to a 16-char Crockford Base32 string
    value = int.from_bytes(random_bytes, "big")
    chars = []
    for _ in range(16):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    raw = "".join(reversed(chars))
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"


def normalize_enrollment_code(raw: str) -> str:
    """
    Normalize a user-entered enrollment code:
    - Strip spaces and dashes
    - Uppercase
    - Replace common confusable characters (O→0, I/L→1)
    Returns the 16-char canonical form without dashes.
    """
    cleaned = raw.upper().replace("-", "").replace(" ", "")
    # Replace O with 0, I/L with 1 (Crockford convention)
    cleaned = cleaned.translate(_NORMALIZE_MAP)
    return cleaned


def generate_device_token() -> str:
    """Generate a 48-byte URL-safe bearer token for remote device sessions."""
    return secrets.token_urlsafe(48)


def generate_stable_identity(platform: str, name: str, hardware_seed: str) -> str:
    """
    Derive a stable SHA-256 device identity that does not change with IP,
    Wi-Fi SSID, SIM, or reboot.  hardware_seed should be Android ID +
    model fingerprint (never IMEI or MAC).
    """
    canonical = f"{platform.lower()}::{name.lower()}::{hardware_seed}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sign_payload(secret: str, payload_str: str) -> str:
    """HMAC-SHA256 signature over payload_str using secret. Returns hex digest."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(secret: str, payload_str: str, signature: str) -> bool:
    """Constant-time HMAC-SHA256 verification."""
    expected = sign_payload(secret, payload_str)
    return hmac.compare_digest(expected.encode("utf-8"), signature.encode("utf-8"))


# ---------------------------------------------------------------------------
# Legacy helpers (preserved for backward compatibility)
# ---------------------------------------------------------------------------

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
