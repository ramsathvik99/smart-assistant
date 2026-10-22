"""
Voice Catalog Module.
Provides a unified catalogue of available voices for the UI pickers.
Orders high-fidelity neural voices first (labelled 'Natural'),
followed by local Windows SAPI voices (labelled 'Basic Windows voices').
"""

from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

def get_voice_catalog() -> List[Dict[str, Any]]:
    """
    Return list of voices to offer in the UI:
    1. Neural voices (Natural) first
    2. SAPI voices (Basic Windows voices) second
    """
    catalog: List[Dict[str, Any]] = []
    seen_ids = set()

    # 1. Neural Voices (Natural)
    try:
        from extensions.system.tts_backend import NeuralTTSBackend
        neural_backend = NeuralTTSBackend()
        raw_neural = neural_backend.get_voices()
        for v in raw_neural:
            vid = getattr(v, "id", "")
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)
            name = getattr(v, "name", vid)
            # Ensure "Natural" label in name for clarity
            if "Natural" not in name:
                name = f"{name} (Natural)"
            catalog.append({
                "id": vid,
                "name": name,
                "gender": getattr(v, "gender", "female"),
                "language": getattr(v, "language", "en-US"),
                "provider": "neural",
                "category": "Natural",
                "label": f"{name} — {getattr(v, 'gender', 'female').title()} ({getattr(v, 'language', 'en-US')}, Natural)",
            })
    except Exception as e:
        logger.warning("[VOICE CATALOG] Could not load neural voices: %s", e)

    # 2. SAPI / OneCore Voices (Basic Windows voices)
    try:
        from legacy.tts import enumerate_voices
        raw_sapi = enumerate_voices()
        for v in raw_sapi:
            vid = v.get("id", "")
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)
            name = v.get("name", "Windows Voice")
            gender = v.get("gender", "female")
            lang = v.get("language", "English")
            catalog.append({
                "id": vid,
                "name": f"{name} (Basic Windows voice)",
                "gender": gender,
                "language": lang,
                "provider": "sapi5",
                "category": "Basic Windows voices",
                "label": f"{name} — {gender.title()} ({lang}, Basic Windows voice)",
            })
    except Exception as e:
        logger.warning("[VOICE CATALOG] Could not load SAPI voices: %s", e)

    return catalog
