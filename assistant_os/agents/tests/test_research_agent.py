"""
assistant_os/agents/tests/test_research_agent.py
===========================================
NOVA OS - Research Agent: Unit Tests

Coverage:
    - Initialization of RAGRetriever and LLMEngine.
    - Path execution: successful SerpAPI search + BeautifulSoup scraping + LLM report.
    - Fallback path execution: Wikipedia search when SerpAPI fails or returns errors.
    - Error path execution: fully failing when both search strategies fail.
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
from assistant_os.agents.research_agent import ResearchAgent


class TestResearchAgent(unittest.TestCase):

    @patch("assistant_os.agents.research_agent.RAGRetriever")
    @patch("assistant_os.agents.research_agent.LLMEngine")
    def setUp(self, mock_llm_class, mock_retriever_class):
        self.mock_retriever = MagicMock()
        mock_retriever_class.return_value = self.mock_retriever

        self.mock_llm = MagicMock()
        mock_llm_class.return_value = self.mock_llm

        self.agent = ResearchAgent()

    @patch("assistant_os.agents.research_agent.requests.get")
    def test_successful_search_and_scrape(self, mock_get):
        # 1. Mock retriever output
        self.mock_retriever.retrieve.return_value = {
            "answer_box": {"links": [{"link": "https://example.com/ai"}]},
            "organic_results": ["AI is growing fast in 2026."],
        }

        # 2. Mock web scraper response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><p>Deep details on AI growth.</p></body></html>"
        mock_get.return_value = mock_resp

        # 3. Mock LLM output
        self.mock_llm.get_completion.return_value = "# AI Research Report\n\n- Key trend: growth."

        task = AgentTask(
            agent_type=AgentType.RESEARCH,
            instruction="Research AI trends",
        )
        result = self.agent.run(task)

        self.assertTrue(result.is_success)
        self.assertEqual(result.status, AgentStatus.SUCCESS)
        self.assertEqual(result.output_type, AgentOutputType.MARKDOWN)
        self.assertIn("# AI Research Report", result.content)

        # Verify calls
        self.mock_retriever.retrieve.assert_called_once_with("real_time_info", "Research AI trends")
        mock_get.assert_called_once_with("https://example.com/ai", timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        self.mock_llm.get_completion.assert_called_once()

    @patch("wikipedia.page")
    @patch("wikipedia.search")
    def test_wikipedia_fallback(self, mock_search, mock_page_class):
        # 1. Force retriever fail
        self.mock_retriever.retrieve.return_value = {"error": "SerpAPI key missing"}

        # 2. Mock wikipedia response
        mock_search.return_value = ["Quantum Computing"]
        mock_page = MagicMock()
        mock_page.title = "Quantum Computing"
        mock_page.content = "Quantum computing is a rapidly-emerging technology..."
        mock_page_class.return_value = mock_page

        # 3. Mock LLM output
        self.mock_llm.get_completion.return_value = "# Quantum Computing Report"

        task = AgentTask(
            agent_type=AgentType.RESEARCH,
            instruction="quantum computing",
        )
        result = self.agent.run(task)

        self.assertTrue(result.is_success)
        self.assertEqual(result.status, AgentStatus.SUCCESS)
        self.assertEqual(result.content, "# Quantum Computing Report")
        mock_search.assert_called_once_with("quantum computing")
        mock_page_class.assert_called_once_with("Quantum Computing")

    def test_total_failure(self):
        # 1. Force retriever fail
        self.mock_retriever.retrieve.return_value = {"error": "SerpAPI error"}
        
        # 2. Force wikipedia fail (by throwing exception or empty search)
        with patch("wikipedia.search", return_value=[]):
            task = AgentTask(
                agent_type=AgentType.RESEARCH,
                instruction="invalid_query_xyz",
            )
            result = self.agent.run(task)

            self.assertTrue(result.is_failure)
            self.assertEqual(result.status, AgentStatus.FAILED)
            self.assertIn("Search failed", result.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
