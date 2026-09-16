import sys
from core.config import CONFIG
from legacy.memory_manager import add_history, get_chat_history
from extensions.llm_engine import LLMEngine

# Single shared engine instance — all calls go through the central provider/fallback chain
_engine = LLMEngine()

# ---------------------------------------------------------
#        BACKWARD COMPATIBILITY FUNCTIONS
# ---------------------------------------------------------
def call_openai(prompt, context="", system_prompt=None, temperature=0.7, max_tokens=500):
    """
    Backward compatibility wrapper for legacy code that imports call_openai.
    Delegates to the centralized LLMEngine.
    """
    return _engine.get_completion(
        prompt=prompt,
        context=context,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens
    )

def call_huggingface(prompt, context="", system_prompt=None, temperature=0.7, max_tokens=500):
    """
    Backward compatibility wrapper for legacy code that imports call_huggingface.
    Delegates to the centralized LLMEngine.
    """
    return _engine.get_completion(
        prompt=prompt,
        context=context,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens
    )

def call_groq(prompt, context="", system_prompt=None, temperature=0.7, max_tokens=500):
    """
    Backward compatibility wrapper for legacy code that imports call_groq.
    Delegates to the centralized LLMEngine.
    """
    return _engine.get_completion(
        prompt=prompt,
        context=context,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens
    )

def call_gemini(prompt, context="", system_prompt=None, temperature=0.7, max_tokens=500):
    """
    Backward compatibility wrapper for legacy code that imports call_gemini.
    Delegates to the centralized LLMEngine.
    """
    return _engine.get_completion(
        prompt=prompt,
        context=context,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens
    )

def call_deepseek(prompt, context="", system_prompt=None, temperature=0.7, max_tokens=500):
    """
    Backward compatibility wrapper for legacy code that imports call_deepseek.
    Delegates to the centralized LLMEngine.
    """
    return _engine.get_completion(
        prompt=prompt,
        context=context,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens
    )

# ---------------------------------------------------------
#                   MAIN REPLY GENERATOR
# ---------------------------------------------------------
def generate_reply(user_input, chat_history):
    """
    Generate AI reply using:
    ✓ Memory (PostgreSQL)
    ✓ Central LLMEngine (OpenAI → Groq → Gemini → DeepSeek → HuggingFace)

    BEFORE: chatbrain → call_openai() / call_groq() / call_gemini() / ... (direct API calls)
    AFTER:  chatbrain → LLMEngine.get_completion() → configured provider / fallback
    """
    user_id = CONFIG["CURRENT_USER_ID"]

    # Resolve assistant name dynamically — no "Nova" hardcoding
    try:
        from instance.config import settings as _cfg
        _asst_name = _cfg.get_assistant_name() or "Assistant"
    except Exception:
        _asst_name = "Assistant"

    # Build the message context string from chat history for LLMEngine
    context_lines = []
    for m in chat_history:
        role_label = "User" if m["role"] == "user" else _asst_name
        context_lines.append(f"{role_label}: {m['content']}")
    context = "\n".join(context_lines[-10:])  # last 10 turns

    system_prompt = (
        f"You are {_asst_name}, a friendly personal AI assistant. "
        f"User ID: {user_id}. Use memory and conversation history to respond naturally."
    )

    # Save user message to DB
    add_history(user_id, "user", user_input)

    # Single authoritative LLM call — provider selected and fallback handled by LLMEngine
    reply = _engine.get_completion(
        prompt=user_input,
        context=context,
        system_prompt=system_prompt,
        temperature=0.8,
        max_tokens=250
    )

    if not reply:
        reply = "I'm sorry, I couldn't generate a response right now."

    # Save assistant reply to DB
    add_history(user_id, "assistant", reply)

    return reply
