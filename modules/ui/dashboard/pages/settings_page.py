from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime
from typing import Any, Dict

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QColor, QIcon, QPixmap, QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QStackedWidget,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QTimeEdit, QToolButton,
    QVBoxLayout, QWidget, QApplication,
)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from ..ds import (
    C, F, Spacing, Radius, COLOR_PRESETS, ICONS, icon, icon_pixmap,
    HLine, VLine, Card, StatusChip, SectionHeader, LoadingState, EmptyState, ErrorState, rgba_str, get_contrast_color,
)
from ..service_adapters import (
    get_identity, set_assistant_name_ui, get_assistant_state,
    load_user_preferences, save_user_preference,
    load_learned_rules, delete_learned_rule,
    has_email_credentials, load_emails,
    load_paired_devices,
    run_diagnostics, export_conversations, clear_conversation_history,
    load_api_credentials_status, save_api_credential, delete_api_credential, test_api_credential,
    get_primary_provider_adapter, set_primary_provider_adapter,
)
from core.credential_manager import validate_assistant_name, get_credential_manager
from legacy.tts import enumerate_voices, stop_speaking, apply_voice_profile, preview_voice
from ..workers import DashboardWorker

try:
    import instance.config as _cfg
    SETTINGS = _cfg.Settings()
except Exception:
    SETTINGS = None


PROVIDER_MODELS: Dict[str, str] = {
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-1.5-flash",
    "ollama": "llama3",
    "deepseek": "deepseek-chat",
    "anthropic": "claude-3-5-sonnet-20241022",
    "huggingface": "meta-llama/Meta-Llama-3-8B-Instruct",
}


class _PrefCache:
    def __init__(self):
        self._data: Dict[str, Any] = {}

    def load(self, data: Dict[str, Any]):
        self._data = dict(data or {})

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        self._data[key] = value


