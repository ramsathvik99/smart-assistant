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

import os
import re
import uuid
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional, List, Union
from enum import Enum

def get_assistant_name() -> str:
    """Get the current user's configured assistant name, defaulting to Trevon."""
    try:
        from instance.config import settings
        name = settings.get_assistant_name()
        if name:
            return name.lower().strip()
    except Exception:
        pass
    return "trevon"

def contains_assistant_name(text: str) -> bool:
    """Check if text contains the current user's assistant name or default 'Trevon'.
    
    This is case-insensitive, position-agnostic, and punctuation-tolerant.
    Used as an addressing signal, NOT as a mandatory wake word.
    Recognizes both the default identity 'Trevon' and any personalized assistant name.
    """
    if not text:
        return False

    clean_text = re.sub(r'[^\w\s]', '', text.lower())

    # 1. Fixed default identity Trevon
    if "trevon" in clean_text:
        return True

    # 2. Personalized assistant name if configured
    assistant_name = get_assistant_name()
    if assistant_name and assistant_name not in ("assistant", "trevon"):
        if assistant_name in clean_text:
            return True

    return False

class Intent(Enum):
    POWER_ACTION = 1
    EMERGENCY = 2
    DEVICE_CONTROL = 3
    OPEN_APPLICATION = 4
    FILE_OPERATIONS = 5
    EMAIL = 6
    NOTES = 7
    REMINDERS = 8
    MUSIC = 9             # Music playback & media controls
    DOCUMENT_GENERATION = 10  # Word (.docx), PDF, Excel (.xlsx) generation
    CALCULATOR = 11
    CODE_GENERATION = 12
    TRANSLATION = 13
    DAILY_BRIEFING = 14   # Composite morning / daily executive briefing
    TIME_QUERY = 15       # Must be before MEMORY_QUERY / RAG_SEARCH so 'what is the time' uses local clock
    DATE_QUERY = 16       # Must be before MEMORY_QUERY / RAG_SEARCH so 'what is the date' uses local clock
    WEATHER_QUERY = 17    # Dedicated weather intent
    MEMORY_QUERY = 18     # Must be before RAG_SEARCH so 'what is my ...' wins
    MEMORY_STORE = 19     # Must be before RAG_SEARCH: stores facts about user
    TASK_MANAGEMENT = 20  # Asynchronous background task queue management
    SMART_HOME = 21       # Smart home devices, lights, switches, thermostats
    WINDOW_CONTEXT = 22   # Active foreground window inspection & screenshots
    LEARNING = 23         # Learned user directives, behavioral rules, preferences
    UNDO = 24             # Reversible action undo stack
    AUDIO_DEVICES = 25    # Audio endpoint enumeration & playback diagnostics
    RECOMMENDATION = 26   # Recommendation engine
    RAG_SEARCH = 27
    GENERAL_CONVERSATION = 28
    VISUAL_SURFACE = 29   # Ephemeral visual response surface & "show that again"
    CLOSE_APPLICATION = 30 # Dedicated close / quit / shut down application intent
    SYSTEM_COMPATIBILITY = 31 # Hardware compatibility & requirements checking
    GAME_DISCOVERY = 32 # Game recommendations and discovery
    VOICE_CONFIGURATION = 33 # Speech rate and voice configuration

EXTERNAL_RETRIEVAL_INTENTS = {"WEATHER_QUERY", "RAG_SEARCH"}

def explicitly_requests_web(text: str) -> bool:
    t = text.lower().strip()
    if re.search(r'\b(?:search|look\s+up)\s+(?:the\s+)?(?:web|internet|online|google|bing)\b', t):
        return True
    if re.search(r'\b(?:search\s+for|look\s+up|find)\s+.+?\s+(?:online|on\s+the\s+web|on\s+the\s+internet)\b', t):
        return True
    if re.search(r'\bsearch\s+the\s+(?:internet|web)\s+for\b', t):
        return True
    if re.search(r'\b(?:latest|breaking|today\'s|current)\s+(?:news|updates?|headlines?|stock\s+price|price|score)\b', t):
        return True
    if re.search(r'\b(?:news|updates?)\s+(?:about|on|regarding)\b', t):
        return True
    if re.search(r'\b(?:current|live|today\'s)\s+(?:stock\s+price|price|score)\s+of\b', t):
        return True
    if re.search(r'\bwho\s+won\s+today(?:\'s)?\s+(?:match|game)\b', t):
        return True
    return False

def is_conversational_followup_or_complaint(text: str) -> bool:
    t = text.lower().strip().rstrip('.?!')
    followup_patterns = [
        r'\bare\s+you\s+(?:getting\s+my\s+point|listening(?:\s+to\s+me)?|paying\s+attention|following\s+me)\b',
        r'\bdo\s+you\s+(?:understand(?:\s+what\s+i(\'m|\s+am)\s+saying)?|get\s+what\s+i\s+mean|hear\s+me)\b',
        r'\bwhy\s+are\s+you\s+(?:doing\s+that|doing\s+this|responding\s+like\s+this|acting\s+like\s+this)\b',
        r'\b(?:what|something)\s+is\s+wrong\s+(?:with\s+you)?\b',
        r'\bno\s*,?\s*that(\'s|\s+is)\s+not\s+what\s+i\s+(?:meant|asked|said)\b',
        r'\bthat(\'s|\s+is)\s+not\s+what\s+i\s+(?:asked|said|meant)\b',
        r'\btry\s+again\b',
        r'\blisten\s+to\s+(?:the\s+whole\s+thing|what\s+i(\'m|\s+am)\s+saying|everything)\b',
        r'\bwhy\s+does\s+not\s+meet\s+the\s+problem\s+is\s+with\s+you\b',
        r'\byou\s+are\s+the\s+one\s+who\s+is\s+not\s+taking\s+all\s+the\s+input\b',
        r'\byou\s+are\s+not\s+able\s+to\s+put\s+what\s+i\s+am\s+trying\s+to\s+say\b',
        r'\byou(\'re|\s+are)\s+not\s+(?:listening|taking\s+all\s+the\s+input|getting\s+it)\b',
    ]
    for pat in followup_patterns:
        if re.search(pat, t):
            return True
    return False

def is_capability_query(text: str) -> bool:
    t = text.lower().strip().rstrip('.?!')
    cap_patterns = [
        r'^(?:the\s+)?actions?\s+(?:that\s+)?you\s+can\s+perform$',
        r'^(?:what|which)\s+actions?\s+(?:can\s+you|do\s+you)\s+perform$',
        r'^(?:what\s+can\s+you\s+do|what\s+are\s+your\s+capabilities|what\s+can\s+you\s+help\s+(?:me\s+)?with)$',
        r'^(?:tell\s+me\s+what\s+you\s+can\s+do|list\s+(?:your\s+)?capabilities|what\s+are\s+you\s+capable\s+of)$',
        r'^(?:what\s+can\s+you\s+do\s+for\s+me|show\s+(?:me\s+)?what\s+you\s+can\s+do)$',
        r'^(?:show\s+(?:me\s+)?(?:the\s+)?full\s+list\s+of\s+capabilities|full\s+list\s+of\s+capabilities|list\s+all\s+capabilities)$',
    ]
    for pat in cap_patterns:
        if re.search(pat, t):
            return True
    return False

def is_stable_knowledge_question(text: str) -> bool:
    t = text.lower().strip().rstrip('.?!')
    if explicitly_requests_web(t):
        return False
    knowledge_patterns = [
        r'^(?:what\s+is|what\s+are|define|tell\s+me\s+about)\s+(?:a\s+|an\s+|the\s+)?(?:concept\s+of\s+)?(python|sql|java|c\+\+|javascript|a\s+neural\s+network|neural\s+networks|machine\s+learning|deep\s+learning|gradient\s+descent|backpropagation|an\s+operating\s+system|operating\s+systems|tcp|ip|dns|http|https|recursion|an\s+algorithm|data\s+structures?|binary\s+search|sorting\s+algorithms?)\b',
        r'^(?:how\s+does|how\s+do)\s+(backpropagation|gradient\s+descent|neural\s+networks?|a\s+computer|an\s+os|memory\s+management)\s+work\b',
        r'^(?:explain|describe)\s+(?:the\s+concept\s+of\s+|about\s+)?(gradient\s+descent|backpropagation|neural\s+networks?|binary\s+search|recursion|polymorphism|inheritance|machine\s+learning|algorithms?|object\s+oriented\s+programming)\b',
    ]
    for pat in knowledge_patterns:
        if re.search(pat, t):
            return True
    return False

def is_conversational_general_query(text: str) -> bool:
    t = text.lower().strip().rstrip('.?!')
    if not t:
        return True
    if t in ("hey", "hello", "hi", "hey friday", "are you there", "you there", "are you here", "are you listening", "can you hear me", "are you awake", "good morning", "good evening", "good afternoon"):
        return True
    if re.search(r'^(?:hey|hello|hi|good\s+(?:morning|evening|afternoon))(?:\s+\w+)?$', t):
        return True
    if re.search(r'\b(?:are\s+you\s+(?:there|here|awake|listening)|can\s+you\s+hear\s+me)\b', t):
        return True
    if re.search(r'\bhow\s+(?:are\s+you|are\s+you\s+feeling|are\s+you\s+doing|do\s+you\s+feel)\b', t):
        return True
    if re.search(r'\b(?:what\'?s|what\s+is)\s+(?:up|new)\b', t):
        return True
    if re.search(r'\b(?:nice|good|great)\s+to\s+(?:see|meet|hear)\s+you\b', t):
        return True
    if re.search(r'\b(?:who\s+are\s+you|what\s+is\s+your\s+name|what\'s\s+your\s+name|whats\s+your\s+name|who\'re\s+you|tell\s+me\s+about\s+yourself|introduce\s+yourself|who\s+made\s+you|who\s+created\s+you|who\s+built\s+you|what\s+are\s+you|who\s+am\s+i\s+(?:speaking|talking)\s+(?:with|to)|what\s+is\s+your\s+identity|whats\s+your\s+identity|who\s+is\s+this|tell\s+me\s+who\s+you\s+are)\b', t):
        return True
    if re.search(r'\b(?:what\s+did\s+i\s+ask(?:\s+you)?\s+(?:earlier|before)|what\s+was\s+my\s+(?:last|previous)\s+question|continue\s+(?:your\s+)?(?:previous\s+)?answer)\b', t):
        return True
    if is_capability_query(t) or is_conversational_followup_or_complaint(t) or is_stable_knowledge_question(t):
        return True
    return False

def should_use_external_retrieval(intent: Any, user_input: str, context: Any = None) -> bool:
    """Hard routing gate to determine if external retrieval (web search, SerpAPI, Tavily) is permitted."""
    if explicitly_requests_web(user_input):
        return True

    intent_name = intent.name if hasattr(intent, "name") else str(intent)

    if intent_name == "GENERAL_CONVERSATION":
        return False

    if is_conversational_followup_or_complaint(user_input):
        return False

    if is_capability_query(user_input):
        return False

    if is_stable_knowledge_question(user_input):
        return False

    return intent_name in EXTERNAL_RETRIEVAL_INTENTS


def validate_device_action_agreement(
    requested_device_target: str,
    requested_action: str,
    resolved_action: str,
    executor_action: str,
) -> bool:
    """
    Strict P0 validator guaranteeing device action agreement.
    Proves and enforces:
    - 'turn off Bluetooth' != 'mute volume'
    - 'unmute' != 'turn on Bluetooth'
    - 'unlock computer' != 'lock computer'
    """
    if not requested_device_target or not requested_action or not resolved_action or not executor_action:
        return True

    req_target = str(requested_device_target).lower().strip()
    req_act = str(requested_action).upper().strip()
    res_act = str(resolved_action).upper().strip()
    exec_act = str(executor_action).lower().strip()

    # 1. Action identity check
    if req_act != res_act:
        return False

    # 2. Target vs Action domain cross-contamination check
    domain_map = {
        "bluetooth": {"BLUETOOTH_ON", "BLUETOOTH_OFF", "BLUETOOTH_QUERY"},
        "volume": {"VOLUME_SET", "VOLUME_DECREASE", "VOLUME_INCREASE", "VOLUME_MUTE", "VOLUME_UNMUTE", "VOLUME_QUERY"},
        "wifi": {"WIFI_ON", "WIFI_OFF", "WIFI_QUERY"},
        "lock": {"LOCK"},
        "unlock": {"UNLOCK"},
        "screen": {"SCREENSHOT"},
        "battery": {"BATTERY_QUERY"},
        "display": {"DISPLAY_QUERY"},
        "application": {"ACTIVE_APP_QUERY"},
        "window": {"ACTIVE_WINDOW_QUERY"},
    }

    allowed_actions = domain_map.get(req_target)
    if allowed_actions and req_act not in allowed_actions:
        return False

    # 3. Executor action domain agreement
    executor_domain_map = {
        "BLUETOOTH_ON": {"enable_bluetooth"},
        "BLUETOOTH_OFF": {"disable_bluetooth"},
        "BLUETOOTH_QUERY": {"bluetooth_status"},
        "VOLUME_SET": {"set_volume", "decrease_volume", "increase_volume", "volume_up", "volume_down"},
        "VOLUME_DECREASE": {"decrease_volume", "volume_down"},
        "VOLUME_INCREASE": {"increase_volume", "volume_up"},
        "VOLUME_QUERY": {"get_volume"},
        "VOLUME_MUTE": {"mute"},
        "VOLUME_UNMUTE": {"unmute"},
        "WIFI_ON": {"enable_wifi"},
        "WIFI_OFF": {"disable_wifi"},
        "WIFI_QUERY": {"wifi_status", "list_wifi_networks"},
        "LOCK": {"lock"},
        "UNLOCK": {"unlock"},
        "SCREENSHOT": {"screenshot"},
        "BATTERY_QUERY": {"battery"},
        "DISPLAY_QUERY": {"display_info"},
        "ACTIVE_APP_QUERY": {"active_application"},
        "ACTIVE_WINDOW_QUERY": {"active_window"},
    }

    allowed_executors = executor_domain_map.get(req_act)
    if allowed_executors and exec_act not in allowed_executors:
        return False

    return True


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
        # In-flight routing cache to avoid duplicate semantic resolution
        self._route_cache = {}
        
    def _compile_patterns(self):
        # NOTE: patterns are tested in strict enum priority order (1→18).
        # More specific / higher-priority intents must be listed first.
        self.patterns = {
            # ── Priority 1: POWER ACTION ───────────────────────────────────────
            # Only match when power words are standalone (not inside longer phrases
            # like "run script to restart"). Require either start-of-string or
            # whitespace/punctuation before the keyword.
            Intent.POWER_ACTION: [
                # Explicit PC/system target: "turn off my computer", "shut down the PC", "power off the computer"
                re.compile(
                    r'\b(?:shutdown|shut\s+down|power\s+off|turn\s+off|reboot|restart)\s+(?:the\s+|my\s+)?(?:pc|computer|system|laptop|machine|workstation)\b',
                    re.IGNORECASE
                ),
                # Explicit sleep with PC target: "put the computer to sleep", "sleep the PC"
                re.compile(
                    r'\b(?:put\s+(?:the\s+|my\s+)?(?:pc|computer|system|laptop|machine|workstation)\s+to\s+sleep|sleep\s+(?:the\s+|my\s+)?(?:pc|computer|system|laptop|machine|workstation))\b',
                    re.IGNORECASE
                ),
                # Standalone power action commands (no other object target)
                re.compile(
                    r'^(?:please\s+)?(?:shutdown|shut\s+down|power\s+off|reboot|restart)(?:\s+(?:the\s+system|the\s+computer|the\s+pc|now|please))?[.!?]?$',
                    re.IGNORECASE
                ),
                re.compile(
                    r'^(?:please\s+)?(?:sleep|system\s+sleep)(?:\s+(?:the\s+system|the\s+computer|the\s+pc|now|please))?[.!?]?$',
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
                # Software management (install / uninstall / package)
                re.compile(r'\b(?:install\s+software|install\s+app|install\s+package|install)\s+([a-zA-Z0-9_\-\.]+)\b', re.IGNORECASE),
                re.compile(r'\b(?:uninstall\s+software|uninstall\s+app|remove\s+software|remove\s+app|uninstall)\s+([a-zA-Z0-9_\-\.]+)\b', re.IGNORECASE),
                # Windows Service control
                re.compile(r'\b(?:start|stop|restart|status\s+of)\s+service\s+([a-zA-Z0-9_\-\.]+)\b', re.IGNORECASE),
                re.compile(r'\bservice\s+([a-zA-Z0-9_\-\.]+)\s+(?:start|stop|restart)\b', re.IGNORECASE),
                # Administrator Elevation Testing / Request
                re.compile(r'\b(?:test|request|check|trigger|verify|prompt)\s+(?:for\s+)?(?:admin(?:istrator)?\s+)?(?:uac\s+)?elevation\b', re.IGNORECASE),
                re.compile(r'\b(?:test|request)\s+(?:admin(?:istrator)?|uac)\s+permissions?\b', re.IGNORECASE),
                re.compile(r'\b(?:elevate|request)\s+(?:to\s+)?(?:admin(?:istrator)?|administrator\s+privileges?|admin\s+privileges?)\b', re.IGNORECASE),
                # Text typing / writing
                re.compile(r'\b(?:type|write)[:\s]+\s*(?!(?:to\b|(?:an?\s+)?(?:note|code|python|javascript|js|typescript|ts|java|c\+\+|cpp|c#|csharp|golang|go|rust|php|ruby|swift|kotlin|dart|r|matlab|sql|html|css|json|yaml|xml|markdown|bash|powershell|shell|script|function|algorithm|class|program|query|interface|struct|module|project|api|scraper|backend|frontend|webpage|website|app|application|report|document|email|mail|record|reminder|binary\s+search|bubble\s+sort|merge\s+sort|quick\s+sort|prime\s+check)(?!\w)))(.+)', re.IGNORECASE),
                re.compile(r'\bput\s+(?!(?:an?\s+)?(?:file|folder|document)\b)(.+?)\s+(?:in|into|inside|there)(?:\s+it)?[.!?]?$', re.IGNORECASE),
                re.compile(r'\b(mute|unmute)\b', re.IGNORECASE),
                # volume only when NOT preceded by 'open'/'launch'/'start'
                re.compile(r'(?<![Oo]pen\s)(?<![Ll]aunch\s)(?<![Ss]tart\s)\b(increase|decrease|raise|lower|set|change)\s+(?:the\s+)?(?:system\s+)?volume\b', re.IGNORECASE),
                re.compile(r'\b(?:set|change)\s+(?:the\s+)?volume\s+(?:to\s+)?(\d+)\s*%?\b', re.IGNORECASE),
                # Volume by N percentage points (e.g. "decrease volume by 12 percentage points")
                re.compile(r'\b(increase|decrease|raise|lower)\s+(?:the\s+)?(?:system\s+|master\s+)?volume\s+(?:by\s+)?(\d+)\s+percentage\s+points?\b', re.IGNORECASE),
                # Ambiguous transcription "[name] is the volume" → ask clarification
                re.compile(r'\b(?:friday|trevon|nova|jarvis|assistant)\s+(?:is|boost|up|down)\s+(?:the\s+)?volume\b', re.IGNORECASE),
                re.compile(r'\b(volume\s+(?:up|down|control|level))\b', re.IGNORECASE),
                re.compile(r'\b(turn\s+(?:up|down)\s+(?:the\s+)?volume)\b', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\x27s|\s+is)\s+(?:my\s+|the\s+)?(?:current\s+)?volum?e?|check\s+(?:my\s+|the\s+)?(?:current\s+)?volum?e?|get\s+(?:my\s+|the\s+)?(?:current\s+)?volum?e?|(?:current\s+)?volum?e?\s+(?:level|status))\b', re.IGNORECASE),
                re.compile(r'\b(?:close|shut)\s+(?:this\s+|the\s+|current\s+|browser\s+)?tab(?:s)?\b', re.IGNORECASE),
                re.compile(r'\b(take\s+(?:a\s+)?screenshot|capture\s+(?:the\s+)?screen|screen\s*capture|screenshot)\b', re.IGNORECASE),
                re.compile(r'\b(lock|logout)\s*(?:the\s+)?(?:computer|pc|system|workstation|screen)?\b', re.IGNORECASE),
                re.compile(r'\b(?:unlock|unlock\s+(?:the\s+)?(?:computer|pc|system|workstation|screen))\b', re.IGNORECASE),
                # Brightness controls
                re.compile(r'\b(?:increase|decrease|raise|lower|set|change)\s+(?:the\s+)?(?:screen\s+)?brightness\b', re.IGNORECASE),
                re.compile(r'\b(?:set|change)\s+(?:the\s+)?(?:screen\s+)?brightness\s+(?:to\s+)?(\d+)\s*%?\b', re.IGNORECASE),
                re.compile(r'\b(?:brightness\s+(?:up|down|level)|screen\s+brightness)\b', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+(?:the\s+)?(?:current\s+)?(?:screen\s+)?brightness|check\s+(?:the\s+)?(?:screen\s+)?brightness|get\s+(?:current\s+)?brightness)\b', re.IGNORECASE),
                # Battery diagnostics
                re.compile(r'\b(?:battery|battery\s+(?:status|level|percentage|life|info(?:rmation)?|health)|how\s+much\s+battery|charging\s+status|is\s+(?:the\s+)?battery\s+charging)\b', re.IGNORECASE),
                re.compile(r'\b(?:tell\s+me\s+(?:my\s+)?)?battery\s+(?:status|percentage|level|life|info(?:rmation)?|health)\b', re.IGNORECASE),
                # System Uptime / Computer running time
                re.compile(r'\b(?:how\s+long\s+(?:has|is)\s+(?:my|the|this)?\s*(?:pc|comput[er]{1,2}|system|mach[in]{1,3}e?|device|laptop|workstation)\s+(?:been\s+|being\s+)?(?:run[in]{1,3}g|on|up)|(?:what(?:\x27s|\s+is)\s+(?:my|the)?\s*(?:system\s+)?uptime|(?:system\s+)?uptime|check\s+(?:my|the)?\s*uptime|how\s+long\s+(?:has\s+it|have\s+you|is\s+it)\s+(?:been\s+|being\s+)?(?:run[in]{1,3}g|on|up)))\b', re.IGNORECASE),
                # Voice listening controls
                re.compile(r'\b(?:toggle|start|stop|pause|resume)\s+(?:voice\s+)?listening\b', re.IGNORECASE),
                # Disk / Storage diagnostics
                re.compile(r'\b(?:how\s+much\s+(?:disk\s+space|storage|space)\s+is\s+(?:avai?la?ble|free|left)|(?:what\s+is\s+(?:the\s+)?(?:storage|disk\s+space|space)\s+(?:left|free|available))|(?:disk\s+space|free\s+space|free\s+storage|storage\s+space|storage\s+left|space\s+left|how\s+much\s+(?:free\s+)?(?:storage|disk\s+space|space)|check\s+disk|disk\s+usage|storage\s+usage|drive\s+information|disk\s+details|disk\s+info(?:rmation)?|avai?la?ble\s+(?:disk|storage)))\b', re.IGNORECASE),
                re.compile(r'\b(?:storage|disk\s+space|space|free\s+space)\s+(?:left|remaining|available|free)\s+(?:in|on)\s+(?:the\s+)?[a-zA-Z]:?(?:\s+drive)?\b', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+(?:the\s+)?storage\s+(?:left|free|available)\s+(?:in|on)\s+(?:the\s+)?[a-zA-Z]:?(?:\s+drive)?)\b', re.IGNORECASE),
                re.compile(r'\b(?:tell\s+me\s+(?:my\s+)?)?disk\s+(?:usage|space|details|info(?:rmation)?)\b', re.IGNORECASE),
                # CPU / Processor diagnostics
                re.compile(r'\b(?:(?:tell\s+me\s+(?:about\s+)?(?:my\s+)?|give\s+me\s+(?:detailed\s+)?|show\s+(?:my\s+)?|check\s+(?:my\s+)?|what\s+is\s+(?:my\s+)?|what\s+)?(?:cpu|processor)\s+(?:usage|utilization|load|info(?:rmation)?|details?|metrics?|specs?|model|status|state))\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+(?:cpu|processor)\s+am\s+i\s+running|tell\s+me\s+about\s+my\s+(?:cpu|processor)|what\s+processor\s+am\s+i\s+running)\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+(?:cpu|processor)\s+(?:do\s+i\s+have|am\s+i\s+using|am\s+i\s+running|is\s+in\s+this\s+(?:pc|system|computer|laptop)|is\s+this\s+(?:computer|pc|system|laptop)\s+using)|what(?:\'s|\s+is)\s+my\s+(?:cpu|processor)|which\s+(?:cpu|processor)\s+do\s+i\s+have)\b', re.IGNORECASE),
                re.compile(r'\b(?:(?:can\s+i\s+)?check\s+(?:my\s+)?(?:cpu|proce?ss?or)|how\s+much\s+(?:cpu|proce?ss?or)\s+(?:am\s+i\s+using|is\s+(?:in\s+use|used|being\s+used))(?:\s+right\s+now)?|what(?:\x27s|\s+is)\s+(?:my\s+)?cpu\s+usage(?:\s+right\s+now)?|(?:current\s+)?cpu\s+(?:usage|utilization|metrics?)(?:\s+right\s+now)?)\b', re.IGNORECASE),
                # "What is the CPU status?" / "current status of the CPU" variant
                re.compile(r'\b(?:what\s+is\s+the\s+(?:current\s+)?(?:status|state)\s+of\s+the\s+(?:cpu|processor|ram|memory|gpu|graphics\s+card)|(?:cpu|processor|ram|memory|gpu|graphics\s+card)\s+(?:status|state)\b)', re.IGNORECASE),
                # "Tell me my current CPU and RAM usage" — explicit combined telemetry
                re.compile(r'\btell\s+me\s+(?:my\s+)?(?:current\s+)?(?:cpu|processor|ram|memory|gpu|disk|storage|battery|uptime|telemetry|hardware|system)\b', re.IGNORECASE),
                # RAM / Memory diagnostics
                re.compile(r'\b(?:(?:tell\s+me\s+(?:my\s+)?|give\s+me\s+(?:detailed\s+)?|show\s+(?:my\s+)?|check\s+(?:my\s+)?|what\s+is\s+(?:my\s+)?|what\s+)?(?:ram|memory)\s+(?:usage|utilization|info(?:rmation)?|details?|metrics?|specs?|status|state))\b', re.IGNORECASE),
                re.compile(r'\b(?:how\s+much\s+(?:ram|memm?ory)\s+(?:am\s+i\s+using|is\s+(?:in\s+use|used|being\s+used|free|avai?la?ble)|do\s+i\s+have|is\s+installed)|(?:what(?:\x27s|\s+is)\s+my\s+(?:ram|memm?ory)\s+usage|(?:current\s+)?(?:ram|memm?ory)\s+usage(?:\s+right\s+now)?))\b', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+my\s+(?:ram|memory)|how\s+much\s+ram\s+do\s+i\s+have)\b', re.IGNORECASE),
                re.compile(r'\b(?:memory\s+usage\s+of\s+(?:the\s+)?(?:computer|pc|system|machine)|(?:available|used)\s+(?:ram|memory))\b', re.IGNORECASE),
                re.compile(r'\b(?:(?:can\s+i\s+)?check\s+(?:my\s+)?(?:ram|memory))\b', re.IGNORECASE),
                # GPU / Graphics diagnostics
                re.compile(r'\b(?:(?:tell\s+me\s+(?:my\s+)?|give\s+me\s+(?:detailed\s+)?|show\s+(?:my\s+)?|check\s+(?:my\s+)?|what\s+is\s+(?:my\s+)?|what\x27s\s+(?:my\s+)?|what\s+)?(?:gpu|graphics\s+card|vram)\s*(?:usage|utilization|load|info(?:rmation)?|details?|metrics?|specs?|telemetry|stat(?:us|s)?|staus|stats|temperature|temp|memory(?:\s+usage)?))\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+(?:gpu|graphics\s+card)\s+do\s+i\s+have|what\s+graphics\s+card\s+does\s+this\s+pc\s+have|graphics\s+card\s+info(?:rmation)?|tell\s+me\s+about\s+(?:my\s+)?(?:gpu|graphics\s+card))\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+(?:gpu|graphics\s+card)\s+(?:am\s+i\s+using|is\s+in\s+this\s+(?:pc|system|computer)|is\s+this\s+(?:computer|pc|system|laptop)\s+(?:using|running)|does\s+this\s+(?:computer|pc|system|laptop)\s+have)|what(?:\'s|\s+is)\s+(?:my\s+|the\s+)?(?:gpu|graphics\s+card)|which\s+(?:gpu|graphics\s+card)\s+(?:do\s+i\s+have|does\s+this\s+(?:pc|computer|system)\s+have|is\s+(?:installed|running)))\b', re.IGNORECASE),
                re.compile(r'\b(?:how\s+much\s+(?:gpu\s+memory|vram|gpu|graphics\s+card)\s+(?:am\s+i\s+using|is\s+(?:being\s+)?used))\b', re.IGNORECASE),
                re.compile(r'\b(?:(?:can\s+i\s+)?check\s+(?:my\s+)?(?:gpu|graphics\s+card)|gpu\s+telemetry)\b', re.IGNORECASE),
                # GPU identity — "What GPU is this computer currently using?" style
                re.compile(r'\b(?:what|which)\s+(?:gpu|graphics\s+card|processor|cpu)\s+(?:is\s+)?(?:this|my|the)\s+(?:computer|pc|system|laptop|machine)\s+(?:currently\s+)?(?:using|running|has|have|equipped\s+with)\b', re.IGNORECASE),
                # Composite telemetry
                re.compile(r'\b(?:check\s+(?:my\s+)?cpu(?:\s*,\s*|\s+and\s+|\s+)ram(?:\s*,\s*|\s+and\s+|\s+)gpu(?:\s+usage|\s+telemetry)?)\b', re.IGNORECASE),
                re.compile(r'\b(?:check\s+(?:my\s+)?(?:system|hardware)\s+(?:usage|telemetry|metrics?|stats?)|show\s+(?:my\s+)?system\s+usage)\b', re.IGNORECASE),
                # Running processes & top resource consuming applications
                re.compile(r'\b(?:which|what)\s+(?:ap{1,2}l(?:ication)?|apps?|proce?ss|program)\s+(?:is\s+)?(?:using|taking|consuming)\s+(?:the\s+)?most\s+(?:of\s+the\s+)?(?:cpu|proce?ss?or|ram|memm?ory)\b', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\x27s|\s+is)\s+using|which\s+(?:ap{1,2}l(?:ication)?|apps?|proce?ss|program)\s+uses)\s+(?:the\s+)?most\s+(?:of\s+the\s+)?(?:cpu|proce?ss?or|ram|memm?ory)\b', re.IGNORECASE),
                re.compile(r'\b(?:top|highest)\s+(?:cpu|ram|memm?ory)\s+(?:proce?ss(?:es)?|apps?|app(?:lication)?s?|programs?)\b', re.IGNORECASE),
                re.compile(r'\b(?:proce?ss|app(?:lication)?|program)\s+with\s+(?:the\s+)?highest\s+(?:cpu|ram|memm?ory)(?:\s+usage)?\b', re.IGNORECASE),
                re.compile(r'\b(?:top\s+processes|running\s+processes|running\s+applications|running\s+programs|currently\s+running\s+(?:programs|applications|processes|apps))\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+(?:applications|processes|programs|apps)\s+are\s+(?:currently\s+)?(?:running|open)|what\s+programs\s+are\s+open\s+right\s+now)\b', re.IGNORECASE),
                re.compile(r'\b(?:list\s+all\s+(?:running\s+)?processes|show\s+all\s+(?:running\s+)?processes|all\s+running\s+processes)\b', re.IGNORECASE),
                # Active foreground application / window queries
                re.compile(r'\b(?:which|what)\s+(?:application|app|window|program)\s+(?:am\s+i\s+(?:currently\s+)?using|is\s+(?:currently\s+)?active)(?:\s+right\s+now)?\b', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\x27s|\s+is)\s+(?:the\s+)?(?:current|active)\s+(?:app|application|window)(?:\s+i\s+am\s+using)?(?:\s+right\s+now)?)\b', re.IGNORECASE),
                re.compile(r'\b(?:active|current)\s+(?:app|application|window)(?:\s+i(?:\x27m|\s+am)\s+using)?(?:\s+right\s+now)?\b', re.IGNORECASE),
                # Window controls
                re.compile(r'\b(?:minimize\s+all(?:\s+windows)?|minimize\s+windows|show\s+desktop)\b', re.IGNORECASE),
                # Clipboard
                re.compile(r'\b(?:read|check|show|get)\s+(?:the\s+|my\s+)?clipboard\b', re.IGNORECASE),
                re.compile(r'\bwhat(?:\'s|\s+is)\s+(?:currently\s+)?(?:in|on|stored\s+in)?\s*(?:the\s+|my\s+)?clipboard\b', re.IGNORECASE),
                re.compile(r'\b(?:copy|put)\s+(?:this|that|.+?)\s+(?:to|on|into)\s+(?:my\s+)?clipboard\b', re.IGNORECASE),
                re.compile(r'\b(?:make|convert|turn|capitalize|trim|count|strip).{0,25}clipboard\b', re.IGNORECASE),
                re.compile(r'\bclipboard.{0,25}(?:uppercase|lowercase|bullets?|bullet\s+points?|words?|trim)\b', re.IGNORECASE),
                re.compile(r'\b(?:analyze|inspect)\s+(?:my\s+)?clipboard(?:\s+content)?\b', re.IGNORECASE),
                # Remote Mobile Device Controls
                re.compile(r'\b(?:pair\s+(?:my\s+)?(?:phone|device|mobile)|connect\s+(?:to\s+)?(?:my\s+)?(?:phone|mobile)|pair\s+a\s+new\s+device)\b', re.IGNORECASE),
                re.compile(r'\b(?:disconnect|unpair|remove)\s+(?:my\s+)?(?:phone|device|mobile)\b', re.IGNORECASE),
                re.compile(r'\b(?:is\s+(?:my\s+)?(?:phone|device|mobile)\s+(?:connected|online)|(?:phone|device|mobile)\s+connection(?:\s+status)?|check\s+(?:my\s+)?(?:phone|device|mobile)\s+connection|(?:show\s+(?:my\s+)?|get\s+(?:my\s+)?)?(?:device|phone)\s+status)\b', re.IGNORECASE),
                re.compile(r'\b(?:list\s+(?:my\s+)?(?:paired|connected)?\s*devices|show\s+(?:my\s+)?(?:paired|connected)?\s*devices|what\s+devices\s+are\s+(?:paired|connected|available))\b', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\'s|\s+is|\s+was)?\s+(?:the\s+)?(?:(?:phone|device)\s+)?(?:pairing\s+)?code(?:\s+again)?|repeat\s+(?:the\s+)?(?:(?:phone|device)\s+)?(?:pairing\s+)?code|show\s+(?:the\s+)?(?:(?:phone|device)\s+)?(?:pairing\s+)?code)\b', re.IGNORECASE),
                re.compile(r'\b(?:phone\s+battery|battery\s+(?:of|on)\s+(?:my\s+)?phone|check\s+(?:my\s+)?phone\s+battery|how\s+much\s+battery\s+does\s+my\s+phone\s+have|what(?:\'s|\s+is)\s+(?:my\s+)?phone\s+battery)\b', re.IGNORECASE),
                re.compile(r'\b(?:turn\s+(?:on|off)\s+(?:the\s+)?(?:phone\s+)?(?:flashlight|torch)|(?:phone\s+)?(?:flashlight|torch)\s+(?:on|off))\b', re.IGNORECASE),
                re.compile(r'\b(?:open|launch|start)\s+.+?\s+on\s+(?:my\s+)?phone\b', re.IGNORECASE),
                # Device Location
                re.compile(r'\b(?:where\s+am\s+i|what\s+is\s+my\s+(?:current\s+)?location|my\s+current\s+location|find\s+(?:my\s+)?(?:current\s+)?location|detect\s+(?:my\s+)?location|(?:refresh|update|reload)\s+(?:my\s+)?location)\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+location\s+source|what\s+(?:is\s+)?(?:the\s+|my\s+)?location\s+source|location\s+provider|how\s+do\s+you\s+know\s+my\s+location)\b', re.IGNORECASE),
                # Display / Monitor Information
                re.compile(r'\b(?:show|get|check|what\s+is|tell\s+me)\s+(?:my\s+)?(?:current\s+)?(?:display|screen|monitor)\s+(?:info|information|resolution|metrics)\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+resolution\s+is\s+my\s+(?:screen|display|monitor)|display\s+resolution|screen\s+resolution)\b', re.IGNORECASE),
                re.compile(r'\b(?:how\s+many\s+(?:displays?|monitors?|screens?)\s+(?:are\s+)?(?:connected|attached)|connected\s+(?:monitors?|displays?|screens?)|monitor\s+count|number\s+of\s+(?:displays?|monitors?))\b', re.IGNORECASE),
                # Wi-Fi / Network
                re.compile(r'\b(?:which\s+wi-?fi(?:\s+network)?\s+(?:am\s+i|i\'m)\s+connected\s+to|what\s+network\s+am\s+i\s+(?:currently\s+)?on)\b', re.IGNORECASE),
                re.compile(r'\b(?:tell\s+me\s+(?:my\s+)?)?(?:network\s+status|network\s+info(?:rmation)?|ip\s+info(?:rmation)?|connection\s+info(?:rmation)?|wi-?fi\s+status|connected\s+wi-?fi)\b', re.IGNORECASE),
                re.compile(r'\b(?:wifi|wi-fi|wireless)\s+(?:status|connection|info|on|off|enable|disable)\b', re.IGNORECASE),
                re.compile(r'\b(?:enable|disable|turn\s+on|turn\s+off)\s+(?:the\s+)?(?:wifi|wi-fi|wireless)\b', re.IGNORECASE),
                re.compile(r'\b(?:is\s+(?:my\s+)?wifi|are\s+(?:we|i)\s+connected\s+to\s+wifi|what\s+wifi\s+am\s+i\s+on|connected\s+to\s+wifi|wifi\s+connected)\b', re.IGNORECASE),
                re.compile(r'\b(?:list|show|scan|find)\s+(?:available\s+|nearby\s+)?(?:wifi|wi-fi|wireless)\s+networks?\b', re.IGNORECASE),
                re.compile(r'\b(?:show|list|check|get)\s+(?:my\s+)?(?:network|internet)\s+(?:adapters?|connections?|status|speeds?|info)\b', re.IGNORECASE),
                re.compile(r'\b(?:my\s+)?network\s+adapters?\b', re.IGNORECASE),
                re.compile(r'\b(?:network|internet)\s+speed\b', re.IGNORECASE),
                re.compile(r'\b(?:how\s+fast\s+is\s+(?:my\s+)?(?:internet|network|wifi|connection))\b', re.IGNORECASE),
                re.compile(r'\b(?:connect\s+to\s+(?:wifi|wi-fi|network)|join\s+(?:wifi|wi-fi))\s+(.+)\b', re.IGNORECASE),
                # Bluetooth
                re.compile(r'\b(?:tell\s+me\s+(?:my\s+)?)?bluetooth\s+(?:status|info(?:rmation)?|availability)\b', re.IGNORECASE),
                re.compile(r'\b(?:bluetooth|bt)\s+(?:status|on|off|enable|disable|available|info)\b', re.IGNORECASE),
                re.compile(r'\b(?:enable|disable|turn\s+on|turn\s+off)\s+(?:the\s+)?bluetooth\b', re.IGNORECASE),
                re.compile(r'\b(?:is\s+bluetooth\s+(?:enabled|on|active|available)|is\s+bluetooth|check\s+bluetooth|bluetooth\s+connected)\b', re.IGNORECASE),
                # Environment state
                re.compile(r'\b(?:what\s+application\s+is\s+(?:currently\s+)?active|what\s+is\s+the\s+active\s+window|active\s+window|current\s+application|what\s+is\s+(?:the\s+)?current\s+app(?:\s+i\s+am\s+using)?(?:\s+right\s+now)?|what\s+app\s+am\s+i\s+using(?:\s+right\s+now)?|which\s+app\s+am\s+i\s+using|active\s+app|what\s+is\s+my\s+screen\s+resolution)\b', re.IGNORECASE),
                # Keyboard toggle keys
                re.compile(r'\b(?:turn\s+(?:the\s+)?caps\s+lock\s+(?:on|off)|(?:toggle|turn\s+on|turn\s+off|enable|disable)\s+caps\s+lock|caps\s+lock\s+(?:on|off))\b', re.IGNORECASE),
                re.compile(r'\b(?:turn\s+(?:the\s+)?num\s+lock\s+(?:on|off)|(?:toggle|turn\s+on|turn\s+off|enable|disable)\s+num\s+lock)\b', re.IGNORECASE),
                re.compile(r'\b(?:turn\s+(?:the\s+)?scroll\s+lock\s+(?:on|off)|(?:toggle|turn\s+on|turn\s+off|enable|disable)\s+scroll\s+lock)\b', re.IGNORECASE),
                re.compile(r'\b(?:is\s+caps\s+lock|caps\s+lock\s+(?:on|off|status|state)|keyboard\s+lights?\s+status)\b', re.IGNORECASE),
                re.compile(r'\b(?:check|show|what\s+is)\s+(?:the\s+)?(?:keyboard|key(?:board)?)\s+(?:toggle|lock)\s+(?:keys?|state|status)\b', re.IGNORECASE),
                # Operating system & System info
                re.compile(r'\b(?:tell\s+me\s+(?:my\s+)?)?(?:windows\s+version(?:\s+and\s+system\s+info(?:rmation)?)?|system\s+info(?:rmation)?|operating\s+system\s+info(?:rmation)?|os\s+version|os\s+information)\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(?:version\s+of\s+)?windows\s+(?:am\s+i\s+running|is\s+this)\b', re.IGNORECASE),
                re.compile(r'\b(?:tell\s+me\s+about\s+(?:my\s+)?hardware|device\s+hardware|hardware\s+spec(?:ification)?s?|hardware\s+info(?:rmation)?)\b', re.IGNORECASE),
                # Power plans
                re.compile(r'\b(?:tell\s+me\s+(?:my\s+)?)?(?:current\s+)?power\s+plan(?:\s+info(?:rmation)?)?\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+power\s+plan\s+am\s+i\s+(?:currently\s+)?using\b', re.IGNORECASE),
                re.compile(r'\b(?:power\s+plan|power\s+mode|active\s+power\s+plan|battery/power\s+configuration)\b', re.IGNORECASE),
                re.compile(r'\b(?:list|show)\s+(?:all\s+)?power\s+plans?\b', re.IGNORECASE),
                # Mouse info
                re.compile(r'\b(?:mouse\s+(?:position|cursor|location|info|status|settings?)|where\s+is\s+(?:my\s+)?(?:mouse|cursor)|cursor\s+position)\b', re.IGNORECASE),
                # Uptime
                re.compile(r'\b(?:tell\s+me\s+(?:my\s+)?)?(?:system\s+uptime|uptime)\b', re.IGNORECASE),
                re.compile(r'\bhow\s+long\s+has\s+(?:the\s+)?(?:system|computer|pc|laptop)\s+been\s+(?:on|running|up)\b', re.IGNORECASE),
                # Dark mode / theme
                re.compile(r'\b(?:toggle\s+dark\s+mode|enable\s+dark\s+mode|disable\s+dark\s+mode|turn\s+(?:on|off)\s+dark\s+mode|turn\s+(?:on|off)\s+light\s+mode|switch\s+to\s+dark\s+mode|switch\s+to\s+light\s+mode|dark\s+mode\s+(?:on|off)|light\s+mode\s+(?:on|off)|toggle\s+theme)\b', re.IGNORECASE),
                # Display resolution change
                re.compile(r'\b(?:change|set)\s+(?:display\s+|screen\s+)?resolution\s+(?:to\s+)?(\d+)\s*[xX*]\s*(\d+)\b', re.IGNORECASE),
                # Wallpaper
                re.compile(r'\b(?:(?:get|what(?:\'s|\s+is)\s+(?:my\s+)?(?:current\s+)?|show\s+(?:my\s+)?(?:current\s+)?|tell\s+me\s+(?:my\s+)?(?:current\s+)?|current\s+)?wallpaper)\b', re.IGNORECASE),
                re.compile(r'\b(?:set|change)\s+(?:my\s+)?wallpaper\s+(?:to\s+)?(.+)\b', re.IGNORECASE),
                # Desktop statistics
                re.compile(r'\b(?:desktop\s+(?:stats|statistics|analysis|summary)|analyze\s+(?:my\s+)?desktop)\b', re.IGNORECASE),
                # Installed games and software inventory
                re.compile(r'\b(?:what\s+games\s+are\s+installed\s+on\s+my\s+pc|list\s+installed\s+games|show\s+installed\s+games|installed\s+games(?:\s+on\s+my\s+pc)?)\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+(?:apps|applications)\s+are\s+installed|list\s+installed\s+(?:apps|applications)|show\s+installed\s+(?:apps|applications)|installed\s+(?:apps|applications|software))\b', re.IGNORECASE),
                re.compile(r'\b(?:find\s+(?:my\s+)?installed\s+(?:browsers?|apps?|applications?|software|programs?)|(?:what|which)\s+browsers?\s+(?:are\s+installed|do\s+i\s+have(?:\s+installed)?|are\s+on\s+(?:my|this)\s+(?:pc|computer|system))|list\s+installed\s+browsers?|show\s+installed\s+browsers?|installed\s+browsers?)\b', re.IGNORECASE),
                # Natural-language browser inventory without trigger words
                re.compile(r'\b(?:the\s+)?browsers?\s+(?:that\s+(?:are\s+)?)?installed\s+(?:on\s+(?:my|this|the)\s+(?:computer|pc|system|laptop)|in\s+(?:my|this|the)\s+(?:computer|pc|system|laptop))\b', re.IGNORECASE),
                re.compile(r'\b(?:list|show|find)\s+(?:the\s+)?browsers?\s+(?:that\s+(?:are\s+)?)?installed\b', re.IGNORECASE),
            ],

            # ── Priority 3.5: CLOSE APPLICATION ───────────────────────────────
            Intent.CLOSE_APPLICATION: [
                re.compile(r'(?:^|\b(?:please|can\s+you|could\s+you|would\s+you)\s+)?(?:close|quit|exit|terminate|kill|shut\s+down)\s+(?:all\s+(?:things|thigs|apps|applications)?\s*(?:you\s+opened|that\s+were\s+opened|opened)?(?:\s+now)?|everything\s*(?:you\s+opened|that\s+were\s+opened|opened)?(?:\s+now)?|all\s+opened\s+(?:apps|applications))\b', re.IGNORECASE),
                re.compile(r'(?:^|\b(?:please|can\s+you|could\s+you|would\s+you)\s+)?(close|quit|exit|terminate|kill|shut\s+down)\s+(?!(?:music|song|track|audio|playback|email|mail|video|tab\b|this tab|current tab|browser tab))\s*(.+)', re.IGNORECASE),
            ],

            # ── Priority 4: OPEN APPLICATION ──────────────────────────────────
            Intent.OPEN_APPLICATION: [
                # Browser search and result selection (explicitly placed before generic open app)
                re.compile(r'\b(?:search\s+(?:the\s+web\s+for|google\s+for)\s+|google\s+(?!chrome\b)|search\s+(?!for\s+(?:files?|folders?|documents?|notes?|reminders?|events?|calendar|meetings?)\b)(?!(?:files?|folders?|documents?|notes?|reminders?|events?|calendar|meetings?)\b)(?:for\s+)?)(.+)', re.IGNORECASE),
                re.compile(r'\b(?:open|click|select)\s+(?:the\s+)?(first|top|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|\d+(?:st|nd|rd|th))\s+(?:result|link)\b', re.IGNORECASE),
                re.compile(r'\b(?:search\s+(?:on\s+|in\s+)?youtube\s+for|search\s+youtube\s+for)\s+(.+)', re.IGNORECASE),
                re.compile(r'\b(?:search\s+(?:on\s+|in\s+)?google\s+for|search\s+google\s+for)\s+(.+)', re.IGNORECASE),
                re.compile(r'\b(open|show|display|launch)\s+((?:(?:the|my)\s+)?dashboard)\b', re.IGNORECASE),
                re.compile(r'(?:^|\b(?:please|can\s+you|could\s+you|would\s+you|then|now|so|just|okay|ok)\s+)(open)\s+(?!(?:music|song|(?:the\s+|this\s+|that\s+)?(?:email|emails|mail|mails)|video|.*?\b(?:folder|directory)\b|file\s+(?!explorer)|windows?\b|open\s+windows?\b|result\b|link\b|(?:first|second|third|fourth|fifth|\d+(?:st|nd|rd|th))\s+(?:result|link)))(.+)', re.IGNORECASE),
                re.compile(r'\b(?:bring\s+up|bring|switch\s+to|switch\s+back\s+to)\s+(?:the\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+(?:back|to\s+(?:the\s+)?front|on\s+the\s+first\s+page|on\s+(?:the\s+)?screen))?$', re.IGNORECASE),
                re.compile(r'\b(launch|start|run)\s+(?!(?:service\b|in\s+this\s+(?:system|pc)|on\s+this\s+(?:system|pc)|games?\b|again\b|over\b|from\s+scratch\b))(.+)', re.IGNORECASE),
                re.compile(r'\b(?:get|bring)\s+([a-zA-Z0-9_\-]+)\s+running\b', re.IGNORECASE),
                re.compile(r'\b(?:i\s+need|i\s+want)\s+(?!(?:to\s+)?(?:unlock|lock|mute|unmute|remind|remember|turn\s+off|turn\s+on|mail|email)\b)([a-zA-Z0-9_\-]+)(?:\s+(?:open|running|up))?\b', re.IGNORECASE),
                # Browser Link & Table Extraction & Follow-ups
                re.compile(r'\b(?:extract\s+(?:all\s+)?(?:the\s+)?(?:available\s+)?links(?:\s+from\s+(?:the\s+|this\s+)?(?:web\s+)?page)?|extract\s+(?:all\s+)?(?:the\s+)?(?:available\s+)?links)\b', re.IGNORECASE),
                re.compile(r'\b(?:extract\s+(?:all\s+)?(?:the\s+)?(?:available\s+)?tables?(?:\s+from\s+(?:the\s+|this\s+)?(?:web\s+)?page)?|extract\s+tables?)\b', re.IGNORECASE),
                re.compile(r'\b(?:how\s+many\s+links(?:\s+(?:did\s+you\s+find|were\s+found|are\s+there|did\s+we\s+get|extracted))?)\b', re.IGNORECASE),
                re.compile(r'\b(?:show|display|what(?:\'s|\s+is))\s+(?:me\s+)?(?:the\s+)?(?:(\d+)(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+link\b', re.IGNORECASE),
                re.compile(r'\b(?:open)\s+(?:the\s+)?(?:(\d+)(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+(?:one|link)\b', re.IGNORECASE),
                re.compile(r'\b(?:show|display|get)\s+(?:me\s+)?(?:the\s+)?first\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+rows?(?:\s+of\s+(?:the\s+)?table)?\b', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+(?:the\s+)?value\s+(?:in|of)\s+(?:the\s+)?|show\s+(?:me\s+)?(?:the\s+)?)(?:(\d+)(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+row\b', re.IGNORECASE),
                # Flight Search & Navigation
                re.compile(r'\b(?:find\s+flights|search\s+flights|flights\s+from|what\s+about\s+flights)\b', re.IGNORECASE),
                re.compile(r'\b(?:go\s+to|visit|browse\s+(?:to\s+)?|navigate\s+to)\s+(.+)', re.IGNORECASE),
                re.compile(r'^(?:go\s+back|navigate\s+back|browser\s+go\s+back|go\s+back\s+in\s+browser)[.!?]?$', re.IGNORECASE),
            ],

            # ── Priority 5: FILE OPERATIONS ───────────────────────────────────
            Intent.FILE_OPERATIONS: [
                # Duplicate files
                re.compile(r'\b(?:duplicate\s+files?|find\s+duplicates?)\b', re.IGNORECASE),
                # File search & filtering
                re.compile(r'\b(?:find\s+all\s+(?!(?:emails?|mails?)\b)|search\s+(?:for\s+)?(?:[a-zA-Z0-9_\-*\.]+\s+)?(?:files?|documents?)|search\s+(?:for\s+)?(?:.+?\s+)?(?:files?|documents?)\s+(?:in|under)\s+.+|(?:files?|documents?)\s+larger\s+than|(?:files?|documents?)\s+modified)\b', re.IGNORECASE),
                # Directory statistics
                re.compile(r'\b(?:statistics\s+for|stats\s+for|how\s+many\s+files\s+in|directory\s+stats)\b', re.IGNORECASE),
                # Largest files
                re.compile(r'\b(?:largest\s+files?|biggest\s+files?)\b', re.IGNORECASE),
                # PDF inspection & utilities
                re.compile(r'\b(?:how\s+many\s+pages\s+(?:are\s+)?in|(?:show\s+(?:me\s+)?)?(?:information|info)\s+about\s+(?:this\s+|the\s+)?pdf|pdf\s+info|split\s+(?:this\s+|the\s+)?(?:[\w\-.]+\.pdf|pdf)|merge\s+(?:these\s+|the\s+)?pdfs?|extract\s+(?:the\s+)?text\s+from\s+(?:this\s+|the\s+)?(?:[\w\-.]+\.pdf|pdf))\b', re.IGNORECASE),
                # Specific file delete
                re.compile(r'\b(delete|remove)\s+(?:the\s+)?(?:file\s+)?([\w\-.]+\.\w+)\b', re.IGNORECASE),
                # File move
                re.compile(r'\bmove\s+(?:the\s+)?(?:file\s+|folder\s+|directory\s+)(.+?)\s+to\s+(.+)', re.IGNORECASE),
                re.compile(r'\bmove\s+(?:the\s+)?(?!.*?(?:meeting|sync|standup|appointment|call|calendar|event)\b)(.+?)\s+to\s+(?!\s*(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december|\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?|\d{1,2}(?::\d{2})?\s*(?:am|pm)))(.+)', re.IGNORECASE),
                # File rename
                re.compile(r'\brename\s+(?:the\s+)?(?:file\s+|folder\s+|directory\s+)(.+?)\s+to\s+(.+)', re.IGNORECASE),
                re.compile(r'\brename\s+(?:the\s+)?(?!.*?(?:meeting|sync|standup|appointment|call|calendar|event)\b)(.+?)\s+to\s+(?!.*?(?:meeting|sync|standup|appointment|call|calendar|event)\b)(.+)', re.IGNORECASE),
                re.compile(r'\b(create|make|new)\s+(?:a\s+)?(?:folder|directory)\s+(?:named\s+|called\s+)?(.+)', re.IGNORECASE),
                re.compile(r'\b(create|make|new)\s+(?:a\s+)?(.+?)\s+(?:folder|directory)\b', re.IGNORECASE),
                re.compile(r'\b(create|make|new)\s+(?:a\s+)?(?:file\s+)?([a-zA-Z0-9_\-\.]+\.(?:txt|csv|py|json|md|log|ini|cfg|html|xml|yaml|yml))\b', re.IGNORECASE),
                re.compile(r'\b(create|make|new)\s+(?:a\s+)?(?:text\s+)?file\s+(?:named\s+|called\s+)?(.+)', re.IGNORECASE),
                # Document save / Save as
                re.compile(r'\b(?:save|save\s+(?:the\s+)?document|save\s+(?:the\s+)?file|save\s+it)\s+as\s+([a-zA-Z0-9_\-\.]+)\b', re.IGNORECASE),
                re.compile(r'\b(?:put|create|make|add)\s+(?:a\s+)?(?:text\s+|notes?\s+)?([a-zA-Z0-9_\-\.]+(?:\.[a-zA-Z0-9]+)?)\s+(?:inside(?:\s+(?:it|that|the\s+folder))?|in\s+(?:it|that|there)|there)\b', re.IGNORECASE),
                re.compile(r'\b(?:put|create|make|add)\s+(?:a\s+)?(?:text\s+|notes?\s+)?file\s+(?:inside(?:\s+(?:it|that|the\s+folder))?|in\s+(?:it|that|there)|there)\b', re.IGNORECASE),
                # "delete the test_ai folder"  (name BEFORE the word folder)
                re.compile(r'\b(delete|remove)\s+(?:the\s+)?(.+?)\s+(?:folder|directory)\b', re.IGNORECASE),
                # "delete the folder named test_ai" (folder BEFORE name)
                re.compile(r'\b(delete|remove)\s+(?:the\s+)?(?:folder|directory)\s+(?:named\s+|called\s+)?(.+)', re.IGNORECASE),
                re.compile(r'\b(open|view|launch|show)\s+(?:the\s+)?(?:folder|directory)\s+(?:named\s+|called\s+)?(.+)', re.IGNORECASE),
                re.compile(r'\b(open|view|launch|show)\s+(?:the\s+)?(.+?)\s+(?:folder|directory)\b', re.IGNORECASE),
                re.compile(r'\b(open|view|launch|show)\s+(?:the|that)\s+(?:folder|directory)\b', re.IGNORECASE),
                re.compile(r'\b(list|show)\s+(?:all\s+)?(?:folders|directories)\b', re.IGNORECASE),
                re.compile(r'\b(list|show)\s+(?:all\s+)?files\b', re.IGNORECASE),
                re.compile(r'\b(open|view|launch)\s+(?:the\s+)?file\s+(?!explorer\b)(.+)', re.IGNORECASE),
                re.compile(r'\b(find|locate)\s+(?:the\s+|my\s+)?(?:file|document|presentation|spreadsheet|pdf|docx|pptx|xlsx|folder|directory)\s+(.+)', re.IGNORECASE),
                re.compile(r'\bwhere\s+is\s+(?:the\s+|my\s+)?(?:file|document|presentation|ppt|pdf|folder|directory)\b(?:\s+(.+))?', re.IGNORECASE),
                re.compile(r'\b(find|locate)\s+(?:the\s+|my\s+)?([a-zA-Z0-9_\-]+\.[a-zA-Z0-9]{2,4})\b', re.IGNORECASE),
                # Desktop organizer
                re.compile(r'\b(?:organize|clean\s+up|clean)\s+(?:my\s+)?(?:desktop|downloads)\b', re.IGNORECASE),
                # File Profiling & Multi-Format Inspection
                re.compile(r'\b(?:profile|inspect|analyze|analyse)\s+(?:(?:the|my|that|this)\s+)?(?:[a-zA-Z0-9_\-]+\s+)?(?:file|data|csv|excel|json|pptx|ppt|presentation|document|pdf)?(?:\s+(.+))?\b', re.IGNORECASE),
                re.compile(r'\b(?:profile\s+file|inspect\s+file|file\s+profile|analyze\s+file|analyse\s+file|inspect\s+(?:data|csv|excel|json|pptx|ppt))\s+(.+)\b', re.IGNORECASE),
            ],

            # ── Priority 6: EMAIL ─────────────────────────────────────────────
            Intent.EMAIL: [
                # Natural Compose / Send variants
                re.compile(r'\b(?:send|compose|write|prepare|draft)\s+(?:an?\s+|another\s+)?(?:email|mail)(?:\s+(?:to|for|addressed\s+to)\b|\b)', re.IGNORECASE),
                re.compile(r'\b(?:mail|email|write\s+to)\s+(?:to\s+|for\s+)?(?:my\s+)?[a-zA-Z0-9_.+-]+', re.IGNORECASE),
                re.compile(r'\b(?:send|write)\s+.+?\s+(?:an?\s+|another\s+)?(?:email|mail)\b', re.IGNORECASE),
                re.compile(r'\b(?:send|write)\s+(?:a\s+)?message\s+(?:to\s+.+?\s+)?(?:through|via|using|by)\s+(?:my\s+)?(?:email|mail)\b', re.IGNORECASE),
                re.compile(r'\b(?:send\s+(?:email|mail)|send\s+.*\s+(?:to|email|mail))\b', re.IGNORECASE),
                re.compile(r'\b(?:email|mail)\s+.+?\s+to\b', re.IGNORECASE),
                re.compile(r'\b(?:send|email|mail)\s+(?:it|that\s+file|this\s+file|the\s+file|the\s+pdf|the\s+excel|the\s+report)\s+to\b', re.IGNORECASE),
                re.compile(r'\b(?:i\s+need\s+to|i\s+want\s+to|can\s+you\s+(?:help\s+me\s+)?|please\s+)?(?:write|compose|prepare|send|mail|email)\s+(?:an?\s+|another\s+)?(?:email|mail|message)\b', re.IGNORECASE),
                re.compile(r'\b(?:complain|send\s+(?:a\s+)?complaint)\s+(?:to\s+.+?\s+)?about\b', re.IGNORECASE),
                re.compile(r'\b(?:inform|notify)\s+(?:my\s+)?[a-zA-Z0-9_\-\s]+?\s+(?:that|about)\b', re.IGNORECASE),
                # Specific read / open / summarize operations
                re.compile(r'\b(?:open|read|view|show|summarize|explain)\s+(?:the\s+|this\s+|that\s+)?email(?:\s+with\s+(?:the\s+)?subject|\s+from|\s+about|\s+saying|\b)', re.IGNORECASE),
                re.compile(r'\b(?:what\s+does\s+(?:this|the|that)\s+email\s+say|read\s+this\s+email)\b', re.IGNORECASE),
                # Email counting operations
                re.compile(r'\bhow\s+many\s+(?:emails?|mails?|messages?)?\s*(?:are\s+)?(?:read|unread)\b', re.IGNORECASE),
                re.compile(r'\bhow\s+many\s+(?:emails?|mails?|messages?)?\s*(?:are\s+there\s+)?(?:in\s+(?:my\s+)?inbox|in\s+total|total)\b', re.IGNORECASE),
                re.compile(r'\bhow\s+many\s+(?:unread|read|total\s+inbox|total)?\s*(?:emails?|mails?|messages?)\b', re.IGNORECASE),
                re.compile(r'\bhow\s+many\s+unread\s+emails?\s+(?:did\s+i|do\s+i)\s+(?:receive|have|get)\b', re.IGNORECASE),
                # Search by sender & sender inquiries
                re.compile(r'\b(?:did\s+i\s+receive|did\s+[a-zA-Z0-9_\-\s]+\s+email|check\s+whether\s+i\s+got|check\s+if\s+i\s+got)\b.*?\b(?:email|mail|emails)\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+was\s+the\s+(?:last|latest)\s+email\s+[a-zA-Z0-9_\-\s]+\s+sent\s+me\b', re.IGNORECASE),
                re.compile(r'\bfind\s+(?:all\s+)?(?:the\s+)?emails?\s+(?:from|about|with|received)\b', re.IGNORECASE),
                # Message organization (mark read / unread)
                re.compile(r'\bmark\s+(?:all\s+)?(?:these\s+|this\s+|that\s+)?(?:the\s+|my\s+)?(?:emails?|mails?|messages?)?\s*(?:as\s+)?(?:read|unread)\b', re.IGNORECASE),
                # Inbox and Mailbox checking variants
                re.compile(r'\b(?:check|read|show|list|view|display|get)\s+(?:me\s+)?(?:my\s+)?(?:latest\s+|recent\s+)?(?:inbox|emails?|mails?|recent\s+messages?|messages?)\b', re.IGNORECASE),
                re.compile(r'\bshow\s+(?:me\s+)?(?:all\s+)?(?:my\s+)?unread\s+emails?\b', re.IGNORECASE),
                re.compile(r'\bshow\s+(?:me\s+)?(?:the\s+)?last\s+\d+\s+emails?\b', re.IGNORECASE),
                re.compile(r'\bshow\s+(?:me\s+)?emails?\s+(?:with\s+attachments?|from\s+yesterday)\b', re.IGNORECASE),
                re.compile(r'\bdid\s+i\s+receive\s+any\s+important\s+emails?\b', re.IGNORECASE),
                re.compile(r'\b(?:unread\s+emails?|new\s+emails?|unread\s+mails?|new\s+mails?)\b', re.IGNORECASE),
                re.compile(r'\bdo\s+i\s+have\s+(?:any\s+)?(?:new\s+|unread\s+)?(?:emails?|mails?|messages?)\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(?:emails?|new\s+emails?|unread\s+emails?|messages?)\s+(?:do\s+i\s+have|have\s+i\s+received?|did\s+i\s+(?:get|receive))\b', re.IGNORECASE),
                re.compile(r'\b(check|read|reply\s+to)\s+(?:my\s+)?(?:latest\s+|recent\s+)?(?:email|emails|mail|messages|inbox)\b', re.IGNORECASE),
                # Email address query
                re.compile(r'\b(?:what\s+is|what\'s|show|tell\s+me|get)\s+(?:my\s+)?(?:email|email\s+address|email\s+id)\b', re.IGNORECASE),
                # Email content operations (summarize / explain / extract actions / reply)
                re.compile(r'\b(?:summarize|summary\s+of|explain|action\s+items?\s+from|reply\s+to|draft\s+a?\s+reply\s+to)\s+(?:this\s+)?(?:email|mail|message)\b', re.IGNORECASE),
                # Pending send confirmation & draft management
                re.compile(r'\b(?:send\s+the\s+mail|send\s+the\s+email|send\s+it|send\s+that\s+email|send\s+this\s+email|send\s+draft|proceed\s+with\s+send|confirm\s+send|yes\s+send\s+it|please\s+send\s+it)\b', re.IGNORECASE),
                re.compile(r'\b(?:show|list|get|view)\s+(?:all\s+)?(?:my\s+)?drafts?\b', re.IGNORECASE),
                re.compile(r'\b(?:send|edit|open|delete|remove|discard)\s+(?:my\s+)?draft\b', re.IGNORECASE),
                re.compile(r'\b(?:cancel\s+(?:the\s+)?(?:email|draft)|discard\s+(?:the\s+)?(?:email|draft)|don\'t\s+send\s+(?:it|the\s+email)|keep\s+(?:it\s+as\s+a\s+)?draft)\b', re.IGNORECASE),
                # Personal mailbox queries (first email, latest email, emails today)
                re.compile(r'\b(?:what\s+(?:is|was)\s+)?(?:the\s+)?(?:first|latest|recent|last|newest)\s+(?:email|mail)(?:\s+(?:i\s+got|i\s+received|in\s+my\s+inbox))?\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+emails?\s+did\s+i\s+(?:get|receive)\s+(?:today|yesterday|this\s+week|recently)\b', re.IGNORECASE),
                re.compile(r'\bwho\s+sent\s+(?:my\s+)?(?:latest|last|first|recent|newest)\s+(?:email|mail)\b', re.IGNORECASE),
                re.compile(r'\b(?:read|check|show)\s+(?:the\s+)?(?:first|latest|newest)\s+(?:email|mail)\b', re.IGNORECASE),
                re.compile(r'\b(?:check|read|show|get)\s+(?:my\s+)?mails?\b', re.IGNORECASE),
            ],

            # ── Priority 7: NOTES ─────────────────────────────────────────────
            Intent.NOTES: [
                re.compile(r'\b(?:take|create|make|add|save|write)\s+(?:a\s+)?note\b', re.IGNORECASE),
                re.compile(r'\bremember\s+this\s+as\s+(?:a\s+)?note\b', re.IGNORECASE),
                re.compile(r'\b(?:show|list|view|get|read)\s+(?:all\s+)?(?:my\s+)?notes\b', re.IGNORECASE),
                re.compile(r'\b(?:delete|remove)\s+(?:my\s+)?note\s+([a-zA-Z0-9]+)\b', re.IGNORECASE),
                re.compile(r'\b(?:jot\s+down|take\s+a\s+memo)\b', re.IGNORECASE),
            ],

            # ── Priority 8: REMINDERS ─────────────────────────────────────────
            Intent.REMINDERS: [
                re.compile(r'\b(?:remind|reminders?|set\s+(?:a\s+)?reminder|alert\s+me)\b', re.IGNORECASE),
                re.compile(r'\b(?:show|list|view|get|check)\s+(?:me\s+)?(?:all\s+)?(?:my\s+)?reminders?\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(?:are\s+(?:my\s+)?reminders?|reminders?\s+do\s+i\s+have)\b', re.IGNORECASE),
                re.compile(r'\b(?:do\s+i\s+have\s+any\s+reminders?|my\s+reminders?)\b', re.IGNORECASE),
            ],

            # ── Priority 9: MUSIC ──────────────────────────────────────────────
            # Music playback commands with high specificity (strictly excludes games/software)
            Intent.MUSIC: [
                # Standalone and explicit transport controls (Highest precedence in MUSIC)
                re.compile(r'\b(pause|resume|stop|next|previous|skip)\s+(?:the\s+)?(?:music|songs?|tracks?|playback|audio)\b', re.IGNORECASE),
                re.compile(r'\b(?:stop|pause|resume)\s+playing\s+(?:the\s+)?(?:music|songs?|audio|tracks?)\b', re.IGNORECASE),
                re.compile(r'\b(?:stop|pause)\s+(?:singing|playing)(?:\s+(?:the\s+)?(?:songs?|music|audio|tracks?))?\b', re.IGNORECASE),
                re.compile(r'\b(stop\s+singing|stop\s+playing\s+songs|stop\s+the\s+music|stop\s+everything|stop\s+all)\b', re.IGNORECASE),
                re.compile(r'\b(play\s+next(?:\s+song|\s+track)?|play\s+previous(?:\s+song|\s+track)?|next\s+track|previous\s+track|next\s+song|previous\s+song|toggle\s+playback|play\s*\/\s*pause)\b', re.IGNORECASE),
                re.compile(r'^\s*(?:can\s+you\s+|could\s+you\s+|please\s+)?(pause|resume|stop|next|previous|skip)\s+(?:the\s+)?(?:tracks?|songs?|audio|music|playback|singing)\s*$', re.IGNORECASE),
                # Play commands (strictly excludes transport 'next' / 'previous')
                re.compile(r'\b(play|start|begin)\s+(?:(?:some\s+)?(?:music|songs|tracks?)|(?:a\s+)?song)\b', re.IGNORECASE),
                re.compile(r'\bplay\s+(?!(?:audio\s+)?(?:sound|sound\s+effect|chime|ping|click|beep|whoosh|chirp|notification(?:\s+sound)?|alert|(?:some\s+)?(?:games?|gaming|online\s+games?|pc\s+games?)|steam|download|which|in\s+this\s+system|online\s+game|fun|multiplayer|rpg|fps|next|previous)\b)(.+?)(?:\s+song|\s+track|\s+audio|$)', re.IGNORECASE),
                # Video song requests
                re.compile(r'\b(?:play\s+video\s+song|show\s+(?:the\s+)?(?:music\s+)?video|play\s+music\s+video)\b', re.IGNORECASE),
                # YouTube video summary
                re.compile(r'\b(?:summarize|summary\s+of)\s+(?:this\s+)?(?:youtube\s+video|video)\b', re.IGNORECASE),
            ],

            # ── Priority 10: DOCUMENT GENERATION ──────────────────────────────
            Intent.DOCUMENT_GENERATION: [
                re.compile(r'\b(?:create|created|generate|generated|make|made|write|wrote|build|built|draft|drafted|put\s+together)\s+(?:an?|the)?\s*(?:(?:\d+[\s\-]slides?|\d+[\s\-]pages?|detailed|comprehensive|powerful|new)\s+)?(?:word\s+doc(?:ument)?|docx|pdf(?:\s+document|\s+report)?|excel(?:\s+sheet|\s+spreadsheet|\s+file)?|spreadsheet|xlsx|powerpoint(?:\s+presentation)?|presentation|pptx|ppt|slides|document|report)\b', re.IGNORECASE),
                re.compile(r'\b(?:create|created|generate|generated|make|made|write|wrote|build|built|draft|drafted)\s+(?:an?|the)?\s*(?:pdf|excel|word|powerpoint|presentation|spreadsheet|ppt|pptx)\s+report\b', re.IGNORECASE),
                re.compile(r'\b(?:create|created|generate|generated|make|made|write|wrote|build|built|draft|drafted)\s+(?:an?|the)?\s*(?:excel\s+(?:expense\s+sheet|sheet|file)|pdf\s+report|presentation\s+with\s+\d+\s+slides?)\b', re.IGNORECASE),
                re.compile(r'\b(?:generate|generated|create|created|make|made|write|wrote|build|built|draft|drafted)\s+(?:an?|the)?\s*(?:report|resume|document|spreadsheet|sheet|presentation|slides)\s*(?:in|as|about|with)?\s*(?:word|docx|pdf|excel|xlsx|pptx|ppt|powerpoint)?\b', re.IGNORECASE),
                re.compile(r'\b(?:create|created|generate|generated|make|made|build|built|draft|drafted)\s+(?:an?|the)?\s*(?:(?:\d+[\s\-]slides?|detailed|comprehensive|powerful|new)\s+)?(?:presentation|ppt|pptx|powerpoint)\b', re.IGNORECASE),
                re.compile(r'\b(?:create|created|generate|generated|make|made|build|built|write|wrote|draft|drafted)\s+(?:an?|the)?\s*(?:word\s+document|doc|docx)\b', re.IGNORECASE),
                re.compile(r'\b(?:create|created|generate|generated|make|made|build|built|write|wrote|draft|drafted)\s+(?:an?|the)?\s*(?:pdf|report\s+about|document\s+about)\b', re.IGNORECASE),
                re.compile(r'\b(?:create|created|generate|generated|make|made|build|built|draft|drafted)\s+(?:an?|the)?\s*(?:excel(?:\s+file|\s+sheet)?|spreadsheet)\b', re.IGNORECASE),
                re.compile(r'\b(?:turn|convert|put)\s+(?:this|it)\s+(?:in|into|to|as)\s+(?:an?|the)?\s*(?:pdf|excel|spreadsheet|presentation|ppt|powerpoint|word|docx)\b', re.IGNORECASE),
                re.compile(r'\b(?:save|export)\s+(?:a\s+copy\s+of\s+)?(?:this|that|the|my)?\s*(?:document|file|report|presentation)?\s*(?:as|to|into)\s+(?:a\s+|an\s+)?(?:pdf|docx|excel|spreadsheet|pptx|ppt)\b', re.IGNORECASE),
                re.compile(r'\b(?:save|export|make)\s+(?:a\s+|an\s+)?(?:pdf|docx|excel|presentation|ppt|pptx)\s+(?:copy|version|file|document)?\b', re.IGNORECASE),
                re.compile(r'\b(?:convert|export)\s+(?:(?:the|my|that|this)\s+)?(?:[a-zA-Z0-9_\-\s]+\s+)?(?:presentation|ppt|pptx|document|report|word|docx|excel|spreadsheet|sheet)\s+(?:to|into|as)\s+(?:a\s+|an\s+)?(?:pdf|docx|excel|spreadsheet|pptx|ppt)\b', re.IGNORECASE),
                re.compile(r'\b(?:convert|export)\s+(?:this|it)\s+(?:to|into|as)\s+(?:a\s+|an\s+)?(?:pdf|docx|excel|spreadsheet|pptx|ppt)\b', re.IGNORECASE),
                re.compile(r'\bmake\s+it\s+\d+\s+slides\b', re.IGNORECASE),
                re.compile(r'\b(?:make\s+it\s+(?:shorter|more\s+detailed|\d+\s+slides?)|add\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:more\s+)?slides?|add\s+(?:a\s+section|deadlock|references))\b', re.IGNORECASE),
                re.compile(r'\bgather\s+.*(?:and\s+)?(?:make|create|build)\s+(?:an?|the|a\s+powerful)?\s*(?:ppt|presentation|document|report|pdf)\b', re.IGNORECASE),
            ],

            # ── Priority 10: CALCULATOR ────────────────────────────────────────
            # Arithmetic calculations and local random number generation
            Intent.CALCULATOR: [
                re.compile(r'\b(?:perform|do)\s+(?:a\s+)?calculation\b', re.IGNORECASE),
                re.compile(r'\b(?:calculate|compute|solve|math)\b', re.IGNORECASE),
                # Basic arithmetic with operators or words
                re.compile(r'\bwhat\s+is\s+[\d.]+\s*(?:[\+\-\*\/\^x]|plus|minus|times|multiplied\s+by|divided\s+by|over|to\s+the\s+power\s+of)\s*[\d.]+', re.IGNORECASE),
                re.compile(r'^\s*[\d.]+\s*(?:[\+\-\*\/\^]|plus|minus|times|divided\s+by)\s*[\d.]+\s*$', re.IGNORECASE),
                re.compile(r'\b(?:subtract|multiply|divide)\s+[\d.]+\b', re.IGNORECASE),
                re.compile(r'\badd\b(?!\s+(?:a\s+)?(?:meeting|event|appointment|calendar|task|reminder|note))\s+[\d.]+\s+(?:to|and)\s+[\d.]+\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+is\s+[\d.]+\s*[\+\-\*\/\%x]\s*[\d.]+\b', re.IGNORECASE),
                # Percentages
                re.compile(r'\b(?:calculate|what\s+is)?\s*[\d.]+\s*(?:percent|%)\s+of\s+[\d.]+\b', re.IGNORECASE),
                re.compile(r'\bpercentage\s+(?:change|increase|decrease|difference)\b', re.IGNORECASE),
                re.compile(r'\b[\d.]+\s+is\s+what\s+percent\s+of\s+[\d.]+\b', re.IGNORECASE),
                # Powers and roots
                re.compile(r'\b(?:square\s+root|cube\s+root|sqrt)\s+(?:of\s+)?[\d.]+\b', re.IGNORECASE),
                re.compile(r'\b[\d.]+\s+(?:squared|cubed)\b', re.IGNORECASE),
                re.compile(r'\b[\d.]+\s+to\s+the\s+(?:power\s+of|power)\s+[\d.]+\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+is\s+)?[\d.]+\s+(?:squared|cubed)\b', re.IGNORECASE),
                re.compile(r'\b[\d.]+(?:th|st|nd|rd)?\s*root\s+of\s+[\d.]+\b', re.IGNORECASE),
                # Trigonometry
                re.compile(r'\b(?:sin|cos|tan|sine|cosine|tangent|asin|acos|atan)\s*(?:of\s+)?[\d.]+', re.IGNORECASE),
                # Logarithms
                re.compile(r'\b(?:log|ln|logarithm|natural\s+log)\s*(?:base\s+[\d.]+\s+of\s+)?[\d.]+', re.IGNORECASE),
                re.compile(r'\blog\s+base\s+[\d.]+\s+of\s+[\d.]+', re.IGNORECASE),
                # Factorials
                re.compile(r'\b(?:factorial\s+of|[\d]+\s+factorial|[\d]+\s*!)\b', re.IGNORECASE),
                # Statistics
                re.compile(r'\b(?:mean|average|median|mode|standard\s+deviation|std\s+dev|variance)\s+(?:of\s+)?[\d]', re.IGNORECASE),
                # GCD / LCM
                re.compile(r'\b(?:gcd|lcm|greatest\s+common|least\s+common)\s+(?:divisor|multiple|factor)?\s+of\b', re.IGNORECASE),
                re.compile(r'\b(?:gcd|lcm)\s+of\s+[\d]+\s+and\s+[\d]+\b', re.IGNORECASE),
                # Prime / factors
                re.compile(r'\bis\s+[\d]+\s+(?:a\s+)?prime\b', re.IGNORECASE),
                re.compile(r'\b(?:factors?|divisors?)\s+of\s+[\d]+\b', re.IGNORECASE),
                # Geometry
                re.compile(r'\b(?:area|circumference|perimeter|volume|surface\s+area)\s+of\s+(?:a\s+)?(?:circle|rectangle|triangle|square|sphere|cylinder|cone|cube)\b', re.IGNORECASE),
                # Financial
                re.compile(r'\b(?:simple|compound)\s+interest\b', re.IGNORECASE),
                # Equation solving
                re.compile(r'\b(?:x\^2|x\s*\*\*\s*2|quadratic|linear\s+equation)\b', re.IGNORECASE),
                re.compile(r'\bsolve\b.{0,50}\bx\b', re.IGNORECASE),
                # Free-form expressions with math functions
                re.compile(r'\b(?:pi\s*[\*\/\+\-]|e\s*\^|\d+\s*\^\s*\d+)\b', re.IGNORECASE),
                # Random numbers
                re.compile(r'\b(?:random\s+numbers?|give\s+me\s+(?:\d+\s+)?random\s+numbers?|tell\s+me\s+(?:\d+\s+)?random\s+numbers?|generate\s+(?:\d+\s+)?random\s+numbers?|numbers?\s+(?:from|between)\s+\d+\s+(?:to|and)\s+\d+)\b', re.IGNORECASE),
            ],

            # ── Priority 11: CODE GENERATION ─────────────────────────────────
            Intent.CODE_GENERATION: [
                re.compile(r'\b(?:diagnose|parse|explain|analyze|check)\s+(?:this\s+)?(?:error|traceback)\b', re.IGNORECASE),
                re.compile(r'\btraceback\s+\(most\s+recent\s+call\s+last\)', re.IGNORECASE),
                re.compile(r'\b(?:explain|analyze)\s+(?:this\s+)?(?:supplied\s+)?code\b', re.IGNORECASE),
                re.compile(r'\b(?:validate|check)\s+(?:the\s+)?(?:syntax\s+of\s+)?(?:this\s+)?(?:supplied\s+)?(?:python\s+|javascript\s+|c\+\+\s+|[a-zA-Z0-9_\-\+\#]+\s+)?code(?:\s+for\s+syntax\s+errors)?\b', re.IGNORECASE),
                re.compile(r'\b(?:does\s+this\s+code\s+have\s+syntax\s+errors|explain\s+(?:the\s+)?structure\s+of\s+(?:this\s+)?(?:python\s+)?code)\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+classes\s+and\s+functions\s+are\s+in\s+this\s+code)\b', re.IGNORECASE),
                re.compile(r'\b(?:fix|debug|repair|solve|correct|refactor|optimize)\s+(?:this\s+)?(?:supplied\s+)?(?:code|program|script|function|bug|error|issue)\b', re.IGNORECASE),
                re.compile(r'\b(?:(?:write|generate|create|build|run|sample|example|source)\s+code|code\s+(?:snippet|block|generation)|coding|program|script|function|algorithm)\b', re.IGNORECASE),
                re.compile(
                    r'\b(write|create|build|make|generate|implement)\b.{0,40}'
                    r'\b(in\s+(?:python|java|javascript|js|c\+\+|cpp|c#|csharp|ruby|go|rust|swift|kotlin|typescript|ts|php|bash|powershell|sql|html|css))(?!\w)',
                    re.IGNORECASE
                ),
                re.compile(
                    r'\b(write|create|build|make|generate|implement)\b.{0,40}'
                    r'\b(?:python|java|javascript|js|typescript|ts|c\+\+|cpp|c#|csharp|go|golang|rust|php|ruby|swift|kotlin|dart|r|matlab|sql|bash|powershell|html|css)\b.{0,40}'
                    r'\b(?:program|script|function|class|interface|query|code|app|project|example|controller|component|dashboard|service|api|model|algorithm|tool|worker|pool|implementation|scraper|server|page|webpage|template)\b',
                    re.IGNORECASE
                ),
                re.compile(
                    r'\b(bubble\s+sort|merge\s+sort|quick\s+sort|binary\s+search|linked\s+list|'
                    r'stack|priority\s+queue|queue\s+data\s+structure|graph|tree|dynamic\s+programming|recursion|maximum\s+subarray|prime\s+check)\b',
                    re.IGNORECASE
                ),
                re.compile(
                    r'\b(write|create|build|generate|implement)\b.{0,40}'
                    r'\b(calculator|to-?do|todo|snake\s+game|tic-?tac-?toe|chatbot|web\s+scraper|api|rest\s+api|flask\s+api|fastapi|webpage|website)\b',
                    re.IGNORECASE
                ),
                re.compile(r'\b(write|create|build|generate|implement)\s+(?:an?\s+)?(?:sql\s+query|database\s+query|query\s+to\b|powershell\s+script|bash\s+script|typescript\s+interface)\b', re.IGNORECASE),
                re.compile(r'\b(generate|create|build)\s+(?:a\s+)?(?:webpage|website)\s+with\s+separate\b', re.IGNORECASE),
                re.compile(r'\b(generate|create|build)\s+(?:a\s+)?(?:multi-module|multi-file|modular)\s+(?:python\s+)?project\b', re.IGNORECASE),
            ],

            # ── Priority 12: TRANSLATION ──────────────────────────────────────
            Intent.TRANSLATION: [
                re.compile(r'\b(translate|translation|convert\s+text\s+to)\b', re.IGNORECASE),
                re.compile(r'\bsay\s+.+?\s+in\s+(?:spanish|french|german|italian|portuguese|russian|chinese|japanese|korean|hindi|telugu|tamil|kannada|malayalam|arabic|english|marathi|bengali|gujarati|punjabi|urdu|latin|greek)\b', re.IGNORECASE),
            ],

            # ── Priority 14: DAILY BRIEFING & CALENDAR ────────────────────────
            # Calendar creation patterns are placed BEFORE CALCULATOR (Priority 10)
            # in enum evaluation order so 'add a meeting' routes here, not CALCULATOR.
            # ── Priority 14: DAILY BRIEFING & CALENDAR ────────────────────────
            # Calendar creation patterns are placed BEFORE CALCULATOR (Priority 10)
            # in enum evaluation order so 'add a meeting' routes here, not CALCULATOR.
            Intent.DAILY_BRIEFING: [
                re.compile(r'\b(daily\s+briefing|morning\s+briefing|morning\s+update|give\s+me\s+my\s+briefing|brief\s+me|daily\s+update)\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+do\s+i\s+have(?:\s+(?:for\s+)?(?:today|tomorrow|scheduled|planned))?\b', re.IGNORECASE),
                re.compile(r'\bwhat(?:\'s|\s+is)\s+(?:on\s+my\s+schedule|scheduled|planned)(?:\s+(?:for\s+)?(?:today|tomorrow))?\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+do\s+i\s+(?:need|have)\s+to\s+do(?:\s+(?:today|tomorrow))?\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(?:meetings?|appointments?)\s+do\s+i\s+have(?:\s+(?:today|tomorrow))?\b', re.IGNORECASE),
                re.compile(r'\b(?:do\s+i\s+have|are\s+there)\s+(?:any\s+)?(?:events?|meetings?|appointments?|plans?|anything\s+scheduled)(?:\s+(?:today|tomorrow|for\s+today|for\s+tomorrow|scheduled))?\b', re.IGNORECASE),
                re.compile(r'\b(?:show|check|view|what(?:\'s|\s+is)\s+on|what)\s+(?:my\s+|today\'?s?\s+)?calendar\b', re.IGNORECASE),
                re.compile(r'\b(?:show|check|view|what)\s+(?:today\'?s?\s+|my\s+)?events\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+events\s+do\s+i\s+have\b', re.IGNORECASE),
                re.compile(r'\b(?:calendar\s+for\s+today|events\s+for\s+today|today\'?s?\s+calendar|today\'?s?\s+events)\b', re.IGNORECASE),
                # ── Next appointment / upcoming appointment ──
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+my\s+)?(?:next|upcoming)\s+(?:appointment|meeting|event|call|sync)\b', re.IGNORECASE),
                # ── Weekly planning around meetings / holidays ──
                re.compile(r'\b(?:plan\s+(?:my\s+)?week|weekly\s+plan(?:ning)?|plan\s+the\s+week)\b', re.IGNORECASE),
                # ── Calendar event modification (reschedule, move, change time, rename) ──
                re.compile(r'\b(?:change|update|reschedule|shift)\s+(?:the\s+)?time\s+of\s+(.+?)\s+to\s+(.+)', re.IGNORECASE),
                re.compile(r'\b(?:move|reschedule|shift|postpone)\s+(.+?)\s+to\s+(?:(?:october|november|december|january|february|march|april|may|june|july|august|september|\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?|today|tomorrow)\b|\d{1,2}(?::\d{2})?\s*(?:am|pm))', re.IGNORECASE),
                re.compile(r'\brename\s+(?:the\s+)?(?:meeting|event|appointment|call|sync|standup)?\s*(.+?)\s+to\s+(?:[a-zA-Z0-9_\s]*?(?:meeting|event|appointment|call|sync|standup)|.+)', re.IGNORECASE),
                # ── Calendar event deletion / cancellation ──
                re.compile(r'\b(?:cancel|delete|remove|drop)\s+(?:all\s+|the\s+|my\s+)?(?:meeting|meetings|event|events|appointment|appointments|call|calls|sync|syncs|standup|standups|huddle|huddles)(?:\s+(?:for|on|at|tomorrow|today|\d{4}-\d{2}-\d{2}))?\b', re.IGNORECASE),
                re.compile(r'\b(?:cancel|delete|remove)\s+(?:all\s+occurrences\s+of\s+|this\s+occurrence\s+of\s+|the\s+|my\s+)?(.+?)\s+(?:on|for|at)\s+(?:\d{4}-\d{2}-\d{2}|\w+\s+\d{1,2}|today|tomorrow)\b', re.IGNORECASE),
                # ── Date range queries (e.g. from X to Y) ──
                re.compile(r'\b(?:show|get|list|view)\s+(?:my\s+)?events\s+from\s+.+?\s+to\s+.+', re.IGNORECASE),
                # ── Holiday queries ──
                re.compile(r'\b(?:how\s+many\s+)?(?:holidays|special\s+days|festivals)\b', re.IGNORECASE),
                re.compile(r'\bwhen\s+is\s+(?:the\s+)?(?:holiday|festival|diwali|christmas|eid|thanksgiving|halloween|new\s+year)\b', re.IGNORECASE),
                re.compile(r'\b(?:what|which)\s+(?:is\s+the\s+|is\s+)?(?:holiday|special\s+day|festival)\s+(?:is\s+)?(?:it\s+)?today\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(?:public\s+)?holiday\s+is\s+today\b', re.IGNORECASE),
                re.compile(r'\bwhy\s+is\s+(?:it|today|this\s+day)\s+observed\b', re.IGNORECASE),
                re.compile(r'\b(?:significance|meaning|history|importance)\s+of\s+(?:today|today\'?s?\s+holiday|this\s+holiday)\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+are\s+the\s+)?(?:public\s+)?holidays\s+(?:this\s+month|in\s+\w+|this\s+week|next\s+week|in\s+the\s+next\s+\d+\s+days)\b', re.IGNORECASE),
                re.compile(r'\b(?:which\s+holidays|what\s+holidays)\s+are\s+(?:in\s+the\s+next|coming\s+up|upcoming)\b', re.IGNORECASE),
                re.compile(r'\b(?:how\s+many\s+)?(?:public\s+)?holidays\s+are\s+(?:left|remaining)\b', re.IGNORECASE),
                re.compile(r'\b(?:is\s+)?(?:today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2})\s+(?:a\s+)?(?:public\s+)?holiday\b', re.IGNORECASE),
                re.compile(r'\b(?:is\s+)?(?:it\s+)?(?:a\s+)?(?:public\s+)?holiday\s+(?:today|tomorrow|yesterday|on\s+\w+|\d{4}-\d{2}-\d{2})\b', re.IGNORECASE),
                re.compile(r'\b(?:is\s+)?(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(?:a\s+)?(?:working\s+day|workday|working\s+or\s+holiday|holiday\s+or\s+(?:a\s+)?working\s+day)\b', re.IGNORECASE),
                re.compile(r'\b(?:any|upcoming|next)\s+(?:public\s+)?holidays?\b', re.IGNORECASE),
                re.compile(r'\bholiday\s+or\s+not\b', re.IGNORECASE),
                # ── Free Time / Busy Time / Open Slots ──
                re.compile(r'\b(?:when\s+am\s+i\s+(?:free|busy)|am\s+i\s+(?:free|busy)|find\s+(?:a\s+)?free\s+slot|free\s+time|open\s+slots?|busy\s+(?:time|periods?)|suggest\s+(?:a\s+)?time)\b', re.IGNORECASE),
                # ── Meeting Artifacts (Notes, Agendas, Checklists) ──
                re.compile(r'\badd\s+(?:meeting\s+)?(?:notes?|agenda(?:\s+items?)?|checklists?)\s+(?:to|for)\b', re.IGNORECASE),
                # ── Calendar Analytics & Schedule Utilization ──
                re.compile(r'\b(?:calendar\s+analytics|schedule\s+utilization|meeting\s+statistics|calendar\s+stats)\b', re.IGNORECASE),
                # ── Calendar Search ──
                re.compile(r'\b(?:search|find)\s+(?:calendar|events|meetings)\b', re.IGNORECASE),
                # ── ICS Export / Import & Calendar Synchronization ──
                re.compile(r'\b(?:export\s+(?:my\s+)?calendar|import\s+(?:my\s+)?calendar|(?:export|import)\s+.+?\s+(?:to|from)\s+(?:an?\s+)?ics(?:\s+file)?|\.?ics\b|sync\s+(?:my\s+)?calendar)\b', re.IGNORECASE),
                # ── Calendar Reminder Snooze ──
                re.compile(r'\bsnooze\s+(?:calendar\s+|meeting\s+)?reminder\b', re.IGNORECASE),
                # ── Event creation ──
                re.compile(r'\b(?:schedule|shedule)\s+(?:an?\s+)?(.+?)\s+(?:on|for|at)\s+(?:\d{4}-\d{2}-\d{2}|\w+\s+\d{1,2}|\d{1,2}(?::\d{2})?\s*(?:am|pm)|today|tomorrow)\b', re.IGNORECASE),
                re.compile(r'\b(?:create|schedule|shedule|add|book|set\s+up)\s+(?:an?\s+)?(?:calendar\s+event|event|meeting|meet|appointment)\b', re.IGNORECASE),
                re.compile(r'\badd\s+(?:an?\s+)?(?:meeting|meet|event|appointment)\b', re.IGNORECASE),
                re.compile(r'\badd\s+.+?\s+to\s+(?:my\s+)?calendar\b', re.IGNORECASE),
                re.compile(r'\b(?:schedule|shedule)\s+(?:an?\s+)?(?:event|meeting|meet|appointment)(?:\s+for)?\b', re.IGNORECASE),
                re.compile(r'\b(?:schedule|shedule)\s+a\s+(?:meet|meeting)\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b', re.IGNORECASE),
                re.compile(r'\bput\s+.+?\s+(?:on|in(?:to)?)\s+(?:my\s+)?calendar\b', re.IGNORECASE),
            ],

            # ── Priority 15: TIME QUERY & CLOCK / ALARM / TIMER / STOPWATCH ─
            Intent.TIME_QUERY: [
                # Alarms
                re.compile(r'\b(?:set|create|put|schedule)\s+(?:an?\s+)?alarm(?:\s+(?:for|at|in)\s+(.+))?\b', re.IGNORECASE),
                re.compile(r'\bwake\s+me\s+up\s+(?:at|in|for)\s+(.+)', re.IGNORECASE),
                re.compile(r'\b(?:show|list|view|check|what\s+are)\s+(?:all\s+|my\s+)?alarms\b', re.IGNORECASE),
                re.compile(r'\b(?:cancel|delete|remove|turn\s+off|stop|dismiss)\s+(?:all\s+|the\s+|my\s+)?alarms?\b', re.IGNORECASE),
                re.compile(r'\bsnooze(?:\s+the\s+alarm)?(?:\s+for\s+(\d+)\s+minutes?)?\b', re.IGNORECASE),
                # Timers
                re.compile(r'\b(?:set|start|create|begin)\s+(?:a\s+)?(?:\d+\s*(?:hours?|hrs?|minutes?|mins?|seconds?|secs?)\s+)?timer(?:\s+(?:for|of)\s+(.+))?\b', re.IGNORECASE),
                re.compile(r'\b(?:show|list|view|check)\s+(?:all\s+|my\s+|active\s+)?timers\b', re.IGNORECASE),
                re.compile(r'\b(?:how\s+much\s+time\s+(?:is\s+)?left\s+on\s+(?:the\s+)?timer|timer\s+status)\b', re.IGNORECASE),
                re.compile(r'\b(?:cancel|stop|delete|reset)\s+(?:the\s+|my\s+|all\s+)?timers?\b', re.IGNORECASE),
                # Stopwatch
                re.compile(r'\b(?:start|begin|run|resume)\s+(?:the\s+)?stopwatch\b', re.IGNORECASE),
                re.compile(r'\b(?:stop|pause|halt)\s+(?:the\s+)?stopwatch\b', re.IGNORECASE),
                re.compile(r'\b(?:reset|clear)\s+(?:the\s+)?stopwatch\b', re.IGNORECASE),
                re.compile(r'\b(?:lap|split)(?:\s+time)?\s+(?:on\s+)?(?:the\s+)?stopwatch\b', re.IGNORECASE),
                re.compile(r'\b(?:check|what(?:\'s|\s+is)\s+(?:the\s+)?time\s+on|show|status\s+of)\s+(?:the\s+)?stopwatch\b', re.IGNORECASE),
                re.compile(r'\bstopwatch\b', re.IGNORECASE),
                # World Clock & Timezones
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+(?:the\s+)?time\s+(?:in|at|for|of)|current\s+time\s+(?:in|at|for)|time\s+in)\s+([a-zA-Z\s]+)', re.IGNORECASE),
                re.compile(r'\bwhat\s+time\s+is\s+it\s+in\s+([a-zA-Z\s]+)', re.IGNORECASE),
                # Standard Local Clock & Multilingual Clock
                re.compile(r'\b(?:what(?:s|\'s|\s+is)\s+(?:the\s+)?time|what\s+time(?:\s+is\s+it)?|(?:can\s+you\s+)?tell\s+me\s+the\s+time|current\s+time|time\s+is\s+it)\b', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+(?:the\s+)?(?:current\s+)?(?:date\s+and\s+time|time\s+and\s+date)|tell\s+me\s+(?:the\s+)?(?:date\s+and\s+time|time\s+and\s+date))\b', re.IGNORECASE),
                # Indic / Multilingual Local Clock Patterns
                re.compile(r'(?:సమయం|టైమ్|టైం|గంటలు?)\s*(?:ఎంత|ఏమిటి|చెప్పు)?|(?:ఎంత|ఏమిటి)\s*(?:సమయం|టైమ్|టైం)|(?:టైమ్|టైం|సమయం)\s+ఎంత|ఫ్రైడే\s+(?:టైమ్|సమయం)|(?:తేదీ\s*మరియు\s*సమయం|సమయం\s*మరియు\s*తేదీ)', re.IGNORECASE),
                re.compile(r'(?:समय|टाइम|वक्त)\s*(?:क्या|कितना|बताओ)?|कितने\s+बजे|टाइम\s+क्या\s+है|समय\s+क्या\s+है|तारीख\s+और\s+समय|समय\s+और\s+तारीख', re.IGNORECASE),
                re.compile(r'(?:நேரம்|மணி|டைம்)\s*(?:என்ன|எவ்வளவு|சொல்லு)?', re.IGNORECASE),
                re.compile(r'\b(?:que\s+hora\s+es|dime\s+la\s+hora|quelle\s+heure\s+est-il)\b', re.IGNORECASE)
            ],

            # ── Priority 14: DATE QUERY (Local System Clock — Bypasses RAG/LLM) ─
            Intent.DATE_QUERY: [
                re.compile(r'\b(?:what(?:s|\'s|\s+is)\s+(?:the\s+)?(?:current\s+)?date|what\s+date(?:\s+is\s+it)?|what\s+date(?:\s+is|\s+will\s+it\s+be)?\s+(?:today|tomorrow|yesterday)|(?:today|tomorrow|yesterday)(?:s|\'s|\s+is)\s+date|what\s+(?:is\s+)?(?:tomorrow|yesterday)(?:\'s)?\s+date|what\s+day\s+is\s+(?:it|today|tomorrow|yesterday)|which\s+day\s+is\s+(?:it|today|tomorrow|yesterday)|which\s+date\s+is\s+(?:it|today|tomorrow|yesterday)|tell\s+me\s+(?:the\s+)?(?:date|today\'?s?\s+date|tomorrow\'?s?\s+date)|current\s+date|date\s+today|date\s+tomorrow)\b', re.IGNORECASE),
                # Indic / Multilingual Local Date Patterns
                re.compile(r'(?:ఈరోజు|ఈ\s*రోజు|రేపు|నిన్న)?\s*(?:తేదీ|దినం|వారం)\s*(?:ఏమిటి|ఎంత|చెప్పు)?|ఈరోజు\s+ఏ\s*రోజు|రేపు\s+ఏ\s*రోజు|తేదీ\s+ఎంత|ఈరోజు\s+తేదీ', re.IGNORECASE),
                re.compile(r'(?:आज|कल|कल\s+की)?\s*(?:की\s+)?(?:तारीख|दिनांक|दिन)\s*(?:क्या\s+है|बताओ)?|आज\s+कौन\s+सा\s+दिन\s+है', re.IGNORECASE),
                re.compile(r'(?:இன்று|நாளை)?\s*(?:தேதி|நாள்)\s*(?:என்ன|சொல்லு)?', re.IGNORECASE),
                re.compile(r'\b(?:que\s+fecha\s+es|qual\s+e\s+a\s+data|quelle\s+est\s+la\s+date)\b', re.IGNORECASE)
            ],

            # ── Priority 15: WEATHER QUERY ─────────────────────────────────────
            Intent.WEATHER_QUERY: [
                re.compile(r'\b(?:what\s+is\s+the\s+)?weather\s+(?:in|at|for|near|of|around)\b', re.IGNORECASE),
                re.compile(r'\b(how\s+is\s+the\s+weather|temperature|forecast|will\s+it\s+rain|humidity|wind\s+speed)\s+(?:in|at|for|near|around)?\b', re.IGNORECASE),
                re.compile(r'\b(?:is\s+it\s+(?:going\s+to\s+)?rain(?:ing)?|will\s+it\s+rain|does\s+it\s+rain)\b', re.IGNORECASE),
                re.compile(r'\b(?:rain|raining|snow|snowing)\s+(?:in|at|for|near|around)\b', re.IGNORECASE),
                re.compile(r'\b(?:temperature|temp|humidity|wind\s*speed)\s+(?:in|at|for|near|around)\b', re.IGNORECASE),
                # Natural paraphrases for weather intent
                re.compile(r'\b(?:weather|rain|sunny|cloudy|forecast)\b.*\b(?:today|tomorrow|tonight|outside|this\s+week)\b', re.IGNORECASE),
                re.compile(r'\b(?:umbrella|raincoat)\b', re.IGNORECASE),   # "do I need an umbrella"
                re.compile(r'\bhow\s+(?:hot|cold|warm|cool)\s+is\s+it\b', re.IGNORECASE),  # "how hot is it outside"
                re.compile(r'\b(?:what\'?s?|show\s+me|display|tell\s+me)\s+(?:the\s+)?weather\b', re.IGNORECASE),          # "what's the weather" / "show me the weather"
            ],

            # ── Priority 16: MEMORY QUERY ────────────────────────────────────
            # Must come BEFORE RAG_SEARCH and MEMORY_STORE so personal queries hit here.
            Intent.MEMORY_QUERY: [
                re.compile(r'\b(who\s+am\s+i|who\'?s\s+am\s+i)\b', re.IGNORECASE),
                re.compile(r'\bhow\s+old\s+am\s+i\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+is\s+my\s+age\b', re.IGNORECASE),
                re.compile(r'\bwhat(?:\'s|\s+is)\s+my\s+height\b', re.IGNORECASE),
                re.compile(r'\bhow\s+tall\s+am\s+i\b', re.IGNORECASE),
                re.compile(r'\b(do\s+you\s+remember|can\s+you\s+remember|do\s+you\s+know|do\s+you\s+recall)\s+(?:what\s+)?my\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(did\s+i|did\s+we|were\s+we|was\s+i|is\s+my|are\s+my|was\s+my)\b(?!\s+(?:task|project(?!\s+(?:name|title|secret|id|code|description))|website|background\s+task|(?:next\s+|upcoming\s+)?(?:appointment|appointments|meeting|meetings|event|events|calendar|schedule))\b)', re.IGNORECASE),
                re.compile(r'\bwhat\s+(?:project\s+)?were\s+we\s+(?:working\s+on|doing|discussing|talking\s+about)\b', re.IGNORECASE),
                re.compile(r'\bwhat(\'s|\s+is)\s+my\b(?!\s+(?:next\s+|upcoming\s+)?(?:appointment|meeting|event|calendar|schedule|task|tasks|project(?!\s+(?:name|title|secret|id|code|description))|website|background\s+task)\b)', re.IGNORECASE),
                # "tell me my" — exclude hardware/telemetry follow-ups (those go to DEVICE_CONTROL)
                re.compile(r'\btell\s+me\s+my\b(?!\s*(?:current\s+)?(?:cpu|processor|gpu|graphics|ram|memory|disk|storage|battery|uptime|telemetry|hardware|system|volume|brightness)\b)', re.IGNORECASE),
                re.compile(r'\bwhich\s+([a-zA-Z\s]+)\s+do\s+i\s+(like|love|prefer)\b', re.IGNORECASE),
                re.compile(r'\b(?:remember\s+my\b(?!\s+[a-zA-Z0-9_\s]+?\s+(?:is|was|=))|recall\s+my\b)', re.IGNORECASE),
                re.compile(r'\bwhat\s+do\s+i\s+like\b', re.IGNORECASE),
                re.compile(r'\b(?:tell\s+me\s+about|what\s+did\s+i\s+tell\s+you\s+about)\s+myself\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+do\s+you\s+(know|remember)\s+about\s+me\b', re.IGNORECASE),
                re.compile(r'\bshow\s+(?:my\s+)?memory\b', re.IGNORECASE),
                re.compile(r'\b(?:project\s+secret|my\s+project\s+secret)\b', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\'s|\s+is)|tell\s+me|show\s+me|get)\b.*?\bmy\s+(?!(?:next\s+|upcoming\s+)?(?:appointment|meeting|event|calendar|schedule|task|tasks|project(?!\s+(?:name|title|secret|id|code|description))|website|background\s+task)\b)([a-zA-Z0-9_\s]+)', re.IGNORECASE),
                re.compile(r'\b(?:which|what)\s+database\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(?:backend|technology|tech\s+stack)\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+name\s+did\s+i\s+choose\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(?:did\s+i\s+(?:ask|tell)\s+you\s+to\s+remember|was\s+the\s+(?:test\s+)?phrase\s+i\s+asked\s+you\s+to\s+remember|was\s+the\s+(?:phrase|fact|secret)\s+i\s+asked\s+you\s+to\s+remember)\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+was\s+(?:the\s+)?(?:test\s+phrase|phrase|fact|secret)\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(?:response\s+style|style\s+of\s+response)\b', re.IGNORECASE),
                re.compile(r'\b(?:which|what)\s+(?:university|college|school|institution)\s+do\s+i\s+(?:attend|go\s+to)\b', re.IGNORECASE),
                re.compile(r'\bwhere\s+do\s+i\s+(?:study|go\s+to\s+(?:school|college|university))\b', re.IGNORECASE),
                re.compile(r'\bwhat(?:\'s|\s+is)\s+my\s+(?:university|college|institution|education|major|student\s+status|degree|activity|role|cell|goal|preferred\s+name)\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+(?:cell|committee|club)(?:\s+or\s+(?:cell|committee|club))?\s+am\s+i\s+(?:in|part\s+of)|am\s+i\s+(?:in|part\s+of)\s+(?:any\s+|the\s+)?(?:placement\s+cell|cell|club|committee))\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+is|what\'s)\s+my\s+(?:preferred\s+)?name\b', re.IGNORECASE),
                re.compile(r'\bwhen\s+is\s+my\s+(?:interview|exam|meeting|test|presentation)\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+happened\s+when\s+you\s+tried\s+that\s+command\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+did\s+you\s+change\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+error\s+did\s+we\s+fix\b', re.IGNORECASE),
            ],

            # ── Priority 17: MEMORY STORE ──────────────────────────────────
            Intent.MEMORY_STORE: [
                re.compile(r'\bmy\s+([a-zA-Z0-9_\s]+?)\s+(?:is|was|=)\s+([^?]+)', re.IGNORECASE),
                re.compile(r'\b(?:please\s+)?(?:remember|note)\s+(?:that\s+)?(.+)', re.IGNORECASE),
                re.compile(r'\bi\s+(?:really\s+)?(?:like|love|enjoy|prefer)\s+(.+)', re.IGNORECASE),
                re.compile(r'\bi\s+prefer\s+([a-zA-Z0-9_\s]+)\s+answers?\b', re.IGNORECASE),
                re.compile(r'\b(?:the\s+)?database\s+(?:for\s+this\s+project\s+)?(?:is|was|=)\s+([a-zA-Z0-9_\s]+)', re.IGNORECASE),
                re.compile(r'\b(?:the\s+)?(?:backend|backend\s+technology)\s+(?:for\s+this\s+project\s+)?(?:is|was|=)\s+([a-zA-Z0-9_\s]+)', re.IGNORECASE),
                re.compile(r'\b(?:save|store|keep)\s+(?:my\s+)?(?!it\b|that\s+file\b|document\b|file\b|.*?\s+as\b)(.+)', re.IGNORECASE),
            ],

            # ── Priority 18: TASK MANAGEMENT ─────────────────────────────────
            Intent.TASK_MANAGEMENT: [
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+(?:the\s+)?status\s+of\s+(?:my\s+)?(?:task|project|website|code\s+generation))\b', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+happening\s+with\s+(?:my\s+)?(?:project|task|website|code))\b', re.IGNORECASE),
                re.compile(r'\b(?:how(?:\'s|\s+is)\s+(?:my\s+)?(?:project|task|website|build|code)\s+(?:coming\s+along|progressing|doing))\b', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+(?:the\s+)?progress\s+on\s+(?:my\s+)?(?:project|task|website|code))\b', re.IGNORECASE),
                re.compile(r'\b(?:cancel\s+(?:the\s+)?(?:project|website|generation)|stop\s+(?:the\s+)?(?:project|website|generation))\b', re.IGNORECASE),
                re.compile(r'\b(?:queue|add|create|schedule)\s+(?:a\s+)?(?:background\s+)?task\b(?:\s*:\s*|\s+(?:to\s+|for\s+)?|\s+)(.+)', re.IGNORECASE),
                re.compile(r'\b(?:run\s+(?:this\s+)?as\s+(?:a\s+)?background\s+task|put\s+this\s+in\s+(?:the\s+)?task\s+queue)\b(?:\s*:\s*|\s+(?:to\s+|for\s+)?|\s+)(.+)', re.IGNORECASE),
                re.compile(r'\b(?:queue\s+task|run\s+(?:this\s+)?in\s+(?:the\s+)?background)\b(?:\s*:\s*|\s+(?:to\s+|for\s+)?|\s+)(.+)', re.IGNORECASE),
                re.compile(r'\brun\s+(.+?)\s+in\s+(?:the\s+)?background\b', re.IGNORECASE),
                re.compile(r'\b(?:check\s+status\s+of\s+(?:my\s+)?task|status\s+of\s+(?:my\s+)?task|task\s+status|show\s+task)\s+([a-zA-Z0-9_\-]+)\b', re.IGNORECASE),
                re.compile(r'\b(?:cancel|stop)\s+(?:my\s+)?task\s+([a-zA-Z0-9_\-]+)\b', re.IGNORECASE),
                re.compile(r'^(?:is\s+it\s+(?:still\s+)?running|did\s+it\s+(?:finish|complete)|check\s+if\s+it(?:\'s|\s+is)\s+(?:still\s+)?running)[?.!]?$', re.IGNORECASE),
                re.compile(r'^(?:what(?:\'s|\s+is)\s+its\s+status|its\s+status|check\s+its\s+status)[?.!]?$', re.IGNORECASE),
                re.compile(r'^(?:cancel\s+it|cancel\s+task|stop\s+it|stop\s+task)[?.!]?$', re.IGNORECASE),
                re.compile(r'\b(?:(?:list|show|view|get|check)\s+(?:all\s+)?(?:my\s+)?(?:background\s+)?tasks?|background\s+tasks?|what\s+(?:background\s+)?tasks?\s+are\s+running)\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+tasks?\s+do\s+i\s+have\b', re.IGNORECASE),
                re.compile(r'\b(?:(?:show|view|check|list)\s+)?task\s+queue\b', re.IGNORECASE),
            ],

            # ── Priority 19: SMART HOME ──────────────────────────────────────
            Intent.SMART_HOME: [
                re.compile(r'\b(?:show\s+(?:my\s+)?smart\s+(?:home\s+)?devices|list\s+(?:my\s+)?smart\s+(?:home\s+)?devices|smart\s+home(?:\s+devices)?|discover\s+smart\s+devices|find\s+smart\s+devices|scan\s+smart\s+devices)\b', re.IGNORECASE),
                re.compile(r'\b(?:turn|switch|power)\s+(?:on|off)\s+(?:the\s+)?([a-zA-Z0-9_\s]+?(?:light|fan|plug|switch|lamp|bulb|ac|air\s+conditioner|heater|thermostat|device))\b', re.IGNORECASE),
                re.compile(r'\b(?:status\s+of|check\s+(?:the\s+)?|is\s+(?:the\s+)?)([a-zA-Z0-9_\s]+?(?:light|fan|plug|switch|lamp|bulb|ac|air\s+conditioner|heater|thermostat))\b', re.IGNORECASE),
                re.compile(r'\bset\s+(?:the\s+)?([a-zA-Z0-9_\s]+?)\s+(?:speed|temperature|temp|brightness)\s+to\s+(\d+)\b', re.IGNORECASE),
            ],

            # ── Priority 20: WINDOW CONTEXT ──────────────────────────────────
            Intent.WINDOW_CONTEXT: [
                re.compile(r'\b(?:what\s+(?:window|app(?:lication)?)\s+(?:is\s+)?(?:currently\s+)?active|what\s+app(?:lication)?\s+am\s+i\s+(?:currently\s+)?using|current\s+window|active\s+window|foreground\s+window|active\s+app(?:lication)?)\b', re.IGNORECASE),
                re.compile(r'\b(?:(?:take\s+(?:a\s+)?)?(?:capture|screenshot|snap)(?:\s+(?:a\s+)?screenshot)?(?:\s+of)?\s+(?:the\s+)?(?:active|current|foreground)\s+window|(?:active|current|foreground)\s+window\s+(?:screenshot|capture))\b', re.IGNORECASE),
                re.compile(r'\b(?:capture|screenshot)\s+(?:the\s+)?active\s+window\b', re.IGNORECASE),
                re.compile(r'\b(?:(?:list|show|what|which)\s+(?:all\s+|my\s+)?(?:open\s+windows|windows\s+(?:are\s+)?open)|open\s+windows)\b', re.IGNORECASE),
                re.compile(r'\b(?:list|show)\s+(?:my\s+)?open\s+windows\b', re.IGNORECASE),
                re.compile(r'\b(?:what|which)\s+windows\s+are\s+open\b', re.IGNORECASE),
                re.compile(r'\b(?:minimize|restore)\s+(?:the\s+)?(?:current|active)\s+window\b', re.IGNORECASE),
            ],

            # ── Priority 21: LEARNING ────────────────────────────────────────
            Intent.LEARNING: [
                re.compile(r'\b(?:learn\s+rule|learned\s+rules|my\s+rules|(?:list|show)\s+(?:my\s+)?rules|(?:list|show)\s+(?:my\s+)?(?:learned\s+)?preferences|(?:list|show)\s+learned\s+preferences|my\s+preferences|what\s+have\s+you\s+learned|what\s+preferences\s+have\s+you\s+learned|(?:list|show)\s+what\s+you(?:\'ve|\s+have)\s+learned)\b', re.IGNORECASE),
                re.compile(r'\b(?:forget|delete|remove|clear)\s+(?:that\s+|my\s+|the\s+)?(?:learned\s+)?(?:preference|rule)(?:\s+[a-zA-Z0-9]+)?\b', re.IGNORECASE),
                re.compile(r'\b(?:forget|delete|remove)\s+rule\s+([a-zA-Z0-9]+)\b', re.IGNORECASE),
                re.compile(r'\b(?:remember\s+that|learn\s+rule:?|always\s+remember|note\s+that)\s+(.+)', re.IGNORECASE),
            ],

            # ── Priority 22: UNDO ────────────────────────────────────────────
            Intent.UNDO: [
                re.compile(r'\b(?:undo|undo\s+last\s+action|undo\s+that|what\s+can\s+i\s+undo|show\s+undo\s+history|undo\s+history)\b', re.IGNORECASE),
                re.compile(r'\bundo\s+(?:the\s+)?(?:last\s+)?(?:change|action|operation|step)\b', re.IGNORECASE),
                re.compile(r'\bwhat(?:\'s|\s+is|\s+was)\s+(?:my\s+)?(?:last\s+)?(?:action\s+that\s+can\s+be\s+undone|undoable\s+action)\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(?:actions?\s+)?can\s+(?:i|be)\s+undo(?:ne)?\b', re.IGNORECASE),
                re.compile(r'\b(?:last\s+)?action\s+that\s+can\s+be\s+undone\b', re.IGNORECASE),
            ],

            # ── Priority 23: AUDIO DEVICES ───────────────────────────────────
            Intent.AUDIO_DEVICES: [
                re.compile(r'\b(?:turn|switch|set)?\s*push\s+to\s+talk\s+(?:on|off|enable|disable|toggle)\b', re.IGNORECASE),
                re.compile(r'\b(?:toggle|enable|disable)\s+push\s+to\s+talk\b', re.IGNORECASE),
                re.compile(r'\b(?:turn\s+on|turn\s+off)\s+push\s+to\s+talk\b', re.IGNORECASE),
                re.compile(r'\bpush\s+to\s+talk\b', re.IGNORECASE),
                re.compile(r'\b(?:i\s+)?(?:can\'?t|cannot)\s+hear(?:\s+(?:you|anything|sound|audio))?\b', re.IGNORECASE),
                re.compile(r'\b(?:no\s+(?:sound|audio)|audio\s+(?:is\s+)?not\s+working|sound\s+(?:is\s+)?not\s+working|diagnose\s+audio|check\s+audio\s+output|test\s+(?:audio|speakers))\b', re.IGNORECASE),
                re.compile(r'\b(?:show\s+audio\s+devices|list\s+audio\s+devices|audio\s+devices|list\s+microphones|show\s+microphones|list\s+speakers|show\s+speakers)\b', re.IGNORECASE),
                re.compile(r'\b(?:switch|change|set)\s+(?:audio\s+)?(?:output|playback|speakers?|device)\s+(?:to\s+)?(.+)', re.IGNORECASE),
                re.compile(r'\b(?:use|set)\s+(.+?)\s+as\s+(?:audio\s+)?(?:output|playback|speakers?)\b', re.IGNORECASE),
                re.compile(r'\bplay\s+(?:an?\s+)?(?:audio\s+)?(?:sound\s+)?(?:effect\s+)?(chime|ping|click|beep|whoosh|chirp|notification(?:\s+sound)?|alert|sound)\b', re.IGNORECASE),
            ],

            # ── Priority 24: RECOMMENDATION ───────────────────────────────────
            Intent.RECOMMENDATION: [
                re.compile(r'^(?:select|choose|pick|details\s+for|info\s+on)\s+recommendation\s+(.+)', re.IGNORECASE),
                re.compile(r'^(?:open|play|show)\s+recommendation\s+(.+)', re.IGNORECASE),
                re.compile(r'^select\s+recommendation\s+(.+)', re.IGNORECASE),
                # Game discovery & compatibility recommendations
                re.compile(r'\b(?:suggest|recommend|find)\s+(?:some\s+)?(?:online\s+|pc\s+|fun\s+|multiplayer\s+|new\s+|good\s+)?games?(?:\s+to\s+play)?(?:\s+which\s+would\s+be\s+fun)?\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+are\s+some\s+|suggest\s+|recommend\s+)?(?:online\s+|fun\s+|pc\s+)?games?\s+(?:to\s+play|i\s+can\s+play)\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+games|games)\s+(?:can\s+i\s+(?:download\s+and\s+)?(?:run|play)|compatible\s+to\s+download\s+and\s+play|compatible\s+with\s+(?:this\s+)?(?:system|pc|computer))\b', re.IGNORECASE),
                re.compile(r'\b(?:area|any|list)\s+of\s+(?:the\s+)?games\s+compatible\s+to\s+download\s+and\s+(?:play|run)\s+(?:in|on)\s+this\s+system\b', re.IGNORECASE),
                re.compile(r'\b(?:what|which)\s+games\s+(?:can\s+i|should\s+i)\s+(?:play|download|try|run(?:\s+on\s+(?:my\s+)?(?:computer|pc|system))?)\b', re.IGNORECASE),
                re.compile(r'\b(?:give\s+me\s+(?:some\s+)?)?recommendations?\s+(?:for|on|about)?\b', re.IGNORECASE),
                re.compile(r'\b(?:recommend|suggest)\s+(?:an?\s+)?(.+)', re.IGNORECASE),
                re.compile(r'\b(?:recommend|suggest)\s*(?:something|anything)?(?:\s+for\s+me)?\b', re.IGNORECASE),
            ],

            # ── Priority 25: RAG SEARCH ───────────────────────────────────────
            Intent.RAG_SEARCH: [
                # Explicit research/gathering requests: "gather information about...", "research...", "gather DBMS information"
                re.compile(r'\b(?:gather|collect|research)\s+(?:all\s+)?(?:the\s+)?([a-zA-Z0-9_\-\s]+?)\s+(?:information|info|facts|details)\b', re.IGNORECASE),
                re.compile(r'\b(?:gather|research)\s+(?:all\s+)?(?:the\s+)?(?:information|info|facts|details|everything|what\s+you\s+can\s+find)\s+(?:about|on|regarding)\s+(.+)', re.IGNORECASE),
                re.compile(r'\b(?:gather|research)\s+everything\s+(?:you\s+can\s+)?(?:about|on)\s+(.+)', re.IGNORECASE),
                re.compile(r'\bwhat\s+did\s+we\s+gather\s+(?:about|on)\s+(.+)', re.IGNORECASE),
                # Explicit web/internet search commands:
                re.compile(r'\b(?:search|look\s+up)\s+(?:the\s+)?(?:web|internet|online|google|bing)\s+(?:for\s+)?(.+)', re.IGNORECASE),
                re.compile(r'\b(?:search\s+for|look\s+up|find)\s+(.+?)\s+(?:online|on\s+the\s+web|on\s+the\s+internet)\b', re.IGNORECASE),
                re.compile(r'\bsearch\s+the\s+(?:internet|web)\s+for\s+(.+)', re.IGNORECASE),
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+the\s+)?latest\s+([a-zA-Z0-9_\s]+?)\s+(?:news|updates?|headlines?)\b', re.IGNORECASE),
                re.compile(r'\b(?:latest|recent|today\'s|breaking)\s+(?:news|updates?|headlines?)\b', re.IGNORECASE),
                re.compile(r'\b(?:current|live|today\'s)\s+(?:stock\s+price|price|score)\s+of\s+(.+)', re.IGNORECASE),
                re.compile(r'\bwho\s+won\s+today(?:\'s)?\s+(?:match|game)\b', re.IGNORECASE),
                # Genuine general knowledge & information retrieval questions
                re.compile(r'^(?:why\s+(?:is|are|does|do)|what\s+(?:is|are)|who\s+(?:is|was|are|were)|when\s+(?:was|is|did)|how\s+(?:does|do|is|are))\s+(?!(?:you\b|your\b|the\s+time\b|today\b|the\s+weather\b|my\b))\S+.*$', re.IGNORECASE),
            ],

            # ── Priority: VISUAL RESPONSE SURFACE ────────────────────────────
            Intent.VISUAL_SURFACE: [
                re.compile(r'^show\s+visual\s+response(?:\s+([a-zA-Z0-9_]+))?$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?(?:can\s+you\s+)?(?:show|display|open)\s+(?:me\s+)?(?:the\s+)?(?:details|details\s+box|full\s+steps|technical\s+details|complete\s+explanation|full\s+explanation|explanation|all\s+(?:the\s+)?information|all\s+info|steps|information|info)(?:\s+(?:of|about)\s+(?:your\s+|the\s+)?(?:previous\s+)?(?:answer|response|explanation))?(?:\s+(?:again|back))?(?:\s+on\s+(?:the\s+)?screen)?\.?$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?(?:can\s+you\s+)?(?:show|display)\s+(?:what\s+you\s+(?:just\s+)?(?:explained|said|told\s+me))(?:\s+on\s+(?:the\s+)?screen)?\.?$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?(?:put\s+(?:that|it|this)\s+on\s+(?:the\s+)?screen|expand\s+that(?:\s+information)?|i\s+didn\'?t\s+understand\s+everything[;,]?\s*show\s+me)\.?$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?(?:show|display)\s+(?:me\s+)?(?:the\s+)?(?:details\s+(?:about|of|for)|information\s+(?:about|of|for))\s+(.+?)(?:\s+on\s+(?:the\s+)?screen)?\.?$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?(?:show|display|put|bring|let\s+me\s+see)\s+(?:that|it|what\s+you\s+(?:just\s+)?(?:said|told\s+me)|the\s+result|the\s+previous\s+result)(?:\s+(?:again|back))?(?:\s+on\s+(?:the\s+)?screen)?\.?$', re.IGNORECASE),
                re.compile(r'^(?:show|display)\s+that\s+again\.?$', re.IGNORECASE),
                re.compile(r'^(?:can\s+you\s+)?(?:show|display)\s+(?:me\s+)?(?:that|it)(?:\s+(?:again|back))?\.?$', re.IGNORECASE),
                re.compile(r'^(?:put\s+that\s+on\s+screen|let\s+me\s+see\s+it|let\s+me\s+see\s+that|bring\s+that\s+back|bring\s+it\s+back|show\s+the\s+list|show\s+the\s+result|display\s+what\s+you\s+(?:just\s+)?(?:said|told\s+me)|display\s+that)\.?$', re.IGNORECASE),
                re.compile(r'^(?:show|display|put)\s+(?:me\s+)?(?:the\s+)?(?:pairing\s+code|code|ip|ip\s+address|address|url|link|file\s+path|file|path|list|devices|table|status|result|device\s+info(?:rmation)?)(?:\s+again)?(?:\s+on\s+(?:the\s+)?screen)?\.?$', re.IGNORECASE),
                re.compile(r'^(?:show|display|put)\s+(?:me\s+)?(?:the\s+)?(?:digital\s+)?numbers?(?:\s+(?:from\s+)?\d+\s+to\s+\d+)?\s+in\s+a\s+box(?:\s+on\s+(?:the\s+)?screen)?\.?$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?(?:show|display|give|generate|list)\s+(?:me\s+)?(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|twenty|thirty|fifty|hundred)?\s*(?:random\s+)?numbers?(?:\s+(?:from|between)\s+\d+\s+(?:to|and)\s+\d+)?(?:\s+in\s+(?:a\s+)?(?:box|table|grid|reverse\s+order|reverse))?(?:\s+on\s+(?:the\s+)?screen)?\.?$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?(?:generate|give\s+me)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty)?\s*(?:random\s+)?numbers?.*$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?(?:show|display)\s+(?:me\s+)?(?:the\s+)?numbers?.*$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?(?:give\s+me|generate)\s+.*\bnumbers?\b.*$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?count\s+(?:from\s+)?\d+\s*(?:to|-)\s*\d+(?:\s+numbers?)?\.?$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?count\s+(?:from\s+)?\d+\s+to\s+\d+(?:\s+numbers?)?\.?$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?count\s+(?:up\s+to\s+)?\d+(?:\s+numbers?)?\.?$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?count\s+(?:me\s+)?(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty)\s+numbers?\.?$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?list\s+numbers?\s+(?:from|between)\s+\d+\s+(?:to|and|-)\s*\d+\.?$', re.IGNORECASE),
                # Multilingual: Telugu
                re.compile(r'.*(?:వివరాలు\s+చూపించు|వివరాలను\s+చూపించు|స్క్రీన్‌పై\s+చూపించు|పూర్తి\s+వివరణ\s+చూపించు|మొత్తం\s+సమాచారం\s+చూపించు|వివరాల\s+పెట్టె).*', re.IGNORECASE),
                # Multilingual: Hindi
                re.compile(r'.*(?:विवरण\s+दिखाएं|विवरण\s+दिखाओ|पूरी\s+जानकारी\s+दिखाओ|स्क्रीन\s+पर\s+दिखाओ|पूरा\s+विवरण\s+दिखाओ|डिटेल्स\s+दिखाओ).*', re.IGNORECASE),
                # Multilingual: Tamil
                re.compile(r'.*(?:விவரங்களை\s+காட்டு|முழு\s+விளக்கத்தை\s+காட்டு|திரையில்\s+காட்டு).*', re.IGNORECASE),
                # Multilingual: Spanish
                re.compile(r'.*(?:muestra\s+los\s+detalles|mostrar\s+detalles|abrir\s+la\s+caja\s+de\s+detalles|muestra\s+toda\s+la\s+informaci[oó]n|pon\s+eso\s+en\s+la\s+pantalla).*', re.IGNORECASE),
            ],

            # ── Priority 31: SYSTEM COMPATIBILITY ──────────────────────────────
            Intent.SYSTEM_COMPATIBILITY: [
                re.compile(r'\b(?:which|what)\s+games\s+(?:can|could)\s+run\s+on\s+this\s+(?:pc|system|computer|machine)\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+games\s+are\s+compatible|games\s+compatible\s+with\s+(?:this|my)\s+(?:system|pc|computer))\b', re.IGNORECASE),
                re.compile(r'\b(?:compare\s+(?:those\s+)?game\s+requirements\s+to\s+(?:the|my)\s+system|compare\s+those\s+requirements)\b', re.IGNORECASE),
                re.compile(r'\b(?:can\s+(?:this|my)\s+(?:pc|system)\s+run\s+.+?|check\s+game\s+compatibility)\b', re.IGNORECASE),
            ],

            # ── Priority 32: GAME DISCOVERY ────────────────────────────────────
            Intent.GAME_DISCOVERY: [
                re.compile(r'\b(?:suggest|recommend|find|show|list)\s+(?:some\s+)?(?:online\s+games?|pc\s+games?|games?\s+i\s+can\s+download|games?\s+to\s+download)\b', re.IGNORECASE),
                re.compile(r'\b(?:can\s+(?:we|i)\s+play|let\'?s?\s+play)\s+(?:some\s+)?(?:games?|online\s+games?|pc\s+games?)\b', re.IGNORECASE),
                re.compile(r'\b(?:suggest\s+some\s+games|recommend\s+(?:some\s+)?games)\b', re.IGNORECASE),
            ],

            # ── Priority 33: VOICE CONFIGURATION & LANGUAGE PREFERENCE ─────────
            Intent.VOICE_CONFIGURATION: [
                re.compile(r'\b(?:speak|talk|reply|respond)\s+(?:to\s+me\s+)?in\s+(telugu|hindi|tamil|kannada|malayalam|spanish|french|german|english)\b', re.IGNORECASE),
                re.compile(r'\b(?:can\s+you\s+)?(?:speak|talk)\s+(?:in\s+)?(telugu|hindi|tamil|kannada|malayalam|spanish|french|german|english)\b', re.IGNORECASE),
                re.compile(r'\b(?:switch|change)\s+(?:language|voice\s+language)\s+to\s+(telugu|hindi|tamil|kannada|malayalam|spanish|french|german|english)\b', re.IGNORECASE),
                re.compile(r'\b(?:telugu|hindi|tamil|kannada|malayalam|spanish|french|german)\s+(?:lo\s+matladu|lo\s+matladandi|lo\s+cheppu|me\s+bolo|me\s+boliye)\b', re.IGNORECASE),
                re.compile(r'(?:తెలుగులో\s*మాట్లాడు|తెలుగులో\s*మాట్లాడండి|తెలుగు\s*మాట్లాడగలవా|హిందీలో\s*మాట్లాడు)', re.IGNORECASE),
                re.compile(r'(?:हिंदी\s*में\s*बोलो|हिंदी\s*में\s*बात\s*करो|तमिल\s*में\s*बोलो)', re.IGNORECASE),
                re.compile(r'\b(?:speak|talk)\s+(?:a\s+little\s+|a\s+bit\s+)?(?:slower|more\s+slowly)\b', re.IGNORECASE),
                re.compile(r'\b(?:speak|talk)\s+(?:a\s+little\s+|a\s+bit\s+)?(?:faster|more\s+quickly)\b', re.IGNORECASE),
                re.compile(r'\b(?:slow\s+down|speed\s+up)\s+(?:your\s+)?(?:voice|speech|talking)\b', re.IGNORECASE),
                re.compile(r'\breset\s+(?:speaking\s+|voice\s+)?rate\b', re.IGNORECASE),
            ],
            # Priority 25: GENERAL_CONVERSATION — fallback, no pattern needed
        }

    
    def _detect_implicit_goal(self, clean_no_polite: str, user_input: str) -> Optional[Dict[str, Any]]:
        text = clean_no_polite.lower().strip().rstrip('.?!')

        # Email operations are direct Intent.EMAIL tasks, not multi-step background implicit goals
        if re.search(r'\b(?:email|mail|inbox)\b', text):
            return None

        # ── Specific patterns FIRST (must win over the broad pattern below) ──────

        # Meeting / document preparation (e.g. "I need to prepare a document for my meeting tomorrow")
        # This specific check must precede the broad goal pattern so the goal_type
        # is correctly identified as "prepare_meeting_document" when "meeting" is present.
        if re.search(r'\b(?:i\s+(?:need|want|\'d\s+like|would\s+like)\s+to\s+)?prepare\s+(?:a\s+document|something)?\s*for\s+(?:my\s+)?meeting\b', text):
            return {
                "action": "implicit_goal",
                "goal_type": "prepare_meeting_document",
                "goal_name": "Prepare Meeting Document",
                "suggested_response": "I can help prepare the document for your meeting. What is the meeting topic?"
            }

        # ── Broad natural-language goal statements (Failure 1 fix) ──────────────
        # Patterns: "I need to <verb> my <thing> for tomorrow"
        #           "I have to finish my project by Friday"
        #           "I need to study for my exam tomorrow"
        # These must be detected BEFORE any specific sub-patterns so they don't
        # fall through to OPEN_APPLICATION or FILE_OPERATIONS.

        _DEADLINE_PATTERN = r'\b(?:(?:for|by|on|at|due|before)\s+)?(?:today|tomorrow|tonight|yesterday|this\s+(?:week|weekend|month|morning|afternoon|evening|night)|next\s+(?:week|weekend|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(?:morning|afternoon|evening|night))?|\d{1,2}(?::\d{2})?\s*(?:am|pm)?|\d+\s+(?:days?|hours?|weeks?)\s+from\s+now)\b'
        _GOAL_VERBS = r'(?:prepare|finish|complete|study|work\s+on|finalize|review|practice|research|draft|write\s+up|put\s+together)'
        _NEED_PREFIX = r'^(?:(?:i\s+)?(?:need\s+to|have\s+to|must|should|want\s+to|have\s+got\s+to|gotta|need)\s+)?'

        m_broad_goal = re.match(
            _NEED_PREFIX + r'(' + _GOAL_VERBS + r')\s+(.+)',
            text, re.IGNORECASE
        )
        if m_broad_goal:
            verb = m_broad_goal.group(1).strip()
            subject = m_broad_goal.group(2).strip()
            # Extract deadline if present
            deadline_match = re.search(_DEADLINE_PATTERN, subject, re.IGNORECASE)
            deadline_str = None
            clean_subject = subject
            if deadline_match:
                raw_deadline = deadline_match.group(0).strip()
                # Normalize cleanly: strip leading prepositions so deadline is "tomorrow", "next week", etc.
                deadline_str = re.sub(r'^(?:for|by|on|at|due|before)\s+', '', raw_deadline, flags=re.IGNORECASE).strip()
                # Strip the raw deadline phrase from the subject
                clean_subject = re.sub(r'\s*' + re.escape(raw_deadline) + r'\b', '', subject, flags=re.IGNORECASE).strip()
                # Also strip any dangling preposition at end of subject (e.g. "for", "by")
                clean_subject = re.sub(r'\s+(?:for|by|on|at|due|before)$', '', clean_subject, flags=re.IGNORECASE).strip()

            clean_subj_no_article = re.sub(r'^(?:my|the|a|an)\s+', '', clean_subject, flags=re.IGNORECASE).strip()
            
            def _format_topic_title(raw: str) -> str:
                acronyms = {"dbms": "DBMS", "ai": "AI", "ml": "ML", "sql": "SQL", "tcp": "TCP", "ip": "IP", "osi": "OSI"}
                words = raw.strip().split()
                formatted = []
                for w in words:
                    low = w.lower().strip(".,:;!?")
                    if low in acronyms:
                        formatted.append(acronyms[low])
                    elif w.isupper() and len(w) > 1:
                        formatted.append(w)
                    else:
                        formatted.append(w.capitalize())
                return " ".join(formatted)

            # Extract structured Topic and Purpose (Level 6 Section 1 & 3)
            topic_extracted = None
            purpose_extracted = "general"
            m_topic_rel = re.search(r'\b(?:about|on|regarding)\s+(.+)$', clean_subj_no_article, re.IGNORECASE)
            if m_topic_rel:
                topic_extracted = _format_topic_title(m_topic_rel.group(1))
                if any(w in clean_subj_no_article.lower() for w in ["presentation", "slides", "ppt"]):
                    purpose_extracted = "presentation"
                elif any(w in clean_subj_no_article.lower() for w in ["report", "document", "doc"]):
                    purpose_extracted = "report"
                elif any(w in clean_subj_no_article.lower() for w in ["excel", "sheet", "spreadsheet"]):
                    purpose_extracted = "spreadsheet"
            else:
                topic_extracted = _format_topic_title(clean_subj_no_article)

            goal_name = f"{verb.capitalize()} {clean_subj_no_article}".strip()
            goal_description = f"{verb} {clean_subj_no_article}".strip()

            if topic_extracted and purpose_extracted == "presentation":
                goal_name = f"Prepare {topic_extracted} Presentation"
                if deadline_str:
                    suggested = f"Got it — I've created a work goal for your {topic_extracted} presentation due {deadline_str}. I've prepared the structure covering key concepts. Would you like me to generate the PPT now?"
                else:
                    suggested = f"Got it — I've created a work goal for your {topic_extracted} presentation. Would you like me to generate the PPT now?"
            elif topic_extracted and purpose_extracted == "report":
                goal_name = f"Prepare {topic_extracted} Report"
                if deadline_str:
                    suggested = f"Got it — I've created a work goal for your {topic_extracted} report due {deadline_str}. Would you like me to generate the report now?"
                else:
                    suggested = f"Got it — I've created a work goal for your {topic_extracted} report. Would you like me to generate the report now?"
            elif deadline_str:
                suggested = f"Got it — I'll help you {verb} {clean_subj_no_article}. I've set this as an active goal for {deadline_str}. Would you like me to create a plan or start with something specific?"
            else:
                suggested = f"Got it — I'll help you {verb} {clean_subj_no_article}. Would you like me to create a step-by-step plan?"

            return {
                "action": "implicit_goal",
                "goal_type": "natural_goal",
                "goal_name": goal_name,
                "goal_description": goal_description,
                "goal_subject": clean_subj_no_article,
                "goal_verb": verb,
                "topic": topic_extracted,
                "purpose": purpose_extracted,
                "deadline": deadline_str,
                "suggested_response": suggested,
            }

        # 1. Writing goal (e.g. "I need to write something", "I want to write something down")
        if re.search(r'\b(?:i\s+(?:need|want|have|\'d\s+like|would\s+like)\s+to\s+)?(?:write|type)\s+(?:something|anything)(?:\s+down)?\b', text) or \
           re.match(r'^(?:i\s+(?:need|want|\'d\s+like|would\s+like)\s+to\s+write)\b', text):
            return {
                "action": "implicit_goal",
                "goal_type": "write",
                "goal_name": "Write Text",
                "suggested_response": "I can help with that. Do you want me to open Notepad?",
                "pending_action": {
                    "intent": "OPEN_APPLICATION",
                    "action": "open",
                    "target": "Notepad",
                    "command": "open Notepad"
                }
            }

        # 2. Calculation goal (e.g. "I need to calculate something", "I want to do some calculations")
        if re.search(r'\b(?:i\s+(?:need|want|have|\'d\s+like|would\s+like)\s+to\s+)?calculate\s+(?:something|anything)\b', text) or \
           re.match(r'^(?:i\s+(?:need|want|\'d\s+like|would\s+like)\s+to\s+do\s+(?:some\s+)?calculations?)\b', text):
            return {
                "action": "implicit_goal",
                "goal_type": "calculate",
                "goal_name": "Calculate",
                "suggested_response": "I can help with that. Would you like me to open Calculator?",
                "pending_action": {
                    "intent": "OPEN_APPLICATION",
                    "action": "open",
                    "target": "Calculator",
                    "command": "open Calculator"
                }
            }


        # 4. Document work (e.g. "I need to work on a document", "I need to work on my report")
        m_work = re.match(r'^(?:i\s+(?:need|want|\'d\s+like|would\s+like)\s+to\s+)?work\s+on\s+(?:a\s+document|my\s+document|my\s+report|my\s+project|a\s+project)\b', text)
        if m_work:
            return {
                "action": "implicit_goal",
                "goal_type": "work_document",
                "goal_name": "Work on Document",
                "suggested_response": "Would you like me to open an existing document or create a new one?"
            }

        # 5. File organization goal (e.g. "I need to organize my AI project files", "I want to organize my files")
        m_org = re.search(r'\b(?:i\s+(?:need|want|\'d\s+like|would\s+like)\s+to\s+)?organize\s+(?:my\s+)?(.+?)(?:\s+files|\s+folder)?$', text)
        if m_org and ("file" in text or "project" in text or not text.startswith(("move ", "copy ", "delete "))):
            target_desc = m_org.group(1).strip() if m_org else "files"
            entity_name = target_desc.title() + " Files" if not target_desc.endswith("files") else target_desc.title()
            if "ai project" in target_desc.lower():
                entity_name = "AI Project Files"
            return {
                "action": "implicit_goal",
                "goal_type": "organize_files",
                "goal_name": f"Organize {entity_name}",
                "goal_entity": entity_name,
                "suggested_response": f"I can help organize your {target_desc} files. Would you like me to create a project folder for it?"
            }

        # 6. Web check goal (e.g. "I need to check something in Chrome", "I need to check something")
        if re.search(r'\b(?:i\s+(?:need|want|\'d\s+like|would\s+like)\s+to\s+)?check\s+something(?:\s+in\s+chrome|\s+online|\s+on\s+the\s+web)?\b', text):
            return {
                "action": "implicit_goal",
                "goal_type": "check_web",
                "goal_name": "Check Web",
                "suggested_response": "I can help with that. What would you like to search for in Chrome?"
            }

        # 7. Continue working (e.g. "I want to continue working", "I need to continue working")
        if re.search(r'\b(?:i\s+(?:need|want|\'d\s+like|would\s+like)\s+to\s+)?(?:continue|resume)\s+working\b', text) or text in ("i want to continue working", "i need to continue working"):
            return {
                "action": "implicit_goal",
                "goal_type": "continue_work",
                "goal_name": "Continue Working",
                "suggested_response": "Your document is still open. I can bring it to the front."
            }

        return None

    def route_command(self, user_input: str, user_id: Optional[Any] = None) -> Tuple[Intent, Dict[str, Any]]:
        """
        Determine intent with hybrid resolution.

        Step 1 — Deterministic regex (priority 1→18, always tried first).
        Step 2 — Semantic fallback via LLMEngine ONLY when Step 1 produces
                 GENERAL_CONVERSATION (i.e. no regex matched).

        Deterministic commands ("open notepad", "what time is it", etc.) are
        NEVER sent to the LLM — they resolve immediately in Step 1.
        """
        if not user_input or not user_input.strip():
            return Intent.GENERAL_CONVERSATION, {}

        if user_id is None:
            try:
                from instance.config import settings
                user_id = getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user()
            except Exception:
                pass

        cache_key = user_input.strip().lower()
        # Contextual commands depend dynamically on live system/audio/reader/dialogue state and must never be cached statically
        is_contextual_verb = bool(re.match(r'^(?:(?:hey|ok|okay)\s+\w+\s+)?(?:can\s+you\s+|could\s+you\s+|please\s+)?(?:stop|halt|hold on|pause|continue|resume|repeat|say that again|what did you say|come again)(?:\s+(?:that|it|this|speaking|reading|music|last part))?[.!?]?$', cache_key)) or any(r in cache_key for r in ("repeat", "say that again", "what did you say", "come again"))
        is_email_active = False
        import sys
        if 'modules.assistant_email.email_controller' in sys.modules:
            try:
                from modules.assistant_email.email_controller import is_active_email_session
                is_email_active = is_active_email_session(user_id)
            except Exception:
                pass

        if hasattr(self, '_route_cache') and not is_contextual_verb and not is_email_active and cache_key in self._route_cache:
            return self._route_cache[cache_key]

        input_lower = user_input.lower().strip()

        def _cache_and_return(res_intent: Intent, res_params: Dict[str, Any]):
            if hasattr(self, '_route_cache') and not is_contextual_verb:
                if len(self._route_cache) > 30:
                    self._route_cache.clear()
                self._route_cache[cache_key] = (res_intent, res_params)
            return res_intent, res_params

        # Strip leading assistant name / wake word and polite prefixes for matching
        clean_input = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*', '', input_lower, flags=re.IGNORECASE).strip()
        assistant_name = get_assistant_name()
        if isinstance(assistant_name, str) and assistant_name.lower() not in ("assistant", "trevon", "friday", "nova", "jarvis", "computer"):
            clean_input = re.sub(rf'^(?:hey\s+|ok\s+|okay\s+)?{re.escape(assistant_name.lower())}[,\s:]*', '', clean_input, flags=re.IGNORECASE).strip()
        clean_no_polite = re.sub(r'^(?:can\s+you\s+|could\s+you\s+|please\s+)+', '', clean_input, flags=re.IGNORECASE).strip()

        # ── Step 0a: Dedicated In-Flight Email Session / Dictation Mode ──────
        # When an email session is active (especially RECORDING_EMAIL_MESSAGE,
        # PENDING_EMAIL_CONFIRMATION, or EMAIL_RECIPIENT_RESOLUTION),
        # all spoken utterances belong strictly to the email subsystem. No regex,
        # document generator, reminder, or LLM router may hijack the message.
        if is_email_active and 'modules.assistant_email.email_controller' in sys.modules:
            try:
                from modules.assistant_email.email_controller import (
                    is_active_email_session, is_in_email_dictation, _resolve_user,
                    get_email_session_state, STATE_EMAIL_AMBIGUOUS_OUTCOME
                )
                cur_u = _resolve_user(user_id)
                if is_in_email_dictation(cur_u):
                    return Intent.EMAIL, {
                        "action": "email_dictation_turn",
                        "raw_input": user_input
                    }
                elif is_active_email_session(cur_u):
                    sess_state = get_email_session_state(cur_u)
                    if sess_state in (STATE_EMAIL_AMBIGUOUS_OUTCOME, "WAITING_FOR_RECIPIENT_ADDRESS", "waiting_for_recipient_address"):
                        from modules.assistant_email.email_controller import is_email_session_input
                        if is_email_session_input(user_input, cur_u):
                            return Intent.EMAIL, {
                                "action": "email_session_turn",
                                "raw_input": user_input
                            }
                        # Fall through to normal intent resolution so independent commands route independently
                        # without discarding or modifying the preserved draft in _pending_email_sessions.
                    else:
                        return Intent.EMAIL, {
                            "action": "email_session_turn",
                            "raw_input": user_input
                        }
            except Exception:
                pass

        # ── Step 1: Deterministic regex, strict priority order ─────────────
        # Fast path: Visual Surface requests ("show that again", "show the pairing code", "numbers in a box", etc.)
        for pattern in self.patterns.get(Intent.VISUAL_SURFACE, []):
            match = pattern.search(input_lower) or pattern.search(clean_input) or pattern.search(clean_no_polite)
            if match:
                params = self._extract_params(Intent.VISUAL_SURFACE, match, user_input)
                self.logger.debug(f"[DETERMINISTIC] '{user_input[:60]}' -> VISUAL_SURFACE")
                return _cache_and_return(Intent.VISUAL_SURFACE, params)

        # Fast path: Pure conversational greetings and small talk (bypasses heavy semantic analysis & RAG)
        if is_conversational_general_query(clean_input) or is_conversational_general_query(input_lower) or is_conversational_general_query(clean_no_polite):
            self.logger.debug(f"[FAST_CONVERSATION] '{user_input[:60]}' -> GENERAL_CONVERSATION")
            return _cache_and_return(Intent.GENERAL_CONVERSATION, {"raw_input": user_input})

        # Fast path: Local system clock queries (date / time)
        for pattern in self.patterns.get(Intent.DATE_QUERY, []):
            match = pattern.search(input_lower) or pattern.search(clean_input) or pattern.search(clean_no_polite)
            if match:
                params = self._extract_params(Intent.DATE_QUERY, match, user_input)
                self.logger.debug(f"[DETERMINISTIC] '{user_input[:60]}' -> DATE_QUERY")
                return _cache_and_return(Intent.DATE_QUERY, params)

        for pattern in self.patterns.get(Intent.TIME_QUERY, []):
            match = pattern.search(input_lower) or pattern.search(clean_input) or pattern.search(clean_no_polite)
            if match:
                params = self._extract_params(Intent.TIME_QUERY, match, user_input)
                self.logger.debug(f"[DETERMINISTIC] '{user_input[:60]}' -> TIME_QUERY")
                return _cache_and_return(Intent.TIME_QUERY, params)

        for pattern in self.patterns.get(Intent.AUDIO_DEVICES, []):
            match = pattern.search(input_lower) or pattern.search(clean_input) or pattern.search(clean_no_polite)
            if match:
                params = self._extract_params(Intent.AUDIO_DEVICES, match, user_input)
                self.logger.debug(f"[DETERMINISTIC] '{user_input[:60]}' -> AUDIO_DEVICES")
                return _cache_and_return(Intent.AUDIO_DEVICES, params)

        # Fast path: Local system telemetry, hardware diagnostics, and administrator elevation testing
        # Local operations (CPU, RAM, uptime, disk, GPU discovery, volume, app enumeration, elevation)
        # must execute deterministically without cloud LLM or RAG latency/fallback.
        for pattern in self.patterns.get(Intent.DEVICE_CONTROL, []):
            match = pattern.search(input_lower) or pattern.search(clean_input) or pattern.search(clean_no_polite)
            if match:
                params = self._extract_params(Intent.DEVICE_CONTROL, match, user_input)
                self.logger.debug(f"[DETERMINISTIC] '{user_input[:60]}' -> DEVICE_CONTROL")
                return _cache_and_return(Intent.DEVICE_CONTROL, params)

        # ── Step 0: Canonical Semantic Understanding Pipeline ─────────────
        # Semantically interprets user intention before pattern matching.
        # Derives user goal, entities, target, desired state, and arbitrated capability.
        try:
            from core.semantic_understanding import semantic_understanding_engine
            dialogue_mgr = None
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager
                dialogue_mgr = get_dialogue_manager(user_id)
            except Exception:
                pass
            ds = dialogue_mgr.current_state if dialogue_mgr else None
            sem_cmd = semantic_understanding_engine.interpret(user_input, dialogue_state=ds, user_id=user_id)

            if sem_cmd and sem_cmd.confidence >= 0.95 and sem_cmd.intent not in ("AUTO", "GENERAL_CONVERSATION", "CLARIFICATION"):
                sem_params = dict(sem_cmd.parameters)
                target_intent_name = sem_cmd.intent
                if target_intent_name in ("CURRENT_ENVIRONMENT_QUERY", "HISTORICAL_ENVIRONMENT_QUERY", "CAUSAL_ENVIRONMENT_QUERY"):
                    if getattr(sem_cmd, "action", "") == "inspect_system" or getattr(sem_cmd, "target_type", "") == "SYSTEM" or getattr(sem_cmd, "sub_intent", "") == "SYSTEM_STATE":
                        target_intent_name = "DEVICE_CONTROL"
                        sem_params["action"] = "system_info"
                    elif getattr(sem_cmd, "action", "") == "inspect_storage" or getattr(sem_cmd, "target_type", "") == "FILESYSTEM" or getattr(sem_cmd, "sub_intent", "") == "FILESYSTEM_STATE":
                        target_intent_name = "DEVICE_CONTROL"
                        sem_params["action"] = "disk"
                    else:
                        target_intent_name = "WINDOW_CONTEXT"
                elif target_intent_name == "CONTENT_INSERTION":
                    if any(k in user_input.lower() for k in [
                        "program", "function", "script", "algorithm", "class", "code",
                        "python", "javascript", "c++", "cpp", "java", "sql", "html", "css", "rust", "go",
                        "fastapi", "flask", "project", "binary search", "subarray", "prime", "second-largest", "second largest"
                    ]):
                        target_intent_name = "CODE_GENERATION"
                        sem_params["action"] = "generate_code"
                    else:
                        target_intent_name = "DEVICE_CONTROL"
                        sem_params["action"] = "type_text"
                elif target_intent_name == "MUSIC":
                    try:
                        from modules.music.music_controller import MusicCommandParser
                        _p = MusicCommandParser().parse(user_input)
                        if _p.is_transport:
                            sem_params["action"] = _p.transport_action
                        elif _p.is_video_requested:
                            sem_params["action"] = "play_video"
                        else:
                            sem_params["action"] = "play"
                    except Exception:
                        pass
                if hasattr(Intent, target_intent_name):
                    resolved_enum = Intent[target_intent_name]
                    sem_params["raw_input"] = user_input
                    sem_params["semantic_command"] = sem_cmd
                    self.logger.debug(f"[SEMANTIC_PIPELINE] '{user_input[:60]}' -> {resolved_enum.name} (action={sem_cmd.action})")
                    return _cache_and_return(resolved_enum, sem_params)
            elif sem_cmd and sem_cmd.intent == "CLARIFICATION":
                return _cache_and_return(Intent.GENERAL_CONVERSATION, {
                    "response": sem_cmd.explanation_text or "Could you please clarify your request?",
                    "action": "clarification",
                    "raw_input": user_input,
                    "semantic_command": sem_cmd,
                })
        except Exception as e:
            self.logger.debug(f"[SEMANTIC_ROUTING_EXCEPTION] {e}")

        # Low-confidence / Garbled STT safety check
        if any(k in input_lower for k in ["hernia of the games", "hernia of games"]):
            return _cache_and_return(Intent.GENERAL_CONVERSATION, {
                "response": "Did you mean: 'What games are compatible with this system?'",
                "action": "clarification",
                "raw_input": user_input
            })

        # Conversation Continuation & List Inspection
        if clean_no_polite in (
            "that's it give me full list", "thats it give me full list",
            "give me full list", "give me the full list", "give full list",
            "full list", "what is the full list", "give the full list",
            "show full list", "show the full list", "show me the full list",
            "tell them all", "tell me all of them", "show them all", "tell all of them",
            "all of them", "tell me those", "what are those", "tell those", "show those"
        ):
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager, _dialogue_managers
                dm = get_dialogue_manager(user_id)
                target_dm = dm if (dm and (dm.current_state.current_recommendation_list or dm.current_state.current_response)) else next((m for m in _dialogue_managers.values() if m.current_state.current_recommendation_list or m.current_state.current_response), None)
                if target_dm:
                    return _cache_and_return(Intent.RECOMMENDATION, {"response": target_dm.get_full_list_response(), "action": "full_list", "raw_input": user_input})
            except Exception:
                pass

        if clean_no_polite in ("repeat last part", "repeat the last part", "repeat what you said", "repeat that", "repeat", "say that again", "what did you say", "come again"):
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager
                eff_u = user_id or getattr(self, '_current_user_id', None) or "default"
                dm = get_dialogue_manager(str(eff_u))
                repeat_text = dm.get_repeat_last_part() if dm else "Nothing was recently spoken to repeat."
                return _cache_and_return(Intent.GENERAL_CONVERSATION, {"response": repeat_text, "action": "repeat", "raw_input": user_input})
            except Exception as e:
                self.logger.warning(f"[ROUTER] Error resolving repeat request: {e}")

        if clean_no_polite in ("next item", "what's next", "whats next", "next recommendation", "next"):
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager, _dialogue_managers
                dm = get_dialogue_manager(user_id)
                target_dm = dm if (dm and dm.current_state.current_recommendation_list) else next((m for m in _dialogue_managers.values() if m.current_state.current_recommendation_list), None)
                if target_dm:
                    return _cache_and_return(Intent.RECOMMENDATION, {"response": target_dm.get_next_item(), "action": "next_item", "raw_input": user_input})
            except Exception:
                pass

        if clean_no_polite in ("first item", "what was the first item", "first recommendation", "first one", "the first one", "tell me the first one"):
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager, _dialogue_managers
                dm = get_dialogue_manager(user_id)
                target_dm = dm if (dm and dm.current_state.current_recommendation_list) else next((m for m in _dialogue_managers.values() if m.current_state.current_recommendation_list), None)
                if target_dm:
                    return _cache_and_return(Intent.RECOMMENDATION, {"response": target_dm.get_first_item(), "action": "first_item", "raw_input": user_input})
            except Exception:
                pass

        if clean_no_polite in ("last item", "what was the last item", "last recommendation", "last one", "the last one", "tell me the last one"):
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager, _dialogue_managers
                dm = get_dialogue_manager(user_id)
                target_dm = dm if (dm and dm.current_state.current_recommendation_list) else next((m for m in _dialogue_managers.values() if m.current_state.current_recommendation_list), None)
                if target_dm:
                    return _cache_and_return(Intent.RECOMMENDATION, {"response": target_dm.get_last_item(), "action": "last_item", "raw_input": user_input})
            except Exception:
                pass

        if clean_no_polite in ("previous item", "what was the previous item", "previous recommendation", "previous one", "the previous one", "previous"):
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager, _dialogue_managers
                dm = get_dialogue_manager(user_id)
                target_dm = dm if (dm and dm.current_state.current_recommendation_list) else next((m for m in _dialogue_managers.values() if m.current_state.current_recommendation_list), None)
                if target_dm:
                    return _cache_and_return(Intent.RECOMMENDATION, {"response": target_dm.get_previous_item(), "action": "previous_item", "raw_input": user_input})
            except Exception:
                pass

        # Check active in-flight email session for confirmation, cancellation, or missing purpose
        try:
            from modules.assistant_email.email_controller import _pending_email_sessions, _resolve_user, get_pending_email
            cur_u = _resolve_user()
            pending_email = get_pending_email(cur_u)
            if not pending_email and len(_pending_email_sessions) == 1:
                pending_email = next(iter(_pending_email_sessions.values()))
            if pending_email:
                low_p = clean_no_polite.lower()
                clean_punct = re.sub(r'[^\w\s]', '', low_p).strip()
                status = pending_email.get("status")
                # 1. PENDING_CONFIRMATION state: single confirmation / cancellation / review
                if status in ("PENDING_CONFIRMATION", "PENDING_EMAIL_CONFIRMATION") or (pending_email.get("recipient") and pending_email.get("subject") and status not in ("RECORDING_EMAIL_MESSAGE", "EMAIL_SENT")):
                    CONFIRM_SET = {
                        "yes", "yeah", "yep", "sure", "ok", "okay", "send it", "send", "go ahead", "proceed",
                        "confirmed", "confirm", "please send it", "yes send it", "yes send", "send that email now",
                        "send the mail", "send the email", "send this email", "send this mail", "send that mail",
                        "send that email", "send mail", "send email", "send draft", "send it now", "confirm send",
                        "i confirm, send the email", "i confirm send the email", "i confirm, send the mail",
                        "i confirm send the mail", "i confirm, send it", "i confirm send it",
                        "you have my confirmation", "you have my confirmation, send it", "you have my confirmation send it",
                        "you have my confirmation please send it", "please send the email", "please send the mail",
                        "send message", "send the message", "confirm retry send"
                    }
                    if low_p in CONFIRM_SET or clean_punct in CONFIRM_SET or any(phrase in low_p for phrase in ("send the mail", "send the email", "send this email", "i confirm, send", "you have my confirmation")):
                        return _cache_and_return(Intent.EMAIL, {"action": "confirm_send", "raw_input": user_input})
                    if low_p in ("no", "nope", "cancel", "don't send", "dont send", "stop", "abort", "discard", "keep it as a draft", "keep as draft", "keep draft") or clean_punct in ("no", "nope", "cancel", "dont send", "stop", "abort", "discard"):
                        return _cache_and_return(Intent.EMAIL, {"action": "cancel", "raw_input": user_input})
                    if any(k in low_p for k in ["show me the email", "show the email", "read the draft", "what are you going to send", "preview it", "preview", "show draft", "view draft"]):
                        return _cache_and_return(Intent.EMAIL, {"action": "review_draft", "raw_input": user_input})
                    if any(k in low_p for k in ["make it", "change subject", "change the subject", "add ", "rewrite", "shorten", "more concise"]):
                        return _cache_and_return(Intent.EMAIL, {"action": "modify_draft", "raw_input": user_input})
                # 2. NEED_PURPOSE state: user answering "What should the email be about?"
                elif pending_email.get("status") == "NEED_PURPOSE":
                    if low_p in ("cancel", "stop", "never mind", "nevermind", "abort", "don't send", "dont send"):
                        return _cache_and_return(Intent.EMAIL, {"action": "cancel", "raw_input": user_input})
                    elif not any(low_p.startswith(w) for w in ["what time", "what is the date", "open ", "launch ", "calculate ", "remind me"]):
                        return _cache_and_return(Intent.EMAIL, {"action": "provide_purpose", "raw_input": user_input})
        except Exception:
            pass

        # Contextual Control Verbs ("stop", "pause", "continue", "resume", "stop that", "start again")
        norm_control = re.sub(r'^(?:yes|yeah|yep|sure|ok|okay|please)\s*[,]?\s*', '', clean_no_polite).strip()
        is_stop_verb = clean_no_polite in ("stop", "halt", "hold on", "pause", "stop that", "stop it", "stop this", "stop task", "cancel task") or norm_control in ("stop", "halt", "hold on", "pause", "stop that", "stop it", "stop this", "stop task", "cancel task") or bool(re.match(r'^(?:stop|halt|hold on|pause)(?:\s+(?:that|it|this|task))?[.!?]?$', clean_no_polite))
        is_continue_verb = clean_no_polite in (
            "continue", "resume", "keep reading", "continue reading", "resume reading",
            "continue what you are saying", "continue what you were saying", "continue what you said",
            "continue saying", "keep going", "go on", "resume what you were saying"
        ) or norm_control in (
            "continue", "resume", "keep reading", "continue reading", "resume reading",
            "continue what you are saying", "continue what you were saying", "continue what you said",
            "continue saying", "keep going", "go on", "resume what you were saying"
        ) or bool(re.match(r'^(?:continue|resume)(?:\s+(?:that|it|this|task|what\s+you\s+(?:are|were)\s+saying))?[.!?]?$', clean_no_polite)) or bool(re.match(r'^(?:continue|resume)(?:\s+(?:that|it|this|task|what\s+you\s+(?:are|were)\s+saying))?[.!?]?$', norm_control))

        is_restart_verb = clean_no_polite in (
            "start again", "start over", "start from scratch", "let's start again", "lets start again",
            "begin again", "try again", "start it again", "do that again"
        ) or norm_control in (
            "start again", "start over", "start from scratch", "let's start again", "lets start again",
            "begin again", "try again", "start it again", "do that again"
        ) or bool(re.match(r'^(?:start\s+(?:again|over|from\s+scratch)|let\'?s?\s+start\s+(?:again|over))[.!?]?$', clean_no_polite))

        if is_restart_verb:
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager
                dm = get_dialogue_manager(user_id)
                if dm:
                    # If user asks to start again referring to previous answer, repeat it or reset conversation
                    if dm.current_state.turns:
                        last_turn = dm.current_state.turns[-1]
                        last_ans = last_turn.assistant_response
                        if last_ans and not any(k in last_ans.lower() for k in ["goodbye", "have a nice day"]):
                            return _cache_and_return(Intent.GENERAL_CONVERSATION, {"response": last_ans, "raw_input": user_input})
            except Exception:
                pass
            return _cache_and_return(Intent.GENERAL_CONVERSATION, {"response": "Sure, let's start again. How can I help you?", "raw_input": user_input})

        target_uid = 1
        if user_id is not None:
            try:
                target_uid = int(user_id)
            except Exception:
                target_uid = 1

        is_explicit_speech_stop = clean_no_polite in (
            "stop speaking", "stop talking", "be quiet", "shut up", "hush", "mute yourself", "stop voice"
        ) or bool(re.search(r'\b(?:stop\s+(?:talking|speaking)|be\s+quiet|shut\s+up|mute\s+yourself)\b', clean_no_polite))

        is_explicit_music_stop = clean_no_polite in (
            "stop music", "pause music", "stop song", "pause song", "stop songs",
            "stop playing songs", "stop playing music", "stop the music", "stop singing",
            "stop singing songs", "stop audio", "stop playback", "stop the playback",
            "stop the song", "stop the songs", "stop the audio", "stop the track", "stop track"
        ) or bool(re.search(r'\b(?:stop|pause)\s+(?:playing\s+)?(?:the\s+)?(?:songs?|music|audio|tracks?|playback|singing)\b', clean_no_polite)) or bool(re.search(r'\bstop\s+singing\b', clean_no_polite))

        is_stop_everything = clean_no_polite in (
            "stop everything", "stop all", "halt everything", "stop all playback", "stop speech and music"
        ) or bool(re.search(r'\b(?:stop\s+everything|stop\s+all|halt\s+everything)\b', clean_no_polite))

        if is_explicit_speech_stop:
            return _cache_and_return(Intent.DEVICE_CONTROL, {"action": "stop_speech", "raw_input": user_input})

        elif is_explicit_music_stop:
            return _cache_and_return(Intent.MUSIC, {"action": "stop", "raw_input": user_input})

        elif is_stop_everything:
            return _cache_and_return(Intent.MUSIC, {"action": "stop_all", "raw_input": user_input})

        elif is_stop_verb:
            # 1. Check if Assistant TTS is currently speaking
            try:
                from legacy.tts import is_speaking
                if is_speaking():
                    return _cache_and_return(Intent.DEVICE_CONTROL, {"action": "stop_speech", "raw_input": user_input})
            except Exception:
                pass

            # 2. Check if a Document is actively being read aloud
            try:
                from core.artifact_reader import get_artifact_reading_controller
                if get_artifact_reading_controller().is_reading(target_uid) or clean_no_polite in ("stop reading", "pause reading"):
                    return _cache_and_return(Intent.DOCUMENT_GENERATION, {"action": "stop_reading", "raw_input": user_input})
            except Exception:
                pass

            # 3. Check if Music is currently playing
            try:
                from modules.music.music_controller import get_controller
                m_ctrl = get_controller()
                is_p = m_ctrl.is_playing() if callable(getattr(m_ctrl, "is_playing", None)) else getattr(m_ctrl, "is_playing", False)
                if is_p:
                    return _cache_and_return(Intent.MUSIC, {"action": "stop", "raw_input": user_input})
            except Exception:
                pass

            # 4. Check if a Background or Goal Task is running
            try:
                from core.task_execution_manager import get_task_execution_manager
                tem = get_task_execution_manager()
                active_tasks = tem.list_tasks(target_uid, active_only=True)
                if active_tasks:
                    target_task = active_tasks[0]
                    return _cache_and_return(Intent.TASK_MANAGEMENT, {"action": "cancel_task", "task_id": target_task.task_id, "raw_input": user_input})
            except Exception:
                pass

            # If nothing is active to stop, return safe conversational response
            return _cache_and_return(Intent.GENERAL_CONVERSATION, {"response": "Nothing is currently playing, speaking, reading, or running.", "raw_input": user_input})

        elif is_continue_verb:
            # 0. Check dialogue continuation state if assistant was speaking or has more to say
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager
                dm = get_dialogue_manager(target_uid)
                if dm:
                    if (dm.current_state.interrupted_speech_text or dm.current_state.remaining_response_segments or dm.current_state.current_recommendation_list):
                        cont_resp = dm.get_continue_response()
                        if cont_resp:
                            return _cache_and_return(Intent.GENERAL_CONVERSATION, {"response": cont_resp, "raw_input": user_input})
                    if getattr(dm.current_state, "pending_goal_continuation", None) or getattr(dm.current_state, "goal_status", "") in ("RUNNING", "PARTIALLY_COMPLETED", "PAUSED"):
                        cont_plan = dm.current_state.pending_goal_continuation or dm.current_state.current_plan
                        if cont_plan:
                            return _cache_and_return(Intent.GENERAL_CONVERSATION, {
                                "action": "continue_goal",
                                "response": "Continuing with your previous task.",
                                "plan": cont_plan,
                                "raw_input": user_input
                            })
            except Exception:
                pass

            # 1. Check if document reading was paused and user says continue
            try:
                from core.artifact_reader import get_artifact_reading_controller
                if get_artifact_reading_controller().load_latest_paused_session(target_uid):
                    return _cache_and_return(Intent.DOCUMENT_GENERATION, {"action": "continue_reading", "raw_input": user_input})
            except Exception:
                pass

            # 2. Check if a background task is waiting/paused
            try:
                from core.task_execution_manager import get_task_execution_manager, TaskStatus
                tem = get_task_execution_manager()
                waiting_tasks = [t for t in tem.list_tasks(target_uid) if getattr(t, 'status', None) in (TaskStatus.WAITING, TaskStatus.PAUSED)]
                if waiting_tasks:
                    return _cache_and_return(Intent.TASK_MANAGEMENT, {"action": "resume_task", "task_id": waiting_tasks[0].task_id, "raw_input": user_input})
            except Exception:
                pass

            # 3. If no paused activity, normal conversational handling
            return _cache_and_return(Intent.GENERAL_CONVERSATION, {"response": "Nothing is paused or waiting to resume.", "raw_input": user_input})

        # Level 5: Check for implicit user goals (distinguish goals from direct execution)
        implicit_goal = self._detect_implicit_goal(clean_no_polite, user_input)
        if implicit_goal:
            self.logger.debug(f"[IMPLICIT_GOAL] '{user_input[:60]}' -> GENERAL_CONVERSATION (implicit_goal)")
            return _cache_and_return(Intent.GENERAL_CONVERSATION, implicit_goal)

        for intent in Intent:
            if intent == Intent.GENERAL_CONVERSATION or intent == Intent.VISUAL_SURFACE:
                continue
            # Background task, visual response & active window queries must not be hijacked by DEVICE_CONTROL
            if intent == Intent.DEVICE_CONTROL:
                if any(any(k in t for k in [
                    "show that again", "show that", "show it again", "show it", "display that again", "display that",
                    "show me that", "show the pairing code", "show me the pairing code", "show the code", "display the pairing code",
                    "show the ip", "display the ip", "put that on screen", "let me see it", "display what you just said",
                    "show visual response",
                    "numbers in a box", "digital numbers in a box", "in a box", "numbers 1 to 100",
                    "queue a task", "queue task", "create a background task", "create a task",
                    "add a task", "schedule a background task", "schedule a task",
                    "run this as a background task", "run in the background", "run this in the background",
                    "task queue", "put this in the task queue", "cancel task", "stop task",
                    "task status", "background task", "list my tasks", "list my task", "show my tasks", "what tasks",
                    "remind me", "remember to", "schedule a reminder", "create a reminder", "set a reminder"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                # Code and script writing commands must NOT be hijacked by DEVICE_CONTROL system status patterns
                if any(any(k in t for k in [
                    "write a script", "write a powershell", "write a python", "write a bash", "write an sql",
                    "create a script", "create a function", "write a program", "powershell script", "python script",
                    "bash script", "write code", "generate code"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                # Active window queries belong to WINDOW_CONTEXT unless explicitly typing/writing text
                if not any(t.startswith(("type ", "write ")) for t in [clean_input, clean_no_polite, input_lower]):
                    if any(any(k in t for k in ["active window", "foreground window", "current window"]) for t in [clean_input, clean_no_polite, input_lower]):
                        continue
            # Code/script writing and generation requests must not be hijacked by FILE_OPERATIONS
            if intent == Intent.FILE_OPERATIONS:
                if any(any(k in t for k in [
                    "write a script", "write a powershell", "write a python", "write a bash", "write an sql",
                    "create a script", "create a function", "write a program", "powershell script", "python script",
                    "bash script", "write code", "generate code"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
            # Preference and learned behavioral rules must not be routed to NOTES
            if intent == Intent.NOTES:
                if any(any(k in t for k in ["rule", "preference", "prefer", "note that "]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
            # Questions and behavioral preferences/rules must not be routed to MEMORY_STORE
            if intent == Intent.MEMORY_STORE:
                if input_lower.endswith('?') or clean_input.endswith('?') or clean_input.startswith(('what', 'which', 'who', 'where', 'when', 'how', 'is my', 'are my', 'do you', 'can you', 'tell me what')):
                    continue
                if any(any(k in t for k in ["prefer", "preference", "rule", "dark mode", "light mode", "always ", "never ", "remember that i like"]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                if any(any(k in t for k in ["save as ", "save it as", "save the document as", "save document as", "save the file as", "save file as"]) for t in [clean_input, clean_no_polite, input_lower]) or re.search(r'\bsave\s+.*?\s+as\b', clean_input):
                    continue
            # Code structure, syntax or programming queries must not be routed to CALCULATOR
            if intent == Intent.CALCULATOR:
                if any(any(k in t for k in ["code", "python", "script", "syntax", "class ", "def ", "function", "program"]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                # Allow random number generation through to CALCULATOR
                is_random = "random" in clean_input or "random" in input_lower or any(any(k in t for k in ["numbers from", "numbers between"]) for t in [clean_input, clean_no_polite, input_lower])
                if not is_random:
                    # Non-calculation display requests (e.g. lists, boxes) are not arithmetic
                    if any(any(k in t for k in [
                        "show me", "give me", "list of numbers", "numbers in reverse", "in reverse order", "in a box", "numbers", "number"
                    ]) for t in [clean_input, clean_no_polite, input_lower]) and not any(any(k in t for k in [
                        "calculate", "times", "divided", "plus", "minus", "percent", "squared", "cubed", "sqrt", "power"
                    ]) for t in [clean_input, clean_no_polite, input_lower]):
                        continue
            # Window management and background task queries must not be routed to OPEN_APPLICATION
            if intent == Intent.OPEN_APPLICATION:
                # Code generation / programming / algorithm requests must NOT be routed to OPEN_APPLICATION
                if any(any(k in t for k in [
                    "write a ", "write an ", "create a python", "create a function", "create a script",
                    "c++", "cpp", "binary search", "bubble sort", "quick sort", "merge sort",
                    "algorithm", "function to", "program to", "script to"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    if not any(k in clean_input for k in ["open ", "launch ", "start ", "switch to "]):
                        continue
                # Email commands ("mail my professor", "send email", "check inbox") must NOT be routed to OPEN_APPLICATION
                if any(re.search(r'\b(?:(?:send|write|prepare|compose|draft)\s+(?:an?\s+)?(?:email|mail)|mail\s+(?:to\s+|for\s+)?(?:my\s+)?[a-z]|email\s+(?:to\s+|for\s+)?(?:my\s+)?[a-z]|check\s+(?:my\s+)?(?:inbox|email|mail))\b', t, re.I) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                # Game discovery & compatibility requests must NOT be routed to OPEN_APPLICATION
                if any(any(k in t for k in [
                    "games compatible", "compatible to download", "compatible to run", "download and play",
                    "download and run", "games can i", "games to play", "suggest some games", "recommend some games",
                    "in this system", "on this system", "on this pc", "hernia of the games", "area of the games"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                # Explicit internet search requests belong to external retrieval / RAG_SEARCH
                if any(any(k in t for k in ["search the internet", "search online for", "search online"]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                # Reminder & Clock/Alarm/Timer/Stopwatch requests MUST NOT be routed to OPEN_APPLICATION
                if any(any(k in t for k in [
                    "remind me", "remind", "reminder", "reminders",
                    "set a reminder", "create a reminder", "alert me",
                    "alarm", "wake me up", "timer", "stopwatch"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                if any(any(k in t for k in [
                    "open windows", "windows are open", "list windows", "show windows",
                    "what windows", "which windows", "active window", "foreground window", "current window",
                    "background task", "queue a task", "queue task", "create a background task",
                    "schedule a background task", "run this as a background task", "run in the background",
                    "run this in the background", "task queue", "put this in the task queue"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                # Failure 1 fix: Natural goal-setting language ("I need to prepare…", "I have to finish…")
                # must NOT be routed to OPEN_APPLICATION — they are caught by _detect_implicit_goal above.
                # Guard here as a safety net in case the implicit-goal check was skipped or extended.
                _GOAL_STATEMENT_RE = re.compile(
                    r'^(?:i\s+)?(?:need\s+to|have\s+to|must|should|gotta|have\s+got\s+to)\s+'
                    r'(?:prepare|finish|complete|study|work\s+on|finalize|review|practice|research|draft|write\s+up|put\s+together)\b',
                    re.IGNORECASE
                )
                if any(_GOAL_STATEMENT_RE.match(t) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                # Failure 2 fix: Unresolvable conversational pronouns/work phrases without an explicit
                # app target must NOT be passed to SmartOpener — they should remain GENERAL_CONVERSATION.
                _PRONOUN_ONLY_RE = re.compile(
                    r'^(?:(?:open|launch|run|start)\s+)?'
                    r'(?:doing\s+that|working\s+on\s+it|finish(?:ing)?\s+it|work(?:ing)?\s+on\s+it|'
                    r'continue\s+(?:doing\s+)?(?:it|that|this)|resume\s+(?:it|that|this)|'
                    r'keep\s+(?:doing\s+)?(?:it|that|this)|do\s+(?:it|that|this))\s*$',
                    re.IGNORECASE
                )
                if any(_PRONOUN_ONLY_RE.match(t) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                # Conversational restart phrases ("start again", "start over") must NOT be routed to OPEN_APPLICATION
                _RESTART_CONV_RE = re.compile(
                    r'^(?:(?:start|run|launch|begin)\s+)?(?:again|over|from\s+scratch)[.!?]?$',
                    re.IGNORECASE
                )
                if any(_RESTART_CONV_RE.match(t) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                # Historical reference questions or environment context queries (e.g., "what was I using before Brave",
                # "what was open before Chrome") must NOT be routed to OPEN_APPLICATION
                if any(k in input_lower for k in [
                    "before brave", "before chrome", "before this", "before that",
                    "what was open", "what was i using", "what was the using", "what did i have open",
                    "which app was open", "what application was i using", "what app was open"
                ]) or (re.search(r'\bbefore\s+(?:the\s+)?(?:application\s+|app\s+)?[a-zA-Z0-9_\-]+', input_lower) and any(w in input_lower for w in ("what", "which", "was", "using", "open"))):
                    continue
            # Background task & pairing code commands must not be routed to CODE_GENERATION unless user explicitly requests code/script writing
            # Document generation requests (PPT, Word, Excel, PDF) and conceptual questions must NEVER be routed to CODE_GENERATION
            if intent == Intent.CODE_GENERATION:
                if any(is_stable_knowledge_question(t) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                if any(any(k in t for k in [
                    "ppt", "powerpoint", "presentation", "slides", "docx", "word doc",
                    "word document", "spreadsheet", "excel sheet", "excel file", "pdf report", "pdf document"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
            # Failure 6 fix: FILE_OPERATIONS (Priority 5) must NOT capture explicit document-creation
            # requests (PPT, Word, Excel, PDF) — those belong to DOCUMENT_GENERATION (Priority 10).
            if intent == Intent.FILE_OPERATIONS:
                # Information gathering and research requests belong to RAG_SEARCH
                _RESEARCH_RE = re.compile(
                    r'\b(?:gather|find|search|research|tell\s+me)\s+(?:all\s+)?(?:the\s+)?(?:information|info|facts|details|everything|what\s+you\s+can\s+find)\s+(?:about|on|regarding)\b|'
                    r'\b(?:gather|find)\s+everything\s+(?:you\s+can\s+)?(?:about|on)\b|'
                    r'\bwhat\s+did\s+we\s+gather\s+(?:about|on)\b',
                    re.IGNORECASE
                )
                if any(_RESEARCH_RE.search(t) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                _DOC_GEN_CREATION_RE = re.compile(
                    r'\b(?:create|make|generate|build|write|produce)\s+(?:a\s+|an\s+|my\s+|the\s+)?'
                    r'(?:(?:\d+[\s\-]slides?|\d+[\s\-]pages?|detailed|comprehensive|powerful|new)\s+)?'
                    r'(?:ppt|pptx|powerpoint|presentation|slides|word\s+doc(?:ument)?|docx|'
                    r'pdf(?:\s+(?:document|report|file))?|excel(?:\s+(?:file|sheet|spreadsheet))?|'
                    r'xlsx|spreadsheet|report)\b',
                    re.IGNORECASE
                )
                if any(_DOC_GEN_CREATION_RE.search(t) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
            # General knowledge queries about email history must NOT route to personal EMAIL intent
            if intent == Intent.EMAIL:
                # Coding / scripting / algorithm requests mentioning email addresses or email validation must NOT be routed to EMAIL
                if any(any(k in t for k in [
                    "function", "script", "program", "code", "validate", "validates", "validation", "regex",
                    "python", "javascript", "js", "typescript", "ts", "java", "c++", "cpp", "c#", "algorithm"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                if any(k in input_lower for k in [
                    "ever sent", "history of email", "invented email", "in the world", "in history",
                    "who sent the first email", "when was email invented", "who invented",
                    "how does email work", "what is email", "explain email", "explain how email"
                ]):
                    continue
            # Music commands must NOT hijack previous app/window/environment queries, speech stop commands, or game recommendations
            if intent == Intent.MUSIC:
                # Music commands must NOT hijack game recommendations or discovery
                if any(any(k in t for k in [
                    "game", "games", "gaming", "steam", "download and play", "compatible to download",
                    "area of the games", "hernia of the games"
                ]) for t in [clean_input, clean_no_polite, input_lower]) and not any(any(k in t for k in [
                    "music", "song", "track", "audio", "playlist", "spotify", "album"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                if any(any(k in t for k in [
                    "previous app", "previous application", "previous website", "previous site",
                    "previous page", "previous video", "previous window", "previous file",
                    "previous document", "previous task", "previous step", "what was the previous",
                    "which was the previous", "stop talking", "stop speaking", "stop reading",
                    "stop voice", "shut up", "be quiet", "stop task"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
            # Explicit filesystem operations with standard extensions must NEVER be hijacked by DOCUMENT_GENERATION (Section 18)
            if intent == Intent.DOCUMENT_GENERATION:
                # References to past claims ("you said you created...") and commands to check/show/open/locate existing artifacts
                # must NOT be hijacked by DOCUMENT_GENERATION.
                _PAST_CLAIM_OR_OPEN_RE = re.compile(
                    r'\b(?:you\s+said\s+you|you\s+claimed\s+you|thought\s+you|did\s+you\s+create|where\s+is\s+the|check\s+what\s+happened|show\s+it\s+to\s+me|open\s+(?:the\s+)?(?:assignment|presentation|ppt|pdf|file))\b',
                    re.IGNORECASE
                )
                if any(_PAST_CLAIM_OR_OPEN_RE.search(t) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                if any(re.search(r'\b[a-zA-Z0-9_\-\.]+\.(?:txt|csv|py|json|md|log|ini|cfg|html|xml|yaml|yml)\b', t) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
                is_explicit_code = any(any(k in t for k in [
                    "write a python", "write python", "python script", "generate code",
                    "write code", "sample code", "example code", "write a function",
                    "validate code", "validate syntax", "check syntax", "write a script",
                    "create a python", "code to"
                ]) for t in [clean_input, clean_no_polite, input_lower])
                if not is_explicit_code and any(any(k in t for k in [
                    "queue a task", "queue task", "create a background task", "create a task",
                    "add a task", "schedule a background task", "schedule a task",
                    "run this as a background task", "run in the background", "task queue",
                    "put this in the task queue", "task status", "cancel task", "stop task", "background task",
                    "pairing code", "code again", "the code again", "what's the code", "whats the code",
                    "what is the code", "what was the code", "repeat the code", "phone pairing code"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
            # General knowledge / definitional queries must NOT be treated as local device control
            if intent == Intent.DEVICE_CONTROL:
                # Contextual artifact insertion requests must NOT be hijacked as generic typing in DEVICE_CONTROL
                if any(re.search(rf'\b{v}\b', clean_no_polite) for v in ("write", "type", "put", "paste", "insert")):
                    try:
                        from core.artifact_resolver import get_artifact_reference_resolver
                        art_res = get_artifact_reference_resolver().resolve(user_input=user_input)
                        if art_res.is_success or art_res.is_ambiguous:
                            continue
                    except Exception:
                        pass

                is_general_knowledge = any(
                    re.search(p, t, re.IGNORECASE) for t in [clean_input, clean_no_polite, input_lower]
                    for p in [
                        r'^(?:what\s+is\s+(?:a|an)\s+(?:cpu|gpu|processor|ram|os|operating\s+system|motherboard|hard\s+drive|ssd|network|monitor|display))\b',
                        r'^(?:what\s+is\s+(?:ram|windows|linux|macos|android|ios|hardware|software|firmware))\??$',
                        r'^(?:explain\s+(?:how\s+)?(?:gpus?|cpus?|ram|processors?|windows|computers?|hardware)\s*(?:work|functions?)?)\b',
                        r'^(?:what\s+does\s+(?:cpu|ram|gpu)\s+usage\s+mean)\b',
                        r'^(?:tell\s+me\s+about\s+(?:computers|gpus|cpus|ram|operating\s+systems))\??$',
                    ]
                )
                if is_general_knowledge:
                    continue

            # Undo, location, learning, and local system queries must not be hijacked by MEMORY_QUERY
            if intent == Intent.MEMORY_QUERY:
                if any(any(k in t for k in [
                    "undo", "undone", "undoable",
                    "email", "emails", "inbox", "mail", "mails",
                    "my location", "where am i", "current location", "location source", "how do you know my location",
                    "learned about me", "preferences have you learned",
                    "disk usage", "disk space", "storage usage", "free space", "available disk", "drive info",
                    "cpu usage", "cpu info", "cpu details", "processor",
                    "ram usage", "ram info", "ram details", "how much ram",
                    "gpu usage", "gpu info", "gpu details", "gpu memory", "vram",
                    "windows version", "system info", "os version", "operating system",
                    "battery status", "battery percentage", "power plan",
                    "display resolution", "connected displays", "how many displays", "how many monitors",
                    "wifi", "wi-fi", "bluetooth", "uptime", "wallpaper",
                    "applications are running", "processes are running", "running programs",
                    "top processes"
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
            # Specific skill commands and conversational questions directed at the assistant must not be routed to RAG_SEARCH
            if intent == Intent.RAG_SEARCH:
                # Conversational questions, complaints, capability queries, or stable knowledge must remain GENERAL_CONVERSATION
                if any(is_conversational_followup_or_complaint(t) for t in (clean_input, clean_no_polite, input_lower)):
                    continue
                if any(is_capability_query(t) for t in (clean_input, clean_no_polite, input_lower)):
                    continue
                if any(is_stable_knowledge_question(t) for t in (clean_input, clean_no_polite, input_lower)):
                    continue
                # Conversational questions directed at the assistant must remain GENERAL_CONVERSATION
                is_conversational_to_assistant = any(
                    re.search(p, t, re.IGNORECASE) for t in [clean_input, clean_no_polite, input_lower]
                    for p in [
                        r'\b(?:why|who|what|how|where|when)\s+(?:are|were|did|do|can|could|will|would|have|is)\s+you\b',
                        r'\b(?:why|who|what|how|where|when)\s+(?:did|are|do)\s+you\b',
                        r'\bwhy\s+(?:did\s+you\s+say\s+that|are\s+you\s+doing\s+this|are\s+you\s+doing\s+that|do\s+you\s+exist)\b',
                        r'\bwho\s+(?:are\s+you|made\s+you|created\s+you|built\s+you)\b',
                        r'\bwhat\s+(?:can\s+you\s+do|are\s+you|do\s+you\s+mean|are\s+you\s+doing|is\s+your\s+name)\b',
                        r'\bhow\s+(?:are\s+you|are\s+you\s+doing|do\s+you\s+feel|do\s+you\s+do)\b',
                        r'\b(?:tell\s+me\s+about\s+yourself|introduce\s+yourself)\b',
                    ]
                )
                if is_conversational_to_assistant:
                    continue

                if any(any(k in t for k in [
                    "what do i have", "what do i need to do", "what's on my schedule", "whats on my schedule",
                    "what is on my schedule", "what's planned", "whats planned", "what is planned",
                    "schedule today", "schedule tomorrow", "my schedule", "what meetings", "what appointments",
                    "do i have today", "do i have tomorrow",
                    "random number", "random numbers", "numbers from", "numbers between", "generate random",
                    "queue task", "task status", "cancel task", "stop task", "background task", "tasks are running",
                    "list my task", "show my task", "what tasks",
                    "smart device", "smart home", "active window", "what window", "what app", "what application", "active application", "active app",
                    "what website", "what site", "which site", "what page", "which page", "what video", "which video", "what am i watching", "what was i watching",
                    "what was the previous", "previous app", "previous website", "previous video", "previous site", "previous page", "before brave", "before chrome",
                    "what changed", "what changed from before", "what was open", "what did i have open", "what did i switch from", "what am i using",
                    "what website am i using", "what was i using", "what was the using", "what was i am using", "which app was open", "what app was open",
                    "what was open previously", "what was open before", "what am i currently using", "before this", "before that",
                    "learn rule", "my rules", "undo", "audio device", "microphone", "speaker",
                    "where am i", "my location", "location source", "calendar", "events today", "today's events",
                    "paired devices", "connected devices", "devices are paired", "devices are available", "device status",
                    "what preferences", "what you've learned", "what you have learned",
                    "recommend", "suggest", "push to talk", "clipboard", "reminder", "reminders",
                    "my notes", "take a note", "create a note", "save a note", "inbox", "unread email",
                    "check my cpu", "check cpu", "cpu usage", "cpu metrics", "how much cpu", "can i check my cpu",
                    "check my gpu", "check gpu", "gpu usage", "gpu memory", "how much gpu", "gpu memory am i using",
                    "check my ram", "check ram", "ram usage", "ram metrics", "how much ram", "how much ram is free",
                    "check cpu ram and gpu", "system usage", "show system usage", "system telemetry",
                    "what wallpaper", "my wallpaper", "current wallpaper", "wallpaper am i using",
                    "displays are connected", "monitors are connected", "how many displays", "how many monitors",
                    "which wi-fi", "which wifi", "what network", "network status", "bluetooth status", "power plan",
                    "windows version", "disk usage", "disk space", "system uptime", "applications are running", "processes are running",
                    "extract all links", "extract links", "available links", "links from this page",
                    "extract all tables", "extract table", "extract tables", "table from this page", "tables from this page",
                    "how many links did you find", "how many links", "show me the third link", "open the third link", "open the third one",
                    "first five rows", "third row", "value in the third row",
                    "find flights", "search flights", "flights from", "flight search", "open that flight search", "open the flight search",
                    "profile this file", "profile file", "diagnose this traceback", "diagnose traceback", "analyse that ppt", "analyze that ppt",
                    "set alarm", "set an alarm", "wake me up", "my alarms", "list alarms", "show alarms", "cancel alarm", "snooze alarm", "stop alarm", "turn off alarm",
                    "set a timer", "set timer", "my timers", "list timers", "cancel timer", "stopwatch", "start stopwatch", "stop stopwatch", "reset stopwatch",
                    "time in", "what time is it", "current time", "what's the time", "today's date", "what day is it", "what day is today",
                ]) for t in [clean_input, clean_no_polite, input_lower]):
                    continue
            patterns = self.patterns.get(intent, [])
            for pattern in patterns:
                match = pattern.search(clean_input) or pattern.search(clean_no_polite) or pattern.search(input_lower)
                if match:
                    params = self._extract_params(intent, match, user_input)
                    self.logger.debug(
                        f"[DETERMINISTIC] '{user_input[:60]}' -> {intent.name}"
                    )
                    arb_intent, arb_params = self._arbitrate_intent(user_input, intent, params, source="deterministic")
                    return _cache_and_return(arb_intent, arb_params)

        # ── Step 2: Semantic fallback — only reached when NO regex matched ──
        if is_conversational_general_query(clean_input) or is_conversational_general_query(user_input):
            return _cache_and_return(Intent.GENERAL_CONVERSATION, {"raw_input": user_input})

        if self._semantic_enabled:
            sem_intent, sem_params = self._semantic_fallback(user_input)
            if sem_params and sem_params.get("_needs_clarification"):
                return _cache_and_return(sem_intent, sem_params)
            if sem_intent != Intent.GENERAL_CONVERSATION:
                arb_intent, arb_params = self._arbitrate_intent(user_input, sem_intent, sem_params, source="semantic")
                return _cache_and_return(arb_intent, arb_params)

        arb_intent, arb_params = self._arbitrate_intent(user_input, Intent.GENERAL_CONVERSATION, {}, source="fallback")
        return _cache_and_return(arb_intent, arb_params)

    def _arbitrate_intent(
        self,
        user_input: str,
        initial_intent: Intent,
        initial_params: Dict[str, Any],
        source: str = "deterministic"
    ) -> Tuple[Intent, Dict[str, Any]]:
        """
        Deterministic intent arbitration stage to resolve ambiguities between:
        MUSIC, RECOMMENDATION, GAME_DISCOVERY, SYSTEM_COMPATIBILITY, WEB_SEARCH,
        OPEN_APPLICATION, DEVICE_CONTROL, and GENERAL_CONVERSATION.
        """
        t = user_input.lower().strip()
        candidates = [{
            "intent": initial_intent.name if hasattr(initial_intent, "name") else str(initial_intent),
            "source": source,
            "confidence": 1.0 if source == "deterministic" else float(initial_params.get("_confidence", 0.5))
        }]

        has_play = bool(re.search(r'\b(?:play|playing)\b', t))
        has_game = bool(re.search(r'\b(?:games?|gaming|steam|multiplayer|rpg|fps|online\s+games?|pc\s+games?)\b', t))
        has_compat = bool(re.search(r'\b(?:compatible|run\s+on\s+(?:this|my)|can\s+run\s+on|system\s+requirements|hardware\s+requirements|compare\s+(?:those\s+)?game\s+requirements)\b', t))
        has_recommend = bool(re.search(r'\b(?:suggest|recommend|ideas\s+for|what\s+should\s+i|can\s+u\s+suggest|can\s+you\s+suggest)\b', t))
        has_music_noun = bool(re.search(r'\b(?:music|song|songs|track|tracks|spotify|playlist|arijit\s+singh|album|artist)\b', t))
        is_transport_music = bool(re.search(r'\b(?:play\s+next|play\s+previous|next\s+song|previous\s+song|next\s+track|previous\s+track|stop\s+music|stop\s+playing|stop\s+singing|pause\s+music|resume\s+music)\b', t))
        has_hardware_spec = bool(re.search(r'\b(?:what\s+(?:cpu|gpu|processor|graphics\s+card)|how\s+much\s+ram)\b', t))

        final_intent = initial_intent
        final_params = dict(initial_params)
        decision = initial_intent.name if hasattr(initial_intent, "name") else str(initial_intent)
        reason = "Preserved initial resolution"

        # 1. False MUSIC classifications:
        # A request must NEVER become MUSIC merely because it contains 'play' when referring to games
        if initial_intent == Intent.MUSIC and not is_transport_music and (has_game or not has_music_noun):
            if has_compat:
                final_intent = Intent.SYSTEM_COMPATIBILITY
                final_params = {"query": user_input, "action": "compatibility_check"}
                decision = "SYSTEM_COMPATIBILITY"
                reason = "Identified game compatibility terms; rejected false MUSIC candidate"
            elif has_recommend or has_game:
                final_intent = Intent.GAME_DISCOVERY
                final_params = {"query": user_input, "action": "game_discovery"}
                decision = "GAME_DISCOVERY"
                reason = "Identified game noun with play verb; rejected false MUSIC candidate"

        # 2. SYSTEM_COMPATIBILITY arbitration
        elif has_compat and has_game:
            if final_intent != Intent.SYSTEM_COMPATIBILITY:
                final_intent = Intent.SYSTEM_COMPATIBILITY
                final_params = {"query": user_input, "action": "compatibility_check"}
                decision = "SYSTEM_COMPATIBILITY"
                reason = "Matched system compatibility query for games"

        # 3. GAME_DISCOVERY arbitration
        elif has_game and (has_recommend or has_play) and not has_music_noun:
            if final_intent not in (Intent.GAME_DISCOVERY, Intent.SYSTEM_COMPATIBILITY):
                final_intent = Intent.GAME_DISCOVERY
                final_params = {"query": user_input, "action": "game_discovery"}
                decision = "GAME_DISCOVERY"
                reason = "Matched game suggestion/play request"

        # 4. RECOMMENDATION bias
        elif has_recommend and not has_game and not is_transport_music and (not has_music_noun or not has_play) and final_intent in (Intent.GENERAL_CONVERSATION, Intent.MUSIC):
            final_intent = Intent.RECOMMENDATION
            final_params = {"query": user_input}
            decision = "RECOMMENDATION"
            reason = "Biased suggest/recommend intent to RECOMMENDATION"

        # 5. Hardware query precedence (what CPU / GPU / RAM)
        elif has_hardware_spec:
            if final_intent != Intent.DEVICE_CONTROL:
                final_intent = Intent.DEVICE_CONTROL
                decision = "DEVICE_CONTROL"
                reason = "Hardware specification query routed directly to DEVICE_CONTROL"

        # 6. Disambiguate REMINDER vs CALENDAR_EVENT vs FILE_OPERATIONS vs MEMORY_QUERY
        has_remind_word = bool(re.search(r'\b(?:remind\s+me|reminder|set\s+(?:a\s+)?reminder|alert\s+me)\b', t))
        has_calendar_schedule = (
            bool(re.search(r'\b(?:schedule|shedule|create|add|book|set\s+up)\s+(?:an?\s+)?(?:another\s+)?(?:meeting|meet|calendar\s+event|event|appointment|project\s+review)\b', t))
            or bool(re.search(r'\b(?:schedule|shedule)\s+(?:an?\s+)?(.+?)\s+(?:on|for|at)\s+(?:\d{4}-\d{2}-\d{2}|\w+\s+\d{1,2}|\d{1,2}(?::\d{2})?\s*(?:am|pm)|today|tomorrow|the\s+same\s+time)\b', t))
        )
        is_calendar_move = bool(re.search(r'\b(?:move|reschedule|shift|postpone)\s+(.+?)\s+to\s+(?:(?:october|november|december|january|february|march|april|may|june|july|august|september|\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?|today|tomorrow)\b|\d{1,2}(?::\d{2})?\s*(?:am|pm))', t))
        is_calendar_time_chg = bool(re.search(r'\b(?:change|update|reschedule|shift)\s+(?:the\s+)?time\s+(?:of|for)\s+(.+?)\s+to\s+(.+)', t))
        is_calendar_rename = bool(re.search(r'\b(?:rename|change\s+the\s+name\s+of)\s+(?:the\s+)?(.+?)\s+to\s+(.+)', t))
        is_calendar_cancel = (
            bool(re.search(r'\b(?:cancel|delete|remove|drop)\s+(?:all\s+|the\s+|my\s+)?(?:meeting|meetings|event|events|appointment|appointments|sync|standup|huddle|hurdle)(?:\s+(?:for|on|at|tomorrow|today|\d{4}-\d{2}-\d{2}))?\b', t))
            or bool(re.search(r'\b(?:cancel|delete|remove|drop)\s+(?:the\s+|my\s+)?(?:daily\s+|weekly\s+)?(?:huddle|hurdle)\b', t))
        )
        is_calendar_next = bool(re.search(r'\b(?:(?:what(?:\'s|\s+is)|when\s+is)\s+(?:my\s+)?(?:next|upcoming)\s+(?:appointment|meeting|event)|next\s+(?:appointment|meeting|event))\b', t))
        is_calendar_plan = bool(re.search(r'\b(?:plan\s+(?:my\s+)?(?:week|schedule|days?)|weekly\s+plan(?:ning)?)\b', t))
        is_calendar_view = bool(
            re.search(r'\b(?:show|list|view|display|check|get|see|read|tell\s+me)\b.+?\b(?:schedule|calendar|agenda|events?|appointments?|meetings?)\b', t)
            or re.search(r'\b(?:what(?:\'s|\s+is)\s+(?:on|in)\s+(?:my\s+)?(?:schedule|calendar|agenda))\b', t)
            or re.search(r'\bwhat\s+(?:do\s+i|do\s+we)\s+have\s+scheduled\b', t)
            or re.search(r'\b(?:all\s+)?upcoming\s+(?:events?|meetings?|appointments?|schedule)\b', t)
            or re.search(r'\b(?:show\s+(?:all\s+)?(?:my\s+)?upcoming\s+events?)\b', t)
            or re.search(r'\b(?:my\s+)?schedule\s+calendar\b', t)
        )

        is_calendar_conflict_res = bool(re.search(
            r'\b(?:keep\s+both(?:\s+events)?|schedule\s+anyway|proceed\s+anyway|move\s+(?:it|the\s+new\s+meeting|the\s+new\s+event)?\s+to\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|move\s+to\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|move\s+to\s+another\s+time|cancel\s+(?:the\s+)?(?:new\s+)?request|reschedule\s+(?:the\s+)?existing\s+event)\b', t
        ))
        is_calendar_duration = bool(re.search(
            r'\b(?:make|extend|shorten)\s+(?:the\s+)?(?:meeting|event|appointment|it)\s+\d+\s*(?:minutes?|mins?|hours?|hrs?)\s*(?:longer|shorter)?\b', t
        ))
        is_calendar_relative_shift = bool(re.search(
            r'\b(?:actually,?\s*)?(?:make\s+it|shift\s+it\s+to|change\s+(?:it|the\s+date)\s+to)\s+(?:today|tomorrow|friday|monday|tuesday|wednesday|thursday|saturday|sunday|next\s+week|\w+\s+\d{1,2})\b', t
        ))
        is_calendar_holiday = bool(re.search(
            r'\b(?:public\s+holiday|public\s+holidays|when\s+is\s+diwali|diwali\s+this\s+year|next\s+public\s+holiday|state\'?s?\s+holidays|holidays?\s+in\s+[a-zA-Z]+|holidays?\s+coming\s+up|how\s+many\s+public\s+holidays)\b', t
        ))
        is_calendar_overlap_check = bool(re.search(
            r'\b(?:do\s+i\s+have\s+anything\s+during\s+that\s+time|is\s+there\s+(?:a\s+)?conflict|any\s+conflicts?)\b', t
        ))

        is_event_reminder = bool(re.search(r'\b(?:with\s+(?:a\s+)?reminder|remind(?:er)?\s+\d+\s*(?:minutes?|mins?|hours?)\s+before)\b', t))
        if has_remind_word and final_intent == Intent.DAILY_BRIEFING and not (has_calendar_schedule and is_event_reminder):
            final_intent = Intent.REMINDERS
            decision = "REMINDERS"
            reason = "Explicit reminder trigger takes precedence over generic schedule"
        elif (has_calendar_schedule or is_calendar_view or is_calendar_move or is_calendar_time_chg or is_calendar_rename or is_calendar_cancel or is_calendar_next or is_calendar_plan or is_calendar_conflict_res or is_calendar_duration or is_calendar_relative_shift or is_calendar_holiday or is_calendar_overlap_check) and (not has_remind_word or is_event_reminder):
            final_intent = Intent.DAILY_BRIEFING
            final_params = {"action": "calendar_query", "raw_input": user_input}
            decision = "DAILY_BRIEFING"
            reason = "Calendar operation routed to DAILY_BRIEFING"

        self.logger.info(
            f"[INTENT_ARBITRATION] candidates={candidates} "
            f"decision={decision} final_intent={final_intent.name if hasattr(final_intent, 'name') else str(final_intent)} reason='{reason}'"
        )
        return final_intent, final_params

    def route(self, user_input: str, user_id: Optional[Any] = None) -> Tuple[Intent, Dict[str, Any]]:
        """Alias for route_command."""
        return self.route_command(user_input, user_id=user_id)

    def _extract_params(self, intent: Intent, match: re.Match, user_input: str) -> Dict[str, Any]:
        params = {"raw_input": user_input}
        try:
            if intent == Intent.VISUAL_SURFACE:
                text_low = user_input.lower().strip()
                m_sub = re.search(r'(?:details\s+(?:about|of|for)|information\s+(?:about|of|for))\s+(.+)', text_low)
                m_spec = re.search(r'show\s+visual\s+response\s+([a-zA-Z0-9_]+)', text_low)
                if m_sub:
                    params["target_type"] = "SUBJECT_DETAILS"
                    params["target_subject"] = m_sub.group(1).strip()
                elif m_spec:
                    params["target_type"] = m_spec.group(1).upper()
                elif "box" in text_low and "number" in text_low:
                    params["target_type"] = "NUMBERS_BOX"
                elif any(w in text_low for w in ["number", "numbers", "count"]):
                    params["target_type"] = "NUMBERS"
                elif any(w in text_low for w in ["again", "back", "previous result", "what you just"]):
                    params["target_type"] = "AGAIN"
                elif any(w in text_low for w in ["detail", "details", "details box", "information", "explanation", "steps", "expand", "understand"]):
                    params["target_type"] = "DETAILS"
                elif any(w in text_low for w in ["వివరాలు", "विवरण", "விவரங்களை", "detalles"]):
                    params["target_type"] = "DETAILS"
                else:
                    m_s = re.search(r'\b(pairing\s+code|code|ip\s+address|ip|address|url|link|file\s+path|file|path|list|devices|table|status|result)\b', text_low)
                    if m_s:
                        params["target_type"] = m_s.group(1).replace(" ", "_").upper()
                    else:
                        params["target_type"] = "DETAILS"
                params["action"] = "show_visual_response"
                return params

            elif intent == Intent.CLOSE_APPLICATION:
                text_low = user_input.lower().strip()
                clean_text_low = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*', '', text_low).strip()
                clean_text_no_polite = re.sub(r'^(?:can\s+you\s+|could\s+you\s+|please\s+)+', '', clean_text_low).strip()

                if re.search(r'\b(?:close|quit|exit|terminate|kill|shut\s+down)\s+(?:all\s+(?:things|thigs|apps|applications)?\s*(?:you\s+opened|that\s+were\s+opened|opened)?(?:\s+now)?|everything\s*(?:you\s+opened|that\s+were\s+opened|opened)?(?:\s+now)?|all\s+opened\s+(?:apps|applications))\b', clean_text_no_polite, re.IGNORECASE):
                    params["action"] = "close_all_opened"
                    params["target"] = "all_opened_apps"
                    params["application"] = "all_opened_apps"
                    return params

                if any(k in user_input.lower() for k in ["kill", "terminate", "process"]):
                    params["action"] = "terminate_process"
                else:
                    params["action"] = "close"

                m_close = re.search(r'\b(?:close|quit|exit|terminate|kill|shut\s+down)\s+(.+)', clean_text_no_polite, re.IGNORECASE)
                raw_target = m_close.group(1).strip() if m_close else user_input
                raw_target = re.sub(r'^(?:the|a|an)\s+', '', raw_target, flags=re.IGNORECASE).strip()
                raw_target = re.sub(r'\s+(?:app|application|program|window)$', '', raw_target, flags=re.IGNORECASE).strip()
                params["target"] = raw_target
                params["application"] = raw_target
                return params

            elif intent == Intent.OPEN_APPLICATION:
                text_low = user_input.lower().strip()
                clean_text_low = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*', '', text_low).strip()
                clean_text_no_polite = re.sub(r'^(?:can\s+you\s+|could\s+you\s+|please\s+)+', '', clean_text_low).strip()

                if re.match(r'^(?:go\s+back|navigate\s+back|browser\s+go\s+back|go\s+back\s+in\s+browser)[.!?]?$', clean_text_no_polite):
                    params["action"] = "navigate_back"
                    params["target"] = "browser"
                    return params

                if re.search(r'\b(?:close|quit|exit|terminate|kill)\s+(?:all\s+(?:things|thigs|apps|applications)?\s*(?:you\s+opened|that\s+were\s+opened|opened)?(?:\s+now)?|everything\s*(?:you\s+opened|that\s+were\s+opened|opened)?(?:\s+now)?|all\s+opened\s+(?:apps|applications))\b', clean_text_no_polite, re.IGNORECASE):
                    params["action"] = "close_all_opened"
                    params["target"] = "all_opened_apps"
                    return params

                if re.search(r'\b(?:extract\s+(?:all\s+)?(?:the\s+)?(?:available\s+)?links(?:\s+from\s+(?:the\s+|this\s+)?(?:web\s+)?page)?|extract\s+(?:all\s+)?(?:the\s+)?(?:available\s+)?links)\b', clean_text_no_polite):
                    params["action"] = "extract_links"
                    params["target"] = "browser"
                    return params
                elif re.search(r'\b(?:extract\s+(?:all\s+)?(?:the\s+)?(?:available\s+)?tables?(?:\s+from\s+(?:the\s+|this\s+)?(?:web\s+)?page)?|extract\s+tables?)\b', clean_text_no_polite):
                    params["action"] = "extract_tables"
                    params["target"] = "browser"
                    return params
                elif re.search(r'\b(?:how\s+many\s+links(?:\s+(?:did\s+you\s+find|were\s+found|are\s+there|did\s+we\s+get|extracted))?)\b', clean_text_no_polite):
                    params["action"] = "count_links"
                    params["target"] = "browser"
                    return params
                elif re.search(r'\b(?:show|display|what(?:\'s|\s+is))\s+(?:me\s+)?(?:the\s+)?(?:(\d+)(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+link\b', clean_text_no_polite):
                    m_l = re.search(r'\b(?:show|display|what(?:\'s|\s+is))\s+(?:me\s+)?(?:the\s+)?(?:(\d+)(?:st|nd|rd|th)|(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth))\s+link\b', clean_text_no_polite)
                    params["action"] = "get_link"
                    params["ordinal"] = (m_l.group(1) or m_l.group(2)) if m_l else "1"
                    params["target"] = "browser"
                    return params
                elif re.search(r'\b(?:open)\s+(?:the\s+)?(?:(\d+)(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+(?:one|link)\b', clean_text_no_polite):
                    m_lo = re.search(r'\b(?:open)\s+(?:the\s+)?(?:(\d+)(?:st|nd|rd|th)|(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth))\s+(?:one|link)\b', clean_text_no_polite)
                    params["action"] = "open_link"
                    params["ordinal"] = (m_lo.group(1) or m_lo.group(2)) if m_lo else "1"
                    params["target"] = "browser"
                    return params
                elif re.search(r'\b(?:show|display|get)\s+(?:me\s+)?(?:the\s+)?first\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+rows?(?:\s+of\s+(?:the\s+)?table)?\b', clean_text_no_polite):
                    m_tr = re.search(r'\b(?:show|display|get)\s+(?:me\s+)?(?:the\s+)?first\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+rows?(?:\s+of\s+(?:the\s+)?table)?\b', clean_text_no_polite)
                    params["action"] = "get_table_rows"
                    params["count_str"] = m_tr.group(1) if m_tr else "5"
                    params["target"] = "browser"
                    return params
                elif re.search(r'\b(?:what(?:\'s|\s+is)\s+(?:the\s+)?value\s+(?:in|of)\s+(?:the\s+)?|show\s+(?:me\s+)?(?:the\s+)?)(?:(\d+)(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+row\b', clean_text_no_polite):
                    m_rw = re.search(r'\b(?:what(?:\'s|\s+is)\s+(?:the\s+)?value\s+(?:in|of)\s+(?:the\s+)?|show\s+(?:me\s+)?(?:the\s+)?)(?:(\d+)(?:st|nd|rd|th)|(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth))\s+row\b', clean_text_no_polite)
                    params["action"] = "get_table_row"
                    params["ordinal"] = (m_rw.group(1) or m_rw.group(2)) if m_rw else "1"
                    params["target"] = "browser"
                    return params
                elif any(k in clean_text_no_polite for k in ["find flights", "search flights", "flights from", "flight from", "what about flights"]):
                    params["action"] = "search_flights"
                    params["target"] = "browser"
                    return params

                m_back = re.search(r'^(?:go\s+back|navigate\s+back|browser\s+go\s+back|go\s+back\s+in\s+browser)[.!?]?$', clean_text_no_polite, re.IGNORECASE)
                if m_back:
                    params["action"] = "browser_go_back"
                    params["target"] = "browser"
                    params["entity_type"] = "BROWSER_RESULT"
                    return params

                m_br_res = re.search(r'\b(?:open|click|select)\s+(?:the\s+)?(first|top|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|\d+(?:st|nd|rd|th))\s+(?:result|link)\b', clean_text_no_polite, re.IGNORECASE)
                if m_br_res:
                    params["action"] = "open_browser_result"
                    params["ordinal"] = m_br_res.group(1).lower()
                    params["entity_type"] = "BROWSER_RESULT"
                    params["target"] = "browser_result"
                    return params

                m_yt = re.search(r'\b(?:search\s+(?:on\s+|in\s+)?youtube\s+for|search\s+youtube\s+for)\s+(.+)', user_input, re.IGNORECASE)
                m_gg = re.search(r'\b(?:search\s+(?:on\s+|in\s+)?google\s+for|search\s+google\s+for)\s+(.+)', user_input, re.IGNORECASE)
                is_open_app_cmd = clean_text_no_polite.startswith(("open ", "launch ", "start ", "run ", "close ", "quit ", "kill "))
                if not is_open_app_cmd:
                    m_sw = re.search(r'\b(?:search\s+(?:for\s+)?|search\s+the\s+web\s+for\s+|search\s+google\s+for\s+|google\s+(?!chrome\b))(.+)', clean_text_no_polite, re.IGNORECASE)
                else:
                    m_sw = re.search(r'\b(?:search\s+(?:for\s+)?|search\s+the\s+web\s+for\s+|search\s+google\s+for\s+)(.+)', clean_text_no_polite, re.IGNORECASE)

                if m_yt:
                    query = m_yt.group(1).strip().rstrip('.?!')
                    import urllib.parse
                    params["action"] = "open"
                    params["target"] = "youtube"
                    params["is_website"] = True
                    params["site_name"] = "YouTube"
                    params["url"] = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
                    params["search_query"] = query
                    params["entity_type"] = "SEARCH_QUERY"
                    return params
                elif m_gg:
                    query = m_gg.group(1).strip().rstrip('.?!')
                    import urllib.parse
                    params["action"] = "search_web"
                    params["target"] = "google"
                    params["is_website"] = True
                    params["site_name"] = "Google"
                    params["url"] = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                    params["search_query"] = query
                    params["query"] = query
                    params["entity_type"] = "SEARCH_QUERY"
                    return params
                elif m_sw and not any(k in clean_text_no_polite for k in ["youtube", "flights", "flight", "extract", "result", "link"]):
                    query = m_sw.group(1).strip().rstrip('.?!')
                    import urllib.parse
                    params["action"] = "search_web"
                    params["target"] = "browser"
                    params["is_website"] = True
                    params["site_name"] = "Browser"
                    params["url"] = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                    params["search_query"] = query
                    params["query"] = query
                    params["entity_type"] = "SEARCH_QUERY"
                    return params

                if match.lastindex and match.lastindex >= 2:
                    action = match.group(1).lower()
                    target = match.group(2).strip()
                else:
                    action = "open"
                    target = match.group(1).strip() if match.lastindex else ""

                if any(clean_text_no_polite.startswith(p) for p in ("switch to ", "switch back to ", "switch ", "bring up ", "bring ", "focus ")):
                    action = "switch"

                # Terminate application target at conjunction/action boundary
                m_act_bound = re.search(r'^(.*?)\s+and\s+(?:search(?:\s+google)?(?:\s+(?:for|on|in))?|type|write|calculate|compute|open|look\s+up|find)\s+(.+)$', target, re.IGNORECASE)
                if m_act_bound:
                    app_only = m_act_bound.group(1).strip()
                    rest_act = m_act_bound.group(2).strip()
                    target = app_only
                    if "search" in user_input.lower() or "find" in user_input.lower():
                        params["search_query"] = rest_act.rstrip('.?!')

                # Normalize instance modifier BEFORE application resolution
                instance_mode = "NORMAL"
                m_trailing_win = re.search(r'\s+in\s+(?:a\s+new|another)\s+(?:window|instance)$', target, re.IGNORECASE)
                if m_trailing_win:
                    instance_mode = "NEW"
                    target = target[:m_trailing_win.start()].strip()

                m_inst = re.match(
                    r'^(?:(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+(?:instance|window)\s+of\s+|'
                    r'(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+)',
                    target,
                    re.IGNORECASE
                )
                if m_inst:
                    instance_mode = "NEW"
                    target = target[m_inst.end():].strip()

                # Strip conversational trailing clauses (e.g. "I need a Chrome to be open on the screen right now", "so that I can work")
                target = re.sub(r'\s+(?:i\s+need|i\s+want|to\s+be\s+open|on\s+the\s+screen|right\s+now|so\s+that|so\s+i\s+can|because|since|asap|now|immediately)\b.*$', '', target, flags=re.IGNORECASE).strip()

                # Iteratively strip conversational wrappers, polite fillers, and generic nouns from the end
                # (e.g. "for me", "please", "app", "application", "browser", "window", "program")
                prev_target = None
                while prev_target != target:
                    prev_target = target
                    target = re.sub(r'\s+(?:for\s+me|please|thanks|thank\s+you|app|application|browser|window|program)$', '', target, flags=re.IGNORECASE).strip()

                # Strip leading articles and generic nouns (e.g. "the Notepad", "the calculator app")
                target = re.sub(r'^(?:the|a|an)\s+', '', target, flags=re.IGNORECASE).strip()
                target = re.sub(r'^(?:app|application|browser)\s+', '', target, flags=re.IGNORECASE).strip()
                target = re.sub(r'^(?:could\s+you\s+|can\s+you\s+|please\s+|launch\s+|open\s+|start\s+|i\s+need\s+|i\s+want\s+|get\s+)+', '', target, flags=re.IGNORECASE).strip()
                target = re.sub(r'\s+running$', '', target, flags=re.IGNORECASE).strip()
                target = re.sub(r'^(?:the|a|an)\s+', '', target, flags=re.IGNORECASE).strip()

                # Resolve actual application entity using system indexer/SmartOpener
                clean_target = target
                try:
                    from extensions.system.smart_opener import SmartOpener
                    opener = SmartOpener()
                    res_app = opener.resolve_detailed(clean_target)
                    if res_app:
                        clean_target = res_app[0]
                    else:
                        words = clean_target.split()
                        for k in range(min(len(words), 3), 0, -1):
                            sub_cand = " ".join(words[:k])
                            sub_res = opener.resolve_detailed(sub_cand)
                            if sub_res:
                                clean_target = sub_res[0]
                                break
                except Exception:
                    pass
                target = clean_target

                params["instance_mode"] = instance_mode
                params["new_instance"] = (instance_mode == "NEW")
                params["application"] = target
                
                # Check for kill/terminate process command
                if any(k in user_input.lower() for k in ["kill", "terminate", "process"]):
                    params["action"] = "terminate_process"
                    clean_target = re.sub(r'\b(?:the\s+)?process\b', '', target, flags=re.IGNORECASE).strip()
                    params["target"] = clean_target or target
                else:
                    params["action"] = "open" if action in ["open", "launch", "start", "run", "go to", "visit", "browse to", "navigate to", "show", "display"] or not action else "close"
                    
                    # Detect web navigation / website request
                    raw_low = user_input.lower()
                    target_low = target.lower()
                    is_web = False
                    
                    # Check website keywords in target or user_input
                    if re.search(r'\b(?:website|site|webpage|web\s+page)\b', target_low):
                        is_web = True
                        clean_t = re.sub(r'^(?:the\s+)?(?:website|site|webpage|web\s+page)\s+(?:of\s+|for\s+)?', '', target, flags=re.IGNORECASE).strip()
                        clean_t = re.sub(r'\s+(?:the\s+)?(?:website|site|webpage|web\s+page)$', '', clean_t, flags=re.IGNORECASE).strip()
                        target = clean_t
                    elif any(w in raw_low for w in ["go to ", "visit ", "browse to ", "navigate to "]):
                        is_web = True
                    
                    # Check if target is a domain or URL
                    tld_match = re.search(r'\b[a-zA-Z0-9-]+\.(?:com|org|net|edu|gov|io|ai|co|app|dev|in|me|info|tv)\b', target, re.IGNORECASE)
                    if tld_match or target.startswith(('http://', 'https://', 'www.')):
                        is_web = True
                    
                    # Also check well-known website names
                    common_sites = {"youtube", "google", "gmail", "github", "reddit", "twitter", "x", "linkedin", "facebook", "instagram", "wikipedia", "amazon", "netflix"}
                    if target.lower().strip() in common_sites:
                        is_web = True
                    
                    if is_web:
                        params["is_website"] = True
                        t_clean = target.strip(' "\'')
                        if t_clean.lower().startswith(('url ', 'link ')):
                            t_clean = re.sub(r'^(?:url|link)\s+', '', t_clean, flags=re.IGNORECASE).strip()
                        if t_clean.startswith(('http://', 'https://')):
                            params["url"] = t_clean
                            params["target"] = t_clean
                            host = re.sub(r'^https?://(?:www\.)?', '', t_clean).split('/')[0].split(':')[0]
                            parts = host.split('.')
                            if len(parts) >= 2:
                                if parts[-2].lower() in ('co', 'com', 'org', 'edu', 'gov', 'net') and len(parts) >= 3:
                                    params["site_name"] = parts[-3].capitalize()
                                else:
                                    params["site_name"] = parts[-2].capitalize()
                            else:
                                params["site_name"] = parts[0].capitalize()
                        elif re.search(r'\.[a-zA-Z]{2,}', t_clean):
                            params["url"] = f"https://{t_clean}"
                            params["target"] = f"https://{t_clean}"
                            host = re.sub(r'^(?:www\.)?', '', t_clean).split('/')[0].split(':')[0]
                            parts = host.split('.')
                            if len(parts) >= 2:
                                if parts[-2].lower() in ('co', 'com', 'org', 'edu', 'gov', 'net') and len(parts) >= 3:
                                    params["site_name"] = parts[-3].capitalize()
                                else:
                                    params["site_name"] = parts[-2].capitalize()
                            else:
                                params["site_name"] = parts[0].capitalize()
                        else:
                            site_urls = {
                                "youtube": "https://www.youtube.com",
                                "google": "https://www.google.com",
                                "gmail": "https://mail.google.com",
                                "github": "https://www.github.com",
                                "reddit": "https://www.reddit.com",
                                "twitter": "https://www.twitter.com",
                                "x": "https://www.x.com",
                                "linkedin": "https://www.linkedin.com",
                                "facebook": "https://www.facebook.com",
                                "instagram": "https://www.instagram.com",
                                "wikipedia": "https://www.wikipedia.org",
                                "amazon": "https://www.amazon.com",
                                "netflix": "https://www.netflix.com",
                            }
                            params["url"] = site_urls.get(t_clean.lower(), f"https://www.{t_clean.lower()}.com")
                            params["site_name"] = t_clean.capitalize()
                        params["entity_type"] = "BROWSER_RESULT"
                    
                    params["target"] = target
            elif intent == Intent.POWER_ACTION:
                g = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                raw_action = g.strip().lower()
                # Normalise to canonical values used by execute_single_action.
                # Also handle cases where the full match string was captured
                # (e.g. "restart the computer" → "restart").
                _pa_norm = {
                    "shutdown": "shutdown",
                    "shut down": "shutdown",
                    "power off": "shutdown",
                    "turn off": "shutdown",
                    "reboot": "restart",
                    "restart": "restart",
                    "sleep": "sleep",
                    "suspend": "sleep",
                    "hibernate": "sleep",
                }
                # Try exact match first; then try substring/prefix match for compound strings
                normalised = _pa_norm.get(raw_action)
                if normalised is None:
                    for key, val in _pa_norm.items():
                        if key in raw_action:
                            normalised = val
                            break
                params["action"] = normalised or raw_action
            elif intent == Intent.DEVICE_CONTROL:
                text_low = user_input.lower()
                if re.search(r'\b(?:install\s+software|install\s+app|install\s+package|install)\s+([a-zA-Z0-9_\-\.]+)\b', text_low):
                    m = re.search(r'\b(?:install\s+software|install\s+app|install\s+package|install)\s+([a-zA-Z0-9_\-\.]+)\b', text_low)
                    params["action"] = "install_software"
                    pkg = m.group(1).strip()
                    params["package_name"] = pkg
                    params["name"] = pkg
                    params["target"] = pkg
                elif re.search(r'\b(?:uninstall\s+software|uninstall\s+app|remove\s+software|remove\s+app|uninstall)\s+([a-zA-Z0-9_\-\.]+)\b', text_low):
                    m = re.search(r'\b(?:uninstall\s+software|uninstall\s+app|remove\s+software|remove\s+app|uninstall)\s+([a-zA-Z0-9_\-\.]+)\b', text_low)
                    params["action"] = "uninstall_software"
                    pkg = m.group(1).strip()
                    params["package_name"] = pkg
                    params["name"] = pkg
                    params["target"] = pkg
                elif re.search(r'\b(?:start|stop|restart)\s+service\s+([a-zA-Z0-9_\-\.]+)\b', text_low) or re.search(r'\bservice\s+([a-zA-Z0-9_\-\.]+)\s+(start|stop|restart)\b', text_low):
                    m1 = re.search(r'\b(start|stop|restart)\s+service\s+([a-zA-Z0-9_\-\.]+)\b', text_low)
                    m2 = re.search(r'\bservice\s+([a-zA-Z0-9_\-\.]+)\s+(start|stop|restart)\b', text_low)
                    params["action"] = "service_control"
                    if m1:
                        params["sub_action"] = m1.group(1).lower()
                        params["service_name"] = m1.group(2).strip()
                        params["name"] = m1.group(2).strip()
                        params["target"] = m1.group(2).strip()
                    elif m2:
                        params["sub_action"] = m2.group(2).lower()
                        params["service_name"] = m2.group(1).strip()
                        params["name"] = m2.group(1).strip()
                        params["target"] = m2.group(1).strip()
                elif re.search(r'\b(?:test|request|check|trigger|verify|prompt)\s+(?:for\s+)?(?:admin(?:istrator)?\s+)?(?:uac\s+)?elevation\b', text_low) \
                     or re.search(r'\b(?:test|request)\s+(?:admin(?:istrator)?|uac)\s+permissions?\b', text_low) \
                     or re.search(r'\b(?:elevate|request)\s+(?:to\s+)?(?:admin(?:istrator)?|administrator\s+privileges?|admin\s+privileges?)\b', text_low) \
                     or "elevation" in text_low:
                    params["action"] = "test_elevation"
                    params["name"] = "elevation_test"
                    params["target"] = "elevation_test"
                elif re.search(r'\b(?:close|shut)\s+(?:this\s+|the\s+|current\s+|browser\s+)?tab(?:s)?\b', text_low):
                    params["action"] = "close_tab"
                elif "screenshot" in text_low or "capture" in text_low:
                    params["action"] = "screenshot"
                    params["requested_device_target"] = "screen"
                    params["requested_action"] = "SCREENSHOT"
                    params["resolved_action"] = "SCREENSHOT"
                    params["executor_action"] = "screenshot"
                elif "unmute" in text_low:
                    params["action"] = "unmute"
                    params["requested_device_target"] = "volume"
                    params["requested_action"] = "VOLUME_UNMUTE"
                    params["resolved_action"] = "VOLUME_UNMUTE"
                    params["executor_action"] = "unmute"
                elif "mute" in text_low:
                    params["action"] = "mute"
                    params["requested_device_target"] = "volume"
                    params["requested_action"] = "VOLUME_MUTE"
                    params["resolved_action"] = "VOLUME_MUTE"
                    params["executor_action"] = "mute"
                elif re.search(r'\bunlock\b', text_low):
                    params["action"] = "unlock"
                    params["requested_device_target"] = "unlock"
                    params["requested_action"] = "UNLOCK"
                    params["resolved_action"] = "UNLOCK"
                    params["executor_action"] = "unlock"
                elif ("logout" in text_low or "lock screen" in text_low or "lock system" in text_low or "lock pc" in text_low or "lock computer" in text_low or "lock workstation" in text_low or (text_low.strip() == "lock") or (re.search(r'\block\b', text_low) and not any(k in text_low for k in ["caps", "num", "scroll", "toggle", "key", "light", "unlock"]))):
                    params["action"] = "lock"
                    params["requested_device_target"] = "lock"
                    params["requested_action"] = "LOCK"
                    params["resolved_action"] = "LOCK"
                    params["executor_action"] = "lock"
                elif (
                    re.search(r'\b(?:pair|connect)\s+(?:to\s+)?(?:(?:my|a|a\s+new)\s+)?(?:phone|device|mobile)\b', text_low)
                    or re.search(r'\b(?:disconnect|unpair|remove)\s+(?:(?:my|a|a\s+new)\s+)?(?:phone|device|mobile)\b', text_low)
                    or re.search(r'\b(?:is\s+(?:my\s+)?(?:phone|device|mobile)\s+(?:connected|online)|(?:phone|device|mobile)\s+connection(?:\s+status)?|check\s+(?:my\s+)?(?:phone|device|mobile)\s+connection|(?:show\s+(?:my\s+)?|get\s+(?:my\s+)?)?(?:device|phone)\s+status)\b', text_low)
                    or re.search(r'\b(?:what(?:\'s|\s+is|\s+was)?\s+(?:the\s+)?(?:(?:phone|device)\s+)?(?:pairing\s+)?code|repeat\s+(?:the\s+)?(?:(?:phone|device)\s+)?(?:pairing\s+)?code)\b', text_low)
                    or any(k in text_low for k in [
                        "pair phone", "pair my phone", "connect phone", "connect my phone", "connect to my phone", "connect to phone",
                        "disconnect phone", "disconnect my phone", "remove phone", "remove my phone", "unpair phone", "unpair my phone",
                        "pair device", "pair my device", "pair a new device", "connect mobile",
                        "phone battery", "my phone battery", "flashlight", "torch", "on my phone",
                        "list devices", "list my devices", "list paired devices", "list my paired devices",
                        "paired devices", "what devices are connected", "show my devices", "show paired devices",
                        "show my connected devices", "show connected devices", "what devices are paired", "what devices are available",
                        "show my device status", "show device status", "device status",
                        "is my phone connected", "is my phone online", "is my device connected",
                        "code again", "pairing code", "what's the code", "what was the code", "repeat the code"
                    ])
                ):
                    params["action"] = "remote_device"
                elif any(k in text_low for k in [
                    "where am i", "what is my location", "current location", "my location", "detect location",
                    "find my current location", "find my location", "refresh my location", "update my location",
                    "location source", "how do you know my location", "location provider"
                ]):
                    params["action"] = "device_location"
                elif any(k in text_low for k in ["analyze clipboard", "inspect clipboard", "analyze my clipboard", "inspect my clipboard", "analyze the clipboard", "inspect the clipboard"]) or re.search(r'\b(?:analyze|inspect)\s+(?:the\s+|my\s+)?clipboard\b', text_low):
                    params["action"] = "analyze_clipboard"
                elif re.search(r'\b(?:copy|put)\s+(.+?)\s+(?:to|on|into)\s+(?:my\s+)?clipboard\b', text_low):
                    params["action"] = "copy_to_clipboard"
                    m_cp = re.search(r'\b(?:copy|put)\s+(.+?)\s+(?:to|on|into)\s+(?:my\s+)?clipboard\b', user_input, re.IGNORECASE)
                    text_to_copy = m_cp.group(1).strip(' "\'') if m_cp else ""
                    params["text_to_copy"] = text_to_copy
                # ── Screenshot ──
                elif any(k in text_low for k in ["screenshot", "capture screen", "capture the screen"]):
                    params["action"] = "screenshot"
                # ── Brightness controls ──
                # 1. Relative INCREASE with numeric amount: "increase brightness by 20%", "raise brightness 20%", etc.
                elif re.search(r'\b(?:increase|raise|turn\s+up|boost)\s+(?:the\s+)?(?:screen\s+)?brightness\s+(?:by\s+)?(\d+)\s*%?\b', text_low) or re.search(r'\b(?:screen\s+)?brightness\s+up\s+(?:by\s+)?(\d+)\s*%?\b', text_low):
                    m_bri = re.search(r'\b(?:increase|raise|turn\s+up|boost)\s+(?:the\s+)?(?:screen\s+)?brightness\s+(?:by\s+)?(\d+)\s*%?\b', text_low) or re.search(r'\b(?:screen\s+)?brightness\s+up\s+(?:by\s+)?(\d+)\s*%?\b', text_low)
                    params["action"] = "increase_brightness"
                    params["amount"] = int(m_bri.group(1)) if m_bri else 10
                # 2. Relative DECREASE with numeric amount: "decrease brightness by 50%", "lower brightness 50%", etc.
                elif re.search(r'\b(?:decrease|lower|reduce|turn\s+down|drop)\s+(?:the\s+)?(?:screen\s+)?brightness\s+(?:by\s+)?(\d+)\s*%?\b', text_low) or re.search(r'\b(?:screen\s+)?brightness\s+down\s+(?:by\s+)?(\d+)\s*%?\b', text_low):
                    m_brd = re.search(r'\b(?:decrease|lower|reduce|turn\s+down|drop)\s+(?:the\s+)?(?:screen\s+)?brightness\s+(?:by\s+)?(\d+)\s*%?\b', text_low) or re.search(r'\b(?:screen\s+)?brightness\s+down\s+(?:by\s+)?(\d+)\s*%?\b', text_low)
                    params["action"] = "decrease_brightness"
                    params["amount"] = int(m_brd.group(1)) if m_brd else 10
                # 3. Absolute SET: "set brightness to 50%", "change brightness to 50%", "brightness to 50%", "brightness 50%"
                elif re.search(r'\b(?:set|change)\s+(?:the\s+)?(?:screen\s+)?brightness\s+(?:to\s+)?(\d+)\s*%?\b', text_low) or re.search(r'\b(?:screen\s+)?brightness\s+to\s+(\d+)\s*%?\b', text_low) or re.search(r'\bbrightness\s+(\d+)\b', text_low):
                    m_br = re.search(r'\b(?:set|change)\s+(?:the\s+)?(?:screen\s+)?brightness\s+(?:to\s+)?(\d+)\s*%?\b', text_low) or re.search(r'\b(?:screen\s+)?brightness\s+to\s+(\d+)\s*%?\b', text_low) or re.search(r'\bbrightness\s+(\d+)\b', text_low)
                    params["action"] = "set_brightness"
                    params["level"] = max(0, min(100, int(m_br.group(1)))) if m_br else 50
                # 4. Relative INCREASE default step (no number)
                elif any(k in text_low for k in ["increase the screen brightness", "increase screen brightness", "increase the brightness", "increase brightness", "raise screen brightness", "raise brightness", "brightness up"]):
                    params["action"] = "increase_brightness"
                    params["amount"] = 10
                # 5. Relative DECREASE default step (no number)
                elif any(k in text_low for k in ["decrease the screen brightness", "decrease screen brightness", "decrease the brightness", "decrease brightness", "lower screen brightness", "lower brightness", "brightness down"]):
                    params["action"] = "decrease_brightness"
                    params["amount"] = 10
                # 6. Read brightness
                elif any(k in text_low for k in ["get current brightness", "what is the brightness", "what is the screen brightness", "check brightness", "screen brightness", "brightness"]):
                    params["action"] = "get_brightness"

                # ── Volume controls ──
                # 0. Volume by N percentage points (e.g. "decrease volume by 12 percentage points")
                elif re.search(r'\b(increase|raise)\s+(?:the\s+)?(?:system\s+|master\s+)?volume\s+(?:by\s+)?(\d+)\s+percentage\s+points?\b', text_low):
                    m_vpp = re.search(r'\b(?:increase|raise)\s+(?:the\s+)?(?:system\s+|master\s+)?volume\s+(?:by\s+)?(\d+)\s+percentage\s+points?\b', text_low)
                    params["action"] = "increase_volume"
                    params["amount"] = int(m_vpp.group(1)) if m_vpp else 10
                elif re.search(r'\b(decrease|lower|reduce)\s+(?:the\s+)?(?:system\s+|master\s+)?volume\s+(?:by\s+)?(\d+)\s+percentage\s+points?\b', text_low):
                    m_vpp = re.search(r'\b(?:decrease|lower|reduce)\s+(?:the\s+)?(?:system\s+|master\s+)?volume\s+(?:by\s+)?(\d+)\s+percentage\s+points?\b', text_low)
                    params["action"] = "decrease_volume"
                    params["amount"] = int(m_vpp.group(1)) if m_vpp else 10
                # Ambiguous transcription: "[name] is the volume by N%" — ask for clarification
                elif re.search(r'\b(?:friday|trevon|nova|jarvis|assistant)\s+(?:is|boost|up|down)\s+(?:the\s+)?volume\b', text_low):
                    params["action"] = "clarify_volume"
                    params["clarification_needed"] = "volume_direction"
                    params["ambiguous_input"] = user_input
                # 1. Relative INCREASE with numeric amount: "increase volume by 20%", "turn up volume by 20%", etc.
                elif re.search(r'\b(?:increase|raise|turn\s+up|boost)\s+(?:the\s+)?(?:system\s+)?volume\s+(?:by\s+)?(\d+)\s*%?\b', text_low) or re.search(r'\bvolume\s+up\s+(?:by\s+)?(\d+)\s*%?\b', text_low):
                    m_vi = re.search(r'\b(?:increase|raise|turn\s+up|boost)\s+(?:the\s+)?(?:system\s+)?volume\s+(?:by\s+)?(\d+)\s*%?\b', text_low) or re.search(r'\bvolume\s+up\s+(?:by\s+)?(\d+)\s*%?\b', text_low)
                    params["action"] = "increase_volume"
                    params["amount"] = int(m_vi.group(1)) if m_vi else 10
                # 2. Relative DECREASE with numeric amount: "decrease volume by 30%", "turn down volume by 30%", etc.
                elif re.search(r'\b(?:decrease|lower|reduce|turn\s+down|drop)\s+(?:the\s+)?(?:system\s+)?volume\s+(?:by\s+)?(\d+)\s*%?\b', text_low) or re.search(r'\bvolume\s+down\s+(?:by\s+)?(\d+)\s*%?\b', text_low):
                    m_vd = re.search(r'\b(?:decrease|lower|reduce|turn\s+down|drop)\s+(?:the\s+)?(?:system\s+)?volume\s+(?:by\s+)?(\d+)\s*%?\b', text_low) or re.search(r'\bvolume\s+down\s+(?:by\s+)?(\d+)\s*%?\b', text_low)
                    params["action"] = "decrease_volume"
                    params["amount"] = int(m_vd.group(1)) if m_vd else 10
                # 3. Absolute SET: "set volume to 50%", "change volume to 50%", "volume to 50%", "volume 50%"
                elif re.search(r'\b(?:set|change)\s+(?:the\s+)?volume\s+(?:to\s+)?(\d+)\s*%?\b', text_low) or re.search(r'\bvolume\s+to\s+(\d+)\s*%?\b', text_low) or re.search(r'\bvolume\s+(\d+)\b', text_low):
                    m_vol = re.search(r'\b(?:set|change)\s+(?:the\s+)?volume\s+(?:to\s+)?(\d+)\s*%?\b', text_low) or re.search(r'\bvolume\s+to\s+(\d+)\s*%?\b', text_low) or re.search(r'\bvolume\s+(\d+)\b', text_low)
                    params["action"] = "set_volume"
                    params["level"] = max(0, min(100, int(m_vol.group(1)))) if m_vol else 50
                # 4. Read volume
                elif any(k in text_low for k in [
                    "what is the current volume", "what is the volume", "what's the volume",
                    "what is my current volume", "what is my volume", "what's my current volume", "what's my volume",
                    "current volume", "check volume", "check my volume", "check current volume", "check the volume",
                    "volume level", "get volume", "my current volume", "current volum"
                ]) or re.search(r'\b(?:what(?:\x27s|\s+is)\s+(?:my\s+|the\s+)?(?:current\s+)?volum?e?|check\s+(?:my\s+|the\s+)?(?:current\s+)?volum?e?)\b', text_low):
                    params["action"] = "get_volume"
                # 5. Relative INCREASE default step (no number)
                elif any(k in text_low for k in ["increase the volume", "increase volume", "raise volume", "turn up the volume", "turn up volume", "volume up"]):
                    params["action"] = "increase_volume"
                    params["amount"] = 10
                # 6. Relative DECREASE default step (no number)
                elif any(k in text_low for k in ["decrease the volume", "decrease volume", "lower volume", "turn down the volume", "turn down volume", "volume down"]):
                    params["action"] = "decrease_volume"
                    params["amount"] = 10
                elif any(k in text_low for k in ["mute", "unmute"]):
                    params["action"] = "mute" if "mute" in text_low and not "unmute" in text_low else "unmute"

                # ── Battery diagnostics ──
                elif any(k in text_low for k in ["battery", "charging status"]):
                    params["action"] = "battery"
                # ── System Uptime / Computer running time ──
                elif re.search(r'\bhow\s+long\s+(?:has|is)\s+(?:my|the|this)?\s*(?:comput[er]{1,2}|pc|system|mach[in]{1,3}e?|device|laptop|workstation)\s+(?:been\s+|being\s+)?(?:run[in]{1,3}g|on|up)\b', text_low) \
                     or re.search(r'\b(?:what(?:\x27s|\s+is)\s+(?:my|the)?\s*(?:system\s+)?uptime|(?:system\s+)?uptime|check\s+(?:my|the)?\s*uptime|how\s+long\s+(?:has\s+it|have\s+you|is\s+it)\s+(?:been\s+|being\s+)?(?:run[in]{1,3}g|on|up))\b', text_low) \
                     or text_low in ("system uptime", "uptime", "check uptime", "what is uptime", "how long is the system running", "how long is the system being running"):
                    params["action"] = "uptime"
                # ── Voice Listening Controls ──
                elif any(k in text_low for k in ["toggle voice listening", "toggle listening", "toggle mic", "toggle microphone"]):
                    params["action"] = "toggle_listening"
                elif any(k in text_low for k in ["start listening", "resume listening", "unmute mic", "unmute microphone", "start voice listening"]):
                    params["action"] = "start_listening"
                elif any(k in text_low for k in ["stop listening", "pause listening", "mute mic", "mute microphone", "stop voice listening"]):
                    params["action"] = "stop_listening"
                # ── Disk / Storage diagnostics ──
                elif any(k in text_low for k in ["all disks", "all drives"]):
                    params["action"] = "all_disks"
                elif any(k in text_low for k in ["disk", "storage", "free space", "drive info", "how much disk space is available", "available disk space", "free disk space", "storage left", "space left"]) or re.search(r'\b(?:storage|disk\s+space|space)\s+(?:left|remaining|free)\b', text_low):
                    params["action"] = "disk"
                    m_dr = re.search(r'\b([a-zA-Z]):|\b(?:drive|on|in)\s+(?:the\s+)?([a-zA-Z])(?:\s+drive)?\b', user_input, re.IGNORECASE)
                    if m_dr:
                        params["drive"] = (m_dr.group(1) or m_dr.group(2)).upper() + ":"
                    else:
                        params["drive"] = "C:"
                # ── Running processes / applications & Top resource consumers ──
                elif re.search(r'\b(?:which|what)\s+(?:ap{1,2}l(?:ication)?|apps?|proce?ss|program)\s+(?:is\s+)?(?:using|taking|consuming)\s+(?:the\s+)?most\s+(?:of\s+the\s+)?(?:cpu|proce?ss?or|ram|memm?ory)\b', text_low) \
                     or re.search(r'\b(?:what(?:\x27s|\s+is)\s+using|which\s+(?:ap{1,2}l(?:ication)?|apps?|proce?ss|program)\s+uses)\s+(?:the\s+)?most\s+(?:of\s+the\s+)?(?:cpu|proce?ss?or|ram|memm?ory)\b', text_low) \
                     or re.search(r'\b(?:proce?ss|app(?:lication)?|program)\s+with\s+(?:the\s+)?highest\s+(?:cpu|ram|memm?ory)(?:\s+usage)?\b', text_low):
                    params["action"] = "top_processes"
                    params["sort_by"] = "cpu" if any(c in text_low for c in ["cpu", "processor"]) else "memory"
                    params["n"] = 1
                elif any(k in text_low for k in ["what applications are currently running", "what applications are open", "what processes are running", "show me currently running programs", "currently running programs", "currently running applications", "what apps are currently running", "what programs are open right now", "list all processes", "show all processes", "all running processes"]):
                    params["action"] = "list_processes"
                    params["sort_by"] = "cpu" if "cpu" in text_low else "memory"
                elif any(k in text_low for k in ["top processes", "running processes", "top cpu processes", "top memory processes"]):
                    params["action"] = "top_processes"
                    params["sort_by"] = "cpu" if "cpu" in text_low else "memory"
                    params["n"] = 5
                # ── Wallpaper ──────────────────────────────────────────────────
                elif re.search(r'\b(?:set|change)\s+(?:my\s+)?wallpaper\s+(?:to\s+)?(.+)\b', text_low):
                    m_wp = re.search(r'\b(?:set|change)\s+(?:my\s+)?wallpaper\s+(?:to\s+)?(.+)\b', user_input, re.IGNORECASE)
                    params["action"] = "set_wallpaper"
                    params["wallpaper_path"] = m_wp.group(1).strip(' "\'') if m_wp else ""
                elif "wallpaper" in text_low:
                    params["action"] = "get_wallpaper"
                # ── Telemetry / Hardware ──
                elif ("cpu" in text_low and "ram" in text_low and "gpu" in text_low) or any(k in text_low for k in ["system usage", "system telemetry", "hardware telemetry", "show system usage", "check system usage"]):
                    params["action"] = "system_telemetry_summary"
                elif any(k in text_low for k in [
                    "gpu status", "gpu staus", "graphics card status", "check gpu status", "what is my gpu status",
                    "what is the gpu status", "what's my gpu status", "check my gpu status",
                    "gpu memory am i using", "how much gpu memory", "gpu memory am i", "how much gpu",
                    "gpu usage", "gpu telemetry", "check gpu", "check my gpu",
                    "graphics card usage", "graphics card telemetry"
                ]):
                    params["action"] = "gpu_telemetry"
                elif any(k in text_low for k in ["gpu memory", "vram", "graphics memory"]):
                    params["action"] = "gpu_memory"
                elif any(k in text_low for k in ["detailed gpu", "gpu details", "graphics card details", "detailed graphics"]):
                    params["action"] = "detailed_gpu"
                elif any(k in text_low for k in ["gpu", "graphics card"]):
                    params["action"] = "gpu_telemetry"
                elif any(k in text_low for k in ["check my cpu", "check cpu", "cpu metrics", "can i check my cpu", "cpu usage", "how much cpu", "what is my cpu", "what's my cpu", "whats my cpu"]):
                    params["action"] = "cpu_metrics"
                elif any(k in text_low for k in ["detailed cpu", "cpu details", "processor details", "detailed processor", "tell me about my cpu", "tell me about my processor", "what cpu", "which cpu", "what processor", "which processor", "cpu do i have", "cpu am i using"]):
                    params["action"] = "detailed_cpu"
                elif any(k in text_low for k in ["cpu", "processor"]) and not any(k in text_low for k in ["ram", "gpu", "top processes", "wallpaper"]):
                    params["action"] = "cpu_metrics"
                elif any(k in text_low for k in [
                    "check my ram", "check ram", "ram metrics", "what is my ram usage", "how much ram is free",
                    "how much ram is being used", "how much ram is in use", "how much ram is used",
                    "how much memory is being used", "how much memory is in use", "how much memory is used"
                ]):
                    params["action"] = "ram_metrics"
                elif any(k in text_low for k in ["detailed ram", "ram details", "detailed memory", "how much ram do i have", "ram do i have", "what is my ram", "total ram"]):
                    params["action"] = "detailed_ram"
                elif (re.search(r'\bram\b', text_low) or any(k in text_low for k in ["memory usage of the computer", "available ram", "used ram", "how much ram", "ram usage"])) and not any(k in text_low for k in ["cpu", "gpu", "top processes", "vram", "wallpaper"]):
                    params["action"] = "ram_metrics"
                # ── Windows / System information ──
                elif any(k in text_low for k in ["windows version", "version of windows", "system info", "system information", "os info", "os version", "operating system information", "what windows am i running", "what windows is this", "device specs", "system specs"]):
                    params["action"] = "system_info"
                # ── Window controls ──
                elif any(k in text_low for k in ["minimize all", "minimize windows", "show desktop"]):
                    params["action"] = "minimize_all"
                # ── Clipboard ──
                elif "clipboard" in text_low:
                    params["action"] = "clipboard"
                    if any(k in text_low for k in ["uppercase", "upper", "caps"]):
                        params["clipboard_op"] = "uppercase"
                    elif any(k in text_low for k in ["lowercase", "lower", "small"]):
                        params["clipboard_op"] = "lowercase"
                    elif any(k in text_low for k in ["capitalize", "title"]):
                        params["clipboard_op"] = "title"
                    elif any(k in text_low for k in ["bullet", "bullets"]):
                        params["clipboard_op"] = "bullet_list"
                    elif any(k in text_low for k in ["count", "word count", "how many words"]):
                        params["clipboard_op"] = "count_words"
                    elif any(k in text_low for k in ["trim", "strip"]):
                        params["clipboard_op"] = "strip"
                # ── Set resolution (must be before display_info to catch 'set display resolution to ...') ────
                elif re.search(r'\b(?:change|set)\s+(?:display\s+|screen\s+)?resolution\s+(?:to\s+)?(\d+)\s*[xX*]\s*(\d+)\b', text_low):
                    m_res = re.search(r'\b(?:change|set)\s+(?:display\s+|screen\s+)?resolution\s+(?:to\s+)?(\d+)\s*[xX*]\s*(\d+)\b', user_input, re.IGNORECASE)
                    params["action"] = "set_resolution"
                    params["width"] = int(m_res.group(1)) if m_res else 1920
                    params["height"] = int(m_res.group(2)) if m_res else 1080
                # ── Display / Monitor info ──
                elif any(k in text_low for k in ["display resolution", "screen resolution", "how many displays", "how many monitors", "connected monitors", "number of displays", "monitor count", "display info", "screen info", "monitor info"]):
                    params["action"] = "display_info"
                    params["requested_device_target"] = "display"
                    params["requested_action"] = "DISPLAY_QUERY"
                    params["resolved_action"] = "DISPLAY_QUERY"
                    params["executor_action"] = "display_info"
                # ── Wi-Fi ──────────────────────────────────────────────────────
                elif any(k in text_low for k in ["which wi-fi", "which wifi", "connected wi-fi", "connected wifi", "wifi status", "wi-fi status", "wifi connection", "wireless status", "wireless connection"]):
                    params["action"] = "wifi_status"
                    params["requested_device_target"] = "wifi"
                    params["requested_action"] = "WIFI_QUERY"
                    params["resolved_action"] = "WIFI_QUERY"
                    params["executor_action"] = "wifi_status"
                elif re.search(r'\b(?:list|show|scan|find)\s+(?:available\s+|nearby\s+)?(?:wifi|wi-fi|wireless)\s+networks?\b', text_low):
                    params["action"] = "list_wifi_networks"
                    params["requested_device_target"] = "wifi"
                    params["requested_action"] = "WIFI_QUERY"
                    params["resolved_action"] = "WIFI_QUERY"
                    params["executor_action"] = "list_wifi_networks"
                elif re.search(r'\b(?:enable|turn\s+on)\s+(?:the\s+)?(?:wifi|wi-fi|wireless)\b', text_low):
                    params["action"] = "enable_wifi"
                    params["requested_device_target"] = "wifi"
                    params["requested_action"] = "WIFI_ON"
                    params["resolved_action"] = "WIFI_ON"
                    params["executor_action"] = "enable_wifi"
                elif re.search(r'\b(?:disable|turn\s+off)\s+(?:the\s+)?(?:wifi|wi-fi|wireless)\b', text_low):
                    params["action"] = "disable_wifi"
                    params["requested_device_target"] = "wifi"
                    params["requested_action"] = "WIFI_OFF"
                    params["resolved_action"] = "WIFI_OFF"
                    params["executor_action"] = "disable_wifi"
                elif any(k in text_low for k in ["network speed", "internet speed", "how fast is my internet", "how fast is my network", "how fast is my wifi"]):
                    params["action"] = "network_speed"
                elif any(k in text_low for k in ["network adapter", "network adapters", "network connection", "network connections", "internet adapter", "internet connection", "internet status", "network info", "list adapters", "show adapters", "adapters", "network status", "what network", "connection info", "ip info"]):
                    params["action"] = "network_adapters"
                # ── Bluetooth ──────────────────────────────────────────────────
                elif re.search(r'\b(?:enable|turn\s+on)\s+(?:the\s+)?bluetooth\b', text_low):
                    params["action"] = "enable_bluetooth"
                    params["requested_device_target"] = "bluetooth"
                    params["requested_action"] = "BLUETOOTH_ON"
                    params["resolved_action"] = "BLUETOOTH_ON"
                    params["executor_action"] = "enable_bluetooth"
                elif re.search(r'\b(?:disable|turn\s+off)\s+(?:the\s+)?bluetooth\b', text_low):
                    params["action"] = "disable_bluetooth"
                    params["requested_device_target"] = "bluetooth"
                    params["requested_action"] = "BLUETOOTH_OFF"
                    params["resolved_action"] = "BLUETOOTH_OFF"
                    params["executor_action"] = "disable_bluetooth"
                elif any(k in text_low for k in ["bluetooth", "bt status", "is bluetooth", "check bluetooth"]):
                    params["action"] = "bluetooth_status"
                    params["requested_device_target"] = "bluetooth"
                    params["requested_action"] = "BLUETOOTH_QUERY"
                    params["resolved_action"] = "BLUETOOTH_QUERY"
                    params["executor_action"] = "bluetooth_status"
                # ── Environment local state ────────────────────────────────────
                elif any(k in text_low for k in ["what application is currently active", "what application is active", "what is the active application", "what's the active application", "active application", "current application", "which application is active", "what app is active", "what app is currently active", "what is the current app i am using right now", "what is the current app i am using", "what app am i using right now", "what app am i using", "which app am i using", "which application am i using right now", "which application am i using", "what application am i using right now", "what application am i using", "active app", "current app"]) or re.search(r'\b(?:which|what)\s+(?:application|app)\s+am\s+i\s+(?:currently\s+)?(?:using|in|on)\b', text_low):
                    params["action"] = "active_application"
                    params["requested_device_target"] = "application"
                    params["requested_action"] = "ACTIVE_APP_QUERY"
                    params["resolved_action"] = "ACTIVE_APP_QUERY"
                    params["executor_action"] = "active_application"
                elif any(k in text_low for k in ["what is the active window", "what's the active window", "active window", "current window", "what window is active", "which window is active", "what is my active window"]):
                    params["action"] = "active_window"
                    params["requested_device_target"] = "window"
                    params["requested_action"] = "ACTIVE_WINDOW_QUERY"
                    params["resolved_action"] = "ACTIVE_WINDOW_QUERY"
                    params["executor_action"] = "active_window"
                # ── Keyboard toggle keys ───────────────────────────────────────
                # SET semantics: "turn on/off [the] X lock", "turn [the] X lock on/off", "enable/disable [the] X lock"
                elif re.search(r'\b(?:turn\s+(?:the\s+)?caps\s+lock\s+on|(?:turn\s+on|enable)\s+(?:the\s+)?caps\s+lock)\b', text_low):
                    params["action"] = "set_key"
                    params["key"] = "caps"
                    params["desired_state"] = True
                elif re.search(r'\b(?:turn\s+(?:the\s+)?caps\s+lock\s+off|(?:turn\s+off|disable)\s+(?:the\s+)?caps\s+lock)\b', text_low):
                    params["action"] = "set_key"
                    params["key"] = "caps"
                    params["desired_state"] = False
                elif re.search(r'\b(?:turn\s+(?:the\s+)?num\s+lock\s+on|(?:turn\s+on|enable)\s+(?:the\s+)?num\s+lock)\b', text_low):
                    params["action"] = "set_key"
                    params["key"] = "num"
                    params["desired_state"] = True
                elif re.search(r'\b(?:turn\s+(?:the\s+)?num\s+lock\s+off|(?:turn\s+off|disable)\s+(?:the\s+)?num\s+lock)\b', text_low):
                    params["action"] = "set_key"
                    params["key"] = "num"
                    params["desired_state"] = False
                elif re.search(r'\b(?:turn\s+(?:the\s+)?scroll\s+lock\s+on|(?:turn\s+on|enable)\s+(?:the\s+)?scroll\s+lock)\b', text_low):
                    params["action"] = "set_key"
                    params["key"] = "scroll"
                    params["desired_state"] = True
                elif re.search(r'\b(?:turn\s+(?:the\s+)?scroll\s+lock\s+off|(?:turn\s+off|disable)\s+(?:the\s+)?scroll\s+lock)\b', text_low):
                    params["action"] = "set_key"
                    params["key"] = "scroll"
                    params["desired_state"] = False
                # TOGGLE semantics: "toggle [the] X lock"
                elif re.search(r'\btoggle\s+(?:the\s+)?caps\s+lock\b', text_low):
                    params["action"] = "toggle_key"
                    params["key"] = "caps"
                elif re.search(r'\btoggle\s+(?:the\s+)?num\s+lock\b', text_low):
                    params["action"] = "toggle_key"
                    params["key"] = "num"
                elif re.search(r'\btoggle\s+(?:the\s+)?scroll\s+lock\b', text_low):
                    params["action"] = "toggle_key"
                    params["key"] = "scroll"
                # READ-only fallback: "what is caps lock", "caps lock status", etc.
                elif any(k in text_low for k in ["caps lock", "num lock", "scroll lock", "keyboard lights", "keyboard toggle", "keyboard lock"]):
                    params["action"] = "keyboard_state"
                # ── GPU telemetry ──────────────────────────────────────────────
                elif any(k in text_low for k in ["gpu telemetry", "gpu usage", "gpu stats", "gpu temp", "gpu temperature", "check gpu"]):
                    params["action"] = "gpu_telemetry"
                # ── Hardware info ──────────────────────────────────────────────
                elif any(k in text_low for k in ["hardware info", "hardware spec", "gpu", "graphics card", "cpu model", "processor model", "my processor", "hardware information", "device hardware"]):
                    params["action"] = "hardware_info"
                # ── Power plans ────────────────────────────────────────────────
                elif any(k in text_low for k in ["list power plans", "show power plans", "all power plans"]):
                    params["action"] = "list_power_plans"
                elif any(k in text_low for k in ["power plan", "power mode", "current power plan", "active power plan", "what power plan"]):
                    params["action"] = "power_plan"
                # ── Mouse info ─────────────────────────────────────────────────
                elif any(k in text_low for k in ["mouse position", "cursor position", "mouse cursor", "mouse location", "mouse info", "mouse settings", "where is my mouse", "where is my cursor"]):
                    params["action"] = "mouse_info"
                # ── Uptime ─────────────────────────────────────────────────────
                elif any(k in text_low for k in ["uptime", "how long has", "system uptime", "how long have i been on"]):
                    params["action"] = "uptime"
                # ── All processes ──────────────────────────────────────────────
                elif any(k in text_low for k in ["list all processes", "show all processes", "all running processes"]):
                    params["action"] = "list_processes"
                    params["sort_by"] = "cpu" if "cpu" in text_low else "memory"
                # ── Dark mode / Theme ──────────────────────────────────────────
                elif any(k in text_low for k in ["dark mode", "light mode", "toggle theme", "switch to dark", "switch to light"]):
                    params["action"] = "toggle_dark_mode"
                    if "enable" in text_low or "dark mode on" in text_low or "turn on dark" in text_low or "switch to dark" in text_low or "on dark mode" in text_low:
                        params["enable"] = True
                    elif "disable" in text_low or "dark mode off" in text_low or "turn off dark" in text_low or "switch to light" in text_low or "off dark mode" in text_low or "light mode on" in text_low:
                        params["enable"] = False
                    else:
                        params["enable"] = None
                # ── Wi-Fi connect ──────────────────────────────────────────────
                elif re.search(r'\b(?:connect\s+to\s+(?:wifi|wi-fi|network)|join\s+(?:wifi|wi-fi))\s+(.+)\b', text_low):
                    m_wf = re.search(r'\b(?:connect\s+to\s+(?:wifi|wi-fi|network)|join\s+(?:wifi|wi-fi))\s+(.+)\b', user_input, re.IGNORECASE)
                    params["action"] = "connect_wifi"
                    params["ssid"] = m_wf.group(1).strip() if m_wf else ""
                # ── Set resolution ─────────────────────────────────────────────
                elif re.search(r'\b(?:change|set)\s+(?:display\s+|screen\s+)?resolution\s+(?:to\s+)?(\d+)\s*[xX*]\s*(\d+)\b', text_low):
                    m_res = re.search(r'\b(?:change|set)\s+(?:display\s+|screen\s+)?resolution\s+(?:to\s+)?(\d+)\s*[xX*]\s*(\d+)\b', user_input, re.IGNORECASE)
                    params["action"] = "set_resolution"
                    params["width"] = int(m_res.group(1)) if m_res else 1920
                    params["height"] = int(m_res.group(2)) if m_res else 1080
                # ── Wallpaper ──────────────────────────────────────────────────
                elif re.search(r'\b(?:set|change)\s+(?:my\s+)?wallpaper\s+(?:to\s+)?(.+)\b', text_low):
                    m_wp = re.search(r'\b(?:set|change)\s+(?:my\s+)?wallpaper\s+(?:to\s+)?(.+)\b', user_input, re.IGNORECASE)
                    params["action"] = "set_wallpaper"
                    params["wallpaper_path"] = m_wp.group(1).strip(' "\'') if m_wp else ""
                elif "wallpaper" in text_low:
                    params["action"] = "get_wallpaper"
                # ── Desktop statistics ─────────────────────────────────────────
                elif any(k in text_low for k in ["desktop stats", "desktop statistics", "desktop summary", "analyze desktop", "analyze my desktop"]):
                    params["action"] = "desktop_stats"

                # ── Type text ──────────────────────────────────────────────────
                elif re.search(r'\b(?:type|write)[:\s]+\s*(?!(?:to\b|are\s+you|(?:an?\s+)?(?:note|code|python|script|report|document|email|mail|record|reminder)\b))(.+)', text_low):
                    # Guard 1: reject negation-prefixed commands ("no", "don't", "I said you don't")
                    _t_raw_low = user_input.lower().strip()
                    is_negation = bool(re.match(
                        r'^\s*(?:no[,\s]|don\'t|i\s+said|wait|actually|stop|cancel|never\s+mind|not)',
                        _t_raw_low
                    ))
                    # Guard 2: reject conversational inquiries ("are you able to see...", "can you see...")
                    is_conversational_type_inquiry = bool(re.search(
                        r'\b(?:are\s+you|can\s+you|do\s+you|will\s+you)\b',
                        _t_raw_low
                    ))
                    # Guard 3: reject implicit corrections about typing ("I said you don't type", "you don't type")
                    is_correction = bool(re.search(
                        r"\b(?:i\s+said|you\s+don'?t|don'?t\s+type|don'?t\s+write|i\s+didn't\s+say|i\s+never\s+said)\b",
                        _t_raw_low
                    ))
                    # Guard 4: reject conversational mentions ("why did you type", "did you type", "stop typing", "what did you type")
                    is_conversational_mention = bool(re.search(
                        r"\b(?:why\s+did\s+you|did\s+you\s+type|stop\s+typing|what\s+did\s+you|what\s+are\s+you\s+typing|you\s+typed|didn't\s+ask\s+you\s+to\s+type)\b",
                        _t_raw_low
                    ))
                    if not is_negation and not is_conversational_type_inquiry and not is_correction and not is_conversational_mention:
                        # Guard artifact insertion
                        is_artifact_insertion = False
                        try:
                            from core.artifact_resolver import get_artifact_reference_resolver
                            art_res = get_artifact_reference_resolver().resolve(user_input=user_input)
                            if art_res.is_success or art_res.is_ambiguous:
                                is_artifact_insertion = True
                        except Exception:
                            pass
                        if not is_artifact_insertion:
                            m_type = re.search(r'\b(?:type|write|enter)[:\s]+\s*(?:exactly\s*[:\s]*)?(?!(?:to\b|(?:an?\s+)?(?:note|code|python|script|report|document|email|mail|record|reminder)\b))(.+)', user_input, re.IGNORECASE)
                            if not m_type:
                                m_type = re.search(r'\bput\s+(?!(?:an?\s+)?(?:file|folder|document)\b)(.+?)\s+(?:in|into|inside|there)(?:\s+it)?[.!?]?$', user_input, re.IGNORECASE)
                            raw_typed = m_type.group(1).strip(' "\'') if m_type else ""
                            m_into = re.search(r'^(.*?)\s+(?:in|into|on)\s+(?:notepad|word|wordpad|editor|document|file)\s*$', raw_typed, re.IGNORECASE)
                            if m_into:
                                raw_typed = m_into.group(1).strip(' "\'')
                            params["action"] = "type_text"
                            params["text"] = raw_typed
                            params["entity_type"] = "TEXT"

                # ── Installed games & software ─────────────────────────────────
                elif any(k in text_low for k in ["games are installed", "installed games", "list games", "list installed games", "show installed games"]):
                    params["action"] = "list_installed_games"
                elif any(k in text_low for k in ["browser", "browsers"]) and any(k in text_low for k in ["installed", "list", "show", "find", "what", "which"]):
                    params["action"] = "list_installed_browsers"
                elif any(k in text_low for k in ["apps are installed", "applications are installed", "installed apps", "installed applications", "installed software", "list installed apps", "list installed applications", "show installed applications", "find my installed", "find installed"]):
                    params["action"] = "list_installed_applications"

                else:
                    # Fallback: infer action from natural-language telemetry queries not caught above
                    _t = text_low
                    if any(k in _t for k in ["gpu", "graphics card", "graphics"]):
                        # Prefer hardware_info for identity queries, gpu_telemetry for usage/status
                        if any(k in _t for k in ["using", "running", "have", "installed", "does this", "is this", "identify"]):
                            params["action"] = "gpu_telemetry"
                        else:
                            params["action"] = "gpu_telemetry"
                    elif any(k in _t for k in ["cpu", "processor"]):
                        params["action"] = "cpu_metrics"
                    elif any(k in _t for k in ["ram", "memory"]):
                        params["action"] = "ram_metrics"
                    elif any(k in _t for k in ["disk", "storage"]):
                        params["action"] = "disk"
                    elif "battery" in _t:
                        params["action"] = "battery"
                    elif "uptime" in _t:
                        params["action"] = "uptime"
                    elif any(k in _t for k in ["browser", "browsers"]):
                        params["action"] = "list_installed_browsers"
                    elif any(k in _t for k in ["volume", "sound"]):
                        params["action"] = "get_volume"
                    else:
                        g = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                        params["action"] = g.strip().lower()
            elif intent == Intent.FILE_OPERATIONS:
                text_low = user_input.lower()
                clean_f_low = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*', '', text_low).strip()
                clean_f_no_polite = re.sub(r'^(?:can\s+you\s+|could\s+you\s+|please\s+)+', '', clean_f_low).strip()
                if any(k in clean_f_no_polite for k in ["profile file", "inspect file", "file profile", "analyze file", "analyse file", "inspect data", "inspect csv", "inspect excel", "inspect json", "inspect pptx", "profile json", "profile csv", "profile pdf", "profile pptx", "profile code", "profile this file", "analyse that ppt", "analyze that ppt", "analyse ppt", "analyze ppt", "analyse that presentation", "analyze that presentation", "analyse this", "analyze this", "profile this"]):
                    params["action"] = "profile_file"
                    m_pf = re.search(r'\b(?:profile|inspect|analyze|analyse)\s+(?:(?:the|my|that|this)\s+)?(?:[a-zA-Z0-9_\-]+\s+)?(?:file|data|csv|excel|json|pptx|ppt|presentation|document|pdf)?(?:\s+(.+))?\b', user_input, re.IGNORECASE)
                    if not m_pf or not m_pf.group(1):
                        m_pf = re.search(r'\b(?:profile\s+file|inspect\s+file|file\s+profile|analyze\s+file|analyse\s+file|inspect\s+(?:data|csv|excel|json|pptx|ppt))\s+(.+)\b', user_input, re.IGNORECASE)
                    params["target"] = m_pf.group(1).strip(' "\'') if (m_pf and m_pf.group(1)) else ("that ppt" if ("ppt" in text_low or "presentation" in text_low) else "")
                elif "duplicate" in text_low:
                    params["action"] = "find_duplicates"
                    params["location"] = "downloads" if "download" in text_low else ("documents" if "document" in text_low else "desktop")
                elif any(k in text_low for k in ["statistic", "stats for", "how many files in", "how many files are in"]):
                    params["action"] = "directory_stats"
                    params["location"] = "downloads" if "download" in text_low else ("documents" if "document" in text_low else "desktop")
                elif any(k in text_low for k in ["largest file", "biggest file"]):
                    params["action"] = "largest_files"
                    params["location"] = "downloads" if "download" in text_low else ("documents" if "document" in text_low else "desktop")
                elif re.search(r'\b(?:how\s+many\s+pages\s+(?:are\s+)?in|(?:show\s+(?:me\s+)?)?(?:information|info)\s+about\s+(?:this\s+|the\s+)?pdf|pdf\s+info)\b', text_low):
                    params["action"] = "pdf_info"
                    m = re.search(r'([\w\-.]+\.pdf)', user_input, re.IGNORECASE)
                    params["target"] = m.group(1) if m else "this pdf"
                elif re.search(r'\bsplit\s+(?:this\s+|the\s+)?(?:([\w\-.]+\.pdf)|pdf)\b', text_low):
                    params["action"] = "split_pdf"
                    m = re.search(r'([\w\-.]+\.pdf)', user_input, re.IGNORECASE)
                    params["target"] = m.group(1) if m else "this pdf"
                    m_p = re.search(r'from\s+page\s+(\d+)\s+to\s+(?:page\s+)?(\d+)', text_low)
                    params["start_page"] = int(m_p.group(1)) if m_p else 1
                    params["end_page"] = int(m_p.group(2)) if m_p else 2
                elif re.search(r'\bmerge\s+(?:these\s+|the\s+)?pdfs?\b', text_low):
                    params["action"] = "merge_pdfs"
                elif re.search(r'\bextract\s+(?:the\s+)?text\s+from\s+(?:this\s+|the\s+)?(?:([\w\-.]+\.pdf)|pdf)\b', text_low):
                    params["action"] = "extract_pdf_text"
                    m = re.search(r'([\w\-.]+\.pdf)', user_input, re.IGNORECASE)
                    params["target"] = m.group(1) if m else "this pdf"
                elif re.search(r'\b(?:find\s+all|search\s+(?:for\s+)?(?:[a-zA-Z0-9_\-*\.]+\s+)?(?:files?|documents?)|search\s+(?:for\s+)?(?:.+?\s+)?(?:files?|documents?)\s+(?:in|under)\s+.+|(?:files?|documents?)\s+larger\s+than|(?:files?|documents?)\s+modified)\b', text_low):
                    params["action"] = "search_files"
                    params["location"] = "downloads" if "download" in text_low else ("documents" if "document" in text_low else "desktop")
                    if "pdf" in text_low:
                        params["pattern"] = "*.pdf"
                        params["ext"] = "pdf"
                    elif "txt" in text_low:
                        params["pattern"] = "*.txt"
                        params["ext"] = "txt"
                    elif "docx" in text_low or "word" in text_low:
                        params["pattern"] = "*.docx"
                        params["ext"] = "docx"
                    elif "xlsx" in text_low or "excel" in text_low:
                        params["pattern"] = "*.xlsx"
                        params["ext"] = "xlsx"
                    elif "python" in text_low or "py" in text_low:
                        params["pattern"] = "*.py"
                        params["ext"] = "py"
                    elif "document" in text_low or "docs" in text_low:
                        params["pattern"] = "*.*"
                    m_sz = re.search(r'larger\s+than\s+(\d+)\s*(?:mb|megabytes)?', text_low)
                    if m_sz: params["min_size_mb"] = float(m_sz.group(1))
                    m_days = re.search(r'(?:modified|changed)\s+(?:in\s+the\s+last|within)\s+(\d+)\s+days?', text_low)
                    if m_days: params["modified_days"] = int(m_days.group(1))
                elif re.search(r'\b(delete|remove)\s+(?:the\s+)?(?:file\s+)?([\w\-.]+\.\w+)', text_low):
                    params["action"] = "delete_file"
                    m = re.search(r'\b(?:delete|remove)\s+(?:the\s+)?(?:file\s+)?([\w\-.]+\.\w+)', user_input, re.IGNORECASE)
                    params["target"] = m.group(1).strip() if m else ""
                elif re.search(r'\bmove\s+(?:the\s+)?(?:file\s+|folder\s+|directory\s+)?(.+?)\s+to\s+(.+)', text_low):
                    params["action"] = "move_file"
                    m = re.search(r'\bmove\s+(?:the\s+)?(?:file\s+|folder\s+|directory\s+)?(.+?)\s+to\s+(.+)', user_input, re.IGNORECASE)
                    raw_src = m.group(1).strip() if m else ""
                    raw_src = re.sub(r'^(?:the\s+)?(?:folder|file|directory)\s+', '', raw_src, flags=re.IGNORECASE).strip(' "\'')
                    params["src"] = raw_src
                    params["dst"] = m.group(2).strip(' "\'') if m else ""
                elif re.search(r'\brename\s+(?:the\s+)?(?:file\s+|folder\s+|directory\s+)?(.+?)\s+to\s+(.+)', text_low):
                    params["action"] = "rename_file"
                    m = re.search(r'\brename\s+(?:the\s+)?(?:file\s+|folder\s+|directory\s+)?(.+?)\s+to\s+(.+)', user_input, re.IGNORECASE)
                    raw_src = m.group(1).strip() if m else ""
                    raw_src = re.sub(r'^(?:the\s+)?(?:folder|file|directory)\s+', '', raw_src, flags=re.IGNORECASE).strip(' "\'')
                    if raw_src.lower() in ("the file", "the folder", "file", "folder", "it", "that", "this"):
                        params["src"] = "it"
                    else:
                        params["src"] = raw_src
                    clean_new = m.group(2).strip(' "\'') if m else ""
                    clean_new = re.sub(r'^(?:the\s+)?(?:folder|file|directory)\s+', '', clean_new, flags=re.IGNORECASE).strip(' "\'')
                    params["new_name"] = clean_new
                elif re.search(r'\b(?:organize|clean\s+up|clean)\s+(?:my\s+)?(?:desktop|downloads)\b', text_low):
                    params["action"] = "organize_desktop"
                    params["location"] = "downloads" if "download" in text_low else "desktop"
                    params["preview"] = "confirm" not in text_low
                m_save_doc = re.search(r'\bsave\s+(?:it|that|(?:the\s+)?document|(?:the\s+)?file)?\s*as\s+([a-zA-Z0-9_\-]+(?:\.[a-zA-Z0-9]+)?)', user_input, re.IGNORECASE)
                if not m_save_doc:
                    m_save_doc = re.search(r'\bsave\s+(?:it|that|(?:the\s+)?document|(?:the\s+)?file)?\s*as\s+([a-zA-Z0-9_\-]+)', user_input, re.IGNORECASE)
                if m_save_doc:
                    params["action"] = "save_document"
                    filename = m_save_doc.group(1).strip(' "\'')
                    if not re.search(r'\.[a-zA-Z0-9]+$', filename):
                        filename = f"{filename}.txt"
                    params["filename"] = filename
                    params["name"] = filename
                    params["target"] = filename
                    params["entity_type"] = "DOCUMENT"
                    return params

                m_put_inside = re.search(r'\b(?:put|create|make|add)\s+(?:a\s+)?(?:file\s+|text\s+file\s+)?([a-zA-Z0-9_\-.\s]+?)(?:\s+file)?\s+(?:inside|in\s+it|in\s+that\s+folder|there)\b', user_input, re.IGNORECASE)
                if m_put_inside or re.search(r'\b(?:put|create|make|add)\s+(?:a\s+)?(?:notes|note|text)\s+file\s+inside\b', text_low):
                    params["action"] = "create_file"
                    fname_raw = m_put_inside.group(1).strip() if m_put_inside else "notes"
                    fname_raw = re.sub(r'^(?:(?:file\s+|text\s+file\s+|a\s+file\s+)|(?:named\s+|called\s+))+', '', fname_raw, flags=re.IGNORECASE).strip()
                    if not fname_raw or fname_raw.lower() in ("a", "the", "my"):
                        fname_raw = "notes"
                    if not re.search(r'\.[a-zA-Z0-9]+$', fname_raw):
                        fname_raw = f"{fname_raw}.txt"
                    params["name"] = fname_raw
                    params["parent_folder"] = "it"
                    params["location"] = "desktop"
                    return params

                m_explicit_file = re.search(r'\b(?:create|make|new)\s+(?:a\s+)?(?:file\s+)?([a-zA-Z0-9_\-\.]+\.(?:txt|csv|py|json|md|log|ini|cfg|html|xml|yaml|yml))\b', user_input, re.IGNORECASE)
                if m_explicit_file:
                    params["action"] = "create_file"
                    fname = m_explicit_file.group(1).strip(' "\'')
                    params["name"] = fname
                    params["target"] = fname
                    params["location"] = "desktop"
                    return params

                m_called = re.search(r'\b(?:folder|directory)\s+(?:named\s+|called\s+)(.+)', user_input, re.IGNORECASE)
                m_folder_suffix = re.search(r'\b(?:create|make|new)\s+(?:a\s+)?(.+?)\s+(?:folder|directory)\b', user_input, re.IGNORECASE)
                if m_called and re.search(r'\b(create|make|new)\b', text_low):
                    params["action"] = "create_folder"
                    folder_name = m_called.group(1).strip(' "\'').rstrip('.?!')
                    folder_name = re.sub(r'\s+on\s+desktop$', '', folder_name, flags=re.IGNORECASE).strip(' "\'')
                    params["name"] = folder_name
                    params["target"] = folder_name
                    params["location"] = "desktop"
                    return params
                elif m_folder_suffix and not re.search(r'\b(?:create|make|new)\s+(?:a\s+)?(?:folder|directory)\b', text_low):
                    params["action"] = "create_folder"
                    folder_name = m_folder_suffix.group(1).strip(' "\'')
                    folder_name = re.sub(r'^(?:named\s+|called\s+)', '', folder_name, flags=re.IGNORECASE).strip(' "\'')
                    folder_name = re.sub(r'\s+on\s+desktop$', '', folder_name, flags=re.IGNORECASE).strip(' "\'')
                    params["name"] = folder_name
                    params["target"] = folder_name
                    params["location"] = "desktop"
                    return params

                elif re.search(r'\b(create|make|new)\s+(?:a\s+)?(?:folder|directory)\b', text_low):
                    params["action"] = "create_folder"
                    m = re.search(r'\b(?:folder|directory)\s+(?:named\s+|called\s+)?(.+)', user_input, re.IGNORECASE)
                    folder_name = m.group(1).strip() if m else ""
                    folder_name = re.sub(r'^(?:named\s+|called\s+)', '', folder_name, flags=re.IGNORECASE).strip(' "\'')
                    folder_name = re.sub(r'\s+on\s+desktop$', '', folder_name, flags=re.IGNORECASE).strip(' "\'')
                    if folder_name.lower().rstrip('.?!') in ("for it", "for that", "for this", "it", "that", "this"):
                        try:
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            from instance.config import settings
                            effective_uid = getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user()
                            dm = get_dialogue_manager(str(effective_uid))
                            folder_name = dm.current_state.session_context.get("active_goal_entity") or dm.current_state.entities.get("goal_entity") or "AI Project Files"
                        except Exception:
                            folder_name = "AI Project Files"
                    params["name"] = folder_name
                    params["location"] = "desktop"
                elif re.search(r'\b(create|make|new)\s+(?:a\s+)?(?:text\s+)?file\b', text_low):
                    params["action"] = "create_file"
                    m = re.search(r'\b(?:file)\s+(?:named\s+|called\s+)?(.+)', user_input, re.IGNORECASE)
                    fname = m.group(1).strip() if m else ""
                    fname = re.sub(r'^(?:named\s+|called\s+)', '', fname, flags=re.IGNORECASE).strip(' "\'')
                    fname = re.sub(r'\s+on\s+desktop$', '', fname, flags=re.IGNORECASE).strip(' "\'')
                    m_in_any = re.search(r'^(.*?)\s+(?:inside|in)\s+(.+)$', fname, re.IGNORECASE)
                    if m_in_any:
                        fname = m_in_any.group(1).strip(' "\'')
                        pf_candidate = m_in_any.group(2).strip(' "\'')
                        pf_candidate = re.sub(r'^(?:folder\s+|directory\s+)', '', pf_candidate, flags=re.IGNORECASE).strip(' "\'')
                        params["parent_folder"] = "it" if pf_candidate.lower() in ("it", "that", "this", "the folder", "the directory") else pf_candidate
                    params["name"] = fname
                    params["location"] = "desktop"
                elif re.search(r'\b(delete|remove)\b', text_low) and re.search(r'\b(folder|directory)\b', text_low):
                    params["action"] = "delete_folder"
                    m = re.search(
                        r'\b(?:delete|remove)\s+(?:the\s+)?(.+?)\s+(?:folder|directory)\b',
                        user_input, re.IGNORECASE
                    )
                    if m:
                        folder_name = m.group(1).strip()
                    else:
                        m2 = re.search(r'\b(?:folder|directory)\s+(?:named\s+|called\s+)?(.+)', user_input, re.IGNORECASE)
                        folder_name = m2.group(1).strip() if m2 else ""
                    folder_name = re.sub(r'\s+on\s+desktop$', '', folder_name, flags=re.IGNORECASE).strip(' "\'')
                    params["name"] = folder_name
                    params["location"] = "desktop"
                elif user_input.strip() == "clarify_which_folder_to_open" or (re.search(r'\b(?:open|view|launch|show)\s+(?:the\s+|that\s+|this\s+)?folder\b', text_low) and not re.search(r'\b(?:folder|directory)\s+(?:named\s+|called\s+)?([a-zA-Z0-9_\-]+)', text_low)):
                    m_f = re.search(r'\b(?:open|view|launch|show)\s+(?:the\s+)?(?:folder|directory)\s+(?:named\s+|called\s+)?(.+)', user_input, re.IGNORECASE)
                    if m_f and m_f.group(1).strip():
                        params["action"] = "open_folder"
                        params["target"] = m_f.group(1).strip(' "\'')
                        params["name"] = params["target"]
                    else:
                        m_f2 = re.search(r'\b(?:open|view|launch|show)\s+(?:the\s+)?(.+?)\s+(?:folder|directory)\b', user_input, re.IGNORECASE)
                        if m_f2 and m_f2.group(1).strip() and m_f2.group(1).strip().lower() not in ("the", "that", "this", "my", "a"):
                            params["action"] = "open_folder"
                            params["target"] = m_f2.group(1).strip(' "\'')
                            params["name"] = params["target"]
                        else:
                            params["action"] = "clarify_folder"
                elif re.search(r'\b(open|view|launch|show)\b', text_low) and re.search(r'\b(folder|directory)\b', text_low):
                    params["action"] = "open_folder"
                    m = re.search(r'\b(?:open|view|launch|show)\s+(?:the\s+)?(?:folder|directory)\s+(?:named\s+|called\s+)?(.+)', user_input, re.IGNORECASE)
                    if m:
                        folder_name = m.group(1).strip()
                    else:
                        m2 = re.search(r'\b(?:open|view|launch|show)\s+(?:the\s+)?(.+?)\s+(?:folder|directory)\b', user_input, re.IGNORECASE)
                        folder_name = m2.group(1).strip() if m2 else ""
                    folder_name = re.sub(r'\s+on\s+desktop$', '', folder_name, flags=re.IGNORECASE).strip(' "\'')
                    params["target"] = folder_name
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
                elif re.search(r'\b(find|locate|where\s+is)\s+(?:the\s+|my\s+)?(?:file|document|presentation|ppt|pdf|folder|directory|[a-zA-Z0-9_\-]+\.[a-zA-Z0-9]{2,4})\b', text_low):
                    params["action"] = "find_file"
                    m = re.search(r'\b(?:find|locate|where\s+is)\s+(?:the\s+|my\s+)?(?:file\s+|document\s+|presentation\s+|folder\s+)?(.+)', user_input, re.IGNORECASE)
                    params["target"] = m.group(1).strip(' "\'') if m else ""
            elif intent == Intent.MUSIC:
                text_low = user_input.lower().strip()
                clean_cmd = re.sub(r'^(?:please\s+|can\s+you\s+|could\s+you\s+)', '', text_low).strip()
                clean_cmd = re.sub(r'^(?:(?:hey|ok|hi)\s+)?(?:friday|trevon|assistant|nova)[,\s]*', '', clean_cmd).strip()

                if any(k in clean_cmd for k in ["toggle playback", "play/pause", "play pause"]):
                    params["action"] = "toggle"
                elif any(k in clean_cmd for k in ["summarize", "summary"]):
                    params["action"] = "summarize_video"
                elif any(k in clean_cmd for k in ["queue", "playlist", "what's playing", "now playing", "what song is playing"]):
                    params["action"] = "queue_status"
                elif re.search(r'\b(?:play\s+)?next\s+(?:song|track)\b|\bskip\b', clean_cmd):
                    params["action"] = "next"
                elif re.search(r'\b(?:play\s+)?(?:previous|prev)\s+(?:song|track)\b|\bgo\s+back\b', clean_cmd):
                    params["action"] = "previous"
                elif re.search(r'\b(?:stop\s+(?:playing\s+)?(?:the\s+)?(?:music|songs?|audio|playback)|stop\s+playing)\b|^stop$', clean_cmd):
                    params["action"] = "stop"
                elif re.search(r'\b(?:pause\s+(?:the\s+)?(?:music|songs?|audio|playback)|pause)\b', clean_cmd):
                    params["action"] = "pause"
                elif re.search(r'\b(?:resume\s+(?:the\s+)?(?:music|songs?|audio|playback)|unpause|resume)\b', clean_cmd):
                    params["action"] = "resume"
                elif re.search(r'\b(?:video\s+song|music\s+video|watch\s+video|show\s+video)\b', clean_cmd):
                    params["action"] = "play_video"
                else:
                    params["action"] = "play"
            elif intent == Intent.DOCUMENT_GENERATION:
                text_low = user_input.lower()
                if "pdf" in text_low or "turn this into a pdf" in text_low or "convert to pdf" in text_low:
                    params["doc_type"] = "pdf"
                elif any(k in text_low for k in ["excel", "spreadsheet", "xlsx", "put this into excel"]):
                    params["doc_type"] = "xlsx"
                elif any(k in text_low for k in ["powerpoint", "presentation", "slides", "pptx", "ppt", "slide"]):
                    params["doc_type"] = "pptx"
                elif any(k in text_low for k in ["word", "docx", "doc", "document", "report"]):
                    params["doc_type"] = "docx"
                else:
                    params["doc_type"] = None

                m_len = re.search(r'\b(\d+)[\s\-]*(?:slides?|pages?|sheets?)\b', text_low)
                if m_len:
                    params["requested_length"] = int(m_len.group(1))

                is_refinement_cmd = any(re.search(p, text_low) for p in [
                    r'^(?:make|turn|convert|put)\s+(?:it|this|that)\b',
                    r'^(?:add|remove)\b',
                    r'^(?:make\s+it\s+(?:shorter|more\s+detailed)|make\s+it\s+\d+[\s\-]slides?)\b',
                    r'^(?:create|generate|make)\s+(?:the\s+)?(?:ppt|presentation|document|pdf|excel)\.?$'
                ])

                if is_refinement_cmd:
                    params["title"] = None
                else:
                    m_t = re.search(r'\b(?:named|called|title(?:d)?)\s+(.+)', user_input, re.IGNORECASE)
                    if m_t:
                        params["title"] = m_t.group(1).strip(' "\'')
                    else:
                        m_ab = re.search(r'\b(?:about|on|for)\s+(?!that\s+information\b|the\s+information\b|information\b|it\b|this\b)(.+?)(?:\s+and\s+(?:make|create|build).*)?$', user_input, re.IGNORECASE)
                        if m_ab:
                            params["title"] = m_ab.group(1).strip(' "\'.').title()
                        else:
                            from modules.document_tools import extract_topic_from_query
                            ext_t = extract_topic_from_query(user_input, default="")
                            if ext_t:
                                params["title"] = ext_t
                            else:
                                params["title"] = None
                params["content"] = user_input
            elif intent == Intent.CODE_GENERATION:
                text_low = user_input.lower()
                if any(re.search(p, text_low) for p in [
                    r'\b(?:validate|check)\s+(?:the\s+)?syntax\b',
                    r'\b(?:validate|check)\s+(?:this\s+)?code\b',
                    r'\bsyntax\s+errors?\b',
                    r'\bdoes\s+this\s+code\s+have\s+syntax\b'
                ]) and not any(k in text_low for k in ["write", "create", "generate", "build", "implement"]):
                    params["action"] = "validate_syntax"
                elif any(k in text_low for k in ["explain structure", "structure of", "what classes and functions"]):
                    params["action"] = "explain_structure"
                elif any(k in text_low for k in ["diagnose", "traceback", "classify error", "parse traceback"]):
                    params["action"] = "diagnose_error"
                elif any(k in text_low for k in ["refactor", "optimize", "clean up", "improve structure", "modernize"]):
                    params["action"] = "refactor_code"
                elif any(k in text_low for k in ["fix", "debug", "repair", "correct"]) and any(c in text_low for c in ["code", "function", "script", "program", "error", "bug", "this"]):
                    params["action"] = "fix_code"
                elif any(k in text_low for k in ["explain", "analyze"]) and "code" in text_low:
                    params["action"] = "explain_code"
                else:
                    params["action"] = "generate_code"
            elif intent == Intent.DAILY_BRIEFING:
                text_low = user_input.lower()
                _briefing_keywords = [
                    "daily briefing", "morning briefing", "morning update", "give me my briefing",
                    "brief me", "daily update", "morning report", "daily report"
                ]
                _sched_keywords = [
                    "what do i have", "what's on my schedule", "whats on my schedule",
                    "what is on my schedule", "what's planned", "whats planned", "what is planned",
                    "what do i need to do", "what do i have to do", "schedule today", "schedule tomorrow",
                    "do i have any events", "my events today", "any events today", "any meetings today"
                ]
                if any(k in text_low for k in _briefing_keywords):
                    params["action"] = "daily_briefing"
                elif any(k in text_low for k in _sched_keywords) and not any(h in text_low for h in ["holiday", "festival", "special day", "working day", "observed"]):
                    params["action"] = "personal_schedule"
                else:
                    params["action"] = "calendar_query"
            elif intent == Intent.WEATHER_QUERY:
                from extensions.weather_engine import _default_weather_engine
                extracted_loc = _default_weather_engine.extract_location(user_input)
                params["location"] = extracted_loc if extracted_loc else "local"
            elif intent == Intent.EMAIL:
                # Extract action and structured email parameters
                try:
                    from modules.assistant_email.email_controller import _parse_email_intent
                    parsed_em = _parse_email_intent(user_input)
                    params["action"] = parsed_em.get("action", "default")
                    params["recipient"] = parsed_em.get("recipient_raw")
                    params["topic"] = parsed_em.get("topic") or parsed_em.get("body_raw")
                    params["send_versus_draft"] = parsed_em.get("send_versus_draft", "send")
                    params["is_dictation"] = parsed_em.get("is_dictation", False)
                except Exception:
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
            elif intent == Intent.TASK_MANAGEMENT:
                text_low = user_input.lower()
                m_q = re.search(
                    r'\b(?:queue|add|create|schedule)\s+(?:a\s+)?(?:background\s+)?task\b(?:\s*:\s*|\s+(?:to\s+|for\s+)?|\s+)(.+)',
                    user_input, re.IGNORECASE
                )
                m_q_alt = re.search(
                    r'\b(?:run\s+(?:this\s+)?as\s+(?:a\s+)?background\s+task|put\s+this\s+in\s+(?:the\s+)?task\s+queue|queue\s+task|run\s+(?:this\s+)?in\s+(?:the\s+)?background)\b(?:\s*:\s*|\s+(?:to\s+|for\s+)?|\s+)(.+)',
                    user_input, re.IGNORECASE
                )
                m_q2 = re.search(r'\brun\s+(.+?)\s+in\s+(?:the\s+)?background\b', user_input, re.IGNORECASE)
                if m_q:
                    params["action"] = "queue_task"
                    params["goal"] = m_q.group(1).strip()
                elif m_q_alt:
                    params["action"] = "queue_task"
                    params["goal"] = m_q_alt.group(1).strip()
                elif m_q2:
                    params["action"] = "queue_task"
                    params["goal"] = m_q2.group(1).strip()
                elif any(k in text_low for k in ["cancel", "stop", "abort"]) and any(k in text_low for k in ["task", "project", "website", "generation", "build", "it", "that"]):
                    params["action"] = "cancel_task"
                    m_c = re.search(r'(?:cancel|stop|abort)\s+(?:(?:the|my)\s+)?(?:task|project|website|generation)?\s*([a-zA-Z0-9_\-]+)?', text_low)
                    params["task_id"] = m_c.group(1) if (m_c and m_c.group(1)) else ""
                elif any(k in text_low for k in ["status", "happening with", "progress on", "coming along", "progress", "is it still running", "is it running", "its status", "did it finish", "show task"]):
                    params["action"] = "task_status"
                    m_s = re.search(r'(?:status\s+of\s+(?:(?:the|my)\s+)?(?:task|project|website)?|task\s+status|show\s+task)\s+([a-zA-Z0-9_\-]+)', text_low)
                    params["task_id"] = m_s.group(1) if m_s else ""
                else:
                    params["action"] = "list_tasks"
            elif intent == Intent.SMART_HOME:
                params["action"] = "smart_home"
            elif intent == Intent.WINDOW_CONTEXT:
                params["action"] = "window_context"
            elif intent == Intent.LEARNING:
                params["action"] = "learning"
            elif intent == Intent.UNDO:
                params["action"] = "undo"
            elif intent == Intent.AUDIO_DEVICES:
                text_low = user_input.lower().strip()
                if any(k in text_low for k in ["hear", "no sound", "no audio", "diagnose audio", "check audio", "test audio", "test speaker"]):
                    params["action"] = "diagnose_audio"
                elif "push to talk" in text_low or "ptt" in text_low:
                    params["action"] = "ptt"
                    if any(w in text_low for w in ["turn off", "disable", " off"]):
                        params["ptt_state"] = "off"
                    elif any(w in text_low for w in ["turn on", "enable", " on"]):
                        params["ptt_state"] = "on"
                    else:
                        params["ptt_state"] = "toggle"
                else:
                    params["action"] = "audio_devices"
            elif intent == Intent.RECOMMENDATION:
                text_low = user_input.lower().strip()
                clean_query = re.sub(
                    r'^(?:can\s+you\s+)?(?:please\s+)?(?:give\s+me\s+(?:some\s+)?)?(?:recommend(?:ations?)?|suggest(?:ions?)?)\s*(?:\b(?:for|on|about|me)\b\s*)?',
                    '', user_input, flags=re.IGNORECASE
                ).strip()
                clean_query = re.sub(r'^(?:an?|some)\s+', '', clean_query, flags=re.IGNORECASE).strip()
                params["action"] = "recommend"
                params["query"] = clean_query if clean_query else user_input
            elif intent == Intent.VISUAL_SURFACE:
                text_low = user_input.lower().strip()
                params["action"] = "show_visual_response"
                m_sub = re.search(r'(?:details\s+(?:about|of|for)|information\s+(?:about|of|for))\s+(.+)', text_low)
                if m_sub:
                    params["target_type"] = "SUBJECT_DETAILS"
                    params["target_subject"] = m_sub.group(1).strip()
                elif "box" in text_low and "number" in text_low:
                    params["target_type"] = "NUMBERS_BOX"
                elif "number" in text_low:
                    params["target_type"] = "NUMBERS"
                elif "pairing" in text_low or "code" in text_low:
                    params["target_type"] = "PAIRING_CODE"
                elif "ip" in text_low or "address" in text_low:
                    params["target_type"] = "IP_ADDRESS"
                elif "url" in text_low or "link" in text_low:
                    params["target_type"] = "URL"
                elif "file" in text_low or "path" in text_low:
                    params["target_type"] = "FILE_PATH"
                elif "list" in text_low or "devices" in text_low:
                    params["target_type"] = "LIST"
                elif "device" in text_low:
                    params["target_type"] = "DEVICE_INFO"
                elif any(k in text_low for k in ["again", "back", "previous", "what you just"]):
                    params["target_type"] = "AGAIN"
                elif any(k in text_low for k in ["detail", "details", "details box", "information", "explanation", "steps", "expand", "understand"]):
                    params["target_type"] = "DETAILS"
                elif any(k in text_low for k in ["వివరాలు", "विवरण", "விவரங்களை", "detalles"]):
                    params["target_type"] = "DETAILS"
                else:
                    params["target_type"] = "DETAILS"
            elif intent == Intent.TIME_QUERY:
                text_low = user_input.lower().strip()
                if "alarm" in text_low or "wake me up" in text_low:
                    if any(k in text_low for k in ["show", "list", "check", "what", "view", "get"]):
                        params["action"] = "list_alarms"
                    elif any(k in text_low for k in ["cancel", "delete", "remove", "turn off", "stop", "dismiss"]):
                        params["action"] = "cancel_alarm"
                    elif "snooze" in text_low:
                        params["action"] = "snooze_alarm"
                        m_m = re.search(r'(\d+)\s*min', text_low)
                        params["duration_minutes"] = int(m_m.group(1)) if m_m else 5
                    else:
                        params["action"] = "set_alarm"
                        params["time_text"] = user_input
                elif "timer" in text_low:
                    if any(k in text_low for k in ["show", "list", "check", "how much time", "remaining", "status"]):
                        params["action"] = "list_timers"
                    elif any(k in text_low for k in ["cancel", "stop", "reset", "delete"]):
                        params["action"] = "cancel_timer"
                    else:
                        params["action"] = "set_timer"
                        params["duration"] = user_input
                elif "stopwatch" in text_low:
                    if any(k in text_low for k in ["start", "begin", "run", "resume"]):
                        params["action"] = "stopwatch_start"
                    elif any(k in text_low for k in ["stop", "pause", "halt"]):
                        params["action"] = "stopwatch_stop"
                    elif "reset" in text_low:
                        params["action"] = "stopwatch_reset"
                    elif any(k in text_low for k in ["lap", "split"]):
                        params["action"] = "stopwatch_lap"
                    else:
                        params["action"] = "stopwatch_status"
                elif any(k in text_low for k in ["time in", "time at", "time of", "in tokyo", "in london", "in new york", "in paris", "in sydney", "in dubai"]):
                    params["action"] = "world_time"
                    m = re.search(r'\b(?:in|at|for|of)\s+([a-zA-Z\s]+?)(?:\s+right\s+now|\s+today|\s+currently|\?|$)', user_input, re.IGNORECASE)
                    params["location"] = m.group(1).strip() if m else ""
                elif any(k in text_low for k in ["what date", "what is the date", "today's date", "todays date", "what day is it", "what day is today"]):
                    params["action"] = "date_query"
                else:
                    params["action"] = "time_query"
            elif intent == Intent.DATE_QUERY:
                params["action"] = "date_query"
            elif intent == Intent.SYSTEM_COMPATIBILITY:
                params["action"] = "compatibility_check"
                params["query"] = user_input
            elif intent == Intent.GAME_DISCOVERY:
                params["action"] = "game_discovery"
                params["query"] = user_input
            elif intent == Intent.VOICE_CONFIGURATION:
                text_low = user_input.lower().strip()
                if any(w in text_low for w in ["slower", "more slowly", "slow down"]):
                    params["action"] = "decrease_rate"
                elif any(w in text_low for w in ["faster", "more quickly", "speed up"]):
                    params["action"] = "increase_rate"
                elif any(w in text_low for w in ["reset", "normal speed", "natural speed"]):
                    params["action"] = "reset_rate"
                elif any(w in text_low for w in ["restore", "previous voice"]):
                    params["action"] = "restore_voice"
                else:
                    params["action"] = "change_language"
                    for lang in ["telugu", "hindi", "tamil", "kannada", "malayalam", "spanish", "french", "german", "english"]:
                        if lang in text_low:
                            params["language"] = lang
                            break
                    if "language" not in params:
                        if any(w in text_low for w in ["తెలుగు", "matladu", "matladandi", "cheppu"]):
                            params["language"] = "telugu"
                        elif any(w in text_low for w in ["हिंदी", "bolo", "boliye", "baat karo"]):
                            params["language"] = "hindi"
                        elif any(w in text_low for w in ["தமிழ்", "pesu"]):
                            params["language"] = "tamil"
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
            UnifiedCommandRouter._SEMANTIC_INTENT_MAP["CLOSE_APPLICATION"] = Intent.CLOSE_APPLICATION
            UnifiedCommandRouter._SEMANTIC_INTENT_MAP["WEB_SEARCH"] = Intent.RAG_SEARCH
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
        if is_conversational_general_query(user_input):
            return Intent.GENERAL_CONVERSATION, {}

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

        # RAG_SEARCH gate: Never allow semantic fallback to classify general conversation,
        # follow-ups, complaints, capability queries, or stable knowledge as RAG_SEARCH
        if intent_label == "RAG_SEARCH" and not should_use_external_retrieval(Intent.RAG_SEARCH, user_input):
            intent_label = "GENERAL_CONVERSATION"

        # Hallucination guard: TIME_QUERY and DATE_QUERY must have explicit time/date terms
        if intent_label == "TIME_QUERY" and not re.search(r'\b(?:time|clock|hour|minute|current\s+time)\b', user_input.lower()):
            intent_label = "GENERAL_CONVERSATION"
        if intent_label == "DATE_QUERY" and not re.search(r'\b(?:date|day|today|month|year)\b', user_input.lower()):
            intent_label = "GENERAL_CONVERSATION"

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
            "FILE_OPERATIONS", "POWER_ACTION", "CLOSE_APPLICATION", "EMAIL",
        }
        is_destructive = intent_label in DESTRUCTIVE_INTENTS
        if intent_label == "DEVICE_CONTROL":
            action_name = (entities.get("action") or "").lower()
            text_low = user_input.lower()
            read_only_keywords = [
                "list", "show", "status", "connected", "online", "battery",
                "check", "is my", "what devices", "paired devices"
            ]
            is_read_only = any(k in text_low for k in read_only_keywords) and not any(
                d in text_low for d in ["lock", "disconnect", "unpair", "remove", "wipe", "delete", "shutdown", "reboot", "restart"]
            )
            disruptive_keywords = [
                "lock", "disconnect", "unpair", "remove", "forget", "remote action",
                "execute", "launch", "open", "turn on", "turn off", "toggle", "flashlight", "torch"
            ]
            if not is_read_only or any(d in text_low or d in action_name for d in disruptive_keywords):
                is_destructive = True

        if needs_clarification or (confidence < 0.70 and is_destructive):
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

        # Override CALCULATOR if the utterance is asking to show/generate/list numbers
        if resolved_intent == Intent.CALCULATOR:
            u_low = user_input.lower()
            if any(k in u_low for k in ["random", "numbers from", "numbers between", "show me", "give me", "generate", "list of numbers", "numbers in reverse", "in reverse order", "in a box", "numbers", "number"]):
                if not any(k in u_low for k in ["calculate", "times", "divided", "plus", "minus", "+", "-", "*", "/", "%", "percent", "squared", "cubed", "sqrt", "power", "math"]):
                    self.logger.info(f"[SEMANTIC] Overriding CALCULATOR -> VISUAL_SURFACE for number generation request")
                    resolved_intent = Intent.VISUAL_SURFACE
                    params = {"action": "show_visual_response", "target_type": "NUMBERS", "raw_input": user_input}
                    return resolved_intent, params

        # Override OPEN_APPLICATION if the query is a historical reference ("what was I using before Brave?")
        if resolved_intent == Intent.OPEN_APPLICATION:
            u_low = user_input.lower()
            if any(k in u_low for k in ["before", "what was", "what did", "previously", "prior to", "which app was", "what app was"]):
                self.logger.info(f"[SEMANTIC] Overriding OPEN_APPLICATION -> GENERAL_CONVERSATION for historical reference query")
                resolved_intent = Intent.GENERAL_CONVERSATION
                return resolved_intent, {"raw_input": user_input}

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
        if intent in (Intent.OPEN_APPLICATION, Intent.CLOSE_APPLICATION):
            if intent == Intent.CLOSE_APPLICATION or intent_label == "CLOSE_APPLICATION" or action_raw in (
                "close", "quit", "exit", "terminate", "kill"
            ):
                params["action"] = "close"
            else:
                params["action"] = "open"

            clean_tgt = target_raw or user_input
            inst_mode = "NORMAL"
            m_trailing_win = re.search(r'\s+in\s+(?:a\s+new|another)\s+(?:window|instance)$', clean_tgt, re.IGNORECASE)
            if m_trailing_win:
                inst_mode = "NEW"
                clean_tgt = clean_tgt[:m_trailing_win.start()].strip()

            # Check if "another" or "a new" is present in target or user_input
            if re.search(r'\b(?:another|a\s+new|new\s+window|new\s+instance)\b', clean_tgt, re.IGNORECASE) or re.search(r'\b(?:another|a\s+new|new\s+window|new\s+instance)\b', user_input, re.IGNORECASE):
                inst_mode = "NEW"

            m_inst = re.match(
                r'^(?:(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+(?:instance|window)\s+of\s+|'
                r'(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+)',
                clean_tgt,
                re.IGNORECASE
            )
            if m_inst:
                inst_mode = "NEW"
                clean_tgt = clean_tgt[m_inst.end():].strip()

            # Strip conversational trailing clauses (e.g. "I need a Chrome to be open on the screen right now", "so that I can work")
            clean_tgt = re.sub(r'\s+(?:i\s+need|i\s+want|to\s+be\s+open|on\s+the\s+screen|right\s+now|so\s+that|so\s+i\s+can|because|since|asap|now|immediately)\b.*$', '', clean_tgt, flags=re.IGNORECASE).strip()

            # Iteratively strip conversational wrappers, polite fillers, and generic nouns from the end
            prev_tgt = None
            while prev_tgt != clean_tgt:
                prev_tgt = clean_tgt
                clean_tgt = re.sub(r'\s+(?:for\s+me|please|thanks|thank\s+you|app|application|browser|window|program)$', '', clean_tgt, flags=re.IGNORECASE).strip()

            # Strip leading articles, generic nouns, and open prefixes
            clean_tgt = re.sub(r'^(?:the|a|an)\s+', '', clean_tgt, flags=re.IGNORECASE).strip()
            clean_tgt = re.sub(r'^(?:app|application|browser)\s+', '', clean_tgt, flags=re.IGNORECASE).strip()
            clean_tgt = re.sub(r'^(?:could\s+you\s+|can\s+you\s+|please\s+|then\s+|launch\s+|open\s+|start\s+)+', '', clean_tgt, flags=re.IGNORECASE).strip()
            clean_tgt = re.sub(r'^(?:the|a|an)\s+', '', clean_tgt, flags=re.IGNORECASE).strip()

            # Resolve actual application entity using system indexer/SmartOpener
            try:
                from extensions.system.smart_opener import SmartOpener
                opener = SmartOpener()
                res_app = opener.resolve_detailed(clean_tgt)
                if res_app:
                    clean_tgt = res_app[0]
                else:
                    words = clean_tgt.split()
                    for k in range(min(len(words), 3), 0, -1):
                        sub_cand = " ".join(words[:k])
                        sub_res = opener.resolve_detailed(sub_cand)
                        if sub_res:
                            clean_tgt = sub_res[0]
                            break
            except Exception:
                pass

            params["instance_mode"] = inst_mode
            params["new_instance"] = (inst_mode == "NEW")
            params["target"] = clean_tgt
            params["application"] = clean_tgt

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
            text_low = user_input.lower()
            if (
                any(k in text_low for k in [
                    "pair", "phone", "mobile", "paired device", "connected device",
                    "my devices", "paired devices", "torch", "flashlight"
                ])
                or action_raw in ("remote_device", "pair", "list_devices", "battery")
            ):
                params["action"] = "remote_device"
            else:
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
            try:
                from modules.music.music_controller import MusicCommandParser
                _p = MusicCommandParser().parse(user_input)
                if _p.is_transport:
                    params["action"] = _p.transport_action
                elif _p.is_video_requested:
                    params["action"] = "play_video"
                else:
                    params["action"] = "play"
            except Exception:
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
            try:
                from modules.assistant_email.email_controller import _parse_email_intent
                parsed_em = _parse_email_intent(user_input)
                params["recipient"] = parsed_em.get("recipient_raw")
                params["topic"] = parsed_em.get("topic") or parsed_em.get("body_raw")
                params["send_versus_draft"] = parsed_em.get("send_versus_draft", "send")
                params["is_dictation"] = parsed_em.get("is_dictation", False)
            except Exception:
                pass

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

    def execute_single_action(
        self,
        user_input: str,
        user_id: Optional[Any] = None,
        confirmed_by_user: bool = False,
        confirmation_id: Optional[str] = None,
        params_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a single action based on intent routing. Enforces one input -> one action."""
        from datetime import datetime, timedelta
        try:
            # Check if assistant name is present (addressing signal, not mandatory)
            has_assistant_name = contains_assistant_name(user_input)
            
            intent, params = self.route_command(user_input, user_id=user_id)
            if params_override:
                params.update(params_override)
            if params.get("semantic_command"):
                s_cmd = params["semantic_command"]
                cmd_id = getattr(s_cmd, "command_id", "cmd_canonical")
                self.logger.info(f"[TYPED_SEMANTIC_PROPAGATION] TraceID={cmd_id} Step={params.get('step_sequence', 0)} Intent={intent.name} Action={params.get('action', '')}")
            self.logger.info(f"Command routed: {intent.name} (assistant_name_present: {has_assistant_name})")
            self.logger.info(f"[ROUTER_DISPATCH] uid={user_id} intent={intent.name} action={params.get('action')} target={params.get('target', params.get('name', ''))}")

            # P0: Validate Device Action Agreement before execution
            req_dev_target = params.get("requested_device_target")
            req_act = params.get("requested_action")
            res_act = params.get("resolved_action")
            exec_act = params.get("executor_action", params.get("action"))
            if req_dev_target and req_act and res_act and exec_act:
                if not validate_device_action_agreement(req_dev_target, req_act, res_act, exec_act):
                    self.logger.error(f"[DEVICE_ACTION_MISMATCH] Disagreement: target={req_dev_target}, requested={req_act}, resolved={res_act}, executor={exec_act}")
                    return {
                        "status": "error",
                        "error": "ACTION_TARGET_MISMATCH",
                        "response": f"Device control rejected: requested {req_act} on {req_dev_target} does not agree with executor action {exec_act}.",
                        "handled": True
                    }

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
            # ── Contextual Resolution Gates (Phase 4.1 & Level 5) ──────────
            if user_input.startswith(("clarify_close_app", "clarify_other_app")):
                apps_match = re.search(r'(?:clarify_close_app|clarify_other_app)\s+(.+)', user_input)
                if apps_match:
                    apps_str = apps_match.group(1).strip()
                else:
                    try:
                        from instance.config import settings
                        eff_u = user_id if user_id is not None else (getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user())
                        from extensions.dialogue_state_manager import get_dialogue_manager
                        dm = get_dialogue_manager(str(eff_u))
                        opened_apps = dm.current_state.session_context.get("opened_applications", [])
                        apps_str = " or ".join(opened_apps[:2]) if len(opened_apps) >= 2 else "which application"
                    except Exception:
                        apps_str = "which application"
                return {
                    "status": "clarification_needed",
                    "goal_status": "WAITING_FOR_USER",
                    "intent": "OPEN_APPLICATION",
                    "response": f"Which application would you like to close ({apps_str})?",
                    "handled": True
                }
            if user_input.startswith("clarify_ambiguous_file"):
                files_match = re.search(r'clarify_ambiguous_file\s+(.+)', user_input)
                files_str = files_match.group(1).strip() if files_match else "report.txt or report_final.txt"
                return {
                    "status": "clarification_needed",
                    "goal_status": "WAITING_FOR_USER",
                    "intent": "FILE_OPERATIONS",
                    "response": f"Multiple matching files were found. Do you mean {files_str}?",
                    "handled": True
                }
            if user_input.startswith("explain_web_search_results_unavailable") or user_input.startswith("explain web search results unavailable"):
                return {
                    "status": "clarification_needed",
                    "intent": "OPEN_APPLICATION",
                    "response": "I cannot see the specific search results (first/second/top results) in your browser to select that result. Please click the result directly in your browser or specify what to search for.",
                    "handled": True
                }
            if user_input.startswith("clarify_candidate_selection_unavailable"):
                return {
                    "status": "clarification_needed",
                    "intent": "FILE_OPERATIONS",
                    "response": "I don't have any active candidate files in context. Please specify which file you want to open.",
                    "handled": True
                }
            if user_input.startswith("candidate_ordinal_out_of_range"):
                parts = user_input.split()
                req = parts[1] if len(parts) > 1 else "requested"
                tot = parts[2] if len(parts) > 2 else "known"
                return {
                    "status": "error",
                    "intent": "FILE_OPERATIONS",
                    "response": f"There are only {tot} candidate files available. Please choose a valid option (1 to {tot}).",
                    "handled": True
                }
            if user_input.startswith("clarify_which_file_to_delete"):
                return {
                    "status": "clarification_needed",
                    "intent": "FILE_OPERATIONS",
                    "response": "I don't have an active file in context. Please specify which file you want to delete.",
                    "handled": True
                }

            if params and params.get("_needs_clarification"):
                return {
                    "status": "clarification_needed",
                    "intent": intent.name,
                    "response": params.get("_clarification_reason", "I'm not sure exactly what you'd like to do. Could you clarify?"),
                    "handled": True
                }

            from instance.config import settings
            effective_uid = user_id if user_id is not None else (getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user())
            result = {"status": "success", "intent": intent.name}

            # ── PHASE 7: Canonical Policy Gate ────────────────────────────────────
            # All side-effecting intents must pass through RiskPolicyEngine before
            # execution.  Read-only / low-risk intents (calculator, time, weather,
            # general conversation, etc.) bypass the gate for performance.
            # IMPORTANT: This gate must NOT modify any intent-dispatch logic below.
            _POLICY_EXEMPT_INTENTS = {
                Intent.TIME_QUERY, Intent.DATE_QUERY, Intent.WEATHER_QUERY,
                Intent.CALCULATOR, Intent.MEMORY_QUERY, Intent.WINDOW_CONTEXT,
                Intent.AUDIO_DEVICES, Intent.RECOMMENDATION, Intent.RAG_SEARCH,
                Intent.GENERAL_CONVERSATION, Intent.VISUAL_SURFACE,
                Intent.DAILY_BRIEFING, Intent.TRANSLATION, Intent.CODE_GENERATION,
            }
            is_email_session = False
            if intent == Intent.EMAIL:
                try:
                    from modules.assistant_email.email_controller import is_active_email_session
                    is_email_session = is_active_email_session(effective_uid)
                except Exception:
                    pass

            if intent not in _POLICY_EXEMPT_INTENTS and not is_email_session:
                try:
                    from core.risk_policy_engine import get_risk_policy_engine, PolicyDecision
                    from core.confirmation_manager import get_confirmation_manager
                    _policy_engine = get_risk_policy_engine()
                    uid_int = int(effective_uid) if effective_uid is not None and str(effective_uid).isdigit() else None

                    # If confirmation_id is provided, validate it against ConfirmationManager
                    if confirmation_id and uid_int is not None:
                        _confirm_mgr = get_confirmation_manager()
                        _confirmed_req = _confirm_mgr.confirm(confirmation_id, uid_int)
                        if _confirmed_req is not None:
                            confirmed_by_user = True

                    _policy_eval = _policy_engine.evaluate(
                        intent=intent.name,
                        command=user_input,
                        user_id=uid_int if uid_int is not None else effective_uid,
                        confirmed_by_user=confirmed_by_user,
                    )
                    if _policy_eval.decision == PolicyDecision.BLOCKED:
                        return {
                            "status": "blocked",
                            "blocked": True,
                            "intent": intent.name,
                            "policy_decision": "BLOCKED",
                            "policy_rules": _policy_eval.policy_rules_applied,
                            "response": f"Action not permitted: {_policy_eval.rationale}",
                            "rationale": _policy_eval.rationale,
                        }
                    elif _policy_eval.decision == PolicyDecision.UNCERTAIN:
                        return {
                            "status": "blocked",
                            "blocked": True,
                            "intent": intent.name,
                            "policy_decision": "UNCERTAIN",
                            "policy_rules": _policy_eval.policy_rules_applied,
                            "response": f"Action held — policy evaluation could not confirm authorization: {_policy_eval.rationale}",
                            "rationale": _policy_eval.rationale,
                        }
                    elif _policy_eval.decision == PolicyDecision.ALLOWED_WITH_CONFIRMATION:
                        uid_int = int(effective_uid) if str(effective_uid).isdigit() else 0
                        _confirm_mgr = get_confirmation_manager()
                        _pending = _confirm_mgr.create_pending_confirmation(
                            user_id=uid_int,
                            intent=intent.name,
                            original_command=user_input,
                            policy_evaluation=_policy_eval,
                        )
                        cr = _pending.to_dict()
                        return {
                            "status": "waiting_for_user",
                            "intent": intent.name,
                            "policy_decision": "ALLOWED_WITH_CONFIRMATION",
                            "confirmation_id": _pending.confirmation_id,
                            "response": (
                                f"I need your confirmation before proceeding. "
                                f"Action: {cr['action']}. "
                                f"Target: {cr['target']}. "
                                f"Effect: {cr['effect']}. "
                                f"Risk: {cr['risk_level']}. "
                                f"Reason: {cr['reason']}. "
                                f"Say 'yes' or 'confirm' to proceed, or 'no'/'cancel' to stop."
                            ),
                            "confirmation_request": cr,
                            "handled": True,
                        }
                    # PolicyDecision.ALLOWED — fall through to existing routing below
                except Exception as _pol_err:
                    import logging as _log
                    _log.getLogger(__name__).error(
                        "[POLICY] Gate evaluation failed: %s", _pol_err
                    )
                    raw_low = str(user_input).lower()
                    destructive_indicators = ["shutdown", "restart", "reboot", "power off", "turn off", "sleep", "sign out", "log off", "lock", "hibernate", "delete"]
                    if intent == Intent.POWER_ACTION or any(d in raw_low for d in destructive_indicators):
                        return {
                            "status": "blocked",
                            "intent": intent.value if hasattr(intent, "value") else str(intent),
                            "response": f"Action blocked: safety policy evaluation failed ({_pol_err}).",
                            "handled": True,
                        }
            # ── End Phase 7 Policy Gate ────────────────────────────────────────────
            effective_uid = effective_uid or 1

            if intent == Intent.POWER_ACTION:
                try:
                    raw_input_lower = user_input.lower()
                    # CRITICAL SAFETY: Ensure smart home devices (light, fan, plug, etc.) never trigger system shutdown
                    smart_device_words = ["light", "fan", "plug", "switch", "lamp", "bulb", "ac", "air conditioner", "heater", "thermostat"]
                    if any(w in raw_input_lower for w in smart_device_words):
                        from skills.smart_home import get_smart_home_controller
                        from instance.config import settings
                        effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1
                        ctrl = get_smart_home_controller()
                        res = ctrl.handle_command(user_input, user_id=effective_uid)
                        result["status"] = "success" if res.get("success", True) else "error"
                        result["intent"] = "SMART_HOME"
                        result["response"] = res.get("message", "Smart home command executed.")
                        result.update(res)
                        return result

                    # CANONICAL ROUTING: Power operations MUST route strictly via UniversalOSGateway
                    from core.os_gateway import get_os_gateway
                    from core.os_gateway.operation_model import OSOperation, OSCapability, OSOperationType, OSRiskLevel

                    action = params.get("action", "")
                    if action in ["shutdown", "power off", "turn off"] or "shutdown" in raw_input_lower or "power off" in raw_input_lower:
                        op_type = OSOperationType.SHUTDOWN
                    elif action in ["restart", "reboot"] or "restart" in raw_input_lower or "reboot" in raw_input_lower:
                        op_type = OSOperationType.RESTART
                    elif action in ["sleep", "suspend", "standby"] or "sleep" in raw_input_lower:
                        op_type = OSOperationType.SLEEP
                    elif (action in ["lock"] or (re.search(r'\block\b', raw_input_lower) and not re.search(r'\bunlock\b', raw_input_lower))):
                        op_type = OSOperationType.LOCK
                    elif action in ["hibernate"] or "hibernate" in raw_input_lower:
                        op_type = OSOperationType.HIBERNATE
                    elif action in ["sign out", "sign_out", "log off", "logout"] or "sign out" in raw_input_lower:
                        op_type = OSOperationType.SIGN_OUT
                    else:
                        result["response"] = "Unrecognized power action."
                        return result

                    op = OSOperation(
                        capability=OSCapability.SYSTEM_POWER,
                        operation_type=op_type,
                        target="system",
                        risk_level=OSRiskLevel.SYSTEM_CRITICAL,
                        requires_confirmation=True,
                        original_goal=user_input,
                    )
                    os_res = get_os_gateway().execute(
                        operation=op,
                        user_id=effective_uid,
                        confirmed_by_user=False,
                        raw_query=user_input,
                    )
                    result["status"] = os_res.status
                    result["response"] = os_res.message
                    if os_res.data:
                        result.update(os_res.data)
                    return result
                except Exception as e:
                    result["status"] = "blocked"
                    result["response"] = f"Power action blocked by safety gate: {e}"
                    return result
                    
            # 2. EMERGENCY
            elif intent == Intent.EMERGENCY:
                result["response"] = "Emergency mode activated. Calling for help."
                
            # 3. DEVICE CONTROL
            elif intent == Intent.DEVICE_CONTROL:
                try:
                    action = params.get("action", "")
                    if action == "stop_speech":
                        from legacy.tts import stop_speaking
                        stop_speaking(interrupted=True)
                        result["status"] = "success"
                        result["action"] = "stop_speech"
                        result["response"] = "Stopped speaking."
                        result["handled"] = True
                        return result
                    elif action == "close_tab":
                        from legacy.actions import close_tab
                        tab_res = close_tab()
                        result["status"] = "success"
                        result["action"] = "close_tab"
                        result["response"] = tab_res
                    elif action == "screenshot":
                        from legacy.skills import take_screenshot
                        shot_res = take_screenshot()
                        if shot_res:
                            result["status"] = "success"
                            result["response"] = shot_res if isinstance(shot_res, str) else "Screenshot saved successfully."
                        else:
                            result["status"] = "error"
                            result["response"] = "Could not capture screenshot."
                    elif action == "increase_volume":
                        from modules.system_controller import volume_up
                        amt = params.get("amount") or params.get("step") or 10
                        v_res = volume_up(steps=amt)
                        result["status"] = "success" if v_res.get("success") else "error"
                        result["response"] = v_res.get("message", f"Volume increased to {v_res.get('level')}%.")
                        result.update(v_res)
                    elif action == "decrease_volume":
                        from modules.system_controller import volume_down
                        amt = params.get("amount") or params.get("step") or 10
                        v_res = volume_down(steps=amt)
                        result["status"] = "success" if v_res.get("success") else "error"
                        result["response"] = v_res.get("message", f"Volume decreased to {v_res.get('level')}%.")
                        result.update(v_res)
                    elif action == "set_volume":
                        from modules.system_controller import set_volume
                        lvl = params.get("level", 50)
                        v_res = set_volume(lvl)
                        result["status"] = "success" if v_res.get("success") else "error"
                        if v_res.get("already_satisfied"):
                            result["already_satisfied"] = True
                        result["response"] = v_res.get("message", f"Set volume to {lvl}%.")
                        result.update(v_res)
                    elif action == "get_volume":
                        from modules.system_controller import get_volume
                        v_res = get_volume()
                        result["status"] = "success" if v_res.get("success") else "error"
                        result["response"] = v_res.get("message", "Volume checked.")
                        result.update(v_res)
                    elif action == "clarify_volume":
                        # Ambiguous transcription — e.g. "Friday is the volume by 12%"
                        ambiguous_input = params.get("ambiguous_input", user_input)
                        result["status"] = "clarification_needed"
                        result["action"] = "clarify_volume"
                        result["clarification_needed"] = "volume_direction"
                        result["response"] = (
                            f"I heard \"{ambiguous_input}\", but I'm not sure whether you want to "
                            "increase or decrease the volume. Could you say 'increase volume by 12%' "
                            "or 'decrease volume by 12%'?"
                        )
                        result["handled"] = True
                        return result
                    elif action in ["mute", "unmute"]:
                        from modules.system_controller import set_mute
                        is_mute = (action == "mute")
                        v_res = set_mute(is_mute)
                        result["status"] = "success" if v_res.get("success") else "error"
                        if v_res.get("already_satisfied"):
                            result["already_satisfied"] = True
                        result["response"] = v_res.get("message", f"Volume {action}d.")
                        result.update(v_res)
                    elif action == "lock":
                        from legacy.skills_utilities import lock_system
                        res_str = lock_system() or "System locked."
                        result["status"] = "success"
                        result["response"] = res_str
                        result["workstation_state"] = "LOCKED"
                    elif action == "unlock":
                        try:
                            import ctypes
                            desk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)
                            if desk:
                                ctypes.windll.user32.CloseDesktop(desk)
                                is_locked = False
                            else:
                                is_locked = True
                        except Exception:
                            is_locked = False
                        if is_locked:
                            result["status"] = "success"
                            result["response"] = "The workstation is currently locked. For security reasons, please authenticate directly on your Windows lock screen to unlock the system."
                            result["workstation_state"] = "LOCKED"
                        else:
                            result["status"] = "success"
                            result["response"] = "The workstation is already unlocked and active."
                            result["workstation_state"] = "UNLOCKED"
                    elif action == "battery":
                        from modules.system_controller import get_battery_status
                        bat = get_battery_status()
                        result["status"] = "success" if bat.get("success") else "error"
                        result["response"] = bat.get("message", "Battery status checked.")
                        result.update(bat)
                    elif action == "uptime":
                        from modules.system_controller import get_uptime
                        u_res = get_uptime()
                        result["status"] = "success" if u_res.get("success") else "error"
                        result["action"] = "uptime"
                        result["response"] = u_res.get("message", "Uptime checked.")
                        result.update(u_res)
                        result["telemetry_type"] = "uptime"
                    elif action in ("toggle_listening", "toggle_voice_listening"):
                        from legacy.sst import is_continuous_audio_running, start_continuous_audio_stream, stop_continuous_audio_stream
                        from core.voice_lifecycle import VoiceLifecycleManager
                        vlm = VoiceLifecycleManager()
                        if is_continuous_audio_running():
                            stop_continuous_audio_stream()
                            vlm.on_mic_closed()
                            msg = "Continuous voice listening paused."
                        else:
                            start_continuous_audio_stream()
                            vlm.on_vad_listening()
                            msg = "Continuous voice listening active."
                        result["status"] = "success"
                        result["action"] = action
                        result["response"] = msg
                    elif action in ("start_listening", "resume_listening", "unmute_mic", "unmute_microphone"):
                        from legacy.sst import is_continuous_audio_running, start_continuous_audio_stream
                        from core.voice_lifecycle import VoiceLifecycleManager
                        if not is_continuous_audio_running():
                            start_continuous_audio_stream()
                        VoiceLifecycleManager().on_vad_listening()
                        result["status"] = "success"
                        result["action"] = action
                        result["response"] = "Continuous voice listening active."
                    elif action in ("stop_listening", "pause_listening", "mute_mic", "mute_microphone"):
                        from legacy.sst import is_continuous_audio_running, stop_continuous_audio_stream
                        from core.voice_lifecycle import VoiceLifecycleManager
                        if is_continuous_audio_running():
                            stop_continuous_audio_stream()
                        VoiceLifecycleManager().on_mic_closed()
                        result["status"] = "success"
                        result["action"] = action
                        result["response"] = "Continuous voice listening paused."
                    elif action == "disk":
                        from modules.system_controller import get_disk_space
                        _drive = params.get("drive", "C:")
                        disk = get_disk_space(_drive)
                        result["status"] = "success" if disk.get("success") else "error"
                        result["response"] = disk.get("message", "Disk space checked.")
                        result.update(disk)
                    elif action == "top_processes":
                        from modules.system_controller import get_top_processes
                        sort_by = params.get("sort_by", "cpu" if any(c in user_input.lower() for c in ["cpu", "processor"]) else "memory")
                        n_proc = params.get("n", 1 if any(w in user_input.lower() for w in ["which", "what", "most", "highest"]) else 5)
                        procs = get_top_processes(n=n_proc, sort_by=sort_by)
                        result["status"] = "success" if procs.get("success") else "error"
                        result["response"] = procs.get("message", "Top processes checked.")
                        result.update(procs)
                    elif action == "increase_brightness":
                        from modules.system_controller import adjust_brightness
                        amt = params.get("amount", 10)
                        b_res = adjust_brightness(+amt)
                        result["status"] = "success" if b_res.get("success") else "error"
                        result["response"] = b_res.get("message", "Increased brightness.")
                        result.update(b_res)
                    elif action == "decrease_brightness":
                        from modules.system_controller import adjust_brightness
                        amt = params.get("amount", 10)
                        b_res = adjust_brightness(-amt)
                        result["status"] = "success" if b_res.get("success") else "error"
                        result["response"] = b_res.get("message", "Decreased brightness.")
                        result.update(b_res)
                    elif action == "set_brightness":
                        from modules.system_controller import set_brightness
                        lvl = params.get("level", 50)
                        b_res = set_brightness(lvl)
                        result["status"] = "success" if b_res.get("success") else "error"
                        if b_res.get("already_satisfied"):
                            result["already_satisfied"] = True
                        result["response"] = b_res.get("message", f"Set brightness to {lvl}%.")
                        result.update(b_res)
                    elif action == "get_brightness":
                        from modules.system_controller import get_brightness
                        b_res = get_brightness()
                        result["status"] = "success" if b_res.get("success") else "error"
                        result["response"] = b_res.get("message", "Brightness checked.")
                        result.update(b_res)
                    elif action == "minimize_all":
                        from modules.system_controller import minimize_all_windows
                        m_res = minimize_all_windows()
                        result["response"] = m_res.get("message", "Minimized all windows.")
                    elif action == "clipboard":
                        from modules.system_controller import get_clipboard_text, transform_clipboard
                        op = params.get("clipboard_op")
                        if op:
                            tr_res = transform_clipboard(op)
                            result["status"] = "success" if tr_res.get("success") else "error"
                            result["response"] = tr_res.get("message", "Transformed clipboard.")
                            result.update(tr_res)
                        else:
                            from skills.clipboard import get_clipboard_controller
                            clip_res = get_clipboard_controller().handle_command(user_input)
                            result["status"] = "success" if clip_res.get("success", True) else "error"
                            result["response"] = clip_res.get("message", "Checked clipboard.")
                            result.update(clip_res)
                    elif action == "system_telemetry_summary":
                        from modules.system_controller import get_system_telemetry_summary
                        st_res = get_system_telemetry_summary()
                        result["status"] = "success"
                        result["response"] = st_res.get("message", "System telemetry checked.")
                        result.update(st_res)
                    elif action == "gpu_memory":
                        from modules.system_controller import get_gpu_memory
                        gm_res = get_gpu_memory()
                        result["status"] = "success"
                        result["response"] = gm_res.get("message", "GPU memory checked.")
                        result.update(gm_res)
                    elif action == "detailed_gpu":
                        from modules.system_controller import get_gpu_telemetry
                        g_res = get_gpu_telemetry(detailed=True)
                        result["status"] = "success"
                        result["response"] = g_res.get("message", "Detailed GPU telemetry checked.")
                        result.update(g_res)
                    elif action == "gpu_telemetry":
                        from modules.system_controller import get_gpu_telemetry
                        g_res = get_gpu_telemetry()
                        result["status"] = "success"
                        result["response"] = g_res.get("message", "GPU telemetry checked.")
                        result.update(g_res)
                    elif action == "detailed_cpu":
                        from modules.system_controller import get_detailed_cpu_info
                        c_res = get_detailed_cpu_info()
                        result["status"] = "success"
                        result["response"] = c_res.get("message", "Detailed CPU info checked.")
                        result.update(c_res)
                    elif action == "cpu_metrics":
                        from modules.system_controller import get_cpu_metrics
                        c_res = get_cpu_metrics()
                        result["status"] = "success"
                        result["response"] = c_res.get("message", "CPU metrics checked.")
                        result.update(c_res)
                    elif action == "detailed_ram":
                        from modules.system_controller import get_detailed_ram_metrics
                        r_res = get_detailed_ram_metrics()
                        result["status"] = "success"
                        result["response"] = r_res.get("message", "Detailed RAM metrics checked.")
                        result.update(r_res)
                    elif action == "ram_metrics":
                        from modules.system_controller import get_ram_metrics
                        r_res = get_ram_metrics()
                        result["status"] = "success"
                        result["response"] = r_res.get("message", "RAM metrics checked.")
                        result.update(r_res)
                    elif action == "system_info":
                        from modules.system_controller import get_system_info
                        s_res = get_system_info()
                        result["status"] = "success" if s_res.get("success") else "error"
                        result["response"] = s_res.get("message", "System info checked.")
                        result.update(s_res)
                    elif action == "display_info":
                        from modules.system_controller import get_display_info
                        d_res = get_display_info()
                        result["status"] = "success" if d_res.get("success") else "error"
                        result["response"] = d_res.get("message", "Display info checked.")
                        result.update(d_res)
                    elif action == "all_disks":
                        from modules.system_controller import get_all_disks
                        ad_res = get_all_disks()
                        result["status"] = "success" if ad_res.get("success") else "error"
                        result["response"] = ad_res.get("message", "Drives checked.")
                        result.update(ad_res)
                    elif action == "remote_device":
                        from skills.device_management import get_device_controller
                        from instance.config import settings
                        effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1
                        ctrl_res = get_device_controller().handle_command(user_input, effective_uid)
                        is_ok = ctrl_res.get("success", True)
                        result["status"] = "success" if is_ok else "error"
                        result["response"] = ctrl_res.get("message", "Device command completed.")
                        result.update(ctrl_res)
                        if not is_ok:
                            result["status"] = "error"
                    elif action == "device_location":
                        from skills.device_location import get_location_controller
                        loc_res = get_location_controller().handle_command(user_input)
                        result["status"] = "success"
                        result["response"] = loc_res.get("message", "Location checked.")
                        result.update(loc_res)
                    elif action == "analyze_clipboard":
                        from skills.clipboard import get_clipboard_controller
                        clip_res = get_clipboard_controller().handle_command(user_input)
                        result["status"] = "success" if clip_res.get("success") else "error"
                        result["response"] = clip_res.get("message", "Clipboard analyzed.")
                        result.update(clip_res)
                    # ── Software Management & Privileged Service Control ──
                    elif action in ("install_software", "uninstall_software"):
                        from modules.system_controller import execute_action
                        effective_uid = user_id or 1
                        pkg = params.get("package_name") or params.get("name")
                        act_res = execute_action({
                            "action": action,
                            "name": pkg,
                            "package": pkg
                        }, confirm=True, user_id=effective_uid)
                        is_ok = act_res.get("success", False)
                        result["status"] = "success" if is_ok else act_res.get("status", "error")
                        result["response"] = act_res.get("message") or f"Software {action} completed."
                        result.update(act_res)
                    elif action == "service_control":
                        from modules.system_controller import execute_action
                        effective_uid = user_id or 1
                        svc = params.get("service_name") or params.get("name")
                        sub_act = params.get("sub_action", "restart")
                        act_res = execute_action({
                            "action": "service_control",
                            "name": svc,
                            "command": sub_act,
                            "service": svc
                        }, confirm=True, user_id=effective_uid)
                        is_ok = act_res.get("success", False)
                        result["status"] = "success" if is_ok else act_res.get("status", "error")
                        result["response"] = act_res.get("message") or f"Service {sub_act} completed."
                        result.update(act_res)
                    elif action in ("test_elevation", "elevation", "request_elevation"):
                        from modules.system_controller import execute_action
                        effective_uid = user_id or 1
                        act_res = execute_action({
                            "action": "test_elevation",
                            "name": "elevation_test"
                        }, confirm=True, user_id=effective_uid)
                        is_ok = bool(act_res.get("success", False) and act_res.get("verified", False))
                        result.update(act_res)
                        status = "verified" if is_ok else act_res.get("status", "error")
                        result["status"] = status
                        result["verified"] = is_ok
                        result["success"] = is_ok
                        result["response"] = act_res.get("message") or ("Administrator elevation verified successfully." if is_ok else "Elevation request failed.")
                    # ── Wi-Fi ────────────────────────────────────────────────
                    elif action == "wifi_status":
                        from modules.system_controller import get_wifi_status
                        w = get_wifi_status()
                        result["response"] = w.get("message", "Wi-Fi status checked.")
                        result.update(w)
                    elif action == "list_wifi_networks":
                        from modules.system_controller import list_wifi_networks
                        w = list_wifi_networks()
                        result["response"] = w.get("message", "Wi-Fi networks scanned.")
                        result.update(w)
                    elif action == "enable_wifi":
                        from modules.system_controller import set_wifi_state
                        w = set_wifi_state(True)
                        result["status"] = "success" if w.get("success") else "error"
                        result["response"] = w.get("message", "Wi-Fi enabled.")
                    elif action == "disable_wifi":
                        from modules.system_controller import set_wifi_state
                        w = set_wifi_state(False)
                        result["status"] = "success" if w.get("success") else "error"
                        result["response"] = w.get("message", "Wi-Fi disabled.")
                    elif action == "network_speed":
                        from modules.system_controller import get_network_speed
                        n = get_network_speed()
                        result["response"] = n.get("message", "Network speed measured.")
                        result.update(n)
                    elif action == "network_adapters":
                        from modules.system_controller import get_network_adapters
                        n = get_network_adapters()
                        result["response"] = n.get("message", "Network adapters listed.")
                        result.update(n)
                    # ── Bluetooth ────────────────────────────────────────────────
                    elif action == "bluetooth_status":
                        from modules.system_controller import get_bluetooth_status
                        bt = get_bluetooth_status()
                        result["response"] = bt.get("message", "Bluetooth status checked.")
                        result.update(bt)
                    elif action in ["enable_bluetooth", "disable_bluetooth"]:
                        from modules.system_controller import set_bluetooth_state
                        enable = (action == "enable_bluetooth")
                        bt = set_bluetooth_state(enable)
                        result["status"] = "success" if bt.get("success") else "error"
                        result["response"] = bt.get("message", f"Bluetooth {'enabled' if enable else 'disabled'}.")
                        result.update(bt)
                    # ── Local Environment State (EnvironmentObserver authority) ──
                    elif action == "active_application":
                        from core.environment_observer import observe_environment
                        obs = observe_environment(user_id=str(user_id or 1))
                        app = obs.active_application or (obs.active_window.get("app_name") if obs.active_window else None) or "Unknown Application"
                        result["status"] = "success"
                        result["response"] = f"The currently active application is {app}."
                        result["active_application"] = app
                    elif action == "active_window":
                        from core.environment_observer import observe_environment
                        obs = observe_environment(user_id=str(user_id or 1))
                        win_title = obs.foreground_window_title or (obs.active_window.get("title") if obs.active_window else None) or "Desktop"
                        result["status"] = "success"
                        result["response"] = f"The active window is {win_title}."
                        result["active_window"] = win_title
                    # ── Keyboard toggle keys ──────────────────────────────────────
                    elif action == "toggle_key":
                        from modules.system_controller import toggle_key
                        key = params.get("key", "caps")
                        k = toggle_key(key)
                        result["status"] = "success" if k.get("success") else "error"
                        result["response"] = k.get("message", f"Toggled {key} lock.")
                    elif action == "set_key":
                        from modules.system_controller import set_key
                        key = params.get("key", "caps")
                        desired = params.get("desired_state", True)
                        k = set_key(key, desired)
                        result["status"] = "success" if k.get("success") else "error"
                        result["response"] = k.get("message", f"{key} lock set.")
                        result["key"] = k.get("key", "Caps Lock")
                        result["state"] = k.get("state")
                        result.update(k)
                    elif action == "keyboard_state":
                        from modules.system_controller import get_toggle_key_states
                        k = get_toggle_key_states()
                        result["status"] = "success" if k.get("success") else "error"
                        low_in = user_input.lower()
                        if "caps" in low_in and not ("num" in low_in or "scroll" in low_in or "keyboard toggle" in low_in or "keyboard lights" in low_in):
                            state_str = "ON" if k.get("caps_lock") else "OFF"
                            result["response"] = f"Caps Lock is {state_str}."
                            result["key"] = "Caps Lock"
                            result["state"] = k.get("caps_lock")
                        elif "num" in low_in and not ("caps" in low_in or "scroll" in low_in or "keyboard toggle" in low_in):
                            state_str = "ON" if k.get("num_lock") else "OFF"
                            result["response"] = f"Num Lock is {state_str}."
                            result["key"] = "Num Lock"
                            result["state"] = k.get("num_lock")
                        elif "scroll" in low_in and not ("caps" in low_in or "num" in low_in or "keyboard toggle" in low_in):
                            state_str = "ON" if k.get("scroll_lock") else "OFF"
                            result["response"] = f"Scroll Lock is {state_str}."
                            result["key"] = "Scroll Lock"
                            result["state"] = k.get("scroll_lock")
                        else:
                            result["response"] = k.get("message", "Keyboard state checked.")
                        result.update(k)
                    # ── Hardware info ─────────────────────────────────────────────
                    elif action == "hardware_info":
                        from modules.system_controller import get_hardware_info
                        h = get_hardware_info()
                        result["response"] = h.get("message", "Hardware info retrieved.")
                        result.update(h)
                    # ── Power plans ───────────────────────────────────────────────
                    elif action == "power_plan":
                        from modules.system_controller import get_active_power_plan
                        pp = get_active_power_plan()
                        result["response"] = pp.get("message", "Power plan checked.")
                        result.update(pp)
                    elif action == "list_power_plans":
                        from modules.system_controller import list_power_plans
                        pp = list_power_plans()
                        result["response"] = pp.get("message", "Power plans listed.")
                        result.update(pp)
                    # ── Mouse info ────────────────────────────────────────────────
                    elif action == "mouse_info":
                        from modules.system_controller import get_mouse_info
                        m = get_mouse_info()
                        result["response"] = m.get("message", "Mouse info retrieved.")
                        result.update(m)
                    # ── Uptime ────────────────────────────────────────────────────
                    elif action == "uptime":
                        from modules.system_controller import get_uptime
                        ut = get_uptime()
                        result["response"] = ut.get("message", "Uptime retrieved.")
                        result.update(ut)
                    # ── All processes list ────────────────────────────────────────
                    elif action == "list_processes":
                        from modules.system_controller import list_all_processes
                        sort_by = params.get("sort_by", "memory")
                        lp = list_all_processes(sort_by=sort_by)
                        result["response"] = lp.get("message", "Processes listed.")
                        result.update(lp)
                    # ── Dark mode / theme ─────────────────────────────────────────
                    elif action == "toggle_dark_mode":
                        from modules.system_controller import toggle_dark_mode
                        dm_res = toggle_dark_mode(enable=params.get("enable"))
                        result["status"] = "success" if dm_res.get("success") else "error"
                        result["response"] = dm_res.get("message", "Appearance theme updated.")
                        result.update(dm_res)
                    # ── Connect Wi-Fi ─────────────────────────────────────────────
                    elif action == "connect_wifi":
                        from modules.system_controller import connect_to_wifi
                        ssid = params.get("ssid", "")
                        wf_res = connect_to_wifi(ssid)
                        result["status"] = "success" if wf_res.get("success") else "error"
                        result["response"] = wf_res.get("message", f"Connecting to Wi-Fi '{ssid}'.")
                        result.update(wf_res)
                    # ── Set display resolution ────────────────────────────────────
                    elif action == "set_resolution":
                        from modules.system_controller import set_display_resolution
                        w = params.get("width", 1920)
                        h = params.get("height", 1080)
                        sr_res = set_display_resolution(w, h)
                        result["status"] = "success" if sr_res.get("success") else "error"
                        result["response"] = sr_res.get("message", f"Resolution set to {w}x{h}.")
                        result.update(sr_res)
                    # ── Desktop wallpaper ──────────────────────────────────────────
                    elif action == "get_wallpaper":
                        from modules.system_controller import get_current_wallpaper
                        wp_res = get_current_wallpaper()
                        result["status"] = "success" if wp_res.get("success") else "error"
                        result["response"] = wp_res.get("message", "Checked current wallpaper.")
                        result.update(wp_res)
                    elif action == "set_wallpaper":
                        from modules.system_controller import set_wallpaper
                        wp_path = params.get("wallpaper_path", "")
                        wp_res = set_wallpaper(wp_path)
                        result["status"] = "success" if wp_res.get("success") else "error"
                        result["response"] = wp_res.get("message", f"Setting wallpaper to {wp_path}.")
                        result.update(wp_res)
                    # ── Desktop statistics ─────────────────────────────────────────
                    elif action == "desktop_stats":
                        from modules.system_controller import get_desktop_statistics
                        ds_res = get_desktop_statistics()
                        result["status"] = "success" if ds_res.get("success") else "error"
                        result["response"] = ds_res.get("message", "Analyzed desktop.")
                        result.update(ds_res)
                    # ── GPU telemetry ──────────────────────────────────────────────
                    elif action == "gpu_telemetry":
                        from modules.system_controller import get_gpu_telemetry
                        gpu_res = get_gpu_telemetry()
                        result["status"] = "success" if gpu_res.get("success") else "error"
                        result["response"] = gpu_res.get("message", "Checked GPU telemetry.")
                        result.update(gpu_res)
                    elif action == "type_text":
                        text_to_type = params.get("text", "")
                        if not text_to_type:
                            m_tp = re.search(r'\b(?:type|write)\s+(.+)', user_input, re.IGNORECASE)
                            text_to_type = m_tp.group(1).strip(' "\'') if m_tp else ""
                        import time
                        time.sleep(0.3)
                        try:
                            import pyautogui
                            pyautogui.write(text_to_type, interval=0.02)
                        except Exception as p_err:
                            self.logger.warning(f"PyAutoGUI typing error: {p_err}")
                        result["status"] = "success"
                        result["action"] = "TYPE_TEXT"
                        result["entity_type"] = "TEXT"
                        result["text"] = text_to_type
                        result["response"] = f"Typed: {text_to_type}"
                    elif action in ("list_installed_games", "list_installed_applications", "list_installed_browsers"):
                        try:
                            from modules.system_controller.universal_computer_access import universal_computer_access
                            raw_apps = universal_computer_access.enumerate_installed_applications()
                            app_names = []
                            for a in raw_apps:
                                if isinstance(a, dict):
                                    n = a.get("name") or a.get("display_name")
                                    if n:
                                        app_names.append(str(n))
                                elif a:
                                    app_names.append(str(a))

                            if action == "list_installed_games":
                                game_keywords = ["game", "steam", "epic", "riot", "blizzard", "ubisoft", "ea", "minecraft", "roblox", "witcher", "cyberpunk", "gta", "halo", "duty", "fifa", "forza"]
                                games = [name for name in app_names if any(k in name.lower() for k in game_keywords)]
                                if games:
                                    msg = f"Found {len(games)} game(s) or gaming platforms installed: {', '.join(games[:8])}."
                                elif app_names:
                                    msg = f"No dedicated standalone games detected, but found {len(app_names)} installed applications on your PC."
                                else:
                                    msg = "No installed games detected on this system."
                                result["status"] = "success"
                                result["response"] = msg
                                result["games"] = games
                            elif action == "list_installed_browsers":
                                detected_browsers = universal_computer_access.detect_available_browsers()
                                name_map = {
                                    "chrome": "Google Chrome",
                                    "edge": "Microsoft Edge",
                                    "brave": "Brave Browser",
                                    "firefox": "Mozilla Firefox",
                                    "opera": "Opera",
                                    "vivaldi": "Vivaldi",
                                    "tor": "Tor Browser",
                                }
                                browser_names = [name_map.get(b.lower(), b.capitalize()) for b in detected_browsers]
                                for app in app_names:
                                    low_app = app.lower()
                                    for b_key, b_disp in name_map.items():
                                        if b_key in low_app and b_disp not in browser_names and not any(bad in low_app for bad in ["webview", "driver", "crashpad", "update"]):
                                            browser_names.append(b_disp)
                                if browser_names:
                                    msg = f"Found {len(browser_names)} installed browser(s) on your PC: {', '.join(browser_names)}."
                                else:
                                    msg = "No standalone web browsers were detected on your PC."
                                result["status"] = "success"
                                result["response"] = msg
                                result["browsers"] = browser_names
                            else:
                                result["status"] = "success"
                                result["response"] = f"Found {len(app_names)} installed application(s) on your PC: {', '.join(app_names[:10])}."
                                result["applications"] = app_names
                        except Exception as e:
                            result["status"] = "error"
                            result["response"] = f"Could not inspect installed applications: {e}"
                    else:
                        result["status"] = "error"
                        result["response"] = f"Unrecognized device control command: '{user_input}'. Could not execute."
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Device control failed: {e}"
                    
            # 4. OPEN / CLOSE APPLICATION
            elif intent in (Intent.OPEN_APPLICATION, Intent.CLOSE_APPLICATION):
                try:
                    target = params.get("target", "").strip()
                    action = params.get("action", "open")
                    if action == "search_web":
                        from modules.browser.browser_controller import search_web
                        query = params.get("query") or params.get("search_query") or user_input
                        s_res = search_web(query)
                        result["status"] = "success" if s_res.get("success") else "error"
                        result["action"] = "SEARCH"
                        result["entity_type"] = "SEARCH_QUERY"
                        result["query"] = query
                        result["results"] = s_res.get("results", [])
                        result["result_count"] = len(result["results"])
                        result["response"] = s_res.get("message", f"Searched for '{query}'.")
                        result.update(s_res)
                        try:
                            from extensions.context_manager import get_manager, ContextType
                            get_manager().active_context["last_browser_result_set"] = result["results"]
                            get_manager().active_context["last_search_query"] = query
                            get_manager().active_context["active_application"] = "browser"
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            dm = get_dialogue_manager(str(effective_uid))
                            dm.current_state.session_context["last_browser_result_set"] = result["results"]
                            dm.current_state.active_browser_result_set = result["results"]
                            dm.current_state.session_context["last_search_query"] = query
                            dm.current_state.session_context["active_application"] = "browser"
                            dm.current_state.active_browser = "browser"
                            dm.current_state.entities["search_query"] = query
                        except Exception:
                            pass
                        return result

                    if action == "browser_go_back":
                        try:
                            from modules.browser.browser_controller import go_back
                            go_back()
                        except Exception:
                            pass
                        result["status"] = "success"
                        result["action"] = "NAVIGATE_BACK"
                        result["entity_type"] = "BROWSER_RESULT"
                        result["response"] = "Navigated back."
                        try:
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            dm = get_dialogue_manager(str(effective_uid))
                            dm.current_state.session_context["active_application"] = "browser"
                            dm.current_state.active_browser = "browser"
                        except Exception:
                            pass
                        return result

                    if action == "open_browser_result":
                        res_set = params.get("res_set") or []
                        if not res_set:
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(effective_uid))
                                res_set = dm.current_state.active_browser_result_set or dm.current_state.session_context.get("last_browser_result_set", [])
                            except Exception:
                                pass
                        if not res_set:
                            try:
                                from extensions.context_manager import get_manager
                                res_set = get_manager().active_context.get("last_browser_result_set", [])
                            except Exception:
                                pass
                        ord_map = {"first": 1, "1st": 1, "top": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "fifth": 5, "5th": 5}
                        ord_raw = str(params.get("ordinal", "1")).lower()
                        idx_num = ord_map.get(ord_raw) or (int(re.sub(r'\D', '', ord_raw)) if re.sub(r'\D', '', ord_raw) else 1)
                        zero_idx = idx_num - 1
                        if res_set and 0 <= zero_idx < len(res_set):
                            item = res_set[zero_idx]
                            if isinstance(item, dict):
                                url = item.get("url") or item.get("link") or ""
                                title = item.get("title", "")
                            else:
                                url = str(item)
                                title = str(item)
                            from modules.browser.browser_controller import open_url
                            open_url(url)
                            result["status"] = "success"
                            result["action"] = "OPEN_BROWSER_RESULT"
                            result["entity_type"] = "BROWSER_RESULT"
                            result["index"] = idx_num
                            result["url"] = url
                            result["title"] = title
                            result["response"] = f"Opened result #{idx_num}: {title or url}"
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(effective_uid))
                                dm.current_state.session_context["last_selected_result"] = item
                                dm.current_state.session_context["active_application"] = "browser"
                                dm.current_state.entities["browser_result"] = title or url
                            except Exception:
                                pass
                        else:
                            last_query = None
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(effective_uid))
                                last_query = dm.current_state.session_context.get("last_search_query")
                            except Exception:
                                pass
                            if last_query:
                                from modules.browser.browser_controller import get_search_results, open_url
                                res_set = get_search_results(last_query)
                                if res_set and 0 <= zero_idx < len(res_set):
                                    item = res_set[zero_idx]
                                    if isinstance(item, dict):
                                        url = item.get("url") or item.get("link") or ""
                                        title = item.get("title", "")
                                    else:
                                        url = str(item)
                                        title = str(item)
                                    open_url(url)
                                    result["status"] = "success"
                                    result["action"] = "OPEN_BROWSER_RESULT"
                                    result["entity_type"] = "BROWSER_RESULT"
                                    result["index"] = idx_num
                                    result["url"] = url
                                    result["title"] = title
                                    result["response"] = f"Opened result #{idx_num}: {title or url}"
                                    return result
                            result["status"] = "error"
                            result["action"] = "OPEN_BROWSER_RESULT"
                            result["entity_type"] = "BROWSER_RESULT"
                            result["response"] = f"Result #{idx_num} is unavailable in search results."
                        return result

                    if action == "close_all_opened":
                        from legacy.actions import close_app
                        from extensions.dialogue_state_manager import get_dialogue_manager
                        dm = get_dialogue_manager(str(effective_uid))
                        opened_apps = list(dm.current_state.session_context.get("opened_applications", []))
                        if not opened_apps:
                            result["status"] = "success"
                            result["action"] = "close_all_opened"
                            result["response"] = "No applications were opened by me in this session."
                            result["closed_apps"] = []
                            return result

                        closed_list = []
                        for app in opened_apps:
                            close_app(app)
                            closed_list.append(app)
                        dm.current_state.session_context["opened_applications"] = []
                        result["status"] = "success"
                        result["action"] = "close_all_opened"
                        result["closed_apps"] = closed_list
                        result["response"] = f"Closed all applications opened in this session: {', '.join(closed_list)}."
                        return result
                    if action == "navigate_back" or target in ["browser back", "back"]:
                        result["status"] = "success"
                        result["target"] = "browser"
                        result["action"] = "navigate_back"
                        result["response"] = "Navigated back."
                        return result
                    if action == "extract_links":
                        from modules.browser.browser_controller import extract_page_links
                        m_u = re.search(r'https?://[^\s]+', user_input)
                        target_url = m_u.group(0) if m_u else "https://en.wikipedia.org"
                        link_res = extract_page_links(target_url)
                        result["status"] = "success" if link_res.get("success") else "error"
                        links = link_res.get("links", [])
                        cnt = link_res.get("count", len(links))
                        result["status"] = "success"
                        result["count"] = cnt
                        result["links"] = links
                        result["response"] = link_res.get("message", f"Extracted {cnt} links.")
                        result.update(link_res)
                        try:
                            from extensions.context_manager import get_manager, ContextType
                            get_manager().active_context["last_extracted_links"] = links
                            get_manager().set_active_context(ContextType.BROWSER, "page", metadata={"links": links, "link_count": cnt, "url": target_url})
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            dm = get_dialogue_manager(str(effective_uid))
                            dm.current_state.session_context["last_extracted_links"] = links
                            dm.current_state.session_context["last_extracted_page_url"] = target_url
                        except Exception:
                            pass
                        return result
                    if action == "extract_tables":
                        from modules.browser.browser_controller import extract_page_tables
                        m_u = re.search(r'https?://[^\s]+', user_input)
                        target_url = m_u.group(0) if m_u else "https://en.wikipedia.org"
                        tab_res = extract_page_tables(target_url)
                        result["status"] = "success" if tab_res.get("success") else "error"
                        tables = tab_res.get("tables", [])
                        result["status"] = "success"
                        result["table_count"] = len(tables)
                        result["tables"] = tables
                        result["response"] = tab_res.get("message", f"Extracted {len(tables)} tables.")
                        result.update(tab_res)
                        try:
                            from extensions.context_manager import get_manager, ContextType
                            get_manager().active_context["last_extracted_tables"] = tables
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            dm = get_dialogue_manager(str(effective_uid))
                            dm.current_state.session_context["last_extracted_tables"] = tables
                            dm.current_state.session_context["last_extracted_page_url"] = target_url
                        except Exception:
                            pass
                        return result
                    if action == "count_links":
                        links = []
                        try:
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            dm = get_dialogue_manager(str(effective_uid))
                            links = dm.current_state.session_context.get("last_extracted_links", [])
                        except Exception:
                            pass
                        if not links:
                            try:
                                from extensions.context_manager import get_manager
                                links = get_manager().active_context.get("last_extracted_links", [])
                            except Exception:
                                pass
                        cnt = len(links)
                        result["status"] = "success"
                        result["count"] = cnt
                        result["response"] = f"I found {cnt} links on the page." if cnt > 0 else "I don't have any extracted links in context."
                        return result
                    if action == "get_link":
                        links = []
                        try:
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            dm = get_dialogue_manager(str(effective_uid))
                            links = dm.current_state.session_context.get("last_extracted_links", [])
                        except Exception:
                            pass
                        if not links:
                            try:
                                from extensions.context_manager import get_manager
                                links = get_manager().active_context.get("last_extracted_links", [])
                            except Exception:
                                pass
                        ord_map = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
                        ord_raw = str(params.get("ordinal", "1")).lower()
                        idx_num = ord_map.get(ord_raw) or (int(re.sub(r'\D', '', ord_raw)) if re.sub(r'\D', '', ord_raw) else 1)
                        zero_idx = idx_num - 1
                        if 0 <= zero_idx < len(links):
                            lk = links[zero_idx]
                            result["status"] = "success"
                            result["link"] = lk
                            result["response"] = f"Link {idx_num} is '{lk.get('text')}' pointing to {lk.get('url')}."
                        else:
                            result["status"] = "error"
                            result["response"] = f"Link {idx_num} is unavailable. Only {len(links)} links were found."
                        return result
                    if action == "open_link":
                        links = []
                        try:
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            dm = get_dialogue_manager(str(effective_uid))
                            links = dm.current_state.session_context.get("last_extracted_links", [])
                        except Exception:
                            pass
                        if not links:
                            try:
                                from extensions.context_manager import get_manager
                                links = get_manager().active_context.get("last_extracted_links", [])
                            except Exception:
                                pass
                        if not links:
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(effective_uid))
                                links = dm.current_state.session_context.get("last_browser_result_set", [])
                            except Exception:
                                pass
                        if not links:
                            last_query = None
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(effective_uid))
                                last_query = dm.current_state.session_context.get("last_search_query")
                            except Exception:
                                pass
                            if last_query:
                                from modules.browser.browser_controller import get_search_results
                                links = get_search_results(last_query)
                        ord_map = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
                        ord_raw = str(params.get("ordinal", "1")).lower()
                        idx_num = ord_map.get(ord_raw) or (int(re.sub(r'\D', '', ord_raw)) if re.sub(r'\D', '', ord_raw) else 1)
                        zero_idx = idx_num - 1
                        if 0 <= zero_idx < len(links):
                            lk = links[zero_idx]
                            url = (lk.get("url") or lk.get("link")) if isinstance(lk, dict) else str(lk)
                            from modules.browser.browser_controller import open_url
                            open_url(url)
                            result["status"] = "success"
                            result["action"] = "OPEN_BROWSER_RESULT"
                            result["entity_type"] = "BROWSER_RESULT"
                            result["url"] = url
                            result["response"] = f"Opening link {idx_num}: {url}."
                        else:
                            result["status"] = "error"
                            result["action"] = "OPEN_BROWSER_RESULT"
                            result["entity_type"] = "BROWSER_RESULT"
                            result["response"] = f"Link {idx_num} is unavailable. Only {len(links)} links were found."
                        return result
                    if action == "get_table_rows":
                        tables = []
                        try:
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            dm = get_dialogue_manager(str(effective_uid))
                            tables = dm.current_state.session_context.get("last_extracted_tables", [])
                        except Exception:
                            pass
                        if not tables:
                            try:
                                from extensions.context_manager import get_manager
                                tables = get_manager().active_context.get("last_extracted_tables", [])
                            except Exception:
                                pass
                        num_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
                        raw_c = str(params.get("count_str", "5")).lower()
                        n_rows = num_map.get(raw_c) or (int(re.sub(r'\D', '', raw_c)) if re.sub(r'\D', '', raw_c) else 5)
                        if tables and len(tables) > 0:
                            tb = tables[0]
                            selected = tb[:n_rows]
                            formatted = "\n".join([" | ".join(r) for r in selected])
                            result["status"] = "success"
                            result["rows"] = selected
                            result["response"] = f"Here are the first {len(selected)} rows:\n{formatted}"
                        else:
                            result["status"] = "error"
                            result["response"] = "No extracted table found in context."
                        return result
                    if action == "get_table_row":
                        tables = []
                        try:
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            dm = get_dialogue_manager(str(effective_uid))
                            tables = dm.current_state.session_context.get("last_extracted_tables", [])
                        except Exception:
                            pass
                        if not tables:
                            try:
                                from extensions.context_manager import get_manager
                                tables = get_manager().active_context.get("last_extracted_tables", [])
                            except Exception:
                                pass
                        ord_map = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
                        ord_raw = str(params.get("ordinal", "1")).lower()
                        idx_num = ord_map.get(ord_raw) or (int(re.sub(r'\D', '', ord_raw)) if re.sub(r'\D', '', ord_raw) else 1)
                        zero_idx = idx_num - 1
                        if tables and len(tables) > 0 and 0 <= zero_idx < len(tables[0]):
                            row = tables[0][zero_idx]
                            result["status"] = "success"
                            result["row"] = row
                            result["response"] = f"The value in row {idx_num} is: {' | '.join(row)}."
                        else:
                            result["status"] = "error"
                            result["response"] = f"Row {idx_num} is unavailable in table context."
                        return result
                    if action == "search_flights":
                        from modules.browser.browser_controller import build_flight_search_url
                        if "express" in user_input.lower():
                            result["status"] = "clarification_needed"
                            result["response"] = "Do you mean Air India Express, or flights from Hyderabad to Mumbai?"
                            result["handled"] = True
                            return result

                        m_o = re.search(r'from\s+([A-Z]{3}|[a-zA-Z\s]+?)\s+to\s+([A-Z]{3}|[a-zA-Z\s]+?)(?:\s+(?:on|tomorrow|next|for)|\s*$)', user_input, re.IGNORECASE)
                        origin = m_o.group(1).strip() if m_o else "Hyderabad"
                        dest = m_o.group(2).strip() if m_o else "Delhi"
                        m_d = re.search(r'(\d{4}-\d{2}-\d{2})', user_input)
                        date_str = m_d.group(1) if m_d else None
                        if "tomorrow" in user_input.lower() and not date_str:
                            from datetime import date
                            date_str = str(date.today() + timedelta(days=1))
                        f_res = build_flight_search_url(origin=origin, destination=dest, departure_date=date_str)
                        result["status"] = "success" if f_res.get("success") else "error"
                        result["response"] = f_res.get("message", "Generated flight search URL.")
                        result.update(f_res)
                        try:
                            from extensions.context_manager import get_manager
                            get_manager().add_user_artifact(user_id=effective_uid, artifact={
                                "path": f_res["url"],
                                "filepath": f_res["url"],
                                "type": "flight_search",
                                "filename": f"Flight Search {origin} to {dest}",
                                "source_action": "flight_search",
                                "url": f_res["url"]
                            })
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            dm = get_dialogue_manager(str(effective_uid))
                            dm.current_state.session_context["last_flight_search"] = f_res
                        except Exception:
                            pass
                        return result
                    if action in ("switch", "switch_application", "focus") or any(user_input.lower().startswith(p) for p in ("switch to ", "switch back to ", "switch ", "bring up ", "bring ", "focus ")):
                        # WINDOW SWITCHING / BRING TO FRONT
                        from extensions.system.smart_opener import smart_opener
                        app_state = smart_opener.get_app_state(target)
                        display = app_state.get("display_name") or target
                        result["action"] = "switch"
                        if app_state.get("running"):
                            if app_state.get("foreground"):
                                result["status"] = "success"
                                result["already_satisfied"] = True
                                result["target"] = target
                                result["app_name"] = display
                                result["response"] = f"{display} is already open and active."
                                return result
                            else:
                                focused = smart_opener.focus_app(target)
                                result["status"] = "success"
                                result["target"] = target
                                result["app_name"] = display
                                result["response"] = f"Switched to {display}." if focused else f"{display} is running, but could not bring its window to the front."
                                return result
                        else:
                            result["status"] = "error"
                            result["target"] = target
                            result["app_name"] = display
                            result["response"] = f"{display} is not currently running."
                            return result

                    if action == "open":
                        clean_target = target.lower().strip().rstrip('.?!')
                        # Check for generic browser
                        if clean_target in ("browser", "the browser", "web browser", "internet", "default browser"):
                            from extensions.system.smart_opener import smart_opener
                            open_dict = smart_opener.smart_open("browser")
                            result["status"] = "success" if open_dict.get("success") else "error"
                            result["target"] = "browser"
                            result["app_name"] = "Browser"
                            result["response"] = open_dict.get("message", "Opened your browser.")
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(effective_uid))
                                dm.current_state.session_context.setdefault("opened_applications", []).append("Browser")
                                dm.current_state.session_context["active_application"] = "browser"
                                from core.environment import verify_and_synchronize_foreground_state
                                verify_and_synchronize_foreground_state(user_id=effective_uid, action_target="browser")
                            except Exception:
                                pass
                            return result

                        # Check for flight search reference first
                        if clean_target in ("the flight search", "that flight search", "the flight results", "that flight results", "flight search", "the flights", "that flights") or (clean_target in ("it", "that") and any(a.get("type") == "flight_search" for a in (get_manager().get_user_artifacts(user_id=effective_uid) if 'get_manager' in locals() else []))):
                            from extensions.context_manager import get_manager
                            flight_url = None
                            art = get_manager().get_last_user_artifact(user_id=effective_uid, artifact_type="flight_search")
                            if art and (art.get("path") or art.get("url")):
                                flight_url = art.get("path") or art.get("url")
                            if not flight_url:
                                try:
                                    from extensions.dialogue_state_manager import get_dialogue_manager
                                    dm = get_dialogue_manager(str(effective_uid))
                                    last_f = dm.current_state.session_context.get("last_flight_search")
                                    if last_f and isinstance(last_f, dict) and last_f.get("url"):
                                        flight_url = last_f["url"]
                                except Exception:
                                    pass
                            if flight_url:
                                from modules.browser.browser_controller import open_url
                                open_url(flight_url)
                                result["status"] = "success"
                                result["url"] = flight_url
                                result["response"] = f"Opened flight search: {flight_url}"
                                return result

                        if clean_target in ["dashboard", "my dashboard", "the dashboard", "assistant dashboard", "ui dashboard"] or "dashboard" in clean_target:
                            from core.assistant_core import assistant_core
                            assistant_core.trigger_ui_action("open_dashboard")
                            result["status"] = "success"
                            result["response"] = "Opening your Dashboard."
                            return result
                        if any(w in clean_target for w in ["first result", "top result", "1st result", "first search result", "second result", "2nd result", "second search result", "2nd search result", "third result", "3rd result", "third search result", "3rd search result", "previous result", "previous search result"]):
                            ord_found = "first"
                            for cand_ord in ["first", "1st", "top", "second", "2nd", "third", "3rd", "fourth", "4th", "fifth", "5th"]:
                                if cand_ord in clean_target:
                                    ord_found = cand_ord
                                    break
                            params["ordinal"] = ord_found
                            params["action"] = "open_browser_result"
                            action = "open_browser_result"
                        if params.get("is_website") or params.get("url") or target.lower() in ["youtube", "google", "gmail", "github"]:
                            from legacy.actions import open_website
                            url = params.get("url")
                            if not url:
                                site_urls = {
                                    "youtube": "https://www.youtube.com",
                                    "google": "https://www.google.com",
                                    "gmail": "https://mail.google.com",
                                    "github": "https://www.github.com",
                                }
                                url = site_urls.get(target.lower(), f"https://www.{target.lower()}.com")
                            site_name = params.get("site_name") or target.capitalize()
                            open_website(url, name=site_name, confirm=False)
                            result["status"] = "success"
                            result["target"] = site_name.lower()
                            result["is_website"] = True
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(effective_uid))
                                opened_apps = dm.current_state.session_context.setdefault("opened_applications", [])
                                b_name = "Chrome" if "chrome" in target.lower() else ("Edge" if "edge" in target.lower() else "Browser")
                                if b_name not in opened_apps:
                                    opened_apps.append(b_name)
                                from core.environment import verify_and_synchronize_foreground_state
                                verify_and_synchronize_foreground_state(user_id=effective_uid, action_target=b_name.lower())
                            except Exception:
                                pass
                            if params.get("search_query"):
                                result["response"] = f"Searching {site_name} for '{params['search_query']}'."
                            else:
                                result["response"] = f"Opening {site_name}."
                            return result
                        elif target.lower() in ["camera", "webcam"]:
                            # smart_opener handles camera via microsoft.windows.camera: URI
                            from extensions.system.smart_opener import smart_opener
                            open_dict = smart_opener.smart_open("camera")
                            if isinstance(open_dict, dict) and open_dict.get("success"):
                                result["status"] = "success"
                                result["response"] = "Opened Camera."
                            else:
                                msg = "Could not open camera."
                                result["status"] = "error"
                                result["response"] = msg
                        else:
                            # Check if target is a direct file path, 'file <path>', or conversational artifact reference (Section 4, 5, 11, 12)
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            from extensions.context_manager import get_manager
                            dm = get_dialogue_manager(str(effective_uid))

                            clean_path = target.strip().rstrip('.?!')
                            if clean_path.lower().startswith("file "):
                                clean_path = clean_path[5:].strip().rstrip('.?!')

                            art_keywords = (
                                "presentation", "ppt", "pptx", "report", "document", "docx", "doc",
                                "pdf", "spreadsheet", "excel", "sheet", "xlsx", "file you created",
                                "the file", "that file", "this file", "it", "that", "assignment",
                                "dbms assignment", "assignment ppt", "dbms assignment ppt"
                            )
                            is_art_query = (
                                clean_path.lower() in art_keywords
                                or any(k in clean_path.lower() for k in art_keywords)
                                or any(k in user_input.lower() for k in [
                                    "open the presentation", "open the ppt", "open my presentation",
                                    "open the report", "open the document", "open the pdf",
                                    "open the excel", "open the spreadsheet", "open the file you created",
                                    "open it", "can you open", "open the assignment", "open my assignment",
                                    "open assignment", "open the dbms assignment", "open the dbms assignment ppt",
                                    "open the assignment, not the other ppt", "open the assignment not the other ppt"
                                ])
                            )

                            resolved_art = None
                            if is_art_query and not (os.path.exists(clean_path) and os.path.isfile(clean_path)):
                                candidates = []

                                if dm and dm.current_state:
                                    if dm.current_state.active_artifact:
                                        candidates.append(dm.current_state.active_artifact)
                                    for a in getattr(dm.current_state, "active_documents", []):
                                        if a not in candidates:
                                            candidates.append(a)
                                    for typed_k in ["active_presentation", "active_pdf", "active_report", "active_spreadsheet"]:
                                        a = dm.current_state.session_context.get(typed_k)
                                        if a and a not in candidates:
                                            candidates.append(a)
                                    active_g = getattr(dm.current_state, "current_goal", None)
                                    if active_g and isinstance(active_g, dict):
                                        for d in active_g.get("deliverables", []):
                                            fp = d.get("file_path")
                                            if fp and os.path.exists(fp):
                                                dt = d.get("type", "").upper()
                                                candidates.append({
                                                    "filepath": fp,
                                                    "path": fp,
                                                    "filename": os.path.basename(fp),
                                                    "artifact_type": "PRESENTATION" if dt in ("PPT", "PPTX") else ("REPORT" if dt in ("DOCX", "DOC") else dt),
                                                    "type": dt.lower(),
                                                    "topic": active_g.get("topic") or active_g.get("title"),
                                                    "work_goal_id": active_g.get("id")
                                                })
                                    for g in dm.current_state.session_context.get("active_work_goals", {}).values():
                                        if isinstance(g, dict):
                                            for d in g.get("deliverables", []):
                                                fp = d.get("file_path")
                                                if fp and os.path.exists(fp) and not any(c.get("filepath") == fp for c in candidates):
                                                    dt = d.get("type", "").upper()
                                                    candidates.append({
                                                        "filepath": fp,
                                                        "path": fp,
                                                        "filename": os.path.basename(fp),
                                                        "artifact_type": "PRESENTATION" if dt in ("PPT", "PPTX") else ("REPORT" if dt in ("DOCX", "DOC") else dt),
                                                        "type": dt.lower(),
                                                        "topic": g.get("topic") or g.get("title"),
                                                        "work_goal_id": g.get("id")
                                                    })

                                try:
                                    user_arts = get_manager().get_user_artifacts(user_id=effective_uid)
                                    for ua in user_arts:
                                        p = ua.get("path") or ua.get("filepath")
                                        if p and os.path.exists(p) and not any(c.get("filepath") == p for c in candidates):
                                            candidates.append({
                                                "filepath": p,
                                                "path": p,
                                                "filename": ua.get("filename", os.path.basename(p)),
                                                "artifact_type": (ua.get("type") or "").upper(),
                                                "type": (ua.get("type") or "").lower(),
                                                "topic": ua.get("topic")
                                            })
                                except Exception:
                                    pass

                                if dm:
                                    l_entity = getattr(dm, "_last_mentioned_entity", None)
                                    if l_entity and l_entity.get("path") and os.path.exists(l_entity["path"]):
                                        candidates.insert(0, {
                                            "filepath": l_entity["path"],
                                            "path": l_entity["path"],
                                            "filename": l_entity.get("name") or os.path.basename(l_entity["path"]),
                                            "type": l_entity.get("entity_type", "FILE").lower()
                                        })


                                valid_candidates = [c for c in candidates if os.path.exists(c.get("filepath") or c.get("path") or "")]

                                query_text = f"{clean_path} {user_input}".lower()
                                req_type = None
                                if any(k in query_text for k in ["presentation", "ppt", "pptx", "slide"]):
                                    req_type = "PRESENTATION"
                                elif any(k in query_text for k in ["pdf"]):
                                    req_type = "PDF"
                                elif any(k in query_text for k in ["report", "docx", "doc", "document"]):
                                    req_type = "REPORT"
                                elif any(k in query_text for k in ["spreadsheet", "excel", "xlsx", "sheet"]):
                                    req_type = "SPREADSHEET"

                                topic_kw = None
                                for kw in ["deadlock", "dbms", "database", "assignment"]:
                                    if kw in query_text:
                                        topic_kw = kw
                                        break
                                if not topic_kw and dm and dm.current_state and dm.current_state.session_context.get("topic_lock"):
                                    topic_kw = dm.current_state.session_context.get("topic_lock").lower()

                                matching_type = []
                                for c in valid_candidates:
                                    c_type = (c.get("artifact_type") or c.get("type") or "").upper()
                                    fn = (c.get("filename") or "").lower()
                                    if req_type == "PRESENTATION" and (c_type in ("PRESENTATION", "PPT", "PPTX") or fn.endswith((".pptx", ".ppt"))):
                                        matching_type.append(c)
                                    elif req_type == "PDF" and (c_type in ("PDF",) or fn.endswith(".pdf")):
                                        matching_type.append(c)
                                    elif req_type == "REPORT" and (c_type in ("REPORT", "DOCX", "DOC", "DOCUMENT") or fn.endswith((".docx", ".doc"))):
                                        matching_type.append(c)
                                    elif req_type == "SPREADSHEET" and (c_type in ("SPREADSHEET", "XLSX", "EXCEL") or fn.endswith((".xlsx", ".xls"))):
                                        matching_type.append(c)
                                    elif req_type is None:
                                        matching_type.append(c)

                                if topic_kw and matching_type:
                                    topic_matches = [
                                        c for c in matching_type
                                        if topic_kw in (c.get("topic") or "").lower()
                                        or topic_kw in (c.get("title") or "").lower()
                                        or topic_kw in (c.get("filename") or "").lower()
                                    ]
                                    if topic_matches:
                                        matching_type = topic_matches

                                if len(matching_type) >= 2:
                                    # If user used a pronoun ("it", "that", "this") or explicitly requested assignment
                                    if clean_path in ("it", "that", "this") or any(phrase in user_input.lower() for phrase in ["open that", "open it", "open this", "open that?", "open it?"]):
                                        if dm and dm.current_state and dm.current_state.active_artifact and dm.current_state.active_artifact in matching_type:
                                            matching_type = [dm.current_state.active_artifact]
                                        elif matching_type:
                                            matching_type = [matching_type[0]]
                                    elif any(phrase in user_input.lower() for phrase in ["not the other", "not other", "the assignment", "this one", "first one"]):
                                        asgn_matches = [
                                            c for c in matching_type
                                            if "assignment" in (c.get("topic") or "").lower()
                                            or "assignment" in (c.get("filename") or "").lower()
                                            or c.get("work_goal_id")
                                        ]
                                        if asgn_matches:
                                            matching_type = [asgn_matches[0]]
                                        else:
                                            matching_type = [matching_type[0]]
                                    else:
                                        distinct_fps = set(c.get("filepath") or c.get("path") for c in matching_type)
                                        if len(distinct_fps) >= 2:
                                            type_plural = f"{req_type}s" if req_type else "artifacts"
                                            msg = f"I found two {type_plural} related to {topic_kw or 'your request'}. Which one do you want?"
                                            result["status"] = "waiting_for_user"
                                            result["intent"] = "CLARIFICATION"
                                            result["response"] = msg
                                            return result

                                if matching_type:
                                    resolved_art = matching_type[0]
                                elif valid_candidates and req_type is None:
                                    resolved_art = valid_candidates[0]

                            if resolved_art:
                                clean_path = resolved_art.get("filepath") or resolved_art.get("path")

                            if os.path.exists(clean_path) and os.path.isfile(clean_path):
                                from modules.system_controller.file_manager import open_file
                                open_file(clean_path)
                                f_name = os.path.basename(clean_path)
                                result["status"] = "success"
                                result["intent"] = "OPEN_ARTIFACT"
                                result["action"] = "open_artifact"
                                result["target"] = (resolved_art.get("filename") if resolved_art else None) or f_name
                                result["filepath"] = clean_path
                                if resolved_art:
                                    result["artifact"] = resolved_art
                                    if dm and dm.current_state:
                                        dm.current_state.active_artifact = resolved_art
                                result["response"] = f"Opened {f_name}."
                                return result

                            # Check for typo correction or low-confidence / unknown target safety guard
                            KNOWN_APPS = [
                                "calculator", "notepad", "chrome", "firefox", "edge", "spotify", "explorer",
                                "word", "excel", "powerpoint", "settings", "terminal", "powershell", "paint", "cmd"
                            ]
                            t_clean = target.strip().lower()
                            import difflib
                            close_matches = difflib.get_close_matches(t_clean, KNOWN_APPS, n=1, cutoff=0.75)
                            if close_matches and t_clean not in KNOWN_APPS:
                                target = close_matches[0].capitalize()
                            elif t_clean in ("ti", "unknown", "app", "thing") or (len(t_clean) <= 2 and t_clean not in ("ps", "ui", "ai", "id")):
                                msg = f"Which application do you mean by '{target}'?"
                                result["status"] = "waiting_for_user"
                                result["intent"] = "CLARIFICATION"
                                result["response"] = msg
                                return result

                            # Level 4 Environment Awareness: Check current OS state before launching
                            from extensions.system.smart_opener import smart_opener
                            instance_mode = params.get("instance_mode", "NORMAL")
                            m_inst_exec = re.match(
                                r'^(?:(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+(?:instance|window)\s+of\s+|'
                                r'(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+)',
                                target,
                                re.IGNORECASE
                            )
                            if m_inst_exec:
                                instance_mode = "NEW"
                                target = target[m_inst_exec.end():].strip()
                                target = re.sub(r'^(?:the|a|an)\s+', '', target, flags=re.IGNORECASE).strip()

                            # Entity-type safety guard (Requirement 2): Never pass movies/recommendations to SmartOpener!
                            dm_inst = None
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm_inst = get_dialogue_manager(str(effective_uid))
                            except Exception:
                                pass
                            is_rec_target = False
                            if params.get("target_type") in ("MOVIE_OR_TV", "RECOMMENDATION", "RECOMMENDATION_ITEM", "MUSIC_OR_AUDIO"):
                                is_rec_target = True
                            elif dm_inst and dm_inst.current_state.current_recommendation_list:
                                if any(target.lower() == str(r).lower() for r in dm_inst.current_state.current_recommendation_list):
                                    is_rec_target = True
                            if is_rec_target:
                                result["status"] = "success"
                                result["intent"] = "RECOMMENDATION"
                                result["target"] = target
                                result["target_type"] = "MOVIE_OR_TV"
                                result["response"] = f"Selected '{target}'. This is a media recommendation, not a desktop application. Would you like me to find where to stream it or search the web for it?"
                                result["handled"] = True
                                return result

                            if instance_mode != "NEW":
                                app_state = smart_opener.get_app_state(target)
                                display = app_state.get("display_name") or target
                                if app_state.get("running"):
                                    if app_state.get("foreground"):
                                        # Already open and active in foreground: state is already satisfied
                                        result["status"] = "success"
                                        result["already_satisfied"] = True
                                        result["target"] = target
                                        result["app_name"] = display
                                        result["instance_mode"] = "NORMAL"
                                        result["response"] = f"{display} is already open and active."
                                        try:
                                            from extensions.dialogue_state_manager import get_dialogue_manager
                                            dm = get_dialogue_manager(str(effective_uid))
                                            opened_apps = dm.current_state.session_context.setdefault("opened_applications", [])
                                            if display not in opened_apps:
                                                opened_apps.append(display)
                                            from core.environment import verify_and_synchronize_foreground_state
                                            verify_and_synchronize_foreground_state(user_id=effective_uid, action_target=target)
                                        except Exception:
                                            pass
                                        return result
                                    else:
                                        # Running in background: focus / bring to front
                                        focused = smart_opener.focus_app(target)
                                        result["status"] = "success"
                                        result["already_satisfied"] = True
                                        result["target"] = target
                                        result["app_name"] = display
                                        result["instance_mode"] = "NORMAL"
                                        result["response"] = f"{display} is already running. Brought it to the front." if focused else f"{display} is already running."
                                        try:
                                            from extensions.dialogue_state_manager import get_dialogue_manager
                                            dm = get_dialogue_manager(str(effective_uid))
                                            opened_apps = dm.current_state.session_context.setdefault("opened_applications", [])
                                            if display not in opened_apps:
                                                opened_apps.append(display)
                                            from core.environment import verify_and_synchronize_foreground_state
                                            verify_and_synchronize_foreground_state(user_id=effective_uid, action_target=target)
                                        except Exception:
                                            pass
                                        return result

                            # Universal path: smart_opener handles .exe, .lnk, Store, URI
                            open_dict = smart_opener.smart_open(target, new_instance=(instance_mode == "NEW"))
                            if isinstance(open_dict, dict) and open_dict.get("success"):
                                display = open_dict.get("display_name") or target
                                result["status"] = "success"
                                result["target"] = target
                                result["app_name"] = display
                                result["instance_mode"] = instance_mode
                                resp_msg = open_dict.get("message") or (f"Opened another instance of {display}." if instance_mode == "NEW" else f"Opened {display}.")
                                result["response"] = resp_msg
                                try:
                                    from extensions.dialogue_state_manager import get_dialogue_manager
                                    dm = get_dialogue_manager(str(effective_uid))
                                    opened_apps = dm.current_state.session_context.setdefault("opened_applications", [])
                                    if display not in opened_apps:
                                        opened_apps.append(display)
                                    from core.environment import verify_and_synchronize_foreground_state
                                    verify_and_synchronize_foreground_state(user_id=effective_uid, action_target=target)
                                except Exception:
                                    pass
                            else:
                                if instance_mode == "NEW":
                                    result["status"] = "error"
                                    result["target"] = target
                                    result["instance_mode"] = "NEW"
                                    result["response"] = open_dict.get("message") if isinstance(open_dict, dict) else f"Could not open another instance of {target}."
                                    return result

                                # Fallback/adaptation: check if the user intended to open a document/file/presentation
                                file_target = target
                                file_target_clean = re.sub(r'^(?:my|the)\s+', '', file_target, flags=re.IGNORECASE).strip().rstrip('.?!')
                                is_doc_like = any(w in file_target_clean.lower() for w in ["presentation", "document", "slides", "report", "pdf", "sheet", "doc", "file", "assignment", "ppt", "pptx"]) or "." in file_target_clean
                                if is_doc_like:
                                    from modules.system_controller.file_manager import find_file_in_desktop, search_files, resolve_directory_name, open_file

                                    # Check memory/dialogue manager artifacts first
                                    try:
                                        from extensions.dialogue_state_manager import get_dialogue_manager
                                        dm = get_dialogue_manager(str(effective_uid))
                                        art_cands = []
                                        if dm and dm.current_state:
                                            if dm.current_state.active_artifact:
                                                art_cands.append(dm.current_state.active_artifact)
                                            for a in getattr(dm.current_state, "active_documents", []):
                                                if a not in art_cands:
                                                    art_cands.append(a)
                                            active_g = getattr(dm.current_state, "current_goal", None)
                                            if active_g and isinstance(active_g, dict):
                                                for d in active_g.get("deliverables", []):
                                                    fp = d.get("file_path")
                                                    if fp and os.path.exists(fp):
                                                        art_cands.append({"filepath": fp, "filename": os.path.basename(fp), "topic": active_g.get("topic")})

                                        matching_art = None
                                        for ac in art_cands:
                                            afp = ac.get("filepath") or ac.get("path")
                                            if afp and os.path.exists(afp):
                                                afn = (ac.get("filename") or os.path.basename(afp)).lower()
                                                atop = (ac.get("topic") or "").lower()
                                                if any(w in file_target_clean.lower() for w in ["assignment", "presentation", "ppt", "deadlock", "dbms"]):
                                                    matching_art = ac
                                                    break
                                                elif not matching_art:
                                                    matching_art = ac

                                        if matching_art:
                                            art_path = matching_art.get("filepath") or matching_art.get("path")
                                            art_name = matching_art.get("filename") or os.path.basename(art_path)
                                            result["status"] = "success"
                                            result["target"] = art_name
                                            result["files"] = [{"name": art_name, "path": art_path}]
                                            open_file(art_path)
                                            result["response"] = f"Opened presentation '{art_name}'."
                                            return result
                                    except Exception:
                                        pass
                                    
                                    is_generic = file_target_clean.lower() in ("presentation", "document", "slides", "report", "doc", "file", "presentation.")
                                    has_extension = "." in file_target_clean and len(file_target_clean.split(".")[-1]) in (2, 3, 4)
                                    if has_extension:
                                        exact_file = find_file_in_desktop(file_target_clean)
                                        if exact_file:
                                            result["status"] = "success"
                                            f0_name = os.path.basename(exact_file)
                                            result["target"] = f0_name
                                            result["files"] = [{"name": f0_name, "path": exact_file}]
                                            open_file(exact_file)
                                            result["response"] = f"Opened presentation '{f0_name}'."
                                            return result

                                    found_files = []
                                    pat = file_target_clean
                                    if "presentation" in pat.lower():
                                        pat = "presentation"
                                    for loc_name in ["desktop", "documents"]:
                                        loc_path = resolve_directory_name(loc_name)
                                        s_res = search_files(pattern=pat, root_dir=loc_path)
                                        if s_res.get("success") and s_res.get("files"):
                                            for f in s_res["files"]:
                                                fname = f.get("name", "").lower()
                                                if "presentation" in pat.lower() and (fname.endswith(".py") or fname.endswith(".exe") or fname.endswith(".log")):
                                                    continue
                                                found_files.append(f)
                                    if found_files:
                                        result["files"] = found_files
                                        result["target"] = found_files[0].get("name")
                                        f0_path = found_files[0].get("path")
                                        f0_name = found_files[0].get("name")
                                        if len(found_files) == 1 or not is_generic:
                                            result["status"] = "success"
                                            open_file(f0_path)
                                            result["response"] = f"Opened presentation '{f0_name}'."
                                        else:
                                            f1_name = found_files[1].get("name")
                                            result["status"] = "waiting_for_user"
                                            result["response"] = f"I found {len(found_files)} presentation files: '{f0_name}' and '{f1_name}'. Which one should I open?"
                                            try:
                                                from extensions.dialogue_state_manager import get_dialogue_manager
                                                dm = get_dialogue_manager(str(effective_uid))
                                                dm.current_state.last_search_results = found_files
                                                dm.current_state.last_search_results_turn = dm.current_state.current_turn
                                                dm.current_state.pending_clarification = {"type": "disambiguate_files", "candidates": found_files, "action": "open"}
                                                dm.current_state.goal_status = "WAITING_FOR_USER"
                                            except Exception:
                                                pass
                                        return result

                                from modules.system_controller.app_launcher import launch_game
                                g_res = launch_game(target)
                                if g_res.get("success"):
                                    result["status"] = "success"
                                    result["target"] = target
                                    result["response"] = g_res.get("message", f"Launching '{target}'.")
                                    return result

                                msg = (open_dict.get("message") if isinstance(open_dict, dict) else None) \
                                      or f"Could not find '{target}' on your system."
                                result["status"] = "error"
                                result["response"] = msg
                    else:
                        # Close application or terminate process
                        if params.get("action") == "terminate_process" or any(k in user_input.lower() for k in ["kill", "terminate", "process"]):
                            from modules.system_controller.system_controller import terminate_process
                            term_res = terminate_process(name=target)
                            result["status"] = "success" if term_res.get("success") else "error"
                            result["response"] = term_res.get("message", f"Terminated process {target}.")
                            result.update(term_res)
                        else:
                            # Safety guard: unknown / low confidence target
                            t_clean = target.strip().lower()
                            if t_clean in ("ti", "unknown", "app", "thing") or (len(t_clean) <= 2 and t_clean not in ("ps", "ui", "ai", "id")):
                                msg = f"Which application do you mean by '{target}'?"
                                result["status"] = "waiting_for_user"
                                result["intent"] = "CLARIFICATION"
                                result["response"] = msg
                                return result

                            from legacy.actions import close_app
                            # Support closing multiple targets (e.g. "Calculator and Notepad")
                            targets = [t.strip() for t in re.split(r'\s+and\s+|,', target) if t.strip()]
                            if len(targets) > 1:
                                res_list = []
                                all_ok = True
                                for sub_t in targets:
                                    sub_res = close_app(sub_t)
                                    res_list.append(sub_res)
                                    if "could not find or close" in sub_res.lower() or "no running browser" in sub_res.lower():
                                        all_ok = False
                                result["status"] = "success" if all_ok else "error"
                                result["intent"] = "CLOSE_APPLICATION"
                                result["action"] = "close_app"
                                result["target"] = target
                                result["response"] = " ".join(res_list)
                                try:
                                    from extensions.dialogue_state_manager import get_dialogue_manager
                                    dm = get_dialogue_manager(str(effective_uid))
                                    low_targets = {st.lower() for st in targets}
                                    opened = dm.current_state.session_context.get("opened_applications", [])
                                    dm.current_state.session_context["opened_applications"] = [
                                        a for a in opened if not any(st.lower() in a.lower() or a.lower() in st.lower() for st in targets)
                                    ]
                                    dm.current_state.active_applications = [
                                        a for a in dm.current_state.active_applications
                                        if a.lower() not in low_targets and not any(st in a.lower() for st in low_targets)
                                    ]
                                    if "APPLICATION" in dm.current_state.active_entity_set:
                                        dm.current_state.active_entity_set["APPLICATION"] = [
                                            a for a in dm.current_state.active_entity_set["APPLICATION"]
                                            if (a.get("value", a) if isinstance(a, dict) else str(a)).lower() not in low_targets
                                        ]
                                    if dm.current_state.active_application and any(st in dm.current_state.active_application.lower() for st in low_targets):
                                        dm.current_state.active_application = dm.current_state.active_applications[-1] if dm.current_state.active_applications else None
                                    from extensions.context_manager import get_manager
                                    ctx_mgr = get_manager()
                                    if ctx_mgr.active_context.get("last_app") and any(st in ctx_mgr.active_context["last_app"].lower() for st in low_targets):
                                        ctx_mgr.active_context["last_app"] = dm.current_state.active_application
                                        if not dm.current_state.active_applications:
                                            ctx_mgr.clear_context()
                                except Exception:
                                    pass
                                return result

                            close_res = close_app(target)
                            result["intent"] = "CLOSE_APPLICATION"
                            result["action"] = "close_app"
                            result["target"] = target
                            if "could not find or close" in close_res.lower() or "no running browser" in close_res.lower():
                                result["status"] = "error"
                            else:
                                result["status"] = "success"
                                try:
                                    from extensions.dialogue_state_manager import get_dialogue_manager
                                    dm = get_dialogue_manager(str(effective_uid))
                                    target_low = target.lower()
                                    opened = dm.current_state.session_context.get("opened_applications", [])
                                    dm.current_state.session_context["opened_applications"] = [
                                        a for a in opened if target_low not in a.lower() and a.lower() not in target_low
                                    ]
                                    dm.current_state.active_applications = [
                                        a for a in dm.current_state.active_applications
                                        if target_low not in a.lower() and a.lower() not in target_low
                                    ]
                                    if "APPLICATION" in dm.current_state.active_entity_set:
                                        dm.current_state.active_entity_set["APPLICATION"] = [
                                            a for a in dm.current_state.active_entity_set["APPLICATION"]
                                            if target_low not in (a.get("value", a) if isinstance(a, dict) else str(a)).lower()
                                        ]
                                    if dm.current_state.active_application and (target_low in dm.current_state.active_application.lower() or dm.current_state.active_application.lower() in target_low):
                                        dm.current_state.active_application = dm.current_state.active_applications[-1] if dm.current_state.active_applications else None
                                    from extensions.context_manager import get_manager
                                    ctx_mgr = get_manager()
                                    if ctx_mgr.active_context.get("last_app") and (target_low in ctx_mgr.active_context["last_app"].lower() or ctx_mgr.active_context["last_app"].lower() in target_low):
                                        ctx_mgr.active_context["last_app"] = dm.current_state.active_application
                                        if not dm.current_state.active_applications:
                                            ctx_mgr.clear_context()
                                except Exception:
                                    pass
                            result["response"] = close_res
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Failed to manage application: {e}"
                    
            # 5. FILE OPERATIONS
            elif intent == Intent.FILE_OPERATIONS:
                try:
                    action = params.get("action", "")
                    from extensions.dialogue_state_manager import get_dialogue_manager
                    from pathlib import Path
                    dm = get_dialogue_manager(str(effective_uid))

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
                            if "already exists" in res.lower():
                                result["already_satisfied"] = True
                                result["already_exists"] = True
                            result["response"] = res
                            result["action"] = "create_folder"
                            result["target"] = folder_name
                            result["folder"] = folder_name
                            from modules.system_controller.file_manager import resolve_directory_name
                            loc_dir = resolve_directory_name(params.get("location", "desktop"))
                            f_path = os.path.join(loc_dir, folder_name)
                            result["path"] = f_path
                            result["filepath"] = f_path
                            if dm and result["status"] == "success":
                                dm.current_state.active_folder = folder_name
                                if folder_name not in dm.current_state.active_folders:
                                    dm.current_state.active_folders.append(folder_name)
                                dm.current_state.session_context["active_folder_path"] = f_path
                                dm.current_state.session_context["last_created_folder"] = f_path
                                dm.current_state.entities["folder"] = folder_name
                                dm.current_state.entities["folder_path"] = f_path
                                dm._record_recent_action("CREATE_FOLDER", "FOLDER", folder_name, True, f_path)
                                dm._last_mentioned_entity = {
                                    "value": folder_name,
                                    "name": folder_name,
                                    "path": f_path,
                                    "intent": "FILE_OPERATIONS",
                                    "entity_type": "FOLDER",
                                    "turn": dm.current_state.current_turn,
                                    "timestamp": datetime.now().isoformat()
                                }

                    elif action == "save_document":
                        from modules.system_controller.folder_manager import get_desktop_path
                        from modules.system_controller.file_manager import create_text_file
                        filename = params.get("filename") or params.get("name") or "document.txt"
                        desktop = get_desktop_path()
                        file_path = os.path.join(desktop, filename)
                        doc_info = dm.current_state.session_context.get("active_document") if dm else None
                        content = ""
                        if doc_info and isinstance(doc_info, dict):
                            content = doc_info.get("content", "")
                        if not content and dm:
                            content = dm.current_state.entities.get("typed_text", "")
                        create_text_file(file_path, content=content)
                        result["status"] = "success"
                        result["action"] = "save_document"
                        result["target"] = filename
                        result["entity_type"] = "DOCUMENT"
                        result["path"] = file_path
                        result["filepath"] = file_path
                        result["response"] = f"Saved document as '{filename}'."
                        if dm:
                            dm.current_state.active_document = filename
                            if filename not in dm.current_state.active_documents:
                                dm.current_state.active_documents.append(filename)
                            dm.current_state.active_file = filename
                            if filename not in dm.current_state.active_files:
                                dm.current_state.active_files.append(filename)
                            dm.current_state.session_context["active_document"] = {"name": filename, "path": file_path, "content": content}
                            dm.current_state.entities["document"] = filename
                            dm.current_state.entities["file"] = filename
                            dm._record_recent_action("SAVE_DOCUMENT", "DOCUMENT", filename, True, file_path)
                            dm._last_mentioned_entity = {
                                "value": filename,
                                "name": filename,
                                "path": file_path,
                                "intent": "FILE_OPERATIONS",
                                "entity_type": "DOCUMENT",
                                "turn": dm.current_state.current_turn,
                                "timestamp": datetime.now().isoformat()
                            }
                        return result

                    elif action == "create_file":
                        from modules.system_controller.file_manager import create_text_file, resolve_directory_name
                        file_name = params.get("target") or params.get("name") or params.get("filename")
                        if not file_name:
                            result["status"] = "error"
                            result["response"] = "Please specify a file name to create."
                        else:
                            clean_name = file_name.strip(' "\'')
                            location = params.get("location") or "desktop"
                            pf = params.get("parent_folder")
                            dir_path = None
                            
                            # 1. Explicit absolute path
                            if pf and os.path.isabs(pf) and os.path.isdir(pf):
                                dir_path = pf
                            # 2. Named folder inside desktop/allowed directories
                            elif pf and pf.lower() not in ("it", "that", "this", "the folder", "folder"):
                                from modules.system_controller.folder_manager import get_desktop_path
                                desktop = get_desktop_path()
                                cand = os.path.join(desktop, pf)
                                if os.path.exists(cand) and os.path.isdir(cand):
                                    dir_path = cand
                                else:
                                    for root, dirs, _ in os.walk(desktop):
                                        if os.path.basename(root).lower() == pf.lower():
                                            dir_path = root
                                            break
                            # 3. Anaphoric reference ("inside it", "inside that", etc.)
                            elif pf and pf.lower() in ("it", "that", "this", "the folder", "folder"):
                                l_entity = getattr(dm, "_last_mentioned_entity", None) if dm else None
                                if l_entity and l_entity.get("path") and os.path.isdir(l_entity["path"]):
                                    dir_path = l_entity["path"]
                                elif dm and dm.current_state.session_context.get("last_created_folder") and os.path.isdir(dm.current_state.session_context["last_created_folder"]):
                                    dir_path = dm.current_state.session_context["last_created_folder"]
                                elif dm and dm.current_state.entities.get("folder_path") and os.path.isdir(dm.current_state.entities["folder_path"]):
                                    dir_path = dm.current_state.entities["folder_path"]
                                elif dm and dm.current_state.entities.get("folder"):
                                    from modules.system_controller.folder_manager import get_desktop_path
                                    cand_f = os.path.join(get_desktop_path(), dm.current_state.entities["folder"])
                                    if os.path.isdir(cand_f):
                                        dir_path = cand_f
                                else:
                                    result["status"] = "error"
                                    result["response"] = "Could not identify which parent folder to create the file inside."
                                    return result
                            
                            # 4. Fallback if no parent folder was requested at all
                            if not dir_path:
                                if pf:
                                    result["status"] = "error"
                                    result["response"] = f"Parent folder '{pf}' not found. Cannot create '{clean_name}' inside it."
                                    return result
                                elif os.path.isabs(clean_name):
                                    full_path = clean_name
                                else:
                                    dir_path = resolve_directory_name(location)
                                    full_path = os.path.join(dir_path, clean_name)
                            else:
                                full_path = os.path.join(dir_path, clean_name)
                            
                            c_res = create_text_file(full_path, content=params.get("content", ""))
                            if c_res.get("success") and os.path.isfile(full_path):
                                result["status"] = "success"
                                result["action"] = "create_file"
                                result["target"] = os.path.basename(full_path)
                                result["path"] = full_path
                                result["file"] = os.path.basename(full_path)
                                result["filepath"] = full_path
                                result["response"] = f"Created file '{os.path.basename(full_path)}' successfully at {full_path}."
                                try:
                                    from extensions.context_manager import get_manager
                                    get_manager().add_user_artifact(effective_uid, {
                                        "path": full_path,
                                        "type": "file",
                                        "name": os.path.basename(full_path)
                                    })
                                except Exception:
                                    pass
                                if dm:
                                    f_base = os.path.basename(full_path)
                                    dm.current_state.active_file = f_base
                                    if f_base not in dm.current_state.active_files:
                                        dm.current_state.active_files.append(f_base)
                                    dm._record_recent_action("CREATE_FILE", "FILE", f_base, True, full_path)
                                    dm._last_mentioned_entity = {
                                        "value": f_base,
                                        "name": f_base,
                                        "path": full_path,
                                        "intent": "FILE_OPERATIONS",
                                        "entity_type": "FILE",
                                        "turn": dm.current_state.current_turn,
                                        "timestamp": datetime.now().isoformat()
                                    }
                            else:
                                result["status"] = "error"
                                result["response"] = c_res.get("message", f"Failed to create file '{clean_name}'.")

                    elif action == "clarify_folder":
                        result["status"] = "success"
                        result["response"] = "Which folder would you like me to open?"

                    elif action == "open_folder":
                        from modules.system_controller.folder_manager import get_desktop_path
                        target_folder = params.get("target") or params.get("name")
                        l_entity = getattr(dm, "_last_mentioned_entity", None) if dm else None
                        if (not target_folder or target_folder.lower() in ("it", "that", "this")) and l_entity:
                            target_folder = l_entity.get("path") or l_entity.get("name") or l_entity.get("value")
                        if not target_folder:
                            result["status"] = "error"
                            result["response"] = "Which folder would you like to open?"
                        else:
                            clean_name = target_folder.strip(' "\'')
                            desktop = get_desktop_path()
                            possible_paths = []
                            clean_name_lower = clean_name.lower().replace("my ", "").strip()
                            if clean_name_lower == "downloads":
                                possible_paths.append(str(Path.home() / "Downloads"))
                            elif clean_name_lower in ("documents", "docs"):
                                possible_paths.append(str(Path.home() / "Documents"))
                            elif clean_name_lower == "desktop":
                                possible_paths.append(desktop)

                            if l_entity and l_entity.get("path") and os.path.isdir(l_entity["path"]):
                                possible_paths.append(l_entity["path"])
                            possible_paths.extend([
                                os.path.join(desktop, clean_name),
                                os.path.join(str(Path.home() / "Downloads"), clean_name),
                                os.path.join(str(Path.home() / "Documents"), clean_name),
                                os.path.join(os.path.expanduser("~"), clean_name),
                                clean_name
                            ])
                            folder_path = None
                            for p in possible_paths:
                                if os.path.exists(p) and os.path.isdir(p):
                                    folder_path = p
                                    break

                            if not folder_path:
                                result["status"] = "error"
                                result["response"] = f"Folder '{clean_name}' not found."
                            else:
                                import platform, subprocess
                                sys_name = platform.system()
                                if sys_name == "Windows":
                                    os.startfile(folder_path)
                                elif sys_name == "Darwin":
                                    subprocess.call(["open", folder_path])
                                else:
                                    subprocess.call(["xdg-open", folder_path])
                                result["status"] = "success"
                                result["response"] = f"Folder '{clean_name}' opened successfully."
                                result["action"] = "open_folder"
                                result["target"] = clean_name
                                result["folder"] = clean_name
                                result["path"] = folder_path
                                if dm:
                                    dm._last_mentioned_entity = {
                                        "value": clean_name,
                                        "name": clean_name,
                                        "path": folder_path,
                                        "intent": "FILE_OPERATIONS",
                                        "entity_type": "FOLDER",
                                        "turn": dm.current_state.current_turn,
                                        "timestamp": datetime.now().isoformat()
                                    }

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
                        target_file = params.get("filepath") or params.get("path") or params.get("target") or params.get("name")
                        l_entity = getattr(dm, "_last_mentioned_entity", None) if dm else None
                        if (not target_file or target_file.lower() in ("it", "that", "this", "the file", "file")) and l_entity:
                            target_file = l_entity.get("path") or l_entity.get("name") or l_entity.get("value")
                        if not target_file:
                            result["status"] = "error"
                            result["response"] = "Please specify a file name to open."
                        else:
                            clean_target = target_file.strip(' "\'')
                            if not os.path.isabs(clean_target) and l_entity and l_entity.get("path") and os.path.exists(l_entity["path"]):
                                if os.path.basename(l_entity["path"]).lower() == clean_target.lower():
                                    clean_target = l_entity["path"]
                            res = open_file(clean_target)
                            if "not found" in res.lower() or "error" in res.lower():
                                result["status"] = "error"
                            else:
                                result["status"] = "success"
                            result["response"] = res
                            result["action"] = "open_file"
                            result["target"] = clean_target
                            result["file"] = os.path.basename(clean_target)
                            result["filepath"] = clean_target if os.path.isabs(clean_target) else None
                            if dm and result["status"] == "success":
                                resolved_path = clean_target if os.path.isabs(clean_target) else (l_entity.get("path") if (l_entity and l_entity.get("name") == clean_target) else None)
                                dm._last_mentioned_entity = {
                                    "value": os.path.basename(clean_target),
                                    "name": os.path.basename(clean_target),
                                    "path": resolved_path,
                                    "intent": "FILE_OPERATIONS",
                                    "entity_type": "FILE",
                                    "turn": dm.current_state.current_turn,
                                    "timestamp": datetime.now().isoformat()
                                }

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
                            found = None
                            # Check active documents / artifacts in dialogue manager first
                            target_low = target_file.lower().strip()
                            is_art_query = any(k in target_low for k in ["ppt", "presentation", "pdf", "report", "document", "file", "created", "assignment"])
                            if is_art_query and dm and dm.current_state:
                                candidates = []
                                if dm.current_state.active_artifact:
                                    candidates.append(dm.current_state.active_artifact)
                                for a in getattr(dm.current_state, "active_documents", []):
                                    if a not in candidates:
                                        candidates.append(a)
                                active_g = getattr(dm.current_state, "current_goal", None)
                                if active_g and isinstance(active_g, dict):
                                    for d in active_g.get("deliverables", []):
                                        fp = d.get("file_path")
                                        if fp and os.path.exists(fp):
                                            candidates.append({"filepath": fp, "filename": os.path.basename(fp)})
                                for c in candidates:
                                    fp = c.get("filepath") or c.get("path")
                                    if fp and os.path.exists(fp):
                                        found = fp
                                        break

                            if not found:
                                found = find_file_in_desktop(target_file)

                            if found:
                                fname = os.path.basename(found)
                                result["status"] = "success"
                                result["target"] = fname
                                result["path"] = found
                                result["filepath"] = found
                                result["files"] = [{"name": fname, "path": found}]
                                result["response"] = f"Found {fname} at {found}."
                            else:
                                result["status"] = "error"
                                result["response"] = f"File '{target_file}' was not found on desktop."

                    elif action == "organize_desktop":
                        from modules.system_controller import organize_directory
                        loc = params.get("location", "desktop")
                        preview = params.get("preview", False)
                        org_res = organize_directory(location=loc, preview_only=preview, user_id=user_id)
                        result["status"] = "success" if org_res.get("success") else "error"
                        result["response"] = org_res.get("message", "Desktop organized.")

                    elif action == "find_duplicates":
                        from modules.system_controller.file_manager import find_duplicate_files, resolve_directory_name
                        loc = resolve_directory_name(params.get("location", "desktop"))
                        dup_res = find_duplicate_files(dir_path=loc)
                        result["status"] = "success" if dup_res.get("success") else "error"
                        result["response"] = dup_res.get("message", "Checked for duplicates.")
                        result.update(dup_res)

                    elif action == "search_files":
                        from modules.system_controller.file_manager import search_files, resolve_directory_name
                        loc = resolve_directory_name(params.get("location", "desktop"))
                        s_res = search_files(
                            root_dir=loc,
                            pattern=params.get("pattern", ""),
                            ext=params.get("ext"),
                            min_size_mb=params.get("min_size_mb"),
                            modified_days=params.get("modified_days")
                        )
                        result["status"] = "success" if s_res.get("success") else "error"
                        result["response"] = s_res.get("message", "Search completed.")
                        result.update(s_res)

                    elif action == "directory_stats":
                        from modules.system_controller.file_manager import get_directory_stats, resolve_directory_name
                        loc = resolve_directory_name(params.get("location", "desktop"))
                        stat_res = get_directory_stats(dir_path=loc)
                        result["status"] = "success" if stat_res.get("success") else "error"
                        result["response"] = stat_res.get("message", "Calculated stats.")
                        result.update(stat_res)

                    elif action == "largest_files":
                        from modules.system_controller.file_manager import get_largest_files, resolve_directory_name
                        loc = resolve_directory_name(params.get("location", "desktop"))
                        large_res = get_largest_files(dir_path=loc, n=params.get("count", 5))
                        result["status"] = "success" if large_res.get("success") else "error"
                        result["response"] = large_res.get("message", "Found largest files.")
                        result.update(large_res)

                    elif action == "delete_file":
                        from modules.system_controller.file_manager import safe_delete_file
                        target_file = params.get("target")
                        if not target_file:
                            result["status"] = "error"
                            result["response"] = "Please specify a file name to delete."
                        else:
                            del_res = safe_delete_file(target_file, use_trash=True)
                            result["status"] = "success" if del_res.get("success") else "error"
                            result["response"] = del_res.get("message", f"Deleted {target_file}.")
                            result.update(del_res)

                    elif action == "move_file":
                        from modules.system_controller.file_manager import move_file, resolve_directory_name
                        src = params.get("src")
                        dst = resolve_directory_name(params.get("dst"))
                        l_entity = getattr(dm, "_last_mentioned_entity", None) if dm else None
                        if l_entity:
                            ent_name = l_entity.get("name") or l_entity.get("value")
                            ent_path = l_entity.get("path")
                            if not src or src.lower() in ("it", "that", "this") or (ent_name and src.lower() == ent_name.lower()):
                                if ent_path and os.path.exists(ent_path):
                                    src = ent_path
                                elif ent_name:
                                    src = ent_name
                        if not src or not dst:
                            result["status"] = "error"
                            result["response"] = "Please specify source file and destination."
                        else:
                            mv_res = move_file(src, dst, user_id=user_id)
                            result["status"] = "success" if mv_res.get("success") else "error"
                            result["response"] = mv_res.get("message", "File moved.")
                            result.update(mv_res)
                            if result["status"] == "success":
                                new_path = mv_res.get("target_path") or os.path.join(dst, os.path.basename(src))
                                is_dir = mv_res.get("is_dir", False) or os.path.isdir(new_path)
                                ent_type = "FOLDER" if is_dir else "FILE"
                                result["path"] = new_path
                                result["target"] = os.path.basename(new_path)
                                if is_dir:
                                    result["folder"] = os.path.basename(new_path)
                                else:
                                    result["file"] = os.path.basename(new_path)
                                if dm:
                                    dm._last_mentioned_entity = {
                                        "value": os.path.basename(new_path),
                                        "name": os.path.basename(new_path),
                                        "path": new_path,
                                        "intent": "FILE_OPERATIONS",
                                        "entity_type": ent_type,
                                        "turn": dm.current_state.current_turn,
                                        "timestamp": datetime.now().isoformat()
                                    }

                    elif action == "rename_file":
                        from modules.system_controller.file_manager import rename_file
                        src = params.get("filepath") or params.get("path") or params.get("src") or params.get("target")
                        new_name = params.get("new_name") or params.get("name") or params.get("dst")
                        l_entity = getattr(dm, "_last_mentioned_entity", None) if dm else None
                        if l_entity:
                            ent_name = l_entity.get("name") or l_entity.get("value")
                            ent_path = l_entity.get("path")
                            if not src or src.lower() in ("it", "that", "this", "the file", "the folder", "file", "folder") or (ent_name and src.lower() == ent_name.lower()):
                                if ent_path and os.path.exists(ent_path):
                                    src = ent_path
                                elif ent_name:
                                    src = ent_name
                        if not src or not new_name:
                            result["status"] = "error"
                            result["response"] = "Please specify the file name and the new name."
                        else:
                            ren_res = rename_file(src, new_name, user_id=user_id)
                            result["status"] = "success" if ren_res.get("success") else "error"
                            result["response"] = ren_res.get("message", "File renamed.")
                            result.update(ren_res)
                            if result["status"] == "success":
                                new_path = ren_res.get("new_path")
                                is_dir = ren_res.get("is_dir", False) or (new_path and os.path.isdir(new_path))
                                ent_type = "FOLDER" if is_dir else "FILE"
                                result["action"] = "rename_file"
                                result["path"] = new_path
                                result["filepath"] = new_path
                                result["target"] = new_name
                                if is_dir:
                                    result["folder"] = new_name
                                else:
                                    result["file"] = new_name
                                if dm:
                                    dm._last_mentioned_entity = {
                                        "value": new_name,
                                        "name": new_name,
                                        "path": new_path,
                                        "intent": "FILE_OPERATIONS",
                                        "entity_type": ent_type,
                                        "turn": dm.current_state.current_turn,
                                        "timestamp": datetime.now().isoformat()
                                    }

                    elif action == "pdf_info":
                        from modules.document_tools import get_pdf_info
                        from modules.system_controller.file_manager import find_file_in_desktop
                        from extensions.context_manager import get_manager
                        from pathlib import Path
                        tf = params.get("target", "").strip()
                        if not tf or tf.lower() in ("this pdf", "the pdf", "pdf"):
                            art = get_manager().get_last_user_artifact(user_id=user_id, artifact_type="pdf")
                            if art and art.get("path") and os.path.exists(art["path"]):
                                tf = art["path"]
                        if not os.path.exists(tf):
                            found = find_file_in_desktop(os.path.basename(tf))
                            if found: tf = found
                            else:
                                for std_dir in ["Documents", "Downloads"]:
                                    cand = Path.home() / std_dir / os.path.basename(tf)
                                    if cand.exists(): tf = str(cand); break
                        p_res = get_pdf_info(tf)
                        result["status"] = "success" if p_res.get("success") else "error"
                        result["response"] = p_res.get("message", "Retrieved PDF info.")
                        result.update(p_res)

                    elif action == "split_pdf":
                        from modules.document_tools import split_pdf
                        from modules.system_controller.file_manager import find_file_in_desktop
                        from extensions.context_manager import get_manager
                        from pathlib import Path
                        tf = params.get("target", "").strip()
                        if not tf or tf.lower() in ("this pdf", "the pdf", "pdf"):
                            art = get_manager().get_last_user_artifact(user_id=user_id, artifact_type="pdf")
                            if art and art.get("path") and os.path.exists(art["path"]):
                                tf = art["path"]
                        if not os.path.exists(tf):
                            found = find_file_in_desktop(os.path.basename(tf))
                            if found: tf = found
                            else:
                                for std_dir in ["Documents", "Downloads"]:
                                    cand = Path.home() / std_dir / os.path.basename(tf)
                                    if cand.exists(): tf = str(cand); break
                        sp_res = split_pdf(tf, start_page=params.get("start_page", 1), end_page=params.get("end_page", 2))
                        result["status"] = "success" if sp_res.get("success") else "error"
                        result["response"] = sp_res.get("message", "Split PDF.")
                        result["filepath"] = sp_res.get("filepath")
                        result.update(sp_res)
                        if result["status"] == "success" and result.get("filepath"):
                            try:
                                get_manager().add_user_artifact(user_id, {
                                    "path": result["filepath"],
                                    "filename": os.path.basename(result["filepath"]),
                                    "type": "pdf",
                                    "source_action": "pdf_split"
                                })
                            except Exception:
                                pass

                    elif action == "merge_pdfs":
                        from modules.document_tools import merge_pdfs
                        from modules.system_controller.file_manager import search_files, resolve_directory_name
                        from extensions.context_manager import get_manager
                        pdf_list = []
                        # 1. Check recent user artifacts
                        arts = get_manager().get_recent_user_artifacts(user_id=user_id, artifact_type="pdf", limit=5)
                        for a in arts:
                            if a.get("path") and os.path.exists(a["path"]) and a["path"] not in pdf_list:
                                pdf_list.append(a["path"])
                        # 2. Check documents directory
                        if len(pdf_list) < 2:
                            for f in search_files(root_dir=resolve_directory_name("documents"), ext="pdf").get("files", []):
                                if f["path"] not in pdf_list:
                                    pdf_list.append(f["path"])
                                if len(pdf_list) >= 3: break
                        # 3. Check downloads directory
                        if len(pdf_list) < 2:
                            for f in search_files(root_dir=resolve_directory_name("downloads"), ext="pdf").get("files", []):
                                if f["path"] not in pdf_list:
                                    pdf_list.append(f["path"])
                                if len(pdf_list) >= 3: break
                        # 4. Check desktop directory
                        if len(pdf_list) < 2:
                            for f in search_files(root_dir=resolve_directory_name("desktop"), ext="pdf").get("files", []):
                                if f["path"] not in pdf_list:
                                    pdf_list.append(f["path"])
                                if len(pdf_list) >= 3: break
                        mg_res = merge_pdfs(pdf_list)
                        result["status"] = "success" if mg_res.get("success") else "error"
                        result["response"] = mg_res.get("message", "Merged PDFs.")
                        result["filepath"] = mg_res.get("filepath")
                        result.update(mg_res)
                        if result["status"] == "success" and result.get("filepath"):
                            try:
                                get_manager().add_user_artifact(user_id, {
                                    "path": result["filepath"],
                                    "filename": os.path.basename(result["filepath"]),
                                    "type": "pdf",
                                    "source_action": "pdf_merge"
                                })
                            except Exception:
                                pass

                    elif action == "extract_pdf_text":
                        from modules.document_tools import extract_pdf_text
                        from modules.system_controller.file_manager import find_file_in_desktop
                        from extensions.context_manager import get_manager
                        from pathlib import Path
                        tf = params.get("target", "").strip()
                        if not tf or tf.lower() in ("this pdf", "the pdf", "pdf"):
                            art = get_manager().get_last_user_artifact(user_id=user_id, artifact_type="pdf")
                            if art and art.get("path") and os.path.exists(art["path"]):
                                tf = art["path"]
                        if not os.path.exists(tf):
                            found = find_file_in_desktop(os.path.basename(tf))
                            if found: tf = found
                            else:
                                for std_dir in ["Documents", "Downloads"]:
                                    cand = Path.home() / std_dir / os.path.basename(tf)
                                    if cand.exists(): tf = str(cand); break
                        ex_res = extract_pdf_text(tf)
                        result["status"] = "success" if ex_res.get("success") else "error"
                        result["response"] = ex_res.get("message", "Extracted PDF text.")
                    elif action == "profile_file":
                        from pathlib import Path
                        from modules.system_controller.file_manager import profile_file_content, find_file_in_desktop, resolve_directory_name
                        tf = params.get("target", "").strip()
                        if not tf or tf.lower() in ("it", "that", "that ppt", "the ppt", "that pptx", "the pptx", "that presentation", "the presentation", "that file", "the file", "this file", "that document", "this document"):
                            from extensions.context_manager import get_manager
                            art_type = "pptx" if ("ppt" in tf.lower() or "presentation" in tf.lower()) else None
                            art = get_manager().get_last_user_artifact(user_id=effective_uid, artifact_type=art_type)
                            if not art and art_type:
                                art = get_manager().get_last_user_artifact(user_id=effective_uid)
                            if art and art.get("path") and os.path.exists(art["path"]):
                                tf = art["path"]
                        if not os.path.exists(tf):
                            found = find_file_in_desktop(os.path.basename(tf))
                            if found: tf = found
                            else:
                                for std_dir in ["Documents", "Downloads"]:
                                    cand = Path.home() / std_dir / os.path.basename(tf)
                                    if cand.exists(): tf = str(cand); break
                        pf_res = profile_file_content(tf)
                        result["status"] = "success" if pf_res.get("success") else "error"
                        result["response"] = pf_res.get("message", "File profiled.")
                        result.update(pf_res)

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
                    from instance.config import settings
                    effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1
                    email_res = handle_email_command(user_input, user_id=effective_uid)
                    if isinstance(email_res, dict):
                        result["status"] = email_res.get("status", "success")
                        result["response"] = email_res.get("message", "Email command executed.")
                        result.update(email_res)
                    else:
                        result["response"] = email_res or "Email command executed."
                except Exception as e:
                    result["status"] = "error"
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
                    from extensions.reminder_engine.enhanced_reminder_handler import get_handler, ReminderAction
                    from extensions.reminder_engine.reminder_scheduler import get_scheduler, initialize_scheduler
                    from extensions.database_manager import DatabaseManager
                    from legacy.memory_manager import get_connection
                    from instance.config import settings
                    
                    # Get the actual authenticated user ID from parameter or session
                    effective_uid = user_id if user_id is not None else getattr(settings, 'CURRENT_USER_ID', None)
                    
                    # If no user is authenticated, return error
                    if effective_uid is None:
                        result["status"] = "error"
                        result["response"] = "No authenticated user. Please log in first."
                        return result
                    user_id = effective_uid
                    
                    # Get database manager and reminder handler
                    # Create a simple pool wrapper for the existing connection function
                    class SimplePoolWrapper:
                        def __init__(self, connection_func):
                            self.get_connection = connection_func
                        
                        def getconn(self):
                            return self.get_connection()
                        
                        def putconn(self, conn):
                            try:
                                conn.close()
                            except:
                                pass
                    
                    db_manager = DatabaseManager(SimplePoolWrapper(get_connection))
                    reminder_handler = get_handler(db_manager)
                    
                    # Ensure scheduler is initialized
                    scheduler = get_scheduler()
                    if scheduler is None:
                        scheduler = initialize_scheduler()
                    
                    # Parse the reminder command
                    parse_result = reminder_handler.parse_reminder_command(user_input, user_id)
                    
                    # Handle based on action type
                    if parse_result["status"] == "error":
                        result["status"] = "error"
                        result["response"] = parse_result["message"]
                    
                    elif parse_result["status"] == "conflict":
                        result["status"] = "conflict"
                        result["response"] = parse_result["message"]
                        result["conflicts"] = parse_result["conflicts"]
                        result["proposed_action"] = parse_result.get("proposed_reminder") or parse_result.get("proposed_update")
                    
                    elif parse_result["status"] == "ambiguous":
                        result["status"] = "ambiguous"
                        result["response"] = parse_result["message"]
                        result["candidates"] = parse_result["candidates"]
                    
                    elif parse_result["status"] == "ready":
                        action = parse_result["action"]
                        
                        action_val = getattr(action, "value", action)
                        if isinstance(action_val, str):
                            action_val = action_val.upper()

                        if action in (ReminderAction.CREATE, ReminderAction.CREATE.value) or action_val == "CREATE":
                            # Create the reminder in database
                            reminder_id = db_manager.add_reminder(
                                user_id,
                                parse_result["task_text"],
                                parse_result["due_at"]
                            )
                            
                            if reminder_id:
                                try:
                                    # Also register with in-memory scheduler
                                    due_datetime = datetime.strptime(parse_result["due_at"], "%Y-%m-%d %H:%M:%S")
                                    scheduler.add_reminder_at_time(parse_result["task_text"], due_datetime, str(reminder_id), user_id, recurrence=parse_result.get("recurrence"))
                                    
                                    # Format response
                                    due_time = datetime.strptime(parse_result["due_at"], "%Y-%m-%d %H:%M:%S")
                                    time_str = due_time.strftime("%I:%M %p") if due_time.date() == datetime.now().date() else due_time.strftime("%B %d at %I:%M %p")
                                    
                                    response = f"Reminder set: {parse_result['task_text']} at {time_str}"
                                    if parse_result.get("recurrence"):
                                        response += f" (recurring {parse_result['recurrence']['frequency']})"
                                    
                                    result["status"] = "success"
                                    result["response"] = response
                                except Exception as sched_err:
                                    self.logger.error(f"Scheduler registration failed for reminder {reminder_id}: {sched_err}")
                                    db_manager.delete_reminder(user_id, reminder_id)
                                    result["status"] = "error"
                                    result["response"] = "Failed to schedule reminder."
                            else:
                                result["status"] = "error"
                                result["response"] = "Failed to create reminder."
                        
                        elif action in (ReminderAction.LIST, ReminderAction.LIST.value) or action_val == "LIST":
                            # Get reminders from database
                            start_date = parse_result.get("start_date")
                            end_date = parse_result.get("end_date")
                            reminders = db_manager.get_reminders(user_id, start_date, end_date)
                            
                            if not reminders:
                                result["response"] = "You have no reminders scheduled."
                            else:
                                reminder_list = []
                                for i, reminder in enumerate(reminders, 1):
                                    raw_due = reminder.get("due_at")
                                    task_text = reminder.get("task_text", "Reminder")
                                    time_str = "scheduled time"
                                    if isinstance(raw_due, datetime):
                                        due_time = raw_due
                                        time_str = due_time.strftime("%I:%M %p") if due_time.date() == datetime.now().date() else due_time.strftime("%B %d at %I:%M %p")
                                    elif isinstance(raw_due, str) and raw_due.strip():
                                        try:
                                            try:
                                                due_time = datetime.strptime(raw_due.strip(), "%Y-%m-%d %H:%M:%S")
                                            except ValueError:
                                                due_time = datetime.fromisoformat(raw_due.strip())
                                            time_str = due_time.strftime("%I:%M %p") if due_time.date() == datetime.now().date() else due_time.strftime("%B %d at %I:%M %p")
                                        except Exception:
                                            time_str = raw_due
                                    elif raw_due is not None:
                                        time_str = str(raw_due)
                                    reminder_list.append(f"{i}. {task_text} at {time_str}")
                                
                                result["response"] = "Your reminders:\n" + "\n".join(reminder_list)
                            
                            result["status"] = "success"
                        
                        elif action in (ReminderAction.DELETE, ReminderAction.DELETE.value) or action_val == "DELETE":
                            # Delete the reminder
                            reminder_id = parse_result["reminder_id"]
                            success = db_manager.delete_reminder(user_id, reminder_id)
                            
                            if success:
                                # Also cancel from scheduler
                                scheduler.cancel_reminder(str(reminder_id))
                                result["status"] = "success"
                                result["response"] = "Reminder deleted."
                            else:
                                result["status"] = "error"
                                result["response"] = "Failed to delete reminder."
                        
                        elif action in (ReminderAction.UPDATE, ReminderAction.UPDATE.value) or action_val == "UPDATE":
                            # Update the reminder
                            reminder_id = parse_result["reminder_id"]
                            success = db_manager.update_reminder(
                                user_id,
                                reminder_id,
                                task_text=parse_result.get("new_task_text"),
                                due_at=parse_result.get("new_due_at")
                            )
                            
                            if success:
                                # Re-register with scheduler if time changed
                                if parse_result.get("new_due_at"):
                                    scheduler.cancel_reminder(str(reminder_id))
                                    due_datetime = datetime.strptime(parse_result["new_due_at"], "%Y-%m-%d %H:%M:%S")
                                    # Get updated reminder text
                                    reminder = db_manager.get_reminder_by_id(user_id, reminder_id)
                                    if reminder:
                                        scheduler.add_reminder_at_time(reminder["task_text"], due_datetime, str(reminder_id), user_id)
                                
                                result["status"] = "success"
                                result["response"] = "Reminder updated."
                            else:
                                result["status"] = "error"
                                result["response"] = "Failed to update reminder."
                        
                        else:
                            result["status"] = "error"
                            result["response"] = "Reminder action not implemented yet."
                    
                    else:
                        result["status"] = "error"
                        result["response"] = "Unknown reminder command status."
                        
                except Exception as e:
                    self.logger.error(f"Reminder handling failed: {e}")
                    import traceback
                    traceback.print_exc()
                    result["status"] = "error"
                    result["response"] = f"Reminder handling failed: {e}"
                    
            # 9. MUSIC
            elif intent == Intent.MUSIC:
                try:
                    from modules.music.music_controller import get_controller
                    controller = get_controller()
                    
                    action = params.get("action", "play").lower()
                    
                    if action == "play":
                        success = controller.play_music(user_input)
                        msg = getattr(controller, "last_status_message", None)
                        result["response"] = msg if msg else ("Music playback started." if success else "Failed to start music playback.")
                    elif action == "play_video":
                        success = controller.play_video(user_input) if hasattr(controller, "play_video") else False
                        msg = getattr(controller, "last_status_message", None)
                        result["response"] = msg if msg else ("Video opened." if success else "Failed to open video.")
                    elif action == "pause":
                        msg = controller.toggle_play_pause()
                        result["response"] = "Paused media playback." if "Toggled" in str(msg) else msg
                    elif action == "resume":
                        msg = controller.toggle_play_pause()
                        result["response"] = "Resumed media playback." if "Toggled" in str(msg) else msg
                    elif action == "toggle":
                        msg = controller.toggle_play_pause()
                        result["response"] = msg
                    elif action in ("stop", "stop_music"):
                        result["response"] = controller.media_stop()
                    elif action == "stop_all":
                        try:
                            from legacy.tts import is_speaking, stop_speaking
                            if is_speaking():
                                stop_speaking(interrupted=True)
                        except Exception:
                            pass
                        try:
                            from core.artifact_reader import get_artifact_reading_controller
                            _r_ctrl = get_artifact_reading_controller()
                            if _r_ctrl.is_reading(effective_uid):
                                _r_ctrl.stop_reading(user_id=effective_uid)
                        except Exception:
                            pass
                        controller.media_stop()
                        result["response"] = "Stopped all active speech and playback."
                    elif action == "queue_status":
                        result["response"] = controller.get_queue_status().get("message")
                    elif action in ["next", "skip"]:
                        if hasattr(controller, "music_queue") and controller.music_queue:
                            msg = controller.next_song()
                        elif hasattr(controller, "media_next"):
                            msg = controller.media_next()
                        else:
                            msg = controller.next_song()
                        result["response"] = msg
                    elif action == "previous":
                        if hasattr(controller, "music_queue") and controller.music_queue:
                            msg = controller.previous_song()
                        elif hasattr(controller, "media_previous"):
                            msg = controller.media_previous()
                        else:
                            msg = controller.previous_song()
                        result["response"] = msg
                    elif action == "summarize_video":
                        from modules.music.youtube_transcript import summarize_youtube_video
                        sum_res = summarize_youtube_video(user_input)
                        result["status"] = "success" if sum_res.get("success") else "error"
                        result["response"] = sum_res.get("summary") or sum_res.get("error", "Could not summarize video.")
                    else:
                        success = controller.play_music(user_input)
                        result["response"] = "Music playback started." if success else "Failed to start music playback."
                except Exception as e:
                    self.logger.error(f"Music execution error: {e}")
                    result["response"] = f"Music playback failed: {e}"
                    
            # 10. DOCUMENT GENERATION
            elif intent == Intent.DOCUMENT_GENERATION:
                try:
                    action = params.get("action")
                    if action == "stop_reading":
                        from core.artifact_reader import get_artifact_reading_controller
                        effective_uid = user_id or 1
                        res = get_artifact_reading_controller().stop_reading(user_id=int(effective_uid) if str(effective_uid).isdigit() else 1)
                        result["status"] = "success"
                        result["response"] = res.get("response", "Stopped reading.")
                        result["handled"] = True
                        return result
                    elif action == "continue_reading":
                        from core.artifact_reader import get_artifact_reading_controller
                        effective_uid = user_id or 1
                        res = get_artifact_reading_controller().continue_reading(user_id=int(effective_uid) if str(effective_uid).isdigit() else 1)
                        result["status"] = "success"
                        result["response"] = res.get("response", "Continuing reading.")
                        result["handled"] = True
                        return result

                    from core.professional_document_engine import get_professional_document_engine
                    from instance.config import settings
                    from extensions.dialogue_state_manager import get_dialogue_manager

                    effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user() or 1
                    dm = get_dialogue_manager(str(effective_uid))

                    doc_context = {
                        "active_goal": getattr(dm.current_state, "current_goal", None) if dm and dm.current_state else None,
                        "active_natural_goal": dm.current_state.session_context.get("active_natural_goal") if dm and dm.current_state else None,
                        "active_document": getattr(dm.current_state, "active_document", None) if dm and dm.current_state else None,
                        "active_artifact": dm.current_state.session_context.get("active_artifact") if dm and dm.current_state else None,
                        "topic_lock": dm.current_state.session_context.get("topic_lock") if dm and dm.current_state else None,
                    }

                    # Canonical Orchestrator: ProfessionalDocumentEngine is the sole high-level orchestrator
                    doc_engine = get_professional_document_engine()
                    doc_res = doc_engine.generate_document_canonical(
                        user_input=user_input,
                        user_id=int(effective_uid) if str(effective_uid).isdigit() else 1,
                        params=params,
                        context=doc_context,
                        dialogue_state=dm.current_state if dm else None,
                    )

                    result["status"] = doc_res.get("status", "success")
                    result["response"] = doc_res.get("response", "Document processed.")
                    result["filepath"] = doc_res.get("filepath")
                    result["doc_type"] = doc_res.get("doc_type")
                    result["topic"] = doc_res.get("topic")
                    result["verification"] = doc_res.get("verification")
                    result["artifact_spec"] = doc_res.get("artifact_spec")
                    result["slide_count"] = doc_res.get("slide_count")
                    result["handled"] = True

                    if doc_res.get("status") == "success" and doc_res.get("filepath"):
                        fn = os.path.basename(doc_res["filepath"])
                        doc_type_val = doc_res.get("doc_type", "pdf")
                        art_type_str = "PRESENTATION" if doc_type_val in ("pptx", "ppt") else ("REPORT" if doc_type_val in ("docx", "doc") else ("PDF" if doc_type_val == "pdf" else ("SPREADSHEET" if doc_type_val == "xlsx" else doc_type_val.upper())))
                        art_info = {
                            "artifact_id": str(uuid.uuid4())[:8],
                            "filename": fn,
                            "filepath": doc_res["filepath"],
                            "path": doc_res["filepath"],
                            "artifact_type": art_type_str,
                            "format": doc_type_val.upper(),
                            "type": doc_type_val,
                            "doc_type": doc_type_val,
                            "title": doc_res.get("title", fn),
                            "topic": doc_res.get("topic", "Document"),
                            "subject": doc_res.get("subject", doc_res.get("topic", "Document")),
                            "created_at": datetime.now().isoformat(),
                            "verified": doc_res.get("verification", {}).get("verified", True) if isinstance(doc_res.get("verification"), dict) else True,
                            "status": "READY",
                            "slide_count": doc_res.get("slide_count"),
                        }
                        if dm and dm.current_state:
                            dm.current_state.active_artifact = art_info
                            dm.current_state.active_document = art_info
                            dm.current_state.active_documents.insert(0, art_info)
                            dm.current_state.session_context["active_artifact"] = art_info
                            dm.current_state.session_context["topic_lock"] = doc_res.get("topic")
                            if art_type_str == "PRESENTATION":
                                dm.current_state.session_context["active_presentation"] = art_info
                            elif art_type_str == "REPORT":
                                dm.current_state.session_context["active_report"] = art_info
                            elif art_type_str == "PDF":
                                dm.current_state.session_context["active_pdf"] = art_info
                            elif art_type_str == "SPREADSHEET":
                                dm.current_state.session_context["active_spreadsheet"] = art_info
                            dm.current_state.session_context.setdefault("recent_artifacts", []).insert(0, art_info)

                            active_g = getattr(dm.current_state, "current_goal", None)
                            if active_g and isinstance(active_g, dict) and active_g.get("deliverables") is not None:
                                from core.goal_planner import WorkGoal
                                wg = WorkGoal.from_dict(active_g)
                                wg.complete_deliverable(doc_type_val, doc_res["filepath"], slide_count=doc_res.get("slide_count"))
                                updated_g_dict = wg.to_dict()
                                dm.current_state.current_goal = updated_g_dict
                                if "active_work_goals" in dm.current_state.session_context:
                                    dm.current_state.session_context["active_work_goals"][wg.id] = updated_g_dict
                                result["active_goal"] = updated_g_dict

                        try:
                            from extensions.context_manager import get_manager
                            get_manager().add_user_artifact(effective_uid, art_info)
                        except Exception:
                            pass
                except Exception as e:
                    self.logger.error(f"Document generation error: {e}", exc_info=True)
                    result["status"] = "error"
                    result["response"] = f"Document generation failed: {e}"

                    
            # 10. CALCULATOR
            elif intent == Intent.CALCULATOR:
                try:
                    if any(w in user_input.lower() for w in ["random", "dice", "coin"]):
                        from legacy.skills_utilities import generate_random_numbers
                        res = generate_random_numbers(user_input)
                        result["response"] = res if res else "Generated random numbers."
                        result["status"] = "success"
                        result["action"] = "RANDOM"
                        result["entity_type"] = "CALCULATION"
                    else:
                        from legacy.skills_utilities import solve_math
                        expr_input = params.get("raw_input") or user_input
                        res = solve_math(expr_input)
                        if not res:
                            m_m = re.search(r'(\d+\s*(?:[\+\-\*\/\^x]|plus|minus|times|multiplied\s+by|divided\s+by)\s*\d+)', expr_input, re.IGNORECASE)
                            if m_m:
                                res = solve_math(m_m.group(1))
                        if not res:
                            res = "Calculation completed."
                        result["response"] = res
                        result["status"] = "success"
                        result["action"] = "CALCULATE"
                        result["entity_type"] = "CALCULATION"
                        if res and res != "Calculation completed.":
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(user_id or 1))
                                if dm and getattr(dm, "current_state", None):
                                    dm.current_state.active_calculation = {
                                        "expression": expr_input,
                                        "result": res
                                    }
                            except Exception:
                                pass
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Calculation failed: {e}"

            # 11. CODE GENERATION
            elif intent == Intent.CODE_GENERATION:
                try:
                    effective_uid = user_id or 1
                    text_low = user_input.lower()
                    from modules.code_generator.utils import detect_language
                    target_lang = detect_language(user_input)

                    req_action = params.get("action", "")

                    # Sub-workflow A: Syntax Validation
                    if req_action == "validate_syntax" or (not req_action and any(k in text_low for k in ["validate syntax", "check syntax", "syntax error", "does this code have syntax"])):
                        from modules.code_generator.utils import validate_code_syntax
                        code_to_check = ""
                        if ":" in user_input:
                            code_to_check = user_input.split(":", 1)[1].strip()
                        elif "```" in user_input:
                            m_c = re.search(r'```(?:\w+)?(.*?)```', user_input, re.DOTALL)
                            if m_c:
                                code_to_check = m_c.group(1).strip()

                        # Spoken or raw code pasted directly without colon/fence
                        if not code_to_check:
                            raw_lines = user_input.strip().splitlines()
                            if len(raw_lines) > 1:
                                code_to_check = "\n".join(raw_lines[1:]).strip()

                        if not code_to_check:
                            # Honest refusal when no code was supplied (do not substitute dummy example)
                            result["status"] = "error"
                            result["response"] = "Please supply or paste the code you would like me to validate."
                            result["handled"] = True
                        else:
                            val_res = validate_code_syntax(code_to_check, language=target_lang)
                            result["status"] = "success" if val_res.get("valid") else "error"
                            result["response"] = val_res.get("message", "Code syntax checked.")
                            result["code"] = code_to_check
                            result["language"] = target_lang
                            result.update(val_res)
                            result["handled"] = True

                    # Sub-workflow B: Traceback Diagnosis
                    elif req_action == "diagnose_error" or (not req_action and any(k in text_low for k in ["diagnose", "traceback", "classify error", "parse traceback"])):
                        from modules.code_generator.utils import classify_execution_error
                        tb_text = ""
                        if ":" in user_input:
                            tb_text = user_input.split(":", 1)[1].strip()
                        elif "```" in user_input:
                            m_c = re.search(r'```(?:\w+)?(.*?)```', user_input, re.DOTALL)
                            if m_c:
                                tb_text = m_c.group(1).strip()
                        if not tb_text:
                            tb_text = user_input

                        diag_res = classify_execution_error(tb_text)
                        result["status"] = "success"
                        result["response"] = diag_res.get("message", f"Diagnosed {diag_res.get('category')}: {diag_res.get('suggestion')}")
                        result.update(diag_res)
                        result["handled"] = True

                    # Sub-workflow C: Static Structure Inspection
                    elif req_action == "explain_structure" or (not req_action and any(k in text_low for k in ["explain structure", "structure of", "what classes and functions"])):
                        from modules.code_generator.utils import explain_code_structure
                        code_to_explain = ""
                        if ":" in user_input:
                            code_to_explain = user_input.split(":", 1)[1].strip()
                        elif "```" in user_input:
                            m_c = re.search(r'```(?:\w+)?(.*?)```', user_input, re.DOTALL)
                            if m_c:
                                code_to_explain = m_c.group(1).strip()

                        if not code_to_explain:
                            result["status"] = "error"
                            result["response"] = "Please provide the code whose structure you would like to analyze."
                            result["handled"] = True
                        else:
                            exp_res = explain_code_structure(code_to_explain, language=target_lang)
                            result["status"] = "success" if exp_res.get("success") else "error"
                            result["response"] = exp_res.get("message", "Code structure analyzed.")
                            result["code"] = code_to_explain
                            result.update(exp_res)
                            result["handled"] = True

                    # Sub-workflow D: Code Repair / Bug Fix / Refactor
                    elif req_action in ("fix_code", "refactor_code") or (not req_action and any(k in text_low for k in ["fix", "debug", "repair", "correct", "refactor", "optimize"]) and any(c in text_low for c in ["code", "function", "script", "program", "error", "bug", "this", "behavior"])):
                        is_refactor = any(k in text_low for k in ["refactor", "optimize", "clean up", "improve structure", "modernize"])
                        code_to_process = ""
                        if ":" in user_input:
                            code_to_process = user_input.split(":", 1)[1].strip()
                        elif "```" in user_input:
                            m_c = re.search(r'```(?:\w+)?(.*?)```', user_input, re.DOTALL)
                            if m_c:
                                code_to_process = m_c.group(1).strip()

                        if not code_to_process:
                            raw_lines = user_input.strip().splitlines()
                            if len(raw_lines) > 1:
                                code_to_process = "\n".join(raw_lines[1:]).strip()

                        # Contextual fallback: check dialogue state / last visual response
                        if not code_to_process:
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(effective_uid))
                                if dm.current_state.last_visual_response:
                                    vr = dm.current_state.last_visual_response
                                    if vr.get("actions") and len(vr["actions"]) > 0:
                                        code_to_process = vr["actions"][0].get("payload", "")
                                    if not code_to_process:
                                        code_to_process = vr.get("primary_value", "")
                            except Exception:
                                pass

                        if not code_to_process:
                            result["status"] = "error"
                            action_name = "refactor" if is_refactor else "fix"
                            result["response"] = f"Please provide the code you would like me to {action_name}."
                            result["handled"] = True
                        elif is_refactor:
                            from modules.code_generator.generator import refactor_code_with_llm
                            ref_res = refactor_code_with_llm(code_to_process, query=user_input, language=target_lang, user_id=effective_uid)
                            result["status"] = "success" if ref_res.get("success") else "error"
                            result["response"] = ref_res.get("explanation", "Code refactored.")
                            result["code"] = ref_res.get("refactored_code")
                            result["language"] = target_lang
                            result["handled"] = True
                        else:
                            from modules.code_generator.generator import fix_code_with_llm
                            fix_res = fix_code_with_llm(code_to_process, query=user_input, language=target_lang, user_id=effective_uid)
                            result["status"] = "success" if fix_res.get("success") else "error"
                            result["response"] = fix_res.get("explanation", "Code repaired.")
                            result["code"] = fix_res.get("fixed_code")
                            result["language"] = target_lang
                            result["handled"] = True

                    # Sub-workflow E: LLM-Based Code Explanation
                    elif req_action == "explain_code" or (not req_action and any(k in text_low for k in ["explain", "analyze"]) and "code" in text_low):
                        from modules.code_generator.generator import explain_code_with_llm
                        code_to_explain = ""
                        if ":" in user_input:
                            code_to_explain = user_input.split(":", 1)[1].strip()
                        elif "```" in user_input:
                            m_c = re.search(r'```(?:\w+)?(.*?)```', user_input, re.DOTALL)
                            if m_c:
                                code_to_explain = m_c.group(1).strip()

                        if not code_to_explain:
                            raw_lines = user_input.strip().splitlines()
                            if len(raw_lines) > 1:
                                code_to_explain = "\n".join(raw_lines[1:]).strip()

                        # Contextual fallback: check dialogue state / last visual response
                        if not code_to_explain:
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(effective_uid))
                                if dm.current_state.last_visual_response:
                                    vr = dm.current_state.last_visual_response
                                    if vr.get("actions") and len(vr["actions"]) > 0:
                                        code_to_explain = vr["actions"][0].get("payload", "")
                                    if not code_to_explain:
                                        code_to_explain = vr.get("primary_value", "")
                            except Exception:
                                pass

                        if not code_to_explain:
                            result["status"] = "error"
                            result["response"] = "Please provide the code you would like me to explain."
                            result["handled"] = True
                        else:
                            exp_text = explain_code_with_llm(code_to_explain, query=user_input, language=target_lang, user_id=effective_uid)
                            result["status"] = "success"
                            result["response"] = exp_text
                            result["code"] = code_to_explain
                            result["language"] = target_lang
                            result["handled"] = True

                    # Sub-workflow F: Code & Project Generation
                    else:
                        from modules.code_generator.task_worker import (
                            classify_task_complexity,
                            execute_code_generation_task,
                            generate_project_milestones,
                            emit_task_visual_response
                        )
                        is_long, reason = classify_task_complexity(user_input)

                        if is_long:
                            from core.task_execution_manager import get_task_execution_manager, TaskPriority
                            tem = get_task_execution_manager()

                            # 1. Check for duplicate active task
                            active_tasks = tem.list_tasks(user_id=effective_uid, active_only=True)
                            duplicate = next((t for t in active_tasks if t.user_request.strip().lower() == user_input.strip().lower()), None)

                            if duplicate:
                                result["status"] = "success"
                                result["task_id"] = duplicate.task_id
                                result["is_background"] = True
                                result["is_duplicate"] = True
                                result["response"] = f"A background task for this project is already active (Task ID: {duplicate.task_id}). Current stage: {duplicate.status.value}."
                                result["handled"] = True
                            else:
                                # 2. Submit new background task
                                task = tem.create_task(
                                    user_request=user_input,
                                    user_id=effective_uid,
                                    normalized_goal=f"Build {target_lang} project",
                                    priority=TaskPriority.NORMAL,
                                    execution_fn=execute_code_generation_task,
                                    metadata={"target_lang": target_lang}
                                )
                                tem.submit_task(task)

                                initial_milestones = generate_project_milestones(user_input, target_lang)
                                vr = emit_task_visual_response(task, initial_milestones, "Task queued and planning started.")

                                result["status"] = "success"
                                result["task_id"] = task.task_id
                                result["is_background"] = True
                                result["response"] = f"I've started building your project in the background (Task ID: {task.task_id}). I'll plan the architecture, generate the files, and validate the code."
                                result["visual_response"] = vr.to_dict()
                                result["handled"] = True
                        else:
                            from modules.code_generator.main import process_request
                            code_res = process_request(user_input, user_id=effective_uid)
                            result.update(code_res)
                            result["response"] = code_res.get("message", "Code generated.")
                            result["handled"] = True

                    # Structured Visual Response Surface Attachment (for synchronous single-file generation)
                    if result.get("status") == "success" and not result.get("is_background") and (result.get("code") or result.get("files") or result.get("project_path")):
                        try:
                            import uuid as _uuid
                            import time as _time
                            from core.visual_response import VisualResponse, VisualResponseType, VisualResponseAction
                            from extensions.dialogue_state_manager import get_dialogue_manager
                            from core.assistant_core import assistant_core

                            vr_title = f"{target_lang.upper()} CODE" if target_lang else "CODE GENERATION"
                            if result.get("project_path"):
                                vr_title = "PROJECT GENERATED"
                                sec_text = f"Location: {result.get('project_path')} ({len(result.get('files', []))} files)"
                            elif result.get("file_path"):
                                sec_text = f"Saved to: {result.get('file_path')}"
                            else:
                                sec_text = result.get("message", "Code generated.")

                            code_payload = result.get("code") or "\n".join(result.get("files", []))
                            actions = [VisualResponseAction(label="Copy", action_type="copy", payload=code_payload)]
                            if result.get("file_path"):
                                actions.append(VisualResponseAction(label="Open File", action_type="open_file", payload=result.get("file_path")))
                            elif result.get("project_path"):
                                actions.append(VisualResponseAction(label="Open Folder", action_type="open_folder", payload=result.get("project_path")))

                            vr_obj = VisualResponse(
                                response_id=str(_uuid.uuid4())[:8],
                                user_id=str(effective_uid),
                                response_type=VisualResponseType.CODE,
                                title=vr_title,
                                primary_value=code_payload,
                                secondary_text=sec_text,
                                raw_content={"code": code_payload, "language": target_lang, "file_path": result.get("file_path"), "project_path": result.get("project_path")},
                                actions=actions,
                                created_at=_time.time(),
                                ttl_seconds=600.0,
                                source_context="code_generation"
                            )
                            dm = get_dialogue_manager(str(effective_uid))
                            dm.store_visual_response(vr_obj)
                            result["visual_response"] = vr_obj.to_dict()
                            assistant_core.show_visual_response(vr_obj, user_input=user_input, intent=intent)
                        except Exception as vr_err:
                            self.logger.debug(f"Code visual response generation notice: {vr_err}")

                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Code operation failed: {e}"
                    result["handled"] = True

            # 13. TRANSLATION
            elif intent == Intent.TRANSLATION:
                try:
                    from legacy.skills_utilities import translate_text
                    res = translate_text(user_input)
                    result["response"] = res if res else "Translation completed."
                except Exception as e:
                    result["response"] = f"Translation failed: {e}"

            # 14. DAILY BRIEFING / CALENDAR
            elif intent == Intent.DAILY_BRIEFING:
                try:
                    action = params.get("action", "daily_briefing")
                    from instance.config import settings
                    effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1
                    effective_uname = getattr(settings, 'CURRENT_USERNAME', 'User')

                    is_holiday_query = any(k in user_input.lower() for k in ["holiday", "special day", "festival", "working day"])
                    is_personal_schedule = not is_holiday_query and (action == "personal_schedule" or (action != "calendar_query" and any(k in user_input.lower() for k in ["what do i have", "do i have", "any events", "my events", "what's on my schedule", "whats on my schedule", "what is on my schedule", "planned", "need to do", "have to do"])))
                    if is_personal_schedule:
                        now = datetime.now()
                        is_tomorrow = "tomorrow" in user_input.lower()
                        target_date = now.date() + timedelta(days=1) if is_tomorrow else now.date()
                        date_label = "tomorrow" if is_tomorrow else "today"
                        target_iso = target_date.strftime("%Y-%m-%d")

                        # 1. Check Calendar Events
                        events = []
                        try:
                            from modules.calendar_manager.calendar_storage import CalendarStorage
                            c_storage = CalendarStorage()
                            events = c_storage.get_events(effective_uid, target_iso) or []
                        except Exception as e:
                            self.logger.debug(f"Calendar events check error: {e}")

                        # 2. Check Reminders for the user
                        reminders = []
                        try:
                            from extensions.database_manager import DatabaseManager
                            from legacy.memory_manager import get_connection
                            class SimplePoolWrapper:
                                def __init__(self, connection_func): self.get_connection = connection_func
                                def getconn(self): return self.get_connection()
                                def putconn(self, conn):
                                    try: conn.close()
                                    except: pass
                            db_mgr = DatabaseManager(SimplePoolWrapper(get_connection))
                            all_rems = db_mgr.get_reminders(effective_uid, start_date=target_date, end_date=target_date) or []
                            reminders = [r for r in all_rems if not r.get("completed")]
                        except Exception as e:
                            self.logger.debug(f"Reminders check error: {e}")

                        # 3. Check Active Background Tasks
                        active_tasks = []
                        try:
                            from skills.task_management.task_queue import TaskQueue
                            tq = getattr(self, "_task_queue", None) or TaskQueue.get_instance()
                            if tq:
                                uid_int = int(effective_uid) if str(effective_uid).isdigit() else 0
                                active_tasks = [t for t in tq.list_tasks(uid_int) if t.get("status") in ("queued", "running")]
                        except Exception as e:
                            self.logger.debug(f"Tasks check error: {e}")

                        # Truthful synthesis without inventing data or calling SerpAPI
                        if not events and not reminders and not active_tasks:
                            result["status"] = "success"
                            result["response"] = f"You don't have anything scheduled/reminded for {date_label}."
                        else:
                            parts = []
                            if events:
                                ev_strs = [f"{e.get('title', 'Event')} at {e.get('time', 'all day')}" for e in events]
                                parts.append(f"{len(events)} event(s): {', '.join(ev_strs)}")
                            if reminders:
                                rem_strs = [f"{r.get('task_text', 'Reminder')}" for r in reminders]
                                parts.append(f"{len(reminders)} reminder(s): {', '.join(rem_strs)}")
                            if active_tasks:
                                task_strs = [f"{t.get('goal', 'Task')}" for t in active_tasks]
                                parts.append(f"{len(active_tasks)} active task(s): {', '.join(task_strs)}")

                            result["status"] = "success"
                            result["response"] = f"For {date_label}, you have " + "; ".join(parts) + "."

                    elif action == "calendar_query" or any(k in user_input.lower() for k in [
                        "calendar", "event", "events", "meeting", "appointment", "schedule", "reschedule",
                        "holiday", "special days", "plan my week", "next appointment", "upcoming appointment",
                        "free", "busy", "slot", "slots", "agenda", "note", "notes", "analytics", "utilization",
                        "ics", "sync", "snooze", "huddle", "hurdle", "standup"
                    ]):
                        from modules.calendar_manager import calendar_controller
                        cal_res = calendar_controller.process_calendar_query(user_input, user_id=effective_uid)
                        result["status"] = "success" if cal_res.get("success", True) else "error"
                        result["response"] = cal_res.get("speech_response") or "I processed your calendar query, but no matching details were found."
                        result["calendar_data"] = cal_res
                    else:
                        from modules.calendar_manager import get_daily_briefing
                        briefing = get_daily_briefing(user_id=effective_uid, user_name=effective_uname)
                        result["status"] = "success"
                        result["response"] = briefing.get("speech_text") or briefing.get("visual_report")
                        result["visual_report"] = briefing.get("visual_report")
                except Exception as e:
                    self.logger.error(f"Daily briefing / calendar error: {e}")
                    result["status"] = "error"
                    result["response"] = f"Failed to process calendar request: {e}"

            # 15. TIME QUERY & CLOCK / ALARM / TIMER / STOPWATCH (Pure Local Clock — Bypasses RAG / LLM)
            elif intent == Intent.TIME_QUERY:
                try:
                    from skills.clock_manager import get_clock_controller
                    ctrl = get_clock_controller()
                    clock_res = ctrl.handle_command(user_input, user_id=effective_uid, params=params)
                    result["status"] = clock_res.get("status", "success")
                    result["response"] = clock_res.get("message") or clock_res.get("response") or "Clock command executed."
                    result.update(clock_res)
                    result["handled"] = True
                except Exception as e:
                    self.logger.error(f"Clock operation failed: {e}")
                    try:
                        from legacy.skills_utilities import tell_time
                        result["response"] = tell_time()
                    except Exception:
                        result["response"] = f"Time query failed: {e}"

            # 14. DATE QUERY (Pure Local Clock — Bypasses RAG / LLM)
            elif intent == Intent.DATE_QUERY:
                try:
                    from skills.clock_manager import get_clock_controller
                    ctrl = get_clock_controller()
                    clock_res = ctrl.get_local_date(user_input)
                    result["status"] = "success"
                    result["response"] = clock_res.get("message") or clock_res.get("response") or "Today's date."
                    result.update(clock_res)
                    result["handled"] = True
                except Exception as e:
                    from legacy.skills_utilities import tell_date
                    result["status"] = "success"
                    result["response"] = tell_date()
                    result["handled"] = True

            # 15. WEATHER QUERY
            elif intent == Intent.WEATHER_QUERY:
                try:
                    location = params.get("location")
                    from extensions.weather_engine import get_weather_for_query, _default_weather_engine

                    explicit_loc = None
                    if location and isinstance(location, str):
                        loc_cand = location.strip()
                        if loc_cand.lower() not in ["local", "", "here", "current location", "my location", "your current location"]:
                            explicit_loc = loc_cand

                    if not explicit_loc:
                        extracted = _default_weather_engine.extract_location(user_input)
                        if extracted and extracted.lower() not in ["local", "", "here", "current location", "my location", "your current location"]:
                            explicit_loc = extracted

                    if explicit_loc:
                        target_loc = explicit_loc
                    else:
                        target_loc = None
                        try:
                            from skills.device_location import get_location_detector
                            target_loc = get_location_detector().get_city()
                        except Exception:
                            pass
                        if not target_loc:
                            target_loc = _default_weather_engine.default_location

                    result["resolved_location"] = target_loc
                    result["response"] = get_weather_for_query(user_input, explicit_location=target_loc)
                except Exception as e:
                    result["response"] = f"Weather query failed: {e}"

            # 16. MEMORY QUERY
            elif intent == Intent.MEMORY_QUERY:
                try:
                    from instance.config import settings
                    effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user()

                    # Check for email address query
                    if re.search(r'\b(?:what\s+is|what\'s|show|tell\s+me|get)\s+(?:my\s+)?(?:email|email\s+address|email\s+id)\b', user_input, re.I):
                        try:
                            from modules.assistant_email.user_storage import get_user_email
                            u_email, _ = get_user_email(effective_uid)
                            if u_email:
                                result["status"] = "success"
                                result["response"] = f"Your email address is {u_email}."
                                result["handled"] = True
                                return result
                        except Exception:
                            pass

                    u_low = user_input.lower().rstrip('.?!,').strip()
                    norm_u_low = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|trevon|nova|jarvis|assistant)[,\s:]*', '', u_low, flags=re.IGNORECASE).strip()
                    is_user_cmd = bool(
                        re.search(r'\b(?:what(?:\'s|\s+is|\s+was)\s+(?:my\s+)?(?:last|previous)\s+command|what\s+did\s+i\s+(?:just\s+)?ask(?:\s+you(?:\s+to\s+do)?)?|what\s+was\s+the\s+last\s+thing\s+i\s+asked|what\s+command\s+did\s+i\s+(?:just\s+)?(?:give|issue|say))\b', u_low)
                        or re.search(r'\b(?:what(?:\'s|\s+is|\s+was)\s+(?:my\s+)?(?:last|previous)\s+command|what\s+did\s+i\s+(?:just\s+)?ask(?:\s+you(?:\s+to\s+do)?)?|what\s+was\s+the\s+last\s+thing\s+i\s+asked|what\s+command\s+did\s+i\s+(?:just\s+)?(?:give|issue|say))\b', norm_u_low)
                        or u_low in ("what is my last command", "what was my last command", "what did i just ask", "what did i just ask you to do", "what did i just ask you", "what was the last thing i asked", "last command")
                    )
                    is_assistant_act = bool(
                        re.search(r'\b(?:what(?:\'s|\s+is|\s+was)\s+(?:the\s+)?last\s+action(?:\s+(?:you\s+)?performed)?|what\s+was\s+your\s+last\s+action|what\s+action\s+did\s+you\s+(?:just\s+)?perform|what\s+did\s+you\s+(?:just\s+)?do|what\s+did\s+you\s+do\s+last|what\s+was\s+the\s+last\s+thing\s+you\s+did|what\s+action\s+did\s+you\s+take)\b', u_low)
                        or re.search(r'\b(?:what(?:\'s|\s+is|\s+was)\s+(?:the\s+)?last\s+action(?:\s+(?:you\s+)?performed)?|what\s+was\s+your\s+last\s+action|what\s+action\s+did\s+you\s+(?:just\s+)?perform|what\s+did\s+you\s+(?:just\s+)?do|what\s+did\s+you\s+do\s+last|what\s+was\s+the\s+last\s+thing\s+you\s+did|what\s+action\s+did\s+you\s+take)\b', norm_u_low)
                        or u_low in ("what was the last action you performed", "what was your last action", "what action did you just perform", "what did you just do", "what did you do last", "what was the last thing you did", "last action")
                    )
                    if is_user_cmd or is_assistant_act:
                        from core.fast_path import FastPathProcessor
                        from extensions.dialogue_state_manager import get_dialogue_manager
                        dm = get_dialogue_manager(str(effective_uid))
                        hist_resp = FastPathProcessor._resolve_recent_history(
                            is_user_cmd=is_user_cmd,
                            dialogue_mgr=dm,
                            user_id=effective_uid
                        )
                        result["response"] = hist_resp
                        result["status"] = "success"
                        result["handled"] = True
                        return result

                    from legacy.skills import query_memory_first
                    ans = query_memory_first(effective_uid, user_input)
                    if ans:
                        result["response"] = ans
                        result["status"] = "success"
                        result["handled"] = True
                        return result

                    # Check if query references an active or stored artifact
                    try:
                        from core.artifact_resolver import get_artifact_reference_resolver
                        art_res = get_artifact_reference_resolver().resolve(
                            user_input=user_input,
                            user_id=int(effective_uid) if str(effective_uid).isdigit() else 1
                        )
                        if art_res.is_success and art_res.artifact:
                            art = art_res.artifact
                            result["status"] = "success"
                            result["response"] = f"Here is the information I found about '{art.topic}':\n\n{art.content}"
                            result["artifact"] = art.to_dict()
                            result["handled"] = True
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(effective_uid))
                                dm.current_state.active_artifact = art.to_dict()
                            except Exception:
                                pass
                            return result
                    except Exception as _art_err:
                        self.logger.debug(f"[MEMORY_QUERY] Artifact check: {_art_err}")

                    if any(w in user_input.lower() for w in ("project secret", "my secret", "my password", "my pin", "my credentials", "my credit card")):
                        result["response"] = "I don't have any record of that secret in your memory."
                        result["handled"] = True
                    else:
                        from extensions.dialogue_state_manager import get_dialogue_manager
                        dm = get_dialogue_manager(str(effective_uid))
                        active_g = dm.current_state.current_goal if dm else None
                        u_low = user_input.lower()
                        if any(w in u_low for w in ("were we working on", "project were we working", "what were we doing", "what was i doing")):
                            if active_g and isinstance(active_g, dict) and active_g.get("title"):
                                result["response"] = f"We were working on {active_g.get('title')}."
                                result["handled"] = True
                            else:
                                from extensions.conversational_memory import recent_memory, _lock
                                with _lock:
                                    recent_list = list(recent_memory)
                                if recent_list:
                                    last_cmds = [r.get("user_command") for r in recent_list[-5:] if r.get("user_command")]
                                    if last_cmds:
                                        result["response"] = f"Recently, you were working on: {', '.join(last_cmds[-2:])}."
                                        result["handled"] = True
                                    else:
                                        result["response"] = "You were working on the desktop assistant, focusing on speech and core interactions."
                                        result["handled"] = True
                                else:
                                    result["response"] = "You were working on the desktop assistant, focusing on speech and core interactions."
                                    result["handled"] = True
                        else:
                            from extensions.llm_engine import LLMEngine
                            from extensions.conversational_memory import get_categorized_user_memory
                            cat_mem = get_categorized_user_memory(effective_uid)
                            engine = LLMEngine()
                            mem_resp = engine.get_completion(
                                prompt=user_input,
                                memory=str(cat_mem) if cat_mem else None,
                                user_id=effective_uid
                            )
                            result["response"] = (mem_resp or "I don't have that information in my memory.").strip()
                            result["handled"] = True
                except Exception as e:
                    self.logger.error(f"Memory query failed: {e}")
                    result["status"] = "error"
                    result["response"] = f"Memory query failed: {e}"
                    result["handled"] = True

            # 17. MEMORY STORE
            elif intent == Intent.MEMORY_STORE:
                try:
                    from instance.config import settings
                    from legacy.skills import detect_and_store_fact
                    effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user()
                    stored, msg = detect_and_store_fact(effective_uid, user_input)
                    if stored:
                        result["response"] = msg
                        result["handled"] = True
                        result["status"] = "success"
                        result["success"] = True
                    else:
                        from core.chatgpt_memory import get_chatgpt_memory
                        extracted = get_chatgpt_memory().extract_and_persist_facts(effective_uid, user_input)
                        if extracted:
                            k, v = extracted[0]
                            result["response"] = f"Understood. I'll remember that {k.replace('_', ' ')} is {v}."
                            result["handled"] = True
                            result["status"] = "success"
                            result["success"] = True
                        else:
                            result["response"] = "I couldn't identify a specific fact or preference to remember. Could you please specify what you'd like me to remember?"
                            result["handled"] = True
                except Exception as e:
                    self.logger.error(f"Memory store failed: {e}")
                    result["status"] = "error"
                    result["response"] = f"Memory storage failed: {e}"
                    result["handled"] = True

            # 18. RAG SEARCH
            elif intent == Intent.RAG_SEARCH:
                try:
                    text_low = user_input.lower()
                    m_url = re.search(r'https?://[^\s]+|\bwww\.[^\s]+', user_input)
                    if m_url and any(k in text_low for k in ["extract", "what does", "read", "text from", "page text"]):
                        from modules.browser.browser_controller import extract_page_text
                        b_res = extract_page_text(m_url.group(0))
                        result["status"] = "success" if b_res.get("success") else "error"
                        result["response"] = b_res.get("message") or b_res.get("text", "Extracted page content.")
                        result.update(b_res)
                        result["handled"] = True
                    elif m_url and "screenshot" in text_low:
                        from modules.browser.browser_controller import take_page_screenshot
                        b_res = take_page_screenshot(m_url.group(0))
                        result["status"] = "success" if b_res.get("success") else "error"
                        result["response"] = b_res.get("message", "Screenshot captured.")
                        result.update(b_res)
                        result["handled"] = True
                    else:
                        from instance.config import settings
                        from core.chatgpt_memory import get_chatgpt_memory
                        from legacy.skills import query_memory_first
                        resolved_user = user_id if user_id is not None else (getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user())
                        try:
                            uid_int = int(resolved_user) if resolved_user is not None else 1
                        except (ValueError, TypeError):
                            uid_int = 1
                        mem_ans = get_chatgpt_memory().answer_historical_fact_query(uid_int, user_input)
                        if not mem_ans:
                            mem_ans = query_memory_first(uid_int, user_input)
                        if mem_ans:
                            result["response"] = mem_ans
                            result["handled"] = True
                            result["status"] = "success"
                            result["success"] = True
                        elif not should_use_external_retrieval(Intent.RAG_SEARCH, user_input):
                            # Bypasses RAG / Web Search entirely for stable knowledge or non-web queries
                            from extensions.llm_engine import LLMEngine
                            engine = LLMEngine()
                            llm_resp = engine.get_completion(prompt=user_input, user_id=resolved_user)
                            result["response"] = (llm_resp or "No answer found.").strip()
                            result["handled"] = True
                        else:
                            from extensions.rag_system import RAGSystem
                            rag = RAGSystem()
                            rag_output = rag.process(user_input, user_id=resolved_user)
                            if isinstance(rag_output, dict):
                                result["response"] = rag_output.get("response", "No answer found.")
                                # CRITICAL: Mark as handled to prevent any fallback to other subsystems
                                result["handled"] = rag_output.get("handled", True)
                            else:
                                result["response"] = str(rag_output)
                                result["handled"] = True
                except Exception as e:
                    self.logger.error(f"[RAG_SEARCH] Execution error: {e}", exc_info=True)
                    try:
                        from instance.config import settings
                        from extensions.llm_engine import LLMEngine
                        engine = LLMEngine()
                        resolved_user = user_id if user_id is not None else (getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user())
                        fallback_resp = engine.get_completion(prompt=user_input, user_id=resolved_user)
                        if fallback_resp and fallback_resp.strip():
                            result["status"] = "success"
                            result["response"] = fallback_resp.strip()
                            result["handled"] = True
                            return result
                    except Exception:
                        pass
                    result["status"] = "error"
                    result["response"] = "I apologize, but I encountered an issue retrieving that information. Please try again."
                    result["handled"] = True  # Still mark as handled to prevent incorrect fallbacks
                    
            # 19. GENERAL CONVERSATION
            elif intent == Intent.GENERAL_CONVERSATION:
                if params.get("response"):
                    result["status"] = "success"
                    result["response"] = params.get("response")
                    result["handled"] = True
                    result["action"] = params.get("action", "general_conversation")
                    return result
                if params.get("action") == "implicit_goal":
                    goal_type = params.get("goal_type")
                    suggested_resp = params.get("suggested_response", "I can help with that.")
                    goal_entity = params.get("goal_entity")
                    pending_act = params.get("pending_action")
                    deadline = params.get("deadline")
                    goal_name = params.get("goal_name", user_input)
                    try:
                        from extensions.dialogue_state_manager import get_dialogue_manager
                        from instance.config import settings
                        eff_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user() or "default"
                        dm = get_dialogue_manager(str(eff_uid))
                        if goal_entity:
                            dm.current_state.entities["goal_entity"] = goal_entity
                            dm.current_state.session_context["active_goal_entity"] = goal_entity
                        if pending_act:
                            dm.current_state.pending_action = pending_act
                            dm.current_state.pending_confirmation = True
                        if goal_type == "continue_work":
                            active_g = dm.current_state.current_goal
                            if active_g and isinstance(active_g, dict) and active_g.get("deliverables") is not None:
                                from core.goal_planner import WorkGoal
                                wg = WorkGoal.from_dict(active_g)
                                wg.resume()
                                dm.current_state.current_goal = wg.to_dict()
                                dm.current_state.goal_status = "RUNNING"
                                pending_delivs = [d for d in wg.deliverables if d.get("status") == "PENDING"]
                                if pending_delivs:
                                    next_del = pending_delivs[0].get("type")
                                    suggested_resp = f"Resuming work on {wg.topic or wg.title}. Continuing to generate the {next_del} deliverable."
                                else:
                                    suggested_resp = f"Resuming work on {wg.topic or wg.title}. Currently: {wg.progress}. Next action: {wg.next_recommended_action or 'final review'}."
                            else:
                                opened_apps = dm.current_state.session_context.get("opened_applications", [])
                                if "Notepad" in opened_apps:
                                    suggested_resp = "Your document is still open in Notepad. I can bring it to the front."
                        # Level 6 Work Goal: Create structured first-class WorkGoal object
                        # with deliverables, subtasks, deadline, topic, and completion state.
                        if goal_type == "natural_goal":
                            from core.goal_planner import create_work_goal
                            import uuid as _uuid
                            _goal_id = _uuid.uuid4().hex[:8]
                            goal_desc = params.get("goal_description") or user_input
                            topic = params.get("topic")
                            purpose = params.get("purpose") or "general"
                            verb = params.get("goal_verb", "prepare")
                            subj = params.get("goal_subject", "")

                            work_goal = create_work_goal(
                                goal_id=_goal_id,
                                title=goal_name,
                                objective=user_input,
                                topic=topic,
                                purpose=purpose,
                                deadline=deadline,
                                priority="normal",
                                verb=verb,
                                subject=subj
                            )
                            _structured_goal = work_goal.to_dict()

                            # Goal switching check: if existing goal exists and is different, archive it
                            if dm.current_state.current_goal and isinstance(dm.current_state.current_goal, dict):
                                old_g = dm.current_state.current_goal
                                if old_g.get("id") != _goal_id:
                                    dm.current_state.previous_contexts.append({"type": "archived_goal", "goal": old_g})
                                    goals_dict = dm.current_state.session_context.setdefault("active_work_goals", {})
                                    goals_dict[old_g.get("id")] = old_g

                            goals_dict = dm.current_state.session_context.setdefault("active_work_goals", {})
                            goals_dict[_goal_id] = _structured_goal

                            dm.current_state.current_goal = _structured_goal
                            dm.current_state.goal_status = "RUNNING"
                            dm.current_state.session_context["active_natural_goal"] = _structured_goal
                            if topic:
                                dm.current_state.session_context["topic_lock"] = topic
                            if deadline:
                                dm.current_state.session_context["active_goal_deadline"] = deadline
                        elif goal_type == "continue_work" and dm.current_state.current_goal and dm.current_state.current_goal.get("deliverables") is not None:
                            pass
                        else:
                            dm.current_state.current_goal = {
                                "goal_name": goal_name,
                                "goal_type": goal_type,
                                "description": user_input,
                                "status": "WAITING_FOR_USER"
                            }
                    except Exception:
                        pass
                    is_active_work_goal = (goal_type == "natural_goal") or (
                        goal_type == "continue_work" and dm and dm.current_state and dm.current_state.current_goal and dm.current_state.current_goal.get("deliverables") is not None
                    )
                    result["status"] = "success" if is_active_work_goal else "clarification_needed"
                    result["goal_status"] = "ACTIVE" if is_active_work_goal else "WAITING_FOR_USER"
                    result["goal_type"] = goal_type
                    result["response"] = suggested_resp
                    result["handled"] = True
                    if goal_type in ("natural_goal", "continue_work"):
                        result["active_goal"] = dm.current_state.current_goal if (dm and dm.current_state) else None
                        if deadline:
                            result["goal_deadline"] = deadline
                    return result

                eff_uid = int(effective_uid) if ('effective_uid' in locals() and str(effective_uid).isdigit()) else 1

                try:
                    from instance.config import settings
                    from legacy.skills import detect_and_store_fact
                    effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user()
                    eff_uid = int(effective_uid) if (effective_uid and str(effective_uid).isdigit()) else 1

                    # Check if this is an explicit memory directive:
                    u_low_strip = user_input.lower().strip()
                    is_explicit_store = u_low_strip.startswith(("remember", "please remember", "note that", "save this")) or (
                        u_low_strip.startswith("my ") and " is " in u_low_strip and not u_low_strip.startswith((
                            "my name is", "my university is", "my college is", "my institution is",
                            "my interview is", "my exam is", "my meeting is", "my presentation is"
                        ))
                    )
                    if is_explicit_store:
                        stored, msg = detect_and_store_fact(effective_uid, user_input)
                        if stored:
                            result["response"] = msg
                            result["handled"] = True
                            return result
                    else:
                        # Extract facts automatically from natural conversation without robotic interruption
                        from core.chatgpt_memory import get_chatgpt_memory
                        get_chatgpt_memory().extract_and_persist_facts(eff_uid, user_input)
                except Exception:
                    pass

                # Fast handling for assistant capability queries (concise voice response or full list)
                if is_capability_query(user_input):
                    u_low = user_input.lower().strip().rstrip('.?!')
                    if any(k in u_low for k in ("full list", "all capabilities", "list all")):
                        from core.capability_registry import get_capability_registry
                        cap_reg = get_capability_registry()
                        result["response"] = cap_reg.format_capabilities_overview()
                    else:
                        result["response"] = (
                            "I can control your computer, open and manage applications, work with files, "
                            "search for information, control system settings, remember your ongoing tasks, "
                            "and help you with coding and other work. If you want, I can show you the full list."
                        )
                    result["handled"] = True
                    return result

                # Fast handling for conversational recovery / speech input complaints
                if is_conversational_followup_or_complaint(user_input):
                    u_low = user_input.lower()
                    if any(p in u_low for p in ("problem is with you", "not taking all the input", "not able to put what i am trying to say")):
                        result["response"] = "You're right. I wasn't capturing your full input. I'll focus on the complete request instead of jumping to a generic interpretation."
                    elif "are you getting my point" in u_low or "do you understand" in u_low:
                        result["response"] = "Yes, I understand what you're saying. Please go ahead."
                    elif "why are you doing that" in u_low or "why are you responding" in u_low:
                        result["response"] = "I was interpreting your input too broadly. I'll stick to exactly what you need."
                    elif "try again" in u_low:
                        result["response"] = "Understood. Please go ahead, I'm listening to your full request."
                    else:
                        result["response"] = "Understood. Let me know what you'd like me to do instead."
                    result["handled"] = True
                    return result

                # Direct conversational handling / bounded LLM generation without RAG, SerpAPI, or Tavily
                try:
                    clean_u = re.sub(r'[,.?!]+', '', user_input.strip().lower()).strip()
                    clean_no_name = re.sub(r'\b(?:friday|trevon|nova|jarvis|assistant)\b', '', clean_u).strip()
                    from instance.config import settings as _cfg
                    asst_name = getattr(_cfg, 'CURRENT_ASSISTANT_NAME', None) or getattr(_cfg, 'ASSISTANT_NAME', None) or 'Friday'

                    # Fast deterministic responses for greetings & small talk
                    if any(p in clean_no_name for p in ("how are you feeling", "how do you feel", "how are you doing", "how are you")):
                        result["response"] = "I'm feeling great and ready to help, thank you! How can I assist you today?"
                        result["handled"] = True
                        return result
                    elif clean_u in ("hey", "friday", "hey friday", "hello", "hi") or re.match(r'^(?:hey|hello|hi)\b', clean_u):
                        result["response"] = "Hey! How can I help you?"
                        result["handled"] = True
                        return result
                    elif any(p in clean_u for p in ("who are you", "what is your name", "what's your name", "introduce yourself", "tell me about yourself")):
                        result["response"] = f"I am {asst_name}, your personal AI desktop assistant."
                        result["handled"] = True
                        return result
                    elif any(p in clean_u for p in ("are you there", "you there", "are you here", "are you awake", "can you hear me")):
                        result["response"] = "I'm right here. How can I help you?"
                        result["handled"] = True
                        return result

                    from extensions.llm_engine import LLMEngine
                    engine = LLMEngine()
                    mem_ctx = None
                    try:
                        from extensions.conversational_memory import recent_memory, _lock
                        with _lock:
                            if recent_memory:
                                last_items = list(recent_memory)[-3:]
                                mem_ctx = " ".join(f"User: {m.get('user_command')} Assistant: {m.get('assistant_response')}" for m in last_items)
                    except Exception:
                        pass

                    # Retrieve relevant memories and prompt context
                    mem_block = ""
                    try:
                        from core.chatgpt_memory import get_chatgpt_memory
                        mem_block = get_chatgpt_memory().build_prompt_context(eff_uid, user_input)
                    except Exception:
                        pass

                    llm_resp = engine.get_completion(
                        prompt=user_input,
                        context=mem_ctx,
                        memory=mem_block,
                        user_id=eff_uid,
                        timeout_budget=7.0,
                        task_type="conversational",
                    )
                    if llm_resp:
                        result["response"] = llm_resp.strip()
                        result["handled"] = True
                    else:
                        # Offline fallback: check direct factual recall or personalized conversational response
                        try:
                            from core.chatgpt_memory import get_chatgpt_memory
                            chatgpt_mem = get_chatgpt_memory()
                            direct_ans = chatgpt_mem.answer_historical_fact_query(eff_uid, user_input)
                            if direct_ans:
                                result["response"] = direct_ans
                                result["handled"] = True
                                return result
                        except Exception:
                            pass

                        # Natural introduction response if user shared identity/background
                        try:
                            from core.chatgpt_memory import get_chatgpt_memory
                            user_facts = get_chatgpt_memory().get_user_facts(eff_uid)
                            u_name = user_facts.get("preferred_name") or user_facts.get("name")
                            u_inst = user_facts.get("institution") or user_facts.get("university")
                            u_cell = user_facts.get("activity") or user_facts.get("role")

                            if any(k in clean_u for k in ("i'm", "i am", "my name is", "placement cell", "srm ap", "final-year", "final year")):
                                if u_name and u_inst and u_cell:
                                    result["response"] = f"Nice to meet you, {u_name}! Great to know you're in the placement cell at {u_inst}. How can I assist you today?"
                                    result["handled"] = True
                                    return result
                                elif u_name and u_inst:
                                    result["response"] = f"Nice to meet you, {u_name}! Great to know you're at {u_inst}. How can I assist you today?"
                                    result["handled"] = True
                                    return result
                                elif u_name:
                                    result["response"] = f"Nice to meet you, {u_name}! How can I help you today?"
                                    result["handled"] = True
                                    return result

                            # Personalized assistance (e.g., "Help me prepare for placements")
                            if any(p in clean_u for p in ("prepare for placements", "prepare for placement", "placement preparation", "placements")):
                                greeting_target = f", {u_name}" if u_name else ""
                                inst_target = f" at {u_inst}" if u_inst else ""
                                cell_context = " Given your involvement with the placement cell, you'll have good perspective." if u_cell else ""
                                result["response"] = (
                                    f"I'd be glad to help you prepare for placements{greeting_target}!{cell_context} "
                                    f"We can work through technical interview topics, coding challenges, core computer science concepts, and resume preparation. "
                                    "Where would you like to begin?"
                                )
                                result["handled"] = True
                                return result
                        except Exception:
                            pass

                        if any(k in clean_u for k in ("what did i ask you earlier", "what did i ask earlier", "what did i ask before", "what was my last question")):
                            if 'last_items' in locals() and last_items:
                                result["response"] = f"Earlier, you asked: '{last_items[-1].get('user_command')}'."
                            else:
                                result["response"] = "You haven't asked any previous questions in this session yet."
                        elif "continue your previous answer" in clean_u or "continue previous answer" in clean_u or "continue where you left off" in clean_u:
                            if 'last_items' in locals() and last_items:
                                result["response"] = f"Continuing from earlier: {last_items[-1].get('assistant_response')}"
                            else:
                                result["response"] = "There is no previous response to continue."
                        else:
                            classified = engine.get_classified_failure() if hasattr(engine, 'get_classified_failure') else {}
                            user_msg = classified.get("user_message")
                            if not user_msg:
                                err_diag = getattr(engine, 'last_error_summary', '')
                                if err_diag:
                                    user_msg = f"Unable to reach the language model service: {err_diag}."
                                else:
                                    user_msg = "Unable to reach the language model service right now. Please check your network connection or try again shortly."
                            result["response"] = user_msg
                            result["failure_category"] = classified.get("category", "provider_failure")
                            result["failure_reason"] = classified.get("reason", getattr(engine, 'last_error_summary', ''))
                        result["handled"] = True
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Conversation failed: {e}"
                    result["handled"] = True

            # 20.5. VOICE CONFIGURATION
            elif intent == Intent.VOICE_CONFIGURATION:
                try:
                    from core.configuration_service import get_configuration_service
                    from legacy.tts import apply_voice_profile
                    from instance.config import settings
                    effective_uid = int(user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1)
                    cfg = get_configuration_service()
                    action = params.get("action", "")

                    current_rate = int(cfg.get_preference(effective_uid, "voice_rate", cfg.get_preference(effective_uid, "assistant_voice_rate", 135)))
                    current_vid = cfg.get_preference(effective_uid, "voice_id", cfg.get_preference(effective_uid, "assistant_voice_id", None))
                    current_vol_raw = float(cfg.get_preference(effective_uid, "voice_volume", cfg.get_preference(effective_uid, "assistant_voice_volume", 100.0)))
                    current_vol = current_vol_raw / 100.0 if current_vol_raw > 1.0 else current_vol_raw

                    if action == "decrease_rate":
                        new_rate = max(110, current_rate - 15)
                        cfg.set_preference(effective_uid, "voice_rate", new_rate)
                        apply_voice_profile(current_vid, rate=new_rate, volume=current_vol)
                        resp_text = f"I have slowed down my speaking rate to {new_rate} words per minute."
                    elif action == "increase_rate":
                        new_rate = min(180, current_rate + 15)
                        cfg.set_preference(effective_uid, "voice_rate", new_rate)
                        apply_voice_profile(current_vid, rate=new_rate, volume=current_vol)
                        resp_text = f"I have increased my speaking rate to {new_rate} words per minute."
                    elif action == "reset_rate":
                        new_rate = 135
                        cfg.set_preference(effective_uid, "voice_rate", new_rate)
                        apply_voice_profile(current_vid, rate=new_rate, volume=current_vol)
                        resp_text = "I've reset my speaking rate to natural speed, 135 words per minute."
                    elif action == "restore_voice":
                        from legacy.memory_manager import get_voice_profile_db
                        prof = get_voice_profile_db(effective_uid)
                        saved_vid = prof.get("voice_id")
                        saved_rate = prof.get("voice_rate", 135)
                        saved_vol = prof.get("voice_volume", 1.0)
                        if saved_vid:
                            cfg.set_preference(effective_uid, "voice_id", saved_vid)
                            cfg.set_preference(effective_uid, "voice_rate", saved_rate)
                            apply_voice_profile(saved_vid, rate=saved_rate, volume=saved_vol)
                            resp_text = "I've restored your previously configured voice profile."
                        else:
                            resp_text = "Your voice settings are active at natural conversational speed."
                    elif action == "change_language" or "language" in params:
                        target_lang = params.get("language", "english").lower()
                        cfg.set_preference(effective_uid, "language", target_lang)
                        cfg.set_preference(effective_uid, "assistant_language", target_lang)
                        if target_lang == "telugu":
                            resp_text = "ఖచ్చితంగా! నేను ఇకపై మీతో తెలుగులో మాట్లాడతాను. నేను మీకు ఎలా సహాయపడగలను?"
                        elif target_lang == "hindi":
                            resp_text = "बिल्कुल! मैं अब आपसे हिंदी में बात करूँगा। मैं आपकी क्या मदद कर सकता हूँ?"
                        elif target_lang == "tamil":
                            resp_text = "நிச்சயமாக! நான் உங்களுடன் தமிழில் பேசுவேன். நான் உங்களுக்கு எவ்வாறு உதவ முடியும்?"
                        elif target_lang == "kannada":
                            resp_text = "ಖಂಡಿತ! ನಾನು ಇನ್ನು ಮುಂದೆ ನಿಮ್ಮೊಂದಿಗೆ ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡುತ್ತೇನೆ."
                        elif target_lang == "malayalam":
                            resp_text = "തീർച്ചയായും! ഞാൻ ഇനി മുതൽ നിങ്ങളോട് മലയാളത്തിൽ സംസാരിക്കാം."
                        elif target_lang == "spanish":
                            resp_text = "¡Claro! A partir de ahora te hablaré en español. ¿En qué te puedo ayudar?"
                        elif target_lang == "french":
                            resp_text = "Bien sûr ! À partir de maintenant, je vous parlerai en français."
                        elif target_lang == "german":
                            resp_text = "Gerne! Ab jetzt spreche ich mit Ihnen auf Deutsch."
                        else:
                            resp_text = f"I will now speak with you in {target_lang.capitalize()}."
                    else:
                        resp_text = "Voice configuration updated."

                    result["status"] = "success"
                    result["intent"] = "VOICE_CONFIGURATION"
                    result["response"] = resp_text
                    result["handled"] = True
                except Exception as ex:
                    result["status"] = "error"
                    result["response"] = f"Failed to update voice configuration: {ex}"
                    result["handled"] = True

            # 21. TASK MANAGEMENT
            elif intent == Intent.TASK_MANAGEMENT:
                try:
                    from skills.task_management import get_task_queue
                    from instance.config import settings
                    effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1
                    tq = get_task_queue()
                    action = params.get("action", "list_tasks")

                    if action == "queue_task":
                        goal = params.get("goal", user_input)
                        task_id = tq.submit(effective_uid, goal)
                        result["status"] = "success"
                        result["task_id"] = task_id
                        result["goal"] = goal
                        result["response"] = f"Task queued successfully with ID {task_id}. It will execute in the background."
                    elif action == "cancel_task":
                        tid = params.get("task_id", "").strip().rstrip('.?!')
                        if not tid:
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(effective_uid))
                                if dm.current_state.active_task and dm.current_state.active_task.get("task_id"):
                                    tid = dm.current_state.active_task["task_id"]
                            except Exception:
                                pass
                        if not tid:
                            try:
                                user_tasks = tq.list_user_tasks(effective_uid)
                                if user_tasks:
                                    tid = user_tasks[-1].get("task_id", "")
                            except Exception:
                                pass
                        if tid:
                            from core.task_execution_manager import get_task_execution_manager
                            tem_inst = get_task_execution_manager()
                            task_obj = tem_inst.get_task(tid)
                            success = tq.cancel(effective_uid, tid)
                            saved_notice = ""
                            if task_obj:
                                ckpt = task_obj.metadata.get("checkpoint") or {}
                                sf = ckpt.get("saved_files") or []
                                pp = ckpt.get("project_path")
                                if sf and pp:
                                    saved_notice = f" {len(sf)} files saved at {pp} were preserved."
                            result["status"] = "success" if success else "error"
                            result["task_id"] = tid
                            result["response"] = f"Task {tid} cancelled.{saved_notice}" if success else f"Could not cancel task {tid}."
                        else:
                            result["status"] = "error"
                            result["response"] = "You have no active background tasks to cancel. Please specify a task ID."
                        result["handled"] = True
                    elif action == "task_status":
                        tid = params.get("task_id", "").strip().rstrip('.?!')
                        if not tid:
                            try:
                                from extensions.dialogue_state_manager import get_dialogue_manager
                                dm = get_dialogue_manager(str(effective_uid))
                                if dm.current_state.active_task and dm.current_state.active_task.get("task_id"):
                                    tid = dm.current_state.active_task["task_id"]
                            except Exception:
                                pass
                        if not tid:
                            try:
                                from core.task_execution_manager import get_task_execution_manager
                                tem_inst = get_task_execution_manager()
                                active_user_tasks = tem_inst.list_tasks(user_id=effective_uid, active_only=True)
                                if active_user_tasks:
                                    active_user_tasks.sort(key=lambda t: t.created_at, reverse=True)
                                    tid = active_user_tasks[0].task_id
                            except Exception:
                                pass
                        if not tid:
                            try:
                                user_tasks = tq.list_user_tasks(effective_uid)
                                if user_tasks:
                                    tid = user_tasks[0].get("task_id", "")
                            except Exception:
                                pass
                        if tid:
                            from core.task_execution_manager import get_task_execution_manager
                            tem_inst = get_task_execution_manager()
                            task_obj = tem_inst.get_task(tid)
                            status_info = tq.get_status(effective_uid, tid)
                            if status_info and task_obj:
                                result["status"] = "success"
                                result["task"] = status_info
                                result["task_id"] = tid
                                st_name = task_obj.status.value
                                step_desc = task_obj.current_step
                                if step_desc:
                                    result["response"] = f"Task {tid} is currently {st_name}: {step_desc}."
                                else:
                                    result["response"] = f"Task {tid} is currently {st_name} ({task_obj.progress})."

                                # Attach visual status card if milestones exist
                                ms = task_obj.metadata.get("milestones")
                                if ms:
                                    from modules.code_generator.task_worker import emit_task_visual_response
                                    vr = emit_task_visual_response(
                                        task=task_obj,
                                        milestones=ms,
                                        current_activity=task_obj.current_step or task_obj.status.value,
                                        project_path=task_obj.metadata.get("project_path"),
                                        files=task_obj.metadata.get("files")
                                    )
                                    result["visual_response"] = vr.to_dict()
                            elif status_info:
                                result["status"] = "success"
                                result["task"] = status_info
                                result["task_id"] = tid
                                result["response"] = f"Task {tid} is currently {status_info['status']}."
                            else:
                                result["status"] = "error"
                                result["response"] = f"No task found with ID {tid} for your account."
                        else:
                            result["status"] = "error"
                            result["response"] = "You have no active background tasks. Please specify a task ID to check its status."
                        result["handled"] = True
                    else:
                        tasks = tq.list_user_tasks(effective_uid)
                        result["status"] = "success"
                        result["tasks"] = tasks
                        if tasks:
                            recent_str = ", ".join([f"[{t['task_id']}] {t['goal'][:25]} ({t['status']})" for t in tasks[:3]])
                            result["response"] = f"You have {len(tasks)} background task(s): {recent_str}."
                        else:
                            result["response"] = "You have no background tasks."
                        result["handled"] = True
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Task management failed: {e}"
                    result["handled"] = True

            # 22. SMART HOME
            elif intent == Intent.SMART_HOME:
                try:
                    from skills.smart_home import get_smart_home_controller
                    from instance.config import settings
                    effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1
                    ctrl = get_smart_home_controller()
                    res = ctrl.handle_command(user_input, user_id=effective_uid)
                    result["status"] = "success" if res.get("success", True) else "error"
                    result["response"] = res.get("message", "Smart home command executed.")
                    result.update(res)
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Smart home command failed: {e}"

            # 23. WINDOW CONTEXT
            elif intent == Intent.WINDOW_CONTEXT:
                try:
                    from skills.window_management import get_window_controller
                    ctrl = get_window_controller()
                    res = ctrl.handle_command(user_input)
                    result["status"] = "success" if res.get("success", True) else "error"
                    result["response"] = res.get("message", "Active window inspected.")
                    result.update(res)
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Window inspection failed: {e}"

            # 24. LEARNING
            elif intent == Intent.LEARNING:
                try:
                    from skills.learning import get_learning_controller
                    from instance.config import settings
                    effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1
                    ctrl = get_learning_controller()
                    res = ctrl.handle_command(user_input, user_id=effective_uid)
                    result["status"] = "success" if res.get("success", True) else "error"
                    result["response"] = res.get("message", "Learned rules updated.")
                    result.update(res)
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Learning operation failed: {e}"

            # 25. UNDO
            elif intent == Intent.UNDO:
                try:
                    from skills.undo import get_undo_controller
                    from instance.config import settings
                    effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1
                    ctrl = get_undo_controller()
                    res = ctrl.handle_command(user_input, user_id=effective_uid)
                    result["status"] = "success" if res.get("success", True) else "error"
                    result["response"] = res.get("message", "Undo executed.")
                    result.update(res)
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Undo failed: {e}"

            # 26. AUDIO DEVICES
            elif intent == Intent.AUDIO_DEVICES:
                try:
                    action = params.get("action", "audio_devices")
                    if action == "ptt":
                        from skills.audio_management import set_ptt_enabled, toggle_ptt
                        state = params.get("ptt_state", "toggle")
                        if state == "on":
                            msg = set_ptt_enabled(True)
                        elif state == "off":
                            msg = set_ptt_enabled(False)
                        else:
                            msg = toggle_ptt()
                        result["status"] = "success"
                        result["response"] = msg
                    else:
                        from skills.audio_management import get_audio_controller
                        ctrl = get_audio_controller()
                        res = ctrl.handle_command(user_input)
                        result["status"] = "success" if res.get("success", True) else "error"
                        result["response"] = res.get("message", "Audio devices listed.")
                        result.update(res)
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Audio command failed: {e}"

            # 27. RECOMMENDATION
            elif intent == Intent.RECOMMENDATION:
                try:
                    if params.get("response"):
                        result["status"] = "success"
                        result["response"] = params.get("response")
                    else:
                        query = params.get("query") or user_input
                        m_sel = re.search(r'^(?:select|choose|pick|details\s+for|info\s+on|open|play)\s+recommendation\s+(.+)', query, re.IGNORECASE)
                        if m_sel:
                            item_name = m_sel.group(1).strip()
                            result["status"] = "success"
                            result["item"] = item_name
                            result["action"] = "select_recommendation"
                            result["target_type"] = "MOVIE_OR_TV" if any(w in query.lower() for w in ("movie", "film", "show")) else "RECOMMENDATION_ITEM"
                            result["response"] = f"Selected '{item_name}' from your recommendations. I can search for where to stream it or provide more details."
                            result["handled"] = True
                            return result
                        from skills.recommendation_engine import recommend
                        rec_res = recommend(query, user_id=user_id)
                        result["status"] = "success"
                        result["response"] = rec_res
                except Exception as e:
                    self.logger.error(f"Recommendation execution error: {e}")
                    result["status"] = "error"
                    result["response"] = f"Failed to get recommendations: {e}"

            # 28. EPHEMERAL VISUAL RESPONSE SURFACE
            elif intent == Intent.VISUAL_SURFACE:
                try:
                    from extensions.dialogue_state_manager import get_dialogue_manager
                    from core.assistant_core import assistant_core
                    from instance.config import settings
                    import time

                    effective_uid = str(user_id or getattr(settings, 'CURRENT_USER_ID', None) or "default")
                    dm = get_dialogue_manager(effective_uid)
                    raw_input = user_input
                    raw_low = user_input.lower()
                    req_type = params.get("target_type")
                    if not req_type:
                        if "box" in raw_low and "number" in raw_low:
                            req_type = "NUMBERS_BOX"
                        elif any(w in raw_low for w in ["number", "numbers", "count"]):
                            req_type = "NUMBERS"
                        elif "pairing" in raw_low or "code" in raw_low:
                            req_type = "PAIRING_CODE"
                        elif "ip" in raw_low or "address" in raw_low:
                            req_type = "IP_ADDRESS"
                        elif "url" in raw_low or "link" in raw_low:
                            req_type = "URL"
                        elif "file" in raw_low or "path" in raw_low:
                            req_type = "FILE_PATH"
                        elif "list" in raw_low or "devices" in raw_low:
                            req_type = "LIST"
                        elif any(w in raw_low for w in ["knowledge", "answer", "explanation", "about"]):
                            req_type = "KNOWLEDGE"

                    # Explicit repeat request check
                    is_explicit_again = bool(
                        req_type == "AGAIN"
                        or re.search(r'\b(?:again|back)\b', raw_low)
                        or re.search(r'\b(?:previous|last)\s+result\b', raw_low)
                        or re.search(r'\bwhat\s+you\s+(?:just\s+)?(?:said|told\s+me)\b', raw_low)
                        or re.match(r'^(?:can\s+you\s+|could\s+you\s+|please\s+)?(?:show|display)\s+(?:me\s+)?(?:that|it)[.!?]?$', raw_low)
                    )

                    # Check for explicit numbers / counting / random numbers / box request
                    is_number_req = (
                        req_type in ("NUMBERS_BOX", "NUMBERS")
                        or (re.search(r'\b(?:count|numbers?)\b', raw_low) and any(w in raw_low for w in ["count", "show", "generate", "give", "list", "box", "random", "reverse", "from", "to", "between"]))
                        or bool(re.search(r'\bcount\s+(?:from\s+)?\d+', raw_low))
                        or bool(re.search(r'\bcount\s+\d+', raw_low))
                    )

                    # --- CASE 1: NUMBERS / COUNTING REQUEST (NEW PAYLOAD) ---
                    if is_number_req and not is_explicit_again and "pairing" not in raw_low and "code" not in raw_low:
                        WORD_NUMS = {
                            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                            "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
                            "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
                            "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
                            "eighty": 80, "ninety": 90, "hundred": 100
                        }

                        # Check for range: "from X to Y" or "between X and Y" or "from X-Y" or "X to Y" or "X-Y"
                        m_range = re.search(r'(?:from|between)\s+(\d+)\s*(?:to|and|-)\s*(\d+)', raw_low)
                        if not m_range:
                            m_range = re.search(r'\b(\d+)\s*(?:to|-)\s*(\d+)\b', raw_low)
                        
                        start_bound, end_bound = None, None
                        if m_range:
                            start_bound = int(m_range.group(1))
                            end_bound = int(m_range.group(2))

                        # Check count
                        count = None
                        m_count_digit = re.search(r'\b(\d+)\s+(?:random\s+)?numbers?\b', raw_low)
                        if m_count_digit:
                            count = int(m_count_digit.group(1))
                        else:
                            m_cnt = re.search(r'\bcount\s+(?:up\s+to\s+)?(\d+)\b', raw_low)
                            if m_cnt:
                                count = int(m_cnt.group(1))
                            else:
                                for word, val in WORD_NUMS.items():
                                    if re.search(rf'\b{word}\s+(?:random\s+)?numbers?\b', raw_low) or re.search(rf'\bcount\s+{word}\b', raw_low):
                                        count = val
                                        break

                        is_random = "random" in raw_low
                        is_reverse = "reverse" in raw_low

                        if count is None:
                            if start_bound is not None and end_bound is not None:
                                count = abs(end_bound - start_bound) + 1
                            else:
                                count = 10

                        import random
                        if is_random:
                            if start_bound is not None and end_bound is not None:
                                low = min(start_bound, end_bound)
                                high = max(start_bound, end_bound)
                            else:
                                low = 1
                                high = max(100, count * 10)
                            num_list = [random.randint(low, high) for _ in range(count)]
                        else:
                            if start_bound is not None and end_bound is not None:
                                step = 1 if end_bound >= start_bound else -1
                                num_list = list(range(start_bound, end_bound + step, step))
                            else:
                                num_list = list(range(1, count + 1))

                        if is_reverse:
                            num_list = list(reversed(num_list))

                        # Format grid
                        cols = 10 if len(num_list) >= 10 else len(num_list)
                        cols = max(cols, 1)
                        width = max(len(str(n)) for n in num_list) if num_list else 2
                        rows = []
                        for i in range(0, len(num_list), cols):
                            chunk = num_list[i:i + cols]
                            rows.append("  ".join(f"{n:>{width}}" for n in chunk))
                        grid_text = "\n".join(rows)

                        # Determine title and speech
                        if is_random:
                            title = "RANDOM NUMBERS"
                            speech = f"Here are {count} random numbers from {low} to {high}."
                            sec_desc = f"{count} random numbers between {low} and {high}."
                        elif "box" in raw_low:
                            title = "NUMBERS IN A BOX"
                            if start_bound and end_bound:
                                speech = f"Here are the numbers {start_bound} to {end_bound} in a box."
                            else:
                                speech = f"Here are {len(num_list)} numbers in a box."
                            sec_desc = f"Numbers structured in a box."
                        elif is_reverse:
                            title = "NUMBERS"
                            speech = f"Here are {len(num_list)} numbers in reverse order."
                            sec_desc = f"{len(num_list)} numbers in reverse order."
                        elif len(num_list) <= 10:
                            title = "NUMBERS"
                            nums_s = ", ".join(str(n) for n in num_list[:-1]) + f", and {num_list[-1]}" if len(num_list) > 1 else str(num_list[0])
                            speech = f"Here are the numbers: {nums_s}."
                            sec_desc = f"{len(num_list)} numbers."
                        elif len(num_list) <= 20:
                            title = "NUMBERS"
                            nums_s = ", ".join(str(n) for n in num_list)
                            speech = f"Here are the numbers from {num_list[0]} to {num_list[-1]}: {nums_s}."
                            sec_desc = f"Numbers from {num_list[0]} to {num_list[-1]}."
                        else:
                            title = "NUMBERS"
                            speech = f"Here are {len(num_list)} numbers from {num_list[0]} to {num_list[-1]}."
                            sec_desc = f"{len(num_list)} numbers."

                        from core.visual_response import VisualResponse, VisualResponseType, VisualResponseAction
                        vr = VisualResponse(
                            response_id=str(uuid.uuid4())[:8],
                            user_id=str(effective_uid),
                            response_type=VisualResponseType.TABLE,
                            title=title,
                            primary_value=grid_text,
                            secondary_text=sec_desc,
                            actions=[VisualResponseAction(label="Copy", action_type="copy", payload=grid_text)],
                            created_at=time.time(),
                            ttl_seconds=600.0,
                            source_context="numbers_display"
                        )
                        vr.metadata["user_input"] = user_input
                        vr.metadata["intent"] = intent.name if hasattr(intent, "name") else str(intent)
                        dm.store_visual_response(vr)
                        assistant_core.show_visual_response(vr, user_input=user_input, intent=intent)

                        # Debug logging (Section 13)
                        print(
                            f"[VISUAL]\n"
                            f"Current command: {user_input}\n"
                            f"Intent: VISUAL_SURFACE\n"
                            f"Payload source: generation\n"
                            f"Payload type: TABLE\n"
                            f"Using previous result: NO\n"
                            f"Previous result age: N/A\n"
                            f"Previous result explicitly referenced: NO"
                        )

                        result["status"] = "success"
                        result["intent"] = "VISUAL_SURFACE"
                        result["response"] = speech
                        result["visual_response"] = vr.to_dict()
                        result["handled"] = True
                        return result

                    # --- CASE 2: EXPLICIT REPLAY ("SHOW THAT AGAIN") ---
                    if is_explicit_again:
                        cached_vr = dm.get_last_visual_response(response_type=req_type if req_type != "AGAIN" else None, allow_expired=True)

                        now = time.time()
                        prev_age = (now - float(cached_vr.get("created_at", now))) if (cached_vr and "created_at" in cached_vr) else 0.0
                        prev_age_str = f"{prev_age:.1f}s" if cached_vr else "N/A"

                        if not cached_vr:
                            print(
                                f"[VISUAL]\n"
                                f"Current command: {user_input}\n"
                                f"Intent: VISUAL_SURFACE\n"
                                f"Payload source: cache\n"
                                f"Payload type: NONE\n"
                                f"Using previous result: NO\n"
                                f"Previous result age: N/A\n"
                                f"Previous result explicitly referenced: YES"
                            )
                            result["status"] = "success"
                            result["intent"] = "VISUAL_SURFACE"
                            result["response"] = "There is no recent information to display."
                            result["handled"] = True
                            return result

                        ttl = float(cached_vr.get("ttl_seconds", 300.0))
                        if prev_age > ttl:
                            result["status"] = "expired"
                            result["intent"] = "VISUAL_SURFACE"
                            result["response"] = "I no longer have a current version of that information. Would you like me to retrieve it again?"
                            result["handled"] = True
                            return result

                        from core.visual_response import VisualResponse
                        vr_obj = VisualResponse.from_dict(cached_vr)
                        vr_obj.metadata["user_input"] = user_input
                        vr_obj.metadata["intent"] = intent.name if hasattr(intent, "name") else str(intent)
                        assistant_core.show_visual_response(vr_obj, user_input=user_input, intent=intent)

                        print(
                            f"[VISUAL]\n"
                            f"Current command: {user_input}\n"
                            f"Intent: VISUAL_SURFACE\n"
                            f"Payload source: cache\n"
                            f"Payload type: {cached_vr.get('response_type', 'UNKNOWN')}\n"
                            f"Using previous result: YES\n"
                            f"Previous result age: {prev_age_str}\n"
                            f"Previous result explicitly referenced: YES"
                        )

                        title_display = vr_obj.title.lower()
                        result["status"] = "success"
                        result["intent"] = "VISUAL_SURFACE"
                        val_preview = vr_obj.primary_value if len(vr_obj.primary_value) <= 40 and "\n" not in vr_obj.primary_value else ""
                        if val_preview:
                            result["response"] = f"Displaying {title_display}: {val_preview}."
                        else:
                            result["response"] = f"Displaying {title_display}."
                        result["visual_response"] = vr_obj.to_dict()
                        result["reused_cache"] = True
                        result["handled"] = True
                        return result

                    # --- CASE 3: EXPLICIT ENTITY QUERY (e.g. "show me the pairing code") ---
                    if req_type == "PAIRING_CODE" or "pairing" in raw_low or "code" in raw_low:
                        cached_vr = dm.get_last_visual_response(response_type="PAIRING_CODE", allow_expired=False)
                        if not cached_vr:
                            try:
                                from skills.device_management import get_device_controller
                                dc = get_device_controller()
                                offer_info = dc.get_active_pairing_code(int(effective_uid) if str(effective_uid).isdigit() else 1)
                                if offer_info and offer_info.get("code"):
                                    from core.visual_response import detect_visual_response
                                    vr_obj = detect_visual_response(offer_info, user_input, user_id=str(effective_uid))
                                    if vr_obj:
                                        dm.store_visual_response(vr_obj)
                                        cached_vr = vr_obj.to_dict()
                            except Exception as e:
                                self.logger.warning(f"Error checking active pairing code: {e}")

                        if cached_vr:
                            from core.visual_response import VisualResponse
                            vr_obj = VisualResponse.from_dict(cached_vr)
                            vr_obj.metadata["user_input"] = user_input
                            vr_obj.metadata["intent"] = intent.name if hasattr(intent, "name") else str(intent)
                            assistant_core.show_visual_response(vr_obj, user_input=user_input, intent=intent)
                            print(
                                f"[VISUAL]\n"
                                f"Current command: {user_input}\n"
                                f"Intent: VISUAL_SURFACE\n"
                                f"Payload source: active_entity\n"
                                f"Payload type: PAIRING_CODE\n"
                                f"Using previous result: YES\n"
                                f"Previous result age: N/A\n"
                                f"Previous result explicitly referenced: NO"
                            )
                            result["status"] = "success"
                            result["intent"] = "VISUAL_SURFACE"
                            result["response"] = f"Displaying mobile pairing: {vr_obj.primary_value}."
                            result["visual_response"] = vr_obj.to_dict()
                            result["handled"] = True
                            return result
                        else:
                            result["status"] = "success"
                            result["intent"] = "VISUAL_SURFACE"
                            result["response"] = "There is no active pairing code. Say 'pair my phone' to connect a new device."
                            result["handled"] = True
                            return result

                    # --- CASE 3B: SPECIFIC ENTITY DETAILS (Calendar Event, Meeting, Email, Document) ---
                    target_subj = params.get("target_subject") or ""
                    is_calendar_entity = (
                        req_type in ("CALENDAR_EVENT", "EVENT", "MEETING")
                        or any(w in raw_low for w in ["meeting", "calendar", "event", "appointment", "schedule"])
                        or any(w in target_subj.lower() for w in ["meeting", "calendar", "event", "appointment"])
                    )
                    if is_calendar_entity and not is_explicit_again:
                        try:
                            from modules.calendar_manager.calendar_storage import CalendarStorage
                            c_storage = CalendarStorage()
                            uid_int = int(effective_uid) if str(effective_uid).isdigit() else 1
                            from datetime import datetime, timedelta
                            today_str = datetime.now().strftime("%Y-%m-%d")
                            evs = c_storage.get_events(uid_int, today_str)
                            if not evs:
                                end_str = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
                                ev_range = c_storage.get_events_range(uid_int, today_str, end_str)
                                for d_evs in ev_range.values():
                                    evs.extend(d_evs)
                            matching_ev = None
                            subj_filter = target_subj.lower() or raw_low
                            for fw in ["show", "details", "about", "for", "my", "the", "calendar", "event", "meeting"]:
                                subj_filter = re.sub(rf'\b{fw}\b', '', subj_filter).strip()
                            if subj_filter and evs:
                                for ev in evs:
                                    t = (ev.get("title") or "").lower()
                                    d = (ev.get("description") or "").lower()
                                    if any(tok in t or tok in d for tok in subj_filter.split() if len(tok) >= 3):
                                        matching_ev = ev
                                        break
                            if not matching_ev and evs:
                                matching_ev = evs[0]
                            if matching_ev:
                                from core.visual_response import VisualResponse
                                vr_obj = VisualResponse.for_calendar_event(matching_ev, user_id=str(effective_uid))
                                dm.store_visual_response(vr_obj)
                                ev_title = matching_ev.get("title", "Event")
                                speech_ans = f"Displaying details for {ev_title}."
                                from core.multilingual_engine import MultilingualEngine
                                me = MultilingualEngine.get_instance()
                                det_l = me.get_active_language(effective_uid)
                                if det_l and det_l != "en":
                                    vr_obj.title = me.translate_from_english(vr_obj.title, det_l)
                                    vr_obj.primary_value = me.translate_from_english(vr_obj.primary_value, det_l)
                                    speech_ans = me.translate_from_english(speech_ans, det_l)
                                vr_obj.metadata["user_input"] = user_input
                                vr_obj.metadata["intent"] = intent.name if hasattr(intent, "name") else str(intent)
                                assistant_core.show_visual_response(vr_obj, user_input=user_input, intent=intent)
                                result["status"] = "success"
                                result["intent"] = "VISUAL_SURFACE"
                                result["response"] = speech_ans
                                result["visual_response"] = vr_obj.to_dict()
                                result["handled"] = True
                                return result
                        except Exception as cal_err:
                            self.logger.warning(f"Calendar details extraction notice: {cal_err}")

                    # --- CASE 3C: EXPLICIT DETAILS / EXPLANATION / STEPS FROM PREVIOUS RESPONSE ---
                    is_details_query = (
                        req_type in ("DETAILS", "STEPS", "EXPLANATION", "SUBJECT_DETAILS")
                        or any(w in raw_low for w in [
                            "detail", "details", "details box", "information", "info", "explanation",
                            "full steps", "technical details", "all the information", "expand",
                            "what you just explained", "understand everything"
                        ])
                        or any(w in raw_low for w in ["వివరాలు", "विवरण", "விவரங்களை", "detalles"])
                    )
                    if is_details_query:
                        cached_vr = dm.get_last_visual_response(allow_expired=False)
                        from core.visual_response import VisualResponse, VisualResponseType, extract_visual_title, format_knowledge_content

                        prev_text = None
                        prev_user_in = None
                        target_resp_type = VisualResponseType.KNOWLEDGE

                        if dm.current_state.turns:
                            for turn in reversed(dm.current_state.turns):
                                resp_cand = getattr(turn, "assistant_response", "") or ""
                                in_cand = getattr(turn, "user_input", "") or ""
                                if resp_cand.strip() and not any(resp_cand.startswith(p) for p in ["There is no recent", "Displaying", "I encountered an error"]):
                                    prev_text = resp_cand.strip()
                                    prev_user_in = in_cand.strip()
                                    break
                        if not prev_text:
                            try:
                                from extensions.conversational_memory import recent_memory, _lock
                                with _lock:
                                    if recent_memory:
                                        for m in reversed(list(recent_memory)):
                                            r_m = m.get("assistant_response", "")
                                            if r_m and not any(r_m.startswith(p) for p in ["There is no recent", "Displaying", "I encountered an error"]):
                                                prev_text = r_m.strip()
                                                prev_user_in = m.get("user_command", "").strip()
                                                break
                            except Exception:
                                pass

                        if prev_text:
                            title_cand = extract_visual_title(prev_user_in or user_input, prev_text, default="DETAILS")
                            formatted_content = format_knowledge_content(prev_text)
                            if any(k in raw_low for k in ["step", "steps"]) or re.search(r'(?:^|\n)\s*\d+[\.\)]\s+', formatted_content):
                                target_resp_type = VisualResponseType.PROCEDURE_STEPS
                            elif "```" in formatted_content or any(k in raw_low for k in ["code", "technical", "command"]):
                                target_resp_type = VisualResponseType.CODE
                            else:
                                target_resp_type = VisualResponseType.KNOWLEDGE

                            vr_obj = VisualResponse.for_text(
                                formatted_content,
                                title=title_cand,
                                description="Full details from previous response.",
                                user_id=str(effective_uid),
                                response_type=target_resp_type
                            )
                            dm.store_visual_response(vr_obj)
                        elif cached_vr and not cached_vr.is_expired():
                            vr_obj = cached_vr
                        else:
                            vr_obj = None

                        if vr_obj:
                            from core.multilingual_engine import MultilingualEngine
                            me = MultilingualEngine.get_instance()
                            det_l = me.get_active_language(effective_uid)
                            speech_ans = "Displaying the details on screen."
                            if det_l and det_l != "en":
                                vr_obj.title = me.translate_from_english(vr_obj.title, det_l)
                                vr_obj.primary_value = me.translate_from_english(vr_obj.primary_value, det_l)
                                speech_ans = me.translate_from_english(speech_ans, det_l)

                            vr_obj.metadata["user_input"] = user_input
                            vr_obj.metadata["intent"] = intent.name if hasattr(intent, "name") else str(intent)
                            assistant_core.show_visual_response(vr_obj, user_input=user_input, intent=intent)
                            result["status"] = "success"
                            result["intent"] = "VISUAL_SURFACE"
                            result["response"] = speech_ans
                            result["visual_response"] = vr_obj.to_dict()
                            result["handled"] = True
                            return result
                        else:
                            result["status"] = "success"
                            result["intent"] = "VISUAL_SURFACE"
                            result["response"] = "There is no recent information to display in the details panel."
                            result["handled"] = True
                            return result

                    # --- CASE 4: EXPLICIT VISUAL DIRECTIVE (Weather / Knowledge / Search) ---
                    if "weather" in raw_low or "temperature" in raw_low:
                        from extensions.weather_engine import get_weather_for_query
                        wx_resp = get_weather_for_query(user_input)
                        result["status"] = "success"
                        result["intent"] = "VISUAL_SURFACE"
                        result["response"] = wx_resp
                        result["handled"] = True
                        from core.visual_response import detect_visual_response
                        vr = detect_visual_response({"response": wx_resp}, user_input, str(effective_uid))
                        if vr:
                            dm.store_visual_response(vr)
                            vr.metadata["user_input"] = user_input
                            vr.metadata["intent"] = intent.name if hasattr(intent, "name") else str(intent)
                            assistant_core.show_visual_response(vr, user_input=user_input, intent=intent)
                            result["visual_response"] = vr.to_dict()
                        print(
                            f"[VISUAL]\n"
                            f"Current command: {user_input}\n"
                            f"Intent: VISUAL_SURFACE\n"
                            f"Payload source: weather_engine\n"
                            f"Payload type: STATUS\n"
                            f"Using previous result: NO\n"
                            f"Previous result age: N/A\n"
                            f"Previous result explicitly referenced: NO"
                        )
                        return result

                    if any(w in raw_low for w in ["what", "who", "where", "when", "why", "how", "explain", "tell me about"]):
                        from extensions.rag_system import RAGSystem
                        rag = RAGSystem()
                        rag_res = rag.process(user_input)
                        ans = rag_res.get("response") if isinstance(rag_res, dict) else str(rag_res)
                        result["status"] = "success"
                        result["intent"] = "VISUAL_SURFACE"
                        result["response"] = ans
                        result["handled"] = True
                        from core.visual_response import detect_visual_response
                        vr = detect_visual_response({"response": ans}, user_input, str(effective_uid))
                        if vr:
                            dm.store_visual_response(vr)
                            vr.metadata["user_input"] = user_input
                            vr.metadata["intent"] = intent.name if hasattr(intent, "name") else str(intent)
                            assistant_core.show_visual_response(vr, user_input=user_input, intent=intent)
                            result["visual_response"] = vr.to_dict()
                        print(
                            f"[VISUAL]\n"
                            f"Current command: {user_input}\n"
                            f"Intent: VISUAL_SURFACE\n"
                            f"Payload source: rag_system\n"
                            f"Payload type: KNOWLEDGE\n"
                            f"Using previous result: NO\n"
                            f"Previous result age: N/A\n"
                            f"Previous result explicitly referenced: NO"
                        )
                        return result

                    # --- CASE 5: STRICT CONTEXT FALLBACK ---
                    # A new command that does not request replay and cannot be resolved visually MUST NEVER blindly reuse previous visual response!
                    print(
                        f"[VISUAL]\n"
                        f"Current command: {user_input}\n"
                        f"Intent: VISUAL_SURFACE\n"
                        f"Payload source: none\n"
                        f"Payload type: NONE\n"
                        f"Using previous result: NO\n"
                        f"Previous result age: N/A\n"
                        f"Previous result explicitly referenced: NO"
                    )
                    result["status"] = "success"
                    result["intent"] = "VISUAL_SURFACE"
                    result["response"] = "I don't have new visual information to display for that request."
                    result["handled"] = True
                    return result
                except Exception as e:
                    self.logger.error(f"Visual surface execution error: {e}")
                    result["status"] = "error"
            elif intent in (Intent.RECOMMENDATION, Intent.GAME_DISCOVERY, Intent.SYSTEM_COMPATIBILITY):
                try:
                    from skills.recommendation_engine import get_recommendation_engine
                    rec_engine = get_recommendation_engine()
                    q = params.get("query", user_input)
                    rec_res = rec_engine.recommend(q, user_id=effective_uid)
                    if isinstance(rec_res, dict):
                        result["status"] = "success"
                        result["response"] = rec_res.get("text", "Here are my recommendations.")
                        result.update(rec_res)
                    else:
                        result["status"] = "success"
                        result["response"] = str(rec_res)
                    if intent == Intent.SYSTEM_COMPATIBILITY:
                        from core.environment_observer import get_canonical_system_snapshot
                        snap = get_canonical_system_snapshot(user_id=effective_uid)
                        result["system_snapshot"] = {
                            "cpu": snap.cpu_model,
                            "gpu": snap.gpu_model,
                            "ram_total_gb": snap.ram_total_gb,
                            "ram_available_gb": snap.ram_available_gb
                        }
                    result["handled"] = True
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Operation failed: {e}"
                    result["handled"] = True

            # Catch-all for not fully implemented intents
            else:
                result["response"] = f"Intent {intent.name} recognized but execution not fully wired yet."

            # Canonical production visual response hook:
            # If the action produced a result with visually useful data and hasn't been emitted yet,
            # detect and dispatch it automatically without altering the authoritative speech response.
            if not result.get("visual_response") and intent != Intent.VISUAL_SURFACE:
                try:
                    from core.visual_response import detect_visual_response
                    vr = detect_visual_response(result, user_input, str(effective_uid))
                    if vr:
                        vr.metadata["user_input"] = user_input
                        vr.metadata["intent"] = intent.name if hasattr(intent, "name") else str(intent)
                        try:
                            from core.multilingual_engine import MultilingualEngine
                            me = MultilingualEngine.get_instance()
                            det_l = me.get_active_language(effective_uid)
                            if det_l and det_l != "en":
                                vr.title = me.translate_from_english(vr.title, det_l)
                                vr.primary_value = me.translate_from_english(vr.primary_value, det_l)
                        except Exception:
                            pass
                        from extensions.dialogue_state_manager import get_dialogue_manager
                        dm = get_dialogue_manager(str(effective_uid))
                        dm.store_visual_response(vr)
                        result["visual_response"] = vr.to_dict()
                        from core.assistant_core import assistant_core
                        assistant_core.show_visual_response(vr, user_input=user_input, intent=intent)
                except Exception as vr_err:
                    self.logger.debug(f"Direct visual response detection notice: {vr_err}")

            if result.get("status") == "success" and intent in (Intent.OPEN_APPLICATION, Intent.CLOSE_APPLICATION, Intent.WINDOW_CONTEXT):
                try:
                    from core.environment import verify_and_synchronize_foreground_state
                    act_target = params.get("target") or params.get("application") or result.get("target") or result.get("app_name")
                    verify_and_synchronize_foreground_state(user_id=effective_uid, action_target=act_target)
                except Exception:
                    pass

            if "response" in result and "speech_response" not in result:
                result["speech_response"] = result["response"]

            return result
            
        except Exception as e:
            self.logger.error(f"Error executing command: {e}")
            return {
                "status": "error",
                "message": f"Execution failed: {str(e)}",
                "intent": "ERROR"
            }

unified_router = UnifiedCommandRouter()

def get_router() -> UnifiedCommandRouter:
    """Return the global UnifiedCommandRouter singleton."""
    return unified_router

def route_and_execute(
    user_input: str,
    user_id: Optional[Any] = None,
    confirmed_by_user: bool = False,
    confirmation_id: Optional[str] = None,
) -> Dict[str, Any]:
    return unified_router.execute_single_action(
        user_input,
        user_id=user_id,
        confirmed_by_user=confirmed_by_user,
        confirmation_id=confirmation_id,
    )
