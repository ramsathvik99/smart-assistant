"""
Reminder Scheduler Module
Thread-based background scheduler for Nova reminders with database integration.
"""

import time
import threading
import datetime
from typing import List, Dict, Callable, Optional
import uuid

class ReminderScheduler:
    """Background thread-based reminder scheduler for Nova Assistant."""
    
    def __init__(self, tts_callback: Optional[Callable] = None, sound_callback: Optional[Callable] = None, db_manager=None, user_id=None):
        """
        Initialize the reminder scheduler.
        
        Args:
            tts_callback: Function to call for TTS output (e.g., speak function)
            sound_callback: Function to call for sound alerts (optional)
            db_manager: DatabaseManager instance for persistence (optional)
            user_id: Current authenticated user ID (optional)
        """
        self.reminders: List[Dict] = []
        self.missed_reminders: List[Dict] = []
        self.running = False
        self.scheduler_thread: Optional[threading.Thread] = None
        self.tts_callback = tts_callback
        self.sound_callback = sound_callback
        self.db_manager = db_manager
        self.user_id = user_id
        self._lock = threading.Lock()
        
        # Start the background scheduler
        self.start()
    
    def start(self):
        """Start the background scheduler thread."""
        if not self.running:
            self.running = True
            self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
            self.scheduler_thread.start()
            print("[REMINDER ENGINE] Background scheduler started")
    
    def stop(self):
        """Stop the background scheduler thread."""
        self.running = False
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=2.0)
        print("[REMINDER ENGINE] Background scheduler stopped")
    
    def add_reminder(
        self,
        text: str,
        delay_seconds: float = 0,
        reminder_id: Optional[str] = None,
        user_id: Optional[int] = None,
        trigger_time: Optional[float] = None,
        target_time: Optional[datetime.datetime] = None,
        recurrence: Optional[Dict] = None
    ) -> str:
        """
        Add a new reminder to the scheduler.
        
        Args:
            text: The reminder text to speak
            delay_seconds: Delay in seconds from now (ignored if trigger_time or target_time is given)
            reminder_id: Optional custom ID (auto-generated if not provided)
            user_id: The user ID this reminder belongs to
            trigger_time: Optional exact POSIX timestamp for trigger
            target_time: Optional target datetime
            recurrence: Optional recurrence specification (e.g. {"frequency": "daily"})
            
        Returns:
            The reminder ID for tracking
        """
        has_custom_id = bool(reminder_id)
        if not reminder_id:
            reminder_id = str(uuid.uuid4())
        reminder_id = str(reminder_id)

        # Calculate exact trigger timestamp
        if trigger_time is not None:
            exact_trigger_time = float(trigger_time)
        elif target_time is not None:
            exact_trigger_time = target_time.timestamp()
        else:
            if delay_seconds <= 0:
                print(f"[REMINDER ENGINE] Rejecting non-positive delay ({delay_seconds}s) for '{text}'")
                return ""
            exact_trigger_time = time.time() + float(delay_seconds)

        # Effective delay for metadata
        calculated_delay = max(0.0, exact_trigger_time - time.time())
        
        with self._lock:
            # 1. Stable Reminder ID: If this ID is already in the scheduler, update it
            existing = next((r for r in self.reminders if str(r.get("id")) == reminder_id), None)
            if existing:
                existing["text"] = text
                existing["trigger_time"] = exact_trigger_time
                existing["target_time"] = target_time
                existing["delay_seconds"] = calculated_delay
                existing["user_id"] = user_id
                existing["triggered"] = False
                if recurrence:
                    existing["recurrence"] = recurrence
                trigger_datetime = datetime.datetime.fromtimestamp(exact_trigger_time)
                print(f"[REMINDER ENGINE] Updated existing scheduled reminder {reminder_id}: '{text}' at {trigger_datetime.strftime('%H:%M:%S')} for user {user_id}")
                return reminder_id

            # 2. Deduplication on un-ID'd inputs:
            # Only perform fuzzy text/time matching if caller did NOT supply a pre-assigned stable ID
            # (e.g. rapid double-tap from live user utterance before DB assignment).
            # Persisted records with distinct database IDs must NEVER be merged!
            if not has_custom_id:
                norm_text = text.strip().lower()
                duplicate = next(
                    (r for r in self.reminders 
                     if not r.get("triggered") 
                     and r.get("user_id") == user_id 
                     and r.get("text", "").strip().lower() == norm_text 
                     and abs(r.get("trigger_time", 0) - exact_trigger_time) < 1.0),
                    None
                )
                if duplicate:
                    print(f"[REMINDER ENGINE] Deduplicated reminder '{text}' for user {user_id}")
                    return duplicate["id"]

            self.reminders.append({
                "id": reminder_id,
                "text": text,
                "trigger_time": exact_trigger_time,
                "target_time": target_time,
                "delay_seconds": calculated_delay,
                "triggered": False,
                "created_at": time.time(),
                "user_id": user_id,
                "recurrence": recurrence
            })
        
        # Calculate human-readable time from exact timestamp
        trigger_datetime = datetime.datetime.fromtimestamp(exact_trigger_time)
        print(f"[REMINDER ENGINE] Scheduled: '{text}' at {trigger_datetime.strftime('%H:%M:%S')} for user {user_id}")
        
        return reminder_id
    
    def add_reminder_at_time(
        self,
        text: str,
        target_time: datetime.datetime,
        reminder_id: Optional[str] = None,
        user_id: Optional[int] = None,
        recurrence: Optional[Dict] = None
    ) -> str:
        """
        Add a reminder for a specific time, preserving exact timestamp semantics.
        
        Args:
            text: The reminder text to speak
            target_time: Specific datetime to trigger
            reminder_id: Optional custom ID
            user_id: The user ID this reminder belongs to
            recurrence: Optional recurrence rule dictionary
            
        Returns:
            The reminder ID for tracking
        """
        if not reminder_id:
            reminder_id = str(uuid.uuid4())
        
        now = datetime.datetime.now()
        if target_time <= now:
            # If time is in the past, schedule for tomorrow
            target_time = target_time + datetime.timedelta(days=1)
        
        exact_trigger_time = target_time.timestamp()
        delay_seconds = max(0.0, (target_time - now).total_seconds())
        return self.add_reminder(
            text=text,
            delay_seconds=delay_seconds,
            reminder_id=reminder_id,
            user_id=user_id,
            trigger_time=exact_trigger_time,
            target_time=target_time,
            recurrence=recurrence
        )
    
    def cancel_reminder(self, reminder_id: str) -> bool:
        """
        Cancel a pending reminder.
        
        Args:
            reminder_id: The ID of the reminder to cancel
            
        Returns:
            True if cancelled, False if not found
        """
        target_id_str = str(reminder_id)
        with self._lock:
            for i, reminder in enumerate(self.reminders):
                if str(reminder.get("id")) == target_id_str and not reminder.get("triggered"):
                    del self.reminders[i]
                    print(f"[REMINDER ENGINE] Cancelled reminder: {target_id_str}")
                    return True
        return False

    def reschedule_reminder(
        self,
        reminder_id: str,
        new_target_time: datetime.datetime,
        new_text: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> bool:
        """
        Reschedule a reminder to a new target time.
        Updates both database (if available) and the active scheduler job.
        Ensures the reminder will not fire at the old time.
        """
        target_id_str = str(reminder_id)
        eff_user_id = user_id if user_id is not None else self.user_id

        # 1. Update database if db_manager is available
        if self.db_manager and eff_user_id is not None:
            try:
                new_time_str = new_target_time.strftime("%Y-%m-%d %H:%M:%S")
                self.db_manager.update_reminder(eff_user_id, reminder_id, task_text=new_text, due_at=new_time_str)
                if hasattr(self.db_manager, "_get_cursor"):
                    with self.db_manager._get_cursor() as cur:
                        if cur:
                            cur.execute("UPDATE reminders SET is_notified = FALSE WHERE id = %s", (reminder_id,))
            except Exception as e:
                print(f"[REMINDER ENGINE] Database reschedule error: {e}")

        # 2. Update active in-memory scheduler job
        now = datetime.datetime.now()
        exact_trigger_time = new_target_time.timestamp()
        delay_seconds = max(0.0, (new_target_time - now).total_seconds())

        with self._lock:
            existing = next((r for r in self.reminders if str(r.get("id")) == target_id_str), None)
            if existing:
                if new_text:
                    existing["text"] = new_text
                existing["trigger_time"] = exact_trigger_time
                existing["target_time"] = new_target_time
                existing["delay_seconds"] = delay_seconds
                existing["triggered"] = False
                if eff_user_id is not None:
                    existing["user_id"] = eff_user_id
                print(f"[REMINDER ENGINE] Rescheduled existing reminder {target_id_str} to {new_target_time.strftime('%Y-%m-%d %H:%M:%S')}")
                return True
            else:
                text_to_use = new_text or f"Reminder {target_id_str}"
                self.reminders.append({
                    "id": target_id_str,
                    "text": text_to_use,
                    "trigger_time": exact_trigger_time,
                    "target_time": new_target_time,
                    "delay_seconds": delay_seconds,
                    "triggered": False,
                    "created_at": time.time(),
                    "user_id": eff_user_id
                })
                print(f"[REMINDER ENGINE] Registered rescheduled reminder {target_id_str} at {new_target_time.strftime('%Y-%m-%d %H:%M:%S')}")
                return True

    def edit_reminder(
        self,
        reminder_id: str,
        new_text: Optional[str] = None,
        new_target_time: Optional[datetime.datetime] = None,
        user_id: Optional[int] = None
    ) -> bool:
        """Edit text and/or target time for a reminder."""
        if new_target_time:
            return self.reschedule_reminder(reminder_id, new_target_time, new_text=new_text, user_id=user_id)
        
        target_id_str = str(reminder_id)
        eff_user_id = user_id if user_id is not None else self.user_id
        
        if self.db_manager and eff_user_id is not None and new_text:
            try:
                self.db_manager.update_reminder(eff_user_id, reminder_id, task_text=new_text)
            except Exception as e:
                print(f"[REMINDER ENGINE] Database edit error: {e}")

        with self._lock:
            existing = next((r for r in self.reminders if str(r.get("id")) == target_id_str), None)
            if existing:
                if new_text:
                    existing["text"] = new_text
                return True
        return False
    
    def get_pending_reminders(self) -> List[Dict]:
        """Get list of pending (not triggered) reminders."""
        with self._lock:
            return [r for r in self.reminders if not r["triggered"]]
    
    def get_all_reminders(self) -> List[Dict]:
        """Get list of all reminders (including triggered)."""
        with self._lock:
            return self.reminders.copy()

    def get_missed_reminders(self) -> List[Dict]:
        """Get list of reminders that were missed during downtime/offline period."""
        with self._lock:
            return self.missed_reminders.copy()

    def record_missed_reminder(self, reminder_data: Dict):
        """Record a missed reminder found on startup."""
        with self._lock:
            rem_id_str = str(reminder_data.get("id"))
            if not any(str(m.get("id")) == rem_id_str for m in self.missed_reminders):
                self.missed_reminders.append(reminder_data)
    
    def clear_completed_reminders(self):
        """Remove all completed reminders from memory."""
        with self._lock:
            before_count = len(self.reminders)
            self.reminders = [r for r in self.reminders if not r["triggered"]]
            removed = before_count - len(self.reminders)
            if removed > 0:
                print(f"[REMINDER ENGINE] Cleared {removed} completed reminders")
    
    def _run_scheduler(self):
        """Main scheduler loop running in background thread."""
        print("[REMINDER ENGINE] Scheduler thread started")
        
        while self.running:
            try:
                now = time.time()
                reminders_to_trigger = []
                
                # Find reminders that need to trigger
                with self._lock:
                    for reminder in self.reminders:
                        if not reminder["triggered"] and now >= reminder["trigger_time"]:
                            reminders_to_trigger.append(reminder)
                            reminder["triggered"] = True
                
                # Trigger reminders outside of lock to avoid blocking
                for reminder in reminders_to_trigger:
                    self._trigger_reminder(reminder)
                
                # Clean up old completed reminders periodically
                if int(now) % 300 == 0:  # Every 5 minutes
                    self._cleanup_old_reminders()
                
                # Sleep for short interval to check frequently
                time.sleep(1)
                
            except Exception as e:
                print(f"[REMINDER ENGINE] Scheduler error: {e}")
                time.sleep(5)  # Wait longer if error occurs
        
        print("[REMINDER ENGINE] Scheduler thread stopped")
    
    def _trigger_reminder(self, reminder: Dict):
        """Trigger a single reminder."""
        with self._lock:
            if reminder.get("_in_trigger"):
                return
            reminder["_in_trigger"] = True
            reminder["triggered"] = True

        try:
            reminder_text = reminder["text"]
            reminder_id = reminder["id"]
            reminder_user_id = reminder.get("user_id")

            # Preserve per-user isolation: do not deliver if active user does not match reminder user
            if self.user_id is not None and reminder_user_id is not None and reminder_user_id != self.user_id:
                print(f"[REMINDER ENGINE] Skipping reminder {reminder_id} for user {reminder_user_id} (active user is {self.user_id})")
                return
            
            print(f"[REMINDER ENGINE] Triggering reminder: '{reminder_text}'")
            
            # Mark as notified in database if db_manager is available (one-off reminders only)
            if self.db_manager and not reminder.get("recurrence"):
                try:
                    self.db_manager.mark_reminder_notified(reminder_id)
                    print(f"[REMINDER ENGINE] Marked reminder {reminder_id} as notified in database")
                except Exception as db_err:
                    print(f"[REMINDER ENGINE] Failed to mark reminder as notified: {db_err}")
            
            # Play sound alert if available
            if self.sound_callback:
                try:
                    self.sound_callback()
                except Exception as e:
                    print(f"[REMINDER ENGINE] Sound alert failed: {e}")
            
            # Speak reminder: use tts_callback if provided (e.g. for testing/simulation), otherwise TTS Coordinator
            if self.tts_callback:
                try:
                    self.tts_callback(f"Reminder: {reminder_text}")
                except Exception as e2:
                    print(f"[REMINDER ENGINE] Custom TTS callback failed: {e2}")
            else:
                try:
                    from extensions.system.tts_coordinator import speak, TTSPriority
                    speak(f"Reminder: {reminder_text}", priority=TTSPriority.REMINDER)
                except (ImportError, Exception) as e:
                    print(f"[REMINDER ENGINE] TTS Coordinator failed: {e}")
                    print(f"[REMINDER] {reminder_text}")

            # Recurrence Handling: calculate next occurrence and reschedule
            rec = reminder.get("recurrence")
            if rec:
                freq = (rec.get("frequency") or "").lower()
                base_time = reminder.get("target_time")
                if not base_time and reminder.get("trigger_time"):
                    base_time = datetime.datetime.fromtimestamp(reminder["trigger_time"])
                if not base_time:
                    base_time = datetime.datetime.now()

                if freq == "daily":
                    next_time = base_time + datetime.timedelta(days=1)
                elif freq == "weekly":
                    next_time = base_time + datetime.timedelta(weeks=1)
                elif freq == "monthly":
                    y = base_time.year + (base_time.month // 12)
                    m = (base_time.month % 12) + 1
                    d = min(base_time.day, 28)
                    next_time = base_time.replace(year=y, month=m, day=d)
                else:
                    next_time = base_time + datetime.timedelta(days=1)

                # Reschedule recurring reminder in database and memory
                if self.db_manager:
                    try:
                        u_id = reminder.get("user_id", self.user_id)
                        next_str = next_time.strftime("%Y-%m-%d %H:%M:%S")
                        self.db_manager.update_reminder(u_id, reminder_id, due_at=next_str)
                        if hasattr(self.db_manager, "_get_cursor"):
                            with self.db_manager._get_cursor() as cur:
                                if cur:
                                    cur.execute("UPDATE reminders SET is_notified = FALSE WHERE id = %s", (reminder_id,))
                    except Exception as rec_err:
                        print(f"[REMINDER ENGINE] Failed to update recurring reminder in database: {rec_err}")

                with self._lock:
                    reminder["trigger_time"] = next_time.timestamp()
                    reminder["target_time"] = next_time
                    reminder["triggered"] = False
                    reminder["delay_seconds"] = max(0.0, (next_time - datetime.datetime.now()).total_seconds())
                print(f"[REMINDER ENGINE] Rescheduled recurring reminder {reminder_id}: '{reminder_text}' for {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
                
        except Exception as e:
            print(f"[REMINDER ENGINE] Error triggering reminder: {e}")
        finally:
            with self._lock:
                reminder["_in_trigger"] = False
    
    def _cleanup_old_reminders(self):
        """Remove old completed reminders to prevent memory leaks."""
        try:
            with self._lock:
                now = time.time()
                # Remove reminders triggered more than 1 hour ago
                self.reminders = [
                    r for r in self.reminders 
                    if not r["triggered"] or (now - r["trigger_time"]) < 3600
                ]
        except Exception as e:
            print(f"[REMINDER ENGINE] Cleanup error: {e}")
    
    def get_status(self) -> Dict:
        """Get scheduler status and statistics."""
        with self._lock:
            pending = len([r for r in self.reminders if not r["triggered"]])
            completed = len([r for r in self.reminders if r["triggered"]])
            total = len(self.reminders)
            
            return {
                "running": self.running,
                "pending_reminders": pending,
                "completed_reminders": completed,
                "total_reminders": total,
                "scheduler_thread_alive": self.scheduler_thread.is_alive() if self.scheduler_thread else False
            }
    
    def reload_for_user(self, user_id):
        """Reload reminders for a specific user (call when user session changes)."""
        self.user_id = user_id
        if self.db_manager and user_id is not None:
            # Clear current in-memory reminders for isolation
            with self._lock:
                self.reminders = []
            
            # Load reminders for the new user
            _load_reminders_from_database(self, self.db_manager, user_id)
            print(f"[REMINDER ENGINE] Reloaded reminders for user {user_id}")


# Global scheduler instance
_global_scheduler: Optional[ReminderScheduler] = None

def get_scheduler() -> Optional[ReminderScheduler]:
    """Get the global reminder scheduler instance."""
    return _global_scheduler

def get_reminder_scheduler(db_manager=None, user_id=None) -> ReminderScheduler:
    """Convenience getter for the global reminder scheduler, initializing if needed."""
    global _global_scheduler
    if _global_scheduler is not None and _global_scheduler.running:
        return _global_scheduler
    return initialize_scheduler(db_manager=db_manager, user_id=user_id)


def initialize_scheduler(tts_callback: Optional[Callable] = None, sound_callback: Optional[Callable] = None, db_manager=None, user_id=None) -> ReminderScheduler:
    """
    Initialize the global reminder scheduler (Idempotent singleton).
    
    Args:
        tts_callback: Function to call for TTS output
        sound_callback: Function to call for sound alerts
        db_manager: DatabaseManager instance for persistence
        user_id: Current authenticated user ID
        
    Returns:
        The initialized scheduler instance
    """
    global _global_scheduler
    
    # If a scheduler is already running, reuse it and avoid stopping/restarting threads
    if _global_scheduler is not None and _global_scheduler.running:
        if tts_callback and not _global_scheduler.tts_callback:
            _global_scheduler.tts_callback = tts_callback
        if sound_callback and not _global_scheduler.sound_callback:
            _global_scheduler.sound_callback = sound_callback
        if db_manager and not _global_scheduler.db_manager:
            _global_scheduler.db_manager = db_manager
        if db_manager and user_id is not None:
            if _global_scheduler.user_id != user_id:
                _global_scheduler.reload_for_user(user_id)
            else:
                existing_user_reminders = [r for r in _global_scheduler.reminders if r.get("user_id") == user_id]
                if not existing_user_reminders:
                    _load_reminders_from_database(_global_scheduler, db_manager, user_id)
        return _global_scheduler

    # Stop existing scheduler if running but flagged
    if _global_scheduler:
        _global_scheduler.stop()
    
    _global_scheduler = ReminderScheduler(tts_callback, sound_callback, db_manager, user_id=user_id)
    
    # Load pending reminders from database if db_manager and user_id are available
    if db_manager and user_id is not None:
        _load_reminders_from_database(_global_scheduler, db_manager, user_id)
    
    return _global_scheduler

def _load_reminders_from_database(scheduler: ReminderScheduler, db_manager, user_id=None):
    """Load pending reminders from database into scheduler for specific user."""
    try:
        pending_reminders = db_manager.get_pending_reminders(user_id)
        now = datetime.datetime.now()
        scheduled_count = 0
        missed_count = 0
        
        for reminder in pending_reminders:
            due_raw = reminder.get("due_at")
            if not due_raw:
                continue
            if isinstance(due_raw, datetime.datetime):
                due_at = due_raw
            elif isinstance(due_raw, str):
                try:
                    due_at = datetime.datetime.strptime(due_raw, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    due_at = datetime.datetime.fromisoformat(due_raw)
            else:
                continue

            reminder_user_id = reminder.get("user_id", user_id)
            rem_id_str = str(reminder["id"])

            # Check recurrence pattern from task_text if not explicitly in reminder dict
            rec = reminder.get("recurrence")
            if not rec:
                from extensions.reminder_engine.enhanced_reminder_handler import EnhancedReminderHandler
                h = EnhancedReminderHandler()
                rec = h._parse_recurrence(reminder.get("task_text", ""))
            
            # Future reminders: register in scheduler
            if due_at > now:
                delay_seconds = max(0.0, (due_at - now).total_seconds())
                exact_trigger_time = due_at.timestamp()
                with scheduler._lock:
                    already_present = any(
                        str(r.get("id")) == rem_id_str or (
                            r.get("user_id") == reminder_user_id
                            and r.get("text", "").strip().lower() == reminder["task_text"].strip().lower()
                            and abs(r.get("trigger_time", 0) - exact_trigger_time) < 1.0
                        )
                        for r in scheduler.reminders
                    )
                if not already_present:
                    scheduler.add_reminder(
                        text=reminder["task_text"],
                        delay_seconds=delay_seconds,
                        reminder_id=rem_id_str,
                        user_id=reminder_user_id,
                        trigger_time=exact_trigger_time,
                        target_time=due_at,
                        recurrence=rec
                    )
                    scheduled_count += 1
            else:
                # Past / missed reminder during downtime
                missed_count += 1
                scheduler.record_missed_reminder({
                    "id": rem_id_str,
                    "user_id": reminder_user_id,
                    "text": reminder.get("task_text"),
                    "due_at": due_at,
                    "recurrence": rec
                })
        
        print(f"[REMINDER ENGINE] Loaded {scheduled_count} eligible future reminders ({missed_count} past/missed) from database for user {user_id}")
    except Exception as e:
        print(f"[REMINDER ENGINE] Error loading reminders from database: {e}")

def shutdown_scheduler():
    """Shutdown the global reminder scheduler."""
    global _global_scheduler
    if _global_scheduler:
        _global_scheduler.stop()
        _global_scheduler = None
