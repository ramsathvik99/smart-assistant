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
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import asdict
from datetime import datetime
import uuid
import re

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


# Module-level singletons (canonical instances)
_multi_intent_analyzer = multi_intent_analyzer
_goal_planner = goal_planner


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def brain_process(user_input: str, user_id: str = "default") -> Dict[str, Any]:
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
    turn_data = dialogue_mgr.process_turn(user_input)
    enriched_input = turn_data.get("enriched_input", user_input)

    reference_resolved = turn_data.get("reference_resolved", False)
    routing_input = turn_data.get("resolved_input", user_input) if reference_resolved else user_input
    clean_low = user_input.strip().lower()

    # ------------------------------------------------------------------
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
    # Step 1.5 — USER INTERRUPTION / CANCELLATION (Requirement 9)
    # ------------------------------------------------------------------
    if routing_input == "cancel current goal" or clean_low in ("stop", "cancel that", "cancel", "abort", "no, don't do that", "don't do that", "stop it", "stop."):
        active_g = dialogue_mgr.current_state.current_goal
        gid = str((active_g.get("id") if active_g else None) or (active_g.get("goal_id") if active_g else None) or uuid.uuid4())[:8]
        dialogue_mgr.current_state.pending_goal_continuation = None
        try:
            from core.proactive_observer import ProactiveObservationCoordinator
            ProactiveObservationCoordinator.get_instance().drain_queued_events(str(user_id))
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
            "status": "success",
            "intent": "GOAL_MANAGEMENT",
            "goal_status": "CANCELLED",
            "response": cancel_msg,
            "goal_outcome": outcome.to_dict()
        }

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

            result = _verify_action_result(result, intent_name, obs, state_diff=state_diff)
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

        categories = select_relevant_categories(analysis.primary_intent.name, routing_input, target_file)
        before_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)

        result = _single_route(routing_input, user_id=user_id)
        intent_name = result.get("intent", analysis.primary_intent.name)

        # Step 5 — OBSERVE RESULT (capture actual system state)
        after_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)
        state_diff = compare_snapshots(before_snap, after_snap)
        observations = after_snap.to_dict()

        # Step 6 — VERIFY RESULT
        result = _verify_action_result(result, intent_name, observations, state_diff=state_diff)
        result["observations"] = observations
        result["state_difference"] = state_diff.to_dict()

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
        is_cancellation = (
            routing_input.lower().startswith("cancel")
            or routing_input.lower().startswith("stop")
            or "cancelled" in str(result.get("response", "")).lower()
            or result.get("action") == "cancel"
        )
        if is_cancellation:
            final_outcome = "CANCELLED"
            failure_reason = None
            blocking_reason = None
            success = False
        elif result.get("status") == "blocked" or result.get("blocked"):
            final_outcome = "BLOCKED"
            blocking_reason = result.get("reason") or result.get("error") or "Required state prevented completion."
            failure_reason = None
            success = False
        elif (
            result.get("status") in ("error", "failed")
            or result.get("success") is False
            or (result.get("verified") is False and "verified" in result)
        ):
            final_outcome = "FAILED"
            failure_reason = result.get("error") or result.get("message") or "Action failed to execute or verify."
            blocking_reason = None
            success = False
        else:
            final_outcome = "COMPLETED"
            failure_reason = None
            blocking_reason = None
            success = True

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
            goal=goal_info,
            subgoals=subgoals,
            goal_status=final_outcome
        )

        verified = result.get("verified", False) or bool(state_diff and state_diff.has_changes)
        verification_src = result.get("verification_source", "environment_observation" if verified else None)

        outcome = GoalOutcome(
            goal_id=goal_info.get("id", str(uuid.uuid4())[:8]),
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

    for step in plan.steps:
        subgoals.append({
            "step": step.intent.name,
            "sequence": step.sequence,
            "status": "pending"
        })

    # Step 9 — STEP-BY-STEP EXECUTION LOOP (EXECUTE → OBSERVE → VERIFY → NEXT STEP)
    step_results = _execute_plan_stateful(plan, user_input, user_id=user_id, dialogue_mgr=dialogue_mgr)

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
        "steps": step_results,
        "plan_id": plan.plan_id,
        "total_steps": plan.total_steps,
        "goal_status": plan.goal_status,
        "warnings": plan.warnings,
        "observations": observations,
        "state_difference": last_diff
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
    Uses only safe, existing capabilities. Never invents state or capabilities.
    """
    if getattr(plan, "adaptation_count", 0) >= getattr(plan, "max_adaptations", 2):
        print(f"[ADAPTATION] Reached maximum allowed adaptations ({getattr(plan, 'max_adaptations', 2)}). Halting adaptation.")
        return step_result, False

    intent_name = step.intent.name if hasattr(step.intent, "name") else str(step.intent)
    adapted_result = None
    adaptation_reason = ""
    adapted_action = ""

    # 1. Application / Browser launch adaptation
    if intent_name == "OPEN_APPLICATION":
        target = (step.parameters.get("app_name") or step.parameters.get("target") or step_input).lower()
        if "chrome" in target or "browser" in target or "youtube" in target:
            # Primary target failed to launch — check if alternative supported browser is available
            alternative_browsers = ["msedge", "edge", "firefox"]
            for alt in alternative_browsers:
                try:
                    alt_input = f"open {alt}"
                    test_res = unified_router.execute_single_action(alt_input, user_id=user_id)
                    if test_res.get("status") != "error":
                        adapted_action = alt_input
                        adaptation_reason = f"Primary application '{target}' failed to launch; adapted to available alternative '{alt}'."
                        adapted_result = test_res
                        adapted_result["response"] = f"Primary browser was unavailable, so I used {alt} to continue."
                        break
                except Exception:
                    continue

    # 2. File Operations adaptation (Broader search on Desktop without hallucinating)
    elif intent_name == "FILE_OPERATIONS":
        try:
            from modules.system_controller import get_desktop_path
            desktop = Path(get_desktop_path())
            candidates = list(desktop.glob("*.pptx")) + list(desktop.glob("*.pdf")) + list(desktop.glob("*.docx"))
            if len(candidates) == 1:
                cand_path = str(candidates[0])
                adapted_action = f"open file {cand_path}"
                adaptation_reason = f"Exact file not found; adapted to available matching file '{candidates[0].name}'."
                test_res = unified_router.execute_single_action(adapted_action, user_id=user_id)
                if test_res.get("status") != "error":
                    adapted_result = test_res
            elif len(candidates) > 1:
                cand_names = [f"'{c.name}'" for c in candidates[:3]]
                adapted_result = {
                    "status": "waiting_for_user",
                    "intent": "FILE_OPERATIONS",
                    "response": f"I found multiple files: {', '.join(cand_names)}. Which one should I open?",
                    "files": [{"name": c.name, "path": str(c)} for c in candidates]
                }
                adapted_action = "request clarification"
                adaptation_reason = "Multiple matching files found; paused for user clarification."
        except Exception:
            pass

    # 3. Task Management adaptation
    elif intent_name == "TASK_MANAGEMENT":
        if obs.get("task_status"):
            task_st = obs["task_status"].get("status", "").lower()
            if task_st in ("completed", "finished", "done", "failed"):
                adapted_result = {
                    "status": "success",
                    "intent": "TASK_MANAGEMENT",
                    "response": f"The task is currently {task_st}."
                }
                adapted_action = "report actual task state"
                adaptation_reason = f"Task is already {task_st}; adapted response to reflect actual completion status."

    if adapted_result is not None:
        plan.adaptation_count = getattr(plan, "adaptation_count", 0) + 1
        plan.adaptation_reason = adaptation_reason
        if not hasattr(plan, "adaptation_history") or plan.adaptation_history is None:
            plan.adaptation_history = []
        plan.adaptation_history.append({
            "step_index": step.sequence,
            "original_action": step_input,
            "adapted_action": adapted_action,
            "reason": adaptation_reason
        })
        print(f"[ADAPTATION #{plan.adaptation_count}] {adaptation_reason}")
        return adapted_result, True

    return step_result, False


def _execute_plan_stateful(
    plan: ExecutionPlan,
    original_input: str,
    user_id: str = "default",
    dialogue_mgr: Optional[Any] = None,
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
        # 1. Check for user interruption before step starts
        if dialogue_mgr and dialogue_mgr.current_state.goal_status == "CANCELLED":
            step.status = "CANCELLED"
            plan.goal_status = "CANCELLED"
            break

        step.status = "RUNNING"
        plan.active_step_index = step.sequence

        # 2. Build candidate step input
        segment_text = step.parameters.get("raw_input", "").strip()
        if segment_text and segment_text != original_input:
            candidate_input = segment_text
        else:
            candidate_input = _build_step_input(step.intent.name, step.parameters, original_input)

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

        categories = select_relevant_categories(step.intent.name, step_input, target_file)
        before_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)

        try:
            step_result = unified_router.execute_single_action(step_input, user_id=user_id)
        except Exception as exc:
            step_result = {
                "status": "error",
                "intent": step.intent.name,
                "response": f"Step failed: {exc}",
            }

        # 5. Observe real system state immediately after step execution
        after_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)
        state_diff = compare_snapshots(before_snap, after_snap)
        obs = after_snap.to_dict()
        step.observation = obs
        step.state_difference = state_diff.to_dict()

        # 6. Verify result
        step_result = _verify_action_result(step_result, step.intent.name, obs, state_diff=state_diff)
        step_result["observations"] = obs
        step_result["state_difference"] = state_diff.to_dict()

        # Check for generic bounded retry (transient retry, max 1)
        if step.retry_on_failure and step_result.get("status") == "error" and step.retry_count < step.max_retries:
            step.retry_count += 1
            print(f"[RECOVERY] Retrying step {step.sequence}: '{step_input}' (retry {step.retry_count}/{step.max_retries})")
            try:
                retry_res = unified_router.execute_single_action(step_input, user_id=user_id)
                retry_after_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_file)
                state_diff = compare_snapshots(before_snap, retry_after_snap)
                obs = retry_after_snap.to_dict()
                step_result = _verify_action_result(retry_res, step.intent.name, obs, state_diff=state_diff)
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
                step_result = _verify_action_result(adapted_res, step.intent.name, obs, state_diff=state_diff)
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

        # Accumulate context for downstream steps
        accumulated_context[step.intent.name] = step_result.get("response", "")

    # If all steps completed successfully, mark plan COMPLETED
    if all(s.status == "COMPLETED" for s in plan.steps):
        plan.goal_status = "COMPLETED"
        if dialogue_mgr:
            dialogue_mgr.current_state.goal_status = "COMPLETED"

    return step_results


def _build_step_input(intent_name: str, params: Dict[str, Any], original: str) -> str:
    """
    Reconstruct a concise natural-language string for each step so that the
    existing unified router can route and execute it correctly.
    """
    intent_to_phrase = {
        # For MUSIC keep the original so the music controller gets the full query
        "MUSIC":          lambda p: original,
        # For EMAIL, reconstruct from params if possible
        "EMAIL":          lambda p: original,
        # For REMINDERS, use the matched segment text or original
        "REMINDERS":      lambda p: params.get("raw_input", original),
        # For WEATHER, rebuild from location param if explicit, otherwise preserve original input
        "WEATHER_QUERY":  lambda p: (
            f"what is the weather in {p['location']}"
            if p.get('location') and str(p['location']).lower() not in ('local', 'here', 'current location', 'my location', '')
            else p.get('raw_input', original)
        ),
        # Keep original for math
        "CALCULATOR":     lambda p: original,
        "TIME_QUERY":     lambda _: "what is the time",
        "DATE_QUERY":     lambda _: "what is the date",
        "POWER_ACTION":   lambda p: p.get("raw_input", original),
        "DEVICE_CONTROL": lambda p: p.get("raw_input", original),
        "FILE_OPERATIONS": lambda p: p.get("raw_input", original),
        "OPEN_APPLICATION": lambda p: f"open {p.get('target', '')}" if p.get('action') != 'close' else f"close {p.get('target', '')}",
        "RAG_SEARCH":     lambda _: original,
        "GENERAL_CONVERSATION": lambda _: original,
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
) -> Dict[str, Any]:
    """
    Cross-check what the router *reported* against what was *observed* and detected changes.
    """
    result = dict(step_result)  # shallow copy — do not mutate caller's dict

    if state_diff:
        result["state_difference"] = state_diff.to_dict() if hasattr(state_diff, "to_dict") else state_diff

    # ── Caps Lock verification ──────────────────────────────────────────────
    if intent_name == "DEVICE_CONTROL" and "caps" in step_input_for_verify(result):
        reported_state = result.get("caps_lock") or result.get("state")
        observed_state = observations.get("caps_lock")
        if observed_state is not None and reported_state is not None:
            if bool(observed_state) != bool(reported_state):
                actual = "ON" if observed_state else "OFF"
                result["response"] = f"Caps Lock is actually {actual}."
                result["caps_lock"] = observed_state
                print(f"[VERIFY] Caps Lock mismatch — reported={reported_state}, observed={observed_state}")

    # ── Application opened verification ────────────────────────────────────
    if intent_name == "OPEN_APPLICATION":
        expected_app = (result.get("app_name") or result.get("target") or "").lower()
        observed_app = (observations.get("active_application") or "").lower()
        if result.get("verified_open") is False:
            result["verified"] = False
            result["status"] = "failed"
            result["response"] = f"Failed to open {expected_app}."
        elif result.get("verified_open") is True or (expected_app and observed_app and (expected_app in observed_app or observed_app in expected_app)):
            result["verified"] = True
            result["verification_source"] = "environment_observation"
        elif expected_app and observed_app and expected_app not in observed_app and observed_app not in expected_app:
            print(f"[VERIFY] App open mismatch — expected='{expected_app}', observed='{observed_app}'")

    return result


def step_input_for_verify(result: Dict[str, Any]) -> str:
    """Helper: extract the original step input stored inside the result, if any."""
    return str(result.get("input", "") or result.get("query", "") or result.get("response", "")).lower()


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def brain_route_and_execute(user_input: str, user_id: Any = None) -> Dict[str, Any]:
    """
    Drop-in replacement for core.unified_command_router.route_and_execute.
    Used by legacy/assistant.py to transparently enable Brain routing.
    """
    return brain_process(user_input, user_id=user_id or "default")


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
