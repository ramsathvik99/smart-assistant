"""
Smart Assistant — Canonical Adaptive Replanning & Recovery Engine (PHASE 4)

Provides bounded, deterministic, and explainable recovery strategies when actions
produce VERIFIED_FAILURE or meaningful state deviations.

Closed Loop:
OBSERVE -> UNDERSTAND -> PLAN -> ACT -> OBSERVE -> COMPARE -> VERIFY
-> IF SUCCESS: CONTINUE
-> IF FAILURE: DIAGNOSE -> ADAPT -> REPLAN -> ACT -> VERIFY AGAIN
"""

from __future__ import annotations

import os
import re
import time
import uuid
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple, Callable

from core.outcome_verifier import (
    OutcomeStatus,
    ConfidenceLevel,
    ExpectedOutcome,
    OutcomeVerificationResult,
    ExecutionRecord,
    get_outcome_verifier,
)
from core.environment_observer import StateDifference


# ============================================================================
# Failure Classification Enumeration
# ============================================================================

class FailureClassification(str, Enum):
    """Categorization of verified failures to drive deterministic recovery."""
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"              # Propagation delay, temporary lock (retryable)
    STATE_MISMATCH = "STATE_MISMATCH"                    # Action executed, but ended in unexpected state
    RESOURCE_MISSING = "RESOURCE_MISSING"                # App, file, or resource not found
    PERMISSION_FAILURE = "PERMISSION_FAILURE"            # Access denied / privilege issue
    INVALID_TARGET = "INVALID_TARGET"                    # Target name/path/identifier invalid
    DEVICE_UNAVAILABLE = "DEVICE_UNAVAILABLE"            # Smart home or audio endpoint unreachable/offline
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"    # Required prerequisite artifact or state missing
    DUPLICATE_RISK = "DUPLICATE_RISK"                    # Action has side-effects that could cause duplicates
    POLICY_BLOCKED = "POLICY_BLOCKED"                    # Strategy or action blocked by canonical policy engine
    VERIFICATION_UNCERTAIN = "VERIFICATION_UNCERTAIN"    # Insufficient evidence to verify or adapt aggressively
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"                  # Insufficient evidence to classify deterministically


class StepReplanStatus(str, Enum):
    """State-aware status for remaining steps in a multi-step execution plan."""
    VALID = "VALID"                              # Step remains valid and executable
    INVALID = "INVALID"                          # Step cannot execute due to unrecoverable environment state
    REQUIRES_REPLAN = "REQUIRES_REPLAN"          # Step depended on failed step and must be adapted/replanned
    ALREADY_SATISFIED = "ALREADY_SATISFIED"      # Expected outcome of step is already present in environment


# ============================================================================
# Strategy & Decision Models
# ============================================================================

@dataclass
class AdaptiveStrategy:
    """Bounded, deterministic alternative strategy to achieve a goal."""
    strategy_id: str
    intent: str
    description: str
    preconditions: Dict[str, Any] = field(default_factory=dict)
    action_parameters: Dict[str, Any] = field(default_factory=dict)
    recovery_command: Optional[str] = None
    expected_outcome: Optional[ExpectedOutcome] = None
    risk_level: str = "low"                      # "low", "medium", "high"
    priority: int = 50                           # Higher = preferred
    is_retry: bool = False                       # True = same-action retry; False = alternative strategy

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "intent": self.intent,
            "description": self.description,
            "preconditions": self.preconditions,
            "action_parameters": self.action_parameters,
            "recovery_command": self.recovery_command,
            "expected_outcome": asdict(self.expected_outcome) if self.expected_outcome else None,
            "risk_level": self.risk_level,
            "priority": self.priority,
            "is_retry": self.is_retry,
        }


@dataclass
class RecoveryDecision:
    """Decision made by the recovery engine after diagnosing a verified failure."""
    decision_id: str
    execution_id: str
    original_intent: str
    failure_classification: FailureClassification
    failure_reason: str
    state_difference: Optional[Dict[str, Any]] = None
    strategy: Optional[AdaptiveStrategy] = None
    rationale: str = ""
    confidence: float = 1.0
    requires_confirmation: bool = False
    terminal: bool = False                       # True if no further recovery should be attempted
    policy_decision: Optional[str] = None
    policy_rules: Optional[List[str]] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "execution_id": self.execution_id,
            "original_intent": self.original_intent,
            "failure_classification": self.failure_classification.value,
            "failure_reason": self.failure_reason,
            "state_difference": self.state_difference,
            "strategy": self.strategy.to_dict() if self.strategy else None,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "requires_confirmation": self.requires_confirmation,
            "terminal": self.terminal,
            "policy_decision": self.policy_decision,
            "policy_rules": self.policy_rules,
            "created_at": self.created_at,
        }


# ============================================================================
# Recovery Budget & Configuration
# ============================================================================

