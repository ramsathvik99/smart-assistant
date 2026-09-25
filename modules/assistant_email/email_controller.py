import os
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from .email_memory import resolve_contact, save_contact
from .email_sender import send_email
from .email_ai import generate_email_structure, generate_summary, generate_reply
from .email_reader import fetch_latest_emails, get_latest_email
from .email_ui import get_email_credentials_popup, show_email_editor
from .user_storage import get_user_email, save_user_email
from dotenv import load_dotenv

# ── GLOBAL CONFIG ────────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
ENV_PATH = os.path.join(PROJECT_ROOT, "legacy", ".env")
load_dotenv(ENV_PATH)

def get_current_user() -> str:
    """Dynamically resolve the current authenticated username for isolation."""
    try:
        from instance.config import settings
        uname = getattr(settings, "CURRENT_USERNAME", None)
        if uname:
            return str(uname).lower().strip()
        uid = getattr(settings, "CURRENT_USER_ID", None)
        if uid:
            return f"user_{uid}"
    except Exception:
        pass
    return "default_user"


try:
    from legacy.tts import speak
    from legacy.sst import listen, listen_continuous
except ImportError:
    def speak(t): print(f"ASSISTANT: {t}")
    def listen(): return input("USER: ")
    def listen_continuous(t): return input(f"USER (until stop message): ")

def _audio_available() -> bool:
    """Return True only when PyAudio / microphone hardware is usable."""
    try:
        import speech_recognition as _sr
        _sr.Microphone()
        return True
    except Exception:
        return False

def get_credentials(user: Optional[str] = None):
    """Fetches user credentials from storage or prompts if missing."""
    current_u = user or get_current_user()
    email, password = get_user_email(current_u)
    if not email or not password:
        speak(f"I don't have email credentials saved for {current_u}. Please enter them in the popup.")
        email, password = get_email_credentials_popup()
        if email and password:
            save_user_email(current_u, email, password)
            speak("Credentials saved successfully.")
        else:
            speak("I couldn't get your credentials. I won't be able to send or read emails.")
            return None, None
    return email, password

def listen_for_recipient():
    """
    Patiently listens for a valid recipient name with retries and reminders.
    """
    max_attempts = 3
    timeout_seconds = 6

    for attempt in range(max_attempts):
        if attempt == 0:
            speak("Who do you want to send the email to?")
        
        response = listen(timeout=timeout_seconds)

        if response and len(response.strip()) > 1:
            return response.strip()

        # If no response or invalid input
        if attempt < max_attempts - 1:
            speak("I didn't catch that. Please tell me the recipient name.")
        else:
            speak("No response received. Cancelling email.")
            return None


def search_user_files_for_email(term: str) -> List[str]:
    """Search user accessible locations (Desktop, Downloads, Documents, workspace) for files matching term."""
    clean_term = term.lower().strip(' "\'')
    if not clean_term:
        return []

    search_dirs = []
    try:
        from modules.system_controller.file_manager import get_desktop_path
        search_dirs.append(get_desktop_path())
    except Exception:
        pass

    user_home = Path.home()
    for sub in ["Downloads", "Documents"]:
        p = user_home / sub
        if p.exists():
            search_dirs.append(str(p))

    search_dirs.append(os.getcwd())

    matches = []
    seen = set()

    stop_words = {"the", "a", "an", "my", "file", "document", "sheet", "pdf"}
    keywords = [w for w in clean_term.split() if w not in stop_words and len(w) > 1]
    if not keywords:
        keywords = [clean_term]

    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        try:
            for root, dirs, files in os.walk(sdir):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in {'node_modules', 'venv', '__pycache__', 'appdata'}]
                for f in files:
                    f_low = f.lower()
                    if all(k in f_low for k in keywords):
                        full = os.path.abspath(os.path.join(root, f))
                        if full not in seen:
                            seen.add(full)
                            matches.append(full)
        except Exception:
            continue

    return matches


