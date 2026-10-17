"""
Smart Assistant — QThread Worker Objects
All long-running backend operations run here, never on the Qt GUI thread.
"""

import traceback
from PyQt6.QtCore import QThread, pyqtSignal, QObject


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND WORKER
# Calls legacy.assistant.process_input() off the GUI thread.
# ─────────────────────────────────────────────────────────────────────────────
class CommandWorker(QObject):
    """Execute a text command in the background."""
    started    = pyqtSignal(str)     # emits the command text
    finished   = pyqtSignal(str, str)  # (command, response)
    error      = pyqtSignal(str, str)  # (command, error_message)
    state_changed = pyqtSignal(str)  # emits state name: thinking / executing / idle

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
            from legacy.assistant import process_input
            response = process_input(cmd)
            self.state_changed.emit("idle")
            self.finished.emit(cmd, response or "")
        except Exception as e:
            self.state_changed.emit("error")
            self.error.emit(cmd, str(e))
            traceback.print_exc()


class CommandThread(QThread):
    """QThread wrapper that runs CommandWorker."""
    started_sig    = pyqtSignal(str)
    finished_sig   = pyqtSignal(str, str)
    error_sig      = pyqtSignal(str, str)
    state_sig      = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._worker = CommandWorker()
        self._worker.started.connect(self.started_sig)
        self._worker.finished.connect(self.finished_sig)
        self._worker.error.connect(self.error_sig)
        self._worker.state_changed.connect(self.state_sig)

    def execute(self, command: str):
        if self.isRunning():
            return False
        self._worker.set_command(command)
        self.start()
        return True

    def run(self):
        self._worker.run()


# ─────────────────────────────────────────────────────────────────────────────
# TTS STATE MONITOR
# Polls legacy.tts.is_speaking() and emits signals when state changes.
# Runs continuously in background.
# ─────────────────────────────────────────────────────────────────────────────
class TTSMonitor(QThread):
    """Emits speaking_started / speaking_stopped based on TTS state."""
    speaking_started = pyqtSignal()
    speaking_stopped = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running = False
        self._was_speaking = False

    def run(self):
        import time
        try:
            from legacy.tts import is_speaking
        except Exception:
            def is_speaking():
                return False

        self._running = True
        while self._running:
            try:
                now_speaking = is_speaking()
                if now_speaking and not self._was_speaking:
                    self.speaking_started.emit()
                elif not now_speaking and self._was_speaking:
                    self.speaking_stopped.emit()
                self._was_speaking = now_speaking
            except Exception:
                pass
            time.sleep(0.08)

    def stop(self):
        self._running = False
        self.quit()
        self.wait(1000)


# ─────────────────────────────────────────────────────────────────────────────
# VAD STATE MONITOR
# Watches for SST activity by sampling TTS + process state changes.
# ─────────────────────────────────────────────────────────────────────────────
class VADMonitor(QThread):
    """Emits signals reflecting genuine microphone VAD and voice lifecycle state."""
    vad_active    = pyqtSignal()          # genuine speech detected
    vad_inactive  = pyqtSignal()          # back to silence
    state_changed = pyqtSignal(str, str)  # (state, message)

    def __init__(self):
        super().__init__()
        self._running = False

    def run(self):
        import time
        from core.voice_lifecycle import get_voice_lifecycle
        vl = get_voice_lifecycle()

        self._running = True
        prev_is_listening = False
        prev_state = ""
        while self._running:
            try:
                curr_state = vl.get_state()
                msg = vl.get_status_message()
                is_listening = (curr_state == "listening")

                if is_listening and not prev_is_listening:
                    self.vad_active.emit()
                elif not is_listening and prev_is_listening:
                    self.vad_inactive.emit()
                prev_is_listening = is_listening

                if curr_state != prev_state:
                    self.state_changed.emit(curr_state, msg)
                    prev_state = curr_state

            except Exception:
                pass
            time.sleep(0.04)

    def stop(self):
        self._running = False
        self.quit()
        self.wait(1000)


# ─────────────────────────────────────────────────────────────────────────────
# AUDIO LEVEL PROVIDER
# Exposes genuine microphone energy levels and voice activity.
# ─────────────────────────────────────────────────────────────────────────────
class AudioLevelProvider(QThread):
    """Provides genuine audio energy levels for visualizer and listening ring animation."""
    level_changed = pyqtSignal(float)   # 0.0 – 1.0

    def __init__(self):
        super().__init__()
        self._running = False

    def run(self):
        import time, math
        from core.voice_lifecycle import get_voice_lifecycle
        vl = get_voice_lifecycle()

        self._running = True
        t = 0.0
        while self._running:
            try:
                st = vl.get_state()
                if st == "listening":
                    # Real microphone energy from VAD loop
                    raw_lvl = vl.get_audio_level()
                    # Add subtle baseline presence so listening ring is visible even during quiet phonemes
                    level = max(0.12, raw_lvl)
                elif st == "speaking":
                    # Organic speech rhythm pulse during assistant playback
                    level = 0.30 + 0.20 * math.sin(t * 8)
                else:
                    level = 0.0

                self.level_changed.emit(max(0.0, min(1.0, float(level))))
            except Exception:
                self.level_changed.emit(0.0)

            t += 0.04
            time.sleep(0.04)  # 25 fps

    def stop(self):
        self._running = False
        self.quit()
        self.wait(1000)


# ─────────────────────────────────────────────────────────────────────────────
# HISTORY LOADER
# Loads chat history from DB in background.
# ─────────────────────────────────────────────────────────────────────────────
class HistoryLoader(QThread):
    history_ready = pyqtSignal(list)  # list of {role, content} dicts

    def __init__(self, user_id):
        super().__init__()
        self._user_id = user_id

    def run(self):
        try:
            from legacy.memory_manager import get_chat_history
            history = get_chat_history(self._user_id, limit=50)
            self.history_ready.emit(history)
        except Exception as e:
            print(f"[HISTORY LOADER] Error: {e}")
            self.history_ready.emit([])
