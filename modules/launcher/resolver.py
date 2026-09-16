
import difflib

class AppResolver:
    def __init__(self, registry):
        self.registry = registry

    def find_app(self, query):
        """
        Returns the best matching app or None.
        Query: "open spotify" -> "spotify" (cleaned by caller usually)
        """
        query = query.lower().strip()
        apps = self.registry.get_all_apps()
        
        if not apps:
            return None

        # 1. Exact Match
        for app in apps:
            if app["lower_name"] == query:
                return app
            
        # 2. Contains Match (high confidence)
        # e.g. "visual studio code" contains "code" -> maybe too broad
        # "google chrome" contains "chrome" -> good.
        # But "chrome.exe" vs "chrome"
        
        matches = []
        for app in apps:
            name = app["lower_name"]
            # remove .exe for matching if present (though scanner usually gets shortcut name which is clean)
            
            # Simple substring
            if query in name:
                matches.append(app)
                
        if len(matches) == 1:
            return matches[0]
            
        # 3. Fuzzy Match using difflib
        # Extract all names
        names = [app["lower_name"] for app in apps]
        
        # get_close_matches(word, possibilities, n=3, cutoff=0.6)
        close = difflib.get_close_matches(query, names, n=1, cutoff=0.6)
        
        if close:
            best_name = close[0]
            for app in apps:
                if app["lower_name"] == best_name:
                    return app
                    
        return None
