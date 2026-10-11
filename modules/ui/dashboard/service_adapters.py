"""
Dashboard Service Adapters
==========================
Thin, non-invasive adapters that expose existing backend services
to the dashboard UI. No backend logic is changed — only safe,
read-oriented wrappers and explicit write paths are provided.

All long-running operations return immediately; the UI layer
uses DashboardWorker (QThread) to execute them off the GUI thread.
"""

from __future__ import annotations

import os
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
#  Identity / User Context
# ─────────────────────────────────────────────────────────────────────────────

def get_identity() -> Dict[str, Any]:
    """Return (username, assistant_name, user_id) from live core context."""
    try:
        from core.assistant_core import assistant_core
        ctx = assistant_core.get_user_context()
        return {
            "user_id":   ctx.get("user_id"),
            "username":  ctx.get("username") or "User",
            "assistant_name": ctx.get("assistant_name") or "Trevon",
            "authenticated": ctx.get("authenticated", False),
        }
    except Exception:
        pass
    try:
        from instance.config import settings
        uid = getattr(settings, "CURRENT_USER_ID", None) or settings.get_last_user()
        aname = settings.get_assistant_name() if hasattr(settings, "get_assistant_name") else "Trevon"
        uname = getattr(settings, "CURRENT_USERNAME", None) or "User"
        return {
            "user_id": uid,
            "username": uname,
            "assistant_name": aname,
            "authenticated": uid is not None,
        }
    except Exception:
        return {"user_id": None, "username": "User", "assistant_name": "Trevon", "authenticated": False}


def set_assistant_name_ui(name: str) -> bool:
    """Update assistant name through core (persists to DB if authenticated)."""
    try:
        from core.assistant_core import assistant_core
        assistant_core.set_assistant_name(name)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Assistant State & Execution
# ─────────────────────────────────────────────────────────────────────────────

def get_assistant_state() -> Dict[str, Any]:
    """Return real-time assistant state from the canonical core."""
    state = "idle"
    audio_level = 0.0
    task_info: Dict[str, Any] = {}
    try:
        from core.assistant_core import assistant_core
        state = assistant_core.get_state()
        audio_level = getattr(assistant_core, "_audio_level", 0.0)
    except Exception:
        pass
    try:
        from core.state_manager import state_manager
        task_info = state_manager.get_current_task_info()
    except Exception:
        pass
    uptime_seconds = 0
    try:
        from core.assistant_core import assistant_core
        start = getattr(assistant_core, "_start_time", time.time())
        uptime_seconds = int(time.time() - start)
    except Exception:
        pass
    return {
        "state": state,
        "audio_level": audio_level,
        "task": task_info.get("task"),
        "progress": task_info.get("progress", 0),
        "active_operation": task_info.get("active_operation"),
        "steps": task_info.get("steps", []),
        "uptime_seconds": uptime_seconds,
    }


def send_command(text: str) -> Tuple[bool, str]:
    """Dispatch a text command through the canonical production path.
    Returns (success, response_text).
    The response string is captured from process_input so the dashboard
    can render the assistant reply immediately, without waiting for the
    DB reload timer."""
    if not text or not text.strip():
        return False, "Empty command"
    try:
        # Route through legacy assistant.process_input (UnifiedCommandRouter)
        from legacy import assistant as legacy_assistant
        response = legacy_assistant.process_input(text.strip())
        return True, str(response or "")
    except Exception as e:
        return False, f"Command error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
#  Settings / Preferences
# ─────────────────────────────────────────────────────────────────────────────

def load_user_preferences(user_id: Optional[int] = None) -> Dict[str, Any]:
    """Load all saved user preferences from PostgreSQL via legacy manager."""
    if user_id is None:
        ident = get_identity()
        user_id = ident.get("user_id")
    if not user_id:
        return {}
    prefs: Dict[str, Any] = {}
    try:
        from legacy.memory_manager import get_all_user_preferences_db
        all_prefs = get_all_user_preferences_db(user_id)
        if isinstance(all_prefs, dict):
            prefs.update(all_prefs)
    except Exception:
        pass
    # Also try the JSON fallback
    try:
        json_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "data", "user_preferences.json"
        )
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)
            ui_prefs = json_data.get("ui_preferences", {}).get(str(user_id), {})
            for k, v in ui_prefs.items():
                prefs.setdefault(k, v)
    except Exception:
        pass
    return prefs


