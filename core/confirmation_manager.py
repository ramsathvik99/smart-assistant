"""
Smart Assistant — Canonical Confirmation Manager (PHASE 7B)

Manages pending confirmation requests for actions that require explicit user
authorization before execution.

Design principles:
- User-scoped: User A cannot confirm User B's pending actions.
- Bounded: max pending confirmations per user enforced.
- Time-limited: TTL enforced; expired confirmations are never executed.
- Secret-safe: No credentials persisted in pending state.
- In-memory: intentionally ephemeral; confirmations do not survive restart.
- Explicit: "yes" only confirms a specific pending action by confirmation_id + user_id.
"""

from __future__ import annotations

import time
import uuid
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.risk_policy_engine import PolicyEvaluation, PolicyDecision, _redact_secrets

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIRMATION_TTL_SECONDS: float = 120.0   # 2-minute window
MAX_PENDING_PER_USER: int = 5              # Bounded queue per user


# ---------------------------------------------------------------------------
# Pending Confirmation State
# ---------------------------------------------------------------------------

class ConfirmationStatus(str):
    PENDING   = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED   = "EXPIRED"


@dataclass
class PendingConfirmation:
    """
    A single pending confirmation request.
    Bound to (confirmation_id, user_id) pair — never transferable between users.
    """
    confirmation_id:   str
    user_id:           int
    intent:            str
    action:            str
    target:            str
    effect:            str
    risk_level:        str
    reason:            str
    rules_applied:     List[str]
    original_command:  str
    policy_evaluation: Optional[Dict[str, Any]]   # serialised PolicyEvaluation
    created_at:        float = field(default_factory=time.time)
    expires_at:        float = field(default_factory=lambda: time.time() + CONFIRMATION_TTL_SECONDS)
    status:            str = ConfirmationStatus.PENDING

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def is_pending(self) -> bool:
        return self.status == ConfirmationStatus.PENDING and not self.is_expired()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confirmation_id":  self.confirmation_id,
            "user_id":          self.user_id,
            "intent":           self.intent,
            "action":           self.action,
            "target":           self.target,
            "effect":           self.effect,
            "risk_level":       self.risk_level,
            "reason":           self.reason,
            "rules_applied":    self.rules_applied,
            "original_command": _redact_secrets(self.original_command),
            "status":           self.status,
            "created_at":       self.created_at,
            "expires_at":       self.expires_at,
            "seconds_remaining": max(0.0, self.expires_at - time.time()),
        }


# ---------------------------------------------------------------------------
# Confirmation Manager
# ---------------------------------------------------------------------------

