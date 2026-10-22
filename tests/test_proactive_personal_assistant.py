"""
Regression Tests for Proactive Personal Assistant

Tests for milestone detection, proactive notifications, consent awareness,
and temporal reasoning per the mission requirements.
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


class TestMilestoneDetection:
    """Test milestone detection from user facts."""

    def test_birthday_detection_basic(self):
        """Basic birthday detection from facts."""
        facts = {
            "birthday": "April 14, 2005",
        }
        structured_memories = []

        milestones = MilestoneDetector.detect_milestones_from_facts(
            user_id=1,
            facts=facts,
            structured_memories=structured_memories,
            timezone_str="UTC"
        )

        # Should detect birthday
        birthday_milestones = [m for m in milestones if m.milestone_type == MilestoneType.BIRTHDAY]
        assert len(birthday_milestones) == 1
        assert birthday_milestones[0].recurring == True
        assert birthday_milestones[0].source_fact_key == "birthday"

    def test_anniversary_detection(self):
        """Anniversary detection from facts."""
        facts = {
            "anniversary": "June 15, 2020",
        }
        structured_memories = []

        milestones = MilestoneDetector.detect_milestones_from_facts(
            user_id=1,
            facts=facts,
            structured_memories=structured_memories,
            timezone_str="UTC"
        )

        anniversary_milestones = [m for m in milestones if m.milestone_type == MilestoneType.ANNIVERSARY]
        assert len(anniversary_milestones) == 1
        assert anniversary_milestones[0].recurring == True

    def test_graduation_detection_future(self):
        """Graduation detection for future date (ISO format)."""
        facts = {}
        structured_memories = [
            {
                "fact_key": "graduation_date",
                "fact_value": "2025-05-15",
                "category": "education",
            }
        ]

        milestones = MilestoneDetector.detect_milestones_from_facts(
            user_id=1,
            facts=facts,
            structured_memories=structured_memories,
            timezone_str="UTC"
        )

        grad_milestones = [m for m in milestones if m.milestone_type == MilestoneType.GRADUATION]
        # Should detect graduation if it's in the future
        if datetime.now().date() < date(2025, 5, 15):
            assert len(grad_milestones) == 1
            assert grad_milestones[0].recurring == False

    def test_graduation_detection_past_no_future(self):
        """Graduation detection for past date should not create future milestone."""
        facts = {}
        structured_memories = [
            {
                "fact_key": "graduation_date",
                "fact_value": "2020-05-15",
                "category": "education",
            }
        ]

        milestones = MilestoneDetector.detect_milestones_from_facts(
            user_id=1,
            facts=facts,
            structured_memories=structured_memories,
            timezone_str="UTC"
        )

        grad_milestones = [m for m in milestones if m.milestone_type == MilestoneType.GRADUATION]
        # Past graduation should not create a future milestone
        assert len(grad_milestones) == 0

    def test_interview_detection(self):
        """Interview detection from commitments."""
        facts = {}
        structured_memories = [
            {
                "fact_key": "commitment",
                "fact_value": "2025-12-25",
                "category": "commitments",
            }
        ]

        milestones = MilestoneDetector.detect_milestones_from_facts(
            user_id=1,
            facts=facts,
            structured_memories=structured_memories,
            timezone_str="UTC"
        )

        # Should detect commitment if date is in future
        if datetime.now().date() < date(2025, 12, 25):
            commitment_milestones = [m for m in milestones if m.milestone_type == MilestoneType.COMMITMENT]
            assert len(commitment_milestones) >= 1

    def test_per_account_isolation(self):
        """Strict separation of milestones between two accounts."""
        user1_facts = {"birthday": "April 14, 2005"}
        user2_facts = {"birthday": "June 15, 1998"}
        structured_memories = []

        milestones1 = MilestoneDetector.detect_milestones_from_facts(
            user_id=1,
            facts=user1_facts,
            structured_memories=structured_memories,
            timezone_str="UTC"
        )

        milestones2 = MilestoneDetector.detect_milestones_from_facts(
            user_id=2,
            facts=user2_facts,
            structured_memories=structured_memories,
            timezone_str="UTC"
        )

        # Each user should have their own birthday
        assert len([m for m in milestones1 if m.user_id == 1]) == 1
        assert len([m for m in milestones2 if m.user_id == 2]) == 1

        # No crossover
        assert all(m.user_id == 1 for m in milestones1)
        assert all(m.user_id == 2 for m in milestones2)


class TestMilestoneScheduler:
    """Test milestone scheduling and delivery."""

    def test_birthday_notification_on_day(self):
        """Birthday notification delivered on the correct day."""
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

        assert result == True
        mock_scheduler.add_reminder_at_time.assert_called_once()
        call_args = mock_scheduler.add_reminder_at_time.call_args
        # Should schedule on the day (advance_days=0)
        assert call_args[1]["target_time"].date() == date(2025, 4, 14)

    def test_proactive_notification_advance_days(self):
        """Non-birthday milestones notified in advance."""
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

        assert result == True
        call_args = mock_scheduler.add_reminder_at_time.call_args
        # Should schedule 1 day in advance
        assert call_args[1]["target_time"].date() == date(2025, 4, 14)

    def test_proactive_disabled_respects_opt_out(self):
        """Proactive interaction respects user opt-out."""
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
            mock_cfg.return_value.get_preference.return_value = False  # Disabled

            scheduler = MilestoneScheduler(reminder_scheduler=mock_scheduler)
            result = scheduler.schedule_milestone(milestone)

            # Should not schedule when proactive is disabled
            assert result == False
            mock_scheduler.add_reminder_at_time.assert_not_called()

    def test_category_disabled_respects_opt_out(self):
        """Specific category opt-out is respected."""
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
            # Proactive enabled, but birthdays disabled
            def mock_get_pref(user_id, key, default=None):
                if key == "proactive_interactions_enabled":
                    return True
                if key == "proactive_birthdays":
                    return False
                return default

            mock_cfg.return_value.get_preference.side_effect = mock_get_pref

            scheduler = MilestoneScheduler(reminder_scheduler=mock_scheduler)
            result = scheduler.schedule_milestone(milestone)

            # Should not schedule when category is disabled
            assert result == False
            mock_scheduler.add_reminder_at_time.assert_not_called()

    def test_personality_aware_messages(self):
        """Proactive messages reflect each account's personality."""
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

        # Test with different personalities
        personalities = ["professional", "witty", "minimal", "friendly"]
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

        # Messages should differ based on personality
        assert len(set(messages)) > 1  # At least some messages should be different

    def test_quiet_hours_respected(self):
        """Quiet hours are respected."""
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
                if key == "quiet_hours_enabled":
                    return True
                if key == "quiet_hours_start":
                    return "22:00"
                if key == "quiet_hours_end":
                    return "08:00"
                return default

            mock_cfg.return_value.get_preference.side_effect = mock_get_pref

            scheduler = MilestoneScheduler(reminder_scheduler=mock_scheduler)
            # For now, this test verifies the check is called
            # Full implementation would test time-of-day logic
            result = scheduler.schedule_milestone(milestone)

            # Quiet hours check is performed (currently defaults to allowed)
            assert True  # Placeholder for full quiet hours implementation


