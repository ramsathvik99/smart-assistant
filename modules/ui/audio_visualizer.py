"""
Smart Assistant — Audio Visualizer
Real-time audio energy visualizer driven by actual microphone data from legacy.sst.
Falls back to idle animation when no audio data is available.
"""

import math
import random

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QRect
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QLinearGradient,
    QRadialGradient, QPainterPath
)

from modules.ui.design_system import C


class AudioVisualizer(QWidget):
    """
    Radial energy bar visualizer.
    Set audio_level (0.0-1.0) from the AudioLevelProvider worker.
    If no real audio available, shows a subtle idle animation.
    """

    def __init__(self, parent=None, bars: int = 32, radius: int = 38):
        super().__init__(parent)
        self.setMinimumSize(120, 120)
        self._bars = bars
        self._radius = radius
        self._audio_level = 0.0
        self._state = "idle"

        # Per-bar state for smooth animation
        self._bar_heights = [0.0] * bars
        self._bar_targets  = [0.0] * bars
        self._idle_phase   = [i * (360.0 / bars) for i in range(bars)]

        # Timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)  # ~33 fps

        self._t = 0.0
        self._custom_rgb: tuple | None = None  # user-chosen accent override
        self.setStyleSheet("background: transparent;")

    def set_audio_level(self, level: float):
        self._audio_level = max(0.0, min(1.0, level))

    def set_state(self, state: str):
        self._state = state

    def set_custom_color(self, rgb: tuple):
        """
        Override the idle visualizer color with the user's chosen Dashboard accent.
        Pass an (R, G, B) integer tuple (0-255). Pass None to revert to state-driven colors.
        """
        self._custom_rgb = rgb if rgb and len(rgb) == 3 else None

    def _tick(self):
        self._t += 0.04
        # Use custom accent for idle state if set
        if self._custom_rgb and self._state == "idle":
            r, g, b = self._custom_rgb
        else:
            r, g, b = C.STATE_MAP.get(self._state, C.STATE_IDLE)

        if self._audio_level > 0.02:
            # Real audio mode: randomize bar targets based on energy
            for i in range(self._bars):
                noise = random.uniform(0.5, 1.5)
                self._bar_targets[i] = self._audio_level * noise * 0.85
        else:
            # Idle animation: gentle sine wave
            for i in range(self._bars):
                phase = self._idle_phase[i]
                val = (math.sin(self._t * 1.5 + math.radians(phase)) * 0.5 + 0.5) * 0.18
                self._bar_targets[i] = val

        # Smooth
        for i in range(self._bars):
            speed = 0.18 if self._bar_targets[i] > self._bar_heights[i] else 0.08
            self._bar_heights[i] += (self._bar_targets[i] - self._bar_heights[i]) * speed

        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        if self._custom_rgb and self._state == "idle":
            r, g, b = self._custom_rgb
        else:
            r, g, b = C.STATE_MAP.get(self._state, C.STATE_IDLE)

        inner_r = min(self._radius, min(w, h) / 2.0 - 20)
        bar_max  = min(w, h) / 2.0 - inner_r - 4

        for i in range(self._bars):
            angle_deg = i * (360.0 / self._bars) - 90
            angle_rad = math.radians(angle_deg)

            bar_h = max(3.0, self._bar_heights[i] * bar_max)
            x0 = cx + math.cos(angle_rad) * inner_r
            y0 = cy + math.sin(angle_rad) * inner_r
            x1 = cx + math.cos(angle_rad) * (inner_r + bar_h)
            y1 = cy + math.sin(angle_rad) * (inner_r + bar_h)

            energy = self._bar_heights[i]
            alpha  = int(80 + energy * 160)
            width  = max(1, int(1.5 + energy * 2.5))

            pen = QPen(QColor(r, g, b, alpha))
            pen.setWidth(width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(int(x0), int(y0), int(x1), int(y1))

        # Inner circle
        grad = QRadialGradient(cx, cy, inner_r)
        grad.setColorAt(0.0, QColor(r, g, b, 40))
        grad.setColorAt(1.0, QColor(r, g, b, 10))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QRect(int(cx - inner_r), int(cy - inner_r),
                            int(inner_r * 2), int(inner_r * 2)))

        # Inner ring
        pen = QPen(QColor(r, g, b, 60))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRect(int(cx - inner_r), int(cy - inner_r),
                            int(inner_r * 2), int(inner_r * 2)))

        p.end()
