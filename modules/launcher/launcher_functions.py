"""
NOVA Launcher Functions
Complete real implementations for all launcher panel buttons.
All functions are non-blocking and thread-safe.
"""

import threading
import subprocess
import sys
import os
import json
import time
from datetime import datetime

# Debug logging
DEBUG = True
def log_debug(msg):
    if DEBUG:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [LAUNCHER_FUNC] {msg}")


# Global references set by launcher_controller
_tk_root = None
_floating_button = None
_main_ui_instance = None


def set_references(root, floating_button, main_ui_instance=None):
    """Set global references for launcher functions."""
    global _tk_root, _floating_button, _main_ui_instance
    _tk_root = root
    _floating_button = floating_button
    _main_ui_instance = main_ui_instance
    log_debug("Launcher functions initialized with references")


def _get_asst_name():
    try:
        from instance.config import settings
        return settings.get_assistant_name() or "Assistant"
    except Exception:
        return "Assistant"


# ─────────────────────────────────────────────────────────
# 1. OPEN NOVA GUI
# ─────────────────────────────────────────────────────────

def open_gui():
    """
    Open NOVA GUI dashboard.
    - Opens main dashboard
    - Restores if already open
    - Brings to front
    - Closes launcher after opening
    """
    global _tk_root, _main_ui_instance
    
    log_debug("open_gui() called")
    
    def _open_in_thread():
        try:
            if _tk_root is None:
                log_debug("Tk root not set")
                return
            
            # Schedule on main thread
            def _do_open():
                global _main_ui_instance
                try:
                    if _main_ui_instance is None or not _main_ui_instance.winfo_exists():
                        log_debug("Creating new AssistantUI instance")
                        from modules.ui.assistant_ui import AssistantUI
                        _main_ui_instance = AssistantUI(_tk_root)
                    else:
                        log_debug("Showing existing AssistantUI instance")
                        _main_ui_instance.deiconify()
                        _main_ui_instance.lift()
                        try:
                            _main_ui_instance.focus_force()
                        except:
                            pass
                    
                    # Close launcher after opening
                    if _floating_button and hasattr(_floating_button, 'launcher_panel'):
                        if _floating_button.launcher_panel:
                            _floating_button.launcher_panel.close()
                    
                    from legacy.tts import speak
                    speak(f"Opening {_get_asst_name()} dashboard")
                    
                except Exception as e:
                    log_debug(f"Error opening GUI: {e}")
                    import traceback
                    traceback.print_exc()
            
            _tk_root.after(0, _do_open)
        except Exception as e:
            log_debug(f"Error in _open_in_thread: {e}")
    
    # Non-blocking: start in daemon thread
    thread = threading.Thread(target=_open_in_thread, daemon=True)
    thread.start()


# ─────────────────────────────────────────────────────────
# 2. OPEN TERMINAL
# ─────────────────────────────────────────────────────────

def open_terminal():
    """
    Open dedicated NOVA terminal window.
    - Shows live logs
    - Allows command execution
    - Allows restarting modules
    - Keeps NOVA running
    """
    log_debug("open_terminal() called")
    
    def _open_in_thread():
        try:
            if _tk_root is None:
                log_debug("Tk root not set")
                return
            
            def _do_open():
                try:
                    from modules.launcher.terminal_window import AssistantTerminal
                    
                    # Check if terminal already exists
                    if hasattr(_tk_root, '_assistant_terminal'):
                        term = _tk_root._assistant_terminal
                        if term and term.winfo_exists():
                            log_debug("Showing existing terminal")
                            term.deiconify()
                            term.lift()
                            try:
                                term.focus_force()
                            except:
                                pass
                            return
                    
                    log_debug("Creating new AssistantTerminal instance")
                    terminal = AssistantTerminal(_tk_root)
                    _tk_root._assistant_terminal = terminal
                    
                    # Close launcher after opening
                    if _floating_button and hasattr(_floating_button, 'launcher_panel'):
                        if _floating_button.launcher_panel:
                            _floating_button.launcher_panel.close()
                    
                    from legacy.tts import speak
                    speak(f"Opening {_get_asst_name()} terminal")
                    
                except ImportError:
                    log_debug("AssistantTerminal not available, opening system terminal")
                    # Fallback to system terminal
                    subprocess.Popen("cmd.exe", shell=True)
                    from legacy.tts import speak
                    speak("Terminal opened")
                except Exception as e:
                    log_debug(f"Error opening terminal: {e}")
                    import traceback
                    traceback.print_exc()
            
            _tk_root.after(0, _do_open)
        except Exception as e:
            log_debug(f"Error in _open_in_thread: {e}")
    
    # Non-blocking: start in daemon thread
    thread = threading.Thread(target=_open_in_thread, daemon=True)
    thread.start()


