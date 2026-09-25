"""
Clipboard Skill Controller
Provides conversational commands for inspecting and analyzing clipboard technical content.
"""

from __future__ import annotations

from typing import Any
from .clipboard_analyzer import analyze_clipboard


class ClipboardController:
    def handle_command(self, user_input: str) -> dict[str, Any]:
        return analyze_clipboard()


_controller_instance: Optional[ClipboardController] = None


def get_clipboard_controller() -> ClipboardController:
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = ClipboardController()
    return _controller_instance
