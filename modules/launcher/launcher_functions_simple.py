"""
NOVA Launcher Functions - Simplified
Simple, non-blocking implementations for launcher buttons.
"""

import threading
import subprocess
import sys
import os
import time
from datetime import datetime

# Debug logging
DEBUG = True
def log_debug(msg):
    if DEBUG:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [LAUNCHER_FUNC] {msg}")


# Global references
_tk_root = None
_main_ui_instance = None


def set_references(root, main_ui_instance=None):
    """Set global references."""
    global _tk_root, _main_ui_instance
    _tk_root = root
    _main_ui_instance = main_ui_instance
    log_debug("Launcher functions initialized")


# ─────────────────────────────────────────────────────────
# 1. OPEN GUI
# ─────────────────────────────────────────────────────────

def open_gui():
    """Open NOVA GUI dashboard."""
    log_debug("open_gui() called")
    
    if _tk_root is None:
        log_debug("No tk_root, cannot open GUI")
        return
    
    def _do_open():
        global _main_ui_instance
        try:
            if _main_ui_instance is None or not _main_ui_instance.winfo_exists():
                log_debug("Creating new AssistantUI")
                from modules.ui.assistant_ui import AssistantUI
                _main_ui_instance = AssistantUI(_tk_root)
            else:
                log_debug("Restoring existing AssistantUI")
                _main_ui_instance.deiconify()
                _main_ui_instance.lift()
                try:
                    _main_ui_instance.focus_force()
                except:
                    pass
            
            try:
                from instance.config import settings as _cfg
                _asst = _cfg.get_assistant_name() or "Assistant"
            except Exception:
                _asst = "Assistant"
            from legacy.tts import speak
            speak(f"Opening {_asst} dashboard")
        except Exception as e:
            log_debug(f"Error opening GUI: {e}")
    
    # Schedule on main thread
    _tk_root.after(0, _do_open)


# ─────────────────────────────────────────────────────────
# 2. OPEN TERMINAL
# ─────────────────────────────────────────────────────────

def open_terminal():
    """Open NOVA terminal."""
    log_debug("open_terminal() called")
    
    if _tk_root is None:
        log_debug("No tk_root")
        return
    
    def _do_open():
        try:
            # Check if terminal already open
            if hasattr(_tk_root, '_assistant_terminal'):
                term = _tk_root._assistant_terminal
                if term and term.winfo_exists():
                    log_debug("Terminal already open, showing")
                    term.deiconify()
                    term.lift()
                    return
            
            # Create new terminal
            log_debug("Creating new terminal")
            from modules.launcher.terminal_window import AssistantTerminal
            terminal = AssistantTerminal(_tk_root)
            _tk_root._assistant_terminal = terminal
            
            from legacy.tts import speak
            speak("Opening terminal")
        except Exception as e:
            log_debug(f"Error opening terminal: {e}")
            import traceback
            traceback.print_exc()
    
    # Schedule on main thread
    _tk_root.after(0, _do_open)


# ─────────────────────────────────────────────────────────
# 3. VOICE MODE
# ─────────────────────────────────────────────────────────

def open_voice_panel():
    """Open voice selection panel."""
    log_debug("open_voice_panel() called")
    
    if _tk_root is None:
        log_debug("No tk_root")
        return
    
    def _do_open():
        try:
            # Check if voice panel already open
            if hasattr(_tk_root, '_voice_panel'):
                panel = _tk_root._voice_panel
                if panel and panel.winfo_exists():
                    log_debug("Voice panel already open")
                    panel.deiconify()
                    panel.lift()
                    return
            
            # Create new voice panel
            log_debug("Creating new voice panel")
            from modules.launcher.voice_panel import VoicePanel
            voice_panel = VoicePanel(_tk_root)
            _tk_root._voice_panel = voice_panel
            
            from legacy.tts import speak
            speak("Opening voice selection")
        except Exception as e:
            log_debug(f"Error opening voice panel: {e}")
            import traceback
            traceback.print_exc()
    
    # Schedule on main thread
    _tk_root.after(0, _do_open)


# ─────────────────────────────────────────────────────────
# 4. SETTINGS
# ─────────────────────────────────────────────────────────

def open_settings():
    """Open settings panel."""
    log_debug("open_settings() called")
    
    if _tk_root is None:
        log_debug("No tk_root")
        return
    
    def _do_open():
        try:
            # Check if settings panel already open
            if hasattr(_tk_root, '_settings_panel'):
                panel = _tk_root._settings_panel
                if panel and panel.winfo_exists():
                    log_debug("Settings panel already open")
                    panel.deiconify()
                    panel.lift()
                    return
            
            # Create new settings panel
            log_debug("Creating new settings panel")
            from modules.launcher.settings_panel import SettingsPanel
            settings_panel = SettingsPanel(_tk_root)
            _tk_root._settings_panel = settings_panel
            
            from legacy.tts import speak
            speak("Opening settings")
        except Exception as e:
            log_debug(f"Error opening settings: {e}")
            import traceback
            traceback.print_exc()
    
    # Schedule on main thread
    _tk_root.after(0, _do_open)
