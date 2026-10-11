import json
import os
import re
from typing import Optional, Tuple, Dict, Any, List
from .security import encrypt_password, decrypt_password

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
USER_EMAILS_PATH = os.path.join(DATA_DIR, "user_emails.json")

def _normalize_user_key(user_id_or_name: Any) -> str:
    """Canonicalize username or integer user_id into consistent storage key."""
    if user_id_or_name is None:
        return "default_user"
    if isinstance(user_id_or_name, int):
        return f"user_{user_id_or_name}"
    s = str(user_id_or_name).strip().lower()
    if s.isdigit():
        return f"user_{s}"
    return s


def _get_user_candidate_keys(user_id_or_name: Any) -> List[str]:
    """
    Returns all possible identifier keys for a user across integer ID,
    'user_X' format, and real username (e.g., ['ram', 'user_8', '8']).
    Ensures that credentials saved under 'ram' can be read by '8' / 'user_8'
    and vice versa.
    """
    keys: List[str] = []
    if user_id_or_name is None:
        try:
            from instance.config import settings
            uname = getattr(settings, "CURRENT_USERNAME", None)
            if uname:
                keys.append(str(uname).strip().lower())
            uid = getattr(settings, "CURRENT_USER_ID", None)
            if uid:
                keys.append(f"user_{uid}")
                keys.append(str(uid).strip().lower())
        except Exception:
            pass
        try:
            from core.assistant_core import assistant_core
            ctx = assistant_core.get_user_context()
            if ctx.get("username"):
                keys.append(str(ctx["username"]).strip().lower())
            if ctx.get("user_id"):
                keys.append(f"user_{ctx['user_id']}")
                keys.append(str(ctx["user_id"]).strip().lower())
        except Exception:
            pass
        keys.append("default_user")
        return list(dict.fromkeys([k for k in keys if k]))

    raw_str = str(user_id_or_name).strip().lower()
    if raw_str:
        keys.append(raw_str)

    uid_num = None
    if isinstance(user_id_or_name, int) or raw_str.isdigit():
        uid_num = int(raw_str) if raw_str.isdigit() else user_id_or_name
    elif raw_str.startswith("user_"):
        raw_num = raw_str.replace("user_", "")
        if raw_num.isdigit():
            uid_num = int(raw_num)

    if uid_num is not None:
        keys.append(f"user_{uid_num}")
        keys.append(str(uid_num))
        # Check settings matching ID
        try:
            from instance.config import settings
            if getattr(settings, "CURRENT_USER_ID", None) == uid_num:
                uname = getattr(settings, "CURRENT_USERNAME", None)
                if uname:
                    keys.append(str(uname).strip().lower())
        except Exception:
            pass
        # Check assistant_core
        try:
            from core.assistant_core import assistant_core
            ctx = assistant_core.get_user_context()
            if ctx.get("user_id") == uid_num and ctx.get("username"):
                keys.append(str(ctx["username"]).strip().lower())
        except Exception:
            pass
        # Check DB by ID
        try:
            from legacy.memory_manager import get_username_by_id
            uname_db = get_username_by_id(uid_num)
            if uname_db:
                keys.append(str(uname_db).strip().lower())
        except Exception:
            pass
    else:
        # String username like 'ram'
        try:
            from instance.config import settings
            cur_uname = (getattr(settings, "CURRENT_USERNAME", "") or "").strip().lower()
            if cur_uname == raw_str:
                uid = getattr(settings, "CURRENT_USER_ID", None)
                if uid:
                    keys.append(f"user_{uid}")
                    keys.append(str(uid).strip().lower())
        except Exception:
            pass
        try:
            from core.assistant_core import assistant_core
            ctx = assistant_core.get_user_context()
            if (ctx.get("username") or "").strip().lower() == raw_str:
                uid = ctx.get("user_id")
                if uid:
                    keys.append(f"user_{uid}")
                    keys.append(str(uid).strip().lower())
        except Exception:
            pass
        # Check DB for user_id by username
        try:
            from legacy.memory_manager import get_connection
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(%s) ORDER BY id ASC LIMIT 1", (raw_str,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row and row[0]:
                uid_db = row[0]
                keys.append(f"user_{uid_db}")
                keys.append(str(uid_db).strip().lower())
        except Exception:
            pass

    return list(dict.fromkeys([k for k in keys if k]))


def get_user_emails_path() -> str:
    """Return the active user emails storage path, supporting test-isolated overrides."""
    return os.environ.get("USER_EMAILS_PATH") or USER_EMAILS_PATH