@dataclass
class RecoveryBudget:
    """Strict bounds on retry and adaptive recovery attempts to prevent infinite loops."""
    max_propagation_retries: int = 2
    max_adaptive_strategies: int = 2
    max_total_recovery_attempts: int = 3

    propagation_retries_used: int = 0
    adaptive_strategies_used: int = 0
    total_attempts_used: int = 0

    def can_retry_propagation(self) -> bool:
        return (
            self.propagation_retries_used < self.max_propagation_retries
            and self.total_attempts_used < self.max_total_recovery_attempts
        )

    def can_adapt_strategy(self) -> bool:
        return (
            self.adaptive_strategies_used < self.max_adaptive_strategies
            and self.total_attempts_used < self.max_total_recovery_attempts
        )

    def record_retry(self):
        self.propagation_retries_used += 1
        self.total_attempts_used += 1

    def record_adaptation(self):
        self.adaptive_strategies_used += 1
        self.total_attempts_used += 1

    def is_exhausted(self) -> bool:
        return self.total_attempts_used >= self.max_total_recovery_attempts


# ============================================================================
# Failure Classifier
# ============================================================================

class FailureClassifier:
    """Classifies verification results and environment state into actionable failure types."""

    @staticmethod
    def classify(
        verification_result: OutcomeVerificationResult,
        action_result: Optional[Dict[str, Any]] = None,
        obs: Optional[Dict[str, Any]] = None,
        intent: str = ""
    ) -> FailureClassification:
        if verification_result.status == OutcomeStatus.UNCERTAIN:
            return FailureClassification.VERIFICATION_UNCERTAIN

        reason = (verification_result.failure_reason or "").lower()
        err_msg = ""
        if action_result:
            err_msg = str(action_result.get("error") or action_result.get("response") or "").lower()
        full_text = f"{reason} {err_msg}"

        # 1. Permission / Access
        if any(w in full_text for w in ["permission denied", "access denied", "administrator", "elevated", "read-only"]):
            return FailureClassification.PERMISSION_FAILURE

        # 2. Device / Hardware endpoint unavailable
        if any(w in full_text for w in ["offline", "unreachable", "endpoint", "cannot connect", "device unavailable"]):
            return FailureClassification.DEVICE_UNAVAILABLE

        # 3. Missing target / resource
        if any(w in full_text for w in ["does not exist", "not found", "no such file", "not installed", "missing"]):
            return FailureClassification.RESOURCE_MISSING

        # 4. Duplicate risk (side-effects like reminder/email/task/doc where repeating may double-execute)
        intent_up = (intent or "").upper()
        if intent_up in ("REMINDERS", "EMAIL", "DOCUMENT_GENERATION", "TASK_MANAGEMENT"):
            if "already exists" in full_text or "duplicate" in full_text:
                return FailureClassification.DUPLICATE_RISK

        # 5. Invalid target / syntax
        if any(w in full_text for w in ["invalid target", "unsupported", "invalid argument", "syntax error"]):
            return FailureClassification.INVALID_TARGET

        # 6. State Mismatch (app ran but didn't come to foreground, volume wrong level, key toggle off)
        if any(w in full_text for w in ["not active", "tolerance", "mismatch", "expected", "window"]):
            return FailureClassification.STATE_MISMATCH

        # 7. Transient delay / propagation
        if verification_result.retry_possible or any(w in full_text for w in ["timeout", "delay", "waiting", "propagation"]):
            return FailureClassification.TRANSIENT_FAILURE

        return FailureClassification.UNKNOWN_FAILURE


# ============================================================================
# Canonical Adaptive Recovery Engine
# ============================================================================

