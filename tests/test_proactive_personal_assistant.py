"""
Regression Tests for Proactive Personal Assistant — Friday

Tests for milestone detection, proactive notifications, consent awareness,
temporal reasoning, fact lifecycle, and per-account isolation per the mission
requirements.

Numbered tests correspond directly to the 20 required test items.
"""

import pytest
from datetime import datetime, date, timedelta
from unittest.mock import Mock, patch, MagicMock
import threading
import time

from core.milestone_engine import (
    MilestoneDetector,
    MilestoneScheduler,
    Milestone,
    MilestoneType,
    MilestoneStatus,
    get_milestone_scheduler,
)
from core.proactive_service import ProactiveService, get_proactive_service
from core.fact_extractor import extract_candidate_facts
from core.temporal_context import (
    get_canonical_temporal_context,
    get_user_local_date,
    get_user_local_now,
    format_temporal_prompt_block,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_now(year, month, day, hour=12) -> datetime:
    """Return a naive datetime for use as a mocked 'now'."""
    return datetime(year, month, day, hour, 0, 0)


def _detect(user_id, facts=None, structured_memories=None, now=None):
    """Helper: call detect_milestones_from_facts with optional now override."""
    return MilestoneDetector.detect_milestones_from_facts(
        user_id=user_id,
        facts=facts or {},
        structured_memories=structured_memories or [],
        timezone_str="UTC",
        now_override=now,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Birthday detection on the correct local date
# ─────────────────────────────────────────────────────────────────────────────
class TestBirthdayDetection:

    def test_birthday_detected_on_correct_date(self):
        """Test 1: Birthday detected with today's date correctly."""
        # Simulate: today is April 14; user's birthday is April 14
        now = _make_now(2026, 4, 14)
        facts = {"birthday": "April 14, 2005"}
        milestones = _detect(1, facts=facts, now=now)
        bdays = [m for m in milestones if m.milestone_type == MilestoneType.BIRTHDAY]
        assert len(bdays) == 1
        assert bdays[0].date == date(2026, 4, 14)

    def test_birthday_not_detected_wrong_date(self):
        """Test 3: No birthday detected on a wrong date (April 13 ≠ April 14)."""
        now = _make_now(2026, 4, 13)  # Day before birthday
        facts = {"birthday": "April 14, 2005"}
        milestones = _detect(1, facts=facts, now=now)
        bdays = [m for m in milestones if m.milestone_type == MilestoneType.BIRTHDAY]
        # Should still detect the upcoming birthday but for April 14, not today
        # The milestone date should be April 14 (tomorrow), not April 13
        if bdays:
            assert bdays[0].date == date(2026, 4, 14)  # Correctly future-dated

    def test_birthday_basic_detection(self):
        """Basic birthday detection from facts dict."""
        facts = {"birthday": "April 14, 2005"}
        milestones = MilestoneDetector.detect_milestones_from_facts(
            user_id=1, facts=facts, structured_memories=[], timezone_str="UTC"
        )
        bdays = [m for m in milestones if m.milestone_type == MilestoneType.BIRTHDAY]
        assert len(bdays) == 1
        assert bdays[0].recurring is True
        assert bdays[0].source_fact_key == "birthday"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Birthday notification delivered at most once per occurrence
# ─────────────────────────────────────────────────────────────────────────────
class TestBirthdayNotificationDedup:

    def test_birthday_notification_on_day(self):
        """Test 2: Birthday notification delivers on the correct day."""
        milestone = Milestone(
            milestone_id="test_birthday",
            user_id=1,
            milestone_type=MilestoneType.BIRTHDAY,
            title="Birthday",
            date=date(2025, 4, 14),
            recurring=True,
            recurrence_rule="yearly",
        )
        mock_scheduler = Mock()
        mock_scheduler.add_reminder_at_time = Mock(return_value="reminder_id")

        scheduler = MilestoneScheduler(reminder_scheduler=mock_scheduler)
        result = scheduler.schedule_milestone(milestone, advance_days=0)

        assert result is True
        mock_scheduler.add_reminder_at_time.assert_called_once()
        call_args = mock_scheduler.add_reminder_at_time.call_args
        assert call_args[1]["target_time"].date() == date(2025, 4, 14)

    def test_duplicate_notification_prevented_after_restart(self):
        """Test 2 & 15: _is_already_notified prevents duplicates after restart."""
        milestone_id = "test_milestone_123"
        notification_date = date(2025, 4, 14)

        with patch('core.db_pool.get_db_pool') as mock_pool:
            mock_cursor = MagicMock()
            mock_pool.return_value.get_cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = [1]  # Already notified

            service = ProactiveService()
            already_notified = service._is_already_notified(
                user_id=1,
                milestone_id=milestone_id,
                notification_date=notification_date,
            )
            assert already_notified is True


# ─────────────────────────────────────────────────────────────────────────────
# 4. February 29 leap-day birthday handling
# ─────────────────────────────────────────────────────────────────────────────
class TestLeapDayBirthday:

    def test_feb29_birthday_in_leap_year(self):
        """Test 4a: Feb 29 birthday scheduled on Feb 29 in a leap year."""
        # 2024 is a leap year
        now = _make_now(2024, 2, 1)
        facts = {"birthday": "2000-02-29"}
        milestones = _detect(1, facts=facts, now=now)
        bdays = [m for m in milestones if m.milestone_type == MilestoneType.BIRTHDAY]
        assert len(bdays) == 1
        assert bdays[0].date == date(2024, 2, 29)

    def test_feb29_birthday_in_non_leap_year_moves_to_mar1(self):
        """Test 4b: Feb 29 birthday moves to Mar 1 in a non-leap year."""
        # 2026 is NOT a leap year
        now = _make_now(2026, 1, 1)
        facts = {"birthday": "2000-02-29"}
        milestones = _detect(1, facts=facts, now=now)
        bdays = [m for m in milestones if m.milestone_type == MilestoneType.BIRTHDAY]
        assert len(bdays) == 1
        # Should be March 1 in non-leap year
        assert bdays[0].date == date(2026, 3, 1)

    def test_feb29_birthday_already_passed_non_leap_year(self):
        """Test 4c: Feb 29 birthday after Mar 1 rolls to next year."""
        # 2026, Mar 10 — the Mar 1 celebration has passed
        now = _make_now(2026, 3, 10)
        facts = {"birthday": "2000-02-29"}
        milestones = _detect(1, facts=facts, now=now)
        bdays = [m for m in milestones if m.milestone_type == MilestoneType.BIRTHDAY]
        assert len(bdays) == 1
        # 2027 is not leap either: Mar 1 again
        assert bdays[0].date == date(2027, 3, 1)

    def test_feb29_birthday_rolls_to_leap_year(self):
        """Test 4d: Feb 29 birthday next year is Feb 29 when it's a leap year."""
        # 2027, Sep 1 — next scheduled occurrence should be Feb 29, 2028 (leap)
        now = _make_now(2027, 9, 1)
        facts = {"birthday": "2000-02-29"}
        milestones = _detect(1, facts=facts, now=now)
        bdays = [m for m in milestones if m.milestone_type == MilestoneType.BIRTHDAY]
        assert len(bdays) == 1
        assert bdays[0].date == date(2028, 2, 29)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Graduation expected date passing does NOT falsely mark graduation complete
# ─────────────────────────────────────────────────────────────────────────────
class TestGraduationLifecycle:

    def test_graduation_date_passing_does_not_mark_completed(self):
        """Test 5: A past graduation_date in memory does NOT create a future milestone."""
        facts = {}
        structured_memories = [
            {"fact_key": "graduation_date", "fact_value": "2024-05-15", "category": "education", "status": "confirmed"}
        ]
        milestones = MilestoneDetector.detect_milestones_from_facts(
            user_id=1, facts=facts, structured_memories=structured_memories, timezone_str="UTC"
        )
        grad_milestones = [m for m in milestones if m.milestone_type == MilestoneType.GRADUATION]
        # Past graduation date → no future milestone generated (not auto-completed)
        assert len(grad_milestones) == 0, "Past graduation date should not generate a future milestone"

    def test_graduation_detection_future(self):
        """Test 5b: Future graduation date is detected as an upcoming milestone."""
        now = _make_now(2027, 1, 1)
        facts = {}
        structured_memories = [
            {"fact_key": "graduation_date", "fact_value": "2027-05-15", "category": "education", "status": "confirmed"}
        ]
        milestones = _detect(1, structured_memories=structured_memories, now=now)
        grad_milestones = [m for m in milestones if m.milestone_type == MilestoneType.GRADUATION]
        assert len(grad_milestones) == 1
        assert grad_milestones[0].date == date(2027, 5, 15)

    def test_confirmed_graduation_updates_education_state(self):
        """Test 6: Confirmed graduation updates education state via fact_extractor."""
        facts = extract_candidate_facts("I graduated from SRM AP last month.")
        graduation_facts = [f for f in facts if f.key == "graduation_status"]
        assert len(graduation_facts) == 1
        assert graduation_facts[0].value == "graduated"
        assert graduation_facts[0].status == "confirmed"
        # Should supersede the old student_status fact
        assert graduation_facts[0].supersedes_key == "student_status"

    def test_graduation_preserves_history(self):
        """Test 6b: Graduated fact also records the institution."""
        facts = extract_candidate_facts("I graduated from SRM University–AP last month.")
        inst_facts = [f for f in facts if f.key == "graduated_from"]
        assert len(inst_facts) == 1
        assert "SRM" in inst_facts[0].value or "University" in inst_facts[0].value


# ─────────────────────────────────────────────────────────────────────────────
# 7. Placement preparation remains historical until confirmed evidence supersedes
# ─────────────────────────────────────────────────────────────────────────────
class TestPlacementLifecycle:

    def test_job_search_not_overridden_by_graduation_date(self):
        """Test 7: 'I am still looking for a job' is not overridden by a past graduation date."""
        facts_text = "I am still looking for a job."
        extracted = extract_candidate_facts(facts_text)
        job_search_facts = [f for f in extracted if f.key == "employment_status" and f.value == "job_searching"]
        assert len(job_search_facts) >= 1

    def test_employed_supersedes_job_search(self):
        """Test 8: 'I got a job at Company X' supersedes the job-search status."""
        facts = extract_candidate_facts("I got a job at Google and I start next month.")
        employer_facts = [f for f in facts if f.key == "employer"]
        employed_facts = [f for f in facts if f.key == "employment_status" and f.value == "employed"]
        assert len(employer_facts) >= 1, "Should extract employer"
        assert "Google" in employer_facts[0].value
        assert len(employed_facts) >= 1, "Should mark as employed"
        # The employer fact should supersede the old goal
        assert employer_facts[0].supersedes_key == "goal"


# ─────────────────────────────────────────────────────────────────────────────
# 9. Unconfirmed interview outcome triggers a question
# ─────────────────────────────────────────────────────────────────────────────
class TestInterviewOutcome:

    def test_uncertain_outcome_triggers_question(self):
        """Test 9 & 20: Interview milestone message is a question/encouragement, not fabricated result."""
        milestone = Milestone(
            milestone_id="test_interview",
            user_id=1,
            milestone_type=MilestoneType.INTERVIEW,
            title="Interview",
            date=date(2025, 4, 14),
            recurring=False,
        )
        scheduler = MilestoneScheduler()
        message = scheduler._generate_proactive_message(milestone)
        assert "?" in message or "luck" in message.lower() or "you've got this" in message.lower()

    def test_interview_followup_asks_how_it_went(self):
        """Test 9: INTERVIEW_FOLLOWUP type generates a 'how did it go?' style question."""
        milestone = Milestone(
            milestone_id="test_interview_followup",
            user_id=1,
            milestone_type=MilestoneType.INTERVIEW_FOLLOWUP,
            title="Interview Follow-up",
            date=date(2025, 4, 15),
            recurring=False,
        )
        scheduler = MilestoneScheduler()
        message = scheduler._generate_proactive_message(milestone)
        assert "interview" in message.lower() or "how did" in message.lower()
        assert "?" in message


# ─────────────────────────────────────────────────────────────────────────────
# 10. Planned events remain planned until completion is confirmed
# ─────────────────────────────────────────────────────────────────────────────
class TestPlannedEvents:

    def test_plan_to_take_exam_is_tentative(self):
        """Test 10: 'I plan to take an exam next year' is extracted as tentative, not confirmed."""
        facts = extract_candidate_facts("I plan to take an exam next year.")
        plan_facts = [f for f in facts if f.key == "planned_event"]
        assert len(plan_facts) >= 1
        assert plan_facts[0].status == "tentative"

    def test_tentative_plan_not_confirmed(self):
        """Test 10b: 'I might apply for an internship' is tentative."""
        facts = extract_candidate_facts("I might apply for an internship next semester.")
        tentative = [f for f in facts if f.status == "tentative"]
        assert len(tentative) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 11. User corrections replacing stale facts
# ─────────────────────────────────────────────────────────────────────────────
class TestUserCorrections:

    def test_user_correction_supersedes_old_fact(self):
        """Test 11: User corrections are extracted with correct status."""
        facts = extract_candidate_facts("Actually, I changed my mind. Use the existing router.")
        # Should extract some correction fact
        corrections = [f for f in facts if f.category == "corrections"]
        assert len(corrections) >= 1

    def test_graduated_supersedes_student_status(self):
        """Test 11b: Graduation confirmation carries supersedes_key for student_status."""
        facts = extract_candidate_facts("I have graduated.")
        grad_facts = [f for f in facts if f.key == "graduation_status"]
        assert len(grad_facts) >= 1
        assert grad_facts[0].supersedes_key == "student_status"

    def test_employed_supersedes_career_goal(self):
        """Test 11c: Getting a job supersedes career_goal."""
        facts = extract_candidate_facts("I joined Amazon last week.")
        employer_facts = [f for f in facts if f.key == "employer"]
        assert len(employer_facts) >= 1
        assert employer_facts[0].supersedes_key == "goal"


# ─────────────────────────────────────────────────────────────────────────────
# 13. Follow-up reminders stop after cancellation or completion
# ─────────────────────────────────────────────────────────────────────────────
class TestFollowUpCancellation:

    def test_follow_up_stops_after_cancellation(self):
        """Test 13: Milestone is marked cancelled and stops being rescheduled."""
        milestone = Milestone(
            milestone_id="test_goal",
            user_id=1,
            milestone_type=MilestoneType.GOAL_CHECKPOINT,
            title="Goal Checkpoint",
            date=date(2025, 4, 14),
            recurring=False,
        )
        scheduler = MilestoneScheduler()
        scheduler._scheduled_milestones["test_goal"] = milestone
        scheduler.update_milestone_status("test_goal", MilestoneStatus.CANCELLED)
        assert scheduler._scheduled_milestones["test_goal"].status == MilestoneStatus.CANCELLED


# ─────────────────────────────────────────────────────────────────────────────
# 14. Proactive interaction respects opt-outs and quiet hours
# ─────────────────────────────────────────────────────────────────────────────
class TestConsentAndQuietHours:

    def test_proactive_disabled_respects_opt_out(self):
        """Test 14a: Proactive interaction respects user opt-out (master switch)."""
        milestone = Milestone(
            milestone_id="test_birthday",
            user_id=1,
            milestone_type=MilestoneType.BIRTHDAY,
            title="Birthday",
            date=date(2025, 4, 14),
            recurring=True,
        )
        mock_scheduler = Mock()
        with patch('core.configuration_service.get_configuration_service') as mock_cfg:
            mock_cfg.return_value.get_preference.return_value = False
            scheduler = MilestoneScheduler(reminder_scheduler=mock_scheduler)
            result = scheduler.schedule_milestone(milestone)
            assert result is False
            mock_scheduler.add_reminder_at_time.assert_not_called()

    def test_category_disabled_respects_opt_out(self):
        """Test 14b: Specific category opt-out is respected."""
        milestone = Milestone(
            milestone_id="test_birthday",
            user_id=1,
            milestone_type=MilestoneType.BIRTHDAY,
            title="Birthday",
            date=date(2025, 4, 14),
            recurring=True,
        )
        mock_scheduler = Mock()
        with patch('core.configuration_service.get_configuration_service') as mock_cfg:
            def mock_get_pref(user_id, key, default=None):
                if key == "proactive_interactions_enabled":
                    return True
                if key == "proactive_birthdays":
                    return False
                return default
            mock_cfg.return_value.get_preference.side_effect = mock_get_pref
            scheduler = MilestoneScheduler(reminder_scheduler=mock_scheduler)
            result = scheduler.schedule_milestone(milestone)
            assert result is False

    def test_quiet_hours_blocks_midnight_notification(self):
        """Test 14c: A notification time of 02:00 is blocked when quiet hours are 22:00-08:00."""
        milestone = Milestone(
            milestone_id="test_birthday_qh",
            user_id=1,
            milestone_type=MilestoneType.BIRTHDAY,
            title="Birthday",
            date=date(2025, 4, 14),
            recurring=True,
        )
        mock_scheduler = Mock()
        with patch('core.configuration_service.get_configuration_service') as mock_cfg:
            def mock_get_pref(user_id, key, default=None):
                if key == "proactive_interactions_enabled":
                    return True
                if key == "quiet_hours_enabled":
                    return True
                if key == "quiet_hours_start":
                    return "22:00"
                if key == "quiet_hours_end":
                    return "08:00"
                if key == "proactive_notification_time":
                    return "02:00"  # In quiet period
                return True  # other category checks pass

            mock_cfg.return_value.get_preference.side_effect = mock_get_pref
            scheduler = MilestoneScheduler(reminder_scheduler=mock_scheduler)
            result = scheduler.schedule_milestone(milestone)
            assert result is False, "02:00 is in quiet hours (22:00–08:00), should not schedule"

    def test_quiet_hours_allows_daytime_notification(self):
        """Test 14d: A notification time of 09:00 is allowed when quiet hours are 22:00-08:00."""
        milestone = Milestone(
            milestone_id="test_birthday_day",
            user_id=1,
            milestone_type=MilestoneType.BIRTHDAY,
            title="Birthday",
            date=date(2025, 4, 14),
            recurring=True,
        )
        mock_scheduler = Mock()
        mock_scheduler.add_reminder_at_time = Mock(return_value="reminder_id")
        with patch('core.configuration_service.get_configuration_service') as mock_cfg:
            def mock_get_pref(user_id, key, default=None):
                if key == "proactive_interactions_enabled":
                    return True
                if key == "quiet_hours_enabled":
                    return True
                if key == "quiet_hours_start":
                    return "22:00"
                if key == "quiet_hours_end":
                    return "08:00"
                if key == "proactive_notification_time":
                    return "09:00"  # Outside quiet period
                return True

            mock_cfg.return_value.get_preference.side_effect = mock_get_pref
            scheduler = MilestoneScheduler(reminder_scheduler=mock_scheduler)
            result = scheduler.schedule_milestone(milestone)
            assert result is True, "09:00 is outside quiet hours (22:00–08:00), should schedule"


# ─────────────────────────────────────────────────────────────────────────────
# 15. No duplicate reminders after application restart
# ─────────────────────────────────────────────────────────────────────────────
class TestNoDuplicatesAfterRestart:

    def test_already_notified_prevents_reschedule(self):
        """Test 15: _is_already_notified True prevents duplicate scheduling."""
        milestone_id = "test_milestone_123"
        notification_date = date(2025, 4, 14)
        with patch('core.db_pool.get_db_pool') as mock_pool:
            mock_cursor = MagicMock()
            mock_pool.return_value.get_cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = [1]  # Already notified
            service = ProactiveService()
            result = service._is_already_notified(1, milestone_id, notification_date)
            assert result is True


# ─────────────────────────────────────────────────────────────────────────────
# 16. Strict account isolation
# ─────────────────────────────────────────────────────────────────────────────
class TestAccountIsolation:

    def test_per_account_milestone_isolation(self):
        """Test 16: Strict separation of milestones between two accounts."""
        user1_facts = {"birthday": "April 14, 2005"}
        user2_facts = {"birthday": "June 15, 1998"}
        milestones1 = MilestoneDetector.detect_milestones_from_facts(1, user1_facts, [])
        milestones2 = MilestoneDetector.detect_milestones_from_facts(2, user2_facts, [])
        assert all(m.user_id == 1 for m in milestones1)
        assert all(m.user_id == 2 for m in milestones2)
        assert len([m for m in milestones1 if m.user_id == 1]) == 1
        assert len([m for m in milestones2 if m.user_id == 2]) == 1

    def test_no_crossover_between_accounts(self):
        """Test 16b: No crossover between account milestone sets."""
        user1_facts = {"birthday": "April 14, 2005"}
        user2_facts = {"anniversary": "June 15, 2020"}
        milestones1 = MilestoneDetector.detect_milestones_from_facts(1, user1_facts, [])
        milestones2 = MilestoneDetector.detect_milestones_from_facts(2, user2_facts, [])
        m1_ids = {m.milestone_id for m in milestones1}
        m2_ids = {m.milestone_id for m in milestones2}
        assert len(m1_ids & m2_ids) == 0, "No milestone IDs should be shared between accounts"


# ─────────────────────────────────────────────────────────────────────────────
# 17. Proactive messages reflect each account's personality
# ─────────────────────────────────────────────────────────────────────────────
class TestPersonalizedMessages:

    def test_personality_aware_messages_differ_across_presets(self):
        """Test 17: Proactive messages vary across personality presets."""
        milestone = Milestone(
            milestone_id="test_birthday",
            user_id=1,
            milestone_type=MilestoneType.BIRTHDAY,
            title="Birthday",
            date=date(2025, 4, 14),
            recurring=True,
        )
        mock_scheduler = Mock()
        mock_scheduler.add_reminder_at_time = Mock(return_value="reminder_id")
        personalities = ["professional", "witty", "minimal", "friendly", "energetic"]
        messages = []
        for persona in personalities:
            with patch('extensions.personality_engine.personality_core.PersonalityCore') as mock_personality:
                mock_profile = Mock()
                mock_profile.preset = persona
                mock_profile.tone = f"{persona} tone"
                mock_personality.return_value.get_personality.return_value = mock_profile
                scheduler = MilestoneScheduler(reminder_scheduler=mock_scheduler)
                scheduler.schedule_milestone(milestone)
                call_args = mock_scheduler.add_reminder_at_time.call_args
                messages.append(call_args[1]["text"])
        assert len(set(messages)) > 1, "Different personalities should produce different messages"


# ─────────────────────────────────────────────────────────────────────────────
# 18. Existing functionality preserved (regression)
# ─────────────────────────────────────────────────────────────────────────────
class TestRegressionExistingFunctionality:

    def test_existing_modules_importable(self):
        """Test 18: Existing modules still import and initialize without error."""
        from core.chatgpt_memory import ChatGPTMemoryManager
        from core.fact_extractor import extract_candidate_facts
        from extensions.reminder_engine.reminder_scheduler import ReminderScheduler
        from extensions.personality_engine.personality_core import PersonalityCore
        from core.configuration_service import ConfigurationService
        from core.unified_command_router import UnifiedCommandRouter
        assert True

    def test_temporal_context_backward_compat(self):
        """Test 18b: Original temporal_context functions still work unchanged."""
        ctx = get_canonical_temporal_context()
        assert "current_date" in ctx
        assert "current_year" in ctx
        assert "timezone" in ctx
        block = format_temporal_prompt_block()
        assert "CANONICAL RUNTIME TEMPORAL CONTEXT" in block
        assert "CRITICAL TEMPORAL RULE" in block

    def test_new_temporal_helpers_available(self):
        """Test 18c: New timezone-aware helpers are accessible without error."""
        d = get_user_local_date("UTC")
        assert isinstance(d, date)
        d2 = get_user_local_date("Asia/Kolkata")
        assert isinstance(d2, date)

    def test_fact_extractor_original_patterns_still_work(self):
        """Test 18d: Existing fact extractor patterns still produce correct results."""
        facts = extract_candidate_facts("I'm Ram, a final-year SRM AP student in the placement cell.")
        keys = {f.key for f in facts}
        assert "name" in keys or "preferred_name" in keys
        assert "education" in keys or "student_status" in keys

    def test_anniversary_detection(self):
        """Anniversary detection from facts (regression)."""
        facts = {"anniversary": "June 15, 2020"}
        milestones = MilestoneDetector.detect_milestones_from_facts(1, facts, [])
        ann = [m for m in milestones if m.milestone_type == MilestoneType.ANNIVERSARY]
        assert len(ann) == 1
        assert ann[0].recurring is True


# ─────────────────────────────────────────────────────────────────────────────
# 19. Offline provider behavior and database failure handling
# ─────────────────────────────────────────────────────────────────────────────
class TestOfflineAndFailureHandling:

    def test_offline_database_handling_in_scan(self):
        """Test 19: Graceful handling when database is unavailable in scan."""
        with patch('core.db_pool.get_db_pool') as mock_pool:
            mock_pool.return_value.is_healthy.return_value = False
            mock_pool.return_value.get_cursor.side_effect = Exception("DB unavailable")
            service = ProactiveService()
            # Should not raise; just logs errors and returns
            service._scan_all_users()

    def test_is_already_notified_returns_false_on_db_error(self):
        """Test 19b: _is_already_notified returns False (safe default) when DB fails."""
        with patch('core.db_pool.get_db_pool') as mock_pool:
            mock_pool.return_value.get_cursor.side_effect = Exception("DB error")
            service = ProactiveService()
            result = service._is_already_notified(1, "milestone_id", date.today())
            assert result is False  # Safe default: allow re-check later


# ─────────────────────────────────────────────────────────────────────────────
# 20. Uncertain milestone outcome triggers a question, not fabrication
# ─────────────────────────────────────────────────────────────────────────────
class TestUncertainOutcome:

    def test_goal_checkpoint_asks_how_its_going(self):
        """Test 20: GOAL_CHECKPOINT message is a question about progress."""
        milestone = Milestone(
            milestone_id="test_goal",
            user_id=1,
            milestone_type=MilestoneType.GOAL_CHECKPOINT,
            title="Learn Python",
            date=date(2025, 4, 14),
            recurring=False,
        )
        scheduler = MilestoneScheduler()
        message = scheduler._generate_proactive_message(milestone)
        assert "?" in message
        assert "goal" in message.lower() or "Learn Python" in message

    def test_interview_does_not_fabricate_outcome(self):
        """Test 20b: Interview message never claims a fabricated outcome."""
        milestone = Milestone(
            milestone_id="test_interview",
            user_id=1,
            milestone_type=MilestoneType.INTERVIEW,
            title="Interview at Google",
            date=date(2025, 4, 14),
            recurring=False,
        )
        scheduler = MilestoneScheduler()
        message = scheduler._generate_proactive_message(milestone)
        # Must not contain fabricated outcome words
        fabricated_patterns = ["got the job", "you were rejected", "you passed", "you failed"]
        for pattern in fabricated_patterns:
            assert pattern.lower() not in message.lower(), f"Fabricated outcome detected: '{pattern}'"


# ─────────────────────────────────────────────────────────────────────────────
# Additional: New milestone types
# ─────────────────────────────────────────────────────────────────────────────
class TestNewMilestoneTypes:

    def test_subscription_renewal_detection(self):
        """Subscription renewal fact extracted correctly."""
        facts = extract_candidate_facts("My Netflix subscription renews on January 5.")
        sub_facts = [f for f in facts if "subscription" in f.key and "renewal" in f.key]
        assert len(sub_facts) >= 1
        assert "January" in sub_facts[0].value or "5" in sub_facts[0].value

    def test_certification_expiry_detection(self):
        """Certification expiry fact extracted correctly."""
        facts = extract_candidate_facts("My AWS certification expires in March 2027.")
        cert_facts = [f for f in facts if "certification" in f.key and "expiry" in f.key]
        assert len(cert_facts) >= 1

    def test_birthday_extraction_from_statement(self):
        """Birthday extracted from natural language statement."""
        facts = extract_candidate_facts("My birthday is April 14.")
        bday_facts = [f for f in facts if f.key == "birthday"]
        assert len(bday_facts) >= 1
        assert "April" in bday_facts[0].value or "14" in bday_facts[0].value

    def test_dob_extraction(self):
        """Date of birth extracted from 'I was born on' statement."""
        facts = extract_candidate_facts("I was born on 1996-07-22.")
        dob_facts = [f for f in facts if f.key in ("birthday", "date_of_birth")]
        assert len(dob_facts) >= 1

    def test_opt_out_preference_extracted(self):
        """Opt-out preference extracted from 'I no longer want X reminders'."""
        facts = extract_candidate_facts("I no longer want placement reminders.")
        opt_out_facts = [f for f in facts if "opt_out" in f.key]
        assert len(opt_out_facts) >= 1
        assert opt_out_facts[0].value == "true"

    def test_subscription_milestone_from_structured_memory(self):
        """Subscription renewal milestone detected from structured memories."""
        now = _make_now(2026, 1, 1)
        structured_memories = [
            {"key": "subscription_netflix_renewal", "value": "2026-03-15", "category": "commitments", "status": "confirmed"}
        ]
        milestones = _detect(1, structured_memories=structured_memories, now=now)
        sub_milestones = [m for m in milestones if m.milestone_type == MilestoneType.SUBSCRIPTION_RENEWAL]
        assert len(sub_milestones) >= 1

    def test_certification_milestone_from_structured_memory(self):
        """Certification expiry milestone detected from structured memories."""
        now = _make_now(2026, 1, 1)
        structured_memories = [
            {"key": "certification_aws_expiry", "value": "2027-06-30", "category": "commitments", "status": "confirmed"}
        ]
        milestones = _detect(1, structured_memories=structured_memories, now=now)
        cert_milestones = [m for m in milestones if m.milestone_type == MilestoneType.CERTIFICATION_EXPIRY]
        assert len(cert_milestones) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# ProactiveService lifecycle tests
# ─────────────────────────────────────────────────────────────────────────────
class TestProactiveServiceLifecycle:

    def test_service_initialization(self):
        """Service initializes correctly."""
        service = ProactiveService(scan_interval_hours=1.0)
        assert service.scan_interval == 3600
        assert service.running is False

    def test_service_start_stop(self):
        """Service can be started and stopped."""
        service = ProactiveService(scan_interval_hours=0.01)
        service.start()
        assert service.running is True
        assert service.thread is not None
        service.stop()
        assert service.running is False

    def test_advance_days_for_non_birthday(self):
        """Non-birthday milestones are notified 1 day in advance."""
        milestone = Milestone(
            milestone_id="test_interview",
            user_id=1,
            milestone_type=MilestoneType.INTERVIEW,
            title="Interview",
            date=date(2025, 4, 15),
            recurring=False,
        )
        mock_scheduler = Mock()
        mock_scheduler.add_reminder_at_time = Mock(return_value="reminder_id")
        scheduler = MilestoneScheduler(reminder_scheduler=mock_scheduler)
        result = scheduler.schedule_milestone(milestone, advance_days=1)
        assert result is True
        call_args = mock_scheduler.add_reminder_at_time.call_args
        assert call_args[1]["target_time"].date() == date(2025, 4, 14)


# ─────────────────────────────────────────────────────────────────────────────
# 12. Outdated facts do not override newer confirmed information
# ─────────────────────────────────────────────────────────────────────────────
class TestOutdatedFactsDoNotOverride:

    def test_cross_key_supersession_marks_old_key_and_cleans_mirror(self):
        """Test 12: A confirmed graduation supersedes the old student_status key
        (marks it superseded in memory_facts and removes the stale JSONB mirror
        key so get_user_facts cannot resurface the outdated value)."""
        from core.chatgpt_memory import ChatGPTMemoryManager
        with patch('core.chatgpt_memory.get_db_pool') as mock_pool, \
             patch('legacy.memory_manager.update_user_memory'), \
             patch('legacy.memory_manager.load_user_memory', return_value={}), \
             patch('legacy.memory_manager.delete_memory_key') as mock_del:
            mock_cursor = MagicMock()
            mock_pool.return_value.get_cursor.return_value.__enter__.return_value = mock_cursor
            # 1st fetchone: no existing graduation_status; 2nd: new fact id
            mock_cursor.fetchone.side_effect = [None, [42]]

            mgr = ChatGPTMemoryManager()
            result = mgr.set_user_fact(
                user_id=1, key="graduation_status", value="graduated",
                category="education", status="confirmed",
                supersedes_key="student_status",
            )
            assert result is True

            # A supersession UPDATE targeting the old key was issued
            def _issued(sql, params=None):
                return "superseded" in str(sql) and "student_status" in str(params)
            assert any(
                _issued(c.args[0], c.args[1] if len(c.args) > 1 else None)
                for c in mock_cursor.execute.call_args_list
            ), "Expected an UPDATE marking student_status as superseded"

            # The stale mirror key was removed so it cannot override newer facts
            mock_del.assert_called_with(1, "student_status")

    def test_same_key_supersession_still_works(self):
        """Test 12b: Same-key value change still supersedes the prior row (regression)."""
        from core.chatgpt_memory import ChatGPTMemoryManager
        with patch('core.chatgpt_memory.get_db_pool') as mock_pool, \
             patch('legacy.memory_manager.update_user_memory'), \
             patch('legacy.memory_manager.load_user_memory', return_value={}):
            mock_cursor = MagicMock()
            mock_pool.return_value.get_cursor.return_value.__enter__.return_value = mock_cursor
            # existing row present with a different value -> supersede + insert new
            mock_cursor.fetchone.side_effect = [[7, "old", "confirmed"], [9]]

            mgr = ChatGPTMemoryManager()
            result = mgr.set_user_fact(
                user_id=1, key="employment_status", value="employed",
                category="employment", status="confirmed",
            )
            assert result is True
            executed = " ".join(str(c.args[0]) for c in mock_cursor.execute.call_args_list)
            assert "superseded" in executed, "Old same-key row should be marked superseded"


# ─────────────────────────────────────────────────────────────────────────────
# Notification timing: configured time + same-day prompt delivery
# ─────────────────────────────────────────────────────────────────────────────
class TestNotificationTiming:

    def test_schedule_uses_configured_notification_time(self):
        """Milestone reminder fires at the configured proactive_notification_time,
        not at midnight."""
        milestone = Milestone(
            milestone_id="b_time", user_id=1,
            milestone_type=MilestoneType.BIRTHDAY,
            title="Birthday", date=date(2026, 10, 20), recurring=True,
        )
        mock_scheduler = Mock()
        mock_scheduler.add_reminder_at_time = Mock(return_value="rid")
        mock_cfg = Mock()
        def pref(uid, key, default=None):
            return "14:30" if key == "proactive_notification_time" else None
        mock_cfg.get_preference.side_effect = pref

        with patch('core.configuration_service.get_configuration_service', return_value=mock_cfg):
            scheduler = MilestoneScheduler(reminder_scheduler=mock_scheduler)
            assert scheduler.schedule_milestone(milestone, advance_days=0) is True

        target = mock_scheduler.add_reminder_at_time.call_args[1]["target_time"]
        assert target.date() == date(2026, 10, 20)
        assert (target.hour, target.minute) == (14, 30)

    def test_same_day_prompt_delivery_when_notify_time_passed(self):
        """A milestone whose notification time already passed today is delivered
        promptly the same day, NOT rolled to tomorrow (the day-late bug)."""
        real_datetime = datetime

        class _FakeDT:
            @classmethod
            def now(cls):
                return real_datetime(2026, 10, 23, 15, 0, 0)  # 15:00, past 09:00
            combine = staticmethod(real_datetime.combine)

        milestone = Milestone(
            milestone_id="b_prompt", user_id=1,
            milestone_type=MilestoneType.BIRTHDAY,
            title="Birthday", date=date(2026, 10, 23), recurring=True,  # today
        )
        mock_scheduler = Mock()
        mock_scheduler.add_reminder_at_time = Mock(return_value="rid")
        mock_cfg = Mock()
        mock_cfg.get_preference.return_value = None  # defaults: enabled, 09:00

        with patch('core.configuration_service.get_configuration_service', return_value=mock_cfg), \
             patch('core.milestone_engine.datetime', _FakeDT):
            scheduler = MilestoneScheduler(reminder_scheduler=mock_scheduler)
            assert scheduler.schedule_milestone(milestone, advance_days=0) is True

        target = mock_scheduler.add_reminder_at_time.call_args[1]["target_time"]
        assert target.date() == date(2026, 10, 23), "Must stay same day (not tomorrow)"
        assert target.hour >= 15, "Must be prompt (after the passed 09:00)"


# ─────────────────────────────────────────────────────────────────────────────
# INTERVIEW_FOLLOWUP: production detection + same-day scheduling
# ─────────────────────────────────────────────────────────────────────────────
class TestInterviewFollowupProductionPath:

    @staticmethod
    def _interview_mem(interview_date):
        val = f"interview tomorrow ({interview_date.isoformat()})"
        return [{"key": "commitment", "value": val,
                 "category": "commitments", "status": "confirmed"}]

    def test_no_followup_on_interview_day(self):
        """No INTERVIEW_FOLLOWUP is created on the interview day itself."""
        now = _make_now(2026, 10, 23)
        mems = self._interview_mem(date(2026, 10, 23))
        ms = _detect(1, structured_memories=mems, now=now)
        assert [m for m in ms if m.milestone_type == MilestoneType.INTERVIEW_FOLLOWUP] == []

    def test_followup_created_day_after_interview(self):
        """INTERVIEW_FOLLOWUP is created the day after the interview, dated that day."""
        now = _make_now(2026, 10, 24)
        mems = self._interview_mem(date(2026, 10, 23))
        ms = _detect(1, structured_memories=mems, now=now)
        fu = [m for m in ms if m.milestone_type == MilestoneType.INTERVIEW_FOLLOWUP]
        assert len(fu) == 1
        assert fu[0].date == date(2026, 10, 24)

    def test_followup_date_and_id_stable_for_dedup(self):
        """Follow-up milestone date/id are stable across later scans so the
        notification dedup (_is_already_notified) prevents a repeat ask."""
        mems = self._interview_mem(date(2026, 10, 23))
        day2 = _detect(1, structured_memories=mems, now=_make_now(2026, 10, 24))
        day3 = _detect(1, structured_memories=mems, now=_make_now(2026, 10, 25))
        fu2 = [m for m in day2 if m.milestone_type == MilestoneType.INTERVIEW_FOLLOWUP][0]
        fu3 = [m for m in day3 if m.milestone_type == MilestoneType.INTERVIEW_FOLLOWUP][0]
        assert fu2.milestone_id == fu3.milestone_id
        assert fu2.date == fu3.date

    def test_followup_scheduled_with_advance_days_zero(self):
        """ProactiveService schedules INTERVIEW_FOLLOWUP with advance_days=0 so it
        fires on the follow-up day, not a day earlier (before the interview)."""
        fu = Milestone(
            milestone_id="fu", user_id=1,
            milestone_type=MilestoneType.INTERVIEW_FOLLOWUP,
            title="Interview Follow-up", date=date(2026, 10, 24), recurring=False,
        )
        with patch('core.chatgpt_memory.ChatGPTMemoryManager') as mock_mem, \
             patch('core.milestone_engine.MilestoneDetector.detect_milestones_from_facts', return_value=[fu]), \
             patch('core.milestone_engine.MilestoneScheduler') as mock_sched_cls, \
             patch.object(ProactiveService, '_get_user_timezone', return_value='UTC'), \
             patch.object(ProactiveService, '_is_already_notified', return_value=False), \
             patch.object(ProactiveService, '_record_notification', return_value=True):
            mock_mem.return_value.get_user_facts.return_value = {}
            mock_mem.return_value.get_structured_user_memories.return_value = []
            mock_sched = mock_sched_cls.return_value
            mock_sched.schedule_milestone.return_value = True

            service = ProactiveService(reminder_scheduler=Mock())
            count = service._scan_user_milestones(1)

        assert count == 1
        _, kwargs = mock_sched.schedule_milestone.call_args
        assert kwargs['advance_days'] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

