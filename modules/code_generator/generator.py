import re
from typing import Optional, Dict, Any, List
from extensions.llm_engine import LLMEngine
from modules.code_generator.utils import clean_code


def _normalize_uid(user_id: Any) -> Optional[int]:
    """Helper to safely coerce user_id to int or None for LLMEngine."""
    if user_id is None:
        return None
    try:
        return int(user_id)
    except (ValueError, TypeError):
        return None


def generate_code(
    prompt: str,
    language: str = "python",
    user_id: Optional[Any] = None,
    max_tokens: int = 3000,
    is_project: bool = False
) -> str:
    """
    Generates professional-grade code using the central multi-provider LLM engine with fallback.
    If is_project=True, delegates to generate_multi_file_project for structured multi-file output.
    """
    if is_project:
        return generate_multi_file_project(prompt, user_id=user_id, max_tokens=max_tokens)
    lang_clean = (language or "python").lower().strip()
    system_prompt = (
        f"You are an expert, professional software engineer specializing in {lang_clean}.\n"
        f"Generate complete, robust, production-grade {lang_clean} code that directly and fully solves the user's requirements.\n"
        f"Requirements:\n"
        f"1. Completeness: Write complete implementations. NEVER use placeholders, TODOs, pseudocode, or ellipses (...).\n"
        f"2. Correctness: Use correct syntax, standard library modules, idioms, and explicit error handling.\n"
        f"3. Maintainability: Provide clear type annotations, clean modular design, and concise docstrings.\n"
        f"4. Security: Prevent command injection, SQL injection, and path traversal.\n"
        f"5. Output format: Present the code inside a standard markdown code block (```{lang_clean} ... ```)."
    )

    try:
        engine = LLMEngine()
        uid = _normalize_uid(user_id)
        response = engine.get_completion(
            prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            user_id=uid,
            task_type="coding"
        )
        if response and response.strip():
            cleaned = clean_code(response)
            if cleaned and "sorry, i could not generate code" not in cleaned.lower():
                return cleaned
    except Exception as e:
        print(f"[Generator EXCEPTION] {type(e).__name__}: {e}")

    return "Sorry, I could not generate code"


def generate_multi_file_project(
    prompt: str,
    user_id: Optional[Any] = None,
    max_tokens: int = 4096
) -> str:
    """
    Generates a complete multi-file project using a structured delimiter protocol:
    FILE: relative/path/to/file.ext
    ```{language}
    ...content...
    ```
    """
    system_prompt = (
        "You are an elite principal software architect and full-stack software engineer.\n"
        "The user is requesting a complete multi-file application or project.\n"
        "You must generate ALL necessary files for a fully functioning deliverable (e.g. source files, configs, tests, README).\n"
        "Crucial Rules:\n"
        "1. Every single file must be completely implemented. NO placeholders, NO '// TODO', NO truncated snippets.\n"
        "2. Consistent naming, imports, routes, and contracts across all files.\n"
        "3. You MUST format each file using this exact delimiter format:\n\n"
        "FILE: relative/path/to/file.ext\n"
        "```language\n"
        "...complete file contents...\n"
        "```\n\n"
        "Ensure all file paths are strictly relative (do NOT start with '/' or 'C:\\' or contain '..')."
    )

    try:
        engine = LLMEngine()
        uid = _normalize_uid(user_id)
        response = engine.get_completion(
            prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            user_id=uid,
            task_type="coding"
        )
        if response and response.strip():
            return response
    except Exception as e:
        print(f"[Multi-File Generator EXCEPTION] {type(e).__name__}: {e}")

    return "Sorry, I could not generate the project"


def explain_code_with_llm(
    code: str,
    query: str = "",
    language: str = "python",
    user_id: Optional[Any] = None
) -> str:
    """
    Explains the purpose, logic, data flow, functions, algorithms, and potential edge cases of supplied code.
    Does not generate or save a new file.
    """
    lang_clean = (language or "python").lower().strip()
    system_prompt = (
        f"You are an expert technical educator and {lang_clean} software engineer.\n"
        "Analyze and explain the provided code clearly, accurately, and thoroughly.\n"
        "Cover:\n"
        "1. High-level Purpose & Architecture: What the code accomplishes.\n"
        "2. Key Functions & Logic: Step-by-step breakdown of algorithms, data structures, and significant lines.\n"
        "3. Data Flow: Inputs, outputs, state mutations, and edge-case handling.\n"
        "4. Potential Limitations or Defects: Any risks, missing validations, or performance concerns.\n"
        "Do not generate a new replacement file unless explicitly requested. Be direct and insightful."
    )
    user_content = f"User Request: {query or 'Explain this code'}\n\nCode to analyze:\n```{lang_clean}\n{code}\n```"

    try:
        engine = LLMEngine()
        uid = _normalize_uid(user_id)
        response = engine.get_completion(
            user_content,
            system_prompt=system_prompt,
            max_tokens=2500,
            user_id=uid,
            task_type="coding"
        )
        if response and response.strip():
            return response.strip()
    except Exception as e:
        print(f"[Explain Code EXCEPTION] {type(e).__name__}: {e}")

    return "Sorry, I could not analyze the code."


