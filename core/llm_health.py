"""
core/llm_health.py
==================
Proactive LLM Provider Health Probing, Cooldown Management, and Latency Ordering.

Responsibilities:
1. At startup (background thread), run cheap health probes against configured providers.
2. Mark dead providers unavailable immediately (30-minute cooldown) when:
   - Python package missing (e.g. anthropic)
   - Authentication rejected (HTTP 401 / 403)
   - Account balance exhausted (HTTP 402 / billing errors)
   - Endpoint unreachable
3. Persist health state with reason, timestamp, and user action to data/llm_provider_health.json.
4. Order healthy providers by measured latency (fastest first), placing rate-limited providers last.
5. Probe local Ollama and include it as last-resort fallback if reachable.
6. Print one clear startup log with actionable user instructions.
"""

import os
import sys
import json
import time
import logging
import threading
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("LLMHealth")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HEALTH_FILE_PATH = os.path.join(PROJECT_ROOT, "data", "llm_provider_health.json")
FATAL_COOLDOWN_SECONDS = int(os.getenv("LLM_FATAL_COOLDOWN_SECONDS", "1800"))  # 30 mins
RATE_LIMIT_COOLDOWN_SECONDS = int(os.getenv("LLM_RATE_LIMIT_COOLDOWN_SECONDS", "60"))  # 60s default

_PROVIDER_LATENCIES: Dict[str, List[float]] = {}
_PROVIDER_STATUS: Dict[str, Dict[str, Any]] = {}
_HEALTH_LOCK = threading.Lock()
_PROBE_STARTED = False
_OLLAMA_REACHABLE = False


def get_health_file_data() -> Dict[str, Any]:
    """Load raw health cache from file."""
    if not os.path.exists(HEALTH_FILE_PATH):
        return {"providers": {}, "keys": {}, "models": {}, "metadata": {}}
    try:
        with open(HEALTH_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        logger.debug(f"[LLM HEALTH] Error reading health file: {e}")
    return {"providers": {}, "keys": {}, "models": {}, "metadata": {}}


def save_health_file_data(data: Dict[str, Any]) -> None:
    """Save health cache atomically to file."""
    try:
        os.makedirs(os.path.dirname(HEALTH_FILE_PATH), exist_ok=True)
        temp_path = f"{HEALTH_FILE_PATH}.tmp.{os.getpid()}"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, HEALTH_FILE_PATH)
    except Exception as e:
        logger.debug(f"[LLM HEALTH] Error saving health file: {e}")


def mark_provider_unhealthy(
    provider: str,
    reason: str,
    user_action: str,
    cooldown_seconds: int = FATAL_COOLDOWN_SECONDS,
    key_tags: Optional[List[str]] = None,
) -> None:
    """Mark a provider unavailable across in-memory cooldown sets and disk."""
    p = str(provider).strip().lower()
    now = time.time()
    expiry = now + cooldown_seconds

    with _HEALTH_LOCK:
        _PROVIDER_STATUS[p] = {
            "status": "unavailable",
            "reason": reason,
            "user_action": user_action,
            "expiry": expiry,
            "timestamp": now,
        }

    # Update in-memory LLMEngine cooldown sets if imported
    try:
        from extensions.llm_engine import _UNAVAILABLE_PROVIDERS, _UNAVAILABLE_KEYS
        _UNAVAILABLE_PROVIDERS.add(p, cooldown=cooldown_seconds)
        if key_tags:
            for kt in key_tags:
                _UNAVAILABLE_KEYS.add(kt, cooldown=cooldown_seconds)
    except Exception:
        pass

    # Persist to disk
    try:
        data = get_health_file_data()
        prov_dict = data.setdefault("providers", {})
        prov_dict[p] = {
            "expiry": expiry,
            "reason": reason,
            "user_action": user_action,
            "timestamp": now,
        }
        if key_tags:
            keys_dict = data.setdefault("keys", {})
            for kt in key_tags:
                keys_dict[kt] = {
                    "expiry": expiry,
                    "reason": reason,
                    "timestamp": now,
                }
        save_health_file_data(data)
    except Exception as e:
        logger.debug(f"[LLM HEALTH] Failed persisting unhealthy status for {p}: {e}")


