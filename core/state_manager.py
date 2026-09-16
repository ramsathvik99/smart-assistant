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
        self.interrupt_count = 0
        
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
        
    def set_current_task(self, task_name):
        """Set current task for debugging"""
        self.current_task = task_name
        
    def get_current_task(self):
        """Get current task name"""
        return self.current_task
        
    def wait_for_clear(self, timeout=1.0):
        """Wait for interrupt to be cleared"""
        return self.interrupt_event.wait(timeout)

# Global singleton instance
state_manager = StateManager()
