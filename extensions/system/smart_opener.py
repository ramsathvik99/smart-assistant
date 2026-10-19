"""
Smart System Opener
Fast, accurate Windows application opening using dynamic system indexing and protocol resolution.
"""

import os
import shutil
import subprocess
from typing import Dict, Optional, Tuple, Any
from .system_indexer import system_indexer

class SmartOpener:
    def __init__(self):
        self.indexer = system_indexer
        self.indexer.initialize()

        # Native Windows built-in applications and protocol URIs
        self.windows_builtins = {
            "browser": "__default_browser__",
            "the browser": "__default_browser__",
            "web browser": "__default_browser__",
            "internet": "__default_browser__",
            "default browser": "__default_browser__",
            "calculator": "calc.exe",
            "calc": "calc.exe",
            "notepad": "notepad.exe",
            "paint": "mspaint.exe",
            "mspaint": "mspaint.exe",
            "camera": "microsoft.windows.camera:",
            "webcam": "microsoft.windows.camera:",
            "settings": "ms-settings:",
            "windows settings": "ms-settings:",
            "explorer": "explorer.exe",
            "file explorer": "explorer.exe",
            "task manager": "taskmgr.exe",
            "taskmgr": "taskmgr.exe",
            "cmd": "cmd.exe",
            "command prompt": "cmd.exe",
            "powershell": "powershell.exe",
            "terminal": "wt.exe",
            "wordpad": "write.exe",
            "snipping tool": "snippingtool.exe",
        }
        self._resolution_cache: Dict[str, Tuple[str, str, str]] = {}

    def resolve_detailed(self, name: str) -> Optional[Tuple[str, str, str]]:
        """
        Resolve app name to (display_name, launch_target, match_type).
        Checks Windows built-in URIs first for standard tools, then queries dynamic indexer.
        """
        name_clean = name.lower().strip()

        # Check hot resolution cache
        if name_clean in self._resolution_cache:
            cached = self._resolution_cache[name_clean]
            if not os.path.isabs(cached[1]) or os.path.exists(cached[1]):
                return cached

        # 1. Check native Windows built-ins / URI schemes
        if name_clean in self.windows_builtins:
            target = self.windows_builtins[name_clean]
            # Protocol URI (e.g. microsoft.windows.camera:, ms-settings:)
            if ":" in target and not os.path.isabs(target):
                dname = "Windows Settings" if "settings" in name_clean else name_clean.title()
                res = (dname, target, "builtin_uri")
                self._resolution_cache[name_clean] = res
                return res
            # System executable via PATH
            which_path = shutil.which(target)
            if which_path and os.path.exists(which_path):
                res = (name_clean.title(), which_path, "builtin_exe")
                self._resolution_cache[name_clean] = res
                return res
            # Check %LOCALAPPDATA%\Microsoft\WindowsApps\<target>
            local_app_path = os.path.expandvars(rf"%LOCALAPPDATA%\Microsoft\WindowsApps\{target}")
            if os.path.exists(local_app_path):
                res = (name_clean.title(), local_app_path, "builtin_exe")
                self._resolution_cache[name_clean] = res
                return res
            # Terminal fallback: if wt.exe is not installed, fall back to PowerShell or cmd
            if name_clean in ("terminal", "windows terminal"):
                ps_path = shutil.which("powershell.exe") or shutil.which("cmd.exe")
                if ps_path and os.path.exists(ps_path):
                    res = ("Terminal", ps_path, "builtin_fallback")
                    self._resolution_cache[name_clean] = res
                    return res
            res = (name_clean.title(), target, "builtin")
            self._resolution_cache[name_clean] = res
            return res

        # 2. Query dynamic multi-tier system indexer
        detailed = self.indexer.resolve_detailed(name_clean)
        if detailed:
            self._resolution_cache[name_clean] = detailed
            return detailed

        # 3. System PATH fallback
        which_path = shutil.which(name_clean) or shutil.which(f"{name_clean}.exe")
        if which_path and os.path.exists(which_path):
            dname = os.path.splitext(os.path.basename(which_path))[0].title()
            res = (dname, which_path, "path")
            self._resolution_cache[name_clean] = res
            return res

        return None

    def resolve_canonical(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Return the canonical application-resolution result object:
        {
            "display_name": "Terminal",
            "executable": "powershell.exe",
            "path": "C:\\...\\powershell.exe",
            "resolution_method": "builtin_fallback"
        }
        """
        detailed = self.resolve_detailed(name)
        if not detailed:
            return None
        dname, target, method = detailed
        exe_name = os.path.basename(target) if target else name
        return {
            "display_name": dname,
            "executable": exe_name,
            "path": target,
            "resolution_method": method
        }

    def resolve_name(self, name: str) -> Optional[str]:
        """Resolve app name to launch target (backward compatibility)"""
        res = self.resolve_detailed(name)
        return res[1] if res else None

    def get_app_state(self, name: str) -> Dict[str, Any]:
        """
        Determine current OS environment state for an application:
        Checks if it is running, whether it is in the foreground, its PID, and window title.
        """
        name_clean = name.lower().strip()
        resolved = self.resolve_detailed(name_clean)
        display_name = resolved[0] if resolved else name_clean.title()
        target = resolved[1] if resolved else None

        # Check foreground window first
        fg_info = {}
        try:
            from skills.window_management.window_context import get_foreground_window_info
            fg_info = get_foreground_window_info() or {}
        except Exception:
            pass

        fg_title = (fg_info.get("title") or "").lower()
        fg_class = (fg_info.get("class_name") or "").lower()
        fg_pid = fg_info.get("pid", 0)

        exe_name = os.path.basename(target).lower() if (target and target.lower().endswith(".exe")) else None
        target_exes = set()
        if exe_name:
            target_exes.add(exe_name)

        alias_map = {
            "notepad": {"notepad.exe"},
            "chrome": {"chrome.exe"},
            "google chrome": {"chrome.exe"},
            "edge": {"msedge.exe"},
            "microsoft edge": {"msedge.exe"},
            "calculator": {"calc.exe", "calculatorapp.exe", "calculator.exe"},
            "calc": {"calc.exe", "calculatorapp.exe", "calculator.exe"},
            "paint": {"mspaint.exe"},
            "terminal": {"windowsterminal.exe", "wt.exe"},
            "cmd": {"cmd.exe"},
        }
        if name_clean in alias_map:
            target_exes.update(alias_map[name_clean])
        if display_name.lower() in alias_map:
            target_exes.update(alias_map[display_name.lower()])

        # Check if foreground matches
        is_foreground = False
        terms_to_match = [name_clean, display_name.lower()]
        if exe_name:
            terms_to_match.append(exe_name.replace(".exe", ""))

        if any(t in fg_title or t in fg_class for t in terms_to_match if t):
            is_foreground = True

        # Check running processes via psutil
        is_running = is_foreground
        found_pid = fg_pid if is_foreground else None

        if not is_running:
            try:
                from core.os_gateway.process_ops import _get_cached_process_list, invalidate_process_cache
                plist = _get_cached_process_list()
                for p in plist:
                    p_name = (p.get('name') or "").lower()
                    if target_exes and p_name in target_exes:
                        is_running = True
                        found_pid = p.get('pid')
                        if found_pid == fg_pid and fg_pid > 0:
                            is_foreground = True
                        break
                    elif any(t in p_name for t in terms_to_match if t and len(t) > 2):
                        is_running = True
                        found_pid = p.get('pid')
                        if found_pid == fg_pid and fg_pid > 0:
                            is_foreground = True
                        break

                if not is_running:
                    # Invalidate short-lived cache and scan once more in case process just started
                    invalidate_process_cache()
                    for p in _get_cached_process_list():
                        p_name = (p.get('name') or "").lower()
                        if target_exes and p_name in target_exes:
                            is_running = True
                            found_pid = p.get('pid')
                            if found_pid == fg_pid and fg_pid > 0:
                                is_foreground = True
                            break
                        elif any(t in p_name for t in terms_to_match if t and len(t) > 2):
                            is_running = True
                            found_pid = p.get('pid')
                            if found_pid == fg_pid and fg_pid > 0:
                                is_foreground = True
                            break
            except Exception:
                pass

        return {
            "name": name,
            "display_name": display_name,
            "target": target,
            "running": is_running,
            "foreground": is_foreground,
            "pid": found_pid,
            "window_title": fg_info.get("title") if is_foreground else None,
        }

    def focus_app(self, name: str) -> bool:
        """Attempt to bring a running application to the foreground."""
        state = self.get_app_state(name)
        display_name = state.get("display_name", name)
        terms = [display_name, name]
        try:
            import win32com.client
            wsh = win32com.client.Dispatch("WScript.Shell")
            for t in terms:
                if wsh.AppActivate(t):
                    return True
            if state.get("pid"):
                if wsh.AppActivate(state["pid"]):
                    return True
        except Exception:
            pass
        return False

    def smart_open(self, name: str, new_instance: bool = False) -> Dict[str, Any]:
        """
        Open app and return truthful result.
        Never reports success unless the underlying target launched without error.
        When new_instance is True, launches a new instance/window and verifies it.
        """
        import re
        import time

        # Defense-in-depth: strip instance modifier prefix if present
        m_mod = re.match(
            r'^(?:(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+(?:instance|window)\s+of\s+|'
            r'(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+)',
            name,
            re.IGNORECASE
        )
        # Defense-in-depth: strip conversational trailing clauses and fillers
        name = re.sub(r'\s+(?:i\s+need|i\s+want|to\s+be\s+open|on\s+the\s+screen|right\s+now|so\s+that|so\s+i\s+can|because|since|asap|now|immediately)\b.*$', '', name, flags=re.IGNORECASE).strip()
        prev_n = None
        while prev_n != name:
            prev_n = name
            name = re.sub(r'\s+(?:for\s+me|please|thanks|thank\s+you|app|application|browser|window|program)$', '', name, flags=re.IGNORECASE).strip()
        # Strip phrasal verbs, qualifiers, and stopword prefixes
        name = re.sub(r'^(?:bring\s+up|bring|switch\s+to|switch\s+back\s+to|up)\s+', '', name, flags=re.IGNORECASE).strip()
        name = re.sub(r'\s+(?:on\s+the\s+first\s+page|on\s+(?:the\s+)?(?:first\s+)?(?:screen|page)|to\s+(?:the\s+)?front|in\s+front|back)$', '', name, flags=re.IGNORECASE).strip()
        name = re.sub(r'^(?:the|a|an)\s+', '', name, flags=re.IGNORECASE).strip()
        name = re.sub(r'^(?:app|application|browser)\s+', '', name, flags=re.IGNORECASE).strip()
        name = re.sub(r'^(?:could\s+you\s+|can\s+you\s+|please\s+|launch\s+|open\s+|start\s+)+', '', name, flags=re.IGNORECASE).strip()
        name = re.sub(r'^(?:the|a|an)\s+', '', name, flags=re.IGNORECASE).strip()

        print(f"[SMART OPENER] Resolving: '{name}' (new_instance={new_instance})")

        resolved = self.resolve_detailed(name)
        if not resolved:
            # Fallback sub-phrase search (first 1-3 words) - NEVER resolve single stopwords
            stopwords = {"up", "on", "in", "to", "it", "at", "as", "by", "or", "an", "is", "my", "no", "so", "we", "he", "me", "do", "go", "be", "if", "us", "am", "the", "and"}
            words = name.split()
            for k in range(min(len(words), 3), 0, -1):
                sub_cand = " ".join(words[:k]).strip()
                if sub_cand.lower() in stopwords:
                    continue
                sub_res = self.resolve_detailed(sub_cand)
                if sub_res and self.indexer._is_legitimate_app(sub_res[0], sub_res[1]):
                    resolved = sub_res
                    break

        if not resolved:
            print(f"[SMART OPENER] Application not found: '{name}'")
            return {
                "success": False,
                "name": name,
                "display_name": name,
                "path": None,
                "message": f"Could not find '{name}' on your system."
            }

        display_name, target, match_type = resolved
        if not self.indexer._is_legitimate_app(display_name, target):
            print(f"[SMART OPENER] Rejected illegitimate application target: '{display_name}' ({target})")
            return {
                "success": False,
                "name": name,
                "display_name": display_name,
                "path": target,
                "message": f"Target '{display_name}' is a setup/uninstaller utility and cannot be opened as an application."
            }
        print(f"[SMART OPENER] Resolved '{name}' -> '{display_name}' ({target}) via {match_type}")

        # Pre-launch process tracking for verification when new_instance=True
        pids_before = set()
        alias_map = {
            "notepad": {"notepad.exe"},
            "chrome": {"chrome.exe"},
            "google chrome": {"chrome.exe"},
            "edge": {"msedge.exe"},
            "microsoft edge": {"msedge.exe"},
            "calculator": {"calc.exe", "calculatorapp.exe", "calculator.exe"},
            "calc": {"calc.exe", "calculatorapp.exe", "calculator.exe"},
            "paint": {"mspaint.exe"},
            "terminal": {"windowsterminal.exe", "wt.exe"},
            "cmd": {"cmd.exe"},
        }
        match_exes = alias_map.get(name.lower(), set())
        if display_name.lower() in alias_map:
            match_exes.update(alias_map[display_name.lower()])

        if new_instance:
            try:
                import psutil
                for p in psutil.process_iter(['pid', 'name']):
                    p_name = (p.info.get('name') or "").lower()
                    if match_exes and p_name in match_exes:
                        pids_before.add(p.info.get('pid'))
                    elif name.lower() in p_name or (len(name) > 3 and name.lower() in p_name):
                        pids_before.add(p.info.get('pid'))
            except Exception:
                pass

        try:
            # Launch Default Web Browser
            if target == "__default_browser__":
                import webbrowser
                try:
                    if new_instance:
                        webbrowser.open_new("https://www.google.com")
                    else:
                        webbrowser.open("https://www.google.com")
                    print(f"[SMART OPENER] Successfully opened default browser (new_instance={new_instance})")
                    return {
                        "success": True,
                        "name": name,
                        "display_name": "Browser",
                        "path": "default_browser",
                        "instance_mode": "NEW" if new_instance else "NORMAL",
                        "message": "Opened another instance of browser." if new_instance else "Opened default browser."
                    }
                except Exception as e:
                    for b_cand in ["Google Chrome", "Microsoft Edge", "Brave", "Firefox"]:
                        b_res = self.resolve_detailed(b_cand)
                        if b_res and b_res[1] != "__default_browser__":
                            return self.smart_open(b_cand, new_instance=new_instance)

            # Launch Shell App / Store Packaged App
            if target.startswith("shell:AppsFolder\\"):
                # If a direct .exe or .lnk exists for this application, prefer it
                direct_target = None
                direct_res = self.indexer._discover_on_demand(name)
                if direct_res and not direct_res[1].startswith("shell:AppsFolder\\"):
                    direct_target = direct_res[1]
                if direct_target and os.path.exists(direct_target):
                    try:
                        subprocess.Popen([direct_target], shell=False)
                    except Exception:
                        os.startfile(direct_target)
                else:
                    try:
                        os.startfile(target)
                    except Exception:
                        subprocess.Popen(["explorer.exe", target])

            # Launch Windows Protocol URI (e.g. microsoft.windows.camera:, ms-settings:)
            elif ":" in target and not os.path.isabs(target):
                os.startfile(target)

            # Launch Shortcut (.lnk)
            elif target.lower().endswith(".lnk"):
                if not os.path.exists(target):
                    return {
                        "success": False,
                        "name": name,
                        "display_name": display_name,
                        "path": target,
                        "message": f"Could not find {display_name} on your system."
                    }
                try:
                    os.startfile(target)
                except Exception:
                    subprocess.Popen(["explorer.exe", target])

            # Launch Directory
            elif os.path.isdir(target):
                os.startfile(target)

            # Launch Standard Executable (.exe) or absolute path
            elif target.lower().endswith(".exe") or os.path.isabs(target):
                resolved_exe = target if (os.path.isabs(target) and os.path.exists(target)) else (shutil.which(target) or target)
                if not os.path.exists(resolved_exe) and not shutil.which(resolved_exe):
                    return {
                        "success": False,
                        "name": name,
                        "display_name": display_name,
                        "path": target,
                        "message": f"Could not launch {display_name}: executable '{target}' was not found on your system."
                    }
                exe_lower = resolved_exe.lower()
                is_browser = any(b in exe_lower for b in ["chrome.exe", "msedge.exe", "brave.exe", "firefox.exe"])
                if new_instance and is_browser:
                    subprocess.Popen([resolved_exe, "--new-window"], shell=False)
                else:
                    try:
                        subprocess.Popen([resolved_exe], shell=False)
                    except Exception:
                        os.startfile(resolved_exe)

            else:
                os.startfile(target)

            # Verification for new instance
            if new_instance:
                new_instance_verified = False
                exe_lower = (target or "").lower()
                is_browser = any(b in exe_lower for b in ["chrome", "msedge", "brave", "firefox", "browser"])
                for _ in range(8):
                    time.sleep(0.2)
                    try:
                        import psutil
                        pids_after = set()
                        for p in psutil.process_iter(['pid', 'name']):
                            p_name = (p.info.get('name') or "").lower()
                            if match_exes and p_name in match_exes:
                                pids_after.add(p.info.get('pid'))
                            elif name.lower() in p_name or (len(name) > 3 and name.lower() in p_name):
                                pids_after.add(p.info.get('pid'))
                        if len(pids_after - pids_before) > 0 or len(pids_after) > len(pids_before):
                            new_instance_verified = True
                            break
                        elif is_browser and len(pids_after) > 0:
                            new_instance_verified = True
                            break
                        elif len(pids_before) == 0 and len(pids_after) > 0:
                            new_instance_verified = True
                            break
                    except Exception:
                        pass

                if not new_instance_verified and len(pids_before) > 0:
                    return {
                        "success": False,
                        "name": name,
                        "display_name": display_name,
                        "path": target,
                        "instance_mode": "NEW",
                        "message": f"{display_name} is already open and does not support creating an additional independent instance."
                    }

            msg = f"Opened another instance of {display_name}." if new_instance else f"Opened {display_name}."
            print(f"[SMART OPENER] Successfully opened: {display_name} ({target}) [instance_mode={'NEW' if new_instance else 'NORMAL'}]")
            return {
                "success": True,
                "name": name,
                "display_name": display_name,
                "path": target,
                "canonical": {
                    "display_name": display_name,
                    "executable": os.path.basename(target) if target else name,
                    "path": target,
                    "resolution_method": match_type
                },
                "instance_mode": "NEW" if new_instance else "NORMAL",
                "message": msg
            }

        except Exception as e:
            print(f"[SMART OPENER] Error opening {display_name} ({target}): {e}")
            return {
                "success": False,
                "name": name,
                "display_name": display_name,
                "path": target,
                "message": f"I couldn't open {display_name}: {str(e)}"
            }

    def search(self, name: str) -> Optional[str]:
        """Search for app without opening"""
        return self.resolve_name(name)

    def rebuild_index(self) -> None:
        """Force rebuild the system index"""
        print("[SMART OPENER] Rebuilding system index...")
        self.indexer.build_index()

    def get_index_info(self) -> Dict[str, Any]:
        """Get information about the current index"""
        return {
            "total_items": self.indexer.get_index_size(),
            "index_file": self.indexer.index_file,
            "cache_exists": os.path.exists(self.indexer.index_file)
        }

# Global instance
smart_opener = SmartOpener()
