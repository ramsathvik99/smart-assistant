import tkinter as tk
from tkinter import messagebox
import threading
import time
import sys
import os

# ───── PATH SETUP ─────
nova_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if nova_root not in sys.path:
    sys.path.insert(0, nova_root)

from legacy.tts import speak

# ───── EXACT COLOR PALETTE ─────
C_BG        = "#0b1a2a"   # main window background
C_PANEL     = "#112b3c"   # panel background
C_INNER     = "#0d2035"   # text area / inner widget bg
C_GLOW      = "#00f5ff"   # cyan glow accent
C_GLOW_DIM  = "#004d5a"   # dim border
C_TEXT      = "#c8eeff"   # main text
C_DIM       = "#3a7080"   # dim/placeholder text
C_TITLE     = "#00f5ff"   # title text
C_BTN_GRN   = "#00c853"   # green button (start)
C_BTN_ORN   = "#ff9800"   # orange button (stop)
C_BTN_BLU   = "#0288d1"   # blue buttons
C_BTN_DRK   = "#0a2535"   # dark button fallback
C_STATUS    = "#00e5aa"   # status accent

# ───── HELPERS ─────
def glow_frame(parent, **kwargs):
    """Creates outer glow frame (cyan) → inner dark frame."""
    outer = tk.Frame(parent, bg=C_GLOW, padx=1, pady=1, **kwargs)
    inner = tk.Frame(outer, bg=C_PANEL)
    inner.pack(fill=tk.BOTH, expand=True)
    return outer, inner

def mk_btn(parent, text, command, bg=C_BTN_BLU, fg="white", width=14):
    return tk.Button(parent, text=text, command=command,
                     bg=bg, fg=fg, activebackground=bg,
                     activeforeground=fg, relief=tk.FLAT,
                     font=("Segoe UI", 9, "bold"), pady=5,
                     cursor="hand2", width=width)

def section_label(parent, text):
    tk.Label(parent, text=text, bg=C_PANEL, fg=C_GLOW,
             font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, padx=10, pady=(6, 2))
    tk.Frame(parent, bg=C_GLOW_DIM, height=1).pack(fill=tk.X, padx=10, pady=(0, 4))

