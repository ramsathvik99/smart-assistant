"""
NOVA Launcher Panel - Stable Implementation
Lightweight, non-blocking launcher with 4 functional buttons.
"""

import tkinter as tk
from tkinter import ttk
import threading
from datetime import datetime

# Debug logging
DEBUG = True
def log_debug(msg):
    if DEBUG:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [LAUNCHER] {msg}")


class LauncherPanel:
    """
    Stable launcher panel with 4 buttons.
    Single Toplevel window, non-blocking design.
    """
    
    def __init__(self, root, button_window):
        """
        Initialize launcher panel.
        
        Args:
            root: Tk root window
            button_window: Floating button window
        """
        log_debug("LauncherPanel.__init__() called")
        
        self.root = root
        self.button_window = button_window
        self.window = None
        self.is_visible = False
        self.close_timer = None
        
        log_debug("LauncherPanel initialized (window not yet created)")
    
    def toggle(self):
        """Toggle launcher visibility."""
        log_debug(f"toggle() called, is_visible={self.is_visible}")
        
        if self.is_visible:
            self.close()
        else:
            self.open()
    
    def open(self):
        """Open the launcher panel."""
        log_debug("open() called")
        
        # Already open?
        if self.is_visible:
            log_debug("Panel already visible, returning")
            return
        
        # Window destroyed? Recreate it
        if self.window is None or not self._window_exists():
            log_debug("Creating new launcher window")
            self._create_window()
        
        # Show window
        try:
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
        except:
            pass
        
        self.is_visible = True
        log_debug("Launcher opened and visible")
    
    def close(self):
        """Close the launcher panel."""
        log_debug("close() called")
        
        if not self.is_visible:
            log_debug("Panel already hidden, returning")
            return
        
        self.is_visible = False
        
        # Cancel any pending close timer
        if self.close_timer:
            self.root.after_cancel(self.close_timer)
            self.close_timer = None
        
        # Hide window (don't destroy - reuse it)
        if self.window and self._window_exists():
            try:
                self.window.withdraw()
            except:
                pass
        
        log_debug("Launcher closed")
    
    def _create_window(self):
        """Create the launcher window."""
        log_debug("_create_window() called")
        
        # Create Toplevel window
        try:
            from instance.config import settings as _cfg
            _asst = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            _asst = "Assistant"

        self.window = tk.Toplevel(self.root)
        self.window.title(f"{_asst} Launcher")
        self.window.geometry("280x220")
        self.window.overrideredirect(False)  # Allow window manager to manage
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)
        
        # Configure style
        self.window.configure(bg="#0b1a2a")
        
        # Bind events
        self.window.bind("<Escape>", self._on_escape)
        self.window.bind("<FocusOut>", self._on_focus_out)
        
        # Create main frame
        main_frame = tk.Frame(self.window, bg="#0b1a2a")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Title
        title_label = tk.Label(
            main_frame,
            text=f"{_asst} Launcher",
            bg="#0b1a2a",
            fg="#00f5ff",
            font=("Segoe UI", 12, "bold")
        )
        title_label.pack(pady=(0, 10))
        
        # Button frame
        button_frame = tk.Frame(main_frame, bg="#0b1a2a")
        button_frame.pack(fill=tk.BOTH, expand=True)
        
        # 4 Launcher buttons
        buttons = [
            ("Open GUI", self._on_open_gui),
            ("Terminal", self._on_terminal),
            ("Voice Mode", self._on_voice_mode),
            ("Settings", self._on_settings),
        ]
        
        for label, callback in buttons:
            btn = tk.Button(
                button_frame,
                text=label,
                command=callback,
                bg="#112b3c",
                fg="#c8eeff",
                activebackground="#1a3a4c",
                activeforeground="#00f5ff",
                relief=tk.FLAT,
                font=("Segoe UI", 10),
                padx=10,
                pady=8,
                cursor="hand2"
            )
            btn.pack(fill=tk.X, pady=4)
        
        # Start hidden
        self.window.withdraw()
        
        log_debug("Launcher window created")
    
    def _window_exists(self):
        """Check if window still exists."""
        if self.window is None:
            return False
        try:
            self.window.winfo_exists()
            return True
        except:
            return False
    
    def _position_window(self):
        """Position window next to floating button."""
        try:
            button_x = self.button_window.winfo_x()
            button_y = self.button_window.winfo_y()
            button_width = self.button_window.winfo_width()
            
            # Place to the right of button
            x = button_x + button_width + 20
            y = button_y
            
            self.window.geometry(f"+{x}+{y}")
        except:
            pass
    
    def _on_escape(self, event):
        """Handle Escape key."""
        log_debug("Escape pressed")
        self.close()
        return "break"
    
    def _on_focus_out(self, event):
        """Handle focus loss."""
        log_debug("Focus lost")
        # Schedule close to avoid issues during event processing
        self.close_timer = self.root.after(100, self.close)
        return "break"
    
    def _on_open_gui(self):
        """Open GUI button clicked."""
        log_debug("Button clicked: Open GUI")
        self.close()
        
        # Execute in main thread
        self.root.after(0, self._execute_open_gui)
    
    def _execute_open_gui(self):
        """Execute open GUI."""
        try:
            log_debug("Executing: open_gui")
            from modules.launcher.launcher_functions_simple import open_gui
            open_gui()
        except Exception as e:
            log_debug(f"Error: {e}")
    
    def _on_terminal(self):
        """Terminal button clicked."""
        log_debug("Button clicked: Terminal")
        self.close()
        
        # Execute in main thread
        self.root.after(0, self._execute_terminal)
    
    def _execute_terminal(self):
        """Execute terminal."""
        try:
            log_debug("Executing: open_terminal")
            from modules.launcher.launcher_functions_simple import open_terminal
            open_terminal()
        except Exception as e:
            log_debug(f"Error: {e}")
    
    def _on_voice_mode(self):
        """Voice Mode button clicked."""
        log_debug("Button clicked: Voice Mode")
        self.close()
        
        # Execute in main thread
        self.root.after(0, self._execute_voice_mode)
    
    def _execute_voice_mode(self):
        """Execute voice mode."""
        try:
            log_debug("Executing: open_voice_panel")
            from modules.launcher.launcher_functions_simple import open_voice_panel
            open_voice_panel()
        except Exception as e:
            log_debug(f"Error: {e}")
    
    def _on_settings(self):
        """Settings button clicked."""
        log_debug("Button clicked: Settings")
        self.close()
        
        # Execute in main thread
        self.root.after(0, self._execute_settings)
    
    def _execute_settings(self):
        """Execute settings."""
        try:
            log_debug("Executing: open_settings")
            from modules.launcher.launcher_functions_simple import open_settings
            open_settings()
        except Exception as e:
            log_debug(f"Error: {e}")
    
    def destroy(self):
        """Destroy the launcher panel."""
        log_debug("destroy() called")
        
        self.is_visible = False
        
        if self.close_timer:
            self.root.after_cancel(self.close_timer)
            self.close_timer = None
        
        if self.window and self._window_exists():
            try:
                self.window.destroy()
            except:
                pass
        
        self.window = None
        log_debug("Launcher destroyed")
