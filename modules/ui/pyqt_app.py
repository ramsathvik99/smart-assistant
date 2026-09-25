"""
Smart Assistant — PyQt6 Application Coordinator
Replaces legacy/main.py as the production UI orchestrator.

Architecture:
  AssistantApp
    ├── LoginWindow     → on success → start backend services + show main UI
    ├── FloatingLauncher (always-on-top orb)
    ├── MainWindow      (hidden at start, shown on launcher click)
    ├── SystemTrayIcon
    ├── CommandThread   (QThread for backend commands)
    ├── TTSMonitor      (QThread polling is_speaking())
    ├── VADMonitor      (QThread polling VAD state)
    └── AudioLevelProvider (QThread reading SST ring buffer)

IMPORTANT: The backend (brain, router, planner, voice engine, DB, memory)
is NEVER modified here — this file is purely a presentation layer.
"""

import sys
import os
import threading
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, pyqtSlot, QObject
from PyQt6.QtGui import QIcon, QPixmap, QColor, QPainter, QBrush, QRadialGradient

from modules.ui.design_system import C, F, APP_STYLESHEET
from modules.ui.login_window import LoginWindow
from modules.ui.floating_launcher import FloatingLauncher
from modules.ui.main_window import MainWindow
from modules.ui.notification_toast import ToastManager
from modules.ui.worker_threads import (
    CommandThread, TTSMonitor, VADMonitor, AudioLevelProvider, HistoryLoader
)


def _make_tray_icon() -> QIcon:
    """Generate a simple colored orb icon for the system tray."""
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


