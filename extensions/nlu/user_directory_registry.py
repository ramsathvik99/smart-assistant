#!/usr/bin/env python3
"""
User Directory Registry - Safe Windows user shell folder handling

Provides deterministic access to common user directories with security constraints.
Only allows access to predefined safe user folders and their contents.
"""

import os
import json
import time
import threading
from pathlib import Path, WindowsPath
from typing import Dict, List, Optional, Set
import fnmatch

class UserDirectoryRegistry:
    """
    Registry for safe user shell directories with file indexing capabilities.
    
    Provides:
    - Dynamic resolution of user shell folders
    - Safe file indexing within allowed directories
    - Security validation for directory/file access
    - Performance-optimized file search
    """
    
    # Safe user shell folder names (Windows shell folder identifiers)
    SAFE_DIRECTORIES = {
        'desktop',
        'documents', 
        'downloads',
        'music',
        'pictures',
        'videos',
        '3d objects',
        'favorites',
        'recent'
    }
    
    # Safe file extensions for search and execution
    SAFE_FILE_EXTENSIONS = {
        # Documents
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.txt', '.rtf', '.odt', '.ods', '.odp',
        
        # Images
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.svg',
        
        # Media
        '.mp3', '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv',
        
        # Code/Text
        '.py', '.js', '.html', '.css', '.json', '.xml', '.md',
        
        # Archives
        '.zip', '.rar', '.7z', '.tar', '.gz',
        
        # Executables (only from user directories)
        '.exe', '.msi', '.bat', '.cmd', '.ps1',
        
        # Shortcuts
        '.lnk'
    }
    
    def __init__(self):
        self._directory_paths: Dict[str, Path] = {}
        self._file_index: Dict[str, List[str]] = {}
        self._index_timestamp: float = 0
        self._index_lock = threading.Lock()
        self._cache_duration = 300  # 5 minutes cache
        
        # Initialize directory paths
        self._initialize_directory_paths()
        
        # File indexing disabled - only build when explicitly requested
        # self._build_file_index()  # REMOVED: No automatic indexing
    
    def _initialize_directory_paths(self):
        """Initialize safe user directory paths dynamically"""
        try:
            home = Path.home()
            
            # Map folder names to actual paths
            self._directory_paths = {
                'desktop': home / 'Desktop',
                'documents': home / 'Documents', 
                'downloads': home / 'Downloads',
                'music': home / 'Music',
                'pictures': home / 'Pictures',
                'videos': home / 'Videos',
                '3d objects': home / '3D Objects',
                'favorites': home / 'Favorites',
                'recent': home / 'AppData' / 'Roaming' / 'Microsoft' / 'Windows' / 'Recent'
            }
            
            # Filter to only existing directories
            self._directory_paths = {
                name: path for name, path in self._directory_paths.items() 
                if path.exists() and path.is_dir()
            }
            
            print(f"[DIR REGISTRY] Initialized {len(self._directory_paths)} safe directories")
            
        except Exception as e:
            print(f"[DIR REGISTRY] Error initializing directories: {e}")
            self._directory_paths = {}
    
    def _build_file_index(self):
        """Build file index for all safe directories"""
        with self._index_lock:
            try:
                self._file_index = {}
                
                for dir_name, dir_path in self._directory_paths.items():
                    files = self._scan_directory_files(dir_path, max_depth=3)
                    self._file_index[dir_name] = files
                
                self._index_timestamp = time.time()
                total_files = sum(len(files) for files in self._file_index.values())
                print(f"[DIR REGISTRY] Indexed {total_files} files across {len(self._file_index)} directories")
                
            except Exception as e:
                print(f"[DIR REGISTRY] Error building file index: {e}")
                self._file_index = {}
    
    def _scan_directory_files(self, directory: Path, max_depth: int = 3) -> List[str]:
        """Scan directory for files within safe extensions and depth limit"""
        files = []
        
        try:
            for item in directory.iterdir():
                if item.is_file():
                    # Check file extension
                    if item.suffix.lower() in self.SAFE_FILE_EXTENSIONS:
                        files.append(str(item))
                elif item.is_dir() and max_depth > 0:
                    # Recursively scan subdirectories (limited depth)
                    try:
                        sub_files = self._scan_directory_files(item, max_depth - 1)
                        files.extend(sub_files)
                    except (PermissionError, OSError):
                        # Skip directories we can't access
                        continue
                        
        except (PermissionError, OSError) as e:
            print(f"[DIR REGISTRY] Permission denied accessing {directory}: {e}")
        
        return files
    
    def get_directory_path(self, folder_name: str) -> Optional[Path]:
        """
        Get the absolute path for a safe directory name.
        
        Args:
            folder_name: Name of the folder (e.g., 'desktop', 'downloads')
            
        Returns:
            Path object if directory exists and is safe, None otherwise
        """
        folder_name = folder_name.lower().strip()
        
        if folder_name not in self.SAFE_DIRECTORIES:
            return None
        
        return self._directory_paths.get(folder_name)
    
    def is_safe_directory(self, path: Path) -> bool:
        """
        Check if a path is within safe user directories.
        
        Args:
            path: Path to check
            
        Returns:
            True if path is within safe directories, False otherwise
        """
        try:
            # Resolve to absolute path
            abs_path = path.resolve()
            
            # Check if path is under any safe directory
            for safe_dir in self._directory_paths.values():
                try:
                    if abs_path.is_relative_to(safe_dir):
                        return True
                except AttributeError:
                    # Python < 3.9 fallback
                    try:
                        abs_path.relative_to(safe_dir)
                        return True
                    except ValueError:
                        continue
                        
        except Exception as e:
            print(f"[DIR REGISTRY] Error checking safe directory: {e}")
        
        return False
    
    def search_files(self, filename: str, limit: int = 10) -> List[Dict[str, str]]:
        """
        Search for files by filename within safe directories.
        
        Args:
            filename: Filename to search for (can include wildcards)
            limit: Maximum number of results to return
            
        Returns:
            List of dictionaries with file info
        """
        # Update index if cache is expired
        if time.time() - self._index_timestamp > self._cache_duration:
            threading.Thread(target=self._build_file_index, daemon=True).start()
        
        results = []
        filename_lower = filename.lower()
        
        with self._index_lock:
            for dir_name, files in self._file_index.items():
                for file_path in files:
                    file_name = Path(file_path).name
                    
                    # Check for partial match (case-insensitive)
                    if filename_lower in file_name.lower():
                        results.append({
                            'filename': file_name,
                            'path': file_path,
                            'directory': dir_name
                        })
                        
                        if len(results) >= limit:
                            return results
        
        return results
    
    def refresh_index(self):
        """Force refresh of file index"""
        threading.Thread(target=self._build_file_index, daemon=True).start()
    
    def get_safe_directories(self) -> Dict[str, str]:
        """Get dictionary of safe directory names and their paths"""
        return {name: str(path) for name, path in self._directory_paths.items()}
    
    def is_safe_file_extension(self, extension: str) -> bool:
        """Check if file extension is considered safe"""
        return extension.lower() in self.SAFE_FILE_EXTENSIONS

# Global registry instance
_registry = None

def get_registry() -> UserDirectoryRegistry:
    """Get the global user directory registry instance"""
    global _registry
    if _registry is None:
        _registry = UserDirectoryRegistry()
    return _registry

def is_safe_directory_path(folder_name: str) -> bool:
    """Check if folder name corresponds to a safe directory"""
    return folder_name.lower().strip() in UserDirectoryRegistry.SAFE_DIRECTORIES

if __name__ == "__main__":
    # Test the registry
    registry = get_registry()
    
    print("Safe User Directory Registry Test")
    print("=" * 50)
    
    print("\nSafe directories:")
    for name, path in registry.get_safe_directories().items():
        print(f"  {name}: {path}")
    
    print("\nTesting directory resolution:")
    test_folders = ['desktop', 'downloads', 'documents', 'system32', 'c:\\']
    for folder in test_folders:
        path = registry.get_directory_path(folder)
        print(f"  {folder} -> {path}")
    
    print("\nTesting file search:")
    search_results = registry.search_files('.pdf', limit=5)
    for result in search_results:
        print(f"  Found: {result['filename']} in {result['directory']}")
    
    print("\n✅ Registry test complete")
