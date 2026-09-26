"""
UI Module for Nova Smart Assistant.
Exposes UI components, visual response surfaces, audio visualizers, and viseme engine.
"""

from .viseme import VisemeStream, text_to_visemes, to_latin, VISEMES

__all__ = [
    'VisemeStream',
    'text_to_visemes',
    'to_latin',
    'VISEMES',
]

