"""
Undo Skill Controller
Provides conversational commands for reversing actions and checking undo history.
"""

from __future__ import annotations

from typing import Any, Optional
from .undo_manager import UndoManager, get_undo_manager


class UndoController:
    def __init__(self, manager: Optional[UndoManager] = None):
        self.manager = manager or get_undo_manager()

    def handle_command(self, user_input: str, user_id: int) -> dict[str, Any]:
        text_low = user_input.lower().strip()

        if any(w in text_low for w in [
            "what can i undo", "undo history", "show undo",
            "action that can be undone", "action that can be undo",
            "undoable", "last undoable action",
            "what is my last action", "what was my last action"
        ]):
            last = self.manager.peek(user_id)
            if not last:
                return {
                    "success": True,
                    "status": "empty",
                    "history": [],
                    "message": "Your undo stack is currently empty."
                }
            if any(w in text_low for w in ["last action", "undoable", "last undoable action"]):
                return {
                    "success": True,
                    "status": "success",
                    "last_action": last,
                    "message": f"Your last undoable action is: {last}."
                }
            history = self.manager.history(user_id)
            lines = [f"{i+1}. {item}" for i, item in enumerate(history)]
            return {
                "success": True,
                "status": "success",
                "history": history,
                "message": f"Recent reversible action(s):\n• " + "\n• ".join(lines)
            }

        return self.manager.undo_last(user_id)


_controller_instance: Optional[UndoController] = None


def get_undo_controller() -> UndoController:
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = UndoController()
    return _controller_instance
