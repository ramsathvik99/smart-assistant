"""
3D Mathematics, Camera Projection, and Holographic Geometry Constructs.
Provides high-performance perspective math and depth-aware geometric objects.
"""
from __future__ import annotations
import math
import random
from typing import List, Tuple, Optional
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QRadialGradient, QBrush


class Camera3D:
    """Perspective camera with smooth translation, rotation, and mouse parallax."""

    def __init__(self, fov: float = 650.0):
        self.fov = fov
        self.x = 0.0
        self.y = 0.0
        self.z = -550.0
        self.pitch = 0.0  # Rotation around X (radians)
        self.yaw = 0.0    # Rotation around Y (radians)
        self.roll = 0.0   # Rotation around Z (radians)

        # Target coordinates for smooth easing
        self.target_x = 0.0
        self.target_y = 0.0
        self.target_z = -550.0
        self.target_pitch = 0.0
        self.target_yaw = 0.0

        # Mouse parallax offsets
        self.mouse_pitch = 0.0
        self.mouse_yaw = 0.0

    def set_mouse_offset(self, norm_x: float, norm_y: float):
        """norm_x, norm_y in range [-1.0, 1.0]. Max parallax tilt ~4 degrees."""
        self.mouse_yaw = norm_x * 0.075
        self.mouse_pitch = -norm_y * 0.055

    def update(self, dt: float, speed_mult: float = 1.0):
        factor = min(1.0, dt * 3.5 * speed_mult)
        self.x += (self.target_x - self.x) * factor
        self.y += (self.target_y - self.y) * factor
        self.z += (self.target_z - self.z) * factor
        
        # Combine target orientation with mouse parallax
        cur_target_pitch = self.target_pitch + self.mouse_pitch
        cur_target_yaw = self.target_yaw + self.mouse_yaw
        self.pitch += (cur_target_pitch - self.pitch) * factor
        self.yaw += (cur_target_yaw - self.yaw) * factor

    def project(self, x: float, y: float, z: float, cx: float, cy: float) -> Optional[Tuple[float, float, float, float]]:
        """
        Projects 3D point (x, y, z) into 2D viewport (screen_x, screen_y, scale, depth).
        Returns None if point is behind the camera.
        """
        # Apply camera translation relative to camera
        rx = x - self.x
        ry = y - self.y
        rz = z - self.z

        # Apply Yaw (rotation around Y axis)
        cos_y = math.cos(self.yaw)
        sin_y = math.sin(self.yaw)
        x1 = rx * cos_y - rz * sin_y
        z1 = rx * sin_y + rz * cos_y

        # Apply Pitch (rotation around X axis)
        cos_p = math.cos(self.pitch)
        sin_p = math.sin(self.pitch)
        y2 = ry * cos_p - z1 * sin_p
        z2 = ry * sin_p + z1 * cos_p

        # Check near clipping plane
        if z2 <= 40.0:
            return None

        scale = self.fov / z2
        sx = cx + x1 * scale
        sy = cy + y2 * scale
        return (sx, sy, scale, z2)


