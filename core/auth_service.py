"""
Smart Assistant — Production Authentication & Token Service
Provides cryptographically secure password hashing (PBKDF2-HMAC-SHA256 with salt),
backward-compatible legacy password upgrade, signed JWT session tokens,
token expiration, refresh, revocation, and security audit logging.
"""

import os
import hmac
import time
import json
import base64
import hashlib
import secrets
from typing import Optional, Dict, Any, Tuple

from core.db_pool import get_db_pool

# Configurable secret for signing tokens
def _init_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    app_env = os.getenv("APP_ENV", "development").lower()
    
    # Insecure known fallbacks that must never be permitted in production
    insecure_fallbacks = {
        "nova-assistant-secure-secret-key-production-389148",
        "trevon-super-secret-jwt-key-change-in-production-2025",
        "secret",
        "changeme"
    }

    if app_env == "production":
        if not secret or secret in insecure_fallbacks:
            raise RuntimeError(
                "CRITICAL SECURITY CONFIGURATION ERROR: "
                "JWT_SECRET environment variable is missing or set to an insecure default in production. "
                "Set a strong random JWT_SECRET in your production environment."
            )
        return secret

    # Development / Testing fallback: generate a cryptographically strong ephemeral secret if none provided
    if not secret or secret in insecure_fallbacks:
        return secrets.token_hex(32)
    return secret

JWT_SECRET = _init_jwt_secret()
DEFAULT_TOKEN_EXPIRY = int(os.getenv("TOKEN_EXPIRY_SECONDS", str(86400 * 7)))  # 7 days default
REFRESH_TOKEN_EXPIRY = int(os.getenv("REFRESH_EXPIRY_SECONDS", str(86400 * 30))) # 30 days default

# Token revocation blacklist in-memory + DB tracking
_token_blacklist = set()


# ── 1. CRYPTOGRAPHIC PASSWORD HASHING ─────────────────────────────────────────

def hash_password(password: str, iterations: int = 100000) -> str:
    """
    Hashes a plaintext password using PBKDF2-HMAC-SHA256 with a random 16-byte salt.
    Format: $pbkdf2-sha256$iterations$salt_hex$hash_hex
    """
    if not password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_bytes(16)
    pw_bytes = password.encode("utf-8")
    derived = hashlib.pbkdf2_hmac("sha256", pw_bytes, salt, iterations)
    return f"$pbkdf2-sha256${iterations}${salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, stored_hash_or_plain: str) -> Tuple[bool, bool]:
    """
    Verifies a plain password against the stored string.
    Returns: (is_valid: bool, needs_rehash: bool)
    Supports legacy plaintext/sha256 passwords and transparently flags them for upgrade.
    """
    if not plain_password or not stored_hash_or_plain:
        return False, False

    # A. Modern PBKDF2 format
    if stored_hash_or_plain.startswith("$pbkdf2-sha256$"):
        try:
            parts = stored_hash_or_plain.split("$")
            # ['', 'pbkdf2-sha256', '100000', salt_hex, hash_hex]
            iterations = int(parts[2])
            salt = bytes.fromhex(parts[3])
            expected_hash = parts[4]

            derived = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations)
            is_valid = hmac.compare_digest(derived.hex(), expected_hash)
            return is_valid, False
        except Exception:
            return False, False

    # B. Legacy SHA256 hex format (64 chars)
    if len(stored_hash_or_plain) == 64 and all(c in "0123456789abcdefABCDEF" for c in stored_hash_or_plain):
        sha_hash = hashlib.sha256(plain_password.encode("utf-8")).hexdigest()
        if hmac.compare_digest(sha_hash.lower(), stored_hash_or_plain.lower()):
            return True, True  # Match! Needs upgrade to PBKDF2

    # C. Legacy Plaintext format
    if hmac.compare_digest(plain_password, stored_hash_or_plain):
        return True, True  # Match! Needs upgrade to PBKDF2

    return False, False


# ── 2. CRYPTOGRAPHIC SIGNED TOKENS (JWT-Style HMAC-SHA256) ───────────────────

def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