def load_user_data() -> Dict[str, Any]:
    """Loads stored user email configurations safely."""
    path = get_user_emails_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[SECURITY] [WARN] Could not parse user email storage: {e}")
        return {}


def save_user_data(data: Dict[str, Any]) -> bool:
    """Saves user email data with atomic write semantics."""
    path = get_user_emails_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        if os.path.exists(path):
            os.replace(temp_path, path)
        else:
            os.rename(temp_path, path)
        return True
    except Exception as e:
        print(f"[SECURITY] [ERROR] Failed to save user emails: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return False


def get_user_email(username: Any) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (email, decrypted_password) for the given username or user_id.
    Tolerates string usernames ('ram'), 'user_8', and numeric IDs (8).
    Falls back to environment variables for primary user if unconfigured or placeholder.
    """
    data = load_user_data()
    candidate_keys = _get_user_candidate_keys(username)

    for k in candidate_keys:
        user_info = data.get(k)
        if user_info and isinstance(user_info, dict):
            email = user_info.get("email")
            encrypted_pass = user_info.get("app_password")
            if email and encrypted_pass:
                # Do not accept mock dummy placeholders like @example.com or @test.com in live runtime
                clean_e = str(email).strip().lower()
                if not (clean_e.endswith("@example.com") or clean_e.endswith("@test.com")):
                    try:
                        decrypted_pass = decrypt_password(encrypted_pass)
                        clean_pass = decrypted_pass.strip().replace(" ", "") if decrypted_pass else ""
                        return email, clean_pass
                    except Exception as e:
                        print(f"[SECURITY] [ERROR] Could not decrypt credentials for {k}: {e}")

    # Fallback to .env credentials for primary user if storage is missing or dummy
    try:
        from instance.config import settings
        primary_uid = getattr(settings, "CURRENT_USER_ID", 8)
        primary_uname = getattr(settings, "CURRENT_USERNAME", "ram")
    except Exception:
        primary_uid = 8
        primary_uname = "ram"

    norm_u = _normalize_user_key(username)
    is_primary = (
        username is None
        or norm_u in ("default_user", f"user_{primary_uid}", str(primary_uid), str(primary_uname).lower())
        or any(k in candidate_keys for k in [str(primary_uname).lower(), f"user_{primary_uid}", str(primary_uid), "default_user"])
    )

    if is_primary:
        from dotenv import load_dotenv
        load_dotenv()
        env_email = os.getenv("EMAIL_ID")
        env_pass = os.getenv("EMAIL_APP_PASSWORD") or os.getenv("EMAIL_PASS")
        if env_email and env_pass:
            clean_pass = env_pass.strip().replace(" ", "")
            return env_email.strip(), clean_pass

    return None, None


def save_user_email(username: Any, email: str, password: str, account_name: str = "primary") -> bool:
    """
    Encrypts and saves user email credentials.
    Writes canonical entry and ensures alias keys match for instant lookup.
    Performs immediate round-trip verification read before returning success.
    """
    if not email or not password:
        return False
    data = load_user_data()
    candidate_keys = _get_user_candidate_keys(username)
    if not candidate_keys:
        candidate_keys = [_normalize_user_key(username)]

    try:
        encrypted_pass = encrypt_password(password.strip())
    except Exception as e:
        print(f"[SECURITY] [ERROR] Refusing to save unencrypted credentials: {e}")
        return False

    entry = {
        "email": email.strip(),
        "app_password": encrypted_pass,
        "account_name": account_name
    }

    for k in candidate_keys:
        data[k] = dict(entry)

    saved = save_user_data(data)
    if not saved:
        return False

    # Verification read to guarantee storage and encryption integrity
    v_email, v_pass = get_user_email(username)
    if v_email == email.strip() and v_pass == password.strip():
        return True

    for k in candidate_keys:
        ve, vp = get_user_email(k)
        if ve == email.strip() and vp == password.strip():
            return True

    return False


def clear_credentials(username: Any) -> bool:
    """
    Removes stored credentials for the given user.
    Required by Settings page and account management.
    """
    data = load_user_data()
    candidate_keys = _get_user_candidate_keys(username)
    modified = False

    for k in candidate_keys:
        if k in data:
            del data[k]
            modified = True

    if modified:
        return save_user_data(data)
    return True


def list_configured_users() -> List[str]:
    """Returns list of user keys that have stored credentials."""
    data = load_user_data()
    return list(data.keys())


# ──────────────────────────────────────────────────────────────────
# Persistent Drafts Management (Per-Account Isolated)
# ──────────────────────────────────────────────────────────────────

DRAFTS_PATH = os.path.join(DATA_DIR, "drafts.json")

def load_drafts_data() -> Dict[str, List[Dict[str, Any]]]:
    """Loads stored drafts grouped by user key."""
    if not os.path.exists(DRAFTS_PATH):
        return {}
    try:
        with open(DRAFTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[STORAGE] [WARN] Could not parse email drafts: {e}")
        return {}

def save_drafts_data(data: Dict[str, List[Dict[str, Any]]]) -> bool:
    """Saves drafts data atomically."""
    os.makedirs(DATA_DIR, exist_ok=True)
    temp_path = DRAFTS_PATH + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        if os.path.exists(DRAFTS_PATH):
            os.replace(temp_path, DRAFTS_PATH)
        else:
            os.rename(temp_path, DRAFTS_PATH)
        return True
    except Exception as e:
        print(f"[STORAGE] [ERROR] Failed to save drafts: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return False

def _find_user_drafts_entry(data: Dict[str, Any], username: Any) -> Tuple[str, List[Dict[str, Any]]]:
    candidate_keys = _get_user_candidate_keys(username)
    for k in candidate_keys:
        if k in data and isinstance(data[k], list):
            return k, data[k]
    primary_key = candidate_keys[0] if candidate_keys else _normalize_user_key(username)
    user_list = data.setdefault(primary_key, [])
    return primary_key, user_list

def save_draft(username: Any, draft: Dict[str, Any]) -> Optional[str]:
    """
    Saves or updates a draft for the given user.
    Returns generated or existing draft_id if saved successfully, else None.
    """
    if not draft or not isinstance(draft, dict):
        return None
    import time
    import uuid

    data = load_drafts_data()
    key, user_drafts = _find_user_drafts_entry(data, username)

    draft_id = draft.get("id") or f"draft_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    entry = {
        "id": draft_id,
        "recipient": draft.get("recipient") or draft.get("to") or "",
        "cc": draft.get("cc") or "",
        "bcc": draft.get("bcc") or "",
        "subject": draft.get("subject") or "(No Subject)",
        "body": draft.get("body") or "",
        "attachments": draft.get("attachments") or [],
        "saved_at": draft.get("saved_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    # If existing draft with this ID, replace it
    replaced = False
    for i, d in enumerate(user_drafts):
        if isinstance(d, dict) and d.get("id") == draft_id:
            user_drafts[i] = entry
            replaced = True
            break
    if not replaced:
        user_drafts.append(entry)

    data[key] = user_drafts
    if save_drafts_data(data):
        return draft_id
    return None

def list_drafts(username: Any) -> List[Dict[str, Any]]:
    """Lists all drafts saved for the specific user."""
    data = load_drafts_data()
    _, user_drafts = _find_user_drafts_entry(data, username)
    return list(user_drafts)

def get_draft(username: Any, draft_id_or_index: Any) -> Optional[Dict[str, Any]]:
    """
    Retrieves a draft by ID or 1-based index (e.g. 1 for draft #1).
    """
    data = load_drafts_data()
    _, user_drafts = _find_user_drafts_entry(data, username)
    if not user_drafts:
        return None

    # Try numeric index first (1-indexed)
    if isinstance(draft_id_or_index, int) or (isinstance(draft_id_or_index, str) and draft_id_or_index.isdigit()):
        idx = int(draft_id_or_index) - 1
        if 0 <= idx < len(user_drafts):
            return user_drafts[idx]

    # Try matching ID
    target_id = str(draft_id_or_index).strip().lower()
    for d in user_drafts:
        if str(d.get("id", "")).lower() == target_id:
            return d
    return None

def delete_draft(username: Any, draft_id_or_index: Any) -> bool:
    """
    Deletes a draft by ID or 1-based index for the specific user.
    """
    data = load_drafts_data()
    key, user_drafts = _find_user_drafts_entry(data, username)
    if not user_drafts:
        return False

    target_idx = None
    if isinstance(draft_id_or_index, int) or (isinstance(draft_id_or_index, str) and draft_id_or_index.isdigit()):
        idx = int(draft_id_or_index) - 1
        if 0 <= idx < len(user_drafts):
            target_idx = idx

    if target_idx is None:
        target_id = str(draft_id_or_index).strip().lower()
        for i, d in enumerate(user_drafts):
            if str(d.get("id", "")).lower() == target_id:
                target_idx = i
                break

    if target_idx is not None:
        del user_drafts[target_idx]
        data[key] = user_drafts
        return save_drafts_data(data)

    return False


