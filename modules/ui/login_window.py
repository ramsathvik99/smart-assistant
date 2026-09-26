"""
Smart Assistant — Cinematic 3D AI Command Environment
Dramatically upgraded futuristic 3D background environment for the authentication experience.
Features:
- Sophisticated Central AI Core with multi-layered geometry, rotating 3D crystalline octahedron cage,
  counter-rotating orbital rings, internal plasma particles, and expanding energy shockwaves.
- Massive 3D Chamber Architecture with distant structural ceiling arches, horizon haze, and energy pillars.
- 3D Digital Globe / spherical planetary data visualization with rotating rings, surface data arcs, and traveling packets.
- 3D Circular Floor Platform with concentric rings, radial perspective grid, rotating radar sweep beam, and floor data pulses.
- Floating Holographic Side Panels with animated mini-waveform visualizer, circular gyroscope radar, and scanning sweeps.
- Multi-layer volumetric particle system (distant starfield, midground drift, and core orbital swarm).
- Dynamic 3D mouse parallax tracking and focus-reactive core illumination.
- Center contrast shield assuring 100% pristine legibility for the minimal authentication controls.
- 100% preservation of PostgreSQL authentication, onboarding, and backend logic.
"""

import math
import random
import threading

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QSizePolicy, QApplication, QComboBox,
    QStackedWidget
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect,
    pyqtSignal, QThread, QObject, QPoint, QPointF
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QLinearGradient,
    QRadialGradient, QPainterPath, QPolygonF, QFocusEvent
)

from modules.ui.design_system import F, Radius


# ─────────────────────────────────────────────────────────────────────────────
# PRESERVED AUTHENTICATION WORKERS & THREADS
# ─────────────────────────────────────────────────────────────────────────────
class AuthWorker(QObject):
    success = pyqtSignal(int, str, object)   # (user_id, username, result_type)
    failed  = pyqtSignal(str)                # error message

    def __init__(self, username: str, password: str, mode: str = "login"):
        super().__init__()
        self._username = username
        self._password = password
        self._mode = mode

    def run(self):
        try:
            if self._mode == "signup":
                from legacy.memory_manager import register_user
                user_id, result = register_user(self._username, self._password)
                if result == "USER_EXISTS":
                    self.failed.emit("That username is already taken. Please choose another or Sign In.")
                elif user_id:
                    self.success.emit(user_id, self._username, result)
                else:
                    self.failed.emit("Account creation could not be completed. Please try again.")
            else:
                from legacy.memory_manager import authenticate_user
                user_id, result = authenticate_user(self._username, self._password)
                if result == "USER_NOT_FOUND":
                    self.failed.emit("No account found with that username.")
                elif result == "WRONG_PASSWORD":
                    self.failed.emit("Incorrect password. Please try again.")
                elif user_id:
                    self.success.emit(user_id, self._username, result)
                else:
                    self.failed.emit("Sign in failed. Please try again.")
        except Exception as e:
            self.failed.emit(f"Connection error: {e}")


class AuthThread(QThread):
    success = pyqtSignal(int, str, object)
    failed  = pyqtSignal(str)

    def __init__(self, username: str, password: str, mode: str = "login"):
        super().__init__()
        self._w = AuthWorker(username, password, mode=mode)
        self._w.success.connect(self.success)
        self._w.failed.connect(self.failed)

    def run(self):
        self._w.run()


# ─────────────────────────────────────────────────────────────────────────────
# 3D PERSPECTIVE PROJECTION ENGINE HELPER
# ─────────────────────────────────────────────────────────────────────────────
def _project_3d(x: float, y: float, z: float, cx: float, cy: float,
                fl: float = 480.0, cam_z: float = 620.0,
                pitch: float = 0.0, yaw: float = 0.0) -> tuple[float | None, float | None, float]:
    """
    Project 3D world coordinates (x, y, z) into 2D screen coordinates (px, py).
    Applies camera yaw (Y-rotation) and pitch (X-rotation) with depth clipping.
    """
    # 1. Rotate around Y (yaw)
    cos_y = math.cos(yaw)
    sin_y = math.sin(yaw)
    x1 = x * cos_y + z * sin_y
    z1 = -x * sin_y + z * cos_y

    # 2. Rotate around X (pitch)
    cos_p = math.cos(pitch)
    sin_p = math.sin(pitch)
    y1 = y * cos_p - z1 * sin_p
    z2 = y * sin_p + z1 * cos_p

    total_z = z2 + cam_z
    if total_z <= 25.0:
        return None, None, 0.0

    scale = fl / total_z
    return cx + x1 * scale, cy + y1 * scale, scale