def _b64_decode(s: str) -> bytes:
    padding = 4 - (len(s) % 4)
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def generate_token(user_id: int, username: str, expires_in: int = DEFAULT_TOKEN_EXPIRY, token_type: str = "access") -> str:
    """
    Generates a cryptographically signed HMAC-SHA256 JWT-style token.
    Header.Payload.Signature
    """
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": int(user_id),
        "username": username,
        "type": token_type,
        "iat": now,
        "exp": now + expires_in,
        "jti": secrets.token_hex(16)
    }

    header_b64 = _b64_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    sig = hmac.new(JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64_encode(sig)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def _ensure_revocation_table():
    pool = get_db_pool()
    if pool.is_healthy():
        try:
            with pool.get_cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS revoked_tokens (
                        token TEXT PRIMARY KEY,
                        revoked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
        except Exception:
            pass

def is_token_revoked(token: str) -> bool:
    """Check if token is blacklisted in-memory or persisted in DB."""
    if not token:
        return True
    if token in _token_blacklist:
        return True
    pool = get_db_pool()
    if pool.is_healthy():
        try:
            with pool.get_cursor() as cur:
                cur.execute("SELECT 1 FROM revoked_tokens WHERE token = %s LIMIT 1;", (token,))
                if cur.fetchone():
                    _token_blacklist.add(token)
                    return True
        except Exception:
            pass
    return False

def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verifies signature and expiration of a token.
    Returns decoded payload if valid, None otherwise.
    """
    if not token or not isinstance(token, str):
        return None

    if is_token_revoked(token):
        return None

    parts = token.split(".")
    if len(parts) != 3:
        return None

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_sig = hmac.new(JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    expected_sig_b64 = _b64_encode(expected_sig)

    if not hmac.compare_digest(sig_b64, expected_sig_b64):
        return None

    try:
        payload_bytes = _b64_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
        now = int(time.time())
        if payload.get("exp", 0) < now:
            return None  # Expired
        return payload
    except Exception:
        return None


def revoke_token(token: str):
    """Adds a token to the revocation blacklist (in-memory and database)."""
    if not token:
        return
    _token_blacklist.add(token)
    pool = get_db_pool()
    if pool.is_healthy():
        try:
            _ensure_revocation_table()
            with pool.get_cursor() as cur:
                cur.execute(
                    "INSERT INTO revoked_tokens (token) VALUES (%s) ON CONFLICT (token) DO NOTHING;",
                    (token,)
                )
        except Exception as e:
            print(f"[AUTH] [WARN] Could not persist revoked token: {e}")


# ── 3. SECURITY AUDIT LOGGING ─────────────────────────────────────────────────

def log_security_event(user_id: Optional[int], action_name: str, status: str, params: Optional[Dict[str, Any]] = None):
    """
    Logs sensitive security events without ever logging plaintext passwords or secrets.
    """
    pool = get_db_pool()
    if not pool.is_healthy():
        return

    safe_params = {}
    if params:
        for k, v in params.items():
            if any(s in k.lower() for s in ["pass", "secret", "token", "key", "auth"]):
                safe_params[k] = "[REDACTED]"
            else:
                safe_params[k] = str(v)[:200]

    params_str = json.dumps(safe_params)
    try:
        with pool.get_cursor() as cur:
            cur.execute("""
                INSERT INTO security_audit_logs (user_id, action_name, params, status)
                VALUES (%s, %s, %s, %s)
            """, (user_id, action_name, params_str, status))
    except Exception as e:
        print(f"[AUTH AUDIT] [WARN] Could not write security audit log: {e}")


# ── 4. HIGH-LEVEL USER AUTHENTICATION & REGISTRATION ──────────────────────────

def is_username_available(username: str) -> bool:
    """
    Checks if a username is available for registration without creating any database records.
    Safe against SQL injection and empty/whitespace inputs.
    """
    username = (username or "").strip().lower()
    if not username or len(username) < 2:
        return False
    pool = get_db_pool()
    if pool.is_healthy():
        try:
            with pool.get_cursor() as cur:
                cur.execute("SELECT 1 FROM users WHERE LOWER(username) = %s LIMIT 1;", (username,))
                return cur.fetchone() is None
        except Exception as e:
            print(f"[AUTH] Error checking username availability via pool: {e}")
    # Fallback to direct connection if pool is unavailable
    try:
        from legacy.memory_manager import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE LOWER(username) = %s LIMIT 1;", (username,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row is None
    except Exception as e:
        print(f"[AUTH] Error checking username availability via direct conn: {e}")
        return True


def register_user(username: str, password: str) -> Dict[str, Any]:
    """
    Registers a new user with secure password hashing and returns an access token.
    """
    username = (username or "").strip().lower()
    if not username:
        return {"success": False, "error": "Username cannot be empty."}
    if not password or len(password) < 4:
        return {"success": False, "error": "Password must be at least 4 characters long."}

    pool = get_db_pool()
    if not pool.is_healthy():
        return {"success": False, "error": "Database service is temporarily offline."}

    # Hash the password
    pw_hash = hash_password(password)

    try:
        with pool.get_cursor() as cur:
            # Check existing username
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                log_security_event(None, "user_signup", "FAILURE_USER_EXISTS", {"username": username})
                return {"success": False, "error": f"Username '{username}' is already taken."}

            # Insert user with password_hash as primary authority
            cur.execute("""
                INSERT INTO users (username, password, password_hash, status)
                VALUES (%s, '[HASHED_PBKDF2]', %s, 'active')
                RETURNING id
            """, (username, pw_hash))
            user_id = cur.fetchone()[0]

            # Initialize empty user memory structure
            cur.execute("""
                INSERT INTO user_memory (user_id, memory)
                VALUES (%s, '{}'::jsonb)
            """, (user_id,))

        token = generate_token(user_id, username)
        log_security_event(user_id, "user_signup", "SUCCESS", {"username": username})
        return {
            "success": True,
            "user_id": user_id,
            "username": username,
            "token": token,
            "expires_in": DEFAULT_TOKEN_EXPIRY
        }
    except Exception as e:
        log_security_event(None, "user_signup", f"ERROR: {str(e)}", {"username": username})
        return {"success": False, "error": f"Database error during registration: {e}"}


def authenticate_user_credentials(username: str, password: str) -> Dict[str, Any]:
    """
    Authenticates username and password against database.
    Performs transparent password migration to PBKDF2 on valid login.
    """
    username = (username or "").strip().lower()
    if not username or not password:
        return {"success": False, "error": "Username and password required.", "code": "INVALID_INPUT"}

    pool = get_db_pool()
    if not pool.is_healthy():
        return {"success": False, "error": "Database service is temporarily offline.", "code": "DB_UNAVAILABLE"}

    try:
        with pool.get_cursor() as cur:
            cur.execute("SELECT id, password_hash, password, status FROM users WHERE username = %s", (username,))
            row = cur.fetchone()

        if not row:
            log_security_event(None, "user_login", "FAILURE_USER_NOT_FOUND", {"username": username})
            return {"success": False, "error": "User not found.", "code": "USER_NOT_FOUND"}

        user_id, stored_hash, stored_pass, status = row[0], row[1], row[2], row[3]

        if status and status != "active":
            log_security_event(user_id, "user_login", "FAILURE_ACCOUNT_INACTIVE", {"username": username})
            return {"success": False, "error": "Account is inactive or suspended.", "code": "ACCOUNT_INACTIVE"}

        # Prefer password_hash column if populated, otherwise use legacy password column
        target_check = stored_hash or stored_pass
        is_valid, needs_rehash = verify_password(password, target_check)

        if not is_valid:
            log_security_event(user_id, "user_login", "FAILURE_WRONG_PASSWORD", {"username": username})
            return {"success": False, "error": "Incorrect password.", "code": "WRONG_PASSWORD"}

        # Transparently upgrade legacy password to PBKDF2 hash
        if needs_rehash or not stored_hash or stored_pass != "[HASHED_PBKDF2]":
            new_hash = hash_password(password)
            try:
                with pool.get_cursor() as cur:
                    cur.execute("""
                        UPDATE users
                        SET password = '[HASHED_PBKDF2]', password_hash = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (new_hash, user_id))
                print(f"[AUTH] Upgraded password for user {username} (ID: {user_id}) to PBKDF2.")
            except Exception as e:
                print(f"[AUTH] [WARN] Password upgrade notice: {e}")

        token = generate_token(user_id, username)
        log_security_event(user_id, "user_login", "SUCCESS", {"username": username})
        return {
            "success": True,
            "user_id": user_id,
            "username": username,
            "token": token,
            "expires_in": DEFAULT_TOKEN_EXPIRY
        }
    except Exception as e:
        log_security_event(None, "user_login", f"ERROR: {str(e)}", {"username": username})
        return {"success": False, "error": f"Authentication system error: {e}", "code": "SYSTEM_ERROR"}


def change_user_password(user_id: int, old_password: str, new_password: str) -> Dict[str, Any]:
    """
    Changes a user's password with old password verification.
    """
    if not new_password or len(new_password) < 4:
        return {"success": False, "error": "New password must be at least 4 characters long."}

    pool = get_db_pool()
    if not pool.is_healthy():
        return {"success": False, "error": "Database service is temporarily offline."}

    try:
        with pool.get_cursor() as cur:
            cur.execute("SELECT password_hash, password FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()

        if not row:
            return {"success": False, "error": "User not found."}

        target_check = row[0] or row[1]
        is_valid, _ = verify_password(old_password, target_check)
        if not is_valid:
            log_security_event(user_id, "password_change", "FAILURE_WRONG_OLD_PASSWORD")
            return {"success": False, "error": "Current password incorrect."}

        new_hash = hash_password(new_password)
        with pool.get_cursor() as cur:
            cur.execute("""
                UPDATE users
                SET password = '[HASHED_PBKDF2]', password_hash = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (new_hash, user_id))

        log_security_event(user_id, "password_change", "SUCCESS")
        return {"success": True, "message": "Password updated successfully."}
    except Exception as e:
        log_security_event(user_id, "password_change", f"ERROR: {str(e)}")
        return {"success": False, "error": f"Database error during password change: {e}"}
