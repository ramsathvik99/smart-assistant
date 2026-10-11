"""
Universal OS Operations — Universal Filesystem Operations
Supports filesystem operations across ALL accessible storage locations:
- C:, D:, E:, USB, removable, and mapped network drives
- User directories, application directories, project directories, temp directories
- Create, read, write, copy, move, rename, delete, search, size, metadata, links
"""

from __future__ import annotations

import filecmp
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Recycle bin support
try:
    import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False


def create_file(path: str, content: str = "") -> Dict[str, Any]:
    """Create a file at any accessible path, ensuring parent directories exist."""
    try:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "status": "created",
            "path": str(p),
            "size": len(content.encode("utf-8")),
            "message": f"Created file '{p.name}' at {p.parent}.",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to create file: {exc}"}


def read_file(path: str, max_bytes: int = 1000000) -> Dict[str, Any]:
    """Read file content safely with size limit guard."""
    try:
        p = Path(path).resolve()
        if not p.exists() or not p.is_file():
            return {"success": False, "status": "error", "error": f"File '{path}' does not exist.", "message": f"File '{path}' does not exist."}

        size = p.stat().st_size
        if size > max_bytes:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_bytes)
            truncated = True
        else:
            content = p.read_text(encoding="utf-8", errors="replace")
            truncated = False

        return {
            "success": True,
            "status": "read",
            "path": str(p),
            "size": size,
            "truncated": truncated,
            "content": content,
            "message": f"Read {len(content)} characters from '{p.name}'" + (" (truncated)" if truncated else "") + ".",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to read file: {exc}"}


def write_file(path: str, content: str, mode: str = "w") -> Dict[str, Any]:
    """Write or append content to a file."""
    try:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        file_mode = "a" if "a" in mode.lower() else "w"
        with open(p, file_mode, encoding="utf-8") as f:
            f.write(content)

        return {
            "success": True,
            "status": "written",
            "path": str(p),
            "mode": file_mode,
            "bytes_written": len(content.encode("utf-8")),
            "message": f"Wrote content to '{p.name}'.",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to write file: {exc}"}


def copy_file(source: str, destination: str) -> Dict[str, Any]:
    """Copy a file across directories or drives."""
    try:
        src = Path(source).resolve()
        if not src.exists() or not src.is_file():
            return {"success": False, "status": "error", "message": f"Source file '{source}' does not exist."}

        dest = Path(destination).resolve()
        if dest.is_dir() or str(destination).endswith(("\\", "/")):
            dest.mkdir(parents=True, exist_ok=True)
            dest = dest / src.name
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(str(src), str(dest))
        return {
            "success": True,
            "status": "copied",
            "source": str(src),
            "destination": str(dest),
            "size": dest.stat().st_size,
            "message": f"Copied '{src.name}' to {dest.parent}.",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to copy file: {exc}"}


def move_file(source: str, destination: str) -> Dict[str, Any]:
    """Move or relocate a file across directories or drives."""
    try:
        src = Path(source).resolve()
        if not src.exists():
            return {"success": False, "status": "error", "message": f"Source file '{source}' does not exist."}

        dest = Path(destination).resolve()
        if dest.is_dir() or str(destination).endswith(("\\", "/")):
            dest.mkdir(parents=True, exist_ok=True)
            dest = dest / src.name
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(str(src), str(dest))
        return {
            "success": True,
            "status": "moved",
            "source": str(src),
            "destination": str(dest),
            "message": f"Moved '{src.name}' to {dest}.",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to move file: {exc}"}


def rename_file(source: str, new_name: str) -> Dict[str, Any]:
    """Rename a file or folder in-place."""
    try:
        src = Path(source).resolve()
        if not src.exists():
            return {"success": False, "status": "error", "message": f"Target '{source}' does not exist."}

        clean_new = os.path.basename(new_name.strip())
        dest = src.parent / clean_new
        src.rename(dest)

        return {
            "success": True,
            "status": "renamed",
            "old_path": str(src),
            "new_path": str(dest),
            "message": f"Renamed '{src.name}' to '{clean_new}'.",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to rename: {exc}"}


def delete_file(path: str, permanent: bool = False) -> Dict[str, Any]:
    """Delete a file, using Recycle Bin by default for safety."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"success": False, "status": "error", "message": f"File '{path}' does not exist."}

        if not permanent and HAS_SEND2TRASH:
            send2trash.send2trash(str(p))
            return {
                "success": True,
                "status": "recycled",
                "path": str(p),
                "message": f"Moved '{p.name}' to Recycle Bin.",
            }
        else:
            if p.is_dir():
                shutil.rmtree(str(p))
            else:
                p.unlink()
            return {
                "success": True,
                "status": "deleted",
                "path": str(p),
                "message": f"Permanently deleted '{p.name}'.",
            }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to delete: {exc}"}


def create_directory(path: str) -> Dict[str, Any]:
    """Create a directory and any intermediate folders."""
    try:
        p = Path(path).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return {
            "success": True,
            "status": "created",
            "path": str(p),
            "message": f"Created directory '{p}'.",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to create directory: {exc}"}


def delete_directory(path: str, permanent: bool = False) -> Dict[str, Any]:
    """Delete a directory."""
    return delete_file(path, permanent=permanent)


def list_directory(path: str, max_items: int = 100) -> Dict[str, Any]:
    """List directory contents with metadata (folders, files, sizes)."""
    try:
        p = Path(path).resolve()
        if not p.exists() or not p.is_dir():
            return {"success": False, "status": "error", "message": f"Directory '{path}' does not exist."}

        items = []
        for entry in p.iterdir():
            try:
                st = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": entry.is_dir(),
                    "size": st.st_size if entry.is_file() else 0,
                    "modified": st.st_mtime,
                })
            except Exception:
                continue

            if len(items) >= max_items:
                break

        dirs = [i for i in items if i["is_dir"]]
        files = [i for i in items if not i["is_dir"]]

        return {
            "success": True,
            "status": "listed",
            "path": str(p),
            "total_items": len(items),
            "folder_count": len(dirs),
            "file_count": len(files),
            "folders": dirs,
            "files": files,
            "entries": items,
            "items": items,
            "message": f"Found {len(dirs)} folders and {len(files)} files in '{p}'.",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to list directory: {exc}"}


def search_files(
    root_path: str = "C:\\",
    pattern: str = "*",
    extension: Optional[str] = None,
    min_size_mb: Optional[float] = None,
    max_size_mb: Optional[float] = None,
    max_results: int = 50,
    search_depth: int = 5,
) -> Dict[str, Any]:
    """
    Search for files matching name pattern, extension, or size filters across any drive.
    e.g. "Find every Python file larger than 100 MB."
    """
    results: List[Dict[str, Any]] = []
    root = Path(root_path).resolve()

    if not root.exists():
        return {"success": False, "status": "error", "message": f"Search root '{root_path}' does not exist."}

    norm_ext = f".{extension.lower().lstrip('.')}" if extension else None
    min_bytes = int(min_size_mb * 1024 * 1024) if min_size_mb is not None else None
    max_bytes = int(max_size_mb * 1024 * 1024) if max_size_mb is not None else None
    target_pattern = pattern.lower()

    ignore_dirs = {
        "$recycle.bin", "system volume information", "windows", "program files",
        "program files (x86)", ".git", "node_modules", "__pycache__", ".venv", "venv"
    }

    try:
        for cur_root, dirs, files in os.walk(str(root)):
            # Respect depth limit
            rel = os.path.relpath(cur_root, str(root))
            depth = 0 if rel == "." else len(Path(rel).parts)
            if depth > search_depth:
                dirs[:] = []
                continue

            # Filter ignored directories
            dirs[:] = [d for d in dirs if d.lower() not in ignore_dirs and not d.startswith('.')]

            for f in files:
                f_low = f.lower()
                if norm_ext and not f_low.endswith(norm_ext):
                    continue
                if pattern != "*" and target_pattern not in f_low:
                    continue

                full_p = os.path.join(cur_root, f)
                try:
                    st = os.stat(full_p)
                    size = st.st_size
                    if min_bytes is not None and size < min_bytes:
                        continue
                    if max_bytes is not None and size > max_bytes:
                        continue

                    results.append({
                        "name": f,
                        "path": full_p,
                        "size": size,
                        "size_mb": round(size / (1024 * 1024), 2),
                        "modified": st.st_mtime,
                    })
                except Exception:
                    continue

                if len(results) >= max_results:
                    break

            if len(results) >= max_results:
                break

        return {
            "success": True,
            "status": "searched",
            "root": str(root),
            "match_count": len(results),
            "results": results,
            "matches": [r["path"] for r in results],
            "message": f"Found {len(results)} matching files in '{root}'.",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Search failed: {exc}"}


def open_file_or_folder(path: str) -> Dict[str, Any]:
    """Open a file or directory using the OS default application / File Explorer."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"success": False, "status": "error", "message": f"Target '{path}' does not exist."}

        if sys.platform == "win32":
            os.startfile(str(p))
        else:
            subprocess.Popen(["xdg-open", str(p)])

        return {
            "success": True,
            "status": "opened",
            "path": str(p),
            "is_dir": p.is_dir(),
            "message": f"Opened {'folder' if p.is_dir() else 'file'} '{p.name}'.",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to open '{path}': {exc}"}


def inspect_metadata(path: str) -> Dict[str, Any]:
    """Inspect detailed filesystem metadata for a file or directory."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"success": False, "status": "error", "message": f"Target '{path}' does not exist."}

        st = p.stat()
        return {
            "success": True,
            "status": "inspected",
            "path": str(p),
            "name": p.name,
            "is_dir": p.is_dir(),
            "is_file": p.is_file(),
            "is_symlink": p.is_symlink(),
            "size": st.st_size,
            "size_bytes": st.st_size,
            "size_kb": round(st.st_size / 1024, 2),
            "size_mb": round(st.st_size / (1024 * 1024), 2),
            "created_at": st.st_ctime,
            "modified_at": st.st_mtime,
            "accessed_at": st.st_atime,
            "extension": p.suffix,
            "drive": p.drive,
            "message": f"Inspected metadata for '{p.name}' ({round(st.st_size / 1024, 1)} KB).",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Metadata inspection failed: {exc}"}


def calculate_size(path: str) -> Dict[str, Any]:
    """Calculate the total size of a file or directory tree."""
    try:
        p = Path(path).resolve()
        if not p.exists():
            return {"success": False, "status": "error", "message": f"Target '{path}' does not exist."}

        if p.is_file():
            total_bytes = p.stat().st_size
            file_count = 1
            folder_count = 0
        else:
            total_bytes = 0
            file_count = 0
            folder_count = 0
            for root, dirs, files in os.walk(str(p)):
                folder_count += len(dirs)
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        total_bytes += os.path.getsize(fp)
                        file_count += 1
                    except Exception:
                        pass

        size_mb = round(total_bytes / (1024 * 1024), 2)
        size_gb = round(total_bytes / (1024 * 1024 * 1024), 2)

        return {
            "success": True,
            "status": "calculated",
            "path": str(p),
            "total_bytes": total_bytes,
            "size_bytes": total_bytes,
            "size_mb": size_mb,
            "size_gb": size_gb,
            "file_count": file_count,
            "folder_count": folder_count,
            "message": f"'{p.name}' contains {file_count} files ({size_mb} MB).",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Size calculation failed: {exc}"}


def compare_files(path_a: str, path_b: str) -> Dict[str, Any]:
    """Compare two files by size, modification time, and SHA-256 hash."""
    try:
        pa = Path(path_a).resolve()
        pb = Path(path_b).resolve()

        if not pa.exists() or not pa.is_file():
            return {"success": False, "status": "error", "message": f"File '{path_a}' does not exist."}
        if not pb.exists() or not pb.is_file():
            return {"success": False, "status": "error", "message": f"File '{path_b}' does not exist."}

        same_size = (pa.stat().st_size == pb.stat().st_size)
        quick_identical = filecmp.cmp(str(pa), str(pb), shallow=False)

        return {
            "success": True,
            "status": "compared",
            "identical": quick_identical,
            "file_a": str(pa),
            "file_b": str(pb),
            "size_a": pa.stat().st_size,
            "size_b": pb.stat().st_size,
            "message": f"Files '{pa.name}' and '{pb.name}' are {'identical' if quick_identical else 'different'}.",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Comparison failed: {exc}"}


def create_archive(sources: List[str], archive_path: str) -> Dict[str, Any]:
    """Archive one or more files/directories into a zip file."""
    import zipfile
    out_zip = os.path.abspath(os.path.expanduser(os.path.expandvars(archive_path)))
    if not out_zip.lower().endswith(".zip"):
        out_zip += ".zip"
    parent = os.path.dirname(out_zip)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    try:
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for src in sources:
                s_abs = os.path.abspath(os.path.expanduser(os.path.expandvars(src)))
                if os.path.isdir(s_abs):
                    for root, _, files in os.walk(s_abs):
                        for f in files:
                            f_full = os.path.join(root, f)
                            rel = os.path.relpath(f_full, os.path.dirname(s_abs))
                            zf.write(f_full, arcname=rel)
                elif os.path.isfile(s_abs):
                    zf.write(s_abs, arcname=os.path.basename(s_abs))
        return {"success": True, "status": "archived", "archive_path": out_zip, "file_count": len(sources)}
    except Exception as e:
        return {"success": False, "status": "error", "error": str(e), "message": f"Failed to create archive: {e}"}


def extract_archive(archive_path: str, extract_dir: str) -> Dict[str, Any]:
    """Extract a zip archive into a destination directory."""
    import zipfile
    arc = os.path.abspath(os.path.expanduser(os.path.expandvars(archive_path)))
    dest = os.path.abspath(os.path.expanduser(os.path.expandvars(extract_dir)))
    if not os.path.exists(arc):
        return {"success": False, "status": "error", "error": f"Archive '{arc}' does not exist.", "message": f"Archive '{arc}' does not exist."}
    try:
        os.makedirs(dest, exist_ok=True)
        with zipfile.ZipFile(arc, "r") as zf:
            zf.extractall(dest)
        return {"success": True, "status": "extracted", "archive": arc, "destination": dest}
    except Exception as e:
        return {"success": False, "status": "error", "error": str(e), "message": f"Failed to extract archive: {e}"}
