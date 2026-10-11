"""
Smart Assistant — Canonical Execution Experience Memory Engine (PHASE 5)

Provides structured, user-isolated execution experience memory across interactions.
Enables future planning and recovery to benefit from previously verified outcomes
and strategy results without unrestricted autonomous learning.

Execution Experience is STRICTLY DISTINCT from conversational memory and user preferences.
Current verified environment state strictly takes precedence over historical experience.
"""

from __future__ import annotations

import os
import re
import time
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple
from collections import deque

from core.db_pool import get_db_pool
from core.outcome_verifier import (
    OutcomeStatus,
    ConfidenceLevel,
    ExecutionRecord,
)


# ============================================================================
# Configuration & Constants
# ============================================================================

DEFAULT_EXPERIENCE_RETENTION_DAYS = int(os.getenv("EXECUTION_EXPERIENCE_RETENTION_DAYS", "90"))
SECRET_PATTERNS = [
    re.compile(r'(?i)(password|passwd|pwd|secret|api[_-]?key|token|bearer|jwt|auth)["\']?\s*[:=]\s*["\']?([^"\'\s,;]+)'),
    re.compile(r'(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}'),
    re.compile(r'ey[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}'), # JWT
]


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class ExecutionAttempt:
    """Individual action/strategy attempt inside a complete execution episode."""
    attempt_index: int
    strategy_id: str
    strategy_type: str                     # "initial", "retry", "adaptive"
    action_command: str
    verification_status: str               # "VERIFIED_SUCCESS", "VERIFIED_FAILURE", "UNCERTAIN"
    failure_reason: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_index": self.attempt_index,
            "strategy_id": self.strategy_id,
            "strategy_type": self.strategy_type,
            "action_command": self.action_command,
            "verification_status": self.verification_status,
            "failure_reason": self.failure_reason,
            "timestamp": self.timestamp,
        }


@dataclass
class ExecutionExperience:
    """
    Canonical Execution Experience Episode.
    Represents a complete action execution episode, including its initial attempt,
    intermediate propagation retries, adaptive strategies, and final verified outcome.
    """
    experience_id: str
    execution_id: str
    user_id: int
    intent: str
    command_signature: str
    action_signature: str
    environment_context: Dict[str, Any] = field(default_factory=dict)
    expected_outcome: Dict[str, Any] = field(default_factory=dict)
    observed_outcome: Dict[str, Any] = field(default_factory=dict)
    verification_status: str = "UNKNOWN"
    confidence: str = "HIGH"
    failure_classification: Optional[str] = None
    strategy_id: Optional[str] = None
    strategy_type: Optional[str] = None
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    adaptation_attempts: int = 0
    final_status: str = "UNKNOWN"
    duration_ms: int = 0
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "execution_id": self.execution_id,
            "user_id": self.user_id,
            "intent": self.intent,
            "command_signature": self.command_signature,
            "action_signature": self.action_signature,
            "environment_context": self.environment_context,
            "expected_outcome": self.expected_outcome,
            "observed_outcome": self.observed_outcome,
            "verification_status": self.verification_status,
            "confidence": self.confidence,
            "failure_classification": self.failure_classification,
            "strategy_id": self.strategy_id,
            "strategy_type": self.strategy_type,
            "attempts": self.attempts,
            "adaptation_attempts": self.adaptation_attempts,
            "final_status": self.final_status,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass
class StrategyStats:
    """Historical effectiveness statistics for a specific strategy."""
    strategy_id: str
    total_attempts: int
    success_count: int
    failure_count: int
    success_rate: float
    sample_volume: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "total_attempts": self.total_attempts,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "sample_volume": self.sample_volume,
        }


@dataclass
class ExperienceSummary:
    """Compact summary of historical execution evidence for an intent/signature."""
    intent: str
    command_signature: str
    total_episodes: int
    strategies: Dict[str, StrategyStats] = field(default_factory=dict)
    most_successful_strategy: Optional[str] = None
    recent_failure_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "command_signature": self.command_signature,
            "total_episodes": self.total_episodes,
            "strategies": {k: v.to_dict() for k, v in self.strategies.items()},
            "most_successful_strategy": self.most_successful_strategy,
            "recent_failure_reasons": self.recent_failure_reasons,
        }


