from extensions.ai_utils import ask_llm

def recommend_movie(query: str) -> str:
    """
    Uses LLM to generate movie recommendations dynamically
    """
    prompt = f"""
You are a movie recommendation assistant.

User query: "{query}"

Generate a clean and well-structured response with:

* A title/header
* 5 to 6 movie recommendations
* Each movie on a new small line with bullet points
* No explanations unless asked
* Keep it neat and readable

Example format:

🎬 Recommended Movies:

* Movie 1
* Movie 2
* Movie 3
"""
    
    try:
        response = ask_llm(prompt)
        return response.strip()
        
    except Exception as e:
        return f"❌ Error generating recommendations: {str(e)}"

__all__ = ["recommend_movie"]