def save_user_preference(*args, **kwargs) -> bool:
    """Persist a single preference value for the authenticated user.
    Supports both save_user_preference(key, value) and save_user_preference(user_id, key, value).
    """
    user_id = None
    if len(args) == 2:
        key, value = args
    elif len(args) == 3:
        user_id, key, value = args
    elif len(args) == 1 and "key" in kwargs:
        user_id = args[0]
        key = kwargs["key"]
        value = kwargs.get("value")
    else:
        key = kwargs.get("key")
        value = kwargs.get("value")
        user_id = kwargs.get("user_id")

    if user_id is None:
        ident = get_identity()
        user_id = ident.get("user_id")
    if not user_id:
        return False
    try:
        from legacy.memory_manager import set_user_preference_db
        set_user_preference_db(int(user_id), str(key), str(value))
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  History / Recent Interactions
# ─────────────────────────────────────────────────────────────────────────────

def load_recent_history(limit: int = 15) -> List[Dict[str, Any]]:
    """Load recent conversation messages from PostgreSQL (messages table)."""
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id:
        return []
    try:
        from extensions.database_manager import DatabaseManager
        db = DatabaseManager()
        if not db.pool:
            return []
        with db._get_cursor() as cur:
            if cur is None:
                return []
            cur.execute(
                "SELECT id, role, content, created_at FROM messages "
                "WHERE user_id = %s ORDER BY id DESC LIMIT %s",
                (user_id, limit)
            )
            rows = cur.fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r[0], "role": r[1], "content": r[2] or "",
                "created_at": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
            })
        return list(reversed(result))
    except Exception as e:
        return []


# ─────────────────────────────────────────────────────────────────────────────
#  Intelligence / Memory / Rules
# ─────────────────────────────────────────────────────────────────────────────

def load_learned_rules() -> List[Dict[str, Any]]:
    """Retrieve saved preference/behavior rules for the current user."""
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id:
        return []
    try:
        from skills.learning.learned_rules import get_learned_rules_engine
        engine = get_learned_rules_engine()
        rules = engine.list_rules(int(user_id))
        return rules or []
    except Exception:
        return []


def add_learned_rule(rule_text: str) -> bool:
    """Persist a new learned rule."""
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id or not rule_text.strip():
        return False
    try:
        from skills.learning.learned_rules import get_learned_rules_engine
        engine = get_learned_rules_engine()
        res = engine.add_rule(int(user_id), rule_text.strip())
        return bool(res and res.get("success"))
    except Exception:
        return False


def delete_learned_rule(rule_id: str) -> bool:
    """Delete a learned rule by id."""
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id or not rule_id:
        return False
    try:
        from skills.learning.learned_rules import get_learned_rules_engine
        engine = get_learned_rules_engine()
        res = engine.delete_rule(int(user_id), rule_id)
        return bool(res and res.get("success"))
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Communications (Email)
# ─────────────────────────────────────────────────────────────────────────────

def has_email_credentials() -> bool:
    """True if email credentials exist for the current user."""
    try:
        from modules.assistant_email.user_storage import get_user_email
        from modules.assistant_email.email_controller import get_current_user
        email, pwd = get_user_email(get_current_user())
        return bool(email and pwd)
    except Exception:
        return False


def load_emails(folder: str = "inbox", limit: int = 20) -> Dict[str, Any]:
    """Fetch latest emails from the existing email module with real credentials.
    Returns {success, emails, message}."""
    if not has_email_credentials():
        return {"success": False, "emails": [], "message": "No email credentials configured."}
    try:
        from modules.assistant_email.email_reader import fetch_latest_emails
        from modules.assistant_email.user_storage import get_user_email
        from modules.assistant_email.email_controller import get_current_user
        email_id, email_pass = get_user_email(get_current_user())
        if not email_id or not email_pass:
            return {"success": False, "emails": [], "message": "Email credentials unavailable."}
        emails = fetch_latest_emails(limit=limit, email_id=email_id, email_pass=email_pass)
        return {"success": True, "emails": emails or [], "message": ""}
    except Exception as e:
        return {"success": False, "emails": [], "message": str(e)}


def send_email_ui(to: str, subject: str, body: str, attachments: Optional[List[str]] = None) -> Dict[str, Any]:
    """Send an email through the existing email module with real credentials."""
    try:
        from modules.assistant_email.email_sender import send_email
        from modules.assistant_email.user_storage import get_user_email
        from modules.assistant_email.email_controller import get_current_user
        email_id, email_pass = get_user_email(get_current_user())
        if not email_id or not email_pass:
            return {"success": False, "message": "Email credentials not configured. Set them up in Settings → Email."}
        result = send_email(
            to_email=to,
            subject=subject,
            body=body,
            email_id=email_id,
            email_pass=email_pass,
            attachments=attachments or [],
        )
        if isinstance(result, dict):
            return result
        return {"success": bool(result), "message": "Message sent successfully." if result else "Send failed — check credentials and try again."}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  Schedule (Calendar + Reminders)