def resolve_email_attachment_and_recipient(command: str, user_id: Optional[Any] = None) -> Dict[str, Any]:
    """
    Parse email parameters from natural language command.
    Resolves:
      1. Recipient
      2. Attachment:
         - Explicit filename: "Send project_report.pdf to Rahul"
         - Conversational reference: "Send it to Rahul", "Send that file to Rahul"
         - Type reference: "Email the PDF to Rahul", "Send the Excel sheet to Rahul"
         - Fuzzy description: "Send the project report to Rahul" -> exact match or disambiguation prompt
      3. Message body / subject
    """
    cmd_lower = command.lower().strip()

    if not any(k in cmd_lower for k in ["send", "email", "mail", "forward"]):
        return {"is_send_command": False}

    recipient = None
    body = None
    target_description = None

    if " to " in command:
        parts = command.split(" to ", 1)
        target_description = parts[0].strip()
        recipient_part = parts[1].strip()

        body_split = False
        for delim in [" and say ", " saying ", " with message ", " with body ", " say "]:
            if delim in recipient_part:
                r_parts = recipient_part.split(delim, 1)
                recipient = r_parts[0].strip()
                body = r_parts[1].strip()
                body_split = True
                break

        if not body_split:
            recipient = recipient_part.strip()
    else:
        m_rec = re.search(r'\b(?:email|mail|send\s+email\s+to|send\s+mail\s+to)\s+([a-zA-Z0-9_.+-@]+|\w+)', command, re.IGNORECASE)
        if m_rec:
            recipient = m_rec.group(1).strip()

    if not recipient:
        return {"is_send_command": True, "recipient": None}

    recipient = re.sub(r'[.?!,;]+$', '', recipient).strip()

    att_text = target_description or ""
    att_text = re.sub(r'^(?:please\s+)?(?:can\s+you\s+)?(?:send|email|mail|forward)\s+(?:an?\s+)?(?:email\s+with\s+)?', '', att_text, flags=re.IGNORECASE).strip()

    # Case 1: Explicit filename with known extension
    m_file = re.search(r'\b([a-zA-Z0-9_\-.]+\.(?:pdf|docx|xlsx|pptx|txt|csv|png|jpg|jpeg|zip))\b', command, re.IGNORECASE)
    resolved_attachment = None

    if m_file:
        explicit_name = m_file.group(1).strip()
        if os.path.isabs(explicit_name) and os.path.isfile(explicit_name):
            resolved_attachment = explicit_name
        else:
            cands = search_user_files_for_email(explicit_name)
            if cands:
                resolved_attachment = cands[0]
            else:
                return {
                    "is_send_command": True,
                    "success": False,
                    "status": "error",
                    "recipient": recipient,
                    "message": f"I couldn't find {explicit_name}. Please provide the correct filename or location."
                }

    # Case 3, 4: Conversational reference ("it", "that file", "this file", "the document I just created")
    elif re.search(r'\b(?:it|that\s+file|this\s+file|the\s+file|the\s+document\s+i\s+just\s+created)\b', att_text, re.IGNORECASE):
        try:
            from extensions.context_manager import get_manager
            art = get_manager().get_last_user_artifact(user_id=user_id)
            if art and art.get("path") and os.path.isfile(art["path"]):
                resolved_attachment = art["path"]
            else:
                return {
                    "is_send_command": True,
                    "success": False,
                    "status": "error",
                    "recipient": recipient,
                    "message": "No recent file found in conversation context to send."
                }
        except Exception:
            pass

    # Case 5: Type reference ("the pdf", "the excel sheet", "the presentation", "the word doc")
    elif re.search(r'\b(?:the|that)?\s*(pdf|pdf\s+report|excel(?:\s+sheet)?|spreadsheet|presentation|slides|powerpoint|word\s+doc(?:ument)?)\b', att_text, re.IGNORECASE):
        m_type = re.search(r'\b(?:the|that)?\s*(pdf|excel|spreadsheet|presentation|slides|word)\b', att_text, re.IGNORECASE)
        t_str = m_type.group(1).lower() if m_type else ""
        type_code = "pdf" if "pdf" in t_str else ("xlsx" if ("excel" in t_str or "spreadsheet" in t_str) else ("pptx" if ("presentation" in t_str or "slides" in t_str) else "docx"))

        try:
            from extensions.context_manager import get_manager
            mgr = get_manager()
            recent_typed = mgr.get_recent_user_artifacts(user_id=user_id, artifact_type=type_code)
            if len(recent_typed) == 1:
                resolved_attachment = recent_typed[0]["path"]
            elif len(recent_typed) > 1:
                names = [a.get("filename") for a in recent_typed[:4]]
                return {
                    "is_send_command": True,
                    "success": False,
                    "status": "clarification",
                    "needs_clarification": True,
                    "recipient": recipient,
                    "message": f"I found multiple recent {type_code.upper()} files ({', '.join(names)}). Which one should I attach?"
                }
            elif len(recent_typed) == 0:
                cands = search_user_files_for_email(type_code)
                if len(cands) == 1:
                    resolved_attachment = cands[0]
                elif len(cands) > 1:
                    names = [os.path.basename(c) for c in cands[:4]]
                    return {
                        "is_send_command": True,
                        "success": False,
                        "status": "clarification",
                        "needs_clarification": True,
                        "recipient": recipient,
                        "message": f"I found multiple {type_code.upper()} files ({', '.join(names)}). Which one should I attach?"
                    }
        except Exception:
            pass

    # Case 2 & 6: Natural language file description (e.g. "the project report", "the sales report")
    elif any(term in att_text for term in ["report", "presentation", "document", "sheet", "summary", "notes"]):
        cands = search_user_files_for_email(att_text)
        if len(cands) == 1:
            resolved_attachment = cands[0]
        elif len(cands) > 1:
            names = [os.path.basename(c) for c in cands[:5]]
            return {
                "is_send_command": True,
                "success": False,
                "status": "clarification",
                "needs_clarification": True,
                "recipient": recipient,
                "message": f"I found multiple matching files ({', '.join(names)}). Which one should I attach?"
            }
        else:
            return {
                "is_send_command": True,
                "success": False,
                "status": "error",
                "recipient": recipient,
                "message": f"I couldn't find '{att_text}'. Please provide the correct filename or location."
            }

    subject = None
    if resolved_attachment:
        att_base = os.path.basename(resolved_attachment)
        subject = f"Document: {att_base}"
        if not body:
            body = f"Hello,\n\nPlease find attached {att_base}.\n\nBest regards."
    else:
        subject = "Message from Smart Assistant"
        if not body:
            body = "Hello,\n\nPlease find the requested information.\n\nBest regards."

    return {
        "is_send_command": True,
        "success": True,
        "status": "resolved",
        "recipient": recipient,
        "attachment": resolved_attachment,
        "subject": subject,
        "body": body
    }


