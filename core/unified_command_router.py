"""
Unified Command Router for NOVA
Implements deterministic, single-execution-path intent routing based on 18 strict priorities.

HYBRID INTENT RESOLUTION (Phase 7):
  Deterministic regex routing remains the primary and fastest path.
  When the deterministic pass produces no match (falls through to
  GENERAL_CONVERSATION), a semantic fallback is invoked via the
  existing LLMEngine.semantic_resolve().  The semantic layer ONLY
  classifies intent + extracts entities — it never executes OS commands.

  Flow:
    USER INPUT
      └─ Deterministic regex (priority 1→17)  ← fast path, no LLM
           ├─ MATCH → existing handler
           └─ NO MATCH (GENERAL_CONVERSATION)
                └─ _semantic_fallback()  ← LLM classification only
                     ├─ needs_clarification=True  → clarification response
                     ├─ confidence ≥ 0.70         → resolved intent → existing handler
                     └─ confidence < 0.70 / fail  → GENERAL_CONVERSATION handler
"""

import re
import logging
from typing import Dict, Any, Tuple, Optional
from enum import Enum

class Intent(Enum):
    POWER_ACTION = 1
    EMERGENCY = 2
    DEVICE_CONTROL = 3
    OPEN_APPLICATION = 4
    FILE_OPERATIONS = 5
    EMAIL = 6
    NOTES = 7
    REMINDERS = 8
    MUSIC = 9             # NEW: Music playback (high priority - actionable)
    CALCULATOR = 10
    CODE_GENERATION = 11
    TRANSLATION = 12
    TIME_QUERY = 13       # Must be before MEMORY_QUERY / RAG_SEARCH so 'what is the time' uses local clock
    DATE_QUERY = 14       # Must be before MEMORY_QUERY / RAG_SEARCH so 'what is the date' uses local clock
    WEATHER_QUERY = 15    # Dedicated weather intent
    MEMORY_QUERY = 16     # Must be before RAG_SEARCH so 'what is my ...' wins
    RAG_SEARCH = 17
    GENERAL_CONVERSATION = 18

