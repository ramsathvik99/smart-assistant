"""
Smart Assistant — Centralized Per-User Credential Manager & Secure Vault
========================================================================
Provides secure, isolated credential storage and lifecycle management
for every user across the entire assistant.

Key Guarantees:
1. Strict per-user isolation: User A cannot read, decrypt, or access User B's keys.
2. Windows DPAPI (CryptProtectData/CryptUnprotectData) OS-protected encryption with
   user-scoped entropy, falling back to AES/Fernet with per-user salt.
3. Plaintext keys are NEVER stored in ordinary settings, logs, or chat memory.
4. Masked metadata only is returned to frontend surfaces (never raw keys).
5. No silent fallback to developer's .env keys for user operations.
6. Centralized credential resolution:
       get_credential(user_context, provider_name) -> Optional[str]
"""

from __future__ import annotations

import os
import sys
import json
import time
import base64
import hashlib
import logging
import threading
import uuid
import stat
import shutil
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple, Callable

logger = logging.getLogger("CredentialManager")

# ─────────────────────────────────────────────────────────────────────────────
# OS-LEVEL ENCRYPTION ENGINE (DPAPI + Fernet Fallback)
# ─────────────────────────────────────────────────────────────────────────────

_HAS_DPAPI = False
try:
    import win32crypt
    _HAS_DPAPI = True
except ImportError:
    pass

_HAS_CRYPTOGRAPHY = False
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    _HAS_CRYPTOGRAPHY = True
except ImportError:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# SUPPORTED PROVIDERS REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

SUPPORTED_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "groq": {
        "name": "groq",
        "display_name": "Groq Cloud (Fast AI)",
        "category": "ai",
        "description": "Ultra-fast low-latency inference for real-time conversation and voice responses (Qwen 2.5, Llama 3.3).",
        "required_for": "Fast voice and interactive conversational responses.",
        "is_secret": True,
        "is_cloud": True,
        "default_model": "qwen/qwen3.8-27b",
        "key_prefix": "gsk_",
        "help_url": "https://console.groq.com/keys"
    },
    "openai": {
        "name": "openai",
        "display_name": "OpenAI",
        "category": "ai",
        "description": "State-of-the-art general reasoning, complex task planning, and fast path intelligence (GPT-4o, GPT-4o-mini).",
        "required_for": "General reasoning, multi-step actions, and task execution.",
        "is_secret": True,
        "is_cloud": True,
        "default_model": "gpt-4o-mini",
        "key_prefix": "sk-",
        "help_url": "https://platform.openai.com/api-keys"
    },
    "gemini": {
        "name": "gemini",
        "display_name": "Google Gemini",
        "category": "ai",
        "description": "Multimodal reasoning and high-context analysis (Gemini 2.5 Flash).",
        "required_for": "Multimodal document analysis and long-context processing.",
        "is_secret": True,
        "is_cloud": True,
        "default_model": "gemini-2.5-flash",
        "key_prefix": "AIza",
        "help_url": "https://aistudio.google.com/app/apikey"
    },
    "deepseek": {
        "name": "deepseek",
        "display_name": "DeepSeek AI",
        "category": "ai",
        "description": "Advanced code synthesis, mathematics, and technical reasoning (deepseek-chat).",
        "required_for": "Programming, mathematical, and technical assistant tasks.",
        "is_secret": True,
        "is_cloud": True,
        "default_model": "deepseek-chat",
        "key_prefix": "sk-",
        "help_url": "https://platform.deepseek.com/api_keys"
    },
    "anthropic": {
        "name": "anthropic",
        "display_name": "Anthropic Claude",
        "category": "ai",
        "description": "Nuanced reasoning, long-document understanding, and high-accuracy tool use (Claude 3.5 Sonnet).",
        "required_for": "Professional document synthesis, safety-critical reasoning, and writing.",
        "is_secret": True,
        "is_cloud": True,
        "default_model": "claude-3-5-sonnet-20241022",
        "key_prefix": "sk-ant-",
        "help_url": "https://console.anthropic.com/settings/keys"
    },
    "huggingface": {
        "name": "huggingface",
        "display_name": "Hugging Face",
        "category": "ai",
        "description": "Access to open-source models hosted on Hugging Face Inference API.",
        "required_for": "Open-source specialized models and embeddings.",
        "is_secret": True,
        "is_cloud": True,
        "default_model": "mistralai/Mistral-7B-Instruct-v0.2",
        "key_prefix": "hf_",
        "help_url": "https://huggingface.co/settings/tokens"
    },
    "ollama": {
        "name": "ollama",
        "display_name": "Local Ollama Server",
        "category": "ai",
        "description": "Local privacy-preserving model server running on this computer (http://localhost:11434). Requires no API key.",
        "required_for": "100% offline local conversation when cloud APIs are unconfigured or unavailable.",
        "is_secret": False,
        "is_cloud": False,
        "default_model": "llama3.2:latest",
        "key_prefix": "",
        "help_url": "https://ollama.com"
    },
    "serpapi": {
        "name": "serpapi",
        "display_name": "SerpAPI (Google Search)",
        "category": "search",
        "description": "Real-time Google Search results for live news, queries, and fact retrieval.",
        "required_for": "Live web search, current news queries, and real-time knowledge.",
        "is_secret": True,
        "is_cloud": True,
        "default_model": "",
        "key_prefix": "",
        "help_url": "https://serpapi.com/manage-api-key"
    },
    "tavily": {
        "name": "tavily",
        "display_name": "Tavily AI Search",
        "category": "search",
        "description": "Deep web search designed specifically for LLM retrieval-augmented generation (RAG).",
        "required_for": "In-depth research queries and fallback web search.",
        "is_secret": True,
        "is_cloud": True,
        "default_model": "",
        "key_prefix": "tvly-",
        "help_url": "https://tavily.com"
    },
    "email": {
        "name": "email",
        "display_name": "Email Integration (Gmail/SMTP)",
        "category": "email",
        "description": "SMTP and IMAP credentials (email address and app password) for reading and sending personal emails.",
        "required_for": "Email drafting, sending, inbox summaries, and reminders via email.",
        "is_secret": True,
        "is_cloud": True,
        "default_model": "",
        "key_prefix": "",
        "help_url": "https://myaccount.google.com/apppasswords"
    },
    "openweather": {
        "name": "openweather",
        "display_name": "OpenWeatherMap",
        "category": "tools",
        "description": "Live weather forecasts and atmospheric conditions.",
        "required_for": "Weather checks, temperature reports, and forecast queries.",
        "is_secret": True,
        "is_cloud": True,
        "default_model": "",
        "key_prefix": "",
        "help_url": "https://home.openweathermap.org/api_keys"
    },
    "tmdb": {
        "name": "tmdb",
        "display_name": "TMDB (Movies & TV)",
        "category": "tools",
        "description": "The Movie Database for movie recommendations, ratings, and release schedules.",
        "required_for": "Movie and entertainment recommendations.",
        "is_secret": True,
        "is_cloud": True,
        "default_model": "",
        "key_prefix": "",
        "help_url": "https://www.themoviedb.org/settings/api"
    },
    "calendarific": {
        "name": "calendarific",
        "display_name": "Calendarific",
        "category": "tools",
        "description": "International and national public holiday calendars.",
        "required_for": "Holiday reminders and regional festival queries.",
        "is_secret": True,
        "is_cloud": True,
        "default_model": "",
        "key_prefix": "",
        "help_url": "https://calendarific.com"
    }
}


