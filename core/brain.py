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
from pathlib import Path
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.unified_command_router import unified_router, route_and_execute as _single_route
from core.multi_intent_analyzer import MultiIntentAnalyzer, analyze_input
from core.goal_planner import GoalPlanner, plan_execution, explain_plan, ExecutionPlan
from extensions.dialogue_state_manager import get_dialogue_manager

# Module-level singletons
_multi_intent_analyzer = MultiIntentAnalyzer()
_goal_planner = GoalPlanner()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def brain_process(user_input: str, user_id: str = "default") -> Dict[str, Any]:
    """
    Main Brain entry point.

    Replaces bare route_and_execute() for all assistant interactions.
    Handles single-intent and multi-intent commands transparently.

    Returns the same dict shape as unified_router.execute_single_action:
        {
            "status":   "success" | "error" | "partial",
            "intent":   <primary intent name>,
            "response": <final spoken response>,
            "steps":    [<step result>, ...],   # multi-intent only
            "plan_id":  <uuid8>,                # multi-intent only
        }
    """
    if not user_input or not user_input.strip():
        return {"status": "error", "intent": "NONE", "response": ""}

    # ------------------------------------------------------------------
    # Step 1 — Dialogue State Manager: enrich input with context
    # ------------------------------------------------------------------
    dialogue_mgr = get_dialogue_manager(user_id)
    turn_data = dialogue_mgr.process_turn(user_input)
    enriched_input = turn_data.get("enriched_input", user_input)

    # resolved_input has pronouns replaced with real entity names
    # (e.g. "close it" → "close WhatsApp"). Use it for routing when
    # a reference was actually resolved; otherwise fall back to original
    # to avoid injecting [context: ...] tag noise into the router.
    reference_resolved = turn_data.get("reference_resolved", False)
    routing_input = turn_data.get("resolved_input", user_input) if reference_resolved else user_input

    # ------------------------------------------------------------------
    # Step 2 — Multi-Intent Analyzer
    # ------------------------------------------------------------------
    analysis = _multi_intent_analyzer.analyze(enriched_input)

    # ------------------------------------------------------------------
    # Step 3 — Single-intent fast path (PHASE 5 backward-compat)
    # ------------------------------------------------------------------
    if not analysis.has_multiple_intents:
        result = _single_route(routing_input)   # resolved or original input (no tag noise)
        _post_turn_update(dialogue_mgr, result, [result.get("intent", "")])
        return result

    # ------------------------------------------------------------------
    # Step 4 — Goal Planner: build execution plan
    # ------------------------------------------------------------------
    plan = _goal_planner.create_plan(analysis)

    # ------------------------------------------------------------------
    # Step 5 — Execute each step in order
    # ------------------------------------------------------------------
    step_results = _execute_plan(plan, user_input)

    # ------------------------------------------------------------------
    # Step 6 — Compose aggregated response
    # ------------------------------------------------------------------
    intents_used = [s.get("intent", "") for s in step_results]
    final_response = _compose_response(step_results, plan)

    result = {
        "status": "success" if all(s.get("status") == "success" for s in step_results) else "partial",
        "intent": analysis.primary_intent.name,
        "response": final_response,
        "steps": step_results,
        "plan_id": plan.plan_id,
        "total_steps": plan.total_steps,
        "warnings": plan.warnings,
    }

    # ------------------------------------------------------------------
    # Step 7 — Update dialogue state
    # ------------------------------------------------------------------
    _post_turn_update(dialogue_mgr, result, intents_used)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _execute_plan(plan: ExecutionPlan, original_input: str) -> List[Dict[str, Any]]:
    """Execute each step in the plan, passing context between steps."""
    step_results: List[Dict[str, Any]] = []
    accumulated_context: Dict[str, Any] = {}

    for step in plan.steps:
        # Prefer the matched segment text stored in parameters (set by multi-intent analyzer)
        segment_text = step.parameters.get("raw_input", "").strip()

        # Build step-specific input: use segment if available, otherwise reconstruct
        if segment_text and segment_text != original_input:
            step_input = segment_text
        else:
            step_input = _build_step_input(step.intent.name, step.parameters, original_input)

        # Inject context from previous steps when dependencies exist
        if accumulated_context and step.dependencies:
            step_input = _inject_context(step_input, accumulated_context)

        # Execute via the existing unified router
        try:
            step_result = unified_router.execute_single_action(step_input)
        except Exception as exc:
            step_result = {
                "status": "error",
                "intent": step.intent.name,
                "response": f"Step failed: {exc}",
            }

        step_result["sequence"] = step.sequence
        step_results.append(step_result)

        # Accumulate context for downstream steps
        accumulated_context[step.intent.name] = step_result.get("response", "")

        # Stop on fatal error unless step is marked continue_on_failure
        if step_result.get("status") == "error" and not step.continue_on_failure:
            break

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
        # For WEATHER, rebuild from location param
        "WEATHER_QUERY":  lambda p: f"what is the weather in {p.get('location', 'local')}",
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
) -> None:
    """Update dialogue state and record response after execution."""
    dialogue_mgr.update_state(result, intents_used)
    dialogue_mgr.record_response(result.get("response", ""))


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def brain_route_and_execute(user_input: str, user_id: str = "default") -> Dict[str, Any]:
    """
    Drop-in replacement for core.unified_command_router.route_and_execute.
    Used by legacy/assistant.py to transparently enable Brain routing.
    """
    return brain_process(user_input, user_id)


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
