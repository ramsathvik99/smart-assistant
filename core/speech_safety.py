"""
Speech Safety & Sanitization Module.
Ensures TTS engines never speak raw exception text, stack traces, URLs, file paths,
JSON objects, markdown symbols, or SSL error strings aloud.
Replaces technical failures with friendly, conversational one-liners while logging
the complete technical diagnostics to the logger/console.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger("SpeechSafety")

# Known error patterns mapped to friendly user-facing spoken explanations
KNOWN_ERROR_PATTERNS = [
    (
        r"(?:urlopen error|certificate verify failed|certificate_verify_failed|ssl:).*(?:weather)",
        "I couldn't reach the weather service right now."
    ),
    (
        r"(?:weather).*(?:urlopen error|certificate verify failed|certificate_verify_failed|ssl:)",
        "I couldn't reach the weather service right now."
    ),
    (
        r"less than urlopen error \[ssl:.*?certificate has expired greater than",
        "I couldn't reach the online service right now."
    ),
    (
        r"\[ssl:\s*certificate_?verify_?failed\].*?certificate has expired",
        "I couldn't reach the online service right now."
    ),
    (
        r"insufficient\s+credit\s+balance|insufficient_quota|quota\s+exceeded",
        "The AI service is currently unavailable due to account limits."
    ),
    (
        r"invalid\s+api\s*key|api\s*key\s+not\s+found|unauthorized|authentication\s+failed",
        "The AI service is not properly configured with an API key."
    ),
    (
        r"traceback\s+\(most\s+recent\s+call\s+last\)",
        "I ran into a problem while processing that request."
    ),
]


def make_speakable(text: Optional[str]) -> str:
    """
    Sanitize text before speech synthesis so the assistant speaks truthfully,
    cleanly, and never reads raw stack traces or internal errors aloud.
    
    Args:
        text: Raw text to be spoken.
        
    Returns:
        Clean, speakable string suitable for TTS.
    """
    if not text or not str(text).strip():
        return ""

    s = str(text).strip()
    original = s
    low_s = s.lower()

    # 1. Check known technical failures and map to friendly spoken messages
    for pattern, friendly_msg in KNOWN_ERROR_PATTERNS:
        if re.search(pattern, low_s, flags=re.IGNORECASE):
            logger.warning(f"[SPEECH SAFETY] Replaced technical error with friendly speech: {original!r}")
            return friendly_msg

    # Generic SSL / urlopen error
    if "urlopen error" in low_s or "certificate verify failed" in low_s or "[ssl:" in low_s:
        logger.warning(f"[SPEECH SAFETY] Suppressed raw SSL/network error from speech: {original!r}")
        if "weather" in low_s:
            return "I couldn't reach the weather service right now."
        return "I'm having trouble connecting to the network service right now."

    # Generic AI provider credit / quota error
    if "insufficient credit" in low_s or "quota" in low_s:
        logger.warning(f"[SPEECH SAFETY] Suppressed AI quota error from speech: {original!r}")
        return "The AI service is currently unavailable due to account limits."

    # Tracebacks
    if "traceback (most recent call last)" in low_s:
        logger.warning(f"[SPEECH SAFETY] Suppressed traceback from speech: {original!r}")
        return "I ran into an unexpected error while processing that."

    # 2. Strip escaped HTML/XML placeholder words "less than" / "greater than"
    s = re.sub(r'\bless than\b\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s*\bgreater than\b', '', s, flags=re.IGNORECASE)
    s = re.sub(r'<[^>]+>', '', s)

    # 3. Strip Markdown links [text](url) -> text, and raw URLs
    s = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', s)
    s = re.sub(r'https?://\S+', '', s)
    s = re.sub(r'\bwww\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9._/-]+', '', s)

    # 4. Strip Windows & POSIX file paths (including paths with spaces ending in filename.ext)
    s = re.sub(r'\b[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]+\.[a-zA-Z0-9]{1,6}\b', '', s)
    s = re.sub(r'\b[A-Za-z]:\\[^\s,;]+', '', s)
    s = re.sub(r'(?:^|\s)/(?:[a-zA-Z0-9_\.-]+/)+[a-zA-Z0-9_\.-]+', '', s)

    # 5. Strip raw code fences and backticks
    s = re.sub(r'```[\s\S]*?```', '', s)
    s = re.sub(r'`([^`]+)`', r'\1', s)

    # 6. Strip Markdown symbols (headers, bold, italics, bullets, table pipes, blockquotes)
    s = re.sub(r'^\s*#{1,6}\s*', '', s, flags=re.MULTILINE)
    s = re.sub(r'^\s*[\*\-•]\s+', '', s, flags=re.MULTILINE)
    s = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', s)
    s = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', s)
    s = s.replace('*', '')
    s = re.sub(r'^\s*>\s*', '', s, flags=re.MULTILINE)
    s = re.sub(r'\|', ' ', s)

    # 7. Strip JSON-like objects { ... }
    s = re.sub(r'\{[^{}]*\}', '', s)

    # 8. Strip technical error labels (e.g. "ValueError: ...", "Exception: ...")
    s = re.sub(r'\b[A-Za-z0-9_]+(?:Error|Exception):\s*', '', s)

    # 9. Clean up multiple spaces, empty parens/brackets, and dangling punctuation
    s = re.sub(r'\(\s*\)', '', s)
    s = re.sub(r'\[\s*\]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'^[,;:\.\s]+', '', s).strip()

    if original != s:
        logger.debug(f"[SPEECH SAFETY] Sanitized speech: {original!r} -> {s!r}")

    # Fallback if sanitization completely emptied an error string
    if not s:
        return "I encountered an issue executing that request."

    return s
