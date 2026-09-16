"""
Settings Panel for NOVA
Compact settings interface with all user preferences.
Settings are saved persistently to instance/user_settings.json
"""

import tkinter as tk
from tkinter import ttk
import json
import os
from datetime import datetime

# Debug logging
DEBUG = True
def log_debug(msg):
    if DEBUG:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [SETTINGS_PANEL] {msg}")


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


# Default settings
DEFAULT_SETTINGS = {
    "microphone": "Default",
    "speaker": "Default",
    "wake_word_sensitivity": 0.5,
    "startup_with_windows": False,
    "launcher_position": "center",
    "theme": "dark",
    "notifications_enabled": True,
    "voice_speed": 150,
    "language": "en-US"
}


class SettingsPanel(tk.Toplevel):
    """
    Settings panel for NOVA.
    Allows customization of:
    - Microphone
    - Speaker
    - Wake-word sensitivity
    - Startup with Windows
    - Launcher position
    - Theme
    - Notification preferences
    - Voice speed
    - Language
    """
    
    def __init__(self, root):
        """Initialize settings panel."""
        super().__init__(root)
        try:
            from instance.config import settings as _cfg
            self.asst_name = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            self.asst_name = "Assistant"
        self.title(f"{self.asst_name} - Settings")
        self.geometry("650x800")
        self.configure(bg=C_BG)
        self.resizable(False, False)
        
        # Center window
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (650 // 2)
        y = (self.winfo_screenheight() // 2) - (800 // 2)
        self.geometry(f"650x800+{x}+{y}")
        
        self.root = root
        self.settings = {}
        self.setting_widgets = {}
        
        # Load settings
        self._load_settings()
        
        # Build UI
        self._build_ui()
        
        log_debug("SettingsPanel initialized")
    
    def _load_settings(self):
        """Load settings from user_settings.json"""
        try:
            settings_file = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "instance", "user_settings.json"
            )
            
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    self.settings = json.load(f)
            else:
                self.settings = DEFAULT_SETTINGS.copy()
            
            log_debug(f"Loaded settings")
        except Exception as e:
            log_debug(f"Error loading settings: {e}")
            self.settings = DEFAULT_SETTINGS.copy()
    
    def _save_settings(self):
        """Save settings to user_settings.json"""
        try:
            instance_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "instance"
            )
            
            # Create instance directory if not exists
            if not os.path.exists(instance_dir):
                os.makedirs(instance_dir)
            
            settings_file = os.path.join(instance_dir, "user_settings.json")
            
            # Update settings from widgets
            self._update_settings_from_widgets()
            
            # Add timestamp
            self.settings['last_updated'] = datetime.now().isoformat()
            
            with open(settings_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
            
            log_debug(f"Saved settings")
        except Exception as e:
            log_debug(f"Error saving settings: {e}")
    
    def _update_settings_from_widgets(self):
        """Update settings dictionary from widget values."""
        for key, widget_info in self.setting_widgets.items():
            widget = widget_info['widget']
            widget_type = widget_info['type']
            
            try:
                if widget_type == 'entry':
                    self.settings[key] = widget.get()
                elif widget_type == 'combobox':
                    self.settings[key] = widget.get()
                elif widget_type == 'checkbutton':
                    self.settings[key] = widget_info['var'].get()
                elif widget_type == 'scale':
                    self.settings[key] = widget.get()
            except Exception as e:
                log_debug(f"Error updating setting {key}: {e}")
    
    def _build_ui(self):
        """Build the settings panel UI."""
        # Title
        title_frame = tk.Frame(self, bg=C_PANEL, height=50)
        title_frame.pack(fill=tk.X, padx=0, pady=0)
        
        title_label = tk.Label(
            title_frame,
            text=f"{getattr(self, 'asst_name', 'Assistant')} Settings",
            bg=C_PANEL,
            fg=C_TITLE,
            font=("Segoe UI", 16, "bold")
        )
        title_label.pack(pady=10)
        
        # Main scrollable area
        canvas = tk.Canvas(self, bg=C_BG, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(self, command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=C_BG)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Settings sections
        self._create_audio_settings(scrollable_frame)
        self._create_system_settings(scrollable_frame)
        self._create_voice_settings(scrollable_frame)
        self._create_notification_settings(scrollable_frame)
        self._create_language_settings(scrollable_frame)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bottom buttons
        button_frame = tk.Frame(self, bg=C_PANEL, height=60)
        button_frame.pack(fill=tk.X, padx=20, pady=15)
        
        # Save button
        save_btn = tk.Button(
            button_frame,
            text="✓ Save Settings",
            bg=C_BTN_GRN,
            fg="white",
            font=("Segoe UI", 11, "bold"),
            relief=tk.FLAT,
            cursor="hand2",
            command=self._on_save
        )
        save_btn.pack(side=tk.LEFT, padx=5)
        
        # Close button
        close_btn = tk.Button(
            button_frame,
            text="✕ Close",
            bg="#cc0000",
            fg="white",
            font=("Segoe UI", 11, "bold"),
            relief=tk.FLAT,
            cursor="hand2",
            command=self.destroy
        )
        close_btn.pack(side=tk.RIGHT, padx=5)
    
    def _create_setting_frame(self, parent, title):
        """Create a settings section frame."""
        frame = tk.Frame(parent, bg=C_PANEL)
        frame.pack(fill=tk.X, padx=10, pady=10)
        
        label = tk.Label(
            frame,
            text=title,
            bg=C_PANEL,
            fg=C_GLOW,
            font=("Segoe UI", 11, "bold")
        )
        label.pack(anchor=tk.W, padx=8, pady=(8, 4))
        
        sep = tk.Frame(frame, bg=C_GLOW_DIM, height=1)
        sep.pack(fill=tk.X, padx=8, pady=(0, 8))
        
        return frame
    
    def _add_combobox_setting(self, parent, key, label, options):
        """Add a combobox setting."""
        container = tk.Frame(parent, bg=C_PANEL)
        container.pack(fill=tk.X, padx=16, pady=6)
        
        lbl = tk.Label(
            container,
            text=label,
            bg=C_PANEL,
            fg=C_TEXT,
            font=("Segoe UI", 10)
        )
        lbl.pack(side=tk.LEFT, padx=(0, 8))
        
        combo = ttk.Combobox(
            container,
            values=options,
            state="readonly",
            width=20
        )
        combo.pack(side=tk.RIGHT, padx=8)
        combo.set(self.settings.get(key, options[0]))
        
        self.setting_widgets[key] = {
            'widget': combo,
            'type': 'combobox'
        }
    
    def _add_checkbutton_setting(self, parent, key, label):
        """Add a checkbutton setting."""
        container = tk.Frame(parent, bg=C_PANEL)
        container.pack(fill=tk.X, padx=16, pady=6)
        
        var = tk.BooleanVar(value=self.settings.get(key, False))
        chk = tk.Checkbutton(
            container,
            text=label,
            variable=var,
            bg=C_PANEL,
            fg=C_TEXT,
            activebackground=C_PANEL,
            activeforeground=C_GLOW,
            font=("Segoe UI", 10),
            cursor="hand2"
        )
        chk.pack(anchor=tk.W, padx=8)
        
        self.setting_widgets[key] = {
            'widget': chk,
            'var': var,
            'type': 'checkbutton'
        }
    
    def _add_scale_setting(self, parent, key, label, from_val=0, to_val=100):
        """Add a scale setting."""
        container = tk.Frame(parent, bg=C_PANEL)
        container.pack(fill=tk.X, padx=16, pady=6)
        
        lbl = tk.Label(
            container,
            text=label,
            bg=C_PANEL,
            fg=C_TEXT,
            font=("Segoe UI", 10)
        )
        lbl.pack(anchor=tk.W, padx=8, pady=(0, 4))
        
        scale = tk.Scale(
            container,
            from_=from_val,
            to=to_val,
            orient=tk.HORIZONTAL,
            bg=C_INNER,
            fg=C_GLOW,
            troughcolor=C_PANEL,
            length=300,
            highlightthickness=0
        )
        scale.pack(fill=tk.X, padx=8, pady=(0, 4))
        scale.set(self.settings.get(key, from_val))
        
        self.setting_widgets[key] = {
            'widget': scale,
            'type': 'scale'
        }
    
    def _create_audio_settings(self, parent):
        """Create audio settings section."""
        frame = self._create_setting_frame(parent, "🔊 Audio Settings")
        
        # Microphone
        self._add_combobox_setting(
            frame, "microphone", "Microphone:",
            ["Default", "Microphone 1", "Microphone 2", "External USB"]
        )
        
        # Speaker
        self._add_combobox_setting(
            frame, "speaker", "Speaker:",
            ["Default", "Speaker 1", "Speaker 2", "Headphones"]
        )
        
        # Voice speed
        self._add_scale_setting(
            frame, "voice_speed", "Voice Speed:", 100, 300
        )
    
    def _create_system_settings(self, parent):
        """Create system settings section."""
        frame = self._create_setting_frame(parent, "⚙️ System Settings")
        
        # Startup with Windows
        _name = getattr(self, 'asst_name', 'Assistant')
        self._add_checkbutton_setting(
            frame, "startup_with_windows", f"Start {_name} with Windows"
        )
        
        # Launcher position
        self._add_combobox_setting(
            frame, "launcher_position", "Launcher Position:",
            ["center", "top-left", "top-right", "bottom-left", "bottom-right"]
        )
        
        # Theme
        self._add_combobox_setting(
            frame, "theme", "Theme:",
            ["dark", "light", "system"]
        )
    
    def _create_voice_settings(self, parent):
        """Create voice settings section."""
        frame = self._create_setting_frame(parent, "🎙️ Voice Settings")
        
        # Wake-word sensitivity
        self._add_scale_setting(
            frame, "wake_word_sensitivity", "Wake-word Sensitivity:", 0, 100
        )
    
    def _create_notification_settings(self, parent):
        """Create notification settings section."""
        frame = self._create_setting_frame(parent, "🔔 Notifications")
        
        # Notifications enabled
        self._add_checkbutton_setting(
            frame, "notifications_enabled", "Enable Notifications"
        )
    
    def _create_language_settings(self, parent):
        """Create language settings section."""
        frame = self._create_setting_frame(parent, "🌐 Language")
        
        # Language
        self._add_combobox_setting(
            frame, "language", "Language:",
            ["en-US", "en-GB", "en-IN", "es-ES", "fr-FR", "de-DE", "ja-JP", "zh-CN"]
        )
    
    def _on_save(self):
        """Save settings and close panel."""
        log_debug("Saving settings")
        
        self._save_settings()
        
        # Speak confirmation
        try:
            from legacy.tts import speak
            speak("Settings saved successfully")
        except:
            pass
        
        # Close panel
        self.destroy()
