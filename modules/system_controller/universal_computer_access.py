"""
Universal Computer Access bridge module for system_controller.
Provides canonical backward-compatible access to core.universal_computer_access.
"""

from core.universal_computer_access import (
    UniversalComputerAccess,
    get_universal_computer_access,
    get_computer_access
)

universal_computer_access = get_universal_computer_access()

__all__ = [
    "UniversalComputerAccess",
    "get_universal_computer_access",
    "get_computer_access",
    "universal_computer_access",
]
