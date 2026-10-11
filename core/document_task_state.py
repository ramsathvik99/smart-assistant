"""
Document Task State Management for NOVA
Tracks persistent document-generation task state across DOCX, PPTX, PDF, and XLSX generation jobs.
Enables deterministic status querying ("is the PPT done?", "did you create it?", "open the document")
without relying on conversational memory or external LLM roundtrips.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class DocumentTask:
    task_id: str
    artifact_type: str  # "PPTX", "DOCX", "PDF", "XLSX"
    request: str
    status: str  # "QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    artifact_path: Optional[str] = None
    title: Optional[str] = None
    topic: Optional[str] = None
    slide_count: Optional[int] = None
    error: Optional[str] = None
    progress: float = 0.0
    user_id: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DocumentTaskManager:
    """Singleton task manager for tracking document generation tasks."""

    _instance: Optional[DocumentTaskManager] = None
    _tasks: Dict[str, DocumentTask] = {}
    _user_task_order: Dict[str, List[str]] = {}

    def __new__(cls) -> DocumentTaskManager:
        if cls._instance is None:
            cls._instance = super(DocumentTaskManager, cls).__new__(cls)
            cls._instance._tasks = {}
            cls._instance._user_task_order = {}
        return cls._instance

    @classmethod
    def get_instance(cls) -> DocumentTaskManager:
        return cls()

    def create_task(
        self,
        artifact_type: str,
        request: str,
        user_id: str = "default",
        title: Optional[str] = None,
        topic: Optional[str] = None,
        status: str = "RUNNING",
    ) -> DocumentTask:
        norm_type = artifact_type.upper()
        task_id = f"doc_{uuid.uuid4().hex[:8]}"
        task = DocumentTask(
            task_id=task_id,
            artifact_type=norm_type,
            request=request,
            status=status,
            user_id=str(user_id),
            title=title,
            topic=topic,
            progress=0.1 if status == "RUNNING" else 0.0,
        )
        self._tasks[task_id] = task
        uid_key = str(user_id)
        if uid_key not in self._user_task_order:
            self._user_task_order[uid_key] = []
        self._user_task_order[uid_key].append(task_id)
        return task

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        artifact_path: Optional[str] = None,
        error: Optional[str] = None,
        slide_count: Optional[int] = None,
    ) -> Optional[DocumentTask]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        if status:
            task.status = status
        if progress is not None:
            task.progress = progress
        if artifact_path:
            task.artifact_path = artifact_path
        if error:
            task.error = error
        if slide_count is not None:
            task.slide_count = slide_count
        task.updated_at = time.time()
        return task

    def complete_task(
        self,
        task_id: str,
        artifact_path: str,
        title: Optional[str] = None,
        slide_count: Optional[int] = None,
    ) -> Optional[DocumentTask]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        task.status = "COMPLETED"
        task.progress = 1.0
        task.artifact_path = artifact_path
        if title:
            task.title = title
        if slide_count is not None:
            task.slide_count = slide_count
        task.updated_at = time.time()
        return task

    def fail_task(self, task_id: str, error: str) -> Optional[DocumentTask]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        task.status = "FAILED"
        task.error = error
        task.updated_at = time.time()
        return task

    def get_task(self, task_id: str) -> Optional[DocumentTask]:
        return self._tasks.get(task_id)

    def get_latest_task(
        self,
        user_id: str = "default",
        artifact_type: Optional[str] = None,
    ) -> Optional[DocumentTask]:
        uid_key = str(user_id)
        task_ids = self._user_task_order.get(uid_key, [])
        if not task_ids and uid_key != "default":
            task_ids = self._user_task_order.get("default", [])
        if not task_ids:
            # Fallback across all tasks if user-specific list empty
            task_ids = list(self._tasks.keys())
        for tid in reversed(task_ids):
            t = self._tasks.get(tid)
            if not t:
                continue
            if artifact_type:
                target_type = artifact_type.upper()
                if target_type in ("PPT", "PPTX", "POWERPOINT", "PRESENTATION"):
                    if t.artifact_type in ("PPT", "PPTX", "PRESENTATION"):
                        return t
                elif target_type in ("DOC", "DOCX", "WORD"):
                    if t.artifact_type in ("DOC", "DOCX", "REPORT"):
                        return t
                elif target_type in ("PDF",):
                    if t.artifact_type == "PDF":
                        return t
                elif target_type in ("XLS", "XLSX", "EXCEL", "SPREADSHEET"):
                    if t.artifact_type in ("XLS", "XLSX", "SPREADSHEET"):
                        return t
                elif t.artifact_type == target_type:
                    return t
            else:
                return t
        return None


def get_document_task_manager() -> DocumentTaskManager:
    return DocumentTaskManager.get_instance()
