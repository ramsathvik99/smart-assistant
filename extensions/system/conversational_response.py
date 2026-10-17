"""
Conversational Response Composer

Transforms raw execution outcomes, LLM responses, and environment context
into natural, human-like spoken dialogue without destroying genuine answers.

Architecture:
  User Input + Subsystem Response + Intent + Context
                     ↓
      ConversationalResponseComposer
  - Categorizes interaction:
      * greeting
      * identity
      * general_conversation
      * explanation / direct_answer
      * recommendation
      * action_confirmation (ONLY for genuine completed actions)
      * action_failure
      * error_recovery
      * proactive_suggestion
      * silence
  - NEVER replaces genuine answers with "Done." or "Got it."
  - Preserves and polishes substantive answers for speech
                     ↓
         ConversationalResponse
                     ↓
            SpeechAdapter
                     ↓
             TTS Coordinator
"""

import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from extensions.system.speech_adapter import (
    adapt_for_speech,
    get_speech_adapter,
    sanitize_user_response,
)

logger = logging.getLogger("ConversationalResponse")


@dataclass
class ConversationalResponse:
    """Rich conversational response representation with full metadata for TTS and UI."""
    text: str
    speech_text: str
    response_type: str = "direct_answer"  # action_confirmation, direct_answer, general_conversation, greeting, identity, explanation, recommendation, clarification, error_recovery, proactive_suggestion, silence
    conversational_style: str = "casual"  # casual, concise, professional, reassuring, detailed, thoughtful
    urgency: str = "normal"               # normal, high, low
    proactive: bool = False
    interruption_allowed: bool = True
    suggested_next_action: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "speech_text": self.speech_text,
            "response_type": self.response_type,
            "conversational_style": self.conversational_style,
            "urgency": self.urgency,
            "proactive": self.proactive,
            "interruption_allowed": self.interruption_allowed,
            "suggested_next_action": self.suggested_next_action,
            "metadata": self.metadata,
        }

    def __str__(self) -> str:
        return self.speech_text or self.text or ""

    def lower(self) -> str:
        return str(self).lower()

    def __contains__(self, item: str) -> bool:
        return item in str(self)


