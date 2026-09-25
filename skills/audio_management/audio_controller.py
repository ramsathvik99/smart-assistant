"""
Audio Management Controller
Provides conversational commands for enumerating audio inputs/outputs, switching devices, and testing sound effects.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .audio_devices import list_devices, resolve, switch_output_device, DEFAULT_LABEL
from .sound_effects import get_sound_manager


class AudioController:
    def __init__(self):
        self.sound_mgr = get_sound_manager()

    def list_audio_endpoints(self) -> dict[str, Any]:
        inputs = list_devices("input")
        outputs = list_devices("output")

        in_str = ", ".join(inputs) if inputs else "System default"
        out_str = ", ".join(outputs) if outputs else "System default"

        msg = f"Audio Endpoints:\n• Microphones: {in_str}\n• Speakers/Headphones: {out_str}"
        return {
            "success": True,
            "inputs": inputs,
            "outputs": outputs,
            "message": msg
        }

    def switch_audio_device(self, target_device: str, kind: str = "output") -> dict[str, Any]:
        """Switch default audio endpoint or report OS availability."""
        return switch_output_device(target_device)

    def play_sound(self, sound_name: str) -> dict[str, Any]:
        res = self.sound_mgr.play(sound_name)
        if res:
            return {"success": True, "sound": sound_name, "message": f"Played sound '{sound_name}'."}
        return {"success": False, "sound": sound_name, "message": f"Sound '{sound_name}' not found."}

    def handle_command(self, user_input: str) -> dict[str, Any]:
        text_low = user_input.lower().strip()

        # Device Switching
        switch_match = re.search(r'\b(?:switch|change|set)\s+(?:audio\s+)?(?:output|playback|speakers?|device)?\s*(?:to\s+)?(.+)', text_low)
        if switch_match and not any(w in text_low for w in ["show", "list"]):
            target = switch_match.group(1).strip()
            # Clean common trailing words
            target = re.sub(r'\b(?:as\s+(?:output|playback|speakers?)|please)\b', '', target).strip()
            if target and target not in ("devices", "audio devices", "endpoints", "microphones", "speakers"):
                return self.switch_audio_device(target)

        use_as_match = re.search(r'\b(?:use|set)\s+(.+?)\s+as\s+(?:audio\s+)?(?:output|playback|speakers?)\b', text_low)
        if use_as_match:
            return self.switch_audio_device(use_as_match.group(1).strip())

        # Audio Endpoints Listing
        if any(w in text_low for w in ["show audio devices", "list audio devices", "show microphones", "list microphones", "show speakers", "list speakers", "audio devices"]):
            return self.list_audio_endpoints()

        # Procedural Sound Effects
        if any(w in text_low for w in ["play sound", "play chime", "play whoosh", "play chirp", "play ping", "play click", "play beep", "notification sound", "play audio chime"]):
            if "chirp" in text_low:
                return self.play_sound("telemetry_chirp")
            elif "whoosh" in text_low:
                return self.play_sound("deploy_whoosh")
            elif "ping" in text_low or "sonar" in text_low:
                return self.play_sound("sonar_ping")
            elif "click" in text_low:
                return self.play_sound("quantum_click")
            elif "beep" in text_low:
                return self.play_sound("power_hum")
            elif "alert" in text_low or "warn" in text_low:
                return self.play_sound("shield_alert")
            else:
                return self.play_sound("mission_complete")

        return self.list_audio_endpoints()


_controller_instance: Optional[AudioController] = None


def get_audio_controller() -> AudioController:
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = AudioController()
    return _controller_instance
