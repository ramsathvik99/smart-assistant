# extensions/rag_system/response_generator.py
from typing import Optional
from extensions.llm_engine import LLMEngine

class RAGResponseGenerator:
    def __init__(self):
        self.llm = LLMEngine()

    def _format_truth_context(self, data: dict) -> str:
        """Format retrieved search and factual data into clean, structured context for the LLM."""
        if not data or not isinstance(data, dict):
            return ""

        sections = []

        # 1. AI Overview (direct synthesis from Google / search engine)
        ai_overview = data.get("ai_overview")
        if ai_overview:
            if isinstance(ai_overview, list):
                ai_text = "\n".join(f"- {s}" for s in ai_overview if s)
            else:
                ai_text = str(ai_overview)
            if ai_text.strip():
                sections.append(f"=== DIRECT ANSWER / AI OVERVIEW ===\n{ai_text.strip()}")

        # 2. Answer Box
        answer_box = data.get("answer_box")
        if answer_box and isinstance(answer_box, dict):
            ans_parts = []
            for k in ["title", "answer", "snippet", "result"]:
                if answer_box.get(k):
                    ans_parts.append(f"{k.capitalize()}: {answer_box[k]}")
            if ans_parts:
                sections.append(f"=== ANSWER BOX ===\n" + "\n".join(ans_parts))

        # 3. Knowledge Graph
        kg = data.get("knowledge_graph")
        if kg and isinstance(kg, dict):
            kg_parts = []
            for k in ["title", "type", "description"]:
                if kg.get(k):
                    kg_parts.append(f"{k.capitalize()}: {kg[k]}")
            if kg_parts:
                sections.append(f"=== KNOWLEDGE GRAPH ===\n" + "\n".join(kg_parts))

        # 4. Organic Search Results with Sources
        organic_items = data.get("organic_items")
        if organic_items and isinstance(organic_items, list):
            item_strs = []
            for idx, item in enumerate(organic_items[:5], 1):
                title = item.get("title", "Untitled")
                snippet = item.get("snippet", "")
                link = item.get("link", "")
                item_strs.append(f"[{idx}] {title}\n    Snippet: {snippet}\n    Source: {link}")
            if item_strs:
                sections.append("=== SEARCH RESULTS ===\n" + "\n\n".join(item_strs))
        elif data.get("organic_results"):
            # Fallback if only snippet strings are available
            snippets = data["organic_results"][:5]
            item_strs = [f"[{idx}] {s}" for idx, s in enumerate(snippets, 1) if s]
            if item_strs:
                sections.append("=== SEARCH RESULTS ===\n" + "\n".join(item_strs))

        # 5. Current Time / Date
        if "current_time" in data:
            sections.append(
                f"=== CURRENT SYSTEM TIME & DATE ===\n"
                f"Time: {data.get('current_time')}\n"
                f"Date: {data.get('current_date')}\n"
                f"Year: {data.get('current_year')}"
            )

        # 6. Location
        if "city" in data or "region" in data:
            sections.append(
                f"=== DETECTED LOCATION ===\n"
                f"City: {data.get('city')}, Region: {data.get('region')}, Country: {data.get('country')}"
            )

        # 7. Memory / Saved Facts
        if "saved_fact" in data:
            sections.append(f"=== SAVED MEMORY FACT ===\n{data['saved_fact']}")
        elif "memory_value" in data:
            sections.append(f"=== STORED MEMORY ===\n{data.get('memory_key')}: {data['memory_value']}")
        elif "all_memory" in data:
            sections.append(f"=== USER MEMORIES ===\n{data['all_memory']}")

        # 8. Calendar
        if "holidays" in data:
            sections.append(f"=== CALENDAR HOLIDAYS ===\n{data['holidays']}")
        if "personal_events" in data:
            sections.append(f"=== PERSONAL EVENTS ===\n{data['personal_events']}")
        if "speech_response" in data and data.get("speech_response"):
            sections.append(f"=== CALENDAR INTELLIGENCE ===\n{data['speech_response']}")

        # Fallback for any other custom keys not explicitly handled above
        handled_keys = {
            "ai_overview", "answer_box", "knowledge_graph", "organic_items", "organic_results",
            "organic_titles", "current_time", "current_date", "current_year", "raw_datetime",
            "city", "region", "country", "timezone", "saved_fact", "memory_key", "memory_value",
            "all_memory", "holidays", "recent_history", "status", "error", "_search_slot", "provider"
        }
        extra_keys = [k for k in data.keys() if k not in handled_keys]
        if extra_keys:
            extra_dict = {k: data[k] for k in extra_keys}
            sections.append(f"=== ADDITIONAL CONTEXT ===\n{extra_dict}")

        return "\n\n".join(sections)

    def extract_direct_answer(self, data: dict) -> Optional[str]:
        """
        Extract clean, validated direct retrieval answer with citations if available.
        Does NOT require LLM synthesis when provider supplied a validated direct answer.
        """
        if not data or not isinstance(data, dict):
            return None

        direct_text = ""
        # 1. Explicit direct_answer field
        if data.get("direct_answer") and isinstance(data["direct_answer"], str) and len(data["direct_answer"].strip()) >= 15:
            direct_text = data["direct_answer"].strip()

        # 2. Answer Box
        if not direct_text:
            ans_box = data.get("answer_box")
            if ans_box and isinstance(ans_box, dict):
                cand = ans_box.get("answer") or ans_box.get("result") or ans_box.get("snippet") or ""
                if len(str(cand).strip()) >= 15:
                    direct_text = str(cand).strip()

        # 3. AI Overview
        if not direct_text:
            ai_ov = data.get("ai_overview")
            if isinstance(ai_ov, list) and ai_ov:
                cand = " ".join(s.strip() for s in ai_ov if s and len(s.strip()) > 15)
                if len(cand) >= 15:
                    direct_text = cand
            elif isinstance(ai_ov, str) and len(ai_ov.strip()) >= 15:
                direct_text = ai_ov.strip()

        # 4. Knowledge Graph
        if not direct_text:
            kg = data.get("knowledge_graph")
            if kg and isinstance(kg, dict):
                cand = kg.get("description") or ""
                if len(str(cand).strip()) >= 15:
                    direct_text = str(cand).strip()

        if not direct_text:
            return None

        # Format clean answer with citations / source links from organic_items
        sources = []
        for item in (data.get("organic_items") or [])[:3]:
            title = item.get("title", "").strip()
            link = item.get("link", "").strip()
            if title and link:
                sources.append(f"[{len(sources) + 1}] {title} ({link})")
            elif link:
                sources.append(f"[{len(sources) + 1}] {link}")

        res = direct_text
        if sources:
            res += "\n\nSources:\n" + "\n".join(sources)
        return res

    def generate(self, query, intent, data, user_id=None):
        """Final response generator using LLM as a reasoning layer."""
        # Check if retrieval already provided a valid direct answer
        if intent in ["dynamic_fact_query", "real_time_info", "web_search", "calendar_query"]:
            direct_ans = self.extract_direct_answer(data)
            if direct_ans:
                print(f"[PIPELINE - GENERATION] Valid direct answer available from retrieval ({data.get('provider', 'retriever')}). Using direct retrieval answer.")
                return direct_ans
        
        # Format history
        history_context = ""
        if data and isinstance(data, dict) and "recent_history" in data:
            # Resolve assistant name dynamically for history labels
            try:
                from instance.config import settings as _cfg
                _hist_label = _cfg.get_assistant_name() or "Assistant"
            except Exception:
                _hist_label = "Assistant"
            msgs = []
            for msg in data["recent_history"]:
                role = "User" if msg.get("role") == "user" else _hist_label
                msgs.append(f"{role}: {msg.get('content')}")
            history_context = "\n".join(msgs)

        # Build structured factual context with canonical runtime temporal anchor
        truth_context = self._format_truth_context(data)
        try:
            from core.temporal_context import format_temporal_prompt_block
            temporal_block = format_temporal_prompt_block()
            truth_context = f"{temporal_block}\n\n{truth_context}" if truth_context.strip() else temporal_block
        except Exception:
            pass
        has_ground_truth = bool(truth_context.strip())

        # Base personality — uses per-user configured assistant name; never hardcodes "NOVA"
        try:
            from instance.config import settings as _cfg
            _asst_name = _cfg.get_assistant_name() or "Trevon"
        except Exception:
            _asst_name = "Trevon"

        base_personality = (
            f"You are {_asst_name}, a highly intelligent, professional AI assistant developed by Trevon Labs.\n"
            "Maintain a calm, efficient, confident, and professional tone.\n\n"
            "CRITICAL COMMUNICATION RULES:\n"
            "- Speak naturally, directly, and conversationally like a knowledgeable assistant (or ChatGPT).\n"
            "- Internal context, memory, RAG results, search results, databases, and tools are invisible implementation details.\n"
            "- NEVER begin responses with retrieval meta-commentary such as 'Based on the retrieved evidence', 'Based on available information', 'According to my search results', 'Based on your references', 'From your history', 'According to my context', etc.\n"
            "- Answer the user's question directly without explaining how you retrieved or verified the answer.\n"
        )

        # Intent-specific guidance
        if intent in ["dynamic_fact_query", "real_time_info", "web_search"]:
            if has_ground_truth:
                intent_instructions = (
                    "CRITICAL GROUNDING REQUIREMENT:\n"
                    "The provided GROUND TRUTH EVIDENCE contains verified, real-time web search results retrieved specifically for this query.\n"
                    "- You MUST answer the user's question accurately using this information (check DIRECT ANSWER / AI OVERVIEW, ANSWER BOX, KNOWLEDGE GRAPH, and SEARCH RESULTS).\n"
                    "- State the factual answer directly, concisely, and accurately without referencing the evidence or search process.\n"
                    "- Do NOT rely on outdated pre-training knowledge when fresh search evidence is provided.\n"
                    "- STRICT FACTUAL GROUNDING: Rely ONLY on verifiable facts. NEVER invent or hallucinate specifications, pricing, model availability, release dates, announcements, or unverified claims (such as flying capabilities, rocket thrusters, pre-order guarantees, or unverified acceleration figures) unless explicitly corroborated by the retrieved ground truth.\n"
                    "- If the provided search results or general knowledge do not verify a specific claim, explicitly state that limitation or lack of verification rather than speculating or asserting it as fact.\n"
                    "- Separate retrieved facts from unverified claims or speculation.\n"
                    "- Do NOT treat prior assistant answers in history as independent evidence for unverified claims."
                )
            else:
                intent_instructions = (
                    "The user asked a factual query, but real-time search retrieval returned no verified results.\n"
                    "- Answer using your general knowledge to the best of your ability.\n"
                    "- Do NOT claim that you searched the web or cite non-existent sources.\n"
                    "- NEVER invent or hallucinate specifications, pricing, model availability, release dates, or speculative features (e.g. flying capabilities or thrusters). State honestly if details are unconfirmed.\n"
                    "- If the query strictly requires live information that you do not possess, truthfully acknowledge that current live data is unavailable."
                )
        elif intent == "fallback":
            intent_instructions = (
                "The user asked a query that normally requires live search or retrieval, but the retrieval service was unavailable.\n"
                "- Answer truthfully to the best of your general knowledge.\n"
                "- Do NOT state 'According to search results' or fabricate retrieved evidence or unverified specifications.\n"
                "- Be concise and direct."
            )
        elif intent == "current_time_query":
            intent_instructions = (
                "PRIORITY: The provided GROUND TRUTH EVIDENCE contains the exact current date, time, and year from the system clock.\n"
                "State the time/date/year directly and precisely. Do not announce sources or data."
            )
        elif intent == "memory_storage":
            intent_instructions = (
                "The user just shared a personal fact which has been successfully saved to their memory.\n"
                "Confirm that you have recorded it in your signature efficient tone."
            )
        elif intent in ["memory_management", "memory_retrieval"]:
            intent_instructions = (
                "The user is asking about their saved memories or preferences.\n"
                "Use the provided GROUND TRUTH EVIDENCE to answer their personal memory question accurately and directly.\n"
                "Do NOT say 'According to my memory', 'From your history', or 'Based on stored records'."
            )
        elif intent == "general_knowledge":
            intent_instructions = (
                "Answer the user's question directly and informatively using your broad knowledge base.\n"
                "Be concise, clear, and professional."
            )
        else:
            intent_instructions = (
                f"Use the GROUND TRUTH EVIDENCE regarding {intent.replace('_', ' ')} to answer directly.\n"
                "If data is missing or if you are unsure, do not hallucinate; state that you don't have that information."
            )

        # Code generation format instructions (for when code is requested)
        code_instructions = (
            "\n\nIf the user is asking you to write or generate code, follow these rules:\n"
            "If multiple files are required, respond in this format:\n"
            "FILE: filename.ext\n"
            "```language\n"
            "code\n"
            "```\n"
            "Otherwise return a single code block."
        )

        # Assemble full system prompt
        full_system_prompt = (
            f"{base_personality}\n"
            f"{intent_instructions}\n"
            f"{code_instructions}\n\n"
            f"GROUND TRUTH EVIDENCE:\n{truth_context if has_ground_truth else 'No live search results retrieved.'}\n\n"
            f"RECENT CONVERSATION HISTORY:\n{history_context if history_context else 'No prior history.'}"
        )

        try:
            print(f"[PIPELINE - GENERATION] Calling LLM with intent: {intent} (has_ground_truth={has_ground_truth})")
            response = self.llm.get_completion(prompt=query, system_prompt=full_system_prompt, user_id=user_id)
            if not response or not isinstance(response, str) or not response.strip():
                # LLM synthesis unavailable: check if retrieval data has usable direct answer or snippets
                if data and isinstance(data, dict):
                    direct_fallback = self.extract_direct_answer(data)
                    if direct_fallback:
                        print("[PIPELINE - GENERATION] LLM unavailable; recovered with validated retrieval direct answer.")
                        return direct_fallback
                    items = data.get("organic_items") or []
                    if items:
                        snippets = [it.get("snippet") for it in items[:2] if it.get("snippet")]
                        if snippets:
                            srcs = [f"[{i+1}] {it.get('title', '')} ({it.get('link', '')})" for i, it in enumerate(items[:2]) if it.get("link")]
                            joined = " ".join(snippets)
                            if srcs:
                                joined += "\n\nSources:\n" + "\n".join(srcs)
                            print("[PIPELINE - GENERATION] LLM unavailable; recovered with top retrieval snippets.")
                classified = getattr(self.llm, "get_classified_failure", lambda: {})()
                if classified and classified.get("user_message"):
                    return f"I am unable to reach my language model service: {classified.get('user_message')}"
                return "I am temporarily unable to reach my language model services. The language model service is currently unavailable."

            response = response.strip()
            if data and isinstance(data, dict):
                organic_items = data.get("organic_items") or []
                if organic_items and "sources:" not in response.lower() and "http" not in response:
                    src_links = []
                    for idx, item in enumerate(organic_items[:3], 1):
                        title = item.get("title", "").strip()
                        link = item.get("link", "").strip()
                        if title and link:
                            src_links.append(f"[{idx}] {title} ({link})")
                        elif link:
                            src_links.append(f"[{idx}] {link}")
                    if src_links:
                        response += "\n\nSources:\n" + "\n".join(src_links)
            return response
        except Exception as e:
            print(f"[RAG GENERATOR ERROR] {e}")
            if data and isinstance(data, dict):
                direct_fallback = self.extract_direct_answer(data)
                if direct_fallback:
                    return direct_fallback
            classified = getattr(self.llm, "get_classified_failure", lambda: {})()
            if classified and classified.get("user_message"):
                return f"I am unable to reach my language model service: {classified.get('user_message')}"
            return "I am temporarily unable to reach my language model services. The knowledge service is currently unavailable."
