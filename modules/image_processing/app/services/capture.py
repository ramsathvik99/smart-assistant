import cv2
import numpy as np
import os
from datetime import datetime
import time

from .logger import get_logger

logger = get_logger("assistant.capture")

def get_desktop_path():
    """Get actual Desktop path (handles OneDrive Desktop)"""
    # Try OneDrive Desktop first (common in Windows)
    onedrive_desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
    
    if os.path.exists(onedrive_desktop):
        return onedrive_desktop
    
    # Fallback to normal Desktop
    return os.path.join(os.path.expanduser("~"), "Desktop")

def capture_screenshot():
    """
    Capture screenshot using system methods
    Returns screenshot image path
    """
    try:
        # Take screenshot
        try:
            import pyautogui
            screenshot = pyautogui.screenshot()
            # Convert PIL image to numpy array (RGB to BGR for OpenCV)
            img = np.array(screenshot)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            return img
            
        except ImportError:
            pass
        
        # Fallback: try mss
        try:
            import mss
            import mss.tools
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # Primary monitor
                screenshot = sct.grab(monitor)
                
                # Convert to numpy array
                img = np.array(screenshot)
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                return img
                
        except ImportError:
            logger.warning("screenshot_dependency_missing")
            return "Error: No screenshot library available. Install with: pip install pyautogui mss"
            
    except Exception as e:
        logger.error(f"screenshot_capture_error error={e}")
        return f"Error during screenshot capture: {str(e)}"

def capture_camera(max_attempts=3, camera_indices=(0, 1)):
    """
    Capture image from camera
    Returns camera image path
    """
    last_error = None
    for attempt in range(max_attempts):
        for index in camera_indices:
            cap = None
            try:
                cap = cv2.VideoCapture(index)
                if not cap.isOpened():
                    last_error = f"camera_open_failed index={index}"
                    continue

                ret, frame = cap.read()
                if not ret or frame is None:
                    last_error = f"camera_read_failed index={index}"
                    continue

                logger.info(f"camera_captured attempt={attempt} index={index}")
                return frame
            except Exception as exc:
                last_error = str(exc)
                logger.warning(f"camera_attempt_error attempt={attempt} index={index} error={exc}")
            finally:
                if cap is not None:
                    cap.release()
        time.sleep(0.25)

    logger.error(f"camera_capture_failed error={last_error}")
    return f"Error: Could not capture from camera after retries ({last_error})"