class AdaptiveRecoveryEngine:
    """
    Decides bounded recovery strategies based on verified failure, environment state,
    and remaining goals.
    """

    def __init__(self, default_budget: Optional[RecoveryBudget] = None, strategy_optimizer: Optional[Any] = None):
        self.default_budget = default_budget or RecoveryBudget()
        self.strategy_optimizer = strategy_optimizer

    def classify_failure(
        self,
        verification_result: OutcomeVerificationResult,
        action_result: Optional[Dict[str, Any]] = None,
        obs: Optional[Dict[str, Any]] = None,
        intent: str = ""
    ) -> FailureClassification:
        return FailureClassifier.classify(verification_result, action_result, obs, intent)

    def decide_recovery(
        self,
        intent: str,
        command_or_input: str,
        verification_result: OutcomeVerificationResult,
        action_result: Dict[str, Any],
        obs: Dict[str, Any],
        state_diff: Optional[StateDifference] = None,
        user_id: Optional[Any] = None,
        budget: Optional[RecoveryBudget] = None,
        previous_decisions: Optional[List[RecoveryDecision]] = None,
        cancellation_check: Optional[Callable[[], bool]] = None,
        experience_summary: Optional[Any] = None,
        experiences: Optional[List[Any]] = None
    ) -> RecoveryDecision:
        """
        Main decision entry point.
        Analyzes evidence, checks safety, evaluates budget, and selects a deterministic strategy.
        """
        rec_budget = budget or self.default_budget
        prev_decisions = previous_decisions or []
        exec_id = uuid.uuid4().hex[:8]
        intent_up = (intent or "").upper().strip()

        # Query historical experience context and relevant experiences if not provided
        if experience_summary is None and user_id is not None:
            try:
                from core.execution_experience import get_experience_manager, generate_command_signature
                cmd_sig = generate_command_signature(intent_up, command_or_input)
                uid_int = int(user_id) if str(user_id).isdigit() else 1
                exp_mgr = get_experience_manager()
                experience_summary = exp_mgr.get_experience_summary(uid_int, intent_up, cmd_sig)
                if experiences is None:
                    experiences = exp_mgr.get_relevant_experiences(
                        user_id=uid_int, intent=intent_up, command_signature=cmd_sig, limit=50
                    )
            except Exception:
                if experiences is None:
                    experiences = []

        # Check for cancellation before deciding
        if cancellation_check and cancellation_check():
            return RecoveryDecision(
                decision_id=uuid.uuid4().hex[:8],
                execution_id=exec_id,
                original_intent=intent_up,
                failure_classification=FailureClassification.UNKNOWN_FAILURE,
                failure_reason="Execution cancelled by user or signal.",
                rationale="Recovery aborted due to cancellation.",
                terminal=True,
                confidence=1.0
            )

        # 1. Classify failure
        f_class = self.classify_failure(verification_result, action_result, obs, intent_up)
        f_reason = verification_result.failure_reason or "Unknown verification failure."

        # 2. Check Budget Exhaustion
        if rec_budget.is_exhausted():
            return RecoveryDecision(
                decision_id=uuid.uuid4().hex[:8],
                execution_id=exec_id,
                original_intent=intent_up,
                failure_classification=f_class,
                failure_reason=f"Recovery budget exhausted ({rec_budget.total_attempts_used}/{rec_budget.max_total_recovery_attempts} attempts).",
                rationale=f"Cannot attempt further recovery: maximum recovery budget reached.",
                terminal=True,
                confidence=1.0
            )

        # 3. Handle UNCERTAIN outcome: Do NOT trigger aggressive recovery loops
        if f_class == FailureClassification.VERIFICATION_UNCERTAIN:
            return RecoveryDecision(
                decision_id=uuid.uuid4().hex[:8],
                execution_id=exec_id,
                original_intent=intent_up,
                failure_classification=f_class,
                failure_reason=f_reason,
                rationale="Outcome verification was uncertain. Uncontrolled adaptation prevented; reporting uncertainty to user.",
                terminal=True,
                confidence=0.5
            )

        # 4. Check for Side-Effect Idempotency / Duplicate Risk Protection
        if self._is_unsafe_duplicate_risk(intent_up, command_or_input, action_result, obs, user_id):
            return RecoveryDecision(
                decision_id=uuid.uuid4().hex[:8],
                execution_id=exec_id,
                original_intent=intent_up,
                failure_classification=FailureClassification.DUPLICATE_RISK,
                failure_reason="Action has side effects that cannot be safely retried without duplicate risk.",
                rationale="Prevented automatic retry of potentially duplicate side effect (e.g. reminder/email/document/task). Requires user confirmation or termination.",
                requires_confirmation=True,
                terminal=True,
                confidence=1.0
            )

        # 5. Check if goal is already satisfied in the environment (Situational Awareness)
        satisfied, sat_reason = self._is_already_satisfied(intent_up, command_or_input, obs, user_id)
        if satisfied:
            strat = AdaptiveStrategy(
                strategy_id="VERIFY_EXISTING_STATE",
                intent=intent_up,
                description="Goal is already satisfied in environment; verify and report state.",
                recovery_command=None,
                risk_level="low",
                priority=100
            )
            return RecoveryDecision(
                decision_id=uuid.uuid4().hex[:8],
                execution_id=exec_id,
                original_intent=intent_up,
                failure_classification=f_class,
                failure_reason=f_reason,
                strategy=strat,
                rationale=f"Environment inspection indicates the goal is already satisfied: {sat_reason}.",
                confidence=0.95,
                terminal=False
            )

        # 6. Check Transient Failure -> Propagation Retry
        if f_class == FailureClassification.TRANSIENT_FAILURE and rec_budget.can_retry_propagation():
            rec_budget.record_retry()
            strat = AdaptiveStrategy(
                strategy_id=f"RETRY_PROPAGATION_{intent_up}",
                intent=intent_up,
                description=f"Wait for system state propagation and re-verify {intent_up}.",
                recovery_command=command_or_input,
                risk_level="low",
                priority=90,
                is_retry=True
            )
            return RecoveryDecision(
                decision_id=uuid.uuid4().hex[:8],
                execution_id=exec_id,
                original_intent=intent_up,
                failure_classification=f_class,
                failure_reason=f_reason,
                strategy=strat,
                rationale="Transient delay or propagation failure diagnosed. Executing bounded propagation retry.",
                confidence=0.9,
                terminal=False
            )

        # 7. Select Bounded Domain-Specific Alternative Strategy
        if not rec_budget.can_adapt_strategy():
            return RecoveryDecision(
                decision_id=uuid.uuid4().hex[:8],
                execution_id=exec_id,
                original_intent=intent_up,
                failure_classification=f_class,
                failure_reason="Adaptive strategy budget exhausted.",
                rationale=f"Reached maximum adaptive strategy modifications ({rec_budget.adaptive_strategies_used}/{rec_budget.max_adaptive_strategies}).",
                terminal=True,
                confidence=1.0
            )

        strat, rationale = self._select_domain_strategy(
            intent_up, command_or_input, f_class, f_reason, obs, action_result, user_id, prev_decisions, experience_summary, experiences, cancellation_check
        )

        if strat:
            rec_budget.record_adaptation()

            # ── PHASE 7: Policy filter for recovery strategy ────────────────────
            # POLICY BLOCK ≠ EXECUTION FAILURE: do not re-try or adapt if policy says no.
            # The optimizer ranks strategies; policy decides whether they may execute.
            # This implements requirements 11, 12, 13 from Phase 7B specification.
            try:
                from core.risk_policy_engine import get_risk_policy_engine, PolicyDecision
                _policy_engine = get_risk_policy_engine()
                uid_val = int(user_id) if str(user_id).isdigit() else None
                _strat_eval = _policy_engine.evaluate(
                    intent=strat.intent or intent_up,
                    command=strat.recovery_command or strat.strategy_id or command_or_input,
                    user_id=uid_val,
                    is_recovery_action=True,
                )
                if _strat_eval.decision == PolicyDecision.BLOCKED:
                    # BLOCKED is not an execution failure — do not recover from it
                    return RecoveryDecision(
                        decision_id=uuid.uuid4().hex[:8],
                        execution_id=exec_id,
                        original_intent=intent_up,
                        failure_classification=FailureClassification.POLICY_BLOCKED,
                        failure_reason=f"Recovery strategy '{strat.strategy_id}' blocked by policy: {_strat_eval.rationale}",
                        rationale=f"POLICY BLOCK (not an execution failure): {_strat_eval.rationale}. Rules: {_strat_eval.policy_rules_applied}",
                        terminal=True,
                        requires_confirmation=False,
                        confidence=1.0,
                        policy_decision=_strat_eval.decision.value,
                        policy_rules=_strat_eval.policy_rules_applied,
                    )
                elif _strat_eval.decision == PolicyDecision.UNCERTAIN:
                    # UNCERTAIN is also not an execution failure — hold safely
                    return RecoveryDecision(
                        decision_id=uuid.uuid4().hex[:8],
                        execution_id=exec_id,
                        original_intent=intent_up,
                        failure_classification=FailureClassification.POLICY_BLOCKED,
                        failure_reason=f"Recovery strategy '{strat.strategy_id}' held by policy (UNCERTAIN): {_strat_eval.rationale}",
                        rationale=f"POLICY UNCERTAIN — holding strategy safely. Do not adapt further.",
                        terminal=True,
                        requires_confirmation=True,
                        confidence=0.5,
                        policy_decision=_strat_eval.decision.value,
                        policy_rules=_strat_eval.policy_rules_applied,
                    )
                elif _strat_eval.decision == PolicyDecision.ALLOWED_WITH_CONFIRMATION:
                    # Strategy requires confirmation — return terminal so brain can pause plan
                    return RecoveryDecision(
                        decision_id=uuid.uuid4().hex[:8],
                        execution_id=exec_id,
                        original_intent=intent_up,
                        failure_classification=f_class,
                        failure_reason=f_reason,
                        strategy=strat,
                        rationale=f"Recovery strategy '{strat.strategy_id}' requires user confirmation before execution.",
                        requires_confirmation=True,
                        terminal=True,
                        confidence=0.8,
                        policy_decision=_strat_eval.decision.value,
                        policy_rules=_strat_eval.policy_rules_applied,
                    )
                # ALLOWED — fall through to normal RecoveryDecision below
            except ImportError:
                pass  # policy engine not yet available; proceed without (safe for LOW-risk)
            except Exception as _pol_err:
                import logging as _log
                _log.getLogger(__name__).warning("[RECOVERY POLICY] filter failed: %s", _pol_err)
            # ── End Phase 7 policy filter ───────────────────────────────────────

            return RecoveryDecision(
                decision_id=uuid.uuid4().hex[:8],
                execution_id=exec_id,
                original_intent=intent_up,
                failure_classification=f_class,
                failure_reason=f_reason,
                strategy=strat,
                rationale=rationale,
                confidence=0.85,
                terminal=False
            )



        # No strategy available -> Terminate truthfully
        return RecoveryDecision(
            decision_id=uuid.uuid4().hex[:8],
            execution_id=exec_id,
            original_intent=intent_up,
            failure_classification=f_class,
            failure_reason=f_reason,
            rationale=rationale or "No safe bounded recovery strategy available for this failure. Terminating truthfully.",
            terminal=True,
            confidence=1.0
        )

    # ------------------------------------------------------------------------
    # Domain Strategy Selection
    # ------------------------------------------------------------------------

    def _select_domain_strategy(
        self,
        intent: str,
        command: str,
        f_class: FailureClassification,
        f_reason: str,
        obs: Dict[str, Any],
        action_result: Dict[str, Any],
        user_id: Optional[Any],
        prev_decisions: List[RecoveryDecision],
        experience_summary: Optional[Any] = None,
        experiences: Optional[List[Any]] = None,
        cancellation_check: Optional[Callable[[], bool]] = None
    ) -> Tuple[Optional[AdaptiveStrategy], str]:
        cmd_low = command.lower().strip()

        # 1. OPEN_APPLICATION (Desktop Applications only - exclude browser results/links)
        is_browser_result_cmd = (
            action_result.get("action") in ("open_browser_result", "OPEN_BROWSER_RESULT", "open_link", "SEARCH", "search_web")
            or action_result.get("entity_type") in ("BROWSER_RESULT", "SEARCH_QUERY")
            or any(k in cmd_low for k in ["result", "link", "search "])
        )
        if (intent == "OPEN_APPLICATION" or cmd_low.startswith(("open ", "launch ", "start "))) and not is_browser_result_cmd:
            target = action_result.get("app_name") or action_result.get("target") or ""
            if not target:
                m = re.match(r"(?:open|launch|start)\s+([a-zA-Z0-9_\-\.]+)", cmd_low)
                if m:
                    target = m.group(1)
            target_norm = target.replace(".exe", "").lower()

            # Situation A: Application is already running as a process, but not active/focused
            # In obs or psutil
            running_processes = obs.get("running_processes") or []
            is_running = False
            if target_norm:
                is_running = any(target_norm in str(p).lower() for p in running_processes)
                if not is_running:
                    try:
                        import psutil
                        for p in psutil.process_iter(['name']):
                            if target_norm in (p.info.get('name') or "").lower():
                                is_running = True
                                break
                    except Exception:
                        pass

            candidate_strategies: List[AdaptiveStrategy] = []

            if is_running:
                # Check if we already tried focusing
                already_focused = any(
                    d.strategy and d.strategy.strategy_id == "FOCUS_EXISTING_APP"
                    for d in prev_decisions
                )
                if not already_focused:
                    candidate_strategies.append(
                        AdaptiveStrategy(
                            strategy_id="FOCUS_EXISTING_APP",
                            intent="OPEN_APPLICATION",
                            description=f"Focus already-running instance of {target}.",
                            recovery_command=f"focus {target}",
                            action_parameters={"app_name": target, "action": "focus"},
                            risk_level="low",
                            priority=95
                        )
                    )

            # Situation B: Browser alternative fallback ONLY for generic browser requests (e.g. "browser", "web browser")
            # Strict fidelity rule: If the user explicitly requested "Chrome" (or any named application),
            # NEVER silently substitute another application like Edge.
            is_generic_browser = target_norm in ("browser", "web browser", "the browser", "internet", "default browser")
            if not is_running and not is_browser_result_cmd and is_generic_browser:
                attempted_alts = {
                    (d.strategy.action_parameters.get("app_name") or "").replace("msedge", "edge").lower()
                    for d in prev_decisions if d.strategy and d.strategy.action_parameters
                }
                for alt in ["chrome", "edge", "firefox"]:
                    if alt not in attempted_alts and alt != target_norm:
                        candidate_strategies.append(
                            AdaptiveStrategy(
                                strategy_id=f"TRY_ALTERNATIVE_BROWSER_{alt.upper()}",
                                intent="OPEN_APPLICATION",
                                description=f"Launch alternative browser '{alt}'.",
                                recovery_command=f"open {alt}",
                                action_parameters={"app_name": alt},
                                risk_level="low",
                                priority=80
                            )
                        )
            elif not is_running and not is_browser_result_cmd and "chrome" in target_norm:
                # User explicitly requested Chrome: retry Chrome resolution only, never substitute Edge
                already_retried_chrome = any(
                    d.strategy and d.strategy.strategy_id == "RETRY_CHROME_RESOLUTION"
                    for d in prev_decisions
                )
                if not already_retried_chrome:
                    candidate_strategies.append(
                        AdaptiveStrategy(
                            strategy_id="RETRY_CHROME_RESOLUTION",
                            intent="OPEN_APPLICATION",
                            description="Retry launching Chrome via canonical system paths and installed application index.",
                            recovery_command="open chrome",
                            action_parameters={"app_name": "chrome", "retry_canonical": True},
                            risk_level="low",
                            priority=85
                        )
                    )

            if candidate_strategies:
                try:
                    from core.strategy_optimizer import get_strategy_optimizer
                    from core.execution_experience import generate_command_signature
                    optimizer = getattr(self, "strategy_optimizer", None) or get_strategy_optimizer()
                    cmd_sig = generate_command_signature("OPEN_APPLICATION", command)
                    uid_int = int(user_id) if user_id and str(user_id).isdigit() else None
                    selection = optimizer.optimize_strategies(
                        candidate_strategies=candidate_strategies,
                        experiences=experiences,
                        intent="OPEN_APPLICATION",
                        command_signature=cmd_sig,
                        current_env=obs,
                        user_id=uid_int,
                        cancellation_check=cancellation_check,
                        experience_summary=experience_summary
                    )
                    # Phase 7B: Filter ranked candidate strategies through canonical policy engine
                    try:
                        from core.risk_policy_engine import get_risk_policy_engine
                        pol_engine = get_risk_policy_engine()
                        ordered_candidates = []
                        if selection.selected_strategy:
                            ordered_candidates.append(selection.selected_strategy)
                        ordered_candidates.extend([s for s in selection.alternatives if s != selection.selected_strategy])

                        filtered = pol_engine.filter_strategies(
                            candidate_strategies=ordered_candidates,
                            intent="OPEN_APPLICATION",
                            user_id=uid_int,
                            current_env=obs,
                        )
                        if filtered.has_any_executable:
                            chosen_strat = filtered.best_allowed
                            strat_id = chosen_strat.strategy_id
                            if chosen_strat != selection.selected_strategy:
                                rationale = f"Primary strategy was filtered by policy; selected highest allowable alternative '{strat_id}'. ({selection.rationale})"
                            elif strat_id == "FOCUS_EXISTING_APP":
                                rationale = f"Target application '{target}' is already running in background. Adapting to focus/bring window to front instead of relaunching. ({selection.rationale})"
                            elif strat_id.startswith("TRY_ALTERNATIVE_BROWSER_"):
                                alt_name = (chosen_strat.action_parameters.get("app_name") or "").lower()
                                evidence_note = ""
                                if experience_summary and getattr(experience_summary, "strategies", None) and strat_id in experience_summary.strategies:
                                    st_stat = experience_summary.strategies[strat_id]
                                    evidence_note = f" (Historical evidence: {st_stat.success_count}/{st_stat.total_attempts} successful)"
                                rationale = f"Primary browser '{target}' failed to launch; switching to available alternative '{alt_name}'.{evidence_note} ({selection.rationale})"
                            else:
                                rationale = selection.rationale
                            return chosen_strat, rationale
                        elif filtered.needs_confirmation:
                            chosen_strat = filtered.needs_confirmation[0]
                            return chosen_strat, f"Recovery strategy '{chosen_strat.strategy_id}' requires explicit user confirmation before execution."
                        else:
                            return None, f"All candidate recovery strategies were blocked by policy."
                    except Exception as _filter_err:
                        import logging as _log
                        _log.getLogger(__name__).warning("Policy filter error: %s", _filter_err)

                    if selection.selected_strategy:
                        strat_id = selection.selected_strategy.strategy_id
                        if strat_id == "FOCUS_EXISTING_APP":
                            rationale = f"Target application '{target}' is already running in background. Adapting to focus/bring window to front instead of relaunching. ({selection.rationale})"
                        elif strat_id.startswith("TRY_ALTERNATIVE_BROWSER_"):
                            alt_name = (selection.selected_strategy.action_parameters.get("app_name") or "").lower()
                            evidence_note = ""
                            if experience_summary and getattr(experience_summary, "strategies", None) and strat_id in experience_summary.strategies:
                                st_stat = experience_summary.strategies[strat_id]
                                evidence_note = f" (Historical evidence: {st_stat.success_count}/{st_stat.total_attempts} successful)"
                            rationale = f"Primary browser '{target}' failed to launch; switching to available alternative '{alt_name}'.{evidence_note} ({selection.rationale})"
                        else:
                            rationale = selection.rationale
                        return selection.selected_strategy, rationale
                except Exception as _opt_err:
                    import logging as _log
                    _log.getLogger(__name__).warning(
                        "StrategyOptimizer error (non-fatal, falling back to heuristic): %s", _opt_err
                    )
                    # Fallback: return first candidate strategy from Phase 4 heuristic list
                    fallback = candidate_strategies[0]
                    return fallback, f"Phase 6 optimizer unavailable ({type(_opt_err).__name__}); using Phase 4 heuristic selection: {fallback.strategy_id}"

            return None, "All application launch alternatives exhausted."

        # 2. FILE_OPERATIONS
        elif intent == "FILE_OPERATIONS":
            # Search Desktop or target directory for matching file
            try:
                from modules.system_controller import get_desktop_path
                from pathlib import Path
                desktop = Path(get_desktop_path())
                candidates = list(desktop.glob("*.pptx")) + list(desktop.glob("*.pdf")) + list(desktop.glob("*.docx"))
                if len(candidates) == 1:
                    cand_path = str(candidates[0])
                    return (
                        AdaptiveStrategy(
                            strategy_id="USE_SINGLE_MATCHING_FILE",
                            intent="FILE_OPERATIONS",
                            description=f"Open single discovered match '{candidates[0].name}'.",
                            recovery_command=f"open file {cand_path}",
                            action_parameters={"path": cand_path},
                            risk_level="low",
                            priority=85
                        ),
                        f"Exact file not found; adapted to single matching desktop file '{candidates[0].name}'."
                    )
                elif len(candidates) > 1:
                    # Ambiguous -> Requires confirmation / clarification
                    cand_names = [c.name for c in candidates[:3]]
                    return (
                        AdaptiveStrategy(
                            strategy_id="CLARIFY_FILE_CHOICE",
                            intent="FILE_OPERATIONS",
                            description="Ask user to clarify which file to open.",
                            recovery_command=None,
                            action_parameters={"candidates": [str(c) for c in candidates[:3]]},
                            risk_level="low",
                            priority=85
                        ),
                        f"Multiple matching files found ({', '.join(cand_names)}). Clarification required."
                    )
            except Exception:
                pass
            return None, "File recovery options exhausted."

        # 3. TASK_MANAGEMENT
        elif intent == "TASK_MANAGEMENT":
            # Check if task is already in queue or completed
            task_status = obs.get("task_status", {})
            if task_status:
                st = task_status.get("status", "").lower()
                if st in ("completed", "finished", "running"):
                    return (
                        AdaptiveStrategy(
                            strategy_id="REPORT_ACTUAL_TASK_STATE",
                            intent="TASK_MANAGEMENT",
                            description=f"Report verified task state: {st}.",
                            recovery_command=None,
                            action_parameters={"status": st},
                            risk_level="low",
                            priority=90
                        ),
                        f"Task already exists in state '{st}'. Reporting actual state instead of duplicate submission."
                    )
            return None, "Task management recovery exhausted."

        # 4. DOCUMENT_GENERATION
        elif intent == "DOCUMENT_GENERATION":
            # If failed due to output path / corrupt, check if alternate directory exists
            target_file = action_result.get("file_path") or action_result.get("path")
            if target_file and not os.path.exists(target_file):
                # Check Desktop as safe alternate output directory
                try:
                    from modules.system_controller import get_desktop_path
                    desktop = get_desktop_path()
                    filename = os.path.basename(target_file)
                    alt_path = os.path.join(desktop, filename)
                    if not any(d.strategy and d.strategy.strategy_id == "GENERATE_TO_DESKTOP" for d in prev_decisions):
                        return (
                            AdaptiveStrategy(
                                strategy_id="GENERATE_TO_DESKTOP",
                                intent="DOCUMENT_GENERATION",
                                description=f"Generate document to safe desktop path {alt_path}.",
                                recovery_command=f"create document {filename}",
                                action_parameters={"output_path": alt_path},
                                risk_level="low",
                                priority=75
                            ),
                            f"Original path '{target_file}' inaccessible. Adapting output destination to desktop directory."
                        )
                except Exception:
                    pass
            return None, "Document generation recovery exhausted."

        # 5. AUDIO / VOLUME
        elif intent in ("AUDIO", "VOLUME", "SYSTEM_SETTINGS"):
            # If audio endpoint inaccessible, do not loop
            if "endpoint" in f_reason.lower() or "direct" in f_reason.lower():
                return None, "Audio endpoint is inaccessible; truthful uncertainty will be reported."

        # 6. SMART_HOME
        elif intent == "SMART_HOME":
            if "offline" in f_reason.lower() or "unreachable" in f_reason.lower():
                return None, "Smart home device is offline. Halting commands to prevent network flooding."

        return None, "No specific domain recovery strategy available."

    # ------------------------------------------------------------------------
    # Safety & Side-Effect Evaluation
    # ------------------------------------------------------------------------

    def _is_unsafe_duplicate_risk(
        self,
        intent: str,
        command: str,
        action_result: Dict[str, Any],
        obs: Dict[str, Any],
        user_id: Optional[Any]
    ) -> bool:
        """
        Detects whether retrying an action could cause an unwanted duplicate side effect.
        """
        cmd_low = command.lower()

        # Reminders: Check if reminder is already present in DB for this user
        if intent == "REMINDERS" or "remind" in cmd_low:
            uid = user_id or 1
            try:
                from core.assistant_core import assistant_core
                reminders = assistant_core.get_user_reminders(user_id=uid)
                if isinstance(reminders, list) and len(reminders) > 0:
                    # Check if matching reminder was already inserted despite verification failure
                    for r in reminders:
                        r_title = (r.get("title") or r.get("task") or "").lower()
                        if r_title and (r_title in cmd_low or any(w in r_title for w in cmd_low.split())):
                            return True  # Already exists! Repeating would duplicate.
            except Exception:
                pass

        # Email: Never automatically resend an email!
        # Only outbound actions (send, reply, forward, dispatch) have duplicate side-effect risk.
        # Read-only queries (check, read, inbox, unread, summarize, what emails) are safe and must report real errors.
        if intent == "EMAIL" or "send" in cmd_low:
            if any(w in cmd_low for w in ["send", "reply", "forward", "dispatch", "compose"]):
                return True

        # Document Generation: If document already exists on disk and has content, do not clobber
        if intent == "DOCUMENT_GENERATION":
            file_path = action_result.get("file_path") or action_result.get("path")
            if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                return True

        return False

    def _is_already_satisfied(
        self,
        intent: str,
        command: str,
        obs: Dict[str, Any],
        user_id: Optional[Any]
    ) -> Tuple[bool, str]:
        """
        Determines whether the intended outcome is already achieved in the environment.
        """
        cmd_low = command.lower()

        # OPEN_APPLICATION: Check if target is foreground window
        if intent == "OPEN_APPLICATION" or cmd_low.startswith(("open ", "launch ")):
            active_app = (obs.get("active_application") or "").lower()
            fg_title = (obs.get("foreground_window_title") or "").lower()
            m = re.match(r"(?:open|launch|start)\s+([a-zA-Z0-9_\-\.]+)", cmd_low)
            if m:
                target = m.group(1).replace(".exe", "").lower()
                if (target in active_app or target in fg_title) and target:
                    return True, f"Application '{target}' is already active and focused in foreground"

        # DEVICE_CONTROL: Toggle keys
        if intent == "DEVICE_CONTROL":
            if "caps" in cmd_low:
                req_val = False if "off" in cmd_low else True
                obs_val = obs.get("caps_lock")
                if obs_val is not None and bool(obs_val) == req_val:
                    return True, f"Caps lock is already {'ON' if req_val else 'OFF'}"

        return False, ""

    # ------------------------------------------------------------------------
    # Plan Dependency Replanning
    # ------------------------------------------------------------------------

    def replan_remaining_steps(
        self,
        plan: Any,
        failed_step: Any,
        obs: Dict[str, Any]
    ) -> Dict[int, StepReplanStatus]:
        """
        Evaluates remaining steps in an ExecutionPlan when a step fails.
        Identifies dependent steps that require replanning vs independent steps that remain valid.
        """
        statuses: Dict[int, StepReplanStatus] = {}
        failed_seq = getattr(failed_step, "sequence", -1)

        steps = getattr(plan, "steps", [])
        for step in steps:
            seq = getattr(step, "sequence", -1)
            # Skip past or current steps
            if seq <= failed_seq:
                continue

            # Check dependencies
            deps = getattr(step, "dependencies", []) or []
            if failed_seq in deps:
                statuses[seq] = StepReplanStatus.REQUIRES_REPLAN
                continue

            # Check semantic context dependency: does step consume output of failed step?
            input_ctx = getattr(step, "input_context", {}) or {}
            failed_intent = getattr(failed_step.intent, "name", str(failed_step.intent))
            if failed_intent in input_ctx:
                statuses[seq] = StepReplanStatus.REQUIRES_REPLAN
                continue

            # Check if step's expected outcome is already satisfied in obs
            step_intent = getattr(step.intent, "name", str(step.intent))
            step_input = getattr(step, "parameters", {}).get("raw_input", "")
            satisfied, _ = self._is_already_satisfied(step_intent, step_input, obs, None)
            if satisfied:
                statuses[seq] = StepReplanStatus.ALREADY_SATISFIED
                continue

            # Step is independent and preconditions remain intact
            statuses[seq] = StepReplanStatus.VALID

        return statuses


# ============================================================================
# Singleton & Accessor
# ============================================================================

_global_adaptive_engine = AdaptiveRecoveryEngine()

def get_adaptive_recovery_engine() -> AdaptiveRecoveryEngine:
    return _global_adaptive_engine
