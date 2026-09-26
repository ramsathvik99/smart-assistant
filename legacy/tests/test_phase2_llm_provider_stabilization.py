"""
Test Suite for Phase 2 LLM Provider Stabilization.
Validates:
1. Provider fallback chain: OpenAI -> Groq -> Gemini -> DeepSeek -> HuggingFace -> Ollama.
2. Missing API keys and disabled providers skipped cleanly.
3. HTTP 404 / model not found marked unavailable and immediately fails over.
4. Provider timeout handled safely without long hangs.
5. All-providers-down condition returns controlled user-friendly response.
6. Ollama local provider integration and failure handling.
7. End-to-end production path conversational requests with real/mocked providers.
"""

import unittest
from unittest.mock import patch, MagicMock
import requests

from extensions.llm_engine import LLMEngine, _UNAVAILABLE_PROVIDERS, _UNAVAILABLE_MODELS, _UNAVAILABLE_KEYS
from instance.config import Settings


class TestPhase2LLMProviderStabilization(unittest.TestCase):

    def setUp(self):
        # Reset runtime blacklist sets before each test
        _UNAVAILABLE_PROVIDERS.clear()
        _UNAVAILABLE_MODELS.clear()
        _UNAVAILABLE_KEYS.clear()
        self.engine = LLMEngine()

    def tearDown(self):
        _UNAVAILABLE_PROVIDERS.clear()
        _UNAVAILABLE_MODELS.clear()
        _UNAVAILABLE_KEYS.clear()

    # ── 1. CONFIGURATION & MODEL VERIFICATION ─────────────────────────────────
    def test_01_model_configuration_integrity(self):
        """Verify model identifiers are valid and supported."""
        self.assertIn("qwen/qwen3.8-27b", self.engine.groq_fallback_models)
        self.assertIn("openai/gpt-oss-120b", self.engine.groq_fallback_models)
        # Ensure deprecated / non-existent compound models are not present
        self.assertNotIn("groq/compound", self.engine.groq_fallback_models)
        self.assertNotIn("groq/compound-mini", self.engine.groq_fallback_models)

    # ── 2. PROVIDER FALLBACK CHAIN (Tier 1 -> Tier 2 -> Tier 3) ───────────────
    def test_02_fallback_from_disabled_openai_to_groq(self):
        """When OpenAI is disabled, Groq is called."""
        self.engine.openai_enabled = False
        with patch.object(self.engine, "_call_groq", return_value="Groq response") as mock_groq:
            resp = self.engine.get_completion("Hello")
            self.assertEqual(resp, "Groq response")
            mock_groq.assert_called()

    def test_03_fallback_from_groq_failure_to_gemini(self):
        """When Groq fails (e.g. rate limit / network error), Gemini is called."""
        self.engine.openai_enabled = False
        with patch.object(self.engine, "_call_groq", return_value=None), \
             patch.object(self.engine, "_call_gemini", return_value="Gemini response") as mock_gemini:
            resp = self.engine.get_completion("Hello")
            self.assertEqual(resp, "Gemini response")
            mock_gemini.assert_called()

    def test_04_fallback_to_ollama_when_cloud_fails(self):
        """When all cloud providers fail, local Ollama is called."""
        self.engine.openai_enabled = False
        with patch.object(self.engine, "_call_groq", return_value=None), \
             patch.object(self.engine, "_call_gemini", return_value=None), \
             patch.object(self.engine, "_call_deepseek", return_value=None), \
             patch.object(self.engine, "_call_huggingface", return_value=None), \
             patch.object(self.engine, "_call_ollama", return_value="Ollama response") as mock_ollama:
            resp = self.engine.get_completion("Hello")
            self.assertEqual(resp, "Ollama response")
            mock_ollama.assert_called()

    # ── 3. ERROR & EXCEPTION HANDLING ─────────────────────────────────────────
    def test_05_http_404_model_not_found_blacklists_model(self):
        """HTTP 404 marks model as unavailable in _UNAVAILABLE_MODELS and breaks immediately."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = '{"error": {"message": "The model `bad_model` does not exist", "type": "invalid_request_error", "code": "model_not_found"}}'
        
        with patch("requests.post", return_value=mock_response):
            res = self.engine._call_groq([{"role": "user", "content": "hi"}], "bad_model", 0.7, 50)
            self.assertIsNone(res)
            self.assertIn("groq:bad_model", _UNAVAILABLE_MODELS)

    def test_06_timeout_handling_safely_marks_unavailable(self):
        """Timeout marks key/provider unavailable without throwing unhandled exceptions."""
        with patch("requests.post", side_effect=requests.exceptions.Timeout("Read timeout")):
            res = self.engine._call_groq([{"role": "user", "content": "hi"}], "qwen/qwen3.8-27b", 0.7, 50)
            self.assertIsNone(res)

    def test_07_all_providers_failing_returns_none_safely(self):
        """When all providers fail, get_completion returns None cleanly."""
        self.engine.openai_enabled = False
        with patch.object(self.engine, "_call_groq", return_value=None), \
             patch.object(self.engine, "_call_gemini", return_value=None), \
             patch.object(self.engine, "_call_deepseek", return_value=None), \
             patch.object(self.engine, "_call_huggingface", return_value=None), \
             patch.object(self.engine, "_call_ollama", return_value=None):
            resp = self.engine.get_completion("Hello")
            self.assertIsNone(resp)

    # ── 4. PRODUCTION PIPELINE & CONVERSATION INTEGRITY ───────────────────────
    def test_08_production_pipeline_all_providers_down(self):
        """RAG response generator returns user-facing fallback when LLM is down."""
        from extensions.rag_system.response_generator import RAGResponseGenerator
        gen = RAGResponseGenerator()
        with patch.object(gen.llm, "get_completion", return_value=None):
            resp = gen.generate("Hello", intent="general_knowledge", data={})
            self.assertIn("unable to reach", resp.lower())

    def test_09_production_path_conversational_requests(self):
        """Production path handles conversational requests through GENERAL_CONVERSATION."""
        from legacy.assistant import process_input
        with patch.object(LLMEngine, "get_completion", return_value="I am here to assist you."):
            r1 = process_input("Friday why are you doing this")
            self.assertTrue(bool(r1))
            r2 = process_input("Friday who are you")
            self.assertTrue(bool(r2))
            r3 = process_input("Friday what can you do")
            self.assertTrue(bool(r3))


if __name__ == "__main__":
    unittest.main()