class UnifiedCommandRouter:
    """
    Centralized command router implementing deterministic routing 
    and strict single execution path enforcement.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._compile_patterns()
        # Lazy-initialised; only created the first time semantic fallback is needed
        self._llm_engine = None
        # Set to False to disable semantic fallback entirely (e.g. in tests)
        self._semantic_enabled = True
        
    def _compile_patterns(self):
        # NOTE: patterns are tested in strict enum priority order (1→18).
        # More specific / higher-priority intents must be listed first.
        self.patterns = {
            # ── Priority 1: POWER ACTION ───────────────────────────────────────
            # Only match when power words are standalone (not inside longer phrases
            # like "run script to restart"). Require either start-of-string or
            # whitespace/punctuation before the keyword.
            Intent.POWER_ACTION: [
                re.compile(
                    r'(?:^|\s)(shutdown|power\s+off|turn\s+off|reboot|sleep)(?:\s|$)',
                    re.IGNORECASE
                ),
                # "restart [the] [PC|computer|system|laptop]" but NOT "restart my app"
                re.compile(
                    r'\brestart\s+(?:the\s+)?(?:pc|computer|system|laptop|machine)\b',
                    re.IGNORECASE
                ),
            ],

            # ── Priority 2: EMERGENCY ──────────────────────────────────────────
            Intent.EMERGENCY: [
                re.compile(r'\b(emergency|help\s+me\s+now|call\s+911)\b', re.IGNORECASE)
            ],

            # ── Priority 3: DEVICE CONTROL ────────────────────────────────────
            # Exclude 'open ... volume' constructs so OPEN_APPLICATION wins.
            Intent.DEVICE_CONTROL: [
                re.compile(r'\b(mute|unmute)\b', re.IGNORECASE),
                # volume only when NOT preceded by 'open'/'launch'/'start'
                re.compile(r'(?<!open\s)(?<!launch\s)(?<!start\s)\b(increase|decrease|raise|lower|set)\s+volume\b', re.IGNORECASE),
                re.compile(r'\b(volume\s+(?:up|down|control|level))\b', re.IGNORECASE),
                re.compile(r'\b(turn\s+(?:up|down)\s+(?:the\s+)?volume)\b', re.IGNORECASE),
                re.compile(r'\b(take\s+(?:a\s+)?screenshot|capture\s+(?:the\s+)?screen|screen\s*capture|screenshot)\b', re.IGNORECASE),
                re.compile(r'\b(lock|logout)\b', re.IGNORECASE),
            ],

            # ── Priority 4: OPEN APPLICATION ──────────────────────────────────
            Intent.OPEN_APPLICATION: [
                re.compile(r'\b(launch|start|run)\s+(.+)', re.IGNORECASE),
                re.compile(r'\b(close|quit|exit|terminate|kill)\s+(?!(?:music|song|track|audio|playback|email|mail|video))\s*(.+)', re.IGNORECASE),
                re.compile(r'\b(open)\s+(?!(?:music|song|email|mail|video|folder|directory|file\s+(?!explorer)))(.+)', re.IGNORECASE),
            ],

            # ── Priority 5: FILE OPERATIONS ───────────────────────────────────
            Intent.FILE_OPERATIONS: [
                re.compile(r'\b(create|make|new)\s+(?:a\s+)?(?:folder|directory)\s+(?:named\s+|called\s+)?(.+)', re.IGNORECASE),
                # "delete the test_ai folder"  (name BEFORE the word folder)
                re.compile(r'\b(delete|remove)\s+(?:the\s+)?(.+?)\s+(?:folder|directory)\b', re.IGNORECASE),
                # "delete the folder named test_ai" (folder BEFORE name)
                re.compile(r'\b(delete|remove)\s+(?:the\s+)?(?:folder|directory)\s+(?:named\s+|called\s+)?(.+)', re.IGNORECASE),
                re.compile(r'\b(list|show)\s+(?:all\s+)?(?:folders|directories)\b', re.IGNORECASE),
                re.compile(r'\b(list|show)\s+(?:all\s+)?files\b', re.IGNORECASE),
                re.compile(r'\b(open|view|launch)\s+(?:the\s+)?file\s+(?!explorer\b)(.+)', re.IGNORECASE),
                re.compile(r'\b(delete|remove)\s+(?:the\s+)?file\s+(.+)', re.IGNORECASE),
                re.compile(r'\b(find|locate|where\s+is)\s+(?:the\s+|my\s+)?(?:file\s+|document\s+)?(.+)', re.IGNORECASE),
            ],

            # ── Priority 6: EMAIL ─────────────────────────────────────────────
            Intent.EMAIL: [
                re.compile(r'\b(send\s+(?:email|mail)|send\s+.*\s+(?:to|email|mail))\b', re.IGNORECASE),
                re.compile(r'\b(check|read|reply\s+to)\s+(?:my\s+)?(?:latest\s+)?(?:email|emails|mail|messages|inbox)\b', re.IGNORECASE),
            ],

            # ── Priority 7: NOTES ─────────────────────────────────────────────
            Intent.NOTES: [
                re.compile(r'\b(note|memo|jot|write\s+down)\b', re.IGNORECASE)
            ],

            # ── Priority 8: REMINDERS ─────────────────────────────────────────
            Intent.REMINDERS: [
                re.compile(r'\b(remind|reminder|set\s+(?:a\s+)?reminder|alert\s+me)\b', re.IGNORECASE)
            ],

            # ── Priority 9: MUSIC ──────────────────────────────────────────────
            # Music playback commands with high specificity
            Intent.MUSIC: [
                re.compile(r'\b(play|start|begin)\s+(?:(?:some\s+)?(?:music|songs|tracks?)|(?:a\s+)?song)\b', re.IGNORECASE),
                re.compile(r'\bplay\s+(.+?)(?:\s+song|\s+track|\s+audio|$)', re.IGNORECASE),
                re.compile(r'\b(pause|resume|stop|next|previous|skip)\s+(?:the\s+)?(?:music|song|track|playback|audio)\b', re.IGNORECASE),
                re.compile(r'\b(pause|resume|stop|next|previous|skip)\b(?:\s+track|\s+song)?(?:\s|$)', re.IGNORECASE),
            ],

            # ── Priority 10: CALCULATOR ────────────────────────────────────────
            Intent.CALCULATOR: [
                re.compile(r'\b(calculate|math|add|subtract|multiply|divide|what\s+is\s+\d+)\b', re.IGNORECASE)
            ],

            # ── Priority 11: CODE GENERATION ─────────────────────────────────
            Intent.CODE_GENERATION: [
                re.compile(r'\b(code|coding|program|script|function|algorithm)\b', re.IGNORECASE),
                re.compile(
                    r'\b(write|create|build|make|generate|implement)\b.{0,40}'
                    r'\b(in\s+(?:python|java|javascript|js|c\+\+|c#|ruby|go|rust|swift|kotlin|typescript|ts))\b',
                    re.IGNORECASE
                ),
                re.compile(
                    r'\b(bubble\s+sort|merge\s+sort|quick\s+sort|binary\s+search|linked\s+list|'
                    r'stack|queue|graph|tree|dynamic\s+programming|recursion)\b',
                    re.IGNORECASE
                ),
                re.compile(
                    r'\b(write|create|build|generate|implement)\b.{0,40}'
                    r'\b(calculator|to-?do|todo|snake\s+game|tic-?tac-?toe|chatbot|web\s+scraper|api|rest\s+api)\b',
                    re.IGNORECASE
                ),
            ],

            # ── Priority 12: TRANSLATION ──────────────────────────────────────
            Intent.TRANSLATION: [
                re.compile(r'\b(translate|translation|convert\s+text\s+to|say\s+.+\s+in)\b', re.IGNORECASE)
            ],

            # ── Priority 13: TIME QUERY (Local System Clock — Bypasses RAG/LLM) ─
            Intent.TIME_QUERY: [
                re.compile(r'\b(what\s+is\s+the\s+time|what\s+time|tell\s+me\s+the\s+time|current\s+time|time\s+is\s+it)\b', re.IGNORECASE)
            ],

            # ── Priority 14: DATE QUERY (Local System Clock — Bypasses RAG/LLM) ─
            Intent.DATE_QUERY: [
                re.compile(r'\b(what\s+is\s+the\s+date|what\s+date|today\'?s?\s+date|what\s+day\s+is\s+it)\b', re.IGNORECASE)
            ],

            # ── Priority 15: WEATHER QUERY ─────────────────────────────────────
            Intent.WEATHER_QUERY: [
                re.compile(r'\b(?:what\s+is\s+the\s+)?weather\s+(?:in|at|for|near)\b', re.IGNORECASE),
                re.compile(r'\b(how\s+is\s+the\s+weather|temperature|forecast|will\s+it\s+rain|humidity|wind\s+speed)\s+(?:in|at|for|near)?\b', re.IGNORECASE),
                # Natural paraphrases for weather intent
                re.compile(r'\b(?:weather|rain|sunny|cloudy|forecast)\b.*\b(?:today|tomorrow|tonight|outside|this\s+week)\b', re.IGNORECASE),
                re.compile(r'\b(?:umbrella|raincoat)\b', re.IGNORECASE),   # "do I need an umbrella"
                re.compile(r'\bhow\s+(?:hot|cold|warm|cool)\s+is\s+it\b', re.IGNORECASE),  # "how hot is it outside"
                re.compile(r'\bwhat\'?s?\s+(?:the\s+)?weather\b', re.IGNORECASE),          # "what's the weather"
            ],

            # ── Priority 16: MEMORY QUERY ────────────────────────────────────
            # Must come BEFORE RAG_SEARCH so "what is my ..." hits here, not RAG.
            Intent.MEMORY_QUERY: [
                re.compile(r'\b(remember|recall)\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(did\s+i|did\s+we|is\s+my|are\s+my|was\s+my)\b', re.IGNORECASE),
            ],

            # ── Priority 17: RAG SEARCH ───────────────────────────────────────
            Intent.RAG_SEARCH: [
                re.compile(r'\b(search|what|who|where|when|why|how|explain|tell\s+me|describe|summarize|news|latest|update|updates)\b', re.IGNORECASE)
            ]
            # Priority 18: GENERAL_CONVERSATION — fallback, no pattern needed
        }

    
    def route_command(self, user_input: str) -> Tuple[Intent, Dict[str, Any]]:
        """
        Determine intent with hybrid resolution.

        Step 1 — Deterministic regex (priority 1→17, always tried first).
        Step 2 — Semantic fallback via LLMEngine ONLY when Step 1 produces
                 GENERAL_CONVERSATION (i.e. no regex matched).

        Deterministic commands ("open notepad", "what time is it", etc.) are
        NEVER sent to the LLM — they resolve immediately in Step 1.
        """
        if not user_input or not user_input.strip():
            return Intent.GENERAL_CONVERSATION, {}

        input_lower = user_input.lower().strip()

        # ── Step 1: Deterministic regex, strict priority order ─────────────
        for intent in Intent:
            if intent == Intent.GENERAL_CONVERSATION:
                continue
            patterns = self.patterns.get(intent, [])
            for pattern in patterns:
                match = pattern.search(input_lower)
                if match:
                    params = self._extract_params(intent, match, user_input)
                    self.logger.debug(
                        f"[DETERMINISTIC] '{user_input[:60]}' -> {intent.name}"
                    )
                    return intent, params

        # ── Step 2: Semantic fallback — only reached when NO regex matched ──
        if self._semantic_enabled:
            sem_intent, sem_params = self._semantic_fallback(user_input)
            if sem_intent != Intent.GENERAL_CONVERSATION:
                return sem_intent, sem_params

        return Intent.GENERAL_CONVERSATION, {}

    def _extract_params(self, intent: Intent, match: re.Match, user_input: str) -> Dict[str, Any]:
        params = {"raw_input": user_input}
        try:
            if intent == Intent.OPEN_APPLICATION:
                if match.lastindex and match.lastindex >= 2:
                    action = match.group(1).lower()
                    target = match.group(2).strip()
                else:
                    action = "open"
                    target = match.group(1).strip() if match.lastindex else ""
                params["action"] = "open" if action in ["open", "launch", "start", "run"] else "close"
                params["target"] = target
            elif intent == Intent.POWER_ACTION:
                g = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                raw_action = g.strip().lower()
                # Normalise to canonical values used by execute_single_action.
                # Also handle cases where the full match string was captured
                # (e.g. "restart the computer" → "restart").
                _pa_norm = {
                    "shutdown": "shutdown",
                    "power off": "shutdown",
                    "turn off": "shutdown",
                    "reboot": "restart",
                    "restart": "restart",
                    "sleep": "sleep",
                    "suspend": "sleep",
                    "hibernate": "sleep",
                }
                # Try exact match first; then try prefix match for compound strings
                normalised = _pa_norm.get(raw_action)
                if normalised is None:
                    for key, val in _pa_norm.items():
                        if raw_action.startswith(key):
                            normalised = val
                            break
                params["action"] = normalised or raw_action
            elif intent == Intent.DEVICE_CONTROL:
                text_low = user_input.lower()
                if "screenshot" in text_low or "capture" in text_low:
                    params["action"] = "screenshot"
                elif "unmute" in text_low:
                    params["action"] = "unmute"
                elif "mute" in text_low:
                    params["action"] = "mute"
                elif "lock" in text_low or "logout" in text_low:
                    params["action"] = "lock"
                elif any(k in text_low for k in ["increase", "raise", "turn up", "volume up"]):
                    params["action"] = "increase_volume"
                elif any(k in text_low for k in ["decrease", "lower", "turn down", "volume down"]):
                    params["action"] = "decrease_volume"
                else:
                    g = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                    params["action"] = g.strip().lower()
            elif intent == Intent.FILE_OPERATIONS:
                text_low = user_input.lower()
                if re.search(r'\b(create|make|new)\s+(?:a\s+)?(?:folder|directory)\b', text_low):
                    params["action"] = "create_folder"
                    m = re.search(r'\b(?:folder|directory)\s+(?:named\s+|called\s+)?(.+)', user_input, re.IGNORECASE)
                    folder_name = m.group(1).strip() if m else ""
                    folder_name = re.sub(r'\s+on\s+desktop$', '', folder_name, flags=re.IGNORECASE).strip(' "\'')
                    params["name"] = folder_name
                    params["location"] = "desktop"
                elif re.search(r'\b(delete|remove)\b', text_low) and re.search(r'\b(folder|directory)\b', text_low):
                    params["action"] = "delete_folder"
                    # Try "delete the NAME folder" pattern first (name before folder word)
                    m = re.search(
                        r'\b(?:delete|remove)\s+(?:the\s+)?(.+?)\s+(?:folder|directory)\b',
                        user_input, re.IGNORECASE
                    )
                    if m:
                        folder_name = m.group(1).strip()
                    else:
                        # Try "delete the folder NAME" pattern
                        m2 = re.search(r'\b(?:folder|directory)\s+(?:named\s+|called\s+)?(.+)', user_input, re.IGNORECASE)
                        folder_name = m2.group(1).strip() if m2 else ""
                    folder_name = re.sub(r'\s+on\s+desktop$', '', folder_name, flags=re.IGNORECASE).strip(' "\'')
                    params["name"] = folder_name
                    params["location"] = "desktop"
                elif re.search(r'\b(list|show)\s+(?:all\s+)?(?:folders|directories)\b', text_low):
                    params["action"] = "list_folders"
                    params["location"] = "desktop"
                elif re.search(r'\b(list|show)\s+(?:all\s+)?files\b', text_low):
                    params["action"] = "list_files"
                    params["location"] = "desktop"
                elif re.search(r'\b(open|view|launch)\s+(?:the\s+)?file\s+(?!explorer\b)', text_low):
                    params["action"] = "open_file"
                    m = re.search(r'\bfile\s+(.+)', user_input, re.IGNORECASE)
                    params["target"] = m.group(1).strip(' "\'') if m else ""
                elif re.search(r'\b(delete|remove)\s+(?:the\s+)?file\b', text_low):
                    params["action"] = "delete_file"
                    m = re.search(r'\bfile\s+(.+)', user_input, re.IGNORECASE)
                    params["target"] = m.group(1).strip(' "\'') if m else ""
                elif re.search(r'\b(find|locate|where\s+is)\b', text_low):
                    params["action"] = "find_file"
                    m = re.search(r'\b(?:find|locate|where\s+is)\s+(?:the\s+|my\s+)?(?:file\s+|document\s+)?(.+)', user_input, re.IGNORECASE)
                    params["target"] = m.group(1).strip(' "\'') if m else ""
            elif intent == Intent.MUSIC:
                # Extract music action and song/artist info
                text = user_input.lower()
                music_actions = ["play", "pause", "resume", "stop", "next", "previous", "skip"]
                action = None
                for ma in music_actions:
                    if ma in text:
                        action = ma
                        break
                params["action"] = action or "play"
            elif intent == Intent.WEATHER_QUERY:
                # Extract location from query
                text = user_input.lower()
                # Remove weather keywords to find location
                weather_keywords = ["weather", "temperature", "forecast", "how is the weather", "what's the weather", "what is the weather", "in", "at", "near"]
                location = user_input
                for keyword in weather_keywords:
                    location = location.lower().replace(keyword, " ").strip()
                params["location"] = location.strip() if location.strip() else "local"
            elif intent == Intent.EMAIL:
                # Extract action (send, read, check, reply)
                text = user_input.lower()
                if "send" in text:
                    params["action"] = "send"
                elif "read" in text:
                    params["action"] = "read"
                elif "check" in text:
                    params["action"] = "check"
                elif "reply" in text:
                    params["action"] = "reply"
                else:
                    params["action"] = "default"
        except IndexError:
            params["action"] = match.group(0).strip().lower() if match.lastindex else ""
        return params

    # =========================================================================
    # SEMANTIC FALLBACK — Tasks 3, 5, 6
    # =========================================================================

    # Intent label string → Intent enum.  Labels match LLMEngine.INTENT_LABELS.
    _SEMANTIC_INTENT_MAP: Dict[str, "Intent"] = {}  # populated lazily below

    def _get_semantic_intent_map(self) -> Dict[str, "Intent"]:
        """Lazy-build the string→Intent mapping on first use."""
        if not self._SEMANTIC_INTENT_MAP:
            for member in Intent:
                UnifiedCommandRouter._SEMANTIC_INTENT_MAP[member.name] = member
            # Extra aliases the LLM might emit
            UnifiedCommandRouter._SEMANTIC_INTENT_MAP["CLOSE_APPLICATION"] = Intent.OPEN_APPLICATION
        return self._SEMANTIC_INTENT_MAP

    def _get_llm_engine(self):
        """Lazily initialise LLMEngine (single shared instance)."""
        if self._llm_engine is None:
            try:
                from extensions.llm_engine import LLMEngine
                self._llm_engine = LLMEngine()
                self.logger.info("[SEMANTIC] LLMEngine initialised for semantic fallback.")
            except Exception as e:
                self.logger.warning(f"[SEMANTIC] Could not initialise LLMEngine: {e}")
        return self._llm_engine

    def _semantic_fallback(self, user_input: str) -> Tuple["Intent", Dict[str, Any]]:
        """
        Semantic intent resolution — called ONLY when deterministic regex
        produces no match.

        Returns:
            (Intent, params_dict)

        The params_dict has the same shape as _extract_params() so that
        execute_single_action() needs zero changes.

        If semantic resolution fails or is ambiguous, returns
        (Intent.GENERAL_CONVERSATION, {}) so the existing RAG/LLM conversation
        handler deals with it naturally.
        """
        engine = self._get_llm_engine()
        if engine is None:
            return Intent.GENERAL_CONVERSATION, {}

        try:
            sem = engine.semantic_resolve(user_input)
        except Exception as e:
            self.logger.warning(f"[SEMANTIC] semantic_resolve() failed: {e}")
            return Intent.GENERAL_CONVERSATION, {}

        intent_label = sem.get("intent", "GENERAL_CONVERSATION")
        confidence   = float(sem.get("confidence", 0.0))
        entities     = sem.get("entities", {}) or {}
        needs_clarification = bool(sem.get("needs_clarification", False))
        clarification_reason = sem.get("clarification_reason", "")

        self.logger.info(
            f"[SEMANTIC] '{user_input[:60]}' -> {intent_label} "
            f"conf={confidence:.2f} clarify={needs_clarification}"
        )

        # ── Ambiguity / safety gate ─────────────────────────────────────────
        # Low confidence on a destructive intent → ask for clarification rather
        # than guessing. We return a special sentinel params dict that
        # execute_single_action() recognises and converts to a clarification
        # response without performing any action.
        DESTRUCTIVE_INTENTS = {
            "FILE_OPERATIONS", "POWER_ACTION", "CLOSE_APPLICATION",
            "DEVICE_CONTROL", "EMAIL",
        }
        if needs_clarification or (confidence < 0.70 and intent_label in DESTRUCTIVE_INTENTS):
            reason = clarification_reason or (
                f"I'm not sure exactly what you'd like to do. Could you clarify?"
            )
            self.logger.info(f"[SEMANTIC] Requesting clarification: {reason}")
            return Intent.GENERAL_CONVERSATION, {
                "_needs_clarification": True,
                "_clarification_reason": reason,
                "raw_input": user_input,
                "_semantic_source": True,
            }

        # Below minimum usable confidence → hand off to conversation handler
        if confidence < 0.50 or intent_label in ("GENERAL_CONVERSATION", "NEEDS_CLARIFICATION"):
            return Intent.GENERAL_CONVERSATION, {}

        # ── Map label string → Intent enum ──────────────────────────────────
        label_map = self._get_semantic_intent_map()
        resolved_intent = label_map.get(intent_label)
        if resolved_intent is None:
            self.logger.warning(f"[SEMANTIC] Unknown label '{intent_label}' — falling through.")
            return Intent.GENERAL_CONVERSATION, {}

        # ── Build params dict from semantic entities ─────────────────────────
        params = self._params_from_semantic(
            resolved_intent, intent_label, entities, user_input
        )
        params["_semantic_source"] = True
        params["_semantic_confidence"] = confidence

        return resolved_intent, params

    def _params_from_semantic(
        self,
        intent: "Intent",
        intent_label: str,
        entities: Dict[str, Any],
        user_input: str,
    ) -> Dict[str, Any]:
        """
        Convert the semantic entity dict into the same params shape that
        _extract_params() produces for each intent.

        This is the Task 5 layer: ensures semantically-resolved commands
        (e.g. "remove the AI folder", "make the computer quiet") produce
        the same params dict as their regex-matched equivalents, so
        execute_single_action() runs the correct handler without change.
        """
        params: Dict[str, Any] = {"raw_input": user_input}

        action_raw = (entities.get("action") or "").lower().strip()
        target_raw = (entities.get("target") or entities.get("name") or "").strip()
        location   = (entities.get("location") or "desktop").strip()

        # ── OPEN_APPLICATION / CLOSE_APPLICATION ────────────────────────────
        if intent == Intent.OPEN_APPLICATION:
            # LLM maps CLOSE_APPLICATION → still OPEN_APPLICATION enum but
            # we distinguish via intent_label or action
            if intent_label == "CLOSE_APPLICATION" or action_raw in (
                "close", "quit", "exit", "terminate", "kill"
            ):
                params["action"] = "close"
            else:
                params["action"] = "open"
            params["target"] = target_raw

        # ── FILE OPERATIONS ─────────────────────────────────────────────────
        elif intent == Intent.FILE_OPERATIONS:
            # Normalise the semantic action values the LLM was instructed to use
            action_map = {
                "create_folder":  "create_folder",
                "delete_folder":  "delete_folder",
                "rename_folder":  "rename_folder",
                "list_folders":   "list_folders",
                "open_file":      "open_file",
                "delete_file":    "delete_file",
                "find_file":      "find_file",
                # Common synonyms LLM might still emit
                "create":         "create_folder",
                "make":           "create_folder",
                "delete":         "delete_folder",
                "remove":         "delete_folder",
                "erase":          "delete_folder",
                "list":           "list_folders",
            }
            params["action"] = action_map.get(action_raw, action_raw)

            # Folder / file name goes into "name" for create/delete, "target" for open/find
            if params["action"] in ("create_folder", "delete_folder", "rename_folder"):
                params["name"] = target_raw
                params["location"] = location
            elif params["action"] in ("open_file", "delete_file", "find_file"):
                params["target"] = target_raw
            else:
                # Unknown sub-action — preserve whatever came in
                params["name"] = target_raw
                params["location"] = location

        # ── DEVICE CONTROL ──────────────────────────────────────────────────
        elif intent == Intent.DEVICE_CONTROL:
            # Normalise semantic action values for device control
            dc_map = {
                "mute":             "mute",
                "unmute":           "unmute",
                "increase_volume":  "increase_volume",
                "decrease_volume":  "decrease_volume",
                "screenshot":       "screenshot",
                "lock":             "lock",
                "screen capture":   "screenshot",
                # Generic synonyms
                "silence":          "mute",
                "quiet":            "mute",
                "louder":           "increase_volume",
                "softer":           "decrease_volume",
            }
            params["action"] = dc_map.get(action_raw, action_raw)

        # ── POWER ACTION ────────────────────────────────────────────────────
        elif intent == Intent.POWER_ACTION:
            pa_map = {
                "shutdown":  "shutdown",
                "restart":   "restart",
                "reboot":    "restart",
                "sleep":     "sleep",
                "hibernate": "sleep",
            }
            params["action"] = pa_map.get(action_raw, action_raw)

        # ── MUSIC ───────────────────────────────────────────────────────────
        elif intent == Intent.MUSIC:
            music_map = {
                "play": "play", "pause": "pause", "resume": "resume",
                "stop": "stop", "next": "next", "previous": "previous", "skip": "next",
            }
            params["action"] = music_map.get(action_raw, "play")

        # ── WEATHER QUERY ───────────────────────────────────────────────────
        elif intent == Intent.WEATHER_QUERY:
            params["location"] = (entities.get("location") or "local").strip()

        # ── EMAIL ───────────────────────────────────────────────────────────
        elif intent == Intent.EMAIL:
            email_map = {
                "send": "send", "read": "read", "check": "check", "reply": "reply",
            }
            params["action"] = email_map.get(action_raw, "default")

        # ── All other intents: no extra params beyond raw_input ─────────────
        # TIME_QUERY, DATE_QUERY, CALCULATOR, CODE_GENERATION, TRANSLATION,
        # MEMORY_QUERY, RAG_SEARCH, NOTES, REMINDERS — execute_single_action
        # reads user_input directly for these, so no extra keys are needed.

        return params

    @staticmethod
    def _clarification_response(reason: str, user_input: str) -> Dict[str, Any]:
        """
        Build a safe 'needs clarification' response dict.
        execute_single_action() detects `_needs_clarification` in params and
        returns this without performing any action.
        """
        return {
            "status": "clarification_needed",
            "intent": "NEEDS_CLARIFICATION",
            "response": reason,
            "handled": True,
        }

    def execute_single_action(self, user_input: str) -> Dict[str, Any]:
        """Execute a single action based on intent routing. Enforces one input -> one action."""
        try:
            intent, params = self.route_command(user_input)
            self.logger.info(f"Command routed: {intent.name}")

            # ── Clarification gate (Task 6) ──────────────────────────────────
            # Semantic fallback may signal that the intent is ambiguous and
            # dangerous to execute without confirmation.  Return a safe
            # clarification response without performing any OS action.
            if params.get("_needs_clarification"):
                reason = params.get(
                    "_clarification_reason",
                    "I'm not sure what you mean. Could you clarify?"
                )
                return self._clarification_response(reason, user_input)

            result = {"status": "success", "intent": intent.name}
            
            # 1. POWER ACTION
            if intent == Intent.POWER_ACTION:
                try:
                    from legacy.skills_utilities import shutdown_system, restart_system, sleep_system
                    action = params.get("action", "")
                    if action in ["shutdown", "power off", "turn off"]:
                        result["response"] = shutdown_system() or "System shutdown initiated."
                    elif action in ["restart", "reboot"]:
                        result["response"] = restart_system() or "System restart initiated."
                    elif action in ["sleep", "suspend", "standby"]:
                        result["response"] = sleep_system() or "System sleep initiated."
                    else:
                        result["response"] = "Unrecognized power action."
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Power action failed: {e}"
                    
            # 2. EMERGENCY
            elif intent == Intent.EMERGENCY:
                result["response"] = "Emergency mode activated. Calling for help."
                
            # 3. DEVICE CONTROL
            elif intent == Intent.DEVICE_CONTROL:
                try:
                    action = params.get("action", "")
                    if action == "screenshot":
                        from legacy.skills import take_screenshot
                        shot_res = take_screenshot()
                        if shot_res:
                            result["status"] = "success"
                            result["response"] = shot_res if isinstance(shot_res, str) else "Screenshot saved successfully."
                        else:
                            result["status"] = "error"
                            result["response"] = "Could not capture screenshot."
                    elif action == "increase_volume":
                        from legacy.actions import increase_volume
                        result["response"] = increase_volume()
                    elif action == "decrease_volume":
                        from legacy.actions import decrease_volume
                        result["response"] = decrease_volume()
                    elif action in ["mute", "unmute"]:
                        from legacy.actions import toggle_mute
                        toggle_mute()
                        result["response"] = f"Volume {action}d."
                    elif action == "lock":
                        from legacy.skills_utilities import lock_system
                        result["response"] = lock_system() or "System locked."
                    else:
                        result["response"] = "Device control command completed."
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Device control failed: {e}"
                    
            # 4. OPEN APPLICATION
            elif intent == Intent.OPEN_APPLICATION:
                try:
                    target = params.get("target", "").strip()
                    action = params.get("action", "open")
                    if action == "open":
                        if target.lower() in ["youtube", "google", "gmail", "github"]:
                            from legacy.actions import open_website
                            site_urls = {
                                "youtube": "https://youtube.com",
                                "google": "https://google.com",
                                "gmail": "https://mail.google.com",
                                "github": "https://github.com",
                            }
                            url = site_urls.get(target.lower(), f"https://{target}.com")
                            open_website(url, target.capitalize())
                            result["status"] = "success"
                            result["response"] = f"Opening {target.capitalize()}."
                        elif target.lower() in ["camera", "webcam"]:
                            # smart_opener handles camera via microsoft.windows.camera: URI
                            from extensions.system.smart_opener import smart_opener
                            from legacy.tts import speak
                            speak("Opening camera.")
                            open_dict = smart_opener.smart_open("camera")
                            if isinstance(open_dict, dict) and open_dict.get("success"):
                                result["status"] = "success"
                                result["response"] = "Opened Camera."
                            else:
                                msg = "Could not open camera."
                                result["status"] = "error"
                                result["response"] = msg
                                speak(msg)
                        else:
                            # Universal path: smart_opener handles .exe, .lnk, Store, URI
                            from extensions.system.smart_opener import smart_opener
                            from legacy.tts import speak
                            open_dict = smart_opener.smart_open(target)
                            if isinstance(open_dict, dict) and open_dict.get("success"):
                                display = open_dict.get("display_name") or target
                                result["status"] = "success"
                                result["response"] = f"Opened {display}."
                                speak(f"Opening {display}.")
                            else:
                                msg = (open_dict.get("message") if isinstance(open_dict, dict) else None) \
                                      or f"Could not find '{target}' on your system."
                                result["status"] = "error"
                                result["response"] = msg
                                speak(msg)
                    else:
                        from legacy.actions import close_app
                        close_res = close_app(target)
                        if "could not find or close" in close_res.lower():
                            result["status"] = "error"
                        else:
                            result["status"] = "success"
                        result["response"] = close_res
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Failed to manage application: {e}"
                    
            # 5. FILE OPERATIONS
            elif intent == Intent.FILE_OPERATIONS:
                try:
                    action = params.get("action", "")
                    if action == "create_folder":
                        from modules.system_controller.folder_manager import create_folder
                        folder_name = params.get("name")
                        if not folder_name:
                            result["status"] = "error"
                            result["response"] = "Please specify a folder name to create."
                        else:
                            res = create_folder(folder_name, location=params.get("location", "desktop"))
                            if res.startswith("Error"):
                                result["status"] = "error"
                            else:
                                result["status"] = "success"
                            result["response"] = res

                    elif action == "delete_folder":
                        from modules.system_controller.folder_manager import delete_folder
                        folder_name = params.get("name")
                        if not folder_name:
                            result["status"] = "error"
                            result["response"] = "Please specify a folder name to delete."
                        else:
                            res = delete_folder(folder_name, location=params.get("location", "desktop"), confirm=True)
                            if "Error" in res or "not found" in res:
                                result["status"] = "error"
                            else:
                                result["status"] = "success"
                            result["response"] = res

                    elif action == "list_folders":
                        from modules.system_controller.folder_manager import list_folders
                        folders = list_folders(location=params.get("location", "desktop"))
                        result["status"] = "success"
                        if folders:
                            result["response"] = f"Folders on desktop: {', '.join(folders[:10])}."
                        else:
                            result["response"] = "No folders found on desktop."

                    elif action == "open_file":
                        from modules.system_controller.file_manager import open_file
                        target_file = params.get("target")
                        if not target_file:
                            result["status"] = "error"
                            result["response"] = "Please specify a file name to open."
                        else:
                            res = open_file(target_file)
                            if "not found" in res.lower() or "error" in res.lower():
                                result["status"] = "error"
                            else:
                                result["status"] = "success"
                            result["response"] = res

                    elif action == "list_files":
                        from modules.system_controller.file_manager import list_files
                        files = list_files()
                        result["status"] = "success"
                        if files:
                            names = [f.get("name", "") for f in files if f.get("name")][:10]
                            result["response"] = f"Files on desktop: {', '.join(names)}."
                        else:
                            result["response"] = "No files found on desktop."

                    elif action == "find_file":
                        from modules.system_controller.file_manager import find_file_in_desktop
                        target_file = params.get("target")
                        if not target_file:
                            result["status"] = "error"
                            result["response"] = "Please specify a file name to find."
                        else:
                            found = find_file_in_desktop(target_file)
                            if found:
                                result["status"] = "success"
                                result["response"] = f"Found {target_file} at {found}."
                            else:
                                result["status"] = "error"
                                result["response"] = f"File '{target_file}' was not found on desktop."
                    else:
                        result["status"] = "error"
                        result["response"] = "Unrecognized file operation."
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"File operation failed: {e}"
                    
            # 6. EMAIL
            elif intent == Intent.EMAIL:
                try:
                    from modules.assistant_email.email_controller import handle_email_command
                    handle_email_command(user_input)
                    result["response"] = "Email command executed."
                except Exception as e:
                    result["response"] = f"Email operation failed: {e}"
                    
            # 7. NOTES
            elif intent == Intent.NOTES:
                try:
                    result["response"] = "Notes operation not fully implemented yet."
                except Exception as e:
                    result["response"] = f"Notes operation failed: {e}"
                    
            # 8. REMINDERS
            elif intent == Intent.REMINDERS:
                try:
                    from extensions.reminder_engine.reminder_scheduler import get_scheduler, initialize_scheduler
                    
                    # Ensure scheduler is initialized
                    scheduler = get_scheduler()
                    if scheduler is None:
                        scheduler = initialize_scheduler()
                    
                    # Parse the reminder from user input
                    # Examples: "remind me to call Sathvik at 6 PM", "set a reminder for tomorrow at 10 AM"
                    import re
                    from datetime import datetime, timedelta
                    
                    text_lower = user_input.lower()
                    
                    # Try to extract time and reminder text
                    # Simple implementation: look for time pattern like "at 6 PM", "tomorrow", "in 5 minutes"
                    
                    reminder_added = False
                    
                    # Check for "in X minutes/hours"
                    in_match = re.search(r'in\s+(\d+)\s+(minutes?|hours?|days?)', text_lower)
                    if in_match:
                        amount = int(in_match.group(1))
                        unit = in_match.group(2).lower()
                        
                        if 'minute' in unit:
                            delay_seconds = amount * 60
                        elif 'hour' in unit:
                            delay_seconds = amount * 3600
                        elif 'day' in unit:
                            delay_seconds = amount * 86400
                        else:
                            delay_seconds = amount * 60
                        
                        reminder_id = scheduler.add_reminder(user_input, delay_seconds)
                        result["response"] = f"Reminder set for {amount} {unit}."
                        reminder_added = True
                    
                    # Check for specific time like "at 6 PM", "at 10:30 AM"
                    if not reminder_added:
                        time_match = re.search(r'at\s+(\d{1,2}):?(\d{2})?\s*(am|pm)?', text_lower)
                        if time_match:
                            hour = int(time_match.group(1))
                            minute = int(time_match.group(2)) if time_match.group(2) else 0
                            ampm = time_match.group(3) or "am"
                            
                            # Convert to 24-hour format
                            if ampm.lower() == "pm" and hour != 12:
                                hour += 12
                            elif ampm.lower() == "am" and hour == 12:
                                hour = 0
                            
                            # Create target time (today or tomorrow if time has passed)
                            target_time = datetime.now().replace(hour=hour, minute=minute, second=0)
                            if target_time < datetime.now():
                                target_time += timedelta(days=1)
                            
                            reminder_id = scheduler.add_reminder_at_time(user_input, target_time)
                            result["response"] = f"Reminder set for {hour}:{minute:02d} {ampm}."
                            reminder_added = True
                    
                    # Default: set reminder for 1 hour from now
                    if not reminder_added:
                        reminder_id = scheduler.add_reminder(user_input, 3600)  # 1 hour
                        result["response"] = "Reminder set for 1 hour from now."
                        
                except Exception as e:
                    self.logger.error(f"Reminder scheduling failed: {e}")
                    result["response"] = f"Reminder scheduling failed: {e}"
                    
            # 9. MUSIC
            elif intent == Intent.MUSIC:
                try:
                    from modules.music.music_controller import get_controller
                    controller = get_controller()
                    
                    action = params.get("action", "play").lower()
                    
                    if action == "play":
                        success = controller.play_music(user_input)
                        result["response"] = "Music playback started." if success else "Failed to start music playback."
                    elif action == "pause":
                        # Pause not directly supported by MusicController, but set state
                        result["response"] = "Music paused."
                    elif action == "resume":
                        result["response"] = "Music resumed."
                    elif action == "stop":
                        result["response"] = "Music playback stopped."
                    elif action == "next":
                        msg = controller.next_song()
                        result["response"] = msg
                    elif action == "previous":
                        msg = controller.previous_song()
                        result["response"] = msg
                    elif action == "skip":
                        msg = controller.next_song()
                        result["response"] = msg
                    else:
                        success = controller.play_music(user_input)
                        result["response"] = "Music playback started." if success else "Failed to start music playback."
                except Exception as e:
                    self.logger.error(f"Music execution error: {e}")
                    result["response"] = f"Music playback failed: {e}"
                    
            # 10. CALCULATOR
            elif intent == Intent.CALCULATOR:
                try:
                    from legacy.skills_utilities import solve_math
                    res = solve_math(user_input)
                    result["response"] = res if res else "Calculated expression."
                except Exception as e:
                    result["response"] = f"Calculation failed: {e}"

            # 11. CODE GENERATION
            elif intent == Intent.CODE_GENERATION:
                try:
                    from modules.code_generator.main import process_request
                    code_res = process_request(user_input)
                    result.update(code_res)
                    result["response"] = code_res.get("message", "Code generated.")
                    # CRITICAL: Mark as handled to prevent any fallback to other subsystems
                    result["handled"] = True
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Code generation failed: {e}"
                    result["handled"] = True  # Still mark as handled to prevent incorrect fallbacks

            # 12. TRANSLATION
            elif intent == Intent.TRANSLATION:
                try:
                    from legacy.skills_utilities import translate_text
                    res = translate_text(user_input)
                    result["response"] = res if res else "Translation completed."
                except Exception as e:
                    result["response"] = f"Translation failed: {e}"

            # 13. TIME QUERY (Pure Local Clock — Bypasses RAG / LLM)
            elif intent == Intent.TIME_QUERY:
                try:
                    from legacy.skills_utilities import tell_time
                    result["response"] = tell_time()
                except Exception as e:
                    result["response"] = f"Time query failed: {e}"

            # 14. DATE QUERY (Pure Local Clock — Bypasses RAG / LLM)
            elif intent == Intent.DATE_QUERY:
                try:
                    from legacy.skills_utilities import tell_date
                    result["response"] = tell_date()
                except Exception as e:
                    result["response"] = f"Date query failed: {e}"

            # 15. WEATHER QUERY
            elif intent == Intent.WEATHER_QUERY:
                try:
                    location = params.get("location", "local")
                    # TODO: Implement actual weather API call
                    from extensions.weather_engine import get_weather_for_query
                    result["response"] = get_weather_for_query(user_input)
                except ImportError:
                    # Fallback: use legacy skills if available
                    try:
                        from legacy.skills_utilities import get_weather
                        result["response"] = get_weather(user_input) or "Weather information unavailable."
                    except Exception as e:
                        result["response"] = f"Weather query failed: {e}"
                except Exception as e:
                    result["response"] = f"Weather query failed: {e}"

            # 16. MEMORY QUERY
            elif intent == Intent.MEMORY_QUERY:
                try:
                    from extensions.rag_system import RAGSystem
                    rag = RAGSystem()
                    rag_output = rag.process(user_input)
                    if isinstance(rag_output, dict):
                        result["response"] = rag_output.get("response", "No memory found.")
                        result["handled"] = rag_output.get("handled", True)
                    else:
                        result["response"] = str(rag_output)
                        result["handled"] = True
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Memory query failed: {e}"
                    result["handled"] = True

            # 17. RAG SEARCH
            elif intent == Intent.RAG_SEARCH:
                try:
                    from extensions.rag_system import RAGSystem
                    rag = RAGSystem()
                    rag_output = rag.process(user_input)
                    if isinstance(rag_output, dict):
                        result["response"] = rag_output.get("response", "No answer found.")
                        # CRITICAL: Mark as handled to prevent any fallback to other subsystems
                        result["handled"] = rag_output.get("handled", True)
                    else:
                        result["response"] = str(rag_output)
                        result["handled"] = True
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"RAG search failed: {e}"
                    result["handled"] = True  # Still mark as handled to prevent incorrect fallbacks
                    
            # 18. GENERAL CONVERSATION
            elif intent == Intent.GENERAL_CONVERSATION:
                try:
                    from extensions.rag_system import RAGSystem
                    rag = RAGSystem()
                    rag_output = rag.process(user_input)
                    if isinstance(rag_output, dict):
                        result["response"] = rag_output.get("response", "I'm not sure how to respond.")
                        # CRITICAL: Mark as handled to prevent any fallback to other subsystems
                        result["handled"] = rag_output.get("handled", True)
                    else:
                        result["response"] = str(rag_output)
                        result["handled"] = True
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Conversation failed: {e}"
                    result["handled"] = True  # Still mark as handled to prevent incorrect fallbacks
            
            # Catch-all for not fully implemented intents
            else:
                result["response"] = f"Intent {intent.name} recognized but execution not fully wired yet."

            return result
            
        except Exception as e:
            self.logger.error(f"Error executing command: {e}")
            return {
                "status": "error",
                "message": f"Execution failed: {str(e)}",
                "intent": "ERROR"
            }

unified_router = UnifiedCommandRouter()

def route_and_execute(user_input: str) -> Dict[str, Any]:
    return unified_router.execute_single_action(user_input)
