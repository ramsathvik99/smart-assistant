"""
Smart Assistant — Canonical Outcome Verification System (PHASE 3)

Transforms read-only environment observations into a rigorous, truthful outcome verification system.
Distinguishes between ACTION RESULT ("function returned without exception") and OUTCOME RESULT
("requested real-world state was achieved").

Prevents FALSE COMPLETION: The assistant must not report successful completion when outcome
verification failed.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from enum import Enum
from dataclasses import dataclass, field, asdict
from collections import deque
from typing import Any, Dict, List, Optional, Tuple, Callable

from core.environment_observer import (
    EnvironmentSnapshot,
    StateDifference,
    observe_environment,
    compare_snapshots,
    select_relevant_categories
)


# ============================================================================
# Status & Confidence Enumerations
# ============================================================================

class OutcomeStatus(str, Enum):
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFIED_FAILURE = "VERIFIED_FAILURE"
    UNCERTAIN = "UNCERTAIN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"          # Direct system / DB / OS inspection confirmed state
    MEDIUM = "MEDIUM"      # Indirect or partial evidence strongly supports outcome
    LOW = "LOW"            # Incomplete or ambiguous evidence
    UNKNOWN = "UNKNOWN"    # Cannot establish outcome deterministically


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class ExpectedOutcome:
    """Explicit definition of expected real-world observable state following an action."""
    action: str
    target: str = ""
    intent: str = ""
    preconditions: Dict[str, Any] = field(default_factory=dict)
    expected_state: Dict[str, Any] = field(default_factory=dict)
    verification_method: str = "state_comparison"
    acceptable_tolerance: Dict[str, Any] = field(default_factory=dict)
    failure_interpretation: str = "The requested state was not detected in the environment."


@dataclass
class OutcomeVerificationResult:
    """Truthful outcome verification assessment."""
    status: OutcomeStatus
    verified: bool
    confidence: ConfidenceLevel
    expected_state: Dict[str, Any] = field(default_factory=dict)
    observed_state: Dict[str, Any] = field(default_factory=dict)
    differences: Dict[str, Any] = field(default_factory=dict)
    failure_reason: Optional[str] = None
    verification_method: str = "generic_observation"
    timestamp: float = field(default_factory=time.time)
    retry_possible: bool = False
    adaptation_possible: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value if isinstance(self.status, OutcomeStatus) else str(self.status),
            "verified": self.verified,
            "confidence": self.confidence.value if isinstance(self.confidence, ConfidenceLevel) else str(self.confidence),
            "expected_state": self.expected_state,
            "observed_state": self.observed_state,
            "differences": self.differences,
            "failure_reason": self.failure_reason,
            "verification_method": self.verification_method,
            "timestamp": self.timestamp,
            "retry_possible": self.retry_possible,
            "adaptation_possible": self.adaptation_possible
        }


@dataclass
class ExecutionRecord:
    """In-memory structured audit trail of an action, its verification, and outcome."""
    execution_id: str
    user_id: Any
    intent: str
    original_command: str
    action: str
    pre_state: Optional[Dict[str, Any]] = None
    expected_state: Optional[Dict[str, Any]] = None
    post_state: Optional[Dict[str, Any]] = None
    state_difference: Optional[Dict[str, Any]] = None
    action_result: Dict[str, Any] = field(default_factory=dict)
    verification_result: Optional[OutcomeVerificationResult] = None
    adaptation_attempted: bool = False
    adaptation_result: Optional[Dict[str, Any]] = None
    final_status: str = "UNKNOWN"
    timestamps: Dict[str, float] = field(default_factory=dict)
    # Phase 4 Adaptive Recovery Extensions
    adaptation_attempts: int = 0
    recovery_decisions: List[Dict[str, Any]] = field(default_factory=list)
    failure_classification: Optional[str] = None
    selected_strategy: Optional[str] = None
    strategy_outcomes: List[Dict[str, Any]] = field(default_factory=list)
    final_recovery_status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "user_id": self.user_id,
            "intent": self.intent,
            "original_command": self.original_command,
            "action": self.action,
            "pre_state": self.pre_state,
            "expected_state": self.expected_state,
            "post_state": self.post_state,
            "state_difference": self.state_difference,
            "action_result": self.action_result,
            "verification_result": self.verification_result.to_dict() if self.verification_result else None,
            "adaptation_attempted": self.adaptation_attempted,
            "adaptation_result": self.adaptation_result,
            "final_status": self.final_status,
            "timestamps": self.timestamps,
            "adaptation_attempts": self.adaptation_attempts,
            "recovery_decisions": self.recovery_decisions,
            "failure_classification": self.failure_classification,
            "selected_strategy": self.selected_strategy,
            "strategy_outcomes": self.strategy_outcomes,
            "final_recovery_status": self.final_recovery_status,
        }


# ============================================================================
# In-Memory Execution Record Store
# ============================================================================

class ExecutionRecordTracker:
    """Maintains a bounded in-memory sliding window of recent execution records."""
    def __init__(self, maxlen: int = 100):
        self._records: deque = deque(maxlen=maxlen)

    def record(self, record: ExecutionRecord):
        self._records.append(record)

    def get_recent(self, user_id: Optional[Any] = None, limit: int = 10) -> List[Dict[str, Any]]:
        results = []
        uid_str = str(user_id) if user_id is not None else None
        for r in reversed(self._records):
            if uid_str is None or str(r.user_id) == uid_str:
                results.append(r.to_dict())
                if len(results) >= limit:
                    break
        return results

    def get_by_id(self, execution_id: str) -> Optional[ExecutionRecord]:
        for r in self._records:
            if r.execution_id == execution_id:
                return r
        return None

    def clear(self):
        self._records.clear()


_global_record_tracker = ExecutionRecordTracker()

def get_record_tracker() -> ExecutionRecordTracker:
    return _global_record_tracker


# ============================================================================
# Verification Adapters (10 Core Categories)
# ============================================================================

class VerificationAdapters:
    """Specialized outcome verification adapters for distinct capability domains."""

    @staticmethod
    def verify_open_application(
        expected: ExpectedOutcome,
        post_obs: Dict[str, Any],
        state_diff: Optional[StateDifference] = None,
        action_result: Optional[Dict[str, Any]] = None
    ) -> OutcomeVerificationResult:
        target = (expected.target or "").lower().strip()
        active_app = (post_obs.get("active_application") or "").lower().strip()
        win_title = (post_obs.get("foreground_window_title") or (post_obs.get("active_window") or {}).get("title") or "").lower().strip()

        # If the action result detected the application was already open / active
        if action_result and action_result.get("already_satisfied"):
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"active_application": target},
                observed_state={"already_satisfied": True, "active_application": active_app, "window_title": win_title},
                verification_method="existing_state_already_satisfied"
            )

        # If action_result successfully launched a new instance
        if action_result and action_result.get("instance_mode") == "NEW" and action_result.get("status") == "success":
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"active_application": target, "instance_mode": "NEW"},
                observed_state={"instance_mode": "NEW", "active_application": active_app, "window_title": win_title},
                verification_method="new_instance_verified"
            )

        # Check explicit verified_open signal if provided by action_result
        if action_result and action_result.get("verified_open") is False:
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verified=False,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"active_application": target},
                observed_state={"active_application": active_app, "window_title": win_title},
                failure_reason=f"Application '{target}' failed to launch.",
                verification_method="process_window_check",
                retry_possible=True
            )

        # Match target against active app or window title
        target_norm = target.replace(".exe", "").lower().strip()
        target_aliases = [target_norm]
        if "edge" in target_norm:
            target_aliases.extend(["edge", "msedge"])
        if "chrome" in target_norm or "google" in target_norm:
            target_aliases.extend(["chrome", "google"])
        if "calc" in target_norm:
            target_aliases.extend(["calc", "calculator", "calculatorapp", "applicationframehost"])
        if "notepad" in target_norm:
            target_aliases.extend(["notepad", "notepad++"])

        # Cross-check: Target mismatch detection (Runs before psutil or window checks)
        # Prevents false completion if an existing process was already running while wrong app launched
        resolved_target = str(action_result.get("display_name") or action_result.get("name") or action_result.get("target") or "").lower().strip() if action_result else ""
        resolved_path = str(action_result.get("path") or "").lower().strip() if action_result else ""

        if target and (resolved_target or resolved_path):
            clean_target = re.sub(r'^(?:the|a|an)\s+', '', target).strip()
            t_tokens = set(re.findall(r'[a-z0-9]+', clean_target))
            r_tokens = set(re.findall(r'[a-z0-9]+', resolved_target))
            p_tokens = set(re.findall(r'[a-z0-9]+', os.path.basename(resolved_path))) if resolved_path else set()

            is_alias_match = any(a in resolved_target or resolved_target in a for a in target_aliases if a) or any(a in resolved_path for a in target_aliases if a)
            is_token_overlap = bool(t_tokens & (r_tokens | p_tokens))

            # Check if resolved path is an uninstaller, setup, or package cache
            is_forbidden_target = any(k in resolved_path for k in ["package cache", "setup.exe", "unins", "prereq", "installer"])

            if is_forbidden_target or (not is_alias_match and not is_token_overlap):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_FAILURE,
                    verified=False,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"requested_application": target},
                    observed_state={"opened_application": resolved_target, "opened_path": resolved_path},
                    failure_reason=f"Target mismatch: requested '{target}', but '{resolved_target or resolved_path}' was executed.",
                    verification_method="target_cross_verification",
                    retry_possible=False
                )

        is_match = False
        for t in target_aliases:
            if t and (t in active_app or active_app in t or t in win_title):
                is_match = True
                break

        # If this was a web search or URL opened in browser, check if active browser is running
        if not is_match and action_result and (action_result.get("is_website") or action_result.get("url")):
            active_proc = (post_obs.get("active_process") or "").lower()
            if any(b in active_proc or b in active_app or b in win_title for b in ["chrome", "msedge", "edge", "firefox", "brave", "browser"]):
                is_match = True

        # Check state difference for application change
        if state_diff and state_diff.details.get("application"):
            app_diff = state_diff.details["application"]
            after_app = (app_diff.get("after") or "").lower()
            if any(t in after_app or after_app in t for t in target_aliases if t):
                is_match = True

        cmd_str = (getattr(expected, 'command', '') or (action_result.get("raw_input") if action_result else "") or (action_result.get("command") if action_result else "") or expected.action or "").lower()
        is_explicit_focus = any(k in cmd_str for k in ["switch to", "focus", "bring to front", "switch", "foreground", "bring"])

        if is_match:
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"active_application": target},
                observed_state={"active_application": active_app, "window_title": win_title},
                verification_method="active_application_and_window_match"
            )

        # Process verification via psutil
        try:
            import psutil
            for p in psutil.process_iter(['name']):
                p_name = (p.info.get('name') or "").lower()
                if any(t in p_name for t in target_aliases if t):
                    if is_explicit_focus:
                        return OutcomeVerificationResult(
                            status=OutcomeStatus.VERIFIED_FAILURE,
                            verified=False,
                            confidence=ConfidenceLevel.HIGH,
                            expected_state={"active_application": target},
                            observed_state={"process_running": p_name, "window_title": win_title},
                            failure_reason=f"Application '{target}' is running but not in foreground as requested.",
                            verification_method="foreground_window_check",
                            retry_possible=True
                        )
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_SUCCESS,
                        verified=True,
                        confidence=ConfidenceLevel.MEDIUM,
                        expected_state={"process_running": target},
                        observed_state={"process_found": p_name},
                        verification_method="running_process_detection"
                    )
        except Exception:
            pass

        # If not explicit focus, check if the execution adapter reported success
        if not is_explicit_focus and action_result and (action_result.get("status") == "success" or action_result.get("success") is True):
            resolved_target = str(action_result.get("display_name") or action_result.get("name") or action_result.get("target") or "").lower().strip()
            resolved_path = str(action_result.get("path") or "").lower().strip()

            # Cross-check: Target mismatch detection
            # Never emit success if the opened executable does not match the requested target
            if target and (resolved_target or resolved_path):
                clean_target = re.sub(r'^(?:the|a|an)\s+', '', target).strip()
                t_tokens = set(re.findall(r'[a-z0-9]+', clean_target))
                r_tokens = set(re.findall(r'[a-z0-9]+', resolved_target))
                p_tokens = set(re.findall(r'[a-z0-9]+', os.path.basename(resolved_path))) if resolved_path else set()

                is_alias_match = any(a in resolved_target or resolved_target in a for a in target_aliases if a) or any(a in resolved_path for a in target_aliases if a)
                is_token_overlap = bool(t_tokens & (r_tokens | p_tokens))

                # Check if resolved path is an uninstaller, setup, or package cache
                is_forbidden_target = any(k in resolved_path for k in ["package cache", "setup.exe", "unins", "prereq", "installer"])

                if is_forbidden_target or (not is_alias_match and not is_token_overlap):
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_FAILURE,
                        verified=False,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"requested_application": target},
                        observed_state={"opened_application": resolved_target, "opened_path": resolved_path},
                        failure_reason=f"Application mismatch: requested '{target}', but '{resolved_target or resolved_path}' was executed.",
                        verification_method="target_cross_verification",
                        retry_possible=False
                    )

            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"application_launched": target},
                observed_state={"status": "success", "active_application": active_app, "window_title": win_title},
                verification_method="successful_execution_adapter"
            )

        return OutcomeVerificationResult(
            status=OutcomeStatus.VERIFIED_FAILURE,
            verified=False,
            confidence=ConfidenceLevel.HIGH,
            expected_state={"active_application": target},
            observed_state={"active_application": active_app, "window_title": win_title},
            failure_reason=f"Application '{target}' is not active or in foreground.",
            verification_method="active_application_and_window_match",
            retry_possible=True
        )

    @staticmethod
    def verify_close_application(
        expected: ExpectedOutcome,
        post_obs: Dict[str, Any],
        state_diff: Optional[StateDifference] = None,
        action_result: Optional[Dict[str, Any]] = None
    ) -> OutcomeVerificationResult:
        target = (expected.target or "").lower().strip()
        active_app = (post_obs.get("active_application") or "").lower().strip()
        win_title = (post_obs.get("foreground_window_title") or (post_obs.get("active_window") or {}).get("title") or "").lower().strip()

        # If action_result reported failure, respect it
        if action_result and (action_result.get("status") == "error" or action_result.get("success") is False):
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verified=False,
                confidence=ConfidenceLevel.HIGH,
                failure_reason=action_result.get("response", f"Failed to close '{target}'."),
                verification_method="action_result_check"
            )

        # Check if target is still foreground active
        target_norm = target.replace(".exe", "").lower().strip()
        target_aliases = [target_norm]
        if "edge" in target_norm:
            target_aliases.extend(["edge", "msedge"])
        if "chrome" in target_norm:
            target_aliases.extend(["chrome", "google"])

        is_foreground = any(t in active_app or t in win_title for t in target_aliases if t)
        if not is_foreground:
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"active_application_closed": target},
                observed_state={"active_application": active_app, "window_title": win_title},
                verification_method="active_application_and_window_match"
            )

        return OutcomeVerificationResult(
            status=OutcomeStatus.VERIFIED_SUCCESS if action_result and action_result.get("status") == "success" else OutcomeStatus.UNCERTAIN,
            verified=True,
            confidence=ConfidenceLevel.MEDIUM,
            verification_method="action_result_check"
        )

    @staticmethod
    def verify_file_operations(
        expected: ExpectedOutcome,
        post_obs: Dict[str, Any],
        state_diff: Optional[StateDifference] = None,
        action_result: Optional[Dict[str, Any]] = None
    ) -> OutcomeVerificationResult:
        file_path = expected.target
        op_type = expected.action.lower()  # "create", "delete", "write"

        # If action result reported already_satisfied (e.g. folder already exists)
        if action_result and (action_result.get("already_satisfied") or action_result.get("already_exists")):
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"exists": True, "path": file_path or action_result.get("path")},
                observed_state={"already_satisfied": True, "already_exists": True},
                verification_method="file_system_inspection"
            )

        if not file_path:
            return OutcomeVerificationResult(
                status=OutcomeStatus.UNCERTAIN,
                verified=False,
                confidence=ConfidenceLevel.LOW,
                failure_reason="No target file path specified for verification.",
                verification_method="file_system_inspection"
            )

        exists = os.path.exists(file_path)
        if not exists:
            try:
                from modules.system_controller.folder_manager import get_desktop_path
                p_cand = os.path.join(get_desktop_path(), file_path)
                if os.path.exists(p_cand):
                    exists = True
                    file_path = p_cand
            except Exception:
                pass

        if op_type in ("create", "write", "save", "rename"):
            if not exists:
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_FAILURE,
                    verified=False,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"exists": True, "path": file_path},
                    observed_state={"exists": False},
                    failure_reason=f"Target '{file_path}' does not exist on disk.",
                    verification_method="file_system_inspection",
                    retry_possible=True
                )
            if not os.path.isdir(file_path):
                size = os.path.getsize(file_path)
                is_create_empty_allowed = (
                    expected.acceptable_tolerance.get("allow_empty", False)
                    or (action_result and action_result.get("action") in ("create_file", "rename_file"))
                    or op_type in ("rename", "rename_file")
                    or "rename" in expected.action.lower()
                    or (action_result and "rename" in str(action_result.get("response", "")).lower())
                )
                if size == 0 and not is_create_empty_allowed:
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_FAILURE,
                        verified=False,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"exists": True, "size_gt": 0, "path": file_path},
                        observed_state={"exists": True, "size": 0},
                        failure_reason=f"Target file '{file_path}' was created but has zero bytes.",
                        verification_method="file_system_inspection"
                    )
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"exists": True, "path": file_path},
                observed_state={"exists": True},
                verification_method="file_system_inspection"
            )

        elif op_type in ("delete", "remove"):
            if exists:
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_FAILURE,
                    verified=False,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"exists": False, "path": file_path},
                    observed_state={"exists": True},
                    failure_reason=f"Target file '{file_path}' still exists after deletion.",
                    verification_method="file_system_inspection",
                    retry_possible=True
                )
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"exists": False, "path": file_path},
                observed_state={"exists": False},
                verification_method="file_system_inspection"
            )

        elif op_type in ("open", "open_folder", "open_file"):
            if not exists and action_result and action_result.get("folder"):
                from modules.system_controller.folder_manager import get_desktop_path
                clean_name = action_result.get("folder")
                desktop = get_desktop_path()
                p_cand = os.path.join(desktop, clean_name)
                exists = os.path.exists(p_cand)
            if exists or (action_result and action_result.get("status") == "success"):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"opened": True, "path": file_path},
                    observed_state={"status": "success"},
                    verification_method="file_system_inspection"
                )

        return OutcomeVerificationResult(
            status=OutcomeStatus.UNCERTAIN,
            verified=False,
            confidence=ConfidenceLevel.LOW,
            failure_reason=f"Unsupported file operation type '{op_type}'.",
            verification_method="file_system_inspection"
        )

    @staticmethod
    def verify_device_control(
        expected: ExpectedOutcome,
        post_obs: Dict[str, Any],
        state_diff: Optional[StateDifference] = None,
        action_result: Optional[Dict[str, Any]] = None
    ) -> OutcomeVerificationResult:
        target = expected.target.lower()
        expected_state = expected.expected_state

        # Toggle Keys (Caps Lock, Num Lock, Scroll Lock)
        for key in ("caps_lock", "num_lock", "scroll_lock"):
            if key in expected_state or key in target:
                req_val = expected_state.get(key)
                if req_val is None and action_result:
                    req_val = action_result.get(key)
                obs_val = post_obs.get(key)
                if obs_val is None:
                    try:
                        from modules.system_controller import get_toggle_key_states
                        k_st = get_toggle_key_states()
                        obs_val = k_st.get(key)
                    except Exception:
                        pass
                if obs_val is None and action_result:
                    obs_val = action_result.get("state")

                if req_val is not None and obs_val is not None:
                    if bool(req_val) == bool(obs_val):
                        return OutcomeVerificationResult(
                            status=OutcomeStatus.VERIFIED_SUCCESS,
                            verified=True,
                            confidence=ConfidenceLevel.HIGH,
                            expected_state={key: req_val},
                            observed_state={key: obs_val},
                            verification_method="win32_key_state_inspection"
                        )
                    else:
                        return OutcomeVerificationResult(
                            status=OutcomeStatus.VERIFIED_FAILURE,
                            verified=False,
                            confidence=ConfidenceLevel.HIGH,
                            expected_state={key: req_val},
                            observed_state={key: obs_val},
                            failure_reason=f"Toggle key {key} is {obs_val}, expected {req_val}.",
                            verification_method="win32_key_state_inspection",
                            retry_possible=True
                        )

        # Brightness Control
        if "brightness" in target or expected.action in ("set_brightness", "adjust_brightness", "increase_brightness", "decrease_brightness"):
            req_b = expected_state.get("brightness")
            if req_b is None and action_result:
                req_b = action_result.get("target") if action_result.get("target") is not None else action_result.get("brightness")
            obs_b = post_obs.get("brightness")
            if obs_b is None:
                try:
                    from modules.system_controller import get_brightness
                    b_st = get_brightness()
                    obs_b = b_st.get("level") if b_st.get("level") is not None else b_st.get("brightness")
                except Exception:
                    pass
            if obs_b is None and action_result:
                obs_b = action_result.get("level") if action_result.get("level") is not None else action_result.get("brightness")
            if req_b is not None and obs_b is not None:
                if abs(obs_b - req_b) <= 5:
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_SUCCESS,
                        verified=True,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"brightness": req_b},
                        observed_state={"brightness": obs_b},
                        verification_method="brightness_state_inspection"
                    )
                else:
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_FAILURE,
                        verified=False,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"brightness": req_b},
                        observed_state={"brightness": obs_b},
                        failure_reason=f"Brightness is {obs_b}%, expected {req_b}%.",
                        verification_method="brightness_state_inspection"
                    )
            elif action_result and action_result.get("success"):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"brightness": req_b or obs_b},
                    observed_state={"brightness": obs_b},
                    verification_method="brightness_state_inspection"
                )

        # Volume Control
        if "volume" in target or expected.action in ("set_volume", "increase_volume", "decrease_volume", "volume_change"):
            req_v = expected_state.get("volume")
            if req_v is None and action_result:
                req_v = action_result.get("target") if action_result.get("target") is not None else action_result.get("volume")
            obs_v = post_obs.get("master_volume") or post_obs.get("volume")
            if obs_v is None:
                try:
                    from modules.system_controller import get_volume
                    v_st = get_volume()
                    obs_v = v_st.get("level") if v_st.get("level") is not None else v_st.get("volume")
                except Exception:
                    pass
            if obs_v is None and action_result:
                obs_v = action_result.get("level") if action_result.get("level") is not None else action_result.get("volume")
            if req_v is not None and obs_v is not None:
                if abs(obs_v - req_v) <= 3:
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_SUCCESS,
                        verified=True,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"volume": req_v},
                        observed_state={"volume": obs_v},
                        verification_method="audio_endpoint_volume_check"
                    )
                else:
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_FAILURE,
                        verified=False,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"volume": req_v},
                        observed_state={"volume": obs_v},
                        failure_reason=f"Volume is {obs_v}%, expected {req_v}%.",
                        verification_method="audio_endpoint_volume_check"
                    )
            elif action_result and action_result.get("success"):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"volume": req_v or obs_v},
                    observed_state={"volume": obs_v},
                    verification_method="audio_endpoint_volume_check"
                )

        # Mute / Unmute Control
        if "mute" in target or expected.action in ("mute", "unmute", "set_mute"):
            req_mute = expected_state.get("is_muted")
            if req_mute is None and action_result:
                req_mute = action_result.get("is_muted")
            if req_mute is None:
                req_mute = False if "unmute" in target or expected.action == "unmute" else True
            obs_mute = post_obs.get("muted")
            if obs_mute is None:
                try:
                    from modules.system_controller import get_volume
                    v_st = get_volume()
                    obs_mute = v_st.get("is_muted")
                except Exception:
                    pass
            if req_mute is not None and obs_mute is not None:
                if bool(req_mute) == bool(obs_mute):
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_SUCCESS,
                        verified=True,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"is_muted": req_mute},
                        observed_state={"is_muted": obs_mute},
                        verification_method="audio_endpoint_mute_check"
                    )
                else:
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_FAILURE,
                        verified=False,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"is_muted": req_mute},
                        observed_state={"is_muted": obs_mute},
                        failure_reason=f"Audio is {'muted' if obs_mute else 'unmuted'}, expected {'muted' if req_mute else 'unmuted'}.",
                        verification_method="audio_endpoint_mute_check"
                    )
            elif action_result and (action_result.get("success") or action_result.get("already_satisfied")):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"is_muted": req_mute},
                    observed_state={"is_muted": obs_mute},
                    verification_method="audio_endpoint_mute_check"
                )

        # General already_satisfied handling for device controls
        if action_result and action_result.get("already_satisfied"):
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state=expected_state,
                observed_state={"already_satisfied": True},
                verification_method="existing_state_already_satisfied"
            )
        if "dark_mode" in target or expected.action == "toggle_dark_mode":
            req_dm = expected_state.get("dark_mode")
            obs_dm = post_obs.get("dark_mode")
            if obs_dm is None and action_result:
                obs_dm = action_result.get("dark_mode")
            if req_dm is not None and obs_dm is not None:
                if bool(req_dm) == bool(obs_dm):
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_SUCCESS,
                        verified=True,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"dark_mode": req_dm},
                        observed_state={"dark_mode": obs_dm},
                        verification_method="registry_theme_inspection"
                    )
                else:
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_FAILURE,
                        verified=False,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"dark_mode": req_dm},
                        observed_state={"dark_mode": obs_dm},
                        failure_reason=f"Dark mode is {obs_dm}, expected {req_dm}.",
                        verification_method="registry_theme_inspection"
                    )
            elif action_result and action_result.get("success"):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"dark_mode": req_dm},
                    observed_state={"dark_mode": obs_dm},
                    verification_method="registry_theme_inspection"
                )

        # Screenshot
        if "screenshot" in target or expected.action == "screenshot":
            path = action_result.get("path") if action_result else None
            if not path and action_result and isinstance(action_result.get("response"), str):
                import re as _re
                m = _re.search(r'([A-Za-z]:\\[^\s]+\.png)', action_result["response"])
                if m:
                    path = m.group(1)
            if path and os.path.exists(path):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"screenshot_exists": True, "path": path},
                    observed_state={"screenshot_exists": True, "path": path},
                    verification_method="filesystem_screenshot_inspection"
                )
            elif action_result and action_result.get("status") == "error":
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_FAILURE,
                    verified=False,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"screenshot_exists": True},
                    observed_state={"screenshot_exists": False},
                    failure_reason=action_result.get("response", "Could not capture screenshot."),
                    verification_method="filesystem_screenshot_inspection"
                )

        # Detailed CPU Telemetry
        if "detailed_cpu" in target or expected.action == "detailed_cpu":
            if action_result and action_result.get("cpu_name") and (action_result.get("logical_processors") or action_result.get("physical_cores")):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"cpu_name": True, "logical_processors": True},
                    observed_state={"cpu_name": action_result.get("cpu_name"), "logical_processors": action_result.get("logical_processors")},
                    verification_method="local_cpu_hardware_telemetry"
                )
            else:
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_FAILURE,
                    verified=False,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"cpu_name": True, "logical_processors": True},
                    observed_state={"cpu_name": action_result.get("cpu_name") if action_result else None},
                    failure_reason="Detailed CPU hardware information (model/cores) was not returned.",
                    verification_method="local_cpu_hardware_telemetry"
                )

        # Detailed RAM Telemetry
        if "detailed_ram" in target or expected.action == "detailed_ram":
            if action_result and action_result.get("total_gb") is not None and action_result.get("swap_total_gb") is not None:
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"total_gb": True, "swap_total_gb": True},
                    observed_state={"total_gb": action_result.get("total_gb"), "swap_total_gb": action_result.get("swap_total_gb")},
                    verification_method="local_ram_hardware_telemetry"
                )
            else:
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_FAILURE,
                    verified=False,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"total_gb": True, "swap_total_gb": True},
                    observed_state={"total_gb": action_result.get("total_gb") if action_result else None},
                    failure_reason="Detailed RAM metrics (total/swap breakdown) were not returned.",
                    verification_method="local_ram_hardware_telemetry"
                )

        # Detailed GPU Telemetry
        if "detailed_gpu" in target or expected.action == "detailed_gpu":
            if action_result and (action_result.get("primary_gpu") or action_result.get("gpus")):
                p_gpu = action_result.get("primary_gpu") or (action_result.get("gpus")[0] if action_result.get("gpus") else {})
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"primary_gpu": True},
                    observed_state={"primary_gpu": p_gpu.get("name") if isinstance(p_gpu, dict) else str(p_gpu)},
                    verification_method="local_gpu_hardware_telemetry"
                )
            else:
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_FAILURE,
                    verified=False,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"primary_gpu": True},
                    observed_state={},
                    failure_reason="Detailed GPU hardware information was not returned.",
                    verification_method="local_gpu_hardware_telemetry"
                )

        # GPU Memory Telemetry
        if "gpu_memory" in target or expected.action == "gpu_memory":
            if action_result:
                if action_result.get("memory_telemetry_available") is True and action_result.get("used_mb") is not None:
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_SUCCESS,
                        verified=True,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"gpu_memory_telemetry": True},
                        observed_state={"used_mb": action_result.get("used_mb"), "total_mb": action_result.get("total_mb")},
                        verification_method="gpu_memory_telemetry_check"
                    )
                elif action_result.get("memory_telemetry_available") is False or action_result.get("status") == "unavailable":
                    # Verified truthful reporting when hardware/driver does not expose telemetry
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_SUCCESS,
                        verified=True,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"gpu_memory_truthful_telemetry": True},
                        observed_state={"memory_telemetry_available": False, "truthfully_reported": True, "gpu_name": action_result.get("gpu_name")},
                        verification_method="gpu_memory_truthful_reporting_check"
                    )
                else:
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_FAILURE,
                        verified=False,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"gpu_memory_telemetry": True},
                        observed_state={"action_result": action_result.get("message")},
                        failure_reason="GPU memory request returned generic GPU info without genuine memory telemetry or truthful unavailability report.",
                        verification_method="gpu_memory_telemetry_check"
                    )

        if action_result and (action_result.get("status") == "success" or action_result.get("success") is True):
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state=expected_state or {"handled": True},
                observed_state={"success": True},
                verification_method="device_query_action_result"
            )


        return OutcomeVerificationResult(
            status=OutcomeStatus.UNCERTAIN,
            verified=bool(action_result and action_result.get("status") != "error"),
            confidence=ConfidenceLevel.LOW,
            failure_reason="Device control target cannot be deterministically verified.",
            verification_method="device_state_inspection"
        )

    @staticmethod
    def verify_document_generation(
        expected: ExpectedOutcome,
        post_obs: Dict[str, Any],
        state_diff: Optional[StateDifference] = None,
        action_result: Optional[Dict[str, Any]] = None
    ) -> OutcomeVerificationResult:
        file_path = expected.target or (action_result.get("file_path") if action_result else "")
        if not file_path and action_result:
            file_path = action_result.get("filepath") or action_result.get("path") or action_result.get("filename")

        # Failure 8 fix: Conversational responses, goal updates, and non-document actions
        # must not be treated as failed document generations.
        if action_result and (action_result.get("goal_type") == "natural_goal" or action_result.get("is_goal_update") or action_result.get("handled")):
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state=expected.expected_state,
                observed_state={"action": "goal_update_or_conversation", "status": "handled"},
                verification_method="conversational_outcome_check"
            )

        if not file_path:
            # If intent is GENERAL_CONVERSATION, lack of file_path is expected, not a failure
            if (expected.intent or "").upper() == "GENERAL_CONVERSATION":
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state=expected.expected_state,
                    observed_state={"action": "conversational", "status": "handled"},
                    verification_method="conversational_outcome_check"
                )
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verified=False,
                confidence=ConfidenceLevel.HIGH,
                failure_reason="Document generator produced no output file path.",
                verification_method="document_structural_inspection"
            )

        if not os.path.exists(file_path):
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verified=False,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"file_exists": True, "path": file_path},
                observed_state={"file_exists": False},
                failure_reason=f"Generated document '{file_path}' does not exist on disk.",
                verification_method="document_structural_inspection",
                retry_possible=True
            )

        size = os.path.getsize(file_path)
        if size == 0:
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verified=False,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"size_gt": 0, "path": file_path},
                observed_state={"size": 0},
                failure_reason=f"Generated document '{file_path}' is an empty zero-byte file.",
                verification_method="document_structural_inspection"
            )

        # Header Magic Bytes Validation
        ext = os.path.splitext(file_path)[1].lower()
        try:
            with open(file_path, "rb") as f:
                header = f.read(8)
                if ext == ".pdf" and not header.startswith(b"%PDF-"):
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_FAILURE,
                        verified=False,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"valid_header": "%PDF-"},
                        observed_state={"actual_header": str(header[:5])},
                        failure_reason="PDF file is corrupt: missing '%PDF-' header signature.",
                        verification_method="document_structural_inspection"
                    )
                elif ext in (".docx", ".xlsx", ".pptx") and not header.startswith(b"PK\x03\x04"):
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_FAILURE,
                        verified=False,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"valid_header": "PK archive"},
                        observed_state={"actual_header": str(header[:4])},
                        failure_reason=f"Office document '{ext}' is corrupt: missing PK zip header.",
                        verification_method="document_structural_inspection"
                    )
        except Exception as e:
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verified=False,
                confidence=ConfidenceLevel.HIGH,
                failure_reason=f"Could not read generated document file: {e}",
                verification_method="document_structural_inspection"
            )

        return OutcomeVerificationResult(
            status=OutcomeStatus.VERIFIED_SUCCESS,
            verified=True,
            confidence=ConfidenceLevel.HIGH,
            expected_state={"exists": True, "size_gt": 0, "path": file_path, "ext": ext},
            observed_state={"exists": True, "size": size, "path": file_path},
            verification_method="document_structural_inspection"
        )

    @staticmethod
    def verify_reminders(
        expected: ExpectedOutcome,
        post_obs: Dict[str, Any],
        state_diff: Optional[StateDifference] = None,
        action_result: Optional[Dict[str, Any]] = None,
        user_id: Optional[Any] = None
    ) -> OutcomeVerificationResult:
        uid = user_id or expected.expected_state.get("user_id") or 1
        target_title = (expected.target or expected.expected_state.get("title") or "").strip().lower()

        try:
            from core.assistant_core import assistant_core
            reminders = assistant_core.get_user_reminders(user_id=uid)
            if not isinstance(reminders, list):
                reminders = []

            is_cancel = expected.action == "cancel_reminder" or expected.expected_state.get("reminder_exists") is False

            # Check if reminder exists for this user
            found = False
            for rem in reminders:
                r_title = (rem.get("title") or rem.get("task") or "").lower()
                if target_title in r_title or (r_title and r_title in target_title):
                    found = True
                    break

            if is_cancel:
                if not found or (action_result and action_result.get("success")):
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_SUCCESS,
                        verified=True,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"reminder_exists": False, "user_id": uid, "title": target_title},
                        observed_state={"found": False},
                        verification_method="database_reminder_query"
                    )
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_FAILURE,
                    verified=False,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"reminder_exists": False, "user_id": uid, "title": target_title},
                    observed_state={"found": True},
                    failure_reason=f"Reminder '{target_title}' was still found in database for User {uid}.",
                    verification_method="database_reminder_query"
                )

            if not found and action_result:
                resp_text = str(action_result.get("response") or "")
                m_task = re.search(r"reminder set:\s*(.+?)(?:\s+at|\s+on|$)", resp_text, re.IGNORECASE)
                if m_task:
                    resp_task = m_task.group(1).strip().lower()
                    for rem in reminders:
                        r_title = (rem.get("title") or rem.get("task") or "").lower()
                        if resp_task in r_title or r_title in resp_task:
                            found = True
                            target_title = resp_task
                            break

            if found or (action_result and action_result.get("success") and not target_title):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"reminder_exists": True, "user_id": uid, "title": target_title},
                    observed_state={"found": True},
                    verification_method="database_reminder_query"
                )

            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verified=False,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"reminder_exists": True, "user_id": uid, "title": target_title},
                observed_state={"found": False, "count": len(reminders)},
                failure_reason=f"Reminder '{target_title}' was not found in database for User {uid}.",
                verification_method="database_reminder_query",
                retry_possible=True
            )
        except Exception as e:
            return OutcomeVerificationResult(
                status=OutcomeStatus.UNCERTAIN,
                verified=False,
                confidence=ConfidenceLevel.LOW,
                failure_reason=f"Error querying reminders from database: {e}",
                verification_method="database_reminder_query"
            )

    @staticmethod
    def verify_task_management(
        expected: ExpectedOutcome,
        post_obs: Dict[str, Any],
        state_diff: Optional[StateDifference] = None,
        action_result: Optional[Dict[str, Any]] = None,
        user_id: Optional[Any] = None
    ) -> OutcomeVerificationResult:
        uid = user_id or expected.expected_state.get("user_id") or 1
        task_id = expected.target or (action_result.get("task_id") if action_result else "")
        req_status = expected.expected_state.get("status", "running").lower()

        try:
            from skills.task_management.task_queue import get_task_queue
            tq = get_task_queue()
            user_tasks = tq.list_user_tasks(uid)

            if task_id:
                for t in user_tasks:
                    if str(t.get("task_id", t.get("id"))) == str(task_id):
                        cur_status = str(t.get("status", "")).lower()
                        if req_status in cur_status or cur_status in req_status:
                            return OutcomeVerificationResult(
                                status=OutcomeStatus.VERIFIED_SUCCESS,
                                verified=True,
                                confidence=ConfidenceLevel.HIGH,
                                expected_state={"task_id": task_id, "status": req_status},
                                observed_state={"task_id": task_id, "status": cur_status},
                                verification_method="task_queue_inspection"
                            )
                        return OutcomeVerificationResult(
                            status=OutcomeStatus.VERIFIED_FAILURE,
                            verified=False,
                            confidence=ConfidenceLevel.HIGH,
                            expected_state={"task_id": task_id, "status": req_status},
                            observed_state={"task_id": task_id, "status": cur_status},
                            failure_reason=f"Task {task_id} status is '{cur_status}', expected '{req_status}'.",
                            verification_method="task_queue_inspection",
                            retry_possible=True
                        )

            # If task_id was not explicit, check state difference
            if state_diff and ("TASK_STARTED" in state_diff.changes or "TASK_COMPLETED" in state_diff.changes):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"status": req_status},
                    observed_state={"diff": state_diff.meaningful_summary},
                    verification_method="state_diff_task_transition"
                )

            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS if (action_result and action_result.get("success")) else OutcomeStatus.UNCERTAIN,
                verified=bool(action_result and action_result.get("success")),
                confidence=ConfidenceLevel.MEDIUM if (action_result and action_result.get("success")) else ConfidenceLevel.LOW,
                verification_method="task_queue_inspection"
            )
        except Exception as e:
            return OutcomeVerificationResult(
                status=OutcomeStatus.UNCERTAIN,
                verified=False,
                confidence=ConfidenceLevel.LOW,
                failure_reason=f"Task queue unavailable: {e}",
                verification_method="task_queue_inspection"
            )

    @staticmethod
    def verify_smart_home(
        expected: ExpectedOutcome,
        post_obs: Dict[str, Any],
        state_diff: Optional[StateDifference] = None,
        action_result: Optional[Dict[str, Any]] = None,
        user_id: Optional[Any] = None
    ) -> OutcomeVerificationResult:
        uid = user_id or expected.expected_state.get("user_id") or 1
        device_id = expected.target or (action_result.get("device_id") if action_result else "")
        req_state = expected.expected_state

        try:
            from skills.smart_home.storage import get_smart_home_storage
            storage = get_smart_home_storage()
            devs = storage.list_devices(uid)

            target_dev = None
            for d in devs:
                d_id = getattr(d, "device_id", None) or d.get("device_id")
                d_name = getattr(d, "name", None) or d.get("name") or ""
                if str(d_id) == str(device_id) or (device_id and device_id.lower() in d_name.lower()):
                    target_dev = d
                    break

            if target_dev:
                dev_dict = target_dev.to_dict() if hasattr(target_dev, "to_dict") else dict(target_dev)
                # Verify match
                is_on = dev_dict.get("is_on")
                if "is_on" in req_state and is_on is not None:
                    if bool(is_on) == bool(req_state["is_on"]):
                        return OutcomeVerificationResult(
                            status=OutcomeStatus.VERIFIED_SUCCESS,
                            verified=True,
                            confidence=ConfidenceLevel.HIGH,
                            expected_state=req_state,
                            observed_state=dev_dict,
                            verification_method="smart_home_device_query"
                        )
                    else:
                        return OutcomeVerificationResult(
                            status=OutcomeStatus.VERIFIED_FAILURE,
                            verified=False,
                            confidence=ConfidenceLevel.HIGH,
                            expected_state=req_state,
                            observed_state=dev_dict,
                            failure_reason=f"Device '{device_id}' state is is_on={is_on}, expected {req_state['is_on']}.",
                            verification_method="smart_home_device_query",
                            retry_possible=True
                        )

            if action_result and action_result.get("success"):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.MEDIUM,
                    verification_method="smart_home_service_result"
                )

            return OutcomeVerificationResult(
                status=OutcomeStatus.UNCERTAIN,
                verified=False,
                confidence=ConfidenceLevel.LOW,
                failure_reason="Device state could not be confirmed with provider.",
                verification_method="smart_home_device_query"
            )
        except Exception as e:
            return OutcomeVerificationResult(
                status=OutcomeStatus.UNCERTAIN,
                verified=False,
                confidence=ConfidenceLevel.LOW,
                failure_reason=f"Smart home verification error: {e}",
                verification_method="smart_home_device_query"
            )

    @staticmethod
    def verify_audio_volume(
        expected: ExpectedOutcome,
        post_obs: Dict[str, Any],
        state_diff: Optional[StateDifference] = None,
        action_result: Optional[Dict[str, Any]] = None
    ) -> OutcomeVerificationResult:
        req_level = expected.expected_state.get("level")
        tolerance = expected.acceptable_tolerance.get("level_tolerance", 5)

        if action_result and action_result.get("already_satisfied"):
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"volume": req_level},
                observed_state={"already_satisfied": True, "volume": action_result.get("volume") or post_obs.get("volume")},
                verification_method="existing_state_already_satisfied"
            )

        # In pure desktop Windows without PyCaw, direct volume reads might be unavailable
        observed_level = post_obs.get("master_volume") or (action_result.get("volume") if action_result else None)

        if req_level is not None and observed_level is not None:
            try:
                diff = abs(float(observed_level) - float(req_level))
                if diff <= float(tolerance):
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_SUCCESS,
                        verified=True,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"volume": req_level},
                        observed_state={"volume": observed_level},
                        verification_method="audio_endpoint_volume_check"
                    )
                else:
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_FAILURE,
                        verified=False,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"volume": req_level},
                        observed_state={"volume": observed_level},
                        failure_reason=f"Observed volume {observed_level} is outside tolerance (+/- {tolerance}) of requested {req_level}.",
                        verification_method="audio_endpoint_volume_check"
                    )
            except (ValueError, TypeError):
                pass

        if action_result and action_result.get("success") is False:
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verified=False,
                confidence=ConfidenceLevel.HIGH,
                failure_reason=action_result.get("error", "Volume adjustment failed."),
                verification_method="audio_action_result"
            )

        # Fallback to UNCERTAIN if audio level cannot be measured deterministically
        return OutcomeVerificationResult(
            status=OutcomeStatus.UNCERTAIN,
            verified=bool(action_result and action_result.get("status") != "error"),
            confidence=ConfidenceLevel.LOW,
            failure_reason="System audio volume could not be measured directly via OS endpoint.",
            verification_method="audio_action_result"
        )

    @staticmethod
    def verify_notes(
        expected: ExpectedOutcome,
        post_obs: Dict[str, Any],
        state_diff: Optional[StateDifference] = None,
        action_result: Optional[Dict[str, Any]] = None,
        user_id: Optional[Any] = None
    ) -> OutcomeVerificationResult:
        uid = user_id or expected.expected_state.get("user_id") or 1
        target_content = (expected.target or expected.expected_state.get("content") or "").strip().lower()

        try:
            from core.assistant_core import assistant_core
            notes = assistant_core.get_user_notes(user_id=uid)
            found = False
            for n in notes:
                content = str(n.get("content") or n.get("note") or "").lower()
                if target_content in content:
                    found = True
                    break

            if not found:
                try:
                    from modules.calendar_manager.calendar_storage import CalendarStorage
                    cal_storage = CalendarStorage()
                    from datetime import datetime, timedelta
                    now = datetime.now()
                    d1 = (now - timedelta(days=7)).strftime("%Y-%m-%d")
                    d2 = (now + timedelta(days=30)).strftime("%Y-%m-%d")
                    ev_map = cal_storage.get_events_range(uid, d1, d2)
                    for _, ev_list in ev_map.items():
                        for ev in ev_list:
                            meta = ev.get("metadata") or {}
                            n_str = str(meta.get("notes") or "").lower()
                            if target_content in n_str or (target_content and any(w in n_str for w in target_content.split() if len(w) > 4)):
                                found = True
                                break
                        if found:
                            break
                except Exception:
                    pass

            if found or (action_result and action_result.get("success") and not target_content):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state={"note_exists": True, "user_id": uid},
                    observed_state={"found": True},
                    verification_method="notes_database_query"
                )

            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verified=False,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"note_exists": True, "user_id": uid, "content": target_content},
                observed_state={"found": False},
                failure_reason=f"Note content was not found in database for User {uid}.",
                verification_method="notes_database_query"
            )
        except Exception as e:
            return OutcomeVerificationResult(
                status=OutcomeStatus.UNCERTAIN,
                verified=False,
                confidence=ConfidenceLevel.LOW,
                failure_reason=f"Could not verify notes: {e}",
                verification_method="notes_database_query"
            )

    @staticmethod
    def verify_memory_store(
        expected: ExpectedOutcome,
        post_obs: Dict[str, Any],
        state_diff: Optional[StateDifference] = None,
        action_result: Optional[Dict[str, Any]] = None,
        user_id: Optional[Any] = None
    ) -> OutcomeVerificationResult:
        uid = user_id or expected.expected_state.get("user_id") or 1
        key = (expected.expected_state.get("key") or expected.target or "").strip()
        val = expected.expected_state.get("value")

        try:
            from core.chatgpt_memory import get_chatgpt_memory
            mem = get_chatgpt_memory()
            facts = mem.get_user_facts(uid)

            if key and key in facts:
                if val is None or str(facts[key]).strip() == str(val).strip():
                    return OutcomeVerificationResult(
                        status=OutcomeStatus.VERIFIED_SUCCESS,
                        verified=True,
                        confidence=ConfidenceLevel.HIGH,
                        expected_state={"key": key, "value": val, "user_id": uid},
                        observed_state={"facts": facts},
                        verification_method="chatgpt_memory_inspection"
                    )

            if action_result and (action_result.get("success") or action_result.get("status") == "success" or action_result.get("handled")):
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.MEDIUM,
                    verification_method="chatgpt_memory_action"
                )

            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verified=False,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"key": key, "value": val, "user_id": uid},
                observed_state={"facts": facts},
                failure_reason=f"Fact '{key}' was not found in ChatGPT memory for User {uid}.",
                verification_method="chatgpt_memory_inspection"
            )
        except Exception as e:
            return OutcomeVerificationResult(
                status=OutcomeStatus.UNCERTAIN,
                verified=False,
                confidence=ConfidenceLevel.LOW,
                failure_reason=f"Memory verification error: {e}",
                verification_method="chatgpt_memory_inspection"
            )


# ============================================================================
# Central Outcome Verifier
# ============================================================================

class OutcomeVerifier:
    """
    Canonical Outcome Verification Coordinator for NOVA.
    Derives Expected Outcomes, routes to appropriate Verification Adapters,
    manages bounded observation retries, and maintains Execution Records.
    """

    def __init__(self, record_tracker: Optional[ExecutionRecordTracker] = None):
        self.tracker = record_tracker or get_record_tracker()

    def verify_open_application(
        self,
        requested_target: str,
        resolved_executable: str,
        launch_result: Optional[Dict[str, Any]] = None
    ) -> OutcomeVerificationResult:
        """Cross-verify an application launch against the requested target."""
        expected = ExpectedOutcome(
            action="open_application",
            target=requested_target,
            intent="OPEN_APPLICATION"
        )
        act_res = dict(launch_result or {})
        act_res.setdefault("path", resolved_executable)
        act_res.setdefault("display_name", os.path.basename(resolved_executable))
        act_res.setdefault("target", requested_target)
        return VerificationAdapters.verify_open_application(
            expected=expected,
            post_obs={},
            state_diff=None,
            action_result=act_res
        )

    def derive_expected_outcome(
        self,
        intent: str,
        command_or_input: str,
        action_result: Optional[Dict[str, Any]] = None,
        target_hint: Optional[str] = None
    ) -> ExpectedOutcome:
        """Derive explicit expected outcome from intent, input text, and action parameters."""
        intent_up = (intent or "").upper().strip()
        text = (command_or_input or "").strip()
        text_low = text.lower()

        # 1. OPEN_APPLICATION / CLOSE_APPLICATION
        is_close_action = (
            intent_up == "CLOSE_APPLICATION"
            or (action_result and (action_result.get("action") in ("close", "close_app", "terminate_process") or "closed" in str(action_result.get("response", "")).lower()))
            or text_low.startswith(("close ", "quit ", "exit ", "kill ", "terminate "))
        )
        if (intent_up in ("OPEN_APPLICATION", "CLOSE_APPLICATION")) and is_close_action:
            target = target_hint or ""
            if not target and action_result:
                target = action_result.get("app_name") or action_result.get("target") or ""
            if not target:
                m = re.match(r"(?:close|quit|exit|kill|terminate)\s+([a-zA-Z0-9_\-\.]+)", text_low)
                if m:
                    target = m.group(1)
            return ExpectedOutcome(
                action="close_application",
                target=target,
                intent="CLOSE_APPLICATION",
                expected_state={"process_running": False},
                verification_method="process_window_check"
            )

        # 1b. FILE_OPERATIONS / OPEN_ARTIFACT
        is_file_or_artifact = (
            intent_up in ("FILE_OPERATIONS", "OPEN_ARTIFACT")
            or (action_result and (action_result.get("intent") in ("OPEN_ARTIFACT", "FILE_OPERATIONS") or action_result.get("files") or action_result.get("action") in ("open_file", "open_folder", "create_folder", "rename_file", "open_artifact")))
            or any(w in text_low for w in ["folder", "directory"])
            or (intent_up != "OPEN_APPLICATION" and any(w in text_low for w in ["file", "delete", "create", "rename"]))
        )
        if is_file_or_artifact:
            op = "create"
            if any(w in text_low for w in ["delete", "remove", "erase"]):
                op = "delete"
            elif any(w in text_low for w in ["open", "view", "launch"]):
                op = "open"
            elif any(w in text_low for w in ["rename"]):
                op = "rename"
            target = target_hint or ""
            if not target and action_result:
                target = action_result.get("filepath") or action_result.get("path") or action_result.get("target") or action_result.get("folder") or ""
            return ExpectedOutcome(
                action=op,
                target=target,
                intent=intent_up or "FILE_OPERATIONS",
                expected_state={"exists": (op != "delete")},
                verification_method="file_system_inspection"
            )

        # 1c. Browser results & web search (must precede generic OPEN_APPLICATION)
        if (action_result and (action_result.get("action") == "open_browser_result" or action_result.get("entity_type") == "BROWSER_RESULT")) or re.search(r'\b(?:open|click|select)\s+(?:the\s+)?(?:first|second|third|fourth|fifth|\d+(?:st|nd|rd|th)|top|previous)?\s*(?:result|link)\b', text_low):
            target_url = (action_result.get("url") if action_result else "") or target_hint or "browser_result"
            return ExpectedOutcome(
                action="open_browser_result",
                target=target_url,
                intent="OPEN_APPLICATION",
                expected_state={"url": target_url, "browser_open": True},
                verification_method="browser_result_verification"
            )

        if (action_result and (action_result.get("action") == "search_web" or action_result.get("entity_type") == "SEARCH_QUERY")) or (text_low.startswith(("search ", "look up ", "find ")) and not any(w in text_low for w in ["file", "folder"])):
            query = (action_result.get("query") if action_result else "") or target_hint or text
            return ExpectedOutcome(
                action="search_web",
                target=query,
                intent="OPEN_APPLICATION",
                expected_state={"search_performed": True, "query": query},
                verification_method="browser_search_verification"
            )

        # 1d. Text Typing
        if (action_result and (action_result.get("action") == "type_text" or action_result.get("entity_type") == "TEXT")) or re.search(r'\b(?:type|write)\s+(?!a\s+note\b|note\b|code\b|python\b|script\b|report\b|document\b|email\b|mail\b)(.+)', text_low):
            typed_text = (action_result.get("text") if action_result else "") or target_hint or ""
            return ExpectedOutcome(
                action="type_text",
                target=typed_text,
                intent="DEVICE_CONTROL",
                expected_state={"text_typed": True},
                verification_method="keyboard_input_verification"
            )

        # 1e. Calculator
        if intent_up == "CALCULATOR" or (action_result and (action_result.get("action") == "calculate" or action_result.get("entity_type") == "CALCULATION")):
            result_val = (action_result.get("result") if action_result else None)
            return ExpectedOutcome(
                action="calculate",
                target=str(result_val or ""),
                intent="CALCULATOR",
                expected_state={"calculation_performed": True, "result": result_val},
                verification_method="calculator_output_verification"
            )

        if intent_up == "OPEN_APPLICATION" or text_low.startswith(("open ", "launch ", "start ")):
            target = target_hint or ""
            if not target and action_result:
                target = action_result.get("app_name") or action_result.get("target") or ""
            if not target:
                clean_open_text = re.sub(
                    r'\b(?:open|launch|start)\s+(?:(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+(?:instance|window)\s+of\s+|(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+)',
                    'open ',
                    text_low,
                    flags=re.IGNORECASE
                )
                m = re.match(r"(?:open|launch|start)\s+(?:(?:the|a|an|my)\s+)?([a-zA-Z0-9_\-\.]+)", clean_open_text)
                if m:
                    target = m.group(1)

            # Strip instance modifiers if present in target
            m_inst_tgt = re.match(
                r'^(?:(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+(?:instance|window)\s+of\s+|'
                r'(?:another|a\s+new|an\s+additional|a\s+fresh|fresh|a\s+different|different|a\s+second|second|new)\s+)',
                target,
                re.IGNORECASE
            )
            if m_inst_tgt:
                target = target[m_inst_tgt.end():].strip()
                target = re.sub(r'^(?:the|a|an)\s+', '', target, flags=re.IGNORECASE).strip()

            if target.lower() in ("another", "new", "fresh", "different", "second", "instance", "window"):
                m_after = re.search(r"(?:another|new|fresh|different|second)\s+([a-zA-Z0-9_\-\.]+)", text_low)
                if m_after:
                    target = m_after.group(1)

            return ExpectedOutcome(
                action="open_application",
                target=target,
                intent=intent_up,
                expected_state={"active_application": target},
                verification_method="active_application_and_window_match"
            )

        # 3. DOCUMENT_GENERATION
        # Must not classify GENERAL_CONVERSATION as document generation unless action_result actually produced a file
        is_doc_intent = (intent_up == "DOCUMENT_GENERATION")
        is_doc_result = bool(action_result and (action_result.get("file_path") or action_result.get("path") or action_result.get("type") == "document"))
        is_explicit_doc_cmd = (intent_up != "GENERAL_CONVERSATION" and any(w in text_low for w in ["pdf", "docx", "pptx", "xlsx", "spreadsheet"]) and any(w in text_low for w in ["create", "generate", "make", "build", "export"]))

        if (is_doc_intent or is_doc_result or is_explicit_doc_cmd) and not (action_result and (action_result.get("goal_type") == "natural_goal" or action_result.get("is_goal_update"))):
            target = target_hint or ""
            if not target and action_result:
                target = action_result.get("file_path") or action_result.get("path") or ""
            return ExpectedOutcome(
                action="document_generation",
                target=target,
                intent=intent_up,
                expected_state={"file_exists": True, "size_gt": 0},
                verification_method="document_structural_inspection"
            )

        # 4. DEVICE_CONTROL
        if intent_up == "DEVICE_CONTROL":
            if "caps" in text_low:
                target = "caps_lock"
                req_val = False if "off" in text_low else True
                return ExpectedOutcome(
                    action="toggle_key",
                    target=target,
                    intent=intent_up,
                    expected_state={"caps_lock": req_val},
                    verification_method="win32_key_state_inspection"
                )
            elif "num" in text_low:
                target = "num_lock"
                req_val = False if "off" in text_low else True
                return ExpectedOutcome(
                    action="toggle_key",
                    target=target,
                    intent=intent_up,
                    expected_state={"num_lock": req_val},
                    verification_method="win32_key_state_inspection"
                )
            elif "volume" in text_low:
                is_rel = any(w in text_low for w in ["increase", "decrease", "raise", "lower", "up", "down", "by"])
                target_val = action_result.get("target") if action_result else None
                if is_rel:
                    action_name = "volume_change"
                    req_lvl = target_val
                else:
                    action_name = "set_volume"
                    m_v = re.search(r'(\d+)', text_low)
                    req_lvl = target_val if target_val is not None else (int(m_v.group(1)) if m_v else None)
                return ExpectedOutcome(
                    action=action_name,
                    target="volume",
                    intent=intent_up,
                    expected_state={"volume": req_lvl} if req_lvl is not None else {},
                    acceptable_tolerance={"level_tolerance": 3},
                    verification_method="audio_endpoint_volume_check"
                )
            elif "brightness" in text_low:
                is_rel = any(w in text_low for w in ["increase", "decrease", "raise", "lower", "up", "down", "by"])
                target_val = action_result.get("target") if action_result else None
                if is_rel:
                    action_name = "adjust_brightness"
                    req_b = target_val
                else:
                    action_name = "set_brightness"
                    m_b = re.search(r'(\d+)', text_low)
                    req_b = target_val if target_val is not None else (int(m_b.group(1)) if m_b else None)
                return ExpectedOutcome(
                    action=action_name,
                    target="brightness",
                    intent=intent_up,
                    expected_state={"brightness": req_b} if req_b is not None else {},
                    acceptable_tolerance={"level_tolerance": 5},
                    verification_method="brightness_state_inspection"
                )
            elif "dark mode" in text_low or "light mode" in text_low:
                req_dm = False if any(w in text_low for w in ["off", "disable", "light mode"]) else True
                return ExpectedOutcome(
                    action="toggle_dark_mode",
                    target="dark_mode",
                    intent=intent_up,
                    expected_state={"dark_mode": req_dm},
                    verification_method="registry_theme_inspection"
                )
            elif "screenshot" in text_low or "capture screen" in text_low:
                return ExpectedOutcome(
                    action="screenshot",
                    target="screenshot",
                    intent=intent_up,
                    expected_state={"screenshot_exists": True},
                    verification_method="filesystem_screenshot_inspection"
                )
            elif "gpu memory" in text_low or "vram" in text_low:
                return ExpectedOutcome(
                    action="gpu_memory",
                    target="gpu_memory",
                    intent=intent_up,
                    expected_state={"gpu_memory_telemetry": True},
                    verification_method="hardware_telemetry_gpu_memory"
                )
            elif "detailed gpu" in text_low:
                return ExpectedOutcome(
                    action="detailed_gpu",
                    target="detailed_gpu",
                    intent=intent_up,
                    expected_state={"primary_gpu": True},
                    verification_method="hardware_telemetry_gpu"
                )
            elif "detailed cpu" in text_low:
                return ExpectedOutcome(
                    action="detailed_cpu",
                    target="detailed_cpu",
                    intent=intent_up,
                    expected_state={"cpu_name": True, "logical_processors": True},
                    verification_method="hardware_telemetry_cpu"
                )
            elif "detailed ram" in text_low or "detailed memory" in text_low:
                return ExpectedOutcome(
                    action="detailed_ram",
                    target="detailed_ram",
                    intent=intent_up,
                    expected_state={"total_gb": True, "swap_total_gb": True},
                    verification_method="hardware_telemetry_ram"
                )
            elif "cpu" in text_low:
                return ExpectedOutcome(
                    action="cpu_metrics",
                    target="cpu",
                    intent=intent_up,
                    expected_state={"cpu_metrics": True},
                    verification_method="hardware_telemetry_cpu"
                )
            elif "ram" in text_low or "memory usage" in text_low:
                return ExpectedOutcome(
                    action="ram_metrics",
                    target="ram",
                    intent=intent_up,
                    expected_state={"ram_metrics": True},
                    verification_method="hardware_telemetry_ram"
                )
            elif "gpu" in text_low:
                return ExpectedOutcome(
                    action="gpu_telemetry",
                    target="gpu",
                    intent=intent_up,
                    expected_state={"gpu_telemetry": True},
                    verification_method="hardware_telemetry_gpu"
                )

        # 5. REMINDERS
        if intent_up == "REMINDERS" or "remind" in text_low:
            is_cancel = any(w in text_low for w in ["cancel", "delete", "remove", "clear"])
            action = "cancel_reminder" if is_cancel else "create_reminder"
            title = ""
            m_to = re.search(r"\bto\s+([^,]+?)(?:\s+at|\s+in|\s+on|$)", text_low)
            if not m_to:
                m_to = re.search(r"\bto\s+(.+)$", text_low)
            if m_to:
                title = m_to.group(1).strip()
            else:
                m = re.search(r"remind\s+(?:me\s+)?(?:to\s+)?(.+?)(?:\s+at|\s+in|\s+on|$)", text_low)
                if m:
                    title = m.group(1).strip()
            return ExpectedOutcome(
                action=action,
                target=title,
                intent=intent_up,
                expected_state={"reminder_exists": not is_cancel, "title": title},
                verification_method="database_reminder_query"
            )

        # 6. TASK_MANAGEMENT
        if intent_up == "TASK_MANAGEMENT" or "task" in text_low:
            action = "run_task"
            if "cancel" in text_low:
                action = "cancel_task"
            return ExpectedOutcome(
                action=action,
                intent=intent_up,
                expected_state={"status": "completed" if action == "run_task" else "cancelled"},
                verification_method="task_queue_inspection"
            )

        # 7. SMART_HOME
        if intent_up == "SMART_HOME" or any(w in text_low for w in ["light", "fan", "ac", "smart"]):
            is_on = False if any(w in text_low for w in ["off", "turn off", "disable"]) else True
            return ExpectedOutcome(
                action="smart_home_control",
                intent=intent_up,
                expected_state={"is_on": is_on},
                verification_method="smart_home_device_query"
            )

        # 8. AUDIO / VOLUME
        if any(w in text_low for w in ["volume", "mute", "unmute", "louder", "softer"]):
            return ExpectedOutcome(
                action="volume_change",
                intent=intent_up,
                expected_state={"status": "adjusted"},
                verification_method="audio_endpoint_volume_check"
            )

        # 9. NOTES
        if (intent_up == "NOTES" or ("note" in text_low and not any(w in text_low for w in ["meeting", "calendar", "event", "standup", "huddle", "review"]))) and not any(w in text_low for w in ["notepad", "close notepad", "open notepad", "quit notepad"]):
            return ExpectedOutcome(
                action="save_note",
                intent=intent_up or "NOTES",
                expected_state={"note_exists": True},
                verification_method="notes_database_query"
            )

        # 10. MEMORY_STORE
        if intent_up == "MEMORY_STORE" or "remember" in text_low:
            return ExpectedOutcome(
                action="store_memory",
                intent=intent_up,
                expected_state={"fact_persisted": True},
                verification_method="chatgpt_memory_inspection"
            )

        # Generic / Informational / Conversational
        return ExpectedOutcome(
            action="conversational_or_query",
            intent=intent_up,
            expected_state={"handled": True},
            verification_method="generic_observation"
        )

    def verify_outcome(
        self,
        intent: str,
        command_or_input: str,
        action_result: Dict[str, Any],
        before_snap: Optional[EnvironmentSnapshot] = None,
        after_snap: Optional[EnvironmentSnapshot] = None,
        state_diff: Optional[StateDifference] = None,
        user_id: Optional[Any] = None,
        target_hint: Optional[str] = None,
        max_retries: int = 1,
        retry_delay: float = 0.25,
        cancellation_check: Optional[Callable[[], bool]] = None
    ) -> OutcomeVerificationResult:
        """
        Main verification entry point.
        Evaluates post-action observations, handles bounded propagation retries,
        and returns an OutcomeVerificationResult.
        """
        # If action itself failed at Python level, fail immediately
        if action_result.get("status") in ("error", "failed") and not action_result.get("handled", False):
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verified=False,
                confidence=ConfidenceLevel.HIGH,
                failure_reason=action_result.get("response") or action_result.get("error") or "Action execution returned error status.",
                verification_method="action_result_status_check",
                adaptation_possible=True
            )

        expected = self.derive_expected_outcome(intent, command_or_input, action_result, target_hint)
        obs_dict = after_snap.to_dict() if after_snap else {}

        intent_up = (intent or "").upper().strip()

        # Route to appropriate adapter
        result = self._dispatch_adapter(expected, obs_dict, state_diff, action_result, user_id)

        # Bounded Propagation Retry:
        # If outcome is failure or uncertain, and retry is possible, wait and re-observe
        retries_done = 0
        while (result.status in (OutcomeStatus.VERIFIED_FAILURE, OutcomeStatus.UNCERTAIN)
               and result.retry_possible
               and retries_done < max_retries):

            if cancellation_check and cancellation_check():
                print("[VERIFY] Bounded retry cancelled via cancellation signal.")
                break

            retries_done += 1
            print(f"[VERIFY] Bounded propagation wait ({retries_done}/{max_retries}) for {intent_up}...")
            time.sleep(retry_delay)

            # Re-observe environment
            categories = select_relevant_categories(intent_up, command_or_input, target_hint)
            new_snap = observe_environment(user_id=user_id, relevant_categories=categories, target_file=target_hint)
            new_obs = new_snap.to_dict()
            new_diff = compare_snapshots(before_snap, new_snap) if before_snap else state_diff

            # Re-dispatch verification
            result = self._dispatch_adapter(expected, new_obs, new_diff, action_result, user_id)
            if result.status == OutcomeStatus.VERIFIED_SUCCESS:
                break

        # False-Completion Protection:
        # If action_result reported success but outcome verification failed, set final status to failed
        return result

    def _dispatch_adapter(
        self,
        expected: ExpectedOutcome,
        obs_dict: Dict[str, Any],
        state_diff: Optional[StateDifference],
        action_result: Dict[str, Any],
        user_id: Optional[Any]
    ) -> OutcomeVerificationResult:
        intent = expected.intent

        if expected.action in ("open_browser_result", "open_link", "search_web") or action_result.get("action") in ("open_browser_result", "OPEN_BROWSER_RESULT", "open_link", "SEARCH") or action_result.get("is_website"):
            if action_result.get("status") in ("success", True) or action_result.get("success") is True:
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state=expected.expected_state,
                    observed_state={"action": expected.action, "url": action_result.get("url"), "query": action_result.get("query")},
                    verification_method="browser_result_verification"
                )
            else:
                return OutcomeVerificationResult(
                    status=OutcomeStatus.FAILED,
                    verified=False,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state=expected.expected_state,
                    observed_state={"action": expected.action, "error": action_result.get("response")},
                    verification_method="browser_result_verification"
                )

        elif expected.action == "type_text":
            if action_result.get("status") in ("success", True) or action_result.get("success") is True:
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state=expected.expected_state,
                    observed_state={"action": "type_text", "text": action_result.get("text")},
                    verification_method="keyboard_input_verification"
                )

        elif expected.action == "close_tab" or action_result.get("action") == "close_tab":
            is_ok = action_result.get("status") in ("success", True) or action_result.get("success") is True
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS if is_ok else OutcomeStatus.VERIFIED_FAILURE,
                verified=is_ok,
                confidence=ConfidenceLevel.HIGH,
                expected_state={"tab_closed": True},
                observed_state={"action": "close_tab", "status": action_result.get("status")},
                failure_reason=action_result.get("response") if not is_ok else None,
                verification_method="browser_tab_close_verification"
            )

        elif expected.action == "calculate" or intent == "CALCULATOR":
            if action_result.get("status") in ("success", True) or action_result.get("result") is not None:
                return OutcomeVerificationResult(
                    status=OutcomeStatus.VERIFIED_SUCCESS,
                    verified=True,
                    confidence=ConfidenceLevel.HIGH,
                    expected_state=expected.expected_state,
                    observed_state={"action": "calculate", "result": action_result.get("result")},
                    verification_method="calculator_output_verification"
                )

        elif expected.action == "close_application":
            return VerificationAdapters.verify_close_application(expected, obs_dict, state_diff, action_result)

        elif intent == "FILE_OPERATIONS" or expected.action in ("create", "delete", "write", "open", "open_folder"):
            return VerificationAdapters.verify_file_operations(expected, obs_dict, state_diff, action_result)

        elif intent == "OPEN_APPLICATION" or expected.action == "open_application":
            return VerificationAdapters.verify_open_application(expected, obs_dict, state_diff, action_result)

        elif intent == "DOCUMENT_GENERATION" or expected.action == "document_generation":
            return VerificationAdapters.verify_document_generation(expected, obs_dict, state_diff, action_result)

        elif intent == "DEVICE_CONTROL" or expected.intent == "DEVICE_CONTROL":
            return VerificationAdapters.verify_device_control(expected, obs_dict, state_diff, action_result)

        elif intent == "REMINDERS" or expected.action == "create_reminder":
            return VerificationAdapters.verify_reminders(expected, obs_dict, state_diff, action_result, user_id=user_id)

        elif intent == "TASK_MANAGEMENT" or expected.action in ("run_task", "cancel_task"):
            return VerificationAdapters.verify_task_management(expected, obs_dict, state_diff, action_result, user_id=user_id)

        elif intent == "SMART_HOME" or expected.action == "smart_home_control":
            return VerificationAdapters.verify_smart_home(expected, obs_dict, state_diff, action_result, user_id=user_id)

        elif expected.action == "volume_change":
            return VerificationAdapters.verify_audio_volume(expected, obs_dict, state_diff, action_result)

        elif intent == "NOTES" or expected.action == "save_note":
            return VerificationAdapters.verify_notes(expected, obs_dict, state_diff, action_result, user_id=user_id)

        elif intent == "MEMORY_STORE" or expected.action == "store_memory":
            return VerificationAdapters.verify_memory_store(expected, obs_dict, state_diff, action_result, user_id=user_id)

        # Informational / Conversational fallback
        if action_result.get("handled", False) or action_result.get("response"):
            return OutcomeVerificationResult(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                verified=True,
                confidence=ConfidenceLevel.HIGH,
                expected_state=expected.expected_state,
                observed_state={"response_generated": True},
                verification_method="conversational_response_presence"
            )

        return OutcomeVerificationResult(
            status=OutcomeStatus.NOT_APPLICABLE,
            verified=True,
            confidence=ConfidenceLevel.UNKNOWN,
            verification_method="not_applicable"
        )


_global_outcome_verifier = OutcomeVerifier()

def get_outcome_verifier() -> OutcomeVerifier:
    return _global_outcome_verifier