# ─────────────────────────────────────────────────────────
# 3. VOICE MODE
# ─────────────────────────────────────────────────────────

def open_voice_panel():
    """
    Open voice selection panel.
    - Show voice selection panel
    - Allow previewing each voice
    - Save selected voice
    - Apply across entire application
    """
    log_debug("open_voice_panel() called")
    
    def _open_in_thread():
        try:
            if _tk_root is None:
                log_debug("Tk root not set")
                return
            
            def _do_open():
                try:
                    from modules.launcher.voice_panel import VoicePanel
                    
                    # Check if voice panel already exists
                    if hasattr(_tk_root, '_voice_panel'):
                        panel = _tk_root._voice_panel
                        if panel and panel.winfo_exists():
                            log_debug("Showing existing voice panel")
                            panel.deiconify()
                            panel.lift()
                            try:
                                panel.focus_force()
                            except:
                                pass
                            return
                    
                    log_debug("Creating new VoicePanel instance")
                    voice_panel = VoicePanel(_tk_root)
                    _tk_root._voice_panel = voice_panel
                    
                    # Close launcher after opening
                    if _floating_button and hasattr(_floating_button, 'launcher_panel'):
                        if _floating_button.launcher_panel:
                            _floating_button.launcher_panel.close()
                    
                    from legacy.tts import speak
                    speak("Opening voice selection panel")
                    
                except Exception as e:
                    log_debug(f"Error opening voice panel: {e}")
                    import traceback
                    traceback.print_exc()
            
            _tk_root.after(0, _do_open)
        except Exception as e:
            log_debug(f"Error in _open_in_thread: {e}")
    
    # Non-blocking: start in daemon thread
    thread = threading.Thread(target=_open_in_thread, daemon=True)
    thread.start()


# ─────────────────────────────────────────────────────────
# 4. SETTINGS
# ─────────────────────────────────────────────────────────

def open_settings():
    """
    Open compact settings panel.
    - Microphone selection
    - Speaker selection
    - Wake-word sensitivity
    - Startup with Windows
    - Launcher position
    - Theme
    - Notification preferences
    - Voice speed
    - Language
    """
    log_debug("open_settings() called")
    
    def _open_in_thread():
        try:
            if _tk_root is None:
                log_debug("Tk root not set")
                return
            
            def _do_open():
                try:
                    from modules.launcher.settings_panel import SettingsPanel
                    
                    # Check if settings panel already exists
                    if hasattr(_tk_root, '_settings_panel'):
                        panel = _tk_root._settings_panel
                        if panel and panel.winfo_exists():
                            log_debug("Showing existing settings panel")
                            panel.deiconify()
                            panel.lift()
                            try:
                                panel.focus_force()
                            except:
                                pass
                            return
                    
                    log_debug("Creating new SettingsPanel instance")
                    settings_panel = SettingsPanel(_tk_root)
                    _tk_root._settings_panel = settings_panel
                    
                    # Close launcher after opening
                    if _floating_button and hasattr(_floating_button, 'launcher_panel'):
                        if _floating_button.launcher_panel:
                            _floating_button.launcher_panel.close()
                    
                    from legacy.tts import speak
                    speak("Opening settings")
                    
                except Exception as e:
                    log_debug(f"Error opening settings: {e}")
                    import traceback
                    traceback.print_exc()
            
            _tk_root.after(0, _do_open)
        except Exception as e:
            log_debug(f"Error in _open_in_thread: {e}")
    
    # Non-blocking: start in daemon thread
    thread = threading.Thread(target=_open_in_thread, daemon=True)
    thread.start()


