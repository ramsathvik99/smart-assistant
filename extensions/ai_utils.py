"""
AI Utilities - Wrapper for Nova's LLM Engine
Provides simple interface for LLM calls across modules
"""

def ask_llm(prompt: str) -> str:
    """
    Simple wrapper to call Nova's LLM engine
    Returns LLM response as string
    """
    try:
        # Check for interrupt before calling LLM
        try:
            from core.state_manager import state_manager
            if state_manager.is_interrupted():
                print("[AI_UTILS] Interrupted before LLM call")
                return "❌ Request interrupted"
        except ImportError:
            pass
        
        from .llm_engine import LLMEngine
        engine = LLMEngine()
        response = engine.get_completion(prompt)
        
        # Check for interrupt after LLM response
        try:
            from core.state_manager import state_manager
            if state_manager.is_interrupted():
                print("[AI_UTILS] Interrupted after LLM call")
                return "❌ Request interrupted"
        except ImportError:
            pass
        
        if response is None:
            return "❌ LLM engine not available"
        
        return response.strip()
        
    except Exception as e:
        return f"❌ Error calling LLM: {str(e)}"

# ── Centralized Provider Functions (Delegates to LLMEngine) ──
_shared_engine = None

def _get_engine():
    global _shared_engine
    if _shared_engine is None:
        from .llm_engine import LLMEngine
        _shared_engine = LLMEngine()
    return _shared_engine

def call_openai(prompt, context="", system_prompt=None, temperature=0.7, max_tokens=500):
    return _get_engine().get_completion(prompt=prompt, context=context, system_prompt=system_prompt, temperature=temperature, max_tokens=max_tokens)

def call_gemini(prompt, context="", system_prompt=None, temperature=0.7, max_tokens=500):
    return _get_engine().get_completion(prompt=prompt, context=context, system_prompt=system_prompt, temperature=temperature, max_tokens=max_tokens)

def call_groq(prompt, context="", system_prompt=None, temperature=0.7, max_tokens=500):
    return _get_engine().get_completion(prompt=prompt, context=context, system_prompt=system_prompt, temperature=temperature, max_tokens=max_tokens)

def call_huggingface(prompt, context="", system_prompt=None, temperature=0.7, max_tokens=500):
    return _get_engine().get_completion(prompt=prompt, context=context, system_prompt=system_prompt, temperature=temperature, max_tokens=max_tokens)

def call_deepseek(prompt, context="", system_prompt=None, temperature=0.7, max_tokens=500):
    return _get_engine().get_completion(prompt=prompt, context=context, system_prompt=system_prompt, temperature=temperature, max_tokens=max_tokens)

