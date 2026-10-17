# extensions/rag_system/retriever.py
"""
RAG Retriever — fetches data for each retrieval intent.

SerpAPI web search changes (repair):
- Reads the SERPAPI_KEYS multi-key array from config (mirrors LLM provider pattern).
- Per-key retry loop: tries each key in order; skips to the next on:
    timeout, connection error, HTTP 429 (rate-limit), HTTP 5xx (server error),
    HTTP 401/403 (auth failure → marks key exhausted for this session),
    or a SerpAPI-level error field in the JSON body.
- Per-attempt timeout is configurable (SERPAPI_TIMEOUT, default 10 s).
  Shorter than the original 15 s so failures are detected quickly and the
  next key is tried within a reasonable wall-clock budget.
- When all keys are exhausted the retriever returns an error dict so the
  RAGSystem can route to the LLM fallback honestly.
- Never logs key values — only slot numbers.
"""

import os
import time
import requests
import json as _json

from instance.config import settings as CONFIG
from modules.calendar_manager.calendar_controller import CalendarController
from legacy.memory_manager import get_chat_history, get_or_create_user

# Keys that are permanently rate-limited or auth-failed in this session.
# Using a set so we never retry a dead key within the same process lifetime.
_exhausted_serpapi_slots: set = set()
_exhausted_tavily_slots: set = set()
_search_provider_cooldowns: dict = {}


def is_search_provider_healthy(provider: str) -> bool:
    """Check if search provider is currently healthy (not in cooldown)."""
    p = provider.lower()
    exp = _search_provider_cooldowns.get(p)
    if not exp:
        return True
    if time.time() > exp:
        _search_provider_cooldowns.pop(p, None)
        return True
    return False


def mark_search_provider_unhealthy(provider: str, cooldown: float = 300.0) -> None:
    """Mark search provider unhealthy with a short cooldown period."""
    p = provider.lower()
    _search_provider_cooldowns[p] = time.time() + cooldown
    print(f"[RAG RETRIEVER] Marked provider '{provider}' unhealthy (cooldown {cooldown:.1f}s).")



