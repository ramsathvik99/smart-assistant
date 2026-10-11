"""
AmbientVisualEngine - High-Performance Synchronized 3D Ambient Visual Engine.
Renders real-time 3D AI ambient environment using hardware-accelerated QOpenGLWidget.
"""
from __future__ import annotations
import math
import time
from typing import List, Optional
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QRadialGradient, QLinearGradient, QBrush
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QWidget

from .config import AmbientConfig
from .theme_adapter import ThemeAdapter
from .geometry import Camera3D, OrbitalRing3D, HolographicGrid3D, DataStream3D
from .particles import ParticleSystem3D
from .state_controller import StateController


import os

_BaseWidget = QWidget
try:
    # In headless/offscreen mode, QOpenGLWidget crashes due to lack of WGL/GLX platform context.
    # We dynamically use QOpenGLWidget when available and not in offscreen platform.
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        from PyQt6.QtOpenGLWidgets import QOpenGLWidget
        _BaseWidget = QOpenGLWidget
except Exception:
    _BaseWidget = QWidget


class AmbientVisualEngine(_BaseWidget):
    """
    Synchronized 3D Ambient Engine that renders behind the entire dashboard.
    Features:
    - Master animation clock driving all systems from a single time source
    - Central procedural energy core with dynamic pulsing
    - 3D tilted orbital rings with telemetry ticks
    - 3D particle field with proximity constellation lines
    - Holographic perspective grid and flowing data streams
    - Smooth 3D camera with mouse parallax
    - Seamless interpolation across all 9 dashboard pages and assistant states
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.config = AmbientConfig()
        self.theme = ThemeAdapter()
        self.state_ctrl = StateController()
        self.camera = Camera3D(fov=620.0)

        # 3D Elements
        self.particles = ParticleSystem3D(count=self.config.max_particles)
        self.grid = HolographicGrid3D(size=1400.0, step=140.0, elevation=280.0)
        self.rings: List[OrbitalRing3D] = [
            OrbitalRing3D(radius=105.0, tilt_x=0.45, tilt_z=0.20, speed=0.35, segments=48, ticks=16),
            OrbitalRing3D(radius=155.0, tilt_x=-0.35, tilt_z=0.55, speed=-0.25, segments=52, ticks=12),
            OrbitalRing3D(radius=210.0, tilt_x=0.65, tilt_z=-0.30, speed=0.18, segments=60, ticks=24),
            OrbitalRing3D(radius=270.0, tilt_x=-0.20, tilt_z=-0.45, speed=-0.12, segments=64, ticks=0),
            OrbitalRing3D(radius=340.0, tilt_x=0.30, tilt_z=0.40, speed=0.08, segments=72, ticks=32),
        ]

        # 3D Data streams
        self.streams: List[DataStream3D] = [
            DataStream3D(start_pt=(-380.0, -120.0, 300.0), end_pt=(250.0, 160.0, -100.0),
                         ctrl_pt=(-60.0, -220.0, 150.0), speed=0.35),
            DataStream3D(start_pt=(360.0, -140.0, 350.0), end_pt=(-220.0, 180.0, -150.0),
                         ctrl_pt=(80.0, 220.0, 180.0), speed=0.42),
            DataStream3D(start_pt=(-150.0, 220.0, 400.0), end_pt=(150.0, -220.0, -50.0),
                         ctrl_pt=(220.0, 40.0, 220.0), speed=0.28),
        ]

        # Master clock and animation state
        self.master_time: float = 0.0
        self._last_frame_time: float = time.perf_counter()
        self._frame_times: List[float] = []

        # Core pulse phase
        self._core_phase: float = 0.0

        # Master timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(16)  # ~60 FPS

    # ------------------------------------------------------------- Public API
    def set_page(self, page_id: str):
        """Notify engine of active dashboard page for smooth world transition."""
        self.state_ctrl.set_page(page_id)
        self.theme.set_page_accent(page_id)
        # Set camera target based on page
        p = self.state_ctrl.target
        self.camera.target_pitch = p.camera_target_pitch
        self.camera.target_yaw = p.camera_target_yaw
        self.camera.target_z = p.camera_target_z

    def set_assistant_state(self, state: str):
        """Notify engine of assistant activity state (listening, thinking, etc.)."""
        self.state_ctrl.set_assistant_state(state)
        if self.config.state_reactive:
            self.theme.set_assistant_state(state)

    def set_accent(self, hex_code: str):
        """Update primary accent color dynamically."""
        self.theme.set_accent_color(hex_code)

    def set_mouse_pos(self, mx: int, my: int):
        """Update subtle mouse parallax offset."""
        if not self.config.mouse_parallax or not self.config.enabled:
            return
        w = max(1, self.width())
        h = max(1, self.height())
        norm_x = (mx / w) * 2.0 - 1.0
        norm_y = (my / h) * 2.0 - 1.0
        self.camera.set_mouse_offset(norm_x, norm_y)

    def apply_config(self, cfg: AmbientConfig):
        """Apply new configuration and quality profile."""
        self.config = cfg
        self.config.apply_quality_profile()
        self.particles.set_particle_count(self.config.max_particles)
        if not self.config.enabled:
            self._timer.stop()
            self.update()
        else:
            interval = int(1000.0 / self.config.target_fps)
            self._timer.setInterval(interval)
            if not self._timer.isActive():
                self._timer.start()

    def set_enabled(self, enabled: bool):
        self.config.enabled = enabled
        self.apply_config(self.config)

    # --------------------------------------------------------- Animation Loop
    def _on_tick(self):
        if not self.config.enabled:
            return

        now = time.perf_counter()
        dt = min(0.1, max(0.001, now - self._last_frame_time))
        self._last_frame_time = now

        # Adaptive performance monitoring (check rolling average)
        self._frame_times.append(dt)
        if len(self._frame_times) > 60:
            avg_dt = sum(self._frame_times) / len(self._frame_times)
            self._frame_times.clear()
            if avg_dt > 0.035 and self.config.quality == "High":  # < ~28 FPS
                # Gracefully degrade to Medium
                self.config.quality = "Medium"
                self.config.apply_quality_profile()
                self.particles.set_particle_count(self.config.max_particles)

        speed_mult = self.config.speed_multiplier
        mods = self.state_ctrl.get_state_modifiers()
        state_speed = mods["speed"]
        core_pulse_mod = mods["core_pulse"]
        excitement = mods["excitement"]

        self.master_time += dt * speed_mult * state_speed
        self._core_phase = (self._core_phase + dt * 1.8 * core_pulse_mod * speed_mult) % (math.pi * 2)

        # Update subcomponents
        self.theme.update(dt)
        self.state_ctrl.update(dt, speed_mult)
        self.camera.update(dt, speed_mult)

        # Update rings
        p_params = self.state_ctrl.current
        for ring in self.rings:
            ring.update(dt, speed_mult * p_params.ring_speed * state_speed)

        # Update particles
        self.particles.node_connection_opacity = p_params.node_connectivity
        self.particles.update(dt, speed_mult * p_params.particle_speed, excitement)

        # Update grid & data streams
        if self.config.enable_hologram_grid:
            self.grid.update(dt, speed_mult)
        if self.config.enable_data_streams:
            for s in self.streams:
                s.update(dt, speed_mult * state_speed)

        self.update()

    # -------------------------------------------------------------- Rendering
    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # If disabled, fill with deep clean canvas and return
        if not self.config.enabled:
            painter.fillRect(self.rect(), QColor(4, 6, 9))
            painter.end()
            return

        w = float(self.width())
        h = float(self.height())
        cx = w * 0.5
        cy = h * 0.5

        # 1. Base cosmic background gradient
        bg_grad = QRadialGradient(cx, cy, max(w, h) * 0.75)
        # Deep glowing cosmic core to obsidian horizon
        primary_col = self.theme.get_color(alpha=18, boost=0.6)
        bg_grad.setColorAt(0.0, QColor(8, 14, 22))
        bg_grad.setColorAt(0.45, QColor(5, 9, 14))
        bg_grad.setColorAt(1.0, QColor(3, 5, 8))
        painter.fillRect(self.rect(), bg_grad)

        # Visual parameters
        p_params = self.state_ctrl.current
        mods = self.state_ctrl.get_state_modifiers()

        # 2. Holographic Ground Grid (Receding horizon floor)
        if self.config.enable_hologram_grid:
            grid_col = self.theme.get_color(alpha=70)
            self.grid.draw(painter, self.camera, cx, cy, grid_col, opacity=p_params.grid_opacity)

        # 3. 3D Data Streams (flowing splines with light packets)
        if self.config.enable_data_streams:
            stream_col = self.theme.get_secondary_color(alpha=110)
            for s in self.streams:
                s.draw(painter, self.camera, cx, cy, stream_col, opacity=p_params.data_stream_opacity)

        # 4. Central Energy Core (multi-stop radial gradient with procedural breath)
        self._draw_energy_core(painter, cx, cy, p_params, mods)

        # 5. Orbital 3D Rings
        ring_col = self.theme.get_color(alpha=125)
        ring_count = min(len(self.rings), p_params.ring_count)
        for i in range(ring_count):
            self.rings[i].draw(painter, self.camera, cx, cy, ring_col, opacity_mult=1.0)

        # 6. 3D Particle Field & Constellation Proximity Lines
        part_col = self.theme.get_color(alpha=175)
        self.particles.draw(painter, self.camera, cx, cy, part_col,
                            max_connections=self.config.max_connections, opacity=0.7)

        # 7. Subtle atmospheric vignette / depth fog
        # Keeps content area clean and readable for the dashboard cards
        vignette = QRadialGradient(cx, cy, max(w, h) * 0.65)
        vignette.setColorAt(0.0, QColor(0, 0, 0, 0))
        vignette.setColorAt(0.65, QColor(3, 5, 8, 40))
        vignette.setColorAt(1.0, QColor(3, 5, 8, 140))
        painter.fillRect(self.rect(), vignette)

        painter.end()

    def _draw_energy_core(self, painter: QPainter, cx: float, cy: float,
                          params, mods):
        """Draws procedural glowing central AI core with layered concentric auras."""
        proj = self.camera.project(0.0, 0.0, 0.0, cx, cy)
        if not proj:
            return

        core_x, core_y, scale, z = proj
        base_r = params.core_radius * scale
        intensity = params.core_intensity * mods["core_pulse"]

        # Breathing oscillation
        pulse = math.sin(self._core_phase) * 0.12 + 1.0
        r_outer = base_r * 2.8 * pulse
        r_inner = base_r * 1.1 * pulse

        # Outer Soft Aura (additive glow feel)
        grad_outer = QRadialGradient(core_x, core_y, r_outer)
        aura_col1 = self.theme.get_color(alpha=int(38 * intensity), boost=1.2)
        aura_col2 = self.theme.get_color(alpha=int(14 * intensity), boost=1.0)
        grad_outer.setColorAt(0.0, aura_col1)
        grad_outer.setColorAt(0.5, aura_col2)
        grad_outer.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad_outer)
        painter.drawEllipse(QPointF(core_x, core_y), r_outer, r_outer)

        # Inner Glowing Nucleus
        grad_inner = QRadialGradient(core_x, core_y, r_inner)
        core_bright = self.theme.get_color(alpha=int(120 * intensity), boost=1.4)
        core_mid = self.theme.get_color(alpha=int(55 * intensity), boost=1.1)
        grad_inner.setColorAt(0.0, QColor(255, 255, 255, int(160 * intensity)))
        grad_inner.setColorAt(0.25, core_bright)
        grad_inner.setColorAt(0.70, core_mid)
        grad_inner.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setBrush(grad_inner)
        painter.drawEllipse(QPointF(core_x, core_y), r_inner, r_inner)

        # Concentric geometric corona ring
        corona_r = base_r * 1.4 * pulse
        pen = QPen(self.theme.get_color(alpha=int(75 * intensity)), 1.2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(core_x, core_y), corona_r, corona_r)
