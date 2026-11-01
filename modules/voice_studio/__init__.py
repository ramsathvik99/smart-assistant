"""
VoiceStudio Integration Module for Friday
Provides studio-grade speech processing, neural TTS mastering, and Whisper ASR
extracted from VoiceStudio.
"""

from .voice_studio_bridge import (
    VoiceStudioBridge,
    get_voice_studio_bridge,
    VoiceStudioTTSBackend,
)

__all__ = [
    "VoiceStudioBridge",
    "get_voice_studio_bridge",
    "VoiceStudioTTSBackend",
]