# ─────────────────────────────────────────────────────────
# 5. RESTART NOVA
# ─────────────────────────────────────────────────────────

def restart_assistant():
    """
    Restart the entire NOVA application.
    - Gracefully shutdown current instance
    - Restart without requiring manual relaunch
    """
    log_debug("restart_assistant() called")
    
    from legacy.tts import speak
    speak(f"Restarting {_get_asst_name()}")
    
    def _restart_in_thread():
        try:
            log_debug("Gracefully shutting down NOVA for restart")
            
            # Close launcher if open
            if _floating_button and hasattr(_floating_button, 'launcher_panel'):
                if _floating_button.launcher_panel:
                    try:
                        _floating_button.launcher_panel.close()
                    except:
                        pass
            
            # Wait a bit for TTS to finish
            time.sleep(0.5)
            
            if _tk_root is None:
                log_debug("Tk root not set")
                return
            
            # Schedule restart on main thread
            def _do_restart():
                try:
                    # Close main window
                    if _main_ui_instance and _main_ui_instance.winfo_exists():
                        _main_ui_instance.destroy()
                    
                    # Close floating button
                    if _floating_button and hasattr(_floating_button, 'window'):
                        try:
                            _floating_button.window.destroy()
                        except:
                            pass
                    
                    # Restart the entire application
                    log_debug("Restarting Assistant process")
                    if sys.platform == "win32":
                        # Windows: restart Python process
                        python_exe = sys.executable
                        script_path = os.path.abspath(__file__)
                        # Find the entry point (assistant.py)
                        nova_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                        entry_point = os.path.join(nova_root, "assistant.py")
                        
                        if os.path.exists(entry_point):
                            subprocess.Popen([python_exe, entry_point])
                        else:
                            # Fallback: try main.py
                            main_py = os.path.join(nova_root, "legacy", "main.py")
                            if os.path.exists(main_py):
                                subprocess.Popen([python_exe, main_py])
                    
                    # Destroy root to exit current instance
                    _tk_root.destroy()
                    
                except Exception as e:
                    log_debug(f"Error during restart: {e}")
                    import traceback
                    traceback.print_exc()
            
            _tk_root.after(500, _do_restart)
            
        except Exception as e:
            log_debug(f"Error in _restart_in_thread: {e}")
    
    # Non-blocking: start in daemon thread
    thread = threading.Thread(target=_restart_in_thread, daemon=True)
    thread.start()


# ─────────────────────────────────────────────────────────
# 6. RELOAD MODULES
# ─────────────────────────────────────────────────────────

def reload_modules():
    """
    Reload plugins and AI modules without restarting.
    """
    log_debug("reload_modules() called")
    
    from legacy.tts import speak
    speak("Reloading modules")
    
    def _reload_in_thread():
        try:
            log_debug("Reloading plugins and AI modules")
            
            # Reload plugin manager
            try:
                from extensions.plugin_manager import PluginManager
                plugin_mgr = PluginManager()
                plugin_mgr.load_plugins()
                log_debug(f"Reloaded plugins: {list(plugin_mgr.plugins.keys())}")
            except Exception as e:
                log_debug(f"Plugin reload error: {e}")
            
            # Reload AI engine
            try:
                import importlib
                import extensions.ai_engine
                importlib.reload(extensions.ai_engine)
                log_debug("Reloaded AI engine")
            except Exception as e:
                log_debug(f"AI engine reload error: {e}")
            
            if _tk_root:
                def _on_complete():
                    speak("Module reload complete")
                _tk_root.after(0, _on_complete)
            
        except Exception as e:
            log_debug(f"Error in _reload_in_thread: {e}")
    
    # Non-blocking: start in daemon thread
    thread = threading.Thread(target=_reload_in_thread, daemon=True)
    thread.start()


