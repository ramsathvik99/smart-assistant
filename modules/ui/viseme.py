"""
Viseme & Mouth-Shape Synchronization Engine for Nova Smart Assistant.
Translates speech transcripts / text into time-sequenced visemes (mouth openness, width, closure)
for accurate audio-visualizer and facial presence synchronization.
Supports universal Latin decomposition, diacritic stripping, Cyrillic, and Greek transliteration.
"""

from __future__ import annotations

import unicodedata
from collections import deque
from typing import Dict, List, Tuple, Optional

# (openness 0..1, width -1..+1, closure 0..1)
# closure forces the lips together regardless of loudness (e.g. for /m/, /b/, /p/)
VISEMES: Dict[str, Tuple[float, float, float]] = {
    "REST": (0.00,  0.00, 0.00),
    "AA":   (0.92, -0.05, 0.00),   # a
    "E":    (0.52,  0.42, 0.00),   # e
    "I":    (0.20,  0.62, 0.00),   # i, y
    "O":    (0.55, -0.52, 0.00),   # o
    "U":    (0.26, -0.74, 0.00),   # u, w
    "MBP":  (0.00,  0.00, 1.00),   # m, b, p - lips pressed shut
    "FV":   (0.10,  0.22, 0.55),   # f, v - lower lip to teeth
    "S":    (0.16,  0.42, 0.00),   # s, z, c, j, x
    "L":    (0.36,  0.18, 0.00),   # l
    "TD":   (0.28,  0.12, 0.00),   # t, d, n
    "K":    (0.30, -0.04, 0.00),   # k, g, h, q
    "R":    (0.28, -0.16, 0.00),   # r
}

_DURATION_WEIGHTS = {
    "REST": 1.0, "AA": 1.15, "E": 1.05, "I": 1.0, "O": 1.1, "U": 1.05,
    "MBP": 0.5, "FV": 0.8, "S": 0.9, "L": 0.65, "TD": 0.5, "K": 0.55,
    "R": 0.55
}

_LETTER_MAP = {
    "a": "AA", "e": "E", "i": "I", "y": "I", "o": "O", "u": "U", "w": "U",
    "b": "MBP", "p": "MBP", "m": "MBP",
    "f": "FV", "v": "FV",
    "s": "S", "z": "S", "c": "S", "j": "S", "x": "S",
    "l": "L",
    "t": "TD", "d": "TD", "n": "TD",
    "k": "K", "g": "K", "h": "K", "q": "K",
    "r": "R",
}

_UNDECOMPOSED = {
    "ı": "i", "ø": "o", "đ": "d", "ħ": "h", "ŀ": "l", "ŧ": "t",
    "ß": "s", "æ": "a", "œ": "o", "þ": "t", "ð": "d", "ŋ": "n",
    "ł": "l",
}

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "j", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "s", "ч": "s", "ш": "s", "щ": "s", "ъ": "",
    "ы": "i", "ь": "", "э": "e", "ю": "u", "я": "a",
    "і": "i", "ї": "i", "є": "e", "ґ": "g", "ў": "u",
}

_GREEK = {
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i",
    "θ": "t", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "i",
    "φ": "f", "χ": "h", "ψ": "s", "ω": "o",
}


def to_latin(text: str) -> str:
    """Reduce any incoming text to lowercase 26 bare Latin letters, digits, and whitespace."""
    buf: List[str] = []
    for ch in text.lower():
        if ch in _UNDECOMPOSED:
            ch = _UNDECOMPOSED[ch]
        elif ch in _CYRILLIC:
            ch = _CYRILLIC[ch]
        elif ch in _GREEK:
            ch = _GREEK[ch]
        
        # Decompose diacritics
        decomp = unicodedata.normalize("NFD", ch)
        stripped = "".join(c for c in decomp if unicodedata.category(c) != "Mn")
        buf.append(stripped)
    return "".join(buf)


def text_to_visemes(text: str) -> List[Tuple[str, float]]:
    """
    Convert text into a list of (viseme_name, duration_weight).
    Punctuation and whitespace insert REST visemes.
    """
    latin = to_latin(text)
    out: List[Tuple[str, float]] = []
    last_viseme: Optional[str] = None
    
    for ch in latin:
        if ch.isspace() or ch in ".,!?;:-_()[]{}'\"/\\":
            if last_viseme != "REST":
                out.append(("REST", 1.0))
                last_viseme = "REST"
            continue
            
        viseme = _LETTER_MAP.get(ch)
        if viseme:
            weight = _DURATION_WEIGHTS.get(viseme, 1.0)
            # Merge adjacent identical consonants
            if viseme == last_viseme and viseme in ("MBP", "TD", "K", "FV"):
                continue
            out.append((viseme, weight))
            last_viseme = viseme
        else:
            if last_viseme != "REST":
                out.append(("REST", 0.5))
                last_viseme = "REST"
                
    return out


class VisemeStream:
    """
    Real-time queue that consumes text fragments and yields timed visemes
    synchronized with speech playback rate.
    """
    def __init__(self, target_fps: float = 30.0, chars_per_second: float = 14.0):
        self.target_fps = max(1.0, float(target_fps))
        self.chars_per_second = max(1.0, float(chars_per_second))
        self._queue: deque[Tuple[str, float, float, float]] = deque()
        self._current_viseme = "REST"
        self._current_values = VISEMES["REST"]

    def reset(self):
        self._queue.clear()
        self._current_viseme = "REST"
        self._current_values = VISEMES["REST"]

    def feed_text(self, text: str):
        """Add speech text to the viseme stream."""
        if not text:
            return
        viseme_sequence = text_to_visemes(text)
        seconds_per_unit = 1.0 / self.chars_per_second
        
        for name, dur_weight in viseme_sequence:
            values = VISEMES.get(name, VISEMES["REST"])
            frames_count = max(1, int(round(dur_weight * seconds_per_unit * self.target_fps)))
            for _ in range(frames_count):
                self._queue.append((name, values[0], values[1], values[2]))

    def next_frame(self) -> Tuple[str, float, float, float]:
        """
        Advance one frame and return (name, openness, width, closure).
        Returns REST when queue is empty.
        """
        if self._queue:
            self._current_viseme, op, wd, cl = self._queue.popleft()
            self._current_values = (op, wd, cl)
        else:
            self._current_viseme = "REST"
            self._current_values = VISEMES["REST"]
        return (self._current_viseme, self._current_values[0], self._current_values[1], self._current_values[2])

    def has_pending(self) -> bool:
        return len(self._queue) > 0
