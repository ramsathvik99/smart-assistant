"""
State Controller for the 3D Ambient System.
Manages smooth visual parameter interpolation across all 9 dashboard pages and assistant states.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, Any


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    t1 = t - 1.0
    return t1 * t1 * t1 + 1.0


@dataclass
class VisualParameters:
    core_radius: float = 48.0
    core_intensity: float = 0.85
    ring_speed: float = 1.0
    ring_count: int = 4
    particle_speed: float = 1.0
    particle_excitement: float = 1.0
    node_connectivity: float = 0.25
    grid_opacity: float = 0.25
    data_stream_opacity: float = 0.30
    camera_target_pitch: float = 0.0
    camera_target_yaw: float = 0.0
    camera_target_z: float = -550.0


class StateController:
    """Computes and eases dynamic parameters based on active page and assistant state."""

    PAGE_PRESETS: Dict[str, VisualParameters] = {
        "home": VisualParameters(
            core_radius=52.0, core_intensity=0.90, ring_speed=1.0, ring_count=4,
            particle_speed=1.0, particle_excitement=1.0, node_connectivity=0.25,
            grid_opacity=0.22, data_stream_opacity=0.30,
            camera_target_pitch=0.08, camera_target_yaw=0.0, camera_target_z=-550.0,
        ),
        "assistant": VisualParameters(
            core_radius=64.0, core_intensity=1.15, ring_speed=1.35, ring_count=5,
            particle_speed=1.25, particle_excitement=1.4, node_connectivity=0.35,
            grid_opacity=0.15, data_stream_opacity=0.45,
            camera_target_pitch=0.04, camera_target_yaw=-0.08, camera_target_z=-500.0,
        ),
        "communications": VisualParameters(
            core_radius=44.0, core_intensity=0.80, ring_speed=0.9, ring_count=3,
            particle_speed=1.1, particle_excitement=1.1, node_connectivity=0.60,
            grid_opacity=0.28, data_stream_opacity=0.70,
            camera_target_pitch=0.12, camera_target_yaw=0.10, camera_target_z=-570.0,
        ),
        "workspace": VisualParameters(
            core_radius=46.0, core_intensity=0.82, ring_speed=0.85, ring_count=4,
            particle_speed=0.85, particle_excitement=0.9, node_connectivity=0.40,
            grid_opacity=0.55, data_stream_opacity=0.35,
            camera_target_pitch=0.16, camera_target_yaw=-0.05, camera_target_z=-560.0,
        ),
        "schedule": VisualParameters(
            core_radius=50.0, core_intensity=0.88, ring_speed=0.95, ring_count=5,
            particle_speed=0.95, particle_excitement=1.0, node_connectivity=0.20,
            grid_opacity=0.20, data_stream_opacity=0.25,
            camera_target_pitch=0.05, camera_target_yaw=0.0, camera_target_z=-540.0,
        ),
        "automation": VisualParameters(
            core_radius=48.0, core_intensity=0.92, ring_speed=1.2, ring_count=4,
            particle_speed=1.3, particle_excitement=1.3, node_connectivity=0.75,
            grid_opacity=0.35, data_stream_opacity=0.65,
            camera_target_pitch=0.14, camera_target_yaw=0.06, camera_target_z=-530.0,
        ),
        "connected_world": VisualParameters(
            core_radius=46.0, core_intensity=0.85, ring_speed=1.05, ring_count=4,
            particle_speed=1.15, particle_excitement=1.15, node_connectivity=0.70,
            grid_opacity=0.30, data_stream_opacity=0.55,
            camera_target_pitch=0.10, camera_target_yaw=-0.09, camera_target_z=-550.0,
        ),
        "intelligence": VisualParameters(
            core_radius=58.0, core_intensity=1.05, ring_speed=1.15, ring_count=4,
            particle_speed=1.2, particle_excitement=1.35, node_connectivity=0.85,
            grid_opacity=0.22, data_stream_opacity=0.50,
            camera_target_pitch=0.06, camera_target_yaw=0.04, camera_target_z=-510.0,
        ),
        "settings": VisualParameters(
            core_radius=42.0, core_intensity=0.70, ring_speed=0.60, ring_count=3,
            particle_speed=0.60, particle_excitement=0.6, node_connectivity=0.18,
            grid_opacity=0.18, data_stream_opacity=0.15,
            camera_target_pitch=0.04, camera_target_yaw=0.0, camera_target_z=-600.0,
        ),
    }

    def __init__(self):
        self.current_page: str = "home"
        self.assistant_state: str = "idle"
        self.current = VisualParameters()
        self.target = VisualParameters()
        self._transition_t: float = 1.0
        self._transition_duration: float = 0.55  # ~550ms smooth transition
        self.set_page("home")

    def set_page(self, page_id: str):
        pid = (page_id or "home").lower()
        if pid not in self.PAGE_PRESETS:
            pid = "home"
        self.current_page = pid
        self.target = self.PAGE_PRESETS[pid]
        self._transition_t = 0.0

    def set_assistant_state(self, state: str):
        self.assistant_state = (state or "idle").lower()

    def update(self, dt: float, speed_mult: float = 1.0):
        if self._transition_t < 1.0:
            self._transition_t = min(1.0, self._transition_t + (dt / self._transition_duration) * speed_mult)
            t = ease_out_cubic(self._transition_t)

            # Interpolate parameters
            c = self.current
            tg = self.target
            c.core_radius += (tg.core_radius - c.core_radius) * t * 0.25
            c.core_intensity += (tg.core_intensity - c.core_intensity) * t * 0.25
            c.ring_speed += (tg.ring_speed - c.ring_speed) * t * 0.25
            c.particle_speed += (tg.particle_speed - c.particle_speed) * t * 0.25
            c.particle_excitement += (tg.particle_excitement - c.particle_excitement) * t * 0.25
            c.node_connectivity += (tg.node_connectivity - c.node_connectivity) * t * 0.25
            c.grid_opacity += (tg.grid_opacity - c.grid_opacity) * t * 0.25
            c.data_stream_opacity += (tg.data_stream_opacity - c.data_stream_opacity) * t * 0.25
            c.camera_target_pitch += (tg.camera_target_pitch - c.camera_target_pitch) * t * 0.25
            c.camera_target_yaw += (tg.camera_target_yaw - c.camera_target_yaw) * t * 0.25
            c.camera_target_z += (tg.camera_target_z - c.camera_target_z) * t * 0.25

    def get_state_modifiers(self) -> Dict[str, float]:
        """Calculates dynamic pulse and speed multipliers from current assistant state."""
        s = self.assistant_state
        if s == "thinking":
            return {"speed": 2.2, "core_pulse": 1.4, "excitement": 1.8}
        elif s == "speaking":
            return {"speed": 1.35, "core_pulse": 1.6, "excitement": 1.5}
        elif s in ("executing", "working", "processing"):
            return {"speed": 1.8, "core_pulse": 1.3, "excitement": 1.6}
        elif s == "listening":
            return {"speed": 1.0, "core_pulse": 1.35, "excitement": 1.2}
        elif s in ("error", "failed"):
            return {"speed": 0.75, "core_pulse": 1.5, "excitement": 0.8}
        elif s in ("offline", "paused", "muted", "disabled"):
            return {"speed": 0.35, "core_pulse": 0.5, "excitement": 0.4}
        else:  # idle
            return {"speed": 1.0, "core_pulse": 1.0, "excitement": 1.0}
