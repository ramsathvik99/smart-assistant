"""
extensions/rag_system/router.py — RAG Intent Classifier

This module bridges the RAGSystem to the single source-of-truth:
core.unified_command_router.UnifiedCommandRouter.

It maps the raw UnifiedCommandRouter intent names to the coarser
RAG-level core_intent / sub_intent vocabulary that RAGSystem.process()
expects, so that RAGSystem acts as a downstream handler for intents
that require retrieval-augmented generation (RAG_SEARCH, GENERAL_CONVERSATION,
CODE_GENERATION, MEMORY_QUERY, etc.)

The RAGRouter does NOT duplicate intent detection — it only translates.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ── Lazy LLM provider ────────────────────────────────────────────────────────
class _LLMProxy:
    """Lazily loads the LLM client to avoid circular imports at startup."""

    def __init__(self):
        self._client = None

    def _ensure(self):
        if self._client is None:
            try:
                from extensions.llm_engine import LLMEngine
                self._client = LLMEngine()
            except Exception as e:
                logger.warning(f"[RAGRouter] LLM engine unavailable: {e}")
                self._client = _NullLLM()

    def get_completion(self, query: str, context: str = "") -> str:
        self._ensure()
        return self._client.get_completion(query, context)


class _NullLLM:
    def get_completion(self, query: str, context: str = "") -> str:
        return "I'm unable to generate a response right now."


# ── Null command registry (commands handled upstream by unified router) ───────
class _NullCommandRegistry:
    def execute_command(self, cmd_obj, query: str) -> bool:
        logger.warning("[RAGRouter] Command execution requested on NullCommandRegistry — should be handled by UnifiedCommandRouter.")
        return False


# ── RAGRouter ────────────────────────────────────────────────────────────────
class RAGRouter:
    """
    Translates unified router intent names into RAGSystem-level routing data.
    Single responsibility: intent name translation only. No detection logic.
    """

    # Maps UnifiedCommandRouter intent names → RAG core_intent + sub_intent
    _INTENT_MAP: Dict[str, Dict[str, str]] = {
        "OPEN_APPLICATION":     {"core_intent": "command",            "sub_intent": "open_application"},
        "POWER_ACTION":        {"core_intent": "command",            "sub_intent": "power_action"},
        "DEVICE_CONTROL":       {"core_intent": "command",            "sub_intent": "device_control"},
        "MUSIC":                {"core_intent": "command",            "sub_intent": "music"},
        "TIME_QUERY":           {"core_intent": "current_time_query", "sub_intent": "time"},
        "DATE_QUERY":           {"core_intent": "current_time_query", "sub_intent": "date"},
        "RAG_SEARCH":           {"core_intent": "dynamic_fact_query", "sub_intent": "general_knowledge"},
        "GENERAL_CONVERSATION": {"core_intent": "chat",               "sub_intent": "general_knowledge"},
        "MEMORY_QUERY":         {"core_intent": "db_search",          "sub_intent": "memory_retrieval"},
        "CODE_GENERATION":      {"core_intent": "chat",               "sub_intent": "code_generation"},
        "EMAIL":                {"core_intent": "chat",               "sub_intent": "general_knowledge"},
        "NOTES":                {"core_intent": "chat",               "sub_intent": "general_knowledge"},
        "REMINDERS":            {"core_intent": "chat",               "sub_intent": "general_knowledge"},
        "TRANSLATION":          {"core_intent": "chat",               "sub_intent": "general_knowledge"},
        "CALCULATOR":           {"core_intent": "chat",               "sub_intent": "general_knowledge"},
    }

    def __init__(self):
        self.llm = _LLMProxy()
        self.command_registry = _NullCommandRegistry()

    def route(self, query: str) -> Dict[str, Any]:
        """
        Translate query intent into RAG routing data.
        Uses UnifiedCommandRouter for intent detection (single source of truth).
        CRITICAL: Always preserves the original unified_intent to prevent incorrect routing fallbacks.
        """
        try:
            from core.unified_command_router import unified_router
            intent, params = unified_router.route_command(query)
            intent_name = intent.name
        except Exception as e:
            logger.error(f"[RAGRouter] Failed to invoke unified_router: {e}")
            intent_name = "GENERAL_CONVERSATION"
            params = {}

        mapping = self._INTENT_MAP.get(intent_name, {
            "core_intent": "chat",
            "sub_intent": "general_knowledge"
        })

        logger.info(f"[RAGRouter] '{intent_name}' -> core_intent='{mapping['core_intent']}' (preserving unified_intent)")

        return {
            "core_intent": mapping["core_intent"],
            "sub_intent": mapping["sub_intent"],
            "command": None,          # Commands are handled upstream by UnifiedCommandRouter
            "unified_intent": intent_name,  # CRITICAL: Always preserve original intent
            "params": params,
        }
