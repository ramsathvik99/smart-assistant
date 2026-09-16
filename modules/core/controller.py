import os
import sys
import threading
import time

nova_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if nova_root not in sys.path:
    sys.path.insert(0, nova_root)

# Import strictly execution-based modules natively
from modules.code_generator.utils import detect_language, generate_filename, save_file, save_file_smart
from modules.code_generator.generator import generate_code
from modules.code_generator.tester import run_code

class AssistantController:
    """
    Deterministic Task Execution Controller for the Assistant.
    Receives tasks and strictly routes to execution modules. 
    NO conversational logic, NO AI chat fallbacks.
    """
    def __init__(self, callbacks: dict = None):
        self.callbacks = callbacks or {}
        
        self.last_generated_file = None
        self.last_output = ""

    def _update_status(self, text):
        if 'update_status' in self.callbacks:
            self.callbacks['update_status'](text)

    def _append_exec(self, text):
        if 'append_exec' in self.callbacks:
            self.callbacks['append_exec'](text)

    def _detect_task_type(self, command: str) -> str:
        command_lower = command.lower()
        if "code" in command_lower or "program" in command_lower or "calculator" in command_lower or "script" in command_lower:
            return "code"
        elif "essay" in command_lower or "write" in command_lower or "explain" in command_lower or "story" in command_lower:
            return "text"
        elif "create" in command_lower or "generate" in command_lower:
            return "code"
        else:
            return "unknown"

    def handle_command(self, command: str, auto_run: bool = True) -> dict:
        """
        Pure deterministic command router.
        """
        self._update_status("Executing task...")
        self._append_exec(f"[Controller] Dispatching: '{command}'")
        
        # --- NEW: SMART CODE DETECTION TRIGGER (FIRST PRIORITY) ---
        text = command.lower()
        
        import re
        
        # --- NEW: SEARCH BYPASS (Priority 1) ---
        match_search = re.search(r"(search for|search|look up|find) (.+)", text)
        if match_search:
            query = match_search.group(2).strip()
            import webbrowser
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            webbrowser.open(url)
            return {
                "status": "success",
                "output": f"Searching for {query}...",
                "file": None
            }
            
        # --- NEW: BROWSER TAB / SYSTEM COMMAND BYPASS (Priority 2 & 3) ---
        if any(k in text for k in ["tab", "close", "open"]):
            from modules.core.tab_manager import handle_tab_command
            output = handle_tab_command(text)
            if output:
                return {
                    "status": "success",
                    "output": output,
                    "file": None
                }
                
        # --- NEW: MUSIC PLAYBACK BYPASS ---
        if "play" in text:
            from modules.core.music_manager import handle_play_command
            output = handle_play_command(text)
            if output:
                return {
                    "status": "success",
                    "output": output,
                    "file": None
                }
                
        # --- NEW: RECOMMENDATION BYPASS ---
        if any(k in text for k in ["suggest", "recommend", "what should i"]):
            from extensions.recommendation.recommender import get_recommendations
            from extensions.llm_engine import LLMEngine
            
            engine = LLMEngine()
            def ai_generate(prompt):
                return engine.get_completion(prompt)
                
            output = get_recommendations(text, ai_generate)
            if output:
                return {
                    "status": "success",
                    "output": output,
                    "file": None
                }

        # --- NEW: AI EXPLAIN BYPASS (Priority 4) ---
        if any(k in text for k in ["what is", "who is", "explain", "tell me about"]):
            from extensions.llm_engine import LLMEngine
            engine = LLMEngine()
            output = engine.get_completion(text)
            return {
                "status": "success",
                "output": output,
                "file": None
            }
        # -------------------------------

        coding_keywords = [
            "code", "program", "implement", "algorithm",
            "function", "script", "write", "create"
        ]
        coding_topics = [
            "sort", "search", "binary", "tree", "linked list",
            "stack", "queue", "graph", "array", "string",
            "bubble sort", "merge sort", "quick sort",
            "factorial", "fibonacci"
        ]
        
        if any(k in text for k in coding_keywords) or any(t in text for t in coding_topics):
            print("[DEBUG] SMART CODE DETECTION TRIGGERED")
            from modules.code_generator.main import process_request
            
            # Clean prompt as requested
            cleaned_prompt = command.replace("write", "").replace("code", "").strip()
            process_request(cleaned_prompt) # already generates, saves, opens VS Code
            
            return {
                "status": "success",
                "output": "I've created the code file for you.",
                "file": None
            }
        # ---------------------------------------------------------

        print(f"UI sending: {command}")
        print(f"Controller received: {command}")
        
        command_lower = command.lower().strip()
        
        try:
            task_type = self._detect_task_type(command_lower)
            
            # --- DATE / TIME (HIGHEST PRIORITY) ---
            if "date" in command_lower:
                print("Routing to: get_date")
                from legacy.action_skills import get_date
                output = get_date()
                self.last_output = output
                return {"status": "success", "output": output, "file": None}
                
            elif "time" in command_lower:
                print("Routing to: get_time")
                from legacy.action_skills import get_time
                output = get_time()
                self.last_output = output
                return {"status": "success", "output": output, "file": None}
            
            # Route 1: Code Generation Task
            elif task_type == "code":
                return self._handle_code_generation(command, auto_run)
                
            # Route 2: Text Generation Task
            elif task_type == "text":
                return self._handle_text_generation(command)
                
            # Route 3: Weather Queries — delegates to legacy.skills.get_weather
            elif "weather" in command_lower:
                print("Routing to: get_weather")
                from legacy.skills import get_weather as _legacy_get_weather
                
                # Extract location: look for "in <city>" or "for <city>"
                import re as _re
                location = None
                for kw in ("in ", "for "):
                    if kw in command_lower:
                        after = command_lower.split(kw, 1)[-1].strip()
                        after = _re.sub(r"[?.!,]+$", "", after).strip()
                        if after:
                            location = after
                            break
                
                print(f"[Controller] Weather route → location: {location}")
                self._append_exec(f"[Module: Legacy Weather] Fetching for: {location or 'not specified'}")
                
                if not location:
                    output = "Please specify a city. Example: 'weather in Nellore'"
                else:
                    output = _legacy_get_weather(location) or f"Could not fetch weather for {location}."
                
                self.last_output = output
                return {"status": "success", "output": output, "file": None}

            # Route 4: Execution Task
            elif "run" in command_lower or "execute" in command_lower:
                return self._handle_run_last()
                
            # Route 6: News — delegates to legacy.skills.get_news
            elif "news" in command_lower:
                print("Routing to: get_news")
                from legacy.skills import get_news as _legacy_get_news
                import re as _re

                # Extract topic/location: look for "about <topic>" or "in <place>"
                topic = "India"  # default
                for kw in ("about ", "on ", "in ", "for "):
                    if kw in command_lower:
                        after = command_lower.split(kw, 1)[-1].strip()
                        after = _re.sub(r"[?.!,]+$", "", after).strip()
                        if after:
                            topic = after
                            break

                print(f"[Controller] News route → topic: {topic}")
                self._append_exec(f"[Module: Legacy News] Fetching news for: {topic}")
                output = _legacy_get_news(topic) or f"Could not fetch news for '{topic}'."
                self.last_output = output
                return {"status": "success", "output": output, "file": None}

            # Route 7: Math Solver
            elif any(w in command_lower for w in ["+", "-", "*", "/", "calculate"]):
                print("Routing to: solve_math")
                from legacy.skills import solve_math
                self._append_exec("[Module: Legacy Math] Solving expression...")
                output = solve_math(command)
                self.last_output = str(output)
                return {"status": "success", "output": output, "file": None}

            # Route 8: Currency Conversion
            elif "convert" in command_lower and any(c in command_lower for c in ["usd", "inr", "eur", "gbp", "yen", "dollar", "rupee"]):
                print("Using legacy currency converter")
                from legacy.skills import convert_currency
                # Note: Legacy expects (amount, src, dest) - we'll let LLM fallback if extraction is complex, 
                # but for simple "convert 10 usd to inr":
                import re as _re
                match = _re.search(r"(\d+(?:\.\d+)?)\s*([a-z]{3})\s*(?:to|in)\s*([a-z]{3})", command_lower)
                if match:
                    amount = float(match.group(1))
                    src = match.group(2)
                    dest = match.group(3)
                    output = convert_currency(amount, src, dest)
                else:
                    output = "Please use format: 'convert 10 USD to INR'"
                self.last_output = output
                return {"status": "success", "output": output, "file": None}

            # Route 9: Unit Conversion
            elif "convert" in command_lower and any(u in command_lower for u in ["meter", "centimeter", "kg", "gram", "mile", "km", "inch", "foot"]):
                print("Using legacy unit converter")
                from legacy.skills import convert_units
                import re as _re
                match = _re.search(r"(\d+(?:\.\d+)?)\s*([a-z]+)\s*(?:to|in)\s*([a-z]+)", command_lower)
                if match:
                    val = float(match.group(1))
                    u_fr = match.group(2)
                    u_to = match.group(3)
                    output = convert_units(val, u_fr, u_to)
                else:
                    output = "Please use format: 'convert 1 meter to feet'"
                self.last_output = output
                return {"status": "success", "output": output, "file": None}

            # Route 10: Alarms & Timers
            elif "alarm" in command_lower:
                from legacy.skills import set_alarm
                self._append_exec("[Module: Legacy Alarm] Setting alarm...")
                output = set_alarm(command)
                return {"status": "success", "output": output, "file": None}
            elif "timer" in command_lower:
                from legacy.skills import set_timer
                self._append_exec("[Module: Legacy Timer] Setting timer...")
                output = set_timer(command)
                return {"status": "success", "output": output, "file": None}

            # Route 11: Translation
            elif "translate" in command_lower:
                from legacy.skills import translate_text
                self._append_exec("[Module: Legacy Translator] Translating...")
                output = translate_text(command)
                return {"status": "success", "output": output, "file": None}

            # Route 12: Dictionary
            elif "define" in command_lower or "meaning of" in command_lower:
                from legacy.skills import define_word
                self._append_exec("[Module: Legacy Dictionary] Looking up definition...")
                output = define_word(command)
                return {"status": "success", "output": output, "file": None}

            # Route 13: Notes System
            elif "note" in command_lower:
                from legacy.skills import add_note, read_notes, clear_all_notes
                if "read" in command_lower:
                    output = read_notes()
                elif "clear" in command_lower or "delete all" in command_lower:
                    output = clear_all_notes()
                else:
                    # extract note text after "add note" or "write note"
                    note_text = command_lower.replace("add note", "").replace("write note", "").replace("note", "").strip()
                    output = add_note(note_text)
                return {"status": "success", "output": output, "file": None}

            # Route 14: System Utilities (Screenshot / Lock)
            elif "screenshot" in command_lower:
                from legacy.skills import take_screenshot
                self._append_exec("[Module: Legacy System] Taking screenshot...")
                output = take_screenshot()
                return {"status": "success", "output": output, "file": None}
            elif "lock" in command_lower and "system" in command_lower:
                from legacy.skills import lock_system
                output = lock_system()
                return {"status": "success", "output": output, "file": None}


                
            # Route 5: General Queries (Who/What/Where)
            elif "who" in command_lower or "what" in command_lower or "where" in command_lower or "when" in command_lower or "why" in command_lower or "how" in command_lower:
                from extensions.llm_engine import LLMEngine
                engine = LLMEngine()
                prompt = (
                    "Answer this question factually and directly in 1-2 sentences. "
                    "Do NOT use conversational filler like 'Sure' or 'I can help'. "
                    f"Question: {command}"
                )
                self._append_exec("[Module: LLM] Querying backend...")
                response = engine.get_completion(prompt)
                
                if response:
                    self.last_output = response
                    self._append_exec("[Module: LLM] Retrieved answer.")
                    return {
                        "status": "success",
                        "output": response,
                        "file": None
                    }
                else:
                    return {
                        "status": "error",
                        "output": "Failed to retrieve an answer.",
                        "file": None
                    }

            # Fallback: Route ALL unknown commands to LLM for intelligent response
            else:
                print(f"[Controller] No deterministic route found. Routing to LLM: {command}")
                self._append_exec("[Module: LLM] No route matched — querying LLM...")
                from extensions.llm_engine import LLMEngine
                engine = LLMEngine()
                prompt = (
                    "Respond to the following request directly and concisely in 1-3 sentences. "
                    "Be helpful but factual. Do NOT use conversational filler like 'Sure!' or 'Of course!'. "
                    f"Request: {command}"
                )
                response = engine.get_completion(prompt)
                if response:
                    self.last_output = response
                    self._append_exec("[Module: LLM] Response received.")
                    return {
                        "status": "success",
                        "output": response,
                        "file": None
                    }
                else:
                    return {
                        "status": "error",
                        "output": f"No handler found for: '{command}'",
                        "file": None
                    }
                
        except Exception as e:
            return {
                "status": "error",
                "output": str(e),
                "file": None
            }
            
        finally:
            self._update_status("Idle")

    # ---- Module Handlers ----

    def _handle_code_generation(self, command: str, auto_run: bool) -> dict:
        self._append_exec("[Module: CodeGen] Processing generation request...")
        language = detect_language(command)
        
        code = generate_code(command, language)
        
        if not code or code.startswith("❌"):
            self._append_exec("[Module: CodeGen] Generation failed.")
            return {
                "status": "error",
                "output": "Failed to generate code.",
                "file": None
            }
            
        self._append_exec("[Module: FileManager] Writing generated code to file...")
        ext = ".js" if language in ["node", "javascript"] else (".cpp" if language == "cpp" else ".py")
        filename = generate_filename(command, ext)
        
        filepath = save_file(filename, code)
        self.last_generated_file = filepath
        self._append_exec(f"[Module: FileManager] File saved globally.")
        
        if auto_run:
            self._append_exec("[Module: Executor] Automatically executing new file...")
            return self._handle_run_last(language)
        else:
            self.last_output = f"Code generated successfully"
            self._append_exec("Task completed")
            return {
                "status": "success",
                "output": code, # Output the raw code if not running it
                "file": filepath
            }

    def _handle_text_generation(self, command: str) -> dict:
        self._append_exec("[Module: Writer] Processing text generation request...")
        from extensions.llm_engine import LLMEngine
        
        engine = LLMEngine()
        prompt = f"Write the requested content clearly and concisely without code blocks unless explicitly asked. Command: {command}"
        text_output = engine.get_completion(prompt)
        
        if not text_output:
            return {
                "status": "error",
                "output": "Failed to generate text content.",
                "file": None
            }
            
        self._append_exec("[Module: FileManager] Saving generated text...")
        filepath = save_file_smart(command, text_output, ".txt")
        
        self.last_generated_file = filepath
        self.last_output = text_output
        self._append_exec(f"Task completed. Saved to: {filepath}")
        
        return {
            "status": "success",
            "output": f"{text_output}\n\n[Saved to: {filepath}]",
            "file": filepath
        }

    def _handle_run_last(self, language=None) -> dict:
        if not self.last_generated_file or not os.path.exists(self.last_generated_file):
            return {
                "status": "error",
                "output": "No file found to execute.",
                "file": None
            }
            
        if not language:
            ext = os.path.splitext(self.last_generated_file)[1].lower()
            lang_map = {'.py': 'python', '.js': 'node', '.cpp': 'cpp', '.c': 'c', '.java': 'java'}
            language = lang_map.get(ext, 'python')
            
        success, output = run_code(self.last_generated_file, language)
        self.last_output = output
        
        if success:
            self._append_exec("[Module: Executor] Task completed")
        else:
            self._append_exec("[Module: Executor] Task failed")
            
        return {
            "status": "success" if success else "error",
            "output": output, # Output ONLY the execution raw stdout/stderr
            "file": self.last_generated_file
        }

    def _handle_save_output(self, command: str) -> dict:
        if not self.last_output.strip():
            return {
                "status": "error",
                "output": "No previous output to save.",
                "file": None
            }
            
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        filename = f"assistant_output_{int(time.time())}.txt"
        
        if " as " in command.lower():
            parts = command.lower().split(" as ")
            if len(parts) > 1 and parts[1].strip():
                filename = parts[1].strip()
                if not filename.endswith(".txt"):
                    filename += ".txt"
        
        filepath = os.path.join(downloads, filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(self.last_output)
                
            self._append_exec(f"[Module: FileManager] File saved iteratively.")
            self._append_exec("Task completed")
            return {
                "status": "success",
                "output": f"Content saved to {filepath}",
                "file": filepath
            }
        except Exception as e:
            return {
                "status": "error",
                "output": str(e),
                "file": None
            }

    def override_last_file_name(self, new_filename: str) -> dict:
        if not new_filename or not self.last_generated_file:
            return {
                "status": "error",
                "output": "No active file to rename.",
                "file": None
            }
            
        old_filepath = self.last_generated_file
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        new_filepath = os.path.join(downloads, new_filename)
        
        try:
            os.rename(old_filepath, new_filepath)
            self.last_generated_file = new_filepath
            self._append_exec(f"[Module: FileManager] Renamed operational file")
            return {
                "status": "success",
                "output": f"Renamed to {new_filename}",
                "file": new_filepath
            }
        except Exception as e:
            return {
                "status": "error",
                "output": str(e),
                "file": None
            }