# ─────────────────────────────────────────────────────────────────────────────
# MAJOR 3D CINEMATIC AI COMMAND ENVIRONMENT CANVAS
# ─────────────────────────────────────────────────────────────────────────────
class Futuristic3DCanvas(QWidget):
    """
    Grand 3D AI Command Chamber Environment.
    A deeply layered, high-impact cybernetic environment:
    1. Deep Atmospheric Spatial Backdrop with vibrant cybernetic radial ambient illumination.
    2. Giant Central AI Core crowning majestically above the authentication controls:
       - Multi-stop radiant white-cyan plasma singularity with lens flares
       - Dual 3D rotating crystalline nested polyhedrons (outer octahedron + inner crystal)
       - 60-tick rotating HUD reticle ring
       - 4 massive panoramic 3D orbital rings (radii 170 to 480px)
       - High-speed quantum spark orbit swarm (24 particles)
       - Periodic expanding 3D shockwave energy pulses (every 6s)
       - Luminous vertical reactor energy beam connecting ceiling to floor dais
    3. 3D Circular Floor Platform & Reactor Dais:
       - 8 concentric depth rings (radii 130 to 1100px)
       - 28 perspective radial spokes receding into horizon depth
       - Continuous 360° rotating radar sweep beam with luminous gradient
       - 4 outward-rippling floor energy waves
       - Glowing intersection nodes at coordinate points
    4. 3D Large Chamber Architecture:
       - Massive vaulted structural ceiling arches with structural truss segments
       - Twin vertical reactor power columns with animated rising data pulses and ladder conduits
    5. Upper-Left: 3D Rotating Holographic Globe:
       - 180 Fibonacci surface nodes with depth-scaled luminescence
       - Equator and 4 rotating latitude/longitude meridian rings
       - Satellite orbital path with orbiting node
       - Great-circle surface data arc with high-speed pulse packet
       - HUD status telemetry
    6. Upper-Right: 3D Holographic Tactical Orbit Array:
       - 3 nested concentric gyroscope telemetry rings
       - Cardinal azimuth markings (000°, 090°, 180°, 270°)
       - Rotating radar scanning sweep
       - Live orbital telemetry caption
    7. Floating Holographic Side Panels:
       - Left: System Matrix with live 12-bar waveform equalizer, directives, and laser scan line
       - Right: Cognitive Capabilities with live rotating circular radar reticle and activity bars
    8. Multi-Layer Volumetric Particles:
       - Distant starfield (Layer A, 90 stars)
       - Drifting volumetric energy motes (Layer B, 65 particles)
       - Large foreground glowing bokeh orbs (Layer C, 12 orbs)
       - Core high-speed quantum swarm (Layer D, 24 particles)
    9. Dynamic 3D mouse parallax and focus reactivity.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        self._t = 0.0
        self._mouse_curr = QPointF(-1000, -1000)
        self._mouse_target = QPointF(-1000, -1000)
        self._focus_intensity = 0.0
        self._target_focus = 0.0
        self._reduced_motion = False

        # ── 1. Distant Starfield Data Points (Layer A) ───────────
        self._starfield = [
            (random.uniform(-1200, 1200), random.uniform(-750, 320), random.uniform(650, 1150),
             random.uniform(0.35, 0.95))
            for _ in range(90)
        ]

        # ── 2. 3D Digital Globe Points (Fibonacci Sphere) ────────
        self._globe_points = []
        n_globe = 180
        r_globe = 140.0
        for i in range(n_globe):
            phi = math.acos(1.0 - 2.0 * (i + 0.5) / n_globe)
            theta = math.pi * (1.0 + 5.0 ** 0.5) * i
            gx = r_globe * math.sin(phi) * math.cos(theta)
            gy = r_globe * math.sin(phi) * math.sin(theta)
            gz = r_globe * math.cos(phi)
            self._globe_points.append((gx, gy, gz))

        # ── 3. Midground Volumetric Drift Particles (Layer B) ────
        self._mid_particles = [
            {
                'x': random.uniform(-700, 700),
                'y': random.uniform(-400, 260),
                'z': random.uniform(60, 780),
                'vx': random.uniform(-0.28, 0.28),
                'vy': random.uniform(-0.48, -0.12),
                'vz': random.uniform(-0.18, 0.18),
                'size': random.uniform(1.8, 3.6),
                'alpha': random.uniform(0.40, 0.90),
                'phase': random.uniform(0.0, 6.28),
            }
            for _ in range(65)
        ]

        # ── 4. Large Foreground Bokeh Orbs (Layer C) ─────────────
        self._fg_orbs = [
            {
                'x': random.uniform(-500, 500),
                'y': random.uniform(-280, 220),
                'z': random.uniform(35, 170),
                'vx': random.uniform(-0.18, 0.18),
                'vy': random.uniform(-0.22, 0.22),
                'size': random.uniform(5.5, 9.0),
                'phase': random.uniform(0.0, 6.28)
            }
            for _ in range(12)
        ]

        # ── 5. Crystalline Octahedron Geometry ───────────────────
        s_oct = 48.0
        self._octahedron_verts = [
            (0.0, -s_oct * 1.45, 0.0),    # 0: Top apex
            (0.0, s_oct * 1.45, 0.0),     # 1: Bottom apex
            (-s_oct, 0.0, 0.0),           # 2: Left
            (s_oct, 0.0, 0.0),            # 3: Right
            (0.0, 0.0, -s_oct),           # 4: Back
            (0.0, 0.0, s_oct),            # 5: Front
        ]
        self._octahedron_edges = [
            (0, 2), (0, 3), (0, 4), (0, 5),
            (1, 2), (1, 3), (1, 4), (1, 5),
            (2, 4), (4, 3), (3, 5), (5, 2)
        ]

        # Inner nested crystal
        s_in = 25.0
        self._inner_verts = [
            (0.0, -s_in * 1.4, 0.0),
            (0.0, s_in * 1.4, 0.0),
            (-s_in, 0.0, 0.0),
            (s_in, 0.0, 0.0),
            (0.0, 0.0, -s_in),
            (0.0, 0.0, s_in),
        ]

        # ── 6. Animation Timer at ~33 FPS ────────────────────────
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(30)

    def set_mouse_position(self, pt: QPoint):
        self._mouse_target = QPointF(pt.x(), pt.y())
        if self._mouse_curr.x() < -500:
            self._mouse_curr = self._mouse_target

    def set_focused(self, focused: bool):
        self._target_focus = 1.0 if focused else 0.0

    def set_reduced_motion(self, reduced: bool):
        self._reduced_motion = reduced

    def _step(self):
        dt = 0.005 if self._reduced_motion else 0.024
        self._t += dt
        self._focus_intensity += (self._target_focus - self._focus_intensity) * 0.12

        # Smooth camera mouse interpolation
        self._mouse_curr += (self._mouse_target - self._mouse_curr) * 0.06

        # Update midground particles
        for p in self._mid_particles:
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['z'] += p['vz']
            if p['y'] < -400:
                p['y'] = 260
                p['x'] = random.uniform(-700, 700)
            elif p['y'] > 260:
                p['y'] = -400
            if p['x'] < -720:
                p['x'] = 720
            elif p['x'] > 720:
                p['x'] = -720
            if p['z'] < 40:
                p['z'] = 780
            elif p['z'] > 790:
                p['z'] = 50

        # Update foreground orbs
        for o in self._fg_orbs:
            o['x'] += o['vx']
            o['y'] += o['vy']
            if o['x'] < -520:
                o['x'] = 520
            elif o['x'] > 520:
                o['x'] = -520
            if o['y'] < -300:
                o['y'] = 240
            elif o['y'] > 240:
                o['y'] = -300

        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        cx = w / 2.0
        cy = h / 2.0

        # ── 1. CINEMATIC DEEP-CHAMBER ATMOSPHERIC BACKGROUND ─────
        # Deep blue-obsidian radial gradient with glowing horizon and core aura
        bg_grad = QRadialGradient(cx, cy * 0.55, max(w, h) * 0.88)
        bg_grad.setColorAt(0.00, QColor(8, 30, 60))       # Radiant deep cyber blue
        bg_grad.setColorAt(0.35, QColor(4, 16, 32))       # Dark cobalt
        bg_grad.setColorAt(0.70, QColor(2, 8, 18))        # Deep obsidian
        bg_grad.setColorAt(1.00, QColor(1, 3, 8))         # Outer dark void
        p.fillRect(0, 0, int(w), int(h), QBrush(bg_grad))

        # Camera orientation
        yaw = 0.0
        pitch = 0.0
        if self._mouse_curr.x() > 0 and not self._reduced_motion:
            yaw = (self._mouse_curr.x() - cx) * 0.00016
            pitch = (self._mouse_curr.y() - cy) * 0.00012

        fl = 500.0
        cam_z = 620.0

        # ── 2. DISTANT STARFIELD / DATA MATRIX (LAYER A) ─────────
        self._draw_starfield(p, cx, cy, fl, cam_z, yaw, pitch)

        # ── 3. DISTANT 3D CHAMBER ARCHITECTURE & PILLARS ─────────
        self._draw_chamber_architecture(p, cx, cy, fl, cam_z, yaw, pitch)

        # ── 4. UPPER SECTOR: 3D HOLOGRAPHIC GLOBE & TACTICAL ARRAY ─
        self._draw_digital_globe(p, cx, cy, fl, cam_z, yaw, pitch)
        self._draw_tactical_array(p, cx, cy, fl, cam_z, yaw, pitch)

        # ── 5. 3D CIRCULAR FLOOR PLATFORM & PERSPECTIVE GRID ──────
        self._draw_floor_platform(p, cx, cy, fl, cam_z, yaw, pitch)

        # ── 6. FLOATING HOLOGRAPHIC SIDE PANELS (DATA & HUD) ─────
        if w >= 880:
            self._draw_holographic_panels(p, cx, cy, fl, cam_z, yaw, pitch, w)

        # ── 7. MIDGROUND VOLUMETRIC DRIFT PARTICLES (LAYER B) ────
        self._draw_mid_particles(p, cx, cy, fl, cam_z, yaw, pitch)

        # ── 8. FOREGROUND GLOWING BOKEH ORBS (LAYER C) ───────────
        self._draw_foreground_orbs(p, cx, cy, fl, cam_z, yaw, pitch)

        # ── 9. SOPHISTICATED CENTRAL AI CORE (HIGH IMPACT) ───────
        self._draw_central_ai_core(p, cx, cy, fl, cam_z, yaw, pitch)

        p.end()

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: DISTANT STARFIELD
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_starfield(self, p: QPainter, cx: float, cy: float,
                        fl: float, cam_z: float, yaw: float, pitch: float):
        p.setPen(Qt.PenStyle.NoPen)
        for idx, (sx, sy, sz, salpha) in enumerate(self._starfield):
            px, py, _ = _project_3d(sx, sy, sz, cx, cy, fl, cam_z, pitch, yaw)
            if px is not None:
                twinkle = 0.7 + 0.3 * math.sin(self._t * 2.5 + idx)
                alpha = int(salpha * twinkle * 255)
                p.setBrush(QBrush(QColor(186, 230, 253, alpha)))
                p.drawEllipse(QPointF(px, py), 1.5, 1.5)

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: DISTANT CHAMBER ARCHITECTURE & PILLARS
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_chamber_architecture(self, p: QPainter, cx: float, cy: float,
                                   fl: float, cam_z: float, yaw: float, pitch: float):
        """Renders massive vaulted architectural ceiling arches and twin reactor power columns."""
        ground_y = 220.0

        # Curved architectural trusses rising across the upper ceiling
        for arch_z, arch_r, col_a in [(400.0, 800.0, 60), (560.0, 960.0, 48), (740.0, 1140.0, 36)]:
            arch_poly = QPolygonF()
            segments = 36
            for s in range(segments + 1):
                ang = math.pi + (s / float(segments)) * math.pi
                ax = arch_r * math.cos(ang)
                ay = -400.0 + (arch_r * 0.44) * math.sin(ang)
                px, py, _ = _project_3d(ax, ay, arch_z, cx, cy, fl, cam_z, pitch, yaw)
                if px is not None:
                    arch_poly.append(QPointF(px, py))

            if len(arch_poly) > 2:
                p.setPen(QPen(QColor(0, 212, 255, col_a), 1.5, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolyline(arch_poly)

        # Twin vertical reactor power columns
        for pill_x in [-640.0, 640.0]:
            p_top_x, p_top_y, _ = _project_3d(pill_x, -440.0, 340.0, cx, cy, fl, cam_z, pitch, yaw)
            p_bot_x, p_bot_y, _ = _project_3d(pill_x, ground_y, 340.0, cx, cy, fl, cam_z, pitch, yaw)
            if p_top_x is not None and p_bot_x is not None:
                # Primary conduit rail
                p.setPen(QPen(QColor(0, 212, 255, 85), 2.2))
                p.drawLine(QPointF(p_top_x, p_top_y), QPointF(p_bot_x, p_bot_y))

                # Secondary parallel rail
                p2_top_x, p2_top_y, _ = _project_3d(pill_x + (18.0 if pill_x > 0 else -18.0), -440.0, 340.0, cx, cy, fl, cam_z, pitch, yaw)
                p2_bot_x, p2_bot_y, _ = _project_3d(pill_x + (18.0 if pill_x > 0 else -18.0), ground_y, 340.0, cx, cy, fl, cam_z, pitch, yaw)
                if p2_top_x is not None and p2_bot_x is not None:
                    p.setPen(QPen(QColor(0, 180, 240, 50), 1.0))
                    p.drawLine(QPointF(p2_top_x, p2_top_y), QPointF(p2_bot_x, p2_bot_y))

                # Horizontal ladder rungs
                for rung_i in range(9):
                    ry = -400.0 + rung_i * 70.0
                    rx1, ry1, _ = _project_3d(pill_x, ry, 340.0, cx, cy, fl, cam_z, pitch, yaw)
                    rx2, ry2, _ = _project_3d(pill_x + (18.0 if pill_x > 0 else -18.0), ry, 340.0, cx, cy, fl, cam_z, pitch, yaw)
                    if rx1 is not None and rx2 is not None:
                        p.setPen(QPen(QColor(0, 212, 255, 45), 1.0))
                        p.drawLine(QPointF(rx1, ry1), QPointF(rx2, ry2))

                # Ascending high-luminance energy pulses
                for pulse_k in range(2):
                    pulse_y = ground_y - ((self._t * 120.0 + (pulse_k * 300.0) + (150.0 if pill_x > 0 else 0)) % 660.0)
                    pulse_px, pulse_py, pscale = _project_3d(pill_x, pulse_y, 340.0, cx, cy, fl, cam_z, pitch, yaw)
                    if pulse_px is not None:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(QBrush(QColor(255, 255, 255, 255)))
                        p.drawEllipse(QPointF(pulse_px, pulse_py), 3.5 * pscale * 1.5, 3.5 * pscale * 1.5)
                        p.setBrush(QBrush(QColor(0, 212, 255, 140)))
                        p.drawEllipse(QPointF(pulse_px, pulse_py), 8.0 * pscale * 1.5, 8.0 * pscale * 1.5)

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: 3D ROTATING HOLOGRAPHIC GLOBE (UPPER-LEFT)
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_digital_globe(self, p: QPainter, cx: float, cy: float,
                            fl: float, cam_z: float, yaw: float, pitch: float):
        """Renders prominent planetary data sphere with glowing nodes, equator, and satellite orbit."""
        globe_rot = self._t * 0.18
        tilt_x = 0.35
        cx_globe = -470.0
        cy_globe = -190.0
        cz_globe = 270.0

        cos_gr = math.cos(globe_rot)
        sin_gr = math.sin(globe_rot)
        cos_tx = math.cos(tilt_x)
        sin_tx = math.sin(tilt_x)

        # Globe outer glowing corona aura
        g_center_x, g_center_y, g_scale = _project_3d(cx_globe, cy_globe, cz_globe, cx, cy, fl, cam_z, pitch, yaw)
        if g_center_x is not None:
            g_rad = 145.0 * g_scale
            g_glow = QRadialGradient(g_center_x, g_center_y, g_rad * 1.3)
            g_glow.setColorAt(0.0, QColor(0, 212, 255, 55))
            g_glow.setColorAt(0.5, QColor(0, 160, 240, 25))
            g_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g_glow))
            p.drawEllipse(QPointF(g_center_x, g_center_y), g_rad * 1.3, g_rad * 1.3)

        # 3 Latitude Rings (Equator, +35°, -35°)
        for lat_deg, lat_alpha in [(0.0, 100), (35.0, 65), (-35.0, 65)]:
            lat_rad = 140.0 * math.cos(math.radians(lat_deg))
            lat_y = 140.0 * math.sin(math.radians(lat_deg))
            ring_poly = QPolygonF()
            for s in range(32):
                ang = math.radians(s * (360.0 / 32))
                rx = lat_rad * math.cos(ang)
                ry = lat_y
                rz = lat_rad * math.sin(ang)

                # Rotate around Y then tilt X
                rx1 = rx * cos_gr + rz * sin_gr
                rz1 = -rx * sin_gr + rz * cos_gr
                ry2 = ry * cos_tx - rz1 * sin_tx
                rz2 = ry * sin_tx + rz1 * cos_tx

                px, py, _ = _project_3d(rx1 + cx_globe, ry2 + cy_globe, rz2 + cz_globe,
                                        cx, cy, fl, cam_z, pitch, yaw)
                if px is not None:
                    ring_poly.append(QPointF(px, py))

            if len(ring_poly) > 2:
                p.setPen(QPen(QColor(0, 212, 255, lat_alpha), 1.2, Qt.PenStyle.DashLine if lat_deg != 0 else Qt.PenStyle.SolidLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolygon(ring_poly)

        # Tilted Satellite Orbit Ring
        sat_poly = QPolygonF()
        sat_r = 180.0
        sat_ang = self._t * 0.95
        sat_node_pt = None
        for s in range(32):
            ang = math.radians(s * (360.0 / 32))
            ox = sat_r * math.cos(ang)
            oy = sat_r * math.sin(ang) * math.cos(0.7)
            oz = sat_r * math.sin(ang) * math.sin(0.7)
            px, py, _ = _project_3d(ox + cx_globe, oy + cy_globe, oz + cz_globe, cx, cy, fl, cam_z, pitch, yaw)
            if px is not None:
                sat_poly.append(QPointF(px, py))

            if s == 0:
                sx = sat_r * math.cos(sat_ang)
                sy = sat_r * math.sin(sat_ang) * math.cos(0.7)
                sz = sat_r * math.sin(sat_ang) * math.sin(0.7)
                spx, spy, _ = _project_3d(sx + cx_globe, sy + cy_globe, sz + cz_globe, cx, cy, fl, cam_z, pitch, yaw)
                if spx is not None:
                    sat_node_pt = QPointF(spx, spy)

        if len(sat_poly) > 2:
            p.setPen(QPen(QColor(0, 212, 255, 75), 1.0, Qt.PenStyle.DotLine))
            p.drawPolygon(sat_poly)
        if sat_node_pt is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, 255)))
            p.drawEllipse(sat_node_pt, 3.5, 3.5)
            p.setBrush(QBrush(QColor(0, 212, 255, 160)))
            p.drawEllipse(sat_node_pt, 7.0, 7.0)

        # Digital Fibonacci Surface Nodes
        p.setPen(Qt.PenStyle.NoPen)
        for gx, gy, gz in self._globe_points:
            gx1 = gx * cos_gr + gz * sin_gr
            gz1 = -gx * sin_gr + gz * cos_gr
            gy2 = gy * cos_tx - gz1 * sin_tx
            gz2 = gy * sin_tx + gz1 * cos_tx

            px, py, scale = _project_3d(gx1 + cx_globe, gy2 + cy_globe, gz2 + cz_globe,
                                        cx, cy, fl, cam_z, pitch, yaw)
            if px is None:
                continue

            # Front-facing vs back-facing depth illumination
            depth_factor = (gz2 + 140.0) / 280.0
            if depth_factor > 0.38:
                alpha = int(45 + 200 * (depth_factor - 0.38) * 1.6)
                p.setBrush(QBrush(QColor(0, 212, 255, alpha)))
                sz = max(1.2, 3.0 * scale * 1.6)
                p.drawEllipse(QPointF(px, py), sz, sz)
            else:
                p.setBrush(QBrush(QColor(0, 140, 200, 30)))
                p.drawEllipse(QPointF(px, py), 1.1, 1.1)

        # Globe Status Telemetry Caption
        if g_center_x is not None:
            p.setFont(F.mono(8))
            p.setPen(QColor(0, 212, 255, 180))
            p.drawText(int(g_center_x - 60), int(g_center_y + 120), "GLOBAL NET // ONLINE")

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: 3D HOLOGRAPHIC TACTICAL ORBIT ARRAY (UPPER-RIGHT)
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_tactical_array(self, p: QPainter, cx: float, cy: float,
                             fl: float, cam_z: float, yaw: float, pitch: float):
        """Renders tactical satellite telemetry array in upper-right quadrant."""
        cx_tac = 470.0
        cy_tac = -190.0
        cz_tac = 270.0

        t_rot = self._t * 0.65

        # Center anchor
        tx, ty, t_scale = _project_3d(cx_tac, cy_tac, cz_tac, cx, cy, fl, cam_z, pitch, yaw)
        if tx is None:
            return

        # 3 Nested concentric gyroscope telemetry rings
        for r_i, r_val in enumerate([60.0, 95.0, 135.0]):
            r_ang = t_rot * (1.0 if r_i % 2 == 0 else -0.8)
            poly = QPolygonF()
            segments = 32
            for s in range(segments + 1):
                ang = math.radians(s * (360.0 / segments)) + r_ang
                lx = r_val * math.cos(ang)
                ly = r_val * math.sin(ang) * 0.45
                px, py, _ = _project_3d(lx + cx_tac, ly + cy_tac, cz_tac, cx, cy, fl, cam_z, pitch, yaw)
                if px is not None:
                    poly.append(QPointF(px, py))
            if len(poly) > 2:
                p.setPen(QPen(QColor(0, 212, 255, 110 - r_i * 25), 1.2, Qt.PenStyle.DashLine if r_i == 1 else Qt.PenStyle.SolidLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolyline(poly)

        # Cardinal tick marks
        p.setPen(QPen(QColor(0, 212, 255, 140), 1.2))
        for deg in [0, 90, 180, 270]:
            rad = math.radians(deg + t_rot * 20.0)
            p1_x, p1_y, _ = _project_3d(cx_tac + 125.0 * math.cos(rad), cy_tac + 125.0 * math.sin(rad) * 0.45, cz_tac, cx, cy, fl, cam_z, pitch, yaw)
            p2_x, p2_y, _ = _project_3d(cx_tac + 145.0 * math.cos(rad), cy_tac + 145.0 * math.sin(rad) * 0.45, cz_tac, cx, cy, fl, cam_z, pitch, yaw)
            if p1_x is not None and p2_x is not None:
                p.drawLine(QPointF(p1_x, p1_y), QPointF(p2_x, p2_y))

        # Central Reticle Hub
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255, 220)))
        p.drawEllipse(QPointF(tx, ty), 3.0, 3.0)
        p.setBrush(QBrush(QColor(0, 212, 255, 120)))
        p.drawEllipse(QPointF(tx, ty), 6.5, 6.5)

        # Telemetry Text
        p.setFont(F.mono(8))
        p.setPen(QColor(0, 212, 255, 180))
        p.drawText(int(tx - 65), int(ty + 120), "TELEMETRY // SYNCED")

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: 3D CIRCULAR FLOOR PLATFORM & PERSPECTIVE GRID
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_floor_platform(self, p: QPainter, cx: float, cy: float,
                             fl: float, cam_z: float, yaw: float, pitch: float):
        """Renders radiant concentric dais rings, 28 perspective spokes, radar sweep, and ripples."""
        ground_y = 220.0

        # Luminous ambient ground dais fill
        dais_poly = QPolygonF()
        for s in range(36):
            ang = math.radians(s * (360.0 / 36))
            px, py, _ = _project_3d(360.0 * math.cos(ang), ground_y, 360.0 * math.sin(ang),
                                    cx, cy, fl, cam_z, pitch, yaw)
            if px is not None:
                dais_poly.append(QPointF(px, py))
        if len(dais_poly) > 2:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(0, 212, 255, 18)))
            p.drawPolygon(dais_poly)

        # Concentric platform rings with high contrast
        floor_radii = [130.0, 230.0, 350.0, 490.0, 650.0, 840.0, 1060.0]
        for idx, rad in enumerate(floor_radii):
            ring_poly = QPolygonF()
            segments = 40
            for s in range(segments + 1):
                ang = math.radians(s * (360.0 / segments))
                fx = rad * math.cos(ang)
                fz = rad * math.sin(ang)
                px, py, _ = _project_3d(fx, ground_y, fz, cx, cy, fl, cam_z, pitch, yaw)
                if px is not None:
                    ring_poly.append(QPointF(px, py))

            if len(ring_poly) > 2:
                if idx in (0, 1, 2):
                    p.setPen(QPen(QColor(0, 212, 255, 150 - idx * 25), 1.8))
                elif idx in (3, 4):
                    p.setPen(QPen(QColor(0, 180, 240, 85), 1.2, Qt.PenStyle.DashLine))
                else:
                    p.setPen(QPen(QColor(0, 140, 210, 50), 1.0, Qt.PenStyle.DotLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolyline(ring_poly)

        # 28 Radial perspective rays receding to the horizon
        ray_count = 28
        for r_idx in range(ray_count):
            ang = math.radians(r_idx * (360.0 / ray_count))
            p1_x, p1_y, _ = _project_3d(130.0 * math.cos(ang), ground_y, 130.0 * math.sin(ang),
                                        cx, cy, fl, cam_z, pitch, yaw)
            p2_x, p2_y, _ = _project_3d(960.0 * math.cos(ang), ground_y, 960.0 * math.sin(ang),
                                        cx, cy, fl, cam_z, pitch, yaw)
            if p1_x is not None and p2_x is not None:
                alpha = 70 if r_idx % 2 == 0 else 38
                p.setPen(QPen(QColor(0, 212, 255, alpha), 1.1))
                p.drawLine(QPointF(p1_x, p1_y), QPointF(p2_x, p2_y))

        # Active rotating radar sweep beam on 350px dais
        sweep_ang = self._t * 0.95
        sweep_poly = QPolygonF()
        cp_x, cp_y, _ = _project_3d(0, ground_y, 0, cx, cy, fl, cam_z, pitch, yaw)
        if cp_x is not None:
            sweep_poly.append(QPointF(cp_x, cp_y))
            for st in range(12):
                sa = sweep_ang - (st * 0.04)
                sp_x, sp_y, _ = _project_3d(350.0 * math.cos(sa), ground_y, 350.0 * math.sin(sa),
                                            cx, cy, fl, cam_z, pitch, yaw)
                if sp_x is not None:
                    sweep_poly.append(QPointF(sp_x, sp_y))
            if len(sweep_poly) > 2:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(0, 212, 255, 60)))
                p.drawPolygon(sweep_poly)

        # 4 Outward-rippling floor energy waves (pulsing ripples)
        for wave_i in range(4):
            wave_progress = ((self._t * 0.45 + wave_i * 0.25) % 1.0)
            wave_rad = 130.0 + wave_progress * 650.0
            wave_alpha = int((1.0 - wave_progress) * 90)
            w_poly = QPolygonF()
            for s in range(28):
                ang = math.radians(s * (360.0 / 28))
                wx, wy, _ = _project_3d(wave_rad * math.cos(ang), ground_y, wave_rad * math.sin(ang),
                                        cx, cy, fl, cam_z, pitch, yaw)
                if wx is not None:
                    w_poly.append(QPointF(wx, wy))
            if len(w_poly) > 2:
                p.setPen(QPen(QColor(0, 212, 255, wave_alpha), 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolygon(w_poly)

        # Moving floor data packets along 4 cardinal paths
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(4):
            path_ang = i * (math.pi / 2.0)
            packet_dist = 130.0 + ((self._t * 135.0 + i * 165.0) % 720.0)
            pkt_x, pkt_y, pscale = _project_3d(packet_dist * math.cos(path_ang), ground_y,
                                              packet_dist * math.sin(path_ang),
                                              cx, cy, fl, cam_z, pitch, yaw)
            if pkt_x is not None:
                p.setBrush(QBrush(QColor(255, 255, 255, 250)))
                p.drawEllipse(QPointF(pkt_x, pkt_y), 3.2 * pscale * 1.5, 3.2 * pscale * 1.5)
                p.setBrush(QBrush(QColor(0, 212, 255, 130)))
                p.drawEllipse(QPointF(pkt_x, pkt_y), 6.5 * pscale * 1.5, 6.5 * pscale * 1.5)

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: FLOATING HOLOGRAPHIC SIDE PANELS
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_holographic_panels(self, p: QPainter, cx: float, cy: float,
                                fl: float, cam_z: float, yaw: float, pitch: float, w: float):
        """Renders prominent cyberpunk holographic panels with live equalizer and radar HUD."""
        offset_x = min(550.0, w * 0.43)
        breathe_l = math.sin(self._t * 1.4) * 6.0
        breathe_r = math.sin(self._t * 1.4 + 1.6) * 6.0

        p.setFont(F.mono(9))

        # ── Left Holographic Panel: System Directives & Live Equalizer ──
        px_l, py_l, sc_l = _project_3d(-offset_x, 40.0 + breathe_l, 100.0, cx, cy, fl, cam_z, pitch, yaw)
        if px_l is not None:
            panel_w = 180.0 * sc_l
            panel_h = 220.0 * sc_l
            x0 = px_l - panel_w / 2.0
            y0 = py_l - panel_h / 2.0

            # Translucent cyber glass backing
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(4, 14, 28, 150)))
            p.drawRoundedRect(int(x0), int(y0), int(panel_w), int(panel_h), 6, 6)

            # Glowing Corner Brackets
            p.setPen(QPen(QColor(0, 212, 255, 210), 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            br = 15.0
            p.drawLine(QPointF(x0, y0 + br), QPointF(x0, y0))
            p.drawLine(QPointF(x0, y0), QPointF(x0 + br, y0))
            p.drawLine(QPointF(x0 + panel_w - br, y0), QPointF(x0 + panel_w, y0))
            p.drawLine(QPointF(x0 + panel_w, y0), QPointF(x0 + panel_w, y0 + br))
            p.drawLine(QPointF(x0, y0 + panel_h - br), QPointF(x0, y0 + panel_h))
            p.drawLine(QPointF(x0, y0 + panel_h), QPointF(x0 + br, y0 + panel_h))
            p.drawLine(QPointF(x0 + panel_w - br, y0 + panel_h), QPointF(x0 + panel_w, y0 + panel_h))
            p.drawLine(QPointF(x0 + panel_w, y0 + panel_h - br), QPointF(x0 + panel_w, y0 + panel_h))

            # Header
            p.setPen(QColor(0, 212, 255, 230))
            p.drawText(int(x0 + 10), int(y0 + 20), "SYS: MATRIX // 01")
            p.setPen(QPen(QColor(0, 212, 255, 100), 1.0))
            p.drawLine(QPointF(x0 + 8, y0 + 26), QPointF(x0 + panel_w - 8, y0 + 26))

            # Core Directives
            left_tags = ["UNDERSTAND", "PLAN", "EXECUTE", "ADAPT"]
            for idx, tag in enumerate(left_tags):
                p.setPen(QColor(224, 242, 254, 210))
                p.drawText(int(x0 + 10), int(y0 + 50 + idx * 22), f"• {tag}")
                # Status mini-dot
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(0, 229, 107, 230)))
                p.drawEllipse(QPointF(x0 + panel_w - 18, y0 + 45 + idx * 22), 2.5, 2.5)

            # Live 12-bar dynamic waveform equalizer
            wave_y = y0 + 188.0
            p.setPen(Qt.PenStyle.NoPen)
            for bar_i in range(12):
                bar_h = (math.sin(self._t * 4.2 + bar_i * 0.7) * 0.5 + 0.5) * 24.0 + 4.0
                bar_x = x0 + 12 + bar_i * 13
                p.setBrush(QBrush(QColor(0, 212, 255, 190)))
                p.drawRect(int(bar_x), int(wave_y - bar_h), 7, int(bar_h))

            # Oscillating vertical scan sweep line
            scan_y = y0 + ((self._t * 50.0) % panel_h)
            p.setPen(QPen(QColor(0, 212, 255, 120), 1.0))
            p.drawLine(QPointF(x0 + 4, scan_y), QPointF(x0 + panel_w - 4, scan_y))

        # ── Right Holographic Panel: Capabilities & Circular Radar HUD ──
        px_r, py_r, sc_r = _project_3d(offset_x, 40.0 + breathe_r, 100.0, cx, cy, fl, cam_z, pitch, yaw)
        if px_r is not None:
            panel_w = 180.0 * sc_r
            panel_h = 220.0 * sc_r
            x0 = px_r - panel_w / 2.0
            y0 = py_r - panel_h / 2.0

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(4, 14, 28, 150)))
            p.drawRoundedRect(int(x0), int(y0), int(panel_w), int(panel_h), 6, 6)

            # Glowing Corner Brackets
            p.setPen(QPen(QColor(0, 212, 255, 210), 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            br = 15.0
            p.drawLine(QPointF(x0, y0 + br), QPointF(x0, y0))
            p.drawLine(QPointF(x0, y0), QPointF(x0 + br, y0))
            p.drawLine(QPointF(x0 + panel_w - br, y0), QPointF(x0 + panel_w, y0))
            p.drawLine(QPointF(x0 + panel_w, y0), QPointF(x0 + panel_w, y0 + br))
            p.drawLine(QPointF(x0, y0 + panel_h - br), QPointF(x0, y0 + panel_h))
            p.drawLine(QPointF(x0, y0 + panel_h), QPointF(x0 + br, y0 + panel_h))
            p.drawLine(QPointF(x0 + panel_w - br, y0 + panel_h), QPointF(x0 + panel_w, y0 + panel_h))
            p.drawLine(QPointF(x0 + panel_w, y0 + panel_h - br), QPointF(x0 + panel_w, y0 + panel_h))

            # Header
            p.setPen(QColor(0, 212, 255, 230))
            p.drawText(int(x0 + 10), int(y0 + 20), "CAPABILITIES // 02")
            p.setPen(QPen(QColor(0, 212, 255, 100), 1.0))
            p.drawLine(QPointF(x0 + 8, y0 + 26), QPointF(x0 + panel_w - 8, y0 + 26))

            # Capabilities list
            right_tags = ["SPEECH", "VISION", "CONTEXT", "AUTOMATION"]
            for idx, tag in enumerate(right_tags):
                p.setPen(QColor(224, 242, 254, 210))
                p.drawText(int(x0 + 10), int(y0 + 50 + idx * 22), f"• {tag}")
                # Mini meter bar
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(0, 212, 255, 150)))
                m_w = 28.0 + 8.0 * math.sin(self._t * 2.0 + idx)
                p.drawRect(int(x0 + panel_w - 44), int(y0 + 42 + idx * 22), int(m_w), 5)

            # Circular Radar / Gyroscope Reticle
            rc_x = x0 + panel_w / 2.0
            rc_y = y0 + 172.0
            rc_r = 28.0

            p.setPen(QPen(QColor(0, 212, 255, 130), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(rc_x, rc_y), rc_r, rc_r)
            p.drawEllipse(QPointF(rc_x, rc_y), rc_r * 0.4, rc_r * 0.4)

            # Rotating crosshairs
            rad_ang = self._t * 1.8
            p.drawLine(QPointF(rc_x - rc_r * math.cos(rad_ang), rc_y - rc_r * math.sin(rad_ang)),
                       QPointF(rc_x + rc_r * math.cos(rad_ang), rc_y + rc_r * math.sin(rad_ang)))

            scan_y = y0 + ((self._t * 45.0 + 50.0) % panel_h)
            p.setPen(QPen(QColor(0, 212, 255, 120), 1.0))
            p.drawLine(QPointF(x0 + 4, scan_y), QPointF(x0 + panel_w - 4, scan_y))

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: MIDGROUND PARTICLES (LAYER B)
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_mid_particles(self, p: QPainter, cx: float, cy: float,
                            fl: float, cam_z: float, yaw: float, pitch: float):
        p.setPen(Qt.PenStyle.NoPen)
        for pt in self._mid_particles:
            px, py, scale = _project_3d(pt['x'], pt['y'], pt['z'], cx, cy, fl, cam_z, pitch, yaw)
            if px is None:
                continue

            pulse = 0.8 + 0.2 * math.sin(self._t * 2.2 + pt['phase'])
            alpha = int(pt['alpha'] * pulse * 255)
            if alpha <= 0:
                continue

            sz = max(1.2, pt['size'] * scale * 1.8)
            p.setBrush(QBrush(QColor(0, 212, 255, alpha)))
            p.drawEllipse(QPointF(px, py), sz, sz)

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: FOREGROUND GLOWING BOKEH ORBS (LAYER C)
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_foreground_orbs(self, p: QPainter, cx: float, cy: float,
                             fl: float, cam_z: float, yaw: float, pitch: float):
        p.setPen(Qt.PenStyle.NoPen)
        for orb in self._fg_orbs:
            px, py, scale = _project_3d(orb['x'], orb['y'], orb['z'], cx, cy, fl, cam_z, pitch, yaw)
            if px is None:
                continue
            pulse = 0.8 + 0.2 * math.sin(self._t * 1.8 + orb['phase'])
            rad = orb['size'] * scale * 2.4
            orb_grad = QRadialGradient(px, py, rad)
            orb_grad.setColorAt(0.0, QColor(255, 255, 255, int(190 * pulse)))
            orb_grad.setColorAt(0.4, QColor(0, 212, 255, int(110 * pulse)))
            orb_grad.setColorAt(1.0, QColor(0, 212, 255, 0))
            p.setBrush(QBrush(orb_grad))
            p.drawEllipse(QPointF(px, py), rad, rad)

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: SOPHISTICATED CENTRAL AI CORE (HIGH IMPACT)
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_central_ai_core(self, p: QPainter, cx: float, cy: float,
                              fl: float, cam_z: float, yaw: float, pitch: float):
        """
        Renders the majestic central AI Core crowning above the authentication controls:
        - Radiant white-hot singularity core + multi-stop corona halo
        - Vertical luminous reactor energy beam
        - Rotating 3D crystalline double-octahedron cage
        - 60-tick rotating HUD reticle ring
        - 4 massive multi-axis 3D orbital rings (radii 170 to 480px)
        - Orbiting quantum sparks swarm
        - Expanding 3D energy shockwave pulses
        """
        core_x = 0.0
        core_y = -180.0   # Elevated to crown majestically above the authentication hub
        core_z = 80.0

        px, py, scale = _project_3d(core_x, core_y, core_z, cx, cy, fl, cam_z, pitch, yaw)
        if px is None:
            return

        speed_mult = 1.0 + self._focus_intensity * 0.50
        t_spin = self._t * speed_mult

        # ── 1. Vertical Luminous Reactor Energy Beam ──
        p_top_x, p_top_y, _ = _project_3d(core_x, -440.0, core_z, cx, cy, fl, cam_z, pitch, yaw)
        p_bot_x, p_bot_y, _ = _project_3d(core_x, 220.0, core_z, cx, cy, fl, cam_z, pitch, yaw)
        if p_top_x is not None and p_bot_x is not None:
            beam_grad = QLinearGradient(QPointF(px - 18, py), QPointF(px + 18, py))
            beam_grad.setColorAt(0.0, QColor(0, 212, 255, 0))
            beam_grad.setColorAt(0.5, QColor(0, 212, 255, int(50 + 35 * self._focus_intensity)))
            beam_grad.setColorAt(1.0, QColor(0, 212, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(beam_grad))
            p.drawRect(int(px - 16), int(p_top_y), 32, int(p_bot_y - p_top_y))

            # Core white energy hairline laser
            p.setPen(QPen(QColor(255, 255, 255, int(190 + 65 * self._focus_intensity)), 1.4))
            p.drawLine(QPointF(p_top_x, p_top_y), QPointF(p_bot_x, p_bot_y))

        # ── 2. Expanding 3D Shockwave Pulses (Periodic System Event) ──
        shock_cycle = (self._t % 6.0) / 6.0
        if shock_cycle < 0.45:
            shock_prog = shock_cycle / 0.45
            shock_rad = 60.0 + shock_prog * 520.0
            shock_alpha = int((1.0 - shock_prog) * 130)
            self._render_3d_ring(p, cx, cy, fl, cam_z, yaw, pitch,
                                r=shock_rad, rot_y=0, tilt_x=0.55, tilt_z=0,
                                center=(core_x, core_y, core_z),
                                color=QColor(0, 212, 255, shock_alpha),
                                width=1.8, dash=True, has_node=False)

        # ── 3. Multi-Stop Radiant Core Corona ──
        breathe = 0.88 + 0.12 * math.sin(self._t * 2.8)
        corona_r = (190.0 + 55.0 * self._focus_intensity) * breathe * scale
        corona = QRadialGradient(px, py, corona_r)
        c_alpha = int((105 + 45 * self._focus_intensity) * breathe)
        corona.setColorAt(0.00, QColor(255, 255, 255, 255))
        corona.setColorAt(0.12, QColor(0, 235, 255, c_alpha))
        corona.setColorAt(0.35, QColor(0, 165, 255, int(c_alpha * 0.70)))
        corona.setColorAt(0.70, QColor(20, 70, 190, int(c_alpha * 0.30)))
        corona.setColorAt(1.00, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(corona))
        p.drawEllipse(QPointF(px, py), corona_r, corona_r)

        # ── 4. 3D Rotating Crystalline Polyhedron Cage ──
        self._draw_octahedron_cage(p, cx, cy, fl, cam_z, yaw, pitch,
                                  core_x, core_y, core_z, t_spin)

        # ── 5. 60-Tick Rotating HUD Reticle Ring ──
        hud_r = 120.0
        hud_rot = t_spin * 0.6
        p.setPen(QPen(QColor(0, 212, 255, int(170 + 60 * self._focus_intensity)), 1.2))
        for tick_i in range(48):
            ang = math.radians(tick_i * (360.0 / 48)) + hud_rot
            r_in = hud_r - (6.0 if tick_i % 4 == 0 else 3.0)
            r_out = hud_r
            t1_x, t1_y, _ = _project_3d(r_in * math.cos(ang), core_y, r_in * math.sin(ang) * 0.4 + core_z, cx, cy, fl, cam_z, pitch, yaw)
            t2_x, t2_y, _ = _project_3d(r_out * math.cos(ang), core_y, r_out * math.sin(ang) * 0.4 + core_z, cx, cy, fl, cam_z, pitch, yaw)
            if t1_x is not None and t2_x is not None:
                p.drawLine(QPointF(t1_x, t1_y), QPointF(t2_x, t2_y))

        # ── 6. Core Quantum Spark Swarm ──
        swarm_count = 24
        p.setPen(Qt.PenStyle.NoPen)
        for s_idx in range(swarm_count):
            s_ang = t_spin * 2.6 + s_idx * (math.pi * 2.0 / swarm_count)
            s_rad = 72.0 + 24.0 * math.sin(self._t * 1.8 + s_idx * 1.2)
            sx = s_rad * math.cos(s_ang)
            sy = s_rad * math.sin(s_ang) * math.cos(0.65)
            sz = s_rad * math.sin(s_ang) * math.sin(0.65)
            sp_x, sp_y, s_scale = _project_3d(sx + core_x, sy + core_y, sz + core_z,
                                              cx, cy, fl, cam_z, pitch, yaw)
            if sp_x is not None:
                p.setBrush(QBrush(QColor(255, 255, 255, int(220 + 35 * self._focus_intensity))))
                p.drawEllipse(QPointF(sp_x, sp_y), 2.8 * s_scale * 1.5, 2.8 * s_scale * 1.5)

        # ── 7. Multi-Axis 3D Orbital Rings (Wide & Panoramic) ──
        # Ring 1: Tilted at 65° X-axis, rotating clockwise
        self._render_3d_ring(p, cx, cy, fl, cam_z, yaw, pitch,
                            r=170.0, rot_y=t_spin * 0.85, tilt_x=1.15, tilt_z=0.15,
                            center=(core_x, core_y, core_z),
                            color=QColor(0, 212, 255, int(190 + 65 * self._focus_intensity)),
                            width=1.6, dash=False, has_node=True)

        # Ring 2: Tilted at -50° X-axis, 35° Z-axis, counter-rotating
        self._render_3d_ring(p, cx, cy, fl, cam_z, yaw, pitch,
                            r=245.0, rot_y=-t_spin * 0.60, tilt_x=-0.85, tilt_z=0.60,
                            center=(core_x, core_y, core_z),
                            color=QColor(0, 240, 255, int(160 + 65 * self._focus_intensity)),
                            width=1.4, dash=True, has_node=True)

        # Ring 3: Tilted at 30° X-axis, -55° Z-axis
        self._render_3d_ring(p, cx, cy, fl, cam_z, yaw, pitch,
                            r=340.0, rot_y=t_spin * 0.40, tilt_x=0.55, tilt_z=-0.95,
                            center=(core_x, core_y, core_z),
                            color=QColor(0, 180, 255, int(130 + 55 * self._focus_intensity)),
                            width=1.2, dash=True, has_node=True)

        # Ring 4: Grand outer celestial perimeter ring with traveling spark
        self._render_3d_ring(p, cx, cy, fl, cam_z, yaw, pitch,
                            r=480.0, rot_y=-t_spin * 0.28, tilt_x=0.35, tilt_z=0.20,
                            center=(core_x, core_y, core_z),
                            color=QColor(0, 212, 255, int(95 + 45 * self._focus_intensity)),
                            width=1.1, dash=True, has_node=True)

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: 3D CRYSTALLINE OCTAHEDRON CAGE
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_octahedron_cage(self, p: QPainter, cx: float, cy: float,
                              fl: float, cam_z: float, yaw: float, pitch: float,
                              ox: float, oy: float, oz: float, t_spin: float):
        """Renders geometric crystalline wireframe cage rotating inside the core."""
        # 1. Outer Octahedron
        rot_y = t_spin * 0.85
        rot_x = t_spin * 0.55
        cos_y = math.cos(rot_y)
        sin_y = math.sin(rot_y)
        cos_x = math.cos(rot_x)
        sin_x = math.sin(rot_x)

        projected_verts = []
        for vx, vy, vz in self._octahedron_verts:
            x1 = vx * cos_y + vz * sin_y
            z1 = -vx * sin_y + vz * cos_y
            y2 = vy * cos_x - z1 * sin_x
            z2 = vy * sin_x + z1 * cos_x

            px, py, _ = _project_3d(x1 + ox, y2 + oy, z2 + oz, cx, cy, fl, cam_z, pitch, yaw)
            projected_verts.append((px, py))

        # Wireframe edges
        p.setPen(QPen(QColor(0, 212, 255, int(190 + 65 * self._focus_intensity)), 1.5))
        for v1_idx, v2_idx in self._octahedron_edges:
            p1 = projected_verts[v1_idx]
            p2 = projected_verts[v2_idx]
            if p1[0] is not None and p2[0] is not None:
                p.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

        # Glowing vertex nodes
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255, int(230 + 25 * self._focus_intensity))))
        for px, py in projected_verts:
            if px is not None:
                p.drawEllipse(QPointF(px, py), 3.2, 3.2)

        # 2. Counter-Rotating Inner Octahedron
        rot_y2 = -t_spin * 1.10
        rot_x2 = -t_spin * 0.70
        cos_y2 = math.cos(rot_y2)
        sin_y2 = math.sin(rot_y2)
        cos_x2 = math.cos(rot_x2)
        sin_x2 = math.sin(rot_x2)

        in_verts = []
        for vx, vy, vz in self._inner_verts:
            x1 = vx * cos_y2 + vz * sin_y2
            z1 = -vx * sin_y2 + vz * cos_y2
            y2 = vy * cos_x2 - z1 * sin_x2
            z2 = vy * sin_x2 + z1 * cos_x2
            px, py, _ = _project_3d(x1 + ox, y2 + oy, z2 + oz, cx, cy, fl, cam_z, pitch, yaw)
            in_verts.append((px, py))

        p.setPen(QPen(QColor(255, 255, 255, int(200 + 55 * self._focus_intensity)), 1.1))
        for v1_idx, v2_idx in self._octahedron_edges:
            p1 = in_verts[v1_idx]
            p2 = in_verts[v2_idx]
            if p1[0] is not None and p2[0] is not None:
                p.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

    # ─────────────────────────────────────────────────────────────────────────
    # 3D ROTATING RING HELPER
    # ─────────────────────────────────────────────────────────────────────────
    def _render_3d_ring(self, p: QPainter, cx: float, cy: float, fl: float, cam_z: float,
                        yaw: float, pitch: float, r: float, rot_y: float, tilt_x: float, tilt_z: float,
                        center: tuple[float, float, float], color: QColor,
                        width: float = 1.0, dash: bool = False, has_node: bool = False):
        segments = 36
        cos_ry = math.cos(rot_y)
        sin_ry = math.sin(rot_y)
        cos_tx = math.cos(tilt_x)
        sin_tx = math.sin(tilt_x)
        cos_tz = math.cos(tilt_z)
        sin_tz = math.sin(tilt_z)

        ring_poly = QPolygonF()
        node_pos = None
        node_seg = int((self._t * 14.0) % segments)

        for s in range(segments + 1):
            ang = math.radians(s * (360.0 / segments))
            lx = r * math.cos(ang)
            ly = 0.0
            lz = r * math.sin(ang)

            # Rotate Y
            x1 = lx * cos_ry + lz * sin_ry
            z1 = -lx * sin_ry + lz * cos_ry

            # Tilt X
            y2 = ly * cos_tx - z1 * sin_tx
            z2 = ly * sin_tx + z1 * cos_tx

            # Tilt Z
            x3 = x1 * cos_tz - y2 * sin_tz
            y3 = x1 * sin_tz + y2 * cos_tz

            px, py, _ = _project_3d(x3 + center[0], y3 + center[1], z2 + center[2],
                                    cx, cy, fl, cam_z, pitch, yaw)
            if px is not None:
                ring_poly.append(QPointF(px, py))
                if has_node and s == node_seg:
                    node_pos = QPointF(px, py)

        if len(ring_poly) > 2:
            pen_style = Qt.PenStyle.DashLine if dash else Qt.PenStyle.SolidLine
            p.setPen(QPen(color, width, pen_style))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(ring_poly)

        if node_pos is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, 255)))
            p.drawEllipse(node_pos, 3.5, 3.5)
            p.setBrush(QBrush(QColor(0, 212, 255, 150)))
            p.drawEllipse(node_pos, 7.5, 7.5)



# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM FOCUS-AWARE INPUT
# ─────────────────────────────────────────────────────────────────────────────
class ReactiveInputField(QLineEdit):
    focus_changed = pyqtSignal(bool)

    def focusInEvent(self, e: QFocusEvent):
        super().focusInEvent(e)
        self.focus_changed.emit(True)

    def focusOutEvent(self, e: QFocusEvent):
        super().focusOutEvent(e)
        self.focus_changed.emit(False)


# ─────────────────────────────────────────────────────────────────────────────
# ELEGANT NAVIGATION CONTROL (NO HEAVY CARDS)
# ─────────────────────────────────────────────────────────────────────────────
class MinimalNavItem(QFrame):
    """
    High-visibility interactive navigation row with deep cyber glass backing.
    Guarantees 100% crisp legibility over radiant 3D background graphics.
    """
    clicked = pyqtSignal()

    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("MinimalNavItem")
        self.setFixedHeight(66)

        self._normal_style = """
            QFrame#MinimalNavItem {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(8, 22, 38, 0.94),
                    stop:1 rgba(6, 16, 28, 0.94));
                border: 1px solid rgba(0, 212, 255, 0.32);
                border-radius: 12px;
            }
        """
        self._hover_style = """
            QFrame#MinimalNavItem {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(14, 38, 68, 0.98),
                    stop:1 rgba(8, 26, 48, 0.98));
                border: 1px solid rgba(0, 212, 255, 0.75);
                border-radius: 12px;
            }
        """
        self.setStyleSheet(self._normal_style)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 10, 20, 10)
        lay.setSpacing(14)

        text_lay = QVBoxLayout()
        text_lay.setContentsMargins(0, 0, 0, 0)
        text_lay.setSpacing(3)
        text_lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._title = QLabel(title)
        self._title.setFont(F.ui(14, bold=True))
        self._title.setStyleSheet("color: #ffffff; font-weight: 700; letter-spacing: 0.2px; background: transparent; border: none;")
        text_lay.addWidget(self._title)

        self._sub = QLabel(subtitle)
        self._sub.setFont(F.ui(12))
        self._sub.setStyleSheet("color: #cbd5e1; font-weight: 400; background: transparent; border: none;")
        text_lay.addWidget(self._sub)

        lay.addLayout(text_lay, stretch=1)

        self._arrow = QLabel("→")
        self._arrow.setFont(F.ui(16, bold=True))
        self._arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._arrow.setStyleSheet("color: #00d4ff; font-weight: 700; background: transparent; border: none;")
        lay.addWidget(self._arrow)

    def enterEvent(self, e):
        super().enterEvent(e)
        self.setStyleSheet(self._hover_style)
        self._arrow.setStyleSheet("color: #ffffff; font-weight: 700; background: transparent; border: none;")
        self._sub.setStyleSheet("color: #f0f9ff; font-weight: 500; background: transparent; border: none;")

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.setStyleSheet(self._normal_style)
        self._arrow.setStyleSheet("color: #00d4ff; font-weight: 700; background: transparent; border: none;")
        self._sub.setStyleSheet("color: #cbd5e1; font-weight: 400; background: transparent; border: none;")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)



# ─────────────────────────────────────────────────────────────────────────────
# VIEW 0: MINIMAL IMMERSIVE WELCOME HUB
# ─────────────────────────────────────────────────────────────────────────────
class WelcomeHubView(QWidget):
    signin_requested = pyqtSignal()
    signup_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 1. Product Name Badge
        name_lbl = QLabel("TREVON LABS")
        name_lbl.setFont(F.mono(10))
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("""
            color: #38bdf8;
            font-weight: 700;
            letter-spacing: 2.2px;
            background: transparent;
            border: none;
        """)
        lay.addWidget(name_lbl)
        lay.addSpacing(10)

        # 2. Core Statement
        stmt_lbl = QLabel("Your intelligent assistant, ready when you are.")
        stmt_lbl.setFont(F.ui(22, bold=True))
        stmt_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stmt_lbl.setStyleSheet("color: #f8fafc; letter-spacing: -0.4px; background: transparent; border: none;")
        lay.addWidget(stmt_lbl)
        lay.addSpacing(6)

        # 3. Prompt
        prompt_lbl = QLabel("How would you like to begin?")
        prompt_lbl.setFont(F.ui(13))
        prompt_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prompt_lbl.setStyleSheet("color: #94a3b8; background: transparent; border: none;")
        lay.addWidget(prompt_lbl)
        lay.addSpacing(28)

        # 4. Choices Container
        choices = QWidget()
        choices.setFixedWidth(380)
        c_lay = QVBoxLayout(choices)
        c_lay.setContentsMargins(0, 0, 0, 0)
        c_lay.setSpacing(14)

        nav_signin = MinimalNavItem("Sign In", "Continue with your account")
        nav_signin.clicked.connect(self.signin_requested.emit)
        c_lay.addWidget(nav_signin)

        nav_signup = MinimalNavItem("Create Account", "Start a personalized account")
        nav_signup.clicked.connect(self.signup_requested.emit)
        c_lay.addWidget(nav_signup)

        lay.addWidget(choices, alignment=Qt.AlignmentFlag.AlignCenter)


# ─────────────────────────────────────────────────────────────────────────────
# VIEW 1: SIGN IN VIEW
# ─────────────────────────────────────────────────────────────────────────────
class SignInView(QWidget):
    back_requested = pyqtSignal()
    submit_requested = pyqtSignal(str, str)
    switch_to_signup = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(380)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        back_btn = QPushButton("← Back")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #94a3b8;
                border: none;
                font-size: 11px;
                font-weight: 600;
                text-align: left;
                padding: 0;
            }
            QPushButton:hover { color: #38bdf8; }
        """)
        back_btn.clicked.connect(self.back_requested.emit)
        lay.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        lay.addSpacing(6)

        title = QLabel("Sign In")
        title.setFont(F.ui(22, bold=True))
        title.setStyleSheet("color: #f8fafc; background: transparent; border: none;")
        lay.addWidget(title)

        sub = QLabel("Enter your username and password to continue.")
        sub.setFont(F.ui(12))
        sub.setStyleSheet("color: #94a3b8; background: transparent; border: none;")
        lay.addWidget(sub)

        lay.addSpacing(8)

        u_lbl = QLabel("USERNAME")
        u_lbl.setFont(F.mono(9))
        u_lbl.setStyleSheet("color: #64748b; font-weight: 700; letter-spacing: 0.8px; background: transparent; border: none;")
        lay.addWidget(u_lbl)

        self._username = ReactiveInputField()
        self._username.setPlaceholderText("Enter your username")
        self._username.setFixedHeight(42)
        self._username.setStyleSheet(self._input_style())
        self._username.returnPressed.connect(self._on_submit)
        lay.addWidget(self._username)

        p_lbl = QLabel("PASSWORD")
        p_lbl.setFont(F.mono(9))
        p_lbl.setStyleSheet("color: #64748b; font-weight: 700; letter-spacing: 0.8px; background: transparent; border: none;")
        lay.addWidget(p_lbl)

        self._password = ReactiveInputField()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("••••••••")
        self._password.setFixedHeight(42)
        self._password.setStyleSheet(self._input_style())
        self._password.returnPressed.connect(self._on_submit)
        lay.addWidget(self._password)

        self._err = QLabel("")
        self._err.setFont(F.ui(11))
        self._err.setStyleSheet("color: #f87171; background: transparent; border: none;")
        self._err.setWordWrap(True)
        self._err.hide()
        lay.addWidget(self._err)

        lay.addSpacing(4)

        self._btn_submit = QPushButton("Sign In →")
        self._btn_submit.setFixedHeight(44)
        self._btn_submit.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_submit.setStyleSheet(self._btn_style())
        self._btn_submit.clicked.connect(self._on_submit)
        lay.addWidget(self._btn_submit)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 8, 0, 0)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        signup_link = QPushButton("Create an account")
        signup_link.setCursor(Qt.CursorShape.PointingHandCursor)
        signup_link.setStyleSheet("background: transparent; color: #38bdf8; border: none; font-size: 11px;")
        signup_link.clicked.connect(self.switch_to_signup.emit)

        footer.addWidget(signup_link)
        lay.addLayout(footer)

    def _input_style(self) -> str:
        return f"""
            QLineEdit {{
                background: rgba(255, 255, 255, 0.04);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.11);
                border-radius: {Radius.SM}px;
                padding: 8px 12px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 1.5px solid #38bdf8;
                background: rgba(56, 189, 248, 0.05);
            }}
        """

    def _btn_style(self) -> str:
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0284c7, stop:1 #0ea5e9);
                color: #ffffff;
                border: 1px solid rgba(56, 189, 248, 0.35);
                border-radius: {Radius.SM}px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0369a1, stop:1 #38bdf8);
            }}
            QPushButton:disabled {{
                background: #1e293b;
                color: #64748b;
                border-color: #334155;
            }}
        """

    def _on_submit(self):
        u = self._username.text().strip()
        p = self._password.text().strip()
        if not u:
            self.show_error("Please enter your username.")
            return
        if not p:
            self.show_error("Please enter your password.")
            return
        self.clear_error()
        self.submit_requested.emit(u, p)

    def show_error(self, msg: str):
        self._err.setText(f"⚠ {msg}")
        self._err.show()

    def clear_error(self):
        self._err.hide()
        self._err.setText("")

    def clear_fields(self):
        self._username.clear()
        self._password.clear()

    def set_loading(self, loading: bool):
        self._btn_submit.setEnabled(not loading)
        self._btn_submit.setText("Signing In..." if loading else "Sign In →")


# ─────────────────────────────────────────────────────────────────────────────
# VIEW 2: CREATE ACCOUNT VIEW
# ─────────────────────────────────────────────────────────────────────────────
class SignUpView(QWidget):
    back_requested = pyqtSignal()
    submit_requested = pyqtSignal(str, str, str)
    switch_to_login = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(380)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(9)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        back_btn = QPushButton("← Back")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #94a3b8;
                border: none;
                font-size: 11px;
                font-weight: 600;
                text-align: left;
                padding: 0;
            }
            QPushButton:hover { color: #38bdf8; }
        """)
        back_btn.clicked.connect(self.back_requested.emit)
        lay.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        lay.addSpacing(4)

        title = QLabel("Create Account")
        title.setFont(F.ui(22, bold=True))
        title.setStyleSheet("color: #f8fafc; background: transparent; border: none;")
        lay.addWidget(title)

        sub = QLabel("Save your preferences, memory, and settings.")
        sub.setFont(F.ui(12))
        sub.setStyleSheet("color: #94a3b8; background: transparent; border: none;")
        lay.addWidget(sub)

        lay.addSpacing(6)

        u_lbl = QLabel("USERNAME")
        u_lbl.setFont(F.mono(9))
        u_lbl.setStyleSheet("color: #64748b; font-weight: 700; letter-spacing: 0.8px; background: transparent; border: none;")
        lay.addWidget(u_lbl)

        self._username = ReactiveInputField()
        self._username.setPlaceholderText("Choose a username")
        self._username.setFixedHeight(40)
        self._username.setStyleSheet(self._input_style())
        lay.addWidget(self._username)

        p_lbl = QLabel("PASSWORD")
        p_lbl.setFont(F.mono(9))
        p_lbl.setStyleSheet("color: #64748b; font-weight: 700; letter-spacing: 0.8px; background: transparent; border: none;")
        lay.addWidget(p_lbl)

        self._password = ReactiveInputField()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("At least 3 characters")
        self._password.setFixedHeight(40)
        self._password.setStyleSheet(self._input_style())
        lay.addWidget(self._password)

        cp_lbl = QLabel("CONFIRM PASSWORD")
        cp_lbl.setFont(F.mono(9))
        cp_lbl.setStyleSheet("color: #64748b; font-weight: 700; letter-spacing: 0.8px; background: transparent; border: none;")
        lay.addWidget(cp_lbl)

        self._confirm = ReactiveInputField()
        self._confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self._confirm.setPlaceholderText("Re-type password")
        self._confirm.setFixedHeight(40)
        self._confirm.setStyleSheet(self._input_style())
        self._confirm.returnPressed.connect(self._on_submit)
        lay.addWidget(self._confirm)

        self._err = QLabel("")
        self._err.setFont(F.ui(11))
        self._err.setStyleSheet("color: #f87171; background: transparent; border: none;")
        self._err.setWordWrap(True)
        self._err.hide()
        lay.addWidget(self._err)

        self._btn_submit = QPushButton("Create Account →")
        self._btn_submit.setFixedHeight(44)
        self._btn_submit.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_submit.setStyleSheet(self._btn_style())
        self._btn_submit.clicked.connect(self._on_submit)
        lay.addWidget(self._btn_submit)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 8, 0, 0)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        login_link = QPushButton("Already have an account? Sign In")
        login_link.setCursor(Qt.CursorShape.PointingHandCursor)
        login_link.setStyleSheet("background: transparent; color: #38bdf8; border: none; font-size: 11px;")
        login_link.clicked.connect(self.switch_to_login.emit)

        footer.addWidget(login_link)
        lay.addLayout(footer)

    def _input_style(self) -> str:
        return f"""
            QLineEdit {{
                background: rgba(255, 255, 255, 0.04);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.11);
                border-radius: {Radius.SM}px;
                padding: 7px 12px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 1.5px solid #38bdf8;
                background: rgba(56, 189, 248, 0.05);
            }}
        """

    def _btn_style(self) -> str:
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0284c7, stop:1 #0ea5e9);
                color: #ffffff;
                border: 1px solid rgba(56, 189, 248, 0.35);
                border-radius: {Radius.SM}px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0369a1, stop:1 #38bdf8);
            }}
            QPushButton:disabled {{
                background: #1e293b;
                color: #64748b;
                border-color: #334155;
            }}
        """

    def _on_submit(self):
        u = self._username.text().strip()
        p = self._password.text().strip()
        cp = self._confirm.text().strip()
        if not u:
            self.show_error("Please choose a username.")
            return
        if len(u) < 2:
            self.show_error("Username must be at least 2 characters.")
            return
        if not p:
            self.show_error("Please enter a password.")
            return
        if len(p) < 3:
            self.show_error("Password must be at least 3 characters.")
            return
        if p != cp:
            self.show_error("Passwords do not match. Please re-enter.")
            return
        self.clear_error()
        self.submit_requested.emit(u, p, cp)

    def show_error(self, msg: str):
        self._err.setText(f"⚠ {msg}")
        self._err.show()

    def clear_error(self):
        self._err.hide()
        self._err.setText("")

    def clear_fields(self):
        self._username.clear()
        self._password.clear()
        self._confirm.clear()

    def set_loading(self, loading: bool):
        self._btn_submit.setEnabled(not loading)
        self._btn_submit.setText("Creating Account..." if loading else "Create Account →")


# ─────────────────────────────────────────────────────────────────────────────
# VIEW 3: ONBOARDING STEP 1 — NAME YOUR ASSISTANT
# ─────────────────────────────────────────────────────────────────────────────
class SetupNameView(QWidget):
    name_submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(380)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        badge = QLabel("STEP 1 OF 2")
        badge.setFont(F.mono(9))
        badge.setStyleSheet("""
            color: #38bdf8;
            background: rgba(56, 189, 248, 0.08);
            border: 1px solid rgba(56, 189, 248, 0.25);
            border-radius: 8px;
            padding: 3px 8px;
            font-weight: 700;
        """)
        lay.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)

        title = QLabel("Name Your Assistant")
        title.setFont(F.ui(22, bold=True))
        title.setStyleSheet("color: #f8fafc; background: transparent; border: none;")
        lay.addWidget(title)

        desc = QLabel(
            "Choose a name for your personal assistant to get started.\n"
            "You can always customize this later in settings."
        )
        desc.setFont(F.ui(12))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94a3b8; background: transparent; border: none;")
        lay.addWidget(desc)

        lay.addSpacing(8)

        lbl = QLabel("ASSISTANT NAME")
        lbl.setFont(F.mono(9))
        lbl.setStyleSheet("color: #64748b; font-weight: 700; letter-spacing: 0.8px; background: transparent; border: none;")
        lay.addWidget(lbl)

        self._input = ReactiveInputField()
        self._input.setPlaceholderText("e.g. Trevon, Athena, Orion...")
        self._input.setFixedHeight(44)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(255, 255, 255, 0.04);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.11);
                border-radius: {Radius.SM}px;
                padding: 10px 14px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 1.5px solid #38bdf8;
                background: rgba(56, 189, 248, 0.05);
            }}
        """)
        self._input.returnPressed.connect(self._on_submit)
        lay.addWidget(self._input)

        self._err = QLabel("")
        self._err.setFont(F.ui(11))
        self._err.setStyleSheet("color: #f87171; background: transparent; border: none;")
        self._err.hide()
        lay.addWidget(self._err)

        lay.addSpacing(6)

        btn = QPushButton("Save & Continue →")
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0284c7, stop:1 #0ea5e9);
                color: #ffffff;
                border: 1px solid rgba(56, 189, 248, 0.35);
                border-radius: {Radius.SM}px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0369a1, stop:1 #38bdf8);
            }}
        """)
        btn.clicked.connect(self._on_submit)
        lay.addWidget(btn)

    def _on_submit(self):
        val = self._input.text().strip()
        if not val:
            self._err.setText("⚠ Please enter a name for your assistant.")
            self._err.show()
            return
        self._err.hide()
        self.name_submitted.emit(val)


# ─────────────────────────────────────────────────────────────────────────────
# VIEW 4: ONBOARDING STEP 2 — VOICE SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
_TONE_PROFILES = [
    ("Calm",         {"rate": 130, "volume": 0.9}),
    ("Professional", {"rate": 155, "volume": 1.0}),
    ("Friendly",     {"rate": 165, "volume": 1.0}),
    ("Energetic",    {"rate": 185, "volume": 1.0}),
    ("Soft",         {"rate": 125, "volume": 0.75}),
]


class SetupVoiceView(QWidget):
    voice_submitted = pyqtSignal(dict)

    def __init__(self, assistant_name: str = "your assistant", parent=None):
        super().__init__(parent)
        self._assistant_name = assistant_name or "your assistant"
        self._all_voices: list[dict] = []
        self._selected_gender = "male"
        self.setFixedWidth(380)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        badge = QLabel("STEP 2 OF 2")
        badge.setFont(F.mono(9))
        badge.setStyleSheet("""
            color: #38bdf8;
            background: rgba(56, 189, 248, 0.08);
            border: 1px solid rgba(56, 189, 248, 0.25);
            border-radius: 8px;
            padding: 3px 8px;
            font-weight: 700;
        """)
        lay.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)

        self._title = QLabel("Voice Settings")
        self._title.setFont(F.ui(22, bold=True))
        self._title.setStyleSheet("color: #f8fafc; background: transparent; border: none;")
        lay.addWidget(self._title)

        sub = QLabel("Choose how you'd like your assistant to sound.")
        sub.setFont(F.ui(12))
        sub.setStyleSheet("color: #94a3b8; background: transparent; border: none;")
        lay.addWidget(sub)

        # Gender Selector
        g_lbl = QLabel("VOICE GENDER")
        g_lbl.setFont(F.mono(9))
        g_lbl.setStyleSheet("color: #64748b; font-weight: 700; letter-spacing: 0.8px; background: transparent; border: none;")
        lay.addWidget(g_lbl)

        gender_row = QHBoxLayout()
        gender_row.setSpacing(10)
        self._btn_male   = QPushButton("♂  Male")
        self._btn_female = QPushButton("♀  Female")
        for btn in (self._btn_male, self._btn_female):
            btn.setFixedHeight(38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(F.ui(12, bold=True))
            btn.setCheckable(True)
        self._btn_male.setChecked(True)
        self._update_gender_styles()
        self._btn_male.clicked.connect(lambda: self._select_gender("male"))
        self._btn_female.clicked.connect(lambda: self._select_gender("female"))
        gender_row.addWidget(self._btn_male)
        gender_row.addWidget(self._btn_female)
        lay.addLayout(gender_row)

        # Voice Selector
        v_lbl = QLabel("VOICE")
        v_lbl.setFont(F.mono(9))
        v_lbl.setStyleSheet("color: #64748b; font-weight: 700; letter-spacing: 0.8px; background: transparent; border: none;")
        lay.addWidget(v_lbl)

        self._voice_combo = QComboBox()
        self._voice_combo.setFixedHeight(38)
        self._voice_combo.setFont(F.ui(11))
        self._voice_combo.setStyleSheet(self._combo_style())
        self._voice_combo.addItem("Loading voices...")
        lay.addWidget(self._voice_combo)

        # Tone Selector
        t_lbl = QLabel("SPEAKING STYLE")
        t_lbl.setFont(F.mono(9))
        t_lbl.setStyleSheet("color: #64748b; font-weight: 700; letter-spacing: 0.8px; background: transparent; border: none;")
        lay.addWidget(t_lbl)

        self._tone_combo = QComboBox()
        self._tone_combo.setFixedHeight(38)
        self._tone_combo.setFont(F.ui(11))
        self._tone_combo.setStyleSheet(self._combo_style())
        for tone_name, _ in _TONE_PROFILES:
            self._tone_combo.addItem(tone_name)
        self._tone_combo.setCurrentIndex(1)
        lay.addWidget(self._tone_combo)

        # Status
        self._status_lbl = QLabel("")
        self._status_lbl.setFont(F.ui(10))
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet("color: #38bdf8; background: transparent; border: none;")
        self._status_lbl.hide()
        lay.addWidget(self._status_lbl)

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._preview_btn = QPushButton("▶ Preview")
        self._preview_btn.setFixedHeight(42)
        self._preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview_btn.setFont(F.ui(12, bold=True))
        self._preview_btn.setStyleSheet("""
            QPushButton {
                background: rgba(56, 189, 248, 0.08);
                color: #38bdf8;
                border: 1px solid rgba(56, 189, 248, 0.28);
                border-radius: 8px;
            }
            QPushButton:hover { background: rgba(56, 189, 248, 0.16); }
        """)
        self._preview_btn.clicked.connect(self._preview_voice)
        btn_row.addWidget(self._preview_btn)

        self._continue_btn = QPushButton("Finish & Launch →")
        self._continue_btn.setFixedHeight(42)
        self._continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._continue_btn.setFont(F.ui(12, bold=True))
        self._continue_btn.setStyleSheet("""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0284c7, stop:1 #0ea5e9);
                color: #ffffff;
                border: 1px solid rgba(56, 189, 248, 0.35);
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0369a1, stop:1 #38bdf8);
            }}
        """)
        self._continue_btn.clicked.connect(self._on_continue)
        btn_row.addWidget(self._continue_btn)
        lay.addLayout(btn_row)

        self._load_voices_async()

    def update_name(self, name: str):
        self._assistant_name = name or "your assistant"

    def _combo_style(self) -> str:
        return f"""
            QComboBox {{
                background: rgba(255, 255, 255, 0.04);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.11);
                border-radius: {Radius.SM}px;
                padding: 6px 12px;
                font-family: '{F.PRIMARY}';
                font-size: 12px;
            }}
            QComboBox:focus {{ border: 1.5px solid #38bdf8; }}
            QComboBox QAbstractItemView {{
                background: #0f172a;
                color: #ffffff;
                selection-background-color: rgba(56, 189, 248, 0.20);
                border: 1px solid rgba(56, 189, 248, 0.25);
            }}
        """

    def _gender_btn_style(self, active: bool) -> str:
        if active:
            return """
                QPushButton {
                    background: rgba(56, 189, 248, 0.16);
                    color: #38bdf8;
                    border: 1.5px solid #38bdf8;
                    border-radius: 8px;
                }
            """
        return """
            QPushButton {
                background: rgba(255, 255, 255, 0.03);
                color: #64748b;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            QPushButton:hover {
                background: rgba(56, 189, 248, 0.05);
                color: #94a3b8;
            }
        """

    def _update_gender_styles(self):
        self._btn_male.setStyleSheet(self._gender_btn_style(self._selected_gender == "male"))
        self._btn_female.setStyleSheet(self._gender_btn_style(self._selected_gender == "female"))

    def _select_gender(self, gender: str):
        self._selected_gender = gender
        self._btn_male.setChecked(gender == "male")
        self._btn_female.setChecked(gender == "female")
        self._update_gender_styles()
        self._populate_voice_combo()

    def _load_voices_async(self):
        import threading
        def _worker():
            try:
                from legacy.tts import enumerate_voices
                voices = enumerate_voices()
            except Exception:
                voices = []
            QTimer.singleShot(0, lambda: self._on_voices_loaded(voices))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_voices_loaded(self, voices: list):
        self._all_voices = voices
        self._populate_voice_combo()

    def _populate_voice_combo(self):
        self._voice_combo.clear()
        filtered = [v for v in self._all_voices
                    if v.get("gender") in (self._selected_gender, "unknown")]
        if not filtered:
            filtered = self._all_voices
        if not filtered:
            self._voice_combo.addItem("System Default Voice", None)
            return
        for v in filtered:
            self._voice_combo.addItem(f"{v['name']}", v["id"])
        self._voice_combo.setCurrentIndex(0)

    def _get_selected_voice(self) -> tuple[str | None, str]:
        idx = self._voice_combo.currentIndex()
        if idx < 0:
            return None, ""
        return self._voice_combo.itemData(idx), self._voice_combo.currentText()

    def _get_tone_params(self) -> tuple[str, int, float]:
        idx = max(0, self._tone_combo.currentIndex())
        tone_name, params = _TONE_PROFILES[idx]
        return tone_name.lower(), params["rate"], params["volume"]

    def _preview_voice(self):
        vid, _  = self._get_selected_voice()
        tone_key, rate, volume = self._get_tone_params()
        name    = self._assistant_name
        preview_text = f"Hello. I'm {name}. It's great to meet you."

        self._preview_btn.setEnabled(False)
        self._status_lbl.setText("▶ Speaking preview...")
        self._status_lbl.show()

        def _speak():
            try:
                from legacy.tts import apply_voice_profile, _speak_pyttsx3
                apply_voice_profile(vid, rate=rate, volume=volume)
                _speak_pyttsx3(preview_text)
            except Exception as e:
                print(f"[VOICE SETUP] Preview error: {e}")
            QTimer.singleShot(0, self._preview_done)

        threading.Thread(target=_speak, daemon=True).start()

    def _preview_done(self):
        self._preview_btn.setEnabled(True)
        self._status_lbl.setText("✓ Preview complete")
        QTimer.singleShot(2500, lambda: self._status_lbl.hide())

    def _on_continue(self):
        vid, _ = self._get_selected_voice()
        tone_key, rate, volume = self._get_tone_params()
        profile = {
            "voice_id":     vid,
            "voice_gender": self._selected_gender,
            "voice_tone":   tone_key,
            "voice_rate":   rate,
            "voice_volume": volume,
        }
        self.voice_submitted.emit(profile)


# ─────────────────────────────────────────────────────────────────────────────
# REDESIGNED AUTHENTICATION WINDOW (3D IMMERSIVE COMMAND ENVIRONMENT)
# ─────────────────────────────────────────────────────────────────────────────
class LoginWindow(QWidget):
    """
    Futuristic 3D Cinematic AI Welcome Window.
    Hosts the living 3D environment canvas behind the clean, unbordered authentication stack.
    """
    login_complete = pyqtSignal(object, str, str)  # (user_id, username, session_mode)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trevon Labs")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)

        self._user_id = None
        self._username = None
        self._auth_thread: AuthThread | None = None

        # 1. Futuristic 3D Cinematic Canvas Background
        self._bg = Futuristic3DCanvas(self)
        self._bg.setGeometry(0, 0, self.width(), self.height())

        # 2. Borderless Floating Column (No heavy card enclosure)
        self._flow_container = QWidget(self)
        self._flow_container.setGeometry(0, 0, self.width(), self.height())
        self._flow_container.setStyleSheet("background: transparent;")
        self._flow_container.setMouseTracking(True)

        flow_lay = QVBoxLayout(self._flow_container)
        flow_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 3. View Switcher
        self._stack = QStackedWidget(self._flow_container)
        self._stack.setStyleSheet("background: transparent;")
        self._stack.setFixedWidth(420)

        self.welcome_view = WelcomeHubView(self._stack)
        self.signin_view = SignInView(self._stack)
        self.signup_view = SignUpView(self._stack)
        self.setup_name_view = SetupNameView(self._stack)
        self.setup_voice_view = SetupVoiceView(parent=self._stack)

        self._stack.addWidget(self.welcome_view)       # Index 0
        self._stack.addWidget(self.signin_view)        # Index 1
        self._stack.addWidget(self.signup_view)        # Index 2
        self._stack.addWidget(self.setup_name_view)    # Index 3
        self._stack.addWidget(self.setup_voice_view)   # Index 4

        flow_lay.addWidget(self._stack, alignment=Qt.AlignmentFlag.AlignCenter)

        # Connect Focus Sensitivity to 3D Background AI Core
        for input_field in (
            self.signin_view._username, self.signin_view._password,
            self.signup_view._username, self.signup_view._password, self.signup_view._confirm,
            self.setup_name_view._input
        ):
            input_field.focus_changed.connect(self._bg.set_focused)

        # Wire Welcome Hub
        self.welcome_view.signin_requested.connect(self._show_signin)
        self.welcome_view.signup_requested.connect(self._show_signup)

        # Wire Sign In
        self.signin_view.back_requested.connect(self._show_welcome)
        self.signin_view.switch_to_signup.connect(self._show_signup)
        self.signin_view.submit_requested.connect(self._on_login_submit)

        # Wire Sign Up
        self.signup_view.back_requested.connect(self._show_welcome)
        self.signup_view.switch_to_login.connect(self._show_signin)
        self.signup_view.submit_requested.connect(self._on_signup_submit)

        # Wire Onboarding
        self.setup_name_view.name_submitted.connect(self._on_name_submitted)
        self.setup_voice_view.voice_submitted.connect(self._on_voice_submitted)

        # 4. Smooth Entrance Fade
        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(450)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        if hasattr(self, '_bg') and self._bg:
            self._bg.setGeometry(0, 0, w, h)
        if hasattr(self, '_flow_container') and self._flow_container:
            self._flow_container.setGeometry(0, 0, w, h)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if hasattr(self, '_bg') and self._bg:
            self._bg.set_mouse_position(pos)

        if hasattr(self, '_drag_pos') and e.buttons() == Qt.MouseButton.LeftButton:
            delta = e.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = e.globalPosition().toPoint()

    # ── Flow Navigation ───────────────────────────────────────────────────────
    def _show_welcome(self):
        self.signin_view.clear_error()
        self.signup_view.clear_error()
        self._stack.setCurrentIndex(0)

    def _show_signin(self):
        self.signin_view.clear_fields()
        self.signin_view.clear_error()
        self._stack.setCurrentIndex(1)
        self.signin_view._username.setFocus()

    def _show_signup(self):
        self.signup_view.clear_fields()
        self.signup_view.clear_error()
        self._stack.setCurrentIndex(2)
        self.signup_view._username.setFocus()



    # ── Login Authentication Flow ─────────────────────────────────────────────
    def _on_login_submit(self, username: str, password: str):
        self.signin_view.clear_error()
        self.signin_view.set_loading(True)

        self._auth_thread = AuthThread(username, password, mode="login")
        self._auth_thread.success.connect(self._on_login_success)
        self._auth_thread.failed.connect(self._on_login_failed)
        self._auth_thread.start()

    def _on_login_success(self, user_id: int, username: str, result_type):
        self.signin_view.set_loading(False)
        self._user_id = user_id
        self._username = username
        self._proceed(user_id, username, "account")

    def _on_login_failed(self, msg: str):
        self.signin_view.set_loading(False)
        self.signin_view.show_error(msg)

    # ── Sign Up Registration Flow ─────────────────────────────────────────────
    def _on_signup_submit(self, username: str, password: str, confirm_pass: str):
        self.signup_view.clear_error()
        self.signup_view.set_loading(True)

        self._auth_thread = AuthThread(username, password, mode="signup")
        self._auth_thread.success.connect(self._on_signup_success)
        self._auth_thread.failed.connect(self._on_signup_failed)
        self._auth_thread.start()

    def _on_signup_success(self, user_id: int, username: str, result_type):
        self.signup_view.set_loading(False)
        self._user_id = user_id
        self._username = username

        # Transition to Onboarding Step 1: Name Assistant
        self._stack.setCurrentIndex(3)
        self.setup_name_view._input.setFocus()

    def _on_signup_failed(self, msg: str):
        self.signup_view.set_loading(False)
        self.signup_view.show_error(msg)

    # ── Onboarding Steps (Name + Voice Setup) ──────────────────────────────────
    def _on_name_submitted(self, name: str):
        try:
            from legacy.memory_manager import set_assistant_name_db
            set_assistant_name_db(self._user_id, name)
            from instance.config import settings
            settings.CURRENT_ASSISTANT_NAME = name
        except Exception as e:
            print(f"[LOGIN] Failed to save assistant name: {e}")

        # Transition to Onboarding Step 2: Voice Settings
        self.setup_voice_view.update_name(name)
        self._stack.setCurrentIndex(4)

    def _on_voice_submitted(self, profile: dict):
        try:
            from legacy.memory_manager import set_voice_profile_db
            set_voice_profile_db(
                self._user_id,
                voice_id=profile.get("voice_id") or "",
                voice_gender=profile.get("voice_gender", "male"),
                voice_tone=profile.get("voice_tone", "professional"),
                voice_rate=int(profile.get("voice_rate", 155)),
                voice_volume=float(profile.get("voice_volume", 1.0)),
            )
            from legacy.tts import apply_voice_profile
            apply_voice_profile(
                profile.get("voice_id"),
                rate=int(profile.get("voice_rate", 155)),
                volume=float(profile.get("voice_volume", 1.0)),
            )
        except Exception as e:
            print(f"[LOGIN] Failed to save voice profile: {e}")

        self._proceed(self._user_id, self._username, "account")

    # ── Window Transition ─────────────────────────────────────────────────────
    def _proceed(self, user_id: object, username: str, session_mode: str = "account"):
        fade_out = QPropertyAnimation(self, b"windowOpacity")
        fade_out.setDuration(350)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        fade_out.finished.connect(lambda: self.login_complete.emit(user_id, username, session_mode))
        fade_out.finished.connect(self.close)
        fade_out.start()
        self._fade_out_anim = fade_out

    def keyPressEvent(self, e):
        pass
