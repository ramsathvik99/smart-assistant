"""
Remote Device Command Dispatcher
Dispatches structured RPC commands to paired remote mobile devices over active connections.
Extended with long-polling command queue and sync waiter for cross-network remote control.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Optional
from uuid import uuid4

from .device_models import DeviceRecord, ProtocolTypes, build_message, new_request_id
from .device_registry import DeviceRegistry, get_device_registry

logger = logging.getLogger(__name__)

# Command queue TTL in seconds (how long an un-polled command stays valid)
_COMMAND_TTL = 60


class RemoteDeviceDispatcher:
    """
    Handles RPC dispatch to connected devices.
    Enforces user isolation, device online validation, and capability checks.

    Two dispatch paths:
    1. WebSocket/callback (local direct connection) — existing dispatch_command_async
    2. Long-poll queue (cross-network via Cloudflare tunnel) — enqueue_remote_command / poll_commands
    """

    def __init__(self, registry: Optional[DeviceRegistry] = None):
        self.registry = registry or get_device_registry()
        self._lock = threading.RLock()
        # In-memory connection channels: device_id -> dict with send callback and pending futures
        self._connections: dict[str, dict[str, Any]] = {}
        self._pending_requests: dict[str, asyncio.Future] = {}

        # Long-poll queue: device_id -> list of {"request_id", "action", "parameters", "expires_at"}
        self._command_queues: dict[str, list[dict[str, Any]]] = {}

        # Sync waiters for dispatch_remote_sync: request_id -> {"event": threading.Event, "result": Any}
        self._sync_waiters: dict[str, dict[str, Any]] = {}

        # Completed results cache: request_id -> {"result": Any, "completed_at": float}
        self._completed_results: dict[str, dict[str, Any]] = {}

        # Request to device mapping for authorization binding
        self._request_device_map: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Existing WebSocket/callback connection management
    # ------------------------------------------------------------------

    def register_connection(self, device_id: str, send_callback: Callable[[dict], Any]) -> None:
        """Register an active connection handler for a device."""
        with self._lock:
            try:
                loop = asyncio.get_running_loop()
                conn_time = loop.time()
            except RuntimeError:
                conn_time = time.time()
            self._connections[device_id] = {
                "send": send_callback,
                "connected_at": conn_time,
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

    def submit_command_result(self, request_id: str, result_payload: dict[str, Any], device_id: Optional[str] = None) -> bool:
        """
        Fulfill pending result for request_id.
        Verifies device binding if device_id is provided.
        Handles asyncio futures (WebSocket path), threading.Events (sync remote path),
        and records in _completed_results cache.
        """
        with self._lock:
            # Device binding check: ensure only the assigned device can submit results
            expected_dev = self._request_device_map.get(request_id)
            if expected_dev and device_id and expected_dev != device_id:
                logger.warning(f"Device mismatch submitting result for {request_id}: expected {expected_dev}, got {device_id}")
                return False

            self._completed_results[request_id] = {
                "result": result_payload,
                "completed_at": time.time(),
                "device_id": device_id or expected_dev or "",
            }
            if len(self._completed_results) > 100:
                oldest = sorted(self._completed_results.keys(), key=lambda k: self._completed_results[k]["completed_at"])[0]
                self._completed_results.pop(oldest, None)
                self._request_device_map.pop(oldest, None)

            # Try asyncio future first
            future = self._pending_requests.pop(request_id, None)
            if future and not future.done():
                try:
                    future.set_result(result_payload)
                except Exception:
                    pass
                return True

            # Try sync waiter
            waiter = self._sync_waiters.get(request_id)
            if waiter:
                waiter["result"] = result_payload
                waiter["event"].set()
                return True

            return True

    def get_command_result(self, request_id: str) -> Optional[dict[str, Any]]:
        """Retrieve recorded result for a completed command."""
        with self._lock:
            item = self._completed_results.get(request_id)
            return item["result"] if item else None

    # Backward-compatible alias
    def handle_device_result(self, request_id: str, result_payload: dict[str, Any]) -> bool:
        return self.submit_command_result(request_id, result_payload)

    # ------------------------------------------------------------------
    # Long-poll command queue (for cross-network remote path)
    # ------------------------------------------------------------------

    def enqueue_remote_command(
        self,
        device_id: str,
        action: str,
        parameters: Optional[dict[str, Any]] = None,
        ttl_seconds: int = _COMMAND_TTL,
    ) -> str:
        """
        Queue a command for a device that polls via GET /api/devices/commands.
        Returns the request_id for result correlation.
        """
        request_id = new_request_id()
        entry = {
            "request_id": request_id,
            "action": action,
            "parameters": dict(parameters or {}),
            "expires_at": time.time() + ttl_seconds,
            "queued_at": time.time(),
        }
        with self._lock:
            self._request_device_map[request_id] = device_id
            if device_id not in self._command_queues:
                self._command_queues[device_id] = []
            self._command_queues[device_id].append(entry)
        logger.debug(f"Enqueued remote command {request_id} ({action}) for device {device_id}")
        return request_id

    def poll_commands(self, device_id: str) -> list[dict[str, Any]]:
        """
        Called by GET /api/devices/commands endpoint.
        Returns all unexpired commands for the device and clears the queue.
        """
        now = time.time()
        with self._lock:
            queue = self._command_queues.pop(device_id, [])
        # Filter expired commands
        valid = [cmd for cmd in queue if cmd.get("expires_at", 0) > now]
        return valid

    def dispatch_remote_sync(
        self,
        device_id: str,
        action: str,
        parameters: Optional[dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """
        Enqueue a command for the long-poll path and block until the device posts a result.
        Used when the device is on a remote network and only reachable via the companion gateway.
        """
        request_id = self.enqueue_remote_command(device_id, action, parameters)

        event = threading.Event()
        waiter: dict[str, Any] = {"event": event, "result": None}
        with self._lock:
            self._sync_waiters[request_id] = waiter

        completed = event.wait(timeout=timeout)

        with self._lock:
            self._sync_waiters.pop(request_id, None)

        if not completed:
            return {
                "success": False,
                "status": "timeout",
                "device": device_id,
                "action": action,
                "message": f"Remote device did not respond within {timeout:.0f}s.",
                "error_code": "TIMEOUT",
            }

        result = waiter.get("result") or {}
        return {
            "success": True,
            "status": "success",
            "device": device_id,
            "action": action,
            "data": result,
            "message": "Remote command executed successfully.",
        }

    # ------------------------------------------------------------------
    # Async dispatch (WebSocket / local path)
    # ------------------------------------------------------------------

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
