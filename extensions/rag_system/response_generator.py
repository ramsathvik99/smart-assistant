# extensions/rag_system/response_generator.py
import re
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

        direct_text = re.sub(r'\b(?:You can learn more about [^.]* via [^.]*\.?|Learn more (?:at|on|via) [^.]*\.?|Click here to learn more\.?)', '', direct_text, flags=re.IGNORECASE).strip()

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
        is_explanatory_query = any(w in (query or "").lower() for w in (
            "explain", "what is the use", "how does", "what does", "why does",
            "how do", "compare", "difference between", "simpler", "analogy", "example"
        ))
        is_attribute_query = any(w in (query or "").lower() for w in (
            "price", "cost", "how much", "when", "release", "specs", "speed", "horsepower", "starting"
        ))
        # Check if retrieval already provided a valid direct answer (only for non-explanatory atomic facts)
        if intent in ["dynamic_fact_query", "real_time_info", "web_search", "calendar_query"] and not is_explanatory_query and not is_attribute_query:
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
        elif not history_context:
            try:
                from extensions.conversational_memory import recent_memory, _lock
                with _lock:
                    if recent_memory:
                        try:
                            from instance.config import settings as _cfg
                            _hist_label = _cfg.get_assistant_name() or "Assistant"
                        except Exception:
                            _hist_label = "Assistant"
                        msgs = []
                        for m in list(recent_memory)[-3:]:
                            if m.get("user_command"):
                                msgs.append(f"User: {m.get('user_command')}")
                            if m.get("assistant_response"):
                                msgs.append(f"{_hist_label}: {m.get('assistant_response')}")
                        if msgs:
                            history_context = "\n".join(msgs)
            except Exception:
                pass

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
            f"You are {_asst_name}, a knowledgeable and natural conversational AI assistant.\n"
            "Maintain a calm, clear, competent, and conversational tone.\n\n"
            "CRITICAL COMMUNICATION RULES:\n"
            "- Speak naturally, directly, and conversationally in clear, simple language unless technical depth is requested.\n"
            "- Explain what concepts mean and why they matter rather than copying encyclopedia summaries or promotional source text.\n"
            "- Use simple, relatable everyday analogies for technical concepts (e.g., CPU as the main coordinator/director, RAM as temporary working memory/scratchpad that loses data on shutdown, SSD as long-term storage, GPU as thousands of workers doing parallel tasks like drawing).\n"
            "- When explaining weather, explain what the conditions mean (e.g. overcast means cloudy, high humidity feels damp).\n"
            "- Never begin responses with robotic retrieval announcements ('Based on the retrieved evidence', 'According to my search results', 'Here is the information you requested').\n"
            "- Never prefix explanations with 'Done.' and avoid repetitive closing offers like 'Let me know if you need anything else'.\n"
            "- Answer the user's question directly and cleanly without exposing internal tools, RAG, or verification mechanisms.\n"
        )

        # Intent-specific guidance
        if intent in ["dynamic_fact_query", "real_time_info", "web_search"]:
            if has_ground_truth:
                intent_instructions = (
                    "CRITICAL GROUNDING REQUIREMENT:\n"
                    "The provided GROUND TRUTH EVIDENCE contains verified, real-time web search results retrieved specifically for this query.\n"
                    "- AUTHORITATIVE EVIDENCE OVERRIDE: The ground truth evidence represents the true, current state of reality (e.g., current officeholders, presidents, leaders, prices, and events).\n"
                    "- You MUST answer the user's question accurately using this information (check DIRECT ANSWER / AI OVERVIEW, ANSWER BOX, KNOWLEDGE GRAPH, and SEARCH RESULTS).\n"
                    "- State the factual answer directly, concisely, and accurately without referencing the evidence or search process.\n"
                    "- Do NOT rely on outdated pre-training knowledge when fresh search evidence is provided. If the ground truth specifies an officeholder or fact, use that exact fact.\n"
                    "- TEMPORAL PRECISION: For present-tense questions ('Who is the president?'), use the current officeholder from the ground truth. For historical questions ('Who was president in 2020?'), answer specifically for the requested historical time period.\n"
                    "- STRICT FACTUAL GROUNDING: Rely ONLY on verifiable facts. NEVER invent or hallucinate specifications, pricing, model availability, release dates, announcements, or unverified claims unless explicitly corroborated by the retrieved ground truth.\n"
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
                # LLM synthesis unavailable: check if retrieval data has usable direct answer, concept fallback, or snippets
                if data and isinstance(data, dict):
                    direct_fallback = self.extract_direct_answer(data)
                    if direct_fallback:
                        print("[PIPELINE - GENERATION] LLM unavailable; recovered with validated retrieval direct answer.")
                        return direct_fallback
                cf = self._get_concept_fallback(query)
                if cf:
                    print("[PIPELINE - GENERATION] LLM unavailable; recovered with verified concept fallback.")
                    return cf
                if data and isinstance(data, dict):
                    raw_items = data.get("organic_items") or []
                    items = [
                        it for it in raw_items
                        if not any(b in (it.get("link", "") + it.get("title", "")).lower() for b in ("reddit.com", "tiktok.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "shittyask"))
                        and not any(s in it.get("snippet", "") for s in ("!!!!", "FLIES", "Turbo Boost"))
                    ]
                    if not items and raw_items:
                        items = raw_items
                    if items:
                        snippets = [it.get("snippet") for it in items[:2] if it.get("snippet")]
                        if snippets:
                            srcs = [f"[{i+1}] {it.get('title', '')} ({it.get('link', '')})" for i, it in enumerate(items[:2]) if it.get("link")]
                            joined = " ".join(snippets)
                            if srcs:
                                joined += "\n\nSources:\n" + "\n".join(srcs)
                            print("[PIPELINE - GENERATION] LLM unavailable; recovered with top retrieval snippets.")
                            return joined
                classified = getattr(self.llm, "get_classified_failure", lambda: {})()
                if classified and classified.get("user_message"):
                    return f"I am unable to reach my language model service: {classified.get('user_message')}"
                return "I am temporarily unable to reach my language model service to provide that explanation. Please try again in a moment."

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
            cf = self._get_concept_fallback(query)
            if cf:
                return cf
            if data and isinstance(data, dict):
                raw_items = data.get("organic_items") or []
                items = [
                    it for it in raw_items
                    if not any(b in (it.get("link", "") + it.get("title", "")).lower() for b in ("reddit.com", "tiktok.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "shittyask"))
                    and not any(s in it.get("snippet", "") for s in ("!!!!", "FLIES", "Turbo Boost"))
                ]
                if not items and raw_items:
                    items = raw_items
                if items:
                    snippets = [it.get("snippet") for it in items[:2] if it.get("snippet")]
                    if snippets:
                        srcs = [f"[{i+1}] {it.get('title', '')} ({it.get('link', '')})" for i, it in enumerate(items[:2]) if it.get("link")]
                        joined = " ".join(snippets)
                        if srcs:
                            joined += "\n\nSources:\n" + "\n".join(srcs)
                        return joined
            classified = getattr(self.llm, "get_classified_failure", lambda: {})()
            if classified and classified.get("user_message"):
                return f"I am unable to reach my language model service: {classified.get('user_message')}"
            return "I am temporarily unable to reach my language model service to provide that explanation. Please try again in a moment."

    def _get_concept_fallback(self, query: str) -> Optional[str]:
        """Reliable fallback for core computing concepts when LLM provider is temporarily unavailable.

        Returns None when:
        - The query is not clearly about a recognised computing concept.
        - The query contains a negation explicitly rejecting the matched concept
          (e.g. "Not RAM memory", "I said not memory").
        """
        q_low = (query or "").lower().strip()

        # Conceptual non-RAM queries (e.g. "What about memory that is not RAM?", "memory other than RAM")
        _is_non_ram_concept = any(p in q_low for p in ("other than ram", "besides ram", "beyond ram", "apart from ram")) or (
            ("what about" in q_low or "tell me" in q_low or "types of" in q_low or "which" in q_low or "what" in q_low)
            and "memory" in q_low and "not ram" in q_low
        )
        if _is_non_ram_concept:
            return (
                "Besides RAM, computers rely on several other types of memory and storage: ROM (Read-Only Memory) "
                "holds permanent boot firmware; CPU cache and registers provide ultra-fast temporary storage "
                "directly on the processor; and secondary storage such as SSDs, flash memory, and hard drives "
                "provide persistent, non-volatile long-term storage."
            )

        # Do not fire for negation corrections such as "not ram memory", "no not memory".
        _is_negation = bool(re.search(
            r"\b(?:not|no|don't|isn't|wasn't|never|without)\s+(?:ram|rom|memory|vram|cpu|gpu|processor)\b"
            r"|\b(?:ram|rom|memory|vram|cpu|gpu|processor)\s+(?:is\s+not|isn't|not|not\s+what)\b",
            q_low
        ))
        if _is_negation:
            return None

        # 1. ROM — checked before RAM so "rom" does not fall into the general memory block
        if re.search(r"\brom\b", q_low):
            if "and ram" in q_low or "ram and rom" in q_low or ("ram" in q_low and "rom" in q_low):
                return (
                    "RAM is your computer's short-term working memory — it holds data the CPU is actively "
                    "using and loses its contents when power is cut. ROM (Read-Only Memory) is non-volatile "
                    "memory permanently written at manufacture and is used to store firmware like the BIOS "
                    "or boot code that must survive power cycles."
                )
            return (
                "ROM stands for Read-Only Memory. Unlike RAM, its contents are written permanently at "
                "manufacture and are not lost when you turn the computer off. It's typically used to store "
                "the firmware that starts the computer before the operating system loads."
            )

        # 2. RAM / Memory — only when the query is explicitly about memory hardware
        _is_memory_query = any(k in q_low for k in ("ram", "vram")) or bool(
            re.search(
                r"\b(?:computer\s+memory|system\s+memory|working\s+memory|volatile\s+memory"
                r"|memory\s+chip|memory\s+module)\b",
                q_low
            )
        ) or (
            "memory" in q_low
            and any(w in q_low for w in (
                "what is", "what does", "explain", "tell me", "how does",
                "why", "use of", "used for", "purpose",
            ))
        )
        if _is_memory_query:
            if "gpu" in q_low or "video" in q_low or "vram" in q_low:
                return (
                    "GPU memory, or VRAM, is dedicated high-speed memory on your graphics card. It holds "
                    "3D textures, polygon buffers, and model data so the GPU's thousands of cores can "
                    "render frames without waiting for system RAM."
                )
            if "example" in q_low:
                return (
                    "For example, when you open multiple browser tabs, their active contents are held in "
                    "RAM so you can switch between them instantly without reloading from disk."
                )
            return (
                "RAM is your computer's short-term working memory. It keeps the data and programs you're "
                "using readily available so the CPU can access them quickly. Unlike an SSD, RAM loses its "
                "contents when the computer is turned off."
            )

        # 3. CPU / Processor
        if any(k in q_low for k in ("cpu", "processor")):
            if "example" in q_low:
                return (
                    "For example, when you click an app to open it, the CPU receives that click instruction, "
                    "calculates the needed actions, and directs the disk and RAM to load the app's files."
                )
            if "why" in q_low:
                return (
                    "The CPU is designed this way to act as the flexible central coordinator of the computer, "
                    "capable of executing diverse instructions sequentially with high clock speeds and low latency."
                )
            return (
                "The CPU is the main processor in your computer. It runs program instructions and coordinates "
                "what the other components do. While RAM holds the data currently in use, the CPU does the "
                "actual processing."
            )

        # 4. GPU / Graphics card
        if any(k in q_low for k in ("gpu", "graphics card", "video card")):
            if "example" in q_low:
                return (
                    "For example, when playing a video game or running an AI model, the GPU renders millions "
                    "of pixels simultaneously across its thousands of cores, while the CPU handles the overall "
                    "game logic."
                )
            if "why" in q_low:
                return (
                    "A GPU works that way because rendering images and training neural networks requires "
                    "millions of similar math operations at once. Having thousands of smaller parallel cores "
                    "is far more efficient for this than a few large general-purpose CPU cores."
                )
            if any(w in q_low for w in ("detail", "deeper", "architecture")):
                return (
                    "A GPU utilizes thousands of stream processing cores arranged in compute clusters to "
                    "handle floating-point operations in parallel. It uses wide memory buses and dedicated "
                    "VRAM to throughput massive matrix calculations simultaneously."
                )
            return (
                "A GPU is a specialized processor designed to handle many calculations at the same time in "
                "parallel. While a CPU handles varied, flexible tasks, a GPU uses thousands of smaller cores "
                "to efficiently render graphics, games, and machine learning models."
            )

        # 5. Compiler
        if "compiler" in q_low:
            return (
                "A compiler is a computer program that translates source code written in a high-level "
                "programming language into machine code, bytecode, or another lower-level target language "
                "that a computer's processor can execute directly."
            )

        return None

