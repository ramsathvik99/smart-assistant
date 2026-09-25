"""
Clipboard Technical Content Analyzer
Classifies clipboard text on-demand into actionable technical categories:
- Error tracebacks / exceptions
- JSON data structures
- SQL database queries
- Source code snippets
Operates on-demand without invasive background sniffing to preserve user privacy.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

import pyperclip


def classify_clipboard_content(text: str) -> Optional[str]:
    """Classifies content into error_traceback, json_data, sql_query, or code_snippet."""
    clean = text.strip()
    if len(clean) < 15:
        return None

    # 1. Error traceback
    if "Traceback (most recent call last):" in clean or ("Exception:" in clean or "Error:" in clean) and "\n" in clean:
        return "error_traceback"

    # 2. JSON data
    if (clean.startswith("{") and clean.endswith("}")) or (clean.startswith("[") and clean.endswith("]")):
        try:
            json.loads(clean)
            return "json_data"
        except Exception:
            pass

    # 3. SQL query
    if re.search(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\s+", clean, re.IGNORECASE):
        return "sql_query"

    # 4. Source code snippet
    code_keywords = ["def ", "class ", "function ", "import ", "from ", "const ", "let ", "var ", "public class", "return "]
    if any(k in clean for k in code_keywords) and "\n" in clean:
        return "code_snippet"

    return "plain_text"


def analyze_clipboard() -> Dict[str, Any]:
    """Inspects and classifies current OS clipboard content."""
    try:
        content = (pyperclip.paste() or "").strip()
    except Exception as e:
        return {
            "success": False,
            "category": "error",
            "message": f"Could not read clipboard: {e}",
            "char_count": 0,
        }

    if not content:
        return {
            "success": True,
            "category": "empty",
            "message": "Your clipboard is currently empty.",
            "char_count": 0,
            "preview": "",
        }

    category = classify_clipboard_content(content) or "plain_text"
    preview = content[:150].replace("\n", " ") + ("..." if len(content) > 150 else "")

    category_labels = {
        "error_traceback": "Error Traceback / Exception",
        "json_data": "JSON Data Structure",
        "sql_query": "SQL Database Query",
        "code_snippet": "Source Code Snippet",
        "plain_text": "Plain Text",
    }
    label = category_labels.get(category, "Text")

    msg = f"Clipboard contains {label} ({len(content)} characters): '{preview}'."
    return {
        "success": True,
        "category": category,
        "category_label": label,
        "char_count": len(content),
        "preview": preview,
        "message": msg,
    }