class ConversationalResponseComposer:
    """Intelligent layer between subsystem output and TTS.
    
    Transforms text so the assistant sounds like a human speaking,
    rather than a synthetic reader reading a printed document.
    """

    # Action confirmations (Strictly reserved for completed mutating actions)
    ACTION_CONFIRMATIONS = [
        "Done.",
        "Yep, that's sorted.",
        "All set.",
        "Got it.",
        "That's done.",
    ]

    LAUNCH_CONFIRMATIONS = [
        "Yep, opening {target}.",
        "Opening {target} now.",
        "Got it, bringing up {target}.",
        "On it, launching {target}.",
    ]

    # Non-action intents that must NEVER receive a blind "Done." or "All set."
    NON_ACTION_INTENTS = {
        "GENERAL_CONVERSATION",
        "RAG_SEARCH",
        "MEMORY_QUERY",
        "TIME_QUERY",
        "DATE_QUERY",
        "WEATHER_QUERY",
        "RECOMMENDATION",
        "CALCULATOR",
        "TRANSLATION",
        "DAILY_BRIEFING",
        "VISUAL_SURFACE",
    }

    def __init__(self):
        self.speech_adapter = get_speech_adapter()
        self._rotation_index = 0

    def _create_conversational_response(
        self,
        decision: str,
        style: str,
        composed_text: str,
        user_input: str,
        intent_name: str,
        context: Dict[str, Any],
        action_result: Dict[str, Any],
        response_type: str,
        urgency: str = "normal",
        proactive: bool = False,
        suggested_next_action: Optional[str] = None,
    ) -> ConversationalResponse:
        sanitized_text = sanitize_user_response(composed_text, user_input)
        speech_text, meta = self.speech_adapter.adapt_for_speech(
            sanitized_text,
            response_type=response_type,
            intent=intent_name,
            user_input=user_input,
            action_result=action_result
        )
        self._log_pipeline(user_input, intent_name, context, action_result, decision, style, sanitized_text, speech_text)
        return ConversationalResponse(
            text=sanitized_text,
            speech_text=speech_text,
            response_type=response_type,
            conversational_style=style,
            urgency=urgency,
            proactive=proactive,
            suggested_next_action=suggested_next_action,
            metadata=meta,
        )

    def compose_response(
        self,
        user_input: str = "",
        raw_response: str = "",
        intent: Optional[str] = None,
        action_result: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        user_id: Any = 1,
        is_proactive: bool = False,
        **kwargs
    ) -> ConversationalResponse:
        """Takes raw command output and environment context to construct a human conversational response."""
        if action_result is None and "act_res" in kwargs:
            action_result = kwargs.pop("act_res")
        if not raw_response and "raw_resp" in kwargs:
            raw_response = kwargs.pop("raw_resp")
        if not raw_response and action_result:
            raw_response = str(action_result.get("response") or action_result.get("message") or "")
        if not user_input and "user_input" in kwargs:
            user_input = kwargs.pop("user_input")

        inp_clean = (user_input or "").strip()
        raw_resp = (raw_response or "").strip()
        ctx = context or {}
        act_res = action_result or {}
        intent_name = (intent or act_res.get("intent") or "").upper()

        decision = "direct_answer"
        style = "casual"
        urgency = "normal"
        next_action = None

        # ---------------------------------------------------------------------
        # 1. Proactive Events (Must meet strict relevance / silence threshold)
        # ---------------------------------------------------------------------
        if is_proactive:
            if not raw_resp or len(raw_resp) < 5:
                return ConversationalResponse(
                    text="",
                    speech_text="",
                    response_type="silence",
                    proactive=True,
                )
            composed_text = self._compose_proactive_response(raw_resp, ctx)
            return self._create_conversational_response(
                decision="proactive_suggestion",
                style="reassuring",
                composed_text=composed_text,
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type="proactive_suggestion",
                proactive=True,
            )

        # ---------------------------------------------------------------------
        # 2. Stop / Pause Commands
        # ---------------------------------------------------------------------
        if self._is_stop_command(inp_clean):
            return self._create_conversational_response(
                decision="action_confirmation",
                style="concise",
                composed_text="Stopping.",
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type="action_confirmation",
            )

        # ---------------------------------------------------------------------
        # 3. User Frustration / Error Recovery
        # ---------------------------------------------------------------------
        if self._is_user_frustrated(inp_clean):
            composed_text = self._compose_frustration_recovery(inp_clean, raw_resp)
            return self._create_conversational_response(
                decision="error_recovery",
                style="reassuring",
                composed_text=composed_text,
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type="error_recovery",
            )

        # ---------------------------------------------------------------------
        # 4. Failed Actions / Transparent Errors
        # ---------------------------------------------------------------------
        if act_res.get("status") in ("error", "failed") or act_res.get("uncertain"):
            composed_text = self._compose_failure_response(inp_clean, raw_resp, act_res)
            return self._create_conversational_response(
                decision="action_failure",
                style="reassuring",
                composed_text=composed_text,
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type="action_failure",
            )

        # ---------------------------------------------------------------------
        # 5. Greetings ("hello how Friday how are you feeling today")
        # ---------------------------------------------------------------------
        if self._is_greeting(inp_clean):
            composed_text = self._compose_greeting_response(inp_clean, raw_resp)
            return self._create_conversational_response(
                decision="greeting",
                style="casual",
                composed_text=composed_text,
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type="greeting",
            )

        # ---------------------------------------------------------------------
        # 6. Identity Queries ("Friday what is your name", "who are you")
        # ---------------------------------------------------------------------
        if self._is_identity_query(inp_clean):
            composed_text = self._compose_identity_response(inp_clean, raw_resp)
            return self._create_conversational_response(
                decision="identity",
                style="casual",
                composed_text=composed_text,
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type="identity",
            )

        # ---------------------------------------------------------------------
        # 7. Recommendation Queries ("What should I work on now?", "Suggest some games")
        # ---------------------------------------------------------------------
        if self._is_recommendation_request(inp_clean, intent_name):
            composed_text, next_action = self._compose_work_recommendation(inp_clean, raw_resp, user_id)
            return self._create_conversational_response(
                decision="recommendation",
                style="casual",
                composed_text=composed_text,
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type="recommendation",
                suggested_next_action=next_action,
            )

        # ---------------------------------------------------------------------
        # 8. Knowledge & Explanations ("what is Python", "explain ...", "why is ...")
        # ---------------------------------------------------------------------
        if self._is_explanation_request(inp_clean, intent_name):
            composed_text = self._compose_conversational_explanation(raw_resp)
            return self._create_conversational_response(
                decision="explanation",
                style="detailed",
                composed_text=composed_text,
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type="explanation",
            )

        # ---------------------------------------------------------------------
        # 9. Open Conversational Questions ("what do you want to do today")
        # ---------------------------------------------------------------------
        if self._is_conversational_question(inp_clean, intent_name):
            composed_text = self._compose_conversational_explanation(raw_resp)
            return self._create_conversational_response(
                decision="general_conversation",
                style="casual",
                composed_text=composed_text,
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type="general_conversation",
            )

        # ---------------------------------------------------------------------
        # 10. Weather Queries (Spoken rather than formal document reports)
        # ---------------------------------------------------------------------
        if intent_name == "WEATHER_QUERY" or "weather" in inp_clean.lower():
            composed_text = self._compose_weather_response(raw_resp)
            return self._create_conversational_response(
                decision="weather_answer",
                style="casual",
                composed_text=composed_text,
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type="direct_answer",
            )

        # ---------------------------------------------------------------------
        # 11. Application / Website Launch Commands ("open YouTube")
        # ---------------------------------------------------------------------
        if self._is_launch_command(inp_clean, intent_name):
            if (
                act_res.get("status") in ("error", "failed")
                or act_res.get("execution_success") is False
                or act_res.get("success") is False
                or act_res.get("verified") is False
            ):
                composed_text = self._compose_failure_response(inp_clean, raw_resp, act_res)
                return self._create_conversational_response(
                    decision="action_failure",
                    style="reassuring",
                    composed_text=composed_text,
                    user_input=inp_clean,
                    intent_name=intent_name,
                    context=ctx,
                    action_result=act_res,
                    response_type="action_failure",
                )
            composed_text = self._compose_launch_response(inp_clean, raw_resp, act_res=act_res)
            return self._create_conversational_response(
                decision="action_launch",
                style="concise",
                composed_text=composed_text,
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type="action_confirmation",
            )

        # ---------------------------------------------------------------------
        # 12. Volume / Media Control Commands ("increase volume by 20 percent")
        # ---------------------------------------------------------------------
        if self._is_volume_command(inp_clean):
            decision = "action_confirmation" if act_res.get("status") == "success" else "action_failure"
            style = "concise"
            if act_res.get("status") == "success" or "volume" in raw_resp.lower() and "failed" not in raw_resp.lower():
                composed_text = "Volume adjusted." if not raw_resp else raw_resp
                res_type = "action_confirmation"
            else:
                composed_text = "I couldn't adjust the volume that time."
                res_type = "action_failure"
            return self._create_conversational_response(
                decision=decision,
                style=style,
                composed_text=composed_text,
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type=res_type,
            )

        # ---------------------------------------------------------------------
        # 13. Genuine Completed Actions ONLY (File creation, window close, etc.)
        # ---------------------------------------------------------------------
        if self._is_true_action(inp_clean, intent_name, act_res, raw_resp):
            composed_text = raw_resp if (raw_resp and len(raw_resp) > 5) else self._compose_action_confirmation(inp_clean, raw_resp, ctx, user_id)
            return self._create_conversational_response(
                decision="action_confirmation",
                style="concise",
                composed_text=composed_text,
                user_input=inp_clean,
                intent_name=intent_name,
                context=ctx,
                action_result=act_res,
                response_type="action_confirmation",
            )

        # ---------------------------------------------------------------------
        # 14. Default for All Other Questions & Conversations: PRESERVE ANSWER
        # ---------------------------------------------------------------------
        composed_text = self._compose_conversational_explanation(raw_resp)
        return self._create_conversational_response(
            decision="direct_answer",
            style="casual",
            composed_text=composed_text,
            user_input=inp_clean,
            intent_name=intent_name,
            context=ctx,
            action_result=act_res,
            response_type="direct_answer",
        )

    # -------------------------------------------------------------------------
    # Intent and Utterance Classifiers
    # -------------------------------------------------------------------------

    def _is_stop_command(self, text: str) -> bool:
        low = text.lower().strip()
        return low in ("stop", "pause", "be quiet", "shut up", "hush", "cancel", "halt")

    def _is_greeting(self, text: str) -> bool:
        low = text.lower()
        if any(g in low for g in ["how are you", "how're you", "how are you doing", "how are you feeling", "how are you today"]):
            return True
        return bool(re.search(r'\b(?:hello|hi|hey|good\s+morning|good\s+afternoon|good\s+evening)\b', low))

    def _compose_greeting_response(self, inp: str, raw_resp: str) -> str:
        # If the LLM returned a substantive greeting response, polish it and preserve it
        if raw_resp and len(raw_resp) > 5 and not any(k in raw_resp.lower() for k in ("error", "unknown command")):
            s = raw_resp
            s = re.sub(r'I am functioning optimally and ready to assist you today\.?', "I'm doing well and ready to help.", s, flags=re.IGNORECASE)
            s = re.sub(r'How can I help you today\??', "What are we working on today?", s, flags=re.IGNORECASE)
            return s.strip()
        return "Hello! I'm doing well and ready to help. What are we working on today?"

    def _is_identity_query(self, text: str) -> bool:
        low = text.lower()
        return any(q in low for q in [
            "what is your name",
            "what's your name",
            "who are you",
            "what are you",
            "who am i talking to",
        ])

    def _compose_identity_response(self, inp: str, raw_resp: str) -> str:
        if raw_resp and len(raw_resp) > 4:
            return raw_resp.strip()
        return "I'm Friday, your desktop assistant."

    def _is_recommendation_request(self, inp: str, intent: str = "") -> bool:
        if intent in ("RECOMMENDATION", "RECOMMENDATIONS", "GAME_DISCOVERY"):
            return True
        low = inp.lower()
        if any(w in low for w in ("suggest", "recommend", "recommendation", "recommendations")):
            return True
        return any(phrase in low for phrase in [
            "what should i work on",
            "what should i do next",
            "what to do now",
            "what next",
            "what should i focus on",
            "recommend something for me",
            "what should we work on",
        ])

    def _is_conversational_question(self, inp: str, intent: str) -> bool:
        """Identifies open-ended conversational questions (e.g. 'what do you want to do today')."""
        if intent == "GENERAL_CONVERSATION":
            return True
        low = inp.lower()
        conversational_triggers = [
            "what do you want to do",
            "what would you like to do",
            "what do you think",
            "tell me a joke",
            "how's your day",
            "how is your day",
            "are you there",
            "do you have feelings",
            "what are your hobbies",
            "what were we",
            "what was i",
            "what were you",
            "what did we",
            "what project were we",
            "what project was i",
            "what are you doing",
        ]
        return any(t in low for t in conversational_triggers)

    def _is_explanation_request(self, inp: str, intent: str) -> bool:
        """Identifies knowledge questions and technical explanations."""
        if intent in ("RAG_SEARCH", "GENERAL_CONVERSATION"):
            low = inp.lower()
            return any(w in low for w in ["what is ", "what are ", "explain ", "why is ", "how does ", "tell me about "])
        low = inp.lower()
        return low.startswith(("what is ", "what are ", "explain ", "how does ", "why is "))

    def _is_volume_command(self, text: str) -> bool:
        low = text.lower()
        return "volume" in low and any(v in low for v in ["increase", "decrease", "raise", "lower", "turn up", "turn down", "mute", "set", "percent", "%"])

    def _is_launch_command(self, inp: str, intent: str) -> bool:
        if intent == "OPEN_APPLICATION":
            return True
        low = inp.lower()
        return low.startswith(("open ", "launch ", "start ", "bring up "))

    def _is_user_frustrated(self, text: str) -> bool:
        low = text.lower()
        if re.search(r"(?:can'?t|cannot)\s+get\s+(?:this|it|everything|\w+)(?:\s+thing)?\s+to\s+work", low):
            return True
        triggers = [
            "this isn't working",
            "not working",
            "it failed again",
            "why is this broken",
            "broken",
            "fix this",
            "stuck",
        ]
        return any(t in low for t in triggers)

    def _compose_frustration_recovery(self, inp: str, raw_resp: str) -> str:
        if raw_resp and not any(r in raw_resp.lower() for r in ("i don't understand", "error", "unknown")):
            return f"Yeah, I see what went wrong. {raw_resp.strip()}"
        return "Yeah, I see what went wrong. Let me help you fix that."

    def _is_true_action(self, inp: str, intent: str, act_res: Dict[str, Any], raw_resp: str) -> bool:
        """Strictly tests whether an interaction was a genuine completed mutating action."""
        # Non-action intents are NEVER action confirmations
        if intent in self.NON_ACTION_INTENTS:
            return False

        low_inp = inp.lower()
        # If the user input is a question, it is NOT an action confirmation
        if low_inp.startswith(("what", "who", "where", "when", "why", "how", "can you", "could you", "do you", "tell me", "explain")):
            return False

        # Read/List queries in action domains are NOT action confirmations
        if any(w in low_inp for w in ["show", "list", "read", "display", "get", "status"]):
            return False

        # Action intents with explicit success
        action_intents = {
            "FILE_OPERATIONS",
            "POWER_ACTION",
            "DOCUMENT_GENERATION",
            "NOTES",
            "REMINDERS",
            "SMART_HOME",
            "TASK_MANAGEMENT",
            "DEVICE_CONTROL",
            "WINDOW_CONTEXT",
            "AUDIO_DEVICES",
            "UNDO",
            "MEMORY_STORE",
        }

        low_resp = raw_resp.lower()
        has_action_phrase = any(w in low_resp for w in [
            "successfully created",
            "has been created",
            "successfully saved",
            "successfully opened",
            "has been launched",
            "closed successfully",
            "operation completed",
            "request has been completed",
            "file created",
            "document created",
            "reminder set",
        ])

        if intent in action_intents and (act_res.get("status") == "success" or has_action_phrase):
            # Only confirm if imperative verb was used
            imperative_verbs = ("create", "make", "delete", "remove", "close", "kill", "save", "write", "set", "turn", "shut", "reboot", "restart")
            if any(low_inp.startswith(v) for v in imperative_verbs) or has_action_phrase:
                return True

        return False

    def _compose_launch_response(self, inp: str, raw_resp: str, act_res: Optional[Dict[str, Any]] = None) -> str:
        target = None
        if act_res:
            target = (
                act_res.get("display_name")
                or act_res.get("target")
                or act_res.get("app_name")
                or act_res.get("application")
            )
        if not target or str(target).strip().lower() in ("it", "app", "application", "the app", "the application"):
            m = re.match(r'^(?:open|launch|start|bring up)\s+(?:the\s+)?(.+?)(?:\s+app|\s+application)?[\.!\?]?$', inp.strip(), re.IGNORECASE)
            target = m.group(1).strip().rstrip('.?!') if m else "the requested application"

        target_str = str(target).strip()
        target_low = target_str.lower()
        if target_low in ("it", "the it"):
            target_str = "the application"
        elif "youtube" in target_low:
            target_str = "YouTube"
        elif "vscode" in target_low or "vs code" in target_low or target_low == "code":
            target_str = "VS Code"
        elif "chrome" in target_low or "google chrome" in target_low:
            target_str = "Chrome"
        elif "terminal" in target_low or "powershell" in target_low or "cmd" in target_low:
            target_str = "Terminal"
        elif "file explorer" in target_low or "explorer" in target_low:
            target_str = "File Explorer"
        else:
            target_str = target_str.title()

        tmpl = self.LAUNCH_CONFIRMATIONS[self._rotation_index % len(self.LAUNCH_CONFIRMATIONS)]
        self._rotation_index += 1
        return tmpl.format(target=target_str)

    def _compose_action_confirmation(self, inp: str, raw_resp: str, ctx: Dict[str, Any], user_id: Any) -> str:
        conf = self.ACTION_CONFIRMATIONS[self._rotation_index % len(self.ACTION_CONFIRMATIONS)]
        self._rotation_index += 1

        suggestion = self._get_contextual_follow_up(ctx, user_id)
        if suggestion:
            return f"{conf} {suggestion}"

        return conf

    def _compose_failure_response(self, inp: str, raw_resp: str, act_res: Dict[str, Any]) -> str:
        err = act_res.get("failure_reason") or act_res.get("error") or raw_resp
        err_type = act_res.get("error_type") or act_res.get("failure_category")
        err_low = str(err).lower()
        logger.info(f"[STRUCTURED_FAILURE] type={err_type} reason='{err}' input='{inp}'")
        if err_type == "temporal_failure" or "already passed" in err_low or "past" in err_low:
            return str(act_res.get("message") or act_res.get("speech_response") or err)
        if err_type == "intent_failure":
            return "I couldn't identify what action to take for that request."
        if err_type == "routing_failure":
            return "I couldn't route that request to a handler."
        if err_type == "validation_failure":
            return f"That request couldn't be validated: {err}."
        if err_type == "capability_unavailable":
            return "That capability isn't currently available on this machine."
        if "permission" in err_low or "administrator" in err_low:
            return "Windows denied permission for that. I can request administrator elevation if you'd like to continue."
        if "not found" in err_low:
            return "I could not locate that item on your system. Want me to check again with a different name?"
        if act_res.get("speech_response"):
            return act_res["speech_response"]
        if act_res.get("message"):
            return act_res["message"]
        return f"I encountered an issue executing that request: {err}."

    def _compose_work_recommendation(self, inp: str, raw_resp: str, user_id: Any) -> Tuple[str, Optional[str]]:
        low = inp.lower()
        is_media_query = any(w in low for w in ("movie", "movies", "film", "films", "game", "games", "song", "songs", "music", "book", "books", "show", "shows", "series"))
        if not is_media_query:
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager
                dm = get_dialogue_manager(user_id=int(user_id) if (user_id and str(user_id).isdigit()) else None)
                active_goal = dm.get_active_goal()
                if active_goal:
                    title = active_goal.get("title") or active_goal.get("topic") or "your project"
                    next_act = active_goal.get("next_action") or active_goal.get("next_recommended_action")
                    if next_act:
                        msg = f"You've been working on {title} for a while. I'd take a short break before continuing—it'll probably help more than pushing through. When you're ready, the next step is {next_act}."
                        return msg, next_act
                    return f"You're currently in the middle of {title}. I'd recommend finishing that up before starting something new.", title
            except Exception:
                pass

        if raw_resp and not raw_resp.startswith("❌"):
            return raw_resp, None

        return "You don't have any pressing deadlines right now. I'd review your recent documents or take a quick break.", None

    def _compose_weather_response(self, raw_resp: str) -> str:
        s = raw_resp
        s = re.sub(r'^according to [^,]+,\s*', '', s, flags=re.IGNORECASE)
        s = re.sub(r'the weather in [a-zA-Z\s]+ is currently', "it's around", s, flags=re.IGNORECASE)
        s = re.sub(r'the current weather is', "it's around", s, flags=re.IGNORECASE)
        s = re.sub(r'with conditions of', 'and', s, flags=re.IGNORECASE)
        s = re.sub(r'with conditions being', 'and', s, flags=re.IGNORECASE)
        if not s.lower().startswith("it's"):
            s = f"It's {s.lstrip()}"
        return s.capitalize()

    def _compose_proactive_response(self, raw_resp: str, ctx: Dict[str, Any]) -> str:
        clean = raw_resp.strip()
        if not clean.lower().startswith(("hey", "by the way", "just a heads up", "reminder")):
            clean = f"Hey, {clean[0].lower() + clean[1:]}" if clean else ""
        return clean

    def _compose_conversational_explanation(self, raw_resp: str) -> str:
        s = raw_resp
        s = re.sub(r'here are the available options:?', "You've got a few options here:", s, flags=re.IGNORECASE)
        s = re.sub(r'here is the information:?', "Here's what I found:", s, flags=re.IGNORECASE)
        s = re.sub(r'the following (?:steps|options|items) are available:?', "You've got a few choices here:", s, flags=re.IGNORECASE)
        return s

    def _get_contextual_follow_up(self, ctx: Dict[str, Any], user_id: Any) -> Optional[str]:
        try:
            from extensions.dialogue_state_manager import get_dialogue_manager
            dm = get_dialogue_manager(user_id=int(user_id) if (user_id and str(user_id).isdigit()) else None)
            active_goal = dm.get_active_goal()
            if active_goal:
                rem_subtasks = active_goal.get("remaining_subtasks") or []
                if rem_subtasks and random.random() < 0.35:
                    return f"By the way, you've still got '{rem_subtasks[0]}' pending. Want me to handle it?"
        except Exception:
            pass
        return None

    def _log_pipeline(
        self,
        user_input: str,
        intent: str,
        context: Dict[str, Any],
        action_result: Dict[str, Any],
        decision: str,
        style: str,
        final_response: str,
        speech_text: str,
    ) -> None:
        print(f"[CONVERSATIONAL PIPELINE]")
        print(f"  USER INPUT           : {user_input[:60]!r}")
        print(f"  INTENT               : {intent}")
        print(f"  CONVERSATIONAL DECISION : {decision} (Style: {style})")
        print(f"  FINAL RESPONSE       : {final_response[:60]!r}")
        print(f"  SPEECH TEXT          : {speech_text[:60]!r}")


# Global Singleton
_conversational_composer = ConversationalResponseComposer()

def get_conversational_composer() -> ConversationalResponseComposer:
    return _conversational_composer

def compose_conversational_response(
    user_input: str,
    raw_response: str,
    intent: Optional[str] = None,
    action_result: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
    user_id: Any = 1,
    is_proactive: bool = False,
) -> ConversationalResponse:
    return _conversational_composer.compose_response(
        user_input=user_input,
        raw_response=raw_response,
        intent=intent,
        action_result=action_result,
        context=context,
        user_id=user_id,
        is_proactive=is_proactive,
    )


__all__ = [
    "ConversationalResponse",
    "ConversationalResponseComposer",
    "get_conversational_composer",
    "compose_conversational_response",
    "sanitize_user_response",
]

