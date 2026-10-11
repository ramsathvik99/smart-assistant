# extensions/llm_engine.py
import os
import json
import requests
from typing import Optional, List, Dict, Any
from instance.config import settings as CONFIG

import time

# Cooldown duration for temporarily failed providers, models, or keys (seconds)
LLM_COOLDOWN_SECONDS = int(os.getenv("LLM_COOLDOWN_SECONDS", "60"))
HEALTH_CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "llm_provider_health.json")

class CooldownSet:
    """
    Tracks unavailable providers, models, and keys with a time-based cooldown and file persistence.
    Automatically restores availability once the cooldown duration elapses.
    Drop-in compatible with standard Python set methods (add, discard, remove, in, len).
    """
    def __init__(self, default_cooldown: int = LLM_COOLDOWN_SECONDS, cache_path: Optional[str] = HEALTH_CACHE_PATH):
        self._timestamps: Dict[str, float] = {}
        self._default_cooldown = default_cooldown
        self._cache_path = cache_path
        self._load_cache()

    def _load_cache(self):
        if not self._cache_path or not os.path.exists(self._cache_path):
            return
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = time.time()
            if isinstance(data, dict):
                for k, expiry in data.items():
                    if isinstance(expiry, (int, float)) and expiry > now:
                        self._timestamps[k] = float(expiry)
        except Exception:
            pass

    def _save_cache(self):
        if not self._cache_path:
            return
        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            now = time.time()
            active = {k: exp for k, exp in self._timestamps.items() if exp > now}
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(active, f)
        except Exception:
            pass

    def add(self, item: str, cooldown: Optional[int] = None):
        duration = cooldown if cooldown is not None else self._default_cooldown
        self._timestamps[item] = time.time() + duration
        self._save_cache()

    def remove(self, item: str):
        self._timestamps.pop(item, None)
        self._save_cache()

    def discard(self, item: str):
        self._timestamps.pop(item, None)
        self._save_cache()

    def __contains__(self, item: str) -> bool:
        if item not in self._timestamps:
            return False
        expiry = self._timestamps[item]
        if time.time() >= expiry:
            del self._timestamps[item]
            self._save_cache()
            return False
        return True

    def __iter__(self):
        now = time.time()
        active = [k for k, exp in list(self._timestamps.items()) if exp > now]
        return iter(active)

    def __len__(self) -> int:
        now = time.time()
        return sum(1 for exp in self._timestamps.values() if exp > now)

    def clear(self):
        self._timestamps.clear()
        self._save_cache()