def mark_provider_healthy(provider: str, latency_s: Optional[float] = None) -> None:
    """Mark a provider healthy and clear cooldowns."""
    p = str(provider).strip().lower()
    now = time.time()

    with _HEALTH_LOCK:
        _PROVIDER_STATUS[p] = {
            "status": "healthy",
            "reason": "Probe succeeded",
            "user_action": "None",
            "timestamp": now,
        }
        if latency_s is not None and latency_s > 0:
            lats = _PROVIDER_LATENCIES.setdefault(p, [])
            lats.append(float(latency_s))
            if len(lats) > 10:
                lats.pop(0)

    try:
        from extensions.llm_engine import _UNAVAILABLE_PROVIDERS
        _UNAVAILABLE_PROVIDERS.discard(p)
    except Exception:
        pass

    try:
        data = get_health_file_data()
        prov_dict = data.setdefault("providers", {})
        if p in prov_dict:
            prov_dict.pop(p, None)
            save_health_file_data(data)
    except Exception:
        pass


def clear_health_cache() -> None:
    """Clear in-memory and persistent health data."""
    global _PROBE_STARTED
    with _HEALTH_LOCK:
        _PROVIDER_STATUS.clear()
        _PROVIDER_LATENCIES.clear()
        _PROBE_STARTED = False
    try:
        save_health_file_data({"providers": {}, "keys": {}, "models": {}, "metadata": {}})
    except Exception:
        pass


def record_provider_latency(provider: str, latency_s: float) -> None:
    """Record observed latency for an LLM provider call."""
    if latency_s <= 0:
        return
    p = str(provider).strip().lower()
    with _HEALTH_LOCK:
        lats = _PROVIDER_LATENCIES.setdefault(p, [])
        lats.append(float(latency_s))
        if len(lats) > 10:
            lats.pop(0)


def get_average_latency(provider: str) -> float:
    """Return moving average latency for a provider, or default estimate."""
    p = str(provider).strip().lower()
    defaults = {
        "groq": 0.45,
        "gemini": 1.10,
        "openai": 1.40,
        "deepseek": 1.80,
        "anthropic": 2.20,
        "huggingface": 2.50,
        "ollama": 4.50,
    }
    with _HEALTH_LOCK:
        lats = _PROVIDER_LATENCIES.get(p)
        if lats:
            return sum(lats) / len(lats)
    return defaults.get(p, 2.0)


def is_ollama_reachable(base_url: str = "http://127.0.0.1:11434") -> bool:
    """Check if local Ollama daemon is reachable.
    Tries base_url and 127.0.0.1:11434 / localhost:11434 fallbacks to prevent Windows IPv6 timeouts.
    """
    global _OLLAMA_REACHABLE
    import requests
    candidate_urls = [base_url]
    if "localhost" in base_url:
        candidate_urls.append(base_url.replace("localhost", "127.0.0.1"))
    elif "127.0.0.1" in base_url:
        candidate_urls.append(base_url.replace("127.0.0.1", "localhost"))

    for u in candidate_urls:
        try:
            url = f"{u.rstrip('/')}/api/tags"
            resp = requests.get(url, timeout=1.5)
            if resp.status_code == 200:
                _OLLAMA_REACHABLE = True
                return True
        except Exception:
            continue

    _OLLAMA_REACHABLE = False
    return False