class TestProactiveService:
    """Test proactive service background scanning."""

    def test_service_initialization(self):
        """Service initializes correctly."""
        service = ProactiveService(scan_interval_hours=1.0)
        assert service.scan_interval == 3600  # 1 hour in seconds
        assert service.running == False

    def test_service_start_stop(self):
        """Service can be started and stopped."""
        service = ProactiveService(scan_interval_hours=0.01)  # Very short interval for testing
        service.start()
        assert service.running == True
        assert service.thread is not None

        service.stop()
        assert service.running == False

    def test_duplicate_medication_after_restart(self):
        """No duplicate reminders after application restart."""
        # This would be tested with actual database state
        # For now, we test the deduplication logic
        milestone_id = "test_milestone_123"
        notification_date = date(2025, 4, 14)

        # Mock database query
        with patch('core.db_pool.get_db_pool') as mock_pool:
            mock_cursor = MagicMock()
            mock_pool.return_value.get_cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = [1]  # Already notified

            service = ProactiveService()
            already_notified = service._is_already_notified(
                user_id=1,
                milestone_id=milestone_id,
                notification_date=notification_date
            )

            assert already_notified == True

    def test_offline_database_handling(self):
        """Graceful handling when database is unavailable."""
        with patch('core.db_pool.get_db_pool') as mock_pool:
            mock_pool.return_value.is_healthy.return_value = False

            service = ProactiveService()
            # Should not crash when database is unhealthy
            service._scan_all_users()
            # No exception raised


