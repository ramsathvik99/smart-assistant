"""
Smart Assistant — Canonical Continuous Learning & Long-Term Adaptation Engine (PHASE 9)

Enables controlled, explainable, bounded long-term strategy learning from verified
execution experiences without bypassing current environment state, explicit user intent,
risk policy, confirmation requirements, or outcome verification.

Core Architectural Invariants:
1. HIERARCHY OF AUTHORITY:
   USER INTENT > AUTHORIZATION > POLICY > CURRENT ENVIRONMENT > SAFETY/DUPLICATE PROTECTION > STRATEGY OPTIMIZATION > LEARNED EXPERIENCE
2. ADVISORY ONLY:
   Historical experience and learning signals are strictly advisory to StrategyOptimizer.
   Learning NEVER directly executes actions, NEVER lowers risk level, NEVER bypasses confirmation.
3. VERIFIED OUTCOMES AS TRUTH:
   Only verified execution outcomes (OutcomeVerifier) can strongly reinforce strategies.
4. OUTCOME DIFFERENTIATION:
   Distinguishes verified success, verified failure, uncertain outcome, policy block,
   confirmation denial, user cancellation, duplicate prevention, recovery success/failure.
   Policy blocks and confirmation denials NEVER become negative strategy learning.
5. USER ISOLATION:
   Learning signals are strictly user-scoped by default. Cross-user learning leakage is 0.
   Global learning is disabled by default.
6. CONSERVATIVE EVIDENCE & RECENCY DECAY:
   Single success cannot produce high confidence. Evidence thresholds prevent overfitting.
   Bounded exponential half-life decay discounts stale experience.
7. SAFE EXPLORATION ONLY:
   Exploration is strictly restricted to LOW-risk, reversible actions with full telemetry.
8. OSCILLATION & STARVATION PROTECTION:
   Detects and penalizes strategy flip-flopping under intermittent failure.
9. TARGETED INVALIDATION & STRATEGY VERSIONING:
   Supports version-aware strategy matching and selective signal invalidation.
10. NO DUPLICATE MEMORY:
    Consumes existing ExecutionExperienceManager and persists learning signals.
"""

from __future__ import annotations

import os
import re
import time
import math
import uuid
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from core.db_pool import get_db_pool
from core.outcome_verifier import OutcomeStatus, ConfidenceLevel
from core.execution_experience import ExecutionExperience, redact_secrets, sanitize_environment_context


# ============================================================================
# Enumerations
# ============================================================================

class OutcomeType(str, Enum):
    """Fine-grained classification of execution episode outcomes."""
    VERIFIED_SUCCESS      = "VERIFIED_SUCCESS"       # True verified real-world success
    VERIFIED_FAILURE      = "VERIFIED_FAILURE"       # True verified failure of execution
    UNCERTAIN             = "UNCERTAIN"              # Verification inconclusive
    POLICY_BLOCK          = "POLICY_BLOCK"           # Action blocked by policy (not execution failure)
    CONFIRMATION_DENIED   = "CONFIRMATION_DENIED"    # User declined confirmation (not execution failure)
    USER_CANCELLED        = "USER_CANCELLED"         # User aborted execution (not execution failure)
    DUPLICATE_PREVENTION  = "DUPLICATE_PREVENTION"   # Action suppressed to prevent duplicate side-effect
    ALREADY_SATISFIED     = "ALREADY_SATISFIED"      # Goal was already satisfied in environment
    RECOVERY_SUCCESS      = "RECOVERY_SUCCESS"       # Adaptive recovery strategy verified success
    RECOVERY_FAILURE      = "RECOVERY_FAILURE"       # Adaptive recovery strategy verified failure
    RESOURCE_MISSING      = "RESOURCE_MISSING"       # Target file/app/resource not found in environment
    PERMISSION_FAILURE    = "PERMISSION_FAILURE"     # OS/filesystem permission denied
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE" # Network or external dependency missing


class LearningConfidence(str, Enum):
    """Categorical confidence in learned strategy preference."""
    LOW    = "LOW"       # Insufficient sample volume, single success, or high variance
    MEDIUM = "MEDIUM"    # Consistent evidence across multiple episodes with low staleness
    HIGH   = "HIGH"      # Substantial verified evidence (>=5 samples), high consistency, high recency


# ============================================================================
# Canonical Learning Data Models
# ============================================================================