# ============================================================================
# Signature Generation & Sanitization
# ============================================================================

def generate_command_signature(intent: str, command_or_input: str, target_hint: Optional[str] = None) -> str:
    """
    Generates a deterministic normalized command signature to cluster related interactions.
    e.g. 'Please open Chrome' -> 'OPEN_APPLICATION:chrome'
    """
    intent_up = (intent or "").upper().strip()
    text = (command_or_input or "").lower().strip()

    # 1. OPEN_APPLICATION
    if intent_up == "OPEN_APPLICATION" or text.startswith(("open ", "launch ", "start ")):
        target = target_hint or ""
        if not target:
            m = re.match(r"(?:open|launch|start)\s+([a-zA-Z0-9_\-\.]+)", text)
            if m:
                target = m.group(1)
        target_norm = target.replace(".exe", "").strip().lower()
        if not target_norm:
            target_norm = "unknown"
        return f"OPEN_APPLICATION:{target_norm}"

    # 2. FILE_OPERATIONS
    if intent_up == "FILE_OPERATIONS" or any(w in text for w in ["file", "delete", "create", "load"]):
        op = "open"
        if any(w in text for w in ["delete", "remove", "erase"]):
            op = "delete"
        elif any(w in text for w in ["create", "save", "write"]):
            op = "create"
        ext = "generic"
        m_ext = re.search(r'\.([a-zA-Z0-9]+)', text)
        if m_ext:
            ext = m_ext.group(1).lower()
        return f"FILE_OPERATIONS:{op}:{ext}"

    # 3. AUDIO / VOLUME
    if any(w in text for w in ["volume", "mute", "unmute"]):
        if "mute" in text:
            return "AUDIO_VOLUME:mute"
        elif "unmute" in text:
            return "AUDIO_VOLUME:unmute"
        m_num = re.search(r'(\d+)', text)
        if m_num:
            return f"AUDIO_VOLUME:set:{m_num.group(1)}"
        return "AUDIO_VOLUME:adjust"

    # 4. REMINDERS
    if intent_up == "REMINDERS" or "remind" in text:
        if any(w in text for w in ["list", "show", "get"]):
            return "REMINDERS:list"
        return "REMINDERS:create"

    # 5. DOCUMENT_GENERATION
    if intent_up == "DOCUMENT_GENERATION" or any(w in text for w in ["pdf", "docx", "pptx", "xlsx"]):
        doc_type = "document"
        for t in ["pdf", "docx", "pptx", "xlsx"]:
            if t in text:
                doc_type = t
                break
        return f"DOCUMENT_GENERATION:{doc_type}"

    # 6. TASK_MANAGEMENT
    if intent_up == "TASK_MANAGEMENT" or "task" in text:
        if "cancel" in text:
            return "TASK_MANAGEMENT:cancel"
        return "TASK_MANAGEMENT:run"

    # 7. SMART_HOME
    if intent_up == "SMART_HOME" or any(w in text for w in ["light", "fan", "ac"]):
        state = "off" if any(w in text for w in ["off", "turn off", "disable"]) else "on"
        dev = "device"
        for d in ["light", "fan", "ac", "switch"]:
            if d in text:
                dev = d
                break
        return f"SMART_HOME:{dev}:{state}"

    # Generic fallback
    first_words = "_".join(re.findall(r'\b[a-zA-Z0-9]+\b', text)[:2])
    return f"{intent_up}:{first_words or 'generic'}"


def redact_secrets(text_or_dict: Any) -> Any:
    """
    Sanitizes and redacts passwords, tokens, API keys, and sensitive secrets.
    """
    if isinstance(text_or_dict, str):
        cleaned = text_or_dict
        # Pattern 0 has a group 1 capturing the key name
        cleaned = SECRET_PATTERNS[0].sub(r'\1: [REDACTED]', cleaned)
        # Patterns 1+ match raw tokens
        for pattern in SECRET_PATTERNS[1:]:
            cleaned = pattern.sub('[REDACTED]', cleaned)
        return cleaned
    elif isinstance(text_or_dict, dict):
        cleaned_dict = {}
        for k, v in text_or_dict.items():
            k_low = str(k).lower()
            if any(s in k_low for s in ["password", "secret", "token", "key", "auth", "jwt", "credential"]):
                cleaned_dict[k] = "[REDACTED]"
            else:
                cleaned_dict[k] = redact_secrets(v)
        return cleaned_dict
    elif isinstance(text_or_dict, list):
        return [redact_secrets(item) for item in text_or_dict]
    return text_or_dict


