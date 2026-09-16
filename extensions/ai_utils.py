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