@dataclass
class LearningEvidence:
    """Individual unit of structured learning evidence derived from an execution episode."""
    evidence_id: str
    user_id: int
    strategy_id: str
    strategy_version: str
    intent: str
    context_signature: str
    outcome_type: OutcomeType
    verification_status: str
    evidence_strength: float = 1.0
    environment_context: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None

    @property
    def evidence_count(self) -> int:
        return self.sample_count

    @property
    def success_count(self) -> int:
        return self.verified_success_count

    @property
    def failure_count(self) -> int:
        return self.verified_failure_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "user_id": self.user_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "intent": self.intent,
            "context_signature": self.context_signature,
            "outcome_type": self.outcome_type.value if isinstance(self.outcome_type, OutcomeType) else str(self.outcome_type),
            "verification_status": self.verification_status,
            "evidence_strength": self.evidence_strength,
            "environment_context": self.environment_context,
            "provenance": self.provenance,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass
class LearningSignal:
    """
    Aggregated, bounded advisory learning signal for a specific strategy and context.
    Supplies scoring inputs to StrategyOptimizer.
    """
    strategy_id: str
    strategy_version: str
    intent: str
    context_signature: str
    confidence: LearningConfidence
    confidence_score: float                  # Bounded 0.0 - 1.0
    effective_score_modifier: float          # Bounded adjustment for StrategyOptimizer ranking
    sample_count: int = 0
    verified_success_count: int = 0
    verified_failure_count: int = 0
    uncertain_count: int = 0
    recovery_success_count: int = 0
    recovery_failure_count: int = 0
    non_execution_blocks: int = 0            # Policy/confirmation/cancellation counts (unpenalized)
    recency_factor: float = 1.0              # Staleness decay multiplier (0.15 - 1.0)
    oscillation_penalty: float = 0.0         # Penalty applied if oscillation is detected
    explanation: str = ""
    user_id: int = 1
    last_updated: float = field(default_factory=time.time)

    @property
    def evidence_count(self) -> int:
        return self.sample_count

    @property
    def failure_count(self) -> int:
        return self.verified_failure_count

    @property
    def success_count(self) -> int:
        return self.verified_success_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "intent": self.intent,
            "context_signature": self.context_signature,
            "confidence": self.confidence.value,
            "confidence_score": self.confidence_score,
            "effective_score_modifier": self.effective_score_modifier,
            "sample_count": self.sample_count,
            "verified_success_count": self.verified_success_count,
            "verified_failure_count": self.verified_failure_count,
            "uncertain_count": self.uncertain_count,
            "recovery_success_count": self.recovery_success_count,
            "recovery_failure_count": self.recovery_failure_count,
            "non_execution_blocks": self.non_execution_blocks,
            "recency_factor": self.recency_factor,
            "oscillation_penalty": self.oscillation_penalty,
            "explanation": self.explanation,
            "user_id": self.user_id,
            "last_updated": self.last_updated,
        }


@dataclass
class LearningDecision:
    """Advisory recommendation for a strategy candidate."""
    strategy_id: str
    strategy_version: str
    recommended: bool
    confidence: LearningConfidence
    score_modifier: float
    explanation: str
    context_match: float
    is_exploratory: bool = False
    exploration_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "recommended": self.recommended,
            "confidence": self.confidence.value,
            "score_modifier": self.score_modifier,
            "explanation": self.explanation,
            "context_match": self.context_match,
            "is_exploratory": self.is_exploratory,
            "exploration_reason": self.exploration_reason,
        }


@dataclass
class ExplorationTelemetry:
    """Structured telemetry record for every exploratory strategy candidate."""
    exploration_id: str
    user_id: int
    intent: str
    candidate_strategy: str
    strategy_version: str
    risk_level: str
    policy_result: str                       # Must be ALLOWED
    is_safe: bool
    reason: str
    outcome: Optional[str] = None
    was_novel: bool = True
    improved_performance: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearningSummary:
    """High-level summary of active learned strategies for an intent/context."""
    user_id: int
    intent: str
    context_signature: str
    signals: Dict[str, LearningSignal] = field(default_factory=dict)
    total_evidence_units: int = 0
    preferred_strategy: Optional[str] = None
    active_versions: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "intent": self.intent,
            "context_signature": self.context_signature,
            "signals": {k: v.to_dict() for k, v in self.signals.items()},
            "total_evidence_units": self.total_evidence_units,
            "preferred_strategy": self.preferred_strategy,
            "active_versions": self.active_versions,
        }


@dataclass
class LearningPolicy:
    """Configurable boundaries and thresholds for continuous learning."""
    min_evidence_threshold: int = 3          # Samples required before strong confidence
    high_confidence_threshold: int = 5       # Samples required for HIGH confidence
    staleness_half_life_days: float = 60.0   # Days until evidence weight drops by 50%
    retention_days: int = 90                 # Retention window for learning signals
    allow_global_learning: bool = False      # Default: strictly user-scoped
    exploration_enabled: bool = True         # Allow safe exploration
    max_exploration_risk: str = "LOW"        # Only LOW allowed
    oscillation_threshold: int = 3           # Alternating failures before penalty
    cooldown_seconds: float = 300.0          # Cooldown after repeated failures
    cross_version_discount: float = 0.0      # Strict version isolation: 0.0 means old version evidence does not transfer to new version


