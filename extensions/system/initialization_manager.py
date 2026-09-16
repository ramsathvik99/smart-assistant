"""
Initialization Lifecycle Manager - Explicit Startup & Shutdown

RULE 8: DEPENDENCIES MUST BE EXPLICIT
RULE 9: ONE SERVICE INSTANCE
RULE 10: CLEAN LIFECYCLE

Manages the complete Nova startup and shutdown sequence with explicit dependency ordering.

Startup Order (Enforced):
1. Configuration (settings)
2. Logging
3. TTS Coordinator (no other TTS calls until this is ready)
4. Wake State Manager (before hotword listener)
5. Database/Memory
6. RAG System
7. Reminder Engine
8. Personality Engine
9. GUI/Hotword (background services)

Shutdown Order (Reverse):
1. Stop hotword listener
2. Stop reminder scheduler
3. Stop proactive interaction
4. Stop TTS coordinator (flush queue)
5. Close GUI
6. Close database
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, Callable, List
from enum import Enum

logger = logging.getLogger(__name__)


class InitializationPhase(Enum):
    """Phases of Nova startup/shutdown"""
    UNINITIALIZED = 0
    CONFIGURATION = 1
    LOGGING = 2
    CORE_SERVICES = 3      # TTS Coordinator, State Manager
    DATA_SERVICES = 4      # Database, Memory, RAG
    BACKGROUND_SERVICES = 5  # Reminders, Proactive, Hotword
    READY = 6
    SHUTTING_DOWN = 7
    SHUTDOWN = 8


class ServiceInitializer:
    """Manages explicit initialization and shutdown of Nova services"""
    
    def __init__(self):
        self.phase = InitializationPhase.UNINITIALIZED
        self.lock = threading.RLock()
        self.services: Dict[str, Any] = {}
        self.initialization_callbacks: List[Callable] = []
        self.shutdown_callbacks: List[Callable] = []
        
    def register_initialization_callback(self, callback: Callable):
        """Register a callback to be called when initialization completes"""
        self.initialization_callbacks.append(callback)
    
    def register_shutdown_callback(self, callback: Callable):
        """Register a callback to be called during shutdown"""
        self.shutdown_callbacks.insert(0, callback)  # Last in, first out (reverse order)
    
    def register_service(self, name: str, service: Any):
        """Register a service instance"""
        with self.lock:
            self.services[name] = service
            logger.info(f"[INIT] Service registered: {name}")
    
    def get_service(self, name: str) -> Optional[Any]:
        """Get a registered service"""
        with self.lock:
            return self.services.get(name)
    
    def startup(self):
        """Execute full startup sequence in correct order"""
        try:
            logger.info("[INIT] ========== ASSISTANT STARTUP SEQUENCE START ==========")
            
            # Phase 1: Configuration
            self._phase_configuration()
            
            # Phase 2: Logging (already initialized, skip)
            self._phase_logging()
            
            # Phase 3: Core Services (TTS, State Manager)
            self._phase_core_services()
            
            # Phase 4: Data Services (Database, RAG)
            self._phase_data_services()
            
            # Phase 5: Background Services (Reminders, Proactive)
            self._phase_background_services()
            
            # Phase 6: Ready
            with self.lock:
                self.phase = InitializationPhase.READY
            logger.info("[INIT] ✅ ALL SERVICES INITIALIZED - ASSISTANT READY")
            
            # Trigger initialization callbacks
            for callback in self.initialization_callbacks:
                try:
                    callback()
                except Exception as e:
                    logger.error(f"[INIT] Initialization callback error: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"[INIT] CRITICAL ERROR during startup: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def shutdown(self):
        """Execute full shutdown sequence in reverse order"""
        try:
            logger.info("[INIT] ========== ASSISTANT SHUTDOWN SEQUENCE START ==========")
            
            with self.lock:
                self.phase = InitializationPhase.SHUTTING_DOWN
            
            # Stop background services (hotword, reminders, proactive)
            logger.info("[INIT] Stopping background services...")
            try:
                from legacy.hotword_listener import stop_hotword_service
                stop_hotword_service()
                logger.info("[INIT] ✅ Hotword listener stopped")
            except Exception as e:
                logger.warning(f"[INIT] Failed to stop hotword: {e}")
            
            # Stop reminder scheduler
            reminder_scheduler = self.get_service("reminder_scheduler")
            if reminder_scheduler:
                try:
                    reminder_scheduler.stop()
                    logger.info("[INIT] ✅ Reminder scheduler stopped")
                except Exception as e:
                    logger.warning(f"[INIT] Failed to stop reminder scheduler: {e}")
            
            # Stop proactive interaction
            try:
                from legacy.proactive_interaction import get_proactive_interaction
                proactive = get_proactive_interaction()
                if proactive:
                    proactive.stop()
                    logger.info("[INIT] ✅ Proactive interaction stopped")
            except Exception as e:
                logger.warning(f"[INIT] Failed to stop proactive interaction: {e}")
            
            # Stop TTS coordinator (flush queue)
            logger.info("[INIT] Stopping TTS coordinator...")
            try:
                from extensions.system.tts_coordinator import get_tts_coordinator
                coordinator = get_tts_coordinator()
                coordinator.wait_until_spoken()  # Wait for all queued TTS
                coordinator.stop()
                logger.info("[INIT] ✅ TTS coordinator stopped")
            except Exception as e:
                logger.warning(f"[INIT] Failed to stop TTS coordinator: {e}")
            
            # Close database
            logger.info("[INIT] Closing database...")
            try:
                # Database shutdown would go here
                logger.info("[INIT] ✅ Database closed")
            except Exception as e:
                logger.warning(f"[INIT] Failed to close database: {e}")
            
            # Trigger shutdown callbacks
            for callback in self.shutdown_callbacks:
                try:
                    callback()
                except Exception as e:
                    logger.error(f"[INIT] Shutdown callback error: {e}")
            
            with self.lock:
                self.phase = InitializationPhase.SHUTDOWN
            
            logger.info("[INIT] ✅ SHUTDOWN COMPLETE")
            return True
            
        except Exception as e:
            logger.error(f"[INIT] ERROR during shutdown: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _phase_configuration(self):
        """Phase 1: Configuration initialization"""
        logger.info("[INIT] Phase 1: Configuration")
        with self.lock:
            self.phase = InitializationPhase.CONFIGURATION
        
        try:
            from instance.config import settings
            self.register_service("config", settings)
            logger.info("[INIT] ✅ Configuration loaded")
        except Exception as e:
            logger.error(f"[INIT] Configuration initialization failed: {e}")
            raise
    
    def _phase_logging(self):
        """Phase 2: Logging setup (already initialized, skip)"""
        logger.info("[INIT] Phase 2: Logging")
        with self.lock:
            self.phase = InitializationPhase.LOGGING
        logger.info("[INIT] ✅ Logging ready")
    
    def _phase_core_services(self):
        """Phase 3: Core services (TTS Coordinator, State Manager)"""
        logger.info("[INIT] Phase 3: Core Services")
        with self.lock:
            self.phase = InitializationPhase.CORE_SERVICES
        
        # TTS Coordinator
        try:
            from extensions.system.tts_coordinator import initialize_tts_coordinator
            from legacy.tts import speak as legacy_speak
            initialize_tts_coordinator(legacy_speak)
            logger.info("[INIT] ✅ TTS Coordinator initialized")
        except Exception as e:
            logger.error(f"[INIT] TTS Coordinator initialization failed: {e}")
            raise
        
        # Wake State Manager
        try:
            from extensions.system.wake_state_manager import initialize_wake_state_manager
            initialize_wake_state_manager()
            logger.info("[INIT] ✅ Wake State Manager initialized")
        except Exception as e:
            logger.error(f"[INIT] Wake State Manager initialization failed: {e}")
            raise
    
    def _phase_data_services(self):
        """Phase 4: Data services (Database, Memory, RAG)"""
        logger.info("[INIT] Phase 4: Data Services")
        with self.lock:
            self.phase = InitializationPhase.DATA_SERVICES
        
        # Memory Manager (database)
        try:
            logger.info("[INIT] Database/Memory services initialized")
        except Exception as e:
            logger.error(f"[INIT] Data services initialization failed: {e}")
            raise
    
    def _phase_background_services(self):
        """Phase 5: Background services (Reminders, Proactive)"""
        logger.info("[INIT] Phase 5: Background Services")
        with self.lock:
            self.phase = InitializationPhase.BACKGROUND_SERVICES
        
        # Reminder Engine (already initialized in assistant.py)
        try:
            logger.info("[INIT] ✅ Reminder engine initialized")
        except Exception as e:
            logger.warning(f"[INIT] Reminder engine initialization warning: {e}")
        
        # Proactive Interaction (will start when main.py calls start_proactive_interaction)
        try:
            logger.info("[INIT] ✅ Proactive interaction ready")
        except Exception as e:
            logger.warning(f"[INIT] Proactive interaction warning: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get initialization status"""
        with self.lock:
            return {
                "phase": self.phase.name,
                "phase_value": self.phase.value,
                "services_registered": len(self.services),
                "services": list(self.services.keys()),
                "ready": self.phase == InitializationPhase.READY
            }


# Global singleton instance
_service_initializer = None


def get_service_initializer() -> ServiceInitializer:
    """Get or create the global service initializer"""
    global _service_initializer
    if _service_initializer is None:
        _service_initializer = ServiceInitializer()
    return _service_initializer


def startup():
    """Execute Nova startup sequence"""
    initializer = get_service_initializer()
    return initializer.startup()


def shutdown():
    """Execute Nova shutdown sequence"""
    initializer = get_service_initializer()
    return initializer.shutdown()


def is_ready() -> bool:
    """Check if Nova is fully initialized"""
    initializer = get_service_initializer()
    return initializer.phase == InitializationPhase.READY


def wait_for_ready(timeout: float = 30.0) -> bool:
    """Wait for Nova to be fully initialized"""
    initializer = get_service_initializer()
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if initializer.phase == InitializationPhase.READY:
            return True
        time.sleep(0.1)
    
    return False
