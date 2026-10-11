"""
Multi-Intent Analyzer for PHASE 6

Extends NOVA to detect and parse multiple intents from a single user input.
Handles intent detection, parameter extraction, dependency analysis, and 
confidence scoring while maintaining PHASE 5 backward compatibility.

Architecture:
- Detects multiple intents in single command
- Extracts parameters for each intent separately
- Identifies dependencies between intents
- Orders intents by priority and dependencies
- Returns structured analysis for Goal Planner
"""

import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Optional
from enum import Enum
from datetime import datetime

import sys
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.unified_command_router import Intent, unified_router


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class IntentMatch:
    """Represents a single intent match from pattern detection"""
    intent: Intent
    matched_text: str
    confidence: float
    start_pos: int = 0
    end_pos: int = 0
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionIntent:
    """Intent ready for execution with all metadata"""
    sequence: int  # Execution order (0 = first)
    intent: Intent
    parameters: Dict[str, Any]
    confidence: float
    dependencies: List[int] = field(default_factory=list)  # Indices of dependencies
    context_from_previous: Dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False


@dataclass
class IntentAnalysis:
    """Complete analysis of user input for multiple intents"""
    intents: List[Dict[str, Any]]  # List of intent analysis dicts
    has_multiple_intents: bool
    total_intents: int
    primary_intent: Intent
    secondary_intents: List[Intent] = field(default_factory=list)
    dependencies: Dict[int, int] = field(default_factory=dict)  # intent_idx -> depends_on_idx
    execution_context: Dict[str, Any] = field(default_factory=dict)
    confidence_score: float = 0.0
    requires_sequential_execution: bool = False
    estimated_execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    original_input: str = ""
    timestamp: str = ""


# ============================================================================
# Multi-Intent Analyzer
# ============================================================================

