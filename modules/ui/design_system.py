"""
Smart Assistant — Design System
Centralized design tokens, color palette, typography, animations.
This is the single source of truth for all UI styling.
"""

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtCore import QEasingCurve


# ─────────────────────────────────────────────────────────────────────────────
# COLOR PALETTE
# ─────────────────────────────────────────────────────────────────────────────
class C:
    """Centralized color tokens. All UI components must import from here."""

    # Core backgrounds
    BG       = "#040608"       # deepest background
    PANEL    = "#080d12"       # raised panel
    PANEL2   = "#0e141b"       # card/inner panel
    PANEL3   = "#141e28"       # hover / elevated panel
    GLASS    = "rgba(8, 13, 18, 220)"

    # Accent — electric cyan
    ACC      = "#00d4ff"
    ACCENT_CYAN = "#00d4ff"
    ACC_DIM  = "rgba(0, 212, 255, 0.15)"
    ACC_GHO  = "rgba(0, 212, 255, 0.06)"
    ACC2     = "#33dfff"       # lighter variant

    # Borders
    BORDER   = "rgba(0, 212, 255, 0.14)"
    BORDER_B = "rgba(0, 212, 255, 0.28)"
    BORDER_A = "rgba(0, 212, 255, 0.18)"

    # Text
    TEXT     = "#e8f4f8"
    TEXT_MED = "#9bbccc"
    TEXT_SECONDARY = "#9bbccc"
    TEXT_DIM = "#4a7080"
    TEXT_MUTED = "#4a7080"
    WHITE    = "#ffffff"

    # Semantic
    GREEN    = "#00e56b"
    GREEN_D  = "#00b854"
    RED      = "#ff4757"
    RED_D    = "#cc3344"
    ORANGE   = "#ff8c00"
    PURPLE   = "#a855f7"
    YELLOW   = "#ffd60a"

    # State colors (floating launcher + HUD)
    STATE_IDLE       = (0, 212, 255)      # cyan
    STATE_LISTENING  = (0, 170, 255)      # electric blue
    STATE_THINKING   = (168, 85, 247)     # violet
    STATE_SPEAKING   = (0, 229, 107)      # emerald
    STATE_EXECUTING  = (255, 140, 0)      # orange
    STATE_ERROR      = (255, 71, 87)      # crimson
    STATE_MUTED      = (74, 112, 128)     # muted gray

    STATE_MAP = {
        "idle":       STATE_IDLE,
        "listening":  STATE_LISTENING,
        "thinking":   STATE_THINKING,
        "speaking":   STATE_SPEAKING,
        "executing":  STATE_EXECUTING,
        "processing": STATE_EXECUTING,
        "working":    STATE_EXECUTING,
        "error":      STATE_ERROR,
        "muted":      STATE_MUTED,
    }

    # Bar background
    BAR_BG   = "#111820"
    DARK     = "#000000"


# ─────────────────────────────────────────────────────────────────────────────
# COLOR PRESETS & ACCENT UTILITIES
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_DASHBOARD_COLOR = "#00D4FF"
DEFAULT_FLOATING_COLOR  = "#00D4FF"

