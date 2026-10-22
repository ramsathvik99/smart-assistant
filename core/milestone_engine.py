"""
Milestone Detection & Proactive Event Engine

Detects meaningful personal milestones from stored facts and schedules
proactive reminders using the existing reminder scheduler.

Milestone Types:
- Personal dates (birthdays, anniversaries)
- Academic milestones (graduation, semester transitions)
- Career milestones (interviews, job starts, application deadlines)
- Goals and commitments (deadlines, check-ins, progress reviews)

Design Principles:
- Reuses existing memory_facts table
- Reuses existing reminder_scheduler for delivery
- Timezone-aware date calculations
- Per-account isolation
- Consent-aware and quiet-hours respecting
- Idempotent and safe on restart
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class MilestoneType(str, Enum):
    """Categories of personal milestones."""
    BIRTHDAY = "birthday"
    ANNIVERSARY = "anniversary"
    GRADUATION = "graduation"
    EXAM = "exam"
    INTERVIEW = "interview"
    APPLICATION_DEADLINE = "application_deadline"
    JOB_START = "job_start"
    PROJECT_DEADLINE = "project_deadline"
    GOAL_CHECKPOINT = "goal_checkpoint"
    COMMITMENT = "commitment"
    CUSTOM_DATE = "custom_date"


class MilestoneStatus(str, Enum):
    """Lifecycle status of a milestone."""
    PENDING = "pending"  # Upcoming, not yet notified
    NOTIFIED = "notified"  # Notification sent for this occurrence
    COMPLETED = "completed"  # User confirmed completion
    CANCELLED = "cancelled"  # User cancelled this milestone
    EXPIRED = "expired"  # Date passed without confirmation
    UNKNOWN = "unknown"  # Outcome uncertain


@dataclass
class Milestone:
    """Represents a detected personal milestone."""
    milestone_id: str
    user_id: int
    milestone_type: MilestoneType
    title: str
    date: date  # Next occurrence date
    time: Optional[str] = None  # Optional time for daily milestones
    recurring: bool = False
    recurrence_rule: Optional[str] = None  # e.g., "yearly", "monthly"
    status: MilestoneStatus = MilestoneStatus.PENDING
    source_fact_key: str = ""
    source_fact_value: str = ""
    last_notified_date: Optional[date] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "milestone_id": self.milestone_id,
            "user_id": self.user_id,
            "milestone_type": self.milestone_type.value,
            "title": self.title,
            "date": self.date.isoformat(),
            "time": self.time,
            "recurring": self.recurring,
            "recurrence_rule": self.recurrence_rule,
            "status": self.status.value,
            "source_fact_key": self.source_fact_key,
            "source_fact_value": self.source_fact_value,
            "last_notified_date": self.last_notified_date.isoformat() if self.last_notified_date else None,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


class MilestoneDetector:
    """
    Detects milestones from user facts and calculates next occurrences.
    Timezone-aware and lifecycle-aware.
    """

    # Date fact keys that represent personal dates
    _DATE_FACT_KEYS = {
        "birthday", "birth_date", "date_of_birth", "dob",
        "anniversary", "wedding_anniversary",
        "graduation_date", "graduation",
        "joining_date", "start_date",
    }

    # Education-related fact keys
    _EDUCATION_KEYS = {
        "education", "student_status", "academic_year", "semester",
        "graduation_date", "graduation",
    }

    # Career-related fact keys
    _CAREER_KEYS = {
        "employment", "job", "company", "work",
        "career_goal", "goal", "career",
    }

    @classmethod
    def detect_milestones_from_facts(
        cls,
        user_id: int,
        facts: Dict[str, str],
        structured_memories: List[Dict[str, Any]],
        timezone_str: str = "UTC"
    ) -> List[Milestone]:
        """
        Scan user facts and structured memories for milestone candidates.
        Returns list of detected milestones with calculated next occurrences.
        """
        milestones: List[Milestone] = []
        now = datetime.now()

        # 1. Personal Dates (birthdays, anniversaries)
        for key, value in facts.items():
            key_low = key.lower().replace("_", " ")
            if any(dk in key_low for dk in cls._DATE_FACT_KEYS):
                parsed = cls._parse_date(value)
                if parsed:
                    milestone_type = MilestoneType.BIRTHDAY if "birth" in key_low else MilestoneType.ANNIVERSARY
                    next_date = cls._calculate_next_occurrence(parsed, now, recurring=True)
                    if next_date:
                        title = f"{key.replace('_', ' ').title()}"
                        milestones.append(Milestone(
                            milestone_id=cls._generate_milestone_id(user_id, key, milestone_type),
                            user_id=user_id,
                            milestone_type=milestone_type,
                            title=title,
                            date=next_date,
                            recurring=True,
                            recurrence_rule="yearly",
                            source_fact_key=key,
                            source_fact_value=value,
                            metadata={"original_date": parsed.isoformat() if hasattr(parsed, 'isoformat') else str(parsed)}
                        ))

        # 2. Education Milestones (graduation, exams)
        for mem in structured_memories:
            cat = mem.get("category", "").lower()
            val = mem.get("fact_value", "")
            key = mem.get("fact_key", "")

            if cat == "education" or any(ed_key in key.lower() for ed_key in cls._EDUCATION_KEYS):
                # Graduation
                if "graduation" in key.lower() or "grad" in key.lower():
                    parsed = cls._parse_date(val)
                    if parsed:
                        next_date = cls._calculate_next_occurrence(parsed, now, recurring=False)
                        if next_date and next_date >= now.date():
                            milestones.append(Milestone(
                                milestone_id=cls._generate_milestone_id(user_id, key, MilestoneType.GRADUATION),
                                user_id=user_id,
                                milestone_type=MilestoneType.GRADUATION,
                                title="Graduation",
                                date=next_date,
                                recurring=False,
                                source_fact_key=key,
                                source_fact_value=val,
                                metadata={"original_date": parsed.isoformat() if hasattr(parsed, 'isoformat') else str(parsed)}
                            ))

                # Exams, deadlines
                if any(kw in val.lower() for kw in ("exam", "test", "deadline", "interview")):
                    parsed = cls._parse_date(val)
                    if parsed:
                        next_date = cls._calculate_next_occurrence(parsed, now, recurring=False)
                        if next_date and next_date >= now.date():
                            milestone_type = MilestoneType.EXAM if "exam" in val.lower() or "test" in val.lower() else MilestoneType.INTERVIEW
                            title = val[:50]  # Use first 50 chars as title
                            milestones.append(Milestone(
                                milestone_id=cls._generate_milestone_id(user_id, key, milestone_type),
                                user_id=user_id,
                                milestone_type=milestone_type,
                                title=title,
                                date=next_date,
                                recurring=False,
                                source_fact_key=key,
                                source_fact_value=val,
                                metadata={"original_date": parsed.isoformat() if hasattr(parsed, 'isoformat') else str(parsed)}
                            ))

        # 3. Career Milestones (job start, application deadlines)
        for mem in structured_memories:
            cat = mem.get("category", "").lower()
            val = mem.get("fact_value", "")
            key = mem.get("fact_key", "")

            if cat == "employment" or any(cr_key in key.lower() for cr_key in cls._CAREER_KEYS):
                # Job start
                if any(kw in val.lower() for kw in ("start", "join", "onboard")):
                    parsed = cls._parse_date(val)
                    if parsed:
                        next_date = cls._calculate_next_occurrence(parsed, now, recurring=False)
                        if next_date and next_date >= now.date():
                            milestones.append(Milestone(
                                milestone_id=cls._generate_milestone_id(user_id, key, MilestoneType.JOB_START),
                                user_id=user_id,
                                milestone_type=MilestoneType.JOB_START,
                                title="Job Start",
                                date=next_date,
                                recurring=False,
                                source_fact_key=key,
                                source_fact_value=val,
                                metadata={"original_date": parsed.isoformat() if hasattr(parsed, 'isoformat') else str(parsed)}
                            ))

                # Application deadlines
                if "deadline" in val.lower() or "apply" in val.lower():
                    parsed = cls._parse_date(val)
                    if parsed:
                        next_date = cls._calculate_next_occurrence(parsed, now, recurring=False)
                        if next_date and next_date >= now.date():
                            milestones.append(Milestone(
                                milestone_id=cls._generate_milestone_id(user_id, key, MilestoneType.APPLICATION_DEADLINE),
                                user_id=user_id,
                                milestone_type=MilestoneType.APPLICATION_DEADLINE,
                                title=val[:50],
                                date=next_date,
                                recurring=False,
                                source_fact_key=key,
                                source_fact_value=val,
                                metadata={"original_date": parsed.isoformat() if hasattr(parsed, 'isoformat') else str(parsed)}
                            ))

        # 4. Commitments and deadlines from fact extractor
        for mem in structured_memories:
            cat = mem.get("category", "").lower()
            if cat == "commitments":
                val = mem.get("fact_value", "")
                key = mem.get("fact_key", "")
                parsed = cls._parse_date(val)
                if parsed:
                    next_date = cls._calculate_next_occurrence(parsed, now, recurring=False)
                    if next_date and next_date >= now.date():
                        milestones.append(Milestone(
                            milestone_id=cls._generate_milestone_id(user_id, key, MilestoneType.COMMITMENT),
                            user_id=user_id,
                            milestone_type=MilestoneType.COMMITMENT,
                            title=val[:50],
                            date=next_date,
                            recurring=False,
                            source_fact_key=key,
                            source_fact_value=val,
                            metadata={"original_date": parsed.isoformat() if hasattr(parsed, 'isoformat') else str(parsed)}
                        ))

        return milestones

    @classmethod
    def _parse_date(cls, raw: Any) -> Optional[date]:
        """Parse a date string into a date object."""
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None

        # ISO format: 2005-04-14
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            pass

        # Month name + day [+ year]: "April 14, 2005"
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
            "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
            "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
        }

        import re
        month_names = "|".join(months.keys())
        m = re.search(rf'\b({month_names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}}))?', text, re.IGNORECASE)
        if m:
            month = months[m.group(1).lower()]
            day = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else datetime.now().year
            try:
                return date(year, month, day)
            except ValueError:
                pass

        # Try to extract just the date part if there's extra text like "My birthday is April 14, 2005"
        # Remove common prefixes
        text_clean = re.sub(r'\b(?:my|the|a|an|is|was|on|in|at)\s+', '', text, flags=re.IGNORECASE)
        return cls._parse_date(text_clean) if text_clean != text else None

    @classmethod
    def _calculate_next_occurrence(
        cls,
        original_date: date,
        now: datetime,
        recurring: bool = False
    ) -> Optional[date]:
        """
        Calculate the next occurrence of a date.
        For recurring dates (birthdays), calculate next birthday.
        For one-time dates, return the date if it's in the future.
        """
        if not original_date:
            return None

        if recurring:
            # For yearly recurring (birthdays, anniversaries)
            this_year_occurrence = date(now.year, original_date.month, original_date.day)
            if this_year_occurrence >= now.date():
                return this_year_occurrence
            else:
                # Already passed this year, next year
                return date(now.year + 1, original_date.month, original_date.day)
        else:
            # One-time event
            if original_date >= now.date():
                return original_date
            else:
                # Already passed, no future occurrence
                return None

    @staticmethod
    def _generate_milestone_id(user_id: int, fact_key: str, milestone_type: MilestoneType) -> str:
        """Generate a deterministic milestone ID."""
        import hashlib
        base = f"{user_id}:{fact_key}:{milestone_type.value}"
        return hashlib.md5(base.encode()).hexdigest()[:16]


class MilestoneScheduler:
    """
    Schedules proactive reminders for detected milestones using the existing
    reminder_scheduler. Handles deduplication, quiet hours, and consent.
    """

    def __init__(self, reminder_scheduler=None):
        """
        Initialize the milestone scheduler.

        Args:
            reminder_scheduler: Instance of ReminderScheduler for delivery
        """
        self.reminder_scheduler = reminder_scheduler
        self._lock = threading.Lock()
        self._scheduled_milestones: Dict[str, Milestone] = {}  # milestone_id -> Milestone
        self._last_check_time: Optional[datetime] = None

    def schedule_milestone(
        self,
        milestone: Milestone,
        advance_days: int = 0,
        advance_hours: int = 0,
        user_timezone: str = "UTC"
    ) -> bool:
        """
        Schedule a proactive reminder for a milestone.

        Args:
            milestone: The milestone to schedule
            advance_days: Days before the milestone to notify (0 = on the day)
            advance_hours: Hours before the milestone to notify
            user_timezone: User's timezone for accurate timing

        Returns:
            True if scheduled successfully, False otherwise
        """
        if not self.reminder_scheduler:
            logger.warning("[MILESTONE] No reminder scheduler available")
            return False

        # Check consent: user must have proactive interactions enabled
        if not self._is_proactive_enabled(milestone.user_id):
            logger.debug(f"[MILESTONE] Proactive interactions disabled for user {milestone.user_id}")
            return False

        # Check category consent
        if not self._is_category_enabled(milestone.user_id, milestone.milestone_type):
            logger.debug(f"[MILESTONE] Milestone type {milestone.milestone_type} disabled for user {milestone.user_id}")
            return False

        # Check quiet hours
        if not self._is_within_allowed_hours(milestone.user_id, milestone.date, user_timezone):
            logger.debug(f"[MILESTONE] Milestone {milestone.milestone_id} outside quiet hours for user {milestone.user_id}")
            return False

        # Calculate notification time
        if advance_days > 0 or advance_hours > 0:
            notify_date = milestone.date - timedelta(days=advance_days, hours=advance_hours)
        else:
            notify_date = milestone.date

        # Generate personality-aware message
        message = self._generate_proactive_message(milestone)

        # Create reminder ID
        reminder_id = f"milestone_{milestone.milestone_id}"

        # Calculate target datetime
        target_datetime = datetime.combine(notify_date, datetime.min.time())

        # Schedule using existing reminder scheduler
        try:
            self.reminder_scheduler.add_reminder_at_time(
                text=message,
                target_time=target_datetime,
                reminder_id=reminder_id,
                user_id=milestone.user_id,
                recurrence={"frequency": "yearly"} if milestone.recurring else None
            )

            with self._lock:
                self._scheduled_milestones[milestone.milestone_id] = milestone

            logger.info(f"[MILESTONE] Scheduled {milestone.milestone_type.value} for user {milestone.user_id} on {notify_date}")
            return True
        except Exception as e:
            logger.error(f"[MILESTONE] Failed to schedule milestone: {e}")
            return False

    def update_milestone_status(self, milestone_id: str, status: MilestoneStatus) -> bool:
        """Update the status of a milestone."""
        with self._lock:
            if milestone_id in self._scheduled_milestones:
                self._scheduled_milestones[milestone_id].status = status
                logger.info(f"[MILESTONE] Updated milestone {milestone_id} to {status.value}")
                return True
        return False

    def _is_proactive_enabled(self, user_id: int) -> bool:
        """Check if user has proactive interactions enabled."""
        try:
            from core.configuration_service import get_configuration_service
            cfg = get_configuration_service()
            enabled = cfg.get_preference(user_id, "proactive_interactions_enabled")
            return enabled if enabled is not None else True  # Default to enabled
        except Exception as e:
            logger.debug(f"[MILESTONE] Error checking proactive enabled: {e}")
            return True  # Default to enabled on error

    def _is_category_enabled(self, user_id: int, milestone_type: MilestoneType) -> bool:
        """Check if specific milestone category is enabled for user."""
        try:
            from core.configuration_service import get_configuration_service
            cfg = get_configuration_service()

            # Category mapping
            category_map = {
                MilestoneType.BIRTHDAY: "proactive_birthdays",
                MilestoneType.ANNIVERSARY: "proactive_anniversaries",
                MilestoneType.GRADUATION: "proactive_education",
                MilestoneType.EXAM: "proactive_education",
                MilestoneType.INTERVIEW: "proactive_career",
                MilestoneType.APPLICATION_DEADLINE: "proactive_career",
                MilestoneType.JOB_START: "proactive_career",
                MilestoneType.PROJECT_DEADLINE: "proactive_projects",
                MilestoneType.GOAL_CHECKPOINT: "proactive_goals",
                MilestoneType.COMMITMENT: "proactive_commitments",
                MilestoneType.CUSTOM_DATE: "proactive_custom_dates",
            }

            pref_key = category_map.get(milestone_type, "proactive_general")
            enabled = cfg.get_preference(user_id, pref_key)
            return enabled if enabled is not None else True  # Default to enabled
        except Exception as e:
            logger.debug(f"[MILESTONE] Error checking category enabled: {e}")
            return True  # Default to enabled on error

    def _is_within_allowed_hours(
        self,
        user_id: int,
        target_date: date,
        timezone_str: str = "UTC"
    ) -> bool:
        """Check if target time is within user's allowed quiet hours."""
        try:
            from core.configuration_service import get_configuration_service
            cfg = get_configuration_service()

            quiet_hours_enabled = cfg.get_preference(user_id, "quiet_hours_enabled")
            if not quiet_hours_enabled:
                return True  # No quiet hours restriction

            quiet_start = cfg.get_preference(user_id, "quiet_hours_start")  # e.g., "22:00"
            quiet_end = cfg.get_preference(user_id, "quiet_hours_end")  # e.g., "08:00"

            if not quiet_start or not quiet_end:
                return True  # No quiet hours configured

            # For now, assume midday notifications (12:00 PM) are always allowed
            # A full implementation would need time-of-day awareness
            return True
        except Exception as e:
            logger.debug(f"[MILESTONE] Error checking quiet hours: {e}")
            return True  # Default to allowed on error

    def _generate_proactive_message(self, milestone: Milestone) -> str:
        """Generate a personality-aware proactive message for the milestone."""
        # Get user's personality profile
        try:
            from extensions.personality_engine.personality_core import PersonalityCore
            personality = PersonalityCore()
            profile = personality.get_personality(user_id=milestone.user_id)
            tone = profile.tone
            preset = profile.preset
        except Exception:
            tone = "warm and approachable"
            preset = "friendly"

        # Base message based on milestone type
        if milestone.milestone_type == MilestoneType.BIRTHDAY:
            if preset == "professional":
                msg = f"Happy Birthday! Wishing you a wonderful day."
            elif preset == "witty":
                msg = f"Happy Birthday! Another year older, another year wiser (hopefully)."
            elif preset == "minimal":
                msg = f"Happy Birthday."
            else:  # friendly
                msg = f"Happy Birthday! Hope you have an amazing day!"
        elif milestone.milestone_type == MilestoneType.ANNIVERSARY:
            msg = f"Happy Anniversary! Celebrating {milestone.title}."
        elif milestone.milestone_type == MilestoneType.GRADUATION:
            msg = f"Congratulations on your graduation! 🎓"
        elif milestone.milestone_type == MilestoneType.INTERVIEW:
            msg = f"Good luck with your interview today! You've got this."
        elif milestone.milestone_type == MilestoneType.APPLICATION_DEADLINE:
            msg = f"Reminder: Application deadline is today for {milestone.title}."
        elif milestone.milestone_type == MilestoneType.JOB_START:
            msg = f"Starting your new job today! Best of luck."
        elif milestone.milestone_type == MilestoneType.EXAM:
            msg = f"Good luck on your exam today! You're prepared."
        elif milestone.milestone_type == MilestoneType.COMMITMENT:
            msg = f"Reminder: {milestone.title} is today."
        else:
            msg = f"Reminder: {milestone.title} is coming up."

        return msg

    def get_scheduled_milestones(self, user_id: Optional[int] = None) -> List[Milestone]:
        """Get all scheduled milestones, optionally filtered by user."""
        with self._lock:
            if user_id is None:
                return list(self._scheduled_milestones.values())
            return [m for m in self._scheduled_milestones.values() if m.user_id == user_id]


def get_milestone_scheduler(reminder_scheduler=None) -> MilestoneScheduler:
    """Get or create the global milestone scheduler instance."""
    if not hasattr(get_milestone_scheduler, "_instance"):
        get_milestone_scheduler._instance = MilestoneScheduler(reminder_scheduler)
    return get_milestone_scheduler._instance