class MultiIntentAnalyzer:
    """
    Analyzes user input to detect and parse multiple intents.
    
    Extends unified_command_router capabilities to handle:
    - Multiple intents in one command
    - Context-aware references
    - Dependent intents
    - Complex goals
    """
    
    # Multi-intent connectors
    INTENT_CONNECTORS = [
        (r'\band\s+then\b', 0.9),     # "open Notepad and then type hello"
        (r'\bafter\s+that\b', 0.9),    # "create folder after that create file"
        (r'\bfollowed\s+by\b', 0.9),   # "search for AI followed by open first result"
        (r'(?<!\bfor\s)(?<!\bby\s)\bnext\b(?!\s+(?:week|weekend|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday|day|time|morning|afternoon|evening|night|step|item))\b', 0.85),           # "open Notepad next write test"
        (r'\bfinally\b', 0.85),        # "create folder, create file, finally open file"
        (r'\band\b', 0.8),             # "play music and set reminder"
        (r'\bthen\b', 0.85),           # "play music then set reminder"
        (r'\balso\b', 0.7),            # "play music also set reminder"
        (r'\bafter\b', 0.9),           # "after playing music, set reminder"
        (r'\bbefore\b', 0.9),          # "before playing music, set reminder"
        (r'\bwhile\b', 0.85),          # "while playing music, set reminder"
        (r'(?<!\d\s)\bplus\b(?!\s*\d)', 0.75),           # "play music plus set reminder"
        (r'[,;]\s*(?!(?:not\s+(?:the\s+)?(?:other|one|that|this)|instead\s+of|rather\s+than)\b)(?=\w)', 0.6),       # "play music, set reminder" or "play music; set reminder"
    ]
    
    # Dependency patterns (intent_A depends on intent_B if pattern matches)
    DEPENDENCY_PATTERNS = {
        # EMAIL depends on WEATHER
        (Intent.EMAIL, Intent.WEATHER_QUERY): r'send.*weather|email.*weather|results to',
        
        # EMAIL depends on MUSIC
        (Intent.EMAIL, Intent.MUSIC): r'send.*song|email.*music',
        
        # EMAIL depends on REMINDERS
        (Intent.EMAIL, Intent.REMINDERS): r'send.*reminder|email.*reminder',
        
        # REMINDERS depends on MUSIC/WEATHER/EMAIL (contextual)
        (Intent.REMINDERS, Intent.MUSIC): r'remind.*music|remember.*song',
        (Intent.REMINDERS, Intent.WEATHER_QUERY): r'remind.*weather',
        (Intent.REMINDERS, Intent.EMAIL): r'remind.*email',

        # OPEN_APPLICATION (open it) depends on FILE_OPERATIONS (find file)
        (Intent.OPEN_APPLICATION, Intent.FILE_OPERATIONS): r'find.*open|search.*open|open\s+(?:it|that|them|the\s+file)',

        # Browser search depends on browser open
        (Intent.RAG_SEARCH, Intent.OPEN_APPLICATION): r'open.*search|launch.*search|browser.*search',
        (Intent.OPEN_APPLICATION, Intent.OPEN_APPLICATION): r'(?:open|launch|start|run).*?(?:search|look\s+up)|chrome.*search|youtube.*search|search.*?(?:open|click|select)|(?:first|second|third|top)\s+result',

        # DEVICE_CONTROL (typing) depends on OPEN_APPLICATION (app open)
        (Intent.DEVICE_CONTROL, Intent.OPEN_APPLICATION): r'(?:open|launch|start).*?(?:type|write)|type.*after.*open',

        # CALCULATOR depends on OPEN_APPLICATION
        (Intent.CALCULATOR, Intent.OPEN_APPLICATION): r'(?:open|launch|start).*?(?:calc|calculate|compute)',

        # FILE_OPERATIONS sequential dependencies
        (Intent.FILE_OPERATIONS, Intent.FILE_OPERATIONS): r'create.*(?:folder|directory).*create.*file|create.*file.*inside|create.*rename|create.*open',

        # TASK_MANAGEMENT status query depends on task creation
        (Intent.TASK_MANAGEMENT, Intent.TASK_MANAGEMENT): r'create.*status|task.*status|clean.*status|logs.*status|create.*running|task.*running|status.*running|clean.*running',

        # DEVICE_CONTROL check depends on device control action
        (Intent.DEVICE_CONTROL, Intent.DEVICE_CONTROL): r'turn.*(?:on|off).*whether|toggle.*whether|set.*is\s+it|turn.*is\s+it',

        # DOCUMENT_GENERATION sequential dependencies (e.g., export/save copy depends on creation)
        (Intent.DOCUMENT_GENERATION, Intent.DOCUMENT_GENERATION): r'(?:create|generate|write|make).*?(?:save|export|convert)|(?:save|export|make)\s+(?:a\s+|an\s+)?(?:pdf|docx|excel|presentation|ppt|pptx)\s+copy',

        # OPEN_APPLICATION (open saved file) depends on DOCUMENT_GENERATION
        (Intent.OPEN_APPLICATION, Intent.DOCUMENT_GENERATION): r'(?:create|generate|write|make|save|export).*?(?:open|view|launch)|open\s+(?:the\s+saved\s+file|saved\s+file|the\s+file|it|that|the\s+document|the\s+pdf)',

        # OPEN_APPLICATION (open search result) depends on RAG_SEARCH
        (Intent.OPEN_APPLICATION, Intent.RAG_SEARCH): r'(?:search|find|look\s+up).*?(?:open|click|select|view)',
    }
    
    # Confidence thresholds
    MIN_CONFIDENCE = 0.7
    HIGH_CONFIDENCE = 0.9
    
    def __init__(self):
        """Initialize multi-intent analyzer"""
        self.router = unified_router
        self.primary_intent_cache = {}
        print("[MULTI_INTENT_ANALYZER] Initialized successfully")
    
    def analyze(self, user_input: str) -> IntentAnalysis:
        """
        Analyze user input for multiple intents.
        
        Args:
            user_input: User's command text
            
        Returns:
            IntentAnalysis with complete breakdown
        """
        if not user_input or not user_input.strip():
            return self._empty_analysis(user_input)
        
        effective_input = user_input.strip()
        try:
            from extensions.dialogue_state_manager import normalize_speech_extensions
            effective_input = normalize_speech_extensions(effective_input)
        except Exception:
            pass

        # Normalize natural conversational preambles
        # e.g. "I need a quick note, open Notepad and write hello" -> "open Notepad and write hello"
        m_pre = re.match(
            r'^(?:i\s+(?:need|want)\s+(?:to\s+)?(?:do|make|take|have)?\s*(?:a\s+)?(?:quick\s+)?(?:note|calculation|document)[,\s:]+)(.+)$',
            effective_input,
            re.IGNORECASE
        )
        if m_pre:
            effective_input = m_pre.group(1).strip()

        # Multi-file list expansion (Section 15: e.g. "create these files: report.txt, report_final.txt, notes.txt")
        m_files_list = re.match(r'^(?:create|make)\s+(?:these\s+)?files?\s*:\s*(.+)$', effective_input, re.IGNORECASE)
        if m_files_list:
            raw_items = re.split(r'[,;]|\band\b', m_files_list.group(1))
            items = [it.strip() for it in raw_items if it.strip()]
            if len(items) > 1:
                effective_input = " and ".join([f"create {it}" for it in items])

        # Multi-file compound expansion (Section 15: e.g. "create report.txt and report_final.txt")
        m_files_compound = re.match(r'^(?:create|make|new)\s+(?:files?\s+)?([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+(?:\s*,\s*[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)*\s+and\s+[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)$', effective_input, re.IGNORECASE)
        if m_files_compound:
            raw_files = re.split(r'[,;]|\band\b', m_files_compound.group(1))
            files = [f.strip() for f in raw_files if f.strip() and '.' in f]
            if len(files) > 1:
                effective_input = " and ".join([f"create {f}" for f in files])

        # Multi-folder expansion (Section 16: e.g. "create folders AI and ML", "create Projects, Notes and Tests folders")
        m_folders = re.match(r'^(?:create|make)\s+folders?\s+(.+)$', effective_input, re.IGNORECASE)
        if m_folders:
            raw_f_items = re.split(r'[,;]|\band\b', m_folders.group(1))
            f_items = [it.strip() for it in raw_f_items if it.strip() and it.lower() not in ("called", "named")]
            if len(f_items) > 1:
                effective_input = " and ".join([f"create folder {it}" for it in f_items])
        else:
            m_folders_post = re.match(r'^(?:create|make)\s+(.+?)\s+folders?$', effective_input, re.IGNORECASE)
            if m_folders_post and not effective_input.lower().startswith(("create folder ", "create a folder ")):
                raw_f_items = re.split(r'[,;]|\band\b', m_folders_post.group(1))
                f_items = [it.strip() for it in raw_f_items if it.strip() and it.lower() not in ("called", "named")]
                if len(f_items) > 1:
                    effective_input = " and ".join([f"create folder {it}" for it in f_items])

        # Multi-app close expansion (e.g. "close Calculator and Notepad", "close Calculator, Notepad")
        m_close_compound = re.match(r'^(?:close|quit|exit|terminate|kill|shut)\s+([a-zA-Z0-9_\-\s]+(?:\s*,\s*[a-zA-Z0-9_\-\s]+)*\s+and\s+[a-zA-Z0-9_\-\s]+)$', effective_input, re.IGNORECASE)
        if m_close_compound:
            remainder = m_close_compound.group(1).strip()
            if not re.search(r'\b(close|quit|exit|terminate|kill|shut|open|launch|start|run)\b', remainder, re.IGNORECASE):
                raw_apps = re.split(r'[,;]|\band\b', remainder)
                apps = [a.strip() for a in raw_apps if a.strip() and a.lower() not in ("called", "named", "and", "the", "app", "apps", "both", "both of them", "them")]
                if len(apps) > 1:
                    effective_input = " and ".join([f"close {a}" for a in apps])

        # Multi-app open expansion (e.g. "open Calculator and Notepad", "open Calculator, Notepad")
        m_open_compound = re.match(r'^(open|launch|start|run)\s+([a-zA-Z0-9_\-\s]+(?:\s*,\s*[a-zA-Z0-9_\-\s]+)*\s+and\s+[a-zA-Z0-9_\-\s]+)$', effective_input, re.IGNORECASE)
        if m_open_compound:
            verb = m_open_compound.group(1).lower()
            remainder = m_open_compound.group(2).strip()
            if not re.search(r'\b(close|quit|exit|terminate|kill|shut|open|launch|start|run|search|type|write|look up|find|google|calculate|calc|play|set)\b', remainder, re.IGNORECASE):
                raw_apps = re.split(r'[,;]|\band\b', remainder)
                apps = [a.strip() for a in raw_apps if a.strip() and a.lower() not in ("called", "named", "and", "the", "app", "apps", "both", "both of them", "them")]
                if len(apps) > 1:
                    effective_input = " and ".join([f"{verb} {a}" for a in apps])

        # Subordinate resultative / participle clauses (e.g. "I want Notepad open with hello typed into it", "Open Notepad with hello already typed")
        m_participle = re.match(
            r'^(.+?)\s+with\s+(.+?)\s+(?:already\s+)?(?:typed|written|put|inserted)(?:\s+(?:in|into|inside|there))?(?:\s+it)?[.!?]?$',
            effective_input,
            re.IGNORECASE
        )
        if m_participle:
            effective_input = f"{m_participle.group(1).strip()} and type {m_participle.group(2).strip()}"

        # Check for multiple intents
        has_connectors = self._detect_connectors(effective_input)
        
        if has_connectors:
            # Multi-intent analysis
            return self._analyze_multiple_intents(effective_input)
        else:
            # Single-intent analysis (backward compatible)
            return self._analyze_single_intent(effective_input)
    
    def _detect_connectors(self, user_input: str) -> bool:
        """Detect if input contains multi-intent connectors"""
        input_lower = user_input.lower()
        
        # Guard: Document generation specs (e.g. "Excel file with name and marks and add formulas")
        if re.search(r'\b(?:create|make|generate|write|build)\s+.*(?:excel|spreadsheet|document|presentation|powerpoint|pdf|docx|pptx|xlsx|ppt|slides)\b', input_lower):
            if not any(k in input_lower for k in ["then", "and email", "and send", "and open", "and play", "and set", "and reminder"]):
                return False

        # Guard: Compound document topics and artifact editing (e.g. "Add deadlock detection and recovery", "Gather everything ... and make a powerful PPT")
        if re.search(r'\b(?:add\s+.*(?:detection|recovery|prevention|avoidance|section|slide)|gather\s+.*(?:and\s+make|and\s+create|and\s+build))\b', input_lower):
            return False

        # Guard: Contextual reminder clauses (e.g. "tomorrow I have to go to movie at 3pm, remind me at 2pm")
        if re.search(r'\b(?:so\s+)?(?:can\s+you\s+|could\s+you\s+|please\s+)?remind\s+me\b', input_lower) and any(k in input_lower for k in ["have to", "need to", "going to", "want to", "at ", "tomorrow", "today"]):
            if not any(k in input_lower for k in ["then", "and open", "and play", "and create", "and launch"]):
                return False

        # Guard: Arithmetic calculation expressions (e.g. "what is 45 plus 55", "10 + 20")
        if re.search(r'\b(?:what\s+is\s+)?[\d.]+\s*(?:plus|minus|times|multiplied\s+by|divided\s+by|\+|\-|\*|\/)\s*[\d.]+', input_lower):
            return False

        # Guard: Natural goal creation statements (e.g. "I need to prepare another presentation for next week")
        if re.match(r'^(?:i\s+)?(?:need\s+to|have\s+to|must|should|want\s+to)\s+(?:prepare|finish|complete|study|work\s+on|finalize|review|practice|research|draft|write\s+up|put\s+together)\b', input_lower):
            if not any(k in input_lower for k in ["and then", "after that", "then open", "then play", "then create"]):
                return False

        # Guard: Game discovery / download and play expressions (e.g. "what games can I download and play on this PC")
        if any(k in input_lower for k in ["download and play", "games can i", "what games", "recommend games", "compatible games", "games to play", "games for this pc"]):
            if not any(k in input_lower for k in ["then", "and email", "and send", "and reminder", "and set reminder"]):
                return False

        for pattern, _ in self.INTENT_CONNECTORS:
            if re.search(pattern, input_lower):
                return True
        
        # Check action verb boundaries without explicit connectors (e.g. 'open calculator open notepad')
        if len(self._split_segment_by_action_boundaries(user_input)) > 1:
            return True
            
        return False
    
    def _analyze_single_intent(self, user_input: str) -> IntentAnalysis:
        """
        Analyze single intent (PHASE 5 backward compatible).
        
        Falls back to existing unified router.
        """
        norm = user_input.lower().strip().rstrip('.?!')
        if norm in ("hello", "hi", "hey", "good morning", "good afternoon", "good evening"):
            intent = Intent.GENERAL_CONVERSATION
            params = {"raw_input": user_input}
            confidence = 0.98
        elif re.match(r'^(?:is|check\s+if)\s+.+?\s+(?:open|running|active)[.!?]?$', norm):
            intent = Intent.DEVICE_CONTROL
            params = {"raw_input": user_input}
            confidence = 0.95
        elif re.match(r'^(?:what(?:\'s|\s+is)\s+(?:my\s+)?(?:current\s+|working\s+)?(?:directory|folder|path)|pwd)[.!?]?$', norm):
            intent = Intent.FILE_OPERATIONS
            params = {"raw_input": user_input}
            confidence = 0.95
        elif user_input in self.primary_intent_cache:
            intent, params, confidence = self.primary_intent_cache[user_input]
        else:
            intent, params = self.router.route_command(user_input)
            confidence = self._calculate_single_intent_confidence(intent, user_input)
            if len(self.primary_intent_cache) < 500:
                self.primary_intent_cache[user_input] = (intent, params, confidence)
        
        from core.semantic_understanding import SemanticCommand
        single_cmd = SemanticCommand(
            user_text=user_input,
            normalized_text=user_input.lower().strip(),
            intent=intent.name,
            action=params.get("action", intent.name.lower()),
            parameters=dict(params),
            confidence=confidence,
        )
        analysis = IntentAnalysis(
            intents=[{
                "intent": intent,
                "confidence": confidence,
                "parameters": params,
                "dependencies": [],
                "sequence_position": 0,
                "matched_text": user_input,
                "semantic_command": single_cmd,
            }],
            has_multiple_intents=False,
            total_intents=1,
            primary_intent=intent,
            secondary_intents=[],
            dependencies={},
            confidence_score=confidence,
            requires_sequential_execution=False,
            estimated_execution_time=0.5,
            original_input=user_input,
            timestamp=datetime.now().isoformat()
        )
        
        return analysis
    
    def _analyze_multiple_intents(self, user_input: str) -> IntentAnalysis:
        """Analyze input with multiple intents detected"""
        
        # Step 1: Split by connectors
        segments = self._split_by_connectors(user_input)
        
        if len(segments) == 1:
            # Fallback to single-intent if split failed
            return self._analyze_single_intent(user_input)
        
        # Step 2: Analyze each segment
        intent_matches = []
        for segment_text, segment_idx in segments:
            clean_seg = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*', '', segment_text, flags=re.IGNORECASE).strip()
            clean_seg = re.sub(r'^(?:can\s+you\s+|could\s+you\s+|please\s+)+', '', clean_seg, flags=re.IGNORECASE).strip()
            effective_seg = clean_seg if clean_seg else segment_text
            seg_lower = effective_seg.lower().strip()

            # Contextual dependent clause recognition based on upstream matches
            is_status_query = bool(re.search(r'\b(?:check|get|show|tell\s+me|what(?:\'s|\s+is))\s+(?:its|the)\s+status\b', seg_lower)) or seg_lower in ("what's its status", "what is its status", "its status", "check its status")
            is_running_query = bool(re.search(r'\b(?:tell\s+me\s+whether\s+it\s+is\s+(?:still\s+)?running|is\s+it\s+(?:still\s+)?running|check\s+if\s+it(?:\'s|\s+is)\s+(?:still\s+)?running)\b', seg_lower))
            is_state_query = bool(re.search(r'\b(?:tell\s+me\s+whether\s+it\s+is|is\s+it|check\s+if\s+it(?:\'s|\s+is))\s+(?:on|off)\b', seg_lower))
            is_open_anaphora = bool(re.match(r'^(?:open|launch)\s+(?:it|that|(?:the\s+)?(?:saved\s+|generated\s+)?file)[.!]?$', seg_lower))

            upstream_match = intent_matches[-1] if intent_matches else None
            upstream_intent = upstream_match.intent if upstream_match else None
            upstream_target = str((upstream_match.context.get("parameters", {}) if upstream_match else {}).get("target", "")).lower()

            # Inherit action verb from upstream segment if current segment has no leading action verb
            if upstream_match and upstream_intent == Intent.OPEN_APPLICATION:
                up_params = upstream_match.context.get("parameters", {})
                up_action = up_params.get("action")
                has_verb = bool(re.match(r'^(?:open|launch|start|run|close|quit|exit|terminate|kill|shut|create|make|delete|remove|save|type|write|search|check|get|tell|show|what|is|how|set|pair|connect)\b', seg_lower))
                if not has_verb:
                    if up_action == "close" or "close" in upstream_match.matched_text.lower():
                        effective_seg = f"close {effective_seg}"
                        seg_lower = effective_seg.lower()
                    elif up_action == "open" or "open" in upstream_match.matched_text.lower():
                        effective_seg = f"open {effective_seg}"
                        seg_lower = effective_seg.lower()

            # Check for correction segment modifying upstream intent
            # e.g. "no, I meant Python programming language documentation", "I meant X", "actually search for X"
            is_correction_seg = bool(re.search(r'^(?:(?:oh\s+)?no[,\s]+)?(?:i\s+meant|actually[,\s]+(?:i\s+meant\s+)?|search\s+for\s+.+\s+instead|change\s+that\s+to\s+)\b', seg_lower))
            if is_correction_seg and intent_matches:
                m_c = re.search(r'^(?:(?:oh\s+)?no[,\s]+)?(?:i\s+meant|actually[,\s]+(?:i\s+meant\s+)?|change\s+that\s+to)\s+(.+)', seg_lower)
                if not m_c:
                    m_c = re.search(r'^(?:actually\s+search\s+for|search\s+for)\s+(.+?)(?:\s+instead)?$', seg_lower)
                corr_target = m_c.group(1).strip().rstrip('.?!') if m_c else ""
                corr_target = re.sub(r'^(?:search\s+(?:for\s+)?|for\s+)', '', corr_target, flags=re.IGNORECASE).strip()
                
                target_match = None
                for candidate_m in reversed(intent_matches):
                    params_c = candidate_m.context.get("parameters", {})
                    if params_c.get("action") == "search_web" or "search_query" in params_c or "search" in candidate_m.matched_text.lower():
                        target_match = candidate_m
                        break
                if not target_match:
                    target_match = intent_matches[-1]
                
                if target_match:
                    params_t = target_match.context.get("parameters", {})
                    if params_t.get("action") == "search_web" or "search_query" in params_t or "search" in target_match.matched_text.lower():
                        new_cmd = f"search google for {corr_target}"
                        new_intent, new_params = self.router.route_command(new_cmd)
                        new_params["raw_input"] = new_cmd
                        target_match.intent = new_intent
                        target_match.matched_text = new_cmd
                        target_match.context["parameters"] = new_params
                        target_match.confidence = 0.95
                        continue
                    elif target_match.intent == Intent.OPEN_APPLICATION:
                        new_cmd = f"open {corr_target}"
                        new_intent, new_params = self.router.route_command(new_cmd)
                        new_params["raw_input"] = new_cmd
                        target_match.intent = new_intent
                        target_match.matched_text = new_cmd
                        target_match.context["parameters"] = new_params
                        target_match.confidence = 0.95
                        continue

            # Ignore standalone filler negation if previous is meaningful
            if seg_lower in ("no", "oh no", "wait", "actually", "not that") and intent_matches:
                continue

            is_browser_upstream = (
                upstream_intent == Intent.OPEN_APPLICATION
                and (
                    any(b in upstream_target for b in ["chrome", "edge", "msedge", "firefox", "brave", "browser"])
                    or any(b in (upstream_match.matched_text if upstream_match else "").lower() for b in ["chrome", "edge", "firefox", "browser"])
                )
            )
            is_search_clause = bool(re.search(r'\b(?:search(?:\s+(?:for|on|in))?|look\s+up|find)\s+(.+)', seg_lower))

            if (is_status_query or is_running_query) and upstream_intent == Intent.TASK_MANAGEMENT:
                intent = Intent.TASK_MANAGEMENT
                params = {"action": "task_status", "raw_input": segment_text}
                confidence = 0.95
            elif (is_status_query or is_state_query) and upstream_intent == Intent.DEVICE_CONTROL:
                intent = Intent.DEVICE_CONTROL
                params = {"action": "check_state", "raw_input": segment_text}
                confidence = 0.95
            elif is_browser_upstream and is_search_clause:
                m_sq = re.search(r'\b(?:search(?:\s+(?:for|on|in))?|look\s+up|find)\s+(.+)', segment_text, re.IGNORECASE)
                raw_term = m_sq.group(1).strip().rstrip('.?!') if m_sq else ""
                clean_term = re.sub(r'^(?:(?:the\s+)?(?:web|internet|google)\s+(?:for\s+)?|for\s+)', '', raw_term, flags=re.IGNORECASE).strip()
                constructed_cmd = f"search google for {clean_term}"
                intent, params = self.router.route_command(constructed_cmd)
                params["raw_input"] = constructed_cmd
                confidence = 0.95
            elif is_state_query:
                intent = Intent.DEVICE_CONTROL
                params = {"action": "check_state", "raw_input": segment_text}
                confidence = 0.95
            elif is_status_query or is_running_query:
                intent = Intent.TASK_MANAGEMENT
                params = {"action": "task_status", "raw_input": segment_text}
                confidence = 0.95
            elif is_open_anaphora and (upstream_intent in (Intent.FILE_OPERATIONS, Intent.DOCUMENT_GENERATION, Intent.MEMORY_STORE) or any(m.intent in (Intent.FILE_OPERATIONS, Intent.DOCUMENT_GENERATION) for m in intent_matches)):
                intent = Intent.OPEN_APPLICATION
                params = {"action": "open_file", "raw_input": segment_text}
                confidence = 0.95
            else:
                intent, params = self.router.route_command(effective_seg)
                if isinstance(params, dict) and "raw_input" not in params:
                    params["raw_input"] = effective_seg
                confidence = self._calculate_segment_confidence(intent, effective_seg)
                if isinstance(params, dict) and params.get("_semantic_confidence"):
                    confidence = max(confidence, float(params["_semantic_confidence"]))
            
            # Only include matches with sufficient confidence
            if confidence >= self.MIN_CONFIDENCE:
                match = IntentMatch(
                    intent=intent,
                    matched_text=segment_text,
                    confidence=confidence,
                    context={"segment_index": segment_idx, "parameters": params}
                )
                intent_matches.append(match)

        # Guard: Purge spurious MUSIC matches if overall query is about games without music terms
        input_lower_all = user_input.lower()
        is_game_overall = any(k in input_lower_all for k in ["game", "games", "gaming", "steam", "download and play"])
        has_music_overall = any(k in input_lower_all for k in ["song", "songs", "track", "tracks", "music", "spotify", "album", "playlist", "audio"])
        if is_game_overall and not has_music_overall:
            intent_matches = [m for m in intent_matches if m.intent != Intent.MUSIC]

        if not intent_matches:
            # No valid intents found, treat as general conversation
            return self._analyze_single_intent(user_input)
        
        # Step 3: Detect dependencies
        dependencies = self._detect_dependencies(intent_matches, user_input)
        
        # Step 4: Order by priority
        ordered_intents = self._order_by_priority(intent_matches, dependencies)
        
        # Step 5: Build IntentAnalysis
        intents_list = []
        import uuid
        from core.semantic_understanding import SemanticCommand
        master_cmd_id = f"cmd_{uuid.uuid4().hex[:12]}"
        for seq_idx, (match, position) in enumerate(ordered_intents):
            sub_text = match.matched_text or user_input
            sub_params = dict(match.context.get("parameters", {}))
            sub_cmd = SemanticCommand(
                command_id=f"cmd_{uuid.uuid4().hex[:12]}",
                parent_command_id=master_cmd_id,
                user_text=sub_text,
                normalized_text=sub_text.lower().strip(),
                intent=match.intent.name,
                action=sub_params.get("action", match.intent.name.lower()),
                parameters=sub_params,
                confidence=match.confidence,
            )
            intents_list.append({
                "intent": match.intent,
                "confidence": match.confidence,
                "parameters": sub_params,
                "dependencies": dependencies.get(seq_idx, []),
                "sequence_position": seq_idx,
                "matched_text": match.matched_text,
                "semantic_command": sub_cmd,
            })
        
        # Calculate average confidence
        avg_confidence = sum(m.confidence for m, _ in ordered_intents) / len(ordered_intents)
        
        analysis = IntentAnalysis(
            intents=intents_list,
            has_multiple_intents=True,
            total_intents=len(intents_list),
            primary_intent=ordered_intents[0][0].intent,
            secondary_intents=[m.intent for m, _ in ordered_intents[1:]],
            dependencies=dependencies,
            execution_context={"segments": len(segments), "original_input": user_input},
            confidence_score=avg_confidence,
            requires_sequential_execution=len(ordered_intents) > 1,
            estimated_execution_time=0.5 + (len(ordered_intents) * 0.3),
            original_input=user_input,
            timestamp=datetime.now().isoformat()
        )
        
        return analysis
    
    def _split_segment_by_action_boundaries(self, text: str) -> List[str]:
        """
        Split a clause into sequential actions if it contains multiple independent action verbs
        without explicit connectors (e.g. 'open calculator open notepad').
        """
        stripped = text.strip()
        if not stripped:
            return []
            
        disallowed_preceding = {
            "for", "on", "in", "to", "with", "about", "called", "named",
            "that", "a", "an", "the", "my", "as", "and", "then", "or",
            "another", "new", "fresh", "inside", "into", "of", "from"
        }
        
        # Action verbs that can start a new command
        pattern = r'\b(open|launch|start|run|close|quit|exit|terminate|kill|create|make|search|type|write|calculate|compute|play|delete|save)\b'
        
        matches = list(re.finditer(pattern, stripped, re.IGNORECASE))
        if len(matches) <= 1:
            return [stripped]
            
        for m in matches[1:]:
            pos = m.start()
            prefix = stripped[:pos].strip()
            suffix = stripped[pos:].strip()
            
            # 1. Check preceding word
            pre_words = prefix.lower().split()
            if not pre_words or pre_words[-1] in disallowed_preceding:
                continue
                
            # 2. Do not split if prefix starts with typing (typing text can contain verbs)
            if prefix.lower().startswith(("type ", "write ")):
                continue
                
            # 3. Verify prefix is a valid actionable command
            intent_pre, _ = self.router.route_command(prefix)
            if intent_pre == Intent.GENERAL_CONVERSATION:
                continue
                
            # 4. Verify suffix is a valid actionable command
            intent_suf, _ = self.router.route_command(suffix)
            if intent_suf == Intent.GENERAL_CONVERSATION:
                continue
                
            # Valid boundary found! Split and recursively process suffix
            return [prefix] + self._split_segment_by_action_boundaries(suffix)
            
        return [stripped]

    def _split_by_connectors(self, user_input: str) -> List[Tuple[str, int]]:
        """
        Split user input by connector patterns and action boundaries.
        
        Returns list of (segment_text, segment_index) tuples
        """
        raw_segments = []
        input_lower = user_input.lower()
        
        # Find all connector positions
        connector_positions = []
        for pattern, _ in self.INTENT_CONNECTORS:
            for match in re.finditer(pattern, input_lower):
                connector_positions.append((match.start(), match.end(), match.group()))
        
        if connector_positions:
            # Sort by start asc, length desc so longer connectors (e.g. 'and then') take precedence
            connector_positions.sort(key=lambda x: (x[0], -(x[1] - x[0])))
            
            # Filter overlapping connectors
            filtered_positions = []
            last_match_end = -1
            for start, end, match_str in connector_positions:
                if start >= last_match_end:
                    filtered_positions.append((start, end, match_str))
                    last_match_end = end
            
            connector_positions = filtered_positions
            
            # Split by connectors
            last_end = 0
            for conn_start, conn_end, connector in connector_positions:
                segment = user_input[last_end:conn_start].strip()
                if segment:
                    raw_segments.append(segment)
                last_end = conn_end
            
            final_segment = user_input[last_end:].strip()
            if final_segment:
                raw_segments.append(final_segment)
        else:
            raw_segments = [user_input]
            
        # Post-split each segment by action verb boundaries (e.g. 'open calculator open notepad')
        final_segments = []
        seg_idx = 0
        for seg in raw_segments:
            sub_segments = self._split_segment_by_action_boundaries(seg)
            for sub in sub_segments:
                if sub.strip():
                    final_segments.append((sub.strip(), seg_idx))
                    seg_idx += 1
        
        return final_segments if final_segments else [(user_input, 0)]
    
    def _calculate_single_intent_confidence(self, intent: Intent, user_input: str) -> float:
        """Calculate confidence for single intent"""
        if intent == Intent.GENERAL_CONVERSATION:
            return 0.5
        
        # Check if intent patterns match
        patterns = self.router.patterns.get(intent, [])
        for pattern in patterns:
            if pattern.search(user_input.lower()):
                return 0.95
        
        return 0.7
    
    def _calculate_segment_confidence(self, intent: Intent, segment: str) -> float:
        """Calculate confidence for segment analysis"""
        if intent == Intent.GENERAL_CONVERSATION:
            return 0.4  # Lower confidence for fallback
        
        # Check keyword density
        segment_lower = segment.lower()
        clean_seg = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)[,\s:]*', '', segment_lower, flags=re.IGNORECASE).strip()
        clean_no_polite = re.sub(r'^(?:can\s+you\s+|could\s+you\s+|please\s+)+', '', clean_seg, flags=re.IGNORECASE).strip()
        patterns = self.router.patterns.get(intent, [])
        
        match_count = 0
        for pattern in patterns:
            if pattern.search(segment_lower) or pattern.search(clean_seg) or pattern.search(clean_no_polite):
                match_count += 1
        
        if match_count > 0:
            return min(0.95, 0.7 + (match_count * 0.1))

        if intent == Intent.OPEN_APPLICATION:
            try:
                from extensions.system.smart_opener import smart_opener
                cl_app = re.sub(r'^(?:bring\s+up|open|launch|start|run|show)\s+(?:the\s+|a\s+)?', '', clean_no_polite, flags=re.IGNORECASE).strip()
                if smart_opener.resolve_detailed(cl_app):
                    return 0.95
            except Exception:
                pass
        
        return 0.5
    
    def _detect_dependencies(
        self,
        intent_matches: List[IntentMatch],
        user_input: str
    ) -> Dict[int, List[int]]:
        """
        Detect dependencies between intents.
        
        Returns dict: intent_index -> list of dependent intent indices
        """
        dependencies = {}
        input_lower = user_input.lower()
        
        for i, match_i in enumerate(intent_matches):
            for j, match_j in enumerate(intent_matches):
                if j >= i:
                    continue  # Later intent i can only depend on earlier intent j
                
                # Check if match_i depends on match_j
                key = (match_i.intent, match_j.intent)
                is_dep = False
                if key in self.DEPENDENCY_PATTERNS:
                    pattern = self.DEPENDENCY_PATTERNS[key]
                    if re.search(pattern, input_lower):
                        is_dep = True

                # Semantic entity dependency: downstream document export or file open depends on upstream creation
                if not is_dep:
                    text_i = match_i.matched_text.lower()
                    if match_i.intent == Intent.DOCUMENT_GENERATION and match_j.intent == Intent.DOCUMENT_GENERATION:
                        if any(w in text_i for w in ("copy", "pdf", "export", "save")):
                            is_dep = True
                    elif match_i.intent == Intent.OPEN_APPLICATION and match_j.intent in (Intent.DOCUMENT_GENERATION, Intent.FILE_OPERATIONS):
                        if any(w in text_i for w in ("saved file", "the file", "the document", "the pdf", "it", "that", "saved")):
                            is_dep = True

                if is_dep:
                    if i not in dependencies:
                        dependencies[i] = []
                    if j not in dependencies[i]:
                        dependencies[i].append(j)
        
        return dependencies
    
    def _order_by_priority(
        self,
        intent_matches: List[IntentMatch],
        dependencies: Dict[int, List[int]]
    ) -> List[Tuple[IntentMatch, int]]:
        """
        Order intents by priority and dependencies.
        
        Returns list of (IntentMatch, original_position) tuples
        """
        # Create ordering with original indices
        original_positions = {i: m for i, m in enumerate(intent_matches)}
        
        # Topological sort for dependencies
        ordered = []
        processed = set()
        visiting = set()
        
        def process_intent(idx):
            if idx in processed:
                return
            if idx in visiting:
                return  # Cycle break
            visiting.add(idx)
            
            # Process dependencies first
            for dep_idx in dependencies.get(idx, []):
                process_intent(dep_idx)
            
            visiting.remove(idx)
            ordered.append((original_positions[idx], idx))
            processed.add(idx)
        
        # Process all intents
        for i in range(len(intent_matches)):
            process_intent(i)
        
        return ordered
    
    def _empty_analysis(self, user_input: str) -> IntentAnalysis:
        """Return empty analysis for invalid input"""
        return IntentAnalysis(
            intents=[],
            has_multiple_intents=False,
            total_intents=0,
            primary_intent=Intent.GENERAL_CONVERSATION,
            confidence_score=0.0,
            original_input=user_input,
            timestamp=datetime.now().isoformat()
        )


