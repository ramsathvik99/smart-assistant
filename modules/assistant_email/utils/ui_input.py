import tkinter as tk
from tkinter import simpledialog, messagebox, scrolledtext

def get_text_input(title, prompt):
    """
    Shows a simple text input dialog.
    """
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    result = simpledialog.askstring(title, prompt, parent=root)
    root.destroy()
    return result

def get_password_input(title, prompt):
    """
    Shows a masked password input dialog.
    """
    root = tk.Tk()
    root.withdraw()
    result = simpledialog.askstring(title, prompt, show='*', parent=root)
    root.destroy()
    return result

def get_multiline_input(title, prompt, initial_text=""):
    """
    Shows a multiline text box with a Submit button.
    """
    root = tk.Tk()
    root.title(title)
    
    # Label
    tk.Label(root, text=prompt, padx=10, pady=10).pack()
    
    # Scrolled Text area
    text_area = scrolledtext.ScrolledText(root, width=50, height=15)
    text_area.pack(padx=20, pady=10)
    text_area.insert(tk.END, initial_text)
    
    result = {"text": initial_text}
    
    def on_submit():
        result["text"] = text_area.get("1.0", tk.END).strip()
        root.destroy()
        
    def on_cancel():
        result["text"] = None
        root.destroy()
    
    # Buttons
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=10)
    
    tk.Button(btn_frame, text="Submit", command=on_submit, width=15).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="Cancel", command=on_cancel, width=15).pack(side=tk.LEFT, padx=5)
    
    # Center window
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f'+{x}+{y}')
    
    root.mainloop()
    return result["text"]

def show_message(title, message, icon="info"):
    """
    Shows an info, warning, or error message box.
    """
    root = tk.Tk()
    root.withdraw()
    if icon == "error":
        messagebox.showerror(title, message, parent=root)
    elif icon == "warning":
        messagebox.showwarning(title, message, parent=root)
    else:
        messagebox.showinfo(title, message, parent=root)
    root.destroy()
