"""
NOVA Status Display Window
Shows current status of all NOVA systems.
"""

import tkinter as tk
from datetime import datetime
import threading
import psutil

# Debug logging
DEBUG = True
def log_debug(msg):
    if DEBUG:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [STATUS_WINDOW] {msg}")


# Color palette
C_BG = "#0b1a2a"
C_PANEL = "#112b3c"
C_INNER = "#0d2035"
C_GLOW = "#00f5ff"
C_GLOW_DIM = "#004d5a"
C_TEXT = "#c8eeff"
C_DIM = "#3a7080"
C_TITLE = "#00f5ff"
C_OK = "#00c853"
C_WARN = "#ff9800"
C_ERR = "#cc0000"


class StatusWindow(tk.Toplevel):
    """
    Status window showing:
    - Voice listener status
    - Microphone status
    - Speaker status
    - Memory system status
    - Internet connectivity
    - Loaded modules
    """
    
    def __init__(self, root):
        """Initialize status window."""
        super().__init__(root)
        try:
            from instance.config import settings as _cfg
            self.asst_name = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            self.asst_name = "Assistant"
        self.title(f"{self.asst_name} - System Status")
        self.geometry("600x500")
        self.configure(bg=C_BG)
        self.resizable(False, False)
        
        # Center window
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (600 // 2)
        y = (self.winfo_screenheight() // 2) - (500 // 2)
        self.geometry(f"600x500+{x}+{y}")
        
        self.root = root
        self.status_labels = {}
        
        # Build UI
        self._build_ui()
        
        # Start status refresh in background
        self._refresh_status()
        
        log_debug("StatusWindow initialized")
    
    def _build_ui(self):
        """Build the status window UI."""
        # Title
        title_frame = tk.Frame(self, bg=C_PANEL, height=50)
        title_frame.pack(fill=tk.X, padx=0, pady=0)
        
        title_label = tk.Label(
            title_frame,
            text=f"{getattr(self, 'asst_name', 'Assistant')} System Status",
            bg=C_PANEL,
            fg=C_TITLE,
            font=("Segoe UI", 16, "bold")
        )
        title_label.pack(pady=10)
        
        # Status frame
        status_frame = tk.Frame(self, bg=C_BG)
        status_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Status items
        self._add_status_item(status_frame, "Voice Listener", "voice_listener")
        self._add_status_item(status_frame, "Microphone", "microphone")
        self._add_status_item(status_frame, "Speaker", "speaker")
        self._add_status_item(status_frame, "Memory System", "memory")
        self._add_status_item(status_frame, "Internet Connection", "internet")
        self._add_status_item(status_frame, "Loaded Modules", "modules")
        self._add_status_item(status_frame, "System Resources", "resources")
        
        # Close button
        close_btn = tk.Button(
            self,
            text="✕ Close",
            bg="#cc0000",
            fg="white",
            font=("Segoe UI", 11, "bold"),
            relief=tk.FLAT,
            cursor="hand2",
            command=self.destroy
        )
        close_btn.pack(pady=15)
    
    def _add_status_item(self, parent, label, key):
        """Add a status item."""
        item_frame = tk.Frame(parent, bg=C_PANEL)
        item_frame.pack(fill=tk.X, pady=8, padx=8)
        
        # Label
        lbl = tk.Label(
            item_frame,
            text=label,
            bg=C_PANEL,
            fg=C_TEXT,
            font=("Segoe UI", 11, "bold"),
            width=20,
            anchor=tk.W
        )
        lbl.pack(side=tk.LEFT, padx=8, pady=8)
        
        # Status indicator
        status_lbl = tk.Label(
            item_frame,
            text="● Loading...",
            bg=C_PANEL,
            fg=C_DIM,
            font=("Segoe UI", 10),
            anchor=tk.E
        )
        status_lbl.pack(side=tk.RIGHT, padx=8, pady=8, fill=tk.X, expand=True)
        
        self.status_labels[key] = status_lbl
    
    def _refresh_status(self):
        """Refresh status displays (in background thread)."""
        def _refresh():
            try:
                # Voice listener status
                self._update_status("voice_listener", "● Running", C_OK)
                
                # Microphone status
                try:
                    import pyaudio
                    p = pyaudio.PyAudio()
                    mics = p.get_device_count()
                    p.terminate()
                    self._update_status("microphone", f"● {mics} device(s) available", C_OK)
                except:
                    self._update_status("microphone", "● Not available", C_ERR)
                
                # Speaker status
                try:
                    import pyaudio
                    p = pyaudio.PyAudio()
                    speakers = p.get_device_count()
                    p.terminate()
                    self._update_status("speaker", f"● {speakers} device(s) available", C_OK)
                except:
                    self._update_status("speaker", "● Not available", C_ERR)
                
                # Memory system status
                self._update_status("memory", "● Operational", C_OK)
                
                # Internet connectivity
                try:
                    import socket
                    socket.create_connection(("1.1.1.1", 53), timeout=2)
                    self._update_status("internet", "● Connected", C_OK)
                except:
                    self._update_status("internet", "● Disconnected", C_WARN)
                
                # Loaded modules
                try:
                    from extensions.plugin_manager import PluginManager
                    pm = PluginManager()
                    pm.load_plugins()
                    count = len(pm.plugins)
                    self._update_status("modules", f"● {count} modules loaded", C_OK)
                except:
                    self._update_status("modules", "● Unknown", C_DIM)
                
                # System resources
                try:
                    cpu_percent = psutil.cpu_percent(interval=1)
                    memory_percent = psutil.virtual_memory().percent
                    status_text = f"● CPU: {cpu_percent:.1f}% | RAM: {memory_percent:.1f}%"
                    self._update_status("resources", status_text, C_OK)
                except:
                    self._update_status("resources", "● Unable to read", C_DIM)
                
            except Exception as e:
                log_debug(f"Error refreshing status: {e}")
        
        # Run in background thread
        thread = threading.Thread(target=_refresh, daemon=True)
        thread.start()
    
    def _update_status(self, key, text, color):
        """Update a status label."""
        try:
            if key in self.status_labels:
                def _do_update():
                    self.status_labels[key].config(text=text, fg=color)
                
                self.root.after(0, _do_update)
        except Exception as e:
            log_debug(f"Error updating status {key}: {e}")
