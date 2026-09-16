"""
Animation utilities for launcher panel.
Provides slide-in animation and timing functions.
"""

import math
import time


class SlideInAnimation:
    """
    Handles slide-in animation for launcher panel.
    Slides in from the side with easing.
    """
    
    def __init__(self, duration_ms=150):
        """
        Initialize animation.
        
        Args:
            duration_ms: Animation duration in milliseconds (150-200ms recommended)
        """
        self.duration_ms = duration_ms
        self.start_time = None
        self.is_active = False
    
    def start(self):
        """Start the animation."""
        self.start_time = time.time()
        self.is_active = True
    
    def get_progress(self):
        """
        Get animation progress (0.0 to 1.0).
        
        Returns:
            float: Progress value, clamped between 0 and 1
        """
        if not self.is_active or self.start_time is None:
            return 0.0
        
        elapsed_ms = (time.time() - self.start_time) * 1000
        progress = elapsed_ms / self.duration_ms
        
        if progress >= 1.0:
            self.is_active = False
            return 1.0
        
        return progress
    
    def get_eased_progress(self):
        """
        Get eased animation progress using ease-out cubic.
        Provides smooth, natural motion.
        
        Returns:
            float: Eased progress value (0.0 to 1.0)
        """
        progress = self.get_progress()
        
        # Ease-out cubic: 1 - (1-x)^3
        eased = 1 - (1 - progress) ** 3
        
        return eased
    
    def is_finished(self):
        """Check if animation is complete."""
        return not self.is_active


class AnimationFrameManager:
    """
    Manages animation frame updates and timing.
    Coordinates redraws with Tkinter event loop.
    """
    
    def __init__(self, parent_widget, target_fps=60):
        """
        Initialize frame manager.
        
        Args:
            parent_widget: Parent Tkinter widget for scheduling callbacks
            target_fps: Target frames per second (default 60)
        """
        self.parent = parent_widget
        self.target_fps = target_fps
        self.frame_time_ms = 1000 // target_fps
        self.animation_id = None
        self.callback = None
    
    def schedule_frame(self, callback):
        """
        Schedule a callback for the next animation frame.
        
        Args:
            callback: Function to call on next frame
        """
        self.callback = callback
        self.animation_id = self.parent.after(self.frame_time_ms, self._frame_tick)
    
    def _frame_tick(self):
        """Internal frame tick handler."""
        if self.callback:
            self.callback()
    
    def cancel(self):
        """Cancel scheduled animation frame."""
        if self.animation_id:
            self.parent.after_cancel(self.animation_id)
            self.animation_id = None


def calculate_panel_position(button_window, button_x, button_y, button_size, 
                              panel_width, panel_height, screen_width, screen_height):
    """
    Calculate optimal position for launcher panel relative to floating button.
    Panel appears on the opposite side from screen edge.
    
    Args:
        button_window: The floating button window object
        button_x: Button x position
        button_y: Button y position
        button_size: Button width/height (assumed square)
        panel_width: Launcher panel width
        panel_height: Launcher panel height
        screen_width: Screen width in pixels
        screen_height: Screen height in pixels
    
    Returns:
        tuple: (x, y) position for panel top-left corner
    """
    # Distance from button to panel
    offset = 20
    
    # Determine horizontal position
    # If button is on the right side, place panel to the left
    mid_screen_x = screen_width / 2
    if button_x > mid_screen_x:
        # Button on right - place panel to the left
        panel_x = button_x - panel_width - offset
    else:
        # Button on left - place panel to the right
        panel_x = button_x + button_size + offset
    
    # Ensure panel doesn't go off-screen horizontally
    if panel_x < 10:
        panel_x = 10
    elif panel_x + panel_width > screen_width - 10:
        panel_x = screen_width - panel_width - 10
    
    # Determine vertical position (center vertically on button)
    panel_y = button_y + (button_size // 2) - (panel_height // 2)
    
    # Ensure panel doesn't go off-screen vertically
    if panel_y < 10:
        panel_y = 10
    elif panel_y + panel_height > screen_height - 10:
        panel_y = screen_height - panel_height - 10
    
    return (panel_x, panel_y)
