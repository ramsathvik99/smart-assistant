from extensions.launcher_engine import LauncherEngine
from modules.launcher.launcher_functions import (
    open_gui,
    open_terminal,
    open_voice_panel,
    open_settings,
    restart_assistant,
    reload_modules,
    check_for_updates,
    show_assistant_status,
    logout_user,
    exit_assistant,
    set_references
)

class LauncherController:
    """
    Main launcher controller for NOVA.
    Routes all launcher panel button clicks to appropriate functions.
    """
    def __init__(self):
        self.engine = LauncherEngine()
        
        # Function routing map
        self.functions = {
            'open_gui': open_gui,
            'open_terminal': open_terminal,
            'open_voice_panel': open_voice_panel,
            'open_settings': open_settings,
            'restart_assistant': restart_assistant,
            'reload_modules': reload_modules,
            'check_for_updates': check_for_updates,
            'show_assistant_status': show_assistant_status,
            'logout_user': logout_user,
            'exit_assistant': exit_assistant,
        }
    
    def initialize(self, root, floating_button, main_ui_instance=None):
        """Initialize launcher controller with references."""
        set_references(root, floating_button, main_ui_instance)
    
    def execute_launcher_item(self, item_id):
        """
        Execute a launcher item by ID.
        
        Args:
            item_id: Launcher item identifier (e.g., 'open_gui', 'open_terminal')
        """
        if item_id in self.functions:
            func = self.functions[item_id]
            func()
        else:
            print(f"[LAUNCHER_CONTROLLER] Unknown item: {item_id}")
    
    def launch_app(self, app_name):
        """App launching (legacy compatibility)."""
        return self.engine.launch_app(app_name)
    
    def handle_context_action(self, app_name, action, text):
        """Handle context actions (legacy compatibility)."""
        return self.engine.handle_app_context_action(app_name, action, text)

# Singleton
_launcher = None
def get_launcher():
    global _launcher
    if not _launcher:
        _launcher = LauncherController()
    return _launcher

def open_app(text):
    """
    open app
    launch application
    start program
    open
    launch
    """
    # extract intent from 'open spotify' -> 'spotify'
    # text is usually the full command input
    # Need to parse? usually command routing handles this but registry.py 
    # executes command.function(text=input)
    
    # We strip the "open" part loosely or pass to launch_app which cleans it
    clean_name = text.lower().replace("open", "").replace("launch", "").replace("start", "").strip()
    if clean_name:
        get_launcher().launch_app(clean_name)
    else:
        # Prompt user
        from legacy.tts import speak
        speak("What application would you like to open?")

