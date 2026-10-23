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
from datetime import datetime, timedelta, date, time as dt_time
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
    SUBSCRIPTION_RENEWAL = "subscription_renewal"   # Subscription/payment reminders
    TRAVEL_DATE = "travel_date"                      # Trips and travel preparation
    CERTIFICATION_EXPIRY = "certification_expiry"   # Expiring certifications/documents
    RECURRING_HABIT = "recurring_habit"              # Recurring commitments and habits
    INTERVIEW_FOLLOWUP = "interview_followup"        # Post-interview outcome check-in


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

    # Subscription / payment keys
    _SUBSCRIPTION_KEYS = {
        "subscription", "renewal", "payment_due", "bill", "membership",
    }

    # Travel-related keys
    _TRAVEL_KEYS = {
        "travel", "trip", "flight", "vacation", "holiday", "departure",
    }

    # Certification/document expiry keys
    _CERTIFICATION_KEYS = {
        "certification", "certificate", "license", "passport", "visa",
        "certification_expiry", "document_expiry",
    }

    @staticmethod
    def _get_mem_field(mem: Dict[str, Any], *keys: str) -> str:
        """
        Retrieve a field from a structured memory record by trying multiple
        key names. chatgpt_memory.get_structured_user_memories() returns
        records with key='key' and key='value', while raw SQL or fact_extractor
        returns fact_key / fact_value. Support both forms.
        """
        for k in keys:
            v = mem.get(k)
            if v is not None:
                return str(v)
        return ""

    @classmethod
    def detect_milestones_from_facts(
        cls,
        user_id: int,
        facts: Dict[str, str],
        structured_memories: List[Dict[str, Any]],
        timezone_str: str = "UTC",
        now_override: Optional[datetime] = None,
    ) -> List[Milestone]:
        """
        Scan user facts and structured memories for milestone candidates.
        Returns list of detected milestones with calculated next occurrences.

        Args:
            user_id: The account to scan (strict isolation enforced by caller)
            facts: Dict of {fact_key: fact_value} from get_user_facts()
            structured_memories: List of records from get_structured_user_memories()
            timezone_str: User's IANA timezone for accurate date calculations
            now_override: Optional timezone-aware datetime to use as "now".
                          When provided by ProactiveService, this is the user's
                          actual local time. Falls back to datetime.now() if None.
        """
        milestones: List[Milestone] = []
        now = now_override if now_override is not None else datetime.now()

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
            # Support both 'fact_key'/'fact_value' (raw SQL) and 'key'/'value' (chatgpt_memory)
            val = cls._get_mem_field(mem, "fact_value", "value")
            key = cls._get_mem_field(mem, "fact_key", "key")

            if cat == "education" or any(ed_key in key.lower() for ed_key in cls._EDUCATION_KEYS):
                # Graduation — only create milestone if status is not 'confirmed' completion
                # (i.e., a planned graduation date, not a retroactively confirmed fact)
                mem_status = mem.get("status", "confirmed")
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
                                metadata={
                                    "original_date": parsed.isoformat() if hasattr(parsed, 'isoformat') else str(parsed),
                                    "fact_status": mem_status,
                                }
                            ))

                # Exams, deadlines
                val_low = val.lower()
                if any(kw in val_low for kw in ("exam", "test", "deadline", "interview")):
                    parsed = cls._parse_date(val)
                    if parsed:
                        next_date = cls._calculate_next_occurrence(parsed, now, recurring=False)
                        if next_date and next_date >= now.date():
                            milestone_type = MilestoneType.EXAM if "exam" in val_low or "test" in val_low else MilestoneType.INTERVIEW
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
            val = cls._get_mem_field(mem, "fact_value", "value")
            key = cls._get_mem_field(mem, "fact_key", "key")

            if cat == "employment" or any(cr_key in key.lower() for cr_key in cls._CAREER_KEYS):
                val_low = val.lower()
                # Job start
                if any(kw in val_low for kw in ("start", "join", "onboard")):
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
                if "deadline" in val_low or "apply" in val_low:
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
                val = cls._get_mem_field(mem, "fact_value", "value")
                key = cls._get_mem_field(mem, "fact_key", "key")
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

        # 4b. Interview follow-up (post-event, outcome unknown)
        # After an interview date has passed (within a short follow-up window),
        # ask how it went rather than assuming success or failure. Consent is
        # enforced at scheduling time via the INTERVIEW_FOLLOWUP -> proactive_career
        # mapping in MilestoneScheduler.
        _followup_window_days = 2
        for mem in structured_memories:
            val = cls._get_mem_field(mem, "fact_value", "value")
            key = cls._get_mem_field(mem, "fact_key", "key")
            if "interview" not in val.lower() and "interview" not in key.lower():
                continue
            parsed = cls._parse_date(val)
            if not parsed:
                continue
            # Follow-up window: interview has happened, but only recently
            days_since = (now.date() - parsed).days
            if 0 < days_since <= _followup_window_days:
                followup_date = parsed + timedelta(days=1)
                milestones.append(Milestone(
                    milestone_id=cls._generate_milestone_id(user_id, f"{key}_interview_followup", MilestoneType.INTERVIEW_FOLLOWUP),
                    user_id=user_id,
                    milestone_type=MilestoneType.INTERVIEW_FOLLOWUP,
                    title="Interview Follow-up",
                    date=followup_date,
                    recurring=False,
                    source_fact_key=key,
                    source_fact_value=val,
                    metadata={"interview_date": parsed.isoformat()}
                ))

        # 5. Subscription / Payment renewals
        for mem in structured_memories:
            cat = mem.get("category", "").lower()
            val = cls._get_mem_field(mem, "fact_value", "value")
            key = cls._get_mem_field(mem, "fact_key", "key")

            if any(sub_key in key.lower() for sub_key in cls._SUBSCRIPTION_KEYS):
                parsed = cls._parse_date(val)
                if parsed:
                    next_date = cls._calculate_next_occurrence(parsed, now, recurring=True)
                    if next_date:
                        milestones.append(Milestone(
                            milestone_id=cls._generate_milestone_id(user_id, key, MilestoneType.SUBSCRIPTION_RENEWAL),
                            user_id=user_id,
                            milestone_type=MilestoneType.SUBSCRIPTION_RENEWAL,
                            title=f"Renewal: {key.replace('_', ' ').title()}",
                            date=next_date,
                            recurring=True,
                            recurrence_rule="yearly",
                            source_fact_key=key,
                            source_fact_value=val,
                            metadata={"original_date": parsed.isoformat() if hasattr(parsed, 'isoformat') else str(parsed)}
                        ))

        # 6. Travel dates
        for mem in structured_memories:
            val = cls._get_mem_field(mem, "fact_value", "value")
            key = cls._get_mem_field(mem, "fact_key", "key")

            if any(tr_key in key.lower() for tr_key in cls._TRAVEL_KEYS):
                parsed = cls._parse_date(val)
                if parsed:
                    next_date = cls._calculate_next_occurrence(parsed, now, recurring=False)
                    if next_date and next_date >= now.date():
                        milestones.append(Milestone(
                            milestone_id=cls._generate_milestone_id(user_id, key, MilestoneType.TRAVEL_DATE),
                            user_id=user_id,
                            milestone_type=MilestoneType.TRAVEL_DATE,
                            title=f"Travel: {key.replace('_', ' ').title()}",
                            date=next_date,
                            recurring=False,
                            source_fact_key=key,
                            source_fact_value=val,
                            metadata={"original_date": parsed.isoformat() if hasattr(parsed, 'isoformat') else str(parsed)}
                        ))

        # 7. Certification / document expiry
        for mem in structured_memories:
            val = cls._get_mem_field(mem, "fact_value", "value")
            key = cls._get_mem_field(mem, "fact_key", "key")

            if any(cert_key in key.lower() for cert_key in cls._CERTIFICATION_KEYS):
                parsed = cls._parse_date(val)
                if parsed:
                    next_date = cls._calculate_next_occurrence(parsed, now, recurring=False)
                    if next_date and next_date >= now.date():
                        milestones.append(Milestone(
                            milestone_id=cls._generate_milestone_id(user_id, key, MilestoneType.CERTIFICATION_EXPIRY),
                            user_id=user_id,
                            milestone_type=MilestoneType.CERTIFICATION_EXPIRY,
                            title=f"Expiry: {key.replace('_', ' ').title()}",
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

        # Embedded ISO date within surrounding text: "interview tomorrow (2026-10-24)"
        import re as _re
        _iso = _re.search(r'\b(\d{4}-\d{2}-\d{2})\b', text)
        if _iso:
            try:
                return datetime.strptime(_iso.group(1), "%Y-%m-%d").date()
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

        Handles Feb 29 (leap day) birthdays correctly:
        - In a non-leap year, the birthday is celebrated on Mar 1.
        - The returned date is always a valid calendar date.
        """
        import calendar
        if not original_date:
            return None

        def _safe_birthday(year: int, month: int, day: int) -> date:
            """Return a valid date for the given year, handling Feb 29 in non-leap years."""
            if month == 2 and day == 29 and not calendar.isleap(year):
                return date(year, 3, 1)  # Celebrate on Mar 1 in non-leap years
            return date(year, month, day)

        if recurring:
            # For yearly recurring (birthdays, anniversaries)
            this_year_occurrence = _safe_birthday(now.year, original_date.month, original_date.day)
            if this_year_occurrence >= now.date():
                return this_year_occurrence
            else:
                # Already passed this year, next year
                return _safe_birthday(now.year + 1, original_date.month, original_date.day)
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

        # Calculate target datetime at the user's configured notification time
        # (default 09:00 local) so delivery matches the quiet-hours check instead
        # of silently firing at midnight.
        hour, minute = self._get_notification_time_of_day(milestone.user_id)
        target_datetime = datetime.combine(notify_date, dt_time(hour=hour, minute=minute))

        # Same-day prompt delivery: if the configured notification moment has
        # already passed today but the milestone is still current, deliver
        # promptly rather than letting the reminder engine roll it a full day
        # late (the day-late birthday bug).
        now_local = datetime.now()
        if target_datetime <= now_local and notify_date >= now_local.date():
            target_datetime = now_local + timedelta(seconds=30)

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

    def _get_notification_time_of_day(self, user_id: int):
        """Return the user's configured proactive notification time as (hour, minute).

        Falls back to 09:00 local when unset or unparseable, matching the default
        used by the quiet-hours check.
        """
        try:
            from core.configuration_service import get_configuration_service
            cfg = get_configuration_service()
            notif_str = cfg.get_preference(user_id, "proactive_notification_time")
            if notif_str:
                parts = str(notif_str).strip().split(":")
                if len(parts) >= 2:
                    return int(parts[0]), int(parts[1])
        except Exception:
            pass
        return 9, 0  # Default 09:00 local

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
                MilestoneType.INTERVIEW_FOLLOWUP: "proactive_career",
                MilestoneType.APPLICATION_DEADLINE: "proactive_career",
                MilestoneType.JOB_START: "proactive_career",
                MilestoneType.PROJECT_DEADLINE: "proactive_projects",
                MilestoneType.GOAL_CHECKPOINT: "proactive_goals",
                MilestoneType.COMMITMENT: "proactive_commitments",
                MilestoneType.CUSTOM_DATE: "proactive_custom_dates",
                MilestoneType.SUBSCRIPTION_RENEWAL: "proactive_subscriptions",
                MilestoneType.TRAVEL_DATE: "proactive_travel",
                MilestoneType.CERTIFICATION_EXPIRY: "proactive_certifications",
                MilestoneType.RECURRING_HABIT: "proactive_habits",
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
        """
        Check whether the proposed notification time falls outside the user's
        configured quiet hours.

        Notification time is assumed to be the user's configured
        'proactive_notification_time' (default 09:00 local time).
        Quiet hours are enforced even across midnight boundaries
        (e.g., start=22:00, end=08:00).
        """
        try:
            from core.configuration_service import get_configuration_service
            cfg = get_configuration_service()

            quiet_hours_enabled = cfg.get_preference(user_id, "quiet_hours_enabled")
            if not quiet_hours_enabled:
                return True  # No quiet hours restriction

            quiet_start_str = cfg.get_preference(user_id, "quiet_hours_start")  # e.g. "22:00"
            quiet_end_str = cfg.get_preference(user_id, "quiet_hours_end")    # e.g. "08:00"

            if not quiet_start_str or not quiet_end_str:
                return True  # No quiet hours configured

            # Determine proposed notification time (default 09:00)
            notif_time_str = cfg.get_preference(user_id, "proactive_notification_time") or "09:00"

            def _parse_hhmm(s: str):
                """Parse HH:MM string into (hour, minute) tuple."""
                parts = str(s).strip().split(":")
                if len(parts) >= 2:
                    try:
                        return int(parts[0]), int(parts[1])
                    except ValueError:
                        pass
                return None

            qs = _parse_hhmm(quiet_start_str)
            qe = _parse_hhmm(quiet_end_str)
            nt = _parse_hhmm(notif_time_str)

            if not (qs and qe and nt):
                return True  # Unparseable config — allow by default

            def _minutes(h, m):
                return h * 60 + m

            notif_mins = _minutes(*nt)
            start_mins = _minutes(*qs)
            end_mins = _minutes(*qe)

            if start_mins <= end_mins:
                # Simple range: quiet from start to end (same day)
                in_quiet = start_mins <= notif_mins < end_mins
            else:
                # Overnight range: quiet from start to midnight + midnight to end
                in_quiet = notif_mins >= start_mins or notif_mins < end_mins

            return not in_quiet  # Allowed if NOT in quiet period

        except Exception as e:
            logger.debug(f"[MILESTONE] Error checking quiet hours: {e}")
            return True  # Default to allowed on error

    def _generate_proactive_message(self, milestone: Milestone) -> str:
        """
        Generate a personality-aware proactive message for the milestone.

        For milestones whose outcome is uncertain (INTERVIEW_FOLLOWUP, EXAM
        that has passed, etc.) the message is a question, never a fabricated
        statement of result.
        """
        # Get user's personality profile
        try:
            from extensions.personality_engine.personality_core import PersonalityCore
            personality = PersonalityCore()
            profile = personality.get_personality(user_id=milestone.user_id)
            preset = profile.preset
        except Exception:
            preset = "friendly"

        # ── Birthday ────────────────────────────────────────────────────────
        if milestone.milestone_type == MilestoneType.BIRTHDAY:
            if preset == "professional":
                msg = "Happy Birthday! Wishing you a productive and wonderful day."
            elif preset == "witty":
                msg = "Happy Birthday! Another year older, another year wiser — hopefully!"
            elif preset == "minimal":
                msg = "Happy Birthday."
            elif preset == "energetic":
                msg = "Happy Birthday! 🎉 Hope your day is absolutely amazing!"
            else:  # friendly / default
                msg = "Happy Birthday! 🎂 Hope you have an amazing day!"

        # ── Anniversary ─────────────────────────────────────────────────────
        elif milestone.milestone_type == MilestoneType.ANNIVERSARY:
            msg = f"Happy Anniversary! Celebrating {milestone.title}."

        # ── Graduation ──────────────────────────────────────────────────────
        elif milestone.milestone_type == MilestoneType.GRADUATION:
            msg = "Your graduation date is approaching! Wishing you all the best. 🎓"

        # ── Interview (pre-event) ────────────────────────────────────────────
        elif milestone.milestone_type == MilestoneType.INTERVIEW:
            if preset == "professional":
                msg = "Reminder: Your interview is today. Best of luck."
            elif preset == "witty":
                msg = "Interview day! Show them what you're made of — you've got this."
            elif preset == "minimal":
                msg = "Interview today. Good luck."
            else:
                msg = "Good luck with your interview today! You've got this. 💪"

        # ── Interview follow-up (post-event, outcome unknown) ────────────────
        elif milestone.milestone_type == MilestoneType.INTERVIEW_FOLLOWUP:
            msg = "How did your interview go? I'd love to hear!"

        # ── Application deadline ─────────────────────────────────────────────
        elif milestone.milestone_type == MilestoneType.APPLICATION_DEADLINE:
            msg = f"Reminder: Application deadline today — {milestone.title}. Don't miss it!"

        # ── Job start ────────────────────────────────────────────────────────
        elif milestone.milestone_type == MilestoneType.JOB_START:
            if preset == "professional":
                msg = "Today is your first day at the new role. Wishing you a strong start."
            elif preset == "witty":
                msg = "First day at the new job — go make a great impression!"
            else:
                msg = "Starting your new job today! Best of luck. 🚀"

        # ── Exam ────────────────────────────────────────────────────────────
        elif milestone.milestone_type == MilestoneType.EXAM:
            msg = "Good luck on your exam today! You're prepared. 📚"

        # ── Project deadline ─────────────────────────────────────────────────
        elif milestone.milestone_type == MilestoneType.PROJECT_DEADLINE:
            msg = f"Project deadline reminder: {milestone.title} is due today."

        # ── Goal checkpoint ──────────────────────────────────────────────────
        elif milestone.milestone_type == MilestoneType.GOAL_CHECKPOINT:
            msg = f"Time to check in on your goal: {milestone.title}. How's it going?"

        # ── Subscription renewal ─────────────────────────────────────────────
        elif milestone.milestone_type == MilestoneType.SUBSCRIPTION_RENEWAL:
            msg = f"Reminder: {milestone.title} renewal is coming up. Want to take any action?"

        # ── Travel date ──────────────────────────────────────────────────────
        elif milestone.milestone_type == MilestoneType.TRAVEL_DATE:
            msg = f"Travel reminder: {milestone.title} is today. Have a safe journey! ✈️"

        # ── Certification expiry ─────────────────────────────────────────────
        elif milestone.milestone_type == MilestoneType.CERTIFICATION_EXPIRY:
            msg = f"Heads up: {milestone.title} is expiring soon. Time to renew?"

        # ── Recurring habit ───────────────────────────────────────────────────
        elif milestone.milestone_type == MilestoneType.RECURRING_HABIT:
            msg = f"Time for your recurring commitment: {milestone.title}."

        # ── Commitment / default ─────────────────────────────────────────────
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
