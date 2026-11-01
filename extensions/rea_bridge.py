"""
REA Bridge (Compatibility Adapter)
Delegates to the canonical modules.reverse_engineering subsystem.
Maintains backward compatibility for existing callers and tests.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from modules.reverse_engineering import get_rea_service, ReaService, ReaMcpClient


class ReaMcpBridge:
    """Compatibility wrapper around ReaService / ReaMcpClient."""

    def __init__(self):
        self._service = get_rea_service()

    @property
    def client(self) -> ReaMcpClient:
        return self._service.client

    def is_running(self) -> bool:
        return self.client.is_running()

    def start(self) -> bool:
        return self.client.start()

    def stop(self) -> None:
        self.client.stop()

    def list_tools(self) -> List[Dict[str, Any]]:
        return self.client.list_tools()

    def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        return self.client.get_tool(name)

    def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        return self.client.call_tool(name, arguments, timeout)

    def get_status(self) -> Dict[str, Any]:
        return self.client.get_status()

    def check_adb_status(self) -> Dict[str, Any]:
        client_res = self.call_tool("inspect_adb_client")
        devices_res = self.call_tool("list_adb_devices")
        return {
            "client_check": client_res,
            "devices_check": devices_res,
        }


_bridge_instance: Optional[ReaMcpBridge] = None


def get_rea_bridge() -> ReaMcpBridge:
    """Returns the backward-compatible ReaMcpBridge singleton."""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = ReaMcpBridge()
    return _bridge_instance


def execute_rea_intent(user_input: str, user_id: int = 1) -> Dict[str, Any]:
    """Routes natural language REA command to ReaService."""
    return get_rea_service().handle_command(user_input, user_id)
