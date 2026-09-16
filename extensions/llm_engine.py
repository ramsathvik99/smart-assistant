# extensions/llm_engine.py
import os
import requests
from typing import Optional, List, Dict, Any
from instance.config import settings as CONFIG

# Global sets to track unavailable models and providers during runtime
_UNAVAILABLE_MODELS = set()
_UNAVAILABLE_PROVIDERS = set()
_UNAVAILABLE_KEYS = set()  # Track specific keys that have failed

class LLMEngine:
    """
    Central Multi-Provider LLM Engine for NOVA.
    Supports primary provider execution with automatic multi-tier fallback:
      OpenAI (multiple keys) -> Groq (multiple keys + model fallback) -> Gemini (multiple keys) -> DeepSeek (multiple keys) -> HuggingFace (multiple keys).
    Implements runtime validation, 404 / quota error detection, and model blacklisting.
    Strictly safeguards secrets (no API keys logged).
    """

    def __init__(self):
        # Support multiple keys per provider for failover
        self.openai_keys = CONFIG.get("OPENAI_API_KEYS", [CONFIG.get("OPENAI_API_KEY", "")])
        self.openai_base = CONFIG.get("OPENAI_API_BASE", "https://api.openai.com/v1")
        self.openai_model = CONFIG.get("OPENAI_MODEL", "gpt-4o-mini")
        # Configurable kill-switch: set OPENAI_ENABLED=false in .env to skip OpenAI
        # instantly (e.g. when quota is exhausted). Set to true when re-enable.
        self.openai_enabled = CONFIG.get("OPENAI_ENABLED", True)

        self.groq_keys = CONFIG.get("GROQ_API_KEYS", [CONFIG.get("GROQ_API_KEY", "")])
        self.groq_model = CONFIG.get("GROQ_MODEL", "qwen/qwen3.8-27b")
        self.groq_fallback_models = CONFIG.get(
            "GROQ_FALLBACK_MODELS",
            ["qwen/qwen3.8-27b", "groq/compound", "groq/compound-mini"]
        )

        self.gemini_keys = CONFIG.get("GEMINI_API_KEYS", [CONFIG.get("GEMINI_API_KEY", "")])
        self.gemini_model = CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash")

        self.deepseek_keys = CONFIG.get("DEEPSEEK_API_KEYS", [CONFIG.get("DEEPSEEK_API_KEY", "")])
        self.deepseek_model = CONFIG.get("DEEPSEEK_MODEL", "deepseek-chat")

        self.hf_keys = CONFIG.get("HF_API_KEYS", [CONFIG.get("HF_API_KEY", "")])
        self.hf_model = CONFIG.get("HF_MODEL_ID", "mistralai/Mistral-7B-Instruct-v0.2")

        # Backward compatibility attributes (use first available key)
        self.openai_key = self.openai_keys[0] if self.openai_keys else ""
        self.groq_key = self.groq_keys[0] if self.groq_keys else ""
        self.gemini_key = self.gemini_keys[0] if self.gemini_keys else ""
        self.deepseek_key = self.deepseek_keys[0] if self.deepseek_keys else ""
        self.hf_key = self.hf_keys[0] if self.hf_keys else ""
        
        self.api_key = self.groq_key
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = self.groq_model

    def _call_openai(self, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> Optional[str]:
        if "openai" in _UNAVAILABLE_PROVIDERS or not self.openai_keys:
            return None
        model_tag = f"openai:{model}"
        if model_tag in _UNAVAILABLE_MODELS:
            return None

        # Try each available OpenAI key
        for key_index, api_key in enumerate(self.openai_keys):
            key_tag = f"openai_key_{key_index}"
            if key_tag in _UNAVAILABLE_KEYS:
                continue
                
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key, base_url=self.openai_base)
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=12
                )
                return response.choices[0].message.content
            except Exception as e:
                err_str = str(e).lower()
                if "insufficient_quota" in err_str or "quota" in err_str or "429" in err_str or "rate_limit" in err_str:
                    print(f"[LLM] Provider=OpenAI Key slot {key_index} quota exceeded or rate limited. Marking key unavailable and trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag)
                elif "model_not_found" in err_str or "404" in err_str or "does not exist" in err_str:
                    print(f"[LLM] Provider=OpenAI Model={model} not found (HTTP 404). Marking model unavailable.")
                    _UNAVAILABLE_MODELS.add(model_tag)
                elif "authentication" in err_str or "invalid" in err_str:
                    print(f"[LLM] Provider=OpenAI Key slot {key_index} authentication failed. Marking key unavailable.")
                    _UNAVAILABLE_KEYS.add(key_tag)
                else:
                    print(f"[LLM] Provider=OpenAI Key slot {key_index} request failed: {type(e).__name__}. Trying next key.")
                # Continue to next key in the loop
        return None

    def _call_groq(self, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> Optional[str]:
        if "groq" in _UNAVAILABLE_PROVIDERS or not self.groq_keys:
            return None
        model_tag = f"groq:{model}"
        if model_tag in _UNAVAILABLE_MODELS:
            return None

        # Try each available Groq key
        for key_index, api_key in enumerate(self.groq_keys):
            key_tag = f"groq_key_{key_index}"
            if key_tag in _UNAVAILABLE_KEYS:
                continue
                
            try:
                headers = {
                    "Authorization": f"Bearer {api_key.strip()}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
                res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=12)
                if res.status_code == 200:
                    data = res.json()
                    return data['choices'][0]['message']['content']
                elif res.status_code == 404 or "model_not_found" in res.text or "does not exist" in res.text:
                    print(f"[LLM] Provider=Groq Key slot {key_index} Model={model} not found (HTTP 404). Marking model unavailable.")
                    _UNAVAILABLE_MODELS.add(model_tag)
                elif res.status_code == 429:
                    print(f"[LLM] Provider=Groq Key slot {key_index} rate limited (HTTP 429). Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag)
                elif res.status_code == 401 or "authentication" in res.text.lower():
                    print(f"[LLM] Provider=Groq Key slot {key_index} authentication failed. Marking key unavailable.")
                    _UNAVAILABLE_KEYS.add(key_tag)
                else:
                    print(f"[LLM] Provider=Groq Key slot {key_index} HTTP {res.status_code} error. Trying next key.")
            except Exception as e:
                print(f"[LLM] Provider=Groq Key slot {key_index} connection exception: {type(e).__name__}. Trying next key.")
        return None

    def _call_gemini(self, prompt: str, system_prompt: str, model: str, temperature: float, max_tokens: int) -> Optional[str]:
        if "gemini" in _UNAVAILABLE_PROVIDERS or not self.gemini_keys:
            return None
        model_tag = f"gemini:{model}"
        if model_tag in _UNAVAILABLE_MODELS:
            return None

        # Try each available Gemini key
        for key_index, api_key in enumerate(self.gemini_keys):
            key_tag = f"gemini_key_{key_index}"
            if key_tag in _UNAVAILABLE_KEYS:
                continue
                
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key.strip()}"
                full_prompt = f"System: {system_prompt}\n\nUser: {prompt}" if system_prompt else prompt
                payload = {
                    "contents": [{"parts": [{"text": full_prompt}]}],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens
                    }
                }
                res = requests.post(url, json=payload, timeout=12)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"]
                elif res.status_code == 404 or "not found" in res.text.lower():
                    print(f"[LLM] Provider=Gemini Key slot {key_index} Model={model} not found (HTTP 404). Marking model unavailable.")
                    _UNAVAILABLE_MODELS.add(model_tag)
                elif res.status_code == 429:
                    print(f"[LLM] Provider=Gemini Key slot {key_index} rate limit / quota exceeded (HTTP 429). Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag)
                elif res.status_code == 401 or "authentication" in res.text.lower():
                    print(f"[LLM] Provider=Gemini Key slot {key_index} authentication failed. Marking key unavailable.")
                    _UNAVAILABLE_KEYS.add(key_tag)
                else:
                    print(f"[LLM] Provider=Gemini Key slot {key_index} HTTP {res.status_code} error. Trying next key.")
            except Exception as e:
                print(f"[LLM] Provider=Gemini Key slot {key_index} connection exception: {type(e).__name__}. Trying next key.")
        return None

    def _call_deepseek(self, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> Optional[str]:
        if "deepseek" in _UNAVAILABLE_PROVIDERS or not self.deepseek_keys:
            return None
        model_tag = f"deepseek:{model}"
        if model_tag in _UNAVAILABLE_MODELS:
            return None

        # Try each available DeepSeek key
        for key_index, api_key in enumerate(self.deepseek_keys):
            key_tag = f"deepseek_key_{key_index}"
            if key_tag in _UNAVAILABLE_KEYS:
                continue
                
            try:
                headers = {
                    "Authorization": f"Bearer {api_key.strip()}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
                res = requests.post("https://api.deepseek.com/chat/completions", json=payload, headers=headers, timeout=10)
                if res.status_code == 200:
                    return res.json()['choices'][0]['message']['content']
                elif res.status_code == 402 or "insufficient balance" in res.text.lower():
                    print(f"[LLM] Provider=DeepSeek Key slot {key_index} insufficient balance (HTTP 402). Marking key unavailable.")
                    _UNAVAILABLE_KEYS.add(key_tag)
                elif res.status_code == 404:
                    print(f"[LLM] Provider=DeepSeek Key slot {key_index} Model={model} not found (HTTP 404). Marking model unavailable.")
                    _UNAVAILABLE_MODELS.add(model_tag)
                elif res.status_code == 429:
                    print(f"[LLM] Provider=DeepSeek Key slot {key_index} rate limited (HTTP 429). Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag)
                elif res.status_code == 401 or "authentication" in res.text.lower():
                    print(f"[LLM] Provider=DeepSeek Key slot {key_index} authentication failed. Marking key unavailable.")
                    _UNAVAILABLE_KEYS.add(key_tag)
                else:
                    print(f"[LLM] Provider=DeepSeek Key slot {key_index} HTTP {res.status_code} error. Trying next key.")
            except Exception as e:
                print(f"[LLM] Provider=DeepSeek Key slot {key_index} exception: {type(e).__name__}. Trying next key.")
        return None

    def _call_huggingface(self, prompt: str, system_prompt: str, model: str, max_tokens: int) -> Optional[str]:
        if "huggingface" in _UNAVAILABLE_PROVIDERS or not self.hf_keys:
            return None
        model_tag = f"huggingface:{model}"
        if model_tag in _UNAVAILABLE_MODELS:
            return None

        # Try each available HuggingFace key
        for key_index, api_key in enumerate(self.hf_keys):
            key_tag = f"huggingface_key_{key_index}"
            if key_tag in _UNAVAILABLE_KEYS:
                continue
                
            try:
                headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"}
                url = "https://router.huggingface.co/hf-inference/v1/chat/completions"
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
                res = requests.post(url, headers=headers, json=payload, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    return data['choices'][0]['message']['content']
                elif res.status_code == 404 or res.status_code == 400:
                    print(f"[LLM] Provider=HuggingFace Key slot {key_index} Model={model} unavailable (HTTP {res.status_code}). Marking model unavailable.")
                    _UNAVAILABLE_MODELS.add(model_tag)
                elif res.status_code == 429:
                    print(f"[LLM] Provider=HuggingFace Key slot {key_index} rate limited (HTTP 429). Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag)
                elif res.status_code == 401 or "authentication" in res.text.lower():
                    print(f"[LLM] Provider=HuggingFace Key slot {key_index} authentication failed. Marking key unavailable.")
                    _UNAVAILABLE_KEYS.add(key_tag)
                else:
                    print(f"[LLM] Provider=HuggingFace Key slot {key_index} HTTP {res.status_code} error. Trying next key.")
            except Exception as e:
                print(f"[LLM] Provider=HuggingFace Key slot {key_index} exception: {type(e).__name__}. Trying next key.")
        return None

    def get_completion(
        self,
        prompt: str,
        context: str = "",
        memory: str = "",
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> Optional[str]:
        """
        Execute completion with strict multi-tier fallback:
        OpenAI (multiple keys) -> Groq (multiple keys + model sequence) -> Gemini (multiple keys) -> DeepSeek (multiple keys) -> HuggingFace (multiple keys).
        """
        if not prompt or not str(prompt).strip():
            return None

        if system_prompt is None:
            # Use the per-user configured assistant name; never fall back to "NOVA"
            try:
                from instance.config import settings as _cfg
                _asst_name = _cfg.get_assistant_name()
            except Exception:
                _asst_name = None

            if _asst_name:
                identity_line = (
                    f"You are {_asst_name}, an intelligent assistant with a calm, professional presence similar to JARVIS. "
                )
            else:
                identity_line = (
                    "You are an intelligent assistant with a calm, professional presence similar to JARVIS. "
                )

            system_prompt = (
                identity_line
                + "You have long-term memory and can recall previous conversations and user preferences. "
                "When relevant, naturally acknowledge what you remember about the user with phrases like 'Based on what I recall...' or 'I remember you mentioned...'. "
                "Your responses should be clear, confident, and slightly formal but approachable. "
                "You maintain continuity across sessions and build upon previous interactions.\n"
                f"Current Context: {context}\n"
                f"Relevant Memory: {memory}\n"
                "Guidelines:\n"
                "- Answer questions directly and concisely\n"
                "- Confirm commands before execution\n"
                "- Reference memory naturally when relevant\n"
                "- Maintain consistent professional tone\n"
                "- Never include internal reasoning or explanations\n"
                "Provide only your final response to the user."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        # 1. Primary: OpenAI (only when OPENAI_ENABLED=true in config)
        if self.openai_enabled and self.openai_keys and "openai" not in _UNAVAILABLE_PROVIDERS:
            resp = self._call_openai(messages, self.openai_model, temperature, max_tokens)
            if resp:
                return resp
        elif not self.openai_enabled:
            print("[LLM] OpenAI disabled via OPENAI_ENABLED=false. Skipping to next provider.")

        # 2. Fallback: Groq (with model sequence)
        if self.groq_keys and "groq" not in _UNAVAILABLE_PROVIDERS:
            models_to_try = [self.groq_model] + [m for m in self.groq_fallback_models if m != self.groq_model]
            for m in models_to_try:
                if f"groq:{m}" in _UNAVAILABLE_MODELS:
                    continue
                resp = self._call_groq(messages, m, temperature, max_tokens)
                if resp:
                    return resp

        # 3. Fallback: Gemini
        if self.gemini_keys and "gemini" not in _UNAVAILABLE_PROVIDERS:
            resp = self._call_gemini(prompt, system_prompt, self.gemini_model, temperature, max_tokens)
            if resp:
                return resp

        # 4. Fallback: DeepSeek
        if self.deepseek_keys and "deepseek" not in _UNAVAILABLE_PROVIDERS:
            resp = self._call_deepseek(messages, self.deepseek_model, temperature, max_tokens)
            if resp:
                return resp

        # 5. Fallback: Hugging Face
        if self.hf_keys and "huggingface" not in _UNAVAILABLE_PROVIDERS:
            resp = self._call_huggingface(prompt, system_prompt, self.hf_model, max_tokens)
            if resp:
                return resp

        print("[LLM] All configured providers and fallback keys failed.")
        return None

    def extract_intent(self, text: str) -> tuple:
        """Extracts intent and confidence score from text."""
        intent_label = "none"
        confidence = 0.95
        
        if "?" in text or len(text.split()) < 2:
            confidence = 0.4
            
        prompt = f"Extract the primary intent from this text: '{text}'. Return only the intent label (e.g., SET_REMINDER, GENERAL_QUERY, SAVE_MEMORY)."
        res = self.get_completion(prompt, max_tokens=20)
        if res:
            intent_label = res.strip().upper()
            
        return intent_label, confidence

    def generate_clarification_prompt(self, text: str):
        """Generates a clarification question when confidence is low."""
        return "I'm not exactly sure what you mean. Could you please clarify if you want me to search for something or perform an action?"

    def check_if_command(self, text):
        """
        Determines if a piece of text is a command/action or a declarative statement.
        """
        prompt = (
            f"Determine if the following text is a command or an action-based request (like 'play music', 'open app', 'set alarm') "
            f"or if it is a declarative statement about the user's life, feelings, or facts (like 'I feel tired', 'My name is...', 'I went to gym').\n\n"
            f"Text: '{text}'\n\n"
            f"Respond with ONLY 'YES' if it is command/action, and 'NO' if it is a declarative statement or fact."
        )
        response = self.get_completion(prompt, max_tokens=10)
        return response and "YES" in response.upper()

    # ------------------------------------------------------------------
    # Semantic Intent Resolution
    # ------------------------------------------------------------------
    #
    # Called ONLY when deterministic regex routing in UnifiedCommandRouter
    # produces no match (falls through to GENERAL_CONVERSATION).
    #
    # Returns a structured dict so the router can map back to existing
    # Intent enum values and execute via the existing deterministic handlers.
    # Never executes OS commands itself.
    # ------------------------------------------------------------------

    # Canonical intent labels the LLM must choose from — mirrors Intent enum
    INTENT_LABELS = [
        "OPEN_APPLICATION",
        "CLOSE_APPLICATION",
        "FILE_OPERATIONS",
        "DEVICE_CONTROL",
        "POWER_ACTION",
        "MUSIC",
        "EMAIL",
        "NOTES",
        "REMINDERS",
        "CALCULATOR",
        "CODE_GENERATION",
        "TRANSLATION",
        "TIME_QUERY",
        "DATE_QUERY",
        "WEATHER_QUERY",
        "MEMORY_QUERY",
        "RAG_SEARCH",
        "GENERAL_CONVERSATION",
        "NEEDS_CLARIFICATION",
    ]

    # System prompt used exclusively for semantic intent resolution.
    # Kept minimal and deterministic — no conversation, just classification.
    _SEMANTIC_SYSTEM_PROMPT = (
        "You are a strict intent classifier for a voice assistant. "
        "Your ONLY job is to output a JSON object — nothing else. "
        "No prose, no explanation, no markdown fences.\n\n"
        "Given a user utterance, output exactly this JSON structure:\n"
        '{"intent": "<INTENT_LABEL>", "confidence": <0.0-1.0>, '
        '"entities": {"action": "<sub-action or null>", "target": "<main object or null>", '
        '"name": "<specific name or null>", "location": "<location or null>"}, '
        '"needs_clarification": <true|false>, '
        '"clarification_reason": "<reason string or null>"}\n\n'
        "INTENT_LABELS you may use:\n"
        "  OPEN_APPLICATION   — user wants to open/launch/start/run/bring up an app\n"
        "  CLOSE_APPLICATION  — user wants to close/quit/exit/terminate an app\n"
        "  FILE_OPERATIONS    — create/delete/remove/erase/rename/list folders or files\n"
        "  DEVICE_CONTROL     — volume, mute, screenshot, brightness, lock\n"
        "  POWER_ACTION       — shutdown, restart, reboot, sleep, hibernate\n"
        "  MUSIC              — play/pause/resume/stop/skip music or songs\n"
        "  EMAIL              — send/read/check/reply email\n"
        "  NOTES              — take a note, jot down\n"
        "  REMINDERS          — set a reminder, alert me, remind me\n"
        "  CALCULATOR         — arithmetic, math calculation\n"
        "  CODE_GENERATION    — write/build/create code, programs, scripts\n"
        "  TRANSLATION        — translate text to another language\n"
        "  TIME_QUERY         — asking what time it is\n"
        "  DATE_QUERY         — asking what date/day it is\n"
        "  WEATHER_QUERY      — asking about weather, temperature, forecast, umbrella\n"
        "  MEMORY_QUERY       — asking what the assistant remembers about the user\n"
        "  RAG_SEARCH         — factual questions, who/what/where/why/how (knowledge)\n"
        "  GENERAL_CONVERSATION — greetings, small talk, vague statements\n"
        "  NEEDS_CLARIFICATION — the utterance is ambiguous and cannot be safely resolved\n\n"
        "FILE_OPERATIONS entity guidance:\n"
        "  action values: create_folder | delete_folder | rename_folder | list_folders | open_file | delete_file | find_file\n"
        "  'remove', 'erase', 'throw away', 'get rid of', 'I don't need' → action=delete_folder or delete_file\n"
        "  'make', 'new', 'create', 'mkdir' → action=create_folder\n\n"
        "DEVICE_CONTROL entity guidance:\n"
        "  action values: mute | unmute | increase_volume | decrease_volume | screenshot | lock\n"
        "  'make quiet', 'turn sound off', 'silence' → action=mute\n"
        "  'too loud', 'lower sound', 'turn down' → action=decrease_volume\n"
        "  'louder', 'turn up' → action=increase_volume\n\n"
        "POWER_ACTION entity guidance:\n"
        "  action values: shutdown | restart | sleep\n"
        "  'turn off PC/computer', 'shut down' → action=shutdown\n"
        "  'reboot', 'restart machine' → action=restart\n\n"
        "OPEN_APPLICATION entity guidance:\n"
        "  action values: open | close\n"
        "  'bring up', 'launch', 'get running', 'start', 'I want to use', 'I need' → action=open\n"
        "  target = the application name\n\n"
        "NEEDS_CLARIFICATION: use when target/action is genuinely ambiguous and guessing "
        "could cause unintended side effects (especially for delete/close/power actions).\n\n"
        "Confidence:\n"
        "  0.9+ = certain\n"
        "  0.7-0.89 = likely, can proceed\n"
        "  0.5-0.69 = uncertain, set needs_clarification=true\n"
        "  <0.5 = unknown, use GENERAL_CONVERSATION\n\n"
        "ONLY return the JSON object. No other text."
    )

    def semantic_resolve(self, user_input: str) -> Dict[str, Any]:
        """
        Semantic intent resolution via LLM — called ONLY when the deterministic
        regex router in UnifiedCommandRouter returns GENERAL_CONVERSATION.

        Uses the existing get_completion() multi-provider failover chain.
        Does NOT execute any OS commands — returns structured intent + entities
        that the UnifiedCommandRouter maps back to existing handlers.

        Returns:
            {
                "intent": str,           # One of INTENT_LABELS
                "confidence": float,     # 0.0 – 1.0
                "entities": {
                    "action":    str|None,
                    "target":    str|None,
                    "name":      str|None,
                    "location":  str|None,
                },
                "needs_clarification": bool,
                "clarification_reason": str|None,
                "source": "semantic"     # marks that this came from LLM, not regex
            }

        On any failure (LLM unavailable, bad JSON, unknown label) returns:
            {"intent": "GENERAL_CONVERSATION", "confidence": 0.5,
             "entities": {}, "needs_clarification": False,
             "clarification_reason": None, "source": "semantic_fallback"}
        """
        import json as _json

        _fallback = {
            "intent": "GENERAL_CONVERSATION",
            "confidence": 0.5,
            "entities": {"action": None, "target": None, "name": None, "location": None},
            "needs_clarification": False,
            "clarification_reason": None,
            "source": "semantic_fallback",
        }

        if not user_input or not user_input.strip():
            return _fallback

        try:
            raw = self.get_completion(
                prompt=user_input,
                system_prompt=self._SEMANTIC_SYSTEM_PROMPT,
                temperature=0.0,   # deterministic — no creativity here
                max_tokens=200,
            )
        except Exception as e:
            print(f"[SEMANTIC_RESOLVE] LLM call failed: {e}")
            return _fallback

        if not raw:
            return _fallback

        # Strip accidental markdown fences or leading/trailing whitespace
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            parsed = _json.loads(raw)
        except (_json.JSONDecodeError, ValueError) as e:
            print(f"[SEMANTIC_RESOLVE] JSON parse error: {e} | Raw: {raw[:200]}")
            return _fallback

        # Validate intent label is one we recognise
        intent_label = str(parsed.get("intent", "")).upper().strip()
        if intent_label not in self.INTENT_LABELS:
            print(f"[SEMANTIC_RESOLVE] Unknown intent label '{intent_label}' — using fallback")
            return _fallback

        confidence = float(parsed.get("confidence", 0.5))
        entities = parsed.get("entities", {})
        if not isinstance(entities, dict):
            entities = {}

        # Normalise entity dict — ensure all expected keys exist
        normalised_entities = {
            "action":   entities.get("action"),
            "target":   entities.get("target"),
            "name":     entities.get("name"),
            "location": entities.get("location"),
        }

        needs_clarification = bool(parsed.get("needs_clarification", False))
        clarification_reason = parsed.get("clarification_reason")

        # Low-confidence result → force clarification for destructive intents
        DESTRUCTIVE_INTENTS = {
            "FILE_OPERATIONS", "POWER_ACTION", "CLOSE_APPLICATION",
            "DEVICE_CONTROL", "EMAIL",
        }
        if confidence < 0.70 and intent_label in DESTRUCTIVE_INTENTS:
            needs_clarification = True
            if not clarification_reason:
                clarification_reason = (
                    f"Low confidence ({confidence:.2f}) for a potentially destructive action. "
                    "Please clarify what you'd like to do."
                )

        result = {
            "intent": intent_label,
            "confidence": confidence,
            "entities": normalised_entities,
            "needs_clarification": needs_clarification,
            "clarification_reason": clarification_reason,
            "source": "semantic",
        }

        print(
            f"[SEMANTIC_RESOLVE] '{user_input[:60]}' → intent={intent_label} "
            f"confidence={confidence:.2f} clarify={needs_clarification}"
        )
        return result