# ─────────────────────────────────────────────────────────────────────────────

def load_calendar_events(date_str: Optional[str] = None, days: int = 14) -> List[Dict[str, Any]]:
    """Load personal calendar events across the given range."""
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id:
        return []
    try:
        from modules.calendar_manager.calendar_storage import CalendarStorage
        storage = CalendarStorage()
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        start_dt = datetime.strptime(date_str, "%Y-%m-%d")
        end_dt = start_dt + timedelta(days=days - 1)
        result = storage.get_events_range(
            int(user_id), start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")
        )
        flat = []
        if isinstance(result, dict):
            for d, evs in result.items():
                for ev in evs:
                    ev.setdefault("date", d)
                    flat.append(ev)
        elif isinstance(result, list):
            flat = list(result)
        return flat
    except Exception:
        return []


def create_calendar_event(title: str, date: str, time: Optional[str] = None,
                          description: Optional[str] = None) -> bool:
    """Create a new personal calendar event."""
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id or not title.strip() or not date:
        return False
    try:
        from modules.calendar_manager.calendar_storage import CalendarStorage
        storage = CalendarStorage()
        event = {"title": title.strip(), "date": date, "time": time or "",
                 "description": description or ""}
        storage.add_event(int(user_id), event)
        return True
    except Exception:
        return False


def load_reminders() -> List[Dict[str, Any]]:
    """Load upcoming reminders for the current user."""
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id:
        return []
    try:
        from extensions.database_manager import DatabaseManager
        db = DatabaseManager()
        if not db.pool:
            return []
        with db._get_cursor() as cur:
            if cur is None:
                return []
            cur.execute(
                "SELECT id, task_text, due_at, is_notified, created_at FROM reminders "
                "WHERE user_id = %s ORDER BY due_at ASC NULLS LAST LIMIT 50",
                (user_id,)
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            due = r[2]
            if hasattr(due, "isoformat"):
                due = due.isoformat()
            created = r[4]
            if hasattr(created, "isoformat"):
                created = created.isoformat()
            out.append({
                "id": r[0], "task_text": r[1] or "", "due_at": due,
                "is_notified": bool(r[3]), "created_at": created,
            })
        return out
    except Exception:
        return []


def create_reminder_ui(task_text: str, due_at_iso: str) -> bool:
    """Create a reminder via database manager."""
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id or not task_text.strip():
        return False
    try:
        from extensions.database_manager import DatabaseManager
        db = DatabaseManager()
        if not db.pool:
            return False
        due = None
        if due_at_iso:
            try:
                due = datetime.fromisoformat(due_at_iso.replace("Z", "+00:00"))
            except Exception:
                due = None
        with db._get_cursor() as cur:
            if cur is None:
                return False
            cur.execute(
                "INSERT INTO reminders (user_id, task_text, due_at, is_notified) "
                "VALUES (%s, %s, %s, %s)",
                (int(user_id), task_text.strip(), due, False)
            )
        return True
    except Exception:
        return False


def delete_reminder(reminder_id) -> bool:
    """Delete a reminder by its id (user-isolated)."""
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id or reminder_id is None:
        return False
    try:
        from extensions.database_manager import DatabaseManager
        db = DatabaseManager()
        if not db.pool:
            return False
        with db._get_cursor() as cur:
            if cur is None:
                return False
            cur.execute(
                "DELETE FROM reminders WHERE id = %s AND user_id = %s",
                (int(reminder_id), int(user_id))
            )
        return True
    except Exception:
        return False


def delete_calendar_event(event_id: str) -> bool:
    """Delete a calendar event by id (user-isolated)."""
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id or not event_id:
        return False
    try:
        from modules.calendar_manager.calendar_storage import CalendarStorage
        storage = CalendarStorage()
        return bool(storage.delete_event(int(user_id), event_id))
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Connected World (Devices + Smart Home + Audio)
# ─────────────────────────────────────────────────────────────────────────────

def load_paired_devices() -> List[Dict[str, Any]]:
    """Return paired mobile devices for the current user."""
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id:
        return []
    try:
        from skills.device_management.device_controller import DeviceController
        ctrl = DeviceController()
        res = ctrl.list_devices(int(user_id))
        if res and res.get("success"):
            return res.get("devices", []) or []
    except Exception:
        pass
    # Fallback: read JSON device cache
    try:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "data", "devices", f"user_{user_id}_devices.json"
        )
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or []
    except Exception:
        pass
    return []


