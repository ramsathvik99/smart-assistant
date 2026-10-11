"""
Theme adapter for the 3D Ambient System.
Manages smooth color interpolation between page accent identities and assistant states.
"""
from __future__ import annotations
import math
from typing import Tuple
from PyQt6.QtGui import QColor


def hex_to_rgb(hex_code: str) -> Tuple[float, float, float]:
    hex_code = (hex_code or "#00d4ff").lstrip("#")
    if len(hex_code) == 3:
        hex_code = "".join([c * 2 for c in hex_code])
    if len(hex_code) != 6:
        return (0.0, 212.0 / 255.0, 1.0)
    r = int(hex_code[0:2], 16) / 255.0
    g = int(hex_code[2:4], 16) / 255.0
    b = int(hex_code[4:6], 16) / 255.0
    return (r, g, b)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_rgb(c1: Tuple[float, float, float], c2: Tuple[float, float, float], t: float) -> Tuple[float, float, float]:
    return (
        lerp(c1[0], c2[0], t),
        lerp(c1[1], c2[1], t),
        lerp(c1[2], c2[2], t),
    )


class ThemeAdapter:
    """Provides smoothly interpolated RGB/QColor values for 3D ambient rendering."""

    STATE_COLORS = {
        "idle": (0.0, 0.83, 1.0),        # Cyan #00D4FF
        "listening": (0.1, 0.65, 1.0),   # Electric Blue #1AA6FF
        "thinking": (0.66, 0.33, 0.97),  # Arcane Violet #A855F7
        "speaking": (0.0, 0.90, 0.42),   # Neural Emerald #00E56B
        "executing": (1.0, 0.55, 0.0),   # Amber/Orange #FF8C00
        "working": (1.0, 0.55, 0.0),
        "processing": (1.0, 0.55, 0.0),
        "success": (0.0, 1.0, 0.6),     # Neon Mint
        "warning": (1.0, 0.75, 0.0),     # Warning Gold #FFBF00
        "error": (1.0, 0.28, 0.34),      # Crimson Ruby #FF4757
        "failed": (1.0, 0.28, 0.34),
        "offline": (0.29, 0.44, 0.50),   # Slate Muted #4A7080
    }

    PAGE_COLORS = {
        "home": (0.0, 0.83, 1.0),           # Cyan #00D4FF
        "assistant": (0.0, 0.83, 1.0),      # Electric Blue
        "communications": (0.24, 0.51, 0.98), # Indigo
        "workspace": (0.05, 0.75, 0.75),    # Teal
        "schedule": (0.54, 0.36, 0.96),     # Violet
        "automation": (1.0, 0.58, 0.0),     # Amber
        "connected_world": (0.0, 0.80, 0.60), # Mint/Teal
        "intelligence": (0.68, 0.33, 0.95), # Purple
        "settings": (0.35, 0.55, 0.70),     # Slate Steel
    }

    def __init__(self, initial_hex: str = "#00d4ff"):
        self._current_rgb = hex_to_rgb(initial_hex)
        self._target_rgb = self._current_rgb
        self._secondary_rgb = (0.2, 0.4, 0.7)
        self._state_rgb = self._current_rgb
        self._state_influence = 0.0  # 0.0 = purely page/accent, 1.0 = purely state
        self._target_state_influence = 0.0
        self._accent_hex = initial_hex

    def set_accent_color(self, hex_code: str):
        self._accent_hex = hex_code
        self._target_rgb = hex_to_rgb(hex_code)

    def set_page_accent(self, page_id: str):
        pid = (page_id or "home").lower()
        if pid in self.PAGE_COLORS:
            self._target_rgb = self.PAGE_COLORS[pid]
        else:
            self._target_rgb = hex_to_rgb(self._accent_hex)

    def set_assistant_state(self, state: str):
        s = (state or "idle").lower()
        if s in self.STATE_COLORS:
            self._state_rgb = self.STATE_COLORS[s]
            # IDLE has low influence (accent dominates), active states have high influence
            if s == "idle":
                self._target_state_influence = 0.2
            elif s in ("error", "warning", "success"):
                self._target_state_influence = 0.85
            else:
                self._target_state_influence = 0.65
        else:
            self._target_state_influence = 0.0

    def update(self, dt: float):
        """Smoothly ease current colors towards targets."""
        factor = min(1.0, dt * 4.0)
        self._current_rgb = lerp_rgb(self._current_rgb, self._target_rgb, factor)
        self._state_influence = lerp(self._state_influence, self._target_state_influence, factor)

    @property
    def primary_rgb(self) -> Tuple[float, float, float]:
        """Blended primary color taking assistant state into account."""
        if self._state_influence <= 0.01:
            return self._current_rgb
        return lerp_rgb(self._current_rgb, self._state_rgb, self._state_influence)

    def get_color(self, alpha: int = 255, boost: float = 1.0) -> QColor:
        r, g, b = self.primary_rgb
        r = min(1.0, max(0.0, r * boost))
        g = min(1.0, max(0.0, g * boost))
        b = min(1.0, max(0.0, b * boost))
        return QColor(int(r * 255), int(g * 255), int(b * 255), max(0, min(255, alpha)))

    def get_secondary_color(self, alpha: int = 255) -> QColor:
        # Complementary / harmonic secondary tone
        r, g, b = self.primary_rgb
        # Shift hue slightly towards violet/cyan
        sr = min(1.0, max(0.0, r * 0.7 + 0.1))
        sg = min(1.0, max(0.0, g * 0.85 + 0.15))
        sb = min(1.0, max(0.0, b * 0.95 + 0.2))
        return QColor(int(sr * 255), int(sg * 255), int(sb * 255), max(0, min(255, alpha)))
