"""
Generic Windows Application Discovery & Indexer
Discovers all installed applications on Windows dynamically:
1. Microsoft Store / Packaged / UWP Apps (via Get-StartApps)
2. Windows Start Menu Shortcuts (All Users & Current User)
3. Windows Desktop Application Shortcuts (.lnk only)
4. Windows Registry Registered App Paths (HKLM, HKCU, WOW6432Node)
5. WindowsApps Execution Aliases (%LOCALAPPDATA%\\Microsoft\\WindowsApps)
6. Windows Registry Installed Applications (Uninstall keys)
7. Windows Core System Executables (System32 & PATH)
Caches discovery in system_index.json for sub-millisecond lookups.
"""

import os
import sys
import re
import json
import time
import shutil
import difflib
import threading
import subprocess
import winreg
from typing import Dict, Optional, Tuple, List, Any

# File extensions that are NEVER standalone applications
NON_APP_EXTENSIONS = (
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.ico', '.svg', '.tif', '.tiff',
    '.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a',
    '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm',
    '.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.csv', '.rtf',
    '.chm', '.hlp', '.htm', '.html', '.xml', '.json', '.zip', '.rar', '.7z', '.tar', '.gz'
)

# Skip keywords for utility/documentation links
SKIP_NAME_KEYWORDS = (
    "uninstall", "documentation", "release notes", "whatsnew", "what's new",
    "readme", "license", "help", "manual", "guide", "feedback"
)

