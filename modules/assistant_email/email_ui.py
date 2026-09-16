import tkinter as tk
from tkinter import messagebox, scrolledtext

def get_email_credentials_popup():
    """
    Shows a popup to enter email and app password.
    Returns: (email, password)
    """
    result = {"email": "", "password": "", "confirmed": False}

    def on_save():
        result["email"] = email_entry.get().strip()
        result["password"] = pass_entry.get().strip()
        if not result["email"] or not result["password"]:
            messagebox.showwarning("Incomplete", "Please enter both email and app password.")
            return
        result["confirmed"] = True
        root.destroy()

    root = tk.Tk()
    try:
        from instance.config import settings as _cfg
        _asst = _cfg.get_assistant_name() or "Assistant"
    except Exception:
        _asst = "Assistant"
    root.title(f"{_asst} Email Configuration")
    root.geometry("400x250")
    root.attributes('-topmost', True)

    tk.Label(root, text="Enter your Email ID:", font=("Arial", 10)).pack(pady=(20, 5))
    email_entry = tk.Entry(root, width=40)
    email_entry.pack(pady=5)

    tk.Label(root, text="Enter GMail App Password:", font=("Arial", 10)).pack(pady=(10, 5))
    pass_entry = tk.Entry(root, width=40, show="*")
    pass_entry.pack(pady=5)

    tk.Button(root, text=" Save Credentials ", command=on_save, bg="#4CAF50", fg="white", font=("Arial", 10, "bold")).pack(pady=20)

    root.mainloop()

    if result["confirmed"]:
        return result["email"], result["password"]
    return None, None

def show_email_editor(subject, body, recipient_email=None, sender_email=None, sender_pass=None):
    """
    Shows an editable popup for subject and body.
    Returns: {"subject": str, "body": str, "confirmed": bool, "sent": bool}
    """
    print(f"[DEBUG] POPUP: Received subject: '{subject}'")
    print(f"[DEBUG] POPUP: Received body: '{body}'")
    print(f"[DEBUG] POPUP: Body length: {len(body)}")
    
    result = {"subject": subject, "body": body, "confirmed": False, "sent": False}

    def on_send():
        result["subject"] = subject_entry.get()
        result["body"] = text_area.get("1.0", tk.END).strip()
        
        # Send email if all parameters are provided
        if recipient_email and sender_email and sender_pass:
            try:
                from .email_sender import send_email
                if send_email(recipient_email, result["subject"], result["body"], sender_email, sender_pass):
                    result["sent"] = True
                    result["confirmed"] = True
                    messagebox.showinfo("Success", "Email sent successfully!")
                else:
                    messagebox.showerror("Error", "Failed to send email. Please check your credentials and connection.")
                    return
            except Exception as e:
                messagebox.showerror("Error", f"Error sending email: {e}")
                return
        else:
            # If no email parameters provided, just confirm the edit
            result["confirmed"] = True
        
        root.destroy()

    def on_cancel():
        result["confirmed"] = False
        result["sent"] = False
        root.destroy()

    root = tk.Tk()
    root.title("Edit Email Before Sending")
    root.geometry("600x500")
    root.attributes('-topmost', True)

    # Main content frame
    main_frame = tk.Frame(root)
    main_frame.pack(fill="both", expand=True, padx=20, pady=10)

    # Subject field
    tk.Label(main_frame, text="Subject:", font=("Arial", 10, "bold")).pack(pady=(10, 0))
    subject_entry = tk.Entry(main_frame, width=80)
    subject_entry.insert(0, subject)
    subject_entry.pack(pady=5)

    # Body field
    tk.Label(main_frame, text="Body:", font=("Arial", 10, "bold")).pack(pady=(10, 0))
    text_area = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, width=70, height=20)
    print(f"[DEBUG] POPUP: Inserting body into text area: '{body}'")
    text_area.insert(tk.END, body)
    text_area.pack(fill="both", expand=True, pady=10)

    # Bottom frame for buttons
    bottom_frame = tk.Frame(root)
    bottom_frame.pack(side="bottom", fill="x", pady=10)

    # Buttons with distinct colors for visibility
    send_btn = tk.Button(bottom_frame, text="Send Email", command=on_send, bg="green", fg="white", font=("Arial", 10, "bold"), width=12)
    cancel_btn = tk.Button(bottom_frame, text="Cancel", command=on_cancel, bg="red", fg="white", font=("Arial", 10, "bold"), width=12)
    
    send_btn.pack(side="left", padx=20)
    cancel_btn.pack(side="right", padx=20)

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.mainloop()

    return result