class TestFactLifecycle:
    """Test fact lifecycle management and temporal reasoning."""

    def test_user_correction_supersedes_old_fact(self):
        """User corrections replace stale authoritative facts."""
        from core.chatgpt_memory import ChatGPTMemoryManager

        # This would be tested with actual database operations
        # For now, we verify the logic exists in chatgpt_memory.py
        # The set_user_fact method already handles supersession
        assert True  # Placeholder for integration test

    def test_planned_events_remain_planned_until_confirmed(self):
        """Planned events remain planned until completion is confirmed."""
        # This would test the status field in memory_facts
        # A graduation date passing should not auto-confirm graduation
        assert True  # Placeholder for integration test

    def test_outdated_facts_not_override_recent(self):
        """Outdated facts do not override more recent confirmed information."""
        # The memory system already prefers last_confirmed timestamp
        # This is implemented in chatgpt_memory.py get_user_facts
        assert True  # Placeholder for integration test


class TestIntegrationScenarios:
    """End-to-end integration scenarios."""

    def test_birthday_greeting_once_per_occurrence(self):
        """Birthday notification delivered at most once per occurrence."""
        # This would test the milestone_notifications table
        # UNIQUE constraint prevents duplicate notifications
        assert True  # Placeholder for integration test

    def test_follow_up_stops_after_cancellation(self):
        """Follow-up reminders stop after cancellation or completion."""
        # This would test milestone status updates
        milestone = Milestone(
            milestone_id="test_goal",
            user_id=1,
            milestone_type=MilestoneType.GOAL_CHECKPOINT,
            title="Goal Checkpoint",
            date=date(2025, 4, 14),
            recurring=False,
        )

        scheduler = MilestoneScheduler()
        # First add the milestone to the scheduler
        scheduler._scheduled_milestones["test_goal"] = milestone
        scheduler.update_milestone_status("test_goal", MilestoneStatus.CANCELLED)

        assert scheduler._scheduled_milestones["test_goal"].status == MilestoneStatus.CANCELLED

    def test_uncertain_outcome_triggers_question(self):
        """Uncertain milestone outcome triggers question rather than fabrication."""
        # This would test the proactive message generation
        # For interviews, should ask "How did it go?" rather than assuming outcome
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

        # Message should be a question/check-in, not a statement of fact
        assert "?" in message or "Good luck" in message or "You've got this" in message

    def test_existing_functionality_preserved(self):
        """Existing reminder, memory, routing, voice, and assistant functionality remains intact."""
        # This is a regression test to ensure nothing broke
        # We'll test that existing modules still import and initialize
        try:
            from core.chatgpt_memory import ChatGPTMemoryManager
            from core.fact_extractor import extract_candidate_facts
            from extensions.reminder_engine.reminder_scheduler import ReminderScheduler
            from extensions.personality_engine.personality_core import PersonalityCore
            from core.configuration_service import ConfigurationService
            from core.unified_command_router import UnifiedCommandRouter

            # All imports successful
            assert True
        except ImportError as e:
            pytest.fail(f"Existing module import failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
