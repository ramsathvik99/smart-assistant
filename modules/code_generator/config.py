# config.py
import os

SUPPORTED_LANGUAGES = {
    "python": ".py",
    "java": ".java",
    "javascript": ".js",
    "typescript": ".ts",
    "c": ".c",
    "cpp": ".cpp",
    "csharp": ".cs",
    "go": ".go",
    "rust": ".rs",
    "php": ".php",
    "ruby": ".rb",
    "swift": ".swift",
    "kotlin": ".kt",
    "dart": ".dart",
    "r": ".r",
    "matlab": ".m",
    "sql": ".sql",
    "bash": ".sh",
    "powershell": ".ps1",
    "html": ".html",
    "css": ".css",
    "json": ".json",
    "yaml": ".yaml",
    "xml": ".xml",
    "markdown": ".md"
}

LANGUAGE_ALIASES = {
    "py": "python",
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "ts": "typescript",
    "c++": "cpp",
    "c plus plus": "cpp",
    "c#": "csharp",
    "c sharp": "csharp",
    "cs": "csharp",
    "sh": "bash",
    "shell": "bash",
    "shell script": "bash",
    "pwsh": "powershell",
    "ps": "powershell",
    "ps1": "powershell",
    "golang": "go",
    "rs": "rust",
    "kt": "kotlin",
    "rb": "ruby",
    "yml": "yaml",
    "htm": "html"
}

DEFAULT_LANGUAGE = "python"

BLOCKED_KEYWORDS = []

try:
    from core.semantic_file_naming import get_semantic_file_naming_service
    GENERATED_CODE_DIR = get_semantic_file_naming_service().get_default_output_dir()
except Exception:
    GENERATED_CODE_DIR = os.path.join(os.path.expanduser("~"), "Desktop")
    os.makedirs(GENERATED_CODE_DIR, exist_ok=True)
