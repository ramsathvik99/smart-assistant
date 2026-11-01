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
    core_x_ratio: float = 0.72
    core_y_ratio: float = 0.32
    core_scale: float = 1.0


class StateController:
    """Computes and eases dynamic parameters based on active page and assistant state."""

    PAGE_PRESETS: Dict[str, VisualParameters] = {
        "home": VisualParameters(
            core_radius=72.0, core_intensity=1.0, ring_speed=1.0, ring_count=5,
            particle_speed=1.0, particle_excitement=1.0, node_connectivity=0.30,
            grid_opacity=0.22, data_stream_opacity=0.30,
            camera_target_pitch=0.08, camera_target_yaw=0.0, camera_target_z=-550.0,
            core_x_ratio=0.59, core_y_ratio=0.42, core_scale=1.0,
        ),
        "assistant": VisualParameters(
            core_radius=22.0, core_intensity=0.85, ring_speed=1.0, ring_count=2,
            particle_speed=0.85, particle_excitement=1.0, node_connectivity=0.20,
            grid_opacity=0.15, data_stream_opacity=0.20,
            camera_target_pitch=0.04, camera_target_yaw=-0.04, camera_target_z=-560.0,
            core_x_ratio=0.083, core_y_ratio=0.82, core_scale=0.32,
        ),
        "communications": VisualParameters(
            core_radius=22.0, core_intensity=0.80, ring_speed=0.85, ring_count=2,
            particle_speed=0.75, particle_excitement=0.85, node_connectivity=0.20,
            grid_opacity=0.18, data_stream_opacity=0.20,
            camera_target_pitch=0.05, camera_target_yaw=0.03, camera_target_z=-570.0,
            core_x_ratio=0.083, core_y_ratio=0.82, core_scale=0.32,
        ),
        "workspace": VisualParameters(
            core_radius=22.0, core_intensity=0.80, ring_speed=0.80, ring_count=2,
            particle_speed=0.75, particle_excitement=0.80, node_connectivity=0.20,
            grid_opacity=0.20, data_stream_opacity=0.18,
            camera_target_pitch=0.05, camera_target_yaw=-0.03, camera_target_z=-560.0,
            core_x_ratio=0.083, core_y_ratio=0.82, core_scale=0.32,
        ),
        "schedule": VisualParameters(
            core_radius=22.0, core_intensity=0.80, ring_speed=0.85, ring_count=2,
            particle_speed=0.80, particle_excitement=0.85, node_connectivity=0.18,
            grid_opacity=0.18, data_stream_opacity=0.18,
            camera_target_pitch=0.04, camera_target_yaw=0.0, camera_target_z=-550.0,
            core_x_ratio=0.083, core_y_ratio=0.82, core_scale=0.32,
        ),
        "automation": VisualParameters(
            core_radius=22.0, core_intensity=0.85, ring_speed=0.95, ring_count=2,
            particle_speed=0.90, particle_excitement=0.95, node_connectivity=0.22,
            grid_opacity=0.20, data_stream_opacity=0.20,
            camera_target_pitch=0.05, camera_target_yaw=0.02, camera_target_z=-540.0,
            core_x_ratio=0.083, core_y_ratio=0.82, core_scale=0.32,
        ),
        "connected_world": VisualParameters(
            core_radius=22.0, core_intensity=0.82, ring_speed=0.90, ring_count=2,
            particle_speed=0.85, particle_excitement=0.90, node_connectivity=0.22,
            grid_opacity=0.20, data_stream_opacity=0.20,
            camera_target_pitch=0.05, camera_target_yaw=-0.02, camera_target_z=-550.0,
            core_x_ratio=0.083, core_y_ratio=0.82, core_scale=0.32,
        ),
        "intelligence": VisualParameters(
            core_radius=22.0, core_intensity=0.85, ring_speed=0.95, ring_count=2,
            particle_speed=0.90, particle_excitement=0.95, node_connectivity=0.25,
            grid_opacity=0.18, data_stream_opacity=0.20,
            camera_target_pitch=0.04, camera_target_yaw=0.02, camera_target_z=-530.0,
            core_x_ratio=0.083, core_y_ratio=0.82, core_scale=0.32,
        ),
        "settings": VisualParameters(
            core_radius=22.0, core_intensity=0.75, ring_speed=0.65, ring_count=2,
            particle_speed=0.65, particle_excitement=0.65, node_connectivity=0.15,
            grid_opacity=0.15, data_stream_opacity=0.15,
            camera_target_pitch=0.03, camera_target_yaw=0.0, camera_target_z=-580.0,
            core_x_ratio=0.083, core_y_ratio=0.82, core_scale=0.32,
        ),
    }

    def __init__(self):
        self.current_page: str = "home"
        self.assistant_state: str = "idle"
        self.audio_level: float = 0.0
        self.progress: float = 0.0
        self.current = VisualParameters()
        self.target = VisualParameters()
        self._transition_t: float = 1.0
        self._transition_duration: float = 0.45  # 450ms smooth transition
        self.set_page("home")

    def set_page(self, page_id: str):
        pid = (page_id or "home").lower()
        if pid not in self.PAGE_PRESETS:
            pid = "home"
        self.current_page = pid
        self.target = self.PAGE_PRESETS[pid]
        self._transition_t = 0.0

    def update_dock_target(self, x_ratio: float, y_ratio: float):
        """Dynamically update docked core coordinates to match sidebar dock slot."""
        for pid, preset in self.PAGE_PRESETS.items():
            if pid != "home":
                preset.core_x_ratio = x_ratio
                preset.core_y_ratio = y_ratio
        if self.current_page != "home":
            self.target.core_x_ratio = x_ratio
            self.target.core_y_ratio = y_ratio

    def set_assistant_state(self, state: str):
        self.assistant_state = (state or "idle").lower()

    def set_audio_level(self, level: float):
        self.audio_level = max(0.0, min(1.0, float(level or 0.0)))

    def set_progress(self, prog: float):
        self.progress = max(0.0, min(100.0, float(prog or 0.0)))

    def update(self, dt: float, speed_mult: float = 1.0):
        if self._transition_t < 1.0:
            self._transition_t = min(1.0, self._transition_t + (dt / self._transition_duration) * speed_mult)
            t = ease_out_cubic(self._transition_t)

            # Interpolate parameters
            c = self.current
            tg = self.target
            factor = min(1.0, t * 0.35)
            c.core_radius += (tg.core_radius - c.core_radius) * factor
            c.core_intensity += (tg.core_intensity - c.core_intensity) * factor
            c.ring_speed += (tg.ring_speed - c.ring_speed) * factor
            c.particle_speed += (tg.particle_speed - c.particle_speed) * factor
            c.particle_excitement += (tg.particle_excitement - c.particle_excitement) * factor
            c.node_connectivity += (tg.node_connectivity - c.node_connectivity) * factor
            c.grid_opacity += (tg.grid_opacity - c.grid_opacity) * factor
            c.data_stream_opacity += (tg.data_stream_opacity - c.data_stream_opacity) * factor
            c.camera_target_pitch += (tg.camera_target_pitch - c.camera_target_pitch) * factor
            c.camera_target_yaw += (tg.camera_target_yaw - c.camera_target_yaw) * factor
            c.camera_target_z += (tg.camera_target_z - c.camera_target_z) * factor
            c.core_x_ratio += (tg.core_x_ratio - c.core_x_ratio) * factor
            c.core_y_ratio += (tg.core_y_ratio - c.core_y_ratio) * factor
            c.core_scale += (tg.core_scale - c.core_scale) * factor

    def get_state_modifiers(self) -> Dict[str, float]:
        """Calculates dynamic pulse and speed multipliers from current assistant state and real audio."""
        s = self.assistant_state
        audio_boost = self.audio_level * 1.5
        if s == "thinking":
            return {"speed": 2.2, "core_pulse": 1.4, "excitement": 1.8, "audio_react": 0.0}
        elif s == "speaking":
            return {"speed": 1.35 + audio_boost * 0.6, "core_pulse": 1.4 + audio_boost * 1.8, "excitement": 1.5 + audio_boost * 2.0, "audio_react": self.audio_level}
        elif s in ("executing", "working", "processing"):
            return {"speed": 1.8, "core_pulse": 1.3, "excitement": 1.6, "audio_react": 0.0}
        elif s == "listening":
            return {"speed": 1.0 + audio_boost * 0.8, "core_pulse": 1.25 + audio_boost * 1.4, "excitement": 1.2 + audio_boost * 1.5, "audio_react": self.audio_level}
        elif s in ("error", "failed"):
            return {"speed": 0.75, "core_pulse": 1.6, "excitement": 0.8, "audio_react": 0.0}
        elif s in ("offline", "paused", "muted", "disabled"):
            return {"speed": 0.25, "core_pulse": 0.4, "excitement": 0.3, "audio_react": 0.0}
        else:  # idle
            return {"speed": 1.0, "core_pulse": 1.0, "excitement": 1.0, "audio_react": 0.0}
