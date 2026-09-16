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

    def resolve_detailed(self, name: str) -> Optional[Tuple[str, str, str]]:
        """
        Resolve app name to (display_name, launch_target, match_type).
        Checks Windows built-in URIs first for standard tools, then queries dynamic indexer.
        """
        name_clean = name.lower().strip()

        # 1. Check native Windows built-ins / URI schemes
        if name_clean in self.windows_builtins:
            target = self.windows_builtins[name_clean]
            # Protocol URI (e.g. microsoft.windows.camera:, ms-settings:)
            if ":" in target and not os.path.isabs(target):
                dname = "Windows Settings" if "settings" in name_clean else name_clean.title()
                return (dname, target, "builtin_uri")
            # System executable via PATH
            which_path = shutil.which(target)
            if which_path and os.path.exists(which_path):
                return (name_clean.title(), which_path, "builtin_exe")
            return (name_clean.title(), target, "builtin")

        # 2. Query dynamic multi-tier system indexer
        detailed = self.indexer.resolve_detailed(name_clean)
        if detailed:
            return detailed

        # 3. System PATH fallback
        which_path = shutil.which(name_clean) or shutil.which(f"{name_clean}.exe")
        if which_path and os.path.exists(which_path):
            dname = os.path.splitext(os.path.basename(which_path))[0].title()
            return (dname, which_path, "path")

        return None

    def resolve_name(self, name: str) -> Optional[str]:
        """Resolve app name to launch target (backward compatibility)"""
        res = self.resolve_detailed(name)
        return res[1] if res else None

    def smart_open(self, name: str) -> Dict[str, Any]:
        """
        Open app and return truthful result.
        Never reports success unless the underlying target launched without error.
        """
        print(f"[SMART OPENER] Resolving: '{name}'")

        resolved = self.resolve_detailed(name)
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
        print(f"[SMART OPENER] Resolved '{name}' -> '{display_name}' ({target}) via {match_type}")

        try:
            # Launch Shell App / Store Packaged App
            if target.startswith("shell:AppsFolder\\"):
                try:
                    subprocess.Popen(["explorer.exe", target])
                except Exception:
                    os.startfile(target)

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
                os.startfile(target)

            # Launch Directory
            elif os.path.isdir(target):
                os.startfile(target)

            # Launch Standard Executable (.exe) or absolute path
            elif target.lower().endswith(".exe") or os.path.isabs(target):
                if not os.path.exists(target) and not shutil.which(target):
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
                    subprocess.Popen([target], shell=False)

            else:
                os.startfile(target)

            print(f"[SMART OPENER] Successfully opened: {display_name} ({target})")
            return {
                "success": True,
                "name": name,
                "display_name": display_name,
                "path": target,
                "message": f"Opened {display_name}."
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
