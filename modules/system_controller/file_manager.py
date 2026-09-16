"""
File Manager for Nova System Controller
Handles file opening and basic file operations
"""

import os
import subprocess
import platform
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def get_desktop_path():
    """Get the user's Desktop path with OneDrive support"""
    # First check OneDrive Desktop
    onedrive_desktop = os.path.join(
        os.environ.get("USERPROFILE", ""),
        "OneDrive",
        "Desktop"
    )
    
    if os.path.exists(onedrive_desktop):
        return onedrive_desktop
    
    # Fallback to standard Desktop
    return os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")

def find_file_in_desktop(filename):
    """Search for a file in the Desktop directory and subdirectories"""
    desktop = get_desktop_path()
    try:
        for root, dirs, files in os.walk(desktop):
            if filename.lower() in [f.lower() for f in files]:
                return os.path.join(root, filename)
    except Exception as e:
        logger.error(f"Error searching for file '{filename}': {str(e)}")
    return None

def is_safe_file_path(file_path):
    """Check if file path is safe for operations"""
    try:
        resolved_path = Path(file_path).resolve()
        # Allow common user directories
        safe_dirs = [
            Path.home(),
            Path.home() / "Desktop",
            Path.home() / "Documents", 
            Path.home() / "Downloads",
            Path.home() / "Pictures",
            Path.home() / "Videos",
            Path.home() / "Music"
        ]
        
        return any(resolved_path.is_relative_to(safe_dir) for safe_dir in safe_dirs)
    except (ValueError, OSError):
        return False

def open_file(file_path):
    """
    Open a file with the default system application
    
    Args:
        file_path (str): Path to the file to open
    
    Returns:
        str: Success message or error
    """
    try:
        if not os.path.exists(file_path):
            # Try smart search in Desktop
            filename = os.path.basename(file_path)
            found_path = find_file_in_desktop(filename)
            if found_path:
                file_path = found_path
            else:
                return f"File '{filename}' not found."
        
        # Safety check
        if not is_safe_file_path(file_path):
            logger.warning(f"Unsafe file access attempted: {file_path}")
            return "Error: File path is outside allowed user directories."
        
        system = platform.system()
        
        if system == "Windows":
            os.startfile(file_path)
        elif system == "Darwin":  # macOS
            subprocess.call(["open", file_path])
        else:  # Linux
            subprocess.call(["xdg-open", file_path])
        
        logger.info(f"File opened: {file_path}")
        return f"File '{os.path.basename(file_path)}' opened successfully."
        
    except Exception as e:
        logger.error(f"Failed to open file '{file_path}': {str(e)}")
        return f"Error opening file: {str(e)}"

def get_file_info(file_path):
    """
    Get basic information about a file
    
    Args:
        file_path (str): Path to the file
    
    Returns:
        dict: File information or error
    """
    try:
        if not os.path.exists(file_path):
            return {"error": "File not found"}
        
        if not is_safe_file_path(file_path):
            return {"error": "File path is outside allowed directories"}
        
        stat = os.stat(file_path)
        return {
            "name": os.path.basename(file_path),
            "path": file_path,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "is_file": os.path.isfile(file_path),
            "is_dir": os.path.isdir(file_path)
        }
        
    except Exception as e:
        logger.error(f"Failed to get file info for '{file_path}': {str(e)}")
        return {"error": str(e)}

def list_files(directory_path=None):
    """
    List files in a directory
    
    Args:
        directory_path (str): Path to directory (defaults to Desktop)
    
    Returns:
        list: List of file information dictionaries
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
        logger.error(f"Failed to list files in '{directory_path}': {str(e)}")
        return []
