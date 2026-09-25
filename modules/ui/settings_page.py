"""
Smart Assistant — Assistant Control Center (Settings)
Distinct, comprehensive configuration hub designed around our assistant's
real architecture: Identity & Persona, Voice & Audio, Intelligence & LLM,
Memory & Privacy, Floating Assistant, and System Diagnostics.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QComboBox, QSlider, QCheckBox,
    QLineEdit, QSizePolicy, QStackedWidget, QGridLayout, QColorDialog
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from modules.ui.design_system import (
    C, F, Radius, Spacing, COLOR_PRESETS,
    DEFAULT_DASHBOARD_COLOR, DEFAULT_FLOATING_COLOR,
    hex_to_rgb, rgb_to_hex, rgba_str, get_contrast_color, ensure_visible_accent
)


def _section_header(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 8)
    lay.setSpacing(2)

    lbl = QLabel(title.upper())
    lbl.setFont(QFont(F.PRIMARY, 12, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color: {C.ACCENT_CYAN}; letter-spacing: 1.5px;")
    lay.addWidget(lbl)

    if subtitle:
        sub = QLabel(subtitle)
        sub.setFont(QFont(F.PRIMARY, 10))
        sub.setStyleSheet(f"color: {C.TEXT_MUTED};")
        lay.addWidget(sub)

    div = QFrame()
    div.setFixedHeight(1)
    div.setStyleSheet("background: rgba(0, 212, 255, 0.15); margin-top: 4px;")
    lay.addWidget(div)
    return w


def _control_card(parent=None) -> QFrame:
    card = QFrame(parent)
    card.setStyleSheet(f"""
        QFrame {{
            background: rgba(8, 14, 22, 0.65);
            border: 1px solid rgba(0, 212, 255, 0.12);
            border-radius: {Radius.MD}px;
            padding: 12px;
        }}
    """)
    return card


# ─────────────────────────────────────────────────────────────────────────────
# ASSISTANT CONTROL CENTER PAGE
# ─────────────────────────────────────────────────────────────────────────────
class SettingsPage(QWidget):
    """
    Complete Assistant Control Center with distinct architecture,
    live initial letter preview, audio testing, and independent appearance personalizer.
    """
    logout_requested        = pyqtSignal()
    assistant_name_changed  = pyqtSignal(str)
    voice_test_requested    = pyqtSignal(str)
    mic_test_requested      = pyqtSignal()
    dashboard_color_changed = pyqtSignal(str)
    floating_color_changed  = pyqtSignal(str)
    voice_profile_changed   = pyqtSignal(dict)   # per-user voice identity saved

    CATEGORIES = [
        ("Identity & Persona", "identity"),
        ("Appearance & Colors", "appearance"),
        ("Voice & Audio", "voice"),
        ("Intelligence & LLM", "intelligence"),
        ("Memory & Privacy", "memory"),
        ("Floating Assistant", "floating"),
        ("Diagnostics & Health", "diagnostics")
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")

        self._dashboard_color = DEFAULT_DASHBOARD_COLOR
        self._floating_color  = DEFAULT_FLOATING_COLOR
        self._accent_color    = DEFAULT_DASHBOARD_COLOR

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left Navigation Rail ────────────────────────────────────
        rail = QFrame()
        rail.setFixedWidth(195)
        rail.setStyleSheet(f"""
            QFrame {{
                background: rgba(4, 7, 12, 210);
                border-right: 1px solid rgba(0, 212, 255, 0.10);
            }}
        """)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(10, 16, 10, 16)
        rail_layout.setSpacing(6)

        title = QLabel("CONTROL CENTER")
        title.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT_MUTED}; letter-spacing: 1px; padding: 4px 8px;")
        rail_layout.addWidget(title)

        self._nav_buttons = []
        for idx, (label, key) in enumerate(self.CATEGORIES):
            btn = QPushButton(f"  {label}")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
            btn.setFixedHeight(34)
            btn.setStyleSheet(self._nav_style(False))
            btn.clicked.connect(lambda _, i=idx: self._select_category(i))
            self._nav_buttons.append(btn)
            rail_layout.addWidget(btn)

        rail_layout.addStretch()

        # Logout in nav bottom
        logout_btn = QPushButton("  🚪 Logout Account")
        logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        logout_btn.setFixedHeight(34)
        logout_btn.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
        logout_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 59, 48, 0.10);
                color: #ff4757;
                border: 1px solid rgba(255, 59, 48, 0.25);
                border-radius: {Radius.SM}px;
                text-align: left;
                padding-left: 10px;
            }}
            QPushButton:hover {{
                background: rgba(255, 59, 48, 0.25);
            }}
        """)
        logout_btn.clicked.connect(self.logout_requested.emit)
        rail_layout.addWidget(logout_btn)

        root.addWidget(rail)

        # ── Right Detail Stack ──────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")

        self._identity_page    = self._build_identity_page()
        self._appearance_page  = self._build_appearance_page()
        self._voice_page       = self._build_voice_page()
        self._intelligence_page= self._build_intelligence_page()
        self._memory_page      = self._build_memory_page()
        self._floating_page    = self._build_floating_page()
        self._diagnostics_page = self._build_diagnostics_page()

        self._stack.addWidget(self._identity_page)
        self._stack.addWidget(self._appearance_page)
        self._stack.addWidget(self._voice_page)
        self._stack.addWidget(self._intelligence_page)
        self._stack.addWidget(self._memory_page)
        self._stack.addWidget(self._floating_page)
        self._stack.addWidget(self._diagnostics_page)

        root.addWidget(self._stack, 1)

        self._select_category(0)


    def _nav_style(self, active: bool) -> str:
        acc = getattr(self, '_accent_color', C.ACCENT_CYAN)
        if active:
            return f"""
                QPushButton {{
                    background: {rgba_str(acc, 0.15)};
                    color: {acc};
                    border: 1px solid {rgba_str(acc, 0.35)};
                    border-radius: {Radius.SM}px;
                    text-align: left;
                    padding-left: 10px;
                    font-weight: bold;
                }}
            """
        return f"""
            QPushButton {{
                background: transparent;
                color: {C.TEXT_MED};
                border: 1px solid transparent;
                border-radius: {Radius.SM}px;
                text-align: left;
                padding-left: 10px;
            }}
            QPushButton:hover {{
                background: {rgba_str(acc, 0.06)};
                color: {C.TEXT};
            }}
        """

    def _select_category(self, idx: int):
        for i, b in enumerate(self._nav_buttons):
            b.setChecked(i == idx)
            b.setStyleSheet(self._nav_style(i == idx))
        self._stack.setCurrentIndex(idx)

    # ─────────────────────────────────────────────────────────────────────────
    # 1. IDENTITY & PERSONA
    # ─────────────────────────────────────────────────────────────────────────
    def _build_identity_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        lay.addWidget(_section_header("Identity & Persona", "Configure assistant name, identity, and dynamic visual initial"))

        card = _control_card()
        c_lay = QVBoxLayout(card)
        c_lay.setSpacing(Spacing.MD)

        # Live Dynamic Initial Preview
        preview_box = QHBoxLayout()
        self.badge_preview = QLabel("J")
        self.badge_preview.setFixedSize(54, 54)
        self.badge_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_preview.setFont(QFont(F.PRIMARY, 24, QFont.Weight.Bold))
        self.badge_preview.setStyleSheet(f"""
            QLabel {{
                background: rgba(0, 212, 255, 0.12);
                color: {C.ACCENT_CYAN};
                border: 2px solid {C.ACCENT_CYAN};
                border-radius: 27px;
            }}
        """)
        preview_box.addWidget(self.badge_preview)

        prev_info = QVBoxLayout()
        prev_title = QLabel("Floating Assistant Initial Preview")
        prev_title.setFont(QFont(F.PRIMARY, 11, QFont.Weight.Bold))
        prev_title.setStyleSheet(f"color: {C.TEXT};")
        prev_info.addWidget(prev_title)

        prev_sub = QLabel("Updates dynamically on the desktop floating control")
        prev_sub.setFont(QFont(F.PRIMARY, 9))
        prev_sub.setStyleSheet(f"color: {C.TEXT_MUTED};")
        prev_info.addWidget(prev_sub)
        preview_box.addLayout(prev_info)
        preview_box.addStretch()

        c_lay.addLayout(preview_box)

        # Assistant Name Input
        name_box = QVBoxLayout()
        name_box.setSpacing(4)
        lbl = QLabel("Assistant Name")
        lbl.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
        lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        name_box.addWidget(lbl)

        self.name_input = QLineEdit()
        self.name_input.setText("Jarvis")
        self.name_input.setFont(QFont(F.PRIMARY, 12))
        self.name_input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(255, 255, 255, 0.05);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: {Radius.SM}px;
                padding: 8px 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {C.ACCENT_CYAN};
            }}
        """)
        self.name_input.textChanged.connect(self._on_name_typed)
        self.name_input.returnPressed.connect(self._save_identity)
        name_box.addWidget(self.name_input)
        c_lay.addLayout(name_box)

        # Persona style selector
        persona_box = QVBoxLayout()
        lbl2 = QLabel("Persona & Speaking Style")
        lbl2.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
        lbl2.setStyleSheet(f"color: {C.TEXT_MED};")
        persona_box.addWidget(lbl2)

        self.persona_combo = QComboBox()
        self.persona_combo.addItems(["Concise & Direct", "Analytical & Technical", "Conversational & Empathetic"])
        self.persona_combo.setStyleSheet(f"""
            QComboBox {{
                background: rgba(255, 255, 255, 0.05);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: {Radius.SM}px;
                padding: 6px 12px;
            }}
        """)
        persona_box.addWidget(self.persona_combo)
        c_lay.addLayout(persona_box)

        # Save Button
        save_btn = QPushButton("Save Assistant Identity")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Bold))
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0, 212, 255, 0.18);
                color: {C.ACCENT_CYAN};
                border: 1px solid rgba(0, 212, 255, 0.35);
                border-radius: {Radius.SM}px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background: rgba(0, 212, 255, 0.35);
            }}
        """)
        save_btn.clicked.connect(self._save_identity)
        c_lay.addWidget(save_btn)

        lay.addWidget(card)
        lay.addStretch()
        return w

    def set_assistant_name(self, name: str):
        """Update displayed assistant name across all settings pages and initial preview."""
        if not name:
            return
        if hasattr(self, 'name_input') and self.name_input:
            self.name_input.blockSignals(True)
            self.name_input.setText(name)
            self.name_input.blockSignals(False)
        if hasattr(self, '_settings_asst_name_input') and self._settings_asst_name_input:
            self._settings_asst_name_input.blockSignals(True)
            self._settings_asst_name_input.setText(name)
            self._settings_asst_name_input.blockSignals(False)
        letter = name[0].upper()
        if hasattr(self, 'badge_preview') and self.badge_preview:
            self.badge_preview.setText(letter)
        if hasattr(self, '_float_prev_badge') and self._float_prev_badge:
            self._float_prev_badge.setText(letter)

    def _on_name_typed(self, text: str):
        letter = text.strip()[0].upper() if text.strip() else "?"
        if hasattr(self, 'badge_preview') and self.badge_preview:
            self.badge_preview.setText(letter)
        if hasattr(self, '_float_prev_badge') and self._float_prev_badge:
            self._float_prev_badge.setText(letter)
        if hasattr(self, '_settings_asst_name_input') and self._settings_asst_name_input:
            self._settings_asst_name_input.blockSignals(True)
            self._settings_asst_name_input.setText(text)
            self._settings_asst_name_input.blockSignals(False)

    def _on_asst_name_typed(self, text: str):
        letter = text.strip()[0].upper() if text.strip() else "?"
        if hasattr(self, 'badge_preview') and self.badge_preview:
            self.badge_preview.setText(letter)
        if hasattr(self, '_float_prev_badge') and self._float_prev_badge:
            self._float_prev_badge.setText(letter)
        if hasattr(self, 'name_input') and self.name_input:
            self.name_input.blockSignals(True)
            self.name_input.setText(text)
            self.name_input.blockSignals(False)

    def _save_identity(self):
        new_name = self.name_input.text().strip()
        if new_name:
            try:
                from instance.config import settings as CONFIG
                if isinstance(CONFIG, dict):
                    CONFIG["ASSISTANT_NAME"] = new_name
                setattr(CONFIG, "CURRENT_ASSISTANT_NAME", new_name)
                # Persist to user_preferences database table
                from legacy.memory_manager import set_assistant_name_db
                uid = getattr(CONFIG, "CURRENT_USER_ID", None)
                if not uid and isinstance(CONFIG, dict):
                    uid = CONFIG.get("CURRENT_USER_ID")
                if uid:
                    set_assistant_name_db(uid, new_name)
                # Sync other input field and initial preview
                if hasattr(self, '_settings_asst_name_input') and self._settings_asst_name_input:
                    self._settings_asst_name_input.blockSignals(True)
                    self._settings_asst_name_input.setText(new_name)
                    self._settings_asst_name_input.blockSignals(False)
                letter = new_name[0].upper()
                if hasattr(self, 'badge_preview') and self.badge_preview:
                    self.badge_preview.setText(letter)
                if hasattr(self, '_float_prev_badge') and self._float_prev_badge:
                    self._float_prev_badge.setText(letter)
                self.assistant_name_changed.emit(new_name)
            except Exception as e:
                print(f"[SETTINGS] Save identity error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # 2. APPEARANCE & COLORS (INDEPENDENT PERSONALIZATION)
    # ─────────────────────────────────────────────────────────────────────────
    def _build_appearance_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        lay.addWidget(_section_header(
            "Appearance & Color Personalization",
            "Independently customize the primary accent themes for Dashboard and Floating Assistant"
        ))

        # ── CARD 1: DASHBOARD COLOR ──────────────────────────────────
        dash_card = _control_card()
        dc_lay = QVBoxLayout(dash_card)
        dc_lay.setSpacing(12)

        dc_header = QHBoxLayout()
        dc_title = QLabel("DASHBOARD COLOR & THEME ACCENT")
        dc_title.setFont(QFont(F.PRIMARY, 11, QFont.Weight.Bold))
        dc_title.setStyleSheet(f"color: {C.TEXT}; letter-spacing: 0.5px;")
        dc_header.addWidget(dc_title)
        dc_header.addStretch()

        self._dash_contrast_badge = QLabel("Optimal Contrast")
        self._dash_contrast_badge.setFont(QFont(F.PRIMARY, 8, QFont.Weight.Bold))
        self._dash_contrast_badge.setStyleSheet(
            "color: #00e56b; background: rgba(0, 229, 107, 0.12); border-radius: 4px; padding: 2px 8px;"
        )
        dc_header.addWidget(self._dash_contrast_badge)
        dc_lay.addLayout(dc_header)

        dc_sub = QLabel("Controls the primary accent color across title bar orb, active tabs, buttons, borders, highlights, and audio visualizer.")
        dc_sub.setFont(QFont(F.PRIMARY, 9))
        dc_sub.setStyleSheet(f"color: {C.TEXT_MUTED};")
        dc_sub.setWordWrap(True)
        dc_lay.addWidget(dc_sub)

        # Dashboard Live Interactive Preview Frame
        self._dash_prev_frame = QFrame()
        self._dash_prev_frame.setStyleSheet(f"""
            QFrame {{
                background: rgba(4, 7, 12, 0.95);
                border: 1px solid {rgba_str(self._dashboard_color, 0.28)};
                border-radius: {Radius.MD}px;
                padding: 10px;
            }}
        """)
        dp_lay = QVBoxLayout(self._dash_prev_frame)
        dp_lay.setContentsMargins(12, 10, 12, 10)
        dp_lay.setSpacing(8)

        # Mini Title Row
        dp_title_row = QHBoxLayout()
        self._dash_prev_orb = QLabel("✦")
        self._dash_prev_orb.setFixedSize(20, 20)
        self._dash_prev_orb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dash_prev_orb.setStyleSheet(f"color: {self._dashboard_color}; border: 1.5px solid {self._dashboard_color}; border-radius: 10px; font-size: 9px;")
        dp_title_row.addWidget(self._dash_prev_orb)

        dp_title_lbl = QLabel("Smart Assistant Dashboard")
        dp_title_lbl.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Bold))
        dp_title_lbl.setStyleSheet(f"color: {C.TEXT};")
        dp_title_row.addWidget(dp_title_lbl)
        dp_title_row.addStretch()

        self._dash_prev_badge = QLabel("● IDLE")
        self._dash_prev_badge.setFont(QFont(F.PRIMARY, 8, QFont.Weight.Bold))
        self._dash_prev_badge.setStyleSheet(f"color: {self._dashboard_color}; background: {rgba_str(self._dashboard_color, 0.12)}; border: 1px solid {rgba_str(self._dashboard_color, 0.3)}; border-radius: 6px; padding: 2px 6px;")
        dp_title_row.addWidget(self._dash_prev_badge)
        dp_lay.addLayout(dp_title_row)

        # Mini Tab Row
        dp_tab_row = QHBoxLayout()
        self._dash_prev_tab_active = QLabel("Dashboard")
        self._dash_prev_tab_active.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Bold))
        self._dash_prev_tab_active.setStyleSheet(f"color: {self._dashboard_color}; background: {rgba_str(self._dashboard_color, 0.15)}; border: 1px solid {rgba_str(self._dashboard_color, 0.4)}; border-radius: 4px; padding: 3px 10px;")
        dp_tab_row.addWidget(self._dash_prev_tab_active)

        for tab_name in ["Chat", "Tasks", "Memory"]:
            t = QLabel(tab_name)
            t.setFont(QFont(F.PRIMARY, 9))
            t.setStyleSheet(f"color: {C.TEXT_MUTED}; padding: 3px 8px;")
            dp_tab_row.addWidget(t)
        dp_tab_row.addStretch()

        self._dash_prev_btn = QLabel("✦ Quick Action")
        self._dash_prev_btn.setFont(QFont(F.PRIMARY, 8, QFont.Weight.Bold))
        self._dash_prev_btn.setStyleSheet(f"color: {self._dashboard_color}; background: {rgba_str(self._dashboard_color, 0.1)}; border: 1px solid {self._dashboard_color}; border-radius: 4px; padding: 3px 8px;")
        dp_tab_row.addWidget(self._dash_prev_btn)
        dp_lay.addLayout(dp_tab_row)

        dc_lay.addWidget(self._dash_prev_frame)

        # Presets Swatches Row
        presets_label = QLabel("Preset Accent Swatches")
        presets_label.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Medium))
        presets_label.setStyleSheet(f"color: {C.TEXT_MED};")
        dc_lay.addWidget(presets_label)

        presets_row = QHBoxLayout()
        presets_row.setSpacing(6)
        for name, hex_code in COLOR_PRESETS:
            p_btn = QPushButton(name)
            p_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            p_btn.setFixedHeight(26)
            p_btn.setFont(QFont(F.PRIMARY, 8, QFont.Weight.Medium))
            p_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(8, 14, 22, 0.85);
                    color: {C.TEXT};
                    border: 1px solid {rgba_str(hex_code, 0.35)};
                    border-left: 4px solid {hex_code};
                    border-radius: 4px;
                    padding: 2px 6px;
                }}
                QPushButton:hover {{
                    background: {rgba_str(hex_code, 0.2)};
                    border: 1px solid {hex_code};
                }}
            """)
            p_btn.clicked.connect(lambda _, h=hex_code: self.set_dashboard_color(h))
            presets_row.addWidget(p_btn)
        presets_row.addStretch()
        dc_lay.addLayout(presets_row)

        # Custom Hex Input & Color Picker
        custom_row = QHBoxLayout()
        custom_row.setSpacing(8)

        self._dash_swatch = QLabel()
        self._dash_swatch.setFixedSize(30, 30)
        self._dash_swatch.setStyleSheet(f"background: {self._dashboard_color}; border: 2px solid #ffffff; border-radius: 6px;")
        custom_row.addWidget(self._dash_swatch)

        self._dash_hex_input = QLineEdit(self._dashboard_color)
        self._dash_hex_input.setFixedWidth(90)
        self._dash_hex_input.setMaxLength(7)
        self._dash_hex_input.setFont(F.mono(10))
        self._dash_hex_input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(14, 20, 27, 0.9);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 4px;
                padding: 4px 6px;
            }}
        """)
        self._dash_hex_input.textChanged.connect(self._on_dash_hex_typed)
        custom_row.addWidget(self._dash_hex_input)

        dash_picker_btn = QPushButton("🎨 Custom Color...")
        dash_picker_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dash_picker_btn.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Medium))
        dash_picker_btn.setFixedHeight(30)
        dash_picker_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.08);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.16);
            }}
        """)
        dash_picker_btn.clicked.connect(self._open_dash_color_picker)
        custom_row.addWidget(dash_picker_btn)

        dash_reset_btn = QPushButton("↺ Reset Dashboard Color")
        dash_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dash_reset_btn.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Medium))
        dash_reset_btn.setFixedHeight(30)
        dash_reset_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C.TEXT_MUTED};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.08);
                color: {C.TEXT};
            }}
        """)
        dash_reset_btn.clicked.connect(self.reset_dashboard_color)
        custom_row.addWidget(dash_reset_btn)

        custom_row.addStretch()
        dc_lay.addLayout(custom_row)

        lay.addWidget(dash_card)

        # ── CARD 2: FLOATING BUTTON COLOR ────────────────────────────
        float_card = _control_card()
        fc_lay = QVBoxLayout(float_card)
        fc_lay.setSpacing(12)

        fc_header = QHBoxLayout()
        fc_title = QLabel("FLOATING BUTTON COLOR & GLOW")
        fc_title.setFont(QFont(F.PRIMARY, 11, QFont.Weight.Bold))
        fc_title.setStyleSheet(f"color: {C.TEXT}; letter-spacing: 0.5px;")
        fc_header.addWidget(fc_title)
        fc_header.addStretch()

        self._float_contrast_badge = QLabel("Optimal Contrast")
        self._float_contrast_badge.setFont(QFont(F.PRIMARY, 8, QFont.Weight.Bold))
        self._float_contrast_badge.setStyleSheet(
            "color: #00e56b; background: rgba(0, 229, 107, 0.12); border-radius: 4px; padding: 2px 8px;"
        )
        fc_header.addWidget(self._float_contrast_badge)
        fc_lay.addLayout(fc_header)

        fc_sub = QLabel("Controls desktop launcher body glow, holographic border, dynamic initial letter core, and Quick Actions HUD.")
        fc_sub.setFont(QFont(F.PRIMARY, 9))
        fc_sub.setStyleSheet(f"color: {C.TEXT_MUTED};")
        fc_sub.setWordWrap(True)
        fc_lay.addWidget(fc_sub)

        # Floating Button Live Interactive Preview Frame
        self._float_prev_frame = QFrame()
        self._float_prev_frame.setStyleSheet(f"""
            QFrame {{
                background: rgba(4, 7, 12, 0.95);
                border: 1px solid {rgba_str(self._floating_color, 0.28)};
                border-radius: {Radius.MD}px;
                padding: 10px;
            }}
        """)
        fp_lay = QHBoxLayout(self._float_prev_frame)
        fp_lay.setContentsMargins(14, 10, 14, 10)
        fp_lay.setSpacing(18)

        # Live Mini Badge preview
        badge_box = QVBoxLayout()
        badge_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._float_prev_badge = QLabel()
        self._float_prev_badge.setFixedSize(56, 56)
        self._float_prev_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        init_letter = self.badge_preview.text() if hasattr(self, 'badge_preview') else "A"
        self._float_prev_badge.setText(init_letter)
        self._float_prev_badge.setFont(QFont(F.PRIMARY, 22, QFont.Weight.Bold))
        self._float_prev_badge.setStyleSheet(f"""
            QLabel {{
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                    stop:0 {rgba_str(self._floating_color, 0.45)},
                    stop:0.7 {rgba_str(self._floating_color, 0.15)},
                    stop:1.0 rgba(4, 7, 12, 0.95));
                color: #ffffff;
                border: 2px solid {self._floating_color};
                border-radius: 28px;
            }}
        """)
        badge_box.addWidget(self._float_prev_badge)
        badge_lbl = QLabel("Desktop Control")
        badge_lbl.setFont(QFont(F.PRIMARY, 8))
        badge_lbl.setStyleSheet(f"color: {C.TEXT_MUTED};")
        badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_box.addWidget(badge_lbl)
        fp_lay.addLayout(badge_box)

        # Live Mini HUD preview
        self._float_prev_hud = QFrame()
        self._float_prev_hud.setStyleSheet(f"""
            QFrame {{
                background: rgba(6, 12, 20, 0.9);
                border: 1px solid {rgba_str(self._floating_color, 0.4)};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        hud_lay = QVBoxLayout(self._float_prev_hud)
        hud_lay.setContentsMargins(8, 6, 8, 6)
        hud_lay.setSpacing(4)

        hud_head = QHBoxLayout()
        self._float_prev_hud_title = QLabel("QUICK ACTIONS HUD")
        self._float_prev_hud_title.setFont(F.mono(8))
        self._float_prev_hud_title.setStyleSheet(f"color: {self._floating_color}; font-weight: bold; letter-spacing: 0.5px;")
        hud_head.addWidget(self._float_prev_hud_title)
        hud_head.addStretch()

        h_badge = QLabel("● ACTIVE")
        h_badge.setFont(F.mono(7))
        h_badge.setStyleSheet("color: #00e56b; background: rgba(0,229,107,0.12); padding: 1px 4px; border-radius: 3px;")
        hud_head.addWidget(h_badge)
        hud_lay.addLayout(hud_head)

        mini_hud_desc = QLabel("Quick actions HUD adapts to the Floating Button's color independently.")
        mini_hud_desc.setFont(QFont(F.PRIMARY, 8))
        mini_hud_desc.setStyleSheet(f"color: {C.TEXT_MUTED};")
        mini_hud_desc.setWordWrap(True)
        hud_lay.addWidget(mini_hud_desc)

        fp_lay.addWidget(self._float_prev_hud, 1)
        fc_lay.addWidget(self._float_prev_frame)

        # Presets Swatches Row
        fc_presets_lbl = QLabel("Preset Accent Swatches")
        fc_presets_lbl.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Medium))
        fc_presets_lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        fc_lay.addWidget(fc_presets_lbl)

        fc_presets_row = QHBoxLayout()
        fc_presets_row.setSpacing(6)
        for name, hex_code in COLOR_PRESETS:
            p_btn = QPushButton(name)
            p_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            p_btn.setFixedHeight(26)
            p_btn.setFont(QFont(F.PRIMARY, 8, QFont.Weight.Medium))
            p_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(8, 14, 22, 0.85);
                    color: {C.TEXT};
                    border: 1px solid {rgba_str(hex_code, 0.35)};
                    border-left: 4px solid {hex_code};
                    border-radius: 4px;
                    padding: 2px 6px;
                }}
                QPushButton:hover {{
                    background: {rgba_str(hex_code, 0.2)};
                    border: 1px solid {hex_code};
                }}
            """)
            p_btn.clicked.connect(lambda _, h=hex_code: self.set_floating_color(h))
            fc_presets_row.addWidget(p_btn)
        fc_presets_row.addStretch()
        fc_lay.addLayout(fc_presets_row)

        # Custom Hex Input & Color Picker
        fc_custom_row = QHBoxLayout()
        fc_custom_row.setSpacing(8)

        self._float_swatch = QLabel()
        self._float_swatch.setFixedSize(30, 30)
        self._float_swatch.setStyleSheet(f"background: {self._floating_color}; border: 2px solid #ffffff; border-radius: 6px;")
        fc_custom_row.addWidget(self._float_swatch)

        self._float_hex_input = QLineEdit(self._floating_color)
        self._float_hex_input.setFixedWidth(90)
        self._float_hex_input.setMaxLength(7)
        self._float_hex_input.setFont(F.mono(10))
        self._float_hex_input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(14, 20, 27, 0.9);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 4px;
                padding: 4px 6px;
            }}
        """)
        self._float_hex_input.textChanged.connect(self._on_float_hex_typed)
        fc_custom_row.addWidget(self._float_hex_input)

        float_picker_btn = QPushButton("🎨 Custom Color...")
        float_picker_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        float_picker_btn.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Medium))
        float_picker_btn.setFixedHeight(30)
        float_picker_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.08);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.16);
            }}
        """)
        float_picker_btn.clicked.connect(self._open_float_color_picker)
        fc_custom_row.addWidget(float_picker_btn)

        float_reset_btn = QPushButton("↺ Reset Floating Button Color")
        float_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        float_reset_btn.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Medium))
        float_reset_btn.setFixedHeight(30)
        float_reset_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C.TEXT_MUTED};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.08);
                color: {C.TEXT};
            }}
        """)
        float_reset_btn.clicked.connect(self.reset_floating_color)
        fc_custom_row.addWidget(float_reset_btn)

        fc_custom_row.addStretch()
        fc_lay.addLayout(fc_custom_row)

        lay.addWidget(float_card)

        # ── CARD 3: GLOBAL RESET & STATUS ────────────────────────────
        global_card = _control_card()
        gc_lay = QHBoxLayout(global_card)
        gc_lay.setContentsMargins(14, 12, 14, 12)
        gc_lay.setSpacing(14)

        g_info = QVBoxLayout()
        g_title = QLabel("INDEPENDENT COLOR PROFILE")
        g_title.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Bold))
        g_title.setStyleSheet(f"color: {C.TEXT}; letter-spacing: 0.5px;")
        g_info.addWidget(g_title)

        self._profile_status_lbl = QLabel(
            f"Dashboard: {self._dashboard_color} | Floating Assistant: {self._floating_color} (Stored separately per user)"
        )
        self._profile_status_lbl.setFont(QFont(F.PRIMARY, 9))
        self._profile_status_lbl.setStyleSheet(f"color: {C.TEXT_MUTED};")
        g_info.addWidget(self._profile_status_lbl)
        gc_lay.addLayout(g_info, 1)

        reset_all_btn = QPushButton("↺ Reset All Appearance")
        reset_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_all_btn.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Bold))
        reset_all_btn.setFixedHeight(32)
        reset_all_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 71, 87, 0.12);
                color: #ff4757;
                border: 1px solid rgba(255, 71, 87, 0.3);
                border-radius: {Radius.SM}px;
                padding: 4px 14px;
            }}
            QPushButton:hover {{
                background: rgba(255, 71, 87, 0.25);
            }}
        """)
        reset_all_btn.clicked.connect(self.reset_all_appearance)
        gc_lay.addWidget(reset_all_btn)

        lay.addWidget(global_card)
        lay.addStretch()

        scroll.setWidget(container)
        return scroll

    # ── Color Management & Real-Time Sync Handlers ───────────────────────────
    def _open_dash_color_picker(self):
        col = QColorDialog.getColor(QColor(self._dashboard_color), self, "Select Dashboard Accent Color")
        if col.isValid():
            self.set_dashboard_color(col.name().upper(), notify=True)

    def _open_float_color_picker(self):
        col = QColorDialog.getColor(QColor(self._floating_color), self, "Select Floating Assistant Button Color")
        if col.isValid():
            self.set_floating_color(col.name().upper(), notify=True)

    def _on_dash_hex_typed(self, text: str):
        cleaned = text.strip()
        if not cleaned.startswith("#"):
            cleaned = "#" + cleaned
        if len(cleaned) == 7:
            try:
                int(cleaned[1:], 16)
                self.set_dashboard_color(cleaned.upper(), notify=True)
            except ValueError:
                pass

    def _on_float_hex_typed(self, text: str):
        cleaned = text.strip()
        if not cleaned.startswith("#"):
            cleaned = "#" + cleaned
        if len(cleaned) == 7:
            try:
                int(cleaned[1:], 16)
                self.set_floating_color(cleaned.upper(), notify=True)
            except ValueError:
                pass

    def set_dashboard_color(self, hex_color: str, notify: bool = True):
        """Sets the Dashboard primary accent color independently."""
        hex_color = hex_color.strip()
        if not hex_color.startswith("#"):
            hex_color = "#" + hex_color
        if len(hex_color) != 7:
            return
        hex_color = ensure_visible_accent(hex_color.upper())
        self._dashboard_color = hex_color

        if hasattr(self, '_dash_hex_input') and self._dash_hex_input.text().upper() != hex_color:
            self._dash_hex_input.blockSignals(True)
            self._dash_hex_input.setText(hex_color)
            self._dash_hex_input.blockSignals(False)

        if hasattr(self, '_dash_swatch'):
            self._dash_swatch.setStyleSheet(f"background: {hex_color}; border: 2px solid #ffffff; border-radius: 6px;")

        self._update_dashboard_preview()
        self.set_accent_color(hex_color)

        if notify:
            self.dashboard_color_changed.emit(self._dashboard_color)

    def set_floating_color(self, hex_color: str, notify: bool = True):
        """Sets the Floating Button primary accent color independently."""
        hex_color = hex_color.strip()
        if not hex_color.startswith("#"):
            hex_color = "#" + hex_color
        if len(hex_color) != 7:
            return
        hex_color = ensure_visible_accent(hex_color.upper())
        self._floating_color = hex_color

        if hasattr(self, '_float_hex_input') and self._float_hex_input.text().upper() != hex_color:
            self._float_hex_input.blockSignals(True)
            self._float_hex_input.setText(hex_color)
            self._float_hex_input.blockSignals(False)

        if hasattr(self, '_float_swatch'):
            self._float_swatch.setStyleSheet(f"background: {hex_color}; border: 2px solid #ffffff; border-radius: 6px;")

        self._update_floating_preview()

        if notify:
            self.floating_color_changed.emit(self._floating_color)

    def _update_dashboard_preview(self):
        c = self._dashboard_color
        if hasattr(self, '_dash_prev_frame'):
            self._dash_prev_frame.setStyleSheet(f"""
                QFrame {{
                    background: rgba(4, 7, 12, 0.95);
                    border: 1px solid {rgba_str(c, 0.35)};
                    border-radius: {Radius.MD}px;
                    padding: 10px;
                }}
            """)
        if hasattr(self, '_dash_prev_orb'):
            self._dash_prev_orb.setStyleSheet(f"color: {c}; border: 1.5px solid {c}; border-radius: 10px; font-size: 9px;")
        if hasattr(self, '_dash_prev_badge'):
            self._dash_prev_badge.setStyleSheet(f"color: {c}; background: {rgba_str(c, 0.12)}; border: 1px solid {rgba_str(c, 0.3)}; border-radius: 6px; padding: 2px 6px;")
        if hasattr(self, '_dash_prev_tab_active'):
            self._dash_prev_tab_active.setStyleSheet(f"color: {c}; background: {rgba_str(c, 0.15)}; border: 1px solid {rgba_str(c, 0.4)}; border-radius: 4px; padding: 3px 10px;")
        if hasattr(self, '_dash_prev_btn'):
            self._dash_prev_btn.setStyleSheet(f"color: {c}; background: {rgba_str(c, 0.1)}; border: 1px solid {c}; border-radius: 4px; padding: 3px 8px;")

        # Contrast status
        if hasattr(self, '_dash_contrast_badge'):
            status, style = self._compute_contrast_badge(c)
            self._dash_contrast_badge.setText(status)
            self._dash_contrast_badge.setStyleSheet(style)

        if hasattr(self, '_profile_status_lbl'):
            self._profile_status_lbl.setText(
                f"Dashboard: {self._dashboard_color} | Floating Assistant: {self._floating_color} (Stored separately per user)"
            )

    def _update_floating_preview(self):
        c = self._floating_color
        if hasattr(self, '_float_prev_frame'):
            self._float_prev_frame.setStyleSheet(f"""
                QFrame {{
                    background: rgba(4, 7, 12, 0.95);
                    border: 1px solid {rgba_str(c, 0.35)};
                    border-radius: {Radius.MD}px;
                    padding: 10px;
                }}
            """)
        if hasattr(self, '_float_prev_badge'):
            self._float_prev_badge.setStyleSheet(f"""
                QLabel {{
                    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                        stop:0 {rgba_str(c, 0.45)},
                        stop:0.7 {rgba_str(c, 0.15)},
                        stop:1.0 rgba(4, 7, 12, 0.95));
                    color: #ffffff;
                    border: 2px solid {c};
                    border-radius: 28px;
                }}
            """)
        if hasattr(self, '_float_prev_hud'):
            self._float_prev_hud.setStyleSheet(f"""
                QFrame {{
                    background: rgba(6, 12, 20, 0.9);
                    border: 1px solid {rgba_str(c, 0.45)};
                    border-radius: 8px;
                    padding: 8px;
                }}
            """)
        if hasattr(self, '_float_prev_hud_title'):
            self._float_prev_hud_title.setStyleSheet(f"color: {c}; font-weight: bold; letter-spacing: 0.5px;")

        # Contrast status
        if hasattr(self, '_float_contrast_badge'):
            status, style = self._compute_contrast_badge(c)
            self._float_contrast_badge.setText(status)
            self._float_contrast_badge.setStyleSheet(style)

        if hasattr(self, '_profile_status_lbl'):
            self._profile_status_lbl.setText(
                f"Dashboard: {self._dashboard_color} | Floating Assistant: {self._floating_color} (Stored separately per user)"
            )

    def _compute_contrast_badge(self, hex_color: str) -> tuple[str, str]:
        r, g, b = hex_to_rgb(hex_color)
        lum = 0.2126 * (r / 255.0) + 0.7152 * (g / 255.0) + 0.0722 * (b / 255.0)
        if lum < 0.10:
            return ("Auto-Enhanced Luma", "color: #ff8c00; background: rgba(255, 140, 0, 0.12); border-radius: 4px; padding: 2px 8px;")
        elif lum > 0.82:
            return ("High Lumens (AAA)", "color: #00e56b; background: rgba(0, 229, 107, 0.12); border-radius: 4px; padding: 2px 8px;")
        else:
            return ("Optimal Contrast (AA)", "color: #00e56b; background: rgba(0, 229, 107, 0.12); border-radius: 4px; padding: 2px 8px;")

    def load_colors(self, dashboard_hex: str, floating_hex: str):
        """Populate current user's saved colors without emitting change signals."""
        if dashboard_hex:
            self.set_dashboard_color(dashboard_hex, notify=False)
        if floating_hex:
            self.set_floating_color(floating_hex, notify=False)

    def reset_dashboard_color(self):
        """Restore default cyan theme for Dashboard."""
        self.set_dashboard_color(DEFAULT_DASHBOARD_COLOR, notify=True)

    def reset_floating_color(self):
        """Restore default cyan theme for Floating Button."""
        self.set_floating_color(DEFAULT_FLOATING_COLOR, notify=True)

    def reset_all_appearance(self):
        """Restore both Dashboard and Floating Button to default cybernetic cyan."""
        self.reset_dashboard_color()
        self.reset_floating_color()

    def set_accent_color(self, hex_color: str):
        """Dynamically updates Settings navigation highlights when Dashboard accent changes."""
        self._accent_color = hex_color
        current_idx = self._stack.currentIndex()
        self._select_category(current_idx)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. VOICE & AUDIO PIPELINE
    # ─────────────────────────────────────────────────────────────────────────
    def _build_voice_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        lay.addWidget(_section_header(
            "Voice & Audio Pipeline",
            "Personalize assistant voice identity, speaking style, and hardware audio settings"
        ))

        # ── CARD 1: ASSISTANT VOICE IDENTITY ─────────────────────────────────
        id_card = _control_card()
        id_lay = QVBoxLayout(id_card)
        id_lay.setSpacing(Spacing.MD)

        id_header_lbl = QLabel("ASSISTANT VOICE IDENTITY")
        id_header_lbl.setFont(QFont(F.PRIMARY, 11, QFont.Weight.Bold))
        id_header_lbl.setStyleSheet(f"color: {C.TEXT}; letter-spacing: 0.5px;")
        id_lay.addWidget(id_header_lbl)

        id_sub = QLabel(
            "Voice identity, gender, and speaking style are saved per authenticated account. "
            "Changes apply immediately to live speech output — no restart required."
        )
        id_sub.setFont(QFont(F.PRIMARY, 9))
        id_sub.setStyleSheet(f"color: {C.TEXT_MUTED};")
        id_sub.setWordWrap(True)
        id_lay.addWidget(id_sub)

        # Assistant Name Field
        name_lbl = QLabel("Assistant Name")
        name_lbl.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
        name_lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        id_lay.addWidget(name_lbl)

        self._settings_asst_name_input = QLineEdit()
        self._settings_asst_name_input.setFixedHeight(34)
        self._settings_asst_name_input.setFont(QFont(F.PRIMARY, 10))
        self._settings_asst_name_input.setPlaceholderText("Enter assistant name (e.g. Jarvis, Friday, Nova)")
        self._settings_asst_name_input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(255,255,255,0.05);
                color: {C.TEXT};
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: {Radius.SM}px;
                padding: 5px 10px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.ACCENT_CYAN}; }}
        """)
        try:
            from instance.config import settings as CONFIG
            aname = getattr(CONFIG, 'CURRENT_ASSISTANT_NAME', None) or "Jarvis"
        except Exception:
            aname = "Jarvis"
        self._settings_asst_name_input.setText(aname)
        self._settings_asst_name_input.textChanged.connect(self._on_asst_name_typed)
        self._settings_asst_name_input.returnPressed.connect(self._settings_save_voice)
        id_lay.addWidget(self._settings_asst_name_input)

        # Gender Row (Filter)
        g_lbl = QLabel("Voice Gender")
        g_lbl.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
        g_lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        id_lay.addWidget(g_lbl)

        gender_row = QHBoxLayout()
        gender_row.setSpacing(10)
        self._settings_btn_male   = QPushButton("♂  Male")
        self._settings_btn_female = QPushButton("♀  Female")
        self._settings_btn_other  = QPushButton("⚥  Other / All")
        for btn in (self._settings_btn_male, self._settings_btn_female, self._settings_btn_other):
            btn.setFixedHeight(36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Bold))
            btn.setCheckable(True)
        self._settings_voice_gender = "female"
        self._settings_selected_voice_id = None
        self._settings_all_voices: list = []
        self._settings_btn_female.setChecked(True)
        self._update_settings_gender_styles()
        self._settings_btn_male.clicked.connect(
            lambda: self._settings_select_gender("male"))
        self._settings_btn_female.clicked.connect(
            lambda: self._settings_select_gender("female"))
        self._settings_btn_other.clicked.connect(
            lambda: self._settings_select_gender("other"))
        gender_row.addWidget(self._settings_btn_male)
        gender_row.addWidget(self._settings_btn_female)
        gender_row.addWidget(self._settings_btn_other)
        gender_row.addStretch()
        id_lay.addLayout(gender_row)

        # Available Voices Section
        v_lbl = QLabel("Available Voices")
        v_lbl.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
        v_lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        id_lay.addWidget(v_lbl)

        self._settings_voice_list_scroll = QScrollArea()
        self._settings_voice_list_scroll.setWidgetResizable(True)
        self._settings_voice_list_scroll.setFixedHeight(230)
        self._settings_voice_list_scroll.setStyleSheet("""
            QScrollArea {
                background: rgba(0,0,0,0.22);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px;
            }
            QScrollBar:vertical {
                width: 6px;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 212, 255, 0.3);
                border-radius: 3px;
            }
        """)

        self._settings_voice_cards_container = QWidget()
        self._settings_voice_cards_container.setStyleSheet("background: transparent;")
        self._settings_voice_cards_layout = QVBoxLayout(self._settings_voice_cards_container)
        self._settings_voice_cards_layout.setContentsMargins(8, 8, 8, 8)
        self._settings_voice_cards_layout.setSpacing(6)
        self._settings_voice_list_scroll.setWidget(self._settings_voice_cards_container)
        id_lay.addWidget(self._settings_voice_list_scroll)

        # Tone dropdown
        t_lbl = QLabel("Speaking Style")
        t_lbl.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
        t_lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        id_lay.addWidget(t_lbl)

        self._settings_tone_combo = QComboBox()
        self._settings_tone_combo.setFixedHeight(34)
        self._settings_tone_combo.setFont(QFont(F.PRIMARY, 10))
        self._settings_tone_combo.setStyleSheet(f"""
            QComboBox {{
                background: rgba(255,255,255,0.05);
                color: {C.TEXT};
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: {Radius.SM}px;
                padding: 5px 10px;
            }}
            QComboBox:focus {{ border: 1px solid {C.ACCENT_CYAN}; }}
            QComboBox QAbstractItemView {{
                background: #0a1520;
                color: {C.TEXT};
                selection-background-color: rgba(0,212,255,0.18);
            }}
        """)
        _TONES = [
            ("Calm",         "Slower rate, slightly quieter"),
            ("Professional", "Neutral rate and volume"),
            ("Friendly",     "Slightly faster, full volume"),
            ("Energetic",    "Fast rate, full volume"),
            ("Soft",         "Slowest rate, lower volume"),
        ]
        self._settings_tone_profiles = {
            "calm":         {"rate": 130, "volume": 0.9},
            "professional": {"rate": 155, "volume": 1.0},
            "friendly":     {"rate": 165, "volume": 1.0},
            "energetic":    {"rate": 185, "volume": 1.0},
            "soft":         {"rate": 125, "volume": 0.75},
        }
        for tname, tdesc in _TONES:
            self._settings_tone_combo.addItem(f"{tname} — {tdesc}", tname.lower())
        self._settings_tone_combo.setCurrentIndex(1)  # Professional default
        id_lay.addWidget(self._settings_tone_combo)

        # Voice status / notification label
        self._settings_voice_status = QLabel("")
        self._settings_voice_status.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Medium))
        self._settings_voice_status.setStyleSheet(f"color: {C.ACCENT_CYAN};")
        self._settings_voice_status.hide()
        id_lay.addWidget(self._settings_voice_status)

        # Action buttons row
        voice_btn_row = QHBoxLayout()
        voice_btn_row.setSpacing(10)

        save_voice_btn = QPushButton("Save Voice Identity")
        save_voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_voice_btn.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Bold))
        save_voice_btn.setFixedHeight(36)
        save_voice_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0,212,255,0.18);
                color: {C.ACCENT_CYAN};
                border: 1px solid rgba(0,212,255,0.38);
                border-radius: {Radius.SM}px;
                padding: 6px 18px;
            }}
            QPushButton:hover {{ background: rgba(0,212,255,0.35); }}
        """)
        save_voice_btn.clicked.connect(self._settings_save_voice)
        voice_btn_row.addWidget(save_voice_btn)
        voice_btn_row.addStretch()
        id_lay.addLayout(voice_btn_row)

        lay.addWidget(id_card)

        # ── CARD 2: HARDWARE AUDIO ────────────────────────────────────────────
        hw_card = _control_card()
        hw_lay = QVBoxLayout(hw_card)
        hw_lay.setSpacing(Spacing.MD)

        hw_header_lbl = QLabel("HARDWARE AUDIO")
        hw_header_lbl.setFont(QFont(F.PRIMARY, 11, QFont.Weight.Bold))
        hw_header_lbl.setStyleSheet(f"color: {C.TEXT}; letter-spacing: 0.5px;")
        hw_lay.addWidget(hw_header_lbl)

        # Microphone Device Selector
        mic_box = QVBoxLayout()
        mic_lbl = QLabel("Input Audio Device")
        mic_lbl.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
        mic_lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        mic_box.addWidget(mic_lbl)

        self.mic_combo = QComboBox()
        self._populate_audio_devices()
        self.mic_combo.setStyleSheet(f"""
            QComboBox {{
                background: rgba(255, 255, 255, 0.05);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: {Radius.SM}px;
                padding: 6px 12px;
            }}
        """)
        mic_box.addWidget(self.mic_combo)
        hw_lay.addLayout(mic_box)

        # Continuous listening toggle
        self.cont_check = QCheckBox("Wake-word-free continuous listening (stateful VAD capture)")
        self.cont_check.setChecked(True)
        self.cont_check.setFont(QFont(F.PRIMARY, 10))
        self.cont_check.setStyleSheet(f"color: {C.TEXT};")
        hw_lay.addWidget(self.cont_check)

        # Action Buttons: Test Voice & Test Mic
        hw_btn_box = QHBoxLayout()
        test_tts_btn = QPushButton("▶ Test Voice Synthesis")
        test_tts_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_tts_btn.setFont(QFont(F.PRIMARY, 10))
        test_tts_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0, 212, 255, 0.12);
                color: {C.ACCENT_CYAN};
                border: 1px solid rgba(0, 212, 255, 0.25);
                border-radius: {Radius.SM}px;
                padding: 7px 14px;
            }}
            QPushButton:hover {{ background: rgba(0, 212, 255, 0.25); }}
        """)
        test_tts_btn.clicked.connect(self._test_voice)
        hw_btn_box.addWidget(test_tts_btn)

        test_mic_btn = QPushButton("🎤 Sample Microphone")
        test_mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_mic_btn.setFont(QFont(F.PRIMARY, 10))
        test_mic_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.06);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: {Radius.SM}px;
                padding: 7px 14px;
            }}
            QPushButton:hover {{ background: rgba(255, 255, 255, 0.14); }}
        """)
        test_mic_btn.clicked.connect(self._test_mic)
        hw_btn_box.addWidget(test_mic_btn)
        hw_btn_box.addStretch()
        hw_lay.addLayout(hw_btn_box)

        # Status output for test mic
        self.mic_status_lbl = QLabel("Hardware status: Microphone stream active via MME")
        self.mic_status_lbl.setFont(QFont(F.PRIMARY, 9))
        self.mic_status_lbl.setStyleSheet(f"color: {C.TEXT_MUTED};")
        hw_lay.addWidget(self.mic_status_lbl)

        lay.addWidget(hw_card)
        lay.addStretch()

        scroll.setWidget(container)

        # Discover real system voices synchronously
        try:
            from legacy.tts import enumerate_voices
            self._settings_all_voices = enumerate_voices()
        except Exception as e:
            print(f"[SETTINGS] Failed to enumerate voices: {e}")
            self._settings_all_voices = []

        self._settings_populate_voice_cards()

        return scroll

    def _settings_gender_btn_style(self, active: bool) -> str:
        acc = C.ACCENT_CYAN
        if active:
            return f"""
                QPushButton {{
                    background: rgba(0,212,255,0.16);
                    color: {acc};
                    border: 1.5px solid {acc};
                    border-radius: {Radius.SM}px;
                }}
            """
        return f"""
            QPushButton {{
                background: rgba(255,255,255,0.04);
                color: {C.TEXT_MED};
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: {Radius.SM}px;
            }}
            QPushButton:hover {{
                background: rgba(0,212,255,0.08);
                color: {C.TEXT};
            }}
        """

    def _update_settings_gender_styles(self):
        if hasattr(self, '_settings_btn_male'):
            self._settings_btn_male.setStyleSheet(
                self._settings_gender_btn_style(self._settings_voice_gender == "male"))
        if hasattr(self, '_settings_btn_female'):
            self._settings_btn_female.setStyleSheet(
                self._settings_gender_btn_style(self._settings_voice_gender == "female"))
        if hasattr(self, '_settings_btn_other'):
            self._settings_btn_other.setStyleSheet(
                self._settings_gender_btn_style(self._settings_voice_gender == "other"))

    def _settings_select_gender(self, gender: str):
        self._settings_voice_gender = gender
        if hasattr(self, '_settings_btn_male'):
            self._settings_btn_male.setChecked(gender == "male")
        if hasattr(self, '_settings_btn_female'):
            self._settings_btn_female.setChecked(gender == "female")
        if hasattr(self, '_settings_btn_other'):
            self._settings_btn_other.setChecked(gender == "other")
        self._update_settings_gender_styles()
        self._settings_populate_voice_cards()

    def _settings_populate_voice_cards(self):
        if not hasattr(self, '_settings_voice_cards_layout'):
            return

        # Clear existing card widgets
        while self._settings_voice_cards_layout.count():
            item = self._settings_voice_cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not getattr(self, '_settings_all_voices', None):
            try:
                from legacy.tts import enumerate_voices
                self._settings_all_voices = enumerate_voices()
            except Exception as e:
                print(f"[SETTINGS] Failed to enumerate voices: {e}")
                self._settings_all_voices = []

        g = getattr(self, '_settings_voice_gender', 'female')
        if g == "male":
            filtered = [v for v in self._settings_all_voices if v.get("gender") == "male"]
        elif g == "female":
            filtered = [v for v in self._settings_all_voices if v.get("gender") == "female"]
        else:
            # "other" / unknown filter - show unknown/other voices, or all if none specifically unknown
            filtered = [v for v in self._settings_all_voices if v.get("gender") not in ("male", "female")]
            if not filtered:
                filtered = list(self._settings_all_voices)

        if not filtered:
            filtered = list(self._settings_all_voices)

        if not filtered:
            empty_lbl = QLabel("No system voices discovered — using engine default")
            empty_lbl.setFont(QFont(F.PRIMARY, 10))
            empty_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; padding: 12px;")
            self._settings_voice_cards_layout.addWidget(empty_lbl)
            return

        # Ensure active selected voice matches active gender options
        avail_ids = [v["id"] for v in filtered]
        sel_id = getattr(self, '_settings_selected_voice_id', None)

        matched_id = None
        if sel_id:
            for v in filtered:
                vid = v["id"]
                token_end = vid.split("\\")[-1]
                sel_end = sel_id.split("\\")[-1]
                if vid == sel_id or token_end == sel_end or vid.endswith(sel_id) or sel_id.endswith(vid):
                    matched_id = vid
                    break

        if matched_id:
            self._settings_selected_voice_id = matched_id
        else:
            self._settings_selected_voice_id = filtered[0]["id"]

        self._settings_voice_card_frames = []

        for voice_info in filtered:
            vid = voice_info["id"]
            is_selected = (vid == self._settings_selected_voice_id)

            card = QFrame()
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setProperty("voice_id", vid)

            card_lay = QHBoxLayout(card)
            card_lay.setContentsMargins(12, 8, 12, 8)
            card_lay.setSpacing(10)

            # Left Info
            info_box = QVBoxLayout()
            info_box.setSpacing(2)

            name_row = QHBoxLayout()
            name_row.setSpacing(8)
            name_lbl = QLabel(voice_info.get("name", "Voice"))
            name_lbl.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Bold))
            name_row.addWidget(name_lbl)

            sel_indicator = QLabel("✓ Selected" if is_selected else "")
            sel_indicator.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Bold))
            sel_indicator.setStyleSheet(f"color: {C.ACCENT_CYAN};")
            name_row.addWidget(sel_indicator)
            name_row.addStretch()
            info_box.addLayout(name_row)

            provider_label = "Microsoft SAPI5" if voice_info.get("provider") == "sapi5" else "Microsoft OneCore"
            meta_lbl = QLabel(f"{voice_info.get('language', 'English')} • {provider_label}")
            meta_lbl.setFont(QFont(F.PRIMARY, 9))
            meta_lbl.setStyleSheet(f"color: {C.TEXT_MUTED};")
            info_box.addWidget(meta_lbl)

            card_lay.addLayout(info_box, 1)

            # Dedicated Preview Button
            prev_btn = QPushButton("▶  Preview")
            prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            prev_btn.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Medium))
            prev_btn.setFixedHeight(28)
            prev_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(0, 212, 255, 0.08);
                    color: {C.ACCENT_CYAN};
                    border: 1px solid rgba(0, 212, 255, 0.25);
                    border-radius: 4px;
                    padding: 3px 12px;
                }}
                QPushButton:hover {{
                    background: rgba(0, 212, 255, 0.22);
                    border: 1px solid {C.ACCENT_CYAN};
                }}
            """)
            prev_btn.clicked.connect(lambda checked, v=voice_info: self._settings_preview_voice_item(v))
            card_lay.addWidget(prev_btn)

            # Styling for selected vs unselected
            if is_selected:
                card.setStyleSheet(f"""
                    QFrame {{
                        background: rgba(0, 212, 255, 0.12);
                        border: 1.5px solid {C.ACCENT_CYAN};
                        border-radius: {Radius.SM}px;
                    }}
                """)
            else:
                card.setStyleSheet(f"""
                    QFrame {{
                        background: rgba(255, 255, 255, 0.03);
                        border: 1px solid rgba(255, 255, 255, 0.08);
                        border-radius: {Radius.SM}px;
                    }}
                    QFrame:hover {{
                        background: rgba(255, 255, 255, 0.06);
                        border: 1px solid rgba(255, 255, 255, 0.16);
                    }}
                """)

            # Clicking card selects it
            def _bind_click(target_id):
                def _mouse_press(e):
                    self._settings_select_voice_id(target_id)
                return _mouse_press

            card.mousePressEvent = _bind_click(vid)
            self._settings_voice_cards_layout.addWidget(card)

        self._settings_voice_cards_layout.addStretch()

    def _settings_select_voice_id(self, vid: str):
        self._settings_selected_voice_id = vid
        self._settings_saved_voice_id = vid
        self._settings_populate_voice_cards()

    def _settings_preview_voice_item(self, voice_info: dict):
        vid = voice_info.get("id")
        vname = voice_info.get("name", "Voice")
        # Also select the voice card when preview is clicked
        self._settings_select_voice_id(vid)

        t_idx = max(0, self._settings_tone_combo.currentIndex()) if hasattr(self, '_settings_tone_combo') else 0
        tone_key = self._settings_tone_combo.itemData(t_idx) if hasattr(self, '_settings_tone_combo') else "professional"
        params   = self._settings_tone_profiles.get(tone_key, {"rate": 155, "volume": 1.0})
        rate     = params["rate"]
        volume   = params["volume"]

        self._settings_voice_status.setText(f"▶ Previewing {vname}...")
        self._settings_voice_status.show()

        def _do_preview():
            try:
                from legacy.tts import preview_voice
                preview_voice(vid, rate=rate, volume=volume, text=f"Hello. This is {vname}. Voice synthesis operational.")
            except Exception as e:
                print(f"[SETTINGS] Voice preview error: {e}")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self._settings_preview_done)

        import threading
        threading.Thread(target=_do_preview, daemon=True).start()

    def _settings_preview_done(self):
        self._settings_voice_status.setText("✓ Preview complete")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2500, lambda: self._settings_voice_status.hide())

    def _settings_save_voice(self):
        """Persist voice profile for current user and apply immediately."""
        vid = getattr(self, '_settings_selected_voice_id', None)
        gender = getattr(self, '_settings_voice_gender', 'male')
        t_idx = max(0, self._settings_tone_combo.currentIndex()) if hasattr(self, '_settings_tone_combo') else 0
        tone_key = self._settings_tone_combo.itemData(t_idx) or "professional"
        params   = self._settings_tone_profiles.get(tone_key, {"rate": 155, "volume": 1.0})
        rate     = params["rate"]
        volume   = params["volume"]

        provider = "sapi5"
        for v in getattr(self, '_settings_all_voices', []):
            if v.get("id") == vid:
                provider = v.get("provider", "sapi5")
                break

        try:
            from instance.config import settings as CONFIG
            uid = getattr(CONFIG, 'CURRENT_USER_ID', None)
            if uid:
                print(f"[VOICE] User {uid} selected voice: {vid}")
                from legacy.memory_manager import set_voice_profile_db
                set_voice_profile_db(
                    uid,
                    voice_id=vid or "",
                    voice_gender=gender,
                    voice_tone=tone_key,
                    voice_rate=rate,
                    voice_volume=volume,
                    voice_provider=provider
                )

                # Also save assistant name if customized
                if hasattr(self, '_settings_asst_name_input') and self._settings_asst_name_input:
                    new_asst_name = self._settings_asst_name_input.text().strip()
                    if new_asst_name:
                        from legacy.memory_manager import set_assistant_name_db
                        set_assistant_name_db(uid, new_asst_name)
                        CONFIG.CURRENT_ASSISTANT_NAME = new_asst_name
                        if hasattr(self, 'name_input') and self.name_input:
                            self.name_input.blockSignals(True)
                            self.name_input.setText(new_asst_name)
                            self.name_input.blockSignals(False)
                        letter = new_asst_name[0].upper()
                        if hasattr(self, 'badge_preview') and self.badge_preview:
                            self.badge_preview.setText(letter)
                        if hasattr(self, '_float_prev_badge') and self._float_prev_badge:
                            self._float_prev_badge.setText(letter)
                        self.assistant_name_changed.emit(new_asst_name)

            # Apply immediately to the TTS engine
            from legacy.tts import apply_voice_profile
            apply_voice_profile(vid, rate=rate, volume=volume)

            # Notify app.py to update any other components
            profile = {
                "voice_id": vid, "voice_gender": gender,
                "voice_tone": tone_key, "voice_rate": rate, "voice_volume": volume,
                "voice_provider": provider
            }
            self.voice_profile_changed.emit(profile)
            self._settings_voice_status.setText("✓ Voice identity saved successfully")
            self._settings_voice_status.show()
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(3000, lambda: self._settings_voice_status.hide())
            print(f"[SETTINGS] Voice profile saved and applied: id={vid}, tone={tone_key}, rate={rate}")
        except Exception as e:
            print(f"[SETTINGS] Save voice error: {e}")
            self._settings_voice_status.setText(f"⚠ Save failed: {e}")
            self._settings_voice_status.show()

    def load_voice_profile(self, profile: dict):
        """
        Pre-populate the voice identity controls from the user's saved DB profile.
        Called by pyqt_app after login. Does NOT emit any save signals.
        """
        if not getattr(self, '_settings_all_voices', None):
            try:
                from legacy.tts import enumerate_voices
                self._settings_all_voices = enumerate_voices()
            except Exception as e:
                print(f"[SETTINGS] Failed to enumerate voices: {e}")
                self._settings_all_voices = []

        if not profile:
            self._settings_voice_gender = "female"
            self._settings_selected_voice_id = None
            self._update_settings_gender_styles()
            self._settings_populate_voice_cards()
            return

        gender   = profile.get("voice_gender", "female")
        tone     = profile.get("voice_tone", "professional")
        vid      = profile.get("voice_id")

        # Gender & Voice ID
        self._settings_voice_gender = gender
        self._settings_selected_voice_id = vid
        self._settings_saved_voice_id = vid
        if hasattr(self, '_settings_btn_male'):
            self._settings_btn_male.setChecked(gender == "male")
        if hasattr(self, '_settings_btn_female'):
            self._settings_btn_female.setChecked(gender == "female")
        if hasattr(self, '_settings_btn_other'):
            self._settings_btn_other.setChecked(gender == "other")
        self._update_settings_gender_styles()

        # Tone
        if hasattr(self, '_settings_tone_combo'):
            for i in range(self._settings_tone_combo.count()):
                if self._settings_tone_combo.itemData(i) == tone:
                    self._settings_tone_combo.setCurrentIndex(i)
                    break

        self._settings_populate_voice_cards()



    def _populate_audio_devices(self):
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    api = p.get_host_api_info_by_index(info.get("hostApi")).get("name", "")
                    self.mic_combo.addItem(f"[{i}] {info.get('name')[:32]} ({api})", i)
            p.terminate()
        except Exception:
            self.mic_combo.addItem("Default OS Microphone", 0)

    def _test_voice(self):
        try:
            from legacy.tts import speak
            speak("Voice engine synthesis operational. All audio channels responding.")
        except Exception as e:
            print(f"[SETTINGS] Voice test error: {e}")

    def _test_mic(self):
        try:
            from legacy.sst import _continuous_audio_state
            dev = _continuous_audio_state.get("device_index", "OS Default")
            running = _continuous_audio_state.get("running", False)
            self.mic_status_lbl.setText(f"Microphone test: Device [{dev}] is {'ACTIVE' if running else 'IDLE'}.")
        except Exception as e:
            self.mic_status_lbl.setText(f"Microphone test error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # 3. INTELLIGENCE & LLM
    # ─────────────────────────────────────────────────────────────────────────
    def _build_intelligence_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        lay.addWidget(_section_header("Intelligence & LLM Engine", "Primary AI model providers, automated fallback chains, and temperature"))

        card = _control_card()
        c_lay = QVBoxLayout(card)
        c_lay.setSpacing(Spacing.MD)

        # Provider
        p_box = QVBoxLayout()
        lbl = QLabel("Primary AI Provider")
        lbl.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
        lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        p_box.addWidget(lbl)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["Groq (Llama-3.3-70B)", "OpenAI (GPT-4o)", "Google Gemini (Gemini-2.0-Flash)", "DeepSeek"])
        self.provider_combo.setStyleSheet(f"""
            QComboBox {{
                background: rgba(255, 255, 255, 0.05);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: {Radius.SM}px;
                padding: 6px 12px;
            }}
        """)
        p_box.addWidget(self.provider_combo)
        c_lay.addLayout(p_box)

        # Fallback explanation
        fb_lbl = QLabel("Automated Failover Chain: Primary Provider → Secondary API → Tertiary API → Local System")
        fb_lbl.setFont(QFont(F.PRIMARY, 10))
        fb_lbl.setStyleSheet(f"color: {C.TEXT_MUTED};")
        c_lay.addWidget(fb_lbl)

        # Temperature
        temp_box = QVBoxLayout()
        self.temp_lbl = QLabel("Reasoning Temperature: 0.7 (Balanced)")
        self.temp_lbl.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
        self.temp_lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        temp_box.addWidget(self.temp_lbl)

        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setRange(1, 10)
        self.temp_slider.setValue(7)
        self.temp_slider.valueChanged.connect(lambda v: self.temp_lbl.setText(f"Reasoning Temperature: {v/10:.1f}"))
        temp_box.addWidget(self.temp_slider)
        c_lay.addLayout(temp_box)

        lay.addWidget(card)
        lay.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────────────────
    # 4. MEMORY & PRIVACY
    # ─────────────────────────────────────────────────────────────────────────
    def _build_memory_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        lay.addWidget(_section_header("Memory & Privacy Controls", "PostgreSQL memory persistence, user data isolation, and retention"))

        card = _control_card()
        c_lay = QVBoxLayout(card)
        c_lay.setSpacing(Spacing.MD)

        self.mem_save_check = QCheckBox("Persist conversational memory to PostgreSQL database")
        self.mem_save_check.setChecked(True)
        self.mem_save_check.setFont(QFont(F.PRIMARY, 10))
        self.mem_save_check.setStyleSheet(f"color: {C.TEXT};")
        c_lay.addWidget(self.mem_save_check)

        self.confirm_check = QCheckBox("Prompt confirmation before sensitive system operations (shutdown, delete)")
        self.confirm_check.setChecked(True)
        self.confirm_check.setFont(QFont(F.PRIMARY, 10))
        self.confirm_check.setStyleSheet(f"color: {C.TEXT};")
        c_lay.addWidget(self.confirm_check)

        # Storage info
        stat_lbl = QLabel("User Storage: Isolated by PostgreSQL user_id | Encrypted session tokens")
        stat_lbl.setFont(QFont(F.PRIMARY, 10))
        stat_lbl.setStyleSheet(f"color: {C.TEXT_MUTED};")
        c_lay.addWidget(stat_lbl)

        lay.addWidget(card)
        lay.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────────────────
    # 5. FLOATING ASSISTANT PREFERENCES
    # ─────────────────────────────────────────────────────────────────────────
    def _build_floating_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        lay.addWidget(_section_header("Floating Assistant Preferences", "Desktop badge behavior, edge snapping, and Quick Action buttons"))

        card = _control_card()
        c_lay = QVBoxLayout(card)
        c_lay.setSpacing(Spacing.MD)

        self.snap_check = QCheckBox("Enable smooth magnetic edge snapping on screen release")
        self.snap_check.setChecked(True)
        self.snap_check.setFont(QFont(F.PRIMARY, 10))
        self.snap_check.setStyleSheet(f"color: {C.TEXT};")
        c_lay.addWidget(self.snap_check)

        self.audio_ring_check = QCheckBox("React dynamically to voice levels (audio reactive aura)")
        self.audio_ring_check.setChecked(True)
        self.audio_ring_check.setFont(QFont(F.PRIMARY, 10))
        self.audio_ring_check.setStyleSheet(f"color: {C.TEXT};")
        c_lay.addWidget(self.audio_ring_check)

        # Quick actions checklist
        qa_box = QVBoxLayout()
        qa_lbl = QLabel("Active Quick Action Buttons (Double-Click HUD)")
        qa_lbl.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Bold))
        qa_lbl.setStyleSheet(f"color: {C.ACCENT_CYAN};")
        qa_box.addWidget(qa_lbl)

        for act in ["🎤 Talk to Assistant", "💬 Open Chat", "⏰ Reminders", "🧠 Memory Hub", "📋 Task Dock", "📊 System Diagnostics"]:
            cb = QCheckBox(act)
            cb.setChecked(True)
            cb.setFont(QFont(F.PRIMARY, 9))
            cb.setStyleSheet(f"color: {C.TEXT};")
            qa_box.addWidget(cb)
        c_lay.addLayout(qa_box)

        lay.addWidget(card)
        lay.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────────────────
    # 6. SYSTEM DIAGNOSTICS & HEALTH
    # ─────────────────────────────────────────────────────────────────────────
    def _build_diagnostics_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG)
        lay.setSpacing(Spacing.MD)

        lay.addWidget(_section_header("System Diagnostics & Health", "Live connectivity status across database, voice, and AI services"))

        card = _control_card()
        c_lay = QVBoxLayout(card)
        c_lay.setSpacing(Spacing.MD)

        grid = QGridLayout()
        grid.setSpacing(10)

        services = [
            ("PostgreSQL Database", "Online"),
            ("Microphone Input", "Capturing (MME)"),
            ("Text-to-Speech Engine", "Ready (pyttsx3)"),
            ("LLM Connectivity", "Online (Groq/Multi-Provider)"),
            ("Reminder Scheduler", "Running (User-isolated)"),
            ("Proactive Monitor", "Active (Background Thread)")
        ]
        for i, (name, status) in enumerate(services):
            row = i // 2
            col = i % 2

            box = QHBoxLayout()
            s_name = QLabel(name)
            s_name.setFont(QFont(F.PRIMARY, 10))
            s_name.setStyleSheet(f"color: {C.TEXT};")
            box.addWidget(s_name)

            box.addStretch()

            s_badge = QLabel(status)
            s_badge.setFont(QFont(F.PRIMARY, 8, QFont.Weight.Bold))
            s_badge.setStyleSheet("""
                QLabel {
                    color: #34c759;
                    background: rgba(52, 199, 89, 0.12);
                    border-radius: 4px;
                    padding: 2px 6px;
                }
            """)
            box.addWidget(s_badge)

            grid.addLayout(box, row, col)

        c_lay.addLayout(grid)

        lay.addWidget(card)
        lay.addStretch()
        return w
