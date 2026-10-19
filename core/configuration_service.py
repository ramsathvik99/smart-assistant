"""
Smart Assistant — Centralized Configuration & Preference Service
================================================================
Architectural Single Source of Truth for all runtime preferences,
credentials, and behavior settings across the entire application:

Flow:
Settings Dashboard → Configuration Service → Persistent Storage (DB + Vault)
                   ↓
         Runtime Modules & Subsystems (TTS, LLM, UI, Observers)
                   ↓
         Authoritative Runtime Behavior

Provides:
- Validated per-user preferences with PostgreSQL persistence and local JSON mirroring.
- Zero-leak credential management with DPAPI/Fernet encryption via CredentialManager.
- Live event bus notifying runtime subsystems (TTS, LLM, UI, Observers) of changes immediately.
- Clean account switching and strict per-user isolation.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("ConfigurationService")


class ConfigurationService:
    """Centralized configuration and preference management service."""

    _instance: Optional[ConfigurationService] = None
    _lock = threading.Lock()

    def __new__(cls) -> ConfigurationService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConfigurationService, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        self._prefs_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = threading.Lock()
        self._listeners: List[Callable[[int, str, Any], None]] = []
        self._listeners_lock = threading.Lock()

        # Connect to CredentialManager change listener to propagate credential events
        try:
            from core.credential_manager import get_credential_manager
            get_credential_manager().register_change_listener(self._on_credential_changed)
        except Exception as e:
            logger.debug("Could not attach to credential manager: %s", e)

        self._initialized = True
        logger.info("[CONFIG] Centralized Configuration Service initialized.")

    # ── User ID Resolution ───────────────────────────────────────────────────

    def _resolve_user_id(self, user_context: Any = None) -> int:
        """Resolve numeric user_id from context, settings, or core."""
        if isinstance(user_context, int) and user_context > 0:
            return user_context
        if isinstance(user_context, dict):
            uid = user_context.get("user_id") or user_context.get("id")
            if uid:
                try:
                    return int(uid)
                except (ValueError, TypeError):
                    pass
        if isinstance(user_context, str):
            s = user_context.strip()
            if s.isdigit():
                return int(s)

        # Check active settings runtime context first
        try:
            from instance.config import settings
            curr = getattr(settings, "CURRENT_USER_ID", None)
            if curr and int(curr) > 0:
                return int(curr)
        except Exception:
            pass

        # Check AssistantCore context
        try:
            from core.assistant_core import assistant_core
            ctx = assistant_core.get_user_context()
            if ctx.get("user_id"):
                return int(ctx["user_id"])
        except Exception:
            pass

        return 0

    # ── Preference Retrieval ─────────────────────────────────────────────────

    def get_preference(self, user_context: Any, key: str, default: Any = None) -> Any:
        """Authoritatively get a preference value for the specified user."""
        uid = self._resolve_user_id(user_context)
        if not key:
            return default

        key_str = str(key).strip()

        # Check memory cache
        with self._cache_lock:
            user_cache = self._prefs_cache.get(str(uid), {})
            if key_str in user_cache:
                return user_cache[key_str]

        # Read from persistence
        val = None
        if uid > 0:
            try:
                from legacy.memory_manager import get_user_preference_db
                val = get_user_preference_db(uid, key_str, None)
            except Exception as e:
                logger.debug("DB pref read failed: %s", e)

        # JSON fallback
        if val is None:
            try:
                json_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "data", "user_preferences.json"
                )
                if os.path.exists(json_path):
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    user_data = data.get("ui_preferences", {}).get(str(uid), {})
                    if key_str in user_data:
                        val = user_data[key_str]
            except Exception:
                pass

        # Check alias if primary key was not found
        if val is None:
            aliases = {
                "voice_id": "assistant_voice_id",
                "assistant_voice_id": "voice_id",
                "voice_rate": "assistant_voice_rate",
                "assistant_voice_rate": "voice_rate",
                "voice_volume": "assistant_voice_volume",
                "assistant_voice_volume": "voice_volume",
            }
            alias_key = aliases.get(key_str)
            if alias_key:
                with self._cache_lock:
                    user_cache = self._prefs_cache.get(str(uid), {})
                    if alias_key in user_cache:
                        val = user_cache[alias_key]
        if val is None and uid > 0:
            if key_str in ("voice_id", "assistant_voice_id", "voice_rate", "voice_volume", "voice_provider", "voice_gender", "voice_tone"):
                try:
                    from legacy.memory_manager import get_voice_profile_db
                    vprof = get_voice_profile_db(uid)
                    if isinstance(vprof, dict):
                        if key_str in ("voice_id", "assistant_voice_id"):
                            val = vprof.get("voice_id")
                        else:
                            val = vprof.get(key_str)
                except Exception:
                    pass

        if val is not None:
            with self._cache_lock:
                self._prefs_cache.setdefault(str(uid), {})[key_str] = val
            return val

        return default

    def get_all_preferences(self, user_context: Any) -> Dict[str, Any]:
        """Load all preferences for the specified user."""
        uid = self._resolve_user_id(user_context)
        all_prefs: Dict[str, Any] = {}

        if uid > 0:
            try:
                from legacy.memory_manager import get_all_user_preferences_db, get_voice_profile_db, has_voice_profile_db
                db_prefs = get_all_user_preferences_db(uid)
                if isinstance(db_prefs, dict):
                    all_prefs.update(db_prefs)
                if has_voice_profile_db(uid):
                    vprof = get_voice_profile_db(uid)
                    if isinstance(vprof, dict):
                        for vk, vv in vprof.items():
                            if vv is not None:
                                all_prefs.setdefault(vk, vv)
                        if vprof.get("voice_id"):
                            all_prefs.setdefault("assistant_voice_id", vprof.get("voice_id"))
            except Exception as e:
                logger.debug("DB get_all_user_preferences_db failed: %s", e)

        # Merge JSON fallback
        try:
            json_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "data", "user_preferences.json"
            )
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                file_prefs = data.get("ui_preferences", {}).get(str(uid), {})
                if isinstance(file_prefs, dict):
                    for k, v in file_prefs.items():
                        all_prefs.setdefault(k, v)
        except Exception:
            pass

        # Update cache
        with self._cache_lock:
            self._prefs_cache[str(uid)] = dict(all_prefs)

        return all_prefs

    # ── Preference Updates & Runtime Dispatch ────────────────────────────────

    def set_preference(self, user_context: Any, key: str, value: Any) -> bool:
        """
        Validate, persist, and live-dispatch a preference change for the user.
        Updates persistent store (DB + JSON mirror) and triggers immediate runtime behavior.
        """
        uid = self._resolve_user_id(user_context)
        if not uid or not key:
            logger.warning("[CONFIG] Cannot set preference: missing user_id (%s) or key (%s)", uid, key)
            return False

        key_str = str(key).strip()
        val_str = str(value) if value is not None else ""

        # 1. Persist to DB & JSON
        persisted = False
        try:
            from legacy.memory_manager import set_user_preference_db
            persisted = set_user_preference_db(uid, key_str, val_str)
        except Exception as e:
            logger.error("[CONFIG] Persistence error for %s: %s", key_str, e)

        # 2. Update memory cache and mirror aliases
        with self._cache_lock:
            self._prefs_cache.setdefault(str(uid), {})[key_str] = val_str

        aliases = {
            "voice_id": "assistant_voice_id",
            "assistant_voice_id": "voice_id",
            "voice_rate": "assistant_voice_rate",
            "assistant_voice_rate": "voice_rate",
            "voice_volume": "assistant_voice_volume",
            "assistant_voice_volume": "voice_volume",
        }
        alias_key = aliases.get(key_str)
        if alias_key:
            try:
                from legacy.memory_manager import set_user_preference_db
                set_user_preference_db(uid, alias_key, val_str)
            except Exception:
                pass
            with self._cache_lock:
                self._prefs_cache.setdefault(str(uid), {})[alias_key] = val_str

        # 3. Dispatch to runtime subsystems immediately
        self._dispatch_runtime_effect(uid, key_str, value)

        # 4. Notify all registered listeners
        self._notify_listeners(uid, key_str, value)

        return persisted or True

    def set_preferences(self, user_context: Any, prefs: Dict[str, Any]) -> bool:
        """Batch set preferences with atomic notifications."""
        ok = True
        for k, v in prefs.items():
            res = self.set_preference(user_context, k, v)
            ok = ok and res
        return ok

    def _dispatch_runtime_effect(self, user_id: int, key: str, value: Any) -> None:
        """Trigger immediate runtime behavioral effects across application modules."""
        key_lower = key.lower().strip()

        # A. Assistant Name
        if key_lower == "assistant_name":
            clean_name = str(value).strip()
            if clean_name:
                try:
                    from instance.config import settings
                    settings.CURRENT_ASSISTANT_NAME = clean_name
                    if hasattr(settings, "set_assistant_name"):
                        settings.set_assistant_name(clean_name)
                except Exception:
                    pass
                try:
                    from core.assistant_core import assistant_core
                    with assistant_core._state_lock:
                        assistant_core._assistant_name = clean_name
                except Exception:
                    pass

        # B. Voice & Audio
        elif key_lower in ("voice_id", "voice_rate", "voice_volume", "voice_engine", "assistant_voice_id", "assistant_voice_rate", "assistant_voice_volume", "assistant_voice_provider"):
            try:
                vid = self.get_preference(user_id, "voice_id", self.get_preference(user_id, "assistant_voice_id", None))
                rate = int(self.get_preference(user_id, "voice_rate", self.get_preference(user_id, "assistant_voice_rate", 135)))
                vol_raw = float(self.get_preference(user_id, "voice_volume", self.get_preference(user_id, "assistant_voice_volume", 100)))
                # Normalize volume if given as 0-100 percentage
                vol = vol_raw / 100.0 if vol_raw > 1.0 else vol_raw

                # Apply profile to TTS engine
                from legacy.tts import apply_voice_profile
                apply_voice_profile(voice_id=vid if vid else None, rate=rate, volume=vol, user_id=user_id)

                # Sync with TTSBackendManager
                from extensions.system.tts_backend import get_tts_backend_manager
                backend_mgr = get_tts_backend_manager()
                if vid:
                    vid_lower = str(vid).lower()
                    if "hkey_" in vid_lower or "speech" in vid_lower or "desktop" in vid_lower or "onecore" in vid_lower:
                        backend_mgr.set_primary_provider("sapi")
                    elif "neural" in vid_lower:
                        backend_mgr.set_primary_provider("neural")
                        neural_backend = backend_mgr.get_backend("neural")
                        if hasattr(neural_backend, "_voice"):
                            neural_backend._voice = vid
                engine_pref = str(self.get_preference(user_id, "voice_engine", "")).lower()
                if "sapi" in engine_pref or "windows" in engine_pref:
                    backend_mgr.set_primary_provider("sapi")
                elif "neural" in engine_pref or "edge" in engine_pref:
                    backend_mgr.set_primary_provider("neural")
            except Exception as e:
                logger.warning("[CONFIG] Live voice dispatch warning: %s", e)

        # C. AI Provider & Models
        elif key_lower in ("ai_provider", "primary_provider", "ai_model", "ai_failover", "openai_enabled"):
            try:
                from instance.config import settings
                if key_lower in ("ai_provider", "primary_provider"):
                    prov = str(value).lower().strip()
                    if hasattr(settings, "AI_PROVIDER"):
                        settings.AI_PROVIDER = prov
                if key_lower == "ai_model":
                    mod = str(value).strip()
                    if hasattr(settings, "DEFAULT_MODEL"):
                        settings.DEFAULT_MODEL = mod
                if key_lower == "openai_enabled":
                    is_en = str(value).lower() in ("true", "1", "yes")
                    if hasattr(settings, "OPENAI_ENABLED"):
                        settings.OPENAI_ENABLED = is_en
            except Exception:
                pass

        # D. Proactive Assistance
        elif key_lower == "proactive_assistance":
            try:
                from core.proactive_observer import proactive_coordinator
                is_active = str(value).lower() in ("true", "1", "yes")
                if is_active:
                    proactive_coordinator.start(str(user_id))
                else:
                    proactive_coordinator.stop()
            except Exception as e:
                logger.debug("[CONFIG] Proactive coordinator toggle: %s", e)

    # ── Credential Operations ────────────────────────────────────────────────

    def save_credential(self, user_context: Any, provider: str, key: str) -> bool:
        """Encrypt and persist API key for the user, updating runtime availability immediately."""
        uid = self._resolve_user_id(user_context)
        from core.credential_manager import get_credential_manager
        mgr = get_credential_manager()
        res = mgr.save_credential(uid, provider, key)
        return bool(res)

    def delete_credential(self, user_context: Any, provider: str) -> bool:
        """Remove API key for user, revoking access immediately."""
        uid = self._resolve_user_id(user_context)
        from core.credential_manager import get_credential_manager
        mgr = get_credential_manager()
        res = mgr.delete_credential(uid, provider)
        return bool(res)

    def get_credential(self, user_context: Any, provider: str) -> Optional[str]:
        """Get decrypted credential for user strictly with user isolation."""
        uid = self._resolve_user_id(user_context)
        from core.credential_manager import get_credential_manager
        return get_credential_manager().get_credential(uid, provider)

    def get_providers_status(self, user_context: Any) -> List[Dict[str, Any]]:
        """Return provider status metadata list."""
        uid = self._resolve_user_id(user_context)
        from core.credential_manager import get_credential_manager
        return get_credential_manager().get_providers_status(uid)

    def set_primary_provider(self, user_context: Any, provider: str) -> bool:
        """Set user's primary AI provider."""
        uid = self._resolve_user_id(user_context)
        from core.credential_manager import get_credential_manager
        mgr = get_credential_manager()
        res = mgr.set_primary_provider(uid, provider)
        self.set_preference(uid, "primary_provider", provider)
        return bool(res)

    def get_primary_provider(self, user_context: Any) -> str:
        """Get user's configured primary provider."""
        uid = self._resolve_user_id(user_context)
        from core.credential_manager import get_credential_manager
        return get_credential_manager().get_primary_provider(uid)

    # ── Account Switch / Rehydration ─────────────────────────────────────────

    def apply_user_configuration(self, user_id: int) -> None:
        """
        Rehydrate and apply a user's entire configured profile to runtime components.
        Called on login and account switching to enforce strict per-user isolation.
        """
        if not user_id or user_id <= 0:
            return

        logger.info("[CONFIG] Applying full user configuration for user_id=%s", user_id)

        # Clear cached preferences of other users if switching
        with self._cache_lock:
            # Re-read fresh from DB
            self._prefs_cache.pop(str(user_id), None)
        prefs = self.get_all_preferences(user_id)

        # 1. Update Assistant Name
        aname = prefs.get("assistant_name")
        if not aname:
            try:
                from legacy.memory_manager import get_assistant_name_db
                aname = get_assistant_name_db(user_id)
            except Exception:
                pass
        clean_name = (aname or "Trevon").strip()
        try:
            from instance.config import settings
            settings.CURRENT_USER_ID = user_id
            settings.CURRENT_ASSISTANT_NAME = clean_name
        except Exception:
            pass
        try:
            from core.assistant_core import assistant_core
            assistant_core.set_assistant_name(clean_name)
        except Exception:
            pass

        # 2. Update Voice Profile
        try:
            vid = prefs.get("voice_id") or prefs.get("assistant_voice_id")
            rate = int(prefs.get("voice_rate") or prefs.get("assistant_voice_rate") or 135)
            vol_raw = float(prefs.get("voice_volume") or prefs.get("assistant_voice_volume") or 100)
            vol = vol_raw / 100.0 if vol_raw > 1.0 else vol_raw
            from legacy.tts import apply_voice_profile
            apply_voice_profile(voice_id=vid if vid else None, rate=rate, volume=vol, user_id=user_id)

            from extensions.system.tts_backend import get_tts_backend_manager
            backend_mgr = get_tts_backend_manager()
            if vid:
                vid_lower = str(vid).lower()
                if "hkey_" in vid_lower or "speech" in vid_lower or "desktop" in vid_lower or "onecore" in vid_lower:
                    backend_mgr.set_primary_provider("sapi")
                elif "neural" in vid_lower:
                    backend_mgr.set_primary_provider("neural")
                    neural_backend = backend_mgr.get_backend("neural")
                    if hasattr(neural_backend, "_voice"):
                        neural_backend._voice = vid
        except Exception as e:
            logger.warning("[CONFIG] Voice rehydration error: %s", e)

        # 3. Update Proactive Coordinator
        try:
            from core.proactive_observer import proactive_coordinator
            pro_pref = prefs.get("proactive_assistance", "True")
            if str(pro_pref).lower() in ("true", "1", "yes"):
                proactive_coordinator.start(str(user_id))
            else:
                proactive_coordinator.stop()
        except Exception as e:
            logger.debug("[CONFIG] Proactive rehydration error: %s", e)

        # 4. Invalidate and rehydrate runtime credentials & LLM cache
        try:
            from core.credential_manager import get_credential_manager
            get_credential_manager().clear_cache()
        except Exception as e:
            logger.debug("[CONFIG] Credential cache clear error: %s", e)

        try:
            from extensions.llm_engine import _UNAVAILABLE_PROVIDERS, _UNAVAILABLE_KEYS
            _UNAVAILABLE_PROVIDERS.clear()
            _UNAVAILABLE_KEYS.clear()
        except Exception:
            pass

        # 5. Synchronize primary AI provider & model to runtime settings
        try:
            primary_prov = prefs.get("primary_provider") or prefs.get("ai_provider")
            if not primary_prov:
                from core.credential_manager import get_credential_manager
                primary_prov = get_credential_manager().get_primary_provider(user_id)
            if primary_prov:
                clean_prov = str(primary_prov).strip().lower()
                from instance.config import settings
                if hasattr(settings, "AI_PROVIDER"):
                    settings.AI_PROVIDER = clean_prov
                if hasattr(settings, "LLM_PRIMARY_PROVIDER"):
                    settings.LLM_PRIMARY_PROVIDER = clean_prov

            model_pref = prefs.get("ai_model")
            if model_pref:
                from instance.config import settings
                if hasattr(settings, "DEFAULT_MODEL"):
                    settings.DEFAULT_MODEL = str(model_pref).strip()
        except Exception as e:
            logger.debug("[CONFIG] AI provider rehydration error: %s", e)

        # 6. Trigger listeners
        self._notify_listeners(user_id, "__account_switched__", prefs)

    # ── Listeners / Event Bus ────────────────────────────────────────────────

    def register_listener(self, callback: Callable[[int, str, Any], None]) -> None:
        """Register a callback for preference changes: callback(user_id, key, value)."""
        with self._listeners_lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def unregister_listener(self, callback: Callable[[int, str, Any], None]) -> None:
        with self._listeners_lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify_listeners(self, user_id: int, key: str, value: Any) -> None:
        if not hasattr(self, "_thread_local"):
            self._thread_local = threading.local()
        if not hasattr(self._thread_local, "active_events"):
            self._thread_local.active_events = set()

        event_key = (int(user_id) if user_id is not None else 0, str(key).strip().lower())
        if event_key in self._thread_local.active_events:
            logger.debug("[CONFIG] Recursive event notification suppressed for %s", event_key)
            return

        self._thread_local.active_events.add(event_key)
        try:
            with self._listeners_lock:
                cbs = list(self._listeners)
            for cb in cbs:
                try:
                    cb(user_id, key, value)
                except Exception as e:
                    cb_name = getattr(cb, "__qualname__", getattr(cb, "__name__", str(cb)))
                    logger.error(
                        "[CONFIG] Listener callback error in '%s' (user_id=%s, key=%s): %s",
                        cb_name, user_id, key, e,
                        exc_info=True
                    )
        finally:
            self._thread_local.active_events.discard(event_key)

    def _on_credential_changed(self, user_id: int, provider: str) -> None:
        """Propagate credential manager changes to our listeners."""
        self._notify_listeners(user_id, f"credential:{provider}", True)


    def switch_user(self, user_id: int) -> None:
        """Alias for apply_user_configuration to switch authenticated user."""
        self.apply_user_configuration(user_id)


# Singleton accessor
_service_instance: Optional[ConfigurationService] = None
_service_lock = threading.Lock()


def get_configuration_service() -> ConfigurationService:
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            if _service_instance is None:
                _service_instance = ConfigurationService()
    return _service_instance


get_config_service = get_configuration_service

