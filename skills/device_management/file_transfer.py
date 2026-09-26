"""
Device File Transfer Service
Provides safe, authenticated file upload, download, and listing with strict user isolation,
filename sanitization, size limits, and duplicate-collision avoidance.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_UPLOAD_MB_DEFAULT = 500


def _safe_filename(raw: str) -> str:
    """Sanitize filename to prevent directory traversal and invalid OS characters."""
    name = Path(raw).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")
    return name or "upload_file"


def get_user_uploads_dir(user_id: int, base_dir: Optional[Path] = None) -> Path:
    """Get or create the isolated uploads directory for a specific user."""
    if base_dir is None:
        project_root = Path(__file__).resolve().parent.parent.parent
        target_dir = project_root / "data" / "uploads" / f"user_{int(user_id)}"
    else:
        target_dir = Path(base_dir) / f"user_{int(user_id)}"
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def save_user_uploaded_file(
    file_bytes: bytes,
    raw_filename: str,
    user_id: int,
    max_mb: int = MAX_UPLOAD_MB_DEFAULT,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Save an uploaded file with filename sanitization, collision handling, and user isolation.
    """
    if not user_id:
        return {"success": False, "error": "Unauthorized: Missing user_id", "status": "unauthorized"}

    max_bytes = max_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        return {
            "success": False,
            "error": f"File exceeds maximum allowed size of {max_mb} MB",
            "status": "size_exceeded",
        }

    uploads_dir = get_user_uploads_dir(user_id, base_dir=base_dir)
    safe_name = _safe_filename(raw_filename)
    dest = uploads_dir / safe_name
    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix

    counter = 1
    while dest.exists():
        dest = uploads_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    try:
        dest.write_bytes(file_bytes)
        logger.info(f"[FILE_TRANSFER] Saved file {dest.name} ({len(file_bytes)} bytes) for user {user_id}")
        return {
            "success": True,
            "filename": dest.name,
            "file_path": str(dest.resolve()),
            "size_bytes": len(file_bytes),
            "status": "saved",
        }
    except Exception as e:
        logger.error(f"[FILE_TRANSFER] Failed to save file for user {user_id}: {e}")
        return {"success": False, "error": str(e), "status": "error"}


def get_user_file_path(filename: str, user_id: int, base_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Safely locate a file in the user's isolated directory.
    Rejects any path escaping the user folder.
    """
    if not user_id or not filename:
        return None
    safe_name = _safe_filename(filename)
    uploads_dir = get_user_uploads_dir(user_id, base_dir=base_dir)
    target = (uploads_dir / safe_name).resolve()

    if not str(target).startswith(str(uploads_dir.resolve())):
        return None
    if target.is_file() and target.exists():
        return target
    return None


def list_user_files(user_id: int, base_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """List all stored files in the user's isolated directory."""
    if not user_id:
        return []
    uploads_dir = get_user_uploads_dir(user_id, base_dir=base_dir)
    results = []
    try:
        for p in sorted(uploads_dir.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True):
            if p.is_file():
                results.append({
                    "name": p.name,
                    "size_bytes": p.stat().st_size,
                    "modified_timestamp": p.stat().st_mtime,
                    "path": str(p.resolve()),
                })
    except Exception as e:
        logger.warning(f"[FILE_TRANSFER] Error listing files for user {user_id}: {e}")
    return results