class OrbitalRing3D:
    """3D tilted orbital ring with telemetry hash marks and depth-graded lighting."""

    def __init__(self, radius: float, tilt_x: float, tilt_z: float, speed: float,
                 segments: int = 36, ticks: int = 10, dash_pattern: bool = False):
        self.radius = radius
        self.tilt_x = tilt_x
        self.tilt_z = tilt_z
        self.speed = speed
        self.segments = segments
        self.ticks = ticks
        self.dash_pattern = dash_pattern
        self.current_angle = random.random() * math.pi * 2

        # Precompute tilt constants
        self.cos_tx = math.cos(self.tilt_x)
        self.sin_tx = math.sin(self.tilt_x)
        self.cos_tz = math.cos(self.tilt_z)
        self.sin_tz = math.sin(self.tilt_z)

        # Per-frame projection cache
        self._cached_frame_id: int = -1
        self._cached_segments = []  # List of (QPointF(p1), QPointF(p2), avg_z, depth_factor)
        self._cached_ticks = []     # List of (QPointF(p_in), QPointF(p_out), avg_z, depth_f)

    def update(self, dt: float, speed_mult: float = 1.0):
        self.current_angle = (self.current_angle + self.speed * dt * speed_mult) % (math.pi * 2)

    def _prepare_frame(self, camera: Camera3D, cx: float, cy: float, scale: float = 1.0):
        """Projects 3D ring points and tick marks once per frame."""
        cos_tx = self.cos_tx
        sin_tx = self.sin_tx
        cos_tz = self.cos_tz
        sin_tz = self.sin_tz
        radius = self.radius * max(0.25, min(1.5, scale))
        angle = self.current_angle
        segs = self.segments

        pts_3d = []
        pts_2d = []
        for i in range(segs + 1):
            theta = (i / segs) * math.pi * 2 + angle
            rx = radius * math.cos(theta)
            rz = radius * math.sin(theta)

            # Rotate around X
            y1 = -rz * sin_tx
            z1 = rz * cos_tx

            # Rotate around Z
            x2 = rx * cos_tz - y1 * sin_tz
            y2 = rx * sin_tz + y1 * cos_tz
            z2 = z1

            proj = camera.project(x2, y2, z2, cx, cy)
            pts_3d.append(proj)
            pts_2d.append(QPointF(proj[0], proj[1]) if proj else None)

        self._cached_segments.clear()
        for i in range(segs):
            p1 = pts_3d[i]
            p2 = pts_3d[i + 1]
            if not p1 or not p2:
                continue
            avg_z = (p1[3] + p2[3]) * 0.5
            depth_factor = max(0.12, min(1.0, 750.0 / avg_z))
            self._cached_segments.append((pts_2d[i], pts_2d[i + 1], avg_z, depth_factor))

        self._cached_ticks.clear()
        if self.ticks > 0:
            r_inner = radius * 0.94
            r_outer = radius * 1.06
            for k in range(self.ticks):
                theta = (k / self.ticks) * math.pi * 2 + angle
                cos_t = math.cos(theta)
                sin_t = math.sin(theta)

                # Inner
                ix = r_inner * cos_t
                iz = r_inner * sin_t
                iy1 = -iz * sin_tx
                iz1 = iz * cos_tx
                ix2 = ix * cos_tz - iy1 * sin_tz
                iy2 = ix * sin_tz + iy1 * cos_tz
                p_in = camera.project(ix2, iy2, iz1, cx, cy)

                # Outer
                ox = r_outer * cos_t
                oz = r_outer * sin_t
                oy1 = -oz * sin_tx
                oz1 = oz * cos_tx
                ox2 = ox * cos_tz - oy1 * sin_tz
                oy2 = ox * sin_tz + oy1 * cos_tz
                p_out = camera.project(ox2, oy2, oz1, cx, cy)

                if p_in and p_out:
                    avg_tz = (p_in[3] + p_out[3]) * 0.5
                    depth_f = max(0.1, min(1.0, 750.0 / p_in[3]))
                    self._cached_ticks.append((
                        QPointF(p_in[0], p_in[1]),
                        QPointF(p_out[0], p_out[1]),
                        avg_tz,
                        depth_f
                    ))

    def draw(self, painter: QPainter, camera: Camera3D, cx: float, cy: float, base_color: QColor,
             opacity_mult: float = 1.0, depth_pass: str = "all", core_z: float = 0.0):
        # Calculate projection only once on back pass (or all pass)
        if depth_pass in ("back", "all"):
            self._prepare_frame(camera, cx, cy, scale=opacity_mult)

        from PyQt6.QtCore import QLineF
        r_base = base_color.red()
        g_base = base_color.green()
        b_base = base_color.blue()
        base_a = base_color.alpha() * opacity_mult
        pen = QPen()

        # 3 Depth Tiers: Far, Mid, Near
        tier_widths = [0.85, 1.25, 1.8]
        tier_alphas = [int(base_a * 0.35), int(base_a * 0.65), int(base_a * 0.95)]
        buckets = [[], [], []]

        # 1. Bucket Ring Segments
        for pt1, pt2, avg_z, depth_factor in self._cached_segments:
            if depth_pass == "back" and avg_z <= core_z:
                continue
            elif depth_pass == "front" and avg_z > core_z:
                continue

            tier = 0 if depth_factor < 0.4 else (1 if depth_factor < 0.75 else 2)
            buckets[tier].append(QLineF(pt1, pt2))

        # Render Ring Segments (3 batched draw calls max)
        for t_idx in range(3):
            line_list = buckets[t_idx]
            if not line_list:
                continue
            pen.setColor(QColor(r_base, g_base, b_base, tier_alphas[t_idx]))
            pen.setWidthF(tier_widths[t_idx])
            painter.setPen(pen)
            painter.drawLines(line_list)

        # 2. Bucket Ticks
        tick_buckets = [[], [], []]
        for pt_in, pt_out, avg_tz, depth_f in self._cached_ticks:
            if depth_pass == "back" and avg_tz <= core_z:
                continue
            elif depth_pass == "front" and avg_tz > core_z:
                continue

            tier = 0 if depth_f < 0.4 else (1 if depth_f < 0.75 else 2)
            tick_buckets[tier].append(QLineF(pt_in, pt_out))

        for t_idx in range(3):
            t_lines = tick_buckets[t_idx]
            if not t_lines:
                continue
            pen.setColor(QColor(r_base, g_base, b_base, int(tier_alphas[t_idx] * 0.85)))
            pen.setWidthF(tier_widths[t_idx] * 1.1)
            painter.setPen(pen)
            painter.drawLines(t_lines)


