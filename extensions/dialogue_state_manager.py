"""
Dialogue State Manager for PHASE 6

Tracks conversation state across multiple turns, extracts and binds entities,
infers missing context, and persists dialogue history.

Enables multi-turn conversations with context memory.
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
from datetime import datetime
import re
import json

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.unified_command_router import Intent

# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class EntityExtraction:
    """Extracted entity from user input"""
    entity_type: str  # "LOCATION", "PERSON", "TIME", "NUMBER", etc.
    entity_value: Any
    confidence: float
    source: str  # "direct", "contextual", "historical"


@dataclass
class ConversationTurn:
    """Single turn in conversation"""
    turn_number: int
    timestamp: str
    user_input: str
    detected_intents: List[str] = field(default_factory=list)
    extracted_entities: Dict[str, Any] = field(default_factory=dict)
    assistant_response: str = ""
    response_timestamp: str = ""
    carried_forward_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DialogueState:
    """Complete dialogue state across turns"""
    session_id: str
    user_id: str
    start_time: str
    last_activity: str
    current_turn: int = 0
    turns: List[ConversationTurn] = field(default_factory=list)
    
    # Accumulated context
    entities: Dict[str, Any] = field(default_factory=dict)
    preferences: Dict[str, Any] = field(default_factory=dict)
    recent_queries: List[str] = field(default_factory=list)
    recent_intents: List[str] = field(default_factory=list)
    session_context: Dict[str, Any] = field(default_factory=dict)
    
    # State flags
    is_active: bool = True


# ============================================================================
# Entity Extraction Patterns
# ============================================================================

LOCATION_PATTERNS = [
    r'\b(Guntur|Hyderabad|Bangalore|Delhi|Mumbai|Chennai|Kolkata|London|New York)\b',
    r'in\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',  # Capitalized city names
]

TIME_PATTERNS = [
    r'\b(today|tomorrow|tonight|now|soon|later|yesterday)\b',
    r'\b(\d{1,2})\s*(AM|PM|am|pm)\b',
    r'\b(\d{1,2}):(\d{2})\s*(AM|PM)?\b',
]

PERSON_PATTERNS = [
    r'(?:to|for)\s+([A-Z][a-z]+)',  # "to Sathvik", "for Mom"
    r'(Sathvik|Mom|Dad|Brother|Sister)',
]

# ============================================================================
# Dialogue State Manager
# ============================================================================

class DialogueStateManager:
    """
    Manages conversation state across multiple turns.
    
    Responsibilities:
    - Track entities and context
    - Extract information from user input
    - Bind to historical context
    - Infer missing parameters
    - Persist conversation history
    """
    
    # Context reference patterns
    CONTEXTUAL_REFERENCES = {
        "same_location": r"\b(there|there too|same place|same city|same location)\b",
        "same_time": r"\b(same time|then|same day)\b",
        "continuation": r"\b(also|additionally|plus|and then|meanwhile)\b",
        "reference": r"\b(what about|how about|what\s+regarding|tell me about)\b",
    }

    # --------------------------------------------------------------------
    # Pronoun / anaphora patterns that signal the user means the entity
    # mentioned in the previous turn rather than a new one.
    # Ordered from most specific to least specific.
    # --------------------------------------------------------------------
    _PRONOUN_PATTERNS = [
        # "close it", "open it", "delete it", "remove it"
        r'^(?P<verb>\w+)\s+(?:the\s+)?(?P<pronoun>it|that|them|this|those)\s*$',
        # "get rid of it", "throw it away"
        r'^(?:get\s+rid\s+of|throw\s+(?:it\s+)?away)\s*(?P<pronoun>it|that|them|this)?\s*$',
        # bare "delete it" / "launch it" / "close it" with trailing words
        r'^(?P<verb>\w+(?:\s+\w+)?)\s+(?P<pronoun>it|that|them|this)\b',
    ]

    # Entity slot names we track in `last_mentioned_entity`
    _TRACKED_ENTITY_SOURCES = ["target", "name", "application", "folder", "file"]
    
    def __init__(self, user_id: str):
        """Initialize dialogue state manager"""
        self.user_id = user_id
        self.current_state = DialogueState(
            session_id=self._generate_session_id(),
            user_id=user_id,
            start_time=datetime.now().isoformat(),
            last_activity=datetime.now().isoformat()
        )
        # Tracks the last concrete entity (app name, folder name, etc.) mentioned
        # so that pronouns ("it", "that") can be resolved on the next turn.
        # Structure: {"value": str, "intent": str, "entity_type": str}
        self._last_mentioned_entity: Optional[Dict[str, Any]] = None
        print(f"[DIALOGUE_STATE_MANAGER] Initialized for user {user_id}")
    
    def _generate_session_id(self) -> str:
        """Generate unique session ID"""
        import uuid
        return str(uuid.uuid4())[:8]
    
    def start_session(self) -> str:
        """Start new conversation session"""
        self.current_state.is_active = True
        return self.current_state.session_id
    
    def process_turn(self, user_input: str) -> Dict[str, Any]:
        """
        Process single conversation turn.

        Step 0: Resolve pronouns / anaphoric references ("it", "that", "them")
                to the actual entity from the previous turn before any other
                processing.  This means "delete it" becomes "delete WhatsApp"
                (or whatever was last mentioned) before the router ever sees it.

        Returns enriched input with context bindings.
        """
        self.current_state.current_turn += 1
        turn_num = self.current_state.current_turn

        # ------------------------------------------------------------------
        # Step 0 — Pronoun / reference resolution
        # ------------------------------------------------------------------
        resolved_input, reference_was_resolved = self._resolve_references(user_input)

        # ------------------------------------------------------------------
        # Steps 1–4 unchanged — operate on the resolved input
        # ------------------------------------------------------------------
        # Extract entities from (possibly resolved) input
        extracted_entities = self._extract_entities(resolved_input)

        # Detect contextual references
        contextual_refs = self._detect_contextual_references(resolved_input)

        # Bind to historical context
        bound_context = self._bind_to_context(
            extracted_entities,
            contextual_refs
        )

        # Enrich user input with context
        enriched_input = self._enrich_input(resolved_input, bound_context)

        # Create turn record
        turn = ConversationTurn(
            turn_number=turn_num,
            timestamp=datetime.now().isoformat(),
            user_input=user_input,
            extracted_entities=bound_context
        )
        if reference_was_resolved:
            turn.carried_forward_context["reference_resolved"] = resolved_input

        self.current_state.turns.append(turn)
        self.current_state.last_activity = datetime.now().isoformat()

        return {
            "original_input": user_input,
            "enriched_input": enriched_input,
            "resolved_input": resolved_input,        # new — router uses this
            "reference_resolved": reference_was_resolved,
            "context": bound_context,
            "turn_number": turn_num,
            "session_id": self.current_state.session_id,
        }
    
    def _resolve_references(self, user_input: str) -> tuple:
        """
        Resolve pronominal / anaphoric references before routing.

        Detects inputs like:
          "close it"          → "close WhatsApp"   (if WhatsApp was last opened)
          "delete it"         → "delete AI folder" (if AI folder was last created)
          "remove that"       → "remove test_ai"
          "get rid of it"     → "get rid of test_ai"

        Returns:
            (resolved_input: str, was_resolved: bool)

        If no pronoun is detected, or no previous entity is available,
        returns the original input unchanged with was_resolved=False.

        Safety rule: if the action is destructive (delete/remove/close/
        shutdown) and there is NO tracked entity to resolve to,
        we do NOT guess — we return the original and let the router
        handle ambiguity.
        """
        if not self._last_mentioned_entity:
            return user_input, False

        stripped = user_input.strip()
        lower = stripped.lower()

        # Fast exit: if the input already contains a specific named entity
        # (i.e. is not just a bare pronoun command) — don't rewrite it.
        # Heuristic: if there are 4+ tokens after the verb, assume explicit.
        tokens = lower.split()
        if len(tokens) >= 5:
            return user_input, False

        # Check for pronoun patterns
        for pat in self._PRONOUN_PATTERNS:
            m = re.match(pat, lower, re.IGNORECASE)
            if m:
                entity_value = self._last_mentioned_entity.get("value", "")
                entity_type = self._last_mentioned_entity.get("entity_type", "")
                intent = self._last_mentioned_entity.get("intent", "")

                if not entity_value:
                    return user_input, False

                # Replace the pronoun portion with the entity value.
                # We reconstruct from the original casing of user_input.
                pronoun_match = re.search(
                    r'\b(it|that|them|this|those)\b', lower
                )
                if pronoun_match:
                    start, end = pronoun_match.start(), pronoun_match.end()
                    resolved = stripped[:start] + entity_value + stripped[end:]
                    print(
                        f"[REFERENCE_RESOLUTION] '{user_input}' → '{resolved}' "
                        f"(entity: '{entity_value}' from {intent})"
                    )
                    return resolved, True

                # Pattern matched "get rid of" style — append entity
                resolved = f"{stripped} {entity_value}".strip()
                print(
                    f"[REFERENCE_RESOLUTION] '{user_input}' → '{resolved}' "
                    f"(entity: '{entity_value}' from {intent})"
                )
                return resolved, True

        return user_input, False

    def _update_last_mentioned_entity(
        self, execution_result: Dict[str, Any], intents: List[str]
    ) -> None:
        """
        After a turn executes, record the most salient entity so that
        the next turn can resolve pronouns against it.

        We store:
          - For OPEN_APPLICATION / CLOSE_APPLICATION → the app target
          - For FILE_OPERATIONS → the folder/file name
          - For MUSIC → the song/query
        """
        if not intents:
            return

        primary_intent = intents[0] if intents else ""

        # Try to pull the entity value from the current turn's context
        if self.current_state.turns:
            last_turn = self.current_state.turns[-1]
            ctx = last_turn.extracted_entities  # bound_context dict

            # The unified router stores params in carried_forward_context after update_state;
            # we also check session_context accumulated across turns.
            # The simplest reliable source is the enriched input itself — parse it.
            raw_input = last_turn.user_input

            # Attempt extraction by intent type
            entity_value = None
            entity_type = "TARGET"

            if primary_intent in ("OPEN_APPLICATION", "CLOSE_APPLICATION"):
                # "open WhatsApp" / "launch Chrome" → extract app name
                m = re.search(
                    r'\b(?:open|launch|start|run|close|quit|exit|terminate|kill|bring up|'
                    r'get\s+\w+\s+running|I\s+(?:want|need)\s+(?:to\s+use\s+)?)\s+(.+)',
                    raw_input, re.IGNORECASE
                )
                if m:
                    entity_value = m.group(1).strip().rstrip('.')
                    entity_type = "APPLICATION"

            elif primary_intent == "FILE_OPERATIONS":
                # "create folder called AI" / "delete the test_ai folder"
                m = re.search(
                    r'\b(?:folder|directory|file)\s+(?:named\s+|called\s+)?(.+?)(?:\s+on\s+desktop)?$',
                    raw_input, re.IGNORECASE
                )
                if m:
                    entity_value = m.group(1).strip().rstrip('.')
                    entity_type = "FOLDER"
                else:
                    # "create a folder test_ai" / "make test_ai"
                    m2 = re.search(
                        r'\b(?:create|make|delete|remove)\s+(?:a\s+)?(?:folder\s+|directory\s+)?(.+)',
                        raw_input, re.IGNORECASE
                    )
                    if m2:
                        entity_value = m2.group(1).strip().rstrip('.')
                        entity_type = "FOLDER"

            elif primary_intent == "MUSIC":
                m = re.search(r'\bplay\s+(.+)', raw_input, re.IGNORECASE)
                if m:
                    entity_value = m.group(1).strip()
                    entity_type = "SONG"

            if entity_value:
                self._last_mentioned_entity = {
                    "value": entity_value,
                    "intent": primary_intent,
                    "entity_type": entity_type,
                }
                print(
                    f"[REFERENCE_TRACKING] Stored entity: '{entity_value}' "
                    f"({entity_type}) from {primary_intent}"
                )

    def _extract_entities(self, user_input: str) -> "List[EntityExtraction]":
        """Extract entities from user input"""
        entities = []
        
        # Extract locations
        for pattern in LOCATION_PATTERNS:
            matches = re.finditer(pattern, user_input, re.IGNORECASE)
            for match in matches:
                entities.append(EntityExtraction(
                    entity_type="LOCATION",
                    entity_value=match.group(1),
                    confidence=0.95,
                    source="direct"
                ))
        
        # Extract times
        for pattern in TIME_PATTERNS:
            matches = re.finditer(pattern, user_input, re.IGNORECASE)
            for match in matches:
                entities.append(EntityExtraction(
                    entity_type="TIME",
                    entity_value=match.group(0),
                    confidence=0.90,
                    source="direct"
                ))
        
        # Extract people
        for pattern in PERSON_PATTERNS:
            matches = re.finditer(pattern, user_input, re.IGNORECASE)
            for match in matches:
                entities.append(EntityExtraction(
                    entity_type="PERSON",
                    entity_value=match.group(1) if match.lastindex else match.group(0),
                    confidence=0.85,
                    source="direct"
                ))
        
        return entities
    
    def _detect_contextual_references(self, user_input: str) -> Dict[str, bool]:
        """Detect references to previous context"""
        references = {}
        input_lower = user_input.lower()
        
        for ref_type, pattern in self.CONTEXTUAL_REFERENCES.items():
            if re.search(pattern, input_lower):
                references[ref_type] = True
        
        return references
    
    def _bind_to_context(
        self,
        extracted_entities: List[EntityExtraction],
        contextual_refs: Dict[str, bool]
    ) -> Dict[str, Any]:
        """Bind extracted entities to conversation history"""
        bound_context = {}
        
        # Add explicit entities from current input
        for entity in extracted_entities:
            key = entity.entity_type.lower()
            bound_context[key] = {
                "value": entity.entity_value,
                "source": "explicit",
                "confidence": entity.confidence
            }
        
        # Add contextual references from history
        if contextual_refs.get("same_location") and "location" not in bound_context:
            if "location" in self.current_state.entities:
                bound_context["location"] = {
                    "value": self.current_state.entities["location"],
                    "source": "contextual",
                    "confidence": 0.85
                }
        
        if contextual_refs.get("same_time") and "time" not in bound_context:
            if "time" in self.current_state.entities:
                bound_context["time"] = {
                    "value": self.current_state.entities["time"],
                    "source": "contextual",
                    "confidence": 0.80
                }
        
        # Fill in missing entities from historical data
        for key, value in self.current_state.entities.items():
            if key.lower() not in bound_context and key not in ["recent_intents", "recent_queries"]:
                bound_context[key] = {
                    "value": value,
                    "source": "historical",
                    "confidence": 0.6
                }
        
        return bound_context
    
    def _enrich_input(self, user_input: str, context: Dict[str, Any]) -> str:
        """Enrich user input with context information"""
        enriched = user_input
        
        # Add contextual information as hints
        if "location" in context and "location" not in user_input.lower():
            location = context["location"]["value"]
            # Add location to input for intent analyzer
            enriched = f"{enriched} [context: in {location}]"
        
        if "time" in context and any(t in user_input.lower() for t in ["tomorrow", "today", "when"]):
            time_val = context["time"]["value"]
            enriched = f"{enriched} [context: {time_val}]"
        
        return enriched
    
    def update_state(self, execution_result: Dict[str, Any], intents: List[str]) -> None:
        """Update dialogue state after execution"""
        
        # Update recent intents
        self.current_state.recent_intents.extend(intents)
        self.current_state.recent_intents = self.current_state.recent_intents[-5:]  # Keep last 5
        
        # Update entities from current turn
        if self.current_state.turns:
            last_turn = self.current_state.turns[-1]
            
            # Record detected intents
            last_turn.detected_intents = intents
            
            # Update accumulated entities
            for key, value in last_turn.extracted_entities.items():
                self.current_state.entities[key] = value.get("value")
            
            # Store execution result
            last_turn.carried_forward_context = execution_result

        # Track last salient entity for pronoun resolution on next turn
        self._update_last_mentioned_entity(execution_result, intents)
    
    def record_response(self, response: str) -> None:
        """Record assistant response"""
        if self.current_state.turns:
            last_turn = self.current_state.turns[-1]
            last_turn.assistant_response = response
            last_turn.response_timestamp = datetime.now().isoformat()
    
    def get_state(self) -> DialogueState:
        """Get current dialogue state"""
        return self.current_state
    
    def get_context_summary(self) -> str:
        """Get human-readable context summary"""
        lines = [f"📋 Session {self.current_state.session_id}"]
        lines.append(f"Turn: {self.current_state.current_turn}")
        
        if self.current_state.entities:
            lines.append("Known Entities:")
            for key, value in self.current_state.entities.items():
                lines.append(f"  - {key}: {value}")
        
        if self.current_state.recent_intents:
            lines.append(f"Recent Intents: {', '.join(self.current_state.recent_intents[-3:])}")
        
        return "\n".join(lines)
    
    def end_session(self) -> Dict[str, Any]:
        """End conversation session and return summary"""
        self.current_state.is_active = False
        
        return {
            "session_id": self.current_state.session_id,
            "turns": len(self.current_state.turns),
            "duration": (
                datetime.fromisoformat(self.current_state.last_activity) -
                datetime.fromisoformat(self.current_state.start_time)
            ).total_seconds(),
            "entities_discovered": len(self.current_state.entities),
            "intents_used": list(set(self.current_state.recent_intents))
        }


# ============================================================================
# Global Instance
# ============================================================================

_dialogue_managers: Dict[str, DialogueStateManager] = {}


def get_dialogue_manager(user_id: str) -> DialogueStateManager:
    """Get or create dialogue manager for user"""
    if user_id not in _dialogue_managers:
        _dialogue_managers[user_id] = DialogueStateManager(user_id)
    return _dialogue_managers[user_id]


# ============================================================================
# Test Cases
# ============================================================================

if __name__ == "__main__":
    print("[DIALOGUE_STATE_MANAGER] Test Cases\n")
    
    # Create manager for test user
    manager = DialogueStateManager("test_user")
    manager.start_session()
    
    # Turn 1: Weather query
    print("=" * 70)
    print("TURN 1: 'What is the weather in Guntur?'")
    print("=" * 70)
    result1 = manager.process_turn("What is the weather in Guntur?")
    print(f"Original: {result1['original_input']}")
    print(f"Enriched: {result1['enriched_input']}")
    print(f"Context: {result1['context']}")
    manager.update_state(
        {"weather": "28°C, clear skies", "location": "Guntur"},
        ["WEATHER_QUERY"]
    )
    manager.record_response("It's 28°C in Guntur with clear skies.")
    print(manager.get_context_summary())
    
    # Turn 2: Follow-up query with context inference
    print("\n" + "=" * 70)
    print("TURN 2: 'What about tomorrow?'")
    print("=" * 70)
    result2 = manager.process_turn("What about tomorrow?")
    print(f"Original: {result2['original_input']}")
    print(f"Enriched: {result2['enriched_input']}")
    print(f"Context: {result2['context']}")
    manager.update_state(
        {"weather": "32°C, sunny", "location": "Guntur"},
        ["WEATHER_QUERY"]
    )
    manager.record_response("Tomorrow in Guntur: 32°C, sunny.")
    print(manager.get_context_summary())
    
    # Turn 3: Multi-intent with context
    print("\n" + "=" * 70)
    print("TURN 3: 'Set a reminder for the rain'")
    print("=" * 70)
    result3 = manager.process_turn("Set a reminder for the rain")
    print(f"Original: {result3['original_input']}")
    print(f"Enriched: {result3['enriched_input']}")
    print(f"Context: {result3['context']}")
    manager.update_state(
        {"reminder": "set", "location": "Guntur"},
        ["REMINDERS"]
    )
    manager.record_response("Reminder set: 'Rain expected in Guntur'")
    print(manager.get_context_summary())
    
    # End session
    print("\n" + "=" * 70)
    print("SESSION SUMMARY")
    print("=" * 70)
    summary = manager.end_session()
    print(f"Turns: {summary['turns']}")
    print(f"Duration: {summary['duration']:.1f}s")
    print(f"Entities: {summary['entities_discovered']}")
    print(f"Intents: {', '.join(summary['intents_used'])}")
