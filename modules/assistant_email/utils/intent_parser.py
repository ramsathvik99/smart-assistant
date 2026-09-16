import sys
import os

try:
    from email_ai import get_client
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from email_ai import get_client

def clean_command(command):
    if not command:
        return ""
    command = command.lower().strip()
    
    # Remove politeness and filler words
    try:
        from instance.config import settings as _cfg
        _asst = (_cfg.get_assistant_name() or "").lower()
    except Exception:
        _asst = ""
    fillers = [
        "please", "can you", "could you", "i want to", "i need to", 
        "would you", "uh", "um", "do i have",
        "can i", "let me", "help me"
    ]
    if _asst:
        fillers.extend([f"hey {_asst}", _asst])
    
    for filler in fillers:
        command = command.replace(filler, " ")
        
    return " ".join(command.split())

def detect_intent(command):
    cleaned = clean_command(command)
    
    # Try AI classification first
    client = get_client()
    if client:
        try:
            prompt = f"Classify the intent of the following command into exactly ONE of these categories: SEND_EMAIL, READ_EMAIL, CHECK_INBOX, SUMMARIZE_EMAIL, REPLY_EMAIL, ADD_CONTACT, UNKNOWN. Command: '{command}'. Return ONLY the category name."
            response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            if response and response.text:
                intent = response.text.strip().upper()
                if intent in ["SEND_EMAIL", "READ_EMAIL", "CHECK_INBOX", "SUMMARIZE_EMAIL", "REPLY_EMAIL", "ADD_CONTACT"]:
                    return intent
        except Exception:
            pass # Fallback to logic matching

    # Keyword lists for overlapping contexts
    send_keywords = ["send", "compose", "write"]
    mail_keywords = ["mail", "email", "message"]
    
    # 1. Reply
    if any(w in cleaned for w in ["reply", "respond", "answer"]):
        return "REPLY_EMAIL"
        
    # 2. Summarize
    if any(w in cleaned for w in ["summary", "summarize", "summarise", "recap"]):
        return "SUMMARIZE_EMAIL"
        
    # 3. Add Contact
    if "contact" in cleaned and any(w in cleaned for w in ["add", "new", "save"]):
        return "ADD_CONTACT"
        
    # 4. Read Latest
    if any(w in cleaned for w in ["read", "open", "show"]) and any(w in cleaned for w in ["latest", "last", "recent", "newest"]):
        return "READ_EMAIL"
        
    # 5. Check Inbox
    if any(w in cleaned for w in ["check", "inbox"]):
        return "CHECK_INBOX"
    if "any new" in cleaned or "new emails" in cleaned or "new mails" in cleaned:
        return "CHECK_INBOX"
    if any(w in cleaned for w in ["read", "get", "show"]) and ("emails" in cleaned or "mails" in cleaned or "inbox" in cleaned):
        return "CHECK_INBOX"
        
    # 6. Send Email
    if any(w in cleaned for w in send_keywords) and any(w in cleaned for w in mail_keywords):
        return "SEND_EMAIL"
    if "mail someone" in cleaned or "email someone" in cleaned:
        return "SEND_EMAIL"
        
    # Bare minimum heuristics if someone just says "send" or "compose"
    if any(w in cleaned for w in ["send", "compose", "mail", "email"]):
        if "read" not in cleaned and "check" not in cleaned and "reply" not in cleaned:
            return "SEND_EMAIL"
            
    return "UNKNOWN"
