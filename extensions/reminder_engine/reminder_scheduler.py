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
    
    def add_reminder(self, text: str, delay_seconds: int, reminder_id: Optional[str] = None, user_id: Optional[int] = None) -> str:
        """
        Add a new reminder to the scheduler.
        
        Args:
            text: The reminder text to speak
            delay_seconds: Delay in seconds from now
            reminder_id: Optional custom ID (auto-generated if not provided)
            user_id: The user ID this reminder belongs to
            
        Returns:
            The reminder ID for tracking
        """
        if not reminder_id:
            reminder_id = str(uuid.uuid4())
        
        trigger_time = time.time() + delay_seconds
        
        with self._lock:
            self.reminders.append({
                "id": reminder_id,
                "text": text,
                "trigger_time": trigger_time,
                "delay_seconds": delay_seconds,
                "triggered": False,
                "created_at": time.time(),
                "user_id": user_id
            })
        
        # Calculate human-readable time
        trigger_datetime = datetime.datetime.fromtimestamp(trigger_time)
        print(f"[REMINDER ENGINE] Scheduled: '{text}' at {trigger_datetime.strftime('%H:%M:%S')} for user {user_id}")
        
        return reminder_id
    
    def add_reminder_at_time(self, text: str, target_time: datetime.datetime, reminder_id: Optional[str] = None, user_id: Optional[int] = None) -> str:
        """
        Add a reminder for a specific time.
        
        Args:
            text: The reminder text to speak
            target_time: Specific datetime to trigger
            reminder_id: Optional custom ID
            user_id: The user ID this reminder belongs to
            
        Returns:
            The reminder ID for tracking
        """
        if not reminder_id:
            reminder_id = str(uuid.uuid4())
        
        now = datetime.datetime.now()
        if target_time <= now:
            # If time is in the past, schedule for tomorrow
            target_time = target_time.replace(day=target_time.day + 1)
        
        delay_seconds = (target_time - now).total_seconds()
        return self.add_reminder(text, int(delay_seconds), reminder_id, user_id)
    
    def cancel_reminder(self, reminder_id: str) -> bool:
        """
        Cancel a pending reminder.
        
        Args:
            reminder_id: The ID of the reminder to cancel
            
        Returns:
            True if cancelled, False if not found
        """
        with self._lock:
            for i, reminder in enumerate(self.reminders):
                if reminder["id"] == reminder_id and not reminder["triggered"]:
                    del self.reminders[i]
                    print(f"[REMINDER ENGINE] Cancelled reminder: {reminder_id}")
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
        try:
            reminder_text = reminder["text"]
            reminder_id = reminder["id"]
            
            print(f"[REMINDER ENGINE] Triggering reminder: '{reminder_text}'")
            
            # Mark as notified in database if db_manager is available
            if self.db_manager:
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
            
            # Speak reminder via TTS Coordinator with REMINDER priority
            try:
                from extensions.system.tts_coordinator import speak, TTSPriority
                speak(f"Reminder: {reminder_text}", priority=TTSPriority.REMINDER)
            except (ImportError, Exception) as e:
                print(f"[REMINDER ENGINE] TTS Coordinator failed: {e}")
                # Fallback to legacy callback if available
                if self.tts_callback:
                    try:
                        import threading
                        threading.Thread(target=self.tts_callback, args=(f"Reminder: {reminder_text}",), daemon=True).start()
                    except Exception as e2:
                        print(f"[REMINDER ENGINE] Fallback TTS failed: {e2}")
                        print(f"[REMINDER] {reminder_text}")
                else:
                    print(f"[REMINDER] {reminder_text}")
                
        except Exception as e:
            print(f"[REMINDER ENGINE] Error triggering reminder: {e}")
    
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
        if self.db_manager and user_id:
            # Clear current in-memory reminders
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

def initialize_scheduler(tts_callback: Optional[Callable] = None, sound_callback: Optional[Callable] = None, db_manager=None, user_id=None) -> ReminderScheduler:
    """
    Initialize the global reminder scheduler.
    
    Args:
        tts_callback: Function to call for TTS output
        sound_callback: Function to call for sound alerts
        db_manager: DatabaseManager instance for persistence
        user_id: Current authenticated user ID
        
    Returns:
        The initialized scheduler instance
    """
    global _global_scheduler
    
    # Stop existing scheduler if running
    if _global_scheduler:
        _global_scheduler.stop()
    
    _global_scheduler = ReminderScheduler(tts_callback, sound_callback, db_manager)
    
    # Load pending reminders from database if db_manager and user_id are available
    if db_manager and user_id:
        _load_reminders_from_database(_global_scheduler, db_manager, user_id)
    
    return _global_scheduler

def _load_reminders_from_database(scheduler: ReminderScheduler, db_manager, user_id=None):
    """Load pending reminders from database into scheduler for specific user."""
    try:
        pending_reminders = db_manager.get_pending_reminders(user_id)
        now = datetime.datetime.now()
        
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
            
            # Only load reminders that are in the future
            if due_at > now:
                delay_seconds = (due_at - now).total_seconds()
                reminder_user_id = reminder.get("user_id", user_id)
                scheduler.add_reminder(reminder["task_text"], int(delay_seconds), str(reminder["id"]), reminder_user_id)
                print(f"[REMINDER ENGINE] Loaded reminder from database for user {reminder_user_id}: '{reminder['task_text']}' at {due_at}")
        
        print(f"[REMINDER ENGINE] Loaded {len(pending_reminders)} reminders from database for user {user_id}")
    except Exception as e:
        print(f"[REMINDER ENGINE] Error loading reminders from database: {e}")

def shutdown_scheduler():
    """Shutdown the global reminder scheduler."""
    global _global_scheduler
    if _global_scheduler:
        _global_scheduler.stop()
        _global_scheduler = None
