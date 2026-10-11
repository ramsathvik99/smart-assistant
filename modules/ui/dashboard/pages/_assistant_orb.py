"""
Assistant Orb Widget — Premium animated central visual presence.
Each state (IDLE / LISTENING / THINKING / SPEAKING / EXECUTING / ERROR / OFFLINE)
has a distinct visual signature. Responds to real assistant state.
"""

from __future__ import annotations
import math
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QLineF
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QRadialGradient, QLinearGradient,
    QPainterPath, QFont, QConicalGradient,
)
from PyQt6.QtWidgets import QWidget

from ..ds import C, hex_to_rgb


# Map state name to explicit RGB tuple. OFFLINE is gray-slate, not in base map.
_STATE_RGB: dict = {
    "idle": (0, 212, 255),
    "listening": (0, 170, 255),
    "thinking": (168, 85, 247),
    "speaking": (0, 229, 107),
    "executing": (255, 140, 0),
    "working": (255, 140, 0),
    "processing": (255, 140, 0),
    "error": (255, 71, 87),
    "failed": (255, 71, 87),
    "offline": (74, 112, 128),
    "paused": (74, 112, 128),
    "muted": (74, 112, 128),
    "disabled": (74, 112, 128),
}


def _state_rgb(state: str) -> tuple[int, int, int]:
    return _STATE_RGB.get((state or "idle").lower(), _STATE_RGB["idle"])


