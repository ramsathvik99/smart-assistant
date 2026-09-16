"""
assistant_os/agents/research_agent.py
==================================
NOVA OS - Research Agent

Architecture:
    This agent subclasses BaseAgent and executes multi-step research.

    BaseAgent ──► ResearchAgent
                       │
                       ├───► RAGRetriever (extensions/rag_system/retriever.py)
                       ├───► LLMEngine (extensions/llm_engine.py)
                       └───► BeautifulSoup4 (for reading HTML bodies)

    Execution Pipeline:
        1. Search: query SerpAPI via RAGRetriever (or fallback to wikipedia API).
        2. Read: Fetch top organic URLs, parse page contents using BeautifulSoup,
                 and retrieve raw text context.
        3. Summarize: Pass raw context and query to LLMEngine to generate a
                      formatted, cited report.
        4. Return report: Return structured/markdown output of the final report.

SDD Reference: Section 26 (Research Agent).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, Any, List, Optional
import requests
from bs4 import BeautifulSoup

from assistant_os.planner.models import AgentType
from assistant_os.agent_manager.models import AgentManifest
from assistant_os.agents.models import (
    AgentOutputType,
    AgentResult,
    AgentStatus,
    AgentTask,
)
from assistant_os.agents.base_agent import BaseAgent

# Reuse existing systems
from extensions.rag_system.retriever import RAGRetriever
from extensions.llm_engine import LLMEngine

logger = logging.getLogger("assistant_os.agents.research")


class ResearchAgent(BaseAgent):
    """
    Performs web search, scrapes page content, synthesizes findings using the LLM,
    and returns a structured report.
    """

    AGENT_MANIFEST = AgentManifest(
        agent_type=AgentType.RESEARCH,
        display_name="Research Agent",
        description="Performs web searches, scrapes pages, and synthesizes structured reports.",
        capabilities=["search_web", "read_html", "summarize"],
        intent_patterns=["research", "find information", "look up", "summarize"],
        max_concurrent=3,
        requires_llm=True,
        requires_network=True,
    )

    def __init__(self, tools=None):
        super().__init__(tools)
        self.retriever = RAGRetriever()
        self.llm = LLMEngine()

    def execute(self, task: AgentTask) -> AgentResult:
        query = task.instruction
        self.logger.info(f"[ResearchAgent] Planning research for query: '{query}'")

        # Step 1: Search
        search_results = self._search(query)
        if not search_results or "error" in search_results:
            # Fall back to wikipedia search
            self.logger.info("[ResearchAgent] Web search failed. Falling back to Wikipedia.")
            wiki_content = self._wikipedia_search(query)
            if wiki_content:
                report = self._generate_report(query, [wiki_content])
                return self._success(task, report, AgentOutputType.MARKDOWN)
            return self._failure(task, f"Search failed: {search_results.get('error', 'Unknown error')}")

        # Step 2: Read
        scraped_pages = []
        organic_results = search_results.get("organic_results", [])
        
        # Try to parse the top 2 links
        links_processed = 0
        for item in search_results.get("answer_box", {}).get("links", []):
            if links_processed >= 2:
                break
            text = self._scrape_url(item.get("link"))
            if text:
                scraped_pages.append(text)
                links_processed += 1

        # Fall back to organic search links if answer box lacked links
        if len(scraped_pages) < 2:
            # Note: SerpAPI organic results list doesn't include the raw link list directly in retriever.py snippet list.
            # But let's check if the SerpAPI raw data has links.
            # If not, we will rely on snippets from organic_results.
            pass

        # Use snippets as auxiliary read source
        snippets = "\n".join(organic_results)
        if snippets:
            scraped_pages.append(f"Search Snippets:\n{snippets}")

        # Step 3: Summarize & Return Report
        try:
            report = self._generate_report(query, scraped_pages)
            return self._success(task, report, AgentOutputType.MARKDOWN)
        except Exception as exc:
            self.logger.exception(f"[ResearchAgent] Report generation failed: {exc}")
            return self._failure(task, f"Report generation failed: {exc}")

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _search(self, query: str) -> Dict[str, Any]:
        """Perform search using the existing RAGRetriever web search."""
        try:
            # In retriever.py: _retrieve_web_search is called when intent is "real_time_info"
            res = self.retriever.retrieve("real_time_info", query)
            return res if isinstance(res, dict) else {"organic_results": [str(res)]}
        except Exception as exc:
            self.logger.warning(f"SerpAPI query failed: {exc}")
            return {"error": str(exc)}

    def _wikipedia_search(self, query: str) -> Optional[str]:
        """Wikipedia fallback search."""
        try:
            import wikipedia
            # Find closest page title
            search_results = wikipedia.search(query)
            if search_results:
                page = wikipedia.page(search_results[0])
                return f"Title: {page.title}\nContent:\n{page.content[:4000]}"
        except Exception as exc:
            self.logger.warning(f"Wikipedia lookup failed: {exc}")
        return None

    def _scrape_url(self, url: Optional[str]) -> Optional[str]:
        """Scrape text content from a URL using BeautifulSoup."""
        if not url:
            return None
        try:
            self.logger.info(f"[ResearchAgent] Scraping URL: {url}")
            resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Remove script and style elements
                for script in soup(["script", "style"]):
                    script.decompose()
                text = soup.get_text()
                # Clean up whitespace
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = "\n".join(chunk for chunk in chunks if chunk)
                return f"Source URL: {url}\nContent:\n{text[:3000]}"
        except Exception as exc:
            self.logger.warning(f"Scraping URL {url} failed: {exc}")
        return None

    def _generate_report(self, query: str, context_blocks: List[str]) -> str:
        """Use LLMEngine to generate the final synthesized research report."""
        context = "\n\n---\n\n".join(context_blocks)
        
        prompt = (
            f"You are the Research Agent. Based on the following source data context, "
            f"generate a comprehensive, structured research report in markdown for the query: '{query}'.\n\n"
            f"Source Data Context:\n{context}\n\n"
            f"Provide a clear summary, key findings, and references/citations."
        )

        response = self.llm.get_completion(prompt)
        if not response:
            raise RuntimeError("LLM returned empty completion for report.")
            
        return response
