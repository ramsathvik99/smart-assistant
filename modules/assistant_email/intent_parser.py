import os
from .email_ai import generate_with_ai
from dotenv import load_dotenv

# ── CENTRALIZED ENV LOADING ──────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
ENV_PATH = os.path.join(PROJECT_ROOT, "legacy", ".env")
load_dotenv(ENV_PATH)

def clean_command(command):
    try:
        from instance.config import settings as _cfg
        _asst = (_cfg.get_assistant_name() or "").lower()
    except Exception:
        _asst = ""
    fillers = ["please", "hey", "can you", "i want to", "i'd like to"]
    if _asst:
        fillers.extend([_asst, f"hey {_asst}"])
    command = command.lower()
    for filler in fillers:
        command = command.replace(filler, " ")
    return " ".join(command.split())

def is_email_command(command):
    """
    Keyword-based trigger for the email module.
    """
    if not command: return False
    cmd = command.lower()

    keywords = [
        "mail", "email", "send", "inbox",
        "read mail", "check mail", "compose"
    ]

    return any(k in cmd for k in keywords)

def detect_intent(command):
    cleared = clean_command(command)
    prompt = f"Categorize this email command into one of: SEND_EMAIL, CHECK_INBOX, SUMMARIZE_INBOX, READ_EMAIL, REPLY_TO_LATEST, ADD_CONTACT.\nCommand: '{cleared}'\nOutput ONLY the category name."
    
    intent = generate_with_ai(prompt)
    if intent:
        intent = intent.strip().upper()
        valid_intents = ["SEND_EMAIL", "CHECK_INBOX", "SUMMARIZE_INBOX", "READ_EMAIL", "REPLY_TO_LATEST", "ADD_CONTACT"]
        for v in valid_intents:
            if v in intent: return v
            
    # Basic Heuristics if AI fails
    if "send" in cleared or "compose" in cleared: return "SEND_EMAIL"
    if "summarize" in cleared or "summary" in cleared: return "SUMMARIZE_INBOX"
    if "read" in cleared: return "READ_EMAIL"
    if "reply" in cleared: return "REPLY_TO_LATEST"
    if "add" in cleared: return "ADD_CONTACT"
    return "CHECK_INBOX"
