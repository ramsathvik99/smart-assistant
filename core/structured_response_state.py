"""
Canonical Structured Response State
Persists rich, structured response objects to enable deterministic follow-up resolution
(e.g., 'tell me the answer', 'and the second', 'to the first step', 'continue', 'all of them')
without falling back to or depending on LLMs.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StructuredResponseState:
    response_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    response_type: str = "GENERAL"  # CALCULATION, RECOMMENDATION, LIST, GOAL_PLAN, DOCUMENT, ARTIFACT
    full_content: str = ""
    items: List[Any] = field(default_factory=list)
    current_index: int = 0
    remaining_items: List[Any] = field(default_factory=list)
    spoken_segments: List[str] = field(default_factory=list)
    remaining_segments: List[str] = field(default_factory=list)
    related_entities: List[str] = field(default_factory=list)
    source_turn: int = 1
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "response_id": self.response_id,
            "response_type": self.response_type,
            "full_content": self.full_content,
            "items": list(self.items),
            "current_index": self.current_index,
            "remaining_items": list(self.remaining_items),
            "spoken_segments": list(self.spoken_segments),
            "remaining_segments": list(self.remaining_segments),
            "related_entities": list(self.related_entities),
            "source_turn": self.source_turn,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StructuredResponseState:
        return cls(
            response_id=data.get("response_id", str(uuid.uuid4())[:8]),
            response_type=data.get("response_type", "GENERAL"),
            full_content=data.get("full_content", ""),
            items=list(data.get("items", [])),
            current_index=int(data.get("current_index", 0)),
            remaining_items=list(data.get("remaining_items", [])),
            spoken_segments=list(data.get("spoken_segments", [])),
            remaining_segments=list(data.get("remaining_segments", [])),
            related_entities=list(data.get("related_entities", [])),
            source_turn=int(data.get("source_turn", 1)),
            timestamp=float(data.get("timestamp", time.time())),
        )