COLOR_PRESETS = [
    ("Cyan",   "#00D4FF"),
    ("Blue",   "#007AFF"),
    ("Purple", "#A855F7"),
    ("Violet", "#7C3AED"),
    ("Green",  "#00E56B"),
    ("Orange", "#FF8C00"),
    ("Red",    "#FF4757"),
    ("Pink",   "#EC4899"),
    ("Gold",   "#EAB308"),
]


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Converts a HEX string (e.g. #00d4ff or #fff) to an (R, G, B) integer tuple."""
    if not hex_str:
        return (0, 212, 255)
    h = str(hex_str).strip().lstrip("#")
    if len(h) == 3:
        h = "".join([c * 2 for c in h])
    if len(h) != 6:
        return (0, 212, 255)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return (0, 212, 255)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Converts (R, G, B) integers (0-255) to a clean #RRGGBB uppercase string."""
    return f"#{max(0, min(255, int(r))):02X}{max(0, min(255, int(g))):02X}{max(0, min(255, int(b))):02X}"


def rgba_str(hex_str: str, alpha: float) -> str:
    """Formats a HEX color into a CSS rgba(...) string with given alpha (0.0 to 1.0)."""
    r, g, b = hex_to_rgb(hex_str)
    return f"rgba({r}, {g}, {b}, {max(0.0, min(1.0, float(alpha))):.2f})"


def get_contrast_color(hex_str: str) -> str:
    """
    Computes WCAG relative luminance and returns optimal high-contrast text color:
    dark text (#040608) on bright backgrounds, or bright text (#FFFFFF) on dark backgrounds.
    """
    r, g, b = hex_to_rgb(hex_str)
    lum = 0.2126 * (r / 255.0) + 0.7152 * (g / 255.0) + 0.0722 * (b / 255.0)
    return "#040608" if lum > 0.55 else "#FFFFFF"


def ensure_visible_accent(hex_str: str, min_lum: float = 0.12) -> str:
    """
    Prevents arbitrary user-selected colors from being completely invisible against
    the assistant's dark obsidian glass background by guaranteeing a baseline luminance.
    """
    r, g, b = hex_to_rgb(hex_str)
    lum = 0.2126 * (r / 255.0) + 0.7152 * (g / 255.0) + 0.0722 * (b / 255.0)
    if lum < min_lum:
        boost = int((min_lum - lum) * 220)
        return rgb_to_hex(min(255, r + boost), min(255, g + boost), min(255, b + boost))
    return hex_str



# ─────────────────────────────────────────────────────────────────────────────
# TYPOGRAPHY
# ─────────────────────────────────────────────────────────────────────────────
class F:
    """Font definitions."""
    PRIMARY   = "Segoe UI"
    MONO      = "JetBrains Mono"
    FALLBACK  = "Consolas"

    @staticmethod
    def ui(size: int, bold: bool = False, weight: int | None = None) -> QFont:
        f = QFont(F.PRIMARY, size)
        if weight is not None:
            f.setWeight(weight)
        elif bold:
            f.setBold(True)
        return f

    @staticmethod
    def mono(size: int = 11) -> QFont:
        f = QFont(F.MONO, size)
        try:
            pass  # already best font
        except Exception:
            f = QFont(F.FALLBACK, size)
        return f


# ─────────────────────────────────────────────────────────────────────────────
# SPACING & RADIUS
# ─────────────────────────────────────────────────────────────────────────────
class Spacing:
    XS  = 4
    SM  = 8
    MD  = 12
    LG  = 16
    XL  = 24
    XXL = 40

class Radius:
    SM  = 6
    MD  = 10
    LG  = 16
    XL  = 24
    PILL = 999


# ─────────────────────────────────────────────────────────────────────────────
# STYLESHEET HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def btn_style(bg: str = C.ACC_DIM, fg: str = C.ACC,
              border: str = C.BORDER_B, radius: int = Radius.MD,
              hover_bg: str | None = None, hover_border: str | None = None) -> str:
    hover_bg = hover_bg or C.ACC_DIM.replace("0.15", "0.25")
    hover_border = hover_border or C.ACC
    return f"""
        QPushButton {{
            background: {bg};
            color: {fg};
            border: 1px solid {border};
            border-radius: {radius}px;
            padding: 7px 18px;
            font-family: '{F.PRIMARY}';
            font-size: 13px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background: {hover_bg};
            border: 1px solid {hover_border};
            color: {C.WHITE};
        }}
        QPushButton:pressed {{
            background: {C.ACC_GHO};
        }}
        QPushButton:disabled {{
            background: rgba(255,255,255,0.04);
            color: {C.TEXT_DIM};
            border: 1px solid rgba(255,255,255,0.06);
        }}
    """


def input_style(radius: int = Radius.MD) -> str:
    return f"""
        QLineEdit {{
            background: rgba(14, 20, 27, 180);
            color: {C.TEXT};
            border: 1px solid {C.BORDER};
            border-radius: {radius}px;
            padding: 8px 14px;
            font-family: '{F.PRIMARY}';
            font-size: 13px;
            selection-background-color: {C.ACC_DIM};
        }}
        QLineEdit:focus {{
            border: 1.5px solid {C.ACC};
            background: rgba(0, 212, 255, 0.04);
        }}
        QLineEdit::placeholder {{
            color: {C.TEXT_DIM};
        }}
    """


def panel_style(radius: int = Radius.LG, border: str = C.BORDER) -> str:
    return f"""
        QFrame {{
            background: {C.PANEL2};
            border: 1px solid {border};
            border-radius: {radius}px;
        }}
    """


def scrollbar_style(accent: str = C.ACC) -> str:
    return f"""
        QScrollBar:vertical {{
            background: transparent;
            width: 6px;
            border: none;
            margin: 4px 0 4px 0;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(0, 212, 255, 0.35);
            border-radius: 3px;
            min-height: 20px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: rgba(0, 212, 255, 0.55);
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar:horizontal {{
            height: 0;
        }}
    """


# ─────────────────────────────────────────────────────────────────────────────
# APPLICATION STYLESHEET (applied globally)
# ─────────────────────────────────────────────────────────────────────────────
APP_STYLESHEET = f"""
    QWidget {{
        background-color: {C.BG};
        color: {C.TEXT};
        font-family: '{F.PRIMARY}';
        font-size: 13px;
    }}
    QToolTip {{
        background-color: {C.PANEL2};
        color: {C.TEXT};
        border: 1px solid {C.BORDER_B};
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 12px;
    }}
    QMenu {{
        background-color: {C.PANEL};
        color: {C.TEXT};
        border: 1px solid {C.BORDER_B};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 7px 20px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background-color: {C.ACC_DIM};
        color: {C.ACC};
    }}
    QMenu::separator {{
        height: 1px;
        background: {C.BORDER};
        margin: 4px 10px;
    }}
"""
