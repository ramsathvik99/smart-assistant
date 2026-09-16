
import webbrowser
import os
import time
from extensions.context_manager import get_manager

class BrowserEngine:
    def __init__(self):
        self.context_manager = get_manager()
        # Common browser executables on Windows
        self.BROWSERS = ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"]

    def open_page(self, name: str, url: str):
        """Opens a URL using the user's preferred browser."""
        preferred = self.context_manager.get_active_preference("browser", "chrome")
        print(f"[BrowserEngine] Opening {name} at {url} (Preferred: {preferred})")
        
        # Mapping common names to webbrowser keys
        browser_map = {
            "chrome": "google-chrome",
            "firefox": "firefox",
            "brave": "brave",
            "edge": "msedge"
        }
        
        success = False
        try:
            b_key = browser_map.get(preferred.lower(), preferred.lower())
            controller = webbrowser.get(b_key)
            controller.open(url)
            success = True
        except Exception:
            # Fallback to default
            webbrowser.open(url)
        
        # Set context so we know what's open
        self.context_manager.set_active_context(
            context_type="browser",
            name=name,
            metadata={"url": url, "browser_used": preferred if success else "default"}
        )
        return f"Opening {name}."

    def close_browser(self, target_name: str = None):
        """
        Closes the browser if active context matches or if generic 'close browser' is requested.
        """
        active_context = self.context_manager.get_active_context()
        
        # If specific target (e.g. "youtube"), check if it matches active context
        if target_name:
            if active_context["type"] == "browser" and active_context["name"] == target_name.lower():
                pass # Match found, proceed to kill
            elif target_name.lower() in ["browser", "internet", "web"]:
                pass # Generic request, proceed if browser is active
            else:
                return f"I couldn't find {target_name} running."
        else:
            # No target, just close whatever is active if it's a browser
            if active_context["type"] != "browser":
                return "No active browser session found."

        # Kill common browser processes
        killed_any = False
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    process_name = proc.info['name'].lower()
                    if any(browser.lower().replace('.exe', '') in process_name for browser in self.BROWSERS):
                        proc.terminate()
                        killed_any = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            # Fallback to subprocess if psutil not available
            import subprocess
            for browser in self.BROWSERS:
                cmd = f"taskkill /IM {browser} /F >nul 2>&1"
                if subprocess.run(cmd, shell=True, capture_output=True).returncode == 0:
                    killed_any = True
        
        # Clear context
        self.context_manager.clear_context()
        
        if killed_any:
            return f"{target_name.capitalize() if target_name else 'Browser'} closed successfully."
        else:
            # Maybe they were already closed or using an uncommon browser
            return f"Browser closed."
