"""
email_controller.py — Upgraded email command handler.

Production path:
  user_input → intent (EMAIL) → handle_email_command()
             → _parse_email_intent()  (sub-action + entities)
             → specialized handler    (read / count / search / compose / reply / forward / organize)
             → review/confirm popup   (mandatory for all outbound)
             → send_email()
             → verified result dict

Architecture rules preserved:
  - No rewrite of UnifiedCommandRouter, GoalPlanner, or DialogueStateManager.
  - No new authentication system; existing user_storage / security are reused.
  - No hardcoded addresses, no sensitive data in logs.
  - All outbound operations require user confirmation.
"""
import os
import re
import time
import datetime
import email.utils
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from .email_memory import (
    resolve_contact, resolve_recipient_detailed, save_contact,
    search_contacts, is_placeholder_email, is_valid_email
)
from .email_sender import send_email
from .email_ai import (
    generate_email_structure, generate_summary, generate_reply,
    edit_email_draft, extract_action_items, explain_email_simple, rewrite_professional
)
from .email_reader import (
    fetch_latest_emails, fetch_latest_emails_with_status,
    get_latest_email, count_unread_emails, organize_email_message, invalidate_cache,
    list_mailboxes, find_folder_by_role, move_email_message
)
from .email_ui import get_email_credentials_popup, show_email_editor
from .user_storage import (
    get_user_email, save_user_email,
    save_draft, list_drafts, get_draft, delete_draft
)

# ── TTS / STT shims (preserved exactly from original) ────────────
try:
    from legacy.tts import speak
    from legacy.sst import listen, listen_continuous
except ImportError:
    def speak(t): print(f"ASSISTANT: {t}")  # noqa
    def listen(*args, **kwargs): return input("USER: ")  # noqa
    def listen_continuous(t): return input(f"USER (until stop message): ")  # noqa


def _parse_nl_date(date_str: str) -> Optional[datetime.date]:
    """Parses date strings into a datetime.date object."""
    if not date_str:
        return None
    cleaned = date_str.strip().lower()
    if cleaned in ("today", "now"):
        return datetime.date.today()
    if cleaned == "yesterday":
        return datetime.date.today() - datetime.timedelta(days=1)

    for fmt in (
        "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y",
        "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
        "%d %B %Y", "%d %b %Y", "%Y/%m/%d", "%d-%b-%Y"
    ):
        try:
            norm = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_str.strip())
            return datetime.datetime.strptime(norm, fmt).date()
        except Exception:
            continue

    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        if dt:
            return dt.date()
    except Exception:
        pass

    return None



# ──────────────────────────────────────────────────────────────────
# Resolved user identity
# ──────────────────────────────────────────────────────────────────

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


def _resolve_user(user_id: Any) -> str:
    """Convert any user_id form to a consistent user key, mapping numeric ID to username if known."""
    if user_id is None:
        cur = get_current_user()
        if cur and cur != "default_user":
            return cur
        if len(_pending_email_sessions) == 1:
            return next(iter(_pending_email_sessions.keys()))
        return "default_user"
    if isinstance(user_id, int) or (isinstance(user_id, str) and user_id.isdigit()):
        uid_num = int(user_id)
        try:
            from instance.config import settings
            if getattr(settings, "CURRENT_USER_ID", None) == uid_num:
                uname = getattr(settings, "CURRENT_USERNAME", None)
                if uname:
                    return str(uname).lower().strip()
        except Exception:
            pass
        try:
            from legacy.memory_manager import get_username_by_id
            uname_db = get_username_by_id(uid_num)
            if uname_db:
                return str(uname_db).lower().strip()
        except Exception:
            pass
        return f"user_{uid_num}"
    s = str(user_id).strip().lower()
    return s or get_current_user()


def _audio_available() -> bool:
    """Return True only when audio hardware is accessible."""
    try:
        import speech_recognition as _sr
        _sr.Microphone()
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────
# Active in-flight / pending email draft state (cross-turn voice/UI)
# ──────────────────────────────────────────────────────────────────

_pending_email_sessions: Dict[str, Dict[str, Any]] = {}