class RAGRetriever:
    def __init__(self):
        # Read keys from the centralised CONFIG
        self.serpapi_keys: list = CONFIG.get("SERPAPI_KEYS", []) or []
        if not self.serpapi_keys:
            bare = os.getenv("SERPAPI_KEY", "")
            if bare:
                self.serpapi_keys = [bare.strip()]

        self.tavily_keys: list = CONFIG.get("TAVILY_API_KEYS", []) or []
        if not self.tavily_keys:
            bare_tavily = os.getenv("TAVILY_API_KEY", "")
            if bare_tavily:
                self.tavily_keys = [bare_tavily.strip()]

        self.search_provider: str = CONFIG.get("SEARCH_PROVIDER", os.getenv("SEARCH_PROVIDER", "serpapi")).lower()
        self.serpapi_timeout: int = CONFIG.get("SERPAPI_TIMEOUT", 10)
        self.calendar_controller = CalendarController()

    # ------------------------------------------------------------------
    def _get_user_search_keys(self, provider: str, user_id=None) -> list:
        resolved_uid = user_id
        if resolved_uid is None:
            try:
                from instance.config import settings
                resolved_uid = getattr(settings, 'CURRENT_USER_ID', None)
            except Exception:
                resolved_uid = None

        if resolved_uid:
            try:
                from core.credential_manager import get_credential_manager
                ukey = get_credential_manager().get_credential(resolved_uid, provider)
                if ukey and str(ukey).strip():
                    return [str(ukey).strip()]
            except Exception:
                pass
            return []

        import sys
        allow_dev = os.getenv("ALLOW_DEV_FALLBACK", "").strip().lower() in ("1", "true")
        if os.getenv("APP_ENV", "").lower() == "production" or getattr(sys, "frozen", False) or not allow_dev:
            return []
        if provider == "serpapi":
            return self.serpapi_keys
        elif provider == "tavily":
            return self.tavily_keys
        return []

    # ------------------------------------------------------------------
    # Public dispatch
    # ------------------------------------------------------------------

    def retrieve(self, intent: str, query: str, user_id=None):
        """Main retrieval dispatcher — routes by intent name."""
        print(f"[RAG RETRIEVER] Retrieving for intent: {intent}")

        if intent == "calendar_query":
            return self._retrieve_calendar(query, user_id=user_id)
        elif intent == "current_time_query":
            return self._retrieve_current_time(query)
        elif intent == "dynamic_fact_query":
            return self._retrieve_dynamic_fact(query, user_id=user_id)
        elif intent == "real_time_info":
            return self._retrieve_web_search(query, user_id=user_id)
        elif intent == "location_query":
            return self._retrieve_location(query)
        elif intent == "memory_management":
            return self._retrieve_memory(query, user_id=user_id)
        elif intent == "history_query":
            return self._retrieve_history(query, user_id=user_id)
        elif intent == "recommendation":
            return self._retrieve_recommendation(query)
        elif intent == "email_command":
            return self._retrieve_email_context(query)
        return None

    # ------------------------------------------------------------------
    # Current time
    # ------------------------------------------------------------------

    def _retrieve_current_time(self, query: str):
        """Fetch current date, time, and year from the local clock."""
        try:
            import datetime
            now = datetime.datetime.now()
            data = {
                "current_time": now.strftime("%I:%M %p"),
                "current_date": now.strftime("%A, %B %d, %Y"),
                "current_year": str(now.year),
                "raw_datetime": now.isoformat(),
            }
            print(f"[RAG RETRIEVER] Current time context: {data}")
            return data
        except Exception as exc:
            print(f"[RAG ERROR] Time retrieval failed: {exc}")
            return {"error": f"Time retrieval failed: {exc}"}

    # ------------------------------------------------------------------
    # Dynamic fact → web search
    # ------------------------------------------------------------------

    def _retrieve_dynamic_fact(self, query: str, user_id=None):
        """Route dynamic fact queries to the web search path."""
        print(f"[RAG RETRIEVER] Routing dynamic fact query to web search: '{query}'")
        return self._retrieve_web_search(query, user_id=user_id)

    # ------------------------------------------------------------------
    # Web search with multi-key and provider failover
    # ------------------------------------------------------------------

    def _retrieve_web_search(self, query: str, user_id=None):
        """
        Fetch live data with provider health checks, fast-skip cooldowns, and failover:
          1. Healthy provider used immediately.
          2. Unhealthy provider (timed out / errored recently) fast-skipped to fallback.
          3. Multiple key slots per provider.
          4. Returns normalized search documents/snippets with sources and direct answers.
          5. Never logs secrets.
        """
        providers_order = ["serpapi", "tavily"] if self.search_provider == "serpapi" else ["tavily", "serpapi"]

        serp_keys = self._get_user_search_keys("serpapi", user_id)
        tav_keys = self._get_user_search_keys("tavily", user_id)

        last_error = "no search provider succeeded"

        # Pass 1: Try only healthy providers
        for provider in providers_order:
            if not is_search_provider_healthy(provider):
                print(f"[RAG RETRIEVER] Provider '{provider}' is in cooldown (unhealthy). Fast-skipping to healthy fallback.")
                continue

            if provider == "serpapi":
                result = self._search_serpapi(query, keys=serp_keys)
            elif provider == "tavily":
                result = self._search_tavily(query, keys=tav_keys)
            else:
                result = None

            if result and result.get("status") == "success" and not result.get("error"):
                return result
            elif result:
                last_error = result.get("error") or "provider returned unsuccessful result"

        # Pass 2: If all providers were skipped (all in cooldown), try fallback provider as last resort
        print(f"[RAG RETRIEVER] All configured providers were in cooldown or failed. Attempting fallback.")
        fallback_prov = "tavily" if self.search_provider == "serpapi" else "serpapi"
        if fallback_prov == "tavily":
            result = self._search_tavily(query, keys=tav_keys)
        else:
            result = self._search_serpapi(query, keys=serp_keys)

        if result and result.get("status") == "success" and not result.get("error"):
            return result
        elif result:
            last_error = result.get("error") or "fallback provider returned unsuccessful result"

        print(f"[RAG ERROR] All search providers failed. Last error: {last_error}")
        return {
            "status": "error",
            "provider": self.search_provider,
            "direct_answer": None,
            "ai_overview": [],
            "answer_box": {},
            "knowledge_graph": {},
            "organic_results": [],
            "organic_titles": [],
            "organic_items": [],
            "error": f"All search providers failed. Last: {last_error}"
        }

    def _search_serpapi(self, query: str, keys: list = None):
        """SerpAPI search with multi-key failover and rich content extraction."""
        target_keys = keys if keys is not None else self.serpapi_keys
        if not target_keys:
            print("[RAG RETRIEVER] SerpAPI: no API keys configured.")
            return {
                "status": "error",
                "provider": "serpapi",
                "error": "SerpAPI keys not configured.",
                "direct_answer": None,
                "ai_overview": [],
                "answer_box": {},
                "knowledge_graph": {},
                "organic_results": [],
                "organic_items": [],
            }

        params_base = {
            "engine": "google",
            "q": query,
        }

        last_error = "SerpAPI failed"

        for slot_idx, api_key in enumerate(target_keys):
            if slot_idx in _exhausted_serpapi_slots:
                print(f"[RAG RETRIEVER] SerpAPI key slot {slot_idx} skipped (previously exhausted).")
                continue

            params = {**params_base, "api_key": api_key}

            try:
                print(
                    f"[RAG RETRIEVER] SerpAPI attempt — slot {slot_idx}, "
                    f"timeout={self.serpapi_timeout}s, query='{query[:80]}'"
                )
                call_timeout = min(self.serpapi_timeout, 4.0)
                response = requests.get(
                    "https://serpapi.com/search",
                    params=params,
                    timeout=(2.0, call_timeout),
                )

                if response.status_code == 429:
                    print(f"[RAG RETRIEVER] SerpAPI slot {slot_idx}: HTTP 429 rate-limited. Trying next key slot.")
                    last_error = f"slot {slot_idx} rate-limited (HTTP 429)"
                    continue

                if response.status_code in (401, 403):
                    print(f"[RAG RETRIEVER] SerpAPI slot {slot_idx}: HTTP {response.status_code} auth failure. Marking slot exhausted.")
                    _exhausted_serpapi_slots.add(slot_idx)
                    last_error = f"slot {slot_idx} auth failure (HTTP {response.status_code})"
                    continue

                if response.status_code >= 500:
                    print(f"[RAG RETRIEVER] SerpAPI slot {slot_idx}: HTTP {response.status_code} server error. Trying next key slot.")
                    last_error = f"slot {slot_idx} server error (HTTP {response.status_code})"
                    continue

                if response.status_code != 200:
                    print(f"[RAG RETRIEVER] SerpAPI slot {slot_idx}: unexpected HTTP {response.status_code}. Trying next key slot.")
                    last_error = f"slot {slot_idx} HTTP {response.status_code}"
                    continue

                try:
                    data = response.json()
                except ValueError as parse_err:
                    print(f"[RAG RETRIEVER] SerpAPI slot {slot_idx}: JSON parse error: {parse_err}. Trying next key slot.")
                    last_error = f"slot {slot_idx} JSON parse error"
                    continue

                if "error" in data:
                    err_msg = str(data["error"])
                    permanent_indicators = (
                        "invalid api key", "api key", "unauthorized",
                        "account", "plan", "exceeded", "upgrade",
                    )
                    is_permanent = any(ind in err_msg.lower() for ind in permanent_indicators)
                    if is_permanent:
                        print(f"[RAG RETRIEVER] SerpAPI slot {slot_idx}: API-level permanent error. Marking slot exhausted. Reason: {err_msg[:80]}")
                        _exhausted_serpapi_slots.add(slot_idx)
                    else:
                        print(f"[RAG RETRIEVER] SerpAPI slot {slot_idx}: API-level transient error. Trying next key slot. Reason: {err_msg[:80]}")
                    last_error = f"slot {slot_idx} API error: {err_msg[:80]}"
                    continue

                # ── Extract rich usable content ──────────────────────────────────
                # 1. AI Overview (modern Google Search direct answer)
                ai_overview_raw = data.get("ai_overview", {})
                ai_snippets = []
                if isinstance(ai_overview_raw, dict):
                    for block in ai_overview_raw.get("text_blocks", []):
                        snip = block.get("snippet", "").strip()
                        if snip:
                            ai_snippets.append(snip)
                        for item in block.get("list", []):
                            item_snip = item.get("snippet", "").strip()
                            if item_snip:
                                ai_snippets.append(item_snip)
                    # Also include references
                    for ref in ai_overview_raw.get("references", []):
                        ref_snip = ref.get("snippet", "").strip()
                        if ref_snip and ref_snip not in ai_snippets:
                            ai_snippets.append(ref_snip)

                # 2. Answer Box
                answer_box = data.get("answer_box", {})

                # 3. Knowledge Graph
                knowledge_graph = data.get("knowledge_graph", {})

                # 4. Organic Results
                organic_items = []
                for r in data.get("organic_results", [])[:6]:
                    title = r.get("title", "").strip()
                    snippet = r.get("snippet", "").strip()
                    link = r.get("link", "").strip()
                    if snippet or title:
                        organic_items.append({
                            "title": title,
                            "snippet": snippet,
                            "link": link
                        })

                organic_snippets = [r["snippet"] for r in organic_items if r["snippet"]]
                organic_titles = [r["title"] for r in organic_items if r["title"]]

                has_usable = (
                    bool(ai_snippets) or
                    bool(answer_box) or
                    bool(knowledge_graph) or
                    len(organic_snippets) > 0
                )

                if not has_usable:
                    print(f"[RAG RETRIEVER] SerpAPI slot {slot_idx}: HTTP 200 but no usable content. Trying next key slot.")
                    last_error = f"slot {slot_idx} returned empty content"
                    continue

                print(
                    f"[RAG RETRIEVER] SerpAPI slot {slot_idx} succeeded. "
                    f"ai_overview={len(ai_snippets)}, answer_box={'yes' if answer_box else 'no'}, "
                    f"knowledge_graph={'yes' if knowledge_graph else 'no'}, organic_results={len(organic_snippets)}"
                )

                direct_ans = ""
                if answer_box and isinstance(answer_box, dict):
                    direct_ans = answer_box.get("answer") or answer_box.get("result") or answer_box.get("snippet") or ""
                if not direct_ans and ai_snippets:
                    direct_ans = ai_snippets[0]
                if not direct_ans and knowledge_graph and isinstance(knowledge_graph, dict):
                    direct_ans = knowledge_graph.get("description", "")

                return {
                    "status": "success",
                    "provider": "serpapi",
                    "ai_overview": ai_snippets,
                    "answer_box": answer_box,
                    "knowledge_graph": knowledge_graph,
                    "organic_results": organic_snippets,
                    "organic_titles": organic_titles,
                    "organic_items": organic_items,
                    "direct_answer": direct_ans,
                    "error": None,
                    "_search_slot": slot_idx,
                }

            except requests.exceptions.Timeout:
                print(f"[RAG RETRIEVER] SerpAPI slot {slot_idx}: timed out after {call_timeout}s. Marking provider in cooldown (300s).")
                mark_search_provider_unhealthy("serpapi", cooldown=300.0)
                return {
                    "status": "timeout",
                    "provider": "serpapi",
                    "error": "SerpAPI timed out; marked unhealthy.",
                    "direct_answer": None,
                    "ai_overview": [],
                    "answer_box": {},
                    "knowledge_graph": {},
                    "organic_results": [],
                    "organic_items": [],
                }

            except requests.exceptions.ConnectionError as conn_err:
                print(f"[RAG RETRIEVER] SerpAPI slot {slot_idx}: connection error ({conn_err}). Marking provider in cooldown (300s).")
                mark_search_provider_unhealthy("serpapi", cooldown=300.0)
                return {
                    "status": "error",
                    "provider": "serpapi",
                    "error": f"SerpAPI connection error: {conn_err}",
                    "direct_answer": None,
                    "ai_overview": [],
                    "answer_box": {},
                    "knowledge_graph": {},
                    "organic_results": [],
                    "organic_items": [],
                }

            except Exception as exc:
                print(f"[RAG RETRIEVER] SerpAPI slot {slot_idx}: unexpected exception: {exc}. Trying next key slot.")
                last_error = f"slot {slot_idx} exception: {exc}"
                continue

        print(f"[RAG RETRIEVER] SerpAPI key slots exhausted. Last error: {last_error}")
        return {
            "status": "error",
            "provider": "serpapi",
            "error": f"SerpAPI failed: {last_error}",
            "direct_answer": None,
            "ai_overview": [],
            "answer_box": {},
            "knowledge_graph": {},
            "organic_results": [],
            "organic_items": [],
        }

    def _search_tavily(self, query: str, keys: list = None):
        """Tavily search provider failover."""
        target_keys = keys if keys is not None else self.tavily_keys
        if not target_keys:
            print("[RAG RETRIEVER] Tavily: no API keys configured.")
            return {
                "status": "error",
                "provider": "tavily",
                "error": "Tavily keys not configured.",
                "direct_answer": None,
                "ai_overview": [],
                "answer_box": {},
                "knowledge_graph": {},
                "organic_results": [],
                "organic_items": [],
            }

        last_error = "Tavily failed"

        for slot_idx, api_key in enumerate(target_keys):
            if slot_idx in _exhausted_tavily_slots:
                print(f"[RAG RETRIEVER] Tavily key slot {slot_idx} skipped (previously exhausted).")
                continue

            try:
                print(f"[RAG RETRIEVER] Attempting search via Tavily slot {slot_idx} for query: '{query[:80]}'")
                payload = {
                    "api_key": api_key,
                    "query": query,
                    "max_results": 5,
                    "include_answer": True,
                }
                response = requests.post(
                    "https://api.tavily.com/search",
                    json=payload,
                    timeout=(4, 10),
                )

                if response.status_code in (401, 403):
                    print(f"[RAG RETRIEVER] Tavily slot {slot_idx}: HTTP {response.status_code} auth failure. Marking slot exhausted.")
                    _exhausted_tavily_slots.add(slot_idx)
                    last_error = f"Tavily slot {slot_idx} auth failure"
                    continue

                if response.status_code == 429:
                    print(f"[RAG RETRIEVER] Tavily slot {slot_idx}: rate limited (HTTP 429). Trying next key slot.")
                    last_error = f"Tavily slot {slot_idx} rate limited"
                    continue

                if response.status_code != 200:
                    print(f"[RAG RETRIEVER] Tavily slot {slot_idx}: HTTP {response.status_code}. Trying next key slot.")
                    last_error = f"Tavily slot {slot_idx} HTTP {response.status_code}"
                    continue

                data = response.json()
                tavily_answer = data.get("answer", "").strip()
                tavily_items = []
                for r in data.get("results", [])[:6]:
                    title = r.get("title", "").strip()
                    content = r.get("content", "").strip()
                    url = r.get("url", "").strip()
                    if content or title:
                        tavily_items.append({
                            "title": title,
                            "snippet": content,
                            "link": url
                        })

                organic_snippets = [r["snippet"] for r in tavily_items if r["snippet"]]
                organic_titles = [r["title"] for r in tavily_items if r["title"]]

                has_usable = bool(tavily_answer) or len(organic_snippets) > 0
                if not has_usable:
                    print(f"[RAG RETRIEVER] Tavily slot {slot_idx}: HTTP 200 but empty results.")
                    last_error = f"Tavily slot {slot_idx} returned empty results"
                    continue

                print(f"[RAG RETRIEVER] Tavily slot {slot_idx} succeeded. results={len(organic_snippets)}, direct_answer={'yes' if tavily_answer else 'no'}")

                return {
                    "status": "success",
                    "provider": "tavily",
                    "ai_overview": [tavily_answer] if tavily_answer else [],
                    "answer_box": {"answer": tavily_answer} if tavily_answer else {},
                    "knowledge_graph": {},
                    "organic_results": organic_snippets,
                    "organic_titles": organic_titles,
                    "organic_items": tavily_items,
                    "direct_answer": tavily_answer,
                    "error": None,
                    "_search_slot": slot_idx,
                }

            except requests.exceptions.Timeout:
                print(f"[RAG RETRIEVER] Tavily slot {slot_idx}: timed out. Marking provider in cooldown (300s).")
                mark_search_provider_unhealthy("tavily", cooldown=300.0)
                last_error = f"Tavily slot {slot_idx} timeout"
                return {
                    "status": "timeout",
                    "provider": "tavily",
                    "error": "Tavily timed out; marked unhealthy.",
                    "direct_answer": None,
                    "ai_overview": [],
                    "answer_box": {},
                    "knowledge_graph": {},
                    "organic_results": [],
                    "organic_items": [],
                }
            except requests.exceptions.ConnectionError as conn_err:
                print(f"[RAG RETRIEVER] Tavily slot {slot_idx}: connection error ({conn_err}). Marking provider in cooldown (300s).")
                mark_search_provider_unhealthy("tavily", cooldown=300.0)
                return {
                    "status": "error",
                    "provider": "tavily",
                    "error": f"Tavily connection error: {conn_err}",
                    "direct_answer": None,
                    "ai_overview": [],
                    "answer_box": {},
                    "knowledge_graph": {},
                    "organic_results": [],
                    "organic_items": [],
                }
            except Exception as exc:
                print(f"[RAG RETRIEVER] Tavily slot {slot_idx}: exception: {exc}")
                last_error = f"Tavily slot {slot_idx} exception: {exc}"
                continue

        return {
            "status": "error",
            "provider": "tavily",
            "error": f"Tavily failed: {last_error}",
            "direct_answer": None,
            "ai_overview": [],
            "answer_box": {},
            "knowledge_graph": {},
            "organic_results": [],
            "organic_items": [],
        }

    # ------------------------------------------------------------------
    # Calendar
    # ------------------------------------------------------------------

    def _retrieve_calendar(self, query: str, user_id=None):
        try:
            resolved_uid = user_id
            if resolved_uid is None:
                try:
                    from instance.config import settings
                    resolved_uid = getattr(settings, 'CURRENT_USER_ID', None)
                except Exception:
                    pass
            res = self.calendar_controller.process_calendar_query(query, user_id=resolved_uid)
            if not isinstance(res, dict):
                return {
                    "status": "error",
                    "provider": "calendar_controller",
                    "error": "Invalid calendar response format",
                    "direct_answer": None,
                    "holidays": [],
                    "personal_events": [],
                    "organic_results": [],
                    "organic_items": [],
                }
            speech_resp = res.get("speech_response") or ""
            return {
                "status": "success" if res.get("success", True) else "error",
                "provider": "calendar_controller",
                "speech_response": speech_resp,
                "direct_answer": speech_resp,
                "holidays": res.get("holidays", []),
                "personal_events": res.get("personal_events", []),
                "calendar_data": res,
                "organic_results": [speech_resp] if speech_resp else [],
                "organic_items": [{"title": "Calendar", "snippet": speech_resp, "link": ""}] if speech_resp else [],
                "error": None if res.get("success", True) else res.get("status", "error"),
            }
        except Exception as exc:
            print(f"[RAG ERROR] Calendar retrieval failed: {exc}")
            return {
                "status": "error",
                "provider": "calendar_controller",
                "error": f"Calendar retrieval failed: {exc}",
                "direct_answer": None,
                "holidays": [],
                "personal_events": [],
                "organic_results": [],
                "organic_items": [],
            }

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------

    def _retrieve_location(self, query: str):
        try:
            print("[RAG RETRIEVER] Fetching location via IP-API...")
            response = requests.get("http://ip-api.com/json/", timeout=5)
            if response.status_code == 200:
                data = response.json()
                res = {
                    "city":     data.get("city"),
                    "region":   data.get("regionName"),
                    "country":  data.get("country"),
                    "timezone": data.get("timezone"),
                }
                print(f"[RAG RETRIEVER] Location: {res['city']}, {res['region']}")
                return res
            print(f"[RAG ERROR] Location API returned status {response.status_code}")
            return {"error": "Could not detect location"}
        except Exception as exc:
            print(f"[RAG ERROR] Location retrieval failed: {exc}")
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def _retrieve_memory(self, query: str, user_id=None):
        effective_uid = user_id or getattr(CONFIG, 'CURRENT_USER_ID', None)
        if not effective_uid:
            print("[RAG ERROR] Memory retrieval: user not authenticated.")
            return {"error": "User not authenticated. Cannot retrieve memory."}

        try:
            from legacy.memory_manager import load_user_memory

            all_memory = load_user_memory(effective_uid)
            available_keys = list(all_memory.keys()) if all_memory else []

            history_data = self._retrieve_history(query, user_id=effective_uid)
            recent_hist = history_data.get("recent_history", []) if isinstance(history_data, dict) else []

            if not available_keys:
                print("[RAG RETRIEVER] No stored user memories found.")
                return {"status": "No memories stored yet.", "recent_history": recent_hist}

            from extensions.llm_engine import LLMEngine
            llm = LLMEngine()
            extract_prompt = (
                f"The user has these stored memory keys: {available_keys}\n"
                f"Which key is the user asking about? Respond with ONLY the key name, nothing else.\n"
                f"If none match, respond with 'NONE'."
            )
            matched_key = (
                llm.get_completion(query, context=extract_prompt)
                .strip()
                .lower()
                .replace(" ", "_")
            )

            if matched_key and matched_key != "none" and matched_key in all_memory:
                val = all_memory[matched_key]
                print(f"[RAG RETRIEVER] Memory matched key: '{matched_key}'")
                return {"memory_key": matched_key, "memory_value": val, "recent_history": recent_hist}

            print("[RAG RETRIEVER] No exact memory key matched; returning all memory.")
            return {"all_memory": all_memory, "status": "No exact key match.", "recent_history": recent_hist}

        except Exception as exc:
            print(f"[RAG ERROR] Memory retrieval exception: {exc}")
            return {"error": f"Memory retrieval failed: {exc}"}

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _retrieve_history(self, query: str, user_id=None):
        effective_uid = user_id or getattr(CONFIG, 'CURRENT_USER_ID', None)
        if not effective_uid:
            print("[RAG RETRIEVER] No active session (no authenticated user).")
            return {"recent_history": [], "status": "No active session."}

        try:
            history = get_chat_history(effective_uid, limit=10)
            print(f"[RAG RETRIEVER] Fetched {len(history)} recent message exchanges.")
            return {"recent_history": history}
        except Exception as exc:
            print(f"[RAG ERROR] History retrieval failed: {exc}")
            return {"error": f"History retrieval failed: {exc}"}

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def _retrieve_recommendation(self, query: str):
        try:
            from skills.recommendation_engine import recommend
            rec_data = recommend(query)
            print("[RAG RETRIEVER] Recommendation engine query executed.")
            return {"recommendation_raw": rec_data}
        except Exception as exc:
            print(f"[RAG ERROR] Recommendation failed: {exc}")
            return {"error": f"Recommendation failed: {exc}"}

    # ------------------------------------------------------------------
    # Email context
    # ------------------------------------------------------------------

    def _retrieve_email_context(self, query: str):
        print("[RAG RETRIEVER] Email context retriever triggered.")
        return {"action": "email_service_active", "provider": "assistant_email"}
