
import os
import subprocess
import threading
from .registry import AppRegistry

# Standard Start Menu locations
START_MENU_PATHS = [
    r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")
]

class AppScanner:
    def __init__(self, registry):
        self.registry = registry

    def scan(self):
        print("[Launcher] Starting system app scan...")
        self.registry.clear()
        
        # 1. Scan Start Menu (.lnk files)
        self._scan_start_menu()
        
        # 2. Scan UWP Apps (via PowerShell)
        self._scan_uwp_apps()

        # 3. Scan Common PATHs (Optional, skipping for noise reduction)
        # self._scan_path_apps()
        
        self.registry.save()
        print(f"[Launcher] Scan complete. Found {len(self.registry.get_all_apps())} apps.")

    def _scan_start_menu(self):
        for base_path in START_MENU_PATHS:
            if not os.path.exists(base_path):
                continue
                
            for root, dirs, files in os.walk(base_path):
                for file in files:
                    if file.lower().endswith(".lnk"):
                        name = os.path.splitext(file)[0]
                        full_path = os.path.join(root, file)
                        self.registry.add_app(name, full_path, "lnk")

    def _scan_uwp_apps(self):
        # Use PowerShell to get UWP apps
        # Get-StartApps returns Name and AppID
        cmd = ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json"]
        try:
            # CreationFlags to hide window
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo)
            if result.returncode == 0 and result.stdout.strip():
                import json
                try:
                    data = json.loads(result.stdout)
                    # output can be list or dict
                    if isinstance(data, dict):
                        data = [data]
                        
                    for item in data:
                        name = item.get("Name")
                        app_id = item.get("AppID")
                        if name and app_id:
                            self.registry.add_app(name, app_id, "uwp")
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            print(f"[Launcher] UWP Scan Error: {e}")

    def scan_async(self):
        t = threading.Thread(target=self.scan, daemon=True)
        t.start()
