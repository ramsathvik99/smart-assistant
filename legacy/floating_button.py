
# ════════════════════════════════════════════════════════════════════════
# RETIRED — This file is NOT the active production UI.
# Production: modules/ui/floating_launcher.py (PyQt6)
# This file is preserved for historical reference only.
# ════════════════════════════════════════════════════════════════════════

import os
import sys
import math
import tkinter as tk
from tkinter import Canvas
from datetime import datetime

# Debug logging with timestamps
DEBUG = True
def log_debug(msg):
    if DEBUG:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [FLOATING_BUTTON] {msg}")


class FloatingButton:
    def __init__(self, root, user_data=None, on_double_click_cb=None, 
                 on_launcher_item=None, on_context_menu_cb=None):
        self.root = root # Reference to main Tk root
        self.user_data = user_data
        self.on_double_click_cb = on_double_click_cb
        self.on_launcher_item = on_launcher_item
        self.on_context_menu_cb = on_context_menu_cb
        
        # Create Toplevel for the button
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True) # Frameless
        self.window.attributes("-topmost", True)
        
        # Transparency setup (Windows specific)
        self.window.attributes("-transparentcolor", "#000001")
        self.window.config(bg="#000001")
        
        self.size = 120
        self.width = self.size
        self.height = self.size
        
        # Center on screen
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        x = (screen_width // 2) - (self.size // 2)
        y = (screen_height // 2) - (self.size // 2)
        self.window.geometry(f"{self.size}x{self.size}+{x}+{y}")
        
        # Canvas
        self.canvas = Canvas(
            self.window, 
            width=self.size, 
            height=self.size, 
            bg="#000001", 
            highlightthickness=0
        )
        self.canvas.pack()
        
        # State
        self.arc_active = False
        self.hover_active = False
        self.angle_1 = 0
        self.angle_2 = 180
        self.pulse_val = 0.0
        
        # Dragging state
        self._drag_data = {"x": 0, "y": 0}
        self._is_dragging = False
        
        # Launcher panel (lazy loaded)
        self.launcher_panel = None
        self.context_menu = None
        
        # Bindings
        self.canvas.bind("<Button-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.do_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<Enter>", self.on_enter)
        self.canvas.bind("<Leave>", self.on_leave)
        
        # Initial draw
        self.draw()

    def start_drag(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
        self._is_dragging = False  # Will be set to True if motion happens

    def do_drag(self, event):
        # Threshold to distinguish drag from click
        dx = abs(event.x - self._drag_data["x"])
        dy = abs(event.y - self._drag_data["y"])
        
        if dx > 5 or dy > 5:
            self._is_dragging = True
            x = self.window.winfo_x() - self._drag_data["x"] + event.x
            y = self.window.winfo_y() - self._drag_data["y"] + event.y
            self.window.geometry(f"+{x}+{y}")

    def on_button_release(self, event):
        """Handle button release - distinguish between click and drag."""
        self._is_dragging = False

    def on_double_click(self, event):
        """Handle double-click - toggle launcher panel (open/close)."""
        log_debug("Double-click detected")
        
        if self.launcher_panel is None:
            # First time - create launcher panel
            log_debug("Creating launcher panel for first time")
            self._create_launcher_panel()
        
        # Toggle the panel
        log_debug("Toggling launcher panel")
        self.launcher_panel.toggle()

    def _create_launcher_panel(self):
        """Initialize and create launcher panel (non-blocking)."""
        log_debug("Creating launcher panel")
        
        try:
            from modules.launcher.launcher_panel_stable import LauncherPanel
            
            # Create fresh panel
            self.launcher_panel = LauncherPanel(self.root, self.window)
            log_debug("Launcher panel created successfully")
        except ImportError as e:
            log_debug(f"Failed to load launcher: {e}")
            # Fallback to old behavior
            if self.on_double_click_cb:
                log_debug("Double-click: Launching main UI (fallback)...")
                self.root.after(0, lambda: self._safe_callback(self.on_double_click_cb))

    def _safe_callback(self, callback, *args):
        """
        Execute callback safely with exception handling.
        
        Protects main thread from any blocking or error-prone callbacks.
        """
        try:
            log_debug(f"Executing callback: {callback.__name__} with args {args}")
            if args:
                callback(*args)
            else:
                callback()
            log_debug(f"Callback completed: {callback.__name__}")
        except Exception as e:
            log_debug(f"ERROR in callback {callback.__name__}: {e}")
            import traceback
            traceback.print_exc()

    def on_right_click(self, event):
        """Handle right-click - show context menu."""
        log_debug("Right-click detected")
        self._show_context_menu(event)

    def _show_context_menu(self, event):
        """Initialize and show context menu (non-blocking)."""
        log_debug("Initializing context menu")
        
        if self.context_menu is None:
            # Lazy load context menu
            try:
                from modules.launcher.system_menu import AssistantSystemMenu
                
                # Create system menu (it will route to launcher functions)
                self.context_menu = AssistantSystemMenu(self.root, self.window)
                log_debug("System menu created")
            except ImportError as e:
                log_debug(f"Failed to load system menu: {e}")
                return
        
        # Show the menu
        self.context_menu.show(event)
        log_debug("System menu shown")

    def open_main_gui(self, event=None):
        """Deprecated: Use launcher panel instead."""
        log_debug("open_main_gui called (deprecated, use launcher panel)")
        if self.on_double_click_cb:
            self.root.after(0, lambda: self._safe_callback(self.on_double_click_cb))
        else:
            log_debug("Double-click detected (No callback set)")

    def on_enter(self, event):
        self.hover_active = True
        self.draw()

    def on_leave(self, event):
        self.hover_active = False
        self.draw()

    # --- Animation ---
    def start_anim(self):
        if not self.arc_active:
            self.arc_active = True
            self.animate()

    def stop_anim(self):
        self.arc_active = False
        # One last draw to reset state
        self.root.after(50, self.draw)

    def animate(self):
        if not self.arc_active:
            return
            
        self.angle_1 = (self.angle_1 - 8) % 360
        self.angle_2 = (self.angle_2 + 12) % 360
        self.pulse_val += 0.2
        
        self.draw()
        
        # Schedule next frame (~30 FPS)
        self.root.after(30, self.animate)

    # --- Drawing ---
    def draw(self):
        self.canvas.delete("all")
        
        cx, cy = self.size / 2, self.size / 2
        
        # Scaling effect
        scale = 1.0
        if self.arc_active:
            scale += math.sin(self.pulse_val) * 0.05
            
        # Draw Glow (simulated with multiple semi-transparent circles if needed, 
        # but Tkinter doesn't do alpha blending well on canvas items usually)
        # Using a simpler outline for glow or just skipping distinct gradient glow
        # Tkinter Canvas limitation: precise gradients/alpha tricky.
        # We'll use style approximations.
        
        # Arcs
        if self.arc_active:
            r1 = 45 * scale
            self.canvas.create_arc(
                cx-r1, cy-r1, cx+r1, cy+r1,
                start=self.angle_1, extent=100,
                style=tk.ARC, outline="#6366f1", width=3
            )
            
            r2 = 38 * scale
            self.canvas.create_arc(
                cx-r2, cy-r2, cx+r2, cy+r2,
                start=self.angle_2, extent=120,
                style=tk.ARC, outline="#22d3ee", width=2
            )

        # Main Bubble
        r = 32 * scale
        
        fill_color = "#000000" # Black bg 
        outline_color = "#6366f1"
        width = 2
        
        if self.hover_active or self.arc_active:
            # "Active" state
            pass 
        else:
            # "Inactive" state - dim
            outline_color = "#404040"
            width = 1

        # Draw circle background (opaque)
        # We use a distinct color (e.g. #1e1e2e) that isn't the transparent key
        bubble_bg = "#1e1e2e" 
        self.canvas.create_oval(
            cx-r, cy-r, cx+r, cy+r,
            fill=bubble_bg, outline=outline_color, width=width
        )
        
        # Text "N"
        font_color = "white" if (self.hover_active or self.arc_active) else "gray"
        self.canvas.create_text(
            cx, cy,
            text="N",
            font=("Segoe UI", 18, "bold"),
            fill=font_color
        )