class HolographicGrid3D:
    """Subtle perspective horizon grid providing architectural floor depth."""

    def __init__(self, size: float = 1200.0, step: float = 150.0, elevation: float = 240.0):
        self.size = size
        self.step = step
        self.elevation = elevation  # Y position below center
        self.pulse = 0.0

    def update(self, dt: float, speed_mult: float = 1.0):
        self.pulse = (self.pulse + dt * 0.5 * speed_mult) % (math.pi * 2)

    def draw(self, painter: QPainter, camera: Camera3D, cx: float, cy: float, base_color: QColor,
             opacity: float = 0.25):
        from PyQt6.QtCore import QLineF
        y = self.elevation
        grid_lines = []

        # Longitudinal lines (Z-direction)
        cur_x = -self.size * 0.5
        max_x = self.size * 0.5
        while cur_x <= max_x:
            p_start = camera.project(cur_x, y, -200.0, cx, cy)
            p_end = camera.project(cur_x, y, 900.0, cx, cy)
            if p_start and p_end:
                grid_lines.append(QLineF(p_start[0], p_start[1], p_end[0], p_end[1]))
            cur_x += self.step

        # Latitudinal lines (X-direction)
        cur_z = -100.0
        while cur_z <= 850.0:
            p1 = camera.project(-self.size * 0.5, y, cur_z, cx, cy)
            p2 = camera.project(self.size * 0.5, y, cur_z, cx, cy)
            if p1 and p2:
                grid_lines.append(QLineF(p1[0], p1[1], p2[0], p2[1]))
            cur_z += self.step

        if grid_lines:
            alpha = int(45 * opacity)
            col = QColor(base_color.red(), base_color.green(), base_color.blue(), alpha)
            pen = QPen(col, 0.8)
            painter.setPen(pen)
            painter.drawLines(grid_lines)


class DataStream3D:
    """Subtle flowing 3D bezier curves with traveling energy light packets."""

    def __init__(self, start_pt: Tuple[float, float, float], end_pt: Tuple[float, float, float],
                 ctrl_pt: Tuple[float, float, float], speed: float = 0.4):
        self.start = start_pt
        self.end = end_pt
        self.ctrl = ctrl_pt
        self.speed = speed
        self.packet_progress = random.random()

    def update(self, dt: float, speed_mult: float = 1.0):
        self.packet_progress = (self.packet_progress + self.speed * dt * speed_mult) % 1.0

    def draw(self, painter: QPainter, camera: Camera3D, cx: float, cy: float, base_color: QColor,
             opacity: float = 0.35):
        # Sample curve points
        pts = []
        for i in range(13):
            t = i / 12.0
            # Quadratic bezier
            omt = 1.0 - t
            bx = omt * omt * self.start[0] + 2 * omt * t * self.ctrl[0] + t * t * self.end[0]
            by = omt * omt * self.start[1] + 2 * omt * t * self.ctrl[1] + t * t * self.end[1]
            bz = omt * omt * self.start[2] + 2 * omt * t * self.ctrl[2] + t * t * self.end[2]
            proj = camera.project(bx, by, bz, cx, cy)
            pts.append(proj)

        # Draw subtle guide line
        pen = QPen()
        for i in range(len(pts) - 1):
            p1 = pts[i]
            p2 = pts[i + 1]
            if p1 and p2:
                alpha = int(32 * opacity)
                col = QColor(base_color.red(), base_color.green(), base_color.blue(), alpha)
                pen.setColor(col)
                pen.setWidthF(0.9)
                painter.setPen(pen)
                painter.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))

        # Draw moving light packet
        t = self.packet_progress
        omt = 1.0 - t
        px = omt * omt * self.start[0] + 2 * omt * t * self.ctrl[0] + t * t * self.end[0]
        py = omt * omt * self.start[1] + 2 * omt * t * self.ctrl[1] + t * t * self.end[1]
        pz = omt * omt * self.start[2] + 2 * omt * t * self.ctrl[2] + t * t * self.end[2]
        proj = camera.project(px, py, pz, cx, cy)
        if proj:
            glow_rad = max(2.0, 5.5 * proj[2])
            alpha = int(180 * opacity)
            col = QColor(base_color.red(), base_color.green(), base_color.blue(), alpha)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(col)
            painter.drawEllipse(QPointF(proj[0], proj[1]), glow_rad, glow_rad)