# ============================================================================
# Canonical Continuous Learning Engine
# ============================================================================

class ContinuousLearningEngine:
    """
    Canonical Continuous Learning & Long-Term Adaptation Engine.
    Processes execution episodes into differentiated evidence units, tracks
    strategy versions, enforces recency decay, calculates confidence levels,
    prevents oscillation, and supplies bounded advisory signals to StrategyOptimizer.
    """

    def __init__(self, policy: Optional[LearningPolicy] = None):
        self.policy = policy or LearningPolicy()
        self.pool = get_db_pool()
        # In-memory store for fast retrieval and test isolation
        self._evidence_store: List[LearningEvidence] = []
        self._exploration_telemetry: List[ExplorationTelemetry] = []
        self._invalidated_filters: List[Dict[str, Any]] = []
        # Strategy execution history for oscillation detection: key=(user_id, intent, sig) -> list of (strat_id, outcome, time)
        self._execution_history: Dict[str, List[Tuple[str, str, float]]] = {}

    # ------------------------------------------------------------------------
    # 1. Outcome Classification & Evidence Ingestion
    # ------------------------------------------------------------------------

    def classify_outcome(
        self,
        verification_status: str,
        failure_classification: Optional[str] = None,
        policy_blocked: bool = False,
        confirmation_denied: bool = False,
        user_cancelled: bool = False,
        is_recovery: bool = False,
        already_satisfied: bool = False
    ) -> OutcomeType:
        """
        Deterministically classifies an episode outcome into fine-grained OutcomeType.
        Guarantees that policy blocks, user cancellations, and confirmation denials
        are NOT misclassified as execution failures.
        """
        if policy_blocked:
            return OutcomeType.POLICY_BLOCK
        if confirmation_denied:
            return OutcomeType.CONFIRMATION_DENIED
        if user_cancelled:
            return OutcomeType.USER_CANCELLED
        if already_satisfied:
            return OutcomeType.ALREADY_SATISFIED

        f_class = (failure_classification or "").upper()
        if "DUPLICATE" in f_class:
            return OutcomeType.DUPLICATE_PREVENTION
        if "POLICY" in f_class:
            return OutcomeType.POLICY_BLOCK
        if "CONFIRMATION" in f_class:
            return OutcomeType.CONFIRMATION_DENIED
        if "CANCEL" in f_class:
            return OutcomeType.USER_CANCELLED
        if "ALREADY_SATISFIED" in f_class:
            return OutcomeType.ALREADY_SATISFIED
        if "RESOURCE_MISSING" in f_class or "NOT_FOUND" in f_class:
            return OutcomeType.RESOURCE_MISSING
        if "PERMISSION" in f_class:
            return OutcomeType.PERMISSION_FAILURE
        if "DENIED" in f_class:
            return OutcomeType.CONFIRMATION_DENIED if "CONFIRM" in f_class else OutcomeType.PERMISSION_FAILURE
        if "NETWORK" in f_class or "DEPENDENCY" in f_class:
            return OutcomeType.DEPENDENCY_UNAVAILABLE

        v_stat = (verification_status or "").upper()
        if v_stat == OutcomeStatus.VERIFIED_SUCCESS.value or v_stat == "VERIFIED_SUCCESS":
            return OutcomeType.RECOVERY_SUCCESS if is_recovery else OutcomeType.VERIFIED_SUCCESS
        elif v_stat == OutcomeStatus.VERIFIED_FAILURE.value or v_stat == "VERIFIED_FAILURE":
            return OutcomeType.RECOVERY_FAILURE if is_recovery else OutcomeType.VERIFIED_FAILURE
        elif v_stat == OutcomeStatus.UNCERTAIN.value or v_stat == "UNCERTAIN":
            return OutcomeType.UNCERTAIN

        return OutcomeType.UNCERTAIN

    def process_experience(
        self,
        exp: ExecutionExperience,
        strategy_version: str = "v1",
        policy_blocked: bool = False,
        confirmation_denied: bool = False,
        user_cancelled: bool = False,
        already_satisfied: bool = False
    ) -> List[LearningEvidence]:
        """
        Consumes an ExecutionExperience episode and generates structured,
        differentiated LearningEvidence units for initial attempts and recovery strategies.
        """
        if not exp or not exp.user_id:
            return []

        user_id = int(exp.user_id)
        evidence_list: List[LearningEvidence] = []
        now = exp.created_at if exp.created_at else time.time()
        ctx_sig = exp.command_signature or f"{exp.intent}:generic"

        # Auto-infer non-execution flags from experience state if not explicitly passed
        meta = exp.metadata if isinstance(getattr(exp, "metadata", None), dict) else {}
        f_class_up = (getattr(exp, "failure_classification", "") or "").upper()
        f_stat_low = (getattr(exp, "final_status", "") or "").lower()
        v_stat_up = (getattr(exp, "verification_status", "") or "").upper()

        p_blocked = policy_blocked or (f_stat_low in ("blocked", "policy_blocked")) or meta.get("policy_blocked", False) or ("POLICY" in f_class_up)
        c_denied = confirmation_denied or (f_stat_low in ("denied", "confirmation_denied")) or meta.get("confirmation_denied", False) or ("CONFIRMATION" in f_class_up)
        u_cancelled = user_cancelled or (f_stat_low in ("cancelled", "user_cancelled")) or meta.get("user_cancelled", False) or ("CANCEL" in f_class_up)
        a_satisfied = already_satisfied or (f_stat_low in ("already_satisfied",)) or (v_stat_up in ("ALREADY_SATISFIED",)) or meta.get("already_satisfied", False)

        # Check attempts array first for fine-grained steps
        attempts = exp.attempts if isinstance(exp.attempts, list) else []

        if attempts:
            for att in attempts:
                strat_id = att.get("strategy_id") or "UNKNOWN_STRATEGY"
                is_recovery = att.get("strategy_type") in ("retry", "adaptive")
                v_stat = att.get("verification_status") or exp.verification_status
                att_meta = att.get("metadata", {}) if isinstance(att.get("metadata"), dict) else {}

                outcome_type = self.classify_outcome(
                    verification_status=v_stat,
                    failure_classification=att.get("failure_classification") or exp.failure_classification,
                    policy_blocked=p_blocked or att_meta.get("policy_blocked", False),
                    confirmation_denied=c_denied or att_meta.get("confirmation_denied", False),
                    user_cancelled=u_cancelled or att_meta.get("user_cancelled", False),
                    is_recovery=is_recovery,
                    already_satisfied=a_satisfied or att_meta.get("already_satisfied", False)
                )

                ev = self._create_evidence_unit(
                    user_id=user_id,
                    strategy_id=strat_id,
                    strategy_version=strategy_version,
                    intent=exp.intent,
                    context_signature=ctx_sig,
                    outcome_type=outcome_type,
                    verification_status=v_stat,
                    env_context=exp.environment_context,
                    source_exp_id=exp.experience_id,
                    execution_id=exp.execution_id,
                    created_at=now
                )
                evidence_list.append(ev)
                self._record_history(user_id, exp.intent, ctx_sig, strat_id, outcome_type.value, now)

        else:
            # Fallback to top-level strategy_id
            strat_id = exp.strategy_id or "DIRECT_ACTION"
            is_recovery = exp.strategy_type == "adaptive"

            outcome_type = self.classify_outcome(
                verification_status=exp.verification_status,
                failure_classification=exp.failure_classification,
                policy_blocked=p_blocked,
                confirmation_denied=c_denied,
                user_cancelled=u_cancelled,
                is_recovery=is_recovery,
                already_satisfied=a_satisfied
            )


            ev = self._create_evidence_unit(
                user_id=user_id,
                strategy_id=strat_id,
                strategy_version=strategy_version,
                intent=exp.intent,
                context_signature=ctx_sig,
                outcome_type=outcome_type,
                verification_status=exp.verification_status,
                env_context=exp.environment_context,
                source_exp_id=exp.experience_id,
                execution_id=exp.execution_id,
                created_at=now
            )
            evidence_list.append(ev)
            self._record_history(user_id, exp.intent, ctx_sig, strat_id, outcome_type.value, now)

        # Store in memory & persist to DB
        for ev in evidence_list:
            self._evidence_store.append(ev)
            self._persist_evidence(ev)

        return evidence_list

    def _create_evidence_unit(
        self,
        user_id: int,
        strategy_id: str,
        strategy_version: str,
        intent: str,
        context_signature: str,
        outcome_type: OutcomeType,
        verification_status: str,
        env_context: Dict[str, Any],
        source_exp_id: str,
        execution_id: str,
        created_at: float
    ) -> LearningEvidence:
        """Helper to create a sanitized, provenance-tracked LearningEvidence instance."""
        # Calculate evidence strength based on outcome type
        strength = 1.0
        if outcome_type in (OutcomeType.POLICY_BLOCK, OutcomeType.CONFIRMATION_DENIED, OutcomeType.USER_CANCELLED):
            strength = 0.0  # Zero weight for non-execution blocks
        elif outcome_type == OutcomeType.UNCERTAIN:
            strength = 0.1  # Minimal dampening weight
        elif outcome_type in (OutcomeType.VERIFIED_SUCCESS, OutcomeType.RECOVERY_SUCCESS):
            strength = 1.0
        elif outcome_type in (OutcomeType.VERIFIED_FAILURE, OutcomeType.RECOVERY_FAILURE):
            strength = 1.0

        provenance = {
            "source_experience_id": source_exp_id,
            "execution_id": execution_id,
            "strategy_version": strategy_version,
            "verification_status": verification_status,
            "sanitized": True
        }

        # Retention expiration
        expires_at = created_at + (self.policy.retention_days * 86400.0)

        return LearningEvidence(
            evidence_id=f"lev_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            intent=intent,
            context_signature=context_signature,
            outcome_type=outcome_type,
            verification_status=verification_status,
            evidence_strength=strength,
            environment_context=sanitize_environment_context(env_context),
            provenance=redact_secrets(provenance),
            created_at=created_at,
            expires_at=expires_at
        )

    # ------------------------------------------------------------------------
    # 2. Learning Signal Generation & Confidence Computation
    # ------------------------------------------------------------------------

    def get_learning_signal(
        self,
        strategy_id: str,
        user_id: int,
        intent: str,
        context_signature: str,
        current_env: Optional[Dict[str, Any]] = None,
        target_version: str = "v1"
    ) -> LearningSignal:
        """
        Aggregates relevant learning evidence to produce a bounded, advisory LearningSignal.
        Enforces user isolation, strategy versioning, staleness decay, and oscillation detection.
        """
        now = time.time()
        relevant_evidence = self._get_active_evidence(
            user_id=user_id,
            intent=intent,
            context_signature=context_signature,
            strategy_id=strategy_id
        )

        sample_count = 0
        succ_count = 0
        fail_count = 0
        unc_count = 0
        rec_succ_count = 0
        rec_fail_count = 0
        block_count = 0

        weighted_succ = 0.0
        weighted_fail = 0.0
        latest_timestamp = 0.0

        sum_ctx_sim = 0.0
        sum_version_factor = 0.0
        sum_staleness = 0.0

        for ev in relevant_evidence:
            latest_timestamp = max(latest_timestamp, ev.created_at)

            # Strategy version compatibility check
            version_factor = 1.0
            if ev.strategy_version != target_version:
                # Evidence for older or mismatched versions is discounted/isolated according to policy
                version_factor = self.policy.cross_version_discount

            # Recency / staleness decay factor
            age_days = max(0.0, (now - ev.created_at) / 86400.0)
            staleness = math.exp(-0.693 * (age_days / max(1.0, self.policy.staleness_half_life_days)))
            staleness = max(0.15, staleness)  # Floor at 15%

            # Contextual similarity match
            ctx_sim = self.calculate_context_similarity(
                ev_intent=ev.intent,
                ev_sig=ev.context_signature,
                ev_env=ev.environment_context,
                target_intent=intent,
                target_sig=context_signature,
                current_env=current_env or {}
            )

            sum_ctx_sim += ctx_sim
            sum_version_factor += version_factor
            sum_staleness += staleness

            effective_weight = ev.evidence_strength * version_factor * staleness * ctx_sim

            sample_count += 1
            ot = ev.outcome_type

            if ot in (
                OutcomeType.POLICY_BLOCK,
                OutcomeType.CONFIRMATION_DENIED,
                OutcomeType.USER_CANCELLED,
                OutcomeType.DUPLICATE_PREVENTION,
                OutcomeType.ALREADY_SATISFIED
            ):
                block_count += 1
                # Non-execution blocks and pre-satisfied states do NOT count as strategy failures
                continue

            elif ot == OutcomeType.VERIFIED_SUCCESS:
                succ_count += 1
                weighted_succ += effective_weight
            elif ot == OutcomeType.RECOVERY_SUCCESS:
                rec_succ_count += 1
                weighted_succ += (effective_weight * 1.2)  # Successful recovery is strongly positive
            elif ot == OutcomeType.VERIFIED_FAILURE:
                fail_count += 1
                weighted_fail += effective_weight
            elif ot == OutcomeType.RECOVERY_FAILURE:
                rec_fail_count += 1
                weighted_fail += (effective_weight * 1.2)
            elif ot == OutcomeType.UNCERTAIN:
                unc_count += 1
                # Uncertain outcomes have 0 positive contribution

        # Effective samples excluding non-execution policy/confirmation blocks
        effective_samples = succ_count + rec_succ_count + fail_count + rec_fail_count + unc_count

        # Confidence determination:
        # LOW: < min_threshold (default 3), or high uncertainty, or single success
        # MEDIUM: >= 3 samples, consistent success/failure
        # HIGH: >= 5 samples, high consistency, recent
        confidence = LearningConfidence.LOW
        conf_score = 0.0

        if effective_samples >= self.policy.high_confidence_threshold and (succ_count + rec_succ_count) >= 4:
            # Check recency
            recency_days = (now - latest_timestamp) / 86400.0 if latest_timestamp else 999.0
            if recency_days <= self.policy.staleness_half_life_days:
                confidence = LearningConfidence.HIGH
                conf_score = min(1.0, 0.7 + (effective_samples / 20.0))
            else:
                confidence = LearningConfidence.MEDIUM
                conf_score = 0.65
        elif effective_samples >= self.policy.min_evidence_threshold:
            confidence = LearningConfidence.MEDIUM
            conf_score = min(0.7, 0.4 + (effective_samples / 10.0))
        elif effective_samples > 0:
            confidence = LearningConfidence.LOW
            conf_score = min(0.35, 0.15 * effective_samples)

        # Oscillation check
        osc_penalty = self.detect_oscillation(user_id, intent, context_signature, strategy_id)

        # Score modifier calculation (bounded to -20.0 to +20.0)
        score_mod = 0.0
        if effective_samples > 0:
            total_weighted = weighted_succ + weighted_fail
            if total_weighted > 0.0:
                net_rate = (weighted_succ - weighted_fail) / total_weighted
                # Scale by confidence score and dampening for small samples
                dampening = 0.3 if effective_samples < self.policy.min_evidence_threshold else 1.0
                avg_ctx_sim = sum_ctx_sim / effective_samples
                avg_version = sum_version_factor / effective_samples
                avg_stale = sum_staleness / effective_samples
                score_mod = round(net_rate * 20.0 * dampening * conf_score * avg_ctx_sim * avg_version * avg_stale, 2)

        # Apply oscillation penalty
        if osc_penalty > 0.0:
            score_mod = round(score_mod - osc_penalty, 2)

        # Explainable rationale
        explanation = self._build_explanation(
            strategy_id=strategy_id,
            strategy_version=target_version,
            confidence=confidence,
            succ=succ_count + rec_succ_count,
            fail=fail_count + rec_fail_count,
            unc=unc_count,
            blocks=block_count,
            mod=score_mod,
            osc_penalty=osc_penalty
        )

        return LearningSignal(
            strategy_id=strategy_id,
            strategy_version=target_version,
            intent=intent,
            context_signature=context_signature,
            confidence=confidence,
            confidence_score=round(conf_score, 2),
            effective_score_modifier=score_mod,
            sample_count=sample_count,
            verified_success_count=succ_count,
            verified_failure_count=fail_count,
            uncertain_count=unc_count,
            recovery_success_count=rec_succ_count,
            recovery_failure_count=rec_fail_count,
            non_execution_blocks=block_count,
            recency_factor=round(math.exp(-0.693 * (max(0.0, (now - latest_timestamp) / 86400.0) / max(1.0, self.policy.staleness_half_life_days))) if latest_timestamp else 1.0, 2),
            oscillation_penalty=osc_penalty,
            explanation=explanation,
            user_id=user_id,
            last_updated=now
        )

    # ------------------------------------------------------------------------
    # 3. Contextual Similarity & Oscillation Protection
    # ------------------------------------------------------------------------

    def calculate_context_similarity(
        self,
        ev_intent: str,
        ev_sig: str,
        ev_env: Dict[str, Any],
        target_intent: str,
        target_sig: str,
        current_env: Dict[str, Any]
    ) -> float:
        """
        Calculates normalized context similarity score (0.1 to 1.0).
        Different OS platforms or major application mismatches heavily penalize similarity.
        """
        if ev_intent != target_intent:
            return 0.1

        score = 0.5  # Base match for same intent

        if ev_sig and target_sig:
            if ev_sig == target_sig:
                score += 0.35  # Exact command signature match
            elif ev_sig.split(":")[0] == target_sig.split(":")[0]:
                score += 0.15  # Action family match

        # OS Platform compatibility
        ev_os = str(ev_env.get("platform") or "").lower()
        curr_os = str(current_env.get("platform") or "").lower()
        if ev_os and curr_os:
            if ev_os == curr_os:
                score += 0.15
            else:
                score = min(score - 0.45, 0.20)  # Severe penalty for OS mismatch, capped at 0.20

        # Active application compatibility
        ev_app = str(ev_env.get("active_application") or "").lower()
        curr_app = str(current_env.get("active_application") or "").lower()
        if ev_app and curr_app and ev_app == curr_app:
            score += 0.10

        return min(1.0, max(0.1, round(score, 2)))

    def _record_history(self, user_id: int, intent: str, sig: str, strat_id: str, outcome: str, timestamp: float):
        """Maintains bounded execution history for oscillation detection."""
        key = f"{user_id}:{intent}:{sig}"
        if key not in self._execution_history:
            self._execution_history[key] = []
        self._execution_history[key].append((strat_id, outcome, timestamp))
        # Keep last 20 events
        if len(self._execution_history[key]) > 20:
            self._execution_history[key] = self._execution_history[key][-20:]

    def detect_oscillation(self, user_id: int, intent: str, sig: str, strategy_id: str) -> float:
        """
        Detects alternating failure patterns between competing strategies.
        If Strategy A and Strategy B alternate failures within a short window,
        returns an oscillation penalty (e.g. 8.0) to stabilize strategy ranking.
        """
        key = f"{user_id}:{intent}:{sig}"
        history = self._execution_history.get(key, [])
        if len(history) < self.policy.oscillation_threshold:
            return 0.0

        # Look at last 6 attempts
        recent = history[-6:]
        strats_used = [item[0] for item in recent]
        failures = [item for item in recent if "FAILURE" in item[1]]

        # If at least 2 distinct strategies failed alternately
        unique_failed_strats = set(item[0] for item in failures)
        if len(unique_failed_strats) >= 2 and len(failures) >= 3:
            # Oscillation detected
            if strategy_id in unique_failed_strats:
                return 8.0  # Apply 8-point stability penalty to suppress flip-flopping

        return 0.0

    # ------------------------------------------------------------------------
    # 4. Safe Exploration Governance
    # ------------------------------------------------------------------------

    def evaluate_exploration(
        self,
        candidate_strategy: Any,
        policy_result: str,
        user_id: int,
        intent: str,
        sample_count: int
    ) -> Tuple[bool, Optional[ExplorationTelemetry]]:
        """
        Evaluates whether a candidate strategy qualifies for safe exploration.
        EXPLORATION RULES:
        1. Policy result MUST be ALLOWED.
        2. Risk level MUST be LOW.
        3. Action MUST NOT be high-risk or external side-effect.
        4. Sample volume MUST be below minimum evidence threshold.
        5. Telemetry is always generated.
        """
        strat_id = getattr(candidate_strategy, "strategy_id", "UNKNOWN")
        risk_level = str(getattr(candidate_strategy, "risk_level", "low")).upper()
        is_safe = (risk_level == "LOW" and policy_result == "ALLOWED")

        eligible = (
            self.policy.exploration_enabled
            and is_safe
            and sample_count < self.policy.min_evidence_threshold
        )

        reason = "Safe low-risk exploration" if eligible else (
            f"Exploration blocked: risk={risk_level}, policy={policy_result}"
        )

        telemetry = ExplorationTelemetry(
            exploration_id=f"exp_{uuid.uuid4().hex[:10]}",
            user_id=user_id,
            intent=intent,
            candidate_strategy=strat_id,
            strategy_version=getattr(candidate_strategy, "version", "v1"),
            risk_level=risk_level,
            policy_result=policy_result,
            is_safe=is_safe,
            reason=reason,
            was_novel=(sample_count == 0),
            timestamp=time.time()
        )

        self._exploration_telemetry.append(telemetry)
        return eligible, telemetry

    # ------------------------------------------------------------------------
    # 5. Targeted Signal Invalidation & Reset
    # ------------------------------------------------------------------------

    def invalidate_learned_signals(
        self,
        user_id: int,
        intent: Optional[str] = None,
        strategy_id: Optional[str] = None,
        strategy_version: Optional[str] = None,
        reason: str = "Manual or automated invalidation"
    ) -> int:
        """
        Selectively invalidates learned evidence without deleting raw execution history.
        Preserves raw audit logs while resetting learned preference signals.
        """
        filter_entry = {
            "user_id": user_id,
            "intent": intent,
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "reason": reason,
            "invalidated_at": time.time()
        }
        self._invalidated_filters.append(filter_entry)

        # Count affected in-memory evidence
        count = 0
        for ev in self._evidence_store:
            if ev.user_id == user_id:
                if intent and ev.intent != intent:
                    continue
                if strategy_id and ev.strategy_id != strategy_id:
                    continue
                if strategy_version and ev.strategy_version != strategy_version:
                    continue
                count += 1

        # Invalidate in DB table if active
        if self.pool and self.pool.is_healthy():
            try:
                with self.pool.get_cursor() as cur:
                    query = "DELETE FROM strategy_learning_signals WHERE user_id = %s"
                    params = [user_id]
                    if intent:
                        query += " AND intent = %s"
                        params.append(intent)
                    if strategy_id:
                        query += " AND strategy_id = %s"
                        params.append(strategy_id)
                    if strategy_version:
                        query += " AND strategy_version = %s"
                        params.append(strategy_version)
                    cur.execute(query, tuple(params))
            except Exception as e:
                print(f"[LEARNING] [WARN] Signal invalidation DB note: {e}")

        return count

    # ------------------------------------------------------------------------
    # 6. Explanation & Persistence Helpers
    # ------------------------------------------------------------------------

    def _build_explanation(
        self,
        strategy_id: str,
        strategy_version: str,
        confidence: LearningConfidence,
        succ: int,
        fail: int,
        unc: int,
        blocks: int,
        mod: float,
        osc_penalty: float
    ) -> str:
        """Generates clear, privacy-safe explanation for learned preference."""
        parts = [
            f"Strategy '{strategy_id}' ({strategy_version})",
            f"Confidence: {confidence.value}",
            f"Evidence: {succ} verified successes, {fail} failures, {unc} uncertain"
        ]
        if blocks > 0:
            parts.append(f"{blocks} non-execution blocks (unpenalized)")
        if osc_penalty > 0.0:
            parts.append(f"Oscillation penalty: -{osc_penalty:.1f}")
        parts.append(f"Score modifier: {mod:+.1f}")
        return redact_secrets("; ".join(parts))

    def _get_active_evidence(
        self,
        user_id: int,
        intent: str,
        context_signature: str,
        strategy_id: str
    ) -> List[LearningEvidence]:
        """Retrieves active, non-invalidated, non-expired evidence for a user."""
        active: List[LearningEvidence] = []
        now = time.time()

        for ev in self._evidence_store:
            # 1. User isolation check (unless global learning explicitly enabled)
            if not self.policy.allow_global_learning and ev.user_id != user_id:
                continue

            # 2. Expiration check
            if ev.expires_at and now > ev.expires_at:
                continue

            # 3. Invalidation check
            if self._is_invalidated(ev):
                continue

            # 4. Strategy & Intent match
            if ev.strategy_id == strategy_id and ev.intent == intent:
                active.append(ev)

        return active

    def _is_invalidated(self, ev: LearningEvidence) -> bool:
        """Checks if an evidence unit matches any active invalidation filter."""
        for f in self._invalidated_filters:
            if f["user_id"] == ev.user_id:
                if f.get("intent") and f["intent"] != ev.intent:
                    continue
                if f.get("strategy_id") and f["strategy_id"] != ev.strategy_id:
                    continue
                if f.get("strategy_version") and f["strategy_version"] != ev.strategy_version:
                    continue
                if ev.created_at < f["invalidated_at"]:
                    return True
        return False

    def _persist_evidence(self, ev: LearningEvidence) -> bool:
        """Persists a learning evidence signal to PostgreSQL if available."""
        if not self.pool or not self.pool.is_healthy():
            return False

        try:
            with self.pool.get_cursor() as cur:
                cur.execute("""
                    INSERT INTO strategy_learning_signals (
                        signal_id, user_id, strategy_id, strategy_version,
                        intent, context_signature, evidence_type, evidence_strength,
                        outcome, verification_status, confidence, provenance,
                        created_at, expires_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        to_timestamp(%s), to_timestamp(%s)
                    )
                    ON CONFLICT (signal_id) DO NOTHING;
                """, (
                    ev.evidence_id,
                    ev.user_id,
                    ev.strategy_id,
                    ev.strategy_version,
                    ev.intent,
                    ev.context_signature,
                    ev.outcome_type.value,
                    ev.evidence_strength,
                    ev.outcome_type.value,
                    ev.verification_status,
                    "LOW",
                    json.dumps(ev.provenance),
                    ev.created_at,
                    ev.expires_at or (ev.created_at + 7776000)
                ))
            return True
        except Exception as e:
            # Non-blocking resilience
            return False


# ============================================================================
# Singleton Accessor
# ============================================================================

_global_learning_engine: Optional[ContinuousLearningEngine] = None

def get_learning_engine() -> ContinuousLearningEngine:
    global _global_learning_engine
    if _global_learning_engine is None:
        _global_learning_engine = ContinuousLearningEngine()
    return _global_learning_engine
