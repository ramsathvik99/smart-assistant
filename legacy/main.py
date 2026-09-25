# main.py — Smart Assistant UI Entry Point
# PRODUCTION UI: PyQt6 (modules.ui.pyqt_app.AssistantApp)
# The Tkinter code below is retained as reference but is NOT active.

import os
import sys
import threading

# ── PyQt6 production entry point ──────────────────────────────────────────────
def main():
    """
    Main entry point for the Smart Assistant.
    Starts the PyQt6 UI which handles login, floating launcher, and all
    window management. Backend (voice, brain, router, DB) is started
    inside AssistantApp after successful authentication.
    """
    # Ensure the project root is on sys.path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from modules.ui.pyqt_app import AssistantApp
    app = AssistantApp()
    app.run()


if __name__ == "__main__":
    main()


# ─────────────────────────────────────────────────────────────────────────────
# RETIRED TKINTER CODE (kept as reference, NOT executed)
# ─────────────────────────────────────────────────────────────────────────────
# The following Tkinter/CustomTkinter code was the previous production UI.
# It is preserved here for historical reference but is no longer called.
# All production startup flows through AssistantApp (PyQt6) above.
#
# import tkinter as tk
# from tkinter import ttk
# try:
#     import customtkinter as ctk
# except ImportError:
#     ctk = None
# from legacy.floating_button import FloatingButton          # RETIRED
# from legacy.login_window import LoginWindow                # RETIRED
# from modules.ui.assistant_ui import AssistantUI            # RETIRED
#
# def _tkinter_main():  # NO LONGER CALLED
#     global root
#     root = tk.Tk()
#     root.withdraw()
#     ...
