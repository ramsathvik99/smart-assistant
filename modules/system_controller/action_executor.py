"""
Action Executor for Nova System Controller
Structured executor for system operations with safety layer
"""

import logging
import json
from datetime import datetime
from .folder_manager import create_folder, delete_folder, list_folders
from .file_manager import open_file, get_file_info, list_files
from .app_launcher import launch_application, get_running_applications


logger = logging.getLogger(__name__)

class SystemActionExecutor:
    """Safe executor for system actions with logging and confirmation"""
    
    def __init__(self):
        self.action_log = []
        self.require_confirmation = ["delete_folder", "delete_file"]
    
    def log_action(self, action, data, result, success=True):
        """Log all system actions for audit trail"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "data": data,
            "result": result,
            "success": success
        }
        self.action_log.append(log_entry)
        logger.info(f"System action logged: {action} - {result}")
    
    def execute_action(self, action_data, confirm=False):
        """
        Execute a system action with safety checks
        
        Args:
            action_data (dict): Action specification with action type and parameters
            confirm (bool): Confirmation flag for dangerous operations
        
        Returns:
            dict: Structured result with success status and message
        """
        try:
            action = action_data.get("action")
            if not action:
                return {"success": False, "message": "No action specified"}
            
            # Check for confirmation requirement
            if action in self.require_confirmation and not confirm:
                return {
                    "success": False, 
                    "message": f"Action '{action}' requires explicit confirmation"
                }
            
            result = None
            success = True
            
            # Folder operations
            if action == "create_folder":
                folder_name = action_data.get("name")
                location = action_data.get("location", "desktop")
                if not folder_name:
                    return {"success": False, "message": "Folder name required"}
                result = create_folder(folder_name, location)
            
            elif action == "delete_folder":
                folder_name = action_data.get("name")
                location = action_data.get("location", "desktop")
                if not folder_name:
                    return {"success": False, "message": "Folder name required"}
                result = delete_folder(folder_name, location, confirm=True)
            
            elif action == "list_folders":
                location = action_data.get("location", "desktop")
                result = list_folders(location)
            
            # File operations
            elif action == "open_file":
                file_path = action_data.get("path")
                if not file_path:
                    return {"success": False, "message": "File path required"}
                result = open_file(file_path)
            
            elif action == "get_file_info":
                file_path = action_data.get("path")
                if not file_path:
                    return {"success": False, "message": "File path required"}
                result = get_file_info(file_path)
            
            elif action == "list_files":
                directory_path = action_data.get("directory")
                result = list_files(directory_path)
            
            # Application operations
            elif action == "launch_app":
                app_name = action_data.get("app")
                if not app_name:
                    return {"success": False, "message": "Application name required"}
                args = action_data.get("args", [])
                result = launch_application(app_name, args)
            
            elif action == "list_running_apps":
                result = get_running_applications()
            
            else:
                return {"success": False, "message": f"Invalid action: {action}"}
            
            # Log the action
            self.log_action(action, action_data, result, success)
            
            return {
                "success": success,
                "message": result,
                "action": action,
                "data": action_data
            }
            
        except Exception as e:
            error_msg = f"Error executing action '{action}': {str(e)}"
            logger.error(error_msg)
            self.log_action(action, action_data, error_msg, False)
            
            return {
                "success": False,
                "message": error_msg,
                "action": action,
                "data": action_data
            }
    
    def get_action_history(self, limit=10):
        """Get recent action history"""
        return self.action_log[-limit:] if self.action_log else []
    
    def clear_action_log(self):
        """Clear the action log"""
        self.action_log.clear()
        return {"success": True, "message": "Action log cleared"}

# Global executor instance
_executor = SystemActionExecutor()

def execute_action(action_data, confirm=False):
    """
    Convenience function for executing actions
    
    Args:
        action_data (dict or str): Action specification (dict or JSON string)
        confirm (bool): Confirmation flag for dangerous operations
    
    Returns:
        dict: Structured result
    """
    if isinstance(action_data, str):
        try:
            action_data = json.loads(action_data)
        except json.JSONDecodeError:
            return {
                "success": False,
                "message": "Invalid JSON format for action data"
            }
    
    return _executor.execute_action(action_data, confirm)


def get_action_history(limit=10):
    """Get recent action history"""
    return _executor.get_action_history(limit)

def clear_action_log():
    """Clear the action log"""
    return _executor.clear_action_log()

# Export the main executor class for advanced usage
__all__ = [
    'SystemActionExecutor',
    'execute_action', 
    'get_action_history',
    'clear_action_log'
]