def sanitize_environment_context(obs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Creates a compact, privacy-safe environment context.
    Avoids storing unrestricted filesystem, private files, or tokens.
    """
    if not obs:
        return {}

    sanitized = {}
    if "active_application" in obs:
        sanitized["active_application"] = str(obs["active_application"])[:60]
    if "foreground_window_title" in obs:
        sanitized["foreground_window_title"] = redact_secrets(str(obs["foreground_window_title"])[:80])
    if "caps_lock" in obs:
        sanitized["caps_lock"] = obs["caps_lock"]
    if "num_lock" in obs:
        sanitized["num_lock"] = obs["num_lock"]
    if "master_volume" in obs:
        sanitized["master_volume"] = obs["master_volume"]
    if "platform" in obs:
        sanitized["platform"] = obs["platform"]
    if "running_processes" in obs:
        # Keep only process names, max 10
        procs = [os.path.basename(str(p)).lower() for p in obs["running_processes"][:10]]
        sanitized["running_processes"] = procs

    return redact_secrets(sanitized)


# ============================================================================
# Canonical Experience Manager
# ============================================================================

class ExecutionExperienceManager:
    """
    Canonical Execution Experience Memory Manager.
    Handles persistence, targeted user-isolated retrieval, staleness decay,
    and aggregation into strategy effectiveness evidence.
    """

    def __init__(self):
        self.pool = get_db_pool()
        # In-memory sliding window cache for fast access & offline resilience
        self._memory_cache: deque[ExecutionExperience] = deque(maxlen=200)
        self._recorded_execution_ids: set = set()
        self._table_checked = False
        self._ensure_table()

    def _ensure_table(self):
        if self._table_checked:
            return
        if not self.pool or not self.pool.is_healthy():
            self.pool = get_db_pool()
        if self.pool and self.pool.is_healthy():
            try:
                with self.pool.get_cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS execution_experiences (
                            experience_id VARCHAR(64) PRIMARY KEY,
                            execution_id VARCHAR(64),
                            user_id INTEGER,
                            intent VARCHAR(64),
                            command_signature VARCHAR(128),
                            action_signature VARCHAR(128),
                            environment_context JSONB,
                            expected_outcome JSONB,
                            observed_outcome JSONB,
                            verification_status VARCHAR(32),
                            confidence VARCHAR(32),
                            failure_classification VARCHAR(64),
                            strategy_id VARCHAR(64),
                            strategy_type VARCHAR(32),
                            attempts JSONB,
                            adaptation_attempts INTEGER,
                            final_status VARCHAR(32),
                            duration_ms INTEGER,
                            created_at TIMESTAMP WITH TIME ZONE,
                            metadata JSONB
                        );
                        CREATE INDEX IF NOT EXISTS idx_exec_exp_user_intent ON execution_experiences(user_id, intent);
                        CREATE INDEX IF NOT EXISTS idx_exec_exp_sig ON execution_experiences(command_signature);
                    """)
                self._table_checked = True
            except Exception as e:
                pass

    def record_experience(self, exp: ExecutionExperience) -> bool:
        """
        Persists an execution experience episode to PostgreSQL with in-memory caching.
        Non-blocking & fail-safe: failures never block primary user actions.
        """
        if not exp or not exp.user_id:
            return False

        if exp.execution_id in self._recorded_execution_ids:
            # Check if this exact experience ID was already cached
            for cached in self._memory_cache:
                if cached.execution_id == exp.execution_id:
                    return True

        self._recorded_execution_ids.add(exp.execution_id)

        # Add to in-memory cache first
        self._memory_cache.append(exp)

        # Phase 9: Continuous learning ingestion
        try:
            from core.continuous_learning import get_learning_engine
            get_learning_engine().process_experience(exp)
        except Exception as _cl_err:
            pass

        # Check DB pool health
        if not self.pool or not self.pool.is_healthy():
            self.pool = get_db_pool()
            if not self.pool or not self.pool.is_healthy():
                print("[EXPERIENCE] [WARN] Database not connected. Experience cached in-memory only.")
                return False

        try:
            with self.pool.get_cursor() as cur:
                # Pre-flight: verify user exists before inserting experience to prevent FK violation
                if exp.user_id is not None:
                    try:
                        cur.execute("SELECT 1 FROM users WHERE id = %s LIMIT 1;", (int(exp.user_id),))
                        if not cur.fetchone():
                            print(f"[EXPERIENCE] [WARN] Cannot persist experience: user {exp.user_id} does not exist in database.")
                            return False
                    except Exception as user_exc:
                        print(f"[EXPERIENCE] [WARN] Pre-flight user verification error: {user_exc}")
                        return False

                cur.execute("""
                    INSERT INTO execution_experiences (
                        experience_id, execution_id, user_id, intent,
                        command_signature, action_signature, environment_context,
                        expected_outcome, observed_outcome, verification_status,
                        confidence, failure_classification, strategy_id,
                        strategy_type, attempts, adaptation_attempts,
                        final_status, duration_ms, created_at, metadata
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, to_timestamp(%s), %s
                    )
                    ON CONFLICT (experience_id) DO NOTHING;
                """, (
                    exp.experience_id,
                    exp.execution_id,
                    int(exp.user_id),
                    exp.intent,
                    exp.command_signature,
                    exp.action_signature,
                    json.dumps(redact_secrets(exp.environment_context)),
                    json.dumps(redact_secrets(exp.expected_outcome)),
                    json.dumps(redact_secrets(exp.observed_outcome)),
                    exp.verification_status,
                    exp.confidence,
                    exp.failure_classification,
                    exp.strategy_id,
                    exp.strategy_type,
                    json.dumps(exp.attempts),
                    exp.adaptation_attempts,
                    exp.final_status,
                    exp.duration_ms,
                    exp.created_at,
                    json.dumps(redact_secrets(exp.metadata)),
                ))
            return True
        except Exception as e:
            print(f"[EXPERIENCE] [WARN] Non-blocking experience persistence error: {e}")
            return False

    def record_from_execution_record(
        self,
        record: ExecutionRecord,
        duration_ms: int = 0
    ) -> Optional[ExecutionExperience]:
        """
        Bridges a Phase 3/4 ExecutionRecord to a persisted Phase 5 ExecutionExperience episode.
        Only records when the execution is in a meaningful terminal state.
        """
        if not record or not record.user_id:
            return None

        if record.execution_id in self._recorded_execution_ids:
            for cached in self._memory_cache:
                if cached.execution_id == record.execution_id:
                    return cached
            return None

        # Build command signature
        cmd_sig = generate_command_signature(record.intent, record.original_command)
        action_sig = f"{record.intent}:{record.action}"

        # Build structured attempts list
        attempts = []
        # Initial attempt
        attempts.append({
            "attempt_index": 0,
            "strategy_id": "INITIAL_ACTION",
            "strategy_type": "initial",
            "action_command": record.original_command,
            "verification_status": record.final_status,
            "failure_reason": record.verification_result.failure_reason if record.verification_result else None,
            "timestamp": record.timestamps.get("timestamp", time.time())
        })

        # Recovery attempts if any
        if record.recovery_decisions:
            for idx, dec in enumerate(record.recovery_decisions, start=1):
                strat = dec.get("strategy") if isinstance(dec, dict) else getattr(dec, "strategy", None)
                strat_dict = strat.to_dict() if hasattr(strat, "to_dict") else (strat if isinstance(strat, dict) else {})
                attempts.append({
                    "attempt_index": idx,
                    "strategy_id": strat_dict.get("strategy_id", "RECOVERY_ATTEMPT"),
                    "strategy_type": "retry" if strat_dict.get("is_retry") else "adaptive",
                    "action_command": strat_dict.get("recovery_command", ""),
                    "verification_status": record.final_status,
                    "failure_reason": dec.get("failure_reason") if isinstance(dec, dict) else getattr(dec, "failure_reason", None),
                    "timestamp": time.time()
                })

        uid = int(record.user_id) if str(record.user_id).isdigit() else 1

        exp = ExecutionExperience(
            experience_id=f"exp_{uuid.uuid4().hex[:12]}",
            execution_id=record.execution_id,
            user_id=uid,
            intent=record.intent,
            command_signature=cmd_sig,
            action_signature=action_sig,
            environment_context=sanitize_environment_context(record.post_state),
            expected_outcome=record.expected_state or {},
            observed_outcome=record.post_state or {},
            verification_status=record.final_status,
            confidence=record.verification_result.confidence.value if record.verification_result else "HIGH",
            failure_classification=record.failure_classification,
            strategy_id=record.selected_strategy,
            strategy_type="adaptive" if record.adaptation_attempted else "direct",
            attempts=attempts,
            adaptation_attempts=record.adaptation_attempts,
            final_status=record.final_recovery_status or record.final_status,
            duration_ms=duration_ms,
            created_at=time.time(),
            metadata={"source": "brain_execution_pipeline"}
        )

        self.record_experience(exp)
        return exp

    # ------------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------------

    def get_relevant_experiences(
        self,
        user_id: int,
        intent: str,
        command_signature: str = "",
        environment_context: Optional[Dict[str, Any]] = None,
        limit: int = 10
    ) -> List[ExecutionExperience]:
        """
        Retrieves historical execution experiences relevant to the current user, intent,
        and command signature.
        Uses PostgreSQL when available; falls back to in-memory cache when offline.
        Ranks by relevance and applies staleness decay.
        """
        if not user_id:
            return []

        user_id = int(user_id)
        intent_up = (intent or "").upper().strip()
        experiences: List[ExecutionExperience] = []

        # 1. Try DB retrieval
        if self.pool and self.pool.is_healthy():
            try:
                with self.pool.get_cursor() as cur:
                    # Query user-isolated experiences matching intent
                    cur.execute("""
                        SELECT experience_id, execution_id, user_id, intent,
                               command_signature, action_signature, environment_context,
                               expected_outcome, observed_outcome, verification_status,
                               confidence, failure_classification, strategy_id,
                               strategy_type, attempts, adaptation_attempts,
                               final_status, duration_ms, EXTRACT(EPOCH FROM created_at), metadata
                        FROM execution_experiences
                        WHERE user_id = %s AND intent = %s
                        ORDER BY created_at DESC
                        LIMIT 50;
                    """, (user_id, intent_up))

                    rows = cur.fetchall()
                    for r in rows:
                        exp = ExecutionExperience(
                            experience_id=r[0],
                            execution_id=r[1],
                            user_id=r[2],
                            intent=r[3],
                            command_signature=r[4],
                            action_signature=r[5],
                            environment_context=r[6] if isinstance(r[6], dict) else json.loads(r[6] or '{}'),
                            expected_outcome=r[7] if isinstance(r[7], dict) else json.loads(r[7] or '{}'),
                            observed_outcome=r[8] if isinstance(r[8], dict) else json.loads(r[8] or '{}'),
                            verification_status=r[9],
                            confidence=r[10],
                            failure_classification=r[11],
                            strategy_id=r[12],
                            strategy_type=r[13],
                            attempts=r[14] if isinstance(r[14], list) else json.loads(r[14] or '[]'),
                            adaptation_attempts=r[15],
                            final_status=r[16],
                            duration_ms=r[17],
                            created_at=float(r[18]),
                            metadata=r[19] if isinstance(r[19], dict) else json.loads(r[19] or '{}'),
                        )
                        experiences.append(exp)
            except Exception as e:
                print(f"[EXPERIENCE] [WARN] DB retrieval error: {e}. Falling back to in-memory cache.")

        # 2. In-memory cache fallback / merge
        if not experiences:
            for exp in reversed(self._memory_cache):
                if exp.user_id == user_id and exp.intent == intent_up:
                    experiences.append(exp)

        # 3. Score & Rank by Relevance
        scored: List[Tuple[float, ExecutionExperience]] = []
        now = time.time()

        for exp in experiences:
            score = 10.0  # Base intent match

            # Signature exact match
            if command_signature and exp.command_signature == command_signature:
                score += 50.0
            elif command_signature and command_signature.split(":")[-1] in exp.command_signature:
                score += 20.0

            # Environment similarity
            if environment_context and exp.environment_context:
                app_curr = (environment_context.get("active_application") or "").lower()
                app_exp = (exp.environment_context.get("active_application") or "").lower()
                if app_curr and app_exp and app_curr == app_exp:
                    score += 15.0

            # Staleness Decay: older experiences lose relevance
            age_days = (now - exp.created_at) / 86400.0
            decay = min(age_days * 0.5, 25.0)  # Max 25 points decay over 50 days
            score = max(score - decay, 1.0)

            scored.append((score, exp))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    # ------------------------------------------------------------------------
    # Summarization & Evidence Aggregation
    # ------------------------------------------------------------------------

    def get_experience_summary(
        self,
        user_id: int,
        intent: str,
        command_signature: str = ""
    ) -> ExperienceSummary:
        """
        Computes a compact summary of strategy effectiveness evidence.
        Preserves sample volume so that 2/2 is not treated the same as 200/200.
        """
        experiences = self.get_relevant_experiences(
            user_id=user_id,
            intent=intent,
            command_signature=command_signature,
            limit=50
        )

        strategies: Dict[str, Dict[str, int]] = {}
        failure_reasons: List[str] = []

        for exp in experiences:
            # Aggregate strategies from attempts
            for att in exp.attempts:
                strat_id = att.get("strategy_id") or "UNKNOWN_STRATEGY"
                if strat_id not in strategies:
                    strategies[strat_id] = {"attempts": 0, "successes": 0, "failures": 0}
                strategies[strat_id]["attempts"] += 1
                if att.get("verification_status") == OutcomeStatus.VERIFIED_SUCCESS.value:
                    strategies[strat_id]["successes"] += 1
                else:
                    strategies[strat_id]["failures"] += 1
                    if att.get("failure_reason"):
                        failure_reasons.append(att["failure_reason"])

            # Also check terminal strategy if present
            if exp.strategy_id and exp.strategy_id not in strategies:
                strategies[exp.strategy_id] = {"attempts": 0, "successes": 0, "failures": 0}
                strategies[exp.strategy_id]["attempts"] += 1
                if exp.verification_status == OutcomeStatus.VERIFIED_SUCCESS.value:
                    strategies[exp.strategy_id]["successes"] += 1
                else:
                    strategies[exp.strategy_id]["failures"] += 1

        stats_map: Dict[str, StrategyStats] = {}
        best_strat: Optional[str] = None
        best_rate = -1.0
        best_vol = 0

        for strat_id, counts in strategies.items():
            tot = counts["attempts"]
            succ = counts["successes"]
            fail = counts["failures"]
            rate = (succ / tot) if tot > 0 else 0.0
            stat = StrategyStats(
                strategy_id=strat_id,
                total_attempts=tot,
                success_count=succ,
                failure_count=fail,
                success_rate=round(rate, 2),
                sample_volume=tot
            )
            stats_map[strat_id] = stat

            # Best strategy prioritizes success rate with volume weighting
            if rate > best_rate or (rate == best_rate and tot > best_vol):
                best_rate = rate
                best_vol = tot
                best_strat = strat_id

        return ExperienceSummary(
            intent=intent,
            command_signature=command_signature,
            total_episodes=len(experiences),
            strategies=stats_map,
            most_successful_strategy=best_strat,
            recent_failure_reasons=failure_reasons[:5]
        )

    # ------------------------------------------------------------------------
    # Retention & Maintenance
    # ------------------------------------------------------------------------

    def cleanup_expired_experiences(self, retention_days: int = DEFAULT_EXPERIENCE_RETENTION_DAYS) -> int:
        """
        Deletes experiences older than retention_days from PostgreSQL.
        Returns the number of deleted records.
        """
        if not self.pool or not self.pool.is_healthy():
            return 0

        deleted_count = 0
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("""
                    DELETE FROM execution_experiences
                    WHERE created_at < NOW() - INTERVAL '%s days';
                """, (int(retention_days),))
                deleted_count = cur.rowcount
            print(f"[EXPERIENCE] [MAINTENANCE] Cleaned up {deleted_count} expired experience records (> {retention_days} days).")
        except Exception as e:
            print(f"[EXPERIENCE] [WARN] Experience cleanup error: {e}")

        return deleted_count


# ============================================================================
# Singleton Accessor
# ============================================================================

_global_experience_manager = ExecutionExperienceManager()

def get_experience_manager() -> ExecutionExperienceManager:
    return _global_experience_manager
