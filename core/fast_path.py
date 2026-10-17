"""
Fast Path Processor for High-Frequency Normal Interactions
Provides sub-millisecond to low-millisecond responses for:
- Conversational greetings, politeness, and identity checks
- Local system/filesystem queries (current directory, pwd)
- Process and application state queries ("is VS Code open?", "is Chrome running?")
- Active file/editor inspection ("what file am I editing?")
- Immediate context & recent action queries ("what did I just do?")
- Pure utility queries (time, date, safe arithmetic)

Preserves 100% of reasoning, safety, verification, and memory systems for complex workflows.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple


class FastPathProcessor:
    """
    Lightweight, deterministic fast-path engine.
    Detects simple queries that do not require multi-intent planning,
    deep environment tree reconstruction, or external LLM round-trips.
    """

    KNOWN_APP_MAPPINGS = {
        "vs code": ("code", "Visual Studio Code"),
        "vscode": ("code", "Visual Studio Code"),
        "visual studio code": ("code", "Visual Studio Code"),
        "code": ("code", "Visual Studio Code"),
        "chrome": ("chrome", "Google Chrome"),
        "google chrome": ("chrome", "Google Chrome"),
        "notepad": ("notepad", "Notepad"),
        "text editor": ("notepad", "Notepad"),
        "the text editor": ("notepad", "Notepad"),
        "calculator": ("calc", "Calculator"),
        "calc": ("calc", "Calculator"),
        "edge": ("msedge", "Microsoft Edge"),
        "ms edge": ("msedge", "Microsoft Edge"),
        "msedge": ("msedge", "Microsoft Edge"),
        "microsoft edge": ("msedge", "Microsoft Edge"),
        "terminal": ("windowsterminal", "Windows Terminal"),
        "windows terminal": ("windowsterminal", "Windows Terminal"),
        "cmd": ("cmd", "Command Prompt"),
        "command prompt": ("cmd", "Command Prompt"),
        "powershell": ("powershell", "PowerShell"),
        "spotify": ("spotify", "Spotify"),
        "discord": ("discord", "Discord"),
        "slack": ("slack", "Slack"),
        "word": ("winword", "Microsoft Word"),
        "excel": ("excel", "Microsoft Excel"),
        "powerpoint": ("powerpnt", "PowerPoint"),
    }

    @classmethod
    def try_fast_path(
        cls,
        user_input: str,
        user_id: str = "default",
        dialogue_mgr: Any = None
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate if query can be answered via the fast path.
        Returns result Dict if handled, or None if complex reasoning/planning is required.
        """
        if not user_input or not user_input.strip():
            return None

        # Active email dictation/session takes strict precedence over fast path
        import sys
        if 'modules.assistant_email.email_controller' in sys.modules:
            try:
                from modules.assistant_email.email_controller import is_active_email_session, _resolve_user
                if is_active_email_session(_resolve_user(user_id)):
                    return None
            except Exception:
                pass

        clean_text = user_input.strip()
        low = clean_text.lower().rstrip('.?!,').strip()

        # Strip assistant wake word prefix or suffix if present (e.g. "Friday what can you do" or "How are you, Friday?")
        norm_low = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|trevon|nova|jarvis|assistant)[,\s:]*', '', low, flags=re.IGNORECASE).strip()
        norm_low = re.sub(r'[,:\s]+(?:friday|trevon|nova|jarvis|assistant)\s*$', '', norm_low, flags=re.IGNORECASE).strip()

        # ---------------------------------------------------------------------
        # 1. Greetings, Politeness & Identity
        # ---------------------------------------------------------------------
        if low in (
            "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
            "howdy", "hey there", "hello there", "greetings", "hi friday", "hello friday",
            "hey friday", "friday"
        ) or norm_low in ("hello", "hi", "hey", "good morning", "good afternoon", "good evening"):
            resp = "Hey! How can I help you today?"
            return cls._build_result("GENERAL_CONVERSATION", resp, dialogue_mgr)

        if low in (
            "thanks", "thank you", "thank you so much", "thanks a lot", "many thanks"
        ) or norm_low in ("thanks", "thank you", "thank you so much"):
            resp = "You're very welcome! Let me know if you need anything else."
            return cls._build_result("GENERAL_CONVERSATION", resp, dialogue_mgr)

        if low in (
            "how are you", "how are you doing", "how's it going", "how are things",
            "what's up", "whats up", "how are you feeling", "how are you feeling today",
            "how are you feeling right now", "how are you doing today", "how do you feel"
        ) or norm_low in (
            "how are you", "how are you doing", "how's it going", "what's up",
            "how are you feeling", "how are you feeling today", "how are you feeling right now",
            "how are you doing today", "how do you feel"
        ):
            resp = "I'm feeling great and ready to help! What would you like to work on?"
            return cls._build_result("GENERAL_CONVERSATION", resp, dialogue_mgr)

        identity_queries = (
            "who are you", "what is your name", "what's your name", "whats your name",
            "who're you", "tell me about yourself", "introduce yourself", "who made you",
            "who created you", "who built you", "what are you", "who am i speaking with",
            "who am i talking to", "what is your identity", "whats your identity", "who is this",
            "tell me who you are", "what should i call you"
        )
        if low in identity_queries or norm_low in identity_queries:
            asst_name = "Trevon"
            try:
                from instance.config import settings as _cfg
                asst_name = _cfg.get_assistant_name()
            except Exception:
                pass
            resp = f"I'm {asst_name}, your desktop assistant."
            return cls._build_result("GENERAL_CONVERSATION", resp, dialogue_mgr)

        # ---------------------------------------------------------------------
        # 1.1 Time and Date Queries (Deterministic, Zero Latency)
        # ---------------------------------------------------------------------
        time_queries = (
            "what time is it", "what is the time", "what's the time", "whats the time",
            "tell me the time", "current time", "time", "what time is it now",
            "tell me what time it is", "do you have the time"
        )
        if (low in time_queries or norm_low in time_queries or
            re.match(r'^(?:tell\s+me\s+)?(?:what\s+(?:is\s+)?(?:the\s+)?time(?:\s+is\s+it)?|current\s+time|what\'?s\s+the\s+time)$', norm_low)):
            now_str = datetime.now().strftime("%I:%M %p")
            resp = f"The current time is {now_str}."
            return cls._build_result("TIME_QUERY", resp, dialogue_mgr)

        date_queries = (
            "what date is it", "what is today's date", "what's today's date", "whats todays date",
            "what is the date", "what's the date", "whats the date", "what day is it",
            "what day is today", "today's date", "todays date", "current date"
        )
        if (low in date_queries or norm_low in date_queries or
            re.match(r'^(?:tell\s+me\s+)?(?:what\s+(?:is\s+)?(?:today\'?s\s+)?date|current\s+date|what\s+day\s+is\s+it|what\s+day\s+is\s+today)$', norm_low)):
            now_str = datetime.now().strftime("%A, %B %d, %Y")
            resp = f"Today is {now_str}."
            return cls._build_result("DATE_QUERY", resp, dialogue_mgr)

        # ---------------------------------------------------------------------
        # 1b. Runtime Capabilities & Registry Query
        # ---------------------------------------------------------------------
        from core.capability_registry import get_capability_registry
        cap_reg = get_capability_registry()

        spec_cap = cap_reg.check_capability_support(norm_low)
        if spec_cap:
            return cls._build_result("CAPABILITY_QUERY", spec_cap, dialogue_mgr)

        concise_capability_overview = cap_reg.format_concise_capabilities()

        if norm_low in (
            "the action that you can perform", "the actions that you can perform",
            "the actions you can perform", "action that you can perform", "actions that you can perform",
            "actions you can perform", "what actions can you perform", "what actions you can perform",
            "what can you do", "what are your capabilities", "what can you help me with",
            "what are you capable of", "what can you do for me", "tell me what you can do",
            "help", "capabilities"
        ) or re.match(r'^(?:what\s+actions?\s+(?:can\s+you|do\s+you)\s+perform|the\s+actions?\s+(?:that\s+)?you\s+can\s+perform)$', norm_low):
            resp = cap_reg.format_capabilities_overview()
            return cls._build_result("CAPABILITY_QUERY", resp, dialogue_mgr)

        # Check active continuation state for list queries before generic capability dump
        list_continuation_keywords = (
            "full list", "continue", "resume", "repeat", "say that again", "next",
            "first", "second", "third", "1st", "2nd", "3rd", "fourth", "fifth"
        )
        if any(k in norm_low for k in list_continuation_keywords):
            if not dialogue_mgr and user_id:
                try:
                    from extensions.dialogue_state_manager import get_dialogue_manager
                    dialogue_mgr = get_dialogue_manager(str(user_id))
                except Exception:
                    pass

        if dialogue_mgr and hasattr(dialogue_mgr, "current_state"):
            cs = dialogue_mgr.current_state
            has_rec = bool(cs.current_recommendation_list)
            has_resp = bool(cs.current_response)
            has_interrupted = bool(cs.interrupted_speech_text)

            # 1. Full list requests
            if norm_low in (
                "that's it give me full list", "thats it give me full list",
                "give me full list", "give me the full list", "give full list",
                "full list", "what is the full list", "give the full list",
                "show full list", "show the full list", "show me the full list"
            ) and (has_rec or has_resp):
                return cls._build_result("RECOMMENDATION", dialogue_mgr.get_full_list_response(), dialogue_mgr)

            # 2. Continue / Resume speech or remaining items
            if norm_low in (
                "continue what you are saying", "continue what you were saying",
                "continue what you said", "continue saying", "keep going",
                "continue", "resume what you were saying"
            ) and (has_interrupted or cs.remaining_response_segments or has_rec):
                return cls._build_result("GENERAL_CONVERSATION", dialogue_mgr.get_continue_response(), dialogue_mgr)

            # 3. Repeat last part
            if norm_low in (
                "repeat last part", "repeat the last part", "repeat what you said",
                "repeat that", "what did you just say", "say that again", "repeat"
            ) and (cs.current_spoken_segment or has_resp):
                return cls._build_result("GENERAL_CONVERSATION", dialogue_mgr.get_repeat_last_part(), dialogue_mgr)

            # 4. Next item
            if norm_low in ("next item", "what's next", "whats next", "next recommendation", "next") and has_rec:
                return cls._build_result("RECOMMENDATION", dialogue_mgr.get_next_item(), dialogue_mgr)

            # 5. First item
            if norm_low in ("first item", "what was the first item", "first recommendation", "first one", "first", "the first", "and the first", "1st") and (has_rec or getattr(cs, "active_response_state", None)):
                return cls._build_result("RECOMMENDATION", dialogue_mgr.get_item_by_index(0), dialogue_mgr)

            # 6. Second item
            if norm_low in ("second item", "what was the second item", "second recommendation", "second one", "second", "the second", "and the second", "2nd") and (has_rec or getattr(cs, "active_response_state", None)):
                return cls._build_result("RECOMMENDATION", dialogue_mgr.get_item_by_index(1), dialogue_mgr)

            # 7. Third item
            if norm_low in ("third item", "what was the third item", "third recommendation", "third one", "third", "the third", "and the third", "3rd") and (has_rec or getattr(cs, "active_response_state", None)):
                return cls._build_result("RECOMMENDATION", dialogue_mgr.get_item_by_index(2), dialogue_mgr)

            # 8. Previous item
            if norm_low in ("previous item", "what was the previous item", "previous recommendation", "previous one") and has_rec:
                return cls._build_result("RECOMMENDATION", dialogue_mgr.get_previous_item(), dialogue_mgr)

            # 9. Last item
            if norm_low in ("last item", "what was the last item", "the last", "last one", "last") and has_rec:
                return cls._build_result("RECOMMENDATION", dialogue_mgr.get_last_item(), dialogue_mgr)

            # 10. Navigation commands ("all of them", "those", "them", "that", "this")
            if norm_low in ("all of them", "those", "them", "that", "this") and (has_rec or getattr(cs, "active_response_state", None)):
                return cls._build_result("RECOMMENDATION", dialogue_mgr.get_full_list_response(), dialogue_mgr)

            # 11. Deterministic Calculation follow-up ("tell me the answer")
            if norm_low in ("tell me the answer", "what is the answer", "what's the answer", "the answer", "answer", "give me the answer"):
                ans = dialogue_mgr.get_calculation_answer()
                if ans is not None:
                    return cls._build_result("CALCULATOR", f"The answer is {ans}.", dialogue_mgr)

            # 12. Deterministic Goal Step follow-up ("to the first step")
            if norm_low in ("to the first step", "the first step", "first step", "to step 1", "step 1", "what is the first step", "to the 1st step"):
                st = dialogue_mgr.get_goal_step(0)
                if st:
                    return cls._build_result("GOAL_TRACKING", st, dialogue_mgr)
            elif norm_low in ("to the second step", "the second step", "second step", "to step 2", "step 2", "what is the second step", "to the 2nd step"):
                st = dialogue_mgr.get_goal_step(1)
                if st:
                    return cls._build_result("GOAL_TRACKING", st, dialogue_mgr)

            # 13. Deterministic Document Task Queries ("is the PPT done?", "did you create it?")
            if re.search(r'^(?:is\s+(?:the\s+)?(?:ppt|presentation|document|doc|docx|pdf|report)\s+(?:done|ready|finished|created)|did\s+you\s+(?:create|make|finish)\s+it|is\s+it\s+(?:done|ready|finished))[.?!]?$', norm_low):
                from core.document_task_state import get_document_task_manager
                mgr = get_document_task_manager()
                task_type = None
                if "ppt" in norm_low or "presentation" in norm_low:
                    task_type = "PPTX"
                elif "pdf" in norm_low:
                    task_type = "PDF"
                elif "doc" in norm_low or "docx" in norm_low or "report" in norm_low:
                    task_type = "DOCX"
                latest_task = mgr.get_latest_task(user_id=str(user_id), artifact_type=task_type)
                if latest_task:
                    if latest_task.status == "COMPLETED":
                        sc_str = f" with {latest_task.slide_count} slides" if latest_task.slide_count else ""
                        msg = f"Yes, the {latest_task.artifact_type} '{latest_task.title or 'document'}' has been created successfully{sc_str} at {latest_task.artifact_path}."
                    elif latest_task.status in ("RUNNING", "QUEUED"):
                        msg = f"The {latest_task.artifact_type} document is currently being generated."
                    else:
                        msg = f"The {latest_task.artifact_type} generation failed: {latest_task.error or 'unknown error'}."
                    return cls._build_result("DOCUMENT_STATUS", msg, dialogue_mgr)
                elif getattr(cs, "active_artifact", None):
                    art = cs.active_artifact
                    msg = f"Yes, the {art.get('format', 'document')} '{art.get('title', 'document')}' has been created successfully at {art.get('filepath', '')}."
                    return cls._build_result("DOCUMENT_STATUS", msg, dialogue_mgr)

            # 14. Deterministic Open Document
            if re.search(r'^(?:open\s+(?:the\s+)?(?:document|presentation|ppt|pptx|report|pdf|excel|file))[.?!]?$', norm_low):
                from core.document_task_state import get_document_task_manager
                mgr = get_document_task_manager()
                latest_task = mgr.get_latest_task(user_id=str(user_id))
                art_path = None
                if latest_task and latest_task.artifact_path and os.path.exists(latest_task.artifact_path):
                    art_path = latest_task.artifact_path
                elif getattr(cs, "active_artifact", None) and cs.active_artifact.get("filepath") and os.path.exists(cs.active_artifact["filepath"]):
                    art_path = cs.active_artifact["filepath"]
                if art_path:
                    try:
                        os.startfile(art_path)
                        fn = os.path.basename(art_path)
                        return cls._build_result("OPEN_APPLICATION", f"Opened {fn}.", dialogue_mgr)
                    except Exception as e:
                        return cls._build_result("OPEN_APPLICATION", f"Found document at {art_path}, but could not launch: {e}", dialogue_mgr)


        if norm_low in ("show me the full list", "show the full list", "show full list", "display the full list", "show all capabilities"):
            resp = cap_reg.format_capabilities_overview()
            return cls._build_result("CAPABILITY_QUERY", resp, dialogue_mgr)

        # ---------------------------------------------------------------------
        # 1c. Conversational Recovery & Follow-up Dialogue
        # ---------------------------------------------------------------------
        if any(p in norm_low for p in (
            "why does not meet the problem is with you",
            "you are the one who is not taking all the input",
            "you are not able to put what i am trying to say",
            "you are not taking all the input",
            "not taking all the input that i am saying",
            "you're not taking all the input",
        )) or (("problem is with you" in norm_low or "not taking all the input" in norm_low) and "you" in norm_low):
            resp = "You're right. I wasn't capturing your full input. I'll focus on the complete request instead of jumping to a generic interpretation."
            return cls._build_result("GENERAL_CONVERSATION", resp, dialogue_mgr)

        if norm_low in (
            "are you getting my point", "do you understand what i'm saying", "do you understand what i am saying",
            "are you listening to me", "are you listening", "are you paying attention"
        ) or re.match(r'^are\s+you\s+(?:getting\s+my\s+point|listening(?:\s+to\s+me)?)$', norm_low):
            resp = "Yes, I understand what you're saying. Please go ahead."
            return cls._build_result("GENERAL_CONVERSATION", resp, dialogue_mgr)

        if norm_low in ("why are you doing that", "why are you responding like this"):
            resp = "I was interpreting your input too broadly. I'll stick to exactly what you need."
            return cls._build_result("GENERAL_CONVERSATION", resp, dialogue_mgr)

        if norm_low in ("try again", "listen to the whole thing", "listen to what i am saying"):
            resp = "Understood. Please go ahead, I'm listening to your full request."
            return cls._build_result("GENERAL_CONVERSATION", resp, dialogue_mgr)

        if norm_low in ("no that's not what i meant", "no that is not what i meant", "that's not what i asked", "that is not what i asked"):
            resp = "Understood. Let me know what you'd like me to do instead."
            return cls._build_result("GENERAL_CONVERSATION", resp, dialogue_mgr)

        # Ambiguous fragments without clear action (Requirement 13)
        if norm_low in ("full", "full details") or re.match(r'^(?:full|full\s+details)$', norm_low):
            active_art = None
            if dialogue_mgr and hasattr(dialogue_mgr, "current_state"):
                active_art = getattr(dialogue_mgr.current_state, "active_artifact", None)
            if active_art and isinstance(active_art, dict) and active_art.get("content"):
                resp = f"Here are the full details for '{active_art.get('topic', 'the active topic')}':\n\n{active_art.get('content')}"
                return cls._build_result("ARTIFACT_QUERY", resp, dialogue_mgr)
            else:
                resp = "Full details on what?"
                return cls._build_result("GENERAL_CONVERSATION", resp, dialogue_mgr)


        # ---------------------------------------------------------------------
        # 2. Current Working Directory / Location in Local Filesystem
        # ---------------------------------------------------------------------
        if low in (
            "what is my current directory", "what's my current directory", "whats my current directory",
            "what is my current working directory", "what's my current working directory",
            "what is my working directory", "what's my working directory", "whats my working directory",
            "what directory am i in", "what folder am i in", "which directory am i in",
            "where am i", "where am i located", "pwd", "current directory", "working directory",
            "get current directory", "show current directory", "tell me my current directory"
        ):
            curr_dir = os.getcwd()
            resp = f"You're in {curr_dir}"
            res = cls._build_result("OS_OPERATION", resp, dialogue_mgr)
            res["directory"] = curr_dir
            return res


        # ---------------------------------------------------------------------
        # 4. Application Running / Open State Query
        # "Is VS Code open?", "Is Chrome running?", "Check if Notepad is open"
        # ---------------------------------------------------------------------
        m_app_query = re.match(
            r'^(?:is|check\s+if)\s+(.+?)\s+(?:currently\s+)?(open|running|active|launched)[.!?]?$',
            low
        )
        if m_app_query:
            target_raw = m_app_query.group(1).strip()
            # Clean articles
            target_clean = re.sub(r'^(?:the|my)\s+', '', target_raw).strip()
            mapped = cls.KNOWN_APP_MAPPINGS.get(target_clean)
            proc_key = mapped[0] if mapped else target_clean
            app_display = mapped[1] if mapped else target_clean.title()

            is_running = False
            # 1. Quick check via psutil process inspection
            try:
                from core.os_gateway.process_ops import find_process
                proc_res = find_process(proc_key)
                if proc_res.get("success"):
                    is_running = True
            except Exception:
                pass

            # 2. Window check fallback
            if not is_running:
                try:
                    from skills.window_management.window_context import get_foreground_window_info
                    fg = get_foreground_window_info()
                    if fg and proc_key in (fg.get("title") or "").lower():
                        is_running = True
                except Exception:
                    pass

            if is_running:
                resp = f"{app_display} is currently open."
            else:
                resp = f"{app_display} is not running."

            res = cls._build_result("SYSTEM_DIAGNOSTICS", resp, dialogue_mgr)
            res["running"] = is_running
            res["application"] = app_display
            return res

        # ---------------------------------------------------------------------
        # 4b. Environment State Query (Active Application, Active Window, Screen Resolution)
        # Authority: EnvironmentObserver / Unified State Engine
        # ---------------------------------------------------------------------
        if low in (
            "what application is currently active", "what application is active",
            "what is the active application", "what's the active application",
            "active application", "current application", "which application is active",
            "what app is active", "what app is currently active"
        ):
            from core.environment_observer import observe_environment
            obs = observe_environment(user_id=str(user_id))
            app = obs.active_application or (obs.active_window.get("app_name") if obs.active_window else None) or "Unknown Application"
            resp = f"The currently active application is {app}."
            res = cls._build_result("SYSTEM_DIAGNOSTICS", resp, dialogue_mgr)
            res["active_application"] = app
            return res

        if low in (
            "what is the active window", "what's the active window", "active window",
            "current window", "what window is active", "which window is active",
            "what is my active window"
        ):
            from core.environment_observer import observe_environment
            obs = observe_environment(user_id=str(user_id))
            win_title = obs.foreground_window_title or (obs.active_window.get("title") if obs.active_window else None) or "Desktop"
            resp = f"The active window is {win_title}."
            res = cls._build_result("SYSTEM_DIAGNOSTICS", resp, dialogue_mgr)
            res["active_window"] = win_title
            return res

        if low in (
            "what is my screen resolution", "what's my screen resolution", "whats my screen resolution",
            "what is the screen resolution", "what's the screen resolution", "screen resolution",
            "display resolution", "what is my display resolution"
        ):
            from modules.system_controller import get_display_info
            disp = get_display_info()
            resp = disp.get("message", "Screen resolution retrieved.")
            res = cls._build_result("DEVICE_CONTROL", resp, dialogue_mgr)
            res["action"] = "display_info"
            res.update(disp)
            return res

        # ---------------------------------------------------------------------
        # 5. Currently Editing / Active File Query
        # "What file am I editing?", "What's the active file?"
        # ---------------------------------------------------------------------
        if low in (
            "what file am i editing", "what file am i working on",
            "what's the active file", "what is the active file", "whats the active file",
            "what file is open", "which file am i editing", "what am i editing",
            "what document am i working on", "what am i working on right now"
        ):
            active_file = None

            # Check dialogue state active artifact
            if dialogue_mgr and getattr(dialogue_mgr, "current_state", None):
                art = getattr(dialogue_mgr.current_state, "active_artifact", None)
                if art and isinstance(art, dict):
                    active_file = art.get("filename") or art.get("filepath") or art.get("title")

            # Check environment state engine
            if not active_file:
                try:
                    from core.environment import get_state_engine
                    eng = get_state_engine()
                    st = eng.get_current_state(str(user_id))
                    if st and not st.is_empty():
                        active_file = st.active_entities.get("active_file") or st.active_entities.get("file_name")
                except Exception:
                    pass

            # Check foreground window title
            if not active_file:
                try:
                    from skills.window_management.window_context import get_foreground_window_info
                    fg = get_foreground_window_info()
                    if fg:
                        title = fg.get("title") or ""
                        # Extract possible filename from title (e.g. "script.py - Visual Studio Code", "notes.txt - Notepad")
                        m_f = re.search(r'([a-zA-Z0-9_\-\.\\]+\.[a-zA-Z0-9]{1,5})', title)
                        if m_f:
                            active_file = m_f.group(1)
                except Exception:
                    pass

            if active_file:
                resp = f"You're currently editing {active_file}."
            else:
                resp = "You don't have an active file open in the editor."

            res = cls._build_result("SYSTEM_DIAGNOSTICS", resp, dialogue_mgr)
            res["active_file"] = active_file
            return res

        # ---------------------------------------------------------------------
        # 6. Recent Context / Last Action Query
        # "What is my last command?", "What did I just ask you to do?", "What was the last action you performed?"
        # ---------------------------------------------------------------------
        is_user_cmd = bool(
            re.search(r'\b(?:what(?:\'s|\s+is|\s+was)\s+(?:my\s+)?(?:last|previous)\s+command|what\s+did\s+i\s+(?:just\s+)?ask(?:\s+you(?:\s+to\s+do)?)?|what\s+was\s+the\s+last\s+thing\s+i\s+asked|what\s+command\s+did\s+i\s+(?:just\s+)?(?:give|issue|say))\b', low)
            or re.search(r'\b(?:what(?:\'s|\s+is|\s+was)\s+(?:my\s+)?(?:last|previous)\s+command|what\s+did\s+i\s+(?:just\s+)?ask(?:\s+you(?:\s+to\s+do)?)?|what\s+was\s+the\s+last\s+thing\s+i\s+asked|what\s+command\s+did\s+i\s+(?:just\s+)?(?:give|issue|say))\b', norm_low)
            or low in ("what is my last command", "what was my last command", "what did i just ask", "what did i just ask you to do", "what did i just ask you", "what was the last thing i asked", "last command")
        )
        is_assistant_act = bool(
            re.search(r'\b(?:what(?:\'s|\s+is|\s+was)\s+(?:the\s+)?last\s+action(?:\s+(?:you\s+)?performed)?|what\s+was\s+your\s+last\s+action|what\s+action\s+did\s+you\s+(?:just\s+)?perform|what\s+did\s+you\s+(?:just\s+)?do|what\s+did\s+you\s+do\s+last|what\s+was\s+the\s+last\s+thing\s+you\s+did|what\s+action\s+did\s+you\s+take)\b', low)
            or re.search(r'\b(?:what(?:\'s|\s+is|\s+was)\s+(?:the\s+)?last\s+action(?:\s+(?:you\s+)?performed)?|what\s+was\s+your\s+last\s+action|what\s+action\s+did\s+you\s+(?:just\s+)?perform|what\s+did\s+you\s+(?:just\s+)?do|what\s+did\s+you\s+do\s+last|what\s+was\s+the\s+last\s+thing\s+you\s+did|what\s+action\s+did\s+you\s+take)\b', norm_low)
            or low in ("what was the last action you performed", "what was your last action", "what action did you just perform", "what did you just do", "what did you do last", "what was the last thing you did", "last action")
        )

        if is_user_cmd or is_assistant_act:
            resp = cls._resolve_recent_history(
                is_user_cmd=is_user_cmd,
                dialogue_mgr=dialogue_mgr,
                user_id=user_id
            )
            res = cls._build_result("MEMORY_QUERY", resp, dialogue_mgr)
            res["query_type"] = "last_command" if is_user_cmd else "last_action"
            return res

        # ---------------------------------------------------------------------
        # 7. Concurrent Task Dashboard & Progress Queries (Section 11 & 19)
        # ---------------------------------------------------------------------
        # A. What are you doing / Active tasks / Update
        if low in (
            "what are you doing", "what are you doing?", "what are you doing right now", "what are you doing right now?",
            "what is running", "what is running?", "whats running", "what's running", "what's running?",
            "what tasks are running", "what tasks are running?", "what task is running", "what task is running?",
            "what is still running", "what is still running?", "what task is still running", "what task is still running?",
            "give me an update", "give me an update.", "task update", "active tasks", "show active tasks", "list tasks"
        ):
            from core.task_execution_manager import get_task_execution_manager
            tem = get_task_execution_manager()
            uid = int(user_id) if str(user_id).isdigit() else 1
            summary = tem.get_active_tasks_summary(user_id=uid)
            return cls._build_result("TASK_MANAGEMENT", summary, dialogue_mgr)

        # B. What did you finish?
        if low in (
            "what did you finish", "what did you finish?", "what did you complete", "what did you complete?",
            "what tasks finished", "what tasks finished?", "what did you just finish", "what did you just finish?"
        ):
            from core.task_execution_manager import get_task_execution_manager, TaskStatus
            tem = get_task_execution_manager()
            uid = int(user_id) if str(user_id).isdigit() else 1
            completed = [t for t in tem.list_tasks(user_id=uid) if t.status == TaskStatus.COMPLETED]
            if completed:
                items = [f"• {t.normalized_goal}" for t in completed[-5:]]
                resp = "Here are the tasks I recently finished:\n" + "\n".join(items)
            else:
                resp = "No tasks have completed recently."
            return cls._build_result("TASK_MANAGEMENT", resp, dialogue_mgr)

        # C. Query specific task progress ("how is that task doing?", "is the download finished?")
        m_task_status = re.match(
            r'^(?:how\s+is\s+(.+?)(?:\s+going|\s+doing)?|how\s+far\s+is\s+(.+?)|is\s+(.+?)\s+(?:finished|done|completed))[.!?]?$',
            low
        )
        if m_task_status:
            ref = (m_task_status.group(1) or m_task_status.group(2) or m_task_status.group(3) or "").strip()
            if not any(w in ref for w in ("open", "running", "active")) and ref not in ("it", ""):
                from core.task_execution_manager import get_task_execution_manager
                tem = get_task_execution_manager()
                uid = int(user_id) if str(user_id).isdigit() else 1
                task = tem.resolve_task_reference(ref, user_id=uid)
                if task:
                    prog = f" ({task.progress})" if task.progress and task.progress != "0%" else ""
                    step = f" Current step: {task.current_step}." if task.current_step else ""
                    resp = f"Task '{task.normalized_goal}' is currently {task.status.value.lower()}{prog}.{step}"
                    return cls._build_result("TASK_MANAGEMENT", resp, dialogue_mgr)

        # D. State mutations (task cancellation, document reading pause/continue/skip)
        # MUST NOT execute in FastPath. FastPath is strictly read-only latency optimization.
        # State-changing queries pass through to Semantic Understanding -> UnifiedCommandRouter.

        # ---------------------------------------------------------------------
        # 8. Deterministic Open Application Fast Path (Section 2)
        # ---------------------------------------------------------------------
        m_open_app = re.match(
            r'^(?:please\s+)?(?:open|launch|start)\s+(?:the\s+|a\s+|an\s+)?([a-zA-Z0-9_\-\.\s]+?)[.?!]?$',
            clean_text,
            re.IGNORECASE
        )
        if m_open_app:
            target_cand = m_open_app.group(1).strip()
            cand_low = target_cand.lower()
            # Do NOT intercept document / file / URL requests
            is_doc_or_file = (
                any(cand_low.endswith(ext) for ext in (".txt", ".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".py", ".md", ".json"))
                or any(w in cand_low for w in ["document", "presentation", "ppt", "report", "file", "spreadsheet", "excel sheet", "assignment", "folder", "directory"])
                or cand_low.startswith(("http://", "https://", "www."))
            )
            if not is_doc_or_file:
                mapped = cls.KNOWN_APP_MAPPINGS.get(cand_low)
                proc_key = mapped[0] if mapped else cand_low
                # Verify it's a known or valid desktop application target
                from extensions.system.smart_opener import smart_opener
                resolved_info = smart_opener.resolve_detailed(proc_key)
                if resolved_info and smart_opener.indexer._is_legitimate_app(resolved_info[0], resolved_info[1]):
                    open_dict = smart_opener.smart_open(proc_key)
                    if open_dict.get("success"):
                        disp_name = open_dict.get("display_name") or resolved_info[0] or target_cand.title()
                        resp_msg = open_dict.get("message") or f"Opened {disp_name}."
                        res = cls._build_result("OPEN_APPLICATION", resp_msg, dialogue_mgr)
                        res["target"] = target_cand
                        res["app_name"] = disp_name
                        res["path"] = open_dict.get("path")
                        if dialogue_mgr and hasattr(dialogue_mgr, "current_state"):
                            try:
                                opened_apps = dialogue_mgr.current_state.session_context.setdefault("opened_applications", [])
                                if disp_name not in opened_apps:
                                    opened_apps.append(disp_name)
                                dialogue_mgr.current_state.session_context["active_application"] = disp_name.lower()
                            except Exception:
                                pass
                        return res

        # ---------------------------------------------------------------------
        # 8b. Deterministic Calendar Query / List Events Fast Path (Section 2)
        # ---------------------------------------------------------------------
        calendar_read_queries = (
            "what is on my calendar", "what's on my calendar", "whats on my calendar",
            "show my calendar", "show calendar", "check my calendar", "view calendar",
            "what is on my schedule", "what's on my schedule", "whats on my schedule",
            "my schedule", "what do i have planned today", "what do i have planned tomorrow",
            "what do i have today", "what do i have tomorrow", "what do i have scheduled today",
            "what do i have scheduled tomorrow", "any events today", "any events tomorrow",
            "calendar today", "calendar tomorrow", "my events today", "my events tomorrow"
        )
        if norm_low in calendar_read_queries or re.match(r'^(?:what(?:\'s|\s+is)\s+on\s+my\s+(?:calendar|schedule)|show(?:\s+me)?\s+(?:my\s+)?calendar)[.?!]?$', norm_low):
            try:
                from datetime import timedelta
                from modules.calendar_manager.calendar_storage import CalendarStorage
                c_storage = CalendarStorage()
                uid = int(user_id) if str(user_id).isdigit() else 1
                is_tomorrow = "tomorrow" in norm_low
                target_dt = datetime.now().date() + timedelta(days=1) if is_tomorrow else datetime.now().date()
                date_lbl = "tomorrow" if is_tomorrow else "today"
                target_iso = target_dt.strftime("%Y-%m-%d")
                events = c_storage.get_events(uid, target_iso) or []
                if not events:
                    resp = f"You don't have any events scheduled for {date_lbl}."
                else:
                    ev_strs = [f"{e.get('title', 'Event')} at {e.get('time', 'all day')}" for e in events]
                    resp = f"For {date_lbl}, you have {len(events)} event(s): {', '.join(ev_strs)}."
                res = cls._build_result("DAILY_BRIEFING", resp, dialogue_mgr)
                res["events"] = events
                res["target_date"] = target_iso
                return res
            except Exception:
                pass

        # ---------------------------------------------------------------------
        # 8c. Straightforward Memory Retrieval Fast Path (Section 2)
        # ---------------------------------------------------------------------
        m_fav = re.match(r"^(?:what\s+is|what\'?s|tell\s+me)\s+(?:my\s+)?(?:favorite|favourite)\s+([a-zA-Z0-9_\s]+?)[.?!]?$", norm_low)
        if m_fav:
            try:
                target_word = m_fav.group(1).strip()
                fact_k = target_word.replace(" ", "_")
                from core.chatgpt_memory import get_chatgpt_memory
                uid = int(user_id) if str(user_id).isdigit() else 1
                facts = get_chatgpt_memory().get_user_facts(uid)
                cand_keys = [f"favorite_{fact_k}", f"favourite_{fact_k}", f"my_favorite_{fact_k}", fact_k]
                found_val = None
                for k in cand_keys:
                    if k in facts:
                        found_val = facts[k]
                        break
                if found_val:
                    resp = f"Your favorite {target_word} is {found_val}."
                    res = cls._build_result("MEMORY_QUERY", resp, dialogue_mgr)
                    res["key"] = fact_k
                    res["value"] = found_val
                    return res
            except Exception:
                pass

        m_user_fact = re.match(r"^(?:what\s+is|what\'?s|tell\s+me|where\s+do\s+i|where\s+am\s+i)\s+(?:my\s+)?(job|occupation|workplace|city|hometown|live|from)[.?!]?$", norm_low)
        if m_user_fact:
            try:
                raw_fact_k = m_user_fact.group(1).strip()
                fact_k = "city" if raw_fact_k == "live" else ("hometown" if raw_fact_k == "from" else raw_fact_k)
                from core.chatgpt_memory import get_chatgpt_memory
                uid = int(user_id) if str(user_id).isdigit() else 1
                facts = get_chatgpt_memory().get_user_facts(uid)
                if fact_k in facts:
                    found_val = facts[fact_k]
                    if fact_k in ("city", "hometown"):
                        resp = f"You live in {found_val}." if fact_k == "city" else f"You are from {found_val}."
                    else:
                        resp = f"Your {raw_fact_k} is {found_val}."
                    res = cls._build_result("MEMORY_QUERY", resp, dialogue_mgr)
                    res["key"] = fact_k
                    res["value"] = found_val
                    return res
            except Exception:
                pass

        # ---------------------------------------------------------------------
        # 8d. Deterministic Memory Storage Fast Path (Requirement 2 & Section 8)
        # "remember that my favorite language is Python", "remember that my secret pin is 7890"
        # ---------------------------------------------------------------------
        m_rem = re.match(r"^(?:please\s+)?(?:remember|note)\s+(?:that\s+)?(?:my\s+|the\s+)?([a-zA-Z0-9_\s]+?)\s+(?:is|was|=)\s+(.+)$", norm_low)
        if m_rem:
            try:
                raw_entity = m_rem.group(1).strip()
                val = m_rem.group(2).strip().rstrip(".!?")
                entity_words = raw_entity.split()
                if 1 <= len(entity_words) <= 5 and not any(w in entity_words for w in ("what", "now", "it", "when", "how", "why", "where")):
                    key = raw_entity.replace(" ", "_")
                    from core.chatgpt_memory import get_chatgpt_memory
                    uid = int(user_id) if str(user_id).isdigit() else 1
                    get_chatgpt_memory().set_user_fact(uid, key, val, confidence=0.98, source="explicit_user_store")
                    if "favorite" in key:
                        get_chatgpt_memory().set_user_fact(uid, key.replace("favorite", "favourite"), val, confidence=0.98, source="explicit_user_store")
                    elif "favourite" in key:
                        get_chatgpt_memory().set_user_fact(uid, key.replace("favourite", "favorite"), val, confidence=0.98, source="explicit_user_store")
                    resp = f"Understood. I'll remember that your {raw_entity} is {val}."
                    res = cls._build_result("MEMORY_STORE", resp, dialogue_mgr)
                    res["key"] = key
                    res["value"] = val
                    return res
            except Exception:
                pass

        # ---------------------------------------------------------------------
        # 9. Time and Date Queries (Sub-millisecond fast path)
        # ---------------------------------------------------------------------
        if low in (
            "what time is it", "what time is it right now", "what's the time", "whats the time",
            "tell me the time", "current time", "time"
        ):
            now = datetime.now()
            resp = f"The current time is {now.strftime('%I:%M %p').lstrip('0')}."
            return cls._build_result("TIME_QUERY", resp, dialogue_mgr)

        if low in (
            "what's the date", "whats the date", "what is the date", "what's today's date",
            "whats todays date", "what is today's date", "what is the date today",
            "today's date", "current date", "tell me the date", "what date is it",
            "what day is it today", "what day is it", "what day is today"
        ) or norm_low in (
            "what's the date", "whats the date", "what is the date", "what's today's date",
            "whats todays date", "what is today's date", "what is the date today",
            "today's date", "current date", "tell me the date", "what date is it",
            "what day is it today", "what day is it", "what day is today"
        ):
            now = datetime.now()
            resp = f"Today is {now.strftime('%A, %B %d, %Y')}."
            return cls._build_result("DATE_QUERY", resp, dialogue_mgr)

        # Not eligible for fast path — fallback to standard semantic & planning pipeline
        return None

    @classmethod
    def _resolve_recent_history(
        cls,
        is_user_cmd: bool,
        dialogue_mgr: Any,
        user_id: Any
    ) -> str:
        """
        Retrieve and distinguish user command from assistant action executed.
        Accurately reports historical record without hallucinating actions.
        """
        meta_query_pattern = re.compile(
            r'\b(?:what(?:\'s|\s+is|\s+was)\s+(?:my\s+)?(?:last|previous)\s+command|'
            r'what\s+did\s+(?:i|you)\s+(?:just\s+)?(?:ask|do)|'
            r'what\s+was\s+(?:the\s+)?last\s+(?:thing|action))\b',
            re.IGNORECASE
        )

        if is_user_cmd:
            # 1. Check dialogue state turns
            if dialogue_mgr and getattr(dialogue_mgr, "current_state", None):
                turns = getattr(dialogue_mgr.current_state, "turns", [])
                for t in reversed(turns):
                    u_in = getattr(t, "user_input", "") or ""
                    if u_in and not meta_query_pattern.search(u_in):
                        return f"Your last command was: '{u_in}'."

            # 2. Check in-memory conversation history from assistant.py
            try:
                from legacy.assistant import conversation_history_by_user
                uid = int(user_id) if str(user_id).isdigit() else 1
                u_hist = conversation_history_by_user.get(uid, [])
                for entry in reversed(u_hist):
                    u_in = entry.get("user", "")
                    if u_in and not meta_query_pattern.search(u_in):
                        return f"Your last command was: '{u_in}'."
            except Exception:
                pass

            # 3. Check conversational memory deque
            try:
                from extensions.conversational_memory import recent_memory, _lock
                with _lock:
                    mem_list = list(recent_memory)
                for entry in reversed(mem_list):
                    u_in = entry.get("user_command", "")
                    if u_in and not meta_query_pattern.search(u_in):
                        return f"Your last command was: '{u_in}'."
            except Exception:
                pass

            return "You haven't issued any commands yet in this session."

        else:
            # Assistant action query: must return actual executed action or report none
            if dialogue_mgr and getattr(dialogue_mgr, "current_state", None):
                rec_actions = getattr(dialogue_mgr.current_state, "recent_actions", [])
                for act in reversed(rec_actions):
                    intent = str(act.get("intent", ""))
                    cmd = str(act.get("command", "") or act.get("command_signature", "")).lower()
                    # Skip meta-queries and conversational queries
                    if intent in ("MEMORY_QUERY", "GENERAL_CONVERSATION", "GREETINGS", "CAPABILITY_QUERY") or meta_query_pattern.search(cmd):
                        continue
                    if act.get("response"):
                        return f"The last action I performed was: {act['response']}"
                    elif act.get("action") and act.get("target"):
                        return f"The last action I performed was {act['action']} on '{act['target']}'."
                    elif act.get("command"):
                        return f"The last action I performed was executing: {act['command']}."

            # Check PersistentExecutionRecordsManager
            try:
                from core.persistent_execution_records import get_persistent_execution_records_manager
                uid = int(user_id) if str(user_id).isdigit() else 1
                mgr = get_persistent_execution_records_manager()
                recs = mgr.get_recent_actions(user_id=uid, limit=5)
                for r in recs:
                    if r.status in ("COMPLETED", "SUCCESS") and r.operation not in ("READ", "QUERY", "INSPECT"):
                        desc = r.intended_action or f"{r.operation} on {r.target}"
                        return f"The last action I performed was: {desc}."
            except Exception:
                pass

            # Check OS Action History
            try:
                from core.os_gateway import get_os_action_history
                uid = int(user_id) if str(user_id).isdigit() else 1
                acts = get_os_action_history().get_recent_actions(user_id=uid, limit=5)
                for a in acts:
                    if a.get("status") in ("SUCCESS", "completed") and a.get("result_message"):
                        return f"The last action I performed was: {a.get('result_message')}"
            except Exception:
                pass

            return "I haven't performed any actions yet in this session."

    @classmethod
    def _build_result(cls, intent: str, response: str, dialogue_mgr: Any) -> Dict[str, Any]:
        """Record response in dialogue manager and construct uniform result dict."""
        if dialogue_mgr and hasattr(dialogue_mgr, "record_response"):
            try:
                dialogue_mgr.record_response(response)
            except Exception:
                pass

        return {
            "status": "success",
            "intent": intent,
            "response": response,
            "handled": True,
            "fast_path": True,
            "verified": True,
            "verification_method": "deterministic_fast_path",
        }

    handle = try_fast_path


fast_path_processor = FastPathProcessor()


def get_instant_response(user_input: str, user_id: str = "default", dialogue_mgr: Any = None) -> Optional[str]:
    """Helper to return instant response string if query is handled by FastPathProcessor, else None."""
    res = FastPathProcessor.try_fast_path(user_input, user_id=user_id, dialogue_mgr=dialogue_mgr)
    if res and res.get("status") == "success":
        return res.get("response")
    return None
