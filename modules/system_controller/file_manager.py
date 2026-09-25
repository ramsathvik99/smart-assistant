"""
File Manager for Nova System Controller
Handles file opening, comprehensive file management, searching, statistics,
archive processing, and safe file lifecycle operations.
"""

import os
import re
import shutil
import subprocess
import platform
import logging
import hashlib
import zipfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Try importing send2trash for real OS recycle bin support
try:
    import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False


def get_desktop_path() -> str:
    """Get the user's Desktop path with OneDrive support"""
    onedrive_desktop = os.path.join(
        os.environ.get("USERPROFILE", ""),
        "OneDrive",
        "Desktop"
    )
    if os.path.exists(onedrive_desktop):
        return onedrive_desktop
    return os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")


def get_default_workspace() -> str:
    """Get default safe user workspace directory (Documents, Desktop, or Home)."""
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    if os.path.exists(docs):
        return docs
    return get_desktop_path()


def resolve_directory_name(name_or_path: Optional[str] = None) -> str:
    """Resolve directory names ('Downloads', 'Documents', 'Desktop', etc.) or paths to absolute directory path."""
    if not name_or_path or str(name_or_path).lower() in ("desktop", "the desktop", ""):
        return get_desktop_path()
    
    clean = str(name_or_path).strip(' "\'')
    low = clean.lower()
    user_home = Path.home()
    
    if "download" in low:
        target = user_home / "Downloads"
        if target.exists():
            return str(target)
    elif "document" in low:
        target = user_home / "Documents"
        if target.exists():
            return str(target)
    elif "picture" in low or "photo" in low:
        target = user_home / "Pictures"
        if target.exists():
            return str(target)
    elif "music" in low:
        target = user_home / "Music"
        if target.exists():
            return str(target)
    elif "video" in low:
        target = user_home / "Videos"
        if target.exists():
            return str(target)

    # Check if direct directory path exists
    p = Path(clean)
    if p.exists() and p.is_dir():
        return str(p.resolve())
        
    candidate_home = user_home / clean
    if candidate_home.exists() and candidate_home.is_dir():
        return str(candidate_home.resolve())
        
    candidate_desk = Path(get_desktop_path()) / clean
    if candidate_desk.exists() and candidate_desk.is_dir():
        return str(candidate_desk.resolve())

    return get_desktop_path()



def is_safe_file_path(file_path: str) -> bool:
    """Check if file path is within allowed user directories and free from path traversal."""
    try:
        resolved = Path(file_path).resolve()
        # Disallow access to Windows system directories
        sys_root = Path(os.environ.get("SystemRoot", "C:\\Windows")).resolve()
        prog_files = Path(os.environ.get("ProgramFiles", "C:\\Program Files")).resolve()
        prog_files_x86 = Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")).resolve()

        if resolved.is_relative_to(sys_root) or resolved.is_relative_to(prog_files) or resolved.is_relative_to(prog_files_x86):
            return False

        # Allow user home directory and any user-owned folders
        user_home = Path.home().resolve()
        return resolved.is_relative_to(user_home) or str(resolved).startswith(str(Path.cwd()))
    except (ValueError, OSError):
        return False


def find_file_in_desktop(filename: str) -> Optional[str]:
    """Search for a file in the Desktop directory and subdirectories."""
    desktop = get_desktop_path()
    try:
        clean_target = re.sub(r'^(?:my|the|a)\s+', '', filename.strip(), flags=re.IGNORECASE).strip()
        tokens = [t.lower() for t in re.split(r'[\s_\-]+', clean_target) if t]

        # 1. Exact match pass
        for root, dirs, files in os.walk(desktop):
            dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS and not d.startswith('.')]
            for f in files:
                if f.lower() == filename.lower() or f.lower() == clean_target.lower():
                    return os.path.join(root, f)

        # 2. Token match pass
        if tokens:
            for root, dirs, files in os.walk(desktop):
                dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS and not d.startswith('.')]
                for f in files:
                    f_low = f.lower()
                    if all(tok in f_low for tok in tokens):
                        return os.path.join(root, f)

        # 3. Substring match pass
        for root, dirs, files in os.walk(desktop):
            dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS and not d.startswith('.')]
            for f in files:
                if clean_target.lower() in f.lower():
                    return os.path.join(root, f)
    except Exception as e:
        logger.error(f"Error searching for file '{filename}': {e}")
    return None


