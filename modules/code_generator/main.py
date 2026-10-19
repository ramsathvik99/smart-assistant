import os
import re
import shutil
import subprocess
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any

from .config import GENERATED_CODE_DIR
from .generator import generate_code, generate_multi_file_project
from .utils import (
    detect_language,
    save_file_smart,
    validate_code_syntax,
    validate_generated_artifact_requirements,
    extract_filename_from_command,
    normalize_extension,
    clean_code
)


# 🧠 STEP 1: DETECT MULTI-FILE PROJECT
def is_multi_file_request(command: str) -> bool:
    """Detect whether a command requests a multi-file project or application."""
    if not command or not isinstance(command, str):
        return False
    command_low = command.lower()
    keywords = [
        "website", "web app", "webapp", "frontend", "backend", "fullstack", "full stack",
        "multi-file", "multi file", "project", "separate html", "separate files",
        "html, css", "html and css", "flask api", "fastapi api", "django",
        "routes, dependencies", "multi-module", "multi module", "codebase",
        "webpage with separate", "with separate html"
    ]
    return any(k in command_low for k in keywords)


# 🧠 STEP 2: EXTRACT MULTIPLE FILES FROM LLM RESPONSE
def extract_files(response: str) -> List[Tuple[str, str]]:
    """
    Extracts multiple files from a structured response formatted as:
    FILE: relative/path/to/filename.ext
    ```language
    ...code...
    ```
    Resilient to markdown headers (###), bolding (**), backticks around filenames, and interstitial blank lines.
    """
    if not response or not isinstance(response, str):
        return []

    marker_pattern = r"(?:^|\n)[#*\s]*(?:FILE|File|PATH|Path):\s*[`*]*([^\r\n`*]+)[`*]*\s*(?:\r?\n[^\n`]*)*?\r?\n```(?:\w+)?\r?\n(.*?)(?:```|$)"
    matches = re.findall(marker_pattern, response, re.DOTALL)

    files = []
    for raw_filename, raw_code in matches:
        filename = raw_filename.strip().replace("\\", "/").strip("/ `*")
        if filename and not filename.startswith("..") and "." in filename:
            files.append((filename, raw_code.strip()))

    return files


