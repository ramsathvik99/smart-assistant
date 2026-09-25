"""
Smart Assistant — PyQt6 Login Window
Intelligent personal assistant entry point with dynamic cybernetic background,
animated AI identity core, glassmorphic panel, real system telemetry, and smooth micro-interactions.
Connects directly to the existing authentication backend without altering auth logic.
"""

import math
import random
import time
import threading

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QGraphicsDropShadowEffect, QSizePolicy,
    QApplication, QToolButton, QComboBox, QScrollArea
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect,
    pyqtSignal, QThread, QObject, QPoint, pyqtProperty, QPointF
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QLinearGradient,
    QRadialGradient, QFont, QPainterPath, QFontMetrics,
    QCursor, QFocusEvent
)

from modules.ui.design_system import C, F, Spacing, Radius


# ─────────────────────────────────────────────────────────────────────────────
# AUTH WORKER & THREAD (PRESERVED CORE BACKEND LOGIC)
# ─────────────────────────────────────────────────────────────────────────────
class AuthWorker(QObject):
    success = pyqtSignal(int, str, object)   # (user_id, username, result_type)
    failed  = pyqtSignal(str)                # error message

    def __init__(self, username: str, password: str):
        super().__init__()
        self._username = username
        self._password = password

    def run(self):
        try:
            from legacy.memory_manager import get_or_create_user
            user_id, result = get_or_create_user(self._username, self._password)
            if result == "WRONG_PASSWORD":
                self.failed.emit("Incorrect password. Verification rejected.")
            elif user_id:
                self.success.emit(user_id, self._username, result)
            else:
                self.failed.emit("Authentication failed. Identity verification declined.")
        except Exception as e:
            self.failed.emit(f"Connection error: {e}")


class AuthThread(QThread):
    success = pyqtSignal(int, str, object)
    failed  = pyqtSignal(str)

    def __init__(self, username: str, password: str):
        super().__init__()
        self._w = AuthWorker(username, password)
        self._w.success.connect(self.success)
        self._w.failed.connect(self.failed)

    def run(self):
        self._w.run()


# ─────────────────────────────────────────────────────────────────────────────
# REAL-TIME SYSTEM TELEMETRY WORKER
# ─────────────────────────────────────────────────────────────────────────────
class SystemStatusWorker(QObject):
    """Checks actual PostgreSQL connection and runtime readiness."""
    status_ready = pyqtSignal(bool, str)  # (is_connected, db_message)

    def run(self):
        try:
            from legacy.memory_manager import get_connection
            conn = get_connection()
            if conn and conn.status == 1:
                conn.close()
                self.status_ready.emit(True, "DATABASE CONNECTED")
            else:
                if conn:
                    conn.close()
                self.status_ready.emit(False, "DATABASE UNRESPONSIVE")
        except Exception:
            self.status_ready.emit(False, "DATABASE OFFLINE")


class SystemStatusThread(QThread):
    status_ready = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        self._w = SystemStatusWorker()
        self._w.status_ready.connect(self.status_ready)

    def run(self):
        self._w.run()


