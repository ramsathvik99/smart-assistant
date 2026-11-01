"""
core/model_registry.py
======================
Model Registry & Multi-Model Capability-Based Task Router for Friday / Smart Assistant.

Provides:
1. Dynamic model catalog integration (from core/model_discovery.py).
2. Capability-based model scoring and selection across:
   - general_conversation (conversational, interactive follow-up)
   - complex_reasoning (planning, analysis, deep logic)
   - code_generation (programming, shell commands, SQL, script creation)
   - code_debugging (code review, bug fixing, lint correction)
   - summarization (extraction, briefings, concise overviews)
   - long_context (documents > 32k tokens, large codebase analysis)
   - structured_output (JSON, tool calling, intent/parameter extraction)
   - vision (image understanding, screenshots, visual documents)
3. Model-level and key-level failure tracking:
   - Isolates model failure (404 / unsupported) from key failure (401 / 429 quota).
   - Distinguishes exhausted account credits (does not retry other models on same dead key).
4. Automatic local Ollama model candidate participation and failover.
"""

from __future__ import annotations

import os
import sys
import time
import logging
from typing import Dict, List, Any, Optional, Tuple, Set

logger = logging.getLogger("ModelRegistry")

# Supported Task Categories
TASK_CATEGORIES = {
    "general_conversation": "Real-time conversation, dialogue turns, voice responses, greetings",
    "complex_reasoning": "Multi-step reasoning, goal planning, architectural decisions",
    "code_generation": "Code synthesis, Python/JS/SQL/shell generation, implementation",
    "code_debugging": "Code review, syntax/runtime error fixing, diagnostics",
    "summarization": "Text summarization, information extraction, meeting digests",
    "long_context": "Large documents (>32k tokens), multi-file context analysis",
    "structured_output": "Strict JSON output, function calling, tool use, schema conformity",
    "vision": "Image recognition, screenshots, multimodal diagrams",
}


class ModelCandidate:
    """Represents an active discovered model candidate ready for routing."""

    def __init__(self, data: Dict[str, Any]):
        self.provider: str = data.get("provider", "")
        self.id: str = data.get("id", "")
        self.display_name: str = data.get("display_name", self.id)
        self.key_fingerprint: str = data.get("key_fingerprint", "")
        self.credential_reference: str = data.get("credential_reference", "")
        self.api_compatibility: str = data.get("api_compatibility", "")
        self.status: str = data.get("status", "available")
        self.input_modalities: List[str] = data.get("input_modalities", ["text"])
        self.output_modalities: List[str] = data.get("output_modalities", ["text"])
        self.context_window: int = int(data.get("context_window", 8192))
        self.max_output_tokens: int = int(data.get("max_output_tokens", 4096))
        self.capabilities: Set[str] = set(data.get("capabilities", []))
        self.is_preview: bool = bool(data.get("is_preview", False))
        self.is_deprecated: bool = bool(data.get("is_deprecated", False))

    @property
    def model_tag(self) -> str:
        return f"{self.provider}:{self.id}"

    @property
    def key_tag(self) -> str:
        return f"{self.provider}_key_{self.key_fingerprint}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "id": self.id,
            "display_name": self.display_name,
            "key_fingerprint": self.key_fingerprint,
            "credential_reference": self.credential_reference,
            "api_compatibility": self.api_compatibility,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "capabilities": sorted(list(self.capabilities)),
            "is_preview": self.is_preview,
        }


