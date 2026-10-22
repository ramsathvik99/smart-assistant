"""
Voice Migration Module.
Migrates legacy SAPI-trapped user voice configurations to natural neural voices
while preserving reversibility via 'previous_voice'.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

def is_sapi_voice_id(voice_id: Optional[str]) -> bool:
    if not voice_id or not isinstance(voice_id, str):
        return False
    v = voice_id.lower().strip()
    return any(marker in v for marker in ("hkey_", "speech\\voices", "tokens", "onecore", "desktop"))

def migrate_user_voice_to_neural(user_id: int) -> bool:
    """
    If a user's saved voice is a SAPI voice, no explicit provider choice was saved,
    and neural is available, switch to a gender-matching neural voice.
    Keeps the old value as 'previous_voice' so the user can switch back.
    """
    if not user_id:
        return False

    try:
        from extensions.system.tts_backend import NeuralTTSBackend
        if not NeuralTTSBackend().is_available():
            logger.info("[VOICE MIGRATION] Neural TTS unavailable — skipping migration for user %s", user_id)
            return False

        from core.configuration_service import get_config_service
        cfg = get_config_service()

        vid = cfg.get_preference(user_id, "voice_id", cfg.get_preference(user_id, "assistant_voice_id", None))
        if not vid or not is_sapi_voice_id(vid):
            return False

        # If user explicitly selected SAPI previously, respect that choice
        explicit_provider = cfg.get_preference(user_id, "explicit_provider_choice", None)
        if explicit_provider and "sapi" in str(explicit_provider).lower():
            logger.info("[VOICE MIGRATION] User %s has explicit SAPI preference — not migrating", user_id)
            return False

        # Determine gender match
        gender = str(cfg.get_preference(user_id, "voice_gender") or cfg.get_preference(user_id, "gender") or "female").lower()
        if "male" in gender and "female" not in gender:
            target_voice = "en-US-GuyNeural"
        else:
            target_voice = "en-US-JennyNeural"

        # Backup previous voice
        cfg.set_preference(user_id, "previous_voice", vid)
        cfg.set_preference(user_id, "previous_voice_provider", "sapi5")

        # Migrate to neural
        cfg.set_preference(user_id, "voice_id", target_voice)
        cfg.set_preference(user_id, "assistant_voice_id", target_voice)
        cfg.set_preference(user_id, "voice_provider", "neural")
        cfg.set_preference(user_id, "assistant_voice_provider", "neural")
        cfg.set_preference(user_id, "voice_engine", "neural")

        logger.info(
            "[VOICE MIGRATION] Migrated user %s from SAPI voice %r to Neural voice %r (saved backup in previous_voice)",
            user_id, vid, target_voice
        )
        return True
    except Exception as exc:
        logger.warning("[VOICE MIGRATION] Error migrating user %s voice: %s", user_id, exc)
        return False

def revert_user_voice_migration(user_id: int) -> bool:
    """
    Revert a previously migrated user voice back to their 'previous_voice' (SAPI).
    """
    if not user_id:
        return False

    try:
        from core.configuration_service import get_config_service
        cfg = get_config_service()

        prev_voice = cfg.get_preference(user_id, "previous_voice", None)
        if not prev_voice:
            return False

        prev_prov = cfg.get_preference(user_id, "previous_voice_provider", "sapi5")

        cfg.set_preference(user_id, "voice_provider", prev_prov)
        cfg.set_preference(user_id, "assistant_voice_provider", prev_prov)
        cfg.set_preference(user_id, "explicit_provider_choice", prev_prov)
        cfg.set_preference(user_id, "voice_id", prev_voice)
        cfg.set_preference(user_id, "assistant_voice_id", prev_voice)
        cfg.set_preference(user_id, "previous_voice", None)

        logger.info("[VOICE MIGRATION] Reverted user %s voice back to %r (%s)", user_id, prev_voice, prev_prov)
        return True
    except Exception as exc:
        logger.warning("[VOICE MIGRATION] Error reverting user %s voice: %s", user_id, exc)
        return False