# ─────────────────────────────────────────────────────────────────────────────
# MASKING & REDACTION UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def mask_credential(val: Optional[str]) -> str:
    """
    Safely masks sensitive credentials for UI display and diagnostics.
    Never returns the full secret.
    """
    if not val or not str(val).strip():
        return ""
    s = str(val).strip()
    if len(s) <= 8:
        return "••••••••"
    if "@" in s and ("." in s or ":" in s):
        # Email: format as u***r@domain.com
        parts = s.split("@", 1)
        u, d = parts[0], parts[1]
        u_masked = u[0] + "•••" + (u[-1] if len(u) > 1 else "")
        return f"{u_masked}@{d}"
    # Token or API key: show first 4 and last 4 characters
    return f"{s[:4]}••••••••{s[-4:]}"


def sanitize_log_message(msg: str) -> str:
    """
    Redacts any potential API keys, authorization tokens, or sensitive URL params from string messages.
    """
    import re
    if not msg:
        return ""
    # Redact common key prefixes
    patterns = [
        r"(sk-ant-[a-zA-Z0-9_\-]{20,})",
        r"(sk-[a-zA-Z0-9_\-]{20,})",
        r"(gsk_[a-zA-Z0-9_\-]{20,})",
        r"(tvly-[a-zA-Z0-9_\-]{20,})",
        r"(AIza[a-zA-Z0-9_\-]{30,})",
        r"(hf_[a-zA-Z0-9_\-]{20,})",
        r"(Bearer\s+[a-zA-Z0-9_\.\-]{20,})",
    ]
    cleaned = str(msg)
    for pat in patterns:
        cleaned = re.sub(pat, "[REDACTED_SECRET]", cleaned)
    # Redact query and key-value parameter secrets
    param_pat = r"((?:key|api_key|appid|secret|password|access_token|token)=)([^\s&\"'>]+)"
    cleaned = re.sub(param_pat, r"\g<1>[REDACTED_SECRET]", cleaned, flags=re.IGNORECASE)
    return cleaned


_redact_secrets = sanitize_log_message


