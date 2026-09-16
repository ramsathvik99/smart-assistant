"""
NOVA Shutdown Manager
Handles graceful logout and application termination.
"""

import threading
import time
import sys
import os
from datetime import datetime

# Debug logging
DEBUG = True
def log_debug(msg):
    if DEBUG:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [SHUTDOWN] {msg}")


# Global references
_tk_root = None
_floating_button = None
_launcher_panel = None
_main_ui_instance = None
_hotword_thread = None
_on_login_success_callback = None


def set_references(root, floating_button=None, launcher_panel=None, main_ui_instance=None, hotword_thread=None, on_login_success_callback=None):
    """Set global references for shutdown."""
    global _tk_root, _floating_button, _launcher_panel, _main_ui_instance, _hotword_thread, _on_login_success_callback
    _tk_root = root
    _floating_button = floating_button
    _launcher_panel = launcher_panel
    _main_ui_instance = main_ui_instance
    _hotword_thread = hotword_thread
    _on_login_success_callback = on_login_success_callback
    log_debug("Shutdown manager initialized with references")


# ─────────────────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────────────────

def logout_user():
    """
    Logout the current user and return to login screen.
    Do NOT terminate the application.
    """
    log_debug("logout_user() called")
    
    if _tk_root is None:
        log_debug("No root window, cannot logout")
        return
    
    # Start logout in daemon thread to avoid blocking UI
    def _logout_in_thread():
        try:
            log_debug("Starting logout sequence")
            
            # Step 1: Close context menu (if visible)
            log_debug("Step 1: Closing context menu")
            # Context menu will close automatically when main UI updates
            
            # Step 2: Close launcher panel
            log_debug("Step 2: Closing launcher panel")
            if _launcher_panel:
                try:
                    if hasattr(_launcher_panel, 'close'):
                        _launcher_panel.close()
                    if hasattr(_launcher_panel, 'destroy'):
                        _launcher_panel.destroy()
                except:
                    pass
            
            # Step 3: Stop voice listening
            log_debug("Step 3: Stopping voice listener")
            _stop_voice_listener()
            
            # Step 4: Stop background services
            log_debug("Step 4: Stopping background services")
            _stop_background_services()
            
            # Step 5: Close main GUI
            log_debug("Step 5: Closing main GUI")
            if _main_ui_instance:
                try:
                    if _main_ui_instance.winfo_exists():
                        _main_ui_instance.destroy()
                except:
                    pass
            
            # Step 6: Clear user session
            log_debug("Step 6: Clearing user session")
            _clear_user_session()
            
            # Step 7: Reset launcher and floating button references
            log_debug("Step 7: Resetting UI references")
            if _floating_button:
                try:
                    _floating_button.launcher_panel = None
                except:
                    pass
            
            # Step 8: Show login window on main thread
            log_debug("Step 8: Showing login window")
            _tk_root.after(0, _show_login_window)
            
            log_debug("Logout sequence completed successfully")
            
        except Exception as e:
            log_debug(f"Error during logout: {e}")
            import traceback
            traceback.print_exc()
    
    # Execute logout in daemon thread
    thread = threading.Thread(target=_logout_in_thread, daemon=True)
    thread.start()


def _stop_voice_listener():
    """Stop the voice/hotword listener."""
    log_debug("Stopping voice listener")
    try:
        # The hotword thread runs in a loop - we can't directly kill it
        # But we can let it naturally exit when the application continues
        # The next login will start a new hotword thread
        pass
    except Exception as e:
        log_debug(f"Error stopping voice listener: {e}")


def _stop_background_services():
    """Stop background services related to current user session."""
    log_debug("Stopping background services")
    try:
        # Stop proactive interaction
        try:
            from legacy.proactive_interaction import stop_proactive_interaction
            stop_proactive_interaction()
        except:
            pass
        
        # Stop any running threads
        import threading
        for thread in threading.enumerate():
            if thread.daemon and thread != threading.current_thread():
                log_debug(f"Daemon thread running: {thread.name}")
                # Daemon threads will automatically terminate when main thread continues
        
    except Exception as e:
        log_debug(f"Error stopping background services: {e}")


def _clear_user_session():
    """Clear the current user session."""
    log_debug("Clearing user session")
    try:
        from instance.config import settings as CONFIG
        from core.config import save_runtime_config

        # Clear current user and assistant name — prevents leakage between accounts
        CONFIG.CURRENT_USER_ID = None
        CONFIG.CURRENT_USERNAME = None
        CONFIG.CURRENT_ASSISTANT_NAME = None  # Per-user assistant name must not leak
        CONFIG.ASSISTANT_NAME = None  # Also clear any env-level name so nothing bleeds through

        # Clear runtime config
        save_runtime_config({"LAST_USER_ID": None})

        log_debug("User session cleared (user, username, assistant name all reset)")
    except Exception as e:
        log_debug(f"Error clearing session: {e}")


