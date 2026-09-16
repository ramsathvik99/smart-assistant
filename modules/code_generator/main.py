import os
import re
import subprocess
from datetime import datetime

# 🧠 STEP 1: DETECT MULTI-FILE PROJECT
def is_multi_file_request(command):
    keywords = ["website", "web app", "frontend", "backend", "project"]
    return any(k in command.lower() for k in keywords)

# 🧠 STEP 2: EXTRACT MULTIPLE FILES FROM LLM
def extract_files(response):
    pattern = r"FILE:\s*(.*?)\n```(\w+)?\n(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)

    files = []
    for filename, lang, code in matches:
        files.append((filename.strip(), code.strip()))

    return files

# 🧠 STEP 3: EXTRACT SINGLE CODE BLOCK & LANGUAGE
def extract_code_and_lang(text):
    match = re.search(r"```(\w+)?\n(.*?)```", text, re.DOTALL)
    
    if match:
        lang = match.group(1)
        code = match.group(2).strip()
        
        if not lang:
            lang = "python"  # fallback
        
        return code, lang.lower()
    
    return None, None

# 🧠 STEP 4: DYNAMIC EXTENSION MAPPING
def get_extension(lang):
    ext_map = {
        "python": "py",
        "javascript": "js",
        "typescript": "ts",
        "html": "html",
        "css": "css",
        "java": "java",
        "cpp": "cpp",
        "c": "c",
        "go": "go",
        "rust": "rs",
        "php": "php",
        "swift": "swift",
        "kotlin": "kt"
    }
    
    return ext_map.get(lang, lang)  # fallback = same as lang

# 🧠 STEP 5: SAVE PROJECT
DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")

def save_project(files):
    folder_name = f"assistant_project_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    project_path = os.path.join(DOWNLOADS, folder_name)

    os.makedirs(project_path, exist_ok=True)

    for filename, code in files:
        file_path = os.path.join(project_path, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)

    return project_path

# 🧠 STEP 6: SAVE SINGLE FILE
def save_single_file(code, extension):
    folder = os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(folder, exist_ok=True)

    filename = f"assistant_code_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{extension}"
    path = os.path.join(folder, filename)

    with open(path, "w", encoding="utf-8") as f:
        f.write(code)

    return path

# 🧠 STEP 7: OPEN IN VS CODE
def open_in_vscode(path):
    try:
        subprocess.Popen(["code", path], shell=True)
        return True
    except Exception as e:
        print(f"[ERROR] VS Code open failed: {e}")
        return False

# 🧠 STEP 8: MAIN PROCESS REQUEST FUNCTION
def process_request(command: str):
    """Main entry point for code generation requests."""
    from .generator import generate_code
    from .utils import detect_language, save_file_smart
    
    print(f"[Code Generator] Processing request: {command}")
    
    # Detect language from command
    language = detect_language(command)
    print(f"[Code Generator] Detected language: {language}")
    
    # Generate code
    code = generate_code(command, language)
    
    if not code or "Sorry, I could not generate code" in code:
        print(f"[Code Generator] Code generation failed.")
        return {
            "status": "error",
            "message": "Failed to generate code",
            "code": None,
            "file_path": None
        }
    
    print(f"[Code Generator] Code generated successfully")
    
    # Save code to file
    try:
        file_path = save_file_smart(command, code, language)
        print(f"[Code Generator] Code saved to: {file_path}")
        
        # Try to open in VS Code
        try:
            open_in_vscode(file_path)
        except Exception as vscode_err:
            print(f"[Code Generator] VS Code launch failed (non-critical): {vscode_err}")
        
        return {
            "status": "success",
            "message": f"Generated {language} code and saved to {file_path}",
            "code": code,
            "file_path": file_path
        }
    except Exception as e:
        print(f"[Code Generator] Error saving file: {e}")
        return {
            "status": "success",
            "message": f"Generated {language} code (could not save file)",
            "code": code,
            "file_path": None
        }
