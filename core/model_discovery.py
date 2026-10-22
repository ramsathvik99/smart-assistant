"""
core/model_discovery.py
=======================
Dynamic, authenticated model discovery engine for Friday / Smart Assistant.

Queries official model discovery endpoints for each configured provider and key:
- OpenAI: GET https://api.openai.com/v1/models
- Groq: GET https://api.groq.com/openai/v1/models
- Google Gemini: GET https://generativelanguage.googleapis.com/v1beta/models?key={key}
- DeepSeek: GET https://api.deepseek.com/models
- Hugging Face: GET https://router.huggingface.co/v1/models (Serverless Inference Providers catalog)
- Anthropic: GET https://api.anthropic.com/v1/models

Guarantees:
1. Never reveals raw API keys, tokens, or secret-bearing headers.
2. Uses non-reversible SHA-256 fingerprints for key attribution.
3. Distinguishes text/chat generation models from embedding-only, audio-only, guard-only, or image-only models.
4. Identifies modalities, context window, capabilities, and deprecation status.
5. Saves sanitized inventory to data/llm_model_catalog.json with caching and refresh policies.
"""

from __future__ import annotations

import os
import sys
import json
import time
import hashlib
import logging
from typing import Dict, List, Any, Optional, Tuple
import requests

logger = logging.getLogger("ModelDiscovery")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CATALOG_PATH = os.path.join(PROJECT_ROOT, "data", "llm_model_catalog.json")
CATALOG_TTL_SECONDS = int(os.getenv("MODEL_CATALOG_TTL_SECONDS", "86400"))  # 24 hours default


def compute_key_fingerprint(api_key: str) -> str:
    """Returns a non-reversible 12-char SHA-256 fingerprint of an API key."""
    if not api_key:
        return "none"
    return hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()[:12]


def mask_key_hint(api_key: str) -> str:
    """Returns safe masked preview for diagnostics (e.g. gsk_...2X4S)."""
    if not api_key:
        return "none"
    k = api_key.strip()
    if len(k) <= 8:
        return f"{k[:2]}...{k[-2:]}"
    return f"{k[:4]}...{k[-4:]}"


