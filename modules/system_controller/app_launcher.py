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


def discover_installed_games() -> list[dict]:
    """
    Discover installed PC games across Steam libraries and Epic Games manifests.
    Returns list of dicts with name, app_id, launcher ('steam'/'epic'), and install path.
    """
    games = []
    
    # 1. Scan Steam Games
    try:
        steam_paths = [
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
            os.path.expanduser(r"~\AppData\Local\Steam")
        ]
        
        # Check Windows registry if available
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                val, _ = winreg.QueryValueEx(key, "SteamPath")
                if val and os.path.exists(val):
                    steam_paths.insert(0, val.replace('/', '\\'))
        except Exception:
            pass

        steam_root = next((p for p in steam_paths if os.path.exists(p)), None)
        if steam_root:
            lib_file = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
            library_dirs = [steam_root]
            
            if os.path.exists(lib_file):
                import re
                with open(lib_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                for match in re.finditer(r'"path"\s+"([^"]+)"', content):
                    p = match.group(1).replace("\\\\", "\\")
                    if os.path.exists(p) and p not in library_dirs:
                        library_dirs.append(p)

            for lib in library_dirs:
                apps_dir = os.path.join(lib, "steamapps")
                if not os.path.exists(apps_dir):
                    continue
                for fname in os.listdir(apps_dir):
                    if fname.startswith("appmanifest_") and fname.endswith(".acf"):
                        acf_path = os.path.join(apps_dir, fname)
                        try:
                            with open(acf_path, "r", encoding="utf-8", errors="ignore") as af:
                                acf_txt = af.read()
                            id_match = re.search(r'"appid"\s+"(\d+)"', acf_txt)
                            name_match = re.search(r'"name"\s+"([^"]+)"', acf_txt)
                            if id_match and name_match:
                                app_id = id_match.group(1)
                                name = name_match.group(1)
                                # Exclude Steamworks Common Redistributables / Proton
                                if not name.startswith("Steamworks") and not name.startswith("Proton"):
                                    games.append({
                                        "name": name,
                                        "app_id": app_id,
                                        "launcher": "steam",
                                        "launch_uri": f"steam://run/{app_id}"
                                    })
                        except Exception:
                            continue
    except Exception as e:
        logger.debug(f"Steam scan error: {e}")

    # 2. Scan Epic Games Manifests
    try:
        epic_manifests = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"
        if os.path.exists(epic_manifests):
            import json
            for mf in os.listdir(epic_manifests):
                if mf.endswith(".item"):
                    try:
                        with open(os.path.join(epic_manifests, mf), "r", encoding="utf-8", errors="ignore") as jf:
                            data = json.load(jf)
                        disp_name = data.get("DisplayName")
                        app_name = data.get("AppName")
                        if disp_name and app_name:
                            games.append({
                                "name": disp_name,
                                "app_id": app_name,
                                "launcher": "epic",
                                "launch_uri": f"com.epicgames.launcher://apps/{app_name}?action=launch&silent=true"
                            })
                    except Exception:
                        continue
    except Exception as e:
        logger.debug(f"Epic scan error: {e}")

    return games


def launch_game(game_query: str) -> dict:
    """
    Find and launch an installed Steam or Epic game matching game_query.
    """
    games = discover_installed_games()
    if not games:
        return {"success": False, "status": "not_found", "message": "No installed games detected on system."}

    q = game_query.lower().strip()
    match = next((g for g in games if q in g["name"].lower()), None)
    if not match:
        names = ", ".join(g["name"] for g in games[:5])
        return {
            "success": False,
            "status": "not_found",
            "message": f"Could not find game matching '{game_query}'. Installed games: {names}."
        }

    try:
        import webbrowser
        uri = match["launch_uri"]
        webbrowser.open(uri)
        return {
            "success": True,
            "status": "success",
            "game": match["name"],
            "launcher": match["launcher"],
            "message": f"Launching '{match['name']}' via {match['launcher'].capitalize()}."
        }
    except Exception as e:
        return {"success": False, "status": "error", "message": f"Failed to launch '{match['name']}': {e}"}

