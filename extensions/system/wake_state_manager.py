"""
Wake-Word State Manager - Thread-Safe State Machine

RULE 6: WAKE MODE IS STATEFUL
- Maintains two distinct states: WAKE_MODE and COMMAND_MODE
- Thread-safe state transitions
- Prevents race conditions between hotword, proactive, and reminder threads
- Enforces strict state machine rules

State Machine:
  WAKE_MODE (listening for wake word only)
    └─ Wake word detected
       └─ COMMAND_MODE (listening for command)
          └─ Command processed
             └─ WAKE_MODE (return to listening)

RULE 7: NO FALSE WAKE CALLBACKS
- Only valid wake-word detections trigger COMMAND_MODE
- No auto-triggers from other events
"""

import logging
import threading
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class WakeState(Enum):
    """Nova wake-word state machine states"""
    WAKE_MODE = "wake"      # Listening for wake word only
    COMMAND_MODE = "command"  # Listening for user command


class WakeStateManager:
    """Thread-safe wake-word state machine"""
    
    def __init__(self):
        self.state = WakeState.WAKE_MODE
        self.lock = threading.RLock()  # Recursive lock for nested calls
        self.state_change_callbacks = {}  # state -> [callback1, callback2, ...]
        
    def get_state(self) -> WakeState:
        """Get current wake state (thread-safe)"""
        with self.lock:
            return self.state
    
    def is_wake_mode(self) -> bool:
        """Check if in wake mode"""
        with self.lock:
            return self.state == WakeState.WAKE_MODE
    
    def is_command_mode(self) -> bool:
        """Check if in command mode"""
        with self.lock:
            return self.state == WakeState.COMMAND_MODE
    
    def enter_command_mode(self) -> bool:
        """
        Transition to COMMAND_MODE after valid wake detection.
        
        RULE 7: This must ONLY be called after actual wake-word detection,
        not from timers, silence, or other spurious triggers.
        
        Returns:
            True if successfully entered COMMAND_MODE, False if already in it
        """
        with self.lock:
            if self.state == WakeState.COMMAND_MODE:
                logger.warning("[WAKE STATE] Already in COMMAND_MODE, ignoring duplicate request")
                return False
            
            old_state = self.state
            self.state = WakeState.COMMAND_MODE
            logger.info("[WAKE STATE] State transition: WAKE_MODE → COMMAND_MODE")
            
            # Trigger callbacks
            self._trigger_callbacks(WakeState.COMMAND_MODE)
            return True
    
    def return_to_wake_mode(self) -> bool:
        """
        Transition back to WAKE_MODE after command processing.
        
        Returns:
            True if successfully returned to WAKE_MODE, False if already in it
        """
        with self.lock:
            if self.state == WakeState.WAKE_MODE:
                logger.warning("[WAKE STATE] Already in WAKE_MODE, ignoring duplicate request")
                return False
            
            old_state = self.state
            self.state = WakeState.WAKE_MODE
            logger.info("[WAKE STATE] State transition: COMMAND_MODE → WAKE_MODE")
            
            # Trigger callbacks
            self._trigger_callbacks(WakeState.WAKE_MODE)
            return True
    
    def register_state_change_callback(self, new_state: WakeState, callback: Callable):
        """
        Register a callback to be invoked when entering a specific state.
        
        Callbacks are executed synchronously within the state lock,
        so they must complete quickly to avoid blocking other state changes.
        
        Args:
            new_state: State to trigger on (WAKE_MODE or COMMAND_MODE)
            callback: Function to call (no arguments)
        
        Example:
            manager.register_state_change_callback(WakeState.COMMAND_MODE, lambda: print("Entered command mode"))
        """
        if new_state not in self.state_change_callbacks:
            self.state_change_callbacks[new_state] = []
        
        self.state_change_callbacks[new_state].append(callback)
        logger.debug(f"[WAKE STATE] Registered callback for {new_state.value}")
    
    def _trigger_callbacks(self, state: WakeState):
        """Trigger all callbacks registered for a state change"""
        callbacks = self.state_change_callbacks.get(state, [])
        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"[WAKE STATE] Callback error for {state.value}: {e}")
    
    def get_status(self) -> dict:
        """Get current state status"""
        with self.lock:
            return {
                "state": self.state.value,
                "is_wake_mode": self.state == WakeState.WAKE_MODE,
                "is_command_mode": self.state == WakeState.COMMAND_MODE,
                "registered_callbacks": {
                    state.value: len(callbacks)
                    for state, callbacks in self.state_change_callbacks.items()
                }
            }


# Global singleton instance
_wake_state_manager = None


def get_wake_state_manager() -> WakeStateManager:
    """Get or create the global wake state manager"""
    global _wake_state_manager
    if _wake_state_manager is None:
        _wake_state_manager = WakeStateManager()
        logger.info("[WAKE STATE] Global WakeStateManager created")
    return _wake_state_manager


def initialize_wake_state_manager():
    """Initialize the global wake state manager"""
    manager = get_wake_state_manager()
    logger.info(f"[WAKE STATE] Initialized: {manager.get_status()}")
    return manager


# Public convenience functions
def is_wake_mode() -> bool:
    """Check if currently in WAKE_MODE"""
    return get_wake_state_manager().is_wake_mode()


def is_command_mode() -> bool:
    """Check if currently in COMMAND_MODE"""
    return get_wake_state_manager().is_command_mode()


def enter_command_mode() -> bool:
    """Enter COMMAND_MODE after wake detection"""
    return get_wake_state_manager().enter_command_mode()


def return_to_wake_mode() -> bool:
    """Return to WAKE_MODE after command processing"""
    return get_wake_state_manager().return_to_wake_mode()