class ModelRegistry:
    """
    Central registry maintaining active models and intelligent task-to-model selection.
    """

    def __init__(self):
        self._models: Dict[str, ModelCandidate] = {}
        self._models_by_provider: Dict[str, List[ModelCandidate]] = {}
        self._last_refresh_time: float = 0.0
        self.refresh()

    def refresh(self, force: bool = False, user_id: Optional[int] = None):
        """Refreshes active models from the model discovery catalog."""
        try:
            from core.model_discovery import get_model_discovery_engine
            engine = get_model_discovery_engine()
            catalog = engine.get_catalog(user_id=user_id, force_refresh=force)
            all_mods = catalog.get("all_compatible_models", [])

            new_models: Dict[str, ModelCandidate] = {}
            by_prov: Dict[str, List[ModelCandidate]] = {}

            for item in all_mods:
                cand = ModelCandidate(item)
                tag = f"{cand.provider}:{cand.id}:{cand.key_fingerprint}"
                new_models[tag] = cand
                by_prov.setdefault(cand.provider, []).append(cand)

            # Register local Ollama model candidate when daemon is reachable
            try:
                from core.llm_health import is_ollama_reachable
                from instance.config import settings as _cfg
                ollama_base = getattr(_cfg, "OLLAMA_API_BASE", "http://127.0.0.1:11434")
                if is_ollama_reachable(ollama_base):
                    ollama_mod_name = getattr(_cfg, "OLLAMA_MODEL", "llama3.2:latest")
                    discovered_models = [ollama_mod_name]
                    try:
                        import requests
                        for probe_url in (ollama_base, "http://127.0.0.1:11434"):
                            r = requests.get(f"{probe_url.rstrip('/')}/api/tags", timeout=1.0)
                            if r.status_code == 200:
                                tags = [m.get("name") for m in r.json().get("models", []) if m.get("name")]
                                if tags:
                                    discovered_models = list(dict.fromkeys([ollama_mod_name] + tags))
                                    break
                    except Exception:
                        pass

                    for mod_name in discovered_models:
                        capabilities = [
                            "general_conversation",
                            "code_generation",
                            "code_debugging",
                            "summarization",
                            "complex_reasoning",
                        ]
                        if any(x in mod_name.lower() for x in ["3.2", "mini", "1b", "3b", "flash"]):
                            capabilities.append("fast_inference")

                        ollama_cand = ModelCandidate({
                            "provider": "ollama",
                            "id": mod_name,
                            "display_name": f"Local Ollama ({mod_name})",
                            "key_fingerprint": "local",
                            "credential_reference": "local:ollama",
                            "api_compatibility": "ollama",
                            "status": "available",
                            "input_modalities": ["text"],
                            "output_modalities": ["text"],
                            "context_window": 8192,
                            "max_output_tokens": 4096,
                            "capabilities": capabilities,
                            "is_preview": False,
                            "is_deprecated": False,
                        })
                        o_tag = f"ollama:{mod_name}:local"
                        new_models[o_tag] = ollama_cand
                        by_prov.setdefault("ollama", []).append(ollama_cand)
            except Exception as _oe:
                logger.debug("Could not register local Ollama candidate: %s", _oe)

            self._models = new_models
            self._models_by_provider = by_prov
            self._last_refresh_time = time.time()
        except Exception as e:
            logger.error(f"Error loading model registry: {e}")

    def list_models(self, provider: Optional[str] = None) -> List[ModelCandidate]:
        """Lists all registered models, optionally filtered by provider."""
        if provider:
            return self._models_by_provider.get(provider.lower().strip(), [])
        return list(self._models.values())

    def get_models_for_key(self, provider: str, key_fingerprint: str) -> List[ModelCandidate]:
        """Returns all models discovered for a specific key fingerprint."""
        prov = provider.lower().strip()
        candidates = self._models_by_provider.get(prov, [])
        return [c for c in candidates if c.key_fingerprint == key_fingerprint]

    # ─────────────────────────────────────────────────────────────────────────
    # TASK-BASED MODEL RANKING & ROUTING
    # ─────────────────────────────────────────────────────────────────────────

    def get_best_models_for_task(
        self,
        task_type: str,
        unavailable_models: Optional[Set[str]] = None,
        unavailable_keys: Optional[Set[str]] = None,
        unavailable_providers: Optional[Set[str]] = None,
        preferred_provider: Optional[str] = None,
        limit: int = 8
    ) -> List[Tuple[ModelCandidate, float]]:
        """
        Ranks and returns the most suitable models for a specific task.
        Excludes models/keys/providers in active cooldown.
        Returns List of (ModelCandidate, suitability_score).
        """
        un_mods = unavailable_models or set()
        un_keys = unavailable_keys or set()
        un_provs = unavailable_providers or set()

        # Map colloquial / pipeline task types to canonical categories
        canonical_task = self._normalize_task_type(task_type)

        scored: List[Tuple[ModelCandidate, float]] = []

        for cand in self._models.values():
            # 1. Exclusion filters
            if cand.provider in un_provs:
                continue
            if cand.model_tag in un_mods:
                continue
            if cand.key_tag in un_keys:
                continue
            if cand.is_deprecated:
                continue

            # 2. Score candidate against task requirements
            score = self._compute_task_score(cand, canonical_task, preferred_provider)
            if score > 0.0:
                scored.append((cand, score))

        # Sort descending by score
        scored.sort(key=lambda x: -x[1])
        return scored[:limit]

    def _normalize_task_type(self, raw_type: str) -> str:
        """Normalizes diverse task descriptors to canonical task categories."""
        if not raw_type:
            return "general_conversation"
        t = raw_type.lower().strip()

        if any(w in t for w in ["code", "programming", "python", "script", "sql", "bash"]):
            if any(w in t for w in ["debug", "review", "lint", "fix", "error"]):
                return "code_debugging"
            return "code_generation"
        if any(w in t for w in ["reason", "plan", "complex", "logic", "architecture", "math"]):
            return "complex_reasoning"
        if any(w in t for w in ["summary", "summarize", "digest", "briefing", "extract"]):
            return "summarization"
        if any(w in t for w in ["document", "long_context", "large_file", "report", "paper", "book"]):
            return "long_context"
        if any(w in t for w in ["json", "schema", "tool", "function", "structured", "classification", "intent"]):
            return "structured_output"
        if any(w in t for w in ["image", "vision", "screenshot", "diagram", "photo", "multimodal"]):
            return "vision"

        return "general_conversation"

    def _compute_task_score(self, cand: ModelCandidate, task: str, preferred_provider: Optional[str] = None) -> float:
        """
        Computes suitability score (0.0 to 100.0) based on model strengths,
        context size, latency characteristics, and provider preference.
        """
        score = 50.0  # Base eligibility score

        # Preferred provider bonus
        if preferred_provider and cand.provider == preferred_provider.lower().strip():
            score += 15.0

        m_id_low = cand.id.lower()

        # ── CATEGORY-SPECIFIC SCORING ─────────────────────────────────────────

        if task == "general_conversation":
            # Fast inference, natural dialogue, moderate context
            if "fast_inference" in cand.capabilities:
                score += 20.0
            if cand.provider == "groq":
                score += 15.0  # Groq ultra-low latency advantage for real-time conversation
            elif "flash" in m_id_low or "mini" in m_id_low:
                score += 12.0
            if "complex_reasoning" in cand.capabilities:
                score += 5.0

        elif task == "complex_reasoning":
            # Deep logic, frontier models, high capacity
            if "complex_reasoning" in cand.capabilities:
                score += 25.0
            if any(x in m_id_low for x in ["deepseek-reasoner", "gemini-2.5-pro", "gpt-4o", "gpt-5", "o1", "o3", "120b"]):
                score += 20.0
            if cand.context_window >= 128000:
                score += 5.0

        elif task == "code_generation":
            # Code synthesis, Python/JS mastery
            if "code_generation" in cand.capabilities:
                score += 25.0
            if any(x in m_id_low for x in ["deepseek", "qwen", "gpt-4o", "gemini-2.5-pro", "codex", "nemotron"]):
                score += 20.0
            if "structured_json" in cand.capabilities:
                score += 5.0

        elif task == "code_debugging":
            # Precise error attribution, rigorous analysis
            if "code_debugging" in cand.capabilities or "code_generation" in cand.capabilities:
                score += 25.0
            if any(x in m_id_low for x in ["deepseek", "gpt-4o", "gemini-2.5-pro", "o1"]):
                score += 20.0

        elif task == "summarization":
            # Fast comprehension, good context window
            if cand.context_window >= 32768:
                score += 15.0
            if "fast_inference" in cand.capabilities:
                score += 15.0
            if cand.provider in ("gemini", "groq", "openai"):
                score += 10.0

        elif task == "long_context":
            # Requires massive token limit (> 100k)
            if cand.context_window >= 1000000:  # Gemini 1M+, DeepSeek 1M+
                score += 35.0
            elif cand.context_window >= 128000:  # Groq Qwen 131k, GPT-4o 128k
                score += 20.0
            else:
                score -= 30.0  # Penalty for small context models on long documents

        elif task == "structured_output":
            # JSON and tool-calling fidelity
            if "structured_json" in cand.capabilities:
                score += 25.0
            if "tool_calling" in cand.capabilities:
                score += 15.0
            if any(x in m_id_low for x in ["gpt-4o", "gpt-4.1", "gemini-2.5-flash", "qwen", "deepseek"]):
                score += 10.0

        elif task == "vision":
            # Multimodal inputs required
            if "vision" in cand.capabilities or "image" in cand.input_modalities:
                score += 40.0
            else:
                return 0.0  # Ineligible for vision tasks if no image modality

        # Slight discount for unverified experimental previews
        if cand.is_preview and not any(x in m_id_low for x in ["gemini-3.8", "gpt-5"]):
            score -= 3.0

        return max(1.0, min(100.0, score))


_REGISTRY_SINGLETON: Optional[ModelRegistry] = None

def get_model_registry() -> ModelRegistry:
    global _REGISTRY_SINGLETON
    if _REGISTRY_SINGLETON is None:
        _REGISTRY_SINGLETON = ModelRegistry()
    return _REGISTRY_SINGLETON
