"""
Addressing and assistant name handling module.
Strips leading/trailing assistant names and greeting tokens, handles fuzzy matching,
and prevents mis-hearings (like "end of Friday" / "go Friday") from being sent to the command router.
"""

import re
from typing import Tuple, Optional

GREETINGS = {"hey", "hi", "hello", "ok", "okay", "yo"}

COMMON_MISHEARINGS = {
    "end of", "go", "and", "so", "oh", "to", "for"
}

def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute the Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]

def _is_name_match(token: str, target_name: str) -> bool:
    """Fuzzy match a single word token against target assistant name."""
    t = token.lower().strip(",.!?\":;'")
    n = target_name.lower().strip()
    if not t or not n:
        return False
    if t == n:
        return True
    # Strip trailing 's' if assistant name was made possessive (e.g. "Friday's")
    if t.endswith("'s") and t[:-2] == n:
        return True
    if t.endswith("s") and t[:-1] == n:
        return True
    # Edit distance threshold: 1 for names <= 6 chars, 2 for longer
    max_dist = 1 if len(n) <= 6 else 2
    if abs(len(t) - len(n)) <= max_dist:
        return levenshtein_distance(t, n) <= max_dist
    return False

def strip_address(text: str, assistant_name: Optional[str] = None) -> Tuple[str, bool]:
    """
    Remove leading or trailing assistant name and greetings.
    
    Args:
        text: Input utterance string.
        assistant_name: Configured name of assistant (default: 'Friday').
        
    Returns:
        (clean_text, addressed)
        - clean_text: command text with addressing stripped.
        - addressed: True if utterance was addressed to the assistant.
    """
    if not text or not text.strip():
        return "", False

    raw = text.strip()

    name = assistant_name
    if not name:
        try:
            from instance.config import settings
            name = getattr(settings, "CURRENT_ASSISTANT_NAME", None)
            if not name:
                from instance.config import get_assistant_name
                name = get_assistant_name()
        except Exception:
            name = None
    if not name:
        name = "Friday"

    name_lower = name.strip().lower()

    # Normalize tokens while keeping punctuation on words
    tokens = raw.split()
    if not tokens:
        return "", False

    addressed = False

    # Check for known leading mis-hearings when short (e.g. "end of Friday", "go Friday")
    low_text = raw.lower().rstrip(".!? ")
    for prefix in ("end of ", "go ", "and ", "so ", "oh "):
        if low_text.startswith(prefix):
            remainder = low_text[len(prefix):].strip()
            rem_tokens = remainder.split()
            if len(rem_tokens) >= 1 and _is_name_match(rem_tokens[0], name_lower):
                addressed = True
                after_name_tokens = tokens[len(prefix.split()) + 1:]
                clean_text = " ".join(after_name_tokens).strip()
                clean_text = re.sub(r"^[,.!?\s]+", "", clean_text).strip()
                return clean_text, True

    # 1. Check leading greeting + name (e.g. "Hey Friday", "Hi Friday what is the time", "Friday open chrome")
    start_idx = 0
    while start_idx < len(tokens):
        w = tokens[start_idx].lower().strip(",.!?\":;'")
        if w in GREETINGS:
            addressed = True
            start_idx += 1
            continue
        elif _is_name_match(w, name_lower):
            addressed = True
            start_idx += 1
            break
        else:
            break

    if addressed:
        remaining_tokens = tokens[start_idx:]
        clean_text = " ".join(remaining_tokens).strip()
        clean_text = re.sub(r"^[,.!?\s]+", "", clean_text).strip()
        return clean_text, True

    # 2. Check trailing name (e.g. "what is the time Friday", "open chrome, Friday.")
    end_idx = len(tokens) - 1
    w_last = tokens[end_idx].lower().strip(",.!?\":;'")
    if _is_name_match(w_last, name_lower):
        addressed = True
        end_idx -= 1
        # Also strip trailing greeting if preceded by one (e.g. "what is the time hey Friday")
        if end_idx >= 0 and tokens[end_idx].lower().strip(",.!?\":;'") in GREETINGS:
            end_idx -= 1
        remaining_tokens = tokens[:end_idx + 1]
        clean_text = " ".join(remaining_tokens).strip()
        clean_text = re.sub(r"[,.!?\s]+$", "", clean_text).strip()
        return clean_text, True

    return raw, False
