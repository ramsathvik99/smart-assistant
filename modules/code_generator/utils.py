# utils.py
import re
import os
import time
from datetime import datetime
from modules.code_generator.config import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, BLOCKED_KEYWORDS

def detect_language(prompt: str) -> str:
    """Detects the target programming language from the prompt using smarter matching."""
    text = prompt.lower()
    if "c++" in text or "cpp" in text or "c plus plus" in text:
        return "cpp"
    elif "java" in text and "javascript" not in text:
        return "java"
    elif "javascript" in text or "js" in text or "node" in text:
        return "javascript"
    else:
        return "python"

def is_web_request(prompt: str) -> bool:
    """Always returns False to bypass blocking of web requests."""
    return False

def clean_code(code: str) -> str:
    """Extracts actual code by removing markdown blocks and cleaning it."""
    # Try to find content inside markdown code blocks ```...```
    match = re.search(r'```(?:[\w+\-]+)?\n(.*?)```', code, re.DOTALL)
    if match:
        code = match.group(1).strip()
    
    # Strict cleaning as requested
    code = code.replace("`python", "")
    code = code.replace("`", "")
    return code.strip()

def extract_filename_from_command(command: str) -> str:
    """Extracts a meaningful, clean filename base from the user's command."""
    remove_words = {
        "create", "generate", "write", "make", "build", "a", "an", "the",
        "program", "code", "script", "in", "using", "with", "for",
        "essay", "on", "about", "story", "letter", "notes", "summary", "paragraph"
    }
    words = command.lower().split()
    # Remove language names from the end if present (they go in extension)
    filtered = [w for w in words if w not in remove_words]
    filename = "_".join(filtered[:5])  # max 5 meaningful words
    # Strip special characters
    filename = re.sub(r'[^a-zA-Z0-9_]', '', filename)
    return filename if filename else "output"

def get_unique_filepath(folder: str, base_name: str, extension: str) -> str:
    """Returns a unique filepath, appending _1, _2 etc. if file already exists."""
    filepath = os.path.join(folder, f"{base_name}{extension}")
    if not os.path.exists(filepath):
        return filepath
    counter = 1
    while True:
        candidate = os.path.join(folder, f"{base_name}_{counter}{extension}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1

def generate_filename(prompt: str, extension: str) -> str:
    """Generates a human-readable filename based on the prompt."""
    base_name = extract_filename_from_command(prompt)
    downloads_folder = get_downloads_folder()
    return os.path.basename(get_unique_filepath(downloads_folder, base_name, extension))

def get_downloads_folder() -> str:
    """Returns the path to the user's Downloads folder (cross-platform)."""
    return os.path.join(os.path.expanduser("~"), "Downloads")


def save_file(filename: str, code: str) -> str:
    """Saves content to the user's Downloads folder and returns the absolute filepath with strict verification."""
    print("[DEBUG] Saving code...")
    
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    print("[DEBUG] Downloads path:", downloads)
    os.makedirs(downloads, exist_ok=True)
    
    filepath = os.path.join(downloads, filename)
    print("[DEBUG] Filename:", filename)
    print("[DEBUG] File path:", filepath)
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)
        print("[DEBUG] File successfully written")
    except Exception as e:
        print("[ERROR] File write failed:", e)
        return ""
        
    if os.path.exists(filepath):
        print("[DEBUG] File exists confirmed")
        return filepath
    else:
        print("[ERROR] File NOT created")
        return ""

def save_file_smart(command: str, content: str, extension: str) -> str:
    """Saves content with a human-readable filename derived from the command."""
    downloads_folder = get_downloads_folder()
    os.makedirs(downloads_folder, exist_ok=True)
    base_name = extract_filename_from_command(command)
    filepath = get_unique_filepath(downloads_folder, base_name, extension)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def validate_code_syntax(code: str, language: str = "python") -> dict:
    """
    Validate code syntax without executing it.
    Uses ast.parse for Python and delimiter balancing for other languages.
    """
    lang = (language or "python").lower().strip()

    if lang in ("python", "py"):
        import ast
        try:
            ast.parse(code)
            return {
                "valid": True,
                "language": "python",
                "message": "Python syntax is valid."
            }
        except SyntaxError as e:
            return {
                "valid": False,
                "language": "python",
                "line": e.lineno,
                "offset": e.offset,
                "error": e.msg,
                "text": e.text.strip() if e.text else "",
                "message": f"Python SyntaxError at line {e.lineno}: {e.msg}."
            }

    elif lang in ("json",):
        import json
        try:
            json.loads(code)
            return {"valid": True, "language": "json", "message": "JSON is valid."}
        except json.JSONDecodeError as e:
            return {
                "valid": False,
                "language": "json",
                "line": e.lineno,
                "col": e.colno,
                "error": str(e),
                "message": f"Invalid JSON at line {e.lineno}, col {e.colno}: {e.msg}."
            }

    else:
        # Bracket and delimiter balancing check
        stack = []
        pairs = {')': '(', '}': '{', ']': '['}
        line_num = 1
        for i, char in enumerate(code):
            if char == '\n':
                line_num += 1
            elif char in "({[":
                stack.append((char, line_num))
            elif char in ")}]":
                if not stack or stack[-1][0] != pairs[char]:
                    return {
                        "valid": False,
                        "language": lang,
                        "line": line_num,
                        "message": f"Mismatched closing bracket '{char}' at line {line_num}."
                    }
                stack.pop()

        if stack:
            unclosed, u_line = stack[-1]
            return {
                "valid": False,
                "language": lang,
                "line": u_line,
                "message": f"Unclosed '{unclosed}' opened at line {u_line}."
            }

        return {
            "valid": True,
            "language": lang,
            "message": f"{language.capitalize()} syntax appears balanced."
        }


def explain_code_structure(code: str, language: str = "python") -> dict:
    """
    Analyzes code to extract structural elements: classes, functions, imports, and metrics.
    """
    lang = (language or "python").lower().strip()
    if lang in ("python", "py"):
        import ast
        try:
            tree = None
            try:
                tree = ast.parse(code)
            except SyntaxError:
                if "\n" not in code:
                    s_norm = re.sub(r'\b(def\s+)', r'\n    \1', code)
                    s_norm = re.sub(r'\b(return\s+)', r'\n        \1', s_norm)
                    try:
                        tree = ast.parse(s_norm)
                    except SyntaxError:
                        pass

            if tree is not None:
                funcs = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
                classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append(node.module)
            else:
                classes = re.findall(r'\bclass\s+([A-Za-z_]\w*)', code)
                funcs = re.findall(r'\bdef\s+([A-Za-z_]\w*)', code)
                imports = re.findall(r'\b(?:import|from)\s+([A-Za-z_]\w*)', code)

            total_lines = len(code.splitlines())
            speech = (
                f"Code has {total_lines} lines, {len(classes)} class(es) ({', '.join(classes[:3])}), "
                f"and {len(funcs)} function(s) ({', '.join(funcs[:3])})."
            )

            return {
                "success": True,
                "status": "success",
                "total_lines": total_lines,
                "classes": classes,
                "functions": funcs,
                "imports": list(set(imports)),
                "message": speech
            }
        except Exception as e:
            return {
                "success": False,
                "status": "error",
                "message": f"Cannot analyze code structure: {e}"
            }

    total_lines = len(code.splitlines())
    return {
        "success": True,
        "status": "success",
        "total_lines": total_lines,
        "message": f"{language.capitalize()} snippet has {total_lines} lines."
    }

