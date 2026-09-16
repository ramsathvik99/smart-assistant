# extensions/launcher_engine.py

import os
import subprocess
import logging
import shutil
import winreg
import webbrowser
from legacy.tts import speak

logger = logging.getLogger(__name__)

# Start Menu paths for fallback app resolution (no hardcoded app paths)
START_MENU_PATHS = [
    os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
    os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs")
]

# Import the new smart opener
try:
    from .system.smart_opener import smart_opener
    SMART_OPENER_AVAILABLE = True
    print("[LAUNCHER] Smart opener loaded successfully")
except ImportError as e:
    SMART_OPENER_AVAILABLE = False
    print(f"[LAUNCHER] Smart opener not available: {e}")

def find_app_in_start_menu(app_name: str):
    """Walk Start Menu .lnk shortcuts for any installed app — no hardcoded paths."""
    for base in START_MENU_PATHS:
        if not os.path.exists(base):
            continue
        for root, dirs, files in os.walk(base):
            for file in files:
                if app_name.lower() in file.lower() and file.endswith(".lnk"):
                    return os.path.join(root, file)
    return None


def handle_youtube(command: str) -> str:
    """
    Strict YouTube intent handler — rule-based, no LLM.
    'open youtube'         -> Web
    'open youtube app'     -> App (with browser fallback)
    'open youtube browser' -> Web
    'open youtube and search for X' -> YouTube Search Result
    """
    import urllib.parse, webbrowser
    from legacy.tts import speak
    
    q = command.lower().strip()

    # ✅ ONLY trigger search if explicit phrase exists
    if "search for" in q:
        # extract ONLY after 'search for'
        search_part = q.split("search for", 1)[1].strip()

        # ❌ if nothing after → DO NOT SEARCH
        if not search_part:
            webbrowser.open("https://www.youtube.com")
            speak("Opening YouTube")
            return "Opening YouTube (Web)"

        encoded = urllib.parse.quote(search_part)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        webbrowser.open(url)

        speak(f"Searching YouTube for {search_part}")
        return f"Searching YouTube for {search_part}"

    # Handle 'app' requested specifically
    if "app" in q or "application" in q:
        result = open_application("youtube")
        if isinstance(result, dict) and result.get("success"):
            return "Opening YouTube App"
        # Fallback to web
        webbrowser.open("https://www.youtube.com")
        speak("YouTube app not found, opening in browser")
        return "YouTube app not found, opened in browser"

    # ✅ SAFE DEFAULT
    webbrowser.open("https://www.youtube.com")
    speak("Opening YouTube")
    return "Opening YouTube (Web)"


def _scan_program_files(app: str):
    exe_name = app.lower().strip()
    if not exe_name.endswith(".exe"):
        exe_name = exe_name + ".exe"
    roots = [
        r"C:\Program Files",
        r"C:\Program Files (x86)",
    ]
    print("[LAUNCHER] Program Files scan")
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            for f in files:
                try:
                    if f.lower() == exe_name:
                        candidate = os.path.join(dirpath, f)
                        if os.path.exists(candidate):
                            return candidate
                except Exception:
                    continue
    return None
def _resolve_executable(exe_name: str):
    path = shutil.which(exe_name)
    if path:
        return path
    reg = _resolve_registry_app_paths(exe_name)
    if reg:
        return reg
    return None

