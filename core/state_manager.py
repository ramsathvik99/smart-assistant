"""
Global State Manager for Nova
Handles interrupt signals across all modules
"""

import threading
import time

class StateManager:
    def __init__(self):
        self.interrupt_event = threading.Event()
        self.current_task = None
        self.task_progress = 0
        self.task_steps = []
        self.active_operation = None
        self.interrupt_count = 0
        self._lock = threading.Lock()
        
    def trigger_interrupt(self):
        """Trigger interrupt signal across all modules"""
        self.interrupt_count += 1
        print(f"[STATE] Interrupt triggered (#{self.interrupt_count})")
        self.interrupt_event.set()
        
    def clear_interrupt(self):
        """Clear interrupt signal for new operations"""
        print(f"[STATE] Interrupt cleared")
        self.interrupt_event.clear()
        
    def is_interrupted(self):
        """Check if interrupt is active"""
        return self.interrupt_event.is_set()
        
    def set_current_task(self, task_name, steps=None):
        """Set current task with optional step plan"""
        with self._lock:
            self.current_task = task_name
            self.task_progress = 0
            self.task_steps = steps or []
            self.active_operation = task_name
        
    def update_task_progress(self, progress: int, current_step: str = None):
        """Update ongoing execution progress (0-100)"""
        with self._lock:
            self.task_progress = max(0, min(100, progress))
            if current_step:
                self.active_operation = current_step
                
    def complete_task(self, success: bool = True):
        """Mark task completed"""
        with self._lock:
            self.task_progress = 100 if success else self.task_progress
            self.active_operation = None
            self.current_task = None
        
    def get_current_task_info(self):
        """Get snapshot of current task and execution status"""
        with self._lock:
            return {
                "task": self.current_task,
                "progress": self.task_progress,
                "active_operation": self.active_operation,
                "steps": list(self.task_steps),
                "interrupted": self.interrupt_event.is_set()
            }

    def get_current_task(self):
        """Get current task name"""
        return self.current_task
        
    def wait_for_clear(self, timeout=1.0):
        """Wait for interrupt to be cleared"""
        return self.interrupt_event.wait(timeout)

# Global singleton instance
state_manager = StateManager()

