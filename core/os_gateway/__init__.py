"""
Universal OS Operations and Computer Control Subsystem.
Provides a unified gateway for computer control across all accessible OS layers:
GUI, applications, files, drives, filesystem, terminal, shells, processes,
services, networking, configuration, Windows APIs, and system diagnostics.
"""

from core.os_gateway.action_history import OSActionHistoryManager, get_os_action_history
from core.os_gateway.context_resolver import OSContextResolver, get_context_resolver
from core.os_gateway.gateway import OSGateway, get_os_gateway
from core.os_gateway.operation_model import (
    OSCapability,
    OSExecutionMethod,
    OSOperation,
    OSOperationResult,
    OSOperationType,
    OSRiskLevel,
)
from core.os_gateway.shell_executor import ShellExecutor, get_shell_executor
from core.os_gateway.verifier import OSVerifier, get_os_verifier

__all__ = [
    "OSGateway",
    "get_os_gateway",
    "OSOperation",
    "OSOperationResult",
    "OSCapability",
    "OSOperationType",
    "OSRiskLevel",
    "OSExecutionMethod",
    "OSContextResolver",
    "get_context_resolver",
    "OSVerifier",
    "get_os_verifier",
    "OSActionHistoryManager",
    "get_os_action_history",
    "ShellExecutor",
    "get_shell_executor",
]
