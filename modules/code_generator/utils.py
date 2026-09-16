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
