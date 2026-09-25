"""
NOVA System Control Menu
Right-click context menu with system control functions.
"""

import tkinter as tk
from datetime import datetime

# Debug logging
DEBUG = True
def log_debug(msg):
    if DEBUG:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [SYSTEM_MENU] {msg}")


class AssistantSystemMenu:
    """
    System control menu for right-click on floating button.
    Provides access to system-level Assistant functions.
    """
    
    def __init__(self, root, button_window):
        """
        Initialize system menu.
        
        Args:
            root: Tk root window
            button_window: The floating button Toplevel window
        """
        self.root = root
        self.button_window = button_window
        self.menu = None
    
    def show(self, event):
        """
        Show the system menu at cursor position (non-blocking).
        
        Args:
            event: Tkinter event containing x, y coordinates
        """
        log_debug("System menu showing")
        
        # Create menu if not exists or recreate if needed
        self._create_menu()
        
        # Position menu at cursor
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        except tk.TclError:
            # Menu already visible
            pass
        finally:
            # Make sure to unpost menu when done
            try:
                self.menu.grab_release()
            except:
                pass
    
    def _create_menu(self):
        """Create the system menu with items."""
        # Destroy old menu if exists
        if self.menu:
            try:
                self.menu.destroy()
            except:
                pass
        
        self.menu = tk.Menu(
            self.root,
            tearoff=0,
            bg="#2a2a3e",
            fg="#c8eeff",
            activebackground="#6366f1",
            activeforeground="white",
            bd=1,
            relief=tk.FLAT,
            font=("Segoe UI", 10)
        )
        
        # Assistant dynamic name
        try:
            from instance.config import settings as _cfg
            _asst = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            _asst = "Assistant"

        # Menu items: (label, callback)
        menu_items = [
            (f"🔄 Restart {_asst}", self._on_restart),
            ("🔁 Reload Modules", self._on_reload),
            ("✓ Check for Updates", self._on_updates),
            (f"ℹ️ {_asst} Status", self._on_status),
            (None, None),  # Separator
            ("🚪 Logout", self._on_logout),
            (f"❌ Exit {_asst}", self._on_exit),
        ]
        
        for label, callback in menu_items:
            if label is None:
                # Add separator
                self.menu.add_separator()
            else:
                # Add menu item
                self.menu.add_command(
                    label=label,
                    command=callback
                )
    
        try:
            from instance.config import settings as _cfg
            _asst = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            _asst = "Assistant"
        log_debug(f"Restart {_asst} selected")
        self.root.after(0, self._execute_restart)
    
    def _execute_restart(self):
        """Execute restart."""
        try:
            from instance.config import settings as _cfg
            _asst = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            _asst = "Assistant"
        try:
            from legacy.tts import speak
            speak(f"Restarting {_asst}")
            
            import subprocess
            import sys
            import time
            
            # Give TTS time to finish
            time.sleep(1)
            
            # Restart the application
            python_exe = sys.executable
            import os
            nova_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            main_py = os.path.join(nova_root, "legacy", "main.py")
            
            subprocess.Popen([python_exe, main_py])
            
            # Exit current instance
            self.root.after(500, lambda: self.root.destroy())
            sys.exit(0)
        except Exception as e:
            log_debug(f"Error restarting: {e}")
    
    def _on_reload(self):
        """Reload modules."""
        log_debug("Reload Modules selected")
        self.root.after(0, self._execute_reload)
    
    def _execute_reload(self):
        """Execute module reload."""
        try:
            from legacy.tts import speak
            speak("Reloading modules")
            
            import importlib
            import extensions.ai_engine
            
            importlib.reload(extensions.ai_engine)
            
            speak("Modules reloaded")
        except Exception as e:
            log_debug(f"Error reloading: {e}")
    
    def _on_updates(self):
        """Check for updates."""
        log_debug("Check for Updates selected")
        self.root.after(0, self._execute_updates)
    
    def _execute_updates(self):
        """Execute update check."""
        try:
            from instance.config import settings as _cfg
            _asst = _cfg.get_assistant_name() or "Assistant"
            from legacy.tts import speak
            speak("Checking for updates")
            # TODO: Implement actual update checking
            speak(f"{_asst} is up to date")
        except Exception as e:
            log_debug(f"Error checking updates: {e}")
    
    def _on_status(self):
        """Show assistant status."""
        try:
            from instance.config import settings as _cfg
            _asst = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            _asst = "Assistant"
        log_debug(f"{_asst} Status selected")
        self.root.after(0, self._execute_status)
    
    def _execute_status(self):
        """Execute status display."""
        try:
            from modules.launcher.status_window import StatusWindow
            
            # Check if status window already open
            if hasattr(self.root, '_status_window'):
                window = self.root._status_window
                if window and window.winfo_exists():
                    window.deiconify()
                    window.lift()
                    return
            
            # Create new status window
            status_window = StatusWindow(self.root)
            self.root._status_window = status_window
        except Exception as e:
            log_debug(f"Error showing status: {e}")
    
    def _on_logout(self):
        """Logout user."""
        log_debug("Logout selected")
        self.root.after(0, self._execute_logout)
    
    def _execute_logout(self):
        """Execute logout."""
        try:
            from legacy.tts import speak
            speak("Logging out")
            
            # Get stored references (set by main.py during startup)
            floating_button = getattr(self.root, '_floating_button', None)
            launcher_panel = None
            main_ui = getattr(self.root, '_main_ui_instance', None)
            
            # Try to get launcher panel if it exists
            if floating_button and hasattr(floating_button, 'launcher_panel'):
                launcher_panel = floating_button.launcher_panel
            
            # Get callback for re-login (should be start_assistant_services)
            login_callback = getattr(self.root, '_on_login_success_callback', None)
            
            # Use shutdown manager
            from modules.launcher.shutdown_manager import logout_user, set_references
            
            set_references(
                self.root,
                floating_button=floating_button,
                launcher_panel=launcher_panel,
                main_ui_instance=main_ui,
                on_login_success_callback=login_callback
            )
            
            logout_user()
        except Exception as e:
            log_debug(f"Error logging out: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_exit(self):
        """Exit assistant."""
        try:
            from instance.config import settings as _cfg
            _asst = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            _asst = "Assistant"
        log_debug(f"Exit {_asst} selected")
        self.root.after(0, self._execute_exit)
    
    def _execute_exit(self):
        """Execute exit."""
        try:
            from instance.config import settings as _cfg
            _asst = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            _asst = "Assistant"
        try:
            from legacy.tts import speak
            speak(f"Exiting {_asst}")
            
            # Get stored references (set by main.py during startup)
            floating_button = getattr(self.root, '_floating_button', None)
            launcher_panel = None
            main_ui = getattr(self.root, '_main_ui_instance', None)
            
            # Try to get launcher panel if it exists
            if floating_button and hasattr(floating_button, 'launcher_panel'):
                launcher_panel = floating_button.launcher_panel
            
            # Use shutdown manager
            from modules.launcher.shutdown_manager import exit_assistant, set_references
            
            set_references(
                self.root,
                floating_button=floating_button,
                launcher_panel=launcher_panel,
                main_ui_instance=main_ui
            )
            
            exit_assistant()
        except Exception as e:
            log_debug(f"Error exiting: {e}")
            import traceback
            traceback.print_exc()
            # Force exit
            import sys
            sys.exit(0)
