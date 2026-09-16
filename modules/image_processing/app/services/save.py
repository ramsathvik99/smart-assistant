import cv2
import os
from datetime import datetime

def get_desktop_path():
    """Get the actual Desktop path (handles OneDrive Desktop)"""
    onedrive_desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
    if os.path.exists(onedrive_desktop):
        return onedrive_desktop
    return os.path.join(os.path.expanduser("~"), "Desktop")

class SaveImage:
    def execute(self, context):
        image = getattr(context, 'image', None)
        if image is None:
            return "Error: No image in memory to save."
            
        print("\n💾 Save Image to Desktop")
        
        # Suggest a default filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"assistant_output_{timestamp}.jpg"
        
        filename = input(f"  Enter filename (default: {default_name}): ").strip()
        if not filename:
            filename = default_name
            
        # Ensure it has an extension
        if not os.path.splitext(filename)[1]:
            filename += ".jpg"
            
        desktop_path = get_desktop_path()
        os.makedirs(desktop_path, exist_ok=True)
        save_path = os.path.join(desktop_path, filename)
        
        try:
            success = cv2.imwrite(save_path, image)
            if success:
                return f"Image successfully saved to: {save_path}"
            else:
                return f"Error: Failed to write image to {save_path}"
        except Exception as e:
            return f"Error during save: {str(e)}"
