"""
NOVA Terminal Window
Dedicated terminal for live logs, command execution, and module management.
"""

import tkinter as tk
from tkinter import scrolledtext
import threading
import subprocess
import os
from datetime import datetime
import queue

# Debug logging
DEBUG = True
def log_debug(msg):
    if DEBUG:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [ASSISTANT_TERMINAL] {msg}")


# Color palette
C_BG = "#0b1a2a"
C_PANEL = "#112b3c"
C_INNER = "#0d2035"
C_GLOW = "#00f5ff"
C_GLOW_DIM = "#004d5a"
C_TEXT = "#c8eeff"
C_DIM = "#3a7080"
C_TITLE = "#00f5ff"
C_BTN_GRN = "#00c853"
C_BTN_BLU = "#0288d1"
C_ERR = "#cc0000"


class AssistantTerminal(tk.Toplevel):
    """
    Dedicated Assistant terminal window.
    Shows live logs and allows command execution.
    """
    
    def __init__(self, root):
        """Initialize terminal window."""
        super().__init__(root)
        try:
            from instance.config import settings as _cfg
            self.asst_name = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            self.asst_name = "Assistant"
        self.title(f"{self.asst_name} - Terminal")
        self.geometry("800x600")
        self.minsize(600, 400)
        self.configure(bg=C_BG)
        
        # Center window
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (800 // 2)
        y = (self.winfo_screenheight() // 2) - (600 // 2)
        self.geometry(f"800x600+{x}+{y}")
        
        self.root = root
        self.log_queue = queue.Queue()
        self.process = None
        
        # Build UI
        self._build_ui()
        
        # Start log refresh
        self._refresh_logs()
        
        log_debug("AssistantTerminal initialized")
    
    def _build_ui(self):
        """Build the terminal UI."""
        # Title
        title_frame = tk.Frame(self, bg=C_PANEL, height=50)
        title_frame.pack(fill=tk.X, padx=0, pady=0)
        
        title_label = tk.Label(
            title_frame,
            text=f"{getattr(self, 'asst_name', 'Assistant')} Terminal",
            bg=C_PANEL,
            fg=C_TITLE,
            font=("Segoe UI", 16, "bold")
        )
        title_label.pack(pady=10)
        
        # Main terminal area (scrolled text)
        self.terminal_text = scrolledtext.ScrolledText(
            self,
            bg=C_INNER,
            fg=C_TEXT,
            insertbackground=C_GLOW,
            font=("Courier New", 10),
            state=tk.NORMAL,
            wrap=tk.WORD
        )
        self.terminal_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Configure tags for different message types
        self.terminal_text.tag_config("info", foreground=C_TEXT)
        self.terminal_text.tag_config("success", foreground=C_BTN_GRN)
        self.terminal_text.tag_config("warning", foreground="#ff9800")
        self.terminal_text.tag_config("error", foreground=C_ERR)
        
        # Input area
        input_frame = tk.Frame(self, bg=C_PANEL, height=40)
        input_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Input label
        input_label = tk.Label(
            input_frame,
            text="Command:",
            bg=C_PANEL,
            fg=C_TEXT,
            font=("Segoe UI", 10)
        )
        input_label.pack(side=tk.LEFT, padx=(0, 8))
        
        # Input field
        self.input_field = tk.Entry(
            input_frame,
            bg=C_INNER,
            fg=C_TEXT,
            insertbackground=C_GLOW,
            font=("Segoe UI", 10)
        )
        self.input_field.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.input_field.bind("<Return>", self._on_input_enter)
        
        # Execute button
        exec_btn = tk.Button(
            input_frame,
            text="Execute",
            bg=C_BTN_BLU,
            fg="white",
            font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT,
            cursor="hand2",
            command=self._execute_command
        )
        exec_btn.pack(side=tk.RIGHT, padx=4)
        
        # Control buttons
        btn_frame = tk.Frame(self, bg=C_BG)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Clear button
        clear_btn = tk.Button(
            btn_frame,
            text="Clear",
            bg=C_GLOW_DIM,
            fg="white",
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            cursor="hand2",
            command=self._clear_terminal
        )
        clear_btn.pack(side=tk.LEFT, padx=4)
        
        # Reload modules button
        reload_btn = tk.Button(
            btn_frame,
            text="Reload Modules",
            bg=C_BTN_GRN,
            fg="white",
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            cursor="hand2",
            command=self._reload_modules
        )
        reload_btn.pack(side=tk.LEFT, padx=4)
        
        # Close button
        close_btn = tk.Button(
            btn_frame,
            text="Close",
            bg=C_ERR,
            fg="white",
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            cursor="hand2",
            command=self.destroy
        )
        close_btn.pack(side=tk.RIGHT, padx=4)
        
        # Welcome message
        _name = getattr(self, 'asst_name', 'Assistant')
        self._log(f"{_name} Terminal Started", "success")
        self._log("Type commands below. Use 'help' for available commands.", "info")
        self._log("", "info")
    
    def _log(self, message, tag="info"):
        """Add a log message to the terminal."""
        try:
            self.terminal_text.config(state=tk.NORMAL)
            self.terminal_text.insert(tk.END, message + "\n", tag)
            self.terminal_text.see(tk.END)
            self.terminal_text.config(state=tk.NORMAL)
        except:
            pass
    
    def _on_input_enter(self, event=None):
        """Handle Enter key in input field."""
        self._execute_command()
    
    def _execute_command(self):
        """Execute a command entered in the input field."""
        command = self.input_field.get().strip()
        if not command:
            return
        
        self.input_field.delete(0, tk.END)
        
        # Log the command
        self._log(f"> {command}", "info")
        
        # Handle built-in commands
        if command.lower() == "clear":
            self._clear_terminal()
            return
        elif command.lower() == "help":
            self._show_help()
            return
        elif command.lower() == "reload":
            self._reload_modules()
            return
        
        # Execute in background thread
        def _execute():
            try:
                # Execute command
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.stdout:
                    self._log(result.stdout.strip(), "success")
                if result.stderr:
                    self._log(result.stderr.strip(), "error")
                if result.returncode != 0:
                    self._log(f"Command failed with code {result.returncode}", "error")
            except subprocess.TimeoutExpired:
                self._log("Command timed out (10s limit)", "error")
            except Exception as e:
                self._log(f"Error: {str(e)}", "error")
        
        thread = threading.Thread(target=_execute, daemon=True)
        thread.start()
    
    def _clear_terminal(self):
        """Clear terminal contents."""
        try:
            self.terminal_text.config(state=tk.NORMAL)
            self.terminal_text.delete(1.0, tk.END)
            self.terminal_text.config(state=tk.NORMAL)
            self._log("Terminal cleared", "success")
        except:
            pass
    
    def _show_help(self):
        """Show help for available commands."""
        help_text = """
Available Commands:
  help              - Show this help
  clear             - Clear terminal
  reload            - Reload NOVA modules
  
System Commands (Windows):
  dir               - List files
  cd <path>         - Change directory
  tasklist          - List running processes
  
Python Commands:
  python -c "..."   - Execute Python code
  python script.py  - Run Python script
"""
        self._log(help_text, "info")
    
    def _reload_modules(self):
        """Reload assistant modules."""
        _name = getattr(self, 'asst_name', 'Assistant')
        self._log(f"Reloading {_name} modules...", "info")
        
        def _reload():
            try:
                import importlib
                import extensions.plugin_manager
                import extensions.ai_engine
                
                importlib.reload(extensions.plugin_manager)
                importlib.reload(extensions.ai_engine)
                
                self._log("Modules reloaded successfully", "success")
            except Exception as e:
                self._log(f"Module reload failed: {str(e)}", "error")
        
        thread = threading.Thread(target=_reload, daemon=True)
        thread.start()
    
    def _refresh_logs(self):
        """Refresh terminal logs (check queue periodically)."""
        try:
            while True:
                try:
                    message, tag = self.log_queue.get_nowait()
                    self._log(message, tag)
                except queue.Empty:
                    break
        except:
            pass
        
        # Schedule next refresh
        if self.winfo_exists():
            self.after(100, self._refresh_logs)
