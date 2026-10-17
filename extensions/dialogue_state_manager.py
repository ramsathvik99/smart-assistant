"""
Dialogue State Manager for PHASE 6

Tracks conversation state across multiple turns, extracts and binds entities,
infers missing context, and persists dialogue history.

Enables multi-turn conversations with context memory.
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import re
import json
import time
import os
import uuid

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
class GoalOutcome:
    """Explicit outcome of a terminal or blocked goal (PHASE 8)."""
    goal_id: str
    user_id: str
    user_request: str
    attempted_action: str
    actual_outcome: str  # "COMPLETED", "FAILED", "BLOCKED", "CANCELLED", "WAITING_FOR_USER"
    success: bool
    summary: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    entities: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    failure_reason: Optional[str] = None
    blocking_reason: Optional[str] = None
    step_outcomes: List[Dict[str, Any]] = field(default_factory=list)
    adaptation_applied: bool = False
    verified: bool = False
    verification_source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResponseState:
    """Explicit structured response state for resumption, navigation, and barge-in tracking."""
    response_id: str = ""
    response_type: str = "conversational"  # "recommendation", "list", "conversational", "document", "system"
    full_text: str = ""
    speech_segments: List[str] = field(default_factory=list)
    current_segment_index: int = 0
    spoken_segments: List[str] = field(default_factory=list)
    remaining_segments: List[str] = field(default_factory=list)
    items: List[str] = field(default_factory=list)
    current_item_index: int = 0
    interrupted: bool = False
    interruption_position: int = 0
    conversation_turn_id: int = 0
    related_entities: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DialogueState:
    """Complete dialogue state across turns"""
    session_id: str
    user_id: str
    start_time: str
    last_activity: str
    current_turn: int = 0
    turns: List[ConversationTurn] = field(default_factory=list)
    # Structured response state model (Task 5)
    active_response_state: Optional[ResponseState] = None
    # New structured entity tracking for Level 5 (Section 3)
    primary_active_entity: Optional[Dict[str, Any]] = None  # e.g., {"value": "Calculator", "entity_type": "APPLICATION"}
    last_mentioned_entity: Optional[Dict[str, Any]] = None
    active_entity: Optional[Dict[str, Any]] = None
    active_entity_set: Dict[str, List[Any]] = field(default_factory=dict)  # e.g., {"APPLICATION": ["Calculator", "Notepad"]}
    active_application: Optional[str] = None
    active_applications: List[str] = field(default_factory=list)
    active_document: Optional[Dict[str, Any]] = None
    active_documents: List[Dict[str, Any]] = field(default_factory=list)
    active_file: Optional[Dict[str, Any]] = None
    active_files: List[Dict[str, Any]] = field(default_factory=list)
    active_folder: Optional[Dict[str, Any]] = None
    active_folders: List[Dict[str, Any]] = field(default_factory=list)
    active_browser_result_set: List[Dict[str, Any]] = field(default_factory=list)
    active_browser_result: Optional[Dict[str, Any]] = None
    recent_actions: List[Dict[str, Any]] = field(default_factory=list)
    recent_entities: List[Dict[str, Any]] = field(default_factory=list)
    recent_successful_actions: List[Dict[str, Any]] = field(default_factory=list)
    recent_failed_actions: List[Dict[str, Any]] = field(default_factory=list)
    previous_contexts: List[Dict[str, Any]] = field(default_factory=list)
    
    # Accumulated context
    entities: Dict[str, Any] = field(default_factory=dict)
    preferences: Dict[str, Any] = field(default_factory=dict)
    recent_queries: List[str] = field(default_factory=list)
    recent_intents: List[str] = field(default_factory=list)
    session_context: Dict[str, Any] = field(default_factory=dict)
    
    # LIVE INTERACTION STATE (PHASE 1, 2 & 3)
    current_goal: Optional[Dict[str, Any]] = None
    original_goal: Optional[Dict[str, Any]] = None
    current_subgoals: List[Dict[str, Any]] = field(default_factory=list)
    current_plan: Optional[Dict[str, Any]] = None
    original_plan: Optional[Dict[str, Any]] = None
    goal_status: str = "IDLE"  # "IDLE", "PENDING", "RUNNING", "COMPLETED", "FAILED", "WAITING_FOR_USER", "CANCELLED"
    adaptation_count: int = 0
    max_adaptations: int = 2
    adaptation_reason: Optional[str] = None
    adaptation_history: List[Dict[str, Any]] = field(default_factory=list)
    completed_steps: List[Dict[str, Any]] = field(default_factory=list)
    failed_steps: List[Dict[str, Any]] = field(default_factory=list)
    pending_goal_continuation: Optional[Dict[str, Any]] = None
    active_window: Optional[Dict[str, Any]] = None
    last_action: Optional[Dict[str, Any]] = None
    last_action_result: Optional[Dict[str, Any]] = None
    last_search_results: List[Dict[str, Any]] = field(default_factory=list)
    last_search_results_turn: int = 0
    last_search_results_intent: Optional[str] = None
    active_task: Optional[Dict[str, Any]] = None
    active_device: Optional[Dict[str, Any]] = None
    active_artifact: Optional[Dict[str, Any]] = None
    active_document: Optional[Dict[str, Any]] = None
    active_documents: List[Dict[str, Any]] = field(default_factory=list)
    pending_action: Optional[Dict[str, Any]] = None
    pending_confirmation: bool = False  # True when pending_action awaits user yes/no
    pending_clarification: Optional[str] = None
    environmental_observations: Dict[str, Any] = field(default_factory=dict)
    last_state_difference: Optional[Dict[str, Any]] = None
    execution_status: str = "idle"

    # PHASE 8: Goal Outcome and Post-Goal Context
    last_goal_outcome: Optional[Dict[str, Any]] = None
    goal_outcomes_history: List[Dict[str, Any]] = field(default_factory=list)
    post_goal_context: Dict[str, Any] = field(default_factory=dict)

    # PHASE 9: Cross-Session Continuity & Persistent Goals
    pending_goal_resumption: Optional[Dict[str, Any]] = None  # Goals offered across session boundary
    restored_goal: Optional[Dict[str, Any]] = None           # Goal currently undergoing restoration

    # EPHEMERAL VISUAL RESPONSE SURFACE (User-scoped, short-lived cache)
    last_visual_response: Optional[Dict[str, Any]] = None
    visual_response_history: List[Dict[str, Any]] = field(default_factory=list)

    # Conversational Continuation Tracking
    current_response: str = ""
    current_spoken_segment: str = ""
    remaining_response_segments: List[str] = field(default_factory=list)
    current_recommendation_list: List[str] = field(default_factory=list)
    current_list_position: int = 0
    interruption_position: int = 0
    interrupted_speech_text: str = ""
    active_calculation: Optional[Dict[str, Any]] = None

    # State flags
    is_active: bool = True

    @property
    def active_goal(self) -> Optional[Dict[str, Any]]:
        return self.current_goal

    @active_goal.setter
    def active_goal(self, value: Optional[Dict[str, Any]]):
        self.current_goal = value


@dataclass
class PersistentGoalRecord:
    """Phase 9: Structured representation of a goal eligible for cross-session resumption."""
    goal_id: str
    user_id: str
    original_request: str
    goal_type: str
    goal_status: str
    current_step: int = 0
    remaining_steps: List[Dict[str, Any]] = field(default_factory=list)
    entities: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())
    session_id: str = ""
    resumable: bool = True
    persistence_reason: str = "WAITING_FOR_USER"
    required_user_input: Optional[str] = None
    last_known_result: Optional[str] = None
    environment_assumptions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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

def normalize_speech_extensions(text: str) -> str:
    """Normalize spoken extensions like 'dot txt' -> '.txt', 'report dot gov dot in dot txt' -> 'report.gov.in.txt'"""
    if not text:
        return text
    # Convert 'dot <ext>' to '.<ext>'
    pattern = r'\bdot\s+([a-zA-Z0-9]+)\b'
    prev = None
    curr = text
    while prev != curr:
        prev = curr
        curr = re.sub(pattern, r'.\1', curr, flags=re.IGNORECASE)
    # Join filename and dot-extension if separated by space
    curr = re.sub(r'(\w+)\s+\.([a-zA-Z0-9]+)', r'\1.\2', curr)
    return curr

DISALLOWED_ENTITY_NAMES = {
    "both", "both of them", "them", "those", "those two", "these", "it", "that", "this",
    "that one", "this one", "the other one", "the other app", "other", "all", "all of them",
    "another", "new", "fresh", "different", "second", "first", "third", "last", "the first one",
    "the second one", "the last one", "to", "ti", "something", "anything", "nothing", "app",
    "application", "file", "folder", "document", "the app", "the other", "the application",
    "anymore", "more", "now", "again", "today", "yesterday", "tomorrow", "up", "down", "out", "in"
}

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
        # "close it", "open it", "delete it", "remove it", "cancel it", "stop it"
        r'^(?P<verb>open|close|quit|exit|launch|start|run|delete|remove|kill|terminate|show|display|read|write|type|insert|put|save|send|copy|move|rename)\s+(?:the\s+)?(?P<pronoun>it|that|them|this|those)\s*$',
        # "delete that file", "open that file", "show that file", "delete this file" (referential noun only when no concrete name follows)
        r'^(?P<verb>open|close|quit|exit|launch|start|run|delete|remove|kill|terminate|show|display|read|write|type|insert|put|save|send|copy|move|rename)\s+(?:the|that|this)\s+(?:file|document|presentation|folder|app|task)\s*$',
        # "inside it create ...", "in it create ..."
        r'^(?:inside|in)\s+(?:it|that)\b',
        # "get rid of it", "throw it away"
        r'^(?:get\s+rid\s+of|throw\s+(?:it\s+)?away)\s*(?P<pronoun>it|that|them|this)?\s*$',
        # bare "delete it" / "launch it" / "close it" with trailing words (must start with recognized action verb)
        r'^(?P<verb>open|close|quit|exit|launch|start|run|delete|remove|kill|terminate|show|display|read|write|type|insert|put|save|send|copy|move|rename)\s+(?P<pronoun>it|that|them|this)\b',
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
        # Initialize new entity tracking structures
        self.current_state.primary_active_entity = None
        self.current_state.active_entity_set = {}
        print(f"[DIALOGUE_STATE_MANAGER] Initialized for user {user_id}")
    
    def reset_state(self):
        """Reset conversation and session state to initial clean state."""
        self.current_state = DialogueState(
            session_id=self._generate_session_id(),
            user_id=self.user_id,
            start_time=datetime.now().isoformat(),
            last_activity=datetime.now().isoformat()
        )
        self._last_mentioned_entity = None
    
    def _generate_session_id(self) -> str:
        """Generate unique session ID"""
        import uuid
        return str(uuid.uuid4())[:8]
    
    def start_session(self) -> str:
        """Start new conversation session"""
        self.current_state.is_active = True
        self.current_state.last_visual_response = None
        self.current_state.visual_response_history = []
        self.check_resumable_goals(auto_offer=True)
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
        user_input = normalize_speech_extensions(user_input)
        self.current_state.current_turn += 1
        turn_num = self.current_state.current_turn

        # ------------------------------------------------------------------
        # Step 0 — Pending confirmation handling before pronoun resolution
        # NOTE: We resolve the input here but do NOT clear pending_action.
        #       brain.py Step 1.55 is the canonical executor that clears it
        #       after the confirmed command has been executed.  Clearing here
        #       would race with brain.py and lose the pending_action before
        #       brain.py can read and execute it.
        # ------------------------------------------------------------------
        lower_input = user_input.strip().lower()
        if self.current_state.pending_action:
            if re.match(r'^(yes|yeah|yep|sure|please|ok|okay|affirmative|indeed|certainly|of\s+course|yup|definitely|absolutely)\b', lower_input):
                if isinstance(self.current_state.pending_action, dict):
                    resolved_input = self.current_state.pending_action.get("command") or f"{self.current_state.pending_action.get('action', '')} {self.current_state.pending_action.get('target', '')}".strip()
                else:
                    resolved_input = str(self.current_state.pending_action)
                reference_was_resolved = True
                print(f"[CONFIRMATION] User affirmed pending action -> '{resolved_input}' (will execute in brain.py)")
                # Do NOT clear pending_action here — brain.py Step 1.55 reads
                # it, executes the command, and clears it after verification.
            elif re.match(r'^(no|nah|nope|cancel|stop|never\s*mind|don\'?t)\b', lower_input):
                print(f"[CONFIRMATION] User cancelled pending action (will clear in brain.py)")
                # Do NOT clear here either — brain.py Step 1.55 / Step 1.5
                # handles the cancellation path and clears the state.
                resolved_input = "cancel"
                reference_was_resolved = True
            else:
                resolved_input, reference_was_resolved = self._resolve_references(user_input)
        else:
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
        # Update primary_active_entity and active_entity_set based on extracted entities
        if extracted_entities:
            for ent in extracted_entities:
                etype_key = ent.entity_type.upper()
                raw_val = ent.entity_value
                if not raw_val:
                    continue
                self.current_state.primary_active_entity = {"value": raw_val, "entity_type": etype_key}
                if etype_key not in self.current_state.active_entity_set:
                    self.current_state.active_entity_set[etype_key] = []
                if raw_val not in self.current_state.active_entity_set[etype_key]:
                    self.current_state.active_entity_set[etype_key].append(raw_val)
        elif bound_context:
            for etype, evalue in bound_context.items():
                # Normalize entity type key
                etype_key = etype.upper()
                raw_val = evalue.get("value") if isinstance(evalue, dict) else evalue
                if not raw_val:
                    continue
                # Update primary active entity
                self.current_state.primary_active_entity = {"value": raw_val, "entity_type": etype_key}
                # Update entity set collection
                if etype_key not in self.current_state.active_entity_set:
                    self.current_state.active_entity_set[etype_key] = []
                if raw_val not in self.current_state.active_entity_set[etype_key]:
                    self.current_state.active_entity_set[etype_key].append(raw_val)
        if reference_was_resolved:
            turn.carried_forward_context["reference_resolved"] = resolved_input

        self.current_state.turns.append(turn)
        self.current_state.last_activity = datetime.now().isoformat()

        return {
            "original_input": user_input,
            "raw_user_input": user_input,
            "normalized_user_input": clean_text if 'clean_text' in locals() else user_input,
            "enriched_input": enriched_input,
            "resolved_input": resolved_input,        # new — router uses this
            "reference_resolved": reference_was_resolved,
            "context": bound_context,
            "turn_number": turn_num,
            "session_id": self.current_state.session_id,
        }
    
    def resolve_references(self, user_input: str) -> Dict[str, Any]:
        """Public interface for reference resolution."""
        resolved, was_resolved = self._resolve_references(user_input)
        return {"resolved_input": resolved, "was_resolved": was_resolved}

    def _resolve_references(self, user_input: str) -> tuple:
        """
        Resolve pronominal / anaphoric references and contextual follow-ups before routing.

        Detects inputs like:
          - Status checks: "What's its status?" -> "check status of task <id>" or "<device> status"
          - State inquiries: "Is it on?" -> "is caps lock on" (if caps lock was last toggled/set)
          - Comparative follow-ups: "What about Hyderabad?" -> "what is the weather in Hyderabad"
          - Selection follow-ups: "Show me the other one" -> "open file <other_file_path>"
          - Browser queries: "Search for AI news" when on YouTube -> "search youtube for AI news"
          - Pronoun commands: "close it" -> "close WhatsApp", "delete it" -> "delete AI folder"

        Returns:
            (resolved_input: str, was_resolved: bool)
        """
        stripped = user_input.strip()
        # Strip wake words and assistant names
        clean_text = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*', '', stripped, flags=re.IGNORECASE).strip()
        lower = clean_text.lower() if clean_text else stripped.lower()
        if not clean_text:
            clean_text = stripped

        # Guard against corrupting list/continuation commands:
        # "tell them all", "tell me all of them", "show them all", "what are those", "tell me those", "all of them", "first one", "last one"
        # These are structured list navigation commands, NOT noun replacement commands!
        is_list_nav_command = bool(
            re.search(r'^(?:(?:hey|ok|okay)\s+\w+\s+)?(?:can\s+you\s+|could\s+you\s+|please\s+)?(?:tell|say|show|what\s+are|give\s+me|list)\s+(?:me\s+)?(?:all\s+of\s+them|all\s+them|them\s+all|those|them|all)\b', lower)
            or re.match(r'^(?:tell|show|say|what\s+are)\s+(?:me\s+)?(?:all\s+of\s+them|all|them|those|all\s+them|them\s+all)$', lower)
            or lower in ("tell them all", "tell me all of them", "show them all", "what are those", "tell me those", "all of them", "tell all of them")
        )
        if is_list_nav_command:
            return user_input, False

        # ---- Plural reference resolution ----
        # Handle phrases like "both of them", "both", "all of them", "them", "those two", "both apps", etc.
        # Resolve strictly to entities in the active_entity_set for the relevant semantic domain.
        # Guard: If user is asking to read aloud or transfer/insert content/artifacts,
        # "them" / "those" refers to content/artifacts (WHAT), NOT applications (WHERE)!
        is_content_or_reading_op = bool(
            re.search(r'\b(?:read|recite|speak|listen)\b', lower) or
            re.search(r'\b(?:write|insert|paste|type|put)\s+(?:them|those|all\s+of\s+them|it|this|that|these)\b', lower)
        )
        plural_patterns = [
            r"\b(?:both(?:\s+of\s+them)?|both\s+apps|both\s+applications|those\s+two|these\s+two|the\s+two(?:\s+apps|\s+applications)?|all\s+of\s+them|all\s+open\s+(?:apps|applications|files|documents)|them)\b",
        ]
        plural_match = (not is_content_or_reading_op) and any(re.search(pat, lower) for pat in plural_patterns)
        if plural_match:
            # Check for an action verb in the command (e.g. "close both", "open both of them")
            m_act = re.match(r'^(?:please\s+|can\s+you\s+)?(close|quit|exit|terminate|kill|shut|open|launch|start|run|delete|remove)\b', clean_text, re.IGNORECASE)
            
            # Determine which entity type has an active set; prefer semantically relevant domain
            entity_type = None
            if m_act:
                v = m_act.group(1).lower()
                if v in ("close", "quit", "exit", "terminate", "kill", "shut", "open", "launch", "start", "run"):
                    entity_type = "APPLICATION"
                elif v in ("delete", "remove"):
                    entity_type = "FILE" if self.current_state.active_entity_set.get("FILE") else "APPLICATION"
            elif self.current_state.primary_active_entity:
                p_type = self.current_state.primary_active_entity.get("entity_type")
                # Reject timestamp or reminder entity sets from noun replacement
                if p_type not in ("REMINDER", "REMINDERS", "TIME", "TIMESTAMP"):
                    entity_type = p_type

            # STRICT DOMAIN GUARD: Never blindly grab stale reminder/time entities
            if not entity_type or entity_type in ("REMINDER", "REMINDERS", "TIME", "TIMESTAMP"):
                for safe_domain in ("APPLICATION", "FILE", "DOCUMENT"):
                    if self.current_state.active_entity_set.get(safe_domain):
                        entity_type = safe_domain
                        break

            if entity_type == "APPLICATION" and not self.current_state.active_entity_set.get(entity_type):
                if self.current_state.active_applications or self.current_state.session_context.get("opened_applications", []):
                    entity_type = "APPLICATION"
            
            entities = []
            if entity_type == "APPLICATION":
                app_candidates = self.current_state.active_applications or self.current_state.active_entity_set.get("APPLICATION", []) or self.current_state.session_context.get("opened_applications", [])
                seen_app_low = set()
                for e in app_candidates:
                    s_val = e.get("value") if isinstance(e, dict) else str(e)
                    sub_vals = [sv.strip() for sv in re.split(r'[,;]|\band\b', s_val) if sv.strip()]
                    for sv in sub_vals:
                        canon = sv.capitalize()
                        low = canon.lower()
                        # Reject timestamps or disallowed names
                        if low and low not in seen_app_low and low not in DISALLOWED_ENTITY_NAMES and not re.search(r'\b\d{1,2}:\d{2}\b', low):
                            seen_app_low.add(low)
                            entities.append(canon)
            elif entity_type:
                raw_entities = self.current_state.active_entity_set.get(entity_type, [])
                seen_ent_low = set()
                for e in raw_entities:
                    s_val = e.get("value") if isinstance(e, dict) else str(e)
                    clean_s = os.path.basename(s_val.strip()) if ('.' in s_val and ('/' in s_val or '\\' in s_val)) else s_val.strip()
                    low = clean_s.lower()
                    if low and low not in seen_ent_low and low not in DISALLOWED_ENTITY_NAMES and not re.search(r'\b\d{1,2}:\d{2}\b', low):
                        seen_ent_low.add(low)
                        entities.append(clean_s)

            if entities:
                # Check for an action verb in the command (e.g. "close both", "open both of them")
                m_act = re.match(r'^(?:please\s+|can\s+you\s+)?(close|quit|exit|terminate|kill|shut|open|launch|start|run|delete|remove)\b', clean_text, re.IGNORECASE)
                if m_act:
                    v = m_act.group(1).lower()
                    resolved = " and ".join([f"{v} {ent}" for ent in entities])
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (distributed plural action: '{v}')")
                    return resolved, True
                else:
                    # Guard: Document refinement commands like "add references to both" or conflict resolutions like "keep both" must NOT replace 'both' with filenames/topics
                    if re.search(r'\b(?:add\s+references|make|turn|convert|put|keep\s+both|keep\s+them|keep)\b', clean_text, re.IGNORECASE):
                        return user_input, False
                    replacement = " and ".join(entities) if len(entities) == 2 else (", ".join(entities[:-1]) + f" and {entities[-1]}" if len(entities) > 2 else entities[0])
                    clean_text = re.sub(r"\b(both of them|both|all of them|all|them|those two|those|these two|the two)\b", lambda m: replacement, clean_text, flags=re.IGNORECASE)
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{clean_text}' (plural replacement: '{replacement}')")
                    return clean_text, True
        
        # ── 00. Intra-Utterance / Same-Turn Self-Correction ──
        # Handles: "Friday open Chrome no I meant Edge", "open Chrome, no I meant Edge",
        # "open Chrome oh no not that edge open edge", "open Chrome actually not that open edge",
        # "open Chrome actually not Chrome, Edge", "open Chrome not that, Edge", "open Chrome I meant Microsoft Edge"
        m_same_turn = re.search(
            r'^(?P<initial>.+?)[,\s]+'
            r'(?:'
                r'(?:oh\s+no|no|actually|wait)[,\s]+(?:i\s+meant|not\s+(?:that|[a-zA-Z0-9_\-]+))[,\s]+'
                r'|(?:oh\s+no|no)[,\s]+i\s+meant\s+'
                r'|no\s+i\s+meant\s+'
                r'|i\s+meant\s+'
                r'|oh\s+no[,\s]+(?:not\s+that\s+)?'
                r'|actually\s+not\s+(?:that|[a-zA-Z0-9_\-]+)[,\s]+'
                r'|actually\s+not\s+that\s+'
                r'|actually\s+'
                r'|not\s+that[,\s]+'
            r')'
            r'(?P<correction>.+)$',
            clean_text,
            re.IGNORECASE
        )
        if m_same_turn:
            init_cmd = m_same_turn.group("initial").strip()
            # If initial command is merely an interjection / filler, this is a cross-turn correction, NOT intra-utterance
            interjections = {"no", "oh no", "wait", "actually", "sorry", "oh", "well", "hey", "friday", "hey friday", "not that"}
            if init_cmd.lower() not in interjections and len(init_cmd.split()) >= 2:
                corr_part = m_same_turn.group("correction").strip()
                
                # Clean residual negation from correction part (e.g. "not that edge", "not Chrome, Edge")
                corr_cleaned = re.sub(r'^(?:not\s+(?:that(?:\s+[a-zA-Z0-9_\-]+)?|[a-zA-Z0-9_\-]+)[,\s]+)+', '', corr_part, flags=re.IGNORECASE).strip()
                corr_cleaned = re.sub(r'^(?:i\s+meant\s+|open\s+instead\s+)', '', corr_cleaned, flags=re.IGNORECASE).strip()

                # If initial command contains a search clause (e.g. "Open Chrome, search for Python tutorials")
                m_search_in_init = re.search(r'\b(?:search(?:\s+(?:for|on|in|google))?|look\s+up|find)\s+(.+)$', init_cmd, re.IGNORECASE)
                if m_search_in_init:
                    clean_corr_query = re.sub(r'^(?:search\s+(?:for\s+)?|for\s+)', '', corr_cleaned, flags=re.IGNORECASE).strip().rstrip('.?!')
                    prefix_before_search = init_cmd[:m_search_in_init.start()].strip().rstrip(',;')
                    if prefix_before_search:
                        resolved = f"{prefix_before_search}, search for {clean_corr_query}"
                    else:
                        resolved = f"search google for {clean_corr_query}"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (intra-utterance search correction)")
                    return resolved, True

                # If correction contains an explicit action verb towards the end (e.g. "not that edge open edge")
                m_end_action = re.search(r'\b(open|launch|start|run|close|quit|exit|terminate|create|delete|remove|play|show)\s+([a-zA-Z0-9_\-\s]+)$', corr_part, re.IGNORECASE)
                if m_end_action:
                    resolved = f"{m_end_action.group(1)} {m_end_action.group(2).strip()}"
                else:
                    m_verb = re.match(r'^(open|launch|start|run|close|quit|exit|terminate|create|delete|remove|play|show)\b', init_cmd, re.IGNORECASE)
                    init_verb = m_verb.group(1) if m_verb else "open"

                    if corr_cleaned.lower() in ("the other app", "the other application", "the other one", "other app", "other application", "other one"):
                        opened_apps = self.current_state.active_applications or self.current_state.session_context.get("opened_applications", []) or self.current_state.active_entity_set.get("APPLICATION", [])
                        unique_apps = []
                        for a in opened_apps:
                            if a and a.capitalize() not in unique_apps and a.lower() not in ("both", "both of them", "them", "other", "the other app"):
                                unique_apps.append(a.capitalize())
                        current_app = (self.current_state.active_application or (self._last_mentioned_entity or {}).get("value", "")).capitalize()
                        other_apps = [a for a in unique_apps if a.lower() != current_app.lower()]
                        if len(other_apps) == 1:
                            resolved = f"{init_verb} {other_apps[0]}"
                            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (intra-utterance other app: '{other_apps[0]}')")
                            return resolved, True

                    if re.match(r'^(?:open|launch|start|run|close|quit|exit|terminate|create|delete|remove|play|show)\b', corr_cleaned, re.IGNORECASE):
                        resolved = corr_cleaned
                    else:
                        resolved = f"{init_verb} {corr_cleaned}".strip()

                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (intra-utterance self-correction)")
                return resolved, True

        # ── 0. Interruption / Goal Cancellation ("Stop", "Cancel that", "Abort") ──
        if re.match(r'^(?:stop|cancel(?:\s+that|\s+it)?|abort|halt|no,?\s+don\'t\s+do\s+that|don\'t\s+do\s+that)[.!]?$', lower):
            if self.current_state.goal_status in ("RUNNING", "PENDING", "WAITING_FOR_USER") or self.current_state.current_goal:
                resolved = "cancel current goal"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (interrupting active goal)")
                return resolved, True

        # ── 0b. Task Cancellation / Stop ("cancel it", "stop it", "cancel that", "abort it") ──
        if re.match(r'^(?:cancel|stop|abort)\s+(?:it|that|the\s+task|this\s+task)[.!?]?$', lower):
            last_intent = (self.current_state.last_action or {}).get("intent")
            last_entity_type = (self._last_mentioned_entity or {}).get("entity_type")
            if (last_intent == "TASK_MANAGEMENT" or last_entity_type == "TASK") and self.current_state.active_task and self.current_state.active_task.get("task_id"):
                tid = self.current_state.active_task.get("task_id")
                resolved = f"cancel task {tid}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (active task: '{tid}')")
                return resolved, True

        # ── 0b2. Environment / Application Resumption ("bring that back", "bring it back", "switch back to it") ──
        if re.match(r'^(?:bring\s+(?:that|it)\s+back|switch\s+back\s+to\s+(?:it|that)|restore\s+(?:it|that))[.!?]?$', lower):
            # If the user previously asked an environment query about what was open/active
            from core.environment import get_state_engine
            se = get_state_engine()
            prev_env = se.get_previous_state(str(self.user_id))
            hist_env = se.get_history(str(self.user_id), limit=3)
            prev_app = None
            if prev_env and not prev_env.is_empty() and prev_env.application:
                prev_app = prev_env.application
            elif hist_env:
                for tr in hist_env:
                    if tr.before_state and not tr.before_state.is_empty() and tr.before_state.application:
                        prev_app = tr.before_state.application
                        break
            if not prev_app and self.current_state.session_context.get("opened_applications"):
                opened = self.current_state.session_context.get("opened_applications")
                if opened:
                    prev_app = opened[-1]

            if prev_app and prev_app.lower() not in ("progman", "desktop", "unknown"):
                resolved = f"open {prev_app}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (environment resumption of '{prev_app}')")
                return resolved, True

        # ── 0c. Ephemeral Visual Response Requests ("Show that again", "Display that", etc.) ──
        is_repeat_visual = (
            re.search(r'^(?:please\s+)?(?:show|display|bring|put|let\s+me\s+see)\s+(?:that|it|what\s+you\s+(?:just\s+)?(?:said|told\s+me)|the\s+result|the\s+previous\s+result)(?:\s+(?:back|again))?(?:\s+on\s+(?:the\s+)?screen)?\.?$', lower)
            or re.search(r'^(?:bring\s+that\s+back|bring\s+it\s+back|display\s+what\s+you\s+(?:just\s+)?(?:said|told\s+me)|put\s+that\s+on\s+screen|let\s+me\s+see\s+that|let\s+me\s+see\s+it)\.?$', lower)
            or lower in [
                "show that again", "show it again", "display that again", "bring that back", "bring it back",
                "can you show me that again?", "can you show me that again", "show that", "show it",
                "put that on screen", "let me see that", "let me see it", "display what you just said",
                "display what you just told me", "show me what you just told me", "show me that",
                "show the result", "show me the result", "display that"
            ]
        )
        if is_repeat_visual:
            target = "again" if ("again" in lower or "back" in lower or "what you just" in lower or "previous" in lower) else ""
            resolved = f"show visual response {target}".strip()
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (ephemeral visual surface repeat)")
            return resolved, True

        m_vis_specific = re.search(r'^(?:please\s+)?(?:show|display|put)\s+(?:me\s+)?(?:the\s+)?(pairing\s+code|code|ip\s+address|ip|address|url|link|file\s+path|file|path|list|devices|table|status|result)(?:\s+again)?(?:\s+on\s+(?:the\s+)?screen)?\.?$', lower)
        if m_vis_specific:
            spec_target = m_vis_specific.group(1).lower().replace(" ", "_")
            resolved = f"show visual response {spec_target}"
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (ephemeral visual surface for '{spec_target}')")
            return resolved, True

        # ── 0d. Action Repetition ("Do it again", "Do that again", "Repeat that", "Once more", "Again", "Try that again") ──
        if re.match(r'^(?:try\s+(?:that|it)?\s+again|try\s+again|do\s+(?:it|that)\s+again|do\s+again|once\s+more|again|repeat\s+(?:that|it|the\s+last\s+action))[.!?]?$', lower):
            # Check recent failed action first if user said "try that again"
            if self.current_state.recent_failed_actions:
                last_fail = self.current_state.recent_failed_actions[-1].get("command")
                if last_fail:
                    clean_fail = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*', '', last_fail, flags=re.IGNORECASE).strip()
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{clean_fail}' (retry of last failed action)")
                    return clean_fail, True
            last_goal = self.current_state.session_context.get("last_completed_goal")
            if last_goal:
                clean_last = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*', '', last_goal, flags=re.IGNORECASE).strip()
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{clean_last}' (action repetition of last completed goal)")
                return clean_last, True
            if self.current_state.recent_actions:
                last_act = self.current_state.recent_actions[-1].get("command")
                if last_act:
                    clean_last = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*', '', last_act, flags=re.IGNORECASE).strip()
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{clean_last}' (action repetition from recent_actions)")
                    return clean_last, True
            if self.current_state.turns:
                last_turn = self.current_state.turns[-1]
                last_turn_input = last_turn.carried_forward_context.get("reference_resolved") or last_turn.user_input
                clean_last = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*', '', last_turn_input, flags=re.IGNORECASE).strip()
                if re.search(r'\b(?:it|that)\b', clean_last.lower()) and self._last_mentioned_entity:
                    entity_val = self._last_mentioned_entity.get("value")
                    if entity_val:
                        clean_last = re.sub(r'\b(?:it|that)\b', entity_val, clean_last, flags=re.IGNORECASE)
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{clean_last}' (action repetition)")
                return clean_last, True

        # ── 1. Status inquiries ("What's its status?", "What is its status?", "Check its status") ──
        if (
            re.match(r'^(?:what(?:\'s|\s+is)|\bcheck|\bget|\bshow|\bhow\s+is)\s+(?:its|the)\s+status[?.!]?$', lower)
            or lower in ["what's its status?", "what is its status?", "what's its status", "what is its status", "its status", "its status?"]
        ):
            last_intent = (self.current_state.last_action or {}).get("intent")
            last_entity_type = (self._last_mentioned_entity or {}).get("entity_type")

            # Check if device control was the most recent action or entity
            if last_intent == "DEVICE_CONTROL" or last_entity_type in ("DEVICE", "phone", "pairing_code"):
                if self.current_state.active_device:
                    dtype = self.current_state.active_device.get("device_type", "phone")
                    resolved = f"{dtype} connection status"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (active device: '{dtype}')")
                    return resolved, True

            # Check if background task was the most recent action or entity
            if last_intent == "TASK_MANAGEMENT" or last_entity_type == "TASK":
                if self.current_state.active_task and self.current_state.active_task.get("task_id"):
                    tid = self.current_state.active_task.get("task_id")
                    resolved = f"check status of task {tid}"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (active task: '{tid}')")
                    return resolved, True

            # General fallback: check active task first, then active device, then entity
            if self.current_state.active_task and self.current_state.active_task.get("task_id"):
                tid = self.current_state.active_task.get("task_id")
                resolved = f"check status of task {tid}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (active task: '{tid}')")
                return resolved, True
            elif self.current_state.active_device:
                dtype = self.current_state.active_device.get("device_type", "phone")
                resolved = f"{dtype} connection status"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (active device: '{dtype}')")
                return resolved, True
            elif self._last_mentioned_entity:
                val = self._last_mentioned_entity.get("value")
                resolved = f"{val} status"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (entity: '{val}')")
                return resolved, True

        # ── 2. State inquiries ("Is it on?", "Is it off?", "Check if it is on", "Tell me whether it is on", "Is it still running", "Did it finish?") ──
        if re.match(r'^(?:is\s+it\s+(?:on|off|active|enabled|disabled|running|still\s+running|done|finished)|did\s+it\s+(?:finish|complete|run)|check\s+if\s+it(?:\'s|\s+is)\s+(?:on|off|running|still\s+running|done|finished)|tell\s+me\s+whether\s+it\s+is\s+(?:on|off|running|still\s+running|done|finished)|whether\s+it\s+is\s+(?:on|off|running|still\s+running))[?.!]?$', lower):
            last_intent = (self.current_state.last_action or {}).get("intent")
            last_entity_type = (self._last_mentioned_entity or {}).get("entity_type")

            # Context 1: Background task in context or "running"/"finish"/"done" with active task
            if (last_intent == "TASK_MANAGEMENT" or last_entity_type == "TASK" or any(w in lower for w in ["running", "finish", "done"])) and self.current_state.active_task and self.current_state.active_task.get("task_id"):
                tid = self.current_state.active_task.get("task_id")
                resolved = f"check status of task {tid}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (active task: '{tid}')")
                return resolved, True

            # Context 2: Device connection in context
            if (last_intent == "DEVICE_CONTROL" or last_entity_type in ("DEVICE", "phone")) and ("connected" in lower or "paired" in lower):
                if self.current_state.active_device:
                    dtype = self.current_state.active_device.get("device_type", "phone")
                    resolved = f"{dtype} connection status"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (active device: '{dtype}')")
                    return resolved, True

            # Context 3: Hardware target (Caps Lock, Num Lock, etc.)
            last_action = self.current_state.last_action or {}
            target = last_action.get("target") or last_action.get("params", {}).get("key")
            if not target and self._last_mentioned_entity:
                target = self._last_mentioned_entity.get("value", "")
            target_str = str(target or "").lower()

            if "caps" in target_str or "keyboard" in target_str or (self.current_state.environmental_observations and "caps_lock" in self.current_state.environmental_observations):
                resolved = "is caps lock on" if "on" in lower else "is caps lock off"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (target: 'caps lock')")
                return resolved, True
            elif "num" in target_str:
                resolved = "is num lock on"
                return resolved, True
            elif "scroll" in target_str:
                resolved = "is scroll lock on"
                return resolved, True
            elif "bluetooth" in target_str or "bt" in target_str:
                resolved = "is bluetooth on"
                return resolved, True
            elif "wifi" in target_str or "wireless" in target_str:
                resolved = "is wifi on"
                return resolved, True
            elif self.current_state.active_application:
                app = self.current_state.active_application
                resolved = f"is {app} running"
                return resolved, True

        # ── 3. Comparative follow-ups ("What about Hyderabad?", "What about Java?") ──
        m_about = re.match(r'^(?:what|how)\s+about\s+([A-Za-z0-9_\-\s.]+?)[?.!]?$', stripped, re.IGNORECASE)
        if m_about:
            candidate = m_about.group(1).strip()
            last_intent = self.current_state.recent_intents[-1] if self.current_state.recent_intents else ""
            last_action_info = self.current_state.last_action or {}
            last_action_desc = str(last_action_info.get("target") or last_action_info.get("action") or "").lower()
            post_ctx = self.current_state.post_goal_context or {}
            post_req = str(post_ctx.get("user_request") or "").lower()
            post_target = str(post_ctx.get("target") or "").lower()

            # Check turn freshness (turn delta <= 2)
            last_turn = self.current_state.turns[-1].turn_number if self.current_state.turns else 0
            if (self.current_state.current_turn - last_turn) <= 2:
                if last_intent == "WEATHER_QUERY" or "weather" in self.current_state.entities or "location" in self.current_state.entities:
                    resolved = f"what is the weather in {candidate}"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (weather follow-up for: '{candidate}')")
                    return resolved, True
                elif (
                    self.current_state.session_context.get("active_site") == "youtube"
                    or "youtube" in (self.current_state.active_application or "").lower()
                    or "youtube" in last_action_desc
                    or "youtube" in post_req
                    or "youtube" in post_target
                ):
                    resolved = f"search youtube for {candidate}"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (youtube search follow-up for: '{candidate}')")
                    return resolved, True
                elif (
                    last_intent == "DEVICE_CONTROL"
                    or any(hw in candidate.lower() for hw in ["gpu", "cpu", "ram", "memory", "battery", "disk", "storage", "hardware"])
                ):
                    resolved = f"tell me about {candidate}"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (hardware follow-up for: '{candidate}')")
                    return resolved, True
                elif (
                    last_intent == "WEB_SEARCH"
                    or (self.current_state.session_context.get("active_browser") is not None and self.current_state.active_application)
                    or "google" in last_action_desc
                    or "google" in post_req
                ):
                    resolved = f"search google for {candidate}"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (web search follow-up for: '{candidate}')")
                    return resolved, True

        # ── 4. Active browser contextual search & result interaction ──
        active_site = self.current_state.session_context.get("active_site", "")
        active_app = self.current_state.active_application or ""
        is_browser = (
            active_site in ("youtube", "google")
            or any(b in active_app.lower() for b in ["youtube", "chrome", "browser", "google", "firefox", "edge"])
            or self.current_state.session_context.get("active_browser") is not None
        )

        # Result click/select ("Open the first result", "click the top result", "open the second result", "open the 3rd result", "open the previous result", "open the first link")
        m_res = re.search(r'\b(?:open|play|select|click)\s+(?:the\s+)?(first|top|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|previous)\s+(?:result|link)\b', lower)
        is_new_search_cmd = any(k in lower for k in ["search for", "search the web", "search google", "search on google", "search on youtube", "find "])
        if is_browser and m_res and not is_new_search_cmd:
            ord_word = m_res.group(1).lower()
            ord_map = {
                "first": 0, "1st": 0, "top": 0,
                "second": 1, "2nd": 1,
                "third": 2, "3rd": 2,
                "fourth": 3, "4th": 3,
                "fifth": 4, "5th": 4,
                "previous": -1,
            }
            target_idx = ord_map.get(ord_word, 0)
            results = self.current_state.last_search_results or []
            if results and 0 <= target_idx < len(results):
                item = results[target_idx]
                target_url = item.get("url") or item.get("link")
                if target_url:
                    resolved = f"open url {target_url}"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (browser search result resolution)")
                    return resolved, True
            elif not results:
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> 'explain_web_search_results_unavailable' (stale search results)")
                return "explain_web_search_results_unavailable", True
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> delegating to canonical open_browser_result")
            return user_input, True

        # Browser Navigation ("Go back", "Navigate back", "Back")
        if is_browser and re.match(r'^(?:go\s+back|navigate\s+back|back)[.!?]?$', lower):
            resolved = "go back"
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (browser navigation back)")
            return resolved, True

        # Search Context Restoration ("Go back to the previous search", "Go back to the TensorFlow search")
        m_back_search = re.search(r'\b(?:go\s+back\s+to\s+(?:the\s+)?(?:previous\s+search|(?:the\s+)?([a-zA-Z0-9_\-\s]+?)\s+search)|return\s+to\s+(?:the\s+)?search)\b', lower)
        if m_back_search:
            s_history = self.current_state.session_context.get("search_history", [])
            named_q = m_back_search.group(1).strip() if (m_back_search.lastindex and m_back_search.group(1)) else None
            restored = None
            if named_q:
                for entry in reversed(s_history):
                    if named_q.lower() in entry.get("query", "").lower():
                        restored = entry
                        break
            if not restored and s_history:
                restored = s_history[-1]
            if restored:
                q = restored.get("query", "")
                self.current_state.session_context["last_search_query"] = q
                self.current_state.session_context["last_browser_result_set"] = restored.get("results", [])
                self.current_state.entities["search_query"] = q
                resolved = f"search google for {q}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (restored search context: '{q}')")
                return resolved, True

        m_bsearch = is_browser and re.match(r'^(?:now\s+|then\s+|please\s+|can\s+you\s+|could\s+you\s+)?(?:search\s+(?:for\s+)?|find\s+videos?\s+(?:about|on|for)\s+)(.+)', stripped, re.IGNORECASE)
        if m_bsearch:
            search_query = m_bsearch.group(1).strip().rstrip('.?!')
            search_query = re.sub(r'^(?:(?:the\s+)?(?:web|internet)\s+(?:for\s+)?|for\s+)', '', search_query, flags=re.IGNORECASE).strip()
            if active_site == "youtube" or "youtube" in active_app.lower():
                resolved = f"search youtube for {search_query}"
            else:
                resolved = f"search google for {search_query}"
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (browser contextual search)")
            return resolved, True

        # ── 4b. User Correction to Active Context / Search ("No, search for SRM University AP instead", "Search for Guntur instead") ──
        m_corr_search = re.search(r'^(?:no[,\s]+)?(?:search\s+(?:for\s+)?|find\s+)(.+?)(?:\s+instead)?[.!?]?$', stripped, re.IGNORECASE)
        if m_corr_search and (lower.startswith("no") or "instead" in lower or is_browser):
            corr_query = m_corr_search.group(1).strip().rstrip('.?!')
            if corr_query.lower().startswith("for "):
                corr_query = corr_query[4:].strip()
            if corr_query:
                if active_site == "youtube" or "youtube" in active_app.lower():
                    resolved = f"search youtube for {corr_query}"
                else:
                    resolved = f"search google for {corr_query}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (user correction for search: '{corr_query}')")
                return resolved, True

        # ── 4c. Application Correction ("Actually, open Firefox instead", "Open Firefox instead") ──
        m_corr_app = re.search(r'^(?:actually[,\s]+|no[,\s]+)?open\s+([a-zA-Z0-9_\-\s]+?)\s+instead[.!?]?$', stripped, re.IGNORECASE)
        if m_corr_app:
            new_app = m_corr_app.group(1).strip()
            resolved = f"open {new_app}"
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (user correction to open app: '{new_app}')")
            return resolved, True

        # ── 4d. Explicit Cancellation / Abort During Interruption ──
        if lower in (
            "don't send it", "don't send", "actually, don't send it",
            "actually don't send it", "no, don't send it", "cancel that",
            "stop", "never mind", "forget it", "cancel it", "cancel",
            "stop it", "abort", "don't do that"
        ):
            resolved = "cancel current goal"
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (explicit cancellation)")
            return resolved, True

        # ── 4e. Conversational Pause / Short Utterance Hold ("Wait", "Wait...", "Hold on") ──
        if lower in (
            "wait", "wait...", "wait!", "hold on", "hang on",
            "wait a second", "wait a sec", "wait a minute", "pause", "actually..."
        ):
            resolved = "pause current goal"
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (conversational pause)")
            return resolved, True

        # ── 4f. Conversational Interruption Follow-up ("Wait, explain that more simply") ──
        m_simpler = re.search(r'^(?:wait[,\s]+)?(?:explain|tell\s+me)\s+(?:that|it)?\s*(?:more\s+simply|simply|in\s+simple\s+terms)[.!?]?$', lower)
        if m_simpler:
            resolved = "explain that more simply"
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (conversational simplification)")
            return resolved, True

        # ── 4g. Interruption Entity / Parameter Correction ──
        # Handles: "No, I meant Edge", "No, Edge", "Actually, Edge", "Actually not Chrome, Edge",
        # "No not Chrome, open Edge", "Oh no, I meant Edge", "Not that, Edge", "I meant Microsoft Edge"
        m_corr = re.match(
            r'^(?:'
                r'(?:oh\s+no|no|actually|wait)[,\s]+(?:i\s+meant|not\s+(?:that|[a-zA-Z0-9_\-]+))[,\s]+'
                r'|(?:oh\s+no|no)[,\s]+i\s+meant\s+'
                r'|no\s+i\s+meant\s+'
                r'|i\s+meant\s+'
                r'|oh\s+no[,\s]+'
                r'|actually\s+not\s+(?:that|[a-zA-Z0-9_\-]+)[,\s]+'
                r'|actually\s+'
                r'|not\s+that[,\s]+'
                r'|no[,\s]+'
                r'|change\s+it\s+to\s+'
                r'|use\s+'
            r')'
            r'(.+?)(?:\s+instead)?[.!?]?$',
            clean_text,
            re.IGNORECASE
        ) or re.search(r'^([a-zA-Z0-9_\-\s]+)\s+instead[.!?]?$', clean_text, re.IGNORECASE)

        if m_corr:
            candidate = m_corr.group(1).strip().rstrip('.?!')
            # Clean residual negation from candidate (e.g. "not Chrome, Edge" -> "Edge", "not Chrome, open Edge" -> "open Edge")
            candidate = re.sub(r'^(?:not\s+(?:that|[a-zA-Z0-9_\-]+)[,\s]+)+', '', candidate, flags=re.IGNORECASE).strip()
            if candidate.lower().startswith("i meant "):
                candidate = candidate[8:].strip()
            if candidate.lower().startswith("it to "):
                candidate = candidate[6:].strip()

            last_intent = self.current_state.recent_intents[-1] if self.current_state.recent_intents else ""
            last_turn_input = self.current_state.turns[-1].user_input.lower() if self.current_state.turns else ""
            has_weather = last_intent == "WEATHER_QUERY" or "weather" in last_turn_input or "location" in self.current_state.entities

            # Case 0: Executable instruction / correction command (Section 6, 7, 8)
            # e.g. "no I need you to open the pdf that you created about the deadlocks",
            # "No, I need you to open the PPT", "No, create the report instead"
            cand_low = candidate.lower()
            action_verbs = ("open", "create", "show", "make", "convert", "export", "save", "edit", "search", "close", "add", "update", "type", "write", "view", "read", "start", "launch", "play")
            has_action = bool(re.search(r'\b(?:' + '|'.join(action_verbs) + r')\b', cand_low))
            has_framing = any(cand_low.startswith(p) for p in ("need you to", "want you to", "can you", "could you", "please"))
            
            # Avoid matching pure format shifts like "make it pdf", "use pdf instead"
            is_pure_fmt_param = cand_low in ("pdf", "docx", "doc", "txt", "presentation", "ppt", "pptx", "excel", "spreadsheet") or cand_low in ("desktop", "downloads")
            if (has_action or has_framing or len(cand_low.split()) >= 4) and not is_pure_fmt_param:
                clean_cmd = candidate
                clean_cmd = re.sub(r'^(?:(?:i\s+)?(?:need|want)\s+you\s+to\s+|(?:can|could)\s+you\s+|(?:please\s+)?)+', '', clean_cmd, flags=re.IGNORECASE).strip()
                clean_cmd = re.sub(r'\s+instead$', '', clean_cmd, flags=re.IGNORECASE).strip()
                if clean_cmd:
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{clean_cmd}' (executable instruction preserved, not parameter correction)")
                    return clean_cmd, True

            # Case A: Weather location correction ("No, Guntur", "No, I meant Guntur", "Hyderabad instead")
            if has_weather and not any(fmt in candidate.lower() for fmt in ("pdf", "docx", "desktop", "downloads", "chrome", "firefox", "edge")):
                resolved = f"what is the weather in {candidate}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (weather location correction to '{candidate}')")
                return resolved, True

            # Case B: Document format parameter ("make it pdf", "use pdf instead", "save as pdf")
            if any(fmt in candidate.lower() for fmt in ("pdf", "docx", "doc", "txt", "markdown", "presentation")):
                target_fmt = "pdf" if "pdf" in candidate.lower() else ("docx" if "docx" in candidate.lower() else candidate)
                resolved = f"make it {target_fmt}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (document format correction to '{target_fmt}')")
                return resolved, True

            # Case C: Destination location ("on the desktop", "desktop", "downloads")
            if any(loc in candidate.lower() for loc in ("desktop", "downloads", "documents", "folder")):
                clean_loc = "Desktop" if "desktop" in candidate.lower() else ("Downloads" if "downloads" in candidate.lower() else candidate)
                resolved = f"save to {clean_loc}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (destination correction to '{clean_loc}')")
                return resolved, True

            # Case D: Application correction ("no, I meant Edge", "Edge instead", "actually Edge", "actually not Chrome, Edge")
            last_action = self.current_state.last_action or {}
            is_typing_task = bool(
                re.search(r'\b(?:type|write|enter|input|note)\b', candidate, re.IGNORECASE)
                or any(phrase in candidate.lower() for phrase in ["need you to", "want you to", "can you", "what can you do", "could you"])
                or len(candidate.split()) > 4
            )
            if is_typing_task:
                # Conversational command with negation prefix, e.g. "no I need you to type what can you do in notepad"
                clean_cmd = re.sub(r'^(?:(?:oh\s+)?no)[,\s]+', '', clean_text, flags=re.IGNORECASE).strip()
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{clean_cmd}' (conversational task preserved, not app correction)")
                return clean_cmd, True

            if (
                last_intent in ("OPEN_APPLICATION", "CLOSE_APPLICATION")
                or last_action.get("intent") in ("OPEN_APPLICATION", "CLOSE_APPLICATION")
                or (self._last_mentioned_entity and self._last_mentioned_entity.get("entity_type") == "APPLICATION")
                or bool(self.current_state.active_applications)
                or bool(self.current_state.active_application)
            ):
                if candidate.lower() in ("the other app", "the other application", "the other one", "other app", "other application", "other one"):
                    opened_apps = self.current_state.active_applications or self.current_state.session_context.get("opened_applications", []) or self.current_state.active_entity_set.get("APPLICATION", [])
                    unique_apps = [a.capitalize() for a in opened_apps if a and a.lower() not in ("both", "both of them", "them", "other", "the other app")]
                    current_app = (self.current_state.active_application or (self._last_mentioned_entity or {}).get("value", "")).capitalize()
                    other_apps = [a for a in unique_apps if a.lower() != current_app.lower()]
                    verb = "close" if "CLOSE" in str(last_intent).upper() or (last_action.get("action") in ("close", "close_app")) else "open"
                    if len(other_apps) == 1:
                        resolved = f"{verb} {other_apps[0]}"
                        print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (resolved other app correction: '{other_apps[0]}')")
                        return resolved, True
                    elif len(other_apps) > 1:
                        resolved = f"clarify_other_app {' or '.join(other_apps[:2])}"
                        return resolved, True

                clean_app = re.sub(r'^(?:open|launch|start)\s+', '', candidate, flags=re.IGNORECASE).strip()
                resolved = f"open {clean_app}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (application correction to '{clean_app}')")
                return resolved, True


        # ── 5. Disambiguation & Alternative Selection ("The second one", "Show me the other one", "The first one", "The fifth one") ──
        m_ordinal = re.search(r'\b(?:the\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|other|1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th)\s+(?:one|file|presentation|document|option)\b|^the\s+(first|second|third|fourth|fifth|other|1st|2nd|3rd|4th|5th)\s+one[?.!]?$', lower)
        if m_ordinal or re.search(r'\b(?:the\s+other\s+one|the\s+second\s+one|the\s+other\s+file)\b', lower):
            ord_map = {
                "first": 0, "1st": 0,
                "second": 1, "2nd": 1, "other": 1,
                "third": 2, "3rd": 2,
                "fourth": 3, "4th": 3,
                "fifth": 4, "5th": 4,
                "sixth": 5, "6th": 5,
                "seventh": 6, "7th": 6,
                "eighth": 7, "8th": 7,
                "ninth": 8, "9th": 8,
                "tenth": 9, "10th": 9,
            }
            ord_word = ""
            if m_ordinal:
                ord_word = (m_ordinal.group(1) or m_ordinal.group(2) or "").lower()
            idx = ord_map.get(ord_word, 1)

            # Check search freshness or pending clarification
            is_search_fresh = (
                bool(self.current_state.last_search_results)
                and (
                    self.current_state.goal_status == "WAITING_FOR_USER"
                    or (self.current_state.current_turn - getattr(self.current_state, "last_search_results_turn", 0) <= 2)
                )
            ) or bool(getattr(self.current_state, "pending_clarification", None))

            candidates = self.current_state.last_search_results
            if not candidates and getattr(self.current_state, "pending_clarification", None):
                candidates = self.current_state.pending_clarification.get("candidates", [])

            # Check active recommendation list if search candidates are absent
            if not candidates and getattr(self.current_state, "current_recommendation_list", None):
                candidates = self.current_state.current_recommendation_list
                is_search_fresh = True

            if not is_search_fresh or not candidates:
                resolved = "clarify_candidate_selection_unavailable"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (no fresh search candidates in state)")
                return resolved, True

            if idx < len(candidates):
                target_item = candidates[idx]
                if isinstance(target_item, dict):
                    fpath = target_item.get("path") or target_item.get("name")
                    resolved = f"open file {fpath}"
                else:
                    is_rec = (candidates is self.current_state.current_recommendation_list) or (
                        getattr(self.current_state, "current_recommendation_list", None) == candidates
                    )
                    if is_rec:
                        resolved = f"select recommendation {target_item}"
                    else:
                        action = (getattr(self.current_state, "pending_clarification", None) or {}).get("action", "open")
                        resolved = f"{action} {target_item}"
                self.current_state.pending_clarification = None
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (ordinal selection [{idx}]: '{resolved}')")
                return resolved, True
            else:
                total_found = len(candidates)
                resolved = f"candidate_ordinal_out_of_range {idx + 1} {total_found}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (ordinal {idx + 1} exceeds {total_found})")
                return resolved, True

        # ── 5b. Folder Reference Resolution ("open the folder", "can you open the folder", "show me the folder", "open that folder") ──
        clean_no_polite = re.sub(r'^(?:can\s+you\s+|could\s+you\s+|please\s+|will\s+you\s+)+', '', clean_text, flags=re.IGNORECASE).strip()
        m_folder_ref = re.match(r'^(?:open|view|launch|show)\s+(?:me\s+)?(?:the\s+|that\s+|this\s+)?folder[.!?]?$', clean_no_polite, re.IGNORECASE)
        if m_folder_ref:
            has_folder_entity = (
                self._last_mentioned_entity
                and self._last_mentioned_entity.get("entity_type") == "FOLDER"
                and ((self.current_state.current_turn - self._last_mentioned_entity.get("turn", 0) <= 2) or (self._last_mentioned_entity.get("turn", 0) == 0))
            )
            if has_folder_entity:
                f_name = self._last_mentioned_entity.get("value", "").strip()
                resolved = f"open folder {f_name}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (folder reference: '{f_name}')")
                return resolved, True
            else:
                resolved = "clarify_which_folder_to_open"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (no folder in context -> clarify)")
                return resolved, True

        # ── 5c. Document Save Reference Resolution ("save it as level.txt", "save it as test.txt") ──
        m_save_as = re.search(r'^(?:please\s+|can\s+you\s+)?save\s+(?:it|that|this|the\s+document|the\s+file)?\s*as\s+([a-zA-Z0-9_\-\.]+)[.!?]?$', clean_text, re.IGNORECASE)
        if m_save_as:
            fname = m_save_as.group(1).strip()
            resolved = f"save document as {fname}"
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (document save resolution: '{fname}')")
            return resolved, True

        # ── 5d. Goal / Task Contextual Folder Creation ("Create a folder for it", "make a folder for it") ──
        m_f_for_it = re.search(r'^(?:please\s+|can\s+you\s+)?(?:create|make|new)\s+(?:a\s+)?(?:folder|directory)\s+(?:for\s+(?:it|that|this)|for\s+(?:my\s+)?(.+?))[.!?]?$', clean_text, re.IGNORECASE)
        if m_f_for_it:
            specific_target = m_f_for_it.group(1).strip() if (m_f_for_it.lastindex and m_f_for_it.group(1)) else ""
            if not specific_target or specific_target.lower() in ("it", "that", "this"):
                goal_ent = (
                    self.current_state.session_context.get("active_goal_entity")
                    or (self.current_state.current_goal or {}).get("entity")
                    or (self.current_state.current_goal or {}).get("topic")
                    or (self.current_state.active_task or {}).get("entity")
                )
                specific_target = goal_ent or "AI Project Files"
            folder_clean = re.sub(r'^(?:my\s+|the\s+)', '', specific_target, flags=re.IGNORECASE).strip()
            folder_clean = " ".join(w.upper() if w.upper() in ("AI", "API", "ML", "UI", "ID", "OS") else w.capitalize() for w in folder_clean.split())
            resolved = f"create folder {folder_clean}"
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (contextual goal folder: '{folder_clean}')")
            return resolved, True

        # ── 5e. Child Artifact Inside Active Folder ("put notes.txt inside", "put a notes file inside", "create a notes file inside it") ──
        m_inside = re.search(r'^(?:please\s+|can\s+you\s+)?(?:put|create|make|add)\s+(?:a\s+)?([a-zA-Z0-9_\-\.]+(?:\.[a-zA-Z0-9]+)?)(?:\s+file)?\s+(?:inside(?:\s+(?:it|that|the\s+folder))?|in\s+(?:it|that|there)|there)[.!?]?$', clean_text, re.IGNORECASE)
        if m_inside:
            fn = m_inside.group(1).strip()
            if fn.lower() in ("notes", "note", "text", "a"):
                fn = "notes.txt"
            elif not re.search(r'\.[a-zA-Z0-9]+$', fn):
                fn = f"{fn}.txt"
            resolved = f"create file {fn} inside it"
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (child file creation in active folder: '{fn}')")
            return resolved, True
        if clean_text.lower() in ("put a notes file inside", "put a notes file inside.", "put a notes file inside it", "add a notes file inside", "create a notes file inside"):
            resolved = "create file notes.txt inside it"
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (child file creation in active folder)")
            return resolved, True

        # ── 5f1. Plural Application Close ("close both of them", "close both", "close those two") ──
        m_close_both = re.match(r'^(?:please\s+|can\s+you\s+)?(?:close|quit|exit|terminate|kill)\s+(?:both(?:\s+of\s+them)?|those\s+two|the\s+two\s+apps|them|all\s+of\s+them)[.!?]?$', clean_text, re.IGNORECASE)
        if m_close_both:
            opened_apps = self.current_state.active_applications or self.current_state.session_context.get("opened_applications", []) or self.current_state.active_entity_set.get("APPLICATION", [])
            unique_apps = []
            for a in opened_apps:
                canon = a.capitalize()
                if canon not in unique_apps and canon.lower() not in ("both", "both of them", "them", "all", "other"):
                    unique_apps.append(canon)
            if len(unique_apps) >= 2:
                resolved = f"close {unique_apps[0]} and close {unique_apps[1]}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (plural close resolution: {unique_apps[:2]})")
                return resolved, True
            elif len(unique_apps) == 1:
                resolved = f"close {unique_apps[0]}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (single open app close resolution: {unique_apps[0]})")
                return resolved, True

        # ── 5f2. Alternative Application Reference ("close the other app", "close the other one") ──
        m_other_app = re.match(r'^(?:please\s+|can\s+you\s+)?(close|quit|exit|open|launch|start)\s+(?:the\s+)?other\s+(?:app|application|one)[.!?]?$', clean_text, re.IGNORECASE)
        if m_other_app:
            verb = m_other_app.group(1).lower()
            opened_apps = self.current_state.active_applications or self.current_state.session_context.get("opened_applications", []) or self.current_state.active_entity_set.get("APPLICATION", [])
            seen_app_low = set()
            unique_apps = []
            for a in opened_apps:
                s_val = a.get("value", a) if isinstance(a, dict) else str(a)
                sub_vals = [sv.strip() for sv in re.split(r'[,;]|\band\b', s_val) if sv.strip()]
                for sv in sub_vals:
                    canon = sv.capitalize()
                    low = canon.lower()
                    if low and low not in seen_app_low and low not in DISALLOWED_ENTITY_NAMES and low not in ("both", "both of them", "them", "other", "the other app"):
                        seen_app_low.add(low)
                        unique_apps.append(canon)
            current_app = (self.current_state.active_application or (self._last_mentioned_entity or {}).get("value", "")).capitalize()
            other_apps = [a for a in unique_apps if a.lower() != current_app.lower()]
            if len(other_apps) == 1:
                resolved = f"{verb} {other_apps[0]}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (resolved other app: '{other_apps[0]}')")
                return resolved, True
            elif len(other_apps) > 1:
                resolved = f"clarify_other_app {' or '.join(other_apps[:2])}"
                return resolved, True

        # ── 5f3. Singular Contextual Application Close ("close it", "close this", "close that", "shut it", "quit it") ──
        m_close_it = re.match(r'^(?:please\s+|can\s+you\s+)?(close|quit|exit|terminate|kill|shut)\s+(?:it|this|that)[.!?]?$', clean_text, re.IGNORECASE)
        if m_close_it:
            verb = m_close_it.group(1).lower()
            # Tier 1: Active application of compatible type
            if self.current_state.active_application and self.current_state.active_application.lower() not in DISALLOWED_ENTITY_NAMES:
                target = self.current_state.active_application.capitalize()
                resolved = f"{verb} {target}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (active application prioritized: '{target}')")
                return resolved, True
            # Tier 2: Compatible primary active entity or last mentioned entity
            last_ent = self.current_state.primary_active_entity or self._last_mentioned_entity
            if last_ent and last_ent.get("entity_type") == "APPLICATION":
                val = last_ent.get("value", "")
                clean_val = val.strip('.,?! ')
                if clean_val and clean_val.lower() not in DISALLOWED_ENTITY_NAMES:
                    target = clean_val.capitalize()
                    resolved = f"{verb} {target}"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (compatible entity: '{target}')")
                    return resolved, True
            # Tier 3: If exactly one active application exists in active_applications / session_context / active_entity_set
            active_apps_source = self.current_state.active_applications or self.current_state.session_context.get("opened_applications", []) or self.current_state.active_entity_set.get("APPLICATION", [])
            seen_app_low = set()
            active_apps = []
            for a in active_apps_source:
                s_val = a.get("value", a) if isinstance(a, dict) else str(a)
                sub_vals = [sv.strip() for sv in re.split(r'[,;]|\band\b', s_val) if sv.strip()]
                for sv in sub_vals:
                    canon = sv.capitalize()
                    low = canon.lower()
                    if low and low not in seen_app_low and low not in DISALLOWED_ENTITY_NAMES and low not in ("both", "both of them", "them", "other", "the other app"):
                        seen_app_low.add(low)
                        active_apps.append(canon)
            if len(active_apps) == 1:
                resolved = f"{verb} {active_apps[0]}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (single active app: '{active_apps[0]}')")
                return resolved, True
            # Tier 4: Ambiguity clarification only if multiple apps exist and none is focused
            elif len(active_apps) >= 2:
                resolved = f"clarify_close_app {' or '.join(active_apps[:2])}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (ambiguous apps to close: {active_apps[:2]})")
                return resolved, True

        # ── 5g. Ambiguous File Open ("open the report", "open report") ──
        m_open_ambig = re.match(r'^(?:please\s+|can\s+you\s+)?open\s+(?:the\s+|that\s+)?report[.!?]?$', clean_text, re.IGNORECASE)
        if m_open_ambig:
            try:
                from modules.system_controller.folder_manager import get_desktop_path
                desktop = get_desktop_path()
                matching = []
                for f in sorted(os.listdir(desktop)):
                    if "report" in f.lower() and f.lower().endswith(('.txt', '.docx', '.pdf')):
                        matching.append(f)
                if len(matching) >= 2:
                    # Save candidates in state so ordinal selection ("the second one") resolves in next turn
                    self.current_state.last_search_results = matching[:2]
                    self.current_state.last_search_results_turn = self.current_state.current_turn
                    self.current_state.pending_clarification = {
                        "type": "disambiguate_files",
                        "candidates": matching[:2],
                        "action": "open file"
                    }
                    self.current_state.goal_status = "WAITING_FOR_USER"
                    resolved = f"clarify_ambiguous_file {' or '.join(matching[:2])}"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (ambiguous files: {matching[:2]})")
                    return resolved, True
            except Exception:
                pass

        # ── 6. Pronominal commands with last_mentioned_entity ("close it", "delete that file", "open it") ──
        if not self._last_mentioned_entity:
            # Check if an active document / artifact is available to serve as the referent
            art = self.current_state.active_artifact
            if not art and getattr(self.current_state, "active_documents", None):
                art = self.current_state.active_documents[0]
            if art and isinstance(art, dict):
                p = art.get("filepath") or art.get("path")
                fn = art.get("filename") or (os.path.basename(p) if p else "")
                if fn:
                    self._last_mentioned_entity = {
                        "value": fn,
                        "name": fn,
                        "path": p,
                        "intent": "DOCUMENT_GENERATION",
                        "entity_type": "FILE",
                        "turn": self.current_state.current_turn,
                        "timestamp": datetime.now().isoformat()
                    }
            if not self._last_mentioned_entity:
                return user_input, False

        # Fast exit only if the input has no pronouns or referential phrases
        tokens = lower.split()
        has_ref = bool(re.search(r'\b(?:it|that|them|this|those|the\s+file|that\s+file|this\s+file|the\s+folder|that\s+folder|inside\s+it|in\s+it|inside\s+that)\b', lower))
        if len(tokens) >= 5 and not has_ref:
            return user_input, False

        # Check entity freshness (turn delta <= 2)
        entity_turn = self._last_mentioned_entity.get("turn", 0)
        is_entity_fresh = (self.current_state.current_turn - entity_turn <= 2) or (entity_turn == 0)

        # Check for pronoun patterns
        for pat in self._PRONOUN_PATTERNS:
            m = re.match(pat, lower, re.IGNORECASE)
            if m:
                entity_value = self._last_mentioned_entity.get("value", "")
                entity_type = self._last_mentioned_entity.get("entity_type", "")
                intent = self._last_mentioned_entity.get("intent", "")

                if not entity_value:
                    return user_input, False

                clean_entity = entity_value.strip().rstrip('.?!')
                clean_stripped = stripped.rstrip('.?!')

                # Special handling for typing / writing references:
                # E.g. "type that sentences into notepad" or "type that into notepad"
                m_type_into = re.match(
                    r'^(?:please\s+|can\s+you\s+|could\s+you\s+)?(?:type|write)\s+(?:(?:that|those|the)\s+(?:sentences?|text|words?|phrase|message|content)|that|it|them|those)\s+(?:into|in|on)\s+([a-zA-Z0-9_\-\s]+)$',
                    clean_stripped,
                    re.IGNORECASE
                )
                if m_type_into:
                    target_app = m_type_into.group(1).strip()
                    resolved = f"open {target_app} and type {clean_entity}"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (typing reference resolution to app)")
                    return resolved, True

                m_type_plain = re.match(
                    r'^(?:please\s+|can\s+you\s+|could\s+you\s+)?(?:type|write)\s+(?:(?:that|those|the)\s+(?:sentences?|text|words?|phrase|message|content)|that|it|them|those)$',
                    clean_stripped,
                    re.IGNORECASE
                )
                if m_type_plain:
                    resolved = f"type {clean_entity}"
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (typing reference resolution)")
                    return resolved, True

                # Check for "that file" / "this file" / "the file" / "that presentation" / "that sentence"
                m_target_phrase = re.search(
                    r'\b(?:that|this|the|those)\s+(?:file|document|presentation|folder|app|task|sentences?|text|words?|phrase|message|content)\b',
                    clean_stripped,
                    re.IGNORECASE
                )
                if m_target_phrase:
                    if not is_entity_fresh:
                        if clean_stripped.lower().startswith("delete") or clean_stripped.lower().startswith("remove"):
                            return "clarify_which_file_to_delete", True
                        elif clean_stripped.lower().startswith("open"):
                            return "clarify_candidate_selection_unavailable", True
                        return user_input, False

                    start, end = m_target_phrase.start(), m_target_phrase.end()
                    prefix_word = "file " if entity_type == "FILE" and not clean_stripped.lower().startswith("delete") else ("folder " if entity_type == "FOLDER" and not clean_stripped.lower().startswith(("delete", "remove")) else "")
                    resolved = clean_stripped[:start] + f"{prefix_word}{clean_entity}" + clean_stripped[end:]
                    resolved = re.sub(r'\s+', ' ', resolved).strip()
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (entity: '{clean_entity}' from {intent})")
                    return resolved, True

                pronoun_match = re.search(
                    r'\b(it|that|them|this|those)\b', clean_stripped, re.IGNORECASE
                )
                if pronoun_match:
                    # Guard 1: Never mutate user input when entity is an APPLICATION unless the verb is an application control verb!
                    if entity_type == "APPLICATION":
                        is_app_verb = bool(re.match(r'^(?:please\s+|can\s+you\s+|could\s+you\s+)?(?:open|close|quit|exit|launch|start|run|kill|terminate|switch\s+to|focus|bring\s+up)\b', clean_stripped, re.IGNORECASE))
                        if not is_app_verb:
                            return user_input, False

                    # Guard 2: Relative clauses: "that you found", "that I said", "that was made", etc.
                    # 'that' is a relative pronoun or conjunction here, NEVER an anaphoric referent!
                    if re.search(r'\bthat\s+(?:you|i|we|he|she|they|it|is|was|are|were|has|have|had|can|could|would|should)\b', clean_stripped, re.IGNORECASE):
                        return user_input, False

                    # Guard 3: Noun-phrase references like "the information that...", "the data that...", "the thing that..."
                    if re.search(r'\b(?:information|data|details|notes?|files?|documents?|results?|points?|code)\s+that\b', clean_stripped, re.IGNORECASE):
                        return user_input, False

                    # Guard: Document refinement commands like "make it 10 slides", "make it shorter", "turn it into..."
                    # must NOT have 'it' replaced by 'file <filename>' because that turns them into file creation commands!
                    if re.search(r'\b(?:make|turn|convert|put)\s+(?:it|this|that)\s+(?:\d+[\s\-]slides?|shorter|more\s+detailed)\b', clean_stripped, re.IGNORECASE):
                        return user_input, False

                    # Guard: Memory store phrases like "remember that...", "note that..." use "that" as a conjunction, not a file pronoun
                    if re.search(r'^\s*(?:remember|note|store|save|record|keep in mind)\s+that\b', clean_stripped, re.IGNORECASE):
                        return user_input, False

                    if not is_entity_fresh:
                        if clean_stripped.lower().startswith("delete") or clean_stripped.lower().startswith("remove"):
                            return "clarify_which_file_to_delete", True
                        return user_input, False

                    # If the command already mentions this entity by name, do not duplicate
                    if clean_entity.lower() in clean_stripped.lower().split():
                        return user_input, False

                    start, end = pronoun_match.start(), pronoun_match.end()
                    no_prefix = any(clean_stripped.lower().startswith(v) for v in ("rename", "move", "copy", "delete", "remove", "open file", "open folder"))
                    prefix_word = "" if no_prefix else ("file " if entity_type == "FILE" else ("folder " if entity_type == "FOLDER" else ""))
                    resolved = clean_stripped[:start] + f"{prefix_word}{clean_entity}".strip() + clean_stripped[end:]
                    resolved = re.sub(r'\s+', ' ', resolved).strip()
                    print(
                        f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' "
                        f"(entity: '{clean_entity}' from {intent})"
                    )
                    return resolved, True

                # If neither a referential target phrase nor a pronoun was matched, do NOT concatenate the entity
                return user_input, False

        return user_input, False


    def _record_recent_action(self, *args, **kwargs) -> None:
        current_t = self.current_state.current_turn
        iso_now = datetime.now().isoformat()
        if len(args) == 1 and isinstance(args[0], dict):
            execution_result = args[0]
            intents = kwargs.get("intents", ["FILE_OPERATIONS"])
            action_name = execution_result.get("action", "")
            status = execution_result.get("status", "success")
        elif len(args) >= 4 and isinstance(args[0], dict):
            execution_result = args[0]
            intents = args[1]
            iso_now = args[2]
            current_t = args[3]
            action_name = execution_result.get("action") or (intents[0] if intents else "")
            status = execution_result.get("status", "success")
        else:
            action_name = args[0] if args else kwargs.get("action", "")
            ent_type = args[1] if len(args) > 1 else kwargs.get("entity_type", "TARGET")
            ent_val = args[2] if len(args) > 2 else kwargs.get("entity_val")
            status = "success" if (args[3] if len(args) > 3 else kwargs.get("success", True)) else "error"
            path = args[4] if len(args) > 4 else kwargs.get("path")
            execution_result = {"action": action_name, "status": status, "entity_type": ent_type, "value": ent_val, "path": path}
            intents = [action_name]
            if ent_val and str(ent_val).lower() not in DISALLOWED_ENTITY_NAMES:
                if ent_type not in self.current_state.active_entity_set:
                    self.current_state.active_entity_set[ent_type] = []
                if ent_val not in self.current_state.active_entity_set[ent_type]:
                    self.current_state.active_entity_set[ent_type].append(ent_val)

        if self._last_mentioned_entity:
            self.current_state.last_mentioned_entity = self._last_mentioned_entity
            self.current_state.active_entity = self._last_mentioned_entity
            self.current_state.primary_active_entity = self._last_mentioned_entity
            ent_type = self._last_mentioned_entity.get("entity_type", "TARGET")
            ent_val = self._last_mentioned_entity.get("value")
            if ent_val and str(ent_val).lower() not in DISALLOWED_ENTITY_NAMES:
                if ent_type not in self.current_state.active_entity_set:
                    self.current_state.active_entity_set[ent_type] = []
                if ent_val not in self.current_state.active_entity_set[ent_type]:
                    self.current_state.active_entity_set[ent_type].append(ent_val)

        action_rec = {
            "action": action_name,
            "intents": intents,
            "status": status,
            "timestamp": iso_now,
            "turn": current_t
        }
        self.current_state.recent_actions.append(action_rec)
        if status == "success":
            self.current_state.recent_successful_actions.append(action_rec)
        elif status == "error":
            self.current_state.recent_failed_actions.append(action_rec)

    def _update_last_mentioned_entity(
        self, execution_result: Dict[str, Any], intents: List[str]
    ) -> None:
        """
        After a turn executes, record the most salient entity so that
        the next turn can resolve pronouns against it.
        """
        if not intents:
            return

        primary_intent = intents[0] if intents else ""
        current_t = self.current_state.current_turn
        iso_now = datetime.now().isoformat()

        # Structured action/entity types from actual execution result
        action_name = execution_result.get("action", "")
        entity_type_res = execution_result.get("entity_type", "")

        # 1. Folder creation / operations take priority when a folder was produced
        if action_name == "create_folder" or entity_type_res == "FOLDER" or execution_result.get("folder"):
            fld = execution_result.get("folder") or execution_result.get("target") or execution_result.get("name")
            fpath = execution_result.get("path") or execution_result.get("filepath")
            self._last_mentioned_entity = {
                "value": fld,
                "name": fld,
                "path": fpath,
                "intent": "FILE_OPERATIONS",
                "entity_type": "FOLDER",
                "turn": current_t,
                "timestamp": iso_now,
            }
            if fpath:
                self.current_state.session_context["last_created_folder"] = fpath
                self.current_state.entities["folder_path"] = fpath
            print(f"[REFERENCE_TRACKING] Stored folder entity: '{fld}' at '{fpath}' (FOLDER)")
            return

        # 2. File creation / operations take priority when a file was produced
        if action_name in ("create_file", "rename_file", "write_file", "open_file") or entity_type_res == "FILE" or execution_result.get("file") or execution_result.get("filepath"):
            fname = execution_result.get("file") or execution_result.get("target") or os.path.basename(execution_result.get("filepath", ""))
            fpath = execution_result.get("filepath") or execution_result.get("path")
            self._last_mentioned_entity = {
                "value": fname,
                "name": fname,
                "path": fpath,
                "intent": primary_intent or "FILE_OPERATIONS",
                "entity_type": "FILE",
                "turn": current_t,
                "timestamp": iso_now,
            }
            if fpath:
                self.current_state.session_context["last_created_file"] = fpath
                self.current_state.entities["file_path"] = fpath
            print(f"[REFERENCE_TRACKING] Stored file entity: '{fname}' at '{fpath}' (FILE)")
            return

        # Check if execution result produced a generated artifact / file
        fpath = execution_result.get("filepath") or execution_result.get("file_path")
        if fpath and (primary_intent in ("DOCUMENT_GENERATION", "FILE_OPERATIONS") or os.path.exists(fpath)):
            self._last_mentioned_entity = {
                "value": fpath,
                "intent": primary_intent or "DOCUMENT_GENERATION",
                "entity_type": "FILE",
                "turn": current_t,
                "timestamp": iso_now,
            }
            print(f"[REFERENCE_TRACKING] Stored artifact entity: '{fpath}' (FILE) from {primary_intent}")
            return

        # Fallback: check if raw input contains a specific filename (only if no structured folder/file was output)
        raw_input_text = self.current_state.turns[-1].user_input if self.current_state.turns else ""
        m_file_target = re.search(r'\b([\w\-.]+\.(?:txt|pdf|docx|xlsx|pptx|py|json|md|csv|png|jpg))\b', raw_input_text, re.IGNORECASE)
        if m_file_target and primary_intent in ("DOCUMENT_GENERATION", "FILE_OPERATIONS"):
            fname = m_file_target.group(1).strip()
            self._last_mentioned_entity = {
                "value": fname,
                "name": fname,
                "intent": "FILE_OPERATIONS",
                "entity_type": "FILE",
                "turn": current_t,
                "timestamp": iso_now,
            }
            print(f"[REFERENCE_TRACKING] Stored file entity from input: '{fname}' (FILE)")
            return

        # Structured action/entity types
        action_name = execution_result.get("action", "")
        entity_type_res = execution_result.get("entity_type", "")

        if action_name == "open_browser_result" or entity_type_res == "BROWSER_RESULT":
            res_val = execution_result.get("url") or execution_result.get("title") or "browser result"
            self._last_mentioned_entity = {
                "value": res_val,
                "url": execution_result.get("url"),
                "title": execution_result.get("title"),
                "intent": "OPEN_APPLICATION",
                "entity_type": "BROWSER_RESULT",
                "turn": current_t,
                "timestamp": iso_now,
            }
            print(f"[REFERENCE_TRACKING] Stored browser result entity: '{res_val}' (BROWSER_RESULT)")
            return

        if action_name in ("save_document", "save_as") or entity_type_res == "DOCUMENT":
            f_val = execution_result.get("target") or execution_result.get("name") or "document"
            f_path = execution_result.get("path") or execution_result.get("filepath")
            self._last_mentioned_entity = {
                "value": f_val,
                "name": f_val,
                "path": f_path,
                "intent": "FILE_OPERATIONS",
                "entity_type": "FILE",
                "turn": current_t,
                "timestamp": iso_now,
            }
            self.current_state.session_context["active_document"] = {
                "filename": f_val,
                "path": f_path,
                "status": "SAVED",
                "type": "DOCUMENT"
            }
            print(f"[REFERENCE_TRACKING] Stored saved document entity: '{f_val}' (FILE)")
            return

        if action_name == "search_web" or entity_type_res == "SEARCH_QUERY":
            q_val = execution_result.get("query", "")
            self._last_mentioned_entity = {
                "value": q_val,
                "query": q_val,
                "intent": "OPEN_APPLICATION",
                "entity_type": "SEARCH_QUERY",
                "turn": current_t,
                "timestamp": iso_now,
            }
            self.current_state.entities["search_query"] = q_val
            self.current_state.session_context["last_search_query"] = q_val
            # Record in search history for context restoration
            if "search_history" not in self.current_state.session_context:
                self.current_state.session_context["search_history"] = []
            self.current_state.session_context["search_history"].append({
                "query": q_val,
                "browser": self.current_state.session_context.get("active_browser") or "Chrome",
                "results": list(self.current_state.session_context.get("last_browser_result_set", [])),
                "timestamp": iso_now
            })
            print(f"[REFERENCE_TRACKING] Stored search query entity: '{q_val}' (SEARCH_QUERY)")
            return

        if action_name == "navigate_back" or execution_result.get("action") == "navigate_back":
            # Navigation back within browser - preserve existing search query and result set
            print("[REFERENCE_TRACKING] Preserving browser context on navigate_back")
            return

        if action_name == "type_text" or entity_type_res == "TEXT":
            t_val = execution_result.get("text", "")
            active_app = self.current_state.active_application or "Notepad"
            self.current_state.entities["typed_text"] = t_val
            self.current_state.session_context["active_document"] = {
                "app": active_app,
                "content": t_val,
                "status": "UNSAVED",
                "type": "DOCUMENT"
            }
            # Entity role: DOCUMENT (the active editing buffer), with text content recorded
            self._last_mentioned_entity = {
                "value": "current document",
                "name": "current document",
                "intent": "DEVICE_CONTROL",
                "entity_type": "DOCUMENT",
                "content": t_val,
                "app": active_app,
                "turn": current_t,
                "timestamp": iso_now,
            }
            print(f"[REFERENCE_TRACKING] Stored document buffer entity from typing in {active_app} (DOCUMENT)")
            return

        if action_name == "calculate" or entity_type_res == "CALCULATION":
            calc_val = str(execution_result.get("result", ""))
            self._last_mentioned_entity = {
                "value": calc_val,
                "expression": execution_result.get("expression"),
                "intent": "CALCULATOR",
                "entity_type": "CALCULATION",
                "turn": current_t,
                "timestamp": iso_now,
            }
            return

        # Update by intent type
        if primary_intent == "TASK_MANAGEMENT":
            if execution_result.get("task_id"):
                self._last_mentioned_entity = {
                    "value": f"task {execution_result['task_id']}",
                    "intent": "TASK_MANAGEMENT",
                    "entity_type": "TASK",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                return

        if primary_intent == "DEVICE_CONTROL":
            raw_input_low = str(self.current_state.turns[-1].user_input if self.current_state.turns else "").lower()
            action_name = execution_result.get("action", "")

            # Check for brightness setting
            if action_name in ("set_brightness", "adjust_brightness", "increase_brightness", "decrease_brightness", "get_brightness") or "brightness" in raw_input_low:
                self._last_mentioned_entity = {
                    "value": "brightness",
                    "intent": "DEVICE_CONTROL",
                    "entity_type": "DEVICE_SETTING",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                return
            # Check for volume setting
            elif action_name in ("set_volume", "volume_up", "volume_down", "increase_volume", "decrease_volume", "get_volume", "mute", "unmute") or "volume" in raw_input_low:
                self._last_mentioned_entity = {
                    "value": "volume",
                    "intent": "DEVICE_CONTROL",
                    "entity_type": "DEVICE_SETTING",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                return
            # Check for keyboard lock keys ONLY when actually referenced or set
            elif (
                execution_result.get("key") in ("Caps Lock", "Num Lock", "Scroll Lock")
                or action_name in ("set_key", "keyboard_state")
                or any(k in raw_input_low for k in ["caps lock", "num lock", "scroll lock"])
            ):
                key_name = execution_result.get("key") or ("Caps Lock" if "caps" in raw_input_low else ("Num Lock" if "num" in raw_input_low else "Scroll Lock"))
                self._last_mentioned_entity = {
                    "value": key_name,
                    "intent": "DEVICE_CONTROL",
                    "entity_type": "LOCK_KEY",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                return
            # Check for mobile device pairing
            elif action_name == "remote_device" or execution_result.get("code") or "phone" in raw_input_low or "mobile" in raw_input_low:
                self._last_mentioned_entity = {
                    "value": "phone",
                    "intent": "DEVICE_CONTROL",
                    "entity_type": "DEVICE",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                return
            # Check for hardware telemetry
            elif action_name in ("cpu_metrics", "detailed_cpu") or "cpu" in raw_input_low:
                self._last_mentioned_entity = {
                    "value": "CPU",
                    "intent": "DEVICE_CONTROL",
                    "entity_type": "HARDWARE",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                return
            elif action_name in ("gpu_telemetry", "detailed_gpu", "gpu_memory") or "gpu" in raw_input_low:
                self._last_mentioned_entity = {
                    "value": "GPU",
                    "intent": "DEVICE_CONTROL",
                    "entity_type": "HARDWARE",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                return
            elif action_name in ("ram_metrics", "detailed_ram") or "ram" in raw_input_low:
                self._last_mentioned_entity = {
                    "value": "RAM",
                    "intent": "DEVICE_CONTROL",
                    "entity_type": "HARDWARE",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                return

        if primary_intent in ("OPEN_APPLICATION", "CLOSE_APPLICATION"):
            raw_input_text = self.current_state.turns[-1].user_input if self.current_state.turns else ""
            m_comp = re.search(r'\b(?:open|launch|start)\s+([a-zA-Z0-9_\-\.]+)\s+and\s+(?:search(?:\s+google)?(?:\s+(?:for|on|in))?|look\s+up|find)\s+(.+?)[.!?]?$', raw_input_text, re.IGNORECASE)
            if m_comp:
                app_raw = m_comp.group(1).strip()
                query_raw = m_comp.group(2).strip().rstrip('.?!')
                app_canonical = "Microsoft Edge" if app_raw.lower() in ("edge", "msedge") else ("Chrome" if app_raw.lower() == "chrome" else app_raw.capitalize())
                self.current_state.entities["application"] = app_canonical
                self.current_state.entities["search_query"] = query_raw
                self._last_mentioned_entity = {
                    "value": app_canonical,
                    "name": app_canonical,
                    "intent": "OPEN_APPLICATION",
                    "entity_type": "APPLICATION",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                print(f"[REFERENCE_TRACKING] Split compound command: App='{app_canonical}' (APPLICATION), Query='{query_raw}' (SEARCH_QUERY)")
                return

            target_app = execution_result.get("app_name") or execution_result.get("target")
            if (
                target_app
                and str(target_app).lower() not in ("none", "", "it", "that", "them", "this", "browser", "browser back", "back", "browser_result")
                and execution_result.get("action") not in ("navigate_back", "open_browser_result", "search_web")
                and execution_result.get("entity_type") != "BROWSER_RESULT"
            ):
                clean_app = str(target_app).strip()
                # Terminate application names at action boundaries
                clean_app = re.split(r'\s+(?:and|then|after\s+that|next)\s+(?:type|write|search|calculate|open|run)\b', clean_app, flags=re.IGNORECASE)[0].strip()
                clean_app = re.sub(r'\s+(?:and|then)$', '', clean_app, flags=re.IGNORECASE).strip()

                # Normalize instance modifier words so "another", "new", "fresh", etc. are never part of app name
                m_inst_ent = re.match(
                    r'^(?:(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+(?:instance|window)\s+of\s+|'
                    r'(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+)',
                    clean_app,
                    re.IGNORECASE
                )
                if m_inst_ent:
                    clean_app = clean_app[m_inst_ent.end():].strip()
                clean_app = re.sub(r'^(?:the|a|an)\s+', '', clean_app, flags=re.IGNORECASE).strip()

                if clean_app.lower() in ("another", "new", "fresh", "different", "second", "instance", "window"):
                    clean_app = ""

                # Guard against storing result or link as application
                if clean_app and not re.search(r'\b(?:(?:first|second|third|fourth|fifth|\d+(?:st|nd|rd|th)|top|previous)\s+)?(?:result|link)\b', clean_app, re.IGNORECASE):
                    action_name = execution_result.get("action", "")
                    is_close_action = (
                        action_name in ("close", "close_app", "terminate_process", "close_all_opened")
                        or primary_intent == "CLOSE_APPLICATION"
                        or "closed" in str(execution_result.get("response", "")).lower()
                    )

                    if is_close_action:
                        # Invalidate active application in state
                        sub_targets = [st.strip() for st in re.split(r'[,;]|\band\b', clean_app) if st.strip()]
                        for st in sub_targets:
                            st_low = st.lower()
                            if self.current_state.active_application and st_low in self.current_state.active_application.lower():
                                self.current_state.active_application = None
                            if self.current_state.entities.get("application") and st_low in self.current_state.entities["application"].lower():
                                del self.current_state.entities["application"]
                            opened = self.current_state.session_context.get("opened_applications", [])
                            self.current_state.session_context["opened_applications"] = [
                                a for a in opened if st_low not in a.lower() and a.lower() not in st_low
                            ]
                            self.current_state.active_applications = [
                                a for a in self.current_state.active_applications if st_low not in a.lower() and a.lower() not in st_low
                            ]
                            if "APPLICATION" in self.current_state.active_entity_set:
                                self.current_state.active_entity_set["APPLICATION"] = [
                                    a for a in self.current_state.active_entity_set["APPLICATION"] if st_low not in str(a).lower()
                                ]

                        if not self.current_state.active_application and self.current_state.active_applications:
                            self.current_state.active_application = self.current_state.active_applications[-1]
                        elif not self.current_state.active_applications:
                            self.current_state.active_application = None

                        for st in sub_targets:
                            if st.lower() not in DISALLOWED_ENTITY_NAMES:
                                self._last_mentioned_entity = {
                                    "value": st.capitalize(),
                                    "name": st.capitalize(),
                                    "intent": "CLOSE_APPLICATION",
                                    "action": "CLOSE_APPLICATION",
                                    "entity_type": "APPLICATION",
                                    "status": "CLOSED",
                                    "turn": current_t,
                                    "timestamp": iso_now,
                                }
                                print(f"[REFERENCE_TRACKING] Stored closed entity: '{st.capitalize()}' (APPLICATION) from CLOSE_APPLICATION")
                        self._record_recent_action(execution_result, intents, iso_now, current_t)
                        return

                    m_comp_tgt = re.search(r'^(.*?)\s+and\s+(?:search(?:\s+google)?(?:\s+(?:for|on|in))?|look\s+up|find)\s+(.+)$', clean_app, re.IGNORECASE)
                    if m_comp_tgt:
                        app_raw = m_comp_tgt.group(1).strip()
                        query_raw = m_comp_tgt.group(2).strip().rstrip('.?!')
                        clean_app = "Microsoft Edge" if app_raw.lower() in ("edge", "msedge") else ("Chrome" if app_raw.lower() == "chrome" else app_raw.capitalize())
                        self.current_state.entities["search_query"] = query_raw
                        self.current_state.entities["application"] = clean_app

                    # Check if clean_app is a compound phrase containing multiple applications (e.g. "Calculator and Notepad", "calculator open notepad")
                    raw_sub_apps = [sa.strip().capitalize() for sa in re.split(r'[,;]|\band\b|\bopen\b|\blaunch\b|\bstart\b', clean_app, flags=re.IGNORECASE) if sa.strip()]
                    clean_sub_apps = [sa for sa in raw_sub_apps if sa.lower() not in DISALLOWED_ENTITY_NAMES and len(sa) > 1]
                    
                    if len(clean_sub_apps) > 1:
                        if "APPLICATION" not in self.current_state.active_entity_set:
                            self.current_state.active_entity_set["APPLICATION"] = []
                        for sa in clean_sub_apps:
                            if sa not in self.current_state.active_applications:
                                self.current_state.active_applications.append(sa)
                            if sa not in self.current_state.active_entity_set["APPLICATION"]:
                                self.current_state.active_entity_set["APPLICATION"].append(sa)
                        clean_app = clean_sub_apps[-1]

                    inst_mode = execution_result.get("instance_mode", "NORMAL")
                    if clean_app.lower() not in DISALLOWED_ENTITY_NAMES:
                        self.current_state.active_application = clean_app
                        if clean_app not in self.current_state.active_applications:
                            self.current_state.active_applications.append(clean_app)
                        if "APPLICATION" not in self.current_state.active_entity_set:
                            self.current_state.active_entity_set["APPLICATION"] = []
                        if clean_app not in self.current_state.active_entity_set["APPLICATION"]:
                            self.current_state.active_entity_set["APPLICATION"].append(clean_app)

                        try:
                            from core.proactive_intelligence import proactive_intelligence
                            proactive_intelligence.record_workflow_action("OPEN_APPLICATION", clean_app, user_id=str(self.user_id))
                        except Exception:
                            pass

                        self._last_mentioned_entity = {
                            "value": clean_app,
                            "name": clean_app,
                            "intent": "OPEN_APPLICATION",
                            "action": "OPEN_APPLICATION",
                            "entity_type": "APPLICATION",
                            "status": "OPEN",
                            "instance_mode": inst_mode,
                            "turn": current_t,
                            "timestamp": iso_now,
                        }
                        print(f"[REFERENCE_TRACKING] Stored entity: '{clean_app}' (APPLICATION, instance_mode={inst_mode}) from OPEN_APPLICATION")
                        self._record_recent_action(execution_result, intents, iso_now, current_t)
                        return

        if self.current_state.turns:
            last_turn = self.current_state.turns[-1]
            raw_input = last_turn.user_input

            entity_value = None
            entity_type = "TARGET"
            f_path = None

            if primary_intent in ("OPEN_APPLICATION", "CLOSE_APPLICATION"):
                clean_raw_app_input = re.sub(
                    r'\b(?:open|launch|start|run)\s+(?:(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+(?:instance|window)\s+of\s+|(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+)',
                    'open ',
                    raw_input,
                    flags=re.IGNORECASE
                )
                m = re.search(
                    r'\b(?:open|launch|start|run|close|quit|exit|terminate|kill|bring up|'
                    r'get\s+\w+\s+running|I\s+(?:want|need)\s+(?:to\s+use\s+)?)\s+([A-Za-z0-9_\-\.]+)',
                    clean_raw_app_input, re.IGNORECASE
                )
                if m:
                    cand_app = m.group(1).strip().rstrip('.')
                    if cand_app.lower() not in DISALLOWED_ENTITY_NAMES and not re.search(r'\b(?:result|link|the|first|second|third|fourth|fifth)\b', cand_app, re.IGNORECASE):
                        entity_value = cand_app
                        entity_type = "APPLICATION"

            elif primary_intent == "FILE_OPERATIONS":
                action_name = execution_result.get("action", "")
                f_path = execution_result.get("path") or execution_result.get("filepath")
                folder_val = execution_result.get("folder")
                file_val = execution_result.get("file")
                target_val = execution_result.get("target") or execution_result.get("name")

                if action_name in ("create_folder", "open_folder", "delete_folder", "list_folders") or folder_val:
                    entity_value = str(folder_val or target_val or "").strip().rstrip('.?!')
                    entity_type = "FOLDER"
                elif action_name in ("create_file", "open_file", "delete_file", "find_file") or file_val:
                    entity_value = str(file_val or target_val or "").strip().rstrip('.?!')
                    entity_type = "FILE"
                else:
                    is_folder_mention = bool(re.search(r'\b(?:folder|directory)\b', raw_input, re.IGNORECASE))
                    is_file_mention = bool(re.search(r'\b(?:file|document|text\s+file)\b', raw_input, re.IGNORECASE))
                    m = re.search(
                        r'\b(?:folder|directory|file)\s+(?:named\s+|called\s+)?(.+?)(?:\s+on\s+desktop)?$',
                        raw_input, re.IGNORECASE
                    )
                    if m:
                        entity_value = m.group(1).strip().rstrip('.')
                        entity_type = "FOLDER" if is_folder_mention and not is_file_mention else "FILE"
                    else:
                        m2 = re.search(
                            r'\b(?:create|make|delete|remove|find|search)\s+(?:a\s+)?(?:folder\s+|directory\s+|file\s+|text\s+file\s+)?(.+)',
                            raw_input, re.IGNORECASE
                        )
                        if m2:
                            entity_value = m2.group(1).strip().rstrip('.')
                            entity_type = "FOLDER" if is_folder_mention and not is_file_mention else "FILE"
                        elif target_val:
                            entity_value = str(target_val).strip().rstrip('.?!')
                            entity_type = "FOLDER" if is_folder_mention else "FILE"

            elif primary_intent == "MUSIC":
                m = re.search(r'\bplay\s+(.+)', raw_input, re.IGNORECASE)
                if m:
                    entity_value = m.group(1).strip()
                    entity_type = "SONG"

            if entity_value and str(entity_value).lower() not in DISALLOWED_ENTITY_NAMES:
                action_name = execution_result.get("action", "")
                is_close_act = (
                    primary_intent == "CLOSE_APPLICATION"
                    or action_name in ("close", "close_app", "terminate_process")
                    or (entity_type == "APPLICATION" and "closed" in str(execution_result.get("response", "")).lower())
                )
                actual_intent = "CLOSE_APPLICATION" if is_close_act else primary_intent
                self._last_mentioned_entity = {
                    "value": entity_value,
                    "name": entity_value,
                    "path": f_path if primary_intent == "FILE_OPERATIONS" else None,
                    "intent": actual_intent,
                    "action": actual_intent,
                    "entity_type": entity_type,
                    "status": "CLOSED" if is_close_act else "OPEN",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                status_lbl = "closed " if is_close_act else ""
                print(
                    f"[REFERENCE_TRACKING] Stored {status_lbl}entity: '{entity_value}' "
                    f"({entity_type}) from {actual_intent}"
                )
                self._record_recent_action(execution_result, intents, iso_now, current_t)

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
        
        # Extract compound application and search queries ("open Edge and search for AIML")
        m_compound = re.search(r'\b(?:open|launch|start)\s+([a-zA-Z0-9_\-\.]+)\s+and\s+(?:search(?:\s+google)?(?:\s+(?:for|on|in))?|look\s+up|find)\s+(.+?)[.!?]?$', user_input, re.IGNORECASE)
        if m_compound:
            app_raw = m_compound.group(1).strip()
            query_raw = m_compound.group(2).strip().rstrip('.?!')
            app_canonical = "Microsoft Edge" if app_raw.lower() in ("edge", "msedge") else ("Chrome" if app_raw.lower() == "chrome" else app_raw.capitalize())
            entities.append(EntityExtraction(
                entity_type="APPLICATION",
                entity_value=app_canonical,
                confidence=0.95,
                source="direct"
            ))
            entities.append(EntityExtraction(
                entity_type="SEARCH_QUERY",
                entity_value=query_raw,
                confidence=0.95,
                source="direct"
            ))

        # Extract general applications (e.g. "open Calculator", "close Notepad", "launch Spotify")
        for m_app in re.finditer(r'\b(?:open|launch|start|run|close|quit|kill)\s+([a-zA-Z0-9_\-\.]+)', user_input, re.IGNORECASE):
            app_raw = m_app.group(1).strip()
            if app_raw.lower() not in (
                "the", "a", "an", "my", "file", "folder", "document", "it", "that", "this", "both", "all",
                "something", "anything", "result", "terminal", "url", "link", "page", "tab"
            ):
                app_canon = "Microsoft Edge" if app_raw.lower() in ("edge", "msedge") else ("Chrome" if app_raw.lower() == "chrome" else app_raw.capitalize())
                entities.append(EntityExtraction(
                    entity_type="APPLICATION",
                    entity_value=app_canon,
                    confidence=0.90,
                    source="direct"
                ))

        # Also extract applications joined by 'and' without second verb (e.g. "open Calculator and Notepad")
        m_app_and = re.search(r'\b(?:open|launch|start|run|close|quit|kill)\s+([a-zA-Z0-9_\-\.]+)\s+and\s+([a-zA-Z0-9_\-\.]+)', user_input, re.IGNORECASE)
        if m_app_and:
            for g in (1, 2):
                a_name = m_app_and.group(g).strip()
                if a_name.lower() not in ("the", "a", "an", "my", "file", "folder", "document", "it", "that", "this", "both", "all"):
                    a_canon = "Microsoft Edge" if a_name.lower() in ("edge", "msedge") else ("Chrome" if a_name.lower() == "chrome" else a_name.capitalize())
                    entities.append(EntityExtraction(
                        entity_type="APPLICATION",
                        entity_value=a_canon,
                        confidence=0.92,
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
        """Enrich user input with context information for weather/time queries"""
        enriched = user_input
        
        # Add contextual information as hints only for relevant queries
        if "location" in context and "location" not in user_input.lower():
            if any(w in user_input.lower() for w in ["weather", "temperature", "forecast", "climate", "rain", "sunny", "how is it outside"]):
                location = context["location"]["value"]
                enriched = f"{enriched} in {location}"
        
        if "time" in context and any(t in user_input.lower() for t in ["tomorrow", "today", "when"]):
            time_val = context["time"]["value"]
            enriched = f"{enriched} [context: {time_val}]"
        
        return enriched
    
    def update_state(
        self,
        execution_result: Dict[str, Any],
        intents: List[str],
        observations: Optional[Dict[str, Any]] = None,
        state_difference: Optional[Dict[str, Any]] = None,
        goal: Optional[Dict[str, Any]] = None,
        subgoals: Optional[List[Dict[str, Any]]] = None,
        plan: Optional[Any] = None,
        goal_status: Optional[str] = None
    ) -> None:
        """Update dialogue state after execution with live state and observations"""
        
        # Update recent intents
        self.current_state.recent_intents.extend(intents)
        self.current_state.recent_intents = self.current_state.recent_intents[-5:]  # Keep last 5
        
        # Update goal, subgoals, plan, and status
        if goal:
            self.current_state.current_goal = goal
            if not self.current_state.original_goal:
                self.current_state.original_goal = goal
        if subgoals is not None:
            self.current_state.current_subgoals = subgoals
        if plan:
            self.current_state.current_plan = plan
            if isinstance(plan, dict):
                if plan.get("original_plan") and not self.current_state.original_plan:
                    self.current_state.original_plan = plan["original_plan"]
                self.current_state.adaptation_count = plan.get("adaptation_count", self.current_state.adaptation_count)
                self.current_state.adaptation_reason = plan.get("adaptation_reason", self.current_state.adaptation_reason)
                self.current_state.adaptation_history = plan.get("adaptation_history", self.current_state.adaptation_history)
                self.current_state.completed_steps = plan.get("completed_steps", self.current_state.completed_steps)
                self.current_state.failed_steps = plan.get("failed_steps", self.current_state.failed_steps)
            elif hasattr(plan, "original_plan"):
                if plan.original_plan and not self.current_state.original_plan:
                    self.current_state.original_plan = plan.original_plan
                self.current_state.adaptation_count = getattr(plan, "adaptation_count", 0)
                self.current_state.adaptation_reason = getattr(plan, "adaptation_reason", None)
                self.current_state.adaptation_history = getattr(plan, "adaptation_history", [])
                self.current_state.completed_steps = getattr(plan, "completed_steps", [])
                self.current_state.failed_steps = getattr(plan, "failed_steps", [])
        if goal_status:
            self.current_state.goal_status = goal_status
            
        # Record execution result in live state
        self.current_state.last_action_result = execution_result

        # Update environmental observations and state difference
        if state_difference:
            self.current_state.last_state_difference = state_difference
        if observations:
            self.current_state.environmental_observations.update(observations)
            if observations.get("active_window"):
                self.current_state.environmental_observations["active_window"] = observations["active_window"]
            if observations.get("active_application"):
                self.current_state.environmental_observations["active_application"] = observations["active_application"]
            if observations.get("caps_lock") is not None:
                self.current_state.environmental_observations["caps_lock"] = observations["caps_lock"]

        # Track background task
        if execution_result.get("task_id"):
            self.current_state.active_task = {
                "task_id": str(execution_result["task_id"]),
                "goal": execution_result.get("goal", ""),
                "status": "queued",
                "timestamp": datetime.now().isoformat()
            }
            self.current_state.last_action = {
                "intent": "TASK_MANAGEMENT",
                "action": "queue_task",
                "target": f"task {execution_result['task_id']}"
            }

        primary_intent = intents[0] if intents else ""

        # Track candidate file search results for multi-step / alternative selection
        if execution_result.get("files"):
            self.current_state.last_search_results = execution_result.get("files", [])
            self.current_state.last_search_results_turn = self.current_state.current_turn
            self.current_state.last_search_results_intent = primary_intent or "FILE_OPERATIONS"

        # Track active applications and sites ONLY when OPEN_APPLICATION occurred successfully
        if primary_intent == "OPEN_APPLICATION" and execution_result.get("status") in ("success", True, None):
            exec_action = execution_result.get("action")
            exec_entity_type = execution_result.get("entity_type")

            if exec_action == "open_browser_result" or exec_entity_type == "BROWSER_RESULT":
                if not self.current_state.active_application:
                    self.current_state.active_application = "browser"
                self.current_state.session_context["last_selected_result"] = execution_result
                if execution_result.get("url"):
                    self.current_state.session_context["active_url"] = execution_result.get("url")
                self.current_state.last_action = {
                    "intent": "OPEN_APPLICATION",
                    "action": "open_browser_result",
                    "target": execution_result.get("url") or execution_result.get("title") or "browser result"
                }
            elif exec_action == "search_web" or exec_entity_type == "SEARCH_QUERY":
                if not self.current_state.active_application:
                    self.current_state.active_application = "browser"
                q = execution_result.get("query") or ""
                self.current_state.session_context["last_search_query"] = q
                if execution_result.get("results"):
                    self.current_state.session_context["last_browser_result_set"] = execution_result["results"]
                self.current_state.last_action = {
                    "intent": "OPEN_APPLICATION",
                    "action": "search_web",
                    "target": q
                }
            else:
                raw_input_low = str(self.current_state.turns[-1].user_input if self.current_state.turns else "").lower()
                is_close = any(k in raw_input_low for k in ["close", "quit", "exit", "terminate", "kill"]) or execution_result.get("action") in ("close", "terminate_process")
                target = execution_result.get("target") or execution_result.get("app_name") or execution_result.get("display_name")
                if not target and self.current_state.turns:
                    m_app = re.search(r'\b(?:open|launch|start|go\s+to|visit|close|quit|exit|terminate|kill)\s+([a-zA-Z0-9_\-\s.]+)', self.current_state.turns[-1].user_input, re.IGNORECASE)
                    if m_app:
                        target = m_app.group(1).strip()

                if target and re.search(r'\s+and\s+(?:search|look\s+up|find)\s+', str(target), re.IGNORECASE):
                    m_comp = re.search(r'^(.*?)\s+and\s+(?:search(?:\s+google)?(?:\s+(?:for|on|in))?|look\s+up|find)\s+(.+)$', str(target), re.IGNORECASE)
                    if m_comp:
                        app_part = m_comp.group(1).strip()
                        query_part = m_comp.group(2).strip().rstrip('.?!')
                        target = "Microsoft Edge" if app_part.lower() in ("edge", "msedge") else ("Chrome" if app_part.lower() == "chrome" else app_part)
                        self.current_state.entities["application"] = target
                        self.current_state.entities["search_query"] = query_part

                if target:
                    target_str = str(target)
                    target_str = re.split(r'\s+(?:and|then|after\s+that|next)\s+(?:type|write|search|calculate|open|run)\b', target_str, flags=re.IGNORECASE)[0].strip()
                    target_str = re.sub(r'\s+(?:and|then)$', '', target_str, flags=re.IGNORECASE).strip()
                    target = target_str

                # Check if target is actually a result/link - do not store as application!
                if target and re.search(r'\b(?:(?:first|second|third|fourth|fifth|\d+(?:st|nd|rd|th)|top|previous)\s+)?(?:result|link)\b', str(target), re.IGNORECASE):
                    target = None

                if is_close:
                    self.current_state.last_action = {
                        "intent": "OPEN_APPLICATION",
                        "action": "close",
                        "target": target
                    }
                    sub_close = [st.strip().lower() for st in re.split(r'[,;]|\band\b', str(target)) if st.strip()]
                    self.current_state.active_applications = [
                        a for a in self.current_state.active_applications
                        if not any(st in a.lower() or a.lower() in st for st in sub_close)
                    ]
                    if "APPLICATION" in self.current_state.active_entity_set:
                        self.current_state.active_entity_set["APPLICATION"] = [
                            a for a in self.current_state.active_entity_set["APPLICATION"]
                            if not any(st in (a.get("value", a) if isinstance(a, dict) else str(a)).lower() for st in sub_close)
                        ]
                    opened = self.current_state.session_context.get("opened_applications", [])
                    self.current_state.session_context["opened_applications"] = [
                        a for a in opened
                        if not any(st in a.lower() or a.lower() in st for st in sub_close)
                    ]
                    if self.current_state.active_application and any(st in self.current_state.active_application.lower() or self.current_state.active_application.lower() in st for st in sub_close):
                        self.current_state.active_application = self.current_state.active_applications[-1] if self.current_state.active_applications else None
                    if not self.current_state.active_applications:
                        self.current_state.active_application = None
                    self.current_state.session_context.pop("active_browser", None)
                    self.current_state.session_context.pop("active_site", None)
                    try:
                        from extensions.context_manager import get_manager
                        ctx_m = get_manager()
                        if not self.current_state.active_applications:
                            ctx_m.clear_context()
                        else:
                            ctx_m.active_context["last_app"] = self.current_state.active_application
                    except Exception:
                        pass
                else:
                    if target:
                        t_low = str(target).lower().strip()
                        if "youtube" in t_low:
                            self.current_state.session_context["active_site"] = "youtube"
                            self.current_state.active_application = "Chrome"
                            if "Chrome" not in self.current_state.active_applications:
                                self.current_state.active_applications.append("Chrome")
                        else:
                            raw_sub_apps = [sa.strip() for sa in re.split(r'[,;]|\band\b', t_low) if sa.strip()]
                            clean_sub_apps = [sa for sa in raw_sub_apps if sa not in DISALLOWED_ENTITY_NAMES and len(sa) > 1]
                            for sa in clean_sub_apps:
                                canon_app = "Microsoft Edge" if sa in ("edge", "msedge") else ("Chrome" if sa == "chrome" else sa.capitalize())
                                if canon_app not in self.current_state.active_applications:
                                    self.current_state.active_applications.append(canon_app)
                                if "APPLICATION" not in self.current_state.active_entity_set:
                                    self.current_state.active_entity_set["APPLICATION"] = []
                                if canon_app not in self.current_state.active_entity_set["APPLICATION"]:
                                    self.current_state.active_entity_set["APPLICATION"].append(canon_app)
                            if clean_sub_apps:
                                last_app = clean_sub_apps[-1]
                                canon_last = "Microsoft Edge" if last_app in ("edge", "msedge") else ("Chrome" if last_app == "chrome" else last_app.capitalize())
                                self.current_state.active_application = canon_last
                                if any(b in canon_last.lower() for b in ["chrome", "browser", "edge", "firefox"]):
                                    self.current_state.session_context["active_browser"] = canon_last.lower()
                    self.current_state.last_action = {
                        "intent": "OPEN_APPLICATION",
                        "action": "open",
                        "target": target
                    }

        # Track device control / hardware state
        if primary_intent == "DEVICE_CONTROL":
            raw_input_low = str(self.current_state.turns[-1].user_input if self.current_state.turns else "").lower()
            action_name = execution_result.get("action", "")

            if action_name in ("set_brightness", "adjust_brightness", "increase_brightness", "decrease_brightness", "get_brightness") or "brightness" in raw_input_low:
                self.current_state.last_action = {
                    "intent": "DEVICE_CONTROL",
                    "action": action_name or "brightness",
                    "target": "brightness"
                }
            elif action_name in ("set_volume", "volume_up", "volume_down", "increase_volume", "decrease_volume", "get_volume", "mute", "unmute") or "volume" in raw_input_low:
                self.current_state.last_action = {
                    "intent": "DEVICE_CONTROL",
                    "action": action_name or "volume",
                    "target": "volume"
                }
            elif (
                execution_result.get("key") in ("Caps Lock", "Num Lock", "Scroll Lock")
                or action_name in ("set_key", "keyboard_state")
                or any(k in raw_input_low for k in ["caps lock", "num lock", "scroll lock"])
            ):
                key_name = execution_result.get("key") or ("Caps Lock" if "caps" in raw_input_low else ("Num Lock" if "num" in raw_input_low else "Scroll Lock"))
                caps_state = execution_result.get("caps_lock") if key_name == "Caps Lock" else execution_result.get("state")
                if caps_state is not None:
                    self.current_state.environmental_observations["caps_lock"] = caps_state
                self.current_state.last_action = {
                    "intent": "DEVICE_CONTROL",
                    "action": action_name or "toggle_key",
                    "target": key_name
                }
            elif action_name == "remote_device" or execution_result.get("code") or "phone" in raw_input_low or "mobile" in raw_input_low:
                self.current_state.active_device = {
                    "device_type": "phone",
                    "status": execution_result.get("status", "pairing_started"),
                    "code": execution_result.get("code")
                }
                self.current_state.last_action = {
                    "intent": "DEVICE_CONTROL",
                    "action": "connect_phone",
                    "target": "phone"
                }
            elif action_name in ("cpu_metrics", "detailed_cpu") or "cpu" in raw_input_low:
                self.current_state.last_action = {
                    "intent": "DEVICE_CONTROL",
                    "action": action_name or "cpu_metrics",
                    "target": "CPU"
                }
            elif action_name in ("gpu_telemetry", "detailed_gpu", "gpu_memory") or "gpu" in raw_input_low:
                self.current_state.last_action = {
                    "intent": "DEVICE_CONTROL",
                    "action": action_name or "gpu_telemetry",
                    "target": "GPU"
                }
            elif action_name in ("ram_metrics", "detailed_ram") or "ram" in raw_input_low:
                self.current_state.last_action = {
                    "intent": "DEVICE_CONTROL",
                    "action": action_name or "ram_metrics",
                    "target": "RAM"
                }

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

        # Update pairing code in session context if present
        if execution_result.get("code") and execution_result.get("status") in ("pairing_started", "pairing_code_active"):
            code_val = str(execution_result["code"])
            self.current_state.session_context["active_pairing_code"] = code_val
            self.current_state.entities["pairing_code"] = code_val
            self._last_mentioned_entity = {
                "value": code_val,
                "intent": "DEVICE_CONTROL",
                "entity_type": "pairing_code",
            }

        # Automatic detection & storage for Ephemeral Visual Response Surface
        try:
            from core.visual_response import detect_visual_response
            raw_user_in = self.current_state.turns[-1].user_input if self.current_state.turns else ""
            active_gid = (self.current_state.current_goal.get("id") or self.current_state.current_goal.get("goal_id")) if self.current_state.current_goal else None
            if not execution_result.get("visual_response"):
                vr = detect_visual_response(execution_result, raw_user_in, self.user_id, goal_id=active_gid)
                if vr:
                    self.store_visual_response(vr)
                    execution_result["visual_response"] = vr.to_dict()
                    try:
                        from core.assistant_core import assistant_core
                        assistant_core.show_visual_response(vr)
                    except Exception:
                        pass
        except Exception as vr_err:
            print(f"[VISUAL_RESPONSE] Auto-detection notice: {vr_err}")

        # Synchronize with ContextManager for system-wide consistency
        try:
            from extensions.context_manager import get_manager
            ctx_mgr = get_manager()
            # Only update active app/browser context if the command actually opened/interacted with an application
            if primary_intent in ("OPEN_APPLICATION", "WINDOW_CONTEXT") and self.current_state.active_application:
                ctx_type = "browser" if self.current_state.active_application in ("chrome", "edge", "firefox", "browser") else "app"
                ctx_mgr.set_active_context(ctx_type, self.current_state.active_application)
            if self.current_state.active_task:
                ctx_mgr.active_context["active_task"] = self.current_state.active_task
            if self.current_state.active_device:
                ctx_mgr.active_context["active_device"] = self.current_state.active_device
        except Exception:
            pass

        # Record structured action history in DialogueState
        raw_cmd = self.current_state.turns[-1].user_input if self.current_state.turns else ""
        act_entry = {
            "intent": primary_intent or execution_result.get("intent", "UNKNOWN"),
            "command": raw_cmd,
            "command_signature": raw_cmd,
            "status": execution_result.get("status", "completed"),
            "action": execution_result.get("action", ""),
            "target": execution_result.get("target") or execution_result.get("app_name") or execution_result.get("file"),
            "timestamp": time.time(),
            "response": execution_result.get("response", "")
        }
        self.current_state.recent_actions.append(act_entry)
        if len(self.current_state.recent_actions) > 20:
            self.current_state.recent_actions.pop(0)

        if execution_result.get("status") in ("success", True, "completed", None) and not execution_result.get("error"):
            self.current_state.recent_successful_actions.append(act_entry)
            if len(self.current_state.recent_successful_actions) > 20:
                self.current_state.recent_successful_actions.pop(0)
        else:
            self.current_state.recent_failed_actions.append(act_entry)
            if len(self.current_state.recent_failed_actions) > 20:
                self.current_state.recent_failed_actions.pop(0)

    def record_execution_result(self, execution_result: Dict[str, Any], intents: Optional[List[str]] = None) -> None:
        """Alias/wrapper for recording execution results into DialogueStateManager."""
        self.update_state(
            execution_result=execution_result,
            intents=intents or []
        )

    def record_goal_outcome(self, outcome: Any) -> Dict[str, Any]:
        """
        Record final outcome of a goal and enforce goal boundary (PHASE 8).

        - Closes active goal / plan so future turns aren't hijacked
        - Updates goal_status to outcome status ("COMPLETED", "FAILED", "BLOCKED", "CANCELLED", "WAITING_FOR_USER")
        - Preserves useful short-term post-goal context (target, app, entities, results)
        - Clears pending continuations/adaptations if cancelled/terminal
        - Stores in-memory goal outcome record
        """
        outcome_dict = outcome.to_dict() if hasattr(outcome, "to_dict") else dict(outcome)

        self.current_state.last_goal_outcome = outcome_dict
        self.current_state.goal_outcomes_history.append(outcome_dict)
        if len(self.current_state.goal_outcomes_history) > 10:
            self.current_state.goal_outcomes_history.pop(0)

        status = outcome_dict.get("actual_outcome", "COMPLETED")
        self.current_state.goal_status = status

        # Build preserved short-term post-goal context
        entities_dict = outcome_dict.get("entities") or {}
        results_dict = outcome_dict.get("results") or {}

        target = (
            results_dict.get("target")
            or results_dict.get("app_name")
            or results_dict.get("file")
            or results_dict.get("task_id")
            or entities_dict.get("target")
            or entities_dict.get("file")
            or entities_dict.get("query")
        )

        self.current_state.post_goal_context = {
            "goal_id": outcome_dict.get("goal_id", ""),
            "user_request": outcome_dict.get("user_request", ""),
            "last_action": outcome_dict.get("attempted_action", ""),
            "outcome": status,
            "summary": outcome_dict.get("summary", ""),
            "entities": entities_dict,
            "results": results_dict,
            "target": target,
            "turn": self.current_state.current_turn,
            "timestamp": outcome_dict.get("timestamp", datetime.now().isoformat()),
            "application": self.current_state.active_application,
            "device": self.current_state.active_device,
        }

        # Enforce Goal Completion Boundary if reaching a terminal state
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            if self.current_state.current_goal:
                self.current_state.current_goal["status"] = status
                self.current_state.current_goal["is_terminal"] = True
            self.current_state.pending_goal_continuation = None
            # Only clear pending_action if there is NO active implicit-goal
            # confirmation awaiting user response.  The implicit-goal handler
            # sets pending_action + pending_confirmation = True and returns
            # "clarification_needed"; brain.py then records outcome as
            # "COMPLETED" — clearing here would wipe the pending action before
            # the user has had a chance to confirm or deny it.
            if not self.current_state.pending_confirmation:
                self.current_state.pending_action = None

            # Phase 9: Synchronize terminal state to PostgreSQL active_contexts
            gid = outcome_dict.get("goal_id")
            if gid:
                try:
                    from extensions.database_manager import get_db
                    db = get_db()
                    if db:
                        db.update_persistent_goal_status(self.user_id, gid, status, resumable=False)
                except Exception:
                    pass

            if status == "CANCELLED":
                self.current_state.pending_clarification = None
                self.current_state.adaptation_count = 0
                self.current_state.adaptation_reason = None
                if self.current_state.active_task:
                    self.current_state.active_task["status"] = "cancelled"
                if self.current_state.active_device:
                    self.current_state.active_device["status"] = "cancelled"
        elif status in ("WAITING_FOR_USER", "BLOCKED"):
            gid = outcome_dict.get("goal_id")
            req = str(outcome_dict.get("user_request", "")).lower()
            if gid and not any(req.startswith(p) for p in ("what is the weather", "what time is it", "calculate", "tell me a joke", "hello", "hi")):
                try:
                    self.persist_current_goal(
                        reason=status,
                        required_user_input=outcome_dict.get("summary"),
                        environment_assumptions=outcome_dict.get("entities", {})
                    )
                except Exception:
                    pass

        return outcome_dict

    # =========================================================================
    # PHASE 9: CROSS-SESSION GOAL CONTINUITY & RESUMPTION
    # =========================================================================

    def persist_current_goal(
        self,
        reason: str = "WAITING_FOR_USER",
        required_user_input: Optional[str] = None,
        environment_assumptions: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Persist an eligible unfinished goal across sessions to PostgreSQL active_contexts.
        
        Eligibility rules (Section 3):
        - WAITING_FOR_USER
        - Eligible BLOCKED goal waiting for external condition
        - Explicitly requested 'USER_EXPLICIT_LATER'
        - Long-running background task
        
        Never persists ordinary completed/failed/cancelled commands, simple questions,
        calculator requests, weather queries, or casual conversation.
        Never persists raw audio, screen captures, passwords, or tokens.
        """
        g = self.current_state.current_goal
        if not g:
            if self.current_state.active_task:
                t = self.current_state.active_task
                tid = t.get("task_id") if isinstance(t, dict) else str(t)
                g = {
                    "goal_id": f"task_goal_{tid}",
                    "user_request": f"Background task {tid}",
                    "goal_type": "TASK_MANAGEMENT",
                    "status": "RUNNING"
                }
            elif self.current_state.pending_goal_continuation:
                cont = self.current_state.pending_goal_continuation
                g = {
                    "goal_id": str(uuid.uuid4())[:8],
                    "user_request": cont.get("raw_input") or "Unfinished goal",
                    "goal_type": "MULTI_STEP",
                    "status": "WAITING_FOR_USER"
                }
            else:
                return False

        status = str(g.get("status", self.current_state.goal_status)).upper()
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            return False

        gid = str(g.get("goal_id") or g.get("id") or uuid.uuid4().hex[:8])
        user_req = str(g.get("user_request") or g.get("request") or g.get("raw_input") or "Unfinished goal")
        
        # Non-persistent intent check
        low_req = user_req.lower()
        if any(low_req.startswith(p) for p in ("what is the weather", "what time is it", "calculate", "tell me a joke", "hello", "hi")):
            return False

        plan = self.current_state.current_plan or {}
        steps = plan.get("steps", [])
        curr_step = plan.get("current_step", 0)
        remaining = steps[curr_step:] if isinstance(steps, list) else []

        record = PersistentGoalRecord(
            goal_id=gid,
            user_id=str(self.user_id),
            original_request=user_req,
            goal_type=str(g.get("goal_type") or "MULTI_STEP"),
            goal_status=status,
            current_step=curr_step,
            remaining_steps=remaining,
            entities=dict(self.current_state.entities),
            created_at=time.time(),
            updated_at=time.time(),
            session_id=str(self.current_state.session_id),
            resumable=True,
            persistence_reason=reason,
            required_user_input=required_user_input or self.current_state.pending_clarification,
            last_known_result=str(self.current_state.last_action_result.get("response", "")) if self.current_state.last_action_result else None,
            environment_assumptions=environment_assumptions or {}
        )

        try:
            from extensions.database_manager import get_db
            db = get_db()
            if db:
                return db.save_persistent_goal(self.user_id, record.to_dict())
        except Exception as e:
            print(f"[DIALOGUE_STATE_MANAGER] Error saving persistent goal: {e}")
        return False

    def check_resumable_goals(self, auto_offer: bool = True) -> Optional[str]:
        """
        Inspect PostgreSQL active_contexts for eligible resumable goals for this user.
        Validates freshness, environment assumptions, and filters out terminal or stale goals.
        Does NOT execute any goal automatically.
        Formulates a concise choice prompt if eligible goals exist.
        """
        try:
            from extensions.database_manager import get_db
            db = get_db()
            if not db:
                return None
            records = db.get_persistent_goals(self.user_id, only_resumable=True)
        except Exception as e:
            print(f"[DIALOGUE_STATE_MANAGER] Error checking resumable goals: {e}")
            return None

        if not records:
            self.current_state.pending_goal_resumption = None
            return None

        valid_goals = []
        now = time.time()
        for rec in records:
            # 1. Freshness check: max 7 days (604800s)
            created_at = float(rec.get("created_at") or now)
            if (now - created_at) > 7 * 86400:
                try:
                    db.update_persistent_goal_status(self.user_id, rec.get("goal_id", ""), "FAILED", resumable=False, last_known_result="Expired continuation window")
                except Exception:
                    pass
                continue

            # 2. Terminal check
            st = str(rec.get("goal_status", "")).upper()
            if st in ("COMPLETED", "FAILED", "CANCELLED"):
                continue

            # 3. Environment assumption validation
            env_assumptions = rec.get("environment_assumptions") or {}
            req_file = env_assumptions.get("required_file")
            if req_file and not os.path.exists(req_file):
                try:
                    db.update_persistent_goal_status(self.user_id, rec.get("goal_id", ""), "FAILED", resumable=False, last_known_result="Required entity/file missing")
                except Exception:
                    pass
                continue

            req_task_id = env_assumptions.get("task_id") or (rec.get("entities") or {}).get("task_id")
            if req_task_id:
                try:
                    from core.environment_observer import observe_environment
                    snap = observe_environment(user_id=self.user_id, relevant_categories={"tasks"})
                    t_info = next((t for t in snap.running_tasks if str(t.get("task_id")) == str(req_task_id)), None)
                    if t_info and t_info.get("status") == "completed":
                        db.update_persistent_goal_status(self.user_id, rec.get("goal_id", ""), "COMPLETED", resumable=False, last_known_result="Background task finished successfully")
                        continue
                except Exception:
                    pass

            valid_goals.append(rec)

        if not valid_goals:
            self.current_state.pending_goal_resumption = None
            return None

        if len(valid_goals) == 1:
            g = valid_goals[0]
            req_text = g.get("original_request", "unfinished task")
            prompt = f"You have an unfinished task: {req_text}. Would you like to continue?"
        else:
            prompt = f"You have {len(valid_goals)} unfinished goals:\n"
            for i, g in enumerate(valid_goals, 1):
                prompt += f"{i}. {g.get('original_request', 'task')}\n"
            prompt += "Which one would you like to continue?"

        if auto_offer:
            self.current_state.pending_goal_resumption = {
                "goals": valid_goals,
                "prompt": prompt,
                "offered_at": now
            }

        return prompt

    def handle_resumption_response(self, user_input: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Evaluate user response to a resumption prompt.
        Returns: (should_resume: bool, selected_goal: Optional[dict], response_text: str)
        """
        if not self.current_state.pending_goal_resumption:
            return (False, None, "")

        goals = self.current_state.pending_goal_resumption.get("goals") or []
        if not goals:
            self.current_state.pending_goal_resumption = None
            return (False, None, "")

        inp_low = user_input.strip().lower()

        # If user input is an independent command or correction (e.g. "no, search for ...", "open chrome", "what time is it")
        if re.search(r'^(?:no[,\s]+)?(?:search|open|find|create|run|calculate|what|show|check|play)\b', inp_low):
            self.current_state.pending_goal_resumption = None
            return (False, None, "")

        # Decline ("no", "not now", "don't", "no thanks", "nope")
        if re.match(r'^(?:no|not\s+now|don\'?t|never\s+mind|skip|no\s+thanks|nope)[.!]?$', inp_low.strip()):
            self.current_state.pending_goal_resumption = None
            return (False, None, "Okay, I won't resume that.")

        # Postpone ("later", "do this later", "not yet")
        if re.search(r'\b(later|not\s+yet|keep\s+it|postpone)\b', inp_low):
            self.current_state.pending_goal_resumption = None
            return (False, None, "Alright, I'll keep it saved for later.")

        # Cancel ("cancel it", "cancel that", "delete it", "stop")
        if re.search(r'\b(cancel(?:\s+it|\s+that)?|delete\s+it|stop)\b', inp_low):
            try:
                from extensions.database_manager import get_db
                db = get_db()
                if db:
                    for g in goals:
                        db.update_persistent_goal_status(self.user_id, g.get("goal_id", ""), "CANCELLED", resumable=False)
            except Exception:
                pass
            self.current_state.pending_goal_resumption = None
            return (False, None, "I've cancelled that unfinished goal.")

        # Selection by number/ordinal or keyword
        selected_goal = None
        if len(goals) == 1:
            if re.search(r'\b(yes|yeah|sure|continue|resume|go\s+ahead|yep|ok|okay)\b', inp_low):
                selected_goal = goals[0]
        else:
            if re.search(r'\b(first|1st|1|the\s+first(?:\s+(?:one|task|goal))?)\b', inp_low):
                selected_goal = goals[0]
            elif len(goals) > 1 and re.search(r'\b(second|2nd|2|the\s+second(?:\s+(?:one|task|goal))?)\b', inp_low):
                selected_goal = goals[1]
            elif len(goals) > 2 and re.search(r'\b(third|3rd|3|the\s+third(?:\s+(?:one|task|goal))?)\b', inp_low):
                selected_goal = goals[2]
            else:
                for g in goals:
                    req_words = [w for w in g.get("original_request", "").lower().split() if len(w) > 3]
                    if any(w in inp_low for w in req_words):
                        selected_goal = g
                        break

            if not selected_goal and re.search(r'\b(yes|yeah|sure|continue|resume)\b', inp_low):
                return (False, None, "Please specify which goal you would like to continue (for example, 'the first one' or 'the second one').")

        if selected_goal:
            self.current_state.pending_goal_resumption = None
            self.current_state.restored_goal = selected_goal
            return (True, selected_goal, f"Resuming: {selected_goal.get('original_request', 'task')}.")

        return (False, None, "")

    def close_persistent_goal(self, goal_id: str, final_status: str = "COMPLETED") -> bool:
        """Closes a persistent goal in PostgreSQL active_contexts so it cannot resurrect."""
        try:
            from extensions.database_manager import get_db
            db = get_db()
            if db:
                return db.update_persistent_goal_status(self.user_id, goal_id, final_status, resumable=False)
        except Exception:
            pass
        return False
    
    def record_response(self, response: str) -> None:
        """Record assistant response"""
        if self.current_state.turns:
            last_turn = self.current_state.turns[-1]
            last_turn.assistant_response = response
            last_turn.response_timestamp = datetime.now().isoformat()
        self.current_state.current_response = response

    # ── Conversational Continuation Methods ─────────────────────────────────
    def update_continuation_state(
        self,
        full_response: str = "",
        spoken_segment: str = "",
        remaining_segments: Optional[List[str]] = None,
        recommendation_list: Optional[List[str]] = None,
        interruption_position: int = 0,
        interrupted_speech: str = "",
    ) -> None:
        """Track granular response, spoken segment, recommendation items, and barge-in state."""
        if full_response:
            self.current_state.current_response = full_response
        if spoken_segment:
            self.current_state.current_spoken_segment = spoken_segment
        if remaining_segments is not None:
            self.current_state.remaining_response_segments = list(remaining_segments)
        if recommendation_list is not None and len(recommendation_list) > 0:
            self.current_state.current_recommendation_list = list(recommendation_list)
            self.current_state.current_list_position = 0
        if interruption_position > 0:
            self.current_state.interruption_position = interruption_position
        if interrupted_speech:
            self.current_state.interrupted_speech_text = interrupted_speech

    def get_full_list_response(self) -> str:
        """Returns the full list from active recommendation state or full response."""
        rec_list = self.current_state.current_recommendation_list
        if rec_list:
            formatted = "\n".join(f"{i+1}. {item}" for i, item in enumerate(rec_list))
            return f"Here is the full list:\n{formatted}"
        full_resp = self.current_state.current_response
        if full_resp:
            return full_resp
        return "I don't have an active recommendation list from our recent conversation."

    def get_continue_response(self) -> str:
        """Resumes from interruption point, remaining segments, or remaining items."""
        # 1. Check if spoken answer was interrupted by barge-in
        if self.current_state.interrupted_speech_text:
            cont = self.current_state.interrupted_speech_text
            self.current_state.interrupted_speech_text = ""
            return f"Continuing what I was saying: {cont}"
        # 2. Check remaining response segments
        if self.current_state.remaining_response_segments:
            seg = self.current_state.remaining_response_segments.pop(0)
            return seg
        # 3. Check remaining recommendation items
        rec_list = self.current_state.current_recommendation_list
        cur_pos = self.current_state.current_list_position
        if rec_list and cur_pos + 1 < len(rec_list):
            rem_items = rec_list[cur_pos + 1:]
            self.current_state.current_list_position = len(rec_list) - 1
            return "Here are the remaining items: " + ", ".join(rem_items) + "."
        return "That was the complete response."

    def get_repeat_last_part(self) -> str:
        """Repeats the last spoken segment or response."""
        if self.current_state.current_spoken_segment:
            return self.current_state.current_spoken_segment
        if self.current_state.current_response:
            return self.current_state.current_response
        return "Nothing was recently spoken to repeat."

    def get_next_item(self) -> str:
        """Returns the next item from the active recommendation list."""
        rec_list = self.current_state.current_recommendation_list
        if not rec_list:
            return "There is no active recommendation list."
        next_pos = self.current_state.current_list_position + 1
        if next_pos < len(rec_list):
            self.current_state.current_list_position = next_pos
            return f"The next item is {rec_list[next_pos]}."
        return f"That was the last item: {rec_list[-1]}."

    def get_first_item(self) -> str:
        """Returns the first item from the active recommendation list."""
        rec_list = self.current_state.current_recommendation_list
        if not rec_list:
            return "There is no active recommendation list."
        self.current_state.current_list_position = 0
        return f"The first item is {rec_list[0]}."

    def get_previous_item(self) -> str:
        """Returns the previous item from the active recommendation list."""
        rec_list = self.current_state.current_recommendation_list
        if not rec_list:
            return "There is no active recommendation list."
        prev_pos = max(0, self.current_state.current_list_position - 1)
        self.current_state.current_list_position = prev_pos
        return f"The previous item is {rec_list[prev_pos]}."

    def get_last_item(self) -> str:
        """Returns the last item from the active recommendation list."""
        rec_list = self.current_state.current_recommendation_list
        if not rec_list:
            return "There is no active recommendation list."
        last_pos = len(rec_list) - 1
        self.current_state.current_list_position = last_pos
        return f"The last item is {rec_list[last_pos]}."

    def get_item_by_index(self, index: int) -> str:
        """Returns the item at a specific 0-based index from active recommendation or response list."""
        rec_list = self.current_state.current_recommendation_list
        if not rec_list and self.current_state.active_response_state:
            rec_list = self.current_state.active_response_state.items
        if not rec_list:
            return "There is no active recommendation list."
        if 0 <= index < len(rec_list):
            self.current_state.current_list_position = index
            item = rec_list[index]
            ord_names = {0: "first", 1: "second", 2: "third", 3: "fourth", 4: "fifth", 5: "sixth", 6: "seventh", 7: "eighth", 8: "ninth", 9: "tenth"}
            ord_label = ord_names.get(index, f"{index + 1}th")
            return f"The {ord_label} item is {item}."
        return f"Index {index + 1} is out of range. There are {len(rec_list)} items available."

    def get_calculation_answer(self) -> Optional[str]:
        """Returns the latest calculation answer deterministically without LLM."""
        calc = getattr(self.current_state, "active_calculation", None)
        if calc and isinstance(calc, dict):
            res = calc.get("result")
            expr = calc.get("expression")
            if res is not None:
                return f"{res}"
        return None

    def get_goal_step(self, step_index: int) -> Optional[str]:
        """Returns step description from active goal or plan deterministically without LLM."""
        g = getattr(self.current_state, "current_goal", None) or getattr(self.current_state, "active_goal", None)
        steps = None
        if g and isinstance(g, dict):
            steps = g.get("steps") or g.get("plan_steps") or (g.get("plan") or {}).get("steps")
        if not steps and getattr(self.current_state, "current_plan", None):
            plan = self.current_state.current_plan
            if isinstance(plan, dict):
                steps = plan.get("steps")
        if steps and isinstance(steps, list) and 0 <= step_index < len(steps):
            step_item = steps[step_index]
            if isinstance(step_item, dict):
                desc = step_item.get("description") or step_item.get("action") or step_item.get("name") or str(step_item)
                return f"Step {step_index + 1}: {desc}"
            return f"Step {step_index + 1}: {step_item}"
        return None

    def set_response_state(self, resp_state: ResponseState) -> None:
        """Store explicit structured response state for resumption and list navigation."""
        self.current_state.active_response_state = resp_state
        if resp_state.items:
            self.current_state.current_recommendation_list = list(resp_state.items)
            self.current_state.current_list_position = resp_state.current_item_index
        if resp_state.full_text:
            self.current_state.current_response = resp_state.full_text
        if resp_state.spoken_segments:
            self.current_state.current_spoken_segment = " ".join(resp_state.spoken_segments)
        if resp_state.remaining_segments:
            self.current_state.remaining_response_segments = list(resp_state.remaining_segments)

    def get_response_state(self) -> Optional[ResponseState]:
        """Retrieve current structured response state."""
        return self.current_state.active_response_state

    def get_state(self) -> DialogueState:
        """Get current dialogue state"""
        return self.current_state

    # ── Ephemeral Visual Response Methods ────────────────────────────────────
    def store_visual_response(self, visual_response: Any) -> None:
        """Store a user-scoped visual response in short-term dialogue state."""
        if hasattr(visual_response, "to_dict"):
            vr_dict = visual_response.to_dict()
        elif isinstance(visual_response, dict):
            vr_dict = visual_response
        else:
            return

        self.current_state.last_visual_response = vr_dict
        self.current_state.visual_response_history.append(vr_dict)
        if len(self.current_state.visual_response_history) > 10:
            self.current_state.visual_response_history.pop(0)

    def is_active(self) -> bool:
        """Return whether dialogue state manager has an active session."""
        return bool(self.current_state.is_active and self.current_state.session_id)

    def get_last_visual_response(
        self,
        response_type: Optional[str] = None,
        allow_expired: bool = False,
        max_age_seconds: Optional[float] = None
    ) -> Optional[Any]:
        """
        Retrieve the last eligible visual response for this user without regeneration.
        Enforces user-scoped cache and contextual freshness.
        """
        now = time.time()
        candidates = []
        if self.current_state.last_visual_response:
            candidates.append(self.current_state.last_visual_response)
        for hist_vr in reversed(self.current_state.visual_response_history):
            if hist_vr not in candidates:
                candidates.append(hist_vr)

        # If no explicit visual response exists in cache, check if previous turn has a spoken response to recover
        if not candidates and self.current_state.turns:
            for turn in reversed(self.current_state.turns):
                resp = getattr(turn, "assistant_response", "") or ""
                u_in = getattr(turn, "user_input", "") or ""
                if resp.strip() and not resp.startswith("There is no recent") and not resp.startswith("I encountered an error"):
                    from core.visual_response import extract_visual_title, VisualResponseType, VisualResponseAction, VisualResponse
                    title_str = extract_visual_title(u_in, resp, default="KNOWLEDGE")
                    synth_vr = VisualResponse(
                        response_id=str(uuid.uuid4())[:8],
                        user_id=self.user_id,
                        response_type=VisualResponseType.KNOWLEDGE,
                        title=title_str,
                        primary_value=resp.strip(),
                        actions=[VisualResponseAction(label="Copy", action_type="copy", payload=resp.strip())],
                        created_at=now,
                        ttl_seconds=300.0,
                        source_context="turn_recovery"
                    )
                    candidates.append(synth_vr.to_dict())
                    self.store_visual_response(synth_vr)
                    break

        if not candidates:
            return None

        from core.visual_response import VisualResponse
        for vr in candidates:
            if response_type and str(response_type).upper() not in ("RESULT", "GENERIC_RESULT", "ANY"):
                t = str(vr.get("response_type", "")).upper()
                req_t = str(response_type).upper()
                if req_t not in t and t not in req_t:
                    continue

            created = float(vr.get("created_at", now))
            ttl = float(vr.get("ttl_seconds", 300.0))
            if max_age_seconds is not None:
                ttl = min(ttl, float(max_age_seconds))

            is_expired = (now - created) > ttl
            if is_expired and not allow_expired:
                continue

            return VisualResponse.from_dict(vr)
        return None

    def get_recent_visual_candidates(self) -> List[Dict[str, Any]]:
        """Return all fresh unexpired visual candidates in recent history."""
        now = time.time()
        valid = []
        for vr in reversed(self.current_state.visual_response_history):
            created = float(vr.get("created_at", now))
            ttl = float(vr.get("ttl_seconds", 300.0))
            if (now - created) <= ttl and vr not in valid:
                valid.append(vr)
        return valid

    def clear_visual_response(self) -> None:
        """Clear current visual response without destroying historical context."""
        self.current_state.last_visual_response = None
    
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


def get_dialogue_manager(user_id: Any = None) -> DialogueStateManager:
    """Get or create dialogue manager for user with active session resolution."""
    resolved_uid = user_id
    if resolved_uid is None or str(resolved_uid).lower() in ("default", "none"):
        try:
            from instance.config import settings
            cur_uid = getattr(settings, 'CURRENT_USER_ID', None)
            if cur_uid is not None:
                resolved_uid = cur_uid
            elif hasattr(settings, 'get_last_user'):
                resolved_uid = settings.get_last_user()
        except Exception:
            pass
    uid_str = str(resolved_uid if resolved_uid is not None else "default")
    if uid_str not in _dialogue_managers:
        _dialogue_managers[uid_str] = DialogueStateManager(uid_str)
    return _dialogue_managers[uid_str]


DialogueStateManager.get_instance = staticmethod(get_dialogue_manager)


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
