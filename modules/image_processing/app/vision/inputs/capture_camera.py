import cv2
import os
import time
from datetime import datetime

def get_desktop_path():
    onedrive_desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
    if os.path.exists(onedrive_desktop):
        return onedrive_desktop
    return os.path.join(os.path.expanduser("~"), "Desktop")

class CaptureCamera:
    def execute(self, context):
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            # Try index 1 if 0 fails
            cap = cv2.VideoCapture(1)
            if not cap.isOpened():
                return "Error: Could not open camera."
        
        print("Capturing image... please hold still")
        
        # Allow camera to adjust exposure
        time.sleep(2)
        
        captured_frame = None
        # Read multiple frames to stabilize
        for _ in range(20):
            ret, temp = cap.read()
            if ret:
                captured_frame = temp
                
        cap.release()
        
        if captured_frame is None:
            return "Failed to capture image"
            
        # Apply automatic enhancement (CLAHE on L channel)
        lab = cv2.cvtColor(captured_frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        enhanced_lab = cv2.merge((cl, a, b))
        enhanced_frame = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
        
        context.image = enhanced_frame
        
        return "Image captured successfully. What do you want to do next?"
