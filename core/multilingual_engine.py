"""
Multilingual Engine for Smart Assistant
Provides seamless, zero-selector language detection, translation, and speech recognition.
"""

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

@dataclass
class LanguageDetectionResult:
    language: str         # 2-letter ISO code: 'en', 'te', 'hi', 'ta', 'es', 'fr', etc.
    locale: str           # Full locale: 'en-US', 'te-IN', 'hi-IN', 'ta-IN', 'es-ES', etc.
    confidence: float     # 0.0 - 1.0
    script: str           # 'telugu', 'devanagari', 'tamil', 'latin', etc.
    is_multilingual: bool # True if not 'en'


class MultilingualEngine:
    """Canonical engine for multilingual identification, intention normalization, and speech."""

    LOCALE_MAP = {
        "en": "en-US",
        "te": "te-IN",
        "hi": "hi-IN",
        "ta": "ta-IN",
        "kn": "kn-IN",
        "ml": "ml-IN",
        "es": "es-ES",
        "fr": "fr-FR",
        "de": "de-DE",
        "it": "it-IT",
        "bn": "bn-IN",
        "mr": "mr-IN",
        "gu": "gu-IN",
    }

    VOICE_MAP = {
        "en": "en-US-JennyNeural",
        "te": "te-IN-ShrutiNeural",
        "hi": "hi-IN-SwaraNeural",
        "ta": "ta-IN-PallaviNeural",
        "kn": "kn-IN-SapnaNeural",
        "ml": "ml-IN-SobhanaNeural",
        "es": "es-ES-ElviraNeural",
        "fr": "fr-FR-DeniseNeural",
        "de": "de-DE-KatjaNeural",
        "it": "it-IT-ElsaNeural",
        "bn": "bn-IN-TanishaaNeural",
        "mr": "mr-IN-AarohiNeural",
        "gu": "gu-IN-DhwaniNeural",
    }

    SHORT_AMBIGUOUS_TOKENS = {
        "yes", "no", "ok", "okay", "yeah", "yep", "nope", "sure",
        "cancel", "stop", "repeat", "say that again", "what", "come again",
        "move it", "confirm", "proceed", "go ahead", "done", "next"
    }

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "MultilingualEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._user_active_languages: Dict[Any, str] = {}
        self._state_lock = threading.Lock()
        self._translation_cache: Dict[Tuple[str, str, str], str] = {}
        self._detection_cache: Dict[str, LanguageDetectionResult] = {}
        self._translator = None

    def _get_translator(self):
        if self._translator is None:
            try:
                import googletrans
                self._translator = googletrans.Translator()
            except Exception as e:
                logger.warning(f"[MULTILINGUAL] Failed to initialize googletrans: {e}")
        return self._translator

    def set_active_language(self, user_id: Any, lang: str):
        """Set the active conversational language for a user session."""
        with self._state_lock:
            uid = user_id or 1
            norm_lang = (lang or "en").strip().lower()[:2]
            if norm_lang in self.LOCALE_MAP:
                self._user_active_languages[uid] = norm_lang
            else:
                self._user_active_languages[uid] = "en"

    def get_active_language(self, user_id: Any) -> str:
        """Get the active conversational language for a user session."""
        with self._state_lock:
            uid = user_id or 1
            return self._user_active_languages.get(uid, "en")

    def detect_script(self, text: str) -> Optional[Tuple[str, str]]:
        """Instant zero-latency Unicode script detection. Returns (lang_code, script_name) or None."""
        if not text:
            return None
        for ch in text:
            cp = ord(ch)
            if 0x0C00 <= cp <= 0x0C7F:
                return "te", "telugu"
            if 0x0900 <= cp <= 0x097F:
                return "hi", "devanagari"
            if 0x0B80 <= cp <= 0x0BFF:
                return "ta", "tamil"
            if 0x0C80 <= cp <= 0x0CFF:
                return "kn", "kannada"
            if 0x0D00 <= cp <= 0x0D7F:
                return "ml", "malayalam"
            if 0x0980 <= cp <= 0x09FF:
                return "bn", "bengali"
            if 0x0A80 <= cp <= 0x0AFF:
                return "gu", "gujarati"
            if 0x0600 <= cp <= 0x06FF:
                return "ar", "arabic"
        return None

    def detect_language(
        self,
        text: str,
        user_id: Any = None,
        context_lang: Optional[str] = None
    ) -> LanguageDetectionResult:
        """Identify the language of input text for typed or transcribed text."""
        if not text or not text.strip():
            active = context_lang or self.get_active_language(user_id)
            return LanguageDetectionResult(
                language=active,
                locale=self.LOCALE_MAP.get(active, "en-US"),
                confidence=1.0,
                script="default",
                is_multilingual=(active != "en")
            )

        clean = text.strip()
        norm_lower = clean.lower()

        # 1. Zero-latency Unicode script check
        script_res = self.detect_script(clean)
        if script_res:
            lang, script = script_res
            return LanguageDetectionResult(
                language=lang,
                locale=self.LOCALE_MAP.get(lang, f"{lang}-IN"),
                confidence=0.99,
                script=script,
                is_multilingual=True
            )

        # 2. Short ambiguous tokens check (use active session context)
        # e.g., "yes", "no", "move it", "ok"
        words = norm_lower.split()
        if len(words) <= 3 and norm_lower in self.SHORT_AMBIGUOUS_TOKENS:
            active = context_lang or self.get_active_language(user_id)
            if active and active != "en":
                return LanguageDetectionResult(
                    language=active,
                    locale=self.LOCALE_MAP.get(active, "en-US"),
                    confidence=0.95,
                    script="latin_context",
                    is_multilingual=True
                )

        # 3. Check memory cache for previously classified text
        with self._state_lock:
            if norm_lower in self._detection_cache:
                return self._detection_cache[norm_lower]

        # 4. Fast heuristic markers for Latin-script European languages
        es_markers = {
            "hola", "buenos", "buenas", "por favor", "gracias", "mañana", "manana",
            "que hora", "reunion", "calendario", "alarma", "tiempo", "clima",
            "abrir", "abre", "notas", "correo", "como estas", "ayuda"
        }
        fr_markers = {
            "bonjour", "merci", "demain", "s'il vous plait", "ouvre", "heure",
            "meteo", "courriel", "reunion", "comment allez-vous", "aide"
        }

        if any(m in norm_lower for m in es_markers) or "ñ" in norm_lower or "¿" in clean or "¡" in clean:
            res = LanguageDetectionResult("es", "es-ES", 0.95, "latin", True)
            with self._state_lock:
                self._detection_cache[norm_lower] = res
            return res

        if any(m in norm_lower for m in fr_markers):
            res = LanguageDetectionResult("fr", "fr-FR", 0.95, "latin", True)
            with self._state_lock:
                self._detection_cache[norm_lower] = res
            return res

        # 5. External model detection via googletrans or deep_translator
        detected_code = "en"
        confidence = 0.8
        try:
            trans = self._get_translator()
            if trans:
                d = trans.detect(clean)
                detected_code = str(d.lang).lower()[:2]
                confidence = float(getattr(d, "confidence", 0.8) or 0.8)
        except Exception as e:
            logger.debug(f"[MULTILINGUAL] googletrans detection failed: {e}")
            try:
                from deep_translator import single_detection
                detected_code = single_detection(clean, api_key=None).lower()[:2]
                confidence = 0.8
            except Exception:
                detected_code = "en"

        norm_code = detected_code if detected_code in self.LOCALE_MAP else "en"
        res = LanguageDetectionResult(
            language=norm_code,
            locale=self.LOCALE_MAP.get(norm_code, "en-US"),
            confidence=confidence,
            script="latin" if norm_code in ("en", "es", "fr", "de", "it") else "other",
            is_multilingual=(norm_code != "en")
        )

        with self._state_lock:
            self._detection_cache[norm_lower] = res
        return res

    def translate_to_english(self, text: str, source_lang: Optional[str] = None) -> str:
        """Translate non-English user input to canonical English for internal intent routing."""
        if not text or not text.strip():
            return ""

        clean = text.strip()
        src = (source_lang or "").strip().lower()[:2]
        if src == "en" or not src:
            # Check script to be certain
            if not self.detect_script(clean):
                # Verify if it has obvious non-English Latin text
                det = self.detect_language(clean)
                if not det.is_multilingual:
                    return clean
                src = det.language

        cache_key = (clean.lower(), src, "en")
        with self._state_lock:
            if cache_key in self._translation_cache:
                return self._translation_cache[cache_key]

        translated = clean
        try:
            trans = self._get_translator()
            if trans:
                res = trans.translate(clean, src=src if src else "auto", dest="en")
                translated = res.text
        except Exception as e:
            logger.warning(f"[MULTILINGUAL] googletrans translation to English failed: {e}")
            try:
                from deep_translator import GoogleTranslator
                gt = GoogleTranslator(source=src if src else "auto", target="en")
                translated = gt.translate(clean)
            except Exception as e2:
                logger.error(f"[MULTILINGUAL] Fallback deep_translator failed: {e2}")
                translated = clean

        with self._state_lock:
            self._translation_cache[cache_key] = translated

        return translated

    def translate_from_english(self, text: str, target_lang: str) -> str:
        """Translate canonical English response back into the user's detected language."""
        if not text or not text.strip():
            return ""

        clean = text.strip()
        tgt = (target_lang or "en").strip().lower()[:2]
        if tgt == "en" or tgt not in self.LOCALE_MAP:
            return clean

        cache_key = (clean.lower(), "en", tgt)
        with self._state_lock:
            if cache_key in self._translation_cache:
                return self._translation_cache[cache_key]

        translated = clean
        try:
            trans = self._get_translator()
            if trans:
                res = trans.translate(clean, src="en", dest=tgt)
                translated = res.text
        except Exception as e:
            logger.warning(f"[MULTILINGUAL] googletrans translation from English failed: {e}")
            try:
                from deep_translator import GoogleTranslator
                gt = GoogleTranslator(source="en", target=tgt)
                translated = gt.translate(clean)
            except Exception as e2:
                logger.error(f"[MULTILINGUAL] Fallback deep_translator failed: {e2}")
                translated = clean

        with self._state_lock:
            self._translation_cache[cache_key] = translated

        return translated

    def recognize_multilingual_audio(
        self,
        audio_data: Any,
        user_id: Any = None
    ) -> Tuple[str, str, float]:
        """Recognize spoken audio across candidate languages concurrently.
        
        Returns (recognized_text, detected_language, confidence).
        """
        import speech_recognition as sr
        r = sr.Recognizer()

        active_lang = self.get_active_language(user_id)
        active_locale = self.LOCALE_MAP.get(active_lang, "en-US")

        # Prioritize candidate locales: active user language first, then en-US, then other core languages
        candidate_locales = [active_locale, "en-US", "te-IN", "hi-IN", "ta-IN", "es-ES"]
        # De-duplicate while preserving order
        seen = set()
        ordered_locales = []
        for loc in candidate_locales:
            if loc not in seen:
                seen.add(loc)
                ordered_locales.append(loc)

        def _probe_locale(loc: str):
            try:
                res = r.recognize_google(audio_data, language=loc, show_all=True)
                return loc, res
            except Exception:
                return loc, None

        # Execute concurrent probes
        with ThreadPoolExecutor(max_workers=len(ordered_locales)) as ex:
            probe_results = list(ex.map(_probe_locale, ordered_locales))

        # Evaluate candidate quality
        scored_candidates = []
        intent_keywords = {
            "set", "schedule", "create", "open", "play", "start", "stop", "pause", "resume",
            "show", "tell", "check", "remind", "search", "find", "call", "send", "email",
            "clear", "delete", "add", "what", "when", "how", "who", "why", "meeting",
            "alarm", "timer", "reminder", "event", "calendar", "note", "weather", "music",
            "song", "volume", "app", "window", "time", "date", "tomorrow", "today", "morning",
            "afternoon", "evening", "night", "pm", "am", "clock"
        }

        for loc, res in probe_results:
            if not res or not isinstance(res, dict) or "alternative" not in res or not res["alternative"]:
                continue
            alt = res["alternative"][0]
            transcript = str(alt.get("transcript", "")).strip()
            if not transcript:
                continue
            conf = float(alt.get("confidence", 0.0) or 0.0)
            lang_prefix = loc.split("-")[0]
            script_res = self.detect_script(transcript)

            score = 0.0
            word_count = len(transcript.split())

            # Check translation intent alignment
            eng_trans = ""
            if lang_prefix != "en":
                try:
                    eng_trans = self.translate_to_english(transcript, source_lang=lang_prefix)
                except Exception:
                    eng_trans = ""
            else:
                eng_trans = transcript

            intent_matches = sum(1 for w in eng_trans.lower().split() if w in intent_keywords)
            score += intent_matches * 6.0

            if script_res:
                script_lang, _ = script_res
                if script_lang == lang_prefix:
                    # Native script matches expected locale language: highly authentic!
                    score += 15.0 + min(word_count, 8)
                else:
                    # Transliterated script into wrong language: penalize
                    score += 1.0
            elif lang_prefix == "en":
                # English transcript
                score += 8.0 + min(word_count, 8)
            elif lang_prefix == "es":
                # Spanish transcript
                det = self.detect_language(transcript)
                if det.language == "es":
                    score += 12.0 + min(word_count, 8)
                else:
                    score += 3.0

            # Active language continuity bonus
            if loc == active_locale:
                score += 8.0

            score += conf * 5.0
            scored_candidates.append((score, transcript, lang_prefix, conf, eng_trans))

        if not scored_candidates:
            return "", "en", 0.0

        # Sort by score descending
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_text, best_lang, best_conf, best_eng = scored_candidates[0]

        # Update active conversation language for the user
        self.set_active_language(user_id, best_lang)

        return best_text, best_lang, best_conf


def get_multilingual_engine() -> MultilingualEngine:
    return MultilingualEngine.get_instance()
