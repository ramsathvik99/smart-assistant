import os
import platform
import subprocess
import re

def get_downloads_path():
    """Returns the path to the user's Downloads folder."""
    return os.path.join(os.path.expanduser("~"), "Downloads")

def sanitize_filename(topic):
    """Clean a topic string into a valid, readable filename."""
    if not topic or not topic.strip():
        return "writing_output"
    
    # Simple sanitization
    filename = topic.replace(" ", "_").strip()
    filename = re.sub(r'[^\w\s-]', '', filename)
    
    # Limit to 40 characters as requested
    if len(filename) > 40:
        filename = filename[:40].rstrip('_')
        
    return filename

def save_writing(topic: str, content: str) -> str:
    """Saves writing content to the Downloads folder with a specific format."""
    try:
        downloads_path = get_downloads_path()
        filename = sanitize_filename(topic) + ".txt"
        file_path = os.path.join(downloads_path, filename)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        print(f"[Writer] Saved to: {file_path}")
        
        # Open in Notepad if on Windows (optional, but keep for usability)
        if platform.system().lower() == "windows":
            try:
                subprocess.Popen(["notepad.exe", file_path])
            except:
                pass
                
        return file_path
    except Exception as e:
        print(f"[Writer ERROR] Failed to save writing: {e}")
        return None

def save_and_open_output(content: str, topic: str = "") -> None:
    """Legacy/Fallback function to save and open output."""
    save_writing(topic, content)
