import os
import re
import sys
import cv2
import numpy as np
from pathlib import Path
from tkinter import Tk, filedialog

# Add the current directory (modules/image_processing) to sys.path 
# so we can import 'app' and its services correctly.
DIP_ROOT = Path(__file__).parent.resolve()
if str(DIP_ROOT) not in sys.path:
    sys.path.append(str(DIP_ROOT))

# --- DIRECTORY UTILS --- 
def get_search_directories():
    """Returns a list of common image directories to search."""
    home = os.path.expanduser("~")
    dirs = [
        os.getcwd(), # Project Root
        os.path.join(home, "Downloads"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "OneDrive", "Desktop"),
        os.path.join(home, "Pictures")
    ]
    # Filter only existing ones
    return [d for d in dirs if os.path.exists(d)]

# --- INPUT METHOD HELPERS ---
def capture_screenshot_to_file():
    """Captures screenshot and returns the file path."""
    from app.services.capture import capture_screenshot
    img = capture_screenshot()
    if isinstance(img, np.ndarray):
        temp_path = os.path.join(os.path.expanduser("~"), "last_screenshot.png")
        cv2.imwrite(temp_path, img)
        return temp_path
    return None

def capture_camera_to_file():
    """Captures camera frame and returns the file path."""
    from app.services.capture import capture_camera
    img = capture_camera()
    if isinstance(img, np.ndarray):
        temp_path = os.path.join(os.path.expanduser("~"), "last_camera.png")
        cv2.imwrite(temp_path, img)
        return temp_path
    return None

def open_manual_picker():
    """Opens tkinter file picker and returns the path."""
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    try:
        from instance.config import settings as _cfg
        _asst = _cfg.get_assistant_name() or "Assistant"
    except Exception:
        _asst = "Assistant"
    file_path = filedialog.askopenfilename(
        title=f"{_asst} — Select an Image File",
        filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp")]
    )
    root.destroy()
    return file_path if file_path else None

# --- MAIN RESOLVER ---
def resolve_image_input(command):
    """
    Intelligent Image Input Resolution System.
    Follows Priority: Screenshot -> Camera -> Search -> Manual Fallback.
    """
    cmd = command.lower().strip()
    resolved_path = None
    input_type = "unknown"
    fallback_steps = []

    # 1. PRIORITY 1: SCREENSHOT (Explicit request)
    screenshot_keywords = ["screenshot", "screen", "capture screen"]
    if any(kw in cmd for kw in screenshot_keywords):
        input_type = "screenshot"
        resolved_path = capture_screenshot_to_file()
        if resolved_path:
            print(f"[RESOLVER] Input Type: SCREENSHOT | Path: {resolved_path}")
            return resolved_path
        fallback_steps.append("Screenshot capture failed")

    # 2. PRIORITY 2: CAMERA (Explicit request)
    camera_keywords = ["camera", "photo", "take a picture", "take a photo", "capture photo"]
    if any(kw in cmd for kw in camera_keywords):
        input_type = "camera"
        resolved_path = capture_camera_to_file()
        if resolved_path:
            print(f"[RESOLVER] Input Type: CAMERA | Path: {resolved_path}")
            return resolved_path
        fallback_steps.append("Camera capture failed")

    # 3. PRIORITY 3: FILE NAME SEARCH (Automatic)
    file_regex = r'\b[\w\-.]+\.(?:jpg|jpeg|png)\b'
    file_matches = re.findall(file_regex, cmd)
    if file_matches:
        filename = file_matches[0]
        input_type = f"file_search ({filename})"
        print(f"[RESOLVER] Detected Filename: {filename}. Searching system...")
        
        for search_dir in get_search_directories():
            potential_path = os.path.join(search_dir, filename)
            if os.path.exists(potential_path):
                print(f"[RESOLVER] Input Type: FILE_SEARCH | Found at: {potential_path}")
                return potential_path
        
        fallback_steps.append(f"File '{filename}' not found in common directories")

    # 4. PRIORITY 4: MANUAL FOLDER SELECTION (Last Resort)
    print("[RESOLVER] No automated source found. Falling back to MANUAL PICKER.")
    input_type = "manual"
    resolved_path = open_manual_picker()
    
    if resolved_path:
        print(f"[RESOLVER] Input Type: MANUAL | Path: {resolved_path}")
        return resolved_path
    
    # FINAL FAILURE
    fallback_steps.append("Manual selection cancelled by user")
    print(f"[RESOLVER] FAILED to resolve image input. Steps: {fallback_steps}")
    return None
