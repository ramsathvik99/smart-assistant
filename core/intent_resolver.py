"""
⚠️ DEPRECATED MODULE — DO NOT USE

This module was replaced by core/unified_command_router.py

Intent detection now happens exclusively through:
  core.unified_command_router.route_command()

See: core/ROUTING_AUTHORITY.md
"""

# LEGACY CODE BELOW - NOT USED
# ============================================================================

import re
import logging
from typing import List, Tuple, Dict, Any, Optional
from core.execution_dispatcher import IntentType, ExecutionRequest, MultiActionRequest
from core.entity_extractor import EntityExtractorManager

logger = logging.getLogger(__name__)


class IntentResolver:
    """
    Resolves user input to intents with confidence scores.
    """
    
    # Intent detection patterns with confidence scores (0.0-1.0)
    INTENT_PATTERNS = {
        IntentType.OPEN_APPLICATION: [
            (r'\b(?:open|launch|start|run)\s+(.+?)(?:\s+(?:app|application)|$)', 0.95),
            (r'\bopen\s+([A-Za-z0-9\s\-]+)', 0.90),
        ],
        IntentType.CLOSE_APPLICATION: [
            (r'\b(?:close|quit|exit|stop|terminate|kill)\s+(.+)', 0.95),
        ],
        IntentType.PLAY_MUSIC: [
            (r'\b(?:play|start|begin)\s+(?:some\s+)?(?:music|songs|track)(?:\s+by\s+)?(.+)?', 0.92),
            (r'\b(?:play|listen to)\s+(.+?)(?:\s+(?:song|track|album)|$)', 0.85),
        ],
        IntentType.STOP_MUSIC: [
            (r'\b(?:stop|end)\s+(?:the\s+)?(?:music|song|track|playback)', 0.95),
            (r'\bstop\s+(?:playing|playback)', 0.90),
        ],
        IntentType.PAUSE_MUSIC: [
            (r'\b(?:pause|pause the)\s+(?:music|song|track|playback)', 0.95),
        ],
        IntentType.RESUME_MUSIC: [
            (r'\b(?:resume|unpause|play|continue)\s+(?:the\s+)?(?:music|song|track|playback)', 0.90),
        ],
        IntentType.EMAIL_SEND: [
            (r'\b(?:send|compose|write|draft)\s+(?:an?\s+)?(?:email|message|mail)(?:\s+to\s+)?(.+)?', 0.92),
            (r'\bemail\s+(.+?)\s+(?:that|a|an)\s+', 0.85),
        ],
        IntentType.EMAIL_READ: [
            (r'\b(?:read|check|show|display)\s+(?:my\s+)?(?:latest\s+)?(?:email|emails|mail|message)(?:\s+from\s+)?(.+)?', 0.90),
            (r'\bshow\s+me\s+(?:my\s+)?(?:email|mail)', 0.85),
        ],
        IntentType.EMAIL_CHECK: [
            (r'\b(?:check|look\s+at|review)\s+(?:my\s+)?(?:inbox|email|mail|messages)', 0.92),
        ],
        IntentType.WEATHER: [
            (r'\b(?:what\s+is|what\'?s?)\s+(?:the\s+)?weather(?:\s+(?:in|for|at)\s+)?(.+)?', 0.95),
            (r'\b(?:tell|show)\s+(?:me\s+)?(?:the\s+)?weather(?:\s+(?:in|for)\s+)?(.+)?', 0.90),
            (r'\bweather\s+(?:in|for)\s+(.+)', 0.92),
        ],
        IntentType.TIME_QUERY: [
            (r'\b(?:what\s+is\s+the\s+time|what\s+time\s+is\s+it|tell\s+me\s+the\s+time|current\s+time)', 0.98),
        ],
        IntentType.DATE_QUERY: [
            (r'\b(?:what\s+is\s+the\s+date|what\s+date\s+is\s+it|tell\s+me\s+the\s+date|today\'?s?\s+date|what\s+day\s+is\s+it)', 0.98),
        ],
        IntentType.BROWSER: [
            (r'\b(?:open|go\s+to|navigate\s+to|browse)\s+(.+?)(?:\s+(?:website|page|site)|\.com|\.org|$)', 0.85),
        ],
        IntentType.BROWSER_SEARCH: [
            (r'\b(?:search|search\s+for|look\s+for|find|google)\s+(?:for\s+)?(.+?)(?:\s+(?:on|in|using|google|bing)|$)', 0.90),
            (r'\bsearch\s+(.+)', 0.85),
        ],
        IntentType.SYSTEM_CONTROL: [
            (r'\b(?:shutdown|power\s+off|turn\s+off|reboot|restart|sleep)\b', 0.95),
        ],
        IntentType.DEVICE_CONTROL: [
            (r'\b(?:mute|unmute|volume|brightness|lock)\b', 0.92),
        ],
        IntentType.FILE_OPERATIONS: [
            (r'\b(?:create|make|new|delete|remove|open|save)\s+(?:a\s+)?(?:file|folder|directory)\s+(.+)?', 0.90),
        ],
        IntentType.POWER_ACTION: [
            (r'\b(?:shutdown|power\s+off|turn\s+off|reboot|restart)\b', 0.98),
        ],
        IntentType.GENERAL_KNOWLEDGE: [
            (r'\b(?:what|who|where|when|why|how|explain|tell\s+me|describe)\b', 0.70),
        ],
        IntentType.CHAT: [
            # Fallback for conversational text
            (r'.+', 0.50),
        ],
    }
    
    @staticmethod
    def resolve_single_intent(text: str) -> Tuple[ExecutionRequest, float]:
        """
        Resolve single intent from text
        
        Returns:
            Tuple of (ExecutionRequest, overall_confidence)
        """
        if not text or not text.strip():
            return None, 0.0
        
        text_lower = text.lower().strip()
        best_intent = None
        best_confidence = 0.0
        best_match = None
        
        # Test all patterns in order of priority
        for intent_type, patterns in IntentResolver.INTENT_PATTERNS.items():
            for pattern, base_confidence in patterns:
                match = re.search(pattern, text_lower, re.IGNORECASE)
                if match and base_confidence > best_confidence:
                    best_intent = intent_type
                    best_confidence = base_confidence
                    best_match = match
        
        if not best_intent:
            # Default to chat
            best_intent = IntentType.CHAT
            best_confidence = 0.30
        
        # Extract entities
        entities = EntityExtractorManager.extract_all(text, best_intent.value)
        
        # Create execution request
        request = ExecutionRequest(
            intent=best_intent,
            confidence=best_confidence,
            input_text=text,
            entities=entities,
            metadata={
                "detected_at": "intent_resolver",
                "pattern_matched": best_match.group(0) if best_match else None
            }
        )
        
        logger.info(
            f"[INTENT RESOLVE] Text: '{text[:50]}...' | "
            f"Intent: {best_intent.value} | Confidence: {best_confidence:.2f}"
        )
        
        return request, best_confidence
    
    @staticmethod
    def detect_multi_intent(text: str) -> Optional[MultiActionRequest]:
        """
        Detect if command contains multiple intents
        
        Example:
            "Open Chrome and play music" -> MultiActionRequest with 2 intents
            "Tell me the weather and the time" -> MultiActionRequest with 2 intents
        """
        text_lower = text.lower().strip()
        
        # Multi-intent indicators
        connectors = [' and ', ' then ', ', then ', ', and ', '&']
        
        # Check for connectors
        has_connector = any(conn in text_lower for conn in connectors)
        if not has_connector:
            return None
        
        # Split by connectors
        parts = re.split(r'\s+(?:and|then)\s+|,\s+(?:and|then)\s+', text, flags=re.IGNORECASE)
        
        if len(parts) < 2:
            return None
        
        logger.info(f"[MULTI-INTENT DETECT] Found {len(parts)} parts in: {text}")
        
        # Resolve each part
        requests = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            request, confidence = IntentResolver.resolve_single_intent(part)
            if request and confidence > 0.5:  # Only include reasonably confident intents
                requests.append(request)
        
        # Return multi-action request if multiple intents detected
        if len(requests) >= 2:
            multi_request = MultiActionRequest(
                intents=requests,
                require_confirmation=True,
                execution_mode="sequential"
            )
            logger.info(f"[MULTI-INTENT] Created multi-action request with {len(requests)} intents")
            return multi_request
        
        return None