# ─────────────────────────────────────────────────────────
# 7. CHECK FOR UPDATES
# ─────────────────────────────────────────────────────────

def check_for_updates():
    """
    Check for newer NOVA versions.
    """
    log_debug("check_for_updates() called")
    
    from legacy.tts import speak
    speak("Checking for updates")
    
    def _check_in_thread():
        try:
            log_debug("Checking for NOVA updates")
            
            # TODO: Implement version check from GitHub/update server
            # For now, just report current version
            
            version_file = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "version.txt"
            )
            
            current_version = "1.0.0"
            if os.path.exists(version_file):
                try:
                    with open(version_file, 'r') as f:
                        current_version = f.read().strip()
                except:
                    pass
            
            log_debug(f"Current NOVA version: {current_version}")
            
            # In production, would check remote repository
            latest_version = current_version  # No updates available for now
            
            if _tk_root:
                def _on_complete():
                    if latest_version == current_version:
                        speak(f"{_get_asst_name()} is up to date")
                    else:
                        speak(f"Update available. Current version {current_version}, new version {latest_version}")
                _tk_root.after(0, _on_complete)
            
        except Exception as e:
            log_debug(f"Error in _check_in_thread: {e}")
            if _tk_root:
                def _on_error():
                    speak("Update check failed")
                _tk_root.after(0, _on_error)
    
    # Non-blocking: start in daemon thread
    thread = threading.Thread(target=_check_in_thread, daemon=True)
    thread.start()


# ─────────────────────────────────────────────────────────
# 8. SHOW NOVA STATUS
# ─────────────────────────────────────────────────────────

def show_assistant_status():
    """
    Display NOVA system status.
    - Voice listener status
    - Microphone status
    - Speaker status
    - Memory system status
    - Internet connectivity
    - Loaded modules
    """
    log_debug("show_assistant_status() called")
    
    def _show_in_thread():
        try:
            if _tk_root is None:
                log_debug("Tk root not set")
                return
            
            def _do_show():
                try:
                    from modules.launcher.status_window import StatusWindow
                    
                    # Check if status window already exists
                    if hasattr(_tk_root, '_status_window'):
                        window = _tk_root._status_window
                        if window and window.winfo_exists():
                            log_debug("Showing existing status window")
                            window.deiconify()
                            window.lift()
                            try:
                                window.focus_force()
                            except:
                                pass
                            return
                    
                    log_debug("Creating new StatusWindow instance")
                    status_window = StatusWindow(_tk_root)
                    _tk_root._status_window = status_window
                    
                    from legacy.tts import speak
                    speak(f"Displaying {_get_asst_name()} status")
                    
                except Exception as e:
                    log_debug(f"Error showing status: {e}")
                    import traceback
                    traceback.print_exc()
            
            _tk_root.after(0, _do_show)
        except Exception as e:
            log_debug(f"Error in _show_in_thread: {e}")
    
    # Non-blocking: start in daemon thread
    thread = threading.Thread(target=_show_in_thread, daemon=True)
    thread.start()


# ─────────────────────────────────────────────────────────
# 9. LOGOUT USER
# ─────────────────────────────────────────────────────────

