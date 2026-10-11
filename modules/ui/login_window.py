"""
Smart Assistant — Cinematic 3D AI Command Environment & Authentication
Visual reproduction of the reference AI/HUD environment for Login and Signup.

Features:
- Central AI Core: 3D rotating crystalline diamond/octahedron cage, luminous reactor beam,
  dual tilted orbital rings (cyan and purple), 48-tick HUD reticle, horizontal lens flare,
  and branded typography: TREVON LABS / INTELLIGENT ASSISTANT.
- Environment & Dais: 3D perspective floor with concentric glowing cyan/purple rings,
  radial perspective spokes, rotating radar sweep beam, and low-poly cyber mountain ridges along horizon.
- HUD Telemetry Panels:
  • Top-Left: SYS: MATRIX // 01 (UNDERSTAND, PLAN, EXECUTE, ADAPT, EVOLVE) with corner brackets.
  • Mid-Left: 3D digital wireframe globe with nodes and GLOBAL NETWORK / ONLINE caption.
  • Bottom-Left: AI CORE with dynamic live waveform sparkline.
  • Top-Right: SYSTEM ONLINE status pill, live digital clock, and telemetry matrix.
  • Mid-Right: CAPABILITIES // 02 with 5 glowing cyan meter bars.
  • Bottom-Right: ENVIRONMENT with live vertical equalizer bars.
- Central Authentication Card:
  • Glassmorphic translucent dark container with electric cyan bottom floor glow reflection.
  • Login Page: "Welcome Back", Email/Username input, Password input with eye toggle,
    "Remember me" checkbox, "Forgot password?" link, cyan-to-purple gradient "Sign In →" pill button,
    "OR CONTINUE WITH" divider, social SSO buttons (Google, Microsoft, Apple), "Create Account" link.
  • Signup Page: "Create Account", Username, Email, Password, Confirm Password,
    Terms agreement checkbox, cyan-to-purple gradient "Create Account →" button, "Sign In" link.
- 100% preservation of authentication backend (AuthWorker, AuthThread, PostgreSQL persistence).
"""

from __future__ import annotations

import math
import os
import random
import sys
import threading
from datetime import datetime

from PyQt6.QtCore import (
    QEasingCurve, QEvent, QObject, QPoint, QPointF, QPropertyAnimation,
    QRect, QRectF, QSize, Qt, QThread, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget,
)

from modules.ui.design_system import C, F, Radius
from modules.ui.dashboard.ds import icon as ds_icon, ICONS


# ─────────────────────────────────────────────────────────────────────────────
# PRESERVED AUTHENTICATION WORKERS & THREADS
# ─────────────────────────────────────────────────────────────────────────────
class AuthWorker(QObject):
    success = pyqtSignal(int, str, object)   # (user_id, username, result_type)
    failed  = pyqtSignal(str)                # error message

    def __init__(self, username: str, password: str, mode: str = "login", email: str = ""):
        super().__init__()
        self._username = username
        self._password = password
        self._mode = mode
        self._email = email

    def run(self):
        _is_frozen_exe = getattr(sys, "frozen", False)

        try:
            if _is_frozen_exe:
                from core.api_client import get_api_client
                client = get_api_client()
                if self._mode == "signup":
                    res = client.signup(self._username, self._password)
                    if res.get("success") and res.get("user_id"):
                        self.success.emit(int(res["user_id"]), res.get("username", self._username), "SIGNUP_OK")
                    elif res.get("error") and "exist" in res.get("error", "").lower():
                        self.failed.emit("That username is already taken. Please choose another or Sign In.")
                    else:
                        self.failed.emit(res.get("error", "Account creation could not be completed. Please try again."))
                else:
                    res = client.login(self._username, self._password)
                    if res.get("success") and res.get("user_id"):
                        self.success.emit(int(res["user_id"]), res.get("username", self._username), "LOGIN_OK")
                    elif res.get("error") and "not found" in res.get("error", "").lower():
                        self.failed.emit("No account found with that username.")
                    elif res.get("error") and ("password" in res.get("error", "").lower() or "credential" in res.get("error", "").lower()):
                        self.failed.emit("Incorrect password. Please try again.")
                    else:
                        self.failed.emit(res.get("error", "Sign in failed. Please try again."))
            else:
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

    def __init__(self, username: str, password: str, mode: str = "login", email: str = ""):
        super().__init__()
        self._w = AuthWorker(username, password, mode=mode, email=email)
        self._w.success.connect(self.success)
        self._w.failed.connect(self.failed)

    def run(self):
        self._w.run()


# ─────────────────────────────────────────────────────────────────────────────
# 3D PERSPECTIVE PROJECTION HELPER
# ─────────────────────────────────────────────────────────────────────────────
def _project_3d(x: float, y: float, z: float, cx: float, cy: float,
                fl: float = 500.0, cam_z: float = 620.0,
                pitch: float = 0.0, yaw: float = 0.0) -> tuple[float | None, float | None, float]:
    cos_y = math.cos(yaw)
    sin_y = math.sin(yaw)
    x1 = x * cos_y + z * sin_y
    z1 = -x * sin_y + z * cos_y

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
# SOCIAL ICONS GENERATOR (Google, Microsoft, Apple vector pixmaps)
# ─────────────────────────────────────────────────────────────────────────────
def make_google_icon(size: int = 18) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = p.font()
    f.setBold(True)
    f.setPixelSize(int(size * 0.85))
    f.setFamily("Arial")
    p.setFont(f)
    p.setPen(QColor("#4285F4"))
    p.drawText(QRectF(0, -1, size, size), Qt.AlignmentFlag.AlignCenter, "G")
    p.end()
    return QIcon(pm)


def make_microsoft_icon(size: int = 16) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    sq = (size - 3) / 2.0
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#F25022"))
    p.drawRect(QRectF(0, 0, sq, sq))
    p.setBrush(QColor("#7FBA00"))
    p.drawRect(QRectF(sq + 3, 0, sq, sq))
    p.setBrush(QColor("#00A4EF"))
    p.drawRect(QRectF(0, sq + 3, sq, sq))
    p.setBrush(QColor("#FFB900"))
    p.drawRect(QRectF(sq + 3, sq + 3, sq, sq))
    p.end()
    return QIcon(pm)


def make_apple_icon(size: int = 18) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#FFFFFF"))
    cx = size / 2.0
    cy = size / 2.0 + 1.0
    r = size * 0.32
    path = QPainterPath()
    path.addEllipse(QRectF(cx - r * 0.85, cy - r * 0.65, r * 1.7, r * 1.5))
    p.drawPath(path)
    p.drawEllipse(QRectF(cx - 1.5, cy - r * 1.25, 4, 3))
    p.end()
    return QIcon(pm)