def handle_email_command(command: str, user_id: Optional[Any] = None) -> Dict[str, Any]:
    cmd_lower = command.lower()

    # 0. Check if this is a read-only inbox / unread query
    is_inbox_query = any(k in cmd_lower for k in [
        "inbox", "unread", "check my email", "check my mail", "check email", "check mail",
        "do i have any", "new emails", "new email", "show email", "show emails", "list email", "list emails",
        "show unread", "list unread"
    ]) or (any(w in cmd_lower for w in ["check", "show", "list", "read", "view"]) and any(e in cmd_lower for e in ["email", "emails", "mail", "inbox"]))
    
    is_send = any(k in cmd_lower for k in ["send", "compose", "forward", "write to", "reply"])
    
    if is_inbox_query and not is_send:
        current_u = (f"user_{user_id}" if user_id and not isinstance(user_id, str) else (user_id if isinstance(user_id, str) and user_id != "default" else None)) or get_current_user()
        return get_emails_overview(limit=5, user=current_u)

    # 1. Check if this is an email send command with resolvable parameters
    if any(k in cmd_lower for k in ["send", "compose", "write", "mail", "email"]):
        res = resolve_email_attachment_and_recipient(command, user_id=user_id)
        if res.get("is_send_command"):
            if res.get("status") in ("error", "clarification"):
                speak(res["message"])
                return res

            if res.get("status") == "resolved" and res.get("recipient"):
                current_u = get_current_user()
                attachments = [res["attachment"]] if res.get("attachment") else None
                send_res = send_email_direct(
                    recipient=res["recipient"],
                    subject=res.get("subject") or "Message from Smart Assistant",
                    body=res.get("body") or "Please find the attached document.",
                    attachments=attachments,
                    user=current_u
                )
                speak(send_res.get("message", "Email processed."))
                return send_res

    # 2. Interactive / Audio Fallback
    email_id, email_pass = get_credentials()
    if not email_id:
        return {"success": False, "status": "error", "message": "Email credentials not configured."}

    initial_recipient = None
    if " to " in command.lower():
        parts = command.lower().split(" to ", 1)
        if len(parts) > 1:
            initial_recipient = parts[1].strip()

    if "send" in cmd_lower or "compose" in cmd_lower or "write" in cmd_lower:
        handle_send_email(initial_recipient, email_id, email_pass)
        return {"success": True, "status": "success", "message": "Handled email send."}
    elif "check" in cmd_lower or "inbox" in cmd_lower or "list" in cmd_lower:
        handle_check_inbox(email_id, email_pass)
        return {"success": True, "status": "success", "message": "Checked inbox."}
    elif "read" in cmd_lower or "open" in cmd_lower:
        handle_read_email(email_id, email_pass)
        return {"success": True, "status": "success", "message": "Read email."}
    elif "summarize" in cmd_lower or "summary" in cmd_lower:
        handle_summarize_inbox(email_id, email_pass)
        return {"success": True, "status": "success", "message": "Summarized inbox."}
    elif "reply" in cmd_lower:
        handle_reply_to_latest(email_id, email_pass)
        return {"success": True, "status": "success", "message": "Handled reply."}
    elif "add" in cmd_lower and "contact" in cmd_lower:
        handle_add_contact()
        return {"success": True, "status": "success", "message": "Added contact."}
    else:
        msg = "I'm not sure what you want to do with email. You can say send email, check inbox, or summarize mail."
        speak(msg)
        return {"success": False, "status": "unknown", "message": msg}


