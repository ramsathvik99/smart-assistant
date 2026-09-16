"""
Context menu for NOVA floating button.
Right-click menu with dark theme and modern styling.

CRITICAL REQUIREMENTS:
- All callbacks must be non-blocking
- Use root.after(0, callback) to schedule callbacks on main thread
- If callback does heavy work, it must start a daemon thread
- All exceptions must be caught and logged
"""

import tkinter as tk
from datetime import datetime

# Debug logging with timestamps
DEBUG = True
def log_debug(msg):
    if DEBUG:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [CONTEXT_MENU] {msg}")


class FloatingButtonContextMenu:
    """
    Context menu for floating button right-click.
    Provides quick access to launcher, settings, restart, logout, and exit.
    """
    
    def __init__(self, root, button_window, callbacks=None):
        """
        Initialize context menu.
        
        Args:
            root: Tk root window
            button_window: The floating button Toplevel window
            callbacks: Dictionary of callback functions:
                {
                    'open_launcher': callable,
                    'settings': callable,
                    'restart': callable,
                    'logout': callable,
                    'exit': callable
                }
        """
        self.root = root
        self.button_window = button_window
        self.callbacks = callbacks or {}
        self.menu = None
    
    def show(self, event):
        """
        Show context menu at cursor position (non-blocking).
        
        Args:
            event: Tkinter event containing x, y coordinates
        """
        log_debug("Context menu showing")
        
        # Create menu if not exists
        if self.menu is None:
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
        """Create the context menu with items."""
        self.menu = tk.Menu(
            self.root,
            tearoff=0,
            bg="#2a2a3e",
            fg="white",
            activebackground="#6366f1",
            activeforeground="white",
            bd=1,
            relief=tk.FLAT,
            font=("Segoe UI", 10)
        )
        
        # Menu items
        try:
            from instance.config import settings as _cfg
            _asst = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            _asst = "Assistant"

        menu_items = [
            ("📱 Open Launcher", "open_launcher"),
            ("⚙️ Settings", "settings"),
            (None, None),  # Separator
            (f"🔄 Restart {_asst}", "restart"),
            ("🚪 Logout", "logout"),
            (f"❌ Exit {_asst}", "exit"),
        ]
        
        for label, action in menu_items:
            if label is None:
                # Add separator
                self.menu.add_separator()
            else:
                # Add menu item
                callback = self.callbacks.get(action) if action else None
                self.menu.add_command(
                    label=label,
                    command=lambda cb=callback: self._on_menu_item(cb)
                )
    
    def _on_menu_item(self, callback):
        """
        Handle menu item selection (non-blocking).
        
        Schedules callback on main thread to ensure non-blocking execution.
        If callback does heavy work, it must start a daemon thread.
        """
        log_debug(f"Menu item selected: {callback}")
        if callback:
            # Schedule callback on main thread (non-blocking)
            self.root.after(0, lambda: self._safe_callback(callback))
    
    def _safe_callback(self, callback):
        """
        Execute callback safely with exception handling.
        
        Protects main thread from any blocking or error-prone callbacks.
        """
        try:
            log_debug(f"Executing menu callback")
            callback()
            log_debug(f"Menu callback completed")
        except Exception as e:
            log_debug(f"ERROR in menu callback: {e}")
            import traceback
            traceback.print_exc()

