import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog, font as tkfont
import threading
import queue
import time
import re
import os
import sys

# Import logic - use relative imports since we're in legacy folder
# NOTE: speak() is intentionally NOT imported at module level.
# The coordinator must be initialized before any speak() call arrives;
# importing it lazily inside _gui_speak() ensures that is always true.
from legacy.sst import listen
from legacy.memory_manager import get_chat_history
# process_input imported lazily inside _process_backend to avoid circular import
from legacy.auth_helpers import try_restore_session


def _gui_speak(text: str) -> None:
    """Route GUI-originated speech through the TTS coordinator (COMMAND priority).

    Falls back to legacy.tts.speak() if the coordinator cannot be imported.
    Import is lazy so this module can be loaded before initialization completes.
    """
    try:
        from extensions.system.tts_coordinator import speak as _coord_speak, TTSPriority
        _coord_speak(text, priority=TTSPriority.COMMAND)
    except Exception:
        try:
            from legacy.tts import speak as _direct_speak
            _direct_speak(text)
        except Exception:
            try:
                from instance.config import settings as _s
                _lb = _s.get_assistant_name() or "Assistant"
            except Exception:
                _lb = "Assistant"
            print(f"{_lb}: {text}")

# Global queue for cross-thread communication
gui_queue = queue.Queue()

# ==========================================
# 1. THEMES & CONSTANTS
# ==========================================
THEMES = {
    "Midnight": {
        "bg": "#1e1e2e",
        "sidebar": "#181825",
        "header": "#1e1e2e",
        "chat": "#2a2a40",
        "input": "#2a2a40",
        "text": "#ffffff",
        "accent": "#6366f1",
        "muted": "#a6accd"
    },
    "Cyber": {
        "bg": "#0d0d0d",
        "sidebar": "#000000",
        "header": "#0d0d0d",
        "chat": "#1a1a1a",
        "input": "#1a1a1a",
        "text": "#00ffcc",
        "accent": "#ff00ff",
        "muted": "#1aedff"
    }
}

def run_in_main_thread(root, func, *args, **kwargs):
    def wrapper():
        func(*args, **kwargs)
    root.after(0, wrapper)