class AssistantOrbWidget(QWidget):
    """Large animated orb with state-specific visual signatures."""

    def __init__(self, size: int = 300, parent=None):
        super().__init__(parent)
        self._size = size
        self.setMinimumSize(size, size)
        self._state = "idle"
        self._audio_level: float = 0.0
        self._t = 0.0
        self._bars = 56
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

    # ---------------------------------------------------------------- API
    def _tick(self):
        self._t += 0.07
        self.update()

    def set_state(self, state: str):
        self._state = (state or "idle").lower()
        self.update()

    def set_audio_level(self, level: float):
        self._audio_level = max(0.0, min(1.0, float(level or 0.0)))

    def on_assistant_state(self, data: dict):
        self.set_state(data.get("state") or "idle")
        self.set_audio_level(float(data.get("audio_level") or 0.0))

    # ------------------------------------------------------------- painting
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w = float(self.width())
        h = float(self.height())
        cx, cy = w / 2.0, h / 2.0
        base_r = min(w, h) * 0.30
        state = self._state
        r, g, b = _state_rgb(state)

        # Flags
        is_active = state in ("listening", "thinking", "speaking",
                              "executing", "working", "processing")
        is_err = state in ("error", "failed")
        is_off = state in ("offline", "paused", "muted", "disabled")
        is_idle = state == "idle"
        is_listening = state == "listening"
        is_thinking = state in ("thinking",)
        is_speaking = state == "speaking"
        is_executing = state in ("executing", "working", "processing")

        t = self._t
        audio = self._audio_level

        # ── 1. Far field ambient glow ──────────────────────────────────────
        if not is_off:
            if is_err:
                far_pulse = 0.35 + 0.30 * abs(math.sin(t * 3.2))
            elif is_active:
                far_pulse = 0.28 + 0.22 * (0.5 + 0.5 * math.sin(t * 1.6))
            else:
                far_pulse = 0.12 + 0.08 * (0.5 + 0.5 * math.sin(t * 0.6))
            for layer, (mult, alpha_mul) in enumerate([(2.4, 0.08), (1.85, 0.16), (1.45, 0.22)]):
                rad = base_r * mult * (1.0 + 0.05 * far_pulse)
                gr = QRadialGradient(cx, cy, rad, cx, cy, rad * 0.45)
                gr.setColorAt(0.0, QColor(r, g, b, int(255 * alpha_mul * far_pulse)))
                gr.setColorAt(0.6, QColor(r, g, b, int(180 * alpha_mul * far_pulse * 0.4)))
                gr.setColorAt(1.0, QColor(r, g, b, 0))
                p.setBrush(QBrush(gr))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(cx, cy), rad, rad)

        # ── 2. Outermost decoration (state-specific) ──────────────────────
        if is_listening:
            # Concentric outward-traveling sound rings
            for i in range(3):
                phase = (t * 0.7 + i * 0.33) % 1.0
                rr = base_r * (1.20 + phase * 0.60)
                alpha = int(max(0, 255 * (1.0 - phase) * 0.28))
                pen = QPen(QColor(r, g, b, alpha), 1.4)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), rr, rr)
            # Audio waveform ring
            self._draw_audio_waveform(p, cx, cy, base_r, r, g, b, audio, t, n=72, rot=t * 0.10)

        elif is_speaking:
            # Propagating sound waves — elliptical "pressure" rings
            for i in range(4):
                phase = (t * 1.0 + i * 0.25) % 1.0
                rr_x = base_r * (1.18 + phase * 0.70)
                rr_y = rr_x * (0.82 + 0.18 * abs(math.sin(t * 2.4 + i)))
                alpha = int(max(0, 255 * (1.0 - phase) * 0.30))
                pen = QPen(QColor(r, g, b, alpha), 1.3)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), rr_x, rr_y)
            self._draw_audio_waveform(p, cx, cy, base_r, r, g, b,
                                      max(audio, 0.25), t, n=72, rot=-t * 0.18)

        elif is_thinking:
            # Double counter-rotating orbiting particles
            self._draw_orbit_ring(p, cx, cy, base_r * 1.30, r, g, b, t * 1.4, 8, 0)
            self._draw_orbit_ring(p, cx, cy, base_r * 1.55, r, g, b, -t * 1.0, 6, math.pi / 6)
            # Faint outer rotating hexagon
            p.save()
            p.translate(cx, cy)
            p.rotate(math.degrees(t * 0.35))
            pen = QPen(QColor(r, g, b, 55), 1.1)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            for i in range(6):
                ang = i * (2 * math.pi / 6)
                x = math.cos(ang) * base_r * 1.65
                y = math.sin(ang) * base_r * 1.65
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            path.closeSubpath()
            p.drawPath(path)
            p.restore()

        elif is_executing:
            # Pulsing scan line + expanding task rings
            for i in range(2):
                phase = (t * 1.2 + i * 0.5) % 1.0
                rr = base_r * (1.15 + phase * 0.75)
                alpha = int(max(0, 255 * (1.0 - phase) * 0.26))
                pen = QPen(QColor(r, g, b, alpha), 1.4)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                # Squircle-ish rounded diamond
                path = QPainterPath()
                for ang_i in range(0, 360, 4):
                    a = math.radians(ang_i)
                    rad = rr * (0.86 + 0.14 * abs(math.cos(a * 2 + t)))
                    x = cx + math.cos(a) * rad
                    y = cy + math.sin(a) * rad
                    if ang_i == 0:
                        path.moveTo(x, y)
                    else:
                        path.lineTo(x, y)
                path.closeSubpath()
                p.drawPath(path)
            # Horizontal scan line
            scan_y = cy + math.sin(t * 2.6) * base_r * 0.95
            scan_w = base_r * 1.85
            gr = QLinearGradient(cx - scan_w, scan_y, cx + scan_w, scan_y)
            gr.setColorAt(0.0, QColor(r, g, b, 0))
            gr.setColorAt(0.5, QColor(r, g, b, 110))
            gr.setColorAt(1.0, QColor(r, g, b, 0))
            pen = QPen(QBrush(gr), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QLineF(cx - scan_w, scan_y, cx + scan_w, scan_y))

        elif is_err:
            # Jagged "alert" ring — double heartbeat pulse
            beat = 0.5 + 0.5 * math.sin(t * 5.0)
            for i, rr_mul in enumerate([1.25, 1.55]):
                alpha = int(90 * (0.4 + 0.6 * beat) / (i + 1))
                pen = QPen(QColor(r, g, b, alpha), 1.5 + beat * 0.8)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                path = QPainterPath()
                for ang_i in range(0, 360, 6):
                    a = math.radians(ang_i)
                    jitter = 1.0 + 0.06 * math.sin(a * 10 + t * 4.0 + i)
                    x = cx + math.cos(a) * base_r * rr_mul * jitter * (1 + beat * 0.05)
                    y = cy + math.sin(a) * base_r * rr_mul * jitter * (1 + beat * 0.05)
                    if ang_i == 0:
                        path.moveTo(x, y)
                    else:
                        path.lineTo(x, y)
                path.closeSubpath()
                p.drawPath(path)

        elif is_off:
            # Offline: two concentric dim rings with diagonal cross-hatching
            for rr_mul, alpha in [(1.25, 35), (1.55, 18)]:
                pen = QPen(QColor(r, g, b, alpha), 1.1, Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), base_r * rr_mul, base_r * rr_mul)

        elif is_idle:
            # Idle: two ultra-subtle breathing rings
            breath = 0.5 + 0.5 * math.sin(t * 0.8)
            for i, (rr_mul, a_mul) in enumerate([(1.28, 0.10), (1.50, 0.05)]):
                alpha = int(255 * a_mul * (0.5 + 0.5 * breath))
                pen = QPen(QColor(r, g, b, alpha), 1.0)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy),
                              base_r * rr_mul * (1 + 0.03 * breath),
                              base_r * rr_mul * (1 + 0.03 * breath))

        # ── 3. Orbital conical arc ring (THINKING / EXECUTING) ─────────────
        if is_thinking:
            self._draw_rotating_arc(p, cx, cy, base_r * 1.06, r, g, b, t * 60, 3.0, arc_deg=310)
            self._draw_rotating_arc(p, cx, cy, base_r * 0.90, g, b, r, -t * 95, 2.2, arc_deg=260)
        elif is_executing:
            self._draw_rotating_arc(p, cx, cy, base_r * 1.06, r, g, b, t * 160, 3.2, arc_deg=300)
        elif is_listening:
            self._draw_rotating_arc(p, cx, cy, base_r * 1.04, r, g, b, t * 25, 2.0, arc_deg=200)

        # ── 4. Inner orb sphere ────────────────────────────────────────────
        if is_off:
            # Offline: flat desaturated circle, no specular, no bright glow
            gr = QRadialGradient(cx - base_r * 0.15, cy - base_r * 0.15, base_r * 0.8, cx, cy, base_r)
            gr.setColorAt(0.0, QColor(110, 135, 150, 240))
            gr.setColorAt(0.55, QColor(70, 95, 108, 240))
            gr.setColorAt(1.0, QColor(42, 62, 74, 240))
            p.setBrush(QBrush(gr))
            p.setPen(QPen(QColor(95, 125, 140, 140), 1.3))
            p.drawEllipse(QPointF(cx, cy), base_r, base_r)
        else:
            breath = 0.5 + 0.5 * math.sin(t * (1.8 if is_active else 0.9))
            r2 = min(255, r + (25 if is_idle else 45 if not is_err else 20))
            g2 = min(255, g + (25 if is_idle else 45 if not is_err else 20))
            b2 = min(255, b + (25 if is_idle else 45 if not is_err else 20))
            gr = QRadialGradient(cx - base_r * 0.33, cy - base_r * 0.36, base_r * 1.15, cx, cy, base_r)
            gr.setColorAt(0.0, QColor(r2, g2, b2, 255))
            gr.setColorAt(0.32, QColor(r, g, b, 240))
            gr.setColorAt(0.70, QColor(max(0, r - 55), max(0, g - 55), max(0, b - 55), 240))
            gr.setColorAt(1.0, QColor(max(0, r - 115), max(0, g - 115), max(0, b - 115), 235))
            p.setBrush(QBrush(gr))
            rim_alpha = 150 + int(50 * (0.5 + 0.5 * breath)) if is_active else 130
            if is_err:
                rim_alpha = 140 + int(80 * (0.5 + 0.5 * math.sin(t * 5.0)))
            p.setPen(QPen(QColor(r, g, b, rim_alpha), 1.3))
            p.drawEllipse(QPointF(cx, cy), base_r, base_r)

            # Specular highlight (stronger for active)
            hi_amp = 0.75 if is_active else 0.55
            if is_err:
                hi_amp = 0.50
            hl = QRadialGradient(cx - base_r * 0.38, cy - base_r * 0.42, base_r * 0.45)
            hl.setColorAt(0.0, QColor(255, 255, 255, int(120 * hi_amp)))
            hl.setColorAt(0.5, QColor(255, 255, 255, int(30 * hi_amp)))
            hl.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(hl))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx - base_r * 0.30, cy - base_r * 0.38),
                          base_r * 0.40, base_r * 0.30)

            # Faint inner "caustic" ring for premium feel
            pen = QPen(QColor(r, g, b, 30), 1.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx + base_r * 0.18, cy + base_r * 0.20),
                          base_r * 0.28, base_r * 0.16)

        # ── 5. Center state glyph ──────────────────────────────────────────
        p.save()
        glyph_text, is_icon_font = self._state_glyph()
        if glyph_text:
            f_size = int(base_r * 0.58)
            if is_off:
                f_size = int(base_r * 0.62)
            if is_icon_font:
                font = QFont("Segoe UI Symbol", f_size, QFont.Weight.Bold)
            else:
                font = QFont("Segoe UI", f_size, QFont.Weight.Bold)
            p.setFont(font)
            if is_off:
                text_color = QColor(220, 232, 240, 160)
            else:
                text_color = QColor(255, 255, 255, 235)
            p.setPen(QPen(text_color, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(cx - base_r, cy - base_r, base_r * 2, base_r * 2)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, glyph_text)
        p.restore()

        # ── 6. Crisp border rim ────────────────────────────────────────────
        if is_off:
            pen = QPen(QColor(120, 150, 165, 120), 1.1)
        else:
            rim_a = 180 if not is_active else 200
            if is_err:
                rim_a = 220
            pen = QPen(QColor(r, g, b, rim_a), 1.25)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), base_r * 1.02, base_r * 1.02)

        p.end()

    # ----------------------------------------------------------- helpers
    def _draw_audio_waveform(self, p, cx, cy, base_r, r, g, b, audio, t, n=64, rot=0.0):
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(rot))
        for i in range(n):
            ang = i * (2 * math.pi / n)
            phase = 0.5 + 0.5 * math.sin(t * 3.4 + i * 0.45)
            drive = max(audio, 0.08) * (0.65 + 0.35 * phase)
            bar_len = base_r * (0.10 + 0.60 * drive)
            if audio < 0.05:
                bar_len = base_r * 0.06 * (0.8 + 0.4 * phase)
            inner = base_r * 1.08
            outer = inner + bar_len
            x1 = math.cos(ang) * inner
            y1 = math.sin(ang) * inner
            x2 = math.cos(ang) * outer
            y2 = math.sin(ang) * outer
            alpha = int(255 * (0.30 + 0.70 * drive))
            pen = QPen(QColor(r, g, b, alpha), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        p.restore()

    def _draw_orbit_ring(self, p, cx, cy, radius, r, g, b, angle, n=6, phase_off=0.0):
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(angle))
        for i in range(n):
            ang = i * (2 * math.pi / n) + phase_off
            depth = 0.5 + 0.5 * math.sin(angle + i)
            x = math.cos(ang) * radius
            y = math.sin(ang) * radius
            dot_r = 2.6 + 2.4 * depth
            alpha = int(80 + 175 * depth)
            # Halo
            gr = QRadialGradient(x, y, dot_r * 3.0)
            gr.setColorAt(0.0, QColor(r, g, b, int(alpha * 0.6)))
            gr.setColorAt(1.0, QColor(r, g, b, 0))
            p.setBrush(QBrush(gr))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, y), dot_r * 3.0, dot_r * 3.0)
            # Core
            p.setBrush(QColor(r, g, b, min(255, alpha + 40)))
            p.drawEllipse(QPointF(x, y), dot_r, dot_r)
        p.restore()

    def _draw_rotating_arc(self, p, cx, cy, radius, r, g, b, rot_deg, width=2.5, arc_deg=300):
        p.save()
        p.translate(cx, cy)
        p.rotate(rot_deg)
        grd = QConicalGradient(0, 0, 0)
        grd.setColorAt(0.0, QColor(r, g, b, 255))
        grd.setColorAt(arc_deg / 360.0 * 0.85, QColor(r, g, b, 90))
        grd.setColorAt(arc_deg / 360.0, QColor(r, g, b, 12))
        grd.setColorAt(max(0.99, arc_deg / 360.0 + 0.001), QColor(r, g, b, 0))
        grd.setColorAt(1.0, QColor(r, g, b, 255))
        pen = QPen(QBrush(grd), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(-radius, -radius, radius * 2, radius * 2)
        start = int(-(360 - arc_deg) / 2.0)
        p.drawArc(rect, start * 16, int(arc_deg * 16))
        p.restore()

    def _state_glyph(self):
        """Return (text, use_icon_font) — icon glyphs drawn from Segoe UI Symbol."""
        return {
            "idle":       ("◉", True),
            "ready":      ("◉", True),
            "listening":  ("◉", True),
            "hearing":    ("◉", True),
            "thinking":   ("◌", True),
            "thought":    ("◌", True),
            "waiting":    ("◌", True),
            "pending":    ("◌", True),
            "speaking":   ("⟡", True),
            "talking":    ("⟡", True),
            "executing":  ("⚡", True),
            "working":    ("⚡", True),
            "processing": ("⚡", True),
            "error":      ("✕", True),
            "failed":     ("✕", True),
            "offline":    ("⊙", True),
            "paused":     ("⊙", True),
            "muted":      ("⊘", True),
            "disabled":   ("⊙", True),
        }.get(self._state, ("◉", True))
