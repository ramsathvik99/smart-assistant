"""
assistant_os/planner/goal_decomposer.py
====================================
NOVA OS - Planner: Goal Decomposer

Architecture:
    This module is responsible for breaking a single high-level
    goal string into a flat list of atomic subtask instructions.

    Two strategies are used (same tiered pattern as IntentClassifier):

    Tier 1 — Rule-Based Decomposition:
        Reuses the existing GoalInterpreter from
        extensions/intelligence/goal_interpreter.py.
        The GoalInterpreter provides `suggested_plan` — a list of
        step strings already decomposed for known patterns.

    Tier 2 — LLM-Based Decomposition:
        For goals that GoalInterpreter cannot match (confidence < threshold
        or None returned), LLMEngine is called with a structured prompt
        that asks it to return a JSON list of step strings.

    Output of this module is ALWAYS a plain List[str] of instructions,
    one per subtask. Dependency mapping happens DOWNSTREAM in the
    DependencyInferencer (this module does not set dependencies).

    This module REUSES:
        - extensions/intelligence/goal_interpreter.py → GoalInterpreter
        - extensions/llm_engine.py → LLMEngine

SDD Reference: Section 12.2 (Planning Steps 1–2: Goal Parsing & Decomposition).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import List, Optional

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger("assistant_os.planner.goal_decomposer")


class GoalDecomposer:
    """
    Converts a high-level goal string into a flat list of
    atomic task instruction strings.

    Usage:
        decomposer = GoalDecomposer(use_llm=True, min_confidence=0.75)
        steps = decomposer.decompose("Research AI trends and email me a summary")
        # → ["Research AI trends online",
        #    "Compose an email summary of research findings",
        #    "Send the email to the user"]
    """

    def __init__(
        self,
        use_llm: bool = True,
        min_confidence: float = 0.75,
        max_tasks: int = 20,
    ):
        """
        Args:
            use_llm:        Enable LLM decomposition as fallback.
            min_confidence: GoalInterpreter confidence threshold below
                            which LLM decomposition is always triggered.
            max_tasks:      Hard cap on returned steps (safety guard).
        """
        self.use_llm        = use_llm
        self.min_confidence = min_confidence
        self.max_tasks      = max_tasks
        self._goal_interpreter = None  # Lazy-loaded
        self._llm              = None  # Lazy-loaded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decompose(self, goal: str, context: Optional[dict] = None) -> List[str]:
        """
        Decompose a goal into atomic task instructions.

        Args:
            goal:    High-level user goal string.
            context: Optional context dict (passed to GoalInterpreter).

        Returns:
            List of instruction strings (1 per subtask), never empty.
            Falls back to [goal] if all decomposition strategies fail.
        """
        # Tier 1: Rule-based via existing GoalInterpreter
        steps = self._rule_based_decompose(goal, context)

        if steps:
            logger.info(
                f"[GoalDecomposer] Rule-based decomposition: {len(steps)} step(s)."
            )
            return steps[:self.max_tasks]

        # Tier 2: LLM-based
        if self.use_llm:
            steps = self._llm_decompose(goal)
            if steps:
                logger.info(
                    f"[GoalDecomposer] LLM decomposition: {len(steps)} step(s)."
                )
                return steps[:self.max_tasks]

        # Fallback: treat the entire goal as a single task
        logger.warning(
            f"[GoalDecomposer] No decomposition strategy succeeded. "
            f"Treating goal as single task: {goal[:80]!r}"
        )
        return [goal]

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _rule_based_decompose(
        self, goal: str, context: Optional[dict]
    ) -> List[str]:
        """
        Use the existing GoalInterpreter to decompose known goal patterns.
        Returns an empty list if no pattern matches or confidence is too low.
        """
        interpreter = self._get_goal_interpreter()
        if interpreter is None:
            return []

        try:
            goal_obj = interpreter.interpret_goal(goal, context)
            if goal_obj is None:
                return []
            if goal_obj.confidence < self.min_confidence:
                logger.debug(
                    f"[GoalDecomposer] GoalInterpreter confidence "
                    f"{goal_obj.confidence:.2f} < {self.min_confidence} — "
                    f"escalating to LLM."
                )
                return []
            # GoalInterpreter returns step strings like "open_vscode".
            # Convert underscored action names to readable instructions.
            return [self._humanize_step(s) for s in goal_obj.suggested_plan]
        except Exception as exc:
            logger.warning(f"[GoalDecomposer] GoalInterpreter error: {exc}")
            return []

    def _llm_decompose(self, goal: str) -> List[str]:
        """
        Ask LLMEngine to decompose the goal into a JSON list of steps.
        Returns an empty list on failure.
        """
        llm = self._get_llm()
        if llm is None:
            return []

        prompt = (
            "You are an AI task planner. Given the following high-level goal, "
            "break it down into a numbered list of concise, atomic task steps. "
            "Each step must be a single action. "
            "Return ONLY a valid JSON array of strings. "
            "Example: [\"Search the web for AI trends\", \"Summarize the results\", \"Send an email\"]\n\n"
            f"Goal: \"{goal}\"\n\n"
            "JSON array:"
        )

        try:
            response = llm.get_completion(prompt)
            if not response:
                return []

            # Extract JSON array from the response (LLM may add extra text)
            match = re.search(r"\[.*?\]", response, re.DOTALL)
            if not match:
                logger.warning(
                    f"[GoalDecomposer] LLM response contained no JSON array: "
                    f"{response[:120]!r}"
                )
                return []

            steps = json.loads(match.group())
            if not isinstance(steps, list):
                return []

            # Sanitize: keep only non-empty strings
            return [str(s).strip() for s in steps if str(s).strip()]

        except (json.JSONDecodeError, Exception) as exc:
            logger.warning(f"[GoalDecomposer] LLM decomposition failed: {exc}")
            return []

    @staticmethod
    def _humanize_step(step: str) -> str:
        """
        Convert underscore-separated GoalInterpreter step names to
        human-readable instructions.

        Example:
            "open_vscode" → "Open VS Code"
            "play_focus_music" → "Play focus music"
        """
        return step.replace("_", " ").capitalize()

    def _get_goal_interpreter(self):
        """Lazy-load the existing GoalInterpreter. Returns None if unavailable."""
        if self._goal_interpreter is not None:
            return self._goal_interpreter
        try:
            from extensions.intelligence.goal_interpreter import GoalInterpreter  # noqa
            self._goal_interpreter = GoalInterpreter()
            logger.debug("[GoalDecomposer] GoalInterpreter loaded successfully.")
        except Exception as exc:
            logger.warning(
                f"[GoalDecomposer] GoalInterpreter unavailable (rule-based disabled): {exc}"
            )
            self._goal_interpreter = None
        return self._goal_interpreter

    def _get_llm(self):
        """Lazy-load the existing LLMEngine. Returns None if unavailable."""
        if self._llm is not None:
            return self._llm
        try:
            from extensions.llm_engine import LLMEngine  # noqa
            self._llm = LLMEngine()
            logger.debug("[GoalDecomposer] LLMEngine loaded successfully.")
        except Exception as exc:
            logger.warning(
                f"[GoalDecomposer] LLMEngine unavailable (LLM decomposition disabled): {exc}"
            )
            self._llm = None
        return self._llm
