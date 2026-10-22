"""
core/json_repair.py
===================
Resilient LLM JSON Parser and Syntax Repair Utility.

Tolerates and repairs common model generation anomalies:
1. Markdown code fences (```json ... ``` or ``` ... ```)
2. Trailing commas in objects ({ "a": 1, }) and arrays ([ 1, 2, ])
3. Unquoted dictionary keys ({ a: 1 })
4. Single-quoted strings ('key': 'value')
5. Python-style literals (True, False, None)
6. Truncated closing braces and brackets ({ "a": [1, 2)
7. Extraneous leading/trailing conversational text
"""

import json
import re
from typing import Any, Dict, Optional, Union


def _extract_candidate_json(text: str) -> str:
    """Extract candidate JSON substring from markdown fences or text."""
    if not text or not isinstance(text, str):
        return ""

    s = text.strip()

    # 1. Check for markdown code fences
    if "```" in s:
        parts = s.split("```")
        for p in parts:
            p_strip = p.strip()
            if p_strip.startswith("json"):
                p_strip = p_strip[4:].strip()
            if (p_strip.startswith("{") and "}" in p_strip) or (p_strip.startswith("[") and "]" in p_strip):
                s = p_strip
                break

    # 2. Extract from outermost { ... }
    first_brace = s.find("{")
    last_brace = s.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return s[first_brace : last_brace + 1]

    # 3. If no closing brace, check if truncated object
    if first_brace != -1:
        return s[first_brace:]

    # 4. Check for array [ ... ]
    first_bracket = s.find("[")
    last_bracket = s.rfind("]")
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        return s[first_bracket : last_bracket + 1]
    if first_bracket != -1:
        return s[first_bracket:]

    return s


def repair_json_string(raw: str) -> str:
    """Apply progressive syntax transformations to fix malformed JSON."""
    s = raw.strip()

    # Normalize Python literals to valid JSON
    s = re.sub(r'\bTrue\b', 'true', s)
    s = re.sub(r'\bFalse\b', 'false', s)
    s = re.sub(r'\bNone\b', 'null', s)

    # Replace single quotes with double quotes when acting as string delimiters
    # E.g. {'key': 'value'} -> {"key": "value"}
    # Be careful not to replace contractions inside strings like "don't"
    def _quote_replace(match):
        content = match.group(1)
        # Escape any unescaped double quotes inside
        content = content.replace('"', '\\"')
        return f'"{content}"'

    s = re.sub(r"(?<=[:{\[,])\s*'([^']*)'(?=\s*[:},\]])", _quote_replace, s)

    # Fix unquoted object keys: { key: "value", other_key: 123 }
    s = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', s)

    # Close unclosed string literals if odd number of unescaped double quotes
    unescaped_quotes = len(re.findall(r'(?<!\\)"', s))
    if unescaped_quotes % 2 != 0:
        s += '"'

    # If truncated after a colon: e.g. "key": -> "key": null
    s = re.sub(r':\s*$', ': null', s)

    # Remove trailing commas before closing braces or brackets:
    # { "a": 1, } -> { "a": 1 }
    # [ 1, 2, ] -> [ 1, 2 ]
    s = re.sub(r',\s*([\}\]])', r'\1', s)
    s = re.sub(r',\s*$', '', s)

    # Balance unclosed brackets and braces
    open_curly = s.count("{")
    close_curly = s.count("}")
    open_square = s.count("[")
    close_square = s.count("]")

    if open_square > close_square:
        s += "]" * (open_square - close_square)
    if open_curly > close_curly:
        s += "}" * (open_curly - close_curly)

    # Remove any trailing commas that might have been exposed before newly added braces
    s = re.sub(r',\s*([\}\]])', r'\1', s)

    return s


def parse_llm_json(text: Any) -> Optional[Union[Dict[str, Any], list]]:
    """
    Parse JSON from LLM output with aggressive repair.
    Returns parsed dict/list, or None only if truly unusable.
    Never raises an exception.
    """
    if not text:
        return None

    if isinstance(text, (dict, list)):
        return text

    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return None

    # Step 1: Direct parse
    candidate = _extract_candidate_json(text)
    try:
        return json.loads(candidate)
    except Exception:
        pass

    # Step 2: Try original text direct parse
    try:
        return json.loads(text.strip())
    except Exception:
        pass

    # Step 3: Progressive repair on candidate
    try:
        repaired = repair_json_string(candidate)
        return json.loads(repaired)
    except Exception:
        pass

    # Step 4: Progressive repair on entire text
    try:
        repaired = repair_json_string(text)
        candidate2 = _extract_candidate_json(repaired)
        return json.loads(candidate2)
    except Exception:
        pass

    # Step 5: Fallback regex extractor for key-value dictionary if JSON syntax is completely mangled
    try:
        kv_pairs = re.findall(r'["\']?([a-zA-Z0-9_]+)["\']?\s*:\s*(?:"([^"]*)"|\'([^\']*)\'|([0-9\.]+)|(true|false|null))', candidate)
        if kv_pairs and len(kv_pairs) >= 2:
            res: Dict[str, Any] = {}
            for k, s1, s2, num, lit in kv_pairs:
                if s1:
                    res[k] = s1
                elif s2:
                    res[k] = s2
                elif num:
                    res[k] = float(num) if '.' in num else int(num)
                elif lit:
                    res[k] = True if lit == 'true' else (False if lit == 'false' else None)
            if res:
                return res
    except Exception:
        pass

    return None
