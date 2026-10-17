import re
import os
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from modules.code_generator.config import (
    SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, BLOCKED_KEYWORDS, LANGUAGE_ALIASES
)

def normalize_extension(ext_or_lang: str) -> str:
    """Normalize language or extension into a proper dotted file extension (e.g., '.py', '.cpp')."""
    if not ext_or_lang:
        return ".py"
    raw = ext_or_lang.strip().lower()
    if raw.startswith("."):
        return raw
    # Check if raw is a known alias or language
    canonical = LANGUAGE_ALIASES.get(raw, raw)
    if canonical in SUPPORTED_LANGUAGES:
        return SUPPORTED_LANGUAGES[canonical]
    # Check if raw itself is directly in supported languages
    if raw in SUPPORTED_LANGUAGES:
        return SUPPORTED_LANGUAGES[raw]
    return f".{raw}"

def detect_language(prompt: str) -> str:
    """Detects the target programming language from the prompt using robust boundary matching."""
    text = prompt.lower()

    # Specific compound or symbolic tokens first
    if re.search(r'(?:\bc\+\+(?!\w)|\bcpp\b|\bc\s+plus\s+plus\b)', text):
        return "cpp"
    if re.search(r'(?:\bc\#(?!\w)|\bcsharp\b|\bc\s+sharp\b)', text):
        return "csharp"
    if re.search(r'\b(?:typescript|ts)\b', text):
        return "typescript"
    if re.search(r'\b(?:javascript|js|node|nodejs)\b', text):
        return "javascript"
    if re.search(r'\b(?:powershell|pwsh|ps1)\b', text):
        return "powershell"
    if re.search(r'\b(?:bash|shell\s+script|sh)\b', text) or (re.search(r'\bshell\b', text) and "powershell" not in text):
        return "bash"
    if re.search(r'\b(?:python|py)\b', text):
        return "python"
    if re.search(r'\bjava\b', text) and "javascript" not in text:
        return "java"
    if re.search(r'\b(?:rust|rs)\b', text):
        return "rust"
    if re.search(r'\b(?:golang|go)\b', text) and not re.search(r'\bgo\s+to\b', text):
        return "go"
    if re.search(r'\b(?:kotlin|kt)\b', text):
        return "kotlin"
    if re.search(r'\bswift\b', text):
        return "swift"
    if re.search(r'\bdart\b', text):
        return "dart"
    if re.search(r'\bruby\b', text):
        return "ruby"
    if re.search(r'\bphp\b', text):
        return "php"
    if re.search(r'\bmatlab\b', text):
        return "matlab"
    if re.search(r'\bsql\b', text):
        return "sql"
    if re.search(r'\bhtml\b', text):
        return "html"
    if re.search(r'\bcss\b', text):
        return "css"
    if re.search(r'\bjson\b', text):
        return "json"
    if re.search(r'\b(?:yaml|yml)\b', text):
        return "yaml"
    if re.search(r'\bxml\b', text):
        return "xml"
    if re.search(r'\bmarkdown\b', text):
        return "markdown"
    # Plain 'c' with explicit programming context
    if re.search(r'\b(?:in\s+c\b|c\s+(?:program|code|function|language|file|script))\b', text):
        return "c"
    # R language with explicit programming context
    if re.search(r'\b(?:in\s+r\b|r\s+(?:program|code|function|language|script))\b', text):
        return "r"

    # Platform context default when the request specifically asks for a script
    if re.search(r'\b(?:script|automation\s+script|maintenance\s+script)\b', text):
        return "powershell" if os.name == 'nt' else "bash"

    return DEFAULT_LANGUAGE

def is_web_request(prompt: str) -> bool:
    """Detects if request is for web technologies."""
    t = prompt.lower()
    return any(k in t for k in ["website", "webpage", "web app", "html", "css", "flask", "django", "fastapi", "frontend", "backend"])