def fix_code_with_llm(
    code: str,
    query: str = "",
    language: str = "python",
    user_id: Optional[Any] = None,
    error_message: str = ""
) -> Dict[str, Any]:
    """
    Diagnoses underlying bugs, generates a targeted correction preserving existing behavior/APIs,
    and returns the fixed code along with an explanation of the fix.
    """
    lang_clean = (language or "python").lower().strip()
    system_prompt = (
        f"You are an expert {lang_clean} debugger and senior software engineer.\n"
        "Inspect the provided code and user request, identify the root cause of the bug or issue, and provide:\n"
        "1. The COMPLETE corrected code inside a single standard markdown code block (```{lang_clean} ... ```).\n"
        "2. A concise explanation of the root cause and the specific changes you made.\n"
        "Preserve existing architecture, public interfaces, and behavior outside the bug fix."
    )
    prompt_issue = query or "Fix the bugs in this code"
    if error_message:
        prompt_issue += f"\nSpecific Error: {error_message}"
    user_content = f"Issue/Request: {prompt_issue}\n\nCode to repair:\n```{lang_clean}\n{code}\n```"

    try:
        engine = LLMEngine()
        uid = _normalize_uid(user_id)
        response = engine.get_completion(
            user_content,
            system_prompt=system_prompt,
            max_tokens=3000,
            user_id=uid,
            task_type="coding"
        )
        if response and response.strip():
            fixed_code = clean_code(response)
            return {
                "success": True,
                "fixed_code": fixed_code,
                "explanation": response.strip(),
                "language": lang_clean
            }
    except Exception as e:
        print(f"[Fix Code EXCEPTION] {type(e).__name__}: {e}")

    return {
        "success": False,
        "fixed_code": code,
        "explanation": "Could not fix code with LLM.",
        "language": lang_clean
    }


def refactor_code_with_llm(
    code: str,
    query: str = "",
    language: str = "python",
    user_id: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Refactors the supplied code for enhanced readability, maintainability, modularity,
    clean separation of concerns, and performance while strictly preserving existing behavior and external contracts.
    """
    lang_clean = (language or "python").lower().strip()
    system_prompt = (
        f"You are a principal {lang_clean} software architect and refactoring specialist.\n"
        "Refactor the provided code according to clean code principles and the user's specific goals (readability, maintainability, performance).\n"
        "Requirements:\n"
        "1. Produce the COMPLETE refactored code inside a single standard markdown code block (```{lang_clean} ... ```).\n"
        "2. Provide a clear, bulleted summary of the refactoring improvements made.\n"
        "3. Strictly preserve all existing public APIs, behaviors, edge cases, and external contracts.\n"
        "4. DO NOT use placeholders, TODO comments, pseudocode, or truncated blocks."
    )
    user_content = f"Refactoring Request: {query or 'Refactor this code for readability, maintainability and performance'}\n\nCode to refactor:\n```{lang_clean}\n{code}\n```"

    try:
        engine = LLMEngine()
        uid = _normalize_uid(user_id)
        response = engine.get_completion(
            user_content,
            system_prompt=system_prompt,
            max_tokens=3000,
            user_id=uid,
            task_type="coding"
        )
        if response and response.strip():
            refactored_code = clean_code(response)
            return {
                "success": True,
                "refactored_code": refactored_code,
                "explanation": response.strip(),
                "language": lang_clean
            }
    except Exception as e:
        print(f"[Refactor Code EXCEPTION] {type(e).__name__}: {e}")

    return {
        "success": False,
        "refactored_code": code,
        "explanation": "Could not refactor code with LLM.",
        "language": lang_clean
    }
