"""
assistant_os/agents/tests/test_conversation_agent.py
================================================
NOVA OS - Conversation Agent: Unit Tests

Coverage:
    - Initialization of DialogueManager and PersonalityCore.
    - Delegation to DialogueManager when matching intents exist.
    - Fallback to LLM reply generation (chatbrain) for general conversation.
    - Formatting response via the personality engine.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from assistant_os.planner.models import AgentType
from assistant_os.agents.models import AgentStatus, AgentOutputType, AgentTask
from assistant_os.agents.conversation_agent import ConversationAgent


class TestConversationAgent(unittest.TestCase):

    @patch("assistant_os.agents.conversation_agent.get_dialogue_manager")
    @patch("assistant_os.agents.conversation_agent.get_personality")
    def setUp(self, mock_personality, mock_dialogue):
        # Configure Mocks
        self.mock_dm = MagicMock()
        mock_dialogue.return_value = self.mock_dm

        self.mock_pers = MagicMock()
        mock_personality.return_value = self.mock_pers

        self.agent = ConversationAgent()

    @patch("assistant_os.agents.conversation_agent.format_response")
    def test_dialogue_manager_match(self, mock_format):
        # Setup dialogue manager returning a response directly
        self.mock_dm.handle.return_value = "Clarification: do you mean project A?"
        mock_format.return_value = "JARVIS: Clarification: do you mean project A?"

        task = AgentTask(
            agent_type=AgentType.CONVERSATION,
            instruction="open project",
        )
        result = self.agent.run(task)

        self.assertTrue(result.is_success)
        self.assertEqual(result.status, AgentStatus.SUCCESS)
        self.assertEqual(result.content, "JARVIS: Clarification: do you mean project A?")
        self.mock_dm.handle.assert_called_once_with("open project")

    @patch("assistant_os.agents.conversation_agent.get_chat_history")
    @patch("assistant_os.agents.conversation_agent.generate_reply")
    @patch("assistant_os.agents.conversation_agent.format_response")
    def test_chatbrain_fallback(self, mock_format, mock_reply, mock_history):
        # Dialogue manager does not handle input (returns None)
        self.mock_dm.handle.return_value = None

        mock_history.return_value = [{"role": "user", "content": "hi"}]
        mock_reply.return_value = "Hello, I am the Assistant."
        mock_format.return_value = "JARVIS: Hello, I am the Assistant."

        task = AgentTask(
            agent_type=AgentType.CONVERSATION,
            instruction="Tell me about yourself",
        )
        result = self.agent.run(task)

        self.assertTrue(result.is_success)
        self.assertEqual(result.status, AgentStatus.SUCCESS)
        self.assertEqual(result.content, "JARVIS: Hello, I am the Assistant.")
        mock_reply.assert_called_once()

    @patch("assistant_os.agents.conversation_agent.get_chat_history")
    @patch("assistant_os.agents.conversation_agent.generate_reply")
    def test_chatbrain_failure(self, mock_reply, mock_history):
        self.mock_dm.handle.return_value = None
        mock_history.return_value = []
        mock_reply.side_effect = Exception("LLM connection timed out")

        task = AgentTask(
            agent_type=AgentType.CONVERSATION,
            instruction="What is the weather?",
        )
        result = self.agent.run(task)

        self.assertTrue(result.is_failure)
        self.assertEqual(result.status, AgentStatus.FAILED)
        self.assertIn("Conversational processing error", result.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