def load_smart_home_devices() -> List[Dict[str, Any]]:
    """Return smart home devices for the current user."""
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id:
        return []
    try:
        from skills.smart_home.service import get_smart_home_service
        svc = get_smart_home_service()
        devices = svc.list_devices(int(user_id))
        return [d.to_dict() for d in devices] if devices else []
    except Exception:
        # Fallback JSON
        try:
            path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                "data", "smart_home", f"user_{user_id}_devices.json"
            )
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f) or []
        except Exception:
            pass
        return []


def set_smart_home_power(target_name: str, on: bool) -> Dict[str, Any]:
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id:
        return {"success": False, "message": "Not authenticated"}
    try:
        from skills.smart_home.service import get_smart_home_service
        svc = get_smart_home_service()
        return svc.set_power(int(user_id), target_name, bool(on)) or {"success": False}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  Workspace / Documents
# ─────────────────────────────────────────────────────────────────────────────

def list_recent_files(directories: Optional[List[str]] = None, limit: int = 30) -> List[Dict[str, Any]]:
    """List recent files from Desktop/Documents/Downloads + workspace."""
    if directories is None:
        home = os.path.expanduser("~")
        directories = [
            os.path.join(home, "Desktop"),
            os.path.join(home, "Documents"),
            os.path.join(home, "Downloads"),
        ]
    entries: List[Tuple[float, Dict[str, Any]]] = []
    seen = set()
    for d in directories:
        if not os.path.isdir(d):
            continue
        try:
            for name in os.listdir(d):
                full = os.path.join(d, name)
                if not os.path.isfile(full):
                    continue
                if name.startswith("."):
                    continue
                try:
                    stat = os.stat(full)
                except Exception:
                    continue
                if full in seen:
                    continue
                seen.add(full)
                ext = os.path.splitext(name)[1].lower().lstrip(".")
                entries.append((
                    stat.st_mtime,
                    {
                        "name": name,
                        "path": full,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "extension": ext,
                        "folder": os.path.basename(d),
                    }
                ))
        except Exception:
            continue
    entries.sort(key=lambda x: x[0], reverse=True)
    return [e[1] for e in entries[:limit]]


