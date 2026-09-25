"""
Device Management Configuration
Provides configurable network, pairing, and timeout settings for remote device connections.
"""

import os
from dataclasses import dataclass


@dataclass
class DeviceGatewayConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    enabled: bool = True
    advertise: bool = True
    service_name: str = "_ASSISTANT._tcp.local."
    pairing_ttl_seconds: int = 300
    request_timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "DeviceGatewayConfig":
        return cls(
            host=os.getenv("DEVICE_GATEWAY_HOST", "0.0.0.0"),
            port=int(os.getenv("DEVICE_GATEWAY_PORT", "8765")),
            enabled=os.getenv("DEVICE_GATEWAY_ENABLED", "true").lower() in ("1", "true", "yes"),
            advertise=os.getenv("DEVICE_GATEWAY_ADVERTISE", "true").lower() in ("1", "true", "yes"),
            service_name=os.getenv("DEVICE_GATEWAY_SERVICE", "_ASSISTANT._tcp.local."),
            pairing_ttl_seconds=int(os.getenv("DEVICE_PAIRING_TTL", "300")),
            request_timeout_seconds=int(os.getenv("DEVICE_REQUEST_TIMEOUT", "30")),
        )
