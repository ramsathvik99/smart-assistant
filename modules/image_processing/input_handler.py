import os
import cv2
from tkinter import Tk, filedialog
import re

import string

EXCLUDE_DIRS = [
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "$Recycle.Bin",
    "AppData"
]

FAST_DIRS = [
    ".",
    "modules/image_processing/",
    "uploads/",
    "images/",
    "C:/Users/Ram Sathvik/OneDrive/Desktop/",
    "Downloads/",
    "Desktop/",
    "Documents/"
]

SEARCH_CACHE = {}

def get_all_drives():
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:/"
        if os.path.exists(drive):
            drives.append(drive)
    return drives

def find_image_full_system(filename):
    filename = filename.lower()

    for drive in get_all_drives():
        for root, dirs, files in os.walk(drive):
            # Skip unwanted folders
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in files:
                if file.lower() == filename:
                    return os.path.join(root, file)

    return None

def find_image(filename):
    # Step 1: Fast search
    for directory in FAST_DIRS:
        if os.path.exists(directory):
            for root, _, files in os.walk(directory):
                for f in files:
                    if f.lower() == filename.lower():
                        return os.path.join(root, f)

    print("[INFO] Fast search failed, scanning system...")

    # Step 2: Full system search
    return find_image_full_system(filename)

def find_image_cached(filename):
    if filename in SEARCH_CACHE:
        return SEARCH_CACHE[filename]

    path = find_image(filename)

    if path:
        SEARCH_CACHE[filename] = path

    return path

def capture_from_camera():
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("[ERROR] Camera not accessible")
        return None

    ret, frame = cap.read()
    cap.release()

    if ret:
        path = "captured_image.jpg"
        cv2.imwrite(path, frame)
        print(f"[INFO] Captured: {path}")
        return path

    return None

def open_file_picker():
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True) # ensure it appears on top

    file_path = filedialog.askopenfilename(
        title="Select Image",
        filetypes=[("Image Files", "*.jpg *.jpeg *.png *.bmp")]
    )

    root.destroy()
    return file_path if file_path else None

def extract_filename(command):
    match = re.search(r'([\w\-]+\.(jpg|jpeg|png|bmp))', command.lower())
    return match.group(1) if match else None

def resolve_image(command, fallback_path=None):
    command = command.lower()

    # 📸 Camera case
    if "camera" in command or "capture" in command:
        return capture_from_camera()

    # 🔍 Filename case
    filename = extract_filename(command)
    path = None

    if filename:
        path = find_image_cached(filename)
        if path:
            print(f"[INFO] Found: {path}")
            return path
        else:
            print("[WARN] File not found")

    # 📂 Fallback cases
    if ("select" in command or "choose" in command or "browse" in command) or not filename or not path:
        print("[INFO] Opening file picker...")
        return open_file_picker()

    # fallback to existing path if provided
    return fallback_path
