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
from core.credential_manager import (
    get_credential_manager,
    validate_assistant_name,
    mask_credential,
    sanitize_log_message,
)
from legacy.tts import enumerate_voices, stop_speaking, apply_voice_profile


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
# IN-MEMORY TEMPORARY SIGNUP SESSION (STAGING BEFORE COMMITTING ACCOUNT)
# ─────────────────────────────────────────────────────────────────────────────
class TemporarySignupSession:
    """
    In-memory temporary staged signup session.
    Keeps username, email, password, staged validated credentials, assistant name, and voice profile.
    NEVER creates any DB account records or active credentials until Step 9 (final commit).
    Guarantees clean state if setup is closed or abandoned without leaving orphaned records.
    """
    def __init__(self):
        self.username: str = ""
        self.email: str = ""
        self.password: str = ""
        self.staged_credentials: dict[str, str] = {}  # provider_id -> raw key string
        self.primary_provider: str = ""
        self.assistant_name: str = "Friday"
        self.voice_profile: dict = {
            "voice_id": "",
            "voice_name": "System Default Voice",
            "voice_gender": "female",
            "voice_tone": "professional",
            "voice_rate": 135,
            "voice_volume": 1.0,
            "language": "English (United States)",
            "provider": "sapi5",
        }

    def has_valid_ai_credential(self) -> bool:
        ai_providers = {"groq", "openai", "gemini", "ollama", "deepseek", "anthropic", "huggingface"}
        return any(p in ai_providers and bool(self.staged_credentials.get(p)) for p in self.staged_credentials)

    def get_configured_ai_providers(self) -> list[str]:
        ai_providers = ["groq", "openai", "gemini", "ollama", "deepseek", "anthropic", "huggingface"]
        return [p for p in ai_providers if p in self.staged_credentials]

    def clear(self):
        self.username = ""
        self.email = ""
        self.password = ""
        self.staged_credentials.clear()
        self.primary_provider = ""
        self.assistant_name = "Friday"
        self.voice_profile = {
            "voice_id": "",
            "voice_name": "System Default Voice",
            "voice_gender": "female",
            "voice_tone": "professional",
            "voice_rate": 135,
            "voice_volume": 1.0,
            "language": "English (United States)",
            "provider": "sapi5",
        }


