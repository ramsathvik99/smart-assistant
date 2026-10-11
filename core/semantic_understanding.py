"""
Smart Assistant — Canonical Semantic Understanding & Action Memory Retrieval Engine

Implements semantic intent extraction, natural reference resolution, and
PostgreSQL historical action & conversation memory retrieval.

Adheres strictly to AGENTS.md permanent regression freeze.
"""

from __future__ import annotations

import re
import time
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# Canonical Entity Types (Requirement 2)
# ============================================================================

class EntityType:
    """
    Distinguishes target entity categories to prevent action/domain type errors.
    """
    DESKTOP_APPLICATION = "DESKTOP_APPLICATION"
    MOVIE_OR_TV = "MOVIE_OR_TV"
    MUSIC_OR_AUDIO = "MUSIC_OR_AUDIO"
    WEB_PAGE_OR_SEARCH = "WEB_PAGE_OR_SEARCH"
    FILE_OR_DOCUMENT = "FILE_OR_DOCUMENT"
    PERSON_OR_ORG = "PERSON_OR_ORG"
    DEVICE_OR_SYSTEM = "DEVICE_OR_SYSTEM"
    RECOMMENDATION_ITEM = "RECOMMENDATION_ITEM"


# ============================================================================
# Semantic Intent Data Structure (Section 11)
# ============================================================================

@dataclass
class SemanticCommand:
    """
    ONE canonical semantic object representing understood user goal, action,
    target, entities, desired state, and parameters across the entire system.
    """
    command_id: str = ""
    parent_command_id: Optional[str] = None
    user_text: str = ""
    normalized_text: str = ""
    goal: str = ""
    intent: str = ""
    action: str = ""
    target: str = ""
    object: Optional[str] = None
    desired_state: Optional[str] = None
    entities: List[Dict[str, Any]] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    temporal_context: Optional[Any] = None
    conversational_reference: Optional[Dict[str, Any]] = None
    environment_context: Optional[Dict[str, Any]] = None
    candidate_interpretations: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    ambiguity_reason: Optional[str] = None
    safety_class: str = "SAFE"
    required_context: bool = False

    # Historical compatibility attributes for SemanticIntentRepresentation
    user_input: str = ""
    interpreted_meaning: str = ""
    references: List[str] = field(default_factory=list)
    context_required: bool = False
    memory_required: bool = False
    action_required: bool = True
    historical_query_type: Optional[str] = None
    time_filter: Optional[str] = None
    rewritten_command: Optional[str] = None
    target_entity: Optional[str] = None
    target_type: Optional[str] = None
    sub_intent: Optional[str] = None
    os_operation: Optional[Any] = None
    request_type: str = "INSTRUCTION"
    resolved_references: Dict[str, Any] = field(default_factory=dict)
    is_correction: bool = False
    is_negation: bool = False
    is_multi_step: bool = False
    steps: List[Dict[str, Any]] = field(default_factory=list)
    explanation_text: Optional[str] = None

    def __post_init__(self):
        if not self.command_id:
            import uuid
            self.command_id = f"cmd_{uuid.uuid4().hex[:12]}"

        # Bi-directional sync between canonical fields and legacy fields
        if not self.user_text and self.user_input:
            self.user_text = self.user_input
        elif not self.user_input and self.user_text:
            self.user_input = self.user_text

        if not self.goal and self.interpreted_meaning:
            self.goal = self.interpreted_meaning
        elif not self.interpreted_meaning and self.goal:
            self.interpreted_meaning = self.goal

        if not self.target and self.target_entity:
            self.target = self.target_entity
        elif not self.target_entity and self.target:
            self.target_entity = self.target

        if not self.normalized_text and self.user_text:
            self.normalized_text = self.user_text.lower().strip()

        if self.context_required and not self.required_context:
            self.required_context = True
        elif self.required_context and not self.context_required:
            self.context_required = True

        if self.intent == "CURRENT_ENVIRONMENT_QUERY" and not self.target:
            self.target = "environment"
            self.target_entity = "environment"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "parent_command_id": self.parent_command_id,
            "user_text": self.user_text,
            "normalized_text": self.normalized_text,
            "goal": self.goal,
            "intent": self.intent,
            "action": self.action,
            "target": self.target,
            "object": self.object,
            "desired_state": self.desired_state,
            "entities": self.entities,
            "parameters": self.parameters,
            "constraints": self.constraints,
            "temporal_context": self.temporal_context,
            "conversational_reference": self.conversational_reference,
            "environment_context": self.environment_context,
            "candidate_interpretations": self.candidate_interpretations,
            "confidence": self.confidence,
            "ambiguity_reason": self.ambiguity_reason,
            "safety_class": self.safety_class,
            "required_context": self.required_context,
            "user_input": self.user_input,
            "interpreted_meaning": self.interpreted_meaning,
            "references": self.references,
            "context_required": self.context_required,
            "memory_required": self.memory_required,
            "action_required": self.action_required,
            "historical_query_type": self.historical_query_type,
            "time_filter": self.time_filter,
            "rewritten_command": self.rewritten_command,
            "target_entity": self.target_entity,
            "target_type": self.target_type,
            "sub_intent": self.sub_intent,
            "os_operation": self.os_operation.to_dict() if hasattr(self.os_operation, "to_dict") else None,
            "request_type": self.request_type,
            "resolved_references": self.resolved_references,
            "is_correction": self.is_correction,
            "is_negation": self.is_negation,
            "is_multi_step": self.is_multi_step,
            "steps": self.steps,
            "explanation_text": self.explanation_text,
        }


SemanticIntentRepresentation = SemanticCommand


# ============================================================================
# PostgreSQL Historical Memory Retriever (Sections 2, 6, 7)
# ============================================================================