def clean_code(code: str) -> str:
    """
    Extracts actual code by removing presentation-only markdown wrappers.
    Preserves all backticks inside code (critical for JS/TS template literals and Bash command substitution).
    """
    if not code:
        return ""
    
    text = code.strip()

    # If code is formatted with multi-file headers (FILE: ...), preserve the full structure
    if re.search(r'(?:^|\n)(?:FILE|=== FILE):\s*[^\n]+', text):
        return text

    # If code has standard markdown fences ```lang\n...```
    m_full = re.search(r'```(?:[\w+\-]+)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m_full:
        return m_full.group(1).strip()

    # If code starts with opening fence but wasn't closed (e.g. truncated output)
    m_open = re.search(r'^```(?:[\w+\-]+)?\s*\n(.*)', text, re.DOTALL)
    if m_open:
        cleaned = m_open.group(1).rstrip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()
        return cleaned

    # Trailing fence only
    if text.endswith("```"):
        text = text[:-3].strip()

    return text

def extract_filename_from_command(command: str) -> str:
    """Extracts a meaningful, clean filename base from the user's command."""
    remove_words = {
        "create", "generate", "write", "make", "build", "a", "an", "the",
        "program", "code", "script", "in", "using", "with", "for", "to",
        "essay", "on", "about", "story", "letter", "notes", "summary", "paragraph",
        "example", "function", "class", "module", "query", "simple",
        # Language names to remove from base name (they become the extension)
        "python", "py", "java", "javascript", "js", "typescript", "ts",
        "c", "cpp", "csharp", "rust", "go", "golang", "powershell", "bash",
        "shell", "ruby", "php", "swift", "kotlin", "dart", "sql", "html", "css", "json"
    }
    # Replace non-alphanumeric with space to separate words
    clean_cmd = re.sub(r'[^a-zA-Z0-9_\s]', ' ', command.lower())
    words = clean_cmd.split()
    filtered = [w for w in words if w not in remove_words and len(w) > 1]
    filename = "_".join(filtered[:5])  # max 5 meaningful words
    return filename if filename else "output"

def get_unique_filepath(folder: str, base_name: str, extension: str) -> str:
    """Returns a unique filepath, appending _1, _2 etc. if file already exists."""
    ext = normalize_extension(extension)
    filepath = os.path.join(folder, f"{base_name}{ext}")
    if not os.path.exists(filepath):
        return filepath
    counter = 1
    while True:
        candidate = os.path.join(folder, f"{base_name}_{counter}{ext}")
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
    downloads = get_downloads_folder()
    os.makedirs(downloads, exist_ok=True)
    filepath = os.path.join(downloads, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)
        if os.path.exists(filepath):
            return filepath
    except Exception as e:
        print(f"[ERROR] File write failed: {e}")
    return ""

def save_file_smart(command: str, content: str, extension: str) -> str:
    """Saves content with a human-readable filename and correct extension derived from the command."""
    downloads_folder = get_downloads_folder()
    os.makedirs(downloads_folder, exist_ok=True)
    base_name = extract_filename_from_command(command)
    ext = normalize_extension(extension)
    filepath = get_unique_filepath(downloads_folder, base_name, ext)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def validate_code_syntax(code: str, language: str = "python") -> dict:
    """
    Validate code syntax without executing it.
    Uses ast.parse for Python, Node.js parser for JS, json/xml/yaml parsers,
    g++ for C++, and delimiter balancing with honest compiler disclosures for other languages.
    """
    import shutil
    import subprocess
    import tempfile
    lang = (language or "python").lower().strip()

    if lang in ("python", "py"):
        import ast
        try:
            ast.parse(code)
            return {
                "valid": True,
                "language": "python",
                "compiler_available": True,
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
            return {"valid": True, "language": "json", "compiler_available": True, "message": "JSON is valid."}
        except json.JSONDecodeError as e:
            return {
                "valid": False,
                "language": "json",
                "line": e.lineno,
                "col": e.colno,
                "error": str(e),
                "message": f"Invalid JSON at line {e.lineno}, col {e.colno}: {e.msg}."
            }

    elif lang in ("xml", "html"):
        import xml.etree.ElementTree as ET
        try:
            ET.fromstring(code)
            return {"valid": True, "language": lang, "compiler_available": True, "message": f"{lang.upper()} markup is well-formed."}
        except ET.ParseError as e:
            if lang == "html":
                # HTML often has self-closing or unclosed void elements; check bracket balance
                pass
            else:
                return {
                    "valid": False,
                    "language": "xml",
                    "error": str(e),
                    "message": f"XML parse error: {e}"
                }

    elif lang in ("yaml", "yml"):
        try:
            import yaml
            yaml.safe_load(code)
            return {"valid": True, "language": "yaml", "compiler_available": True, "message": "YAML syntax is valid."}
        except Exception as e:
            return {
                "valid": False,
                "language": "yaml",
                "error": str(e),
                "message": f"YAML parse error: {e}"
            }

    elif lang in ("javascript", "js"):
        node_bin = shutil.which("node")
        if node_bin:
            try:
                # Use vm.Script to check syntax without executing code
                js_script = "const vm = require('vm'); try { new vm.Script(process.env.CODE_TO_CHECK); console.log('__VALID__'); } catch(e) { console.error(e.message); process.exit(1); }"
                env = os.environ.copy()
                env["CODE_TO_CHECK"] = code
                res = subprocess.run([node_bin, "-e", js_script], env=env, capture_output=True, text=True, timeout=5)
                if res.returncode == 0 and "__VALID__" in res.stdout:
                    return {"valid": True, "language": "javascript", "compiler_available": True, "message": "JavaScript syntax is valid (verified via Node.js)."}
                else:
                    err_msg = res.stderr.strip() or "Syntax error in JavaScript"
                    return {"valid": False, "language": "javascript", "error": err_msg, "message": f"JavaScript syntax error: {err_msg}"}
            except Exception as e:
                pass  # Fallback to delimiter check

    elif lang in ("cpp", "c++", "c"):
        compiler = shutil.which("g++") if lang in ("cpp", "c++") else shutil.which("gcc")
        if compiler:
            suffix = ".cpp" if lang in ("cpp", "c++") else ".c"
            tf = None
            try:
                tf = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w", encoding="utf-8")
                tf.write(code)
                tf.close()
                res = subprocess.run([compiler, "-fsyntax-only", tf.name], capture_output=True, text=True, timeout=5)
                if res.returncode == 0:
                    return {"valid": True, "language": lang, "compiler_available": True, "message": f"{lang.upper()} syntax is valid (verified via {os.path.basename(compiler)})."}
                else:
                    first_err = res.stderr.splitlines()[0] if res.stderr else "Syntax error"
                    return {"valid": False, "language": lang, "error": first_err, "message": f"{lang.upper()} compilation check failed: {first_err}"}
            except Exception:
                pass
            finally:
                if tf and os.path.exists(tf.name):
                    try:
                        os.unlink(tf.name)
                    except Exception:
                        pass

    # Delimiter balancing check for all languages without active toolchain or as fallback
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

    # Honest disclosure: delimiter balanced, but note compiler absence if toolchain not installed
    known_compilers = {
        "java": "javac", "rust": "rustc", "go": "go", "typescript": "tsc",
        "csharp": "dotnet/csc", "swift": "swiftc", "kotlin": "kotlinc"
    }
    comp_tool = known_compilers.get(lang)
    if comp_tool and not shutil.which(comp_tool):
        return {
            "valid": True,
            "language": lang,
            "compiler_available": False,
            "message": f"{language.capitalize()} syntax appears structurally balanced. Note: {comp_tool} is not installed in the environment for full compilation validation."
        }

    return {
        "valid": True,
        "language": lang,
        "compiler_available": bool(shutil.which(comp_tool)) if comp_tool else False,
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


def parse_traceback(error_output: str) -> Dict[str, Any]:
    """
    Parse Python execution traceback or runtime error to extract failing file,
    line number, error type, and message.
    """
    if not error_output:
        return {"has_error": False, "message": "No error output provided."}

    lines = error_output.strip().splitlines()
    failing_file = None
    failing_line = None
    error_line_content = None

    # Scan for standard Python traceback patterns: File "...", line X, in ...
    for line in reversed(lines):
        match = re.search(r'File ["\']([^"\']+)["\'], line (\d+)(?:, in (.+))?', line)
        if match:
            failing_file = match.group(1)
            failing_line = int(match.group(2))
            break

    # Look for the last error type and message (e.g. ValueError: ...)
    last_line = lines[-1].strip() if lines else ""
    err_match = re.match(r'^([A-Za-z_]\w*(?:Error|Exception|Warning|Interrupt)):?\s*(.*)', last_line)
    err_type = err_match.group(1) if err_match else "RuntimeError"
    err_msg = err_match.group(2) if err_match else last_line

    return {
        "has_error": True,
        "file": failing_file,
        "line": failing_line,
        "error_type": err_type,
        "error_message": err_msg,
        "summary": f"{err_type} at {os.path.basename(failing_file) if failing_file else 'unknown'}:{failing_line or '?'}: {err_msg}"
    }


def classify_execution_error(error_output: str) -> Dict[str, Any]:
    """
    Classify common coding execution errors into actionable categories
    (e.g., missing dependency, syntax error, type error, permission, file not found).
    """
    if not error_output:
        return {
            "success": True,
            "status": "success",
            "category": "none",
            "suggestion": "No error.",
            "message": "No traceback error detected."
        }

    text = error_output.lower()

    # Missing module / package
    mod_match = re.search(r"modulenotfounderror: no module named ['\"]([^'\"]+)['\"]", text)
    if mod_match:
        missing_pkg = mod_match.group(1)
        sug = f"Install the missing dependency with: pip install {missing_pkg}"
        return {
            "success": True,
            "status": "success",
            "category": "missing_dependency",
            "package": missing_pkg,
            "suggestion": sug,
            "message": f"Diagnosed missing_dependency: {sug}"
        }

    # Import error
    if "importerror:" in text:
        sug = "Check module name spelling, circular imports, or package version compatibility."
        return {
            "success": True,
            "status": "success",
            "category": "import_error",
            "suggestion": sug,
            "message": f"Diagnosed import_error: {sug}"
        }

    # Syntax error / Indentation error
    if "syntaxerror:" in text or "indentationerror:" in text:
        sug = "Fix syntax or indentation error on the indicated line."
        return {
            "success": True,
            "status": "success",
            "category": "syntax_error",
            "suggestion": sug,
            "message": f"Diagnosed syntax_error: {sug}"
        }

    # Name error
    if "nameerror:" in text:
        name_m = re.search(r"nameerror: name ['\"]([^'\"]+)['\"] is not defined", text)
        var_name = name_m.group(1) if name_m else "unknown"
        sug = f"Variable or function '{var_name}' is referenced before definition or import."
        return {
            "success": True,
            "status": "success",
            "category": "name_error",
            "variable": var_name,
            "suggestion": sug,
            "message": f"Diagnosed name_error: {sug}"
        }

    # File not found
    if "filenotfounderror:" in text or "no such file or directory" in text:
        sug = "Verify file paths and working directory."
        return {
            "success": True,
            "status": "success",
            "category": "file_not_found",
            "suggestion": sug,
            "message": f"Diagnosed file_not_found: {sug}"
        }

    # Permission error
    if "permissionerror:" in text or "access is denied" in text:
        sug = "Run with appropriate user permissions or check file lock status."
        return {
            "success": True,
            "status": "success",
            "category": "permission_denied",
            "suggestion": sug,
            "message": f"Diagnosed permission_denied: {sug}"
        }

    sug = "Review traceback details to identify runtime issue."
    return {
        "success": True,
        "status": "success",
        "category": "general_error",
        "suggestion": sug,
        "message": f"Diagnosed general_error: {sug}"
    }


