"""
Resource Helper for NOVA Assistant
Provides cross-platform resource path resolution for both development and packaged environments.
"""
import os
import sys
from pathlib import Path

def get_base_dir():
    """
    Get the absolute project root directory
    
    Returns:
        Path: Absolute path to the project root
    """
    return Path(__file__).resolve().parent.parent

def resource_path(relative_path):
    """
    Get absolute path to resource, works for dev and for PyInstaller
    
    Args:
        relative_path (str): Relative path from the project root
        
    Returns:
        str: Absolute path to the resource
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
        return os.path.join(base_path, relative_path)
    except Exception:
        # In development, use absolute project root
        base_dir = get_base_dir()
        return str(base_dir / relative_path)

def get_resource_dir():
    """Get the resource directory path"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        return sys._MEIPASS
    except Exception:
        # In development, use the absolute project root
        return str(get_base_dir())
