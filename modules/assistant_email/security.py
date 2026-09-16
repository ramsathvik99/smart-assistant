import sys
import subprocess

def install_missing_package(package_name: str):
    """Attempts to install a missing package for the current interpreter."""
    print(f"[SYSTEM] Attempting to install missing dependency: {package_name}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        print(f"[SYSTEM] Successfully installed {package_name}. Please restart the application.")
        return True
    except Exception:
        return False

try:
    from cryptography.fernet import Fernet
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    if install_missing_package("cryptography"):
        try:
            from cryptography.fernet import Fernet
            CRYPTOGRAPHY_AVAILABLE = True
        except ImportError:
            CRYPTOGRAPHY_AVAILABLE = False
    else:
        CRYPTOGRAPHY_AVAILABLE = False
    
    if not CRYPTOGRAPHY_AVAILABLE:
        print("[ERROR] Cryptography not installed. Email module disabled.")
import os

KEY_FILE = os.path.join(os.path.dirname(__file__), "secret.key")

def load_key():
    """
    Loads the encryption key from secret.key or generates a new one.
    """
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
    else:
        with open(KEY_FILE, "rb") as f:
            key = f.read()
    return key

# Initialize Cipher
if CRYPTOGRAPHY_AVAILABLE:
    _key = load_key()
    _cipher = Fernet(_key)
else:
    _cipher = None

def encrypt_password(password):
    """
    Encrypts a plain-text password.
    """
    if not password: return ""
    if not _cipher: return password  # Fallback to plain text if security unavailable
    return _cipher.encrypt(password.encode()).decode()

def decrypt_password(encrypted_password):
    """
    Decrypts an encrypted password string.
    """
    if not encrypted_password: return ""
    if not _cipher: return encrypted_password  # Fallback if security unavailable (or if already plain)
    try:
        return _cipher.decrypt(encrypted_password.encode()).decode()
    except Exception as e:
        # If it fails, it might be plain text from before encryption was enabled
        return encrypted_password
