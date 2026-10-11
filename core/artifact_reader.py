"""
Stateful Artifact Reading Controller & Persistent Reading Session Manager.
Provides:
  1. Chunked reading pipeline: Artifact -> sections -> paragraphs -> sentences/chunks.
  2. Persistent reading cursor and session tracking in PostgreSQL (artifact_reading_sessions).
  3. Integration with TTSCoordinator & legacy TTS (start, pause/stop, resume, complete).
  4. Precise cursor advance only after chunk completion is confirmed.
  5. Multi-artifact and cross-restart resumption support.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.artifact_graph import ContentArtifact, get_artifact_graph

logger = logging.getLogger("ArtifactReader")


class ReadingStatus(str, Enum):
    QUEUED = "QUEUED"
    READING = "READING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass
class ReadingChunk:
    chunk_index: int
    text: str
    section_title: str = ""
    char_length: int = 0
    word_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_index": self.chunk_index,
            "text": self.text,
            "section_title": self.section_title,
            "char_length": self.char_length or len(self.text),
            "word_count": self.word_count or len(self.text.split()),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReadingChunk:
        return cls(
            chunk_index=int(data.get("chunk_index", 0)),
            text=str(data.get("text", "")),
            section_title=str(data.get("section_title", "")),
            char_length=int(data.get("char_length", 0)),
            word_count=int(data.get("word_count", 0)),
        )


@dataclass
class ReadingSession:
    session_id: str = field(default_factory=lambda: f"readsess_{uuid.uuid4().hex[:10]}")
    user_id: int = 1
    artifact_id: str = ""
    status: ReadingStatus = ReadingStatus.QUEUED
    current_chunk_idx: int = 0
    total_chunks: int = 0
    last_completed_chunk_idx: int = -1
    char_offset: int = 0
    word_offset: int = 0
    chunks: List[ReadingChunk] = field(default_factory=list)
    artifact_version: str = ""
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stopped_at: Optional[float] = None
    completed_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "artifact_id": self.artifact_id,
            "status": self.status.value,
            "current_chunk_idx": self.current_chunk_idx,
            "total_chunks": self.total_chunks,
            "last_completed_chunk_idx": self.last_completed_chunk_idx,
            "char_offset": self.char_offset,
            "word_offset": self.word_offset,
            "chunk_data": [c.to_dict() for c in self.chunks],
            "artifact_version": self.artifact_version,
            "error": self.error,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "stopped_at": self.stopped_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }


class ArtifactReadingController:
    """
    Stateful controller managing chunked reading, persistent cursor progression,
    TTS playback synchronization, and seamless stop/continue operations.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._active_sessions: Dict[int, ReadingSession] = {}  # user_id -> ReadingSession
        self._stop_events: Dict[str, threading.Event] = {}     # session_id -> Event
        self._worker_threads: Dict[str, threading.Thread] = {} # session_id -> Thread
        self.graph = get_artifact_graph()

    # ------------------------------------------------------------------------
    # Chunking Engine
    # ------------------------------------------------------------------------

    def chunk_content(self, content: str, content_type: str = "information") -> List[ReadingChunk]:
        """
        Partition raw content into readable, manageable chunks for TTS.
        Hierarchy: Sections / Headers -> Paragraphs -> Sentences (<= 250 characters each).
        """
        chunks: List[ReadingChunk] = []
        if not content or not content.strip():
            return chunks

        # Code artifacts: chunk by function / block / group of lines
        if content_type == "code":
            lines = content.strip().split("\n")
            current_block: List[str] = []
            block_idx = 0
            for line in lines:
                current_block.append(line)
                if len("\n".join(current_block)) >= 180 or line.strip().startswith(("def ", "class ", "if __name__")):
                    b_text = "\n".join(current_block).strip()
                    if b_text:
                        chunks.append(ReadingChunk(
                            chunk_index=block_idx,
                            text=b_text,
                            section_title="Code Segment",
                            char_length=len(b_text),
                            word_count=len(b_text.split())
                        ))
                        block_idx += 1
                    current_block = []
            if current_block:
                b_text = "\n".join(current_block).strip()
                if b_text:
                    chunks.append(ReadingChunk(
                        chunk_index=block_idx,
                        text=b_text,
                        section_title="Code Segment",
                        char_length=len(b_text),
                        word_count=len(b_text.split())
                    ))
            return chunks

        # Standard text, explanation, summary, information
        # Step 1: Split into sections / paragraphs
        paragraphs = [p.strip() for p in re.split(r'\n{2,}', content) if p.strip()]
        chunk_idx = 0

        for para in paragraphs:
            # Check for header
            header_match = re.match(r'^(?:#+\s*|(?:\d+\.|\*|\-)\s+)?([A-Z][A-Za-z0-9\s\-_:]{2,50})(?:\n|$)', para)
            sec_title = header_match.group(1).strip() if header_match else "Overview"

            # Clean markdown formatting for clean audio narration
            clean_para = re.sub(r'[*_#`>]', '', para).strip()
            
            # Sentence split
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', clean_para) if s.strip()]
            buffer = ""
            for sent in sentences:
                if len(buffer) + len(sent) + 1 <= 220:
                    buffer = f"{buffer} {sent}".strip()
                else:
                    if buffer:
                        chunks.append(ReadingChunk(
                            chunk_index=chunk_idx,
                            text=buffer,
                            section_title=sec_title,
                            char_length=len(buffer),
                            word_count=len(buffer.split())
                        ))
                        chunk_idx += 1
                    buffer = sent
            if buffer:
                chunks.append(ReadingChunk(
                    chunk_index=chunk_idx,
                    text=buffer,
                    section_title=sec_title,
                    char_length=len(buffer),
                    word_count=len(buffer.split())
                ))
                chunk_idx += 1

        return chunks

    # ------------------------------------------------------------------------
    # Session Initialization & Retrieval
    # ------------------------------------------------------------------------

    def get_active_session(self, user_id: int = 1) -> Optional[ReadingSession]:
        """Get the active or latest paused reading session for this user (in-memory or DB)."""
        with self._lock:
            sess = self._active_sessions.get(user_id)
            if sess:
                return sess
            return self.load_latest_reading_session(user_id) or self.load_latest_paused_session(user_id)

    def is_reading(self, user_id: int = 1) -> bool:
        """Check if reading playback is currently actively occurring for this user."""
        with self._lock:
            sess = self.get_active_session(user_id)
            if sess and sess.status in (ReadingStatus.READING, ReadingStatus.QUEUED):
                worker = self._worker_threads.get(sess.session_id)
                if worker and worker.is_alive():
                    return True
                return sess.status == ReadingStatus.READING
            return False

    def start_reading(
        self,
        artifact: ContentArtifact,
        user_id: int = 1,
        from_beginning: bool = False,
        async_playback: bool = True
    ) -> Dict[str, Any]:
        """
        Start or restart reading an artifact aloud.
        """
        with self._lock:
            # Check if there is an active session for this user reading something else
            existing_sess = self.get_active_session(user_id)
            if existing_sess and existing_sess.status == ReadingStatus.READING:
                self.stop_reading(user_id)

            # Check if there is an existing paused session for this exact artifact
            session = None
            if not from_beginning:
                session = self._find_session_for_artifact(artifact.artifact_id, user_id)

            if not session or from_beginning or session.status in (ReadingStatus.COMPLETED, ReadingStatus.FAILED):
                # Verify content
                chunks = self.chunk_content(artifact.content, artifact.content_type)
                if not chunks:
                    return {
                        "status": "error",
                        "response": f"The artifact '{artifact.topic}' contains no readable content.",
                    }

                session = ReadingSession(
                    user_id=user_id,
                    artifact_id=artifact.artifact_id,
                    status=ReadingStatus.QUEUED,
                    current_chunk_idx=0,
                    total_chunks=len(chunks),
                    last_completed_chunk_idx=-1,
                    chunks=chunks,
                    artifact_version=artifact.content_hash,
                    metadata={"topic": artifact.topic, "content_type": artifact.content_type}
                )
            else:
                # Existing session resumed
                # Verify that artifact has not been modified
                if session.artifact_version and artifact.content_hash != session.artifact_version:
                    logger.warning("[ARTIFACT_READER] Artifact version changed; re-chunking from beginning.")
                    chunks = self.chunk_content(artifact.content, artifact.content_type)
                    session.chunks = chunks
                    session.total_chunks = len(chunks)
                    session.current_chunk_idx = 0
                    session.last_completed_chunk_idx = -1
                    session.artifact_version = artifact.content_hash

            self._active_sessions[user_id] = session
            self._persist_session(session)

            stop_event = threading.Event()
            self._stop_events[session.session_id] = stop_event

            if async_playback:
                worker = threading.Thread(
                    target=self._run_reading_worker,
                    args=(session, stop_event),
                    daemon=True,
                    name=f"ReaderWorker-{session.session_id}"
                )
                self._worker_threads[session.session_id] = worker
                worker.start()
            else:
                # Synchronous / test execution
                self._run_reading_worker(session, stop_event)

            curr_idx = min(session.current_chunk_idx, len(session.chunks) - 1) if session.chunks else 0
            first_text = session.chunks[curr_idx].text if session.chunks and curr_idx >= 0 else ""
            return {
                "status": "success",
                "session_id": session.session_id,
                "artifact_id": session.artifact_id,
                "topic": artifact.topic,
                "current_chunk": session.current_chunk_idx + 1,
                "total_chunks": session.total_chunks,
                "response": f"Reading '{artifact.topic}': {first_text}",
                "chunk_text": first_text,
            }

    def continue_reading(self, user_id: int = 1, async_playback: bool = True) -> Dict[str, Any]:
        """
        Resume reading from the exact last saved cursor position.
        """
        with self._lock:
            # 1. Check in-memory active session
            session = self._active_sessions.get(user_id)

            # 2. Check PostgreSQL persistence if none in memory or to refresh paused session
            if not session or session.status in (ReadingStatus.STOPPED, ReadingStatus.PAUSED):
                db_sess = self.load_latest_paused_session(user_id)
                if db_sess:
                    session = db_sess

            if not session:
                return {
                    "status": "error",
                    "error_code": "NO_PAUSED_SESSION",
                    "response": "There is no paused reading session to continue.",
                }

            if session.status == ReadingStatus.COMPLETED:
                art = self.graph.get_artifact(session.artifact_id)
                topic = art.topic if art else "this content"
                return {
                    "status": "noop",
                    "error_code": "ALREADY_COMPLETED",
                    "response": f"You've already finished reading '{topic}'. Say 'read it again' if you want to listen from the start.",
                }

            # Check if artifact still exists
            artifact = self.graph.get_artifact(session.artifact_id)
            if not artifact:
                return {
                    "status": "error",
                    "error_code": "ARTIFACT_NOT_FOUND",
                    "response": "The artifact for this reading session no longer exists.",
                }

            # Check if artifact content changed
            if session.artifact_version and artifact.content_hash != session.artifact_version:
                return {
                    "status": "error",
                    "error_code": "VERSION_MISMATCH",
                    "response": f"The content of '{artifact.topic}' has been updated since you paused. Please ask to read it again to restart with the new version.",
                }

            # Set starting chunk
            next_chunk_idx = session.last_completed_chunk_idx + 1
            if next_chunk_idx >= session.total_chunks:
                session.status = ReadingStatus.COMPLETED
                session.completed_at = time.time()
                self._persist_session(session)
                return {
                    "status": "noop",
                    "error_code": "ALREADY_COMPLETED",
                    "response": f"All sections of '{artifact.topic}' have already been read.",
                }

            session.current_chunk_idx = next_chunk_idx
            session.status = ReadingStatus.QUEUED
            session.updated_at = time.time()
            self._active_sessions[user_id] = session
            self._persist_session(session)

            stop_event = threading.Event()
            self._stop_events[session.session_id] = stop_event

            if async_playback:
                worker = threading.Thread(
                    target=self._run_reading_worker,
                    args=(session, stop_event),
                    daemon=True,
                    name=f"ReaderWorker-{session.session_id}"
                )
                self._worker_threads[session.session_id] = worker
                worker.start()
            else:
                self._run_reading_worker(session, stop_event)

            curr_idx = min(session.current_chunk_idx, len(session.chunks) - 1) if session.chunks else 0
            chunk_text = session.chunks[curr_idx].text if session.chunks and curr_idx >= 0 else ""
            return {
                "status": "success",
                "session_id": session.session_id,
                "artifact_id": session.artifact_id,
                "topic": artifact.topic,
                "resumed_at_chunk": session.current_chunk_idx + 1,
                "total_chunks": session.total_chunks,
                "response": f"Continuing '{artifact.topic}': {chunk_text}",
                "chunk_text": chunk_text,
            }

    def stop_reading(self, user_id: int = 1) -> Dict[str, Any]:
        """
        Immediately stop/pause TTS reading and persist the current position.
        Does NOT lose the session, does NOT cancel gathering, does NOT delete artifact.
        """
        with self._lock:
            session = self._active_sessions.get(user_id) or self.load_latest_reading_session(user_id)
            if not session or session.status not in (ReadingStatus.READING, ReadingStatus.QUEUED):
                # Check if there is already a paused session
                paused_sess = self.load_latest_paused_session(user_id)
                if paused_sess:
                    art = self.graph.get_artifact(paused_sess.artifact_id)
                    t_name = art.topic if art else "content"
                    return {
                        "status": "noop",
                        "response": f"Reading is already paused for '{t_name}'.",
                        "session_id": paused_sess.session_id,
                    }
                return {
                    "status": "noop",
                    "response": "Nothing is currently being read.",
                }

            # 1. Trigger session stop event
            stop_ev = self._stop_events.get(session.session_id)
            if stop_ev:
                stop_ev.set()

            # 2. Interrupt TTS engine hardware buffer immediately
            try:
                from extensions.system.tts_coordinator import TTSCoordinator
                # Access singleton if available
                from legacy.tts import stop_speaking
                stop_speaking(interrupted=True)
            except Exception as e:
                logger.warning(f"[ARTIFACT_READER] TTS interrupt notice: {e}")

            session.status = ReadingStatus.STOPPED
            session.stopped_at = time.time()
            session.updated_at = time.time()

            # The current chunk index remains where the user stopped.
            # Next resumption will start either at current_chunk_idx if it didn't complete,
            # or last_completed_chunk_idx + 1.
            self._persist_session(session)

            art = self.graph.get_artifact(session.artifact_id)
            topic_str = art.topic if art else "content"

            return {
                "status": "success",
                "session_id": session.session_id,
                "artifact_id": session.artifact_id,
                "topic": topic_str,
                "stopped_at_chunk": session.current_chunk_idx + 1,
                "last_completed_chunk": session.last_completed_chunk_idx + 1,
                "total_chunks": session.total_chunks,
                "response": f"Stopped reading '{topic_str}'. Say 'continue' whenever you want to resume.",
            }

    # ------------------------------------------------------------------------
    # Reading Worker Loop & Chunk Advancement
    # ------------------------------------------------------------------------

    def _run_reading_worker(self, session: ReadingSession, stop_event: threading.Event) -> None:
        """
        Background worker that feeds chunks sequentially to TTS.
        CRITICAL INVARIANT: The cursor is advanced in PostgreSQL ONLY AFTER
        the chunk has been fully synthesized and spoken.
        """
        logger.info(f"[ARTIFACT_READER] Worker started for session {session.session_id}")
        session.status = ReadingStatus.READING
        self._persist_session(session)

        try:
            from extensions.system.tts_coordinator import TTSCoordinator, TTSPriority
            from legacy.tts import speak, wait_until_spoken
        except Exception:
            speak = None
            wait_until_spoken = None

        idx = session.current_chunk_idx
        while idx < session.total_chunks:
            if stop_event.is_set():
                logger.info(f"[ARTIFACT_READER] Stop signaled at chunk {idx}")
                session.status = ReadingStatus.STOPPED
                session.stopped_at = time.time()
                self._persist_session(session)
                return

            chunk = session.chunks[idx]
            session.current_chunk_idx = idx
            logger.debug(f"[ARTIFACT_READER] Speaking chunk {idx + 1}/{session.total_chunks}: {chunk.text[:40]}...")

            if speak is not None:
                # Deliver chunk to TTS
                try:
                    speak(chunk.text, block=True, user_id=session.user_id)
                except Exception as tts_err:
                    logger.error(f"[ARTIFACT_READER] TTS error on chunk {idx}: {tts_err}")
                    if stop_event.is_set():
                        session.status = ReadingStatus.STOPPED
                        session.stopped_at = time.time()
                        self._persist_session(session)
                        return
                    session.error = str(tts_err)
                    session.status = ReadingStatus.FAILED
                    self._persist_session(session)
                    return

            # Check if interrupted during speech
            if stop_event.is_set():
                logger.info(f"[ARTIFACT_READER] Interrupted during chunk {idx} playback.")
                session.status = ReadingStatus.STOPPED
                session.stopped_at = time.time()
                self._persist_session(session)
                return

            # Chunk successfully completed! Advance confirmed cursor
            session.last_completed_chunk_idx = idx
            session.char_offset += chunk.char_length
            session.word_offset += chunk.word_count
            session.updated_at = time.time()
            self._persist_session(session)

            idx += 1

        # Completed all chunks
        session.status = ReadingStatus.COMPLETED
        session.completed_at = time.time()
        session.updated_at = time.time()
        self._persist_session(session)
        logger.info(f"[ARTIFACT_READER] Session {session.session_id} completed successfully.")

    # ------------------------------------------------------------------------
    # PostgreSQL Persistence
    # ------------------------------------------------------------------------

    def _persist_session(self, session: ReadingSession) -> None:
        """Persist reading session and cursor state to PostgreSQL.

        Pre-flight: ensures the parent content_artifact row exists before
        inserting the session.  store_artifact() silently swallows DB errors,
        so the artifact may be in-memory but not yet in PostgreSQL.  If that
        happens and we attempt to insert the session, PostgreSQL raises an FK
        violation.  We prevent this by upserting the artifact first.
        """
        try:
            from core.db_pool import get_db_pool
            import json
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    # ── Pre-flight: guarantee the artifact row exists ──────────
                    cur.execute(
                        "SELECT 1 FROM content_artifacts WHERE artifact_id = %s LIMIT 1;",
                        (session.artifact_id,)
                    )
                    if not cur.fetchone():
                        # Artifact is missing from DB — attempt to upsert it now
                        # from the in-memory graph before the session insert.
                        art = self.graph.get_artifact(session.artifact_id)
                        if art:
                            try:
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
                                    ON CONFLICT (artifact_id) DO NOTHING;
                                """, (
                                    art.artifact_id, art.user_id, art.topic, art.subtopic,
                                    art.content, art.content_type, art.programming_language,
                                    art.original_user_request, art.task_id, art.parent_id,
                                    art.root_id, json.dumps(art.transformation_history),
                                    json.dumps(art.source_info), art.content_hash,
                                    art.status, json.dumps(art.metadata), art.created_at,
                                ))
                                logger.debug(
                                    "[ARTIFACT_READER] Pre-flight: upserted missing artifact "
                                    "%s into content_artifacts before session persist.",
                                    session.artifact_id,
                                )
                            except Exception as art_exc:
                                # If we still can't write the artifact, skip session persist
                                # to avoid an FK violation — session stays in-memory only.
                                logger.warning(
                                    "[ARTIFACT_READER] Cannot persist session %s: artifact "
                                    "%s could not be written to DB (%s). Session retained "
                                    "in memory only.",
                                    session.session_id, session.artifact_id, art_exc,
                                )
                                return
                        else:
                            # Artifact not found anywhere — cannot safely persist session.
                            logger.warning(
                                "[ARTIFACT_READER] Cannot persist session %s: artifact "
                                "%s is not in memory or DB. Session retained in memory only.",
                                session.session_id, session.artifact_id,
                            )
                            return

                    # ── Main session upsert ───────────────────────────────────
                    chunk_json = json.dumps([c.to_dict() for c in session.chunks])
                    meta_json = json.dumps(session.metadata)
                    cur.execute("""
                        INSERT INTO artifact_reading_sessions (
                            session_id, user_id, artifact_id, status,
                            current_chunk_idx, total_chunks, last_completed_chunk_idx,
                            char_offset, word_offset, chunk_data, artifact_version,
                            error, updated_at, stopped_at, completed_at, metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s)
                        ON CONFLICT (session_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            current_chunk_idx = EXCLUDED.current_chunk_idx,
                            total_chunks = EXCLUDED.total_chunks,
                            last_completed_chunk_idx = EXCLUDED.last_completed_chunk_idx,
                            char_offset = EXCLUDED.char_offset,
                            word_offset = EXCLUDED.word_offset,
                            chunk_data = EXCLUDED.chunk_data,
                            artifact_version = EXCLUDED.artifact_version,
                            error = EXCLUDED.error,
                            updated_at = CURRENT_TIMESTAMP,
                            stopped_at = EXCLUDED.stopped_at,
                            completed_at = EXCLUDED.completed_at,
                            metadata = EXCLUDED.metadata;
                    """, (
                        session.session_id,
                        session.user_id,
                        session.artifact_id,
                        session.status.value,
                        session.current_chunk_idx,
                        session.total_chunks,
                        session.last_completed_chunk_idx,
                        session.char_offset,
                        session.word_offset,
                        chunk_json,
                        session.artifact_version,
                        session.error,
                        time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(session.stopped_at)) if session.stopped_at else None,
                        time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(session.completed_at)) if session.completed_at else None,
                        meta_json,
                    ))
        except Exception as e:
            logger.warning(f"[ARTIFACT_READER] Persistence notice: {e}")


    def load_latest_paused_session(self, user_id: int) -> Optional[ReadingSession]:
        """Retrieve most recent paused/stopped reading session from DB."""
        try:
            from core.db_pool import get_db_pool
            import json
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        SELECT session_id, user_id, artifact_id, status, current_chunk_idx,
                               total_chunks, last_completed_chunk_idx, char_offset, word_offset,
                               chunk_data, artifact_version, error, metadata
                        FROM artifact_reading_sessions
                        WHERE user_id = %s AND status IN ('PAUSED', 'STOPPED', 'QUEUED')
                        ORDER BY updated_at DESC
                        LIMIT 1;
                    """, (user_id,))
                    row = cur.fetchone()
                    if row:
                        return self._row_to_session(row)
        except Exception as e:
            logger.warning(f"[ARTIFACT_READER] DB load notice: {e}")
        return None

    def load_latest_reading_session(self, user_id: int) -> Optional[ReadingSession]:
        """Retrieve active reading session from DB."""
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        SELECT session_id, user_id, artifact_id, status, current_chunk_idx,
                               total_chunks, last_completed_chunk_idx, char_offset, word_offset,
                               chunk_data, artifact_version, error, metadata
                        FROM artifact_reading_sessions
                        WHERE user_id = %s AND status = 'READING'
                        ORDER BY updated_at DESC
                        LIMIT 1;
                    """, (user_id,))
                    row = cur.fetchone()
                    if row:
                        return self._row_to_session(row)
        except Exception as e:
            logger.warning(f"[ARTIFACT_READER] DB load active notice: {e}")
        return None

    def _find_session_for_artifact(self, artifact_id: str, user_id: int) -> Optional[ReadingSession]:
        """Find an existing reading session for this specific artifact."""
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        SELECT session_id, user_id, artifact_id, status, current_chunk_idx,
                               total_chunks, last_completed_chunk_idx, char_offset, word_offset,
                               chunk_data, artifact_version, error, metadata
                        FROM artifact_reading_sessions
                        WHERE user_id = %s AND artifact_id = %s
                        ORDER BY updated_at DESC
                        LIMIT 1;
                    """, (user_id, artifact_id))
                    row = cur.fetchone()
                    if row:
                        return self._row_to_session(row)
        except Exception as e:
            logger.warning(f"[ARTIFACT_READER] DB find notice: {e}")
        return None

    def _row_to_session(self, row: Tuple[Any, ...]) -> ReadingSession:
        import json
        sess_id, u_id, a_id, st, cur_idx, tot_chk, last_c_idx, c_off, w_off, raw_chunks, a_ver, err, raw_meta = row
        chunks = []
        if isinstance(raw_chunks, list):
            chunks = [ReadingChunk.from_dict(c) for c in raw_chunks]
        elif isinstance(raw_chunks, str):
            try:
                chunks = [ReadingChunk.from_dict(c) for c in json.loads(raw_chunks)]
            except Exception:
                pass

        meta = raw_meta if isinstance(raw_meta, dict) else {}
        if isinstance(raw_meta, str):
            try:
                meta = json.loads(raw_meta)
            except Exception:
                meta = {}

        return ReadingSession(
            session_id=sess_id,
            user_id=u_id,
            artifact_id=a_id,
            status=ReadingStatus(st),
            current_chunk_idx=cur_idx,
            total_chunks=tot_chk,
            last_completed_chunk_idx=last_c_idx,
            char_offset=c_off,
            word_offset=w_off,
            chunks=chunks,
            artifact_version=a_ver or "",
            error=err,
            metadata=meta
        )

# Singleton instance
_reading_controller: Optional[ArtifactReadingController] = None

def get_artifact_reading_controller() -> ArtifactReadingController:
    global _reading_controller
    if _reading_controller is None:
        _reading_controller = ArtifactReadingController()
    return _reading_controller