class ConfirmationManager:
    """
    In-memory, user-scoped store for pending confirmation requests.

    Lifecycle:
        create_pending_confirmation()  → returns confirmation_id
        get_pending_confirmation()     → retrieves if valid and user-matched
        confirm()                      → marks CONFIRMED, returns context to resume
        cancel()                       → marks CANCELLED
        expire()                       → marks EXPIRED
        get_user_pending()             → lists active confirmations for a user
    """

    def __init__(self) -> None:
        self._store: Dict[str, PendingConfirmation] = {}   # confirmation_id -> PendingConfirmation
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_pending_confirmation(
        self,
        user_id:          int,
        intent:           str,
        original_command: str,
        policy_evaluation: PolicyEvaluation,
        ttl_seconds:      float = CONFIRMATION_TTL_SECONDS,
    ) -> PendingConfirmation:
        """
        Register a new pending confirmation for a user.

        Args:
            user_id:           Authenticated user creating the request.
            intent:            Intent name that triggered the confirmation.
            original_command:  The original command string (will be redacted).
            policy_evaluation: The PolicyEvaluation that required confirmation.
            ttl_seconds:       Time-to-live for this pending confirmation.

        Returns:
            PendingConfirmation object with a unique confirmation_id.
        """
        cr = getattr(policy_evaluation, "confirmation_request", None) if policy_evaluation else None
        conf_id = str(uuid.uuid4())

        # Determine risk level safely
        risk_val = "CRITICAL"
        if cr and getattr(cr, "risk_level", None):
            risk_val = cr.risk_level
        elif policy_evaluation and getattr(policy_evaluation, "risk_level", None):
            risk_val = policy_evaluation.risk_level.value if hasattr(policy_evaluation.risk_level, "value") else str(policy_evaluation.risk_level)
        elif policy_evaluation and getattr(policy_evaluation, "assessment", None) and getattr(policy_evaluation.assessment, "risk_level", None):
            risk_val = policy_evaluation.assessment.risk_level.value

        reason_val = cr.reason if (cr and getattr(cr, "reason", None)) else (
            policy_evaluation.rationale if (policy_evaluation and getattr(policy_evaluation, "rationale", None)) else "Explicit user confirmation required"
        )
        rules_val = cr.rules_applied if (cr and getattr(cr, "rules_applied", None)) else (
            policy_evaluation.policy_rules_applied if (policy_evaluation and getattr(policy_evaluation, "policy_rules_applied", None)) else []
        )
        pe_dict = policy_evaluation.to_dict() if (policy_evaluation and hasattr(policy_evaluation, "to_dict")) else {}

        pending = PendingConfirmation(
            confirmation_id   = conf_id,
            user_id           = user_id,
            intent            = intent,
            action            = cr.action if (cr and getattr(cr, "action", None)) else intent,
            target            = cr.target if (cr and getattr(cr, "target", None)) else "",
            effect            = cr.effect if (cr and getattr(cr, "effect", None)) else "",
            risk_level        = risk_val,
            reason            = reason_val,
            rules_applied     = rules_val,
            original_command  = original_command,    # will be redacted on serialisation
            policy_evaluation = pe_dict,
            expires_at        = time.time() + ttl_seconds,
        )

        with self._lock:
            # Enforce per-user bounded queue
            user_pending = [c for c in self._store.values()
                            if c.user_id == user_id and c.is_pending()]
            if len(user_pending) >= MAX_PENDING_PER_USER:
                # Expire the oldest
                oldest = min(user_pending, key=lambda c: c.created_at)
                oldest.status = ConfirmationStatus.EXPIRED

            self._store[conf_id] = pending

        return pending

    # ------------------------------------------------------------------
    # Retrieve
    # ------------------------------------------------------------------

    def get_pending_confirmation(
        self,
        confirmation_id: str,
        user_id:         int,
    ) -> Optional[PendingConfirmation]:
        """
        Retrieve a pending confirmation — only if it belongs to user_id and has not expired.
        Returns None on mismatch, expiry, or absence.
        """
        with self._lock:
            c = self._store.get(confirmation_id)
            if c is None:
                return None
            # USER ISOLATION: never return another user's confirmation
            if c.user_id != user_id:
                return None
            if c.is_expired():
                c.status = ConfirmationStatus.EXPIRED
                return None
            if c.status != ConfirmationStatus.PENDING:
                return None
            return c

    # ------------------------------------------------------------------
    # Confirm
    # ------------------------------------------------------------------

    def confirm(
        self,
        confirmation_id: str,
        user_id:         int,
    ) -> Optional[PendingConfirmation]:
        """
        Mark a pending confirmation as CONFIRMED.
        Returns the confirmed PendingConfirmation (with original context) or None.
        """
        with self._lock:
            c = self.get_pending_confirmation(confirmation_id, user_id)
            if c is None:
                return None
            c.status = ConfirmationStatus.CONFIRMED
            return c

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    def cancel(
        self,
        confirmation_id: str,
        user_id:         int,
    ) -> bool:
        """
        Cancel a pending confirmation. Returns True if cancelled, False if not found.
        """
        with self._lock:
            c = self.get_pending_confirmation(confirmation_id, user_id)
            if c is None:
                return False
            c.status = ConfirmationStatus.CANCELLED
            return True

    # ------------------------------------------------------------------
    # User-level operations
    # ------------------------------------------------------------------

    def get_user_pending(self, user_id: int) -> List[PendingConfirmation]:
        """Return all active pending confirmations for a user."""
        with self._lock:
            result = []
            for c in self._store.values():
                if c.user_id == user_id:
                    if c.is_expired():
                        c.status = ConfirmationStatus.EXPIRED
                    elif c.status == ConfirmationStatus.PENDING:
                        result.append(c)
            return result

    def cancel_all_for_user(self, user_id: int) -> int:
        """Cancel all pending confirmations for a user. Returns count cancelled."""
        with self._lock:
            count = 0
            for c in self._store.values():
                if c.user_id == user_id and c.status == ConfirmationStatus.PENDING:
                    c.status = ConfirmationStatus.CANCELLED
                    count += 1
            return count

    def find_latest_pending(self, user_id: int) -> Optional[PendingConfirmation]:
        """Return the most recently created pending confirmation for a user."""
        pending = self.get_user_pending(user_id)
        if not pending:
            return None
        return max(pending, key=lambda c: c.created_at)

    def find_latest_confirmation(self, user_id: int) -> Optional[PendingConfirmation]:
        """Return the most recently created confirmation for a user (pending or expired)."""
        with self._lock:
            candidates = [c for c in self._store.values() if c.user_id == user_id]
            if not candidates:
                return None
            return max(candidates, key=lambda c: c.created_at)

    def purge_expired(self) -> int:
        """Remove expired entries from store. Returns count purged."""
        with self._lock:
            expired_ids = [
                cid for cid, c in self._store.items()
                if c.is_expired() or c.status in (ConfirmationStatus.CANCELLED, ConfirmationStatus.CONFIRMED)
            ]
            for cid in expired_ids:
                del self._store[cid]
            return len(expired_ids)

    # ------------------------------------------------------------------
    # Permission Scope Management (Phase 7 / Level 1)
    # ------------------------------------------------------------------

    def grant_scope(self, user_id: int, scope: str, ttl_seconds: float = 3600.0) -> None:
        """Grant a time-bounded permission scope (e.g. 'SYSTEM_CONTROL') to a user."""
        uid = int(user_id) if (user_id is not None and str(user_id).isdigit()) else 1
        with self._lock:
            if not hasattr(self, "_granted_scopes"):
                self._granted_scopes = {}
            if uid not in self._granted_scopes:
                self._granted_scopes[uid] = {}
            self._granted_scopes[uid][scope.upper()] = time.time() + ttl_seconds

    def has_scope(self, user_id: int, scope: str) -> bool:
        """Check whether a user holds an active, non-expired permission scope."""
        uid = int(user_id) if (user_id is not None and str(user_id).isdigit()) else 1
        with self._lock:
            if not hasattr(self, "_granted_scopes"):
                return False
            user_scopes = self._granted_scopes.get(uid, {})
            exp = user_scopes.get(scope.upper())
            if exp is None:
                return False
            if time.time() > exp:
                del user_scopes[scope.upper()]
                return False
            return True

    def revoke_scope(self, user_id: int, scope: Optional[str] = None) -> None:
        """Revoke a permission scope (or all scopes) for a user."""
        uid = int(user_id) if (user_id is not None and str(user_id).isdigit()) else 1
        with self._lock:
            if not hasattr(self, "_granted_scopes"):
                return
            if scope:
                self._granted_scopes.get(uid, {}).pop(scope.upper(), None)
            else:
                self._granted_scopes.pop(uid, None)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_confirmation_manager: Optional[ConfirmationManager] = None

def get_confirmation_manager() -> ConfirmationManager:
    global _confirmation_manager
    if _confirmation_manager is None:
        _confirmation_manager = ConfirmationManager()
    return _confirmation_manager
