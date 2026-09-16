# memory_store.py
import os
import psycopg2
from psycopg2 import pool
from datetime import datetime
from instance.config import settings as CONFIG

class MemoryStore:
    def __init__(self, db_pool=None):
        self.pool = db_pool
        self._init_db()

    def _init_db(self):
        """Schema managed by assistant_production_schema.sql - no table creation here."""
        # This class now adapts to the legacy JSONB memory model:
        # user_memory(user_id INTEGER, memory JSONB)
        # We store facts as: {"facts": [{"fact": "...", "importance": 0.5, "created_at": "..."}]}
        pass

    def store_fact(self, user_id, fact, importance=0.5):
        """Store a fact in the legacy JSONB memory model."""
        if user_id is None or not self.pool:
            return False
            
        conn = None
        try:
            conn = self.pool.getconn()
            cursor = conn.cursor()
            uid = int(user_id)
            
            # Legacy model: Append to JSONB array in memory column
            from datetime import datetime
            import json
            
            fact_obj = {
                "fact": fact,
                "importance": float(importance),
                "created_at": datetime.now().isoformat()
            }
            
            # Check if user memory exists
            cursor.execute("SELECT memory FROM user_memory WHERE user_id = %s", (uid,))
            row = cursor.fetchone()
            
            if row:
                # Update existing
                current_memory = row[0]
                if not current_memory: current_memory = {}
                facts = current_memory.get('facts', [])
                if not isinstance(facts, list): facts = []
                
                facts.append(fact_obj)
                new_memory = {**current_memory, "facts": facts}
                
                cursor.execute(
                    "UPDATE user_memory SET memory = %s::jsonb WHERE user_id = %s",
                    (json.dumps(new_memory), uid)
                )
            else:
                # Insert new
                new_memory = {"facts": [fact_obj]}
                cursor.execute(
                    "INSERT INTO user_memory (user_id, memory) VALUES (%s, %s::jsonb)",
                    (uid, json.dumps(new_memory))
                )
            
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"[MEMORY STORE ERROR] {e}")
            return False
        finally:
            if conn:
                self.pool.putconn(conn)

    def retrieve_relevant(self, user_id, query, limit=5):
        """Retrieve facts matching query from legacy JSONB model."""
        if user_id is None or not self.pool:
            return []
            
        conn = None
        try:
            conn = self.pool.getconn()
            cursor = conn.cursor()
            uid = int(user_id)
            
            # Extract facts array from JSONB and filter
            cursor.execute('''
                SELECT jsonb_array_elements(memory->'facts') as fact
                FROM user_memory 
                WHERE user_id = %s
            ''', (uid,))
            
            rows = cursor.fetchall()
            cursor.close()
            
            # Filter by query and limit
            import json
            results = []
            for row in rows:
                fact_obj = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                if query.lower() in fact_obj.get('fact', '').lower():
                    results.append(fact_obj)
                    if len(results) >= limit:
                        break
            
            return results
        except Exception as e:
            print(f"[MEMORY RETRIEVE ERROR] {e}")
            return []
        finally:
            if conn:
                self.pool.putconn(conn)

    def get_all_user_facts(self, user_id):
        """Get all facts for a user from JSONB model."""
        if user_id is None or not self.pool:
            return []
        conn = None
        try:
            conn = self.pool.getconn()
            cursor = conn.cursor()
            uid = int(user_id)
            
            cursor.execute('''
                SELECT memory->'facts' FROM user_memory WHERE user_id = %s
            ''', (uid,))
            
            row = cursor.fetchone()
            cursor.close()
            
            if not row or not row[0]:
                return []
            
            import json
            facts_array = row[0] if isinstance(row[0], list) else json.loads(row[0])
            return [f.get('fact', '') for f in facts_array if isinstance(f, dict)]
        except Exception as e:
            print(f"[MEMORY ERROR] {e}")
            return []
        finally:
            if conn:
                self.pool.putconn(conn)
    def delete_fact(self, user_id, search_query):
        """Deletes facts matching the search query for a user from the JSONB array."""
        if user_id is None or not self.pool:
            return False
            
        conn = None
        try:
            conn = self.pool.getconn()
            cursor = conn.cursor()
            uid = int(user_id)
            
            # Fetch current memory
            cursor.execute("SELECT memory FROM user_memory WHERE user_id = %s", (uid,))
            row = cursor.fetchone()
            
            if not row or not row[0]:
                cursor.close()
                return False
                
            import json
            current_memory = row[0]
            if not isinstance(current_memory, dict):
                current_memory = json.loads(current_memory)
                
            facts = current_memory.get('facts', [])
            if not facts:
                cursor.close()
                return False
                
            # Filter matches
            query_lower = search_query.lower()
            original_len = len(facts)
            new_facts = [f for f in facts if query_lower not in f.get('fact', '').lower()]
            
            if len(new_facts) == original_len:
                cursor.close()
                return False
                
            # Update DB
            new_memory = {**current_memory, "facts": new_facts}
            cursor.execute(
                "UPDATE user_memory SET memory = %s::jsonb WHERE user_id = %s",
                (json.dumps(new_memory), uid)
            )
            
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"[MEMORY DELETE ERROR] {e}")
            if conn: conn.rollback()
            return False
        finally:
            if conn:
                self.pool.putconn(conn)

    def store_system_memory(self, user_id, key, value):
        """Stores or updates a system-level key-value pair for a user (Context Persistence)."""
        if not self.pool: return False
        conn = None
        try:
            conn = self.pool.getconn()
            cursor = conn.cursor()
            uid = int(user_id) if user_id is not None else None
            cursor.execute('''
                INSERT INTO system_memory (user_id, key, value, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
            ''', (uid, key, str(value)))
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"[SYSTEM MEMORY STORE ERROR] {e}")
            return False
        finally:
            if conn: self.pool.putconn(conn)

    def get_system_memory(self, user_id, key):
        """Retrieves a system-level value."""
        if not self.pool: return None
        conn = None
        try:
            conn = self.pool.getconn()
            cursor = conn.cursor()
            uid = int(user_id) if user_id is not None else None
            cursor.execute('SELECT value FROM system_memory WHERE user_id = %s AND key = %s', (uid, key))
            row = cursor.fetchone()
            cursor.close()
            return row[0] if row else None
        except Exception as e:
            print(f"[SYSTEM MEMORY GET ERROR] {e}")
            return None
        finally:
            if conn: self.pool.putconn(conn)

    def clear_all_memory(self, user_id):
        """Clears all memory for a user."""
        if user_id is None or not self.pool:
            return False
        conn = None
        try:
            conn = self.pool.getconn()
            cursor = conn.cursor()
            uid = int(user_id)
            cursor.execute('DELETE FROM user_memory WHERE user_id = %s', (uid,))
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"[MEMORY CLEAR ERROR] {e}")
            return False
        finally:
            if conn:
                self.pool.putconn(conn)
