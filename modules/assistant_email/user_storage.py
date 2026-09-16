import json
import os
from .security import encrypt_password, decrypt_password

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
USER_EMAILS_PATH = os.path.join(DATA_DIR, "user_emails.json")

def load_user_data():
    if not os.path.exists(USER_EMAILS_PATH):
        return {}
    try:
        with open(USER_EMAILS_PATH, "r") as f:
            return json.load(f)
    except:
        return {}

def save_user_data(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USER_EMAILS_PATH, "w") as f:
        json.dump(data, f, indent=4)

def get_user_email(username):
    """
    Returns (email, decrypted_password) for the given username.
    """
    data = load_user_data()
    user_info = data.get(username.lower())
    if user_info:
        email = user_info.get("email")
        encrypted_pass = user_info.get("app_password")
        # Decrypt for runtime use
        decrypted_pass = decrypt_password(encrypted_pass)
        return email, decrypted_pass
    return None, None

def save_user_email(username, email, password):
    """
    Encrypts and saves the user email and password.
    """
    data = load_user_data()
    # Encrypt for persistent storage
    encrypted_pass = encrypt_password(password)
    data[username.lower()] = {
        "email": email,
        "app_password": encrypted_pass
    }
    save_user_data(data)
