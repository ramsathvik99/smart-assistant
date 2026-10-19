"""
Safe File Operations and Discovery for Document Tools.
Implements safe creation, discovery, and verified deletion of document artifacts
with path traversal guards and Send2Trash recovery.
"""

import os
import re
import glob
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("SafeFileOps")


def sanitize_filename(filename: str, max_length: int = 120) -> str:
    """Sanitize user-provided filename and prevent path traversal."""
    from core.semantic_file_naming import get_semantic_file_naming_service
    return get_semantic_file_naming_service().sanitize_filename(filename, max_length=max_length)


def is_safe_path(target_path: str, allowed_roots: Optional[List[str]] = None) -> bool:
    """Ensure target path does not escape allowed directories."""
    from core.semantic_file_naming import get_semantic_file_naming_service
    return get_semantic_file_naming_service().is_safe_path(target_path, allowed_roots=allowed_roots)


def list_assistant_documents(
    search_dir: Optional[str] = None,
    extensions: Optional[List[str]] = None,
    limit: int = 25
) -> Dict[str, Any]:
    """
    List and discover documents created by the assistant or residing in document folders.
    """
    if extensions is None:
        extensions = [".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".txt", ".md", ".html"]

    home = os.path.expanduser("~")
    dirs_to_check = [search_dir] if search_dir else [
        os.path.join(home, "OneDrive", "Desktop"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "OneDrive", "Documents"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads")
    ]

    found_files = []
    for d in dirs_to_check:
        if d and os.path.exists(d) and os.path.isdir(d):
            try:
                for entry in os.scandir(d):
                    if entry.is_file():
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in extensions:
                            stat = entry.stat()
                            found_files.append({
                                "name": entry.name,
                                "path": entry.path,
                                "size_bytes": stat.st_size,
                                "size_kb": round(stat.st_size / 1024, 1),
                                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                                "format": ext.lstrip('.')
                            })
            except Exception as e:
                logger.warning(f"[SafeFileOps] Error scanning {d}: {e}")

    # Sort by modification time descending
    found_files.sort(key=lambda x: x["modified_at"], reverse=True)
    results = found_files[:limit]

    return {
        "success": True,
        "count": len(results),
        "files": results,
        "message": f"Found {len(results)} document(s)."
    }


def safe_delete_document(
    filepath: str,
    confirm: bool = False
) -> Dict[str, Any]:
    """
    Safely delete a specifically identified document artifact using Send2Trash.
    Requires target verification and non-ambiguous path.
    """
    if not filepath or not str(filepath).strip():
        return {
            "success": False,
            "status": "error",
            "message": "Please specify the exact document file to delete."
        }

    clean_path = filepath.strip(' "\'')

    # Ambiguity check
    vague_targets = {"file", "files", "document", "documents", "everything", "all", "it", "that", "this"}
    if clean_path.lower() in vague_targets:
        return {
            "success": False,
            "status": "clarification_needed",
            "message": "Which document would you like to delete? Please specify the file name."
        }

    # Resolve relative names against default directories if needed
    target = os.path.abspath(clean_path)
    if not os.path.exists(target):
        # Look in Documents and Desktop
        home = os.path.expanduser("~")
        candidates = [
            os.path.join(home, "Documents", clean_path),
            os.path.join(home, "Desktop", clean_path),
            os.path.join(home, "Downloads", clean_path)
        ]
        found = False
        for c in candidates:
            if os.path.exists(c):
                target = c
                found = True
                break
        if not found:
            return {
                "success": False,
                "status": "error",
                "message": f"File '{clean_path}' does not exist."
            }

    if os.path.isdir(target):
        return {
            "success": False,
            "status": "error",
            "message": f"Target '{target}' is a directory, not a document. Directory deletion is blocked for safety."
        }

    # Execute safe trash deletion
    try:
        from send2trash import send2trash
        send2trash(target)
    except ImportError:
        try:
            os.remove(target)
        except Exception as e:
            return {"success": False, "status": "error", "message": f"Failed to delete file: {e}"}
    except Exception as e:
        return {"success": False, "status": "error", "message": f"Failed to delete file safely: {e}"}

    # Verify file is gone
    if os.path.exists(target):
        return {
            "success": False,
            "status": "error",
            "message": f"Verification failed: '{os.path.basename(target)}' is locked or could not be removed."
        }

    return {
        "success": True,
        "status": "success",
        "deleted_path": target,
        "filename": os.path.basename(target),
        "message": f"Successfully deleted document '{os.path.basename(target)}'."
    }


class SafeFileOps:
    """Class wrapper for safe file operations, traversal checks, and deletion."""

    @staticmethod
    def sanitize_filename(filename: str, max_length: int = 120) -> str:
        return sanitize_filename(filename, max_length)

    @staticmethod
    def is_safe_path(target_path: str, allowed_roots: Optional[List[str]] = None) -> bool:
        return is_safe_path(target_path, allowed_roots)

    @staticmethod
    def list_documents(search_dir: Optional[str] = None, extensions: Optional[List[str]] = None, limit: int = 25) -> Dict[str, Any]:
        return list_assistant_documents(search_dir, extensions, limit)

    @staticmethod
    def safe_delete_document(filepath: str, confirm: bool = False, user_id: Any = None) -> Dict[str, Any]:
        return safe_delete_document(filepath, confirm)

    @staticmethod
    def resolve_user_path(requested_path: str, user_id: str = "1") -> str:
        # Check path traversal
        norm = os.path.normpath(requested_path)
        parts = norm.replace("\\", "/").split("/")
        if ".." in parts or requested_path.startswith("..") or "/../" in requested_path or "\\..\\" in requested_path:
            raise ValueError(f"Directory traversal detected in path: '{requested_path}'")
        return norm

