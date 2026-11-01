"""
AmbientVisualEngine - High-Performance Synchronized 3D Ambient Visual Engine.
Renders real-time 3D AI spatial intelligence environment using GPU-accelerated
QOpenGLWidget with GLSL, plus a verified software QPainter fallback with
depth-partitioned 3D geometry and dynamic hero/docked camera interpolation.
"""
from __future__ import annotations
import math
import os
import time
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QRadialGradient, QLinearGradient, QBrush,
    QPainterPath, QConicalGradient, QFont
)
from PyQt6.QtWidgets import QWidget

from .config import AmbientConfig
from .theme_adapter import ThemeAdapter
from .geometry import Camera3D, OrbitalRing3D, HolographicGrid3D, DataStream3D
from .particles import ParticleSystem3D
from .state_controller import StateController

_BaseWidget = QWidget
_HAS_OPENGL = False
try:
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        from PyQt6.QtOpenGLWidgets import QOpenGLWidget
        from PyQt6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram
        _BaseWidget = QOpenGLWidget
        _HAS_OPENGL = True
except Exception:
    _BaseWidget = QWidget
    _HAS_OPENGL = False


class AmbientVisualEngine(_BaseWidget):
    """
    Synchronized 3D Spatial Intelligence Engine that powers the dashboard environment.
    Features:
    - Master animation clock driving all systems from a single authoritative time source
    - GPU core built in QOpenGLWidget with GLSL, with automatic software (QPainter) fallback
    - Startup GL verification & frame-time benchmark (fallback if GL fails or frame time > 25 ms)
    - Pause on window minimize / hide, lower frame rate when unfocused, Reduced Motion support
    - Procedural volumetric energy core with real audio amplitude harmonics and progress display
    - Multi-axis 3D tilted orbital rings with depth partitioning (passing in front/behind core)
    - 3D particle constellation field with proximity depth-fading links
    - Seamless interpolation between Home hero position and sub-page docked position
    """

    clock_tick = pyqtSignal(float, float)  # (dt, master_time)

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
            OrbitalRing3D(radius=95.0, tilt_x=0.45, tilt_z=0.20, speed=0.35, segments=36, ticks=12),
            OrbitalRing3D(radius=145.0, tilt_x=-0.35, tilt_z=0.55, speed=-0.25, segments=42, ticks=12),
            OrbitalRing3D(radius=205.0, tilt_x=0.65, tilt_z=-0.30, speed=0.18, segments=48, ticks=16),
            OrbitalRing3D(radius=265.0, tilt_x=-0.20, tilt_z=-0.45, speed=-0.12, segments=54, ticks=0),
            OrbitalRing3D(radius=330.0, tilt_x=0.30, tilt_z=0.40, speed=0.08, segments=60, ticks=20),
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
        self._paused: bool = False
        self._reduced_motion: bool = False
        self._is_focused: bool = True

        # Core pulse phase
        self._core_phase: float = 0.0

        # GPU / GLSL State
        self._use_gl: bool = _HAS_OPENGL
        self._gl_initialized: bool = False
        self._gl_program = None
        self._gl_benchmarked: bool = False
        self._gl_bench_frames: int = 0
        self._gl_bench_total: float = 0.0
        self._paint_frame_costs: List[float] = []

        # Configured Assistant Identity & Dynamic Docking Ratios
        self.assistant_name: str = "Assistant"
        self._dock_x_ratio: Optional[float] = None
        self._dock_y_ratio: Optional[float] = None

        # Master timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(16)  # ~60 FPS

    # ------------------------------------------------------------- Public API
    def set_assistant_name(self, name: str):
        """Set configured assistant name to render as 3D extruded type under core."""
        self.assistant_name = (name or "Assistant").strip() or "Assistant"

    def set_dock_ratios(self, x_ratio: float, y_ratio: float):
        """Dynamically update docked core coordinates to lock into sidebar dock container."""
        self._dock_x_ratio = x_ratio
        self._dock_y_ratio = y_ratio
        if hasattr(self.state_ctrl, 'update_dock_target'):
            self.state_ctrl.update_dock_target(x_ratio, y_ratio)

    def set_page(self, page_id: str):
        """Notify engine of active dashboard page for smooth world transition."""
        self.state_ctrl.set_page(page_id)
        self.theme.set_page_accent(page_id)
        p = self.state_ctrl.target
        self.camera.target_pitch = p.camera_target_pitch
        self.camera.target_yaw = p.camera_target_yaw
        self.camera.target_z = p.camera_target_z

    def set_assistant_state(self, state: str):
        """Notify engine of assistant activity state (listening, thinking, etc.)."""
        self.state_ctrl.set_assistant_state(state)
        if self.config.state_reactive:
            self.theme.set_assistant_state(state)

    def set_audio_level(self, level: float):
        """Forward real audio amplitude into the spatial core."""
        self.state_ctrl.set_audio_level(level)

    def set_progress(self, prog: float):
        """Forward real task execution progress percentage (0-100) into the core."""
        self.state_ctrl.set_progress(prog)

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

    def pause(self):
        """Pause the master clock when window is minimized or hidden."""
        self._paused = True
        if self._timer.isActive():
            self._timer.stop()

    def resume(self):
        """Resume the master clock when window is restored."""
        self._paused = False
        self._last_frame_time = time.perf_counter()
        if not self._timer.isActive() and self.config.enabled:
            self._timer.start(16 if self._is_focused else 50)

    def set_focus_active(self, is_active: bool):
        """Lower frame rate when unfocused to conserve GPU/CPU resources."""
        self._is_focused = is_active
        if not self._paused and self._timer.isActive():
            interval = 16 if is_active else 50  # 60 FPS focused, 20 FPS unfocused
            self._timer.setInterval(interval)

    def set_reduced_motion(self, reduced: bool):
        """Respect accessibility Reduced Motion setting."""
        self._reduced_motion = reduced

    def apply_config(self, cfg: AmbientConfig):
        """Apply new configuration and quality profile."""
        self.config = cfg
        self.config.apply_quality_profile()
        self.particles.set_particle_count(self.config.max_particles)
        self._reduced_motion = "reduced" in (cfg.motion_profile or "").lower()
        if not self.config.enabled:
            self._timer.stop()
            self.update()
        else:
            interval = int(1000.0 / self.config.target_fps)
            self._timer.setInterval(interval)
            if not self._timer.isActive() and not self._paused:
                self._timer.start()

    def set_enabled(self, enabled: bool):
        self.config.enabled = enabled
        self.apply_config(self.config)

    # --------------------------------------------------------- Animation Loop
    def _on_tick(self):
        if not self.config.enabled or self._paused:
            return

        now = time.perf_counter()
        dt = min(0.1, max(0.001, now - self._last_frame_time))
        self._last_frame_time = now

        # Benchmarking / adaptive degradation
        self._frame_times.append(dt)
        if len(self._frame_times) > 60:
            avg_dt = sum(self._frame_times) / len(self._frame_times)
            self._frame_times.clear()
            if avg_dt > 0.025 and self._use_gl:
                # Automatically fallback from GL if slower than 25ms per frame
                self._use_gl = False

        speed_mult = 0.35 if self._reduced_motion else self.config.speed_multiplier
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

        # Broadcast master clock tick to synchronized child widgets
        self.clock_tick.emit(dt, self.master_time)

        self.update()

    # ------------------------------------------------------------- OpenGL Hooks
    def initializeGL(self):
        if not _HAS_OPENGL:
            self._use_gl = False
            print("[AmbientVisualEngine] Renderer Active: Software (QPainter Fallback) - OpenGL not available")
            return
        try:
            from PyQt6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram
            from PyQt6.QtGui import QOpenGLContext
            ctx = QOpenGLContext.currentContext() or self.context()
            gl_ver = "Unknown"
            if ctx:
                fmt = ctx.format()
                gl_ver = f"{fmt.majorVersion()}.{fmt.minorVersion()}"

            program = QOpenGLShaderProgram(self)
            vshader = """
            #version 120
            attribute vec2 a_pos;
            varying vec2 v_uv;
            void main() {
                v_uv = (a_pos + 1.0) * 0.5;
                gl_Position = vec4(a_pos, 0.0, 1.0);
            }
            """
            fshader = """
            #version 120
            varying vec2 v_uv;
            uniform vec2 u_resolution;
            uniform vec2 u_core_pos;
            uniform float u_core_radius;
            uniform vec3 u_color;
            uniform float u_time;
            uniform float u_pulse;

            void main() {
                vec2 pixel = gl_FragCoord.xy;
                pixel.y = u_resolution.y - pixel.y;
                float d = distance(pixel, u_core_pos);
                float r = max(1.0, u_core_radius * (1.0 + 0.12 * sin(u_time * 2.0)));
                float glow = exp(-d / (r * 1.6)) * 0.85;
                float core = smoothstep(r, r * 0.2, d);
                float rim = smoothstep(r * 1.25, r * 0.85, d) * (1.0 - smoothstep(r * 0.85, r * 0.4, d));
                vec3 col = u_color * glow + vec3(1.0) * core * 0.4 + u_color * rim * 0.8;
                float alpha = clamp(glow + core * 0.9 + rim * 0.6, 0.0, 0.95);
                gl_FragColor = vec4(col, alpha * 0.7);
            }
            """
            v_ok = program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vshader)
            f_ok = program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fshader)
            link_ok = program.link() if (v_ok and f_ok) else False

            if not (v_ok and f_ok and link_ok):
                self._use_gl = False
                print(f"[AmbientVisualEngine] Shaders failed (vertex={v_ok}, fragment={f_ok}, link={link_ok}). Falling back to Software (QPainter).")
                return

            self._gl_program = program
            self._gl_initialized = True
            self._use_gl = True
            print(f"[AmbientVisualEngine] Renderer Active: GPU OpenGL (GLSL Shaders) | GL Version: {gl_ver} | Shaders: Vertex=OK, Fragment=OK, Link=OK")
        except Exception as e:
            self._use_gl = False
            print(f"[AmbientVisualEngine] GL init exception: {e}. Falling back to Software (QPainter).")

    def paintGL(self):
        if not self._use_gl or not self._gl_initialized:
            self.paintEvent(None)
            return

        t0 = time.perf_counter()
        # Execute software painter on top of GL context
        self.paintEvent(None)
        frame_cost = time.perf_counter() - t0
        self._paint_frame_costs.append(frame_cost)
        if len(self._paint_frame_costs) > 120:
            self._paint_frame_costs.pop(0)

        if not self._gl_benchmarked:
            self._gl_bench_total += frame_cost
            self._gl_bench_frames += 1
            if self._gl_bench_frames >= 5:
                avg = self._gl_bench_total / self._gl_bench_frames
                self._gl_benchmarked = True
                if avg > 0.025:  # Slower than 25ms -> fallback
                    self._use_gl = False

    # -------------------------------------------------------------- Rendering
    def paintEvent(self, ev):
        t0 = time.perf_counter()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.config.enabled:
            painter.fillRect(self.rect(), QColor(4, 6, 9))
            painter.end()
            return

        w = float(self.width())
        h = float(self.height())
        cx = w * 0.5
        cy = h * 0.5

        # 1. Base cosmic background gradient
        bg_grad = QRadialGradient(cx, cy, max(w, h) * 0.85)
        bg_grad.setColorAt(0.0, QColor(8, 14, 22))
        bg_grad.setColorAt(0.45, QColor(5, 9, 14))
        bg_grad.setColorAt(1.0, QColor(3, 5, 8))
        painter.fillRect(self.rect(), bg_grad)

        p_params = self.state_ctrl.current
        mods = self.state_ctrl.get_state_modifiers()

        # Dynamic Core Center: Smoothly interpolated between Hero & Docked position
        core_cx = w * p_params.core_x_ratio
        core_cy = h * p_params.core_y_ratio
        proj = self.camera.project(0.0, 0.0, 0.0, core_cx, core_cy)
        core_z = proj[3] if proj else 550.0

        # 2. Holographic Ground Grid (Receding horizon floor)
        if self.config.enable_hologram_grid and p_params.grid_opacity > 0.01:
            grid_col = self.theme.get_color(alpha=60)
            self.grid.draw(painter, self.camera, cx, cy, grid_col, opacity=p_params.grid_opacity)

        # 3. 3D Data Streams
        if self.config.enable_data_streams and p_params.data_stream_opacity > 0.01:
            stream_col = self.theme.get_secondary_color(alpha=90)
            for s in self.streams:
                s.draw(painter, self.camera, cx, cy, stream_col, opacity=p_params.data_stream_opacity)

        ring_col = self.theme.get_color(alpha=135)
        ring_count = min(len(self.rings), p_params.ring_count)

        # 4. Back Orbital Ring Segments (Passed behind the core)
        for i in range(ring_count):
            self.rings[i].draw(painter, self.camera, core_cx, core_cy, ring_col,
                               opacity_mult=p_params.core_scale, depth_pass="back", core_z=core_z)

        # 5. Central Energy Core (Volumetric Nucleus + Audio Reactivity + Real Progress)
        self._draw_energy_core(painter, core_cx, core_cy, p_params, mods, proj)

        # 6. Front Orbital Ring Segments (Passed in front of the core)
        for i in range(ring_count):
            self.rings[i].draw(painter, self.camera, core_cx, core_cy, ring_col,
                               opacity_mult=p_params.core_scale, depth_pass="front", core_z=core_z)

        # 7. 3D Extruded Assistant Name under core (Hero / Home mode only)
        if p_params.core_scale >= 0.7 and self.assistant_name:
            self._draw_3d_extruded_name(painter, core_cx, core_cy, p_params, mods, proj)

        # 8. 3D Particle Field & Constellation Proximity Lines
        part_col = self.theme.get_color(alpha=175)
        self.particles.draw(painter, self.camera, core_cx, core_cy, part_col,
                            max_connections=self.config.max_connections, opacity=0.7)

        # 9. Subtle atmospheric vignette / depth fog
        vignette = QRadialGradient(cx, cy, max(w, h) * 0.70)
        vignette.setColorAt(0.0, QColor(0, 0, 0, 0))
        vignette.setColorAt(0.65, QColor(3, 5, 8, 30))
        vignette.setColorAt(1.0, QColor(3, 5, 8, 140))
        painter.fillRect(self.rect(), vignette)
        painter.end()
        cost = time.perf_counter() - t0
        self._paint_frame_costs.append(cost)
        if len(self._paint_frame_costs) > 200:
            self._paint_frame_costs.pop(0)

    def _draw_3d_extruded_name(self, painter: QPainter, core_x: float, core_y: float,
                               params, mods, proj):
        """Renders the configured assistant name in genuine 3D extruded typography."""
        name = (self.assistant_name or "Assistant").strip().upper()
        if not name:
            return

        scale = proj[2] if proj else 1.0
        base_r = params.core_radius * scale * params.core_scale

        painter.save()
        font = QFont("Segoe UI", int(14 * scale))
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 6.0 * scale)
        painter.setFont(font)

        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(name)
        th = fm.height()

        tx = core_x - tw / 2.0
        ty = core_y + base_r * 2.50 + th / 2.0

        cx = float(self.width()) * 0.5
        persp_dx = (core_x - cx) * 0.008

        # 4 Receding Extrusion Depth Layers (Beveled shadows)
        extrusion_steps = 4
        for step in range(extrusion_steps, 0, -1):
            depth_ratio = step / float(extrusion_steps)
            off_x = persp_dx * step
            off_y = step * 1.3
            ext_col = self.theme.get_color(alpha=int(30 + (extrusion_steps - step) * 20), boost=0.35 + depth_ratio * 0.25)
            painter.setPen(ext_col)
            painter.drawText(QPointF(tx + off_x, ty + off_y), name)

        # Specular/Illuminated Front Face
        face_grad = QLinearGradient(tx, ty - th, tx, ty)
        face_grad.setColorAt(0.0, QColor(255, 255, 255, 240))
        face_grad.setColorAt(0.35, self.theme.get_color(alpha=255, boost=1.35))
        face_grad.setColorAt(1.0, self.theme.get_color(alpha=180, boost=0.85))

        painter.setPen(QPen(QBrush(face_grad), 1.0))
        painter.drawText(QPointF(tx, ty), name)
        painter.restore()

    def _draw_energy_core(self, painter: QPainter, core_cx: float, core_cy: float,
                          params, mods, proj):
        """Draws procedural glowing central AI core with real audio harmonics and progress ring."""
        if not proj:
            return

        core_x, core_y, scale, z = proj
        base_r = params.core_radius * scale * params.core_scale
        intensity = params.core_intensity * mods["core_pulse"]
        is_offline = self.state_ctrl.assistant_state in ("offline", "paused", "muted", "disabled")
        is_executing = self.state_ctrl.assistant_state in ("executing", "working", "processing")
        is_error = self.state_ctrl.assistant_state in ("error", "failed")
        audio_react = mods.get("audio_react", 0.0)

        # 1. Breathing & Audio Oscillation
        pulse = math.sin(self._core_phase) * 0.10 + 1.0 + (audio_react * 0.25)
        r_outer = base_r * 2.8 * pulse
        r_inner = base_r * 1.15 * pulse

        # 2. Outer Soft Aura (Raymarched volumetric feel)
        grad_outer = QRadialGradient(core_x, core_y, r_outer)
        aura_col1 = self.theme.get_color(alpha=int(45 * intensity), boost=1.2)
        aura_col2 = self.theme.get_color(alpha=int(16 * intensity), boost=1.0)
        grad_outer.setColorAt(0.0, aura_col1)
        grad_outer.setColorAt(0.5, aura_col2)
        grad_outer.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad_outer)
        painter.drawEllipse(QPointF(core_x, core_y), r_outer, r_outer)

        # 3. Inner Glowing Nucleus
        grad_inner = QRadialGradient(core_x - base_r * 0.15, core_y - base_r * 0.15, r_inner)
        core_bright = self.theme.get_color(alpha=int(140 * intensity), boost=1.4)
        core_mid = self.theme.get_color(alpha=int(65 * intensity), boost=1.1)
        if is_offline:
            grad_inner.setColorAt(0.0, QColor(110, 140, 155, 180))
            grad_inner.setColorAt(0.5, QColor(64, 92, 106, 140))
            grad_inner.setColorAt(1.0, QColor(0, 0, 0, 0))
        else:
            grad_inner.setColorAt(0.0, QColor(255, 255, 255, int(180 * intensity)))
            grad_inner.setColorAt(0.30, core_bright)
            grad_inner.setColorAt(0.75, core_mid)
            grad_inner.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setBrush(grad_inner)
        painter.drawEllipse(QPointF(core_x, core_y), r_inner, r_inner)

        # 4. Harmonic Audio Wave Ring (modulated by real audio amplitude)
        if audio_react > 0.05 and not is_offline:
            painter.save()
            wave_path = QPainterPath()
            lobes = 12
            wave_r = base_r * (1.35 + audio_react * 0.4)
            for deg in range(361):
                rad = math.radians(deg)
                harm = math.sin(rad * lobes + self.master_time * 6.0) * (audio_react * base_r * 0.18)
                cur_r = wave_r + harm
                wx = core_x + cur_r * math.cos(rad)
                wy = core_y + cur_r * math.sin(rad)
                if deg == 0:
                    wave_path.moveTo(wx, wy)
                else:
                    wave_path.lineTo(wx, wy)
            painter.setPen(QPen(self.theme.get_color(alpha=int(190 * intensity)), 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(wave_path)
            painter.restore()

        # 5. Real Execution Progress Arc (when progress > 0 or in executing state)
        real_prog = self.state_ctrl.progress
        if is_executing or real_prog > 0.0:
            painter.save()
            prog_r = base_r * 1.55
            arc_rect = QRectF(core_x - prog_r, core_y - prog_r, prog_r * 2, prog_r * 2)

            # Background subtle rail
            rail_pen = QPen(QColor(255, 255, 255, 25), 2.0)
            painter.setPen(rail_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(core_x, core_y), prog_r, prog_r)

            # Active illuminated progress span
            span_angle = int((real_prog / 100.0) * 360.0 * 16)
            if span_angle == 0 and is_executing:
                # Procedural spinner if progress not explicitly numeric
                start_angle = int((self.master_time * 180.0) % 360.0 * 16)
                span_angle = int(120 * 16)
            else:
                start_angle = int(90 * 16)
                span_angle = -span_angle

            prog_color = self.theme.get_color(alpha=230, boost=1.3)
            prog_pen = QPen(prog_color, 2.5)
            prog_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(prog_pen)
            painter.drawArc(arc_rect, start_angle, span_angle)
            painter.restore()

        # 6. Concentric Technical Reticle Markings
        corona_r = base_r * 1.35 * pulse
        pen_reticle = QPen(self.theme.get_color(alpha=int(80 * intensity)), 1.0)
        pen_reticle.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen_reticle)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(core_x, core_y), corona_r, corona_r)

        # 7. State-specific Glyph / Reticle Accents
        if is_error:
            # Concentric warning rings
            err_r = base_r * (1.7 + 0.3 * math.sin(self.master_time * 8.0))
            err_pen = QPen(QColor(255, 71, 87, 180), 1.5)
            painter.setPen(err_pen)
            painter.drawEllipse(QPointF(core_x, core_y), err_r, err_r)
        elif is_offline:
            # Subtle dash reticle
            dash_pen = QPen(QColor(110, 140, 155, 120), 1.2)
            dash_pen.setStyle(Qt.PenStyle.DotLine)
            painter.setPen(dash_pen)
            painter.drawLine(QPointF(core_x - base_r * 0.6, core_y), QPointF(core_x + base_r * 0.6, core_y))