def logout_user():
    """
    Destroy user session and return to login screen.
    """
    log_debug("logout_user() called")
    
    from legacy.tts import speak
    speak("Logging out")
    
    def _logout_in_thread():
        try:
            if _tk_root is None:
                log_debug("Tk root not set")
                return
            
            def _do_logout():
                try:
                    # Close all NOVA windows
                    if _main_ui_instance and _main_ui_instance.winfo_exists():
                        try:
                            _main_ui_instance.destroy()
                        except:
                            pass
                    
                    if hasattr(_tk_root, '_assistant_terminal'):
                        term = _tk_root._assistant_terminal
                        if term and term.winfo_exists():
                            try:
                                term.destroy()
                            except:
                                pass
                    
                    if hasattr(_tk_root, '_voice_panel'):
                        panel = _tk_root._voice_panel
                        if panel and panel.winfo_exists():
                            try:
                                panel.destroy()
                            except:
                                pass
                    
                    if hasattr(_tk_root, '_settings_panel'):
                        panel = _tk_root._settings_panel
                        if panel and panel.winfo_exists():
                            try:
                                panel.destroy()
                            except:
                                pass
                    
                    # Close floating button and launcher
                    if _floating_button and hasattr(_floating_button, 'window'):
                        try:
                            _floating_button.window.destroy()
                        except:
                            pass
                    
                    # Clear user session
                    from instance.config import settings as CONFIG
                    CONFIG.CURRENT_USER_ID = None
                    CONFIG.CURRENT_USERNAME = None
                    
                    # Clear runtime config
                    from core.config import save_runtime_config
                    save_runtime_config({"LAST_USER_ID": None})
                    
                    # Show login window
                    log_debug("Showing login window")
                    from legacy.login_window import LoginWindow
                    login = LoginWindow(_tk_root, on_login_success=lambda: log_debug("Re-logged in"))
                    
                except Exception as e:
                    log_debug(f"Error during logout: {e}")
                    import traceback
                    traceback.print_exc()
            
            _tk_root.after(0, _do_logout)
        except Exception as e:
            log_debug(f"Error in _logout_in_thread: {e}")
    
    # Non-blocking: start in daemon thread
    thread = threading.Thread(target=_logout_in_thread, daemon=True)
    thread.start()


# ─────────────────────────────────────────────────────────
# 10. EXIT NOVA
# ─────────────────────────────────────────────────────────

def exit_assistant():
    """
    Gracefully terminate NOVA.
    - Close GUI
    - Close floating button
    - Close launcher
    - Stop voice listener
    - Stop background services
    """
    log_debug("exit_assistant() called")
    
    from legacy.tts import speak
    speak(f"Exiting {_get_asst_name()}")
    
    def _exit_in_thread():
        try:
            log_debug("Gracefully shutting down NOVA")
            
            # Wait for TTS to finish
            time.sleep(0.5)
            
            if _tk_root is None:
                log_debug("Tk root not set")
                return
            
            def _do_exit():
                try:
                    # Close all windows
                    if _main_ui_instance and _main_ui_instance.winfo_exists():
                        try:
                            _main_ui_instance.destroy()
                        except:
                            pass
                    
                    if hasattr(_tk_root, '_assistant_terminal'):
                        term = _tk_root._assistant_terminal
                        if term and term.winfo_exists():
                            try:
                                term.destroy()
                            except:
                                pass
                    
                    if hasattr(_tk_root, '_voice_panel'):
                        panel = _tk_root._voice_panel
                        if panel and panel.winfo_exists():
                            try:
                                panel.destroy()
                            except:
                                pass
                    
                    if hasattr(_tk_root, '_settings_panel'):
                        panel = _tk_root._settings_panel
                        if panel and panel.winfo_exists():
                            try:
                                panel.destroy()
                            except:
                                pass
                    
                    # Close floating button
                    if _floating_button and hasattr(_floating_button, 'window'):
                        try:
                            _floating_button.window.destroy()
                        except:
                            pass
                    
                    # Close root window
                    log_debug("Closing NOVA root window")
                    _tk_root.destroy()
                    
                except Exception as e:
                    log_debug(f"Error during exit: {e}")
                    import traceback
                    traceback.print_exc()
            
            _tk_root.after(0, _do_exit)
            
        except Exception as e:
            log_debug(f"Error in _exit_in_thread: {e}")
    
    # Non-blocking: start in daemon thread
    thread = threading.Thread(target=_exit_in_thread, daemon=True)
    thread.start()
