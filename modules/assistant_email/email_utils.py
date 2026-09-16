import tkinter as tk
from tkinter import simpledialog, messagebox, scrolledtext

def get_text_input(title, prompt):
    root = tk.Tk()
    root.withdraw()
    result = simpledialog.askstring(title, prompt, parent=root)
    root.destroy()
    return result

def get_password_input(title, prompt):
    root = tk.Tk()
    root.withdraw()
    result = simpledialog.askstring(title, prompt, show='*', parent=root)
    root.destroy()
    return result

def get_multiline_input(title, prompt, initial_text=""):
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

def show_email_editor(subject, body):
    """
    Shows an editable popup for subject and body.
    Returns: {"subject": str, "body": str, "confirmed": bool}
    """
    result = {"subject": subject, "body": body, "confirmed": False}

    def on_ok():
        result["subject"] = subject_entry.get()
        result["body"] = text_area.get("1.0", tk.END).strip()
        result["confirmed"] = True
        root.destroy()

    def on_cancel():
        result["confirmed"] = False
        root.destroy()

    root = tk.Tk()
    root.title("Edit Email Before Sending")
    root.geometry("600x550")
    
    # Ensure it's on top
    root.attributes('-topmost', True)

    # Subject field
    tk.Label(root, text="Subject:", font=("Arial", 10, "bold")).pack(pady=(10, 0))
    subject_entry = tk.Entry(root, width=80)
    subject_entry.insert(0, subject)
    subject_entry.pack(pady=5, padx=20)

    # Body field
    tk.Label(root, text="Body:", font=("Arial", 10, "bold")).pack(pady=(10, 0))
    text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=70, height=20)
    text_area.insert(tk.END, body)
    text_area.pack(pady=10, padx=20)

    # Buttons
    button_frame = tk.Frame(root)
    button_frame.pack(pady=20)

    tk.Button(button_frame, text="   OK   ", command=on_ok, bg="#4CAF50", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=20)
    tk.Button(button_frame, text=" Cancel ", command=on_cancel, bg="#f44336", fg="white", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=20)

    root.protocol("WM_DELETE_WINDOW", on_cancel) # Handle window close as cancel
    root.mainloop()

    return result

def show_message(title, message, icon="info"):
    root = tk.Tk()
    root.withdraw()
    if icon == "error":
        messagebox.showerror(title, message, parent=root)
    elif icon == "warning":
        messagebox.showwarning(title, message, parent=root)
    else:
        messagebox.showinfo(title, message, parent=root)
    root.destroy()
