"""
assistant_os/planner/intent_classifier.py
=======================================
NOVA OS - Planner: Agent-Type Intent Classifier

Architecture:
    This module maps a natural language task instruction to the
    most appropriate AgentType.

    It uses a two-tier strategy:

    Tier 1 — Keyword Heuristics (always available, zero latency):
        Fast dictionary-based matching. Sufficient for the vast
        majority of common requests.

    Tier 2 — LLM Classification (optional, network-dependent):
        Falls back to LLMEngine.get_completion() when Tier 1
        returns AgentType.UNKNOWN. Asks the LLM to choose from
        the registered AgentType list.

    This module is called by Planner._classify_agent() for each
    decomposed subtask instruction.

    The module REUSES the existing LLMEngine from
    extensions/llm_engine.py. It does NOT create a new LLM wrapper.

SDD Reference: Section 26 (Agent Design — all agent intent patterns).
"""

from __future__ import annotations

import logging
import sys
import os
from typing import Tuple

# Ensure the project root is on the path so existing extensions are importable.
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from assistant_os.planner.models import AgentType, RiskLevel

logger = logging.getLogger("assistant_os.planner.intent_classifier")


# ---------------------------------------------------------------------------
# Keyword → AgentType Heuristic Tables
# ---------------------------------------------------------------------------

# Maps AgentType → list of trigger keywords (lowercase, substring match)
_AGENT_KEYWORDS: dict[AgentType, list[str]] = {
    AgentType.CONVERSATION: [
        "chat", "talk", "conversation", "tell me", "what is", "who is",
        "explain", "describe", "how does", "why does", "joke", "story",
        "advice", "opinion", "recommend",
    ],
    AgentType.CODING: [
        "code", "program", "script", "function", "class", "debug",
        "fix bug", "write a function", "implement", "algorithm",
        "python", "javascript", "java", "c++", "sql", "compile",
        "test", "unit test", "refactor", "lint",
    ],
    AgentType.RESEARCH: [
        "research", "find information", "look up", "summarize", "article",
        "paper", "study", "report", "analyse", "analyze", "investigate",
        "search for", "gather", "fetch", "news", "latest",
    ],
    AgentType.BROWSER: [
        "open website", "navigate to", "go to", "browse", "click",
        "fill form", "login", "submit", "download from", "scrape",
        "open url", "http",
    ],
    AgentType.RESUME: [
        "resume", "cv", "curriculum vitae", "cover letter",
        "job application", "linkedin", "portfolio", "tailor",
    ],
    AgentType.STUDY: [
        "study", "learn", "quiz me", "flashcard", "tutorial",
        "exam", "syllabus", "explain concept", "teach me",
        "practice", "notes", "lecture",
    ],
    AgentType.AUTOMATION: [
        "open app", "launch", "close", "move file", "copy file",
        "delete file", "create folder", "rename", "restart",
        "shutdown", "schedule", "run script", "terminal",
        "system", "os", "windows", "file manager",
    ],
    AgentType.MEMORY: [
        "remember", "recall", "forget", "save this", "store",
        "what did i say", "my preference", "last time",
        "history", "previous conversation",
    ],
}

# Keywords that suggest irreversibility (used for risk scoring)
_HIGH_RISK_KEYWORDS: list[str] = [
    "delete", "remove", "shutdown", "format", "wipe", "send email",
    "submit form", "post", "publish", "pay", "transfer",
]
_CRITICAL_RISK_KEYWORDS: list[str] = [
    "rm -rf", "format drive", "delete all", "factory reset",
]


# ---------------------------------------------------------------------------
# IntentClassifier
# ---------------------------------------------------------------------------