# ============================================================================
# Global Analyzer Instance
# ============================================================================

multi_intent_analyzer = MultiIntentAnalyzer()


# ============================================================================
# Utility Functions
# ============================================================================

def analyze_input(user_input: str) -> IntentAnalysis:
    """
    Convenience function to analyze user input.
    
    Usage:
        analysis = analyze_input("play music and set reminder")
    """
    return multi_intent_analyzer.analyze(user_input)


def has_multiple_intents(user_input: str) -> bool:
    """Check if input contains multiple intents"""
    analysis = analyze_input(user_input)
    return analysis.has_multiple_intents


def get_execution_order(user_input: str) -> List[ExecutionIntent]:
    """
    Get ordered list of intents ready for execution.
    
    Returns list of ExecutionIntent objects in execution order.
    """
    analysis = analyze_input(user_input)
    
    execution_intents = []
    for intent_dict in analysis.intents:
        exec_intent = ExecutionIntent(
            sequence=intent_dict["sequence_position"],
            intent=intent_dict["intent"],
            parameters=intent_dict["parameters"],
            confidence=intent_dict["confidence"],
            dependencies=intent_dict.get("dependencies", []),
            requires_confirmation=intent_dict["confidence"] < 0.8
        )
        execution_intents.append(exec_intent)
    
    return execution_intents


if __name__ == "__main__":
    # Test multi-intent analyzer
    
    test_cases = [
        # Single intents (backward compatible)
        "play music",
        "what is the time",
        "send email to sathvik",
        
        # Multi-intents
        "play some Telugu songs and set a reminder to listen later",
        "find weather in Guntur and send the results to Sathvik",
        "open Chrome and search for weather",
        
        # Context-aware (single intent with context)
        "what about tomorrow",
        
        # Edge cases
        "I like music and email",
        "play music and stop music",
    ]
    
    print("[MULTI_INTENT_ANALYZER] Test Cases\n")
    
    for test_input in test_cases:
        print(f"Input: {test_input}")
        analysis = analyze_input(test_input)
        print(f"  Multiple Intents: {analysis.has_multiple_intents}")
        print(f"  Total Intents: {analysis.total_intents}")
        print(f"  Primary Intent: {analysis.primary_intent.name}")
        print(f"  Confidence: {analysis.confidence_score:.2f}")
        if analysis.has_multiple_intents:
            print(f"  Secondary Intents: {[i.name for i in analysis.secondary_intents]}")
        print()
