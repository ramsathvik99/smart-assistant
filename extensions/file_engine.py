
import os
import re

class FileEngine:
    def create_folder(self, command_text: str):
        """
        Creates a folder based on natural language command.
        e.g. "create a folder named ok" -> creates "ok"
        """
        # Extract folder name
        # Patterns: "named X", "called X", "folder X"
        name = None
        
        # Regex for "named" or "called"
        match = re.search(r"(?:named|called)\s+(.+)", command_text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
        else:
            # Fallback: "create folder X" -> take X
            # Remove "create", "make", "new", "folder", "directory", "a", "an"
            words = command_text.split()
            keywords = ["create", "make", "new", "folder", "directory", "a", "an", "the"]
            filtered = [w for w in words if w.lower() not in keywords]
            
            if filtered:
                name = " ".join(filtered)
        
        if not name:
            return "Please tell me the folder name."
            
    def create_folder_pure(self, folder_name: str):
        """
        Creates a folder with the exact name provided.
        Used for follow-up responses where regex extraction isn't needed.
        """
        if not folder_name:
            return "Folder name cannot be empty."
            
        # Sanitize name active path
        # For simple robust testing, create on Desktop
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        path = os.path.join(desktop, folder_name)
        
        try:
            if os.path.exists(path):
                return f"Folder {folder_name} already exists."
            
            os.makedirs(path)
            return f"Folder {folder_name} created successfully."
        except Exception as e:
            return f"Failed to create folder {folder_name}."
