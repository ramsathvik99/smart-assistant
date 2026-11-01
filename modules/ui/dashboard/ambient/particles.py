"""
3D Particle System and Constellation Graph Network.
Implements orbital particles, drifting cosmic dust, and dynamic proximity node connections.
"""
from __future__ import annotations
import math
import random
from typing import List, Tuple, Optional
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush
from .geometry import Camera3D


class Particle3D:
    __slots__ = ('x', 'y', 'z', 'vx', 'vy', 'vz', 'radius', 'angle', 'speed',
                 'orbit_tilt', 'kind', 'base_size', 'alpha_factor', 'pulse_offset')

    def __init__(self, kind: str = "orbital"):
        self.kind = kind
        self.pulse_offset = random.random() * math.pi * 2
        self.alpha_factor = 0.4 + random.random() * 0.6
        self.base_size = 1.0 + random.random() * 2.2
        self.reset()

    def reset(self):
        if self.kind == "orbital":
            self.radius = 120.0 + random.random() * 320.0
            self.angle = random.random() * math.pi * 2
            self.speed = (0.2 + random.random() * 0.5) * (1 if random.random() > 0.4 else -1)
            self.orbit_tilt = (random.random() - 0.5) * 1.2
            self.y = (random.random() - 0.5) * 60.0
            self.x = self.radius * math.cos(self.angle)
            self.z = self.radius * math.sin(self.angle)
            self.vx = 0.0
            self.vy = 0.0
            self.vz = 0.0
        elif self.kind == "node":
            # Distributed constellation node in volume
            self.x = (random.random() - 0.5) * 750.0
            self.y = (random.random() - 0.5) * 450.0
            self.z = (random.random() - 0.5) * 500.0 + 100.0
            self.vx = (random.random() - 0.5) * 12.0
            self.vy = (random.random() - 0.5) * 8.0
            self.vz = (random.random() - 0.5) * 10.0
            self.radius = 0.0
            self.angle = 0.0
            self.speed = 0.0
            self.orbit_tilt = 0.0
        else:  # ambient dust
            self.x = (random.random() - 0.5) * 1100.0
            self.y = (random.random() - 0.5) * 750.0
            self.z = random.random() * 900.0 - 150.0
            self.vx = (random.random() - 0.5) * 15.0
            self.vy = (random.random() - 0.5) * 10.0
            self.vz = (random.random() - 0.5) * 12.0
            self.radius = 0.0
            self.angle = 0.0
            self.speed = 0.0
            self.orbit_tilt = 0.0


class ParticleSystem3D:
    """Manages 3D particle physics, orbital mechanics, and proximity node connections."""

    def __init__(self, count: int = 120):
        self.particles: List[Particle3D] = []
        self._init_particles(count)
        self.connection_distance: float = 140.0
        self.node_connection_opacity: float = 0.25

    def _init_particles(self, count: int):
        self.particles.clear()
        for i in range(count):
            if i < int(count * 0.45):
                p = Particle3D(kind="orbital")
            elif i < int(count * 0.75):
                p = Particle3D(kind="node")
            else:
                p = Particle3D(kind="ambient")
            self.particles.append(p)

    def set_particle_count(self, count: int):
        cur = len(self.particles)
        if count == cur:
            return
        if count > cur:
            for i in range(cur, count):
                k = "orbital" if i % 2 == 0 else "node"
                self.particles.append(Particle3D(kind=k))
        else:
            self.particles = self.particles[:count]

    def update(self, dt: float, speed_mult: float = 1.0, excitement: float = 1.0):
        for p in self.particles:
            if p.kind == "orbital":
                # Accelerate rotation with excitement (e.g. thinking/executing)
                p.angle += p.speed * dt * speed_mult * excitement
                cos_t = math.cos(p.orbit_tilt)
                sin_t = math.sin(p.orbit_tilt)
                rx = p.radius * math.cos(p.angle)
                rz = p.radius * math.sin(p.angle)
                p.x = rx
                p.y = rz * sin_t + math.sin(p.angle * 2.0 + p.pulse_offset) * 15.0
                p.z = rz * cos_t
            else:
                p.x += p.vx * dt * speed_mult
                p.y += p.vy * dt * speed_mult
                p.z += p.vz * dt * speed_mult

                # Bounds wrap
                if abs(p.x) > 600.0:
                    p.x = -p.x * 0.95
                if abs(p.y) > 420.0:
                    p.y = -p.y * 0.95
                if p.z > 800.0:
                    p.z = -120.0
                elif p.z < -140.0:
                    p.z = 780.0

    def draw(self, painter: QPainter, camera: Camera3D, cx: float, cy: float, base_color: QColor,
             max_connections: int = 35, opacity: float = 0.5):
        # Project all particles
        projected = []
        for p in self.particles:
            res = camera.project(p.x, p.y, p.z, cx, cy)
            if res:
                projected.append((p, res))

        # Sort by depth (back to front)
        projected.sort(key=lambda item: item[1][3], reverse=True)

        # 1. Draw proximity connection lines between nearby 'node' particles
        if max_connections > 0 and self.node_connection_opacity > 0.02:
            from PyQt6.QtCore import QLineF
            conn_lines = []
            nodes = [item for item in projected if item[0].kind == "node"]
            dist_sq_limit = self.connection_distance * self.connection_distance

            for i in range(len(nodes)):
                if len(conn_lines) >= max_connections:
                    break
                p1, proj1 = nodes[i]
                for j in range(i + 1, min(i + 5, len(nodes))):
                    p2, proj2 = nodes[j]
                    dx = p1.x - p2.x
                    dy = p1.y - p2.y
                    dz = p1.z - p2.z
                    d_sq = dx * dx + dy * dy + dz * dz
                    if d_sq < dist_sq_limit:
                        conn_lines.append(QLineF(proj1[0], proj1[1], proj2[0], proj2[1]))
                        if len(conn_lines) >= max_connections:
                            break

            if conn_lines:
                col = QColor(base_color.red(), base_color.green(), base_color.blue(),
                             int(36 * self.node_connection_opacity * opacity))
                pen = QPen(col)
                pen.setWidthF(0.8)
                painter.setPen(pen)
                painter.drawLines(conn_lines)

        # 2. Draw particle points / glows
        painter.setPen(Qt.PenStyle.NoPen)
        r_base, g_base, b_base = base_color.red(), base_color.green(), base_color.blue()
        base_a = base_color.alpha() * opacity
        brush = QBrush(Qt.BrushStyle.SolidPattern)

        for p, proj in projected:
            sx, sy, scale, z = proj
            depth_factor = max(0.12, min(1.0, 750.0 / z))
            alpha = int(base_a * depth_factor * p.alpha_factor)
            if alpha <= 3:
                continue

            pt_radius = max(0.8, p.base_size * scale * 0.9)
            brush.setColor(QColor(r_base, g_base, b_base, alpha))
            painter.setBrush(brush)
            painter.drawEllipse(QPointF(sx, sy), pt_radius, pt_radius)
