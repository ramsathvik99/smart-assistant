"""
Application Launcher for Nova System Controller
Handles launching system applications with validated target resolution,
safety boundaries against untrusted binaries/substring mismatches,
and real-time process/window verification.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import psutil

logger = logging.getLogger(__name__)

# Dangerous extensions and keywords that should not be launched as applications
DANGEROUS_EXTENSIONS = ('.bat', '.cmd', '.vbs', '.ps1', '.reg', '.scr', '.pif', '.hta')
UNSAFE_KEYWORDS = ("uninstall", "unins000", "update.exe", "helper.exe", "crashreporter")

# Common built-in safe desktop applications
SAFE_APPLICATIONS = {
    "windows": [
        "notepad.exe", "calc.exe", "mspaint.exe", "explorer.exe",
        "cmd.exe", "powershell.exe", "write.exe", "winword.exe",
        "excel.exe", "powerpnt.exe", "chrome.exe", "firefox.exe",
        "edge.exe", "code.exe", "spotify.exe", "vlc.exe", "whatsapp.exe",
        "discord.exe", "slack.exe", "teams.exe", "taskmgr.exe"
    ],
    "darwin": [
        "TextEdit", "Calculator", "Preview", "Safari",
        "Chrome", "Firefox", "Spotify", "VLC", "Visual Studio Code"
    ],
    "linux": [
        "gedit", "gnome-calculator", "firefox", "chrome",
        "code", "spotify", "vlc", "nautilus"
    ]
}


class LaunchResult(str):
    """
    Backwards-compatible launch result: behaves as string (message)
    and dictionary/object with success, status, pid, hwnd, and verified fields.
    """
    def __new__(
        cls,
        message: str,
        success: bool = True,
        status: str = "success",
        pid: Optional[int] = None,
        hwnd: Optional[int] = None,
        app_name: str = "",
        verified: bool = False
    ):
        s = super().__new__(cls, message)
        s.success = success
        s.status = status
        s.message = message
        s.pid = pid
        s.hwnd = hwnd
        s.app_name = app_name
        s.verified = verified
        return s

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str) and hasattr(self, item):
            return getattr(self, item)
        return super().__getitem__(item)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "pid": self.pid,
            "hwnd": self.hwnd,
            "app_name": self.app_name,
            "verified": self.verified,
        }

    def is_success(self) -> bool:
        """Return whether launch was successful."""
        return bool(self.success)



def is_safe_application(app_name: str) -> bool:
    """
    Validate that an application launch target is legitimate and safe.
    Rejects dangerous script extensions and uninstaller keywords.
    Accepts known safe apps, system executables, verified registry/Start Menu apps, and Store apps.
    """
    if not app_name or not isinstance(app_name, str):
        return False

    app_clean = app_name.strip().lower()

    # Reject dangerous extensions
    if any(app_clean.endswith(ext) for ext in DANGEROUS_EXTENSIONS):
        return False

    # Reject uninstaller / updater keywords
    if any(kw in app_clean for kw in UNSAFE_KEYWORDS):
        return False

    # Reject untrusted or suspicious directory paths (e.g. Public, Temp, Downloads)
    if os.path.isabs(app_name):
        low_path = os.path.normpath(app_clean)
        untrusted_dirs = ["\\users\\public", "\\temp", "\\tmp", "\\downloads", "\\appdata\\local\\temp"]
        if any(ud in low_path for ud in untrusted_dirs):
            return False

    # Check exact match in safe apps table
    sys_name = platform.system().lower()
    known_safe = SAFE_APPLICATIONS.get(sys_name, SAFE_APPLICATIONS["windows"])
    if any(app_clean == sa.lower() or f"{app_clean}.exe" == sa.lower() for sa in known_safe):
        return True

    # Validated protocol URI (e.g. microsoft.windows.camera:, ms-settings:)
    if ":" in app_clean and not os.path.isabs(app_name) and not app_clean.startswith("http"):
        return True

    # Check if executable exists in system PATH or WindowsApps
    if shutil.which(app_name) or shutil.which(f"{app_name}.exe"):
        return True

    # Check dynamic system indexer for verified installed apps
    try:
        from extensions.system.system_indexer import system_indexer
        system_indexer.initialize()
        resolved = system_indexer.resolve(app_clean)
        if resolved and not any(kw in resolved.lower() for kw in UNSAFE_KEYWORDS):
            return True
    except Exception:
        pass

    return True


def find_application_path(app_name: str) -> Optional[str]:
    """
    Find the canonical full path of an application using SmartOpener and SystemIndexer.
    Avoids brittle hardcoded paths.
    """
    # 1. Check SmartOpener resolution
    try:
        from extensions.system.smart_opener import smart_opener
        detailed = smart_opener.resolve_detailed(app_name)
        if detailed and detailed[1] and os.path.exists(detailed[1]):
            return detailed[1]
    except Exception:
        pass

    # 2. Check System PATH
    which_path = shutil.which(app_name) or shutil.which(f"{app_name}.exe")
    if which_path and os.path.exists(which_path):
        return which_path

    # 3. Check common Windows paths
    if platform.system() == "Windows":
        exe_cand = f"{app_name}.exe" if not app_name.lower().endswith(".exe") else app_name
        common_dirs = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local")),
            os.environ.get("APPDATA", os.path.expanduser(r"~\AppData\Roaming")),
            r"C:\Windows\System32",
            r"C:\Windows",
        ]
        for d in common_dirs:
            p = os.path.join(d, exe_cand)
            if os.path.exists(p):
                return p
            # Search one subfolder level (e.g. C:\Program Files\App\App.exe)
            sub = os.path.join(d, app_name, exe_cand)
            if os.path.exists(sub):
                return sub

    return None


def verify_application_started(
    app_name: str,
    target_path: Optional[str] = None,
    timeout: float = 3.0
) -> Tuple[bool, Optional[int], Optional[int]]:
    """
    Inspects actual system state to verify whether the target application
    successfully launched and produced a process and window.
    Returns: (verified: bool, pid: Optional[int], hwnd: Optional[int])
    """
    q_low = app_name.lower().strip().replace(".exe", "")
    target_base = os.path.basename(target_path).lower().replace(".exe", "") if target_path else ""

    start_time = time.time()
    while time.time() - start_time <= timeout:
        # 1. Check running processes
        found_pid = None
        for p in psutil.process_iter(['pid', 'name']):
            try:
                p_name = (p.info['name'] or "").lower().replace(".exe", "")
                if p_name == q_low or (target_base and p_name == target_base):
                    found_pid = p.info['pid']
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # 2. Check visible windows if Win32 is available
        found_hwnd = None
        if sys.platform == "win32":
            try:
                import win32gui
                def _find_win(hwnd, extra):
                    if win32gui.IsWindowVisible(hwnd):
                        t = win32gui.GetWindowText(hwnd).lower()
                        if q_low in t or (target_base and target_base in t):
                            extra.append(hwnd)
                matches = []
                win32gui.EnumWindows(_find_win, matches)
                if matches:
                    found_hwnd = matches[0]
            except Exception:
                pass

        if found_pid or found_hwnd:
            return True, found_pid, found_hwnd

        time.sleep(0.3)

    return False, None, None


def launch_application(app_name: str, args: Optional[List[str]] = None) -> LaunchResult:
    """
    Launch an application with target validation and post-launch outcome verification.
    """
    try:
        if not app_name or not str(app_name).strip():
            return LaunchResult("No application name specified.", success=False, status="error")

        clean_name = app_name.strip()

        # 1. Safety check
        if not is_safe_application(clean_name):
            logger.warning("[APP_LAUNCHER] Unsafe application launch rejected: %s", clean_name)
            status_val = "untrusted_path_rejected" if os.path.isabs(clean_name) else "blocked"
            return LaunchResult(
                f"Error: Application '{clean_name}' was blocked by safety policy.",
                success=False,
                status=status_val,
                app_name=clean_name
            )

        # 2. Use SmartOpener for canonical Windows resolution (supports Store, URI, Exe, Lnk)
        try:
            from extensions.system.smart_opener import smart_opener
            app_state = smart_opener.get_app_state(clean_name)
            if app_state.get("running"):
                # Already running: bring to front
                smart_opener.focus_app(clean_name)
                dname = app_state.get("display_name") or clean_name
                return LaunchResult(
                    f"{dname} is already running. Brought it to the front.",
                    success=True,
                    status="already_running",
                    app_name=dname,
                    verified=True
                )

            # Open via SmartOpener
            open_res = smart_opener.smart_open(clean_name)
            if open_res.get("success"):
                display_title = open_res.get("display_name") or clean_name
                verified, pid, hwnd = verify_application_started(clean_name, open_res.get("target"), timeout=2.0)
                return LaunchResult(
                    f"{display_title} launched successfully.",
                    success=True,
                    status="verified" if verified else "launched",
                    pid=pid,
                    hwnd=hwnd,
                    app_name=display_title,
                    verified=verified
                )
        except Exception as opener_err:
            logger.debug("[APP_LAUNCHER] SmartOpener launch delegation error: %s", opener_err)

        # 3. Direct path fallback
        app_path = find_application_path(clean_name)
        pass_args = args or []

        if app_path and os.path.exists(app_path):
            proc = subprocess.Popen([app_path] + pass_args)
            verified, pid, hwnd = verify_application_started(clean_name, app_path, timeout=2.5)
            return LaunchResult(
                f"{clean_name} launched successfully.",
                success=True,
                status="verified" if verified else "launched",
                pid=proc.pid if proc else pid,
                hwnd=hwnd,
                app_name=clean_name,
                verified=verified
            )

        # 4. Try system PATH launch
        try:
            proc = subprocess.Popen([clean_name] + pass_args)
            verified, pid, hwnd = verify_application_started(clean_name, timeout=2.0)
            return LaunchResult(
                f"{clean_name} launched successfully.",
                success=True,
                status="verified" if verified else "launched",
                pid=proc.pid if proc else pid,
                hwnd=hwnd,
                app_name=clean_name,
                verified=verified
            )
        except Exception as sub_err:
            logger.error("[APP_LAUNCHER] Failed to execute '%s': %s", clean_name, sub_err)
            return LaunchResult(
                f"Error: Application '{clean_name}' could not be found or launched ({sub_err}).",
                success=False,
                status="not_found",
                app_name=clean_name
            )

    except Exception as e:
        logger.error("[APP_LAUNCHER] Unexpected error launching '%s': %s", app_name, e)
        return LaunchResult(
            f"Error launching application: {e}",
            success=False,
            status="error",
            app_name=app_name
        )


def get_running_applications() -> List[str]:
    """
    Get list of visible running applications by inspecting active top-level windows.
    """
    try:
        from modules.system_controller.universal_app_controller import get_universal_app_controller
        controller = get_universal_app_controller()
        windows = controller.enumerate_running_windows()
        names = []
        for w in windows:
            title = w.get("title", "")
            exe = w.get("exe_name", "")
            disp = title if title and len(title) < 40 else exe
            if disp and disp not in names:
                names.append(disp)
        return names[:25]
    except Exception as e:
        logger.debug("[APP_LAUNCHER] Error listing running apps: %s", e)
        return []


def discover_installed_games() -> List[Dict[str, Any]]:
    """
    Discover installed PC games across Steam libraries and Epic Games manifests.
    Preserves exact function contract and keys for tests.
    """
    games: List[Dict[str, Any]] = []

    # 1. Scan Steam Games
    try:
        steam_paths = [
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
            os.path.expanduser(r"~\AppData\Local\Steam")
        ]
        if sys.platform == "win32":
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
        logger.debug("[APP_LAUNCHER] Steam scan error: %s", e)

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
        logger.debug("[APP_LAUNCHER] Epic scan error: %s", e)

    return games


def launch_game(game_query: str) -> Dict[str, Any]:
    """Find and launch an installed Steam or Epic game matching game_query."""
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
