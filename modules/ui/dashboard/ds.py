"""
Dashboard Design System — Extended (Premium Visual Edition)
============================================================
Builds on modules/ui/design_system.py with refined tokens for the
cinematic, sophisticated, next-gen AI control center.

Principles:
  • 4-level depth (canvas/surface/card/highlight) with subtle 1px borders
  • Subtle 12–32% accent glow, never neon-bright
  • Strict type scale: 11/12/13/14/16/18/22/28/34 px with explicit weights
  • 8-pt spacing grid 4/8/12/16/20/24/32/40
  • Controlled radius ramp: 6/10/14/20/28, pill = 999
  • Consistent component variants with purposeful hover/focus micro-motion
  • Accessibility: ≥ 4.5:1 contrast on body text, visible focus rings

All dashboard components import tokens from here.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, Optional, Tuple

from PyQt6.QtCore import (
    QEasingCurve, QEvent, QObject, QParallelAnimationGroup, QPointF, QPropertyAnimation,
    QRectF, QSize, Qt, QTimer, pyqtProperty, QAbstractAnimation,
)
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QCursor, QFont, QFontDatabase, QIcon,
    QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap,
    QPolygonF, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFrame,
    QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QProgressBar, QPushButton, QRadioButton, QScrollArea, QSizePolicy,
    QSlider, QSpinBox, QSplashScreen, QTableWidget, QTableWidgetItem,
    QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

# Re-export the base design system tokens.
from modules.ui.design_system import (
    C, F, Spacing, Radius, COLOR_PRESETS,
    hex_to_rgb, rgb_to_hex, rgba_str, get_contrast_color,
    ensure_visible_accent,
)

# ─────────────────────────────────────────────────────────────────────
#  REFINED COLOR TOKENS
# ─────────────────────────────────────────────────────────────────────

# -- Short-hands and accent-derived aliases --
C.ACCENT = C.ACCENT_CYAN
C.ACC = C.ACCENT_CYAN

# Accent palette (define once; all pages reference these.)
C.ACC_VIOLET = "#8B5CF6"
C.ACC_VIOLET_DIM = "rgba(139, 92, 246, 0.14)"
C.ACC_EMERALD = "#10B981"
C.ACC_AMBER = "#F59E0B"
C.ACC_ROSE = "#F43F5E"
C.ACCENT_GREEN = getattr(C, "GREEN", C.ACC_EMERALD)

# Section-specific semantic accents
C.SEC_DASHBOARD = "#00D4FF"      # Cyan for dashboard
C.SEC_ASSISTANT = "#00D4FF"     # Cyan/blue for assistant
C.SEC_COMMUNICATIONS = "#3B82F6" # Blue for email
C.SEC_WORKSPACE = "#6366F1"     # Indigo for files
C.SEC_SCHEDULE = "#8B5CF6"       # Violet for calendar
C.SEC_AUTOMATION = "#F59E0B"     # Amber for automation
C.SEC_CONNECTED = "#14B8A6"       # Teal for devices
C.SEC_INTELLIGENCE = "#A855F7"   # Purple for memory
C.SEC_SETTINGS = "#0EA5E9"        # Calm cyan/blue for settings
C.SEC_SETTINGS_GREEN = "#10B981"  # Status success green for settings diagnostics
C.SEC_SETTINGS_VIOLET = "#8B5CF6" # Violet accent for settings options

# Semantic status colors (consistent across all pages)
C.STATUS_SUCCESS = "#10B981"      # Green
C.STATUS_CONNECTED = "#10B981"    # Green
C.STATUS_ACTIVE = "#00D4FF"       # Cyan
C.STATUS_INFO = "#3B82F6"         # Blue
C.STATUS_WARNING = "#F59E0B"      # Amber
C.STATUS_PENDING = "#F59E0B"      # Amber
C.STATUS_ERROR = "#F43F5E"        # Red
C.STATUS_OFFLINE = "#6B7280"      # Muted gray
C.STATUS_DISABLED = "#4B5563"    # Neutral gray

# Semantic fallbacks (base C class is source of truth if populated)
for src, alias in [
    ("GREEN",   C.ACCENT_GREEN),
    ("RED",     C.ACC_ROSE),
    ("ORANGE",  C.ACC_AMBER),
    ("YELLOW",  C.ACC_AMBER),
    ("VIOLET",  C.ACC_VIOLET),
    ("PURPLE",  C.ACC_VIOLET),
]:
    if not hasattr(C, src):
        setattr(C, src, alias)
if not hasattr(C, "TEXT_PRIMARY"):
    C.TEXT_PRIMARY = C.TEXT
if not hasattr(C, "DISABLED"):
    C.DISABLED = "rgba(255, 255, 255, 0.15)"
if not hasattr(C, "ACCENT_VIOLET"):
    C.ACCENT_VIOLET = C.ACC_VIOLET
if not hasattr(C, "ACCENT_CYAN"):
    C.ACCENT_CYAN = C.ACCENT_CYAN
if not hasattr(C, "ACCENT_GREEN"):
    C.ACCENT_GREEN = C.ACCENT_GREEN
if not hasattr(C, "ERROR"):
    C.ERROR = C.ACC_ROSE
if not hasattr(C, "ACC_AMBER"):
    C.ACC_AMBER = "#F59E0B"
if not hasattr(C, "ACC_EMERALD"):
    C.ACC_EMERALD = "#10B981"

# -- Obsidian canvas (levels of depth) --
C.CANVAS_BG = "#040609"            # app background (deepest)
C.SURFACE_BG = "#070B11"           # sidebar / topbar shell
C.PANEL_BG = "#0A1118"             # page container
C.CARD_BG = "#0E161F"              # default card body
C.CARD_HIGHLIGHT = "#121C27"       # elevated / hover card
C.CARD_BG_ALT = "#121C27"          # alternate card background
C.HIGHLIGHT_GLOW = "rgba(0, 212, 255, 0.04)"  # subtle 4% tint

# -- Glass --
C.GLASS_STRONG = "rgba(6, 10, 15, 246)"
C.GLASS_MED = "rgba(8, 13, 18, 188)"
C.GLASS_LIGHT = "rgba(8, 13, 18, 96)"

# -- Contrast-aware borders (use 8–14% accent tint, never solid white) --
C.BORDER = "rgba(148, 184, 204, 0.10)"       # card/cell outline
C.BORDER_MED = "rgba(148, 184, 204, 0.16)"   # panel outline
C.BORDER_HARD = "rgba(148, 184, 204, 0.24)"  # dialog / highlight ring
C.DIVIDER = "rgba(148, 184, 204, 0.07)"      # 7% divider hairline
C.DIVIDER_STRONG = "rgba(148, 184, 204, 0.14)"

# -- Shell surfaces --
C.SIDEBAR_BG = "#05080C"
C.SIDEBAR_HOVER = "#0C141C"
C.SIDEBAR_ACTIVE = "#121C27"
C.TOPBAR_BG = "#05080C"

# -- Focus ring (visible accent outline, non-obtrusive) --
C.FOCUS_RING = "rgba(0, 212, 255, 0.35)"

# ─────────────────────────────────────────────────────────────────────
#  EXTENDED SPACING / RADIUS / DEPTH
# ─────────────────────────────────────────────────────────────────────

# Spacing ramp (8-pt grid + midpoints for density control)
Spacing.SM2 = 6
Spacing.LG2 = 20
Spacing.XL2 = 32
Spacing.XXL2 = 48
Spacing.XXXL = 64

# Radius ramp — more controlled to avoid "excessive rounded cards"
Radius.XS = 4
Radius.MD2 = 12
Radius.XL2 = 20

# Elevation: QGraphicsDropShadowEffect presets (accent-aware, soft, shallow)
class Elevation:
    NONE = (0, 0, 0, 0)
    LOW = (0, 2, 8, 22)
    MID = (0, 4, 16, 30)
    HIGH = (0, 6, 28, 38)
    HIGHLIGHT = (0, 0, 20, 44)
    DIALOG = (0, 10, 48, 64)     # dialogs / modals
    GLOW_SOFT = (0, 0, 14, 52)   # centered soft accent glow
    GLOW_HALO = (0, 0, 32, 70)   # strong centered halo (focused states)


class SidebarSize:
    WIDTH_EXPANDED = 260
    WIDTH_COLLAPSED = 70
    TOPBAR_HEIGHT = 64
    STATUS_HEIGHT = 36
    MINIMUM_ORB = 240
    BRAND_PAD = 18
    NAV_PAD_H = 12
    NAV_ROW_PAD_V = 11
    NAV_ROW_PAD_H = 14
    NAV_INDICATOR_W = 3


class Density:
    """Named UI density profiles; controls inner padding defaults."""
    COMFORTABLE = dict(pad=Spacing.LG2, gap=Spacing.MD, row=Spacing.LG2)
    COZY = dict(pad=Spacing.MD + 2, gap=Spacing.SM + 2, row=Spacing.MD + 6)
    COMPACT = dict(pad=Spacing.SM + 2, gap=Spacing.SM2, row=Spacing.MD)


class Animation:
    """Timing & easing presets. FAST/INSTANT for micro-interactions."""
    INSTANT = 50
    MICRO = 90
    FAST = 140
    NORMAL = 220
    SLOW = 380
    SLOWER = 680

    EASE_IN_OUT = QEasingCurve(QEasingCurve.Type.InOutCubic)
    EASE_OUT = QEasingCurve(QEasingCurve.Type.OutCubic)
    EASE_IN = QEasingCurve(QEasingCurve.Type.InCubic)
    EASE_DECEL = QEasingCurve(QEasingCurve.Type.OutExpo)
    EASE_SPRING = QEasingCurve(QEasingCurve.Type.OutBack)
    EASE_SINE = QEasingCurve(QEasingCurve.Type.InOutSine)
    EASE_EMPHASIS = QEasingCurve(QEasingCurve.Type.OutElastic)


# ─────────────────────────────────────────────────────────────────────
#  EXTENDED TYPOGRAPHY SCALE (Font QSS helpers)
# ─────────────────────────────────────────────────────────────────────

class TypeScale:
    """Immutable typographic scale for the dashboard.

    Every page must use these sizes via .setObjectName() / QSS class:
      Overline / Caption / Body-sm / Body / Body-lg / Subtitle /
      Title-sm / Title / Title-lg / Display
    """
    OVERLINE = ("", 10, 700, 2.4)
    CAPTION = ("", 11, 500, 0.2)
    BODY_SM = ("", 12, 400, 0.0)
    BODY = ("", 13, 400, 0.0)
    BODY_LG = ("", 14, 500, 0.0)
    SUBTITLE = ("", 15, 600, -0.1)
    TITLE_SM = ("", 17, 600, -0.2)
    TITLE = ("", 19, 700, -0.3)
    TITLE_LG = ("", 24, 700, -0.5)
    DISPLAY = ("", 32, 800, -0.8)

    @staticmethod
    def qss(cls: str, scale_tuple, color: str) -> str:
        fam, size, weight_100, ls = scale_tuple
        ls_px = f"letter-spacing: {ls:.1f}px;" if ls else ""
        w = weight_100
        return (
            f".{cls} {{"
            f" font-size: {size}px; font-weight: {w};"
            f" color: {color}; {ls_px} background: transparent; background-color: transparent;"
            f"}}"
        )


import os
os.environ.setdefault("QT_API", "pyqt6")

# ─────────────────────────────────────────────────────────────────────
#  ICONS (FontAwesome 5 names — fully compatible with qtawesome)
# ─────────────────────────────────────────────────────────────────────

class ICONS:
    HOME = "fa5s.home"
    ASSISTANT = "fa5s.robot"
    COMMUNICATIONS = "fa5s.envelope"
    WORKSPACE = "fa5s.folder-open"
    SCHEDULE = "fa5s.calendar-alt"
    AUTOMATION = "fa5s.bolt"
    CONNECTED_WORLD = "fa5s.network-wired"
    INTELLIGENCE = "fa5s.brain"
    SETTINGS = "fa5s.cog"
    SEARCH = "fa5s.search"
    MIC = "fa5s.microphone"
    SEND = "fa5s.paper-plane"
    PLUS = "fa5s.plus"
    CLOSE = "fa5s.times"
    BELL = "fa5s.bell"
    USER = "fa5s.user"
    POWER = "fa5s.power-off"
    REFRESH = "fa5s.sync-alt"
    PLAY = "fa5s.play"
    PAUSE = "fa5s.pause"
    STOP = "fa5s.stop"
    EDIT = "fa5s.edit"
    TRASH = "fa5s.trash-alt"
    COPY = "fa5s.copy"
    DOWNLOAD = "fa5s.download"
    UPLOAD = "fa5s.upload"
    SAVE = "fa5s.save"
    CHECK = "fa5s.check"
    WARNING = "fa5s.exclamation-triangle"
    INFO = "fa5s.info-circle"
    CHEVRON_RIGHT = "fa5s.chevron-right"
    CHEVRON_DOWN = "fa5s.chevron-down"
    CHEVRON_LEFT = "fa5s.chevron-left"
    MENU = "fa5s.bars"
    PIN = "fa5s.thumbtack"
    STAR = "fa5s.star"
    CLOCK = "fa5s.clock"
    FILE = "fa5s.file"
    FILE_PDF = "fa5s.file-pdf"
    FILE_WORD = "fa5s.file-word"
    FILE_EXCEL = "fa5s.file-excel"
    FILE_POWERPOINT = "fa5s.file-powerpoint"
    LIGHTBULB = "fa5s.lightbulb"
    THERMOMETER = "fa5s.thermometer-half"
    FAN = "fa5s.fan"
    LOCK = "fa5s.lock"
    UNLOCK = "fa5s.unlock"
    VOLUME_UP = "fa5s.volume-up"
    VOLUME_MUTE = "fa5s.volume-mute"
    CAMERA = "fa5s.camera"
    PHONE = "fa5s.mobile-alt"
    DESKTOP = "fa5s.desktop"
    HOME_SMART = "fa5s.home"
    MUSIC = "fa5s.music"
    EYE = "fa5s.eye"
    EYE_SLASH = "fa5s.eye-slash"
    ARROW_RIGHT = "fa5s.arrow-right"
    ARROW_UP = "fa5s.arrow-up"
    ARROW_DOWN = "fa5s.arrow-down"
    ARROW_LEFT = "fa5s.arrow-left"
    DIAGNOSTICS = "fa5s.stethoscope"
    DATABASE = "fa5s.database"
    SATELLITE_DISH = "fa5s.satellite-dish"
    WAND_MAGIC = "fa5s.magic"
    BARS = "fa5s.chart-bar"
    PREV = "fa5s.step-backward"
    NEXT = "fa5s.step-forward"
    REPLY = "fa5s.reply"
    REPLY_ALL = "fa5s.reply-all"
    FORWARD = "fa5s.share"
    ATTACH = "fa5s.paperclip"
    GLOBE = "fa5s.globe"
    LOGOUT = "fa5s.sign-out-alt"
    BRAIN = "fa5s.brain"
    NETWORK_WIRED = "fa5s.network-wired"
    BATTERY = "fa5s.battery-half"
    FOLDER_OPEN = "fa5s.folder-open"
    BOLT = "fa5s.bolt"


# ─────────────────────────────────────────────────────────────────────
#  ICON LOADER (lazy, optional qtawesome)
# ─────────────────────────────────────────────────────────────────────

_ICON_CACHE: Dict[str, QIcon] = {}
_PIXMAP_CACHE: Dict[str, QPixmap] = {}
_QTA_AVAILABLE: Optional[bool] = None


def qta_available() -> bool:
    global _QTA_AVAILABLE
    if _QTA_AVAILABLE is None:
        try:
            import qtawesome  # noqa: F401
            _QTA_AVAILABLE = True
        except Exception:
            _QTA_AVAILABLE = False
    return _QTA_AVAILABLE


def icon(name: str, color: str = C.TEXT, size: int = 16) -> QIcon:
    key = f"{name}|{color}|{size}|ic"
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    if qta_available():
        try:
            import qtawesome as qta
            ic = qta.icon(name, color=color, color_disabled=C.TEXT_DIM)
            _ICON_CACHE[key] = ic
            return ic
        except Exception as e:
            pass
    # Fallback: render a simple geometric icon based on name patterns
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    try:
        r, g, b = hex_to_rgb(color)
    except Exception:
        r, g, b = 155, 188, 204
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(r, g, b, 210))
    
    # Draw different shapes based on icon name patterns
    center = size / 2
    if 'home' in name.lower() or 'house' in name.lower():
        # House shape
        p.drawPolygon([
            QPointF(center, size * 0.2),
            QPointF(size * 0.9, size * 0.45),
            QPointF(size * 0.9, size * 0.8),
            QPointF(size * 0.1, size * 0.8),
            QPointF(size * 0.1, size * 0.45)
        ])
    elif 'user' in name.lower() or 'person' in name.lower():
        # Circle (user icon)
        p.drawEllipse(QPointF(center, center), size * 0.35, size * 0.35)
    elif 'settings' in name.lower() or 'gear' in name.lower():
        # Gear-like circle with notch
        p.drawEllipse(QPointF(center, center), size * 0.35, size * 0.35)
        p.setBrush(QColor(0, 0, 0, 0))
        p.drawEllipse(QPointF(center, center), size * 0.15, size * 0.15)
    elif 'search' in name.lower() or 'magnifying' in name.lower():
        # Magnifying glass
        p.drawEllipse(QPointF(center * 0.7, center * 0.7), size * 0.25, size * 0.25)
        p.setBrush(QColor(r, g, b, 210))
        p.setPen(QPen(QColor(r, g, b, 210), 2))
        p.drawLine(int(center * 0.85), int(center * 0.85), int(size * 0.9), int(size * 0.9))
    elif 'mail' in name.lower() or 'envelope' in name.lower() or 'email' in name.lower():
        # Envelope
        p.drawRect(QRectF(size * 0.15, size * 0.3, size * 0.7, size * 0.5))
        p.setBrush(QColor(0, 0, 0, 0))
        p.drawRect(QRectF(size * 0.15, size * 0.35, size * 0.7, size * 0.3))
    elif 'file' in name.lower() or 'folder' in name.lower():
        # File/folder
        p.drawRect(QRectF(size * 0.2, size * 0.15, size * 0.6, size * 0.7))
        p.setBrush(QColor(0, 0, 0, 0))
        p.drawRect(QRectF(size * 0.25, size * 0.2, size * 0.25, size * 0.05))
    elif 'calendar' in name.lower() or 'date' in name.lower():
        # Calendar
        p.drawRect(QRectF(size * 0.15, size * 0.15, size * 0.7, size * 0.7))
        p.setBrush(QColor(0, 0, 0, 0))
        p.drawRect(QRectF(size * 0.15, size * 0.15, size * 0.7, size * 0.25))
    elif 'bell' in name.lower() or 'notification' in name.lower():
        # Bell
        p.drawEllipse(QPointF(center, size * 0.35), size * 0.25, size * 0.25)
        p.setBrush(QColor(r, g, b, 210))
        p.drawPolygon([
            QPointF(center, size * 0.15),
            QPointF(center - size * 0.15, size * 0.55),
            QPointF(center + size * 0.15, size * 0.55)
        ])
    elif 'mic' in name.lower() or 'microphone' in name.lower():
        # Microphone
        p.drawEllipse(QPointF(center, size * 0.4), size * 0.25, size * 0.15)
        p.drawRect(QRectF(center - size * 0.03, size * 0.45, size * 0.06, size * 0.35))
    elif 'plus' in name.lower() or 'add' in name.lower():
        # Plus sign
        p.setBrush(QColor(r, g, b, 210))
        p.drawRect(QRectF(center - size * 0.03, size * 0.2, size * 0.06, size * 0.6))
        p.drawRect(QRectF(size * 0.2, center - size * 0.03, size * 0.6, size * 0.06))
    elif 'trash' in name.lower() or 'delete' in name.lower():
        # Trash can
        p.drawRect(QRectF(size * 0.25, size * 0.2, size * 0.5, size * 0.6))
        p.setBrush(QColor(0, 0, 0, 0))
        p.drawPolygon([
            QPointF(size * 0.25, size * 0.15),
            QPointF(size * 0.5, size * 0.25),
            QPointF(size * 0.75, size * 0.15)
        ])
    elif 'save' in name.lower() or 'floppy' in name.lower():
        # Save disk
        p.drawRect(QRectF(size * 0.2, size * 0.2, size * 0.6, size * 0.6))
        p.setBrush(QColor(0, 0, 0, 0))
        p.drawRect(QRectF(size * 0.2, size * 0.2, size * 0.6, size * 0.15))
    elif 'close' in name.lower() or 'xmark' in name.lower():
        # X mark
        p.setBrush(QColor(r, g, b, 210))
        p.drawRect(QRectF(center - size * 0.2, center - size * 0.03, size * 0.4, size * 0.06))
        p.drawRect(QRectF(center - size * 0.03, center - size * 0.2, size * 0.06, size * 0.4))
    elif 'brain' in name.lower() or 'intelligence' in name.lower():
        # Brain-like shape
        p.drawEllipse(QPointF(center, center), size * 0.35, size * 0.3)
        p.drawEllipse(QPointF(center - size * 0.15, center + size * 0.1), size * 0.15, size * 0.15)
        p.drawEllipse(QPointF(center + size * 0.15, center + size * 0.1), size * 0.15, size * 0.15)
    elif 'device' in name.lower() or 'phone' in name.lower() or 'mobile' in name.lower():
        # Device/phone
        p.drawRoundedRect(QRectF(size * 0.2, size * 0.15, size * 0.6, size * 0.7), 4, 4)
        p.setBrush(QColor(0, 0, 0, 0))
        p.drawEllipse(QPointF(center, size * 0.3), size * 0.1, size * 0.08)
    else:
        # Default circle
        p.drawEllipse(QPointF(center, center), size * 0.35, size * 0.35)
    
    p.end()
    ic = QIcon(pm)
    _ICON_CACHE[key] = ic
    return ic


def icon_pixmap(name: str, color: str = C.TEXT, size: int = 16) -> QPixmap:
    key = f"{name}|{color}|{size}|pm"
    if key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[key]
    pm = icon(name, color, size).pixmap(size, size)
    _PIXMAP_CACHE[key] = pm
    return pm


# ─────────────────────────────────────────────────────────────────────
#  GLOW / ELEVATION HELPERS
# ─────────────────────────────────────────────────────────────────────

def make_glow(widget: QWidget, color: str = C.ACCENT_CYAN,
              blur: int = 28, alpha: int = 70) -> QGraphicsDropShadowEffect:
    """Attach a soft centered accent glow to a widget.

    Shallow by default: no X/Y offset, so it reads as focused highlight
    rather than a cheap 3-D drop shadow.
    """
    r, g, b = hex_to_rgb(color)
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setXOffset(0)
    eff.setYOffset(0)
    eff.setColor(QColor(r, g, b, max(0, min(255, alpha))))
    widget.setGraphicsEffect(eff)
    return eff


def make_elevation(widget: QWidget, y_off: int = 3, blur: int = 18,
                   alpha: int = 40, color: str = "#000000") -> QGraphicsDropShadowEffect:
    """Soft 'realistic' elevation shadow used for modal dialogs / highlights."""
    r, g, b = hex_to_rgb(color)
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setXOffset(0)
    eff.setYOffset(y_off)
    eff.setColor(QColor(r, g, b, alpha))
    widget.setGraphicsEffect(eff)
    return eff


# ─────────────────────────────────────────────────────────────────────
#  LAYOUT HELPERS
# ─────────────────────────────────────────────────────────────────────

def clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        try:
            w = item.widget()
            if w is not None:
                try:
                    import sip
                    if not sip.isdeleted(w):
                        w.setParent(None)
                        w.deleteLater()
                except Exception:
                    try:
                        w.setParent(None)
                        w.deleteLater()
                    except Exception:
                        pass
            else:
                sub = item.layout()
                if sub is not None:
                    clear_layout(sub)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────
#  FADE-IN / PAGE TRANSITION MIXIN
# ─────────────────────────────────────────────────────────────────────

class FadeInPageMixin(QObject):
    """Mix into a page QWidget to animate opacity when shown.

    Use: class MyPage(QWidget, FadeInPageMixin): ...  then call
    self._install_fade() at end of __init__ and override on_visible().

    For already-instantiated widgets, call FadeInPageMixin.install_on(widget)
    to attach a lightweight fade-timer proxy (no inheritance required).
    """

    def __init__(self, duration: int = Animation.SLOW):
        super().__init__()
        self._fade_dur = duration
        self._fade_installed = False
        self._window_opacity_target = 1.0

    @classmethod
    def install_on(cls, widget: QWidget, duration: int = Animation.SLOW) -> "FadeInPageMixin":
        """Attach fade-in to an existing widget (returns proxy used for tracking)."""
        proxy = cls(duration=duration)
        proxy.setParent(widget)
        # Install the timer onto widget via proxy.__dict__ injection
        widget._fade_proxy = proxy
        proxy._bind_to(widget)
        proxy._install_fade()
        return proxy

    def _bind_to(self, widget):
        """Create the timer parented to widget so it fires on widget lifecycle."""
        self._bind_widget = widget

    def _install_fade(self):
        if self._fade_installed:
            return
        self._fade_installed = True
        # QWidget windowOpacity works top-level only; skip for non-toplevel widgets
        # Use a simple timer + repaint-friendly QPropertyAnimation via graphicsOpacity proxy:
        self._fade_eff = QGraphicsDropShadowEffect(self)
        self._fade_eff.setBlurRadius(0)
        self._fade_eff.setColor(QColor(0, 0, 0, 0))
        # Use a "fake" animation that fires a slot to restyle: QProperty's "opacity" doesn't exist
        # on plain widgets, so we simulate via QTimer with easing curve instead (no flicker).
        self._fade_t = 0.0
        self._fade_anim_timer = QTimer(self)
        self._fade_anim_timer.setInterval(16)

        def tick():
            self._fade_t = min(1.0, self._fade_t + (16.0 / max(40.0, float(self._fade_dur))))
            # Apply soft repaint; we don't change top-level opacity to avoid flicker on Win.
            # Instead, emit a repaint via update().
            try:
                target = getattr(self, "_bind_widget", None) or self
                target.update()
            except Exception:
                pass
            if self._fade_t >= 1.0:
                self._fade_anim_timer.stop()

        self._fade_anim_timer.timeout.connect(tick)
        QTimer.singleShot(20, self._fade_anim_timer.start)


# ─────────────────────────────────────────────────────────────────────
#  HOVER LIFT — Subtle elevation micro-animation for card surfaces
# ─────────────────────────────────────────────────────────────────────

class HoverLift(QObject):
    """Attaches to any widget and adds a 2px upward hover lift + accent glow.

    Works purely via event-filter + QGraphicsDropShadowEffect; no Qt
    property animations (avoids Windows compositor flicker).

    Use:
        HoverLift.install_on(my_card)
        HoverLift.install_on(kpi_tile, accent=C.ACC_AMBER)
    """

    def __init__(self, target: QWidget, dy: int = -2,
                 blur_normal: int = Elevation.LOW[2],
                 blur_hover: int = Elevation.MID[2],
                 accent: str = C.ACCENT_CYAN):
        super().__init__(target)
        self._t = target
        self._dy = dy
        self._bn = blur_normal
        self._bh = blur_hover
        self._acc = accent
        self._orig_y = target.y() if target.parentWidget() else 0
        self._parent_layout_item = False
        self._eff: Optional[QGraphicsDropShadowEffect] = None
        self._install_effect()

    @classmethod
    def install_on(cls, widget: QWidget, dy: int = -2,
                   blur_normal: int = Elevation.LOW[2],
                   blur_hover: int = Elevation.MID[2],
                   accent: str = C.ACCENT_CYAN) -> "HoverLift":
        proxy = cls(widget, dy=dy, blur_normal=blur_normal,
                    blur_hover=blur_hover, accent=accent)
        widget.installEventFilter(proxy)
        return proxy

    def _install_effect(self):
        try:
            eff = QGraphicsDropShadowEffect(self._t)
            eff.setBlurRadius(self._bn)
            eff.setXOffset(0)
            eff.setYOffset(2)
            r, g, b = hex_to_rgb(self._acc)
            eff.setColor(QColor(r, g, b, Elevation.LOW[3]))
            self._t.setGraphicsEffect(eff)
            self._eff = eff
        except Exception:
            self._eff = None

    def _set_lifted(self, lifted: bool):
        # Shadow swap
        if self._eff is not None:
            r, g, b = hex_to_rgb(self._acc)
            if lifted:
                self._eff.setBlurRadius(self._bh)
                self._eff.setYOffset(4)
                self._eff.setColor(QColor(r, g, b, Elevation.MID[3]))
            else:
                self._eff.setBlurRadius(self._bn)
                self._eff.setYOffset(2)
                self._eff.setColor(QColor(r, g, b, Elevation.LOW[3]))
        # Vertical offset — try to nudge via parent geometry if inside a layout.
        p = self._t.parentWidget()
        if p is not None and p.layout() is not None:
            # Prefer margins — many cards are in QGridLayout/QHBoxLayout cells;
            # we nudge widget geometry via setContentsMargins on the containing
            # layout item if possible, otherwise rely on shadow only.
            try:
                m = self._t.contentsMargins()
                if lifted:
                    self._t.setContentsMargins(m.left(), max(0, m.top() + self._dy),
                                               m.right(), m.bottom() - self._dy)
                else:
                    self._t.setContentsMargins(m.left(), max(0, m.top() - self._dy),
                                               m.right(), m.bottom() + self._dy)
            except Exception:
                pass

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        t = ev.type()
        if t == QEvent.Type.Enter:
            self._set_lifted(True)
        elif t == QEvent.Type.Leave:
            self._set_lifted(False)
        return super().eventFilter(obj, ev)


# ─────────────────────────────────────────────────────────────────────
#  STYLESHEET (built from tokens)
# ─────────────────────────────────────────────────────────────────────

_CHEVRON_SVG_PATH = os.path.join(os.path.dirname(__file__), "chevron_down.svg").replace("\\", "/")

def dashboard_stylesheet(accent_hex: str = C.ACCENT_CYAN) -> str:
    accent = ensure_visible_accent(accent_hex or C.ACCENT_CYAN)
    acc_dim = rgba_str(accent, 0.12)
    acc_dim2 = rgba_str(accent, 0.18)
    acc_gho = rgba_str(accent, 0.045)
    acc_gho2 = rgba_str(accent, 0.08)
    acc_border = rgba_str(accent, 0.30)
    acc_border_a = rgba_str(accent, 0.18)
    acc_focus = rgba_str(accent, 0.42)
    acc_faint = rgba_str(accent, 0.025)
    text_on_accent = get_contrast_color(accent)
    r, g, b = hex_to_rgb(accent)

    def shade(pct: int) -> str:
        sign = 1 if pct >= 0 else -1
        amt = abs(pct) / 100.0
        return rgb_to_hex(
            min(255, int(r + sign * (255 - r) * amt)) if sign > 0 else int(r * (1 - amt)),
            min(255, int(g + sign * (255 - g) * amt)) if sign > 0 else int(g * (1 - amt)),
            min(255, int(b + sign * (255 - b) * amt)) if sign > 0 else int(b * (1 - amt)),
        )

    type_css = (
        TypeScale.qss("Overline", TypeScale.OVERLINE, C.TEXT_DIM) +
        TypeScale.qss("Caption", TypeScale.CAPTION, C.TEXT_DIM) +
        TypeScale.qss("BodySm", TypeScale.BODY_SM, C.TEXT_MED) +
        TypeScale.qss("Body", TypeScale.BODY, C.TEXT) +
        TypeScale.qss("BodyLg", TypeScale.BODY_LG, C.TEXT) +
        TypeScale.qss("Subtitle", TypeScale.SUBTITLE, C.TEXT) +
        TypeScale.qss("TitleSm", TypeScale.TITLE_SM, C.TEXT) +
        TypeScale.qss("Title", TypeScale.TITLE, C.TEXT) +
        TypeScale.qss("TitleLg", TypeScale.TITLE_LG, C.TEXT) +
        TypeScale.qss("Display", TypeScale.DISPLAY, C.TEXT)
    )

    return f"""
    /* ============================================================
       DASHBOARD CORE STYLESHEET  — Premium Cinematic Edition
       Accent: {accent}
       ============================================================ */
    QWidget {{
        background-color: transparent;
        color: {C.TEXT};
        font-family: "{F.PRIMARY}", "Segoe UI", "Inter", system-ui;
        font-size: 13px;
        outline: 0;
        selection-background-color: {acc_dim};
        selection-color: {C.TEXT};
    }}
    DashboardMainWindow, QWidget#DashboardMainWindow, QMainWindow, QDialog,
    QWidget#AppRoot, .AppCanvas {{
        background-color: {C.CANVAS_BG};
        background: {C.CANVAS_BG};
    }}
    QStackedWidget, .PageRoot {{
        background-color: transparent;
        background: transparent;
    }}

    /* ---------- Text Labels — always transparent so they sit naturally on surfaces ---------- */
    QLabel {{
        background-color: transparent;
        background: transparent;
    }}

    /* ---------- Scroll areas & Viewports — transparent canvas ---------- */
    QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{
        background-color: transparent;
        background: transparent;
    }}

    /* ---------- Tooltips (glass-style) ---------- */
    QToolTip {{
        background: {C.CARD_HIGHLIGHT};
        color: {C.TEXT};
        border: 1px solid {acc_border_a};
        padding: 7px 12px;
        border-radius: {Radius.SM}px;
        font-size: 12px;
    }}

    /* ---------- Scrollbars — refined slim profile ---------- */
    QScrollBar:vertical, QScrollBar:horizontal {{
        background: transparent;
        border: none;
        margin: 3px;
    }}
    QScrollBar:vertical   {{ width: 5px; }}
    QScrollBar:horizontal {{ height: 5px; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: rgba(148,184,204,0.14);
        border-radius: 3px;
        min-height: 28px; min-width: 28px;
    }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
        background: {rgba_str(accent, 0.38)};
    }}
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; border: none; height: 0; width: 0;
    }}

    /* ---------- Shell layers ---------- */
    .SidebarPanel {{
        background: {C.SIDEBAR_BG};
        border-right: 1px solid {C.BORDER};
    }}
    .TopbarPanel {{
        background: {C.TOPBAR_BG};
        border-bottom: 1px solid {C.BORDER};
    }}
    .StatusStrip {{
        background: {C.SURFACE_BG};
        border-top: 1px solid {C.BORDER};
    }}

    /* ---------- Typography classes ---------- */
    {type_css}

    /* ---------- Cards — refined border + hover lift ---------- */
    .CardPanel {{
        background: {C.CARD_BG};
        border: 1px solid {C.BORDER};
        border-radius: {Radius.MD2}px;
    }}
    .CardPanel:hover {{
        border-color: {C.BORDER_MED};
        background: {C.CARD_BG};
    }}
    .CardInner {{
        background: rgba(148, 184, 204, 0.05);
        border: 1px solid {C.BORDER};
        border-radius: {Radius.MD}px;
    }}
    .CardInner:hover {{
        background: rgba(148, 184, 204, 0.09);
        border-color: {C.BORDER_MED};
    }}
    .CardInner[accented="true"] {{
        border-color: {acc_border_a};
        background: {acc_gho};
    }}
    .CardPanel QLabel, .CardInner QLabel {{
        background-color: transparent;
        background: transparent;
    }}
    SectionHeader, SectionHeader QLabel, #PageTitle, #PageSubtitle {{
        background-color: transparent;
        background: transparent;
    }}

    /* ---------- Sidebar Navigation — premium row styling ---------- */
    .NavButton {{
        background: transparent;
        color: {C.TEXT_MED};
        border: 1px solid transparent;
        border-radius: 9px;
        padding: 11px 14px 11px 14px;
        text-align: left;
        font-weight: 500;
        font-size: 13px;
        margin: 1px {SidebarSize.NAV_PAD_H}px;
    }}
    .NavButton:hover {{
        background: {C.SIDEBAR_HOVER};
        color: {C.TEXT};
        border-color: {C.BORDER};
    }}
    .NavButton[active="true"] {{
        background: {acc_dim};
        color: {accent};
        border: 1px solid {acc_border_a};
    }}
    .NavButton[active="true"]:hover {{ background: {acc_dim2}; }}

    /* ---------- Buttons — standard ---------- */
    QPushButton {{
        background: {C.CARD_BG};
        color: {C.TEXT};
        border: 1px solid {C.BORDER};
        border-radius: 9px;
        padding: 9px 15px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background: {C.CARD_HIGHLIGHT};
        border-color: {acc_border_a};
        color: {C.WHITE};
    }}
    QPushButton:focus {{
        border-color: {acc_focus};
        background: {acc_faint};
    }}
    QPushButton:pressed {{
        background: {C.SURFACE_BG};
        padding-top: 10px;
        padding-bottom: 8px;
    }}
    QPushButton:disabled {{
        color: {C.TEXT_DIM};
        border-color: {C.BORDER};
        background: {C.SURFACE_BG};
    }}

    /* Primary — luminous accent fill */
    QPushButton#PrimaryBtn {{
        background: {accent};
        color: {text_on_accent};
        border: 1px solid {accent};
        font-weight: 600;
    }}
    QPushButton#PrimaryBtn:hover {{
        background: {shade(12)};
        border-color: {shade(12)};
    }}
    QPushButton#PrimaryBtn:focus {{
        border: 1px solid {accent};
    }}
    QPushButton#PrimaryBtn:pressed {{
        background: {shade(-8)};
        border-color: {shade(-8)};
    }}
    QPushButton#PrimaryBtn:disabled {{
        background: {rgba_str(accent, 0.30)};
        border-color: {rgba_str(accent, 0.20)};
        color: {text_on_accent};
    }}

    /* Ghost — minimal chrome until hover */
    QPushButton#GhostBtn {{
        background: transparent;
        border: 1px solid {C.BORDER_MED};
        color: {C.TEXT_MED};
    }}
    QPushButton#GhostBtn:hover {{
        background: {C.CARD_BG};
        color: {C.TEXT};
        border-color: {acc_border_a};
    }}
    QPushButton#GhostBtn:pressed {{
        background: {C.SURFACE_BG};
    }}

    /* Success — semantic green */
    QPushButton#SuccessBtn {{
        background: {rgba_str(C.STATUS_SUCCESS, 0.12)};
        color: {C.STATUS_SUCCESS};
        border: 1px solid {rgba_str(C.STATUS_SUCCESS, 0.28)};
        font-weight: 600;
    }}
    QPushButton#SuccessBtn:hover {{
        background: {rgba_str(C.STATUS_SUCCESS, 0.20)};
        color: #D1FAE5;
        border-color: {rgba_str(C.STATUS_SUCCESS, 0.44)};
    }}

    /* Warning — semantic amber */
    QPushButton#WarningBtn {{
        background: {rgba_str(C.STATUS_WARNING, 0.12)};
        color: {C.STATUS_WARNING};
        border: 1px solid {rgba_str(C.STATUS_WARNING, 0.28)};
        font-weight: 600;
    }}
    QPushButton#WarningBtn:hover {{
        background: {rgba_str(C.STATUS_WARNING, 0.20)};
        color: #FEF3C7;
        border-color: {rgba_str(C.STATUS_WARNING, 0.44)};
    }}

    /* Danger — semantic red */
    QPushButton#DangerBtn {{
        background: {rgba_str(C.STATUS_ERROR, 0.08)};
        color: {C.STATUS_ERROR};
        border: 1px solid {rgba_str(C.STATUS_ERROR, 0.26)};
        font-weight: 600;
    }}
    QPushButton#DangerBtn:hover {{
        background: {rgba_str(C.STATUS_ERROR, 0.18)};
        color: #FFE4E6;
        border-color: {rgba_str(C.STATUS_ERROR, 0.42)};
    }}

    /* Icon-only button — quiet until interaction */
    QPushButton#IconBtn {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 6px;
        color: {C.TEXT_MED};
    }}
    QPushButton#IconBtn:hover {{
        background: {C.CARD_BG};
        border-color: {C.BORDER};
        color: {C.TEXT};
    }}
    QPushButton#IconBtn:focus {{
        border-color: {acc_focus};
        background: {acc_faint};
    }}

    /* ---------- Inputs — refined focus halo ---------- */
    QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QTimeEdit, QDateEdit, QDateTimeEdit {{
        background: {C.CARD_BG};
        color: {C.TEXT};
        border: 1px solid {C.BORDER};
        border-radius: 9px;
        padding: 6px 11px;
        selection-background-color: {acc_dim};
        selection-color: {C.TEXT};
    }}
    QLineEdit {{
        padding: 6px 11px;
    }}
    QComboBox {{
        padding: 5px 10px;
    }}
    QLineEdit:hover, QTextEdit:hover, QComboBox:hover,
    QSpinBox:hover, QDoubleSpinBox:hover {{
        border-color: {C.BORDER_MED};
    }}
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus,
    QSpinBox:focus, QDoubleSpinBox:focus,
    QTimeEdit:focus, QDateEdit:focus, QDateTimeEdit:focus {{
        border-color: {accent};
        background: {acc_faint};
    }}
    QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {{
        color: {C.TEXT_DIM};
        background: {C.SURFACE_BG};
        border-color: {C.BORDER};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 26px;
        border: none;
        background: transparent;
    }}
    QComboBox::down-arrow {{
        image: url("{_CHEVRON_SVG_PATH}");
        width: 11px;
        height: 7px;
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {C.CARD_BG};
        color: {C.TEXT};
        border: 1px solid {acc_border_a};
        border-radius: 10px;
        padding: 5px;
        selection-background-color: {acc_dim};
        selection-color: {C.TEXT};
        outline: 0;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 28px;
        padding: 0 10px;
        border-radius: {Radius.SM}px;
    }}

    /* ---------- Checkboxes / Radios ---------- */
    QCheckBox {{
        spacing: 10px;
        color: {C.TEXT};
    }}
    QCheckBox::indicator {{
        width: 17px; height: 17px;
        border-radius: {Radius.XS}px;
        border: 1px solid {C.BORDER_MED};
        background: {C.CARD_BG};
    }}
    QCheckBox::indicator:hover {{ border-color: {acc_border_a}; }}
    QCheckBox::indicator:checked {{
        background: {accent};
        border-color: {accent};
    }}
    QCheckBox::indicator:focus {{ border-color: {acc_focus}; }}

    QRadioButton {{
        spacing: 10px;
        color: {C.TEXT};
    }}
    QRadioButton::indicator {{
        width: 17px; height: 17px;
        border-radius: 9px;
        border: 1px solid {C.BORDER_MED};
        background: {C.CARD_BG};
    }}
    QRadioButton::indicator:hover {{ border-color: {acc_border_a}; }}
    QRadioButton::indicator:checked {{
        background: {accent};
        border-color: {accent};
    }}

    /* ---------- Sliders ---------- */
    QSlider::groove:horizontal {{
        height: 4px;
        background: rgba(148, 184, 204, 0.10);
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {accent};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 15px; height: 15px;
        margin: -6px 0;
        border-radius: 8px;
        background: #F4FAFF;
        border: 2px solid {accent};
    }}
    QSlider::handle:horizontal:hover {{
        background: #FFFFFF;
        width: 16px; height: 16px;
        margin: -7px 0;
    }}

    /* ---------- Progress bars ---------- */
    QProgressBar {{
        background: rgba(148,184,204,0.07);
        border: 1px solid {C.BORDER};
        border-radius: 9px;
        text-align: center;
        color: {C.TEXT};
        height: 9px;
        padding: 0;
    }}
    QProgressBar::chunk {{
        background: {accent};
        border-radius: 9px;
    }}

    /* ---------- Tables / Lists ---------- */
    QListWidget, QTableWidget, QTreeWidget {{
        background: {C.CARD_BG};
        border: 1px solid {C.BORDER};
        border-radius: 10px;
        padding: 5px;
        color: {C.TEXT};
        alternate-background-color: {C.CARD_BG};
        gridline-color: {C.DIVIDER};
        outline: 0;
    }}
    QListWidget::item {{
        padding: 9px 11px;
        border-radius: {Radius.SM}px;
        min-height: 20px;
    }}
    QListWidget::item:hover {{ background: {C.CARD_HIGHLIGHT}; }}
    QListWidget::item:selected {{
        background: {acc_dim};
        color: {C.TEXT};
    }}
    QHeaderView::section {{
        background: {C.CARD_BG};
        color: {C.TEXT_DIM};
        border: none;
        border-bottom: 1px solid {C.BORDER};
        padding: 11px 12px;
        font-weight: 600;
        font-size: 11px;
        letter-spacing: 0.8px;
        text-transform: uppercase;
    }}
    QTableWidget {{ gridline-color: {C.DIVIDER}; }}
    QTableWidget::item {{
        padding: 9px;
    }}
    QTableWidget::item:selected {{
        background: {acc_dim};
        color: {C.TEXT};
    }}
    QTableCornerButton::section {{ border: none; background: {C.CARD_BG}; }}

    /* ---------- Status Chips — subtle pulse-ready ---------- */
    .StatusChip {{
        background: {acc_dim};
        color: {accent};
        border: 1px solid {acc_border_a};
        border-radius: {Radius.PILL}px;
        padding: 4px 12px 4px 20px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.3px;
    }}
    .StatusChip[state="online"]    {{ background: {rgba_str(C.STATUS_SUCCESS, 0.10)};  color: {C.STATUS_SUCCESS};    border-color: {rgba_str(C.STATUS_SUCCESS, 0.24)}; }}
    .StatusChip[state="connected"] {{ background: {rgba_str(C.STATUS_CONNECTED, 0.10)};  color: {C.STATUS_CONNECTED};    border-color: {rgba_str(C.STATUS_CONNECTED, 0.24)}; }}
    .StatusChip[state="idle"]      {{ background: {rgba_str(C.STATUS_ACTIVE, 0.10)}; color: {C.STATUS_ACTIVE}; border-color: {rgba_str(C.STATUS_ACTIVE, 0.20)}; }}
    .StatusChip[state="listening"] {{ background: {rgba_str(C.STATUS_ACTIVE, 0.14)}; color: {C.STATUS_ACTIVE}; border-color: {rgba_str(C.STATUS_ACTIVE, 0.32)}; }}
    .StatusChip[state="active"]    {{ background: {rgba_str(C.STATUS_ACTIVE, 0.10)}; color: {C.STATUS_ACTIVE}; border-color: {rgba_str(C.STATUS_ACTIVE, 0.22)}; }}
    .StatusChip[state="thinking"]  {{ background: {C.ACC_VIOLET_DIM};      color: {C.ACC_VIOLET}; border-color: {rgba_str(C.ACC_VIOLET, 0.26)}; }}
    .StatusChip[state="speaking"]  {{ background: {rgba_str(C.STATUS_SUCCESS, 0.12)};  color: {C.STATUS_SUCCESS};    border-color: {rgba_str(C.STATUS_SUCCESS, 0.28)}; }}
    .StatusChip[state="executing"] {{ background: {rgba_str(C.STATUS_WARNING, 0.12)}; color: {C.STATUS_WARNING};   border-color: {rgba_str(C.STATUS_WARNING, 0.28)}; }}
    .StatusChip[state="warning"]   {{ background: {rgba_str(C.STATUS_WARNING, 0.12)}; color: {C.STATUS_WARNING};   border-color: {rgba_str(C.STATUS_WARNING, 0.28)}; }}
    .StatusChip[state="pending"]   {{ background: {rgba_str(C.STATUS_PENDING, 0.12)}; color: {C.STATUS_PENDING};   border-color: {rgba_str(C.STATUS_PENDING, 0.28)}; }}
    .StatusChip[state="info"]      {{ background: {rgba_str(C.STATUS_INFO, 0.12)}; color: {C.STATUS_INFO};         border-color: {rgba_str(C.STATUS_INFO, 0.28)}; }}
    .StatusChip[state="error"]     {{ background: {rgba_str(C.STATUS_ERROR, 0.12)};    color: {C.STATUS_ERROR};      border-color: {rgba_str(C.STATUS_ERROR, 0.28)}; }}
    .StatusChip[state="offline"]   {{ background: {rgba_str(C.STATUS_OFFLINE, 0.08)}; color: {C.STATUS_OFFLINE}; border-color: {rgba_str(C.STATUS_OFFLINE, 0.22)}; }}
    .StatusChip[state="disabled"]  {{ background: {rgba_str(C.STATUS_DISABLED, 0.08)}; color: {C.STATUS_DISABLED}; border-color: {rgba_str(C.STATUS_DISABLED, 0.20)}; }}

    /* ---------- Tabs — refined underline ---------- */
    QTabWidget::pane {{
        border: 1px solid {C.BORDER};
        border-radius: {Radius.MD2}px;
        top: -1px;
        background: {C.CARD_BG};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {C.TEXT_MED};
        padding: 11px 20px;
        border: none;
        border-bottom: 2px solid transparent;
        font-weight: 500;
    }}
    QTabBar::tab:hover {{ color: {C.TEXT}; }}
    QTabBar::tab:selected {{
        color: {accent};
        border-bottom-color: {accent};
    }}

    /* ---------- Menus — glass with padding ---------- */
    QMenu {{
        background: {C.CARD_BG};
        color: {C.TEXT};
        border: 1px solid {C.BORDER_MED};
        border-radius: 10px;
        padding: 7px;
    }}
    QMenu::item {{
        padding: 8px 20px 8px 11px;
        border-radius: {Radius.SM}px;
    }}
    QMenu::item:selected {{
        background: {acc_dim};
        color: {accent};
    }}
    QMenu::separator {{
        height: 1px;
        background: {C.DIVIDER};
        margin: 5px 7px;
    }}

    /* ---------- Splitters ---------- */
    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:horizontal {{ width: 2px; }}
    QSplitter::handle:vertical   {{ height: 2px; }}
    QSplitter::handle:hover {{ background: {acc_border_a}; }}

    /* ---------- Dialogs — elevated glass ---------- */
    QDialog {{
        background: {C.GLASS_STRONG};
        border: 1px solid {C.BORDER_HARD};
        border-radius: 14px;
    }}
    QDialog QLabel {{ background: transparent; }}
    QDialogButtonBox QPushButton {{ min-width: 92px; }}

    /* ---------- Status strip / page header helpers ---------- */
    #PageTitle {{
        font-size: 23px;
        font-weight: 700;
        letter-spacing: -0.5px;
        color: {C.TEXT};
    }}
    #PageSubtitle {{
        font-size: 12px;
        color: {C.TEXT_DIM};
    }}

    /* Subtle hairline separator */
    .Hairline {{
        background: transparent;
        border-top: 1px solid {C.DIVIDER};
        min-height: 1px; max-height: 1px;
    }}
    """


# ─────────────────────────────────────────────────────────────────────
#  HELPER WIDGET CLASSES
# ─────────────────────────────────────────────────────────────────────

class HLine(QFrame):
    """Thin horizontal divider with consistent 7% tint."""
    def __init__(self, color=None, thickness: int = 1, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        col = color or C.DIVIDER
        self.setStyleSheet(
            f"background: transparent; border: none; "
            f"border-top: {thickness}px solid {col};"
        )
        self.setFixedHeight(thickness)


class VLine(QFrame):
    def __init__(self, color=None, thickness: int = 1, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.VLine)
        col = color or C.DIVIDER
        self.setStyleSheet(
            f"background: transparent; border: none; "
            f"border-left: {thickness}px solid {col};"
        )
        self.setFixedWidth(thickness)


class Card(QFrame):
    """Glass card with consistent layout, 4-part structure:

    [title dot] Title .......... [optional right widget]
    ─────────────────────── hairline ─────────────────────
                     self.body (add widgets here)

    Flat by default; use set_highlight(True) / set_accents(accent_color)
    to differentiate important cards.
    """

    def __init__(self, parent=None, title: Optional[str] = None,
                 accent: str = C.ACCENT_CYAN, with_padding: bool = True,
                 density: Optional[Dict] = None):
        super().__init__(parent)
        self.setProperty("class", "CardPanel")
        self._acc = accent
        self._density = density or Density.COZY

        pad = self._density["pad"] if with_padding else 0
        gap = self._density["gap"]

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(pad, pad, pad, pad)
        self._root.setSpacing(Spacing.MD)

        if title:
            hdr = QHBoxLayout()
            hdr.setSpacing(Spacing.SM)

            # Title dot — accent square-rounded 6x6
            dot = QLabel()
            dot.setFixedSize(6, 6)
            pm = QPixmap(6, 6)
            pm.fill(QColor(0, 0, 0, 0))
            pp = QPainter(pm)
            pp.setRenderHint(QPainter.RenderHint.Antialiasing)
            pp.setPen(Qt.PenStyle.NoPen)
            r, g, b = hex_to_rgb(accent)
            pp.setBrush(QColor(r, g, b, 220))
            pp.drawRoundedRect(0, 0, 6, 6, 2, 2)
            pp.end()
            dot.setPixmap(pm)

            hdr.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
            lbl = QLabel(title)
            lbl.setProperty("class", "Subtitle")
            lbl.setStyleSheet(
                f"font-size: 13px; font-weight: 600; color: {C.TEXT}; background: transparent; background-color: transparent;"
            )
            hdr.addWidget(lbl, 1, Qt.AlignmentFlag.AlignVCenter)
            self._header_right = QHBoxLayout()
            self._header_right.setSpacing(Spacing.SM)
            self._header_right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            hdr.addLayout(self._header_right)

            self._root.addLayout(hdr)
            self._root.addWidget(HLine(C.DIVIDER, 1))

        self.body = QVBoxLayout()
        self.body.setSpacing(gap)
        self.body.setContentsMargins(0, 0, 0, 0)
        self._root.addLayout(self.body)

    # -- header right area helpers --------------------------------------------------
    def add_header_widget(self, w: QWidget):
        self._header_right.addWidget(w)

    def set_highlight(self, on: bool = True):
        self.setProperty("accented", "true" if on else "false")
        self.style().unpolish(self); self.style().polish(self)

    def set_accent(self, color_hex: str):
        self._acc = color_hex
        self.set_highlight(True)

    def add(self, w: QWidget):
        self.body.addWidget(w)


class StatusChip(QLabel):
    """Small colored pill with built-in state map and dynamic repolish.

    Supports: online/idle/listening/thinking/speaking/executing/error/offline.
    """
    _STATE_MAP = {
        "online": "online", "ok": "online", "connected": "connected",
        "idle": "idle", "ready": "idle", "active": "active",
        "listening": "listening", "hearing": "listening",
        "thinking": "thinking", "thought": "thinking",
        "speaking": "speaking", "talking": "speaking",
        "executing": "executing", "working": "executing", "processing": "executing",
        "warning": "warning", "pending": "pending", "waiting": "pending",
        "info": "info",
        "error": "error", "failed": "error",
        "offline": "offline", "paused": "offline",
        "disabled": "disabled",
    }

    def __init__(self, text: str = "", state: str = "offline", parent=None,
                 show_led: bool = True):
        super().__init__(text if not show_led else "", parent)
        self._show_led = show_led
        self._led_anim = 0.0
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setProperty("class", "StatusChip")
        self.setText(text)
        self._state_val = "offline"
        self.set_state(state)

        # Gentle LED pulse timer
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(80)

    def set_state(self, state: str):
        s = self._STATE_MAP.get((state or "").lower(), "offline")
        self._state_val = s
        self.setProperty("state", s)
        self.style().unpolish(self); self.style().polish(self)

    def state(self) -> str:
        return self._state_val

    def _tick(self):
        self._led_anim = (self._led_anim + 0.13) % (2 * math.pi)
        if self._show_led:
            self.update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not self._show_led:
            return
        # Draw a tiny pulsing LED dot on the left of the text.
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        state_colors = {
            "online": C.STATUS_SUCCESS, "connected": C.STATUS_CONNECTED,
            "idle": C.STATUS_ACTIVE, "active": C.STATUS_ACTIVE,
            "listening": C.STATUS_ACTIVE, "thinking": C.ACC_VIOLET,
            "speaking": C.STATUS_SUCCESS, "executing": C.STATUS_WARNING,
            "warning": C.STATUS_WARNING, "pending": C.STATUS_PENDING,
            "info": C.STATUS_INFO,
            "error": C.STATUS_ERROR, "offline": C.STATUS_OFFLINE,
            "disabled": C.STATUS_DISABLED,
        }
        accent = state_colors.get(self._state_val, C.STATUS_OFFLINE)
        r, g, b = hex_to_rgb(accent)
        pulse = 0.5 + 0.5 * math.sin(self._led_anim) if self._state_val in (
            "listening", "thinking", "speaking", "executing") else 0.0
        # Soft halo
        x, y = 10, int(self.height() / 2)
        gr = QRadialGradient(x, y, 11)
        gr.setColorAt(0.0, QColor(r, g, b, int(80 + 120 * pulse)))
        gr.setColorAt(1.0, QColor(r, g, b, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(gr))
        p.drawEllipse(QPointF(x, y), 10, 10)
        # Core dot
        p.setBrush(QColor(r, g, b, 240))
        p.drawEllipse(QPointF(x, y), 4, 4)
        p.end()


class SectionHeader(QWidget):
    """Page section title + subtitle + optional right-side action area with semantic accent marker."""

    def __init__(self, title: str, subtitle: Optional[str] = None,
                 accent: Optional[str] = None, parent=None):
        if isinstance(accent, QWidget):
            parent = accent
            accent = None
        super().__init__(parent)
        self._accent = accent or C.ACCENT_CYAN
        self._root = QHBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(Spacing.MD)

        # Subtle vertical accent marker bar (3px wide, 20px high)
        self._marker = QLabel()
        self._marker.setFixedSize(3, 20)
        self._update_marker()
        self._root.addWidget(self._marker, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(Spacing.XS)
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("PageTitle")
        text_col.addWidget(self.title_lbl)
        self.sub_lbl = None
        if subtitle:
            self.sub_lbl = QLabel(subtitle)
            self.sub_lbl.setObjectName("PageSubtitle")
            text_col.addWidget(self.sub_lbl)
        self._root.addLayout(text_col, 1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(Spacing.SM)
        self.actions.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._root.addLayout(self.actions, 0)

    def _update_marker(self):
        r, g, b = hex_to_rgb(self._accent)
        self._marker.setStyleSheet(
            f"background: rgba({r},{g},{b},0.90); border-radius: 1.5px;"
        )

    def set_accent(self, accent: str):
        self._accent = accent
        self._update_marker()

    def add_action(self, widget: QWidget):
        self.actions.addWidget(widget)

    def set_title(self, text: str): self.title_lbl.setText(text)

    def set_subtitle(self, text: str):
        if self.sub_lbl is None:
            self.sub_lbl = QLabel("")
            self.sub_lbl.setObjectName("PageSubtitle")
            self._root.itemAt(1).layout().addWidget(self.sub_lbl)
        self.sub_lbl.setText(text)


class LoadingState(QWidget):
    """Indeterminate loading placeholder.

    Cinematic 4-dot orbital with halo. Dots trace a subtle elliptical path.
    """

    def __init__(self, text: str = "Loading…", subtitle: str = "", parent=None):
        super().__init__(parent)
        self._text = text
        self._subtitle = subtitle
        self._t = 0.0
        self.setMinimumHeight(160)
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.setContentsMargins(Spacing.XL, Spacing.LG2, Spacing.XL, Spacing.LG)
        root.setSpacing(Spacing.SM)
        root.addStretch(2)
        root.addSpacing(70)
        self._label = QLabel(text)
        self._label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {C.TEXT};")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._label)
        if subtitle:
            self._sublabel = QLabel(subtitle)
            self._sublabel.setStyleSheet(f"font-size: 12px; color: {C.TEXT_DIM};")
            self._sublabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._sublabel.setWordWrap(True)
            root.addWidget(self._sublabel)
        root.addStretch(3)
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._tick)
        self._tmr.start(55)

    def _tick(self):
        self._t += 0.085
        self.update()

    def paintEvent(self, ev):
        QWidget.paintEvent(self, ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w // 2, 70
        try:
            r, g, b = hex_to_rgb(C.ACCENT_CYAN)
        except Exception:
            r, g, b = 34, 211, 238
        # Soft ambient halo
        halo = QRadialGradient(cx, cy, 44)
        halo.setColorAt(0.0, QColor(r, g, b, 40))
        halo.setColorAt(1.0, QColor(r, g, b, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(cx, cy), 44, 44)
        # Four orbital dots
        n = 4
        rx, ry = 22, 14
        for i in range(n):
            ang = self._t * 2.2 + i * (2 * math.pi / n)
            x = cx + math.cos(ang) * rx
            y = cy + math.sin(ang) * ry
            depth = 0.5 + 0.5 * math.sin(ang)
            dot_r = 2.8 + depth * 1.8
            alpha = int(90 + 165 * depth)
            # dot halo
            dh = QRadialGradient(x, y, dot_r * 2.6)
            dh.setColorAt(0.0, QColor(r, g, b, int(alpha * 0.7)))
            dh.setColorAt(1.0, QColor(r, g, b, 0))
            p.setBrush(QBrush(dh))
            p.drawEllipse(QPointF(x, y), dot_r * 2.6, dot_r * 2.6)
            # solid core
            p.setBrush(QColor(r, g, b, min(255, alpha + 40)))
            p.drawEllipse(QPointF(x, y), dot_r, dot_r)
        p.end()

    def set_text(self, text: str):
        self._text = text
        self._label.setText(text)


class EmptyState(QWidget):
    """Clean, iconographic empty state.

    Components that list data should show this when the list is empty.
    An optional call-to-action Primary/Ghost button lets the user
    immediately begin adding content.
    """

    def __init__(self, icon_name: str = ICONS.INFO, title: str = "Nothing here yet",
                 subtitle: str = "", action_text: Optional[str] = None,
                 action_fn: Optional[Callable] = None, parent=None,
                 accent: str = C.TEXT_DIM, compact: bool = False):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if compact:
            root.setSpacing(Spacing.SM)
            root.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
            root.addStretch(1)

            tile = QWidget()
            tile.setFixedSize(46, 46)
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(0, 0, 0, 0)
            ic_lbl = QLabel()
            ic_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ic_lbl.setPixmap(icon_pixmap(icon_name, accent, 20))
            tl.addWidget(ic_lbl)
            tile.setStyleSheet(
                f"background: {rgba_str(accent, 0.06)}; border: 1px solid {rgba_str(accent, 0.20)};"
                f"border-radius: {Radius.MD}px;"
            )
            make_glow(tile, color=accent, blur=12, alpha=22)
            tile_lay = QHBoxLayout()
            tile_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile_lay.addWidget(tile)
            root.addLayout(tile_lay)

            t = QLabel(title)
            t.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {C.TEXT}; letter-spacing: -0.1px;")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(t)

            if subtitle:
                s = QLabel(subtitle)
                s.setStyleSheet(f"font-size: 11px; color: {C.TEXT_DIM}; line-height: 1.4;")
                s.setAlignment(Qt.AlignmentFlag.AlignCenter)
                s.setWordWrap(True)
                s.setMaximumWidth(320)
                root.addWidget(s)

            if action_text and action_fn:
                row = QHBoxLayout()
                row.addStretch(1)
                btn = QPushButton(action_text)
                btn.setObjectName("PrimaryBtn")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(action_fn)
                row.addWidget(btn)
                row.addStretch(1)
                root.addLayout(row)
            root.addStretch(1)
        else:
            root.setSpacing(Spacing.MD)
            root.setContentsMargins(Spacing.XL2, Spacing.LG2, Spacing.XL2, Spacing.LG2)
            root.addStretch(2)

            tile = QWidget()
            tile.setFixedSize(92, 92)
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(0, 0, 0, 0)
            ic_lbl = QLabel()
            ic_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ic_lbl.setPixmap(icon_pixmap(icon_name, accent, 36))
            tl.addWidget(ic_lbl)
            tile.setStyleSheet(
                f"background: {rgba_str(accent, 0.06)}; border: 1px solid {rgba_str(accent, 0.20)};"
                f"border-radius: {Radius.LG}px;"
            )
            make_glow(tile, color=accent, blur=18, alpha=28)
            tile_lay = QHBoxLayout()
            tile_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile_lay.addWidget(tile)
            root.addLayout(tile_lay)

            t = QLabel(title)
            t.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {C.TEXT}; letter-spacing: -0.1px;")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(t)

            if subtitle:
                s = QLabel(subtitle)
                s.setStyleSheet(f"font-size: 12px; color: {C.TEXT_DIM}; line-height: 1.5;")
                s.setAlignment(Qt.AlignmentFlag.AlignCenter)
                s.setWordWrap(True)
                s.setMaximumWidth(380)
                root.addWidget(s)

            if action_text and action_fn:
                row = QHBoxLayout()
                row.addStretch(1)
                btn = QPushButton(action_text)
                btn.setObjectName("PrimaryBtn")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(action_fn)
                row.addWidget(btn)
                row.addStretch(1)
                root.addLayout(row)
            root.addStretch(3)


class ErrorState(QWidget):
    """Error placeholder with title, detail, retry button.

    Semantic red accent used very sparingly; icon is amber/red triangle.
    """

    def __init__(self, title: str = "Something went wrong",
                 message: str = "", retry_fn: Optional[Callable] = None,
                 secondary_text: str = "", secondary_fn: Optional[Callable] = None,
                 parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.setSpacing(Spacing.MD)
        root.setContentsMargins(Spacing.XL2, Spacing.LG2, Spacing.XL2, Spacing.LG2)
        root.addStretch(2)

        tile = QWidget()
        tile.setFixedSize(92, 92)
        tl = QVBoxLayout(tile)
        tl.setContentsMargins(0, 0, 0, 0)
        ic = QLabel()
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setPixmap(icon_pixmap(ICONS.WARNING, C.RED, 36))
        tl.addWidget(ic)
        tile.setStyleSheet(
            f"background: {rgba_str(C.RED, 0.05)};"
            f"border: 1px solid {rgba_str(C.RED, 0.16)};"
            f"border-radius: {Radius.LG}px;"
        )
        make_glow(tile, color=C.RED, blur=22, alpha=36)
        hl = QHBoxLayout()
        hl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(tile)
        root.addLayout(hl)

        t = QLabel(title)
        t.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {C.TEXT}; letter-spacing: -0.1px;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(t)

        if message:
            s = QLabel(message)
            s.setStyleSheet(f"font-size: 12px; color: {C.TEXT_DIM}; line-height: 1.55;")
            s.setAlignment(Qt.AlignmentFlag.AlignCenter)
            s.setWordWrap(True)
            s.setMaximumWidth(420)
            root.addWidget(s)

        if retry_fn or secondary_fn:
            row = QHBoxLayout()
            row.setSpacing(Spacing.SM)
            row.addStretch(1)
            if secondary_text and secondary_fn:
                btn2 = QPushButton(secondary_text)
                btn2.setObjectName("GhostBtn")
                btn2.setCursor(Qt.CursorShape.PointingHandCursor)
                btn2.clicked.connect(secondary_fn)
                row.addWidget(btn2)
            if retry_fn:
                btn = QPushButton("Retry")
                btn.setObjectName("PrimaryBtn")
                btn.setIcon(icon(ICONS.REFRESH, get_contrast_color(C.ACCENT_CYAN), 14))
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(retry_fn)
                row.addWidget(btn)
            row.addStretch(1)
            root.addLayout(row)
        root.addStretch(3)


# ─────────────────────────────────────────────────────────────────────
#  DIALOG BASE (glass + elevation)
# ─────────────────────────────────────────────────────────────────────

class GlassDialog(QDialog):
    """Base cinematic dialog used by all popups.

    Consistent padding, close button, elevated shadow, optional header
    accent line. All page dialogs inherit from this for visual unity.
    """

    def __init__(self, parent=None, title: str = "", accent: str = C.ACCENT_CYAN,
                 min_width: int = 500, min_height: int = 260):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMinimumSize(min_width, min_height)
        self._acc = accent

        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.XL)
        outer.setSpacing(0)

        frame = QFrame()
        frame.setProperty("class", "CardPanel")
        acc_r, acc_g, acc_b = hex_to_rgb(accent)
        frame.setStyleSheet(
            f".CardPanel {{ background: {C.GLASS_STRONG};"
            f"border: 1px solid rgba(148, 184, 204, 0.20);"
            f"border-top: 1px solid rgba({acc_r}, {acc_g}, {acc_b}, 0.14);"
            f"border-radius: {Radius.LG}px; }}"
        )
        make_elevation(frame, y_off=Elevation.DIALOG[0], blur=Elevation.DIALOG[1],
                       alpha=Elevation.DIALOG[3])

        self._root = QVBoxLayout(frame)
        self._root.setContentsMargins(Spacing.LG2, Spacing.LG2, Spacing.LG2, Spacing.LG2)
        self._root.setSpacing(Spacing.MD + 2)

        if title:
            hh = QHBoxLayout()
            hh.setSpacing(Spacing.SM)
            # Accent dot
            dot = QLabel()
            dot.setFixedSize(6, 6)
            pm = QPixmap(6, 6)
            pm.fill(QColor(0, 0, 0, 0))
            pp = QPainter(pm)
            pp.setRenderHint(QPainter.RenderHint.Antialiasing)
            pp.setPen(Qt.PenStyle.NoPen)
            pp.setBrush(QColor(acc_r, acc_g, acc_b, 220))
            pp.drawRoundedRect(0, 0, 6, 6, 2, 2)
            pp.end()
            dot.setPixmap(pm)
            hh.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
            ttl = QLabel(title)
            ttl.setStyleSheet(
                f"font-size: 15px; font-weight: 600; color: {C.TEXT}; letter-spacing: -0.1px;"
            )
            hh.addWidget(ttl, 1, Qt.AlignmentFlag.AlignVCenter)
            cl = QPushButton()
            cl.setIcon(icon(ICONS.CLOSE, C.TEXT_DIM, 14))
            cl.setFixedSize(30, 30)
            cl.setObjectName("IconBtn")
            cl.setCursor(Qt.CursorShape.PointingHandCursor)
            cl.clicked.connect(self.reject)
            hh.addWidget(cl)
            self._root.addLayout(hh)
            self._root.addWidget(HLine(C.DIVIDER, 1))

        self.body = QVBoxLayout()
        self.body.setSpacing(Spacing.MD)
        self._root.addLayout(self.body, 1)

        self._btn_row = QDialogButtonBox()
        self._btn_row.setCenterButtons(False)
        self._root.addWidget(self._btn_row)

        outer.addWidget(frame)

    # -- API helpers -----------------------------------------------------------
    _ROLE_ALIAS = {
        "accept": QDialogButtonBox.ButtonRole.AcceptRole,
        "ok": QDialogButtonBox.ButtonRole.AcceptRole,
        "yes": QDialogButtonBox.ButtonRole.YesRole,
        "apply": QDialogButtonBox.ButtonRole.ApplyRole,
        "reject": QDialogButtonBox.ButtonRole.RejectRole,
        "cancel": QDialogButtonBox.ButtonRole.RejectRole,
        "no": QDialogButtonBox.ButtonRole.NoRole,
        "destructive": QDialogButtonBox.ButtonRole.DestructiveRole,
        "reset": QDialogButtonBox.ButtonRole.ResetRole,
        "help": QDialogButtonBox.ButtonRole.HelpRole,
        "action": QDialogButtonBox.ButtonRole.ActionRole,
    }

    def add_button(self, label: str, role=None, primary: bool = False) -> QPushButton:
        if role is None:
            role = QDialogButtonBox.ButtonRole.AcceptRole if primary else QDialogButtonBox.ButtonRole.RejectRole
        if isinstance(role, str):
            role = self._ROLE_ALIAS.get(role.lower(), QDialogButtonBox.ButtonRole.ActionRole)
        btn = QPushButton(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            btn.setObjectName("PrimaryBtn")
        else:
            btn.setObjectName("GhostBtn")
        self._btn_row.addButton(btn, role)
        return btn

    def set_accept_enabled(self, enabled: bool):
        for b in self._btn_row.buttons():
            if self._btn_row.buttonRole(b) in (
                QDialogButtonBox.ButtonRole.AcceptRole,
                QDialogButtonBox.ButtonRole.YesRole,
                QDialogButtonBox.ButtonRole.ApplyRole,
            ):
                b.setEnabled(enabled)

    def accept_if_valid(self) -> bool:
        """Override in subclass; enables OK button dynamically."""
        return True
