from extensions.ai_utils import ask_llm
from datetime import datetime

current_year = datetime.now().year

def recommend(query: str) -> str:
    """
    Universal recommendation engine powered by LLM
    Handles ANY type of recommendation query with focus on real items
    """
    # Check for interrupt before processing
    try:
        from core.state_manager import state_manager
        if state_manager.is_interrupted():
            print("[RECOMMENDATION] Interrupted before processing")
            return "❌ Request interrupted"
    except ImportError:
        pass
    
    # Check if user explicitly asks for latest items
    query_lower = query.lower()
    wants_latest = any(word in query_lower for word in ["latest", "newest", "recent", "current"])
    
    if wants_latest:
        prompt = f"""
You are a recommendation system.

User query: "{query}"

RULES:

* Recommend ONLY real, existing items
* DO NOT invent names or fake items
* Prioritize very recent releases (last 1-2 years)
* If unsure about latest releases, suggest well-known recent ones
* Do NOT guess unknown future items
* Focus on items that actually exist and are verifiable

OUTPUT FORMAT:

* Clear title
* 5-7 bullet points
* Clean and readable
"""
    else:
        prompt = f"""
You are a recommendation system.

User query: "{query}"

RULES:

* Recommend ONLY real, existing items
* DO NOT invent names or fake items
* Prefer recent and popular items (last few years)
* It is OK to include items from different years if relevant
* Do NOT force all items to be from the current year
* If unsure about latest releases, suggest well-known recent ones

OUTPUT FORMAT:

* Clear title
* 5-7 bullet points
* Clean and readable
"""
    
    try:
        response = ask_llm(prompt).strip()
        
        # Check for interrupt after LLM call
        try:
            from core.state_manager import state_manager
            if state_manager.is_interrupted():
                print("[RECOMMENDATION] Interrupted after LLM call")
                return "❌ Request interrupted"
        except ImportError:
            pass
        
        return response
        
    except Exception as e:
        return f"❌ Recommendation error: {str(e)}"

__all__ = ["recommend"]