def handle_send_email(initial_recipient, sender_email, sender_pass):
    # STEP 2: RESOLVE RECIPIENT
    if initial_recipient:
        recipient_name = initial_recipient
    else:
        # If no audio hardware available, we cannot ask for recipient interactively
        if not _audio_available():
            speak("Email send requires voice input, but audio hardware is unavailable.")
            return
        recipient_name = listen_for_recipient()
    
    if not recipient_name: return
    
    recipient_email = resolve_contact(recipient_name)
    if not recipient_email:
        speak(f"I don't have an email for {recipient_name}. Please type it in the popup.")
        from .email_utils import get_text_input
        recipient_email = get_text_input("Contact Email", f"Enter email for {recipient_name}:")
        if recipient_email:
            save_contact(recipient_name, recipient_email)
    
    if not recipient_email:
        speak("I couldn't get a valid recipient email.")
        return

    # STEP 3: CAPTURE MESSAGE (VOICE ONLY)
    if not _audio_available():
        speak("Audio hardware unavailable. Cannot capture message voice input.")
        return

    speak("Start speaking your message. Say 'stop message' when done.")
    raw_text = listen_continuous("stop message")
    
    if not raw_text:
        speak("I didn't capture any message.")
        return
    
    # STEP 4: REWRITE MESSAGE PROFESSIONALLY (STRICT)
    speak("Processing and rewriting your message...")
    subject, body = generate_email_structure(raw_text, recipient_name)
    
    # STEP 5: VOICE CONFIRMATION AFTER PROCESSING
    speak("Your email is ready. Do you want to send it, edit it, or cancel?")
    
    while True:
        response = listen().lower()
        print(f"[DEBUG] USER DECISION: {response}")
        
        if "send" in response:
            # Send email directly
            speak("Sending email...")
            if send_email(recipient_email, subject, body, sender_email, sender_pass):
                speak("Email sent successfully.")
            else:
                speak("Failed to send email. Check your connection or credentials.")
            return
            
        elif "edit" in response:
            # Open popup for editing
            speak("Please review and edit the draft in the popup window.")
            edited = show_email_editor(subject, body, recipient_email, sender_email, sender_pass)
            
            if not edited["confirmed"]:
                speak("Email cancelled.")
                return
            
            if edited["sent"]:
                # Email was sent from popup
                return
                
            # Update with edited content and send
            subject = edited["subject"]
            body = edited["body"]
            speak("Sending edited email...")
            if send_email(recipient_email, subject, body, sender_email, sender_pass):
                speak("Email sent successfully.")
            else:
                speak("Failed to send email. Check your connection or credentials.")
            return
            
        elif "cancel" in response or "stop" in response or "abort" in response:
            speak("Email cancelled.")
            return
            
        else:
            speak("Please say send, edit, or cancel.")

