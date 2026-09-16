# extensions/services/app_service.py

from extensions.system.smart_opener import smart_opener


class AppService:
    """
    Application launching service layer using smart opener only.
    Completely replaces LauncherEngine with smart_opener system.
    """

    def __init__(self):
        # No launcher engine - use smart_opener directly
        pass

    def open(self, name: str) -> dict:
        """Use smart_opener as the ONLY execution engine"""
        return smart_opener.smart_open(name)

    def find(self, name: str):
        """Search using smart_opener"""
        try:
            return smart_opener.search(name)
        except Exception:
            return None
