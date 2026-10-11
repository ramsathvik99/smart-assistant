"""
Configuration and quality profiles for the 3D Ambient System.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class AmbientConfig:
    enabled: bool = True
    quality: str = "High"  # High, Medium, Low
    particle_density: str = "High"  # High, Medium, Low
    motion_profile: str = "Dynamic"  # Dynamic, Subtle, Reduced Motion
    mouse_parallax: bool = True
    state_reactive: bool = True
    target_fps: int = 60
    
    # Computed / adaptive properties
    max_particles: int = 140
    max_connections: int = 40
    enable_bloom: bool = True
    enable_data_streams: bool = True
    enable_hologram_grid: bool = True
    speed_multiplier: float = 1.0

    def apply_quality_profile(self):
        """Adjust internal rendering limits according to quality and density presets."""
        q = (self.quality or "High").capitalize()
        d = (self.particle_density or "High").capitalize()
        m = (self.motion_profile or "Dynamic").lower()

        # Quality settings
        if q == "Low":
            self.target_fps = 30
            self.enable_bloom = False
            self.enable_data_streams = False
            self.max_connections = 12
        elif q == "Medium":
            self.target_fps = 60
            self.enable_bloom = True
            self.enable_data_streams = True
            self.max_connections = 24
        else:  # High
            self.target_fps = 60
            self.enable_bloom = True
            self.enable_data_streams = True
            self.max_connections = 45

        # Particle density
        if d == "Low":
            self.max_particles = 60 if q != "Low" else 40
        elif d == "Medium":
            self.max_particles = 100 if q != "Low" else 60
        else:  # High
            self.max_particles = 160 if q == "High" else (100 if q == "Medium" else 60)

        # Motion profile
        if "reduced" in m:
            self.speed_multiplier = 0.25
            self.mouse_parallax = False
        elif "subtle" in m:
            self.speed_multiplier = 0.65
        else:
            self.speed_multiplier = 1.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AmbientConfig:
        cfg = cls(
            enabled=bool(data.get("ambient_3d_enabled", True)),
            quality=str(data.get("ambient_3d_quality", "High")),
            particle_density=str(data.get("ambient_3d_density", "High")),
            motion_profile=str(data.get("ambient_3d_motion", "Dynamic")),
            mouse_parallax=bool(data.get("ambient_3d_parallax", True)),
            state_reactive=bool(data.get("ambient_3d_state_reactive", True)),
        )
        cfg.apply_quality_profile()
        return cfg
