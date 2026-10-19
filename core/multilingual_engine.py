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
        self._user_requested_response_languages: Dict[Any, str] = {}
        self._state_lock = threading.Lock()
        self._translation_cache: Dict[Tuple[str, str, str], str] = {}
        self._detection_cache: Dict[str, LanguageDetectionResult] = {}
        self._translator = None
        self._translator_checked = False

    def _get_translator(self):
        if not self._translator_checked:
            self._translator_checked = True
            try:
                from deep_translator import GoogleTranslator
                self._translator = GoogleTranslator
                logger.info("[MULTILINGUAL] Using deep_translator for translation services.")
            except ImportError:
                self._translator = None
                logger.debug("[MULTILINGUAL] deep_translator not available in environment.")
        return self._translator

    def set_requested_response_language(self, user_id: Any, lang: str):
        """Set an explicit user-requested response language (e.g. 'speak in Telugu')."""
        with self._state_lock:
            uid = user_id or 1
            norm_lang = (lang or "en").strip().lower()[:2]
            if norm_lang in self.LOCALE_MAP:
                self._user_requested_response_languages[uid] = norm_lang
                self._user_active_languages[uid] = norm_lang
            else:
                self._user_requested_response_languages[uid] = "en"
                self._user_active_languages[uid] = "en"

    def get_requested_response_language(self, user_id: Any) -> Optional[str]:
        """Get the explicit user-requested response language if set."""
        with self._state_lock:
            uid = user_id or 1
            return self._user_requested_response_languages.get(uid)

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

        # 5. External model detection via deep_translator
        detected_code = "en"
        confidence = 0.8
        try:
            from deep_translator import single_detection
            det = single_detection(clean, api_key=None)
            if det:
                detected_code = str(det).lower()[:2]
                confidence = 0.85
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

    def _offline_translate_to_english(self, clean: str, src: str) -> Optional[str]:
        """Deterministic local dictionary fallback for essential assistant commands."""
        norm = clean.lower().strip().rstrip('.?!,')
        PHRASES_TO_EN = {
            # Telugu commands
            "సమయం ఎంత": "what is the time",
            "టైమ్ ఎంత": "what is the time",
            "టైం ఎంత": "what is the time",
            "ఫ్రైడే టైమ్ ఎంత": "what is the time",
            "ఫ్రైడే సమయం ఎంత": "what is the time",
            "ఈరోజు తేదీ ఏమిటి": "what is today's date",
            "ఈరోజు తేదీ ఎంత": "what is the date today",
            "తేదీ ఎంత": "what is the date",
            "ఈరోజు ఏ రోజు": "which day is today",
            "రేపు ఏ రోజు": "which day is tomorrow",
            "నోట్‌ప్యాడ్ తెరవండి": "open notepad",
            "నోట్‌ప్యాడ్‌ను తెరవండి": "open notepad",
            "నోట్ పాడ్ తెరవండి": "open notepad",
            "వాతావరణం ఎలా ఉంది": "how is the weather",
            "హలో": "hello",
            "నమస్కారం": "hello",
            "ధన్యవాదాలు": "thank you",
            # Hindi commands
            "समय क्या हुआ है": "what is the time",
            "टाइम क्या है": "what is the time",
            "समय क्या है": "what is the time",
            "कितने बजे हैं": "what is the time",
            "आज की तारीख क्या है": "what is today's date",
            "तारीख क्या है": "what is the date",
            "आज कौन सा दिन है": "which day is today",
            "नोटपैड खोलो": "open notepad",
            "नोटपैड खोलें": "open notepad",
            "मौसम कैसा है": "how is the weather",
            "नमस्ते": "hello",
            "धन्यवाद": "thank you",
            # Spanish commands
            "que hora es": "what is the time",
            "dime la hora": "tell me the time",
            "que fecha es": "what is the date",
            "abrir bloc de notas": "open notepad",
            "como esta el clima": "how is the weather",
        }
        if norm in PHRASES_TO_EN:
            return PHRASES_TO_EN[norm]
        for k, v in PHRASES_TO_EN.items():
            if k in norm:
                return v
        return None

    def _offline_translate_from_english(self, clean: str, tgt: str) -> Optional[str]:
        """Deterministic local dictionary fallback for assistant responses."""
        norm = clean.lower().strip()
        if tgt == "te":
            if "current time is" in norm:
                m = re.search(r'(\d{1,2}:\d{2}\s*(?:am|pm)?)', clean, re.IGNORECASE)
                if m:
                    return f"ప్రస్తుత సమయం {m.group(1)}."
                return "ప్రస్తుత సమయం ఇది."
            if "today is" in norm:
                return f"ఈరోజు {clean.replace('Today is', '').strip()}."
            if "opened notepad" in norm or "open notepad" in norm:
                return "నోట్‌ప్యాడ్ విజయవంతంగా తెరవబడింది."
        elif tgt == "hi":
            if "current time is" in norm:
                m = re.search(r'(\d{1,2}:\d{2}\s*(?:am|pm)?)', clean, re.IGNORECASE)
                if m:
                    return f"वर्तमान समय {m.group(1)} है।"
                return "वर्तमान समय यह है।"
            if "today is" in norm:
                return f"आज {clean.replace('Today is', '').strip()} है।"
            if "opened notepad" in norm or "open notepad" in norm:
                return "नोटपैड सफलतापूर्वक खोल दिया गया है।"
        elif tgt == "es":
            if "current time is" in norm:
                m = re.search(r'(\d{1,2}:\d{2}\s*(?:am|pm)?)', clean, re.IGNORECASE)
                if m:
                    return f"La hora actual es {m.group(1)}."
                return "La hora actual es esta."
            if "today is" in norm:
                return f"Hoy es {clean.replace('Today is', '').strip()}."
            if "opened notepad" in norm or "open notepad" in norm:
                return "Notepad se ha abierto con éxito."
        elif tgt == "ta":
            if "current time is" in norm:
                m = re.search(r'(\d{1,2}:\d{2}\s*(?:am|pm)?)', clean, re.IGNORECASE)
                if m:
                    return f"தற்போதைய நேரம் {m.group(1)}."
                return "தற்போதைய நேரம் இது."
            if "today is" in norm:
                return f"இன்று {clean.replace('Today is', '').strip()}."
            if "opened notepad" in norm or "open notepad" in norm:
                return "நோட்பேட் வெற்றிகரமாக திறக்கப்பட்டது."
        return None

    def translate_to_english(self, text: str, source_lang: Optional[str] = None) -> str:
        """Translate non-English user input to canonical English with multi-tier fallback."""
        if not text or not text.strip():
            return ""

        clean = text.strip()
        src = (source_lang or "").strip().lower()[:2]
        if src == "en" or not src:
            # Check script to be certain
            if not self.detect_script(clean):
                det = self.detect_language(clean)
                if not det.is_multilingual:
                    return clean
                src = det.language

        cache_key = (clean.lower(), src, "en")
        with self._state_lock:
            if cache_key in self._translation_cache:
                return self._translation_cache[cache_key]

        translated = None
        # Tier 1: Try deep_translator
        try:
            from deep_translator import GoogleTranslator
            gt = GoogleTranslator(source=src if src else "auto", target="en")
            res = gt.translate(clean)
            if res and res.strip():
                translated = res.strip()
        except Exception as e:
            logger.debug(f"[MULTILINGUAL] deep_translator to_english notice: {e}")

        # Tier 2: Try googletrans if Tier 1 failed or rate-limited
        if not translated:
            try:
                import googletrans
                gtr = googletrans.Translator()
                g_res = gtr.translate(clean, dest="en", src=src if src else "auto")
                if g_res and g_res.text and g_res.text.strip():
                    translated = g_res.text.strip()
            except Exception as e:
                logger.debug(f"[MULTILINGUAL] googletrans to_english notice: {e}")

        # Tier 3: Local offline dictionary fallback
        if not translated:
            translated = self._offline_translate_to_english(clean, src)

        final_translated = translated or clean
        with self._state_lock:
            self._translation_cache[cache_key] = final_translated

        return final_translated

    def translate_from_english(self, text: str, target_lang: str) -> str:
        """Translate canonical English response back into the user's detected or requested language."""
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

        translated = None
        # Tier 1: Try deep_translator
        try:
            from deep_translator import GoogleTranslator
            gt = GoogleTranslator(source="en", target=tgt)
            res = gt.translate(clean)
            if res and res.strip():
                translated = res.strip()
        except Exception as e:
            logger.debug(f"[MULTILINGUAL] deep_translator from_english notice: {e}")

        # Tier 2: Try googletrans if Tier 1 failed or rate-limited
        if not translated:
            try:
                import googletrans
                gtr = googletrans.Translator()
                g_res = gtr.translate(clean, dest=tgt, src="en")
                if g_res and g_res.text and g_res.text.strip():
                    translated = g_res.text.strip()
            except Exception as e:
                logger.debug(f"[MULTILINGUAL] googletrans from_english notice: {e}")

        # Tier 3: Local offline dictionary fallback
        if not translated:
            translated = self._offline_translate_from_english(clean, tgt)

        final_translated = translated or clean
        with self._state_lock:
            self._translation_cache[cache_key] = final_translated

        return final_translated

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
        req_lang = self.get_requested_response_language(user_id)
        req_locale = self.LOCALE_MAP.get(req_lang, None) if req_lang else None

        # Prioritize candidate locales: active user language, requested language, then all supported languages
        candidate_locales = [active_locale]
        if req_locale:
            candidate_locales.append(req_locale)
        candidate_locales.extend(["en-US", "te-IN", "hi-IN", "ta-IN", "es-ES"])
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

        return self.resolve_probe_results(probe_results, user_id=user_id)

    def resolve_best_transcript(
        self,
        candidates: List[Dict[str, Any]],
        user_id: Any = None
    ) -> Tuple[str, str, float]:
        """Resolve the best transcript from candidate dictionaries."""
        formatted_probes = []
        for c in candidates:
            if isinstance(c, tuple) and len(c) == 2:
                formatted_probes.append(c)
            elif isinstance(c, dict):
                lang = c.get("language", "en")
                loc = c.get("locale") or self.LOCALE_MAP.get(lang, f"{lang}-IN")
                res = {
                    "alternative": [
                        {
                            "transcript": c.get("text", ""),
                            "confidence": c.get("confidence", 0.88)
                        }
                    ]
                }
                formatted_probes.append((loc, res))
        return self.resolve_probe_results(formatted_probes, user_id=user_id)

    def resolve_probe_results(
        self,
        probe_results: List[Tuple[str, Any]],
        user_id: Any = None
    ) -> Tuple[str, str, float]:
        """Score probe results across locales and resolve the single winning transcript."""
        active_lang = self.get_active_language(user_id)
        active_locale = self.LOCALE_MAP.get(active_lang, "en-US")

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
            raw_conf = alt.get("confidence")
            conf = float(raw_conf) if raw_conf is not None else 0.88
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
                    score += 18.0 + min(word_count, 8)
                else:
                    # Transliterated script into wrong language: penalize
                    score += 1.0
            elif lang_prefix == "en":
                # English transcript: give base parity with native script
                score += 18.0 + min(word_count, 8)
            elif lang_prefix in ("es", "fr", "de", "it"):
                # European Latin languages: verify with language detection
                det = self.detect_language(transcript)
                if det.language == lang_prefix:
                    score += 14.0 + min(word_count, 8)
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

        # Guard: If an English probe recognized coherent command terms or speech,
        # never allow a phonetic transliteration in Devanagari/Telugu/etc. to override English.
        en_cand = next((c for c in scored_candidates if c[2] == "en"), None)
        if en_cand and best_lang != "en":
            en_score, en_text, _, en_conf, _ = en_cand
            en_words = set(en_text.lower().split())
            best_eng_words = set((best_eng or "").lower().split())
            has_en_intent = bool(en_words & intent_keywords)
            
            # Check if the non-English transcript is essentially a phonetic transliteration of the English input
            # (e.g. "open chrome" translated from "ओपन क्रोम" is "open chrome")
            common_overlap = en_words & best_eng_words
            is_phonetic_mirror = bool(common_overlap) and (len(common_overlap) / max(len(en_words), 1) >= 0.5)

            if is_phonetic_mirror or has_en_intent or (en_conf >= 0.65 and en_score + 10.0 >= best_score):
                best_score, best_text, best_lang, best_conf, best_eng = en_cand

        try:
            logger.info(
                f"[ASR DIAGNOSTIC] Selected={best_lang} ({best_conf:.2f}): {best_text!r} | "
                f"Probes={[(c[2], c[1][:40], round(c[3], 2)) for c in scored_candidates]}"
            )
        except Exception:
            pass

        # Update active conversation language for the user only when unambiguous native vocabulary was spoken
        # Do not latch away from English on ambiguous or phonetically borrowed commands
        if not self.get_requested_response_language(user_id):
            if best_lang == "en" or best_conf >= 0.85:
                self.set_active_language(user_id, best_lang)

        return best_text, best_lang, best_conf


def get_multilingual_engine() -> MultilingualEngine:
    return MultilingualEngine.get_instance()
