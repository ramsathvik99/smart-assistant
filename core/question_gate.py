"""
core/question_gate.py
=====================
Zero-classification Fast Gate for Conversational & Knowledge Questions.

Bypasses LLM classification (semantic_resolve) for requests that are clearly questions
or conversational chat (question words, knowledge inquiries, greetings, chit-chat)
with no imperative action verbs or device/app/file triggers.

Directly routes to answer generation in ONE model call instead of two.
"""

import re
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("QuestionGate")

# Action verbs and imperatives that indicate an executable device/system/file/app command
DISQUALIFYING_ACTIONS = re.compile(
    r'\b(?:'
    r'open|launch|start|run|close|kill|quit|exit|terminate|shut\s+down|restart|reboot|'
    r'set|change|adjust|increase|decrease|lower|raise|turn\s+up|turn\s+down|boost|drop|'
    r'mute|unmute|play|pause|resume|next\s+track|previous\s+track|'
    r'create|make|generate|build|delete|remove|rename|move|copy|save|edit|'
    r'remind|reminder|schedule|alarm|timer|reschedule|'
    r'send|compose|email|mail|'
    r'calibrate|benchmark|'
    r'turn\s+on|turn\s+off|switch\s+on|switch\s+off'
    r')\b',
    re.IGNORECASE
)

# Target devices, settings, apps, files that indicate action execution
DISQUALIFYING_TARGETS = re.compile(
    r'\b(?:'
    r'volume|brightness|wifi|bluetooth|hotspot|'
    r'notepad|calculator|chrome|firefox|spotify|vlc|'
    r'directory|folder|document|spreadsheet|presentation|pdf|docx|xlsx|pptx'
    r')\b',
    re.IGNORECASE
)

# Positive question / knowledge / chit-chat indicators
QUESTION_STARTERS = re.compile(
    r'^(?:(?:hey|ok|okay)\s+\w+[,\s:]*)?'
    r'(?:can\s+you\s+|could\s+you\s+|please\s+)?'
    r'(?:'
    r'what(?:\x27s|\s+is|\s+are|\s+was|\s+were)?\b|'
    r'who(?:\x27s|\s+is|\s+was|\s+were)?\b|'
    r'where(?:\x27s|\s+is|\s+are|\s+was|\s+were)?\b|'
    r'when(?:\x27s|\s+is|\s+was|\s+were)?\b|'
    r'why(?:\x27s|\s+is|\s+are|\s+was|\s+were)?\b|'
    r'how(?:\x27s|\s+is|\s+are|\s+was|\s+were|\s+do|\s+does|\s+can|\s+to|\s+has|\s+have)?\b|'
    r'which\b|whose\b|whom\b|'
    r'explain\b|describe\b|define\b|elaborate\b|tell\s+me\s+about\b|'
    r'and\s+what\s+about\b|what\s+about\b|how\s+about\b|'
    r'translate\b|how\s+do\s+you\s+say\b|meaning\s+of\b|'
    r'tell\s+me\s+a\s+joke\b|joke\b|'
    r'hello\b|hi\b|hey\b|good\s+(?:morning|afternoon|evening|night)\b|'
    r'who\s+are\s+you\b|what\s+can\s+you\s+do\b'
    r')',
    re.IGNORECASE
)

AUXILIARY_QUESTION = re.compile(
    r'^(?:is|are|am|was|were|do|does|did|can|could|will|would|should|may|might|have|has|had)\s+\w+',
    re.IGNORECASE
)


def is_plain_question(text: str, context: Optional[Dict[str, Any]] = None) -> bool:
    """
    Determine if text is clearly a general question, explanation, or chit-chat.
    
    Returns:
        True: Skip semantic_resolve classification and route directly to answer generation.
        False: "Not sure" or actionable command — retain standard router evaluation.
    """
    if not text or not isinstance(text, str):
        return False

    raw = text.strip()
    low = raw.lower().rstrip('?!. \t')

    if not low:
        return False

    # 1. Any disqualifying device or target?
    if DISQUALIFYING_TARGETS.search(low):
        return False

    # 2. Any disqualifying action verbs?
    # Exception: "explain how to..." or "explain what..." contains words, but is an explanation
    if DISQUALIFYING_ACTIONS.search(low):
        # Allow "explain", "meaning", "tell me about" even if followed by action nouns/verbs like "explain how to build"
        if not re.match(r'^(?:can\s+you\s+|could\s+you\s+|please\s+)?(?:explain|tell\s+me\s+about|describe)\b', low):
            return False

    # 2b. Specialized information queries (clock, user memory, documents, live facts, historical queries)
    # Must NOT be fast-tracked to plain conversational chat — allow canonical router evaluation
    if re.search(r'\b(?:time|clock|date|today\'?s?\s+date|day\s+is\s+it)\b', low):
        return False
    if re.search(r'\b(?:my\s+(?:name|university|college|degree|major|school|role|email|phone|placement|notes?|doc|document|report|artifact)|who\s+am\s+i|about\s+me)\b', low):
        return False
    if re.search(r'\b(?:president|prime\s+minister|ceo|stock\s+price|latest|current\s+price|weather)\b', low):
        return False
    if re.search(r'\b\d{4}\b', low):
        return False

    # 3. Positive match on question starter / interrogative?
    if QUESTION_STARTERS.match(low):
        logger.debug(f"[QUESTION GATE] Fast-tracked as plain question: '{raw[:50]}'")
        return True

    # 4. Ends with question mark and starts with auxiliary verb?
    if raw.endswith("?") and AUXILIARY_QUESTION.match(low):
        logger.debug(f"[QUESTION GATE] Fast-tracked as auxiliary question: '{raw[:50]}'")
        return True

    return False
