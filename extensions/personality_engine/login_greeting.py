"""
Dynamic Login Greeting Service
Generates natural, varied, context-aware login greetings tailored to the authenticated
user's identity, personality preset, time of day, and pending schedule.
Enforces per-user account isolation and anti-repetition via PostgreSQL preference storage.
"""

from __future__ import annotations

import os
import json
import random
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from extensions.personality_engine.personality_core import get_personality
from legacy.memory_manager import get_user_preference_db, set_user_preference_db, get_connection

logger = logging.getLogger(__name__)

# Fallback template bank partitioned by time-of-day and style for offline resilience
OFFLINE_GREETING_TEMPLATES = {
    "morning": [
        "Good morning, {username}. {assistant_name} is standing by.",
        "Good morning, {username}! Ready to get started with your day?",
        "Morning, {username}. All systems are ready when you are.",
        "Good morning, {username}! Let's make today productive.",
        "A very good morning to you, {username}. How can I assist you today?"
    ],
    "afternoon": [
        "Good afternoon, {username}. What can I help you with today?",
        "Good afternoon, {username}! {assistant_name} is ready for your instructions.",
        "Hope your day is going smoothly, {username}. Ready whenever you need me.",
        "Good afternoon, {username}. Let's keep the momentum going.",
        "Afternoon, {username}! How can I help you right now?"
    ],
    "evening": [
        "Good evening, {username}. Ready when you are.",
        "Good evening, {username}! {assistant_name} is here to assist.",
        "Evening, {username}. How can I help wrap up your day?",
        "Good evening, {username}! Standing by for your instructions.",
        "Hope you had a productive day, {username}. What can I do for you tonight?"
    ],
    "night": [
        "Good evening, {username}. Working late tonight? I'm here to assist.",
        "Hello {username}. {assistant_name} is ready whenever you need me tonight.",
        "Late night session, {username}? Let me know how I can help.",
        "Good evening, {username}. Standing by for your commands."
    ]
}