class AssistantApp(QObject):
    """
    Main coordinator class for the Smart Assistant PyQt6 UI.
    Call run() to start the application event loop.
    """

    def __init__(self):
        super().__init__()
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setApplicationDisplayName("Smart Assistant")
        self._app.setStyleSheet(APP_STYLESHEET)

        # Load window icon if available
        icon_path = os.path.join(os.path.dirname(__file__), "..", "..", "legacy", "icon.ico")
        if os.path.exists(icon_path):
            self._app.setWindowIcon(QIcon(icon_path))

        # Components initialized after login
        self._launcher:    FloatingLauncher    | None = None
        self._win:         MainWindow          | None = None
        self._tray:        QSystemTrayIcon     | None = None
        self._toasts:      ToastManager        = ToastManager()

        # Worker threads
        self._cmd_thread:  CommandThread       | None = None
        self._tts_mon:     TTSMonitor          | None = None
        self._vad_mon:     VADMonitor          | None = None
        self._audio_prov:  AudioLevelProvider  | None = None

        self._user_id:     int  | None = None
        self._username:    str  | None = None
        self._assistant_name: str = "Assistant"

    # ── Startup ───────────────────────────────────────────────────────────────
    def run(self):
        """Entry point — show login then start event loop."""
        self._show_login()
        sys.exit(self._app.exec())

    def _show_login(self):
        self._login_win = LoginWindow()
        self._login_win.login_complete.connect(self._on_login_complete)
        self._login_win.show()

    # ── Post-login ────────────────────────────────────────────────────────────
    @pyqtSlot(int, str)
    def _on_login_complete(self, user_id: int, username: str):
        self._user_id  = user_id
        self._username = username

        # 1. Synchronize session state and identity
        try:
            from legacy.auth_helpers import login_success
            login_success(user_id, username)
        except Exception as e:
            print(f"[AUTH] Error recording login success: {e}")

        # 2. Retrieve user-specific assistant name
        try:
            from legacy.memory_manager import get_assistant_name_db
            asst_name = get_assistant_name_db(user_id)
            if asst_name:
                self._assistant_name = asst_name
            else:
                from instance.config import settings
                self._assistant_name = getattr(settings, 'CURRENT_ASSISTANT_NAME', None) or username
        except Exception:
            self._assistant_name = username

        print(f"[APP] User authenticated: {username} (ID: {user_id}) | Assistant: {self._assistant_name}")

        # Register user with canonical AssistantCore (Single Source of Truth)
        try:
            from core.assistant_core import assistant_core
            assistant_core.set_authenticated_user(user_id, username, self._assistant_name)
        except Exception as e:
            print(f"[APP] Core registration notice: {e}")

        # 3. Build UI components first so visual interface appears immediately
        self._build_ui()

        # 3a. Load and apply user-specific color personalization
        self._apply_user_colors(user_id)

        # 3b. Load and apply per-user voice identity (TTS engine + Settings panel)
        self._apply_user_voice(user_id)

        # 4. Start backend services (Reminders with user_id, Proactive system, optional Dashboard)
        self._start_backend_services()

        # 5. Speak canonical greeting, then start continuous audio stream
        self._speak_greeting()

    def _apply_user_colors(self, user_id: int):
        """
        Load saved dashboard_color and floating_button_color from PostgreSQL for this user,
        apply them to the UI, populate the Settings appearance page, and wire live-update signals.
        """
        try:
            from legacy.memory_manager import get_user_preference_db, set_user_preference_db
            from modules.ui.design_system import DEFAULT_DASHBOARD_COLOR, DEFAULT_FLOATING_COLOR

            dash_color  = get_user_preference_db(user_id, 'dashboard_color',      DEFAULT_DASHBOARD_COLOR)
            float_color = get_user_preference_db(user_id, 'floating_button_color', DEFAULT_FLOATING_COLOR)

            # Apply immediately to live UI
            if self._win:
                self._win.set_accent_color(dash_color)
            if self._launcher:
                self._launcher.set_accent_color(float_color)

            # Populate the Settings appearance page with current user colors
            if self._win and hasattr(self._win, 'settings_page') and self._win.settings_page:
                self._win.settings_page.load_colors(dash_color, float_color)

            # Wire Settings → real-time update + persistence
            if self._win and hasattr(self._win, 'settings_page') and self._win.settings_page:
                sp = self._win.settings_page

                def _on_dash_color_changed(hex_color: str):
                    if self._win:
                        self._win.set_accent_color(hex_color)
                    try:
                        set_user_preference_db(self._user_id, 'dashboard_color', hex_color)
                        print(f"[COLOR] Dashboard color saved: {hex_color} for user {self._user_id}")
                    except Exception as e:
                        print(f"[COLOR] Failed to persist dashboard color: {e}")

                def _on_float_color_changed(hex_color: str):
                    if self._launcher:
                        self._launcher.set_accent_color(hex_color)
                    try:
                        set_user_preference_db(self._user_id, 'floating_button_color', hex_color)
                        print(f"[COLOR] Floating button color saved: {hex_color} for user {self._user_id}")
                    except Exception as e:
                        print(f"[COLOR] Failed to persist floating color: {e}")

                sp.dashboard_color_changed.connect(_on_dash_color_changed)
                sp.floating_color_changed.connect(_on_float_color_changed)

            print(f"[COLOR] User {user_id} colors applied — Dashboard: {dash_color} | Floating: {float_color}")

        except Exception as e:
            print(f"[COLOR] Color personalization setup failed (non-critical): {e}")

    def _apply_user_voice(self, user_id: int):
        """
        Load saved voice profile from PostgreSQL for this user, apply it to the TTS engine,
        pre-populate the Settings Voice & Audio panel, and wire the voice_profile_changed signal.
        Non-fatal: if no profile exists (user hasn't configured voice yet), TTS uses engine defaults.
        """
        try:
            from legacy.memory_manager import get_voice_profile_db, has_voice_profile_db
            profile = get_voice_profile_db(user_id)
            has_profile = has_voice_profile_db(user_id)

            if has_profile and profile.get("voice_id"):
                vid      = profile.get("voice_id")
                gender   = profile.get("voice_gender", "male")
                tone     = profile.get("voice_tone", "professional")
                provider = profile.get("voice_provider", "windows")
                rate     = profile.get("voice_rate", 155)
                vol      = profile.get("voice_volume", 1.0)

                print(f"[VOICE] Loaded profile for user {user_id}")
                print(f"[VOICE] Gender: {gender}")
                print(f"[VOICE] Voice ID: {vid}")
                print(f"[VOICE] Provider: {provider}")
                print(f"[VOICE] Tone: {tone}")

                # Apply to TTS engine immediately so the greeting uses the user's voice
                from legacy.tts import apply_voice_profile
                apply_voice_profile(vid, rate=rate, volume=vol)
            else:
                print(f"[VOICE] User {user_id} has no saved voice profile — using engine defaults")

            # Populate the Settings voice panel with loaded profile (or empty defaults)
            if self._win and hasattr(self._win, 'settings_page') and self._win.settings_page:
                sp = self._win.settings_page
                sp.load_voice_profile(profile if has_profile else {})

                # Wire Settings voice_profile_changed → apply immediately
                def _on_voice_profile_changed(prof: dict):
                    try:
                        from legacy.tts import apply_voice_profile
                        apply_voice_profile(
                            prof.get("voice_id"),
                            rate=int(prof.get("voice_rate", 155)),
                            volume=float(prof.get("voice_volume", 1.0)),
                        )
                        print(f"[VOICE] Voice profile updated live: {prof.get('voice_tone')}")
                    except Exception as e:
                        print(f"[VOICE] Live apply error: {e}")

                sp.voice_profile_changed.connect(_on_voice_profile_changed)

        except Exception as e:
            print(f"[VOICE] Voice personalization setup failed (non-critical): {e}")

    def _start_backend_services(self):
        """Start backend services (reminders, proactive interaction, optional web dashboard)."""
        print("[UI] Starting backend services...")

        # 1. Reminder Scheduler for this authenticated user
        try:
            from extensions.reminder_engine.reminder_scheduler import initialize_scheduler
            from extensions.database_manager import DatabaseManager
            from legacy.memory_manager import get_connection
            from legacy.tts import speak

            def _reminder_sound_alert():
                try:
                    import winsound
                    winsound.Beep(1000, 200)
                except Exception:
                    pass

            class SimplePoolWrapper:
                def __init__(self, connection_func):
                    self.get_connection = connection_func
                def getconn(self):
                    return self.get_connection()
                def putconn(self, conn):
                    try: conn.close()
                    except: pass

            db_manager = DatabaseManager(SimplePoolWrapper(get_connection))
            self._reminder_scheduler = initialize_scheduler(
                tts_callback=speak,
                sound_callback=_reminder_sound_alert,
                db_manager=db_manager,
                user_id=self._user_id
            )
            print(f"[REMINDER ENGINE] Initialized successfully with database persistence for user {self._user_id}")
        except Exception as e:
            print(f"[UI] Reminder scheduler error: {e}")

        # 2. Proactive interaction monitor
        try:
            from legacy.proactive_interaction import start_proactive_interaction
            start_proactive_interaction()
            print("[UI] Proactive interaction monitor started")
        except Exception as e:
            print(f"[UI] Proactive interaction error: {e}")

        # 3. Optional Web Dashboard Server (strictly decoupled)
        try:
            from dashboard.server import start_dashboard_server
            start_dashboard_server()
        except Exception as e:
            print(f"[Dashboard] Optional dashboard server skipped: {e}")

    def _speak_greeting(self):
        """Perform canonical post-login greeting and start continuous audio listening."""
        user = self._username or "there"
        asst = self._assistant_name or "Assistant"

        greeting = f"Welcome back {user}. {asst} is ready when you are."
        print(f"[GREETING] {greeting}")

        def _do_greeting_and_start_audio():
            import threading
            import time
            try:
                import legacy.tts as tts_mod
                # Speak canonical greeting
                tts_mod.speak(greeting)
                # Wait for greeting to finish before opening microphone to prevent self-hearing
                tts_mod.wait_for_silence(timeout=10.0)
            except Exception as e:
                print(f"[GREETING] Error during greeting: {e}")

            # Once greeting is done and silence verified, start continuous audio stream
            try:
                from legacy.sst import start_continuous_audio_stream
                if start_continuous_audio_stream():
                    print("[UI] Continuous audio stream started")
                else:
                    print("[UI] Audio stream failed to start (no audio device?)")
            except Exception as e:
                print(f"[UI] Audio stream error: {e}")

        threading.Thread(target=_do_greeting_and_start_audio, daemon=True).start()

    def _build_ui(self):
        """Construct the PyQt6 UI components after successful authentication."""
        # ── Floating launcher ──
        self._launcher = FloatingLauncher()
        self._launcher.set_user_context(self._username, self._assistant_name)
        self._launcher.single_clicked.connect(self._toggle_main_window)
        self._launcher.action_requested.connect(self._handle_launcher_action)

        # ── Main window ──
        self._win = MainWindow()
        self._win.set_assistant_name(self._assistant_name)
        if self._username:
            self._win.set_user_name(self._username)
        self._win.command_submitted.connect(self._on_command_submitted)
        self._win.logout_requested.connect(self.logout)
        self._win.assistant_name_changed.connect(self._on_assistant_name_updated)
        self._win.minimized.connect(lambda: self._launcher.set_state("idle"))
        # Load recent chat history in background
        self._load_history()

        # ── System tray ──
        self._tray = QSystemTrayIcon(_make_tray_icon(), self._app)
        self._tray.setToolTip(self._assistant_name)
        self._tray.setContextMenu(self._build_tray_menu())
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        # ── Command thread ──
        self._cmd_thread = CommandThread()
        self._cmd_thread.started_sig.connect(self._on_cmd_started)
        self._cmd_thread.finished_sig.connect(self._on_cmd_finished)
        self._cmd_thread.error_sig.connect(self._on_cmd_error)
        self._cmd_thread.state_sig.connect(self._propagate_state)

        # ── TTS monitor ──
        self._tts_mon = TTSMonitor()
        self._tts_mon.speaking_started.connect(lambda: self._propagate_state("speaking"))
        self._tts_mon.speaking_stopped.connect(lambda: self._propagate_state("idle"))
        self._tts_mon.start()

        # ── VAD monitor ──
        self._vad_mon = VADMonitor()
        self._vad_mon.vad_active.connect(self._on_vad_active)
        self._vad_mon.vad_inactive.connect(self._on_vad_inactive)
        self._vad_mon.start()

        # ── Audio level provider ──
        self._audio_prov = AudioLevelProvider()
        self._audio_prov.level_changed.connect(self._on_audio_level)
        self._audio_prov.start()

        # ── Bridge: TTS → floating launcher animation ──
        try:
            import legacy.tts as tts_mod
            tts_mod.floating_ref = _TkBridgeAdapter(self._launcher)
            tts_mod._tk_root = None
        except Exception as e:
            print(f"[UI] TTS bridge setup failed: {e}")

        # ── Clean speech listener for chat feed ──
        try:
            import legacy.tts as tts_mod
            def _on_speech_spoken(text: str):
                if text and text.strip():
                    QTimer.singleShot(0, lambda t=text: (
                        self._win.add_assistant_message(t) if self._win else None
                    ))
            tts_mod.register_speech_callback(_on_speech_spoken)
            self._speech_callback = _on_speech_spoken
            print("[UI] Registered native TTS speech listener for chat feed")
        except Exception as e:
            print(f"[UI] Speech callback registration failed: {e}")

        # ── User ID and subcomponents wiring ──
        if self._user_id and self._win:
            self._win.set_user_id(self._user_id)

        # Register UI presentation handlers with canonical AssistantCore
        try:
            from core.assistant_core import assistant_core
            assistant_core.register_ui_action_handler("open_dashboard", self.open_dashboard)

            # Register Ephemeral Visual Response Surface listener
            def _on_visual_event(vr_data):
                if vr_data is None:
                    if self._launcher:
                        self._launcher.dismiss_visual_response()
                else:
                    from core.visual_response import VisualResponse
                    vr = VisualResponse.from_dict(vr_data)
                    if self._launcher:
                        QTimer.singleShot(0, lambda v=vr: self._launcher.show_visual_response(v) if self._launcher else None)

            assistant_core.register_visual_listener(_on_visual_event)
            self._visual_event_listener = _on_visual_event
        except Exception as e:
            print(f"[UI] UI action handler registration notice: {e}")

        # ── Startup UI state: Floating Launcher only. Dashboard remains closed by default ──
        self._launcher.show()
        print("[UI] PyQt6 UI ready — Floating Launcher active. Dashboard window is closed by default.")

    # ── Command flow ─────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_command_submitted(self, text: str):
        if not text or not text.strip():
            return
        if self._cmd_thread and self._cmd_thread.isRunning():
            self._toasts.show("Still processing previous command…", "warning", 2500)
            return

        # Dismiss visual response panel when a new command is entered (Requirement 18)
        if self._launcher:
            self._launcher.dismiss_visual_response()

        # Show in chat
        if self._win:
            self._win.show_on_chat()
            self._win.add_user_message(text)
            self._win.show_thinking()
            self._win.set_input_enabled(False)

        self._propagate_state("thinking")
        if self._cmd_thread:
            self._cmd_thread.execute(text)

    @pyqtSlot(str)
    def _on_cmd_started(self, cmd: str):
        pass  # state already set to thinking

    @pyqtSlot(str, str)
    def _on_cmd_finished(self, cmd: str, response: str):
        if self._win:
            self._win.add_assistant_message(response)
            self._win.set_input_enabled(True)
        self._propagate_state("idle")

    @pyqtSlot(str, str)
    def _on_cmd_error(self, cmd: str, error: str):
        if self._win:
            self._win.add_assistant_message(f"Error: {error}")
            self._win.set_input_enabled(True)
        self._propagate_state("error")
        self._toasts.show(f"Command error: {error[:60]}", "error")
        # Reset to idle after 3s
        QTimer.singleShot(3000, lambda: self._propagate_state("idle"))

    # ── State propagation ─────────────────────────────────────────────────────
    @pyqtSlot(str)
    def _propagate_state(self, state: str):
        try:
            from core.assistant_core import assistant_core
            assistant_core.set_state(state)
        except Exception:
            pass
        if self._launcher:
            self._launcher.set_state(state)
        if self._win:
            self._win.set_state(state)

    # ── VAD ───────────────────────────────────────────────────────────────────
    def _on_vad_active(self):
        if not (self._cmd_thread and self._cmd_thread.isRunning()):
            self._propagate_state("listening")
            if self._win:
                self._win.set_listening_indicator(True)

    def _on_vad_inactive(self):
        if not (self._cmd_thread and self._cmd_thread.isRunning()):
            self._propagate_state("idle")
            if self._win:
                self._win.set_listening_indicator(False)

    # ── Audio level ───────────────────────────────────────────────────────────
    def _on_audio_level(self, level: float):
        try:
            from core.assistant_core import assistant_core
            assistant_core.set_audio_level(level)
        except Exception:
            pass
        if self._launcher:
            self._launcher.set_audio_level(level)
        if self._win:
            self._win.set_audio_level(level)

    # ── Launcher / window control ─────────────────────────────────────────────
    def open_dashboard(self):
        """
        Open or restore the Assistant Dashboard window.
        Connects directly to existing assistant state, restores if minimized,
        and focuses the existing window without creating duplicate instances.
        """
        if not self._win:
            return
        self._win.select_tab(0)  # Tab 0 is Dashboard
        self._win.refresh_dashboard()
        if self._win.isMinimized():
            self._win.showNormal()
        self._win.show_animated()
        self._win.raise_()
        self._win.activateWindow()

    def _toggle_main_window(self):
        if self._win:
            if self._win.isVisible():
                self._win.hide()
            else:
                self._win.show_on_chat()

    def _show_main_window(self):
        if self._win:
            self._win.show_on_chat()

    def _on_task_cancel_requested(self):
        self._toasts.show("Task cancellation requested", "warning", 2000)
        try:
            from core.assistant_core import assistant_core
            assistant_core.cancel_task()
        except Exception:
            pass
        if self._win:
            self._win.task_dock.complete_task(success=False, message="Task stopped by user.")

    def _on_assistant_name_updated(self, new_name: str):
        self._assistant_name = new_name
        try:
            from core.assistant_core import assistant_core
            assistant_core.set_assistant_name(new_name)
        except Exception:
            pass
        if self._launcher:
            self._launcher.set_assistant_name(new_name)
        if self._tray:
            self._tray.setToolTip(new_name)
        self._toasts.show(f"Assistant renamed to {new_name}", "info", 2500)

    def _handle_launcher_action(self, action: str):
        if not self._win:
            return

        # ── Double-Click Quick Actions ──
        if action == "talk":
            self._win.show_on_chat()
            self._toasts.show("Listening for your command…", "info", 2000)
        elif action == "type_request":
            self._win.show_on_chat()
            if hasattr(self._win, '_chat_page') and hasattr(self._win._chat_page, 'cmd_bar'):
                self._win._chat_page.cmd_bar.focus_input()
        elif action == "reminders":
            self._win.show_on_chat()
            self._win.add_assistant_message("Here are your upcoming reminders. Say 'Remind me to...' or type your reminder to schedule a new one.")
        elif action == "recent_conversation":
            self._win.select_tab(1)
            self._win.show_animated()
        elif action == "memory":
            self._win.select_tab(3)
            self._win.show_animated()
        elif action == "current_task" or action == "tasks":
            self._win.select_tab(2)
            self._win.show_animated()
        elif action == "stop_cancel":
            if hasattr(self, '_cmd_thread') and self._cmd_thread and self._cmd_thread.isRunning():
                self._cmd_thread.terminate()
            self._propagate_state("idle")
            self._toasts.show("Task execution stopped.", "info", 2000)
        elif action in ("stop_speaking", "mute_tts"):
            try:
                from legacy.tts import stop_speaking
                stop_speaking()
            except Exception as e:
                print(f"[UI] Stop speaking error: {e}")
            self._propagate_state("idle")
            self._toasts.show("Audio output silenced.", "info", 1500)
        elif action == "system_status" or action == "telemetry":
            self._win.select_tab(4)
            self._win.show_animated()

        # ── Right-Click Control Center Actions & Dashboard ──
        elif action in ("dashboard", "show"):
            self.open_dashboard()
        elif action == "toggle_listening":
            try:
                from legacy.sst import is_continuous_audio_running, start_continuous_audio_stream, stop_continuous_audio_stream
                if is_continuous_audio_running():
                    stop_continuous_audio_stream()
                    self._toasts.show("Continuous listening paused (Mic muted)", "info", 2000)
                else:
                    start_continuous_audio_stream()
                    self._toasts.show("Continuous listening active (Mic unmuted)", "info", 2000)
            except Exception as e:
                print(f"[UI] Toggle listening error: {e}")
                self._toasts.show(f"Mic toggle notice: {e}", "warning", 2500)
        elif action == "reset_mic":
            try:
                from legacy.sst import reset_microphone
                reset_microphone()
                self._toasts.show("Microphone re-calibrated for ambient noise", "info", 2200)
            except Exception as e:
                self._toasts.show(f"Mic calibration error: {e}", "warning", 2500)
        elif action == "settings":
            self._win.select_tab(5)
            self._win.show_animated()
        elif action == "web_dashboard":
            try:
                import webbrowser
                from dashboard.server import is_dashboard_running, start_dashboard_server, get_dashboard_url
                if not is_dashboard_running():
                    start_dashboard_server()
                webbrowser.open(get_dashboard_url())
            except Exception as e:
                print(f"[UI] Error opening web dashboard: {e}")
        elif action == "restart":
            confirmed = True
            if self._win:
                confirmed = self._win.request_confirmation(
                    title=f"Restart {self._assistant_name}",
                    message="Are you sure you want to restart the assistant and all runtime services?",
                    is_destructive=False
                )
            if confirmed:
                self._restart()
        elif action == "logout":
            confirmed = True
            if self._win:
                confirmed = self._win.request_confirmation(
                    title="Sign Out",
                    message="Are you sure you want to sign out and return to the login screen?",
                    is_destructive=False
                )
            if confirmed:
                self.logout()
        elif action == "quit":
            confirmed = True
            if self._win:
                confirmed = self._win.request_confirmation(
                    title="Exit Smart Assistant",
                    message="Are you sure you want to shut down the assistant and all services?",
                    is_destructive=True
                )
            if confirmed:
                self._quit()

    def _restart(self):
        """Gracefully restart the assistant application."""
        print("[APP] Restarting application...")
        import subprocess, sys, os
        python_exe = sys.executable
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        entry = os.path.join(root_dir, "assistant.py")
        try:
            subprocess.Popen([python_exe, entry], cwd=root_dir)
            self._quit()
        except Exception as e:
            print(f"[APP] Restart error: {e}")

    def _quit(self):
        """Perform orderly application termination."""
        print("[APP] Shutting down application...")
        if self._launcher:
            self._launcher.close()
        if self._win:
            self._win.close()
        if self._tray:
            self._tray.hide()
        from assistant import shutdown
        shutdown()

    # ── System tray ──────────────────────────────────────────────────────────
    def _build_tray_menu(self) -> QMenu:
        menu = QMenu()
        menu.setStyleSheet(f"""
            QMenu {{
                background: rgba(8, 13, 18, 245);
                color: {C.TEXT};
                border: 1px solid rgba(0, 212, 255, 0.28);
                border-radius: 10px;
                padding: 4px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
            }}
            QMenu::item {{
                padding: 8px 20px;
                border-radius: 6px;
            }}
            QMenu::item:selected {{
                background: rgba(0, 212, 255, 0.12);
                color: {C.ACC};
            }}
            QMenu::separator {{
                height: 1px;
                background: rgba(0, 212, 255, 0.12);
                margin: 4px 10px;
            }}
        """)

        title = menu.addAction(f"  {self._assistant_name}")
        title.setEnabled(False)
        menu.addSeparator()

        dash_act = menu.addAction("  Dashboard")
        chat_act = menu.addAction("  Chat")
        task_act = menu.addAction("  Tasks")
        mem_act  = menu.addAction("  Memory Hub")
        telem_act = menu.addAction("  System Telemetry")
        sett_act = menu.addAction("  Settings")
        menu.addSeparator()
        logout_act = menu.addAction("  Logout")
        quit_act = menu.addAction("  Quit")

        dash_act.triggered.connect(lambda: self.open_dashboard())
        chat_act.triggered.connect(lambda: self._win.show_on_chat() if self._win else None)
        task_act.triggered.connect(lambda: (self._win.select_tab(2), self._win.show_animated()) if self._win else None)
        mem_act.triggered.connect(lambda: (self._win.select_tab(3), self._win.show_animated()) if self._win else None)
        telem_act.triggered.connect(lambda: (self._win.select_tab(4), self._win.show_animated()) if self._win else None)
        sett_act.triggered.connect(lambda: (self._win.select_tab(5), self._win.show_animated()) if self._win else None)
        logout_act.triggered.connect(self.logout)
        quit_act.triggered.connect(self._quit)
        return menu

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_main_window()

    def logout(self):
        """Logout the current user and return to the login window."""
        print("[APP] Logging out current user...")

        # Stop speech listener
        try:
            import legacy.tts as tts_mod
            if hasattr(self, '_speech_callback'):
                tts_mod.unregister_speech_callback(self._speech_callback)
        except Exception:
            pass

        # Stop continuous audio capture
        try:
            from legacy.sst import stop_continuous_audio_stream
            stop_continuous_audio_stream()
        except Exception as e:
            print(f"[APP] Error stopping audio stream: {e}")

        # Stop reminder scheduler
        try:
            from extensions.reminder_engine.reminder_scheduler import shutdown_scheduler
            shutdown_scheduler()
        except Exception:
            pass

        # Stop proactive interaction
        try:
            from legacy.proactive_interaction import get_proactive_interaction
            proactive = get_proactive_interaction()
            if proactive:
                proactive.stop()
        except Exception:
            pass

        # Stop proactive observation coordinator (Phase 6)
        try:
            from core.proactive_observer import proactive_coordinator
            from instance.config import settings
            uid = getattr(settings, 'CURRENT_USER_ID', None)
            proactive_coordinator.logout_user(str(uid) if uid else None)
        except Exception:
            pass

        # Stop monitoring worker threads
        for worker in [self._tts_mon, self._vad_mon, self._audio_prov]:
            if worker:
                try:
                    worker.stop()
                except Exception:
                    pass

        # Hide active UI components
        if self._launcher:
            self._launcher.hide()
            self._launcher = None
        if self._win:
            self._win.hide()
            self._win = None
        if self._tray:
            self._tray.hide()
            self._tray = None

        # Reset session identity
        try:
            from instance.config import settings
            settings.CURRENT_USER_ID = None
            settings.CURRENT_USERNAME = None
            settings.CURRENT_ASSISTANT_NAME = None
            settings.set_last_user(None)
        except Exception:
            pass

        try:
            from core.assistant_core import assistant_core
            assistant_core.set_authenticated_user(0, "guest", "Assistant")
        except Exception:
            pass

        self._user_id = None
        self._username = None

        # Return to login window
        self._show_login()

    def _quit(self):
        """Gracefully shut down all services and exit application."""
        print("[APP] Shutting down application...")

        # Stop speech listener
        try:
            import legacy.tts as tts_mod
            if hasattr(self, '_speech_callback'):
                tts_mod.unregister_speech_callback(self._speech_callback)
        except Exception:
            pass

        # Stop continuous audio capture
        try:
            from legacy.sst import stop_continuous_audio_stream
            stop_continuous_audio_stream()
        except Exception:
            pass

        # Stop reminder scheduler
        try:
            from extensions.reminder_engine.reminder_scheduler import shutdown_scheduler
            shutdown_scheduler()
        except Exception:
            pass

        # Stop proactive interaction
        try:
            from legacy.proactive_interaction import get_proactive_interaction
            proactive = get_proactive_interaction()
            if proactive:
                proactive.stop()
        except Exception:
            pass

        # Stop workers
        for worker in [self._tts_mon, self._vad_mon, self._audio_prov]:
            if worker:
                try:
                    worker.stop()
                except Exception:
                    pass

        # Stop dashboard server cleanly if running
        try:
            from dashboard.server import stop_dashboard_server
            stop_dashboard_server()
        except Exception:
            pass

        if self._tray:
            self._tray.hide()
        QApplication.quit()

    # ── History loader ────────────────────────────────────────────────────────
    def _load_history(self):
        if not self._user_id:
            return
        loader = HistoryLoader(self._user_id)
        loader.history_ready.connect(self._on_history_ready)
        loader.start()
        self._hist_loader = loader  # keep reference

    @pyqtSlot(list)
    def _on_history_ready(self, history: list):
        if self._win:
            self._win.load_chat_history(history)


# ─────────────────────────────────────────────────────────────────────────────
# TK → Qt bridge adapter
# Replaces the Tkinter floating_ref so legacy/tts.py can still call
# start_anim() / stop_anim() without any Tkinter dependency.
# ─────────────────────────────────────────────────────────────────────────────
class _TkBridgeAdapter:
    """
    Drop-in replacement for FloatingButton that the TTS worker references.
    Routes start_anim/stop_anim calls to the PyQt6 FloatingLauncher via Qt timers
    (since TTS runs in a background thread, not the Qt main thread).
    """

    def __init__(self, launcher: FloatingLauncher):
        self._launcher = launcher

    def start_anim(self):
        """Called by TTS worker thread when speech starts."""
        QTimer.singleShot(0, lambda: self._launcher.set_state("speaking"))

    def stop_anim(self):
        """Called by TTS worker thread when speech stops."""
        QTimer.singleShot(0, lambda: self._launcher.set_state("idle"))

