"""
Device Discovery Beacon
Broadcasts UDP discovery beacons on the local network so mobile devices can locate the assistant.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Determine the host's primary local LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually connect; determines route
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class DeviceDiscoveryBeacon:
    """
    Periodic UDP broadcaster advertising assistant gateway presence to local LAN.
    """

    def __init__(
        self,
        port: int = 8765,
        broadcast_port: int = 8766,
        service_name: str = "SmartAssistantGateway",
        interval_seconds: float = 3.0,
    ):
        self.port = port
        self.broadcast_port = broadcast_port
        self.service_name = service_name
        self.interval_seconds = interval_seconds
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._broadcast_loop,
            daemon=True,
            name="DeviceDiscoveryBeacon"
        )
        self._thread.start()
        logger.info(f"Device discovery beacon started on port {self.broadcast_port}")

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("Device discovery beacon stopped")

    def _broadcast_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.5)

        while self._running:
            try:
                ip = get_local_ip()
                payload = json.dumps({
                    "service": self.service_name,
                    "host": ip,
                    "port": self.port,
                    "timestamp": time.time(),
                }).encode("utf-8")

                sock.sendto(payload, ("<broadcast>", self.broadcast_port))
            except Exception as e:
                logger.debug(f"Discovery beacon broadcast error: {e}")

            time.sleep(self.interval_seconds)

        sock.close()


_beacon_instance: Optional[DeviceDiscoveryBeacon] = None
_beacon_lock = threading.Lock()


def get_discovery_beacon(port: int = 8765) -> DeviceDiscoveryBeacon:
    global _beacon_instance
    with _beacon_lock:
        if _beacon_instance is None:
            _beacon_instance = DeviceDiscoveryBeacon(port=port)
        return _beacon_instance
