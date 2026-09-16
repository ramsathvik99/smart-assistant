import json
import os
import difflib
from dotenv import load_dotenv

# ── CENTRALIZED ENV LOADING ──────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
ENV_PATH = os.path.join(PROJECT_ROOT, "legacy", ".env")
load_dotenv(ENV_PATH)

# Path definition
CONTACTS_FILE = os.path.join(os.path.dirname(__file__), "data", "contacts.json")

def load_contacts():
    if not os.path.exists(CONTACTS_FILE):
        return {}
    try:
        with open(CONTACTS_FILE, 'r') as f:
            data = json.load(f)
            return data
    except Exception as e:
        print(f"Error loading contacts: {e}")
        return {}

def save_contact(name, email, spoken_alias=None):
    contacts = load_contacts()
    name = name.lower().strip()
    target_name = name
    for k, v in contacts.items():
        if isinstance(v, dict) and v.get("email") == email:
            target_name = k
            break
    if target_name not in contacts:
        contacts[target_name] = {"email": email, "aliases": []}
    aliases = contacts[target_name].setdefault("aliases", [])
    if name != target_name and name not in aliases:
        aliases.append(name)
    if spoken_alias:
        spoken_alias = spoken_alias.lower().strip()
        if spoken_alias != target_name and spoken_alias not in aliases:
            aliases.append(spoken_alias)
    contacts[target_name]["aliases"] = aliases
    os.makedirs(os.path.dirname(CONTACTS_FILE), exist_ok=True)
    try:
        with open(CONTACTS_FILE, 'w') as f:
            json.dump(contacts, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving contact: {e}")
        return False

def resolve_contact(name):
    contacts = load_contacts()
    if not contacts: return None
    name = name.lower().strip()
    if name in contacts: return contacts[name].get("email")
    for main_name, data in contacts.items():
        if name in data.get("aliases", []): return data.get("email")
    for main_name, data in contacts.items():
        all_names = [main_name] + data.get("aliases", [])
        for n in all_names:
            if name in n or n in name:
                save_contact(main_name, data.get("email"), spoken_alias=name)
                return data.get("email")
    all_names = []
    name_to_main = {}
    for main_name, data in contacts.items():
        all_names.append(main_name)
        name_to_main[main_name] = main_name
        for alias in data.get("aliases", []):
            all_names.append(alias)
            name_to_main[alias] = main_name
    close_matches = difflib.get_close_matches(name, all_names, n=1, cutoff=0.6)
    if close_matches:
        main_name = name_to_main[close_matches[0]]
        save_contact(main_name, contacts[main_name].get("email"), spoken_alias=name)
        return contacts[main_name].get("email")
    return None
