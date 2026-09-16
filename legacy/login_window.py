import tkinter as tk
from tkinter import messagebox
import traceback
import legacy.tts as tts
from legacy.memory_manager import get_or_create_user, get_assistant_name_db, set_assistant_name_db
from legacy.auth_helpers import login_success


# ─────────────────────────────────────────────────────────────────────────────
# NAME YOUR ASSISTANT DIALOG
# ─────────────────────────────────────────────────────────────────────────────
class NameAssistantDialog:
    """
    First-time popup: asks the user to name their assistant.
    Only shown when a user logs in and has no assistant_name in user_preferences.
    Styled with the same dark theme as LoginWindow.
    """

    def __init__(self, parent, user_id, username, on_done):
        """
        parent   – parent Toplevel or Tk window (for centering)
        user_id  – int, to save into user_preferences
        username – str, shown in greeting
        on_done  – callable(name: str) called once the name is saved
        """
        self.user_id = user_id
        self.username = username
        self.on_done = on_done
        self.chosen_name = None

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Name Your Assistant")
        self.dialog.geometry("420x300")
        self.dialog.configure(bg="#1e1e2e")
        self.dialog.resizable(False, False)
        # Block the parent window until this is completed
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)

        self._center(parent)
        self._build_ui()

    def _center(self, parent):
        self.dialog.update_idletasks()
        w, h = 420, 300
        sw = self.dialog.winfo_screenwidth()
        sh = self.dialog.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.dialog.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        container = tk.Frame(self.dialog, bg="#1e1e2e", padx=40, pady=30)
        container.pack(fill=tk.BOTH, expand=True)

        # Icon / header
        tk.Label(
            container,
            text="✨  Name Your Assistant",
            font=("Segoe UI", 16, "bold"),
            bg="#1e1e2e",
            fg="#6366f1"
        ).pack(pady=(0, 8))

        tk.Label(
            container,
            text=f"Hi {self.username}! What would you like to call your assistant?",
            font=("Segoe UI", 10),
            bg="#1e1e2e",
            fg="#cdd6f4",
            wraplength=340,
            justify="center"
        ).pack(pady=(0, 20))

        # Name entry
        self.name_var = tk.StringVar()
        self.name_entry = tk.Entry(
            container,
            textvariable=self.name_var,
            font=("Segoe UI", 12),
            bg="#313244",
            fg="white",
            insertbackground="white",
            relief=tk.FLAT,
            justify="center"
        )
        self.name_entry.pack(fill=tk.X, ipady=8, pady=(0, 6))
        self.name_entry.insert(0, "e.g. Aria, Friday, Jarvis...")
        self.name_entry.bind("<FocusIn>", self._clear_placeholder)
        self.name_entry.bind("<Return>", lambda e: self._submit())
        self.name_entry.config(fg="grey")

        # Hint
        tk.Label(
            container,
            text="You can change this later in settings.",
            font=("Segoe UI", 8),
            bg="#1e1e2e",
            fg="#6c7086"
        ).pack(pady=(0, 16))

        # Continue button
        tk.Button(
            container,
            text="Continue  →",
            font=("Segoe UI", 10, "bold"),
            bg="#6366f1",
            fg="white",
            activebackground="#5558d1",
            activeforeground="white",
            relief=tk.FLAT,
            cursor="hand2",
            command=self._submit
        ).pack(fill=tk.X, ipady=6)

    def _clear_placeholder(self, event=None):
        current = self.name_entry.get()
        if current.startswith("e.g."):
            self.name_entry.delete(0, "end")
            self.name_entry.config(fg="white")

    def _submit(self):
        name = self.name_var.get().strip()
        if not name or name.startswith("e.g."):
            messagebox.showwarning(
                "Name Required",
                "Please enter a name for your assistant.",
                parent=self.dialog
            )
            return

        # Persist to DB
        set_assistant_name_db(self.user_id, name)
        self.chosen_name = name

        # Update runtime config
        from instance.config import settings as CONFIG
        CONFIG.CURRENT_ASSISTANT_NAME = name

        self.dialog.grab_release()
        self.dialog.destroy()
        self.on_done(name)

    def _on_close(self):
        """If user closes dialog without naming, generate a generic default."""
        messagebox.showinfo(
            "Name Required",
            "You must name your assistant to continue.",
            parent=self.dialog
        )


