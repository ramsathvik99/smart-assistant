"""
Remote Device Command Dispatcher
Dispatches structured RPC commands to paired remote mobile devices over active connections.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable, Optional

from .device_models import DeviceRecord, ProtocolTypes, build_message, new_request_id
from .device_registry import DeviceRegistry, get_device_registry

logger = logging.getLogger(__name__)


class RemoteDeviceDispatcher:
    """
    Handles RPC dispatch to connected devices.
    Enforces user isolation, device online validation, and capability checks.
    """

    def __init__(self, registry: Optional[DeviceRegistry] = None):
        self.registry = registry or get_device_registry()
        self._lock = threading.RLock()
        # In-memory connection channels: device_id -> dict with send callback and pending futures
        self._connections: dict[str, dict[str, Any]] = {}
        self._pending_requests: dict[str, asyncio.Future] = {}

    def register_connection(self, device_id: str, send_callback: Callable[[dict], Any]) -> None:
        """Register an active connection handler for a device."""
        with self._lock:
            self._connections[device_id] = {
                "send": send_callback,
                "connected_at": asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0,
            }
            logger.info(f"Registered connection for device {device_id}")

    def unregister_connection(self, device_id: str) -> None:
        """Remove an active connection when a device disconnects."""
        with self._lock:
            self._connections.pop(device_id, None)
            logger.info(f"Unregistered connection for device {device_id}")

    def is_connected(self, device_id: str) -> bool:
        with self._lock:
            return device_id in self._connections

    def handle_device_result(self, request_id: str, result_payload: dict[str, Any]) -> bool:
        """Fulfill pending future when response arrives from device."""
        with self._lock:
            future = self._pending_requests.pop(request_id, None)
            if future and not future.done():
                future.set_result(result_payload)
                return True
            return False

    async def dispatch_command_async(
        self,
        user_id: int,
        target_query: str,
        action: str,
        parameters: Optional[dict[str, Any]] = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """
        Asynchronously send a command to a user's paired device and await the response.
        """
        parameters = dict(parameters or {})
        matches = self.registry.resolve_device(user_id, target_query)

        if not matches:
            return {
                "success": False,
                "status": "not_paired",
                "device": target_query,
                "action": action,
                "message": f"No paired device found matching '{target_query or 'phone'}'. Say 'pair phone' to connect a device.",
                "error_code": "DEVICE_NOT_FOUND",
            }

        if len(matches) > 1:
            device_names = ", ".join([d.name for d in matches])
            return {
                "success": False,
                "status": "multiple_devices",
                "device": target_query,
                "action": action,
                "message": f"Multiple devices matched ({device_names}). Please specify which one.",
                "error_code": "MULTIPLE_DEVICES",
                "matches": [d.to_dict() for d in matches],
            }

        device = matches[0]

        if device.revoked:
            return {
                "success": False,
                "status": "revoked",
                "device": device.name,
                "action": action,
                "message": f"Device '{device.name}' pairing has been revoked.",
                "error_code": "DEVICE_REVOKED",
            }

        if not device.online or not self.is_connected(device.device_id):
            return {
                "success": False,
                "status": "offline",
                "device": device.name,
                "action": action,
                "message": f"Your {device.name} is currently offline. Please open the Assistant Connect app on your phone.",
                "error_code": "DEVICE_OFFLINE",
            }

        # Check capabilities
        req_cap = parameters.pop("required_capability", None)
        if req_cap and req_cap not in device.capabilities:
            return {
                "success": False,
                "status": "unsupported",
                "device": device.name,
                "action": action,
                "message": f"Your {device.name} does not support {req_cap}.",
                "error_code": "CAPABILITY_MISSING",
            }

        # Build message and send
        request_id = new_request_id()
        msg = build_message(
            ProtocolTypes.EXECUTE,
            payload={"device_id": device.device_id, "action": action, "parameters": parameters},
            request_id=request_id
        )

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        with self._lock:
            self._pending_requests[request_id] = future
            conn = self._connections.get(device.device_id)

        if not conn or not conn.get("send"):
            with self._lock:
                self._pending_requests.pop(request_id, None)
            return {
                "success": False,
                "status": "disconnected",
                "device": device.name,
                "action": action,
                "message": f"Connection lost to {device.name}.",
                "error_code": "CONNECTION_LOST",
            }

        try:
            conn["send"](msg)
            result = await asyncio.wait_for(future, timeout=timeout)
            return {
                "success": True,
                "status": "success",
                "device": device.name,
                "action": action,
                "data": result,
                "message": f"Command executed successfully on {device.name}.",
            }
        except asyncio.TimeoutError:
            with self._lock:
                self._pending_requests.pop(request_id, None)
            return {
                "success": False,
                "status": "timeout",
                "device": device.name,
                "action": action,
                "message": f"Timed out waiting for response from {device.name}.",
                "error_code": "TIMEOUT",
            }
        except Exception as e:
            with self._lock:
                self._pending_requests.pop(request_id, None)
            return {
                "success": False,
                "status": "error",
                "device": device.name,
                "action": action,
                "message": f"Failed to communicate with {device.name}: {e}",
                "error_code": "DISPATCH_ERROR",
            }

    def dispatch_command_sync(
        self,
        user_id: int,
        target_query: str,
        action: str,
        parameters: Optional[dict[str, Any]] = None,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Synchronous wrapper for dispatching commands in threaded environments."""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    fut = executor.submit(
                        asyncio.run,
                        self.dispatch_command_async(user_id, target_query, action, parameters, timeout)
                    )
                    return fut.result(timeout=timeout + 1.0)
            else:
                return asyncio.run(
                    self.dispatch_command_async(user_id, target_query, action, parameters, timeout)
                )
        except Exception as e:
            logger.error(f"Sync dispatch error: {e}")
            matches = self.registry.resolve_device(user_id, target_query)
            if not matches:
                return {
                    "success": False,
                    "status": "not_paired",
                    "message": f"No paired device found matching '{target_query or 'phone'}'. Say 'pair phone' to connect a device."
                }
            return {
                "success": False,
                "status": "offline",
                "message": f"Your {matches[0].name} is currently offline."
            }


_dispatcher_instance: Optional[RemoteDeviceDispatcher] = None
_disp_lock = threading.Lock()


def get_device_dispatcher() -> RemoteDeviceDispatcher:
    global _dispatcher_instance
    with _disp_lock:
        if _dispatcher_instance is None:
            _dispatcher_instance = RemoteDeviceDispatcher()
        return _dispatcher_instance
