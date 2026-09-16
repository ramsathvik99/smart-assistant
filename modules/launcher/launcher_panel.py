"""
Launcher panel for NOVA floating button.
Compact, modern launcher with rounded corners and slide-in animation.

CRITICAL REQUIREMENTS FOR NON-BLOCKING OPERATION:
- All operations must run in the main Tkinter event loop
- No mainloop() calls
- No time.sleep() calls
- No blocking focus operations or wait_window() calls
- Use after() for all delays
- Single Tk root instance only
- All callbacks must be non-blocking
- Heavy work must be delegated to daemon threads
- Thread-safe UI updates via root.after()
"""

import tkinter as tk
from tkinter import Canvas
import math
import threading
from datetime import datetime
from modules.launcher.animation import SlideInAnimation, calculate_panel_position

# Debug logging with timestamps
DEBUG = True
def log_debug(msg):
    if DEBUG:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [LAUNCHER_PANEL] {msg}")


class RoundedButton:
    """
    Reusable rounded button component for launcher items.
    """
    
    def __init__(self, canvas, x, y, width, height, text, command=None,
                 bg_color="#2a2a3e", fg_color="white", hover_bg="#3a3a50"):
        """
        Create a rounded button on canvas.
        
        Args:
            canvas: Parent canvas
            x, y: Button position
            width, height: Button dimensions
            text: Button label
            command: Callback function on click
            bg_color: Background color
            fg_color: Text color
            hover_bg: Hover state background color
        """
        self.canvas = canvas
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.text = text
        self.command = command
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.hover_bg = hover_bg
        self.is_hover = False
        self.rect_id = None
        self.text_id = None
        self.is_enabled = True
        
        # Create tag BEFORE draw()
        self.tag = f"btn_{id(self)}"
        
        self.draw()
        
        # Bind mouse events
        self.canvas.tag_bind(self.tag, "<Enter>", self._on_enter)
        self.canvas.tag_bind(self.tag, "<Leave>", self._on_leave)
        self.canvas.tag_bind(self.tag, "<Button-1>", self._on_click)
    
    def draw(self):
        """Draw the button on canvas."""
        # Choose color based on state
        color = self.hover_bg if self.is_hover else self.bg_color
        
        # Create rounded rectangle using polygon approximation
        # For simplicity, use a filled rectangle with oval corners overlay
        radius = 4
        
        # Draw main rectangle
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        
        # Simplified: use rectangle with tag for hit detection
        self.rect_id = self.canvas.create_rectangle(
            self.x, self.y,
            self.x + self.width, self.y + self.height,
            fill=color, outline="#4a4a60", width=1,
            tags=(self.tag,)
        )
        
        # Draw text
        if self.text_id:
            self.canvas.delete(self.text_id)
        
        text_color = self.fg_color if self.is_enabled else "#888888"
        self.text_id = self.canvas.create_text(
            self.x + self.width // 2,
            self.y + self.height // 2,
            text=self.text,
            font=("Segoe UI", 10, "normal"),
            fill=text_color,
            tags=(self.tag,)
        )
    
    def _on_enter(self, event=None):
        """Mouse enter event."""
        if self.is_enabled:
            self.is_hover = True
            self.draw()
    
    def _on_leave(self, event=None):
        """Mouse leave event."""
        self.is_hover = False
        self.draw()
    
    def _on_click(self, event=None):
        """Mouse click event (non-blocking)."""
        if self.is_enabled and self.command:
            # Schedule callback on main thread to prevent blocking
            self.canvas.winfo_toplevel().after(0, self.command)
    
    def set_enabled(self, enabled):
        """Enable or disable button."""
        self.is_enabled = enabled
        self.draw()


