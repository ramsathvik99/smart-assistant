"""
Proactive Personal Assistant Service

Background service that periodically scans user facts for milestones,
detects upcoming events, and schedules proactive reminders.

Design:
- Runs in a background thread
- Scans all users periodically (e.g., every 6 hours)
- Detects milestones from facts
- Schedules reminders using existing reminder_scheduler
- Respects user preferences and quiet hours
- Idempotent and safe on restart
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ProactiveService:
    """
    Background service for proactive personal assistant functionality.
    """

    def __init__(
        self,
        scan_interval_hours: float = 6.0,
        reminder_scheduler=None
    ):
        """
        Initialize the proactive service.

        Args:
            scan_interval_hours: How often to scan for milestones (default: 6 hours)
            reminder_scheduler: Instance of ReminderScheduler for delivery
        """
        self.scan_interval = scan_interval_hours * 3600  # Convert to seconds
        self.reminder_scheduler = reminder_scheduler
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self):
        """Start the background proactive service."""
        if self.running:
            logger.warning("[PROACTIVE] Service already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_service, daemon=True, name="proactive-service")
        self.thread.start()
        logger.info("[PROACTIVE] Background service started")

    def stop(self):
        """Stop the background proactive service."""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
        logger.info("[PROACTIVE] Background service stopped")

    def _run_service(self):
        """Main service loop."""
        logger.info("[PROACTIVE] Service loop started")

        # Initial scan on startup
        self._scan_all_users()

        while self.running:
            try:
                # Sleep for the scan interval
                time.sleep(self.scan_interval)

                # Perform periodic scan
                if self.running:
                    self._scan_all_users()

            except Exception as e:
                logger.error(f"[PROACTIVE] Service loop error: {e}", exc_info=True)
                time.sleep(60)  # Wait 1 minute before retry

        logger.info("[PROACTIVE] Service loop stopped")

    def _scan_all_users(self):
        """Scan all users for milestones and schedule proactive reminders."""
        try:
            logger.info("[PROACTIVE] Starting milestone scan for all users")

            # Get all user IDs
            user_ids = self._get_all_user_ids()
            if not user_ids:
                logger.debug("[PROACTIVE] No users found")
                return

            milestones_scheduled = 0

            for user_id in user_ids:
                try:
                    count = self._scan_user_milestones(user_id)
                    milestones_scheduled += count
                except Exception as e:
                    logger.error(f"[PROACTIVE] Error scanning user {user_id}: {e}")

            logger.info(f"[PROACTIVE] Scan complete: {milestones_scheduled} milestones scheduled")

        except Exception as e:
            logger.error(f"[PROACTIVE] Error in scan_all_users: {e}", exc_info=True)

    def _get_all_user_ids(self) -> list:
        """Get all user IDs from the database."""
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            with pool.get_cursor() as cur:
                cur.execute("SELECT id FROM users;")
                return [row[0] for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"[PROACTIVE] Error getting user IDs: {e}")
            return []

    def _scan_user_milestones(self, user_id: int) -> int:
        """
        Scan a single user for milestones and schedule reminders.
        Returns the number of milestones scheduled.
        """
        try:
            # Get user's timezone
            timezone_str = self._get_user_timezone(user_id)

            # Load user facts
            from core.chatgpt_memory import ChatGPTMemoryManager
            memory_mgr = ChatGPTMemoryManager()
            facts = memory_mgr.get_user_facts(user_id)
            structured_memories = memory_mgr.get_structured_user_memories(user_id)

            # Detect milestones
            from core.milestone_engine import MilestoneDetector, MilestoneScheduler
            milestones = MilestoneDetector.detect_milestones_from_facts(
                user_id=user_id,
                facts=facts,
                structured_memories=structured_memories,
                timezone_str=timezone_str
            )

            if not milestones:
                logger.debug(f"[PROACTIVE] No milestones detected for user {user_id}")
                return 0

            # Get milestone scheduler
            milestone_scheduler = MilestoneScheduler(self.reminder_scheduler)

            # Schedule each milestone
            scheduled_count = 0
            for milestone in milestones:
                # Check if already notified for this occurrence
                if self._is_already_notified(user_id, milestone.milestone_id, milestone.date):
                    logger.debug(f"[PROACTIVE] Milestone {milestone.milestone_id} already notified for {milestone.date}")
                    continue

                # Schedule the milestone
                # For birthdays, notify on the day (advance_days=0)
                # For other events, notify 1 day in advance
                advance_days = 0 if milestone.milestone_type.value == "birthday" else 1

                if milestone_scheduler.schedule_milestone(
                    milestone=milestone,
                    advance_days=advance_days,
                    user_timezone=timezone_str
                ):
                    # Record notification
                    self._record_notification(user_id, milestone)
                    scheduled_count += 1

            logger.info(f"[PROACTIVE] Scheduled {scheduled_count} milestones for user {user_id}")
            return scheduled_count

        except Exception as e:
            logger.error(f"[PROACTIVE] Error scanning user {user_id}: {e}", exc_info=True)
            return 0

    def _get_user_timezone(self, user_id: int) -> str:
        """Get user's timezone preference."""
        try:
            from core.configuration_service import get_configuration_service
            cfg = get_configuration_service()
            tz = cfg.get_preference(user_id, "timezone")
            return tz if tz else "UTC"
        except Exception:
            return "UTC"

    def _is_already_notified(self, user_id: int, milestone_id: str, notification_date) -> bool:
        """Check if a milestone has already been notified for a specific date."""
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            with pool.get_cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM milestone_notifications
                    WHERE user_id = %s AND milestone_id = %s AND notification_date = %s;
                """, (user_id, milestone_id, notification_date))
                count = cur.fetchone()[0]
                return count > 0
        except Exception as e:
            logger.debug(f"[PROACTIVE] Error checking notification status: {e}")
            return False  # Assume not notified on error

    def _record_notification(self, user_id: int, milestone) -> bool:
        """Record that a milestone notification has been scheduled."""
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            with pool.get_cursor() as cur:
                cur.execute("""
                    INSERT INTO milestone_notifications
                    (user_id, milestone_id, milestone_type, notification_date, message)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, milestone_id, notification_date) DO NOTHING;
                """, (
                    user_id,
                    milestone.milestone_id,
                    milestone.milestone_type.value,
                    milestone.date,
                    milestone.title
                ))
            return True
        except Exception as e:
            logger.error(f"[PROACTIVE] Error recording notification: {e}")
            return False


# Global instance
_proactive_service: Optional[ProactiveService] = None
_proactive_lock = threading.Lock()


def get_proactive_service(reminder_scheduler=None) -> ProactiveService:
    """Get or create the global proactive service instance."""
    global _proactive_service
    with _proactive_lock:
        if _proactive_service is None:
            _proactive_service = ProactiveService(reminder_scheduler=reminder_scheduler)
        return _proactive_service


def start_proactive_service(reminder_scheduler=None):
    """Start the proactive service if not already running."""
    service = get_proactive_service(reminder_scheduler)
    if not service.running:
        service.start()


def stop_proactive_service():
    """Stop the proactive service."""
    global _proactive_service
    with _proactive_lock:
        if _proactive_service:
            _proactive_service.stop()
