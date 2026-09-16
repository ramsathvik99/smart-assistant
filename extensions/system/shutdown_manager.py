import sys
import threading

class ShutdownManager:
    def __init__(self):
        self.shutdown_event = threading.Event()

    def trigger_shutdown(self):
        print("[SYSTEM] Initiating full shutdown...")
        self.shutdown_event.set()

    def should_shutdown(self):
        return self.shutdown_event.is_set()

    def force_exit(self):
        print("[SYSTEM] Exiting process.")
        sys.exit(0)