# ==========================================
# 2. MAIN APP (AssistantGui)
# ==========================================
class AssistantGui(tk.Tk):
    def __init__(self):
        super().__init__()

        # Title uses dynamic assistant name; falls back to 'AI Assistant' if none configured
        try:
            from instance.config import settings as _cfg
            _asst_name = _cfg.get_assistant_name() or "AI Assistant"
        except Exception:
            _asst_name = "AI Assistant"
        self.title(_asst_name)
        self._asst_name = _asst_name  # store for later UI updates
        self.geometry("600x700")
        self.configure(bg="#1e1e2e")

        # ---- SESSION RESTORATION ----
        try_restore_session()

        # ---- STATE ----
        self.typing_anim = False
        self.is_listening = False
        self.current_theme_name = "Midnight"
        self.font_size = 11

        self._build_ui()

        # --- DB POLLING & QUEUE ---
        self.last_msg_count = 0
        self.last_seen_msg_id = -1
        self.after(100, self._process_queue)
        self.after(500, self._poll_database)
        self.after(1000, self._poll_activity) # NEW

        self.status_var.set("Connected to brain. Standing by...")

    # ======================================
    # UI
    # ======================================
    def _build_ui(self):
        t = THEMES[self.current_theme_name]
        
        # Sidebar
        self.sidebar = tk.Frame(self, bg=t["sidebar"], width=70)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        self._add_sidebar_btn("🏠", "Home", self.clear_chat)
        self._add_sidebar_btn("🕒", "History", self._toggle_history)
        self._add_sidebar_btn("⚡", "Activity", self._toggle_activity) # NEW
        self._add_sidebar_btn("🌓", "Theme", self.toggle_theme)
        self._add_sidebar_btn("➕", "Font+", lambda: self.change_font(1))
        self._add_sidebar_btn("➖", "Font-", lambda: self.change_font(-1))
        
        # Main content area
        self.main_area = tk.Frame(self, bg=t["bg"])
        self.main_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Header
        self.header = tk.Frame(self.main_area, bg=t["header"])
        self.header.pack(fill=tk.X, padx=10, pady=10)

        self.lbl_title = tk.Label(
            self.header, text=getattr(self, '_asst_name', 'AI Assistant'),
            font=("Inter", 18, "bold"), fg="white", bg=t["header"]
        )
        self.lbl_title.pack(side=tk.LEFT)

        user = CONFIG.get("CURRENT_USERNAME", "User")
        
        self.lbl_user = tk.Label(
            self.header, text=f"Logged in as: {user}",
            fg=t["muted"], bg=t["header"]
        )
        self.lbl_user.pack(side=tk.RIGHT)

        self.btn_info = tk.Button(
            self.header, text="ℹ️", bg=t["sidebar"], fg=t["muted"],
            font=("Arial", 10), relief=tk.FLAT, command=self.show_about
        )
        self.btn_info.pack(side=tk.RIGHT, padx=(10, 0))

        # Suggestion Chips
        self.suggestion_frame = tk.Frame(self.main_area, bg=t["bg"])
        self.suggestion_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        suggestions = ["Weather 🌤️", "Tell a Joke 😂", "News Headlines 📰", "What's the Time? 🕒"]
        for s in suggestions:
            btn = tk.Button(
                self.suggestion_frame, text=s, bg=t["chat"], fg=t["muted"],
                font=("Arial", 9), relief=tk.FLAT, padx=8, pady=2,
                command=lambda val=s: self.quick_input(val)
            )
            btn.pack(side=tk.LEFT, padx=(0, 5))
            self._add_hover(btn, t["accent"], t["chat"])

        # Context Menu
        self.context_menu = tk.Menu(self, tearoff=0, bg=t["chat"], fg="white", activebackground=t["accent"])
        self.context_menu.add_command(label="Copy Message", command=self._copy_selection)
        self.context_menu.add_command(label="Explain this Decision", command=self._explain_latest)
        self.context_menu.add_command(label="Why NOT? (Diagnostics)", command=self._show_why_not)
        self.chat_display.bind("<Button-3>", self._show_context_menu)

        # Chat display area
        self.paned = tk.PanedWindow(self.main_area, orient=tk.HORIZONTAL, bg=t["bg"], sashwidth=4)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=10)

        # Activity Panel (Phase 4)
        self.activity_frame = tk.Frame(self.paned, bg=t["sidebar"], width=200)
        self.activity_visible = False
        
        lbl_act = tk.Label(self.activity_frame, text="ACTIVITY FEED", bg=t["sidebar"], fg=t["accent"], font=("Arial", 9, "bold"))
        lbl_act.pack(fill=tk.X, pady=5)
        
        self.activity_feed = scrolledtext.ScrolledText(
            self.activity_frame, bg=t["sidebar"], fg=t["muted"],
            bd=0, highlightthickness=0, font=("Consolas", 9), state=tk.DISABLED
        )
        self.activity_feed.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # History panel (hidden initially)
        self.history_frame = tk.Frame(self.paned, bg=t["sidebar"], width=200)
        self.history_visible = False

        self.history_list = tk.Listbox(
            self.history_frame, bg=t["sidebar"], fg=t["muted"],
            bd=0, highlightthickness=0, font=("Arial", 10)
        )
        self.history_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.history_list.bind("<<ListboxSelect>>", self._on_history_click)

        # Chat window
        chat_container = tk.Frame(self.paned, bg=t["bg"])
        self.paned.add(chat_container, minsize=400)

        self.chat_display = scrolledtext.ScrolledText(
            chat_container, state=tk.DISABLED,
            font=("Segoe UI", self.font_size),
            bg=t["chat"], fg=t["text"],
            insertbackground="white",
            bd=0, padx=10, pady=10,
            undo=True
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)

        # Context Menu
        self.context_menu = tk.Menu(self, tearoff=0, bg=t["chat"], fg="white", activebackground=t["accent"])
        self.context_menu.add_command(label="Copy Message", command=self._copy_selection)
        self.chat_display.bind("<Button-3>", self._show_context_menu)

        # Input area
        self.input_container = tk.Frame(self.main_area, bg=t["input"])
        self.input_container.pack(fill=tk.X, side=tk.BOTTOM)

        self.status_var = tk.StringVar()
        self.status_bar = tk.Label(
            self.input_container, textvariable=self.status_var,
            fg=t["accent"], bg=t["input"], font=("Arial", 9)
        )
        self.status_bar.pack(side=tk.TOP, fill=tk.X, pady=2)

        input_frame = tk.Frame(self.input_container, bg=t["input"], pady=10, padx=10)
        input_frame.pack(fill=tk.X)

        self.entry = tk.Entry(
            input_frame, font=("Arial", 12),
            bg=t["bg"], fg=t["text"],
            insertbackground="white",
            bd=1, relief=tk.FLAT
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), ipady=5)
        self.entry.bind("<Return>", self.send_text)

        self.btn_send = tk.Button(
            input_frame, text="Send",
            bg=t["accent"], fg="white",
            font=("Arial", 10, "bold"),
            relief=tk.FLAT, command=self.send_text
        )
        self.btn_send.pack(side=tk.RIGHT, ipadx=10)

        self.btn_mic = tk.Button(
            input_frame, text="🎤",
            bg=t["input"], fg="white",
            font=("Arial", 12),
            relief=tk.FLAT, command=self.listen_voice
        )
        self.btn_mic.pack(side=tk.RIGHT, padx=(0, 10))

    def _add_sidebar_btn(self, icon, label, cmd):
        t = THEMES[self.current_theme_name]
        btn = tk.Button(
            self.sidebar, text=icon, bg=t["sidebar"], fg=t["muted"],
            font=("Arial", 18), relief=tk.FLAT, pady=15, command=cmd
        )
        btn.pack(side=tk.TOP, fill=tk.X)
        self._add_hover(btn, t["accent"], t["sidebar"])

    def _add_hover(self, widget, h_color, d_color):
        widget.bind("<Enter>", lambda e: widget.config(fg=h_color))
        widget.bind("<Leave>", lambda e: widget.config(fg=THEMES[self.current_theme_name]["muted"]))

    def quick_input(self, text):
        clean_text = re.sub(r'[^\w\s\?]', '', text).strip()
        self.entry.delete(0, tk.END)
        self.entry.insert(0, clean_text)
        self.send_text()

    def toggle_theme(self):
        self.current_theme_name = "Cyber" if self.current_theme_name == "Midnight" else "Midnight"
        # Re-build UI (simplest way to update everything for now)
        for widget in self.winfo_children():
            widget.destroy()
        self._build_ui()
        self.status_var.set(f"Switched to {self.current_theme_name} Theme")

    def change_font(self, delta):
        self.font_size = max(8, min(24, self.font_size + delta))
        self.chat_display.config(font=("Segoe UI", self.font_size))

    # ======================================
    # HISTORY
    # ======================================
    def _toggle_history(self):
        if self.history_visible:
            self.paned.forget(self.history_frame)
            self.history_visible = False
        else:
            self.paned.add(self.history_frame, minsize=200)
            self._refresh_history_list()
            self.history_visible = True


    def _refresh_history_list(self):
        uid = CONFIG.get("CURRENT_USER_ID")
        if not uid:
            return
        try:
            self.history_list.delete(0, tk.END)
            msgs = get_chat_history(uid, limit=50)
            for m in msgs:
                if m["role"] == "user":
                    snippet = m["content"][:30]
                    if len(m["content"]) > 30:
                        snippet += "..."
                    self.history_list.insert(0, snippet)
        except Exception as e:
            print(f"[GUI] History refresh failed: {e}")
            pass

    def _on_history_click(self, event):
        sel = self.history_list.curselection()
        if not sel:
            return
        text = self.history_list.get(sel[0]).replace("...", "")
        self.entry.delete(0, tk.END)
        self.entry.insert(0, text)

    # ======================================
    # CHAT
    # ======================================
    def send_text(self, event=None):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        self._append_message("User", text)
        threading.Thread(
            target=self._process_backend,
            args=(text,),
            daemon=True
        ).start()

    def listen_voice(self):
        if self.is_listening:
            return
        threading.Thread(target=self._voice_worker, daemon=True).start()

    def _voice_worker(self):
        run_in_main_thread(self, self._update_listen_state, True)
        try:
            # Guard: wait until TTS is silent before opening the microphone.
            # sst.listen() also does this internally, but doing it here lets
            # us update the button state while we wait so the user knows why
            # the mic hasn't opened yet.
            try:
                from legacy.tts import wait_for_silence, is_speaking
                if is_speaking():
                    run_in_main_thread(
                        self, self.status_var.set, "Waiting for assistant to finish speaking..."
                    )
                    wait_for_silence(timeout=12.0)
            except Exception:
                pass

            text = listen()
            if text:
                run_in_main_thread(self, self.entry.insert, 0, text)
                run_in_main_thread(self, self.send_text)
            else:
                self._append_message("System", "I didn't catch that.")
        except Exception as e:
            self._append_message("System", f"Voice error: {e}")
        finally:
            run_in_main_thread(self, self._update_listen_state, False)

    def _update_listen_state(self, is_listening):
        self.is_listening = is_listening
        if is_listening:
            self.btn_mic.config(bg="#ef4444")
            self.status_var.set("🎤 Listening...")
        else:
            self.btn_mic.config(bg="#2a2a40")
            self.status_var.set("Standing by")

    def _process_backend(self, text):
        run_in_main_thread(self, self._start_typing)
        try:
            # Lazy import avoids circular dependency during module scan
            from legacy.assistant import process_input as assistant_process_input
            assistant_process_input(text)
        except Exception as e:
            run_in_main_thread(self, self._append_message, "System", str(e))
        finally:
            run_in_main_thread(self, self._stop_typing)

    def _start_typing(self):
        if self.typing_anim: return
        self.typing_anim = True
        self._typing_step = 0
        self._animate_typing()

    def _animate_typing(self):
        if not self.typing_anim: return
        dots = "." * (self._typing_step % 4)
        _thinking_name = getattr(self, '_asst_name', 'Assistant')
        self.status_var.set(f"{_thinking_name} is thinking{dots}")
        
        # Pulse color effect
        colors = ["#6366f1", "#818cf8", "#a5b4fc", "#818cf8"]
        current_color = colors[self._typing_step % len(colors)]
        self.status_bar.config(fg=current_color)
        
        self._typing_step += 1
        self.after(500, self._animate_typing)

    def _stop_typing(self):
        self.typing_anim = False
        t = THEMES[self.current_theme_name]
        self.status_bar.config(fg=t["accent"])
        self.status_var.set("Standing by")

    def clear_chat(self):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.delete('1.0', tk.END)
        self.chat_display.config(state=tk.DISABLED)

    def show_about(self):
        _name = getattr(self, '_asst_name', 'AI Assistant')
        messagebox.showinfo(f"About {_name}", f"{_name} v2.0\nBuilt for a premium AI experience.")

    def _show_context_menu(self, event):
        self.context_menu.post(event.x_root, event.y_root)

    def _copy_selection(self):
        try:
            selected_text = self.chat_display.selection_get()
            self.clipboard_clear()
            self.clipboard_append(selected_text)
        except Exception as e:
            print(f"[GUI] Status update failed: {e}")

    def _append_message(self, role, msg):
        self.chat_display.config(state=tk.NORMAL)
        t = THEMES[self.current_theme_name]

        self.chat_display.tag_config("user", foreground=t["muted"], font=("Segoe UI", self.font_size, "bold"))
        self.chat_display.tag_config("assistant", foreground=t["accent"], font=("Segoe UI", self.font_size, "bold"))
        self.chat_display.tag_config("system", foreground="#ef4444", font=("Segoe UI", self.font_size, "italic"))

        ts = time.strftime("%H:%M")
        tag = "assistant" if role.lower() != "user" else "user"
        if role.lower() == "system": tag = "system"

        self.chat_display.insert(tk.END, f"[{ts}] {role}: ", tag)
        
        # Typing effect
        def type_text(index=0):
            if index < len(msg):
                self.chat_display.config(state=tk.NORMAL)
                self.chat_display.insert(tk.END, msg[index])
                self.chat_display.config(state=tk.DISABLED)
                self.chat_display.see(tk.END)
                self.after(20, lambda: type_text(index + 1))
            else:
                self.chat_display.config(state=tk.NORMAL)
                self.chat_display.insert(tk.END, "\n\n")
                self.chat_display.config(state=tk.DISABLED)
                self.chat_display.see(tk.END)

        _asst_label = getattr(self, '_asst_name', 'Assistant').lower()
        if role.lower() == _asst_label or role.lower() == "assistant":
            type_text()
        else:
            self.chat_display.insert(tk.END, msg + "\n\n")
            self.chat_display.config(state=tk.DISABLED)
            self.chat_display.see(tk.END)

        if self.history_visible and role.lower() == "user":
            self._refresh_history_list()

    # ======================================
    # BACKGROUND UPDATES
    # ======================================
    def _poll_database(self):
        uid = CONFIG.get("CURRENT_USER_ID")
        if uid:
            try:
                # Fetch more messages to catch potentially missed ones if GUI was slow
                msgs = get_chat_history(uid, limit=5)
                for last in msgs:
                    msg_id = last.get("id", -1)
                    if msg_id > self.last_seen_msg_id:
                        role = getattr(self, '_asst_name', 'Assistant') if last["role"] == "assistant" else last["role"].capitalize()
                        self._append_message(role, last["content"])
                        self.last_seen_msg_id = msg_id
            except Exception as e:
                print(f"[POLL ERROR] {e}")
        self.after(500, self._poll_database)

    # ======================================
    # ACTIVITY & EXPLAINABILITY (Phase 4)
    # ======================================
    def _toggle_activity(self):
        if self.activity_visible:
            self.paned.forget(self.activity_frame)
            self.activity_visible = False
        else:
            self.paned.add(self.activity_frame, minsize=200)
            self.activity_visible = True
            self._poll_activity()

    def _poll_activity(self):
        if not self.activity_visible: return
        uid = CONFIG.get("CURRENT_USER_ID")
        if not uid: return
        
        try:
            from legacy.memory_manager import get_activity_logs_db
            logs = get_activity_logs_db(uid, limit=20)
            
            self.activity_feed.config(state=tk.NORMAL)
            self.activity_feed.delete('1.0', tk.END)
            for log in logs:
                ts = log['created_at'].strftime("%H:%M:%S")
                color = "#6366f1" if log['type'] == 'DECISION' else "#1aedff"
                self.activity_feed.insert(tk.END, f"[{ts}] ", "gray")
                self.activity_feed.insert(tk.END, f"{log['type']}: ", "bold")
                self.activity_feed.insert(tk.END, f"{log['target']} - {log['content']}\n", "text")
            self.activity_feed.config(state=tk.DISABLED)
        except Exception as e:
            print(f"[ACTIVITY POLL ERROR] {e}")
        
        if self.activity_visible:
            self.after(2000, self._poll_activity)

    def _explain_latest(self):
        uid = CONFIG.get("CURRENT_USER_ID")
        if not uid: return
        try:
            from legacy.memory_manager import get_latest_decision_db
            log = get_latest_decision_db(uid)
            if log:
                msg = f"Last Decision: {log['decision']}\n"
                msg += f"Component: {log['component']}\n"
                msg += f"Reason: {log['reason']}\n"
                msg += f"Time: {log['created_at']}"
                messagebox.showinfo("Explainability", msg)
            else:
                messagebox.showinfo("Explainability", "No recent decisions logged.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _show_why_not(self):
        try:
            # We need to reach through assistant.py to the orchestrator instance
            # In a real app, orchestrator would be global or in common config
            from legacy.assistant import orchestrator
            skips = orchestrator.explainability.get_skipped_decisions()
            if not skips:
                messagebox.showinfo("Diagnostics", "No routing bypasses logged for the last request.")
                return
            
            msg = "ROUTING ANALYSIS (Why certain handlers were skipped):\n\n"
            for s in skips:
                msg += f"• {s['handler']}: {s['reason']}\n"
            messagebox.showinfo("Why NOT? Analysis", msg)
        except Exception as e:
            messagebox.showerror("Error", f"Could not fetch diagnostics: {e}")

    def _process_queue(self):
        try:
            while True:
                func, args = gui_queue.get_nowait()
                func(*args)
        except queue.Empty:
            pass
        self.after(100, self._process_queue)
