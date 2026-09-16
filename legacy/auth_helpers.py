import os
from instance.config import settings
from legacy.memory_manager import get_username_by_id, user_exists, get_assistant_name_db

def try_restore_session():
    """
    Attempts to restore the user session from runtime_config.json.
    Returns True if a valid session is restored, False otherwise.
    Also loads the assistant name for the restored session.
    """
    try:
        last = settings.get_last_user()
        if last:
            if not user_exists(last):
                print(f"[SYSTEM] Stored user id {last} is invalid (not in DB). Resetting session.")
                settings.set_last_user(None)
                settings.CURRENT_USER_ID = None
                settings.CURRENT_USERNAME = None
                settings.CURRENT_ASSISTANT_NAME = None
                return False

            settings.CURRENT_USER_ID = last
            try:
                name = get_username_by_id(last)
                if name:
                    settings.CURRENT_USERNAME = name
                    # Load per-user assistant name from DB
                    asst_name = get_assistant_name_db(last)
                    settings.CURRENT_ASSISTANT_NAME = asst_name
                    print("  Restored user:", name)
                    if asst_name:
                        print("  Restored assistant name:", asst_name)
                    return True
                else:
                    print("[SYSTEM] User ID found but name missing.")
                    settings.set_last_user(None)  # Clear invalid state
                    settings.CURRENT_USER_ID = None
                    settings.CURRENT_ASSISTANT_NAME = None
                    return False
            except Exception as e:
                print("[SYSTEM] Failed to load username:", e)
                return False
    except Exception as e:
        print("[SYSTEM] Failed to restore last user:", e)
        return False
        
    return False

def login_success(user_id, username):
    """
    Call this when a login is successful to update the session.
    Assistant name is loaded from the DB here too.
    """
    settings.set_last_user(user_id)
    settings.CURRENT_USER_ID = user_id
    settings.CURRENT_USERNAME = username
    # Load per-user assistant name
    asst_name = get_assistant_name_db(user_id)
    settings.CURRENT_ASSISTANT_NAME = asst_name
    print(f"[SYSTEM] Login successful. User: {username} ({user_id}) | Assistant name: {asst_name}")
