"""
assistant_os/agents/conversation_agent.py
======================================
NOVA OS - Conversation Agent

Architecture:
    This agent wraps the existing dialogue manager, personality engine,
    and conversational brain.

    BaseAgent ──► ConversationAgent
                       │
                       ├───► DialogueManager (extensions/dialogue_engine/)
                       ├───► PersonalityCore & format_response (extensions/personality_engine/)
                       └───► generate_reply & get_chat_history (core/chatbrain.py & legacy/memory_manager.py)

    This agent does NOT duplicate any conversational logic. It acts as
    the standardized agentic interface (AgentTask -> AgentResult) for the
    entirety of NOVA OS conversation pathways.

SDD Reference: Section 26 (Conversation Agent).
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional

from assistant_os.planner.models import AgentType
from assistant_os.agent_manager.models import AgentManifest
from assistant_os.agents.models import (
    AgentOutputType,
    AgentResult,
    AgentStatus,
    AgentTask,
)
from assistant_os.agents.base_agent import BaseAgent

# Reuse existing modules safely without duplicate logic
from extensions.dialogue_engine import get_dialogue_manager
from extensions.personality_engine import get_personality, format_response
from core.chatbrain import generate_reply
from legacy.memory_manager import get_chat_history, add_history
from instance.config import settings as CONFIG

logger = logging.getLogger("assistant_os.agents.conversation")


class ConversationAgent(BaseAgent):
    """
    Handles natural language dialogue, clarification requests,
    slot filling, and personality-driven formatted chat responses.
    """

    AGENT_MANIFEST = AgentManifest(
        agent_type=AgentType.CONVERSATION,
        display_name="Conversation Agent",
        description="Handles all direct user conversation, personality styling, and clarifications.",
        capabilities=["converse", "clarify", "personalize"],
        intent_patterns=[
            "chat", "talk", "tell me", "what is", "who is",
            "explain", "describe", "how does", "why does", "joke", "story",
        ],
        max_concurrent=5,
        requires_llm=True,
        requires_network=True,
    )

    def __init__(self, tools=None):
        """Initialise agent and hook into dialogue and personality controllers."""
        super().__init__(tools)
        self.dialogue_manager = get_dialogue_manager()
        self.personality = get_personality()

    def execute(self, task: AgentTask) -> AgentResult:
        user_input = task.instruction
        user_id = task.user_id or CONFIG.get("CURRENT_USER_ID", 1)

        # 1. Attempt Dialogue Manager first (for slot-filling or follow-up flow)
        try:
            dialogue_response = self.dialogue_manager.handle(user_input)
            if dialogue_response is not None:
                self.logger.info("[ConversationAgent] Handled via DialogueManager.")
                # Personalize and format response
                formatted_resp = format_response(dialogue_response, self.personality)
                return self._success(task, formatted_resp, AgentOutputType.TEXT)
        except Exception as exc:
            self.logger.warning(
                f"[ConversationAgent] DialogueManager check failed: {exc}"
            )

        # 2. Fall back to LLM reply generator (chatbrain)
        try:
            self.logger.info("[ConversationAgent] Generating reply via LLM Chatbrain.")
            # Retrieve last 30 turns of conversational history
            chat_history = get_chat_history(user_id, limit=30)
            
            # generate_reply automatically registers user and assistant inputs to DB
            reply = generate_reply(user_input, chat_history)
            
            # Format and apply assistant personality constraints
            formatted_reply = format_response(reply, self.personality)
            return self._success(task, formatted_reply, AgentOutputType.TEXT)
        except Exception as exc:
            self.logger.exception(
                f"[ConversationAgent] Chatbrain reply generation failed: {exc}"
            )
            return self._failure(task, f"Conversational processing error: {exc}")
