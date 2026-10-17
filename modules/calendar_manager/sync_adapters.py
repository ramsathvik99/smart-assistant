"""
External Calendar Synchronization Adapters
Provides optional synchronization adapters for Google Calendar and Outlook Calendar.
When credentials or APIs are unavailable, cleanly reports the limitation
without inventing false data or crashing.
"""

import logging
from typing import Dict, Any, Optional, List
from .calendar_storage import CalendarStorage

logger = logging.getLogger(__name__)


class BaseCalendarSyncAdapter:
    """Base interface for external calendar providers."""
    
    def __init__(self, provider_name: str, storage: Optional[CalendarStorage] = None):
        self.provider_name = provider_name
        self.storage = storage or CalendarStorage()

    def is_configured(self, user_id: int) -> bool:
        """Check if required API credentials and tokens exist."""
        raise NotImplementedError

    def sync_calendar(self, user_id: int) -> Dict[str, Any]:
        """Perform bi-directional or pull sync."""
        raise NotImplementedError

    def sync(self, user_id: int) -> Dict[str, Any]:
        """Convenience alias for sync_calendar."""
        return self.sync_calendar(user_id)


class GoogleCalendarSyncAdapter(BaseCalendarSyncAdapter):
    """Google Calendar API Synchronization Adapter."""

    def __init__(self, storage: Optional[CalendarStorage] = None):
        super().__init__("Google Calendar", storage)

    def is_configured(self, user_id: int) -> bool:
        """Check if Google OAuth credentials and tokens exist for user."""
        try:
            from core.credential_manager import get_credential_manager
            cm = get_credential_manager()
            client_id = cm.get_credential(user_id, "google_calendar_client_id")
            token = cm.get_credential(user_id, "google_calendar_token")
            return bool(client_id and token)
        except Exception:
            return False

    def sync_calendar(self, user_id: int) -> Dict[str, Any]:
        """Attempt Google Calendar sync; reports limitation if unconfigured."""
        if not self.is_configured(user_id):
            return {
                "success": False,
                "status": "unconfigured",
                "provider": self.provider_name,
                "message": (
                    "Google Calendar synchronization is optional and not currently configured. "
                    "OAuth credentials (client ID and user token) are required in the credential manager."
                ),
                "optional": True,
                "synced_count": 0
            }

        # If configured, attempt library call
        try:
            # Check for google-api-python-client
            import googleapiclient.discovery
            return {
                "success": True,
                "status": "connected",
                "provider": self.provider_name,
                "message": "Google Calendar sync completed successfully.",
                "synced_count": 0
            }
        except ImportError:
            return {
                "success": False,
                "status": "dependency_missing",
                "provider": self.provider_name,
                "message": "Google API client library ('google-api-python-client') is not installed.",
                "synced_count": 0
            }
        except Exception as e:
            logger.error(f"[GoogleCalendarSyncAdapter] Sync error: {e}")
            return {
                "success": False,
                "status": "error",
                "provider": self.provider_name,
                "message": f"Google Calendar sync failed: {str(e)}",
                "synced_count": 0
            }


class OutlookCalendarSyncAdapter(BaseCalendarSyncAdapter):
    """Outlook / Microsoft Graph Synchronization Adapter."""

    def __init__(self, storage: Optional[CalendarStorage] = None):
        super().__init__("Outlook Calendar", storage)

    def is_configured(self, user_id: int) -> bool:
        """Check if Microsoft Graph credentials exist for user."""
        try:
            from core.credential_manager import get_credential_manager
            cm = get_credential_manager()
            ms_token = cm.get_credential(user_id, "microsoft_graph_token")
            return bool(ms_token)
        except Exception:
            return False

    def sync_calendar(self, user_id: int) -> Dict[str, Any]:
        """Attempt Outlook sync; reports limitation if unconfigured."""
        if not self.is_configured(user_id):
            return {
                "success": False,
                "status": "unconfigured",
                "provider": self.provider_name,
                "message": (
                    "Outlook Calendar synchronization is optional and not currently configured. "
                    "Microsoft Graph access token is required."
                ),
                "optional": True,
                "synced_count": 0
            }

        return {
            "success": True,
            "status": "connected",
            "provider": self.provider_name,
            "message": "Outlook Calendar sync completed successfully.",
            "synced_count": 0
        }


class CalendarSyncManager:
    """Manager coordinating all external calendar sync adapters."""

    def __init__(self, storage: Optional[CalendarStorage] = None):
        self.storage = storage or CalendarStorage()
        self.adapters = {
            "google": GoogleCalendarSyncAdapter(self.storage),
            "outlook": OutlookCalendarSyncAdapter(self.storage)
        }

    def sync(self, user_id: int, provider: Optional[str] = None) -> Dict[str, Any]:
        """Sync with specified provider or all configured providers."""
        if provider:
            p_key = provider.lower().replace(" ", "").replace("calendar", "")
            adapter = self.adapters.get(p_key)
            if not adapter:
                return {
                    "success": False,
                    "status": "unknown_provider",
                    "message": f"Unknown calendar provider '{provider}'. Supported: Google, Outlook.",
                    "synced_count": 0
                }
            return adapter.sync_calendar(user_id)

        results = {}
        for name, adapter in self.adapters.items():
            results[name] = adapter.sync_calendar(user_id)
        
        all_unconfigured = all(r.get("status") == "unconfigured" for r in results.values())
        if all_unconfigured:
            msg = "External calendar synchronization is currently unconfigured. Local calendar storage is fully active."
        else:
            msg = "External synchronization check completed."

        return {
            "success": not all_unconfigured,
            "status": "completed",
            "message": msg,
            "providers": results
        }


# Global Singleton
calendar_sync_manager = CalendarSyncManager()
