"""
Strategy Optimizer Module (Phase 6 - Controlled Experience-Based Strategy Optimization)

This module enables historical execution evidence from Phase 5 (Execution Experience Memory)
to inform and improve the selection of existing Phase 4 recovery strategies in a controlled,
explainable, and strictly bounded manner.

Key Principles:
1. Existing Safe Strategies Only: The optimizer ONLY scores and ranks pre-existing,
   authorized strategies defined in Phase 4. It NEVER creates or generates new executable strategies.
2. Current State Precedence: Verified current environment observations ALWAYS take precedence
   over historical experience (CURRENT STATE > HISTORICAL EXPERIENCE).
3. Phase 4 Safety Authoritative: Recovery budgets, duplicate risk protections, confirmation
   requirements, and user isolation are strictly preserved and never bypassed.
4. Small-Sample Protection: Bayesian smoothing prevents small sample anomalies (e.g. 1/1 outranking 95/120).
5. Minimum Evidence Threshold: Strategies below the threshold (default: 3) have strictly dampened influence.
6. Non-Reinforcement Learning: Deterministic scoring and explainable rationale; no neural training or code modification.
"""

from __future__ import annotations
import math
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple, Set

from core.outcome_verifier import OutcomeStatus


# ============================================================================
# Canonical Models
# ============================================================================

@dataclass
class StrategyEvidence:
    """Historical execution evidence aggregated for a specific strategy."""
    strategy_id: str
    intent: str
    command_signature: str
    sample_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    uncertain_count: int = 0
    success_rate: float = 0.0
    average_duration_ms: float = 0.0
    average_attempts: float = 1.0
    last_used_at: float = 0.0
    confidence: float = 0.0
    environment_match: float = 1.0
    user_specific: bool = True
    recent_failures: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyScore:
    """Detailed scoring breakdown for a candidate strategy."""
    strategy_id: str
    base_priority: int
    evidence_score: float = 0.0
    environment_score: float = 0.0
    confidence_score: float = 0.0
    risk_penalty: float = 0.0
    uncertainty_penalty: float = 0.0
    recent_failure_penalty: float = 0.0
    exploration_bonus: float = 0.0
    learning_modifier: float = 0.0
    learning_confidence: str = "LOW"
    final_score: float = 0.0
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StrategySelection:
    """Outcome of strategy optimization containing chosen strategy and evidence audit."""
    selected_strategy: Optional[Any]  # AdaptiveStrategy
    alternatives: List[Any] = field(default_factory=list)  # List[AdaptiveStrategy]
    scores: Dict[str, StrategyScore] = field(default_factory=dict)
    learning_signals: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    evidence_used: bool = False
    requires_confirmation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_strategy": self.selected_strategy.to_dict() if hasattr(self.selected_strategy, "to_dict") else None,
            "alternatives": [s.to_dict() if hasattr(s, "to_dict") else str(s) for s in self.alternatives],
            "scores": {k: v.to_dict() for k, v in self.scores.items()},
            "learning_signals": {k: (v.to_dict() if hasattr(v, "to_dict") else str(v)) for k, v in self.learning_signals.items()},
            "rationale": self.rationale,
            "evidence_used": self.evidence_used,
            "requires_confirmation": self.requires_confirmation,
        }


# ============================================================================
# Canonical Strategy Optimizer
# ============================================================================

