"""
Audio Management Skill Package
"""

from .audio_devices import list_devices, resolve, configure, prefetch, DEFAULT_LABEL
from .echo_guard import EchoGuard
from .hotkey import PushToTalk, DEFAULT_CHORD, chord_label, set_ptt_enabled, toggle_ptt, is_ptt_enabled
from .sound_effects import SoundManager, get_sound_manager
from .audio_controller import AudioController, get_audio_controller

__all__ = [
    "list_devices",
    "resolve",
    "configure",
    "prefetch",
    "DEFAULT_LABEL",
    "EchoGuard",
    "PushToTalk",
    "DEFAULT_CHORD",
    "chord_label",
    "set_ptt_enabled",
    "toggle_ptt",
    "is_ptt_enabled",
    "SoundManager",
    "get_sound_manager",
    "AudioController",
    "get_audio_controller",
]
