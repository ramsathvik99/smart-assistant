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
    active_application: Optional[str] = None
    active_window: Optional[Dict[str, Any]] = None
    last_action: Optional[Dict[str, Any]] = None
    last_action_result: Optional[Dict[str, Any]] = None
    last_search_results: List[Dict[str, Any]] = field(default_factory=list)
    last_search_results_turn: int = 0
    last_search_results_intent: Optional[str] = None
    active_task: Optional[Dict[str, Any]] = None
    active_device: Optional[Dict[str, Any]] = None
    pending_action: Optional[Dict[str, Any]] = None
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

    # State flags
    is_active: bool = True


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
        r'^(?P<verb>\w+)\s+(?:the\s+)?(?P<pronoun>it|that|them|this|those)\s*$',
        # "delete that file", "open that file", "show that file", "delete this file"
        r'^(?P<verb>\w+)\s+(?:the\s+|that\s+|this\s+)?(?:file|document|presentation|folder|app|task)\s*$',
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
        lower = stripped.lower()

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
                    last_intent == "WEB_SEARCH"
                    or self.current_state.session_context.get("active_browser") is not None
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

        # Result click/select ("Open the first result", "click the top result", "open the second result", "open the 3rd result", "open the previous result")
        m_res = re.search(r'\b(?:open|play|select|click)\s+(?:the\s+)?(first|top|1st|second|2nd|third|3rd|previous)\s+result\b', lower)
        if is_browser and m_res:
            # Check if concrete web search results exist in state
            has_web_results = any(r.get("type") == "web_result" or r.get("url") for r in self.current_state.last_search_results)
            if not has_web_results:
                resolved = "explain_web_search_results_unavailable"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (truthful web search resolution: no web result entities)")
                return resolved, True

            ord_name = m_res.group(1).lower()
            ord_idx = 0 if ord_name in ("first", "top", "1st") else (1 if ord_name in ("second", "2nd") else (2 if ord_name in ("third", "3rd") else 0))
            if ord_idx < len(self.current_state.last_search_results):
                item = self.current_state.last_search_results[ord_idx]
                target_url = item.get("url") or item.get("link")
                if target_url:
                    resolved = f"open url {target_url}"
                    return resolved, True

        # Browser Navigation ("Go back", "Navigate back", "Back")
        if is_browser and re.match(r'^(?:go\s+back|navigate\s+back|back)[.!?]?$', lower):
            resolved = "go back"
            print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (browser navigation back)")
            return resolved, True

        if is_browser and re.match(r'^(?:search\s+(?:for\s+)?|find\s+videos?\s+(?:about|on|for)\s+)(.+)', stripped, re.IGNORECASE):
            m_s = re.match(r'^(?:search\s+(?:for\s+)?|find\s+videos?\s+(?:about|on|for)\s+)(.+)', stripped, re.IGNORECASE)
            search_query = m_s.group(1).strip().rstrip('.?!')
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

            # Check search freshness
            is_search_fresh = (
                bool(self.current_state.last_search_results)
                and (
                    self.current_state.goal_status == "WAITING_FOR_USER"
                    or (self.current_state.current_turn - getattr(self.current_state, "last_search_results_turn", 0) <= 2)
                )
            )

            if not is_search_fresh or not self.current_state.last_search_results:
                resolved = "clarify_candidate_selection_unavailable"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (no fresh search candidates in state)")
                return resolved, True

            candidates = self.current_state.last_search_results
            if idx < len(candidates):
                target_item = candidates[idx]
                fpath = target_item.get("path") or target_item.get("name")
                resolved = f"open file {fpath}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (ordinal file selection [{idx}]: '{fpath}')")
                return resolved, True
            else:
                total_found = len(candidates)
                resolved = f"candidate_ordinal_out_of_range {idx + 1} {total_found}"
                print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (ordinal {idx + 1} exceeds {total_found})")
                return resolved, True

        # ── 6. Pronominal commands with last_mentioned_entity ("close it", "delete that file", "open it") ──
        if not self._last_mentioned_entity:
            return user_input, False

        # Fast exit: if the input already contains a specific named entity
        tokens = lower.split()
        if len(tokens) >= 5:
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

                # Check for "that file" / "this file" / "the file" / "that presentation"
                m_target_phrase = re.search(r'\b(?:that|this|the)\s+(?:file|document|presentation|folder|app|task)\b', clean_stripped, re.IGNORECASE)
                if m_target_phrase:
                    if not is_entity_fresh:
                        if clean_stripped.lower().startswith("delete") or clean_stripped.lower().startswith("remove"):
                            return "clarify_which_file_to_delete", True
                        elif clean_stripped.lower().startswith("open"):
                            return "clarify_candidate_selection_unavailable", True
                        return user_input, False

                    start, end = m_target_phrase.start(), m_target_phrase.end()
                    prefix_word = "file " if entity_type == "FILE" and not clean_stripped.lower().startswith("delete") else ""
                    resolved = clean_stripped[:start] + f"{prefix_word}{clean_entity}" + clean_stripped[end:]
                    resolved = re.sub(r'\s+', ' ', resolved).strip()
                    print(f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' (entity: '{clean_entity}' from {intent})")
                    return resolved, True

                pronoun_match = re.search(
                    r'\b(it|that|them|this|those)\b', clean_stripped, re.IGNORECASE
                )
                if pronoun_match:
                    if not is_entity_fresh:
                        if clean_stripped.lower().startswith("delete") or clean_stripped.lower().startswith("remove"):
                            return "clarify_which_file_to_delete", True
                        return user_input, False

                    start, end = pronoun_match.start(), pronoun_match.end()
                    prefix_word = "file " if entity_type == "FILE" and not clean_stripped.lower().startswith("open file") else ""
                    resolved = clean_stripped[:start] + f"{prefix_word}{clean_entity}".strip() + clean_stripped[end:]
                    resolved = re.sub(r'\s+', ' ', resolved).strip()
                    print(
                        f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' "
                        f"(entity: '{clean_entity}' from {intent})"
                    )
                    return resolved, True

                if not is_entity_fresh:
                    return user_input, False

                resolved = f"{clean_stripped} {clean_entity}".strip()
                print(
                    f"[REFERENCE_RESOLUTION] '{user_input}' -> '{resolved}' "
                    f"(entity: '{clean_entity}' from {intent})"
                )
                return resolved, True

        return user_input, False

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

        # Check if raw input or execution target contains a specific filename
        raw_input_text = self.current_state.turns[-1].user_input if self.current_state.turns else ""
        m_file_target = re.search(r'\b([\w\-.]+\.(?:txt|pdf|docx|xlsx|pptx|py|json|md|csv|png|jpg))\b', raw_input_text, re.IGNORECASE)
        if m_file_target:
            fname = m_file_target.group(1).strip()
            self._last_mentioned_entity = {
                "value": fname,
                "intent": "FILE_OPERATIONS",
                "entity_type": "FILE",
                "turn": current_t,
                "timestamp": iso_now,
            }
            print(f"[REFERENCE_TRACKING] Stored file entity: '{fname}' (FILE)")
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
            if execution_result.get("key") == "Caps Lock" or "caps" in str(execution_result).lower():
                self._last_mentioned_entity = {
                    "value": "Caps Lock",
                    "intent": "DEVICE_CONTROL",
                    "entity_type": "LOCK_KEY",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                return
            elif "phone" in str(execution_result).lower() or execution_result.get("code"):
                self._last_mentioned_entity = {
                    "value": "phone",
                    "intent": "DEVICE_CONTROL",
                    "entity_type": "DEVICE",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                return

        if primary_intent == "FILE_OPERATIONS":
            if execution_result.get("files"):
                self.current_state.last_search_results = execution_result["files"]
                self.current_state.last_search_results_turn = current_t
                self.current_state.last_search_results_intent = "FILE_OPERATIONS"
            target_val = execution_result.get("target") or execution_result.get("name")
            if not target_val and execution_result.get("files"):
                target_val = execution_result["files"][0].get("name")
            if target_val:
                self._last_mentioned_entity = {
                    "value": target_val,
                    "intent": "FILE_OPERATIONS",
                    "entity_type": "FILE",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                print(f"[REFERENCE_TRACKING] Stored entity: '{target_val}' (FILE) from FILE_OPERATIONS")
                return

        if primary_intent in ("OPEN_APPLICATION", "CLOSE_APPLICATION"):
            target_app = execution_result.get("app_name") or execution_result.get("target")
            if target_app and str(target_app).lower() not in ("none", ""):
                clean_app = str(target_app).strip()
                self._last_mentioned_entity = {
                    "value": clean_app,
                    "intent": primary_intent,
                    "entity_type": "APPLICATION",
                    "turn": current_t,
                    "timestamp": iso_now,
                }
                print(f"[REFERENCE_TRACKING] Stored entity: '{clean_app}' (APPLICATION) from {primary_intent}")
                return

        if self.current_state.turns:
            last_turn = self.current_state.turns[-1]
            raw_input = last_turn.user_input

            entity_value = None
            entity_type = "TARGET"

            if primary_intent in ("OPEN_APPLICATION", "CLOSE_APPLICATION"):
                m = re.search(
                    r'\b(?:open|launch|start|run|close|quit|exit|terminate|kill|bring up|'
                    r'get\s+\w+\s+running|I\s+(?:want|need)\s+(?:to\s+use\s+)?)\s+([A-Za-z0-9_\-\.]+)',
                    raw_input, re.IGNORECASE
                )
                if m:
                    entity_value = m.group(1).strip().rstrip('.')
                    entity_type = "APPLICATION"

            elif primary_intent == "FILE_OPERATIONS":
                m = re.search(
                    r'\b(?:folder|directory|file)\s+(?:named\s+|called\s+)?(.+?)(?:\s+on\s+desktop)?$',
                    raw_input, re.IGNORECASE
                )
                if m:
                    entity_value = m.group(1).strip().rstrip('.')
                    entity_type = "FOLDER"
                else:
                    m2 = re.search(
                        r'\b(?:create|make|delete|remove|find|search)\s+(?:a\s+)?(?:folder\s+|directory\s+|file\s+)?(.+)',
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
                    "turn": current_t,
                    "timestamp": iso_now,
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
                self.current_state.active_window = observations["active_window"]
            if observations.get("active_application"):
                self.current_state.active_application = observations["active_application"]
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

        # Track active applications and sites
        if primary_intent == "OPEN_APPLICATION" or "open" in str(execution_result.get("response", "")).lower():
            target = execution_result.get("target") or execution_result.get("app_name") or execution_result.get("display_name")
            if not target and self.current_state.turns:
                m_app = re.search(r'\b(?:open|launch|start|go\s+to|visit)\s+([a-zA-Z0-9_\-\s.]+)', self.current_state.turns[-1].user_input, re.IGNORECASE)
                if m_app:
                    target = m_app.group(1).strip()
            if target:
                t_low = str(target).lower().strip()
                if "youtube" in t_low:
                    self.current_state.session_context["active_site"] = "youtube"
                    self.current_state.active_application = "chrome"
                else:
                    self.current_state.active_application = t_low
                    if "chrome" in t_low or "browser" in t_low:
                        self.current_state.session_context["active_browser"] = "chrome"
            self.current_state.last_action = {
                "intent": "OPEN_APPLICATION",
                "action": "open",
                "target": target
            }

        # Track device control / hardware state
        if primary_intent == "DEVICE_CONTROL":
            if "phone" in str(execution_result).lower() or execution_result.get("code") or "phone" in str(self.current_state.turns[-1].user_input if self.current_state.turns else "").lower():
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
            if "caps" in str(execution_result).lower() or execution_result.get("key") == "Caps Lock":
                caps_state = execution_result.get("caps_lock")
                if caps_state is None:
                    caps_state = execution_result.get("state")
                if caps_state is not None:
                    self.current_state.environmental_observations["caps_lock"] = caps_state
                self.current_state.last_action = {
                    "intent": "DEVICE_CONTROL",
                    "action": execution_result.get("action", "toggle_key"),
                    "target": "Caps Lock"
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
            if self.current_state.active_application:
                ctx_type = "browser" if self.current_state.active_application in ("chrome", "edge", "firefox", "browser") else "app"
                ctx_mgr.set_active_context(ctx_type, self.current_state.active_application)
            if self.current_state.active_task:
                ctx_mgr.active_context["active_task"] = self.current_state.active_task
            if self.current_state.active_device:
                ctx_mgr.active_context["active_device"] = self.current_state.active_device
        except Exception:
            pass

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
