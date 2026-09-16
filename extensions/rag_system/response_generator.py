# extensions/rag_system/response_generator.py
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

    def generate(self, query, intent, data):
        """Final response generator using LLM as a reasoning layer."""
        
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

        # Build structured factual context
        truth_context = self._format_truth_context(data)
        has_ground_truth = bool(truth_context.strip())

        # Base personality — uses per-user configured assistant name; never hardcodes "NOVA"
        try:
            from instance.config import settings as _cfg
            _asst_name = _cfg.get_assistant_name()
        except Exception:
            _asst_name = None

        if _asst_name:
            base_personality = (
                f"You are {_asst_name}, a highly intelligent, professional, and JARVIS-like AI assistant.\n"
                "Maintain a calm, efficient, confident, and slightly formal tone.\n"
            )
        else:
            base_personality = (
                "You are a highly intelligent, professional, and JARVIS-like AI assistant.\n"
                "Maintain a calm, efficient, confident, and slightly formal tone.\n"
            )

        # Intent-specific guidance
        if intent in ["dynamic_fact_query", "real_time_info", "web_search"]:
            if has_ground_truth:
                intent_instructions = (
                    "CRITICAL GROUNDING REQUIREMENT:\n"
                    "The provided GROUND TRUTH EVIDENCE contains verified, real-time web search results retrieved specifically for this query.\n"
                    "- You MUST answer the user's question accurately using this retrieved information (check DIRECT ANSWER / AI OVERVIEW, ANSWER BOX, KNOWLEDGE GRAPH, and SEARCH RESULTS).\n"
                    "- Base your factual statements strictly on the retrieved ground truth evidence.\n"
                    "- Answer directly, concisely, and factually.\n"
                    "- Do NOT rely on outdated pre-training knowledge when fresh search evidence is provided."
                )
            else:
                intent_instructions = (
                    "The user asked a factual query, but real-time search retrieval returned no verified results.\n"
                    "- Answer using your general knowledge to the best of your ability.\n"
                    "- Do NOT claim that you searched the web or cite non-existent sources.\n"
                    "- If the query strictly requires live information that you do not possess, truthfully acknowledge that current live data is unavailable."
                )
        elif intent == "fallback":
            intent_instructions = (
                "The user asked a query that normally requires live search or retrieval, but the retrieval service was unavailable.\n"
                "- Answer truthfully to the best of your general knowledge.\n"
                "- Do NOT state 'According to search results' or fabricate retrieved evidence.\n"
                "- Be concise and direct."
            )
        elif intent == "current_time_query":
            intent_instructions = (
                "PRIORITY: The provided GROUND TRUTH EVIDENCE contains the exact current date, time, and year from the system clock.\n"
                "State the time/date/year directly and precisely based on this data. Do not guess."
            )
        elif intent == "memory_storage":
            intent_instructions = (
                "The user just shared a personal fact which has been successfully saved to their memory.\n"
                "Confirm that you have recorded it in your signature efficient tone."
            )
        elif intent in ["memory_management", "memory_retrieval"]:
            intent_instructions = (
                "The user is asking about their saved memories or preferences.\n"
                "Use the provided GROUND TRUTH EVIDENCE to answer their personal memory question accurately."
            )
        elif intent == "general_knowledge":
            intent_instructions = (
                "Answer the user's question directly and informatively using your broad knowledge base.\n"
                "Be concise, clear, and professional."
            )
        else:
            intent_instructions = (
                f"Use the GROUND TRUTH EVIDENCE regarding {intent.replace('_', ' ')} to answer.\n"
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
            response = self.llm.get_completion(prompt=query, system_prompt=full_system_prompt)
            return response
        except Exception as e:
            print(f"[RAG GENERATOR ERROR] {e}")
            return "I apologize, but I encountered an error while formulating my response."