# Global tracking with time-based cooldown to prevent permanent blacklisting
_UNAVAILABLE_MODELS = CooldownSet()
_UNAVAILABLE_PROVIDERS = CooldownSet()
_UNAVAILABLE_KEYS = CooldownSet()


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

        self.ollama_base = CONFIG.get("OLLAMA_API_BASE", "http://localhost:11434")
        self.ollama_model = CONFIG.get("OLLAMA_MODEL", "llama3.2:latest")
        self.ollama_enabled = CONFIG.get("OLLAMA_ENABLED", True)
        self.ollama_timeout = float(CONFIG.get("OLLAMA_TIMEOUT", 60.0))
        self.ollama_interactive_timeout = float(CONFIG.get("OLLAMA_INTERACTIVE_TIMEOUT", 3.8))
        self.interactive_timeout = float(CONFIG.get("LLM_INTERACTIVE_TIMEOUT", 7.0))

        # Primary provider and authoritative timeout configuration
        self.primary_provider = str(CONFIG.get("LLM_PRIMARY_PROVIDER", CONFIG.get("PRIMARY_PROVIDER", "openai"))).lower().strip()
        self.request_timeout = float(CONFIG.get("LLM_REQUEST_TIMEOUT", CONFIG.get("LLM_TIMEOUT", 65.0)))
        self.groq_timeout = float(CONFIG.get("GROQ_TIMEOUT", 6.0))
        self.openai_timeout = float(CONFIG.get("OPENAI_TIMEOUT", 8.0))
        self.gemini_timeout = float(CONFIG.get("GEMINI_TIMEOUT", 6.0))
        self.deepseek_timeout = float(CONFIG.get("DEEPSEEK_TIMEOUT", 8.0))
        self.hf_timeout = float(CONFIG.get("HF_TIMEOUT", 6.0))

        # Backward compatibility attributes (use first available key)
        self.openai_key = self.openai_keys[0] if self.openai_keys else ""
        self.groq_key = self.groq_keys[0] if self.groq_keys else ""
        self.gemini_key = self.gemini_keys[0] if self.gemini_keys else ""
        self.deepseek_key = self.deepseek_keys[0] if self.deepseek_keys else ""
        self.hf_key = self.hf_keys[0] if self.hf_keys else ""
        
        self.api_key = self.groq_key
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = self.groq_model

    def _call_openai(self, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int, timeout: float = 8.0) -> Optional[str]:
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
                    timeout=timeout
                )
                return response.choices[0].message.content
            except Exception as e:
                err_str = str(e).lower()
                if "insufficient_quota" in err_str or "quota" in err_str or "429" in err_str or "rate_limit" in err_str:
                    print(f"[LLM] Provider=OpenAI Key slot {key_index} quota exceeded or rate limited. Marking key unavailable and trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=300)
                elif "model_not_found" in err_str or "404" in err_str or "does not exist" in err_str:
                    print(f"[LLM] Provider=OpenAI Model={model} not found (HTTP 404). Marking model unavailable.")
                    _UNAVAILABLE_MODELS.add(model_tag, cooldown=3600)
                elif "authentication" in err_str or "invalid" in err_str or "401" in err_str:
                    print(f"[LLM] Provider=OpenAI Key slot {key_index} authentication failed. Marking key unavailable.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=3600)
                else:
                    print(f"[LLM] Provider=OpenAI Key slot {key_index} request failed: {type(e).__name__}. Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=120)
        # If all keys are unavailable, mark entire provider unavailable
        if all(f"openai_key_{i}" in _UNAVAILABLE_KEYS for i in range(len(self.openai_keys))):
            _UNAVAILABLE_PROVIDERS.add("openai", cooldown=300)
        return None

    def _call_groq(self, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int, timeout: float = 6.0) -> Optional[str]:
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
                res = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=timeout)
                if res.status_code == 200:
                    data = res.json()
                    return data['choices'][0]['message']['content']
                elif res.status_code == 404 or "model_not_found" in res.text or "does not exist" in res.text:
                    print(f"[LLM] Provider=Groq Key slot {key_index} Model={model} not found (HTTP 404). Marking model unavailable.")
                    _UNAVAILABLE_MODELS.add(model_tag, cooldown=3600)
                    break
                elif res.status_code == 429:
                    print(f"[LLM] Provider=Groq Key slot {key_index} rate limited (HTTP 429). Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=300)
                elif res.status_code == 401 or "authentication" in res.text.lower():
                    print(f"[LLM] Provider=Groq Key slot {key_index} authentication failed. Marking key unavailable.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=3600)
                else:
                    print(f"[LLM] Provider=Groq Key slot {key_index} HTTP {res.status_code} error. Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=120)
            except Exception as e:
                print(f"[LLM] Provider=Groq Key slot {key_index} connection exception: {type(e).__name__}. Trying next key.")
                _UNAVAILABLE_KEYS.add(key_tag, cooldown=120)

        # If all keys are unavailable or rate-limited, mark entire provider unavailable
        if all(f"groq_key_{i}" in _UNAVAILABLE_KEYS for i in range(len(self.groq_keys))):
            _UNAVAILABLE_PROVIDERS.add("groq", cooldown=300)
        return None

    def _call_gemini(self, prompt: str, system_prompt: str, model: str, temperature: float, max_tokens: int, timeout: float = 6.0) -> Optional[str]:
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
                res = requests.post(url, json=payload, timeout=timeout)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"]
                elif res.status_code == 404 or "not found" in res.text.lower():
                    print(f"[LLM] Provider=Gemini Key slot {key_index} Model={model} not found (HTTP 404). Marking model unavailable.")
                    _UNAVAILABLE_MODELS.add(model_tag, cooldown=3600)
                    break
                elif res.status_code == 429:
                    print(f"[LLM] Provider=Gemini Key slot {key_index} rate limit / quota exceeded (HTTP 429). Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=300)
                elif res.status_code == 401 or "authentication" in res.text.lower():
                    print(f"[LLM] Provider=Gemini Key slot {key_index} authentication failed. Marking key unavailable.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=3600)
                else:
                    print(f"[LLM] Provider=Gemini Key slot {key_index} HTTP {res.status_code} error. Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=120)
            except Exception as e:
                print(f"[LLM] Provider=Gemini Key slot {key_index} connection exception: {type(e).__name__}. Trying next key.")
                _UNAVAILABLE_KEYS.add(key_tag, cooldown=120)

        # If all keys are unavailable or rate-limited, mark entire provider unavailable
        if all(f"gemini_key_{i}" in _UNAVAILABLE_KEYS for i in range(len(self.gemini_keys))):
            _UNAVAILABLE_PROVIDERS.add("gemini", cooldown=300)
        return None

    def _call_deepseek(self, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int, timeout: float = 6.0) -> Optional[str]:
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
                res = requests.post("https://api.deepseek.com/chat/completions", json=payload, headers=headers, timeout=timeout)
                if res.status_code == 200:
                    return res.json()['choices'][0]['message']['content']
                elif res.status_code == 402 or "insufficient balance" in res.text.lower():
                    print(f"[LLM] Provider=DeepSeek Key slot {key_index} insufficient balance (HTTP 402). Marking key unavailable.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=3600)
                    _UNAVAILABLE_PROVIDERS.add("deepseek", cooldown=3600)
                elif res.status_code == 404:
                    print(f"[LLM] Provider=DeepSeek Key slot {key_index} Model={model} not found (HTTP 404). Marking model unavailable.")
                    _UNAVAILABLE_MODELS.add(model_tag, cooldown=3600)
                    break
                elif res.status_code == 429:
                    print(f"[LLM] Provider=DeepSeek Key slot {key_index} rate limited (HTTP 429). Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=300)
                elif res.status_code == 401 or "authentication" in res.text.lower():
                    print(f"[LLM] Provider=DeepSeek Key slot {key_index} authentication failed. Marking key unavailable.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=3600)
                else:
                    print(f"[LLM] Provider=DeepSeek Key slot {key_index} HTTP {res.status_code} error. Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=120)
            except Exception as e:
                print(f"[LLM] Provider=DeepSeek Key slot {key_index} exception: {type(e).__name__}. Trying next key.")
                _UNAVAILABLE_KEYS.add(key_tag, cooldown=120)

        # If all keys are unavailable, mark entire provider unavailable
        if all(f"deepseek_key_{i}" in _UNAVAILABLE_KEYS for i in range(len(self.deepseek_keys))):
            _UNAVAILABLE_PROVIDERS.add("deepseek", cooldown=300)
        return None

    def _call_huggingface(self, prompt: str, system_prompt: str, model: str, max_tokens: int, timeout: float = 6.0) -> Optional[str]:
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
                res = requests.post(url, headers=headers, json=payload, timeout=timeout)
                if res.status_code == 200:
                    data = res.json()
                    return data['choices'][0]['message']['content']
                elif res.status_code == 404 or res.status_code == 400:
                    print(f"[LLM] Provider=HuggingFace Key slot {key_index} Model={model} unavailable (HTTP {res.status_code}). Marking model and provider unavailable.")
                    _UNAVAILABLE_MODELS.add(model_tag, cooldown=3600)
                    _UNAVAILABLE_PROVIDERS.add("huggingface", cooldown=1800)
                    break
                elif res.status_code == 429:
                    print(f"[LLM] Provider=HuggingFace Key slot {key_index} rate limited (HTTP 429). Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=300)
                elif res.status_code == 401 or "authentication" in res.text.lower():
                    print(f"[LLM] Provider=HuggingFace Key slot {key_index} authentication failed. Marking key unavailable.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=3600)
                else:
                    print(f"[LLM] Provider=HuggingFace Key slot {key_index} HTTP {res.status_code} error. Trying next key.")
                    _UNAVAILABLE_KEYS.add(key_tag, cooldown=120)
            except Exception as e:
                print(f"[LLM] Provider=HuggingFace Key slot {key_index} exception: {type(e).__name__}. Trying next key.")
                _UNAVAILABLE_KEYS.add(key_tag, cooldown=120)

        # If all keys are unavailable, mark entire provider unavailable
        if all(f"huggingface_key_{i}" in _UNAVAILABLE_KEYS for i in range(len(self.hf_keys))):
            _UNAVAILABLE_PROVIDERS.add("huggingface", cooldown=300)
        return None

    def _call_ollama(self, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int, timeout: Optional[float] = None) -> Optional[str]:
        if "ollama" in _UNAVAILABLE_PROVIDERS or not self.ollama_enabled:
            return None
        model_tag = f"ollama:{model}"
        if model_tag in _UNAVAILABLE_MODELS:
            return None

        effective_timeout = timeout if timeout is not None else self.ollama_timeout

        # Quick socket check to verify Ollama daemon is active before making request
        try:
            import socket
            from urllib.parse import urlparse
            p = urlparse(self.ollama_base)
            with socket.create_connection((p.hostname or "localhost", p.port or 11434), timeout=1.5):
                pass
        except Exception:
            print(f"[LLM] Provider=Ollama daemon not reachable at {self.ollama_base}.")
            _UNAVAILABLE_PROVIDERS.add("ollama", cooldown=30)
            return None

        try:
            url = f"{self.ollama_base.rstrip('/')}/api/chat"
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "keep_alive": "30m",
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            res = requests.post(url, json=payload, timeout=effective_timeout)
            if res.status_code == 200:
                data = res.json()
                if "message" in data and "content" in data["message"]:
                    return data["message"]["content"]
            elif res.status_code == 404 or "not found" in res.text.lower():
                print(f"[LLM] Provider=Ollama Model={model} not found (HTTP 404). Marking model unavailable.")
                _UNAVAILABLE_MODELS.add(model_tag, cooldown=1800)
            else:
                print(f"[LLM] Provider=Ollama HTTP {res.status_code} error.")
                _UNAVAILABLE_PROVIDERS.add("ollama", cooldown=60)
        except requests.exceptions.Timeout:
            print(f"[LLM] Provider=Ollama request timed out after {effective_timeout:.1f}s.")
            _UNAVAILABLE_PROVIDERS.add("ollama", cooldown=30)
        except Exception as e:
            print(f"[LLM] Provider=Ollama connection exception: {type(e).__name__}.")
            _UNAVAILABLE_PROVIDERS.add("ollama", cooldown=30)
        return None

    def get_completion(
        self,
        prompt: str,
        context: str = "",
        memory: str = "",
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        user_id: Optional[int] = None,
        timeout_budget: Optional[float] = None,
        task_type: str = "interactive",
    ) -> Optional[str]:
        """
        Execute completion with bounded timeout budget and healthy-first provider selection.
        Honors primary provider preference and authoritative request deadline.
        Task-specific deadlines: interactive requests target 5-8s total with fast Ollama timeout (~3.8s);
        deep reasoning / document / coding preserves generous limits.
        """
        if not prompt or not str(prompt).strip():
            return None

        is_interactive = task_type in ("interactive", "conversational", "chat", "classification")
        primary = getattr(self, "primary_provider", "openai").lower().strip()
        if timeout_budget is None:
            if is_interactive:
                timeout_budget = self.interactive_timeout
            else:
                if primary == "ollama" or (self.ollama_enabled and "ollama" not in _UNAVAILABLE_PROVIDERS):
                    timeout_budget = max(self.request_timeout, self.ollama_timeout + 5.0)
                else:
                    timeout_budget = self.request_timeout

        start_time = time.time()
        deadline = start_time + timeout_budget

        def get_call_timeout(prov_timeout: float) -> float:
            rem = deadline - time.time()
            return max(0.5, min(prov_timeout, rem))

        if system_prompt is None:
            # Use the per-user configured assistant name; never fall back to "NOVA"
            try:
                from instance.config import settings as _cfg
                _asst_name = _cfg.get_assistant_name()
            except Exception:
                _asst_name = None

            if _asst_name:
                identity_line = (
                    f"You are {_asst_name}, an intelligent assistant developed by Trevon Labs with a calm, professional, and capable presence. "
                )
            else:
                identity_line = (
                    "You are Trevon, an intelligent assistant developed by Trevon Labs with a calm, professional, and capable presence. "
                )

            system_prompt = (
                identity_line
                + "You have long-term memory and can recall previous conversations and user preferences. "
                "Integrate memory and context naturally into your answers without announcing internal memory, context, or retrieval mechanisms. "
                "Do NOT use meta-commentary phrases like 'Based on what I recall...', 'Based on your history...', 'From your references...', or 'According to my context...'. "
                "Your responses should be clear, confident, and approachable. "
                "You maintain continuity across sessions and build upon previous interactions.\n"
                f"Current Context: {context}\n"
                f"Relevant Memory: {memory}\n"
                "Guidelines:\n"
                "- Answer questions directly, naturally, and concisely\n"
                "- Spoken voice policy: keep responses concise (1–3 sentences for ordinary conversation, 1–4 sentences for simple factual or explanatory questions, 1 short sentence for actions)\n"
                "- Never output bloated multi-category bullet lists unless explicitly asked to 'show the full list'\n"
                "- Confirm commands before execution\n"
                "- Use memory and context naturally without announcing it\n"
                "- Maintain consistent professional tone\n"
                "- Never include internal reasoning, retrieval metadata, or explanations of how you found the answer\n"
                "Provide only your final response to the user."
            )

        # Resolve user ID for user-isolated personalization
        resolved_uid = user_id
        if resolved_uid is None:
            try:
                from instance.config import settings as _cfg
                resolved_uid = getattr(_cfg, 'CURRENT_USER_ID', None) or _cfg.get_last_user()
            except Exception:
                resolved_uid = None

        # Personalization: Inject authenticated user's learned rules & preferences ONLY for verified user
        if resolved_uid is not None:
            try:
                from skills.learning.learned_rules import get_learned_rules_engine
                lr_engine = get_learned_rules_engine()
                injections = lr_engine.get_prompt_injections(int(resolved_uid))
                if injections and injections.strip():
                    rule_block = (
                        "\n[USER PERSONALIZATION & LEARNED RULES]\n"
                        "The user has specified the following persistent preferences for your responses:\n"
                        f"{injections.strip()}\n"
                        "Adhere to these preferences while maintaining standard safety and operational guidelines.\n"
                    )
                    system_prompt = (system_prompt or "") + "\n" + rule_block
            except Exception:
                pass

        # Inject canonical runtime temporal context for any queries dealing with current time/date
        temporal_keywords = ("today", "now", "current", "tonight", "tomorrow", "this week")
        prompt_low = (prompt or "").lower()
        if any(k in prompt_low for k in temporal_keywords):
            try:
                from core.temporal_context import format_temporal_prompt_block
                temporal_block = format_temporal_prompt_block()
                if temporal_block not in (system_prompt or ""):
                    system_prompt = f"{system_prompt}\n\n{temporal_block}"
            except Exception:
                pass

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        default_chain = ["openai", "groq", "gemini", "deepseek", "huggingface", "ollama"]
        if primary in default_chain and primary != "ollama":
            provider_chain = [primary] + [p for p in default_chain if p != primary]
        else:
            provider_chain = default_chain

        for prov in provider_chain:
            if prov in _UNAVAILABLE_PROVIDERS:
                continue

            rem_budget = deadline - time.time()
            if rem_budget < 0.5:
                print(f"[LLM] Request deadline reached ({timeout_budget:.1f}s budget exhausted).")
                break

            prov_start = time.time()

            if prov == "groq":
                if self.groq_keys and "groq" not in _UNAVAILABLE_PROVIDERS:
                    models_to_try = [self.groq_model] + [m for m in self.groq_fallback_models if m != self.groq_model]
                    for m in models_to_try:
                        if f"groq:{m}" in _UNAVAILABLE_MODELS:
                            continue
                        call_to = get_call_timeout(self.groq_timeout)
                        try:
                            resp = self._call_groq(messages, m, temperature, max_tokens, timeout=call_to)
                            if resp:
                                return resp
                        except Exception as e:
                            print(f"[LLM] Provider=Groq raised {type(e).__name__}: {e}")
                        if deadline - time.time() < 0.5:
                            break
                    print(f"[LLM] Provider=Groq attempt failed (elapsed={time.time() - prov_start:.2f}s). Remaining: {max(0.0, deadline - time.time()):.2f}s")

            elif prov == "openai":
                if self.openai_enabled and self.openai_keys and "openai" not in _UNAVAILABLE_PROVIDERS:
                    call_to = get_call_timeout(self.openai_timeout)
                    try:
                        resp = self._call_openai(messages, self.openai_model, temperature, max_tokens, timeout=call_to)
                        if resp:
                            return resp
                    except Exception as e:
                        print(f"[LLM] Provider=OpenAI raised {type(e).__name__}: {e}")
                    print(f"[LLM] Provider=OpenAI attempt failed (elapsed={time.time() - prov_start:.2f}s). Remaining: {max(0.0, deadline - time.time()):.2f}s")

            elif prov == "gemini":
                if self.gemini_keys and "gemini" not in _UNAVAILABLE_PROVIDERS:
                    call_to = get_call_timeout(self.gemini_timeout)
                    try:
                        resp = self._call_gemini(prompt, system_prompt, self.gemini_model, temperature, max_tokens, timeout=call_to)
                        if resp:
                            return resp
                    except Exception as e:
                        print(f"[LLM] Provider=Gemini raised {type(e).__name__}: {e}")
                    print(f"[LLM] Provider=Gemini attempt failed (elapsed={time.time() - prov_start:.2f}s). Remaining: {max(0.0, deadline - time.time()):.2f}s")

            elif prov == "deepseek":
                if self.deepseek_keys and "deepseek" not in _UNAVAILABLE_PROVIDERS:
                    call_to = get_call_timeout(self.deepseek_timeout)
                    try:
                        resp = self._call_deepseek(messages, self.deepseek_model, temperature, max_tokens, timeout=call_to)
                        if resp:
                            return resp
                    except Exception as e:
                        print(f"[LLM] Provider=DeepSeek raised {type(e).__name__}: {e}")
                    print(f"[LLM] Provider=DeepSeek attempt failed (elapsed={time.time() - prov_start:.2f}s). Remaining: {max(0.0, deadline - time.time()):.2f}s")

            elif prov == "huggingface":
                if self.hf_keys and "huggingface" not in _UNAVAILABLE_PROVIDERS:
                    call_to = get_call_timeout(self.hf_timeout)
                    try:
                        resp = self._call_huggingface(prompt, system_prompt, self.hf_model, max_tokens, timeout=call_to)
                        if resp:
                            return resp
                    except Exception as e:
                        print(f"[LLM] Provider=HuggingFace raised {type(e).__name__}: {e}")
                    print(f"[LLM] Provider=HuggingFace attempt failed (elapsed={time.time() - prov_start:.2f}s). Remaining: {max(0.0, deadline - time.time()):.2f}s")

            elif prov == "ollama":
                if self.ollama_enabled and "ollama" not in _UNAVAILABLE_PROVIDERS:
                    ollama_limit = self.ollama_interactive_timeout if is_interactive else self.ollama_timeout
                    call_to = get_call_timeout(ollama_limit)
                    try:
                        resp = self._call_ollama(messages, self.ollama_model, temperature, max_tokens, timeout=call_to)
                        if resp:
                            return resp
                    except Exception as e:
                        print(f"[LLM] Provider=Ollama raised {type(e).__name__}: {e}")
                    print(f"[LLM] Provider=Ollama attempt failed (elapsed={time.time() - prov_start:.2f}s, timeout={call_to:.1f}s). Remaining: {max(0.0, deadline - time.time()):.2f}s")

        print("[LLM] All configured providers and fallback keys exhausted within budget.")
        return None

    def stream_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        context: Optional[str] = None,
        memory: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        user_id: Optional[int] = None
    ):
        """
        Streams completion sentence-by-sentence.
        Yields each completed sentence as soon as it is generated for instant TTS dispatch.
        """
        full_text = self.get_completion(
            prompt=prompt,
            system_prompt=system_prompt,
            context=context,
            memory=memory,
            temperature=temperature,
            max_tokens=max_tokens,
            user_id=user_id
        )
        if not full_text:
            return

        from extensions.system.tts_backend import split_sentences_for_streaming
        sentences = split_sentences_for_streaming(full_text)
        for s in sentences:
            if s.strip():
                yield s.strip()

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
        "RECOMMENDATION",
        "GAME_DISCOVERY",
        "SYSTEM_COMPATIBILITY",
        "WEB_SEARCH",
        "RAG_SEARCH",
        "VISUAL_SURFACE",
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
        "  MUSIC              — play/pause/resume/stop/skip music, songs, audio tracks, Spotify. NEVER use for games ('play games' is GAME_DISCOVERY)\n"
        "  RECOMMENDATION     — suggest or recommend items, movies, books, general recommendations ('suggest some action movies')\n"
        "  GAME_DISCOVERY     — discover, suggest, or find games to play or download ('suggest some online games', 'can we play some games online', 'recommend games I can download')\n"
        "  SYSTEM_COMPATIBILITY — check if games/apps can run on this system, system hardware compatibility, or compare requirements ('which games can run on this PC', 'what games are compatible with my system', 'compare those game requirements to my system')\n"
        "  EMAIL              — send/read/check/reply email\n"
        "  NOTES              — take a note, jot down\n"
        "  REMINDERS          — set a reminder, alert me, remind me\n"
        "  CALCULATOR         — arithmetic, math calculation (e.g. 'calculate 25 * 8', 'what is 12 + 37'). NEVER for generating or listing numbers\n"
        "  CODE_GENERATION    — write/build/create code, programs, scripts\n"
        "  TRANSLATION        — translate text to another language\n"
        "  TIME_QUERY         — asking what time it is\n"
        "  DATE_QUERY         — asking what date/day it is\n"
        "  WEATHER_QUERY      — asking about weather, temperature, forecast, umbrella\n"
        "  MEMORY_QUERY       — asking what the assistant remembers about the user, or what the user and assistant were working on\n"
        "  RAG_SEARCH         — ONLY for explicit requests to search the web/internet, live dynamic lookups, or breaking news ('search the web for...', 'look up online...', 'latest news'). NEVER for general concepts, definitions, programming queries, or conversation\n"
        "  VISUAL_SURFACE     — requests to show, display, or generate numbers, lists, pairing codes, results, or data ('show me 10 numbers', 'generate 5 random numbers', 'show that again')\n"
        "  GENERAL_CONVERSATION — greetings ('hello', 'hi'), presence checks ('are you there', 'you there'), identity ('who are you', 'what is your name'), small talk, explanations of concepts ('what is Python', 'how does backpropagation work'), assistant capabilities ('what can you do', 'the action that you can perform'), user feedback/complaints, and conversational follow-ups\n"
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
                timeout_budget=2.5,
                task_type="classification",
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
            "FILE_OPERATIONS", "POWER_ACTION", "CLOSE_APPLICATION", "EMAIL",
        }
        is_destructive = intent_label in DESTRUCTIVE_INTENTS
        if intent_label == "DEVICE_CONTROL":
            action_name = (normalised_entities.get("action") or "").lower()
            text_low = user_input.lower()
            read_only_keywords = [
                "list", "show", "status", "connected", "online", "battery",
                "check", "is my", "what devices", "paired devices"
            ]
            is_read_only = any(k in text_low for k in read_only_keywords) and not any(
                d in text_low for d in ["lock", "disconnect", "unpair", "remove", "wipe", "delete", "shutdown", "reboot", "restart"]
            )
            disruptive_keywords = [
                "lock", "disconnect", "unpair", "remove", "forget", "remote action",
                "execute", "launch", "open", "turn on", "turn off", "toggle", "flashlight", "torch"
            ]
            if not is_read_only or any(d in text_low or d in action_name for d in disruptive_keywords):
                is_destructive = True

        if confidence < 0.70 and is_destructive:
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
            f"[SEMANTIC_RESOLVE] '{user_input[:60]}' -> intent={intent_label} "
            f"confidence={confidence:.2f} clarify={needs_clarification}"
        )
        return result

    def semantic_reasoning(
        self,
        user_input: str,
        structured_context: Optional[Dict[str, Any]] = None,
        timeout_budget: float = 3.0,
    ) -> Dict[str, Any]:
        """
        Primary semantic reasoning layer for NOVA.
        Understands the true MEANING of natural language utterances given structured context.
        Distinguishes instructions, questions, explanations, negations, hypotheticals, and corrections.
        Resolves pronouns ('it', 'that', 'there', 'the previous one') using context.
        """
        import json as _json

        _fallback = {
            "goal": user_input,
            "request_type": "INSTRUCTION",
            "requires_action": True,
            "requires_information": False,
            "requires_clarification": False,
            "clarification_prompt": None,
            "capability": "AUTO",
            "parameters": {"action": None, "target": None, "text": None, "destination": None, "query_type": None},
            "references": {"what": None, "where": None},
            "is_multi_step": False,
            "steps": [],
            "confidence": 0.5,
            "source": "fallback",
        }

        if not user_input or not user_input.strip():
            return _fallback

        # Format structured context into a concise prompt block
        ctx_lines = []
        ctx = structured_context or {}
        if ctx.get("current_environment"):
            ce = ctx["current_environment"]
            ce_parts = []
            if ce.get("application"): ce_parts.append(f"app={ce['application']}")
            if ce.get("window_title"): ce_parts.append(f"window='{ce['window_title']}'")
            if ce.get("document"): ce_parts.append(f"doc='{ce['document']}'")
            if ce.get("url"): ce_parts.append(f"url='{ce['url']}'")
            if ce.get("folder"): ce_parts.append(f"folder='{ce['folder']}'")
            if ce.get("selected_files"): ce_parts.append(f"selected={ce['selected_files']}")
            if ce_parts: ctx_lines.append(f"Current Environment: {', '.join(ce_parts)}")

        if ctx.get("previous_environment"):
            pe = ctx["previous_environment"]
            pe_parts = []
            if pe.get("application"): pe_parts.append(f"app={pe['application']}")
            if pe.get("window_title"): pe_parts.append(f"window='{pe['window_title']}'")
            if pe_parts: ctx_lines.append(f"Previous Environment: {', '.join(pe_parts)}")

        if ctx.get("active_artifact"):
            art = ctx["active_artifact"]
            ctx_lines.append(f"Active Artifact: topic='{art.get('topic')}', summary='{art.get('summary', '')[:80]}'")

        if ctx.get("active_goal"):
            ag = ctx["active_goal"]
            ctx_lines.append(f"Active Goal: topic='{ag.get('topic')}', description='{ag.get('description', '')[:80]}'")

        if ctx.get("recent_actions"):
            acts = ctx["recent_actions"]
            act_strs = [f"{a.get('action')} target={a.get('target')}" for a in acts[-2:]]
            ctx_lines.append(f"Recent OS Actions: {'; '.join(act_strs)}")

        if ctx.get("recent_dialogue"):
            dialogue = ctx["recent_dialogue"]
            diag_strs = [f"User: '{d.get('user')}' -> Assistant: '{d.get('assistant', '')[:60]}'" for d in dialogue[-2:]]
            ctx_lines.append(f"Recent Conversation:\n" + "\n".join(diag_strs))

        context_block = "\n".join(ctx_lines) if ctx_lines else "No active context."

        system_prompt = (
            "You are the primary semantic reasoning engine of a voice-first Windows computer assistant.\n"
            "Your job is to understand the true MEANING, underlying goal, and structured parameters of the user's utterance.\n"
            "You must NOT simply match words or keywords.\n\n"
            "CRITICAL LINGUISTIC RULES:\n"
            "1. REQUEST TYPE:\n"
            "   - 'INSTRUCTION': User gives a command to perform an action (e.g. 'Open Notepad', 'Bring up Notepad', 'I need the text editor', 'Put that in Downloads', 'Stop reading', 'Read it').\n"
            "   - 'QUESTION': User asks for information or state (e.g. 'What app am I using?', 'Where did you put the file?', 'What folder am I in?', 'Did you open Notepad?', 'What did you just do?', 'What was open before this?').\n"
            "     CRITICAL: QUESTIONS MUST NEVER EXECUTE ACTIONS! Even if words like 'open', 'put', or 'folder' appear!\n"
            "   - 'EXPLANATION': User asks why something happened (e.g. 'Why did you open Notepad?'). EXPLANATIONS MUST NEVER EXECUTE ACTIONS!\n"
            "   - 'NEGATION': User explicitly negates or forbids an action (e.g. 'Don't open Notepad', 'I don't want Notepad open', 'Do not create that file'). NEGATIONS MUST NEVER EXECUTE ACTIONS!\n"
            "   - 'HYPOTHETICAL': User discusses a possibility (e.g. 'I was thinking about opening Notepad', 'What if we used Chrome?'). MUST NOT EXECUTE ACTIONS!\n"
            "   - 'CORRECTION': User corrects a previous request or target (e.g. 'Actually open Chrome instead', 'No, put it in Downloads instead', 'No, the other one').\n"
            "   - 'CONVERSATION': Greetings, small talk, capabilities ('Hey Friday', 'What can you do?').\n\n"
            "2. REFERENCE & PRONOUN RESOLUTION:\n"
            "   - 'that', 'it', 'this', 'what you found', 'the information gathered' -> resolve to the active artifact or recently discussed entity in context.\n"
            "   - 'there', 'here' -> resolve to current active window, focused application, or destination folder in context.\n"
            "   - 'the previous one', 'the one before' -> resolve to previous application, previous document, or previous window in context.\n\n"
            "3. DYNAMIC CONTEXT:\n"
            "   - Current user utterance has priority! Context exists to resolve references, never to override a new explicit request.\n\n"
            "OUTPUT ONLY A STRICT JSON OBJECT:\n"
            "{\n"
            '  "goal": "<concise summary of underlying user goal>",\n'
            '  "request_type": "<INSTRUCTION | QUESTION | EXPLANATION | NEGATION | HYPOTHETICAL | CORRECTION | CONVERSATION>",\n'
            '  "requires_action": <true ONLY for INSTRUCTION or actionable CORRECTION; false for QUESTION, EXPLANATION, NEGATION, HYPOTHETICAL, CONVERSATION>,\n'
            '  "requires_information": <true for QUESTION or EXPLANATION; false otherwise>,\n'
            '  "requires_clarification": <true if genuinely ambiguous>,\n'
            '  "clarification_prompt": <string or null>,\n'
            '  "capability": "<OPEN_APPLICATION | CLOSE_APPLICATION | DEVICE_CONTROL | CONTENT_INSERTION | CONTENT_ACQUISITION | ARTIFACT_READING | ENVIRONMENT_QUERY | HISTORICAL_QUERY | FILE_OPERATIONS | TASK_MANAGEMENT | MUSIC | STOP_SPEECH | GENERAL_CONVERSATION>",\n'
            '  "parameters": {\n'
            '    "action": "<action name or null>",\n'
            '    "target": "<target app, file, or topic or null>",\n'
            '    "text": "<text to type/insert or null>",\n'
            '    "destination": "<destination folder/window or null>",\n'
            '    "query_type": "<current_app | previous_app | current_folder | selected_file | current_website | past_action | past_search | past_task | capabilities | null>"\n'
            '  },\n'
            '  "references": {\n'
            '    "what": "<resolved content/artifact reference or null>",\n'
            '    "where": "<resolved destination/target reference or null>"\n'
            '  },\n'
            '  "is_multi_step": <true if compound goal requiring multiple sequential steps>,\n'
            '  "steps": [\n'
            '    {"capability": "...", "target": "...", "parameters": {...}}\n'
            '  ],\n'
            '  "confidence": <0.0 to 1.0>\n'
            "}"
        )

        user_prompt = f"Context:\n{context_block}\n\nUser utterance:\n\"{user_input}\""

        try:
            raw = self.get_completion(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.0,
                max_tokens=350,
                timeout_budget=timeout_budget
            )
        except Exception as e:
            print(f"[SEMANTIC_REASONING] LLM error: {e}")
            return _fallback

        if not raw:
            return _fallback

        raw = raw.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            parsed = _json.loads(raw)
            if not isinstance(parsed, dict):
                return _fallback
            parsed["source"] = "semantic_llm"
            return parsed
        except Exception as e:
            print(f"[SEMANTIC_REASONING] JSON decode failed: {e} | Raw: {raw[:150]}")
            return _fallback

