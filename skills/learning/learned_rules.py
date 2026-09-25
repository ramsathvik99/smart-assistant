"""
Learned Rules Engine
Enables continuous personalization by capturing user directives, corrections, and habits.
Enforces strict user isolation: User A cannot view or modify User B's learned directives.
Stores rules safely as plain text directives without arbitrary code execution.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LearnedRulesEngine:
    """Manages persistent behavioral rules and directives learned per user."""

    def __init__(self, storage_dir: Optional[str] = None):
        self._lock = threading.RLock()
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.storage_dir = project_root / "data" / "learned_rules"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _user_file(self, user_id: int) -> Path:
        return self.storage_dir / f"user_{int(user_id)}_rules.json"

    def _load_user_rules(self, user_id: int) -> list[dict[str, Any]]:
        with self._lock:
            path = self._user_file(user_id)
            if not path.exists():
                return []
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data.get("rules", []) if isinstance(data, dict) else []
            except Exception as e:
                logger.warning(f"Failed to load rules for user {user_id}: {e}")
                return []

    def _save_user_rules(self, user_id: int, rules: list[dict[str, Any]]) -> bool:
        with self._lock:
            path = self._user_file(user_id)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = {"user_id": user_id, "rules": rules, "updated_at": time.time()}
                path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                return True
            except Exception as e:
                logger.error(f"Failed to save rules for user {user_id}: {e}")
                return False

    def add_rule(self, user_id: int, rule_text: str, category: str = "general", origin: str = "user_directive") -> dict[str, Any]:
        clean_text = rule_text.strip()
        if not clean_text:
            return {"success": False, "status": "empty", "message": "Rule text cannot be empty."}

        with self._lock:
            rules = self._load_user_rules(user_id)

            # Deduplicate
            for r in rules:
                if r.get("rule", "").lower() == clean_text.lower():
                    r["active"] = True
                    r["updated_at"] = time.time()
                    self._save_user_rules(user_id, rules)
                    return {
                        "success": True,
                        "status": "exists",
                        "rule": r,
                        "message": f"I already have that preference noted and active: '{clean_text}'."
                    }

            new_rule = {
                "id": str(uuid.uuid4())[:8],
                "user_id": user_id,
                "rule": clean_text,
                "category": category,
                "origin": origin,
                "active": True,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            rules.append(new_rule)
            self._save_user_rules(user_id, rules)
            logger.info(f"Learned rule for user {user_id}: {clean_text}")
            return {
                "success": True,
                "status": "learned",
                "rule": new_rule,
                "message": f"I've remembered your preference: '{clean_text}'."
            }

    def list_rules(self, user_id: int, active_only: bool = False) -> list[dict[str, Any]]:
        rules = self._load_user_rules(user_id)
        if active_only:
            return [r for r in rules if r.get("active", True)]
        return rules

    def toggle_rule(self, user_id: int, rule_id: str) -> dict[str, Any]:
        with self._lock:
            rules = self._load_user_rules(user_id)
            for r in rules:
                if r.get("id") == rule_id:
                    r["active"] = not r.get("active", True)
                    r["updated_at"] = time.time()
                    self._save_user_rules(user_id, rules)
                    status = "activated" if r["active"] else "deactivated"
                    return {"success": True, "message": f"Rule '{r.get('rule')}' has been {status}."}
            return {"success": False, "message": f"Rule ID '{rule_id}' was not found."}

    def delete_rule(self, user_id: int, rule_id: str) -> dict[str, Any]:
        with self._lock:
            rules = self._load_user_rules(user_id)
            initial_len = len(rules)
            filtered = [r for r in rules if r.get("id") != rule_id]
            if len(filtered) < initial_len:
                self._save_user_rules(user_id, filtered)
                return {"success": True, "message": f"Rule {rule_id} has been forgotten."}
            return {"success": False, "message": f"Rule ID '{rule_id}' was not found."}

    def get_prompt_injections(self, user_id: int) -> str:
        """Formats active rules for runtime system prompt injection."""
        active = [r.get("rule", "").strip() for r in self.list_rules(user_id, active_only=True) if r.get("rule")]
        if not active:
            return ""

        lines = ["\nUSER PREFERENCES & LEARNED BEHAVIORAL DIRECTIVES:"]
        for i, rule in enumerate(active, 1):
            lines.append(f"{i}. {rule}")
        return "\n".join(lines) + "\n"


_rules_instance: Optional[LearnedRulesEngine] = None
_rules_lock = threading.Lock()


def get_learned_rules_engine() -> LearnedRulesEngine:
    global _rules_instance
    with _rules_lock:
        if _rules_instance is None:
            _rules_instance = LearnedRulesEngine()
        return _rules_instance
