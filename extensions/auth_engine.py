import hashlib
import time

class AuthEngine:
    """
    Handles User Authentication and Session Management for Nova.
    """
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.current_user_id = None
        self.current_username = None

    def _hash_password(self, password):
        """Simple SHA-256 hashing."""
        return hashlib.sha256(password.encode()).hexdigest()

    def login(self, username, password):
        """Verifies credentials and sets current session."""
        user = self.db_manager.get_user_by_username(username)
        if user:
            uid, uname, pwd_hash = user
            if pwd_hash == self._hash_password(password):
                self.current_user_id = uid
                self.current_username = uname
                self.db_manager.update_session(uid, is_active=True)
                print(f"[AUTH] User {username} logged in successfully.")
                return uid
        print(f"[AUTH] Login failed for user {username}.")
        return None

    def signup(self, username, password):
        """Creates a new user and logs them in."""
        # Check if user exists
        existing = self.db_manager.get_user_by_username(username)
        if existing:
            print(f"[AUTH] Signup failed: User {username} already exists.")
            return None
        
        pwd_hash = self._hash_password(password)
        uid = self.db_manager.create_user(username, pwd_hash)
        if uid:
            self.current_user_id = uid
            self.current_username = username
            self.db_manager.update_session(uid, is_active=True)
            print(f"[AUTH] User {username} signed up and logged in.")
            return uid
        return None

    def logout(self):
        """Clears current session."""
        if self.current_user_id:
            self.db_manager.update_session(self.current_user_id, is_active=False)
            print(f"[AUTH] User {self.current_username} logged out.")
            self.current_user_id = None
            self.current_username = None
            return True
        return False

    def auto_restore(self):
        """Attempts to restore the last active session if valid."""
        uid = self.db_manager.get_active_session_user()
        if uid:
            # We don't have the username easily without another query or storing it in session
            # For simplicity, we just set the ID. 
            # In AssistantOrchestrator, we can fetch username if needed for display.
            self.current_user_id = uid
            print(f"[AUTH] Auto-restored session for User ID {uid}.")
            return uid
        return None
