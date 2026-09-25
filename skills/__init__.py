"""
Native Assistant Skills Package
Provides specialized capabilities integrated into the assistant architecture.
"""

from . import device_management
from . import task_management
from . import smart_home
from . import audio_management
from . import window_management
from . import learning
from . import undo
from . import device_location
from . import clipboard

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
]
