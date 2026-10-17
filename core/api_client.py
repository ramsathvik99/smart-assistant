"""
Smart Assistant — Desktop Client API Integration Layer
Allows the desktop assistant client (.exe) to communicate with the Production
Backend API over HTTPS/REST with secure session token authentication.
Never embeds database credentials or LLM secrets in the client binary.
Strictly disallows silent local database fallback in production builds.
"""

import os
import json
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List

class SmartAssistantApiClient:
    """
    API client for desktop application (.exe).
    Enforces strict production vs development environment boundaries.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.app_env = os.getenv("APP_ENV", "development").lower()
        self.allow_local_fallback = os.getenv("ALLOW_LOCAL_FALLBACK", "false" if self.app_env == "production" else "true").lower() in ("true", "1", "yes")
        
        default_url = "https://api.assistant.trevonlabs.com" if self.app_env == "production" else "http://localhost:8000"
        self.base_url = (base_url or os.getenv("API_BASE_URL", default_url)).rstrip("/")
        
        # Enforce production security invariant
        if self.app_env == "production":
            local_patterns = ["localhost", "127.0.0.1", "0.0.0.0", "192.168.", "10.0.", "172.16."]
            is_local = any(pat in self.base_url for pat in local_patterns)
            allow_test_override = os.getenv("ALLOW_TEST_LOCAL_PRODUCTION", "false").lower() in ("true", "1")
            if is_local and not allow_test_override:
                raise ValueError(f"Security Policy Violation: Production build cannot point to local development address: {self.base_url}")

        self.token: Optional[str] = None
        self.user_id: Optional[int] = None
        self.username: Optional[str] = None
        self.timeout = int(os.getenv("API_TIMEOUT", "15"))

    def set_session(self, user_id: int, username: str, token: str):
        """Configure authenticated session token."""
        if user_id is None:
            raise ValueError("user_id cannot be None")
        self.user_id = int(user_id)
        self.username = username
        self.token = token

    def clear_session(self):
        """Clear active session credentials."""
        self.user_id = None
        self.username = None
        self.token = None

    def _request(self, endpoint: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute HTTP request with Bearer authorization header."""
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"SmartAssistant-Desktop/2.0 ({self.app_env})"
        }

        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_body = resp.read().decode("utf-8")
                return json.loads(resp_body)
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8")
                return json.loads(err_body)
            except Exception:
                return {"success": False, "error": f"HTTP {e.code}: {e.reason}", "status_code": e.code}
        except Exception as e:
            if self.app_env == "production":
                return {
                    "success": False,
                    "error": "Smart Assistant Cloud API is unreachable. Please verify your internet connection.",
                    "code": "NETWORK_OFFLINE",
                    "details": str(e)
                }
            return {"success": False, "error": str(e), "code": "CONNECTION_FAILED"}

    # ── Auth Endpoints ────────────────────────────────────────────────────────
    def check_username(self, username: str) -> Dict[str, Any]:
        return self._request("/api/auth/check-username", method="POST", payload={"username": username})

    def validate_candidate_key(self, provider: str, api_key: str) -> Dict[str, Any]:
        return self._request("/api/credentials/validate", method="POST", payload={"provider": provider, "api_key": api_key})

    def signup(self, username: str, password: str) -> Dict[str, Any]:
        res = self._request("/api/auth/signup", method="POST", payload={"username": username, "password": password})
        if res.get("success") and res.get("token"):
            self.set_session(res["user_id"], res["username"], res["token"])
        return res

    def login(self, username: str, password: str) -> Dict[str, Any]:
        res = self._request("/api/auth/login", method="POST", payload={"username": username, "password": password})
        if res.get("success") and res.get("token"):
            self.set_session(res["user_id"], res["username"], res["token"])
        return res

    def logout(self) -> Dict[str, Any]:
        res = self._request("/api/auth/logout", method="POST")
        self.clear_session()
        return res

    # ── Core Operations ───────────────────────────────────────────────────────
    def execute_command(self, command: str) -> Dict[str, Any]:
        return self._request("/api/command", method="POST", payload={"command": command})

    def get_user_profile(self) -> Dict[str, Any]:
        return self._request("/api/users/me", method="GET")

    def export_data(self) -> Dict[str, Any]:
        return self._request("/api/users/me/export", method="GET")

    def delete_account(self) -> Dict[str, Any]:
        return self._request("/api/users/me/delete", method="DELETE")

    # ── Memory & Facts ────────────────────────────────────────────────────────
    def get_memories(self) -> Dict[str, Any]:
        return self._request("/api/memories", method="GET")

    def search_memories(self, query: str) -> Dict[str, Any]:
        return self._request("/api/memories/search", method="POST", payload={"query": query})

    def set_memory_fact(self, key: str, value: str) -> Dict[str, Any]:
        return self._request("/api/memories/facts", method="POST", payload={"key": key, "value": value})

    # ── Reminders & Calendar ──────────────────────────────────────────────────
    def get_reminders(self) -> Dict[str, Any]:
        return self._request("/api/reminders", method="GET")

    def get_calendar_events(self) -> Dict[str, Any]:
        return self._request("/api/calendar", method="GET")

    # ── Health Check ──────────────────────────────────────────────────────────
    def check_health(self) -> Dict[str, Any]:
        return self._request("/api/health", method="GET")

    # ── Per-User API Credentials ─────────────────────────────────────────────
    def get_credentials_status(self) -> Dict[str, Any]:
        return self._request("/api/credentials", method="GET")

    def save_credential(self, provider: str, api_key: str) -> Dict[str, Any]:
        return self._request("/api/credentials", method="POST", payload={"provider": provider, "api_key": api_key})

    def delete_credential(self, provider: str) -> Dict[str, Any]:
        return self._request(f"/api/credentials?provider={provider}", method="DELETE")

    def test_credential(self, provider: str, api_key: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"provider": provider}
        if api_key is not None:
            payload["api_key"] = api_key
        return self._request("/api/credentials/test", method="POST", payload=payload)

    def get_api_setup_status(self) -> Dict[str, Any]:
        return self._request("/api/credentials/setup-status", method="GET")

    def set_api_setup_status(self, completed: bool = True) -> Dict[str, Any]:
        return self._request("/api/credentials/setup-status", method="POST", payload={"completed": completed})


# Global singleton
_api_client_instance: Optional[SmartAssistantApiClient] = None

def get_api_client() -> SmartAssistantApiClient:
    global _api_client_instance
    if _api_client_instance is None:
        _api_client_instance = SmartAssistantApiClient()
    return _api_client_instance