def get_pending_email(user: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve the active pending draft for a given user."""
    u = _resolve_user(user)
    return _pending_email_sessions.get(u)

def clear_pending_email(user: Optional[str] = None) -> None:
    """Clear any active pending draft for a given user."""
    u = _resolve_user(user)
    _pending_email_sessions.pop(u, None)


# ── Email State Machine Constants ─────────────────────────────────
STATE_IDLE = "IDLE"
STATE_EMAIL_RECIPIENT_RESOLUTION = "EMAIL_RECIPIENT_RESOLUTION"
STATE_RECORDING_EMAIL_MESSAGE = "RECORDING_EMAIL_MESSAGE"
STATE_PROCESSING_EMAIL_MESSAGE = "PROCESSING_EMAIL_MESSAGE"
STATE_PENDING_EMAIL_CONFIRMATION = "PENDING_EMAIL_CONFIRMATION"
STATE_SENDING_EMAIL = "SENDING_EMAIL"
STATE_EMAIL_SENT = "EMAIL_SENT"
STATE_EMAIL_SEND_FAILED = "EMAIL_SEND_FAILED"
STATE_EMAIL_AMBIGUOUS_OUTCOME = "EMAIL_SEND_AMBIGUOUS"
STATE_EMAIL_PARTIAL_DELIVERY = "EMAIL_PARTIAL_DELIVERY"
STATE_UNVERIFIED_RECIPIENT = "UNVERIFIED_RECIPIENT"


def is_in_email_dictation(user: Optional[Any] = None) -> bool:
    """Check if the given user is currently in the dedicated RECORDING_EMAIL_MESSAGE state."""
    u = _resolve_user(user)
    session = _pending_email_sessions.get(u)
    if not session and user is None and len(_pending_email_sessions) == 1:
        session = next(iter(_pending_email_sessions.values()))
    return bool(session and session.get("status") == STATE_RECORDING_EMAIL_MESSAGE)


def is_active_email_session(user: Optional[Any] = None) -> bool:
    """Check if the given user has any active in-flight email state."""
    u = _resolve_user(user)
    session = _pending_email_sessions.get(u)
    if not session and user is None and len(_pending_email_sessions) == 1:
        session = next(iter(_pending_email_sessions.values()))
    if not session:
        return False
    status = session.get("status")
    return status in (
        STATE_RECORDING_EMAIL_MESSAGE,
        STATE_PROCESSING_EMAIL_MESSAGE,
        STATE_PENDING_EMAIL_CONFIRMATION,
        STATE_EMAIL_RECIPIENT_RESOLUTION,
        STATE_EMAIL_SEND_FAILED,
        STATE_SENDING_EMAIL,
        STATE_EMAIL_AMBIGUOUS_OUTCOME,
        STATE_EMAIL_PARTIAL_DELIVERY,
        STATE_UNVERIFIED_RECIPIENT,
        "PENDING_CONFIRMATION",
        "NEED_PURPOSE"
    )


def get_email_session_state(user: Optional[Any] = None) -> str:
    """Retrieve current state machine status for a user, or IDLE."""
    u = _resolve_user(user)
    session = _pending_email_sessions.get(u)
    return session.get("status", STATE_IDLE) if session else STATE_IDLE

def _format_spoken_error(send_res_or_msg: Any, context: str = "send", draft_retained: bool = True) -> str:
    """
    Format a concise, human-friendly spoken response for TTS.
    Diagnostic logs preserve the full technical exception, but voice output
    must remain calm, concise, and non-technical.
    """
    raw_status = ""
    raw_msg = ""
    if isinstance(send_res_or_msg, dict):
        raw_status = str(send_res_or_msg.get("status", "")).lower()
        raw_msg = str(send_res_or_msg.get("message", "")).lower()
    else:
        raw_msg = str(send_res_or_msg).lower()

    tail = " Your draft is still available." if draft_retained else ""

    if "auth" in raw_status or "auth" in raw_msg or "password" in raw_msg or "credentials" in raw_msg:
        return f"I couldn't authenticate with your mail server. Please check your email credentials.{tail}"
    if "network" in raw_status or "network" in raw_msg or "connect" in raw_msg or "closed" in raw_msg or "timeout" in raw_msg:
        return f"I couldn't connect to your mail server.{tail}"
    if "recipient" in raw_status or "recipient" in raw_msg or "address" in raw_msg:
        return f"The mail server rejected the recipient address.{tail}"
    return f"I couldn't {context} the email.{tail}"


import threading

_in_flight_sends: set = set()
_send_state_lock = threading.Lock()

def _dispatch_pending_email(user: str, email_id: Optional[str], email_pass: Optional[str], override_draft: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Atomically reserve a user's send slot and hold it through result processing."""
    with _send_state_lock:
        if user in _in_flight_sends:
            return {"success": False, "status": "in_progress", "message": "Email is already being sent. Please wait."}
        _in_flight_sends.add(user)
    try:
        return _dispatch_pending_email_impl(user, email_id, email_pass, override_draft)
    finally:
        with _send_state_lock:
            _in_flight_sends.discard(user)


def _dispatch_pending_email_impl(user: str, email_id: Optional[str], email_pass: Optional[str], override_draft: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Dispatch the active pending email draft while preserving it on any non-success outcome."""
    pending = override_draft or _pending_email_sessions.get(user)
    if not pending or not pending.get("recipient"):
        return {"success": False, "status": "no_pending_email", "message": "No pending email to send."}

    if pending.get("status") == STATE_EMAIL_SENT:
        return {"success": False, "status": "already_sent", "message": "This email has already been sent."}

    to_addr = pending["recipient"]
    # Check for placeholder recipient before sending
    if is_placeholder_email(to_addr):
        pending["status"] = STATE_UNVERIFIED_RECIPIENT
        _pending_email_sessions[user] = pending
        msg = f"Cannot send email to placeholder address '{to_addr}'. Please specify a verified email address."
        speak(msg)
        return {"success": False, "status": "unverified_recipient", "message": msg, "draft": pending}

    if not email_id or not email_pass:
        return _no_creds_error(user)

    subject = pending.get("subject", "(No Subject)")
    body = pending.get("body", "")
    attachments = pending.get("attachments", [])
    cc = pending.get("cc") or None
    bcc = pending.get("bcc") or None

    # The public wrapper owns the in-flight reservation for the full lifecycle.
    pending["status"] = STATE_SENDING_EMAIL
    pending["send_attempt"] = pending.get("send_attempt", 0) + 1
    send_attempt_id = str(uuid.uuid4())
    pending["last_send_attempt_id"] = send_attempt_id
    _pending_email_sessions[user] = pending

    send_res = None
    try:
        send_res = send_email(
            to_email=to_addr,
            subject=subject,
            body=body,
            email_id=email_id,
            email_pass=email_pass,
            attachments=attachments,
            cc=cc,
            bcc=bcc
        )
    except Exception as exc:
        # The sender raised without proving whether transmission began. Treat this
        # as ambiguous: preserve the draft but never offer an automatic blind retry.
        pending["status"] = STATE_EMAIL_AMBIGUOUS_OUTCOME
        pending["last_error"] = f"Unclassified send exception: {type(exc).__name__}: {exc}"
        pending["send_outcome_ambiguous"] = True
        _pending_email_sessions[user] = pending
        err_msg = (
            "The send outcome could not be confirmed. Your draft is preserved. "
            "Check your Sent folder before deciding whether to retry."
        )
        try:
            speak("I couldn't confirm whether the email was sent. Your draft is saved. Please check Sent before retrying.")
        except Exception:
            pass
        return {
            "success": False,
            "status": "ambiguous_outcome",
            "message": err_msg,
            "draft": pending,
            "retry_safe": False
        }

    # Check for ambiguous send result. The wrapper keeps this user reserved until
    # success/failure state is persisted and the response has been prepared.
    res_status = send_res.get("status", "") if isinstance(send_res, dict) else ""
    if res_status == "partial_delivery":
        pending["status"] = STATE_EMAIL_PARTIAL_DELIVERY
        pending["last_error"] = send_res.get("message", "Some recipients accepted the email and others refused it.")
        pending["accepted_recipients"] = send_res.get("accepted_recipients", [])
        pending["refused_recipients"] = send_res.get("refused_recipients", [])
        pending["send_outcome_ambiguous"] = False
        _pending_email_sessions[user] = pending
        msg = (f"The server accepted the email for some recipients but rejected it for others. {pending['last_error']} "
               "I will not resend the whole message because that could duplicate delivery. Cancel this draft and create a new email only to the rejected recipients.")
        try:
            speak(msg)
        except Exception:
            pass
        return {"success": False, "status": "partial_delivery", "message": msg, "draft": pending, "retry_safe": False}

    if res_status in ("timeout_ambiguous", "ambiguous") or (isinstance(send_res, dict) and send_res.get("retry_safe") is False):
        pending["status"] = STATE_EMAIL_AMBIGUOUS_OUTCOME
        pending["last_error"] = send_res.get("message", "The email delivery outcome could not be confirmed.")
        pending["send_outcome_ambiguous"] = True
        msg = f"The email may have been accepted by the mail server. {send_res.get('message', '')} Please check your Sent mailbox before retrying to prevent duplicate emails."
        _pending_email_sessions[user] = pending
        try:
            speak(msg)
        except Exception:
            pass
        return {
            "success": False,
            "status": "ambiguous_outcome",
            "message": msg,
            "draft": pending,
            "retry_safe": False
        }

    is_success = bool(send_res.get("success", False)) if isinstance(send_res, dict) else bool(send_res)
    if is_success:
        pending["status"] = STATE_EMAIL_SENT
        pending["sent_at"] = datetime.datetime.now().isoformat()
        _pending_email_sessions.pop(user, None)  # ONLY remove on confirmed success!
        invalidate_cache(email_id)
        att_note = f" with {send_res.get('attachments_count', 0)} attachment(s)" if (isinstance(send_res, dict) and send_res.get("attachments_count")) else ""
        msg = f"Email successfully sent to {to_addr}{att_note}."
        try:
            speak(msg)
        except Exception:
            pass
        return {
            "success": True,
            "status": "success",
            "recipient": to_addr,
            "subject": subject,
            "message": msg
        }
    else:
        # Sender returned failure (e.g. auth failure, network error, recipient rejected)
        pending["status"] = STATE_EMAIL_SEND_FAILED
        pending["last_error"] = send_res.get("message", f"Failed to send email to {to_addr}.") if isinstance(send_res, dict) else str(send_res)
        _pending_email_sessions[user] = pending
        err_msg = send_res.get("message", f"Failed to send email to {to_addr}.") if isinstance(send_res, dict) else str(send_res)
        spoken_err = _format_spoken_error(send_res, context="send", draft_retained=True)
        speak(spoken_err)
        return {
            "success": False,
            "status": send_res.get("status", "error") if isinstance(send_res, dict) else "error",
            "message": err_msg,
            "draft": pending
        }


# ──────────────────────────────────────────────────────────────────
# Credential management
# ──────────────────────────────────────────────────────────────────

def get_credentials(user: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetches stored credentials or prompts via GUI popup.
    Returns (email_id, plaintext_password) or (None, None).
    """
    current_u = user or get_current_user()
    email, password = get_user_email(current_u)
    if not email or not password:
        speak(f"I don't have email credentials for {current_u}. Please enter them in the popup.")
        email, password = get_email_credentials_popup()
        if email and password:
            save_user_email(current_u, email, password)
            speak("Credentials saved successfully.")
        else:
            speak("Could not get credentials. Email operations are unavailable.")
            return None, None
    return email, password


# ──────────────────────────────────────────────────────────────────
# File / attachment resolution (preserved from original)
# ──────────────────────────────────────────────────────────────────

def search_user_files_for_email(term: str) -> List[str]:
    """Search user-accessible directories for files matching term."""
    clean_term = term.lower().strip(' "\'')
    if not clean_term:
        return []

    search_dirs: List[str] = []
    try:
        from modules.system_controller.file_manager import get_desktop_path
        search_dirs.append(get_desktop_path())
    except Exception:
        pass

    user_home = Path.home()
    for sub in ["Downloads", "Documents", "Desktop"]:
        p = user_home / sub
        if p.exists():
            search_dirs.append(str(p))
    search_dirs.append(os.getcwd())

    stop_words = {"the", "a", "an", "my", "file", "document", "sheet", "pdf"}
    keywords = [w for w in clean_term.split() if w not in stop_words and len(w) > 1]
    if not keywords:
        keywords = [clean_term]

    matches: List[str] = []
    seen: set = set()

    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        try:
            for root_dir, dirs, files in os.walk(sdir):
                dirs[:] = [d for d in dirs if not d.startswith('.')
                            and d.lower() not in {'node_modules', 'venv', '__pycache__', 'appdata'}]
                for f in files:
                    f_low = f.lower()
                    if all(k in f_low for k in keywords):
                        full = os.path.abspath(os.path.join(root_dir, f))
                        if full not in seen:
                            seen.add(full)
                            matches.append(full)
        except Exception:
            continue

    return matches


# ──────────────────────────────────────────────────────────────────
# Natural-language intent parsing
# ──────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────
# Natural-language intent parsing
# ──────────────────────────────────────────────────────────────────

# Intent classification for email sub-actions
_RE_READ      = re.compile(r'\b(read|open|show|view|display)\b', re.I)
_RE_CHECK     = re.compile(r'\b(check|list|do i have|any new|show me|get)\b', re.I)
_RE_SEND      = re.compile(r'\b(send|compose|write|draft)\b', re.I)
_RE_REPLY     = re.compile(r'\b(reply|respond|reply all|respond to)\b', re.I)
_RE_FORWARD   = re.compile(r'\b(forward)\b', re.I)
_RE_SUMMARIZE = re.compile(r'\b(summarize|summary|brief|overview)\b', re.I)
_RE_UNREAD    = re.compile(r'\b(unread|unseen|new emails?|new mails?)\b', re.I)
_RE_TODAY     = re.compile(r'\b(today|received today|got today)\b', re.I)
_RE_YESTERDAY = re.compile(r'\b(yesterday|received yesterday|got yesterday)\b', re.I)
_RE_LAST_7_DAYS = re.compile(r'\b(last\s+7\s+days|past\s+7\s+days|past\s+week|last\s+week)\b', re.I)
_RE_LAST_30_DAYS = re.compile(r'\b(last\s+30\s+days|past\s+30\s+days|past\s+month|last\s+month)\b', re.I)
_RE_DATE_RANGE = re.compile(r'\b(?:between|from)\s+([0-9]{4}-[0-9]{1,2}-[0-9]{1,2}|[A-Za-z]+\s+[0-9]{1,2}(?:st|nd|rd|th)?(?:,?\s+[0-9]{4})?|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})\s+(?:and|to)\s+([0-9]{4}-[0-9]{1,2}-[0-9]{1,2}|[A-Za-z]+\s+[0-9]{1,2}(?:st|nd|rd|th)?(?:,?\s+[0-9]{4})?|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})\b', re.I)
_RE_DATE_BEFORE = re.compile(r'\b(?:emails?\s+)?before\s+([0-9]{4}-[0-9]{1,2}-[0-9]{1,2}|[A-Za-z]+\s+[0-9]{1,2}(?:st|nd|rd|th)?(?:,?\s+[0-9]{4})?|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})\b', re.I)
_RE_DATE_AFTER = re.compile(r'\b(?:emails?\s+)?(?:after|since)\s+([0-9]{4}-[0-9]{1,2}-[0-9]{1,2}|[A-Za-z]+\s+[0-9]{1,2}(?:st|nd|rd|th)?(?:,?\s+[0-9]{4})?|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})\b', re.I)
_RE_SEARCH    = re.compile(r'\b(find|search|look for|emails? from|emails? about|emails? with|where is the email)\b', re.I)
_RE_ARCHIVE   = re.compile(r'\b(archive)\b', re.I)
_RE_TRASH     = re.compile(r'\b(trash|delete|remove|move to trash)\b', re.I)
_RE_STAR      = re.compile(r'\b(star|flag|important)\b', re.I)
_RE_MARK_READ = re.compile(r'\b(mark\b.+\bas\s+read|mark\s+as\s+read|mark\s+read)\b', re.I)
_RE_MARK_UNREAD = re.compile(r'\b(mark\b.+\bas\s+unread|mark\s+as\s+unread|mark\s+unread)\b', re.I)
_RE_COUNT     = re.compile(r'\b(how many|count|number of)\b.{0,30}\b(email|mail|unread|message)\b', re.I)
_RE_ADD_CONTACT = re.compile(r'\b(add contact|save contact|new contact)\b', re.I)
_RE_ACTION_ITEMS = re.compile(r'\b(action items?|tasks? from|deadlines?|what deadlines|what does.+want)\b', re.I)

_RE_EXPLAIN   = re.compile(r'\b(explain|what does.+mean|in simple terms|what is this email about)\b', re.I)

# Draft intents
_RE_DRAFT_LIST = re.compile(r'\b(?:show|list|get|view)\s+(?:all\s+)?(?:my\s+)?drafts?\b', re.I)
_RE_DRAFT_SEND = re.compile(r'\b(?:send)\s+(?:my\s+)?draft\s*([0-9a-zA-Z_-]+)?\b', re.I)
_RE_DRAFT_EDIT = re.compile(r'\b(?:edit|open|modify|change|resume)\s+(?:my\s+)?draft\s*([0-9a-zA-Z_-]+)?\b', re.I)
_RE_DRAFT_DELETE = re.compile(r'\b(?:delete|remove|discard|trash)\s+(?:my\s+)?draft\s*([0-9a-zA-Z_-]+)?\b', re.I)

# Identity & status intents
_RE_MY_EMAIL = re.compile(r'\b(?:what\s+is|what\'s|show|tell\s+me|get)\s+(?:my\s+)?(?:email|email\s+address|email\s+id)\b', re.I)

# Folder and mailbox intents
_RE_FOLDER_LIST = re.compile(r'\b(?:list|show|get)\s+(?:all\s+)?(?:folders|mailboxes|labels)\b', re.I)
_RE_MOVE_EMAIL = re.compile(r'\b(?:move|transfer)\s+(?:this|the|latest)?\s*email\s+(?:to|into)\s+([a-zA-Z0-9_\-\s]+)\b', re.I)
_RE_FOLDER_CHECK = re.compile(r'\b(?:check|show|list|open|search\s+in)\s+(?:my\s+)?(inbox|sent|drafts?|spam|junk|trash|archive|bin|[a-zA-Z0-9_\-]+)\s+(?:folder|mailbox)\b', re.I)


def _extract_pasted_email_content(command: str) -> Optional[str]:
    """Extract embedded or pasted email text from a natural language prompt."""
    if not command:
        return None
    cmd = command.strip()
    cmd_low = cmd.lower()

    if any(h in cmd_low for h in ["from:", "subject:", "to:", "date:"]):
        m = re.search(r'(?:summarize|explain|extract|reply|draft\s+a?\s+reply|analyze|action\s+items?)(?:\s+(?:to|from|for|of)?\s*(?:this|the)?\s*(?:email|mail|message))?[:\s]+(.+)', cmd, re.I | re.DOTALL)
        if m and len(m.group(1).strip()) > 10:
            return m.group(1).strip()
        return cmd

    m_paste = re.search(r'\b(?:this\s+email|the\s+following\s+email|this\s+message|the\s+email)[:\s]+(.+)', cmd, re.I | re.DOTALL)
    if m_paste and len(m_paste.group(1).strip()) > 15:
        return m_paste.group(1).strip()

    return None


def _parse_email_intent(command: str) -> Dict[str, Any]:
    """
    Classify the user's email command into a structured intent dict.
    Returns: {action, search_query, recipient_raw, body_raw, tone, attachment_term}
    """
    cmd = command.strip()
    cmd_low = cmd.lower()

    action = "default"
    search_query: Optional[str] = None
    recipient_raw: Optional[str] = None
    body_raw: Optional[str] = None
    tone = "professional"
    attachment_term: Optional[str] = None

    # 0. General knowledge questions guard
    if re.search(r'^(?:how\s+does\s+email\s+work|what\s+is\s+email|why\s+email)\b', cmd_low):
        return {
            "action": "question",
            "search_query": None,
            "recipient_raw": None,
            "body_raw": None,
            "tone": "professional",
            "attachment_term": None,
            "original_command": cmd
        }

    # 0.5 Natural confirmation phrasing detection
    CONFIRM_SET = {
        "yes", "yeah", "yep", "sure", "ok", "okay", "send it", "send", "go ahead", "proceed",
        "confirmed", "confirm", "please send it", "yes send it", "yes send", "send that email now",
        "send the mail", "send the email", "send this email", "send this mail", "send that mail",
        "send that email", "send mail", "send email", "send draft", "send it now", "confirm send",
        "i confirm, send the email", "i confirm send the email", "i confirm, send the mail",
        "i confirm send the mail", "i confirm, send it", "i confirm send it",
        "you have my confirmation", "you have my confirmation, send it", "you have my confirmation send it",
        "you have my confirmation please send it", "please send the email", "please send the mail",
        "send message", "send the message", "confirm retry send"
    }
    c_clean = re.sub(r'[^\w\s]', '', cmd_low).strip()
    if cmd_low in CONFIRM_SET or c_clean in CONFIRM_SET:
        return {
            "action": "confirm_send",
            "search_query": None,
            "recipient_raw": None,
            "body_raw": None,
            "tone": "professional",
            "attachment_term": None,
            "original_command": cmd
        }

    # Natural-language compose extraction across varied phrasings
    c = re.sub(r'^(?:friday|alexa|hey\s+friday|assistant)[,\s]*', '', cmd, flags=re.I)
    c = re.sub(r'^(?:can\s+you\s+(?:help\s+me\s+)?|could\s+you\s+|please\s+|i\s+need\s+to\s+|i\s+want\s+to\s+)', '', c, flags=re.I).strip()
    c = c.rstrip('.?!').strip()

    # Pattern A: 'send a message to <recip> through [my] email'
    m_msg = re.search(r'\bsend\s+(?:a\s+)?message\s+(?:to\s+)?(.+?)\s+through\s+(?:my\s+)?email(?:\s+(?:that|saying|about|to)\s+(.*))?$', c, re.I)
    if m_msg:
        action = "compose"
        recipient_raw = m_msg.group(1).strip().rstrip('.?!')
        if m_msg.group(2):
            body_raw = m_msg.group(2).strip().rstrip('.?!')

    # Pattern B: prefix: (send an email|send a mail|mail|email|compose a mail|compose an email|prepare an email|prepare a mail|write an email|write a mail|write) (to|for|addressed to) <recip>
    if not recipient_raw:
        prefix_re = r'^(?:(?:send|compose|prepare|draft|write)\s+(?:an?\s+)?(?:email|mail)\s+(?:addressed\s+to|to|for)|mail\s+(?:to\s+)?|email\s+(?:to\s+)?|write\s+to\s+)'
        m_prefix = re.search(prefix_re, c, re.I)
        if m_prefix:
            action = "compose"
            remainder = c[m_prefix.end():].strip()
            m_pur = re.search(r'\s+(that|saying|about|to\s+request|with\s+message)\s+', remainder, re.I)
            if m_pur:
                recipient_raw = remainder[:m_pur.start()].strip().rstrip('.?!')
                if m_pur.group(1).lower().startswith('to'):
                    body_raw = remainder[m_pur.start():].strip().rstrip('.?!')
                else:
                    body_raw = remainder[m_pur.end():].strip().rstrip('.?!')
            else:
                recipient_raw = remainder.strip().rstrip('.?!')
                body_raw = None

    # Pattern C: 'send <recip> an email' / 'send <recip> a mail'
    if not recipient_raw:
        m_to_email = re.search(r'\bsend\s+(?!(?:an?|the|this|that|my|your|our)\s+(?:email|mail|message))(.+?)\s+(?:an?\s+)?(?:email|mail)(?:\s+(?:that|saying|about|to)\s+(.*))?$', c, re.I)
        if m_to_email:
            cand = m_to_email.group(1).strip().rstrip('.?!')
            if cand.lower() not in {"the", "a", "an", "this", "that", "it", "me", "my", "your", "our", "their", "send", "mail", "email", "draft", "message", "now", "please"}:
                action = "compose"
                recipient_raw = cand
                if m_to_email.group(2):
                    body_raw = m_to_email.group(2).strip().rstrip('.?!')

    # Inbox & general mailbox requests
    _RE_INBOX_QUERY = re.compile(
        r'\b(?:'
        r'check\s+(?:my\s+)?(?:inbox|email|emails|mail|mails)|'
        r'show\s+(?:me\s+)?(?:my\s+)?(?:latest|recent)?\s*(?:emails?|mails?|messages?|inbox)|'
        r'what\s+emails?\s+(?:have\s+i|did\s+i)\s+(?:received|got)|'
        r'read\s+(?:my\s+)?(?:recent|latest)?\s*(?:emails?|mails?|messages?)|'
        r'list\s+(?:my\s+)?(?:emails?|mails?|messages?)|'
        r'get\s+(?:my\s+)?(?:emails?|mails?|inbox)'
        r')\b',
        re.I
    )
    if action == "default" and _RE_INBOX_QUERY.search(cmd_low):
        action = "check"

    # Determine primary action with specific intent precedence if not already composed
    if action == "default":
        if _RE_MY_EMAIL.search(cmd_low):
            action = "my_email"
        elif _RE_DRAFT_LIST.search(cmd_low):
            action = "draft_list"
        elif _RE_DRAFT_SEND.search(cmd_low):
            action = "draft_send"
        elif _RE_DRAFT_EDIT.search(cmd_low):
            action = "draft_edit"
        elif _RE_DRAFT_DELETE.search(cmd_low):
            action = "draft_delete"
        elif _RE_FOLDER_LIST.search(cmd_low):
            action = "folder_list"
        elif _RE_MOVE_EMAIL.search(cmd_low):
            action = "folder_move"
        elif _RE_FOLDER_CHECK.search(cmd_low):
            action = "folder_check"
        elif _RE_ADD_CONTACT.search(cmd_low):
            action = "add_contact"
        elif _RE_COUNT.search(cmd_low):
            action = "count_unread" if _RE_UNREAD.search(cmd_low) else "count_inbox"
        elif _RE_FORWARD.search(cmd_low):
            action = "forward"
        elif _RE_REPLY.search(cmd_low):
            if "reply all" in cmd_low or "reply-all" in cmd_low:
                action = "reply_all"
            else:
                action = "reply"
        elif _RE_SUMMARIZE.search(cmd_low):
            action = "summarize"
        elif _RE_MARK_UNREAD.search(cmd_low):
            action = "mark_unread"
        elif _RE_MARK_READ.search(cmd_low):
            action = "mark_read"
        elif _RE_ARCHIVE.search(cmd_low):
            action = "archive"
        elif _RE_TRASH.search(cmd_low) and not any(k in cmd_low for k in ["folder", "mailbox", "draft"]):
            action = "trash"
        elif _RE_STAR.search(cmd_low) and "unstar" not in cmd_low:
            action = "star"
        elif "unstar" in cmd_low:
            action = "unstar"
        elif _RE_ACTION_ITEMS.search(cmd_low):
            action = "extract_actions"
        elif _RE_EXPLAIN.search(cmd_low):
            action = "explain"
        elif _RE_SEARCH.search(cmd_low):
            action = "search"
            m = re.search(r'\b(?:find|search|look for|emails?\s+from|emails?\s+about|emails?\s+with)\s+(.+?)(?:\s+(?:in|from|to|and|then).*)?$', cmd_low)
            if m:
                search_query = m.group(1).strip()
        elif _RE_DATE_RANGE.search(cmd_low):
            action = "date_range"
        elif _RE_DATE_BEFORE.search(cmd_low):
            action = "date_before"
        elif _RE_DATE_AFTER.search(cmd_low):
            action = "date_after"
        elif _RE_LAST_30_DAYS.search(cmd_low):
            action = "date_last_30_days"
        elif _RE_LAST_7_DAYS.search(cmd_low):
            action = "date_last_7_days"
        elif _RE_YESTERDAY.search(cmd_low):
            action = "date_yesterday"
        elif _RE_TODAY.search(cmd_low):
            action = "check_today"
        elif _RE_SEND.search(cmd_low):
            action = "compose"
        elif _RE_READ.search(cmd_low):
            action = "read"
        elif _RE_CHECK.search(cmd_low):
            action = "check"
        elif _RE_UNREAD.search(cmd_low):
            action = "check_unread"

    # Clean up recipient if extracted
    if recipient_raw:
        recipient_raw = re.sub(r'^(?:to|for|addressed\s+to)\s+', '', recipient_raw, flags=re.I).strip()
        recipient_raw = re.sub(r'^(?:the|a|an|this|that)\s+', '', recipient_raw, flags=re.I).strip()
        if recipient_raw.lower() in {"the", "a", "an", "this", "that", "it", "me", "my", "your", "our", "their", "send", "mail", "email", "draft", "message", "now", "please"}:
            recipient_raw = None
        elif len(recipient_raw) > 60:
            recipient_raw = recipient_raw[:60].strip()

    # Fallback recipient extraction: "send/email/mail/reply to <name_or_email> [and say <body>]"
    if action in ("compose", "reply", "reply_all", "forward") and not recipient_raw:
        m_to = re.search(r'\b(?:(?:send|compose|write|draft)\s+(?:an?\s+)?(?:email|mail)\s+(?:to|for)|to|for)\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-.]+|[A-Za-z0-9_\s]+?)(?:\s+(?:about|and|saying|with|regarding|re:)|$)', cmd, re.I)
        if m_to:
            candidate = m_to.group(1).strip().rstrip('.,?!')
            candidate = re.sub(r'^(?:to|for)\s+', '', candidate, flags=re.I).strip()
            candidate = re.sub(r'^(?:the|a|an|this|that)\s+', '', candidate, flags=re.I).strip()
            if candidate.lower() in {"the", "a", "an", "this", "that", "it", "me", "my", "your", "our", "their", "send", "mail", "email", "draft", "message", "now", "please"}:
                candidate = ""
            if candidate and len(candidate) <= 60:
                recipient_raw = candidate

        if not body_raw:
            m_body = re.search(r'\b(?:about|saying|and say|tell him|tell her|ask (?:him|her|them)|with message)\s+(.+)', cmd, re.I)
            if m_body:
                body_raw = m_body.group(1).strip()

    # Attachment term
    m_att = re.search(r'\b([a-zA-Z0-9_\-.]+\.(?:pdf|docx|xlsx|pptx|txt|csv|png|jpg|zip))\b', cmd, re.I)
    if m_att:
        attachment_term = m_att.group(1)
    else:
        for kw in ["the pdf", "the excel", "the spreadsheet", "the presentation", "the report", "the document"]:
            if kw in cmd_low:
                attachment_term = kw
                break

    return {
        "action": action,
        "search_query": search_query,
        "recipient_raw": recipient_raw,
        "body_raw": body_raw,
        "tone": tone,
        "attachment_term": attachment_term,
        "original_command": cmd
    }


def _handle_email_dictation_turn(
    command: str,
    user: str,
    pending: Dict[str, Any],
    email_id: Optional[str],
    email_pass: Optional[str]
) -> Dict[str, Any]:
    """
    Handles turns while in STATE_RECORDING_EMAIL_MESSAGE.
    Appends dictated speech segments in order, suppressing duplicate transcripts.
    Detects end-of-message / stop phrases ('stop message', 'stop dictation'),
    transitions to PROCESSING_EMAIL_MESSAGE, restructures the message professionally,
    and asks exactly one final confirmation question in PENDING_EMAIL_CONFIRMATION.
    """
    cmd_strip = command.strip()
    cmd_lower = cmd_strip.lower().rstrip('.?!')

    # Cancellation check
    if cmd_lower in (
        "cancel", "discard", "abort", "don't send", "dont send",
        "never mind", "nevermind", "cancel email", "cancel message", "cancel draft",
        "stop dictation and cancel"
    ):
        _pending_email_sessions.pop(user, None)
        speak("Pending email cancelled.")
        return {"success": True, "status": "cancelled", "message": "Pending email cancelled."}

    # Terminator / stop phrase detection
    stop_pattern = re.compile(
        r'\b(?:stop\s+message|stop\s+dictation|end\s+message|finish\s+message|finished\s+message|done\s+message)\b',
        re.IGNORECASE
    )
    stop_match = stop_pattern.search(command)

    if stop_match:
        # Dictation completed!
        text_before = command[:stop_match.start()].strip()
        text_after = command[stop_match.end():].strip()
        trailing_segment = f"{text_before} {text_after}".strip()
        trailing_segment = re.sub(r'^[.,\s]+|[.,\s]+$', '', trailing_segment).strip()

        if trailing_segment:
            if trailing_segment.lower() != pending.get("last_transcript", "").lower():
                pending.setdefault("message_buffer", []).append(trailing_segment)
                pending["last_transcript"] = trailing_segment

        pending["status"] = STATE_PROCESSING_EMAIL_MESSAGE

        message_buffer = pending.get("message_buffer", [])
        full_dictated = " ".join(seg for seg in message_buffer if seg.strip()).strip()

        if not full_dictated:
            pending["status"] = STATE_RECORDING_EMAIL_MESSAGE
            msg = "I didn't catch your message. Please dictate your message, or say 'cancel' to abort."
            speak(msg)
            return {"success": True, "status": "recording_email_message", "message": msg}

        recipient_name = pending.get("recipient_name") or pending.get("recipient")
        to_email = pending.get("recipient")
        attachments = pending.get("attachments", [])
        tone = pending.get("tone", "professional")

        speak(f"Preparing email for {recipient_name}...")
        subject, body = rewrite_professional(full_dictated, recipient_name, tone=tone)

        # Show review editor
        edited = show_email_editor(
            subject=subject,
            body=body,
            recipient_email=to_email,
            sender_email=email_id,
            sender_pass=email_pass,
            attachments=attachments
        )
        if edited.get("action") == "cancel":
            _pending_email_sessions.pop(user, None)
            speak("Draft cancelled.")
            return {"success": True, "status": "cancelled", "message": "Draft cancelled."}
        if edited.get("sent"):
            _pending_email_sessions.pop(user, None)
            att_note = f" with {len(edited.get('attachments', []))} attachment(s)" if edited.get("attachments") else ""
            msg = f"Email sent to {edited.get('recipient', to_email)}{att_note}."
            speak(msg)
            invalidate_cache(email_id)
            return {"success": True, "status": "success", "message": msg,
                    "recipient": edited.get("recipient", to_email), "subject": edited.get("subject", subject)}

        if edited.get("action") == "send" or (edited.get("confirmed") and edited.get("action") == "approved"):
            return _dispatch_pending_email(user, email_id, email_pass, override_draft=edited)

        final_subject = edited.get("subject", subject)
        final_body = edited.get("body", body)
        pending["recipient"] = edited.get("recipient", to_email)
        pending["subject"] = final_subject
        pending["body"] = final_body
        pending["raw_dictation"] = full_dictated
        pending["attachments"] = edited.get("attachments", attachments)
        pending["cc"] = edited.get("cc") or ""
        pending["bcc"] = edited.get("bcc") or ""
        pending["status"] = STATE_PENDING_EMAIL_CONFIRMATION
        pending["version"] = 1
        pending["timestamp"] = datetime.datetime.now().isoformat()
        _pending_email_sessions[user] = pending

        # Exactly ONE final confirmation question
        confirm_msg = f"Would you like me to send this email to {recipient_name} with the subject '{final_subject}'?"
        speak(confirm_msg)
        return {
            "success": True,
            "status": "pending_confirmation",
            "recipient": to_email,
            "recipient_name": recipient_name,
            "subject": final_subject,
            "body": final_body,
            "message": confirm_msg,
            "draft": pending
        }

    # Ongoing dictation turn
    # Suppress duplicate utterance (e.g. VAD repeat)
    if cmd_strip.lower() == pending.get("last_transcript", "").lower():
        return {
            "success": True,
            "status": "recording_email_message",
            "message": "Continuing listening...",
            "duplicate_ignored": True,
            "handled": True
        }

    pending.setdefault("message_buffer", []).append(cmd_strip)
    pending["last_transcript"] = cmd_strip
    _pending_email_sessions[user] = pending

    return {
        "success": True,
        "status": "recording_email_message",
        "message": "Listening for your message. Say 'stop message' when finished.",
        "captured_segment": cmd_strip,
        "buffer_count": len(pending["message_buffer"]),
        "recipient": pending.get("recipient"),
        "handled": True
    }


# ──────────────────────────────────────────────────────────────────
# Core public function — called from UnifiedCommandRouter
# ──────────────────────────────────────────────────────────────────

def handle_email_command(command: str, user_id: Optional[Any] = None) -> Dict[str, Any]:
    """
    Main entry point dispatched by the unified router for Intent.EMAIL.
    Preserves original signature: (command, user_id) → dict.
    """
    cmd_lower = command.lower()
    current_u = _resolve_user(user_id)

    # Fetch credentials for this specific user (isolated)
    email_id, email_pass = get_user_email(current_u)

    parsed = _parse_email_intent(command)
    action = parsed["action"]

    # ── Active In-Flight Pending Email Resolution ────────────────────────────
    pending = _pending_email_sessions.get(current_u)
    if pending:
        if pending.get("status") == STATE_SENDING_EMAIL:
            return {"success": False, "status": "in_progress", "message": "The email is currently being sent. Please wait for the result before editing or cancelling it."}

        if pending.get("status") == STATE_EMAIL_PARTIAL_DELIVERY:
            if any(w in cmd_lower for w in ["cancel", "discard", "abort", "don't send", "dont send", "never mind", "nevermind"]):
                _pending_email_sessions.pop(current_u, None)
                try:
                    speak("The partial-delivery draft was cleared. Previously accepted recipients may already have received the email.")
                except Exception:
                    pass
                return {"success": True, "status": "cancelled", "message": "Partial-delivery draft cleared; previously accepted recipients may already have received the message."}
            msg = ("This email was partially delivered. I will not resend the full recipient list because some recipients may already have received it. "
                   "Cancel this draft and create a new email addressed only to the rejected recipients.")
            try:
                speak(msg)
            except Exception:
                pass
            return {"success": False, "status": "partial_delivery", "message": msg, "draft": pending, "retry_safe": False}

        # An ambiguous delivery must never be retried by a plain repeated "yes",
        # "send", or "retry". Require the user to acknowledge checking Sent first.
        if pending.get("status") == STATE_EMAIL_AMBIGUOUS_OUTCOME:
            if any(w in cmd_lower for w in ["cancel", "discard", "abort", "don't send", "dont send", "never mind", "nevermind"]):
                _pending_email_sessions.pop(current_u, None)
                try:
                    speak("Pending email cancelled. No further send attempt was made.")
                except Exception:
                    pass
                return {"success": True, "status": "cancelled", "message": "Pending email cancelled."}
            checked_sent = any(phrase in cmd_lower for phrase in (
                "checked sent", "checked my sent", "checked the sent", "looked in sent", "checked sent folder"
            ))
            absent_from_sent = any(phrase in cmd_lower for phrase in (
                "not there", "isn't there", "isnt there", "not in sent", "wasn't sent", "wasnt sent", "not sent"
            ))
            if checked_sent and absent_from_sent and any(w in cmd_lower for w in ("retry", "resend", "send again")):
                pending["status"] = "PENDING_CONFIRMATION"
                pending["retry_after_ambiguous_ack"] = True
                _pending_email_sessions[current_u] = pending
                msg = "Because delivery was uncertain, I need one final confirmation. Say 'confirm retry send' only if you checked Sent and the email is not there."
                try:
                    speak(msg)
                except Exception:
                    pass
                return {"success": True, "status": "pending_confirmation", "message": msg, "draft": pending}
            msg = ("The previous send outcome is uncertain. I will not send it again automatically. "
                   "Check your Sent folder first; if it is absent, tell me you checked Sent and it was not there, then ask to retry.")
            try:
                speak(msg)
            except Exception:
                pass
            return {"success": False, "status": "ambiguous_outcome", "message": msg, "draft": pending, "retry_safe": False}

        # Case 0: Recipient clarification / disambiguation
        if pending.get("status") in (STATE_EMAIL_RECIPIENT_RESOLUTION, STATE_UNVERIFIED_RECIPIENT):
            if any(w in cmd_lower for w in ["cancel", "discard", "abort", "don't send", "dont send", "stop", "never mind", "nevermind", "no"]):
                _pending_email_sessions.pop(current_u, None)
                speak("Pending email cancelled.")
                return {"success": True, "status": "cancelled", "message": "Pending email cancelled."}

            # Check if user provided an email address directly
            m_email = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', command)
            if m_email and is_valid_email(m_email.group(1)) and not is_placeholder_email(m_email.group(1)):
                verified_addr = m_email.group(1)
                recipient_name = pending.get("recipient_name") or pending.get("recipient_raw") or "recipient"
                save_contact(recipient_name, verified_addr)
                session_id = pending.get("session_id", str(uuid.uuid4()))
                pending["status"] = STATE_RECORDING_EMAIL_MESSAGE
                pending["recipient"] = verified_addr
                pending["recipient_name"] = recipient_name
                pending["message_buffer"] = []
                pending["last_transcript"] = ""
                _pending_email_sessions[current_u] = pending
                msg = f"Got it, saved {verified_addr} for {recipient_name}. Sure, I'm listening. Say your message, then say 'stop message' when you're finished."
                speak(msg)
                return {
                    "success": True,
                    "status": "recording_email_message",
                    "session_id": session_id,
                    "recipient": verified_addr,
                    "recipient_name": recipient_name,
                    "message": msg
                }

            candidates = pending.get("candidates", [])
            chosen = None
            for cand in candidates:
                if cand["name"].lower() in cmd_lower or cand["email"].lower() in cmd_lower:
                    chosen = cand
                    break
            if not chosen and candidates:
                if "first" in cmd_lower or "1" in cmd_lower:
                    chosen = candidates[0]
                elif ("second" in cmd_lower or "2" in cmd_lower) and len(candidates) > 1:
                    chosen = candidates[1]

            if chosen:
                to_email = chosen["email"]
                recipient_name = chosen["name"]
                if is_placeholder_email(to_email):
                    pending["status"] = STATE_UNVERIFIED_RECIPIENT
                    pending["recipient_name"] = recipient_name
                    _pending_email_sessions[current_u] = pending
                    msg = f"'{to_email}' for {recipient_name} is an unverified placeholder. Please provide a verified email address."
                    speak(msg)
                    return {
                        "success": False,
                        "status": "clarification",
                        "needs_clarification": True,
                        "message": msg
                    }

                session_id = pending.get("session_id", str(uuid.uuid4()))
                pending["status"] = STATE_RECORDING_EMAIL_MESSAGE
                pending["recipient"] = to_email
                pending["recipient_name"] = recipient_name
                pending["message_buffer"] = []
                pending["last_transcript"] = ""
                _pending_email_sessions[current_u] = pending
                msg = f"Got it, sending to {recipient_name}. Sure, I'm listening. Say your message, then say 'stop message' when you're finished."
                speak(msg)
                return {
                    "success": True,
                    "status": "recording_email_message",
                    "session_id": session_id,
                    "recipient": to_email,
                    "recipient_name": recipient_name,
                    "message": msg
                }
            else:
                names = ", ".join(f"{c['name']} ({c['email']})" for c in candidates[:4])
                msg = f"'{pending.get('recipient_raw')}' matches multiple contacts: {names}. Which one did you mean?"
                speak(msg)
                return {
                    "success": False,
                    "status": "clarification",
                    "needs_clarification": True,
                    "message": msg
                }

        # Case 1: Dedicated Voice Dictation Recording Mode
        if pending.get("status") == STATE_RECORDING_EMAIL_MESSAGE:
            return _handle_email_dictation_turn(command, current_u, pending, email_id, email_pass)

        # Case 2: User is in NEED_PURPOSE state (gathering purpose before creating draft)
        if pending.get("status") == "NEED_PURPOSE":
            if any(w in cmd_lower for w in ["cancel", "discard", "abort", "don't send", "dont send", "stop", "never mind", "nevermind", "no"]):
                _pending_email_sessions.pop(current_u, None)
                speak("Pending email cancelled.")
                return {"success": True, "status": "cancelled", "message": "Pending email cancelled."}

            # Capture purpose provided by user
            purpose = re.sub(r'^(?:that|saying|about|to)\s+', '', command.strip(), flags=re.I).strip()
            recipient_name = pending.get("recipient_name") or pending.get("recipient")
            to_email = pending.get("recipient")
            attachments = pending.get("attachments", [])
            tone = pending.get("tone", "professional")

            speak(f"Preparing draft for {recipient_name}...")
            subject, body = rewrite_professional(purpose, recipient_name, tone=tone)

            # Show review editor
            edited = show_email_editor(
                subject=subject,
                body=body,
                recipient_email=to_email,
                sender_email=email_id,
                sender_pass=email_pass,
                attachments=attachments
            )
            if edited.get("action") == "cancel":
                _pending_email_sessions.pop(current_u, None)
                speak("Draft cancelled.")
                return {"success": True, "status": "cancelled", "message": "Draft cancelled."}
            if edited.get("sent") or edited.get("action") == "send":
                _pending_email_sessions.pop(current_u, None)
                return _dispatch_pending_email(current_u, email_id, email_pass, override_draft=edited)

            final_subject = edited.get("subject", subject)
            final_body = edited.get("body", body)
            pending["subject"] = final_subject
            pending["body"] = final_body
            pending["status"] = "PENDING_CONFIRMATION"
            pending["version"] = 1
            pending["timestamp"] = datetime.datetime.now().isoformat()
            _pending_email_sessions[current_u] = pending

            # Exactly ONE final confirmation question
            confirm_msg = f"Would you like me to send this email to {recipient_name} with the subject '{final_subject}'?"
            speak(confirm_msg)
            return {
                "success": True,
                "status": "pending_confirmation",
                "recipient": to_email,
                "recipient_name": recipient_name,
                "subject": final_subject,
                "body": final_body,
                "message": confirm_msg,
                "draft": pending
            }

        # Case B: Draft is prepared and pending single send confirmation
        if pending.get("recipient"):
            # 1. Cancellation
            if any(w in cmd_lower for w in ["cancel", "discard", "abort", "don't send", "dont send", "cancel the email", "cancel email", "cancel draft", "no", "nope", "stop", "keep it as a draft", "keep as draft", "keep draft"]):
                if any(k in cmd_lower for k in ["keep", "save"]):
                    draft_id = save_draft(current_u, pending)
                    _pending_email_sessions.pop(current_u, None)
                    speak("Draft saved.")
                    return {"success": True, "status": "draft_saved", "draft_id": draft_id, "message": f"Draft saved (ID: {draft_id})."}
                _pending_email_sessions.pop(current_u, None)
                speak("Pending email cancelled.")
                return {"success": True, "status": "cancelled", "message": "Pending email cancelled."}

            # 2. Re-open review / show draft
            if any(k in cmd_lower for k in ["show me the email", "show the email", "read the draft", "what are you going to send", "preview it", "preview", "show me the draft", "show the draft", "show draft", "view draft", "review draft", "open draft", "show draft again"]):
                recipient_name = pending.get("recipient_name") or pending.get("recipient")
                preview_text = f"To: {recipient_name} <{pending.get('recipient')}>\nSubject: {pending.get('subject')}\nBody:\n{pending.get('body')}"
                confirm_msg = f"Would you like me to send this email to {recipient_name} with the subject '{pending.get('subject')}'?"
                speak(f"Here is your draft. {confirm_msg}")
                return {
                    "success": True,
                    "status": "pending_confirmation",
                    "preview": preview_text,
                    "message": f"{preview_text}\n\n{confirm_msg}",
                    "draft": pending
                }

            # 3. Draft Modification ("make it shorter", "change subject to X", "add ...", "rewrite ...")
            is_modification = (
                any(k in cmd_lower for k in [
                    "make it shorter", "make that email shorter", "make email shorter", "shorten", "more concise",
                    "change subject", "change the subject", "subject to", "change body", "change the body",
                    "add that", "add note", "add meeting", "make it formal", "make it casual", "make it friendly",
                    "rewrite", "edit draft", "update draft", "modify draft", "add attachment"
                ])
                and not parsed.get("recipient_raw")
            )
            if is_modification:
                current_subj = pending.get("subject", "")
                current_body = pending.get("body", "")
                new_subj, new_body = edit_email_draft(current_subj, current_body, command)
                pending["subject"] = new_subj
                pending["body"] = new_body
                pending["version"] = pending.get("version", 1) + 1
                pending["updated_at"] = datetime.datetime.now().isoformat()
                _pending_email_sessions[current_u] = pending
                recipient_name = pending.get("recipient_name") or pending.get("recipient")
                confirm_msg = f"Would you like me to send this email to {recipient_name} with the subject '{new_subj}'?"
                speak(f"I've updated the draft. {confirm_msg}")
                return {
                    "success": True,
                    "status": "pending_confirmation",
                    "message": confirm_msg,
                    "draft": pending
                }

            # 4. Check for send confirmation
            clean_cmd = re.sub(r'[^\w\s]', '', cmd_lower).strip()
            new_recipient = parsed.get("recipient_raw")
            is_same_or_no_recipient = (
                not new_recipient
                or new_recipient.lower() in {"the", "a", "an", "this", "that", "it", "me", "my", "your", "our", "their", "send", "mail", "email"}
                or new_recipient.lower() == (pending.get("recipient_name") or "").lower()
                or new_recipient.lower() == (pending.get("recipient") or "").lower()
            )
            is_send_confirmation = (
                (
                    action == "confirm_send"
                    or any(k in cmd_lower or k in clean_cmd for k in [
                        "send the mail", "send the email", "send this email", "send this mail", "send that email",
                        "send that mail", "send it", "send mail", "send email", "send it now",
                        "confirm send", "confirm retry send", "proceed", "yes send", "send draft", "send",
                        "yes", "yeah", "yep", "sure", "ok", "okay", "go ahead", "confirmed", "confirm", "please send it",
                        "send that email now", "i confirm, send the email", "i confirm send the email",
                        "i confirm, send the mail", "i confirm send the mail", "i confirm, send it",
                        "i confirm send it", "you have my confirmation", "you have my confirmation, send it",
                        "you have my confirmation send it", "please send the email", "please send the mail",
                        "send message", "send the message", "retry", "try again", "resend", "retry send"
                    ])
                    or clean_cmd in {
                        "yes", "yeah", "yep", "sure", "ok", "okay", "send it", "send", "go ahead", "proceed",
                        "confirmed", "confirm", "please send it", "yes send it", "send the mail", "send the email",
                        "send this email", "i confirm send the email", "you have my confirmation",
                        "you have my confirmation send it"
                    }
                    or any(phrase in cmd_lower for phrase in [
                        "send the mail", "send the email", "send this email", "i confirm, send",
                        "you have my confirmation", "confirm send"
                    ])
                )
                and is_same_or_no_recipient
            )
            if is_send_confirmation:
                return _dispatch_pending_email(current_u, email_id, email_pass)

    # ── 0. My Email Address Query ─────────────────────────────────────────────
    if action == "my_email" or _RE_MY_EMAIL.search(cmd_lower):
        return _handle_my_email(current_u)

    # ── 0. Persistent Draft Management (Priority P1) ──────────────────────────
    if action == "draft_list" or _RE_DRAFT_LIST.search(cmd_lower):
        return _handle_draft_list(current_u)

    if action == "draft_send" or _RE_DRAFT_SEND.search(cmd_lower):
        m_ref = _RE_DRAFT_SEND.search(cmd_lower)
        ref = m_ref.group(1) if m_ref and m_ref.group(1) else None
        return _handle_draft_send(command, current_u, ref)

    if action == "draft_edit" or _RE_DRAFT_EDIT.search(cmd_lower):
        m_ref = _RE_DRAFT_EDIT.search(cmd_lower)
        ref = m_ref.group(1) if m_ref and m_ref.group(1) else None
        return _handle_draft_edit(command, current_u, ref)

    if action == "draft_delete" or _RE_DRAFT_DELETE.search(cmd_lower):
        m_ref = _RE_DRAFT_DELETE.search(cmd_lower)
        ref = m_ref.group(1) if m_ref and m_ref.group(1) else None
        return _handle_draft_delete(command, current_u, ref)

    # ── 1. Folder and Mailbox Navigation (Priority P3) ────────────────────────
    if action == "folder_list" or _RE_FOLDER_LIST.search(cmd_lower):
        return _handle_folder_list(email_id, email_pass, current_u)

    if action == "folder_move" or _RE_MOVE_EMAIL.search(cmd_lower):
        m_mov = _RE_MOVE_EMAIL.search(cmd_lower)
        dest = m_mov.group(1).strip() if m_mov else "Trash"
        return _handle_move_email(email_id, email_pass, current_u, dest, command)

    if action == "folder_check" or _RE_FOLDER_CHECK.search(cmd_lower):
        m_chk = _RE_FOLDER_CHECK.search(cmd_lower)
        target = m_chk.group(1).strip() if m_chk else "inbox"
        return _handle_folder_check(email_id, email_pass, current_u, target, query=parsed.get("search_query"))

    # ── 2. Custom Date Filtering (Priority P3) ────────────────────────────────
    if action == "date_range" or _RE_DATE_RANGE.search(cmd_lower):
        m_rng = _RE_DATE_RANGE.search(cmd_lower)
        if m_rng:
            d1 = _parse_nl_date(m_rng.group(1))
            d2 = _parse_nl_date(m_rng.group(2))
            if d1 and d2:
                return _handle_date_query(email_id, email_pass, current_u, criterion="RANGE",
                                          date_from=d1, date_to=d2, label=f"between {d1} and {d2}")
        return {"success": False, "status": "clarification", "message": "I could not understand the date range. Please specify dates like 'between 2026-10-01 and 2026-10-08'."}

    if action == "date_before" or _RE_DATE_BEFORE.search(cmd_lower):
        m_bef = _RE_DATE_BEFORE.search(cmd_lower)
        if m_bef:
            d_val = _parse_nl_date(m_bef.group(1))
            if d_val:
                return _handle_date_query(email_id, email_pass, current_u, criterion="BEFORE",
                                          date_to=d_val, label=f"before {d_val}")
        return {"success": False, "status": "clarification", "message": "Please specify a clear date (e.g., 'emails before 2026-10-05')."}

    if action == "date_after" or _RE_DATE_AFTER.search(cmd_lower):
        m_aft = _RE_DATE_AFTER.search(cmd_lower)
        if m_aft:
            d_val = _parse_nl_date(m_aft.group(1))
            if d_val:
                return _handle_date_query(email_id, email_pass, current_u, criterion="AFTER",
                                          date_from=d_val, label=f"after {d_val}")
        return {"success": False, "status": "clarification", "message": "Please specify a clear date (e.g., 'emails after 2026-10-01')."}

    if action == "date_last_30_days" or _RE_LAST_30_DAYS.search(cmd_lower):
        return _handle_date_query(email_id, email_pass, current_u, criterion="LAST_30_DAYS", label="the last 30 days")

    if action == "date_last_7_days" or _RE_LAST_7_DAYS.search(cmd_lower):
        return _handle_date_query(email_id, email_pass, current_u, criterion="LAST_7_DAYS", label="the last 7 days")

    if action == "date_yesterday" or _RE_YESTERDAY.search(cmd_lower):
        return _handle_date_query(email_id, email_pass, current_u, criterion="YESTERDAY", label="yesterday")

    if _RE_TODAY.search(cmd_lower) and any(e in cmd_lower for e in ["email", "mail"]):
        return _handle_today_emails(email_id, email_pass, current_u)

    # ── 3. First email / latest email sender (legacy query paths, preserved) ─
    if any(k in cmd_lower for k in ["first mail", "first email", "first message"]) and \
       not any(k in cmd_lower for k in ["ever sent", "in the world", "in history"]):
        return _handle_first_email(email_id, email_pass, current_u)

    if any(k in cmd_lower for k in ["who sent", "latest sender", "last sender",
                                     "sender of my latest", "sender of my last"]):
        return _handle_latest_sender(email_id, email_pass, current_u)

    # ── 4. Inbox / unread check ──────────────────────────────────────────────
    is_inbox_query = (
        any(k in cmd_lower for k in [
            "inbox", "check my email", "check my mail", "check my mails",
            "check email", "check mail", "check mails", "do i have any",
            "new emails", "new email", "show email", "show emails",
            "list email", "list emails", "show unread", "list unread"
        ])
        or (any(w in cmd_lower for w in ["check", "show", "list", "get"])
            and any(e in cmd_lower for e in ["email", "emails", "mail", "mails", "inbox"]))
    )
    is_send = any(k in cmd_lower for k in ["send", "compose", "forward", "write to", "reply", "draft"])

    if is_inbox_query and not is_send:
        if _RE_UNREAD.search(cmd_lower):
            return _handle_unread(email_id, email_pass, current_u)
        return get_emails_overview(limit=5, user=current_u)

    # ── 5. Count unread ──────────────────────────────────────────────────────
    if action == "count_unread" or (
        _RE_COUNT.search(cmd_lower) and _RE_UNREAD.search(cmd_lower)
    ):
        return _handle_count_unread(email_id, email_pass, current_u)

    # ── 6. Search ────────────────────────────────────────────────────────────
    if action == "search":
        return _handle_search(email_id, email_pass, current_u, parsed.get("search_query") or "")

    # ── 7. Summary ───────────────────────────────────────────────────────────
    if action == "summarize":
        return _handle_summarize(email_id, email_pass, current_u, command=command)

    # ── 8. Extract action items ──────────────────────────────────────────────
    if action == "extract_actions":
        return _handle_extract_actions(email_id, email_pass, current_u, command=command)

    # ── 9. Explain email ─────────────────────────────────────────────────────
    if action == "explain":
        return _handle_explain_email(email_id, email_pass, current_u, command=command)

    # ── 10. Reply / Reply All (Priority P2) ──────────────────────────────────
    if action in ("reply", "reply_all") or "reply all" in cmd_lower or "reply-all" in cmd_lower:
        is_reply_all = (action == "reply_all" or "reply all" in cmd_lower or "reply-all" in cmd_lower)
        return _handle_reply(email_id, email_pass, current_u, reply_all=is_reply_all, command=command)

    # ── 11. Forward ──────────────────────────────────────────────────────────
    if action == "forward":
        return _handle_forward(command, parsed, email_id, email_pass, current_u)

    # ── 12. Message organization (mark read/unread, star, archive, trash) ───
    if action in ("mark_read", "mark_unread", "star", "unstar", "archive", "trash"):
        return _handle_organize(email_id, email_pass, current_u, action, command)

    # ── 13. Compose / Send with mandatory review-confirm workflow ────────────
    if action == "compose" or any(k in cmd_lower for k in ["send email", "compose email", "write email", "send a mail", "send mail", "send an email"]):
        return _handle_compose_with_review(command, parsed, current_u, user_id)

    # ── 14. Add contact ──────────────────────────────────────────────────────
    if action == "add_contact":
        return _handle_add_contact()

    # ── Fallback: interactive mode ────────────────────────────────────────────
    email_id, email_pass = get_credentials(current_u)
    if not email_id:
        return {"success": False, "status": "error",
                "message": "Email credentials not configured."}

    if "send" in cmd_lower or "compose" in cmd_lower or "write" in cmd_lower:
        _handle_send_interactive(None, email_id, email_pass)
        return {"success": True, "status": "success", "message": "Handled email send."}
    elif "check" in cmd_lower or "inbox" in cmd_lower:
        _handle_check_inbox_interactive(email_id, email_pass)
        return {"success": True, "status": "success", "message": "Checked inbox."}
    elif "read" in cmd_lower or "open" in cmd_lower:
        _handle_read_interactive(email_id, email_pass)
        return {"success": True, "status": "success", "message": "Read email."}
    elif "summarize" in cmd_lower or "summary" in cmd_lower:
        _handle_summarize_interactive(email_id, email_pass)
        return {"success": True, "status": "success", "message": "Summarized inbox."}
    elif "reply" in cmd_lower:
        _handle_reply_interactive(email_id, email_pass)
        return {"success": True, "status": "success", "message": "Handled reply."}
    elif "add" in cmd_lower and "contact" in cmd_lower:
        return _handle_add_contact()
    else:
        msg = ("I'm not sure what you want to do with email. "
               "You can say send email, check inbox, summarize mail, reply, or search emails.")
        speak(msg)
        return {"success": False, "status": "unknown", "message": msg}


# ──────────────────────────────────────────────────────────────────
# Specialized handlers
# ──────────────────────────────────────────────────────────────────

def _no_creds_error(user: str) -> Dict[str, Any]:
    return {
        "success": False,
        "status": "auth_required",
        "message": (f"Email credentials not configured for '{user}'. "
                    "Please set them up in Settings → Email.")
    }


def _handle_first_email(email_id, email_pass, user) -> Dict[str, Any]:
    if not email_id or not email_pass:
        return _no_creds_error(user)
    emails, meta = fetch_latest_emails_with_status(limit=10, email_id=email_id, email_pass=email_pass)
    if not meta.get("success"):
        return {"success": False, "status": "error", "message": f"Email access failed: {meta.get('error')}."}
    if emails:
        e = emails[-1]
        msg = (f"The earliest email in your recent inbox is from {e.get('sender', 'Unknown')} "
               f"regarding '{e.get('subject', 'No subject')}', received on {e.get('date', 'unknown date')}.")
        return {"success": True, "status": "success", "email": e, "message": msg}
    return {"success": True, "status": "success", "message": "No emails found in your inbox."}


def _handle_latest_sender(email_id, email_pass, user) -> Dict[str, Any]:
    if not email_id or not email_pass:
        return _no_creds_error(user)
    emails, meta = fetch_latest_emails_with_status(limit=1, email_id=email_id, email_pass=email_pass)
    if not meta.get("success"):
        return {"success": False, "status": "error", "message": f"Email access failed: {meta.get('error')}."}
    if emails:
        e = emails[0]
        msg = (f"Your latest email was sent by {e.get('sender', 'Unknown')} "
               f"regarding '{e.get('subject', 'No subject')}'.")
        return {"success": True, "status": "success", "email": e, "message": msg}
    return {"success": True, "status": "success", "message": "No emails found in your inbox."}


def _handle_today_emails(email_id, email_pass, user) -> Dict[str, Any]:
    if not email_id or not email_pass:
        return _no_creds_error(user)
    emails, meta = fetch_latest_emails_with_status(
        limit=20, email_id=email_id, email_pass=email_pass, criterion="TODAY"
    )
    if not meta.get("success"):
        return {"success": False, "status": "error", "message": f"Email access failed: {meta.get('error')}."}
    if emails:
        summaries = [f"From {e.get('sender')}: '{e.get('subject')}'" for e in emails[:5]]
        msg = f"You received {len(emails)} email(s) today. " + "; ".join(summaries) + "."
        return {"success": True, "status": "success", "emails": emails, "message": msg}
    return {"success": True, "status": "success", "message": "No emails received today."}


def _handle_unread(email_id, email_pass, user) -> Dict[str, Any]:
    if not email_id or not email_pass:
        return _no_creds_error(user)
    emails, meta = fetch_latest_emails_with_status(
        limit=20, email_id=email_id, email_pass=email_pass, criterion="UNSEEN"
    )
    if not meta.get("success"):
        return {"success": False, "status": "error", "message": f"Email access failed: {meta.get('error')}."}
    if emails:
        summaries = [f"From {e.get('sender')}: '{e.get('subject')}'" for e in emails[:5]]
        msg = f"You have {len(emails)} unread email(s). " + "; ".join(summaries) + "."
        return {"success": True, "status": "success", "emails": emails, "count": len(emails), "message": msg}
    return {"success": True, "status": "success", "count": 0, "emails": [],
            "message": "No unread emails found."}


def _handle_count_unread(email_id, email_pass, user) -> Dict[str, Any]:
    if not email_id or not email_pass:
        return _no_creds_error(user)
    count, meta = count_unread_emails(email_id, email_pass)
    if not meta.get("success"):
        return {"success": False, "status": "error",
                "message": f"Could not count unread emails: {meta.get('error')}."}
    msg = f"You have {count} unread email{'s' if count != 1 else ''}." if count > 0 else "You have no unread emails."
    return {"success": True, "status": "success", "count": count, "message": msg}


def _handle_search(email_id, email_pass, user, query: str) -> Dict[str, Any]:
    if not email_id or not email_pass:
        return _no_creds_error(user)
    if not query.strip():
        return {"success": False, "status": "error",
                "message": "Please specify what to search for (e.g., a sender name, keyword, or subject)."}

    clean_q = re.sub(r'^(?:the\s+)?(?:latest\s+|recent\s+)?(?:emails?\s+)?(?:from|about|with)\s+', '', query, flags=re.I).strip()
    if not clean_q:
        clean_q = query.strip()

    if "attachment" in query.lower() or "attachment" in clean_q.lower():
        # Search a bounded, recent window specifically for attachment metadata;
        # the reader filters before applying the result limit, not after fetching
        # only the latest 20 arbitrary messages.
        scan_limit = 500
        emails, meta = fetch_latest_emails_with_status(
            limit=scan_limit,
            email_id=email_id,
            email_pass=email_pass,
            attachments_only=True,
            attachment_scan_limit=scan_limit,
        )
        if not meta.get("success"):
            return {"success": False, "status": "error", "message": f"Search failed: {meta.get('error')}."}
        filtered = [e for e in emails if e.get("attachments")]
        scan_note = f" in the {meta.get('scanned_count', scan_limit)} most recent messages checked"
        if meta.get("scan_truncated"):
            scan_note += "; older messages were not scanned"
        if filtered:
            summaries = [f"From {e.get('sender')}: '{e.get('subject')}' ({len(e.get('attachments', []))} attachment(s))" for e in filtered[:5]]
            msg = f"Found {len(filtered)} email(s) with attachments{scan_note}. " + "; ".join(summaries) + "."
            return {"success": True, "status": "success", "emails": filtered, "query": query, "message": msg,
                    "scanned_count": meta.get("scanned_count"), "scan_truncated": meta.get("scan_truncated", False)}
        return {"success": True, "status": "success", "emails": [], "query": query,
                "scanned_count": meta.get("scanned_count"), "scan_truncated": meta.get("scan_truncated", False),
                "message": f"No emails with attachments found{scan_note}."}

    emails, meta = fetch_latest_emails_with_status(
        limit=10, email_id=email_id, email_pass=email_pass,
        search_query=clean_q
    )
    if not meta.get("success"):
        return {"success": False, "status": "error", "message": f"Search failed: {meta.get('error')}."}
    if emails:
        summaries = [f"From {e.get('sender')}: '{e.get('subject')}'" for e in emails[:5]]
        msg = f"Found {len(emails)} email(s) matching '{clean_q}'. " + "; ".join(summaries) + "."
        return {"success": True, "status": "success", "emails": emails, "query": clean_q, "message": msg}
    return {"success": True, "status": "success", "emails": [], "query": clean_q,
            "message": f"No emails found matching '{clean_q}'."}


def _handle_my_email(user: str) -> Dict[str, Any]:
    email_id, _ = get_user_email(user)
    if email_id:
        msg = f"Your email address is {email_id}."
        speak(msg)
        return {"success": True, "status": "success", "email": email_id, "message": msg}
    else:
        msg = f"I don't have an email address configured for '{user}'. You can configure it in email settings."
        speak(msg)
        return {"success": False, "status": "not_configured", "message": msg}


def _handle_summarize(email_id, email_pass, user, command: str = "") -> Dict[str, Any]:
    pasted = _extract_pasted_email_content(command)
    if pasted:
        summary = generate_summary([{"sender": "Pasted Content", "subject": "Pasted Email", "body": pasted}])
        speak(summary)
        return {"success": True, "status": "success", "message": summary, "emails": [{"sender": "Pasted Content", "subject": "Pasted Email", "body": pasted}]}
    if not email_id or not email_pass:
        return _no_creds_error(user)
    emails, meta = fetch_latest_emails_with_status(limit=8, email_id=email_id, email_pass=email_pass)
    if not meta.get("success"):
        return {"success": False, "status": "error", "message": f"Email access failed: {meta.get('error')}."}
    summary = generate_summary(emails)
    speak(summary)
    return {"success": True, "status": "success", "message": summary, "emails": emails}


def _handle_extract_actions(email_id, email_pass, user, command: str = "") -> Dict[str, Any]:
    pasted = _extract_pasted_email_content(command)
    if pasted:
        items = extract_action_items(pasted)
        if items:
            msg = "The action items from the email are: " + "; ".join(items) + "."
        else:
            msg = "No specific action items found in the provided email text."
        speak(msg)
        return {"success": True, "status": "success", "action_items": items, "message": msg}
    if not email_id or not email_pass:
        return _no_creds_error(user)
    emails, meta = fetch_latest_emails_with_status(limit=5, email_id=email_id, email_pass=email_pass)
    if not meta.get("success"):
        return {"success": False, "status": "error", "message": f"Email access failed: {meta.get('error')}."}
    if not emails:
        return {"success": True, "status": "success", "message": "No recent emails to analyze."}
    all_items = []
    for e in emails[:5]:
        body = e.get("body", "")
        items = extract_action_items(f"Subject: {e.get('subject')}\n\n{body}")
        for it in items:
            all_items.append(f"{it} (from '{e.get('subject')}')")
    if all_items:
        msg = f"Found {len(all_items)} action item(s) / deadline(s): " + "; ".join(all_items[:5]) + "."
    else:
        msg = "No specific action items or deadlines found in your recent emails."
    speak(msg)
    return {"success": True, "status": "success", "action_items": all_items, "message": msg}



def _handle_explain_email(email_id, email_pass, user, command: str = "") -> Dict[str, Any]:
    pasted = _extract_pasted_email_content(command)
    if pasted:
        explanation = explain_email_simple(pasted)
        speak(explanation)
        return {"success": True, "status": "success", "message": explanation}
    if not email_id or not email_pass:
        return _no_creds_error(user)
    emails, meta = fetch_latest_emails_with_status(limit=1, email_id=email_id, email_pass=email_pass)
    if not meta.get("success"):
        return {"success": False, "status": "error", "message": f"Email access failed: {meta.get('error')}."}
    if not emails:
        return {"success": True, "status": "success", "message": "No email to explain."}
    e = emails[0]
    explanation = explain_email_simple(f"From: {e.get('sender')}\nSubject: {e.get('subject')}\n\n{e.get('body', '')}")
    speak(explanation)
    return {"success": True, "status": "success", "message": explanation}


def _handle_compose_with_review(
    command: str,
    parsed: Dict[str, Any],
    user: str,
    user_id: Any = None
) -> Dict[str, Any]:
    """
    Full compose workflow:
    1. Resolve attachment
    2. Resolve recipient (ambiguity check)
    3. AI-generate subject + body
    4. Show review/edit popup (MANDATORY)
    5. Only send if user explicitly approves in the popup
    6. Report verified outcome
    """
    email_id, email_pass = get_user_email(user)
    if not email_id or not email_pass:
        return _no_creds_error(user)

    # ── Attachment resolution ────────────────────────────────────────────────
    attachment_term = parsed.get("attachment_term")
    resolved_attachment: Optional[str] = None

    if attachment_term:
        m_file = re.search(
            r'\b([a-zA-Z0-9_\-.]+\.(?:pdf|docx|xlsx|pptx|txt|csv|png|jpg|jpeg|zip))\b',
            command, re.I
        )
        if m_file:
            explicit_name = m_file.group(1)
            if os.path.isabs(explicit_name) and os.path.isfile(explicit_name):
                resolved_attachment = explicit_name
            else:
                cands = search_user_files_for_email(explicit_name)
                if cands:
                    resolved_attachment = cands[0]
                else:
                    return {
                        "success": False, "status": "error",
                        "message": f"Cannot find attachment '{explicit_name}'. Please verify the filename."
                    }
        else:
            # Contextual reference ("the pdf", "that file", "the document I just created")
            if re.search(r'\b(it|that\s+file|this\s+file|the\s+file|the\s+document\s+i\s+just\s+created)\b',
                         command, re.I):
                try:
                    from extensions.context_manager import get_manager
                    art = get_manager().get_last_user_artifact(user_id=user_id)
                    if art and art.get("path") and os.path.isfile(art["path"]):
                        resolved_attachment = art["path"]
                    else:
                        return {
                            "success": False, "status": "error",
                            "message": "No recent file found in conversation context to attach."
                        }
                except Exception:
                    pass
            elif attachment_term and not attachment_term.startswith("the "):
                cands = search_user_files_for_email(attachment_term)
                if len(cands) == 1:
                    resolved_attachment = cands[0]
                elif len(cands) > 1:
                    names = [os.path.basename(c) for c in cands[:5]]
                    return {
                        "success": False, "status": "clarification",
                        "needs_clarification": True,
                        "message": f"I found multiple matching files: {', '.join(names)}. Which one should I attach?"
                    }

    # ── Recipient resolution ─────────────────────────────────────────────────
    recipient_raw = parsed.get("recipient_raw")

    # Try to extract from "to <name_or_email>" in command if not caught by parser
    if not recipient_raw:
        m_to = re.search(r'\bto\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-.]+|[A-Za-z][A-Za-z\s]+?)(?:\s+(?:about|and|saying|regarding|re:)|[,.]|$)',
                         command, re.I)
        if m_to:
            candidate = m_to.group(1).strip().rstrip('.,?!')
            if 1 < len(candidate) <= 60:
                recipient_raw = candidate

    if not recipient_raw:
        return {
            "success": False, "status": "clarification",
            "needs_clarification": True,
            "message": "Who should I send this email to? Please specify the recipient."
        }

    rec_result = resolve_recipient_detailed(recipient_raw)

    if rec_result["status"] == "ambiguous":
        candidates = rec_result.get("candidates", [])
        names = ", ".join(f"{c['name']} ({c['email']})" for c in candidates[:4])
        tone = parsed.get("tone", "professional")
        _pending_email_sessions[user] = {
            "status": STATE_EMAIL_RECIPIENT_RESOLUTION,
            "session_id": str(uuid.uuid4()),
            "user_id": user,
            "recipient_raw": recipient_raw,
            "candidates": candidates,
            "attachments": [resolved_attachment] if resolved_attachment else [],
            "tone": tone,
            "timestamp": datetime.datetime.now().isoformat()
        }
        msg = f"'{recipient_raw}' matches multiple contacts: {names}. Which one did you mean?"
        speak(msg)
        return {
            "success": False, "status": "clarification",
            "needs_clarification": True,
            "recipient_candidates": candidates,
            "message": msg
        }

    if rec_result["status"] in ("unverified", "missing_email"):
        cand_email = rec_result.get("email") or ""
        tone = parsed.get("tone", "professional")
        _pending_email_sessions[user] = {
            "status": STATE_UNVERIFIED_RECIPIENT,
            "session_id": str(uuid.uuid4()),
            "user_id": user,
            "recipient_raw": recipient_raw,
            "recipient_name": rec_result.get("name") or recipient_raw,
            "attachments": [resolved_attachment] if resolved_attachment else [],
            "tone": tone,
            "timestamp": datetime.datetime.now().isoformat()
        }
        msg = f"The contact '{recipient_raw}' has an unverified placeholder email address ({cand_email}). Please specify a valid email address."
        speak(msg)
        return {
            "success": False, "status": "clarification",
            "needs_clarification": True,
            "message": msg
        }

    if rec_result["status"] == "invalid_email":
        msg = f"'{recipient_raw}' is not a valid email address format. Please specify a valid recipient."
        speak(msg)
        return {
            "success": False, "status": "clarification",
            "needs_clarification": True,
            "message": msg
        }

    if rec_result["status"] == "not_found":
        return {
            "success": False, "status": "error",
            "message": (f"I couldn't find a contact named '{recipient_raw}'. "
                        "Please add them to your contacts first or use their email address directly.")
        }

    to_email = rec_result["email"]
    recipient_name = rec_result.get("name") or recipient_raw

    # ── Voice Dictation Workflow: Enter RECORDING_EMAIL_MESSAGE ──────────────
    # Friday asks: "Sure, I'm listening. Say your message, then say 'stop message' when you're finished."
    tone = parsed.get("tone", "professional")
    body_raw = parsed.get("body_raw")

    has_stop = False
    if body_raw:
        has_stop = bool(re.search(
            r'\b(?:stop\s+message|stop\s+dictation|end\s+message|finish\s+message|finished\s+message|done\s+message)\b',
            body_raw, re.I
        ))

    if not body_raw or not has_stop:
        initial_buffer = [body_raw.strip()] if (body_raw and body_raw.strip()) else []
        session_id = str(uuid.uuid4())
        _pending_email_sessions[user] = {
            "status": STATE_RECORDING_EMAIL_MESSAGE,
            "session_id": session_id,
            "user_id": user,
            "recipient": to_email,
            "recipient_name": recipient_name,
            "message_buffer": initial_buffer,
            "last_transcript": initial_buffer[0] if initial_buffer else "",
            "attachments": [resolved_attachment] if resolved_attachment else [],
            "tone": tone,
            "timestamp": datetime.datetime.now().isoformat()
        }
        prompt_msg = "Sure, I'm listening. Say your message, then say 'stop message' when you're finished."
        speak(prompt_msg)
        return {
            "success": True,
            "status": "recording_email_message",
            "session_id": session_id,
            "recipient": to_email,
            "recipient_name": recipient_name,
            "message": prompt_msg
        }

    # If body_raw already has 'stop message' in the initial command:
    # Strip the stop message phrase and continue to restructure immediately!
    dictated_clean = re.sub(
        r'\b(?:stop\s+message|stop\s+dictation|end\s+message|finish\s+message|finished\s+message|done\s+message)\b',
        '', body_raw, flags=re.I
    ).strip()
    dictated_clean = re.sub(r'^[.,\s]+|[.,\s]+$', '', dictated_clean).strip()
    body_raw = dictated_clean or body_raw

    # ── AI draft generation ──────────────────────────────────────────────────
    tone = parsed.get("tone", "professional")
    speak(f"Preparing a professional email for {recipient_name}...")
    subject, body = rewrite_professional(body_raw, recipient_name, tone=tone)
    attachments = [resolved_attachment] if resolved_attachment else []

    # ── Mandatory review/edit popup ──────────────────────────────────────────
    speak("Your email is ready. Please review it in the popup window.")
    edited = show_email_editor(
        subject=subject,
        body=body,
        recipient_email=to_email,
        sender_email=email_id,
        sender_pass=email_pass,
        attachments=attachments
    )

    action_taken = edited.get("action", "dismissed")
    confirmed = edited.get("confirmed", False)

    if action_taken == "cancel":
        _pending_email_sessions.pop(user, None)
        speak("Email cancelled.")
        return {"success": False, "status": "cancelled",
                "message": "Email cancelled by user."}

    if action_taken == "save_draft":
        _pending_email_sessions.pop(user, None)
        draft_id = save_draft(user, {
            "recipient": edited.get("recipient", to_email),
            "subject": edited.get("subject", subject),
            "body": edited.get("body", body),
            "attachments": edited.get("attachments", attachments),
            "cc": edited.get("cc") or "",
            "bcc": edited.get("bcc") or ""
        })
        if draft_id:
            speak("Draft saved.")
            return {
                "success": True,
                "status": "draft_saved",
                "draft_id": draft_id,
                "message": f"Email draft saved (ID: {draft_id}). Say 'show my drafts' when you want to send or edit it.",
                "draft": {
                    "id": draft_id,
                    "to": edited.get("recipient", to_email),
                    "subject": edited.get("subject", subject),
                    "body": edited.get("body", body),
                    "attachments": edited.get("attachments", attachments)
                }
            }
        speak("Failed to save draft.")
        return {"success": False, "status": "error", "message": "Failed to persist draft."}

    # If send was triggered from popup directly
    if edited.get("sent"):
        _pending_email_sessions.pop(user, None)
        att_note = f" with {len(edited.get('attachments', []))} attachment(s)" if edited.get("attachments") else ""
        msg = f"Email sent to {edited.get('recipient', to_email)}{att_note}."
        speak(msg)
        invalidate_cache(email_id)
        return {"success": True, "status": "success",
                "recipient": edited.get("recipient", to_email),
                "subject": edited.get("subject", subject),
                "message": msg}

    # If send was approved in popup
    if action_taken == "send" or (confirmed and action_taken == "approved"):
        updated_to = edited.get("recipient", to_email)
        updated_subject = edited.get("subject", subject)
        updated_body = edited.get("body", body)
        updated_attachments = edited.get("attachments", attachments)
        updated_cc = edited.get("cc") or None
        updated_bcc = edited.get("bcc") or None

        send_res = send_email(
            to_email=updated_to,
            subject=updated_subject,
            body=updated_body,
            email_id=email_id,
            email_pass=email_pass,
            attachments=updated_attachments,
            cc=updated_cc,
            bcc=updated_bcc
        )
        if send_res:
            _pending_email_sessions.pop(user, None)
            att_note = f" with {send_res.get('attachments_count', 0)} attachment(s)" if send_res.get("attachments_count") else ""
            msg = f"Email sent to {updated_to}{att_note}."
            speak(msg)
            invalidate_cache(email_id)
            return {"success": True, "status": "success",
                    "recipient": updated_to,
                    "subject": updated_subject,
                    "message": msg}
        else:
            _pending_email_sessions[user] = {
                "recipient": updated_to,
                "recipient_name": recipient_name,
                "subject": updated_subject,
                "body": updated_body,
                "attachments": updated_attachments,
                "cc": updated_cc or "",
                "bcc": updated_bcc or "",
                "status": "PENDING_CONFIRMATION",
                "timestamp": datetime.datetime.now().isoformat()
            }
            spoken_err = _format_spoken_error(send_res, context="send", draft_retained=True)
            speak(spoken_err)
            return {"success": False, "status": send_res.get("status", "error"),
                    "message": send_res.get("message", "Email sending failed.")}

    # Review popup closed or dismissed without sending -> keep draft pending confirmation
    final_subject = edited.get("subject", subject)
    final_body = edited.get("body", body)
    _pending_email_sessions[user] = {
        "id": f"draft_{int(time.time())}",
        "recipient": edited.get("recipient", to_email),
        "recipient_name": recipient_name,
        "subject": final_subject,
        "body": final_body,
        "attachments": edited.get("attachments", attachments),
        "cc": edited.get("cc") or "",
        "bcc": edited.get("bcc") or "",
        "version": 1,
        "status": "PENDING_CONFIRMATION",
        "timestamp": datetime.datetime.now().isoformat()
    }
    # Exactly ONE final send confirmation question (Step 6)
    msg = f"Would you like me to send this email to {recipient_name} with the subject '{final_subject}'?"
    speak(msg)
    return {
        "success": True,
        "status": "pending_confirmation",
        "recipient": edited.get("recipient", to_email),
        "recipient_name": recipient_name,
        "subject": final_subject,
        "body": final_body,
        "message": msg,
        "draft": _pending_email_sessions[user]
    }


def _handle_reply(email_id, email_pass, user: str, reply_all: bool = False) -> Dict[str, Any]:
    """Reply or reply-all to the most recently fetched email with mandatory review."""
    if not email_id or not email_pass:
        return _no_creds_error(user)

    latest = get_latest_email(email_id=email_id, email_pass=email_pass)
    if not latest:
        return {"success": False, "status": "error",
                "message": "No emails found to reply to."}

    sender_str = latest.get("sender", "")
    to_str = latest.get("to", "")
    cc_str = latest.get("cc", "")

    # Parse primary reply recipient from From or Reply-To
    from_addrs = email.utils.getaddresses([sender_str])
    primary_to = latest.get("reply_to") or (from_addrs[0][1] if from_addrs and from_addrs[0][1] else sender_str)

    # Reply-All: extract To and Cc headers, exclude self and primary_to, deduplicate case-insensitively
    reply_cc = None
    if reply_all:
        all_raw = email.utils.getaddresses([sender_str, to_str, cc_str])
        user_email_norm = (email_id or "").strip().lower()
        primary_norm = primary_to.strip().lower()
        seen = {user_email_norm, primary_norm}
        cc_list = []
        for name, addr in all_raw:
            addr_clean = addr.strip().lower()
            if addr_clean and addr_clean not in seen:
                seen.add(addr_clean)
                cc_list.append(addr.strip())
        if cc_list:
            reply_cc = ", ".join(cc_list)

    speak(f"Generating {'reply all' if reply_all else 'reply'} to {primary_to} regarding '{latest.get('subject')}'...")
    reply_body = generate_reply(
        f"From: {latest.get('sender')}\nSubject: {latest.get('subject')}\n\n{latest.get('body', '')}"
    )

    reply_subject = latest.get("subject", "")
    if not reply_subject.lower().startswith("re:"):
        reply_subject = f"Re: {reply_subject}"

    edited = show_email_editor(
        subject=reply_subject,
        body=reply_body,
        recipient_email=primary_to,
        sender_email=email_id,
        sender_pass=email_pass,
        cc=reply_cc
    )

    if not edited.get("confirmed") or edited.get("action") == "cancel":
        speak("Reply cancelled.")
        return {"success": False, "status": "cancelled", "message": "Reply cancelled."}

    if edited.get("action") == "save_draft":
        draft_id = save_draft(user, {
            "recipient": edited.get("recipient", primary_to),
            "cc": edited.get("cc", reply_cc) or "",
            "subject": edited.get("subject", reply_subject),
            "body": edited.get("body", reply_body)
        })
        if draft_id:
            speak("Reply draft saved.")
            return {"success": True, "status": "draft_saved", "draft_id": draft_id, "message": "Reply draft saved."}
        return {"success": False, "status": "error", "message": "Failed to persist draft."}

    if edited.get("sent"):
        invalidate_cache(email_id)
        return {"success": True, "status": "success", "message": f"Reply sent to {edited.get('recipient', primary_to)}."}

    # Fallback send
    send_res = send_email(
        to_email=edited.get("recipient", primary_to),
        subject=edited.get("subject", reply_subject),
        body=edited.get("body", reply_body),
        email_id=email_id,
        email_pass=email_pass,
        cc=edited.get("cc", reply_cc) or None,
        in_reply_to=latest.get("message_id"),
        references=latest.get("references") or latest.get("message_id")
    )
    if send_res:
        invalidate_cache(email_id)
        speak("Reply sent.")
        return {"success": True, "status": "success",
                "message": f"Reply sent to {edited.get('recipient', primary_to)}."}
    spoken_err = _format_spoken_error(send_res, context="reply", draft_retained=False)
    speak(spoken_err)
    return {"success": False, "status": "error",
            "message": send_res.get("message", "Failed to send reply.")}


def _handle_forward(command: str, parsed: Dict[str, Any], email_id, email_pass, user: str) -> Dict[str, Any]:
    """Forward the latest email to a resolved recipient with review."""
    if not email_id or not email_pass:
        return _no_creds_error(user)

    latest = get_latest_email(email_id=email_id, email_pass=email_pass)
    if not latest:
        return {"success": False, "status": "error",
                "message": "No emails found to forward."}

    recipient_raw = parsed.get("recipient_raw")
    if not recipient_raw:
        m_to = re.search(r'\bto\s+([A-Za-z][A-Za-z\s]+?)(?:\s+(?:about|and)|[,.]|$)', command, re.I)
        if m_to:
            recipient_raw = m_to.group(1).strip().rstrip('.,?!')

    if not recipient_raw:
        return {
            "success": False, "status": "clarification",
            "needs_clarification": True,
            "message": "Who should I forward this email to?"
        }

    rec_result = resolve_recipient_detailed(recipient_raw)
    if rec_result["status"] == "ambiguous":
        cands = ", ".join(f"{c['name']} ({c['email']})" for c in rec_result.get("candidates", [])[:3])
        return {"success": False, "status": "clarification",
                "message": f"'{recipient_raw}' matches: {cands}. Which one?"}
    if rec_result["status"] == "not_found":
        return {"success": False, "status": "error",
                "message": f"Could not find contact '{recipient_raw}'."}

    fwd_to = rec_result["email"]
    fwd_subject = latest.get("subject", "")
    if not fwd_subject.lower().startswith("fwd:"):
        fwd_subject = f"Fwd: {fwd_subject}"
    fwd_body = (f"---------- Forwarded Message ----------\n"
                f"From: {latest.get('sender')}\n"
                f"Subject: {latest.get('subject')}\n"
                f"Date: {latest.get('date')}\n\n"
                f"{latest.get('body', '')}")

    edited = show_email_editor(
        subject=fwd_subject,
        body=fwd_body,
        recipient_email=fwd_to,
        sender_email=email_id,
        sender_pass=email_pass
    )

    if not edited.get("confirmed") or edited.get("action") == "cancel":
        speak("Forward cancelled.")
        return {"success": False, "status": "cancelled", "message": "Forward cancelled."}

    if edited.get("sent"):
        invalidate_cache(email_id)
        return {"success": True, "status": "success", "message": f"Email forwarded to {fwd_to}."}

    send_res = send_email(
        to_email=edited.get("recipient", fwd_to),
        subject=edited.get("subject", fwd_subject),
        body=edited.get("body", fwd_body),
        email_id=email_id,
        email_pass=email_pass
    )
    if send_res:
        invalidate_cache(email_id)
        speak("Email forwarded.")
        return {"success": True, "status": "success", "message": f"Email forwarded to {fwd_to}."}
    return {"success": False, "status": "error",
            "message": send_res.get("message", "Forward failed.")}


def _handle_organize(email_id, email_pass, user: str, action: str, command: str) -> Dict[str, Any]:
    """Apply organization action to the latest email or a specified one."""
    if not email_id or not email_pass:
        return _no_creds_error(user)

    # Require explicit confirmation for destructive actions
    if action in ("trash",):
        speak(f"Are you sure you want to move the latest email to Trash? Say yes or no.")
        if _audio_available():
            confirm = listen().lower()
            if "yes" not in confirm and "confirm" not in confirm:
                return {"success": False, "status": "cancelled", "message": "Operation cancelled."}

    emails, meta = fetch_latest_emails_with_status(limit=1, email_id=email_id, email_pass=email_pass)
    if not meta.get("success") or not emails:
        return {"success": False, "status": "error",
                "message": "Could not fetch email to organize."}

    e = emails[0]
    email_uid = e.get("id")
    if not email_uid:
        return {"success": False, "status": "error", "message": "Could not identify email ID."}

    result = organize_email_message(email_uid, action, email_id, email_pass)
    if result.get("success"):
        speak(result.get("message", "Done."))
    return result


def _handle_add_contact() -> Dict[str, Any]:
    """Interactive contact addition."""
    from .email_utils import get_text_input
    speak("Please enter the contact details in the popup.")
    name = get_text_input("New Contact", "Enter contact name:")
    if not name:
        return {"success": False, "status": "cancelled", "message": "Contact addition cancelled."}
    email_addr = get_text_input("New Contact", f"Enter email for {name}:")
    if email_addr and save_contact(name, email_addr):
        speak(f"Contact {name} saved.")
        return {"success": True, "status": "success", "message": f"Contact {name} added successfully."}
    return {"success": False, "status": "error", "message": "Could not save contact."}


# ──────────────────────────────────────────────────────────────────
# Draft, Folder, and Date Specialized Handlers
# ──────────────────────────────────────────────────────────────────

def _handle_draft_list(user: str) -> Dict[str, Any]:
    """Lists all saved drafts for the user with useful metadata."""
    drafts = list_drafts(user)
    if not drafts:
        msg = "You have no saved email drafts."
        speak(msg)
        return {"success": True, "status": "success", "drafts": [], "count": 0, "message": msg}

    summaries = []
    for i, d in enumerate(drafts, start=1):
        to_rec = d.get("recipient") or d.get("to") or "No recipient"
        subj = d.get("subject") or "(No subject)"
        d_id = d.get("id", f"draft_{i}")
        saved = d.get("saved_at") or d.get("updated_at") or "recently"
        summaries.append(f"Draft {i} [{d_id}]: To {to_rec}, Subject '{subj}' (Saved: {saved})")

    msg = f"You have {len(drafts)} saved draft(s):\n" + "\n".join(summaries)
    speak(f"You have {len(drafts)} saved email draft(s).")
    return {"success": True, "status": "success", "drafts": drafts, "count": len(drafts), "message": msg}


def _handle_draft_edit(command: str, user: str, draft_ref: Optional[str] = None) -> Dict[str, Any]:
    """Opens a saved draft in the review/editor popup for modification."""
    email_id, email_pass = get_user_email(user)

    if not draft_ref:
        m = _RE_DRAFT_EDIT.search(command)
        draft_ref = m.group(1) if m and m.group(1) else "1"

    draft = get_draft(user, draft_ref)
    if not draft:
        msg = f"Draft '{draft_ref}' not found."
        speak(msg)
        return {"success": False, "status": "error", "message": msg}

    speak(f"Opening draft for {draft.get('recipient') or 'editing'}...")
    edited = show_email_editor(
        subject=draft.get("subject", ""),
        body=draft.get("body", ""),
        recipient_email=draft.get("recipient") or draft.get("to") or "",
        sender_email=email_id,
        sender_pass=email_pass,
        cc=draft.get("cc") or "",
        bcc=draft.get("bcc") or "",
        attachments=draft.get("attachments") or []
    )

    action_taken = edited.get("action", "cancel")
    if action_taken == "cancel" or not edited.get("confirmed"):
        return {"success": False, "status": "cancelled", "message": "Draft editing cancelled."}

    if action_taken == "save_draft":
        draft_update = {
            "id": draft.get("id"),
            "recipient": edited.get("recipient"),
            "cc": edited.get("cc"),
            "bcc": edited.get("bcc"),
            "subject": edited.get("subject"),
            "body": edited.get("body"),
            "attachments": edited.get("attachments", [])
        }
        res_id = save_draft(user, draft_update)
        if res_id:
            speak("Draft updated.")
            return {"success": True, "status": "draft_saved", "draft_id": res_id, "message": "Draft updated."}
        return {"success": False, "status": "error", "message": "Failed to update draft."}

    if edited.get("sent") or action_taken == "send":
        delete_draft(user, draft.get("id"))
        if email_id:
            invalidate_cache(email_id)
        msg = f"Draft sent to {edited.get('recipient')}."
        speak(msg)
        return {"success": True, "status": "success", "message": msg}

    return {"success": False, "status": "cancelled", "message": "Operation cancelled."}


def _handle_draft_send(command: str, user: str, draft_ref: Optional[str] = None) -> Dict[str, Any]:
    """
    Sends a selected draft ONLY after showing the user the final editable review
    and receiving explicit confirmation.
    """
    email_id, email_pass = get_user_email(user)
    if not email_id or not email_pass:
        return _no_creds_error(user)

    if not draft_ref:
        m = _RE_DRAFT_SEND.search(command)
        draft_ref = m.group(1) if m and m.group(1) else "1"

    draft = get_draft(user, draft_ref)
    if not draft:
        msg = f"Draft '{draft_ref}' not found."
        speak(msg)
        return {"success": False, "status": "error", "message": msg}

    target_recipient = draft.get("recipient") or draft.get("to")
    if not target_recipient:
        return {"success": False, "status": "error", "message": "Draft does not have a valid recipient. Please edit it first."}

    speak(f"Please review the draft before sending to {target_recipient}.")
    edited = show_email_editor(
        subject=draft.get("subject", ""),
        body=draft.get("body", ""),
        recipient_email=target_recipient,
        sender_email=email_id,
        sender_pass=email_pass,
        cc=draft.get("cc") or "",
        bcc=draft.get("bcc") or "",
        attachments=draft.get("attachments") or []
    )

    if not edited.get("confirmed") or edited.get("action") == "cancel":
        speak("Draft send cancelled.")
        return {"success": False, "status": "cancelled", "message": "Draft send cancelled."}

    if edited.get("sent"):
        delete_draft(user, draft.get("id"))
        invalidate_cache(email_id)
        msg = f"Draft successfully sent to {edited.get('recipient', target_recipient)}."
        speak(msg)
        return {"success": True, "status": "success", "message": msg}

    # If approved via non-GUI send
    send_res = send_email(
        to_email=edited.get("recipient", target_recipient),
        subject=edited.get("subject", draft.get("subject", "")),
        body=edited.get("body", draft.get("body", "")),
        email_id=email_id,
        email_pass=email_pass,
        attachments=edited.get("attachments", draft.get("attachments", [])),
        cc=edited.get("cc") or None,
        bcc=edited.get("bcc") or None
    )

    if send_res:
        delete_draft(user, draft.get("id"))
        invalidate_cache(email_id)
        msg = f"Draft successfully sent to {edited.get('recipient', target_recipient)}."
        speak(msg)
        return {"success": True, "status": "success", "message": msg}

    return {"success": False, "status": "error", "message": send_res.get("message", "Failed to send draft.")}


def _handle_draft_delete(command: str, user: str, draft_ref: Optional[str] = None) -> Dict[str, Any]:
    """Deletes a selected draft with confirmation."""
    if not draft_ref:
        m = _RE_DRAFT_DELETE.search(command)
        draft_ref = m.group(1) if m and m.group(1) else "1"

    draft = get_draft(user, draft_ref)
    if not draft:
        msg = f"Draft '{draft_ref}' not found."
        speak(msg)
        return {"success": False, "status": "error", "message": msg}

    deleted = delete_draft(user, draft.get("id"))
    if deleted:
        msg = f"Draft {draft_ref} ('{draft.get('subject', '(No Subject)')}') deleted successfully."
        speak(msg)
        return {"success": True, "status": "success", "message": msg}
    return {"success": False, "status": "error", "message": f"Could not delete draft {draft_ref}."}


def _handle_folder_list(email_id, email_pass, user: str) -> Dict[str, Any]:
    """Discovers and lists available mailboxes/folders for the account."""
    if not email_id or not email_pass:
        return _no_creds_error(user)

    folders, meta = list_mailboxes(email_id, email_pass)
    if not meta.get("success"):
        return {"success": False, "status": "error", "message": f"Could not list folders: {meta.get('error')}"}

    names = [f"{f['display_name']} ({f['role']})" for f in folders]
    msg = f"Available folders ({len(folders)}): " + ", ".join(names)
    speak(f"You have {len(folders)} mailboxes available.")
    return {"success": True, "status": "success", "folders": folders, "count": len(folders), "message": msg}


def _handle_folder_check(email_id, email_pass, user: str, folder_target: str, query: Optional[str] = None) -> Dict[str, Any]:
    """Checks emails inside a specific folder."""
    if not email_id or not email_pass:
        return _no_creds_error(user)

    actual_folder = find_folder_by_role(folder_target, email_id, email_pass) or folder_target
    emails, meta = fetch_latest_emails_with_status(
        limit=10,
        email_id=email_id,
        email_pass=email_pass,
        folder=actual_folder,
        search_query=query
    )
    if not meta.get("success"):
        return {"success": False, "status": "error", "message": f"Failed to check folder '{folder_target}': {meta.get('error')}"}

    if emails:
        summaries = [f"From {e.get('sender')}: '{e.get('subject')}'" for e in emails[:5]]
        msg = f"Found {len(emails)} email(s) in {folder_target}. " + "; ".join(summaries) + "."
        return {"success": True, "status": "success", "emails": emails, "folder": actual_folder, "message": msg}
    return {"success": True, "status": "success", "emails": [], "folder": actual_folder, "message": f"No emails found in {folder_target}."}


def _handle_move_email(email_id, email_pass, user: str, dest_folder: str, command: str = "") -> Dict[str, Any]:
    """Moves an email to a destination folder."""
    if not email_id or not email_pass:
        return _no_creds_error(user)

    actual_dest = find_folder_by_role(dest_folder, email_id, email_pass) or dest_folder

    emails, meta = fetch_latest_emails_with_status(limit=1, email_id=email_id, email_pass=email_pass)
    if not meta.get("success") or not emails:
        return {"success": False, "status": "error", "message": "No email found to move."}

    e = emails[0]
    email_uid = e.get("id")
    if not email_uid:
        return {"success": False, "status": "error", "message": "Could not identify email ID."}

    res = move_email_message(email_uid, actual_dest, email_id, email_pass)
    if res.get("success"):
        speak(f"Email moved to {dest_folder}.")
    return res


def _handle_date_query(
    email_id, email_pass, user: str,
    criterion: str = "ALL",
    date_from: Optional[datetime.date] = None,
    date_to: Optional[datetime.date] = None,
    label: str = "specified date"
) -> Dict[str, Any]:
    """Fetches emails matching specific date boundaries."""
    if not email_id or not email_pass:
        return _no_creds_error(user)

    emails, meta = fetch_latest_emails_with_status(
        limit=20,
        email_id=email_id,
        email_pass=email_pass,
        criterion=criterion,
        date_from=date_from,
        date_to=date_to
    )
    if not meta.get("success"):
        return {"success": False, "status": "error", "message": f"Email date search failed: {meta.get('error')}."}

    if emails:
        summaries = [f"From {e.get('sender')}: '{e.get('subject')}' ({e.get('date', '')})" for e in emails[:5]]
        msg = f"Found {len(emails)} email(s) from {label}. " + "; ".join(summaries) + "."
        return {"success": True, "status": "success", "emails": emails, "count": len(emails), "message": msg}
    return {"success": True, "status": "success", "emails": [], "count": 0, "message": f"No emails found from {label}."}


# ──────────────────────────────────────────────────────────────────
# Interactive (audio) handlers — preserved from original
# ──────────────────────────────────────────────────────────────────

def _handle_send_interactive(initial_recipient, sender_email, sender_pass):
    if initial_recipient:
        recipient_name = initial_recipient
    else:
        if not _audio_available():
            speak("Email send requires voice input, but audio hardware is unavailable.")
            return
        speak("Who do you want to send the email to?")
        recipient_name = listen()

    if not recipient_name:
        return

    rec_result = resolve_recipient_detailed(recipient_name)
    recipient_email = None
    if rec_result["status"] == "resolved":
        recipient_email = rec_result["email"]
        recipient_name = rec_result.get("name") or recipient_name
    else:
        speak(f"I don't have an email for {recipient_name}. Please type it in the popup.")
        from .email_utils import get_text_input
        recipient_email = get_text_input("Contact Email", f"Enter email for {recipient_name}:")
        if recipient_email:
            save_contact(recipient_name, recipient_email)

    if not recipient_email:
        speak("Couldn't get a valid recipient email.")
        return

    if not _audio_available():
        speak("Audio hardware unavailable. Cannot capture message voice input.")
        return

    speak("Start speaking your message. Say 'stop message' when done.")
    raw_text = listen_continuous("stop message")
    if not raw_text:
        speak("No message captured.")
        return

    speak("Processing your message...")
    subject, body = generate_email_structure(raw_text, recipient_name)

    speak("Your email is ready. Please review it in the popup.")
    edited = show_email_editor(
        subject=subject, body=body,
        recipient_email=recipient_email,
        sender_email=sender_email, sender_pass=sender_pass
    )

    if not edited.get("confirmed") or edited.get("action") == "cancel":
        speak("Email cancelled.")
        return
    if edited.get("sent"):
        speak("Email sent successfully.")
        return
    if edited.get("action") == "save_draft":
        speak("Draft saved.")
        return
    # If approved, send
    res = send_email(
        to_email=edited.get("recipient", recipient_email),
        subject=edited.get("subject", subject),
        body=edited.get("body", body),
        email_id=sender_email,
        email_pass=sender_pass,
        attachments=edited.get("attachments")
    )
    if res:
        speak("Email sent successfully.")
    else:
        speak(_format_spoken_error(res, context="send", draft_retained=False))


def _handle_check_inbox_interactive(email_id, email_pass):
    speak("Fetching your latest emails...")
    emails = fetch_latest_emails(limit=5, email_id=email_id, email_pass=email_pass)
    if not emails:
        speak("Your inbox is empty or I couldn't access it.")
        return
    speak(f"You have {len(emails)} recent emails.")
    for i, e in enumerate(emails):
        speak(f"Email {i+1} is from {e.get('sender')} regarding {e.get('subject')}")


def _handle_summarize_interactive(email_id, email_pass):
    speak("Working on a summary of your latest emails...")
    emails = fetch_latest_emails(limit=10, email_id=email_id, email_pass=email_pass)
    summary = generate_summary(emails)
    speak(summary)


def _handle_read_interactive(email_id, email_pass):
    speak("Which email number should I read?")
    num_text = listen()
    try:
        idx = int(''.join(filter(str.isdigit, num_text))) - 1
        emails = fetch_latest_emails(limit=10, email_id=email_id, email_pass=email_pass)
        if 0 <= idx < len(emails):
            e = emails[idx]
            speak(f"From: {e.get('sender')}")
            speak(f"Subject: {e.get('subject')}")
            speak("Content:")
            speak(e.get("body", "(No body)"))
        else:
            speak("I couldn't find that email.")
    except Exception:
        speak("I didn't catch the email number.")


def _handle_reply_interactive(email_id, email_pass):
    speak("Fetching the latest email to reply to...")
    latest = get_latest_email(email_id=email_id, email_pass=email_pass)
    if not latest:
        speak("No emails found to reply to.")
        return
    speak(f"Replying to {latest.get('sender')} regarding {latest.get('subject')}")
    speak("Generating professional reply...")
    reply_body = generate_reply(
        f"From: {latest.get('sender')}\nSubject: {latest.get('subject')}\n\n{latest.get('body', '')}"
    )
    sender_str = latest.get("sender", "")
    m_addr = re.search(r'<([^>]+)>', sender_str)
    reply_to_email = m_addr.group(1) if m_addr else sender_str
    reply_subject = latest.get("subject", "")
    if not reply_subject.lower().startswith("re:"):
        reply_subject = f"Re: {reply_subject}"

    speak("Please review the reply in the popup.")
    edited = show_email_editor(
        subject=reply_subject, body=reply_body,
        recipient_email=reply_to_email,
        sender_email=email_id, sender_pass=email_pass
    )
    if not edited.get("confirmed") or edited.get("action") == "cancel":
        speak("Reply cancelled.")
        return
    if edited.get("sent"):
        speak("Reply sent successfully.")
        return
    res = send_email(
        to_email=edited.get("recipient", reply_to_email),
        subject=edited.get("subject", reply_subject),
        body=edited.get("body", reply_body),
        email_id=email_id, email_pass=email_pass,
        in_reply_to=latest.get("message_id")
    )
    if res:
        speak("Reply sent successfully.")
    else:
        speak(_format_spoken_error(res, context="reply", draft_retained=False))


# ──────────────────────────────────────────────────────────────────
# Programmatic API functions (called by router / UI / dashboard)
# ──────────────────────────────────────────────────────────────────

def send_email_direct(
    recipient: str,
    subject: str,
    body: str,
    attachments: Optional[List[str]] = None,
    user: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None
) -> Dict[str, Any]:
    """
    Non-interactive programmatic send. Resolves contact, validates attachments,
    dispatches via SMTP. Does NOT trigger GUI review — callers invoking this
    from the router have already passed through the review workflow.
    """
    try:
        current_u = user or get_current_user()
        email_id, email_pass = get_user_email(current_u)
        if not email_id or not email_pass:
            return _no_creds_error(current_u)

        # Resolve contact name to email if needed
        to_addr = recipient.strip()
        if "@" not in to_addr:
            rec_result = resolve_recipient_detailed(to_addr)
            if rec_result["status"] == "resolved":
                to_addr = rec_result["email"]
            elif rec_result["status"] == "ambiguous":
                candidates = ", ".join(c["name"] for c in rec_result.get("candidates", [])[:3])
                return {
                    "success": False,
                    "status": "clarification",
                    "message": f"'{recipient}' matches multiple contacts: {candidates}. Please specify."
                }
            else:
                return {
                    "success": False,
                    "status": "error",
                    "message": f"Could not resolve recipient '{recipient}' to an email address."
                }

        # Validate attachments
        valid_attachments: List[str] = []
        if attachments:
            for att in attachments:
                if not att:
                    continue
                norm = os.path.abspath(att)
                if os.path.isfile(norm):
                    valid_attachments.append(norm)
                else:
                    return {
                        "success": False,
                        "status": "error",
                        "message": f"Attachment not found: '{os.path.basename(att)}'."
                    }

        sent = send_email(
            to_email=to_addr,
            subject=subject,
            body=body,
            email_id=email_id,
            email_pass=email_pass,
            attachments=valid_attachments,
            cc=cc,
            bcc=bcc
        )
        if sent:
            invalidate_cache(email_id)
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
                "status": sent.get("status", "error"),
                "message": sent.get("message", f"Failed to send email to {to_addr}.")
            }
    except Exception as e:
        return {"success": False, "status": "error", "message": f"Email sending error: {e}"}


def get_emails_overview(limit: int = 5, user: Optional[str] = None) -> Dict[str, Any]:
    """
    Non-blocking programmatic reader for latest inbox emails.
    Called by dashboard adapters, router, and settings page.
    """
    try:
        current_u = user or get_current_user()
        email_id, email_pass = get_user_email(current_u)
        if not email_id or not email_pass:
            return {
                "success": False,
                "status": "error",
                "emails": [],
                "message": (f"Email credentials not configured for '{current_u}'. "
                            "Please configure an Application-Specific Password in Settings.")
            }

        emails, meta = fetch_latest_emails_with_status(limit=limit, email_id=email_id, email_pass=email_pass)
        if not meta.get("success"):
            err = meta.get("error", "Failed to access inbox.")
            return {
                "success": False,
                "status": "error",
                "emails": [],
                "message": f"Email access failed: {err}."
            }

        if not emails:
            return {
                "success": True,
                "status": "success",
                "emails": [],
                "count": 0,
                "message": "No new emails found in inbox."
            }

        summaries = [f"From {e.get('sender')}: '{e.get('subject')}'" for e in emails[:3]]
        source_note = " (cached)" if meta.get("source") == "cached_fallback" else ""
        speech_text = f"You have {len(emails)} recent email(s){source_note}. " + "; ".join(summaries) + "."

        return {
            "success": True,
            "status": "success",
            "count": len(emails),
            "emails": emails,
            "source": meta.get("source", "live"),
            "message": speech_text
        }
    except Exception as e:
        return {"success": False, "status": "error", "emails": [],
                "message": f"Failed to fetch emails: {e}"}


def resolve_email_attachment_and_recipient(command: str, user_id: Optional[Any] = None) -> Dict[str, Any]:
    """
    Backwards-compatible helper preserved for any callers that used the original function.
    Delegates to _handle_compose_with_review via parsed intent.
    """
    parsed = _parse_email_intent(command)
    if not any(k in command.lower() for k in ["send", "email", "mail", "forward"]):
        return {"is_send_command": False}
    return {"is_send_command": True, **parsed}


# ──────────────────────────────────────────────────────────────────
# EmailController class wrapper (preserves __init__.py interface)
# ──────────────────────────────────────────────────────────────────

class EmailController:
    """Wrapper class providing static and instance access to email capabilities."""
    send_email = staticmethod(send_email)
    show_email_editor = staticmethod(show_email_editor)
    send_email_direct = staticmethod(send_email_direct)
    get_emails_overview = staticmethod(get_emails_overview)
    handle_email_command = staticmethod(handle_email_command)
    get_credentials = staticmethod(get_credentials)
    get_current_user = staticmethod(get_current_user)
    get_pending_email = staticmethod(get_pending_email)
    clear_pending_email = staticmethod(clear_pending_email)
    _resolve_user = staticmethod(_resolve_user)
    _dispatch_pending_email = staticmethod(_dispatch_pending_email)

email_controller = EmailController()
