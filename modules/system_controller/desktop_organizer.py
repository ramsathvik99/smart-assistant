"""
Desktop & Downloads Organizer for Nova Smart Assistant.
Safely scans and organizes cluttered loose files into category folders.
Includes dry-run previews and protects system shortcuts/folders.
"""

import os
import shutil
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# File type categorizations
CATEGORIES = {
    "Documents": {".pdf", ".docx", ".doc", ".txt", ".rtf", ".odt", ".pptx", ".ppt", ".xlsx", ".xls", ".csv"},
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".tiff", ".psd"},
    "Media": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
    "Installers": {".exe", ".msi", ".iso"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".java", ".cpp", ".c", ".h", ".json", ".sql", ".sh", ".bat"}
}

# Never move these files from Desktop
PROTECTED_EXTENSIONS = {".lnk", ".url", ".ini"}
PROTECTED_FILENAMES = {"desktop.ini", "thumbs.db"}


def get_target_directory(location: str = "desktop") -> str:
    """Resolve directory path for desktop or downloads."""
    home = os.path.expanduser("~")
    if location.lower() == "downloads":
        path = os.path.join(home, "Downloads")
    else:
        path = os.path.join(home, "Desktop")
    return path if os.path.exists(path) else home


def scan_unorganized_files(target_dir: str) -> List[Dict[str, Any]]:
    """
    Scan target directory for loose files that can be organized.
    """
    candidates = []
    try:
        with os.scandir(target_dir) as entries:
            for entry in entries:
                if entry.is_file():
                    name = entry.name
                    ext = os.path.splitext(name)[1].lower()
                    
                    if ext in PROTECTED_EXTENSIONS or name.lower() in PROTECTED_FILENAMES or name.startswith('.'):
                        continue
                    
                    # Find category
                    matched_category = "Other"
                    for cat, exts in CATEGORIES.items():
                        if ext in exts:
                            matched_category = cat
                            break
                            
                    candidates.append({
                        "name": name,
                        "path": entry.path,
                        "category": matched_category,
                        "size": entry.stat().st_size,
                        "extension": ext
                    })
    except Exception as e:
        logger.error(f"[ORGANIZER] Scan error: {e}")
    return candidates


def organize_directory(
    location: str = "desktop",
    preview_only: bool = False
) -> Dict[str, Any]:
    """
    Organize loose files into categorized subfolders.
    
    Args:
        location: "desktop" or "downloads"
        preview_only: If True, returns planned actions without moving files.
    """
    target_dir = get_target_directory(location)
    files = scan_unorganized_files(target_dir)
    
    if not files:
        return {
            "success": True,
            "location": location,
            "files_count": 0,
            "preview": preview_only,
            "message": f"Your {location.capitalize()} is already clean! No loose files found to organize."
        }
        
    category_summary = {}
    for f in files:
        cat = f["category"]
        category_summary[cat] = category_summary.get(cat, 0) + 1
        
    summary_str = ", ".join([f"{count} {cat}" for cat, count in category_summary.items()])
    
    if preview_only:
        return {
            "success": True,
            "location": location,
            "files_count": len(files),
            "preview": True,
            "categories": category_summary,
            "message": f"Found {len(files)} files on your {location.capitalize()} ({summary_str}). Say 'confirm organize' to move them into organized folders."
        }
        
    # Execute file organization
    moved_count = 0
    moved_pairs: List[tuple] = []
    errors = []
    
    for f in files:
        cat = f["category"]
        cat_dir = os.path.join(target_dir, cat)
        os.makedirs(cat_dir, exist_ok=True)
        
        dest_path = os.path.join(cat_dir, f["name"])
        # Handle filename collisions
        if os.path.exists(dest_path):
            base, ext = os.path.splitext(f["name"])
            dest_path = os.path.join(cat_dir, f"{base}_{int(datetime.now().timestamp())}{ext}")
            
        try:
            shutil.move(f["path"], dest_path)
            moved_pairs.append((f["path"], dest_path))
            moved_count += 1
        except Exception as e:
            errors.append(f"Failed to move {f['name']}: {e}")
            logger.warning(f"[ORGANIZER] Error moving {f['name']}: {e}")
            
    # Register Undo rollback closure if files were moved
    if moved_pairs:
        try:
            from skills.undo.undo_manager import get_undo_manager
            uid = user_id
            if uid is None:
                from instance.config import settings
                uid = getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user() or 1

            def _rollback():
                restored = 0
                for orig_p, dest_p in reversed(moved_pairs):
                    if os.path.exists(dest_p) and not os.path.exists(orig_p):
                        try:
                            shutil.move(dest_p, orig_p)
                            restored += 1
                        except Exception:
                            pass
                return f"Restored {restored} files back to {location}"

            get_undo_manager().push_undo(
                user_id=int(uid),
                label=f"Organize {location} ({len(moved_pairs)} files)",
                undo_fn=_rollback
            )
        except Exception as undo_err:
            logger.warning(f"Failed to register undo for organize_directory: {undo_err}")

    res_msg = f"Successfully organized {moved_count} files on your {location.capitalize()} into: {summary_str}."
    if errors:
        res_msg += f" Note: {len(errors)} files could not be moved."
        
    return {
        "success": True,
        "location": location,
        "moved_count": moved_count,
        "categories": category_summary,
        "errors": errors,
        "message": res_msg
    }
