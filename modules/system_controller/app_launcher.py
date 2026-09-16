"""
Application Launcher for Nova System Controller
Handles launching system applications
"""

import subprocess
import platform
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Common safe applications that can be launched
SAFE_APPLICATIONS = {
    "windows": [
        "notepad.exe",
        "calc.exe", 
        "mspaint.exe",
        "explorer.exe",
        "cmd.exe",
        "powershell.exe",
        "write.exe",  # WordPad
        "winword.exe",  # Microsoft Word
        "excel.exe",   # Microsoft Excel
        "powerpnt.exe",  # Microsoft PowerPoint
        "chrome.exe",
        "firefox.exe",
        "edge.exe",
        "code.exe",  # VS Code
        "spotify.exe",
        "vlc.exe"
    ],
    "darwin": [  # macOS
        "TextEdit",
        "Calculator",
        "Preview",
        "Safari",
        "Chrome",
        "Firefox",
        "Spotify",
        "VLC",
        "Visual Studio Code"
    ],
    "linux": [
        "gedit",
        "gnome-calculator",
        "firefox",
        "chrome",
        "code",
        "spotify",
        "vlc",
        "nautilus"
    ]
}

def is_safe_application(app_name):
    """Check if application is in the safe list"""
    system = platform.system().lower()
    
    if system == "windows":
        safe_apps = SAFE_APPLICATIONS["windows"]
    elif system == "darwin":
        safe_apps = SAFE_APPLICATIONS["darwin"] 
    else:
        safe_apps = SAFE_APPLICATIONS["linux"]
    
    # Check exact match or partial match for safety
    app_lower = app_name.lower()
    return any(safe_app.lower() in app_lower for safe_app in safe_apps)

def find_application_path(app_name):
    """
    Find the full path of an application
    
    Args:
        app_name (str): Name of the application
    
    Returns:
        str: Full path to application or None if not found
    """
    system = platform.system()
    
    if system == "Windows":
        # Check common Windows paths
        common_paths = [
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), app_name),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), app_name),
            os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local")), app_name),
            os.path.join(os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming")), app_name)
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        # Try to find in PATH
        try:
            result = subprocess.run(["where", app_name], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except:
            pass
    
    elif system == "Darwin":
        # Check common macOS paths
        common_paths = [
            f"/Applications/{app_name}.app",
            f"/Applications/{app_name}.app/Contents/MacOS/{app_name}"
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
    
    else:  # Linux
        # Try to find in PATH
        try:
            result = subprocess.run(["which", app_name], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
    
    return None

def launch_application(app_name, args=None):
    """
    Launch an application
    
    Args:
        app_name (str): Name or path of the application to launch
        args (list): Additional arguments for the application
    
    Returns:
        str: Success message or error
    """
    try:
        # Safety check
        if not is_safe_application(app_name):
            logger.warning(f"Unsafe application launch attempted: {app_name}")
            return f"Error: Application '{app_name}' is not in the safe list."
        
        system = platform.system()
        
        if args is None:
            args = []
        
        if system == "Windows":
            # Try to find the application path
            app_path = find_application_path(app_name)
            if app_path:
                subprocess.Popen([app_path] + args)
            else:
                # Try launching directly
                subprocess.Popen([app_name] + args)
        
        elif system == "Darwin":  # macOS
            subprocess.call(["open", "-a", app_name] + args)
        
        else:  # Linux
            subprocess.Popen([app_name] + args)
        
        logger.info(f"Application launched: {app_name}")
        return f"{app_name} launched successfully."
        
    except Exception as e:
        logger.error(f"Failed to launch application '{app_name}': {str(e)}")
        return f"Error launching application: {str(e)}"

def get_running_applications():
    """
    Get list of running applications (limited implementation)
    
    Returns:
        list: List of running application names
    """
    try:
        system = platform.system()
        
        if system == "Windows":
            # Use tasklist to get running processes
            result = subprocess.run(["tasklist", "/fo", "csv"], capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                apps = []
                for line in lines[:20]:  # Limit to first 20
                    if line.strip():
                        parts = line.split(',')
                        if len(parts) > 0:
                            app_name = parts[0].strip('"')
                            if app_name and not app_name.endswith('.exe'):
                                app_name += '.exe'
                            apps.append(app_name)
                return apps
        
        return []
        
    except Exception as e:
        logger.error(f"Failed to get running applications: {str(e)}")
        return []