def open_file(file_path: str) -> str:
    """
    Open a file with the default system application.
    """
    try:
        if not os.path.exists(file_path):
            filename = os.path.basename(file_path)
            found_path = find_file_in_desktop(filename)
            if found_path:
                file_path = found_path
            else:
                return f"File '{filename}' not found."

        if not is_safe_file_path(file_path):
            logger.warning(f"Unsafe file access attempted: {file_path}")
            return "Error: File path is outside allowed user directories."

        sys_name = platform.system()
        if sys_name == "Windows":
            os.startfile(file_path)
        elif sys_name == "Darwin":
            subprocess.call(["open", file_path])
        else:
            subprocess.call(["xdg-open", file_path])

        logger.info(f"File opened: {file_path}")
        return f"File '{os.path.basename(file_path)}' opened successfully."
    except Exception as e:
        logger.error(f"Failed to open file '{file_path}': {e}")
        return f"Error opening file: {e}"


def get_file_info(file_path: str) -> Dict[str, Any]:
    """
    Get detailed information and metadata about a file.
    """
    try:
        if not os.path.exists(file_path):
            return {"error": "File not found"}

        if not is_safe_file_path(file_path):
            return {"error": "File path is outside allowed directories"}

        stat = os.stat(file_path)
        size_bytes = stat.st_size
        size_kb = round(size_bytes / 1024, 1)
        size_mb = round(size_bytes / (1024 * 1024), 2)
        mod_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        return {
            "name": os.path.basename(file_path),
            "path": os.path.abspath(file_path),
            "size_bytes": size_bytes,
            "size_kb": size_kb,
            "size_mb": size_mb,
            "modified": mod_time,
            "is_file": os.path.isfile(file_path),
            "is_dir": os.path.isdir(file_path),
            "extension": os.path.splitext(file_path)[1].lower()
        }
    except Exception as e:
        logger.error(f"Failed to get file info for '{file_path}': {e}")
        return {"error": str(e)}


def list_files(directory_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List files in a directory.
    """
    try:
        if directory_path is None:
            directory_path = get_desktop_path()

        if not os.path.exists(directory_path):
            return []

        if not is_safe_file_path(directory_path):
            logger.warning(f"Unsafe directory access attempted: {directory_path}")
            return []

        files = []
        for item in os.listdir(directory_path):
            item_path = os.path.join(directory_path, item)
            if os.path.isfile(item_path):
                files.append(get_file_info(item_path))

        return files
    except Exception as e:
        logger.error(f"Failed to list files in '{directory_path}': {e}")
        return []


IGNORE_DIRS = {'.git', 'node_modules', '__pycache__', 'venv', '.venv', 'appdata', '$recycle.bin', '.idea', '.vscode', '.gemini'}


def search_files(
    pattern: str = "",
    root_dir: Optional[str] = None,
    recursive: bool = True,
    ext: Optional[str] = None,
    min_size_mb: Optional[float] = None,
    max_size_mb: Optional[float] = None,
    modified_days: Optional[int] = None,
    max_results: int = 50,
    directory: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search for files with multi-criteria filtering.
    """
    try:
        search_root = resolve_directory_name(root_dir or directory)
        if not os.path.exists(search_root):
            return {"success": False, "status": "error", "files": [], "message": f"Directory '{search_root}' does not exist."}

        if not is_safe_file_path(search_root):
            return {"success": False, "status": "error", "files": [], "message": "Search directory is outside allowed user folders."}

        target_ext = f".{ext.lower().lstrip('.')}" if ext else None
        pattern_lower = pattern.lower() if pattern else ""
        cutoff_date = datetime.now() - timedelta(days=modified_days) if modified_days is not None else None

        results = []
        if recursive:
            search_path_obj = Path(search_root)
            for root, dirs, files in os.walk(search_root):
                dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS and not d.startswith('.')]
                try:
                    if len(Path(root).relative_to(search_path_obj).parts) >= 3:
                        dirs.clear()
                except Exception:
                    pass
                for f in files:
                    if pattern_lower and pattern_lower not in f.lower():
                        continue

                    if target_ext and not f.lower().endswith(target_ext):
                        continue

                    full_path = os.path.join(root, f)
                    try:
                        stat = os.stat(full_path)
                        size_mb = stat.st_size / (1024 * 1024)

                        if min_size_mb is not None and size_mb < min_size_mb:
                            continue
                        if max_size_mb is not None and size_mb > max_size_mb:
                            continue
                        if cutoff_date is not None and datetime.fromtimestamp(stat.st_mtime) < cutoff_date:
                            continue

                        results.append({
                            "name": f,
                            "path": full_path,
                            "size_mb": round(size_mb, 2),
                            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                        })

                        if len(results) >= max_results:
                            break
                    except (PermissionError, OSError):
                        continue
                if len(results) >= max_results:
                    break
        else:
            for f in os.listdir(search_root):
                full_path = os.path.join(search_root, f)
                if not os.path.isfile(full_path):
                    continue
                if pattern_lower and pattern_lower not in f.lower():
                    continue
                if target_ext and not f.lower().endswith(target_ext):
                    continue
                try:
                    stat = os.stat(full_path)
                    size_mb = stat.st_size / (1024 * 1024)
                    if min_size_mb is not None and size_mb < min_size_mb:
                        continue
                    if max_size_mb is not None and size_mb > max_size_mb:
                        continue
                    if cutoff_date is not None and datetime.fromtimestamp(stat.st_mtime) < cutoff_date:
                        continue
                    results.append({
                        "name": f,
                        "path": full_path,
                        "size_mb": round(size_mb, 2),
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    })
                    if len(results) >= max_results:
                        break
                except (PermissionError, OSError):
                    continue

        speech = f"Found {len(results)} file(s) matching '{pattern or '*'}'." if results else f"No files found matching '{pattern or '*'}'."
        return {
            "success": True,
            "status": "success",
            "count": len(results),
            "files": results,
            "message": speech
        }
    except Exception as e:
        logger.error(f"[FILE_MANAGER] Search error: {e}")
        return {"success": False, "status": "error", "files": [], "message": f"Search failed: {e}"}


