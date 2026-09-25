"""
Learning Skill Controller
Provides conversational commands for teaching the assistant preferences, listing rules, and deleting rules.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from .learned_rules import LearnedRulesEngine, get_learned_rules_engine


class LearningController:
    def __init__(self, engine: Optional[LearnedRulesEngine] = None):
        self.engine = engine or get_learned_rules_engine()

    def handle_command(self, user_input: str, user_id: int) -> dict[str, Any]:
        text = user_input.strip()
        text_low = text.lower()

        # 1. List rules
        if any(w in text_low for w in [
            "list rules", "show rules", "what have you learned", "my preferences", "learned rules",
            "learned preferences", "show my learned", "what preferences", "you've learned", "you have learned"
        ]):
            rules = self.engine.list_rules(user_id)
            if not rules:
                return {
                    "success": True,
                    "status": "no_rules",
                    "rules": [],
                    "message": "I haven't learned any custom behavioral rules for your account yet. You can say 'Remember that I prefer concise responses'."
                }
            lines = [f"[{r['id']}] {r['rule']}" for r in rules]
            return {
                "success": True,
                "status": "success",
                "rules": rules,
                "message": f"Here are your {len(rules)} saved preference(s):\n• " + "\n• ".join(lines)
            }

        # 2. Forget / Delete rule
        if any(w in text_low for w in [
            "forget that", "forget preference", "remove that", "remove preference",
            "forget my preference", "delete that preference", "delete preference",
            "forget the preference", "remove the preference"
        ]):
            rules = self.engine.list_rules(user_id)
            if not rules:
                return {
                    "success": False,
                    "status": "no_rules",
                    "message": "You don't have any learned preferences to forget."
                }
            target_rule = None
            clean_subj = re.sub(r'^(?:forget|delete|remove)\s+(?:that|the|my)?\s*(?:learned)?\s*(?:preference|rule)?(?:\s+about)?\s*', '', text_low).strip(' .!?')
            if clean_subj and clean_subj not in ["", "that", "preference", "rule", "it"]:
                for r in reversed(rules):
                    if clean_subj in r.get("rule", "").lower():
                        target_rule = r
                        break
            if not target_rule:
                target_rule = rules[-1]
            res = self.engine.delete_rule(user_id, target_rule["id"])
            if res.get("success"):
                return {
                    "success": True,
                    "status": "deleted",
                    "rule_id": target_rule["id"],
                    "message": f"Forgotten preference: '{target_rule['rule']}'."
                }
            return res

        m_del = re.search(r"(?:forget|delete|remove)\s+(?:rule\s+)?([a-z0-9]{4,8})", text_low)
        if m_del and m_del.group(1).strip() not in ["that", "this", "rule", "item", "preference"]:
            rule_id = m_del.group(1).strip()
            return self.engine.delete_rule(user_id, rule_id)

        # 3. Add / Remember rule
        m_learn = re.search(r"(?:remember that|learn rule:?|always remember|note that|preference:?)\s+(.+)", text, re.IGNORECASE)
        if m_learn:
            rule_text = m_learn.group(1).strip()
            return self.engine.add_rule(user_id, rule_text)

        # Fallback if user just said "remember X"
        if text_low.startswith("remember "):
            rule_text = text[9:].strip()
            return self.engine.add_rule(user_id, rule_text)

        return self.handle_command("show rules", user_id)


_controller_instance: Optional[LearningController] = None


def get_learning_controller() -> LearningController:
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = LearningController()
    return _controller_instance