def probe_single_provider(provider: str, keys: List[str]) -> Tuple[bool, str, str]:
    """
    Run one very cheap probe for a provider.
    Returns: (is_healthy, reason, user_action)
    """
    import requests
    p = str(provider).strip().lower()

    if p == "anthropic":
        try:
            import importlib
            importlib.import_module("anthropic")
        except ModuleNotFoundError:
            return False, "No module named 'anthropic'", "pip install anthropic"
        except Exception as e:
            return False, f"Anthropic import error: {e}", "pip install anthropic"

        if not keys:
            return False, "No API key configured", "Add Anthropic API key"
        try:
            url = "https://api.anthropic.com/v1/models"
            resp = requests.get(
                url,
                headers={"x-api-key": keys[0], "anthropic-version": "2023-06-01"},
                timeout=3.0,
            )
            if resp.status_code in (401, 403):
                return False, f"HTTP {resp.status_code} authentication failed", "Anthropic key invalid"
            if resp.status_code == 402:
                return False, "HTTP 402 insufficient balance", "Anthropic balance is empty"
            if resp.status_code == 200:
                return True, "Healthy", ""
            return False, f"HTTP {resp.status_code}", "Check Anthropic account"
        except Exception as e:
            return False, f"Connection error: {e}", "Check Anthropic connection"

    elif p == "huggingface":
        if not keys:
            return False, "No API key configured", "Add HuggingFace API key"
        try:
            url = "https://router.huggingface.co/v1/models"
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {keys[0]}"},
                timeout=3.0,
            )
            if resp.status_code in (401, 403):
                return False, f"HTTP {resp.status_code} authentication failed", "HuggingFace key invalid"
            if resp.status_code == 402:
                return False, "HTTP 402 insufficient balance", "HuggingFace balance is empty"
            if resp.status_code == 200:
                return True, "Healthy", ""
            return False, f"HTTP {resp.status_code}", "Check HuggingFace status"
        except Exception as e:
            return False, f"Connection error: {e}", "Check HuggingFace connection"


    elif p == "groq":
        if not keys:
            return False, "No API key configured", "Add Groq API key"
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {keys[0]}", "Content-Type": "application/json"},
                json={"model": "qwen/qwen3.8-27b", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                timeout=3.0,
            )
            if resp.status_code in (401, 403):
                return False, f"HTTP {resp.status_code} authentication failed", "Groq key invalid"
            if resp.status_code == 429:
                retry_hdr = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
                cd = RATE_LIMIT_COOLDOWN_SECONDS
                if retry_hdr:
                    try:
                        cd = max(2, min(int(float(retry_hdr)) + 1, 60))
                    except Exception:
                        cd = RATE_LIMIT_COOLDOWN_SECONDS
                return False, f"HTTP 429 rate limited (retry-after={cd}s)", f"Groq rate limited (in cooldown {cd}s)"
            if resp.status_code == 200:
                return True, "Healthy", ""
            return False, f"HTTP {resp.status_code}", "Check Groq account"
        except Exception as e:
            return False, f"Connection error: {e}", "Check Groq connection"

    elif p == "openai":
        if not keys:
            return False, "No API key configured", "Add OpenAI API key"
        try:
            url = "https://api.openai.com/v1/chat/completions"
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {keys[0]}", "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                timeout=3.0,
            )
            if resp.status_code in (401, 403):
                return False, f"HTTP {resp.status_code} authentication failed", "OpenAI key invalid"
            if resp.status_code == 429 or resp.status_code == 402 or "quota" in resp.text.lower() or "billing" in resp.text.lower() or "credits" in resp.text.lower():
                return False, "Quota/credits exhausted", "OpenAI quota exhausted"
            if resp.status_code == 200:
                return True, "Healthy", ""
            return False, f"HTTP {resp.status_code}", "Check OpenAI account"
        except Exception as e:
            return False, f"Connection error: {e}", "Check OpenAI connection"

    elif p == "deepseek":
        if not keys:
            return False, "No API key configured", "Add DeepSeek API key"
        try:
            url = "https://api.deepseek.com/chat/completions"
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {keys[0]}", "Content-Type": "application/json"},
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                timeout=3.0,
            )
            if resp.status_code in (401, 403):
                return False, f"HTTP {resp.status_code} authentication failed", "DeepSeek key invalid"
            if resp.status_code == 402 or "insufficient" in resp.text.lower():
                return False, "HTTP 402 insufficient balance", "DeepSeek balance is empty"
            if resp.status_code == 200:
                return True, "Healthy", ""
            return False, f"HTTP {resp.status_code}", "Check DeepSeek account"
        except Exception as e:
            return False, f"Connection error: {e}", "Check DeepSeek connection"

    elif p == "gemini":
        if not keys:
            return False, "No API key configured", "Add Gemini API key"
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
            resp = requests.post(
                url,
                headers={"x-goog-api-key": keys[0], "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": "hi"}]}], "generationConfig": {"maxOutputTokens": 1}},
                timeout=3.0,
            )
            if resp.status_code in (400, 401, 403):
                return False, f"HTTP {resp.status_code} authentication failed", "Gemini key invalid"
            if resp.status_code == 429 or "quota" in resp.text.lower() or "resource_exhausted" in resp.text.lower():
                return False, "Gemini quota exhausted", "Check Gemini quota"
            if resp.status_code == 200:
                return True, "Healthy", ""
            return False, f"HTTP {resp.status_code}", "Check Gemini status"
        except Exception as e:
            return False, f"Connection error: {e}", "Check Gemini connection"

    return False, "Unknown provider", "Configure provider"


