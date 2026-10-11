import os
from typing import Optional, Tuple, Dict, Any, List

def get_email_credentials_popup() -> Tuple[Optional[str], Optional[str]]:
    """
    Shows a popup to enter email and app password.
    Returns: (email, password)
    """
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        return None, None

    result = {"email": "", "password": "", "confirmed": False}

    def on_save():
        result["email"] = email_entry.get().strip()
        result["password"] = pass_entry.get().strip()
        if not result["email"] or not result["password"]:
            messagebox.showwarning("Incomplete", "Please enter both email and app password.")
            return
        result["confirmed"] = True
        root.destroy()

    try:
        root = tk.Tk()
        from instance.config import settings as _cfg
        _asst = _cfg.get_assistant_name() or "Assistant"
    except Exception:
        return None, None

    try:
        root.title(f"{_asst} Email Configuration")
        root.geometry("420x280")
        root.attributes('-topmost', True)

        tk.Label(root, text="Enter your Email Address:", font=("Segoe UI", 10)).pack(pady=(20, 5))
        email_entry = tk.Entry(root, width=42, font=("Segoe UI", 10))
        email_entry.pack(pady=5)

        tk.Label(root, text="Enter Google / Provider App Password:", font=("Segoe UI", 10)).pack(pady=(10, 5))
        pass_entry = tk.Entry(root, width=42, show="*", font=("Segoe UI", 10))
        pass_entry.pack(pady=5)

        tk.Button(
            root, text=" Save Credentials ", command=on_save,
            bg="#2E7D32", fg="white", font=("Segoe UI", 10, "bold"), padx=10, pady=5
        ).pack(pady=20)

        root.mainloop()
    except Exception:
        return None, None

    if result["confirmed"]:
        return result["email"], result["password"]
    return None, None

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
    """
    Shows a comprehensive review & editor popup showing:
    To, CC, BCC, Subject, Attachments list, and Body.
    Returns: {
        "subject": str,
        "body": str,
        "recipient": str,
        "cc": str,
        "bcc": str,
        "attachments": list,
        "confirmed": bool,
        "sent": bool,
        "action": "send" | "save_draft" | "cancel"
    }
    """
    try:
        import tkinter as tk
        from tkinter import messagebox, scrolledtext, filedialog
    except ImportError:
        return {
            "subject": subject, "body": body, "recipient": recipient_email,
            "cc": cc, "bcc": bcc, "attachments": attachments or [],
            "confirmed": True, "sent": False, "action": "approved"
        }

    current_attachments = list(attachments or [])
    result = {
        "subject": subject,
        "body": body,
        "recipient": recipient_email or "",
        "cc": cc or "",
        "bcc": bcc or "",
        "attachments": current_attachments,
        "confirmed": False,
        "sent": False,
        "action": "cancel"
    }

    try:
        root = tk.Tk()
        root.title("Review & Edit Email Before Sending")
        root.geometry("680x700")
        root.attributes('-topmost', True)

        main_frame = tk.Frame(root)
        main_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # To field
        tk.Label(main_frame, text="To:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        to_entry = tk.Entry(main_frame, width=70, font=("Segoe UI", 10))
        to_entry.insert(0, recipient_email or "")
        to_entry.pack(fill="x", pady=(0, 6))

        # CC / BCC row
        cc_row = tk.Frame(main_frame)
        cc_row.pack(fill="x", pady=(0, 6))

        tk.Label(cc_row, text="CC:", font=("Segoe UI", 9, "bold")).pack(side="left")
        cc_entry = tk.Entry(cc_row, font=("Segoe UI", 10))
        cc_entry.insert(0, cc or "")
        cc_entry.pack(side="left", fill="x", expand=True, padx=(5, 15))

        tk.Label(cc_row, text="BCC:", font=("Segoe UI", 9, "bold")).pack(side="left")
        bcc_entry = tk.Entry(cc_row, font=("Segoe UI", 10))
        bcc_entry.insert(0, bcc or "")
        bcc_entry.pack(side="left", fill="x", expand=True, padx=5)

        # Subject field
        tk.Label(main_frame, text="Subject:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        subject_entry = tk.Entry(main_frame, width=70, font=("Segoe UI", 10))
        subject_entry.insert(0, subject)
        subject_entry.pack(fill="x", pady=(0, 6))

        # Attachments label & frame
        att_frame = tk.Frame(main_frame)
        att_frame.pack(fill="x", pady=(0, 6))

        att_label = tk.Label(
            att_frame,
            text=f"Attachments ({len(current_attachments)}): " + (", ".join([os.path.basename(a) for a in current_attachments]) if current_attachments else "None"),
            font=("Segoe UI", 9, "italic"),
            anchor="w"
        )
        att_label.pack(side="left", fill="x", expand=True)

        def add_att():
            fpath = filedialog.askopenfilename()
            if fpath and fpath not in current_attachments:
                current_attachments.append(fpath)
                att_label.config(text=f"Attachments ({len(current_attachments)}): " + ", ".join([os.path.basename(a) for a in current_attachments]))

        def clear_att():
            current_attachments.clear()
            att_label.config(text="Attachments (0): None")

        tk.Button(att_frame, text="+ Add File", command=add_att, font=("Segoe UI", 8)).pack(side="right", padx=2)
        tk.Button(att_frame, text="Clear", command=clear_att, font=("Segoe UI", 8)).pack(side="right", padx=2)

        # Body field
        tk.Label(main_frame, text="Message Body:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        text_area = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, font=("Segoe UI", 10), height=16)
        text_area.insert(tk.END, body)
        text_area.pack(fill="both", expand=True, pady=(0, 10))

        # Buttons
        bottom_frame = tk.Frame(root)
        bottom_frame.pack(side="bottom", fill="x", padx=20, pady=12)

        def on_send():
            result["recipient"] = to_entry.get().strip()
            result["cc"] = cc_entry.get().strip()
            result["bcc"] = bcc_entry.get().strip()
            result["subject"] = subject_entry.get().strip()
            result["body"] = text_area.get("1.0", tk.END).strip()
            result["attachments"] = current_attachments
            result["confirmed"] = True
            result["action"] = "send"

            if sender_email and sender_pass and result["recipient"]:
                try:
                    from .email_sender import send_email
                    send_res = send_email(
                        to_email=result["recipient"],
                        subject=result["subject"],
                        body=result["body"],
                        email_id=sender_email,
                        email_pass=sender_pass,
                        attachments=result["attachments"],
                        cc=result["cc"] or None,
                        bcc=result["bcc"] or None
                    )
                    if send_res:
                        result["sent"] = True
                        messagebox.showinfo("Success", "Email sent successfully!")
                    else:
                        messagebox.showerror("Error", f"Failed to send email: {send_res.get('message', 'Unknown error')}")
                        return
                except Exception as e:
                    messagebox.showerror("Error", f"Error sending email: {e}")
                    return
            root.destroy()

        def on_draft():
            result["recipient"] = to_entry.get().strip()
            result["cc"] = cc_entry.get().strip()
            result["bcc"] = bcc_entry.get().strip()
            result["subject"] = subject_entry.get().strip()
            result["body"] = text_area.get("1.0", tk.END).strip()
            result["attachments"] = current_attachments
            result["confirmed"] = True
            result["sent"] = False
            result["action"] = "save_draft"
            root.destroy()

        def on_cancel():
            result["confirmed"] = False
            result["sent"] = False
            result["action"] = "cancel"
            root.destroy()

        def on_close_window():
            # User dismissed or closed window without clicking Cancel button
            result["recipient"] = to_entry.get().strip() or recipient_email or ""
            result["cc"] = cc_entry.get().strip() or ""
            result["bcc"] = bcc_entry.get().strip() or ""
            result["subject"] = subject_entry.get().strip() or subject
            result["body"] = text_area.get("1.0", tk.END).strip() or body
            result["attachments"] = current_attachments
            result["confirmed"] = False
            result["sent"] = False
            result["action"] = "dismissed"
            root.destroy()

        tk.Button(bottom_frame, text="Send Email", command=on_send, bg="#2E7D32", fg="white", font=("Segoe UI", 10, "bold"), width=13, pady=4).pack(side="left", padx=(0, 10))
        tk.Button(bottom_frame, text="Save as Draft", command=on_draft, bg="#1976D2", fg="white", font=("Segoe UI", 10), width=13, pady=4).pack(side="left", padx=5)
        tk.Button(bottom_frame, text="Cancel", command=on_cancel, bg="#C62828", fg="white", font=("Segoe UI", 10), width=10, pady=4).pack(side="right")

        root.protocol("WM_DELETE_WINDOW", on_close_window)
        root.mainloop()
    except Exception:
        # Headless or display error fallback
        return {
            "subject": subject, "body": body, "recipient": recipient_email or "",
            "cc": cc or "", "bcc": bcc or "", "attachments": attachments or [],
            "confirmed": True, "sent": False, "action": "approved"
        }

    return result