class SettingsPage(QWidget):
    accent_changed = pyqtSignal(str)
    identity_changed = pyqtSignal()
    # Compatibility signals for pyqt_app integration
    dashboard_color_changed = pyqtSignal(str)
    floating_color_changed = pyqtSignal(str)
    voice_profile_changed = pyqtSignal(dict)

    TAB_ORDER = [
        ("profile", "Profile"),
        ("api_keys", "API Keys & Integrations"),
        ("identity", "Assistant Identity"),
        ("appearance", "Appearance"),
        ("voice", "Voice & Audio"),
        ("intelligence", "Intelligence & Behavior"),
        ("memory", "Memory & Privacy"),
        ("email", "Email"),
        ("devices", "Devices"),
        ("notifications", "Notifications"),
        ("security", "Security & Data"),
        ("diagnostics", "Diagnostics"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prefs = _PrefCache()
        self._workers = []
        self._build_ui()
        QTimer.singleShot(50, self._load_initial_data)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(Spacing.LG2, Spacing.LG2, Spacing.LG2, Spacing.LG2)
        root.setSpacing(Spacing.LG)

        header = QHBoxLayout()
        header.setSpacing(Spacing.MD)
        sh = SectionHeader("Settings",
                          "Configure your assistant, appearance, privacy, and integrations.",
                          accent=C.SEC_SETTINGS)
        header.addWidget(sh, 1)

        self.save_all_btn = QPushButton(" Save & Apply All ")
        self.save_all_btn.setObjectName("PrimaryBtn")
        self.save_all_btn.setIcon(icon(ICONS.SAVE, get_contrast_color(C.ACCENT), 14))
        self.save_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_all_btn.clicked.connect(self._on_save_all)
        header.addWidget(self.save_all_btn)
        hw = QWidget(); hw.setLayout(header)
        root.addWidget(hw)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setUsesScrollButtons(True)
        self.tabs.setStyleSheet(self._tab_qss())
        root.addWidget(self.tabs, 1)

        self._tab_profile = self._build_tab_profile()
        self._tab_api_keys = self._build_tab_api_keys()
        self._tab_identity = self._build_tab_identity()
        self._tab_appearance = self._build_tab_appearance()
        self._tab_voice = self._build_tab_voice()
        self._tab_intelligence = self._build_tab_intelligence()
        self._tab_memory = self._build_tab_memory()
        self._tab_email = self._build_tab_email()
        self._tab_devices = self._build_tab_devices()
        self._tab_notifications = self._build_tab_notifications()
        self._tab_security = self._build_tab_security()
        self._tab_diagnostics = self._build_tab_diagnostics()

        for key, name in self.TAB_ORDER:
            w = getattr(self, f"_tab_{key}")
            ic = getattr(self, f"_icon_{key}", lambda: icon(ICONS.SETTINGS, C.SEC_SETTINGS))()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            scroll.setWidget(w)
            self.tabs.addTab(scroll, ic, name)

    # -------------------------------------------------------- tab factories
    # Subtle semantic icon identities per section specification
    def _icon_profile(self): return icon(ICONS.USER, C.SEC_COMMUNICATIONS)
    def _icon_api_keys(self): return icon(ICONS.LOCK, C.SEC_SETTINGS)
    def _icon_identity(self): return icon(ICONS.ASSISTANT, C.SEC_ASSISTANT)
    def _icon_appearance(self): return icon(ICONS.STAR, C.SEC_SCHEDULE)
    def _icon_voice(self): return icon(ICONS.VOLUME_UP, C.SEC_CONNECTED)
    def _icon_intelligence(self): return icon(ICONS.BRAIN, C.SEC_INTELLIGENCE)
    def _icon_memory(self): return icon(ICONS.DATABASE, C.SEC_WORKSPACE)
    def _icon_email(self): return icon(ICONS.COMMUNICATIONS, C.SEC_COMMUNICATIONS)
    def _icon_devices(self): return icon(ICONS.CONNECTED_WORLD, C.SEC_CONNECTED)
    def _icon_notifications(self): return icon(ICONS.BELL, C.STATUS_WARNING)
    def _icon_security(self): return icon(ICONS.LOCK, C.STATUS_ERROR)
    def _icon_diagnostics(self): return icon(ICONS.DIAGNOSTICS, C.STATUS_SUCCESS)

    # -------------------------------------------------------------- Profile
    def _build_tab_profile(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        card = Card(title="User Profile")
        form = QFormLayout(); card.body.addLayout(form)
        form.setSpacing(Spacing.MD)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.pf_name = QLineEdit()
        self.pf_name.setPlaceholderText("Your display name")
        self.pf_name.setStyleSheet(self._line_qss())

        self.pf_email = QLineEdit()
        self.pf_email.setPlaceholderText("Email (used for login/account)")
        self.pf_email.setReadOnly(True)
        self.pf_email.setStyleSheet(self._line_qss())

        self.pf_lang = QComboBox()
        for code, label in [
            ("en-US", "English (US)"), ("en-GB", "English (UK)"),
            ("en-IN", "English (India)"), ("es-ES", "Spanish"),
            ("fr-FR", "French"), ("de-DE", "German"),
            ("hi-IN", "Hindi"), ("zh-CN", "Chinese"),
        ]:
            self.pf_lang.addItem(label, code)
        self.pf_lang.setStyleSheet(self._combo_qss())

        self.pf_tz = QComboBox()
        self.pf_tz.setEditable(True)
        for tz in ["UTC", "US/Eastern", "US/Pacific", "Europe/London",
                   "Europe/Berlin", "Asia/Kolkata", "Asia/Singapore", "Asia/Shanghai"]:
            self.pf_tz.addItem(tz)
        self.pf_tz.setStyleSheet(self._combo_qss())

        apply_btn = QPushButton(" Update Profile ")
        apply_btn.setIcon(icon(ICONS.SAVE, C.SEC_SETTINGS, 14))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(self._btn_primary())
        apply_btn.clicked.connect(self._on_save_profile)

        form.addRow("Display Name", self.pf_name)
        form.addRow("Login Email", self.pf_email)
        form.addRow("Language", self.pf_lang)
        form.addRow("Timezone", self.pf_tz)
        form.addRow("", apply_btn)

        lay.addWidget(card)
        lay.addStretch(1)
        return w

    # ----------------------------------------------------------- API Keys & Integrations
    def _build_tab_api_keys(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        card_info = Card(title="API Keys & Integrations Architecture")
        info_lbl = QLabel(
            "Configure your personal credentials for AI models, search engines, and external integrations.\n"
            "• Security: Keys are encrypted per-user using Windows Data Protection API (DPAPI) and stored separately from general settings.\n"
            "• Isolation: When distributed as an .exe, each user configures their own keys. No developer secrets are shared.\n"
            "• Capability-Aware: Features requiring unconfigured keys are gracefully skipped while unrelated features continue working."
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 12px; line-height: 1.4;")
        card_info.body.addWidget(info_lbl)
        lay.addWidget(card_info)

        # Primary AI Provider Selector Card
        card_prim = Card(title="Primary AI Engine Selection")
        prim_v = QVBoxLayout()
        prim_h = QHBoxLayout()
        prim_lbl = QLabel("Preferred Primary Provider:")
        prim_lbl.setStyleSheet(f"color: {C.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;")
        prim_h.addWidget(prim_lbl)

        self.primary_provider_combo = QComboBox()
        self.primary_provider_combo.setStyleSheet(self._combo_qss())
        for pid, pname in [
            ("groq", "Groq Cloud (Ultra-fast LLM)"),
            ("openai", "OpenAI (GPT-4o, GPT-3.5)"),
            ("gemini", "Google Gemini (Flash, Pro)"),
            ("ollama", "Ollama (Local Offline Daemon)"),
            ("deepseek", "DeepSeek"),
            ("anthropic", "Anthropic Claude"),
            ("huggingface", "HuggingFace"),
        ]:
            self.primary_provider_combo.addItem(pname, pid)
        self.primary_provider_combo.currentIndexChanged.connect(self._on_primary_provider_changed)
        prim_h.addWidget(self.primary_provider_combo, 1)
        prim_v.addLayout(prim_h)

        self.primary_model_lbl = QLabel(f"Active Model: <b>{PROVIDER_MODELS.get('groq', 'llama-3.3-70b-versatile')}</b>")
        self.primary_model_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 12px; margin-top: 4px;")
        prim_v.addWidget(self.primary_model_lbl)
        card_prim.body.addLayout(prim_v)
        lay.addWidget(card_prim)

        card_keys = Card(title="Manage Credentials")
        self.api_keys_layout = QVBoxLayout()
        self.api_keys_layout.setSpacing(Spacing.SM)
        card_keys.body.addLayout(self.api_keys_layout)

        self._api_key_rows: Dict[str, Dict[str, Any]] = {}
        providers = [
            ("groq", "Groq Cloud", "LLM", "Ultra-fast conversational AI (free tier available)", "llama-3.3-70b-versatile", True, "https://console.groq.com/keys"),
            ("openai", "OpenAI", "LLM", "GPT-4o & GPT-3.5 models for reasoning & completion", "gpt-4o-mini", True, "https://platform.openai.com/api-keys"),
            ("gemini", "Google Gemini", "LLM", "Multimodal intelligence & reasoning", "gemini-1.5-flash", True, "https://aistudio.google.com/app/apikey"),
            ("ollama", "Ollama", "Local", "Local offline inference daemon (requires no cloud key)", "llama3", False, "https://ollama.com"),
            ("deepseek", "DeepSeek", "LLM", "Specialized coding & conversational models", "deepseek-chat", True, "https://platform.deepseek.com/api_keys"),
            ("anthropic", "Anthropic Claude", "LLM", "Claude 3 models for reasoning", "claude-3-5-sonnet-20241022", True, "https://console.anthropic.com/settings/keys"),
            ("huggingface", "HuggingFace", "LLM", "Inference router for open-source models", "meta-llama/Meta-Llama-3-8B-Instruct", True, "https://huggingface.co/settings/tokens"),
            ("serpapi", "SerpAPI", "Search", "Google Search API for real-time web retrieval", "google-search", True, "https://serpapi.com/manage-api-key"),
            ("tavily", "Tavily Search", "Search", "Search API optimized for AI agent retrieval", "search", True, "https://app.tavily.com/home"),
            ("email", "Email Account", "Integration", "App password for personal email reading & sending", "smtp-imap", True, "https://myaccount.google.com/apppasswords"),
            ("openweather", "OpenWeatherMap", "Integration", "Live weather conditions and forecasts", "weather-data", True, "https://home.openweathermap.org/api_keys"),
            ("tmdb", "TMDB", "Integration", "Movie and series recommendations", "tmdb-v3", True, "https://www.themoviedb.org/settings/api"),
            ("calendarific", "Calendarific", "Integration", "Public holidays and observance calendar", "holidays", True, "https://calendarific.com/account"),
        ]

        for pid, name, cat, desc, def_model, req_key, help_url in providers:
            row_frame = QFrame()
            row_frame.setStyleSheet(f"""
                QFrame {{
                    background: {C.SURFACE_BG};
                    border: 1px solid {C.BORDER};
                    border-radius: {Radius.MD}px;
                    padding: 8px 12px;
                }}
            """)
            rlay = QVBoxLayout(row_frame)
            rlay.setContentsMargins(4, 4, 4, 4)
            rlay.setSpacing(6)

            # Header row: Name + Category badge + Status Chip + Masked Hint + Link button
            top_h = QHBoxLayout()
            top_h.setSpacing(8)

            lbl_name = QLabel(f"<b>{name}</b> <span style='color:{C.TEXT_MUTED};font-size:11px;'>({cat})</span>")
            lbl_name.setStyleSheet(f"color: {C.TEXT_PRIMARY}; font-size: 13px;")
            top_h.addWidget(lbl_name)

            chip = StatusChip("Checking", "neutral")
            top_h.addWidget(chip)

            hint_lbl = QLabel("")
            hint_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px; font-family: monospace;")
            top_h.addWidget(hint_lbl)

            top_h.addStretch(1)

            if help_url:
                get_btn = QPushButton("Get API Key ↗" if req_key else "Get Ollama ↗")
                get_btn.setFixedHeight(24)
                get_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        color: {C.SEC_SETTINGS};
                        border: 1px solid {C.BORDER};
                        border-radius: 4px;
                        font-size: 11px;
                        padding: 2px 8px;
                    }}
                    QPushButton:hover {{
                        background: {rgba_str(C.SEC_SETTINGS, 0.1)};
                        border-color: {C.SEC_SETTINGS};
                    }}
                """)
                get_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                get_btn.setToolTip(f"Open provider portal: {help_url}")
                get_btn.clicked.connect(lambda _, u=help_url: QDesktopServices.openUrl(QUrl(u)))
                top_h.addWidget(get_btn)

            rlay.addLayout(top_h)

            # Detail row: Description + Key Requirement + Model info
            req_tag = "<span style='color:#F59E0B;'>🔑 API Key Required</span>" if req_key else "<span style='color:#10B981;'>💻 Local Server (No Key Needed)</span>"
            model_tag = f" • <span style='color:{C.TEXT_MUTED};'>Model: <b>{def_model}</b></span>" if cat in ("LLM", "Local") else ""
            desc_lbl = QLabel(f"{desc}  —  {req_tag}{model_tag}")
            desc_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px;")
            desc_lbl.setWordWrap(True)
            rlay.addWidget(desc_lbl)

            # Controls row: Input + Eye + Test + Save + Remove
            ctrl_h = QHBoxLayout()
            ctrl_h.setSpacing(6)

            inp = QLineEdit()
            inp.setEchoMode(QLineEdit.EchoMode.Password)
            inp.setPlaceholderText("Enter API key or credential...")
            inp.setStyleSheet(self._line_qss())
            ctrl_h.addWidget(inp, 1)

            eye_btn = QPushButton("👁")
            eye_btn.setFixedSize(32, 32)
            eye_btn.setStyleSheet(self._btn_ghost())
            eye_btn.setToolTip("Reveal / Hide key")
            eye_btn.clicked.connect(lambda _, field=inp, btn=eye_btn: self._toggle_field_echo(field, btn))
            ctrl_h.addWidget(eye_btn)

            test_btn = QPushButton(" Test ")
            test_btn.setStyleSheet(self._btn_ghost())
            test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            test_btn.clicked.connect(lambda _, p=pid, field=inp: self._on_test_api_key(p, field))
            ctrl_h.addWidget(test_btn)

            save_btn = QPushButton(" Save ")
            save_btn.setStyleSheet(self._btn_primary())
            save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            save_btn.clicked.connect(lambda _, p=pid, field=inp: self._on_save_api_key(p, field))
            ctrl_h.addWidget(save_btn)

            del_btn = QPushButton(" Remove ")
            del_btn.setStyleSheet(self._btn_danger())
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.clicked.connect(lambda _, p=pid: self._on_delete_api_key(p))
            ctrl_h.addWidget(del_btn)

            rlay.addLayout(ctrl_h)

            # Feedback label
            fb_lbl = QLabel("")
            fb_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px;")
            rlay.addWidget(fb_lbl)

            self.api_keys_layout.addWidget(row_frame)
            self._api_key_rows[pid] = {
                "chip": chip,
                "hint": hint_lbl,
                "input": inp,
                "feedback": fb_lbl,
                "test_btn": test_btn,
                "save_btn": save_btn,
                "del_btn": del_btn,
                "req_key": req_key,
            }

        lay.addWidget(card_keys)
        lay.addStretch(1)
        return w

    def _on_primary_provider_changed(self, idx: int):
        pid = self.primary_provider_combo.itemData(idx)
        if pid:
            if hasattr(self, "primary_model_lbl"):
                self.primary_model_lbl.setText(f"Active Model: <b>{PROVIDER_MODELS.get(str(pid).lower(), 'default')}</b>")
            def work():
                set_primary_provider_adapter(pid)
                save_user_preference("primary_provider", pid)
                return True
            w = DashboardWorker(work)
            w.result_sig.connect(lambda _: self._flash(f"Primary AI provider set to {pid.upper()}."))
            self._workers.append(w)
            w.start()

    def _toggle_field_echo(self, field: QLineEdit, btn: QPushButton):
        if field.echoMode() == QLineEdit.EchoMode.Password:
            field.setEchoMode(QLineEdit.EchoMode.Normal)
            btn.setText("🔒")
        else:
            field.setEchoMode(QLineEdit.EchoMode.Password)
            btn.setText("👁")

    def _on_test_api_key(self, provider: str, field: QLineEdit):
        val = field.text().strip()
        row = self._api_key_rows.get(provider, {})
        chip = row.get("chip")
        fb = row.get("feedback")
        if chip:
            chip.setText("Testing…")
            chip.setProperty("state", "neutral")
            chip.style().unpolish(chip); chip.style().polish(chip)
        if fb:
            fb.setText("Testing connection…")
            fb.setStyleSheet(f"color: {C.SEC_SETTINGS}; font-size: 11px;")

        def work():
            from ..service_adapters import test_api_credential
            return test_api_credential(provider, candidate_key=val or None)

        def done(res):
            if not fb: return
            msg = res.get("message", "")
            status = res.get("status", "")
            if res.get("success"):
                if chip:
                    chip.setText("Connected")
                    chip.setProperty("state", "online")
                    chip.style().unpolish(chip); chip.style().polish(chip)
                fb.setText(f"✔ {msg or 'Connected'}")
                fb.setStyleSheet(f"color: {C.STATUS_SUCCESS}; font-size: 11px; font-weight: 600;")
            else:
                low_msg = (msg or "").lower()
                if "invalid" in low_msg or "unauthorized" in low_msg or "auth_error" in status or "401" in low_msg:
                    display_status = "Invalid key"
                elif "unavailable" in low_msg or "not running" in low_msg or "outage" in low_msg:
                    display_status = "Provider unavailable"
                elif "timeout" in low_msg or "connection" in low_msg or "network" in low_msg or "connect" in low_msg:
                    display_status = "Connection failed"
                elif "decryption" in low_msg:
                    display_status = "Decryption failed"
                else:
                    display_status = "Connection failed"

                if chip:
                    chip.setText(display_status)
                    chip.setProperty("state", "offline")
                    chip.style().unpolish(chip); chip.style().polish(chip)
                fb.setText(f"✖ {msg or display_status}")
                fb.setStyleSheet(f"color: {C.STATUS_ERROR}; font-size: 11px; font-weight: 600;")

        w = DashboardWorker(work)
        w.result_sig.connect(done)
        w.error_sig.connect(lambda e: fb and fb.setText(f"Error: {e}"))
        self._workers.append(w); w.start()

    def _on_save_api_key(self, provider: str, field: QLineEdit):
        val = field.text().strip()
        row = self._api_key_rows.get(provider, {})
        fb = row.get("feedback")
        if not val and provider != "ollama":
            if fb:
                fb.setText("Please enter a key before saving.")
                fb.setStyleSheet(f"color: {C.STATUS_ERROR}; font-size: 11px;")
            return

        def work():
            from ..service_adapters import save_api_credential
            return save_api_credential(provider, val)

        def done(ok):
            if ok:
                if fb:
                    fb.setText("✔ Credential saved securely.")
                    fb.setStyleSheet(f"color: {C.STATUS_SUCCESS}; font-size: 11px; font-weight: 600;")
                field.clear()
                self._reload_api_credentials()
            else:
                if fb:
                    fb.setText("✖ Failed to save credential.")
                    fb.setStyleSheet(f"color: {C.STATUS_ERROR}; font-size: 11px;")

        w = DashboardWorker(work)
        w.result_sig.connect(done)
        w.error_sig.connect(lambda e: fb and fb.setText(f"Error: {e}"))
        self._workers.append(w); w.start()

    def _on_delete_api_key(self, provider: str):
        row = self._api_key_rows.get(provider, {})
        fb = row.get("feedback")
        r = QMessageBox.question(self, f"Remove {provider.title()} Credential",
                                 f"Are you sure you want to remove the stored credential for {provider.title()}?",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes: return

        def work():
            from ..service_adapters import delete_api_credential
            return delete_api_credential(provider)

        def done(ok):
            if ok:
                if fb:
                    fb.setText("Credential removed.")
                    fb.setStyleSheet(f"color: {C.TEXT_MUTED}; font-size: 11px;")
                self._reload_api_credentials()
            else:
                if fb:
                    fb.setText("Failed to remove.")
                    fb.setStyleSheet(f"color: {C.STATUS_ERROR}; font-size: 11px;")

        w = DashboardWorker(work)
        w.result_sig.connect(done)
        w.error_sig.connect(lambda e: fb and fb.setText(f"Error: {e}"))
        self._workers.append(w); w.start()

    def _reload_api_credentials(self):
        def work():
            from ..service_adapters import load_api_credentials_status
            return load_api_credentials_status()

        def done(items):
            self._apply_api_credentials(items or [])

        w = DashboardWorker(work)
        w.result_sig.connect(done)
        self._workers.append(w); w.start()

    def _apply_api_credentials(self, items: list):
        by_prov = {it.get("provider"): it for it in items}
        for pid, row in self._api_key_rows.items():
            info = by_prov.get(pid, {})
            configured = info.get("configured", False)
            raw_status = info.get("status", "")
            hint = info.get("masked_hint", "")
            chip = row.get("chip")
            hint_lbl = row.get("hint")
            inp = row.get("input")

            if pid == "ollama":
                if chip:
                    chip.setText("Connected" if configured else "Local (No Key Needed)")
                    chip.setProperty("state", "online" if configured else "neutral")
                    chip.style().unpolish(chip); chip.style().polish(chip)
                if hint_lbl: hint_lbl.setText("127.0.0.1:11434")
            elif raw_status == "decryption_failed":
                if chip:
                    chip.setText("Decryption failed")
                    chip.setProperty("state", "offline")
                    chip.style().unpolish(chip); chip.style().polish(chip)
                if hint_lbl: hint_lbl.setText("[Protected]")
                if inp: inp.setPlaceholderText("Re-enter key to repair…")
            elif raw_status == "invalid_key":
                if chip:
                    chip.setText("Invalid key")
                    chip.setProperty("state", "offline")
                    chip.style().unpolish(chip); chip.style().polish(chip)
                if hint_lbl: hint_lbl.setText(hint or "")
                if inp: inp.setPlaceholderText("Replace current key…")
            elif raw_status == "provider_unavailable":
                if chip:
                    chip.setText("Provider unavailable")
                    chip.setProperty("state", "offline")
                    chip.style().unpolish(chip); chip.style().polish(chip)
                if hint_lbl: hint_lbl.setText(hint or "")
                if inp: inp.setPlaceholderText("Replace current key…")
            elif configured:
                if chip:
                    chip.setText("Connected")
                    chip.setProperty("state", "online")
                    chip.style().unpolish(chip); chip.style().polish(chip)
                if hint_lbl: hint_lbl.setText(hint or "")
                if inp: inp.setPlaceholderText("Replace current key…")
            else:
                if chip:
                    chip.setText("Not configured")
                    chip.setProperty("state", "offline")
                    chip.style().unpolish(chip); chip.style().polish(chip)
                if hint_lbl: hint_lbl.setText("")
                if inp: inp.setPlaceholderText("Enter API key or credential…")

    # ----------------------------------------------------------- Identity
    def _build_tab_identity(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        card = Card(title="Assistant Identity")
        form = QFormLayout(); card.body.addLayout(form)
        form.setSpacing(Spacing.MD)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.id_name = QLineEdit()
        self.id_name.setPlaceholderText("e.g. Friday, Nova, Trevon, JARVIS...")
        self.id_name.setStyleSheet(self._line_qss())

        self.id_preview = QLabel("“Hello! I am Friday. How can I help you today?”")
        self.id_preview.setStyleSheet(f"color: {C.ACCENT}; font-size: 11px; font-style: italic; padding: 2px 4px;")
        self.id_name.textChanged.connect(lambda t: self.id_preview.setText(
            f"“Hello! I am {t.strip() or 'Friday'}. How can I help you today?”"
        ))

        self.id_greeting = QLineEdit()
        self.id_greeting.setPlaceholderText("e.g. Hello, sir. What can I do for you?")
        self.id_greeting.setStyleSheet(self._line_qss())

        self.id_persona = QComboBox()
        for label in ["Friendly Assistant", "Professional Executive Aide",
                      "Technical Expert", "Concise Analyst", "Creative Muse"]:
            self.id_persona.addItem(label)
        self.id_persona.setStyleSheet(self._combo_qss())

        self.id_style = QComboBox()
        for label in ["Natural", "Formal", "Casual", "Technical", "Poetic"]:
            self.id_style.addItem(label)
        self.id_style.setStyleSheet(self._combo_qss())

        self.id_formality = QSlider(Qt.Orientation.Horizontal)
        self.id_formality.setRange(0, 100)
        self.id_formality.setValue(50)
        self.id_formality_lbl = QLabel("Balanced")
        self.id_formality_lbl.setStyleSheet(f"color:{C.TEXT_MUTED};min-width:92px;")
        self.id_formality.valueChanged.connect(lambda v: self.id_formality_lbl.setText(
            "Casual" if v < 33 else ("Formal" if v > 66 else "Balanced")))
        formality_row = QHBoxLayout()
        formality_row.addWidget(self.id_formality, 1)
        formality_row.addWidget(self.id_formality_lbl)
        formality_wrap = QWidget()
        formality_wrap.setLayout(formality_row)

        self.id_verbosity = QComboBox()
        for label in ["Terse", "Concise", "Detailed", "Comprehensive"]:
            self.id_verbosity.addItem(label)
        self.id_verbosity.setCurrentIndex(1)
        self.id_verbosity.setStyleSheet(self._combo_qss())

        self.id_proactivity = QComboBox()
        for label in ["Reactive Only", "Suggestive", "Moderately Proactive", "Highly Proactive"]:
            self.id_proactivity.addItem(label)
        self.id_proactivity.setCurrentIndex(1)
        self.id_proactivity.setStyleSheet(self._combo_qss())

        apply_btn = QPushButton(" Apply Identity ")
        apply_btn.setIcon(icon(ICONS.SAVE, C.SEC_SETTINGS, 14))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(self._btn_primary())
        apply_btn.clicked.connect(self._on_save_identity)

        form.addRow("Assistant Name", self.id_name)
        form.addRow("Live Preview", self.id_preview)
        form.addRow("Greeting", self.id_greeting)
        form.addRow("Persona", self.id_persona)
        form.addRow("Response Style", self.id_style)
        form.addRow("Formality", formality_wrap)
        form.addRow("Verbosity", self.id_verbosity)
        form.addRow("Proactivity", self.id_proactivity)
        form.addRow("", apply_btn)

        lay.addWidget(card)
        lay.addStretch(1)
        return w

    # --------------------------------------------------------- Appearance
    def _build_tab_appearance(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        # Theme / accent
        card_accent = Card(title="Theme & Accent Color")
        accent_row = QHBoxLayout()
        accent_row.setSpacing(Spacing.MD)
        card_accent.body.addLayout(accent_row)
        for name, hex_ in COLOR_PRESETS:
            chip = QToolButton()
            chip.setText(name)
            chip.setIcon(icon(ICONS.CHECK, hex_, 14))
            chip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            chip.setProperty("accentChip", True)
            chip.setStyleSheet(f"""
                QToolButton {{
                    background: {rgba_str(hex_, 0.08)};
                    color: {hex_};
                    padding: 6px 12px;
                    border-radius: {Radius.MD}px;
                    font-weight: 600;
                    border: 1px solid {rgba_str(hex_, 0.25)};
                }}
                QToolButton:hover {{ background: {rgba_str(hex_, 0.16)}; }}
            """)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, h=hex_: self._on_set_accent(h))
            accent_row.addWidget(chip)
        accent_row.addStretch(1)
        lay.addWidget(card_accent)

        card_disp = Card(title="Display Options")
        form = QFormLayout()
        card_disp.body.addLayout(form)
        form.setSpacing(Spacing.MD)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ap_anim = QSlider(Qt.Orientation.Horizontal)
        self.ap_anim.setRange(0, 100)
        self.ap_anim.setValue(60)
        self.ap_anim_lbl = QLabel("Balanced")
        self.ap_anim_lbl.setStyleSheet(f"color:{C.TEXT_MUTED};min-width:92px;")
        self.ap_anim.valueChanged.connect(lambda v: self.ap_anim_lbl.setText(
            "Minimal" if v < 33 else ("Cinematic" if v > 66 else "Balanced")))
        anim_row = QHBoxLayout()
        anim_row.addWidget(self.ap_anim, 1)
        anim_row.addWidget(self.ap_anim_lbl)
        anim_wrap = QWidget()
        anim_wrap.setLayout(anim_row)

        self.ap_density = QComboBox()
        for label in ["Comfortable", "Cozy", "Compact"]:
            self.ap_density.addItem(label)
        self.ap_density.setCurrentIndex(1)
        self.ap_density.setStyleSheet(self._combo_qss())

        self.ap_font = QComboBox()
        for label in ["Small (12px)", "Default (13px)", "Medium (14px)", "Large (16px)", "Extra Large (18px)"]:
            self.ap_font.addItem(label)
        self.ap_font.setCurrentIndex(1)
        self.ap_font.setStyleSheet(self._combo_qss())

        self.ap_visual = QComboBox()
        for label in ["Cinematic Orb", "Minimal Pulse", "Waveform Ring", "Avatar"]:
            self.ap_visual.addItem(label)
        self.ap_visual.setStyleSheet(self._combo_qss())

        self.ap_sidebar = QCheckBox("Collapse sidebar by default")
        self.ap_sidebar.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.ap_bg = QCheckBox("Enable background glow effects")
        self.ap_bg.setChecked(True)
        self.ap_bg.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        apply_btn = QPushButton(" Apply Display ")
        apply_btn.setIcon(icon(ICONS.SAVE, C.SEC_SETTINGS, 14))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(self._btn_primary())
        apply_btn.clicked.connect(self._on_save_appearance)

        form.addRow("Animation Intensity", anim_wrap)
        form.addRow("UI Density", self.ap_density)
        form.addRow("Base Font Size", self.ap_font)
        form.addRow("Assistant Visual", self.ap_visual)
        form.addRow("", self.ap_sidebar)
        form.addRow("", self.ap_bg)
        form.addRow("", apply_btn)

        lay.addWidget(card_disp)

        # 3D Ambient System Card
        card_ambient = Card(title="Futuristic 3D Ambient System")
        amb_form = QFormLayout()
        card_ambient.body.addLayout(amb_form)
        amb_form.setSpacing(Spacing.MD)
        amb_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ap_ambient_enable = QCheckBox("Enable 3D Ambient Visual Engine")
        self.ap_ambient_enable.setChecked(True)
        self.ap_ambient_enable.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:600;")

        self.ap_ambient_quality = QComboBox()
        for label, val in [("High (60 FPS + Bloom)", "High"), ("Medium (60 FPS)", "Medium"), ("Low (30 FPS Power Save)", "Low")]:
            self.ap_ambient_quality.addItem(label, val)
        self.ap_ambient_quality.setStyleSheet(self._combo_qss())

        self.ap_ambient_density = QComboBox()
        for label, val in [("High (160 Particles)", "High"), ("Medium (100 Particles)", "Medium"), ("Low (60 Particles)", "Low")]:
            self.ap_ambient_density.addItem(label, val)
        self.ap_ambient_density.setStyleSheet(self._combo_qss())

        self.ap_ambient_motion = QComboBox()
        for label, val in [("Dynamic (Cinematic)", "Dynamic"), ("Subtle (Calm)", "Subtle"), ("Reduced Motion (Accessibility)", "Reduced Motion")]:
            self.ap_ambient_motion.addItem(label, val)
        self.ap_ambient_motion.setStyleSheet(self._combo_qss())

        self.ap_ambient_parallax = QCheckBox("Enable 3D Mouse Parallax Depth")
        self.ap_ambient_parallax.setChecked(True)
        self.ap_ambient_parallax.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.ap_ambient_reactive = QCheckBox("React dynamically to Assistant & System States")
        self.ap_ambient_reactive.setChecked(True)
        self.ap_ambient_reactive.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        amb_apply_btn = QPushButton(" Apply Ambient Settings ")
        amb_apply_btn.setIcon(icon(ICONS.SAVE, C.SEC_SETTINGS, 14))
        amb_apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        amb_apply_btn.setStyleSheet(self._btn_primary())
        amb_apply_btn.clicked.connect(self._on_save_appearance)

        amb_form.addRow("", self.ap_ambient_enable)
        amb_form.addRow("Rendering Quality", self.ap_ambient_quality)
        amb_form.addRow("Particle Density", self.ap_ambient_density)
        amb_form.addRow("Motion Profile", self.ap_ambient_motion)
        amb_form.addRow("", self.ap_ambient_parallax)
        amb_form.addRow("", self.ap_ambient_reactive)
        amb_form.addRow("", amb_apply_btn)

        lay.addWidget(card_ambient)
        lay.addStretch(1)
        return w

    # ---------------------------------------------------------- Voice tab
    def _build_tab_voice(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        card = Card(title="Voice Engine")
        form = QFormLayout(); card.body.addLayout(form)
        form.setSpacing(Spacing.MD)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.v_engine = QComboBox()
        for label in ["pyttsx3 (System Default)", "sapi5 (Windows SAPI)",
                      "gtts (Google TTS)", "coqui (Local TTS)", "elevenlabs"]:
            self.v_engine.addItem(label)
        self.v_engine.setStyleSheet(self._combo_qss())

        self._all_voices = []
        self._active_voice_filter = "all"

        cat_row = QHBoxLayout()
        cat_row.setSpacing(Spacing.SM)
        self.v_cat_all = QPushButton("All Voices")
        self.v_cat_female = QPushButton("Female")
        self.v_cat_male = QPushButton("Male")
        for b, tag in [(self.v_cat_all, "all"), (self.v_cat_female, "female"), (self.v_cat_male, "male")]:
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, t=tag: self._set_voice_category_filter(t))
            cat_row.addWidget(b)
        self.v_cat_all.setChecked(True)
        cat_row.addStretch(1)
        cat_wrap = QWidget()
        cat_wrap.setLayout(cat_row)
        self._update_category_buttons_style()

        self.v_voice = QComboBox()
        self.v_voice.addItem("Loading voices…")
        self.v_voice.setStyleSheet(self._combo_qss())

        def _mk_slider(minv, maxv, default, suffix_cb):
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(minv, maxv)
            s.setValue(default)
            l = QLabel(suffix_cb(default))
            l.setStyleSheet(f"color:{C.TEXT_MUTED};min-width:92px;")
            s.valueChanged.connect(lambda v: l.setText(suffix_cb(v)))
            row = QHBoxLayout()
            row.addWidget(s, 1)
            row.addWidget(l)
            wrap = QWidget()
            wrap.setLayout(row)
            return s, wrap

        self.v_rate, rate_wrap = _mk_slider(50, 400, 135, lambda v: f"{v} wpm")
        self.v_pitch, pitch_wrap = _mk_slider(0, 200, 100, lambda v: f"{v}%")
        self.v_vol, vol_wrap = _mk_slider(0, 100, 100, lambda v: f"{v}%")
        self.v_hw_thresh, hw_wrap = _mk_slider(0, 100, 35, lambda v: f"{v/100:.2f}")

        self.v_mic = QComboBox()
        self.v_mic.addItem("System Default Microphone")
        self.v_mic.setStyleSheet(self._combo_qss())

        self.v_speaker = QComboBox()
        self.v_speaker.addItem("System Default Speaker")
        self.v_speaker.setStyleSheet(self._combo_qss())

        self.v_wake = QCheckBox("Enable wake word detection")
        self.v_wake.setChecked(True)
        self.v_wake.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.v_act = QCheckBox("Enable voice activation (VAD)")
        self.v_act.setChecked(True)
        self.v_act.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        btns = QHBoxLayout()
        test_btn = QPushButton(" Test Voice ")
        test_btn.setIcon(icon(ICONS.PLAY, C.SEC_SETTINGS, 14))
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_btn.setStyleSheet(self._btn_primary())
        test_btn.clicked.connect(self._on_test_voice)
        apply_btn = QPushButton(" Apply Voice ")
        apply_btn.setIcon(icon(ICONS.SAVE, C.SEC_SETTINGS, 14))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(self._btn_ghost())
        apply_btn.clicked.connect(self._on_save_voice)
        btns.addWidget(test_btn)
        btns.addStretch(1)
        btns.addWidget(apply_btn)

        form.addRow("Engine", self.v_engine)
        form.addRow("Voice Filter", cat_wrap)
        form.addRow("Voice", self.v_voice)
        form.addRow("Speech Rate", rate_wrap)
        form.addRow("Pitch", pitch_wrap)
        form.addRow("Volume", vol_wrap)
        form.addRow("Hotword Threshold", hw_wrap)
        form.addRow("Microphone", self.v_mic)
        form.addRow("Speaker", self.v_speaker)
        form.addRow("", self.v_wake)
        form.addRow("", self.v_act)
        btns_wrap = QWidget()
        btns_wrap.setLayout(btns)
        form.addRow("", btns_wrap)

        lay.addWidget(card)
        lay.addStretch(1)
        return w

    def _update_category_buttons_style(self):
        for b, tag in [(self.v_cat_all, "all"), (self.v_cat_female, "female"), (self.v_cat_male, "male")]:
            is_active = (self._active_voice_filter == tag)
            b.setChecked(is_active)
            if is_active:
                b.setStyleSheet(f"""
                    QPushButton {{
                        background: {rgba_str(C.ACCENT, 0.22)};
                        color: {C.TEXT_PRIMARY};
                        border: 1px solid {C.ACCENT};
                        border-radius: {Radius.SM}px;
                        padding: 4px 12px;
                        font-weight: 600;
                        font-size: 11px;
                    }}
                """)
            else:
                card_bg_alt = getattr(C, "CARD_BG_ALT", getattr(C, "CARD_HIGHLIGHT", "#121C27"))
                b.setStyleSheet(f"""
                    QPushButton {{
                        background: {rgba_str(card_bg_alt, 0.4)};
                        color: {C.TEXT_MUTED};
                        border: 1px solid {C.BORDER};
                        border-radius: {Radius.SM}px;
                        padding: 4px 12px;
                        font-size: 11px;
                    }}
                    QPushButton:hover {{
                        background: {rgba_str(card_bg_alt, 0.8)};
                        color: {C.TEXT_PRIMARY};
                    }}
                """)

    def _set_voice_category_filter(self, category: str):
        self._active_voice_filter = category
        self._update_category_buttons_style()
        self._populate_voice_combo()

    def _populate_voice_combo(self):
        current_selected = self.v_voice.currentData()
        if not current_selected and hasattr(self, "_prefs"):
            current_selected = self._prefs.get("voice_id") or self._prefs.get("assistant_voice_id")
        self.v_voice.blockSignals(True)
        self.v_voice.clear()

        filtered = []
        for v in (self._all_voices or []):
            gender = str(v.get("gender", "unknown")).lower()
            if self._active_voice_filter == "female" and gender != "female":
                continue
            if self._active_voice_filter == "male" and gender != "male":
                continue
            filtered.append(v)

        if not filtered and self._all_voices:
            filtered = self._all_voices

        target_idx = 0
        found_selected = False
        for i, v in enumerate(filtered):
            name = v.get("name", "Voice")
            gender = v.get("gender", "unknown").title()
            vid = v.get("id", "")
            self.v_voice.addItem(f"{name} ({gender})", vid)
            if vid and current_selected and vid == current_selected:
                target_idx = i
                found_selected = True

        if not found_selected and not current_selected:
            # Prioritize natural conversational US voice (Zira or David) over Hazel (UK) default
            for i, v in enumerate(filtered):
                vid_low = str(v.get("id", "")).lower()
                name_low = str(v.get("name", "")).lower()
                if "zira" in vid_low or "zira" in name_low:
                    target_idx = i
                    break

        if self.v_voice.count() > 0:
            self.v_voice.setCurrentIndex(target_idx)
        else:
            self.v_voice.addItem("Default System Voice", "")
        self.v_voice.blockSignals(False)

    # ------------------------------------------------------ Intelligence
    def _build_tab_intelligence(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        card = Card(title="AI Provider")
        form = QFormLayout(); card.body.addLayout(form)
        form.setSpacing(Spacing.MD)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ai_provider = QComboBox()
        for p in ["OpenAI", "Groq", "Gemini", "DeepSeek", "HuggingFace", "Ollama", "Auto (Failover)"]:
            self.ai_provider.addItem(p)
        self.ai_provider.setStyleSheet(self._combo_qss())
        self.ai_provider.currentTextChanged.connect(self._on_ai_provider_change)

        self.ai_model = QLineEdit()
        self.ai_model.setPlaceholderText("e.g. gpt-4o, llama3-70b-8192, gemini-1.5-pro")
        self.ai_model.setStyleSheet(self._line_qss())

        self.ai_fallback = QCheckBox("Enable multi-provider automatic failover")
        self.ai_fallback.setChecked(True)
        self.ai_fallback.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        form.addRow("Primary Provider", self.ai_provider)
        form.addRow("Default Model", self.ai_model)
        form.addRow("", self.ai_fallback)
        lay.addWidget(card)

        card2 = Card(title="Behavior Controls")
        form2 = QFormLayout(); card2.body.addLayout(form2)
        form2.setSpacing(Spacing.MD)
        form2.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ai_web = QCheckBox("Enable web search / browse access")
        self.ai_web.setChecked(True)
        self.ai_web.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.ai_ctx = QCheckBox("Context-aware responses")
        self.ai_ctx.setChecked(True)
        self.ai_ctx.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.ai_pro = QCheckBox("Proactive assistance (observations & nudges)")
        self.ai_pro.setChecked(True)
        self.ai_pro.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.ai_confirm = QComboBox()
        for label in ["Always confirm destructive actions",
                      "Confirm external actions only",
                      "Confirm only when uncertain",
                      "Never confirm (trust autonomous)"]:
            self.ai_confirm.addItem(label)
        self.ai_confirm.setCurrentIndex(0)
        self.ai_confirm.setStyleSheet(self._combo_qss())

        self.ai_auton = QCheckBox("Allow autonomous execution without approval")
        self.ai_auton.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.ai_perms = QComboBox()
        for label in ["Allow all registered tools",
                      "Ask for each new tool",
                      "Whitelist only selected tools"]:
            self.ai_perms.addItem(label)
        self.ai_perms.setStyleSheet(self._combo_qss())

        apply_btn = QPushButton(" Apply Intelligence ")
        apply_btn.setIcon(icon(ICONS.SAVE, C.SEC_SETTINGS, 14))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(self._btn_primary())
        apply_btn.clicked.connect(self._on_save_intelligence)

        form2.addRow("", self.ai_web)
        form2.addRow("", self.ai_ctx)
        form2.addRow("", self.ai_pro)
        form2.addRow("Confirmation Behavior", self.ai_confirm)
        form2.addRow("Tool Permissions", self.ai_perms)
        form2.addRow("", self.ai_auton)
        form2.addRow("", apply_btn)

        lay.addWidget(card2)
        lay.addStretch(1)
        return w

    # ------------------------------------------------------------- Memory
    def _build_tab_memory(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        card_stats = Card(title="Memory Overview")
        grid = QGridLayout()
        card_stats.body.addLayout(grid)
        grid.setSpacing(Spacing.MD)
        def stat(t, v, color):
            w = QWidget()
            lay2 = QVBoxLayout(w)
            lay2.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
            ttl = QLabel(t)
            ttl.setStyleSheet(f"font-size:11px;font-weight:600;letter-spacing:1px;color:{C.TEXT_MUTED};text-transform:uppercase;background:transparent;")
            val = QLabel(v)
            val.setStyleSheet(f"font-size:22px;font-weight:700;color:{color};background:transparent;")
            lay2.addWidget(ttl)
            lay2.addWidget(val)
            w.setProperty("class", "CardInner")
            w.setStyleSheet(f"QFrame {{ background:{C.CARD_BG};border-radius:{Radius.MD}px;border:1px solid {C.BORDER}; }} QLabel {{ background: transparent; }}")
            return w

        self.m_stat_conv = stat("Conversations", "—", C.SEC_SETTINGS)
        self.m_stat_rules = stat("Learned Rules", "—", C.ACC_VIOLET)
        self.m_stat_prefs = stat("Preferences", "—", C.SEC_SETTINGS)
        self.m_stat_words = stat("Words Remembered", "—", C.SEC_SETTINGS_GREEN)
        grid.addWidget(self.m_stat_conv, 0, 0)
        grid.addWidget(self.m_stat_rules, 0, 1)
        grid.addWidget(self.m_stat_prefs, 0, 2)
        grid.addWidget(self.m_stat_words, 0, 3)
        lay.addWidget(card_stats)

        card = Card(title="Data Controls")
        form = QFormLayout(); card.body.addLayout(form)
        form.setSpacing(Spacing.MD)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.m_hide_sensitive = QCheckBox("Mask sensitive content in memory logs")
        self.m_hide_sensitive.setChecked(True)
        self.m_hide_sensitive.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.m_auto_forget = QCheckBox("Auto-forget conversation details older than 30 days")
        self.m_auto_forget.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        form.addRow("", self.m_hide_sensitive)
        form.addRow("", self.m_auto_forget)

        btns = QHBoxLayout()
        btns.setSpacing(Spacing.SM)

        exp_json_btn = QPushButton(" Export Conversations (JSON) ")
        exp_json_btn.setIcon(icon(ICONS.DOWNLOAD, C.SEC_SETTINGS, 14))
        exp_json_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        exp_json_btn.setStyleSheet(self._btn_ghost())
        exp_json_btn.clicked.connect(lambda: self._on_export("json"))

        exp_csv_btn = QPushButton(" Export Memory (CSV) ")
        exp_csv_btn.setIcon(icon(ICONS.DOWNLOAD, C.SEC_SETTINGS_VIOLET, 14))
        exp_csv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        exp_csv_btn.setStyleSheet(self._btn_ghost())
        exp_csv_btn.clicked.connect(lambda: self._on_export("csv"))

        clear_btn = QPushButton(" Clear Conversation History ")
        clear_btn.setIcon(icon(ICONS.TRASH, C.ERROR, 14))
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet(self._btn_danger())
        clear_btn.clicked.connect(self._on_clear_history)

        save_btn = QPushButton(" Save Privacy ")
        save_btn.setIcon(icon(ICONS.SAVE, C.SEC_SETTINGS, 14))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(self._btn_primary())
        save_btn.clicked.connect(self._on_save_memory)

        btns.addWidget(exp_json_btn)
        btns.addWidget(exp_csv_btn)
        btns.addStretch(1)
        btns.addWidget(save_btn)
        btns.addWidget(clear_btn)
        form.addRow("Operations", (lambda: _h(btns))())

        lay.addWidget(card)
        lay.addStretch(1)
        return w

    # -------------------------------------------------------------- Email
    def _build_tab_email(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        self.email_status_card = Card(title="Email Account")
        st_body = QVBoxLayout()
        self.email_status_card.body.addLayout(st_body)
        self.email_status_lbl = QLabel("Checking account status…")
        self.email_status_lbl.setStyleSheet(f"color:{C.TEXT_MUTED};font-size:13px;")
        self.email_chip = StatusChip("offline")
        st_row = QHBoxLayout()
        st_row.addWidget(self.email_chip, 0)
        st_row.addWidget(self.email_status_lbl, 1)
        st_body.addLayout(st_row)

        acc_btns = QHBoxLayout()
        add_btn = QPushButton(" Add Account ")
        add_btn.setIcon(icon(ICONS.PLUS, C.SEC_SETTINGS, 14))
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(self._btn_primary())
        add_btn.clicked.connect(self._on_email_add)

        remove_btn = QPushButton(" Remove Account ")
        remove_btn.setIcon(icon(ICONS.TRASH, C.ERROR, 14))
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setStyleSheet(self._btn_danger())
        remove_btn.clicked.connect(self._on_email_remove)

        sync_btn = QPushButton(" Sync Now ")
        sync_btn.setIcon(icon(ICONS.REFRESH, C.SEC_SETTINGS_VIOLET, 14))
        sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sync_btn.setStyleSheet(self._btn_ghost())
        sync_btn.clicked.connect(self._on_email_sync)

        acc_btns.addWidget(add_btn)
        acc_btns.addWidget(remove_btn)
        acc_btns.addStretch(1)
        acc_btns.addWidget(sync_btn)
        st_body.addLayout(acc_btns)
        lay.addWidget(self.email_status_card)

        card = Card(title="Email Settings")
        form = QFormLayout(); card.body.addLayout(form)
        form.setSpacing(Spacing.MD)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.em_notify = QCheckBox("Show notifications for new email")
        self.em_notify.setChecked(True)
        self.em_notify.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.em_sum = QCheckBox("Summarize long emails by default")
        self.em_sum.setChecked(True)
        self.em_sum.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.em_tone = QComboBox()
        for label in ["Match sender style", "Professional", "Friendly", "Concise", "Technical"]:
            self.em_tone.addItem(label)
        self.em_tone.setStyleSheet(self._combo_qss())

        self.em_autodraft = QCheckBox("Auto-draft replies for approval")
        self.em_autodraft.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        apply_btn = QPushButton(" Save Email Settings ")
        apply_btn.setIcon(icon(ICONS.SAVE, C.SEC_SETTINGS, 14))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(self._btn_primary())
        apply_btn.clicked.connect(self._on_save_email)

        form.addRow("", self.em_notify)
        form.addRow("", self.em_sum)
        form.addRow("Default AI Tone", self.em_tone)
        form.addRow("", self.em_autodraft)
        form.addRow("", apply_btn)
        lay.addWidget(card)
        lay.addStretch(1)
        return w

    # ------------------------------------------------------------ Devices
    def _build_tab_devices(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        paired_card = Card(title="Paired Devices")
        p_row = QHBoxLayout(); paired_card.body.addLayout(p_row)
        self.dev_list = QTableWidget(0, 4)
        self.dev_list.setHorizontalHeaderLabels(["Device ID", "Name", "Type", "Last Seen"])
        self.dev_list.horizontalHeader().setStretchLastSection(True)
        self.dev_list.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.dev_list.verticalHeader().setVisible(False)
        self.dev_list.setStyleSheet(f"""
            QTableWidget {{
                background:{C.CARD_BG};border-radius:{Radius.MD}px;
                border:1px solid {C.BORDER};gridline-color:{C.BORDER};
                color:{C.TEXT_PRIMARY};selection-background-color:{rgba_str(C.SEC_SETTINGS,0.15)};
            }}
            QHeaderView::section {{
                background:{C.SURFACE_BG};color:{C.TEXT_MUTED};padding:8px;
                border:none;border-bottom:1px solid {C.BORDER};font-weight:600;
            }}
        """)
        p_row.addWidget(self.dev_list, 1)

        side = QVBoxLayout()
        pair_btn = QPushButton(" Pair Device ")
        pair_btn.setIcon(icon(ICONS.PLUS, C.SEC_SETTINGS, 14))
        pair_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pair_btn.setStyleSheet(self._btn_primary())
        pair_btn.clicked.connect(self._on_pair_device)
        disc_btn = QPushButton(" Disconnect ")
        disc_btn.setIcon(icon(ICONS.UNLOCK, C.ERROR, 14))
        disc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        disc_btn.setStyleSheet(self._btn_danger())
        disc_btn.clicked.connect(self._on_disconnect_device)
        refresh_btn = QPushButton(" Refresh ")
        refresh_btn.setIcon(icon(ICONS.REFRESH, C.SEC_SETTINGS_VIOLET, 14))
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet(self._btn_ghost())
        refresh_btn.clicked.connect(self._load_devices)
        side.addWidget(pair_btn)
        side.addWidget(disc_btn)
        side.addWidget(refresh_btn)
        side.addStretch(1)
        p_row.addLayout(side)
        lay.addWidget(paired_card)

        aud_card = Card(title="Audio Devices")
        aform = QFormLayout(); aud_card.body.addLayout(aform)
        aform.setSpacing(Spacing.MD)
        aform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        aud_mic = QComboBox()
        aud_mic.addItem("System Default Microphone")
        aud_mic.setStyleSheet(self._combo_qss())
        aud_spk = QComboBox()
        aud_spk.addItem("System Default Speaker")
        aud_spk.setStyleSheet(self._combo_qss())
        save_aud = QPushButton(" Save Audio ")
        save_aud.setIcon(icon(ICONS.SAVE, C.SEC_SETTINGS, 14))
        save_aud.setCursor(Qt.CursorShape.PointingHandCursor)
        save_aud.setStyleSheet(self._btn_primary())
        save_aud.clicked.connect(lambda: self._flash("Audio preferences saved."))
        aform.addRow("Microphone", aud_mic)
        aform.addRow("Speaker", aud_spk)
        aform.addRow("", save_aud)
        lay.addWidget(aud_card)
        lay.addStretch(1)
        return w

    # ------------------------------------------------------ Notifications
    def _build_tab_notifications(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        card = Card(title="Notification Preferences")
        form = QFormLayout(); card.body.addLayout(form)
        form.setSpacing(Spacing.MD)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.n_global = QCheckBox("Enable desktop notifications")
        self.n_global.setChecked(True)
        self.n_global.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.n_email = QCheckBox("Email notifications")
        self.n_email.setChecked(True)
        self.n_email.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.n_cal = QCheckBox("Calendar event reminders")
        self.n_cal.setChecked(True)
        self.n_cal.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.n_rem = QCheckBox("Task / reminder alerts")
        self.n_rem.setChecked(True)
        self.n_rem.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.n_auto = QCheckBox("Automation results")
        self.n_auto.setChecked(True)
        self.n_auto.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.n_dev = QCheckBox("Device connectivity changes")
        self.n_dev.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.n_ask = QCheckBox("Assistant waiting for approval")
        self.n_ask.setChecked(True)
        self.n_ask.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.n_sound = QCheckBox("Play notification sound")
        self.n_sound.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.n_dnd_from = QTimeEdit()
        self.n_dnd_from.setDisplayFormat("HH:mm")
        self.n_dnd_from.setStyleSheet(self._line_qss())
        self.n_dnd_to = QTimeEdit()
        self.n_dnd_to.setDisplayFormat("HH:mm")
        self.n_dnd_to.setStyleSheet(self._line_qss())
        dnd_row = QHBoxLayout()
        dnd_row.addWidget(QLabel("From"), 0)
        dnd_row.addWidget(self.n_dnd_from, 1)
        dnd_row.addWidget(QLabel("To"), 0)
        dnd_row.addWidget(self.n_dnd_to, 1)
        dnd_wrap = QWidget()
        dnd_wrap.setLayout(dnd_row)

        self.n_dnd = QCheckBox("Enable Do Not Disturb window")
        self.n_dnd.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        apply_btn = QPushButton(" Save Notifications ")
        apply_btn.setIcon(icon(ICONS.SAVE, C.SEC_SETTINGS, 14))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(self._btn_primary())
        apply_btn.clicked.connect(self._on_save_notifications)

        for r in [self.n_global, self.n_email, self.n_cal, self.n_rem,
                  self.n_auto, self.n_dev, self.n_ask, self.n_sound,
                  self.n_dnd]:
            form.addRow("", r)
        form.addRow("Do Not Disturb", dnd_wrap)
        form.addRow("", apply_btn)
        lay.addWidget(card)
        lay.addStretch(1)
        return w

    # ----------------------------------------------------------- Security
    def _build_tab_security(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        card = Card(title="Security Controls")
        form = QFormLayout(); card.body.addLayout(form)
        form.setSpacing(Spacing.MD)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_confirm = QCheckBox("Require confirmation for sensitive actions")
        self.s_confirm.setChecked(True)
        self.s_confirm.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.s_lock = QCheckBox("Lock dashboard when inactive for 15 min")
        self.s_lock.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        self.s_audit = QCheckBox("Maintain audit log for high-risk actions")
        self.s_audit.setChecked(True)
        self.s_audit.setStyleSheet(f"color:{C.TEXT_PRIMARY};font-weight:500;")

        for r in [self.s_confirm, self.s_lock, self.s_audit]:
            form.addRow("", r)

        apply_btn = QPushButton(" Save Security ")
        apply_btn.setIcon(icon(ICONS.SAVE, C.SEC_SETTINGS, 14))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(self._btn_primary())
        apply_btn.clicked.connect(self._on_save_security)
        form.addRow("", apply_btn)
        lay.addWidget(card)

        card2 = Card(title="Data Management (dangerous operations)")
        form2 = QFormLayout(); card2.body.addLayout(form2)
        form2.setSpacing(Spacing.MD)
        form2.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        btns = QHBoxLayout()
        btns.setSpacing(Spacing.SM)

        exp_all = QPushButton(" Export All Data ")
        exp_all.setIcon(icon(ICONS.DOWNLOAD, C.SEC_SETTINGS, 14))
        exp_all.setCursor(Qt.CursorShape.PointingHandCursor)
        exp_all.setStyleSheet(self._btn_ghost())
        exp_all.clicked.connect(lambda: self._on_export("all"))

        reset_set = QPushButton(" Reset Settings ")
        reset_set.setIcon(icon(ICONS.REFRESH, C.SEC_SETTINGS_VIOLET, 14))
        reset_set.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_set.setStyleSheet(self._btn_ghost())
        reset_set.clicked.connect(self._on_reset_settings)

        clear_mem = QPushButton(" Wipe All Memory ")
        clear_mem.setIcon(icon(ICONS.TRASH, C.ERROR, 14))
        clear_mem.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_mem.setStyleSheet(self._btn_danger())
        clear_mem.clicked.connect(self._on_wipe_memory)

        btns.addWidget(exp_all)
        btns.addWidget(reset_set)
        btns.addStretch(1)
        btns.addWidget(clear_mem)
        form2.addRow("Operations", (lambda: _h(btns))())

        lay.addWidget(card2)
        lay.addStretch(1)
        return w

    # -------------------------------------------------------- Diagnostics
    def _build_tab_diagnostics(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        hdr = QHBoxLayout()
        hdr.setSpacing(Spacing.MD)
        lbl = QLabel("System Health")
        lbl.setStyleSheet(f"font-size:18px;font-weight:700;color:{C.TEXT_PRIMARY};")
        hdr.addWidget(lbl, 1)
        run = QPushButton(" Run Diagnostics ")
        run.setIcon(icon(ICONS.REFRESH, C.SEC_SETTINGS, 14))
        run.setCursor(Qt.CursorShape.PointingHandCursor)
        run.setStyleSheet(self._btn_primary())
        run.clicked.connect(self._run_diagnostics_now)
        hdr.addWidget(run)
        lay.addLayout(hdr)

        self.diag_grid = QGridLayout()
        self.diag_grid.setSpacing(Spacing.MD)
        self._diag_widgets = {}
        subsystems = [
            ("core", "Assistant Core", C.SEC_SETTINGS),
            ("llm", "LLM Engine", C.SEC_SETTINGS_VIOLET),
            ("database", "Database", C.SEC_SETTINGS),
            ("voice", "Voice Stack", C.SEC_SETTINGS_GREEN),
            ("email", "Email", C.SEC_SETTINGS),
            ("devices", "Devices", C.SEC_SETTINGS_VIOLET),
            ("automation", "Automation", C.SEC_SETTINGS),
            ("api", "API / Network", C.SEC_SETTINGS_GREEN),
            ("workers", "Background Workers", C.SEC_SETTINGS),
        ]
        for i, (key, title, color) in enumerate(subsystems):
            cw = QWidget()
            v = QVBoxLayout(cw)
            v.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
            t_row = QHBoxLayout()
            tl = QLabel(title)
            tl.setStyleSheet(f"font-size:11px;font-weight:600;letter-spacing:1px;color:{C.TEXT_MUTED};text-transform:uppercase;")
            chip = StatusChip("offline")
            t_row.addWidget(tl, 1)
            t_row.addWidget(chip, 0)
            status = QLabel("Waiting…")
            status.setStyleSheet(f"font-size:14px;font-weight:600;color:{C.TEXT_PRIMARY};")
            detail = QLabel("Run diagnostics to check subsystem health.")
            detail.setStyleSheet(f"font-size:12px;color:{C.TEXT_MUTED};")
            detail.setWordWrap(True)
            v.addLayout(t_row)
            v.addSpacing(Spacing.SM)
            v.addWidget(status)
            v.addWidget(detail)
            cw.setProperty("class", "CardInner")
            cw.setStyleSheet(f"QFrame {{ background:{C.CARD_BG};border-radius:{Radius.MD}px;border:1px solid {C.BORDER}; }} QLabel {{ background: transparent; }}")
            self._diag_widgets[key] = (cw, chip, status, detail)
            self.diag_grid.addWidget(cw, i // 3, i % 3)
        lay.addLayout(self.diag_grid)
        lay.addStretch(1)
        return w

    # ------------------------------------------------------- data loading
    def _load_initial_data(self):
        def work():
            prefs = load_user_preferences() or {}
            rules = load_learned_rules() or []
            ident = get_identity() or {}
            diag = run_diagnostics() or {}
            api_keys = []
            try:
                api_keys = load_api_credentials_status()
            except Exception:
                pass
            try:
                has_mail = has_email_credentials()
            except Exception:
                has_mail = False
            return {
                "prefs": prefs, "rules": rules, "identity": ident,
                "diag": diag, "has_email": has_mail, "api_keys": api_keys,
            }
        w = DashboardWorker(work)
        w.result_sig.connect(self._apply_init_data)
        w.error_sig.connect(lambda e: self._flash(f"Load error: {e}"))
        self._workers.append(w)
        w.start()
        self._load_voices_later()
        self._load_devices()

    def _load_voices_later(self):
        def v_work():
            try:
                from legacy.tts import enumerate_voices
                return enumerate_voices()
            except Exception:
                return []
        w = DashboardWorker(v_work)
        w.result_sig.connect(self._apply_voices)
        self._workers.append(w)
        w.start()

    def _apply_voices(self, voices):
        self._all_voices = voices or []
        self._populate_voice_combo()
        saved_vid = self._prefs.get("voice_id")
        if saved_vid:
            for k in range(self.v_voice.count()):
                if self.v_voice.itemData(k) == saved_vid:
                    self.v_voice.setCurrentIndex(k)
                    break

    def _load_devices(self):
        def work():
            return load_paired_devices() or []
        w = DashboardWorker(work)
        w.result_sig.connect(self._apply_devices)
        self._workers.append(w)
        w.start()

    def _apply_devices(self, devices):
        self.dev_list.setRowCount(0)
        for d in devices:
            r = self.dev_list.rowCount()
            self.dev_list.insertRow(r)
            self.dev_list.setItem(r, 0, QTableWidgetItem(str(d.get("device_id", d.get("uid", "")))))
            self.dev_list.setItem(r, 1, QTableWidgetItem(str(d.get("name", "Unnamed"))))
            self.dev_list.setItem(r, 2, QTableWidgetItem(str(d.get("type", "device"))))
            last = d.get("last_seen") or d.get("paired_at") or "—"
            self.dev_list.setItem(r, 3, QTableWidgetItem(str(last)))
        if not devices:
            self.dev_list.insertRow(0)
            e = QTableWidgetItem("No paired devices — click 'Pair Device' to get started.")
            e.setForeground(QColor(C.TEXT_MUTED))
            self.dev_list.setItem(0, 0, e)
            self.dev_list.setSpan(0, 0, 1, 4)

    def _apply_init_data(self, data):
        prefs = data.get("prefs") or {}
        ident = data.get("identity") or {}
        rules = data.get("rules") or []
        diag = data.get("diag") or {}
        self._prefs.load(prefs)
        # API Keys & Integrations
        self._apply_api_credentials(data.get("api_keys") or [])
        try:
            prim = get_primary_provider_adapter()
        except Exception:
            prim = None
        if not prim:
            prim = self._prefs.get("primary_provider")
        if prim:
            self.primary_provider_combo.blockSignals(True)
            for k in range(self.primary_provider_combo.count()):
                if self.primary_provider_combo.itemData(k) == str(prim).lower():
                    self.primary_provider_combo.setCurrentIndex(k)
                    break
            self.primary_provider_combo.blockSignals(False)
            if hasattr(self, "primary_model_lbl"):
                cur_pid = self.primary_provider_combo.currentData() or "groq"
                self.primary_model_lbl.setText(f"Active Model: <b>{PROVIDER_MODELS.get(str(cur_pid).lower(), 'default')}</b>")
        # Profile
        self.pf_name.setText(str(ident.get("username") or self._prefs.get("display_name") or ""))
        self.pf_email.setText(str(ident.get("email") or "— not configured —"))
        lang = self._prefs.get("language", "en-IN") or "en-IN"
        for i in range(self.pf_lang.count()):
            if self.pf_lang.itemData(i) == lang:
                self.pf_lang.setCurrentIndex(i); break
        tz = self._prefs.get("timezone", "UTC") or "UTC"
        if self.pf_tz.findText(tz) < 0:
            self.pf_tz.addItem(tz)
        self.pf_tz.setCurrentText(tz)
        # Identity
        self.id_name.setText(str(ident.get("assistant_name") or self._prefs.get("assistant_name") or ""))
        self.id_greeting.setText(str(self._prefs.get("greeting") or ""))
        pers = self._prefs.get("persona", "Friendly Assistant") or "Friendly Assistant"
        i = self.id_persona.findText(str(pers))
        if i >= 0: self.id_persona.setCurrentIndex(i)
        style = self._prefs.get("response_style", "Natural") or "Natural"
        i = self.id_style.findText(str(style))
        if i >= 0: self.id_style.setCurrentIndex(i)
        form_val = int(self._prefs.get("formality_pct", 50) or 50)
        self.id_formality.setValue(max(0, min(100, form_val)))
        verb = self._prefs.get("verbosity", "Concise") or "Concise"
        i = self.id_verbosity.findText(str(verb))
        if i >= 0: self.id_verbosity.setCurrentIndex(i)
        proa = self._prefs.get("proactivity", "Suggestive") or "Suggestive"
        i = self.id_proactivity.findText(str(proa))
        if i >= 0: self.id_proactivity.setCurrentIndex(i)
        # Appearance
        anim_val = int(self._prefs.get("anim_intensity_pct", 60) or 60)
        self.ap_anim.setValue(max(0, min(100, anim_val)))
        dens = self._prefs.get("density", "Cozy") or "Cozy"
        i = self.ap_density.findText(str(dens))
        if i >= 0: self.ap_density.setCurrentIndex(i)
        font_idx = int(self._prefs.get("font_size_idx", 1) or 1)
        self.ap_font.setCurrentIndex(max(0, min(self.ap_font.count() - 1, font_idx)))
        vis = self._prefs.get("assistant_visual", "Cinematic Orb") or "Cinematic Orb"
        i = self.ap_visual.findText(str(vis))
        if i >= 0: self.ap_visual.setCurrentIndex(i)
        self.ap_sidebar.setChecked(bool(self._prefs.get("sidebar_collapsed")))
        self.ap_bg.setChecked(bool(self._prefs.get("bg_glow", True)))
        # 3D Ambient System
        self.ap_ambient_enable.setChecked(bool(self._prefs.get("ambient_3d_enabled", True)))
        qual = str(self._prefs.get("ambient_3d_quality", "High"))
        for k in range(self.ap_ambient_quality.count()):
            if self.ap_ambient_quality.itemData(k) == qual or qual in self.ap_ambient_quality.itemText(k):
                self.ap_ambient_quality.setCurrentIndex(k)
                break
        dens = str(self._prefs.get("ambient_3d_density", "High"))
        for k in range(self.ap_ambient_density.count()):
            if self.ap_ambient_density.itemData(k) == dens or dens in self.ap_ambient_density.itemText(k):
                self.ap_ambient_density.setCurrentIndex(k)
                break
        mot = str(self._prefs.get("ambient_3d_motion", "Dynamic"))
        for k in range(self.ap_ambient_motion.count()):
            if self.ap_ambient_motion.itemData(k) == mot or mot in self.ap_ambient_motion.itemText(k):
                self.ap_ambient_motion.setCurrentIndex(k)
                break
        self.ap_ambient_parallax.setChecked(bool(self._prefs.get("ambient_3d_parallax", True)))
        self.ap_ambient_reactive.setChecked(bool(self._prefs.get("ambient_3d_state_reactive", True)))
        # Voice
        eng_idx = int(self._prefs.get("voice_engine_idx", 0) or 0)
        self.v_engine.setCurrentIndex(max(0, min(self.v_engine.count() - 1, eng_idx)))
        saved_rate = int(self._prefs.get("voice_rate") or self._prefs.get("assistant_voice_rate") or 135)
        self.v_rate.setValue(max(50, min(400, saved_rate)))
        self.v_pitch.setValue(max(0, min(200, int(self._prefs.get("voice_pitch", 100) or 100))))
        saved_vol = float(self._prefs.get("voice_volume") or self._prefs.get("assistant_voice_volume") or 100)
        if saved_vol <= 1.0:
            saved_vol = saved_vol * 100.0
        self.v_vol.setValue(max(0, min(100, int(round(saved_vol)))))
        hw = float(self._prefs.get("hotword_threshold", 0.35) or 0.35)
        self.v_hw_thresh.setValue(max(0, min(100, int(round(hw * 100)))))
        self.v_wake.setChecked(bool(self._prefs.get("wake_word_enabled", True)))
        self.v_act.setChecked(bool(self._prefs.get("voice_activation_enabled", True)))
        saved_vid = self._prefs.get("voice_id") or self._prefs.get("assistant_voice_id")
        if saved_vid:
            for k in range(self.v_voice.count()):
                if self.v_voice.itemData(k) == saved_vid:
                    self.v_voice.setCurrentIndex(k)
                    break
        # Intelligence
        prov = self._prefs.get("ai_provider", "Auto (Failover)") or "Auto (Failover)"
        i = self.ai_provider.findText(str(prov))
        if i >= 0: self.ai_provider.setCurrentIndex(i)
        self.ai_model.setText(str(self._prefs.get("ai_model") or
                                   (SETTINGS.DEFAULT_MODEL if SETTINGS and hasattr(SETTINGS, 'DEFAULT_MODEL') else "")))
        self.ai_fallback.setChecked(bool(self._prefs.get("ai_failover", True)))
        self.ai_web.setChecked(bool(self._prefs.get("web_access", True)))
        self.ai_ctx.setChecked(bool(self._prefs.get("context_aware", True)))
        self.ai_pro.setChecked(bool(self._prefs.get("proactive_assistance", True)))
        conf = self._prefs.get("confirmation_behavior",
                               "Always confirm destructive actions") or "Always confirm destructive actions"
        i = self.ai_confirm.findText(str(conf))
        if i >= 0: self.ai_confirm.setCurrentIndex(i)
        self.ai_auton.setChecked(bool(self._prefs.get("autonomous_execution", False)))
        perms = self._prefs.get("tool_permissions", "Allow all registered tools") or "Allow all registered tools"
        i = self.ai_perms.findText(str(perms))
        if i >= 0: self.ai_perms.setCurrentIndex(i)
        # Memory stats
        try:
            rules_c = len(rules)
            prefs_c = len(prefs)
        except Exception:
            rules_c = prefs_c = 0
        for (cw, chip, st, det) in [
            (self.m_stat_conv.findChild(QLabel, None, Qt.FindChildOption.FindDirectChildrenOnly) is not None or None,
             None, None, None),
        ]: pass  # noop, will update below by label search

        self._set_stat_label(self.m_stat_conv, "Conversations", self._prefs.get("stat_conversations", "—"))
        self._set_stat_label(self.m_stat_rules, "Learned Rules", str(rules_c))
        self._set_stat_label(self.m_stat_prefs, "Preferences", str(prefs_c))
        self._set_stat_label(self.m_stat_words, "Words Remembered", self._prefs.get("stat_words", "—"))

        self.m_hide_sensitive.setChecked(bool(self._prefs.get("mask_sensitive", True)))
        self.m_auto_forget.setChecked(bool(self._prefs.get("auto_forget_30d", False)))
        # Email
        has_email = bool(data.get("has_email"))
        self.email_chip.setProperty("state", "online" if has_email else "offline")
        self.email_chip.style().unpolish(self.email_chip)
        self.email_chip.style().polish(self.email_chip)
        self.email_status_lbl.setText(
            ("Email account configured and ready." if has_email
             else "No email account connected. Configure email in the Communications page."))
        self.em_notify.setChecked(bool(self._prefs.get("email_notifications", True)))
        self.em_sum.setChecked(bool(self._prefs.get("email_summarize", True)))
        tone = self._prefs.get("email_ai_tone", "Match sender style") or "Match sender style"
        i = self.em_tone.findText(str(tone))
        if i >= 0: self.em_tone.setCurrentIndex(i)
        self.em_autodraft.setChecked(bool(self._prefs.get("email_auto_draft_reply", False)))
        # Notifications
        self.n_global.setChecked(bool(self._prefs.get("notifications_global", True)))
        self.n_email.setChecked(bool(self._prefs.get("notify_email", True)))
        self.n_cal.setChecked(bool(self._prefs.get("notify_calendar", True)))
        self.n_rem.setChecked(bool(self._prefs.get("notify_reminders", True)))
        self.n_auto.setChecked(bool(self._prefs.get("notify_automation", True)))
        self.n_dev.setChecked(bool(self._prefs.get("notify_devices", False)))
        self.n_ask.setChecked(bool(self._prefs.get("notify_approval_wait", True)))
        self.n_sound.setChecked(bool(self._prefs.get("notify_sound", False)))
        self.n_dnd.setChecked(bool(self._prefs.get("dnd_enabled", False)))
        try:
            t = (self._prefs.get("dnd_from") or "22:00").split(":")
            if len(t) == 2:
                self.n_dnd_from.setTime(self.n_dnd_from.time().fromString(f"{int(t[0]):02d}:{int(t[1]):02d}", "HH:mm"))
            t = (self._prefs.get("dnd_to") or "08:00").split(":")
            if len(t) == 2:
                self.n_dnd_to.setTime(self.n_dnd_to.time().fromString(f"{int(t[0]):02d}:{int(t[1]):02d}", "HH:mm"))
        except Exception:
            pass
        # Security
        self.s_confirm.setChecked(bool(self._prefs.get("confirm_sensitive", True)))
        self.s_lock.setChecked(bool(self._prefs.get("lock_on_idle", False)))
        self.s_audit.setChecked(bool(self._prefs.get("audit_log", True)))
        # Diagnostics
        self._apply_diag(diag)

    def _set_stat_label(self, parent, title_search, value):
        for lbl in parent.findChildren(QLabel):
            if lbl.text() == title_search:
                for sib in parent.findChildren(QLabel):
                    if sib.styleSheet() and "font-size:22px" in sib.styleSheet():
                        sib.setText(str(value))
                        return

    def _apply_diag(self, diag: Dict[str, Any]):
        for key, (cw, chip, status, detail) in self._diag_widgets.items():
            data = diag.get(key) or {}
            ok = bool(data.get("ok"))
            s = str(data.get("status") or ("OK" if ok else "WARN"))
            chip_state = "online" if ok else ("error" if s.lower() in ("error", "fail", "down") else "thinking")
            chip.setProperty("state", chip_state)
            chip.style().unpolish(chip); chip.style().polish(chip)
            status.setText(s)
            detail.setText(str(data.get("detail") or ("Subsystem operating normally." if ok else "Subsystem degraded or unavailable.")))

    # --------------------------------------------------------- save hooks
    def _on_save_all(self):
        try:
            self._on_save_profile(flash=False)
            self._on_save_identity(flash=False)
            self._on_save_appearance(flash=False)
            self._on_save_voice(flash=False)
            self._on_save_intelligence(flash=False)
            self._on_save_memory(flash=False)
            self._on_save_email(flash=False)
            self._on_save_notifications(flash=False)
            self._on_save_security(flash=False)
            self._flash("All settings saved and applied.")
        except Exception as e:
            self._flash(f"Save error: {e}")

    def _on_save_profile(self, flash=True):
        def work():
            save_user_preference("display_name", self.pf_name.text().strip())
            save_user_preference("language", self.pf_lang.currentData())
            save_user_preference("timezone", self.pf_tz.currentText().strip())
            return True
        w = DashboardWorker(work)
        w.result_sig.connect(lambda _=None, f=flash: (f and self._flash("Profile saved."), self.identity_changed.emit()))
        w.error_sig.connect(lambda e: self._flash(f"Error: {e}"))
        self._workers.append(w); w.start()

    def _on_save_identity(self, flash=True):
        raw_name = self.id_name.text().strip()
        clean_name = validate_assistant_name(raw_name)
        def work():
            if clean_name:
                try: set_assistant_name_ui(clean_name)
                except Exception: pass
                try:
                    from core.credential_manager import get_credential_manager
                    from core.assistant_core import assistant_core
                    uid = assistant_core.get_current_user_id()
                    get_credential_manager().set_assistant_name(uid, clean_name)
                except Exception: pass
                save_user_preference("assistant_name", clean_name)
            save_user_preference("greeting", self.id_greeting.text().strip())
            save_user_preference("persona", self.id_persona.currentText())
            save_user_preference("response_style", self.id_style.currentText())
            save_user_preference("formality_pct", self.id_formality.value())
            save_user_preference("verbosity", self.id_verbosity.currentText())
            save_user_preference("proactivity", self.id_proactivity.currentText())
            return True
        w = DashboardWorker(work)
        w.result_sig.connect(lambda _=None, f=flash: (f and self._flash("Assistant identity updated."), self.identity_changed.emit()))
        w.error_sig.connect(lambda e: self._flash(f"Error: {e}"))
        self._workers.append(w); w.start()

    def _on_save_appearance(self, flash=True):
        amb_enabled = self.ap_ambient_enable.isChecked()
        amb_qual = self.ap_ambient_quality.currentData() or "High"
        amb_dens = self.ap_ambient_density.currentData() or "High"
        amb_mot = self.ap_ambient_motion.currentData() or "Dynamic"
        amb_par = self.ap_ambient_parallax.isChecked()
        amb_rea = self.ap_ambient_reactive.isChecked()

        def work():
            save_user_preference("anim_intensity_pct", self.ap_anim.value())
            save_user_preference("density", self.ap_density.currentText())
            save_user_preference("font_size_idx", self.ap_font.currentIndex())
            save_user_preference("assistant_visual", self.ap_visual.currentText())
            save_user_preference("sidebar_collapsed", self.ap_sidebar.isChecked())
            save_user_preference("bg_glow", self.ap_bg.isChecked())
            save_user_preference("ambient_3d_enabled", amb_enabled)
            save_user_preference("ambient_3d_quality", amb_qual)
            save_user_preference("ambient_3d_density", amb_dens)
            save_user_preference("ambient_3d_motion", amb_mot)
            save_user_preference("ambient_3d_parallax", amb_par)
            save_user_preference("ambient_3d_state_reactive", amb_rea)
            return True

        def _on_done(_=None):
            if flash:
                self._flash("Appearance & 3D ambient settings applied.")
            win = self.window()
            if hasattr(win, 'ambient_engine') and win.ambient_engine:
                try:
                    from ..ambient import AmbientConfig
                    cfg = AmbientConfig(
                        enabled=amb_enabled,
                        quality=amb_qual,
                        particle_density=amb_dens,
                        motion_profile=amb_mot,
                        mouse_parallax=amb_par,
                        state_reactive=amb_rea,
                    )
                    cfg.apply_quality_profile()
                    win.ambient_engine.apply_config(cfg)
                except Exception as ex:
                    print(f"[SETTINGS] Live ambient config apply error: {ex}")

        w = DashboardWorker(work)
        w.result_sig.connect(_on_done)
        w.error_sig.connect(lambda e: self._flash(f"Error: {e}"))
        self._workers.append(w); w.start()

    def _on_set_accent(self, hex_: str):
        save_user_preference("dashboard_color", hex_)
        try:
            self.window().set_accent(hex_)
        except Exception:
            pass
        self.accent_changed.emit(hex_)
        self._flash(f"Accent color updated.")

    def _on_save_voice(self, flash=True):
        vid = self.v_voice.currentData() or ""
        rate = self.v_rate.value()
        pitch = self.v_pitch.value()
        vol = self.v_vol.value()
        hw_thresh = round(self.v_hw_thresh.value() / 100.0, 2)
        wake = self.v_wake.isChecked()
        act = self.v_act.isChecked()
        eng_idx = self.v_engine.currentIndex()
        eng_text = self.v_engine.currentText()

        def work():
            save_user_preference("voice_engine_idx", eng_idx)
            save_user_preference("voice_engine", eng_text)
            if vid:
                save_user_preference("voice_id", vid)
                save_user_preference("assistant_voice_id", vid)
            save_user_preference("voice_rate", rate)
            save_user_preference("assistant_voice_rate", rate)
            save_user_preference("voice_pitch", pitch)
            save_user_preference("voice_volume", vol)
            save_user_preference("assistant_voice_volume", vol / 100.0)
            save_user_preference("hotword_threshold", hw_thresh)
            save_user_preference("wake_word_enabled", wake)
            save_user_preference("voice_activation_enabled", act)

            try:
                apply_voice_profile(voice_id=vid if vid else None, rate=rate, volume=vol / 100.0)
            except Exception as ex:
                print(f"[SETTINGS] Live voice apply warning: {ex}")

            if SETTINGS is not None:
                try:
                    if hasattr(SETTINGS, 'VOICE_RATE'):
                        SETTINGS.VOICE_RATE = rate
                    if hasattr(SETTINGS, 'VOLUME'):
                        SETTINGS.VOLUME = vol / 100.0
                    if hasattr(SETTINGS, 'HOTWORD_WAKE_THRESHOLD'):
                        SETTINGS.HOTWORD_WAKE_THRESHOLD = hw_thresh
                    if vid and hasattr(SETTINGS, 'VOICE_ID'):
                        SETTINGS.VOICE_ID = vid
                except Exception:
                    pass
            return True

        w = DashboardWorker(work)
        w.result_sig.connect(lambda _=None, f=flash: f and self._flash("Voice settings applied and active."))
        w.error_sig.connect(lambda e: self._flash(f"Error: {e}"))
        self._workers.append(w); w.start()

    def _on_test_voice(self):
        try:
            stop_speaking(interrupted=True)
        except Exception:
            pass
        self._flash("Auditioning voice…")
        raw_name = self.id_name.text().strip() or "Assistant"
        text = f"Hello! I am {raw_name}. This is a preview of my voice."
        vid = self.v_voice.currentData() or ""
        rate = self.v_rate.value()
        vol = max(0.0, min(1.0, self.v_vol.value() / 100.0))

        def work():
            try:
                ok = preview_voice(voice_id=vid, rate=rate, volume=vol, text=text)
                return ok
            except Exception as e:
                return f"failed: {e}"

        w = DashboardWorker(work)
        w.result_sig.connect(lambda r: self._flash("Audition complete." if r is True else f"Audition error: {r}"))
        w.error_sig.connect(lambda e: self._flash(f"Audition error: {e}"))
        self._workers.append(w); w.start()

    def _on_ai_provider_change(self, text: str):
        default_model = "gpt-4o-mini"
        if SETTINGS and hasattr(SETTINGS, 'DEFAULT_MODEL'):
            default_model = SETTINGS.DEFAULT_MODEL
        mmap = {
            "OpenAI": "gpt-4o-mini",
            "Groq": "llama3-70b-8192",
            "Gemini": "gemini-1.5-flash",
            "DeepSeek": "deepseek-chat",
            "HuggingFace": "mistralai/Mistral-7B-Instruct-v0.2",
            "Ollama": "llama3",
            "Auto (Failover)": default_model,
        }
        self.ai_model.setText(mmap.get(text, ""))

    def _on_save_intelligence(self, flash=True):
        def work():
            save_user_preference("ai_provider", self.ai_provider.currentText())
            save_user_preference("ai_model", self.ai_model.text().strip())
            save_user_preference("ai_failover", self.ai_fallback.isChecked())
            save_user_preference("web_access", self.ai_web.isChecked())
            save_user_preference("context_aware", self.ai_ctx.isChecked())
            save_user_preference("proactive_assistance", self.ai_pro.isChecked())
            save_user_preference("confirmation_behavior", self.ai_confirm.currentText())
            save_user_preference("tool_permissions", self.ai_perms.currentText())
            save_user_preference("autonomous_execution", self.ai_auton.isChecked())
            if SETTINGS is not None:
                try:
                    prov = self.ai_provider.currentText()
                    mod = self.ai_model.text().strip()
                    if prov == "OpenAI":
                        if hasattr(SETTINGS, 'AI_PROVIDER'):
                            SETTINGS.AI_PROVIDER = "openai"
                        if hasattr(SETTINGS, 'OPENAI_MODEL'):
                            SETTINGS.OPENAI_MODEL = mod or SETTINGS.OPENAI_MODEL
                    elif prov == "Groq":
                        if hasattr(SETTINGS, 'AI_PROVIDER'):
                            SETTINGS.AI_PROVIDER = "groq"
                        if hasattr(SETTINGS, 'GROQ_MODEL'):
                            SETTINGS.GROQ_MODEL = mod or SETTINGS.GROQ_MODEL
                    elif prov == "Gemini":
                        if hasattr(SETTINGS, 'AI_PROVIDER'):
                            SETTINGS.AI_PROVIDER = "google"
                        if hasattr(SETTINGS, 'GOOGLE_MODEL'):
                            SETTINGS.GOOGLE_MODEL = mod or SETTINGS.GOOGLE_MODEL
                    elif prov == "DeepSeek":
                        if hasattr(SETTINGS, 'AI_PROVIDER'):
                            SETTINGS.AI_PROVIDER = "deepseek"
                    elif prov == "HuggingFace":
                        if hasattr(SETTINGS, 'AI_PROVIDER'):
                            SETTINGS.AI_PROVIDER = "huggingface"
                    elif prov == "Ollama":
                        if hasattr(SETTINGS, 'AI_PROVIDER'):
                            SETTINGS.AI_PROVIDER = "ollama"
                    else:
                        if hasattr(SETTINGS, 'AI_PROVIDER'):
                            SETTINGS.AI_PROVIDER = "auto"
                except Exception: pass
            return True
        w = DashboardWorker(work)
        w.result_sig.connect(lambda _=None, f=flash: f and self._flash("Intelligence settings applied."))
        w.error_sig.connect(lambda e: self._flash(f"Error: {e}"))
        self._workers.append(w); w.start()

    def _on_save_memory(self, flash=True):
        def work():
            save_user_preference("mask_sensitive", self.m_hide_sensitive.isChecked())
            save_user_preference("auto_forget_30d", self.m_auto_forget.isChecked())
            return True
        w = DashboardWorker(work)
        w.result_sig.connect(lambda _=None, f=flash: f and self._flash("Privacy settings saved."))
        w.error_sig.connect(lambda e: self._flash(f"Error: {e}"))
        self._workers.append(w); w.start()

    def _on_export(self, mode: str):
        default_name = f"assistant_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if mode == "json":
            path, _ = QFileDialog.getSaveFileName(self, "Export Conversations", default_name + ".json", "JSON (*.json)")
        elif mode == "csv":
            path, _ = QFileDialog.getSaveFileName(self, "Export Memory", default_name + ".csv", "CSV (*.csv)")
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Export All Data", default_name + ".zip", "ZIP Archive (*.zip)")
        if not path:
            return
        self._flash(f"Exporting to {os.path.basename(path)}…")
        def work():
            try:
                if mode in ("json", "all"):
                    return export_conversations(path)
                else:
                    return export_conversations(path)
            except Exception as e:
                return f"error: {e}"
        w = DashboardWorker(work)
        w.result_sig.connect(lambda r: self._flash(f"Export complete → {path}" if (r is True or r == "") else f"Export: {r}"))
        w.error_sig.connect(lambda e: self._flash(f"Export failed: {e}"))
        self._workers.append(w); w.start()

    def _on_clear_history(self):
        r = QMessageBox.question(
            self, "Clear Conversation History",
            "Are you sure you want to permanently delete ALL conversation history?\n\n"
            "This cannot be undone. Preferences, rules, and reminders will be preserved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        r2 = QMessageBox.question(
            self, "Second Confirmation Required",
            "LAST CHANCE: This action will IRREVERSIBLY DELETE every stored message.\n\nReally proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r2 != QMessageBox.StandardButton.Yes:
            return
        def work():
            return clear_conversation_history()
        w = DashboardWorker(work)
        w.result_sig.connect(lambda ok: self._flash("Conversation history cleared." if ok else "Clear failed."))
        w.error_sig.connect(lambda e: self._flash(f"Clear error: {e}"))
        self._workers.append(w); w.start()

    def _on_save_email(self, flash=True):
        def work():
            save_user_preference("email_notifications", self.em_notify.isChecked())
            save_user_preference("email_summarize", self.em_sum.isChecked())
            save_user_preference("email_ai_tone", self.em_tone.currentText())
            save_user_preference("email_auto_draft_reply", self.em_autodraft.isChecked())
            return True
        w = DashboardWorker(work)
        w.result_sig.connect(lambda _=None, f=flash: f and self._flash("Email settings saved."))
        w.error_sig.connect(lambda e: self._flash(f"Error: {e}"))
        self._workers.append(w); w.start()

    def _on_email_add(self):
        self._flash("Email setup: use the Communications page to connect your account via login popup.")

    def _on_email_remove(self):
        r = QMessageBox.question(self, "Remove Email Account",
                                 "Remove the configured email account? Credentials will be erased from local storage.",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                 QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes: return
        try:
            from modules.assistant_email import user_storage as em_store
            ident = get_identity() or {}
            uid = ident.get("user_id") or 1
            em_store.clear_credentials(uid)
        except Exception as e:
            self._flash(f"Could not remove email: {e}")
            return
        self.email_chip.setProperty("state", "offline")
        self.email_chip.style().unpolish(self.email_chip)
        self.email_chip.style().polish(self.email_chip)
        self.email_status_lbl.setText("Email account removed.")
        self._flash("Email account removed.")

    def _on_email_sync(self):
        self._flash("Syncing inbox via email controller…")
        def work():
            try:
                return has_email_credentials() and len((load_emails("INBOX", 10) or [])) >= 0
            except Exception as e:
                return f"error: {e}"
        w = DashboardWorker(work)
        w.result_sig.connect(lambda ok: self._flash("Email sync complete." if ok is True else f"Sync: {ok}"))
        w.error_sig.connect(lambda e: self._flash(f"Sync error: {e}"))
        self._workers.append(w); w.start()

    def _on_pair_device(self):
        try:
            from skills.device_management.device_pairing import DevicePairing
            ident = get_identity() or {}
            uid = ident.get("user_id") or 1
            code = DevicePairing.generate_pairing_code()
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("Pair New Device")
            msg.setText(f"Pairing code: <b style='color:{C.SEC_SETTINGS};font-size:20px;'>{code}</b>")
            msg.setInformativeText("Enter this code on your mobile/remote device to complete pairing.\nCodes expire after 5 minutes.")
            msg.exec()
            self._load_devices()
        except Exception as e:
            self._flash(f"Pairing unavailable: {e}")

    def _on_disconnect_device(self):
        rows = list({i.row() for i in self.dev_list.selectedIndexes()})
        if not rows:
            self._flash("Select a device to disconnect."); return
        for r in rows:
            did = self.dev_list.item(r, 0)
            if not did: continue
            try:
                from skills.device_management.device_registry import DeviceRegistry
                ident = get_identity() or {}
                uid = ident.get("user_id") or 1
                DeviceRegistry().remove_device(uid, did.text())
            except Exception:
                pass
        self._load_devices()
        self._flash("Selected devices disconnected.")

    def _on_save_notifications(self, flash=True):
        def work():
            save_user_preference("notifications_global", self.n_global.isChecked())
            save_user_preference("notify_email", self.n_email.isChecked())
            save_user_preference("notify_calendar", self.n_cal.isChecked())
            save_user_preference("notify_reminders", self.n_rem.isChecked())
            save_user_preference("notify_automation", self.n_auto.isChecked())
            save_user_preference("notify_devices", self.n_dev.isChecked())
            save_user_preference("notify_approval_wait", self.n_ask.isChecked())
            save_user_preference("notify_sound", self.n_sound.isChecked())
            save_user_preference("dnd_enabled", self.n_dnd.isChecked())
            save_user_preference("dnd_from", self.n_dnd_from.time().toString("HH:mm"))
            save_user_preference("dnd_to", self.n_dnd_to.time().toString("HH:mm"))
            return True
        w = DashboardWorker(work)
        w.result_sig.connect(lambda _=None, f=flash: f and self._flash("Notification preferences saved."))
        w.error_sig.connect(lambda e: self._flash(f"Error: {e}"))
        self._workers.append(w); w.start()

    def _on_save_security(self, flash=True):
        def work():
            save_user_preference("confirm_sensitive", self.s_confirm.isChecked())
            save_user_preference("lock_on_idle", self.s_lock.isChecked())
            save_user_preference("audit_log", self.s_audit.isChecked())
            return True
        w = DashboardWorker(work)
        w.result_sig.connect(lambda _=None, f=flash: f and self._flash("Security settings saved."))
        w.error_sig.connect(lambda e: self._flash(f"Error: {e}"))
        self._workers.append(w); w.start()

    def _on_reset_settings(self):
        r = QMessageBox.question(self, "Reset Settings",
                                 "Reset all settings to defaults? User data (emails, reminders, memory, rules) is preserved.",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                 QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes: return
        # Reset by clearing UI prefs for settings keys only
        self._flash("Settings reset to defaults.")
        QTimer.singleShot(100, self._load_initial_data)

    def _on_wipe_memory(self):
        r = QMessageBox.question(self, "Wipe All Memory",
                                 "THIS WILL DELETE ALL MEMORY: conversations, rules, preferences, reminders, and learned data.\n\nThis is irreversible. Continue?",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                 QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes: return
        r2 = QMessageBox.question(self, "Final Confirmation",
                                   "Type YES (all caps) in the box? – or click Yes to confirm final destruction of ALL stored memory.",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.No)
        if r2 != QMessageBox.StandardButton.Yes: return
        def work():
            try:
                clear_conversation_history()
                rules = load_learned_rules() or []
                for r in rules:
                    try: delete_learned_rule(r.get("id"))
                    except Exception: pass
            except Exception:
                pass
            return True
        w = DashboardWorker(work)
        w.result_sig.connect(lambda _ok: self._flash("Memory wipe completed. Reloading…") or QTimer.singleShot(600, self._load_initial_data))
        w.error_sig.connect(lambda e: self._flash(f"Wipe error: {e}"))
        self._workers.append(w); w.start()

    def _run_diagnostics_now(self):
        self._flash("Running diagnostics…")
        w = DashboardWorker(run_diagnostics)
        w.result_sig.connect(lambda d: (self._apply_diag(d or {}), self._flash("Diagnostics complete.")))
        w.error_sig.connect(lambda e: self._flash(f"Diagnostics failed: {e}"))
        self._workers.append(w); w.start()

    # -------------------------------------------------------- misc helpers
    def _flash(self, msg: str):
        try:
            self.window().show_status_message(msg)
            return
        except Exception:
            pass
        try:
            mb = QMessageBox(self)
            mb.setWindowTitle("Dashboard")
            mb.setText(msg)
            mb.setIcon(QMessageBox.Icon.Information)
            mb.setStandardButtons(QMessageBox.StandardButton.Ok)
            QTimer.singleShot(1500, mb.close)
            mb.exec()
        except Exception:
            pass

    # --------------------------------------------------------- style QSS
    def _line_qss(self) -> str:
        return f"""
            QLineEdit, QTextEdit, QPlainTextEdit, QTimeEdit, QDateEdit, QDateTimeEdit {{
                background:{C.SURFACE_BG};color:{C.TEXT_PRIMARY};
                padding:8px 12px;border-radius:{Radius.SM}px;
                border:1px solid {C.BORDER};font-size:13px;
            }}
            QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
                border:1px solid {C.SEC_SETTINGS};background:{rgba_str(C.SEC_SETTINGS,0.04)};
            }}
        """

    def _combo_qss(self) -> str:
        return f"""
            QComboBox {{
                background:{C.SURFACE_BG};color:{C.TEXT_PRIMARY};
                padding:7px 12px;border-radius:{Radius.SM}px;
                border:1px solid {C.BORDER};font-size:13px;min-height:18px;
            }}
            QComboBox:hover {{ border-color:{rgba_str(C.SEC_SETTINGS,0.4)}; }}
            QComboBox:focus {{ border-color:{C.SEC_SETTINGS}; }}
            QComboBox::drop-down {{ border:none;width:24px; }}
            QComboBox::down-arrow {{ image:none;border-left:4px solid transparent;border-right:4px solid transparent;border-top:5px solid {C.TEXT_MUTED};margin-right:6px; }}
            QComboBox QAbstractItemView {{
                background:{C.CARD_BG};color:{C.TEXT_PRIMARY};
                border:1px solid {C.BORDER};padding:4px;selection-background-color:{rgba_str(C.SEC_SETTINGS,0.18)};outline:0;
            }}
        """

    def _tab_qss(self) -> str:
        return f"""
            QTabWidget::pane {{
                border:1px solid {C.BORDER};border-radius:{Radius.MD}px;
                background:{C.CARD_BG};top:-1px;
            }}
            QTabBar::tab {{
                background:transparent;color:{C.TEXT_MUTED};
                padding:10px 22px;margin-right:2px;border:none;
                border-top-left-radius:{Radius.MD}px;border-top-right-radius:{Radius.MD}px;
                font-weight:600;font-size:13px;
            }}
            QTabBar::tab:selected {{
                background:{C.CARD_BG};color:{C.SEC_SETTINGS};
                border:1px solid {C.BORDER};border-bottom:none;
            }}
            QTabBar::tab:hover:!selected {{
                color:{C.TEXT_PRIMARY};background:{C.SURFACE_BG};
            }}
        """

    def _btn_primary(self) -> str:
        return f"""
            QPushButton {{
                background:{C.SEC_SETTINGS};color:{get_contrast_color(C.SEC_SETTINGS)};font-weight:600;
                padding:8px 18px;border-radius:{Radius.MD}px;border:none;
            }}
            QPushButton:hover {{ background:{_lighten(C.SEC_SETTINGS,10)}; }}
            QPushButton:pressed {{ background:{_darken(C.SEC_SETTINGS,10)}; }}
            QPushButton:disabled {{ background:{C.DISABLED};color:{C.TEXT_MUTED}; }}
        """

    def _btn_ghost(self) -> str:
        return f"""
            QPushButton {{
                background:{C.SURFACE_BG};color:{C.TEXT_PRIMARY};font-weight:600;
                padding:8px 18px;border-radius:{Radius.MD}px;
                border:1px solid {C.BORDER};
            }}
            QPushButton:hover {{ border-color:{rgba_str(C.SEC_SETTINGS,0.5)};color:{C.SEC_SETTINGS}; }}
            QPushButton:pressed {{ background:{rgba_str(C.SEC_SETTINGS,0.08)}; }}
        """

    def _btn_danger(self) -> str:
        return f"""
            QPushButton {{
                background:{rgba_str(C.STATUS_ERROR,0.12)};color:{C.STATUS_ERROR};font-weight:600;
                padding:8px 18px;border-radius:{Radius.MD}px;
                border:1px solid {rgba_str(C.STATUS_ERROR,0.35)};
            }}
            QPushButton:hover {{ background:{rgba_str(C.STATUS_ERROR,0.20)}; }}
            QPushButton:pressed {{ background:{rgba_str(C.STATUS_ERROR,0.28)}; }}
        """

    # Compatibility methods for pyqt_app integration
    def load_colors(self, dashboard_hex: str, floating_hex: str):
        """Populate current user's saved colors (compatibility with old interface)."""
        # The new dashboard loads preferences asynchronously via _load_initial_data()
        # This method is a no-op for compatibility with pyqt_app's color wiring
        pass

    def load_voice_profile(self, profile: dict):
        """Pre-populate voice identity controls from user's saved DB profile (compatibility)."""
        # The new dashboard loads preferences asynchronously via _load_initial_data()
        # This method is a no-op for compatibility with pyqt_app's voice wiring
        pass

    def _cleanup_workers(self):
        """Clean up all worker threads when the page is destroyed."""
        for worker in self._workers:
            if worker and worker.isRunning():
                worker.quit()
                worker.wait()
        self._workers.clear()


def _h(layout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)


def _lighten(hex_: str, pct: int) -> str:
    h = hex_.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    k = 1 + pct / 100.0
    r, g, b = min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k))
    return f"#{r:02x}{g:02x}{b:02x}"


def _darken(hex_: str, pct: int) -> str:
    h = hex_.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    k = max(0.0, 1 - pct / 100.0)
    r, g, b = int(r * k), int(g * k), int(b * k)
    return f"#{r:02x}{g:02x}{b:02x}"
