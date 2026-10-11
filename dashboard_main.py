"""
Dashboard Entry Point — Next-Gen AI Assistant Control Center
=============================================================

Launches the premium desktop dashboard UI for the existing smart assistant
project, without replacing or rewriting the backend core.

This entry point:
1. Ensures the working directory is the project root.
2. Loads environment variables, PostgreSQL pool, and the canonical Settings.
3. Initializes Qt with the dashboard design system stylesheet.
4. Shows the DashboardMainWindow which uses service adapters to:
   - Present real user/assistant identity
   - Display live assistant state (idle/thinking/speaking/executing/listening)
   - Expose real services (email, calendar, reminders, devices, smart home,
     documents, memory, automation, diagnostics)
   - Save every setting back to the database + runtime config.

Existing `assistant.py` remains fully intact. Use this file when you want
the premium new UI as the main interface.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path


# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so absolute imports (core.*, modules.*,
# extensions.*, legacy.*, skills.*) work regardless of how the script is
# launched.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _load_env():
    """Load .env before any module that reads os.environ."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except Exception:
        # dotenv is optional — parse manually as a fallback.
        try:
            for raw in env_path.read_text().splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip().strip('"'), v.strip().strip('"'))
        except Exception:
            pass


_load_env()


# ---------------------------------------------------------------------------
# Early Qt availability check
# ---------------------------------------------------------------------------
try:
    from PyQt6.QtWidgets import QApplication, QSplashScreen, QMessageBox
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QIcon
except Exception as e:
    sys.stderr.write(
        "PyQt6 is required for the dashboard UI.\n"
        "Install it with:  pip install PyQt6 qtawesome Pillow pyqtdarktheme\n"
        f"Detail: {e}\n"
    )
    sys.exit(2)


def _make_splash() -> QSplashScreen:
    pm = QPixmap(520, 320)
    pm.fill(QColor("#05080c"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Outer ring
    from PyQt6.QtCore import QRectF
    pen = p.pen()
    pen.setColor(QColor("#0b1420"))
    pen.setWidth(2)
    p.setPen(pen)
    p.drawRoundedRect(QRectF(10, 10, 500, 300), 22, 22)

    # Accent halo
    try:
        from modules.ui.design_system import C as _C
        accent = getattr(_C, "ACCENT_CYAN", "#00d4ff")
    except Exception:
        accent = "#00d4ff"
    acolor = QColor(accent)
    pen.setColor(acolor)
    pen.setWidthF(1.6)
    p.setPen(pen)
    p.drawRoundedRect(QRectF(10, 10, 500, 300), 22, 22)

    p.setPen(Qt.PenStyle.NoPen)
    from PyQt6.QtGui import QRadialGradient
    grad = QRadialGradient(260, 130, 160)
    acolor.setAlpha(70)
    grad.setColorAt(0.0, acolor)
    acolor.setAlpha(0)
    grad.setColorAt(1.0, acolor)
    p.setBrush(grad)
    p.drawEllipse(120, 20, 280, 200)

    # Title
    p.setPen(QColor(accent))
    f = QFont("Segoe UI", 10)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 5)
    f.setWeight(QFont.Weight.Bold)
    p.setFont(f)
    p.drawText(40, 78, "NEXT-GEN  AI  ASSISTANT")

    p.setPen(QColor("#e6f1ff"))
    f = QFont("Segoe UI", 28)
    f.setWeight(QFont.Weight.Bold)
    p.setFont(f)
    p.drawText(40, 150, "Control Center")

    p.setPen(QColor("#9bbccc"))
    f = QFont("Segoe UI", 11)
    f.setWeight(QFont.Weight.Normal)
    p.setFont(f)
    p.drawText(40, 180, "Loading services, connections and intelligence context…")

    p.setPen(QColor(accent))
    f = QFont("Segoe UI", 9)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
    f.setWeight(QFont.Weight.DemiBold)
    p.setFont(f)
    p.drawText(40, 288, "INITIALIZING")
    p.end()
    sp = QSplashScreen(pm)
    return sp


def main():
    # -----------------------------------------------------------------------
    # Pre-start: ensure we have the required modules. Import them early so
    # that QApplication is created only if the dashboard code is sane.
    # -----------------------------------------------------------------------
    try:
        from modules.ui.dashboard.ds import (
            C, F, dashboard_stylesheet, icon_pixmap, ICONS,
        )
        from modules.ui.dashboard.main_window import DashboardMainWindow
        from modules.ui.dashboard.service_adapters import (
            get_identity, load_user_preferences,
        )
    except Exception as e:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Dashboard Failed to Start")
        msg.setText("Dashboard modules could not be imported.")
        msg.setDetailedText(traceback.format_exc())
        msg.exec()
        sys.exit(3)

    # -----------------------------------------------------------------------
    # Build QApplication
    # -----------------------------------------------------------------------
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Smart Assistant — Control Center")
    app.setOrganizationName("SmartAssistant")

    # High-DPI support
    try:
        app.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    splash = _make_splash()
    try:
        splash.setPixmap(splash.pixmap())
        splash.show()
        app.processEvents()
    except Exception:
        pass

    def _status(msg: str):
        try:
            splash.showMessage(msg, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, QColor(C.TEXT))
            app.processEvents()
        except Exception:
            app.processEvents()

    # -----------------------------------------------------------------------
    # Phase through startup. We touch each backend adapter inside a
    # DashboardWorker-like sequential warmup to keep UX responsive.
    # -----------------------------------------------------------------------
    _status("Resolving identity and user context…")
    try:
        ident = get_identity() or {}
    except Exception:
        ident = {}
    time.sleep(0.08)

    _status("Loading saved preferences from database…")
    try:
        prefs = load_user_preferences() or {}
    except Exception:
        prefs = {}
    time.sleep(0.08)

    _status("Initializing design system theme…")
    saved_accent = prefs.get("dashboard_color")
    accent_hex = saved_accent if saved_accent and isinstance(saved_accent, str) else C.ACCENT

    try:
        stylesheet = dashboard_stylesheet(accent_hex)
        app.setStyleSheet(stylesheet)
    except Exception:
        app.setStyleSheet(dashboard_stylesheet(C.ACCENT_CYAN))
    time.sleep(0.08)

    _status("Constructing main dashboard window…")
    try:
        window = DashboardMainWindow()
    except Exception as e:
        splash.close() if hasattr(splash, "close") else None
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Dashboard Failed to Start")
        msg.setText("Could not create the dashboard window.")
        msg.setDetailedText(traceback.format_exc())
        msg.exec()
        sys.exit(4)

    # Apply accent immediately if it differs from default
    try:
        if accent_hex.lower() != C.ACCENT_CYAN.lower():
            window.set_accent(accent_hex)
    except Exception:
        pass

    _status("Ready — welcome back.")
    QTimer.singleShot(260, window.show)
    QTimer.singleShot(640, splash.close)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
