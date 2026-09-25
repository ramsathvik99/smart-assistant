"""
Proactive Observation & Meaningful State-Change Events (PHASE 6)

Builds a controlled proactive-awareness layer ON TOP of Phase 5 EnvironmentObserver.
Observes safe, lightweight state categories, detects meaningful changes, applies
relevance filtering, deduplication, cooldowns, debounce, quiet/busy checking,
and surfaces concise notifications to the user without executing autonomous actions.

Key Guarantees:
- NO AUTONOMOUS ARBITRARY ACTIONS (observe & inform only)
- SAFE LIGHTWEIGHT CATEGORIES ONLY (active app/window, background tasks, paired devices)
- NO SENSITIVE POLLING (strictly no polling for clipboard, location, mic, camera, screen, filesystem)
- USER ISOLATED (events strictly scoped by user_id)
- DETERMINISTIC DEDUPLICATION & COOLDOWNS (deterministic event IDs, 30s default)
- DEBOUNCE / STABILITY (suppresses rapid state flapping)
- QUIET / BUSY AWARENESS (respects speaking state, active goal execution, cancellations)
- USER PREFERENCE CONTROL (ON / OFF)
- THREAD-SAFE & CLEAN SHUTDOWN
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from core.environment_observer import (
    EnvironmentSnapshot,
    StateDifference,
    observe_environment,
    compare_snapshots,
)

logger = logging.getLogger(__name__)

# Safe lightweight categories permitted for proactive background observation
SAFE_PROACTIVE_CATEGORIES: Set[str] = {"window", "app", "tasks", "devices"}

# Default configuration constants
DEFAULT_OBSERVATION_INTERVAL: float = 5.0   # seconds (minimum 5s)
DEFAULT_EVENT_COOLDOWN: float = 30.0        # seconds
DEFAULT_DEBOUNCE_WINDOW: float = 3.0        # seconds


class GoalImpact(str, Enum):
    """Phase 7: Classification of how a proactive event affects an active goal or conversation."""
    GOAL_PROGRESS = "GOAL_PROGRESS"
    GOAL_COMPLETED = "GOAL_COMPLETED"
    GOAL_BLOCKED = "GOAL_BLOCKED"
    GOAL_REQUIRES_USER = "GOAL_REQUIRES_USER"
    INFORMATIONAL = "INFORMATIONAL"
    IRRELEVANT = "IRRELEVANT"


@dataclass
class ProactiveEvent:
    """Represents a meaningful, user-relevant environmental state change."""
    event_id: str
    event_type: str
    timestamp: float = field(default_factory=time.time)
    source_category: str = "unknown"
    observed_change: str = ""
    before_state: Optional[Any] = None
    after_state: Optional[Any] = None
    user_id: str = "default"
    relevance_reason: str = ""
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    surfaced: bool = False
    
    # Phase 7 Goal-Aware Fields
    entity_type: str = ""                    # e.g., "task", "device", "application", "window"
    entity_id: str = ""                      # e.g., task_id, device_id, app_name
    impact: GoalImpact = GoalImpact.IRRELEVANT
    correlated_goal_id: Optional[str] = None
    correlated_step_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if isinstance(self.impact, Enum):
            d["impact"] = self.impact.value
        return d


@dataclass
class ProactiveObserverConfig:
    """Centralized configuration for proactive observation."""
    enabled: bool = True
    interval: float = DEFAULT_OBSERVATION_INTERVAL
    cooldown_seconds: float = DEFAULT_EVENT_COOLDOWN
    debounce_seconds: float = DEFAULT_DEBOUNCE_WINDOW
    allowed_categories: Set[str] = field(default_factory=lambda: set(SAFE_PROACTIVE_CATEGORIES))


# ============================================================================
# Proactive Event Detector & Relevance Filter
# ============================================================================

class ProactiveEventDetector:
    """
    Evaluates StateDifference from EnvironmentObserver snapshots,
    filters by user relevance and active goal awareness, and produces ProactiveEvents.
    """

    @staticmethod
    def generate_event_id(user_id: str, event_type: str, entity_id: str, state_transition: str) -> str:
        """Create a deterministic event identifier for deduplication and cooldown."""
        clean_u = str(user_id).strip().lower()
        clean_t = str(event_type).strip().upper()
        clean_e = str(entity_id).strip().lower()
        clean_s = str(state_transition).strip().lower()
        return f"{clean_u}:{clean_t}:{clean_e}:{clean_s}"

    @classmethod
    def detect_events(
        cls,
        before: EnvironmentSnapshot,
        after: EnvironmentSnapshot,
        state_diff: StateDifference,
        user_id: str = "default",
        active_goal_info: Optional[Dict[str, Any]] = None,
    ) -> List[ProactiveEvent]:
        """
        Extract meaningful, relevant proactive events from a state difference.
        Applies relevance rules to ensure noisy changes (e.g. routine window switches)
        are NOT announced unless explicitly relevant to an active goal.
        """
        events: List[ProactiveEvent] = []
        if not state_diff.has_changes:
            return events

        # ── 1. Background Tasks ───────────────────────────────────────────────
        b_task_ids = {str(t.get("task_id", t.get("id"))): t for t in before.active_tasks}
        a_task_ids = {str(t.get("task_id", t.get("id"))): t for t in after.active_tasks}

        for tid, t_data in a_task_ids.items():
            t_name = t_data.get("name") or t_data.get("description") or t_data.get("command") or f"task {tid}"
            a_st = str(t_data.get("status", "")).lower()
            b_st = str(b_task_ids.get(tid, {}).get("status", "")).lower() if tid in b_task_ids else "none"

            if a_st != b_st:
                if a_st in ("completed", "done", "finished"):
                    event_id = cls.generate_event_id(user_id, "TASK_COMPLETED", tid, f"{b_st}->completed")
                    events.append(ProactiveEvent(
                        event_id=event_id,
                        event_type="TASK_COMPLETED",
                        source_category="tasks",
                        entity_type="task",
                        entity_id=tid,
                        observed_change=f"Task '{t_name}' completed successfully",
                        before_state=b_st,
                        after_state=a_st,
                        user_id=str(user_id),
                        relevance_reason="User background task completed execution",
                        message=f"Your task '{t_name}' is complete.",
                        details={"task_id": tid, "task_name": t_name, "status": a_st},
                    ))
                elif a_st in ("failed", "error"):
                    event_id = cls.generate_event_id(user_id, "TASK_FAILED", tid, f"{b_st}->failed")
                    events.append(ProactiveEvent(
                        event_id=event_id,
                        event_type="TASK_FAILED",
                        source_category="tasks",
                        entity_type="task",
                        entity_id=tid,
                        observed_change=f"Task '{t_name}' failed",
                        before_state=b_st,
                        after_state=a_st,
                        user_id=str(user_id),
                        relevance_reason="User background task encountered a failure",
                        message=f"Your task '{t_name}' failed.",
                        details={"task_id": tid, "task_name": t_name, "status": a_st, "error": t_data.get("error")},
                    ))

        # ── 2. Paired Devices ─────────────────────────────────────────────────
        b_dev_ids = {str(d.get("device_id")): d for d in before.connected_devices}
        a_dev_ids = {str(d.get("device_id")): d for d in after.connected_devices}

        # Device came online or newly connected
        for did, d_data in a_dev_ids.items():
            d_name = d_data.get("name") or d_data.get("device_name") or f"device {did}"
            b_online = b_dev_ids[did].get("online", False) if did in b_dev_ids else False
            a_online = d_data.get("online", True)

            if did not in b_dev_ids or (not b_online and a_online):
                event_id = cls.generate_event_id(user_id, "DEVICE_CONNECTED", did, "offline->online")
                events.append(ProactiveEvent(
                    event_id=event_id,
                    event_type="DEVICE_CONNECTED",
                    source_category="devices",
                    entity_type="device",
                    entity_id=did,
                    observed_change=f"Device '{d_name}' connected",
                    before_state="offline" if did in b_dev_ids else "unpaired",
                    after_state="online",
                    user_id=str(user_id),
                    relevance_reason="Paired user device came online",
                    message=f"Your device '{d_name}' is now connected.",
                    details={"device_id": did, "device_name": d_name},
                ))

        # Device went offline or was removed
        for did, d_data in b_dev_ids.items():
            d_name = d_data.get("name") or d_data.get("device_name") or f"device {did}"
            b_online = d_data.get("online", True)
            if did not in a_dev_ids:
                event_id = cls.generate_event_id(user_id, "DEVICE_DISCONNECTED", did, "online->removed")
                events.append(ProactiveEvent(
                    event_id=event_id,
                    event_type="DEVICE_DISCONNECTED",
                    source_category="devices",
                    entity_type="device",
                    entity_id=did,
                    observed_change=f"Device '{d_name}' disconnected",
                    before_state="online" if b_online else "offline",
                    after_state="removed",
                    user_id=str(user_id),
                    relevance_reason="Paired user device was disconnected",
                    message=f"Your device '{d_name}' disconnected.",
                    details={"device_id": did, "device_name": d_name},
                ))
            else:
                a_online = a_dev_ids[did].get("online", False)
                if b_online and not a_online:
                    event_id = cls.generate_event_id(user_id, "DEVICE_DISCONNECTED", did, "online->offline")
                    events.append(ProactiveEvent(
                        event_id=event_id,
                        event_type="DEVICE_DISCONNECTED",
                        source_category="devices",
                        entity_type="device",
                        entity_id=did,
                        observed_change=f"Device '{d_name}' went offline",
                        before_state="online",
                        after_state="offline",
                        user_id=str(user_id),
                        relevance_reason="Paired user device went offline",
                        message=f"Your device '{d_name}' disconnected.",
                        details={"device_id": did, "device_name": d_name},
                    ))

        # ── 3. Active Window / Application (Filtered / Contextual Only) ────────
        # Window & App changes are NOT announced proactively by default.
        # They are only marked as relevant if an active goal explicitly depends on them.
        if "APPLICATION_CHANGED" in state_diff.changes or "ACTIVE_WINDOW_CHANGED" in state_diff.changes:
            app_before = before.active_application or "unknown"
            app_after = after.active_application or "unknown"
            win_title = after.foreground_window_title or ""

            goal_desc = (active_goal_info.get("description") or "").lower() if active_goal_info else ""
            goal_running = active_goal_info.get("status") in ("RUNNING", "WAITING_FOR_USER") if active_goal_info else False

            # Check if active goal explicitly waits for this application/window
            is_goal_relevant = False
            if goal_running and goal_desc:
                if (app_after != "unknown" and app_after.lower() in goal_desc) or (win_title and any(w in win_title.lower() for w in goal_desc.split() if len(w) > 3)):
                    is_goal_relevant = True

            if is_goal_relevant:
                event_id = cls.generate_event_id(user_id, "APPLICATION_CHANGED", app_after, f"{app_before}->{app_after}")
                events.append(ProactiveEvent(
                    event_id=event_id,
                    event_type="APPLICATION_CHANGED",
                    source_category="app",
                    entity_type="application",
                    entity_id=app_after,
                    observed_change=f"Application changed to '{app_after}'",
                    before_state=app_before,
                    after_state=app_after,
                    user_id=str(user_id),
                    relevance_reason=f"Application switch matches active goal '{goal_desc}'",
                    message=f"{app_after.capitalize()} is now active.",
                    details={"app": app_after, "window_title": win_title, "goal": goal_desc},
                ))
            else:
                logger.debug(
                    "[PROACTIVE] Suppressing unprompted app/window change from '%s' to '%s' (no active goal dependency)",
                    app_before, app_after
                )

        return events


# ============================================================================
# Phase 7: Goal-Aware Proactive Event Reasoner
# ============================================================================

class GoalAwareEventReasoner:
    """
    Phase 7: Correlates proactive events with active goals, plans, and execution steps.
    Determines GoalImpact:
      - GOAL_PROGRESS
      - GOAL_COMPLETED
      - GOAL_BLOCKED
      - GOAL_REQUIRES_USER
      - INFORMATIONAL
      - IRRELEVANT

    Guarantees:
      - Evidence-based deterministic matching (no probabilistic guessing)
      - User-scoped isolation
      - Freshness verification (stale events rejected)
      - Cancellation priority (cancelled goals cannot be completed)
      - Preserves WAITING_FOR_USER context
      - Zero autonomous side effects (no rogue actions executed)
    """

    @classmethod
    def correlate_and_apply(
        cls,
        event: ProactiveEvent,
        user_id: str = "default",
        dialogue_mgr: Optional[Any] = None,
    ) -> GoalImpact:
        """
        Evaluate how a proactive event affects the current active goal/dialogue state.
        Updates in-memory goal state and records evidence naturally.
        """
        uid = str(user_id)
        if dialogue_mgr is None:
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager
                dialogue_mgr = get_dialogue_manager(uid)
            except Exception:
                dialogue_mgr = None

        if not dialogue_mgr or not dialogue_mgr.current_state:
            event.impact = GoalImpact.INFORMATIONAL if event.source_category in ("devices", "tasks") else GoalImpact.IRRELEVANT
            return event.impact

        state = dialogue_mgr.current_state

        # 1. Cancellation Priority Check (Requirement 7 & 8)
        is_task_cancelled = bool(state.active_task and state.active_task.get("status") == "cancelled" and str(state.active_task.get("task_id", "")).lower() == str(event.entity_id).lower())
        is_device_cancelled = bool(state.active_device and state.active_device.get("status") == "cancelled")
        was_last_cancelled = bool(state.last_goal_outcome and state.last_goal_outcome.get("actual_outcome") == "CANCELLED" and state.current_goal is None)

        if state.goal_status == "CANCELLED" or is_task_cancelled or (was_last_cancelled and (is_task_cancelled or is_device_cancelled)):
            event.impact = GoalImpact.IRRELEVANT
            event.relevance_reason = "Active goal or entity was cancelled by user; proactive event cannot revive cancelled goal."
            return GoalImpact.IRRELEVANT

        # 2. Missing Entity Information Check (Requirement 14)
        if not event.entity_type or not event.entity_id or event.entity_id == "unknown":
            event.impact = GoalImpact.IRRELEVANT
            event.relevance_reason = "Event lacks concrete entity identification; cannot fabricate correlation."
            return GoalImpact.IRRELEVANT

        # 3. Freshness / Stale Event Check (Requirement 8)
        # Compare against last activity or current turn timestamp
        if state.last_activity:
            try:
                last_act_dt = datetime.fromisoformat(state.last_activity)
                last_act_ts = last_act_dt.timestamp()
                # If event timestamp significantly predates current active context (> 180s older)
                if event.timestamp < (last_act_ts - 180.0):
                    event.impact = GoalImpact.IRRELEVANT
                    event.relevance_reason = "Event timestamp is stale and predates active conversation context."
                    return GoalImpact.IRRELEVANT
            except Exception:
                pass

        # 4. Check for active goal, plan, task, or device context
        active_goal = state.current_goal
        active_task = state.active_task
        active_device = state.active_device
        goal_status = state.goal_status

        has_active_context = (
            goal_status in ("RUNNING", "WAITING_FOR_USER", "PENDING")
            or (active_task and active_task.get("status") in ("queued", "running", "pending"))
            or (active_device and active_device.get("status") in ("pairing_started", "connecting"))
            or state.pending_goal_continuation is not None
        )

        if not has_active_context:
            # No active goal awaiting completion
            if event.event_type in ("TASK_COMPLETED", "DEVICE_DISCONNECTED", "TASK_FAILED"):
                event.impact = GoalImpact.INFORMATIONAL
            else:
                event.impact = GoalImpact.IRRELEVANT
            return event.impact

        # 5. Entity-Specific Correlation

        # --- A. Task Management Correlation ---
        if event.entity_type == "task":
            target_task_id = str(active_task.get("task_id", "")).strip().lower() if active_task else ""
            event_task_id = str(event.entity_id).strip().lower()

            is_matching_task = False
            if target_task_id:
                is_matching_task = (target_task_id == event_task_id)
            elif active_goal and ("task" in (active_goal.get("description") or "").lower()):
                desc_low = (active_goal.get("description") or "").lower()
                is_matching_task = (event_task_id in desc_low or f"task {event_task_id}" in desc_low or "task" in desc_low)
            elif state.current_plan and hasattr(state.current_plan, "steps"):
                for stp in state.current_plan.steps:
                    if str(stp.parameters.get("task_id", "")).lower() == event_task_id or stp.intent.name == "TASK_MANAGEMENT":
                        is_matching_task = True
                        break

            if is_matching_task:
                if event.event_type == "TASK_COMPLETED":
                    event.impact = GoalImpact.GOAL_COMPLETED
                    event.correlated_goal_id = active_goal.get("id") if active_goal else target_task_id
                    state.goal_status = "COMPLETED"
                    if active_goal:
                        active_goal["status"] = "COMPLETED"
                    if active_task:
                        active_task["status"] = "completed"
                    if state.current_plan and hasattr(state.current_plan, "goal_status"):
                        state.current_plan.goal_status = "COMPLETED"
                        for stp in getattr(state.current_plan, "steps", []):
                            if str(stp.parameters.get("task_id", "")).lower() == event_task_id or stp.intent.name == "TASK_MANAGEMENT":
                                stp.status = "COMPLETED"
                    state.pending_goal_continuation = None
                    tname = event.details.get("task_name") or f"task {event.entity_id}"
                    event.message = f"Your task '{tname}' is complete."

                    # PHASE 8: Record Goal Outcome and close goal boundary
                    try:
                        from extensions.dialogue_state_manager import GoalOutcome
                        outcome = GoalOutcome(
                            goal_id=str(event.correlated_goal_id or event_task_id),
                            user_id=uid,
                            user_request=active_goal.get("description", f"Run task {event_task_id}") if active_goal else f"Run task {event_task_id}",
                            attempted_action=f"task_{event_task_id}",
                            actual_outcome="COMPLETED",
                            success=True,
                            summary=event.message,
                            timestamp=datetime.now().isoformat(),
                            entities={"task_id": event_task_id, "task_name": tname},
                            results={"status": "completed", "event": event.to_dict()},
                            verified=True,
                            verification_source="proactive_task_event",
                        )
                        dialogue_mgr.record_goal_outcome(outcome)
                    except Exception as err:
                        logger.warning("[PROACTIVE] Failed to record goal outcome: %s", err)

                    return GoalImpact.GOAL_COMPLETED

                elif event.event_type == "TASK_FAILED":
                    event.impact = GoalImpact.GOAL_BLOCKED
                    state.goal_status = "FAILED"
                    if active_goal:
                        active_goal["status"] = "FAILED"
                    if active_task:
                        active_task["status"] = "failed"
                    tname = event.details.get("task_name") or f"task {event.entity_id}"
                    event.message = f"Your task '{tname}' failed."

                    # PHASE 8: Record Goal Outcome and close goal boundary
                    try:
                        from extensions.dialogue_state_manager import GoalOutcome
                        outcome = GoalOutcome(
                            goal_id=str(active_goal.get("id", event_task_id)) if active_goal else event_task_id,
                            user_id=uid,
                            user_request=active_goal.get("description", f"Run task {event_task_id}") if active_goal else f"Run task {event_task_id}",
                            attempted_action=f"task_{event_task_id}",
                            actual_outcome="FAILED",
                            success=False,
                            summary=event.message,
                            timestamp=datetime.now().isoformat(),
                            entities={"task_id": event_task_id, "task_name": tname},
                            results={"status": "failed", "event": event.to_dict()},
                            failure_reason=event.message,
                            verified=True,
                            verification_source="proactive_task_event",
                        )
                        dialogue_mgr.record_goal_outcome(outcome)
                    except Exception as err:
                        logger.warning("[PROACTIVE] Failed to record goal outcome: %s", err)

                    return GoalImpact.GOAL_BLOCKED
            else:
                # Unrelated task: does not modify active goal, but is user-relevant info
                event.impact = GoalImpact.INFORMATIONAL
                return GoalImpact.INFORMATIONAL

        # --- B. Device Management Correlation ---
        if event.entity_type == "device":
            target_device_type = str(active_device.get("device_type", "")).strip().lower() if active_device else ""
            target_device_id = str(active_device.get("device_id", "")).strip().lower() if active_device else ""
            goal_desc = (active_goal.get("description") or "").lower() if active_goal else ""
            
            is_device_goal = bool(
                target_device_type or "phone" in goal_desc or "device" in goal_desc or
                (state.last_action and state.last_action.get("intent") == "DEVICE_CONTROL")
            )

            event_dev_name = str(event.details.get("device_name", "")).lower()
            event_dev_id = str(event.entity_id).lower()

            is_matching_device = False
            if is_device_goal:
                if target_device_id and target_device_id == event_dev_id:
                    is_matching_device = True
                elif (target_device_type == "phone" or "phone" in goal_desc) and ("phone" in event_dev_name or "phone" in event_dev_id or "mobile" in event_dev_name):
                    is_matching_device = True
                elif not target_device_id and target_device_type and (target_device_type in event_dev_name or target_device_type in event_dev_id):
                    is_matching_device = True

            if is_matching_device:
                if event.event_type == "DEVICE_CONNECTED":
                    event.impact = GoalImpact.GOAL_COMPLETED
                    state.goal_status = "COMPLETED"
                    if active_goal:
                        active_goal["status"] = "COMPLETED"
                    if active_device:
                        active_device["status"] = "connected"
                        active_device["device_id"] = event.entity_id
                    state.pending_goal_continuation = None
                    dname = event.details.get("device_name") or "phone"
                    event.message = f"Your {dname} is now connected."

                    # PHASE 8: Record Goal Outcome and close goal boundary
                    try:
                        from extensions.dialogue_state_manager import GoalOutcome
                        outcome = GoalOutcome(
                            goal_id=str(active_goal.get("id", "device_connection")) if active_goal else "device_connection",
                            user_id=uid,
                            user_request=active_goal.get("description", f"Connect {dname}") if active_goal else f"Connect {dname}",
                            attempted_action=f"connect_{dname}",
                            actual_outcome="COMPLETED",
                            success=True,
                            summary=event.message,
                            timestamp=datetime.now().isoformat(),
                            entities={"device_id": event.entity_id, "device_name": dname},
                            results={"status": "connected", "event": event.to_dict()},
                            verified=True,
                            verification_source="proactive_device_event",
                        )
                        dialogue_mgr.record_goal_outcome(outcome)
                    except Exception as err:
                        logger.warning("[PROACTIVE] Failed to record goal outcome: %s", err)

                    return GoalImpact.GOAL_COMPLETED

                elif event.event_type == "DEVICE_DISCONNECTED":
                    event.impact = GoalImpact.GOAL_BLOCKED
                    state.goal_status = "FAILED"
                    if active_goal:
                        active_goal["status"] = "FAILED"
                    if active_device:
                        active_device["status"] = "disconnected"
                    dname = event.details.get("device_name") or "phone"
                    event.message = f"The {dname} disconnected before connection could be completed."

                    # PHASE 8: Record Goal Outcome and close goal boundary
                    try:
                        from extensions.dialogue_state_manager import GoalOutcome
                        outcome = GoalOutcome(
                            goal_id=str(active_goal.get("id", "device_connection")) if active_goal else "device_connection",
                            user_id=uid,
                            user_request=active_goal.get("description", f"Connect {dname}") if active_goal else f"Connect {dname}",
                            attempted_action=f"connect_{dname}",
                            actual_outcome="FAILED",
                            success=False,
                            summary=event.message,
                            timestamp=datetime.now().isoformat(),
                            entities={"device_id": event.entity_id, "device_name": dname},
                            results={"status": "disconnected", "event": event.to_dict()},
                            blocking_reason=event.message,
                            verified=True,
                            verification_source="proactive_device_event",
                        )
                        dialogue_mgr.record_goal_outcome(outcome)
                    except Exception as err:
                        logger.warning("[PROACTIVE] Failed to record goal outcome: %s", err)

                    return GoalImpact.GOAL_BLOCKED
            else:
                # Unrelated device event
                if event.event_type == "DEVICE_DISCONNECTED":
                    # A paired device disconnecting is meaningful info to the user, though unrelated to current goal
                    event.impact = GoalImpact.INFORMATIONAL
                    return GoalImpact.INFORMATIONAL
                else:
                    # Unrelated device connecting (e.g. smart bulb while connecting phone) is suppressed
                    event.impact = GoalImpact.IRRELEVANT
                    return GoalImpact.IRRELEVANT

        # --- C. Application / Window Correlation ---
        if event.entity_type in ("application", "app", "window"):
            app_id = str(event.entity_id).strip().lower()
            goal_desc = (active_goal.get("description") or "").lower() if active_goal else ""

            matched_step = None
            if state.current_plan and hasattr(state.current_plan, "steps"):
                for stp in state.current_plan.steps:
                    stp_target = (stp.parameters.get("app_name") or stp.parameters.get("target") or "").lower()
                    if (app_id in stp_target or stp_target in app_id) and stp.status != "COMPLETED":
                        matched_step = stp
                        break

            if matched_step is not None:
                event.impact = GoalImpact.GOAL_PROGRESS
                matched_step.status = "COMPLETED"
                state.active_application = app_id
                event.correlated_step_index = getattr(matched_step, "sequence", None)
                event.message = f"{app_id.capitalize()} is now active."
                return GoalImpact.GOAL_PROGRESS
            elif app_id in goal_desc and goal_status in ("RUNNING", "PENDING"):
                event.impact = GoalImpact.GOAL_PROGRESS
                state.active_application = app_id
                event.message = f"{app_id.capitalize()} is now active."
                return GoalImpact.GOAL_PROGRESS
            else:
                event.impact = GoalImpact.IRRELEVANT
                return GoalImpact.IRRELEVANT

        # Default fallback
        event.impact = GoalImpact.IRRELEVANT
        return GoalImpact.IRRELEVANT

    @classmethod
    def provide_evidence_for_adaptation(
        cls,
        event: ProactiveEvent,
        user_id: str = "default",
        dialogue_mgr: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Provides proactive event and observation evidence to the existing Phase 3 adaptation mechanism.
        Uses _attempt_plan_adaptation from core.brain without creating a new adaptation engine.
        """
        uid = str(user_id)
        if dialogue_mgr is None:
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager
                dialogue_mgr = get_dialogue_manager(uid)
            except Exception:
                return None

        state = dialogue_mgr.current_state
        if not state.current_plan or not hasattr(state.current_plan, "steps"):
            return None

        plan = state.current_plan
        if getattr(plan, "adaptation_count", 0) >= getattr(plan, "max_adaptations", 2):
            return None

        active_step = None
        for step in plan.steps:
            if step.status in ("FAILED", "RUNNING", "PENDING"):
                active_step = step
                break

        if not active_step:
            return None

        obs = {
            "proactive_event": event.to_dict(),
            "observed_change": event.observed_change,
            "error": event.details.get("error") or event.observed_change,
        }

        try:
            from core.brain import _attempt_plan_adaptation
            step_input = active_step.parameters.get("target") or active_step.parameters.get("app_name") or str(active_step.intent.name)
            step_result = {"status": "error", "error": event.observed_change}
            adapted_res, adapted = _attempt_plan_adaptation(
                step=active_step,
                step_input=step_input,
                step_result=step_result,
                obs=obs,
                plan=plan,
                user_id=uid,
                dialogue_mgr=dialogue_mgr
            )
            if adapted:
                active_step.status = "COMPLETED"
                state.adaptation_count = getattr(plan, "adaptation_count", state.adaptation_count)
                state.adaptation_reason = getattr(plan, "adaptation_reason", state.adaptation_reason)
                state.adaptation_history = getattr(plan, "adaptation_history", state.adaptation_history)
                return adapted_res
        except Exception as exc:
            logger.warning("[PROACTIVE] Adaptation attempt exception: %s", exc)

        return None