# ─────────────────────────────────────────────────────────────────────────────
# 3D CINEMATIC BACKGROUND CANVAS (MATCHING REFERENCE IMAGE)
# ─────────────────────────────────────────────────────────────────────────────
class Futuristic3DCanvas(QWidget):
    """
    Renders the exact futuristic AI/HUD environment from the reference image:
    - Glowing central crystal AI core with horizontal lens flare streak
    - Dual tilted concentric orbital rings (cyan and purple)
    - Branded typography: TREVON LABS / INTELLIGENT ASSISTANT
    - Reflective 3D perspective floor dais with concentric glowing rings and sweep beam
    - Low-poly cyber mountain ridges along the horizon
    - 6 HUD telemetry panels in exact quadrants
    - Starfield and volumetric particles
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._t = 0.0
        self._mouse_curr = QPointF(-1000, -1000)
        self._mouse_target = QPointF(-1000, -1000)
        self._focus_intensity = 0.0
        self._target_focus = 0.0

        # Starfield points
        self._starfield = [
            (random.uniform(-1400, 1400), random.uniform(-800, 300), random.uniform(600, 1200),
             random.uniform(0.3, 0.95))
            for _ in range(110)
        ]

        # 3D Digital Globe points (Fibonacci sphere)
        self._globe_points = []
        n_globe = 160
        r_globe = 130.0
        for i in range(n_globe):
            phi = math.acos(1.0 - 2.0 * (i + 0.5) / n_globe)
            theta = math.pi * (1.0 + 5.0 ** 0.5) * i
            gx = r_globe * math.sin(phi) * math.cos(theta)
            gy = r_globe * math.sin(phi) * math.sin(theta)
            gz = r_globe * math.cos(phi)
            self._globe_points.append((gx, gy, gz))

        # Secondary small right sphere
        self._right_sphere_pts = []
        n_r = 70
        r_r = 70.0
        for i in range(n_r):
            phi = math.acos(1.0 - 2.0 * (i + 0.5) / n_r)
            theta = math.pi * (1.0 + 5.0 ** 0.5) * i
            self._right_sphere_pts.append((
                r_r * math.sin(phi) * math.cos(theta),
                r_r * math.sin(phi) * math.sin(theta),
                r_r * math.cos(phi)
            ))

        # Horizon mountain ridge points (left and right)
        self._mountains_left = [
            (-950, 180), (-850, 130), (-750, 155), (-680, 95), (-600, 145),
            (-520, 80), (-450, 160), (-380, 110), (-300, 195)
        ]
        self._mountains_right = [
            (300, 195), (380, 120), (460, 165), (540, 90), (620, 150),
            (700, 105), (780, 160), (860, 115), (960, 185)
        ]

        # Crystal octahedron cage vertices
        s_oct = 46.0
        self._octahedron_verts = [
            (0.0, -s_oct * 1.45, 0.0),    # Top apex
            (0.0, s_oct * 1.45, 0.0),     # Bottom apex
            (-s_oct, 0.0, 0.0),           # Left
            (s_oct, 0.0, 0.0),            # Right
            (0.0, 0.0, -s_oct),           # Back
            (0.0, 0.0, s_oct),            # Front
        ]
        self._octahedron_edges = [
            (0, 2), (0, 3), (0, 4), (0, 5),
            (1, 2), (1, 3), (1, 4), (1, 5),
            (2, 4), (4, 3), (3, 5), (5, 2)
        ]

        # Timer ~33 FPS
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(30)

    def set_mouse_position(self, pt: QPoint):
        self._mouse_target = QPointF(pt.x(), pt.y())
        if self._mouse_curr.x() < -500:
            self._mouse_curr = self._mouse_target

    def set_focused(self, focused: bool):
        self._target_focus = 1.0 if focused else 0.0

    def _step(self):
        self._t += 0.024
        self._focus_intensity += (self._target_focus - self._focus_intensity) * 0.12
        self._mouse_curr += (self._mouse_target - self._mouse_curr) * 0.06
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        w = float(self.width())
        h = float(self.height())
        cx = w / 2.0
        cy = h / 2.0

        # ── 1. DEEP SPACE ATMOSPHERIC BACKDROP ─────────────────────
        bg_grad = QRadialGradient(cx, cy * 0.50, max(w, h) * 0.85)
        bg_grad.setColorAt(0.00, QColor(6, 26, 54))     # Deep cyber cyan-blue center
        bg_grad.setColorAt(0.38, QColor(4, 14, 30))     # Dark cobalt
        bg_grad.setColorAt(0.70, QColor(2, 7, 16))      # Deep obsidian
        bg_grad.setColorAt(1.00, QColor(1, 3, 8))       # Midnight black
        p.fillRect(0, 0, int(w), int(h), QBrush(bg_grad))

        # Camera orientation
        yaw = 0.0
        pitch = 0.0
        if self._mouse_curr.x() > 0:
            yaw = (self._mouse_curr.x() - cx) * 0.00012
            pitch = (self._mouse_curr.y() - cy) * 0.00008

        fl = 500.0
        cam_z = 620.0

        # ── 2. DISTANT STARFIELD PARTICLES ────────────────────────
        p.setPen(Qt.PenStyle.NoPen)
        for idx, (sx, sy, sz, salpha) in enumerate(self._starfield):
            px, py, _ = _project_3d(sx, sy, sz, cx, cy, fl, cam_z, pitch, yaw)
            if px is not None:
                twinkle = 0.7 + 0.3 * math.sin(self._t * 2.2 + idx)
                alpha = int(salpha * twinkle * 255)
                p.setBrush(QBrush(QColor(186, 230, 253, alpha)))
                p.drawEllipse(QPointF(px, py), 1.4, 1.4)

        # ── 3. HORIZON DIGITAL MOUNTAINS / WIREFRAME RIDGES ────────
        self._draw_digital_horizon(p, cx, cy, fl, cam_z, yaw, pitch)

        # ── 4. 3D DIGITAL GLOBE (MID-LEFT) ────────────────────────
        if w >= 920:
            self._draw_digital_globe(p, cx, cy, fl, cam_z, yaw, pitch)

        # ── 5. SECONDARY ORBITAL SPHERE (MID-RIGHT) ───────────────
        if w >= 960:
            self._draw_secondary_sphere(p, cx, cy, fl, cam_z, yaw, pitch)

        # ── 6. 3D FLOOR PLATFORM & REFLECTION DAIS ────────────────
        self._draw_floor_platform(p, cx, cy, fl, cam_z, yaw, pitch, w, h)

        # ── 7. TELEMETRY HUD PANELS (4 QUADRANTS) ──────────────────
        if w >= 880:
            self._draw_hud_panels(p, w, h)

        # ── 8. CENTRAL GLOWING AI CORE & ORBITAL RINGS ────────────
        self._draw_central_ai_core(p, cx, cy, fl, cam_z, yaw, pitch, w, h)

        p.end()

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: DIGITAL HORIZON LOW-POLY RIDGES
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_digital_horizon(self, p: QPainter, cx: float, cy: float,
                              fl: float, cam_z: float, yaw: float, pitch: float):
        ground_y = 200.0
        p.setBrush(Qt.BrushStyle.NoBrush)

        for ridges, z_depth in [(self._mountains_left, 520.0), (self._mountains_right, 520.0)]:
            poly = QPolygonF()
            for x_val, y_val in ridges:
                px, py, _ = _project_3d(x_val, y_val, z_depth, cx, cy, fl, cam_z, pitch, yaw)
                if px is not None:
                    poly.append(QPointF(px, py))

            if len(poly) > 2:
                p.setPen(QPen(QColor(0, 212, 255, 45), 1.1))
                p.drawPolyline(poly)
                # Draw vertical mesh lines downward to ground
                p.setPen(QPen(QColor(0, 180, 240, 25), 0.8))
                for pt in poly:
                    px_g, py_g, _ = _project_3d((pt.x() - cx) / (fl / (z_depth + cam_z)), ground_y, z_depth,
                                                cx, cy, fl, cam_z, pitch, yaw)
                    if px_g is not None:
                        p.drawLine(pt, QPointF(pt.x(), py_g))

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: 3D HOLOGRAPHIC GLOBE (MID-LEFT)
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_digital_globe(self, p: QPainter, cx: float, cy: float,
                            fl: float, cam_z: float, yaw: float, pitch: float):
        globe_rot = self._t * 0.16
        tilt_x = 0.35
        cx_globe = -490.0
        cy_globe = -40.0
        cz_globe = 280.0

        cos_gr = math.cos(globe_rot)
        sin_gr = math.sin(globe_rot)
        cos_tx = math.cos(tilt_x)
        sin_tx = math.sin(tilt_x)

        g_center_x, g_center_y, g_scale = _project_3d(cx_globe, cy_globe, cz_globe, cx, cy, fl, cam_z, pitch, yaw)
        if g_center_x is None:
            return

        # Corona glow
        g_rad = 135.0 * g_scale
        g_glow = QRadialGradient(g_center_x, g_center_y, g_rad * 1.35)
        g_glow.setColorAt(0.0, QColor(0, 212, 255, 60))
        g_glow.setColorAt(0.5, QColor(0, 160, 240, 20))
        g_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g_glow))
        p.drawEllipse(QPointF(g_center_x, g_center_y), g_rad * 1.35, g_rad * 1.35)

        # Latitude rings
        for lat_deg in [0.0, 35.0, -35.0]:
            lat_rad = 130.0 * math.cos(math.radians(lat_deg))
            lat_y = 130.0 * math.sin(math.radians(lat_deg))
            poly = QPolygonF()
            for s in range(32):
                ang = math.radians(s * (360.0 / 32))
                rx = lat_rad * math.cos(ang)
                rz = lat_rad * math.sin(ang)
                rx1 = rx * cos_gr + rz * sin_gr
                rz1 = -rx * sin_gr + rz * cos_gr
                ry2 = lat_y * cos_tx - rz1 * sin_tx
                rz2 = lat_y * sin_tx + rz1 * cos_tx
                px, py, _ = _project_3d(rx1 + cx_globe, ry2 + cy_globe, rz2 + cz_globe, cx, cy, fl, cam_z, pitch, yaw)
                if px is not None:
                    poly.append(QPointF(px, py))
            if len(poly) > 2:
                p.setPen(QPen(QColor(0, 212, 255, 95 if lat_deg == 0 else 55), 1.1,
                              Qt.PenStyle.SolidLine if lat_deg == 0 else Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolyline(poly)

        # Longitude meridian rings
        for lon_deg in [0.0, 60.0, 120.0]:
            poly = QPolygonF()
            for s in range(32):
                ang = math.radians(s * (360.0 / 32))
                rx = 130.0 * math.sin(ang) * math.cos(math.radians(lon_deg))
                ry = 130.0 * math.cos(ang)
                rz = 130.0 * math.sin(ang) * math.sin(math.radians(lon_deg))
                rx1 = rx * cos_gr + rz * sin_gr
                rz1 = -rx * sin_gr + rz * cos_gr
                ry2 = ry * cos_tx - rz1 * sin_tx
                rz2 = ry * sin_tx + rz1 * cos_tx
                px, py, _ = _project_3d(rx1 + cx_globe, ry2 + cy_globe, rz2 + cz_globe, cx, cy, fl, cam_z, pitch, yaw)
                if px is not None:
                    poly.append(QPointF(px, py))
            if len(poly) > 2:
                p.setPen(QPen(QColor(0, 212, 255, 65), 1.0, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolyline(poly)

        # Nodes
        p.setPen(Qt.PenStyle.NoPen)
        for gx, gy, gz in self._globe_points:
            gx1 = gx * cos_gr + gz * sin_gr
            gz1 = -gx * sin_gr + gz * cos_gr
            gy2 = gy * cos_tx - gz1 * sin_tx
            gz2 = gy * sin_tx + gz1 * cos_tx
            px, py, sc = _project_3d(gx1 + cx_globe, gy2 + cy_globe, gz2 + cz_globe, cx, cy, fl, cam_z, pitch, yaw)
            if px is not None:
                depth = (gz2 + 130.0) / 260.0
                if depth > 0.40:
                    alpha = int(50 + 205 * (depth - 0.40) * 1.6)
                    p.setBrush(QBrush(QColor(0, 212, 255, alpha)))
                    p.drawEllipse(QPointF(px, py), 2.5 * sc * 1.5, 2.5 * sc * 1.5)

        # Text below globe
        p.setFont(F.mono(9))
        p.setPen(QColor(186, 230, 253, 190))
        p.drawText(int(g_center_x - 55), int(g_center_y + g_rad + 24), "GLOBAL NETWORK")
        p.setPen(QColor(0, 212, 255, 250))
        p.drawText(int(g_center_x - 55), int(g_center_y + g_rad + 40), "ONLINE")
        p.setPen(QPen(QColor(0, 212, 255, 180), 1.5))
        p.drawLine(QPointF(g_center_x - 12, g_center_y + g_rad + 37), QPointF(g_center_x + 35, g_center_y + g_rad + 37))

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: SECONDARY ORBITAL SPHERE (MID-RIGHT)
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_secondary_sphere(self, p: QPainter, cx: float, cy: float,
                               fl: float, cam_z: float, yaw: float, pitch: float):
        r_rot = -self._t * 0.22
        cx_r = 510.0
        cy_r = -60.0
        cz_r = 290.0

        cos_r = math.cos(r_rot)
        sin_r = math.sin(r_rot)

        center_x, center_y, scale = _project_3d(cx_r, cy_r, cz_r, cx, cy, fl, cam_z, pitch, yaw)
        if center_x is None:
            return

        rad = 75.0 * scale
        glow = QRadialGradient(center_x, center_y, rad * 1.4)
        glow.setColorAt(0.0, QColor(0, 212, 255, 45))
        glow.setColorAt(0.6, QColor(139, 92, 246, 20))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(center_x, center_y), rad * 1.4, rad * 1.4)

        # Orbit ring around sphere
        poly = QPolygonF()
        for s in range(32):
            ang = math.radians(s * (360.0 / 32))
            ox = 100.0 * math.cos(ang)
            oy = 100.0 * math.sin(ang) * 0.35
            oz = 100.0 * math.sin(ang) * 0.45
            px, py, _ = _project_3d(ox + cx_r, oy + cy_r, oz + cz_r, cx, cy, fl, cam_z, pitch, yaw)
            if px is not None:
                poly.append(QPointF(px, py))
        if len(poly) > 2:
            p.setPen(QPen(QColor(139, 92, 246, 120), 1.2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(poly)

        # Nodes on sphere
        p.setPen(Qt.PenStyle.NoPen)
        for gx, gy, gz in self._right_sphere_pts:
            gx1 = gx * cos_r + gz * sin_r
            gz1 = -gx * sin_r + gz * cos_r
            px, py, sc = _project_3d(gx1 + cx_r, gy + cy_r, gz1 + cz_r, cx, cy, fl, cam_z, pitch, yaw)
            if px is not None and gz1 > -20:
                p.setBrush(QBrush(QColor(186, 230, 253, 180)))
                p.drawEllipse(QPointF(px, py), 2.0 * sc * 1.5, 2.0 * sc * 1.5)

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: FLOOR PLATFORM & REFLECTIVE DAIS
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_floor_platform(self, p: QPainter, cx: float, cy: float,
                             fl: float, cam_z: float, yaw: float, pitch: float, w: float, h: float):
        ground_y = 200.0

        # Floor dais gradient backing
        dais_poly = QPolygonF()
        for s in range(36):
            ang = math.radians(s * (360.0 / 36))
            px, py, _ = _project_3d(400.0 * math.cos(ang), ground_y, 400.0 * math.sin(ang),
                                    cx, cy, fl, cam_z, pitch, yaw)
            if px is not None:
                dais_poly.append(QPointF(px, py))
        if len(dais_poly) > 2:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(0, 212, 255, 14)))
            p.drawPolygon(dais_poly)

        # Concentric platform rings with alternating cyan and purple glowing rings
        floor_radii = [140.0, 230.0, 340.0, 480.0, 640.0, 840.0, 1080.0]
        for idx, rad in enumerate(floor_radii):
            ring_poly = QPolygonF()
            segments = 40
            for s in range(segments + 1):
                ang = math.radians(s * (360.0 / segments))
                px, py, _ = _project_3d(rad * math.cos(ang), ground_y, rad * math.sin(ang),
                                        cx, cy, fl, cam_z, pitch, yaw)
                if px is not None:
                    ring_poly.append(QPointF(px, py))

            if len(ring_poly) > 2:
                # Ring color alternating between neon cyan and neon purple
                if idx % 2 == 1:
                    p.setPen(QPen(QColor(139, 92, 246, 140 - idx * 15), 1.8 if idx < 3 else 1.2))
                else:
                    p.setPen(QPen(QColor(0, 212, 255, 160 - idx * 18), 2.0 if idx < 3 else 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolyline(ring_poly)

        # Perspective spokes
        for r_idx in range(24):
            ang = math.radians(r_idx * (360.0 / 24))
            p1_x, p1_y, _ = _project_3d(140.0 * math.cos(ang), ground_y, 140.0 * math.sin(ang),
                                        cx, cy, fl, cam_z, pitch, yaw)
            p2_x, p2_y, _ = _project_3d(980.0 * math.cos(ang), ground_y, 980.0 * math.sin(ang),
                                        cx, cy, fl, cam_z, pitch, yaw)
            if p1_x is not None and p2_x is not None:
                p.setPen(QPen(QColor(0, 212, 255, 40 if r_idx % 2 == 0 else 22), 1.0))
                p.drawLine(QPointF(p1_x, p1_y), QPointF(p2_x, p2_y))

        # Rotating radar sweep beam
        sweep_ang = self._t * 0.85
        sweep_poly = QPolygonF()
        cp_x, cp_y, _ = _project_3d(0, ground_y, 0, cx, cy, fl, cam_z, pitch, yaw)
        if cp_x is not None:
            sweep_poly.append(QPointF(cp_x, cp_y))
            for st in range(12):
                sa = sweep_ang - (st * 0.04)
                sp_x, sp_y, _ = _project_3d(340.0 * math.cos(sa), ground_y, 340.0 * math.sin(sa),
                                            cx, cy, fl, cam_z, pitch, yaw)
                if sp_x is not None:
                    sweep_poly.append(QPointF(sp_x, sp_y))
            if len(sweep_poly) > 2:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(0, 212, 255, 45)))
                p.drawPolygon(sweep_poly)

        # Radiant Floor Light Reflection Pool directly beneath the authentication card
        # Exactly as seen in reference image
        ref_y = h * 0.90
        ref_w = 440.0
        ref_h = 100.0
        glow_grad = QRadialGradient(cx, ref_y, ref_w * 0.65)
        glow_grad.setColorAt(0.00, QColor(0, 212, 255, 120))
        glow_grad.setColorAt(0.35, QColor(0, 180, 255, 60))
        glow_grad.setColorAt(0.70, QColor(139, 92, 246, 25))
        glow_grad.setColorAt(1.00, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow_grad))
        p.drawEllipse(QRectF(cx - ref_w * 0.65, ref_y - ref_h * 0.5, ref_w * 1.3, ref_h))

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: HUD TELEMETRY PANELS (4 QUADRANTS)
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_hud_panels(self, p: QPainter, w: float, h: float):
        p.setFont(F.mono(9))

        # ── 1. TOP-LEFT: SYS: MATRIX // 01 ─────────────────────────
        tl_x = 42.0
        tl_y = 48.0
        tl_w = 170.0
        tl_h = 150.0

        p.setPen(QPen(QColor(0, 212, 255, 180), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        br = 12.0
        # Corner brackets
        p.drawLine(QPointF(tl_x, tl_y + br), QPointF(tl_x, tl_y))
        p.drawLine(QPointF(tl_x, tl_y), QPointF(tl_x + br, tl_y))
        p.drawLine(QPointF(tl_x + tl_w - br, tl_y), QPointF(tl_x + tl_w, tl_y))
        p.drawLine(QPointF(tl_x + tl_w, tl_y), QPointF(tl_x + tl_w, tl_y + br))
        p.drawLine(QPointF(tl_x, tl_y + tl_h - br), QPointF(tl_x, tl_y + tl_h))
        p.drawLine(QPointF(tl_x, tl_y + tl_h), QPointF(tl_x + br, tl_y + tl_h))
        p.drawLine(QPointF(tl_x + tl_w - br, tl_y + tl_h), QPointF(tl_x + tl_w, tl_y + tl_h))
        p.drawLine(QPointF(tl_x + tl_w, tl_y + tl_h), QPointF(tl_x + tl_w, tl_y + tl_h - br))

        p.setPen(QColor(0, 212, 255, 230))
        p.drawText(int(tl_x + 10), int(tl_y + 20), "SYS: MATRIX // 01")

        directives = ["UNDERSTAND", "PLAN", "EXECUTE", "ADAPT", "EVOLVE"]
        for i, d in enumerate(directives):
            p.setPen(QColor(186, 230, 253, 200))
            p.drawText(int(tl_x + 12), int(tl_y + 44 + i * 20), f"•  {d}")

        # ── 2. BOTTOM-LEFT: AI CORE + WAVEFORM ─────────────────────
        bl_x = 42.0
        bl_y = h - 145.0
        p.setPen(QColor(0, 212, 255, 220))
        p.drawText(int(bl_x), int(bl_y), "AI CORE")

        statuses = ["Processing", "Learning", "Optimizing", "Ready"]
        for i, s in enumerate(statuses):
            p.setPen(QColor(148, 163, 184, 210))
            p.drawText(int(bl_x + 2), int(bl_y + 18 + i * 16), f"• {s}")
            # Dot
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(0, 229, 107, 230) if i == 3 else QColor(0, 212, 255, 180)))
            p.drawEllipse(QPointF(bl_x + 85, bl_y + 13 + i * 16), 2.2, 2.2)

        # Dynamic cyan waveform sparkline
        wave_start_x = bl_x + 105.0
        wave_y = bl_y + 40.0
        wave_poly = QPolygonF()
        for wi in range(16):
            wx = wave_start_x + wi * 5.0
            wh = math.sin(self._t * 3.5 + wi * 0.8) * 8.0 + math.cos(self._t * 2.1 + wi * 0.4) * 4.0
            wave_poly.append(QPointF(wx, wave_y + wh))
        p.setPen(QPen(QColor(0, 212, 255, 210), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(wave_poly)

        # ── 3. TOP-RIGHT: SYSTEM ONLINE & TELEMETRY BOX ────────────
        tr_x = w - 235.0
        tr_y = 48.0

        # System Online status pill
        p.setPen(QPen(QColor(0, 229, 107, 100), 1.0))
        p.setBrush(QBrush(QColor(4, 24, 18, 140)))
        p.drawRoundedRect(int(tr_x), int(tr_y), 98, 22, 11, 11)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 229, 107, 255)))
        p.drawEllipse(QPointF(tr_x + 10, tr_y + 11), 3.0, 3.0)
        p.setPen(QColor(0, 229, 107, 240))
        p.setFont(F.mono(8))
        p.drawText(int(tr_x + 18), int(tr_y + 15), "SYSTEM ONLINE")

        # Digital Clock
        now_str = datetime.now().strftime("%H:%M:%S")
        p.setPen(QColor(186, 230, 253, 210))
        p.drawText(int(tr_x + 115), int(tr_y + 15), now_str)

        # Telemetry Box
        box_y = tr_y + 32.0
        box_w = 195.0
        box_h = 105.0
        p.setPen(QPen(QColor(0, 212, 255, 60), 1.0))
        p.setBrush(QBrush(QColor(6, 14, 26, 120)))
        p.drawRoundedRect(int(tr_x), int(box_y), int(box_w), int(box_h), 6, 6)

        telem_rows = [
            ("ASSISTANT CORE", "ACTIVE", QColor(0, 229, 107)),
            ("SECURE CHANNEL", "ENCRYPTED", QColor(0, 212, 255)),
            ("DATABASE", "ONLINE", QColor(0, 229, 107)),
            ("AI MODELS", "READY", QColor(0, 229, 107)),
            ("VOICE SYSTEM", "ONLINE", QColor(0, 229, 107)),
        ]
        for i, (k, v, col) in enumerate(telem_rows):
            p.setPen(QColor(148, 163, 184, 210))
            p.drawText(int(tr_x + 8), int(box_y + 18 + i * 18), k)
            p.setPen(col)
            p.drawText(int(tr_x + box_w - 76), int(box_y + 18 + i * 18), v)
            # Dot
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(tr_x + box_w - 8, box_y + 14 + i * 18), 2.2, 2.2)

        # ── 4. MID-RIGHT: CAPABILITIES // 02 ───────────────────────
        cap_x = w - 210.0
        cap_y = 220.0
        p.setPen(QColor(0, 212, 255, 230))
        p.setFont(F.mono(9))
        p.drawText(int(cap_x), int(cap_y), "CAPABILITIES // 02")

        capabilities = [
            ("SPEECH", 0.90),
            ("VISION", 0.65),
            ("CONTEXT", 0.85),
            ("AUTOMATION", 0.75),
            ("INTEGRATION", 0.60),
        ]
        for i, (c_name, fill_pct) in enumerate(capabilities):
            cy_item = cap_y + 24.0 + i * 20.0
            p.setPen(QColor(186, 230, 253, 210))
            p.drawText(int(cap_x + 4), int(cy_item + 8), f"• {c_name}")

            # Rounded cyan meter bar
            bar_x = cap_x + 95.0
            bar_w = 64.0
            bar_h = 7.0
            p.setPen(Qt.PenStyle.NoPen)
            # Track
            p.setBrush(QBrush(QColor(15, 23, 42, 180)))
            p.drawRoundedRect(int(bar_x), int(cy_item), int(bar_w), int(bar_h), 3, 3)
            # Fill
            dynamic_fill = min(1.0, max(0.2, fill_pct + 0.05 * math.sin(self._t * 2.0 + i)))
            p.setBrush(QBrush(QColor(0, 212, 255, 230)))
            p.drawRoundedRect(int(bar_x), int(cy_item), int(bar_w * dynamic_fill), int(bar_h), 3, 3)

        # ── 5. BOTTOM-RIGHT: ENVIRONMENT ───────────────────────────
        env_x = w - 210.0
        env_y = h - 145.0
        p.setPen(QColor(0, 212, 255, 220))
        p.drawText(int(env_x), int(env_y), "ENVIRONMENT")

        env_items = ["Network", "Security", "Performance", "All Systems"]
        for i, item in enumerate(env_items):
            p.setPen(QColor(148, 163, 184, 210))
            p.drawText(int(env_x + 4), int(env_y + 18 + i * 16), f"• {item}")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(0, 229, 107, 230)))
            p.drawEllipse(QPointF(env_x + 90, env_y + 13 + i * 16), 2.2, 2.2)

        # Vertical equalizer bars
        eq_start_x = env_x + 115.0
        eq_base_y = env_y + 68.0
        p.setPen(Qt.PenStyle.NoPen)
        for ei in range(8):
            eh = (math.sin(self._t * 4.0 + ei * 0.9) * 0.5 + 0.5) * 22.0 + 4.0
            ex = eq_start_x + ei * 7.0
            p.setBrush(QBrush(QColor(0, 212, 255, 200)))
            p.drawRoundedRect(int(ex), int(eq_base_y - eh), 4, int(eh), 2, 2)

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: CENTRAL AI CORE & ORBITAL RINGS
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_central_ai_core(self, p: QPainter, cx: float, cy: float,
                              fl: float, cam_z: float, yaw: float, pitch: float, w: float, h: float):
        # Anchor the central core vertically in the upper screen crown
        px = cx
        py = max(110.0, h * 0.17)
        scale = min(1.15, max(0.72, h / 1080.0))

        t_spin = self._t * (1.0 + self._focus_intensity * 0.4)

        # ── 1. Vertical Luminous Reactor Energy Beam ──
        beam_grad = QLinearGradient(QPointF(px - 22, py), QPointF(px + 22, py))
        beam_grad.setColorAt(0.0, QColor(0, 212, 255, 0))
        beam_grad.setColorAt(0.5, QColor(0, 212, 255, int(55 + 30 * self._focus_intensity)))
        beam_grad.setColorAt(1.0, QColor(0, 212, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(beam_grad))
        p.drawRect(int(px - 22), 0, 44, int(h * 0.45))
        # Core laser hairline
        p.setPen(QPen(QColor(255, 255, 255, 180), 1.2))
        p.drawLine(QPointF(px, 0), QPointF(px, h * 0.45))

        # ── 2. Horizontal Lens Flare Streak ──
        flare_w = 400.0 * scale
        flare_h = 3.5
        flare_grad = QLinearGradient(QPointF(px - flare_w, py), QPointF(px + flare_w, py))
        flare_grad.setColorAt(0.00, QColor(0, 212, 255, 0))
        flare_grad.setColorAt(0.35, QColor(0, 212, 255, 120))
        flare_grad.setColorAt(0.50, QColor(255, 255, 255, 255))
        flare_grad.setColorAt(0.65, QColor(0, 212, 255, 120))
        flare_grad.setColorAt(1.00, QColor(0, 212, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(flare_grad))
        p.drawRect(QRectF(px - flare_w, py - flare_h / 2.0, flare_w * 2.0, flare_h))

        # ── 3. Multi-Stop Radiant Core Corona ──
        breathe = 0.90 + 0.10 * math.sin(self._t * 2.6)
        corona_r = (165.0 + 35.0 * self._focus_intensity) * breathe * scale
        corona = QRadialGradient(px, py, corona_r)
        corona.setColorAt(0.00, QColor(255, 255, 255, 255))
        corona.setColorAt(0.12, QColor(0, 235, 255, 210))
        corona.setColorAt(0.35, QColor(0, 165, 255, 110))
        corona.setColorAt(0.70, QColor(139, 92, 246, 45))
        corona.setColorAt(1.00, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(corona))
        p.drawEllipse(QPointF(px, py), corona_r, corona_r)

        # ── 4. 3D Rotating Crystal Octahedron Cage ──
        self._draw_octahedron(p, px, py, scale, t_spin)

        # ── 5. 48-Tick Rotating HUD Reticle Ring ──
        hud_r = 95.0 * scale
        hud_rot = t_spin * 0.5
        p.setPen(QPen(QColor(0, 212, 255, 160), 1.2))
        for tick_i in range(48):
            ang = math.radians(tick_i * (360.0 / 48)) + hud_rot
            r_in = hud_r - (6.0 if tick_i % 4 == 0 else 3.0)
            r_out = hud_r
            t1_x = px + r_in * math.cos(ang)
            t1_y = py + r_in * math.sin(ang) * 0.38
            t2_x = px + r_out * math.cos(ang)
            t2_y = py + r_out * math.sin(ang) * 0.38
            p.drawLine(QPointF(t1_x, t1_y), QPointF(t2_x, t2_y))

        # ── 6. DUAL TILTED CONCENTRIC ORBITAL RINGS (CYAN & PURPLE) ──
        # Ring 1: Neon Cyan orbital ring with node beads
        self._render_3d_ring(p, px, py, scale,
                             r=155.0, rot_y=t_spin * 0.75, tilt_x=1.15, tilt_z=0.15,
                             color=QColor(0, 212, 255, 230),
                             width=1.8, dash=False, has_node=True, node_color=QColor(255, 255, 255))

        # Ring 2: Vivid Purple / Violet orbital ring with node beads (Matches Reference!)
        self._render_3d_ring(p, px, py, scale,
                             r=220.0, rot_y=-t_spin * 0.55, tilt_x=-0.85, tilt_z=0.55,
                             color=QColor(168, 85, 247, 210),
                             width=1.8, dash=True, has_node=True, node_color=QColor(216, 180, 254))

        # Ring 3: Outer perimeter ellipse
        self._render_3d_ring(p, px, py, scale,
                             r=320.0, rot_y=t_spin * 0.35, tilt_x=0.45, tilt_z=-0.30,
                             color=QColor(0, 212, 255, 120),
                             width=1.2, dash=True, has_node=True, node_color=QColor(0, 212, 255))

        # ── 7. BRANDED TYPOGRAPHY DIRECTLY BENEATH CORE ────────────
        # Exact reproduction of:
        # TREVON LABS
        # — INTELLIGENT ASSISTANT —
        # Your intelligent assistant, ready when you are.
        ty_brand = py + 62.0 * scale

        # Title: TREVON LABS
        p.setPen(QColor("#E0F2FE"))
        f_title = QFont(F.PRIMARY, 16)
        f_title.setBold(True)
        f_title.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4.5)
        p.setFont(f_title)
        fm = p.fontMetrics()
        t_str = "TREVON LABS"
        p.drawText(int(px - fm.horizontalAdvance(t_str) / 2.0), int(ty_brand), t_str)

        # Sub-title: — INTELLIGENT ASSISTANT —
        ty_sub = ty_brand + 20.0
        p.setPen(QColor("#00D4FF"))
        f_sub = QFont(F.PRIMARY, 9)
        f_sub.setBold(True)
        f_sub.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        p.setFont(f_sub)
        fm2 = p.fontMetrics()
        sub_str = "INTELLIGENT ASSISTANT"
        sub_w = fm2.horizontalAdvance(sub_str)
        p.drawText(int(px - sub_w / 2.0), int(ty_sub), sub_str)
        # Horizontal accent rules
        p.setPen(QPen(QColor(0, 212, 255, 160), 1.2))
        p.drawLine(QPointF(px - sub_w / 2.0 - 24, ty_sub - 3), QPointF(px - sub_w / 2.0 - 6, ty_sub - 3))
        p.drawLine(QPointF(px + sub_w / 2.0 + 6, ty_sub - 3), QPointF(px + sub_w / 2.0 + 24, ty_sub - 3))

        # Tagline: Your intelligent assistant, ready when you are.
        ty_tag = ty_sub + 18.0
        p.setPen(QColor("#8FA0B5"))
        f_tag = QFont(F.PRIMARY, 11)
        f_tag.setWeight(QFont.Weight.Normal)
        p.setFont(f_tag)
        fm3 = p.fontMetrics()
        tag_str = "Your intelligent assistant, ready when you are."
        p.drawText(int(px - fm3.horizontalAdvance(tag_str) / 2.0), int(ty_tag), tag_str)

    # ─────────────────────────────────────────────────────────────────────────
    # SUB-RENDERER: 3D CRYSTAL OCTAHEDRON
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_octahedron(self, p: QPainter, center_x: float, center_y: float, scale: float, t_spin: float):
        rot_y = t_spin * 0.85
        rot_x = t_spin * 0.50
        cos_y = math.cos(rot_y)
        sin_y = math.sin(rot_y)
        cos_x = math.cos(rot_x)
        sin_x = math.sin(rot_x)

        projected = []
        for vx, vy, vz in self._octahedron_verts:
            x1 = vx * cos_y + vz * sin_y
            z1 = -vx * sin_y + vz * cos_y
            y2 = vy * cos_x - z1 * sin_x
            z2 = vy * sin_x + z1 * cos_x
            sc = scale * (420.0 / (z2 + 420.0))
            px = center_x + x1 * sc
            py = center_y + y2 * sc
            projected.append((px, py))

        # Glowing facets / inner blinding core
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 212, 255, 65)))
        for tri in [(0, 2, 5), (0, 5, 3), (0, 3, 4), (0, 4, 2)]:
            pts = [QPointF(projected[i][0], projected[i][1]) for i in tri]
            p.drawPolygon(QPolygonF(pts))

        # Draw glowing edges
        p.setPen(QPen(QColor(0, 235, 255, 230), 1.8))
        for v1, v2 in self._octahedron_edges:
            p1 = projected[v1]
            p2 = projected[v2]
            p.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

        # Vertices
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255, 255)))
        for px, py in projected:
            p.drawEllipse(QPointF(px, py), 3.4 * scale, 3.4 * scale)

    # ─────────────────────────────────────────────────────────────────────────
    # 3D ROTATING RING HELPER
    # ─────────────────────────────────────────────────────────────────────────
    def _render_3d_ring(self, p: QPainter, center_x: float, center_y: float, scale: float,
                        r: float, rot_y: float, tilt_x: float, tilt_z: float,
                        color: QColor, width: float = 1.0, dash: bool = False,
                        has_node: bool = False, node_color: QColor = QColor(255, 255, 255)):
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
            lz = r * math.sin(ang)

            x1 = lx * cos_ry + lz * sin_ry
            z1 = -lx * sin_ry + lz * cos_ry
            y2 = -z1 * sin_tx
            z2 = z1 * cos_tx
            x3 = x1 * cos_tz - y2 * sin_tz
            y3 = x1 * sin_tz + y2 * cos_tz

            sc = scale * (500.0 / (z2 + 500.0))
            px = center_x + x3 * sc
            py = center_y + y3 * sc
            ring_poly.append(QPointF(px, py))
            if has_node and s == node_seg:
                node_pos = QPointF(px, py)

        if len(ring_poly) > 2:
            # Neon soft halo underlay
            glow_pen = QColor(color)
            glow_pen.setAlpha(int(color.alpha() * 0.35))
            p.setPen(QPen(glow_pen, width * 2.8, Qt.PenStyle.SolidLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(ring_poly)

            # Core sharp ring
            p.setPen(QPen(color, width, Qt.PenStyle.DashLine if dash else Qt.PenStyle.SolidLine))
            p.drawPolyline(ring_poly)

        if node_pos is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(node_color))
            p.drawEllipse(node_pos, 3.8 * scale, 3.8 * scale)
            glow_c = QColor(color)
            glow_c.setAlpha(120)
            p.setBrush(QBrush(glow_c))
            p.drawEllipse(node_pos, 8.0 * scale, 8.0 * scale)


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM INPUT FIELD WITH EMBEDDED ICONS & FOCUS REACTIVITY
# ─────────────────────────────────────────────────────────────────────────────
class IconInputField(QLineEdit):
    focus_changed = pyqtSignal(bool)

    def __init__(self, placeholder: str = "", icon_name: str = "", is_password: bool = False, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setFixedHeight(46)
        self._is_password = is_password
        self._password_visible = False

        if icon_name:
            lead_ic = ds_icon(icon_name, "#728CA6", 15)
            self.addAction(lead_ic, QLineEdit.ActionPosition.LeadingPosition)

        if is_password:
            self.setEchoMode(QLineEdit.EchoMode.Password)
            self._eye_action = self.addAction(ds_icon(ICONS.EYE, "#728CA6", 15), QLineEdit.ActionPosition.TrailingPosition)
            self._eye_action.triggered.connect(self._toggle_password)

        self.setStyleSheet("""
            QLineEdit {
                background: rgba(12, 20, 36, 0.78);
                color: #ffffff;
                border: 1px solid rgba(40, 72, 115, 0.65);
                border-radius: 10px;
                padding: 10px 14px;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
            }
            QLineEdit:focus {
                border: 1.5px solid #00D4FF;
                background: rgba(16, 28, 48, 0.88);
            }
            QLineEdit::placeholder {
                color: #5A708A;
            }
        """)

    def _toggle_password(self):
        self._password_visible = not self._password_visible
        if self._password_visible:
            self.setEchoMode(QLineEdit.EchoMode.Normal)
            self._eye_action.setIcon(ds_icon(ICONS.EYE_SLASH, "#00D4FF", 15))
        else:
            self.setEchoMode(QLineEdit.EchoMode.Password)
            self._eye_action.setIcon(ds_icon(ICONS.EYE, "#728CA6", 15))

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focus_changed.emit(True)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.focus_changed.emit(False)


# ─────────────────────────────────────────────────────────────────────────────
# VIEW: SIGN IN (MATCHING REFERENCE IMAGE)
# ─────────────────────────────────────────────────────────────────────────────
class SignInView(QWidget):
    submit_requested = pyqtSignal(str, str)
    switch_to_signup = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Title: Welcome Back
        title = QLabel("Welcome Back")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #FFFFFF; font-size: 24px; font-weight: 700; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(title)

        # Subtitle: Authenticate to continue to your assistant.
        sub = QLabel("Authenticate to continue to your assistant.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #8FA0B5; font-size: 12px; font-family: 'Segoe UI'; margin-bottom: 6px; background: transparent;")
        lay.addWidget(sub)

        # Username / Email Input
        self._username = IconInputField("Email or Username", ICONS.USER, is_password=False)
        self._username.returnPressed.connect(self._on_submit)
        lay.addWidget(self._username)

        # Password Input with Eye Toggle
        self._password = IconInputField("Password", ICONS.LOCK, is_password=True)
        self._password.returnPressed.connect(self._on_submit)
        lay.addWidget(self._password)

        # Options Row: Remember Me & Forgot Password
        opt_row = QHBoxLayout()
        opt_row.setContentsMargins(2, 2, 2, 2)

        self._remember = QCheckBox("Remember me")
        self._remember.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remember.setStyleSheet("""
            QCheckBox {
                color: #8FA0B5;
                font-size: 12px;
                spacing: 8px;
                background: transparent;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
                border: 1px solid rgba(0, 212, 255, 0.45);
                border-radius: 4px;
                background: rgba(10, 18, 32, 0.8);
            }
            QCheckBox::indicator:hover {
                border: 1px solid #00D4FF;
            }
            QCheckBox::indicator:checked {
                background: #00D4FF;
                border: 1px solid #00D4FF;
            }
        """)
        opt_row.addWidget(self._remember)
        opt_row.addStretch(1)

        forgot_btn = QPushButton("Forgot password?")
        forgot_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        forgot_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #38BDF8;
                border: none;
                font-size: 12px;
            }
            QPushButton:hover {
                color: #00D4FF;
                text-decoration: underline;
            }
        """)
        forgot_btn.clicked.connect(self._on_forgot)
        opt_row.addWidget(forgot_btn)
        lay.addLayout(opt_row)

        # Error banner
        self._err = QLabel("")
        self._err.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._err.setStyleSheet("""
            color: #F87171;
            font-size: 11px;
            background: rgba(248, 113, 113, 0.12);
            border: 1px solid rgba(248, 113, 113, 0.35);
            border-radius: 6px;
            padding: 5px;
        """)
        self._err.hide()
        lay.addWidget(self._err)

        # Primary Button: Sign In → (Cyan-to-Purple Gradient Pill)
        self._btn_submit = QPushButton("Sign In   →")
        self._btn_submit.setFixedHeight(46)
        self._btn_submit.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_submit.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00D4FF, stop:1 #9B51E0);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 23px;
                font-size: 15px;
                font-weight: 700;
                font-family: 'Segoe UI';
                letter-spacing: 0.5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1AE0FF, stop:1 #A855F7);
                border: 1px solid rgba(255, 255, 255, 0.45);
            }
            QPushButton:disabled {
                background: #1E293B;
                color: #64748B;
                border-color: #334155;
            }
        """)
        self._btn_submit.clicked.connect(self._on_submit)
        lay.addWidget(self._btn_submit)

        # Divider: — OR CONTINUE WITH —
        div_lbl = QLabel("OR CONTINUE WITH")
        div_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        div_lbl.setStyleSheet("color: #5A708A; font-size: 10px; font-weight: 700; letter-spacing: 1.2px; margin-top: 4px; background: transparent;")
        lay.addWidget(div_lbl)

        # Social SSO Buttons (Google, Microsoft, Apple)
        sso_row = QHBoxLayout()
        sso_row.setSpacing(12)
        sso_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for make_fn, name in [
            (make_google_icon, "Google"),
            (make_microsoft_icon, "Microsoft"),
            (make_apple_icon, "Apple"),
        ]:
            sso_btn = QPushButton()
            sso_btn.setIcon(make_fn(18))
            sso_btn.setIconSize(QSize(18, 18))
            sso_btn.setFixedSize(54, 38)
            sso_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            sso_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.12);
                    border: 1px solid rgba(0, 212, 255, 0.45);
                }
            """)
            sso_btn.clicked.connect(lambda _, n=name: self._on_sso(n))
            sso_row.addWidget(sso_btn)

        lay.addLayout(sso_row)

        # Footer Link: Don't have an account? Create Account
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        f_lbl = QLabel("Don't have an account?")
        f_lbl.setStyleSheet("color: #8FA0B5; font-size: 12px; background: transparent;")
        footer.addWidget(f_lbl)

        create_btn = QPushButton("Create Account")
        create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        create_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #00D4FF;
                border: none;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton:hover {
                text-decoration: underline;
                color: #38BDF8;
            }
        """)
        create_btn.clicked.connect(self.switch_to_signup.emit)
        footer.addWidget(create_btn)

        lay.addLayout(footer)

    def _on_submit(self):
        u = self._username.text().strip()
        p = self._password.text().strip()
        if not u:
            self.show_error("Please enter your email or username.")
            return
        if not p:
            self.show_error("Please enter your password.")
            return
        self.clear_error()
        self.submit_requested.emit(u, p)

    def _on_forgot(self):
        self.show_error("Password reset is managed via your administrator or database credentials.")

    def _on_sso(self, provider: str):
        self.show_error(f"{provider} single sign-on is available for enterprise domain deployments.")

    def show_error(self, msg: str):
        self._err.setText(msg)
        self._err.show()

    def clear_error(self):
        self._err.hide()
        self._err.setText("")

    def clear_fields(self):
        self._username.clear()
        self._password.clear()

    def set_loading(self, loading: bool):
        self._btn_submit.setEnabled(not loading)
        self._btn_submit.setText("Signing In..." if loading else "Sign In   →")


# ─────────────────────────────────────────────────────────────────────────────
# VIEW: SIGN UP / REGISTRATION (MATCHING REFERENCE AESTHETIC)
# ─────────────────────────────────────────────────────────────────────────────
class SignUpView(QWidget):
    submit_requested = pyqtSignal(str, str, str)  # (username, password, confirm)
    switch_to_login = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Title: Create Account
        title = QLabel("Create Account")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #FFFFFF; font-size: 24px; font-weight: 700; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(title)

        sub = QLabel("Join Trevon Labs to initialize your personal assistant.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #8FA0B5; font-size: 12px; font-family: 'Segoe UI'; margin-bottom: 4px; background: transparent;")
        lay.addWidget(sub)

        # Username / Display Name Input
        self._username = IconInputField("Display Name or Username", ICONS.USER, is_password=False)
        lay.addWidget(self._username)

        # Email Input
        self._email = IconInputField("Email address", ICONS.COMMUNICATIONS, is_password=False)
        lay.addWidget(self._email)

        # Password Input
        self._password = IconInputField("Password", ICONS.LOCK, is_password=True)
        lay.addWidget(self._password)

        # Confirm Password Input
        self._confirm = IconInputField("Confirm Password", ICONS.LOCK, is_password=True)
        self._confirm.returnPressed.connect(self._on_submit)
        lay.addWidget(self._confirm)

        # Error banner
        self._err = QLabel("")
        self._err.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._err.setStyleSheet("""
            color: #F87171;
            font-size: 11px;
            background: rgba(248, 113, 113, 0.12);
            border: 1px solid rgba(248, 113, 113, 0.35);
            border-radius: 6px;
            padding: 5px;
        """)
        self._err.hide()
        lay.addWidget(self._err)

        # Terms Agreement Checkbox
        self._terms = QCheckBox("I agree to the Terms of Service & Privacy Policy")
        self._terms.setChecked(True)
        self._terms.setCursor(Qt.CursorShape.PointingHandCursor)
        self._terms.setStyleSheet("""
            QCheckBox {
                color: #8FA0B5;
                font-size: 11px;
                spacing: 8px;
                background: transparent;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid rgba(0, 212, 255, 0.45);
                border-radius: 3px;
                background: rgba(10, 18, 32, 0.8);
            }
            QCheckBox::indicator:hover {
                border: 1px solid #00D4FF;
            }
            QCheckBox::indicator:checked {
                background: #00D4FF;
                border: 1px solid #00D4FF;
            }
        """)
        lay.addWidget(self._terms)

        # Primary Button: Create Account → (Cyan-to-Purple Gradient Pill)
        self._btn_submit = QPushButton("Create Account   →")
        self._btn_submit.setFixedHeight(46)
        self._btn_submit.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_submit.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00D4FF, stop:1 #9B51E0);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 23px;
                font-size: 15px;
                font-weight: 700;
                font-family: 'Segoe UI';
                letter-spacing: 0.5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1AE0FF, stop:1 #A855F7);
                border: 1px solid rgba(255, 255, 255, 0.45);
            }
            QPushButton:disabled {
                background: #1E293B;
                color: #64748B;
                border-color: #334155;
            }
        """)
        self._btn_submit.clicked.connect(self._on_submit)
        lay.addWidget(self._btn_submit)

        # Footer Link: Already have an account? Sign In
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        f_lbl = QLabel("Already have an account?")
        f_lbl.setStyleSheet("color: #8FA0B5; font-size: 12px; background: transparent;")
        footer.addWidget(f_lbl)

        login_btn = QPushButton("Sign In")
        login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        login_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #00D4FF;
                border: none;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton:hover {
                text-decoration: underline;
                color: #38BDF8;
            }
        """)
        login_btn.clicked.connect(self.switch_to_login.emit)
        footer.addWidget(login_btn)

        lay.addLayout(footer)

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
        if not self._terms.isChecked():
            self.show_error("Please accept the Terms of Service to continue.")
            return
        self.clear_error()
        self.submit_requested.emit(u, p, cp)

    def show_error(self, msg: str):
        self._err.setText(msg)
        self._err.show()

    def clear_error(self):
        self._err.hide()
        self._err.setText("")

    def clear_fields(self):
        self._username.clear()
        self._email.clear()
        self._password.clear()
        self._confirm.clear()

    def set_loading(self, loading: bool):
        self._btn_submit.setEnabled(not loading)
        self._btn_submit.setText("Creating Account..." if loading else "Create Account   →")


# ─────────────────────────────────────────────────────────────────────────────
# VIEW: ONBOARDING STEP 1 — NAME YOUR ASSISTANT
# ─────────────────────────────────────────────────────────────────────────────
class SetupNameView(QWidget):
    name_submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Name Your Assistant")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #FFFFFF; font-size: 22px; font-weight: 700; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(title)

        sub = QLabel("Choose what you'd like your AI companion to be called.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #8FA0B5; font-size: 12px; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(sub)

        lay.addSpacing(6)

        self._input = IconInputField("Assistant name (e.g. Friday, Jarvis, Trevon)", ICONS.ASSISTANT, is_password=False)
        self._input.setText("Friday")
        self._input.returnPressed.connect(self._on_submit)
        lay.addWidget(self._input)

        btn = QPushButton("Continue   →")
        btn.setFixedHeight(46)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00D4FF, stop:1 #9B51E0);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 23px;
                font-size: 15px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1AE0FF, stop:1 #A855F7);
            }
        """)
        btn.clicked.connect(self._on_submit)
        lay.addWidget(btn)

    def _on_submit(self):
        name = self._input.text().strip() or "Friday"
        self.name_submitted.emit(name)


