"""
Smart Assistant — Distinct Floating Assistant, Quick Actions HUD & Control Center
Cybernetic hexagonal badge displaying the dynamic Initial Letter of the active assistant.
Two Distinct Interaction Modes:
1. DOUBLE-CLICK: Compact, context-aware Quick Actions HUD ("What do I want to DO right now?")
2. RIGHT-CLICK: Structured Assistant Control Center ("How do I CONTROL or MANAGE the Assistant?")
"""

import math
import os
from PyQt6.QtWidgets import (
    QWidget, QApplication, QMenu, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QFrame, QGraphicsDropShadowEffect, QSizePolicy
)
from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QRect, QRectF, pyqtSignal, QPropertyAnimation,
    QEasingCurve, QPointF
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QRadialGradient, QLinearGradient,
    QPainterPath, QFont
)

from modules.ui.design_system import (
    C, F, Radius, Spacing,
    hex_to_rgb, rgba_str, ensure_visible_accent
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. DOUBLE-CLICK: QUICK ACTIONS HUD PANEL (Context-Aware / Action-Oriented)
# ─────────────────────────────────────────────────────────────────────────────
class QuickActionsPanel(QWidget):
    """
    Compact, action-oriented Quick Action HUD.
    Answers: 'What do I want to DO right now?'
    Dynamically adapts actions based on real Assistant state (idle, speaking, executing).
    """
    action_triggered = pyqtSignal(str)

    def __init__(self, assistant_name: str = "Assistant", parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(280)

        self._assistant_name = assistant_name
        self._state = "idle"
        self._custom_hex = "#00D4FF"

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        self._card = QFrame()
        self._card.setObjectName("QuickCard")
        self._card.setStyleSheet(f"""
            QFrame#QuickCard {{
                background: rgba(6, 12, 20, 248);
                border: 1px solid rgba(0, 212, 255, 0.38);
                border-radius: {Radius.LG}px;
            }}
        """)
        self._shadow = QGraphicsDropShadowEffect(self._card)
        self._shadow.setBlurRadius(28)
        self._shadow.setColor(QColor(0, 212, 255, 75))
        self._shadow.setOffset(0, 0)
        self._card.setGraphicsEffect(self._shadow)

        self._card_layout = QVBoxLayout(self._card)
        self._card_layout.setContentsMargins(14, 14, 14, 14)
        self._card_layout.setSpacing(6)

        # Header
        header_box = QHBoxLayout()
        header_box.setContentsMargins(0, 0, 0, 0)

        self._title_lbl = QLabel("QUICK ACTIONS")
        self._title_lbl.setFont(F.mono(9))
        self._title_lbl.setStyleSheet("color: #00d4ff; font-weight: 700; letter-spacing: 1px; background: transparent;")
        header_box.addWidget(self._title_lbl)

        self._status_badge = QLabel("● IDLE")
        self._status_badge.setFont(F.mono(8))
        self._status_badge.setStyleSheet("color: #00e56b; font-weight: 700; background: rgba(0, 229, 107, 0.12); border-radius: 4px; padding: 2px 6px;")
        header_box.addWidget(self._status_badge)

        header_box.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(18, 18)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("color: #6d8e9e; background: transparent; border: none; font-size: 11px;")
        close_btn.clicked.connect(self.hide)
        header_box.addWidget(close_btn)

        self._card_layout.addLayout(header_box)

        self._sep = QFrame()
        self._sep.setFixedHeight(1)
        self._sep.setStyleSheet("background: rgba(0, 212, 255, 0.16);")
        self._card_layout.addWidget(self._sep)

        # Action button container
        self._btn_container = QWidget()
        self._btn_container_layout = QVBoxLayout(self._btn_container)
        self._btn_container_layout.setContentsMargins(0, 4, 0, 0)
        self._btn_container_layout.setSpacing(6)
        self._card_layout.addWidget(self._btn_container)

        root.addWidget(self._card)

        # Build initial buttons
        self.update_context(self._state, self._assistant_name)

    def set_accent_color(self, hex_color: str):
        """Dynamically update Quick Actions HUD border and title accent."""
        hex_color = ensure_visible_accent(hex_color)
        self._custom_hex = hex_color
        self._card.setStyleSheet(f"""
            QFrame#QuickCard {{
                background: rgba(6, 12, 20, 248);
                border: 1px solid {rgba_str(hex_color, 0.45)};
                border-radius: {Radius.LG}px;
            }}
        """)
        r, g, b = hex_to_rgb(hex_color)
        if hasattr(self, '_shadow'):
            self._shadow.setColor(QColor(r, g, b, 80))
        if hasattr(self, '_title_lbl'):
            self._title_lbl.setStyleSheet(f"color: {hex_color}; font-weight: 700; letter-spacing: 1px; background: transparent;")
        if hasattr(self, '_sep'):
            self._sep.setStyleSheet(f"background: {rgba_str(hex_color, 0.2)};")

    def set_assistant_name(self, name: str):
        """Update assistant name and rebuild contextual action panel."""
        self._assistant_name = name or "Assistant"
        self.update_context(self._state, self._assistant_name)

    def update_context(self, state: str, assistant_name: str):
        """Rebuild actions dynamically based on the real Assistant runtime state."""
        self._state = state
        self._assistant_name = assistant_name

        # Update badge
        state_text = f"● {state.upper()}"
        if state == "speaking":
            self._status_badge.setText(state_text)
            self._status_badge.setStyleSheet("color: #00e56b; font-weight: 700; background: rgba(0, 229, 107, 0.15); border-radius: 4px; padding: 2px 6px;")
        elif state in ("executing", "processing", "planning"):
            self._status_badge.setText(state_text)
            self._status_badge.setStyleSheet("color: #ff8c00; font-weight: 700; background: rgba(255, 140, 0, 0.15); border-radius: 4px; padding: 2px 6px;")
        elif state == "listening":
            self._status_badge.setText(state_text)
            self._status_badge.setStyleSheet("color: #00a8ff; font-weight: 700; background: rgba(0, 168, 255, 0.15); border-radius: 4px; padding: 2px 6px;")
        else:
            self._status_badge.setText("● READY")
            self._status_badge.setStyleSheet("color: #00d4ff; font-weight: 700; background: rgba(0, 212, 255, 0.12); border-radius: 4px; padding: 2px 6px;")

        # Clear previous dynamic buttons immediately
        while self._btn_container_layout.count():
            item = self._btn_container_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        # Build contextual action set
        if state == "speaking":
            # Priority action: Stop speech
            actions = [
                ("🛑 Stop Speaking", "stop_speaking", True),
                ("💬 View Response", "recent_conversation", False),
                ("📋 Task Monitor", "current_task", False),
                ("📊 System Health", "system_status", False),
            ]
        elif state in ("executing", "processing", "planning"):
            # Priority action: Stop task
            actions = [
                ("⏹ Stop / Cancel Task", "stop_cancel", True),
                ("📋 Inspect Active Task", "current_task", False),
                ("🎤 Voice Interruption", "talk", False),
                ("📊 System Health", "system_status", False),
            ]
        else:
            # Idle / normal interaction set (compact & focused)
            actions = [
                ("🗔 Open Dashboard", "dashboard", False),
                ("🎤 Talk to Assistant", "talk", False),
                ("⌨ Type a Request", "type_request", False),
                ("⏰ Remind Me", "reminders", False),
                ("💬 Recent Conversation", "recent_conversation", False),
                ("🧠 Search Memory", "memory", False),
                ("📋 Task Monitor", "current_task", False),
                ("📊 System Health", "system_status", False),
            ]

        for label, act, is_urgent in actions:
            btn = QPushButton(label)
            btn.setFixedHeight(36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
            if is_urgent:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: rgba(255, 71, 87, 0.18);
                        color: #ff5252;
                        border: 1px solid rgba(255, 71, 87, 0.45);
                        border-radius: {Radius.SM}px;
                        padding: 6px 12px;
                        text-align: left;
                        font-weight: 700;
                    }}
                    QPushButton:hover {{
                        background: rgba(255, 71, 87, 0.32);
                        color: #ffffff;
                        border: 1px solid #ff5252;
                    }}
                """)
            else:
                acc = getattr(self, '_custom_hex', '#00D4FF')
                r, g, b = hex_to_rgb(acc)
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: rgba(255, 255, 255, 0.04);
                        color: {C.TEXT};
                        border: 1px solid rgba(255, 255, 255, 0.07);
                        border-radius: {Radius.SM}px;
                        padding: 6px 12px;
                        text-align: left;
                    }}
                    QPushButton:hover {{
                        background: rgba({r}, {g}, {b}, 0.14);
                        color: {acc};
                        border: 1px solid rgba({r}, {g}, {b}, 0.35);
                    }}
                """)
            btn.clicked.connect(lambda _, a=act: self._on_action(a))
            self._btn_container_layout.addWidget(btn)

        self.adjustSize()

    def _on_action(self, act: str):
        self.hide()
        self.action_triggered.emit(act)


