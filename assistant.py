# assistant.py
import sys
print("[DEBUG] Running Python:", sys.executable)
import os
import time
import signal
import threading
from pathlib import Path
from dotenv import load_dotenv

# PROJECT ROOT - Set before any other imports
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CURRENT_DIR = PROJECT_ROOT

# Global reference to orchestrator for shutdown
orchestrator = None
gui_thread = None

# Global shutdown manager instance
from extensions.system.shutdown_manager import ShutdownManager
shutdown_manager = ShutdownManager()


def start_assistant_backend():
    """Start backend only (GUI decoupled)"""
    global orchestrator
    
    print("[LAUNCHER] Starting backend...")
    
    # Initialize core services
    initialize_core()
    
    # Load environment variables: root .env first, then legacy/.env (legacy overrides)
    root_env_path = PROJECT_ROOT / '.env'
    legacy_env_path = PROJECT_ROOT / 'legacy' / '.env'
    load_dotenv(root_env_path)
    load_dotenv(legacy_env_path, override=True)
    print(f"[LAUNCHER] Loaded environment from: {root_env_path} and {legacy_env_path}")
    
    # Ensure proper directories are in sys.path
    root_dir = PROJECT_ROOT
    legacy_dir = PROJECT_ROOT / "legacy"
    extensions_dir = PROJECT_ROOT / "extensions"
    core_dir = PROJECT_ROOT / "core"
    communication_dir = PROJECT_ROOT / "communication"
    commands_dir = PROJECT_ROOT / "commands"
    skills_dir = PROJECT_ROOT / "skills"
    tools_dir = PROJECT_ROOT / "tools"
    
    for directory in [root_dir, legacy_dir, extensions_dir, core_dir, communication_dir, commands_dir, skills_dir, tools_dir]:
        if directory not in sys.path:
            sys.path.insert(0, directory)

    try:
        # Change CWD to legacy directory early
        # This ensures legacy relative paths (config, db, assets) work correctly
        import os
        os.chdir(legacy_dir)
        
        # Import consolidated config early to establish shared state
        from instance.config import settings
        
        # Import Orchestrator from extensions but don't start legacy GUI
        from extensions.assistant_orchestrator import AssistantOrchestrator
        orchestrator = AssistantOrchestrator()
        
        # Register signal handler for graceful shutdown
        signal.signal(signal.SIGINT, signal_handler)
        
        # Initialize orchestrator
        initialize_orchestrator()
        
        # Start orchestrator services in background thread
        orchestrator_thread = threading.Thread(target=orchestrator.start, daemon=True)
        orchestrator_thread.start()
        print("[LAUNCHER] Orchestrator started in background thread")
        
        # Keep-alive loop - prevents assistant.py from exiting
        print("[LAUNCHER] Backend is now running. Press Ctrl+C to shutdown.")
        print("[LAUNCHER] GUI can be launched via floating button double-click.")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[LAUNCHER] Shutdown requested via keyboard interrupt.")
            shutdown()
            
    except ImportError as e:
        print(f"[LAUNCHER FATAL] Failed to import extensions: {e}")
        print("Please ensure the 'extensions' directory exists and contains 'assistant_orchestrator.py'.")
        sys.exit(1)
    except Exception as e:
        print(f"[LAUNCHER FATAL] An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
        shutdown()
        sys.exit(1)
    finally:
        # Ensure cleanup happens even if something goes wrong
        shutdown()

def initialize_core():
    """Initialize core services with explicit lifecycle"""
    print("[LAUNCHER] Initializing core services...")
    
    # Use explicit initialization manager
    try:
        from extensions.system.initialization_manager import startup as init_startup
        init_startup()
        print("[LAUNCHER] ✅ Core services initialized")
    except Exception as e:
        print(f"[LAUNCHER] CRITICAL: Core services initialization failed: {e}")
        raise

def initialize_orchestrator():
    """Initialize orchestrator"""
    global orchestrator
    print("[LAUNCHER] Initializing orchestrator...")
    # This will be handled in main() function
    pass

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    print("\n[LAUNCHER] Shutdown signal received...")
    shutdown()
    sys.exit(0)

def shutdown():
    """Enhanced graceful shutdown of services"""
    global orchestrator
    
    # Use explicit initialization manager for clean shutdown
    try:
        from extensions.system.initialization_manager import shutdown as init_shutdown
        init_shutdown()
    except Exception as e:
        print(f"[LAUNCHER] Initialization manager shutdown error: {e}")
    
    if orchestrator:
        try:
            print("[LAUNCHER] Initiating orchestrator shutdown...")
            orchestrator.cleanup_and_shutdown()
        except Exception as e:
            print(f"[LAUNCHER] Error during orchestrator shutdown: {e}")
    
    print("[LAUNCHER] ✅ Shutdown complete")
    sys.exit(0)

def start_assistant():
    """Start Assistant with GUI support"""
    global orchestrator
    
    print("[LAUNCHER] Starting Assistant with Intelligence Extensions...")
    
    # Initialize core services
    initialize_core()
    
    # Load environment variables: root .env first, then legacy/.env (legacy overrides)
    root_env_path = PROJECT_ROOT / '.env'
    legacy_env_path = PROJECT_ROOT / 'legacy' / '.env'
    load_dotenv(root_env_path)
    load_dotenv(legacy_env_path, override=True)
    print(f"[LAUNCHER] Loaded environment from: {root_env_path} and {legacy_env_path}")
    
    # Ensure proper directories are in sys.path
    root_dir = PROJECT_ROOT
    legacy_dir = PROJECT_ROOT / "legacy"
    extensions_dir = PROJECT_ROOT / "extensions"
    core_dir = PROJECT_ROOT / "core"
    communication_dir = PROJECT_ROOT / "communication"
    commands_dir = PROJECT_ROOT / "commands"
    skills_dir = PROJECT_ROOT / "skills"
    tools_dir = PROJECT_ROOT / "tools"
    
    for directory in [root_dir, legacy_dir, extensions_dir, core_dir, communication_dir, commands_dir, skills_dir, tools_dir]:
        if directory not in sys.path:
            sys.path.insert(0, directory)

    try:
        # Change CWD to legacy directory early
        # This ensures legacy relative paths (config, db, assets) work correctly
        import os
        os.chdir(legacy_dir)
        
        # Import consolidated config early to establish shared state
        from instance.config import settings
        
        # Import Orchestrator from extensions and attach to assistant
        # Initialize Orchestrator from extensions and attach to assistant
        from legacy import assistant
        from extensions.assistant_orchestrator import AssistantOrchestrator
        orchestrator = AssistantOrchestrator()
        assistant.orchestrator = orchestrator
        
        # --- INITIALIZE UNIFIED ROUTING ---
        initialize_unified_routing()
        
        # Register signal handler for graceful shutdown
        signal.signal(signal.SIGINT, signal_handler)
        
        # Initialize orchestrator
        initialize_orchestrator()
        
        # GUI is now decoupled - launch only via floating button double-click
        print("[LAUNCHER] GUI decoupled. Use floating button double-click to launch.")
        
        # Start the orchestrator (this runs legacy.main as a module)
        print("[LAUNCHER] Starting orchestrator...")
        orchestrator.start()
        print("[LAUNCHER] ✅ Orchestrator started successfully")
        
        # Keep-alive loop - prevents assistant.py from exiting
        print("[LAUNCHER] Assistant is now running. Press Ctrl+C to shutdown.")
        print("[LAUNCHER] Entering keep-alive loop...")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[LAUNCHER] Shutdown requested via keyboard interrupt.")
            shutdown()
            
    except ImportError as e:
        print(f"[LAUNCHER FATAL] Failed to import extensions: {e}")
        print("Please ensure the 'extensions' directory exists and contains 'assistant_orchestrator.py'.")
        sys.exit(1)
    except Exception as e:
        print(f"[LAUNCHER FATAL] An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
        shutdown()
        sys.exit(1)
    finally:
        # Ensure cleanup happens even if something goes wrong
        shutdown()

def initialize_unified_routing():
    """
    CRITICAL: Unified Command Router is now natively integrated into assistant.process_input.
    No monkey patching is required.
    """
    print("[UNIFIED ROUTER] Native Single Execution Path Enforced")

def main():
    """Main entry point for Assistant - complete system with GUI"""
    print("[ASSISTANT] Starting complete system...")
    
    # Initialize environment
    initialize_backend_only()
    
    # Initialize Unified Routing
    initialize_unified_routing()

    print("[ASSISTANT] Running system entry point...")
    from legacy.main import main as legacy_main
    legacy_main()

    # Keep application running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[ASSISTANT] Shutdown requested.")
        shutdown()


def initialize_environment():
    """Initialize environment and paths"""
    print("[LAUNCHER] Initializing environment...")
    
    # Load environment variables
    root_env_path = PROJECT_ROOT / '.env'
    legacy_env_path = PROJECT_ROOT / 'legacy' / '.env'
    load_dotenv(root_env_path)
    load_dotenv(legacy_env_path, override=True)
    print(f"[LAUNCHER] Loaded environment from: {root_env_path} and {legacy_env_path}")
    
    # Ensure proper directories are in sys.path
    directories = [
        PROJECT_ROOT,
        PROJECT_ROOT / "legacy",
        PROJECT_ROOT / "extensions", 
        PROJECT_ROOT / "core",
        PROJECT_ROOT / "communication",
        PROJECT_ROOT / "commands",
        PROJECT_ROOT / "skills",
        PROJECT_ROOT / "tools"
    ]
    
    for directory in directories:
        if directory not in sys.path:
            sys.path.insert(0, directory)

def initialize_backend_only():
    """Initialize backend environment without starting background threads"""
    print("[ASSISTANT] Initializing backend environment...")
    
    # Load environment variables
    root_env_path = PROJECT_ROOT / '.env'
    legacy_env_path = PROJECT_ROOT / 'legacy' / '.env'
    load_dotenv(root_env_path)
    load_dotenv(legacy_env_path, override=True)
    
    # Standard sys.path setup
    paths = [PROJECT_ROOT, PROJECT_ROOT / "legacy", PROJECT_ROOT / "extensions"]
    for p in paths:
        if str(p) not in sys.path: sys.path.insert(0, str(p))
    
    # Change CWD to legacy directory
    import os
    os.chdir(PROJECT_ROOT / "legacy")
    print("[ASSISTANT] Environment Ready")

def start_backend():
    """Start backend only (GUI decoupled)"""
    global orchestrator
    
    print("[ASSISTANT] Initializing backend core...")
    initialize_backend_only()

    try:
        from extensions.assistant_orchestrator import AssistantOrchestrator
        orchestrator = AssistantOrchestrator()
        
        # Initialize Unified Routing
        initialize_unified_routing()
        
        signal.signal(signal.SIGINT, signal_handler)
        initialize_orchestrator()
        
        orchestrator_thread = threading.Thread(target=orchestrator.start, daemon=True)
        orchestrator_thread.start()
        print("[ASSISTANT] Backend services started")
        
    except Exception as e:
        print(f"[ASSISTANT] Failed to start backend: {e}")
        shutdown()
        sys.exit(1)

if __name__ == "__main__":
    main()
