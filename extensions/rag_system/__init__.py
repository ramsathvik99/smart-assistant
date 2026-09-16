# extensions/rag_system/__init__.py
from .router import RAGRouter
from .retriever import RAGRetriever
from .validator import RAGValidator
from .response_generator import RAGResponseGenerator

class RAGSystem:
    def __init__(self):
        self.router = RAGRouter()
        self.retriever = RAGRetriever()
        self.validator = RAGValidator()
        self.generator = RAGResponseGenerator()
        
        # Load configuration settings with fallbacks
        import os
        from instance.config import settings as CONFIG
        self.enable_rag = CONFIG.get("ENABLE_RAG", os.getenv("ENABLE_RAG", "true").lower() in ("true", "1", "yes"))
        self.enable_web_search = CONFIG.get("ENABLE_WEB_SEARCH", os.getenv("ENABLE_WEB_SEARCH", "true").lower() in ("true", "1", "yes"))
        self.enable_retrieval = CONFIG.get("ENABLE_RETRIEVAL", os.getenv("ENABLE_RETRIEVAL", "true").lower() in ("true", "1", "yes"))
        self.enable_live_data = CONFIG.get("ENABLE_LIVE_DATA", os.getenv("ENABLE_LIVE_DATA", "true").lower() in ("true", "1", "yes"))
        self.search_provider = CONFIG.get("SEARCH_PROVIDER", os.getenv("SEARCH_PROVIDER", "serpapi"))
        self.fallback_to_llm = CONFIG.get("FALLBACK_TO_LLM", os.getenv("FALLBACK_TO_LLM", "true").lower() in ("true", "1", "yes"))
        
        print(f"[RAG SYSTEM] Configs: ENABLE_RAG={self.enable_rag}, ENABLE_WEB_SEARCH={self.enable_web_search}, ENABLE_RETRIEVAL={self.enable_retrieval}, ENABLE_LIVE_DATA={self.enable_live_data}, SEARCH_PROVIDER={self.search_provider}, FALLBACK_TO_LLM={self.fallback_to_llm}")

    def process(self, query):
        """
        Main Execution Pipeline: Input -> Intent -> Decision -> Execution -> Response.
        Returns a dictionary: {"intent": str, "response": str, "data": dict}
        """
        print(f"\n==============================================")
        print(f"[PIPELINE - INPUT] Received: {query}")
        
        # Check global RAG/retrieval bypass
        if not self.enable_rag or not self.enable_retrieval:
            print("[RAG SYSTEM] RAG or retrieval disabled globally. Bypassing to direct general generation.")
            try:
                response = self.generator.generate(query, "general_knowledge", None)
                return {
                    "intent": "general_knowledge",
                    "response": response,
                    "data": None,
                    "handled": True
                }
            except Exception as e:
                print(f"[RAG SYSTEM ERROR] Direct general generation failed: {e}")
                return {
                    "intent": "general_knowledge",
                    "response": "I had a bit of trouble formulating a response.",
                    "data": None,
                    "handled": False
                }
                
        # 1. Pipeline: Intent Detection
        routing_data = self.router.route(query)
        core_intent = routing_data.get("core_intent", "chat")
        sub_intent = routing_data.get("sub_intent", "general_knowledge")
        cmd_obj = routing_data.get("command")
        # CRITICAL: Preserve the original unified intent throughout the pipeline to prevent incorrect routing
        original_unified_intent = routing_data.get("unified_intent", "GENERAL_CONVERSATION")
        final_intent = core_intent  # Track final intent separately
        print(f"[PIPELINE - DECISION] Core Intent: '{core_intent}' | Sub Intent: '{sub_intent}' | Original Unified Intent: '{original_unified_intent}'")
        
        # BROWSER SEARCH INTERCEPT
        if core_intent == "browser_search":
            print("[PIPELINE - EXECUTION] Executing browser search via standard library.")
            import webbrowser
            import urllib.parse
            from legacy.tts import speak
            
            q = query.lower().strip()
            # extract ONLY after 'search for'
            if "search for" in q:
                search_part = q.split("search for", 1)[1].strip()
                if not search_part:
                    webbrowser.open("https://www.google.com")
                    speak("Opening Google")
                    return {"intent": "browser_search", "response": "Opening Google", "handled": True, "data": {}}
                
                encoded = urllib.parse.quote(search_part)
                url = f"https://www.google.com/search?q={encoded}"
                webbrowser.open(url)
                speak("Searching on Google")
                return {"intent": "browser_search", "response": "Searching on Google", "handled": True, "data": {}}
            else:
                # Safe fallback
                webbrowser.open("https://www.google.com")
                speak("Opening Google")
                return {"intent": "browser_search", "response": "Opening Google", "handled": True, "data": {}}
            
        # 2. Pipeline: Execution & Conflict Resolution
        response = None
        data = None
        
        if core_intent == "command":
             print(f"[PIPELINE - EXECUTION] Triggering Command Safe Layer: {cmd_obj.name if cmd_obj else 'unified_router'}")
             if cmd_obj:
                 success = self.router.command_registry.execute_command(cmd_obj, query)
                 resp = None
             else:
                 from core.unified_command_router import unified_router
                 cmd_res = unified_router.execute_single_action(query)
                 success = cmd_res.get("status") == "success"
                 resp = cmd_res.get("response")
             print("[PIPELINE - RESPONSE] Command executed synchronously.")
             print(f"==============================================\n")
             return {"intent": "system_command", "response": resp, "handled": True, "data": {"success": success}}
             
        elif core_intent == "current_time_query":
             print("[PIPELINE - EXECUTION] Fetching current time/date context.")
             data = self.retriever.retrieve("current_time_query", query)
             
        elif core_intent == "dynamic_fact_query":
             if not self.enable_web_search or not self.enable_live_data:
                 print("[RAG SYSTEM] Web search or live data disabled by configuration. Bypassing dynamic fact lookup.")
                 data = {"error": "Web search or live data disabled by configuration."}
             else:
                 print(f"[PIPELINE - EXECUTION] Fetching dynamic fact context via {self.search_provider}.")
                 data = self.retriever.retrieve("dynamic_fact_query", query)
                 
             # Check validation
             if not self.validator.validate("dynamic_fact_query", data):
                 print(f"[RAG SYSTEM ERROR] Dynamic fact retrieval validation failed. Data: {data}")
                 if not self.fallback_to_llm:
                     print("[RAG SYSTEM] LLM fallback is disabled. Returning error.")
                     return {
                         "intent": "error",
                         "response": "I apologize, but I could not fetch real-time information to answer that question.",
                         "data": data,
                         "handled": True
                     }
                 print("[RAG SYSTEM] Falling back to LLM direct generation (chat) for knowledge query.")
                 # CRITICAL: Keep the original unified intent to prevent incorrect routing
                 core_intent = "chat"
                 final_intent = "chat"
                 data = None  # Clear data so generator knows retrieval failed honestly
                 # IMPORTANT: DO NOT change original_unified_intent - it must remain as the user's original intent
             else:
                 print(f"[RAG SYSTEM] Dynamic fact retrieval succeeded and validated via {data.get('provider', self.search_provider)}.")
                 
        elif core_intent == "db_search":
             print(f"[PIPELINE - EXECUTION] Fetching local database/memory for: {sub_intent}")
             
             if sub_intent == "memory_storage":
                 # Secondary Extraction Pass
                 extract_prompt = (
                     "Identify the core fact the user wants to remember and provide a concise key-value pair.\n"
                     "Format: JSON | Example: 'Remember my dog's name is Buddy' -> {\"key\": \"dog_name\", \"value\": \"Buddy\"}\n"
                     "Respond with ONLY the JSON object."
                 )
                 try:
                     print("[PIPELINE - EXTRACTION] Extracting memory fact via LLM...")
                     raw_json = self.router.llm.get_completion(query, context=extract_prompt)
                     import json
                     fact = json.loads(raw_json)
                     
                     from extensions.memory.memory_parser import save_memory
                     save_memory(fact["key"], fact["value"])
                     
                     data = {"status": "success", "saved_fact": fact}
                     print(f"[PIPELINE - EXECUTION] Memory persisted: {fact['key']} = {fact['value']}")
                 except Exception as e:
                     print(f"[RAG SYSTEM ERROR] Memory extraction/save failed: {e}")
                     data = {"error": "Could not extract or save memory fact."}
             else:
                 # Retrieval
                 retrieval_intent = sub_intent if sub_intent != "memory_retrieval" else "memory_management"
                 data = self.retriever.retrieve(retrieval_intent, query)
             
             # DB Fallback Relevance Check
             if not self.validator.validate(sub_intent, data):
                 print(f"[RAG SYSTEM ERROR] DB data irrelevant/missing. Rerouting to web_search or chat. Data: {data}")
                 core_intent = "web_search" if sub_intent != "memory_retrieval" and sub_intent != "memory_storage" else "chat"
                 final_intent = core_intent
                 # IMPORTANT: DO NOT change original_unified_intent - it must remain as the user's original intent
                 print(f"[PIPELINE - DECISION] Recovered to Core Intent: '{core_intent}' (Original Unified Intent preserved: '{original_unified_intent}')")
             else:
                 print("[PIPELINE - VALIDATION] DB data valid. Proceeding to generation.")
                 
        if core_intent == "web_search":
             if not self.enable_web_search or not self.enable_live_data:
                 print("[RAG SYSTEM] Web search or live data disabled by configuration. Bypassing external web knowledge lookup.")
                 data = {"error": "Web search or live data disabled by configuration."}
             else:
                 print("[PIPELINE - EXECUTION] Fetching external web knowledge.")
                 data = self.retriever.retrieve("real_time_info", query)
                 
             # Web search fallback
             if not self.validator.validate("real_time_info", data):
                 print(f"[RAG SYSTEM ERROR] Web Search validation failed. Data: {data}")
                 if not self.fallback_to_llm:
                     print("[RAG SYSTEM] LLM fallback is disabled. Returning error.")
                     return {
                         "intent": "error",
                         "response": "I apologize, but I could not retrieve real-time search results.",
                         "data": data,
                         "handled": True
                     }
                 print("[RAG SYSTEM] Falling back to LLM direct generation (chat).")
                 core_intent = "chat"
                 final_intent = "chat"
                 data = None  # Clear data so generator knows retrieval failed honestly
                 # IMPORTANT: DO NOT change original_unified_intent - it must remain as the user's original intent
                 print(f"[PIPELINE - DECISION] Recovered to Core Intent: '{core_intent}'")
                 
        if core_intent == "chat":
             print("[PIPELINE - EXECUTION] Building conversational context.")
             # Pull limited recent context for normal chatter
             data = self.retriever.retrieve("history_query", query)
             
        # 3. Pipeline: Response Generation
        print("[PIPELINE - GENERATION] Synthesizing final response via LLM.")
        if final_intent in ["dynamic_fact_query", "current_time_query", "real_time_info", "web_search"]:
            eff_intent = final_intent
        elif final_intent == "db_search":
            eff_intent = sub_intent
        elif final_intent == "chat":
            eff_intent = "fallback" if original_unified_intent == "RAG_SEARCH" else "general_knowledge"
        else:
            eff_intent = sub_intent if sub_intent else "general_knowledge"
        
        try:
             response = self.generator.generate(query, eff_intent, data)
        except Exception as e:
             print(f"[PIPELINE - ERROR] Generation failed: {e}")
             response = "I had a bit of trouble formulating a response. What did you say?"
             
        # ====== PIPELINE INTEGRATION: DIRECT CODE GENERATION BYPASS ======
        # CRITICAL FIX: Only trigger code generation when the ORIGINAL unified intent was CODE_GENERATION
        # This prevents knowledge questions from incorrectly triggering code generation when RAG fails
        try:
            from modules.code_generator.main import (
                is_multi_file_request,
                extract_files, save_project, extract_code_and_lang, get_extension, save_single_file, open_in_vscode
            )
            # STRICT CHECK: Only proceed with code generation if the original unified intent was CODE_GENERATION
            if original_unified_intent == "CODE_GENERATION":
                print("[PIPELINE - GENERATION] Code request detected (original intent: CODE_GENERATION). Attempting extraction...")

                
                if is_multi_file_request(query):
                    files = extract_files(response)
                    if files:
                        project_path = save_project(files)
                        open_in_vscode(project_path)
                        response = f"Project created at {project_path} and opened in VS Code."
                    else:
                        # Fallback if LLM just answers with a single block even if requested multi-file
                        extracted_code, lang = extract_code_and_lang(response)
                        if extracted_code:
                            extension = get_extension(lang)
                            path = save_single_file(extracted_code, extension)
                            open_in_vscode(path)
                            response = f"Code saved as .{extension} and opened in VS Code."
                        else:
                            response = "Multi-file code generation failed."
                else:
                    extracted_code, lang = extract_code_and_lang(response)
                    if extracted_code:
                        extension = get_extension(lang)
                        path = save_single_file(extracted_code, extension)
                        open_in_vscode(path)
                        response = f"Code saved as .{extension} and opened in VS Code."
                    else:
                        response = "Code generation failed."
            else:
                print(f"[PIPELINE - GENERATION] Skipping code generation - original intent was '{original_unified_intent}', not CODE_GENERATION")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[PIPELINE - ERROR] Code Integration failed: {e}")
        # =================================================================
             
        try:
            print(f"[PIPELINE - OUTPUT] {response}")
        except (UnicodeEncodeError, Exception):
            safe_resp = response.encode("ascii", errors="replace").decode("ascii") if isinstance(response, str) else str(response)
            print(f"[PIPELINE - OUTPUT] {safe_resp}")
        print(f"==============================================\n")
        
        return {
            "intent": eff_intent, 
            "response": response,
            "data": data,
            "handled": True,  # Mark as handled to prevent legacy fallthrough
            "original_unified_intent": original_unified_intent  # Preserve original intent for debugging
        }