class LauncherPanel:
    """
    Compact launcher panel for NOVA floating button.
    
    CRITICAL DESIGN: This is a NON-BLOCKING popup that runs in the main
    Tkinter event loop. It mimics Windows popup menu behavior.
    
    Features:
    - Borderless Tkinter Toplevel window (not a separate app)
    - Dark modern theme with instant open/close
    - Slide-in animation (via after(), not blocking)
    - Toggle behavior (double-click to open/close)
    - Auto-close on outside click or focus loss
    - No mainloop() - uses parent root's event loop
    """
    
    def __init__(self, root, button_window, on_item_selected=None):
        """
        Initialize launcher panel.
        
        Args:
            root: Tk root window (MUST be the only Tk instance)
            button_window: The floating button Toplevel window
            on_item_selected: Callback when an item is selected (item_id)
        """
        log_debug("Initializing launcher panel")
        
        self.root = root
        self.button_window = button_window
        self.on_item_selected = on_item_selected
        self.window = None
        self.canvas = None
        self.animation = SlideInAnimation(duration_ms=150)
        self.is_visible = False
        self.animation_frame_id = None
        self.outside_click_id = None
        self.buttons = []
        
        # UI dimensions
        self.panel_width = 220
        self.item_height = 36
        self.padding = 10
        
        # Initialize launcher items with all 7 buttons
        self._initialize_items()
        
        # Calculate panel height based on items
        self.panel_height = len(self.items) * self.item_height + (2 * self.padding)
        
        # Target and current position
        self.target_x = 0
        self.target_y = 0
        self.start_x = 0
        
        # Create window (not shown yet)
        self._create_window()
        log_debug("Panel initialized (window hidden)")
    
    def _initialize_items(self):
        """Initialize launcher panel items with all 7 buttons."""
        try:
            from instance.config import settings as _cfg
            _asst = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            _asst = "Assistant"

        # Items: (icon, label, item_id)
        self.items = [
            ("🎨", f"Open {_asst} GUI", "open_gui"),
            ("💻", "Terminal", "open_terminal"),
            ("🎙️", "Voice Mode", "open_voice_panel"),
            ("⚙️", "Settings", "open_settings"),
            ("🔄", "Reload Modules", "reload_modules"),
            ("ℹ️", "Status", "show_assistant_status"),
            ("🚀", "Quick Launch", "quick_launch"),
        ]
    
    def _create_window(self):
        """Create the launcher panel window (initially hidden)."""
        self.window = tk.Toplevel(self.root)
        self.window.overrideredirect(True)  # Frameless
        self.window.attributes("-topmost", True)
        self.window.attributes("-transparentcolor", "#000001")
        self.window.withdraw()  # Start hidden
        
        # Set initial geometry (will be positioned on show)
        self.window.geometry(f"{self.panel_width}x{self.panel_height}+0+0")
        
        # Create canvas for drawing
        self.canvas = Canvas(
            self.window,
            width=self.panel_width,
            height=self.panel_height,
            bg="#1a1a2e",
            highlightthickness=0,
            bd=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # Draw border/frame effect
        self.canvas.create_rectangle(
            0, 0,
            self.panel_width - 1, self.panel_height - 1,
            fill=None, outline="#6366f1", width=1
        )
        
        # Bind events - NON-BLOCKING
        # Escape key to close
        self.window.bind("<Escape>", self._on_escape, add=True)
        
        # Focus out - try to detect but don't block
        self.window.bind("<FocusOut>", self._on_focus_out_event, add=True)
        
        # Canvas mouse events for detecting outside clicks
        self.canvas.bind("<Button-1>", self._on_canvas_click, add=True)
        
        # Draw launcher items
        self._draw_items()
    
    def _draw_items(self):
        """Draw launcher menu items."""
        y_offset = self.padding
        
        for i, (icon, label, item_id) in enumerate(self.items):
            x = self.padding
            y = y_offset + (i * self.item_height)
            
            # Create callback for this item
            callback = lambda iid=item_id: self._on_item_selected(iid)
            
            # Create button
            item_text = f"{icon}  {label}"
            btn = RoundedButton(
                self.canvas, x, y,
                self.panel_width - (2 * self.padding), self.item_height - 4,
                item_text, command=callback,
                bg_color="#2a2a3e" if i % 2 == 0 else "#252540",
                fg_color="white"
            )
            
            self.buttons.append(btn)
    
    def show(self):
        """
        Show the launcher panel with slide-in animation.
        
        NON-BLOCKING: Uses after() for animation, returns immediately.
        """
        # Check if window was destroyed and needs recreation
        if self.window is None:
            log_debug("Window is None, recreating window before show")
            self._create_window()
        
        if self.is_visible:
            log_debug("Panel already visible, ignoring show request")
            return
        
        log_debug("Opening launcher panel")
        
        # Get button position
        button_x = self.button_window.winfo_x()
        button_y = self.button_window.winfo_y()
        button_size = 120  # From FloatingButton.size
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Calculate optimal position
        panel_x, panel_y = calculate_panel_position(
            self.button_window, button_x, button_y, button_size,
            self.panel_width, self.panel_height,
            screen_width, screen_height
        )
        
        # Store target position
        self.target_x = panel_x
        self.target_y = panel_y
        
        # Calculate start position for slide-in animation
        if panel_x < button_x:
            # Panel will appear to left - slide from further left
            self.start_x = panel_x - 50
        else:
            # Panel will appear to right - slide from further right
            self.start_x = panel_x + 50
        
        # Set initial geometry
        self.window.geometry(
            f"{self.panel_width}x{self.panel_height}+{int(self.start_x)}+{int(panel_y)}"
        )
        
        # Make visible and bring to front
        self.window.deiconify()
        self.window.lift()
        
        # Try to focus (won't block even if it fails)
        try:
            self.window.focus_force()
        except:
            pass
        
        # Mark as visible
        self.is_visible = True
        
        # Start animation
        self.animation.start()
        self._animate_frame()
        
        # Set up outside click detection (non-blocking)
        # Check periodically if user clicked outside
        self._monitor_outside_click()
        
        log_debug(f"Panel opened at ({panel_x}, {panel_y})")
    
    def _animate_frame(self):
        """
        Animation frame update (non-blocking).
        
        Uses after() to schedule next frame - never blocks event loop.
        """
        if not self.is_visible:
            return
        
        progress = self.animation.get_eased_progress()
        
        if progress < 1.0:
            # Smooth slide-in animation
            current_x = self.start_x + (self.target_x - self.start_x) * progress
            try:
                self.window.geometry(
                    f"{self.panel_width}x{self.panel_height}+{int(current_x)}+{int(self.target_y)}"
                )
            except:
                # Silently ignore if window is being destroyed
                pass
            
            # Schedule next frame (~60 FPS)
            self.animation_frame_id = self.root.after(16, self._animate_frame)
        else:
            # Animation complete
            try:
                self.window.geometry(
                    f"{self.panel_width}x{self.panel_height}+{int(self.target_x)}+{int(self.target_y)}"
                )
            except:
                pass
            self.animation_frame_id = None
    
    def hide(self):
        """
        Hide the launcher panel.
        
        NON-BLOCKING: Destroys window to free resources.
        """
        if not self.is_visible:
            return
        
        log_debug("Closing launcher panel")
        
        self.is_visible = False
        
        # Cancel animation
        if self.animation_frame_id:
            self.root.after_cancel(self.animation_frame_id)
            self.animation_frame_id = None
        
        # Cancel outside click monitoring
        if self.outside_click_id:
            self.root.after_cancel(self.outside_click_id)
            self.outside_click_id = None
        
        # Destroy the window to free resources
        if self.window:
            try:
                self.window.destroy()
            except:
                pass
            self.window = None
        
        log_debug("Panel destroyed")
    
    def close(self):
        """Alias for hide() - for compatibility."""
        self.hide()
    
    def is_destroyed(self):
        """
        Check if the launcher panel window has been destroyed.
        
        Returns True if the window doesn't exist or has been destroyed.
        """
        if self.window is None:
            return True
        
        try:
            # Try to access a property - will fail if window is destroyed
            self.window.winfo_exists()
            return False
        except:
            return True
    
    def toggle(self):
        """
        Toggle panel visibility.
        
        This is the main entry point from double-click.
        Handles both closed and destroyed panels.
        """
        # Check if window was destroyed
        if self.is_destroyed():
            log_debug("Panel was destroyed, recreating window")
            # Recreate the window
            self._create_window()
            # Show the new window
            self.show()
        elif self.is_visible:
            # Panel is visible - close it
            self.hide()
        else:
            # Panel exists but is hidden - show it
            self.show()
    
    def _on_escape(self, event):
        """Handle Escape key - close panel."""
        log_debug("Escape pressed, closing panel")
        self.hide()
        return "break"  # Consume event
    
    def _on_focus_out_event(self, event):
        """
        Handle focus out event (non-blocking).
        
        Don't close immediately - check if focus is truly lost.
        """
        # Schedule a check later instead of doing it immediately
        self.root.after(100, self._check_if_should_close)
        return "break"
    
    def _check_if_should_close(self):
        """
        Check if we should close based on focus state.
        
        This is called asynchronously and doesn't block.
        """
        if not self.is_visible or not self.window:
            return
        
        # Check if any widget in panel has focus
        try:
            focus_widget = self.root.focus_get()
            if focus_widget and focus_widget not in [self.window, self.canvas]:
                # Focus moved elsewhere
                log_debug("Focus moved away, closing panel")
                self.hide()
        except:
            # Error checking focus - ignore
            pass
    
    def _on_canvas_click(self, event):
        """Handle clicks on canvas (menu item selections)."""
        # This is handled by RoundedButton callbacks
        return "break"
    
    def _monitor_outside_click(self):
        """
        Monitor for clicks outside the panel (non-blocking).
        
        Check periodically without blocking the event loop.
        """
        if not self.is_visible or not self.window:
            return
        
        try:
            # Get mouse position
            root_x = self.root.winfo_pointerx()
            root_y = self.root.winfo_pointery()
            
            # Get panel position
            panel_x = self.window.winfo_x()
            panel_y = self.window.winfo_y()
            panel_right = panel_x + self.panel_width
            panel_bottom = panel_y + self.panel_height
            
            # Check if mouse is outside panel
            if root_x < panel_x or root_x > panel_right or \
               root_y < panel_y or root_y > panel_bottom:
                # Mouse is outside - but don't close yet, just monitor
                pass
        except:
            # Error getting positions - ignore
            pass
        
        # Schedule next check (non-blocking)
        if self.is_visible:
            self.outside_click_id = self.root.after(250, self._monitor_outside_click)
    
    def _on_item_selected(self, item_id):
        """
        Handle launcher item selection (NON-BLOCKING).
        
        Args:
            item_id: The launcher item ID (e.g., 'open_gui', 'open_terminal')
        """
        log_debug(f"Launcher item selected: {item_id}")
        
        # Close launcher immediately
        self.hide()
        
        # Execute the item callback on main thread
        if self.on_item_selected:
            self.root.after(0, lambda: self._safe_callback(item_id))
    
    def _safe_callback(self, item_id):
        """
        Execute callback safely with exception handling.
        
        Protects main thread from any blocking or error-prone callbacks.
        If callback does heavy work, it must start a daemon thread.
        """
        try:
            log_debug(f"Executing callback for {item_id}")
            if self.on_item_selected:
                self.on_item_selected(item_id)
        except Exception as e:
            log_debug(f"ERROR in callback for {item_id}: {e}")
            import traceback
            traceback.print_exc()
    
    # ===== Legacy Callback Methods (For Compatibility) =====
    
    def _on_open_gui(self):
        """Open NOVA GUI - calls the main callback. NON-BLOCKING."""
        log_debug("Opening NOVA GUI (callback scheduled)")
        self.hide()
        # Schedule callback on main thread
        if self.on_item_selected:
            self.root.after(0, lambda: self._safe_callback("open_gui"))
    
    def _on_terminal(self):
        """Open Terminal - placeholder. NON-BLOCKING."""
        log_debug("Terminal selected (callback scheduled)")
        self.hide()
        if self.on_item_selected:
            self.root.after(0, lambda: self._safe_callback("terminal"))
    
    def _on_voice_mode(self):
        """Voice Mode - placeholder. NON-BLOCKING."""
        log_debug("Voice Mode selected (callback scheduled)")
        self.hide()
        if self.on_item_selected:
            self.root.after(0, lambda: self._safe_callback("voice_mode"))
    
    def _on_translator(self):
        """Translator - placeholder. NON-BLOCKING."""
        log_debug("Translator selected (callback scheduled)")
        self.hide()
        if self.on_item_selected:
            self.root.after(0, lambda: self._safe_callback("translator"))
    
    def _on_image_tools(self):
        """Image Tools - placeholder. NON-BLOCKING."""
        log_debug("Image Tools selected (callback scheduled)")
        self.hide()
        if self.on_item_selected:
            self.root.after(0, lambda: self._safe_callback("image_tools"))
    
    def _on_settings(self):
        """Settings - placeholder. NON-BLOCKING."""
        log_debug("Settings selected (callback scheduled)")
        self.hide()
        if self.on_item_selected:
            self.root.after(0, lambda: self._safe_callback("settings"))