def run_startup_probes(llm_engine: Optional[Any] = None) -> Dict[str, Any]:
    """Execute startup health probes and log the summary line."""
    from instance.config import settings as CONFIG

    # Read existing disk cache to respect active cooldowns
    disk_data = get_health_file_data()
    disk_provs = disk_data.get("providers", {})
    now = time.time()

    providers_to_probe = ["groq", "gemini", "openai", "deepseek", "huggingface", "anthropic"]
    active: List[str] = []
    skipped: List[str] = []

    # Check Ollama
    ollama_ok = is_ollama_reachable(CONFIG.get("OLLAMA_API_BASE", "http://localhost:11434"))
    if ollama_ok:
        active.append("ollama (local)")

    for prov in providers_to_probe:
        # Check if already in persistent cooldown
        cached_info = disk_provs.get(prov, {})
        cached_exp = cached_info.get("expiry", 0) if isinstance(cached_info, dict) else (cached_info if isinstance(cached_info, (int, float)) else 0)
        cached_reason = cached_info.get("reason", "cooldown") if isinstance(cached_info, dict) else "cooldown"
        cached_action = cached_info.get("user_action", cached_reason) if isinstance(cached_info, dict) else cached_reason

        if cached_exp > now:
            skipped.append(f"{prov} ({cached_action})")
            try:
                from extensions.llm_engine import _UNAVAILABLE_PROVIDERS
                _UNAVAILABLE_PROVIDERS.add(prov, cooldown=int(cached_exp - now))
            except Exception:
                pass
            continue

        # Get configured keys
        keys: List[str] = []
        if llm_engine and hasattr(llm_engine, f"{prov}_keys"):
            keys = getattr(llm_engine, f"{prov}_keys")
        else:
            raw_k = CONFIG.get(f"{prov.upper()}_API_KEYS", [CONFIG.get(f"{prov.upper()}_API_KEY", "")])
            keys = [k.strip() for k in raw_k if isinstance(k, str) and k.strip()]

        if not keys and prov != "anthropic":
            # Unconfigured
            continue

        t0 = time.time()
        healthy, reason, user_action = probe_single_provider(prov, keys)
        elapsed = time.time() - t0

        if healthy:
            mark_provider_healthy(prov, latency_s=elapsed)
            active.append(f"{prov} ({elapsed*1000:.0f}ms)")
        else:
            if "rate limit" in reason.lower() or "429" in reason:
                import re
                m_cd = re.search(r'retry-after=(\d+)', reason)
                cd = int(m_cd.group(1)) if m_cd else RATE_LIMIT_COOLDOWN_SECONDS
            else:
                cd = FATAL_COOLDOWN_SECONDS
            mark_provider_unhealthy(prov, reason=reason, user_action=user_action, cooldown_seconds=cd)
            skipped.append(f"{prov} ({user_action})")

    summary_active = ", ".join(active) if active else "none"
    summary_skipped = "; ".join(skipped) if skipped else "none"
    log_line = f"[LLM HEALTH] Active providers: [{summary_active}] | Skipped: [{summary_skipped}]"
    print(log_line)
    logger.info(log_line)

    return {"active": active, "skipped": skipped}


def start_background_probes(llm_engine: Optional[Any] = None) -> None:
    """Start the startup probe asynchronously in a daemon thread."""
    global _PROBE_STARTED
    with _HEALTH_LOCK:
        if _PROBE_STARTED:
            return
        _PROBE_STARTED = True

    t = threading.Thread(
        target=run_startup_probes,
        args=(llm_engine,),
        daemon=True,
        name="llm-health-probe"
    )
    t.start()


def order_provider_chain(chain: List[str], primary: Optional[str] = None) -> List[str]:
    """
    Orders the candidate provider chain:
    1. Healthy providers ordered by measured latency (fastest first).
    2. Rate-limited providers (e.g. Groq in 429 cooldown) placed last.
    3. Excludes permanently unavailable/dead providers.
    4. Includes reachable local Ollama at the end of the chain as fallback.
    """
    from extensions.llm_engine import _UNAVAILABLE_PROVIDERS

    healthy: List[str] = []
    cooldown_providers: List[str] = []

    for p in chain:
        p_low = p.lower().strip()
        if p_low in _UNAVAILABLE_PROVIDERS:
            cooldown_providers.append(p_low)
        else:
            healthy.append(p_low)

    # Sort healthy providers by measured latency
    healthy.sort(key=lambda x: get_average_latency(x))

    # Keep primary first if it is healthy
    if primary and primary in healthy:
        healthy = [primary] + [p for p in healthy if p != primary]

    # Include Ollama as local provider if reachable
    if (_OLLAMA_REACHABLE or is_ollama_reachable()) and "ollama" not in healthy and "ollama" not in cooldown_providers:
        healthy.append("ollama")

    # Combine: healthy first, only fallback to cooldown providers if NO healthy provider is available
    ordered = healthy if healthy else cooldown_providers
    return ordered
