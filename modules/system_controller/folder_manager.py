"""
Folder Manager for Nova System Controller
Handles folder creation and deletion operations
"""

import os
import shutil
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

def get_user_home():
    """Get the user's home directory"""
    return os.path.expanduser("~")

def is_safe_path(path, base_path=None):
    """Check if path is safe for operations (within user directories)"""
    if base_path is None:
        base_path = get_user_home()
    
    try:
        resolved_path = Path(path).resolve()
        resolved_base = Path(base_path).resolve()
        return resolved_path.is_relative_to(resolved_base)
    except (ValueError, OSError):
        return False

def create_folder(folder_name, location="desktop"):
    """
    Create a folder in specified location
    
    Args:
        folder_name (str): Name of the folder to create
        location (str): "desktop" or "home"
    
    Returns:
        str: Success message or error
    """
    try:
        if location == "desktop":
            base_path = get_desktop_path()
        else:
            base_path = get_user_home()

        folder_path = os.path.join(base_path, folder_name)
        
        # Safety check
        if not is_safe_path(folder_path, base_path):
            logger.warning(f"Unsafe folder creation attempted: {folder_path}")
            return "Error: Folder path is outside allowed user directories."
        
        os.makedirs(folder_path, exist_ok=True)
        logger.info(f"Folder created: {folder_path}")
        return f"Folder '{folder_name}' created at {base_path}"
        
    except Exception as e:
        logger.error(f"Failed to create folder '{folder_name}': {str(e)}")
        return f"Error creating folder: {str(e)}"

def delete_folder(folder_name, location="desktop", confirm=False):
    """
    Delete a folder from specified location
    
    Args:
        folder_name (str): Name of the folder to delete
        location (str): "desktop" or "home"
        confirm (bool): Confirmation flag for safety
    
    Returns:
        str: Success message or error
    """
    if not confirm:
        return "Error: Deletion requires explicit confirmation."
    
    try:
        if location == "desktop":
            base_path = get_desktop_path()
        else:
            base_path = get_user_home()

        folder_path = os.path.join(base_path, folder_name)
        
        # Safety check
        if not is_safe_path(folder_path, base_path):
            logger.warning(f"Unsafe folder deletion attempted: {folder_path}")
            return "Error: Folder path is outside allowed user directories."
        
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)
            logger.info(f"Folder deleted: {folder_path}")
            return f"Folder '{folder_name}' deleted."
        else:
            return "Folder not found."
            
    except Exception as e:
        logger.error(f"Failed to delete folder '{folder_name}': {str(e)}")
        return f"Error deleting folder: {str(e)}"

def list_folders(location="desktop"):
    """
    List folders in specified location
    
    Args:
        location (str): "desktop" or "home"
    
    Returns:
        list: List of folder names
    """
    try:
        if location == "desktop":
            base_path = get_desktop_path()
        else:
            base_path = get_user_home()

        if os.path.exists(base_path):
            items = os.listdir(base_path)
            folders = [item for item in items if os.path.isdir(os.path.join(base_path, item))]
            return folders
        return []
        
    except Exception as e:
        logger.error(f"Failed to list folders: {str(e)}")
        return []