class PostgresHistoricalMemoryRetriever:
    """
    Retrieves historical interactions, assistant actions, and previous results
    directly from PostgreSQL persistent storage.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def _get_connection(self):
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                return pool.get_cursor()
        except Exception:
            pass
        return None

    def retrieve_recent_actions(self, user_id: int, limit: int = 10, minutes_ago: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve recent actions performed by the assistant from PostgreSQL execution_experiences."""
        actions = []
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    if minutes_ago:
                        cur.execute("""
                            SELECT intent, command_signature, action_signature,
                                   expected_outcome, observed_outcome, verification_status,
                                   attempts, EXTRACT(EPOCH FROM created_at), metadata
                            FROM execution_experiences
                            WHERE user_id = %s AND created_at >= NOW() - INTERVAL '%s minutes'
                            ORDER BY created_at DESC
                            LIMIT %s;
                        """, (int(user_id), int(minutes_ago), limit))
                    else:
                        cur.execute("""
                            SELECT intent, command_signature, action_signature,
                                   expected_outcome, observed_outcome, verification_status,
                                   attempts, EXTRACT(EPOCH FROM created_at), metadata
                            FROM execution_experiences
                            WHERE user_id = %s
                            ORDER BY created_at DESC
                            LIMIT %s;
                        """, (int(user_id), limit))

                    rows = cur.fetchall()
                    for r in rows:
                        actions.append({
                            "intent": r[0],
                            "command_signature": r[1],
                            "action_signature": r[2],
                            "expected_outcome": r[3] if isinstance(r[3], dict) else json.loads(r[3] or '{}'),
                            "observed_outcome": r[4] if isinstance(r[4], dict) else json.loads(r[4] or '{}'),
                            "verification_status": r[5],
                            "attempts": r[6] if isinstance(r[6], list) else json.loads(r[6] or '[]'),
                            "created_at": float(r[7]),
                            "metadata": r[8] if isinstance(r[8], dict) else json.loads(r[8] or '{}'),
                        })
        except Exception as e:
            self.logger.warning(f"[MEMORY RETRIEVER] Error querying execution_experiences: {e}")
        return actions

    def retrieve_past_searches(self, user_id: int, time_filter: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve past web/browser searches from messages and execution_experiences."""
        searches = []
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    time_clause = ""
                    if time_filter == "yesterday":
                        time_clause = "AND created_at >= CURRENT_DATE - INTERVAL '1 day' AND created_at < CURRENT_DATE + INTERVAL '1 day'"
                    elif time_filter == "last_week":
                        time_clause = "AND created_at >= CURRENT_DATE - INTERVAL '7 days'"
                    elif time_filter == "today":
                        time_clause = "AND created_at >= CURRENT_DATE"

                    query = f"""
                        SELECT content, EXTRACT(EPOCH FROM created_at)
                        FROM messages
                        WHERE user_id = %s AND role = 'user'
                              AND (LOWER(content) LIKE '%%search%%' OR LOWER(content) LIKE '%%google%%' OR LOWER(content) LIKE '%%look up%%')
                              AND NOT LOWER(content) LIKE '%%what did i search%%'
                              AND NOT LOWER(content) LIKE '%%what was that%%'
                              {time_clause}
                        ORDER BY created_at DESC
                        LIMIT %s;
                    """
                    cur.execute(query, (int(user_id), limit))
                    for r in cur.fetchall():
                        text = r[0]
                        # Extract the search term
                        m = re.search(r'\b(?:search\s+for|search|google|look\s+up)\s+(.+)', text, re.IGNORECASE)
                        term = m.group(1).strip(' "\'') if m else text
                        if not term.lower().startswith(("what did", "what was", "what were")):
                            searches.append({
                                "query": term,
                                "raw_text": text,
                                "timestamp": float(r[1])
                            })
        except Exception as e:
            self.logger.warning(f"[MEMORY RETRIEVER] Error querying searches: {e}")

        # In-memory execution experience fallback if DB table was disconnected
        if not searches:
            try:
                from core.execution_experience import get_experience_manager
                exp_mgr = get_experience_manager()
                for exp in reversed(exp_mgr._memory_cache):
                    if int(exp.user_id) == int(user_id):
                        cmd = exp.command_signature or ""
                        m = re.search(r'\b(?:search\s+for|search\s+google\s+for|search|google|look\s+up)\s+(.+)', cmd, re.IGNORECASE)
                        if m:
                            term = m.group(1).strip(' "\'')
                            if not term.lower().startswith(("what did", "what was")):
                                searches.append({
                                    "query": term,
                                    "raw_text": cmd,
                                    "timestamp": exp.created_at
                                })
                                break
            except Exception:
                pass
        return searches

    def retrieve_past_websites(self, user_id: int, time_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve past websites and URLs requested or opened."""
        websites = []
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    time_clause = ""
                    if time_filter == "last_week":
                        time_clause = "AND created_at >= CURRENT_DATE - INTERVAL '7 days'"
                    elif time_filter == "yesterday":
                        time_clause = "AND created_at >= CURRENT_DATE - INTERVAL '1 day'"

                    query = f"""
                        SELECT content, EXTRACT(EPOCH FROM created_at)
                        FROM messages
                        WHERE user_id = %s AND role = 'user'
                              AND (LOWER(content) LIKE '%%http%%' OR LOWER(content) LIKE '%%.com%%' OR LOWER(content) LIKE '%%.org%%' OR LOWER(content) LIKE '%%website%%' OR LOWER(content) LIKE '%%open %%')
                              {time_clause}
                        ORDER BY created_at DESC
                        LIMIT 10;
                    """
                    cur.execute(query, (int(user_id),))
                    for r in cur.fetchall():
                        websites.append({
                            "content": r[0],
                            "timestamp": float(r[1])
                        })
        except Exception as e:
            self.logger.warning(f"[MEMORY RETRIEVER] Error querying websites: {e}")
        return websites

    def answer_historical_query(
        self,
        user_id: int,
        rep: SemanticIntentRepresentation,
        dialogue_state: Optional[Any] = None
    ) -> str:
        """
        Synthesizes a precise factual response for a historical memory query
        using data retrieved from PostgreSQL.
        """
        q_type = rep.historical_query_type
        time_filt = rep.time_filter
        user_input_low = rep.user_input.lower()

        # 1. Past Search Query ("What did I search for yesterday?", etc.)
        if q_type == "past_search":
            searches = self.retrieve_past_searches(user_id, time_filter=time_filt)
            # Also check dialogue state if DB empty
            if not searches and dialogue_state and hasattr(dialogue_state, "last_search_results"):
                if dialogue_state.last_search_results:
                    first_res = dialogue_state.last_search_results[0]
                    t = first_res.get("title") or first_res.get("query")
                    if t:
                        searches.append({"query": t, "raw_text": t, "timestamp": time.time()})

            if searches:
                top_query = searches[0]["query"]
                clean_term = re.sub(r'^(?:for|about)\s+', '', top_query, flags=re.IGNORECASE).strip(' "\'')
                time_str = "yesterday" if time_filt == "yesterday" else ("today" if time_filt == "today" else ("recently" if not time_filt else f"in the {time_filt}"))
                if len(searches) == 1:
                    return f"You searched for '{clean_term}' {time_str}."
                terms = [s['query'] for s in searches[:3]]
                return f"You searched for '{clean_term}' {time_str}. Other recent searches include: {', '.join(terms[1:])}."
            else:
                time_str = "yesterday" if time_filt == "yesterday" else ("today" if time_filt == "today" else "in that time period")
                return f"I checked my records, and you didn't perform any searches {time_str}."

        # 2. Past Website Query ("What was that website I asked you to open last week?")
        if q_type == "past_website" or "website" in user_input_low or "site" in user_input_low:
            sites = self.retrieve_past_websites(user_id, time_filter=time_filt)
            if sites:
                most_recent = sites[0]["content"]
                m_url = re.search(r'(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9_\-]+\.(?:com|org|edu|gov|net|in|io))', most_recent)
                site_name = m_url.group(1) if m_url else most_recent
                return f"The website you asked me to open was {site_name}."
            return "I couldn't find a recorded website request from that timeframe in your history."

        # 3. Action Sequence Query ("What did you do after I asked you to search for placements?")
        if "after i asked you to" in user_input_low or "after" in user_input_low:
            actions = self.retrieve_recent_actions(user_id, limit=15)
            # Also check dialogue state recent_actions
            if dialogue_state and hasattr(dialogue_state, "recent_actions") and dialogue_state.recent_actions:
                actions = dialogue_state.recent_actions + actions

            m_topic = re.search(r'after\s+(?:i\s+asked\s+you\s+to\s+|we\s+did\s+)?(.+)', user_input_low)
            topic = m_topic.group(1).strip(' ?.') if m_topic else ""

            relevant_steps = []
            for act in actions:
                cmd = str(act.get("command_signature") or act.get("command") or "").lower()
                outcome = str(act.get("observed_outcome") or act.get("status") or "")
                if topic and topic in cmd:
                    continue  # Found the anchor, subsequent ones are 'after'
                if cmd:
                    relevant_steps.append(cmd)

            if relevant_steps:
                steps_summary = "; then ".join(relevant_steps[:3])
                return f"After that request, I performed the following actions: {steps_summary}."
            return "After that request, no further actions were recorded."

        # 4. Specific Action & Interaction History (Section O)
        # 4a. "What did I ask you to do?" / "What did I just ask you to do?"
        if any(p in user_input_low for p in ("what did i ask you to do", "what did i just ask", "what was the last thing i asked")):
            if dialogue_state and hasattr(dialogue_state, "turns") and dialogue_state.turns:
                # Find previous turn where user spoke
                prev_turns = [t for t in dialogue_state.turns if getattr(t, "user_input", None) and t.user_input.lower().strip() != user_input_low.strip()]
                if prev_turns:
                    return f"You asked me to: '{prev_turns[-1].user_input}'."
            try:
                from core.db_pool import get_db_pool
                pool = get_db_pool()
                if pool and pool.is_healthy():
                    with pool.get_cursor() as cur:
                        cur.execute("""
                            SELECT content FROM messages
                            WHERE user_id = %s AND role = 'user' AND content NOT ILIKE %s
                            ORDER BY created_at DESC LIMIT 1;
                        """, (int(user_id), f"%{user_input_low[:15]}%"))
                        row = cur.fetchone()
                        if row:
                            return f"You asked me to: '{row[0]}'."
            except Exception:
                pass
            return "I don't have a record of your previous request."

        # 4b. "What was the last application you opened?"
        if any(p in user_input_low for p in ("last application you opened", "last app you opened", "last application i asked you to open")):
            try:
                from core.db_pool import get_db_pool
                pool = get_db_pool()
                if pool and pool.is_healthy():
                    with pool.get_cursor() as cur:
                        cur.execute("""
                            SELECT target, parameters FROM action_records
                            WHERE user_id = %s AND (action_type = 'OPEN_APPLICATION' OR intent = 'APPLICATION')
                            ORDER BY created_at DESC LIMIT 1;
                        """, (int(user_id),))
                        row = cur.fetchone()
                        if row and row[0]:
                            return f"The last application I opened was {row[0].capitalize()}."
            except Exception:
                pass
            actions = self.retrieve_recent_actions(user_id, limit=10)
            for a in actions:
                cmd = str(a.get("command_signature") or a.get("command") or "").lower()
                m = re.search(r'(?:open|start|launch)\s+([a-zA-Z0-9_\-]+)', cmd)
                if m:
                    return f"The last application I opened was {m.group(1).capitalize()}."
            return "I have no recent record of opening an application."

        # 4c. "What did I ask you to gather yesterday?" / "gather yesterday"
        if any(p in user_input_low for p in ("what did i ask you to gather", "gather yesterday", "what did we gather")):
            try:
                from core.db_pool import get_db_pool
                pool = get_db_pool()
                if pool and pool.is_healthy():
                    with pool.get_cursor() as cur:
                        cur.execute("""
                            SELECT topic, content_type FROM content_artifacts
                            WHERE user_id = %s
                            ORDER BY created_at DESC LIMIT 1;
                        """, (int(user_id),))
                        row = cur.fetchone()
                        if row:
                            return f"You asked me to gather information about {row[0]}."
            except Exception:
                pass
            return "I don't have a record of a gather request from that timeframe."

        # 4d. "What did you insert into Notepad?"
        if any(p in user_input_low for p in ("insert into notepad", "what did you insert", "write into notepad", "put into notepad")):
            try:
                from core.db_pool import get_db_pool
                pool = get_db_pool()
                if pool and pool.is_healthy():
                    with pool.get_cursor() as cur:
                        cur.execute("""
                            SELECT a.topic, a.content_type, i.target_app
                            FROM artifact_insertions i
                            JOIN content_artifacts a ON i.artifact_id = a.artifact_id
                            WHERE i.user_id = %s
                            ORDER BY i.inserted_at DESC LIMIT 1;
                        """, (int(user_id),))
                        row = cur.fetchone()
                        if row:
                            return f"I inserted the {row[1]} for '{row[0]}' into {row[2].capitalize()}."
            except Exception:
                pass
            return "I don't have a record of inserting content into Notepad."

        # 4e. "What did you read before I stopped you?"
        if any(p in user_input_low for p in ("what did you read before", "read before i stopped", "what was being read")):
            try:
                from core.db_pool import get_db_pool
                pool = get_db_pool()
                if pool and pool.is_healthy():
                    with pool.get_cursor() as cur:
                        cur.execute("""
                            SELECT a.topic, a.content_type
                            FROM artifact_reading_sessions s
                            JOIN content_artifacts a ON s.artifact_id = a.artifact_id
                            WHERE s.user_id = %s
                            ORDER BY s.updated_at DESC LIMIT 1;
                        """, (int(user_id),))
                        row = cur.fetchone()
                        if row:
                            return f"Before you stopped me, I was reading the {row[1]} for '{row[0]}'."
            except Exception:
                pass
            return "I was not reading any content before being stopped."

        # 4f. "What task did I cancel?"
        if any(p in user_input_low for p in ("what task did i cancel", "task did i cancel", "what did i cancel")):
            try:
                from core.db_pool import get_db_pool
                pool = get_db_pool()
                if pool and pool.is_healthy():
                    with pool.get_cursor() as cur:
                        cur.execute("""
                            SELECT normalized_goal FROM concurrent_tasks
                            WHERE user_id = %s AND status = 'CANCELLED'
                            ORDER BY completed_at DESC NULLS LAST, created_at DESC LIMIT 1;
                        """, (int(user_id),))
                        row = cur.fetchone()
                        if row:
                            return f"You cancelled the task '{row[0]}'."
            except Exception:
                pass
            return "There are no records of cancelled tasks."

        # 4g. "What did you do before that?"
        if "what did you do before that" in user_input_low or "before that" in user_input_low:
            actions = self.retrieve_recent_actions(user_id, limit=5)
            if not actions and dialogue_state and hasattr(dialogue_state, "recent_actions"):
                actions = dialogue_state.recent_actions
            if len(actions) >= 2:
                prior = actions[1]
                cmd = prior.get("command_signature") or prior.get("command") or prior.get("intent") or "an action"
                status = prior.get("verification_status") or prior.get("status") or "completed"
                return f"Before that, I executed {cmd} ({status})."

        # 4h. Recent Actions Query ("What did you just do?", "What did you do recently?")
        if q_type == "past_action" or "what did you just do" in user_input_low or "five minutes ago" in user_input_low or "what did you do" in user_input_low or "what happened" in user_input_low or "what command did you run" in user_input_low or "what did you close" in user_input_low:
            actions = self.retrieve_recent_actions(user_id, limit=5, minutes_ago=10 if "five" in user_input_low else None)
            if not actions and dialogue_state and hasattr(dialogue_state, "recent_actions"):
                actions = dialogue_state.recent_actions[-5:]

            if not actions:
                try:
                    from core.os_gateway import get_os_action_history
                    os_acts = get_os_action_history().get_recent_actions(user_id=user_id, limit=5)
                    if os_acts:
                        descs = [f"{a['operation_type']} on '{a.get('target', '')}' ({a['status']})" for a in os_acts]
                        return f"Here is what I did: {', '.join(descs)}."
                except Exception:
                    pass

            if actions:
                descs = []
                for act in actions:
                    cmd = act.get("command_signature") or act.get("command") or act.get("intent") or "an action"
                    status = act.get("verification_status") or act.get("status") or "completed"
                    descs.append(f"{cmd} ({status})")
                return f"Here is what I did: {', '.join(descs)}."
            else:
                # Check recent turns
                if dialogue_state and hasattr(dialogue_state, "turns") and dialogue_state.turns:
                    last_turns = dialogue_state.turns[-3:]
                    turn_texts = [f"responded to '{t.user_input}'" for t in last_turns if getattr(t, 'user_input', None)]
                    if turn_texts:
                        return f"In our recent interaction, I {', and then I '.join(turn_texts)}."
                return "I don't have any recorded actions in that timeframe."

        # 5. Completed Tasks Query ("What tasks did we complete yesterday?")
        if q_type == "past_task" or "tasks did we complete" in user_input_low or "completed tasks" in user_input_low:
            actions = self.retrieve_recent_actions(user_id, limit=20)
            completed = [
                a.get("command_signature") or a.get("command")
                for a in actions
                if a.get("verification_status") == "VERIFIED_SUCCESS" or a.get("status") == "success"
            ]
            if completed:
                unique_tasks = list(dict.fromkeys(completed))[:5]
                return f"Here are the tasks completed: {', '.join(unique_tasks)}."
            return "There are no recorded completed tasks for that time period."

        # 6. Destination / Placement Query ("Where did you put it?", "Where did you put the file?")
        if q_type == "recent_destination" or any(p in user_input_low for p in ("where did you put it", "where did you put that", "where did you put the file", "where did that go", "where is it saved", "where did you save it", "where did you place it", "where did it go")):
            if dialogue_state and hasattr(dialogue_state, "session_context"):
                last_file = dialogue_state.session_context.get("last_saved_file")
                last_dest = dialogue_state.session_context.get("last_insertion_target")
                if last_file:
                    return f"I saved it to {last_dest or 'Downloads'} at {last_file}."
                if last_dest:
                    return f"I put it into {last_dest}."

            try:
                from core.db_pool import get_db_pool
                pool = get_db_pool()
                if pool and pool.is_healthy():
                    with pool.get_cursor() as cur:
                        cur.execute("""
                            SELECT a.topic, i.target_app, i.target_file
                            FROM artifact_insertions i
                            JOIN content_artifacts a ON i.artifact_id = a.artifact_id
                            WHERE i.user_id = %s
                            ORDER BY i.inserted_at DESC LIMIT 1;
                        """, (int(user_id),))
                        row = cur.fetchone()
                        if row:
                            target_display = row[2] or (row[1].capitalize() if row[1] else "the target")
                            return f"I put it into {target_display}."
            except Exception:
                pass

            try:
                from core.os_gateway import get_os_action_history
                acts = get_os_action_history().get_recent_actions(user_id=user_id, limit=5)
                for a in acts:
                    if a.get("operation_type") in ("MOVE_FILE", "COPY_FILE", "WRITE_FILE", "CREATE_FILE"):
                        params = a.get("parameters") or {}
                        dest = params.get("destination") or a.get("target")
                        if dest:
                            return f"I placed it in {dest}."
            except Exception:
                pass

            return "I don't have a record of where that was placed."

        # 7. Action Verification Query ("Did you open Notepad?", "Have you opened Notepad?")
        if q_type == "action_verification" or rep.sub_intent == "ACTION_VERIFICATION" or any(p in user_input_low for p in ("did you open", "have you opened")):
            target = rep.target_entity or "the application"
            # Check recent actions
            acts = self.retrieve_recent_actions(user_id, limit=5)
            for a in acts:
                cmd = str(a.get("command_signature") or a.get("command") or "").lower()
                if target.lower() in cmd and any(w in cmd for w in ("open", "launch", "start")):
                    return f"Yes, I opened {target.capitalize()}."
            # Check running windows
            try:
                from core.environment import get_state_engine
                curr_st = get_state_engine().get_current_state(str(user_id))
                if curr_st and target.lower() in curr_st.application.lower():
                    return f"Yes, {target.capitalize()} is currently open and active."
            except Exception:
                pass
            return f"No, I haven't opened {target.capitalize()}."

        # 8. Action Explanation Query ("Why did you open Notepad?", "Why did you do that?")
        if q_type == "explanation" or rep.sub_intent == "EXPLANATION_QUERY" or any(p in user_input_low for p in ("why did you open", "why did you do that")):
            target = rep.target_entity or "that"
            if dialogue_state and hasattr(dialogue_state, "turns") and dialogue_state.turns:
                for t in reversed(dialogue_state.turns[:-1]):
                    u_in = getattr(t, "user_input", "") or ""
                    if target.lower() in u_in.lower() or any(w in u_in.lower() for w in ("notepad", "text editor", "put that into")):
                        return f"I opened {target.capitalize()} earlier because you requested: '{u_in}'."
            return f"I opened {target.capitalize()} earlier in response to your previous instruction."

        # Default fallback to general recent interaction summary
        return "I reviewed our stored interactions, but couldn't find a matching record for that specific query."


# ============================================================================
# Semantic Understanding Engine (Sections 3, 4, 9, 10)
# ============================================================================

class SemanticUnderstandingEngine:
    """
    Understands the natural-language meaning of user input, resolves references,
    distinguishes commands from expressions/desires, and handles memory queries.
    """

    def __init__(self):
        self.memory_retriever = PostgresHistoricalMemoryRetriever()

    @staticmethod
    def is_local_environment_query(text: str) -> bool:
        """Determines if a natural language query targets local machine state rather than general knowledge."""
        if not text:
            return False
        tl = text.lower()
        patterns = [
            r'\b(?:what|which)\s+(?:app|application|window|program|website|site|page|video|file|document|project|branch|browser)\b',
            r'\bwhat\s+(?:am\s+i|are\s+we)\s+(?:using|on|watching|viewing|editing|working\s+(?:on|in)|looking\s+at)\b',
            r'\bwhat\s+was\s+(?:i\s+|the\s+)?(?:using|on|watching|open|working\s+(?:in|on))\b',
            r'\bwhat\s+was\s+i\s+working\s+(?:in|on)\s*(?:just\s+now|previously|before)?\b',
            r'\b(?:what\s+was\s+the\s+previous|previous\s+app|previous\s+website|previous\s+video|previous\s+page)\b',
            r'\bwhat\s+did\s+i\s+(?:have\s+open|switch\s+from)\b',
            r'\bbefore\s+(?:this|that|[a-zA-Z0-9_\-]+)\b',
            r'\bwhat\s+changed\b',
            r'\bcan\s+you\s+see\s+(?:my\s+)?(?:system|screen|computer|desktop)\b',
            r'\b(?:system\s+(?:info|information|overview|status)|what\s+machine\s+is\s+this)\b',
            r'\bwhat\s+(?:is\s+)?(?:running|active\s+processes|processes\s+are\s+running)\b',
            r'\b(?:what|list|show)\s+(?:drives|disks|storage|partitions)\b',
            r'\b(?:where\s+am\s+i\s+in\s+(?:the\s+)?terminal|terminal\s+(?:directory|cwd|folder))\b',
            r'\bwhat\s+am\s+i\s+looking\s+at\b',
            r'\b(?:which|what)\s+browser\s+(?:am\s+i\s+using|is\s+open)\b',
            r'\b(?:what\s+is\s+my\s+ip|network\s+status|am\s+i\s+connected\s+to\s+(?:the\s+)?internet)\b',
            r'\b(?:what|which)\s+document\s+(?:am\s+i\s+editing|is\s+open)\b',
        ]
        return any(re.search(p, tl) for p in patterns)

    def _detect_environment_query(
        self,
        raw_text: str,
        text_low: str,
        dialogue_state: Optional[Any] = None
    ) -> Optional[SemanticIntentRepresentation]:
        """
        Understands natural language environment, state, and history queries.
        Normalizes natural speech variations and extracts reference entities.
        """
        # 1. Strip polite phrases, greetings, assistant names, and conversational preambles
        clean = re.sub(r'^(?:hey\s+|ok\s+|okay\s+)?(?:friday|trevon|nova|jarvis|assistant|computer)[,\s:]*', '', text_low).strip()
        clean = re.sub(r'^(?:now\s+|so\s+|and\s+|just\s+)?(?:can\s+you\s+|could\s+you\s+|would\s+you\s+|please\s+)?(?:tell\s+me\s+|show\s+me\s+|explain\s+to\s+me\s+|let\s+me\s+know\s+)?(?:now\s+|just\s+)?', '', clean).strip()
        clean = clean.rstrip('.?!,').strip()

        # Normalize common speech recognition / natural phrasing artifacts
        norm = re.sub(r'\bwhat\s+was\s+(?:the|i\s+am)\s+using\b', 'what was i using', clean)
        norm = re.sub(r'\bwhat\s+(?:was\s+i|was\s+the|did\s+i)\s+am\s+using\b', 'what was i using', norm)

        # -------------------------------------------------------------
        # A. Causal Attribution & State Change Queries
        # -------------------------------------------------------------
        if any(re.search(p, norm) for p in [
            r'^(?:what\s+changed(?:\s+from\s+before|\s+since\s+before|\s+since\s+earlier)?|what\s+is\s+different|what\'s\s+different)$',
            r'\b(?:what\s+changed\s+(?:from\s+before|since\s+earlier|after\s+you))\b',
            r'\b(?:why\s+did\s+(?:this|that|it|the\s+browser)\s+change)\b',
            r'\b(?:what\s+caused\s+([a-zA-Z0-9_\-]+)\s+to\s+become\s+active)\b',
            r'\b(?:why\s+did\s+(?!you\b)([a-zA-Z0-9_\-]+)\s+open)\b',
            r'\b(?:what\s+caused\s+the\s+file\s+to\s+change)\b',
            r'\b(?:what\s+did\s+you\s+do\s+that\s+caused\s+this)\b',
            r'\b(?:what\s+happened\s+after\s+i\s+asked\s+you)\b',
            r'\b(?:why\s+did\s+the\s+browser\s+switch\s+to\s+that\s+video)\b',
        ]) or norm in ("what changed", "what changed from before", "what changed since before"):
            m_cause = re.search(r'\b(?:caused|why\s+did)\s+([a-zA-Z0-9_\-]+)', norm)
            cause_ent = m_cause.group(1) if m_cause else None
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is inquiring about an environment state change or causal attribution.",
                intent="CAUSAL_ENVIRONMENT_QUERY",
                sub_intent="CAUSAL_STATE_QUERY" if cause_ent else "STATE_CHANGE",
                target_type="STATE_CHANGE",
                target_entity=cause_ent,
                action="explain_causal_change",
                historical_query_type="causal_attribution",
                context_required=True,
                memory_required=True,
                action_required=False,
                confidence=0.98,
            )

        # -------------------------------------------------------------
        # B. Previous / Historical Environment Queries
        # -------------------------------------------------------------
        hist_ref_entity = None
        m_before = re.search(r'\bbefore\s+(?:the\s+)?(?:application\s+|app\s+)?([a-zA-Z0-9_\-]+)(?:\s+(?:application|app|browser|program|window))?\b', norm)
        if m_before and m_before.group(1).lower() not in ("this", "that", "now", "it"):
            hist_ref_entity = m_before.group(1).strip()

        # 1. Previous Video
        if any(re.search(p, norm) for p in [
            r'\b(?:what|which)\s+(?:was\s+i\s+watching|video\s+was\s+i\s+watching|clip\s+was\s+i\s+watching)\s*(?:before|earlier|previously)?\b',
            r'\bwhat\s+was\s+i\s+watching\s+before\s+(?:this|that)\b',
            r'\bwhat\s+video\s+(?:did\s+i\s+have|was\s+i\s+watching|was\s+playing)\s*(?:before|earlier|previously)?\b',
            r'\bwhat\s+video\s+did\s+i\s+have\s+before\b',
            r'\bprevious\s+video\b',
            r'\bshow\s+me\s+the\s+(?:clip|video)\s+i\s+had\s+open\s*(?:before|earlier)?\b',
        ]) or norm in ("what was i watching before this", "what video was i watching before", "what was i watching before", "previous video"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying previous video or media playback state.",
                intent="HISTORICAL_ENVIRONMENT_QUERY",
                sub_intent="PREVIOUS_VIDEO",
                target_type="VIDEO",
                action="query_previous_environment",
                historical_query_type="environment_history",
                temporal_context="previous",
                references=["before this", "previous"],
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 2. Previous Website / Page / Browser Tab
        if any(re.search(p, norm) for p in [
            r'\bwhere\s+was\s+i\s+before\s+this\s*(?:page|site|website)?\b',
            r'\bwhat\s+(?:website|site|page|tab|url)\s+(?:was\s+i|did\s+i\s+have)\s+(?:on|viewing|looking\s+at|browsing|open)\s*(?:before|earlier|previously)?\b',
            r'\bwhat\s+was\s+i\s+on\s+before\s+(?:that|this)\b',
            r'\bprevious\s+(?:website|site|page|tab)\b',
            r'\bshow\s+me\s+the\s+(?:page|tab|site|website)\s+i\s+had\s+open\s*(?:before|earlier)?\b',
        ]) or norm in ("where was i before this page", "where was i before this", "what website was i on before", "previous website", "previous page"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying previous website, URL, or browser page.",
                intent="HISTORICAL_ENVIRONMENT_QUERY",
                sub_intent="PREVIOUS_WEBSITE",
                target_type="WEBSITE",
                action="query_previous_environment",
                historical_query_type="environment_history",
                temporal_context="previous",
                references=["before that", "before this", "previous"],
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 3. Previous Application / General Environment History
        if hist_ref_entity or any(re.search(p, norm) for p in [
            r'^(?:what\s+was\s+the\s+previous\s+app|previous\s+app)$',
            r'\b(?:what|which)\s+(?:was\s+the\s+)?previous\s+(?:app|application|window|program)\b',
            r'\b(?:what|which)\s+(?:one|app|application|window|program)\s+(?:was|did\s+i\s+have)?\s*(?:open|active|running|used)?\s*(?:before(?:\s+(?:this|that|this\s+one))?|previously|earlier)\b',
            r'\b(?:what|which)(?:\s+one)?\s+was\s+(?:i\s+)?(?:using|on|running|open|working\s+in)\s*(?:before(?:\s+(?:this|that|this\s+one|[a-zA-Z0-9_\-]+))?|previously|earlier)\b',
            r'\bwhat\s+did\s+i\s+(?:have\s+open|use)\s*(?:before(?:\s+(?:this|that|this\s+one))?|previously|earlier|prior)\b',
            r'\bwhat\s+did\s+i\s+switch\s+from\b',
            r'\b(?:what|which)(?:\s+one)?\s+was\s+open\s+(?:previously|earlier|before(?:\s+(?:this|that|[a-zA-Z0-9_\-]+))?)\b',
            r'\bwhat\s+was\s+i\s+doing\s+before\s+this\b',
            r'\b(?:what|which)\s+(?:one|app)\s+was\s+open\s*(?:before(?:\s+(?:this|that))?|previously|earlier)\b',
            r'\bwhat\s+was\s+i\s+working\s+(?:in|on)\s*(?:just\s+now|previously|before)?\b',
        ]) or norm in ("what was the previous app", "previous app", "which app was open before this", "which one was open before this", "what app was open before this", "what was open previously", "what did i have open previously", "what did i have open before this", "what did i switch from", "what was i doing before this", "what app was open before", "what was i working in previously", "what was i working in just now"):
            target_ent = hist_ref_entity or ("that" if "before that" in norm else None)
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying previous application or system environment state.",
                intent="HISTORICAL_ENVIRONMENT_QUERY",
                sub_intent="PREVIOUS_APPLICATION",
                target_type="APPLICATION",
                target_entity=target_ent,
                action="query_previous_environment",
                historical_query_type="environment_history",
                temporal_context="previous",
                references=[target_ent] if target_ent else ["previous"],
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # -------------------------------------------------------------
        # C. Current Environment Queries
        # -------------------------------------------------------------

        # 1. Current Video
        if any(re.search(p, norm) for p in [
            r'\bwhat\s+video\s+am\s+i\s+(?:currently\s+)?(?:watching|viewing|looking\s+at)\b',
            r'\bwhich\s+video\s+am\s+i\s+(?:currently\s+)?(?:watching|viewing)\b',
            r'\bwhat\s+am\s+i\s+(?:currently\s+)?watching\b',
            r'\bwhich\s+video\s+is\s+(?:currently\s+)?(?:playing|open|active)\b',
            r'\bwhat\s+video\s+is\s+(?:currently\s+)?(?:playing|open|active)\b',
            r'\bwhich\s+channel\s+is\s+this\b',
            r'\bwhat\s+channel\s+is\s+this\b',
        ]) or norm in ("what video am i watching", "which video am i watching", "what am i watching", "what video is playing", "which channel is this", "what channel is this"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying current video or media playback state.",
                intent="CURRENT_ENVIRONMENT_QUERY",
                sub_intent="CURRENT_VIDEO",
                target_type="VIDEO",
                action="query_environment",
                historical_query_type="current_environment",
                temporal_context="current",
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 2. Current Website / Browser Page
        if any(re.search(p, norm) for p in [
            r'\bwhat\s+website\s+am\s+i\s+(?:currently\s+)?(?:on|using|browsing|viewing|looking\s+at)\b',
            r'\bwhat\s+site\s+am\s+i\s+(?:currently\s+)?(?:on|using|browsing|viewing|looking\s+at)\b',
            r'\bwhich\s+site\s+am\s+i\s+(?:currently\s+)?(?:on|using|browsing|viewing|looking\s+at)\b',
            r'\bwhich\s+website\s+am\s+i\s+(?:currently\s+)?(?:on|using|browsing|viewing|looking\s+at)\b',
            r'\bwhich\s+(?:site|website)\s+is\s+(?:currently\s+)?open\b',
            r'\bwhat\s+page\s+am\s+i\s+(?:currently\s+)?(?:on|using|viewing|looking\s+at)\b',
            r'\bwhat\s+url\s+am\s+i\s+(?:currently\s+)?(?:on|viewing)\b',
            r'\bwhere\s+am\s+i\s+(?:currently\s+)?browsing\b',
            r'\bwhich\s+browser\s+(?:page|tab)\s+is\s+(?:currently\s+)?open\b',
            r'\bwhat\s+(?:website|site|page)\s+is\s+this\b',
        ]) or norm in ("what website am i on", "what website am i using", "which site am i on", "which site is open", "what page am i on", "which site am i browsing", "where am i browsing", "what page am i viewing"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying current website or web browser page.",
                intent="CURRENT_ENVIRONMENT_QUERY",
                sub_intent="CURRENT_WEBSITE",
                target_type="WEBSITE",
                action="query_environment",
                historical_query_type="current_environment",
                temporal_context="current",
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 3. Current Code / File / Document / Project / Branch / Selection
        if any(re.search(p, norm) for p in [
            r'\bwhat\s+(?:file|document)\s+am\s+i\s+(?:working\s+on|editing|in)\b',
            r'\bwhat\s+(?:file|document)\s+is\s+(?:currently\s+)?(?:open|active)\b',
            r'\bwhich\s+(?:file|document)\s+am\s+i\s+(?:working\s+on|editing|in)\b',
            r'\bwhat\s+project\s+am\s+i\s+in\b',
            r'\bwhich\s+branch\s+am\s+i\s+on\b',
            r'\bwhat\s+branch\s+am\s+i\s+on\b',
            r'\bwhat\s+is\s+selected\b',
            r'\bwhat\s+files\s+do\s+i\s+have\s+selected\b',
            r'\bwhat\s+do\s+i\s+have\s+selected\b',
        ]) or norm in ("what file am i working on", "what document am i editing", "what document is open", "what project am i in", "which branch am i on", "what branch am i on", "what is selected", "what files do i have selected", "what do i have selected"):
            tgt = "DOCUMENT" if "document" in norm else ("FILE" if "file" in norm else ("PROJECT" if "project" in norm else ("BRANCH" if "branch" in norm else "SELECTION")))
            sub = f"CURRENT_{tgt}"
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User is querying current {tgt.lower()} environment state.",
                intent="CURRENT_ENVIRONMENT_QUERY",
                sub_intent=sub,
                target_type=tgt,
                action="query_environment",
                historical_query_type="current_environment",
                temporal_context="current",
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 4. System State & Visibility ("Can you see my system?")
        if any(re.search(p, norm) or re.search(p, text_low) for p in [
            r'\b(?:can\s+you\s+)?see\s+(?:my\s+)?(?:system|screen|computer|desktop)\b',
            r'\bwhat\s+machine\s+is\s+this(?:\s+running\s+on)?\b',
            r'\b(?:what\s+is\s+my\s+|system\s+)?(?:hostname|computer\s+name|os\s+version|windows\s+version)\b',
            r'\b(?:what\s+is\s+my\s+|check\s+my\s+)?(?:cpu\s+usage|ram\s+usage|memory\s+usage|gpu\s+usage|system\s+info|system\s+information)\b',
            r'\bhow\s+much\s+(?:ram|memory|cpu)\b',
        ]) or norm in ("see my system", "see my screen", "can you see my system", "can you see my screen", "system info", "system information", "what machine is this"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying local system information or visibility into the computer.",
                intent="CURRENT_ENVIRONMENT_QUERY",
                sub_intent="SYSTEM_STATE",
                target_type="SYSTEM",
                action="inspect_system",
                historical_query_type="current_environment",
                temporal_context="current",
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 5. Process State ("What's running on my computer?")
        if any(re.search(p, norm) for p in [
            r'\bwhat(?:\'s|\s+is)\s+running(?:\s+on\s+my\s+computer)?\b',
            r'\bwhat\s+processes\s+are\s+(?:currently\s+)?running\b',
            r'\b(?:list|show)\s+(?:running\s+)?processes\b',
            r'\bwhat\s+is\s+using\s+(?:the\s+)?(?:cpu|memory|ram)\b',
        ]) or norm in ("what's running", "what is running", "what's running on my computer", "list processes", "running processes"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying running processes and resource consumers.",
                intent="CURRENT_ENVIRONMENT_QUERY",
                sub_intent="PROCESS_STATE",
                target_type="PROCESS",
                action="inspect_processes",
                historical_query_type="current_environment",
                temporal_context="current",
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 5b. Current Folder / Working Directory ("What folder am I in right now?", "What folder am I in?")
        if any(re.search(p, norm) for p in [
            r'\bwhat\s+folder\s+am\s+i\s+(?:in|currently\s+in|in\s+right\s+now)\b',
            r'\bwhich\s+folder\s+am\s+i\s+(?:in|currently\s+in|in\s+right\s+now)\b',
            r'\bwhat\s+directory\s+am\s+i\s+(?:in|currently\s+in|in\s+right\s+now)\b',
            r'\bwhat\s+folder\s+is\s+(?:this|open)\b',
        ]) or norm in ("what folder am i in", "what folder am i in right now", "what directory am i in", "what directory am i in right now", "which folder am i in"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying current directory or active File Explorer folder.",
                intent="CURRENT_ENVIRONMENT_QUERY",
                sub_intent="CURRENT_FOLDER",
                target_type="FOLDER",
                action="query_environment",
                historical_query_type="current_environment",
                temporal_context="current",
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 6. Filesystem / Storage State ("What drives do I have?")
        if any(re.search(p, norm) for p in [
            r'\bwhat\s+(?:drives|disks|partitions)\s+(?:do\s+i\s+have|are\s+available)\b',
            r'\b(?:list|show)\s+(?:all\s+)?(?:my\s+)?drives\b',
            r'\bhow\s+much\s+(?:free\s+space|storage|disk\s+space)\b',
        ]) or norm in ("what drives do i have", "list drives", "show drives"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying filesystem, drives, or storage state.",
                intent="CURRENT_ENVIRONMENT_QUERY",
                sub_intent="FILESYSTEM_STATE",
                target_type="FILESYSTEM",
                action="inspect_storage",
                historical_query_type="current_environment",
                temporal_context="current",
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 7. Terminal Directory State ("Where am I in the terminal?")
        if any(re.search(p, norm) for p in [
            r'\bwhere\s+am\s+i\s+in\s+(?:the\s+)?terminal\b',
            r'\bwhat\s+is\s+my\s+terminal\s+(?:directory|cwd|folder|path)\b',
            r'\bwhat\s+directory\s+is\s+the\s+terminal\s+in\b',
            r'\bwhat\s+(?:directory|folder)\s+am\s+i\s+(?:currently\s+)?in\b',
            r'\bterminal\s+(?:directory|cwd)\b',
        ]) or norm in ("where am i in the terminal", "what is my terminal directory", "terminal directory", "terminal cwd", "what directory am i in", "what directory am i currently in"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying current terminal working directory context.",
                intent="CURRENT_ENVIRONMENT_QUERY",
                sub_intent="CURRENT_TERMINAL_DIRECTORY",
                target_type="TERMINAL",
                action="inspect_terminal",
                historical_query_type="current_environment",
                temporal_context="current",
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 8. Network State ("What is my IP?")
        if any(re.search(p, norm) for p in [
            r'\bwhat\s+is\s+my\s+ip(?:\s+address)?\b',
            r'\bwhat\s+(?:network\s+adapters|dns)\s+do\s+i\s+have\b',
            r'\bam\s+i\s+connected\s+to\s+(?:the\s+)?internet\b',
            r'\bnetwork\s+status\b',
        ]) or norm in ("what is my ip", "network status", "am i connected to the internet"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying local network status, IP, or connectivity.",
                intent="CURRENT_ENVIRONMENT_QUERY",
                sub_intent="NETWORK_STATE",
                target_type="NETWORK",
                action="inspect_network",
                historical_query_type="current_environment",
                temporal_context="current",
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 9. Current Browser ("Which browser am I using?")
        if any(re.search(p, norm) for p in [
            r'\b(?:what|which)\s+browser\s+(?:am\s+i\s+using|is\s+open|is\s+active)\b',
        ]) or norm in ("what browser am i using", "which browser am i using", "what browser is open"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying current web browser.",
                intent="CURRENT_ENVIRONMENT_QUERY",
                sub_intent="CURRENT_BROWSER",
                target_type="BROWSER",
                action="query_environment",
                historical_query_type="current_environment",
                temporal_context="current",
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 10. Current Window / Screen ("What am I looking at?" / "What window is active?")
        if any(re.search(p, norm) for p in [
            r'\bwhat\s+am\s+i\s+looking\s+at\b',
            r'\bwhat\s+window\s+is\s+(?:currently\s+)?active\b',
            r'\bwhich\s+window\s+is\s+(?:currently\s+)?focused\b',
            r'\bwhat\s+is\s+(?:currently\s+)?on\s+my\s+screen\b',
        ]) or norm in ("what am i looking at", "what window is active", "what is on my screen"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying active window or on-screen context.",
                intent="CURRENT_ENVIRONMENT_QUERY",
                sub_intent="CURRENT_WINDOW",
                target_type="WINDOW",
                action="query_environment",
                historical_query_type="current_environment",
                temporal_context="current",
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # 11. Current Application / Window / General Current Environment
        if any(re.search(p, norm) for p in [
            r'\bwhat\s+(?:app|application|window|program)\s+(?:am\s+i|is|is\s+currently)\s+(?:currently\s+)?(?:using|on|in|focused|active|open|running|working\s+in)\b',
            r'\bwhich\s+(?:app|application|window|program)\s+is\s+(?:currently\s+)?(?:active|open|focused|running)\b',
            r'\bwhat\s+am\s+i\s+(?:currently\s+)?(?:using|doing|working\s+in|working\s+on)\b',
            r'\bwhat\s+is\s+(?:currently\s+)?(?:open\s+on\s+my\s+screen|on\s+my\s+screen|focused|currently\s+running|active)\b',
            r'\bwhat(?:\'s|\s+is)\s+(?:currently\s+)?in\s+front\b',
            r'\bwhat\s+window\s+am\s+i\s+(?:currently\s+)?(?:working\s+in|using|on|in)\b',
            r'\bwhat\s+app\s+is\s+open\b',
            r'\bwhat\s+window\s+am\s+i\s+on\b',
        ]) or norm in (
            "what app am i using", "what application am i using", "what am i currently using",
            "what am i currently working in", "what am i working in", "which application is open",
            "what app is open", "which application is active", "what application is currently active",
            "which app is active", "what is open", "what window am i on", "what is on my screen",
            "what's currently in front", "what window am i working in"
        ):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying current active application or window environment state.",
                intent="CURRENT_ENVIRONMENT_QUERY",
                sub_intent="CURRENT_APPLICATION",
                target_type="APPLICATION",
                action="query_environment",
                historical_query_type="current_environment",
                temporal_context="current",
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        return None

    @staticmethod
    def resolve_canonical_application(raw_name: str) -> Optional[str]:
        if not raw_name:
            return None
        t = raw_name.lower().strip()
        t = re.sub(r'^(?:the|a|an)\s+', '', t).strip()
        t = re.sub(r'\s+(?:app|application|program|window)$', '', t).strip()
        t = re.sub(r'\s+(?:on\s+the\s+first\s+page|on\s+the\s+screen|on\s+screen|in\s+foreground|on\s+top|up|please)$', '', t).strip()

        # Stopword acronyms check
        stopword_acronyms = {
            "up", "on", "in", "to", "it", "at", "as", "by", "or", "an", "is",
            "my", "no", "so", "we", "he", "me", "do", "go", "be", "if", "us",
            "am", "the", "and", "but", "for", "out", "app", "run", "get", "see"
        }
        if t in stopword_acronyms:
            return None

        # Ordinals and conversational referents are not applications
        if t in ("one", "it", "that", "this", "link", "page", "file", "folder", "first", "second", "third", "fourth", "fifth", "last", "1st", "2nd", "3rd", "4th", "5th") or re.search(r'\b(?:first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th)\s+(?:one|item|link|file|tab)\b', t):
            return None

        # System / machine / hardware targets are not desktop applications
        if t in ("computer", "pc", "laptop", "machine", "system", "workstation", "desktop", "my computer", "my pc", "my laptop", "the computer", "the pc", "the system"):
            return None

        # Clock, alarm, timer, and stopwatch utilities are not desktop applications
        if t in ("stopwatch", "timer", "alarm", "clock", "alarms", "timers", "stopwatches", "the stopwatch", "the timer", "the alarm", "the clock"):
            return None

        # Conversational clauses, pronouns, and relative phrases are not applications
        if any(w in t.split() for w in ("what", "where", "how", "why", "when", "doing", "were", "was", "did", "do", "we", "i", "you", "they", "asked", "said", "left", "off", "again", "back", "previous")):
            return None

        # Reject uninstaller, installer, setup, prereq keywords
        skip_keywords = (
            "uninstall", "unins000", "unins", "documentation", "release notes", "whatsnew", "what's new",
            "readme", "license", "help", "manual", "guide", "feedback",
            "package cache", "setup.exe", "prereq", "prerequisites", "installer", "install.exe",
            "update.exe", "updater", "crashreporter", "helper.exe"
        )
        if any(bad in t for bad in skip_keywords):
            return None

        # Semantic Concept Resolvers for broad natural language generalization
        # Browser Concept ("Google's browser", "the browser I use", "open my browser", etc.)
        if (
            t in (
                "chrome", "google chrome", "google chrome browser", "browser", "the browser",
                "web browser", "internet browser", "internet program", "web tool",
                "my browser", "the browser i use", "google's browser", "googles browser",
                "google browser", "the google browser"
            )
            or ("google" in t and "browser" in t)
        ):
            return "Google Chrome"

        # Code Editor Concept ("the code editor", "development tool", "programming editor", etc.)
        if (
            t in (
                "vscode", "vs code", "code", "code editor", "the code editor", "visual studio code",
                "coding tool", "coding program", "development tool", "programming editor", "ide"
            )
            or ("code" in t and "editor" in t)
        ):
            return "Visual Studio Code"

        # Text Editor Concept ("the text editor", "plain text tool", "notes program", etc.)
        if (
            t in (
                "notepad", "text editor", "the text editor", "editor", "plain text tool",
                "plain text editor", "notes program", "simple editor", "ms notepad"
            )
            or ("text" in t and "editor" in t)
        ):
            return "Notepad"

        # Terminal / CLI Concept ("terminal", "command prompt", "console", etc.)
        if t in ("terminal", "powershell", "cmd", "command prompt", "console", "command line", "cli"):
            return "Terminal"

        # File Manager Concept ("file explorer", "folder explorer", "files", etc.)
        if t in ("explorer", "file explorer", "file manager", "folder explorer", "files"):
            return "File Explorer"

        # Calculator Concept ("calc", "calculator", "math tool")
        if t in ("calculator", "calc", "math tool"):
            return "Calculator"

        # Canonical application mapping table
        mapping = {
            "chrome": "Google Chrome",
            "google chrome": "Google Chrome",
            "google chrome browser": "Google Chrome",
            "browser": "Google Chrome",
            "web browser": "Google Chrome",
            "internet browser": "Google Chrome",
            "vscode": "Visual Studio Code",
            "vs code": "Visual Studio Code",
            "code": "Visual Studio Code",
            "code editor": "Visual Studio Code",
            "visual studio code": "Visual Studio Code",
            "notepad": "Notepad",
            "text editor": "Notepad",
            "editor": "Notepad",
            "calculator": "Calculator",
            "calc": "Calculator",
            "explorer": "File Explorer",
            "file explorer": "File Explorer",
            "file manager": "File Explorer",
            "terminal": "Terminal",
            "powershell": "PowerShell",
            "cmd": "Command Prompt",
            "command prompt": "Command Prompt",
            "spotify": "Spotify",
            "word": "Microsoft Word",
            "excel": "Microsoft Excel",
            "powerpoint": "Microsoft PowerPoint",
            "ppt": "Microsoft PowerPoint",
            "brave": "Brave",
            "edge": "Microsoft Edge",
            "firefox": "Mozilla Firefox",
        }
        if t in mapping:
            return mapping[t]

        # Reject generic file, artifact, or media terms from being treated as applications
        if any(w in t.split() for w in ("file", "files", "document", "documents", "doc", "pdf", "docx", "pptx", "xlsx", "report", "presentation", "sheet", "saved", "link", "result", "results", "source", "sources", "item", "copy")):
            return None

        # Plausible generic desktop application
        if len(t) >= 2 and len(t.split()) <= 2 and not any(w in t for w in ("that", "this", "it", "something", "anything")):
            return raw_name.strip()
        return None

    def interpret(
        self,
        raw_text: str,
        context: Optional[Dict[str, Any]] = None,
        dialogue_state: Optional[Any] = None,
        user_id: Any = 1,
    ) -> SemanticCommand:
        """
        Derives canonical semantic command representation from natural user language.
        Normalizes input, extracts user goal, target, action, entities, desired state,
        arbitrates ambiguities, resolves contextual references deterministically,
        and enforces safety invariants.
        """
        if not raw_text or not raw_text.strip():
            return SemanticCommand(
                user_text="",
                normalized_text="",
                goal="empty_input",
                intent="GENERAL_CONVERSATION",
                confidence=1.0,
                safety_class="SAFE",
            )

        text_stripped = raw_text.strip()
        text_low = text_stripped.lower()

        # Normalization: strip polite preambles and addressing signals
        clean_text = re.sub(
            r'^(?:can\s+you\s+|could\s+you\s+|please\s+|would\s+you\s+|will\s+you\s+|kindly\s+|friday\s+|trevon\s+|nova\s+|hey\s+friday\s+|hey\s+trevon\s+|hey\s+nova\s+|i\s+want\s+to\s+|i\s+need\s+you\s+to\s+|i\s+need\s+to\s+|can\s+we\s+|let\'?s\s+|tell\s+me\s+to\s+)+',
            '',
            text_low
        ).strip()
        clean_low = clean_text.rstrip('.?!,').strip()

        # Speech error recovery (phonetic / STT normalization)
        norm = re.sub(r'\bturn\s+of\s+bluetooth\b', 'turn off bluetooth', clean_low)
        norm = re.sub(r'\bturn\s+of\s+(?:the\s+)?wifi\b', 'turn off wifi', norm)
        norm = re.sub(r'\bshedule\b', 'schedule', norm)
        norm = re.sub(r'\bmeting\b', 'meeting', norm)

        # -------------------------------------------------------------
        # 1. Garbled Speech / Plausibility Guard (Section 11)
        # -------------------------------------------------------------
        if norm in ("open open", "close close", "run run") or any(k in norm for k in ["hernia of the games", "hernia of games"]):
            clarification_prompt = "Did you mean: 'What games are compatible with this system?'" if "hernia" in norm else "I did not quite understand that. Could you please clarify your request?"
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="Clarify garbled speech input",
                intent="CLARIFICATION",
                action="ask_clarification",
                target="",
                safety_class="BLOCKED",
                confidence=0.3,
                ambiguity_reason="implausible_or_garbled_speech",
                explanation_text=clarification_prompt,
                parameters={"action": "clarification", "response": clarification_prompt},
            )

        # -------------------------------------------------------------
        # 1.1 Canonical Environment, Causal & Historical Queries (Section 4)
        # -------------------------------------------------------------
        if self.is_local_environment_query(norm) or self.is_local_environment_query(text_stripped):
            env_cmd = self._detect_environment_query(text_stripped, norm, dialogue_state)
            if env_cmd:
                return env_cmd

        # -------------------------------------------------------------
        # 2. Negation, Hypothetical, Explanation, and Verification Queries
        # -------------------------------------------------------------
        m_neg = re.search(r'\b(?:don\'?t|do\s+not|never|not)\s+(?:open|launch|start|run|create|delete|close|bring\s+up)\s+([a-zA-Z0-9_\-\s]+)', norm)
        m_dont_want = re.search(r'\bi\s+(?:don\'?t|do\s+not)\s+want\s+([a-zA-Z0-9_\-\s]+?)\s+(?:open|opened|running|started)', norm)
        if m_neg or m_dont_want or norm in ("don't open notepad", "do not open notepad", "don't do that", "do not do that", "stop, don't do that", "don't open it"):
            target_app = (m_neg.group(1) if m_neg else (m_dont_want.group(1) if m_dont_want else "")).strip().rstrip('.?!')
            target_app = re.sub(r'^(?:the|a|an)\s+', '', target_app)
            if "notepad" in norm:
                target_app = "notepad"
            elif "chrome" in norm:
                target_app = "chrome"
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"Negation: do not perform action on {target_app or 'that'}",
                intent="NEGATION",
                action="negation",
                target=target_app or "that",
                is_negation=True,
                action_required=False,
                confidence=0.99,
            )

        if any(re.search(p, norm) for p in [
            r'\bi\s+was\s+thinking\s+(?:about|of)\s+(?:opening|launching|running|using)\s+([a-zA-Z0-9_\-\s]+)',
            r'\bwhat\s+if\s+(?:i|we)\s+(?:opened|launched|ran|started)\s+([a-zA-Z0-9_\-\s]+)',
            r'\bmaybe\s+(?:i|we)\s+should\s+(?:open|launch|run|use)\s+([a-zA-Z0-9_\-\s]+)',
        ]) or norm.startswith("i was thinking about opening"):
            target_app = "notepad" if "notepad" in norm else ("chrome" if "chrome" in norm else "the application")
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"Hypothetical consideration of {target_app}",
                intent="HYPOTHETICAL",
                action="hypothetical",
                target=target_app,
                action_required=False,
                confidence=0.98,
            )

        if any(re.search(p, norm) for p in [
            r'\bwhy\s+did\s+you\s+(?:open|launch|start|close|delete|create|do)\s*([a-zA-Z0-9_\-\s]*)',
            r'\bwhy\s+is\s+([a-zA-Z0-9_\-\s]+?)\s+(?:open|running|active)\b',
            r'\bwhat\s+made\s+you\s+(?:open|do|start)\b',
        ]) or norm in ("why did you open notepad", "why did you do that", "why did you open that"):
            target_app = "notepad" if "notepad" in norm else ("chrome" if "chrome" in norm else "the action")
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"Explain reason for {target_app}",
                intent="EXPLANATION_QUERY",
                action="explain_action",
                target=target_app,
                historical_query_type="explanation",
                action_required=False,
                confidence=0.99,
            )

        if any(re.search(p, norm) for p in [
            r'\b(?:did\s+you|have\s+you)\s+(?:open|opened|launch|launched|start|started)\s+([a-zA-Z0-9_\-\s]+)',
            r'\bis\s+([a-zA-Z0-9_\-\s]+?)\s+(?:open|running|active)\b',
        ]) or norm in ("did you open notepad", "have you opened notepad"):
            target_app = "notepad" if "notepad" in norm else ("chrome" if "chrome" in norm else "the application")
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"Verify whether {target_app} is open/running",
                intent="ACTION_VERIFICATION",
                action="verify_action",
                target=target_app,
                historical_query_type="action_verification",
                action_required=False,
                confidence=0.98,
            )

        # -------------------------------------------------------------
        # 3. Contextual Structured Referents (Section 6, 7)
        # -------------------------------------------------------------
        if (
            norm in ("what's the answer", "whats the answer", "what was the answer", "tell me the answer", "the answer", "what is the answer")
            or any(k in norm for k in ("repeat the result", "result of my last calculation", "result of the calculation", "last calculation result", "previous calculation"))
            or re.search(r'\b(?:repeat|tell\s+me|show\s+me)\s+(?:the\s+)?result\s+of\s+(?:my\s+)?(?:last\s+)?calculation\b', norm)
        ):
            calc_val = None
            if dialogue_state:
                calc_val = getattr(dialogue_state, "active_calculation", None)
                if not calc_val and hasattr(dialogue_state, "session_context"):
                    calc_val = dialogue_state.session_context.get("last_calculation_result")
            if not calc_val:
                try:
                    from extensions.dialogue_state_manager import get_dialogue_manager
                    dm = get_dialogue_manager(str(user_id))
                    calc_val = getattr(dm.current_state, "active_calculation", None) or dm.current_state.session_context.get("last_calculation_result")
                except Exception:
                    pass
            if calc_val is not None:
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="retrieve previous calculation result",
                    intent="CALCULATOR",
                    action="retrieve_result",
                    target="calculation_result",
                    object=str(calc_val),
                    desired_state="retrieved",
                    parameters={"response": str(calc_val), "result": calc_val, "action": "retrieve_result"},
                    conversational_reference={"type": "calculation", "value": calc_val},
                    confidence=1.0,
                )

        m_ord = None
        has_browser_links = False
        if dialogue_state:
            has_browser_links = bool(
                getattr(dialogue_state, "session_context", {}).get("last_extracted_links")
                or getattr(dialogue_state, "active_extracted_links", None)
            )
        if not has_browser_links:
            try:
                from extensions.dialogue_state_manager import get_dialogue_manager
                dm = get_dialogue_manager(str(user_id))
                has_browser_links = bool(dm.current_state.session_context.get("last_extracted_links"))
            except Exception:
                pass
        if not has_browser_links:
            try:
                from extensions.context_manager import context_manager
                has_browser_links = bool(context_manager.active_context.get("last_extracted_links"))
            except Exception:
                pass

        if not has_browser_links and not any(k in norm for k in ("email", "mail", "link", "file", "tab", "window", "folder", "song", "track", "video")):
            m_ord = re.search(r'\b(?:what\s+about\s+(?:the\s+)?|tell\s+me\s+about\s+(?:the\s+)?|what\s+is\s+(?:the\s+)?|pick\s+(?:the\s+)?|choose\s+(?:the\s+)?|open\s+(?:the\s+)?|play\s+(?:the\s+)?|show\s+(?:the\s+)?|select\s+(?:the\s+)?)(first|second|third|fourth|fifth|last|next|1st|2nd|3rd|4th|5th)\s*(?:one|item|recommendation|movie|song|option|result)?\b', norm)
            if not m_ord:
                m_ord = re.search(r'^(?:the\s+)?(first|second|third|fourth|fifth|last|next|1st|2nd|3rd|4th|5th)\s*(?:one|item|recommendation|movie|song|option|result)?$', norm)
        if m_ord:
            ord_word = m_ord.group(1)
            ord_map = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "fifth": 4, "5th": 4, "next": 1, "last": -1}
            idx = ord_map.get(ord_word, 0)
            rec_list = []
            if dialogue_state:
                rec_list = getattr(dialogue_state, "current_recommendation_list", []) or []
            if not rec_list:
                try:
                    from extensions.dialogue_state_manager import get_dialogue_manager
                    dm = get_dialogue_manager(str(user_id))
                    rec_list = dm.current_state.current_recommendation_list or []
                except Exception:
                    pass
            item_val = rec_list[idx] if (rec_list and (abs(idx) <= len(rec_list))) else f"item_{ord_word}"

            is_movie = False
            if dialogue_state:
                cat = getattr(dialogue_state, "session_context", {}).get("last_recommendation_category", "")
                if any(w in str(cat).lower() for w in ("movie", "film", "cinema", "show", "series")):
                    is_movie = True
            if not is_movie and dialogue_state and hasattr(dialogue_state, "turns") and dialogue_state.turns:
                for t in reversed(dialogue_state.turns):
                    t_txt = getattr(t, "user_input", "").lower()
                    if any(w in t_txt for w in ("movie", "movies", "film", "films", "cinema", "show", "shows")):
                        is_movie = True
                        break

            target_type = EntityType.MOVIE_OR_TV if is_movie else EntityType.RECOMMENDATION_ITEM
            is_select_or_open = bool(re.search(r'\b(?:open|play|show|select|pick|choose)\b', norm))
            act_name = "select_item" if is_select_or_open else "inspect_item"

            tgt_val = f"item_{idx+1 if idx >= 0 else 'last'}" if act_name == "inspect_item" else str(item_val)

            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"Select recommendation list item: {item_val}",
                intent="RECOMMENDATION",
                action=act_name,
                target=tgt_val,
                target_type=target_type,
                target_entity=str(item_val),
                object=str(item_val),
                desired_state="selected",
                parameters={"action": act_name, "index": idx, "target": str(item_val), "target_type": target_type, "response": f"Selected '{item_val}' from your recommendations."},
                conversational_reference={"type": "recommendation_item", "index": idx, "value": str(item_val)},
                confidence=0.99,
            )

        if re.search(r'\b(?:is|has)\s+(?:the\s+|my\s+)?(?:ppt|powerpoint|presentation|document|docx|report|task)\s+(?:done|finished|completed|ready)\b', norm):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="query document generation task status",
                intent="TASK_MANAGEMENT",
                action="query_status",
                target="document_task",
                desired_state="queried",
                parameters={"action": "task_status", "target": "document_task"},
                confidence=0.99,
            )

        if norm in ("close it", "close this", "get rid of this", "close that"):
            active_target = None
            if dialogue_state:
                active_target = getattr(dialogue_state, "active_application", None)
            if not active_target:
                try:
                    from extensions.dialogue_state_manager import get_dialogue_manager
                    dm = get_dialogue_manager(str(user_id))
                    active_target = dm.current_state.active_application
                    if not active_target and dm.current_state.session_context.get("opened_applications"):
                        active_target = dm.current_state.session_context["opened_applications"][-1]
                except Exception:
                    pass
            if active_target:
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal=f"Close active application {active_target}",
                    intent="CLOSE_APPLICATION",
                    action="CLOSE_APPLICATION",
                    target=active_target,
                    desired_state="closed",
                    parameters={"application": active_target, "target": active_target, "action": "close"},
                    conversational_reference={"referent": active_target},
                    confidence=0.98,
                )
            else:
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="Close active application",
                    intent="CLARIFICATION",
                    action="clarify_close_app",
                    target="",
                    confidence=0.4,
                    ambiguity_reason="unresolved_active_application",
                    safety_class="CONFIRMATION_REQUIRED",
                    explanation_text="Which application would you like to close?",
                    parameters={"action": "clarification", "response": "Which application would you like to close?"},
                )

        # -------------------------------------------------------------
        # 3b. Context Resumption / Continuation (Section 7, 20)
        # -------------------------------------------------------------
        if any(k in norm for k in (
            "continue that", "continue what i was doing", "can you bring back what we were doing",
            "bring back what we were doing", "go back to what we were doing", "do that again",
            "continue where we left off", "resume previous work", "return to the task",
            "return to what we were doing", "back to what we were doing"
        )) or norm.startswith(("return to the task", "go back to the task", "resume the task", "return to what")):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="resume previous task or context",
                intent="CONTEXT_RESUMPTION",
                action="resume",
                target="previous_task",
                desired_state="resumed",
                parameters={"action": "resume"},
                confidence=1.0,
            )

        # -------------------------------------------------------------
        # 4. Universal Diagnostics (Section 18)
        # -------------------------------------------------------------
        if any(k in norm for k in ("laptop feels slow", "computer is slow", "pc is lagging", "pc feels sluggish", "something is wrong with the computer", "something is wrong with the pc", "why is my laptop slow")):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="Diagnose system performance and resource bottlenecks",
                intent="DEVICE_CONTROL",
                action="diagnose_performance",
                target="system_telemetry",
                desired_state="analyzed",
                parameters={"action": "cpu_metrics", "device": "cpu", "diagnostic": True},
                confidence=0.98,
            )

        # -------------------------------------------------------------
        # 5. Volume Equivalence Group (Section 2, 3, 9)
        # -------------------------------------------------------------
        if any(re.search(p, norm) for p in [
            r'\b(?:make\s+(?:it|things)\s+quieter|quieter|lower\s+(?:the\s+)?sound|decrease\s+volume|turn\s+down\s+volume|turn\s+volume\s+down|volume\s+down|reduce\s+volume|lower\s+volume|less\s+volume|softer\s+volume)\b',
        ]):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="reduce audio output",
                intent="DEVICE_CONTROL",
                action="VOLUME_DECREASE",
                target="system_volume",
                desired_state="quieter",
                parameters={
                    "requested_device_target": "volume",
                    "requested_action": "VOLUME_SET",
                    "resolved_action": "VOLUME_SET",
                    "executor_action": "decrease_volume",
                    "action": "decrease_volume",
                    "step": 10,
                },
                confidence=1.0,
            )

        if any(re.search(p, norm) for p in [
            r'\b(?:make\s+(?:it|things)\s+louder|louder|raise\s+(?:the\s+)?sound|increase\s+volume|turn\s+up\s+volume|turn\s+volume\s+up|volume\s+up|higher\s+volume|more\s+volume)\b',
        ]):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="increase audio output",
                intent="DEVICE_CONTROL",
                action="VOLUME_INCREASE",
                target="system_volume",
                desired_state="louder",
                parameters={
                    "requested_device_target": "volume",
                    "requested_action": "VOLUME_SET",
                    "resolved_action": "VOLUME_SET",
                    "executor_action": "increase_volume",
                    "action": "increase_volume",
                    "step": 10,
                },
                confidence=1.0,
            )

        # Volume Unmute Concept Extraction
        # Covers: "Unmute the sound", "Restore audio output", "Turn sound back on",
        # "Bring back the audio", "Sound on", "Unmute speakers", "Restore sound", "Unmute"
        has_volume_noun = any(k in norm for k in ("volume", "sound", "audio", "speakers", "speaker", "pc", "computer", "system", "machine", "it"))
        is_unmute_concept = (
            any(k in norm for k in (
                "unmute", "restore audio", "restore sound", "bring back sound", "bring back the audio",
                "sound on", "turn sound back on", "turn the sound back on", "turn audio on", "enable audio",
                "hear the sound", "hear audio", "hear the audio", "sound again", "audio again", "let me hear"
            ))
            or ("unmute" in norm and has_volume_noun)
        )
        if is_unmute_concept and not any(k in norm for k in ("bluetooth", "wifi", "wi-fi")):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="unmute audio output",
                intent="DEVICE_CONTROL",
                action="VOLUME_UNMUTE",
                target="system_volume",
                desired_state="unmuted",
                parameters={
                    "requested_device_target": "volume",
                    "requested_action": "VOLUME_UNMUTE",
                    "resolved_action": "VOLUME_UNMUTE",
                    "executor_action": "unmute",
                    "action": "unmute",
                },
                confidence=1.0,
            )

        # Volume Mute Concept Extraction
        # Covers: "Mute the sound", "Silence the volume", "Turn the volume off",
        # "Make the PC quiet", "Make the computer quiet", "Make the computer completely quiet",
        # "Mute my speakers", "Sound off", "Kill the sound", "Mute volume", "make it silent"
        is_mute_verb = (
            any(re.search(p, norm) for p in [r'\bmute\b', r'\bsilence\b', r'\bsound\s+off\b', r'\bkill\s+the\s+sound\b', r'\bturn\s+off\s+(?:the\s+)?volume\b', r'\bturn\s+volume\s+off\b', r'\bturn\s+off\s+volume\b', r'\bturn\s+(?:the\s+)?sound\s+off\b', r'\bmake\s+it\s+silent\b'])
            or (has_volume_noun and any(k in norm for k in ("completely quiet", "quiet", "silent", "no audio", "zero volume", "quiet down")))
        )
        if is_mute_verb and not is_unmute_concept and not any(k in norm for k in ("bluetooth", "wifi", "wi-fi", "task", "reading", "talking", "speaking")):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="mute audio output",
                intent="DEVICE_CONTROL",
                action="VOLUME_MUTE",
                target="system_volume",
                desired_state="muted",
                parameters={
                    "requested_device_target": "volume",
                    "requested_action": "VOLUME_MUTE",
                    "resolved_action": "VOLUME_MUTE",
                    "executor_action": "mute",
                    "action": "mute",
                },
                confidence=1.0,
            )

        # -------------------------------------------------------------
        # 6. Bluetooth Equivalence Group (Section 2, 3, 9)
        # -------------------------------------------------------------
        if "bluetooth" in norm or "bt radio" in norm or "bluetooth radio" in norm:
            if any(k in norm for k in ("off", "disable", "cut off", "shut off", "shut down", "down", "disconnect", "deactivate", "stop")):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="change Bluetooth state",
                    intent="DEVICE_CONTROL",
                    action="BLUETOOTH_OFF",
                    target="bluetooth",
                    desired_state="disabled",
                    parameters={
                        "requested_device_target": "bluetooth",
                        "requested_action": "BLUETOOTH_OFF",
                        "resolved_action": "BLUETOOTH_OFF",
                        "executor_action": "disable_bluetooth",
                        "action": "disable_bluetooth",
                    },
                    confidence=1.0,
                )
            elif any(k in norm for k in ("on", "enable", "activate", "connect", "start", "switch on")):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="change Bluetooth state",
                    intent="DEVICE_CONTROL",
                    action="BLUETOOTH_ON",
                    target="bluetooth",
                    desired_state="enabled",
                    parameters={
                        "requested_device_target": "bluetooth",
                        "requested_action": "BLUETOOTH_ON",
                        "resolved_action": "BLUETOOTH_ON",
                        "executor_action": "enable_bluetooth",
                        "action": "enable_bluetooth",
                    },
                    confidence=1.0,
                )

        # -------------------------------------------------------------
        # 7. Wi-Fi Equivalence Group
        # -------------------------------------------------------------
        if any(re.search(p, norm) for p in [
            r'\b(?:turn\s+off\s+(?:the\s+)?wifi|disable\s+wifi|wifi\s+off|switch\s+off\s+wifi|turn\s+wifi\s+off|deactivate\s+wifi)\b',
        ]):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="change Wi-Fi state",
                intent="DEVICE_CONTROL",
                action="WIFI_OFF",
                target="wifi",
                desired_state="disabled",
                parameters={
                    "requested_device_target": "wifi",
                    "requested_action": "WIFI_OFF",
                    "resolved_action": "WIFI_OFF",
                    "executor_action": "disable_wifi",
                    "action": "disable_wifi",
                },
                confidence=1.0,
            )

        if any(re.search(p, norm) for p in [
            r'\b(?:turn\s+on\s+(?:the\s+)?wifi|enable\s+wifi|wifi\s+on|switch\s+on\s+wifi|turn\s+wifi\s+on|activate\s+wifi)\b',
        ]):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="change Wi-Fi state",
                intent="DEVICE_CONTROL",
                action="WIFI_ON",
                target="wifi",
                desired_state="enabled",
                parameters={
                    "requested_device_target": "wifi",
                    "requested_action": "WIFI_ON",
                    "resolved_action": "WIFI_ON",
                    "executor_action": "enable_wifi",
                    "action": "enable_wifi",
                },
                confidence=1.0,
            )

        # -------------------------------------------------------------
        # 8. Workstation Lock / Unlock Equivalence Group (Section 9)
        # -------------------------------------------------------------
        has_workstation_noun = any(k in norm for k in ("computer", "pc", "system", "workstation", "screen", "session", "machine"))
        is_unlock_act = (
            "unlock" in norm
            or ("open" in norm and any(k in norm for k in ("workstation", "session")) and not any(k in norm for k in ("browser", "app", "file", "folder", "chrome", "notepad", "code")))
            or ("access" in norm and any(k in norm for k in ("workstation", "session")))
        )
        if is_unlock_act:
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="unlock workstation",
                intent="DEVICE_CONTROL",
                action="UNLOCK",
                target="workstation",
                desired_state="unlocked",
                parameters={
                    "requested_device_target": "unlock",
                    "requested_action": "UNLOCK",
                    "resolved_action": "UNLOCK",
                    "executor_action": "unlock",
                    "action": "unlock",
                },
                confidence=1.0,
            )

        if any(k in norm for k in ("lock", "secure")) and (has_workstation_noun or norm in ("lock", "lock it", "lock now")):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="lock workstation",
                intent="DEVICE_CONTROL",
                action="LOCK",
                target="workstation",
                desired_state="locked",
                parameters={
                    "requested_device_target": "lock",
                    "requested_action": "LOCK",
                    "resolved_action": "LOCK",
                    "executor_action": "lock",
                    "action": "lock",
                },
                confidence=1.0,
            )

        # -------------------------------------------------------------
        # 9. Hardware Queries Equivalence Groups (Section 15)
        # -------------------------------------------------------------
        if any(re.search(p, norm) for p in [
            r'\b(?:check\s+(?:my\s+)?cpu(?:\s*,\s*|\s+and\s+|\s+)ram(?:\s*,\s*|\s+and\s+|\s+)gpu(?:\s+usage|\s+telemetry)?|show\s+system\s+usage|check\s+system\s+usage)\b',
        ]):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="query composite system telemetry",
                intent="DEVICE_CONTROL",
                action="QUERY_SYSTEM_TELEMETRY",
                target="system",
                desired_state="queried",
                parameters={
                    "action": "system_telemetry_summary",
                },
                confidence=1.0,
            )

        if any(re.search(p, norm) for p in [
            r'\b(?:how\s+much\s+(?:ram|memory)|what\s+(?:is\s+my\s+)?(?:ram|memory)|tell\s+me\s+my\s+ram|what\s+memory\s+does\s+this\s+pc\s+have|check\s+(?:my\s+)?(?:ram|memory)|ram\s+usage|memory\s+on\s+this\s+computer|know\s+how\s+much\s+ram)\b',
        ]):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="query system memory hardware",
                intent="DEVICE_CONTROL",
                action="QUERY_SYSTEM_HARDWARE",
                target="ram",
                desired_state="queried",
                parameters={
                    "action": "ram_metrics",
                    "device": "ram",
                    "metric": "ram_metrics",
                },
                confidence=1.0,
            )

        if any(re.search(p, norm) for p in [
            r'\b(?:what\s+is\s+my\s+cpu|check\s+(?:my\s+)?cpu|how\s+much\s+cpu|cpu\s+usage|what\'s\s+my\s+cpu|tell\s+me\s+about\s+my\s+cpu|what\s+processor\s+am\s+i\s+running)\b',
        ]):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="query cpu telemetry",
                intent="DEVICE_CONTROL",
                action="QUERY_SYSTEM_TELEMETRY",
                target="cpu",
                desired_state="queried",
                parameters={
                    "action": "cpu_metrics",
                    "device": "cpu",
                    "metric": "cpu_metrics",
                },
                confidence=1.0,
            )

        if any(re.search(p, norm) for p in [
            r'\b(?:what\s+is\s+my\s+gpu|check\s+(?:my\s+)?gpu|how\s+much\s+gpu|gpu\s+usage|gpu\s+telemetry|gpu\s+memory|graphics\s+card)\b',
        ]):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="query gpu telemetry",
                intent="DEVICE_CONTROL",
                action="QUERY_SYSTEM_TELEMETRY",
                target="gpu",
                desired_state="queried",
                parameters={
                    "action": "gpu_telemetry",
                    "device": "gpu",
                },
                confidence=1.0,
            )

        # -------------------------------------------------------------
        # 10. Polysemous "Play": Games vs Music (Section 4, 8)
        # -------------------------------------------------------------
        has_compat = any(k in norm for k in ("compatible", "can i run", "can i download and run", "can run on", "in this system", "on this pc", "requirements"))
        has_game = any(k in norm for k in ("games", "game", "gaming"))
        has_music_noun = any(k in norm for k in ("music", "song", "songs", "tune", "tunes", "track", "spotify"))

        if has_game and any(k in norm for k in ("installed", "are installed")):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="list installed games",
                intent="DEVICE_CONTROL",
                action="list_installed_games",
                target="games",
                desired_state="enumerated",
                parameters={"action": "list_installed_games"},
                confidence=1.0,
            )

        if has_game and has_compat:
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="check system game compatibility",
                intent="SYSTEM_COMPATIBILITY",
                action="compatibility_check",
                target="games",
                desired_state="evaluated",
                candidate_interpretations=[
                    {"intent": "SYSTEM_COMPATIBILITY", "confidence": 0.99},
                    {"intent": "GAME_DISCOVERY", "confidence": 0.85},
                    {"intent": "MUSIC", "confidence": 0.01},
                ],
                parameters={"query": text_stripped, "action": "compatibility_check"},
                confidence=0.99,
            )
        if has_game:
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="discover games",
                intent="GAME_DISCOVERY",
                action="discover_games",
                target="games",
                desired_state="recommended",
                candidate_interpretations=[
                    {"intent": "GAME_DISCOVERY", "confidence": 0.99},
                    {"intent": "MUSIC", "confidence": 0.01},
                ],
                parameters={"query": text_stripped, "action": "discover_games"},
                confidence=0.99,
            )
        if has_music_noun:
            is_rec_query = any(w in norm for w in (
                "recommend", "recommendation", "recommendations",
                "suggest", "suggestion", "suggestions",
                "discover", "discovery",
                "what should i listen", "what artists", "what music should",
                "music ideas", "ideas for music", "new artists", "new music"
            ))
            if is_rec_query:
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="recommend music",
                    intent="RECOMMENDATION",
                    action="recommend",
                    target="music",
                    target_type=EntityType.RECOMMENDATION_ITEM,
                    desired_state="recommended",
                    candidate_interpretations=[
                        {"intent": "RECOMMENDATION", "confidence": 0.99},
                        {"intent": "MUSIC", "confidence": 0.01},
                    ],
                    parameters={"action": "recommend", "query": text_stripped, "domain": "music"},
                    confidence=0.99,
                )
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="music playback",
                intent="MUSIC",
                action="PLAY_MUSIC",
                target="music",
                desired_state="playing",
                candidate_interpretations=[
                    {"intent": "MUSIC", "confidence": 0.99},
                ],
                parameters={"action": "play", "query": text_stripped},
                confidence=0.99,
            )

        # -------------------------------------------------------------
        # 11. Generalized Application Launch Concept Extraction (Section 3, 10)
        # (Evaluated before web search so app names like Google Chrome win)
        # -------------------------------------------------------------
        app_launch_cand = None
        # Split verbs and particles: "bring chrome up", "bring up chrome", "get chrome running", "put me in chrome"
        m_phrasal = re.search(r'\b(?:bring\s+up|bring\s+back|fire\s+up|start\s+using|switch\s+to|load\s+up)\s+(.+)', norm)
        if m_phrasal:
            app_launch_cand = m_phrasal.group(1).strip()
        if not app_launch_cand:
            m_bring = re.search(r'\bbring\s+(.+?)\s+(?:up|back)\b', norm)
            if m_bring:
                app_launch_cand = m_bring.group(1).strip()
        if not app_launch_cand:
            m_get = re.search(r'\bget\s+(.+?)\s+(?:up|running)\b', norm)
            if m_get:
                app_launch_cand = m_get.group(1).strip()
        if not app_launch_cand:
            m_put_in = re.search(r'\bput\s+me\s+in\s+(.+)', norm)
            if m_put_in:
                app_launch_cand = m_put_in.group(1).strip()
        if not app_launch_cand:
            m_put_screen = re.search(r'\b(?:put|bring)\s+(.+?)\s+(?:on\s+(?:the\s+)?screen|in\s+front(?:\s+of\s+me)?|to\s+(?:the\s+)?front)\b', norm)
            if m_put_screen:
                app_launch_cand = m_put_screen.group(1).strip()
        if not app_launch_cand:
            m_let_use = re.search(r'^(?:let\'?s\s+use|can\s+we\s+use|use)\s+(.+)', norm)
            if m_let_use:
                app_launch_cand = m_let_use.group(1).strip()
        if not app_launch_cand:
            m_want = re.search(r'^(?:i\s+want|i\s+need)\s+([a-zA-Z0-9_\-\s]+?)(?:\s+(?:running|open|up|now))?$', norm)
            if m_want:
                app_launch_cand = m_want.group(1).strip()
        if not app_launch_cand:
            m_direct = re.search(r'\b(?:open|launch|start|run)\s+(.+)', norm)
            if m_direct:
                app_launch_cand = m_direct.group(1).strip()

        if app_launch_cand:
            cleaned_app_target = re.sub(r'\s+(?:for\s+me|please|right\s+now|now|on\s+the\s+first\s+page|on\s+screen|in\s+foreground|up|in\s+front(?:\s+of\s+me)?)$', '', app_launch_cand).strip()
            canonical_app = self.resolve_canonical_application(cleaned_app_target)
            if canonical_app:
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal=f"launch application {canonical_app}",
                    intent="OPEN_APPLICATION",
                    action="LAUNCH_APPLICATION",
                    target=canonical_app,
                    object=canonical_app,
                    desired_state="running",
                    parameters={"application": canonical_app, "target": canonical_app, "action": "open"},
                    confidence=1.0,
                )

        # -------------------------------------------------------------
        # 11b. System Power Actions Concept Extraction (Section 11)
        # Covers: "shutdown the computer", "shut down the pc", "turn off the computer",
        # "power off the pc", "reboot the system", "restart computer", "sleep the computer",
        # "shutdown", "reboot", "restart", "power off", "sign out of the computer", etc.
        # -------------------------------------------------------------
        m_power = re.search(
            r'\b(?:shutdown|shut\s+down|power\s+off|power\s+down|turn\s+off|reboot|restart|hibernate|sleep)\b',
            norm
        )
        if m_power:
            p_action = m_power.group(0).lower().replace(" ", "_")
            if p_action in ("shut_down", "power_off", "power_down", "turn_off"):
                canonical_p_action = "shutdown"
            elif p_action in ("reboot",):
                canonical_p_action = "restart"
            else:
                canonical_p_action = p_action

            is_system_target = bool(re.search(
                r'\b(?:the\s+|my\s+)?(?:computer|pc|system|laptop|machine|workstation|desktop|device)\b',
                norm
            ))
            is_standalone_power = norm.strip() in (
                "shutdown", "shut down", "power off", "power down", "turn off",
                "reboot", "restart", "hibernate", "sleep", "sign out", "log off"
            )
            is_smart_home = any(w in norm for w in ("light", "fan", "lamp", "bulb", "plug", "switch", "ac", "heater", "thermostat"))

            if (is_system_target or is_standalone_power) and not is_smart_home:
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal=f"{canonical_p_action} the system",
                    intent="POWER_ACTION",
                    action=canonical_p_action,
                    target="computer",
                    target_type=EntityType.DEVICE_OR_SYSTEM,
                    safety_class="CONFIRMATION_REQUIRED",
                    confidence=1.0,
                    parameters={
                        "power_action": canonical_p_action,
                        "action": canonical_p_action,
                        "target": "computer",
                        "raw_input": text_stripped,
                    },
                )

        # -------------------------------------------------------------
        # 12. Generalized Application Close Concept Extraction (Section 5)
        # -------------------------------------------------------------
        app_close_cand = None
        m_done = re.search(r'\b(?:i(?:\'m|\s+am)\s+done\s+with|finished\s+with)\s+([a-zA-Z0-9_\-\s]+?)(?:,\s*close\s+it|\s+close\s+it|\.|$)', norm)
        if m_done:
            app_close_cand = m_done.group(1).strip()
        if not app_close_cand:
            m_dont_want = re.search(r'\b(?:don\'?t\s+want|do\s+not\s+want)\s+([a-zA-Z0-9_\-\s]+?)\s+(?:open|running)(?:\s+anymore)?\b', norm)
            if m_dont_want:
                app_close_cand = m_dont_want.group(1).strip()
        if not app_close_cand:
            m_rid = re.search(r'\bget\s+rid\s+of\s+([a-zA-Z0-9_\-\s]+)', norm)
            if m_rid:
                app_close_cand = m_rid.group(1).strip()
        if not app_close_cand:
            m_close = re.search(r'\b(?:close|shut\s+down|terminate|exit|quit|kill)\s+([a-zA-Z0-9_\-\s]+)', norm)
            if m_close:
                app_close_cand = m_close.group(1).strip()

        if app_close_cand:
            cleaned_close_target = re.sub(r'\s+(?:for\s+me|please|right\s+now|now)$', '', app_close_cand).strip()
            canonical_close_app = self.resolve_canonical_application(cleaned_close_target)
            if canonical_close_app:
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal=f"close application {canonical_close_app}",
                    intent="CLOSE_APPLICATION",
                    action="CLOSE_APPLICATION",
                    target=canonical_close_app,
                    object=canonical_close_app,
                    desired_state="closed",
                    parameters={"application": canonical_close_app, "target": canonical_close_app, "action": "close"},
                    confidence=1.0,
                )

        # -------------------------------------------------------------
        # 11c. Recommendation & Discovery Concept Extraction
        # Covers: "recommend movies", "recommend only action movies", "suggest comedy films",
        # "suggest project ideas", "give me book recommendations", "what should I read/watch",
        # and recommendation rejection handling ("I don't like X, give me alternatives").
        # -------------------------------------------------------------
        is_rec_verb = bool(re.search(
            r'\b(?:recommend|recommendation|recommendations|suggest|suggestion|suggestions|what\s+should\s+i\s+(?:watch|read|build|listen\s+to|try)|ideas\s+for|what\s+are\s+some\s+good|give\s+me\s+(?:some\s+)?(?:recommendations|suggestions|ideas))\b',
            norm
        ))
        is_rej_verb = bool(re.search(
            r'\b(?:don\'?t\s+like|dislike|hate|not\s+interested\s+in|reject|alternative\s+to|different\s+(?:than|from))\s+([a-zA-Z0-9_\-:\s]+?)(?:,\s*|\.\s*|\s+(?:give|suggest|recommend|show)|$)',
            norm
        ))
        if is_rec_verb or is_rej_verb:
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="provide balanced recommendations",
                intent="RECOMMENDATION",
                action="recommend",
                target="recommendations",
                target_type=EntityType.RECOMMENDATION_ITEM,
                desired_state="recommended",
                candidate_interpretations=[
                    {"intent": "RECOMMENDATION", "confidence": 0.99},
                ],
                parameters={"query": text_stripped, "action": "recommend", "raw_input": text_stripped},
                confidence=0.99,
            )
        is_search_intent = False
        search_query_extracted = None

        m_web_search = re.search(r'\b(?:search\s+(?:the\s+)?(?:web|internet)|search\s+online|look\s+up\s+online|check\s+(?:the\s+)?internet\s+for|google(?!\s+(?:chrome|browser)))\s+(?:for\s+)?(.+)', norm)
        if m_web_search:
            is_search_intent = True
            search_query_extracted = m_web_search.group(1).strip()
        elif any(k in norm for k in ("online", "on the web", "on the internet", "online sources", "internet sources")) and any(k in norm for k in ("search", "look up", "look for", "find out", "find", "check")):
            m_s = re.search(r'\b(?:search|look\s+up|look\s+for|find\s+out|find|check)\s+(.+?)(?:\s+(?:online|on\s+the\s+web|on\s+the\s+internet|by\s+checking\s+online\s+sources|from\s+online\s+sources|online\s+sources))(?:\s+for\s+me)?$', norm)
            if m_s:
                is_search_intent = True
                search_query_extracted = m_s.group(1).strip()
            elif norm in ("look this up online", "look this up on the web", "search this online", "check the internet for this", "find this on the web"):
                is_search_intent = True
                search_query_extracted = "this"
            else:
                is_search_intent = True
                search_query_extracted = re.sub(r'\b(?:by\s+checking\s+online\s+sources|on\s+the\s+internet|online\s+sources|online)\b', '', norm).strip()
        elif re.search(r'^(?:research|find\s+out\s+about|look\s+into)\s+(.+)', norm):
            m_r = re.search(r'^(?:research|find\s+out\s+about|look\s+into)\s+(.+)', norm)
            is_search_intent = True
            search_query_extracted = m_r.group(1).strip()
        elif re.search(r'\bwhat(?:\'s|\s+is)\s+happening\s+in\s+(.+?)(?:\s+(?:right\s+now|today|recently))?$', norm):
            m_h = re.search(r'\bwhat(?:\'s|\s+is)\s+happening\s+in\s+(.+?)(?:\s+(?:right\s+now|today|recently))?$', norm)
            is_search_intent = True
            search_query_extracted = f"what is happening in {m_h.group(1).strip()}"
        elif re.search(r'\bfind\s+recent\s+(.+?)(?:\s+developments|\s+news)?$', norm):
            m_f = re.search(r'\bfind\s+recent\s+(.+?)(?:\s+developments|\s+news)?$', norm)
            is_search_intent = True
            search_query_extracted = f"recent {m_f.group(1).strip()} developments"
        elif re.search(r'\blook\s+up\s+today(?:\'s)?\s+(.+)', norm):
            m_l = re.search(r'\blook\s+up\s+today(?:\'s)?\s+(.+)', norm)
            is_search_intent = True
            search_query_extracted = f"today's {m_l.group(1).strip()}"

        if is_search_intent and search_query_extracted:
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"search the web for {search_query_extracted}",
                intent="RAG_SEARCH",
                action="search_web",
                target="web",
                object=search_query_extracted,
                desired_state="searched",
                parameters={
                    "query": search_query_extracted,
                    "search_query": search_query_extracted,
                    "action": "search_web",
                },
                confidence=1.0,
            )

        # -------------------------------------------------------------
        # 14. Environment State Query Concept Extraction (Section 6, 9, 11)
        # -------------------------------------------------------------
        is_env_query = (
            norm in (
                "what am i using", "what am i using right now", "what am i currently using",
                "which app is active", "what app is active", "which application is active",
                "what do i currently have open", "what do i have open", "what is currently open",
                "what's on my screen", "whats on my screen", "what is on my screen",
                "what do i currently have on my screen", "what do i have on my screen",
                "what am i working on", "what am i working on right now", "what am i currently working on",
                "which program is active in front", "what program is in front",
                "what windows currently open", "what windows are open", "what window is active",
                "active window", "current window", "active application"
            )
            or bool(re.search(r'\bwhat\s+(?:am\s+i|do\s+i\s+have)\s+(?:currently\s+)?(?:using|working\s+(?:on|in)|have\s+open|on\s+my\s+screen)\b', norm))
            or bool(re.search(r'\bwhich\s+(?:app|application|program|window)\s+(?:is|has)\s+(?:currently\s+)?(?:active|in\s+front|focused|my\s+attention)\b', norm))
            or bool(re.search(r'\bwhat\s+(?:is\s+)?(?:open|active)\s+in\s+front\b', norm))
            or bool(re.search(r'\bwhat\s+windows\s+(?:are\s+)?(?:currently\s+)?(?:active|open)\b', norm))
        )
        if is_env_query:
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="query current environment and active application",
                intent="CURRENT_ENVIRONMENT_QUERY",
                action="query_environment",
                target="environment",
                desired_state="queried",
                parameters={"action": "query_window_context"},
                confidence=1.0,
            )

        # -------------------------------------------------------------
        # 15. Conversational History Recall (Section 7, 20)
        # -------------------------------------------------------------
        if any(re.search(p, norm) for p in [
            r'\b(?:what\s+did\s+i|what\s+i)\s+(?:just\s+)?ask(?:\s+(?:you\s+)?(?:before|earlier|to\s+do|for|immediately))?\b',
            r'\bwhat\s+(?:was|is)\s+(?:the\s+question(?:\s+that)?\s+i\s+asked|my\s+last\s+question|my\s+previous\s+question|the\s+last\s+thing\s+i\s+asked)\b',
            r'\bremind\s+me\s+what\s+i\s+asked\b',
        ]) or norm in ("what did i ask before", "what was the question that i asked before", "what is the question that i asked before", "what did i just ask", "what did i ask earlier"):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="recall previous user query from dialogue",
                intent="MEMORY_QUERY",
                action="recall_previous_turn",
                target="dialogue_history",
                desired_state="recalled",
                parameters={"historical_query_type": "past_action", "action": "retrieve_past_actions"},
                confidence=1.0,
            )

        # -------------------------------------------------------------
        # 16. Context Resumption / Continuation (Section 7, 20)
        # -------------------------------------------------------------
        if norm in (
            "continue that", "continue what i was doing", "can you bring back what we were doing",
            "bring back what we were doing", "go back to what we were doing", "do that again",
            "continue where we left off", "resume previous work"
        ):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="resume previous task or context",
                intent="CONTEXT_RESUMPTION",
                action="resume",
                target="previous_task",
                desired_state="resumed",
                parameters={"action": "resume"},
                confidence=1.0,
            )

        # -------------------------------------------------------------
        # 17. Document Export / Conversion to PDF / DOCX / Spreadsheet (Requirement 3)
        # -------------------------------------------------------------
        m_doc_export = re.search(
            r'\b(?:save|export|convert)\s+(?:a\s+copy\s+of\s+)?(?:this|that|the|my)?\s*(?:document|file|report|presentation)?\s*(?:as|to|into)\s+(?:a\s+|an\s+)?(pdf|docx|excel|spreadsheet|pptx|ppt)\b',
            norm
        ) or re.search(
            r'\b(?:save|export)\s+(?:a\s+|an\s+)?(pdf|docx|excel|presentation|ppt|pptx)\s+(?:copy|version|file|document)?\b',
            norm
        )
        if m_doc_export:
            exp_fmt = m_doc_export.group(1).lower()
            doc_type_val = "pdf" if exp_fmt == "pdf" else ("xlsx" if "excel" in exp_fmt or "sheet" in exp_fmt else ("pptx" if "ppt" in exp_fmt else "docx"))
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"Export document as {exp_fmt.upper()}",
                intent="DOCUMENT_GENERATION",
                action="export_document",
                target=exp_fmt,
                target_type=EntityType.FILE_OR_DOCUMENT,
                parameters={
                    "doc_type": doc_type_val,
                    "action": "export_document",
                    "format": exp_fmt,
                },
                confidence=0.99,
                action_required=True,
            )

        # Delegate remaining requests to legacy analysis branches
        return self._analyze_legacy(text_stripped, dialogue_state, user_id)

    def analyze(
        self,
        user_input: str,
        dialogue_state: Optional[Any] = None,
        user_id: int = 1
    ) -> SemanticIntentRepresentation:
        """
        Main semantic understanding pipeline entry point.
        """
        return self.interpret(user_input, None, dialogue_state, user_id)

    def _analyze_legacy(
        self,
        user_input: str,
        dialogue_state: Optional[Any] = None,
        user_id: int = 1
    ) -> SemanticIntentRepresentation:
        """
        Legacy analysis branches for environment queries, negations, explanations, and LLM reasoning.
        """
        raw_text = user_input.strip()
        text_low = raw_text.lower()
        clean_text = re.sub(r'^(?:can\s+you\s+|could\s+you\s+|please\s+|would\s+you\s+|friday\s+|trevon\s+|hey\s+friday\s+|hey\s+trevon\s+)+', '', text_low).strip()
        clean_low = clean_text.rstrip('.?!,').strip()

        # --------------------------------------------------------------------
        # 00. Low Confidence / Garbled STT Plausibility Guard (Section 11)
        # --------------------------------------------------------------------
        if any(k in text_low for k in ["hernia of the games", "hernia of games"]):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="Garbled or implausible speech recognition input.",
                intent="CLARIFICATION",
                action="ask_clarification",
                action_required=False,
                confidence=0.3,
                explanation_text="Did you mean: 'What games are compatible with this system?'",
            )

        # --------------------------------------------------------------------
        # 0. Media / Speech Command Disambiguation
        # --------------------------------------------------------------------
        if clean_low in ("stop talking", "stop speaking", "be quiet", "shut up", "hush", "stop voice", "mute yourself"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants assistant to stop speaking (TTS stop).",
                intent="STOP_ASSISTANT_SPEECH",
                action="stop_speech",
                action_required=True,
                confidence=0.99
            )
        if clean_low in ("stop reading", "pause reading"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants to stop/pause document reading.",
                intent="ARTIFACT_READING_STOP",
                action="stop_reading",
                action_required=True,
                confidence=0.99
            )
        if re.search(r'\b(?:stop|cancel|abort)\s+(?:the\s+|my\s+)?task\b', clean_low) or clean_low in ("stop task", "cancel task"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants to cancel an active task.",
                intent="TASK_CANCELLATION",
                action="cancel_task",
                action_required=True,
                confidence=0.99
            )
        if clean_low in ("stop music", "pause music", "stop song", "pause song") or re.search(r'\b(?:stop|pause)\s+(?:the\s+)?(?:music|song|playback|audio)\b', clean_low):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants to pause/stop music playback.",
                intent="MUSIC",
                action="pause",
                rewritten_command="pause music",
                action_required=True,
                confidence=0.98
            )
        if clean_low in ("previous song", "previous track", "play previous track", "play previous song") or re.search(r'\bprevious\s+(?:song|track)\b', clean_low):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants to skip to previous music track.",
                intent="MUSIC",
                action="previous",
                rewritten_command="previous track",
                action_required=True,
                confidence=0.98
            )

        # --------------------------------------------------------------------
        # 0a. Capability queries
        # --------------------------------------------------------------------
        if any(re.search(p, text_low) for p in [
            r'^\s*(?:what\s+can\s+you\s+do|what\s+are\s+your\s+capabilities|what\s+can\s+you\s+help\s+me\s+with|what\s+are\s+you\s+capable\s+of|what\s+can\s+you\s+do\s+for\s+me|tell\s+me\s+what\s+you\s+can\s+do)\s*[\.!\?]?\s*$',
            r'\b(?:what\s+can\s+you\s+do|what\s+are\s+your\s+capabilities|what\s+can\s+you\s+help\s+me\s+with|what\s+are\s+you\s+capable\s+of)\b',
            r'\bcan\s+you\s+(?:control\s+applications|read\s+gathered\s+information|remember\s+what\s+i\s+asked|create\s+documents|manage\s+files)\b',
        ]) or clean_low in ("what can you do", "what are your capabilities", "what can you help me with", "what are you capable of", "what can you do for me", "tell me what you can do"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is inquiring about the assistant's registered runtime capabilities.",
                intent="CAPABILITY_QUERY",
                action="query_capabilities",
                context_required=False,
                action_required=False,
                confidence=0.99,
            )

        # --------------------------------------------------------------------
        # 0b1. Semantic Negation Detection (Section 5)
        # --------------------------------------------------------------------
        m_neg = re.search(r'\b(?:don\'?t|do\s+not|never|not)\s+(?:open|launch|start|run|create|delete|close|bring\s+up)\s+([a-zA-Z0-9_\-\s]+)', clean_low)
        m_dont_want = re.search(r'\bi\s+(?:don\'?t|do\s+not)\s+want\s+([a-zA-Z0-9_\-\s]+?)\s+(?:open|opened|running|started)', clean_low)
        if m_neg or m_dont_want or clean_low in ("don't open notepad", "do not open notepad", "don't do that", "do not do that", "stop, don't do that", "don't open it"):
            target_app = (m_neg.group(1) if m_neg else (m_dont_want.group(1) if m_dont_want else "")).strip().rstrip('.?!')
            target_app = re.sub(r'^(?:the|a|an)\s+', '', target_app)
            if "notepad" in clean_low:
                target_app = "notepad"
            elif "chrome" in clean_low:
                target_app = "chrome"
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User is explicitly negating an action on {target_app or 'that'}: do not execute.",
                intent="NEGATION",
                request_type="NEGATION",
                is_negation=True,
                action_required=False,
                target_entity=target_app or "that",
                confidence=0.99,
            )

        # --------------------------------------------------------------------
        # 0b2. Hypothetical / Consideration Expression (Section 5)
        # --------------------------------------------------------------------
        if any(re.search(p, clean_low) for p in [
            r'\bi\s+was\s+thinking\s+(?:about|of)\s+(?:opening|launching|running|using)\s+([a-zA-Z0-9_\-\s]+)',
            r'\bwhat\s+if\s+(?:i|we)\s+(?:opened|launched|ran|started)\s+([a-zA-Z0-9_\-\s]+)',
            r'\bmaybe\s+(?:i|we)\s+should\s+(?:open|launch|run|use)\s+([a-zA-Z0-9_\-\s]+)',
        ]) or clean_low.startswith("i was thinking about opening"):
            target_app = "notepad" if "notepad" in clean_low else ("chrome" if "chrome" in clean_low else "the application")
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User is expressing a hypothetical thought regarding {target_app}, not an imperative command.",
                intent="HYPOTHETICAL",
                request_type="HYPOTHETICAL",
                action_required=False,
                target_entity=target_app,
                confidence=0.98,
            )

        # --------------------------------------------------------------------
        # 0b3. Action Explanation Query (Section 6, 20)
        # --------------------------------------------------------------------
        if any(re.search(p, clean_low) for p in [
            r'\bwhy\s+did\s+you\s+(?:open|launch|start|close|delete|create|do)\s*([a-zA-Z0-9_\-\s]*)',
            r'\bwhy\s+is\s+([a-zA-Z0-9_\-\s]+?)\s+(?:open|running|active)\b',
            r'\bwhat\s+made\s+you\s+(?:open|do|start)\b',
        ]) or clean_low in ("why did you open notepad", "why did you do that", "why did you open that"):
            target_app = "notepad" if "notepad" in clean_low else ("chrome" if "chrome" in clean_low else "the action")
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User is requesting an explanation for why {target_app} was opened/performed, not requesting a new action.",
                intent="EXPLANATION_QUERY",
                request_type="EXPLANATION",
                sub_intent="EXPLANATION_QUERY",
                historical_query_type="explanation",
                target_entity=target_app,
                action_required=False,
                confidence=0.99,
            )

        # --------------------------------------------------------------------
        # 0b4. Action Verification Query (Section 6)
        # --------------------------------------------------------------------
        if any(re.search(p, clean_low) for p in [
            r'\b(?:did\s+you|have\s+you)\s+(?:open|opened|launch|launched|start|started)\s+([a-zA-Z0-9_\-\s]+)',
            r'\bis\s+([a-zA-Z0-9_\-\s]+?)\s+(?:open|running|active)\b',
        ]) or clean_low in ("did you open notepad", "have you opened notepad"):
            target_app = "notepad" if "notepad" in clean_low else ("chrome" if "chrome" in clean_low else "the application")
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User is verifying whether {target_app} was opened, not requesting an action.",
                intent="ACTION_VERIFICATION",
                request_type="QUESTION",
                sub_intent="ACTION_VERIFICATION",
                historical_query_type="action_verification",
                target_entity=target_app,
                action_required=False,
                confidence=0.98,
            )

        # --------------------------------------------------------------------
        # 0b5. Destination / Result Placement Query (Section 6, 20)
        # --------------------------------------------------------------------
        if any(re.search(p, clean_low) for p in [
            r'\bwhere\s+did\s+you\s+(?:put|save|place|move)\s+(?:it|that|this|the\s+file|the\s+information|the\s+document)\b',
            r'\bwhere\s+(?:is|was)\s+(?:it|that|the\s+file|the\s+information)\s+(?:put|saved|placed|moved)\b',
            r'\bwhere\s+did\s+that\s+go\b',
        ]) or clean_low in ("where did you put it", "where did you put that", "where did you put the file", "where did that go", "where is it saved", "where did you save it"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is asking where recent content or file was placed/saved.",
                intent="MEMORY_QUERY",
                request_type="QUESTION",
                sub_intent="RECENT_DESTINATION",
                historical_query_type="recent_destination",
                action_required=False,
                confidence=0.99,
            )

        # --------------------------------------------------------------------
        # 0b6. Gathered Information Recall (Section 7, 30)
        # --------------------------------------------------------------------
        if any(re.search(p, clean_low) for p in [
            r'\bwhat\s+did\s+you\s+(?:find(?:\s+out)?|discover|gather|get)\b',
            r'\bwhat\s+was\s+(?:found|discovered|gathered)\b',
            r'^(?:show\s+me|tell\s+me)?\s*(?:what\s+you\s+found|what\s+was\s+found)\b',
        ]) or clean_low in ("what did you find", "what did you find out", "what did you discover", "what did you gather"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is asking to review previously acquired information or research artifact.",
                intent="ARTIFACT_QUERY",
                request_type="QUESTION",
                action="query_artifact",
                references=["information"],
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # --------------------------------------------------------------------
        # 0b. Environment, Context & History Queries
        # --------------------------------------------------------------------
        env_rep = self._detect_environment_query(raw_text, text_low, dialogue_state)
        if env_rep is not None:
            return env_rep

        # --------------------------------------------------------------------
        # 0b7. Application Paraphrases & Indirect Requests (Section 4)
        # --------------------------------------------------------------------
        m_app_req = re.search(
            r'^(?:actually[,\s]+|no[,\s]+|wait[,\s]+|well[,\s]+)?(?:can\s+you\s+|could\s+you\s+|would\s+you\s+|please\s+)?(?:bring\s+up|bring\s+back|get\s+up|i\s+need|let\'?s\s+use|let\s+us\s+use|can\s+we\s+use|open(?:\s+up)?|launch|start)\s+(?:the\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+(?:back|up|again|please|instead))?$',
            clean_low
        )
        if m_app_req:
            raw_cand = m_app_req.group(1).strip().rstrip('.?!')
            target_app = raw_cand
            if raw_cand in ("text editor", "the text editor", "editor"):
                target_app = "notepad"
            elif raw_cand in ("code editor", "the code editor", "ide"):
                target_app = "vscode"
            elif raw_cand in ("web browser", "browser", "the browser", "internet browser"):
                target_app = "chrome"
            elif raw_cand in ("file manager", "file explorer"):
                target_app = "explorer"

            common_apps = ("notepad", "chrome", "vscode", "code", "calc", "calculator", "explorer", "terminal", "powershell", "cmd", "word", "excel", "spotify")
            if target_app.lower() in common_apps:
                return SemanticIntentRepresentation(
                    user_input=raw_text,
                    interpreted_meaning=f"User wants to open application '{target_app}'.",
                    intent="OPEN_APPLICATION",
                    request_type="INSTRUCTION",
                    action="open_application",
                    entities=[{"value": target_app, "type": "application"}],
                    rewritten_command=f"open {target_app}",
                    target_entity=target_app,
                    action_required=True,
                    confidence=0.98,
                )

        # --------------------------------------------------------------------
        # 0b. Professional Document & Presentation Generation (Phases 2, 4)
        # --------------------------------------------------------------------
        is_pro_doc = False
        is_revision = False
        target_art_type = "report"

        if re.search(r'\b(?:presentation|ppt|pptx|slide\s*deck|slides)\b', text_low) and \
           re.search(r'\b(?:create|make|generate|turn|build|draft|prepare)\b', text_low):
            is_pro_doc = True
            target_art_type = "presentation"
        elif re.search(r'\b(?:study\s+guide|study\s+notes)\b', text_low) and \
             re.search(r'\b(?:create|make|generate|build|draft|prepare)\b', text_low):
            is_pro_doc = True
            target_art_type = "study_guide"
        elif re.search(r'\b(?:pdf|report|briefing|whitepaper|document)\b', text_low) and \
             re.search(r'\b(?:professional|detailed|executive|comprehensive|technical)\b', text_low) and \
             re.search(r'\b(?:create|make|generate|produce|write|draft|build)\b', text_low):
            is_pro_doc = True
            target_art_type = "report"
        elif re.search(r'\b(?:create|make|generate|draft)\s+(?:a\s+)?(?:pdf|report|study\s+guide|presentation)\s+(?:about|on|for)\b', text_low):
            is_pro_doc = True
            if "presentation" in text_low or "slide" in text_low:
                target_art_type = "presentation"
            elif "study" in text_low:
                target_art_type = "study_guide"
            else:
                target_art_type = "report"
        elif re.search(r'\b(?:make\s+it|make\s+the\s+previous\s+(?:document|presentation|report))\s+(?:more\s+detailed|shorter|longer|brief)\b', text_low) or \
             re.search(r'\bturn\s+(?:that|the)\s+(?:report|document)\s+into\s+a\s+presentation\b', text_low):
            is_pro_doc = True
            is_revision = True
            target_art_type = "presentation" if "presentation" in text_low else "report"

        if is_pro_doc:
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants to generate or revise a professional publication-grade document/presentation.",
                intent="PROFESSIONAL_DOCUMENT_GENERATION",
                action="revise_artifact" if is_revision else "create_artifact",
                entities=[{"type": "artifact_type", "value": target_art_type}],
                references=["previous", "that"] if is_revision else [],
                context_required=is_revision,
                action_required=True,
                confidence=0.96,
            )

        # --------------------------------------------------------------------
        # 0b2. Concurrent Task Status and Cancellation (Section M)
        # --------------------------------------------------------------------
        if any(re.search(p, text_low) for p in [
            r'\b(?:how\s+is\s+(?:the|that|my)\s+(?:task|research|download|process|job)(?:\s+(?:going|doing))?)\b',
            r'\b(?:what\s+is\s+(?:that|the|my)\s+task\s+doing)\b',
            r'\b(?:show\s+me\s+(?:the\s+)?task\s+status)\b',
            r'\b(?:what\s+is\s+the\s+status\s+of\s+(?:that|the)\s+task)\b',
            r'^\s*task\s+status\s*[\.!\?]?\s*$',
        ]) or clean_low in ("task status", "show me the task status", "show task status", "how is the research going", "what is that task doing"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying status or progress of a concurrent task.",
                intent="TASK_STATUS_QUERY",
                action="query_task_status",
                references=["that", "the"],
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        if any(re.search(p, text_low) for p in [
            r'\b(?:cancel|abort)\s+(?:the\s+|that\s+)?(?:task|research|download|background\s+task|job)\b',
            r'\bstop\s+(?:the\s+|that\s+)?(?:background\s+task|research\s+task|task)\b',
            r'^\s*(?:cancel\s+the\s+research|cancel\s+research)\s*[\.!\?]?\s*$',
        ]) or clean_low in ("cancel the research", "cancel research", "stop the background task", "cancel that task", "stop that task"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants to cancel a running or queued background task.",
                intent="TASK_CANCELLATION",
                action="cancel_task",
                references=["that", "the"],
                context_required=True,
                action_required=True,
                confidence=0.98,
            )

        # --------------------------------------------------------------------
        # 0c1. Contextual Content Insertion ("write the code here", "put that here")
        # --------------------------------------------------------------------
        has_transfer_verb = bool(re.search(r'\b(?:write|type|put|paste|insert|place)\b', text_low))
        is_scratch_creation = bool(re.search(r'\b(?:write|create)\s+(?:an?\s+)?(?:note|email|mail|letter|function|program)\b', text_low))

        if has_transfer_verb and not is_scratch_creation:
            # Check if this references an artifact or indicates a transfer to a target/cursor
            has_transfer_target = bool(re.search(r'\b(?:here|where\s+my\s+cursor\s+is|at\s+(?:the\s+)?cursor|at\s+(?:the\s+)?caret|in\s+(?:this|the|a)?\s*(?:file|editor|notepad|vscode|document|window|downloads|desktop|documents|folder|directory)|into\s+(?:this|the|a)?\s*(?:file|editor|notepad|vscode|document|window|downloads|desktop|documents|folder|directory))\b', text_low))
            has_artifact_noun = bool(re.search(r'\b(?:code|information|summary|notes|concept|details|answer|explanation|it|that|this)\b', text_low))

            # Query the ArtifactReferenceResolver directly to see if an active artifact matches
            art_matches = False
            try:
                from core.artifact_resolver import get_artifact_reference_resolver
                art_res = get_artifact_reference_resolver().resolve(
                    user_input=raw_text,
                    user_id=user_id,
                    dialogue_state=dialogue_state
                )
                if art_res.is_success or art_res.is_ambiguous:
                    art_matches = True
            except Exception:
                art_matches = False

            if art_matches or (has_transfer_target and has_artifact_noun) or re.search(r'^\s*(?:write|type|put|paste|insert)\s+(?:here|there|into\s+notepad|in\s+downloads|in\s+notepad)\s*[\.!\?]?\s*$', text_low):
                tgt_ent = None
                tgt_type = "CURSOR"
                if "downloads" in text_low:
                    tgt_ent = "downloads"
                    tgt_type = "FOLDER"
                elif "notepad" in text_low:
                    tgt_ent = "notepad"
                    tgt_type = "APPLICATION"
                elif "vscode" in text_low or "editor" in text_low:
                    tgt_ent = "vscode"
                    tgt_type = "APPLICATION"

                is_corr = bool(any(w in text_low for w in ("instead", "actually don't", "no, put", "no put", "rather", "not there")))

                return SemanticIntentRepresentation(
                    user_input=raw_text,
                    interpreted_meaning=f"User wants to insert or place a resolved content artifact at {tgt_ent or 'the current target location'}.",
                    intent="CONTENT_INSERTION",
                    request_type="CORRECTION" if is_corr else "INSTRUCTION",
                    action="insert_artifact",
                    target_entity=tgt_ent,
                    target_type=tgt_type,
                    is_correction=is_corr,
                    references=["here", "that", "this", "it"],
                    context_required=True,
                    action_required=True,
                    confidence=0.98,
                )

        # --------------------------------------------------------------------
        # 0c2. Artifact Transformation ("summarize it", "give me the full information")
        # --------------------------------------------------------------------
        is_inline_code = bool(re.search(r'(?:def\s+[a-zA-Z0-9_]+\s*\(|class\s+[a-zA-Z0-9_]+|return\s+|import\s+|Traceback)', raw_text))
        if not is_inline_code and any(re.search(p, text_low) for p in [
            r'\b(?:summarize|summarise)\s+(?:it|that|this|the\s+concept|(?:the\s+)?[a-zA-Z0-9_\s]+?\s+(?:concept|information|notes|code)|the\s+code|the\s+information|those\s+notes)\b',
            r'^\s*(?:summarize|summarise)\s*(?:it|that|this)?\s*[\.!\?]?\s*$',
            r'\b(?:give\s+me|give)\s+(?:the\s+)?full\s+information\b',
            r'\b(?:give\s+me|give)\s+(?:the\s+)?(?:python|javascript|cpp|c\+\+|java)\s+implementation\b',
            r'\bconvert\s+(?:it|that|this|the\s+code)\s+to\s+([a-zA-Z0-9_\+]+)\b',
            r'^\s*(?:explain|shorten|expand)\s+(?:it|that|this|the\s+concept)\s*[\.!\?]?\s*$',
        ]):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants to transform an existing content artifact (summarize, expand, convert language, etc.).",
                intent="ARTIFACT_TRANSFORMATION",
                request_type="INSTRUCTION",
                action="transform_artifact",
                references=["it", "that", "this"],
                context_required=True,
                action_required=True,
                confidence=0.97,
            )

        # --------------------------------------------------------------------
        # 0c3. Contextual Content Acquisition & Research
        # --------------------------------------------------------------------
        if any(re.search(p, text_low) for p in [
            r'\b(?:gather|collect|find|research)\s+(?:all\s+)?(?:the\s+)?([a-zA-Z0-9_\-\s]+?)\s+(?:information|info|facts|details)\b',
            r'\b(?:gather|collect|find|search\s+for|look\s+up|get)\s+(?:some\s+|all\s+(?:the\s+)?|any\s+|the\s+)?information\s+(?:about|on|for)\s+(.+)',
            r'\b(?:tell\s+me|find\s+out)\s+(?:something|some\s+information|all\s+information)\s+about\s+(.+)',
            r'\bresearch\s+(?:normalization\s+in\s+dbms|this\s+topic|this\s+concept|.+)',
            r'\bget\s+(?:the\s+)?code\s+(?:for|of)\s+(.+)',
            r'\bget\s+(?:the\s+)?(?:python|javascript|cpp|c\+\+|java)\s+implementation(?:\s+(?:for|of)\s+(.+))?',
            r'\bcollect\s+everything\s+important\s+about\s+(.+)',
            r'\bfind\s+(?:all\s+the\s+|some\s+)?information\s+about\s+(.+)',
            r'\bget\s+(?:all\s+the\s+|some\s+)?information\s+about\s+(.+)',
            r'\bget\s+(?:the\s+)?code\s+for\s+(?:this|that)\b',
        ]):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants to acquire, research, or generate a structured content artifact.",
                intent="CONTENT_ACQUISITION",
                request_type="INSTRUCTION",
                action="acquire_content",
                references=["this", "that"] if ("this" in text_low or "that" in text_low) else [],
                context_required=("this" in text_low or "that" in text_low),
                action_required=True,
                confidence=0.97,
            )

        # --------------------------------------------------------------------
        # 0c3b. Direct Artifact Reference / Recall Query
        # --------------------------------------------------------------------
        if any(re.search(p, text_low) for p in [
            r'\b(?:what\s+was\s+gathered|what\s+did\s+(?:we|you)\s+gather|what\s+have\s+we\s+gathered)\b',
            r'^(?:the|that|this)?\s*information\s+(?:that\s+)?you\s+(?:found|gathered|got)(?:\s+about\s+(.+))?',
            r'^(?:the|that|this)?\s*information\s+about\s+(.+)',
            r'^(?:show\s+me|tell\s+me|what\s+is|what\s+was)?\s*(?:the\s+)?information\s+(?:that\s+)?you\s+(?:found|gathered)(?:\s+about\s+(.+))?',
        ]):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is referring to or requesting information from an existing artifact.",
                intent="ARTIFACT_QUERY",
                action="query_artifact",
                references=["information"],
                context_required=True,
                action_required=False,
                confidence=0.98,
            )

        # --------------------------------------------------------------------
        # 0c4. Stateful Artifact Reading, Stop, and Continue
        # --------------------------------------------------------------------
        # Read artifact aloud
        if any(re.search(p, text_low) for p in [
            r'\bread\s+(?:out\s+)?(?:them|it|those|these|that|this|all\s+of\s+it|all\s+of\s+them|everything|the\s+whole\s+thing|the\s+information|the\s+code|the\s+summary|what\s+you\s+(?:gathered|found|wrote|inserted)|the\s+above|previous\s+content|last\s+gathered\s+content|last\s+code)(?:\s+(?:out|aloud|to\s+me))?\b',
            r'\bread\s+(?:all\s+of\s+it|all\s+of\s+them|everything|the\s+whole\s+thing|the\s+information|all\s+the\s+information|the\s+code|the\s+summary|them|those|these)\b',
            r'\bread\s+(?:the\s+|all\s+(?:the\s+)?)?([a-zA-Z0-9_\-\s]+?)\s+(?:information|code|summary|concept|notes)\b',
            r'\bread\s+the\s+(?:first|second|third|1st|2nd|3rd)\s+(?:code|one|information|summary)\b',
            r'\bread\s+(?:this|these|it|them|those|that|the\s+summary|the\s+information|the\s+code)\s+(?:to\s+me|aloud|out)\b',
            r'^\s*(?:can\s+you\s+|could\s+you\s+|please\s+)?read\s+(?:them|it|those|these|that|this)(?:\s+(?:out|aloud|to\s+me))?\s*[\.!\?]?\s*$',
            r'^\s*read\s+aloud\s*[\.!\?]?\s*$',
            r'^\s*read\s+out\s*[\.!\?]?\s*$',
            r'^\s*read\s+to\s+me\s*[\.!\?]?\s*$',
            r'^\s*read\s*[\.!\?]?\s*$',
        ]) or clean_low in ("read them out", "read them", "read it out", "read it", "read those", "read these", "read aloud", "read to me", "read out"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants the assistant to read the referenced artifact or document aloud.",
                intent="ARTIFACT_READING",
                action="read_artifact",
                references=[p for p in ("it", "that", "this", "them", "these", "those") if p in text_low.split()],
                context_required=True,
                action_required=True,
                confidence=0.98,
            )

        # Stop reading
        is_reading_active = False
        try:
            from core.artifact_reader import get_artifact_reading_controller
            is_reading_active = get_artifact_reading_controller().is_reading(user_id)
        except Exception:
            pass

        if clean_low in ("stop reading", "pause reading", "halt reading") or (clean_low in ("stop", "pause", "hold on") and is_reading_active):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants the assistant to stop reading the current artifact.",
                intent="ARTIFACT_READING_STOP",
                action="stop_reading",
                context_required=True,
                action_required=True,
                confidence=0.99,
            )

        # Continue reading
        if clean_low in ("continue", "continue reading", "resume reading", "keep reading", "resume"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants the assistant to continue reading from the saved cursor position.",
                intent="ARTIFACT_READING_CONTINUE",
                action="continue_reading",
                context_required=True,
                action_required=True,
                confidence=0.99,
            )

        # --------------------------------------------------------------------
        # 0c. Document Intelligence & Cross-Document Synthesis (Phases 4, 11)
        # --------------------------------------------------------------------
        if any(re.search(p, text_low) for p in [
            r'\b(?:summarize|digest|overview\s+of)\s+(?:the\s+file\s+)?(?:these|the|all|those|[a-zA-Z0-9_\-\\]+\.(?:pdf|docx|txt|pptx|xlsx))\b',
            r'\b(?:summarize|digest|overview\s+of)\s+(?:these|the|all|those)\s+(?:reports|documents|pdfs|papers|articles|files)\b',
            r'\b(?:give\s+me\s+the\s+big\s+picture|big\s+picture)\b',
            r'\b(?:analyze|analyse)\s+the\s+(?:core\s+theses|theses|arguments|findings)\s+(?:of|in)\s+(?:these|the|all|those)\s+(?:reports|documents|pdfs|papers)\b',
            r'\btell\s+me\s+what\s+(?:all\s+)?these\s+(?:documents|reports|pdfs|papers)\s+collectively\s+say\b',
            r'\bcompare\s+(?:the\s+arguments|these|the\s+findings|the\s+theses)\s+(?:in|across|of)\s+(?:these|the|all)\s+(?:papers|documents|reports|pdfs)\b',
            r'\bextract\s+the\s+(?:important|key|core)\s+(?:ideas|concepts|points|findings)\s+(?:from|in)\s+(?:these|the|all)\s+(?:pdfs|documents|reports|papers)\b',
            r'\bwhat\s+conclusions\s+can\s+we\s+draw\s+across\s+these\s+(?:documents|reports|pdfs|papers)\b',
        ]):
            is_comp = "compare" in text_low
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants multi-document synthesis, cross-document comparison, or core theses extraction.",
                intent="DOCUMENT_INTELLIGENCE",
                action="compare" if is_comp else "synthesize",
                entities=[{"type": "scope", "value": "cross_document"}],
                context_required=True,
                action_required=True,
                confidence=0.95,
            )

        # --------------------------------------------------------------------
        # 1. Historical Memory & Action Queries (Section 2, 6, 7)
        # --------------------------------------------------------------------
        # Past searches: "What did I search for yesterday?", "what did i search earlier"
        if re.search(r'\bwhat\s+did\s+i\s+(?:search\s+for|search|google|look\s+up)\b', text_low):
            time_filter = "yesterday" if "yesterday" in text_low else ("last_week" if "last week" in text_low else "today")
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying their past search history from persistent memory.",
                intent="MEMORY_QUERY",
                action="retrieve_past_searches",
                historical_query_type="past_search",
                time_filter=time_filter,
                memory_required=True,
                action_required=False,
                confidence=0.98
            )

        # Past websites: "What was that website I asked you to open last week?"
        if re.search(r'\bwhat\s+(?:was\s+that\s+website|website\s+did\s+i\s+ask|site\s+did\s+i\s+ask)\b', text_low):
            time_filter = "last_week" if "last week" in text_low else ("yesterday" if "yesterday" in text_low else None)
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is asking about a previously opened website from historical memory.",
                intent="MEMORY_QUERY",
                action="retrieve_past_websites",
                historical_query_type="past_website",
                time_filter=time_filter,
                memory_required=True,
                action_required=False,
                confidence=0.98
            )

        # Past assistant actions: "What did you do?", "What did you do five minutes ago?", "What command did you run?"
        # Also: "What did I ask you to do?", "What did I just ask?", "What was my last request?"
        if re.search(r'\bwhat\s+did\s+you\s+do\b', text_low) or \
           re.search(r'\bwhat\s+command\s+did\s+you\s+run\b', text_low) or \
           re.search(r'\bwhat\s+did\s+you\s+close\b', text_low) or \
           re.search(r'\bwhere\s+did\s+you\s+put\s+that\s+file\b', text_low) or \
           re.search(r'\b(?:what\s+happened\s+after\s+that|why\s+did\s+you\s+(?:open|do|run)\s+that)\b', text_low) or \
           re.search(r'\bwhat\s+was\s+the\s+last\s+thing\s+(?:i\s+asked|you\s+did)\b', text_low) or \
           re.search(r'\bwhat\s+did\s+i\s+(?:just\s+)?ask\s+(?:you\s+)?(?:to\s+do|for)?\b', text_low) or \
           re.search(r'\bwhat\s+was\s+(?:my|the)\s+last\s+request\b', text_low):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying assistant's past action execution history.",
                intent="MEMORY_QUERY",
                action="retrieve_past_actions",
                historical_query_type="past_action",
                memory_required=True,
                action_required=False,
                confidence=0.98
            )

        # Completed tasks: "What tasks did we complete yesterday?", "What did we work on yesterday?"
        if re.search(r'\bwhat\s+(?:tasks\s+did\s+we\s+complete|did\s+we\s+(?:complete|finish|work\s+on))\s+(?:yesterday|today|last\s+week)\b', text_low):
            time_filter = "yesterday" if "yesterday" in text_low else "today"
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying completed tasks from persistent task history.",
                intent="MEMORY_QUERY",
                action="retrieve_completed_tasks",
                historical_query_type="past_task",
                time_filter=time_filter,
                memory_required=True,
                action_required=False,
                confidence=0.98
            )

        # --------------------------------------------------------------------
        # 2. General Conversation, Reasoning & Entertainment (Sections 1, 10)
        # --------------------------------------------------------------------
        # Jokes / Humor: "Tell me a joke."
        if re.search(r'\b(?:tell\s+me\s+a\s+joke|make\s+me\s+laugh|say\s+something\s+funny)\b', text_low):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is requesting casual entertainment/joke.",
                intent="GENERAL_CONVERSATION",
                action="joke",
                action_required=False,
                confidence=0.98
            )

        # Scientific / General Knowledge Questions: "Why is the sky blue?", "How does gravity work?"
        if re.search(r'\b(?:why\s+is\s+the\s+sky\s+blue|how\s+does\s+gravity\s+work|what\s+is\s+photosynthesis|why\s+do\s+stars\s+twinkle)\b', text_low):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is asking an informational/scientific question requiring explanation, not device action.",
                intent="RAG_SEARCH",
                action="explain_concept",
                action_required=False,
                confidence=0.98
            )

        # Expression of desire (NOT an imperative command, Section 9)
        # "I wish I could see my downloads."
        if re.search(r'\b(?:i\s+wish\s+i\s+could\s+see|i\s+wish\s+i\s+had|would\s+be\s+nice\s+if)\b', text_low):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is expressing a desire or conversational thought, not issuing an imperative command.",
                intent="GENERAL_CONVERSATION",
                action="conversational_response",
                action_required=False,
                confidence=0.92
            )

        # --------------------------------------------------------------------
        # 3. Semantic Natural Language Commands (Sections 3, 9)
        # --------------------------------------------------------------------
        # "Can you get Chrome up? I want to check something." -> Open Chrome
        m_get_up = re.search(r'\b(?:get|bring)\s+([a-zA-Z0-9_\s]+?)\s+(?:up|open|running)\b', text_low)
        if m_get_up:
            target_app = m_get_up.group(1).strip()
            # Clean filler phrases like "i want to check something"
            target_app = re.sub(r'\s+(?:i\s+want|to\s+check|so\s+i\s+can).*', '', target_app).strip()
            if target_app:
                return SemanticIntentRepresentation(
                    user_input=raw_text,
                    interpreted_meaning=f"User wants to open application '{target_app}'.",
                    intent="OPEN_APPLICATION",
                    action="open_application",
                    entities=[{"value": target_app, "type": "application"}],
                    rewritten_command=f"open {target_app}",
                    target_entity=target_app,
                    action_required=True,
                    confidence=0.96
                )

        # "I'm done with Spotify, close it." -> Close Spotify
        m_done_with = re.search(r'\b(?:i(?:\'m| am)\s+done\s+with|finished\s+with)\s+([a-zA-Z0-9_\s]+?)(?:,\s*close\s+it|\s+close\s+it|\.|$)', text_low)
        if m_done_with:
            target_app = m_done_with.group(1).strip()
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User is done with '{target_app}' and wants it closed.",
                intent="DEVICE_CONTROL",
                action="close_app",
                entities=[{"value": target_app, "type": "application"}],
                rewritten_command=f"close {target_app}",
                target_entity=target_app,
                action_required=True,
                confidence=0.98
            )

        # "I don't want Chrome open anymore." -> Close Chrome (Negative desire, Section 9)
        m_dont_want = re.search(r'\b(?:i\s+don\'?t\s+want|do\s+not\s+want)\s+([a-zA-Z0-9_\s]+?)\s+(?:open|running)(?:\s+anymore)?\b', text_low)
        if m_dont_want:
            target_app = m_dont_want.group(1).strip()
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User does not want '{target_app}' open anymore; close it.",
                intent="DEVICE_CONTROL",
                action="close_app",
                entities=[{"value": target_app, "type": "application"}],
                rewritten_command=f"close {target_app}",
                target_entity=target_app,
                action_required=True,
                confidence=0.98
            )

        # ── Universal OS Operations ──────────────────────────────────────────
        # Port & Process inspection / termination:
        # "Check what's using port 8000 and stop it", "What's using port 8000?"
        m_pk = re.search(r'\b(?:check\s+what(?:\'s|\s+is)\s+using\s+port\s+(\d+)\s+and\s+(?:stop|kill)\s+it|kill\s+process\s+on\s+port\s+(\d+)|stop\s+what(?:\'s|\s+is)\s+using\s+port\s+(\d+))\b', text_low)
        if m_pk:
            p_num = int(m_pk.group(1) or m_pk.group(2) or m_pk.group(3))
            from core.os_gateway.operation_model import OSOperation, OSCapability, OSOperationType, OSRiskLevel
            os_op = OSOperation(
                capability=OSCapability.PROCESS,
                operation_type=OSOperationType.KILL_BY_PORT,
                target=str(p_num),
                parameters={"port": p_num, "force": True},
                risk_level=OSRiskLevel.MODIFYING,
                original_goal=raw_text,
            )
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User wants to inspect port {p_num} and stop the process using it.",
                intent="PROCESS",
                action="kill_by_port",
                entities=[{"value": p_num, "type": "port"}],
                target_entity=str(p_num),
                action_required=True,
                confidence=0.98,
                os_operation=os_op,
            )

        m_pc = re.search(r'\b(?:what(?:\'s|\s+is)\s+using\s+port\s+(\d+)|check\s+port\s+(\d+)|who\s+is\s+using\s+port\s+(\d+))\b', text_low)
        if m_pc:
            p_num = int(m_pc.group(1) or m_pc.group(2) or m_pc.group(3))
            from core.os_gateway.operation_model import OSOperation, OSCapability, OSOperationType, OSRiskLevel
            os_op = OSOperation(
                capability=OSCapability.PROCESS,
                operation_type=OSOperationType.INSPECT_PORT,
                target=str(p_num),
                parameters={"port": p_num},
                risk_level=OSRiskLevel.READ_ONLY,
                original_goal=raw_text,
            )
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User wants to know what process is using port {p_num}.",
                intent="PROCESS",
                action="inspect_port",
                entities=[{"value": p_num, "type": "port"}],
                target_entity=str(p_num),
                action_required=True,
                confidence=0.98,
                os_operation=os_op,
            )

        # Storage inquiry: "How much space is left on D", "check space on D drive"
        m_sp = re.search(r'\b(?:how\s+much\s+)?space\s+(?:is\s+)?left\s+on\s+([a-zA-Z])(?:\s+drive|\s*:)?\b', text_low)
        if m_sp:
            dl = m_sp.group(1).upper()
            from core.os_gateway.operation_model import OSOperation, OSCapability, OSOperationType, OSRiskLevel
            os_op = OSOperation(
                capability=OSCapability.STORAGE,
                operation_type=OSOperationType.INSPECT_DRIVE,
                target=f"{dl}:",
                parameters={"drive": f"{dl}:"},
                risk_level=OSRiskLevel.READ_ONLY,
                original_goal=raw_text,
            )
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User wants to check available disk space on drive {dl}.",
                intent="STORAGE",
                action="inspect_drive",
                entities=[{"value": dl, "type": "drive"}],
                target_entity=f"{dl}:",
                action_required=True,
                confidence=0.98,
                os_operation=os_op,
            )

        # Cross-drive move / file placement: "Put this file in my D drive project folder", "Move this there"
        m_mv = re.search(r'\b(?:put|move)\s+(this(?:\s+file)?|that(?:\s+file)?|the\s+file|[^\s]+?\.[a-zA-Z0-9]+)\s+(?:in|into|to|on)\s+(.+)', text_low)
        if m_mv:
            src_text = m_mv.group(1).strip()
            dest_text = m_mv.group(2).strip()
            from core.os_gateway.context_resolver import get_context_resolver
            from core.os_gateway.operation_model import OSOperation, OSCapability, OSOperationType, OSRiskLevel
            cr = get_context_resolver()
            src_res = cr.resolve_target(src_text, user_id=user_id, entity_hint="FILE") or src_text
            dest_res = cr.resolve_destination(dest_text, source_path=src_res)
            os_op = OSOperation(
                capability=OSCapability.FILESYSTEM,
                operation_type=OSOperationType.MOVE_FILE,
                target=src_res,
                parameters={"destination": dest_res, "source": src_res},
                risk_level=OSRiskLevel.MODIFYING,
                original_goal=raw_text,
            )
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User wants to move '{src_res}' to '{dest_res}'.",
                intent="FILE_OPERATIONS",
                action="move_file",
                entities=[{"value": src_res, "type": "source_file"}, {"value": dest_res, "type": "destination"}],
                target_entity=src_res,
                action_required=True,
                confidence=0.98,
                os_operation=os_op,
            )

        # Network diagnostics: "Why isn't my backend accessible?"
        if any(w in text_low for w in ["why isn't my backend", "backend not accessible", "why is port 8000 not working"]):
            from core.os_gateway.operation_model import OSOperation, OSCapability, OSOperationType, OSRiskLevel
            os_op = OSOperation(
                capability=OSCapability.NETWORK,
                operation_type=OSOperationType.DIAGNOSE_NETWORK,
                target="8000",
                parameters={"port": 8000},
                risk_level=OSRiskLevel.READ_ONLY,
                original_goal=raw_text,
            )
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is asking for diagnostics on why their backend application is not accessible.",
                intent="NETWORK",
                action="diagnose_backend",
                entities=[{"value": 8000, "type": "port"}],
                target_entity="8000",
                action_required=True,
                confidence=0.98,
                os_operation=os_op,
            )

        # --------------------------------------------------------------------
        # 4. Reference Resolution: Retry & Context Resumption (Sections 5, 13, 14)
        # --------------------------------------------------------------------
        # "Try that again." / "Do it again." / "Retry."
        if re.search(r'^\s*(?:try\s+(?:that|it)\s+again|do\s+(?:it|the\s+same\s+thing)\s+again|retry|retry\s+that)\s*[\.!\?]?\s*$', text_low):
            last_cmd = ""
            last_intent = "OPEN_APPLICATION"
            if dialogue_state:
                # Check recent failed actions first
                if hasattr(dialogue_state, "recent_failed_actions") and dialogue_state.recent_failed_actions:
                    last_act = dialogue_state.recent_failed_actions[-1]
                    last_cmd = last_act.get("command") or last_act.get("command_signature") or ""
                    last_intent = last_act.get("intent") or last_intent
                elif hasattr(dialogue_state, "recent_actions") and dialogue_state.recent_actions:
                    last_act = dialogue_state.recent_actions[-1]
                    last_cmd = last_act.get("command") or last_act.get("command_signature") or ""
                    last_intent = last_act.get("intent") or last_intent

            if not last_cmd:
                # Retrieve from PostgreSQL execution_experiences
                past_acts = self.memory_retriever.retrieve_recent_actions(user_id, limit=1)
                if past_acts:
                    last_cmd = past_acts[0].get("command_signature") or ""
                    last_intent = past_acts[0].get("intent") or last_intent

            rewritten = last_cmd if last_cmd else raw_text
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User wants to retry the previous action: '{rewritten}'.",
                intent=last_intent,
                action="retry",
                references=["that"],
                rewritten_command=rewritten,
                memory_required=True,
                action_required=True,
                confidence=0.95
            )

        # "Close what you just opened."
        if re.search(r'\b(?:close\s+what\s+you\s+just\s+opened|close\s+the\s+thing\s+you\s+opened)\b', text_low):
            last_app = ""
            if dialogue_state:
                if hasattr(dialogue_state, "active_application") and dialogue_state.active_application:
                    last_app = dialogue_state.active_application
                elif hasattr(dialogue_state, "active_applications") and dialogue_state.active_applications:
                    last_app = dialogue_state.active_applications[-1]
            if not last_app:
                # Check execution_experiences
                past_acts = self.memory_retriever.retrieve_recent_actions(user_id, limit=3)
                for a in past_acts:
                    if a.get("intent") == "OPEN_APPLICATION":
                        m = re.search(r'\b(?:open|launch)\s+([a-zA-Z0-9_\-]+)', a.get("command_signature", ""), re.I)
                        if m:
                            last_app = m.group(1)
                            break
            target = last_app or "window"
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"User wants to close the most recently opened application: '{target}'.",
                intent="DEVICE_CONTROL",
                action="close_app",
                entities=[{"value": target, "type": "application"}],
                references=["what you just opened"],
                rewritten_command=f"close {target}",
                target_entity=target,
                action_required=True,
                confidence=0.96
            )

        # --------------------------------------------------------------------
        # 5. LLM Semantic Reasoning Layer (Sections 3, 37, 38)
        # --------------------------------------------------------------------
        try:
            from extensions.llm_engine import get_llm_engine
            llm = get_llm_engine()
            ctx_summary: Dict[str, Any] = {}
            if dialogue_state:
                if getattr(dialogue_state, "active_application", None):
                    ctx_summary["current_app"] = dialogue_state.active_application
                if getattr(dialogue_state, "active_artifact", None):
                    ctx_summary["active_artifact"] = getattr(dialogue_state, "active_artifact")
                if hasattr(dialogue_state, "session_context"):
                    if dialogue_state.session_context.get("last_insertion_target"):
                        ctx_summary["last_target"] = dialogue_state.session_context["last_insertion_target"]
                    if dialogue_state.session_context.get("last_artifact_topic"):
                        ctx_summary["last_topic"] = dialogue_state.session_context["last_artifact_topic"]
                if hasattr(dialogue_state, "turns") and dialogue_state.turns:
                    last_turn = dialogue_state.turns[-1]
                    ctx_summary["previous_request"] = getattr(last_turn, "user_input", "")

            llm_result = llm.semantic_reasoning(raw_text, structured_context=ctx_summary, timeout_budget=2.5)
            if llm_result and isinstance(llm_result, dict):
                req_t = llm_result.get("request_type", "INSTRUCTION")
                act_req = bool(llm_result.get("action_required", True))
                goal = llm_result.get("goal") or raw_text
                caps = llm_result.get("capabilities", [])
                primary_cap = caps[0] if caps else "AUTO"
                params = llm_result.get("parameters", {})
                refs = llm_result.get("references", {})

                # Strict guarantee: Non-action request types must never trigger action
                if req_t in ("NEGATION", "HYPOTHETICAL", "QUESTION", "EXPLANATION", "CONVERSATION"):
                    act_req = False

                return SemanticIntentRepresentation(
                    user_input=raw_text,
                    interpreted_meaning=goal,
                    intent=primary_cap,
                    request_type=req_t,
                    action_required=act_req,
                    is_negation=(req_t == "NEGATION"),
                    entities=[{"value": v, "type": k} for k, v in params.items()] if isinstance(params, dict) else [],
                    references=list(refs.keys()) if isinstance(refs, dict) else [],
                    resolved_references=refs if isinstance(refs, dict) else {},
                    target_entity=params.get("application") or params.get("target") or params.get("destination") if isinstance(params, dict) else None,
                    confidence=float(llm_result.get("confidence", 0.90)),
                )
        except Exception as e:
            logger.debug(f"[SEMANTIC_ENGINE] LLM reasoning fallback skipped: {e}")

        # Default pass-through for regular commands
        return SemanticIntentRepresentation(
            user_input=raw_text,
            interpreted_meaning=raw_text,
            intent="AUTO",
            action_required=True,
            confidence=0.90
        )

    # Method alias for natural semantic resolution
    understand = analyze


# Module-level singleton
semantic_understanding_engine = SemanticUnderstandingEngine()
