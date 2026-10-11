"""
Smart Assistant — Thin Client Entry Point
=========================================
This is the PRODUCTION DESKTOP CLIENT entry point.

It launches ONLY the PyQt6 UI.
All AI/backend processing happens on the remote production server.
No database, no ML models, no backend modules are imported.

Communication: PyQt6 UI → HTTPS REST API → Production Backend
"""

import sys
import os
from pathlib import Path

# ── Ensure project root is on sys.path ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Fix stdout encoding on Windows ──────────────────────────────────────────
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ── Load environment (only API_BASE_URL, APP_ENV — no DB secrets) ───────────
try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # dotenv not strictly required — env vars can be set by installer


def main():
    """Launch the Smart Assistant thin client desktop application."""
    print("[CLIENT] Smart Assistant Desktop Client starting...")
    print(f"[CLIENT] APP_ENV = {os.getenv('APP_ENV', 'development')}")
    print(f"[CLIENT] API_BASE_URL = {os.getenv('API_BASE_URL', '(default)')}")

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt

    # High-DPI support
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except AttributeError:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("Smart Assistant")
    app.setOrganizationName("Trevon Labs")
    app.setQuitOnLastWindowClosed(False)

    # Import UI modules (these only import PyQt6 + api_client — no backend)
    from modules.ui.client_app import ClientApp
    client = ClientApp(app)
    client.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
