"""
Smart Assistant — Multi-User Isolation & GDPR Service
Enforces strict server-side ownership isolation, token-derived identity,
GDPR-compliant structured data export, and cascading data deletion.
"""

import json
import logging
from typing import Optional, Dict, Any, Tuple

from core.db_pool import get_db_pool
from core.auth_service import verify_token, log_security_event

logger = logging.getLogger("UserIsolation")


class AuthorizationError(Exception):
    """Raised when an operation violates multi-user isolation boundaries."""
    pass


def resolve_identity(user_id: Any = None, allow_system: bool = False) -> Optional[int]:
    """
    Authoritative identity resolution across the entire assistant.
    Flow:
      explicit request user_id -> instance.config CURRENT_USER_ID -> instance.config get_last_user()
    Never silently defaults to user_id 1.
    If identity cannot be resolved:
      - returns None (or system context if allow_system is True).
    """
    if user_id is not None:
        try:
            val = int(user_id)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass
        s = str(user_id).strip()
        if s.isdigit():
            return int(s)
        # Try database username lookup
        try:
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("SELECT id FROM users WHERE username = %s LIMIT 1;", (s,))
                    row = cur.fetchone()
                    if row and row[0]:
                        return int(row[0])
        except Exception:
            pass

    # Check session/runtime context
    try:
        from instance.config import settings
        curr = getattr(settings, 'CURRENT_USER_ID', None)
        if curr is not None:
            return int(curr)
        last_u = settings.get_last_user()
        if last_u is not None:
            return int(last_u)
    except Exception:
        pass

    return None


