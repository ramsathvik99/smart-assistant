# config.py
import os

SUPPORTED_LANGUAGES = {
    "python": ".py",
    "java": ".java",
    "cpp": ".cpp",
    "c": ".c",
    "javascript": ".js"
}

DEFAULT_LANGUAGE = "python"

BLOCKED_KEYWORDS = [
    "flask", "django", "api", "react", "html", "css",
    "backend", "frontend", "server", "web", "website"
]

GENERATED_CODE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "generated_code"
)
