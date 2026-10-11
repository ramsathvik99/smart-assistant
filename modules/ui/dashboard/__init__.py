"""
Dashboard Package — Next-Gen AI Assistant Control Center
Integrates with existing backend services without modification.
"""

__all__ = ["DashboardMainWindow"]


def __getattr__(name):
    if name == "DashboardMainWindow":
        from .main_window import DashboardMainWindow
        return DashboardMainWindow
    raise AttributeError(f"module 'modules.ui.dashboard' has no attribute {name!r}")
