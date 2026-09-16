"""
Voice Selection Panel for NOVA
Allows users to select and preview different voice profiles.
Saves selected voice persistently to instance/user_voice.json
"""

import tkinter as tk
from tkinter import Canvas
import threading
import json
import os
from datetime import datetime

# Debug logging
DEBUG = True
def log_debug(msg):
    if DEBUG:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [VOICE_PANEL] {msg}")


# Voice profiles
VOICE_PROFILES = {
    "assistant_calm": {
        "name": "Calm",
        "description": "Smooth, peaceful voice",
        "icon": "🧘",
        "rate": 140,
        "voice_id": "calm"
    },
    "assistant_professional": {
        "name": "Professional",
        "description": "Confident, business voice",
        "icon": "💼",
        "rate": 160,
        "voice_id": "professional"
    },
    "assistant_friendly": {
        "name": "Friendly",
        "description": "Warm, conversational voice",
        "icon": "😊",
        "rate": 150,
        "voice_id": "friendly"
    },
    "assistant_energetic": {
        "name": "Energetic",
        "description": "Upbeat, enthusiastic voice",
        "icon": "⚡",
        "rate": 180,
        "voice_id": "energetic"
    },
    "assistant_classic": {
        "name": "Classic",
        "description": "Traditional, standard voice",
        "icon": "🎙️",
        "rate": 150,
        "voice_id": "default"
    }
}

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
C_SELECT = "#00e5aa"


