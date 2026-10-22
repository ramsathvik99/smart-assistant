"""
Assistant Orb Widget — Advanced 3D Interactive Holographic Command Center.
Features:
  • Multi-axis 3D tilted orbital rings with genuine depth partitioning (Z-buffer occlusion)
  • Dynamic pointer-responsive parallax camera (yaw/pitch tracking cursor movements)
  • 3D particle constellation field with proximity connection lines
  • Multi-layered holographic Friday core with dynamic specular tracking
  • Comprehensive real-time state responsiveness across all 7 assistant states:
    IDLE, LISTENING, THINKING, SPEAKING, EXECUTING, ERROR, OFFLINE
  • Motion accessibility and background pause optimizations
"""

from __future__ import annotations
import math
import random
from typing import Optional, List, Tuple

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QLineF
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QRadialGradient, QLinearGradient,
    QPainterPath, QFont, QConicalGradient,
)
from PyQt6.QtWidgets import QWidget

from ..ds import C, hex_to_rgb


# Canonical state RGB color signatures
_STATE_RGB: dict = {
    "idle": (0, 212, 255),          # Vibrant Cyan
    "listening": (0, 170, 255),     # Electric Azure
    "thinking": (168, 85, 247),     # Cyber Violet
    "speaking": (0, 229, 107),      # Neon Emerald
    "executing": (255, 140, 0),     # Amber Gold
    "working": (255, 140, 0),       # Amber Gold
    "processing": (255, 140, 0),    # Amber Gold
    "error": (255, 71, 87),         # Crimson Alert
    "failed": (255, 71, 87),        # Crimson Alert
    "offline": (74, 112, 128),      # Muted Slate
    "paused": (74, 112, 128),       # Muted Slate
    "muted": (74, 112, 128),        # Muted Slate
    "disabled": (74, 112, 128),     # Muted Slate
}


def _state_rgb(state: str) -> tuple[int, int, int]:
    return _STATE_RGB.get((state or "idle").lower(), _STATE_RGB["idle"])


class _Particle3D:
    """A floating point in 3D spherical space around the core."""
    def __init__(self, r: float, theta: float, phi: float, speed: float, size: float):
        self.r = r
        self.theta = theta
        self.phi = phi
        self.speed = speed
        self.size = size