def generate_document(doc_type: str, topic: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Generate a PDF/DOCX/XLSX/PPTX document using the existing document_tools module."""
    extra = extra or {}
    try:
        from modules.document_tools import (
            build_document_content, build_presentation_slides, build_spreadsheet_spec,
            create_pdf_document, create_docx_document, create_excel_spreadsheet,
            create_presentation,
        )
        dt = (doc_type or "pdf").lower()
        output_dir = os.path.join(os.path.expanduser("~"), "Documents", "Trevon Assistant")
        os.makedirs(output_dir, exist_ok=True)
        safe_topic = "".join(c for c in topic if c.isalnum() or c in " _-").strip() or "document"
        if dt in ("pdf", "docx"):
            content = build_document_content(topic)
            if isinstance(content, dict):
                title = content.get("title") or safe_topic
                sections = content.get("sections", []) or content
            else:
                title = safe_topic
                sections = content or safe_topic
            if dt == "pdf":
                path = os.path.join(output_dir, f"{safe_topic}.pdf")
                res = create_pdf_document(title=title, content=sections, filename=path)
                if not res.get("success"):
                    return {"success": False, "message": res.get("message", "Failed to generate PDF")}
            else:
                path = os.path.join(output_dir, f"{safe_topic}.docx")
                res = create_docx_document(title=title, content=sections, filename=path)
                if not res.get("success"):
                    return {"success": False, "message": res.get("message", "Failed to generate Word document")}
        elif dt == "xlsx":
            spec = build_spreadsheet_spec(topic) or {}
            sheets = spec.get("sheets", [{"title": "Sheet1", "headers": ["Item", "Value"], "rows": []}])
            path = os.path.join(output_dir, f"{safe_topic}.xlsx")
            res = create_excel_spreadsheet(sheet_title="Sheet1", sheets=sheets, filename=path)
            if not res.get("success"):
                return {"success": False, "message": res.get("message", "Failed to generate Excel spreadsheet")}
        elif dt == "pptx":
            slides = build_presentation_slides(topic) or []
            path = os.path.join(output_dir, f"{safe_topic}.pptx")
            res = create_presentation(title=topic, slides=slides, filename=path)
            if not res.get("success"):
                return {"success": False, "message": res.get("message", "Failed to generate PowerPoint presentation")}
        else:
            return {"success": False, "message": f"Unsupported type: {doc_type}"}
        return {"success": True, "path": path, "message": f"Generated: {path}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  Diagnostics / System Health
# ─────────────────────────────────────────────────────────────────────────────

def run_diagnostics() -> Dict[str, Dict[str, Any]]:
    """Produce a real health snapshot of every major subsystem."""
    results: Dict[str, Dict[str, Any]] = {}

    # 1. Assistant Core
    try:
        from core.assistant_core import assistant_core
        state = assistant_core.get_state()
        results["core"] = {"status": "online", "detail": f"state={state}", "ok": True}
    except Exception as e:
        results["core"] = {"status": "error", "detail": str(e), "ok": False}

    # 2. LLM Engine
    try:
        from extensions.llm_engine import LLMEngine
        eng = LLMEngine()
        keys_count = len(eng.openai_keys or []) + len(eng.groq_keys or []) + len(eng.gemini_keys or [])
        results["llm"] = {
            "status": "configured" if keys_count > 0 else "no_keys",
            "detail": f"providers_with_keys={keys_count}",
            "ok": keys_count > 0,
        }
    except Exception as e:
        results["llm"] = {"status": "error", "detail": str(e), "ok": False}

    # 3. Database
    try:
        from extensions.database_manager import DatabaseManager
        db = DatabaseManager()
        ok = db.pool is not None
        results["database"] = {
            "status": "online" if ok else "unavailable",
            "detail": "pool_ready" if ok else "no_pool",
            "ok": ok,
        }
    except Exception as e:
        results["database"] = {"status": "error", "detail": str(e), "ok": False}

    # 4. Voice (pyttsx3 + microphone)
    try:
        import pyttsx3
        engine = pyttsx3.init()
        voices = engine.getProperty("voices") or []
        results["voice"] = {
            "status": "online",
            "detail": f"voices={len(voices)}",
            "ok": True,
        }
    except Exception as e:
        results["voice"] = {"status": "error", "detail": str(e), "ok": False}

    # 5. Email
    results["email"] = {
        "status": "configured" if has_email_credentials() else "not_configured",
        "detail": "",
        "ok": has_email_credentials(),
    }

    # 6. Devices
    try:
        devs = load_paired_devices()
        results["devices"] = {
            "status": "ok",
            "detail": f"paired={len(devs)}",
            "ok": True,
        }
    except Exception as e:
        results["devices"] = {"status": "error", "detail": str(e), "ok": False}

    # 7. Automation / Reminders
    try:
        rems = load_reminders()
        results["automation"] = {
            "status": "ok",
            "detail": f"reminders={len(rems)}",
            "ok": True,
        }
    except Exception as e:
        results["automation"] = {"status": "error", "detail": str(e), "ok": False}

    # 8. API / Network
    try:
        import requests
        r = requests.get("https://1.1.1.1", timeout=3)
        results["api"] = {"status": "online", "detail": "network_ok", "ok": r.status_code < 500}
    except Exception as e:
        results["api"] = {"status": "offline", "detail": str(e), "ok": False}

    # 9. Background workers (check orchestrator running)
    try:
        running = False
        import threading
        for t in threading.enumerate():
            if "orchestrator" in t.name.lower() or "voice" in t.name.lower():
                running = True
                break
        results["workers"] = {
            "status": "running" if running else "idle",
            "detail": "",
            "ok": True,
        }
    except Exception as e:
        results["workers"] = {"status": "error", "detail": str(e), "ok": False}

    return results


# ─────────────────────────────────────────────────────────────────────────────
#  Export / Data operations
# ─────────────────────────────────────────────────────────────────────────────

def export_conversations(output_path: str) -> bool:
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id:
        return False
    try:
        hist = load_recent_history(limit=1000)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(hist, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def clear_conversation_history() -> bool:
    ident = get_identity()
    user_id = ident.get("user_id")
    if not user_id:
        return False
    try:
        from extensions.database_manager import DatabaseManager
        db = DatabaseManager()
        if not db.pool:
            return False
        with db._get_cursor() as cur:
            if cur is None:
                return False
            cur.execute("DELETE FROM messages WHERE user_id = %s", (int(user_id),))
        return True
    except Exception:
        return False
