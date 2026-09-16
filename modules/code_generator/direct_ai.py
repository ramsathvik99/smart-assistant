import os
import re
from extensions.llm_engine import LLMEngine
from modules.code_generator.utils import save_file_smart

# Shared engine — same provider/fallback chain used everywhere
_engine = LLMEngine()

def generate_code_ai(prompt: str) -> str:
    """
    Direct AI code generation using the central LLMEngine.

    BEFORE: direct OpenAI(gpt-4o-mini) call — bypassed all fallback logic
    AFTER:  LLMEngine.get_completion() → configured provider → fallback chain
    """
    print("[DEBUG] CODE AI CALLED")
    try:
        system_prompt = "You are an expert programmer. Write clean and correct code."
        content = _engine.get_completion(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=1500
        )

        if not content:
            print("[DEBUG] LLMEngine returned no content")
            return "Sorry, I couldn't generate the code."

        # Clean code (remove markdown blocks)
        code = content.strip()
        code = re.sub(r'```(?:\w+)?\n', '', code)
        code = code.replace('```', '')

        # Detect language and set extension
        ext = ".py"
        prompt_lower = prompt.lower()
        if "java" in prompt_lower:
            ext = ".java"
        elif "c++" in prompt_lower or "cpp" in prompt_lower:
            ext = ".cpp"
        elif "javascript" in prompt_lower or " js" in prompt_lower:
            ext = ".js"

        # Generate clean filename
        filename = prompt_lower.replace("write code for", "").replace("write code", "").strip()
        filename = re.sub(r'[^a-z0-9\s_]', '', filename)
        filename = filename.replace(" ", "_")
        if not filename:
            filename = "generated_code"

        # Save to Downloads
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(downloads, exist_ok=True)
        filepath = os.path.join(downloads, f"{filename}{ext}")

        # Unique filepath if already exists
        counter = 1
        while os.path.exists(filepath):
            filepath = os.path.join(downloads, f"{filename}_{counter}{ext}")
            counter += 1

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"[DEBUG] Code saved to: {filepath}")

        # Open in VS Code
        try:
            os.system(f'code "{filepath}"')
        except Exception as os_err:
            print(f"[DEBUG] Failed to open VS Code: {os_err}")

        return "I've created the code file for you."

    except Exception as e:
        print(f"[DEBUG] Error in generate_code_ai: {e}")
        return "Sorry, I couldn't generate the code."
