"""
Smart Assistant — Thin Client Application Coordinator
======================================================
Production .exe desktop client coordinator.

Architecture:
    ClientApp
        ├── LoginWindow         → API login (core.api_client)
        ├── FloatingLauncher    → always-on-top orb
        ├── DashboardMainWindow → main dashboard interface
        ├── SystemTrayIcon
        ├── ClientCommandThread → API-backed command execution
        ├── ClientAudioLevelProvider
        └── ClientHistoryLoader

Communication: PyQt6 UI → core.api_client → HTTPS → Production API

IMPORTANT: This module must NEVER import from:
    - legacy.*  /  extensions.*
    - core.db_pool  /  core.migration_runner
    - psycopg2 / pgvector
    - torch / tensorflow / scipy / pandas / sklearn
"""

import sys
import os
import threading
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QObject
from PyQt6.QtGui import QIcon, QPixmap, QColor, QPainter, QBrush, QRadialGradient

from modules.ui.design_system import C, F, APP_STYLESHEET
from modules.ui.login_window import LoginWindow
from modules.ui.floating_launcher import FloatingLauncher
from modules.ui.dashboard.main_window import DashboardMainWindow
from modules.ui.notification_toast import ToastManager
from modules.ui.client_worker_threads import (
    ClientCommandThread,
    ClientAudioLevelProvider,
    ClientHistoryLoader,
    ClientTTSMonitor,
    ClientVADMonitor,
)


def _make_tray_icon() -> QIcon:
    """Generate a colored orb icon for the system tray."""
    px = QPixmap(32, 32)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QRadialGradient(14, 12, 10, 16, 16)
    grad.setColorAt(0.0, QColor(0, 212, 255, 255))
    grad.setColorAt(1.0, QColor(0, 100, 160, 200))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawEllipse(4, 4, 24, 24)
    p.end()
    return QIcon(px)


