"""
Dashboard Main Window
=====================
The central QMainWindow that composes:
  • Left Sidebar (navigation + user profile)
  • Top Bar (search, actions, notifications, user menu)
  • QStackedWidget with all dashboard pages
  • Bottom Status Strip (assistant state, uptime, current task)

Registers itself as a state listener on the canonical AssistantCore
so the UI reacts to real state changes without polling latency.
"""

from __future__ import annotations

import math
import os
from datetime import datetime
from typing import Callable, Dict, Optional

from PyQt6.QtCore import Qt, QTimer, QSize, QPropertyAnimation, QEasingCurve, pyqtSignal, QEvent, QPoint, QPointF, QRectF, pyqtProperty
from PyQt6.QtGui import QAction, QColor, QIcon, QPixmap, QPainter, QBrush, QRadialGradient, QPalette, QPen, QConicalGradient
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QPushButton,
    QStackedWidget, QWidget, QSizePolicy, QToolButton, QLineEdit, QScrollArea,
    QMenu, QSplashScreen, QSystemTrayIcon, QMessageBox, QDialog,
)

# Local dashboard imports
from .ds import (
    C, F, Spacing, Radius, SidebarSize, Animation, ICONS,
    icon, icon_pixmap, hex_to_rgb, rgba_str, get_contrast_color, ensure_visible_accent,
    dashboard_stylesheet, make_glow, clear_layout,
    HLine, VLine, Card, StatusChip, SectionHeader, LoadingState, EmptyState, ErrorState,
    FadeInPageMixin,
)
from .service_adapters import (
    get_identity, get_assistant_state, load_user_preferences,
)
from .workers import DashboardPoller
from .ambient import AmbientVisualEngine, AmbientConfig

# Pages
from .pages.home_page import HomePage
from .pages.assistant_page import AssistantPage
from .pages.communications_page import CommunicationsPage
from .pages.workspace_page import WorkspacePage
from .pages.schedule_page import SchedulePage
from .pages.automation_page import AutomationPage
from .pages.connected_world_page import ConnectedWorldPage
from .pages.intelligence_page import IntelligencePage
from .pages.settings_page import SettingsPage


_NAV_ITEMS: list[tuple[str, str, str, type]] = [
    # (page_id, display_name, icon_name, page_class)
    ("home",             "Dashboard",       ICONS.HOME,             HomePage),
    ("assistant",        "Assistant",       ICONS.ASSISTANT,        AssistantPage),
    ("communications",   "Communications",  ICONS.COMMUNICATIONS,   CommunicationsPage),
    ("workspace",        "Workspace",       ICONS.WORKSPACE,        WorkspacePage),
    ("schedule",         "Schedule",        ICONS.SCHEDULE,         SchedulePage),
    ("automation",       "Automation",      ICONS.AUTOMATION,       AutomationPage),
    ("connected_world",  "Connected World", ICONS.CONNECTED_WORLD,  ConnectedWorldPage),
    ("intelligence",     "Intelligence",    ICONS.INTELLIGENCE,     IntelligencePage),
    ("settings",         "Settings",        ICONS.SETTINGS,         SettingsPage),
]


class AssistantOrb(QWidget):
    """Minimal animated orb in the topbar / sidebar that reflects current state.

    Supports all 7 states: IDLE, LISTENING, THINKING, SPEAKING,
    EXECUTING, ERROR, OFFLINE. Driven by Settings theme colour with
    error (red) and offline (grey) states.
    """

    def __init__(self, size: int = 14, parent=None):
        super().__init__(parent)
        self._size = size
        self._state = "idle"
        self._pulse = 0.0
        self._last_err_flash = 0.0
        self.setFixedSize(size, size)

    def set_state(self, state: str):
        s = (state or "idle").lower()
        if s == "error" and self._state != "error":
            self._last_err_flash = self._pulse
        self._state = s
        self.update()

    def sync_tick(self, master_time: float):
        """Driven exclusively by the master animation clock — no per-widget timer."""
        self._pulse = (master_time * 2.8) % (2 * 3.14159)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        is_error = self._state in ("error", "failed")
        is_offline = self._state in ("offline", "paused", "muted", "disabled")
        if is_error:
            r, g, b = (255, 71, 87)
        elif is_offline:
            r, g, b = (110, 125, 135)
        else:
            r, g, b = hex_to_rgb(C.ACC)
        w = float(self.width())
        h = float(self.height())
        cx, cy = w / 2.0, h / 2.0
        active = self._state in ("listening", "thinking", "speaking", "executing",
                                  "working", "processing")
        is_error = self._state in ("error", "failed")
        is_offline = self._state in ("offline", "paused", "muted", "disabled")

        # Outer ambient halo — stronger for active, dim for idle, off for offline
        if not is_offline:
            halo_alpha = 0
            if active:
                halo_alpha = 0.30 + 0.35 * (0.5 + 0.5 * math_sin(self._pulse * 2.2))
            elif is_error:
                err_beat = 0.5 + 0.5 * math_sin(self._pulse * 4.0)
                halo_alpha = 0.25 + 0.35 * err_beat
            else:
                halo_alpha = 0.10 + 0.08 * (0.5 + 0.5 * math_sin(self._pulse * 0.8))
            halo_r = min(cx, cy) * 0.95
            gr = QRadialGradient(cx, cy, halo_r, cx, cy, halo_r * 0.25)
            gr.setColorAt(0.0, QColor(r, g, b, int(200 * halo_alpha)))
            gr.setColorAt(0.55, QColor(r, g, b, int(60 * halo_alpha)))
            gr.setColorAt(1.0, QColor(r, g, b, 0))
            p.setBrush(QBrush(gr))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), halo_r, halo_r)

        # Subtle ring for thinking/executing: rotating arc
        if self._state in ("thinking", "executing", "working", "processing"):
            p.save()
            p.translate(cx, cy)
            speed = 2.0 if self._state == "thinking" else 4.5
            p.rotate(math.degrees(self._pulse * speed))
            rr = min(cx, cy) * 0.78
            arc_g = QConicalGradient(0.0, 0.0, 0.0)
            arc_g.setColorAt(0.0, QColor(r, g, b, 250))
            arc_g.setColorAt(0.35, QColor(r, g, b, 40))
            arc_g.setColorAt(0.75, QColor(r, g, b, 0))
            arc_g.setColorAt(1.0, QColor(r, g, b, 250))
            pen = QPen(QBrush(arc_g), max(1.4, w * 0.07))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(-rr, -rr, rr * 2, rr * 2), int(30 * 16), int(300 * 16))
            p.restore()

        # Inner core orb
        cx2, cy2 = cx - w * 0.06, cy - w * 0.06
        inner = min(cx, cy) * 0.60
        gr = QRadialGradient(cx2, cy2, inner * 1.3, cx, cy, inner * 0.9)
        if is_offline:
            gr.setColorAt(0.0, QColor(110, 140, 155, 255))
            gr.setColorAt(0.6, QColor(64, 92, 106, 255))
            gr.setColorAt(1.0, QColor(42, 64, 76, 255))
        else:
            gr.setColorAt(0.0, QColor(min(255, r + 50), min(255, g + 50), min(255, b + 50), 255))
            gr.setColorAt(0.5, QColor(r, g, b, 240))
            gr.setColorAt(1.0, QColor(max(0, r - 70), max(0, g - 70), max(0, b - 70), 240))
        p.setBrush(QBrush(gr))
        border_a = 180 if not is_offline else 110
        p.setPen(QColor(r, g, b, border_a))
        p.drawEllipse(QPointF(cx, cy), inner, inner)

        # Specular highlight
        if not is_offline:
            hl = QRadialGradient(cx - inner * 0.45, cy - inner * 0.55, inner * 0.55)
            hl.setColorAt(0.0, QColor(255, 255, 255, 90))
            hl.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(hl))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx - inner * 0.35, cy - inner * 0.45),
                          inner * 0.36, inner * 0.26)

        # Error state: tiny cross glyph
        if is_error:
            p.setPen(QColor(255, 255, 255, 220))
            stroke = max(1.2, w * 0.06)
            pen = QPen(QColor(255, 255, 255, 230), stroke)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            sz = inner * 0.42
            p.drawLine(QPointF(cx - sz, cy - sz), QPointF(cx + sz, cy + sz))
            p.drawLine(QPointF(cx + sz, cy - sz), QPointF(cx - sz, cy + sz))
        elif is_offline:
            # Offline: small dash / empty ring indicator
            p.setPen(QColor(200, 215, 222, 140))
            stroke = max(1.0, w * 0.05)
            pen = QPen(QColor(200, 215, 222, 150), stroke)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            sz = inner * 0.45
            p.drawLine(QPointF(cx - sz, cy), QPointF(cx + sz, cy))

        p.end()


