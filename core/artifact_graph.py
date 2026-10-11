"""
Multi-Artifact Memory & Context Graph System
Provides:
  1. ContentArtifact: Data model for acquired knowledge, code, summaries, and transformations.
  2. ArtifactContextGraph: Graph-structured in-memory & PostgreSQL persistent storage with
     bidirectional lineage, parent-child transformations, and multi-signal semantic indexing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("ArtifactContextGraph")


@dataclass
class ContentArtifact:
    """
    Structured representation of an acquired content artifact (code, information,
    explanation, summary, notes, data, etc.) with provenance and transformation lineage.
    """
    artifact_id: str = field(default_factory=lambda: f"art_{uuid.uuid4().hex[:10]}")
    user_id: int = 1
    topic: str = ""
    subtopic: Optional[str] = None
    content: str = ""
    content_type: str = "information"  # code, information, explanation, summary, notes, answer, document, data
    programming_language: Optional[str] = None  # python, javascript, cpp, sql, etc.
    original_user_request: str = ""
    task_id: Optional[str] = None
    parent_id: Optional[str] = None
    root_id: Optional[str] = None
    transformation_history: List[Dict[str, Any]] = field(default_factory=list)
    source_info: Dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    status: str = "active"
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.content_hash and self.content:
            self.content_hash = self.compute_hash(self.content)
        if not self.root_id:
            self.root_id = self.parent_id or self.artifact_id

    @staticmethod
    def compute_hash(text: str) -> str:
        """Compute deterministic SHA-256 content hash for deduplication."""
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Convert artifact to serializable dictionary."""
        return {
            "artifact_id": self.artifact_id,
            "user_id": self.user_id,
            "topic": self.topic,
            "subtopic": self.subtopic,
            "content": self.content,
            "content_type": self.content_type,
            "programming_language": self.programming_language,
            "original_user_request": self.original_user_request,
            "task_id": self.task_id,
            "parent_id": self.parent_id,
            "root_id": self.root_id,
            "transformation_history": self.transformation_history,
            "source_info": self.source_info,
            "content_hash": self.content_hash,
            "status": self.status,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ContentArtifact:
        """Construct artifact from dictionary."""
        valid_keys = {
            "artifact_id", "user_id", "topic", "subtopic", "content",
            "content_type", "programming_language", "original_user_request",
            "task_id", "parent_id", "root_id", "transformation_history",
            "source_info", "content_hash", "status", "created_at", "metadata"
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


class ArtifactContextGraph:
    """
    Context Graph maintaining all active and historical content artifacts simultaneously.
    Provides multi-signal semantic search, topological lineage tracing, deduplication,
    and PostgreSQL persistence.
    """

    def __init__(self):
        self._artifacts: Dict[str, ContentArtifact] = {}
        self._user_artifacts: Dict[int, List[str]] = {}
        self._loaded_users: Set[int] = set()

    def _ensure_user_loaded(self, user_id: int):
        """Lazy load artifacts from PostgreSQL into memory for user."""
        if user_id in self._loaded_users:
            return

        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        SELECT artifact_id, user_id, topic, subtopic, content,
                               content_type, programming_language, original_user_request,
                               task_id, parent_id, root_id, transformation_history,
                               source_info, content_hash, status,
                               EXTRACT(EPOCH FROM created_at) as created_at_sec, metadata
                        FROM content_artifacts
                        WHERE user_id = %s
                        ORDER BY created_at ASC;
                    """, (user_id,))
                    rows = cur.fetchall()
                    for r in rows:
                        art = ContentArtifact(
                            artifact_id=r[0],
                            user_id=r[1],
                            topic=r[2],
                            subtopic=r[3],
                            content=r[4],
                            content_type=r[5],
                            programming_language=r[6],
                            original_user_request=r[7] or "",
                            task_id=r[8],
                            parent_id=r[9],
                            root_id=r[10],
                            transformation_history=r[11] or [],
                            source_info=r[12] or {},
                            content_hash=r[13] or "",
                            status=r[14] or "active",
                            created_at=float(r[15]) if r[15] is not None else time.time(),
                            metadata=r[16] or {},
                        )
                        self._artifacts[art.artifact_id] = art
                        if user_id not in self._user_artifacts:
                            self._user_artifacts[user_id] = []
                        if art.artifact_id not in self._user_artifacts[user_id]:
                            self._user_artifacts[user_id].append(art.artifact_id)
        except Exception as e:
            logger.debug(f"[ARTIFACT_GRAPH] Note on DB load: {e}")

        self._loaded_users.add(user_id)

    def store_artifact(self, artifact: ContentArtifact) -> ContentArtifact:
        """
        Store a new or transformed artifact in the context graph and PostgreSQL.
        Handles deduplication by content hash while preserving transformation history.
        """
        user_id = artifact.user_id
        self._ensure_user_loaded(user_id)

        # Check for deduplication: identical content for same user
        existing_dup = self.find_by_hash(user_id, artifact.content_hash)
        if existing_dup and existing_dup.topic.lower() == artifact.topic.lower():
            # Update metadata and return existing instead of duplicate
            existing_dup.transformation_history.extend(artifact.transformation_history)
            existing_dup.metadata.update(artifact.metadata)
            return existing_dup

        self._artifacts[artifact.artifact_id] = artifact
        if user_id not in self._user_artifacts:
            self._user_artifacts[user_id] = []
        self._user_artifacts[user_id].append(artifact.artifact_id)

        # Persist to PostgreSQL
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        INSERT INTO content_artifacts (
                            artifact_id, user_id, topic, subtopic, content,
                            content_type, programming_language, original_user_request,
                            task_id, parent_id, root_id, transformation_history,
                            source_info, content_hash, status, metadata, created_at
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s, to_timestamp(%s)
                        )
                        ON CONFLICT (artifact_id) DO UPDATE SET
                            content = EXCLUDED.content,
                            transformation_history = EXCLUDED.transformation_history,
                            metadata = EXCLUDED.metadata,
                            created_at = EXCLUDED.created_at;
                    """, (
                        artifact.artifact_id,
                        artifact.user_id,
                        artifact.topic,
                        artifact.subtopic,
                        artifact.content,
                        artifact.content_type,
                        artifact.programming_language,
                        artifact.original_user_request,
                        artifact.task_id,
                        artifact.parent_id,
                        artifact.root_id,
                        json.dumps(artifact.transformation_history),
                        json.dumps(artifact.source_info),
                        artifact.content_hash,
                        artifact.status,
                        json.dumps(artifact.metadata),
                        artifact.created_at,
                    ))
        except Exception as e:
            logger.debug(f"[ARTIFACT_GRAPH] Note on DB store: {e}")

        logger.info(f"[ARTIFACT_GRAPH] Stored artifact {artifact.artifact_id} ({artifact.topic} / {artifact.content_type})")
        return artifact

    def add_artifact(self, topic: str, content: str, content_type: str = "information", user_id: int = 1, **kwargs) -> ContentArtifact:
        """Convenience method to construct and store an artifact."""
        art = ContentArtifact(topic=topic, content=content, content_type=content_type, user_id=user_id, **kwargs)
        return self.store_artifact(art)

    def create_child_artifact(self, parent_id: str, content: str, transformation_type: str, user_id: int = 1, **kwargs) -> ContentArtifact:
        """Create and store a transformed child artifact linked to parent."""
        parent = self.get_artifact(parent_id)
        topic = parent.topic if parent else "Transformed Content"
        c_type = "summary" if transformation_type == "summarize" else ("translation" if transformation_type == "translate" else "code")
        root_id = parent.root_id or parent.artifact_id if parent else None
        trans_hist = list(parent.transformation_history) if parent else []
        trans_hist.append({"operation": transformation_type, "timestamp": time.time(), "parent_id": parent_id})
        art = ContentArtifact(
            topic=topic,
            content=content,
            content_type=c_type,
            user_id=user_id,
            parent_id=parent_id,
            root_id=root_id,
            transformation_history=trans_hist,
            **kwargs
        )
        return self.store_artifact(art)

    def get_artifact(self, artifact_id: str) -> Optional[ContentArtifact]:
        """Retrieve artifact by ID."""
        return self._artifacts.get(artifact_id)

    def find_by_hash(self, user_id: int, content_hash: str) -> Optional[ContentArtifact]:
        """Find artifact by content hash for a given user."""
        if not content_hash:
            return None
        self._ensure_user_loaded(user_id)
        for aid in self._user_artifacts.get(user_id, []):
            art = self._artifacts.get(aid)
            if art and art.content_hash == content_hash:
                return art
        return None

    def list_artifacts(self, user_id: int, content_type: Optional[str] = None, status: str = "active") -> List[ContentArtifact]:
        """List all artifacts for user, optionally filtered by content_type and status."""
        self._ensure_user_loaded(user_id)
        res = []
        for aid in self._user_artifacts.get(user_id, []):
            art = self._artifacts.get(aid)
            if art and (status is None or art.status == status):
                if content_type is None or art.content_type == content_type:
                    res.append(art)
        return res

    def get_parent(self, artifact_id: str) -> Optional[ContentArtifact]:
        """Retrieve the immediate parent artifact."""
        art = self.get_artifact(artifact_id)
        if art and art.parent_id:
            return self.get_artifact(art.parent_id)
        return None

    def get_root(self, artifact_id: str) -> Optional[ContentArtifact]:
        """Retrieve the root parent artifact of a transformation chain."""
        art = self.get_artifact(artifact_id)
        if not art:
            return None
        if art.root_id and art.root_id in self._artifacts:
            return self._artifacts[art.root_id]
        curr = art
        while curr and curr.parent_id:
            parent = self.get_artifact(curr.parent_id)
            if not parent or parent == curr:
                break
            curr = parent
        return curr

    def get_children(self, artifact_id: str) -> List[ContentArtifact]:
        """Retrieve all immediate children transformed from this artifact."""
        children = []
        for art in self._artifacts.values():
            if art.parent_id == artifact_id:
                children.append(art)
        return children

    def get_lineage(self, artifact_id: str) -> List[ContentArtifact]:
        """
        Get the full chronological lineage chain from root to this artifact
        and all its subsequent descendants.
        """
        root = self.get_root(artifact_id)
        if not root:
            art = self.get_artifact(artifact_id)
            return [art] if art else []

        # Collect all descendants under root
        lineage = [root]
        queue = [root.artifact_id]
        seen = {root.artifact_id}

        while queue:
            curr_id = queue.pop(0)
            for child in self.get_children(curr_id):
                if child.artifact_id not in seen:
                    seen.add(child.artifact_id)
                    lineage.append(child)
                    queue.append(child.artifact_id)

        lineage.sort(key=lambda a: a.created_at)
        return lineage

    def record_insertion(
        self,
        artifact_id: str,
        user_id: int = 1,
        target_app: str = "unknown",
        target_window: str = "",
        target_file: Optional[str] = "",
        target_control: Optional[str] = "",
        execution_method: str = "direct_api",
        success: bool = True,
        verification_status: Optional[str] = None,
        verification_result: Optional[Dict[str, Any]] = None,
        failure_reason: Optional[str] = None,
        **kwargs: Any
    ) -> bool:
        """Record an insertion event in PostgreSQL for historical context and audit."""
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            v_res = verification_result or {"status": verification_status or ("success" if success else "failed")}
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        INSERT INTO artifact_insertions (
                            artifact_id, user_id, target_app, target_window,
                            target_file, target_control, execution_method,
                            success, verification_result, failure_reason
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s
                        );
                    """, (
                        artifact_id,
                        user_id,
                        target_app,
                        target_window,
                        target_file,
                        target_control,
                        execution_method,
                        success,
                        json.dumps(v_res),
                        failure_reason
                    ))
            return True
        except Exception as e:
            logger.debug(f"[ARTIFACT_GRAPH] Note on insertion audit: {e}")
            return False


# Singleton instance
_artifact_graph_instance: Optional[ArtifactContextGraph] = None

def get_artifact_graph() -> ArtifactContextGraph:
    """Get the singleton ArtifactContextGraph instance."""
    global _artifact_graph_instance
    if _artifact_graph_instance is None:
        _artifact_graph_instance = ArtifactContextGraph()
    return _artifact_graph_instance