# ─────────────────────────────────────────────────────────────────────────────
# 2. RIGHT-CLICK: ASSISTANT CONTROL CENTER PANEL (Management & System Controls)
# ─────────────────────────────────────────────────────────────────────────────
class AssistantControlCenterPanel(QWidget):
    """
    Structured, management-oriented Assistant Control Center.
    Answers: 'How do I CONTROL or MANAGE the Assistant?'
    Provides categorized controls for system lifecycle, audio, session, and diagnostics.
    """
    action_triggered = pyqtSignal(str)

    def __init__(self, assistant_name: str = "Assistant", username: str = "User", parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(280)

        self._assistant_name = assistant_name
        self._username = username

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        card = QFrame()
        card.setObjectName("ControlCard")
        card.setStyleSheet(f"""
            QFrame#ControlCard {{
                background: rgba(8, 14, 22, 250);
                border: 1px solid rgba(0, 212, 255, 0.32);
                border-radius: {Radius.LG}px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(32)
        shadow.setColor(QColor(0, 212, 255, 65))
        shadow.setOffset(0, 0)
        card.setGraphicsEffect(shadow)
        self._card = card
        self._shadow = shadow

        self._layout = QVBoxLayout(card)
        self._layout.setContentsMargins(14, 14, 14, 14)
        self._layout.setSpacing(8)

        # Header
        top = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        main_title = QLabel("ASSISTANT CONTROL CENTER")
        main_title.setFont(F.mono(9))
        main_title.setStyleSheet("color: #00d4ff; font-weight: 700; letter-spacing: 0.8px; background: transparent;")
        title_box.addWidget(main_title)
        self._main_title = main_title

        sub_title = QLabel("SYSTEM MANAGEMENT & CONTROLS")
        sub_title.setFont(F.mono(7))
        sub_title.setStyleSheet("color: #5d7e91; letter-spacing: 0.5px; background: transparent;")
        title_box.addWidget(sub_title)
        top.addLayout(title_box)

        top.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(18, 18)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("color: #6d8e9e; background: transparent; border: none; font-size: 11px;")
        close_btn.clicked.connect(self.hide)
        top.addWidget(close_btn)
        self._layout.addLayout(top)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(0, 212, 255, 0.16);")
        self._layout.addWidget(sep)
        self._sep = sep

        # ── Section 1: ASSISTANT RUNTIME ──
        self._add_section_header("ASSISTANT RUNTIME")
        self._add_action_btn("🗔 Assistant Dashboard", "dashboard")
        self._add_action_btn("🔄 Restart Assistant", "restart")
        self._add_action_btn("⏻ Exit Assistant", "quit", is_destructive=True)

        # ── Section 2: AUDIO & INPUT CONTROLS ──
        self._add_section_header("AUDIO & INPUT CONTROLS")
        self._mic_btn = self._add_action_btn("🎙 Continuous Listening", "toggle_listening")
        self._add_action_btn("🔇 Silence Audio Output", "mute_tts")
        self._add_action_btn("🔄 Re-calibrate Microphone", "reset_mic")

        # ── Section 3: OPERATOR & SESSION ──
        self._add_section_header("OPERATOR & SESSION")
        self._operator_badge = QLabel(f"👤 Operator: {self._username}")
        self._operator_badge.setFont(F.mono(9))
        self._operator_badge.setStyleSheet("color: #8da4b5; padding: 4px 8px; background: rgba(255, 255, 255, 0.03); border-radius: 4px;")
        self._layout.addWidget(self._operator_badge)

        self._callsign_badge = QLabel(f"✦ Callsign: {self._assistant_name}")
        self._callsign_badge.setFont(F.mono(9))
        self._callsign_badge.setStyleSheet("color: #00d4ff; padding: 4px 8px; background: rgba(0, 212, 255, 0.06); border-radius: 4px;")
        self._layout.addWidget(self._callsign_badge)

        self._add_action_btn("🚪 Sign Out / Switch User", "logout")

        # ── Section 4: INFRASTRUCTURE & SETTINGS ──
        self._add_section_header("INFRASTRUCTURE & SETTINGS")
        self._add_action_btn("⚙ System Preferences", "settings")
        self._add_action_btn("📊 Diagnostics && Telemetry", "telemetry")
        self._add_action_btn("🌐 Open Web Dashboard", "web_dashboard")

        root.addWidget(card)

    def set_assistant_name(self, name: str):
        """Update callsign and identity badge in control center."""
        self._assistant_name = name or "Assistant"
        if hasattr(self, '_callsign_badge') and self._callsign_badge:
            self._callsign_badge.setText(f"✦ Callsign: {self._assistant_name}")

    def _add_section_header(self, text: str):
        lbl = QLabel(text)
        lbl.setFont(F.mono(8))
        lbl.setStyleSheet("color: #00d4ff; font-weight: 700; letter-spacing: 0.8px; margin-top: 4px; background: transparent;")
        self._layout.addWidget(lbl)

    def _add_action_btn(self, label: str, act: str, is_destructive: bool = False) -> QPushButton:
        btn = QPushButton(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Medium))
        if is_destructive:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 71, 87, 0.08);
                    color: #ff5252;
                    border: 1px solid rgba(255, 71, 87, 0.25);
                    border-radius: {Radius.SM}px;
                    padding: 5px 10px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: rgba(255, 71, 87, 0.22);
                    color: #ffffff;
                    border: 1px solid #ff5252;
                }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.03);
                    color: {C.TEXT};
                    border: 1px solid rgba(255, 255, 255, 0.06);
                    border-radius: {Radius.SM}px;
                    padding: 5px 10px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: rgba(0, 212, 255, 0.12);
                    color: {C.ACCENT_CYAN};
                    border: 1px solid rgba(0, 212, 255, 0.30);
                }}
            """)
        btn.clicked.connect(lambda _, a=act: self._on_action(a))
        self._layout.addWidget(btn)
        return btn

    def update_context(self, assistant_name: str, username: str, is_listening: bool = True):
        self._assistant_name = assistant_name
        self._username = username
        self._operator_badge.setText(f"👤 Operator: {self._username}")
        self._callsign_badge.setText(f"✦ Callsign: {self._assistant_name}")
        mic_status = "Active" if is_listening else "Muted"
        self._mic_btn.setText(f"🎙 Continuous Listening [{mic_status}]")

    def set_accent_color(self, hex_color: str):
        """Re-theme the Control Center panel (border, shadow, titles, callsign badge, button hovers)."""
        acc = ensure_visible_accent(str(hex_color).strip())
        r, g, b = hex_to_rgb(acc)
        # Card border + shadow
        if hasattr(self, '_card'):
            self._card.setStyleSheet(f"""
                QFrame#ControlCard {{
                    background: rgba(8, 14, 22, 250);
                    border: 1px solid rgba({r}, {g}, {b}, 0.32);
                    border-radius: {Radius.LG}px;
                }}
            """)
        if hasattr(self, '_shadow'):
            self._shadow.setColor(QColor(r, g, b, 65))
        # Header title
        if hasattr(self, '_main_title'):
            self._main_title.setStyleSheet(f"color: {acc}; font-weight: 700; letter-spacing: 0.8px; background: transparent;")
        # Separator
        if hasattr(self, '_sep'):
            self._sep.setStyleSheet(f"background: rgba({r}, {g}, {b}, 0.16);")
        # Section headers
        for lbl in self.findChildren(QLabel):
            ss = lbl.styleSheet()
            if 'letter-spacing: 0.8px' in ss and 'margin-top: 4px' in ss:
                lbl.setStyleSheet(f"color: {acc}; font-weight: 700; letter-spacing: 0.8px; margin-top: 4px; background: transparent;")
        # Callsign badge
        if hasattr(self, '_callsign_badge'):
            self._callsign_badge.setStyleSheet(f"color: {acc}; padding: 4px 8px; background: rgba({r}, {g}, {b}, 0.06); border-radius: 4px;")
        # Non-destructive action button hovers
        for btn in self.findChildren(QPushButton):
            ss = btn.styleSheet()
            if 'rgba(255, 71, 87' not in ss and btn.text() not in ('✕',):
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: rgba(255, 255, 255, 0.03);
                        color: {C.TEXT};
                        border: 1px solid rgba(255, 255, 255, 0.06);
                        border-radius: {Radius.SM}px;
                        padding: 5px 10px;
                        text-align: left;
                    }}
                    QPushButton:hover {{
                        background: rgba({r}, {g}, {b}, 0.12);
                        color: {acc};
                        border: 1px solid rgba({r}, {g}, {b}, 0.30);
                    }}
                """)

    def _on_action(self, act: str):
        self.hide()
        self.action_triggered.emit(act)


# ─────────────────────────────────────────────────────────────────────────────
# 3. DISTINCT CYBERNETIC FLOATING ASSISTANT CONTROL
# ─────────────────────────────────────────────────────────────────────────────
class FloatingLauncher(QWidget):
    """
    Distinct Cybernetic Hex-Badge Floating Assistant.
    Displays dynamic Initial Letter of the active assistant at its core.

    Two Distinct Interaction Modes:
    - DOUBLE-CLICK: Opens compact Quick Actions HUD ('What do I want to DO right now?')
    - RIGHT-CLICK: Opens Assistant Control Center ('How do I CONTROL or MANAGE the Assistant?')
    - SINGLE-CLICK: Focuses / toggles main window.
    - DRAGGABLE: Magnetically snaps to screen edge upon release.
    """
    single_clicked   = pyqtSignal()
    double_clicked   = pyqtSignal()
    action_requested = pyqtSignal(str)
    position_changed = pyqtSignal(int, int)

    # State colors: (R, G, B)
    _STATE_COLORS = {
        "idle":       (0, 212, 255),    # Cyan
        "listening":  (0, 170, 255),    # Blue
        "thinking":   (168, 85, 247),   # Violet
        "planning":   (138, 43, 226),   # Purple
        "executing":  (255, 140, 0),    # Amber
        "speaking":   (0, 229, 107),    # Emerald
        "error":      (255, 71, 87),    # Crimson
    }

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(86, 86)

        # State
        self._state = "idle"
        self._assistant_name = "Jarvis"
        self._username = "Operator"
        self._initial_letter = "F"
        self._hovered = False
        self._dragging = False
        self._drag_start_pos = QPoint()
        self._audio_lvl = 0.0

        # Animation parameters
        self._t = 0.0
        self._glow_phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

        # User-chosen accent color (overrides idle color only)
        self._custom_rgb: tuple | None = None

        # Click detection (distinguish single vs double click)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._on_single_click_timeout)

        # Mode 1: Double-Click Quick Actions HUD
        self._quick_hud = QuickActionsPanel(self._assistant_name)
        self._quick_hud.action_triggered.connect(self.action_requested.emit)

        # Mode 2: Right-Click Assistant Control Center
        self._control_center = AssistantControlCenterPanel(self._assistant_name, self._username)
        self._control_center.action_triggered.connect(self.action_requested.emit)

        # Mode 3: Ephemeral Visual Response Surface
        from modules.ui.visual_response_surface import VisualResponsePanel
        self._visual_panel = VisualResponsePanel()

        # Initial placement: Bottom-Right screen
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - 110, screen.height() - 140)

    def set_assistant_name(self, name: str):
        """Update assistant identity while maintaining the centered 'F' for the Pulse Ring design."""
        self._assistant_name = name or "Assistant"
        self._initial_letter = "F"
        self.setToolTip(f"{self._assistant_name} (Click: Focus | Double-click: Quick Actions | Right-click: Controls)")
        if hasattr(self, '_quick_hud') and self._quick_hud:
            self._quick_hud.set_assistant_name(self._assistant_name)
        if hasattr(self, '_control_center') and self._control_center:
            self._control_center.set_assistant_name(self._assistant_name)
        self.update()

    def set_user_context(self, username: str, assistant_name: str):
        """Update user session info for control center."""
        self._username = username or "Operator"
        self.set_assistant_name(assistant_name)

    def set_accent_color(self, hex_color: str):
        """
        Apply user-chosen floating button accent color.
        Overrides the idle glow; semantic state colors (listening, speaking, etc.) are preserved.
        Propagates the accent to Quick Actions HUD, Control Center, and Visual Response panel.
        """
        from modules.ui.design_system import hex_to_rgb, ensure_visible_accent
        safe_hex = ensure_visible_accent(str(hex_color).strip())
        self._custom_hex = safe_hex
        self._custom_rgb = hex_to_rgb(safe_hex)
        # Propagate to Quick Actions HUD
        if hasattr(self, '_quick_hud') and self._quick_hud:
            self._quick_hud.set_accent_color(safe_hex)
        # Propagate to Control Center panel
        if hasattr(self, '_control_center') and self._control_center:
            self._control_center.set_accent_color(safe_hex)
        # Propagate to Ephemeral Visual Response Surface
        if hasattr(self, '_visual_panel') and self._visual_panel:
            self._visual_panel.set_accent_color(safe_hex)
        self.update()

    def show_visual_response(self, visual_response):
        """Display an ephemeral visual response next to the floating button."""
        if hasattr(self, '_visual_panel') and self._visual_panel:
            self._visual_panel.show_response(visual_response, anchor_widget=self)

    def dismiss_visual_response(self):
        """Dismiss active ephemeral visual response."""
        if hasattr(self, '_visual_panel') and self._visual_panel:
            self._visual_panel.dismiss()

    def set_state(self, state: str):
        """Update state: idle, listening, thinking, planning, executing, speaking, error."""
        if state != self._state:
            self._state = state
            # If quick HUD is open, adapt contextually
            if self._quick_hud and self._quick_hud.isVisible():
                self._quick_hud.update_context(self._state, self._assistant_name)
            self.update()

    def set_audio_level(self, level: float):
        """Live audio level (0.0 to 1.0)."""
        self._audio_lvl = max(0.0, min(1.0, level))

    def _state_rgb(self):
        # Idle state: use custom accent if user has personalized it
        if self._state == "idle" and self._custom_rgb:
            return self._custom_rgb
        return self._STATE_COLORS.get(self._state, (0, 212, 255))

    def _tick(self):
        self._t += 0.05
        self._glow_phase = (math.sin(self._t * 2.0) + 1.0) / 2.0
        self.update()

    # ── Paint Event: Pulse Ring Design (Option 10) ───────────────────────────
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2.0, h / 2.0
        r, g, b = self._state_rgb()

        # Dynamic size with audio reactivity and hover boost
        audio_boost = self._audio_lvl * 5.5 if self._state in ("listening", "speaking") else 0.0
        base_radius = 28.5 + (audio_boost * 0.5)
        if self._hovered:
            base_radius += 1.5

        # 1. Subtle Expanding Pulse Wave (Radiating ripple effect)
        wave_speed = 1.2 if self._state == "thinking" else 0.7
        wave_prog = (self._t * wave_speed) % 1.0
        wave_r = base_radius + 2.0 + (wave_prog * 9.5)
        wave_alpha = int(max(0, 42 * (1.0 - wave_prog)))
        if wave_alpha > 0:
            wave_pen = QPen(QColor(r, g, b, wave_alpha))
            wave_pen.setWidthF(1.2)
            p.setPen(wave_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), wave_r, wave_r)

        # 2. Outer Subtle Pulse Ring (Ambient breathing ring)
        pulse_freq = 3.2 if self._state == "thinking" else 2.2
        pulse_r = base_radius + 5.5 + (math.sin(self._t * pulse_freq) * 1.8) + (audio_boost * 1.0)
        pulse_alpha = int(48 + 48 * self._glow_phase)
        pulse_pen = QPen(QColor(r, g, b, pulse_alpha))
        pulse_pen.setWidthF(1.5)
        p.setPen(pulse_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), pulse_r, pulse_r)

        # 3. Ambient Glow Halo behind the segmented ring
        halo_r = base_radius + 7.5
        halo_grad = QRadialGradient(cx, cy, halo_r)
        halo_grad.setColorAt(0.0, QColor(r, g, b, 0))
        halo_grad.setColorAt(0.68, QColor(r, g, b, int(22 * self._glow_phase)))
        halo_grad.setColorAt(0.92, QColor(r, g, b, int(42 * self._glow_phase)))
        halo_grad.setColorAt(1.0, QColor(r, g, b, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo_grad))
        p.drawEllipse(QPointF(cx, cy), halo_r, halo_r)

        # 4. Faint Continuous Circular Track Ring
        track_pen = QPen(QColor(r, g, b, 45))
        track_pen.setWidthF(1.0)
        p.setPen(track_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), base_radius, base_radius)

        # 5. Segmented Circular Ring (Concentric Arcs with Gaps)
        num_segments = 4
        seg_span = 64.0   # Arc length in degrees
        gap_span = 26.0   # Gap length in degrees
        rot_speed = 52.0 if self._state == "thinking" else (30.0 if self._state == "executing" else 22.0)
        rot_deg = (self._t * rot_speed) % 360.0

        seg_alpha = int(210 + 45 * self._glow_phase)
        seg_pen = QPen(QColor(r, g, b, seg_alpha))
        seg_pen.setWidthF(2.6)
        seg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(seg_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        rect_seg = QRectF(cx - base_radius, cy - base_radius, base_radius * 2.0, base_radius * 2.0)
        for i in range(num_segments):
            start_angle = (rot_deg + i * (seg_span + gap_span)) % 360.0
            p.drawArc(rect_seg, int(start_angle * 16), int(seg_span * 16))

        # 6. Central Dark Cybernetic Glass Core Disc
        core_r = base_radius - 5.5
        core_grad = QRadialGradient(cx, cy, core_r)
        core_grad.setColorAt(0.0, QColor(14, 22, 34, 248))
        core_grad.setColorAt(0.82, QColor(8, 13, 22, 252))
        core_grad.setColorAt(1.0, QColor(4, 7, 13, 255))
        p.setPen(QPen(QColor(r, g, b, 100), 1.2))
        p.setBrush(QBrush(core_grad))
        p.drawEllipse(QPointF(cx, cy), core_r, core_r)

        # 7. Core Glow behind the Initial Letter
        core_glow_r = core_r * 0.75 + (audio_boost * 1.5)
        glow_grad = QRadialGradient(cx, cy, core_glow_r)
        glow_grad.setColorAt(0.0, QColor(r, g, b, 85))
        glow_grad.setColorAt(0.6, QColor(r, g, b, 25))
        glow_grad.setColorAt(1.0, QColor(r, g, b, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow_grad))
        p.drawEllipse(QPointF(cx, cy), core_glow_r, core_glow_r)

        # 8. Center 'F'
        letter = self._initial_letter or "F"
        letter_font = QFont(F.PRIMARY, 19, QFont.Weight.Bold)
        letter_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        p.setFont(letter_font)

        # Drop shadow for depth
        p.setPen(QPen(QColor(0, 0, 0, 190)))
        p.drawText(QRectF(cx - 20, cy - 20 + 1.5, 40, 40),
                   Qt.AlignmentFlag.AlignCenter, letter)

        # Sharp high-contrast letter
        p.setPen(QPen(QColor(245, 250, 255)))
        p.drawText(QRectF(cx - 20, cy - 20, 40, 40),
                   Qt.AlignmentFlag.AlignCenter, letter)

        p.end()

    # ── Mouse Interaction: Single / Double Click & Dragging ───────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._drag_start_pos = e.globalPosition().toPoint()
            self._drag_offset = e.pos()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton:
            delta = e.globalPosition().toPoint() - self._drag_start_pos
            if delta.manhattanLength() > 3:
                self._dragging = True
                new_pos = e.globalPosition().toPoint() - self._drag_offset
                screen = QApplication.primaryScreen().availableGeometry()
                # Constrain within available screen rectangle during free drag
                clamped_x = max(screen.left(), min(new_pos.x(), screen.right() - self.width()))
                clamped_y = max(screen.top(), min(new_pos.y(), screen.bottom() - self.height()))
                self.move(clamped_x, clamped_y)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._dragging:
                self._dragging = False
                self._constrain_to_screen()
                self.position_changed.emit(self.x(), self.y())
            else:
                # Distinguish single vs double click
                if self._click_timer.isActive():
                    self._click_timer.stop()
                    self._on_double_click()
                else:
                    self._click_timer.start(260)

    def _on_single_click_timeout(self):
        """Single click confirmed -> Focus / open main window."""
        self.single_clicked.emit()

    def _on_double_click(self):
        """Double click confirmed -> Open compact Quick Actions HUD."""
        self.double_clicked.emit()
        self._toggle_quick_hud()

    def _toggle_quick_hud(self):
        if self._control_center.isVisible():
            self._control_center.hide()

        if self._quick_hud.isVisible():
            self._quick_hud.hide()
        else:
            self._quick_hud.update_context(self._state, self._assistant_name)
            screen = QApplication.primaryScreen().availableGeometry()
            # Try placing to the left of the button; if too close to screen left, place to right
            hud_x = self.x() - self._quick_hud.width() - 10
            if hud_x < screen.left() + 10:
                hud_x = self.x() + self.width() + 10
            if hud_x + self._quick_hud.width() > screen.right() - 10:
                hud_x = screen.right() - self._quick_hud.width() - 10
            hud_x = max(screen.left() + 10, hud_x)

            # Center vertically with button and clamp to screen
            hud_y = self.y() + (self.height() - self._quick_hud.height()) // 2
            hud_y = min(max(screen.top() + 10, hud_y), screen.bottom() - self._quick_hud.height() - 10)

            self._quick_hud.move(hud_x, hud_y)
            self._quick_hud.show()
            self._quick_hud.raise_()

    # ── Right-Click: Assistant Control Center ──────────────────────────────────
    def contextMenuEvent(self, event):
        """Right click confirmed -> Open structured Assistant Control Center."""
        if self._quick_hud.isVisible():
            self._quick_hud.hide()

        # Check real continuous listening status
        is_listening = True
        try:
            from legacy.sst import is_continuous_audio_running
            is_listening = is_continuous_audio_running()
        except Exception:
            pass

        self._control_center.update_context(self._assistant_name, self._username, is_listening)

        # Position smartly adjacent to badge anywhere on screen
        screen = QApplication.primaryScreen().availableGeometry()
        cc_x = self.x() - self._control_center.width() - 10
        if cc_x < screen.left() + 10:
            cc_x = self.x() + self.width() + 10
        if cc_x + self._control_center.width() > screen.right() - 10:
            cc_x = screen.right() - self._control_center.width() - 10
        cc_x = max(screen.left() + 10, cc_x)

        cc_y = self.y() + (self.height() - self._control_center.height()) // 2
        cc_y = min(max(screen.top() + 10, cc_y), screen.bottom() - self._control_center.height() - 10)

        self._control_center.move(cc_x, cc_y)
        self._control_center.show()
        self._control_center.raise_()

    def _constrain_to_screen(self):
        """
        Keep floating button comfortably within visible screen bounds while
        letting it rest at ANY custom position across the screen chosen by the user.
        """
        screen = QApplication.primaryScreen().availableGeometry()
        target_x = max(screen.left() + 4, min(self.x(), screen.right() - self.width() - 4))
        target_y = max(screen.top() + 4, min(self.y(), screen.bottom() - self.height() - 4))

        if self.pos() != QPoint(target_x, target_y):
            anim = QPropertyAnimation(self, b"pos", self)
            anim.setDuration(120)
            anim.setStartValue(self.pos())
            anim.setEndValue(QPoint(target_x, target_y))
            anim.setEasingCurve(QEasingCurve.Type.OutQuad)
            anim.start()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    # ── TTS Bridge Methods ───────────────────────────────────────────────────
    def start_anim(self):
        self.set_state("speaking")

    def stop_anim(self):
        self.set_state("idle")
