"""
Level 6 — Proactive Intelligence & Anticipatory Assistance Engine

Canonical implementation of Friday's Level 6 Proactive Intelligence Layer.
Coordinates:
- Observation (EnvironmentObserver, StateDifference)
- Context & Dialogue (DialogueStateManager, ContextManager)
- User Activity State (IDLE, AVAILABLE, ACTIVELY_INTERACTING, BUSY, IN_CONVERSATION)
- Goal & Task Awareness (CURRENT_GOAL, ACTIVE_TASK, COMPLETED_GOAL, INTERRUPTED_GOAL, UNFINISHED_GOAL)
- Repeated Workflow Recognition
- Deadline & Reminder Context Correlation
- Safety Policy (DO_NOTHING, SUGGEST, ASK_PERMISSION, PREPARE, EXECUTE)
- Cooldown & Dismissal Lifecycle
- Observability with structured [PROACTIVE] logging

Integrates strictly with existing canonical planners, routers, and verifiers.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# Enums and Structured Data Models (Level 6 Specifications)
# ============================================================================

class UserActivityState(str, Enum):
    """Activity and interruption classification for the active user."""
    IDLE = "IDLE"                                   # User is away or has not interacted for a long period
    AVAILABLE = "AVAILABLE"                         # User is active/present, not busy, receptive to low-friction suggestions
    ACTIVELY_INTERACTING = "ACTIVELY_INTERACTING"   # User is speaking, typing, or currently interacting with assistant
    BUSY = "BUSY"                                   # User is in DND, active goal running, or focused on intense foreground work
    IN_CONVERSATION = "IN_CONVERSATION"             # A multi-turn conversation is actively in progress


class ProactiveDecisionType(str, Enum):
    """The canonical 5-tier proactive decision policy."""
    DO_NOTHING = "DO_NOTHING"                       # Default: insufficient evidence, busy user, low confidence, or noise
    SUGGEST = "SUGGEST"                             # Low-risk contextual suggestion, no destructive side effect
    ASK_PERMISSION = "ASK_PERMISSION"               # Action with meaningful external side-effects requires explicit permission
    PREPARE = "PREPARE"                             # Safe, reversible background preparation (gather context, draft checklist)
    EXECUTE = "EXECUTE"                             # Strictly authorized, pre-approved action execution


class ProactiveLifecycleState(str, Enum):
    """Lifecycle tracking for proactive events to prevent repetition and spam."""
    DETECTED = "DETECTED"
    EVALUATED = "EVALUATED"
    SUGGESTED = "SUGGESTED"
    ACCEPTED = "ACCEPTED"
    DISMISSED = "DISMISSED"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"


class GoalStage(str, Enum):
    """Goal and task state categories for proactive tracking."""
    CURRENT_GOAL = "CURRENT_GOAL"
    ACTIVE_TASK = "ACTIVE_TASK"
    COMPLETED_GOAL = "COMPLETED_GOAL"
    INTERRUPTED_GOAL = "INTERRUPTED_GOAL"
    UNFINISHED_GOAL = "UNFINISHED_GOAL"


@dataclass
class ProactiveDecision:
    """Structured proactive decision representation."""
    decision: ProactiveDecisionType
    reason: str
    confidence: float
    trigger: str
    related_goal: Optional[str] = None
    proposed_action: Optional[str] = None
    action_intent: Optional[str] = None
    action_parameters: Dict[str, Any] = field(default_factory=dict)
    required_confirmation: bool = False
    details: Dict[str, Any] = field(default_factory=dict)
    lifecycle_state: ProactiveLifecycleState = ProactiveLifecycleState.EVALUATED
    timestamp: float = field(default_factory=time.time)
    user_response: Optional[str] = None
    outcome: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if isinstance(self.decision, Enum):
            d["decision"] = self.decision.value
        if isinstance(self.lifecycle_state, Enum):
            d["lifecycle_state"] = self.lifecycle_state.value
        return d


# ============================================================================
# Canonical Proactive Intelligence Layer
# ============================================================================

class ProactiveIntelligenceEngine:
    """
    Single canonical engine responsible for proactive decision-making in Friday.
    Evaluates environment snapshots, dialogue state, active goals, reminders,
    and user activity, producing structured ProactiveDecisions.
    """

    _instance: Optional[ProactiveIntelligenceEngine] = None

    def __init__(self):
        # Cooldown & Dismissal tracking: user_id -> Dict[trigger_key, timestamp]
        self._suggestion_timestamps: Dict[str, Dict[str, float]] = {}
        # Dismissed triggers: user_id -> Set[trigger_key]
        self._dismissed_triggers: Dict[str, Set[str]] = {}
        # Workflow history: user_id -> List[List[str]] (sequences of opened apps)
        self._workflow_history: Dict[str, List[List[str]]] = {}
        # Active pending decisions: user_id -> ProactiveDecision
        self._active_decisions: Dict[str, ProactiveDecision] = {}

        # Default configuration
        self.min_confidence_threshold: float = 0.65
        self.suggestion_cooldown_seconds: float = 180.0     # 3 minutes between identical suggestions
        self.dismissal_cooldown_seconds: float = 3600.0     # 1 hour suppression for dismissed suggestions
        self.idle_timeout_seconds: float = 300.0            # 5 minutes idle threshold

    @classmethod
    def get_instance(cls) -> ProactiveIntelligenceEngine:
        """Singleton accessor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    # ------------------------------------------------------------------------
    # Step 9: User Activity / Interruption Awareness
    # ------------------------------------------------------------------------

    def classify_user_activity(self, user_id: str = "default") -> UserActivityState:
        """
        Classifies current user activity:
        IDLE | AVAILABLE | ACTIVELY_INTERACTING | BUSY | IN_CONVERSATION
        """
        uid = str(user_id)

        # 1. Check if assistant is speaking via TTS coordinator
        try:
            from extensions.system.tts_coordinator import tts_coordinator
            if tts_coordinator and tts_coordinator.is_speaking():
                return UserActivityState.BUSY
        except Exception:
            pass

        # 2. Check dialogue state manager for active execution or conversation turns
        try:
            from extensions.dialogue_state_manager import get_dialogue_manager
            dm = get_dialogue_manager(uid)
            if dm and dm.current_state:
                # Active execution in progress
                if getattr(dm.current_state, "execution_status", "idle") == "executing":
                    return UserActivityState.BUSY
                if getattr(dm.current_state, "goal_status", "IDLE") == "RUNNING":
                    cg = getattr(dm.current_state, "current_goal", None)
                    if isinstance(cg, dict) and cg.get("status") in ("NOT_STARTED", "IDLE", "PAUSED", "WAITING_FOR_USER"):
                        pass
                    else:
                        return UserActivityState.BUSY

                # Active turn recency
                now = time.time()
                last_turn_time = 0.0
                if dm.current_state.turns:
                    last_turn = dm.current_state.turns[-1]
                    try:
                        from datetime import datetime
                        last_turn_time = datetime.fromisoformat(last_turn.timestamp).timestamp()
                    except Exception:
                        last_turn_time = now

                time_since_turn = now - last_turn_time if last_turn_time > 0 else 999.0

                if time_since_turn < 10.0:
                    return UserActivityState.ACTIVELY_INTERACTING
                elif time_since_turn < 35.0:
                    return UserActivityState.IN_CONVERSATION
                elif time_since_turn > self.idle_timeout_seconds:
                    return UserActivityState.IDLE
        except Exception:
            pass

        return UserActivityState.AVAILABLE

    # ------------------------------------------------------------------------
    # Step 5: Insignificant Change / Noise Detection
    # ------------------------------------------------------------------------

    def is_noise_change(self, state_diff: Any) -> bool:
        """
        Determines if an observed state difference is trivial/noisy and should be ignored:
        CPU fluctuations, volume changes, brightness changes, minor window title changes.
        """
        if not state_diff or not getattr(state_diff, "has_changes", False):
            return False

        changes = set(getattr(state_diff, "changes", []))
        if not changes:
            return False

        # Trivial noise categories
        noise_changes = {
            "VOLUME_CHANGED",
            "BRIGHTNESS_CHANGED",
            "MUTED_CHANGED",
            "CAPS_LOCK_CHANGED",
            "NUM_LOCK_CHANGED",
            "SCROLL_LOCK_CHANGED",
            "CPU_CHANGED",
            "MEMORY_CHANGED",
        }

        # If all observed changes belong to the noise set, suppress completely
        if changes.issubset(noise_changes):
            return True

        # Routine window title change check
        if changes == {"ACTIVE_WINDOW_CHANGED"}:
            details = getattr(state_diff, "details", {}).get("active_window", {})
            b_title = str(details.get("before", "")).lower()
            a_title = str(details.get("after", "")).lower()
            # Minor browser tab changes or clock ticks without application switch
            if b_title and a_title:
                b_words = set(b_title.split())
                a_words = set(a_title.split())
                overlap = len(b_words.intersection(a_words))
                if overlap >= max(len(b_words), len(a_words)) * 0.7:
                    return True

        return False

    # ------------------------------------------------------------------------
    # Step 10: Suggestion Cooldown & Dismissal Tracking
    # ------------------------------------------------------------------------

    def is_in_cooldown_or_dismissed(self, trigger_key: str, user_id: str = "default") -> Tuple[bool, str]:
        """
        Checks if a trigger is in active cooldown or was previously dismissed by user.
        """
        uid = str(user_id)
        now = time.time()

        # 1. Dismissal check
        user_dismissed = self._dismissed_triggers.get(uid, set())
        if trigger_key in user_dismissed:
            return True, f"Suggestion '{trigger_key}' was dismissed by user"

        # 2. Cooldown check
        user_timestamps = self._suggestion_timestamps.get(uid, {})
        last_time = user_timestamps.get(trigger_key, 0.0)
        elapsed = now - last_time
        if elapsed < self.suggestion_cooldown_seconds:
            return True, f"Suggestion '{trigger_key}' in cooldown ({self.suggestion_cooldown_seconds - elapsed:.1f}s remaining)"

        return False, ""

    def record_suggestion_surfaced(self, decision: ProactiveDecision, user_id: str = "default") -> None:
        """Records that a suggestion was presented to user."""
        uid = str(user_id)
        if uid not in self._suggestion_timestamps:
            self._suggestion_timestamps[uid] = {}
        self._suggestion_timestamps[uid][decision.trigger] = time.time()
        decision.lifecycle_state = ProactiveLifecycleState.SUGGESTED
        self._active_decisions[uid] = decision

    def record_user_response(self, user_id: str, affirmative: bool, raw_input: str = "") -> Optional[ProactiveDecision]:
        """
        Integrates user response ("yes", "no", "not now", "stop suggesting this").
        """
        uid = str(user_id)
        active = self._active_decisions.get(uid)
        if not active:
            return None

        active.user_response = raw_input
        if affirmative:
            active.lifecycle_state = ProactiveLifecycleState.ACCEPTED
            active.outcome = "ACCEPTED"
            self._log_decision(active, f"User accepted proactive suggestion: '{raw_input}'")
            self._active_decisions.pop(uid, None)
            return active
        else:
            active.lifecycle_state = ProactiveLifecycleState.DISMISSED
            active.outcome = "DISMISSED"
            if uid not in self._dismissed_triggers:
                self._dismissed_triggers[uid] = set()
            self._dismissed_triggers[uid].add(active.trigger)
            self._log_decision(active, f"User dismissed proactive suggestion: '{raw_input}'")
            self._active_decisions.pop(uid, None)
            return active

    # ------------------------------------------------------------------------
    # Step 7: Repeated Workflow Recognition
    # ------------------------------------------------------------------------

    def record_workflow_action(self, action_type: str, target: str, user_id: str = "default") -> None:
        """Records an app launch or tool action for workflow pattern detection."""
        uid = str(user_id)
        if uid not in self._workflow_history:
            self._workflow_history[uid] = []

        clean_tgt = str(target).strip().capitalize()
        if not clean_tgt or clean_tgt in ("None", "Both", "Them"):
            return

        history = self._workflow_history[uid]
        if not history:
            history.append([clean_tgt])
        else:
            current_seq = history[-1]
            if clean_tgt in current_seq:
                history.append([clean_tgt])
            elif len(current_seq) < 4:
                current_seq.append(clean_tgt)
            else:
                history.append([clean_tgt])

        # Keep history bounded
        if len(history) > 20:
            self._workflow_history[uid] = history[-20:]

    def detect_repeated_workflow(self, user_id: str = "default") -> Optional[List[str]]:
        """
        Inspects workflow history for repeated sequence patterns of apps (>= 2 times).
        """
        uid = str(user_id)
        history = self._workflow_history.get(uid, [])
        if len(history) < 2:
            return None

        # Compare last sequence with previous sequences
        latest = history[-1]
        if len(latest) < 2:
            return None

        latest_set = set(latest)
        count = 0
        for seq in history[:-1]:
            if set(seq) == latest_set:
                count += 1

        if count >= 1:  # Appears at least twice total
            return sorted(list(latest_set))
        return None

    # ------------------------------------------------------------------------
    # Step 8: Deadline / Reminder Context Integration
    # ------------------------------------------------------------------------

    def find_relevant_upcoming_reminder(
        self,
        active_apps: List[str],
        active_goal_desc: str = "",
        user_id: str = "default"
    ) -> Optional[Dict[str, Any]]:
        """
        Finds pending reminders relevant to current environment or goal.
        Returns reminder dict only if a contextual semantic relationship exists.
        If no connection exists, returns None (enforces DO_NOTHING).
        """
        uid = str(user_id)
        reminders = []
        try:
            from extensions.reminder_engine.reminder_scheduler import get_scheduler
            sched = get_scheduler()
            if sched:
                with sched._lock:
                    reminders = [dict(r) for r in sched.reminders if not r.get("triggered")]
        except Exception:
            pass

        if not reminders:
            try:
                from extensions.database_manager import get_db
                db = get_db()
                if db:
                    reminders = db.get_pending_reminders(int(uid) if uid.isdigit() else 1)
            except Exception:
                pass

        if not reminders:
            return None

        # Determine context keywords from active apps, goal description
        context_keywords: Set[str] = set()
        for a in active_apps:
            a_low = a.lower()
            context_keywords.add(a_low)
            if "code" in a_low or "vs" in a_low or "py" in a_low:
                context_keywords.update(["project", "code", "development", "presentation", "demo"])
            elif "powerpoint" in a_low or "ppt" in a_low or "slides" in a_low:
                context_keywords.update(["presentation", "slides", "meeting", "demo"])
            elif "word" in a_low or "doc" in a_low or "notepad" in a_low:
                context_keywords.update(["document", "notes", "report", "summary", "meeting"])

        if active_goal_desc:
            words = [w for w in re.split(r'[^a-zA-Z0-9]', active_goal_desc.lower()) if len(w) > 3]
            context_keywords.update(words)

        # Check reminders for overlap
        for rem in reminders:
            rem_text = str(rem.get("task_text") or rem.get("text", "")).lower()
            rem_words = [w for w in re.split(r'[^a-zA-Z0-9]', rem_text) if len(w) > 3]
            matches = [w for w in rem_words if w in context_keywords or any(k in w or w in k for k in context_keywords)]
            if len(matches) >= 1:
                return rem

        return None

    # ------------------------------------------------------------------------
    # Step 6: Active Goal & Unfinished Goal Detection
    # ------------------------------------------------------------------------

    def find_unfinished_goal(self, user_id: str = "default", active_apps: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Inspects dialogue state and PostgreSQL persistence for unfinished goals.
        Only returns persistent goals if context makes continuation relevant (Step 6).
        """
        uid = str(user_id)
        try:
            from extensions.dialogue_state_manager import get_dialogue_manager
            dm = get_dialogue_manager(uid)
            if dm and dm.current_state:
                # 1. In-memory current_goal in dialogue state
                if dm.current_state.current_goal:
                    c_goal = dm.current_state.current_goal
                    status = c_goal.get("status") or dm.current_state.goal_status
                    if status not in ("COMPLETED", "CANCELLED"):
                        return {
                            "goal_id": c_goal.get("id") or c_goal.get("goal_id", "current_unfinished"),
                            "original_request": c_goal.get("description") or c_goal.get("user_request") or "unfinished task",
                            "description": c_goal.get("description") or c_goal.get("goal_name") or "unfinished task",
                            "topic": c_goal.get("topic"),
                            "deadline": c_goal.get("deadline"),
                            "status": status,
                            "requirements": c_goal.get("requirements", []),
                            "goal_subject": c_goal.get("goal_subject", ""),
                            "goal_verb": c_goal.get("goal_verb", ""),
                            "raw_goal": c_goal,
                        }

                # 2. In-memory pending resumption
                resumption = getattr(dm.current_state, "pending_goal_resumption", None)
                if resumption and resumption.get("goals"):
                    return resumption["goals"][0]

                # 3. Pending goal continuation
                cont = getattr(dm.current_state, "pending_goal_continuation", None)
                if cont and dm.current_state.goal_status in ("WAITING_FOR_USER", "BLOCKED"):
                    return {
                        "goal_id": "pending_continuation",
                        "original_request": cont.get("raw_input") or "unfinished goal",
                        "description": cont.get("raw_input") or "unfinished goal",
                        "status": dm.current_state.goal_status
                    }

                # 4. Persistent goals from DB: only if context makes continuation relevant
                from extensions.database_manager import get_db
                db = get_db()
                if db and active_apps:
                    goals = db.get_persistent_goals(int(uid) if uid.isdigit() else 1, only_resumable=True)
                    if goals:
                        context_keywords = set()
                        for a in active_apps:
                            context_keywords.update(re.findall(r'[a-zA-Z0-9]{3,}', a.lower()))
                        for g in goals:
                            req_text = str(g.get("user_request") or g.get("description") or "").lower()
                            words = set(re.findall(r'[a-zA-Z0-9]{3,}', req_text))
                            if words.intersection(context_keywords):
                                return g
        except Exception:
            pass

        return None

    # ------------------------------------------------------------------------
    # Main Decision Engine (Steps 3, 4, 12, 14)
    # ------------------------------------------------------------------------

    def evaluate_situation(
        self,
        current_snapshot: Any,
        previous_snapshot: Optional[Any] = None,
        state_difference: Optional[Any] = None,
        user_id: str = "default",
        force_available: bool = False
    ) -> ProactiveDecision:
        """
        Canonical Level 6 evaluation pipeline:
        Environment Observer
        ↓
        Unified State / Context
        ↓
        State Difference / Change Detector
        ↓
        Active Goals + User Context
        ↓
        PROACTIVE INTELLIGENCE
        ↓
        Decision: DO_NOTHING | SUGGEST | ASK_PERMISSION | PREPARE | EXECUTE
        """
        uid = str(user_id)

        # ── 1. User Activity Check (Step 9) ──
        activity = UserActivityState.AVAILABLE if force_available else self.classify_user_activity(uid)
        if activity in (UserActivityState.BUSY, UserActivityState.ACTIVELY_INTERACTING, UserActivityState.IN_CONVERSATION):
            dec = ProactiveDecision(
                decision=ProactiveDecisionType.DO_NOTHING,
                reason=f"User is currently {activity.value}; proactive interruption suppressed",
                confidence=0.95,
                trigger="user_activity_guard",
                details={"activity": activity.value}
            )
            self._log_decision(dec)
            return dec

        # ── 2. Insignificant Change / Noise Check (Step 5) ──
        if state_difference is not None and self.is_noise_change(state_difference):
            dec = ProactiveDecision(
                decision=ProactiveDecisionType.DO_NOTHING,
                reason="Observed environment change is insignificant or noise (volume/keys/minor window change)",
                confidence=0.90,
                trigger="noise_filter"
            )
            self._log_decision(dec)
            return dec

        # ── 3. Meaningful External Event from ProactiveObserver (Step 5) ──
        if state_difference is not None and getattr(state_difference, "has_changes", False):
            changes = getattr(state_difference, "changes", [])
            if "TASK_COMPLETED" in changes or "TASK_FAILED" in changes:
                dec = ProactiveDecision(
                    decision=ProactiveDecisionType.SUGGEST,
                    reason="Background task reached completion or failure state",
                    confidence=0.92,
                    trigger="task_state_change",
                    details={"changes": changes}
                )
                self._log_decision(dec)
                return dec

        # Extract active context
        active_apps = []
        if current_snapshot:
            if hasattr(current_snapshot, "active_application") and current_snapshot.active_application:
                active_apps.append(current_snapshot.active_application)
            if hasattr(current_snapshot, "open_windows"):
                for w in current_snapshot.open_windows or []:
                    t = w.get("title", "")
                    if t:
                        active_apps.append(t)

        try:
            from extensions.dialogue_state_manager import get_dialogue_manager
            dm = get_dialogue_manager(uid)
            if dm and dm.current_state:
                if dm.current_state.active_application:
                    active_apps.append(dm.current_state.active_application)
                active_apps.extend(dm.current_state.active_applications)
        except Exception:
            dm = None

        goal_desc = (dm.current_state.current_goal.get("description") if (dm and dm.current_state.current_goal) else "") or ""

        # ── 4. Upcoming Reminder / Deadline Context Correlation (Step 8) ──
        relevant_reminder = self.find_relevant_upcoming_reminder(active_apps, goal_desc, uid)
        if relevant_reminder:
            rem_id = str(relevant_reminder.get("id", "reminder"))
            rem_text = str(relevant_reminder.get("task_text") or relevant_reminder.get("text", "upcoming event"))
            trigger_key = f"reminder_context_{rem_id}"

            in_cooldown, reason = self.is_in_cooldown_or_dismissed(trigger_key, uid)
            if not in_cooldown:
                prompt = f"You have your {rem_text}, and you're currently working on the project. Would you like me to prepare a quick presentation checklist?"
                dec = ProactiveDecision(
                    decision=ProactiveDecisionType.SUGGEST,
                    reason="Upcoming deadline is directly relevant to active project tools in environment",
                    confidence=0.88,
                    trigger=trigger_key,
                    related_goal=rem_text,
                    proposed_action="create report.txt and final.txt",  # Concrete preparation action
                    action_intent="FILE_OPERATIONS",
                    action_parameters={"action": "create_file", "files": ["presentation_checklist.txt"]},
                    required_confirmation=True,
                    details={"prompt": prompt, "reminder": relevant_reminder}
                )
                self.record_suggestion_surfaced(dec, uid)
                self._log_decision(dec)
                return dec

        # ── 5. Repeated Workflow Recognition (Step 7) ──
        repeated_apps = self.detect_repeated_workflow(uid)
        if repeated_apps and len(repeated_apps) >= 2:
            trigger_key = f"workflow_pattern_{'_'.join(repeated_apps).lower()}"
            in_cooldown, reason = self.is_in_cooldown_or_dismissed(trigger_key, uid)
            if not in_cooldown:
                app_list_str = ", ".join(repeated_apps)
                prompt = f"I've noticed you repeatedly open the same set of tools ({app_list_str}) for this project. Would you like me to create a quick-start workflow?"
                dec = ProactiveDecision(
                    decision=ProactiveDecisionType.SUGGEST,
                    reason=f"Repeated workflow pattern detected across sessions for: {app_list_str}",
                    confidence=0.82,
                    trigger=trigger_key,
                    related_goal="quick_start_workflow",
                    proposed_action=f"open {' and '.join(repeated_apps)}",
                    action_intent="OPEN_APPLICATION",
                    action_parameters={"apps": repeated_apps},
                    required_confirmation=True,
                    details={"prompt": prompt, "apps": repeated_apps}
                )
                self.record_suggestion_surfaced(dec, uid)
                self._log_decision(dec)
                return dec

        # ── 6. Unfinished / Interrupted Goal Evaluation (Step 6) ──
        unfinished = self.find_unfinished_goal(uid, active_apps=active_apps)
        if unfinished:
            gid = str(unfinished.get("goal_id", "unfinished_task"))
            raw_g = unfinished.get("raw_goal") or {}
            desc = str(unfinished.get("description") or unfinished.get("original_request") or "unfinished task")
            topic = unfinished.get("topic")
            deadline = unfinished.get("deadline")

            # Section 1 & 2: Reconstruct WorkGoal to inspect actual progress, deliverables, and subtasks
            from core.goal_planner import WorkGoal
            wg = WorkGoal.from_dict(raw_g) if raw_g else None

            deliverables = wg.deliverables if wg else raw_g.get("deliverables", [])
            pending_delivs = [d for d in deliverables if d.get("status") == "PENDING"]
            # File-backed completed deliverables (excludes PLAN entries with no real file artifact)
            completed_delivs = [d for d in deliverables if d.get("status") == "COMPLETED" and d.get("file_path")]
            # all_delivs_done requires: no pending deliverables AND at least one real file artifact exists
            # This prevents a fresh goal (only PLAN entry, no actual PPT/PDF) from being wrongly
            # classified as "artifacts ready" before anything has been generated.
            all_delivs_done = (len(completed_delivs) > 0 and len(pending_delivs) == 0)

            subtasks = wg.subtasks if wg else raw_g.get("subtasks", [])
            has_pending_review = any(
                st.get("status") != "COMPLETED" and any(k in st.get("title", "").lower() for k in ["review", "check", "verify"])
                for st in subtasks
            )

            is_ready_for_submission = (
                (wg and wg.status == "READY_FOR_SUBMISSION")
                or (all_delivs_done and not has_pending_review)
            )

            if is_ready_for_submission:
                # All executable tasks done; remaining step is user submission
                trigger_key = f"submission_ready_{gid}"
                in_cooldown, _ = self.is_in_cooldown_or_dismissed(trigger_key, uid)
                if not in_cooldown:
                    prompt = f"Your {topic or 'project'} deliverables and review are complete. The remaining step is submission."
                    proposed_cmd = "finish everything"
                    dec = ProactiveDecision(
                        decision=ProactiveDecisionType.SUGGEST,
                        reason="All executable tasks complete; submission ready",
                        confidence=0.85,
                        trigger=trigger_key,
                        related_goal=gid,
                        proposed_action=proposed_cmd,
                        action_intent="GOAL_MANAGEMENT",
                        action_parameters={"action": "submission_ready", "topic": topic, "goal_id": gid},
                        required_confirmation=True,
                        details={"prompt": prompt, "goal": unfinished}
                    )
                    self.record_suggestion_surfaced(dec, uid)
                    self._log_decision(dec)
                    return dec

            elif all_delivs_done:
                # Deliverables exist & are verified; review remains
                # Section 1 & 2: DO NOT suggest creating what already exists!
                trigger_key = f"review_goal_{gid}"
                in_cooldown, _ = self.is_in_cooldown_or_dismissed(trigger_key, uid)
                if not in_cooldown:
                    doc_kind = "presentation" if any(d.get("type") == "PPT" for d in completed_delivs) else ("report" if any(d.get("type") == "DOCX" for d in completed_delivs) else "document")
                    prompt = f"Your {topic} {doc_kind} is ready. The remaining step is your final review. Do you want me to review it?"
                    proposed_cmd = f"review {topic} {doc_kind}"
                    dec = ProactiveDecision(
                        decision=ProactiveDecisionType.SUGGEST,
                        reason="Deliverable verified; review remaining",
                        confidence=0.90,
                        trigger=trigger_key,
                        related_goal=gid,
                        proposed_action=proposed_cmd,
                        action_intent="GOAL_MANAGEMENT",
                        action_parameters={"action": "review_deliverable", "topic": topic, "goal_id": gid},
                        required_confirmation=True,
                        details={"prompt": prompt, "goal": unfinished}
                    )
                    self.record_suggestion_surfaced(dec, uid)
                    self._log_decision(dec)
                    return dec

            else:
                # Deliverables NOT yet created -> suggest creating the first pending deliverable
                trigger_key = f"unfinished_goal_{gid}"
                in_cooldown, reason = self.is_in_cooldown_or_dismissed(trigger_key, uid)
                if not in_cooldown:
                    clean_desc = re.sub(r'^(?:prepare|work\s+on|finish|complete)\s+', '', desc, flags=re.IGNORECASE).strip()
                    if not clean_desc:
                        clean_desc = desc

                    next_deliv_type = pending_delivs[0].get("type", "PPT") if pending_delivs else ("PPT" if "presentation" in desc.lower() else "DOCX")

                    if topic and deadline:
                        if next_deliv_type == "PPT" or "presentation" in desc.lower():
                            prompt = f"You still have your {topic} presentation to finish for {deadline}. Do you want me to create the PPT?"
                            proposed_cmd = f"create presentation on {topic}"
                        elif next_deliv_type in ("DOCX", "PDF") or "report" in desc.lower():
                            prompt = f"Your {topic} report is pending for {deadline}. Shall I create it?"
                            proposed_cmd = f"create a report on {topic}"
                        else:
                            prompt = f"You still have your {topic} task to finish for {deadline}. Shall I continue from where you stopped?"
                            proposed_cmd = f"continue"
                    elif topic:
                        if next_deliv_type == "PPT" or "presentation" in desc.lower():
                            prompt = f"You haven't created the {topic} presentation yet. I can create it."
                            proposed_cmd = f"create presentation on {topic}"
                        else:
                            prompt = f"You haven't completed the {topic} task yet. I can continue from where you stopped."
                            proposed_cmd = f"continue"
                    elif deadline:
                        prompt = f"You have an unfinished {clean_desc} due {deadline}. Would you like me to help start working on it?"
                        proposed_cmd = f"create presentation" if "presentation" in desc.lower() else f"resume goal {gid}"
                    else:
                        prompt = f"You still have the {desc} task unfinished. Would you like to continue?"
                        proposed_cmd = f"resume goal {gid}"

                    dec = ProactiveDecision(
                        decision=ProactiveDecisionType.SUGGEST,
                        reason="Unfinished active goal in dialogue state and user is available",
                        confidence=0.88,
                        trigger=trigger_key,
                        related_goal=gid,
                        proposed_action=proposed_cmd,
                        action_intent="DOCUMENT_GENERATION" if ("presentation" in desc.lower() or next_deliv_type == "PPT") else "GOAL_MANAGEMENT",
                        action_parameters={"action": "create_presentation" if next_deliv_type == "PPT" else "resume_goal", "topic": topic, "goal_id": gid},
                        required_confirmation=True,
                        details={"prompt": prompt, "goal": unfinished}
                    )
                    self.record_suggestion_surfaced(dec, uid)
                    self._log_decision(dec)
                    return dec

        # ── 7. Safe Proactive Preparation (PREPARE) Check (Step 12) ──
        # If user is in an active workspace and files can be non-destructively pre-indexed
        if dm and dm.current_state and getattr(dm.current_state, "active_folder", None):
            fld = dm.current_state.active_folder.get("path") if isinstance(dm.current_state.active_folder, dict) else str(dm.current_state.active_folder)
            if fld and os.path.exists(fld):
                trigger_key = f"prepare_folder_index_{os.path.basename(fld)}"
                in_cooldown, _ = self.is_in_cooldown_or_dismissed(trigger_key, uid)
                if not in_cooldown:
                    dec = ProactiveDecision(
                        decision=ProactiveDecisionType.PREPARE,
                        reason=f"Non-destructive preparation: scanning active folder '{os.path.basename(fld)}' context",
                        confidence=0.80,
                        trigger=trigger_key,
                        proposed_action=f"scan_folder_context {fld}",
                        required_confirmation=False,
                        details={"folder": fld, "prepared": True}
                    )
                    self.record_suggestion_surfaced(dec, uid)
                    self._log_decision(dec)
                    return dec

        # ── 8. Default Safe Policy: DO_NOTHING ──
        dec = ProactiveDecision(
            decision=ProactiveDecisionType.DO_NOTHING,
            reason="No actionable, high-confidence proactive opportunity with clear user benefit detected",
            confidence=0.90,
            trigger="default_policy"
        )
        return dec

    # ------------------------------------------------------------------------
    # Step 14: Structured Observability Logging
    # ------------------------------------------------------------------------

    def _log_decision(self, decision: ProactiveDecision, context_note: str = "") -> None:
        """Emits structured [PROACTIVE] log according to Step 14."""
        if decision.decision == ProactiveDecisionType.DO_NOTHING:
            if decision.trigger == "default_policy":
                return  # Suppress default idle noise from console
            # Suppress repeated identical DO_NOTHING evaluations (e.g. user_activity_guard, noise_filter)
            last_suppressed = getattr(self, "_last_suppressed_decisions", {})
            last_key = (decision.trigger, decision.reason)
            if last_suppressed.get(decision.trigger) == last_key:
                return  # Suppress identical repeated DO_NOTHING decisions; log only on transition
            if not hasattr(self, "_last_suppressed_decisions"):
                self._last_suppressed_decisions = {}
            self._last_suppressed_decisions[decision.trigger] = last_key
        else:
            if hasattr(self, "_last_suppressed_decisions"):
                self._last_suppressed_decisions.clear()

        log_lines = [
            "[PROACTIVE]",
            f"Trigger:            {decision.trigger}",
            f"Context:            {context_note or 'Environment & Dialogue State'}",
            f"Detected situation: {decision.reason}",
            f"Decision:           {decision.decision.value}",
            f"Confidence:         {decision.confidence:.2f}",
            f"Reason:             {decision.reason}",
            f"Action:             {decision.proposed_action or 'None'}",
            f"User response:      {decision.user_response or 'Pending / None'}",
            f"Outcome:            {decision.outcome or decision.lifecycle_state.value}",
        ]
        formatted = "\n".join(log_lines)
        print(formatted)
        logger.info(formatted)


# Global singleton instance
proactive_intelligence = ProactiveIntelligenceEngine.get_instance()