class SystemIndexer:
    def __init__(self):
        self.index_file = os.path.join(os.path.dirname(__file__), "system_index.json")
        self.system_index: Dict[str, str] = {}
        self._catalog_cache: List[Tuple[str, str, str, str, List[str], str]] = []
        self._last_built: float = 0.0
        self._is_building: bool = False

    def _clean_name(self, name: str) -> str:
        """Clean application display names for better matching"""
        suffixes_to_remove = [" (x64)", " (x86)", " (64-bit)", " (32-bit)", " - shortcut", ".lnk", ".exe"]
        cleaned = name
        for s in suffixes_to_remove:
            pattern = re.compile(re.escape(s), re.IGNORECASE)
            cleaned = pattern.sub("", cleaned)
        return cleaned.strip()

    def _is_legitimate_app(self, name: str, target: str) -> bool:
        """Validate that an entry is a genuine application, not an image/doc/file"""
        n_low = name.lower()
        t_low = target.lower()

        # Disallow non-app extensions
        if any(n_low.endswith(ext) or t_low.endswith(ext) for ext in NON_APP_EXTENSIONS):
            return False

        # Disallow documentation / uninstallers
        if any(kw in n_low for kw in SKIP_NAME_KEYWORDS):
            return False

        # Web URLs and direct non-app file URIs
        if t_low.startswith("http:") or t_low.startswith("https:") or t_low.startswith("file:"):
            return False

        return True

    def build_index(self) -> None:
        """Build generic Windows application index from all discovery sources"""
        if self._is_building:
            return
        self._is_building = True
        try:
            print("[SYSTEM INDEXER] Discovering installed Windows applications...")
            start_time = time.time()
            catalog: Dict[str, str] = {}

            # 1. Discover via PowerShell Get-StartApps (UWP, Store, packaged desktop apps)
            try:
                cmd = ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json"]
                out = subprocess.check_output(cmd, text=True, errors="replace", timeout=12)
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                if isinstance(data, list):
                    for item in data:
                        raw_name = item.get("Name", "")
                        appid = item.get("AppID", "")
                        if not raw_name or not appid:
                            continue
                        clean_name = self._clean_name(raw_name)
                        if not self._is_legitimate_app(clean_name, appid):
                            continue

                        # Determine launch target
                        if "!" in appid or not (os.path.isabs(appid) and os.path.exists(appid)):
                            catalog[clean_name] = f"shell:AppsFolder\\{appid}"
                        else:
                            catalog[clean_name] = appid
            except Exception as e:
                print(f"[SYSTEM INDEXER] Get-StartApps discovery note: {e}")

            # 2. Discover Start Menu Application Shortcuts (.lnk)
            start_menu_paths = [
                os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
                os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
            ]
            for base in start_menu_paths:
                if os.path.exists(base):
                    for root, _, files in os.walk(base):
                        for f in files:
                            if f.lower().endswith(".lnk"):
                                clean_name = self._clean_name(os.path.splitext(f)[0])
                                full_path = os.path.join(root, f)
                                if self._is_legitimate_app(clean_name, full_path) and clean_name not in catalog:
                                    catalog[clean_name] = full_path

            # 3. Discover Desktop Application Shortcuts (.lnk ONLY)
            desktop_paths = [
                os.path.join(os.environ.get("USERPROFILE", ""), r"Desktop"),
                os.path.join(os.environ.get("USERPROFILE", ""), r"OneDrive", r"Desktop"),
                os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), r"Desktop"),
            ]
            for d_path in desktop_paths:
                if os.path.exists(d_path):
                    try:
                        for f in os.listdir(d_path):
                            if f.lower().endswith(".lnk"):
                                clean_name = self._clean_name(os.path.splitext(f)[0])
                                full_path = os.path.join(d_path, f)
                                if self._is_legitimate_app(clean_name, full_path) and clean_name not in catalog:
                                    catalog[clean_name] = full_path
                    except Exception:
                        pass

            # 4. Discover Windows Registry Registered App Paths (HKLM & HKCU)
            for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                for sub in [r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
                            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"]:
                    try:
                        with winreg.OpenKey(hive, sub) as key:
                            count = winreg.QueryInfoKey(key)[0]
                            for i in range(count):
                                try:
                                    subkey_name = winreg.EnumKey(key, i)
                                    val = winreg.QueryValue(key, subkey_name)
                                    if val:
                                        clean_val = val.strip('"')
                                        if os.path.exists(clean_val):
                                            base_name = self._clean_name(os.path.splitext(subkey_name)[0])
                                            if self._is_legitimate_app(base_name, clean_val):
                                                if base_name not in catalog and base_name.title() not in catalog:
                                                    catalog[base_name] = clean_val
                                except Exception:
                                    pass
                    except Exception:
                        pass

            # 5. Discover WindowsApps execution aliases (%LOCALAPPDATA%\Microsoft\WindowsApps)
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            winapps = os.path.join(local_app_data, "Microsoft", "WindowsApps")
            if os.path.exists(winapps):
                try:
                    for f in os.listdir(winapps):
                        if f.lower().endswith(".exe"):
                            base_name = self._clean_name(os.path.splitext(f)[0])
                            full_path = os.path.join(winapps, f)
                            if self._is_legitimate_app(base_name, full_path):
                                if base_name not in catalog and base_name.title() not in catalog:
                                    catalog[base_name] = full_path
                except Exception:
                    pass

            # 6. Discover Installed Applications from Registry Uninstall Keys
            for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                for sub in [r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"]:
                    try:
                        with winreg.OpenKey(hive, sub) as key:
                            count = winreg.QueryInfoKey(key)[0]
                            for i in range(count):
                                try:
                                    sk = winreg.OpenKey(key, winreg.EnumKey(key, i))
                                    display_name = winreg.QueryValueEx(sk, 'DisplayName')[0]
                                    clean_name = self._clean_name(display_name)
                                    if not clean_name or clean_name in catalog or clean_name.title() in catalog:
                                        continue
                                    if not self._is_legitimate_app(clean_name, ""):
                                        continue

                                    # Try DisplayIcon first
                                    exe_target = None
                                    try:
                                        icon_val = winreg.QueryValueEx(sk, 'DisplayIcon')[0].split(',')[0].strip('"')
                                        if icon_val.lower().endswith(".exe") and os.path.exists(icon_val):
                                            exe_target = icon_val
                                    except Exception:
                                        pass

                                    # Try InstallLocation if no DisplayIcon
                                    if not exe_target:
                                        try:
                                            install_loc = winreg.QueryValueEx(sk, 'InstallLocation')[0].strip('"')
                                            if os.path.isdir(install_loc):
                                                # Look for direct exe matching app name
                                                for f in os.listdir(install_loc):
                                                    if f.lower().endswith(".exe") and not any(kw in f.lower() for kw in ["unins", "setup", "helper"]):
                                                        exe_target = os.path.join(install_loc, f)
                                                        break
                                        except Exception:
                                            pass

                                    if exe_target and os.path.exists(exe_target):
                                        catalog[clean_name] = exe_target
                                except Exception:
                                    pass
                    except Exception:
                        pass

            # 8. Discover user-space installed apps in %LOCALAPPDATA%\Programs
            #    (e.g. Opera, VS Code, Cursor, Ollama, Kiro, Devin, Trae, Windsurf, GIMP …)
            local_programs = os.path.join(local_app_data, "Programs")
            if os.path.exists(local_programs):
                try:
                    for app_dir in os.listdir(local_programs):
                        app_dir_path = os.path.join(local_programs, app_dir)
                        if not os.path.isdir(app_dir_path):
                            continue
                        # Walk one level deep only to stay fast
                        for f in os.listdir(app_dir_path):
                            if not f.lower().endswith(".exe"):
                                continue
                            # Skip known non-main helpers
                            fl = f.lower()
                            if any(kw in fl for kw in ["unins", "setup", "update", "helper", "crash", "squirrel"]):
                                continue
                            clean_name = self._clean_name(os.path.splitext(f)[0])
                            # Also try the folder name as a display name
                            folder_name = self._clean_name(app_dir)
                            full_path = os.path.join(app_dir_path, f)
                            if not self._is_legitimate_app(clean_name, full_path):
                                continue
                            # Prefer folder name if it's more descriptive
                            chosen_name = folder_name if len(folder_name) >= len(clean_name) else clean_name
                            if chosen_name not in catalog and chosen_name.title() not in catalog:
                                catalog[chosen_name] = full_path
                            # Also register by exe base name in case of mismatch
                            if clean_name not in catalog and clean_name.title() not in catalog:
                                catalog[clean_name] = full_path
                except Exception as e:
                    print(f"[SYSTEM INDEXER] LocalPrograms discovery note: {e}")

            # 9. Core Windows standard executables & protocol URIs
            system_tools = {
                "Notepad": "notepad.exe",
                "Calculator": "calc.exe",
                "Paint": "mspaint.exe",
                "File Explorer": "explorer.exe",
                "Task Manager": "taskmgr.exe",
                "Command Prompt": "cmd.exe",
                "PowerShell": "powershell.exe",
                "Windows Terminal": "wt.exe",
                "Settings": "ms-settings:",
                "Camera": "microsoft.windows.camera:",
            }
            for s_name, s_target in system_tools.items():
                if s_name not in catalog:
                    which = shutil.which(s_target) if s_target.endswith(".exe") else None
                    catalog[s_name] = which if which else s_target

            # Final sanitize check
            self.system_index = self._sanitize_index(catalog)
            self._last_built = time.time()
            self._save_index()
            self._prepare_catalog_cache()

            elapsed = time.time() - start_time
            print(f"[SYSTEM INDEXER] Generic index built: {len(self.system_index)} applications discovered in {elapsed:.2f}s")
        finally:
            self._is_building = False

    def _sanitize_index(self, catalog: Dict[str, str]) -> Dict[str, str]:
        """Strip out any corrupted, non-app, or media entries"""
        sanitized = {}
        for name, target in catalog.items():
            if self._is_legitimate_app(name, target):
                sanitized[name] = target
        return sanitized

    def _save_index(self) -> None:
        """Save index with metadata to cache file"""
        payload = {
            "version": 2,
            "last_built": self._last_built,
            "total_apps": len(self.system_index),
            "apps": self.system_index
        }
        try:
            with open(self.index_file, "w", encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            print(f"[SYSTEM INDEXER] Index saved to {self.index_file}")
        except Exception as e:
            print(f"[SYSTEM INDEXER] Failed to save index: {e}")

    def load_index(self) -> bool:
        """Load index from cache file with schema and integrity validation"""
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding='utf-8') as f:
                    data = json.load(f)

                # Support both v2 schema (with metadata) and v1 legacy schema
                if isinstance(data, dict):
                    if "apps" in data and isinstance(data["apps"], dict):
                        loaded_apps = data["apps"]
                        self._last_built = data.get("last_built", 0.0)
                    else:
                        loaded_apps = data
                        self._last_built = os.path.getmtime(self.index_file)

                    # Sanitize against any legacy non-app entries
                    self.system_index = self._sanitize_index(loaded_apps)
                    self._prepare_catalog_cache()
                    print(f"[SYSTEM INDEXER] Loaded {len(self.system_index)} applications from cache")

                    # If cache is older than 24 hours or has too few items, refresh asynchronously
                    if time.time() - self._last_built > 86400 or len(self.system_index) < 10:
                        self.build_index_async()

                    return len(self.system_index) > 0
            except Exception as e:
                print(f"[SYSTEM INDEXER] Failed to load index: {e}")
        return False

    def build_index_async(self) -> None:
        """Refresh application catalog in background thread without blocking"""
        t = threading.Thread(target=self.build_index, daemon=True, name="SystemIndexerBuildThread")
        t.start()

    def _prepare_catalog_cache(self) -> None:
        """Pre-compute normalized forms, words, and acronyms for instant matching"""
        entries = []
        for name, target in self.system_index.items():
            n_name = name.lower()
            a_name = re.sub(r'[^a-z0-9]', '', n_name)
            words = [re.sub(r'[^a-z0-9]', '', w) for w in re.split(r'[\s\-_\.]+', n_name) if w]
            words = [w for w in words if w]
            acronym = "".join(w[0] for w in words if w) if len(words) > 1 else ""
            entries.append((name, target, n_name, a_name, words, acronym))
        self._catalog_cache = entries

    def _discover_on_demand(self, query: str) -> Optional[Tuple[str, str, str]]:
        """
        Fast on-demand check for applications newly installed or not in cache:
        1. System PATH via shutil.which
        2. Windows Registry App Paths
        3. WindowsApps execution aliases
        4. Targeted StartApps query
        """
        q_norm = query.lower().strip()
        q_alnum = re.sub(r'[^a-z0-9]', '', q_norm)
        if not q_alnum:
            return None

        # 1. System PATH
        for cand in [q_norm, f"{q_norm}.exe", q_alnum, f"{q_alnum}.exe"]:
            which = shutil.which(cand)
            if which and os.path.exists(which):
                dname = self._clean_name(os.path.splitext(os.path.basename(which))[0]).title()
                self.system_index[dname] = which
                self._prepare_catalog_cache()
                return (dname, which, "on_demand_path")

        # 2. Registry App Paths
        for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            for sub in [r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
                        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"]:
                try:
                    with winreg.OpenKey(hive, sub) as key:
                        for ext in ["", ".exe"]:
                            try:
                                val = winreg.QueryValue(key, q_norm + ext)
                                if val:
                                    clean_val = val.strip('"')
                                    if os.path.exists(clean_val):
                                        dname = q_norm.title()
                                        self.system_index[dname] = clean_val
                                        self._prepare_catalog_cache()
                                        return (dname, clean_val, "on_demand_registry")
                            except Exception:
                                pass
                except Exception:
                    pass

        # 3. WindowsApps Execution Aliases
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        winapps = os.path.join(local_app_data, "Microsoft", "WindowsApps")
        if os.path.exists(winapps):
            candidate_exe = os.path.join(winapps, f"{q_norm}.exe")
            if os.path.exists(candidate_exe):
                dname = q_norm.title()
                self.system_index[dname] = candidate_exe
                self._prepare_catalog_cache()
                return (dname, candidate_exe, "on_demand_windowsapps")

        # 4. %LOCALAPPDATA%\Programs — user-space app installs (Opera, VS Code, etc.)
        local_programs = os.path.join(local_app_data, "Programs")
        if os.path.exists(local_programs):
            for app_dir in os.listdir(local_programs):
                app_dir_path = os.path.join(local_programs, app_dir)
                if not os.path.isdir(app_dir_path):
                    continue
                dir_norm = re.sub(r'[^a-z0-9]', '', app_dir.lower())
                # Check if query matches folder name
                if q_alnum in dir_norm or dir_norm.startswith(q_alnum) or q_alnum.startswith(dir_norm):
                    for f in os.listdir(app_dir_path):
                        if not f.lower().endswith(".exe"):
                            continue
                        fl = f.lower()
                        if any(kw in fl for kw in ["unins", "setup", "update", "helper", "crash", "squirrel"]):
                            continue
                        full_path = os.path.join(app_dir_path, f)
                        dname = self._clean_name(app_dir)
                        self.system_index[dname] = full_path
                        self._prepare_catalog_cache()
                        return (dname, full_path, "on_demand_local_programs")

        # 5. Targeted StartApps lookup for packaged store apps
        try:
            cmd = ["powershell", "-NoProfile", "-Command",
                   f"Get-StartApps | Where-Object {{ $_.Name -like '*{q_norm}*' }} | ConvertTo-Json"]
            out = subprocess.check_output(cmd, text=True, errors="replace", timeout=6)
            if out.strip():
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                if isinstance(data, list) and data:
                    item = data[0]
                    raw_name = item.get("Name", "")
                    appid = item.get("AppID", "")
                    if raw_name and appid:
                        dname = self._clean_name(raw_name)
                        target = f"shell:AppsFolder\\{appid}" if "!" in appid or not os.path.isabs(appid) else appid
                        self.system_index[dname] = target
                        self._prepare_catalog_cache()
                        return (dname, target, "on_demand_startapps")
        except Exception:
            pass

        return None

    def resolve_detailed(self, name: str) -> Optional[Tuple[str, str, str]]:
        """
        Hierarchical application resolution engine:
        1. Exact Match (case/punctuation normalized)
        2. Acronym / Special Alias Match
        3. Standalone Word Match in Multi-Word App
        4. Prefix Match
        5. Safe Fuzzy Match (Typo tolerance)
        6. Dynamic On-Demand Lookup for newly installed apps
        
        Returns: (display_name, launch_target, match_type) or None
        """
        if not self._catalog_cache:
            self._prepare_catalog_cache()

        q_raw = name.strip()
        q_norm = q_raw.lower()
        q_alnum = re.sub(r'[^a-z0-9]', '', q_norm)
        if not q_alnum:
            return None

        # Tier 1: Exact match on normalized or alphanumeric
        for dname, target, n_name, a_name, words, acronym in self._catalog_cache:
            if q_norm == n_name or q_alnum == a_name:
                return (dname, target, "exact")

        # Tier 2: Acronym / special alias match
        if q_alnum in ["vscode", "vsc"]:
            for dname, target, n_name, a_name, words, acronym in self._catalog_cache:
                if "visual studio code" in n_name:
                    return (dname, target, "special_alias")

        for dname, target, n_name, a_name, words, acronym in self._catalog_cache:
            if len(q_alnum) >= 2 and q_alnum == acronym:
                return (dname, target, "acronym")

        # Tier 3: User query is one of the exact standalone words in app name
        # e.g. "chrome" in "Google Chrome", "edge" in "Microsoft Edge", "explorer" in "File Explorer"
        word_matches = []
        for dname, target, n_name, a_name, words, acronym in self._catalog_cache:
            if q_alnum in words:
                # Rank by relevance: prefer fewer total words and shorter name
                word_matches.append((len(words), len(a_name), dname, target))
        if word_matches:
            word_matches.sort()
            best = word_matches[0]
            return (best[2], best[3], "word_match")

        # Tier 4: Prefix match (e.g. "calc" -> "Calculator", "note" -> "Notepad")
        if len(q_alnum) >= 3:
            prefix_matches = []
            for dname, target, n_name, a_name, words, acronym in self._catalog_cache:
                if a_name.startswith(q_alnum):
                    prefix_matches.append((len(a_name), dname, target))
            if prefix_matches:
                prefix_matches.sort()
                best = prefix_matches[0]
                return (best[1], best[2], "prefix")

        # Tier 5: Safe fuzzy match for minor typos (e.g. "whattsapp" / "whatts app" -> "WhatsApp")
        fuzzy_matches = []
        for dname, target, n_name, a_name, words, acronym in self._catalog_cache:
            r1 = difflib.SequenceMatcher(None, q_alnum, a_name).ratio()
            r2 = max((difflib.SequenceMatcher(None, q_alnum, w).ratio() for w in words), default=0.0)
            best_r = max(r1, r2)
            if best_r >= 0.82:
                fuzzy_matches.append((best_r, dname, target))
        if fuzzy_matches:
            fuzzy_matches.sort(key=lambda x: x[0], reverse=True)
            best = fuzzy_matches[0]
            return (best[1], best[2], f"fuzzy ({best[0]:.2f})")

        # Tier 6: Dynamic on-demand discovery if not found in pre-built catalog
        on_demand_match = self._discover_on_demand(q_raw)
        if on_demand_match:
            return on_demand_match

        return None

    def resolve(self, name: str) -> Optional[str]:
        """Resolve name to launch target for backward compatibility"""
        detailed = self.resolve_detailed(name)
        if detailed:
            return detailed[1]
        return None

    def get_index_size(self) -> int:
        """Get number of indexed applications"""
        return len(self.system_index)

    def initialize(self) -> None:
        """Initialize indexer (load from cache or build new)"""
        if not self.load_index():
            self.build_index()

# Global instance
system_indexer = SystemIndexer()