# ============================================================================
# Proactive Observation Coordinator
# ============================================================================

class ProactiveObservationCoordinator:
    """
    Centralized coordinator for proactive environment observation.
    
    Responsibilities:
    - Runs periodic background observation of safe, lightweight categories.
    - Tracks baseline snapshots per user.
    - Detects meaningful state differences.
    - Manages deduplication, cooldowns, and debounce stability.
    - Inspects quiet/busy state (TTS speaking, user speaking, active goal).
    - Maintains an in-memory user-isolated event queue.
    - Surfaces notifications through existing response / TTS infrastructure.
    - Provides clean, safe lifecycle control (start / stop).
    """

    _instance: Optional[ProactiveObservationCoordinator] = None
    _lock = threading.RLock()

    def __init__(self, config: Optional[ProactiveObserverConfig] = None):
        self.config = config or ProactiveObserverConfig()
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # User-isolated state
        self._user_baselines: Dict[str, EnvironmentSnapshot] = {}
        self._event_history: Dict[str, float] = {}              # event_id -> last_surfaced_timestamp (for cooldown)
        self._pending_flaps: Dict[str, Tuple[str, float]] = {}  # entity_id -> (last_state, timestamp) (for debounce)
        self._event_queues: Dict[str, List[ProactiveEvent]] = {} # user_id -> List[ProactiveEvent]
        self._user_preference_overrides: Dict[str, bool] = {}   # user_id -> bool
        self._active_user_id: Optional[str] = None

        # Surfacing callback (e.g. TTS speak or UI notification)
        self._surface_callback: Optional[Callable[[ProactiveEvent], None]] = None

    @classmethod
    def get_instance(cls, config: Optional[ProactiveObserverConfig] = None) -> ProactiveObservationCoordinator:
        """Singleton accessor."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config=config)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for testing."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.stop()
                cls._instance = None

    def set_surface_callback(self, callback: Callable[[ProactiveEvent], None]) -> None:
        """Register a callback for surfacing events to user (e.g., TTS or UI)."""
        self._surface_callback = callback

    # ------------------------------------------------------------------------
    # User Preference & Enablement
    # ------------------------------------------------------------------------

    def is_enabled_for_user(self, user_id: str = "default") -> bool:
        """
        Check if proactive awareness is enabled for a given user.
        Checks in-memory overrides, PostgreSQL user preferences, and global config.
        """
        if not self.config.enabled:
            return False

        if user_id in self._user_preference_overrides:
            return self._user_preference_overrides[user_id]

        # Check existing user preferences in database if available
        try:
            from extensions.database_manager import get_db
            db = get_db()
            uid_int = int(user_id) if str(user_id).isdigit() else None
            if db and uid_int is not None:
                prefs = db.get_user_preferences(uid_int)
                val = prefs.get("proactive_awareness")
                if val is not None:
                    return str(val).lower() in ("true", "1", "yes", "on")
        except Exception:
            pass

        return True

    def set_user_preference(self, user_id: str, enabled: bool) -> None:
        """Update proactive awareness preference for a user."""
        self._user_preference_overrides[str(user_id)] = enabled
        try:
            from extensions.database_manager import get_db
            db = get_db()
            uid_int = int(user_id) if str(user_id).isdigit() else None
            if db and uid_int is not None:
                db.set_user_preference(uid_int, "proactive_awareness", "true" if enabled else "false")
        except Exception:
            pass


    # ------------------------------------------------------------------------
    # Quiet / Busy State Inspection
    # ------------------------------------------------------------------------

    def is_system_busy(self, user_id: str = "default") -> bool:
        """
        Determine whether the system is busy (assistant speaking, user speaking,
        or active goal executing) to prevent disruptive interruptions.
        """
        # 1. Check if assistant is currently speaking via TTS
        try:
            from extensions.system.tts_coordinator import tts_coordinator
            if tts_coordinator and tts_coordinator.is_speaking():
                return True
        except Exception:
            try:
                from legacy.tts import is_speaking
                if is_speaking():
                    return True
            except Exception:
                pass

        # 2. Check dialogue state manager for active goal execution or waiting state
        try:
            from extensions.dialogue_state_manager import get_dialogue_manager
            dm = get_dialogue_manager(str(user_id))
            if dm and dm.current_state:
                status = dm.current_state.goal_status
                if status in ("RUNNING", "WAITING_FOR_USER"):
                    return True
        except Exception:
            pass

        return False

    def is_cancelled(self, user_id: str = "default") -> bool:
        """Check if the user recently requested cancellation."""
        try:
            from extensions.dialogue_state_manager import get_dialogue_manager
            dm = get_dialogue_manager(str(user_id))
            if dm and dm.current_state:
                return dm.current_state.goal_status == "CANCELLED"
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------------
    # Deduplication, Cooldown, and Debounce
    # ------------------------------------------------------------------------

    def should_surface_event(self, event: ProactiveEvent) -> bool:
        """
        Check whether an event passes deduplication, cooldown, and debounce checks.
        """
        now = time.time()
        event_id = event.event_id

        # 1. Cooldown / Deduplication check
        last_surfaced = self._event_history.get(event_id, 0.0)
        if (now - last_surfaced) < self.config.cooldown_seconds:
            logger.debug("[PROACTIVE] Event '%s' in cooldown (%.1fs remaining)", event_id, self.config.cooldown_seconds - (now - last_surfaced))
            return False

        # 2. Debounce / Flap check (e.g. rapid ONLINE -> OFFLINE -> ONLINE)
        entity_key = f"{event.user_id}:{event.source_category}:{event.details.get('device_id') or event.details.get('task_id') or event.event_type}"
        last_state, state_time = self._pending_flaps.get(entity_key, ("", 0.0))
        current_transition = f"{event.before_state}->{event.after_state}"

        if (now - state_time) < self.config.debounce_seconds:
            if last_state and last_state != current_transition:
                logger.debug("[PROACTIVE] Rapid state flapping detected for '%s' — debouncing event", entity_key)
                self._pending_flaps[entity_key] = (current_transition, now)
                return False

        self._pending_flaps[entity_key] = (current_transition, now)
        return True

    def record_event_surfaced(self, event: ProactiveEvent) -> None:
        """Record that an event has been presented to the user."""
        self._event_history[event.event_id] = time.time()
        event.surfaced = True

    # ------------------------------------------------------------------------
    # Event Queuing & Draining
    # ------------------------------------------------------------------------

    def queue_event(self, event: ProactiveEvent) -> None:
        """Queue a proactive event when system is busy."""
        uid = event.user_id
        if uid not in self._event_queues:
            self._event_queues[uid] = []
        self._event_queues[uid].append(event)
        logger.info("[PROACTIVE] Queued event '%s' for user '%s' (system busy)", event.event_type, uid)

    def drain_queued_events(self, user_id: str = "default") -> List[ProactiveEvent]:
        """
        Retrieve and drain queued events for a user when system becomes available.
        Suppresses events if user cancelled or if event is no longer valid.
        """
        uid = str(user_id)
        if uid not in self._event_queues:
            return []

        if self.is_cancelled(uid):
            logger.info("[PROACTIVE] User '%s' is in CANCELLED state — clearing queued events", uid)
            self._event_queues[uid] = []
            return []

        ready_events: List[ProactiveEvent] = []
        remaining: List[ProactiveEvent] = []

        for evt in self._event_queues[uid]:
            if evt.impact == GoalImpact.IRRELEVANT:
                continue
            if not evt.surfaced and self.should_surface_event(evt):
                ready_events.append(evt)
            else:
                remaining.append(evt)

        self._event_queues[uid] = remaining
        return ready_events

    # ------------------------------------------------------------------------
    # Core Single-Tick Observation Cycle
    # ------------------------------------------------------------------------

    def tick_user(self, user_id: str = "default") -> List[ProactiveEvent]:
        """
        Perform a single observation step for a specific user.
        Captures snapshot, compares with user baseline, evaluates relevance,
        correlates with active goal, and either surfaces or queues the resulting events.
        
        Fail-safe: Catches any observer exception without interrupting assistant.
        """
        uid = str(user_id)
        if not self.is_enabled_for_user(uid):
            return []

        try:
            # Observe only safe lightweight categories
            current_snap = observe_environment(
                user_id=uid,
                relevant_categories=self.config.allowed_categories,
                explicit_clipboard=False,  # strictly prohibited in proactive
            )
        except Exception as exc:
            logger.warning("[PROACTIVE] Fail-safe: Observation failed for user '%s': %s", uid, exc)
            return []

        baseline = self._user_baselines.get(uid)
        if baseline is None:
            # First tick captures initial baseline
            self._user_baselines[uid] = current_snap
            return []

        try:
            diff = compare_snapshots(baseline, current_snap)
            self._user_baselines[uid] = current_snap

            if not diff.has_changes:
                return []

            # Retrieve active goal info if any
            active_goal = None
            dm = None
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager
                dm = get_dialogue_manager(uid)
                if dm and dm.current_state and dm.current_state.current_goal:
                    active_goal = dm.current_state.current_goal
            except Exception:
                pass

            raw_events = ProactiveEventDetector.detect_events(
                before=baseline,
                after=current_snap,
                state_diff=diff,
                user_id=uid,
                active_goal_info=active_goal,
            )

            surfaced_events: List[ProactiveEvent] = []
            for evt in raw_events:
                # Phase 7: Goal-Aware Proactive Reasoning
                GoalAwareEventReasoner.correlate_and_apply(evt, user_id=uid, dialogue_mgr=dm)

                # Suppress IRRELEVANT events
                if evt.impact == GoalImpact.IRRELEVANT:
                    logger.debug("[PROACTIVE] Suppressed IRRELEVANT event '%s'", evt.event_id)
                    continue

                if not self.should_surface_event(evt):
                    continue

                if self.is_cancelled(uid):
                    logger.debug("[PROACTIVE] Event suppressed due to user cancellation")
                    continue

                if self.is_system_busy(uid):
                    self.queue_event(evt)
                else:
                    self.record_event_surfaced(evt)
                    surfaced_events.append(evt)
                    self._dispatch_event(evt)

            return surfaced_events
        except Exception as exc:
            logger.warning("[PROACTIVE] Fail-safe: Error processing events for user '%s': %s", uid, exc)
            return []

    def _dispatch_event(self, event: ProactiveEvent) -> None:
        """Route event to registered surface callback or TTS coordinator."""
        if self._surface_callback:
            try:
                self._surface_callback(event)
                return
            except Exception as exc:
                logger.error("[PROACTIVE] Surface callback error: %s", exc)

        # Default dispatch to centralized TTS coordinator if available
        if event.message:
            try:
                from extensions.system.tts_coordinator import tts_coordinator, TTSPriority
                if tts_coordinator:
                    tts_coordinator.speak(event.message, priority=TTSPriority.PROACTIVE)
            except Exception:
                pass

    # ------------------------------------------------------------------------
    # Lifecycle Control (Thread Management & User Isolation)
    # ------------------------------------------------------------------------

    def start(self, active_user_id: str = "default") -> None:
        """Start the background proactive observation thread."""
        with self._lock:
            self._active_user_id = str(active_user_id)
            if self._running:
                logger.info("[PROACTIVE] Observation coordinator already running; updated active user to '%s'", self._active_user_id)
                return
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name="Assistant-ProactiveObserver"
            )
            self._thread.start()
            logger.info("[PROACTIVE] Observation loop started for user '%s' (interval=%.1fs)", self._active_user_id, self.config.interval)

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the background proactive observation thread cleanly."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None
        logger.info("[PROACTIVE] Observation loop stopped")

    def clear_user_state(self, user_id: str) -> None:
        """Clear all in-memory observation state for a user (called on logout/session reset)."""
        uid = str(user_id)
        with self._lock:
            self._user_baselines.pop(uid, None)
            self._event_queues.pop(uid, None)
            self._user_preference_overrides.pop(uid, None)
            self._event_history = {k: v for k, v in self._event_history.items() if not k.startswith(f"{uid.lower()}:")}
            self._pending_flaps = {k: v for k, v in self._pending_flaps.items() if not k.startswith(f"{uid.lower()}:")}
            logger.debug("[PROACTIVE] Cleared observation state for user '%s'", uid)

    def logout_user(self, user_id: Optional[str] = None) -> None:
        """Handle user logout: stops background worker and clears user-isolated observation state."""
        with self._lock:
            target_uid = str(user_id) if user_id is not None else getattr(self, "_active_user_id", None)
            self.stop()
            if target_uid:
                self.clear_user_state(target_uid)
            self._active_user_id = None
            logger.info("[PROACTIVE] User '%s' logged out and observation state cleared", target_uid)

    def _run_loop(self) -> None:
        """Background observation loop."""
        while not self._stop_event.is_set():
            active_uid = getattr(self, "_active_user_id", None)
            if active_uid:
                try:
                    self.tick_user(active_uid)
                except Exception as exc:
                    logger.warning("[PROACTIVE] Loop exception: %s", exc)

            # Controlled sleep using wait on stop event
            self._stop_event.wait(timeout=max(self.config.interval, 1.0))


# Global singleton instance accessor
proactive_coordinator = ProactiveObservationCoordinator.get_instance()