class AssistantOrbWidget(QWidget):
    """
    Advanced 3D Holographic AI Command Center Widget.
    Renders a true multi-depth 3D orbital system with pointer-responsive parallax.
    """

    def __init__(self, size: int = 280, parent=None):
        super().__init__(parent)
        self._size = size
        self.setMinimumSize(size, size)
        self.setMouseTracking(True)

        self._state = "idle"
        self._audio_level: float = 0.0
        self._t: float = 0.0
        self._reduced_motion: bool = False

        # 3D Camera / Parallax angles (in radians)
        self._yaw: float = 0.0
        self._pitch: float = 0.0
        self._target_yaw: float = 0.0
        self._target_pitch: float = 0.0

        # Initialize 3D Constellation Particles
        rng = random.Random(42)
        self._particles: List[_Particle3D] = []
        for _ in range(24):
            self._particles.append(_Particle3D(
                r=1.25 + rng.uniform(0.0, 0.85),
                theta=rng.uniform(0.0, math.pi * 2),
                phi=rng.uniform(-0.8, 0.8),
                speed=rng.uniform(0.15, 0.55) * (1 if rng.random() > 0.5 else -1),
                size=rng.uniform(1.8, 3.2),
            ))

        # Main animation clock (~50 FPS)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(20)

    # ------------------------------------------------------------- Lifecycle & API
    def set_state(self, state: str):
        self._state = (state or "idle").lower()
        self.update()

    def set_audio_level(self, level: float):
        self._audio_level = max(0.0, min(1.0, float(level or 0.0)))

    def on_assistant_state(self, data: dict):
        self.set_state(data.get("state") or "idle")
        self.set_audio_level(float(data.get("audio_level") or 0.0))

    def set_mouse_parallax(self, dx: float, dy: float):
        """External pointer tracking (e.g. from parent dashboard page)."""
        self._target_yaw = max(-0.45, min(0.45, float(dx) * 0.35))
        self._target_pitch = max(-0.35, min(0.35, -float(dy) * 0.28))

    def mouseMoveEvent(self, ev):
        super().mouseMoveEvent(ev)
        w = float(self.width())
        h = float(self.height())
        pos = ev.position() if hasattr(ev, 'position') else ev.pos()
        dx = (pos.x() - w / 2.0) / (w / 2.0)
        dy = (pos.y() - h / 2.0) / (h / 2.0)
        self.set_mouse_parallax(dx, dy)

    def leaveEvent(self, ev):
        super().leaveEvent(ev)
        # Gently ease back to neutral when cursor leaves
        self._target_yaw = 0.0
        self._target_pitch = 0.0

    def hideEvent(self, ev):
        super().hideEvent(ev)
        if self._timer.isActive():
            self._timer.stop()

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._timer.isActive():
            self._timer.start(20)

    def _tick(self):
        if not self.isVisible():
            return
        speed_mult = 0.4 if self._reduced_motion else 1.0
        self._t += 0.05 * speed_mult

        # Smooth camera parallax interpolation (exponential damping)
        self._yaw += (self._target_yaw - self._yaw) * 0.08
        self._pitch += (self._target_pitch - self._pitch) * 0.08

        # Step particle positions
        for p in self._particles:
            p.theta = (p.theta + 0.02 * p.speed * speed_mult) % (math.pi * 2)

        self.update()

    # ------------------------------------------------------------- 3D Mathematics
    def _project_3d(self, x: float, y: float, z: float, cx: float, cy: float, fov: float = 460.0) -> Tuple[float, float, float, float]:
        """
        Rotates (x, y, z) by camera pitch & yaw and applies perspective projection.
        Returns: (proj_x, proj_y, rotated_z, scale)
        """
        # Yaw rotation (around Y axis)
        cos_y, sin_y = math.cos(self._yaw), math.sin(self._yaw)
        x1 = x * cos_y + z * sin_y
        z1 = -x * sin_y + z * cos_y

        # Pitch rotation (around X axis)
        cos_p, sin_p = math.cos(self._pitch), math.sin(self._pitch)
        y2 = y * cos_p - z1 * sin_p
        z2 = y * sin_p + z1 * cos_p

        # Perspective divide
        depth = fov + z2
        scale = fov / max(40.0, depth)
        px = cx + x1 * scale
        py = cy + y2 * scale
        return px, py, z2, scale

    def _get_orbital_point_3d(self, radius: float, angle: float, tilt_x: float, tilt_z: float) -> Tuple[float, float, float]:
        """Calculates 3D position of an orbital point on an inclined elliptical plane."""
        # Flat orbit on XZ plane
        ox = math.cos(angle) * radius
        oz = math.sin(angle) * radius
        oy = 0.0

        # Apply tilt X
        cx_t, sx_t = math.cos(tilt_x), math.sin(tilt_x)
        y1 = -oz * sx_t
        z1 = oz * cx_t

        # Apply tilt Z
        cz_t, sz_t = math.cos(tilt_z), math.sin(tilt_z)
        x2 = ox * cz_t - y1 * sz_t
        y2 = ox * sz_t + y1 * cz_t

        return x2, y2, z1

    # ------------------------------------------------------------- Painting Engine
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w = float(self.width())
        h = float(self.height())
        cx, cy = w / 2.0, h / 2.0
        base_r = min(w, h) * 0.26
        state = self._state
        r, g, b = _state_rgb(state)

        is_active = state in ("listening", "thinking", "speaking", "executing", "working", "processing")
        is_err = state in ("error", "failed")
        is_off = state in ("offline", "paused", "muted", "disabled")
        is_idle = state == "idle"
        is_listening = state == "listening"
        is_thinking = state == "thinking"
        is_speaking = state == "speaking"
        is_executing = state in ("executing", "working", "processing")

        t = self._t
        audio = self._audio_level

        # Ring definitions: (radius_mult, tilt_x, tilt_z, speed, segments, tick_interval)
        rings_def = [
            (1.22,  0.52,  0.22,  0.42, 64, 8),   # Inner Telemetry Ring
            (1.54, -0.42, -0.32, -0.28, 72, 6),   # Equatorial Magnetic Ring
            (1.88,  0.82,  0.62,  0.18, 80, 10),  # Polar Orbital Ring
            (2.20, -0.62,  0.35, -0.12, 88, 12),  # Deep Celestial Perimeter
        ]

        # ── 1. Ambient Background Spatial Grid & Corona Glow ───────────────
        if not is_off:
            pulse = 0.5 + 0.5 * math.sin(t * (2.8 if is_active else 1.2))
            glow_rad = base_r * 2.3 * (1.0 + 0.06 * pulse)
            gr = QRadialGradient(cx, cy, glow_rad)
            gr.setColorAt(0.0, QColor(r, g, b, int(45 * (0.8 + 0.2 * pulse))))
            gr.setColorAt(0.45, QColor(r, g, b, int(20 * (0.8 + 0.2 * pulse))))
            gr.setColorAt(1.0, QColor(r, g, b, 0))
            p.setBrush(QBrush(gr))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), glow_rad, glow_rad)

            # Subtle holographic perspective grid lines beneath
            grid_pen = QPen(QColor(r, g, b, 14), 1.0)
            p.setPen(grid_pen)
            for gx in range(-3, 4):
                px1, py1, _, _ = self._project_3d(gx * base_r * 0.6, base_r * 1.4, -base_r * 1.5, cx, cy)
                px2, py2, _, _ = self._project_3d(gx * base_r * 0.9, base_r * 1.4, base_r * 1.5, cx, cy)
                p.drawLine(QPointF(px1, py1), QPointF(px2, py2))

        # ── 2. Render Background Orbital Elements (Z < 0, Behind Core) ─────
        for rad_mult, tx, tz, spd, segs, tick_int in rings_def:
            self._draw_3d_orbital_ring(p, cx, cy, base_r * rad_mult, tx, tz, t * spd,
                                       r, g, b, segs, tick_int, draw_back=True)

        # Background constellation particles (Z < 0)
        self._draw_constellation_particles(p, cx, cy, base_r, r, g, b, draw_back=True)

        # ── 3. State-Specific Atmospheric Rings (Behind Core) ──────────────
        if is_listening:
            # Concentric 3D sound pressure ripples
            for i in range(3):
                phase = (t * 0.85 + i * 0.33) % 1.0
                rr = base_r * (1.15 + phase * 0.65)
                alpha = int(max(0, 220 * (1.0 - phase) * 0.35))
                pen = QPen(QColor(r, g, b, alpha), 1.5)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), rr, rr * 0.88)

        elif is_speaking:
            # Harmonic voice oscillation ripples
            for i in range(3):
                phase = (t * 1.1 + i * 0.33) % 1.0
                rr_x = base_r * (1.15 + phase * 0.70)
                rr_y = rr_x * (0.80 + 0.15 * math.sin(t * 3.0 + i))
                alpha = int(max(0, 240 * (1.0 - phase) * 0.32))
                pen = QPen(QColor(r, g, b, alpha), 1.5)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), rr_x, rr_y)

        # ── 4. Central Holographic Friday Core Sphere ──────────────────────
        self._draw_holographic_core(p, cx, cy, base_r, r, g, b, state, t, audio)

        # ── 5. Render Foreground Orbital Elements (Z >= 0, In Front of Core)
        for rad_mult, tx, tz, spd, segs, tick_int in rings_def:
            self._draw_3d_orbital_ring(p, cx, cy, base_r * rad_mult, tx, tz, t * spd,
                                       r, g, b, segs, tick_int, draw_back=False)

        # Foreground constellation particles (Z >= 0)
        self._draw_constellation_particles(p, cx, cy, base_r, r, g, b, draw_back=False)

        # ── 6. Foreground State Overlays & Scan Telemetry ──────────────────
        if is_listening:
            # Radial audio waveform equalizer nodes
            self._draw_3d_waveform(p, cx, cy, base_r, r, g, b, audio, t)
        elif is_thinking:
            # Dual counter-rotating quantum particle streams
            self._draw_quantum_stream(p, cx, cy, base_r * 1.12, r, g, b, t * 2.2, 8)
            self._draw_quantum_stream(p, cx, cy, base_r * 1.34, 0, 212, 255, -t * 1.8, 6)
        elif is_executing:
            # 3D Holographic scanning beam sweeping vertically across core
            scan_phase = math.sin(t * 3.2)
            scan_y = cy + scan_phase * base_r * 0.95
            scan_w = base_r * 1.35 * math.sqrt(max(0.1, 1.0 - scan_phase * scan_phase))
            gr = QLinearGradient(cx - scan_w, scan_y, cx + scan_w, scan_y)
            gr.setColorAt(0.0, QColor(r, g, b, 0))
            gr.setColorAt(0.5, QColor(255, 255, 255, 230))
            gr.setColorAt(1.0, QColor(r, g, b, 0))
            p.setPen(QPen(QBrush(gr), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx - scan_w, scan_y), QPointF(cx + scan_w, scan_y))

        p.end()

    # ------------------------------------------------------------- 3D Sub-Renderers
    def _draw_3d_orbital_ring(self, p: QPainter, cx: float, cy: float, radius: float,
                              tilt_x: float, tilt_z: float, angle_offset: float,
                              r: int, g: int, b: int, segments: int, tick_interval: int,
                              draw_back: bool):
        """Draws one partition (back or front) of a tilted 3D elliptical orbital ring."""
        step = (2 * math.pi) / segments

        # Draw segmented orbital arcs
        for i in range(segments):
            a1 = i * step + angle_offset
            a2 = (i + 1) * step + angle_offset

            x1_3d, y1_3d, z1_3d = self._get_orbital_point_3d(radius, a1, tilt_x, tilt_z)
            x2_3d, y2_3d, z2_3d = self._get_orbital_point_3d(radius, a2, tilt_x, tilt_z)

            # Check Z partition relative to core plane
            mid_z = (z1_3d + z2_3d) * 0.5
            is_back = mid_z < 0.0

            if is_back != draw_back:
                continue

            px1, py1, _, scale1 = self._project_3d(x1_3d, y1_3d, z1_3d, cx, cy)
            px2, py2, _, scale2 = self._project_3d(x2_3d, y2_3d, z2_3d, cx, cy)

            # Atmospheric depth fading
            depth_factor = 0.35 + 0.65 * max(0.0, min(1.0, (mid_z + radius) / (2.0 * radius)))
            alpha = int(120 * depth_factor) if draw_back else int(195 * depth_factor)
            width = max(0.8, 1.4 * depth_factor)

            pen = QPen(QColor(r, g, b, alpha), width)
            p.setPen(pen)
            p.drawLine(QPointF(px1, py1), QPointF(px2, py2))

            # Telemetry Tick Mark
            if tick_interval > 0 and i % tick_interval == 0:
                # Radial outward vector
                norm_x, norm_y = (x1_3d / radius) * 6.0, (y1_3d / radius) * 6.0
                tx_3d, ty_3d, tz_3d = x1_3d + norm_x, y1_3d + norm_y, z1_3d
                ptx, pty, _, _ = self._project_3d(tx_3d, ty_3d, tz_3d, cx, cy)

                tick_pen = QPen(QColor(r, g, b, int(alpha * 1.3)), max(1.0, 1.2 * depth_factor))
                p.setPen(tick_pen)
                p.drawLine(QPointF(px1, py1), QPointF(ptx, pty))

        # Satellite orbiter traveling along this ring
        sat_a = self._t * 0.8 + angle_offset * 1.5
        sx_3d, sy_3d, sz_3d = self._get_orbital_point_3d(radius, sat_a, tilt_x, tilt_z)
        if (sz_3d < 0.0) == draw_back:
            spx, spy, _, sat_scale = self._project_3d(sx_3d, sy_3d, sz_3d, cx, cy)
            depth_factor = 0.4 + 0.6 * max(0.0, min(1.0, (sz_3d + radius) / (2.0 * radius)))
            dot_r = max(2.0, 3.8 * sat_scale * depth_factor)

            # Node glow
            halo_r = dot_r * 2.8
            gr = QRadialGradient(spx, spy, halo_r)
            gr.setColorAt(0.0, QColor(r, g, b, int(220 * depth_factor)))
            gr.setColorAt(1.0, QColor(r, g, b, 0))
            p.setBrush(QBrush(gr))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(spx, spy), halo_r, halo_r)

            # Node core
            p.setBrush(QColor(255, 255, 255, int(240 * depth_factor)))
            p.drawEllipse(QPointF(spx, spy), dot_r * 0.6, dot_r * 0.6)

    def _draw_constellation_particles(self, p: QPainter, cx: float, cy: float, base_r: float,
                                      r: int, g: int, b: int, draw_back: bool):
        """Draws floating 3D particle nodes and proximity constellation lines."""
        projected: List[Tuple[float, float, float, float]] = []

        for part in self._particles:
            rad = base_r * part.r
            x = rad * math.cos(part.theta) * math.cos(part.phi)
            y = rad * math.sin(part.phi)
            z = rad * math.sin(part.theta) * math.cos(part.phi)

            px, py, pz, scale = self._project_3d(x, y, z, cx, cy)
            is_back = pz < 0.0

            if is_back == draw_back:
                projected.append((px, py, pz, part.size * scale))

                # Render particle dot
                depth = max(0.2, min(1.0, (pz + rad) / (2.0 * rad)))
                p.setBrush(QColor(r, g, b, int(180 * depth)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(px, py), part.size * scale * depth, part.size * scale * depth)

        # Proximity constellation connection lines
        n = len(projected)
        for i in range(n):
            for j in range(i + 1, n):
                x1, y1, z1, _ = projected[i]
                x2, y2, z2, _ = projected[j]
                dist_sq = (x1 - x2) ** 2 + (y1 - y2) ** 2
                max_dist_sq = (base_r * 0.55) ** 2
                if dist_sq < max_dist_sq:
                    strength = 1.0 - (dist_sq / max_dist_sq)
                    alpha = int(65 * strength)
                    pen = QPen(QColor(r, g, b, alpha), 0.9)
                    p.setPen(pen)
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _draw_holographic_core(self, p: QPainter, cx: float, cy: float, base_r: float,
                               r: int, g: int, b: int, state: str, t: float, audio: float):
        """Renders the layered 3D holographic plasma energy core."""
        is_off = state in ("offline", "paused", "muted", "disabled")
        is_active = state in ("listening", "thinking", "speaking", "executing", "working", "processing")
        is_err = state in ("error", "failed")

        # 3D Specular Highlight offset derived from Camera Parallax
        spec_ox = -base_r * 0.32 + self._yaw * base_r * 0.45
        spec_oy = -base_r * 0.35 + self._pitch * base_r * 0.45

        if is_off:
            # Offline structural dormant core
            gr = QRadialGradient(cx + spec_ox, cy + spec_oy, base_r * 1.1)
            gr.setColorAt(0.0, QColor(95, 120, 135, 230))
            gr.setColorAt(0.65, QColor(50, 72, 84, 240))
            gr.setColorAt(1.0, QColor(28, 42, 52, 250))
            p.setBrush(QBrush(gr))
            p.setPen(QPen(QColor(80, 110, 125, 130), 1.2, Qt.PenStyle.DashLine))
            p.drawEllipse(QPointF(cx, cy), base_r, base_r)
        else:
            pulse = 0.5 + 0.5 * math.sin(t * (2.2 if is_active else 1.1))
            core_r = base_r * (1.0 + 0.03 * pulse + 0.06 * audio)

            # Deep 3D Spherical Plasma Gradient
            r_bright = min(255, int(r * 1.25 + 40))
            g_bright = min(255, int(g * 1.25 + 40))
            b_bright = min(255, int(b * 1.25 + 40))

            gr = QRadialGradient(cx + spec_ox, cy + spec_oy, core_r * 1.15)
            gr.setColorAt(0.0, QColor(r_bright, g_bright, b_bright, 255))
            gr.setColorAt(0.28, QColor(r, g, b, 240))
            gr.setColorAt(0.68, QColor(max(0, r - 70), max(0, g - 70), max(0, b - 70), 245))
            gr.setColorAt(1.0, QColor(10, 20, 32, 240))
            p.setBrush(QBrush(gr))

            rim_alpha = 220 if is_active else 165
            if is_err:
                rim_alpha = 160 + int(95 * math.sin(t * 6.0))
            p.setPen(QPen(QColor(r, g, b, rim_alpha), 1.5))
            p.drawEllipse(QPointF(cx, cy), core_r, core_r)

            # 3D Specular Luster (Parallax reactive)
            hl = QRadialGradient(cx + spec_ox * 1.1, cy + spec_oy * 1.1, core_r * 0.42)
            hl.setColorAt(0.0, QColor(255, 255, 255, 175 if is_active else 120))
            hl.setColorAt(0.45, QColor(r_bright, g_bright, b_bright, 60))
            hl.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(hl))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx + spec_ox, cy + spec_oy), core_r * 0.40, core_r * 0.28)

            # Internal Rotating Gyroscopic Gimbal Rings
            p.save()
            p.translate(cx, cy)
            p.rotate(math.degrees(t * 0.45 + self._yaw))
            gimbal_pen = QPen(QColor(r_bright, g_bright, b_bright, 45), 1.1, Qt.PenStyle.DotLine)
            p.setPen(gimbal_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0, 0), core_r * 0.72, core_r * 0.45)
            p.rotate(90)
            p.drawEllipse(QPointF(0, 0), core_r * 0.72, core_r * 0.35)
            p.restore()

        # Center Holographic Glyph & Telemetry Emblem
        glyph_text, is_symbol = self._state_glyph()
        if glyph_text:
            p.save()
            f_size = int(base_r * 0.46)
            font_family = "Segoe UI Symbol" if is_symbol else "Segoe UI"
            font = QFont(font_family, f_size, QFont.Weight.Bold)
            p.setFont(font)
            text_color = QColor(200, 225, 238, 140) if is_off else QColor(255, 255, 255, 245)
            p.setPen(QPen(text_color, 1))
            rect = QRectF(cx - base_r, cy - base_r, base_r * 2, base_r * 2)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, glyph_text)
            p.restore()

    def _draw_3d_waveform(self, p: QPainter, cx: float, cy: float, base_r: float,
                          r: int, g: int, b: int, audio: float, t: float, n: int = 48):
        """Draws radial 3D acoustic waveform sensors reacting to voice level."""
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(t * 0.15))
        for i in range(n):
            ang = i * (2 * math.pi / n)
            phase = 0.5 + 0.5 * math.sin(t * 4.2 + i * 0.5)
            drive = max(audio, 0.06) * (0.6 + 0.4 * phase)
            bar_len = base_r * (0.08 + 0.55 * drive)
            inner = base_r * 1.08
            outer = inner + bar_len

            x1 = math.cos(ang) * inner
            y1 = math.sin(ang) * inner * 0.92
            x2 = math.cos(ang) * outer
            y2 = math.sin(ang) * outer * 0.92

            alpha = int(255 * (0.35 + 0.65 * drive))
            pen = QPen(QColor(r, g, b, alpha), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        p.restore()

    def _draw_quantum_stream(self, p: QPainter, cx: float, cy: float, radius: float,
                             r: int, g: int, b: int, angle: float, n: int = 6):
        """Draws energetic orbital particle stream with motion blur trails."""
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(angle))
        for i in range(n):
            ang = i * (2 * math.pi / n)
            x = math.cos(ang) * radius
            y = math.sin(ang) * radius * 0.75

            # Trail
            p.setBrush(QColor(r, g, b, 70))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, y), 5.5, 5.5)

            # Bright core node
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawEllipse(QPointF(x, y), 2.5, 2.5)
        p.restore()

    def _state_glyph(self) -> Tuple[str, bool]:
        """Returns the canonical state icon glyph."""
        mapping = {
            "idle":       ("◉", True),
            "ready":      ("◉", True),
            "listening":  ("◉", True),
            "thinking":   ("◌", True),
            "speaking":   ("⟡", True),
            "executing":  ("⚡", True),
            "working":    ("⚡", True),
            "processing": ("⚡", True),
            "error":      ("✕", True),
            "failed":     ("✕", True),
            "offline":    ("⊙", True),
            "paused":     ("⊙", True),
            "muted":      ("⊘", True),
            "disabled":   ("⊙", True),
        }
        return mapping.get(self._state, ("◉", True))