# ─────────────────────────────────────────────────────────────────────────────
# ANIMATED AI ASSISTANT IDENTITY CORE
# ─────────────────────────────────────────────────────────────────────────────
class AssistantIdentityCore(QWidget):
    """
    Distinctive animated AI Identity Core.
    Features counter-rotating geometric segmented rings, a pulsating neural core,
    and reactive acceleration/glow when user inputs receive focus.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(88, 88)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._t = 0.0
        self._rot_outer = 0.0
        self._rot_inner = 0.0
        self._focus_intensity = 0.0  # 0.0 = idle, 1.0 = focused
        self._target_focus = 0.0

        # Animation loop at ~30 FPS for optimal performance
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step_animation)
        self._timer.start(33)

    def set_focused(self, focused: bool):
        self._target_focus = 1.0 if focused else 0.0

    def _step_animation(self):
        self._t += 0.035
        # Smooth interpolation of focus state
        self._focus_intensity += (self._target_focus - self._focus_intensity) * 0.15

        # Speed multiplies with focus intensity
        speed_mult = 1.0 + self._focus_intensity * 1.5
        self._rot_outer = (self._rot_outer + 1.2 * speed_mult) % 360.0
        self._rot_inner = (self._rot_inner - 1.8 * speed_mult) % 360.0

        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = self.width() / 2.0, self.height() / 2.0
        r_max = min(cx, cy) - 4

        # 1. Ambient Background Aura
        pulse = 0.82 + 0.18 * math.sin(self._t * 2.2)
        glow_alpha = int((30 + 35 * self._focus_intensity) * pulse)
        aura_rad = r_max * (1.15 + 0.15 * self._focus_intensity)
        aura = QRadialGradient(cx, cy, aura_rad)
        aura.setColorAt(0.0, QColor(0, 212, 255, glow_alpha))
        aura.setColorAt(0.6, QColor(0, 150, 255, int(glow_alpha * 0.4)))
        aura.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), QBrush(aura))

        p.save()
        p.translate(cx, cy)

        # 2. Outer Segmented Orbital Ring (Clockwise)
        p.save()
        p.rotate(self._rot_outer)
        outer_pen = QPen(QColor(0, 212, 255, int(140 + 80 * self._focus_intensity)))
        outer_pen.setWidthF(1.6)
        p.setPen(outer_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        r_outer = r_max * 0.88
        # Draw 3 dashed segmented arcs
        span_angle = 75
        gap_angle = 45
        for i in range(3):
            start = i * (span_angle + gap_angle)
            p.drawArc(QRect(int(-r_outer), int(-r_outer), int(r_outer * 2), int(r_outer * 2)),
                      int(start * 16), int(span_angle * 16))

        # Orbital tick nodes on outer ring
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255, int(200 + 55 * self._focus_intensity))))
        for i in range(3):
            rad_angle = math.radians(i * (span_angle + gap_angle))
            nx = r_outer * math.cos(rad_angle)
            ny = r_outer * math.sin(rad_angle)
            p.drawEllipse(QPointF(nx, ny), 2.2, 2.2)
        p.restore()

        # 3. Inner Counter-Rotating Hexagonal Carrier (Counter-Clockwise)
        p.save()
        p.rotate(self._rot_inner)
        inner_pen = QPen(QColor(0, 180, 240, int(90 + 70 * self._focus_intensity)))
        inner_pen.setWidthF(1.2)
        p.setPen(inner_pen)

        r_mid = r_max * 0.62
        poly_path = QPainterPath()
        sides = 6
        for s in range(sides):
            sa = math.radians(s * (360 / sides))
            px = r_mid * math.cos(sa)
            py = r_mid * math.sin(sa)
            if s == 0:
                poly_path.moveTo(px, py)
            else:
                poly_path.lineTo(px, py)
        poly_path.closeSubpath()
        p.drawPath(poly_path)
        p.restore()

        # 4. Central Pulsating AI Core
        core_r = r_max * (0.34 + 0.06 * math.sin(self._t * 3.0) + 0.05 * self._focus_intensity)
        core_grad = QRadialGradient(0, 0, core_r)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 240))
        core_grad.setColorAt(0.35, QColor(0, 225, 255, int(220 + 35 * self._focus_intensity)))
        core_grad.setColorAt(0.85, QColor(0, 140, 240, int(150 + 60 * self._focus_intensity)))
        core_grad.setColorAt(1.0, QColor(0, 70, 180, 0))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(core_grad))
        p.drawEllipse(QPointF(0, 0), core_r, core_r)

        # 5. Core Neural Diamond Mark (Center Glyph)
        diamond_size = 5.0 + 1.5 * self._focus_intensity
        d_path = QPainterPath()
        d_path.moveTo(0, -diamond_size)
        d_path.lineTo(diamond_size * 0.75, 0)
        d_path.lineTo(0, diamond_size)
        d_path.lineTo(-diamond_size * 0.75, 0)
        d_path.closeSubpath()

        p.setPen(QPen(QColor(255, 255, 255, 255), 1.0))
        p.setBrush(QBrush(QColor(255, 255, 255, 220)))
        p.drawPath(d_path)

        p.restore()
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# INTERACTIVE CYBERNETIC BACKGROUND CANVAS
# ─────────────────────────────────────────────────────────────────────────────
class LoginBackground(QWidget):
    """
    Immersive cybernetic canvas.
    Renders deep gradients, subtle coordinate micro-grids, connected constellation
    particles, and dynamic ambient lighting with interactive mouse responsiveness.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        self._t = 0.0
        self._particles = []
        self._mouse_curr = QPointF(-1000, -1000)
        self._mouse_target = QPointF(-1000, -1000)

        # Animation loop at ~30 FPS
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_mouse_position(self, pt: QPoint):
        self._mouse_target = QPointF(pt.x(), pt.y())
        if self._mouse_curr.x() < -500:
            self._mouse_curr = self._mouse_target

    def _init_particles(self):
        w = max(self.width(), 800)
        h = max(self.height(), 600)
        count = 65
        self._particles = [
            {
                'x': random.uniform(0, w),
                'y': random.uniform(0, h),
                'vx': random.uniform(-0.35, 0.35),
                'vy': random.uniform(-0.45, -0.1),
                'size': random.uniform(1.2, 2.6),
                'base_alpha': random.uniform(0.12, 0.45),
                'pulse_phase': random.uniform(0.0, 6.28),
            }
            for _ in range(count)
        ]

    def _tick(self):
        self._t += 0.02
        w, h = self.width(), self.height()
        if not self._particles and w > 0:
            self._init_particles()

        # Smooth mouse motion interpolation
        self._mouse_curr += (self._mouse_target - self._mouse_curr) * 0.08

        # Update particles
        for p in self._particles:
            p['x'] += p['vx']
            p['y'] += p['vy']

            # Gentle mouse repulsion / disturbance if mouse is active
            if self._mouse_curr.x() > 0:
                dx = p['x'] - self._mouse_curr.x()
                dy = p['y'] - self._mouse_curr.y()
                dist = math.hypot(dx, dy)
                if 0 < dist < 120:
                    force = (120 - dist) / 120.0 * 0.45
                    p['x'] += (dx / dist) * force
                    p['y'] += (dy / dist) * force

            # Wrap around boundaries seamlessly
            if p['y'] < -10:
                p['y'] = h + 10
                p['x'] = random.uniform(0, w)
            elif p['y'] > h + 10:
                p['y'] = -10
            if p['x'] < -10:
                p['x'] = w + 10
            elif p['x'] > w + 10:
                p['x'] = -10

        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # 1. Deep Layered Obsidian Gradient
        bg_grad = QLinearGradient(0, 0, w * 0.5, h)
        bg_grad.setColorAt(0.0, QColor("#020509"))
        bg_grad.setColorAt(0.45, QColor("#050d17"))
        bg_grad.setColorAt(0.75, QColor("#03070d"))
        bg_grad.setColorAt(1.0, QColor("#010204"))
        p.fillRect(0, 0, w, h, QBrush(bg_grad))

        # 2. Dynamic Ambient Mouse Glow (Follows cursor smoothly)
        if self._mouse_curr.x() > 0 and self._mouse_curr.y() > 0:
            mg = QRadialGradient(self._mouse_curr.x(), self._mouse_curr.y(), 420)
            mg.setColorAt(0.0, QColor(0, 212, 255, 26))
            mg.setColorAt(0.45, QColor(0, 150, 255, 10))
            mg.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(0, 0, w, h, QBrush(mg))

        # 3. Center Atmospheric Radial Glow
        cx, cy = w / 2.0, h / 2.0
        center_glow = QRadialGradient(cx, cy, min(w, h) * 0.6)
        center_glow.setColorAt(0.0, QColor(0, 180, 255, 22))
        center_glow.setColorAt(0.5, QColor(0, 100, 220, 8))
        center_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, h, QBrush(center_glow))

        # 4. Fine Technological Micro-Grid
        grid_step = 70
        grid_pen = QPen(QColor(0, 212, 255, 10))
        grid_pen.setWidth(1)
        p.setPen(grid_pen)

        for x in range(0, w, grid_step):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, grid_step):
            p.drawLine(0, y, w, y)

        # 5. Subtle Technical Crosshairs & Corner Telemetry
        p.setPen(QPen(QColor(0, 212, 255, 35), 1))
        ch_len = 8
        margin = 40
        # 4 corner crosshairs
        for pt_x, pt_y in [
            (margin, margin),
            (w - margin, margin),
            (margin, h - margin),
            (w - margin, h - margin)
        ]:
            p.drawLine(pt_x - ch_len, pt_y, pt_x + ch_len, pt_y)
            p.drawLine(pt_x, pt_y - ch_len, pt_x, pt_y + ch_len)

        # Technical watermarks
        p.setFont(F.mono(9))
        p.setPen(QColor(0, 212, 255, 45))
        p.drawText(margin + 16, margin + 4, "SYSTEM: STANDBY // CORE: ACTIVE")
        p.drawText(w - margin - 140, h - margin + 4, "SECURE_GATEWAY_V2")

        # 6. Constellation Particle Network & Interconnecting Filaments
        n = len(self._particles)
        max_dist = 88.0

        # Draw connecting lines between close particles
        for i in range(n):
            pi = self._particles[i]
            for j in range(i + 1, min(i + 12, n)):
                pj = self._particles[j]
                dx = pi['x'] - pj['x']
                dy = pi['y'] - pj['y']
                dist = math.hypot(dx, dy)
                if dist < max_dist:
                    line_alpha = int((1.0 - (dist / max_dist)) * 38)
                    p.setPen(QPen(QColor(0, 212, 255, line_alpha), 1))
                    p.drawLine(int(pi['x']), int(pi['y']), int(pj['x']), int(pj['y']))

        # Draw particle nodes
        p.setPen(Qt.PenStyle.NoPen)
        for pt in self._particles:
            pulse = 0.75 + 0.25 * math.sin(self._t * 2.0 + pt['pulse_phase'])
            alpha = int(pt['base_alpha'] * pulse * 255)
            if alpha <= 0:
                continue

            sz = pt['size']
            p.setBrush(QBrush(QColor(0, 212, 255, alpha)))
            p.drawEllipse(QPointF(pt['x'], pt['y']), sz, sz)

            # Highlight brightest particles with center white specular dot
            if alpha > 75:
                p.setBrush(QBrush(QColor(255, 255, 255, min(255, alpha + 50))))
                p.drawEllipse(QPointF(pt['x'], pt['y']), sz * 0.45, sz * 0.45)

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM FOCUS-SENSITIVE TEXT INPUT
# ─────────────────────────────────────────────────────────────────────────────
class ReactiveInputField(QLineEdit):
    """
    Custom QLineEdit that notifies listener on focus in/out
    to trigger animated AI Core reactions.
    """
    focus_changed = pyqtSignal(bool)

    def focusInEvent(self, e: QFocusEvent):
        super().focusInEvent(e)
        self.focus_changed.emit(True)

    def focusOutEvent(self, e: QFocusEvent):
        super().focusOutEvent(e)
        self.focus_changed.emit(False)