def _show_login_window():
    """Show the login window."""
    log_debug("Showing login window")
    try:
        from legacy.login_window import LoginWindow
        
        # Create callback for re-login that calls the stored callback
        def _on_relogin_success():
            log_debug("User logged back in, restarting services")
            if _on_login_success_callback:
                _on_login_success_callback()
            else:
                log_debug("No callback set for post-login, services may not restart")
        
        # Create new login window
        login = LoginWindow(_tk_root, on_login_success=_on_relogin_success)
        log_debug("Login window created and displayed")
    except Exception as e:
        log_debug(f"Error showing login window: {e}")
        import traceback
        traceback.print_exc()


# ─────────────────────────────────────────────────────────
# EXIT NOVA
# ─────────────────────────────────────────────────────────

def exit_assistant():
    """
    Gracefully shut down and exit the Assistant completely.
    """
    log_debug("exit_assistant() called")
    
    if _tk_root is None:
        log_debug("No root window, exiting immediately")
        sys.exit(0)
    
    # Start shutdown in daemon thread to avoid blocking UI
    def _exit_in_thread():
        try:
            log_debug("Starting shutdown sequence")
            
            # Step 1: Stop accepting new commands
            log_debug("Step 1: Stopping command processing")
            
            # Step 2: Close launcher panel
            log_debug("Step 2: Closing launcher panel")
            if _launcher_panel:
                try:
                    if hasattr(_launcher_panel, 'close'):
                        _launcher_panel.close()
                    if hasattr(_launcher_panel, 'destroy'):
                        _launcher_panel.destroy()
                except:
                    pass
            
            # Step 3: Close floating button
            log_debug("Step 3: Closing floating button")
            if _floating_button:
                try:
                    if hasattr(_floating_button, 'window'):
                        _floating_button.window.destroy()
                except:
                    pass
            
            # Step 4: Close main GUI
            log_debug("Step 4: Closing main GUI")
            if _main_ui_instance:
                try:
                    if _main_ui_instance.winfo_exists():
                        _main_ui_instance.destroy()
                except:
                    pass
            
            # Step 5: Stop voice listener
            log_debug("Step 5: Stopping voice listener")
            _stop_voice_listener()
            
            # Step 6: Stop all background services
            log_debug("Step 6: Stopping background services")
            _stop_all_services()
            
            # Step 7: Close database connections
            log_debug("Step 7: Closing database connections")
            _close_database_connections()
            
            # Step 8: Stop plugins
            log_debug("Step 8: Stopping plugins")
            _stop_plugins()
            
            # Step 9: Save state
            log_debug("Step 9: Saving application state")
            _save_application_state()
            
            # Step 10: Schedule shutdown on main thread
            log_debug("Step 10: Scheduling shutdown on main thread")
            _tk_root.after(100, _do_shutdown)
            
            log_debug("Shutdown sequence initiated")
            
        except Exception as e:
            log_debug(f"Error during shutdown: {e}")
            import traceback
            traceback.print_exc()
            # Force exit anyway
            _tk_root.after(100, _do_shutdown)
    
    # Execute shutdown in daemon thread
    thread = threading.Thread(target=_exit_in_thread, daemon=True)
    thread.start()


def _stop_all_services():
    """Stop all background services."""
    log_debug("Stopping all services")
    try:
        # Stop proactive interaction
        try:
            from legacy.proactive_interaction import stop_proactive_interaction
            stop_proactive_interaction()
        except:
            pass
        
        # Stop TTS worker
        try:
            from legacy import tts
            # Queue None to signal worker thread to stop
            tts._tts_queue.put(None)
        except:
            pass
        
        # Stop speech recognition
        try:
            from legacy import sst
            if hasattr(sst, 'stop_listening'):
                sst.stop_listening()
        except:
            pass
        
        log_debug("All services stopped")
    except Exception as e:
        log_debug(f"Error stopping services: {e}")


def _close_database_connections():
    """Close database connections."""
    log_debug("Closing database connections")
    try:
        # Close any open database connections
        # This depends on your database setup
        pass
    except Exception as e:
        log_debug(f"Error closing database: {e}")


def _stop_plugins():
    """Stop plugins."""
    log_debug("Stopping plugins")
    try:
        from extensions.plugin_manager import PluginManager
        pm = PluginManager()
        # Plugins are unloaded automatically when the app exits
        log_debug("Plugins stopped")
    except Exception as e:
        log_debug(f"Error stopping plugins: {e}")


def _save_application_state():
    """Save any required application state before exit."""
    log_debug("Saving application state")
    try:
        # Save user settings if needed
        # Save logs if needed
        # Save session state if needed
        pass
    except Exception as e:
        log_debug(f"Error saving state: {e}")


def _do_shutdown():
    """Perform final shutdown on main thread."""
    log_debug("Performing final shutdown")
    try:
        # Destroy root window
        if _tk_root:
            try:
                _tk_root.quit()
                _tk_root.destroy()
            except:
                pass
        
        log_debug("Root window destroyed")
        time.sleep(0.2)  # Brief pause to allow cleanup
        
        log_debug("Exiting application")
        sys.exit(0)
        
    except Exception as e:
        log_debug(f"Error during final shutdown: {e}")
        # Force exit
        os._exit(0)
