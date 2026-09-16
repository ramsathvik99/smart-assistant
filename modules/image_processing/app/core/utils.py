import os
import cv2
import time

def get_desktop_path():
    """Get the actual Desktop path (handles OneDrive Desktop)"""
    onedrive_desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
    if os.path.exists(onedrive_desktop):
        return onedrive_desktop
    return os.path.join(os.path.expanduser("~"), "Desktop")

def auto_save_result(operation_name, image):
    """
    Centralized auto-save logic for NOVA operations.
    Saves image to Desktop with timestamped filename.
    """
    if image is None:
        return None
        
    try:
        # Standard filename: operation_timestamp.jpg
        filename = f"{operation_name}_{int(time.time())}.jpg"
        desktop_path = get_desktop_path()
        
        # Ensure path exists
        if not os.path.exists(desktop_path):
            os.makedirs(desktop_path, exist_ok=True)
            
        save_path = os.path.join(desktop_path, filename)
        
        # Write to disk
        success = cv2.imwrite(save_path, image)
        
        if success:
            return save_path
        return None
    except Exception as e:
        print(f"  [ERROR] Auto-save failed: {e}")
        return None