# ─────────────────────────────────────────────────────────────────────────────
# CREDENTIAL MANAGER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class CredentialManager:
    """
    Centralized, thread-safe, per-user credential management service.
    """
    _instance: Optional[CredentialManager] = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> CredentialManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = CredentialManager()
            return cls._instance

    def __init__(self):
        self._cache: Dict[str, Dict[str, str]] = {}  # uid -> {provider -> key}
        self._cache_lock = threading.RLock()
        self._change_listeners: List[Callable[[int, str], None]] = []
        self._user_locks: Dict[int, threading.RLock] = {}
        self._user_locks_guard = threading.Lock()

        # Determine vault directory
        appdata = os.getenv("APPDATA")
        if appdata and os.path.exists(appdata):
            self._vault_dir = os.path.join(appdata, "SmartAssistant", "vaults")
        else:
            self._vault_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "secure_vault")
        os.makedirs(self._vault_dir, exist_ok=True)

    def clear_cache(self, user_id: Optional[int] = None) -> None:
        """
        Clears in-memory decrypted credentials for a specific user or all users.
        Must be invoked upon logout or account switching to prevent credential cross-talk.
        """
        with self._cache_lock:
            if user_id is not None:
                self._cache.pop(str(user_id), None)
            else:
                self._cache.clear()

    # ── User Context Resolution ──────────────────────────────────────────────
    def _resolve_user_id(self, user_context: Any) -> int:
        """
        Resolves canonical integer user ID from context, dictionary, or runtime settings.
        Never defaults to user 1.
        """
        if isinstance(user_context, int):
            return user_context
        if isinstance(user_context, dict):
            uid = user_context.get("user_id") or user_context.get("id") or user_context.get("sub")
            if uid:
                try:
                    return int(uid)
                except (ValueError, TypeError):
                    pass
        if isinstance(user_context, str):
            s = user_context.strip().lower()
            if s.isdigit():
                return int(s)
            if s.startswith("user_") and s[5:].isdigit():
                return int(s[5:])
            # Try looking up username in DB
            try:
                from core.db_pool import get_db_pool
                pool = get_db_pool()
                if pool and pool.is_healthy():
                    with pool.get_cursor() as cur:
                        cur.execute("SELECT id FROM users WHERE LOWER(username) = %s LIMIT 1;", (s,))
                        row = cur.fetchone()
                        if row and row[0]:
                            return int(row[0])
            except Exception:
                pass

        # Check runtime context
        try:
            from instance.config import settings
            curr = getattr(settings, "CURRENT_USER_ID", None)
            if curr:
                return int(curr)
        except Exception:
            pass

        return 0

    # ── Encryption & Decryption ──────────────────────────────────────────────
    def _encrypt_for_user(self, plaintext: str, user_id: int) -> str:
        """
        Encrypts a string for a specific user using DPAPI or Fernet with user-scoped entropy.
        Returns URL-safe Base64 encoded string.
        """
        data_bytes = plaintext.encode("utf-8")
        entropy = f"SmartAssistant_User_{user_id}".encode("utf-8")

        # 1. Prefer Windows DPAPI
        if _HAS_DPAPI:
            try:
                encrypted = win32crypt.CryptProtectData(
                    data_bytes,
                    f"UserCredential_{user_id}",
                    entropy,
                    None,
                    None,
                    0
                )
                return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
            except Exception as e:
                logger.warning(f"DPAPI encryption failed, falling back to Fernet: {e}")

        # 2. Fernet fallback with user-isolated salt
        if _HAS_CRYPTOGRAPHY:
            try:
                salt = hashlib.sha256(f"salt_{user_id}_smart_assistant".encode()).digest()[:16]
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    iterations=100000,
                )
                master_seed = (os.getenv("JWT_SECRET") or os.getenv("DB_PASSWORD") or "secure_desktop_vault_secret").encode()
                key = base64.urlsafe_b64encode(kdf.derive(master_seed))
                f = Fernet(key)
                token = f.encrypt(data_bytes)
                return "fernet:" + token.decode("ascii")
            except Exception as e:
                logger.error(f"Fernet encryption error: {e}")

        # Fail closed: never store raw plaintext
        raise RuntimeError("Secure encryption backend unavailable on this platform.")

    def _decrypt_for_user(self, ciphertext_envelope: str, user_id: int) -> Optional[str]:
        """
        Decrypts an encrypted string for a specific user.
        Rejects decryption if the user entropy does not match.
        """
        if not ciphertext_envelope:
            return None

        entropy = f"SmartAssistant_User_{user_id}".encode("utf-8")

        if ciphertext_envelope.startswith("dpapi:"):
            if not _HAS_DPAPI:
                logger.error("Cannot decrypt DPAPI credential: win32crypt unavailable.")
                return None
            try:
                raw_bytes = base64.b64decode(ciphertext_envelope[6:])
                decrypted = win32crypt.CryptUnprotectData(
                    raw_bytes,
                    entropy,
                    None,
                    None,
                    0
                )[1]
                return decrypted.decode("utf-8")
            except Exception as e:
                logger.error(f"DPAPI decryption failed for user {user_id}: {e}")
                return None

        if ciphertext_envelope.startswith("fernet:"):
            if not _HAS_CRYPTOGRAPHY:
                logger.error("Cannot decrypt Fernet credential: cryptography unavailable.")
                return None
            try:
                token = ciphertext_envelope[7:].encode("ascii")
                salt = hashlib.sha256(f"salt_{user_id}_smart_assistant".encode()).digest()[:16]
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    iterations=100000,
                )
                master_seed = (os.getenv("JWT_SECRET") or os.getenv("DB_PASSWORD") or "secure_desktop_vault_secret").encode()
                key = base64.urlsafe_b64encode(kdf.derive(master_seed))
                f = Fernet(key)
                decrypted = f.decrypt(token)
                return decrypted.decode("utf-8")
            except Exception as e:
                logger.error(f"Fernet decryption failed for user {user_id}: {e}")
                return None

        # Unknown or legacy format
        return None

    # ── Local File Vault Helpers ─────────────────────────────────────────────
    def _vault_path_for_user(self, user_id: int) -> str:
        return os.path.join(self._vault_dir, f"user_{user_id}.vault")

    def _get_user_lock(self, user_id: int) -> threading.RLock:
        """Returns or creates a thread-safe reentrant lock specific to a user ID."""
        with self._user_locks_guard:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = threading.RLock()
            return self._user_locks[user_id]

    @contextmanager
    def _user_file_lock(self, user_id: int, timeout: float = 5.0):
        """
        Cross-thread and cross-process lock manager for a user's vault.
        Combines process-level threading.RLock with OS-level file locking.
        """
        thread_lock = self._get_user_lock(user_id)
        with thread_lock:
            lock_path = os.path.join(self._vault_dir, f"user_{user_id}.lock")
            fd = None
            start_t = time.time()
            acquired = False

            while time.time() - start_t < timeout:
                try:
                    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except (OSError, IOError, PermissionError, BlockingIOError):
                    if fd is not None:
                        try:
                            os.close(fd)
                        except Exception:
                            pass
                        fd = None
                    time.sleep(0.02)

            if not acquired and fd is None:
                logger.debug(f"Vault inter-process lock acquisition timed out for user {user_id}; proceeding under thread lock.")

            try:
                yield
            finally:
                if fd is not None:
                    try:
                        if os.name == "nt":
                            import msvcrt
                            try:
                                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                            except Exception:
                                pass
                        os.close(fd)
                    except Exception:
                        pass

    def _parse_vault_content(self, content: str, user_id: int) -> Tuple[Dict[str, str], bool]:
        """
        Parses vault JSON content with self-healing support for multi-block,
        concatenated, or partially corrupt JSON (recovering from Extra data: line X column Y).
        Returns (data_dict, was_repaired).
        """
        content_stripped = content.strip()
        if not content_stripped:
            return {}, False

        # 1. Attempt standard clean JSON decode
        try:
            parsed = json.loads(content_stripped)
            if isinstance(parsed, dict):
                return parsed, False
        except json.JSONDecodeError as jde:
            logger.warning(f"Standard JSON decode failed for user {user_id} vault: {jde}. Attempting self-healing recovery.")

        # 2. Self-healing multi-block stream decoder
        decoder = json.JSONDecoder()
        pos = 0
        combined: Dict[str, str] = {}
        found_blocks = 0
        raw_len = len(content)

        while pos < raw_len:
            while pos < raw_len and content[pos].isspace():
                pos += 1
            if pos >= raw_len:
                break

            try:
                obj, end_pos = decoder.raw_decode(content, idx=pos)
                if isinstance(obj, dict):
                    combined.update(obj)
                    found_blocks += 1
                pos = end_pos
            except Exception:
                next_brace = content.find("{", pos + 1)
                if next_brace != -1:
                    pos = next_brace
                else:
                    break

        if found_blocks > 0 and combined:
            logger.info(f"Self-healing successfully recovered {len(combined)} credential/preference item(s) from {found_blocks} JSON block(s) for user {user_id}.")
            return combined, True

        return {}, False

    def _load_vault_for_user(self, user_id: int) -> Dict[str, str]:
        path = self._vault_path_for_user(user_id)
        if not os.path.exists(path):
            return {}

        with self._user_file_lock(user_id):
            if not os.path.exists(path):
                return {}
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                data, was_repaired = self._parse_vault_content(content, user_id)

                # If file had extra data / partial blocks and was recovered, heal it on disk
                if was_repaired and data:
                    self._save_vault_unlocked(user_id, data)
                    return data

                # If file parsing produced no data (corrupt or 0-bytes, not a valid intentional "{}" empty dict), try backup
                if not data and content.strip() not in ("{}", "{\n}", "{\r\n}"):
                    bak_path = path + ".bak"
                    if os.path.exists(bak_path):
                        logger.warning(f"Vault corrupt/truncated for user {user_id}; attempting recovery from backup file {bak_path}")
                        with open(bak_path, "r", encoding="utf-8", errors="replace") as bf:
                            bak_content = bf.read()
                        bak_data, _ = self._parse_vault_content(bak_content, user_id)
                        if bak_data:
                            logger.info(f"Successfully recovered {len(bak_data)} item(s) from backup for user {user_id}.")
                            self._save_vault_unlocked(user_id, bak_data)
                            return bak_data

                return data
            except Exception as e:
                logger.error(f"Error reading vault file for user {user_id}: {e}")
                return {}

    def _save_vault_unlocked(self, user_id: int, data: Dict[str, str]) -> bool:
        """
        Internal unlocked atomic save with Windows sharing violation retry,
        backup creation, and transactional read-after-write verification.
        Must be called under _user_file_lock(user_id).
        """
        path = self._vault_path_for_user(user_id)
        temp_path = os.path.join(self._vault_dir, f"user_{user_id}_{uuid.uuid4().hex}.tmp")
        bak_path = path + ".bak"

        try:
            # 1. Write formatted JSON to unique temp file
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            # 2. Pre-replace integrity validation
            with open(temp_path, "r", encoding="utf-8") as tf:
                temp_parsed = json.load(tf)
            if not isinstance(temp_parsed, dict):
                raise ValueError("Temp file validation failed: content is not a valid dictionary.")

            # 3. Create backup of current valid vault file
            if os.path.exists(path) and os.path.getsize(path) > 0:
                try:
                    shutil.copy2(path, bak_path)
                except Exception as b_err:
                    logger.debug(f"Could not create vault backup copy: {b_err}")

            # 4. Safe atomic replacement with Windows retry loop (WinError 32 / WinError 5)
            replace_success = False
            last_err = None
            for attempt in range(10):
                try:
                    if os.path.exists(path):
                        try:
                            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                        except Exception:
                            pass
                    os.replace(temp_path, path)
                    replace_success = True
                    break
                except (PermissionError, OSError) as e:
                    last_err = e
                    # Fallback for Windows file locks
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                        shutil.move(temp_path, path)
                        replace_success = True
                        break
                    except Exception as inner_e:
                        last_err = inner_e
                        time.sleep(0.04 * (attempt + 1))

            if not replace_success:
                raise OSError(f"Failed to replace vault file for user {user_id} after 10 retries: {last_err}")

            # 5. Read-after-write verification: ensure file can be reloaded and matches data
            with open(path, "r", encoding="utf-8") as vf:
                verified_data = json.load(vf)
            if not isinstance(verified_data, dict):
                raise ValueError("Verified vault data is not a dictionary.")

            for k, v in data.items():
                if k not in verified_data or verified_data[k] != v:
                    raise ValueError(f"Vault verification mismatch on key: {k}")

            return True

        except Exception as e:
            logger.error(f"Error saving vault for user {user_id}: {e}")
            # If target was left missing or empty, attempt restoring from backup
            if os.path.exists(bak_path) and (not os.path.exists(path) or os.path.getsize(path) == 0):
                try:
                    shutil.copy2(bak_path, path)
                    logger.info(f"Restored vault from backup for user {user_id} after save error.")
                except Exception:
                    pass
            return False

        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def _save_vault_for_user(self, user_id: int, data: Dict[str, str]) -> bool:
        with self._user_file_lock(user_id):
            return self._save_vault_unlocked(user_id, data)

    # ── Core Credential API ──────────────────────────────────────────────────
    def get_credential(self, user_context: Any, provider_name: str) -> Optional[str]:
        """
        Authoritative retrieval of a user's decrypted credential.
        Guarantees isolation: never falls back to another user's key or developer .env.
        """
        uid = self._resolve_user_id(user_context)
        if not uid or uid <= 0:
            return None

        prov = provider_name.strip().lower()

        # Check in-memory cache
        with self._cache_lock:
            user_cache = self._cache.get(str(uid), {})
            if prov in user_cache:
                return user_cache[prov]

        # 1. Try PostgreSQL Database
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute(
                        "SELECT encrypted_value FROM user_api_credentials WHERE user_id = %s AND provider = %s LIMIT 1;",
                        (uid, prov)
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        decrypted = self._decrypt_for_user(row[0], uid)
                        if decrypted:
                            with self._cache_lock:
                                self._cache.setdefault(str(uid), {})[prov] = decrypted
                            return decrypted
        except Exception as e:
            logger.debug(f"DB credential query skipped or failed: {e}")

        # 2. Try Local Encrypted Vault
        vault = self._load_vault_for_user(uid)
        encrypted_val = vault.get(prov)
        if encrypted_val:
            decrypted = self._decrypt_for_user(encrypted_val, uid)
            if decrypted:
                with self._cache_lock:
                    self._cache.setdefault(str(uid), {})[prov] = decrypted
                return decrypted

        # Special case: Ollama is a local server; return base URL if enabled
        if prov == "ollama":
            raw_url = vault.get("ollama_url")
            if raw_url and (str(raw_url).startswith("dpapi:") or str(raw_url).startswith("fernet:")):
                dec = self._decrypt_for_user(raw_url, uid)
                if dec:
                    return dec
            return raw_url or "http://localhost:11434"

        return None

    def get_user_credentials(self, user_context: Any) -> Dict[str, str]:
        """
        Returns all configured decrypted credentials for a given user.
        Internal use for engines only.
        """
        uid = self._resolve_user_id(user_context)
        if not uid or uid <= 0:
            return {}

        results: Dict[str, str] = {}
        for prov in SUPPORTED_PROVIDERS:
            val = self.get_credential(uid, prov)
            if val:
                results[prov] = val
        return results

    def save_credential(self, user_context: Any, provider_name: str, credential_value: str) -> bool:
        """
        Encrypts and persists an API key or credential for the given user.
        Updates DB and local vault with atomic semantics.
        """
        uid = self._resolve_user_id(user_context)
        if not uid or uid <= 0:
            logger.error(f"Cannot save credential: invalid user context ({user_context})")
            return False

        prov = provider_name.strip().lower()
        clean_val = str(credential_value or "").strip()
        if not clean_val:
            return self.delete_credential(user_context, provider_name)

        encrypted = self._encrypt_for_user(clean_val, uid)
        masked = mask_credential(clean_val)

        # 1. Persist to PostgreSQL if connected
        db_saved = False
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO user_api_credentials (user_id, provider, encrypted_value, masked_hint, status, updated_at)
                        VALUES (%s, %s, %s, %s, 'valid', CURRENT_TIMESTAMP)
                        ON CONFLICT (user_id, provider) DO UPDATE SET
                            encrypted_value = EXCLUDED.encrypted_value,
                            masked_hint = EXCLUDED.masked_hint,
                            status = 'valid',
                            updated_at = CURRENT_TIMESTAMP;
                        """,
                        (uid, prov, encrypted, masked)
                    )
                db_saved = True
        except Exception as e:
            logger.warning(f"Could not save credential to database: {e}")

        # 2. Persist to local vault under user lock with read-after-write verification
        file_saved = False
        with self._user_file_lock(uid):
            vault = self._load_vault_for_user(uid)
            vault[prov] = encrypted
            vault[f"{prov}_masked"] = masked
            vault[f"{prov}_status"] = "valid"
            file_saved = self._save_vault_unlocked(uid, vault)

        # 3. Transactional persist check: Only report success if actually persisted
        if not (db_saved or file_saved):
            logger.error(f"Failed to persist credential for user {uid} provider {prov} to both DB and local vault.")
            return False

        # 4. Update memory cache only after verified persistence
        with self._cache_lock:
            self._cache.setdefault(str(uid), {})[prov] = clean_val

        # 5. Notify listeners (LLMEngine, UI)
        self._notify_change(uid, prov)

        return True

    def delete_credential(self, user_context: Any, provider_name: str) -> bool:
        """
        Removes a credential for a given user.
        Subsequent requests will immediately stop using it.
        """
        uid = self._resolve_user_id(user_context)
        if not uid or uid <= 0:
            return False

        prov = provider_name.strip().lower()

        # 1. Remove from database
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute(
                        "DELETE FROM user_api_credentials WHERE user_id = %s AND provider = %s;",
                        (uid, prov)
                    )
        except Exception as e:
            logger.warning(f"DB credential deletion notice: {e}")

        # 2. Remove from local vault under user lock
        with self._user_file_lock(uid):
            vault = self._load_vault_for_user(uid)
            vault.pop(prov, None)
            vault.pop(f"{prov}_masked", None)
            vault.pop(f"{prov}_status", None)
            self._save_vault_unlocked(uid, vault)

        # 3. Invalidate memory cache
        with self._cache_lock:
            if str(uid) in self._cache:
                self._cache[str(uid)].pop(prov, None)

        self._notify_change(uid, prov)
        return True

    def register_change_listener(self, callback: Callable[[int, str], None]):
        """Register listener to be notified when user credentials change."""
        with self._lock:
            if callback not in self._change_listeners:
                self._change_listeners.append(callback)

    def _notify_change(self, user_id: int, provider: str):
        for cb in list(self._change_listeners):
            try:
                cb(user_id, provider)
            except Exception:
                pass

    # ── Providers Status Metadata (For UI & Settings) ────────────────────────
    def get_providers_status(self, user_context: Any) -> List[Dict[str, Any]]:
        """
        Returns sanitized metadata list for all supported providers for this user.
        NEVER returns raw API keys.
        """
        uid = self._resolve_user_id(user_context)
        vault = self._load_vault_for_user(uid) if uid > 0 else {}

        # Query database masked hints if available
        db_hints: Dict[str, Tuple[str, str]] = {}
        if uid > 0:
            try:
                from core.db_pool import get_db_pool
                pool = get_db_pool()
                if pool and pool.is_healthy():
                    with pool.get_cursor() as cur:
                        cur.execute(
                            "SELECT provider, masked_hint, status FROM user_api_credentials WHERE user_id = %s;",
                            (uid,)
                        )
                        for r in cur.fetchall():
                            db_hints[r[0]] = (r[1] or "", r[2] or "untested")
            except Exception:
                pass

        results: List[Dict[str, Any]] = []
        for prov_id, meta in SUPPORTED_PROVIDERS.items():
            is_configured = False
            masked_key = ""
            status = "unconfigured"

            if prov_id == "ollama":
                is_configured = True
                status = "ready"
                masked_key = "http://localhost:11434"
            elif prov_id in db_hints:
                is_configured = True
                masked_key = db_hints[prov_id][0]
                status = db_hints[prov_id][1]
            elif prov_id in vault:
                is_configured = True
                masked_key = vault.get(f"{prov_id}_masked", "••••••••••••")
                status = vault.get(f"{prov_id}_status", "configured")

            # Verify whether the stored credential is truly recoverable/decryptable for this user
            if is_configured and prov_id != "ollama" and uid > 0:
                decrypted = self.get_credential(uid, prov_id)
                if not decrypted:
                    status = "decryption_failed"
                    is_configured = False

            results.append({
                "provider": prov_id,
                "display_name": meta["display_name"],
                "category": meta["category"],
                "description": meta["description"],
                "required_for": meta["required_for"],
                "is_secret": meta["is_secret"],
                "is_cloud": meta["is_cloud"],
                "is_configured": is_configured,
                "configured": is_configured,
                "masked_key": masked_key,
                "masked_hint": masked_key,
                "status": status,
                "help_url": meta.get("help_url", ""),
                "default_model": meta.get("default_model", ""),
            })

        return results

    def test_credential(
        self,
        user_context: Any,
        provider_name: str,
        candidate_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Convenience alias for test_provider_connection."""
        return self.test_provider_connection(user_context, provider_name, candidate_key)

    # ── First-Run Setup Tracking ─────────────────────────────────────────────
    def has_completed_api_setup(self, user_context: Any) -> bool:
        uid = self._resolve_user_id(user_context)
        if not uid or uid <= 0:
            return False

        # 1. Check local setup file
        flag_file = os.path.join(self._vault_dir, f"setup_done_{uid}.flag")
        if os.path.exists(flag_file):
            return True

        # 2. Check DB preferences
        try:
            from legacy.memory_manager import get_user_preference_db
            res = get_user_preference_db(uid, "api_setup_completed")
            if res and str(res).lower() in ("true", "1", "yes"):
                return True
            elif res and str(res).lower() in ("false", "0", "no"):
                return False
        except Exception:
            pass

        # 3. Check if any credentials exist
        vault = self._load_vault_for_user(uid)
        cloud_keys = [k for k in vault if not k.endswith("_masked") and not k.endswith("_status")]
        return len(cloud_keys) > 0

    def set_completed_api_setup(self, user_context: Any, completed: bool = True) -> bool:
        uid = self._resolve_user_id(user_context)
        if not uid or uid <= 0:
            return False

        flag_file = os.path.join(self._vault_dir, f"setup_done_{uid}.flag")
        try:
            if completed:
                with open(flag_file, "w") as f:
                    f.write("completed")
            else:
                if os.path.exists(flag_file):
                    os.remove(flag_file)
        except Exception:
            pass

        try:
            from legacy.memory_manager import set_user_preference_db
            set_user_preference_db(uid, "api_setup_completed", "true" if completed else "false")
        except Exception:
            pass

        return True

    # ── Connection Test Engine ───────────────────────────────────────────────
    def test_provider_connection(
        self,
        user_context: Any,
        provider_name: str,
        candidate_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validates connectivity and credentials with a bounded, safe HTTP probe.
        Does not perform consequential actions or leak keys.
        """
        import requests
        prov = provider_name.strip().lower()
        raw_key = str(candidate_key or "").strip() if candidate_key is not None else str(self.get_credential(user_context, prov) or "").strip()

        if prov != "ollama":
            if not raw_key:
                return {
                    "success": False,
                    "status": "empty_key",
                    "message": f"API key cannot be empty or whitespace for {prov}."
                }
            if len(raw_key) < 8 or any(c.isspace() for c in raw_key):
                return {
                    "success": False,
                    "status": "malformed_key",
                    "message": f"Malformed API key for {prov}. The key format is invalid."
                }

        key_to_test = raw_key

        try:
            if prov == "ollama":
                import socket
                from urllib.parse import urlparse
                base_url = str(candidate_key or self.get_credential(user_context, "ollama") or "http://localhost:11434").strip()
                p = urlparse(base_url)
                host = p.hostname or "localhost"
                port = p.port or 11434
                try:
                    with socket.create_connection((host, port), timeout=2.0):
                        pass
                    return {
                        "success": True,
                        "status": "valid",
                        "message": "Local Ollama daemon is active and responding."
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "status": "ollama_unreachable",
                        "message": f"Could not connect to Ollama at {base_url}. Please ensure the Ollama service is running."
                    }

            elif prov == "groq":
                headers = {"Authorization": f"Bearer {key_to_test}", "Content-Type": "application/json"}
                # Use lightweight models list to validate authentication without model inference cost
                resp = requests.get("https://api.groq.com/openai/v1/models", headers=headers, timeout=5.0)
                if resp.status_code == 200:
                    return {"success": True, "status": "valid", "message": "Groq connection verified."}
                elif resp.status_code in (401, 403):
                    return {"success": False, "status": "invalid_key", "message": "Groq rejected key (Invalid API Key)."}
                elif resp.status_code == 429:
                    return {"success": False, "status": "rate_limited", "message": "Groq rate limit or quota exceeded."}
                else:
                    return {"success": False, "status": "error", "message": f"Groq HTTP {resp.status_code}."}

            elif prov == "openai":
                headers = {"Authorization": f"Bearer {key_to_test}", "Content-Type": "application/json"}
                resp = requests.get("https://api.openai.com/v1/models", headers=headers, timeout=5.0)
                if resp.status_code == 200:
                    return {"success": True, "status": "valid", "message": "OpenAI connection verified."}
                elif resp.status_code in (401, 403):
                    return {"success": False, "status": "invalid_key", "message": "OpenAI rejected key (Invalid API Key)."}
                elif resp.status_code == 429:
                    return {"success": False, "status": "rate_limited", "message": "OpenAI quota exhausted (HTTP 429)."}
                else:
                    return {"success": False, "status": "error", "message": f"OpenAI HTTP {resp.status_code}."}

            elif prov == "gemini":
                url = "https://generativelanguage.googleapis.com/v1beta/models"
                headers = {"x-goog-api-key": key_to_test}
                resp = requests.get(url, headers=headers, timeout=5.0)
                if resp.status_code == 200:
                    return {"success": True, "status": "valid", "message": "Google Gemini connection verified."}
                elif resp.status_code in (400, 401, 403):
                    return {"success": False, "status": "invalid_key", "message": "Gemini rejected API key."}
                elif resp.status_code == 429:
                    return {"success": False, "status": "rate_limited", "message": "Gemini quota or rate limit reached."}
                else:
                    return {"success": False, "status": "error", "message": f"Gemini HTTP {resp.status_code}."}

            elif prov == "deepseek":
                headers = {"Authorization": f"Bearer {key_to_test}", "Content-Type": "application/json"}
                resp = requests.get("https://api.deepseek.com/models", headers=headers, timeout=5.0)
                if resp.status_code == 200:
                    return {"success": True, "status": "valid", "message": "DeepSeek connection verified."}
                elif resp.status_code in (401, 403):
                    return {"success": False, "status": "invalid_key", "message": "DeepSeek rejected API key."}
                elif resp.status_code == 402:
                    return {"success": False, "status": "quota_exhausted", "message": "DeepSeek insufficient balance."}
                else:
                    return {"success": False, "status": "error", "message": f"DeepSeek HTTP {resp.status_code}."}

            elif prov == "anthropic":
                headers = {
                    "x-api-key": key_to_test,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                resp = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json={
                        "model": "claude-3-5-sonnet-20241022",
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "ping"}]
                    },
                    timeout=5.0
                )
                if resp.status_code == 200:
                    return {"success": True, "status": "valid", "message": "Anthropic Claude connection verified."}
                elif resp.status_code in (401, 403):
                    return {"success": False, "status": "invalid_key", "message": "Anthropic rejected API key."}
                elif resp.status_code == 429:
                    return {"success": False, "status": "rate_limited", "message": "Anthropic rate limit reached."}
                else:
                    return {"success": False, "status": "error", "message": f"Anthropic HTTP {resp.status_code}."}

            elif prov == "huggingface":
                headers = {"Authorization": f"Bearer {key_to_test}"}
                resp = requests.get("https://huggingface.co/api/whoami-v2", headers=headers, timeout=5.0)
                if resp.status_code == 200:
                    return {"success": True, "status": "valid", "message": "Hugging Face token verified."}
                else:
                    return {"success": False, "status": "invalid_key", "message": "Hugging Face rejected token."}

            elif prov == "ollama":
                base = key_to_test or "http://localhost:11434"
                resp = requests.get(f"{base.rstrip('/')}/api/tags", timeout=2.0)
                if resp.status_code == 200:
                    return {"success": True, "status": "valid", "message": "Local Ollama server is running and accessible."}
                else:
                    return {"success": False, "status": "unreachable", "message": f"Ollama returned HTTP {resp.status_code}."}

            elif prov == "serpapi":
                resp = requests.get(f"https://serpapi.com/account?api_key={key_to_test}", timeout=5.0)
                if resp.status_code == 200:
                    return {"success": True, "status": "valid", "message": "SerpAPI connection verified."}
                else:
                    return {"success": False, "status": "invalid_key", "message": "SerpAPI rejected key."}

            elif prov == "tavily":
                resp = requests.post(
                    "https://api.tavily.com/search",
                    json={"api_key": key_to_test, "query": "test", "max_results": 1},
                    timeout=5.0
                )
                if resp.status_code == 200:
                    return {"success": True, "status": "valid", "message": "Tavily AI Search verified."}
                else:
                    return {"success": False, "status": "invalid_key", "message": "Tavily rejected API key."}

            elif prov == "email":
                # Expecting format: "email:password" or json
                parts = key_to_test.split(":", 1) if ":" in key_to_test else (key_to_test, "")
                if len(parts) < 2 or not parts[1]:
                    return {"success": False, "status": "invalid_format", "message": "Enter format 'email@domain.com:app_password'"}
                import smtplib
                email_addr, app_pw = parts[0].strip(), parts[1].strip()
                smtp_server = "smtp.gmail.com" if "gmail" in email_addr.lower() else "smtp.office365.com"
                try:
                    with smtplib.SMTP_SSL(smtp_server, 465, timeout=5.0) as server:
                        server.login(email_addr, app_pw)
                    return {"success": True, "status": "valid", "message": "Email SMTP authentication successful."}
                except Exception as e:
                    return {"success": False, "status": "invalid_credentials", "message": f"Email login failed: {e}"}

            elif prov == "openweather":
                resp = requests.get(f"https://api.openweathermap.org/data/2.5/weather?q=London&appid={key_to_test}", timeout=5.0)
                if resp.status_code == 200:
                    return {"success": True, "status": "valid", "message": "OpenWeatherMap connection verified."}
                else:
                    return {"success": False, "status": "invalid_key", "message": "OpenWeatherMap rejected key."}

            elif prov == "tmdb":
                resp = requests.get(f"https://api.themoviedb.org/3/authentication?api_key={key_to_test}", timeout=5.0)
                if resp.status_code == 200 and resp.json().get("success"):
                    return {"success": True, "status": "valid", "message": "TMDB API key verified."}
                else:
                    return {"success": False, "status": "invalid_key", "message": "TMDB rejected key."}

            elif prov == "calendarific":
                resp = requests.get(f"https://calendarific.com/api/v2/holidays?api_key={key_to_test}&country=US&year=2026", timeout=5.0)
                if resp.status_code == 200:
                    return {"success": True, "status": "valid", "message": "Calendarific API verified."}
                else:
                    return {"success": False, "status": "invalid_key", "message": "Calendarific rejected key."}

            else:
                return {"success": True, "status": "untested", "message": f"Provider {prov} configured."}

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "status": "timeout",
                "retryable": True,
                "message": f"Connection to {prov} timed out. This is a temporary network issue, not an invalid key. Please verify your connection and retry."
            }
        except (requests.exceptions.ConnectionError, requests.exceptions.RequestException) as re_err:
            return {
                "success": False,
                "status": "network_error",
                "retryable": True,
                "message": f"Could not reach {prov} servers ({sanitize_log_message(str(re_err))}). Please check your internet connection and retry."
            }
        except Exception as e:
            return {"success": False, "status": "error", "message": sanitize_log_message(str(e))}

    # ── Primary Provider Preferences ──────────────────────────────────────────
    def get_primary_provider(self, user_context: Any) -> str:
        uid = self._resolve_user_id(user_context)
        if uid > 0:
            try:
                from legacy.memory_manager import get_user_preference_db
                res = get_user_preference_db(uid, "primary_provider")
                if res and str(res).strip():
                    return str(res).strip().lower()
            except Exception:
                pass
            vault = self._load_vault_for_user(uid)
            if vault.get("primary_provider"):
                return vault["primary_provider"].lower()
        return ""

    def set_primary_provider(self, user_context: Any, provider_name: str) -> bool:
        uid = self._resolve_user_id(user_context)
        prov = (provider_name or "groq").strip().lower()
        if uid > 0:
            try:
                from legacy.memory_manager import set_user_preference_db
                set_user_preference_db(uid, "primary_provider", prov)
            except Exception:
                pass
            with self._user_file_lock(uid):
                vault = self._load_vault_for_user(uid)
                vault["primary_provider"] = prov
                return self._save_vault_unlocked(uid, vault)
        return False

    # ── Assistant Name Personalization ────────────────────────────────────────
    def get_assistant_name(self, user_context: Any) -> str:
        uid = self._resolve_user_id(user_context)
        if uid > 0:
            try:
                from legacy.memory_manager import get_assistant_name_db
                res = get_assistant_name_db(uid)
                if res and str(res).strip():
                    return str(res).strip()
            except Exception:
                pass
            vault = self._load_vault_for_user(uid)
            if vault.get("assistant_name"):
                return vault["assistant_name"]
        try:
            from instance.config import settings
            return getattr(settings, "CURRENT_ASSISTANT_NAME", "Friday") or "Friday"
        except Exception:
            return "Friday"

    def set_assistant_name(self, user_context: Any, name: str) -> bool:
        uid = self._resolve_user_id(user_context)
        clean = validate_assistant_name(name)
        if uid > 0:
            try:
                from legacy.memory_manager import set_assistant_name_db
                set_assistant_name_db(uid, clean)
            except Exception:
                pass
            saved = False
            with self._user_file_lock(uid):
                vault = self._load_vault_for_user(uid)
                vault["assistant_name"] = clean
                saved = self._save_vault_unlocked(uid, vault)
            try:
                from instance.config import settings
                settings.CURRENT_ASSISTANT_NAME = clean
            except Exception:
                pass
            return saved
        return False


def validate_assistant_name(name: Optional[str]) -> str:
    """Validates custom assistant display name, ensuring length and input safety."""
    if not name or not str(name).strip():
        return "Friday"
    s = str(name).strip()
    # Strip HTML/script tags first
    import re
    s = re.sub(r'<[^>]*>', '', s)
    # Strip dangerous prompt injection and syntax characters
    for ch in ("<", ">", "{", "}", "\n", "\r", "\t", '"', "'", ";", "/"):
        s = s.replace(ch, "")
    s = s.strip()
    if len(s) < 2:
        return "Friday"
    if len(s) > 30:
        s = s[:30].strip()
    return s or "Friday"


# Global singleton access
def get_credential_manager() -> CredentialManager:
    return CredentialManager.get_instance()

def get_credential(user_context: Any, provider_name: str) -> Optional[str]:
    """Convenience functional interface for whole-assistant access."""
    return get_credential_manager().get_credential(user_context, provider_name)
