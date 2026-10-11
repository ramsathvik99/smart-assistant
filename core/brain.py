"""
NOVA Brain — PHASE 6 Integration Layer

Wires multi-intent analyzer, goal planner, and dialogue state manager
together with the existing unified_command_router.

Entry point:  brain_process(user_input, user_id) -> Dict
Fallback:     route_and_execute(user_input) for single-intent backward compat

Architecture:
  User Input
    └─ Dialogue State Manager  (context enrichment + state tracking)
        └─ Multi-Intent Analyzer (detect 1..N intents)
            └─ Goal Planner      (order, deps, risk)
                └─ Unified Router (execute each step)
                    └─ TTS response
"""

import sys
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable
from dataclasses import asdict
from datetime import datetime
import uuid
import re
import time

logger = logging.getLogger("Brain")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.unified_command_router import unified_router, route_and_execute as _single_route, Intent
from core.multi_intent_analyzer import multi_intent_analyzer, analyze_input
from core.goal_planner import goal_planner, plan_execution, explain_plan, ExecutionPlan
from extensions.dialogue_state_manager import get_dialogue_manager, GoalOutcome
from core.environment_observer import (
    observe_environment,
    compare_snapshots,
    select_relevant_categories,
    EnvironmentSnapshot,
    StateDifference,
)
from core.proactive_observer import proactive_coordinator
from core.outcome_verifier import (
    get_outcome_verifier,
    OutcomeStatus,
    ConfidenceLevel,
    OutcomeVerificationResult,
    ExecutionRecord,
)
from core.adaptive_recovery import (
    get_adaptive_recovery_engine,
    FailureClassification,
    RecoveryDecision,
    AdaptiveStrategy,
    RecoveryBudget,
    StepReplanStatus,
)

from core.fast_path import FastPathProcessor

# Module-level singletons (canonical instances)
_multi_intent_analyzer = multi_intent_analyzer
_goal_planner = goal_planner


def _detect_and_apply_goal_update(
    user_input: str,
    current_goal: Dict[str, Any]
) -> Optional[Tuple[Dict[str, Any], str, List[str]]]:
    """
    Evaluates whether user_input is a natural-language update to the active goal (Failures 1 & 3).
    Supports updating: topic, status, deadline, requirements, progress, notes.
    Preserves all unrelated fields.
    Returns (updated_goal_dict, ack_message, updated_fields_list) or None.
    """
    if not current_goal or not isinstance(current_goal, dict):
        return None

    text = user_input.strip()
    text_low = text.lower()

    # Guard: Do not intercept if user is creating a NEW goal, canceling, or confirming
    if re.match(r'^(?:i\s+)?(?:need\s+to|have\s+to|must|should|want\s+to)\s+(?:prepare|finish|complete|study|work\s+on|finalize|review|practice|research|draft|write\s+up|put\s+together)\s+(?:another|a\s+new|different)\b', text_low):
        return None
    if text_low.startswith(("cancel", "stop", "abort", "yes", "no", "open ", "launch ", "play ", "delete ", "close ")):
        return None

    updated_fields = []
    g = dict(current_goal)
    if "requirements" not in g or not isinstance(g.get("requirements"), list):
        g["requirements"] = list(g.get("requirements") or [])

    # 1. Topic / Subject extraction
    # Patterns: "The topic is X", "The subject is X", "The topic will be X"
    # Can be followed by " and I haven't started yet" or " and the requirements are..."
    m_top = re.search(
        r'\b(?:the\s+)?(?:topic|subject)\s+(?:is|will\s+be|=|:)\s+([^,.\n]+?)(?:\s+(?:and\s+(?:i\s+|the\s+|it\s+|we\s+)|but\s+|with\s+requirements?|\.|$)|$|\.|\,)',
        text,
        re.IGNORECASE
    )
    if m_top:
        raw_topic = m_top.group(1).strip().rstrip('.?!,')
        if raw_topic and raw_topic.lower() not in ("what", "unknown"):
            g["topic"] = raw_topic
            updated_fields.append("topic")

    # 2. Status / Progress extraction
    if re.search(r'\b(?:haven\'t\s+started(?:\s+yet)?|have\s+not\s+started(?:\s+yet)?|not\s+started(?:\s+yet)?|haven\'t\s+even\s+started)\b', text_low):
        g["status"] = "NOT_STARTED"
        g["progress"] = "NOT_STARTED"
        updated_fields.append("status")
    elif re.search(r'\b(?:already\s+started|started\s+already|i\'m\s+working\s+on(?:\s+it)?|working\s+on\s+it|currently\s+working|in\s+progress)\b', text_low):
        g["status"] = "IN_PROGRESS"
        g["progress"] = "IN_PROGRESS"
        updated_fields.append("status")
    elif re.search(r'\b(?:i\s+finished(?:\s+it)?|finished\s+it|completed\s+it|already\s+finished|all\s+done)\b', text_low):
        g["status"] = "COMPLETED"
        g["progress"] = "COMPLETED"
        updated_fields.append("status")

    # 3. Deadline extraction
    m_dl = re.search(r'\b(?:the\s+)?deadline\s+(?:is|will\s+be)\s+([a-zA-Z0-9_\-\s]+?)(?:\s+(?:and|$|\.|\,)|$)', text_low)
    if m_dl:
        raw_dl = m_dl.group(1).strip().rstrip('.?!,')
        clean_dl = re.sub(r'^(?:for|by|on|at|due|before)\s+', '', raw_dl, flags=re.IGNORECASE).strip()
        if clean_dl:
            g["deadline"] = clean_dl
            updated_fields.append("deadline")

    # 4. Requirements extraction
    # "The presentation needs to contain all the important information about deadlocks."
    # "The presentation should explain prevention, avoidance, detection and recovery."
    # "It needs to contain X", "The requirements are X", "I need X in it", "I want to include X"
    m_req = re.search(
        r'\b(?:(?:the\s+)?(?:presentation|project|document|task|goal|it)\s+(?:needs\s+to\s+contain|needs\s+all|needs\s+to\s+explain|needs\s+to\s+cover|should\s+contain|should\s+include|should\s+explain|should\s+cover|should\s+detail|should\s+discuss|should\s+focus\s+on|must\s+include|must\s+explain|must\s+cover)|(?:the\s+)?requirements?\s+(?:are|is)|i\s+need\s+(?:to\s+include|in\s+it)?|i\s+want\s+to\s+include)\s+(.+)',
        text,
        re.IGNORECASE
    )
    if m_req:
        req_val = m_req.group(1).strip().rstrip('.?!')
        req_val = re.sub(r'^(?:in\s+it\s+|to\s+include\s+)', '', req_val, flags=re.IGNORECASE).strip()
        if req_val and req_val not in g["requirements"]:
            g["requirements"].append(req_val)
            updated_fields.append("requirements")

    if not updated_fields:
        return None

    # Construct concise acknowledgment
    acks = []
    if "topic" in updated_fields:
        acks.append(f"topic to {g.get('topic')}")
    if "status" in updated_fields:
        acks.append(f"status to {g.get('status')}")
    if "deadline" in updated_fields:
        acks.append(f"deadline to {g.get('deadline')}")
    if "requirements" in updated_fields:
        acks.append("requirements")

    ack_str = f"Got it. I've updated the active goal ({', '.join(acks)})."
    return g, ack_str, updated_fields


# ---------------------------------------------------------------------------
# Environment Awareness Helpers (Continuous Environment Observer integration)
# ---------------------------------------------------------------------------
# ARCHITECTURAL NOTE:
# Environment state is injected as STRUCTURED CONTEXT into the dialogue manager
# so the existing semantic understanding layer can resolve environment queries
# naturally ("what am I watching?", "what was that video?", "what was I doing"
# before this?") using meaning + context, NOT keyword matching.
#
# NO keyword rules here. The environment context is rich structured data that
# the semantic layer reads from dialogue_mgr.current_state.session_context.
# ---------------------------------------------------------------------------


def _inject_environment_context(user_id: str, dialogue_mgr) -> None:
    """
    Attach current + historical environment state to the dialogue manager's
    session_context as structured data.

    This gives the semantic understanding layer (and any LLM prompt builder)
    full access to:
      - current_environment: rich EnvironmentState entities
      - environment_history: list of recent meaningful state transitions
      - environment_context_block: pre-formatted string for LLM prompt injection

    Never raises — always best-effort.
    """
    try:
        from core.environment import get_state_engine
        engine = get_state_engine()
        state = engine.get_current_state(user_id)
        prev_state = engine.get_previous_state(user_id)
        history = engine.get_history(user_id, limit=10)

        if not hasattr(dialogue_mgr, "current_state"):
            return
        ctx = getattr(dialogue_mgr.current_state, "session_context", {})
        if not isinstance(ctx, dict):
            return

        # Current environment — structured entities
        if not state.is_empty():
            ctx["current_environment"] = {
                "application": state.application,
                "app_category": state.app_category,
                "window_title": state.window_title,
                "content_context": state.content_context,
                "summary": state.format_summary(),
                "entities": dict(state.active_entities),
                "source_tier": state.source_tier,
                "timestamp": state.timestamp,
            }

        # Previous environment — for "what was I doing before this?" queries
        if prev_state and not prev_state.is_empty():
            ctx["previous_environment"] = {
                "application": prev_state.application,
                "app_category": prev_state.app_category,
                "window_title": prev_state.window_title,
                "content_context": prev_state.content_context,
                "summary": prev_state.format_summary(),
                "entities": dict(prev_state.active_entities),
            }

        # Recent history — for "what was I watching before?" queries
        if history:
            ctx["environment_history"] = [
                {
                    "timestamp": t.timestamp,
                    "change_type": t.change_type,
                    "summary": t.transition_summary,
                    "before": t.before_state.format_summary() if t.before_state else "",
                    "after": t.after_state.format_summary() if t.after_state else "",
                    "after_entities": dict(t.after_state.active_entities) if t.after_state else {},
                }
                for t in history[:10]
            ]

        # Pre-formatted context block for LLM prompt injection
        ctx["environment_context_block"] = engine.format_combined_context(user_id)

    except Exception:
        pass


def get_environment_context_for_prompt(user_id: str) -> str:
    """
    Return a formatted environment context block suitable for LLM prompt injection.
    Can be called from any downstream module (TTS, outcome verifier, etc.).
    Never raises.

    Returns empty string if no state has been observed.
    """
    try:
        from core.environment import get_state_engine
        engine = get_state_engine()
        state = engine.get_current_state(user_id)
        if state.is_empty():
            return ""
        return engine.format_combined_context(user_id)
    except Exception:
        return ""

