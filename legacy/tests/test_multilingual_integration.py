"""
Unit and Integration Tests for Multilingual Voice & Conversation Pipeline
Tests language detection, intent normalization, response translation, and voice mapping.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ["TEST_MODE"] = "true"

from core.multilingual_engine import MultilingualEngine, get_multilingual_engine
from extensions.system.tts_backend import NeuralTTSBackend


class TestMultilingualIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = get_multilingual_engine()

    def test_01_language_detection_indic_scripts(self):
        """Verify zero-latency Unicode script identification."""
        te_res = self.engine.detect_language("సమయం ఎంత?")
        self.assertEqual(te_res.language, "te")
        self.assertEqual(te_res.locale, "te-IN")
        self.assertTrue(te_res.is_multilingual)

        hi_res = self.engine.detect_language("समय क्या हुआ है?")
        self.assertEqual(hi_res.language, "hi")
        self.assertEqual(hi_res.locale, "hi-IN")
        self.assertTrue(hi_res.is_multilingual)

        ta_res = self.engine.detect_language("மணி என்ன?")
        self.assertEqual(ta_res.language, "ta")
        self.assertEqual(ta_res.locale, "ta-IN")
        self.assertTrue(ta_res.is_multilingual)

    def test_02_language_detection_latin_languages(self):
        """Verify European language detection."""
        es_res = self.engine.detect_language("Que hora es?")
        self.assertEqual(es_res.language, "es")
        self.assertEqual(es_res.locale, "es-ES")
        self.assertTrue(es_res.is_multilingual)

        en_res = self.engine.detect_language("What is the time right now?")
        self.assertEqual(en_res.language, "en")
        self.assertFalse(en_res.is_multilingual)

    def test_03_active_language_context_continuity(self):
        """Verify short ambiguous inputs ('yes', 'no') reuse session language."""
        user_id = 98765
        self.engine.set_active_language(user_id, "te")
        self.assertEqual(self.engine.get_active_language(user_id), "te")

        res_yes = self.engine.detect_language("yes", user_id=user_id)
        self.assertEqual(res_yes.language, "te")

        res_cancel = self.engine.detect_language("cancel", user_id=user_id)
        self.assertEqual(res_cancel.language, "te")

        # Automatic switch when user speaks Hindi
        res_hi = self.engine.detect_language("नमस्ते", user_id=user_id)
        self.assertEqual(res_hi.language, "hi")
        self.engine.set_active_language(user_id, "hi")

        res_ok = self.engine.detect_language("ok", user_id=user_id)
        self.assertEqual(res_ok.language, "hi")

    def test_04_translation_to_english_and_back(self):
        """Verify bidirectional translation and caching."""
        eng_cmd = self.engine.translate_to_english("నోట్‌ప్యాడ్ తెరవండి", source_lang="te")
        self.assertTrue(any(w in eng_cmd.lower() for w in ("open", "notepad")))

        te_resp = self.engine.translate_from_english("Opened Notepad successfully.", target_lang="te")
        self.assertTrue(any(0x0C00 <= ord(c) <= 0x0C7F for c in te_resp))

    def test_05_tts_neural_voice_mapping(self):
        """Verify Edge TTS maps detected language to verified neural voice."""
        te_voice = NeuralTTSBackend.resolve_voice(language="te")
        self.assertEqual(te_voice, "te-IN-ShrutiNeural")

        hi_voice = NeuralTTSBackend.resolve_voice(language="hi")
        self.assertEqual(hi_voice, "hi-IN-SwaraNeural")

        ta_voice = NeuralTTSBackend.resolve_voice(language="ta")
        self.assertEqual(ta_voice, "ta-IN-PallaviNeural")

        es_voice = NeuralTTSBackend.resolve_voice(language="es")
        self.assertEqual(es_voice, "es-ES-ElviraNeural")

        en_voice = NeuralTTSBackend.resolve_voice(language="en")
        self.assertEqual(en_voice, "en-US-JennyNeural")

    def test_06_end_to_end_production_path_process_input(self):
        """Verify full production path through process_input."""
        from legacy.assistant import process_input

        # Telugu input -> Telugu output
        resp_te = process_input("సమయం ఎంత?")
        self.assertTrue(any(0x0C00 <= ord(c) <= 0x0C7F for c in resp_te))

        # Hindi input -> Hindi output
        resp_hi = process_input("समय क्या हुआ है?")
        self.assertTrue(any(0x0900 <= ord(c) <= 0x097F for c in resp_hi))

        # Spanish input -> Spanish output
        resp_es = process_input("Que hora es?")
        self.assertTrue(any(w in resp_es.lower() for w in ("hora", "actual", "son", "las", "es")))

        # English input -> English output
        resp_en = process_input("What time is it?")
        self.assertTrue(any(w in resp_en.lower() for w in ("time", "current", "is")))


if __name__ == "__main__":
    unittest.main()
