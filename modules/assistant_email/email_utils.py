import os
from typing import Optional, Dict, Any, List

def get_text_input(title: str, prompt: str) -> Optional[str]:
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        result = simpledialog.askstring(title, prompt, parent=root)
        root.destroy()
        return result
    except Exception:
        return None

def get_password_input(title: str, prompt: str) -> Optional[str]:
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        result = simpledialog.askstring(title, prompt, show='*', parent=root)
        root.destroy()
        return result
    except Exception:
        return None

def get_multiline_input(title: str, prompt: str, initial_text: str = "") -> str:
    try:
        import tkinter as tk
        from tkinter import scrolledtext
        root = tk.Tk()
        root.title(title)
        tk.Label(root, text=prompt, padx=10, pady=10).pack()
        text_area = scrolledtext.ScrolledText(root, width=50, height=15)
        text_area.pack(padx=20, pady=10)
        text_area.insert(tk.END, initial_text)
        result = {"text": initial_text}
        def on_submit():
            result["text"] = text_area.get("1.0", tk.END).strip()
            root.destroy()
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Submit", command=on_submit, width=15).pack(side=tk.LEFT, padx=5)
        root.mainloop()
        return result["text"]
    except Exception:
        return initial_text

def show_email_editor(
    subject: str,
    body: str,
    recipient_email: Optional[str] = None,
    sender_email: Optional[str] = None,
    sender_pass: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    attachments: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Delegates to the unified email editor in email_ui."""
    from .email_ui import show_email_editor as _show_editor
    return _show_editor(
        subject=subject,
        body=body,
        recipient_email=recipient_email,
        sender_email=sender_email,
        sender_pass=sender_pass,
        cc=cc,
        bcc=bcc,
        attachments=attachments
    )

def show_message(title: str, message: str, icon: str = "info"):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        if icon == "error":
            messagebox.showerror(title, message, parent=root)
        elif icon == "warning":
            messagebox.showwarning(title, message, parent=root)
        else:
            messagebox.showinfo(title, message, parent=root)
        root.destroy()
    except Exception:
        pass