# ─────────────────────────────────────────────────────────────────────────────
# REDESIGNED SOPHISTICATED LOGIN CARD
# ─────────────────────────────────────────────────────────────────────────────
class LoginCard(QFrame):
    """
    Glassmorphic translucent login panel.
    Integrated identity core, refined typography, structured field layout,
    password reveal toggle, vibrant CTA button, and real-time system status.
    """

    submit_requested = pyqtSignal(str, str)  # (username, password)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(420)
        self.setObjectName("LoginCard")

        # Glassmorphic translucent styling with subtle cyan border gradient
        self.setStyleSheet("""
            QFrame#LoginCard {
                background: rgba(6, 12, 20, 0.90);
                border: 1.2px solid rgba(0, 212, 255, 0.28);
                border-radius: 22px;
            }
        """)

        # Soft layered ambient cyan drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(70)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 212, 255, 45))
        self.setGraphicsEffect(shadow)

        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(38, 36, 38, 32)
        main_lay.setSpacing(18)

        # ── 1. ASSISTANT IDENTITY HEADER ──────────────────────────────────────
        id_container = QWidget()
        id_lay = QVBoxLayout(id_container)
        id_lay.setContentsMargins(0, 0, 0, 0)
        id_lay.setSpacing(10)
        id_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Animated AI Core Identity
        self._identity_core = AssistantIdentityCore()
        id_lay.addWidget(self._identity_core, alignment=Qt.AlignmentFlag.AlignCenter)

        # System Badge Pill
        badge = QLabel("SMART ASSISTANT // OS")
        badge.setFont(F.mono(10))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet("""
            QLabel {
                color: #00d4ff;
                background: rgba(0, 212, 255, 0.08);
                border: 1px solid rgba(0, 212, 255, 0.35);
                border-radius: 10px;
                padding: 3px 12px;
                font-weight: 700;
                letter-spacing: 1px;
            }
        """)
        id_lay.addWidget(badge, alignment=Qt.AlignmentFlag.AlignCenter)

        # Title & Subtitle
        title = QLabel("Welcome Back")
        title.setFont(F.ui(22, bold=True))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #ffffff; letter-spacing: 0.8px; background: transparent; border: none;")
        id_lay.addWidget(title)

        subtitle = QLabel("Neural interface ready. Identify yourself to proceed.")
        subtitle.setFont(F.ui(11))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #8da4b5; background: transparent; border: none;")
        id_lay.addWidget(subtitle)

        main_lay.addWidget(id_container)

        # ── 2. FORM FIELDS ───────────────────────────────────────────────────
        fields_box = QVBoxLayout()
        fields_box.setSpacing(14)

        # Common input stylesheet
        input_css = f"""
            QLineEdit {{
                background: rgba(11, 20, 31, 0.85);
                color: #ffffff;
                border: 1px solid rgba(0, 212, 255, 0.22);
                border-radius: {Radius.MD}px;
                padding: 10px 14px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
                selection-background-color: rgba(0, 212, 255, 0.3);
            }}
            QLineEdit:focus {{
                border: 1.5px solid #00d4ff;
                background: rgba(0, 212, 255, 0.06);
            }}
            QLineEdit::placeholder {{
                color: #537184;
            }}
        """

        # Username Field
        user_header = QLabel("IDENTIFIER")
        user_header.setFont(F.mono(10))
        user_header.setStyleSheet("color: #00d4ff; letter-spacing: 0.8px; font-weight: 600; background: transparent; border: none;")
        fields_box.addWidget(user_header)

        self._username = ReactiveInputField()
        self._username.setPlaceholderText("Enter operator username...")
        self._username.setFixedHeight(44)
        self._username.setStyleSheet(input_css)
        self._username.focus_changed.connect(self._identity_core.set_focused)
        self._username.returnPressed.connect(self._on_submit)
        fields_box.addWidget(self._username)

        # Password Field
        pass_header = QLabel("ACCESS KEY")
        pass_header.setFont(F.mono(10))
        pass_header.setStyleSheet("color: #00d4ff; letter-spacing: 0.8px; font-weight: 600; background: transparent; border: none;")
        fields_box.addWidget(pass_header)

        # Password input wrapper with toggle button
        pass_container = QWidget()
        pass_container.setFixedHeight(44)
        pass_lay = QHBoxLayout(pass_container)
        pass_lay.setContentsMargins(0, 0, 0, 0)
        pass_lay.setSpacing(0)

        # Separate CSS for password field with right-padding for toggle button
        pass_css = f"""
            QLineEdit {{
                background: rgba(11, 20, 31, 0.85);
                color: #ffffff;
                border: 1px solid rgba(0, 212, 255, 0.22);
                border-radius: {Radius.MD}px;
                padding: 10px 40px 10px 14px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
                selection-background-color: rgba(0, 212, 255, 0.3);
            }}
            QLineEdit:focus {{
                border: 1.5px solid #00d4ff;
                background: rgba(0, 212, 255, 0.06);
            }}
            QLineEdit::placeholder {{
                color: #537184;
            }}
        """

        self._password = ReactiveInputField()
        self._password.setPlaceholderText("Enter password key...")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setFixedHeight(44)
        self._password.setStyleSheet(pass_css)
        self._password.focus_changed.connect(self._identity_core.set_focused)
        self._password.returnPressed.connect(self._on_submit)
        pass_lay.addWidget(self._password)

        # Visibility toggle button inside password area
        self._toggle_btn = QToolButton(self._password)
        self._toggle_btn.setText("👁")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setToolTip("Toggle password visibility")
        self._toggle_btn.setStyleSheet("""
            QToolButton {
                background: transparent;
                color: #6d8e9e;
                border: none;
                font-size: 14px;
                padding-right: 6px;
            }
            QToolButton:hover {
                color: #00d4ff;
            }
        """)
        self._toggle_btn.clicked.connect(self._toggle_password_visibility)

        fields_box.addWidget(pass_container)
        main_lay.addLayout(fields_box)

        # ── 3. ERROR BANNER ───────────────────────────────────────────────────
        self._err_label = QLabel("")
        self._err_label.setFont(F.ui(11))
        self._err_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._err_label.setWordWrap(True)
        self._err_label.setStyleSheet("""
            QLabel {
                color: #ff5252;
                background: rgba(255, 82, 82, 0.12);
                border: 1px solid rgba(255, 82, 82, 0.35);
                border-radius: 8px;
                padding: 6px 12px;
            }
        """)
        self._err_label.hide()
        main_lay.addWidget(self._err_label)

        # ── 4. SIGN IN ACTION BUTTON ─────────────────────────────────────────
        self._btn = QPushButton("AUTHENTICATE && ENTER →")
        self._btn.setFixedHeight(48)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0088cc, stop:0.5 #00a8e8, stop:1 #00d4ff);
                color: #ffffff;
                border: 1px solid rgba(0, 212, 255, 0.6);
                border-radius: {Radius.MD}px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 0.8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0099e6, stop:0.5 #18bcf5, stop:1 #33e0ff);
                border: 1px solid #00d4ff;
            }}
            QPushButton:pressed {{
                background: #0077b6;
            }}
            QPushButton:disabled {{
                background: rgba(12, 28, 42, 0.8);
                color: rgba(255, 255, 255, 0.35);
                border: 1px solid rgba(0, 212, 255, 0.12);
            }}
        """)
        self._btn.clicked.connect(self._on_submit)
        main_lay.addWidget(self._btn)

        # ── 5. REAL RUNTIME TELEMETRY STATUS ───────────────────────────────────
        status_box = QHBoxLayout()
        status_box.setContentsMargins(4, 4, 4, 0)
        status_box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._sys_status = QLabel("● SYSTEM READY")
        self._sys_status.setFont(F.mono(9))
        self._sys_status.setStyleSheet("color: #00e56b; font-weight: 600; background: transparent; border: none;")

        sep = QLabel(" // ")
        sep.setFont(F.mono(9))
        sep.setStyleSheet("color: #436275; background: transparent; border: none;")

        self._db_status = QLabel("● CHECKING DB...")
        self._db_status.setFont(F.mono(9))
        self._db_status.setStyleSheet("color: #ffd60a; font-weight: 600; background: transparent; border: none;")

        status_box.addWidget(self._sys_status)
        status_box.addWidget(sep)
        status_box.addWidget(self._db_status)
        main_lay.addLayout(status_box)

        # Subtle Operator Hint
        footer = QLabel("New operator? Credentials automatically initialize account profile.")
        footer.setFont(F.ui(10))
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setWordWrap(True)
        footer.setStyleSheet("color: #637f90; background: transparent; border: none;")
        main_lay.addWidget(footer)

        # Adjust toggle position inside password field on resize
        QTimer.singleShot(50, self._adjust_toggle_pos)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._adjust_toggle_pos()

    def _adjust_toggle_pos(self):
        if hasattr(self, '_toggle_btn') and hasattr(self, '_password'):
            w = self._password.width()
            h = self._password.height()
            self._toggle_btn.setGeometry(w - 36, int((h - 28) / 2), 30, 28)

    def _toggle_password_visibility(self):
        if self._password.echoMode() == QLineEdit.EchoMode.Password:
            self._password.setEchoMode(QLineEdit.EchoMode.Normal)
            self._toggle_btn.setText("🔒")
            self._toggle_btn.setToolTip("Hide password")
        else:
            self._password.setEchoMode(QLineEdit.EchoMode.Password)
            self._toggle_btn.setText("👁")
            self._toggle_btn.setToolTip("Show password")

    def _on_submit(self):
        self.submit_requested.emit(
            self._username.text().strip(),
            self._password.text()
        )

    def set_loading(self, loading: bool):
        self._btn.setEnabled(not loading)
        self._btn.setText("AUTHENTICATING..." if loading else "AUTHENTICATE && ENTER →")
        self._username.setEnabled(not loading)
        self._password.setEnabled(not loading)
        self._toggle_btn.setEnabled(not loading)
        self._identity_core.set_focused(loading)

    def show_error(self, msg: str):
        self._err_label.setText(f"⚠  {msg}")
        self._err_label.show()

    def clear_error(self):
        self._err_label.hide()
        self._err_label.setText("")

    def set_db_status(self, is_online: bool, text: str):
        if is_online:
            self._db_status.setText(f"● {text}")
            self._db_status.setStyleSheet("color: #00e56b; font-weight: 600; background: transparent; border: none;")
        else:
            self._db_status.setText(f"● {text}")
            self._db_status.setStyleSheet("color: #ff5252; font-weight: 600; background: transparent; border: none;")


# ─────────────────────────────────────────────────────────────────────────────
# REDESIGNED NAME ASSISTANT CARD (FIRST-TIME ONBOARDING)
# ─────────────────────────────────────────────────────────────────────────────
class NameAssistantCard(QFrame):
    """
    Shown after first-time login to let the user name their assistant.
    Matches the exact cybernetic glassmorphic aesthetic of the login screen.
    """

    name_submitted = pyqtSignal(str)  # the chosen name

    def __init__(self, username: str, parent=None):
        super().__init__(parent)
        self.setFixedWidth(420)
        self.setObjectName("NameCard")
        self.setStyleSheet("""
            QFrame#NameCard {
                background: rgba(6, 12, 20, 0.90);
                border: 1.2px solid rgba(0, 212, 255, 0.28);
                border-radius: 22px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(70)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 212, 255, 45))
        self.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(38, 36, 38, 32)
        lay.setSpacing(18)

        # Header with AI Identity Core
        self._core = AssistantIdentityCore()
        lay.addWidget(self._core, alignment=Qt.AlignmentFlag.AlignCenter)

        badge = QLabel("INITIALIZATION PROTOCOL")
        badge.setFont(F.mono(10))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet("""
            QLabel {
                color: #00d4ff;
                background: rgba(0, 212, 255, 0.08);
                border: 1px solid rgba(0, 212, 255, 0.35);
                border-radius: 10px;
                padding: 3px 12px;
                font-weight: 700;
                letter-spacing: 1px;
            }
        """)
        lay.addWidget(badge, alignment=Qt.AlignmentFlag.AlignCenter)

        hi = QLabel(f"Welcome, {username}")
        hi.setFont(F.ui(22, bold=True))
        hi.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hi.setStyleSheet("color: #ffffff; background: transparent; border: none;")
        lay.addWidget(hi)

        desc = QLabel(
            "Designate an identity for your personal assistant.\n"
            "This name will anchor your neural workspace profile."
        )
        desc.setFont(F.ui(11))
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8da4b5; background: transparent; border: none;")
        lay.addWidget(desc)

        # Input
        label = QLabel("ASSISTANT CALLSIGN")
        label.setFont(F.mono(10))
        label.setStyleSheet("color: #00d4ff; letter-spacing: 0.8px; font-weight: 600; background: transparent; border: none;")
        lay.addWidget(label)

        self._name_input = ReactiveInputField()
        self._name_input.setPlaceholderText("e.g. Jarvis, Nova, Aira, Friday...")
        self._name_input.setFixedHeight(44)
        self._name_input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(11, 20, 31, 0.85);
                color: #ffffff;
                border: 1px solid rgba(0, 212, 255, 0.22);
                border-radius: {Radius.MD}px;
                padding: 10px 14px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 1.5px solid #00d4ff;
                background: rgba(0, 212, 255, 0.06);
            }}
        """)
        self._name_input.focus_changed.connect(self._core.set_focused)
        self._name_input.returnPressed.connect(self._on_submit)
        lay.addWidget(self._name_input)

        self._err = QLabel("")
        self._err.setFont(F.ui(11))
        self._err.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._err.setStyleSheet("color: #ff5252; background: transparent; border: none;")
        self._err.hide()
        lay.addWidget(self._err)

        btn = QPushButton("INITIALIZE ASSISTANT →")
        btn.setFixedHeight(48)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0088cc, stop:0.5 #00a8e8, stop:1 #00d4ff);
                color: #ffffff;
                border: 1px solid rgba(0, 212, 255, 0.6);
                border-radius: {Radius.MD}px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 0.8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0099e6, stop:0.5 #18bcf5, stop:1 #33e0ff);
                border: 1px solid #00d4ff;
            }}
        """)
        btn.clicked.connect(self._on_submit)
        lay.addWidget(btn)

    def _on_submit(self):
        name = self._name_input.text().strip()
        if not name:
            self._err.setText("⚠ Please specify a callsign for your assistant.")
            self._err.show()
            return
        self._err.hide()
        self.name_submitted.emit(name)


