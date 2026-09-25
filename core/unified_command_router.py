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
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from enum import Enum

def get_assistant_name() -> str:
    """Get the current user's configured assistant name."""
    try:
        from instance.config import settings
        name = settings.get_assistant_name()
        if name:
            return name.lower().strip()
    except Exception:
        pass
    return "assistant"  # Fallback default

def contains_assistant_name(text: str) -> bool:
    """Check if text contains the current user's assistant name.
    
    This is case-insensitive, position-agnostic, and punctuation-tolerant.
    Used as an addressing signal, NOT as a mandatory wake word.
    
    Examples for assistant name "Aira":
    - "Aira open Chrome" → True
    - "open Chrome Aira" → True  
    - "can you Aira open Chrome" → True
    - "can you open Chrome, Aira?" → True
    - "AIRA open Chrome" → True
    """
    assistant_name = get_assistant_name()
    if not assistant_name or assistant_name == "assistant":
        return False  # No specific name configured
    
    # Clean the text: remove punctuation, convert to lowercase
    clean_text = re.sub(r'[^\w\s]', '', text.lower())
    clean_name = assistant_name.lower()
    
    # Check if name appears anywhere in the text
    return clean_name in clean_text

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
                re.compile(r'\b(mute|unmute)\b', re.IGNORECASE),
                # volume only when NOT preceded by 'open'/'launch'/'start'
                re.compile(r'(?<!open\s)(?<!launch\s)(?<!start\s)\b(increase|decrease|raise|lower|set)\s+volume\b', re.IGNORECASE),
                re.compile(r'\b(volume\s+(?:up|down|control|level))\b', re.IGNORECASE),
                re.compile(r'\b(turn\s+(?:up|down)\s+(?:the\s+)?volume)\b', re.IGNORECASE),
                re.compile(r'\b(take\s+(?:a\s+)?screenshot|capture\s+(?:the\s+)?screen|screen\s*capture|screenshot)\b', re.IGNORECASE),
                re.compile(r'\b(lock|logout)\b', re.IGNORECASE),
                # Brightness controls
                re.compile(r'\b(?:increase|decrease|raise|lower|set)\s+brightness\b', re.IGNORECASE),
                re.compile(r'\b(?:brightness\s+(?:up|down|level)|screen\s+brightness)\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+is\s+(?:the\s+)?brightness|check\s+brightness)\b', re.IGNORECASE),
                # Battery diagnostics
                re.compile(r'\b(?:battery|battery\s+(?:status|level|percentage|life)|how\s+much\s+battery)\b', re.IGNORECASE),
                # Disk / Storage diagnostics
                re.compile(r'\b(?:disk\s+space|free\s+space|storage\s+space|how\s+much\s+storage|check\s+disk)\b', re.IGNORECASE),
                # System telemetry / Top processes
                re.compile(r'\b(?:top\s+processes|running\s+processes|what\s+is\s+using\s+my\s+(?:ram|cpu|memory)|cpu\s+usage|memory\s+usage)\b', re.IGNORECASE),
                # Window controls
                re.compile(r'\b(?:minimize\s+all(?:\s+windows)?|minimize\s+windows|show\s+desktop)\b', re.IGNORECASE),
                # Clipboard
                re.compile(r'\b(?:read|check|show|get)\s+(?:the\s+|my\s+)?clipboard\b', re.IGNORECASE),
                re.compile(r'\bwhat(?:\'s|\s+is)\s+(?:currently\s+)?(?:in|on|stored\s+in)?\s*(?:the\s+|my\s+)?clipboard\b', re.IGNORECASE),
                re.compile(r'\b(?:copy|put)\s+(?:this|that|.+?)\s+(?:to|on|into)\s+(?:my\s+)?clipboard\b', re.IGNORECASE),
                re.compile(r'\b(?:make|convert|turn|capitalize|trim|count|strip).{0,25}clipboard\b', re.IGNORECASE),
                re.compile(r'\bclipboard.{0,25}(?:uppercase|lowercase|bullets?|bullet\s+points?|words?|trim)\b', re.IGNORECASE),
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
                # Clipboard Technical Analysis
                re.compile(r'\b(?:analyze|inspect)\s+(?:my\s+)?clipboard(?:\s+content)?\b', re.IGNORECASE),
                # Display / Monitor Information
                re.compile(r'\b(?:show|get|check|what\s+is)\s+(?:my\s+)?(?:display|screen|monitor)\s+(?:info|information|resolution|metrics)\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+resolution\s+is\s+my\s+(?:screen|display|monitor)\b', re.IGNORECASE),
                re.compile(r'\b(?:display|screen|monitor)\s+resolution\b', re.IGNORECASE),
                # Wi-Fi / Network
                re.compile(r'\b(?:wifi|wi-fi|wireless)\s+(?:status|connection|info|on|off|enable|disable)\b', re.IGNORECASE),
                re.compile(r'\b(?:enable|disable|turn\s+on|turn\s+off)\s+(?:wifi|wi-fi|wireless)\b', re.IGNORECASE),
                re.compile(r'\b(?:is\s+(?:my\s+)?wifi|are\s+(?:we|i)\s+connected\s+to\s+wifi|what\s+wifi\s+am\s+i\s+on|connected\s+to\s+wifi|wifi\s+connected)\b', re.IGNORECASE),
                re.compile(r'\b(?:list|show|scan|find)\s+(?:available\s+|nearby\s+)?(?:wifi|wi-fi|wireless)\s+networks?\b', re.IGNORECASE),
                re.compile(r'\b(?:show|list|check|get)\s+(?:my\s+)?(?:network|internet)\s+(?:adapters?|connections?|status|speeds?|info)\b', re.IGNORECASE),
                re.compile(r'\b(?:my\s+)?network\s+adapters?\b', re.IGNORECASE),
                re.compile(r'\b(?:network|internet)\s+speed\b', re.IGNORECASE),
                re.compile(r'\b(?:how\s+fast\s+is\s+(?:my\s+)?(?:internet|network|wifi|connection))\b', re.IGNORECASE),
                # Bluetooth
                re.compile(r'\b(?:bluetooth|bt)\s+(?:status|on|off|enable|disable|available|info)\b', re.IGNORECASE),
                re.compile(r'\b(?:enable|disable|turn\s+on|turn\s+off)\s+bluetooth\b', re.IGNORECASE),
                re.compile(r'\b(?:is\s+bluetooth|check\s+bluetooth|bluetooth\s+connected)\b', re.IGNORECASE),
                # Keyboard toggle keys
                re.compile(r'\b(?:turn\s+(?:the\s+)?caps\s+lock\s+(?:on|off)|(?:toggle|turn\s+on|turn\s+off|enable|disable)\s+caps\s+lock)\b', re.IGNORECASE),
                re.compile(r'\b(?:turn\s+(?:the\s+)?num\s+lock\s+(?:on|off)|(?:toggle|turn\s+on|turn\s+off|enable|disable)\s+num\s+lock)\b', re.IGNORECASE),
                re.compile(r'\b(?:turn\s+(?:the\s+)?scroll\s+lock\s+(?:on|off)|(?:toggle|turn\s+on|turn\s+off|enable|disable)\s+scroll\s+lock)\b', re.IGNORECASE),
                re.compile(r'\b(?:is\s+caps\s+lock|caps\s+lock\s+(?:on|off|status|state)|keyboard\s+lights?\s+status)\b', re.IGNORECASE),
                re.compile(r'\b(?:check|show|what\s+is)\s+(?:the\s+)?(?:keyboard|key(?:board)?)\s+(?:toggle|lock)\s+(?:keys?|state|status)\b', re.IGNORECASE),
                # Hardware info
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+(?:my\s+)?(?:gpu|graphics\s+card|cpu\s+model|processor|hardware)|my\s+gpu|my\s+cpu\s+model|my\s+processor|hardware\s+info(?:rmation)?)\b', re.IGNORECASE),
                re.compile(r'\b(?:tell\s+me\s+about\s+(?:my\s+)?hardware|device\s+hardware|hardware\s+spec(?:ification)?s?)\b', re.IGNORECASE),
                # Power plans
                re.compile(r'\b(?:power\s+plan|power\s+mode|current\s+power\s+plan|active\s+power\s+plan|what\s+power\s+plan)\b', re.IGNORECASE),
                re.compile(r'\b(?:list|show)\s+(?:all\s+)?power\s+plans?\b', re.IGNORECASE),
                # Mouse info
                re.compile(r'\b(?:mouse\s+(?:position|cursor|location|info|status|settings?)|where\s+is\s+(?:my\s+)?(?:mouse|cursor)|cursor\s+position)\b', re.IGNORECASE),
                # Uptime
                re.compile(r'\b(?:system\s+uptime|how\s+long\s+has\s+(?:the\s+)?(?:system|computer|pc|laptop)\s+been\s+(?:on|running|up)|uptime)\b', re.IGNORECASE),
                # All processes list
                re.compile(r'\b(?:list\s+all\s+(?:running\s+)?processes|show\s+all\s+(?:running\s+)?processes|all\s+running\s+processes)\b', re.IGNORECASE),
            ],

            # ── Priority 4: OPEN APPLICATION ──────────────────────────────────
            Intent.OPEN_APPLICATION: [
                re.compile(r'\b(?:search\s+(?:on\s+|in\s+)?youtube\s+for|search\s+youtube\s+for)\s+(.+)', re.IGNORECASE),
                re.compile(r'\b(?:search\s+(?:on\s+|in\s+)?google\s+for|search\s+google\s+for)\s+(.+)', re.IGNORECASE),
                re.compile(r'\b(open|show|display|launch)\s+((?:(?:the|my)\s+)?dashboard)\b', re.IGNORECASE),
                re.compile(r'\b(launch|start|run)\s+(.+)', re.IGNORECASE),
                re.compile(r'\b(close|quit|exit|terminate|kill)\s+(?!(?:music|song|track|audio|playback|email|mail|video))\s*(.+)', re.IGNORECASE),
                re.compile(r'(?:^|\b(?:please|can\s+you|could\s+you)\s+)(open)\s+(?!(?:music|song|email|mail|video|folder|directory|file\s+(?!explorer)|windows?\b|open\s+windows?\b))(.+)', re.IGNORECASE),
                re.compile(r'\b(?:go\s+to|visit|browse\s+(?:to\s+)?|navigate\s+to)\s+(.+)', re.IGNORECASE),
                re.compile(r'^(?:go\s+back|navigate\s+back|browser\s+go\s+back|go\s+back\s+in\s+browser)[.!?]?$', re.IGNORECASE),
            ],

            # ── Priority 5: FILE OPERATIONS ───────────────────────────────────
            Intent.FILE_OPERATIONS: [
                # Duplicate files
                re.compile(r'\b(?:duplicate\s+files?|find\s+duplicates?)\b', re.IGNORECASE),
                # File search & filtering
                re.compile(r'\b(?:find\s+all|search\s+(?:for\s+)?files?|files?\s+larger\s+than|files?\s+modified)\b', re.IGNORECASE),
                # Directory statistics
                re.compile(r'\b(?:statistics\s+for|stats\s+for|how\s+many\s+files\s+in|directory\s+stats)\b', re.IGNORECASE),
                # Largest files
                re.compile(r'\b(?:largest\s+files?|biggest\s+files?)\b', re.IGNORECASE),
                # PDF inspection & utilities
                re.compile(r'\b(?:how\s+many\s+pages\s+(?:are\s+)?in|information\s+about\s+(?:the\s+)?pdf|pdf\s+info|split\s+.*\.pdf|merge\s+.*pdfs?|extract\s+(?:the\s+)?text\s+from\s+.*\.pdf)\b', re.IGNORECASE),
                # Specific file delete
                re.compile(r'\b(delete|remove)\s+(?:the\s+)?(?:file\s+)?([\w\-.]+\.\w+)\b', re.IGNORECASE),
                # File move
                re.compile(r'\bmove\s+(?:the\s+)?(?:file\s+)?(.+?)\s+to\s+(.+)', re.IGNORECASE),
                # File rename
                re.compile(r'\brename\s+(?:the\s+)?(?:file\s+)?(.+?)\s+to\s+(.+)', re.IGNORECASE),
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
                # Desktop organizer
                re.compile(r'\b(?:organize|clean\s+up|clean)\s+(?:my\s+)?(?:desktop|downloads)\b', re.IGNORECASE),
            ],

            # ── Priority 6: EMAIL ─────────────────────────────────────────────
            Intent.EMAIL: [
                re.compile(r'\b(send\s+(?:email|mail)|send\s+.*\s+(?:to|email|mail))\b', re.IGNORECASE),
                re.compile(r'\b(?:email|mail)\s+.+?\s+to\b', re.IGNORECASE),
                re.compile(r'\b(?:send|email|mail)\s+(?:it|that\s+file|this\s+file|the\s+file|the\s+pdf|the\s+excel|the\s+report)\s+to\b', re.IGNORECASE),
                re.compile(r'\b(?:show|list|view|check|read|get)\s+(?:my\s+)?(?:unread\s+|new\s+)?(?:emails?|mail|inbox)\b', re.IGNORECASE),
                re.compile(r'\b(?:unread\s+emails?|new\s+emails?)\b', re.IGNORECASE),
                re.compile(r'\bdo\s+i\s+have\s+(?:any\s+)?(?:new\s+|unread\s+)?emails?\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(?:emails?|new\s+emails?|unread\s+emails?)\s+do\s+i\s+have\b', re.IGNORECASE),
                re.compile(r'\b(check|read|reply\s+to)\s+(?:my\s+)?(?:latest\s+)?(?:email|emails|mail|messages|inbox)\b', re.IGNORECASE),
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
            # Music playback commands with high specificity
            Intent.MUSIC: [
                re.compile(r'\b(play|start|begin)\s+(?:(?:some\s+)?(?:music|songs|tracks?)|(?:a\s+)?song)\b', re.IGNORECASE),
                re.compile(r'\bplay\s+(?!(?:audio\s+)?(?:sound|sound\s+effect|chime|ping|click|beep|whoosh|chirp|notification(?:\s+sound)?|alert)\b)(.+?)(?:\s+song|\s+track|\s+audio|$)', re.IGNORECASE),
                re.compile(r'\b(pause|resume|stop|next|previous|skip)\s+(?:the\s+)?(?:music|song|track|playback|audio)\b', re.IGNORECASE),
                # NOTE: negative lookahead prevents 'stop task <id>' from matching here;
                # that command belongs to TASK_MANAGEMENT (Priority 18).
                re.compile(r'\b(pause|resume|stop|next|previous|skip)\b(?!\s+(?:my\s+)?task\b)(?:\s+track|\s+song)?(?:\s|$)', re.IGNORECASE),
                re.compile(r'\b(toggle\s+playback|play\s*\/\s*pause|next\s+track|previous\s+track)\b', re.IGNORECASE),
                # YouTube video summary
                re.compile(r'\b(?:summarize|summary\s+of)\s+(?:this\s+)?(?:youtube\s+video|video)\b', re.IGNORECASE),
            ],

            # ── Priority 10: DOCUMENT GENERATION ──────────────────────────────
            Intent.DOCUMENT_GENERATION: [
                re.compile(r'\b(create|generate|make|write)\s+(?:an?\s+)?(?:word\s+doc(?:ument)?|docx|pdf(?:\s+document)?|excel(?:\s+sheet|\s+spreadsheet)?|spreadsheet|xlsx|powerpoint(?:\s+presentation)?|presentation|pptx|slides)\b', re.IGNORECASE),
                re.compile(r'\b(?:create|generate|make|write)\s+(?:an?\s+)?(?:pdf|excel|word|powerpoint|presentation|spreadsheet)\s+report\b', re.IGNORECASE),
                re.compile(r'\b(?:create|generate|make|write)\s+(?:an?\s+)?(?:excel\s+(?:expense\s+sheet|sheet)|pdf\s+report)\b', re.IGNORECASE),
                re.compile(r'\b(?:generate|create|make)\s+(?:an?\s+)?(?:report|resume|document|spreadsheet|sheet|presentation|slides)\s*(?:in|as)?\s*(?:word|docx|pdf|excel|xlsx|pptx|powerpoint)?\b', re.IGNORECASE),
            ],

            # ── Priority 10: CALCULATOR ────────────────────────────────────────
            # NOTE: 'add' is intentionally narrow here — 'add a meeting/event/appointment'
            # must NOT match so they fall through to DAILY_BRIEFING (Priority 14).
            Intent.CALCULATOR: [
                re.compile(
                    r'\b(calculate|math|subtract|multiply|divide|what\s+is\s+\d+)\b'
                    r'|\badd\b(?!\s+(?:a\s+)?(?:meeting|event|appointment|calendar|task|reminder|note))\s+\d',
                    re.IGNORECASE
                )
            ],

            # ── Priority 11: CODE GENERATION ─────────────────────────────────
            Intent.CODE_GENERATION: [
                re.compile(r'\b(?:validate|check)\s+(?:this\s+)?(?:python\s+)?code(?:\s+for\s+syntax\s+errors)?\b', re.IGNORECASE),
                re.compile(r'\b(?:does\s+this\s+code\s+have\s+syntax\s+errors|explain\s+(?:the\s+)?structure\s+of\s+(?:this\s+)?(?:python\s+)?code)\b', re.IGNORECASE),
                re.compile(r'\b(?:what\s+classes\s+and\s+functions\s+are\s+in\s+this\s+code)\b', re.IGNORECASE),
                re.compile(r'\b(?:(?:write|generate|create|build|run|sample|example|source)\s+code|code\s+(?:snippet|block|generation)|coding|program|script|function|algorithm)\b', re.IGNORECASE),
                re.compile(
                    r'\b(write|create|build|make|generate|implement)\b.{0,40}'
                    r'\b(in\s+(?:python|java|javascript|js|c\+\+|c#|ruby|go|rust|swift|kotlin|typescript|ts))\b',
                    re.IGNORECASE
                ),
                re.compile(
                    r'\b(bubble\s+sort|merge\s+sort|quick\s+sort|binary\s+search|linked\s+list|'
                    r'stack|priority\s+queue|queue\s+data\s+structure|graph|tree|dynamic\s+programming|recursion)\b',
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
                re.compile(r'\b(translate|translation|convert\s+text\s+to)\b', re.IGNORECASE),
                re.compile(r'\bsay\s+.+?\s+in\s+(?:spanish|french|german|italian|portuguese|russian|chinese|japanese|korean|hindi|telugu|tamil|kannada|malayalam|arabic|english|marathi|bengali|gujarati|punjabi|urdu|latin|greek)\b', re.IGNORECASE),
            ],

            # ── Priority 14: DAILY BRIEFING & CALENDAR ────────────────────────
            # Calendar creation patterns are placed BEFORE CALCULATOR (Priority 10)
            # in enum evaluation order so 'add a meeting' routes here, not CALCULATOR.
            Intent.DAILY_BRIEFING: [
                re.compile(r'\b(daily\s+briefing|morning\s+briefing|morning\s+update|give\s+me\s+my\s+briefing|brief\s+me|daily\s+update)\b', re.IGNORECASE),
                re.compile(r'\b(?:show|check|view|what(?:\'s|\s+is)\s+on|what)\s+(?:my\s+|today\'?s?\s+)?calendar\b', re.IGNORECASE),
                re.compile(r'\b(?:show|check|view|what)\s+(?:today\'?s?\s+|my\s+)?events\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+events\s+do\s+i\s+have\b', re.IGNORECASE),
                re.compile(r'\b(?:calendar\s+for\s+today|events\s+for\s+today|today\'?s?\s+calendar|today\'?s?\s+events)\b', re.IGNORECASE),
                # ── Calendar event creation (must be specific to win over CALCULATOR's 'add') ──
                re.compile(r'\b(?:create|schedule|add)\s+(?:an?\s+)?(?:calendar\s+event|event|meeting|appointment)\b', re.IGNORECASE),
                re.compile(r'\badd\s+(?:an?\s+)?(?:meeting|event|appointment)\b', re.IGNORECASE),
                re.compile(r'\badd\s+.+?\s+to\s+(?:my\s+)?calendar\b', re.IGNORECASE),
                re.compile(r'\bschedule\s+(?:an?\s+)?(?:event|meeting|appointment)(?:\s+for)?\b', re.IGNORECASE),
                re.compile(r'\bput\s+.+?\s+(?:on|in(?:to)?)\s+(?:my\s+)?calendar\b', re.IGNORECASE),
            ],

            # ── Priority 15: TIME QUERY (Local System Clock — Bypasses RAG/LLM) ─
            Intent.TIME_QUERY: [
                re.compile(r'\b(?:what(?:\'s|\s+is)\s+(?:the\s+)?time|what\s+time(?:\s+is\s+it)?|(?:can\s+you\s+)?tell\s+me\s+the\s+time|current\s+time|time\s+is\s+it)\b', re.IGNORECASE)
            ],

            # ── Priority 14: DATE QUERY (Local System Clock — Bypasses RAG/LLM) ─
            Intent.DATE_QUERY: [
                re.compile(r'\b(what\s+is\s+the\s+date|what\s+date|today\'?s?\s+date|what\s+day\s+is\s+it)\b', re.IGNORECASE)
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
                re.compile(r'\b(who\s+are\s+you|what(?:\'s|\s+is)\s+your\s+name)\b', re.IGNORECASE),
                re.compile(r'\bhow\s+old\s+am\s+i\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+is\s+my\s+age\b', re.IGNORECASE),
                re.compile(r'\bwhat(?:\'s|\s+is)\s+my\s+height\b', re.IGNORECASE),
                re.compile(r'\bhow\s+tall\s+am\s+i\b', re.IGNORECASE),
                re.compile(r'\b(do\s+you\s+remember|can\s+you\s+remember|do\s+you\s+know|do\s+you\s+recall)\s+(?:what\s+)?my\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+(did\s+i|did\s+we|is\s+my|are\s+my|was\s+my)\b', re.IGNORECASE),
                re.compile(r'\bwhat(\'s|\s+is)\s+my\b', re.IGNORECASE),
                re.compile(r'\btell\s+me\s+my\b', re.IGNORECASE),
                re.compile(r'\bwhich\s+([a-zA-Z\s]+)\s+do\s+i\s+(like|love|prefer)\b', re.IGNORECASE),
                re.compile(r'\b(remember|recall)\s+my\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+do\s+i\s+like\b', re.IGNORECASE),
                re.compile(r'\b(?:tell\s+me\s+about|what\s+did\s+i\s+tell\s+you\s+about)\s+myself\b', re.IGNORECASE),
                re.compile(r'\bwhat\s+do\s+you\s+(know|remember)\s+about\s+me\b', re.IGNORECASE),
                re.compile(r'\bshow\s+(?:my\s+)?memory\b', re.IGNORECASE),
            ],

            # ── Priority 17: MEMORY STORE ──────────────────────────────────
            Intent.MEMORY_STORE: [
                re.compile(r'\bmy\s+([a-zA-Z0-9_\s]+?)\s+(?:is|was|=)\s+([^?]+)', re.IGNORECASE),
                re.compile(r'\b(?:please\s+)?(?:remember|note)\s+(?:that\s+)?(.+)', re.IGNORECASE),
                re.compile(r'\bi\s+(?:really\s+)?(?:like|love|enjoy|prefer)\s+(.+)', re.IGNORECASE),
                re.compile(r'\b(?:save|store|keep)\s+(?:my\s+)?(.+)', re.IGNORECASE),
            ],

            # ── Priority 18: TASK MANAGEMENT ─────────────────────────────────
            Intent.TASK_MANAGEMENT: [
                re.compile(r'\b(?:queue\s+(?:a\s+)?task|add\s+(?:a\s+)?task|create\s+(?:a\s+)?(?:background\s+)?task|schedule\s+(?:a\s+)?(?:background\s+)?task|run\s+(?:this\s+)?as\s+(?:a\s+)?background\s+task|put\s+this\s+in\s+(?:the\s+)?task\s+queue)\b(?:\s*:\s*|\s+(?:to\s+|for\s+)?|\s+)(.+)', re.IGNORECASE),
                re.compile(r'\b(?:queue\s+task|run\s+(?:this\s+)?in\s+(?:the\s+)?background)\b(?:\s*:\s*|\s+(?:to\s+|for\s+)?|\s+)(.+)', re.IGNORECASE),
                re.compile(r'\brun\s+(.+?)\s+in\s+(?:the\s+)?background\b', re.IGNORECASE),
                re.compile(r'\b(?:check\s+status\s+of\s+(?:my\s+)?task|status\s+of\s+(?:my\s+)?task|task\s+status|show\s+task)\s+([a-zA-Z0-9]+)\b', re.IGNORECASE),
                re.compile(r'\b(?:cancel|stop)\s+(?:my\s+)?task\s+([a-zA-Z0-9]+)\b', re.IGNORECASE),
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
                re.compile(r'\b(?:what\s+(?:window|app(?:lication)?)\s+(?:is\s+)?(?:currently\s+)?active|what\s+app(?:lication)?\s+am\s+i\s+using|current\s+window|active\s+window|foreground\s+window|active\s+app(?:lication)?)\b', re.IGNORECASE),
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
                re.compile(r'\b(?:show\s+audio\s+devices|list\s+audio\s+devices|audio\s+devices|list\s+microphones|show\s+microphones|list\s+speakers|show\s+speakers)\b', re.IGNORECASE),
                re.compile(r'\b(?:switch|change|set)\s+(?:audio\s+)?(?:output|playback|speakers?|device)\s+(?:to\s+)?(.+)', re.IGNORECASE),
                re.compile(r'\b(?:use|set)\s+(.+?)\s+as\s+(?:audio\s+)?(?:output|playback|speakers?)\b', re.IGNORECASE),
                re.compile(r'\bplay\s+(?:an?\s+)?(?:audio\s+)?(?:sound\s+)?(?:effect\s+)?(chime|ping|click|beep|whoosh|chirp|notification(?:\s+sound)?|alert|sound)\b', re.IGNORECASE),
            ],

            # ── Priority 24: RECOMMENDATION ───────────────────────────────────
            Intent.RECOMMENDATION: [
                re.compile(r'\b(?:give\s+me\s+(?:some\s+)?)?recommendations?\s+(?:for|on|about)?\b', re.IGNORECASE),
                re.compile(r'\b(?:recommend|suggest)\s+(?:an?\s+)?(.+)', re.IGNORECASE),
                re.compile(r'\b(?:recommend|suggest)\s*(?:something|anything)?(?:\s+for\s+me)?\b', re.IGNORECASE),
            ],

            # ── Priority 25: RAG SEARCH ───────────────────────────────────────
            Intent.RAG_SEARCH: [
                re.compile(r'\b(?:show\s+me|display)\s+(?:who|what|where|when|why|how|(?:an?|the)\s+explanation|an?\s+overview|what\s+you\s+know\s+about|facts|info|information|details|[a-zA-Z0-9_\s]{2,40})\b', re.IGNORECASE),
                re.compile(r'\b(search|what|who|where|when|why|how|explain|explanation|tell\s+me|describe|summarize|news|latest|update|updates)\b', re.IGNORECASE)
            ],

            # ── Priority: VISUAL RESPONSE SURFACE ────────────────────────────
            Intent.VISUAL_SURFACE: [
                re.compile(r'^show\s+visual\s+response(?:\s+([a-zA-Z0-9_]+))?$', re.IGNORECASE),
                re.compile(r'^(?:please\s+)?(?:show|display|put|bring|let\s+me\s+see)\s+(?:that|it|what\s+you\s+(?:just\s+)?(?:said|told\s+me)|the\s+result|the\s+previous\s+result)(?:\s+(?:again|back))?(?:\s+on\s+(?:the\s+)?screen)?\.?$', re.IGNORECASE),
                re.compile(r'^(?:show|display)\s+that\s+again\.?$', re.IGNORECASE),
                re.compile(r'^(?:can\s+you\s+)?(?:show|display)\s+(?:me\s+)?(?:that|it)(?:\s+(?:again|back))?\.?$', re.IGNORECASE),
                re.compile(r'^(?:put\s+that\s+on\s+screen|let\s+me\s+see\s+it|let\s+me\s+see\s+that|bring\s+that\s+back|bring\s+it\s+back|show\s+the\s+list|show\s+the\s+result|display\s+what\s+you\s+(?:just\s+)?(?:said|told\s+me)|display\s+that)\.?$', re.IGNORECASE),
                re.compile(r'^(?:show|display|put)\s+(?:me\s+)?(?:the\s+)?(?:pairing\s+code|code|ip|ip\s+address|address|url|link|file\s+path|file|path|list|devices|table|status|result)(?:\s+again)?(?:\s+on\s+(?:the\s+)?screen)?\.?$', re.IGNORECASE),
            ]
            # Priority 25: GENERAL_CONVERSATION — fallback, no pattern needed
        }

    
    def route_command(self, user_input: str) -> Tuple[Intent, Dict[str, Any]]:
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

        cache_key = user_input.strip().lower()
        if hasattr(self, '_route_cache') and cache_key in self._route_cache:
            return self._route_cache[cache_key]

        input_lower = user_input.lower().strip()

        def _cache_and_return(res_intent: Intent, res_params: Dict[str, Any]):
            if hasattr(self, '_route_cache'):
                if len(self._route_cache) > 30:
                    self._route_cache.clear()
                self._route_cache[cache_key] = (res_intent, res_params)
            return res_intent, res_params

        # ── Step 1: Deterministic regex, strict priority order ─────────────
        # Fast path: Visual Surface requests ("show that again", "show the pairing code", etc.)
        for pattern in self.patterns.get(Intent.VISUAL_SURFACE, []):
            match = pattern.search(input_lower)
            if match:
                params = self._extract_params(Intent.VISUAL_SURFACE, match, user_input)
                self.logger.debug(f"[DETERMINISTIC] '{user_input[:60]}' -> VISUAL_SURFACE")
                return _cache_and_return(Intent.VISUAL_SURFACE, params)

        for intent in Intent:
            if intent == Intent.GENERAL_CONVERSATION or intent == Intent.VISUAL_SURFACE:
                continue
            # Background task, visual response & active window queries must not be hijacked by DEVICE_CONTROL
            if intent == Intent.DEVICE_CONTROL:
                if any(k in input_lower for k in [
                    "show that again", "show that", "show it again", "show it", "display that again", "display that",
                    "show me that", "show the pairing code", "show me the pairing code", "show the code", "display the pairing code",
                    "show the ip", "display the ip", "put that on screen", "let me see it", "display what you just said",
                    "show visual response",
                    "active window", "foreground window", "current window",
                    "queue a task", "queue task", "create a background task", "create a task",
                    "add a task", "schedule a background task", "schedule a task",
                    "run this as a background task", "run in the background", "run this in the background",
                    "task queue", "put this in the task queue", "cancel task", "stop task",
                    "task status", "background task", "list my tasks", "list my task", "show my tasks", "what tasks"
                ]):
                    continue
            # Preference and learned behavioral rules must not be routed to NOTES
            if intent == Intent.NOTES:
                if any(k in input_lower for k in ["rule", "preference", "prefer", "note that "]):
                    continue
            # Questions and behavioral preferences/rules must not be routed to MEMORY_STORE
            if intent == Intent.MEMORY_STORE:
                if input_lower.endswith('?') or input_lower.startswith(('what', 'which', 'who', 'where', 'when', 'how', 'is my', 'are my', 'do you', 'can you', 'tell me what')):
                    continue
                if any(k in input_lower for k in ["prefer", "preference", "rule", "dark mode", "light mode", "always ", "never ", "remember that i like"]):
                    continue
            # Code structure, syntax or programming queries must not be routed to CALCULATOR
            if intent == Intent.CALCULATOR:
                if any(k in input_lower for k in ["code", "python", "script", "syntax", "class ", "def ", "function", "program"]):
                    continue
            # Window management and background task queries must not be routed to OPEN_APPLICATION
            if intent == Intent.OPEN_APPLICATION:
                if any(k in input_lower for k in [
                    "open windows", "windows are open", "list windows", "show windows",
                    "what windows", "which windows", "active window", "foreground window", "current window",
                    "background task", "queue a task", "queue task", "create a background task",
                    "schedule a background task", "run this as a background task", "run in the background",
                    "run this in the background", "task queue", "put this in the task queue"
                ]):
                    continue
            # Background task & pairing code commands must not be routed to CODE_GENERATION unless user explicitly requests code/script writing
            if intent == Intent.CODE_GENERATION:
                is_explicit_code = any(k in input_lower for k in [
                    "write a python", "write python", "python script", "generate code",
                    "write code", "sample code", "example code", "write a function",
                    "validate code", "validate syntax", "check syntax", "write a script",
                    "create a python", "code to"
                ])
                if not is_explicit_code and any(k in input_lower for k in [
                    "queue a task", "queue task", "create a background task", "create a task",
                    "add a task", "schedule a background task", "schedule a task",
                    "run this as a background task", "run in the background", "task queue",
                    "put this in the task queue", "task status", "cancel task", "stop task", "background task",
                    "pairing code", "code again", "the code again", "what's the code", "whats the code",
                    "what is the code", "what was the code", "repeat the code", "phone pairing code"
                ]):
                    continue
            # Undo, location, and learning queries must not be hijacked by MEMORY_QUERY
            if intent == Intent.MEMORY_QUERY:
                if any(k in input_lower for k in [
                    "undo", "undone", "undoable",
                    "my location", "where am i", "current location", "location source", "how do you know my location",
                    "learned about me", "preferences have you learned"
                ]):
                    continue
            # Specific skill commands must not be routed to RAG_SEARCH
            if intent == Intent.RAG_SEARCH:
                if any(k in input_lower for k in [
                    "queue task", "task status", "cancel task", "stop task", "background task", "tasks are running",
                    "list my task", "show my task", "what tasks",
                    "smart device", "smart home", "active window", "what window", "what app", "what application", "active application", "active app",
                    "learn rule", "my rules", "undo", "audio device", "microphone", "speaker",
                    "where am i", "my location", "location source", "calendar", "events today", "today's events",
                    "paired devices", "connected devices", "devices are paired", "devices are available", "device status",
                    "what preferences", "what you've learned", "what you have learned",
                    "recommend", "suggest", "push to talk", "clipboard", "reminder", "reminders",
                    "my notes", "take a note", "create a note", "save a note", "inbox", "unread email"
                ]):
                    continue
            patterns = self.patterns.get(intent, [])
            for pattern in patterns:
                match = pattern.search(input_lower)
                if match:
                    params = self._extract_params(intent, match, user_input)
                    self.logger.debug(
                        f"[DETERMINISTIC] '{user_input[:60]}' -> {intent.name}"
                    )
                    return _cache_and_return(intent, params)

        # ── Step 2: Semantic fallback — only reached when NO regex matched ──
        if self._semantic_enabled:
            sem_intent, sem_params = self._semantic_fallback(user_input)
            if sem_intent != Intent.GENERAL_CONVERSATION:
                return _cache_and_return(sem_intent, sem_params)

        return _cache_and_return(Intent.GENERAL_CONVERSATION, {})

    def _extract_params(self, intent: Intent, match: re.Match, user_input: str) -> Dict[str, Any]:
        params = {"raw_input": user_input}
        try:
            if intent == Intent.VISUAL_SURFACE:
                text_low = user_input.lower().strip()
                m_spec = re.search(r'show\s+visual\s+response\s+([a-zA-Z0-9_]+)', text_low)
                if m_spec:
                    params["target_type"] = m_spec.group(1).upper()
                else:
                    m_s = re.search(r'\b(pairing\s+code|code|ip\s+address|ip|address|url|link|file\s+path|file|path|list|devices|table|status|result)\b', text_low)
                    if m_s:
                        params["target_type"] = m_s.group(1).replace(" ", "_").upper()
                params["action"] = "show_visual_response"
                return params

            elif intent == Intent.OPEN_APPLICATION:
                text_low = user_input.lower().strip()
                if re.match(r'^(?:go\s+back|navigate\s+back|browser\s+go\s+back|go\s+back\s+in\s+browser)[.!?]?$', text_low):
                    params["action"] = "navigate_back"
                    params["target"] = "browser"
                    return params

                m_yt = re.search(r'\b(?:search\s+(?:on\s+|in\s+)?youtube\s+for|search\s+youtube\s+for)\s+(.+)', user_input, re.IGNORECASE)
                m_gg = re.search(r'\b(?:search\s+(?:on\s+|in\s+)?google\s+for|search\s+google\s+for)\s+(.+)', user_input, re.IGNORECASE)
                if m_yt:
                    query = m_yt.group(1).strip().rstrip('.?!')
                    import urllib.parse
                    params["action"] = "open"
                    params["target"] = "youtube"
                    params["is_website"] = True
                    params["site_name"] = "YouTube"
                    params["url"] = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
                    params["search_query"] = query
                    return params
                elif m_gg:
                    query = m_gg.group(1).strip().rstrip('.?!')
                    import urllib.parse
                    params["action"] = "open"
                    params["target"] = "google"
                    params["is_website"] = True
                    params["site_name"] = "Google"
                    params["url"] = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                    params["search_query"] = query
                    return params

                if match.lastindex and match.lastindex >= 2:
                    action = match.group(1).lower()
                    target = match.group(2).strip()
                else:
                    action = "open"
                    target = match.group(1).strip() if match.lastindex else ""
                
                # Check for kill/terminate process command
                if any(k in user_input.lower() for k in ["kill", "terminate", "process"]):
                    params["action"] = "terminate_process"
                    clean_target = re.sub(r'\b(?:the\s+)?process\b', '', target, flags=re.IGNORECASE).strip()
                    params["target"] = clean_target or target
                else:
                    params["action"] = "open" if action in ["open", "launch", "start", "run", "go to", "visit", "browse to", "navigate to"] or not action else "close"
                    
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
                        if t_clean.startswith(('http://', 'https://')):
                            params["url"] = t_clean
                            params["site_name"] = re.sub(r'^https?://(?:www\.)?', '', t_clean).split('/')[0].split('.')[0].capitalize()
                        elif re.search(r'\.[a-zA-Z]{2,}', t_clean):
                            params["url"] = f"https://{t_clean}"
                            params["site_name"] = t_clean.split('.')[0].capitalize()
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
                if "screenshot" in text_low or "capture" in text_low:
                    params["action"] = "screenshot"
                elif "unmute" in text_low:
                    params["action"] = "unmute"
                elif "mute" in text_low:
                    params["action"] = "mute"
                elif ("logout" in text_low or "lock screen" in text_low or "lock system" in text_low or "lock pc" in text_low or "lock computer" in text_low or "lock workstation" in text_low or (text_low.strip() == "lock") or (re.search(r'\block\b', text_low) and not any(k in text_low for k in ["caps", "num", "scroll", "toggle", "key", "light"]))):
                    params["action"] = "lock"
                elif any(k in text_low for k in ["increase brightness", "raise brightness", "brightness up"]):
                    params["action"] = "increase_brightness"
                elif any(k in text_low for k in ["decrease brightness", "lower brightness", "brightness down"]):
                    params["action"] = "decrease_brightness"
                elif "brightness" in text_low:
                    m_b = re.search(r'\b(?:set\s+brightness\s+(?:to\s+)?|brightness\s+)(\d{1,3})\b', text_low)
                    if m_b:
                        params["action"] = "set_brightness"
                        params["level"] = int(m_b.group(1))
                    else:
                        params["action"] = "get_brightness"
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
                elif "battery" in text_low:
                    params["action"] = "battery"
                elif any(k in text_low for k in ["disk", "storage", "free space"]):
                    params["action"] = "disk"
                elif any(k in text_low for k in ["list all processes", "show all processes", "all running processes", "all processes"]):
                    params["action"] = "list_processes"
                    params["sort_by"] = "cpu" if "cpu" in text_low else "memory"
                elif any(k in text_low for k in ["top processes", "running processes", "cpu usage", "ram usage", "memory usage"]):
                    params["action"] = "top_processes"
                    params["sort_by"] = "cpu" if "cpu" in text_low else "memory"
                elif any(k in text_low for k in ["minimize all", "minimize windows", "show desktop"]):
                    params["action"] = "minimize_all"
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
                elif any(k in text_low for k in ["cpu metrics", "cpu utilization", "per core cpu", "core usage"]):
                    params["action"] = "cpu_metrics"
                elif any(k in text_low for k in ["ram metrics", "ram usage", "memory utilization"]):
                    params["action"] = "ram_metrics"
                elif any(k in text_low for k in ["system info", "system information", "os info", "device specs", "system specs"]):
                    params["action"] = "system_info"
                elif any(k in text_low for k in ["display info", "display information", "screen info", "screen information", "monitor info", "monitor information", "monitor resolution", "screen resolution", "display resolution"]):
                    params["action"] = "display_info"
                elif any(k in text_low for k in ["all disks", "all drives"]):
                    params["action"] = "all_disks"
                elif any(k in text_low for k in ["increase", "raise", "turn up", "volume up"]):
                    params["action"] = "increase_volume"
                elif any(k in text_low for k in ["decrease", "lower", "turn down", "volume down"]):
                    params["action"] = "decrease_volume"
                # ── Wi-Fi ──────────────────────────────────────────────────────
                elif any(k in text_low for k in ["wifi status", "wi-fi status", "wifi connection", "is my wifi", "wifi connected", "connected to wifi", "what wifi", "wireless status", "wireless connection"]):
                    params["action"] = "wifi_status"
                elif re.search(r'\b(?:list|show|scan|find)\s+(?:available\s+|nearby\s+)?(?:wifi|wi-fi|wireless)\s+networks?\b', text_low):
                    params["action"] = "list_wifi_networks"
                elif re.search(r'\b(?:enable|turn\s+on)\s+(?:wifi|wi-fi|wireless)\b', text_low):
                    params["action"] = "enable_wifi"
                elif re.search(r'\b(?:disable|turn\s+off)\s+(?:wifi|wi-fi|wireless)\b', text_low):
                    params["action"] = "disable_wifi"
                elif any(k in text_low for k in ["network speed", "internet speed", "how fast is my internet", "how fast is my network", "how fast is my wifi"]):
                    params["action"] = "network_speed"
                elif any(k in text_low for k in ["network adapter", "network adapters", "network connection", "network connections", "internet adapter", "internet connection", "internet status", "network info", "list adapters", "show adapters", "adapters"]):
                    params["action"] = "network_adapters"
                # ── Bluetooth ──────────────────────────────────────────────────
                elif any(k in text_low for k in ["bluetooth", "bt status", "is bluetooth", "check bluetooth"]):
                    params["action"] = "bluetooth_status"
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
                else:
                    g = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                    params["action"] = g.strip().lower()
            elif intent == Intent.FILE_OPERATIONS:
                text_low = user_input.lower()
                if "duplicate" in text_low:
                    params["action"] = "find_duplicates"
                    params["location"] = "downloads" if "download" in text_low else ("documents" if "document" in text_low else "desktop")
                elif any(k in text_low for k in ["statistic", "stats for", "how many files in", "how many files are in"]):
                    params["action"] = "directory_stats"
                    params["location"] = "downloads" if "download" in text_low else ("documents" if "document" in text_low else "desktop")
                elif any(k in text_low for k in ["largest file", "biggest file"]):
                    params["action"] = "largest_files"
                    params["location"] = "downloads" if "download" in text_low else ("documents" if "document" in text_low else "desktop")
                elif re.search(r'\b(?:how\s+many\s+pages\s+(?:are\s+)?in|information\s+about\s+.*\.pdf|pdf\s+info)\b', text_low):
                    params["action"] = "pdf_info"
                    m = re.search(r'([\w\-.]+\.pdf)', user_input, re.IGNORECASE)
                    params["target"] = m.group(1) if m else ""
                elif re.search(r'\bsplit\s+(?:the\s+)?([\w\-.]+\.pdf)', text_low):
                    params["action"] = "split_pdf"
                    m = re.search(r'([\w\-.]+\.pdf)', user_input, re.IGNORECASE)
                    params["target"] = m.group(1) if m else ""
                    m_p = re.search(r'from\s+page\s+(\d+)\s+to\s+(?:page\s+)?(\d+)', text_low)
                    params["start_page"] = int(m_p.group(1)) if m_p else 1
                    params["end_page"] = int(m_p.group(2)) if m_p else 2
                elif re.search(r'\bmerge\s+(?:these\s+)?pdfs?\b', text_low):
                    params["action"] = "merge_pdfs"
                elif re.search(r'\bextract\s+(?:the\s+)?text\s+from\s+([\w\-.]+\.pdf)', text_low):
                    params["action"] = "extract_pdf_text"
                    m = re.search(r'([\w\-.]+\.pdf)', user_input, re.IGNORECASE)
                    params["target"] = m.group(1) if m else ""
                elif re.search(r'\b(?:find\s+all|search\s+(?:for\s+)?files?|files?\s+larger\s+than|files?\s+modified)\b', text_low):
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
                    m_sz = re.search(r'larger\s+than\s+(\d+)\s*(?:mb|megabytes)?', text_low)
                    if m_sz: params["min_size_mb"] = float(m_sz.group(1))
                    m_days = re.search(r'(?:modified|changed)\s+(?:in\s+the\s+last|within)\s+(\d+)\s+days?', text_low)
                    if m_days: params["modified_days"] = int(m_days.group(1))
                elif re.search(r'\b(delete|remove)\s+(?:the\s+)?(?:file\s+)?([\w\-.]+\.\w+)', text_low):
                    params["action"] = "delete_file"
                    m = re.search(r'\b(?:delete|remove)\s+(?:the\s+)?(?:file\s+)?([\w\-.]+\.\w+)', user_input, re.IGNORECASE)
                    params["target"] = m.group(1).strip() if m else ""
                elif re.search(r'\bmove\s+(?:the\s+)?(?:file\s+)?(.+?)\s+to\s+(.+)', text_low):
                    params["action"] = "move_file"
                    m = re.search(r'\bmove\s+(?:the\s+)?(?:file\s+)?(.+?)\s+to\s+(.+)', user_input, re.IGNORECASE)
                    params["src"] = m.group(1).strip() if m else ""
                    params["dst"] = m.group(2).strip() if m else ""
                elif re.search(r'\brename\s+(?:the\s+)?(?:file\s+)?(.+?)\s+to\s+(.+)', text_low):
                    params["action"] = "rename_file"
                    m = re.search(r'\brename\s+(?:the\s+)?(?:file\s+)?(.+?)\s+to\s+(.+)', user_input, re.IGNORECASE)
                    params["src"] = m.group(1).strip() if m else ""
                    params["new_name"] = m.group(2).strip() if m else ""
                elif re.search(r'\b(?:organize|clean\s+up|clean)\s+(?:my\s+)?(?:desktop|downloads)\b', text_low):
                    params["action"] = "organize_desktop"
                    params["location"] = "downloads" if "download" in text_low else "desktop"
                    params["preview"] = "confirm" not in text_low
                elif re.search(r'\b(create|make|new)\s+(?:a\s+)?(?:folder|directory)\b', text_low):
                    params["action"] = "create_folder"
                    m = re.search(r'\b(?:folder|directory)\s+(?:named\s+|called\s+)?(.+)', user_input, re.IGNORECASE)
                    folder_name = m.group(1).strip() if m else ""
                    folder_name = re.sub(r'\s+on\s+desktop$', '', folder_name, flags=re.IGNORECASE).strip(' "\'')
                    params["name"] = folder_name
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
                text_low = user_input.lower().strip()
                if any(k in text_low for k in ["toggle playback", "play/pause", "play pause"]):
                    params["action"] = "toggle"
                elif any(k in text_low for k in ["summarize", "summary"]):
                    params["action"] = "summarize_video"
                elif any(k in text_low for k in ["queue", "playlist", "what's playing", "now playing"]):
                    params["action"] = "queue_status"
                elif re.search(r'\b(pause|hold)\b', text_low) and not text_low.startswith("play"):
                    params["action"] = "pause"
                elif re.search(r'\b(resume|unpause)\b', text_low):
                    params["action"] = "resume"
                elif re.search(r'\b(stop)\b', text_low) and not text_low.startswith("play"):
                    params["action"] = "stop"
                elif re.search(r'\b(next|skip)\b', text_low) and not text_low.startswith("play"):
                    params["action"] = "next"
                elif re.search(r'\b(previous|prev)\b', text_low) and not text_low.startswith("play"):
                    params["action"] = "previous"
                else:
                    params["action"] = "play"
            elif intent == Intent.DOCUMENT_GENERATION:
                text_low = user_input.lower()
                if "pdf" in text_low:
                    params["doc_type"] = "pdf"
                elif any(k in text_low for k in ["excel", "spreadsheet", "xlsx"]):
                    params["doc_type"] = "xlsx"
                elif any(k in text_low for k in ["powerpoint", "presentation", "slides", "pptx"]):
                    params["doc_type"] = "pptx"
                else:
                    params["doc_type"] = "docx"
                m_t = re.search(r'\b(?:named|called|title(?:d)?)\s+(.+)', user_input, re.IGNORECASE)
                if m_t:
                    params["title"] = m_t.group(1).strip(' "\'')
                else:
                    m_ab = re.search(r'\b(?:about|on|for)\s+(.+)', user_input, re.IGNORECASE)
                    if m_ab:
                        params["title"] = m_ab.group(1).strip(' "\'.').title()
                    else:
                        params["title"] = "Document"
                params["content"] = user_input
            elif intent == Intent.CODE_GENERATION:
                text_low = user_input.lower()
                if any(k in text_low for k in ["validate", "check syntax", "syntax error", "does this code have syntax"]):
                    params["action"] = "validate_syntax"
                elif any(k in text_low for k in ["explain structure", "structure of", "what classes and functions"]):
                    params["action"] = "explain_structure"
                else:
                    params["action"] = "generate_code"
            elif intent == Intent.DAILY_BRIEFING:
                text_low = user_input.lower()
                # Route to calendar_query when creation/event/meeting/appointment keywords present.
                # This ensures "add a meeting tomorrow" reaches process_calendar_query,
                # not the daily-briefing summary handler.
                _calendar_keywords = [
                    "calendar", "event", "events", "meeting", "appointment",
                    "schedule", "create", "add",
                ]
                _creation_verbs = ("create", "schedule", "add", "put", "book", "set up")
                _is_creation = any(text_low.startswith(v) or (" " + v + " ") in text_low for v in _creation_verbs)
                if any(k in text_low for k in _calendar_keywords) or _is_creation:
                    params["action"] = "calendar_query"
                else:
                    params["action"] = "daily_briefing"
            elif intent == Intent.WEATHER_QUERY:
                from extensions.weather_engine import _default_weather_engine
                extracted_loc = _default_weather_engine.extract_location(user_input)
                params["location"] = extracted_loc if extracted_loc else "local"
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
            elif intent == Intent.TASK_MANAGEMENT:
                text_low = user_input.lower()
                m_q = re.search(
                    r'\b(?:queue\s+(?:a\s+)?task|add\s+(?:a\s+)?task|create\s+(?:a\s+)?(?:background\s+)?task|schedule\s+(?:a\s+)?(?:background\s+)?task|run\s+(?:this\s+)?as\s+(?:a\s+)?background\s+task|put\s+this\s+in\s+(?:the\s+)?task\s+queue|queue\s+task|run\s+(?:this\s+)?in\s+(?:the\s+)?background)\b(?:\s*:\s*|\s+(?:to\s+|for\s+)?|\s+)(.+)',
                    user_input, re.IGNORECASE
                )
                m_q2 = re.search(r'\brun\s+(.+?)\s+in\s+(?:the\s+)?background\b', user_input, re.IGNORECASE)
                if m_q:
                    params["action"] = "queue_task"
                    params["goal"] = m_q.group(1).strip()
                elif m_q2:
                    params["action"] = "queue_task"
                    params["goal"] = m_q2.group(1).strip()
                elif ("cancel" in text_low or "stop" in text_low) and ("task" in text_low or text_low.strip() in ("cancel it", "stop it", "cancel that", "abort it")):
                    params["action"] = "cancel_task"
                    m_c = re.search(r'(?:cancel|stop)\s+(?:my\s+)?task\s+([a-zA-Z0-9]+)', text_low)
                    params["task_id"] = m_c.group(1) if m_c else ""
                elif any(k in text_low for k in ["status of task", "task status", "show task", "is it still running", "is it running", "its status", "did it finish"]):
                    params["action"] = "task_status"
                    m_s = re.search(r'(?:status\s+of\s+(?:my\s+)?task|task\s+status|show\s+task)\s+([a-zA-Z0-9]+)', text_low)
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
                if "push to talk" in text_low or "ptt" in text_low:
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
                    r'^(?:can\s+you\s+)?(?:please\s+)?(?:give\s+me\s+(?:some\s+)?)?(?:recommend(?:ations?)?|suggest(?:ions?)?)\s*(?:for|on|about|me)?\s*',
                    '', user_input, flags=re.IGNORECASE
                ).strip()
                clean_query = re.sub(r'^(?:an?|some)\s+', '', clean_query, flags=re.IGNORECASE).strip()
                params["action"] = "recommend"
                params["query"] = clean_query if clean_query else user_input
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

    def execute_single_action(self, user_input: str, user_id: Optional[Any] = None) -> Dict[str, Any]:
        """Execute a single action based on intent routing. Enforces one input -> one action."""
        try:
            # Check if assistant name is present (addressing signal, not mandatory)
            has_assistant_name = contains_assistant_name(user_input)
            
            intent, params = self.route_command(user_input)
            self.logger.info(f"Command routed: {intent.name} (assistant_name_present: {has_assistant_name})")

            # ── Clarification gate (Task 6) ──────────────────────────────────
            # Semantic fallback may signal that the intent is ambiguous and
            # dangerous to execute without confirmation.  Return a safe
            # clarification response without performing any OS action.
            if params.get("_needs_clarification"):
                reason = params.get(
                    "_clarification_reason",
                    "I'm not sure what you mean. Could you clarify?"
                )
            # ── Contextual Resolution Gates (Phase 4.1 Truthfulness) ──────────
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

            result = {"status": "success", "intent": intent.name}
            
            # 1. POWER ACTION
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
                    elif action == "battery":
                        from modules.system_controller import get_battery_status
                        bat = get_battery_status()
                        result["response"] = bat.get("message", "Battery status checked.")
                    elif action == "disk":
                        from modules.system_controller import get_disk_space
                        disk = get_disk_space("C:")
                        result["response"] = disk.get("message", "Disk space checked.")
                    elif action == "top_processes":
                        from modules.system_controller import get_top_processes
                        sort_by = params.get("sort_by", "memory")
                        procs = get_top_processes(n=5, sort_by=sort_by)
                        result["response"] = procs.get("message", "Top processes checked.")
                    elif action == "increase_brightness":
                        from modules.system_controller import adjust_brightness
                        b_res = adjust_brightness(+15)
                        result["response"] = b_res.get("message", "Increased brightness.")
                    elif action == "decrease_brightness":
                        from modules.system_controller import adjust_brightness
                        b_res = adjust_brightness(-15)
                        result["response"] = b_res.get("message", "Decreased brightness.")
                    elif action == "set_brightness":
                        from modules.system_controller import set_brightness
                        lvl = params.get("level", 70)
                        b_res = set_brightness(lvl)
                        result["response"] = b_res.get("message", f"Set brightness to {lvl}%.")
                    elif action == "get_brightness":
                        from modules.system_controller import get_brightness
                        b_res = get_brightness()
                        result["response"] = b_res.get("message", "Brightness checked.")
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
                    elif action == "cpu_metrics":
                        from modules.system_controller import get_cpu_metrics
                        c_res = get_cpu_metrics()
                        result["response"] = c_res.get("message", "CPU metrics checked.")
                    elif action == "ram_metrics":
                        from modules.system_controller import get_ram_metrics
                        r_res = get_ram_metrics()
                        result["response"] = r_res.get("message", "RAM metrics checked.")
                    elif action == "system_info":
                        from modules.system_controller import get_system_info
                        s_res = get_system_info()
                        result["response"] = s_res.get("message", "System info checked.")
                    elif action == "display_info":
                        from modules.system_controller import get_display_info
                        d_res = get_display_info()
                        result["response"] = d_res.get("message", "Display info checked.")
                    elif action == "all_disks":
                        from modules.system_controller import get_all_disks
                        ad_res = get_all_disks()
                        result["response"] = ad_res.get("message", "Drives checked.")
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
                    else:
                        result["status"] = "error"
                        result["response"] = f"Unrecognized device control command: '{user_input}'. Could not execute."
                except Exception as e:
                    result["status"] = "error"
                    result["response"] = f"Device control failed: {e}"
                    
            # 4. OPEN APPLICATION
            elif intent == Intent.OPEN_APPLICATION:
                try:
                    target = params.get("target", "").strip()
                    action = params.get("action", "open")
                    if action == "navigate_back" or target in ["browser back", "back"]:
                        result["status"] = "success"
                        result["target"] = "browser"
                        result["action"] = "navigate_back"
                        result["response"] = "Navigated back."
                        return result
                    if action == "open":
                        clean_target = target.lower().strip()
                        if clean_target in ["dashboard", "my dashboard", "the dashboard", "assistant dashboard", "ui dashboard"] or "dashboard" in clean_target:
                            from core.assistant_core import assistant_core
                            from legacy.tts import speak
                            assistant_core.trigger_ui_action("open_dashboard")
                            result["status"] = "success"
                            result["response"] = "Opening your Dashboard."
                            speak("Opening your Dashboard.")
                            return result
                        if any(w in clean_target for w in ["first result", "top result", "1st result", "first search result", "second result", "2nd result", "second search result", "2nd search result", "third result", "3rd result", "third search result", "3rd search result", "previous result", "previous search result"]):
                            result["status"] = "clarification_needed"
                            result["target"] = "browser_search_result"
                            result["handled"] = True
                            result["response"] = "I cannot see the specific search results (first/second/top results) in your browser to select that result. Please click the result directly in your browser or specify what to search for."
                            return result
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
                            if params.get("search_query"):
                                result["response"] = f"Searching {site_name} for '{params['search_query']}'."
                            else:
                                result["response"] = f"Opening {site_name}."
                            return result
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
                                result["target"] = target
                                result["app_name"] = display
                                result["response"] = f"Opened {display}."
                                speak(f"Opening {display}.")
                            else:
                                # Fallback/adaptation: check if the user intended to open a document/file/presentation
                                file_target = target
                                file_target_clean = re.sub(r'^(?:my|the)\s+', '', file_target, flags=re.IGNORECASE).strip().rstrip('.?!')
                                is_doc_like = any(w in file_target_clean.lower() for w in ["presentation", "document", "slides", "report", "pdf", "sheet", "doc", "file"]) or "." in file_target_clean
                                if is_doc_like:
                                    from modules.system_controller.file_manager import find_file_in_desktop, search_files, resolve_directory_name, open_file
                                    
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
                                            speak(result["response"])
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
                                            speak(result["response"])
                                        else:
                                            f1_name = found_files[1].get("name")
                                            result["status"] = "waiting_for_user"
                                            result["response"] = f"I found {len(found_files)} presentation files: '{f0_name}' and '{f1_name}'. Which one should I open?"
                                            speak(result["response"])
                                        return result

                                msg = (open_dict.get("message") if isinstance(open_dict, dict) else None) \
                                      or f"Could not find '{target}' on your system."
                                result["status"] = "error"
                                result["response"] = msg
                                speak(msg)
                    else:
                        # Close application or terminate process
                        if params.get("action") == "terminate_process" or any(k in user_input.lower() for k in ["kill", "terminate", "process"]):
                            from modules.system_controller.system_controller import terminate_process
                            term_res = terminate_process(name=target)
                            result["status"] = "success" if term_res.get("success") else "error"
                            result["response"] = term_res.get("message", f"Terminated process {target}.")
                            result.update(term_res)
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
                                fname = os.path.basename(found)
                                result["status"] = "success"
                                result["target"] = fname
                                result["path"] = found
                                result["files"] = [{"name": fname, "path": found}]
                                result["response"] = f"Found {fname} on desktop."
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
                        if not src or not dst:
                            result["status"] = "error"
                            result["response"] = "Please specify source file and destination."
                        else:
                            mv_res = move_file(src, dst, user_id=user_id)
                            result["status"] = "success" if mv_res.get("success") else "error"
                            result["response"] = mv_res.get("message", "File moved.")
                            result.update(mv_res)

                    elif action == "rename_file":
                        from modules.system_controller.file_manager import rename_file
                        src = params.get("src") or params.get("target")
                        new_name = params.get("new_name") or params.get("name") or params.get("dst")
                        if not src or not new_name:
                            result["status"] = "error"
                            result["response"] = "Please specify the file name and the new name."
                        else:
                            ren_res = rename_file(src, new_name, user_id=user_id)
                            result["status"] = "success" if ren_res.get("success") else "error"
                            result["response"] = ren_res.get("message", "File renamed.")
                            result.update(ren_res)

                    elif action == "pdf_info":
                        from modules.document_tools import get_pdf_info
                        from modules.system_controller.file_manager import find_file_in_desktop
                        from pathlib import Path
                        tf = params.get("target", "")
                        if not os.path.exists(tf):
                            found = find_file_in_desktop(os.path.basename(tf))
                            if found: tf = found
                            else:
                                for std_dir in ["Downloads", "Documents"]:
                                    cand = Path.home() / std_dir / os.path.basename(tf)
                                    if cand.exists(): tf = str(cand); break
                        p_res = get_pdf_info(tf)
                        result["status"] = "success" if p_res.get("success") else "error"
                        result["response"] = p_res.get("message", "Retrieved PDF info.")
                        result.update(p_res)

                    elif action == "split_pdf":
                        from modules.document_tools import split_pdf
                        from modules.system_controller.file_manager import find_file_in_desktop
                        from pathlib import Path
                        tf = params.get("target", "")
                        if not os.path.exists(tf):
                            found = find_file_in_desktop(os.path.basename(tf))
                            if found: tf = found
                            else:
                                for std_dir in ["Downloads", "Documents"]:
                                    cand = Path.home() / std_dir / os.path.basename(tf)
                                    if cand.exists(): tf = str(cand); break
                        sp_res = split_pdf(tf, start_page=params.get("start_page", 1), end_page=params.get("end_page", 2))
                        result["status"] = "success" if sp_res.get("success") else "error"
                        result["response"] = sp_res.get("message", "Split PDF.")
                        result.update(sp_res)

                    elif action == "merge_pdfs":
                        from modules.document_tools import merge_pdfs
                        from modules.system_controller.file_manager import search_files, resolve_directory_name
                        pdf_list = [f["path"] for f in search_files(root_dir=resolve_directory_name("downloads"), ext="pdf").get("files", [])[:3]]
                        if len(pdf_list) < 2:
                            pdf_list = [f["path"] for f in search_files(root_dir=resolve_directory_name("desktop"), ext="pdf").get("files", [])[:3]]
                        mg_res = merge_pdfs(pdf_list)
                        result["status"] = "success" if mg_res.get("success") else "error"
                        result["response"] = mg_res.get("message", "Merged PDFs.")
                        result.update(mg_res)

                    elif action == "extract_pdf_text":
                        from modules.document_tools import extract_pdf_text
                        from modules.system_controller.file_manager import find_file_in_desktop
                        from pathlib import Path
                        tf = params.get("target", "")
                        if not os.path.exists(tf):
                            found = find_file_in_desktop(os.path.basename(tf))
                            if found: tf = found
                            else:
                                for std_dir in ["Downloads", "Documents"]:
                                    cand = Path.home() / std_dir / os.path.basename(tf)
                                    if cand.exists(): tf = str(cand); break
                        ex_res = extract_pdf_text(tf)
                        result["status"] = "success" if ex_res.get("success") else "error"
                        result["response"] = ex_res.get("message", "Extracted PDF text.")
                        result.update(ex_res)

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
                    
                    # Get the actual authenticated user ID from session
                    user_id = getattr(settings, 'CURRENT_USER_ID', None)
                    
                    # If no user is authenticated, return error
                    if user_id is None:
                        result["status"] = "error"
                        result["response"] = "No authenticated user. Please log in first."
                        return result
                    
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
                        
                        if action == ReminderAction.CREATE:
                            # Create the reminder in database
                            reminder_id = db_manager.add_reminder(
                                user_id,
                                parse_result["task_text"],
                                parse_result["due_at"]
                            )
                            
                            if reminder_id:
                                # Also register with in-memory scheduler
                                due_datetime = datetime.strptime(parse_result["due_at"], "%Y-%m-%d %H:%M:%S")
                                scheduler.add_reminder_at_time(parse_result["task_text"], due_datetime, str(reminder_id), user_id)
                                
                                # Format response
                                due_time = datetime.strptime(parse_result["due_at"], "%Y-%m-%d %H:%M:%S")
                                time_str = due_time.strftime("%I:%M %p") if due_time.date() == datetime.now().date() else due_time.strftime("%B %d at %I:%M %p")
                                
                                response = f"Reminder set: {parse_result['task_text']} at {time_str}"
                                if parse_result.get("recurrence"):
                                    response += f" (recurring {parse_result['recurrence']['frequency']})"
                                
                                result["status"] = "success"
                                result["response"] = response
                            else:
                                result["status"] = "error"
                                result["response"] = "Failed to create reminder."
                        
                        elif action == ReminderAction.LIST:
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
                        
                        elif action == ReminderAction.DELETE:
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
                        
                        elif action == ReminderAction.UPDATE:
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
                        result["response"] = "Music playback started." if success else "Failed to start music playback."
                    elif action == "pause":
                        msg = controller.toggle_play_pause()
                        result["response"] = "Paused media playback." if "Toggled" in str(msg) else msg
                    elif action == "resume":
                        msg = controller.toggle_play_pause()
                        result["response"] = "Resumed media playback." if "Toggled" in str(msg) else msg
                    elif action == "toggle":
                        msg = controller.toggle_play_pause()
                        result["response"] = msg
                    elif action == "stop":
                        result["response"] = controller.media_stop()
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
                    from modules.document_tools import create_docx_document, create_pdf_document, create_excel_spreadsheet, create_presentation
                    doc_type = params.get("doc_type", "docx")
                    title = params.get("title", "Document")
                    content = params.get("content", user_input)
                    
                    if doc_type == "pdf":
                        doc_res = create_pdf_document(title=title, content=content)
                    elif doc_type == "xlsx":
                        headers = ["Item", "Details", "Date"]
                        rows = [["Generated Item", "Created by Smart Assistant", datetime.now().strftime("%Y-%m-%d")]]
                        doc_res = create_excel_spreadsheet(sheet_title=title, headers=headers, rows=rows)
                    elif doc_type == "pptx":
                        slides = [{"type": "content", "title": "Overview", "bullets": [content[:200]]}]
                        doc_res = create_presentation(title=title, slides=slides)
                    else:
                        doc_res = create_docx_document(title=title, content=content)
                        
                    result["status"] = "success" if doc_res.get("success") else "error"
                    result["response"] = doc_res.get("message", "Document generated.")
                    result["filepath"] = doc_res.get("filepath")

                    if result["status"] == "success" and result.get("filepath"):
                        try:
                            from extensions.context_manager import get_manager
                            from instance.config import settings
                            effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1
                            get_manager().add_user_artifact(effective_uid, {
                                "path": result["filepath"],
                                "filename": os.path.basename(result["filepath"]),
                                "type": doc_type,
                                "source_action": "document_generation"
                            })
                        except Exception as e:
                            self.logger.warning(f"Failed to record artifact in context: {e}")
                except Exception as e:
                    self.logger.error(f"Document generation error: {e}")
                    result["status"] = "error"
                    result["response"] = f"Document generation failed: {e}"
                    
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
                    text_low = user_input.lower()
                    if any(k in text_low for k in ["validate", "check syntax", "syntax error", "does this code have syntax"]):
                        from modules.code_generator.utils import validate_code_syntax
                        code_to_check = ""
                        if ":" in user_input:
                            code_to_check = user_input.split(":", 1)[1].strip()
                        elif "```" in user_input:
                            m_c = re.search(r'```(?:python)?(.*?)```', user_input, re.DOTALL)
                            if m_c: code_to_check = m_c.group(1).strip()
                        
                        if not code_to_check:
                            from modules.system_controller.system_controller import get_clipboard_text
                            cb = get_clipboard_text()
                            code_to_check = cb.get("text", "")

                        if not code_to_check:
                            code_to_check = "def example():\n    pass"

                        val_res = validate_code_syntax(code_to_check, language="python")
                        result["status"] = "success" if val_res.get("valid") else "error"
                        result["response"] = val_res.get("message", "Code syntax validated.")
                        result.update(val_res)
                        result["handled"] = True

                    elif any(k in text_low for k in ["explain structure", "structure of", "what classes and functions"]):
                        from modules.code_generator.utils import explain_code_structure
                        code_to_explain = ""
                        if ":" in user_input:
                            code_to_explain = user_input.split(":", 1)[1].strip()
                        elif "```" in user_input:
                            m_c = re.search(r'```(?:python)?(.*?)```', user_input, re.DOTALL)
                            if m_c: code_to_explain = m_c.group(1).strip()
                            
                        if not code_to_explain:
                            from modules.system_controller.system_controller import get_clipboard_text
                            cb = get_clipboard_text()
                            code_to_explain = cb.get("text", "")

                        if not code_to_explain:
                            code_to_explain = "class Example:\n    def run(self):\n        pass"

                        exp_res = explain_code_structure(code_to_explain, language="python")
                        result["status"] = "success" if exp_res.get("success") else "error"
                        result["response"] = exp_res.get("message", "Code structure analyzed.")
                        result.update(exp_res)
                        result["handled"] = True

                    else:
                        from modules.code_generator.main import process_request
                        code_res = process_request(user_input)
                        result.update(code_res)
                        result["response"] = code_res.get("message", "Code generated.")
                        result["handled"] = True
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

                    if action == "calendar_query" or any(k in user_input.lower() for k in ["calendar", "event", "events"]):
                        from modules.calendar_manager import calendar_controller
                        cal_res = calendar_controller.process_calendar_query(user_input, user_id=effective_uid)
                        result["status"] = "success" if cal_res.get("success", True) else "error"
                        result["response"] = cal_res.get("speech_response") or "Calendar query processed."
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

            # 15. TIME QUERY (Pure Local Clock — Bypasses RAG / LLM)
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
                    from legacy.skills import query_memory_first
                    effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user()
                    ans = query_memory_first(effective_uid, user_input)
                    if ans:
                        result["response"] = ans
                        result["handled"] = True
                    else:
                        from extensions.rag_system import RAGSystem
                        rag = RAGSystem()
                        rag_output = rag.process(user_input)
                        if isinstance(rag_output, dict):
                            result["response"] = rag_output.get("response", "I don't have that information in my memory.")
                            result["handled"] = rag_output.get("handled", True)
                        else:
                            result["response"] = str(rag_output)
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
                    else:
                        result["response"] = "I've noted that."
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
                    
            # 19. GENERAL CONVERSATION
            elif intent == Intent.GENERAL_CONVERSATION:
                try:
                    from instance.config import settings
                    from legacy.skills import detect_and_store_fact
                    effective_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user()
                    stored, msg = detect_and_store_fact(effective_uid, user_input)
                    if stored:
                        result["response"] = msg
                        result["handled"] = True
                        return result
                except Exception:
                    pass

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
                            success = tq.cancel(effective_uid, tid)
                            result["status"] = "success" if success else "error"
                            result["task_id"] = tid
                            result["response"] = f"Task {tid} cancelled." if success else f"Could not cancel task {tid}."
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
                                user_tasks = tq.list_user_tasks(effective_uid)
                                if user_tasks:
                                    tid = user_tasks[-1].get("task_id", "")
                            except Exception:
                                pass
                        if tid:
                            status_info = tq.get_status(effective_uid, tid)
                            if status_info:
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
                    from skills.recommendation_engine import recommend
                    query = params.get("query") or user_input
                    rec_res = recommend(query)
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

                    req_type = params.get("target_type")
                    if not req_type:
                        raw_low = user_input.lower()
                        if "pairing" in raw_low or "code" in raw_low:
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

                    is_explicit_again = (
                        "again" in user_input.lower()
                        or "again" in raw_input.lower()
                        or req_type == "AGAIN"
                        or "previous" in raw_input.lower()
                        or "what you just" in raw_input.lower()
                        or "back" in raw_input.lower()
                        or "on screen" in raw_input.lower()
                        or "let me see" in raw_input.lower()
                        or "display what" in raw_input.lower()
                        or "show that" in raw_input.lower()
                    )
                    if req_type == "AGAIN":
                        req_type = None

                    # Check for ambiguity if multiple fresh distinct visual responses exist
                    candidates = dm.get_recent_visual_candidates()
                    if len(candidates) > 1 and not req_type and not is_explicit_again:
                        types = set(c.get("response_type") for c in candidates)
                        if len(types) > 1:
                            result["status"] = "waiting_for_user"
                            result["intent"] = "VISUAL_SURFACE"
                            result["response"] = "I have more than one recent result. Which one would you like me to show?"
                            result["handled"] = True
                            return result

                    # Retrieve last visual response for this user (user-isolated, no regeneration)
                    cached_vr = dm.get_last_visual_response(response_type=req_type, allow_expired=True)

                    if not cached_vr:
                        result["status"] = "success"
                        result["intent"] = "VISUAL_SURFACE"
                        result["response"] = "There is no recent information to display."
                        result["handled"] = True
                        return result

                    # Check freshness
                    now = time.time()
                    created = float(cached_vr.get("created_at", now))
                    ttl = float(cached_vr.get("ttl_seconds", 300.0))
                    if (now - created) > ttl:
                        result["status"] = "expired"
                        result["intent"] = "VISUAL_SURFACE"
                        result["response"] = "I no longer have a current version of that information. Would you like me to retrieve it again?"
                        result["handled"] = True
                        return result

                    # Restore cached visual response without regeneration
                    from core.visual_response import VisualResponse
                    vr_obj = VisualResponse.from_dict(cached_vr)
                    assistant_core.show_visual_response(vr_obj)

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
                except Exception as e:
                    self.logger.error(f"Visual surface execution error: {e}")
                    result["status"] = "error"
                    result["response"] = f"Failed to restore visual response: {e}"
                    result["handled"] = True
            
            # Catch-all for not fully implemented intents
            else:
                result["response"] = f"Intent {intent.name} recognized but execution not fully wired yet."

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

def route_and_execute(user_input: str, user_id: Optional[Any] = None) -> Dict[str, Any]:
    return unified_router.execute_single_action(user_input, user_id=user_id)