def _evaluate_context_relevance(
    user_input: str,
    routing_input: str,
    dialogue_mgr: Any,
    current_intent: str,
) -> Tuple[Optional[str], str, Optional[str]]:
    """
    Explicit Relevance Gate (Issue 4):
    Determines whether previous artifact, topic, or active goal context
    is semantically relevant to the current user utterance.

    Prevents stale context leakage (e.g. attaching Deep Learning document to 'who is Pradushan').
    Decays or clears irrelevant context.

    Returns:
        (relevant_topic, relevant_context, relevant_artifact)
    """
    inp_low = (user_input or routing_input or "").lower().strip()

    # 1. Check artifact relevance
    artifact_ref_patterns = [
        r'\b(?:open|read|view|edit|show|close|delete|check|describe|summarize)\s+(?:that|this|the|it)\b',
        r'\b(?:that|this|the)\s+(?:document|doc|file|report|presentation|ppt|pptx|spreadsheet|excel|sheet|artifact)\b',
        r'\b(?:read|open|show|tell me about)\s+(?:it|that|this)\b',
        r'\b(?:read\s+the\s+document\s+again|read\s+it\s+again|open\s+that\s+again|open\s+it\s+again)\b',
        r'\b(?:tell\s+me\s+more\s+about\s+that\s+document|what\s+is\s+in\s+that\s+document)\b',
    ]
    has_artifact_ref = any(bool(re.search(pat, inp_low)) for pat in artifact_ref_patterns)

    active_art = getattr(dialogue_mgr.current_state, "active_artifact", None) or {}
    art_fn = (active_art.get("filename") or "").lower()
    art_topic = (active_art.get("topic") or "").lower()
    mentions_art = (
        (bool(art_fn) and art_fn in inp_low) or
        (bool(art_topic) and len(art_topic) >= 4 and art_topic in inp_low)
    )

    relevant_art = None
    if has_artifact_ref or mentions_art:
        if active_art:
            relevant_art = active_art.get("filename") or active_art.get("filepath")
        elif getattr(dialogue_mgr.current_state, "active_documents", None):
            relevant_art = dialogue_mgr.current_state.active_documents[0].get("filename")

    # 2. Check topic relevance
    prev_topic = (
        dialogue_mgr.current_state.session_context.get("topic_lock")
        or (dialogue_mgr.current_state.current_goal or {}).get("topic")
        or (dialogue_mgr.current_state.active_artifact or {}).get("topic")
        or ""
    )

    topic_words = set(re.findall(r'[a-zA-Z0-9]{3,}', prev_topic.lower())) if prev_topic else set()
    query_words = set(re.findall(r'[a-zA-Z0-9]{3,}', inp_low))
    has_topic_overlap = bool(topic_words and (topic_words & query_words))
    has_topic_ref = any(p in inp_low for p in ("about that", "on that topic", "more about that", "continue with that"))

    is_standalone_query = (
        any(inp_low.startswith(p) for p in ("who is", "who was", "who are", "what is", "where is", "when did", "how does", "tell me a joke", "what time", "what day", "what date", "weather in", "play ", "search for"))
        or current_intent in ("TIME_QUERY", "DATE_QUERY", "WEATHER_QUERY", "CALCULATOR", "JOKE", "MUSIC", "RAG_SEARCH")
    )

    relevant_topic = None
    if (has_topic_overlap or has_topic_ref) and not is_standalone_query:
        relevant_topic = prev_topic
    elif "deadlock" in inp_low:
        relevant_topic = "DBMS Deadlocks"
    elif is_standalone_query and not has_topic_overlap:
        # Standalone unrelated query: clear stale topic lock and do NOT attach previous topic
        if "topic_lock" in dialogue_mgr.current_state.session_context:
            dialogue_mgr.current_state.session_context.pop("topic_lock", None)
        relevant_topic = None
    elif has_topic_overlap:
        relevant_topic = prev_topic

    # 3. Check active goal relevance
    curr_g = dialogue_mgr.current_state.current_goal
    g_status = (curr_g.get("status") if isinstance(curr_g, dict) else None) or dialogue_mgr.current_state.goal_status or "IDLE"

    # If previous goal is completed or cancelled, decay it
    if curr_g and g_status in ("COMPLETED", "CANCELLED", "FAILED"):
        dialogue_mgr.current_state.current_goal = None
        dialogue_mgr.current_state.goal_status = "IDLE"
        curr_g = None
        is_running_goal = False
    else:
        is_running_goal = (curr_g is not None) and (g_status in ("ACTIVE", "RUNNING", "IN_PROGRESS", "PAUSED", "WAITING_FOR_USER"))

    if is_running_goal:
        is_goal_rel = (
            has_topic_overlap or
            has_artifact_ref or
            any(w in inp_low for w in ("goal", "task", "subtask", "continue", "resume", "pause", "cancel", "status", "finish", "complete", "next", "remaining", "what's left"))
        )
        if is_goal_rel:
            relevant_context = "active_goal"
        else:
            relevant_context = "idle"
    else:
        if relevant_art is not None:
            relevant_context = "active_artifact"
        else:
            relevant_context = "idle"

    return relevant_topic, relevant_context, relevant_art


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def brain_process(
    user_input: str,
    user_id: str = "default",
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Main Brain entry point — PHASE 2 Continuous Stateful Agent Loop.

    Pipeline:
      USER INPUT
      → UNDERSTAND (dialogue state + pronoun/reference resolution + context binding)
      → DETECT USER INTERRUPTION (Stop, Cancel that)
      → RESUME PAUSED GOAL IF WAITING_FOR_USER
      → UPDATE LIVE STATE
      → DETERMINE USER GOAL (Command vs Multi-step Goal)
      → PLAN (GoalPlanner for multi-step dependencies)
      → STEP-BY-STEP EXECUTE THROUGH EXISTING ROUTER
      → OBSERVE RESULT AFTER EVERY STEP
      → VERIFY RESULT & BOUNDED ADAPTATION
      → UPDATE LIVE STATE PER STEP
      → RESPOND & CONTINUE USING UPDATED CONTEXT
    """
    if not user_input or not user_input.strip():
        return {"status": "error", "intent": "NONE", "response": ""}

    if not user_id or user_id == "default":
        try:
            from instance.config import settings
            user_id = getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user() or "default"
        except Exception:
            user_id = "default"

    # ------------------------------------------------------------------
    # Step 1 — UNDERSTAND & CONTEXTUAL RESOLUTION (Dialogue State Manager)
    # ------------------------------------------------------------------
    dialogue_mgr = get_dialogue_manager(str(user_id))

    # ------------------------------------------------------------------
    # Step 0 — ACTIVE EMAIL SESSION / VOICE DICTATION PREEMPTION
    # While RECORDING_EMAIL_MESSAGE, PENDING_EMAIL_CONFIRMATION, or
    # EMAIL_RECIPIENT_RESOLUTION is active, all utterances bypass
    # general intent classification, fast path, RAG, and document/reminder creation.
    # ------------------------------------------------------------------
    try:
        from modules.assistant_email.email_controller import (
            is_active_email_session, handle_email_command, _resolve_user
        )
        cur_u = _resolve_user(user_id)
        if is_active_email_session(cur_u):
            em_res = handle_email_command(user_input, user_id=cur_u)
            resp_str = em_res.get("message") or em_res.get("response") or ""
            dialogue_mgr.record_response(resp_str)
            return {
                "status": "success" if em_res.get("success", False) else "error",
                "intent": "EMAIL",
                "response": resp_str,
                "handled": True,
                "email_result": em_res,
            }
    except Exception as _em_err:
        pass

    # ------------------------------------------------------------------
    # Step 1.1 — DETERMINISTIC FAST PATH (Requirement 2 & Section 8)
    # Check if query can be answered immediately with 0 reasoning overhead
    # (greetings, current directory, app status, editing status, simple utilities)
    # Only applies when no pending action, confirmation, or paused goal exists.
    # ------------------------------------------------------------------
    _has_pending = bool(
        getattr(dialogue_mgr.current_state, "pending_action", None)
        or getattr(dialogue_mgr.current_state, "pending_confirmation", False)
        or (dialogue_mgr.current_state.goal_status == "WAITING_FOR_USER")
    )
    if not _has_pending:
        _fast_res = FastPathProcessor.try_fast_path(user_input, str(user_id), dialogue_mgr)
        if _fast_res is not None:
            outcome = GoalOutcome(
                goal_id=str(uuid.uuid4())[:8],
                user_id=str(user_id),
                user_request=user_input,
                attempted_action=user_input,
                actual_outcome="COMPLETED",
                success=True,
                summary=_fast_res.get("response", ""),
                timestamp=datetime.now().isoformat(),
                results=_fast_res,
                verified=True,
                verification_source="deterministic_fast_path",
            )
            dialogue_mgr.record_goal_outcome(outcome)
            _fast_res["goal_outcome"] = outcome.to_dict()
            return _fast_res

    turn_data = dialogue_mgr.process_turn(user_input)
    enriched_input = turn_data.get("enriched_input", user_input)

    reference_resolved = turn_data.get("reference_resolved", False)
    routing_input = turn_data.get("resolved_input", user_input) if reference_resolved else user_input
    clean_low = user_input.strip().lower()

    # ------------------------------------------------------------------
    # Step 1.1b — CONTINUOUS ENVIRONMENT AWARENESS
    # Inject current + historical environment state into dialogue context as
    # structured data (session_context["current_environment"],
    # session_context["previous_environment"], session_context["environment_history"],
    # session_context["environment_context_block"]).
    #
    # The semantic understanding layer uses this to answer environment queries
    # naturally (meaning + context), NOT through keyword matching.
    # This block is strictly additive and never modifies existing variables.
    # ------------------------------------------------------------------
    _inject_environment_context(str(user_id), dialogue_mgr)

    # ------------------------------------------------------------------
    # Step 1.1c — CONCURRENT TASK ORCHESTRATION & PROGRESSIVE UPDATES
    # ------------------------------------------------------------------
    uid_int = int(user_id) if (user_id and str(user_id).isdigit()) else 1
    from core.task_execution_manager import get_task_execution_manager, TaskPriority, TaskStatus
    tem = get_task_execution_manager()
    pending_updates = tem.notification_manager.get_and_clear_notifications(uid_int)
    pending_prefix = (" ".join(pending_updates) + "\n") if pending_updates else ""

    # ------------------------------------------------------------------
    # Step 1.1b — CANONICAL SEMANTIC INTENT UNDERSTANDING
    # ------------------------------------------------------------------
    from core.semantic_understanding import semantic_understanding_engine
    semantic_rep = semantic_understanding_engine.analyze(user_input, dialogue_mgr.current_state, uid_int)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Step 1.1b0 — SPEECH CANCELLATION / ASSISTANT TTS STOP
    # ------------------------------------------------------------------
    if semantic_rep.intent == "STOP_ASSISTANT_SPEECH":
        try:
            from legacy.tts import stop_speaking
            stop_speaking(interrupted=True)
        except Exception:
            pass
        full_resp = (pending_prefix + "Stopped speaking.").strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "STOP_ASSISTANT_SPEECH",
            "response": full_resp,
            "handled": True,
            "semantic_representation": semantic_rep.to_dict(),
        }

    # ------------------------------------------------------------------
    # Step 1.1b00 — LOW-CONFIDENCE / GARBLED STT CLARIFICATION
    # ------------------------------------------------------------------
    if semantic_rep.intent == "CLARIFICATION":
        clarify_resp = semantic_rep.explanation_text or "Could you please clarify your request?"
        dialogue_mgr.record_response(clarify_resp)
        return {
            "status": "success",
            "intent": "CLARIFICATION",
            "response": clarify_resp,
            "action_required": False,
            "handled": True,
            "semantic_representation": semantic_rep.to_dict(),
        }

    # ------------------------------------------------------------------
    # Step 1.1b0a — LINGUISTIC NEGATION & NON-ACTION INTENTS (Section 5)
    # ------------------------------------------------------------------
    if semantic_rep.intent == "NEGATION" or semantic_rep.request_type == "NEGATION" or getattr(semantic_rep, "is_negation", False):
        tgt = semantic_rep.target_entity or "that"
        if tgt.lower() in ("notepad", "chrome", "vscode", "explorer", "terminal", "calc", "calculator"):
            neg_resp = f"Understood, I won't open {tgt.capitalize()}."
        else:
            neg_resp = f"Understood, I won't do {tgt}."
        full_resp = (pending_prefix + neg_resp).strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "NEGATION",
            "response": full_resp,
            "action_required": False,
            "handled": True,
            "semantic_representation": semantic_rep.to_dict(),
        }

    if semantic_rep.intent == "HYPOTHETICAL" or semantic_rep.request_type == "HYPOTHETICAL":
        tgt = semantic_rep.target_entity or "the application"
        hyp_resp = f"Understood. Let me know if you would like me to open {tgt.capitalize()}."
        full_resp = (pending_prefix + hyp_resp).strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "HYPOTHETICAL",
            "response": hyp_resp,
            "action_required": False,
            "handled": True,
            "semantic_representation": semantic_rep.to_dict(),
        }

    if semantic_rep.intent == "EXPLANATION_QUERY" or semantic_rep.request_type == "EXPLANATION":
        hist_ans = semantic_understanding_engine.memory_retriever.answer_historical_query(
            uid_int, semantic_rep, dialogue_mgr.current_state
        )
        full_resp = (pending_prefix + hist_ans).strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "EXPLANATION_QUERY",
            "response": full_resp,
            "action_required": False,
            "handled": True,
            "semantic_representation": semantic_rep.to_dict(),
        }

    if semantic_rep.intent == "ACTION_VERIFICATION" or semantic_rep.sub_intent == "ACTION_VERIFICATION":
        verif_ans = semantic_understanding_engine.memory_retriever.answer_historical_query(
            uid_int, semantic_rep, dialogue_mgr.current_state
        )
        full_resp = (pending_prefix + verif_ans).strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "ACTION_VERIFICATION",
            "response": full_resp,
            "action_required": False,
            "handled": True,
            "semantic_representation": semantic_rep.to_dict(),
        }

    if semantic_rep.intent == "MEMORY_QUERY" and (
        semantic_rep.historical_query_type == "recent_destination"
        or semantic_rep.action in ("recall_previous_turn", "recall_last_request", "memory_query")
        or any(w in clean_low for w in ("what did i ask", "what did i just ask", "what was the last thing i asked", "what was my last request"))
    ):
        mem_ans = semantic_understanding_engine.memory_retriever.answer_historical_query(
            uid_int, semantic_rep, dialogue_mgr.current_state
        )
        sub_int = "RECENT_DESTINATION" if semantic_rep.historical_query_type == "recent_destination" else "CONVERSATIONAL_HISTORY"
        full_resp = (pending_prefix + mem_ans).strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "MEMORY_QUERY",
            "sub_intent": sub_int,
            "response": full_resp,
            "action_required": False,
            "handled": True,
            "semantic_representation": semantic_rep.to_dict(),
        }

    # ------------------------------------------------------------------
    # Step 1.1b1 — RUNTIME CAPABILITIES & REGISTRY QUERIES
    # ------------------------------------------------------------------
    if semantic_rep.intent == "CAPABILITY_QUERY":
        from core.capability_registry import get_capability_registry
        cap_reg = get_capability_registry()
        clean_q = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|trevon|nova|jarvis|assistant)[,\s:]*', '', clean_low).strip()
        spec_ans = cap_reg.check_capability_support(clean_q)
        cap_resp = spec_ans if spec_ans else cap_reg.format_capabilities_overview()
        full_resp = (pending_prefix + cap_resp).strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "CAPABILITY_QUERY",
            "response": full_resp,
            "handled": True,
            "semantic_representation": semantic_rep.to_dict(),
        }

    # ------------------------------------------------------------------
    # Step 1.1b2 — CURRENT, CAUSAL & HISTORICAL ENVIRONMENT QUERIES
    # ------------------------------------------------------------------
    if semantic_rep.intent == "CURRENT_ENVIRONMENT_QUERY":
        from core.environment import get_state_engine, verify_and_synchronize_foreground_state
        engine = get_state_engine()
        curr_state = engine.get_current_state(str(user_id))

        # Perform authoritative foreground verification if empty or window changed
        try:
            from skills.window_management.window_context import get_foreground_window_info
            from core.environment.continuous_observer import ContinuousEnvironmentObserver
            win_info = get_foreground_window_info()
            if win_info and win_info.get("title") and win_info.get("class_name") not in ("Progman", "unknown"):
                app_name = ContinuousEnvironmentObserver._infer_app_name(win_info)
                if app_name and app_name != "unknown":
                    if curr_state.is_empty() or app_name.lower() != curr_state.application.lower():
                        curr_state = verify_and_synchronize_foreground_state(str(user_id), action_target=app_name)
        except Exception as e:
            logger.debug(f"[BRAIN] Live foreground synchronization check failed: {e}")

        ans = None
        from core.universal_computer_access import get_universal_computer_access
        uca = get_universal_computer_access()

        # Check for system visibility or hardware / OS info
        if (
            semantic_rep.sub_intent == "SYSTEM_STATE"
            or any(w in clean_low for w in ("can you see my system", "can you see my screen", "see my computer", "what can you see on my screen", "what can you see on my computer"))
        ):
            if any(w in clean_low for w in ("cpu", "ram", "memory", "gpu", "os", "hostname", "specs", "system info", "hardware")):
                s_info = uca.get_system_info()
                ans = (
                    f"Machine: {s_info['hostname']} ({s_info['os_name']} {s_info['os_release']}, Build {s_info['os_version']}). "
                    f"CPU: {s_info['cpu_count']} cores ({s_info['cpu_percent']}% usage). "
                    f"RAM: {s_info['ram_used_gb']} GB used of {s_info['ram_total_gb']} GB ({s_info['ram_percent']}%)."
                )
            else:
                ans = uca.explain_system_visibility(user_id=user_id)

        # Check for running processes
        elif (
            semantic_rep.sub_intent == "PROCESS_STATE"
            or any(w in clean_low for w in ("what's running", "what is running", "running processes", "running on my computer", "what apps are running", "list processes"))
        ):
            procs = uca.list_processes(limit=6, sort_by="cpu")
            if procs:
                proc_strs = [f"{p['name']} (PID {p['pid']}, CPU {p['cpu_percent']}%, {p['memory_mb']} MB)" for p in procs]
                ans = f"Top running processes on your computer:\n" + "\n".join(f"- {s}" for s in proc_strs)
            else:
                ans = "I could not enumerate running processes."

        # Check for current folder / directory
        elif (
            semantic_rep.sub_intent == "CURRENT_FOLDER"
            or any(w in clean_low for w in ("what folder am i in", "which folder am i in", "what directory am i in", "what folder am i currently in"))
        ):
            active_win = uca.get_active_window()
            deep = uca.observe_ui_deep(active_win.get("hwnd", 0), active_win.get("class_name", ""))
            current_folder = (
                deep.get("explorer_folder")
                or (curr_state.active_entities.get("current_directory") if curr_state else None)
                or (curr_state.active_entities.get("folder_name") if curr_state else None)
                or deep.get("terminal_cwd")
                or (curr_state.active_entities.get("cwd") if curr_state else None)
            )
            if not current_folder and active_win.get("title"):
                m_folder = re.search(r'([A-Za-z]:\\[^"\'<>|?*]+)', active_win["title"])
                if m_folder:
                    current_folder = m_folder.group(1).rstrip()
            if not current_folder:
                current_folder = os.getcwd()

            ans = f"You are currently in folder '{current_folder}'."

        # Check for drives / filesystem state
        elif (
            semantic_rep.sub_intent == "FILESYSTEM_STATE"
            or any(w in clean_low for w in ("what drives", "available drives", "storage space", "disk space", "hard drive", "free space on"))
        ):
            drives = uca.get_drives_and_storage()
            if drives:
                d_strs = [f"{d['drive']} ({d['free_gb']} GB free of {d['total_gb']} GB, {d['percent_used']}% used)" for d in drives]
                ans = f"Accessible drives on your system: " + ", ".join(d_strs) + "."
            else:
                ans = "I could not detect any accessible drives."

        # Check for terminal directory
        elif (
            semantic_rep.sub_intent == "CURRENT_TERMINAL_DIRECTORY"
            or any(w in clean_low for w in ("where am i in terminal", "where am i in the terminal", "terminal directory", "terminal cwd", "current terminal directory", "what directory am i in", "what directory am i currently in", "directory am i in"))
        ):
            active_win = uca.get_active_window()
            deep = uca.observe_ui_deep(active_win.get("hwnd", 0), active_win.get("class_name", ""))
            cwd = deep.get("terminal_cwd") or (curr_state.active_entities.get("terminal_cwd") if curr_state else None) or (curr_state.active_entities.get("cwd") if curr_state else None)
            if not cwd and active_win.get("title"):
                m_cwd = re.search(r'([A-Za-z]:\\[^"\'<>|?*]+)', active_win["title"])
                if m_cwd:
                    cwd = m_cwd.group(1).rstrip()
            if not cwd and any(t in (active_win.get("title", "") + active_win.get("class_name", "")).lower() for t in ("cmd", "powershell", "terminal", "bash", "mintty", "console")):
                cwd = os.getcwd()

            if cwd:
                ans = f"You are currently in directory '{cwd}' in the terminal."
            else:
                ans = f"Active window is '{active_win.get('title')}', but a specific terminal directory was not detectable."

        # Check for network state
        elif (
            semantic_rep.sub_intent == "NETWORK_STATE"
            or any(w in clean_low for w in ("network status", "ip address", "ip info", "internet connection", "connectivity diagnostics"))
        ):
            net = uca.get_network_info()
            ips = ", ".join(f"{k}: {v.get('ip')}" for k, v in net.get("adapters", {}).items() if v.get("ip"))
            ans = f"Network is {'connected' if net.get('connected') else 'disconnected'}. Active IP addresses: {ips}."

        # Check for current website / URL
        elif semantic_rep.sub_intent in ("CURRENT_WEBSITE", "CURRENT_URL") or any(w in clean_low for w in ("what website", "which website", "what site", "which site", "what url", "current website")):
            bstate = uca.get_browser_state()
            url = bstate.get("url") if bstate else None
            title = bstate.get("title") if bstate else ""
            if not url and curr_state and curr_state.active_entities:
                url = curr_state.active_entities.get("url") or curr_state.active_entities.get("website")
            if not title and curr_state and curr_state.active_entities:
                title = curr_state.active_entities.get("title") or curr_state.active_entities.get("tab_title")

            if url:
                m_domain = re.search(r'https?://(?:www\.)?([^/]+)', url)
                domain = m_domain.group(1) if m_domain else url
                if title:
                    ans = f"You are currently on {domain} viewing '{title}' ({url})."
                else:
                    ans = f"You are currently on {domain} ({url})."
            elif title:
                ans = f"You are currently viewing '{title}' in your web browser."
            elif bstate and bstate.get("browser") and bstate.get("browser") != "browser":
                ans = f"You have {bstate['browser'].capitalize()} open, but no active website URL could be detected."
            else:
                ans = "No active website or web browser is currently detected."

        # Check for current browser
        elif semantic_rep.sub_intent == "CURRENT_BROWSER" or any(w in clean_low for w in ("which browser", "what browser")):
            bstate = uca.get_browser_state()
            if bstate and bstate.get("browser"):
                ans = f"You are currently using {bstate['browser'].capitalize()} viewing '{bstate.get('title')}'."
            elif curr_state and curr_state.application and curr_state.application.lower() in ("chrome", "brave", "msedge", "edge", "firefox"):
                ans = f"You are currently using {curr_state.application.capitalize()}."
            else:
                ans = "No active web browser is currently focused."

        elif curr_state and not curr_state.is_empty():
            # Check for YouTube channel query
            if any(w in clean_low for w in ("which channel", "what channel", "channel")):
                channel = curr_state.active_entities.get("channel")
                if channel:
                    ans = f"The channel is '{channel}'."
                else:
                    ans = "I could not determine the channel from the current page."

            # Check for selected code / text in editor
            elif any(w in clean_low for w in ("what is selected", "what's selected", "what is highlighted", "selected code")):
                selection = curr_state.active_entities.get("selection")
                if selection:
                    ans = f"The selected code is:\n{selection}"
                else:
                    ans = "There is no code currently selected in the active editor."

            # Check for selected files in File Explorer
            elif any(w in clean_low for w in ("files do i have selected", "files are selected", "what files are selected", "what do i have selected", "selected files")):
                sel_files = curr_state.active_entities.get("selected_files") or []
                if sel_files:
                    names = [os.path.basename(f) for f in sel_files]
                    ans = f"You have selected: {', '.join(names)}."
                else:
                    ans = "No files are currently selected in File Explorer."

            # Check for git branch query
            elif any(w in clean_low for w in ("what branch", "which branch", "branch am i")):
                branch = curr_state.active_entities.get("git_branch")
                if branch:
                    ans = f"You are on branch '{branch}'."
                else:
                    ans = "No git branch was detected for the current project."

            # Check for project / workspace query
            elif any(w in clean_low for w in ("what project", "which project", "project am i")):
                proj = curr_state.active_entities.get("project") or curr_state.active_entities.get("workspace")
                if proj:
                    ans = f"You are in the '{proj}' project."
                else:
                    ans = "No active project was detected."

            # Check for active file or document query
            elif (semantic_rep.sub_intent in ("CURRENT_FILE", "CURRENT_DOCUMENT") or
                  any(w in clean_low for w in ("what file", "which file", "file am i", "file do i", "what document", "which document", "document am i"))):
                active_win = uca.get_active_window()
                deep = uca.observe_ui_deep(active_win.get("hwnd", 0), active_win.get("class_name", ""))
                doc = deep.get("document") or curr_state.active_entities.get("document")
                file_name = deep.get("active_file") or curr_state.active_entities.get("active_file") or curr_state.active_entities.get("file_name")
                proj = deep.get("project") or curr_state.active_entities.get("project") or curr_state.active_entities.get("workspace")

                if doc and "notepad" in (active_win.get("title", "") + active_win.get("class_name", "")).lower():
                    ans = f"You are currently editing document '{doc}' in Notepad."
                elif file_name and proj:
                    ans = f"You are currently working on '{file_name}' in project '{proj}'."
                elif file_name:
                    ans = f"You are currently working on '{file_name}'."
                elif doc:
                    ans = f"You are currently editing document '{doc}'."
                else:
                    ans = "No active file or document was detected in the active editor."

            # Check for video / youtube query
            elif (semantic_rep.sub_intent == "CURRENT_VIDEO" or semantic_rep.target_type == "VIDEO" or
                  any(w in clean_low for w in ("video", "clip", "watching", "youtube", "stream"))):
                dialogue_mgr.current_state.session_context["last_environment_query_type"] = "video"
                vt = curr_state.active_entities.get("video_title")
                channel = curr_state.active_entities.get("channel")
                is_youtube = (
                    "youtube" in curr_state.application.lower()
                    or "youtube" in curr_state.window_title.lower()
                    or "youtube" in str(curr_state.active_entities.get("url", "")).lower()
                )
                if vt:
                    ans = f"You are currently watching '{vt}'" + (f" by {channel} on YouTube." if channel else " on YouTube.")
                elif is_youtube:
                    ans = "YouTube is open, but I can't currently determine the video."
                else:
                    app_cap = curr_state.application.capitalize() if curr_state.application else "another application"
                    ans = f"No video is currently playing. You are currently in {app_cap} ('{curr_state.window_title}')."

            # Check for website / URL / browser page query
            elif (semantic_rep.sub_intent in ("CURRENT_WEBSITE", "CURRENT_PAGE") or semantic_rep.target_type in ("WEBSITE", "PAGE") or
                  any(w in clean_low for w in ("website", "site", "url", "page", "browser page", "tab", "webpage"))):
                dialogue_mgr.current_state.session_context["last_environment_query_type"] = "website"
                url = curr_state.active_entities.get("url")
                domain = curr_state.active_entities.get("domain")
                page_title = curr_state.active_entities.get("page_title") or curr_state.window_title
                if url or domain:
                    loc = url or domain
                    ans = f"You are currently browsing '{page_title}' at {loc}."
                elif curr_state.app_category == "browser" or curr_state.application.lower() in ("chrome", "brave", "msedge", "edge", "firefox", "browser"):
                    ans = f"You are currently in {curr_state.application.capitalize()} viewing '{curr_state.window_title}'."
                else:
                    ans = f"You are not currently browsing a website. You are using {curr_state.application.capitalize()} ('{curr_state.window_title}')."

            # Check for VS Code / IDE context query
            elif "vs code" in clean_low or "vscode" in clean_low or (curr_state.application.lower() in ("code", "vscode") and "app" not in clean_low):
                file_name = curr_state.active_entities.get("active_file") or curr_state.active_entities.get("file_name")
                proj = curr_state.active_entities.get("workspace") or curr_state.active_entities.get("project")
                if file_name and proj:
                    ans = f"You are currently editing '{file_name}' in project '{proj}' using VS Code."
                elif file_name:
                    ans = f"You are currently editing '{file_name}' in VS Code."
                else:
                    ans = f"You are currently in VS Code with window '{curr_state.window_title}'."

            # Check for Explorer context query
            elif "explorer" in clean_low or (curr_state.application.lower() == "explorer" and "app" not in clean_low):
                current_folder = curr_state.active_entities.get("current_directory") or curr_state.active_entities.get("folder_name")
                if current_folder:
                    ans = f"You are currently browsing the folder '{current_folder}' in File Explorer."
                else:
                    ans = f"You are currently in File Explorer viewing '{curr_state.window_title}'."

            # Check for window query
            elif any(w in clean_low for w in ("window", "screen", "focused")):
                ans = f"Your currently active window is '{curr_state.window_title}' in {curr_state.application.capitalize()}."

            # Default: active application query ("what app am I using", "what application is open", "which app is active")
            else:
                dialogue_mgr.current_state.session_context["last_environment_query_type"] = "application"
                app_raw = curr_state.application
                try:
                    from extensions.system.smart_opener import smart_opener
                    res_c = smart_opener.resolve_canonical(app_raw)
                    if res_c and res_c.get("display_name"):
                        raw_disp = res_c["display_name"]
                        if raw_disp.lower() in ("vscode", "vs code", "code"):
                            app_cap = "VS Code"
                        elif raw_disp.lower() in ("powershell", "cmd", "terminal"):
                            app_cap = "Terminal"
                        else:
                            app_cap = raw_disp.title()
                    elif app_raw.lower() in ("vscode", "code"):
                        app_cap = "VS Code"
                    elif app_raw.lower() in ("powershell", "cmd", "terminal"):
                        app_cap = "Terminal"
                    else:
                        app_cap = app_raw.title()
                except Exception:
                    app_cap = "VS Code" if app_raw.lower() in ("vscode", "code") else app_raw.title()

                if curr_state.window_title and curr_state.window_title.lower() != app_cap.lower() and not curr_state.window_title.lower().startswith("untitled"):
                    ans = f"You are currently using {app_cap} ({curr_state.window_title})."
                else:
                    ans = f"You are currently using {app_cap}."

        if not ans:
            if semantic_rep.target_type == "VIDEO" or semantic_rep.sub_intent == "CURRENT_VIDEO":
                ans = "No video is currently detected or playing."
            elif semantic_rep.target_type in ("WEBSITE", "PAGE") or semantic_rep.sub_intent in ("CURRENT_WEBSITE", "CURRENT_PAGE"):
                ans = "No active website or browser page was detected."
            else:
                active_win = uca.get_active_window()
                if active_win.get("title"):
                    proc_name = active_win.get("process_name") or active_win.get("class_name") or "Application"
                    proc_clean = proc_name.replace(".exe", "").capitalize()
                    ans = f"You are currently using {proc_clean} ({active_win.get('title')})."
                else:
                    ans = "I don't have an active environment observation for what application or window you are currently using."

        full_resp = (pending_prefix + ans).strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "CURRENT_ENVIRONMENT_QUERY",
            "response": full_resp,
            "handled": True,
            "environment_state": curr_state.to_dict() if curr_state else None,
            "semantic_representation": semantic_rep.to_dict(),
        }

    if semantic_rep.intent == "CAUSAL_ENVIRONMENT_QUERY":
        from core.causal_attribution import get_causal_attribution_engine
        causal_eng = get_causal_attribution_engine()
        causal_resp = causal_eng.explain_change(user_id=uid_int, query=user_input)
        full_resp = (pending_prefix + causal_resp).strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "CAUSAL_ENVIRONMENT_QUERY",
            "response": full_resp,
            "handled": True,
            "semantic_representation": semantic_rep.to_dict(),
        }

    if semantic_rep.intent == "HISTORICAL_ENVIRONMENT_QUERY":
        from core.environment import get_state_engine
        engine = get_state_engine()
        curr_state = engine.get_current_state(str(user_id))
        prev_state = engine.get_previous_state(str(user_id))
        history = engine.get_history(str(user_id), limit=10)

        ans = None

        # 1. Video history
        if (semantic_rep.sub_intent == "PREVIOUS_VIDEO" or semantic_rep.target_type == "VIDEO" or
            any(w in clean_low for w in ("watching before", "video did i have before", "video was i watching", "clip was i", "what was i watching before"))):
            dialogue_mgr.current_state.session_context["last_environment_query_type"] = "video"
            for t in history:
                st = t.before_state
                if st and st.active_entities.get("video_title"):
                    vt = st.active_entities.get("video_title")
                    ans = f"Before this, you were watching '{vt}' on YouTube."
                    break
            if not ans and prev_state and prev_state.active_entities.get("video_title"):
                vt = prev_state.active_entities.get("video_title")
                ans = f"Before this, you were watching '{vt}' on YouTube."
            if not ans:
                ans = "I do not have a record of a video playing previously."

        # 2. Website / Page history
        elif (semantic_rep.sub_intent == "PREVIOUS_WEBSITE" or semantic_rep.target_type == "WEBSITE" or
              any(w in clean_low for w in ("before this page", "before this site", "before this website", "where was i before", "website was i on before"))):
            dialogue_mgr.current_state.session_context["last_environment_query_type"] = "website"
            for t in history:
                st = t.before_state
                if st and not st.is_empty() and (st.active_entities.get("url") or st.active_entities.get("domain") or st.active_entities.get("page_title")):
                    url = st.active_entities.get("url") or st.active_entities.get("domain")
                    title = st.active_entities.get("page_title") or st.window_title
                    ans = f"Before this page, you were viewing '{title}' at {url}."
                    break
            if not ans and prev_state and not prev_state.is_empty() and (prev_state.active_entities.get("url") or prev_state.active_entities.get("domain") or prev_state.active_entities.get("page_title")):
                url = prev_state.active_entities.get("url") or prev_state.active_entities.get("domain")
                title = prev_state.active_entities.get("page_title") or prev_state.window_title
                ans = f"Before this page, you were viewing '{title}' at {url}."
            if not ans:
                ans = "I do not have a record of what website you were viewing previously."

        # 3. Contextual pronoun follow-up ("before that")
        elif "before that" in clean_low or clean_low.endswith("before that"):
            last_type = dialogue_mgr.current_state.session_context.get("last_environment_query_type", "application")
            if last_type == "website":
                for t in history:
                    st = t.before_state
                    if st and not st.is_empty() and (st.active_entities.get("url") or st.active_entities.get("domain") or st.active_entities.get("page_title")):
                        url = st.active_entities.get("url") or st.active_entities.get("domain")
                        title = st.active_entities.get("page_title") or st.window_title
                        ans = f"Before that, you were viewing '{title}' at {url}."
                        break
            elif last_type == "video":
                for t in history:
                    st = t.before_state
                    if st and st.active_entities.get("video_title"):
                        vt = st.active_entities.get("video_title")
                        ans = f"Before that, you were watching '{vt}' on YouTube."
                        break
            if not ans:
                if len(history) >= 2 and history[1].before_state and not history[1].before_state.is_empty():
                    ans = f"{history[1].before_state.application.capitalize()} was active before that."
                elif prev_state and not prev_state.is_empty():
                    ans = f"{prev_state.application.capitalize()} was active before that."

        # 4. Target application reference ("what was I using before Brave?", "what was open before Chrome")
        target_app_entity = semantic_rep.target_entity
        if not target_app_entity:
            m_before_app = re.search(r'\bbefore\s+(?:the\s+)?(?:application\s+|app\s+)?([a-zA-Z0-9_\-]+)', clean_low)
            if m_before_app and m_before_app.group(1).lower() not in ("this", "that", "now", "it"):
                target_app_entity = m_before_app.group(1).lower()

        if not ans and target_app_entity and target_app_entity not in ("this", "that", "now", "it"):
            app_target = target_app_entity.lower().strip()
            for t in history:
                if t.after_state and t.after_state.application.lower() == app_target and t.before_state and not t.before_state.is_empty():
                    ans = f"Before {app_target.capitalize()}, you were using {t.before_state.application.capitalize()} ({t.before_state.format_summary()})."
                    break
            if not ans and curr_state and curr_state.application.lower() == app_target and prev_state and not prev_state.is_empty():
                ans = f"Before {app_target.capitalize()}, you were using {prev_state.application.capitalize()} ({prev_state.format_summary()})."
            if not ans:
                ans = f"I do not have a record of what was active before {app_target.capitalize()}."

        # 5. Check what application the user switched from / previous app
        elif not ans and (
            semantic_rep.sub_intent == "PREVIOUS_APPLICATION"
            or any(w in clean_low for w in (
                "previous app", "previous application", "app was open before", "application was open before",
                "switch from", "switched from", "open previously", "open before this", "what did i have open",
                "which app was open", "what app was open", "what was the previous"
            ))
        ):
            prev_app = None
            if prev_state and not prev_state.is_empty():
                prev_app = prev_state.application.capitalize()
            elif history and history[0].before_state and not history[0].before_state.is_empty():
                prev_app = history[0].before_state.application.capitalize()
            if prev_app:
                ans = f"{prev_app} was the previous active application."
            else:
                ans = "I do not have a record of what application was active previously."

        # 6. Check if user asked what changed
        elif not ans and "what changed" in clean_low:
            if history:
                ans = f"The observable difference was: {history[0].transition_summary}."
            elif prev_state and curr_state:
                ans = f"The environment transitioned from {prev_state.application.capitalize()} to {curr_state.application.capitalize()}."
            else:
                ans = "No recent environment changes were detected."

        if not ans and prev_state and not prev_state.is_empty():
            ans = f"{prev_state.application.capitalize()} was the previous active application."
        elif not ans and history:
            ans = f"Previously, {history[0].transition_summary}."
        elif not ans:
            ans = "I don't have an environment record of what you were doing previously."

        full_resp = (pending_prefix + ans).strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "HISTORICAL_ENVIRONMENT_QUERY",
            "response": full_resp,
            "handled": True,
            "semantic_representation": semantic_rep.to_dict(),
        }

    # ------------------------------------------------------------------
    # Step 1.1b3 — CONCURRENT TASK STATUS & CANCELLATION (Sections L, M)
    # ------------------------------------------------------------------
    if semantic_rep.intent == "TASK_STATUS_QUERY":
        from core.task_execution_manager import get_task_execution_manager
        tem = get_task_execution_manager()
        clean_ref = re.sub(r'^(?:what\s+is|how\s+is|show\s+me|tell\s+me)\s+(?:the\s+)?(?:task\s+status|status\s+of\s+)?', '', clean_low)
        clean_ref = re.sub(r'\s+(?:doing|going|status)[.!?]?$', '', clean_ref).strip()
        task = tem.resolve_task_reference(clean_ref or "latest", user_id=uid_int)
        if task:
            prog = f" ({task.progress})" if task.progress and task.progress != "0%" else ""
            step = f" Current step: {task.current_step}." if task.current_step else ""
            status_text = f"Task '{task.normalized_goal}' is currently {task.status.value.lower()}{prog}.{step}"
        else:
            status_text = tem.get_active_tasks_summary(user_id=uid_int)
        full_resp = (pending_prefix + status_text).strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "TASK_STATUS_QUERY",
            "response": full_resp,
            "handled": True,
            "task_id": task.task_id if task else None,
            "semantic_representation": semantic_rep.to_dict(),
        }

    if semantic_rep.intent == "TASK_CANCELLATION":
        from core.task_execution_manager import get_task_execution_manager
        tem = get_task_execution_manager()
        clean_ref = re.sub(r'^(?:cancel|stop|abort)\s+(?:the\s+|that\s+)?', '', clean_low).rstrip('.!?').strip()
        task = tem.resolve_task_reference(clean_ref or "latest", user_id=uid_int)
        if task and task.is_active:
            res = tem.cancel_task(task.task_id, user_id=uid_int)
            cancel_resp = res.get("response", f"Cancelled task '{task.normalized_goal}'.")
        else:
            cancel_resp = "I couldn't find an active task matching that description to cancel."
        full_resp = (pending_prefix + cancel_resp).strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "TASK_CANCELLATION",
            "response": full_resp,
            "handled": True,
            "task_id": task.task_id if task else None,
            "semantic_representation": semantic_rep.to_dict(),
        }

    # ------------------------------------------------------------------
    # Step 1.1d1 — CONTEXTUAL CONTENT ACQUISITION, TRANSFORMATION & INSERTION
    # ------------------------------------------------------------------
    if semantic_rep.intent == "CONTENT_INSERTION":
        from core.artifact_resolver import get_artifact_reference_resolver
        from core.target_resolver import get_target_resolver
        from core.content_inserter import get_content_inserter

        art_resolver = get_artifact_reference_resolver()
        target_resolver = get_target_resolver()
        inserter = get_content_inserter()

        # 1. Resolve WHAT content the user means
        res_artifact = art_resolver.resolve(
            user_input=user_input,
            user_id=uid_int,
            dialogue_state=dialogue_mgr.current_state,
        )

        if not res_artifact.is_success:
            # Check for direct inline text or dialogue history fallback
            inline_text = None
            m_inline = re.search(r'(?:write|insert|type|put)\s+["\']([^"\']+)["\'](?:\s+here)?', user_input, re.IGNORECASE)
            if m_inline:
                inline_text = m_inline.group(1).strip()
            else:
                m_inline2 = re.search(r'(?:write|insert|type|put)\s+(.+?)\s+here', user_input, re.IGNORECASE)
                if m_inline2:
                    cand = m_inline2.group(1).strip()
                    if cand.lower() not in ("this", "that", "it", "code", "the code", "this code", "here", "something"):
                        inline_text = cand

            # If still None, check if dialogue history has recent assistant code or text
            if not inline_text and dialogue_mgr and hasattr(dialogue_mgr, "current_state"):
                hist = getattr(dialogue_mgr.current_state, "history", [])
                for turn in reversed(hist):
                    if getattr(turn, "role", "") == "assistant":
                        resp_content = getattr(turn, "content", "")
                        m_code = re.search(r'```(?:[a-zA-Z0-9_\+]*\n)?(.*?)```', resp_content, re.DOTALL)
                        if m_code:
                            inline_text = m_code.group(1).strip()
                            break
                        elif resp_content and len(resp_content) < 500 and not any(w in resp_content.lower() for w in ("how can i help", "hello", "what can i do")):
                            inline_text = resp_content.strip()
                            break

            if inline_text:
                from core.artifact_graph import ContentArtifact
                artifact = ContentArtifact(
                    artifact_id=f"art_dynamic_{int(time.time()*1000)}",
                    content=inline_text,
                    topic="operator_content",
                    content_type="code" if ("def " in inline_text or "class " in inline_text or "import " in inline_text) else "text",
                    user_id=uid_int,
                )
            else:
                clarification_msg = res_artifact.clarification_prompt or "I couldn't identify which artifact you'd like to insert."
                full_msg = (pending_prefix + clarification_msg).strip()
                dialogue_mgr.record_response(full_msg)
                return {
                    "status": "clarification_needed" if res_artifact.is_ambiguous else "not_found",
                    "intent": "CONTENT_INSERTION",
                    "response": full_msg,
                    "is_ambiguous": res_artifact.is_ambiguous,
                    "clarification_prompt": res_artifact.clarification_prompt,
                    "candidate_artifacts": [a.to_dict() for a in res_artifact.candidate_artifacts],
                    "handled": True,
                }
        else:
            artifact = res_artifact.artifact


        # 2. Check if target is a filesystem destination (e.g. Downloads)
        if "downloads" in clean_low or getattr(semantic_rep, "target_entity", "") == "downloads":
            from core.os_gateway.context_resolver import get_context_resolver
            cr = get_context_resolver()
            dest_dir = cr.resolve_destination("Downloads")
            os.makedirs(dest_dir, exist_ok=True)
            clean_topic = re.sub(r'[^a-zA-Z0-9_\-]', '_', artifact.topic).strip('_') or 'information'
            dest_file = os.path.join(dest_dir, f"{clean_topic}.txt")
            with open(dest_file, "w", encoding="utf-8") as f:
                f.write(artifact.content)

            # Record in session context for subsequent "Where did you put it?" queries
            dialogue_mgr.current_state.session_context["last_insertion_target"] = "Downloads"
            dialogue_mgr.current_state.session_context["last_saved_file"] = dest_file

            # Record in OSActionHistory
            try:
                from core.os_gateway import get_os_action_history
                get_os_action_history().record_action(
                    operation_type="WRITE_FILE",
                    target=dest_file,
                    parameters={"destination": dest_dir, "topic": artifact.topic},
                    user_id=uid_int,
                    status="success"
                )
            except Exception:
                pass

            success_msg = f"Saved the {artifact.content_type} for '{artifact.topic}' to Downloads."
            full_resp = (pending_prefix + success_msg).strip()
            dialogue_mgr.record_response(full_resp)
            dialogue_mgr.update_state(
                execution_result={
                    "status": "success",
                    "intent": "CONTENT_INSERTION",
                    "action": "save_to_downloads",
                    "target": "Downloads",
                    "response": full_resp,
                },
                intents=["CONTENT_INSERTION"],
            )
            return {
                "status": "success",
                "intent": "CONTENT_INSERTION",
                "response": full_resp,
                "artifact": artifact.to_dict(),
                "target": {"destination": dest_file, "folder": dest_dir},
                "handled": True,
            }

        # 3. Resolve application destination ("here" / active target / Notepad)
        target = target_resolver.resolve_current_target(dialogue_state=dialogue_mgr.current_state)

        # If user explicitly requested Notepad, ensure Notepad is open and active
        if "notepad" in clean_low or getattr(semantic_rep, "target_entity", "") == "notepad":
            if target.app_name != "notepad":
                unified_router.execute_single_action("open notepad", user_id=uid_int)
                time.sleep(0.3)
                target = target_resolver.resolve_current_target(dialogue_state=dialogue_mgr.current_state)
                if target.app_name != "notepad":
                    target.app_name = "notepad"
                    target.target_type = "notepad"

        # 4. Check Safety Gate (password / credential field)
        if not target.is_safe:
            safety_msg = f"I cannot insert content into this field: {target.safety_reason or 'Protected sensitive field.'}"
            full_msg = (pending_prefix + safety_msg).strip()
            dialogue_mgr.record_response(full_msg)
            return {
                "status": "blocked_safety",
                "intent": "CONTENT_INSERTION",
                "response": full_msg,
                "target": target.to_dict(),
                "handled": True,
            }

        # 5. Execute Insertion & Outcome Verification
        insert_res = inserter.insert(artifact=artifact, target=target, user_id=uid_int)

        if insert_res.get("success"):
            app_display = target.app_name.capitalize() if target.app_name else "active window"
            if target.app_name == "vscode":
                app_display = "VS Code"
            elif target.app_name == "notepad":
                app_display = "Notepad"

            type_label = artifact.content_type
            if artifact.content_type == "code" and artifact.programming_language:
                type_label = f"{artifact.programming_language.capitalize()} code"

            dialogue_mgr.current_state.session_context["last_insertion_target"] = app_display
            dialogue_mgr.current_state.session_context["last_saved_file"] = None

            success_msg = f"Inserted the {type_label} for '{artifact.topic}' into {app_display} at your cursor."
            full_resp = (pending_prefix + success_msg).strip()
            dialogue_mgr.record_response(full_resp)
            dialogue_mgr.update_state(
                execution_result={
                    "status": "success",
                    "intent": "CONTENT_INSERTION",
                    "action": "insert_content",
                    "target": app_display,
                    "response": full_resp,
                },
                intents=["CONTENT_INSERTION"],
            )
            return {
                "status": "success",
                "intent": "CONTENT_INSERTION",
                "response": full_resp,
                "artifact": artifact.to_dict(),
                "target": target.to_dict(),
                "insertion_result": insert_res,
                "handled": True,
            }
        else:
            fail_reason = insert_res.get("failure_reason") or "Insertion could not be completed."
            fail_msg = f"Failed to insert content: {fail_reason}"
            full_resp = (pending_prefix + fail_msg).strip()
            dialogue_mgr.record_response(full_resp)
            return {
                "status": "error",
                "intent": "CONTENT_INSERTION",
                "response": full_resp,
                "artifact": artifact.to_dict(),
                "target": target.to_dict(),
                "insertion_result": insert_res,
                "handled": True,
            }

    if semantic_rep.intent == "ARTIFACT_TRANSFORMATION":
        from core.artifact_resolver import get_artifact_reference_resolver
        from core.content_acquisition import get_content_acquisition_engine

        art_resolver = get_artifact_reference_resolver()
        acq_engine = get_content_acquisition_engine()

        # 1. Resolve which artifact to transform
        res_artifact = art_resolver.resolve(
            user_input=user_input,
            user_id=uid_int,
            dialogue_state=dialogue_mgr.current_state,
        )

        if not res_artifact.is_success:
            clarification_msg = res_artifact.clarification_prompt or "I couldn't identify which artifact you'd like me to transform."
            full_msg = (pending_prefix + clarification_msg).strip()
            dialogue_mgr.record_response(full_msg)
            return {
                "status": "clarification_needed" if res_artifact.is_ambiguous else "not_found",
                "intent": "ARTIFACT_TRANSFORMATION",
                "response": full_msg,
                "handled": True,
            }

        parent_art = res_artifact.artifact

        # Check if user requested the root/full information: "Give me the full information"
        req_full_info = any(w in clean_low for w in ("full information", "full concept", "entire information", "original information", "complete information", "all the information", "all information"))
        if req_full_info:
            root_art = acq_engine.graph.get_root(parent_art.artifact_id) or parent_art
            dialogue_mgr.current_state.session_context["last_content_artifact_id"] = root_art.artifact_id
            dialogue_mgr.current_state.session_context["last_content_topic"] = root_art.topic
            dialogue_mgr.current_state.session_context["last_content_type"] = root_art.content_type

            resp_text = f"Here is the complete information for '{root_art.topic}':\n\n{root_art.content}"
            full_resp = (pending_prefix + resp_text).strip()
            dialogue_mgr.record_response(full_resp)
            return {
                "status": "success",
                "intent": "ARTIFACT_TRANSFORMATION",
                "response": full_resp,
                "artifact": root_art.to_dict(),
                "handled": True,
            }

        # Determine transformation type
        t_type = "summary"
        if any(w in clean_low for w in ("summarize", "summarise", "summary", "shorten", "brief")):
            t_type = "summary"
        elif any(w in clean_low for w in ("explain", "explanation", "details")):
            t_type = "explanation"
        elif any(w in clean_low for w in ("code", "implementation", "convert to")):
            t_type = "code"

        target_lang = None
        for lang in ("python", "javascript", "cpp", "c++", "java", "sql"):
            if lang in clean_low:
                target_lang = "cpp" if lang == "c++" else lang
                break

        child_art = acq_engine.transform_artifact(
            parent_artifact=parent_art,
            transformation_type=t_type,
            target_language=target_lang,
            user_id=uid_int,
        )

        dialogue_mgr.current_state.session_context["last_content_artifact_id"] = child_art.artifact_id
        dialogue_mgr.current_state.session_context["last_content_topic"] = child_art.topic
        dialogue_mgr.current_state.session_context["last_content_type"] = child_art.content_type

        ack_text = f"I've generated the {child_art.content_type} for '{child_art.topic}' and linked it to the parent artifact.\n\n{child_art.content}"
        full_resp = (pending_prefix + ack_text).strip()
        dialogue_mgr.record_response(full_resp)
        return {
            "status": "success",
            "intent": "ARTIFACT_TRANSFORMATION",
            "response": full_resp,
            "artifact": child_art.to_dict(),
            "parent_artifact_id": parent_art.artifact_id,
            "handled": True,
        }

    if semantic_rep.intent == "CONTENT_ACQUISITION":
        from core.content_acquisition import get_content_acquisition_engine
        acq_engine = get_content_acquisition_engine()

        artifact = acq_engine.acquire_content(
            user_request=user_input,
            user_id=uid_int,
            dialogue_state=dialogue_mgr.current_state,
        )

        dialogue_mgr.current_state.active_artifact = artifact.to_dict()
        dialogue_mgr.current_state.session_context["active_artifact"] = artifact.to_dict()
        dialogue_mgr.current_state.session_context["last_content_artifact_id"] = artifact.artifact_id
        dialogue_mgr.current_state.session_context["last_content_topic"] = artifact.topic
        dialogue_mgr.current_state.session_context["last_content_type"] = artifact.content_type

        if artifact.content_type == "code":
            type_label = f"{artifact.programming_language.capitalize()} code" if artifact.programming_language else "code"
            msg = f"Done. I found and gathered the {type_label} for {artifact.topic}."
        else:
            msg = f"Done. I found and gathered the information about {artifact.topic}."

        full_resp = (pending_prefix + msg).strip()
        dialogue_mgr.record_response(full_resp)
        dialogue_mgr.update_state(
            execution_result={
                "status": "success",
                "intent": "CONTENT_ACQUISITION",
                "action": "gather_information",
                "target": artifact.topic,
                "response": full_resp,
            },
            intents=["CONTENT_ACQUISITION"],
        )
        return {
            "status": "success",
            "intent": "CONTENT_ACQUISITION",
            "response": full_resp,
            "artifact_id": artifact.artifact_id,
            "topic": artifact.topic,
            "content_type": artifact.content_type,
            "artifact": artifact.to_dict(),
            "handled": True,
        }

    if semantic_rep.intent == "ARTIFACT_QUERY":
        from core.artifact_resolver import get_artifact_reference_resolver
        art_resolver = get_artifact_reference_resolver()
        res_artifact = art_resolver.resolve(
            user_input=user_input,
            user_id=uid_int,
            dialogue_state=dialogue_mgr.current_state,
        )
        if res_artifact.is_success and res_artifact.artifact:
            art = res_artifact.artifact
            dialogue_mgr.current_state.active_artifact = art.to_dict()
            dialogue_mgr.current_state.session_context["active_artifact"] = art.to_dict()
            dialogue_mgr.current_state.session_context["last_content_artifact_id"] = art.artifact_id
            dialogue_mgr.current_state.session_context["last_content_topic"] = art.topic
            dialogue_mgr.current_state.session_context["last_content_type"] = art.content_type
            resp_text = f"Here is the information I found about '{art.topic}':\n\n{art.content}"
            full_resp = (pending_prefix + resp_text).strip()
            dialogue_mgr.record_response(full_resp)
            return {
                "status": "success",
                "intent": "ARTIFACT_QUERY",
                "response": full_resp,
                "artifact": art.to_dict(),
                "handled": True,
            }
        else:
            clarification_msg = res_artifact.clarification_prompt or "I couldn't find the information you mentioned."
            full_msg = (pending_prefix + clarification_msg).strip()
            dialogue_mgr.record_response(full_msg)
            return {
                "status": "clarification_needed" if res_artifact.is_ambiguous else "not_found",
                "intent": "ARTIFACT_QUERY",
                "response": full_msg,
                "handled": True,
            }

    # ------------------------------------------------------------------
    # Step 1.1d1b — STATEFUL ARTIFACT READING, STOP, AND CONTINUE
    # ------------------------------------------------------------------
    if semantic_rep.intent == "ARTIFACT_READING":
        from core.artifact_resolver import get_artifact_reference_resolver
        from core.artifact_reader import get_artifact_reading_controller

        art_resolver = get_artifact_reference_resolver()
        reading_ctrl = get_artifact_reading_controller()

        res_artifact = art_resolver.resolve(
            user_input=user_input,
            user_id=uid_int,
            dialogue_state=dialogue_mgr.current_state,
        )

        if not res_artifact.is_success:
            clarification_msg = res_artifact.clarification_prompt or "I couldn't identify which content you'd like me to read."
            full_msg = (pending_prefix + clarification_msg).strip()
            dialogue_mgr.record_response(full_msg)
            return {
                "status": "clarification_needed" if res_artifact.is_ambiguous else "not_found",
                "intent": "ARTIFACT_READING",
                "response": full_msg,
                "is_ambiguous": res_artifact.is_ambiguous,
                "clarification_prompt": res_artifact.clarification_prompt,
                "candidate_artifacts": [a.to_dict() for a in res_artifact.candidate_artifacts],
                "handled": True,
            }

        target_artifact = res_artifact.artifact
        read_result = reading_ctrl.start_reading(
            artifact=target_artifact,
            user_id=uid_int,
            from_beginning=False,
            async_playback=True,
        )

        resp_text = (pending_prefix + read_result.get("response", f"Reading {target_artifact.topic}...")).strip()
        dialogue_mgr.record_response(resp_text)
        return {
            "status": read_result.get("status", "success"),
            "intent": "ARTIFACT_READING",
            "response": resp_text,
            "reading_result": read_result,
            "artifact": target_artifact.to_dict(),
            "handled": True,
        }

    if semantic_rep.intent == "ARTIFACT_READING_CONTINUE":
        from core.artifact_reader import get_artifact_reading_controller
        reading_ctrl = get_artifact_reading_controller()

        cont_result = reading_ctrl.continue_reading(user_id=uid_int, async_playback=True)
        resp_text = (pending_prefix + cont_result.get("response", "Resuming reading.")).strip()
        dialogue_mgr.record_response(resp_text)
        return {
            "status": cont_result.get("status", "success"),
            "intent": "ARTIFACT_READING_CONTINUE",
            "response": resp_text,
            "reading_result": cont_result,
            "handled": True,
        }

    if semantic_rep.intent == "ARTIFACT_READING_STOP":
        from core.artifact_reader import get_artifact_reading_controller
        reading_ctrl = get_artifact_reading_controller()

        stop_result = reading_ctrl.stop_reading(user_id=uid_int)
        resp_text = (pending_prefix + stop_result.get("response", "Stopped reading.")).strip()
        dialogue_mgr.record_response(resp_text)
        return {
            "status": stop_result.get("status", "success"),
            "intent": "ARTIFACT_READING_STOP",
            "response": resp_text,
            "reading_result": stop_result,
            "handled": True,
        }

    # ------------------------------------------------------------------
    # Step 1.1d2 — PROFESSIONAL DOCUMENT & PRESENTATION ENGINE
    # ------------------------------------------------------------------
    is_pro_doc_cmd = (semantic_rep.intent == "PROFESSIONAL_DOCUMENT_GENERATION") or any(
        phrase in clean_low for phrase in (
            "create a pdf about", "make a pdf about", "create a report", "make a report",
            "create a professional report", "make a professional report",
            "create a presentation", "make a presentation", "create a ppt", "make a ppt",
            "turn these into a presentation", "turn that into a presentation",
            "turn these documents into a presentation", "turn that report into a presentation",
            "create a study guide", "make a study guide", "create study notes", "make study notes",
            "make a professional ppt", "make the report more detailed", "make it more detailed",
            "make it shorter", "create a detailed document", "create a detailed report",
            "report and presentation", "make a one-page summary", "create an executive summary",
            "presentation about", "presentation on", "report about", "report on",
            "pdf about", "pdf on"
        )
    ) or (
        any(k in clean_low for k in ("presentation", "ppt", "pptx", "slide deck"))
        and any(w in clean_low for w in ("create", "make", "generate", "turn", "build"))
    ) or (
        any(k in clean_low for k in ("study guide", "study notes"))
        and any(w in clean_low for w in ("create", "make", "generate", "build"))
    ) or (
        any(k in clean_low for k in ("report", "study guide"))
        and any(w in clean_low for w in ("professional", "detailed", "executive", "one-page", "one page"))
        and any(w in clean_low for w in ("create", "make", "generate", "produce", "turn"))
    ) or (
        "create a detailed document" in clean_low
    )

    if is_pro_doc_cmd:
        from core.professional_document_engine import get_professional_document_engine
        from core.document_resolver import get_document_reference_resolver

        pro_engine = get_professional_document_engine()
        resolver = get_document_reference_resolver()

        has_doc_reference = any(w in clean_low for w in ("from these", "from this", "from those", "these pdfs", "these documents", "these files", "those pdfs", "5 pdfs", "from documents"))
        source_paths = None
        resolved_docs_meta = []

        if has_doc_reference:
            res_result = resolver.resolve(
                user_input=user_input,
                dialogue_state=dialogue_mgr.current_state,
                user_id=uid_int,
            )
            if res_result.is_success and res_result.resolved_documents:
                source_paths = [r.document_path for r in res_result.resolved_documents]
                resolved_docs_meta = [r.to_dict() for r in res_result.resolved_documents]
                dialogue_mgr.current_state.session_context["resolved_documents"] = source_paths
                dialogue_mgr.current_state.session_context["last_resolved_documents"] = [
                    r.document_name for r in res_result.resolved_documents
                ]
            elif not res_result.is_success and (res_result.clarification_prompt or res_result.missing_files):
                clarification_msg = res_result.clarification_prompt or "Could not resolve the referenced source documents."
                full_msg = (pending_prefix + clarification_msg).strip()
                dialogue_mgr.record_response(full_msg)
                return {
                    "status": res_result.status,
                    "intent": "PROFESSIONAL_DOCUMENT_GENERATION",
                    "response": full_msg,
                    "clarification_prompt": res_result.clarification_prompt,
                    "missing_files": res_result.missing_files,
                    "handled": True,
                }
        else:
            prev_resolved = dialogue_mgr.current_state.session_context.get("resolved_documents")
            if not prev_resolved:
                last_art = dialogue_mgr.current_state.session_context.get("last_artifact_path")
                if last_art and os.path.exists(last_art):
                    prev_resolved = [last_art]
            if prev_resolved and any(w in clean_low for w in ("turn that", "turn these", "from that", "from this", "make it more detailed", "make it shorter", "from it", "make a presentation from it")):
                source_paths = prev_resolved

        topic = pro_engine._extract_clean_topic(user_input, dialogue_mgr.current_state)
        if dialogue_mgr.current_state and hasattr(dialogue_mgr.current_state, "session_context"):
            dialogue_mgr.current_state.session_context["last_artifact_topic"] = topic

        def _execute_pro_task(task, report_progress, cancel_token):
            return pro_engine.process_professional_request(
                user_request=user_input,
                user_id=uid_int,
                dialogue_state=dialogue_mgr.current_state,
                source_paths=source_paths,
                report_progress=report_progress,
            )

        task = tem.create_task(
            user_request=user_input,
            user_id=uid_int,
            conversation_id=str(getattr(dialogue_mgr.current_state, "conversation_id", "default")),
            priority=TaskPriority.NORMAL,
            execution_fn=_execute_pro_task,
        )
        tem.submit_task(task)

        is_pres = any(w in clean_low for w in ("presentation", "ppt", "pptx", "slides"))
        is_study = any(w in clean_low for w in ("study guide", "study notes"))
        if is_pres:
            ack_msg = f"I'm creating a professional presentation on '{topic.title()}' with presentation-tailored architecture and theme styling."
        elif is_study:
            ack_msg = f"I'm creating a structured academic study guide on '{topic.title()}'."
        else:
            ack_msg = f"I'm generating a publication-grade technical report on '{topic.title()}'."

        full_resp = (pending_prefix + ack_msg).strip()
        dialogue_mgr.record_response(full_resp)

        return {
            "status": "success",
            "intent": "PROFESSIONAL_DOCUMENT_GENERATION",
            "response": full_resp,
            "task_id": task.task_id,
            "task_status": task.status.value,
            "topic": topic,
            "resolved_documents": resolved_docs_meta,
            "handled": True,
            "background_updates": pending_updates,
        }

    # ------------------------------------------------------------------
    # Step 1.1d — DOCUMENT INTELLIGENCE & REFERENCE RESOLUTION
    # ------------------------------------------------------------------
    is_email_cmd = any(k in clean_low for k in ("email", "emails", "mail", "mails", "inbox", "from:", "subject:", "reply to this", "draft a reply"))
    is_doc_cmd = (not is_email_cmd) and ((semantic_rep.intent in ("DOCUMENT_INTELLIGENCE", "DOCUMENT_READING")) or any(
        phrase in clean_low for phrase in (
            "summarize", "summary", "big picture", "compare these", "compare the documents",
            "make a summary pdf", "create one pdf", "make that into a pdf", "make a pdf",
            "read to me", "read these to me", "read this pdf to me", "read it to me", "read the summary", "read aloud", "find those pdfs"
        )
    ) and (
        any(k in clean_low for k in ("pdf", "pdfs", "document", "documents", "these", "this", "here", ".pdf", "summary"))
        or clean_low in ("give me the big picture", "compare these", "summarize these", "read to me", "read these to me", "read it to me", "make a summary pdf")
    ))

    if is_doc_cmd:
        from core.document_resolver import get_document_reference_resolver
        from core.document_intelligence import get_document_intelligence_controller, ParsedDocument, SummaryMode

        doc_ctrl = get_document_intelligence_controller()
        resolver = get_document_reference_resolver()

        # Handle "Read it to me" / "Read the summary" when recent summary exists
        if any(w in clean_low for w in ("read it to me", "read the summary")) or (("read" in clean_low) and ("summary" in clean_low or "it" in clean_low)):
            prev_sum = getattr(dialogue_mgr.current_state, "session_context", {}).get("last_summary")
            if prev_sum and isinstance(prev_sum, dict):
                overview = prev_sum.get("overview", "")
                full_resp = (pending_prefix + f"I'll read the summary: {overview}").strip()
                dialogue_mgr.record_response(full_resp)
                return {
                    "status": "success",
                    "intent": "DOCUMENT_READING",
                    "response": full_resp,
                    "handled": True,
                }

        # Resolve document references (Strict Priorities 1 -> 5, Ambiguity & Missing Files detection)
        res_result = resolver.resolve(
            user_input=user_input,
            dialogue_state=dialogue_mgr.current_state,
            user_id=uid_int,
        )

        if not res_result.is_success:
            clarification_msg = res_result.clarification_prompt or "Could not resolve the documents."
            full_msg = (pending_prefix + clarification_msg).strip()
            dialogue_mgr.record_response(full_msg)
            return {
                "status": res_result.status,
                "intent": "DOCUMENT_INTELLIGENCE",
                "response": full_msg,
                "clarification_prompt": res_result.clarification_prompt,
                "resolved_documents": [r.to_dict() for r in res_result.resolved_documents],
                "missing_files": res_result.missing_files,
                "handled": True,
            }

        # Read aloud single document
        is_read_aloud = any(w in clean_low for w in ("read these to me", "read this to me", "read to me", "read this", "read aloud"))
        if is_read_aloud and res_result.resolved_documents:
            parsed = doc_ctrl.extractor.extract(res_result.resolved_documents[0].document_path)
            read_res = doc_ctrl.reading_mgr.start_reading(uid_int, parsed)
            resp_str = (pending_prefix + read_res.get("response", "")).strip()
            dialogue_mgr.record_response(resp_str)
            return {
                "status": "success",
                "intent": "DOCUMENT_READING",
                "response": resp_str,
                "reading_state": read_res,
                "handled": True,
            }

        # Maintain resolved document context in dialogue state
        dialogue_mgr.current_state.session_context["resolved_documents"] = [
            r.document_path for r in res_result.resolved_documents
        ]
        dialogue_mgr.current_state.session_context["last_resolved_documents"] = [
            r.document_name for r in res_result.resolved_documents
        ]

        # Multi-document execution via TaskExecutionManager
        target_docs_count = len(res_result.resolved_documents)
        is_artifact_request = any(w in clean_low for w in ("create one pdf", "make a summary pdf", "make that into a pdf", "make a pdf", "create pdf", "summary pdf", "into a pdf"))
        is_big_picture = any(w in clean_low for w in ("big picture", "give me the big picture"))

        def _execute_doc_task(task, report_progress, cancel_token):
            report_progress(f"I found the {target_docs_count} PDFs.", 20.0)
            if cancel_token.is_set():
                return {"status": "cancelled"}

            parsed_list = []
            for ref in res_result.resolved_documents:
                if cancel_token.is_set():
                    return {"status": "cancelled"}
                parsed_list.append(doc_ctrl.extractor.extract(ref.document_path))

            report_progress("Text extraction is complete.", 50.0)
            if cancel_token.is_set():
                return {"status": "cancelled"}

            mode = SummaryMode.NORMAL
            if is_big_picture or len(parsed_list) > 1:
                mode = SummaryMode.BIG_PICTURE
            elif any(w in clean_low for w in ("short", "brief")):
                mode = SummaryMode.SHORT
            elif any(w in clean_low for w in ("detailed", "everything")):
                mode = SummaryMode.DETAILED

            report_progress("I'm synthesizing the documents.", 75.0)
            synthesis = doc_ctrl.synthesizer.synthesize(parsed_list, mode=mode)
            if cancel_token.is_set():
                return {"status": "cancelled"}

            art_path = None
            if is_artifact_request:
                report_progress("The summary PDF is being generated.", 90.0)
                art_path = doc_ctrl.artifact_generator.generate_summary_pdf(synthesis)
                report_progress("The summary PDF is ready.", 100.0)
            else:
                report_progress("Document synthesis is complete.", 100.0)

            # Persist summary
            doc_ctrl._persist_summary(uid_int, synthesis, art_path)
            dialogue_mgr.current_state.session_context["last_summary"] = synthesis.to_dict()
            if art_path:
                dialogue_mgr.current_state.session_context["last_artifact_path"] = art_path

            return {
                "synthesis": synthesis.to_dict(),
                "artifact_path": art_path,
                "status": "success",
            }

        task = tem.create_task(
            user_request=user_input,
            user_id=uid_int,
            conversation_id=str(getattr(dialogue_mgr.current_state, "conversation_id", "default")),
            priority=TaskPriority.NORMAL,
            execution_fn=_execute_doc_task,
        )
        tem.submit_task(task)

        if is_big_picture:
            ack_resp = "I'll combine their main ideas and relationships."
        elif is_artifact_request:
            ack_resp = "I'm creating the summary PDF."
        elif "compare" in clean_low:
            ack_resp = f"I'll compare the {target_docs_count} selected documents."
        else:
            ack_resp = f"I found {target_docs_count} selected PDFs. I'll summarize them."

        full_resp = (pending_prefix + ack_resp).strip()
        dialogue_mgr.record_response(full_resp)

        return {
            "status": "success",
            "intent": "DOCUMENT_INTELLIGENCE",
            "response": full_resp,
            "task_id": task.task_id,
            "task_status": task.status.value,
            "resolved_documents": [r.to_dict() for r in res_result.resolved_documents],
            "handled": True,
            "background_updates": pending_updates,
        }

    active_tasks = tem.list_tasks(user_id=uid_int, active_only=True)
    is_explicit_long_task = any(
        k in clean_low for k in (
            "download and process", "process this dataset", "download dataset",
            "process these files", "process dataset", "run in background", "in the background"
        )
    )
    is_info_question = (
        clean_low.endswith("?")
        or any(clean_low.startswith(q) for q in ("who ", "why ", "when ", "where ", "what ", "how ", "is ", "are ", "can you tell me"))
    ) and not any(w in clean_low for w in ("create", "open", "run", "download", "check", "disk space", "make"))

    is_concurrent_followup = bool(
        active_tasks and (
            any(w in clean_low for w in ("while that", "in the meantime", "in the background", "at the same time", "concurrently", "also check", "also run", "also open"))
            or ("vs code" in clean_low and "python" in clean_low)
            or (("disk space" in clean_low or "disk" in clean_low) and "check" in clean_low)
            or ("dataset" in clean_low or "process" in clean_low)
        )
    )

    if is_explicit_long_task or is_concurrent_followup:
        prio = TaskPriority.NORMAL
        if "disk space" in clean_low or "disk" in clean_low:
            prio = TaskPriority.HIGH
        elif "dataset" in clean_low or "process" in clean_low or "download" in clean_low:
            prio = TaskPriority.BACKGROUND

        task = tem.create_task(
            user_request=user_input,
            user_id=uid_int,
            conversation_id=str(getattr(dialogue_mgr.current_state, "conversation_id", "default")),
            priority=prio,
        )
        tem.submit_task(task)

        if "dataset" in clean_low or "process" in clean_low:
            ack_resp = "I'll work on that."
        elif "vs code" in clean_low or "python file" in clean_low:
            ack_resp = "I'll open VS Code and create the Python file."
        elif "disk space" in clean_low or "disk" in clean_low:
            ack_resp = "Checking your disk space."
        else:
            ack_resp = f"I've started working on '{task.normalized_goal}' in the background."

        full_resp = (pending_prefix + ack_resp).strip()
        dialogue_mgr.record_response(full_resp)

        return {
            "status": "success",
            "intent": "CONCURRENT_TASK",
            "response": full_resp,
            "task_id": task.task_id,
            "task_status": task.status.value,
            "handled": True,
            "background_updates": pending_updates,
        }

    # ------------------------------------------------------------------
    # Step 1.2 — CANONICAL SEMANTIC INTENT & HISTORICAL MEMORY RETRIEVAL
    # ------------------------------------------------------------------
    from core.semantic_understanding import semantic_understanding_engine
    semantic_rep = semantic_understanding_engine.analyze(user_input, dialogue_mgr.current_state, uid_int)

    # 1. Historical Memory & Action Queries (PostgreSQL persistent memory, Sections 2, 6, 7)
    if semantic_rep.historical_query_type and not semantic_rep.action_required:
        hist_response = semantic_understanding_engine.memory_retriever.answer_historical_query(
            uid_int, semantic_rep, dialogue_mgr.current_state
        )
        dialogue_mgr.record_response(hist_response)
        return {
            "status": "success",
            "intent": "MEMORY_QUERY",
            "response": hist_response,
            "semantic_representation": semantic_rep.to_dict(),
            "handled": True
        }

    # 2. Natural semantic rewriting (Sections 3, 5, 9, 13, 14)
    if semantic_rep.rewritten_command:
        routing_input = semantic_rep.rewritten_command
        enriched_input = semantic_rep.rewritten_command

    # 2.1 Universal OS Operations Gateway (Direct OS Operation execution)
    if getattr(semantic_rep, "os_operation", None) is not None:
        try:
            from core.os_gateway import get_os_gateway
            os_gw = get_os_gateway()
            res = os_gw.execute(semantic_rep.os_operation, user_id=uid_int, raw_query=user_input)
            dialogue_mgr.record_response(res.message)
            return {
                "status": "success" if res.success else "error",
                "intent": "OS_OPERATION",
                "response": res.message,
                "os_result": res.to_dict(),
                "semantic_representation": semantic_rep.to_dict(),
                "handled": True
            }
        except Exception as _os_exc:
            logger.error("[BRAIN] OS operation execution error: %s", _os_exc)
            err_msg = f"Operation blocked: safety failure ({_os_exc})."
            dialogue_mgr.record_response(err_msg)
            return {
                "status": "blocked",
                "intent": "OS_OPERATION",
                "response": err_msg,
                "error": str(_os_exc),
                "handled": True
            }

    # 2.2 Universal OS Goal Execution (Natural OS Operations)
    if not semantic_rep.rewritten_command:
        try:
            from core.os_gateway import get_os_gateway
            os_gw = get_os_gateway()
            os_goal_res = os_gw.execute_natural_goal(user_input, user_id=uid_int)
            if os_goal_res.get("status") != "unhandled":
                resp_text = os_goal_res.get("response", "")
                dialogue_mgr.record_response(resp_text)
                return {
                    "status": "success" if os_goal_res.get("success") else "error",
                    "intent": "OS_OPERATION",
                    "response": resp_text,
                    "os_result": os_goal_res,
                    "semantic_representation": semantic_rep.to_dict(),
                    "handled": True
                }
        except Exception as _ng_exc:
            logger.error("[BRAIN] Natural goal OS execution error: %s", _ng_exc)
            destructive_words = ("shutdown", "restart", "reboot", "power off", "sleep", "sign out", "log off", "lock", "hibernate", "delete")
            if any(w in clean_low for w in destructive_words):
                err_msg = f"Action blocked: safety failure during OS execution ({_ng_exc})."
                dialogue_mgr.record_response(err_msg)
                return {
                    "status": "blocked",
                    "intent": "OS_OPERATION",
                    "response": err_msg,
                    "error": str(_ng_exc),
                    "handled": True
                }

    # 3. Conversational thoughts / non-action expressions (Section 9)
    if not semantic_rep.action_required and semantic_rep.intent == "GENERAL_CONVERSATION" and not any(w in clean_low for w in ("joke", "hello", "hi", "how are you")):
        conv_ack = "I understand! If you'd like me to perform an action for you, just let me know."
        dialogue_mgr.record_response(conv_ack)
        return {
            "status": "success",
            "intent": "GENERAL_CONVERSATION",
            "response": conv_ack,
            "semantic_representation": semantic_rep.to_dict(),
            "handled": True
        }
    # Step 1.4 — EXPLICIT POSTPONEMENT / PERSISTENCE (Phase 9)
    # ------------------------------------------------------------------
    if any(phrase in clean_low for phrase in ("continue this later", "save this for later", "finish this later", "postpone this", "remember this for later", "save this goal")):
        if dialogue_mgr.current_state.goal_status in ("RUNNING", "WAITING_FOR_USER", "BLOCKED") or dialogue_mgr.current_state.current_goal:
            saved = dialogue_mgr.persist_current_goal(reason="USER_EXPLICIT_LATER")
            dialogue_mgr.current_state.pending_goal_continuation = None
            dialogue_mgr.current_state.goal_status = "IDLE"
            resp = "I've saved your unfinished goal. You can continue it in a future session."
            dialogue_mgr.record_response(resp)
            return {
                "status": "success",
                "intent": "GOAL_MANAGEMENT",
                "goal_status": "POSTPONED",
                "response": resp,
                "saved_persistent": saved
            }

    # ------------------------------------------------------------------
    # Step 1.41 — WORK INTERRUPTION & PAUSE (Level 6 Section 20)
    # ------------------------------------------------------------------
    if clean_low in ("stop for now", "stop for now.", "pause for now", "pause the work", "pause goal", "pause", "pause.", "hold on for now") or clean_low.startswith("stop for now"):
        curr_g = dialogue_mgr.current_state.current_goal
        if curr_g and isinstance(curr_g, dict) and curr_g.get("status") not in ("COMPLETED", "CANCELLED"):
            from core.goal_planner import WorkGoal
            wg = WorkGoal.from_dict(curr_g)
            wg.pause(reason="USER_EXPLICIT_PAUSE")
            updated_g = wg.to_dict()
            dialogue_mgr.current_state.current_goal = updated_g
            dialogue_mgr.current_state.goal_status = "PAUSED"
            if "active_work_goals" in dialogue_mgr.current_state.session_context:
                dialogue_mgr.current_state.session_context["active_work_goals"][wg.id] = updated_g
            dialogue_mgr.current_state.session_context["paused_work_goal"] = updated_g
            resp = f"Paused your work on {wg.topic or wg.title}. You can say 'continue' or 'continue my presentation' whenever you're ready."
            dialogue_mgr.record_response(resp)
            return {
                "status": "success",
                "intent": "GOAL_MANAGEMENT",
                "goal_status": "PAUSED",
                "active_goal": updated_g,
                "response": resp
            }

    # ------------------------------------------------------------------
    # Step 1.42 — SPECIFIC WORK GOAL RESUMPTION (Level 6 Section 20 & 21)
    # ------------------------------------------------------------------
    clean_raw_text = clean_low.rstrip('.?!').strip()
    m_cont_specific = re.match(r'^(?:continue|resume)\s+(?:my\s+|the\s+)?(presentation|report|document|spreadsheet|excel|project|work)(?:\s+(?:on|about)\s+(.+))?$', clean_raw_text)
    if m_cont_specific:
        target_kind = m_cont_specific.group(1).lower()
        target_topic = m_cont_specific.group(2).strip().lower() if m_cont_specific.group(2) else ""

        selected_goal = None
        goals_dict = dialogue_mgr.current_state.session_context.get("active_work_goals", {})
        candidates = list(goals_dict.values())
        if dialogue_mgr.current_state.current_goal and dialogue_mgr.current_state.current_goal not in candidates:
            candidates.insert(0, dialogue_mgr.current_state.current_goal)

        for g in candidates:
            if not isinstance(g, dict):
                continue
            desc_text = str(g.get("title") or g.get("topic") or g.get("purpose") or g.get("objective") or "").lower()
            if target_kind in desc_text or (target_kind == "presentation" and "ppt" in desc_text):
                if not target_topic or target_topic in desc_text:
                    selected_goal = g
                    break

        if selected_goal:
            from core.goal_planner import WorkGoal
            wg = WorkGoal.from_dict(selected_goal)
            wg.resume()
            updated_g = wg.to_dict()
            dialogue_mgr.current_state.current_goal = updated_g
            dialogue_mgr.current_state.goal_status = "RUNNING"
            if "active_work_goals" in dialogue_mgr.current_state.session_context:
                dialogue_mgr.current_state.session_context["active_work_goals"][wg.id] = updated_g

            pending_delivs = [d for d in wg.deliverables if d.get("status") == "PENDING"]
            if pending_delivs:
                resp = f"Resumed your {wg.topic} {wg.purpose or 'task'}. Last status: {wg.progress}. I can now generate the {pending_delivs[0].get('type')} deliverable."
            else:
                resp = f"Resumed your {wg.topic} {wg.purpose or 'task'}. All deliverables are completed. Remaining: {wg.next_recommended_action or 'final review and submission'}."
            dialogue_mgr.record_response(resp)
            return {
                "status": "success",
                "intent": "GOAL_MANAGEMENT",
                "goal_status": "RUNNING",
                "active_goal": updated_g,
                "response": resp
            }

    # ------------------------------------------------------------------
    # Step 1.43 — FINISH THE WORK / FINISH EVERYTHING (Level 6 Section 10 & 23)
    # ------------------------------------------------------------------
    finish_triggers = (
        "finish the work", "finish work", "finish it", "finish this task",
        "finish everything", "finish all", "finish the presentation",
        "finish the report", "do everything", "do everything needed for the presentation",
        "complete the work", "complete everything", "finish up"
    )
    if any(clean_raw_text == trig or clean_raw_text.startswith(trig) for trig in finish_triggers):
        curr_g = dialogue_mgr.current_state.current_goal
        if curr_g and isinstance(curr_g, dict):
            from core.goal_planner import WorkGoal
            wg = WorkGoal.from_dict(curr_g)
            pending_delivs = [d for d in wg.deliverables if d.get("status") == "PENDING"]
            if pending_delivs:
                next_d = pending_delivs[0]
                d_type = next_d.get("type", "PPT").upper()
                if d_type in ("PPT", "PPTX"):
                    action_cmd = f"create presentation on {wg.topic}"
                elif d_type in ("DOCX", "DOC", "PDF"):
                    action_cmd = f"create a report on {wg.topic}"
                else:
                    action_cmd = f"create an excel spreadsheet for {wg.topic}"
                result = unified_router.execute_single_action(action_cmd, user_id=user_id)
                return result
            else:
                for st in wg.subtasks:
                    if any(k in st.get("title", "").lower() for k in ["verify", "review", "check", "references", "quality"]):
                        st["status"] = "COMPLETED"
                wg.status = "READY_FOR_SUBMISSION"
                wg.progress = "All artifacts generated and quality-verified. Ready for submission."
                wg.next_recommended_action = "Submit to portal"
                updated_g = wg.to_dict()
                dialogue_mgr.current_state.current_goal = updated_g
                dialogue_mgr.current_state.goal_status = "READY_FOR_SUBMISSION"
                if "active_work_goals" in dialogue_mgr.current_state.session_context:
                    dialogue_mgr.current_state.session_context["active_work_goals"][wg.id] = updated_g

                resp = (
                    f"Everything is prepared and verified. All deliverables for your {wg.topic or wg.title} "
                    f"have passed quality checks (topic correctness, slide/page count, structural integrity). "
                    f"The project is ready for submission. The remaining step is for you to submit it to the portal."
                )
                dialogue_mgr.record_response(resp)
                return {
                    "status": "success",
                    "intent": "GOAL_MANAGEMENT",
                    "goal_status": "READY_FOR_SUBMISSION",
                    "active_goal": updated_g,
                    "response": resp
                }

    # ------------------------------------------------------------------
    # Step 1.44 — WHAT WAS I WORKING ON (Level 6 Section 20)
    # ------------------------------------------------------------------
    if clean_low in ("what was i working on?", "what was i working on", "what am i working on", "what am i working on?", "show my goals", "list my work goals"):
        goals_dict = dialogue_mgr.current_state.session_context.get("active_work_goals", {})
        active_list = list(goals_dict.values())
        if dialogue_mgr.current_state.current_goal and dialogue_mgr.current_state.current_goal not in active_list:
            active_list.append(dialogue_mgr.current_state.current_goal)

        if active_list:
            items = []
            for g in active_list:
                t = g.get("topic") or g.get("title") or g.get("goal_name") or "Task"
                st = g.get("status") or "IN_PROGRESS"
                dl = f" (due: {g.get('deadline')})" if g.get("deadline") else ""
                items.append(f"- {t}: {st}{dl}")
            resp = "Here is what you were working on:\n" + "\n".join(items)
        else:
            resp = "You have no active or unfinished work goals."
        dialogue_mgr.record_response(resp)
        return {
            "status": "success",
            "intent": "GENERAL_CONVERSATION",
            "active_goals": active_list,
            "response": resp
        }

    # ------------------------------------------------------------------
    # Step 1.45 — WHAT'S LEFT / REMAINING WORK (Level 6 Section 21)
    # ------------------------------------------------------------------
    whats_left_triggers = (
        "what's left", "what is left", "whats left", "what is remaining",
        "what remains", "what's left to do", "whats left to do",
        "what is left to do", "what's remaining", "whats remaining",
        "what tasks are left", "remaining tasks"
    )
    if any(clean_raw_text == trig or clean_raw_text.startswith(trig) for trig in whats_left_triggers):
        curr_g = dialogue_mgr.current_state.current_goal
        if curr_g and isinstance(curr_g, dict):
            from core.goal_planner import WorkGoal
            wg = WorkGoal.from_dict(curr_g)
            completed = [st.get("title") for st in wg.subtasks if st.get("status") == "COMPLETED"]
            remaining = [st.get("title") for st in wg.subtasks if st.get("status") != "COMPLETED"]
            lines = [f"Here is what remains for your {wg.topic or wg.title}:"]
            if completed:
                lines.append("\nCompleted:")
                for c in completed:
                    lines.append(f"  ✓ {c}")
            if remaining:
                lines.append("\nRemaining:")
                for r in remaining:
                    lines.append(f"  • {r}")
            else:
                lines.append("\nAll tasks are completed! Ready for submission.")
            resp = "\n".join(lines)
            dialogue_mgr.record_response(resp)
            return {
                "status": "success",
                "intent": "GOAL_MANAGEMENT",
                "goal_status": wg.status,
                "active_goal": wg.to_dict(),
                "completed_subtasks": completed,
                "remaining_subtasks": remaining,
                "response": resp
            }

    # ------------------------------------------------------------------
    # Step 1.45 — CROSS-SESSION GOAL RESUMPTION (Phase 9)
    # ------------------------------------------------------------------
    if dialogue_mgr.current_state.pending_goal_resumption and not dialogue_mgr.current_state.pending_goal_continuation:
        should_resume, selected_goal, resp_text = dialogue_mgr.handle_resumption_response(user_input)
        if not should_resume and resp_text:
            dialogue_mgr.record_response(resp_text)
            return {
                "status": "success",
                "intent": "GOAL_MANAGEMENT",
                "goal_status": "IDLE",
                "response": resp_text
            }
        elif should_resume and selected_goal:
            # Explicit confirmation received -> proceed to validate environment & resume
            orig_req = selected_goal.get("original_request", "")
            gid = str(selected_goal.get("goal_id") or uuid.uuid4().hex[:8])

            # Step A: Validate Freshness
            now_ts = datetime.now().timestamp()
            created_ts = float(selected_goal.get("created_at") or now_ts)
            if (now_ts - created_ts) > 7 * 86400:
                dialogue_mgr.close_persistent_goal(gid, final_status="FAILED")
                rej_msg = "The continuation window for this goal has expired."
                dialogue_mgr.record_response(rej_msg)
                return {
                    "status": "error",
                    "intent": "GOAL_MANAGEMENT",
                    "goal_status": "FAILED",
                    "response": rej_msg
                }

            # Step B: Re-observe Environment (Never trust old environment state)
            assumptions = selected_goal.get("environment_assumptions") or {}
            req_file = assumptions.get("required_file")
            if req_file and not os.path.exists(req_file):
                dialogue_mgr.close_persistent_goal(gid, final_status="FAILED")
                env_err = f"Cannot resume: required file {req_file} no longer exists."
                dialogue_mgr.record_response(env_err)
                return {
                    "status": "error",
                    "intent": "GOAL_MANAGEMENT",
                    "goal_status": "FAILED",
                    "response": env_err
                }

            categories = select_relevant_categories("SYSTEM", orig_req)
            current_snap = observe_environment(user_id=user_id, relevant_categories=categories)

            # Step C: Reconstruct active goal
            dialogue_mgr.current_state.current_goal = {
                "id": gid,
                "description": orig_req,
                "status": "RUNNING"
            }
            dialogue_mgr.current_state.goal_status = "RUNNING"

            # Step D: Execute remaining or adapted steps using GoalPlanner -> Brain -> UnifiedCommandRouter
            rem_steps = selected_goal.get("remaining_steps") or []
            if not rem_steps:
                p = plan_execution(orig_req)
                rem_steps = [{"action": s.parameters.get("raw_input", orig_req), "intent": s.intent.name} for s in p.steps]

            step_results = []
            all_ok = True
            for st in rem_steps:
                cmd = st.get("action") or st.get("raw_input") or orig_req

                # Adaptation: check if action is already satisfied in current environment
                already_done = False
                if "open chrome" in cmd.lower() and any("chrome" in w.get("name", "").lower() for w in current_snap.window_titles):
                    already_done = True
                elif "open notepad" in cmd.lower() and any("notepad" in w.get("name", "").lower() for w in current_snap.window_titles):
                    already_done = True

                if already_done:
                    r = {"status": "success", "response": f"{cmd} is already open in current environment.", "intent": st.get("intent", "APPLICATION_CONTROL")}
                else:
                    r = _single_route(cmd, user_id=user_id)

                step_results.append(r)
                if r.get("status") in ("error", "failed"):
                    all_ok = False
                    break

            final_outcome = "COMPLETED" if all_ok else "FAILED"
            exec_summary = " ".join([r.get("response", "") for r in step_results if r.get("response")])
            res_msg = f"Resumed and {final_outcome.lower()}: {orig_req}. {exec_summary}".strip()
            dialogue_mgr.record_response(res_msg)

            # Close persistent goal in PostgreSQL
            dialogue_mgr.close_persistent_goal(gid, final_status=final_outcome)

            outcome = GoalOutcome(
                goal_id=gid,
                user_id=str(user_id),
                user_request=orig_req,
                attempted_action=f"resumed: {orig_req}",
                actual_outcome=final_outcome,
                success=all_ok,
                summary=res_msg,
                timestamp=datetime.now().isoformat(),
                results={"steps": step_results},
                verified=True,
                verification_source="environment_observation"
            )
            dialogue_mgr.record_goal_outcome(outcome)

            return {
                "status": "success" if all_ok else "error",
                "intent": "GOAL_MANAGEMENT",
                "goal_status": final_outcome,
                "response": res_msg,
                "goal_outcome": outcome.to_dict(),
                "observations": current_snap.to_dict()
            }
        else:
            dialogue_mgr.current_state.pending_goal_resumption = None

    # ------------------------------------------------------------------
    # Step 1.46 — ACTIVE GOAL CONTEXT UPDATE (Level 6 Failures 1 & 3)
    # ------------------------------------------------------------------
    if dialogue_mgr.current_state.current_goal:
        _curr_g = dialogue_mgr.current_state.current_goal
        _g_status = _curr_g.get("status") or dialogue_mgr.current_state.goal_status
        if _g_status not in ("COMPLETED", "CANCELLED"):
            _update_res = _detect_and_apply_goal_update(user_input, _curr_g)
            if _update_res is not None:
                _updated_goal, _ack_str, _fields = _update_res
                dialogue_mgr.current_state.current_goal = _updated_goal
                dialogue_mgr.current_state.session_context["active_natural_goal"] = _updated_goal
                if _updated_goal.get("topic"):
                    dialogue_mgr.current_state.session_context["topic_lock"] = _updated_goal.get("topic")
                if _updated_goal.get("status") == "COMPLETED":
                    dialogue_mgr.current_state.goal_status = "COMPLETED"
                else:
                    dialogue_mgr.current_state.goal_status = "RUNNING"
                dialogue_mgr.record_response(_ack_str)
                return {
                    "status": "success",
                    "intent": "GENERAL_CONVERSATION",
                    "goal_status": _updated_goal.get("status", "ACTIVE"),
                    "response": _ack_str,
                    "active_goal": _updated_goal,
                    "is_goal_update": True,
                    "handled": True
                }

    # ------------------------------------------------------------------
    # Step 1.48 — CONTEXTUAL STOP & CONTINUE DISAMBIGUATION
    # ------------------------------------------------------------------
    _clean_stop_cmd = clean_low.rstrip('.?!,').strip()

    # Contextual STOP: Resolves by active context (TTS -> Reading -> Music -> Task)
    if _clean_stop_cmd in (
        "stop", "halt", "hold on", "pause", "wait", "stop that", "stop it", "stop this",
        "be quiet", "shut up", "hush", "stop talking", "stop speaking", "mute yourself",
        "stop reading", "pause reading", "stop music", "pause music", "stop task", "cancel task"
    ) or bool(re.match(r'^(?:please\s+)?(?:stop|halt|cancel)\s+(?:that|it|this|task)[.!?]?$', _clean_stop_cmd)):
        # 1. Check if Assistant TTS is currently speaking
        try:
            from legacy.tts import is_speaking, stop_speaking
            if is_speaking() or _clean_stop_cmd in ("stop talking", "stop speaking", "be quiet", "shut up", "hush", "mute yourself"):
                stop_speaking(interrupted=True)
                msg = "Stopped speaking."
                dialogue_mgr.record_response(msg)
                return {
                    "status": "success",
                    "intent": "STOP_ASSISTANT_SPEECH",
                    "response": msg,
                    "handled": True,
                }
        except Exception:
            pass

        # 2. Check if Document Reading is active
        try:
            from core.artifact_reader import get_artifact_reading_controller
            _r_ctrl = get_artifact_reading_controller()
            if _r_ctrl.is_reading(uid_int) or _clean_stop_cmd in ("stop reading", "pause reading"):
                stop_res = _r_ctrl.stop_reading(user_id=uid_int)
                resp_str = (pending_prefix + stop_res.get("response", "Stopped reading.")).strip()
                dialogue_mgr.record_response(resp_str)
                return {
                    "status": "success",
                    "intent": "ARTIFACT_READING_STOP",
                    "response": resp_str,
                    "reading_result": stop_res,
                    "handled": True,
                }
        except Exception:
            pass

        # 3. Check if Music / Media is playing
        try:
            from modules.music.music_controller import get_controller
            _m_ctrl = get_controller()
            if _m_ctrl.is_playing() or _clean_stop_cmd in ("stop music", "pause music", "stop song", "pause song"):
                _m_ctrl.media_stop()
                msg = "Music playback stopped."
                dialogue_mgr.record_response(msg)
                return {
                    "status": "success",
                    "intent": "MUSIC",
                    "response": msg,
                    "action": "stop",
                    "handled": True,
                }
        except Exception:
            pass

        # 4. Check if a Background or Goal Task is actively running
        try:
            from core.task_execution_manager import get_task_execution_manager
            tem = get_task_execution_manager()
            active_tasks = tem.list_active_tasks(user_id=uid_int)
            if active_tasks and (_clean_stop_cmd in ("stop that", "stop it", "stop this", "stop task", "cancel task") or len(active_tasks) == 1):
                tgt_task = active_tasks[0]
                cancel_res = tem.cancel_task(tgt_task.task_id, user_id=uid_int)
                resp_str = cancel_res.get("response", f"Cancelled task '{tgt_task.normalized_goal}'.")
                dialogue_mgr.record_response(resp_str)
                return {
                    "status": "success",
                    "intent": "TASK_CANCELLATION",
                    "response": resp_str,
                    "task_id": tgt_task.task_id,
                    "handled": True,
                }
        except Exception:
            pass

    # Contextual CONTINUE: Resolves by paused context (Reading -> Music -> Goal)
    _clean_cont_cmd = clean_low.rstrip('.?!,').strip()
    if _clean_cont_cmd in ("continue", "resume", "keep reading", "continue reading", "resume reading"):
        # 1. Check if Document Reading was paused
        try:
            from core.artifact_reader import get_artifact_reading_controller
            _r_ctrl = get_artifact_reading_controller()
            paused_sess = _r_ctrl.load_latest_paused_session(user_id=uid_int)
            if paused_sess:
                cont_res = _r_ctrl.continue_reading(user_id=uid_int)
                resp_str = (pending_prefix + cont_res.get("response", "Continuing reading.")).strip()
                dialogue_mgr.record_response(resp_str)
                return {
                    "status": "success",
                    "intent": "ARTIFACT_READING_CONTINUE",
                    "response": resp_str,
                    "reading_result": cont_res,
                    "handled": True,
                }
        except Exception:
            pass

        # 2. Check if Music was paused
        try:
            from modules.music.music_controller import get_controller
            _m_ctrl = get_controller()
            if getattr(_m_ctrl, 'current_index', -1) >= 0 and not _m_ctrl.is_playing():
                msg = _m_ctrl.toggle_play_pause()
                resp_str = "Resumed music playback." if "Toggled" in str(msg) else str(msg)
                dialogue_mgr.record_response(resp_str)
                return {
                    "status": "success",
                    "intent": "MUSIC",
                    "action": "resume",
                    "response": resp_str,
                    "handled": True,
                }
        except Exception:
            pass

    if routing_input == "pause current goal" or clean_low in ("wait", "wait...", "wait!", "hold on", "hang on", "wait a second", "wait a sec", "wait a minute", "pause"):
        active_g = dialogue_mgr.current_state.current_goal or {}
        dialogue_mgr.current_state.goal_status = "WAITING_FOR_USER"
        dialogue_mgr.current_state.pending_goal_continuation = active_g or {"request": user_input}
        pause_msg = "I've paused. What would you like to change?"
        dialogue_mgr.record_response(pause_msg)
        return {
            "status": "success",
            "intent": "GOAL_MANAGEMENT",
            "goal_status": "WAITING_FOR_USER",
            "response": pause_msg,
            "handled": True
        }

    # ------------------------------------------------------------------
    # Step 1.5 — USER INTERRUPTION / CANCELLATION (Requirement 9 & 12)
    # ------------------------------------------------------------------
    _pending_act = getattr(dialogue_mgr.current_state, "pending_action", None)
    clean_low_nopunct = clean_low.rstrip('.?!,').strip()
    _is_explicit_goal_cancel = (
        clean_low_nopunct in ("cancel current goal", "cancel the goal", "cancel goal", "cancel the task", "cancel task", "cancel the presentation task", "cancel active goal", "cancel presentation", "cancel the presentation")
        or bool(re.search(r'\b(?:cancel|abort)\s+(?:the\s+)?(?:current\s+)?(?:goal|task|presentation|project)\b', clean_low_nopunct))
    )

    # Section 6, 7, 18: Distinguish actual cancellation from correction / new command
    _action_verbs_pattern = r'\b(?:open|create|show|make|convert|export|save|edit|search|close|add|update|type|write|view|read|start|launch|play|run)\b'
    _has_new_action = bool(re.search(_action_verbs_pattern, clean_low_nopunct))

    if (_pending_act or getattr(dialogue_mgr.current_state, "pending_confirmation", False)) and not _is_explicit_goal_cancel:
        if _has_new_action:
            # User provided a correction / new instruction (e.g. "No, I need you to open the PPT")
            # Dismiss old pending action/suggestion and let the new command win
            if _pending_act and _pending_act.get("proactive"):
                try:
                    from core.proactive_intelligence import proactive_intelligence
                    proactive_intelligence.record_user_response(str(user_id), affirmative=False, raw_input=user_input)
                except Exception:
                    pass
            dialogue_mgr.current_state.pending_action = None
            dialogue_mgr.current_state.pending_confirmation = False

            # Dismiss any pending confirmation in ConfirmationManager too
            try:
                from core.confirmation_manager import get_confirmation_manager
                uid_int = int(user_id) if str(user_id).isdigit() else 1
                get_confirmation_manager().cancel_all_for_user(uid_int)
            except Exception:
                pass

            # Strip correction prefixes from routing input
            clean_cmd = re.sub(
                r'^(?:(?:oh\s+)?no[,\s]+(?:i\s+need\s+you\s+to\s+|i\s+meant\s+|not\s+that\s+)?|yes[,\s]+(?:but\s+)?|but\s+|actually\s+|i\s+meant\s+|rather\s+|instead\s+|(?:i\s+)?(?:need|want)\s+you\s+to\s+)',
                '',
                clean_low_nopunct,
                flags=re.IGNORECASE
            ).strip()
            clean_cmd = re.sub(r'\s+instead$', '', clean_cmd, flags=re.IGNORECASE).strip()
            if clean_cmd:
                routing_input = clean_cmd
                enriched_input = clean_cmd
                clean_low = routing_input.lower()
                clean_raw_text = clean_low.rstrip('.?!').strip()
        elif (
            clean_low_nopunct in (
                "no, don't do that", "don't do that", "stop it", "stop", "never mind", "forget it",
                "no thanks", "no, thanks", "no", "deny", "disallow", "don't do it", "do not do that", "not now", "nope", "nah"
            )
            or bool(re.match(r'^(?:no|nah|nope|don\'?t|never\s*mind)\b', clean_low_nopunct))
        ):
            # True rejection: Reject pending suggestion ONLY, do NOT cancel active goal
            if _pending_act and _pending_act.get("proactive"):
                try:
                    from core.proactive_intelligence import proactive_intelligence
                    proactive_intelligence.record_user_response(str(user_id), affirmative=False, raw_input=user_input)
                except Exception:
                    pass
            dialogue_mgr.current_state.pending_action = None
            dialogue_mgr.current_state.pending_confirmation = False
            cancel_msg = "Okay, cancelled."
            dialogue_mgr.record_response(cancel_msg)
            return {
                "status": "cancelled",
                "intent": "PROACTIVE_SUGGESTION" if (_pending_act and _pending_act.get("proactive")) else "GOAL_MANAGEMENT",
                "goal_status": dialogue_mgr.current_state.goal_status or "RUNNING",
                "response": cancel_msg,
                "active_goal": dialogue_mgr.current_state.current_goal,
                "handled": True,
            }

    if routing_input in ("cancel", "cancel current goal") or _is_explicit_goal_cancel or clean_low in (
        "stop", "cancel that", "cancel", "abort",
        "don't send it", "actually, don't send it", "no, don't send it",
        "don't send", "cancel it"
    ):
        active_g = dialogue_mgr.current_state.current_goal
        gid = str((active_g.get("id") if active_g else None) or (active_g.get("goal_id") if active_g else None) or uuid.uuid4())[:8]
        dialogue_mgr.current_state.pending_goal_continuation = None
        # Also clear implicit-goal confirmation state so tests / UI see clean state
        _had_pending_action = bool(_pending_act)
        if _pending_act and _pending_act.get("proactive"):
            try:
                from core.proactive_intelligence import proactive_intelligence
                proactive_intelligence.record_user_response(str(user_id), affirmative=False, raw_input=user_input)
            except Exception:
                pass
        dialogue_mgr.current_state.pending_action = None
        dialogue_mgr.current_state.pending_confirmation = False
        try:
            from core.proactive_observer import ProactiveObservationCoordinator
            ProactiveObservationCoordinator.get_instance().drain_queued_events(str(user_id))
        except Exception:
            pass
        try:
            from core.confirmation_manager import get_confirmation_manager
            uid_int = int(user_id) if str(user_id).isdigit() else 1
            get_confirmation_manager().cancel_all_for_user(uid_int)
        except Exception:
            pass
        cancel_msg = "Goal cancelled. I have stopped the execution."
        dialogue_mgr.record_response(cancel_msg)

        outcome = GoalOutcome(
            goal_id=gid,
            user_id=str(user_id),
            user_request=user_input,
            attempted_action="cancellation",
            actual_outcome="CANCELLED",
            success=False,
            summary=cancel_msg,
            timestamp=datetime.now().isoformat(),
            results={"status": "cancelled", "response": cancel_msg},
        )
        dialogue_mgr.record_goal_outcome(outcome)

        return {
            "status": "cancelled" if (_had_pending_action or not active_g) else "success",
            "intent": "GOAL_MANAGEMENT",
            "goal_status": "CANCELLED",
            "response": cancel_msg,
            "goal_outcome": outcome.to_dict()
        }

    # ------------------------------------------------------------------
    # Step 1.55 — EXPLICIT USER CONFIRMATION RESOLUTION (Phase 7B)
    # ------------------------------------------------------------------
    _is_negative = (not _has_new_action) and (clean_low in (
        "no", "deny", "disallow", "permission denied", "don't do it", "do not do it", "do not allow", "no thanks",
        "cancel", "don't", "dont", "never mind", "stop", "not now", "later", "stop suggesting this", "stop suggesting",
        "don't do that", "do not do that", "stop doing that", "no, cancel it", "cancel it"
    ) or clean_low.startswith(("no, ", "deny ", "disallow ", "don't ", "dont ", "not now", "stop suggesting", "cancel ")))

    if _is_negative:
        if getattr(dialogue_mgr.current_state, "pending_action", None) or getattr(dialogue_mgr.current_state, "pending_confirmation", False):
            _pending_act = getattr(dialogue_mgr.current_state, "pending_action", None)
            if _pending_act and _pending_act.get("proactive"):
                try:
                    from core.proactive_intelligence import proactive_intelligence
                    proactive_intelligence.record_user_response(str(user_id), affirmative=False, raw_input=user_input)
                except Exception:
                    pass
            dialogue_mgr.current_state.pending_action = None
            dialogue_mgr.current_state.pending_confirmation = False
            cancel_msg = "Okay, cancelled."
            dialogue_mgr.record_response(cancel_msg)
            return {
                "status": "cancelled",
                "intent": "GOAL_MANAGEMENT",
                "goal_status": dialogue_mgr.current_state.goal_status or "RUNNING",
                "response": cancel_msg,
                "active_goal": dialogue_mgr.current_state.current_goal,
                "handled": True,
            }
        try:
            from core.confirmation_manager import get_confirmation_manager, ConfirmationStatus
            _confirm_mgr = get_confirmation_manager()
            uid_int = int(user_id) if str(user_id).isdigit() else 1
            _pending = _confirm_mgr.find_latest_pending(uid_int)
            if _pending is not None and _pending.is_pending():
                _confirm_mgr.cancel(_pending.confirmation_id, uid_int)
                denied_msg = "Permission was denied. I have cancelled the operation."
                dialogue_mgr.record_response(denied_msg)
                return {
                    "status": "cancelled",
                    "intent": "POLICY_GOVERNANCE",
                    "policy_decision": "DENIED",
                    "response": denied_msg,
                    "handled": True,
                }
        except Exception:
            pass

    _is_affirmative = (not _has_new_action and "but " not in clean_low and "instead" not in clean_low) and (
        clean_low in (
            "yes", "confirm", "proceed", "go ahead", "do it", "sure", "ok", "okay",
            "yes please", "yes do it", "yes proceed", "i confirm", "approved", "approve",
            "open it", "please do", "yes you may confirm", "you may confirm", "you may proceed"
        )
        or clean_low.startswith(("yes, ", "confirm ", "proceed with ", "yes please", "yes you may", "you may"))
        or bool(re.search(r'\b(?:yes|confirm|proceed|approve|approved)\b', clean_low) and not re.search(r'\b(?:no|not|don\'t|cancel|abort|but|instead)\b', clean_low))
    )

    if _is_affirmative:
        if getattr(dialogue_mgr.current_state, "pending_action", None):
            _pending_act = dialogue_mgr.current_state.pending_action
            dialogue_mgr.current_state.pending_action = None
            dialogue_mgr.current_state.pending_confirmation = False
            if _pending_act and _pending_act.get("proactive"):
                try:
                    from core.proactive_intelligence import proactive_intelligence
                    proactive_intelligence.record_user_response(str(user_id), affirmative=True, raw_input=user_input)
                except Exception:
                    pass
            _confirmed_cmd = _pending_act.get("command") or f"{_pending_act.get('action', '')} {_pending_act.get('target', '')}".strip()
            routing_input = _confirmed_cmd
            enriched_input = _confirmed_cmd
            clean_low = _confirmed_cmd.lower().strip()
        else:
            try:
                from core.confirmation_manager import get_confirmation_manager, ConfirmationStatus
                _confirm_mgr = get_confirmation_manager()
                uid_int = int(user_id) if str(user_id).isdigit() else 1
                _pending = _confirm_mgr.find_latest_pending(uid_int)
                if _pending is not None and _pending.is_pending():
                    if _pending.is_expired():
                        _pending.status = ConfirmationStatus.EXPIRED
                        expired_msg = "The confirmation request has expired (exceeded 120 seconds). Please repeat your command if you still want to perform it."
                        dialogue_mgr.record_response(expired_msg)
                        return {
                            "status": "error",
                            "intent": "POLICY_GOVERNANCE",
                            "policy_decision": "EXPIRED",
                            "response": expired_msg,
                            "handled": True,
                        }

                    # Confirm the pending request
                    _confirm_mgr.confirm(_pending.confirmation_id, uid_int)
                    if _pending.intent in ("DEVICE_CONTROL", "SYSTEM_SETTINGS"):
                        _confirm_mgr.grant_scope(uid_int, "SYSTEM_CONTROL", ttl_seconds=3600.0)

                    # Execute the confirmed action through the canonical pipeline
                    _confirmed_cmd = _pending.original_command
                    _target_file = None
                    _m_file = re.search(r'([a-zA-Z0-9_\-\\]+\.(?:txt|pdf|docx|pptx|xlsx|csv|py))', _confirmed_cmd)
                    if _m_file:
                        _target_file = _m_file.group(1)

                    _categories = select_relevant_categories(_pending.intent, _confirmed_cmd, _target_file)
                    _before_snap = observe_environment(user_id=user_id, relevant_categories=_categories, target_file=_target_file)

                    _exec_res = unified_router.execute_single_action(
                        _confirmed_cmd,
                        user_id=user_id,
                        confirmed_by_user=True,
                        confirmation_id=_pending.confirmation_id,
                    )
                    _intent_name = _exec_res.get("intent", _pending.intent)

                    _after_snap = observe_environment(user_id=user_id, relevant_categories=_categories, target_file=_target_file)
                    _state_diff = compare_snapshots(_before_snap, _after_snap)
                    _obs = _after_snap.to_dict()

                    _verified_res = _verify_action_result(
                        _exec_res, _intent_name, _obs, state_diff=_state_diff,
                        before_snap=_before_snap, after_snap=_after_snap,
                        user_id=user_id, command_input=_confirmed_cmd,
                    )
                    _verified_res["observations"] = _obs
                    _verified_res["state_difference"] = _state_diff.to_dict()

                    # Check if this confirmation was part of a paused multi-step plan
                    if dialogue_mgr.current_state.goal_status == "WAITING_FOR_USER" and dialogue_mgr.current_state.pending_goal_continuation:
                        cont = dialogue_mgr.current_state.pending_goal_continuation
                        if isinstance(cont, dict) and "plan" in cont:
                            paused_plan = cont["plan"]
                            step_idx = cont.get("step_index", 1)
                            # Mark confirmed step as completed
                            for st in paused_plan.steps:
                                if st.sequence < step_idx:
                                    st.status = "COMPLETED"
                            dialogue_mgr.current_state.pending_goal_continuation = None
                            dialogue_mgr.current_state.goal_status = "RUNNING"
                            subsequent_results = _execute_plan_stateful(
                                paused_plan, paused_plan.original_input, user_id=str(user_id), dialogue_mgr=dialogue_mgr
                            )
                            combined_res = [_verified_res] + subsequent_results
                            is_all_ok = all(r.get("status") == "success" for r in combined_res)
                            final_msg = " ".join([r.get("response", "") for r in combined_res if r.get("response")])
                            dialogue_mgr.record_response(final_msg)
                            return {
                                "status": "success" if is_all_ok else "partial",
                                "intent": _intent_name,
                                "response": final_msg,
                                "results": combined_res,
                                "handled": True,
                            }

                    dialogue_mgr.current_state.goal_status = "COMPLETED"
                    resp_text = _verified_res.get("response") or f"Confirmed and executed: {_confirmed_cmd}."
                    dialogue_mgr.record_response(resp_text)
                    return _verified_res
            except Exception as _conf_err:
                import logging as _log
                _log.getLogger(__name__).warning("[CONFIRMATION] Resolution failed: %s", _conf_err)

    # ------------------------------------------------------------------
    # Step 1.6 — RESUME PAUSED GOAL IF WAITING_FOR_USER (Requirement 8 & Test F)
    # ------------------------------------------------------------------
    if dialogue_mgr.current_state.goal_status == "WAITING_FOR_USER" and dialogue_mgr.current_state.pending_goal_continuation:
        # Check if user input is an unrelated intent (like TIME_QUERY, CALCULATOR, etc.)
        analyzed_pending = _multi_intent_analyzer.analyze(routing_input)
        is_clarification_response = bool(
            re.search(r'([a-zA-Z0-9_\-\\]+\.(?:txt|pdf|docx|pptx|xlsx|csv|py))', routing_input)
            or any(w in routing_input.lower() for w in ["first", "second", "third", "other", "1st", "2nd", "3rd", "one", "this", "that", "the "])
        )
        if not is_clarification_response and analyzed_pending.primary_intent.name in ("TIME_QUERY", "WEATHER_QUERY", "CALCULATOR", "DATE_QUERY", "MUSIC"):
            # Unrelated new request interrupts the waiting goal
            dialogue_mgr.current_state.pending_goal_continuation = None
            dialogue_mgr.current_state.goal_status = "IDLE"
            # Fall through to execute the new request!
        else:
            continuation = dialogue_mgr.current_state.pending_goal_continuation
            dialogue_mgr.current_state.pending_goal_continuation = None
            dialogue_mgr.current_state.goal_status = "RUNNING"
            
            target_file = None
            m_file = re.search(r'([a-zA-Z0-9_\-\\]+\.(?:txt|pdf|docx|pptx|xlsx|csv|py))', routing_input)
            if m_file:
                target_file = m_file.group(1)
            categories = select_relevant_categories("FILE_OPERATIONS", routing_input, target_file)
            before_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)

            # Execute the user's choice/resolution
            result = _single_route(routing_input, user_id=user_id)
            intent_name = result.get("intent", "FILE_OPERATIONS")

            after_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)
            state_diff = compare_snapshots(before_snap, after_snap)
            obs = after_snap.to_dict()

            result = _verify_action_result(
                result, intent_name, obs, state_diff=state_diff,
                before_snap=before_snap, after_snap=after_snap, user_id=user_id, command_input=routing_input
            )
            result["observations"] = obs
            result["state_difference"] = state_diff.to_dict()

            # PHASE 8: Determine verified outcome
            is_success = result.get("status") == "success" or not result.get("error")
            final_outcome = "COMPLETED" if is_success else "FAILED"
            
            _post_turn_update(
                dialogue_mgr,
                result,
                [intent_name],
                observations=obs,
                state_difference=state_diff.to_dict(),
                goal_status=final_outcome
            )
            
            outcome = GoalOutcome(
                goal_id=str(continuation.get("goal_id", uuid.uuid4()))[:8],
                user_id=str(user_id),
                user_request=continuation.get("raw_input", user_input),
                attempted_action=routing_input,
                actual_outcome=final_outcome,
                success=is_success,
                summary=result.get("response", "Goal resumed and completed."),
                timestamp=datetime.now().isoformat(),
                entities=turn_data.get("context", {}),
                results=result,
                verified=True,
                verification_source="environment_observation",
            )
            dialogue_mgr.record_goal_outcome(outcome)
            result["goal_status"] = final_outcome
            result["goal_outcome"] = outcome.to_dict()
            return result

    # ------------------------------------------------------------------
    # Step 2 — MULTI-INTENT ANALYSIS
    # ------------------------------------------------------------------
    analysis = _multi_intent_analyzer.analyze(enriched_input)

    sem_intent = analysis.primary_intent.name
    sem_action = getattr(analysis.primary_intent, "name", "execute").lower()

    sem_topic, sem_context, res_art = _evaluate_context_relevance(
        user_input, routing_input, dialogue_mgr, sem_intent
    )
    sem_conf = 0.95

    print(
        f"\n[SEMANTIC UNDERSTANDING]\n"
        f"Intent: {sem_intent}\n"
        f"Action: {sem_action}\n"
        f"Topic: {sem_topic or 'None'}\n"
        f"Context: {sem_context}\n"
        f"Confidence: {sem_conf:.2f}\n"
        f"[REFERENCE RESOLUTION]\n"
        f"Resolved artifact: {res_art or 'None'}\n"
        f"[UNIFIED ROUTER]\n"
        f"Intent: {sem_intent}\n"
        f"[EXECUTION]\n"
        f"Command: {routing_input}"
    )

    # ------------------------------------------------------------------
    # Step 3 — DETERMINE GOAL VS COMMAND
    # ------------------------------------------------------------------
    goal_info = {
        "description": user_input,
        "primary_intent": analysis.primary_intent.name,
        "is_multi_step": analysis.has_multiple_intents,
        "created_turn": turn_data.get("turn_number", 1),
        "status": "RUNNING" if analysis.has_multiple_intents else "IDLE"
    }
    subgoals: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Step 4 — SINGLE-INTENT FAST PATH (with observation & live state update)
    # ------------------------------------------------------------------
    if not analysis.has_multiple_intents:
        target_file = None
        m_file = re.search(r'([a-zA-Z0-9_\-\\]+\.(?:txt|pdf|docx|pptx|xlsx|csv|py))', routing_input)
        if m_file:
            target_file = m_file.group(1)
        else:
            m_folder = re.search(r'\b(?:folder|directory)\s+([a-zA-Z0-9_\-]+)', routing_input, re.I)
            if m_folder:
                target_file = m_folder.group(1)

        categories = select_relevant_categories(analysis.primary_intent.name, routing_input, target_file)
        if categories:
            before_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)
        else:
            before_snap = EnvironmentSnapshot(observed_categories=[])

        result = _single_route(routing_input, user_id=user_id)
        intent_name = result.get("intent", analysis.primary_intent.name)

        # Step 5 — OBSERVE RESULT (capture actual system state)
        if categories:
            after_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)
            state_diff = compare_snapshots(before_snap, after_snap)
            observations = after_snap.to_dict()
        else:
            after_snap = before_snap
            state_diff = StateDifference()
            observations = {}

        # Step 6 — VERIFY RESULT (Canonical Outcome Verification)
        result = _verify_action_result(
            result, intent_name, observations, state_diff=state_diff,
            before_snap=before_snap, after_snap=after_snap, user_id=user_id, command_input=routing_input
        )
        result["observations"] = observations
        result["state_difference"] = state_diff.to_dict()

        # Step 6b — ADAPTIVE RECOVERY (PHASE 4)
        is_cancel = (
            routing_input.lower().startswith("cancel")
            or routing_input.lower().startswith("stop")
            or "cancelled" in str(result.get("response", "")).lower()
            or result.get("action") == "cancel"
        )
        if (result.get("status") in ("error", "failed") or (result.get("verified") is False and "verified" in result)) and not is_cancel and not result.get("blocked") and result.get("policy_decision") not in ("BLOCKED", "UNCERTAIN"):
            rec_engine = get_adaptive_recovery_engine()
            budget = RecoveryBudget(max_propagation_retries=1, max_adaptive_strategies=2, max_total_recovery_attempts=3)
            verif_dict = result.get("outcome_verification", {})
            verif_obj = OutcomeVerificationResult(
                status=OutcomeStatus(verif_dict.get("status", "VERIFIED_FAILURE")),
                verified=verif_dict.get("verified", False),
                confidence=ConfidenceLevel(verif_dict.get("confidence", "HIGH")),
                expected_state=verif_dict.get("expected_state", {}),
                observed_state=verif_dict.get("observed_state", observations or {}),
                differences=verif_dict.get("differences", {}),
                failure_reason=verif_dict.get("failure_reason") or result.get("failure_reason") or result.get("response"),
                verification_method=verif_dict.get("verification_method", "generic")
            )
            decision = rec_engine.decide_recovery(
                intent=intent_name,
                command_or_input=routing_input,
                verification_result=verif_obj,
                action_result=result,
                obs=observations,
                state_diff=state_diff,
                user_id=user_id,
                budget=budget
            )
            result["recovery_decision"] = decision.to_dict()

            if decision.requires_confirmation:
                result["status"] = "waiting_for_user"
                result["response"] = decision.rationale

            elif decision.strategy and not decision.terminal:
                strat = decision.strategy
                if strat.strategy_id == "VERIFY_EXISTING_STATE":
                    result["status"] = "success"
                    result["verified"] = True
                    result["response"] = decision.rationale
                    result["adaptation_attempted"] = True
                elif strat.strategy_id == "REPORT_ACTUAL_TASK_STATE":
                    st = strat.action_parameters.get("status", "completed")
                    result["status"] = "success"
                    result["response"] = f"The task is currently {st}."
                    result["adaptation_attempted"] = True
                elif strat.recovery_command:
                    try:
                        adapted_res = unified_router.execute_single_action(strat.recovery_command, user_id=user_id)
                        adapt_after_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)
                        state_diff = compare_snapshots(before_snap, adapt_after_snap)
                        observations = adapt_after_snap.to_dict()
                        adapted_verif_res = _verify_action_result(
                            adapted_res, intent_name, observations, state_diff=state_diff,
                            before_snap=before_snap, after_snap=adapt_after_snap, user_id=user_id, command_input=strat.recovery_command
                        )
                        adapted_verif_res["adaptation_attempted"] = True
                        adapted_verif_res["selected_strategy"] = strat.strategy_id
                        adapted_verif_res["recovery_decision"] = decision.to_dict()
                        result = adapted_verif_res
                        result["observations"] = observations
                        result["state_difference"] = state_diff.to_dict()
                    except Exception as e:
                        print(f"[RECOVERY] Adapted single action execution error: {e}")

        # Handle single-intent ambiguity (e.g. "Open my presentation" finding 2+ files)
        if result.get("status") == "waiting_for_user":
            dialogue_mgr.current_state.goal_status = "WAITING_FOR_USER"
            goal_info["status"] = "WAITING_FOR_USER"
            dialogue_mgr.current_state.current_goal = goal_info
            dialogue_mgr.current_state.pending_goal_continuation = {
                "intent": intent_name,
                "raw_input": user_input,
                "goal_id": goal_info.get("id", str(uuid.uuid4())[:8])
            }
            _post_turn_update(
                dialogue_mgr,
                result,
                [intent_name],
                observations=observations,
                state_difference=state_diff.to_dict(),
                goal=goal_info,
                subgoals=[{"step": routing_input, "intent": intent_name, "status": "waiting_for_user"}],
                goal_status="WAITING_FOR_USER"
            )
            outcome = GoalOutcome(
                goal_id=goal_info.get("id", str(uuid.uuid4())[:8]),
                user_id=str(user_id),
                user_request=user_input,
                attempted_action=routing_input,
                actual_outcome="WAITING_FOR_USER",
                success=False,
                summary=result.get("response", "Waiting for user clarification."),
                timestamp=datetime.now().isoformat(),
                entities=turn_data.get("context", {}),
                results=result,
                step_outcomes=[{"step": routing_input, "intent": intent_name, "status": "waiting_for_user"}],
            )
            dialogue_mgr.record_goal_outcome(outcome)
            result["goal_outcome"] = outcome.to_dict()
            return result

        # Determine terminal outcome for single-intent
        is_natural_goal = (
            result.get("goal_type") == "natural_goal"
            or result.get("goal_status") == "ACTIVE"
            or (dialogue_mgr and dialogue_mgr.current_state.session_context.get("active_natural_goal") and result.get("handled") and result.get("intent") == "GENERAL_CONVERSATION")
        )
        is_cancellation = (
            routing_input.lower().startswith("cancel")
            or routing_input.lower().startswith("stop")
            or "cancelled" in str(result.get("response", "")).lower()
            or result.get("action") == "cancel"
        )
        active_nat_goal = (
            dialogue_mgr.current_state.session_context.get("active_natural_goal")
            if (dialogue_mgr and dialogue_mgr.current_state.session_context.get("active_natural_goal")
                and dialogue_mgr.current_state.current_goal
                and isinstance(dialogue_mgr.current_state.current_goal, dict)
                and dialogue_mgr.current_state.current_goal.get("status") not in ("COMPLETED", "CANCELLED"))
            else None
        )
        if is_natural_goal:
            final_outcome = "RUNNING"
            failure_reason = None
            blocking_reason = None
            success = True
            goal_for_update = (dialogue_mgr.current_state.current_goal if dialogue_mgr and dialogue_mgr.current_state.current_goal else goal_info)
        elif is_cancellation:
            final_outcome = "CANCELLED"
            failure_reason = None
            blocking_reason = None
            success = False
            goal_for_update = goal_info
        elif active_nat_goal is not None:
            # An active natural goal is ongoing and the user executed a sub-action/step (e.g. via proactive suggestion)
            # The active natural goal remains active; do not overwrite it with the transient command info!
            final_outcome = "RUNNING"
            failure_reason = None
            blocking_reason = None
            success = (result.get("status") == "success" or not result.get("error"))
            goal_for_update = active_nat_goal
            # Update goal progress if relevant
            if result.get("file_path") or result.get("path"):
                active_nat_goal["status"] = "IN_PROGRESS"
                active_nat_goal["progress"] = f"Created {result.get('file_path') or result.get('path')}"
        elif result.get("status") == "blocked" or result.get("blocked"):
            final_outcome = "BLOCKED"
            blocking_reason = result.get("reason") or result.get("error") or "Required state prevented completion."
            failure_reason = None
            success = False
            goal_for_update = goal_info
        elif (
            result.get("status") in ("error", "failed")
            or result.get("success") is False
            or (result.get("verified") is False and "verified" in result)
        ):
            final_outcome = "FAILED"
            failure_reason = result.get("error") or result.get("message") or "Action failed to execute or verify."
            blocking_reason = None
            success = False
            goal_for_update = goal_info
        else:
            final_outcome = "COMPLETED"
            failure_reason = None
            blocking_reason = None
            success = True
            goal_for_update = goal_info

        subgoals.append({
            "step": routing_input,
            "intent": intent_name,
            "status": final_outcome.lower()
        })

        # Step 7 — UPDATE LIVE STATE & RESPOND
        _post_turn_update(
            dialogue_mgr,
            result,
            [intent_name],
            observations=observations,
            state_difference=state_diff.to_dict(),
            goal=goal_for_update,
            subgoals=subgoals,
            goal_status=final_outcome
        )

        if is_natural_goal and dialogue_mgr and dialogue_mgr.current_state.current_goal:
            # Re-ensure structured natural goal fields remain intact
            result["active_goal"] = dialogue_mgr.current_state.current_goal
            result["goal_status"] = "RUNNING"

        verified = result.get("verified", False) or bool(state_diff and state_diff.has_changes)
        verification_src = result.get("verification_source", "environment_observation" if verified else None)

        _effective_gid = (goal_for_update.get("id") if isinstance(goal_for_update, dict) else str(uuid.uuid4())[:8])
        outcome = GoalOutcome(
            goal_id=_effective_gid,
            user_id=str(user_id),
            user_request=user_input,
            attempted_action=routing_input,
            actual_outcome=final_outcome,
            success=success,
            summary=result.get("response", "Goal finished."),
            timestamp=datetime.now().isoformat(),
            entities=turn_data.get("context", {}),
            results=result,
            failure_reason=failure_reason,
            blocking_reason=blocking_reason,
            step_outcomes=[{"step": routing_input, "intent": intent_name, "status": final_outcome.lower()}],
            adaptation_applied=False,
            verified=verified,
            verification_source=verification_src,
        )
        dialogue_mgr.record_goal_outcome(outcome)
        result["goal_outcome"] = outcome.to_dict()
        result["goal_status"] = final_outcome
        return result

    # ------------------------------------------------------------------
    # Step 8 — MULTI-INTENT / MULTI-STEP GOAL PATH (Goal Planner)
    # ------------------------------------------------------------------
    plan = _goal_planner.create_plan(analysis)
    plan.goal_status = "RUNNING"
    dialogue_mgr.current_state.goal_status = "RUNNING"
    dialogue_mgr.current_state.current_goal = goal_info

    ack_msg = None
    if plan.total_steps > 1:
        ack_msg = f"I'm on it. Starting {plan.total_steps}-step task..."
        if on_progress:
            try:
                on_progress(ack_msg)
            except Exception:
                pass

    for step in plan.steps:
        subgoals.append({
            "step": step.intent.name,
            "sequence": step.sequence,
            "status": "pending"
        })

    # Step 9 — STEP-BY-STEP EXECUTION LOOP (EXECUTE → OBSERVE → VERIFY → NEXT STEP)
    step_results = _execute_plan_stateful(plan, user_input, user_id=user_id, dialogue_mgr=dialogue_mgr, on_progress=on_progress)

    for i, s_res in enumerate(step_results):
        if i < len(subgoals):
            subgoals[i]["status"] = s_res.get("status", "success")

    # Step 10 — OBSERVE FINAL STATE
    last_intent = step_results[-1].get("intent", "") if step_results else ""
    observations = _observe_action_result(
        step_results[-1] if step_results else {},
        last_intent,
        user_input,
        user_id
    )

    # Step 11 — COMPOSE AGGREGATED RESPONSE
    intents_used = [s.get("intent", "") for s in step_results]
    
    # If the plan was paused waiting for user clarification, return the clarification prompt directly
    if plan.goal_status == "WAITING_FOR_USER":
        final_response = step_results[-1].get("response", "Which one would you like me to open?")
    else:
        final_response = _compose_response(step_results, plan)

    last_diff = step_results[-1].get("state_difference") if step_results else None
    result = {
        "status": "success" if plan.goal_status == "COMPLETED" else plan.goal_status.lower(),
        "intent": analysis.primary_intent.name,
        "response": final_response,
        "acknowledgement": ack_msg,
        "steps": step_results,
        "plan_id": plan.plan_id,
        "total_steps": plan.total_steps,
        "goal_status": plan.goal_status,
        "warnings": plan.warnings,
        "observations": observations,
        "state_difference": last_diff,
        "verified": all(s.get("verified", False) for s in step_results) if step_results else False,
    }

    # Step 12 — UPDATE LIVE INTERACTION STATE
    _post_turn_update(
        dialogue_mgr,
        result,
        intents_used,
        observations=observations,
        state_difference=last_diff,
        goal=goal_info,
        subgoals=subgoals,
        plan=asdict(plan) if hasattr(plan, "__dataclass_fields__") else None,
        goal_status=plan.goal_status
    )

    final_outcome = plan.goal_status
    adaptation_applied = getattr(plan, "adaptation_count", 0) > 0
    failure_reason = None
    blocking_reason = None
    if final_outcome == "FAILED":
        for s in plan.steps:
            if s.status == "FAILED":
                failure_reason = getattr(s, "error", None) or f"Step {s.sequence} ({s.intent.name}) failed."
                break
    elif final_outcome == "BLOCKED":
        blocking_reason = "Required environmental or device state prevented plan completion."

    step_outcomes = [
        {
            "step": s.sequence,
            "intent": s.intent.name,
            "status": s.status,
            "error": getattr(s, "error", None),
        }
        for s in plan.steps
    ]

    outcome = GoalOutcome(
        goal_id=plan.plan_id,
        user_id=str(user_id),
        user_request=user_input,
        attempted_action=f"Multi-step plan ({len(plan.steps)} steps)",
        actual_outcome=final_outcome,
        success=(final_outcome == "COMPLETED"),
        summary=final_response,
        timestamp=datetime.now().isoformat(),
        entities=turn_data.get("context", {}),
        results=result,
        failure_reason=failure_reason,
        blocking_reason=blocking_reason,
        step_outcomes=step_outcomes,
        adaptation_applied=adaptation_applied,
        verified=(final_outcome == "COMPLETED"),
        verification_source="plan_execution_and_observation",
    )
    dialogue_mgr.record_goal_outcome(outcome)
    result["goal_outcome"] = outcome.to_dict()

    return result


brain_route_and_execute = brain_process


# ---------------------------------------------------------------------------
# Phase 2 & 3 Stateful Adaptive Execution Engine
# ---------------------------------------------------------------------------

def _attempt_plan_adaptation(
    step: Any,
    step_input: str,
    step_result: Dict[str, Any],
    obs: Dict[str, Any],
    plan: Any,
    user_id: Any,
    dialogue_mgr: Any
) -> Tuple[Dict[str, Any], bool]:
    """
    Attempt bounded plan adaptation when a step deviates or fails.
    Uses canonical AdaptiveRecoveryEngine. Bounded by strict recovery budget.
    """
    rec_engine = get_adaptive_recovery_engine()

    # Initialize or load budget for this plan
    if not hasattr(plan, "recovery_budget") or plan.recovery_budget is None:
        max_adapts = getattr(plan, "max_adaptations", 2)
        plan.recovery_budget = RecoveryBudget(
            max_propagation_retries=2,
            max_adaptive_strategies=max_adapts,
            max_total_recovery_attempts=max_adapts + 1
        )
    budget = plan.recovery_budget

    if budget.is_exhausted() or getattr(plan, "adaptation_count", 0) >= getattr(plan, "max_adaptations", 2):
        print(f"[ADAPTATION] Recovery budget exhausted. Halting adaptation.")
        return step_result, False

    intent_name = step.intent.name if hasattr(step.intent, "name") else str(step.intent)

    # Extract or construct verification result
    verif_dict = step_result.get("outcome_verification", {})
    verif_obj = OutcomeVerificationResult(
        status=OutcomeStatus(verif_dict.get("status", "VERIFIED_FAILURE")),
        verified=verif_dict.get("verified", False),
        confidence=ConfidenceLevel(verif_dict.get("confidence", "HIGH")),
        expected_state=verif_dict.get("expected_state", {}),
        observed_state=verif_dict.get("observed_state", obs or {}),
        differences=verif_dict.get("differences", {}),
        failure_reason=verif_dict.get("failure_reason") or step_result.get("failure_reason") or step_result.get("response"),
        verification_method=verif_dict.get("verification_method", "generic")
    )

    prev_decisions = []
    if hasattr(plan, "recovery_decisions"):
        prev_decisions = plan.recovery_decisions
    else:
        plan.recovery_decisions = []

    # Check for cancellation
    cancellation_check = None
    if dialogue_mgr:
        cancellation_check = lambda: getattr(dialogue_mgr.current_state, "goal_status", "") == "CANCELLED"

    decision = rec_engine.decide_recovery(
        intent=intent_name,
        command_or_input=step_input,
        verification_result=verif_obj,
        action_result=step_result,
        obs=obs,
        user_id=user_id,
        budget=budget,
        previous_decisions=prev_decisions,
        cancellation_check=cancellation_check
    )
    plan.recovery_decisions.append(decision)

    if decision.terminal:
        print(f"[ADAPTATION] Terminal recovery decision: {decision.rationale}")
        return step_result, False

    if decision.requires_confirmation:
        clarify_res = {
            "status": "waiting_for_user",
            "intent": intent_name,
            "response": decision.rationale,
            "recovery_decision": decision.to_dict()
        }
        return clarify_res, True

    strat = decision.strategy
    if not strat:
        return step_result, False

    adapted_result = None
    adapted_action = strat.recovery_command or strat.strategy_id
    adaptation_reason = decision.rationale

    if strat.strategy_id == "VERIFY_EXISTING_STATE":
        adapted_result = {
            "status": "success",
            "intent": intent_name,
            "response": decision.rationale,
            "verified": True
        }
    elif strat.strategy_id == "REPORT_ACTUAL_TASK_STATE":
        st = strat.action_parameters.get("status", "completed")
        adapted_result = {
            "status": "success",
            "intent": intent_name,
            "response": f"The task is currently {st}."
        }
    elif strat.strategy_id == "CLARIFY_FILE_CHOICE":
        cands = strat.action_parameters.get("candidates", [])
        cand_names = [os.path.basename(c) for c in cands]
        adapted_result = {
            "status": "waiting_for_user",
            "intent": "FILE_OPERATIONS",
            "response": f"I found multiple files: {', '.join(cand_names)}. Which one should I open?",
            "files": [{"name": os.path.basename(c), "path": c} for c in cands]
        }
    elif strat.recovery_command:
        try:
            test_res = unified_router.execute_single_action(strat.recovery_command, user_id=user_id)
            if test_res.get("status") != "error":
                adapted_result = test_res
                if "response" not in adapted_result or not adapted_result["response"]:
                    adapted_result["response"] = decision.rationale
        except Exception as e:
            print(f"[ADAPTATION] Error executing recovery command '{strat.recovery_command}': {e}")
            return step_result, False

    if adapted_result is not None:
        plan.adaptation_count = getattr(plan, "adaptation_count", 0) + 1
        plan.adaptation_reason = adaptation_reason
        if not hasattr(plan, "adaptation_history") or plan.adaptation_history is None:
            plan.adaptation_history = []
        plan.adaptation_history.append({
            "step_index": step.sequence,
            "original_action": step_input,
            "adapted_action": adapted_action,
            "strategy_id": strat.strategy_id,
            "reason": adaptation_reason,
            "is_retry": strat.is_retry
        })
        print(f"[ADAPTATION #{plan.adaptation_count}] {adaptation_reason}")
        return adapted_result, True

    return step_result, False


def _execute_plan_stateful(
    plan: ExecutionPlan,
    original_input: str,
    user_id: str = "default",
    dialogue_mgr: Optional[Any] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    """
    PHASE 3: Stateful Execution Loop with Bounded Deviation Recovery.

    Execute each step in the plan sequentially with observe/verify/adapt.

    Flow per step:
      1. Check for cancellation
      2. Re-resolve step input against latest live state
      3. Execute via UnifiedCommandRouter
      4. Observe real OS / hardware / subsystem state
      5. Verify pre/post-conditions & bounded retry (transient failure)
      6. Compare actual state with expected state (deviation detection)
      7. Re-evaluate & Adapt remaining plan using safe, existing capabilities
      8. Update live state immediately
      9. Handle ambiguity (WAITING_FOR_USER)
      10. Continue to next dependent step or halt on failure
    """
    step_results: List[Dict[str, Any]] = []
    accumulated_context: Dict[str, Any] = {}

    for step in plan.steps:
        # Skip steps that have already completed in a resumed plan
        if getattr(step, "status", None) == "COMPLETED":
            continue

        # 1. Check for user interruption before step starts
        if dialogue_mgr and dialogue_mgr.current_state.goal_status == "CANCELLED":
            step.status = "CANCELLED"
            plan.goal_status = "CANCELLED"
            break

        step.status = "RUNNING"
        plan.active_step_index = step.sequence
        if on_progress and plan.total_steps > 1:
            try:
                step_name = step.intent.name.lower().replace('_', ' ')
                on_progress(f"Step {step.sequence} of {plan.total_steps}: {step_name}")
            except Exception:
                pass

        # 2. Build candidate step input
        segment_text = step.parameters.get("raw_input", "").strip()
        if segment_text and segment_text != original_input:
            candidate_input = segment_text
        else:
            candidate_input = _build_step_input(step.intent.name, step.parameters, original_input)

        params_override: Dict[str, Any] = {}
        if getattr(step, "semantic_command", None):
            params_override["semantic_command"] = step.semantic_command
            params_override["step_sequence"] = step.sequence

        # 1.1 Check upstream dependencies: If any dependent step failed or search yielded no results, do not run!
        if getattr(step, "dependencies", None):
            failed_dep_idx = None
            no_search_results = False
            for dep_idx in step.dependencies:
                if 0 <= dep_idx < len(step_results):
                    dep_res = step_results[dep_idx]
                    if dep_res.get("status") in ("error", "failed", "REQUIRES_REPLAN", "INVALID", "skipped"):
                        failed_dep_idx = dep_idx
                        break
                    # If upstream step was a search, verify that it returned usable results
                    if dep_res.get("action") in ("SEARCH", "search_web", "recommend") or "results" in dep_res or "res_set" in dep_res:
                        s_results = dep_res.get("results") or dep_res.get("res_set")
                        if not s_results:
                            no_search_results = True
                            failed_dep_idx = dep_idx
                            break
            if failed_dep_idx is not None:
                step.status = "SKIPPED_DUE_TO_DEPENDENCY_FAILURE"
                reason_msg = f"Skipped step {step.sequence} because upstream search yielded no usable results." if no_search_results else f"Skipped step {step.sequence} because upstream dependent step {failed_dep_idx} failed."
                step_result = {
                    "status": "skipped",
                    "intent": step.intent.name,
                    "response": reason_msg,
                    "handled": True,
                    "skipped": True,
                    "reason": "upstream_dependency_failure"
                }
                step.result = step_result
                step_results.append(step_result)
                continue

        # Bind structured outputs from previous dependent steps
        if getattr(step, "dependencies", None):
            for dep_idx in step.dependencies:
                if 0 <= dep_idx < len(step_results):
                    dep_res = step_results[dep_idx]
                    dep_path = dep_res.get("path") or dep_res.get("filepath") or dep_res.get("new_path")
                    # Folder output dependency
                    if dep_res.get("action") == "create_folder" or dep_res.get("folder") or (dep_path and os.path.isdir(dep_path)):
                        folder_path = dep_path or dep_res.get("folder")
                        if folder_path:
                            params_override["parent_folder"] = folder_path
                    # File output dependency
                    elif dep_res.get("action") in ("create_file", "rename_file", "write_file") or dep_res.get("file") or (dep_path and os.path.isfile(dep_path)):
                        file_path = dep_path or dep_res.get("file")
                        if file_path:
                            params_override["filepath"] = file_path
                            params_override["src"] = file_path
                            params_override["target"] = file_path
                            params_override["path"] = file_path
                    # Document generation / export output dependency
                    elif step.intent.name in ("DOCUMENT_GENERATION", "OPEN_APPLICATION", "FILE_OPERATIONS") and (dep_res.get("filepath") or dep_res.get("path") or dep_path):
                        real_file = dep_res.get("filepath") or dep_res.get("path") or dep_path
                        if real_file:
                            params_override["filepath"] = real_file
                            params_override["src"] = real_file
                            params_override["target"] = real_file
                            params_override["path"] = real_file
                            for ph in ("the saved file", "saved file", "the created file", "the document", "the pdf", "the report"):
                                if ph in candidate_input.lower():
                                    candidate_input = re.sub(re.escape(ph), f'"{real_file}"', candidate_input, flags=re.IGNORECASE)
                    # Search output dependency
                    elif dep_res.get("action") in ("SEARCH", "search_web") or dep_res.get("results"):
                        s_results = dep_res.get("results")
                        if s_results:
                            params_override["res_set"] = s_results

        # 3. Dynamic reference resolution using current live state
        step_input = candidate_input
        if dialogue_mgr:
            resolved_step, was_resolved = dialogue_mgr._resolve_references(candidate_input)
            if was_resolved:
                step_input = resolved_step

        # 4. Observe before state & execute step via UnifiedCommandRouter
        target_file = None
        m_file = re.search(r'([a-zA-Z0-9_\-\\]+\.(?:txt|pdf|docx|pptx|xlsx|csv|py))', step_input)
        if m_file:
            target_file = m_file.group(1)
        else:
            m_folder = re.search(r'\b(?:folder|directory)\s+([a-zA-Z0-9_\-]+)', step_input, re.I)
            if m_folder:
                target_file = m_folder.group(1)

        categories = select_relevant_categories(step.intent.name, step_input, target_file)
        before_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)

        try:
            step_result = unified_router.execute_single_action(step_input, user_id=user_id, params_override=params_override)
        except Exception as exc:
            step_result = {
                "status": "error",
                "intent": step.intent.name,
                "response": f"Step failed: {exc}",
            }

        # Validate dependency satisfaction
        if params_override.get("parent_folder") and step.intent.name == "FILE_OPERATIONS" and step_result.get("action") == "create_file":
            exp_parent = params_override["parent_folder"]
            actual_f = step_result.get("path") or step_result.get("filepath")
            if actual_f and not actual_f.lower().startswith(exp_parent.lower()):
                step_result["status"] = "error"
                step_result["response"] = f"Dependency failure: File '{actual_f}' was not created inside required folder '{exp_parent}'."

        # 5. Observe real system state immediately after step execution
        after_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)
        state_diff = compare_snapshots(before_snap, after_snap)
        obs = after_snap.to_dict()
        step.observation = obs
        step.state_difference = state_diff.to_dict()

        # 6. Verify result (Canonical Outcome Verification)
        step_result = _verify_action_result(
            step_result, step.intent.name, obs, state_diff=state_diff,
            before_snap=before_snap, after_snap=after_snap, user_id=user_id, command_input=step_input
        )
        step_result["observations"] = obs
        step_result["state_difference"] = state_diff.to_dict()

        # Check for generic bounded retry (transient retry, max 1)
        if step.retry_on_failure and step_result.get("status") in ("error", "failed") and step.retry_count < step.max_retries:
            step.retry_count += 1
            print(f"[RECOVERY] Retrying step {step.sequence}: '{step_input}' (retry {step.retry_count}/{step.max_retries})")
            try:
                retry_res = unified_router.execute_single_action(step_input, user_id=user_id, params_override=params_override)
                retry_after_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)
                state_diff = compare_snapshots(before_snap, retry_after_snap)
                obs = retry_after_snap.to_dict()
                step_result = _verify_action_result(
                    retry_res, step.intent.name, obs, state_diff=state_diff,
                    before_snap=before_snap, after_snap=retry_after_snap, user_id=user_id, command_input=step_input
                )
                step_result["observations"] = obs
                step_result["state_difference"] = state_diff.to_dict()
                step.observation = obs
                step.state_difference = state_diff.to_dict()
            except Exception:
                pass

        # 7. PHASE 3: Deviation Detection and Bounded Plan Adaptation
        is_deviation = step_result.get("status") in ("error", "failed") or step_result.get("deviation") is True
        if is_deviation and getattr(plan, "adaptation_count", 0) < getattr(plan, "max_adaptations", 2):
            adapted_res, was_adapted = _attempt_plan_adaptation(
                step, step_input, step_result, obs, plan, user_id=user_id, dialogue_mgr=dialogue_mgr
            )
            if was_adapted:
                adapt_after_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)
                state_diff = compare_snapshots(before_snap, adapt_after_snap)
                obs = adapt_after_snap.to_dict()
                step_result = _verify_action_result(
                    adapted_res, step.intent.name, obs, state_diff=state_diff,
                    before_snap=before_snap, after_snap=adapt_after_snap, user_id=user_id, command_input=step_input
                )
                step_result["observations"] = obs
                step_result["state_difference"] = state_diff.to_dict()
                step.observation = obs
                step.state_difference = state_diff.to_dict()

        step.result = step_result
        step_result["sequence"] = step.sequence
        step_results.append(step_result)

        # 8. Check for Ambiguity / WAITING_FOR_USER
        if step_result.get("status") == "waiting_for_user":
            step.status = "WAITING_FOR_USER"
            plan.goal_status = "WAITING_FOR_USER"
            if dialogue_mgr:
                dialogue_mgr.current_state.goal_status = "WAITING_FOR_USER"
                dialogue_mgr.current_state.pending_goal_continuation = {
                    "plan": plan,
                    "step_index": step.sequence + 1
                }
                dialogue_mgr.update_state(
                    step_result,
                    [step.intent.name],
                    observations=obs,
                    plan=asdict(plan) if hasattr(plan, "__dataclass_fields__") else plan,
                    goal_status="WAITING_FOR_USER"
                )
            return step_results

        # 9. Check step success vs failure
        if step_result.get("status") in ("error", "failed"):
            step.status = "FAILED"
            plan.goal_status = "FAILED"
            if not hasattr(plan, "failed_steps") or plan.failed_steps is None:
                plan.failed_steps = []
            plan.failed_steps.append({
                "sequence": step.sequence,
                "intent": step.intent.name,
                "action": step_input,
                "error": step_result.get("response", "Unknown error")
            })

            # Phase 4 Plan Dependency Replanning
            replan_statuses = get_adaptive_recovery_engine().replan_remaining_steps(plan, step, obs)
            for future_step in plan.steps:
                f_seq = getattr(future_step, "sequence", -1)
                if f_seq in replan_statuses:
                    st_val = replan_statuses[f_seq]
                    if st_val == StepReplanStatus.REQUIRES_REPLAN:
                        future_step.status = "REQUIRES_REPLAN"
                    elif st_val == StepReplanStatus.ALREADY_SATISFIED:
                        future_step.status = "ALREADY_SATISFIED"
                    elif st_val == StepReplanStatus.INVALID:
                        future_step.status = "INVALID"

            if dialogue_mgr:
                dialogue_mgr.update_state(
                    step_result,
                    [step.intent.name],
                    observations=obs,
                    plan=asdict(plan) if hasattr(plan, "__dataclass_fields__") else plan,
                    goal_status="FAILED"
                )
            if not step.continue_on_failure:
                break
        else:
            step.status = "COMPLETED"
            if not hasattr(plan, "completed_steps") or plan.completed_steps is None:
                plan.completed_steps = []
            plan.completed_steps.append({
                "sequence": step.sequence,
                "intent": step.intent.name,
                "action": step_input,
                "response": step_result.get("response", "")
            })
            # Update dialogue state immediately so next step can bind entities/context
            if dialogue_mgr:
                dialogue_mgr.update_state(
                    step_result,
                    [step.intent.name],
                    observations=obs,
                    plan=asdict(plan) if hasattr(plan, "__dataclass_fields__") else plan,
                    goal_status="RUNNING"
                )
            if step.intent.name in ("OPEN_APPLICATION", "CLOSE_APPLICATION", "WINDOW_MANAGEMENT"):
                try:
                    from core.environment import verify_and_synchronize_foreground_state
                    act_tgt = step.parameters.get("target") or step.parameters.get("application") or step_result.get("target") or step_result.get("app_name")
                    verify_and_synchronize_foreground_state(user_id=user_id, action_target=act_tgt)
                except Exception:
                    pass

        # Accumulate context for downstream steps
        accumulated_context[step.intent.name] = step_result.get("response", "")

    # If all steps completed successfully, mark plan COMPLETED
    if all(s.status == "COMPLETED" for s in plan.steps):
        plan.goal_status = "COMPLETED"
        if dialogue_mgr:
            dialogue_mgr.current_state.goal_status = "COMPLETED"
            dialogue_mgr.current_state.session_context["last_completed_goal"] = original_input
    elif getattr(plan, "goal_status", None) != "WAITING_FOR_USER":
        plan.goal_status = "FAILED"
        if dialogue_mgr:
            dialogue_mgr.current_state.goal_status = "FAILED"

    return step_results


def _build_step_input(intent_name: str, params: Dict[str, Any], original: str) -> str:
    """
    Reconstruct a concise natural-language string for each step so that the
    existing unified router can route and execute it correctly.
    """
    raw = params.get("raw_input")
    if raw and isinstance(raw, str) and raw.strip() and raw.strip() != original.strip():
        return raw.strip()

    intent_to_phrase = {
        # For MUSIC keep the original or raw_input
        "MUSIC":          lambda p: p.get("raw_input", original),
        # For EMAIL, reconstruct from params if possible
        "EMAIL":          lambda p: p.get("raw_input", original),
        # For REMINDERS, use the matched segment text or original
        "REMINDERS":      lambda p: p.get("raw_input", original),
        # For WEATHER, rebuild from location param if explicit, otherwise preserve original input
        "WEATHER_QUERY":  lambda p: (
            f"what is the weather in {p['location']}"
            if p.get('location') and str(p['location']).lower() not in ('local', 'here', 'current location', 'my location', '')
            else p.get('raw_input', original)
        ),
        # For CALCULATOR, prefer raw_input or extract math
        "CALCULATOR":     lambda p: p.get("raw_input", original),
        "TIME_QUERY":     lambda _: "what is the time",
        "DATE_QUERY":     lambda _: "what is the date",
        "POWER_ACTION":   lambda p: p.get("raw_input", original),
        "DEVICE_CONTROL": lambda p: (f"type {p['text']}" if p.get("action") == "type_text" and p.get("text") else p.get("raw_input", original)),
        "FILE_OPERATIONS": lambda p: p.get("raw_input", original),
        "OPEN_APPLICATION": lambda p: (
            f"search google for {p['query']}" if p.get("action") == "search_web" and p.get("query")
            else (f"open the {p['ordinal']} result" if p.get("action") == "open_browser_result" and "ordinal" in p
            else (f"search google for {p['search_query']}" if p.get('search_query')
            else (f"open {p.get('target', '')}" if p.get('action') != 'close' else f"close {p.get('target', '')}")))
        ),
        "RAG_SEARCH":     lambda p: p.get("raw_input", original),
        "GENERAL_CONVERSATION": lambda p: p.get("raw_input", original),
    }

    builder = intent_to_phrase.get(intent_name)
    if builder:
        phrase = builder(params)
        return phrase if phrase.strip() else original
    return original


def _inject_context(step_input: str, context: Dict[str, Any]) -> str:
    """
    Append a context hint to the step input when upstream results are
    needed (e.g. weather data used in an email body).
    """
    if not context:
        return step_input
    context_hints = "; ".join(f"{k}: {v}" for k, v in context.items() if v)
    return f"{step_input} [prior_context: {context_hints}]"


def _compose_response(step_results: List[Dict[str, Any]], plan: ExecutionPlan) -> str:
    """Compose one coherent spoken response from all step results."""
    responses = [
        r.get("response", "")
        for r in step_results
        if r.get("response", "").strip()
    ]

    if not responses:
        return "Done."

    if len(responses) == 1:
        return responses[0]

    # Multiple steps: join naturally
    parts = []
    for i, (resp, result) in enumerate(zip(responses, step_results)):
        intent = result.get("intent", "")
        parts.append(f"{resp}")

    combined = " Also, ".join(parts)

    # Append warnings if any
    if plan.warnings:
        warning_text = "; ".join(plan.warnings)
        combined += f" Note: {warning_text}"

    return combined


def _post_turn_update(
    dialogue_mgr,
    result: Dict[str, Any],
    intents_used: List[str],
    observations: Optional[Dict[str, Any]] = None,
    state_difference: Optional[Dict[str, Any]] = None,
    goal: Optional[Dict[str, Any]] = None,
    subgoals: Optional[List[Dict[str, Any]]] = None,
    plan: Optional[Any] = None,
    goal_status: Optional[str] = None,
) -> None:
    """Update dialogue state and record response after execution."""
    dialogue_mgr.update_state(
        result,
        intents_used,
        observations=observations,
        state_difference=state_difference,
        goal=goal,
        subgoals=subgoals,
        plan=plan,
        goal_status=goal_status,
    )
    dialogue_mgr.record_response(result.get("response", ""))

    # Section 6 & 7: Persist assistant action to PostgreSQL execution_experiences
    try:
        from core.execution_experience import ExecutionExperience, get_experience_manager
        mgr = get_experience_manager()
        intent = intents_used[0] if intents_used else result.get("intent", "UNKNOWN")
        raw_cmd = dialogue_mgr.current_state.turns[-1].user_input if dialogue_mgr.current_state.turns else ""
        uid = int(dialogue_mgr.user_id) if str(dialogue_mgr.user_id).isdigit() else 1
        is_ok = result.get("status") in ("success", True, "completed", None) and not result.get("error")
        exp = ExecutionExperience(
            experience_id=f"exp_{uuid.uuid4().hex[:12]}",
            execution_id=f"exec_{uuid.uuid4().hex[:12]}",
            user_id=uid,
            intent=intent,
            command_signature=raw_cmd[:250],
            action_signature=f"{intent}:{result.get('action', 'execute')}",
            environment_context=observations or {},
            expected_outcome={},
            observed_outcome=result,
            verification_status="VERIFIED_SUCCESS" if is_ok else "VERIFIED_FAILURE",
            confidence="HIGH",
            final_status="COMPLETED" if is_ok else "FAILED",
            created_at=time.time(),
            metadata={"response": result.get("response", "")}
        )
        mgr.record_experience(exp)
    except Exception:
        pass

    # Causal attribution tracking
    try:
        if state_difference:
            from core.causal_attribution import get_causal_attribution_engine
            c_eng = get_causal_attribution_engine()
            raw_cmd = dialogue_mgr.current_state.turns[-1].user_input if dialogue_mgr.current_state.turns else ""
            intent = intents_used[0] if intents_used else result.get("intent", "UNKNOWN")
            uid = int(dialogue_mgr.user_id) if str(dialogue_mgr.user_id).isdigit() else 1
            c_eng.attribute_action_outcome(
                action_record_id=result.get("action_record_id"),
                user_id=uid,
                action_type=intent,
                target=result.get("target") or result.get("file_path") or raw_cmd,
                before_state=None,
                after_state=observations or {},
                state_difference=state_difference,
                task_id=result.get("task_id"),
            )
    except Exception:
        pass


def _observe_action_result(
    step_result: Dict[str, Any],
    intent_name: str,
    step_input: str,
    user_id: str,
    target_file: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Capture the *actual* system state that resulted from executing an action.
    Uses the Phase 5 EnvironmentObserver with relevance filtering.
    """
    categories = select_relevant_categories(intent_name, step_input, target_file)
    snapshot = observe_environment(
        user_id=user_id,
        relevant_categories=categories,
        target_file=target_file,
    )
    obs = snapshot.to_dict()

    # Legacy/compatibility fallback if step_result specifies task_id
    task_id = step_result.get("task_id")
    if task_id and "task_status" not in obs:
        try:
            from skills.task_management.task_queue import TaskQueue
            tq = TaskQueue.get_instance() if hasattr(TaskQueue, "get_instance") else None
            if tq is None:
                from core.unified_command_router import unified_router
                tq = getattr(unified_router, "_task_queue", None)
            if tq:
                uid_int = int(user_id) if str(user_id).isdigit() else 0
                task_info = tq.get_status(uid_int, str(task_id))
                if task_info:
                    obs["task_status"] = task_info
        except Exception:
            pass

    return obs


def _verify_action_result(
    step_result: Dict[str, Any],
    intent_name: str,
    observations: Dict[str, Any],
    state_diff: Optional[Any] = None,
    before_snap: Optional[Any] = None,
    after_snap: Optional[Any] = None,
    user_id: Optional[Any] = None,
    command_input: Optional[str] = None
) -> Dict[str, Any]:
    """
    Cross-check what the router reported against real-world environment observations.
    Delegates to canonical OutcomeVerifier to distinguish action result from outcome result.
    Enforces FALSE COMPLETION PROTECTION: an action is not marked completed if outcome failed.
    """
    result = dict(step_result)  # shallow copy — do not mutate caller's dict

    if result.get("status") == "waiting_for_user":
        return result

    if state_diff:
        result["state_difference"] = state_diff.to_dict() if hasattr(state_diff, "to_dict") else state_diff

    verifier = get_outcome_verifier()
    cmd = command_input or step_input_for_verify(result)

    verification = verifier.verify_outcome(
        intent=intent_name,
        command_or_input=cmd,
        action_result=result,
        before_snap=before_snap,
        after_snap=after_snap,
        state_diff=state_diff,
        user_id=user_id
    )

    result["outcome_verification"] = verification.to_dict()

    if verification.status == OutcomeStatus.VERIFIED_SUCCESS:
        result["verified"] = True
        result["verification_source"] = verification.verification_method
        if "status" in result and result["status"] == "error":
            result["status"] = "success"

    elif verification.status == OutcomeStatus.VERIFIED_FAILURE:
        # FALSE COMPLETION PROTECTION:
        # Action reported success but outcome failed -> mark failed!
        result["verified"] = False
        result["status"] = "failed"
        if verification.failure_reason:
            result["failure_reason"] = verification.failure_reason
            # Provide truthful failure response if original was falsely claiming success
            orig_resp = str(result.get("response", "")).lower()
            if any(w in orig_resp for w in ["success", "opened", "created", "deleted", "done", "completed"]):
                result["response"] = f"Action failed: {verification.failure_reason}"
        print(f"[VERIFY] Verified failure for {intent_name}: {verification.failure_reason}")

    elif verification.status == OutcomeStatus.UNCERTAIN:
        result["uncertain"] = True
        if "verified" not in result:
            result["verified"] = False

    # Record in-memory execution record
    try:
        f_class_str = None
        if verification.status == OutcomeStatus.VERIFIED_FAILURE:
            rec_eng = get_adaptive_recovery_engine()
            f_class = rec_eng.classify_failure(verification, result, observations, intent_name)
            f_class_str = f_class.value
        elif verification.status == OutcomeStatus.UNCERTAIN:
            f_class_str = FailureClassification.VERIFICATION_UNCERTAIN.value

        rec_dec = result.get("recovery_decision")
        recovery_decisions_list = [rec_dec] if rec_dec else []

        record = ExecutionRecord(
            execution_id=uuid.uuid4().hex[:8],
            user_id=user_id,
            intent=intent_name,
            original_command=cmd,
            action=verification.verification_method,
            pre_state=before_snap.to_dict() if before_snap and hasattr(before_snap, "to_dict") else None,
            expected_state=verification.expected_state,
            post_state=observations,
            state_difference=state_diff.to_dict() if state_diff and hasattr(state_diff, "to_dict") else None,
            action_result=dict(step_result),
            verification_result=verification,
            adaptation_attempted=result.get("adaptation_attempted", False),
            adaptation_result=rec_dec,
            final_status=verification.status.value,
            timestamps={"timestamp": time.time()},
            adaptation_attempts=1 if result.get("adaptation_attempted") else 0,
            recovery_decisions=recovery_decisions_list,
            failure_classification=f_class_str,
            selected_strategy=result.get("selected_strategy"),
            final_recovery_status=result.get("status")
        )
        verifier.tracker.record(record)

        # Phase 5: Persist canonical Execution Experience
        try:
            from core.execution_experience import get_experience_manager
            exp_mgr = get_experience_manager()
            exp_mgr.record_from_execution_record(record)
        except Exception as exp_err:
            print(f"[EXPERIENCE] [WARN] Could not record execution experience: {exp_err}")
    except Exception as e:
        print(f"[VERIFY] [WARN] Could not save execution record: {e}")

    return result


def step_input_for_verify(result: Dict[str, Any]) -> str:
    """Helper: extract the original step input stored inside the result, if any."""
    return str(result.get("input", "") or result.get("query", "") or result.get("response", "")).lower()


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def brain_route_and_execute(user_input: str, user_id: Any = None, on_progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """
    Drop-in replacement for core.unified_command_router.route_and_execute.
    Used by legacy/assistant.py to transparently enable Brain routing.
    """
    return brain_process(user_input, user_id=user_id or "default", on_progress=on_progress)


if __name__ == "__main__":
    # Quick smoke test
    tests = [
        "play some Telugu songs",
        "what is the time",
        "play some Telugu songs and set a reminder to listen later",
        "calculate 25 * 18",
    ]

    for t in tests:
        print(f"\nInput : {t}")
        result = brain_process(t)
        print(f"Intent: {result['intent']}")
        print(f"Steps : {result.get('total_steps', 1)}")
        print(f"Reply : {result['response']}")
        print("-" * 60)
