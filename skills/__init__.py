"""
Native Assistant Skills Package
Provides specialized capabilities integrated into the assistant architecture.
"""

import importlib

__all__ = [
    "device_management",
    "task_management",
    "smart_home",
    "audio_management",
    "window_management",
    "learning",
    "undo",
    "device_location",
    "clipboard",
    "clock_manager",
]

def __getattr__(name: str):
    if name in __all__:
        module = importlib.import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

def __dir__():
    return __all__