# ─────────────────────────────────────────────────────────────────────────────
# VIEW: ONBOARDING STEP 2 — VOICE PERSONALIZATION
# ─────────────────────────────────────────────────────────────────────────────
_TONE_PROFILES = [
    ("Professional", {"rate": 155, "volume": 1.0}),
    ("Casual",       {"rate": 165, "volume": 1.0}),
    ("Direct",       {"rate": 175, "volume": 1.0}),
    ("Calm",         {"rate": 140, "volume": 0.9}),
]


class SetupVoiceView(QWidget):
    voice_submitted = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._assistant_name = "Assistant"
        self._selected_gender = "female"
        self._all_voices = []
        self._build_ui()
        self._load_voices_async()

    def update_name(self, name: str):
        self._assistant_name = name
        self._sub.setText(f"Select the voice and speaking tone for {name}.")

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Select Voice Profile")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #FFFFFF; font-size: 22px; font-weight: 700; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(title)

        self._sub = QLabel("Select the voice and speaking tone for your assistant.")
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub.setStyleSheet("color: #8FA0B5; font-size: 12px; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(self._sub)

        # Voice selection combo
        self._voice_combo = QComboBox()
        self._voice_combo.setFixedHeight(40)
        self._voice_combo.setStyleSheet("""
            QComboBox {
                background: rgba(12, 20, 36, 0.85);
                color: #ffffff;
                border: 1px solid rgba(40, 72, 115, 0.65);
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 13px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #0B1626;
                color: #FFFFFF;
                selection-background-color: #00D4FF;
                selection-color: #000000;
            }
        """)
        lay.addWidget(self._voice_combo)

        # Preview Button
        self._preview_btn = QPushButton("▶  Preview Voice")
        self._preview_btn.setFixedHeight(38)
        self._preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 212, 255, 0.12);
                color: #00D4FF;
                border: 1px solid rgba(0, 212, 255, 0.40);
                border-radius: 8px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(0, 212, 255, 0.22);
                border-color: #00D4FF;
            }
        """)
        self._preview_btn.clicked.connect(self._preview_voice)
        lay.addWidget(self._preview_btn)

        # Finish button
        finish_btn = QPushButton("Finish & Launch   →")
        finish_btn.setFixedHeight(46)
        finish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        finish_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00D4FF, stop:1 #9B51E0);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 23px;
                font-size: 15px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1AE0FF, stop:1 #A855F7);
            }
        """)
        finish_btn.clicked.connect(self._on_continue)
        lay.addWidget(finish_btn)

    def _load_voices_async(self):
        def _worker():
            voices = []
            try:
                import pyttsx3
                engine = pyttsx3.init()
                raw = engine.getProperty("voices")
                voices = [
                    {"id": v.id, "name": v.name, "gender": getattr(v, "gender", "unknown")}
                    for v in (raw or [])
                ]
            except Exception:
                voices = []
            QTimer.singleShot(0, lambda: self._on_voices_loaded(voices))
        threading.Thread(target=_worker, daemon=True).start()

    def _on_voices_loaded(self, voices: list):
        self._all_voices = voices
        self._voice_combo.clear()
        if not voices:
            self._voice_combo.addItem("System Default Voice", None)
            return
        for v in voices:
            self._voice_combo.addItem(f"{v['name']}", v["id"])
        self._voice_combo.setCurrentIndex(0)

    def _preview_voice(self):
        idx = self._voice_combo.currentIndex()
        vid = self._voice_combo.itemData(idx) if idx >= 0 else None
        preview_text = f"Hello. I'm {self._assistant_name}. Your system is online and ready."

        def _speak():
            try:
                import pyttsx3
                engine = pyttsx3.init()
                if vid:
                    engine.setProperty("voice", vid)
                engine.setProperty("rate", 155)
                engine.setProperty("volume", 1.0)
                engine.say(preview_text)
                engine.runAndWait()
            except Exception as e:
                print(f"[VOICE SETUP] Preview error: {e}")

        threading.Thread(target=_speak, daemon=True).start()

    def _on_continue(self):
        idx = self._voice_combo.currentIndex()
        vid = self._voice_combo.itemData(idx) if idx >= 0 else None
        profile = {
            "voice_id": vid,
            "voice_gender": self._selected_gender,
            "voice_tone": "professional",
            "voice_rate": 155,
            "voice_volume": 1.0,
        }
        self.voice_submitted.emit(profile)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN AUTHENTICATION WINDOW (LOGIN & SIGNUP)
