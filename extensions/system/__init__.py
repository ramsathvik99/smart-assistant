# Extensions System Module
"""
System Module - Fast System-Wide App & Folder Opener
Provides intelligent app and folder discovery and launching capabilities
"""

from .system_indexer import system_indexer
from .smart_opener import smart_opener

__all__ = ['system_indexer', 'smart_opener']
