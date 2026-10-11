import os
import sys

try:
    from cryptography.fernet import Fernet, InvalidToken
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    Fernet = None
    InvalidToken = Exception
    print("[ERROR] Cryptography is not installed. Email encryption is unavailable.")

# Secure key storage paths
_MODULE_DIR = os.path.dirname(__file__)
_WORKSPACE_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, "../../"))
_INSTANCE_KEY_FILE = os.path.join(_WORKSPACE_ROOT, "instance", "secret.key")
_LEGACY_KEY_FILE = os.path.join(_MODULE_DIR, "secret.key")

def load_key() -> bytes:
    """
    Loads the encryption key with secure precedence:
    1. Environment variable EMAIL_ENCRYPTION_KEY or ASSISTANT_ENCRYPTION_KEY
    2. Instance secure key file (instance/secret.key)
    3. Legacy key file (modules/assistant_email/secret.key) for backward compatibility
    4. Auto-generates a new key stored in instance/secret.key
    """
    if not CRYPTOGRAPHY_AVAILABLE:
        return None

    # 1. Environment variable
    env_key = os.environ.get("EMAIL_ENCRYPTION_KEY") or os.environ.get("ASSISTANT_ENCRYPTION_KEY")
    if env_key:
        key_bytes = env_key.strip().encode("utf-8")
        try:
            Fernet(key_bytes)
            return key_bytes
        except Exception:
            pass

    # 2. Instance key file
    if os.path.isfile(_INSTANCE_KEY_FILE):
        try:
            with open(_INSTANCE_KEY_FILE, "rb") as f:
                key = f.read().strip()
                if key:
                    Fernet(key)
                    return key
        except Exception:
            pass

    # 3. Legacy key file (preserve existing installed credentials)
    if os.path.isfile(_LEGACY_KEY_FILE):
        try:
            with open(_LEGACY_KEY_FILE, "rb") as f:
                key = f.read().strip()
                if key:
                    Fernet(key)
                    # Opportunistically copy to instance key file if writable
                    try:
                        os.makedirs(os.path.dirname(_INSTANCE_KEY_FILE), exist_ok=True)
                        if not os.path.exists(_INSTANCE_KEY_FILE):
                            with open(_INSTANCE_KEY_FILE, "wb") as f_inst:
                                f_inst.write(key)
                    except Exception:
                        pass
                    return key
        except Exception:
            pass

    # 4. Generate new key in instance directory
    try:
        os.makedirs(os.path.dirname(_INSTANCE_KEY_FILE), exist_ok=True)
        new_key = Fernet.generate_key()
        with open(_INSTANCE_KEY_FILE, "wb") as f:
            f.write(new_key)
        return new_key
    except Exception as e:
        print(f"[SECURITY] [ERROR] Failed to generate or write instance key: {e}")
        return None

def _get_cipher():
    """Lazily resolve and cache Fernet cipher."""
    if not CRYPTOGRAPHY_AVAILABLE:
        return None
    key = load_key()
    if not key:
        return None
    try:
        return Fernet(key)
    except Exception as e:
        print(f"[SECURITY] [ERROR] Failed to initialize Fernet cipher: {e}")
        return None

def encrypt_password(password: str) -> str:
    """
    Encrypts a plain-text password.
    Fails closed: if encryption is unavailable, raises RuntimeError rather than storing plaintext.
    """
    if not password:
        return ""
    cipher = _get_cipher()
    if not cipher:
        raise RuntimeError(
            "CRITICAL SECURITY FAILURE: Email encryption service is unavailable (cryptography missing or key error). "
            "Refusing to store email password in plaintext."
        )
    return cipher.encrypt(password.encode("utf-8")).decode("utf-8")

def decrypt_password(encrypted_password: str) -> str:
    """
    Decrypts an encrypted password string.
    Fails closed: if decryption is unavailable or payload is malformed, raises RuntimeError.
    """
    if not encrypted_password:
        return ""
    cipher = _get_cipher()
    if not cipher:
        raise RuntimeError(
            "CRITICAL SECURITY FAILURE: Email decryption service is unavailable. Cannot decrypt credentials."
        )
    try:
        return cipher.decrypt(encrypted_password.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise RuntimeError("Decryption failed: stored credential was encrypted with a different key or is corrupted.")
    except Exception as e:
        raise RuntimeError(f"Failed to decrypt stored email credential: {e}")