# ─────────────────────────────────────────────────────────────────────────────
class LoginWindow(QWidget):
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

        # 1. Full-screen 3D Cinematic Canvas
        self._bg = Futuristic3DCanvas(self)
        self._bg.setGeometry(0, 0, self.width(), self.height())

        # 2. Centered Authentication Flow Container
        self._flow_container = QWidget(self)
        self._flow_container.setGeometry(0, 0, self.width(), self.height())
        self._flow_container.setStyleSheet("background: transparent;")
        self._flow_container.setMouseTracking(True)

        main_lay = QVBoxLayout(self._flow_container)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        # 3. Dedicated Glassmorphism Card (AuthCard)
        # Sits centered vertically, beneath the central AI Core
        self._card = QFrame(self._flow_container)
        self._card.setObjectName("AuthCard")
        self._card.setFixedWidth(430)
        self._card.setStyleSheet("""
            QFrame#AuthCard {
                background: rgba(8, 14, 26, 0.84);
                border: 1px solid rgba(0, 212, 255, 0.35);
                border-radius: 22px;
            }
        """)

        card_lay = QVBoxLayout(self._card)
        card_lay.setContentsMargins(28, 28, 28, 24)
        card_lay.setSpacing(0)

        # 4. View Switcher inside Card
        self._stack = QStackedWidget(self._card)
        self._stack.setStyleSheet("background: transparent;")

        self.signin_view = SignInView(self._stack)
        self.signup_view = SignUpView(self._stack)
        self.setup_name_view = SetupNameView(self._stack)
        self.setup_voice_view = SetupVoiceView(self._stack)

        self._stack.addWidget(self.signin_view)        # Index 0: Login
        self._stack.addWidget(self.signup_view)        # Index 1: Signup
        self._stack.addWidget(self.setup_name_view)    # Index 2: Name
        self._stack.addWidget(self.setup_voice_view)   # Index 3: Voice

        card_lay.addWidget(self._stack)

        # Spacing to anchor the card beneath the central AI core
        self._top_spacer = QWidget()
        py_init = max(110.0, self.height() * 0.17)
        scale_init = min(1.15, max(0.72, self.height() / 1080.0))
        self._top_spacer.setFixedHeight(int(py_init + 120.0 * scale_init))
        self._top_spacer.setStyleSheet("background: transparent;")

        main_lay.addWidget(self._top_spacer)
        main_lay.addWidget(self._card, alignment=Qt.AlignmentFlag.AlignHCenter)
        main_lay.addStretch(1)

        # Focus reactivity on inputs
        for inp in (
            self.signin_view._username, self.signin_view._password,
            self.signup_view._username, self.signup_view._email,
            self.signup_view._password, self.signup_view._confirm,
            self.setup_name_view._input,
        ):
            inp.focus_changed.connect(self._bg.set_focused)

        # Wire transitions
        self.signin_view.switch_to_signup.connect(self._show_signup)
        self.signin_view.submit_requested.connect(self._on_login_submit)

        self.signup_view.switch_to_login.connect(self._show_signin)
        self.signup_view.submit_requested.connect(self._on_signup_submit)

        self.setup_name_view.name_submitted.connect(self._on_name_submitted)
        self.setup_voice_view.voice_submitted.connect(self._on_voice_submitted)

        # Smooth fade-in
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
        if hasattr(self, "_bg") and self._bg:
            self._bg.setGeometry(0, 0, w, h)
        if hasattr(self, "_flow_container") and self._flow_container:
            self._flow_container.setGeometry(0, 0, w, h)
        if hasattr(self, "_top_spacer") and self._top_spacer:
            # Dynamically adapt top offset based on window height so card sits cleanly beneath tagline
            py = max(110.0, h * 0.17)
            scale = min(1.15, max(0.72, h / 1080.0))
            spacer_h = int(py + 120.0 * scale)
            self._top_spacer.setFixedHeight(spacer_h)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if hasattr(self, "_bg") and self._bg:
            self._bg.set_mouse_position(pos)

        if hasattr(self, "_drag_pos") and e.buttons() == Qt.MouseButton.LeftButton:
            delta = e.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = e.globalPosition().toPoint()

    def _show_signin(self):
        self.signin_view.clear_fields()
        self.signin_view.clear_error()
        self._stack.setCurrentIndex(0)
        self.signin_view._username.setFocus()

    def _show_signup(self):
        self.signup_view.clear_fields()
        self.signup_view.clear_error()
        self._stack.setCurrentIndex(1)
        self.signup_view._username.setFocus()

    # ── Login Authentication ──────────────────────────────────────────────────
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

    # ── Signup Registration ───────────────────────────────────────────────────
    def _on_signup_submit(self, username: str, password: str, confirm_pass: str):
        self.signup_view.clear_error()
        self.signup_view.set_loading(True)

        email = self.signup_view._email.text().strip()
        self._auth_thread = AuthThread(username, password, mode="signup", email=email)
        self._auth_thread.success.connect(self._on_signup_success)
        self._auth_thread.failed.connect(self._on_signup_failed)
        self._auth_thread.start()

    def _on_signup_success(self, user_id: int, username: str, result_type):
        self.signup_view.set_loading(False)
        self._user_id = user_id
        self._username = username

        # Transition to Onboarding Step 1: Name Assistant
        self._stack.setCurrentIndex(2)
        self.setup_name_view._input.setFocus()

    def _on_signup_failed(self, msg: str):
        self.signup_view.set_loading(False)
        self.signup_view.show_error(msg)

    # ── Onboarding Steps ──────────────────────────────────────────────────────
    def _on_name_submitted(self, name: str):
        try:
            if getattr(sys, "frozen", False):
                from core.api_client import get_api_client
                get_api_client()._request(
                    "/api/users/me/preferences",
                    method="POST",
                    payload={"assistant_name": name}
                )
            else:
                from legacy.memory_manager import set_assistant_name_db
                set_assistant_name_db(self._user_id, name)
                from instance.config import settings
                settings.CURRENT_ASSISTANT_NAME = name
        except Exception as e:
            print(f"[LOGIN] Failed to save assistant name: {e}")

        self.setup_voice_view.update_name(name)
        self._stack.setCurrentIndex(3)

    def _on_voice_submitted(self, profile: dict):
        try:
            if getattr(sys, "frozen", False):
                from core.api_client import get_api_client
                get_api_client()._request(
                    "/api/users/me/preferences",
                    method="POST",
                    payload={"voice_profile": profile}
                )
            else:
                from legacy.memory_manager import set_voice_profile_db
                set_voice_profile_db(
                    self._user_id,
                    voice_id=profile.get("voice_id") or "",
                    voice_gender=profile.get("voice_gender", "female"),
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

    # ── Transition to Dashboard ───────────────────────────────────────────────
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