def _resolve_known_browser(exe_name: str):
    candidates = []
    if exe_name.lower() == "chrome.exe":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    if exe_name.lower() == "msedge.exe":
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
    if exe_name.lower() == "brave.exe":
        candidates = [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

def _resolve_registry_app_paths(exe_name: str):
    try:
        for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            for view in [winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY]:
                try:
                    base = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths", 0, winreg.KEY_READ | view)
                except FileNotFoundError:
                    continue
                for suffix in ["", exe_name, exe_name.lower(), exe_name.upper()]:
                    try:
                        key = winreg.OpenKey(base, suffix if suffix else exe_name)
                        path, _ = winreg.QueryValueEx(key, "")
                        if path and os.path.exists(path):
                            return path
                    except FileNotFoundError:
                        continue
    except Exception:
        pass
    return None

def _resolve_uwp_appid(name: str):
    try:
        cmd = f'powershell "Get-StartApps | Where-Object {{$_.Name -like \'*{name}*\'}} | Select -First 1 | ForEach-Object {{$_.AppID}}"'
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
        if out:
            return out
    except Exception:
        pass
    known = {
        "whatsapp": [
            "WhatsApp.WhatsAppDesktop_8wekyb3d8bbwe!App",
            "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
        ],
        "camera": [
            "Microsoft.WindowsCamera_8wekyb3d8bbwe!App",
        ],
    }
    key = name.lower()
    if key in known:
        for appid in known[key]:
            return appid
    return None

def _resolve_by_layers(app: str):
    path = _resolve_executable(app + ".exe")
    if path:
        return path
    kb = _resolve_known_browser(app + ".exe")
    if kb:
        return kb
    reg = _resolve_registry_app_paths(app + ".exe")
    if reg:
        return reg
    appid = _resolve_uwp_appid(app)
    if appid:
        subprocess.Popen(f'start shell:AppsFolder\\{appid}', shell=True)
        return "__UWP__"
    return None

def _resolve_for_test(app: str):
    app_clean = app.lower().strip()
    print(f"[LAUNCHER TEST] Attempting to launch: {app_clean}")
    # PATH
    for candidate in [app_clean, app_clean + ".exe"]:
        found = shutil.which(candidate)
        if found:
            print(f"[LAUNCHER TEST] Resolved via PATH: {found}")
            return {"method": "PATH", "value": found}
    # System exe fallback
    exe_try = app_clean + ".exe"
    print(f"[LAUNCHER TEST] EXE fallback candidate: {exe_try}")
    # We can't verify existence reliably here; report candidate
    # Program Files scan
    pf = _scan_program_files(app_clean)
    if pf:
        print(f"[LAUNCHER TEST] Resolved via Program Files scan: {pf}")
        return {"method": "PROGRAM_FILES", "value": pf}
    # UWP
    appid = _resolve_uwp_appid(app_clean)
    if appid:
        resolved = f"shell:AppsFolder\\{appid}"
        print(f"[LAUNCHER TEST] Resolved via UWP AppID: {resolved}")
        return {"method": "UWP", "value": resolved}
    kb = _resolve_known_browser(app_clean + ".exe")
    if kb:
        print(f"[LAUNCHER TEST] Resolved via known install: {kb}")
        return {"method": "KNOWN_PATH", "value": kb}
    print("[LAUNCHER TEST] No resolution found")
    return {"method": "NONE", "value": None}

def launcher_self_test():
    results = []
    for app in ["brave", "notepad", "calc"]:
        res = _resolve_for_test(app)
        results.append((app, res))
        print(f"[LAUNCHER TEST] Launch result: {'success' if res.get('value') else 'failure'}")
    return results
def open_with_shell(app_name: str) -> dict:
    r"""
    STEP 1: Windows AppsFolder — best for Store apps (WhatsApp, Spotify, etc.)
    Equivalent to Win+R → shell:AppsFolder\AppID
    """
    try:
        print(f"[LAUNCHER] AppsFolder attempt: {app_name}")
        appid = _resolve_uwp_appid(app_name)
        if appid:
            subprocess.Popen(
                ["explorer.exe", f"shell:AppsFolder\\{appid}"],
                shell=False
            )
            print(f"[LAUNCHER] Opened via AppsFolder: {appid}")
            return {"success": True, "name": app_name,
                    "path": f"shell:AppsFolder\\{appid}",
                    "method": "appsfolder",
                    "message": f"{app_name} opened successfully."}
    except Exception as e:
        print(f"[LAUNCHER] AppsFolder failed: {e}")
    return None


def open_from_start_menu(app_name: str) -> dict:
    """
    STEP 2: Start Menu shortcut (.lnk) — covers all installed desktop apps.
    Uses shell=True with the shortcut path for correct execution context.
    """
    lnk = find_app_in_start_menu(app_name)
    if lnk:
        try:
            print(f"[LAUNCHER] Start Menu shortcut found: {lnk}")
            subprocess.Popen(lnk, shell=True)
            return {"success": True, "name": app_name,
                    "path": lnk,
                    "method": "start_menu",
                    "message": f"{app_name} opened successfully."}
        except Exception as e:
            print(f"[LAUNCHER] Start Menu launch failed: {e}")
    return None


def open_with_start_command(app_name: str) -> dict:
    """
    STEP 3: cmd /c start — works for PATH executables (notepad, calc, etc.)
    Equivalent to Win+R → type app name and press Enter.
    """
    try:
        print(f"[LAUNCHER] cmd start attempt: {app_name}")
        subprocess.Popen(["cmd", "/c", "start", "", app_name], shell=False)
        return {"success": True, "name": app_name,
                "path": app_name,
                "method": "cmd_start",
                "message": f"{app_name} opened successfully."}
    except Exception as e:
        print(f"[LAUNCHER] cmd start failed: {e}")
    return None


def open_application(app_name: str) -> dict:
    """
    Universal Windows app launcher — 3-step reliable pipeline.
    """
    # 🚨 SEARCH LOGIC AT THE TOP (Part 1 - Default Web Search)
    # ✅ ONLY trigger search if explicit phrase exists
    if "search for" in app_name.lower():
        import urllib.parse, webbrowser
        from legacy.tts import speak

        # extract ONLY after 'search for'
        search_part = app_name.lower().split("search for", 1)[1].strip()

        # ❌ if nothing after → DO NOT SEARCH
        if not search_part:
            # Fallback: maybe just open google?
            webbrowser.open("https://www.google.com")
            speak("Opening Google")
            return {"success": True, "name": "google", "message": "Opening Google"}

        encoded = urllib.parse.quote(search_part)
        url = f"https://www.google.com/search?q={encoded}"
        webbrowser.open(url)

        speak("Searching on Google")
        return {"success": True, "name": app_name, "message": "Searching Google"}

    app = app_name.lower().strip()
    print(f"[LAUNCHER] Resolving: '{app}'")

    # STEP 1 — AppsFolder (best for Store/UWP apps)
    res = open_with_shell(app)
    if res:
        return res

    # STEP 2 — Start Menu shortcut walk
    res = open_from_start_menu(app)
    if res:
        return res

    # STEP 3 — cmd /c start (PATH executables, system tools)
    res = open_with_start_command(app)
    if res:
        return res

    print(f"[LAUNCHER] Not found: '{app}'")
    return {
        "success": False,
        "name": app_name,
        "path": None,
        "message": f"{app_name} not found"
    }



class LauncherEngine:
    """
    Simplified Windows App Launcher using os.startfile() + fallback
    """

    APP_ALIASES = {
        "word": "WINWORD.EXE",
        "word document": "WINWORD.EXE",
        "excel": "EXCEL.EXE",
        "powerpoint": "POWERPNT.EXE",
        "power point": "POWERPNT.EXE",
        "ppt": "POWERPNT.EXE",
    }

    def __init__(self):
        pass

    def open(self, name: str) -> dict:
        """
        Core open logic with smart opener integration.
        Must never raise unhandled exception.
        Returns structured dictionary.
        """
        try:
            # PRIORITY 1: Use smart opener if available (fastest and most comprehensive)
            if SMART_OPENER_AVAILABLE:
                print(f"[LAUNCHER] Using smart opener for: {name}")
                result = smart_opener.smart_open(name)
                if result.get("success"):
                    return result
                else:
                    print(f"[LAUNCHER] Smart opener failed, falling back to legacy methods")

            # PRIORITY 2: Legacy resolution methods
            exe_path = self._resolve_application(name)

            if not exe_path:
                return {
                    "success": False,
                    "name": name,
                    "path": None,
                    "message": f"{name} not found."
                }

            # Handle UWP apps vs regular apps
            if exe_path == "__UWP__":
                # The _resolve_application method already launches the UWP app via explorer/start
                pass
            elif exe_path.endswith(":"):
                import subprocess
                subprocess.Popen(f"start {exe_path}", shell=True)
            else:
                import subprocess
                subprocess.Popen([exe_path], shell=False)

            return {
                "success": True,
                "name": name,
                "path": exe_path,
                "message": f"{name} opened successfully."
            }

        except Exception as e:
            return {
                "success": False,
                "name": name,
                "path": None,
                "message": f"Error opening {name}: {str(e)}"
            }

    def _resolve_application(self, name: str):
        """
        Internal method to resolve application path.
        Returns executable path or None.
        """
        name = name.lower().strip()
        if name in ["chrome", "google chrome"]:
            for exe in ["chrome.exe"]:
                path = _resolve_executable(exe) or _resolve_known_browser(exe)
                if path:
                    return path
        if name in ["edge", "microsoft edge", "msedge"]:
            for exe in ["msedge.exe"]:
                path = _resolve_executable(exe) or _resolve_known_browser(exe)
                if path:
                    return path
        if name in ["brave", "brave browser"]:
            for exe in ["brave.exe"]:
                path = _resolve_executable(exe) or _resolve_known_browser(exe)
                if path:
                    return path
        if name in ["whatsapp", "whatsapp desktop"]:
            appid = _resolve_uwp_appid("WhatsApp")
            if appid:
                subprocess.Popen(f'start shell:AppsFolder\\{appid}', shell=True)
                return "__UWP__"
            local_exe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "WhatsApp", "WhatsApp.exe")
            if os.path.exists(local_exe):
                return local_exe
        if name in ["calculator", "calc"]:
            return "calc.exe"
        if name in ["notepad"]:
            return "notepad.exe"
        if name in self.APP_ALIASES:
            exe_name = self.APP_ALIASES[name]
            path = _resolve_executable(exe_name)
            if path:
                return path
        exe_name = name + ".exe"
        path = _resolve_executable(exe_name)
        if path:
            return path
        path = _resolve_registry_app_paths(exe_name)
        if path:
            return path
        appid = _resolve_uwp_appid(name)
        if appid:
            subprocess.Popen(f'start shell:AppsFolder\\{appid}', shell=True)
            return "__UWP__"
        return None

    def search(self, name: str):
        """
        Enhanced search logic using smart opener.
        """
        # PRIORITY 1: Use smart opener if available
        if SMART_OPENER_AVAILABLE:
            path = smart_opener.search(name)
            if path:
                return name  # Return the original name for compatibility
        
        # PRIORITY 2: Fallback to basic search
        return name if name else None

    # Compatibility layer for legacy
    def find_app(self, name: str):
        result = self.search(name)
        print(f"[DEBUG] LauncherEngine.find_app: '{name}' -> '{result}'")
        return result

    def open_app(self, name: str):
        return self.open(name)

    def launch_app(self, app_name):
        """Launch application using the new Windows-native launcher"""
        from legacy.tts import speak
        
        result = self.open(app_name)
        
        if result.get("success", False):
            speak(f"Opening {app_name}.")
            return True
        else:
            speak(f"Failed to open {app_name}.")
            return False

    def handle_app_context_action(self, app_name, action, text):
        """
        Handles in-app actions (simplified version).
        """
        app_name = app_name.lower()
        
        if "spotify" in app_name:
            if action in ["play", "resume"]:
                query = text.replace("play music", "").replace("play", "").strip()
                if query:
                    speak(f"Searching {query} in Spotify.")
                    os.startfile(f"spotify:search:{query}")
                else:
                    speak("Resuming Spotify.")
                    os.startfile("spotify:track")
                return True
            elif action in ["pause", "stop"]:
                try:
                    import pyautogui
                    pyautogui.press("playpause")
                    speak("Paused.")
                    return True
                except ImportError:
                    speak("Pause functionality not available.")
                    return False
                    
        elif "explorer" in app_name or "folder" in app_name:
            if action == "open":
                folder = text.replace("open", "").strip()
                if folder:
                    speak(f"Opening {folder}.")
                    os.startfile(folder)
                    return True
                    
        return False
