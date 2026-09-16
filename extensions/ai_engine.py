import os
import requests
from instance.config import settings as CONFIG
from extensions.llm_engine import LLMEngine
from extensions.context_manager import get_manager


class AIEngine:
    """
    Robust AI Engine with provider management.
    Delegates all LLM generation to the central LLMEngine.
    Integrates with DatabaseManager for logging and ContextManager for personalization.

    BEFORE: AIEngine._call_openai() / _call_groq() → direct provider API
    AFTER:  AIEngine.get_response() → LLMEngine.get_completion() → configured provider / fallback
    """
    def __init__(self):
        self._engine = LLMEngine()
        self.db_manager = None
        self.current_user_id = None

    def set_db_manager(self, db_manager, user_id):
        self.db_manager = db_manager
        self.current_user_id = user_id

    def validate_apis(self):
        """Validates configured providers at startup via a lightweight LLMEngine probe."""
        print("[AI Engine] Validating providers via LLMEngine...")
        result = self._engine.get_completion("ping", max_tokens=5)
        if result:
            print("[AI Engine] At least one LLM provider is reachable.")
        else:
            print("[AI Engine] WARNING: No LLM providers responded. AI features will be limited.")

    def get_response(self, prompt: str, system_prompt: str = None) -> str:
        """
        AI response via central LLMEngine: provider selection and fallback handled there.
        """
        if not system_prompt:
            ctx = get_manager()
            tone = ctx.get_active_preference("tone", "professional")
            # Get current assistant name — never fall back to "Nova"
            try:
                from instance.config import settings as _cfg
                _asst_name = _cfg.get_assistant_name() or "your assistant"
            except Exception:
                _asst_name = "your assistant"
            prompts = {
                "professional": f"You are {_asst_name}, an efficient and professional AI assistant. Keep responses formal, technical, and direct. Avoid fluff.",
                "friendly": f"You are {_asst_name}, a warm and friendly AI companion. Use a natural, helpful, and kind tone. Feel free to use encouraging words.",
                "casual": f"I'm {_asst_name}. Keep it chill, use casual language, avoid formal greetings, and be brief and cool."
            }
            system_prompt = prompts.get(tone, prompts["professional"])

        response = self._engine.get_completion(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=150
        )
        model_used = "llm_engine"

        if not response:
            response = "I'm currently unable to access my online intelligence layer. I can still help with local system tasks though."
            model_used = "fallback"

        # Log Interaction
        if self.db_manager and self.current_user_id:
            try:
                self.db_manager.log_ai_interaction(self.current_user_id, prompt, response, model_used)
            except Exception as e:
                print(f"[AI ERROR] Database logging failed: {e}")

        return response


# Global AI engine instance
_ai_engine = None

def get_llm_engine():
    """Get the global AI engine instance"""
    global _ai_engine
    if _ai_engine is None:
        _ai_engine = AIEngine()
        _ai_engine.validate_apis()
    return _ai_engine

def reset_ai_engine():
    """Reset the global AI engine instance (for testing)"""
    global _ai_engine
    _ai_engine = None
