import os
import sys

# Ensure path is correct for absolute imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from legacy.memory_manager import update_user_memory, load_user_memory

from instance.config import settings as CONFIG

def normalize_key(text):
    return text.lower().strip().replace(" ", "_")

def save_memory(key, value):
    user_id = CONFIG.CURRENT_USER_ID
    if not user_id:
        print("[MEMORY ERROR] No active user to save memory to.")
        return
        
    key = normalize_key(key)
    value = value.strip().lower()
    
    print(f"[DEBUG] Saving memory for user {user_id}: {key} = {value}")
    update_user_memory(user_id, key, value)
    print(f"[MEMORY STORE] {key} = {value}")

def get_memory(key):
    user_id = CONFIG.CURRENT_USER_ID
    if not user_id:
        print("[MEMORY ERROR] No active user to fetch memory from.")
        return None
        
    key = normalize_key(key)
    
    print(f"[DEBUG] Fetching memory for user {user_id}: {key}")
    memory_dict = load_user_memory(user_id)
    
    if memory_dict and key in memory_dict:
        value = memory_dict[key]
        print(f"[MEMORY RETRIEVE] {key} → {value}")
        return value
    else:
        print(f"[MEMORY RETRIEVE] {key} → NOT FOUND")
        return None