class ClientApp(QObject):
    """
    Thin-client application coordinator.
    Manages the lifecycle of UI components and API communication.
    """

    def __init__(self, app: QApplication):
        super().__init__()
        self._app = app
        self._app.setStyle("Fusion")
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setApplicationDisplayName("Trevon Labs")
        self._app.setStyleSheet(APP_STYLESHEET)

        # Load window icon
        icon_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "legacy", "icon.ico"
        )
        if os.path.exists(icon_path):
            self._app.setWindowIcon(QIcon(icon_path))

        # Components (initialized after login)
        self._launcher:   FloatingLauncher          | None = None
        self._win:        DashboardMainWindow       | None = None
        self._tray:       QSystemTrayIcon           | None = None
        self._toasts:     ToastManager              = ToastManager()

        # Worker threads (thin client — API backed)
        self._cmd_thread: ClientCommandThread       | None = None
        self._audio_prov: ClientAudioLevelProvider  | None = None
        self._tts_mon:    ClientTTSMonitor          | None = None
        self._vad_mon:    ClientVADMonitor          | None = None

        # Session state
        self._user_id:        int | None = None
        self._username:       str | None = None
        self._assistant_name: str = "Trevon"

    # ── Public entry point ───────────────────────────────────────────────────

    def start(self):
        """Show login window and start the Qt event loop."""
        self._show_login()

    # ── Login ────────────────────────────────────────────────────────────────

    def _show_login(self):
        self._login_win = LoginWindow()
        self._login_win.login_complete.connect(self._on_login_complete)
        self._login_win.show()

    @pyqtSlot(object, str, str)
    def _on_login_complete(self, user_id, username: str, session_mode: str = "account"):
        """Called by LoginWindow after successful authentication."""
        self._user_id  = int(user_id)
        self._username = username or "user"
        print(f"[CLIENT APP] Login complete: {username} (ID: {self._user_id})")

        # Configure the global API client session
        try:
            from core.api_client import get_api_client
            self._api_client = get_api_client()
        except Exception as e:
            print(f"[CLIENT APP] API client init error: {e}")

        # Fetch assistant name from API
        self._fetch_assistant_name()

        # Build UI
        self._build_ui()

        # Load chat history from API
        self._load_history()

        # Start background workers
        self._start_workers()

        # Greet user
        self._greet_user()

    def _fetch_assistant_name(self):
        """Fetch per-user assistant name from API (optional, falls back to 'Trevon')."""
        try:
            from core.api_client import get_api_client
            client = get_api_client()
            result = client.get_user_profile()
            if result.get("success"):
                profile = result.get("user", {})
                name = profile.get("assistant_name") or profile.get("name")
                if name:
                    self._assistant_name = name
        except Exception as e:
            print(f"[CLIENT APP] Could not fetch assistant name: {e}")

    # ── UI Construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        """Create all UI components after login."""
        # ── Floating launcher orb ──
        self._launcher = FloatingLauncher()
        self._launcher.set_user_context(self._username, self._assistant_name)
        self._launcher.single_clicked.connect(self._toggle_main_window)
        self._launcher.action_requested.connect(self._handle_launcher_action)

        # ── Main window (NEW DASHBOARD) ──
        self._win = DashboardMainWindow()
        self._win.set_assistant_name(self._assistant_name)
        if self._username:
            self._win.set_user_name(self._username)
        self._win.command_submitted.connect(self._on_command_submitted)
        self._win.logout_requested.connect(self._on_logout)
        self._win.assistant_name_changed.connect(self._on_assistant_name_updated)
        self._win.accent_changed.connect(self._on_accent_changed)
        self._win.minimized.connect(lambda: self._launcher.set_state("idle"))

        # ── System tray ──
        self._build_tray()

    def _build_tray(self):
        """Set up system tray icon and menu."""
        self._tray = QSystemTrayIcon(_make_tray_icon(), self._app)
        tray_menu = QMenu()
        tray_menu.addAction(
            f"Open {self._assistant_name}",
            lambda: self._win.show_animated() if self._win else None
        )
        tray_menu.addSeparator()
        tray_menu.addAction("Quit", self._app.quit)
        self._tray.setContextMenu(tray_menu)
        self._tray.setToolTip(f"Smart Assistant — {self._assistant_name}")
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_main_window()

    def _toggle_main_window(self):
        """Show or hide the main window."""
        if self._win:
            if self._win.isVisible():
                self._win.hide()
            else:
                self._win.show_animated()

    def _handle_launcher_action(self, action: str):
        """Handle floating launcher quick actions."""
        if action == "open":
            if self._win:
                self._win.show_animated()
        elif action == "quit":
            self._app.quit()

    # ── Workers ──────────────────────────────────────────────────────────────

    def _start_workers(self):
        """Start background QThread workers."""
        # Command execution thread (API-backed)
        self._cmd_thread = ClientCommandThread()
        self._cmd_thread.started_sig.connect(self._on_cmd_started)
        self._cmd_thread.finished_sig.connect(self._on_cmd_finished)
        self._cmd_thread.error_sig.connect(self._on_cmd_error)
        self._cmd_thread.state_sig.connect(self._propagate_state)

        # Audio level animation
        self._audio_prov = ClientAudioLevelProvider()
        self._audio_prov.level_changed.connect(self._on_audio_level)
        self._audio_prov.start()

        # TTS / VAD stubs (keep UI animation consistent)
        self._tts_mon = ClientTTSMonitor()
        self._vad_mon = ClientVADMonitor()

    def _load_history(self):
        """Load recent chat history from the API."""
        loader = ClientHistoryLoader()
        loader.history_ready.connect(self._on_history_ready)
        loader.start()

    @pyqtSlot(list)
    def _on_history_ready(self, messages: list):
        if self._win and messages:
            self._win.load_chat_history(messages)

    # ── Audio level ──────────────────────────────────────────────────────────

    def _on_audio_level(self, level: float):
        """Forward audio level to the floating launcher animation."""
        # FloatingLauncher may have set_audio_level or similar; gracefully skip
        try:
            if self._launcher and hasattr(self._launcher, "set_audio_level"):
                self._launcher.set_audio_level(level)
        except Exception:
            pass

    # ── State propagation ────────────────────────────────────────────────────

    def _propagate_state(self, state: str):
        """Forward state changes to launcher and main window."""
        if self._launcher:
            self._launcher.set_state(state)
        if self._win:
            try:
                self._win.set_state(state)
            except AttributeError:
                pass
        if self._audio_prov:
            if state in ("thinking", "executing"):
                self._audio_prov.set_state("listening")
            elif state == "speaking":
                self._audio_prov.set_state("speaking")
            else:
                self._audio_prov.set_state("idle")

    # ── Command Handling ─────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_command_submitted(self, command: str):
        """Route a user command through the API command thread."""
        if not command.strip():
            return
        if self._win:
            self._win.add_user_message(command)
            self._win.show_thinking()
        if self._cmd_thread:
            self._cmd_thread.execute(command)
        self._propagate_state("thinking")

    @pyqtSlot(str)
    def _on_cmd_started(self, command: str):
        if self._win:
            self._win.set_input_enabled(False)

    @pyqtSlot(str, str)
    def _on_cmd_finished(self, command: str, response: str):
        if self._win:
            self._win.add_assistant_message(response)
            self._win.set_input_enabled(True)
        self._propagate_state("speaking")
        # Optional local TTS
        self._speak_locally(response)
        # Return to idle after a short delay
        QTimer.singleShot(2500, lambda: self._propagate_state("idle"))

    @pyqtSlot(str, str)
    def _on_cmd_error(self, command: str, error: str):
        error_msg = "Sorry, I couldn't reach the server. Please check your internet connection."
        if self._win:
            self._win.add_assistant_message(error_msg)
            self._win.set_input_enabled(True)
        self._propagate_state("idle")
        print(f"[CLIENT APP] Command error for '{command}': {error}")

    # ── TTS ──────────────────────────────────────────────────────────────────

    def _speak_locally(self, text: str):
        """Optionally speak response with local pyttsx3 TTS."""
        def _tts():
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", 175)
                engine.setProperty("volume", 0.9)
                engine.say(text[:400])
                engine.runAndWait()
                self._propagate_state("idle")
            except Exception:
                pass  # TTS is optional in thin client
        threading.Thread(target=_tts, daemon=True).start()

    # ── Greeting ─────────────────────────────────────────────────────────────

    def _greet_user(self):
        """Show greeting after login."""
        greeting = (
            f"Welcome back, {self._username}! "
            f"I'm {self._assistant_name}. How can I help you today?"
        )
        QTimer.singleShot(600, lambda: self._on_cmd_finished("", greeting))

    # ── Assistant name update ────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_assistant_name_updated(self, new_name: str):
        """Handle user renaming the assistant from settings."""
        self._assistant_name = new_name
        if self._launcher:
            self._launcher.set_user_context(self._username, new_name)
        if self._tray:
            self._tray.setToolTip(f"Smart Assistant — {new_name}")
        # Persist via API
        try:
            from core.api_client import get_api_client
            get_api_client()._request(
                "/api/users/me/preferences",
                method="POST",
                payload={"assistant_name": new_name}
            )
        except Exception as e:
            print(f"[CLIENT APP] Could not persist assistant name: {e}")

    @pyqtSlot(str)
    def _on_accent_changed(self, hex_color: str):
        """Handle accent color update from settings or configuration."""
        if not hex_color:
            return
        if self._launcher:
            self._launcher.set_accent_color(hex_color)
        if self._win:
            self._win.set_accent_color(hex_color)

    # ── Logout ───────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_logout(self):
        """Handle logout: clear session, show login again."""
        print("[CLIENT APP] Logout requested.")

        # Stop workers
        if self._audio_prov:
            self._audio_prov.stop()
            self._audio_prov = None
        if self._tts_mon:
            self._tts_mon.stop()
            self._tts_mon = None
        if self._vad_mon:
            self._vad_mon.stop()
            self._vad_mon = None

        # Clear API session
        try:
            from core.api_client import get_api_client
            get_api_client().logout()
        except Exception:
            pass

        # Hide all windows
        if self._win:
            self._win.hide()
            self._win = None
        if self._launcher:
            self._launcher.hide()
            self._launcher = None
        if self._tray:
            self._tray.hide()
            self._tray = None

        # Reset session state
        self._user_id = None
        self._username = None
        self._assistant_name = "Trevon"
        self._cmd_thread = None

        # Show login again
        QTimer.singleShot(300, self._show_login)
