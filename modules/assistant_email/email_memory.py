import json
import os
import re
import difflib
from typing import Optional, Dict, Any, List, Tuple
from dotenv import load_dotenv

# Path definition
CONTACTS_FILE = os.path.join(os.path.dirname(__file__), "data", "contacts.json")

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')

PLACEHOLDER_DOMAINS = {
    "example.com", "example.org", "example.net", "example.edu",
    "test.com", "test.org", "test.net", "invalid", "localhost",
    "sample.com", "dummy.com", "fake.com"
}

def is_valid_email(email_str: str) -> bool:
    if not email_str or not isinstance(email_str, str):
        return False
    clean = email_str.strip()
    return bool(EMAIL_REGEX.match(clean))

def is_placeholder_email(email_str: str) -> bool:
    """Checks if an email uses a reserved testing/documentation or placeholder domain."""
    if not email_str or not isinstance(email_str, str) or "@" not in email_str:
        return True
    clean = email_str.strip().lower()
    domain = clean.split("@")[-1].strip()
    if domain in PLACEHOLDER_DOMAINS or domain.endswith(".invalid") or domain.endswith(".example"):
        return True
    if clean.startswith("placeholder@") or clean.startswith("test@example"):
        return True
    return False

def load_contacts() -> Dict[str, Any]:
    """Loads contacts dictionary safely."""
    if not os.path.exists(CONTACTS_FILE):
        return {}
    try:
        with open(CONTACTS_FILE, 'r', encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[CONTACTS] [ERROR] Could not load contacts: {e}")
        return {}

def save_contact(name: str, email: str, spoken_alias: Optional[str] = None) -> bool:
    """
    Saves or updates a contact and its aliases.
    Validates email format before saving.
    """
    if not name or not email:
        return False
    email = email.strip()
    if not is_valid_email(email):
        print(f"[CONTACTS] [WARN] Invalid email address format: {email}")
        return False

    contacts = load_contacts()
    clean_name = name.lower().strip()
    target_name = clean_name

    # Check if this email already exists under a different key
    for k, v in contacts.items():
        if isinstance(v, dict) and v.get("email", "").lower() == email.lower():
            target_name = k
            break

    if target_name not in contacts:
        contacts[target_name] = {"email": email, "aliases": []}
    else:
        contacts[target_name]["email"] = email

    aliases = contacts[target_name].setdefault("aliases", [])
    if clean_name != target_name and clean_name not in aliases:
        aliases.append(clean_name)
    if spoken_alias:
        clean_alias = spoken_alias.lower().strip()
        if clean_alias != target_name and clean_alias not in aliases:
            aliases.append(clean_alias)

    contacts[target_name]["aliases"] = aliases
    os.makedirs(os.path.dirname(CONTACTS_FILE), exist_ok=True)
    temp_file = CONTACTS_FILE + ".tmp"
    try:
        with open(temp_file, 'w', encoding="utf-8") as f:
            json.dump(contacts, f, indent=4)
        if os.path.exists(CONTACTS_FILE):
            os.replace(temp_file, CONTACTS_FILE)
        else:
            os.rename(temp_file, CONTACTS_FILE)
        return True
    except Exception as e:
        print(f"[CONTACTS] [ERROR] Failed to save contact: {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
        return False

def delete_contact(name: str) -> bool:
    """Deletes a contact by canonical name or alias."""
    contacts = load_contacts()
    clean_name = name.lower().strip()
    target = None
    if clean_name in contacts:
        target = clean_name
    else:
        for k, v in contacts.items():
            if clean_name in [a.lower() for a in v.get("aliases", [])]:
                target = k
                break
    if target and target in contacts:
        del contacts[target]
        temp_file = CONTACTS_FILE + ".tmp"
        try:
            with open(temp_file, 'w', encoding="utf-8") as f:
                json.dump(contacts, f, indent=4)
            if os.path.exists(CONTACTS_FILE):
                os.replace(temp_file, CONTACTS_FILE)
            else:
                os.rename(temp_file, CONTACTS_FILE)
            return True
        except Exception:
            return False
    return False

def resolve_recipient_detailed(identifier: str) -> Dict[str, Any]:
    """
    Authoritative recipient resolver that distinguishes:
    1. Direct valid email address:
       - 'user@gmail.com' -> 'resolved'
       - 'user@example.com' -> 'unverified' (placeholder domain)
       - 'bad-email' -> 'invalid_email'
    2. Stored contacts match:
       - Single match with valid non-placeholder email -> 'resolved'
       - Single match with placeholder email -> 'unverified'
       - Single match with missing/invalid email -> 'missing_email'
       - Multiple matches with different emails -> 'ambiguous'
    3. No match -> 'not_found'
    """
    if not identifier or not isinstance(identifier, str):
        return {"status": "not_found", "email": None, "name": None, "candidates": []}

    clean = re.sub(r'^(?:to|for)\s+', '', identifier.strip(), flags=re.IGNORECASE).strip()

    # 1. Direct email check
    if "@" in clean:
        clean_addr = clean.split("<")[-1].split(">")[0].strip() if ("<" in clean and ">" in clean) else clean
        if not is_valid_email(clean_addr):
            return {
                "status": "invalid_email",
                "email": clean_addr,
                "name": clean_addr.split("@")[0] if "@" in clean_addr else clean,
                "candidates": [],
                "message": f"'{clean_addr}' is not a valid email address format."
            }
        if is_placeholder_email(clean_addr):
            return {
                "status": "unverified",
                "email": clean_addr,
                "name": clean_addr.split("@")[0],
                "candidates": [],
                "message": f"'{clean_addr}' is a placeholder or unverified email address."
            }
        return {
            "status": "resolved",
            "email": clean_addr,
            "name": clean_addr.split("@")[0],
            "candidates": []
        }

    contacts = load_contacts()
    if not contacts:
        return {"status": "not_found", "email": None, "name": None, "candidates": []}

    norm = clean.lower()
    norm_clean = re.sub(r'^(?:my|the)\s+', '', norm).strip()

    def _build_cand(main_key: str, data: Dict[str, Any]) -> Dict[str, Any]:
        email_val = data.get("email", "")
        return {
            "name": main_key.title(),
            "email": email_val,
            "is_placeholder": is_placeholder_email(email_val) if email_val else True,
            "key": main_key
        }

    # 2. Gather ALL exact matches across main keys AND aliases simultaneously
    exact_cands: Dict[str, Dict[str, Any]] = {}
    for main_name, data in contacts.items():
        all_names = [main_name.lower()] + [a.lower() for a in data.get("aliases", [])]
        if norm in all_names or norm_clean in all_names:
            exact_cands[main_name] = _build_cand(main_name, data)

    if exact_cands:
        unique_emails = {c["email"].lower() for c in exact_cands.values() if c.get("email")}
        if len(unique_emails) > 1 or (len(exact_cands) > 1 and len(unique_emails) != 1):
            return {
                "status": "ambiguous",
                "email": None,
                "name": clean,
                "candidates": list(exact_cands.values())
            }
        cand = next(iter(exact_cands.values()))
        c_email = cand["email"]
        if not c_email or not is_valid_email(c_email):
            return {
                "status": "missing_email",
                "email": None,
                "name": cand["name"],
                "candidates": [cand],
                "message": f"Contact '{cand['name']}' does not have a valid email address configured."
            }
        if is_placeholder_email(c_email):
            return {
                "status": "unverified",
                "email": c_email,
                "name": cand["name"],
                "candidates": [cand],
                "message": f"Contact '{cand['name']}' has an unverified placeholder email address ({c_email})."
            }
        return {
            "status": "resolved",
            "email": c_email,
            "name": cand["name"],
            "candidates": []
        }

    # 3. Substring matching
    substring_cands: Dict[str, Dict[str, Any]] = {}
    for main_name, data in contacts.items():
        all_names = [main_name.lower()] + [a.lower() for a in data.get("aliases", [])]
        if any(norm == n or (len(norm) >= 3 and (norm in n or n in norm)) for n in all_names):
            substring_cands[main_name] = _build_cand(main_name, data)

    if substring_cands:
        unique_emails = {c["email"].lower() for c in substring_cands.values() if c.get("email")}
        if len(unique_emails) > 1 or (len(substring_cands) > 1 and len(unique_emails) != 1):
            return {
                "status": "ambiguous",
                "email": None,
                "name": clean,
                "candidates": list(substring_cands.values())
            }
        cand = next(iter(substring_cands.values()))
        c_email = cand["email"]
        if not c_email or not is_valid_email(c_email):
            return {"status": "missing_email", "email": None, "name": cand["name"], "candidates": [cand]}
        if is_placeholder_email(c_email):
            return {"status": "unverified", "email": c_email, "name": cand["name"], "candidates": [cand]}
        return {"status": "resolved", "email": c_email, "name": cand["name"], "candidates": []}

    # 4. Fuzzy match (>0.85)
    name_map: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for main_name, data in contacts.items():
        name_map[main_name.lower()] = (main_name, data)
        for alias in data.get("aliases", []):
            name_map[alias.lower()] = (main_name, data)

    close = difflib.get_close_matches(norm, list(name_map.keys()), n=4, cutoff=0.85)
    if close:
        fuzzy_cands: Dict[str, Dict[str, Any]] = {}
        for c in close:
            m_name, m_data = name_map[c]
            fuzzy_cands[m_name] = _build_cand(m_name, m_data)

        unique_emails = {c["email"].lower() for c in fuzzy_cands.values() if c.get("email")}
        if len(unique_emails) > 1 or len(fuzzy_cands) > 1:
            return {
                "status": "ambiguous",
                "email": None,
                "name": clean,
                "candidates": list(fuzzy_cands.values())
            }
        cand = next(iter(fuzzy_cands.values()))
        c_email = cand["email"]
        if not c_email or not is_valid_email(c_email):
            return {"status": "missing_email", "email": None, "name": cand["name"], "candidates": [cand]}
        if is_placeholder_email(c_email):
            return {"status": "unverified", "email": c_email, "name": cand["name"], "candidates": [cand]}
        return {"status": "resolved", "email": c_email, "name": cand["name"], "candidates": []}

    return {"status": "not_found", "email": None, "name": None, "candidates": []}

def resolve_contact(name: str) -> Optional[str]:
    """
    Backwards-compatible helper: returns the email address if unambiguous, or None.
    Does NOT automatically mutate contacts or accept ambiguous matches.
    """
    res = resolve_recipient_detailed(name)
    if res.get("status") == "resolved":
        return res.get("email")
    return None

def search_contacts(query: str) -> List[Dict[str, Any]]:
    """Searches contacts by name, alias, or email substring."""
    contacts = load_contacts()
    q = query.lower().strip()
    results = []
    for name, data in contacts.items():
        all_terms = [name.lower(), data.get("email", "").lower()] + [a.lower() for a in data.get("aliases", [])]
        if any(q in t for t in all_terms):
            results.append({
                "name": name,
                "email": data.get("email"),
                "aliases": data.get("aliases", [])
            })
    return results

def list_contacts() -> List[Dict[str, Any]]:
    """Returns all saved contacts."""
    contacts = load_contacts()
    return [{"name": k, "email": v.get("email"), "aliases": v.get("aliases", [])} for k, v in contacts.items()]