def handle_check_inbox(email_id, email_pass):
    speak("Fetching your latest emails...")
    emails = fetch_latest_emails(limit=5, email_id=email_id, email_pass=email_pass)
    if not emails:
        speak("Your inbox is empty or I couldn't access it.")
        return
    
    speak(f"You have {len(emails)} recent emails.")
    for i, e in enumerate(emails):
        speak(f"Email {i+1} is from {e['sender']} regarding {e['subject']}")
    

def handle_summarize_inbox(email_id, email_pass):
    speak("Working on a summary of your latest emails...")
    emails = fetch_latest_emails(limit=10, email_id=email_id, email_pass=email_pass)
    summary = generate_summary(emails)
    speak(summary)

def handle_read_email(email_id, email_pass):
    speak("Which email number should I read?")
    num_text = listen()
    try:
        idx = int(''.join(filter(str.isdigit, num_text))) - 1
        emails = fetch_latest_emails(limit=10, email_id=email_id, email_pass=email_pass)
        if 0 <= idx < len(emails):
            e = emails[idx]
            speak(f"From: {e['sender']}")
            speak(f"Subject: {e['subject']}")
            # Not speaking body as per request to keep it professional/silent review if possible
            # But for reading mail, we must speak it.
            speak("Content:")
            speak(e['body'])
        else:
            speak("I couldn't find that email.")
    except:
        speak("I didn't catch the email number.")

def handle_reply_to_latest(email_id, email_pass):
    speak("Fetching the latest email to reply to...")
    latest = get_latest_email(email_id, email_pass)
    if not latest:
        speak("No emails found to reply to.")
        return
        
    speak(f"Replying to {latest['sender']} regarding {latest['subject']}")
    speak("Generating professional reply...")
    reply_body = generate_reply(f"From: {latest['sender']}\nSubject: {latest['subject']}\nBody: {latest['body']}")
    
    speak("Please review the reply in the popup.")
    edited = show_email_editor(f"Re: {latest['subject']}", reply_body, latest['sender'], email_id, email_pass)
    
    if not edited["confirmed"]:
        speak("Reply cancelled.")
        return
    
    if edited["sent"]:
        # Reply was sent from popup, no need for confirmation
        return
        
    subject = edited["subject"]
    body = edited["body"]

    while True:
        speak("Should I send this reply? Please say yes or no.")
        confirm = listen().lower()
        if "yes" in confirm or "send" in confirm:
            recipient_email = latest['sender']
            if "<" in recipient_email: 
                recipient_email = recipient_email.split("<")[-1].split(">")[0]
            if send_email(recipient_email, subject, body, email_id, email_pass):
                speak("Reply sent successfully.")
            else:
                speak("Failed to send reply.")
            return
        elif "no" in confirm or "cancel" in confirm:
            speak("Reply cancelled.")
            return
        else:
            speak("Please say yes or no.")

