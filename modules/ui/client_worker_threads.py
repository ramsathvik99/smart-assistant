"""
Smart Assistant — Thin Client QThread Workers
=============================================
Production desktop client workers that communicate via HTTPS REST API.
NO imports from legacy.*, backend.*, or any ML/database modules.
"""

import time
import math
import traceback
from PyQt6.QtCore import QThread, pyqtSignal, QObject


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND WORKER — calls API instead of legacy.assistant.process_input()
# ─────────────────────────────────────────────────────────────────────────────
class ClientCommandWorker(QObject):
    """Execute a text command via the production REST API."""
    started       = pyqtSignal(str)
    finished      = pyqtSignal(str, str)   # (command, response)
    error         = pyqtSignal(str, str)   # (command, error_message)
    state_changed = pyqtSignal(str)        # thinking / executing / idle / error

    def __init__(self):
        super().__init__()
        self._command = ""

    def set_command(self, text: str):
        self._command = text

    def run(self):
        cmd = self._command
        self.started.emit(cmd)
        self.state_changed.emit("thinking")
        try:
            from core.api_client import get_api_client
            client = get_api_client()
            result = client.execute_command(cmd)
            self.state_changed.emit("idle")
            if result.get("success"):
                response = result.get("response", result.get("message", "Done."))
            else:
                response = result.get("error", "An error occurred. Please try again.")
            self.finished.emit(cmd, response)
        except Exception as e:
            self.state_changed.emit("error")
            self.error.emit(cmd, str(e))
            traceback.print_exc()


class ClientCommandThread(QThread):
    """QThread wrapper for ClientCommandWorker."""
    started_sig = pyqtSignal(str)
    finished_sig = pyqtSignal(str, str)
    error_sig   = pyqtSignal(str, str)
    state_sig   = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._worker = ClientCommandWorker()
        self._worker.started.connect(self.started_sig)
        self._worker.finished.connect(self.finished_sig)
        self._worker.error.connect(self.error_sig)
        self._worker.state_changed.connect(self.state_sig)

    def execute(self, command: str) -> bool:
        if self.isRunning():
            return False
        self._worker.set_command(command)
        self.start()
        return True

    def run(self):
        self._worker.run()


# ─────────────────────────────────────────────────────────────────────────────
# HISTORY LOADER — loads chat history via API
# ─────────────────────────────────────────────────────────────────────────────
class ClientHistoryLoader(QThread):
    """Loads conversation history from the remote API."""
    history_ready = pyqtSignal(list)   # list of {role, content} dicts

    def __init__(self, conversation_id: str = None):
        super().__init__()
        self._conversation_id = conversation_id

    def run(self):
        try:
            from core.api_client import get_api_client
            client = get_api_client()
            endpoint = (
                f"/api/conversations/{self._conversation_id}/messages"
                if self._conversation_id
                else "/api/conversations/recent/messages"
            )
            result = client._request(endpoint)
            messages = result.get("messages", [])
            self.history_ready.emit(messages)
        except Exception as e:
            print(f"[HISTORY LOADER] Error: {e}")
            self.history_ready.emit([])


# ─────────────────────────────────────────────────────────────────────────────
# AUDIO LEVEL PROVIDER — synthetic animation (no local mic access needed)
# ─────────────────────────────────────────────────────────────────────────────
class ClientAudioLevelProvider(QThread):
    """Generates simulated audio energy for the visualizer animation."""
    level_changed = pyqtSignal(float)   # 0.0 – 1.0

    def __init__(self):
        super().__init__()
        self._running = False
        self._state = "idle"   # idle | listening | speaking

    def set_state(self, state: str):
        """Update animation state: 'idle', 'listening', 'speaking'."""
        self._state = state

    def run(self):
        self._running = True
        t = 0.0
        import random
        while self._running:
            try:
                if self._state == "speaking":
                    level = 0.35 + 0.25 * math.sin(t * 8) + random.uniform(-0.05, 0.05)
                elif self._state == "listening":
                    level = 0.08 + 0.04 * math.sin(t * 3) + random.uniform(-0.02, 0.02)
                else:
                    level = 0.02 + 0.01 * math.sin(t * 1)
                self.level_changed.emit(max(0.0, min(1.0, level)))
            except Exception:
                self.level_changed.emit(0.0)
            t += 0.04
            time.sleep(0.04)  # 25 fps

    def stop(self):
        self._running = False
        self.quit()
        self.wait(1000)


# ─────────────────────────────────────────────────────────────────────────────
# TTS STUB MONITOR — thin client uses system TTS (pyttsx3) if available
# ─────────────────────────────────────────────────────────────────────────────
class ClientTTSMonitor(QThread):
    """
    Thin-client TTS state monitor.
    If local pyttsx3 is available, tracks its state.
    Otherwise emits no signals (UI stays in idle animation).
    """
    speaking_started = pyqtSignal()
    speaking_stopped = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running = False
        self._was_speaking = False

    def run(self):
        self._running = True
        while self._running:
            try:
                # Try local pyttsx3 state if available
                import pyttsx3
                # pyttsx3 doesn't expose a global is_speaking state easily
                # so we rely on ClientAudioLevelProvider._state instead
                pass
            except ImportError:
                pass
            time.sleep(0.1)

    def stop(self):
        self._running = False
        self.quit()
        self.wait(500)


# ─────────────────────────────────────────────────────────────────────────────
# VAD STUB — thin client microphone recording (optional)
# ─────────────────────────────────────────────────────────────────────────────
class ClientVADMonitor(QThread):
    """
    Thin-client VAD stub.
    Full voice-activity detection happens on the server.
    This is a placeholder that keeps the UI consistent.
    """
    vad_active   = pyqtSignal()
    vad_inactive = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            time.sleep(0.2)

    def stop(self):
        self._running = False
        self.quit()
        self.wait(500)