# ─────────────────────────────────────────────────────────────────────────────
# VOICE SETUP CARD  (Step 2 of first-time onboarding)
# ─────────────────────────────────────────────────────────────────────────────
_TONE_PROFILES = [
    ("Calm",         {"rate": 130, "volume": 0.9}),
    ("Professional", {"rate": 155, "volume": 1.0}),
    ("Friendly",     {"rate": 165, "volume": 1.0}),
    ("Energetic",    {"rate": 185, "volume": 1.0}),
    ("Soft",         {"rate": 125, "volume": 0.75}),
]


class VoiceSetupCard(QFrame):
    """
    Second step of first-time onboarding: configure assistant voice identity.
    Shows gender selector → real system voices filtered by gender → tone selector
    → live TTS preview → save.
    Emits voice_submitted(dict) with keys: voice_id, voice_gender, voice_tone,
    voice_rate, voice_volume.
    """
    voice_submitted = pyqtSignal(dict)

    def __init__(self, assistant_name: str, parent=None):
        super().__init__(parent)
        self._assistant_name = assistant_name or "your assistant"
        self._all_voices: list[dict] = []  # populated in background
        self._selected_gender = "male"

        self.setFixedWidth(460)
        self.setObjectName("VoiceCard")
        self.setStyleSheet("""
            QFrame#VoiceCard {
                background: rgba(6, 12, 20, 0.92);
                border: 1.2px solid rgba(0, 212, 255, 0.28);
                border-radius: 22px;
            }
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(70)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 212, 255, 45))
        self.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(38, 32, 38, 30)
        lay.setSpacing(16)

        # ── Header ─────────────────────────────────────────────
        badge = QLabel("VOICE IDENTITY CONFIGURATION")
        badge.setFont(F.mono(9))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet("""
            QLabel {
                color: #00d4ff;
                background: rgba(0,212,255,0.08);
                border: 1px solid rgba(0,212,255,0.32);
                border-radius: 10px;
                padding: 3px 12px;
                font-weight: 700;
                letter-spacing: 1px;
            }
        """)
        lay.addWidget(badge, alignment=Qt.AlignmentFlag.AlignCenter)

        title = QLabel(f"How should {self._assistant_name} sound?")
        title.setFont(F.ui(18, bold=True))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        title.setStyleSheet("color: #ffffff; background: transparent; border: none;")
        lay.addWidget(title)

        # ── Gender Selection ──────────────────────────────────
        g_lbl = QLabel("VOICE CHARACTER")
        g_lbl.setFont(F.mono(9))
        g_lbl.setStyleSheet("color: #5a7a8a; letter-spacing: 0.8px; background: transparent; border: none;")
        lay.addWidget(g_lbl)

        gender_row = QHBoxLayout()
        gender_row.setSpacing(10)
        self._btn_male   = QPushButton("♂  Male")
        self._btn_female = QPushButton("♀  Female")
        for btn in (self._btn_male, self._btn_female):
            btn.setFixedHeight(40)
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

        # ── Voice Selector ───────────────────────────────────
        v_lbl = QLabel("VOICE")
        v_lbl.setFont(F.mono(9))
        v_lbl.setStyleSheet("color: #5a7a8a; letter-spacing: 0.8px; background: transparent; border: none;")
        lay.addWidget(v_lbl)

        self._voice_combo = QComboBox()
        self._voice_combo.setFixedHeight(38)
        self._voice_combo.setFont(F.ui(11))
        self._voice_combo.setStyleSheet(self._combo_style())
        self._voice_combo.addItem("Loading voices...")
        lay.addWidget(self._voice_combo)

        # ── Tone Selector ────────────────────────────────────
        t_lbl = QLabel("SPEAKING STYLE")
        t_lbl.setFont(F.mono(9))
        t_lbl.setStyleSheet("color: #5a7a8a; letter-spacing: 0.8px; background: transparent; border: none;")
        lay.addWidget(t_lbl)

        self._tone_combo = QComboBox()
        self._tone_combo.setFixedHeight(38)
        self._tone_combo.setFont(F.ui(11))
        self._tone_combo.setStyleSheet(self._combo_style())
        for tone_name, _ in _TONE_PROFILES:
            self._tone_combo.addItem(tone_name)
        self._tone_combo.setCurrentIndex(1)  # Professional default
        lay.addWidget(self._tone_combo)

        tone_hint = QLabel(
            "Tone adjusts rate & volume. Calm = slower/quieter. Energetic = faster."
        )
        tone_hint.setFont(F.ui(9))
        tone_hint.setWordWrap(True)
        tone_hint.setStyleSheet("color: #4a6070; background: transparent; border: none;")
        lay.addWidget(tone_hint)

        # ── Preview + Continue buttons ────────────────────────
        self._status_lbl = QLabel("")
        self._status_lbl.setFont(F.ui(10))
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet("color: #00d4ff; background: transparent; border: none;")
        self._status_lbl.hide()
        lay.addWidget(self._status_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._preview_btn = QPushButton("▶  Preview Voice")
        self._preview_btn.setFixedHeight(44)
        self._preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview_btn.setFont(F.ui(12, bold=True))
        self._preview_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0,212,255,0.10);
                color: #00d4ff;
                border: 1.5px solid rgba(0,212,255,0.4);
                border-radius: 10px;
                font-weight: 700;
            }
            QPushButton:hover { background: rgba(0,212,255,0.22); }
            QPushButton:disabled { color: #2a4050; border-color: rgba(0,212,255,0.1); }
        """)
        self._preview_btn.clicked.connect(self._preview_voice)
        btn_row.addWidget(self._preview_btn)

        self._continue_btn = QPushButton("SAVE & CONTINUE →")
        self._continue_btn.setFixedHeight(44)
        self._continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._continue_btn.setFont(F.ui(12, bold=True))
        self._continue_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #0088cc, stop:0.5 #00a8e8, stop:1 #00d4ff);
                color: #ffffff;
                border: 1px solid rgba(0,212,255,0.6);
                border-radius: 10px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #0099e6, stop:0.5 #18bcf5, stop:1 #33e0ff);
            }
            QPushButton:disabled { background: #1a2a3a; color: #2a4050; }
        """)
        self._continue_btn.clicked.connect(self._on_continue)
        btn_row.addWidget(self._continue_btn)
        lay.addLayout(btn_row)

        # Load voices in background thread
        self._load_voices_async()

    # ── Internal helpers ────────────────────────────────────────
    def _combo_style(self) -> str:
        return f"""
            QComboBox {{
                background: rgba(11,20,31,0.85);
                color: #ffffff;
                border: 1px solid rgba(0,212,255,0.22);
                border-radius: {Radius.MD}px;
                padding: 6px 12px;
                font-family: '{F.PRIMARY}';
                font-size: 12px;
            }}
            QComboBox:focus {{ border: 1.5px solid #00d4ff; }}
            QComboBox QAbstractItemView {{
                background: #0a1520;
                color: #ffffff;
                selection-background-color: rgba(0,212,255,0.20);
                border: 1px solid rgba(0,212,255,0.25);
            }}
        """

    def _gender_btn_style(self, active: bool) -> str:
        if active:
            return """
                QPushButton {
                    background: rgba(0,212,255,0.18);
                    color: #00d4ff;
                    border: 1.5px solid #00d4ff;
                    border-radius: 10px;
                }
            """
        return """
            QPushButton {
                background: rgba(255,255,255,0.04);
                color: #6a8a9a;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
            }
            QPushButton:hover {
                background: rgba(0,212,255,0.08);
                color: #a0c0d0;
                border-color: rgba(0,212,255,0.3);
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
        """Load SAPI5 voices in a background thread to keep the UI responsive."""
        import threading
        def _worker():
            try:
                from legacy.tts import enumerate_voices
                voices = enumerate_voices()
            except Exception:
                voices = []
            # Schedule UI update on main thread
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
            # Fallback: show all voices if gender filtering yields nothing
            filtered = self._all_voices
        if not filtered:
            self._voice_combo.addItem("No voices found — using system default", None)
            return
        for v in filtered:
            display = f"{v['name']}"
            self._voice_combo.addItem(display, v["id"])
        self._voice_combo.setCurrentIndex(0)

    def _get_selected_voice(self) -> tuple[str | None, str]:
        """Return (voice_id, voice_name) of the currently selected item."""
        idx = self._voice_combo.currentIndex()
        if idx < 0:
            return None, ""
        vid = self._voice_combo.itemData(idx)
        name = self._voice_combo.currentText()
        return vid, name

    def _get_tone_params(self) -> tuple[str, int, float]:
        """Return (tone_key, rate, volume) for the selected tone."""
        idx = max(0, self._tone_combo.currentIndex())
        tone_name, params = _TONE_PROFILES[idx]
        return tone_name.lower(), params["rate"], params["volume"]

    def _preview_voice(self):
        """Speak a preview sentence using the currently configured voice."""
        vid, _  = self._get_selected_voice()
        tone_key, rate, volume = self._get_tone_params()
        name    = self._assistant_name
        preview_text = f"Hello. I'm {name}. It's nice to meet you."

        self._preview_btn.setEnabled(False)
        self._status_lbl.setText("▶ Speaking preview...")
        self._status_lbl.show()

        def _speak_preview():
            try:
                from legacy.tts import apply_voice_profile, _speak_pyttsx3
                apply_voice_profile(vid, rate=rate, volume=volume)
                _speak_pyttsx3(preview_text)
            except Exception as e:
                print(f"[VOICE SETUP] Preview error: {e}")
            QTimer.singleShot(0, self._preview_done)

        import threading
        threading.Thread(target=_speak_preview, daemon=True).start()

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
# REDESIGNED LOGIN WINDOW (TOP-LEVEL)
# ─────────────────────────────────────────────────────────────────────────────
class LoginWindow(QWidget):
    """
    Full-screen responsive AI Assistant login window.
    Features cybernetic background canvas, interactive mouse tracking,
    glassmorphic login panel, real-time database health check,
    and fluid entrance/exit animations.
    """
    login_complete = pyqtSignal(int, str)  # (user_id, username)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Assistant — Gateway")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)

        self._user_id = None
        self._username = None
        self._auth_thread: AuthThread | None = None
        self._db_thread: SystemStatusThread | None = None

        # 1. Canvas Background
        self._bg = LoginBackground(self)
        self._bg.setGeometry(0, 0, self.width(), self.height())

        # 2. Centered Container for Responsive Card Placement
        self._card_container = QWidget(self)
        self._card_container.setGeometry(0, 0, self.width(), self.height())
        self._card_container.setStyleSheet("background: transparent;")
        self._card_container.setMouseTracking(True)

        container_lay = QVBoxLayout(self._card_container)
        container_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 3. Main Login Card
        self._login_card = LoginCard()
        self._login_card.submit_requested.connect(self._on_submit)
        container_lay.addWidget(self._login_card)

        # 4a. Name Assistant Card (Step 1 of new-user onboarding)
        self._name_card = NameAssistantCard("")
        self._name_card.name_submitted.connect(self._on_name_submitted)
        self._name_card.hide()
        container_lay.addWidget(self._name_card)

        # 4b. Voice Setup Card (Step 2 of new-user onboarding) — created on demand
        self._voice_card: VoiceSetupCard | None = None
        self._pending_name: str = ""  # assistant name chosen in Step 1

        # 5. Check real database status in background
        self._check_system_status()

        # 6. Smooth Fade-in Animation
        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(450)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.start()

    def resizeEvent(self, event):
        """Handle screen resizing and responsive layout."""
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        if hasattr(self, '_bg') and self._bg:
            self._bg.setGeometry(0, 0, w, h)
        if hasattr(self, '_card_container') and self._card_container:
            self._card_container.setGeometry(0, 0, w, h)

    def mousePressEvent(self, e):
        """Window drag handling."""
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        """Pass mouse coordinates to interactive background and support drag."""
        pos = e.position().toPoint()
        if hasattr(self, '_bg') and self._bg:
            self._bg.set_mouse_position(pos)

        if hasattr(self, '_drag_pos') and e.buttons() == Qt.MouseButton.LeftButton:
            delta = e.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = e.globalPosition().toPoint()

    def _check_system_status(self):
        """Query real database connectivity asynchronously without blocking UI."""
        self._db_thread = SystemStatusThread()
        self._db_thread.status_ready.connect(self._login_card.set_db_status)
        self._db_thread.start()

    # ── Authentication Flow (Preserved Backend Integration) ───────────────────
    def _on_submit(self, username: str, password: str):
        if not username:
            self._login_card.show_error("Please enter your operator identifier.")
            return
        if not password:
            self._login_card.show_error("Please enter your access key.")
            return

        self._login_card.clear_error()
        self._login_card.set_loading(True)

        self._auth_thread = AuthThread(username, password)
        self._auth_thread.success.connect(self._on_auth_success)
        self._auth_thread.failed.connect(self._on_auth_failed)
        self._auth_thread.start()

    def _on_auth_success(self, user_id: int, username: str, result_type):
        self._login_card.set_loading(False)
        self._user_id = user_id
        self._username = username

        if result_type == "NEW_USER":
            # First time setup: Step 1 — name the assistant
            self._name_card.deleteLater()
            self._name_card = NameAssistantCard(username, self._card_container)
            self._name_card.name_submitted.connect(self._on_name_submitted)
            self._card_container.layout().addWidget(self._name_card)

            self._login_card.hide()
            self._name_card.show()
        else:
            # Existing user: proceed into the assistant environment
            self._proceed()

    def _on_auth_failed(self, msg: str):
        self._login_card.set_loading(False)
        self._login_card.show_error(msg)

    def _on_name_submitted(self, name: str):
        """Step 1 complete: save name, move to Step 2 (voice setup)."""
        try:
            from legacy.memory_manager import set_assistant_name_db
            set_assistant_name_db(self._user_id, name)
            from instance.config import settings
            settings.CURRENT_ASSISTANT_NAME = name
        except Exception as e:
            print(f"[LOGIN] Failed to save assistant name: {e}")
        self._pending_name = name
        # Transition to voice setup
        self._name_card.hide()
        self._show_voice_setup(name)

    def _show_voice_setup(self, assistant_name: str):
        """Create and show VoiceSetupCard, wired to _on_voice_submitted."""
        if self._voice_card is not None:
            try:
                self._voice_card.deleteLater()
            except Exception:
                pass
        self._voice_card = VoiceSetupCard(assistant_name, self._card_container)
        self._voice_card.voice_submitted.connect(self._on_voice_submitted)
        self._card_container.layout().addWidget(self._voice_card)
        self._voice_card.show()

    def _on_voice_submitted(self, profile: dict):
        """Step 2 complete: persist voice profile, then proceed to app."""
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
            # Apply immediately so the greeting uses this voice
            from legacy.tts import apply_voice_profile
            apply_voice_profile(
                profile.get("voice_id"),
                rate=int(profile.get("voice_rate", 155)),
                volume=float(profile.get("voice_volume", 1.0)),
            )
        except Exception as e:
            print(f"[LOGIN] Failed to save voice profile: {e}")
        self._proceed()

    def _proceed(self):
        """Smooth fade-out and emit login_complete."""
        fade_out = QPropertyAnimation(self, b"windowOpacity")
        fade_out.setDuration(400)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        fade_out.finished.connect(lambda: self.login_complete.emit(self._user_id, self._username))
        fade_out.finished.connect(self.close)
        fade_out.start()
        self._fade_out_anim = fade_out

    def keyPressEvent(self, e):
        # Prevent accidental Escape dismissal without logging in
        pass
