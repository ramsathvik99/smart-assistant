"""
NOVA Personality Engine
Provides consistent personality-driven behavior across the entire system.
"""

from .personality_core import get_personality, PersonalityCore
from .response_formatter import ResponseFormatter, format_response
from .behavior_layer import BehaviorLayer, adjust_behavior, get_behavior_layer
from .proactive_personality import (
    ProactivePersonality, 
    get_proactive_personality,
    start_proactive_system,
    stop_proactive_system,
    update_proactive_interaction
)

__all__ = [
    'get_personality',
    'PersonalityCore', 
    'ResponseFormatter',
    'format_response',
    'BehaviorLayer',
    'adjust_behavior',
    'get_behavior_layer',
    'ProactivePersonality',
    'get_proactive_personality',
    'start_proactive_system',
    'stop_proactive_system',
    'update_proactive_interaction'
]
