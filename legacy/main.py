# main.py
import os
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk
try:
    import customtkinter as ctk
    print("[GUI] CustomTkinter loaded successfully")
except ImportError as e:
    print(f"[GUI] CustomTkinter not available: {e}")
    print("[GUI] Falling back to standard Tkinter")
    ctk = None
from legacy.floating_button import FloatingButton
from instance.config import settings
from legacy.auth_helpers import try_restore_session
try:
    from legacy.login_window import LoginWindow
    print("[GUI] LoginWindow available")
except ImportError as e:
    print(f"[GUI] LoginWindow not available: {e}")
    LoginWindow = None
import legacy.tts as tts 

# Global references for components
bubble = None
hotword_thread = None
root = None
login_window_ref = None
main_ui_instance = None

def start_hotword_thread():
    """Start hotword listener in background thread with retry loop (no recursion)."""
    RETRY_DELAY = 3  # seconds between retries
    while True:
        try:
            from legacy.hotword_listener import start_hotword_service, run_hotword_loop
            
            print("[WAKE] Starting hotword service...")
            if start_hotword_service():
                print("[WAKE] Hotword service started successfully")
                print("[WAKE] Starting wake word detection loop...")
                run_hotword_loop()
            else:
                print("[WAKE] Hotword service failed, falling back to keyboard")
                from legacy.hotword_listener import keyboard_fallback
                keyboard_fallback()
                return  # keyboard_fallback is its own blocking loop; don't retry
                
        except KeyboardInterrupt:
            print("[WAKE] Hotword thread interrupted by user")
            return
        except Exception as e:
            print(f"[WAKE ERROR] Hotword thread crashed: {e}")
            import traceback
            traceback.print_exc()
        
        # Auto-restart after crash — loop instead of recursion
        print(f"[WAKE] Restarting hotword service in {RETRY_DELAY}s...")
        time.sleep(RETRY_DELAY)

def start_assistant_services():
    """
    Initialize and start all Assistant services after successful authentication.
    """
    global bubble, hotword_thread, root, main_ui_instance
    
    print("[SYSTEM] Starting Assistant services...")
    
    # 1. Create floating bubble (Tkinter Toplevel)
    # We pass root and user_data to it
    user_data = {
        'user_id': settings.CURRENT_USER_ID,
        'username': settings.CURRENT_USERNAME
    }
    # Pass launch_ui as a callback for double-click
    bubble = FloatingButton(root, user_data, on_double_click_cb=launch_ui)
    
    # 2. Expose bubble to tts so other threads can pulse it safely
    tts.floating_ref = bubble
    
    # 3. Store floating button reference on root for later access
    root._floating_button = bubble
    
    # 4. Initialize launcher functions with references
    try:
        from modules.launcher.launcher_functions_simple import set_references
        set_references(root, main_ui_instance)
        print("[SYSTEM] Launcher functions initialized")
    except Exception as e:
        print(f"[SYSTEM] Failed to initialize launcher functions: {e}")
    
    # 5. Start hotword listener in background thread (daemon so app exits cleanly)
    print("[SYSTEM] Starting hotword listener thread...")
    hotword_thread = threading.Thread(target=start_hotword_thread, daemon=True)
    hotword_thread.start()
    
    # 6. Initialize shutdown manager with references for logout/exit
    try:
        from modules.launcher.shutdown_manager import set_references as set_shutdown_references
        set_shutdown_references(
            root=root,
            floating_button=bubble,
            launcher_panel=bubble.launcher_panel,  # May be None initially, will be created on first double-click
            main_ui_instance=main_ui_instance,
            hotword_thread=hotword_thread
        )
        print("[SYSTEM] Shutdown manager initialized")
    except Exception as e:
        print(f"[SYSTEM] Failed to initialize shutdown manager: {e}")
    
    # 7. Start proactive interaction monitoring
    try:
        from legacy.proactive_interaction import start_proactive_interaction
        start_proactive_interaction()
        print("[Proactive Interaction] Started with random 20-30 min idle timer")
    except Exception as e:
        print(f"[Proactive Interaction] Failed to start: {e}")
    
    print("[SYSTEM] All Assistant services started successfully.")

def launch_ui():
    """
    Launch or show the main Assistant UI window.
    Ensures only one instance exists.
    """
    global main_ui_instance, root
    
    if main_ui_instance is None or not main_ui_instance.winfo_exists():
        print("[SYSTEM] Creating new UI instance...")
        from modules.ui.assistant_ui import AssistantUI
        main_ui_instance = AssistantUI(root)
        # Store reference on root for later access by shutdown manager
        # Store reference on root for later access by shutdown manager
        root._main_ui_instance = main_ui_instance
    else:
        print("[SYSTEM] Showing existing UI instance...")
        main_ui_instance.deiconify()
        main_ui_instance.lift()
        main_ui_instance.focus_force()

def main():
    """
    Main entry point for the Assistant.
    Handles login flow and service initialization using Tkinter.
    """
    global root
    
    # Initialize the ONE and ONLY Tk root
    root = tk.Tk()
    root.withdraw() # Hide the root window, we only want Toplevels
    
    # Pass root to TTS for thread-safe updates
    tts.set_root(root)
    
    print("[SYSTEM] Assistant starting (Tkinter mode)...")
    
    # Store startup callback on root for later use by shutdown_manager
    root._on_login_success_callback = start_assistant_services
    
    # Force login to always appear (disable auto session restore)
    force_login = True
    
    # Try to restore previous session only if force_login is False
    if not force_login:
        authenticated = try_restore_session()
    else:
        authenticated = False
    
    if authenticated:
        # Session restored successfully - start services directly
        print("[SYSTEM] Session restored. Starting services...")
        start_assistant_services()
    else:
        # Force login - always show login window
        print("[SYSTEM] Showing login window (auto restore disabled)...")
        # LoginWindow serves as the initial UI
        # Pass root and success callback
        global login_window_ref
        if LoginWindow is not None:
            login_window_ref = LoginWindow(root, on_login_success=start_assistant_services)
        else:
            print("[GUI] LoginWindow not available, starting services directly...")
            start_assistant_services()
    
    # Run Tkinter event loop
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("[SYSTEM] Shutdown requested via keyboard interrupt.")
        root.destroy()
        sys.exit(0)

if __name__ == "__main__":
    main()