class StrategyOptimizer:
    """
    Ranks and selects among existing Phase 4 recovery strategies using
    historical execution evidence, conservative statistical smoothing,
    and current environment observation.
    """

    MIN_STRATEGY_EVIDENCE: int = 3       # Minimum sample volume before heavy historical influence
    STALENESS_HORIZON_DAYS: float = 60.0 # Age at which historical evidence weight decays to 50%
    ALPHA_PRIOR: float = 3.0             # Bayesian smoothing pseudo-counts
    PRIOR_SUCCESS_RATE: float = 0.5      # Neutral prior success rate

    def __init__(self, min_evidence_threshold: int = MIN_STRATEGY_EVIDENCE):
        self.min_evidence_threshold = min_evidence_threshold

    # ------------------------------------------------------------------------
    # Evidence Aggregation
    # ------------------------------------------------------------------------

    def aggregate_evidence(
        self,
        strategy_ids: List[str],
        experiences: List[Any],  # List[ExecutionExperience]
        target_intent: str,
        target_signature: str,
        current_env: Optional[Dict[str, Any]] = None,
        target_user_id: Optional[int] = None,
        experience_summary: Optional[Any] = None
    ) -> Dict[str, StrategyEvidence]:
        """
        Extracts structured evidence metrics for candidate strategies from
        historical execution experience episodes or an experience summary.
        """
        evidence_map: Dict[str, StrategyEvidence] = {}
        now = time.time()

        for sid in strategy_ids:
            evidence_map[sid] = StrategyEvidence(
                strategy_id=sid,
                intent=target_intent,
                command_signature=target_signature,
                user_specific=True
            )

        if experience_summary and getattr(experience_summary, "strategies", None):
            strat_dict = experience_summary.strategies
            for sid, ev in evidence_map.items():
                if sid in strat_dict:
                    st_stat = strat_dict[sid]
                    tot = getattr(st_stat, "total_attempts", getattr(st_stat, "sample_volume", 0))
                    succ = getattr(st_stat, "success_count", 0)
                    fail = getattr(st_stat, "failure_count", 0)
                    if tot > ev.sample_count:
                        ev.sample_count = tot
                        ev.success_count = succ
                        ev.failure_count = fail
                        ev.success_rate = getattr(st_stat, "success_rate", succ / tot if tot else 0.0)
                        ev.confidence = min(1.0, round(tot / (self.min_evidence_threshold * 3), 3))
                        if getattr(experience_summary, "most_successful_strategy", "") == sid:
                            ev.environment_match = 1.0

        if not experiences:
            return evidence_map

        # Process experiences in reverse-chronological order (most recent first)
        sorted_exps = sorted(experiences, key=lambda x: getattr(x, "created_at", 0), reverse=True)

        for sid, ev in evidence_map.items():
            durations: List[float] = []
            attempt_counts: List[int] = []
            recent_attempts: List[str] = []

            for exp in sorted_exps:
                # User isolation check
                if target_user_id is not None and getattr(exp, "user_id", None) != target_user_id:
                    continue

                exp_created = getattr(exp, "created_at", now)
                if exp_created > ev.last_used_at:
                    ev.last_used_at = exp_created

                # Match context similarity (Exact > Partial > General)
                ctx_similarity = self._calculate_context_similarity(
                    exp_intent=getattr(exp, "intent", ""),
                    exp_sig=getattr(exp, "command_signature", ""),
                    exp_env=getattr(exp, "environment_context", {}) or {},
                    target_intent=target_intent,
                    target_sig=target_signature,
                    current_env=current_env or {}
                )

                # Look for attempts using this strategy
                exp_attempts = getattr(exp, "attempts", []) or []
                found_in_attempts = False

                for att in exp_attempts:
                    att_sid = att.get("strategy_id") if isinstance(att, dict) else getattr(att, "strategy_id", None)
                    if att_sid == sid:
                        found_in_attempts = True
                        ev.sample_count += 1
                        st = att.get("verification_status") if isinstance(att, dict) else getattr(att, "verification_status", None)
                        dur = att.get("duration_ms", 0) if isinstance(att, dict) else getattr(att, "duration_ms", 0)
                        if dur:
                            durations.append(float(dur))

                        if st == OutcomeStatus.VERIFIED_SUCCESS.value or st == "VERIFIED_SUCCESS":
                            ev.success_count += 1
                            recent_attempts.append("SUCCESS")
                        elif st == OutcomeStatus.UNCERTAIN.value or st == "UNCERTAIN":
                            ev.uncertain_count += 1
                            recent_attempts.append("UNCERTAIN")
                        else:
                            ev.failure_count += 1
                            recent_attempts.append("FAILURE")

                # If not explicitly in attempts array, check terminal strategy_id
                if not found_in_attempts and getattr(exp, "strategy_id", None) == sid:
                    ev.sample_count += 1
                    dur = getattr(exp, "duration_ms", 0)
                    if dur:
                        durations.append(float(dur))
                    term_status = getattr(exp, "final_status", "") or getattr(exp, "verification_status", "")
                    if term_status == OutcomeStatus.VERIFIED_SUCCESS.value or term_status == "VERIFIED_SUCCESS":
                        ev.success_count += 1
                        recent_attempts.append("SUCCESS")
                    elif term_status == OutcomeStatus.UNCERTAIN.value or term_status == "UNCERTAIN":
                        ev.uncertain_count += 1
                        recent_attempts.append("UNCERTAIN")
                    else:
                        ev.failure_count += 1
                        recent_attempts.append("FAILURE")

                if found_in_attempts:
                    attempt_counts.append(len(exp_attempts))

            # Aggregate stats
            if ev.sample_count > 0:
                ev.success_rate = round(ev.success_count / ev.sample_count, 3)
                ev.average_duration_ms = round(sum(durations) / len(durations), 1) if durations else 0.0
                ev.average_attempts = round(sum(attempt_counts) / len(attempt_counts), 2) if attempt_counts else 1.0

                # Recent failures in last 3 attempts
                ev.recent_failures = sum(1 for res in recent_attempts[:3] if res == "FAILURE")

                # Confidence scales with sample count
                ev.confidence = min(1.0, round(ev.sample_count / (self.min_evidence_threshold * 3), 3))

        return evidence_map

    # ------------------------------------------------------------------------
    # Deterministic Scoring Engine
    # ------------------------------------------------------------------------

    def score_strategy(
        self,
        strategy: Any,  # AdaptiveStrategy
        evidence: StrategyEvidence,
        current_env: Dict[str, Any],
        is_already_satisfied: bool = False,
        learning_signal: Optional[Any] = None
    ) -> StrategyScore:
        """
        Computes a conservative, explainable score for a single candidate strategy.
        Formula:
          FinalScore = BasePriority
                     + EvidenceScore
                     + EnvironmentScore
                     + LearningModifier
                     - UncertaintyPenalty
                     - RecentFailurePenalty
                     - RiskPenalty
                     + ExplorationBonus
        """
        now = time.time()
        base_priority = getattr(strategy, "priority", 50)
        risk_level = getattr(strategy, "risk_level", "low").lower()
        strategy_id = getattr(strategy, "strategy_id", "UNKNOWN")
        current_env = current_env or {}

        # 1. Base Priority
        # Preserves canonical Phase 4 prioritization as the baseline anchor
        score_val = float(base_priority)

        # 2. Evidence Score (with Bayesian smoothing & Small Sample Protection)
        evidence_score = 0.0
        confidence_score = 0.0
        if evidence.sample_count > 0:
            # Bayesian smoothed success rate:
            # (succ + alpha * prior) / (sample_count + alpha)
            smoothed_rate = (
                evidence.success_count + self.ALPHA_PRIOR * self.PRIOR_SUCCESS_RATE
            ) / (evidence.sample_count + self.ALPHA_PRIOR)

            # Dampen evidence influence if sample count < min_evidence_threshold
            if evidence.sample_count < self.min_evidence_threshold:
                sample_dampening = (evidence.sample_count / self.min_evidence_threshold) * 0.4
            else:
                sample_dampening = 0.4 + 0.6 * min(1.0, evidence.sample_count / (self.min_evidence_threshold * 4))

            # Staleness decay: older evidence has reduced weight
            staleness_factor = 1.0
            if evidence.last_used_at > 0:
                age_days = max(0.0, (now - evidence.last_used_at) / 86400.0)
                # Exponential half-life decay over STALENESS_HORIZON_DAYS
                staleness_factor = math.exp(-0.693 * (age_days / self.STALENESS_HORIZON_DAYS))
                staleness_factor = max(0.15, staleness_factor)  # Floor at 15%

            # Evidence points: centered around neutral 0.5 (-25 to +25 range)
            raw_evidence_pts = (smoothed_rate - 0.5) * 50.0
            evidence_score = round(raw_evidence_pts * sample_dampening * staleness_factor * evidence.environment_match, 2)
            confidence_score = round(sample_dampening * staleness_factor, 2)

        # 3. Environment Score (CURRENT STATE ALWAYS WINS)
        environment_score = 0.0
        env_explanations = []

        # Check situational awareness: if app is already running
        target_app = (getattr(strategy, "action_parameters", {}) or {}).get("app_name", "").lower()
        running_procs = [str(p).lower() for p in (current_env.get("running_processes") or [])]
        is_running = any(target_app and target_app in p for p in running_procs)

        if is_running:
            if "focus" in strategy_id.lower() or strategy_id == "FOCUS_EXISTING_APP":
                environment_score += 35.0
                env_explanations.append("Target already running in environment -> prioritized focus/reuse strategy")
            elif "launch" in strategy_id.lower() or "open" in strategy_id.lower():
                environment_score -= 60.0
                env_explanations.append("Target already running in environment -> penalized duplicate launch attempt")

        if is_already_satisfied:
            if strategy_id == "VERIFY_EXISTING_STATE":
                environment_score += 50.0
                env_explanations.append("Goal already satisfied in environment")
            else:
                environment_score -= 40.0
                env_explanations.append("Action redundant: goal state already exists")

        # 4. Uncertainty Penalty
        uncertainty_penalty = 0.0
        if evidence.sample_count > 0 and evidence.uncertain_count > 0:
            unc_rate = evidence.uncertain_count / evidence.sample_count
            uncertainty_penalty = round(unc_rate * 20.0 * confidence_score, 2)

        # 5. Recent Failure Penalty (Detects recent strategy degradation/breakage)
        recent_failure_penalty = 0.0
        if evidence.recent_failures > 0:
            recent_failure_penalty = round(evidence.recent_failures * 10.0, 2)

        # 6. Risk Penalty (High risk requires extra caution)
        risk_penalty = 0.0
        if risk_level == "high":
            risk_penalty = 30.0
        elif risk_level == "medium":
            risk_penalty = 10.0

        # 7. Safe Exploration Bonus (Conservative Exploration vs Exploitation)
        exploration_bonus = 0.0
        if risk_level == "low" and evidence.sample_count < self.min_evidence_threshold and not is_already_satisfied:
            # Under-tested safe strategies receive a tiny exploration bonus to prevent arbitrary starvation
            exploration_bonus = round(4.0 * (1.0 - (evidence.sample_count / self.min_evidence_threshold)), 2)

        # 8. Continuous Learning Signal (Phase 9)
        learning_modifier = 0.0
        learning_confidence = "LOW"
        if learning_signal is not None:
            learning_modifier = getattr(learning_signal, "effective_score_modifier", 0.0)
            conf_obj = getattr(learning_signal, "confidence", None)
            learning_confidence = getattr(conf_obj, "value", str(conf_obj)) if conf_obj else "LOW"

        # Compute Final Score
        final_score = (
            score_val
            + evidence_score
            + environment_score
            + learning_modifier
            - uncertainty_penalty
            - recent_failure_penalty
            - risk_penalty
            + exploration_bonus
        )
        final_score = round(final_score, 2)

        # Generate Explainable Rationale
        parts = [f"Base priority: {base_priority}"]
        if evidence.sample_count > 0:
            parts.append(
                f"History ({evidence.success_count}/{evidence.sample_count} succ, "
                f"{evidence.uncertain_count} unc, weight={evidence_score:+.1f})"
            )
        else:
            parts.append("No prior history (default baseline)")

        if environment_score != 0.0:
            parts.append(f"Environment match ({environment_score:+.1f}): {'; '.join(env_explanations)}")
        if learning_modifier != 0.0:
            parts.append(f"Learned preference ({learning_confidence}, {learning_modifier:+.1f})")
        if recent_failure_penalty > 0:
            parts.append(f"Recent failure penalty (-{recent_failure_penalty})")
        if uncertainty_penalty > 0:
            parts.append(f"Uncertainty penalty (-{uncertainty_penalty})")
        if risk_penalty > 0:
            parts.append(f"Risk penalty (-{risk_penalty} for {risk_level} risk)")
        if exploration_bonus > 0:
            parts.append(f"Safe exploration bonus (+{exploration_bonus})")

        explanation = f"Score={final_score:.1f} [{'; '.join(parts)}]"

        return StrategyScore(
            strategy_id=strategy_id,
            base_priority=base_priority,
            evidence_score=evidence_score,
            environment_score=environment_score,
            confidence_score=confidence_score,
            risk_penalty=risk_penalty,
            uncertainty_penalty=uncertainty_penalty,
            recent_failure_penalty=recent_failure_penalty,
            exploration_bonus=exploration_bonus,
            learning_modifier=learning_modifier,
            learning_confidence=learning_confidence,
            final_score=final_score,
            explanation=explanation
        )

    # ------------------------------------------------------------------------
    # Optimization & Selection
    # ------------------------------------------------------------------------

    def optimize_strategies(
        self,
        candidate_strategies: List[Any],  # List[AdaptiveStrategy]
        experiences: Optional[List[Any]] = None,  # List[ExecutionExperience]
        intent: str = "",
        command_signature: str = "",
        current_env: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        is_already_satisfied: bool = False,
        cancellation_check: Optional[Any] = None,
        experience_summary: Optional[Any] = None,
        enable_learning: bool = True,
        strategy_version: str = "v1"
    ) -> StrategySelection:
        """
        Ranks candidate strategies using historical evidence and current environment state.
        Returns a StrategySelection containing the winning strategy, alternatives, and audit scores.
        """
        if cancellation_check and cancellation_check():
            return StrategySelection(
                selected_strategy=None,
                alternatives=[],
                scores={},
                learning_signals={},
                rationale="Optimization aborted due to cancellation.",
                evidence_used=False,
                requires_confirmation=False
            )

        if not candidate_strategies:
            return StrategySelection(
                selected_strategy=None,
                alternatives=[],
                scores={},
                learning_signals={},
                rationale="No candidate strategies provided for optimization.",
                evidence_used=False,
                requires_confirmation=False
            )

        # 1. Aggregate historical evidence
        strategy_ids = [getattr(s, "strategy_id", "") for s in candidate_strategies if getattr(s, "strategy_id", "")]
        evidence_map = self.aggregate_evidence(
            strategy_ids=strategy_ids,
            experiences=experiences or [],
            target_intent=intent,
            target_signature=command_signature,
            current_env=current_env or {},
            target_user_id=user_id,
            experience_summary=experience_summary
        )

        # Retrieve Continuous Learning Signals (Phase 9)
        learning_signals: Dict[str, Any] = {}
        if enable_learning and user_id is not None:
            try:
                from core.continuous_learning import get_learning_engine
                engine = get_learning_engine()
                for strat in candidate_strategies:
                    sid = getattr(strat, "strategy_id", "")
                    sver = getattr(strat, "version", strategy_version)
                    sig = engine.get_learning_signal(
                        strategy_id=sid,
                        user_id=user_id,
                        intent=intent,
                        context_signature=command_signature,
                        current_env=current_env,
                        target_version=sver
                    )
                    learning_signals[sid] = sig
            except Exception as _learn_err:
                pass

        # 2. Score all valid candidate strategies
        scores: Dict[str, StrategyScore] = {}
        has_usable_evidence = False

        for strat in candidate_strategies:
            sid = getattr(strat, "strategy_id", "")
            ev = evidence_map.get(sid) or StrategyEvidence(
                strategy_id=sid, intent=intent, command_signature=command_signature
            )
            if ev.sample_count > 0:
                has_usable_evidence = True

            sc = self.score_strategy(
                strategy=strat,
                evidence=ev,
                current_env=current_env,
                is_already_satisfied=is_already_satisfied,
                learning_signal=learning_signals.get(sid)
            )
            scores[sid] = sc

        # 3. Sort strategies descending by final_score
        ranked_strategies = sorted(
            candidate_strategies,
            key=lambda s: scores.get(getattr(s, "strategy_id", ""), StrategyScore(getattr(s, "strategy_id", ""), 0)).final_score,
            reverse=True
        )

        selected = ranked_strategies[0]
        alternatives = ranked_strategies[1:]
        winner_id = getattr(selected, "strategy_id", "")
        winner_score = scores.get(winner_id)

        # Explainable rationale
        winner_exp = winner_score.explanation if winner_score else "Default priority selection"
        rationale = f"Selected '{winner_id}' based on: {winner_exp}."

        requires_conf = getattr(selected, "risk_level", "low").lower() == "high"

        return StrategySelection(
            selected_strategy=selected,
            alternatives=alternatives,
            scores=scores,
            learning_signals=learning_signals,
            rationale=rationale,
            evidence_used=has_usable_evidence,
            requires_confirmation=requires_conf
        )

    # ------------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------------

    def _calculate_context_similarity(
        self,
        exp_intent: str,
        exp_sig: str,
        exp_env: Dict[str, Any],
        target_intent: str,
        target_sig: str,
        current_env: Dict[str, Any]
    ) -> float:
        """
        Determines contextual match level between historical experience and current context.
        Exact match (same intent + same signature + matching OS/platform): 1.0
        Partial match (same intent + signature prefix/family): 0.75
        General match (same intent only): 0.5
        """
        if exp_intent != target_intent:
            return 0.2

        score = 0.5  # Base match for same intent

        if exp_sig and target_sig:
            if exp_sig == target_sig:
                score += 0.35  # Exact command signature
            elif exp_sig.split(":")[0] == target_sig.split(":")[0]:
                score += 0.20  # Partial action signature

        # Check OS / environment compatibility
        exp_os = (exp_env.get("os") or "").lower()
        curr_os = (current_env.get("os") or "").lower()
        if exp_os and curr_os:
            if exp_os == curr_os:
                score += 0.15
            else:
                score -= 0.30  # Different OS significantly reduces relevance

        return min(1.0, max(0.1, round(score, 2)))


# Singleton access
_strategy_optimizer: Optional[StrategyOptimizer] = None

def get_strategy_optimizer() -> StrategyOptimizer:
    global _strategy_optimizer
    if _strategy_optimizer is None:
        _strategy_optimizer = StrategyOptimizer()
    return _strategy_optimizer