class LoginGreetingService:
    """Intelligent dynamic login greeting generator with anti-repetition memory."""

    @staticmethod
    def _get_time_of_day() -> str:
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 22:
            return "evening"
        else:
            return "night"

    @classmethod
    def get_recent_greetings(cls, user_id: int) -> List[str]:
        """Retrieve recent greetings from persistent user preferences in PostgreSQL."""
        try:
            raw = get_user_preference_db(user_id, "recent_login_greetings", "[]")
            if isinstance(raw, list):
                return raw
            if isinstance(raw, str) and raw.strip():
                return json.loads(raw)
        except Exception as e:
            logger.debug(f"[GREETING] Error loading recent greetings for user {user_id}: {e}")
        return []

    @classmethod
    def record_greeting(cls, user_id: int, greeting: str) -> None:
        """Persist greeting in user preferences, maintaining a sliding window of 10 items."""
        if not user_id or not greeting:
            return
        try:
            recent = cls.get_recent_greetings(user_id)
            # Remove exact duplicate if present
            recent = [g for g in recent if g.strip().lower() != greeting.strip().lower()]
            recent.append(greeting.strip())
            # Keep last 10 entries
            recent = recent[-10:]
            set_user_preference_db(user_id, "recent_login_greetings", json.dumps(recent))
        except Exception as e:
            logger.warning(f"[GREETING] Failed to persist recent greeting for user {user_id}: {e}")

    @classmethod
    def _get_pending_tasks_summary(cls, user_id: int) -> Optional[str]:
        """Check if user has pending reminders or calendar items scheduled today."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*), MIN(task_text)
                FROM reminders
                WHERE user_id = %s
                  AND is_notified = FALSE
                  AND due_at >= NOW()
                  AND due_at <= NOW() + INTERVAL '16 hours'
                """,
                (user_id,)
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row and row[0] and row[0] > 0:
                count = row[0]
                first_task = str(row[1]).strip()
                if count == 1:
                    return f"You have 1 reminder scheduled today: '{first_task}'."
                else:
                    return f"You have {count} reminders scheduled today."
        except Exception as e:
            logger.debug(f"[GREETING] Could not query pending reminders for user {user_id}: {e}")
        return None

    @classmethod
    def generate_greeting(
        cls,
        user_id: int,
        username: str,
        assistant_name: Optional[str] = None,
        allow_llm: bool = True
    ) -> str:
        """
        Generate a fresh, natural, persona-aligned greeting for the authenticated user.
        Never blocks startup and falls back immediately on LLM unavailability.
        """
        clean_user = (username or "there").strip().capitalize()
        asst = (assistant_name or "Trevon").strip()
        time_slot = cls._get_time_of_day()
        recent_greetings = cls.get_recent_greetings(user_id)
        pending_summary = cls._get_pending_tasks_summary(user_id)

        # Retrieve isolated personality profile
        personality = get_personality()
        profile = personality.get_personality(user_id=user_id)

        # 1. Attempt LLM generation if allowed and providers are healthy
        if allow_llm:
            try:
                from extensions.llm_engine import LLMEngine
                llm = LLMEngine()

                avoid_list = "\n".join(f"- \"{g}\"" for g in recent_greetings[-5:]) if recent_greetings else "None"
                task_ctx = f"Pending schedule: {pending_summary}" if pending_summary else "No urgent tasks scheduled right now."

                system_prompt = (
                    f"You are {asst}, an intelligent desktop assistant with a {profile.preset} personality.\n"
                    f"Tone: {profile.tone}. Warmth: {profile.warmth_pct}%. Directness: {profile.directness_pct}%.\n"
                    f"Generate a single, warm, natural login greeting for user {clean_user}.\n"
                    f"Rules:\n"
                    f"- Current time period: {time_slot}.\n"
                    f"- Keep it strictly 1 to 2 sentences (under 25 words).\n"
                    f"- Speak naturally to {clean_user}.\n"
                    f"- DO NOT repeat or closely mimic any of these recently used greetings:\n{avoid_list}\n"
                    f"- You may briefly incorporate context if helpful ({task_ctx}), or provide a fresh welcoming greeting.\n"
                    f"- Output ONLY the spoken greeting text. No quotes, no markdown, no preamble."
                )

                user_prompt = f"User {clean_user} just logged in. Time of day: {time_slot}."

                generated = llm.get_completion(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    user_id=user_id,
                    timeout_budget=2.0,
                    temperature=0.8,
                    max_tokens=60
                )

                if generated and len(generated.strip()) > 5:
                    clean_gen = generated.strip().strip('"\'')
                    # Verify it's not an exact repeat
                    if not any(clean_gen.lower() == g.lower() for g in recent_greetings[-3:]):
                        cls.record_greeting(user_id, clean_gen)
                        return clean_gen
            except Exception as llm_err:
                logger.debug(f"[GREETING] LLM generation skipped/failed ({llm_err}), using smart fallback.")

        # 2. Intelligent Offline Fallback Rotation
        candidates = OFFLINE_GREETING_TEMPLATES.get(time_slot, OFFLINE_GREETING_TEMPLATES["evening"])
        recent_lower = {g.lower() for g in recent_greetings[-4:]}

        # Format candidates with current names
        formatted_candidates = [
            tmpl.format(username=clean_user, assistant_name=asst)
            for tmpl in candidates
        ]

        # Filter out recently used templates
        available = [c for c in formatted_candidates if c.lower() not in recent_lower]
        if not available:
            available = formatted_candidates

        # If there is a pending task, optionally append it to the greeting
        chosen = random.choice(available)
        if pending_summary and random.random() < 0.5:
            chosen = f"{chosen} {pending_summary}"

        cls.record_greeting(user_id, chosen)
        return chosen


# Global singleton access
_greeting_service = LoginGreetingService()

def get_login_greeting_service() -> LoginGreetingService:
    return _greeting_service