# 🧠 STEP 3: EXTRACT SINGLE CODE BLOCK & LANGUAGE
def extract_code_and_lang(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extracts the first code block and its language tag from Markdown text."""
    if not text or not isinstance(text, str):
        return None, None

    match = re.search(r"```(\w+)?\r?\n(.*?)```", text, re.DOTALL)
    if match:
        lang = match.group(1)
        code = match.group(2).strip()
        if not lang:
            lang = "python"
        return code, lang.lower().strip()

    return None, None


# 🧠 STEP 4: DYNAMIC EXTENSION MAPPING
def get_extension(lang: str) -> str:
    """Normalize language into standard file extension."""
    ext = normalize_extension(lang)
    return ext.lstrip(".")


# 🧠 STEP 5: SAVE MULTI-FILE PROJECT SAFELY
def save_project(files: List[Tuple[str, str]], base_name: Optional[str] = None, output_dir: Optional[str] = None) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Safely creates a project directory in GENERATED_CODE_DIR (or custom output_dir) and writes files.
    Enforces strict path traversal rejection using commonpath.
    """
    if output_dir:
        project_path = os.path.abspath(output_dir)
    else:
        from core.semantic_file_naming import get_semantic_file_naming_service
        namer = get_semantic_file_naming_service()
        project_path = namer.derive_project_directory(command=base_name or "assistant_project", parent_dir=GENERATED_CODE_DIR)
    os.makedirs(project_path, exist_ok=True)

    saved_files = []
    for rel_path, code in files:
        # Standardize separators and remove leading slashes/drives
        clean_rel = rel_path.lstrip("/\\").replace('/', os.sep).replace('\\', os.sep)
        target_path = os.path.abspath(os.path.join(project_path, clean_rel))

        # Enforce that target_path is strictly inside project_path
        if os.path.commonpath([project_path, target_path]) != project_path:
            print(f"[SECURITY] Path traversal blocked for: {rel_path}")
            continue

        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(code)
        saved_files.append((rel_path, target_path))

    return project_path, saved_files


# 🧠 STEP 6: SAVE SINGLE FILE
def save_single_file(code: str, extension: str, command: str = "assistant_code") -> str:
    """Saves a single code file using save_file_smart."""
    return save_file_smart(command, code, extension)


# 🧠 STEP 7: OPEN IN VS CODE HONESTLY
def open_in_vscode(path: str) -> bool:
    """
    Attempts to open a file or folder in VS Code.
    Returns True ONLY if VS Code executable is present and launched cleanly.
    """
    code_bin = shutil.which("code") or shutil.which("code.cmd")
    if not code_bin:
        # VS Code is not installed or not in PATH
        return False

    try:
        subprocess.Popen([code_bin, path], shell=False)
        return True
    except Exception as e:
        print(f"[VS Code Notice] Launch error: {e}")
        return False


# 🧠 STEP 8: MAIN PROCESS REQUEST FUNCTION
def process_request(command: str, user_id: Optional[Any] = None) -> Dict[str, Any]:
    """
    Main entry point for code generation requests.
    Handles both multi-file projects and single-file programs/snippets.
    """
    print(f"[Code Generator] Processing request: {command}")

    # 1. Multi-file project request
    if is_multi_file_request(command):
        print(f"[Code Generator] Multi-file project request detected.")
        raw_response = generate_multi_file_project(command, user_id=user_id)

        if not raw_response or "sorry, i could not generate" in raw_response.lower():
            return {
                "status": "error",
                "message": "Failed to generate multi-file project.",
                "code": None,
                "file_path": None,
                "project_path": None,
                "files": []
            }

        extracted = extract_files(raw_response)

        if extracted:
            base_name = extract_filename_from_command(command)
            project_path, saved_files = save_project(extracted, base_name=base_name)
            file_names = [f[0] for f in saved_files]

            # Run syntax checks on any Python/JS files in the generated set
            validation_summaries = []
            for rel, abs_p in saved_files:
                if rel.endswith(".py"):
                    try:
                        with open(abs_p, "r", encoding="utf-8") as f_in:
                            val = validate_code_syntax(f_in.read(), language="python")
                            if not val.get("valid"):
                                validation_summaries.append(f"{rel}: {val.get('message')}")
                    except Exception:
                        pass

            # Construct preview of files
            preview_lines = [f"Project: {os.path.basename(project_path)}", f"Location: {project_path}\n", "Files Generated:"]
            for f in file_names:
                preview_lines.append(f"  • {f}")
            if validation_summaries:
                preview_lines.append(f"\nValidation Notices:\n  • " + "\n  • ".join(validation_summaries))
            code_preview = "\n".join(preview_lines)

            # Try to open in editor
            opened = open_in_vscode(project_path)

            return {
                "status": "success",
                "message": f"Generated {len(file_names)}-file project at {project_path}.",
                "code": code_preview,
                "file_path": project_path,
                "project_path": project_path,
                "files": file_names,
                "opened_in_editor": opened,
                "is_project": True
            }

        # Fallback: if model failed to use FILE: markers, check for standard code block
        code, lang = extract_code_and_lang(raw_response)
        if code:
            language = lang or detect_language(command)
            file_path = save_file_smart(command, code, language)
            val_res = validate_code_syntax(code, language=language)
            open_in_vscode(file_path)
            return {
                "status": "success",
                "message": f"Generated {language} code and saved to {file_path}.",
                "code": code,
                "file_path": file_path,
                "language": language,
                "validation": val_res,
                "is_project": False
            }

    # 2. Single-file program / snippet request
    language = detect_language(command)
    print(f"[Code Generator] Detected language: {language}")

    code = generate_code(command, language=language, user_id=user_id)

    if not code or "sorry, i could not generate code" in code.lower():
        print(f"[Code Generator] Code generation failed.")
        return {
            "status": "error",
            "message": "Failed to generate code.",
            "code": None,
            "file_path": None,
            "language": language
        }

    print(f"[Code Generator] Code generated successfully ({len(code)} characters).")

    # Save code to file with honest validation and bounded repair
    try:
        val_res = validate_code_syntax(code, language=language)
        req_res = validate_generated_artifact_requirements(code, command)

        # 1. Bounded repair succeeded
        if val_res.get("repaired"):
            final_code = val_res.get("repaired_code", code)
            file_path = save_file_smart(command, final_code, language)
            orig_path = save_file_smart(command + "_original_unrepaired", code, language)
            print(f"[Code Generator] Code repaired and saved to: {file_path} (original preserved at {orig_path})")
            opened = open_in_vscode(file_path)
            req_res = validate_generated_artifact_requirements(final_code, command)
            return {
                "status": "success",
                "message": f"Generated and validated {language} code saved to {file_path}. ({val_res.get('message', '')})",
                "code": final_code,
                "file_path": file_path,
                "language": language,
                "validation": val_res,
                "requirements": req_res,
                "artifact_state": {
                    "generated": True,
                    "saved": True,
                    "syntax_checked": bool(val_res.get("valid")),
                    "compiled": bool(val_res.get("compiled", False)),
                    "executed": False,
                    "missing_tools": val_res.get("missing_tools", []),
                    "requirements_satisfied": req_res.get("satisfied", True),
                    "missing_requirements": req_res.get("missing_requirements", [])
                },
                "opened_in_editor": opened,
                "is_project": False
            }

        # 2. Validation failed and could not be repaired
        if not val_res.get("valid"):
            invalid_path = save_file_smart(command + "_invalid", code, language)
            print(f"[Code Generator] Validation failed. Preserved invalid artifact at: {invalid_path}")
            return {
                "status": "error",
                "message": f"Generated {language} code failed syntax validation: {val_res.get('message')}. Artifact preserved for diagnosis at {invalid_path}.",
                "code": code,
                "file_path": invalid_path,
                "language": language,
                "validation": val_res,
                "requirements": req_res,
                "artifact_state": {
                    "generated": True,
                    "saved": True,
                    "syntax_checked": False,
                    "compiled": False,
                    "executed": False,
                    "missing_tools": val_res.get("missing_tools", []),
                    "requirements_satisfied": req_res.get("satisfied", True),
                    "missing_requirements": req_res.get("missing_requirements", [])
                },
                "is_project": False
            }

        # 3. Code is fully valid
        file_path = save_file_smart(command, code, language)
        print(f"[Code Generator] Code saved to: {file_path}")
        opened = open_in_vscode(file_path)

        return {
            "status": "success",
            "message": f"Generated {language} code and saved to {file_path}. {val_res.get('message', '')}",
            "code": code,
            "file_path": file_path,
            "language": language,
            "validation": val_res,
            "requirements": req_res,
            "artifact_state": {
                "generated": True,
                "saved": True,
                "syntax_checked": True,
                "compiled": bool(val_res.get("compiled", False)),
                "executed": False,
                "missing_tools": val_res.get("missing_tools", []),
                "requirements_satisfied": req_res.get("satisfied", True),
                "missing_requirements": req_res.get("missing_requirements", [])
            },
            "opened_in_editor": opened,
            "is_project": False
        }
    except Exception as e:
        print(f"[Code Generator] Error saving file: {e}")
        return {
            "status": "error",
            "message": f"Generated {language} code but failed saving file: {e}.",
            "code": code,
            "file_path": None,
            "language": language,
            "is_project": False
        }
