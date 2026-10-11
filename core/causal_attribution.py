"""
Causal State Attribution Engine (PHASE 10)
Connects user actions, execution records, and environment state transitions
into an authoritative causal attribution model.

Prevents invented causality: uses conservative matching rules and explicit evidence.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("CausalAttribution")


class CausalRelationship(str, Enum):
    CAUSED = "CAUSED"
    LIKELY_CAUSED = "LIKELY_CAUSED"
    OBSERVED_AFTER = "OBSERVED_AFTER"
    NOT_CAUSALLY_RELATED = "NOT_CAUSALLY_RELATED"


@dataclass
class CausalEvent:
    causal_id: str
    user_id: int
    cause_action_id: Optional[str]
    task_id: Optional[str]
    effect_transition_id: Optional[int]
    event_type: str
    relationship: CausalRelationship
    confidence: float
    cause_description: str
    effect_summary: str
    previous_state: Dict[str, Any] = field(default_factory=dict)
    new_state: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["relationship"] = self.relationship.value
        return d


class CausalAttributionEngine:
    """
    Evaluates observed environment changes against recent actions
    and establishes verifiable causal connections.
    """

    def __init__(self):
        self._in_memory_events: List[CausalEvent] = []

    def attribute_action_outcome(
        self,
        action_record_id: Optional[str],
        user_id: int,
        action_type: str,
        target: Optional[str],
        before_state: Optional[Dict[str, Any]],
        after_state: Optional[Dict[str, Any]],
        state_difference: Optional[Dict[str, Any]],
        task_id: Optional[str] = None,
        transition_id: Optional[int] = None,
    ) -> Optional[CausalEvent]:
        """
        Conservatively determines if state differences were CAUSED by the executed action.
        """
        if not state_difference:
            return None

        has_changes = state_difference.get("has_changes", False)
        changes = state_difference.get("changes", [])
        if not has_changes and not changes:
            return None

        act_clean = (action_type or "").upper().strip()
        target_clean = (target or "").lower().strip()
        details = state_difference.get("details", {})
        diff_summary = state_difference.get("meaningful_summary", "")

        relationship = CausalRelationship.OBSERVED_AFTER
        confidence = 0.5
        event_type = "ENVIRONMENT_OBSERVATION"
        evidence: Dict[str, Any] = {
            "action_type": act_clean,
            "target": target_clean,
            "detected_changes": changes,
            "details": details,
        }

        # 1. Application Launch / Focus
        if "APPLICATION_CHANGED" in changes or "ACTIVE_WINDOW_CHANGED" in changes:
            after_app = str(after_state.get("application", "") if after_state else "").lower()
            after_title = str(after_state.get("window_title", "") if after_state else "").lower()

            if act_clean in ("OPEN_APPLICATION", "START_PROCESS", "FOCUS_WINDOW", "APPLICATION"):
                if target_clean and (target_clean in after_app or target_clean in after_title):
                    relationship = CausalRelationship.CAUSED
                    confidence = 0.98
                    event_type = "APPLICATION_LAUNCHED"
                else:
                    relationship = CausalRelationship.LIKELY_CAUSED
                    confidence = 0.80
                    event_type = "APPLICATION_SWITCHED"

        # 2. File Operations
        elif any("FILE" in c for c in changes) or act_clean in ("CREATE_FILE", "WRITE_FILE", "DELETE_FILE", "MOVE_FILE"):
            if act_clean == "CREATE_FILE" or act_clean == "WRITE_FILE":
                relationship = CausalRelationship.CAUSED
                confidence = 0.95
                event_type = "FILE_MUTATED"
            elif act_clean == "DELETE_FILE":
                relationship = CausalRelationship.CAUSED
                confidence = 0.98
                event_type = "FILE_DELETED"

        # 3. Media / Browser Playback
        elif "MEDIA" in act_clean or "PLAY" in act_clean or "VIDEO" in act_clean:
            relationship = CausalRelationship.CAUSED
            confidence = 0.92
            event_type = "MEDIA_PLAYBACK_CHANGED"

        # 4. Background Task Lifecycle
        elif "TASK_STARTED" in changes or "TASK_COMPLETED" in changes or act_clean in ("CONCURRENT_TASK", "TASK_EXECUTION"):
            relationship = CausalRelationship.CAUSED
            confidence = 0.99
            event_type = "TASK_STATE_CHANGED"

        cause_desc = f"Action '{action_type}' targeting '{target or 'system'}'"
        effect_desc = diff_summary or f"Environment state change: {', '.join(changes)}"

        event = CausalEvent(
            causal_id=f"causal_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            cause_action_id=action_record_id,
            task_id=task_id,
            effect_transition_id=transition_id,
            event_type=event_type,
            relationship=relationship,
            confidence=confidence,
            cause_description=cause_desc,
            effect_summary=effect_desc,
            previous_state=before_state or {},
            new_state=after_state or {},
            evidence=evidence,
            created_at=time.time(),
        )

        self._in_memory_events.append(event)
        self._persist_causal_event(event)
        return event

    def _persist_causal_event(self, event: CausalEvent) -> None:
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    actual_action_id = None
                    if event.cause_action_id:
                        try:
                            cur.execute("SELECT 1 FROM action_records WHERE action_id = %s LIMIT 1;", (event.cause_action_id,))
                            if cur.fetchone():
                                actual_action_id = event.cause_action_id
                        except Exception:
                            pass

                    cur.execute("""
                        INSERT INTO causal_state_events (
                            causal_id, user_id, cause_action_id, task_id,
                            effect_transition_id, event_type, relationship,
                            confidence, cause_description, effect_summary,
                            previous_state, new_state, evidence
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                        ON CONFLICT (causal_id) DO NOTHING;
                    """, (
                        event.causal_id,
                        event.user_id,
                        actual_action_id,
                        event.task_id,
                        event.effect_transition_id,
                        event.event_type,
                        event.relationship.value,
                        event.confidence,
                        event.cause_description,
                        event.effect_summary,
                        json.dumps(event.previous_state, default=str),
                        json.dumps(event.new_state, default=str),
                        json.dumps(event.evidence, default=str),
                    ))
        except Exception as e:
            logger.debug("[CAUSAL] Failed to persist event to PostgreSQL: %s", e)

    def get_recent_causal_events(self, user_id: int, limit: int = 10) -> List[CausalEvent]:
        """Fetch recent verified causal events from PostgreSQL or memory fallback."""
        events: List[CausalEvent] = []
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        SELECT causal_id, user_id, cause_action_id, task_id,
                               effect_transition_id, event_type, relationship,
                               confidence, cause_description, effect_summary,
                               previous_state, new_state, evidence, EXTRACT(EPOCH FROM created_at)
                        FROM causal_state_events
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s;
                    """, (user_id, limit))
                    rows = cur.fetchall()
                    for r in rows:
                        events.append(CausalEvent(
                            causal_id=r[0],
                            user_id=r[1],
                            cause_action_id=r[2],
                            task_id=r[3],
                            effect_transition_id=r[4],
                            event_type=r[5],
                            relationship=CausalRelationship(r[6]),
                            confidence=float(r[7]),
                            cause_description=r[8],
                            effect_summary=r[9],
                            previous_state=r[10] if isinstance(r[10], dict) else {},
                            new_state=r[11] if isinstance(r[11], dict) else {},
                            evidence=r[12] if isinstance(r[12], dict) else {},
                            created_at=float(r[13] or time.time()),
                        ))
                    if events:
                        return events
        except Exception as e:
            logger.debug("[CAUSAL] PostgreSQL read note: %s", e)

        # Fallback to in-memory ring
        if not events:
            events = [e for e in reversed(self._in_memory_events) if e.user_id == user_id][:limit]
        return events

    def explain_change(self, user_id: int, query: str) -> str:
        """
        Answers causal questions:
        - "What changed?"
        - "Why did this change?"
        - "What did you do that caused this?"
        - "What caused Notepad to become active?"
        - "What caused the file to change?"
        - "What happened after I opened Chrome?"
        """
        events = self.get_recent_causal_events(user_id=user_id, limit=10)
        if not events:
            return "I don't have a record of any causal changes directly linked to recent actions."

        low_query = query.lower()
        target_event = None

        # Look for entity-specific matches in query
        for ev in events:
            target_str = str(ev.evidence.get("target", "")).lower()
            effect_str = ev.effect_summary.lower()
            cause_str = ev.cause_description.lower()
            new_app = str(ev.new_state.get("application", "")).lower()

            if target_str and target_str in low_query:
                target_event = ev
                break
            if new_app and new_app in low_query:
                target_event = ev
                break
            if any(w in low_query for w in ("file", "document")) and ev.event_type in ("FILE_MUTATED", "FILE_DELETED"):
                target_event = ev
                break
            if "browser" in low_query or "chrome" in low_query or "youtube" in low_query:
                if "browser" in new_app or "chrome" in new_app or ev.event_type == "MEDIA_PLAYBACK_CHANGED":
                    target_event = ev
                    break

        if not target_event:
            target_event = events[0]

        if target_event.relationship == CausalRelationship.CAUSED:
            return (
                f"{target_event.effect_summary}. "
                f"This change was caused by {target_event.cause_description} "
                f"(confidence: {int(target_event.confidence * 100)}%)."
            )
        elif target_event.relationship == CausalRelationship.LIKELY_CAUSED:
            return (
                f"{target_event.effect_summary}. "
                f"This change was likely caused by {target_event.cause_description}."
            )
        elif target_event.relationship == CausalRelationship.OBSERVED_AFTER:
            return (
                f"This change ({target_event.effect_summary}) was observed after "
                f"{target_event.cause_description}, but direct causality is not definitively confirmed."
            )
        elif target_event.relationship == CausalRelationship.NOT_CAUSALLY_RELATED:
            return f"No direct causal relationship was found between {target_event.cause_description} and the observed change."
        else:
            return f"The observed change was: {target_event.effect_summary}."


_causal_engine: Optional[CausalAttributionEngine] = None


def get_causal_attribution_engine() -> CausalAttributionEngine:
    global _causal_engine
    if _causal_engine is None:
        _causal_engine = CausalAttributionEngine()
    return _causal_engine