class ConfidenceAdjuster:
    """Adjusts confidence scores based on context and patterns"""
    
    # Confidence boost/penalty rules
    BOOST_RULES = {
        # Very explicit commands get confidence boost
        r'\b(?:please\s+)?(?:please\s+)?(?:definitely|absolutely|definitely)\b': 0.05,
        r'\b(?:make sure|be sure to|definitely)\b': 0.05,
    }
    
    PENALTY_RULES = {
        # Questions might be lower confidence
        r'\bdo\s+you\s+think|maybe|perhaps|possibly\b': -0.10,
        r'\bcan\s+you\s+(?:try|attempt)': -0.05,
    }
    
    @staticmethod
    def adjust_confidence(text: str, base_confidence: float) -> float:
        """Adjust confidence based on textual patterns"""
        adjusted = base_confidence
        
        # Apply boost rules
        for pattern, boost in ConfidenceAdjuster.BOOST_RULES.items():
            if re.search(pattern, text, re.IGNORECASE):
                adjusted = min(1.0, adjusted + boost)
        
        # Apply penalty rules
        for pattern, penalty in ConfidenceAdjuster.PENALTY_RULES.items():
            if re.search(pattern, text, re.IGNORECASE):
                adjusted = max(0.0, adjusted + penalty)
        
        return adjusted


def resolve_intent(text: str) -> Tuple[ExecutionRequest, float]:
    """
    Main intent resolution function
    
    Returns:
        Tuple of (ExecutionRequest, confidence_score)
    """
    # Check for multi-intent first
    multi_request = IntentResolver.detect_multi_intent(text)
    if multi_request:
        # Return first intent from multi-request as single for now
        # Caller should check for multi-intent type
        return multi_request.intents[0], 0.75  # Return with multi-intent metadata
    
    # Single intent resolution
    request, confidence = IntentResolver.resolve_single_intent(text)
    
    # Adjust confidence based on text patterns
    adjusted_confidence = ConfidenceAdjuster.adjust_confidence(text, confidence)
    
    if request:
        request.confidence = adjusted_confidence
    
    return request, adjusted_confidence


def detect_multi_intent(text: str) -> Optional[MultiActionRequest]:
    """Detect multiple intents in command"""
    return IntentResolver.detect_multi_intent(text)