def get_directory_stats(dir_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Calculate comprehensive directory statistics: total files, size, and extension breakdown.
    """
    try:
        target = resolve_directory_name(dir_path)
        if not os.path.exists(target):
            return {"success": False, "status": "error", "message": f"Directory not found: {target}"}

        total_files = 0
        total_dirs = 0
        total_size = 0
        ext_counts = {}
        ext_sizes = {}

        target_path_obj = Path(target)
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS and not d.startswith('.')]
            try:
                if len(Path(root).relative_to(target_path_obj).parts) >= 2:
                    dirs.clear()
            except Exception:
                pass
            total_dirs += len(dirs)
            for f in files:
                full = os.path.join(root, f)
                try:
                    size = os.path.getsize(full)
                    total_size += size
                    total_files += 1
                    ext = os.path.splitext(f)[1].lower() or "no_ext"
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1
                    ext_sizes[ext] = ext_sizes.get(ext, 0) + size
                except (PermissionError, OSError):
                    continue

        size_mb = round(total_size / (1024 * 1024), 2)
        top_exts = sorted(ext_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_str = ", ".join([f"{count} {ext}" for ext, count in top_exts])

        speech = f"Directory has {total_files} files in {total_dirs} folders, totaling {size_mb} MB ({top_str})."

        return {
            "success": True,
            "status": "success",
            "directory": target,
            "total_files": total_files,
            "total_folders": total_dirs,
            "total_size_mb": size_mb,
            "total_size_kb": round(total_size / 1024, 1),
            "top_extensions": dict(top_exts),
            "message": speech
        }
    except Exception as e:
        logger.error(f"[FILE_MANAGER] Directory stats error: {e}")
        return {"success": False, "status": "error", "message": f"Failed to get directory stats: {e}"}


def get_largest_files(dir_path: Optional[str] = None, n: int = 10) -> Dict[str, Any]:
    """
    Find top N space-consuming files in a directory tree.
    """
    try:
        target = resolve_directory_name(dir_path)
        if not os.path.exists(target):
            return {"success": False, "files": [], "message": f"Directory '{target}' not found."}

        all_files = []
        target_path_obj = Path(target)
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS and not d.startswith('.')]
            try:
                if len(Path(root).relative_to(target_path_obj).parts) >= 2:
                    dirs.clear()
            except Exception:
                pass
            for f in files:
                full = os.path.join(root, f)
                try:
                    size = os.path.getsize(full)
                    all_files.append((f, full, size))
                except (PermissionError, OSError):
                    continue

        all_files.sort(key=lambda x: x[2], reverse=True)
        top_list = [
            {"name": item[0], "path": item[1], "size_mb": round(item[2] / (1024 * 1024), 2)}
            for item in all_files[:n]
        ]

        summary = ", ".join([f"{f['name']} ({f['size_mb']} MB)" for f in top_list[:3]])
        speech = f"Top {len(top_list)} largest files in {os.path.basename(target)}: {summary}."

        return {
            "success": True,
            "count": len(top_list),
            "files": top_list,
            "message": speech
        }
    except Exception as e:
        return {"success": False, "files": [], "message": f"Failed to find largest files: {e}"}


def find_duplicate_files(dir_path: Optional[str] = None, sample_size_kb: int = 64) -> Dict[str, Any]:
    """
    Find potential duplicate files based on identical file sizes and MD5 header hash.
    """
    try:
        target = resolve_directory_name(dir_path)
        if not os.path.exists(target):
            return {"success": False, "duplicates": [], "message": f"Directory '{target}' not found."}

        size_map = {}
        target_path_obj = Path(target)
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS and not d.startswith('.')]
            try:
                if len(Path(root).relative_to(target_path_obj).parts) >= 2:
                    dirs.clear()
            except Exception:
                pass
            for f in files:
                full = os.path.join(root, f)
                try:
                    size = os.path.getsize(full)
                    if size > 0:
                        size_map.setdefault(size, []).append(full)
                except (PermissionError, OSError):
                    continue

        # Check hash of candidate groups
        duplicates = []
        for size, paths in size_map.items():
            if len(paths) < 2:
                continue
            hash_groups = {}
            for p in paths:
                try:
                    with open(p, "rb") as fp:
                        sample = fp.read(sample_size_kb * 1024)
                        h = hashlib.md5(sample).hexdigest()
                        hash_groups.setdefault(h, []).append(p)
                except (PermissionError, OSError):
                    continue

            for h, matches in hash_groups.items():
                if len(matches) > 1:
                    duplicates.append({
                        "size_mb": round(size / (1024 * 1024), 2),
                        "count": len(matches),
                        "files": matches
                    })

        speech = f"Found {len(duplicates)} set(s) of potential duplicate files in {os.path.basename(target)}."
        return {
            "success": True,
            "status": "success",
            "duplicate_groups": len(duplicates),
            "duplicates": duplicates,
            "message": speech
        }
    except Exception as e:
        return {"success": False, "status": "error", "duplicates": [], "message": f"Duplicate search failed: {e}"}


def create_text_file(file_path: str, content: str = "", overwrite: bool = False) -> Dict[str, Any]:
    """
    Create a new text file safely.
    """
    try:
        if not is_safe_file_path(file_path):
            return {"success": False, "status": "error", "message": "Destination path is outside allowed directories."}

        if os.path.exists(file_path) and not overwrite:
            return {"success": False, "status": "error", "message": f"File already exists: '{file_path}'. Set overwrite=True to replace."}

        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {"success": True, "status": "success", "path": file_path, "message": f"Created file '{os.path.basename(file_path)}' successfully."}
    except Exception as e:
        return {"success": False, "status": "error", "message": f"Failed to create file: {e}"}


def _resolve_uid(user_id: Optional[int] = None) -> int:
    if user_id is not None:
        return int(user_id)
    try:
        from instance.config import settings
        return int(getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user() or 1)
    except Exception:
        return 1


def copy_file(src_path: str, dst_path: str, user_id: Optional[int] = None) -> Dict[str, Any]:
    """Copy a file safely and register an undo rollback closure."""
    try:
        if not os.path.exists(src_path):
            return {"success": False, "message": f"Source file does not exist: {src_path}"}
        if not is_safe_file_path(src_path) or not is_safe_file_path(dst_path):
            return {"success": False, "message": "Paths must be within safe user directories."}

        target_dst = dst_path
        if os.path.isdir(dst_path):
            target_dst = os.path.join(dst_path, os.path.basename(src_path))

        os.makedirs(os.path.dirname(os.path.abspath(target_dst)), exist_ok=True)
        shutil.copy2(src_path, target_dst)

        uid = _resolve_uid(user_id)
        try:
            from skills.undo.undo_manager import get_undo_manager
            def _rollback():
                if os.path.exists(target_dst):
                    os.remove(target_dst)
                    return f"Removed copied file '{os.path.basename(target_dst)}'"
                raise RuntimeError("Cannot undo copy: target file not found.")

            get_undo_manager().push_undo(
                user_id=uid,
                label=f"Copy '{os.path.basename(src_path)}' to '{target_dst}'",
                undo_fn=_rollback
            )
        except Exception as undo_err:
            logger.warning(f"Failed to register undo: {undo_err}")

        return {"success": True, "message": f"Copied '{os.path.basename(src_path)}' to '{target_dst}'."}
    except Exception as e:
        return {"success": False, "message": f"Failed to copy file: {e}"}


def move_file(src_path: str, dst_path: str, user_id: Optional[int] = None) -> Dict[str, Any]:
    """Move a file safely and register an undo rollback closure."""
    try:
        if not os.path.exists(src_path):
            return {"success": False, "message": f"Source file does not exist: {src_path}"}
        if not is_safe_file_path(src_path) or not is_safe_file_path(dst_path):
            return {"success": False, "message": "Paths must be within safe user directories."}

        target_dst = dst_path
        if os.path.isdir(dst_path):
            target_dst = os.path.join(dst_path, os.path.basename(src_path))

        os.makedirs(os.path.dirname(os.path.abspath(target_dst)), exist_ok=True)
        shutil.move(src_path, target_dst)

        uid = _resolve_uid(user_id)
        try:
            from skills.undo.undo_manager import get_undo_manager
            def _rollback():
                if os.path.exists(target_dst) and not os.path.exists(src_path):
                    shutil.move(target_dst, src_path)
                    return f"Restored '{os.path.basename(target_dst)}' back to '{src_path}'"
                raise RuntimeError("Cannot undo move: destination file state has changed.")

            get_undo_manager().push_undo(
                user_id=uid,
                label=f"Move '{os.path.basename(src_path)}' to '{target_dst}'",
                undo_fn=_rollback
            )
        except Exception as undo_err:
            logger.warning(f"Failed to register undo: {undo_err}")

        return {"success": True, "message": f"Moved '{os.path.basename(src_path)}' to '{target_dst}'."}
    except Exception as e:
        return {"success": False, "message": f"Failed to move file: {e}"}


def rename_file(file_path: str, new_name: str, user_id: Optional[int] = None) -> Dict[str, Any]:
    """Rename a file safely within its current parent directory and register an undo rollback closure."""
    try:
        actual_path = file_path
        if not os.path.exists(actual_path):
            found = find_file_in_desktop(os.path.basename(file_path))
            if found:
                actual_path = found
            else:
                for std_dir in ["Downloads", "Documents"]:
                    cand = Path.home() / std_dir / os.path.basename(file_path)
                    if cand.exists():
                        actual_path = str(cand)
                        break

        if not os.path.exists(actual_path):
            return {"success": False, "message": f"File not found: {file_path}"}
        if not is_safe_file_path(actual_path):
            return {"success": False, "message": "File is outside allowed directories."}

        parent = os.path.dirname(os.path.abspath(actual_path))
        clean_new = os.path.basename(new_name.strip())
        new_path = os.path.join(parent, clean_new)

        if os.path.exists(new_path):
            return {"success": False, "message": f"A file named '{clean_new}' already exists."}

        orig_basename = os.path.basename(actual_path)
        os.rename(actual_path, new_path)

        uid = _resolve_uid(user_id)
        try:
            from skills.undo.undo_manager import get_undo_manager
            def _rollback():
                if os.path.exists(new_path) and not os.path.exists(actual_path):
                    os.rename(new_path, actual_path)
                    return f"Restored '{clean_new}' back to '{orig_basename}'"
                raise RuntimeError(f"Cannot undo rename: file state at '{new_path}' has changed.")

            get_undo_manager().push_undo(
                user_id=uid,
                label=f"Rename '{orig_basename}' to '{clean_new}'",
                undo_fn=_rollback
            )
        except Exception as undo_err:
            logger.warning(f"Failed to register undo: {undo_err}")

        return {"success": True, "new_path": new_path, "message": f"Renamed '{orig_basename}' to '{clean_new}'."}
    except Exception as e:
        return {"success": False, "message": f"Failed to rename file: {e}"}


def safe_delete_file(file_path: str, use_trash: bool = True) -> Dict[str, Any]:
    """
    Safely delete a file by moving to Windows Recycle Bin / Trash or quarantine folder.
    Never permanently deletes without warning.
    """
    try:
        actual_path = file_path
        if not os.path.exists(actual_path):
            found = find_file_in_desktop(os.path.basename(file_path))
            if found:
                actual_path = found
            else:
                for std_dir in ["Downloads", "Documents"]:
                    cand = Path.home() / std_dir / os.path.basename(file_path)
                    if cand.exists():
                        actual_path = str(cand)
                        break

        if not os.path.exists(actual_path):
            return {"success": False, "status": "error", "message": f"File not found: {file_path}"}
        if not is_safe_file_path(actual_path):
            return {"success": False, "status": "error", "message": "Cannot delete files outside allowed directories."}

        fname = os.path.basename(actual_path)

        if use_trash and HAS_SEND2TRASH:
            send2trash.send2trash(actual_path)
            return {"success": True, "status": "success", "message": f"Moved '{fname}' to Recycle Bin (can be restored)."}
        else:
            # Fallback: Move to local safe quarantine folder
            trash_dir = os.path.join(os.path.expanduser("~"), ".assistant_trash")
            os.makedirs(trash_dir, exist_ok=True)
            ts = int(datetime.now().timestamp())
            quarantine_path = os.path.join(trash_dir, f"{ts}_{fname}")
            shutil.move(actual_path, quarantine_path)
            return {"success": True, "status": "success", "message": f"Moved '{fname}' to safe assistant trash (quarantined)."}
    except Exception as e:
        return {"success": False, "status": "error", "message": f"Failed to delete file: {e}"}


def inspect_zip_archive(zip_path: str) -> Dict[str, Any]:
    """
    List contents, compressed size, and file count of a ZIP archive without extracting.
    """
    try:
        if not os.path.exists(zip_path):
            return {"success": False, "message": f"Archive not found: {zip_path}"}

        with zipfile.ZipFile(zip_path, 'r') as zf:
            infolist = zf.infolist()
            total_uncompressed = sum(info.file_size for info in infolist)
            entries = [
                {
                    "filename": info.filename,
                    "size_bytes": info.file_size,
                    "size_kb": round(info.file_size / 1024, 1),
                    "is_dir": info.is_dir()
                }
                for info in infolist[:30]
            ]

            speech = (
                f"ZIP archive '{os.path.basename(zip_path)}' contains {len(infolist)} items "
                f"totaling {round(total_uncompressed / (1024 * 1024), 2)} MB uncompressed."
            )

            return {
                "success": True,
                "archive": zip_path,
                "total_items": len(infolist),
                "uncompressed_mb": round(total_uncompressed / (1024 * 1024), 2),
                "sample_entries": entries,
                "message": speech
            }
    except Exception as e:
        return {"success": False, "message": f"Failed to inspect ZIP archive: {e}"}


def extract_zip_archive(zip_path: str, extract_to: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract a ZIP archive safely with ZipSlip path traversal prevention.
    """
    try:
        if not os.path.exists(zip_path):
            return {"success": False, "message": f"Archive not found: {zip_path}"}

        out_dir = extract_to or os.path.splitext(zip_path)[0]
        out_path = Path(out_dir).resolve()
        os.makedirs(out_path, exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            # ZipSlip security check
            for member in zf.namelist():
                member_path = (out_path / member).resolve()
                if not member_path.is_relative_to(out_path):
                    return {"success": False, "message": "Security Error: Malicious ZIP path traversal detected."}

            zf.extractall(out_path)

        return {
            "success": True,
            "extracted_to": str(out_path),
            "message": f"Successfully extracted archive to '{os.path.basename(str(out_path))}'."
        }
    except Exception as e:
        return {"success": False, "message": f"Failed to extract ZIP archive: {e}"}


def extract_text_content(file_path: str, max_chars: int = 10000) -> Dict[str, Any]:
    """
    Safely extract plain text from text, markdown, csv, json, log, and python files.
    """
    try:
        if not os.path.exists(file_path):
            return {"success": False, "message": f"File not found: {file_path}"}
        if not is_safe_file_path(file_path):
            return {"success": False, "message": "File is outside allowed directories."}

        ext = os.path.splitext(file_path)[1].lower()
        supported = {".txt", ".md", ".csv", ".json", ".log", ".py", ".html", ".css", ".js", ".xml"}
        if ext not in supported:
            return {"success": False, "message": f"File type '{ext}' is not a plain text format."}

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(max_chars)

        is_truncated = len(content) == max_chars
        msg = f"Extracted {len(content)} characters from '{os.path.basename(file_path)}'." + (" (truncated)" if is_truncated else "")
        return {
            "success": True,
            "text": content,
            "truncated": is_truncated,
            "message": msg
        }
    except Exception as e:
        return {"success": False, "message": f"Failed to read file: {e}"}
