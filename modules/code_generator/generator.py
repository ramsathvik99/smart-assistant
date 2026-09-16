from extensions.llm_engine import LLMEngine
from modules.code_generator.utils import clean_code

def generate_code(prompt: str, language: str = "python") -> str:
    """Generates code using the central multi-provider LLM engine with fallback."""
    system_prompt = (
        f"You are an expert {language} programmer. "
        f"Write clean, correct, and complete {language} code for the given problem. "
        f"Output the code in a standard markdown code block."
    )

    try:
        engine = LLMEngine()
        response = engine.get_completion(prompt, system_prompt=system_prompt, max_tokens=1500)
        if response and response.strip():
            cleaned = clean_code(response)
            if cleaned and "sorry, i could not generate code" not in cleaned.lower():
                return cleaned
    except Exception as e:
        print(f"[Generator EXCEPTION] {type(e).__name__}: {e}")

    return "Sorry, I could not generate code"