class IntentClassifier:
    """
    Maps a task instruction string to an AgentType and RiskLevel.

    Usage:
        classifier = IntentClassifier(use_llm=True)
        agent_type, risk = classifier.classify("Write a Python sort function")
        # → (AgentType.CODING, RiskLevel.LOW)
    """

    def __init__(self, use_llm: bool = True):
        """
        Args:
            use_llm: When True, falls back to LLMEngine for UNKNOWN intents.
                     Set False for offline/testing environments.
        """
        self.use_llm = use_llm
        self._llm = None  # Lazy-loaded only if needed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, instruction: str) -> Tuple[AgentType, RiskLevel]:
        """
        Classify a task instruction into an AgentType and RiskLevel.

        Args:
            instruction: The natural language instruction for a subtask.

        Returns:
            Tuple of (AgentType, RiskLevel).
        """
        instruction_lower = instruction.lower()

        # Tier 1: Keyword heuristics
        agent_type = self._keyword_match(instruction_lower)

        # Tier 2: LLM fallback
        if agent_type == AgentType.UNKNOWN and self.use_llm:
            agent_type = self._llm_classify(instruction)

        risk = self._assess_risk(instruction_lower, agent_type)

        logger.debug(
            f"[IntentClassifier] '{instruction[:60]}' → "
            f"agent={agent_type.value}, risk={risk.value}"
        )
        return agent_type, risk

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _keyword_match(self, instruction_lower: str) -> AgentType:
        """Tier 1: Find the AgentType with the most keyword hits."""
        scores: dict[AgentType, int] = {}

        for agent_type, keywords in _AGENT_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in instruction_lower)
            if hits > 0:
                scores[agent_type] = hits

        if not scores:
            return AgentType.UNKNOWN

        # Return agent with the highest keyword match count
        return max(scores, key=lambda k: scores[k])

    def _llm_classify(self, instruction: str) -> AgentType:
        """
        Tier 2: Ask the existing LLMEngine to classify the instruction.
        Returns AgentType.UNKNOWN on failure.
        """
        try:
            llm = self._get_llm()
            if llm is None:
                return AgentType.UNKNOWN

            agent_names = ", ".join(a.value for a in AgentType if a != AgentType.UNKNOWN)
            prompt = (
                f"You are an AI routing system. Given the following task instruction, "
                f"select the SINGLE best agent type from this list: {agent_names}.\n\n"
                f"Task: \"{instruction}\"\n\n"
                f"Respond with ONLY the agent type name, nothing else."
            )
            response = llm.get_completion(prompt)
            if response:
                candidate = response.strip().upper()
                try:
                    return AgentType(candidate)
                except ValueError:
                    logger.warning(
                        f"[IntentClassifier] LLM returned unknown agent type: {candidate!r}"
                    )
        except Exception as exc:
            logger.warning(f"[IntentClassifier] LLM classification failed: {exc}")

        return AgentType.UNKNOWN

    def _assess_risk(self, instruction_lower: str, agent_type: AgentType) -> RiskLevel:
        """
        Assign a RiskLevel based on keyword patterns and agent type.

        Rules (in priority order):
          - Any critical keyword → CRITICAL
          - Any high-risk keyword → HIGH
          - AUTOMATION / BROWSER agents → at least MEDIUM
          - Everything else → LOW
        """
        for kw in _CRITICAL_RISK_KEYWORDS:
            if kw in instruction_lower:
                return RiskLevel.CRITICAL

        for kw in _HIGH_RISK_KEYWORDS:
            if kw in instruction_lower:
                return RiskLevel.HIGH

        if agent_type in (AgentType.AUTOMATION, AgentType.BROWSER):
            return RiskLevel.MEDIUM

        return RiskLevel.LOW

    def _get_llm(self):
        """Lazy-load the existing LLMEngine. Returns None if unavailable."""
        if self._llm is not None:
            return self._llm
        try:
            # Reuse the existing engine — no duplication.
            from extensions.llm_engine import LLMEngine  # noqa: PLC0415
            self._llm = LLMEngine()
            logger.debug("[IntentClassifier] LLMEngine loaded successfully.")
        except Exception as exc:
            logger.warning(
                f"[IntentClassifier] Could not load LLMEngine (LLM fallback disabled): {exc}"
            )
            self._llm = None
        return self._llm
