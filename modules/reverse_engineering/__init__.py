"""
Reverse Engineering & Inspection Module
Integrated REA runtime exposing binary diagnostics, PE inspection,
SQLite database analysis, Electron inspection, and MCP tool execution.
"""

from .mcp_client import ReaMcpClient
from .rea_service import ReaService, get_rea_service

__all__ = [
    "ReaMcpClient",
    "ReaService",
    "get_rea_service",
]
