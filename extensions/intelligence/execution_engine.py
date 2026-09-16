"""
Execution Engine Module
Executes multi-step plans and learned tasks with intelligent mapping.
"""

import logging
import time
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass

@dataclass
class ExecutionStep:
    """Represents a single step in an execution plan"""
    action: str
    description: str
    requires_confirmation: bool = False
    timeout: float = 30.0

class ExecutionEngine:
    """Executes multi-step plans and learned tasks"""
    
    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger("assistant.intelligence.execution")
        
        # Step execution mapping
        self.step_mapping: Dict[str, Callable] = {
            # VSCode actions
            "open_vscode": self._open_vscode,
            "open_project": self._open_project,
            "open_project_folder": self._open_project_folder,
            "open_terminal": self._open_terminal,
            "open_git": self._open_git,
            "open_extensions": self._open_vscode_extensions,
            "open_settings": self._open_vscode_settings,
            
            # Browser actions
            "open_browser": self._open_browser,
            "search_query": self._search_query,
            "search_tutorial": self._search_tutorial,
            "search_documentation": self._search_documentation,
            "pause_video": self._pause_video,
            "play_video": self._play_video,
            "next_video": self._next_video,
            "previous_video": self._previous_video,
            "stop_video": self._stop_video,
            "mute_video": self._mute_video,
            "unmute_video": self._unmute_video,
            "fullscreen_video": self._fullscreen_video,
            "browser_back": self._browser_back,
            "browser_forward": self._browser_forward,
            "browser_refresh": self._browser_refresh,
            "browser_home": self._browser_home,
            "browser_new_tab": self._browser_new_tab,
            "browser_close_tab": self._browser_close_tab,
            
            # System actions
            "close_distractions": self._close_distractions,
            "play_focus_music": self._play_focus_music,
            "play_music": self._play_music,
            "set_reminder": self._set_reminder,
            "confirm": self._confirm_action,
            
            # Media control
            "pause": self._pause_media,
            "play": self._play_media,
            "next": self._next_media,
            "previous": self._previous_media,
            "stop": self._stop_media,
            "mute": self._mute_media,
            "unmute": self._unmute_media,
        }
        
        # Execution state
        self.current_plan: Optional[List[str]] = None
        self.current_step_index: int = 0
        self.execution_history: List[Dict[str, Any]] = []
    
    def execute_plan(self, plan: List[str], context: Dict[str, Any] | None = None) -> bool:
        """
        Execute a multi-step plan.
        
        Args:
            plan: List of step identifiers
            context: Execution context
            
        Returns:
            True if plan executed successfully, False otherwise
        """
        if not plan:
            self.logger.warning("Empty plan provided")
            return False
        
        self.current_plan = plan.copy()
        self.current_step_index = 0
        
        self.logger.info(f"Executing plan with {len(plan)} steps: {plan}")
        
        for i, step_id in enumerate(plan):
            self.current_step_index = i
            
            try:
                success = self.execute_step(step_id, context)
                
                # Record execution
                self.execution_history.append({
                    "step": step_id,
                    "success": success,
                    "timestamp": time.time(),
                    "context": context
                })
                
                if not success:
                    self.logger.error(f"Plan execution failed at step {i+1}: {step_id}")
                    return False
                
                # Small delay between steps for better user experience
                time.sleep(0.5)
                
            except Exception as e:
                self.logger.error(f"Error executing step {step_id}: {e}")
                self.execution_history.append({
                    "step": step_id,
                    "success": False,
                    "error": str(e),
                    "timestamp": time.time(),
                    "context": context
                })
                return False
        
        self.logger.info("Plan executed successfully")
        return True
    
    def execute_step(self, step_id: str, context: Dict[str, Any] | None = None) -> bool:
        """
        Execute a single step.
        
        Args:
            step_id: Step identifier
            context: Execution context
            
        Returns:
            True if step executed successfully, False otherwise
        """
        if step_id not in self.step_mapping:
            self.logger.warning(f"Unknown step: {step_id}")
            return False
        
        try:
            self.logger.info(f"Executing step: {step_id}")
            
            # Execute the step
            success = self.step_mapping[step_id](context or {})
            
            if success:
                self.logger.info(f"Step completed successfully: {step_id}")
            else:
                self.logger.warning(f"Step failed: {step_id}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Exception executing step {step_id}: {e}")
            return False
    
    def get_step_description(self, step_id: str) -> str:
        """Get a human-readable description of a step."""
        descriptions = {
            "open_vscode": "Opening VS Code",
            "open_project": "Opening project",
            "open_project_folder": "Opening project folder",
            "open_terminal": "Opening terminal",
            "open_git": "Opening Git",
            "open_extensions": "Opening VS Code extensions",
            "open_settings": "Opening VS Code settings",
            "open_browser": "Opening browser",
            "search_query": "Searching web",
            "search_tutorial": "Searching for tutorial",
            "search_documentation": "Searching for documentation",
            "pause_video": "Pausing video",
            "play_video": "Playing video",
            "next_video": "Next video",
            "previous_video": "Previous video",
            "stop_video": "Stopping video",
            "mute_video": "Muting video",
            "unmute_video": "Unmuting video",
            "fullscreen_video": "Fullscreen video",
            "browser_back": "Going back in browser",
            "browser_forward": "Going forward in browser",
            "browser_refresh": "Refreshing browser",
            "browser_home": "Going to browser home",
            "browser_new_tab": "Opening new tab",
            "browser_close_tab": "Closing tab",
            "close_distractions": "Closing distractions",
            "play_focus_music": "Playing focus music",
            "play_music": "Playing music",
            "set_reminder": "Setting reminder",
            "confirm": "Confirming action",
            "pause": "Pausing media",
            "play": "Playing media",
            "next": "Next media",
            "previous": "Previous media",
            "stop": "Stopping media",
            "mute": "Muting media",
            "unmute": "Unmuting media",
        }
        
        return descriptions.get(step_id, f"Executing {step_id}")
    
    def get_execution_progress(self) -> Dict[str, Any]:
        """Get current execution progress."""
        if not self.current_plan:
            return {"status": "no_plan"}
        
        return {
            "status": "executing",
            "total_steps": len(self.current_plan),
            "current_step": self.current_step_index + 1,
            "current_step_id": self.current_plan[self.current_step_index] if self.current_step_index < len(self.current_plan) else None,
            "progress_percent": (self.current_step_index / len(self.current_plan)) * 100
        }
    
    def cancel_execution(self):
        """Cancel current execution."""
        self.current_plan = None
        self.current_step_index = 0
        self.logger.info("Execution cancelled")
    
    def get_execution_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent execution history."""
        return self.execution_history[-limit:]
    
    # Step implementation methods
    def _open_vscode(self, context: Dict[str, Any]) -> bool:
        """Open VS Code."""
        try:
            from legacy.actions import open_app
            return open_app("vscode")
        except Exception as e:
            self.logger.error(f"Error opening VS Code: {e}")
            return False
    
    def _open_project(self, context: Dict[str, Any]) -> bool:
        """Open project (placeholder)."""
        # This would need to be implemented based on project detection
        self._open_vscode(context)
        return True
    
    def _open_project_folder(self, context: Dict[str, Any]) -> bool:
        """Open project folder."""
        try:
            import os
            # Try to open current directory or common project folders
            project_folders = ["src", "app", "project", "workspace"]
            current_dir = os.getcwd()
            
            for folder in project_folders:
                folder_path = os.path.join(current_dir, folder)
                if os.path.exists(folder_path):
                    os.startfile(folder_path)
                    return True
            
            # Fallback to opening current directory
            os.startfile(current_dir)
            return True
        except Exception as e:
            self.logger.error(f"Error opening project folder: {e}")
            return False
    
    def _open_terminal(self, context: Dict[str, Any]) -> bool:
        """Open terminal."""
        try:
            import subprocess
            subprocess.Popen(["cmd"], shell=True)
            return True
        except Exception as e:
            self.logger.error(f"Error opening terminal: {e}")
            return False
    
    def _open_git(self, context: Dict[str, Any]) -> bool:
        """Open Git interface."""
        try:
            import subprocess
            subprocess.Popen(["git", "gui"], shell=True)
            return True
        except Exception as e:
            self.logger.error(f"Error opening Git: {e}")
            return False
    
    def _open_vscode_extensions(self, context: Dict[str, Any]) -> bool:
        """Open VS Code extensions."""
        # This would need VS Code API integration
        return self._open_vscode(context)
    
    def _open_vscode_settings(self, context: Dict[str, Any]) -> bool:
        """Open VS Code settings."""
        # This would need VS Code API integration
        return self._open_vscode(context)
    
    def _open_browser(self, context: Dict[str, Any]) -> bool:
        """Open browser."""
        try:
            from legacy.actions import open_app
            return open_app("chrome")
        except Exception as e:
            self.logger.error(f"Error opening browser: {e}")
            return False
    
    def _search_query(self, context: Dict[str, Any]) -> bool:
        """Search web."""
        try:
            from legacy.actions import search_web
            query = context.get("query", "")
            return search_web(query)
        except Exception as e:
            self.logger.error(f"Error searching web: {e}")
            return False
    
    def _search_tutorial(self, context: Dict[str, Any]) -> bool:
        """Search for tutorial."""
        context["query"] = "programming tutorial"
        return self._search_query(context)
    
    def _search_documentation(self, context: Dict[str, Any]) -> bool:
        """Search for documentation."""
        context["query"] = "documentation"
        return self._search_query(context)
    
    def _pause_video(self, context: Dict[str, Any]) -> bool:
        """Pause video."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("pause video")
        except Exception as e:
            self.logger.error(f"Error pausing video: {e}")
            return False
    
    def _play_video(self, context: Dict[str, Any]) -> bool:
        """Play video."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("play video")
        except Exception as e:
            self.logger.error(f"Error playing video: {e}")
            return False
    
    def _next_video(self, context: Dict[str, Any]) -> bool:
        """Next video."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("next video")
        except Exception as e:
            self.logger.error(f"Error going to next video: {e}")
            return False
    
    def _previous_video(self, context: Dict[str, Any]) -> bool:
        """Previous video."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("previous video")
        except Exception as e:
            self.logger.error(f"Error going to previous video: {e}")
            return False
    
    def _stop_video(self, context: Dict[str, Any]) -> bool:
        """Stop video."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("stop video")
        except Exception as e:
            self.logger.error(f"Error stopping video: {e}")
            return False
    
    def _mute_video(self, context: Dict[str, Any]) -> bool:
        """Mute video."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("mute video")
        except Exception as e:
            self.logger.error(f"Error muting video: {e}")
            return False
    
    def _unmute_video(self, context: Dict[str, Any]) -> bool:
        """Unmute video."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("unmute video")
        except Exception as e:
            self.logger.error(f"Error unmuting video: {e}")
            return False
    
    def _fullscreen_video(self, context: Dict[str, Any]) -> bool:
        """Fullscreen video."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("fullscreen video")
        except Exception as e:
            self.logger.error(f"Error fullscreen video: {e}")
            return False
    
    def _browser_back(self, context: Dict[str, Any]) -> bool:
        """Browser back."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("back")
        except Exception as e:
            self.logger.error(f"Error going back in browser: {e}")
            return False
    
    def _browser_forward(self, context: Dict[str, Any]) -> bool:
        """Browser forward."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("forward")
        except Exception as e:
            self.logger.error(f"Error going forward in browser: {e}")
            return False
    
    def _browser_refresh(self, context: Dict[str, Any]) -> bool:
        """Browser refresh."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("refresh")
        except Exception as e:
            self.logger.error(f"Error refreshing browser: {e}")
            return False
    
    def _browser_home(self, context: Dict[str, Any]) -> bool:
        """Browser home."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("home")
        except Exception as e:
            self.logger.error(f"Error going to browser home: {e}")
            return False
    
    def _browser_new_tab(self, context: Dict[str, Any]) -> bool:
        """Browser new tab."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("new tab")
        except Exception as e:
            self.logger.error(f"Error opening new tab: {e}")
            return False
    
    def _browser_close_tab(self, context: Dict[str, Any]) -> bool:
        """Browser close tab."""
        try:
            from legacy.actions import handle_browser_command
            return handle_browser_command("close tab")
        except Exception as e:
            self.logger.error(f"Error closing tab: {e}")
            return False
    
    def _close_distractions(self, context: Dict[str, Any]) -> bool:
        """Close distractions."""
        try:
            # Close common distraction apps
            distraction_apps = ["chrome", "youtube", "spotify", "discord"]
            from legacy.actions import close_app
            
            for app in distraction_apps:
                try:
                    close_app(app)
                except Exception as app_err:
                    self.logger.warning(f"[ExecutionEngine] Could not close distraction app '{app}': {app_err}")
            
            return True
        except Exception as e:
            self.logger.error(f"Error closing distractions: {e}")
            return False
    
    def _play_focus_music(self, context: Dict[str, Any]) -> bool:
        """Play focus music."""
        try:
            from legacy.skills import play_music
            return play_music()
        except Exception as e:
            self.logger.error(f"Error playing focus music: {e}")
            return False
    
    def _play_music(self, context: Dict[str, Any]) -> bool:
        """Play music."""
        try:
            from legacy.skills import play_music
            return play_music()
        except Exception as e:
            self.logger.error(f"Error playing music: {e}")
            return False
    
    def _set_reminder(self, context: Dict[str, Any]) -> bool:
        """Set reminder."""
        # This would need to be implemented with reminder integration
        return True
    
    def _confirm_action(self, context: Dict[str, Any]) -> bool:
        """Confirm action."""
        return True
    
    def _pause_media(self, context: Dict[str, Any]) -> bool:
        """Pause media."""
        return self._pause_video(context)
    
    def _play_media(self, context: Dict[str, Any]) -> bool:
        """Play media."""
        return self._play_video(context)
    
    def _next_media(self, context: Dict[str, Any]) -> bool:
        """Next media."""
        return self._next_video(context)
    
    def _previous_media(self, context: Dict[str, Any]) -> bool:
        """Previous media."""
        return self._previous_video(context)
    
    def _stop_media(self, context: Dict[str, Any]) -> bool:
        """Stop media."""
        return self._stop_video(context)
    
    def _mute_media(self, context: Dict[str, Any]) -> bool:
        """Mute media."""
        return self._mute_video(context)
    
    def _unmute_media(self, context: Dict[str, Any]) -> bool:
        """Unmute media."""
        return self._unmute_video(context)

# Global execution engine instance
_execution_engine = None

def get_execution_engine() -> ExecutionEngine:
    """Get the global execution engine instance."""
    global _execution_engine
    if _execution_engine is None:
        _execution_engine = ExecutionEngine()
    return _execution_engine

def reset_execution_engine():
    """Reset the global execution engine instance (for testing)."""
    global _execution_engine
    _execution_engine = None
