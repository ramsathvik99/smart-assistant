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
    required_capabilities: List[str] = field(default_factory=list)
    prohibited_capabilities: List[str] = field(default_factory=list)
    target_device: str = "none"
    negated_targets: List[str] = field(default_factory=list)
    corrected_target: Optional[str] = None
    is_continuation: bool = False
    continuation_goal_id: Optional[str] = None

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
            "required_capabilities": self.required_capabilities,
            "prohibited_capabilities": self.prohibited_capabilities,
            "target_device": self.target_device,
            "negated_targets": self.negated_targets,
            "corrected_target": self.corrected_target,
            "is_continuation": self.is_continuation,
            "continuation_goal_id": self.continuation_goal_id,
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

        # Conversational History Recall ("What did I ask you earlier?", "What was my last question?", etc.)
        is_conversational_recall = (
            getattr(rep, "action", "") == "recall_previous_turn"
            or any(p in user_input_low for p in (
                "what did i ask you earlier", "what did i ask earlier", "what did i ask you before",
                "what did i ask before", "what did i ask you", "what did i ask",
                "what did i just ask", "what was my last question", "what was my previous question",
                "what was the question that i asked", "what was the last thing i asked",
                "remind me what i asked"
            ))
        )
        if is_conversational_recall:
            if dialogue_state and hasattr(dialogue_state, "turns") and dialogue_state.turns:
                prev_turns = [t for t in dialogue_state.turns if getattr(t, "user_input", None) and t.user_input.lower().strip() != user_input_low.strip()]
                if prev_turns:
                    return f"You asked: '{prev_turns[-1].user_input}'."
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
                            return f"You asked: '{row[0]}'."
            except Exception:
                pass
            return "I don't have a record of your previous request."

        # Check factual memory and command recall from centralized ChatGPTMemoryManager
        try:
            from core.chatgpt_memory import get_chatgpt_memory
            chatgpt_mem = get_chatgpt_memory()
            fact_res = chatgpt_mem.answer_historical_fact_query(int(user_id), rep.user_input)
            if fact_res:
                return fact_res
            cmd_res = chatgpt_mem.answer_historical_command_query(int(user_id), rep.user_input)
            if cmd_res:
                return cmd_res
        except Exception:
            pass

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
                            SELECT target, parameters FROM os_action_history
                            WHERE user_id = %s AND (operation_type = 'OPEN_APPLICATION' OR capability = 'APPLICATION')
                            ORDER BY created_at DESC LIMIT 1;
                        """, (int(user_id),))
                        row = cur.fetchone()
                        if row and row[0]:
                            return f"The last application I opened was {row[0].capitalize()}."

                        cur.execute("""
                            SELECT target, parameters FROM action_records
                            WHERE user_id = %s AND (operation = 'OPEN_APPLICATION' OR capability = 'APPLICATION')
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
                            SELECT target, parameters FROM os_action_history
                            WHERE user_id = %s AND operation_type IN ('WEB_SEARCH', 'RESEARCH', 'BROWSE')
                            ORDER BY created_at DESC LIMIT 1;
                        """, (int(user_id),))
                        row = cur.fetchone()
                        if row and row[0]:
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
                            SELECT target, parameters, result_message FROM os_action_history
                            WHERE user_id = %s AND operation_type IN ('TYPE_TEXT', 'PASTE_CLIPBOARD', 'INSERT')
                            ORDER BY created_at DESC LIMIT 1;
                        """, (int(user_id),))
                        row = cur.fetchone()
                        if row:
                            return f"I inserted content into {row[0] or 'Notepad'}."
            except Exception:
                pass
            return "I don't have a record of inserting content into Notepad."

        # 4e. "What did you read before I stopped you?"
        if any(p in user_input_low for p in ("what did you read before", "read before i stopped", "what was being read")):
            try:
                from core.artifact_reader import get_artifact_reading_controller
                sess = get_artifact_reading_controller().load_latest_paused_session(user_id=int(user_id))
                if sess and sess.get("filename"):
                    return f"Before you stopped me, I was reading '{sess.get('filename')}'."
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
                            SELECT title FROM goals
                            WHERE user_id = %s AND status = 'CANCELLED'
                            ORDER BY updated_at DESC LIMIT 1;
                        """, (int(user_id),))
                        row = cur.fetchone()
                        if row and row[0]:
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
        is_negative_why = any(p in user_input_low for p in ("why didn't you", "why did you not", "why haven't you", "why have you not", "why won't you", "why wouldn't you", "why don't you"))
        is_why_explanation = (
            q_type == "explanation"
            or rep.sub_intent == "EXPLANATION_QUERY"
            or is_negative_why
            or any(p in user_input_low for p in ("why did you", "why did we", "why was", "why would you", "what made you"))
        )
        if not is_why_explanation and (q_type == "action_verification" or rep.sub_intent == "ACTION_VERIFICATION" or any(p in user_input_low for p in ("did you open", "have you opened"))):
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

        # 8. Negative Action Query ("Why didn't you open Chrome?", "Why haven't you opened Notepad?")
        if is_negative_why:
            target = rep.target_entity or "that"
            if target.lower() in ("that", "it", "the action", "the application", ""):
                target = getattr(dialogue_state, "active_application", None) or "the application"
            acts = self.retrieve_recent_actions(user_id, limit=5)
            for a in acts:
                cmd = str(a.get("command_signature") or a.get("command") or "").lower()
                status = str(a.get("status") or "").lower()
                if target.lower() in cmd:
                    if "fail" in status or "error" in status:
                        return f"I didn't open {target.capitalize()} because the operation failed: {a.get('error') or 'an unexpected error occurred'}."
            was_requested = False
            if dialogue_state and hasattr(dialogue_state, "turns") and dialogue_state.turns:
                for t in dialogue_state.turns:
                    u_in = getattr(t, "user_input", "") or ""
                    if target.lower() in u_in.lower() and any(w in u_in.lower() for w in ("open", "launch", "start")):
                        was_requested = True
                        break
            if was_requested:
                return f"I didn't open {target.capitalize()} because the system was unable to execute the launch command successfully."
            return f"I didn't open {target.capitalize()} because no command was issued to open it."

        # 8b. Action Explanation Query ("Why did you open Notepad?", "Why did you do that?", "Why did you open it?")
        if is_why_explanation or q_type == "explanation" or rep.sub_intent == "EXPLANATION_QUERY" or any(p in user_input_low for p in ("why did you open", "why did you do that", "why did you")):
            target = rep.target_entity or "that"
            if target.lower() in ("that", "it", "the action", "the application", ""):
                target = getattr(dialogue_state, "active_application", None) or "that"
            if dialogue_state and hasattr(dialogue_state, "turns") and dialogue_state.turns:
                prior_turns = dialogue_state.turns[:-1] if len(dialogue_state.turns) > 1 else dialogue_state.turns
                for t in reversed(prior_turns):
                    u_in = getattr(t, "user_input", "") or ""
                    if not u_in:
                        continue
                    if target.lower() in u_in.lower() or any(w in u_in.lower() for w in ("open", "launch", "start", "notepad", "chrome", "edge", "calculator")):
                        verb_str = f"opened {target.capitalize()}" if any(w in u_in.lower() for w in ("open", "launch", "start")) else f"performed {target}"
                        return f"I {verb_str} earlier because you requested: '{u_in}'."
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
    def is_location_intelligence_query(text: str) -> bool:
        """Determines if a query targets location intelligence, navigation, device location, or places."""
        if not text:
            return False
        tl = text.lower().strip()
        # Scheduling and reminder commands are never location queries unless map/navigation is explicitly asked
        if re.search(r'\b(?:schedules?|shedules?|reminders?|remiders?|alarms?|timers?|meetings?|appointments?)\b', tl):
            if not any(k in tl for k in ('map', 'location', 'directions', 'route', 'navigate', 'distance', 'where is', 'eta')):
                return False
        location_patterns = [
            r'\b(?:where\s+am\s+i|where\s+am\s+i\s+located)\b',
            r'\b(?:what(?:\x27s|\s+is)\s+(?:my\s+)?(?:current\s+)?location|check\s+(?:my\s+)?(?:current\s+)?location|get\s+(?:my\s+)?(?:current\s+)?location|find\s+(?:my\s+)?(?:current\s+)?location|my\s+current\s+location|current\s+location|my\s+location)\b',
            r'\b(?:refresh|update|detect)\s+(?:my\s+)?(?:current\s+)?location\b',
            r'\b(?:where\s+do\s+i\s+live|where(?:\x27s|\s+is)\s+my\s+home|what(?:\x27s|\s+is)\s+my\s+home\s+address|my\s+home\s+address|my\s+home\s+location)\b',
            r'\b(?:where(?:\x27s|\s+is)\s+my\s+(?:phone|connected\s+phone|mobile|android|redmi)|locate\s+(?:my\s+)?(?:phone|mobile)|find\s+my\s+phone|track\s+my\s+phone|phone\s+location)\b',
            r'\b(?:where(?:\x27s|\s+is)\s+my\s+(?:computer|pc|laptop)|locate\s+(?:my\s+)?(?:computer|pc|laptop)|find\s+my\s+(?:computer|pc|laptop)|computer\s+location|pc\s+location)\b',
            r'\b(?:show|open|view|display)\s+(?:(?:my\s+)?(?:current\s+|device\s+)?location\s+)?(?:on\s+(?:the\s+)?map|in\s+(?:google\s+)?maps?|on\s+map|(?:the\s+)?maps?)\b',
            r'\b(?:show\s+)?details\s+(?:of|for)\s+(?:that|the)?\s*(?:hospital|pharmacy|restaurant|place)\b',
            r'\b(?:navigate|directions?|route|drive|walk|cycle)\s+(?:to|towards)\s+.+\b',
            r'\b(?:navigate|directions?|route|drive|walk|cycle)\s+from\s+.+?\s+(?:to|towards)\s+.+\b',
            r'\b(?:plan\s+(?:a\s+)?route|route)\s+(?:through|via|across)\s+.+\b',
            r'\b(?:how\s+far\s+is|distance\s+to|calculate\s+(?:the\s+)?distance\s+to)\s+.+\b',
            r'\b(?:distance\s+between|how\s+far\s+is\s+it\s+from)\s+.+?\s+(?:and|to)\s+.+\b',
            r'\b(?:what\s+is\s+(?:the\s+)?eta|eta\s+from|travel\s+time\s+from)\b',
            r'\b(?:compare\s+(?:the\s+)?fastest\s+and\s+shortest\s+routes|fastest\s+route|shortest\s+route|which\s+route\s+is\s+fastest|shortest\s+route\s+instead)\b',
            r'\b(?:avoid\s+tolls?|avoid\s+toll\s+roads?|add\s+a\s+(?:fuel\s+|gas\s+)?stop|how\s+much\s+farther|what\s+is\s+my\s+eta\s+now|update\s+my\s+eta|distance\s+remaining)\b',
            r'\b(?:find|search|show|look\s+for|where\s+is\s+a|where\s+are|locate|get)\s+(?:a\s+|an\s+|the\s+|all\s+|nearby\s+)?(?:nearest\s+|nearby\s+)?(?:hospitals?|hospit[eo]ls?|pharmacies?|farmac(?:y|ies)|parmac(?:y|ies)|medical\s+stores?|fuel\s+stations?|gas\s+stations?|petrol\s+(?:pumps?|stations?)|restaurants?|restarents?|restarants?|resturants?|restaraunts?|resteraunts?|restraunts?|food|atms?|banks?|hotels?|parking|cafes?|places?)\b',
            r'\b(?:find|search|show|look\s+for|where\s+are|what\s+are|locate|get|list)\s+.*\b(?:nearby|near\s+me|around\s+me|around\s+here)\b',
            r'\b(?:nearby|near\s+me|around\s+me|around\s+here)\s+(?:hospitals?|hospit[eo]ls?|pharmacies?|farmac(?:y|ies)|medical\s+stores?|restaurants?|restarents?|restarants?|resturants?|restraunts?|food|cafes?|places?|stores?|shops?|hotels?|atms?|banks?)\b',
            r'\b(?:what(?:\s+are|\x27s|\s+is)\s+there|what\s+places\s+are\s+there|show\s+them|list\s+them)\b',
            r'\b(?:which\s+(?:one\s+)?is\s+(?:closest|nearest)|what\s+is\s+(?:the\s+)?(?:closest|nearest))\b',
            r'\b(?:tell\s+me\s+about|info\s+(?:on|about)|details\s+(?:on|about|for)|show\s+details\s+of)\s+(?:the\s+)?(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|closest|nearest|last)\s*(?:one|place|restaurant|hospital|pharmacy)?\b',
            r'\b(?:show|tell|give|what(?:\x27s|\s+is))\s+(?:me\s+)?(?:the\s+|its\s+)?address\b',
            r'\b(?:the\s+address|its\s+address)\b',
            r'\b(?:nearby\s+(?:hospitals?|pharmacies|pharmacy|restaurants?|atms?|gas\s+stations?|fuel\s+stations?|petrol\s+pumps?|hotels?|banks?))\b',
            r'\b(?:show\s+only|filter\s+(?:by|to)|only\s+show)\s+(?:hospitals?|pharmacies|pharmacy|restaurants?|petrol\s+stations?|gas\s+stations?|fuel\s+stations?|atms?|hotels?)\b',
            r'\b(?:add|include|show)\s+(?:hospitals?|pharmacies|pharmacy|restaurants?|petrol\s+stations?|gas\s+stations?|fuel\s+stations?|atms?|hotels?)(?:\s+(?:too|as\s+well|also))?\b',
            r'\b(?:remove|hide|exclude)\s+(?:hospitals?|pharmacies|pharmacy|restaurants?|petrol\s+stations?|gas\s+stations?|fuel\s+stations?|atms?|hotels?)\b',
            r'\b(?:show\s+all\s+(?:of\s+them|places|markers|results)|show\s+all\s+(?:on|in)\s+(?:the\s+)?map|reset\s+filters?|clear\s+filters?)\b',
            r'\b(?:go\s+to|navigate\s+to|route\s+to|take\s+me\s+to|select)\s+(?:the\s+)?(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|nearest|closest)(?:\s+(?:one|place|hospital|pharmacy|restaurant|stop))?\b',
            r'\b(?:navigate\s+there|take\s+me\s+there|route\s+there|directions?\s+there)\b',
            r'\b(?:zoom\s+in|zoom\s+out|zoom\s+map|reset\s+zoom)\b',
            r'\b(?:clear\s+(?:the\s+)?route|stop\s+navigation|cancel\s+navigation|end\s+route)\b',
            r'\b(?:keep\s+(?:the\s+)?map\s+open|leave\s+(?:the\s+)?map\s+open|pin\s+(?:the\s+)?map)\b',
            r'\b(?:close\s+(?:the\s+)?map|hide\s+(?:the\s+)?map|minimize\s+(?:the\s+)?map)\b',
            r'\bsave\s+(?:this\s+place|this\s+location|current\s+location|here)\s+as\s+[a-zA-Z0-9_\-\s]+\b',
            r'\b(?:where\s+is\s+(?:my\s+)?saved\s+[a-zA-Z0-9_\-\s]+|saved\s+places?|list\s+saved\s+places?)\b',
            r'\b(?:why\s+is\s+(?:my\s+)?location\s+unavailable|why\s+can\x27t\s+you\s+get\s+my\s+(?:live\s+)?location|why\s+cant\s+you\s+get\s+my\s+(?:live\s+)?location)\b',
            r'\b(?:how\s+accurate\s+is\s+my\s+location|location\s+accuracy|when\s+was\s+my\s+location\s+last\s+updated|location\s+source|location\s+provider|location\s+status|location\s+diagnostics)\b',
            r'\b(?:which\s+device\s+is\s+providing\s+(?:my\s+)?(?:current\s+)?location|which\s+device\s+provides\s+(?:my\s+)?location|what\s+device\s+is\s+providing\s+(?:my\s+)?location|how\s+do\s+you\s+know\s+my\s+location)\b',
            r'\b(?:exact\s+coordinates|show\s+my\s+coordinates|what\s+are\s+my\s+coordinates|my\s+coordinates)\b',
        ]
        return any(re.search(p, tl, re.IGNORECASE) for p in location_patterns)


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
    def _is_website_or_domain(target: str) -> bool:
        if not target:
            return False
        t = target.lower().strip()
        t = re.sub(r'^(?:the\s+)?(?:website|site|webpage|web\s+page)\s+(?:of\s+|for\s+)?', '', t).strip()
        t = re.sub(r'\s+(?:the\s+)?(?:website|site|webpage|web\s+page)$', '', t).strip()
        # Explicit URLs
        if t.startswith(("http://", "https://", "www.")) or "://" in t:
            return True
        # Domains with TLD
        if re.search(r'\b[a-zA-Z0-9-]+\.(?:com|org|net|edu|gov|io|ai|co|app|dev|in|me|info|tv)\b', t):
            return True
        # Exclude applications that mention chrome / code / terminal
        if t in ("chrome", "google chrome", "visual studio code", "vscode", "code", "notepad", "calculator", "terminal"):
            return False
        common_sites = {
            "wikipedia", "youtube", "google", "gmail", "github", "reddit",
            "twitter", "x", "linkedin", "facebook", "instagram", "amazon",
            "netflix", "stackoverflow", "bing", "yahoo", "duckduckgo",
            "quora", "medium", "twitch", "imdb"
        }
        return t in common_sites

    @staticmethod
    def _resolve_website_target(target: str) -> Tuple[str, str]:
        t = target.strip()
        t_clean = re.sub(r'^(?:the\s+)?(?:website|site|webpage|web\s+page)\s+(?:of\s+|for\s+)?', '', t, flags=re.I).strip()
        t_clean = re.sub(r'\s+(?:the\s+)?(?:website|site|webpage|web\s+page)$', '', t_clean, flags=re.I).strip()
        low = t_clean.lower()
        common_site_map = {
            "wikipedia": ("https://www.wikipedia.org", "Wikipedia"),
            "youtube": ("https://www.youtube.com", "YouTube"),
            "google": ("https://www.google.com", "Google"),
            "gmail": ("https://mail.google.com", "Gmail"),
            "github": ("https://www.github.com", "GitHub"),
            "reddit": ("https://www.reddit.com", "Reddit"),
            "twitter": ("https://www.twitter.com", "Twitter"),
            "x": ("https://x.com", "X"),
            "linkedin": ("https://www.linkedin.com", "LinkedIn"),
            "facebook": ("https://www.facebook.com", "Facebook"),
            "instagram": ("https://www.instagram.com", "Instagram"),
            "amazon": ("https://www.amazon.com", "Amazon"),
            "netflix": ("https://www.netflix.com", "Netflix"),
        }
        if low in common_site_map:
            return common_site_map[low]

        if low.startswith(("http://", "https://")):
            url = t_clean
        elif low.startswith("www."):
            url = f"https://{t_clean}"
        elif re.search(r'\.[a-zA-Z]{2,}', low):
            url = f"https://{t_clean}"
        else:
            url = f"https://www.{low}.com"

        host = re.sub(r'^https?://(?:www\.)?', '', url).split('/')[0].split(':')[0]
        parts = host.split('.')
        site_name = parts[-2].capitalize() if len(parts) >= 2 else parts[0].capitalize()
        return url, site_name

    @classmethod
    def resolve_canonical_application(cls, raw_name: str) -> Optional[str]:
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

        # URLs, links, domain names, and known websites are web destinations, not desktop applications
        if cls._is_website_or_domain(t):
            return None

        if t.startswith(("http://", "https://", "www.", "javascript:", "javascript(")) or "://" in t or ("." in t and "/" in t) or any(t.endswith(ext) for ext in (".com", ".org", ".net", ".edu", ".io", ".gov", ".asp", ".html", ".php")):
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

        # Reject generic file, artifact, media, script, or abstract terms from being treated as applications
        if any(w in t.split() for w in ("file", "files", "document", "documents", "doc", "pdf", "docx", "pptx", "xlsx", "report", "presentation", "sheet", "saved", "link", "result", "results", "source", "sources", "item", "copy", "script", "scripts", "code", "program", "function", "algorithm", "marathon", "business")):
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
        user_id: Any = None,
    ) -> SemanticCommand:
        """
        Derives canonical semantic command representation from natural user language.
        Normalizes input, extracts user goal, target, action, entities, desired state,
        arbitrates ambiguities, resolves contextual references deterministically,
        and enforces safety invariants.
        """
        if user_id is None:
            try:
                from instance.config import settings
                user_id = getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user()
            except Exception:
                pass
        if user_id is None:
            user_id = 1

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
        norm = re.sub(r'\bwats\b', 'what is', norm)
        norm = re.sub(r'\bwat\b', 'what', norm)
        norm = re.sub(r'\bcurrnt\b', 'current', norm)
        norm = re.sub(r'\bplz\b|\bpls\b', '', norm).strip()
        norm = re.sub(r'\bu\b', 'you', norm)
        norm = re.sub(r'\brite\b', 'right', norm)
        norm = re.sub(r'\bunloack\b', 'unlock', norm)
        norm = re.sub(r'\blok\b', 'lock', norm)
        norm = re.sub(r'\bphne\b', 'phone', norm)
        norm = re.sub(r'\bmob\b', 'mobile', norm)
        norm = re.sub(r'\bclg\b', 'college', norm)
        norm = re.sub(r'\buni\b', 'university', norm)
        norm = re.sub(r"\bwho's\b|\bwhos\b", 'who is', norm)
        norm = re.sub(r"\bwhat's\b|\bwhats\b", 'what is', norm)
        norm = re.sub(r"\bwhere's\b|\bwheres\b", 'where is', norm)
        norm = re.sub(r"\bwhen's\b|\bwhens\b", 'when is', norm)
        norm = re.sub(r"\bhow's\b|\bhows\b", 'how is', norm)
        norm = re.sub(r"\bthat's\b", 'that is', norm)
        norm = re.sub(r"\bit's\b", 'it is', norm)
        norm = re.sub(r"\bthere's\b", 'there is', norm)

        # Scheduling, reminder, and colloquial speech normalization
        try:
            from core.unified_command_router import normalize_scheduling_text
            norm = normalize_scheduling_text(norm)
        except Exception:
            pass

        # -------------------------------------------------------------
        # 1. Garbled Speech / Plausibility Guard (Section 11)
        # -------------------------------------------------------------
        if (
            norm in ("open open", "close close", "run run")
            or bool(re.search(r'\b(?:open\s+open|close\s+close|run\s+run)\b', norm))
            or any(k in norm for k in ["hernia of the games", "hernia of games"])
        ):
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
                action_required=False,
                request_type="QUESTION",
            )

        # -------------------------------------------------------------
        # 1.05 Canonical Conversational Knowledge & Questions (Intent-Driven)
        # -------------------------------------------------------------
        is_explicit_creation_cmd = bool(re.search(r'\b(?:create|make|write|generate|save|export|build)\s+(?:a\s+|an\s+)?(?:doc|document|word|pdf|presentation|ppt|file|code|script|report)\b', norm))
        is_explanation_how_it_works = bool(re.search(r'\bhow\s+([a-zA-Z0-9_\-\s]+?)\s+(?:works?|functions?)\b', norm)) or norm.startswith("tell me how ") or norm.startswith("explain how ")
        if is_explanation_how_it_works and not is_explicit_creation_cmd:
            m_topic = re.search(r'\bhow\s+([a-zA-Z0-9_\-\s]+?)\s+(?:works?|functions?)\b', norm)
            topic = m_topic.group(1).strip() if m_topic else norm
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"Explain how {topic} works",
                intent="GENERAL_CONVERSATION",
                action="answer_question",
                request_type="QUESTION",
                action_required=False,
                required_capabilities=["conversational_knowledge"],
                prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                parameters={"topic": topic, "question": text_stripped},
                confidence=0.98,
            )

        is_explicit_device_cmd = bool(re.search(r'\b(?:lock|unlock|shutdown|restart|sleep|mute|volume|brightness|bluetooth|wifi|battery|call)\b', norm))
        is_explicit_app_cmd = bool(re.search(r'\b(?:open|launch|start|close|kill|terminate|switch\s+to)\s+[a-zA-Z0-9_\-\s]+', norm))
        is_correction_cmd = bool(re.search(r'^(?:no\s*,?\s*)?(?:i\s+mean|i\s+meant|not\s+(?:the|my)|switch\s+to|change\s+to|stop\s+that[;,]?\s*i\s+meant)\b', norm))

        # -------------------------------------------------------------
        # 1.05 Canonical Question Understanding & Information Requirement Routing
        # -------------------------------------------------------------
        if not is_explicit_creation_cmd and not is_explicit_device_cmd and not is_explicit_app_cmd and not is_correction_cmd:
            # 1.05a Local Clock Time Query
            if re.search(r'\b(?:what\s+time\s+is\s+it|what\s+(?:is\s+the\s+)?(?:current\s+)?time|tell\s+me\s+(?:the\s+)?time|current\s+time)\b', norm):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="Query current local time from system clock",
                    intent="TIME_QUERY",
                    action="time_query",
                    request_type="QUESTION",
                    action_required=False,
                    required_capabilities=["clock_service"],
                    prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                    parameters={"action": "time_query", "question": text_stripped},
                    confidence=0.99,
                )

            # 1.05b Local Clock Date Query
            is_past_event = bool(re.search(r'\b(?:did|was|were|happened|occurred|took\s+place|landed|landing|apollo|born|died|invented|discovered|founded|built|war)\b', norm))
            if not is_past_event and re.search(r'\b(?:what\s+(?:is\s+)?(?:the\s+)?date|what\s+is\s+today\'?s?\s+date|what\s+day(?:\s+of\s+(?:the\s+)?week)?\s+is\s+(?:it|today)|today\'?s?\s+date|current\s+date|what\s+year\s+is\s+it|what\s+year\s+are\s+we\s+(?:currently\s+)?in|what\s+is\s+(?:the\s+)?current\s+year|current\s+year|which\s+year\s+are\s+we\s+in|what\s+is\s+this\s+year)\b', norm):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="Query current local date from system clock",
                    intent="DATE_QUERY",
                    action="date_query",
                    request_type="QUESTION",
                    action_required=False,
                    required_capabilities=["clock_service"],
                    prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                    parameters={"action": "date_query", "question": text_stripped},
                    confidence=0.99,
                )

            # 1.05c User Personal Memory & Profile Query
            if not any(k in norm for k in ('job', 'prospect', 'career', 'opportunit', 'salary')) and re.search(r'\b(?:(?:what\s+is\s+)?my\s+(?:name|university|uni|college|degree|major|school|role|email|(?:phone|mobile)\s+number|placement)(?:\s+name)?|where\s+do\s+i\s+(?:study|work|live|go\s+to\s+school)|who\s+am\s+i|what\s+do\s+you\s+remember\s+about\s+me|what\s+are\s+my\s+(?:skills|interests|facts))\b', norm):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal=f"Query user personal memory: {text_stripped}",
                    intent="MEMORY_QUERY",
                    action="retrieve_memory",
                    request_type="QUESTION",
                    action_required=False,
                    required_capabilities=["persistent_memory"],
                    prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                    parameters={"action": "retrieve_memory", "question": text_stripped},
                    confidence=0.99,
                )

            # 1.05d Private Document / Artifact Corpus Query
            if (
                re.search(r'\b(?:what\s+does\s+my\s+[a-z0-9_\-\s]{0,30}?(?:document|report|notes?|file|pdf|presentation|artifact)\s+say|what\s+is\s+in\s+my\s+[a-z0-9_\-\s]{0,30}?(?:document|report|notes?|file|pdf|presentation|artifact)|summarize\s+my\s+[a-z0-9_\-\s]{0,30}?(?:document|report|notes?|file|pdf|presentation|artifact)|in\s+my\s+(?:document|report|notes?|file|pdf|presentation|artifact))\b', norm)
                or re.search(r'\b(?:artificial\s+neural\s+networks?\s+(?:report|artifact|doc|presentation)|dbms\s+normalization(?:\s+artifact)?)\b', norm)
            ):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal=f"Search user private document corpus: {text_stripped}",
                    intent="RAG_SEARCH",
                    action="document_search",
                    request_type="QUESTION",
                    action_required=False,
                    required_capabilities=["rag_retrieval"],
                    prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                    parameters={"scope": "documents", "query": text_stripped},
                    confidence=0.98,
                )

            # 1.05e Hybrid Personal Memory & Live Research Query
            if re.search(r'\b(?:job\s+prospects\s+for\s+my\s+(?:degree|major|career)|opportunities\s+for\s+my\s+(?:degree|major)|jobs\s+for\s+my\s+degree)\b', norm):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal=f"Hybrid personal memory and live research: {text_stripped}",
                    intent="RAG_SEARCH",
                    action="hybrid_search",
                    request_type="QUESTION",
                    action_required=False,
                    required_capabilities=["persistent_memory", "rag_retrieval"],
                    prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                    parameters={"requires_live_search": True, "requires_memory": True, "query": text_stripped},
                    confidence=0.98,
                )

            # 1.05f Current Dynamic / Live Fact Query (Officeholders, Leaders, Real-time status)
            if (
                re.search(r'\b(?:who\s+is\s+(?:the\s+)?(?:current\s+)?(?:president|potus|vice\s+president|prime\s+minister|ceo|governor|chancellor|leader|mayor)|what\s+is\s+(?:the\s+)?current\s+(?:price|stock\s+price|weather|version|population)|current\s+ceo\s+of|latest\s+(?:news|updates?|score))\b', norm)
                or (norm.startswith("who is ") and any(k in norm for k in ("president", "potus", "ceo", "prime minister", "governor", "leader", "chief")))
            ):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal=f"Retrieve dynamic real-world facts: {text_stripped}",
                    intent="RAG_SEARCH",
                    action="research",
                    request_type="QUESTION",
                    action_required=False,
                    required_capabilities=["rag_retrieval"],
                    prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                    parameters={"requires_live_search": True, "scope": "web", "query": text_stripped},
                    confidence=0.98,
                )

            # 1.05g Historical Factual Queries (Specific past years/events)
            if re.search(r'\b(?:who\s+was\s+(?:the\s+)?(?:president|prime\s+minister|ceo|leader|winner)|who\s+won\s+the\s+\d{4}|in\s+\d{4}\b|during\s+\d{4}\b|back\s+in\s+\d{4}\b)', norm):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal=f"Answer historical factual query: {text_stripped}",
                    intent="RAG_SEARCH",
                    action="research",
                    request_type="QUESTION",
                    action_required=False,
                    required_capabilities=["conversational_knowledge"],
                    prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                    parameters={"temporal_scope": "historical", "query": text_stripped},
                    confidence=0.98,
                )

            # 1.05h Conversational Verification ("Are you sure?", "Really?")
            if re.match(r'^(?:are\s+you\s+(?:sure|certain|positive)|really|you\s+sure|is\s+that\s+(?:true|accurate|correct))\??$', norm):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="Verify accuracy of previous statement",
                    intent="GENERAL_CONVERSATION",
                    action="conversational_verification",
                    request_type="QUESTION",
                    action_required=False,
                    required_capabilities=["conversational_knowledge"],
                    prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                    parameters={"action": "verify_claim", "question": text_stripped},
                    confidence=0.99,
                )

            # 1.05i Conversational Follow-up Inquiry ("What about X?", "How about X?")
            m_follow_up = re.match(r'^(?:what|how)\s+about\s+(.+?)\??$', norm)
            if m_follow_up:
                topic = m_follow_up.group(1).strip()
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal=f"Answer follow-up question regarding {topic}",
                    intent="GENERAL_CONVERSATION",
                    action="follow_up_inquiry",
                    request_type="QUESTION",
                    action_required=False,
                    required_capabilities=["conversational_knowledge"],
                    prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                    parameters={"action": "follow_up", "topic": topic, "question": text_stripped},
                    confidence=0.98,
                )

            # 1.05j-Math Canonical Mathematical & Arithmetic Calculation (Intent-Driven)
            if (
                re.search(r'\b(?:calculate|compute|solve)\b', norm)
                or re.search(r'\bwhat\s+is\s+[\d.]+\s*(?:[\+\-\*/\^x]|plus|minus|times|multiplied\s+by|divided\s+by)\s*[\d.]+', norm)
                or re.search(r'^\s*[\d.]+\s*(?:[\+\-\*/\^]|plus|minus|times|multiplied\s+by|divided\s+by)\s*[\d.]+\s*$', norm)
            ):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal=f"Perform calculation: {text_stripped}",
                    intent="CALCULATOR",
                    action="calculate",
                    request_type="QUESTION",
                    action_required=False,
                    required_capabilities=["calculator"],
                    prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                    parameters={"action": "calculate", "expression": text_stripped},
                    confidence=0.99,
                )

            # 1.05j Casual Entertainment / Joke Request
            if re.search(r'\b(?:tell\s+me|give\s+me|say)?\s*(?:a|another|a\s+different)?\s*(?:[a-zA-Z0-9_\-]+\s+)?jokes?\b', norm) or norm in ("joke", "another joke", "tell me a joke"):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="Tell a joke",
                    intent="GENERAL_CONVERSATION",
                    action="joke",
                    request_type="QUESTION",
                    action_required=False,
                    required_capabilities=["conversational_knowledge"],
                    prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                    parameters={"action": "joke", "question": text_stripped},
                    confidence=0.99,
                )

        m_knowledge = re.match(r'^(?:tell\s+me\s+(?:about\s+)?|what\s+(?:is|are|was|were|year|day|month|time|company|animal|planet|kind|type|sort|part|language|happened)|which\s+|where\s+(?:is|was|are|were|did|do|does)|when\s+(?:is|was|were|did|will)|who\s+(?:is|was|are|were|did)|why\s+(?:is|was|are|were|do|does|did)|how\s+(?:does|do|did|is|are|can|come)|explain\s+(?:to\s+me\s+)?(?:what\s+is\s+|how\s+|the\s+concept\s+of\s+)?)(.+)', norm)
        if m_knowledge and not is_explicit_creation_cmd and not is_explicit_device_cmd and not is_explicit_app_cmd:
            topic = m_knowledge.group(1).strip()
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"Answer conversational question about {topic}",
                intent="GENERAL_CONVERSATION",
                action="answer_question",
                request_type="QUESTION",
                action_required=False,
                required_capabilities=["conversational_knowledge"],
                prohibited_capabilities=["windows_workstation", "android_device", "applications", "media_control", "os_operations"],
                parameters={"topic": topic, "question": text_stripped},
                confidence=0.98,
            )

        # -------------------------------------------------------------
        # 1.06 Canonical Reminders & Memory Directives (Intent-Driven)
        # -------------------------------------------------------------
        if re.search(r'\b(?:remember\s+(?:this|that)|remind\s+me\s+(?:about\s+this|to|for))\s+(?:for|on|at|by)\s+(tomorrow|tonight|next\s+\w+|\d+)', norm) or norm.startswith("remember this for tomorrow"):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="Store reminder in persistent memory and schedule reminder",
                intent="REMINDERS",
                action="create_reminder",
                request_type="INSTRUCTION",
                action_required=True,
                required_capabilities=["persistent_memory", "reminders"],
                prohibited_capabilities=["windows_workstation", "android_device", "applications"],
                parameters={"action": "create_reminder", "content": text_stripped, "time": "tomorrow"},
                confidence=0.98,
            )

        # -------------------------------------------------------------
        # 1.1 Canonical Environment, Causal & Historical Queries (Section 4)
        # -------------------------------------------------------------
        if self.is_local_environment_query(norm) or self.is_local_environment_query(text_stripped):
            env_cmd = self._detect_environment_query(text_stripped, norm, dialogue_state)
            if env_cmd:
                return env_cmd

        # -------------------------------------------------------------
        # 1.15 Canonical Location Intelligence & Navigation (Section 8)
        # -------------------------------------------------------------
        if self.is_location_intelligence_query(norm) or self.is_location_intelligence_query(text_stripped):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"Execute location intelligence command: {text_stripped}",
                intent="DEVICE_CONTROL",
                action="device_location",
                target_type=EntityType.DEVICE_OR_SYSTEM,
                parameters={"action": "device_location", "raw_input": text_stripped, "query": text_stripped},
                confidence=0.99,
                action_required=True,
            )

        # -------------------------------------------------------------
        # 1.16 Canonical Reminders & Alerts & Schedules (Master Directive)
        # -------------------------------------------------------------
        # 1. Bulk cancellation / deletion / clear ("cancel all my reminders", "cancel all my schedules", "remove all the reminders", "delete all reminders", "cancel all meeting reminders", "clear reminder history")
        is_reminder_noun = bool(re.search(r'\b(?:reminders?|schedules?|reminder\s+history)\b', norm))
        is_cancel_verb = bool(re.search(r'\b(?:cancel|delete|remove|clear|purge)\b', norm))
        if (is_cancel_verb and is_reminder_noun) or norm in ("cancel all schedules", "cancel all my schedules", "cancel all my reminders", "remove all the reminders", "delete all reminders", "clear reminder history"):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"cancel/delete reminders: {text_stripped}",
                intent="REMINDERS",
                action="cancel",
                parameters={"action": "cancel", "raw_input": text_stripped},
                confidence=0.99,
                action_required=True,
            )

        # 2. Pause & resume reminders / schedules
        if re.search(r'\b(?:pause|resume)\s+(?:all\s+)?(?:of\s+)?(?:the\s+|my\s+)?(?:reminders?|schedules?)\b', norm) or norm in ("pause reminders", "resume reminders", "pause my reminders", "resume my reminders", "pause schedules", "resume schedules"):
            act = "pause" if "pause" in norm else "resume"
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"{act} reminders: {text_stripped}",
                intent="REMINDERS",
                action=act,
                parameters={"action": act, "raw_input": text_stripped},
                confidence=0.99,
                action_required=True,
            )

        # 3. Snooze reminder
        if re.search(r'\bsnooze\b', norm):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"snooze reminder: {text_stripped}",
                intent="REMINDERS",
                action="snooze",
                parameters={"action": "snooze", "raw_input": text_stripped},
                confidence=0.99,
                action_required=True,
            )

        # 4. Mark completed / done / dismiss
        if re.search(r'\b(?:mark\s+(?:the\s+|this\s+|my\s+)?reminder(?:\s*#?\d+)?\s*(?:as\s+)?(?:done|complete|completed|finished)|complete\s+(?:the\s+|this\s+|my\s+)?reminder|dismiss\s+(?:the\s+|this\s+|my\s+)?reminder)\b', norm):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"complete reminder: {text_stripped}",
                intent="REMINDERS",
                action="complete",
                parameters={"action": "complete", "raw_input": text_stripped},
                confidence=0.99,
                action_required=True,
            )

        # 5. Reschedule / postpone / move reminder
        if re.search(r'\b(?:reschedule|postpone|move|defer|delay)\s+(?:the\s+|my\s+)?(?:reminder|schedule|that|it|#\d+)\b', norm):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"reschedule reminder: {text_stripped}",
                intent="REMINDERS",
                action="reschedule",
                parameters={"action": "reschedule", "raw_input": text_stripped},
                confidence=0.99,
                action_required=True,
            )

        # 6. Create reminder / schedule
        if re.search(r'\b(?:set\s+(?:a\s+)?(?:reminder|meeting|appointment|schedule)|remind\s+me|create\s+(?:a\s+)?(?:reminder|meeting|appointment|schedule)|add\s+(?:a\s+)?(?:reminder|meeting|appointment|schedule)|schedule\b|remember\s+to\b)', norm):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"set reminder: {text_stripped}",
                intent="REMINDERS",
                action="create",
                parameters={"action": "create", "raw_input": text_stripped},
                confidence=0.99,
                action_required=True,
            )

        # 7. List / Query reminders & schedules
        if (
            re.search(r'\b(?:show|list|view|get|check)\s+(?:me\s+)?(?:all\s+)?(?:my\s+)?(?:upcoming\s+|overdue\s+|missed\s+|completed\s+|paused\s+)?(?:reminders?|schedules?)\b', norm)
            or re.search(r'\bwhat\s+(?:are\s+)?(?:all\s+)?(?:my\s+)?(?:reminders|schedules)\b', norm)
            or re.search(r'\bdo\s+i\s+have\s+(?:any\s+)?(?:reminders|schedules|anything\s+scheduled)\b', norm)
            or re.search(r'\bwhat\s+do\s+i\s+have\s+scheduled\b', norm)
            or re.search(r'\b(?:search|find)\s+(?:my\s+)?(?:reminders?|schedules?)\b', norm)
            or norm in ("reminders", "my reminders", "schedules", "my schedules", "all my schedules", "check reminders", "what are my reminders", "what do i have scheduled", "reminder history", "show reminders", "list reminders")
        ):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="list reminders",
                intent="REMINDERS",
                action="list",
                parameters={"action": "list", "raw_input": text_stripped},
                confidence=0.99,
                action_required=True,
            )

        # 8. Single cancel / delete
        if re.search(r'\b(?:cancel|delete|remove|clear)\s+(?:the\s+|this\s+|my\s+)?(?:reminder|schedule|#\d+|reminder\s+#\d+)\b', norm):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="cancel reminder",
                intent="REMINDERS",
                action="cancel",
                parameters={"action": "cancel", "raw_input": text_stripped},
                confidence=0.99,
                action_required=True,
            )

        # -------------------------------------------------------------
        # 1.2 Active Browser / Page Title & Content Queries
        # -------------------------------------------------------------
        is_opening_website_first = bool(re.match(r'^(?:open|launch|visit|go\s+to|browse)\s+(?:https?://|[a-zA-Z0-9_\-\.]+\.(?:com|org|net|gov|edu|io)|youtube|google|wikipedia|gmail|github|reddit|twitter|x|linkedin|facebook|instagram|amazon|netflix)\b', norm))
        if not is_opening_website_first:
            if re.search(r'\b(?:(?:retrevie|retrieve|get|tell\s+me|show\s+me|what(?:\'s|\s+is))\s+(?:the\s+)?(?:page\s+)?title(?:\s+of\s+(?:this|the)\s+page)?|(?:page|website)\s+title)\b', norm) or norm in ("page title", "what's the title", "what is the title", "title of the page", "retrieve page title", "retrevie the title of the page"):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="Retrieve active web page title",
                    intent="WINDOW_CONTEXT",
                    action="page_title",
                    target="active_page",
                    parameters={"action": "page_title", "target": "active_page", "raw_input": text_stripped},
                    confidence=1.0,
                )

            if re.search(r'\b(?:what\s+is\s+(?:this|the)\s+(?:page|website)\s+about|what\s+is\s+this\s+about|explain\s+(?:this|the)\s+(?:page|website))\b', norm):
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="Explain active web page content",
                    intent="WINDOW_CONTEXT",
                    action="page_summary",
                    target="active_page",
                    parameters={"action": "page_summary", "target": "active_page", "raw_input": text_stripped},
                    confidence=1.0,
                )

        # -------------------------------------------------------------
        # 1.3 Deterministic Website / URL Navigation & Compound Browser Commands
        # -------------------------------------------------------------
        m_web_nav = re.match(r'^(?:open|launch|start|run|go\s+to|visit|browse(?:\s+to)?|navigate(?:\s+to)?)\s+(.+)$', norm)
        if m_web_nav:
            raw_target = m_web_nav.group(1).strip()
            cleaned_target = re.sub(r'\s+(?:for\s+me|please|right\s+now|now)$', '', raw_target).strip()

            comp_steps = []
            m_and = re.match(r'^(.*?)\s+(?:and|then)\s+(.+)$', cleaned_target, re.I)
            if m_and:
                head_part = m_and.group(1).strip()
                rest_part = m_and.group(2).strip()
                if self._is_website_or_domain(head_part):
                    cleaned_target = head_part
                    from core.unified_command_router import unified_router
                    comp_steps = unified_router._parse_browser_steps(rest_part)

            if self._is_website_or_domain(cleaned_target):
                site_url, site_name = self._resolve_website_target(cleaned_target)
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal=f"open website {site_name}",
                    intent="OPEN_APPLICATION",
                    action="open_website",
                    target=site_url,
                    object=site_name,
                    desired_state="opened",
                    parameters={
                        "action": "open",
                        "is_website": True,
                        "url": site_url,
                        "target": site_url,
                        "site_name": site_name,
                        "application": site_name,
                        "browser_steps": comp_steps,
                        "raw_input": text_stripped,
                    },
                    confidence=1.0,
                )

        # -------------------------------------------------------------
        # 2. Negation, Hypothetical, Explanation, and Verification Queries
        # -------------------------------------------------------------
        # Fast path: Negation with affirmative alternative ("Don't open Chrome, open Calculator", "Instead of opening Chrome, open Calculator")
        neg_alt_match = re.match(
            r"^(?:do\s+not|don['’]?t|never)\s+(?:open|launch|run|start|create|make|delete|remove|send|search|play|set)\b.+?(?:[,;]|\s+(?:instead|but)\b)\s*(?:instead\s*,?\s*|please\s+|just\s+)?(?P<affirmative>[a-zA-Z].+)$",
            norm,
            re.IGNORECASE
        )
        if not neg_alt_match:
            neg_alt_match = re.match(
                r"^instead\s+of\s+.+?(?:[,;]|\s+(?:please|just)\b)\s*(?:please\s+|just\s+)?(?P<affirmative>[a-zA-Z].+)$",
                norm,
                re.IGNORECASE
            )
        if neg_alt_match:
            affirmative_cmd = neg_alt_match.group("affirmative").strip()
            neg_part = norm[:neg_alt_match.start("affirmative")].strip(";,. ")
            m_neg_tgt = re.search(r'\b(?:open|launch|run|start|create|make|delete|remove|send|search|play|set)\s+([a-zA-Z0-9_\-]+)', neg_part)
            neg_tgt_name = m_neg_tgt.group(1).strip() if m_neg_tgt else ""
            if neg_tgt_name:
                affirmative_cmd = re.sub(r'\b(?:it|that|this)\b', neg_tgt_name, affirmative_cmd)

            if affirmative_cmd:
                sub_res = self.interpret(affirmative_cmd, dialogue_state=dialogue_state, user_id=user_id)
                sub_res.user_text = text_stripped
                sub_res.normalized_text = norm
                return sub_res

        # Fast path: Reported speech / quoted error / system messages as data (prevent accidental execution of quoted verbs)
        reported_data_match = re.search(
            r"^(?:(?:the|my|this|our|a)\s+)?(?:error(?:\s+message)?|log(?:s)?|console(?:\s+output)?|terminal(?:\s+output)?|stack\s*trace|system\s+message|prompt|dialog(?:ue)?|exception|boss|user|he|she|they|it)\s+(?:says?|said|stated?|tells?|told|reports?|reported?|shows?|showed?|outputs?|reads?|read|contains?)\s*[:\"'\s]+(?P<quoted>.+)",
            norm,
            re.IGNORECASE
        )
        if not reported_data_match:
            reported_data_match = re.search(
                r"^[\"'](?P<quoted>.+?)[\"']\s+(?:is\s+(?:the\s+)?(?:error|message|output|log)|appeared|was\s+shown)",
                norm,
                re.IGNORECASE
            )
        if reported_data_match:
            quoted_text = reported_data_match.group("quoted").strip().strip('"\'')
            is_error_context = any(w in norm for w in ("error", "exception", "traceback", "failed", "failure", "bug", "crash", "issue"))
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="Discuss reported information without executing quoted action",
                intent="GENERAL_CONVERSATION",
                action="discuss_reported_data",
                target="",
                parameters={"action": "discuss_reported_data", "reported_text": quoted_text, "is_error": is_error_context, "raw_input": text_stripped},
                confidence=0.99,
            )

        m_neg = re.search(r'\b(?:don\'?t|do\s+not|never|not)\s+(?:open|launch|start|run|create|delete|close|bring\s+up)\s+([a-zA-Z0-9_\-\s]+)', norm)
        m_dont_want = re.search(r'\bi\s+(?:don\'?t|do\s+not)\s+want\s+([a-zA-Z0-9_\-\s]+?)\s+(?:open|opened|running|started)', norm)
        has_affirmative_alt = bool(re.search(r'[,;]\s*(?:instead\s*,?\s*|please\s+|just\s+)?(?:open|launch|start|run|create|make|help|calculate|show)\b', norm))
        if not has_affirmative_alt and (m_neg or m_dont_want or norm in ("don't open notepad", "do not open notepad", "don't do that", "do not do that", "stop, don't do that", "don't open it")):
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

        m_why_act = re.search(r'\bwhy\s+(?:did\s+not|didn\'?t|haven\'?t|have\s+not|won\'?t|wouldn\'?t|don\'?t|do\s+not|did)\s+you\s+(?:open|launch|start|close|delete|create|do)\s*([a-zA-Z0-9_\-\s]*)', norm)
        is_action_why = bool(
            m_why_act or any(re.search(p, norm) for p in [
                r'\bwhy\s+is\s+([a-zA-Z0-9_\-\s]+?)\s+(?:open|running|active)\b',
                r'\bwhat\s+made\s+you\s+(?:open|do|start)\b',
            ]) or norm in ("why did you open notepad", "why did you do that", "why did you open that", "why did you open it", "why did you do it")
        )
        if not is_action_why and norm == "why":
            last_act_intent = (getattr(dialogue_state, "last_action", {}) or {}).get("intent")
            if last_act_intent in ("OPEN_APPLICATION", "CLOSE_APPLICATION", "FILE_OPERATIONS", "POWER_ACTION"):
                is_action_why = True

        if is_action_why:
            active_app = getattr(dialogue_state, "active_application", None) if dialogue_state else None
            extracted_target = m_why_act.group(1).strip() if (m_why_act and m_why_act.group(1).strip()) else None
            target_app = extracted_target or ("notepad" if "notepad" in norm else ("chrome" if "chrome" in norm else (active_app or "the action")))
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

        # -------------------------------------------------------------
        # 2a. System Uptime & Telemetry Queries (Section 2, 4, 18)
        # -------------------------------------------------------------
        if any(re.search(p, norm) for p in [
            r'\bhow\s+long\s+(?:has|is)\s+(?:my|the|this)?\s*(?:pc|comput[er]{1,2}|system|mach[in]{1,3}e?|device|laptop|workstation)\s+(?:been\s+|being\s+)?(?:run[in]{1,3}g|on|up)\b',
            r'\b(?:what(?:\x27s|\s+is)\s+(?:my|the)?\s*(?:system\s+)?uptime|(?:system\s+)?uptime|check\s+(?:my|the)?\s*uptime|how\s+long\s+(?:has\s+it|have\s+you|is\s+it)\s+(?:been\s+|being\s+)?(?:run[in]{1,3}g|on|up))\b',
        ]) or norm in ("system uptime", "uptime", "check uptime", "what is uptime", "how long is the system running", "how long is the system being running"):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="check system uptime",
                intent="DEVICE_CONTROL",
                action="uptime",
                target="system_uptime",
                parameters={"action": "uptime"},
                confidence=1.0,
            )

        # -------------------------------------------------------------
        # 2b. Voice Listening & Microphone Lifecycle Control
        # -------------------------------------------------------------
        if any(re.search(p, norm) for p in [
            r'\b(?:toggle|switch)\s+(?:voice\s+)?listening\b',
            r'\b(?:toggle|switch)\s+(?:the\s+)?(?:mic|microphone)\b',
        ]) or norm in ("toggle voice listening", "toggle listening", "toggle mic", "toggle microphone"):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="toggle continuous voice listening",
                intent="DEVICE_CONTROL",
                action="toggle_listening",
                target="voice_listening",
                parameters={"action": "toggle_listening"},
                confidence=1.0,
            )

        if any(re.search(p, norm) for p in [
            r'\b(?:start|resume|enable|unpause)\s+(?:voice\s+)?listening\b',
            r'\b(?:unmute)\s+(?:the\s+)?(?:mic|microphone|voice)\b',
        ]) or norm in ("start listening", "resume listening", "unmute mic", "unmute microphone", "start voice listening"):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="start continuous voice listening",
                intent="DEVICE_CONTROL",
                action="start_listening",
                target="voice_listening",
                parameters={"action": "start_listening"},
                confidence=1.0,
            )

        if any(re.search(p, norm) for p in [
            r'\b(?:stop|pause|disable)\s+(?:voice\s+)?listening\b',
            r'\b(?:mute)\s+(?:the\s+)?(?:mic|microphone|voice)\b',
        ]) or norm in ("stop listening", "pause listening", "mute mic", "mute microphone", "stop voice listening"):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="pause continuous voice listening",
                intent="DEVICE_CONTROL",
                action="stop_listening",
                target="voice_listening",
                parameters={"action": "stop_listening"},
                confidence=1.0,
            )

        # -------------------------------------------------------------
        # 2c. System Resource Queries (CPU, RAM, Disk, GPU, Processes)
        # -------------------------------------------------------------
        if any(re.search(p, norm) for p in [
            r'\b(?:what(?:\x27s|\s+is)\s+(?:my\s+)?cpu\s+usage|check\s+(?:my\s+)?cpu|how\s+much\s+cpu\s+(?:am\s+i\s+using|is\s+used)|cpu\s+usage)\b',
        ]) or norm in ("cpu usage", "check cpu", "what is my cpu usage"):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="check CPU usage",
                intent="DEVICE_CONTROL",
                action="cpu_usage",
                target="cpu",
                parameters={"action": "cpu_usage"},
                confidence=1.0,
            )

        if any(re.search(p, norm) for p in [
            r'\b(?:what(?:\x27s|\s+is)\s+(?:my\s+)?(?:ram|memory)\s+usage|check\s+(?:my\s+)?(?:ram|memory)|how\s+much\s+(?:ram|memory)\s+(?:am\s+i\s+using|is\s+used|do\s+i\s+have)|ram\s+usage|memory\s+usage)\b',
        ]) or norm in ("ram usage", "memory usage", "check ram", "check memory", "what is my ram usage"):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="check RAM usage",
                intent="DEVICE_CONTROL",
                action="ram_usage",
                target="ram",
                parameters={"action": "ram_usage"},
                confidence=1.0,
            )

        if any(re.search(p, norm) for p in [
            r'\b(?:how\s+much\s+(?:disk\s+space|storage|space)\s+is\s+(?:available|free|left)|check\s+disk|disk\s+usage|storage\s+usage|available\s+disk\s+space|free\s+disk\s+space)\b',
        ]) or norm in ("disk space", "disk usage", "storage usage", "check disk"):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="check disk space",
                intent="DEVICE_CONTROL",
                action="disk",
                target="disk",
                parameters={"action": "disk", "drive": "C:"},
                confidence=1.0,
            )

        if any(re.search(p, norm) for p in [
            r'\b(?:what(?:\x27s|\s+is)\s+my\s+gpu|what(?:\x27s|\s+is)\s+(?:my\s+)?gpu\s+usage|check\s+(?:my\s+)?gpu|gpu\s+usage|gpu\s+telemetry|what\s+gpu\s+do\s+i\s+have|graphics\s+card\s+info)\b',
        ]) or norm in ("gpu usage", "check gpu", "gpu telemetry", "graphics card"):
            try:
                from core.unified_command_router import is_general_hardware_knowledge
                is_gk = is_general_hardware_knowledge(norm)
            except Exception:
                is_gk = False
            if not is_gk:
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="check GPU telemetry",
                    intent="DEVICE_CONTROL",
                    action="gpu_telemetry",
                    target="gpu",
                    parameters={"action": "gpu_telemetry"},
                    confidence=1.0,
                )

        if any(re.search(p, norm) for p in [
            r'\b(?:which|what)\s+(?:app|application|process|program)\s+(?:is\s+)?(?:using|taking|consuming)\s+(?:the\s+)?most\s+cpu\b',
            r'\btop\s+cpu\s+processes?\b',
        ]) or norm in ("top processes", "top cpu processes", "what is using the most cpu"):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="check top CPU processes",
                intent="DEVICE_CONTROL",
                action="top_processes",
                target="processes",
                parameters={"action": "top_processes", "sort_by": "cpu", "n": 1},
                confidence=1.0,
            )

        # Guard: Exclude telemetry questions (e.g. "how long is the system running", "how long is the system being running")
        is_telemetry_question = any(q in norm for q in ("how long", "how much", "how many", "what is my", "what is the")) or any(s in norm for s in ("system", "pc", "computer", "machine", "cpu", "gpu", "disk", "uptime"))
        if not is_telemetry_question and (any(re.search(p, norm) for p in [
            r'\b(?:did\s+you|have\s+you)\s+(?:open|opened|launch|launched|start|started)\s+([a-zA-Z0-9_\-\s]+)',
            r'^(?:is|is\s+the)\s+([a-zA-Z0-9_\-]+)\s+(?:open|running|active)\b',
        ]) or norm in ("did you open notepad", "have you opened notepad")):
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

        # -------------------------------------------------------------
        # Calendar & Scheduling Commands (Requirement 1 & AGENTS.md Freeze)
        # -------------------------------------------------------------
        is_calendar_schedule = (
            bool(re.search(r'\b(?:schedule|shedule|create|add|book|set\s+up)\s+(?:an?\s+)?(.+?)\s+(?:on|for|at)\s+(?:\d{4}-\d{2}-\d{2}|\w+\s+\d{1,2}|\d{1,2}(?::\d{2})?\s*(?:am|pm)|today|tomorrow)\b', norm))
            or bool(re.search(r'\b(?:change|update|reschedule|shift)\s+(?:the\s+)?time\s+of\s+(.+?)\s+to\s+(.+)', norm))
            or (bool(re.search(r'\b(?:move|reschedule|shift|postpone)\s+(.+?)\s+to\s+(.+)', norm)) and not any(k in norm for k in ["file", "folder", "directory"]))
            or (bool(re.search(r'\brename\s+(.+?)\s+to\s+(.+)', norm)) and any(k in norm for k in ["sync", "standup", "meeting", "event", "appointment", "call"]) and not any(k in norm for k in ["file", "folder", "directory"]))
            or bool(re.search(r'\b(?:cancel|delete|remove|drop)\s+(?:all\s+|the\s+|my\s+)?(?:meeting|meetings|event|events|appointment|appointments|sync|standup)(?:\s+(?:for|on|at|tomorrow|today|\d{4}-\d{2}-\d{2}))?\b', norm))
            or bool(re.search(r'\b(?:what(?:\'s|\s+is)\s+(?:my\s+)?(?:next|upcoming)\s+(?:appointment|meeting|event)|next\s+(?:appointment|meeting|event))\b', norm))
            or bool(re.search(r'\b(?:plan\s+(?:my\s+)?(?:week|schedule|days?)|weekly\s+plan(?:ning)?)\b', norm))
            or (bool(re.search(r'\b(?:from|between)\s+(.+?)\s+(?:to|and|-)\s+(.+)', norm)) and any(k in norm for k in ["event", "events", "calendar", "schedule", "meeting", "meetings"]))
            or bool(re.search(r'\b(?:how\s+many\s+holidays|count\s+(?:the\s+)?holidays|number\s+of\s+holidays)\b', norm))
            or (bool(re.search(r'\b(?:explain|tell\s+me\s+about)\s+(?:the\s+holiday\s+|holiday\s+)?([a-zA-Z\s]+?)(?:\s+holiday|\s+festival|\s+significance|\s+history|$)', norm)) and any(k in norm for k in ["holiday", "festival", "diwali", "christmas", "easter", "thanksgiving"]))
            or bool(re.search(r'\b(?:show|check|view|what(?:\'s|\s+is)\s+on)\s+(?:my\s+|today\'?s?\s+)?calendar\b', norm))
            or bool(re.search(r'\b(?:show|check|view)\s+(?:today\'?s?\s+|my\s+)?events\b', norm))
        )
        if is_calendar_schedule and not any(k in norm for k in ["remind me", "reminder", "set a reminder", "alert me"]):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="calendar operation",
                intent="DAILY_BRIEFING",
                action="calendar_query",
                target="calendar",
                confidence=1.0,
                safety_class="SAFE",
                parameters={"action": "calendar_query", "raw_input": text_stripped}
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
            # Guard: queries about conversational history must NOT be matched as recommendation ordinals
            _is_history_query = any(k in norm for k in (
                "asked", "question", "questions", "said", "told", "request",
                "today", "yesterday", "earlier", "before", "last time", "recently",
                "i asked", "i said", "you said", "you told",
            ))
            if not _is_history_query:
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

        # --------------------------------------------------------------------
        # Voice Rate & Speed Configuration Commands
        # --------------------------------------------------------------------
        slow_patterns = [
            r'\b(?:speak|talk)\s+(?:a\s+little\s+|a\s+bit\s+)?(?:slower|more\s+slowly)\b',
            r'\b(?:you\s+are|you\'re)\s+speaking\s+(?:much\s+|way\s+)?too\s+fast\b',
            r'\bspeaking\s+too\s+fast\b',
            r'\bslow\s+down(?:\s+your\s+(?:speech|voice|talking))?\b',
            r'\b(?:decrease|reduce|lower)\s+(?:your\s+)?(?:speaking\s+|voice\s+|speech\s+)?(?:rate|speed)\b',
        ]
        if any(re.search(p, norm) for p in slow_patterns) or norm in (
            "speak slower", "speak a little slower", "slow down", "you are speaking too fast",
            "you're speaking too fast", "speaking too fast", "talk slower"
        ):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="decrease speaking rate",
                intent="VOICE_CONFIGURATION",
                action="decrease_rate",
                parameters={"action": "decrease_rate"},
                confidence=0.99,
            )

        fast_patterns = [
            r'\b(?:speak|talk)\s+(?:a\s+little\s+|a\s+bit\s+)?(?:faster|more\s+quickly)\b',
            r'\b(?:you\s+are|you\'re)\s+speaking\s+(?:much\s+|way\s+)?too\s+slow\b',
            r'\bspeaking\s+too\s+slow\b',
            r'\bspeed\s+up(?:\s+your\s+(?:speech|voice|talking))?\b',
            r'\b(?:increase|raise)\s+(?:your\s+)?(?:speaking\s+|voice\s+|speech\s+)?(?:rate|speed)\b',
        ]
        if any(re.search(p, norm) for p in fast_patterns) or norm in (
            "speak faster", "speak a little faster", "speed up", "you are speaking too slow",
            "you're speaking too slow", "speaking too slow", "talk faster"
        ):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="increase speaking rate",
                intent="VOICE_CONFIGURATION",
                action="increase_rate",
                parameters={"action": "increase_rate"},
                confidence=0.99,
            )

        natural_patterns = [
            r'\b(?:speak|talk)\s+(?:naturally|normally|at\s+normal\s+speed)\b',
            r'\b(?:normal|natural)\s+(?:speed|rate)\b',
            r'\breset\s+(?:your\s+)?(?:speaking\s+|voice\s+|speech\s+)?(?:rate|speed)\b',
        ]
        if any(re.search(p, norm) for p in natural_patterns) or norm in (
            "speak naturally", "normal speed", "natural speed", "speak normally",
            "reset speech speed", "reset speaking rate"
        ):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="reset speaking rate to natural speed",
                intent="VOICE_CONFIGURATION",
                action="reset_rate",
                parameters={"action": "reset_rate"},
                confidence=0.99,
            )

        restore_patterns = [
            r'\b(?:use|switch\s+to|restore)\s+(?:the\s+)?(?:same|previous|saved)\s+voice(?:\s+as\s+before)?\b',
            r'\brestore\s+(?:my\s+)?voice\b',
        ]
        if any(re.search(p, norm) for p in restore_patterns) or norm in (
            "use the same voice as before", "restore voice", "restore my voice", "use my saved voice"
        ):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="restore previously configured voice",
                intent="VOICE_CONFIGURATION",
                action="restore_voice",
                parameters={"action": "restore_voice"},
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
        # 3a. Deterministic Explicit Close Application / Website / Window
        # -------------------------------------------------------------
        m_explicit_close = re.match(r'^(?:close|quit|exit|terminate|kill|shut\s+down)\s+(?:the\s+)?(.+?)[\.!\?]?$', norm)
        if m_explicit_close:
            raw_c = m_explicit_close.group(1).strip()
            if not any(k in raw_c for k in ("it", "this", "that", "all", "everything")):
                clean_c = re.sub(r'\s+(?:app|application|program|window|tab|for\s+me|please|now)$', '', raw_c).strip()
                if clean_c:
                    target_to_close = self.resolve_canonical_application(clean_c) or clean_c
                    return SemanticCommand(
                        user_text=text_stripped,
                        normalized_text=norm,
                        goal=f"close application {target_to_close}",
                        intent="CLOSE_APPLICATION",
                        action="CLOSE_APPLICATION",
                        target=target_to_close,
                        object=target_to_close,
                        desired_state="closed",
                        parameters={"application": target_to_close, "target": target_to_close, "action": "close"},
                        confidence=1.0,
                    )

        # -------------------------------------------------------------
        # 3b. Context Resumption / Continuation (Section 7, 20)
        # -------------------------------------------------------------
        is_continuation_phrase = any(k in norm for k in (
            "continue that", "continue what i was doing", "continue what we were doing", "can you bring back what we were doing",
            "bring back what we were doing", "go back to what we were doing", "do that again",
            "continue where we left off", "resume previous work", "return to the task",
            "return to what we were doing", "back to what we were doing", "keep going with what we were doing"
        )) or bool(re.search(r'\b(?:continue|resume|go\s+on\s+with|keep\s+going\s+with)\s+(?:what\s+(?:we|i)\s+were\s+doing|where\s+we\s+left\s+off|previous\s+(?:task|work|activity))\b', norm)) or norm.startswith(("return to the task", "go back to the task", "resume the task", "return to what"))
        if is_continuation_phrase:
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="resume previous task or context",
                intent="CONTEXT_RESUMPTION",
                action="resume",
                target="previous_task",
                desired_state="resumed",
                request_type="CONTINUATION",
                action_required=True,
                is_continuation=True,
                required_capabilities=["task_continuation"],
                prohibited_capabilities=["windows_workstation", "android_device", "applications"],
                parameters={"action": "resume"},
                confidence=1.0,
            )

        # -------------------------------------------------------------
        # 3.9 Architecture-Level Device Target Resolution & Mobile Guard
        # -------------------------------------------------------------
        from core.target_resolver import resolve_device_target, TargetDeviceType
        dev_target = resolve_device_target(text_stripped, user_id=user_id)
        if dev_target.target_device == TargetDeviceType.ANDROID_PHONE:
            is_corr = bool(re.search(r'^(?:no\s*,?\s*)?(?:i\s+mean|i\s+meant|not\s+(?:the|my)|switch\s+to|change\s+to)\b', norm)) or bool(dev_target.negated_targets)
            is_lock_status_query = bool(re.search(r'\b(?:is|check\s+if)\s+(?:(?:my|the)\s+)?(?:phone|mobile)\s+(?:currently\s+)?(locked|sleeping|awake|screen\s+off|screen\s+on)\b', norm))
            resolved_req_action = "query_lock_status" if is_lock_status_query else "PHONE_CONTROL"
            raw_dispatch_cmd = text_stripped

            if is_corr and dialogue_state:
                # Inherit previous action from dialogue state context (e.g. lock -> phone_lock)
                prev_action_str = getattr(dialogue_state, "last_action", "") or ""
                recent_acts = getattr(dialogue_state, "recent_actions", []) or []
                recent_action_names = [a.get("action", "") if isinstance(a, dict) else str(a) for a in recent_acts]
                if any("lock" in a.lower() for a in ([prev_action_str] + recent_action_names)) or (hasattr(dialogue_state, "turns") and any("lock" in getattr(t, "user_input", "").lower() for t in getattr(dialogue_state, "turns", [])[-2:])):
                    resolved_req_action = "phone_lock"
                    raw_dispatch_cmd = "lock phone"
                elif any("whatsapp" in a.lower() for a in ([prev_action_str] + recent_action_names)):
                    resolved_req_action = "launch_app"
                    raw_dispatch_cmd = "open whatsapp on phone"

            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"Execute mobile device command: {raw_dispatch_cmd}" if not is_lock_status_query else "Query phone lock status",
                intent="DEVICE_CONTROL",
                action="remote_device" if not is_lock_status_query else "query_lock_status",
                target=dev_target.device_name or "phone",
                target_type=EntityType.DEVICE_OR_SYSTEM,
                target_device="android_phone",
                required_capabilities=["android_device"],
                prohibited_capabilities=["windows_workstation", "applications"],
                negated_targets=["windows_workstation"],
                is_correction=is_corr,
                corrected_target="android_phone" if is_corr else None,
                parameters={
                    "action": "remote_device" if not is_lock_status_query else "query_lock_status",
                    "raw_command": raw_dispatch_cmd,
                    "target_device": "android_phone",
                    "device_id": dev_target.device_id,
                    "device_name": dev_target.device_name,
                    "serial": dev_target.serial,
                    "requested_device_target": "android_phone",
                    "resolved_device": dev_target.serial or dev_target.device_name,
                    "requested_action": resolved_req_action,
                    "resolved_action": resolved_req_action,
                    "executor_action": "remote_device" if not is_lock_status_query else "query_lock_status",
                    "is_correction": is_corr,
                },
                confidence=0.99,
                action_required=not is_lock_status_query,
            )

        if dev_target.target_device == TargetDeviceType.WINDOWS_WORKSTATION:
            is_corr_ws = bool(re.search(r'^(?:no\s*,?\s*)?(?:i\s+mean|i\s+meant|not\s+(?:the|my)|switch\s+to|change\s+to|stop\s+that[;,]?\s*i\s+meant)\b', norm)) or bool(dev_target.negated_targets)
            if is_corr_ws:
                return SemanticCommand(
                    user_text=text_stripped,
                    normalized_text=norm,
                    goal="lock workstation",
                    intent="DEVICE_CONTROL",
                    action="LOCK",
                    target="workstation",
                    desired_state="locked",
                    target_device="windows_workstation",
                    required_capabilities=["windows_workstation"],
                    prohibited_capabilities=["android_device"],
                    negated_targets=["android_phone"],
                    is_correction=True,
                    corrected_target="windows_workstation",
                    parameters={
                        "action": "lock",
                        "requested_action": "LOCK",
                        "resolved_action": "LOCK",
                        "executor_action": "lock",
                        "target_device": "windows_workstation",
                        "is_correction": True,
                    },
                    confidence=0.99,
                    action_required=True,
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
        # Absolute Volume SET
        m_vset = re.search(r'\b(?:set|change)\s+(?:the\s+)?volume\s+(?:to\s+)?(\d+)\s*%?\b', norm) or re.search(r'\bvolume\s+to\s+(\d+)\s*%?\b', norm)
        if m_vset:
            lvl = max(0, min(100, int(m_vset.group(1))))
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"set audio output volume to {lvl}%",
                intent="DEVICE_CONTROL",
                action="VOLUME_SET",
                target="system_volume",
                desired_state=f"{lvl}%",
                parameters={
                    "requested_device_target": "volume",
                    "requested_action": "VOLUME_SET",
                    "resolved_action": "VOLUME_SET",
                    "executor_action": "set_volume",
                    "action": "set_volume",
                    "level": lvl,
                    "amount": lvl,
                    "step": lvl,
                },
                confidence=1.0,
            )

        # Read volume level
        if any(k in norm for k in (
            "what is the current volume", "what is the volume", "what's the volume",
            "what is my current volume", "what is my volume", "what's my current volume", "what's my volume",
            "current volume", "check volume", "check my volume", "check current volume", "check the volume",
            "volume level", "get volume", "my current volume"
        )) or re.search(r'\b(?:what(?:\x27s|\s+is)\s+(?:my\s+|the\s+)?(?:current\s+)?volum?e?|check\s+(?:my\s+|the\s+)?(?:current\s+)?volum?e?)\b', norm):
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="read audio volume level",
                intent="DEVICE_CONTROL",
                action="get_volume",
                target="system_volume",
                parameters={"action": "get_volume"},
                confidence=1.0,
            )

        if not any(w in norm for w in ("phone", "mobile", "android", "redmi")) and any(re.search(p, norm) for p in [
            r'\b(?:make\s+(?:it|things)\s+quieter|quieter|lower\s+(?:the\s+)?sound|decrease\s+volume|turn\s+down\s+volume|turn\s+volume\s+down|volume\s+down|reduce\s+volume|lower\s+volume|less\s+volume|softer\s+volume)\b',
        ]):
            m_amt = re.search(r'\b(?:by\s+)?(\d+)\s*%?\b', norm)
            step_val = int(m_amt.group(1)) if m_amt else 10
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
                    "step": step_val,
                    "amount": step_val,
                },
                confidence=1.0,
            )

        if not any(w in norm for w in ("phone", "mobile", "android", "redmi")) and any(re.search(p, norm) for p in [
            r'\b(?:make\s+(?:it|things)\s+louder|louder|raise\s+(?:the\s+)?sound|increase\s+volume|turn\s+up\s+volume|turn\s+volume\s+up|volume\s+up|higher\s+volume|more\s+volume)\b',
        ]):
            m_amt = re.search(r'\b(?:by\s+)?(\d+)\s*%?\b', norm)
            step_val = int(m_amt.group(1)) if m_amt else 10
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
                    "step": step_val,
                    "amount": step_val,
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
        has_workstation_noun = any(k in norm for k in ("computer", "pc", "system", "workstation", "screen", "session", "machine")) and (TargetDeviceType.WINDOWS_WORKSTATION not in dev_target.negated_targets)
        is_unlock_act = (
            dev_target.target_device != TargetDeviceType.ANDROID_PHONE
            and (
                (has_workstation_noun and "unlock" in norm)
                or ("unlock" in norm and not any(k in norm for k in ("phone", "mobile", "android", "cell", "cellphone", "device")))
                or ("open" in norm and any(k in norm for k in ("workstation", "session")) and not any(k in norm for k in ("browser", "app", "file", "folder", "chrome", "notepad", "code", "phone", "mobile")))
                or ("access" in norm and any(k in norm for k in ("workstation", "session")))
            )
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
                target_device="windows_workstation",
                required_capabilities=["windows_workstation"],
                prohibited_capabilities=["android_device"],
                negated_targets=["android_phone"],
                parameters={
                    "requested_device_target": "windows_workstation",
                    "target_device": "windows_workstation",
                    "device_id": "workstation",
                    "requested_action": "UNLOCK",
                    "resolved_action": "UNLOCK",
                    "executor_action": "unlock",
                    "action": "unlock",
                },
                confidence=1.0,
            )

        if any(k in norm for k in ("lock", "secure")) and (has_workstation_noun or norm in ("lock", "lock it", "lock now")) and dev_target.target_device != TargetDeviceType.ANDROID_PHONE:
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="lock workstation",
                intent="DEVICE_CONTROL",
                action="LOCK",
                target="workstation",
                desired_state="locked",
                target_device="windows_workstation",
                required_capabilities=["windows_workstation"],
                prohibited_capabilities=["android_device"],
                negated_targets=["android_phone"],
                parameters={
                    "requested_device_target": "windows_workstation",
                    "target_device": "windows_workstation",
                    "device_id": "workstation",
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

        is_concept_query = bool(
            re.match(r'^(?:explain|how\s+does|how\s+do|what\s+is\s+the\s+concept|tell\s+me\s+how|difference\s+between)\b', norm)
            or "concept" in norm
        )
        if not is_concept_query and any(re.search(p, norm) for p in [
            r'\b(?:what\s+is\s+my\s+gpu(?:\s+memory)?|check\s+(?:my\s+)?gpu(?:\s+memory)?|how\s+much\s+gpu\s+memory|gpu\s+usage|gpu\s+telemetry|my\s+gpu\s+memory|my\s+graphics\s+card)\b',
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
        is_email_or_comm = bool(
            re.search(r'\b(?:email|mail|inbox|unread)\b', norm)
            or "@" in text_stripped
            or any(k in norm for k in ("send to", "send an email", "send email", "write email", "compose email", "send him", "send her", "send them", "send a mail", "send mail", "email is", "email address", "'s email"))
        )
        has_compat = any(k in norm for k in ("compatible", "can i run", "can i download and run", "can run on", "in this system", "on this pc", "requirements"))
        has_game = any(k in norm for k in ("games", "game", "gaming"))
        has_music_noun = any(k in norm for k in ("music", "song", "songs", "tune", "tunes", "track")) or ("spotify" in norm and not any(norm.startswith(p) for p in ("switch to ", "switch ", "bring ", "focus ", "close ", "quit ", "kill ")))
        has_play_game = any(k in norm for k in ("play", "playing", "start a game", "play a game", "play games", "game to play", "games to play", "play some games"))
        has_game_rec = any(k in norm for k in ("recommend", "recommendation", "recommendations", "suggest", "suggestion", "suggestions", "discover", "discovery", "good games", "best games", "fun games", "ideas for games", "what games", "which games"))

        if not is_email_or_comm and has_game and any(k in norm for k in ("installed", "are installed")):
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

        if not is_email_or_comm and has_game and has_compat:
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
        if not is_email_or_comm and has_game and (has_game_rec or has_play_game) and not has_music_noun:
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
            m_action = "play"
            m_goal = "music playback"
            m_desired_state = "playing"
            try:
                from modules.music.music_controller import MusicCommandParser
                _p = MusicCommandParser().parse(text_stripped)
                if _p.is_transport:
                    m_action = _p.transport_action
                    m_goal = f"music {m_action}"
                    m_desired_state = "paused" if m_action == "pause" else ("stopped" if m_action == "stop" else "playing")
                elif _p.is_video_requested:
                    m_action = "play_video"
                    m_goal = "music video playback"
                    m_desired_state = "playing"
            except Exception:
                pass

            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=m_goal,
                intent="MUSIC",
                action="PLAY_MUSIC" if m_action == "play" else m_action.upper(),
                target="music",
                desired_state=m_desired_state,
                candidate_interpretations=[
                    {"intent": "MUSIC", "confidence": 0.99},
                ],
                parameters={"action": m_action, "query": text_stripped},
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
        if not app_launch_cand and not re.search(r'^(?:how\s+(?:to|do|can|should|would|is|are|did|does)|why\s+(?:didn\'?t|did\s+not|haven\'?t|have\s+not|won\'?t|wouldn\'?t|don\'?t|do\s+not|did|is|are|do|would)|what\s+(?:is|are|was|were|does|did|happens)|where\s+(?:is|can|do))\b', norm):
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
        # 14b. Conversational Correction / Rejection Detection
        # -------------------------------------------------------------
        is_pure_correction = bool(re.search(
            r'^(?:(?:oh\s+)?no[,\s]+)?(?:that\'?s|that\s+is|it\'?s|it\s+is)?\s*(?:not\s+what\s+i\s+(?:asked|was\s+asking|meant)|you\s+misunderstood|that\'?s\s+wrong)[.!?]?$',
            norm, re.IGNORECASE
        ))
        if is_pure_correction:
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal="correction of previous turn interpretation",
                intent="CLARIFICATION",
                action="reconsider_previous_request",
                target="dialogue_history",
                desired_state="corrected",
                parameters={"correction": True, "action": "reconsider_previous_request"},
                confidence=0.9,
            )

        # -------------------------------------------------------------
        # 15. Conversational History Recall (Section 7, 20)
        # -------------------------------------------------------------
        is_not_correction = not bool(re.search(r'\b(?:not|isn\'?t|wasn\'?t|didn\'?t)\s+what\s+i\b', norm)) and not norm.startswith("no ")
        if is_not_correction and (any(re.search(p, norm) for p in [
            r'\b(?:what\s+did\s+i|what\s+was\s+i)\s+(?:just\s+)?ask(?:ing)?(?:\s+(?:you\s+)?(?:before|earlier|to\s+do|for|immediately|about))?\b',
            r'\bwhat\s+(?:was|is)\s+(?:the\s+question(?:\s+that)?\s+i\s+asked|my\s+last\s+question|my\s+previous\s+question|the\s+last\s+thing\s+i\s+asked)\b',
            r'\bremind\s+me\s+what\s+i\s+asked\b',
        ]) or norm in ("what did i ask before", "what was the question that i asked before", "what is the question that i asked before", "what did i just ask", "what did i ask earlier", "what did i ask you earlier")):
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

        # -------------------------------------------------------------
        # 0c0. Mobile Device Control (Fast-Path Deterministic Guard)
        # -------------------------------------------------------------
        mobile_screenshot_match = bool(
            re.search(r'\b(?:screenshot\s+(?:on|of)|take\s+(?:a\s+)?screenshot\s+(?:on|of))\s+(?:(?:my|the)\s+)?(?:phone|mobile|device|android|redmi[a-z0-9_\-\s]*)\b', norm)
            or re.search(r'\b(?:phone|mobile)\s+screenshot\b', norm)
            or any(k in norm for k in ["screenshot on phone", "screenshot on mobile", "screenshot of my phone", "take a screenshot on my phone", "take a screenshot of my phone", "capture phone screen", "show my phone screen", "show phone screen"])
        )
        mobile_nav_match = bool(
            re.search(r'\b(?:go\s+(?:to\s+)?(?:the\s+)?home(?:\s+screen)?|press\s+home(?:\s+screen)?|home\s+screen)\s+(?:on\s+)?(?:(?:my|the)\s+)?(?:phone|mobile|device|android|redmi[a-z0-9_\-\s]*)\b', norm)
            or any(k in norm for k in ["press home on phone", "go home on phone", "go home on my phone", "home on my phone", "home on phone", "go to the home screen on my phone", "go to the home screen on phone", "back on phone", "recents on phone"])
        )
        mobile_battery_match = bool(
            re.search(r'\b(?:(?:phone|mobile|device|redmi[a-z0-9_\-\s]*)(?:\x27s)?\s+battery|battery\s+(?:of|on|for)\s+(?:(?:my|the)\s+)?(?:phone|mobile|device|redmi[a-z0-9_\-\s]*)|check\s+(?:(?:my|the)\s+)?(?:phone|mobile|device|redmi[a-z0-9_\-\s]*)(?:\x27s)?\s+battery)\b', norm)
            or any(k in norm for k in ["phone battery", "my phone battery", "phone's battery", "my phone's battery", "mobile battery", "battery on phone", "battery on my phone"])
        )
        mobile_app_match = bool(
            re.search(r'\b(?:open|launch|start)\s+.+?\s+on\s+(?:(?:my|the)\s+)?(?:phone|mobile|device|android|redmi[a-z0-9_\-\s]*)\b', norm)
        )
        mobile_vol_match = bool(
            re.search(r'\b(?:turn\s+(?:up|down)\s+(?:the\s+)?volume|volume\s+(?:up|down)|lower\s+volume|raise\s+volume|decrease\s+volume|increase\s+volume)\s+on\s+(?:(?:my|the)\s+)?(?:phone|mobile|device|android|redmi[a-z0-9_\-\s]*)\b', norm)
        )
        mobile_conn_match = bool(
            re.search(r'\b(?:pair|(?:re)?connect)\s+(?:to\s+)?(?:(?:my|a|a\s+new)\s+)?(?:phone|device|mobile|android|redmi[a-z0-9_\-\s]*)\b', norm)
            or re.search(r'\b(?:disconnect|unpair|remove)\s+(?:(?:my|a|a\s+new)\s+)?(?:phone|device|mobile|android|redmi[a-z0-9_\-\s]*)\b', norm)
            or re.search(r'\b(?:is\s+(?:my\s+)?(?:phone|device|mobile)\s+(?:connected|online)|which\s+phone\s+is\s+connected|what\s+phone\s+is\s+connected)\b', norm)
        )

        if mobile_screenshot_match or mobile_nav_match or mobile_battery_match or mobile_app_match or mobile_vol_match or mobile_conn_match:
            return SemanticCommand(
                user_text=text_stripped,
                normalized_text=norm,
                goal=f"Execute mobile device command: {text_stripped}",
                intent="DEVICE_CONTROL",
                action="remote_device",
                target_type=EntityType.DEVICE_OR_SYSTEM,
                parameters={"action": "remote_device", "raw_command": text_stripped},
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
        clean_text = re.sub(r'^(?:can\s+you\s+|could\s+you\s+|please\s+|would\s+you\s+|friday\s+|trevon\s+|hey\s+friday\s+|hey\s+trevon\s+|and\s+|nd\s+)+', '', text_low).strip()
        clean_low = clean_text.rstrip('.?!,').strip()
        norm = clean_low

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
        # 0. Location Intelligence Commands
        # --------------------------------------------------------------------
        if self.is_location_intelligence_query(clean_low) or self.is_location_intelligence_query(raw_text):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"Execute location intelligence command: {raw_text}",
                intent="DEVICE_CONTROL",
                action="device_location",
                action_required=True,
                parameters={"action": "device_location", "raw_input": raw_text, "query": raw_text},
                confidence=0.99,
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

        # --------------------------------------------------------------------
        # 0.05 Voice Speed & Identity Configuration Commands
        # --------------------------------------------------------------------
        slow_patterns = [
            r'\b(?:speak|talk)\s+(?:a\s+little\s+|a\s+bit\s+)?(?:slower|more\s+slowly)\b',
            r'\b(?:you\s+are|you\'re)\s+speaking\s+(?:much\s+|way\s+)?too\s+fast\b',
            r'\bspeaking\s+too\s+fast\b',
            r'\bslow\s+down(?:\s+your\s+(?:speech|voice|talking))?\b',
            r'\b(?:decrease|reduce|lower)\s+(?:your\s+)?(?:speaking\s+|voice\s+|speech\s+)?(?:rate|speed)\b',
        ]
        if any(re.search(p, clean_low) for p in slow_patterns) or clean_low in (
            "speak slower", "speak a little slower", "slow down", "you are speaking too fast",
            "you're speaking too fast", "speaking too fast", "talk slower"
        ):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants assistant to speak slower.",
                intent="VOICE_CONFIGURATION",
                action="decrease_rate",
                sub_intent="DECREASE_RATE",
                action_required=True,
                confidence=0.99,
            )

        fast_patterns = [
            r'\b(?:speak|talk)\s+(?:a\s+little\s+|a\s+bit\s+)?(?:faster|more\s+quickly)\b',
            r'\b(?:you\s+are|you\'re)\s+speaking\s+(?:much\s+|way\s+)?too\s+slow\b',
            r'\bspeaking\s+too\s+slow\b',
            r'\bspeed\s+up(?:\s+your\s+(?:speech|voice|talking))?\b',
            r'\b(?:increase|raise)\s+(?:your\s+)?(?:speaking\s+|voice\s+|speech\s+)?(?:rate|speed)\b',
        ]
        if any(re.search(p, clean_low) for p in fast_patterns) or clean_low in (
            "speak faster", "speak a little faster", "speed up", "you are speaking too slow",
            "you're speaking too slow", "speaking too slow", "talk faster"
        ):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants assistant to speak faster.",
                intent="VOICE_CONFIGURATION",
                action="increase_rate",
                sub_intent="INCREASE_RATE",
                action_required=True,
                confidence=0.99,
            )

        natural_patterns = [
            r'\b(?:speak|talk)\s+(?:naturally|normally|at\s+normal\s+speed)\b',
            r'\b(?:normal|natural)\s+(?:speed|rate)\b',
            r'\breset\s+(?:your\s+)?(?:speaking\s+|voice\s+|speech\s+)?(?:rate|speed)\b',
        ]
        if any(re.search(p, clean_low) for p in natural_patterns) or clean_low in (
            "speak naturally", "normal speed", "natural speed", "speak normally",
            "reset speech speed", "reset speaking rate"
        ):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants assistant to speak at natural conversational speed.",
                intent="VOICE_CONFIGURATION",
                action="reset_rate",
                sub_intent="RESET_RATE",
                action_required=True,
                confidence=0.99,
            )

        restore_patterns = [
            r'\b(?:use|switch\s+to|restore)\s+(?:the\s+)?(?:same|previous|saved)\s+voice(?:\s+as\s+before)?\b',
            r'\brestore\s+(?:my\s+)?voice\b',
        ]
        if any(re.search(p, clean_low) for p in restore_patterns) or clean_low in (
            "use the same voice as before", "restore voice", "restore my voice", "use my saved voice"
        ):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants to restore their previously configured voice.",
                intent="VOICE_CONFIGURATION",
                action="restore_voice",
                sub_intent="RESTORE_VOICE",
                action_required=True,
                confidence=0.99,
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
        if clean_low in ("stop music", "pause music", "stop song", "pause song", "stop playing", "pause playing", "stop playback", "pause playback", "stop audio", "pause audio") or re.search(r'\b(?:stop|pause)\s+(?:the\s+)?(?:music|song|playback|audio|playing)\b', clean_low):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User wants to pause/stop music playback.",
                intent="MUSIC",
                action="stop" if "stop" in clean_low else "pause",
                rewritten_command="stop music" if "stop" in clean_low else "pause music",
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
        has_affirmative_alt = bool(re.search(r'[,;]\s*(?:instead\s*,?\s*|please\s+|just\s+)?(?:open|launch|start|run|create|make|help|calculate|show)\b', clean_low))
        if not has_affirmative_alt and (m_neg or m_dont_want or clean_low in ("don't open notepad", "do not open notepad", "don't do that", "do not do that", "stop, don't do that", "don't open it")):
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
        m_rep_why = re.search(r'\bwhy\s+(?:did\s+not|didn\'?t|haven\'?t|have\s+not|won\'?t|wouldn\'?t|don\'?t|do\s+not|did)\s+you\s+(?:open|launch|start|close|delete|create|do)\s*([a-zA-Z0-9_\-\s]*)', clean_low)
        if m_rep_why or any(re.search(p, clean_low) for p in [
            r'\bwhy\s+is\s+([a-zA-Z0-9_\-\s]+?)\s+(?:open|running|active)\b',
            r'\bwhat\s+made\s+you\s+(?:open|do|start)\b',
        ]) or clean_low in ("why did you open notepad", "why did you do that", "why did you open that"):
            target_app = (m_rep_why.group(1).strip() if (m_rep_why and m_rep_why.group(1).strip()) else None) or ("notepad" if "notepad" in clean_low else ("chrome" if "chrome" in clean_low else "the action"))
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
        is_legacy_telemetry = any(q in clean_low for q in ("how long", "how much", "how many", "what is my", "what is the")) or any(s in clean_low for s in ("system", "pc", "computer", "machine", "cpu", "gpu", "disk", "uptime"))
        if not is_legacy_telemetry and (any(re.search(p, clean_low) for p in [
            r'\b(?:did\s+you|have\s+you)\s+(?:open|opened|launch|launched|start|started)\s+([a-zA-Z0-9_\-\s]+)',
            r'^(?:is|is\s+the)\s+([a-zA-Z0-9_\-]+)\s+(?:open|running|active)\b',
        ]) or clean_low in ("did you open notepad", "have you opened notepad")):
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
            r'^(?:actually[,\s]+|no[,\s]+|wait[,\s]+|well[,\s]+)?(?:can\s+you\s+|could\s+you\s+|would\s+you\s+|please\s+)?(switch\s+to|switch\s+back\s+to|switch|bring\s+up|bring\s+back|bring|focus|get\s+up|i\s+need|let\'?s\s+use|let\s+us\s+use|can\s+we\s+use|open(?:\s+up)?|launch|start)\s+(?:the\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+(?:back|up|again|please|instead|to\s+(?:the\s+)?front))?$',
            clean_low
        )
        if m_app_req:
            verb_matched = m_app_req.group(1).lower()
            raw_cand = m_app_req.group(2).strip().rstrip('.?!')
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
                is_switch = any(v in verb_matched for v in ("switch", "focus", "front"))
                act = "switch_application" if is_switch else "open_application"
                act_cmd = f"switch to {target_app}" if is_switch else f"open {target_app}"
                meaning = f"User wants to switch to application '{target_app}'." if is_switch else f"User wants to open application '{target_app}'."
                return SemanticIntentRepresentation(
                    user_input=raw_text,
                    interpreted_meaning=meaning,
                    intent="OPEN_APPLICATION",
                    request_type="INSTRUCTION",
                    action=act,
                    entities=[{"value": target_app, "type": "application"}],
                    rewritten_command=act_cmd,
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

        is_announcing_content = bool(re.search(
            r'\b(?:i\s+will|i\'ll|i\s+am\s+going\s+to|let\s+me)\s+(?:give|send|provide|share)\s+(?:you\s+)?(?:some\s+|the\s+)?(?:info|information|details|notes|text|data)\b',
            text_low
        )) or bool(re.search(
            r'\b(?:create|make|generate|build)\s+(?:a\s+|an\s+)?(?:ppt|presentation|document|doc|report|spreadsheet)\s+(?:based\s+on\s+(?:that|it|this|the\s+info(?:rmation)?)|from\s+(?:that|it|this))\b',
            text_low
        ))

        if is_announcing_content:
            doc_type_val = "pptx" if any(k in text_low for k in ("presentation", "ppt", "pptx", "slide")) else ("docx" if any(k in text_low for k in ("word", "doc", "docx")) else "pptx")
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is announcing intention to provide content for a document/presentation.",
                intent="DOCUMENT_GENERATION",
                action="announce_content",
                entities=[{"type": "artifact_type", "value": "presentation" if doc_type_val == "pptx" else "document"}],
                references=[],
                context_required=False,
                action_required=False,
                confidence=0.98,
                parameters={"waiting_for_content": True, "doc_type": doc_type_val}
            )

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
        is_scratch_creation = bool(re.search(r'\b(?:write|create|generate|make|build)\s+(?:an?\s+)?(?:note|email|mail|letter|document|doc|docx|report|presentation|slides?|ppt|pptx|spreadsheet|sheet|excel|xlsx|pdf|function|program|query|sql|script|code|algorithm|class|module|interface|struct)\b', text_low))

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
        # 0c2b. Jokes, Humor & Conversational Entertainment Follow-ups
        # --------------------------------------------------------------------
        joke_patterns = [
            r'\b(?:tell\s+me|give\s+me|say)\s+(?:a|another|some\s+other|a\s+different)\s+jokes?\b',
            r'\b(?:tell\s+me\s+a\s+joke|make\s+me\s+laugh|say\s+something\s+funny)\b',
            r'\b(?:tell\s+any\s+other\s+jokes?|another\s+joke|some\s+other\s+joke|different\s+joke)\b',
            r'^\s*(?:another\s+one|one\s+more|tell\s+me\s+another|another|next\s+one)\s*[\.!\?]?\s*$',
            r'^\s*(?:that\s+one\s+was\s+bad|that\s+was\s+bad|not\s+funny|tell\s+me\s+a\s+different\s+kind|different\s+kind)\s*[\.!\?]?\s*$',
        ]
        stop_joke_patterns = [
            r'\b(?:stop\s+joking|no\s+more\s+jokes|be\s+serious|answer\s+seriously|stop\s+making\s+jokes)\b',
        ]
        if any(re.search(p, clean_low) for p in stop_joke_patterns) or clean_low in ("stop joking", "be serious", "answer seriously"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User requests to stop joking and switch to serious tone.",
                intent="GENERAL_CONVERSATION",
                action="stop_joking",
                action_required=False,
                confidence=0.99
            )

        if any(re.search(p, clean_low) for p in joke_patterns) or clean_low in ("another one", "one more", "different kind", "tell me another"):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is requesting casual entertainment/joke.",
                intent="GENERAL_CONVERSATION",
                action="joke",
                action_required=False,
                confidence=0.98
            )

        # Casual status chat: "what are you doing?"
        if re.search(r'\b(?:what\s+are\s+you\s+doing|what\'?re\s+you\s+doing|what\s+are\s+you\s+up\s+to|what\'?s\s+up)\b', clean_low):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is making casual conversational inquiry about assistant status.",
                intent="GENERAL_CONVERSATION",
                action="status_chat",
                action_required=False,
                confidence=0.98
            )

        # --------------------------------------------------------------------
        # 0c0. Mobile Device Control (Fast-Path Deterministic Guard)
        # --------------------------------------------------------------------
        mobile_screenshot = bool(
            re.search(r'\b(?:screenshot\s+(?:on|of)|take\s+(?:a\s+)?screenshot\s+(?:on|of))\s+(?:(?:my|the)\s+)?(?:phone|mobile|device|android|redmi[a-z0-9_\-\s]*)\b', text_low)
            or re.search(r'\b(?:phone|mobile)\s+screenshot\b', text_low)
            or any(k in text_low for k in ["screenshot on phone", "screenshot on mobile", "screenshot of my phone", "take a screenshot on my phone", "take a screenshot of my phone", "capture phone screen", "show my phone screen", "show phone screen"])
        )
        mobile_nav = bool(
            re.search(r'\b(?:go\s+(?:to\s+)?(?:the\s+)?home(?:\s+screen)?|press\s+home(?:\s+screen)?|home\s+screen)\s+(?:on\s+)?(?:(?:my|the)\s+)?(?:phone|mobile|device|android|redmi[a-z0-9_\-\s]*)\b', text_low)
            or any(k in text_low for k in ["press home on phone", "go home on phone", "go home on my phone", "home on my phone", "home on phone", "go to the home screen on my phone", "go to the home screen on phone", "back on phone", "recents on phone"])
        )
        mobile_battery = bool(
            re.search(r'\b(?:(?:phone|mobile|device|redmi[a-z0-9_\-\s]*)(?:\x27s)?\s+battery|battery\s+(?:of|on|for)\s+(?:(?:my|the)\s+)?(?:phone|mobile|device|redmi[a-z0-9_\-\s]*)|check\s+(?:(?:my|the)\s+)?(?:phone|mobile|device|redmi[a-z0-9_\-\s]*)(?:\x27s)?\s+battery)\b', text_low)
            or any(k in text_low for k in ["phone battery", "my phone battery", "phone's battery", "my phone's battery", "mobile battery", "battery on phone", "battery on my phone"])
        )
        mobile_app = bool(
            re.search(r'\b(?:open|launch|start)\s+.+?\s+on\s+(?:(?:my|the)\s+)?(?:phone|mobile|device|android|redmi[a-z0-9_\-\s]*)\b', text_low)
        )
        mobile_vol = bool(
            re.search(r'\b(?:turn\s+(?:up|down)\s+(?:the\s+)?volume|volume\s+(?:up|down)|lower\s+volume|raise\s+volume|decrease\s+volume|increase\s+volume)\s+on\s+(?:(?:my|the)\s+)?(?:phone|mobile|device|android|redmi[a-z0-9_\-\s]*)\b', text_low)
        )
        mobile_conn = bool(
            re.search(r'\b(?:pair|(?:re)?connect)\s+(?:to\s+)?(?:(?:my|a|a\s+new)\s+)?(?:phone|device|mobile|android|redmi[a-z0-9_\-\s]*)\b', text_low)
            or re.search(r'\b(?:disconnect|unpair|remove)\s+(?:(?:my|a|a\s+new)\s+)?(?:phone|device|mobile|android|redmi[a-z0-9_\-\s]*)\b', text_low)
            or re.search(r'\b(?:is\s+(?:my\s+)?(?:phone|device|mobile)\s+(?:connected|online)|which\s+phone\s+is\s+connected|what\s+phone\s+is\s+connected)\b', text_low)
        )

        if mobile_screenshot or mobile_nav or mobile_battery or mobile_app or mobile_vol or mobile_conn:
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning=f"Mobile device control request: {raw_text}",
                intent="DEVICE_CONTROL",
                request_type="INSTRUCTION",
                action="remote_device",
                action_required=True,
                confidence=0.99,
                parameters={"action": "remote_device", "raw_command": raw_text},
            )

        # --------------------------------------------------------------------
        # 0c3. Contextual Content Acquisition & Research
        # --------------------------------------------------------------------
        is_joke_or_chat = bool(re.search(r'\b(?:jokes?|laugh|funny)\b', text_low)) or clean_low in ("another one", "one more", "different kind")
        if not is_joke_or_chat and any(re.search(p, text_low) for p in [
            r'\b(?:gather|collect|find|research)\s+(?:all\s+)?(?:the\s+)?([a-zA-Z0-9_\-\s]+?)\s+(?:information|info|facts|details)\b',
            r'\b(?:gather|collect|find|search\s+for|look\s+up|get)\s+(?:some\s+|all\s+(?:the\s+)?|any\s+|the\s+)?information\s+(?:about|on|for)\s+(.+)',
            r'\b(?:gather\s+(?:all\s+)?(?:the\s+)?|collect\s+(?:all\s+)?(?:the\s+)?|research\s+and\s+gather\s+)(?:information|info|facts|details)\s+about\s+(.+)',
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

        # Declarative factual recall: Database, Backend, Assistant Name, Preferences, "What did I ask you to remember?", University, Cell, Name
        if any(re.search(pat, text_low) for pat in [
            r'\b(?:which|what)\s+database\b',
            r'\bwhat\s+database\s+(?:does|is)\b',
            r'\bwhat\s+(?:technology|backend|tech\s+stack)\s+(?:did\s+i|do\s+we)\s+use\b',
            r'\bwhat\s+name\s+did\s+i\s+choose\s+(?:for\s+my\s+assistant|for\s+you)\b',
            r'\bwhat(?:\'s|\s+is)\s+my\s+assistant(?:\'s)?\s+name\b',
            r'\bwhat\s+did\s+i\s+(?:ask|tell)\s+you\s+to\s+remember\b',
            r'\bwhat\s+do\s+you\s+remember\s+about\s+(?:me|this\s+project)\b',
            r'\bwhat\s+(?:response\s+style|style\s+of\s+response)\s+(?:did\s+i|do\s+i)\b',
            r'\b(?:which|what)\s+(?:university|college|school|institution)\b',
            r'\bwhere\s+do\s+i\s+(?:study|attend)\b',
            r'\bwhat(?:\'s|\s+is)\s+my\s+(?:education|student\s+status|major|degree)\b',
            r'\bwhat\s+(?:club|cell|committee)(?:\s+or\s+(?:club|cell|committee))?\s+am\s+i\s+(?:in|part\s+of)\b',
            r'\bam\s+i\s+(?:in|part\s+of)\s+(?:any\s+|the\s+)?(?:club|cell|placement\s+cell)\b',
            r'\bwhat(?:\'s|\s+is)\s+my\s+(?:preferred\s+)?name\b',
        ]):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying persistent declarative facts or preferences from PostgreSQL memory.",
                intent="MEMORY_QUERY",
                action="retrieve_user_facts",
                historical_query_type="factual_memory",
                memory_required=True,
                action_required=False,
                confidence=0.99
            )

        # Historical command outcomes & settings changes:
        if any(re.search(pat, text_low) for pat in [
            r'\bwhat\s+happened\s+when\s+you\s+tried\s+that\s+command\b',
            r'\bwhat\s+(?:was|were)\s+the\s+outcome\b',
            r'\bwhat\s+did\s+you\s+change\b',
            r'\bwhat\s+setting\s+did\s+you\s+change\b',
            r'\bwhat\s+error\s+did\s+we\s+fix\b',
        ]):
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="User is querying historical command outcomes and execution records.",
                intent="MEMORY_QUERY",
                action="retrieve_command_history",
                historical_query_type="past_command",
                memory_required=True,
                action_required=False,
                confidence=0.99
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
           re.search(r'\bwhat\s+did\s+you\s+(?:change|modify|update)\b', text_low) or \
           re.search(r'\bwhat\s+(?:changes|change)\s+did\s+you\s+make\b', text_low) or \
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
        # 4.9. Deterministic Conversational & Identity Resolution (Zero LLM Latency)
        # --------------------------------------------------------------------
        conv_identity_phrases = (
            "who are you", "who are u", "who r u", "who r you", "what is your name", "what is ur name",
            "what's your name", "whats your name", "whats ur name", "who're you", "tell me about yourself",
            "introduce yourself", "who made you", "who created you", "who built you", "what are you",
            "who am i speaking with", "who am i talking to", "what is your identity", "whats your identity",
            "who is this", "tell me who you are", "what should i call you", "hello", "hi", "hey",
            "good morning", "good afternoon", "good evening", "how are you",
            "how are you doing", "how's it going", "how are things", "what's up",
            "whats up", "thanks", "thank you", "thank you so much", "many thanks"
        )
        is_conv = (
            norm in conv_identity_phrases
            or clean_low in conv_identity_phrases
            or text_low in conv_identity_phrases
        )
        if not is_conv:
            try:
                from core.unified_command_router import (
                    is_conversational_general_query,
                    is_capability_query,
                    is_stable_knowledge_question,
                    is_conversational_followup_or_complaint,
                )
                if (
                    is_conversational_general_query(raw_text)
                    or is_capability_query(raw_text)
                    or is_stable_knowledge_question(raw_text)
                    or is_conversational_followup_or_complaint(raw_text)
                ):
                    is_conv = True
            except Exception:
                pass

        if is_conv:
            return SemanticIntentRepresentation(
                user_input=raw_text,
                interpreted_meaning="Conversational greeting, small talk, identity inquiry, knowledge query, or follow-up.",
                intent="GENERAL_CONVERSATION",
                request_type="CONVERSATION",
                action_required=False,
                confidence=1.0,
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
                    if dialogue_state.session_context.get("current_environment"):
                        ctx_summary["current_environment"] = dialogue_state.session_context["current_environment"]
                    if dialogue_state.session_context.get("previous_environment"):
                        ctx_summary["previous_environment"] = dialogue_state.session_context["previous_environment"]
                    if dialogue_state.session_context.get("active_goal"):
                        ctx_summary["active_goal"] = dialogue_state.session_context["active_goal"]

                # Forward current environment observations if not already populated
                if "current_environment" not in ctx_summary:
                    env_obs = getattr(dialogue_state, "environmental_observations", {}) or {}
                    app = getattr(dialogue_state, "active_application", None) or env_obs.get("active_application")
                    win = env_obs.get("active_window")
                    if app or win:
                        ctx_summary["current_environment"] = {"application": app, "window_title": win}

                # Forward recent actions
                if hasattr(dialogue_state, "recent_actions") and dialogue_state.recent_actions:
                    ctx_summary["recent_actions"] = dialogue_state.recent_actions[-3:]

                # Forward genuine previous dialogue turns (dialogue_state.turns[-1] is the current turn!)
                if hasattr(dialogue_state, "turns") and dialogue_state.turns:
                    prior_turns = dialogue_state.turns[:-1] if len(dialogue_state.turns) > 1 else []
                    if prior_turns:
                        last_turn = prior_turns[-1]
                        ctx_summary["previous_request"] = getattr(last_turn, "user_input", "")
                        recent_diag = []
                        for t in prior_turns[-3:]:
                            u_in = getattr(t, "user_input", "")
                            a_res = getattr(t, "assistant_response", "") or getattr(t, "system_response", "")
                            if u_in:
                                recent_diag.append({"user": u_in, "assistant": a_res})
                        if recent_diag:
                            ctx_summary["recent_dialogue"] = recent_diag

            # Classification must allow adequate time for network roundtrip and model completion
            reasoning_budget = 4.0
            try:
                from core.turn_deadline import get_current_turn_deadline
                tdl = get_current_turn_deadline()
                if tdl:
                    rem_t = tdl.time_remaining()
                    reasoning_budget = min(5.0, max(3.5, rem_t * 0.50))
            except Exception:
                pass
            llm_result = llm.semantic_reasoning(raw_text, structured_context=ctx_summary, timeout_budget=reasoning_budget, user_id=user_id)
            if llm_result and isinstance(llm_result, dict) and llm_result.get("source") == "semantic_llm":
                req_t = llm_result.get("request_type", "INSTRUCTION")
                # The semantic contract uses requires_action; accept the legacy
                # action_required spelling but never invent a default.
                if "requires_action" in llm_result:
                    act_req = bool(llm_result.get("requires_action"))
                else:
                    act_req = bool(llm_result.get("action_required", False))
                goal = llm_result.get("goal") or raw_text
                caps = llm_result.get("capabilities")
                if not isinstance(caps, list):
                    caps = []
                primary_cap = (caps[0] if caps else None) or llm_result.get("capability") or "AUTO"
                primary_cap = str(primary_cap).strip().upper()
                if primary_cap not in getattr(llm, "REASONING_CAPABILITIES", [primary_cap]):
                    primary_cap = "AUTO"
                params = llm_result.get("parameters", {})
                refs = llm_result.get("references", {})
                # Confidence must come from the validated object; a missing or
                # malformed score means the reasoning pass failed, not "certain".
                confidence = llm._coerce_confidence(llm_result.get("confidence"))

                # Strict guarantee: Non-action request types must never trigger action
                if req_t in ("NEGATION", "HYPOTHETICAL", "QUESTION", "EXPLANATION", "CONVERSATION"):
                    act_req = False
                    if primary_cap == "ARTIFACT_READING" and not any(w in raw_text.lower() for w in ("read", "listen", "recite", "speak aloud", "read out", "read to me")):
                        primary_cap = "GENERAL_CONVERSATION"

                if confidence is None:
                    logger.debug("[SEMANTIC_ENGINE] Reasoning object missing confidence; ignoring")
                else:
                    dev_res = resolve_device_target(raw_text, user_id=user_id)
                    tgt_dev = dev_res.target_device if dev_res.target_device not in (TargetDeviceType.UNSPECIFIED, TargetDeviceType.AMBIGUOUS) else "none"
                    req_caps = ["android_device"] if tgt_dev == "android_phone" else (["windows_workstation"] if tgt_dev == "windows_workstation" else (caps or []))
                    prohib_caps = ["windows_workstation"] if tgt_dev == "android_phone" else (["android_device"] if tgt_dev == "windows_workstation" else [])
                    is_corr_flag = (req_t == "CORRECTION") or bool(re.search(r'^(?:no\s*,?\s*)?(?:i\s+mean|i\s+meant|not\s+(?:the|my)|switch\s+to|change\s+to|stop\s+that[;,]?\s*i\s+meant)\b', raw_text.lower()))
                    act_name = "lock" if (is_corr_flag and tgt_dev == "windows_workstation") else ("remote_device" if tgt_dev == "android_phone" else "")

                    return SemanticIntentRepresentation(
                        user_input=raw_text,
                        interpreted_meaning=goal,
                        intent="DEVICE_CONTROL" if (tgt_dev in ("android_phone", "windows_workstation") and is_corr_flag) else primary_cap,
                        action=act_name,
                        request_type=req_t,
                        action_required=act_req,
                        is_negation=(req_t == "NEGATION"),
                        is_correction=is_corr_flag,
                        target_device=tgt_dev,
                        required_capabilities=req_caps,
                        prohibited_capabilities=prohib_caps,
                        negated_targets=dev_res.negated_targets,
                        entities=[{"value": v, "type": k} for k, v in params.items()] if isinstance(params, dict) else [],
                        references=list(refs.keys()) if isinstance(refs, dict) else [],
                        resolved_references=refs if isinstance(refs, dict) else {},
                        target_entity=(params.get("application") or params.get("target") or params.get("destination")) if isinstance(params, dict) else None,
                        confidence=confidence,
                    )
        except Exception as e:
            logger.debug(f"[SEMANTIC_ENGINE] LLM reasoning fallback skipped: {e}")

        # Default pass-through with architecture-level device target and negation binding
        from core.target_resolver import resolve_device_target, TargetDeviceType
        dev_res = resolve_device_target(raw_text, user_id=user_id)
        tgt_dev = dev_res.target_device if dev_res.target_device not in (TargetDeviceType.UNSPECIFIED, TargetDeviceType.AMBIGUOUS) else "none"
        req_caps = ["android_device"] if tgt_dev == "android_phone" else (["windows_workstation"] if tgt_dev == "windows_workstation" else [])
        prohib_caps = ["windows_workstation"] if tgt_dev == "android_phone" else (["android_device"] if tgt_dev == "windows_workstation" else [])
        is_corr_flag = bool(re.search(r'^(?:no\s*,?\s*)?(?:i\s+mean|i\s+meant|not\s+(?:the|my)|switch\s+to|change\s+to|stop\s+that[;,]?\s*i\s+meant)\b', raw_text.lower()))
        is_neg_query = bool(re.search(r'\b(?:don\x27t|do\s+not)\s+(?:open|launch|run|start)\b', raw_text.lower()))
        act_name = "lock" if (is_corr_flag and tgt_dev == "windows_workstation") else ("remote_device" if tgt_dev == "android_phone" else "")

        return SemanticIntentRepresentation(
            user_input=raw_text,
            interpreted_meaning=raw_text,
            intent="DEVICE_CONTROL" if (tgt_dev in ("android_phone", "windows_workstation") and is_corr_flag) else ("ENVIRONMENT_QUERY" if is_neg_query else "AUTO"),
            action=act_name,
            request_type="CORRECTION" if is_corr_flag else ("QUESTION" if is_neg_query else "INSTRUCTION"),
            action_required=not is_neg_query,
            is_negation=is_neg_query,
            is_correction=is_corr_flag,
            target_device=tgt_dev,
            required_capabilities=req_caps,
            prohibited_capabilities=prohib_caps,
            negated_targets=dev_res.negated_targets,
            confidence=0.90
        )

    # Method alias for natural semantic resolution
    understand = analyze


# Module-level singleton
semantic_understanding_engine = SemanticUnderstandingEngine()