class VoicePanel(tk.Toplevel):
    """
    Voice selection panel for NOVA.
    Shows 5 voice profiles with preview capability.
    Saves selection to instance/user_voice.json
    """
    
    def __init__(self, root):
        """Initialize voice panel."""
        super().__init__(root)
        try:
            from instance.config import settings as _cfg
            self.asst_name = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            self.asst_name = "Assistant"
        self.title(f"{self.asst_name} - Voice Selection")
        self.geometry("600x700")
        self.configure(bg=C_BG)
        self.resizable(False, False)
        
        # Center window
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (600 // 2)
        y = (self.winfo_screenheight() // 2) - (700 // 2)
        self.geometry(f"600x700+{x}+{y}")
        
        self.root = root
        self.current_selection = None
        self.preview_thread = None
        self.buttons = {}
        
        # Load current voice selection
        self._load_selected_voice()
        
        # Build UI
        self._build_ui()
        
        log_debug("VoicePanel initialized")
    
    def _load_selected_voice(self):
        """Load current voice selection from user_voice.json"""
        try:
            voice_file = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "instance", "user_voice.json"
            )
            
            if os.path.exists(voice_file):
                with open(voice_file, 'r') as f:
                    data = json.load(f)
                    self.current_selection = data.get("selected_voice", "assistant_friendly")
            else:
                self.current_selection = "assistant_friendly"
            
            log_debug(f"Loaded voice selection: {self.current_selection}")
        except Exception as e:
            log_debug(f"Error loading voice selection: {e}")
            self.current_selection = "assistant_friendly"
    
    def _save_selected_voice(self, voice_key):
        """Save selected voice to user_voice.json"""
        try:
            instance_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "instance"
            )
            
            # Create instance directory if not exists
            if not os.path.exists(instance_dir):
                os.makedirs(instance_dir)
            
            voice_file = os.path.join(instance_dir, "user_voice.json")
            
            data = {
                "selected_voice": voice_key,
                "voice_name": VOICE_PROFILES[voice_key]["name"],
                "voice_rate": VOICE_PROFILES[voice_key]["rate"],
                "timestamp": datetime.now().isoformat()
            }
            
            with open(voice_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            log_debug(f"Saved voice selection: {voice_key}")
        except Exception as e:
            log_debug(f"Error saving voice selection: {e}")
    
    def _build_ui(self):
        """Build the voice panel UI."""
        # Title
        title_frame = tk.Frame(self, bg=C_PANEL, height=50)
        title_frame.pack(fill=tk.X, padx=0, pady=0)
        
        title_label = tk.Label(
            title_frame,
            text=f"Select Your {getattr(self, 'asst_name', 'Assistant')} Voice",
            bg=C_PANEL,
            fg=C_TITLE,
            font=("Segoe UI", 16, "bold")
        )
        title_label.pack(pady=10)
        
        # Subtitle
        subtitle = tk.Label(
            title_frame,
            text="Choose a voice profile and preview it",
            bg=C_PANEL,
            fg=C_DIM,
            font=("Segoe UI", 10)
        )
        subtitle.pack(pady=(0, 10))
        
        # Main scrollable area
        canvas = Canvas(self, bg=C_BG, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(self, command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=C_BG)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Voice options
        for voice_key, voice_data in VOICE_PROFILES.items():
            self._create_voice_option(scrollable_frame, voice_key, voice_data)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bottom buttons
        button_frame = tk.Frame(self, bg=C_PANEL, height=60)
        button_frame.pack(fill=tk.X, padx=20, pady=15)
        
        # Save button
        save_btn = tk.Button(
            button_frame,
            text="✓ Save Selection",
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
    
    def _create_voice_option(self, parent, voice_key, voice_data):
        """Create a voice option button."""
        # Container frame
        option_frame = tk.Frame(parent, bg=C_INNER)
        option_frame.pack(fill=tk.X, pady=8)
        
        is_selected = (voice_key == self.current_selection)
        
        # Create clickable button frame
        btn_frame = tk.Frame(option_frame, bg=C_GLOW if is_selected else C_PANEL)
        btn_frame.pack(fill=tk.X, padx=1, pady=1)
        
        inner_frame = tk.Frame(btn_frame, bg=C_PANEL if not is_selected else C_INNER)
        inner_frame.pack(fill=tk.X, padx=8, pady=8)
        
        # Icon and name
        header = tk.Frame(inner_frame, bg=C_PANEL if not is_selected else C_INNER)
        header.pack(fill=tk.X, pady=(0, 4))
        
        icon_label = tk.Label(
            header,
            text=voice_data["icon"],
            bg=C_PANEL if not is_selected else C_INNER,
            fg=C_TEXT,
            font=("Segoe UI", 20)
        )
        icon_label.pack(side=tk.LEFT, padx=(0, 8))
        
        name_label = tk.Label(
            header,
            text=voice_data["name"],
            bg=C_PANEL if not is_selected else C_INNER,
            fg=C_SELECT if is_selected else C_TITLE,
            font=("Segoe UI", 13, "bold")
        )
        name_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        if is_selected:
            check_label = tk.Label(
                header,
                text="✓",
                bg=C_PANEL if not is_selected else C_INNER,
                fg=C_SELECT,
                font=("Segoe UI", 14, "bold")
            )
            check_label.pack(side=tk.RIGHT)
        
        # Description
        desc_label = tk.Label(
            inner_frame,
            text=voice_data["description"],
            bg=C_PANEL if not is_selected else C_INNER,
            fg=C_DIM,
            font=("Segoe UI", 9),
            justify=tk.LEFT
        )
        desc_label.pack(fill=tk.X, padx=40, pady=(0, 8))
        
        # Preview button
        preview_btn = tk.Button(
            inner_frame,
            text="🔊 Preview",
            bg=C_BTN_BLU,
            fg="white",
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            cursor="hand2",
            command=lambda: self._preview_voice(voice_key, voice_data)
        )
        preview_btn.pack(side=tk.LEFT, padx=40, pady=(4, 0))
        
        # Select button
        select_btn = tk.Button(
            inner_frame,
            text="Select",
            bg=C_BTN_GRN if is_selected else C_GLOW_DIM,
            fg="white" if not is_selected else C_BG,
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            cursor="hand2",
            command=lambda: self._select_voice(voice_key, btn_frame, inner_frame)
        )
        select_btn.pack(side=tk.RIGHT, padx=40, pady=(4, 0))
        
        # Store reference for updating
        self.buttons[voice_key] = {
            'btn_frame': btn_frame,
            'inner_frame': inner_frame,
            'header': header,
            'select_btn': select_btn,
            'check_label': None
        }
    
    def _select_voice(self, voice_key, btn_frame, inner_frame):
        """Select a voice and update UI."""
        log_debug(f"Voice selected: {voice_key}")
        
        # Reset all buttons
        for key, btn_data in self.buttons.items():
            try:
                btn_data['btn_frame'].configure(bg=C_PANEL)
                btn_data['inner_frame'].configure(bg=C_INNER)
            except:
                pass
        
        # Highlight selected
        btn_frame.configure(bg=C_GLOW)
        inner_frame.configure(bg=C_INNER)
        
        self.current_selection = voice_key
    
    def _preview_voice(self, voice_key, voice_data):
        """Preview a voice (non-blocking)."""
        log_debug(f"Previewing voice: {voice_key}")
        
        def _preview_in_thread():
            try:
                from legacy.tts import speak
                import time
                
                # Speak preview text with voice info
                preview_text = f"Hello, I am {voice_data['name']}. This is my voice."
                speak(preview_text, lang_hint='en')
                
            except Exception as e:
                log_debug(f"Error previewing voice: {e}")
        
        # Run in daemon thread to not block UI
        thread = threading.Thread(target=_preview_in_thread, daemon=True)
        thread.start()
    
    def _on_save(self):
        """Save the selected voice and close panel."""
        log_debug(f"Saving voice selection: {self.current_selection}")
        
        self._save_selected_voice(self.current_selection)
        
        # Speak confirmation
        try:
            from legacy.tts import speak
            voice_name = VOICE_PROFILES[self.current_selection]["name"]
            speak(f"Voice changed to {voice_name}")
        except:
            pass
        
        # Close panel
        self.destroy()