def text_area(parent, height=4):
    # Create an inner frame to hold the text and scrollbar
    frame = tk.Frame(parent, bg=C_INNER)
    frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    t = tk.Text(frame, height=height, bg=C_INNER, fg=C_TEXT,
                insertbackground=C_GLOW, relief=tk.FLAT,
                font=("Consolas", 9), state=tk.DISABLED,
                selectbackground="#0288d1", padx=6, pady=4)
    t.grid(row=0, column=0, sticky="nsew")

    scrollbar = tk.Scrollbar(frame, command=t.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    t.config(yscrollcommand=scrollbar.set)
    return t

def styled_entry(parent, textvariable=None, readonly=False):
    e = tk.Entry(parent, textvariable=textvariable,
                 bg=C_INNER, fg=C_GLOW, insertbackground=C_GLOW,
                 relief=tk.FLAT, font=("Segoe UI", 10),
                 highlightthickness=1,
                 highlightbackground=C_GLOW_DIM,
                 highlightcolor=C_GLOW,
                 state="readonly" if readonly else tk.NORMAL)
    return e

# ─────────────────────────────────────────────────────────
class AssistantUI(tk.Toplevel):
    def _get_assistant_name(self):
        try:
            from instance.config import settings
            return settings.get_assistant_name() or "Assistant"
        except Exception:
            return "Assistant"

    def __init__(self, parent):
        super().__init__(parent)
        self.asst_name = self._get_assistant_name()
        self.title(f"{self.asst_name} – Central Controller")
        self.geometry("1000x720")
        self.minsize(900, 600)
        self.configure(bg=C_BG)
        self.resizable(True, True)

        # Start Maximized
        if sys.platform == "win32":
            self.state("zoomed")

        # Root Window Resizing Configure
        self.rowconfigure(0, weight=0) # Header
        self.rowconfigure(1, weight=0) # Separator Line
        self.rowconfigure(2, weight=1) # Main Body
        self.columnconfigure(0, weight=1)

        self.is_listening = False
        
        self._build_header()
        self._build_main()

        # Handle window close (hide instead of destroy)
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

    # ══════ HEADER ══════
    def _build_header(self):
        hdr = tk.Frame(self, bg=C_PANEL, height=54)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.pack_propagate(False)

        tk.Label(hdr, text=f"⬡  {self.asst_name} – Central Controller",
                 bg=C_PANEL, fg=C_TITLE,
                 font=("Segoe UI", 15, "bold")).pack(side=tk.LEFT, padx=20)

        self.lbl_status = tk.Label(hdr, text="● Status: Idle",
                                   bg=C_PANEL, fg=C_STATUS,
                                   font=("Segoe UI", 10))
        self.lbl_status.pack(side=tk.RIGHT, padx=20)

        tk.Frame(self, bg=C_GLOW, height=2).grid(row=1, column=0, sticky="ew")

    # ══════ MAIN LAYOUT ══════
    def _build_main(self):
        main = tk.Frame(self, bg=C_BG)
        main.grid(row=2, column=0, sticky="nsew", padx=10, pady=8)

        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=1, minsize=260)
        main.rowconfigure(0, weight=0)
        main.rowconfigure(1, weight=0)
        main.rowconfigure(2, weight=1)
        main.rowconfigure(3, weight=0)
        main.rowconfigure(4, weight=0)
        main.rowconfigure(5, weight=0)

        # Row 0: Voice Control (left) + Command Display (right)
        self._build_voice_panel(main)
        self._build_command_panel(main)

        # Row 1: Execution Status (full width)
        self._build_exec_panel(main)

        # Row 2: Output (expandable, full width)
        self._build_output_panel(main)

        # Row 3: TTS buttons
        self._build_tts_row(main)

        # Row 4: Fallback + File Saver
        self._build_input_row(main)

        # Row 5: Quick Actions
        self._build_quick_actions(main)

    # ══════ VOICE CONTROL ══════
    def _build_voice_panel(self, parent):
        outer, inner = glow_frame(parent)
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 6))

        section_label(inner, "Voice Control")

        # Waveform area
        wf = tk.Frame(inner, bg=C_INNER, height=52,
                      highlightthickness=1, highlightbackground=C_GLOW_DIM)
        wf.pack(fill=tk.X, padx=10, pady=(0, 8))
        wf.pack_propagate(False)

        self.lbl_wave = tk.Label(wf,
                                  text="〰 〰 〰 〰 〰 〰 〰 〰 〰 〰 〰",
                                  bg=C_INNER, fg=C_GLOW_DIM,
                                  font=("Segoe UI", 14))
        self.lbl_wave.pack(expand=True)

        btn_row = tk.Frame(inner, bg=C_PANEL)
        btn_row.pack(pady=(0, 8))

        mk_btn(btn_row, "▶  Start Listening", self.on_start_listen,
               bg=C_BTN_GRN, width=18).pack(side=tk.LEFT, padx=8)
        mk_btn(btn_row, "✖  Stop Listening", self.on_stop_listen,
               bg=C_BTN_ORN, width=18).pack(side=tk.LEFT, padx=8)

    # ══════ COMMAND DISPLAY ══════
    def _build_command_panel(self, parent):
        outer, inner = glow_frame(parent)
        outer.grid(row=0, column=1, sticky="nsew", pady=(0, 6))

        section_label(inner, "Command Display")

        tk.Label(inner, text="Command Heard:", bg=C_PANEL, fg=C_DIM,
                 font=("Segoe UI", 8)).pack(anchor=tk.W, padx=10)

        self.var_command = tk.StringVar(value="[No command yet]")
        self.entry_cmd = styled_entry(inner, textvariable=self.var_command, readonly=True)
        self.entry_cmd.pack(fill=tk.X, padx=10, pady=4)

        mk_btn(inner, "✏  Edit / Run", self.on_edit_command,
               bg=C_BTN_BLU, width=14).pack(anchor=tk.E, padx=10, pady=(0, 8))

    # ══════ EXECUTION STATUS ══════
    def _build_exec_panel(self, parent):
        outer, inner = glow_frame(parent)
        outer.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 6))

        section_label(inner, "Execution Status")
        self.txt_exec = text_area(inner, height=3)

    # ══════ OUTPUT ══════
    def _build_output_panel(self, parent):
        outer, inner = glow_frame(parent)
        outer.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(0, 6))

        section_label(inner, "Output")
        self.txt_output = text_area(inner, height=8)

    # ══════ TTS BUTTONS ══════
    def _build_tts_row(self, parent):
        row = tk.Frame(parent, bg=C_BG)
        row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        mk_btn(row, "🔊  Speak Output", self.speak_output,
               bg="#006633", fg="white", width=18).pack(side=tk.LEFT, padx=(0, 8))
        mk_btn(row, "⏹  Stop Speaking", self.stop_speech,
               bg=C_BTN_ORN, fg="white", width=18).pack(side=tk.LEFT)

    # ══════ FALLBACK + FILE SAVER ══════
    def _build_input_row(self, parent):
        row = tk.Frame(parent, bg=C_BG)
        row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)

        # Fallback
        fb_outer, fb_inner = glow_frame(row)
        fb_outer.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        section_label(fb_inner, "Fallback Input")
        fb_row = tk.Frame(fb_inner, bg=C_PANEL)
        fb_row.pack(fill=tk.X, padx=10, pady=(0, 8))

        self.var_fallback = tk.StringVar()
        styled_entry(fb_row, textvariable=self.var_fallback).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        mk_btn(fb_row, "▶ Route", self.on_run_fallback,
               bg=C_BTN_BLU, width=10).pack(side=tk.RIGHT)

        # File Saver
        fs_outer, fs_inner = glow_frame(row)
        fs_outer.grid(row=0, column=1, sticky="ew")

        section_label(fs_inner, "File Override / Saver")
        fs_row = tk.Frame(fs_inner, bg=C_PANEL)
        fs_row.pack(fill=tk.X, padx=10, pady=(0, 8))

        self.var_filename = tk.StringVar()
        styled_entry(fs_row, textvariable=self.var_filename).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        mk_btn(fs_row, "💾 Save As", self.on_save_override,
               bg=C_BTN_BLU, width=10).pack(side=tk.RIGHT)

    # ══════ QUICK ACTIONS ══════
    def _build_quick_actions(self, parent):
        outer, inner = glow_frame(parent)
        outer.grid(row=5, column=0, columnspan=2, sticky="ew")

        section_label(inner, "Quick Connect Actions")

        btn_row = tk.Frame(inner, bg=C_PANEL)
        btn_row.pack(pady=(0, 8), padx=10, anchor=tk.W)

        actions = [
            ("📱  Run Last Task",      self.on_run_last),
            ("💾  Save Output",        self.on_save_output),
            ("⚡  Demo Calculator",    self.on_demo),
            ("🕒  What is the Time?",  lambda: self.execute_command("what is the time")),
            ("📅  What is the Date?",  lambda: self.execute_command("what is the date")),
        ]

        for label, cmd in actions:
            mk_btn(btn_row, label, cmd, bg=C_BTN_DRK, fg=C_TEXT, width=20
                   ).pack(side=tk.LEFT, padx=4)

    # ══════ THREAD-SAFE UPDATERS ══════
    def update_status_safe(self, text):
        self.after(0, lambda: self.lbl_status.config(text=f"● Status: {text}"))

    def append_exec_safe(self, text):
        def _f():
            self.txt_exec.config(state=tk.NORMAL)
            self.txt_exec.insert(tk.END, text + "\n")
            self.txt_exec.see(tk.END)
            self.txt_exec.config(state=tk.DISABLED)
        self.after(0, _f)

    def clear_displays_safe(self):
        def _f():
            for w in (self.txt_exec, self.txt_output):
                w.config(state=tk.NORMAL)
                w.delete("1.0", tk.END)
                w.config(state=tk.DISABLED)
        self.after(0, _f)

    # ══════ EVENT HANDLERS ══════
    def on_start_listen(self):
        self.is_listening = True
        self.update_status_safe("Listening…")
        self.lbl_wave.config(fg=C_GLOW)
        self.clear_displays_safe()
        threading.Thread(target=self._voice_thread, daemon=True).start()

    def on_stop_listen(self):
        self.is_listening = False
        self.update_status_safe("Idle")
        self.lbl_wave.config(fg=C_GLOW_DIM)

    def on_edit_command(self):
        if self.entry_cmd["state"] == "readonly":
            self.entry_cmd.config(state=tk.NORMAL, fg=C_TEXT)
        else:
            self.entry_cmd.config(state="readonly", fg=C_GLOW)
            self.execute_command(self.var_command.get())

    def on_run_fallback(self):
        cmd = self.var_fallback.get().strip()
        if cmd:
            self.execute_command(cmd)

    def on_run_last(self):
        self.execute_command("run last task")

    def on_save_output(self):
        self.execute_command(f"save output as assistant_log_{int(time.time())}.txt")

    def on_demo(self):
        self.execute_command("create a calculator in python")

    def on_save_override(self):
        name = self.var_filename.get().strip()
        if name:
            result = self.controller.override_last_file_name(name)
            self._render_result(result)

    def speak_output(self):
        text = self.txt_output.get("1.0", tk.END).strip()
        if text:
            threading.Thread(target=speak, args=(text,), daemon=True).start()

    def stop_speech(self):
        pass   # legacy.tts manages its own queue

    def execute_command(self, cmd: str):
        print(f"[GUI INPUT] {cmd}")
        print("[GUI ROUTING] Using process_command")
        
        # Clear displays before executing
        self.clear_displays_safe()
        
        # Use EXACT same pipeline as voice input
        from legacy.assistant import process_input
        response = process_input(cmd)
        
        if response:
            self._render_result(response)

    # ══════ BACKGROUND THREADS ══════
    def _voice_thread(self):
        import time as _t
        _t.sleep(2)
        cmd = "create a calculator in python"
        if self.is_listening:
            self.after(0, self.execute_command, cmd)
            self.after(0, self.on_stop_listen)

    def _render_result(self, result):
        # process_input returns string directly, not dict
        if isinstance(result, str):
            output = result
        elif isinstance(result, dict):
            output = result.get("output", str(result))
        else:
            output = str(result)
        
        print(f"[GUI OUTPUT] {output}")
            
        # Update output panel with dynamic assistant prefix
        _name = self._get_assistant_name()
        self.txt_output.config(state=tk.NORMAL)
        self.txt_output.delete("1.0", tk.END)
        self.txt_output.insert(tk.END, f"{_name}: {output}")
        self.txt_output.config(state=tk.DISABLED)
        
        # Update command display
        if hasattr(self, 'var_command'):
            self.var_command.set(output[:100] + "..." if len(output) > 100 else output)
        
        # Speak output if not empty
        if output.strip():
            threading.Thread(target=speak, args=(output,), daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    app = AssistantUI(root)
    app.deiconify()
    root.mainloop()
