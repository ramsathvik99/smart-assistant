
import json
import os
import time

CACHE_FILE = os.path.join(os.path.dirname(__file__), "app_cache.json")

class AppRegistry:
    def __init__(self):
        self.apps = []
        self.last_scan = 0
        self.load()

    def load(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as f:
                    data = json.load(f)
                    self.apps = data.get("apps", [])
                    self.last_scan = data.get("last_scan", 0)
            except Exception as e:
                print(f"[Launcher] Cache load error: {e}")
                self.apps = []
        else:
            self.apps = []

    def save(self):
        data = {
            "last_scan": time.time(),
            "apps": self.apps
        }
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Launcher] Cache save error: {e}")

    def add_app(self, name, path, app_type="exe", app_id=None):
        # Check if exists to avoid dupes (simple check)
        for app in self.apps:
            if app["path"] == path:
                return
        
        entry = {
            "name": name,
            "path": path,
            "type": app_type,
            "lower_name": name.lower()
        }
        if app_id:
            entry["app_id"] = app_id
            
        self.apps.append(entry)

    def get_all_apps(self):
        return self.apps

    def clear(self):
        self.apps = []