def math_sin(x: float) -> float:
    import math
    return math.sin(x)


def QConicalGradient_fallback(x, y, angle):
    from PyQt6.QtGui import QConicalGradient
    return QConicalGradient(x, y, angle)


class Sidebar(QFrame):
    nav_changed = pyqtSignal(str)
    collapse_toggled = pyqtSignal(bool)

    def get_sidebar_width(self) -> int:
        return self.width()

    def set_sidebar_width(self, w: int):
        self.setFixedWidth(w)

    sidebarWidth = pyqtProperty(int, get_sidebar_width, set_sidebar_width)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "SidebarPanel")
        self._buttons: Dict[str, QPushButton] = {}
        self._current: Optional[str] = None
        self._collapsed = False
        self._username = "User"
        self._assistant_name = "Assistant"
        self._current_state = "idle"

        # Check existing user preference for sidebar collapse
        try:
            prefs = load_user_preferences() or {}
            if bool(prefs.get("sidebar_collapsed")):
                self._collapsed = True
        except Exception:
            pass

        self._build_ui()
        if self._collapsed:
            self.set_collapsed(True, animate=False)
        else:
            self.setFixedWidth(SidebarSize.WIDTH_EXPANDED)

    # --- UI build ------------------------------------------------------------
    def _build_ui(self):
        self._root_layout = QVBoxLayout(self)
        bp = SidebarSize.BRAND_PAD
        self._root_layout.setContentsMargins(bp - 2, bp, bp - 2, bp)
        self._root_layout.setSpacing(Spacing.XS)

        # Brand / App header
        self._brand_row = QHBoxLayout()
        self._brand_row.setSpacing(Spacing.SM)
        self._brand_row.setContentsMargins(2, 0, 0, 0)
        self._logo_orb = AssistantOrb(26)
        self._brand_row.addWidget(self._logo_orb, 0, Qt.AlignmentFlag.AlignVCenter)

        self._brand_text_wrap = QWidget()
        brand_col = QVBoxLayout(self._brand_text_wrap)
        brand_col.setSpacing(1)
        brand_col.setContentsMargins(0, 0, 0, 0)
        self._app_name = QLabel("Smart Assistant")
        self._app_name.setStyleSheet(
            f"font-weight: 800; font-size: 13px; letter-spacing: 0.2px; color: {C.TEXT};"
        )
        self._app_sub = QLabel("Intelligent Assistant")
        self._app_sub.setProperty("class", "Caption")
        self._app_sub.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px;")
        brand_col.addWidget(self._app_name)
        brand_col.addWidget(self._app_sub)
        self._brand_row.addWidget(self._brand_text_wrap, 1)

        # Collapse / Expand toggle button
        self._toggle_btn = QPushButton()
        self._toggle_btn.setObjectName("IconBtn")
        self._toggle_btn.setFixedSize(30, 30)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setIcon(icon(ICONS.CHEVRON_LEFT, C.TEXT_MED, 13))
        self._toggle_btn.setToolTip("Collapse sidebar")
        self._toggle_btn.clicked.connect(lambda: self.toggle_collapse(animate=True))
        self._brand_row.addWidget(self._toggle_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._root_layout.addLayout(self._brand_row)

        self._sep1 = HLine(C.DIVIDER, 1)
        self._root_layout.addSpacing(Spacing.XS)
        self._root_layout.addWidget(self._sep1)
        self._root_layout.addSpacing(Spacing.XS)

        # Identity card
        self._identity_card = QFrame()
        self._identity_card.setProperty("class", "CardInner")
        self._id_layout = QHBoxLayout(self._identity_card)
        self._id_layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        self._id_layout.setSpacing(Spacing.MD)
        self._avatar = QLabel()
        self._avatar.setFixedSize(38, 38)
        self._avatar.setStyleSheet(
            f"border-radius: 19px; background: {rgba_str(C.ACC, 0.14)}; "
            f"color: {C.ACC}; font-weight: 700; font-size: 14px;"
            f"border: 1px solid {rgba_str(C.ACC, 0.22)};"
        )
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setText("U")
        self._id_layout.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignCenter)

        self._id_text_wrap = QWidget()
        id_col = QVBoxLayout(self._id_text_wrap)
        id_col.setSpacing(1)
        id_col.setContentsMargins(0, 0, 0, 0)
        self._user_lbl = QLabel("User")
        self._user_lbl.setStyleSheet(f"font-weight: 600; font-size: 13px; color: {C.TEXT};")
        self._asst_lbl = QLabel("Assistant")
        self._asst_lbl.setProperty("class", "Caption")
        self._asst_lbl.setStyleSheet(f"font-size: 11px; color: {C.TEXT_DIM};")
        id_col.addWidget(self._user_lbl)
        id_col.addWidget(self._asst_lbl)
        self._id_layout.addWidget(self._id_text_wrap, 1)

        self._root_layout.addWidget(self._identity_card)
        self._root_layout.addSpacing(Spacing.SM)

        self._nav_header = QLabel("NAVIGATION")
        self._nav_header.setProperty("class", "Caption")
        self._nav_header.setStyleSheet(
            f"letter-spacing: 1.6px; font-size: 10px; padding: 0 {Spacing.MD}px; color: {C.TEXT_DIM};"
        )
        self._root_layout.addWidget(self._nav_header)
        self._root_layout.addSpacing(2)

        # Scrollable nav list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setContentsMargins(0, 0, 0, 0)
        scroll_contents = QWidget()
        scroll_contents.setStyleSheet("background: transparent;")
        self._nav_layout = QVBoxLayout(scroll_contents)
        self._nav_layout.setContentsMargins(0, 0, 0, 0)
        self._nav_layout.setSpacing(2)

        # Section accent colors for navigation
        self._nav_accents = {
            "home": C.SEC_DASHBOARD,
            "assistant": C.SEC_ASSISTANT,
            "communications": C.SEC_COMMUNICATIONS,
            "workspace": C.SEC_WORKSPACE,
            "schedule": C.SEC_SCHEDULE,
            "automation": C.SEC_AUTOMATION,
            "connected_world": C.SEC_CONNECTED,
            "intelligence": C.SEC_INTELLIGENCE,
            "settings": C.SEC_SETTINGS,
        }

        for pid, label, icon_name, _cls in _NAV_ITEMS:
            btn = QPushButton()
            accent = self._nav_accents.get(pid, C.SEC_SETTINGS)
            btn.setIcon(icon(icon_name, C.TEXT_MED, 18))
            btn.setIconSize(QSize(18, 18))
            btn.setText("   " + label)
            btn.setProperty("class", "NavButton")
            btn.setProperty("active", False)
            btn.setProperty("accent", accent)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(38)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _=False, p=pid: self.nav_changed.emit(p))
            self._buttons[pid] = btn
            self._nav_layout.addWidget(btn)

        self._nav_layout.addStretch(1)
        scroll.setWidget(scroll_contents)
        self._root_layout.addWidget(scroll, 1)

        # Dedicated unobstructed dock slot for 3D ambient core / FloatingLauncher
        self._dock_container = QWidget()
        self._dock_container.setFixedHeight(54)
        self._dock_container.setStyleSheet("background: transparent;")
        self._root_layout.addWidget(self._dock_container)

        self._sep2 = HLine(C.DIVIDER, 1)
        self._root_layout.addWidget(self._sep2)
        self._root_layout.addSpacing(Spacing.XS)

        # Assistant state at bottom
        self._state_row = QHBoxLayout()
        self._state_row.setSpacing(Spacing.SM)
        self._state_row.setContentsMargins(4, 0, 4, 0)
        self._state_orb = AssistantOrb(14)
        self._state_row.addWidget(self._state_orb, 0, Qt.AlignmentFlag.AlignVCenter)
        self._state_chip = StatusChip("IDLE", "idle")
        self._state_row.addWidget(self._state_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        self._state_spacer = QWidget()
        self._state_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._state_row.addWidget(self._state_spacer)
        self._root_layout.addLayout(self._state_row)

    # --- Collapse / Expand Interaction ---------------------------------------
    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def is_collapsed(self) -> bool:
        return self._collapsed

    def toggle_collapse(self, animate: bool = True):
        self.set_collapsed(not self._collapsed, animate=animate)

    def set_collapsed(self, collapsed: bool, animate: bool = True):
        self._collapsed = collapsed
        target_w = SidebarSize.WIDTH_COLLAPSED if collapsed else SidebarSize.WIDTH_EXPANDED
        bp = SidebarSize.BRAND_PAD
        accent = getattr(self, '_accent', C.ACC)

        if collapsed:
            self._root_layout.setContentsMargins(6, 12, 6, 12)
            self._brand_row.setContentsMargins(0, 0, 0, 0)
            self._brand_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._logo_orb.setVisible(False)
            self._brand_text_wrap.setVisible(False)
            self._toggle_btn.setVisible(True)
            self._toggle_btn.setFixedSize(46, 36)
            self._toggle_btn.setIcon(icon(ICONS.CHEVRON_RIGHT, accent, 14))
            self._toggle_btn.setToolTip("Expand sidebar")

            self._id_text_wrap.setVisible(False)
            self._id_layout.setContentsMargins(0, 0, 0, 0)
            self._id_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._identity_card.setStyleSheet("background: transparent; border: none;")
            self._avatar.setFixedSize(38, 38)
            self._avatar.setToolTip(f"User: {self._username}")

            self._nav_header.setVisible(False)
            self._state_chip.setVisible(False)
            self._state_spacer.setVisible(False)
            self._state_row.setContentsMargins(0, 0, 0, 0)
            self._state_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._state_orb.setToolTip(f"Assistant: {self._current_state.upper()}")
        else:
            self._root_layout.setContentsMargins(bp - 2, bp, bp - 2, bp)
            self._brand_row.setContentsMargins(2, 0, 0, 0)
            self._brand_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._logo_orb.setVisible(True)
            self._brand_text_wrap.setVisible(True)
            self._toggle_btn.setVisible(True)
            self._toggle_btn.setFixedSize(30, 30)
            self._toggle_btn.setIcon(icon(ICONS.CHEVRON_LEFT, C.TEXT_MED, 13))
            self._toggle_btn.setToolTip("Collapse sidebar")

            self._id_text_wrap.setVisible(True)
            self._id_layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
            self._id_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._identity_card.setStyleSheet("")
            self._avatar.setFixedSize(38, 38)
            self._avatar.setToolTip("")

            self._nav_header.setVisible(True)
            self._state_chip.setVisible(True)
            self._state_spacer.setVisible(True)
            self._state_row.setContentsMargins(4, 0, 4, 0)
            self._state_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._state_orb.setToolTip("")

        # Update button texts, tooltips, and padding
        for pid, label, icon_name, _cls in _NAV_ITEMS:
            btn = self._buttons.get(pid)
            if btn:
                btn.setProperty("collapsed", collapsed)
                if collapsed:
                    btn.setText("")
                    btn.setToolTip(label)
                    btn.setFixedSize(48, 38)
                    btn.setIconSize(QSize(20, 20))
                    self._nav_layout.setAlignment(btn, Qt.AlignmentFlag.AlignHCenter)
                else:
                    btn.setText("   " + label)
                    btn.setToolTip("")
                    btn.setMinimumHeight(38)
                    btn.setMaximumHeight(38)
                    btn.setMinimumWidth(0)
                    btn.setMaximumWidth(16777215)
                    btn.setIconSize(QSize(18, 18))
                    self._nav_layout.setAlignment(btn, Qt.AlignmentFlag.AlignLeft)
                btn.style().unpolish(btn)
                btn.style().polish(btn)

        if self._current:
            self.set_current(self._current)

        # Persist preference asynchronously
        try:
            from .service_adapters import save_user_preference
            save_user_preference("sidebar_collapsed", self._collapsed)
        except Exception:
            pass

        self.collapse_toggled.emit(self._collapsed)

        # Smooth animation or immediate jump
        if animate:
            if hasattr(self, "_anim") and self._anim.state() == QPropertyAnimation.State.Running:
                self._anim.stop()
            self._anim = QPropertyAnimation(self, b"sidebarWidth")
            self._anim.setDuration(220)
            self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self._anim.setStartValue(self.width())
            self._anim.setEndValue(target_w)
            self._anim.start()
        else:
            self.setFixedWidth(target_w)

    # --- Public API ----------------------------------------------------------
    def set_current(self, page_id: str):
        self._current = page_id
        accent = getattr(self, '_accent', C.ACC)
        for pid, btn in self._buttons.items():
            active = pid == page_id
            btn.setProperty("active", active)
            item_accent = self._nav_accents.get(pid, accent)
            icon_name = _NAV_ITEMS[[p[0] for p in _NAV_ITEMS].index(pid)][2]
            icon_sz = 20 if self._collapsed else 18
            if active:
                btn.setIcon(icon(icon_name, item_accent, icon_sz))
                pad_css = "padding: 0px; text-align: center;" if self._collapsed else "padding: 8px 12px; text-align: left;"
                btn.setStyleSheet(f"""
                    QPushButton.NavButton {{
                        background: {rgba_str(item_accent, 0.14)};
                        color: {item_accent};
                        border: 1px solid {rgba_str(item_accent, 0.32)};
                        font-weight: 600;
                        border-radius: 8px;
                        {pad_css}
                    }}
                    QPushButton.NavButton:hover {{
                        background: {rgba_str(item_accent, 0.20)};
                        border: 1px solid {rgba_str(item_accent, 0.45)};
                        color: {item_accent};
                    }}
                """)
            else:
                btn.setIcon(icon(icon_name, C.TEXT_MED, icon_sz))
                pad_css = "padding: 0px; text-align: center;" if self._collapsed else "padding: 8px 12px; text-align: left;"
                btn.setStyleSheet(f"""
                    QPushButton.NavButton {{
                        background: transparent;
                        color: {C.TEXT_MED};
                        border: 1px solid transparent;
                        border-radius: 8px;
                        {pad_css}
                    }}
                    QPushButton.NavButton:hover {{
                        background: {C.SIDEBAR_HOVER};
                        color: {C.TEXT};
                        border: 1px solid {C.BORDER};
                    }}
                """)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_accent(self, accent: str):
        self._accent = accent
        for k in self._nav_accents:
            self._nav_accents[k] = accent
        self._avatar.setStyleSheet(
            f"border-radius: 19px; background: {rgba_str(accent, 0.14)}; "
            f"color: {accent}; font-weight: 700; font-size: 14px;"
            f"border: 1px solid {rgba_str(accent, 0.28)};"
        )
        if hasattr(self, '_toggle_btn') and self._collapsed:
            self._toggle_btn.setIcon(icon(ICONS.CHEVRON_RIGHT, accent, 14))
        if self._current:
            self.set_current(self._current)
        self.update()

    def update_identity(self, username: str, assistant_name: str):
        self._username = username or "User"
        self._assistant_name = assistant_name or "Assistant"
        self._user_lbl.setText(self._username)
        self._asst_lbl.setText(self._assistant_name)
        letter = self._username[0:1].upper()
        self._avatar.setText(letter)
        if self._collapsed:
            self._avatar.setToolTip(f"User: {self._username}")

    def update_state(self, state: str):
        s = (state or "idle").lower()
        self._current_state = s
        self._state_orb.set_state(s)
        self._state_chip.set_state(s)
        self._state_chip.setText(s.upper())
        self._logo_orb.set_state(s)
        if self._collapsed:
            self._state_orb.setToolTip(f"Assistant: {s.upper()}")

    def _sync_orbs(self, master_time: float):
        """Synchronize child orbs from the master animation clock."""
        if hasattr(self, '_logo_orb') and self._logo_orb:
            self._logo_orb.sync_tick(master_time)
        if hasattr(self, '_state_orb') and self._state_orb:
            self._state_orb.sync_tick(master_time)


class Topbar(QFrame):
    """Persistent top bar with title, search, actions, and user menu."""

    action_triggered = pyqtSignal(str)  # 'search', 'notifications', 'user', 'settings', 'new_chat'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "TopbarPanel")
        self.setFixedHeight(SidebarSize.TOPBAR_HEIGHT)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(Spacing.LG2, 0, Spacing.LG2, 0)
        root.setSpacing(Spacing.MD + 2)

        # Left section: page crumb with subtle accent bar
        left = QHBoxLayout()
        left.setSpacing(Spacing.MD)
        # Subtle accent marker
        self._acc_bar = QLabel()
        self._acc_bar.setFixedSize(3, 18)
        acc_r, acc_g, acc_b = hex_to_rgb(C.SEC_DASHBOARD)
        self._acc_bar.setStyleSheet(
            f"background: rgba({acc_r},{acc_g},{acc_b},0.85); border-radius: 2px;"
        )
        left.addWidget(self._acc_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        self._crumb_lbl = QLabel("Dashboard")
        self._crumb_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {C.TEXT}; letter-spacing: -0.1px;"
        )
        left.addWidget(self._crumb_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(left, 0)

        # Center: search (flexible)
        root.addSpacing(Spacing.LG)
        search_wrap = QHBoxLayout()
        search_wrap.setSpacing(0)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search conversations, files, calendar, commands…  (Ctrl+K)")
        self._search.setMinimumWidth(220)
        self._search.setMaximumWidth(520)
        self._search.setFixedHeight(36)
        self._search.addAction(icon(ICONS.SEARCH, C.TEXT_DIM, 14),
                                QLineEdit.ActionPosition.LeadingPosition)
        self._search.returnPressed.connect(lambda: self.action_triggered.emit("search"))
        search_wrap.addWidget(self._search)
        root.addLayout(search_wrap, 1)

        # Right section: actions
        root.addStretch(1)
        actions = QHBoxLayout()
        actions.setSpacing(Spacing.SM + 1)

        self._new_btn = QPushButton("  New Conversation")
        self._new_btn.setObjectName("GhostBtn")
        self._new_btn.setIcon(icon(ICONS.PLUS, C.TEXT, 14))
        self._new_btn.setFixedHeight(36)
        self._new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_btn.clicked.connect(lambda: self.action_triggered.emit("new_chat"))
        actions.addWidget(self._new_btn)

        actions.addSpacing(Spacing.SM)

        self._notif_btn = QPushButton()
        self._notif_btn.setObjectName("IconBtn")
        self._notif_btn.setIcon(icon(ICONS.BELL, C.TEXT, 16))
        self._notif_btn.setIconSize(QSize(18, 18))
        self._notif_btn.setToolTip("Notifications")
        self._notif_btn.setFixedSize(38, 36)
        self._notif_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._notif_btn.clicked.connect(lambda: self.action_triggered.emit("notifications"))
        actions.addWidget(self._notif_btn)

        self._user_btn = QPushButton()
        self._user_btn.setObjectName("IconBtn")
        self._user_btn.setIcon(icon(ICONS.USER, C.TEXT, 16))
        self._user_btn.setIconSize(QSize(18, 18))
        self._user_btn.setToolTip("Account")
        self._user_btn.setFixedSize(38, 36)
        self._user_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._user_btn.clicked.connect(lambda: self.action_triggered.emit("user"))
        actions.addWidget(self._user_btn)

        root.addLayout(actions, 0)

    def set_crumb(self, text: str, accent: Optional[str] = None):
        self._crumb_lbl.setText(text)
        if accent and hasattr(self, "_acc_bar"):
            acc_r, acc_g, acc_b = hex_to_rgb(accent)
            self._acc_bar.setStyleSheet(
                f"background: rgba({acc_r},{acc_g},{acc_b},0.85); border-radius: 2px;"
            )


class StatusStrip(QFrame):
    """Bottom status bar — assistant state, uptime, current operation, diagnostics access."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "StatusStrip")
        self.setFixedHeight(SidebarSize.STATUS_HEIGHT)
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(Spacing.LG2, 0, Spacing.LG2, 0)
        root.setSpacing(Spacing.MD + 2)

        # Assistant state group
        self._state_orb = AssistantOrb(11)
        root.addWidget(self._state_orb, 0, Qt.AlignmentFlag.AlignVCenter)
        self._state_txt = QLabel("IDLE")
        self._state_txt.setStyleSheet(
            f"font-size: 11px; font-weight: 600; letter-spacing: 0.8px; color: {C.TEXT_MED};"
        )
        root.addWidget(self._state_txt, 0, Qt.AlignmentFlag.AlignVCenter)

        # Divider
        v = QLabel("·")
        v.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 14px; padding: 0 2px;")
        root.addWidget(v, 0, Qt.AlignmentFlag.AlignVCenter)

        # Uptime
        self._uptime_lbl = QLabel("Uptime 00:00:00")
        self._uptime_lbl.setStyleSheet(f"font-size: 11px; color: {C.TEXT_DIM};")
        root.addWidget(self._uptime_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        root.addStretch(1)

        # Current operation
        self._op_lbl = QLabel("")
        self._op_lbl.setStyleSheet(
            f"font-size: 11px; font-weight: 500; color: {C.ACC}; letter-spacing: 0.2px;"
        )
        root.addWidget(self._op_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        root.addSpacing(Spacing.MD)

    def update_state(self, state_data: dict):
        s = (state_data.get("state") or "idle").lower()
        self._state_orb.set_state(s)
        display = s.upper()
        self._state_txt.setText(display)
        if s in ("error", "failed"):
            color = C.STATUS_ERROR
        elif s in ("offline", "paused", "muted", "disabled"):
            color = C.STATUS_OFFLINE
        else:
            color = C.ACC
        self._state_txt.setStyleSheet(
            f"font-size: 11px; font-weight: 600; letter-spacing: 0.8px; color: {color};"
        )

        op = state_data.get("active_operation") or state_data.get("task") or ""
        if op:
            prog = state_data.get("progress", 0)
            self._op_lbl.setText(f"{op}  {prog}%" if prog else str(op))
        else:
            self._op_lbl.setText("")

        up = int(state_data.get("uptime_seconds") or 0)
        h, rem = divmod(up, 3600)
        m, sec = divmod(rem, 60)
        self._uptime_lbl.setText(f"Uptime {h:02d}:{m:02d}:{sec:02d}")

    def _sync_orbs(self, master_time: float):
        """Synchronize status orb from the master animation clock."""
        if hasattr(self, '_state_orb') and self._state_orb:
            self._state_orb.sync_tick(master_time)


# =============================================================================
# Main Window
# =============================================================================

class DashboardMainWindow(QWidget):
    """Primary dashboard top-level window. Uses QWidget (not QMainWindow)
    for clean composability into any existing QApplication."""

    identity_changed = pyqtSignal(dict)

    # Compatibility signals for pyqt_app.py
    command_submitted = pyqtSignal(str)
    minimized = pyqtSignal()
    restored = pyqtSignal()
    logout_requested = pyqtSignal()
    assistant_name_changed = pyqtSignal(str)
    accent_changed = pyqtSignal(str)
    dock_geometry_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardMainWindow")
        self.setWindowFlags(Qt.WindowType.Window)
        self.setWindowTitle("Smart Assistant — Control Center")
        self._assistant_name = "Assistant"
        self.resize(1440, 900)
        self.setMinimumSize(1024, 640)
        self.setMouseTracking(True)
        self._current_page_id: Optional[str] = None
        self._accent: str = C.ACC
        self._state_listener_registered = False

        # Shared 3D Ambient Visual Engine
        self.ambient_engine = AmbientVisualEngine(parent=self)
        self.ambient_engine.set_accent(self._accent)
        try:
            prefs = load_user_preferences() or {}
            cfg = AmbientConfig.from_dict(prefs)
            self.ambient_engine.apply_config(cfg)
            if bool(prefs.get("reduced_motion")):
                self.ambient_engine.set_reduced_motion(True)
        except Exception:
            pass

        # Wire Master Animation Clock to synchronized dashboard components
        self.ambient_engine.clock_tick.connect(self._on_master_clock_tick)

        self._build_ui()
        self._setup_polling()
        self._apply_identity()
        # Navigate to default page
        QTimer.singleShot(0, lambda: self._on_nav("home"))

    def _on_master_clock_tick(self, dt: float, master_time: float):
        """Dispatches single clock tick to sidebar, status bar, and active page."""
        if hasattr(self, 'sidebar') and hasattr(self.sidebar, '_sync_orbs'):
            self.sidebar._sync_orbs(master_time)
        if hasattr(self, 'status') and hasattr(self.status, '_sync_orbs'):
            self.status._sync_orbs(master_time)
        curr_page = self._page_map.get(self._current_page_id) if hasattr(self, '_page_map') else None
        if curr_page and hasattr(curr_page, "sync_tick"):
            try:
                curr_page.sync_tick(master_time)
            except Exception:
                pass
        try:
            from .ds import dispatch_master_clock_tick
            dispatch_master_clock_tick(dt, master_time)
        except Exception:
            pass

    def changeEvent(self, event):
        """Handle window state changes (minimize/restore) — pause master clock on minimize."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                if hasattr(self, 'ambient_engine') and self.ambient_engine:
                    self.ambient_engine.pause()
                self.minimized.emit()
            elif not (self.windowState() & Qt.WindowState.WindowMinimized):
                if hasattr(self, 'ambient_engine') and self.ambient_engine:
                    self.ambient_engine.resume()
                self.restored.emit()

    def event(self, ev):
        """Throttle animation frame rate when window is unfocused."""
        if ev.type() in (QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate, QEvent.Type.ActivationChange):
            is_active = self.isActiveWindow()
            if hasattr(self, 'ambient_engine') and self.ambient_engine:
                self.ambient_engine.set_focus_active(is_active)
        return super().event(ev)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'ambient_engine') and self.ambient_engine:
            self.ambient_engine.setGeometry(0, 0, self.width(), self.height())
            self.ambient_engine.lower()
            self._update_dock_target()

    def _update_dock_target(self):
        """Map the geometry of the sidebar dock container to dynamic screen ratios."""
        try:
            if hasattr(self, 'sidebar') and hasattr(self.sidebar, '_dock_container'):
                dc = self.sidebar._dock_container
                pt = dc.mapTo(self, QPoint(int(dc.width() * 0.5), int(dc.height() * 0.5)))
                w = max(1.0, float(self.width()))
                h = max(1.0, float(self.height()))
                rx = pt.x() / w
                ry = pt.y() / h
                if hasattr(self, 'ambient_engine') and self.ambient_engine:
                    self.ambient_engine.set_dock_ratios(rx, ry)
        except Exception:
            pass

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if hasattr(self, 'ambient_engine') and self.ambient_engine:
            pos = event.position() if hasattr(event, 'position') else event.pos()
            self.ambient_engine.set_mouse_pos(int(pos.x()), int(pos.y()))

    def isMinimized(self):
        """Check if window is minimized (compatibility with pyqt_app.py)"""
        return bool(self.windowState() & Qt.WindowState.WindowMinimized)

    # ---------------------------------------------------------------- build
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar()
        self.sidebar.nav_changed.connect(self._on_nav)
        body.addWidget(self.sidebar)

        # Center column
        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)

        self.topbar = Topbar()
        self.topbar.action_triggered.connect(self._on_topbar_action)
        center.addWidget(self.topbar)

        self.pages = QStackedWidget()
        self._page_map: Dict[str, QWidget] = {}
        for pid, _label, _ic, cls in _NAV_ITEMS:
            try:
                page = cls()
            except Exception as e:
                print(f"[DASHBOARD] Failed to construct page {pid}: {e}")
                # Fallback placeholder
                page = ErrorState(f"Failed to load {pid}", str(e),
                                  retry_fn=lambda p=pid, c=cls: self._rebuild_page(p, c))
            try:
                FadeInPageMixin.install_on(page, duration=Animation.SLOW)
            except Exception as fade_err:
                print(f"[DASHBOARD] Fade install failed on {pid}: {fade_err}")
            self.pages.addWidget(page)
            self._page_map[pid] = page

        # Wire settings page configuration signals to main window
        settings_page = self._page_map.get("settings")
        if settings_page:
            if hasattr(settings_page, "accent_changed"):
                settings_page.accent_changed.connect(self.set_accent)
            if hasattr(settings_page, "dashboard_color_changed"):
                settings_page.dashboard_color_changed.connect(self.set_accent)
            if hasattr(settings_page, "identity_changed"):
                settings_page.identity_changed.connect(self._on_settings_identity_changed)

        center.addWidget(self.pages, 1)

        self.status = StatusStrip()
        center.addWidget(self.status)

        center_w = QWidget()
        center_w.setLayout(center)
        body.addWidget(center_w, 1)

        body_w = QWidget()
        body_w.setLayout(body)
        root.addWidget(body_w, 1)

        # Ambient 3D background behind all UI content
        if hasattr(self, 'ambient_engine') and self.ambient_engine:
            self.ambient_engine.setGeometry(0, 0, self.width(), self.height())
            self.ambient_engine.lower()

        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(dashboard_stylesheet(self._accent))

    def _on_settings_identity_changed(self):
        try:
            ident = get_identity()
            new_name = ident.get("assistant_name")
            if new_name:
                self.set_assistant_name(new_name)
                self.assistant_name_changed.emit(new_name)
        except Exception as e:
            print(f"[DASHBOARD] _on_settings_identity_changed error: {e}")

    def set_accent(self, accent_hex: str):
        try:
            target_accent = ensure_visible_accent(accent_hex or C.ACC)
            curr = getattr(self, '_accent', None)
            if curr and str(curr).strip().lower() == str(target_accent).strip().lower():
                return  # Prevent redundant re-theming and infinite signal recursion
            if getattr(self, '_in_accent_update', False):
                return
            self._in_accent_update = True
            try:
                self._accent = target_accent
                C.ACCENT = self._accent
                C.ACCENT_CYAN = self._accent
                C.ACC = self._accent
                C.SEC_DASHBOARD = self._accent
                if hasattr(self, 'ambient_engine') and self.ambient_engine:
                    self.ambient_engine.set_accent(self._accent)
                if hasattr(self, 'sidebar'):
                    if hasattr(self.sidebar, 'set_accent'):
                        self.sidebar.set_accent(self._accent)
                    elif hasattr(self.sidebar, '_nav_accents'):
                        for k in self.sidebar._nav_accents:
                            self.sidebar._nav_accents[k] = self._accent
                app = QApplication.instance()
                if app:
                    app.setStyleSheet(dashboard_stylesheet(self._accent))
                self._apply_theme()
                if hasattr(self, 'sidebar') and hasattr(self.sidebar, '_current') and self.sidebar._current:
                    self.sidebar.set_current(self.sidebar._current)
                    accent = self.sidebar._nav_accents.get(self.sidebar._current, C.SEC_SETTINGS)
                    label = self.sidebar._current
                    for pid, lab, _ic, _cls in _NAV_ITEMS:
                        if pid == self.sidebar._current:
                            label = lab
                            break
                    self.topbar.set_crumb(label, accent)
                for page in self._page_map.values():
                    if hasattr(page, "on_accent_changed"):
                        try:
                            page.on_accent_changed(self._accent)
                        except Exception:
                            pass
                self.accent_changed.emit(self._accent)
            finally:
                self._in_accent_update = False
        except Exception as e:
            print(f"[DASHBOARD] set_accent error: {e}")

    # --------------------------------------------------------------- navigation
    def _on_nav(self, page_id: str):
        if page_id not in self._page_map:
            return
        self._current_page_id = page_id
        if hasattr(self, 'ambient_engine') and self.ambient_engine:
            self._update_dock_target()
            self.ambient_engine.set_page(page_id)
        self.sidebar.set_current(page_id)
        # Find nav label and accent
        label = page_id
        for pid, lab, _ic, _cls in _NAV_ITEMS:
            if pid == page_id:
                label = lab
                break
        accent = self.sidebar._nav_accents.get(page_id, C.SEC_SETTINGS)
        self.topbar.set_crumb(label, accent)
        page = self._page_map[page_id]
        self.pages.setCurrentWidget(page)
        if hasattr(page, "on_visible"):
            try:
                page.on_visible()
            except Exception as e:
                print(f"[DASHBOARD] on_visible error for {page_id}: {e}")

    def _rebuild_page(self, page_id: str, cls):
        try:
            new_page = cls()
            old_idx = self.pages.indexOf(self._page_map[page_id])
            old = self.pages.widget(old_idx)
            self.pages.removeWidget(old)
            self.pages.insertWidget(old_idx, new_page)
            self._page_map[page_id] = new_page
        except Exception as e:
            print(f"[DASHBOARD] Rebuild {page_id} failed: {e}")

    # -------------------------------------------------------------- topbar
    def _on_topbar_action(self, action: str):
        if action == "new_chat":
            self._on_nav("assistant")
            page = self._page_map.get("assistant")
            if hasattr(page, "new_conversation"):
                try: page.new_conversation()
                except Exception: pass
        elif action == "settings":
            self._on_nav("settings")
        elif action == "user":
            self._show_user_menu()
        elif action == "notifications":
            self._show_notifications_menu()
        elif action == "search":
            text = self.topbar._search.text().strip()
            if text:
                # Jump to assistant page with search context (best-effort)
                self._on_nav("assistant")
                page = self._page_map.get("assistant")
                if hasattr(page, "prefill_input"):
                    try: page.prefill_input(text)
                    except Exception: pass

    def _show_user_menu(self):
        menu = QMenu(self)
        ident = get_identity()
        a1 = menu.addAction(icon(ICONS.USER, C.TEXT, 14),
                            f"Signed in as {ident.get('username', 'User')}")
        a1.setEnabled(False)
        menu.addSeparator()
        a_settings = menu.addAction(icon(ICONS.SETTINGS, C.TEXT, 14), "Settings")
        a_settings.triggered.connect(lambda: self._on_nav("settings"))
        a_signout = menu.addAction(icon(ICONS.POWER, C.RED, 14), "Sign out")
        a_signout.triggered.connect(self._sign_out)
        menu.exec(self.topbar._user_btn.mapToGlobal(
            self.topbar._user_btn.rect().bottomLeft()
        ))

    def _show_notifications_menu(self):
        menu = QMenu(self)
        head = menu.addAction("Notifications")
        head.setEnabled(False)
        menu.addSeparator()
        try:
            reminders = []
            try:
                from .service_adapters import load_reminders
                reminders = load_reminders() or []
            except Exception:
                pass
            if reminders:
                for r in reminders[:5]:
                    due = r.get("due_at") or "No date"
                    menu.addAction(f"⏰  {r.get('task_text','')[:40]} — {str(due)[:16]}")
            else:
                menu.addAction("No pending notifications").setEnabled(False)
        except Exception:
            pass
        menu.addSeparator()
        menu.addAction("View all in Schedule").triggered.connect(lambda: self._on_nav("schedule"))
        menu.exec(self.topbar._notif_btn.mapToGlobal(
            self.topbar._notif_btn.rect().bottomLeft()
        ))

    def _sign_out(self):
        dlg = QMessageBox(self)
        dlg.setIcon(QMessageBox.Icon.Question)
        dlg.setWindowTitle("Sign out?")
        dlg.setText("This will close the dashboard. You can sign back in from the login window.")
        dlg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if dlg.exec() == QMessageBox.StandardButton.Yes:
            self.close()
            try: QApplication.instance().quit()
            except Exception: pass

    def show_status_message(self, msg: str, timeout_ms: int = 3500):
        """Display an inline status message in the bottom status strip without modal popups."""
        if hasattr(self, 'status') and hasattr(self.status, '_op_lbl'):
            self.status._op_lbl.setText(msg)
            QTimer.singleShot(timeout_ms, lambda: self.status._op_lbl.setText("") if getattr(self.status, '_op_lbl', None) and self.status._op_lbl.text() == msg else None)

    # --------------------------------------------------------------- state sync
    def _setup_polling(self):
        # Fallback poller; if we can register a core state listener we prefer that
        try:
            from core.assistant_core import assistant_core
            def _cb(state):
                # Called from arbitrary thread — bounce through QTimer
                QTimer.singleShot(0, self._refresh_state)
            assistant_core.register_state_listener(_cb)
            self._state_listener_registered = True

            def _on_ui_connected_world():
                QTimer.singleShot(0, lambda: self._on_nav("connected_world"))

            def _on_ui_open_live_control():
                def _do():
                    self._on_nav("connected_world")
                    cw_page = self._page_map.get("connected_world")
                    if cw_page and hasattr(cw_page, "open_live_control"):
                        cw_page.open_live_control()
                QTimer.singleShot(0, _do)

            def _on_ui_close_live_control():
                def _do():
                    cw_page = self._page_map.get("connected_world")
                    if cw_page and hasattr(cw_page, "close_live_control"):
                        cw_page.close_live_control()
                QTimer.singleShot(0, _do)

            assistant_core.register_ui_action_handler("open_connected_world", _on_ui_connected_world)
            assistant_core.register_ui_action_handler("open_live_control", _on_ui_open_live_control)
            assistant_core.register_ui_action_handler("close_live_control", _on_ui_close_live_control)
            self._ui_handlers_registered = {
                "open_connected_world": _on_ui_connected_world,
                "open_live_control": _on_ui_open_live_control,
                "close_live_control": _on_ui_close_live_control,
            }
        except Exception:
            pass
        self._state_poller = DashboardPoller(get_assistant_state, interval_ms=400, parent=self)
        self._state_poller.tick_sig.connect(self._on_state_tick)
        self._state_poller.start()

        # Identity refresh (every 3 s) for live assistant name change
        self._identity_timer = QTimer(self)
        self._identity_timer.timeout.connect(self._apply_identity)
        self._identity_timer.start(3000)

    def closeEvent(self, event):
        """Clean up threads and timers when window closes."""
        # Stop state poller
        if hasattr(self, '_state_poller') and self._state_poller:
            self._state_poller.stop()

        # Stop identity timer
        if hasattr(self, '_identity_timer') and self._identity_timer:
            self._identity_timer.stop()

        if hasattr(self, '_ui_handlers_registered'):
            try:
                from core.assistant_core import assistant_core
                for act, fn in self._ui_handlers_registered.items():
                    assistant_core.unregister_ui_action_handler(act, fn)
            except Exception:
                pass

        # Clean up workers in all pages
        for page in self._page_map.values():
            if hasattr(page, '_cleanup_workers'):
                try:
                    page._cleanup_workers()
                except Exception:
                    pass

        if hasattr(self, 'ambient_engine') and self.ambient_engine:
            try:
                self.ambient_engine.set_enabled(False)
            except Exception:
                pass

        event.accept()

    def _on_state_tick(self, data):
        try:
            self.status.update_state(data)
            state_str = str(data.get("state") or "idle").lower()
            self.sidebar.update_state(state_str)
            prog = float(data.get("progress") or 0.0)
            if hasattr(self, 'ambient_engine') and self.ambient_engine:
                self.ambient_engine.set_assistant_state(state_str)
                self.ambient_engine.set_progress(prog)
            # Broadcast to pages
            for page in self._page_map.values():
                if hasattr(page, "on_assistant_state"):
                    try: page.on_assistant_state(data)
                    except Exception: pass
        except Exception:
            pass

    def _refresh_state(self):
        try:
            data = get_assistant_state()
            self._on_state_tick(data)
        except Exception:
            pass

    # --------------------------------------------------------------- identity
    def _apply_identity(self):
        ident = get_identity()
        asst_name = ident.get("assistant_name") or "Assistant"
        self.sidebar.update_identity(ident.get("username"), asst_name)
        if hasattr(self, 'ambient_engine') and self.ambient_engine:
            self.ambient_engine.set_assistant_name(asst_name)
        # Broadcast identity to pages
        for page in self._page_map.values():
            if hasattr(page, "on_identity"):
                try: page.on_identity(ident)
                except Exception: pass
        # Apply saved accent
        try:
            uid = ident.get("user_id")
            if uid:
                prefs = load_user_preferences(uid) or {}
                acc = prefs.get("dashboard_color")
                if acc and str(acc).startswith("#") and acc != self._accent:
                    self.set_accent(acc)
        except Exception:
            pass

    # ================================================================
    # COMPATIBILITY METHODS FOR pyqt_app.py INTEGRATION
    # ================================================================

    def set_assistant_name(self, name: str):
        """Set assistant name (compatibility with pyqt_app.py)"""
        clean_name = str(name).strip() if name else "Assistant"
        if getattr(self, '_assistant_name', None) == clean_name:
            return
        ident = get_identity()
        if ident:
            ident["assistant_name"] = clean_name
        self.sidebar.update_identity(ident.get("username") if ident else None, clean_name)
        self.setWindowTitle(f"Smart Assistant — {clean_name}")
        self._assistant_name = clean_name

    def set_user_name(self, name: str):
        """Set user name (compatibility with pyqt_app.py)"""
        ident = get_identity()
        if ident:
            ident["username"] = name
        self.sidebar.update_identity(name, ident.get("assistant_name"))

    def set_user_id(self, user_id: int):
        """Set user ID (compatibility with pyqt_app.py)"""
        # Identity is loaded from backend, just trigger refresh
        self._apply_identity()

    def set_state(self, state: str):
        """Set assistant state (compatibility with pyqt_app.py)"""
        # State is polled automatically, but we can force update
        self._refresh_state()

    def set_audio_level(self, level: float):
        """Forward real audio amplitude into the spatial core and active page."""
        lvl = max(0.0, min(1.0, float(level or 0.0)))
        if hasattr(self, 'ambient_engine') and self.ambient_engine:
            self.ambient_engine.set_audio_level(lvl)
        curr_page = self._page_map.get(self._current_page_id) if hasattr(self, '_page_map') else None
        if curr_page and hasattr(curr_page, "set_audio_level"):
            try:
                curr_page.set_audio_level(lvl)
            except Exception:
                pass

    def show_animated(self):
        """Show window with animation (compatibility with pyqt_app.py)"""
        self.show()
        self.raise_()
        self.activateWindow()

    def show_on_chat(self):
        """Show and navigate to assistant page (compatibility with pyqt_app.py)"""
        self._on_nav("assistant")
        self.show()
        self.raise_()
        self.activateWindow()

    def select_tab(self, idx: int):
        """Select tab by index (compatibility with pyqt_app.py)"""
        # Map old tab indices to new page IDs
        tab_map = {
            0: "home",           # Dashboard
            1: "assistant",      # Chat
            2: "workspace",      # Tasks (closest match)
            3: "intelligence",   # Memory
            4: "automation",     # Telemetry (closest match)
            5: "settings",       # Settings
        }
        page_id = tab_map.get(idx, "home")
        self._on_nav(page_id)

    def refresh_dashboard(self):
        """Refresh dashboard data (compatibility with pyqt_app.py)"""
        # Trigger refresh on current page
        current_page = self._page_map.get(self._current_page_id)
        if current_page and hasattr(current_page, "on_visible"):
            try:
                current_page.on_visible()
            except Exception:
                pass

    def add_user_message(self, text: str):
        """Add user message to chat (compatibility with pyqt_app.py)"""
        page = self._page_map.get("assistant")
        if page and hasattr(page, "add_user_message"):
            try:
                page.add_user_message(text)
            except Exception:
                pass

    def add_assistant_message(self, text: str):
        """Add assistant message to chat (compatibility with pyqt_app.py)"""
        page = self._page_map.get("assistant")
        if page and hasattr(page, "add_assistant_message"):
            try:
                page.add_assistant_message(text)
            except Exception:
                pass

    def show_thinking(self):
        """Show thinking indicator (compatibility with pyqt_app.py)"""
        page = self._page_map.get("assistant")
        if page and hasattr(page, "show_thinking"):
            try:
                page.show_thinking()
            except Exception:
                pass

    def set_input_enabled(self, enabled: bool):
        """Enable/disable input (compatibility with pyqt_app.py)"""
        page = self._page_map.get("assistant")
        if page and hasattr(page, "set_input_enabled"):
            try:
                page.set_input_enabled(enabled)
            except Exception:
                pass

    def set_listening_indicator(self, active: bool):
        """Set listening indicator (compatibility with pyqt_app.py)"""
        # Listening state is handled by state polling
        pass

    def load_chat_history(self, history: list):
        """Load chat history (compatibility with pyqt_app.py)"""
        page = self._page_map.get("assistant")
        if page and hasattr(page, "load_history"):
            try:
                page.load_history(history)
            except Exception:
                pass

    def set_accent_color(self, hex_color: str):
        """Set accent color (compatibility with pyqt_app.py)"""
        self.set_accent(hex_color)

    def request_confirmation(self, title: str, message: str, is_destructive: bool = True) -> bool:
        """Request user confirmation (compatibility with pyqt_app.py)"""
        dlg = QMessageBox(self)
        dlg.setIcon(QMessageBox.Icon.Question if not is_destructive else QMessageBox.Icon.Warning)
        dlg.setWindowTitle(title)
        dlg.setText(message)
        dlg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return dlg.exec() == QMessageBox.StandardButton.Yes

    @property
    def settings_page(self):
        """Access settings page (compatibility with pyqt_app.py)"""
        return self._page_map.get("settings")

    @property
    def task_dock(self):
        """Access task dock (compatibility with pyqt_app.py) - maps to automation page"""
        return self._page_map.get("automation")

    @property
    def memory_page(self):
        """Access memory page (compatibility with pyqt_app.py) - maps to intelligence page"""
        return self._page_map.get("intelligence")

    @property
    def telemetry_page(self):
        """Access telemetry page (compatibility with pyqt_app.py) - maps to intelligence page"""
        return self._page_map.get("intelligence")

    def moveEvent(self, ev):
        super().moveEvent(ev)
        self.dock_geometry_changed.emit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.dock_geometry_changed.emit()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.dock_geometry_changed.emit()