def handle_add_contact():
    name = listen_for_recipient()
    if not name: return
    speak(f"Please type the email address for {name} in the popup.")
    from .email_utils import get_text_input
    email_addr = get_text_input("New Contact", f"Email for {name}")
    if email_addr and save_contact(name, email_addr):
        speak(f"Contact {name} added.")
    else:
        speak("Could not save contact.")


def send_email_direct(
    recipient: str,
    subject: str,
    body: str,
    attachments: Optional[list] = None,
    user: Optional[str] = None
) -> dict:
    """
    Non-blocking programmatic email sender for router and background services.
    Validates recipient, checks attachments, and dispatches email via SMTP.
    """
    try:
        current_u = user or get_current_user()
        email_id, email_pass = get_user_email(current_u)
        if not email_id or not email_pass:
            return {
                "success": False,
                "status": "error",
                "message": f"Email credentials not configured for user '{current_u}'. Please configure them in Settings."
            }

        # Resolve contact name to email if needed
        to_addr = recipient.strip()
        if "@" not in to_addr:
            resolved = resolve_contact(to_addr)
            if resolved:
                to_addr = resolved
            else:
                return {
                    "success": False,
                    "status": "error",
                    "message": f"Could not resolve recipient '{recipient}' to an email address."
                }

        # Validate attachments
        valid_attachments = []
        if attachments:
            for att in attachments:
                if os.path.isfile(att):
                    valid_attachments.append(att)
                else:
                    return {
                        "success": False,
                        "status": "error",
                        "message": f"Attachment not found: '{att}'."
                    }

        sent = send_email(to_addr, subject, body, email_id, email_pass, valid_attachments)
        if sent:
            att_msg = f" with {len(valid_attachments)} attachment(s)" if valid_attachments else ""
            return {
                "success": True,
                "status": "success",
                "recipient": to_addr,
                "subject": subject,
                "attachments_count": len(valid_attachments),
                "message": f"Email successfully sent to {to_addr}{att_msg}."
            }
        else:
            return {
                "success": False,
                "status": "error",
                "message": f"Failed to send email to {to_addr}. Please check SMTP credentials."
            }
    except Exception as e:
        return {"success": False, "status": "error", "message": f"Email sending error: {e}"}


def get_emails_overview(limit: int = 5, user: Optional[str] = None) -> dict:
    """
    Non-blocking programmatic reader for latest inbox emails.
    """
    try:
        current_u = user or get_current_user()
        email_id, email_pass = get_user_email(current_u)
        if not email_id or not email_pass:
            return {
                "success": False,
                "status": "error",
                "emails": [],
                "message": f"Email credentials not configured for user '{current_u}'."
            }

        emails = fetch_latest_emails(limit=limit, email_id=email_id, email_pass=email_pass)
        if not emails:
            return {
                "success": True,
                "status": "success",
                "emails": [],
                "message": "No new emails found in inbox."
            }

        summaries = [f"From {e.get('sender')}: '{e.get('subject')}'" for e in emails[:3]]
        speech_text = f"You have {len(emails)} recent email(s). " + "; ".join(summaries) + "."

        return {
            "success": True,
            "status": "success",
            "count": len(emails),
            "emails": emails,
            "message": speech_text
        }
    except Exception as e:
        return {"success": False, "status": "error", "emails": [], "message": f"Failed to fetch emails: {e}"}


class EmailController:
    """Wrapper class for programmatic access to assistant email capabilities."""
    send_email_direct = staticmethod(send_email_direct)
    get_emails_overview = staticmethod(get_emails_overview)
    handle_email_command = staticmethod(handle_email_command)

email_controller = EmailController()