# ─────────────────────────────────────────────────────────────────────────────
# VIEW: SIGN UP / REGISTRATION (STEP 2: ACCOUNT CREDENTIALS SETUP)
# ─────────────────────────────────────────────────────────────────────────────
class SignUpView(QWidget):
    account_info_submitted = pyqtSignal(str, str, str)  # (username, email, password)
    switch_to_login = pyqtSignal()
    _username_check_done = pyqtSignal(bool, str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._username_check_done.connect(self._on_username_check_completed)
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
        self._username = IconInputField("Username", ICONS.USER, is_password=False)
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

        # Primary Button: Continue to Mandatory AI Key Setup →
        self._btn_submit = QPushButton("Continue to AI Setup   →")
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
        em = self._email.text().strip()
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
        if len(p) < 4:
            self.show_error("Password must be at least 4 characters.")
            return
        if p != cp:
            self.show_error("Passwords do not match. Please re-enter.")
            return
        if not self._terms.isChecked():
            self.show_error("Please accept the Terms of Service to continue.")
            return

        self.clear_error()
        self.set_loading(True)

        def _check_async():
            avail = True
            try:
                if getattr(sys, "frozen", False):
                    from core.api_client import get_api_client
                    res = get_api_client().check_username(u)
                    avail = bool(res.get("available", True))
                else:
                    from core.auth_service import is_username_available
                    avail = is_username_available(u)
            except Exception:
                avail = True

            self._username_check_done.emit(avail, u, em, p)

        threading.Thread(target=_check_async, daemon=True).start()

    def _on_username_check_completed(self, avail: bool, u: str, em: str, p: str):
        self.set_loading(False)
        if not avail:
            self.show_error("That username is already taken. Please choose another or Sign In.")
        else:
            self.account_info_submitted.emit(u, em, p)

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
        self._btn_submit.setText("Verifying..." if loading else "Continue to AI Setup   →")


# ─────────────────────────────────────────────────────────────────────────────
# VIEW: ONBOARDING STEP 1 OF 4 — MANDATORY AI PROVIDER & MULTI-API KEYS
# ─────────────────────────────────────────────────────────────────────────────
class SetupAPIKeysView(QWidget):
    keys_confirmed = pyqtSignal()
    back_requested = pyqtSignal()
    setup_finished = pyqtSignal()
    _key_test_done = pyqtSignal(dict, str, str)
    _creds_status_done = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session: TemporarySignupSession | None = None
        self._user_id: int | None = None
        self._username: str | None = None
        self._key_test_done.connect(self._on_key_test_completed)
        self._creds_status_done.connect(self._on_creds_status_completed)
        self._build_ui()

    def init_signup_session(self, session: TemporarySignupSession):
        self._session = session
        self._user_id = None
        self._username = session.username
        self._key_input.clear()
        self._msg_lbl.setText("")
        self._refresh_configured_badges()
        self._update_primary_dropdown()

    def set_user(self, user_id: int, username: str):
        self._user_id = user_id
        self._username = username
        self._session = None
        self._load_status_existing_user()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Step Indicator
        step_lbl = QLabel("MANDATORY SETUP // STEP 1 OF 4")
        step_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        step_lbl.setStyleSheet("color: #00D4FF; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; background: transparent;")
        lay.addWidget(step_lbl)

        title = QLabel("AI Provider & Credentials")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #FFFFFF; font-size: 20px; font-weight: 700; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(title)

        sub = QLabel("At least one valid AI provider is required before account creation.\nYour credentials are encrypted locally with Windows DPAPI.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #8FA0B5; font-size: 11px; font-family: 'Segoe UI'; background: transparent; line-height: 1.3;")
        lay.addWidget(sub)

        # Provider Selector
        self._prov_combo = QComboBox()
        self._prov_combo.setFixedHeight(36)
        self._prov_combo.setStyleSheet("""
            QComboBox {
                background: rgba(12, 20, 36, 0.85);
                color: #ffffff;
                border: 1px solid rgba(0, 212, 255, 0.35);
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: 600;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #0B1626;
                color: #FFFFFF;
                selection-background-color: #00D4FF;
                selection-color: #000000;
            }
        """)

        self._providers = [
            ("groq", "Groq Cloud (Fast LLM - Free tier)", "Ultra-fast conversational AI"),
            ("openai", "OpenAI (GPT-4o, GPT-3.5)", "Advanced reasoning and chat completion"),
            ("gemini", "Google Gemini (Flash, Pro)", "Multimodal & general intelligence"),
            ("ollama", "Ollama (Local Offline LLM)", "Local inference daemon (no cloud key needed)"),
            ("deepseek", "DeepSeek", "Specialized coding and chat models"),
            ("anthropic", "Anthropic Claude", "Claude 3 models for reasoning"),
            ("huggingface", "HuggingFace", "Inference API router"),
            ("serpapi", "SerpAPI (Google Search)", "Real-time Google search results"),
            ("tavily", "Tavily Search", "Web search tailored for AI agents"),
            ("email", "Email Integration (App Password)", "Access and send personal emails"),
            ("openweather", "OpenWeatherMap", "Live weather forecasts and temperatures"),
            ("tmdb", "TMDB Movies & Series", "Movie recommendations and ratings"),
            ("calendarific", "Calendarific Holidays", "Public holiday calendars"),
        ]
        for pid, name, desc in self._providers:
            self._prov_combo.addItem(name, pid)
        self._prov_combo.currentIndexChanged.connect(self._on_provider_changed)
        lay.addWidget(self._prov_combo)

        # Feature description
        self._desc_lbl = QLabel(self._providers[0][2])
        self._desc_lbl.setStyleSheet("color: #00D4FF; font-size: 11px; font-weight: 500; background: transparent;")
        self._desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._desc_lbl)

        # Key Input with eye reveal
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self._key_input = QLineEdit()
        self._key_input.setFixedHeight(36)
        self._key_input.setPlaceholderText("Enter API key or credential...")
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setStyleSheet("""
            QLineEdit {
                background: rgba(12, 20, 36, 0.85);
                color: #ffffff;
                border: 1px solid rgba(40, 72, 115, 0.65);
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #00D4FF;
            }
        """)
        input_row.addWidget(self._key_input, 1)

        self._eye_btn = QPushButton("👁")
        self._eye_btn.setFixedSize(36, 36)
        self._eye_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._eye_btn.setStyleSheet("""
            QPushButton {
                background: rgba(12, 20, 36, 0.85);
                color: #8FA0B5;
                border: 1px solid rgba(40, 72, 115, 0.65);
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton:hover {
                color: #00D4FF;
                border-color: #00D4FF;
            }
        """)
        self._eye_btn.clicked.connect(self._toggle_echo)
        input_row.addWidget(self._eye_btn)
        lay.addLayout(input_row)

        # Action: Validate & Add Provider Button
        self._add_btn = QPushButton("Validate & Save Provider")
        self._add_btn.setFixedHeight(34)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 212, 255, 0.15);
                color: #00D4FF;
                border: 1px solid rgba(0, 212, 255, 0.50);
                border-radius: 8px;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: rgba(0, 212, 255, 0.28);
            }
            QPushButton:disabled {
                background: rgba(40, 60, 90, 0.3);
                color: #64748B;
                border-color: #334155;
            }
        """)
        self._add_btn.clicked.connect(self._on_validate_and_add)
        lay.addWidget(self._add_btn)

        # Feedback / Message Label
        self._msg_lbl = QLabel("")
        self._msg_lbl.setStyleSheet("color: #FFFFFF; font-size: 11px; background: transparent;")
        self._msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg_lbl.setWordWrap(True)
        lay.addWidget(self._msg_lbl)

        # Configured Providers Badge Container
        self._badges_box = QFrame()
        self._badges_box.setStyleSheet("background: rgba(10, 18, 32, 0.6); border: 1px dashed rgba(40, 72, 115, 0.5); border-radius: 8px; padding: 4px;")
        self._badges_lay = QVBoxLayout(self._badges_box)
        self._badges_lay.setContentsMargins(6, 4, 6, 4)
        self._badges_lay.setSpacing(4)
        self._badges_title = QLabel("Configured Providers: (None yet - 1 required)")
        self._badges_title.setStyleSheet("color: #FFA500; font-size: 11px; font-weight: 600; background: transparent;")
        self._badges_lay.addWidget(self._badges_title)
        lay.addWidget(self._badges_box)

        # Primary Provider Selector (if multiple configured)
        prim_row = QHBoxLayout()
        prim_lbl = QLabel("Primary AI Provider:")
        prim_lbl.setStyleSheet("color: #8FA0B5; font-size: 11px; font-weight: 600; background: transparent;")
        prim_row.addWidget(prim_lbl)
        self._primary_combo = QComboBox()
        self._primary_combo.setFixedHeight(30)
        self._primary_combo.setStyleSheet("""
            QComboBox {
                background: rgba(12, 20, 36, 0.85);
                color: #00D4FF;
                border: 1px solid rgba(0, 212, 255, 0.35);
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 700;
            }
            QComboBox QAbstractItemView {
                background: #0B1626;
                color: #FFFFFF;
                selection-background-color: #00D4FF;
                selection-color: #000000;
            }
        """)
        self._primary_combo.currentIndexChanged.connect(self._on_primary_changed)
        prim_row.addWidget(self._primary_combo, 1)
        lay.addLayout(prim_row)

        lay.addSpacing(4)

        # Continue Button: Continue to Step 2
        self._continue_btn = QPushButton("Continue to Assistant Personalization   →")
        self._continue_btn.setFixedHeight(42)
        self._continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._continue_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00D4FF, stop:1 #9B51E0);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 21px;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1AE0FF, stop:1 #A855F7);
            }
        """)
        self._continue_btn.clicked.connect(self._on_continue)
        lay.addWidget(self._continue_btn)

        # Back Button: Back to Account Credentials
        self._back_btn = QPushButton("← Back to Account Credentials")
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8FA0B5;
                border: none;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                color: #00D4FF;
                text-decoration: underline;
            }
        """)
        self._back_btn.clicked.connect(self.back_requested.emit)
        lay.addWidget(self._back_btn)

    def _toggle_echo(self):
        if self._key_input.echoMode() == QLineEdit.EchoMode.Password:
            self._key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self._eye_btn.setText("🔒")
        else:
            self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self._eye_btn.setText("👁")

    def _on_provider_changed(self, idx: int):
        if 0 <= idx < len(self._providers):
            pid, name, desc = self._providers[idx]
            self._desc_lbl.setText(desc)
            self._key_input.clear()
            self._msg_lbl.setText("")
            if pid == "ollama":
                self._key_input.setPlaceholderText("http://localhost:11434 (or leave blank for default)")
            else:
                self._key_input.setPlaceholderText("Enter API key or credential...")

    def _on_validate_and_add(self):
        pid = self._prov_combo.currentData()
        val = self._key_input.text().strip()

        # Reject empty keys for non-ollama providers immediately
        if not val and pid != "ollama":
            self._msg_lbl.setText("✖ API key cannot be empty or whitespace.")
            self._msg_lbl.setStyleSheet("color: #EF4444; font-size: 11px; font-weight: 600;")
            return

        self._add_btn.setEnabled(False)
        self._msg_lbl.setText("Validating authentication probe...")
        self._msg_lbl.setStyleSheet("color: #00D4FF; font-size: 11px;")

        def _worker():
            try:
                from core.credential_manager import get_credential_manager
                mgr = get_credential_manager()
                res = mgr.test_provider_connection(self._user_id, pid, candidate_key=val or None)
            except Exception as e:
                res = {"success": False, "status": "error", "message": sanitize_log_message(str(e))}
            self._key_test_done.emit(res, pid, val)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_key_test_completed(self, res: dict, pid: str, val: str):
        self._add_btn.setEnabled(True)
        if res.get("success"):
            self._msg_lbl.setText(f"✔ {res.get('message', 'Credential verified!')}")
            self._msg_lbl.setStyleSheet("color: #4ADE80; font-size: 11px; font-weight: 600;")

            # Stage in session or save for existing user
            if self._session is not None:
                self._session.staged_credentials[pid] = val or "http://localhost:11434"
                if not self._session.primary_provider and pid in ("groq", "openai", "gemini", "ollama", "deepseek", "anthropic", "huggingface"):
                    self._session.primary_provider = pid
                self._refresh_configured_badges()
                self._update_primary_dropdown()
            elif self._user_id is not None:
                try:
                    from core.credential_manager import get_credential_manager
                    get_credential_manager().save_credential(self._user_id, pid, val or "http://localhost:11434")
                    self._load_status_existing_user()
                except Exception:
                    pass
            self._key_input.clear()
        else:
            self._msg_lbl.setText(f"✖ {res.get('message', 'Validation failed.')}")
            self._msg_lbl.setStyleSheet("color: #EF4444; font-size: 11px; font-weight: 600;")

    def _refresh_configured_badges(self):
        if not self._session:
            return
        staged = self._session.staged_credentials
        ai_staged = self._session.get_configured_ai_providers()

        # Clear existing dynamic items except title
        while self._badges_lay.count() > 1:
            item = self._badges_lay.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

        if ai_staged:
            self._badges_title.setText(f"Configured Providers: ({len(staged)} active, {len(ai_staged)} AI engine)")
            self._badges_title.setStyleSheet("color: #4ADE80; font-size: 11px; font-weight: 600; background: transparent;")
        else:
            self._badges_title.setText("Configured Providers: (None yet - At least 1 AI provider required)")
            self._badges_title.setStyleSheet("color: #FFA500; font-size: 11px; font-weight: 600; background: transparent;")

        for p, key_val in staged.items():
            row = QHBoxLayout()
            masked = "local daemon" if p == "ollama" else mask_credential(key_val)
            lbl = QLabel(f"✔ <b>{p.upper()}</b> <span style='color:#8FA0B5;'>({masked})</span>")
            lbl.setStyleSheet("color: #FFFFFF; font-size: 11px;")
            row.addWidget(lbl, 1)

            del_btn = QPushButton("✕")
            del_btn.setFixedSize(20, 20)
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setStyleSheet("color: #EF4444; background: transparent; border: none; font-size: 12px; font-weight: 700;")
            del_btn.clicked.connect(lambda _, prov=p: self._remove_staged_provider(prov))
            row.addWidget(del_btn)
            self._badges_lay.addLayout(row)

    def _remove_staged_provider(self, prov: str):
        if self._session and prov in self._session.staged_credentials:
            del self._session.staged_credentials[prov]
            if self._session.primary_provider == prov:
                configured_ai = self._session.get_configured_ai_providers()
                self._session.primary_provider = configured_ai[0] if configured_ai else ""
            self._refresh_configured_badges()
            self._update_primary_dropdown()

    def _update_primary_dropdown(self):
        self._primary_combo.blockSignals(True)
        self._primary_combo.clear()
        if self._session:
            configured_ai = self._session.get_configured_ai_providers()
            for p in configured_ai:
                self._primary_combo.addItem(p.upper(), p)
            if self._session.primary_provider:
                idx = self._primary_combo.findData(self._session.primary_provider)
                if idx >= 0:
                    self._primary_combo.setCurrentIndex(idx)
        self._primary_combo.blockSignals(False)

    def _on_primary_changed(self, idx: int):
        val = self._primary_combo.itemData(idx)
        if val and self._session:
            self._session.primary_provider = val

    def _on_continue(self):
        if self._session:
            if not self._session.has_valid_ai_credential():
                self._msg_lbl.setText("✖ At least one valid AI provider (e.g. Groq, OpenAI, Gemini, Ollama) must be verified before continuing.")
                self._msg_lbl.setStyleSheet("color: #EF4444; font-size: 11px; font-weight: 600;")
                return
            self.keys_confirmed.emit()
        else:
            self.setup_finished.emit()

    def _load_status_existing_user(self):
        def _worker():
            try:
                from modules.ui.dashboard.service_adapters import load_api_credentials_status
                res = load_api_credentials_status(self._user_id)
            except Exception:
                res = []
            self._creds_status_done.emit(res or [])
        threading.Thread(target=_worker, daemon=True).start()

    def _on_creds_status_completed(self, res: list):
        while self._badges_lay.count() > 1:
            item = self._badges_lay.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        configured = [c for c in (res or []) if c.get("configured")]
        if configured:
            self._badges_title.setText(f"Configured Credentials ({len(configured)} active):")
            self._badges_title.setStyleSheet("color: #4ADE80; font-size: 11px; font-weight: 600;")
            for c in configured:
                lbl = QLabel(f"✔ <b>{c.get('provider', '').upper()}</b>: {c.get('masked_hint', '')}")
                lbl.setStyleSheet("color: #FFFFFF; font-size: 11px;")
                self._badges_lay.addWidget(lbl)
        else:
            self._badges_title.setText("Configured Providers: (None)")


# ─────────────────────────────────────────────────────────────────────────────
# VIEW: ONBOARDING STEP 2 OF 4 — NAME YOUR ASSISTANT
# ─────────────────────────────────────────────────────────────────────────────
class SetupNameView(QWidget):
    name_submitted = pyqtSignal(str)
    back_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session: TemporarySignupSession | None = None
        self._build_ui()

    def init_session(self, session: TemporarySignupSession):
        self._session = session
        cur_name = session.assistant_name or "Friday"
        self._input.setText(cur_name)
        self._update_preview(cur_name)
        self._err.hide()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Step indicator
        step_lbl = QLabel("PERSONALIZATION // STEP 2 OF 4")
        step_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        step_lbl.setStyleSheet("color: #00D4FF; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; background: transparent;")
        lay.addWidget(step_lbl)

        title = QLabel("Name Your Assistant")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #FFFFFF; font-size: 22px; font-weight: 700; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(title)

        sub = QLabel("Choose what you'd like your AI companion to be called.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #8FA0B5; font-size: 12px; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(sub)

        lay.addSpacing(4)

        self._input = IconInputField("Assistant name (e.g. Friday, Jarvis, Trevon)", ICONS.ASSISTANT, is_password=False)
        self._input.setText("Friday")
        self._input.textChanged.connect(self._update_preview)
        self._input.returnPressed.connect(self._on_submit)
        lay.addWidget(self._input)

        # Live UI Preview Card
        self._preview_card = QFrame()
        self._preview_card.setStyleSheet("""
            QFrame {
                background: rgba(10, 18, 32, 0.75);
                border: 1px solid rgba(0, 212, 255, 0.35);
                border-radius: 12px;
                padding: 10px;
            }
        """)
        prev_lay = QVBoxLayout(self._preview_card)
        prev_lay.setContentsMargins(10, 10, 10, 10)
        prev_lay.setSpacing(6)

        prev_header = QLabel("AI COMPANION // LIVE PREVIEW")
        prev_header.setStyleSheet("color: #00D4FF; font-size: 10px; font-weight: 700; letter-spacing: 1.2px;")
        prev_lay.addWidget(prev_header)

        self._prev_msg = QLabel("“Hello! I am Friday. Your system is online and ready.”")
        self._prev_msg.setWordWrap(True)
        self._prev_msg.setStyleSheet("color: #E2E8F0; font-size: 12px; font-style: italic; font-family: 'Segoe UI';")
        prev_lay.addWidget(self._prev_msg)

        lay.addWidget(self._preview_card)

        # Error label
        self._err = QLabel("")
        self._err.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._err.setStyleSheet("color: #EF4444; font-size: 11px; background: rgba(239, 68, 68, 0.1); border-radius: 6px; padding: 4px;")
        self._err.hide()
        lay.addWidget(self._err)

        lay.addSpacing(6)

        btn = QPushButton("Continue to Voice Setup   →")
        btn.setFixedHeight(46)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00D4FF, stop:1 #9B51E0);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 23px;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1AE0FF, stop:1 #A855F7);
            }
        """)
        btn.clicked.connect(self._on_submit)
        lay.addWidget(btn)

        back_btn = QPushButton("← Back to AI Provider Setup")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8FA0B5;
                border: none;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                color: #00D4FF;
                text-decoration: underline;
            }
        """)
        back_btn.clicked.connect(self.back_requested.emit)
        lay.addWidget(back_btn)

    def _update_preview(self, text: str):
        display_name = text.strip() or "Friday"
        self._prev_msg.setText(f"“Hello! I am {display_name}. Your system is online and ready.”")

    def _on_submit(self):
        raw_name = self._input.text().strip()
        if raw_name and len(raw_name) < 2:
            self._err.setText("✖ Assistant name must be at least 2 characters.")
            self._err.show()
            return
        validated_name = validate_assistant_name(raw_name or "Friday")
        self._err.hide()
        if self._session:
            self._session.assistant_name = validated_name
        self.name_submitted.emit(validated_name)


# ─────────────────────────────────────────────────────────────────────────────
# VIEW: ONBOARDING STEP 3 OF 4 — VOICE PERSONALIZATION & AUDITION
# ─────────────────────────────────────────────────────────────────────────────
class SetupVoiceView(QWidget):
    voice_submitted = pyqtSignal(dict)
    back_requested = pyqtSignal()
    _voices_loaded_signal = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session: TemporarySignupSession | None = None
        self._assistant_name = "Friday"
        self._current_filter = "female"
        self._all_voices = []
        self._voices_loaded_signal.connect(self._on_voices_loaded)
        self._build_ui()
        self._load_voices_async()

    def init_session(self, session: TemporarySignupSession):
        self._session = session
        self._assistant_name = session.assistant_name or "Friday"
        self._sub.setText(f"Audition and select the speaking voice for {self._assistant_name}.")
        self._filter_and_populate_voices()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        step_lbl = QLabel("PERSONALIZATION // STEP 3 OF 4")
        step_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        step_lbl.setStyleSheet("color: #00D4FF; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; background: transparent;")
        lay.addWidget(step_lbl)

        title = QLabel("Select Voice Profile")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #FFFFFF; font-size: 22px; font-weight: 700; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(title)

        self._sub = QLabel("Select the voice and speaking tone for your assistant.")
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub.setStyleSheet("color: #8FA0B5; font-size: 11px; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(self._sub)

        # Category Filter Buttons: Female / Male / All
        cat_box = QHBoxLayout()
        cat_box.setSpacing(6)
        cat_lbl = QLabel("Voice Category:")
        cat_lbl.setStyleSheet("color: #8FA0B5; font-size: 11px; font-weight: 600; background: transparent;")
        cat_box.addWidget(cat_lbl)

        self._btn_fem = QPushButton("👩 Female")
        self._btn_fem.setCheckable(True)
        self._btn_fem.setChecked(True)
        self._btn_fem.setFixedHeight(28)
        self._btn_fem.setCursor(Qt.CursorShape.PointingHandCursor)

        self._btn_male = QPushButton("👨 Male")
        self._btn_male.setCheckable(True)
        self._btn_male.setFixedHeight(28)
        self._btn_male.setCursor(Qt.CursorShape.PointingHandCursor)

        self._btn_all = QPushButton("🌐 All")
        self._btn_all.setCheckable(True)
        self._btn_all.setFixedHeight(28)
        self._btn_all.setCursor(Qt.CursorShape.PointingHandCursor)

        self._cat_style_active = "background: #00D4FF; color: #000000; font-weight: 700; border-radius: 6px; padding: 2px 8px; font-size: 11px;"
        self._cat_style_inactive = "background: rgba(12, 20, 36, 0.8); color: #8FA0B5; border: 1px solid rgba(40, 72, 115, 0.65); border-radius: 6px; padding: 2px 8px; font-size: 11px;"

        self._btn_fem.setStyleSheet(self._cat_style_active)
        self._btn_male.setStyleSheet(self._cat_style_inactive)
        self._btn_all.setStyleSheet(self._cat_style_inactive)

        self._btn_fem.clicked.connect(lambda: self._set_category_filter("female"))
        self._btn_male.clicked.connect(lambda: self._set_category_filter("male"))
        self._btn_all.clicked.connect(lambda: self._set_category_filter("all"))

        cat_box.addWidget(self._btn_fem)
        cat_box.addWidget(self._btn_male)
        cat_box.addWidget(self._btn_all)
        lay.addLayout(cat_box)

        # Voice selection combo
        self._voice_combo = QComboBox()
        self._voice_combo.setFixedHeight(38)
        self._voice_combo.setStyleSheet("""
            QComboBox {
                background: rgba(12, 20, 36, 0.85);
                color: #ffffff;
                border: 1px solid rgba(40, 72, 115, 0.65);
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 12px;
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

        # Preview Audition Button
        self._preview_btn = QPushButton("▶  Audition Voice Sample")
        self._preview_btn.setFixedHeight(36)
        self._preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 212, 255, 0.12);
                color: #00D4FF;
                border: 1px solid rgba(0, 212, 255, 0.40);
                border-radius: 8px;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: rgba(0, 212, 255, 0.22);
                border-color: #00D4FF;
            }
        """)
        self._preview_btn.clicked.connect(self._preview_voice)
        lay.addWidget(self._preview_btn)

        # Speaking Tone Combo
        tone_box = QHBoxLayout()
        tone_lbl = QLabel("Speaking Tone:")
        tone_lbl.setStyleSheet("color: #8FA0B5; font-size: 11px; font-weight: 600; background: transparent;")
        tone_box.addWidget(tone_lbl)

        self._tone_combo = QComboBox()
        self._tone_combo.setFixedHeight(32)
        self._tone_combo.setStyleSheet("""
            QComboBox {
                background: rgba(12, 20, 36, 0.85);
                color: #ffffff;
                border: 1px solid rgba(40, 72, 115, 0.65);
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 11px;
            }
            QComboBox QAbstractItemView {
                background: #0B1626;
                color: #FFFFFF;
                selection-background-color: #00D4FF;
                selection-color: #000000;
            }
        """)
        for tname in ["Professional", "Casual", "Direct", "Calm"]:
            self._tone_combo.addItem(tname)
        tone_box.addWidget(self._tone_combo, 1)
        lay.addLayout(tone_box)

        lay.addSpacing(4)

        # Finish / Continue button
        finish_btn = QPushButton("Continue to Review Summary   →")
        finish_btn.setFixedHeight(44)
        finish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        finish_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00D4FF, stop:1 #9B51E0);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 22px;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1AE0FF, stop:1 #A855F7);
            }
        """)
        finish_btn.clicked.connect(self._on_continue)
        lay.addWidget(finish_btn)

        back_btn = QPushButton("← Back to Assistant Name")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8FA0B5;
                border: none;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                color: #00D4FF;
                text-decoration: underline;
            }
        """)
        back_btn.clicked.connect(self.back_requested.emit)
        lay.addWidget(back_btn)

    def _set_category_filter(self, cat: str):
        self._current_filter = cat
        self._btn_fem.setChecked(cat == "female")
        self._btn_male.setChecked(cat == "male")
        self._btn_all.setChecked(cat == "all")

        self._btn_fem.setStyleSheet(self._cat_style_active if cat == "female" else self._cat_style_inactive)
        self._btn_male.setStyleSheet(self._cat_style_active if cat == "male" else self._cat_style_inactive)
        self._btn_all.setStyleSheet(self._cat_style_active if cat == "all" else self._cat_style_inactive)
        self._filter_and_populate_voices()

    def _load_voices_async(self):
        def _worker():
            try:
                voices = enumerate_voices()
            except Exception:
                voices = []
            self._voices_loaded_signal.emit(voices)
        threading.Thread(target=_worker, daemon=True).start()

    def _on_voices_loaded(self, voices: list):
        self._all_voices = voices or []
        self._filter_and_populate_voices()

    def _filter_and_populate_voices(self):
        self._voice_combo.clear()
        matching = []
        if self._current_filter == "all":
            matching = list(self._all_voices)
        else:
            matching = [v for v in self._all_voices if v.get("gender") == self._current_filter]

        if not matching:
            # Fallback to all if category has no system voices
            matching = list(self._all_voices)

        if not matching:
            self._voice_combo.addItem("System Default Voice", None)
            return

        for v in matching:
            name = v.get("name", "Voice")
            g = v.get("gender", "unknown").capitalize()
            lang = v.get("language", "English")
            prov = v.get("provider", "sapi5")
            label = f"{name} — {g} ({lang}, {prov})"
            self._voice_combo.addItem(label, v)
        self._voice_combo.setCurrentIndex(0)

    def _preview_voice(self):
        v_data = self._voice_combo.currentData()
        vid = v_data.get("id") if isinstance(v_data, dict) else None
        preview_text = f"Hello, I am {self._assistant_name}. Your system is online and ready."

        def _speak():
            try:
                # Stop any previous speech
                stop_speaking(interrupted=True)
                from legacy.tts import preview_voice
                preview_voice(vid, preview_text)
            except Exception as e:
                print(f"[VOICE SETUP] Preview error: {e}")

        threading.Thread(target=_speak, daemon=True).start()

    def _on_continue(self):
        v_data = self._voice_combo.currentData()
        vid = v_data.get("id") if isinstance(v_data, dict) else ""
        vname = v_data.get("name") if isinstance(v_data, dict) else "System Default Voice"
        vgender = v_data.get("gender") if isinstance(v_data, dict) else self._current_filter
        vlang = v_data.get("language") if isinstance(v_data, dict) else "English (United States)"
        vprov = v_data.get("provider") if isinstance(v_data, dict) else "sapi5"

        rate_map = {"Professional": 155, "Casual": 165, "Direct": 175, "Calm": 140}
        tone = self._tone_combo.currentText()
        rate = rate_map.get(tone, 155)

        profile = {
            "voice_id": vid,
            "voice_name": vname,
            "voice_gender": vgender,
            "voice_tone": tone.lower(),
            "voice_rate": rate,
            "voice_volume": 1.0,
            "language": vlang,
            "provider": vprov,
        }
        if self._session:
            self._session.voice_profile = profile
        self.voice_submitted.emit(profile)


# ─────────────────────────────────────────────────────────────────────────────
# VIEW: ONBOARDING STEP 4 OF 4 — SUMMARY & ATOMIC ACCOUNT ACTIVATION
# ─────────────────────────────────────────────────────────────────────────────
class SignupSummaryView(QWidget):
    commit_requested = pyqtSignal()
    back_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        step_lbl = QLabel("SUMMARY & ACTIVATION // STEP 4 OF 4")
        step_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        step_lbl.setStyleSheet("color: #00D4FF; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; background: transparent;")
        lay.addWidget(step_lbl)

        title = QLabel("Review & Initialize")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #FFFFFF; font-size: 22px; font-weight: 700; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(title)

        sub = QLabel("Confirm your configuration before your account is created.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #8FA0B5; font-size: 11px; font-family: 'Segoe UI'; background: transparent;")
        lay.addWidget(sub)

        # Summary Card
        self._card = QFrame()
        self._card.setStyleSheet("""
            QFrame {
                background: rgba(10, 18, 32, 0.85);
                border: 1px solid rgba(0, 212, 255, 0.35);
                border-radius: 12px;
                padding: 12px;
            }
        """)
        c_lay = QVBoxLayout(self._card)
        c_lay.setContentsMargins(12, 10, 12, 10)
        c_lay.setSpacing(6)

        self._lbl_user = QLabel("• Account: —")
        self._lbl_user.setStyleSheet("color: #FFFFFF; font-size: 12px;")
        c_lay.addWidget(self._lbl_user)

        self._lbl_name = QLabel("• Assistant Name: —")
        self._lbl_name.setStyleSheet("color: #00D4FF; font-size: 12px; font-weight: 700;")
        c_lay.addWidget(self._lbl_name)

        self._lbl_primary = QLabel("• Primary AI Provider: —")
        self._lbl_primary.setStyleSheet("color: #4ADE80; font-size: 12px; font-weight: 700;")
        c_lay.addWidget(self._lbl_primary)

        self._lbl_provs = QLabel("• Configured Providers: —")
        self._lbl_provs.setStyleSheet("color: #E2E8F0; font-size: 12px;")
        c_lay.addWidget(self._lbl_provs)

        self._lbl_voice = QLabel("• Voice Profile: —")
        self._lbl_voice.setStyleSheet("color: #E2E8F0; font-size: 12px;")
        c_lay.addWidget(self._lbl_voice)

        lay.addWidget(self._card)

        # Security Assurance Note
        sec_note = QLabel("🔒 Privacy Guarantee: Credentials are encrypted per-user with DPAPI. Zero developer keys are embedded.")
        sec_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sec_note.setWordWrap(True)
        sec_note.setStyleSheet("color: #728CA6; font-size: 10px; font-family: 'Segoe UI';")
        lay.addWidget(sec_note)

        # Error banner
        self._err = QLabel("")
        self._err.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._err.setStyleSheet("color: #EF4444; font-size: 11px; background: rgba(239, 68, 68, 0.1); border-radius: 6px; padding: 4px;")
        self._err.hide()
        lay.addWidget(self._err)

        lay.addSpacing(4)

        # Commit & Launch Button
        self._btn_commit = QPushButton("Create Account & Activate Assistant   →")
        self._btn_commit.setFixedHeight(46)
        self._btn_commit.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_commit.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00D4FF, stop:1 #9B51E0);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 23px;
                font-size: 14px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1AE0FF, stop:1 #A855F7);
            }
            QPushButton:disabled {
                background: #1E293B;
                color: #64748B;
                border-color: #334155;
            }
        """)
        self._btn_commit.clicked.connect(self.commit_requested.emit)
        lay.addWidget(self._btn_commit)

        back_btn = QPushButton("← Back to Voice Selection")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8FA0B5;
                border: none;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                color: #00D4FF;
                text-decoration: underline;
            }
        """)
        back_btn.clicked.connect(self.back_requested.emit)
        lay.addWidget(back_btn)

    def update_summary(self, session: TemporarySignupSession):
        self._lbl_user.setText(f"• Account: <b>{session.username}</b> ({session.email or 'Local Profile'})")
        self._lbl_name.setText(f"• Assistant Name: <b>{session.assistant_name}</b>")
        self._lbl_primary.setText(f"• Primary AI Provider: <b>{session.primary_provider.upper() or 'NONE'}</b>")
        configured_list = list(session.staged_credentials.keys())
        self._lbl_provs.setText(f"• Configured Providers: <b>{', '.join(configured_list).upper() if configured_list else 'None'}</b>")

        vp = session.voice_profile
        vname = vp.get("voice_name", "Default System Voice")
        vg = vp.get("voice_gender", "").capitalize()
        vlang = vp.get("language", "")
        self._lbl_voice.setText(f"• Voice: <b>{vname}</b> ({vg}, {vlang})")
        self.clear_error()

    def show_error(self, msg: str):
        self._err.setText(msg)
        self._err.show()

    def clear_error(self):
        self._err.hide()
        self._err.setText("")

    def set_loading(self, loading: bool):
        self._btn_commit.setEnabled(not loading)
        self._btn_commit.setText("Creating Account & Encrypting Keys..." if loading else "Create Account & Activate Assistant   →")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN AUTHENTICATION WINDOW (LOGIN, ONBOARDING & SIGNUP)
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
        self._signup_session = TemporarySignupSession()

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
        self._card = QFrame(self._flow_container)
        self._card.setObjectName("AuthCard")
        self._card.setFixedWidth(440)
        self._card.setStyleSheet("""
            QFrame#AuthCard {
                background: rgba(8, 14, 26, 0.88);
                border: 1px solid rgba(0, 212, 255, 0.35);
                border-radius: 22px;
            }
        """)

        card_lay = QVBoxLayout(self._card)
        card_lay.setContentsMargins(28, 24, 28, 24)
        card_lay.setSpacing(0)

        # 4. View Switcher inside Card
        self._stack = QStackedWidget(self._card)
        self._stack.setStyleSheet("background: transparent;")

        self.signin_view = SignInView(self._stack)
        self.signup_view = SignUpView(self._stack)
        self.setup_api_keys_view = SetupAPIKeysView(self._stack)
        self.setup_name_view = SetupNameView(self._stack)
        self.setup_voice_view = SetupVoiceView(self._stack)
        self.signup_summary_view = SignupSummaryView(self._stack)

        self._stack.addWidget(self.signin_view)           # Index 0: Login
        self._stack.addWidget(self.signup_view)           # Index 1: Signup Account Info
        self._stack.addWidget(self.setup_api_keys_view)    # Index 2: Mandatory API Key Wizard
        self._stack.addWidget(self.setup_name_view)       # Index 3: Assistant Name Personalization
        self._stack.addWidget(self.setup_voice_view)      # Index 4: Voice Personalization
        self._stack.addWidget(self.signup_summary_view)   # Index 5: Summary & Final Activation

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
        self.signup_view.account_info_submitted.connect(self._on_signup_info_submitted)

        self.setup_api_keys_view.back_requested.connect(lambda: self._stack.setCurrentIndex(1))
        self.setup_api_keys_view.keys_confirmed.connect(self._on_keys_confirmed)
        self.setup_api_keys_view.setup_finished.connect(lambda: self._proceed(self._user_id, self._username, "account"))

        self.setup_name_view.back_requested.connect(lambda: self._stack.setCurrentIndex(2))
        self.setup_name_view.name_submitted.connect(self._on_name_submitted)

        self.setup_voice_view.back_requested.connect(lambda: self._stack.setCurrentIndex(3))
        self.setup_voice_view.voice_submitted.connect(self._on_voice_submitted)

        self.signup_summary_view.back_requested.connect(lambda: self._stack.setCurrentIndex(4))
        self.signup_summary_view.commit_requested.connect(self._on_commit_signup)

        # Smooth fade-in
        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(450)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.start()

    def closeEvent(self, event):
        # Clean up any staged registration session safely on close
        if hasattr(self, "_signup_session") and self._signup_session:
            self._signup_session.clear()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        if hasattr(self, "_bg") and self._bg:
            self._bg.setGeometry(0, 0, w, h)
        if hasattr(self, "_flow_container") and self._flow_container:
            self._flow_container.setGeometry(0, 0, w, h)
        if hasattr(self, "_top_spacer") and self._top_spacer:
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
        self._signup_session.clear()
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

        has_setup = False
        try:
            from modules.ui.dashboard.service_adapters import get_api_setup_status
            res = get_api_setup_status(user_id)
            has_setup = bool(res.get("completed", False)) if isinstance(res, dict) else bool(res)
        except Exception:
            has_setup = True

        if not has_setup:
            self.setup_api_keys_view.set_user(user_id, username)
            self._stack.setCurrentIndex(2)
        else:
            self._proceed(user_id, username, "account")

    def _on_login_failed(self, msg: str):
        self.signin_view.set_loading(False)
        self.signin_view.show_error(msg)

    # ── Onboarding Step Transitions ───────────────────────────────────────────
    def _on_signup_info_submitted(self, username: str, email: str, password: str):
        self._signup_session.username = username
        self._signup_session.email = email
        self._signup_session.password = password
        self.setup_api_keys_view.init_signup_session(self._signup_session)
        self._stack.setCurrentIndex(2)  # Step 1: Mandatory AI Key

    def _on_keys_confirmed(self):
        self.setup_name_view.init_session(self._signup_session)
        self._stack.setCurrentIndex(3)  # Step 2: Name Assistant

    def _on_name_submitted(self, name: str):
        self._signup_session.assistant_name = name
        self.setup_voice_view.init_session(self._signup_session)
        self._stack.setCurrentIndex(4)  # Step 3: Voice Selection

    def _on_voice_submitted(self, profile: dict):
        self._signup_session.voice_profile = profile
        self.signup_summary_view.update_summary(self._signup_session)
        self._stack.setCurrentIndex(5)  # Step 4: Summary & Commit

    # ── Step 9: Final Atomic Account Creation & Credentials Activation ─────────
    def _on_commit_signup(self):
        if not self._signup_session.has_valid_ai_credential():
            self.signup_summary_view.show_error("Validation error: At least one valid AI provider is mandatory before account creation.")
            return

        self.signup_summary_view.set_loading(True)
        u = self._signup_session.username
        p = self._signup_session.password
        em = self._signup_session.email

        self._auth_thread = AuthThread(u, p, mode="signup", email=em)
        self._auth_thread.success.connect(self._on_commit_signup_success)
        self._auth_thread.failed.connect(self._on_commit_signup_failed)
        self._auth_thread.start()

    def _on_commit_signup_success(self, user_id: int, username: str, result_type):
        self.signup_summary_view.set_loading(False)
        self._user_id = user_id
        self._username = username

        # 1. Save all validated credentials in the user vault
        mgr = get_credential_manager()
        for prov, key_val in self._signup_session.staged_credentials.items():
            mgr.save_credential(user_id, prov, key_val)

        # 2. Save primary provider preference
        if self._signup_session.primary_provider:
            mgr.set_primary_provider(user_id, self._signup_session.primary_provider)

        # 3. Save assistant name
        asst_name = self._signup_session.assistant_name or "Friday"
        try:
            from legacy.memory_manager import set_assistant_name_db
            set_assistant_name_db(user_id, asst_name)
            mgr.set_assistant_name(user_id, asst_name)
            from instance.config import settings
            settings.CURRENT_ASSISTANT_NAME = asst_name
        except Exception as e:
            print(f"[SIGNUP COMMIT] Error saving assistant name: {e}")

        # 4. Save voice profile
        v_prof = self._signup_session.voice_profile
        try:
            from legacy.memory_manager import set_voice_profile_db
            set_voice_profile_db(
                user_id,
                voice_id=v_prof.get("voice_id") or "",
                voice_gender=v_prof.get("voice_gender", "female"),
                voice_tone=v_prof.get("voice_tone", "professional"),
                voice_rate=int(v_prof.get("voice_rate", 135)),
                voice_volume=float(v_prof.get("voice_volume", 1.0)),
            )
            apply_voice_profile(
                v_prof.get("voice_id"),
                rate=int(v_prof.get("voice_rate", 135)),
                volume=float(v_prof.get("voice_volume", 1.0)),
            )
        except Exception as e:
            print(f"[SIGNUP COMMIT] Error saving voice profile: {e}")

        # 5. Mark setup completed
        mgr.set_completed_api_setup(user_id, True)

        # 5b. Initialize default capability consents in PostgreSQL
        try:
            from core.capability_consent_manager import get_capability_consent_manager
            get_capability_consent_manager().grant_all_default_consents(user_id)
        except Exception as e:
            print(f"[SIGNUP COMMIT] Capability consent initialization notice: {e}")

        # 6. Discard temporary signup session safely
        self._signup_session.clear()

        # 7. Proceed to launch assistant
        self._proceed(user_id, username, "account")

    def _on_commit_signup_failed(self, msg: str):
        self.signup_summary_view.set_loading(False)
        self.signup_summary_view.show_error(msg)

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
