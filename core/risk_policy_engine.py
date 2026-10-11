"""
Smart Assistant — Canonical Risk Policy Engine (PHASE 7)

A deterministic, stateless governance layer that evaluates whether a proposed
action is ALLOWED, ALLOWED_WITH_CONFIRMATION, BLOCKED, or UNCERTAIN before
execution.

Architecture Position:
    USER COMMAND
        -> INTENT
        -> ROUTER / PLANNER
        -> RiskPolicyEngine.evaluate()   <- THIS MODULE
        -> EXECUTION (only if ALLOWED or confirmed ALLOWED_WITH_CONFIRMATION)
        -> OutcomeVerifier
        -> ExecutionExperienceManager

Key Invariants:
    1. POLICY > STRATEGY OPTIMIZATION — blocked strategies stay blocked regardless
       of historical success rate.
    2. HISTORICAL EXPERIENCE != AUTHORIZATION — 100% success history does NOT
       lower risk classification or remove confirmation requirements.
    3. HIGH/CRITICAL actions FAIL CLOSED — if policy evaluation itself errors,
       high-risk actions are returned as BLOCKED/UNCERTAIN, never silently executed.
    4. CURRENT ENVIRONMENT > HISTORY — live state can prevent duplicate side-effects.
    5. USER IDENTITY IS MANDATORY — user-scoped actions require a valid user_id.
    6. EXPLAINABILITY — every decision carries structured rule IDs and rationale.
    7. NO SECRETS IN LOGS — sensitive values are redacted from policy records.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================================
# Enumerations
# ============================================================================

class RiskLevel(str, Enum):
    """Canonical risk classification for proposed actions."""
    LOW      = "LOW"       # Read-only or fully reversible, no external effects
    MEDIUM   = "MEDIUM"    # Local state change, reversible, no external effects
    HIGH     = "HIGH"      # Significant local or external side-effect, harder to reverse
    CRITICAL = "CRITICAL"  # Irreversible external side-effects or privileged system ops


class Reversibility(str, Enum):
    """Reversibility classification for proposed actions."""
    REVERSIBLE           = "REVERSIBLE"           # Can be fully undone
    PARTIALLY_REVERSIBLE = "PARTIALLY_REVERSIBLE" # Can be partially undone
    IRREVERSIBLE         = "IRREVERSIBLE"          # Cannot be undone after execution
    UNKNOWN              = "UNKNOWN"               # Cannot be determined at policy time


class ExternalEffect(str, Enum):
    """Whether the action has side-effects outside the local process."""
    READ_ONLY       = "READ_ONLY"       # No state change
    LOCAL_CHANGE    = "LOCAL_CHANGE"    # Local filesystem / settings / memory only
    EXTERNAL_EFFECT = "EXTERNAL_EFFECT" # Network call, email, device, external API


class PolicyDecision(str, Enum):
    """Outcome of policy evaluation."""
    ALLOWED                    = "ALLOWED"                    # Execute immediately
    ALLOWED_WITH_CONFIRMATION  = "ALLOWED_WITH_CONFIRMATION"  # Pause for user confirmation
    BLOCKED                    = "BLOCKED"                    # Do not execute
    UNCERTAIN                  = "UNCERTAIN"                  # Cannot determine; conservative hold


# ============================================================================
# Policy Rule Registry
# ============================================================================

# Canonical rule IDs referenced in every PolicyEvaluation for explainability.
RULE_READ_ONLY_ALLOWED       = "POL-001"  # Read-only always allowed
RULE_LOW_RISK_ALLOWED        = "POL-002"  # Low-risk reversible allowed automatically
RULE_MEDIUM_REVERSIBLE_OK    = "POL-003"  # Medium reversible allowed if user authorized
RULE_HIGH_REQUIRES_CONFIRM   = "POL-004"  # High risk requires confirmation
RULE_CRITICAL_BLOCKED        = "POL-005"  # Critical risk blocked unless authorized pathway
RULE_EMAIL_PROTECTED         = "POL-006"  # Outbound email always requires confirmation
RULE_FILE_DELETE_PROTECTED   = "POL-007"  # File/folder deletion requires confirmation
RULE_EXTERNAL_EFFECT_CONFIRM = "POL-008"  # Any external side-effect requires confirmation
RULE_DUPLICATE_RISK_BLOCKED  = "POL-009"  # Potential duplicate side-effect blocked
RULE_USER_ID_REQUIRED        = "POL-010"  # User-scoped action requires valid user_id
RULE_USER_MISMATCH_BLOCKED   = "POL-011"  # User A cannot authorize User B's actions
RULE_HISTORY_NOT_AUTH        = "POL-012"  # Historical success does not grant authorization
RULE_FAIL_CLOSED_HIGH        = "POL-013"  # Engine error on HIGH/CRITICAL -> BLOCKED
RULE_IRREVERSIBLE_CONFIRM    = "POL-014"  # Irreversible actions require confirmation
RULE_SMART_HOME_CONFIRM      = "POL-015"  # Smart home state changes require confirmation
RULE_POWER_ACTION_CRITICAL   = "POL-016"  # Power actions (shutdown/restart) are CRITICAL
RULE_PROCESS_KILL_HIGH       = "POL-017"  # Killing processes is HIGH risk
RULE_SYSTEM_SETTINGS_MEDIUM  = "POL-018"  # Non-critical system settings are MEDIUM
RULE_PRIVILEGED_BLOCKED      = "POL-019"  # Admin/privilege-required actions blocked if not elevated


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class RiskAssessment:
    """Structured risk assessment for a proposed action."""
    risk_level:             RiskLevel
    reversibility:          Reversibility
    external_effect:        ExternalEffect
    duplicate_risk:         bool = False
    user_scope_required:    bool = True
    confirmation_required:  bool = False
    risk_factors:           List[str] = field(default_factory=list)
    rationale:              str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_level":            self.risk_level.value,
            "reversibility":         self.reversibility.value,
            "external_effect":       self.external_effect.value,
            "duplicate_risk":        self.duplicate_risk,
            "user_scope_required":   self.user_scope_required,
            "confirmation_required": self.confirmation_required,
            "risk_factors":          self.risk_factors,
            "rationale":             self.rationale,
        }


@dataclass
class ConfirmationRequest:
    """Specific, human-readable confirmation prompt for a proposed action."""
    action:          str
    target:          str
    effect:          str
    risk_level:      str
    reason:          str
    rules_applied:   List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action":        self.action,
            "target":        self.target,
            "effect":        self.effect,
            "risk_level":    self.risk_level,
            "reason":        self.reason,
            "rules_applied": self.rules_applied,
        }


@dataclass
class PolicyEvaluation:
    """
    Final result of policy evaluation for a proposed action.
    Contains the decision, structured assessment, and full audit trail.
    """
    decision:              PolicyDecision
    assessment:            RiskAssessment
    action_signature:      str
    policy_rules_applied:  List[str]
    rationale:             str
    requires_confirmation: bool
    evaluated_at:          float = field(default_factory=time.time)
    confirmation_request:  Optional[ConfirmationRequest] = None
    user_id:               Optional[int] = None

    def is_executable(self) -> bool:
        """True only if decision is ALLOWED (confirmation already obtained externally)."""
        return self.decision == PolicyDecision.ALLOWED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision":              self.decision.value,
            "assessment":            self.assessment.to_dict(),
            "action_signature":      self.action_signature,
            "policy_rules_applied":  self.policy_rules_applied,
            "rationale":             self.rationale,
            "requires_confirmation": self.requires_confirmation,
            "evaluated_at":          self.evaluated_at,
            "confirmation_request":  self.confirmation_request.to_dict() if self.confirmation_request else None,
            "user_id":               self.user_id,
        }


# ============================================================================
# Risk Taxonomy
# ============================================================================

# Maps intent names to their baseline (intent-level) risk.
# Actual risk may be elevated by operation + target + environment.
_INTENT_RISK_MAP: Dict[str, RiskLevel] = {
    # LOW — Read-only, observation, query
    "TIME_QUERY":          RiskLevel.LOW,
    "DATE_QUERY":          RiskLevel.LOW,
    "WEATHER_QUERY":       RiskLevel.LOW,
    "MEMORY_QUERY":        RiskLevel.LOW,
    "CALCULATOR":          RiskLevel.LOW,
    "WINDOW_CONTEXT":      RiskLevel.LOW,
    "AUDIO_DEVICES":       RiskLevel.LOW,
    "RECOMMENDATION":      RiskLevel.LOW,
    "GENERAL_CONVERSATION":RiskLevel.LOW,
    "RAG_SEARCH":          RiskLevel.LOW,
    "VISUAL_SURFACE":      RiskLevel.LOW,
    "DAILY_BRIEFING":      RiskLevel.LOW,
    "TRANSLATION":         RiskLevel.LOW,
    "CODE_GENERATION":     RiskLevel.LOW,   # Generation only; execution would be HIGH

    # MEDIUM — Reversible local state changes
    "OPEN_APPLICATION":    RiskLevel.MEDIUM,
    "CLOSE_APPLICATION":   RiskLevel.MEDIUM,
    "MUSIC":               RiskLevel.MEDIUM,
    "NOTES":               RiskLevel.MEDIUM,
    "MEMORY_STORE":        RiskLevel.MEDIUM,
    "LEARNING":            RiskLevel.MEDIUM,
    "TASK_MANAGEMENT":     RiskLevel.MEDIUM,
    "REMINDERS":           RiskLevel.MEDIUM,
    "DOCUMENT_GENERATION": RiskLevel.MEDIUM,
    "DEVICE_CONTROL":      RiskLevel.MEDIUM,  # Volume, brightness, etc.
    "SYSTEM_SETTINGS":     RiskLevel.MEDIUM,

    # HIGH — Significant side-effects, external impact, or harder to reverse
    "FILE_OPERATIONS":     RiskLevel.HIGH,    # Elevated further for delete ops
    "EMAIL":               RiskLevel.HIGH,
    "SMART_HOME":          RiskLevel.HIGH,
    "BROWSER":             RiskLevel.HIGH,
    "CALENDAR":            RiskLevel.HIGH,
    "UNDO":                RiskLevel.MEDIUM,  # Undo is generally reversing HIGH actions

    # CRITICAL — Irreversible system-level actions
    "POWER_ACTION":        RiskLevel.CRITICAL,
    "EMERGENCY":           RiskLevel.CRITICAL,
}

# Operations within FILE_OPERATIONS that elevate to CRITICAL
_CRITICAL_FILE_OPS = {"delete", "remove", "shred", "wipe", "format", "overwrite", "truncate"}
# Operations that keep FILE_OPERATIONS at MEDIUM (read-only)
_READONLY_FILE_OPS = {"read", "open", "view", "list", "find", "search", "info", "get", "check", "stat"}

# Secret patterns to redact from policy logs
_SECRET_PATTERNS = [
    re.compile(r'(?i)(password|passwd|pwd|secret|api[_-]?key|token|bearer|jwt)["\']?\s*[:=]\s*["\']?([^"\'\s,;]+)'),
    re.compile(r'(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}'),
    re.compile(r'ey[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}'),
]


def _redact_secrets(value: str) -> str:
    """Remove credential-like values from a string before logging."""
    # Pattern 1: key=value pairs (has 2 groups: key + value)
    value = _SECRET_PATTERNS[0].sub(r'\1=[REDACTED]', value)
    # Pattern 2: bearer token (no capture group to preserve)
    value = _SECRET_PATTERNS[1].sub('[REDACTED]', value)
    # Pattern 3: JWT tokens
    value = _SECRET_PATTERNS[2].sub('[REDACTED]', value)
    return value


# ============================================================================
# Risk Classifier
# ============================================================================

class RiskClassifier:
    """
    Deterministic risk classification based on intent + operation + target + environment.
    Historical success rate does NOT influence risk classification (POL-012, POL-017).
    """

    def classify(
        self,
        intent: str,
        command: str,
        action_result: Optional[Dict[str, Any]] = None,
        current_env: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ) -> RiskAssessment:
        """
        Returns a RiskAssessment for the proposed action.
        Risk is determined by intent + operation signals, NOT by historical experience.
        """
        intent_up = intent.upper().strip()
        cmd_low = command.lower().strip()
        action_result = action_result or {}
        current_env = current_env or {}
        risk_factors: List[str] = []

        # 1. Baseline risk from intent
        base_risk = _INTENT_RISK_MAP.get(intent_up, RiskLevel.MEDIUM)

        # 2. Elevate based on operation signals within the command
        risk = base_risk
        reversibility = Reversibility.REVERSIBLE
        ext_effect = ExternalEffect.LOCAL_CHANGE
        duplicate_risk = False
        confirmation_required = False

        # --- Read-only downgrade ---
        if intent_up in ("TIME_QUERY", "DATE_QUERY", "WEATHER_QUERY", "CALCULATOR",
                         "MEMORY_QUERY", "WINDOW_CONTEXT", "AUDIO_DEVICES",
                         "RECOMMENDATION", "RAG_SEARCH", "GENERAL_CONVERSATION",
                         "VISUAL_SURFACE", "DAILY_BRIEFING", "TRANSLATION",
                         "CODE_GENERATION"):
            ext_effect = ExternalEffect.READ_ONLY
            reversibility = Reversibility.REVERSIBLE

        # --- POWER_ACTION & SYSTEM SESSION: always CRITICAL + IRREVERSIBLE ---
        elif intent_up == "POWER_ACTION" or any(w in cmd_low for w in ["shutdown", "restart", "reboot", "hibernate", "sleep", "sign out", "sign off", "log off", "log out"]):
            risk = RiskLevel.CRITICAL
            reversibility = Reversibility.IRREVERSIBLE
            ext_effect = ExternalEffect.LOCAL_CHANGE
            confirmation_required = True
            risk_factors.append("Power or session action affects system state irreversibly")

        # --- EMAIL: separate read-only / draft-compose / outbound / destructive ---
        elif intent_up == "EMAIL":
            is_destructive = any(w in cmd_low for w in ["delete", "remove", "trash", "modify", "discard"])
            is_pending_send_confirm = any(k in cmd_low for k in ["send it", "send the mail", "send the email", "confirm send", "proceed with send", "send mail", "send this email", "send draft"]) and not any(k in cmd_low for k in ["delete", "remove", "trash"])
            is_direct_outbound = any(k in cmd_low for k in ["forward", "reply", "resend"])
            is_compose = any(w in cmd_low for w in ["compose", "draft", "write", "prepare", "new email", "create email"]) or ("send" in cmd_low and not is_direct_outbound and not is_pending_send_confirm)

            duplicate_risk = _check_existing_in_env(current_env, cmd_low, intent_up)

            if is_destructive:
                risk = RiskLevel.HIGH
                ext_effect = ExternalEffect.LOCAL_CHANGE
                reversibility = Reversibility.PARTIALLY_REVERSIBLE
                confirmation_required = True
                risk_factors.append("Destructive email operation is a protected action")
                risk_factors.append(RULE_EMAIL_PROTECTED)
            elif is_pending_send_confirm or is_compose:
                # Composing creates a draft; confirming a reviewed draft executes SMTP send as already authorized by the user
                risk = RiskLevel.MEDIUM
                ext_effect = ExternalEffect.LOCAL_CHANGE if is_compose else ExternalEffect.EXTERNAL_EFFECT
                reversibility = Reversibility.REVERSIBLE if is_compose else Reversibility.IRREVERSIBLE
                confirmation_required = False
                if duplicate_risk:
                    risk_factors.append("Duplicate side-effect risk: identical email already exists")
                risk_factors.append("Email composition / reviewed draft confirmation")
            elif is_direct_outbound:
                risk = RiskLevel.HIGH
                ext_effect = ExternalEffect.EXTERNAL_EFFECT
                reversibility = Reversibility.IRREVERSIBLE
                confirmation_required = True
                if duplicate_risk:
                    risk_factors.append("Duplicate side-effect risk: identical email dispatch in progress")
                risk_factors.append("Outbound email action is an irreversible external side-effect")
                risk_factors.append(RULE_EMAIL_PROTECTED)
            else:
                risk = RiskLevel.LOW
                ext_effect = ExternalEffect.READ_ONLY
                reversibility = Reversibility.REVERSIBLE
                confirmation_required = False

        # --- FILE_OPERATIONS: elevate for destructive ops ---
        elif intent_up == "FILE_OPERATIONS":
            is_delete = any(w in cmd_low for w in _CRITICAL_FILE_OPS)
            is_read   = any(w in cmd_low for w in _READONLY_FILE_OPS) and not is_delete

            if is_delete:
                risk = RiskLevel.CRITICAL
                reversibility = Reversibility.PARTIALLY_REVERSIBLE  # recycle bin = partially
                confirmation_required = True
                risk_factors.append("File/folder deletion — may be irreversible if recycle bin is bypassed")
                risk_factors.append(RULE_FILE_DELETE_PROTECTED)
            elif is_read:
                risk = RiskLevel.LOW
                ext_effect = ExternalEffect.READ_ONLY
                reversibility = Reversibility.REVERSIBLE
            else:
                # Create / write / move
                risk = RiskLevel.MEDIUM
                reversibility = Reversibility.PARTIALLY_REVERSIBLE
                overwrite_signals = ["overwrite", "replace", "clobber"]
                if any(w in cmd_low for w in overwrite_signals):
                    risk = RiskLevel.HIGH
                    confirmation_required = True
                    risk_factors.append("File overwrite is a potentially irreversible local change")

        # --- SMART_HOME: HIGH + EXTERNAL ---
        elif intent_up == "SMART_HOME":
            ext_effect = ExternalEffect.EXTERNAL_EFFECT
            reversibility = Reversibility.PARTIALLY_REVERSIBLE
            confirmation_required = True
            risk_factors.append("Smart home state change has external physical side-effects")
            risk_factors.append(RULE_SMART_HOME_CONFIRM)

        # --- REMINDERS / TASK_MANAGEMENT: duplicate risk if creating ---
        elif intent_up in ("REMINDERS", "TASK_MANAGEMENT"):
            if any(w in cmd_low for w in ["create", "add", "set", "schedule"]):
                duplicate_risk = _check_existing_in_env(current_env, cmd_low, intent_up)
                if duplicate_risk:
                    risk_factors.append("Duplicate side-effect risk: item may already exist")
            elif any(w in cmd_low for w in ["delete all", "remove all", "clear all", "purge", "cancel all"]):
                risk = RiskLevel.HIGH
                confirmation_required = True
                risk_factors.append("Deleting all reminders/tasks is an irreversible change")

        # --- DEVICE_CONTROL: MEDIUM, fully reversible ---
        elif intent_up == "DEVICE_CONTROL":
            reversibility = Reversibility.REVERSIBLE
            from core.confirmation_manager import get_confirmation_manager
            mgr = get_confirmation_manager()
            uid = int(user_id) if (user_id is not None and str(user_id).isdigit()) else 1
            has_sys_scope = mgr.has_scope(uid, "SYSTEM_CONTROL")

            mutating_ops = [
                "set resolution", "change resolution", "set display resolution", "change display resolution",
                "set wallpaper", "change wallpaper", "set my wallpaper", "change my wallpaper",
                "lock workstation", "lock pc", "lock computer", "lock screen"
            ]
            if any(op in cmd_low for op in mutating_ops) and not has_sys_scope:
                risk = RiskLevel.HIGH
                confirmation_required = True
                risk_factors.append("System control mutation requires user authorization (POL-018)")
                risk_factors.append("SYSTEM_CONTROL scope required")

        # --- DOCUMENT_GENERATION ---
        elif intent_up == "DOCUMENT_GENERATION":
            reversibility = Reversibility.PARTIALLY_REVERSIBLE
            # If a file already exists at the target path
            out_path = action_result.get("file_path") or action_result.get("path") or ""
            import os as _os
            if out_path and _os.path.exists(out_path) and _os.path.getsize(out_path) > 0:
                risk = RiskLevel.HIGH
                confirmation_required = True
                duplicate_risk = True
                risk_factors.append(f"Output file already exists at '{_redact_secrets(out_path)}' — overwrite would be irreversible")

        # --- Apply confirmation rules based on final risk level ---
        if risk == RiskLevel.CRITICAL and not confirmation_required:
            confirmation_required = True
            risk_factors.append("CRITICAL risk always requires confirmation")

        if risk == RiskLevel.HIGH and not confirmation_required:
            confirmation_required = True
            risk_factors.append("HIGH risk requires confirmation before execution")

        if reversibility == Reversibility.IRREVERSIBLE and not confirmation_required:
            confirmation_required = True
            risk_factors.append("Irreversible action requires confirmation (POL-014)")

        if ext_effect == ExternalEffect.EXTERNAL_EFFECT and not confirmation_required:
            confirmation_required = True
            risk_factors.append("External side-effect requires confirmation (POL-008)")

        rationale = self._build_rationale(intent_up, risk, reversibility, ext_effect, confirmation_required)

        return RiskAssessment(
            risk_level=risk,
            reversibility=reversibility,
            external_effect=ext_effect,
            duplicate_risk=duplicate_risk,
            user_scope_required=True,
            confirmation_required=confirmation_required,
            risk_factors=risk_factors,
            rationale=rationale,
        )

    @staticmethod
    def _build_rationale(
        intent: str,
        risk: RiskLevel,
        rev: Reversibility,
        ext: ExternalEffect,
        conf: bool,
    ) -> str:
        parts = [f"Intent={intent}", f"Risk={risk.value}", f"Reversibility={rev.value}", f"Effect={ext.value}"]
        if conf:
            parts.append("Confirmation=REQUIRED")
        else:
            parts.append("Confirmation=NOT_REQUIRED")
        return "; ".join(parts)


def _check_existing_in_env(env: Dict[str, Any], cmd_low: str, intent: str) -> bool:
    """Check if a similar item already exists in environment to detect duplicate risk."""
    try:
        if intent == "REMINDERS":
            existing = env.get("reminders") or env.get("active_reminders") or []
            if existing:
                cmd_words = set(cmd_low.split())
                for r in existing:
                    title = (r.get("title") or r.get("text") or "").lower()
                    if title and len(cmd_words & set(title.split())) >= 2:
                        return True
        elif intent == "TASK_MANAGEMENT":
            existing = env.get("tasks") or env.get("active_tasks") or []
            if existing:
                cmd_words = set(cmd_low.split())
                for t in existing:
                    title = (t.get("title") or t.get("name") or "").lower()
                    if title and len(cmd_words & set(title.split())) >= 2:
                        return True
        elif intent == "EMAIL":
            existing = env.get("sent_emails") or env.get("recent_sends") or env.get("in_flight_sends") or []
            if existing:
                for s in existing:
                    target = (s.get("recipient") or s.get("target") or "").lower()
                    subject = (s.get("subject") or "").lower()
                    if target and target in cmd_low and subject and subject in cmd_low:
                        return True
    except Exception:
        pass
    return False


# ============================================================================
# Policy Engine
# ============================================================================

class RiskPolicyEngine:
    """
    Canonical governance layer for action execution decisions.

    Evaluates whether a proposed action is:
        ALLOWED | ALLOWED_WITH_CONFIRMATION | BLOCKED | UNCERTAIN

    Safety hierarchy (highest wins):
        1. Authentication / identity
        2. Authorization / user scope
        3. Policy restrictions (CRITICAL block)
        4. Current environment safety (duplicate detection)
        5. Duplicate/side-effect protection
        6. Risk classification
        7. Confirmation requirements
        8. Strategy optimization (Phase 6 — cannot override policy)
        9. Historical experience (Phase 5 — cannot grant authorization)
        10. Default heuristic priority
    """

    def __init__(self) -> None:
        self._classifier = RiskClassifier()

    # ------------------------------------------------------------------
    # Primary Evaluation API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        intent: str,
        command: str,
        user_id: Optional[int] = None,
        action_result: Optional[Dict[str, Any]] = None,
        current_env: Optional[Dict[str, Any]] = None,
        experience_summary: Optional[Any] = None,   # Phase 5 — informational only
        is_recovery_action: bool = False,
        confirmed_by_user: bool = False,
        cancellation_check: Optional[Any] = None,
    ) -> PolicyEvaluation:
        """
        Evaluate governance decision for a proposed action.

        Args:
            intent:             Intent name (e.g. "EMAIL", "FILE_OPERATIONS")
            command:            Raw command string proposed for execution
            user_id:            Authenticated user identifier (None = unauthenticated)
            action_result:      Prior action result dict (for duplicate/overwrite detection)
            current_env:        Live environment snapshot dict
            experience_summary: Phase 5 ExperienceSummary — informational, NOT authorizing
            is_recovery_action: True if this is an adaptive recovery strategy execution
            confirmed_by_user:  True if user has already confirmed this specific action
            cancellation_check: Callable returning True if user cancelled

        Returns:
            PolicyEvaluation with decision, assessment, rules applied, rationale.
        """
        try:
            return self._evaluate_internal(
                intent=intent,
                command=command,
                user_id=user_id,
                action_result=action_result or {},
                current_env=current_env or {},
                experience_summary=experience_summary,
                is_recovery_action=is_recovery_action,
                confirmed_by_user=confirmed_by_user,
                cancellation_check=cancellation_check,
            )
        except Exception as err:
            # FAIL CLOSED for high-risk: engine failure must NOT silently permit execution
            import logging as _log
            _log.getLogger(__name__).error("RiskPolicyEngine.evaluate() failed: %s", err)
            assessment = RiskAssessment(
                risk_level=RiskLevel.HIGH,
                reversibility=Reversibility.UNKNOWN,
                external_effect=ExternalEffect.LOCAL_CHANGE,
                confirmation_required=True,
                risk_factors=["Policy evaluation failed — fail-closed (POL-013)"],
                rationale="Policy engine encountered an internal error. Failing closed for safety.",
            )
            return PolicyEvaluation(
                decision=PolicyDecision.UNCERTAIN,
                assessment=assessment,
                action_signature=_build_action_signature(intent, command),
                policy_rules_applied=[RULE_FAIL_CLOSED_HIGH],
                rationale="Policy engine error — action held for safety. Do not execute.",
                requires_confirmation=True,
                user_id=user_id,
            )

    def _evaluate_internal(
        self,
        intent: str,
        command: str,
        user_id: Optional[int],
        action_result: Dict[str, Any],
        current_env: Dict[str, Any],
        experience_summary: Optional[Any],
        is_recovery_action: bool,
        confirmed_by_user: bool,
        cancellation_check: Optional[Any],
    ) -> PolicyEvaluation:
        intent_up = intent.upper().strip()
        action_sig = _build_action_signature(intent_up, command)
        rules_applied: List[str] = []

        # ------------------------------------------------------------------
        # Gate 0: Cancellation check
        # ------------------------------------------------------------------
        if cancellation_check and cancellation_check():
            assessment = RiskAssessment(
                risk_level=RiskLevel.LOW,
                reversibility=Reversibility.REVERSIBLE,
                external_effect=ExternalEffect.READ_ONLY,
                rationale="Action cancelled by user before policy evaluation.",
            )
            return PolicyEvaluation(
                decision=PolicyDecision.BLOCKED,
                assessment=assessment,
                action_signature=action_sig,
                policy_rules_applied=["CANCEL"],
                rationale="User cancelled the action.",
                requires_confirmation=False,
                user_id=user_id,
            )

        # ------------------------------------------------------------------
        # Gate 1: User Identity Check (POL-010)
        # ------------------------------------------------------------------
        assessment = self._classifier.classify(intent_up, command, action_result, current_env, user_id)

        if assessment.user_scope_required and user_id is None:
            rules_applied.append(RULE_USER_ID_REQUIRED)
            return PolicyEvaluation(
                decision=PolicyDecision.BLOCKED,
                assessment=assessment,
                action_signature=action_sig,
                policy_rules_applied=rules_applied,
                rationale=f"Action '{intent_up}' requires an authenticated user identity. No user_id provided.",
                requires_confirmation=False,
                user_id=None,
            )

        # ------------------------------------------------------------------
        # Gate 2: CRITICAL actions — blocked unless confirmed + non-recovery
        # ------------------------------------------------------------------
        if assessment.risk_level == RiskLevel.CRITICAL:
            rules_applied.append(RULE_CRITICAL_BLOCKED)
            if not confirmed_by_user:
                conf_req = ConfirmationRequest(
                    action=intent_up,
                    target=_extract_target(command),
                    effect=f"{assessment.reversibility.value} action with {assessment.external_effect.value} effect",
                    risk_level=assessment.risk_level.value,
                    reason="; ".join(assessment.risk_factors) or "CRITICAL risk level",
                    rules_applied=[RULE_CRITICAL_BLOCKED],
                )
                return PolicyEvaluation(
                    decision=PolicyDecision.ALLOWED_WITH_CONFIRMATION,
                    assessment=assessment,
                    action_signature=action_sig,
                    policy_rules_applied=rules_applied,
                    rationale=f"CRITICAL risk action '{intent_up}' requires explicit user confirmation before execution.",
                    requires_confirmation=True,
                    confirmation_request=conf_req,
                    user_id=user_id,
                )
            else:
                rules_applied.append(RULE_CRITICAL_BLOCKED + ":CONFIRMED")

        # ------------------------------------------------------------------
        # Gate 3: Duplicate side-effect detection (POL-009)
        # ------------------------------------------------------------------
        if assessment.duplicate_risk:
            rules_applied.append(RULE_DUPLICATE_RISK_BLOCKED)
            return PolicyEvaluation(
                decision=PolicyDecision.BLOCKED,
                assessment=assessment,
                action_signature=action_sig,
                policy_rules_applied=rules_applied,
                rationale="Duplicate side-effect risk detected. Action would create a duplicate or re-send an already-executed effect.",
                requires_confirmation=False,
                user_id=user_id,
            )

        # ------------------------------------------------------------------
        # Gate 4: HIGH risk — confirmation required (POL-004)
        # ------------------------------------------------------------------
        if assessment.risk_level == RiskLevel.HIGH and assessment.confirmation_required:
            if not confirmed_by_user:
                rules_applied.append(RULE_HIGH_REQUIRES_CONFIRM)
                if assessment.external_effect == ExternalEffect.EXTERNAL_EFFECT:
                    rules_applied.append(RULE_EXTERNAL_EFFECT_CONFIRM)
                conf_req = ConfirmationRequest(
                    action=intent_up,
                    target=_extract_target(command),
                    effect=f"{assessment.reversibility.value} action with {assessment.external_effect.value} effect",
                    risk_level=assessment.risk_level.value,
                    reason="; ".join(assessment.risk_factors) or "HIGH risk level",
                    rules_applied=rules_applied[:],
                )
                return PolicyEvaluation(
                    decision=PolicyDecision.ALLOWED_WITH_CONFIRMATION,
                    assessment=assessment,
                    action_signature=action_sig,
                    policy_rules_applied=rules_applied,
                    rationale=f"HIGH risk action '{intent_up}' requires user confirmation.",
                    requires_confirmation=True,
                    confirmation_request=conf_req,
                    user_id=user_id,
                )
            else:
                rules_applied.append(RULE_HIGH_REQUIRES_CONFIRM + ":CONFIRMED")

        # ------------------------------------------------------------------
        # Gate 5: Irreversible actions — confirmation required (POL-014)
        # ------------------------------------------------------------------
        if assessment.reversibility == Reversibility.IRREVERSIBLE and not confirmed_by_user:
            rules_applied.append(RULE_IRREVERSIBLE_CONFIRM)
            conf_req = ConfirmationRequest(
                action=intent_up,
                target=_extract_target(command),
                effect="Irreversible action — cannot be undone after execution",
                risk_level=assessment.risk_level.value,
                reason="Irreversible actions always require explicit confirmation",
                rules_applied=[RULE_IRREVERSIBLE_CONFIRM],
            )
            return PolicyEvaluation(
                decision=PolicyDecision.ALLOWED_WITH_CONFIRMATION,
                assessment=assessment,
                action_signature=action_sig,
                policy_rules_applied=rules_applied,
                rationale=f"Irreversible action '{intent_up}' requires user confirmation before execution.",
                requires_confirmation=True,
                confirmation_request=conf_req,
                user_id=user_id,
            )

        # ------------------------------------------------------------------
        # Gate 6: External side effects — confirmation (POL-008)
        # ------------------------------------------------------------------
        if assessment.external_effect == ExternalEffect.EXTERNAL_EFFECT and not confirmed_by_user:
            rules_applied.append(RULE_EXTERNAL_EFFECT_CONFIRM)
            conf_req = ConfirmationRequest(
                action=intent_up,
                target=_extract_target(command),
                effect="External side-effect that cannot be recalled after execution",
                risk_level=assessment.risk_level.value,
                reason="Actions with external side-effects require confirmation",
                rules_applied=[RULE_EXTERNAL_EFFECT_CONFIRM],
            )
            return PolicyEvaluation(
                decision=PolicyDecision.ALLOWED_WITH_CONFIRMATION,
                assessment=assessment,
                action_signature=action_sig,
                policy_rules_applied=rules_applied,
                rationale=f"External side-effect action '{intent_up}' requires confirmation.",
                requires_confirmation=True,
                confirmation_request=conf_req,
                user_id=user_id,
            )

        # ------------------------------------------------------------------
        # Gate 7: LOW / MEDIUM — ALLOWED (POL-001, POL-002, POL-003)
        # ------------------------------------------------------------------
        if assessment.external_effect == ExternalEffect.READ_ONLY:
            rules_applied.append(RULE_READ_ONLY_ALLOWED)
            rationale = f"Read-only action '{intent_up}' is permitted without restriction."
        elif assessment.risk_level == RiskLevel.LOW:
            rules_applied.append(RULE_LOW_RISK_ALLOWED)
            rationale = f"Low-risk reversible action '{intent_up}' is permitted."
        else:
            rules_applied.append(RULE_MEDIUM_REVERSIBLE_OK)
            rationale = f"Medium-risk reversible local action '{intent_up}' is permitted for authenticated user {user_id}."

        return PolicyEvaluation(
            decision=PolicyDecision.ALLOWED,
            assessment=assessment,
            action_signature=action_sig,
            policy_rules_applied=rules_applied,
            rationale=rationale,
            requires_confirmation=False,
            user_id=user_id,
        )

    # ------------------------------------------------------------------
    # Strategy Filter API (for StrategyOptimizer / AdaptiveRecovery integration)
    # ------------------------------------------------------------------

    def filter_strategies(
        self,
        candidate_strategies: List[Any],  # List[AdaptiveStrategy]
        intent: str,
        user_id: Optional[int],
        current_env: Optional[Dict[str, Any]] = None,
        confirmed_by_user: bool = False,
    ) -> "StrategyFilterResult":
        """
        Evaluates each candidate strategy through the policy engine.
        Returns the set of executable strategies, blocked strategies, and
        strategies requiring confirmation.

        Phase 6 StrategyOptimizer ranking is preserved for ordering WITHIN
        each tier — but POLICY decides which tier a strategy belongs to.
        """
        allowed:          List[Any] = []
        needs_confirm:    List[Any] = []
        blocked:          List[Any] = []
        evaluations:      Dict[str, PolicyEvaluation] = {}

        for strat in candidate_strategies:
            strat_cmd = getattr(strat, "recovery_command", "") or getattr(strat, "strategy_id", "")
            strat_intent = getattr(strat, "intent", intent)
            strat_id = getattr(strat, "strategy_id", "UNKNOWN")

            ev = self.evaluate(
                intent=strat_intent,
                command=strat_cmd,
                user_id=user_id,
                current_env=current_env,
                confirmed_by_user=confirmed_by_user,
            )
            evaluations[strat_id] = ev

            if ev.decision == PolicyDecision.ALLOWED:
                allowed.append(strat)
            elif ev.decision in (PolicyDecision.ALLOWED_WITH_CONFIRMATION, PolicyDecision.UNCERTAIN):
                needs_confirm.append(strat)
            else:  # BLOCKED
                blocked.append(strat)

        return StrategyFilterResult(
            allowed=allowed,
            needs_confirmation=needs_confirm,
            blocked=blocked,
            evaluations=evaluations,
        )


@dataclass
class StrategyFilterResult:
    """Result of filtering candidate strategies through the policy engine."""
    allowed:          List[Any]                       # Strategies cleared for immediate execution
    needs_confirmation: List[Any]                     # Strategies that require confirmation
    blocked:          List[Any]                       # Strategies that must not execute
    evaluations:      Dict[str, PolicyEvaluation]     # Full audit trail per strategy_id

    @property
    def best_allowed(self) -> Optional[Any]:
        """Returns the first allowed strategy (highest-scoring per Phase 6 ordering)."""
        return self.allowed[0] if self.allowed else None

    @property
    def has_any_executable(self) -> bool:
        return bool(self.allowed)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed_count":           len(self.allowed),
            "needs_confirmation_count": len(self.needs_confirmation),
            "blocked_count":           len(self.blocked),
            "evaluations":             {k: v.to_dict() for k, v in self.evaluations.items()},
        }


# ============================================================================
# Helpers
# ============================================================================

def _build_action_signature(intent: str, command: str) -> str:
    """Generate a canonical action signature for audit records."""
    cmd_preview = _redact_secrets(command[:80]) if command else ""
    return f"{intent.upper()}:{cmd_preview}"


def _extract_target(command: str) -> str:
    """
    Heuristically extract the likely target of the action for confirmation prompts.
    Never logs full paths/credentials — uses _redact_secrets.
    """
    cmd_safe = _redact_secrets(command)
    # Try to extract file path
    m = re.search(r'([a-zA-Z]:[\\\/][^\s"\']{0,120}|\/[^\s"\']{0,120}|[\w\-\.]+\.\w{2,5})', cmd_safe)
    if m:
        return m.group(1)[:100]
    # Try to extract quoted string
    m = re.search(r'["\']([^"\']{1,80})["\']', cmd_safe)
    if m:
        return m.group(1)
    # Return first meaningful word after verb
    parts = cmd_safe.split()
    if len(parts) >= 2:
        return parts[-1][:60]
    return cmd_safe[:60]


# ============================================================================
# Singleton
# ============================================================================

_policy_engine: Optional[RiskPolicyEngine] = None

def get_risk_policy_engine() -> RiskPolicyEngine:
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = RiskPolicyEngine()
    return _policy_engine
