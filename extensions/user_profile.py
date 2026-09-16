# user_profile.py
import json
import psycopg2
from instance.config import settings as CONFIG

class UserProfile:
    def __init__(self, db_pool=None):
        self.pool = db_pool
        self._init_db()

    def _init_db(self):
        """Schema managed by assistant_production_schema.sql - no table creation here."""
        pass

    def load_profile(self, user_id):
        if user_id is None or not self.pool:
            return {"user_id": user_id, "preferences": {}}
            
        conn = None
        try:
            conn = self.pool.getconn()
            cursor = conn.cursor()
            
            # Ensure user exists in canonical table - but we can't create users without username/password
            # This should only be called for existing users
            uid = int(user_id)
            cursor.execute("SELECT 1 FROM users WHERE id = %s", (uid,))
            if not cursor.fetchone():
                print(f"[PROFILE ERROR] User {uid} does not exist in users table")
                cursor.close()
                return {"user_id": user_id, "preferences": {}}
            
            cursor.execute("SELECT pref_key, pref_value FROM user_preferences WHERE user_id = %s", (uid,))
            prefs = {r[0]: r[1] for r in cursor.fetchall()}
            cursor.close()
            return {"user_id": uid, "preferences": prefs}
        except Exception as e:
            print(f"[PROFILE LOAD ERROR] {e}")
            return {"user_id": user_id, "preferences": {}}
        finally:
            if conn:
                self.pool.putconn(conn)

    def set_preference(self, user_id, key, value):
        if user_id is None or not self.pool:
            return

        conn = None
        try:
            conn = self.pool.getconn()
            cursor = conn.cursor()
            uid = int(user_id)
            cursor.execute('''
                INSERT INTO user_preferences (user_id, pref_key, pref_value)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, pref_key) DO UPDATE SET pref_value = EXCLUDED.pref_value
            ''', (uid, key, value))
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"[PROFILE SET ERROR] {e}")
        finally:
            if conn:
                self.pool.putconn(conn)