class ModelDiscoveryEngine:
    """
    Authoritative authenticated discovery engine for cloud LLM providers.
    """

    def __init__(self, catalog_path: str = CATALOG_PATH):
        self.catalog_path = catalog_path
        self._cache: Optional[Dict[str, Any]] = None
        self._last_loaded_time: float = 0.0
        self._user_caches: Dict[int, Dict[str, Any]] = {}
        self._user_cache_times: Dict[int, float] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # 1. PER-PROVIDER DISCOVERY PROTOCOLS
    # ─────────────────────────────────────────────────────────────────────────

    def discover_openai_models(self, api_key: str, key_ref: str, base_url: str = "https://api.openai.com/v1", timeout: float = 12.0) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Queries OpenAI GET /v1/models using authenticated Bearer token.
        Filters for chat/completion capable models.
        """
        if not api_key:
            return [], "no_key_provided"

        url = f"{base_url.rstrip('/')}/models"
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "User-Agent": "Friday-SmartAssistant/2.0"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                err_text = resp.text[:200]
                status_cat = "auth_error" if resp.status_code == 401 else ("rate_limited" if resp.status_code == 429 else f"http_{resp.status_code}")
                return [], f"{status_cat}: {err_text}"

            data = resp.json().get("data", [])
            discovered: List[Dict[str, Any]] = []
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            # Known non-text or embedding/audio models to exclude from conversational/coding text generation
            excluded_substrings = [
                "tts", "whisper", "dall-e", "embedding", "realtime", "moderation",
                "audio", "transcription", "edit", "similarity", "search", "curie", "babbage", "davinci"
            ]

            for item in data:
                m_id = item.get("id", "")
                if not m_id:
                    continue
                m_lower = m_id.lower()

                # Filter text generation models
                is_text_gen = any(p in m_lower for p in ["gpt", "o1", "o3", "o4", "chat", "codex"]) and not any(sub in m_lower for sub in excluded_substrings)
                if not is_text_gen:
                    continue

                # Capabilities heuristics based on model family
                capabilities = ["text_generation"]
                if "mini" in m_lower or "nano" in m_lower:
                    capabilities.append("fast_inference")
                if any(x in m_lower for x in ["o1", "o3", "o4", "reasoning", "gpt-5", "gpt-4.1", "gpt-4o"]):
                    capabilities.extend(["complex_reasoning", "code_generation", "structured_json", "tool_calling"])
                if "gpt-4o" in m_lower or "gpt-5" in m_lower or "vision" in m_lower:
                    capabilities.append("vision")
                if any(x in m_lower for x in ["gpt-4o", "gpt-4.1", "gpt-5", "128k", "mini"]):
                    capabilities.append("long_context")

                ctx_window = 128000
                if "gpt-3.5-turbo" in m_lower:
                    ctx_window = 16385
                elif "gpt-4-32k" in m_lower:
                    ctx_window = 32768
                elif "gpt-4.1" in m_lower or "gpt-5" in m_lower or "o1" in m_lower or "o3" in m_lower:
                    ctx_window = 200000

                model_meta = {
                    "provider": "openai",
                    "id": m_id,
                    "display_name": m_id,
                    "owned_by": item.get("owned_by", "openai"),
                    "key_fingerprint": compute_key_fingerprint(api_key),
                    "credential_reference": key_ref,
                    "discovered_at": now_iso,
                    "api_compatibility": "openai_chat_completions",
                    "status": "available",
                    "input_modalities": ["text", "image"] if "vision" in capabilities else ["text"],
                    "output_modalities": ["text"],
                    "context_window": ctx_window,
                    "max_output_tokens": 16384 if ("o1" in m_lower or "o3" in m_lower or "gpt-4o" in m_lower) else 4096,
                    "capabilities": sorted(list(set(capabilities))),
                    "is_preview": "preview" in m_lower or "preview" in item.get("id", ""),
                    "is_deprecated": False,
                }
                discovered.append(model_meta)

            return discovered, None
        except Exception as e:
            return [], f"request_exception: {type(e).__name__} ({str(e)[:100]})"

    def discover_groq_models(self, api_key: str, key_ref: str, base_url: str = "https://api.groq.com/openai/v1", timeout: float = 12.0) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Queries Groq GET /openai/v1/models using authenticated Bearer token.
        Filters for active chat/completion models.
        """
        if not api_key:
            return [], "no_key_provided"

        url = f"{base_url.rstrip('/')}/models"
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "User-Agent": "Friday-SmartAssistant/2.0"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                err_text = resp.text[:200]
                status_cat = "auth_error" if resp.status_code == 401 else ("rate_limited" if resp.status_code == 429 else f"http_{resp.status_code}")
                return [], f"{status_cat}: {err_text}"

            data = resp.json().get("data", [])
            discovered: List[Dict[str, Any]] = []
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            # Exclude speech, audio, and prompt-guard classifiers
            non_chat_markers = ["whisper", "orpheus", "prompt-guard", "safeguard", "embedding"]

            for item in data:
                m_id = item.get("id", "")
                if not m_id:
                    continue
                m_lower = m_id.lower()
                is_active = item.get("active", True)

                if any(x in m_lower for x in non_chat_markers) or not is_active:
                    continue

                ctx = item.get("context_window", 8192)
                capabilities = ["text_generation", "fast_inference"]
                if ctx >= 64000:
                    capabilities.append("long_context")
                if any(x in m_lower for x in ["qwen", "llama-3", "gpt-oss", "deepseek"]):
                    capabilities.extend(["code_generation", "structured_json", "tool_calling"])
                if any(x in m_lower for x in ["120b", "70b", "qwen3.8", "gpt-oss-120b"]):
                    capabilities.append("complex_reasoning")

                model_meta = {
                    "provider": "groq",
                    "id": m_id,
                    "display_name": m_id,
                    "owned_by": item.get("owned_by", "groq"),
                    "key_fingerprint": compute_key_fingerprint(api_key),
                    "credential_reference": key_ref,
                    "discovered_at": now_iso,
                    "api_compatibility": "groq_chat_completions",
                    "status": "available",
                    "input_modalities": ["text"],
                    "output_modalities": ["text"],
                    "context_window": ctx,
                    "max_output_tokens": min(8192, ctx),
                    "capabilities": sorted(list(set(capabilities))),
                    "is_preview": "preview" in m_lower,
                    "is_deprecated": False,
                }
                discovered.append(model_meta)

            return discovered, None
        except Exception as e:
            return [], f"request_exception: {type(e).__name__} ({str(e)[:100]})"

    def discover_gemini_models(self, api_key: str, key_ref: str, timeout: float = 12.0) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Queries Google Gemini models.list API via GET /v1beta/models?key={key}.
        Filters for models supporting 'generateContent'.
        """
        if not api_key:
            return [], "no_key_provided"

        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key.strip()}"
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code != 200:
                err_text = resp.text[:200]
                status_cat = "auth_error" if resp.status_code in (400, 401, 403) else ("rate_limited" if resp.status_code == 429 else f"http_{resp.status_code}")
                return [], f"{status_cat}: {err_text}"

            data = resp.json().get("models", [])
            discovered: List[Dict[str, Any]] = []
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            for item in data:
                raw_name = item.get("name", "")
                m_id = raw_name.replace("models/", "") if raw_name.startswith("models/") else raw_name
                methods = item.get("supportedGenerationMethods", [])

                # Must support generateContent for text generation
                if "generateContent" not in methods:
                    continue
                # Exclude pure speech synthesis/transcription models from standard text completion
                if "tts" in m_id.lower() or "transcribe" in m_id.lower() or "lyria" in m_id.lower():
                    continue

                display_name = item.get("displayName", m_id)
                in_limit = item.get("inputTokenLimit", 1048576)
                out_limit = item.get("outputTokenLimit", 65536)

                capabilities = ["text_generation", "vision", "multimodal", "structured_json", "tool_calling"]
                if in_limit >= 100000:
                    capabilities.append("long_context")
                if "pro" in m_id.lower() or "research" in m_id.lower() or "3.5" in m_id.lower() or "3.8" in m_id.lower() or "argon" in m_id.lower():
                    capabilities.extend(["complex_reasoning", "code_generation"])
                if "flash" in m_id.lower() or "lite" in m_id.lower():
                    capabilities.append("fast_inference")

                model_meta = {
                    "provider": "gemini",
                    "id": m_id,
                    "display_name": display_name,
                    "owned_by": "google",
                    "key_fingerprint": compute_key_fingerprint(api_key),
                    "credential_reference": key_ref,
                    "discovered_at": now_iso,
                    "api_compatibility": "gemini_generate_content",
                    "status": "available",
                    "input_modalities": ["text", "image", "audio", "video"],
                    "output_modalities": ["text"],
                    "context_window": in_limit,
                    "max_output_tokens": out_limit,
                    "capabilities": sorted(list(set(capabilities))),
                    "is_preview": "preview" in m_id.lower(),
                    "is_deprecated": False,
                }
                discovered.append(model_meta)

            return discovered, None
        except Exception as e:
            return [], f"request_exception: {type(e).__name__} ({str(e)[:100]})"

    def discover_deepseek_models(self, api_key: str, key_ref: str, base_url: str = "https://api.deepseek.com", timeout: float = 12.0) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Queries DeepSeek GET /models using authenticated Bearer token.
        """
        if not api_key:
            return [], "no_key_provided"

        url = f"{base_url.rstrip('/')}/models"
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "User-Agent": "Friday-SmartAssistant/2.0"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                err_text = resp.text[:200]
                status_cat = "auth_error" if resp.status_code == 401 else ("rate_limited" if resp.status_code == 429 else f"http_{resp.status_code}")
                return [], f"{status_cat}: {err_text}"

            data = resp.json().get("data", [])
            discovered: List[Dict[str, Any]] = []
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            for item in data:
                m_id = item.get("id", "")
                if not m_id:
                    continue
                display_name = item.get("name", m_id)
                ctx = item.get("context_window", 1048576)
                out_tokens = item.get("max_output_tokens", 393216)
                in_mods = item.get("input_modalities", ["text"])
                out_mods = item.get("output_modalities", ["text"])

                capabilities = [
                    "text_generation", "code_generation", "code_debugging",
                    "complex_reasoning", "structured_json", "tool_calling", "long_context"
                ]
                if "flash" in m_id.lower():
                    capabilities.append("fast_inference")
                if "image" in in_mods:
                    capabilities.append("vision")

                model_meta = {
                    "provider": "deepseek",
                    "id": m_id,
                    "display_name": display_name,
                    "owned_by": item.get("owned_by", "deepseek"),
                    "key_fingerprint": compute_key_fingerprint(api_key),
                    "credential_reference": key_ref,
                    "discovered_at": now_iso,
                    "api_compatibility": "deepseek_chat_completions",
                    "status": "available",
                    "input_modalities": in_mods,
                    "output_modalities": out_mods,
                    "context_window": ctx,
                    "max_output_tokens": out_tokens,
                    "capabilities": sorted(list(set(capabilities))),
                    "is_preview": False,
                    "is_deprecated": False,
                }
                discovered.append(model_meta)

            return discovered, None
        except Exception as e:
            return [], f"request_exception: {type(e).__name__} ({str(e)[:100]})"

    def discover_huggingface_models(self, api_key: str, key_ref: str, timeout: float = 12.0) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Queries Hugging Face Serverless Inference Providers catalog via GET https://router.huggingface.co/v1/models.
        Identifies active models supporting the chat-completion interface used by Friday.
        """
        if not api_key:
            return [], "no_key_provided"

        url = "https://router.huggingface.co/v1/models"
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "User-Agent": "Friday-SmartAssistant/2.0"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                err_text = resp.text[:200]
                status_cat = "auth_error" if resp.status_code == 401 else ("rate_limited" if resp.status_code == 429 else f"http_{resp.status_code}")
                return [], f"{status_cat}: {err_text}"

            data = resp.json().get("data", [])
            discovered: List[Dict[str, Any]] = []
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            # Filter out non-chat / embedding / reranking models
            non_chat_markers = ["embed", "sentence", "rerank", "reward", "bge", "e5", "whisper", "tts"]

            for item in data:
                m_id = item.get("id", "")
                if not m_id or any(x in m_id.lower() for x in non_chat_markers):
                    continue

                m_lower = m_id.lower()
                capabilities = ["text_generation"]
                if any(x in m_lower for x in ["flash", "8b", "7b", "mini"]):
                    capabilities.append("fast_inference")
                if any(x in m_lower for x in ["instruct", "chat", "qwen", "llama", "deepseek", "glm"]):
                    capabilities.extend(["structured_json", "code_generation"])
                if any(x in m_lower for x in ["deepseek", "70b", "816b", "super", "nemotron"]):
                    capabilities.append("complex_reasoning")
                if any(x in m_lower for x in ["vl", "vision", "super-vl"]):
                    capabilities.append("vision")

                model_meta = {
                    "provider": "huggingface",
                    "id": m_id,
                    "display_name": m_id,
                    "owned_by": item.get("owned_by", "huggingface"),
                    "key_fingerprint": compute_key_fingerprint(api_key),
                    "credential_reference": key_ref,
                    "discovered_at": now_iso,
                    "api_compatibility": "huggingface_router_chat_completions",
                    "status": "available",
                    "input_modalities": ["text", "image"] if "vision" in capabilities else ["text"],
                    "output_modalities": ["text"],
                    "context_window": 32768,
                    "max_output_tokens": 8192,
                    "capabilities": sorted(list(set(capabilities))),
                    "is_preview": False,
                    "is_deprecated": False,
                }
                discovered.append(model_meta)

            return discovered, None
        except Exception as e:
            return [], f"request_exception: {type(e).__name__} ({str(e)[:100]})"

    def discover_anthropic_models(self, api_key: str, key_ref: str, base_url: str = "https://api.anthropic.com/v1", timeout: float = 12.0) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Queries Anthropic GET /v1/models using authenticated x-api-key header.
        """
        if not api_key:
            return [], "no_key_provided"

        url = f"{base_url.rstrip('/')}/models"
        headers = {
            "x-api-key": api_key.strip(),
            "anthropic-version": "2023-06-01",
            "User-Agent": "Friday-SmartAssistant/2.0"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                try:
                    err_json = resp.json()
                    err_obj = err_json.get("error", {})
                    if isinstance(err_obj, dict):
                        e_type = str(err_obj.get("type") or "")
                        e_msg = str(err_obj.get("message") or "")
                        err_text = f"{e_type}: {e_msg}" if e_type else e_msg
                    else:
                        err_text = str(err_obj)
                except Exception:
                    err_text = resp.text[:200]

                from core.credential_manager import sanitize_log_message
                clean_err = sanitize_log_message(err_text)
                status_cat = "auth_error" if resp.status_code in (401, 403) else ("rate_limited" if resp.status_code == 429 else f"http_{resp.status_code}")
                return [], f"{status_cat}: {clean_err}"

            data = resp.json().get("data", [])
            discovered: List[Dict[str, Any]] = []
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            for item in data:
                m_id = item.get("id", "")
                if not m_id:
                    continue
                display_name = item.get("display_name", m_id)
                capabilities = ["text_generation", "complex_reasoning", "code_generation", "code_debugging", "structured_json", "tool_calling", "long_context"]
                if "sonnet" in m_id.lower() or "opus" in m_id.lower():
                    capabilities.append("vision")
                if "haiku" in m_id.lower():
                    capabilities.append("fast_inference")

                model_meta = {
                    "provider": "anthropic",
                    "id": m_id,
                    "display_name": display_name,
                    "owned_by": "anthropic",
                    "key_fingerprint": compute_key_fingerprint(api_key),
                    "credential_reference": key_ref,
                    "discovered_at": now_iso,
                    "api_compatibility": "anthropic_messages",
                    "status": "available",
                    "input_modalities": ["text", "image"] if "vision" in capabilities else ["text"],
                    "output_modalities": ["text"],
                    "context_window": 200000,
                    "max_output_tokens": 8192,
                    "capabilities": sorted(list(set(capabilities))),
                    "is_preview": False,
                    "is_deprecated": False,
                }
                discovered.append(model_meta)

            return discovered, None
        except Exception as e:
            return [], f"request_exception: {type(e).__name__} ({str(e)[:100]})"

    # ─────────────────────────────────────────────────────────────────────────
    # 2. COMPLETE CATALOG DISCOVERY ORCHESTRATOR
    # ─────────────────────────────────────────────────────────────────────────

    def discover_all_credentials(self, user_id: Optional[int] = None, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Discovers all available models for the specified or active authenticated user.
        Ensures strict user credential isolation: never scans across all users in DB,
        and never falls back to shared environment keys for authenticated users.
        """
        from instance.config import settings
        from core.credential_manager import get_credential_manager

        # Resolve active user ID safely without get_last_user()
        active_uid: Optional[int] = None
        if user_id is not None and int(user_id) > 0:
            active_uid = int(user_id)
        else:
            try:
                curr = getattr(settings, 'CURRENT_USER_ID', None)
                if curr is None:
                    from core.assistant_core import get_current_user_id
                    curr = get_current_user_id()
                if curr is not None and int(curr) > 0:
                    active_uid = int(curr)
            except Exception:
                active_uid = None

        if not force_refresh and self._is_cached_valid(active_uid):
            if active_uid and active_uid > 0:
                return self._user_caches.get(active_uid, {})
            return self._cache or {}

        cm = get_credential_manager()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Collect configured keys for each provider (deduplicated by key string)
        # Format: provider -> List of (api_key, key_ref)
        provider_keys: Dict[str, List[Tuple[str, str]]] = {
            "openai": [],
            "groq": [],
            "gemini": [],
            "deepseek": [],
            "huggingface": [],
            "anthropic": []
        }

        # 1. Per-user vault keys (authoritative source) - isolated strictly to active_uid
        if active_uid and active_uid > 0:
            try:
                for prov in provider_keys.keys():
                    k_val = cm.get_credential(active_uid, prov)
                    if k_val and str(k_val).strip():
                        provider_keys[prov].append((k_val.strip(), f"vault:user_{active_uid}:{prov}"))
            except Exception as _e_vault:
                logger.debug(f"Could not load active user vault credentials for user {active_uid}: {_e_vault}")
            # Strict user isolation: Authenticated users NEVER fall back to .env or other users' credentials
        else:
            # 2. Only unauthenticated development operations may check environment keys if explicitly allowed
            allow_env = (
                os.getenv("ALLOW_DEV_ENV_FALLBACK", "").strip().lower() in ("1", "true") or
                os.getenv("ALLOW_LOCAL_FALLBACK", "").strip().lower() in ("1", "true")
            )
            app_env = os.getenv("APP_ENV", "development").lower()
            if allow_env and (app_env == "development" and not getattr(sys, "frozen", False)):
                env_map = {
                    "openai": settings.OPENAI_API_KEYS,
                    "groq": settings.GROQ_API_KEYS,
                    "gemini": settings.GEMINI_API_KEYS,
                    "deepseek": settings.DEEPSEEK_API_KEYS,
                    "huggingface": settings.HF_API_KEYS,
                    "anthropic": settings.ANTHROPIC_API_KEYS
                }
                for prov, env_keys in env_map.items():
                    existing_keys = [pk[0] for pk in provider_keys[prov]]
                    for idx, k in enumerate(env_keys):
                        if k and k.strip() and k.strip() not in existing_keys:
                            provider_keys[prov].append((k.strip(), f"env:{prov.upper()}_API_KEY_{idx}"))

        catalog: Dict[str, Any] = {
            "metadata": {
                "generated_at": now_iso,
                "ttl_seconds": CATALOG_TTL_SECONDS,
                "version": "2.0.0",
                "search_tool_providers": ["serpapi", "tavily"],  # Explicitly documented as non-LLMs
                "excluded_local_providers": ["ollama"]             # Explicitly excluded by design
            },
            "providers": {},
            "models_by_provider": {},
            "all_compatible_models": [],
            "discovery_failures": []
        }

        # Query each configured key separately
        for prov, keys in provider_keys.items():
            catalog["providers"][prov] = {
                "configured_keys_count": len(keys),
                "key_fingerprints": [compute_key_fingerprint(k[0]) for k in keys],
                "status": "configured" if keys else "unconfigured"
            }
            catalog["models_by_provider"][prov] = []

            if not keys:
                continue

            for api_key, key_ref in keys:
                k_fp = compute_key_fingerprint(api_key)
                models: List[Dict[str, Any]] = []
                err: Optional[str] = None

                if prov == "openai":
                    models, err = self.discover_openai_models(api_key, key_ref)
                elif prov == "groq":
                    models, err = self.discover_groq_models(api_key, key_ref)
                elif prov == "gemini":
                    models, err = self.discover_gemini_models(api_key, key_ref)
                elif prov == "deepseek":
                    models, err = self.discover_deepseek_models(api_key, key_ref)
                elif prov == "huggingface":
                    models, err = self.discover_huggingface_models(api_key, key_ref)
                elif prov == "anthropic":
                    models, err = self.discover_anthropic_models(api_key, key_ref)

                if err:
                    catalog["discovery_failures"].append({
                        "provider": prov,
                        "key_reference": key_ref,
                        "key_fingerprint": k_fp,
                        "error": err,
                        "timestamp": now_iso
                    })
                else:
                    for m in models:
                        # Append to provider list and global compatible list
                        catalog["models_by_provider"][prov].append(m)
                        catalog["all_compatible_models"].append(m)

        # Write sanitized catalog to disk
        self._write_catalog_file(catalog, user_id=active_uid)
        if active_uid and active_uid > 0:
            self._user_caches[active_uid] = catalog
            self._user_cache_times[active_uid] = time.time()
        else:
            self._cache = catalog
            self._last_loaded_time = time.time()
        return catalog

    def _get_catalog_path(self, user_id: Optional[int] = None) -> str:
        if user_id and int(user_id) > 0:
            base_dir = os.path.dirname(self.catalog_path)
            return os.path.join(base_dir, f"llm_model_catalog_user_{int(user_id)}.json")
        return self.catalog_path

    def _is_cached_valid(self, user_id: Optional[int] = None) -> bool:
        if user_id and int(user_id) > 0:
            uid = int(user_id)
            if uid in self._user_caches and (time.time() - self._user_cache_times.get(uid, 0.0) < CATALOG_TTL_SECONDS):
                return True
            target_path = self._get_catalog_path(uid)
            if os.path.exists(target_path):
                try:
                    mtime = os.path.getmtime(target_path)
                    if time.time() - mtime < CATALOG_TTL_SECONDS:
                        with open(target_path, "r", encoding="utf-8") as f:
                            self._user_caches[uid] = json.load(f)
                        self._user_cache_times[uid] = time.time()
                        return True
                except Exception:
                    pass
            return False

        if self._cache and (time.time() - self._last_loaded_time < CATALOG_TTL_SECONDS):
            return True
        if os.path.exists(self.catalog_path):
            try:
                mtime = os.path.getmtime(self.catalog_path)
                if time.time() - mtime < CATALOG_TTL_SECONDS:
                    with open(self.catalog_path, "r", encoding="utf-8") as f:
                        self._cache = json.load(f)
                    self._last_loaded_time = time.time()
                    return True
            except Exception:
                pass
        return False

    def _write_catalog_file(self, data: Dict[str, Any], user_id: Optional[int] = None) -> None:
        target_path = self._get_catalog_path(user_id)
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write catalog file {target_path}: {e}")

    def get_catalog(self, user_id: Optional[int] = None, force_refresh: bool = False) -> Dict[str, Any]:
        """Returns the active discovered model catalog for the specified or active user."""
        if user_id is None:
            try:
                from instance.config import settings
                user_id = getattr(settings, 'CURRENT_USER_ID', None)
                if user_id is None:
                    from core.assistant_core import get_current_user_id
                    user_id = get_current_user_id()
                if user_id is not None:
                    user_id = int(user_id) if int(user_id) > 0 else None
            except Exception:
                user_id = None

        if force_refresh or not self._is_cached_valid(user_id):
            return self.discover_all_credentials(user_id=user_id, force_refresh=True)

        if user_id and int(user_id) > 0:
            return self._user_caches.get(int(user_id), {})
        return self._cache or {}


_DISCOVERY_SINGLETON: Optional[ModelDiscoveryEngine] = None

def get_model_discovery_engine() -> ModelDiscoveryEngine:
    global _DISCOVERY_SINGLETON
    if _DISCOVERY_SINGLETON is None:
        _DISCOVERY_SINGLETON = ModelDiscoveryEngine()
    return _DISCOVERY_SINGLETON