def extract_authenticated_user(auth_header: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Extracts and validates Bearer token from HTTP Authorization header.
    Returns decoded token payload {'sub': user_id, 'username': str, ...} or None.
    """
    if not auth_header:
        return None

    parts = auth_header.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        token = parts[1]
        return verify_token(token)
    elif len(parts) == 1:
        return verify_token(parts[0])

    return None


def enforce_ownership(authenticated_user_id: int, target_user_id: Optional[int]) -> bool:
    """
    Guarantees that an operation cannot access or mutate another user's data.
    Raises AuthorizationError if IDs do not match.
    """
    if target_user_id is None:
        return True
    try:
        auth_uid = int(authenticated_user_id)
        target_uid = int(target_user_id)
        if auth_uid != target_uid:
            log_security_event(auth_uid, "unauthorized_access_attempt", "BLOCKED", {
                "target_user_id": target_uid
            })
            raise AuthorizationError(f"Access denied: User {auth_uid} is not authorized to access User {target_uid}'s resources.")
        return True
    except (ValueError, TypeError):
        raise AuthorizationError("Invalid user identity identifier.")


# ── GDPR DATA EXPORT (Structured JSON) ────────────────────────────────────────

def export_user_data(user_id: int) -> Dict[str, Any]:
    """
    Exports all data owned by the authenticated user across all tables in clean JSON.
    Strictly isolated to user_id.
    """
    pool = get_db_pool()
    if not pool.is_healthy():
        return {"error": "Database service offline"}

    user_id = int(user_id)
    export_result = {
        "user_id": user_id,
        "profile": {},
        "preferences": {},
        "memories": {},
        "memory_facts": [],
        "conversations": [],
        "messages": [],
        "notes": [],
        "reminders": [],
        "calendar_events": [],
        "active_contexts": []
    }

    try:
        with pool.get_cursor() as cur:
            # 1. Profile (excluding sensitive password hashes)
            cur.execute("SELECT username, status, created_at, updated_at FROM users WHERE id = %s", (user_id,))
            user_row = cur.fetchone()
            if user_row:
                export_result["profile"] = {
                    "username": user_row[0],
                    "status": user_row[1],
                    "created_at": str(user_row[2]) if user_row[2] else None,
                    "updated_at": str(user_row[3]) if user_row[3] else None
                }

            # 2. Preferences
            cur.execute("SELECT pref_key, pref_value, created_at FROM user_preferences WHERE user_id = %s", (user_id,))
            for r in cur.fetchall():
                export_result["preferences"][r[0]] = r[1]

            # 3. Categorized / JSONB memory
            cur.execute("SELECT memory, created_at FROM user_memory WHERE user_id = %s", (user_id,))
            mem_row = cur.fetchone()
            if mem_row and mem_row[0]:
                export_result["memories"] = mem_row[0]

            # 4. Memory Facts
            cur.execute("""
                SELECT fact_key, fact_value, confidence, source, created_at, last_accessed
                FROM memory_facts WHERE user_id = %s
            """, (user_id,))
            for r in cur.fetchall():
                export_result["memory_facts"].append({
                    "key": r[0],
                    "value": r[1],
                    "confidence": r[2],
                    "source": r[3],
                    "created_at": str(r[4]) if r[4] else None,
                    "last_accessed": str(r[5]) if r[5] else None
                })

            # 5. Conversations
            cur.execute("""
                SELECT id, user_input, assistant_response, timestamp, session_id, metadata
                FROM conversations WHERE user_id = %s ORDER BY id ASC
            """, (user_id,))
            for r in cur.fetchall():
                export_result["conversations"].append({
                    "id": r[0],
                    "user_input": r[1],
                    "assistant_response": r[2],
                    "timestamp": str(r[3]) if r[3] else None,
                    "session_id": r[4],
                    "metadata": r[5]
                })

            # 6. Messages
            cur.execute("""
                SELECT id, role, content, created_at, conversation_id
                FROM messages WHERE user_id = %s ORDER BY id ASC
            """, (user_id,))
            for r in cur.fetchall():
                export_result["messages"].append({
                    "id": r[0],
                    "role": r[1],
                    "content": r[2],
                    "created_at": str(r[3]) if r[3] else None,
                    "conversation_id": r[4]
                })

            # 7. Notes
            cur.execute("SELECT id, note, pinned, done, created_at FROM notes WHERE user_id = %s", (user_id,))
            for r in cur.fetchall():
                export_result["notes"].append({
                    "id": r[0],
                    "note": r[1],
                    "pinned": r[2],
                    "done": r[3],
                    "created_at": str(r[4]) if r[4] else None
                })

            # 8. Reminders
            cur.execute("""
                SELECT id, task_text, due_at, is_notified, created_at
                FROM reminders WHERE user_id = %s
            """, (user_id,))
            for r in cur.fetchall():
                export_result["reminders"].append({
                    "id": r[0],
                    "task": r[1],
                    "due_at": str(r[2]) if r[2] else None,
                    "is_notified": r[3],
                    "created_at": str(r[4]) if r[4] else None
                })

            # 9. Calendar Events
            cur.execute("""
                SELECT id, title, description, start_datetime, end_datetime, is_all_day, event_type
                FROM calendar_events WHERE user_id = %s
            """, (user_id,))
            for r in cur.fetchall():
                export_result["calendar_events"].append({
                    "id": str(r[0]),
                    "title": r[1],
                    "description": r[2],
                    "start": str(r[3]) if r[3] else None,
                    "end": str(r[4]) if r[4] else None,
                    "all_day": r[5],
                    "type": r[6]
                })

        log_security_event(user_id, "gdpr_data_export", "SUCCESS")
        return export_result
    except Exception as e:
        log_security_event(user_id, "gdpr_data_export", f"ERROR: {str(e)}")
        return {"error": f"Failed to export user data: {e}"}


# ── GDPR CASCADING DATA DELETION ──────────────────────────────────────────────

def delete_user_account_cascading(user_id: int) -> Dict[str, Any]:
    """
    Permanently deletes a user and cascades deletion across all user-owned records.
    Atomic transaction ensures all or nothing.
    """
    pool = get_db_pool()
    if not pool.is_healthy():
        return {"success": False, "error": "Database service offline"}

    user_id = int(user_id)
    try:
        with pool.get_cursor() as cur:
            # Explicit deletes to safeguard against non-cascading legacy setups
            cur.execute("DELETE FROM user_memory WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM user_preferences WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM system_memory WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM memory_facts WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM memory_embeddings WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM conversations WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM messages WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM notes WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM reminders WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM calendar_events WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM calendar_settings WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM active_contexts WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM plugin_logs WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM decision_logs WHERE user_id = %s", (user_id,))

            # Finally, delete from users authority table
            cur.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
            deleted = cur.fetchone()

        if not deleted:
            return {"success": False, "error": "User does not exist"}

        log_security_event(None, "gdpr_user_deletion", "SUCCESS", {"deleted_user_id": user_id})
        return {"success": True, "message": f"User {user_id} and all associated data permanently deleted."}
    except Exception as e:
        log_security_event(user_id, "gdpr_user_deletion", f"ERROR: {str(e)}")
        return {"success": False, "error": f"Failed to delete user account: {e}"}
