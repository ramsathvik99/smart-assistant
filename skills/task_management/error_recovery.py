"""
Error Recovery and Resilience Analyzer
Provides structured failure analysis, classifying errors into RETRY, SKIP, REPLAN, or ABORT with recovery suggestions.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ErrorDecision(Enum):
    RETRY = "retry"    # Transient error (network timeout, temporary lock)
    SKIP = "skip"      # Non-critical step that can be bypassed
    REPLAN = "replan"  # Wrong approach, need alternative method
    ABORT = "abort"    # Fatal error or safety/permission violation


# Transient error patterns that can succeed upon retry
TRANSIENT_PATTERNS = [
    "timeout", "timed out", "connection reset", "temporarily unavailable",
    "busy", "lock", "try again", "resource temporarily unavailable", "rate limit"
]

# Fatal error patterns that cannot succeed and should not be retried
FATAL_PATTERNS = [
    "permission denied", "forbidden", "unauthorized", "syntaxerror",
    "not permitted", "safety violation", "refused", "protected"
]


def analyze_task_error(
    step_or_goal: str,
    error: str,
    attempt: int = 1,
    max_attempts: int = 2
) -> dict[str, Any]:
    """
    Analyzes an execution error and produces a structured recovery decision.

    Returns:
        {
            "decision": ErrorDecision,
            "reason": str,
            "fix_suggestion": str,
            "max_retries": int,
            "user_message": str
        }
    """
    err_low = error.lower()

    # 1. Max attempts already reached
    if attempt >= max_attempts:
        return {
            "decision": ErrorDecision.REPLAN,
            "reason": f"Maximum retry attempts ({max_attempts}) reached.",
            "fix_suggestion": "Switch to an alternative tool or simplified parameters.",
            "max_retries": 0,
            "user_message": "Attempt limit reached. Trying an alternative approach.",
        }

    # 2. Fatal safety or permission error -> ABORT
    if any(p in err_low for p in FATAL_PATTERNS):
        return {
            "decision": ErrorDecision.ABORT,
            "reason": f"Permission or security constraint: {error[:100]}",
            "fix_suggestion": "Verify file permissions or user security privileges.",
            "max_retries": 0,
            "user_message": "Operation cannot proceed due to a security or permission restriction.",
        }

    # 3. Transient network or locking error -> RETRY
    if any(p in err_low for p in TRANSIENT_PATTERNS):
        return {
            "decision": ErrorDecision.RETRY,
            "reason": f"Transient error detected: {error[:100]}",
            "fix_suggestion": "Wait momentarily and retry the operation.",
            "max_retries": 1,
            "user_message": "Encountered a temporary delay. Retrying now.",
        }

    # 4. Missing resource or file -> REPLAN
    if any(p in err_low for p in ["not found", "no such file", "does not exist", "missing"]):
        return {
            "decision": ErrorDecision.REPLAN,
            "reason": f"Resource not found: {error[:100]}",
            "fix_suggestion": "Verify target path or locate the resource in alternative directories.",
            "max_retries": 0,
            "user_message": "The requested item was not found. Checking alternate locations.",
        }

    # 5. Default fallback to SKIP or REPLAN
    return {
        "decision": ErrorDecision.REPLAN,
        "reason": f"Execution failed: {error[:100]}",
        "fix_suggestion": "Review command parameters and retry with alternative inputs.",
        "max_retries": 0,
        "user_message": "Encountered an issue executing this step. Adjusting strategy.",
    }