# ─────────────────────────────────────────────────────────────────────────────
# LOGIN WINDOW
# ─────────────────────────────────────────────────────────────────────────────
class LoginWindow:
    def __init__(self, root, on_login_success):
        self.root = root  # This is the hidden root window
        self.on_login_success = on_login_success

        print("[DEBUG] LoginWindow initializing...")
        try:
            self.window = tk.Toplevel(root)
            self.window.title("Assistant - Login")
            self.window.geometry("400x320")
            self.window.configure(bg="#1e1e2e")
            self.window.resizable(False, False)

            # Handle window close
            self.window.protocol("WM_DELETE_WINDOW", self.on_close)

            # Center the window
            self.center_window()
            self.init_ui()
        except Exception as e:
            print(f"[ERROR] LoginWindow initialization failed: {e}")
            traceback.print_exc()
            raise

    def center_window(self):
        self.window.update_idletasks()
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        x = (self.window.winfo_screenwidth() // 2) - (width // 2)
        y = (self.window.winfo_screenheight() // 2) - (height // 2)
        self.window.geometry('{}x{}+{}+{}'.format(width, height, x, y))

    def init_ui(self):
        # Container frame
        container = tk.Frame(self.window, bg="#1e1e2e", padx=40, pady=40)
        container.pack(fill=tk.BOTH, expand=True)

        # Title — no hardcoded "Nova"
        title_lbl = tk.Label(
            container,
            text="AI Assistant",
            font=("Segoe UI", 18, "bold"),
            bg="#1e1e2e",
            fg="#6366f1"
        )
        title_lbl.pack(pady=(0, 20))

        # Username Entry
        self.user_var = tk.StringVar()
        self.user_entry = tk.Entry(
            container,
            textvariable=self.user_var,
            font=("Segoe UI", 10),
            bg="#313244",
            fg="white",
            insertbackground="white",
            relief=tk.FLAT
        )
        self.user_entry.pack(fill=tk.X, pady=(0, 15), ipady=8)
        self.user_entry.insert(0, "Username")
        self.user_entry.bind("<FocusIn>", lambda e: self.on_entry_click(self.user_entry, "Username"))
        self.user_entry.bind("<FocusOut>", lambda e: self.on_focus_out(self.user_entry, "Username"))

        # Password Entry
        self.pass_var = tk.StringVar()
        self.pass_entry = tk.Entry(
            container,
            textvariable=self.pass_var,
            font=("Segoe UI", 10),
            bg="#313244",
            fg="white",
            insertbackground="white",
            relief=tk.FLAT,
            show="*"
        )
        self.pass_entry.pack(fill=tk.X, pady=(0, 20), ipady=8)

        self.pass_entry.insert(0, "Password")
        self.pass_entry.bind("<FocusIn>", lambda e: self.on_pass_entry_click())
        self.pass_entry.bind("<FocusOut>", lambda e: self.on_pass_focus_out())

        # Login Button
        self.login_btn = tk.Button(
            container,
            text="Login",
            font=("Segoe UI", 10, "bold"),
            bg="#6366f1",
            fg="white",
            activebackground="#5558d1",
            activeforeground="white",
            relief=tk.FLAT,
            cursor="hand2",
            command=self.do_login
        )
        self.login_btn.pack(fill=tk.X, ipady=5)

        # Bind events
        self.pass_entry.bind("<Return>", lambda e: self.do_login())
        self.user_entry.bind("<Return>", lambda e: self.pass_entry.focus_set())


    def on_entry_click(self, entry, placeholder):
        if entry.get() == placeholder:
            entry.delete(0, "end")
            entry.config(fg='white')

    def on_focus_out(self, entry, placeholder):
        if entry.get() == '':
            entry.insert(0, placeholder)
            entry.config(fg='grey')

    def on_pass_entry_click(self):
        if self.pass_entry.get() == "Password":
            self.pass_entry.delete(0, "end")
            self.pass_entry.config(fg='white', show="*")

    def on_pass_focus_out(self):
        if self.pass_entry.get() == '':
            self.pass_entry.insert(0, "Password")
            self.pass_entry.config(fg='grey', show="")

    def speak_msg(self, text):
        tts.speak(text)

    def do_login(self):
        username = self.user_var.get().strip()
        password = self.pass_var.get().strip()

        print("[LOGIN] Attempting login for user:", repr(username))
        print("[LOGIN] Password provided:", bool(password))

        # Remove placeholders if present
        if username == "Username":
            username = ""
        if password == "Password":
            password = ""

        if not username or not password:
            self.speak_msg("Please enter both username and password.")
            messagebox.showwarning("Input Error", "Please enter both username and password.", parent=self.window)
            return

        user_id, status = get_or_create_user(username, password)

        if user_id is None:
            self.speak_msg("Incorrect password. Please try again.")
            messagebox.showerror("Login Failed", "Incorrect password.", parent=self.window)
            return

        # Set session state
        login_success(user_id, username)

        # Check if this user already has an assistant name
        existing_name = get_assistant_name_db(user_id)

        if status == "NEW_USER" or not existing_name:
            # First time — show name dialog before continuing
            def _after_name_chosen(chosen_name):
                """Called by NameAssistantDialog when name is saved."""
                if status == "NEW_USER":
                    greeting = f"Hi {username}. I'm {chosen_name}. I'm happy to meet you."
                else:
                    greeting = f"Hi {username}. You've named your assistant {chosen_name}. Let's get started."
                self.speak_msg(greeting)
                self._proceed_to_app()

            self.window.withdraw()  # Hide login window while dialog is shown
            NameAssistantDialog(
                self.root,
                user_id=user_id,
                username=username,
                on_done=_after_name_chosen
            )

        else:
            # Returning user — greet using their assistant's name
            self.speak_msg(f"Welcome back {username}. {existing_name} is ready when you are.")
            self._proceed_to_app()

    def _proceed_to_app(self):
        """Destroy login window and invoke the success callback."""
        if self.on_login_success:
            self.on_login_success()
        try:
            self.window.destroy()
        except Exception:
            pass

    def on_close(self):
        self.root.destroy()
        import sys
        sys.exit(0)

    def show(self):
        self.window.deiconify()
        self.window.lift()
