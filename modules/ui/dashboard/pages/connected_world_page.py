"""
Connected World Page
=====================
Unified view of everything the assistant can interact with:
  • Mobile devices (paired) — battery, online state, pair, disconnect
  • Smart home devices — on/off, brightness, temperature, speed
  • Media controls (play/pause/next/prev/volume)
  • Audio devices (mics / speakers, volumes)
  • Computer control (launch apps, window focus)
"""

from __future__ import annotations
import secrets

from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QComboBox, QMessageBox, QGridLayout,
    QMenu, QDialog, QDialogButtonBox, QFormLayout, QCheckBox, QSlider,
    QFileDialog, QTabWidget, QProgressBar, QSizePolicy, QSplitter,
    QTextEdit, QListWidget, QListWidgetItem,
)

from ..ds import (
    C, F, Spacing, Radius, ICONS, icon, icon_pixmap,
    HLine, VLine, Card, StatusChip, SectionHeader,
    LoadingState, EmptyState, ErrorState,
    rgba_str, get_contrast_color,
)
from ..service_adapters import (
    load_paired_devices, load_smart_home_devices, set_smart_home_power,
)
from ..workers import DashboardWorker


# ----------------------------- reusable sub-widgets -------------------------

class DeviceTile(QFrame):
    """Generic device card with icon, name, status, and inline actions."""

    def __init__(self, icon_name: str, accent: str, name: str, sub: str,
                 online: Optional[bool] = None, parent=None):
        super().__init__(parent)
        self.setProperty("class", "CardInner")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(110)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        lay.setSpacing(Spacing.SM)
        top = QHBoxLayout(); top.setSpacing(Spacing.SM)
        tile = QLabel(); tile.setFixedSize(36, 36)
        tile.setStyleSheet(
            f"background: {rgba_str(accent, 0.14)}; border-radius: {Radius.MD}px;"
        )
        tl = QVBoxLayout(tile); tl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel(); ic.setPixmap(icon_pixmap(icon_name, accent, 18))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter); tl.addWidget(ic)
        top.addWidget(tile)
        top.addStretch(1)
        if online is not None:
            chip = StatusChip("ONLINE" if online else "OFFLINE",
                              "connected" if online else "offline")
            top.addWidget(chip)
        lay.addLayout(top)
        name_lbl = QLabel(name); name_lbl.setStyleSheet("font-weight: 700; font-size: 14px;")
        lay.addWidget(name_lbl)
        sub_lbl = QLabel(sub); sub_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px;")
        sub_lbl.setWordWrap(True)
        lay.addWidget(sub_lbl)
        self.action_row = QHBoxLayout(); self.action_row.setSpacing(Spacing.XS)
        lay.addLayout(self.action_row)


class PowerToggle(QPushButton):
    """On/off toggle button."""
    def __init__(self, on: bool, on_change=None, parent=None):
        super().__init__("", parent)
        self._on = bool(on)
        self._fn = on_change
        self.setFixedSize(60, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._toggle)
        self._paint()

    def _toggle(self):
        self._on = not self._on
        self._paint()
        if self._fn:
            try: self._fn(self._on)
            except Exception: pass

    def _paint(self):
        c_on = C.SEC_CONNECTED
        c_off = C.PANEL3
        color = c_on if self._on else c_off
        text_color = get_contrast_color(c_on) if self._on else C.TEXT_MED
        hover_bg = rgba_str(c_on, 0.85) if self._on else C.PANEL2
        self.setText(" ON " if self._on else " OFF ")
        self.setStyleSheet(
            f"QPushButton {{ border: none; border-radius: 15px; padding: 0 10px; "
            f"background: {color}; color: {text_color}; "
            f"font-weight: 700; font-size: 11px; }}"
            f"QPushButton:hover {{ background: {hover_bg}; }}"
        )

    def set_on(self, on: bool):
        self._on = bool(on)
        self._paint()


# ---------------------------------------------------------------------------

class WirelessPairDialog(QDialog):
    """
    Dialog for pairing and connecting mobile devices wirelessly via Android 11+ Wireless Debugging (ADB).
    Supports pairing via 6-digit Wi-Fi pairing code and direct connection to known network endpoints.
    """

    def __init__(self, parent=None, default_host: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Wireless Device Pairing")
        self.resize(520, 560)
        self.setMinimumSize(480, 500)
        self._worker: Optional[DashboardWorker] = None
        self._default_host = default_host or ""
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(f"""
            QDialog {{
                background: #0d1522;
                color: {C.TEXT};
            }}
            QLabel {{
                color: {C.TEXT};
            }}
            QLineEdit {{
                background: rgba(0, 0, 0, 0.45);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 6px;
                padding: 8px 12px;
                color: {C.TEXT};
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 1px solid {C.ACC};
            }}
            QTabWidget::pane {{
                border: 1px solid rgba(255, 255, 255, 0.10);
                background: rgba(255, 255, 255, 0.02);
                border-radius: 8px;
                margin-top: 8px;
            }}
            QTabBar::tab {{
                background: rgba(255, 255, 255, 0.04);
                color: {C.TEXT_MED};
                padding: 8px 16px;
                border-radius: 6px;
                margin-right: 6px;
                font-weight: 600;
                font-size: 12px;
            }}
            QTabBar::tab:selected {{
                background: rgba(255, 255, 255, 0.10);
                color: {C.TEXT};
                border-bottom: 2px solid {C.ACC};
            }}
            QPushButton#PrimaryBtn {{
                background: {C.ACC};
                color: {get_contrast_color(C.ACC)};
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton#PrimaryBtn:hover {{
                background: {rgba_str(C.ACC, 0.88)};
            }}
            QPushButton#PrimaryBtn:disabled {{
                background: rgba(255, 255, 255, 0.08);
                color: {C.TEXT_DIM};
            }}
            QPushButton#GhostBtn {{
                background: rgba(255, 255, 255, 0.05);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 10px 18px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton#GhostBtn:hover {{
                background: rgba(255, 255, 255, 0.10);
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        root.setSpacing(Spacing.MD)

        # Header
        head_lay = QHBoxLayout()
        head_lay.setSpacing(Spacing.MD)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(icon_pixmap(ICONS.PHONE, C.SEC_CONNECTED, 24))
        head_lay.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_lbl = QLabel("Pair Mobile Device Wirelessly")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: " + C.TEXT + ";")
        sub_lbl = QLabel("Connect Android 11+ over Wi-Fi using native Developer Options (Zero App Installation)")
        sub_lbl.setStyleSheet(f"font-size: 11px; color: {C.TEXT_DIM};")
        title_col.addWidget(title_lbl)
        title_col.addWidget(sub_lbl)
        head_lay.addLayout(title_col, 1)
        root.addLayout(head_lay)

        # Tabs
        self._tabs = QTabWidget()

        # --- TAB 1: Pair with 6-Digit Code ---
        tab_pair = QWidget()
        pair_lay = QVBoxLayout(tab_pair)
        pair_lay.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        pair_lay.setSpacing(Spacing.MD)

        guide = QLabel(
            "<b>Steps on your Android phone:</b><br>"
            "1. Connect phone and PC to the same Wi-Fi.<br>"
            "2. Open <b>Settings → Additional Settings → Developer Options → Wireless Debugging</b> (turn ON).<br>"
            "3. Tap <b>'Pair device with pairing code'</b> to view the popup.<br>"
            "4. Enter the details from the popup below and keep the popup open:"
        )
        guide.setStyleSheet(f"background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 6px; padding: 10px; font-size: 12px; color: {C.TEXT_MED}; line-height: 140%;")
        guide.setWordWrap(True)
        pair_lay.addWidget(guide)

        form = QFormLayout()
        form.setSpacing(Spacing.SM)

        self._imei_input = QLineEdit()
        self._imei_input.setPlaceholderText("Optional (leave blank or enter 15-digit IMEI)")
        self._imei_input.setMaxLength(15)
        form.addRow("Device IMEI (Optional):", self._imei_input)

        self._ip_input = QLineEdit()
        self._ip_input.setPlaceholderText("e.g. 192.168.1.4")
        if self._default_host:
            self._ip_input.setText(self._default_host)
        form.addRow("Phone IP Address:", self._ip_input)

        self._pairing_port_input = QLineEdit()
        self._pairing_port_input.setPlaceholderText("e.g. 42113 (5-digit port in popup)")
        form.addRow("Pairing Port:", self._pairing_port_input)

        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("6-digit code (e.g. 123456)")
        self._code_input.setMaxLength(6)
        self._code_input.setStyleSheet("font-family: monospace; font-size: 15px; font-weight: 700; letter-spacing: 2px;")
        form.addRow("Pairing Code:", self._code_input)

        self._connect_port_input = QLineEdit()
        self._connect_port_input.setPlaceholderText("Optional (e.g. 39671 or 5555)")
        form.addRow("Connect Port (Optional):", self._connect_port_input)

        pair_lay.addLayout(form)

        self._pair_status = QLabel("")
        self._pair_status.setStyleSheet("font-size: 12px; color: " + C.TEXT_MED + ";")
        self._pair_status.setWordWrap(True)
        pair_lay.addWidget(self._pair_status)

        self._pair_btn = QPushButton(" Pair and Connect Device ")
        self._pair_btn.setObjectName("PrimaryBtn")
        self._pair_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pair_btn.clicked.connect(self._on_pair_clicked)
        pair_lay.addWidget(self._pair_btn)

        pair_lay.addStretch(1)
        self._tabs.addTab(tab_pair, "Pair with 6-Digit Code")

        # --- TAB 2: Quick Connect (Already Paired) ---
        tab_conn = QWidget()
        conn_lay = QVBoxLayout(tab_conn)
        conn_lay.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        conn_lay.setSpacing(Spacing.MD)

        conn_guide = QLabel(
            "<b>Already paired previously?</b><br>"
            "If your phone has already trusted this computer, enter its current IP address and connection port from the Wireless Debugging main screen."
        )
        conn_guide.setStyleSheet(f"background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 6px; padding: 10px; font-size: 12px; color: {C.TEXT_MED}; line-height: 140%;")
        conn_guide.setWordWrap(True)
        conn_lay.addWidget(conn_guide)

        conn_form = QFormLayout()
        conn_form.setSpacing(Spacing.SM)

        self._conn_target_input = QLineEdit()
        self._conn_target_input.setPlaceholderText("e.g. 192.168.1.4:5555 or 192.168.1.4:39671")
        conn_form.addRow("Device Target (IP:Port):", self._conn_target_input)
        conn_lay.addLayout(conn_form)

        self._conn_status = QLabel("")
        self._conn_status.setStyleSheet("font-size: 12px; color: " + C.TEXT_MED + ";")
        self._conn_status.setWordWrap(True)
        conn_lay.addWidget(self._conn_status)

        self._connect_btn = QPushButton(" Connect to Device ")
        self._connect_btn.setObjectName("PrimaryBtn")
        self._connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        conn_lay.addWidget(self._connect_btn)

        conn_lay.addStretch(1)
        self._tabs.addTab(tab_conn, "Direct Connect")

        root.addWidget(self._tabs, 1)

        # Bottom Cancel/Close button
        btn_box = QHBoxLayout()
        btn_box.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("GhostBtn")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        btn_box.addWidget(close_btn)
        root.addLayout(btn_box)

    def _on_pair_clicked(self):
        host = self._ip_input.text().strip()
        port_s = self._pairing_port_input.text().strip()
        code = self._code_input.text().strip()
        conn_port_s = self._connect_port_input.text().strip()

        if not host:
            self._set_pair_status("Please enter the phone IP address.", error=True)
            return
        if not port_s or not port_s.isdigit():
            self._set_pair_status("Please enter a valid numeric pairing port.", error=True)
            return
        if not code or len(code) != 6 or not code.isdigit():
            self._set_pair_status("Please enter the 6-digit pairing code.", error=True)
            return

        pairing_port = int(port_s)
        conn_port = int(conn_port_s) if conn_port_s.isdigit() else None

        self._pair_btn.setEnabled(False)
        self._set_pair_status(f"Pairing with {host}:{pairing_port}...", error=False)

        imei = self._imei_input.text().strip()
        clean_imei = None
        if imei:
            from skills.device_management import validate_imei
            ok_imei, clean_imei, imei_err = validate_imei(imei)
            if not ok_imei:
                self._pair_btn.setEnabled(True)
                self._set_pair_status(f"✕ {imei_err}", error=True)
                return

        def _do():
            from skills.device_management.device_controller import get_device_controller
            from ..service_adapters import get_identity
            ident = get_identity() or {}
            uid = int(ident.get("user_id") or 1)
            ctrl = get_device_controller()
            return ctrl.register_and_pair_remote_device(
                user_id=uid,
                imei=clean_imei,
                network_ip=host,
                pairing_ip=host,
                pairing_port=pairing_port,
                pairing_code=code,
                connection_ip=host,
                connection_port=conn_port
            )

        self._worker = DashboardWorker(_do, parent=self)
        self._worker.result_sig.connect(self._handle_pair_result)
        self._worker.error_sig.connect(lambda e: self._handle_pair_result({"success": False, "message": str(e)}))
        self._worker.start()

    def _handle_pair_result(self, res: dict):
        self._pair_btn.setEnabled(True)
        if res.get("success"):
            if res.get("needs_connection_port"):
                self._set_pair_status("✓ " + res.get("message", "Pairing succeeded!"), success=True)
                host = self._ip_input.text().strip()
                if host:
                    self._conn_target_input.setText(f"{host}:")
                self._tabs.setCurrentIndex(1)
                self._set_conn_status("Phone paired! Enter the connection port from your phone's main screen and click Connect.", error=False)
            else:
                self._set_pair_status(f"✓ {res.get('message', 'Successfully paired and connected!')}", success=True)
                parent = self.parent()
                if parent and hasattr(parent, "_reload"):
                    try: parent._reload()
                    except Exception: pass
                elif parent and hasattr(parent, "_load_devices"):
                    try: parent._load_devices()
                    except Exception: pass
                QTimer.singleShot(2000, self.accept)
        else:
            msg = res.get("message") or "Pairing failed. Check IP, port, and code."
            self._set_pair_status(f"✕ {msg}", error=True)

    def _on_connect_clicked(self):
        target = self._conn_target_input.text().strip()
        if not target:
            self._set_conn_status("Please enter target IP:Port.", error=True)
            return

        self._connect_btn.setEnabled(False)
        self._set_conn_status(f"Connecting to {target}...", error=False)

        def _do_conn():
            from skills.device_management.device_controller import get_device_controller
            from ..service_adapters import get_identity
            ident = get_identity() or {}
            uid = int(ident.get("user_id") or 1)
            ctrl = get_device_controller()
            target_s = target.strip()
            if ":" in target_s:
                h, p = target_s.split(":", 1)
                if p.isdigit():
                    return ctrl.connect_wireless_mobile(user_id=uid, host=h, connection_port=int(p))
            return ctrl.connect_mobile(user_id=uid, target=target_s)

        self._worker = DashboardWorker(_do_conn, parent=self)
        self._worker.result_sig.connect(self._handle_conn_result)
        self._worker.error_sig.connect(lambda e: self._handle_conn_result({"success": False, "message": str(e)}))
        self._worker.start()

    def _handle_conn_result(self, res: dict):
        self._connect_btn.setEnabled(True)
        if res.get("success"):
            self._set_conn_status(f"✓ {res.get('message', 'Connected successfully!')}", success=True)
            parent = self.parent()
            if parent and hasattr(parent, "_reload"):
                try: parent._reload()
                except Exception: pass
            elif parent and hasattr(parent, "_load_devices"):
                try: parent._load_devices()
                except Exception: pass
            QTimer.singleShot(1500, self.accept)
        else:
            msg = res.get("message") or "Connection failed."
            self._set_conn_status(f"✕ {msg}", error=True)

    def _set_pair_status(self, text: str, error: bool = False, success: bool = False):
        color = C.STATUS_ERROR if error else (C.STATUS_SUCCESS if success else C.TEXT_MED)
        self._pair_status.setStyleSheet(f"font-size: 12px; color: {color};")
        self._pair_status.setText(text)

    def _set_conn_status(self, text: str, error: bool = False, success: bool = False):
        color = C.STATUS_ERROR if error else (C.STATUS_SUCCESS if success else C.TEXT_MED)
        self._conn_status.setStyleSheet(f"font-size: 12px; color: {color};")
        self._conn_status.setText(text)



# ---------------------------------------------------------------------------
# MobileControlPanel — Full Android Device Control Centre
# ---------------------------------------------------------------------------

class _BannerLabel(QLabel):
    """Small inline status banner that fades after a timeout."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("font-size: 11px; padding: 3px 8px; border-radius: 6px;")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._safe_clear)
        self.hide()

    def _safe_clear(self):
        try:
            from PyQt6 import sip
            if sip.isdeleted(self):
                return
            self.clear()
            self.hide()
        except (RuntimeError, Exception):
            pass

    def show_msg(self, text: str, ok: bool = True, ms: int = 4000):
        try:
            from PyQt6 import sip
            if sip.isdeleted(self):
                return
            bg = "#1a4d2e" if ok else "#4d1a1a"
            fg = "#4ade80" if ok else "#f87171"
            self.setStyleSheet(
                f"font-size: 11px; padding: 3px 8px; border-radius: 6px; "
                f"background: {bg}; color: {fg};"
            )
            self.setText(text)
            self.show()
            self._timer.start(ms)
        except (RuntimeError, Exception):
            pass


class MobileControlPanel(QFrame):
    """
    Expandable control panel for a registered Android device.
    Header shows live status; expandable body has 5 control tabs.
    All actions route through DashboardWorker → DeviceController.handle_command().
    """

    def __init__(self, device: dict, parent=None):
        super().__init__(parent)
        self._dev = device
        self._expanded = False
        self._workers = []
        self.setProperty("class", "CardInner")
        self._build()

    # ------------------------------------------------------------------ build

    def _build(self):
        d = self._dev
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────────
        header = QFrame()
        header.setProperty("class", "CardInner")
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.setStyleSheet("border-radius: 10px;")
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(14, 12, 14, 12)
        hlay.setSpacing(10)

        # Phone icon
        from ..ds import icon_pixmap, C, ICONS
        ic = QLabel()
        ic.setPixmap(icon_pixmap(ICONS.PHONE, C.SEC_CONNECTED, 22))
        hlay.addWidget(ic)

        # Name + sub-info
        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        name = str(d.get("name") or "Android Device")
        self._name_lbl = QLabel(f"<b>{name}</b>")
        self._name_lbl.setStyleSheet("font-size: 13px;")
        info_col.addWidget(self._name_lbl)

        meta = d.get("metadata") or {}
        conn_type = meta.get("connection_type", "wireless").replace("_", " ").title()
        endpoint = meta.get("endpoint") or meta.get("serial") or ""
        android_ver = d.get("os_version") or "?"
        sub_text = f"Android {android_ver} · {conn_type}"
        if endpoint:
            sub_text += f" · {endpoint}"
        self._sub_lbl = QLabel(sub_text)
        self._sub_lbl.setStyleSheet("font-size: 11px; color: #888;")
        info_col.addWidget(self._sub_lbl)
        hlay.addLayout(info_col)
        hlay.addStretch(1)

        # Status / battery badges
        badge_col = QVBoxLayout()
        badge_col.setSpacing(4)
        badge_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        online = bool(d.get("online") or d.get("status") == "online")
        status_text = "ONLINE" if online else "OFFLINE"
        status_color = "#22c55e" if online else "#ef4444"
        self._status_lbl = QLabel(status_text)
        self._status_lbl.setStyleSheet(
            f"font-size: 10px; font-weight: 700; color: {status_color}; "
            f"background: {'#14532d' if online else '#450a0a'}; "
            f"padding: 2px 7px; border-radius: 6px;"
        )
        badge_col.addWidget(self._status_lbl, alignment=Qt.AlignmentFlag.AlignRight)
        battery = d.get("battery")
        if battery is not None:
            charging = d.get("charging", False)
            bat_icon = "⚡" if charging else "🔋"
            bat_lbl = QLabel(f"{bat_icon} {battery}%")
            bat_lbl.setStyleSheet("font-size: 10px; color: #aaa;")
            badge_col.addWidget(bat_lbl, alignment=Qt.AlignmentFlag.AlignRight)
        hlay.addLayout(badge_col)

        # Header Disconnect Button
        header_disc = QPushButton("Disconnect")
        header_disc.setObjectName("GhostBtn")
        header_disc.setStyleSheet(
            "padding: 3px 8px; font-size: 11px; color: #f87171; "
            "background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.35); "
            "border-radius: 6px;"
        )
        header_disc.setToolTip("Disconnect and remove this phone")
        header_disc.clicked.connect(self._confirm_disconnect)
        hlay.addWidget(header_disc)

        # Expand toggle
        self._expand_btn = QPushButton("▾")
        self._expand_btn.setObjectName("GhostBtn")
        self._expand_btn.setFixedSize(28, 28)
        self._expand_btn.setStyleSheet("font-size: 14px; padding: 0;")
        self._expand_btn.clicked.connect(self._toggle_expand)
        hlay.addWidget(self._expand_btn)

        header.mousePressEvent = lambda e: self._toggle_expand()
        self._root.addWidget(header)

        # ── Quick Action Bar ─────────────────────────────────────────────────
        self._qbar = QFrame()
        qlay = QHBoxLayout(self._qbar)
        qlay.setContentsMargins(14, 4, 14, 4)
        qlay.setSpacing(6)

        _quick = [
            ("📸 Mirror", "mirror my phone"),
            ("🖼 Screenshot", "take a screenshot of my phone"),
            ("🏠 Home", "go to home screen on my phone"),
            ("◀ Back", "go back on my phone"),
            ("🔒 Lock", "lock my phone"),
            ("🔋 Battery", f"check battery on my {d.get('name','phone')}"),
            ("🔌 Disconnect", "disconnect"),
        ]
        for label, cmd in _quick:
            btn = QPushButton(label)
            btn.setObjectName("GhostBtn")
            if "Disconnect" in label:
                btn.setStyleSheet("padding: 3px 7px; font-size: 11px; color: #f87171;")
                btn.clicked.connect(self._confirm_disconnect)
            else:
                btn.setStyleSheet("padding: 3px 7px; font-size: 11px;")
                btn.clicked.connect(lambda _=False, c=cmd: self._run_cmd(c))
            qlay.addWidget(btn)
        qlay.addStretch(1)
        self._root.addWidget(self._qbar)
        self._qbar.setVisible(False)

        # ── Expandable Control Centre ────────────────────────────────────────
        self._body = QFrame()
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(10, 4, 10, 10)
        body_lay.setSpacing(6)

        # Banner
        self._banner = _BannerLabel()
        body_lay.addWidget(self._banner)

        tabs = QTabWidget()
        tabs.setStyleSheet(
            "QTabBar::tab { padding: 5px 14px; font-size: 11px; }"
            "QTabBar::tab:selected { font-weight: 700; }"
        )
        body_lay.addWidget(tabs)

        # Tab 1: Screen & Navigation
        t1 = QWidget()
        t1l = QVBoxLayout(t1)
        t1l.setContentsMargins(8, 8, 8, 8)
        t1l.setSpacing(10)

        # --- Section 1: Live Screen Mirroring (scrcpy) ---
        mirror_box = QFrame()
        mirror_box.setProperty("class", "CardInner")
        mirror_box.setStyleSheet(
            "background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); "
            "border-radius: 8px; padding: 10px;"
        )
        mlay = QVBoxLayout(mirror_box)
        mlay.setContentsMargins(6, 6, 6, 6)
        mlay.setSpacing(8)

        # Header with title and live status pill
        mhead = QHBoxLayout()
        mtitle = QLabel("🖥 Live Screen Mirroring (scrcpy 60 FPS)")
        mtitle.setStyleSheet("font-weight: 700; font-size: 12px; color: #fff;")
        mhead.addWidget(mtitle)
        mhead.addStretch(1)

        self._mirror_status_lbl = QLabel("Ready • HW Accel")
        self._mirror_status_lbl.setStyleSheet(
            "font-size: 10px; font-weight: 600; color: #38bdf8; "
            "background: rgba(56, 189, 248, 0.15); padding: 2px 8px; border-radius: 6px;"
        )
        mhead.addWidget(self._mirror_status_lbl)
        mlay.addLayout(mhead)

        # Configuration row: Resolution, FPS, Bitrate
        cfg_row = QHBoxLayout()
        cfg_row.setSpacing(8)

        # Resolution
        res_lbl = QLabel("Resolution:")
        res_lbl.setStyleSheet("font-size: 11px; color: #888;")
        cfg_row.addWidget(res_lbl)
        self._res_combo = QComboBox()
        self._res_combo.setStyleSheet("font-size: 11px; padding: 3px 6px; border-radius: 5px;")
        self._res_combo.addItem("1080p (Native)", 1080)
        self._res_combo.addItem("720p (High Speed)", 720)
        self._res_combo.addItem("480p (Ultra Low Latency)", 480)
        cfg_row.addWidget(self._res_combo)

        # FPS
        fps_lbl = QLabel("FPS:")
        fps_lbl.setStyleSheet("font-size: 11px; color: #888;")
        cfg_row.addWidget(fps_lbl)
        self._fps_combo = QComboBox()
        self._fps_combo.setStyleSheet("font-size: 11px; padding: 3px 6px; border-radius: 5px;")
        self._fps_combo.addItem("60 FPS (Ultra Smooth)", 60)
        self._fps_combo.addItem("30 FPS (Low Bandwidth)", 30)
        cfg_row.addWidget(self._fps_combo)

        # Bitrate
        br_lbl = QLabel("Bitrate:")
        br_lbl.setStyleSheet("font-size: 11px; color: #888;")
        cfg_row.addWidget(br_lbl)
        self._bitrate_combo = QComboBox()
        self._bitrate_combo.setStyleSheet("font-size: 11px; padding: 3px 6px; border-radius: 5px;")
        self._bitrate_combo.addItem("4 Mbps (Recommended)", "4M")
        self._bitrate_combo.addItem("8 Mbps (Maximum Quality)", "8M")
        self._bitrate_combo.addItem("2 Mbps (Fast Network)", "2M")
        cfg_row.addWidget(self._bitrate_combo)

        cfg_row.addStretch(1)
        mlay.addLayout(cfg_row)

        # Action buttons row: Start, Fullscreen, Stop
        mact_row = QHBoxLayout()
        mact_row.setSpacing(8)

        start_mirror_btn = QPushButton("▶ Start Live Mirror")
        start_mirror_btn.setObjectName("PrimaryBtn")
        start_mirror_btn.setStyleSheet(
            "padding: 6px 14px; font-size: 12px; font-weight: 700; "
            "background: #2563eb; color: #fff; border-radius: 6px;"
        )
        start_mirror_btn.setToolTip("Stream phone screen at 60 FPS with hardware decoding and interactive mouse/touch/keyboard control")
        start_mirror_btn.clicked.connect(lambda: self._launch_custom_mirror(fullscreen=False))
        mact_row.addWidget(start_mirror_btn)

        fs_mirror_btn = QPushButton("⛶ Fullscreen Mirror")
        fs_mirror_btn.setObjectName("GhostBtn")
        fs_mirror_btn.setStyleSheet("padding: 6px 12px; font-size: 11px; border-radius: 6px;")
        fs_mirror_btn.clicked.connect(lambda: self._launch_custom_mirror(fullscreen=True))
        mact_row.addWidget(fs_mirror_btn)

        stop_mirror_btn = QPushButton("⏹ Stop Mirror")
        stop_mirror_btn.setObjectName("GhostBtn")
        stop_mirror_btn.setStyleSheet(
            "padding: 6px 12px; font-size: 11px; color: #f87171; "
            "background: rgba(239, 68, 68, 0.1); border-radius: 6px;"
        )
        stop_mirror_btn.clicked.connect(self._stop_mirror)
        mact_row.addWidget(stop_mirror_btn)

        mact_row.addStretch(1)
        mlay.addLayout(mact_row)

        # Informational hint
        hint_lbl = QLabel("ℹ Full interactive mouse touch, drag/swipe, PC keyboard typing, and shortcuts active inside scrcpy window.")
        hint_lbl.setStyleSheet("font-size: 10px; color: #777; font-style: italic;")
        mlay.addWidget(hint_lbl)

        t1l.addWidget(mirror_box)

        # --- Section 2: Remote Navigation & Controls ---
        nav_box = QFrame()
        nav_box.setProperty("class", "CardInner")
        nav_box.setStyleSheet(
            "background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.06); "
            "border-radius: 8px; padding: 8px;"
        )
        nlay = QVBoxLayout(nav_box)
        nlay.setContentsMargins(6, 6, 6, 6)
        nlay.setSpacing(6)

        ntitle = QLabel("🎮 Device Hardware & System Navigation")
        ntitle.setStyleSheet("font-weight: 700; font-size: 11px; color: #bbb;")
        nlay.addWidget(ntitle)

        t1_grid = QGridLayout()
        t1_grid.setSpacing(6)
        _nav_btns = [
            ("🏠 Home", "go to home screen on my phone"),
            ("◀ Back", "go back on my phone"),
            ("⊞ Recents", "show recent apps on my phone"),
            ("🔒 Lock Screen", "lock my phone"),
            ("⚡ Power Menu", "power menu on my phone"),
            ("📷 Screenshot", "take a screenshot of my phone"),
            ("🔔 Notifications", "expand notification shade on my phone"),
            ("⚙ Quick Settings", "open quick settings on my phone"),
            ("📸 Take Photo", "take a photo on my phone"),
            ("📍 Location", "where is my phone"),
            ("🔊 Vol +", "volume up on my phone"),
            ("🔉 Vol −", "volume down on my phone"),
            ("🔇 Mute", "mute my phone"),
            ("📋 Sync Clipboard", "get phone clipboard"),
        ]
        for idx, (lbl, cmd) in enumerate(_nav_btns):
            btn = QPushButton(lbl)
            btn.setObjectName("GhostBtn")
            btn.setStyleSheet("padding: 5px 8px; font-size: 11px;")
            btn.clicked.connect(lambda _=False, c=cmd: self._run_cmd(c))
            t1_grid.addWidget(btn, idx // 5, idx % 5)
        nlay.addLayout(t1_grid)
        t1l.addWidget(nav_box)
        t1l.addStretch(1)

        tabs.addTab(t1, "🖥 Screen & Nav")

        # Tab 2: Applications
        t2 = QWidget()
        t2l = QVBoxLayout(t2)
        t2l.setSpacing(6)
        fgapp_row = QHBoxLayout()
        fg_lbl = QLabel("Foreground app:")
        fg_lbl.setStyleSheet("font-size: 11px; color: #888;")
        self._fg_app_lbl = QLabel("—")
        self._fg_app_lbl.setStyleSheet("font-size: 11px; color: #ddd;")
        fg_btn = QPushButton("Refresh")
        fg_btn.setObjectName("GhostBtn")
        fg_btn.setStyleSheet("padding: 3px 8px; font-size: 11px;")
        fg_btn.clicked.connect(self._refresh_fg_app)
        fgapp_row.addWidget(fg_lbl)
        fgapp_row.addWidget(self._fg_app_lbl)
        fgapp_row.addStretch(1)
        fgapp_row.addWidget(fg_btn)
        t2l.addLayout(fgapp_row)

        app_grid = QGridLayout()
        app_grid.setSpacing(6)
        _apps = [
            ("▶ YouTube", "open youtube on my phone"),
            ("🌐 Chrome", "open chrome on my phone"),
            ("💬 WhatsApp", "open whatsapp on my phone"),
            ("📷 Camera", "open camera on my phone"),
            ("⚙ Settings", "open settings on my phone"),
            ("🗺 Maps", "open maps on my phone"),
        ]
        for i, (lbl, cmd) in enumerate(_apps):
            btn = QPushButton(lbl)
            btn.setObjectName("GhostBtn")
            btn.setStyleSheet("padding: 5px 8px; font-size: 11px;")
            btn.clicked.connect(lambda _=False, c=cmd: self._run_cmd(c))
            app_grid.addWidget(btn, i // 3, i % 3)
        t2l.addLayout(app_grid)

        # Custom app launch
        cust_row = QHBoxLayout()
        self._app_input = QLineEdit()
        self._app_input.setPlaceholderText("App name (e.g. Spotify)")
        self._app_input.setStyleSheet("padding: 4px 8px; border-radius: 6px; font-size: 11px;")
        launch_btn = QPushButton("Launch")
        launch_btn.setObjectName("PrimaryBtn")
        launch_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        launch_btn.clicked.connect(self._launch_custom_app)
        cust_row.addWidget(self._app_input, 1)
        cust_row.addWidget(launch_btn)
        t2l.addLayout(cust_row)

        # Close app
        close_row = QHBoxLayout()
        self._close_input = QLineEdit()
        self._close_input.setPlaceholderText("App to close (force-stop)")
        self._close_input.setStyleSheet("padding: 4px 8px; border-radius: 6px; font-size: 11px;")
        close_btn = QPushButton("Force Stop")
        close_btn.setObjectName("DangerBtn")
        close_btn.setStyleSheet("padding: 4px 10px; font-size: 11px; background: #450a0a; color: #f87171; border-radius: 6px;")
        close_btn.clicked.connect(self._close_custom_app)
        close_row.addWidget(self._close_input, 1)
        close_row.addWidget(close_btn)
        t2l.addLayout(close_row)
        t2l.addStretch(1)
        tabs.addTab(t2, "📱 Apps")

        # Tab 3: Device Info & Telemetry
        t3 = QWidget()
        t3l = QVBoxLayout(t3)
        t3l.setSpacing(8)
        self._info_box = QTextEdit()
        self._info_box.setReadOnly(True)
        self._info_box.setStyleSheet("background: #1a1a1a; color: #ccc; font-size: 11px; border-radius: 6px; padding: 8px;")
        self._info_box.setFixedHeight(160)
        t3l.addWidget(self._info_box)
        t3_btns = QHBoxLayout()
        for lbl, cmd in [
            ("🔋 Battery", f"check battery on my {d.get('name','phone')}"),
            ("💾 Storage", "phone storage"),
            ("🧠 RAM", "phone ram on my phone"),
            ("🌐 Network", "phone network status"),
            ("🌡 System", "phone system status"),
        ]:
            btn = QPushButton(lbl)
            btn.setObjectName("GhostBtn")
            btn.setStyleSheet("padding: 5px 8px; font-size: 11px;")
            btn.clicked.connect(lambda _=False, c=cmd: self._run_info_cmd(c))
            t3_btns.addWidget(btn)
        t3l.addLayout(t3_btns)
        t3l.addStretch(1)
        tabs.addTab(t3, "📊 Info")

        # Tab 4: Files & Media
        t4 = QWidget()
        t4l = QVBoxLayout(t4)
        t4l.setSpacing(8)

        # Media row
        media_frame = QFrame()
        media_frame.setStyleSheet("background: #1a1a1a; border-radius: 8px; padding: 4px;")
        media_lay = QHBoxLayout(media_frame)
        media_lay.setContentsMargins(8, 6, 8, 6)
        for lbl, action in [("⏮", "previous"), ("⏯", "play_pause"), ("⏭", "next"), ("⏹", "stop")]:
            btn = QPushButton(lbl)
            btn.setObjectName("GhostBtn")
            btn.setStyleSheet("font-size: 18px; padding: 4px 10px;")
            btn.clicked.connect(lambda _=False, a=action: self._run_cmd(f"{a} music on phone"))
            media_lay.addWidget(btn)
        t4l.addWidget(media_frame)

        # Clipboard
        clip_row = QHBoxLayout()
        self._clip_out = QLabel("Clipboard: —")
        self._clip_out.setStyleSheet("font-size: 11px; color: #888;")
        read_clip = QPushButton("Read Clipboard")
        read_clip.setObjectName("GhostBtn")
        read_clip.setStyleSheet("padding: 4px 8px; font-size: 11px;")
        read_clip.clicked.connect(lambda: self._run_info_cmd("phone clipboard"))
        clip_row.addWidget(self._clip_out, 1)
        clip_row.addWidget(read_clip)
        t4l.addLayout(clip_row)

        send_clip_row = QHBoxLayout()
        self._clip_input = QLineEdit()
        self._clip_input.setPlaceholderText("Text to copy to phone clipboard")
        self._clip_input.setStyleSheet("padding: 4px 8px; border-radius: 6px; font-size: 11px;")
        send_clip = QPushButton("Send")
        send_clip.setObjectName("PrimaryBtn")
        send_clip.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        send_clip.clicked.connect(self._send_clipboard)
        send_clip_row.addWidget(self._clip_input, 1)
        send_clip_row.addWidget(send_clip)
        t4l.addLayout(send_clip_row)

        # File browser
        file_row = QHBoxLayout()
        browse_btn = QPushButton("📁 Browse Downloads")
        browse_btn.setObjectName("GhostBtn")
        browse_btn.setStyleSheet("padding: 5px 10px; font-size: 11px;")
        browse_btn.clicked.connect(lambda: self._run_info_cmd("browse files on phone"))
        push_btn = QPushButton("⬆ Push File to Phone")
        push_btn.setObjectName("GhostBtn")
        push_btn.setStyleSheet("padding: 5px 10px; font-size: 11px;")
        push_btn.clicked.connect(self._push_file_dialog)
        file_row.addWidget(browse_btn)
        file_row.addWidget(push_btn)
        file_row.addStretch(1)
        t4l.addLayout(file_row)

        self._files_list = QListWidget()
        self._files_list.setStyleSheet(
            "background: #1a1a1a; color: #ccc; font-size: 11px; border-radius: 6px;"
        )
        self._files_list.setMaximumHeight(130)
        t4l.addWidget(self._files_list)
        t4l.addStretch(1)
        tabs.addTab(t4, "📂 Files & Media")

        # Tab 5: Connectivity
        t5 = QWidget()
        t5l = QVBoxLayout(t5)
        t5l.setSpacing(8)

        meta = d.get("metadata") or {}
        conn_info_lines = [
            f"Device ID: {d.get('device_id','?')}",
            f"Endpoint: {meta.get('endpoint') or meta.get('serial','?')}",
            f"Transport: {meta.get('session_type','?')} / {meta.get('connection_type','?')}",
            f"Paired at: {str(d.get('paired_at','?'))[:19]}",
            f"Last seen: {str(d.get('last_seen','?'))[:19]}",
        ]
        info_text = QLabel("\n".join(conn_info_lines))
        info_text.setStyleSheet("font-size: 11px; color: #888; line-height: 1.6;")
        t5l.addWidget(info_text)

        conn_btns = QHBoxLayout()
        for lbl, cmd in [
            ("🔄 Reconnect", f"reconnect to my enrolled phone"),
            ("🔌 Disconnect", "disconnect"),
            ("🔍 Refresh Status", ""),
            ("🗑 Unpair", "unpair"),
        ]:
            btn = QPushButton(lbl)
            btn.setObjectName("GhostBtn" if "Unpair" not in lbl else "DangerBtn")
            if "Disconnect" in lbl:
                btn.setStyleSheet("padding: 5px 10px; font-size: 11px; background: rgba(239, 68, 68, 0.12); color: #f87171; border-radius: 6px;")
                btn.clicked.connect(self._confirm_disconnect)
            elif "Unpair" in lbl:
                btn.setStyleSheet("padding: 5px 10px; font-size: 11px; background: #450a0a; color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 6px;")
                btn.clicked.connect(self._confirm_unpair)
            elif "Refresh" in lbl:
                btn.setStyleSheet("padding: 5px 10px; font-size: 11px;")
                btn.clicked.connect(self._refresh_status)
            else:
                btn.setStyleSheet("padding: 5px 10px; font-size: 11px;")
                btn.clicked.connect(lambda _=False, c=cmd: self._run_cmd(c))
            conn_btns.addWidget(btn)
        conn_btns.addStretch(1)
        t5l.addLayout(conn_btns)
        t5l.addStretch(1)
        tabs.addTab(t5, "🔗 Connectivity")

        self._body.setVisible(False)
        self._root.addWidget(self._body)

    # ---------------------------------------------------------------- actions

    def _is_alive(self) -> bool:
        try:
            from PyQt6 import sip
            if sip.isdeleted(self):
                return False
            if hasattr(self, "_banner") and (self._banner is None or sip.isdeleted(self._banner)):
                return False
            return True
        except (RuntimeError, Exception):
            return False

    def _toggle_expand(self):
        if not self._is_alive():
            return
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._qbar.setVisible(self._expanded)
        self._expand_btn.setText("▴" if self._expanded else "▾")
        if self._expanded:
            self._refresh_mirror_status()

    def _launch_custom_mirror(self, fullscreen: bool = False):
        if not self._is_alive():
            return
        from skills.device_management import get_device_controller
        dc = get_device_controller()
        max_size = int(self._res_combo.currentData()) if hasattr(self, "_res_combo") and self._res_combo.currentData() else 1080
        max_fps = int(self._fps_combo.currentData()) if hasattr(self, "_fps_combo") and self._fps_combo.currentData() else 60
        bit_rate = str(self._bitrate_combo.currentData()) if hasattr(self, "_bitrate_combo") and self._bitrate_combo.currentData() else "4M"

        target = self._dev.get("name") or self._dev.get("device_id") or ""

        def _exec():
            return dc.launch_scrcpy_mirror(
                user_id=1,
                target=target,
                max_size=max_size,
                max_fps=max_fps,
                bit_rate=bit_rate,
                fullscreen=fullscreen,
            )

        w = DashboardWorker(_exec)
        w.result_sig.connect(self._on_mirror_result)
        self._workers.append(w)
        w.start()

    def _stop_mirror(self):
        if not self._is_alive():
            return
        from skills.device_management import get_device_controller
        dc = get_device_controller()
        w = DashboardWorker(dc.stop_scrcpy)
        w.result_sig.connect(self._on_mirror_result)
        self._workers.append(w)
        w.start()

    def _on_mirror_result(self, res):
        if not self._is_alive():
            return
        try:
            if isinstance(res, dict):
                ok = res.get("success", False)
                msg = res.get("message") or ("Mirroring active." if ok else "Mirroring failed.")
            else:
                ok = True
                msg = str(res)
            if hasattr(self, "_banner") and self._banner is not None:
                self._banner.show_msg(msg, ok=ok)
            self._refresh_mirror_status()
        except (RuntimeError, Exception):
            pass

    def _refresh_mirror_status(self):
        if not self._is_alive():
            return
        from skills.device_management import get_device_controller
        dc = get_device_controller()
        w = DashboardWorker(dc.get_mirror_status)
        w.result_sig.connect(self._on_mirror_status_result)
        self._workers.append(w)
        w.start()

    def _on_mirror_status_result(self, st):
        if not self._is_alive() or not hasattr(self, "_mirror_status_lbl"):
            return
        try:
            if not isinstance(st, dict):
                return
            running = st.get("running", False)
            installed = st.get("installed", False)
            if running:
                self._mirror_status_lbl.setText("Streaming • 60 FPS (HW Accel, <25ms)")
                self._mirror_status_lbl.setStyleSheet(
                    "font-size: 10px; font-weight: 700; color: #4ade80; "
                    "background: rgba(34, 197, 94, 0.15); padding: 2px 8px; border-radius: 6px;"
                )
            elif installed:
                self._mirror_status_lbl.setText("Ready • HW Accel")
                self._mirror_status_lbl.setStyleSheet(
                    "font-size: 10px; font-weight: 600; color: #38bdf8; "
                    "background: rgba(56, 189, 248, 0.15); padding: 2px 8px; border-radius: 6px;"
                )
            else:
                self._mirror_status_lbl.setText("scrcpy not found")
                self._mirror_status_lbl.setStyleSheet(
                    "font-size: 10px; font-weight: 600; color: #f87171; "
                    "background: rgba(239, 68, 68, 0.15); padding: 2px 8px; border-radius: 6px;"
                )
        except (RuntimeError, Exception):
            pass

    def _run_cmd(self, cmd: str):
        if not self._is_alive():
            return
        if cmd == "disconnect":
            self._confirm_disconnect()
            return
        from ..service_adapters import send_command
        w = DashboardWorker(send_command, cmd)
        w.result_sig.connect(lambda r: self._on_result(r, cmd))
        self._workers.append(w)
        w.start()

    def _run_info_cmd(self, cmd: str):
        if not self._is_alive():
            return
        from ..service_adapters import send_command
        def _exec():
            return send_command(cmd)
        w = DashboardWorker(_exec)
        w.result_sig.connect(lambda r: self._on_info_result(r, cmd))
        self._workers.append(w)
        w.start()

    def _on_result(self, result, cmd: str):
        if not self._is_alive():
            return
        try:
            if isinstance(result, dict):
                ok = result.get("success", True)
                msg = result.get("message") or result.get("status") or ("Done" if ok else "Error")
            else:
                ok = True
                msg = str(result)[:120] if result else "Done"
            if hasattr(self, "_banner") and self._banner is not None:
                self._banner.show_msg(msg, ok=ok)
        except (RuntimeError, Exception):
            pass

    def _on_info_result(self, result, cmd: str):
        if not self._is_alive():
            return
        try:
            if isinstance(result, dict):
                ok = result.get("success", True)
                msg = result.get("message") or ""
                # Format clipboard result
                if "clipboard" in cmd:
                    clip = result.get("clipboard") or msg
                    if hasattr(self, "_clip_out") and self._clip_out is not None:
                        self._clip_out.setText(f"Clipboard: {clip[:80]}")
                # Format file browser result
                elif "browse" in cmd or "files" in cmd:
                    if hasattr(self, "_files_list") and self._files_list is not None:
                        self._files_list.clear()
                        for f in result.get("files") or []:
                            prefix = "📁" if f.get("is_dir") else "📄"
                            self._files_list.addItem(f"{prefix} {f['name']}  ({f.get('size','?')})")
                else:
                    if hasattr(self, "_info_box") and self._info_box is not None:
                        self._info_box.setPlainText(msg)
            else:
                if hasattr(self, "_info_box") and self._info_box is not None:
                    self._info_box.setPlainText(str(result)[:500] if result else "No data returned.")
        except (RuntimeError, Exception):
            pass

    def _refresh_fg_app(self):
        if not self._is_alive():
            return
        from ..service_adapters import send_command
        w = DashboardWorker(send_command, "what app is open on my phone")
        def _done(r):
            if not self._is_alive():
                return
            try:
                if isinstance(r, dict):
                    app = (r.get("foreground_app") or r.get("app_name") or
                           r.get("message") or "Unknown")
                else:
                    app = str(r) if r else "—"
                if hasattr(self, "_fg_app_lbl") and self._fg_app_lbl is not None:
                    self._fg_app_lbl.setText(str(app)[:40])
            except (RuntimeError, Exception):
                pass
        w.result_sig.connect(_done)
        self._workers.append(w)
        w.start()

    def _launch_custom_app(self):
        if not self._is_alive():
            return
        app = self._app_input.text().strip()
        if app:
            self._run_cmd(f"open {app} on my phone")

    def _close_custom_app(self):
        if not self._is_alive():
            return
        app = self._close_input.text().strip()
        if not app:
            return
        if QMessageBox.question(self, "Force Stop", f"Force-stop '{app}' on your phone?") != QMessageBox.StandardButton.Yes:
            return
        self._run_cmd(f"close {app} on my phone")

    def _send_clipboard(self):
        if not self._is_alive():
            return
        text = self._clip_input.text().strip()
        if text:
            self._run_cmd(f"copy {text} to phone clipboard")

    def _push_file_dialog(self):
        if not self._is_alive():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select file to push to phone")
        if not path:
            return

        def _do_push():
            try:
                from ..service_adapters import get_identity
                from skills.device_management.device_controller import get_device_controller
                ident = get_identity() or {}
                uid = int(ident.get("user_id") or 1)
                ctrl = get_device_controller()
                return ctrl.push_file(path, uid)
            except Exception as ex:
                return {"success": False, "message": str(ex)}

        w = DashboardWorker(_do_push)
        w.result_sig.connect(lambda r: self._on_result(r, "push_file"))
        self._workers.append(w)
        w.start()

    def _find_page(self):
        try:
            p = self.parent()
            while p and not hasattr(p, "_reload"):
                p = p.parent()
            return p
        except Exception:
            return None

    def _confirm_disconnect(self):
        d = self._dev
        name = d.get("name") or "device"
        device_id = d.get("device_id") or ""
        meta = d.get("metadata") or {}
        endpoint = meta.get("endpoint") or meta.get("serial") or ""

        reply = QMessageBox.question(
            self,
            "Disconnect Device",
            f"Disconnect and remove {name} from Connected World?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        cw_page = self._find_page()

        def _do_disconnect():
            try:
                from ..service_adapters import get_identity
                from skills.device_management.device_controller import get_device_controller
                from skills.device_management.device_registry import get_device_registry

                ident = get_identity() or {}
                uid = int(ident.get("user_id") or 1)

                ctrl = get_device_controller()
                res = ctrl.disconnect_device(uid, target=device_id or name)

                # Ensure removed from registry and clean up any duplicates
                reg = get_device_registry()
                if device_id:
                    reg.remove_device(uid, device_id)
                for dev_rec in list(reg.list_devices(uid)):
                    rmeta = dev_rec.metadata or {}
                    if (
                        dev_rec.device_id == device_id
                        or (endpoint and (rmeta.get("endpoint") == endpoint or rmeta.get("serial") == endpoint))
                        or (name and dev_rec.name.lower() == name.lower())
                    ):
                        reg.remove_device(uid, dev_rec.device_id)

                return {"success": True, "message": f"Disconnected and removed {name}."}
            except Exception as e:
                return {"success": False, "message": str(e)}

        def _on_done(r):
            try:
                self.setVisible(False)
            except Exception:
                pass
            if not self._is_alive():
                return
            ok = r.get("success", True) if isinstance(r, dict) else True
            msg = r.get("message", f"Disconnected {name}.") if isinstance(r, dict) else str(r)
            if hasattr(self, "_banner") and self._banner is not None:
                try:
                    from PyQt6 import sip
                    if not sip.isdeleted(self._banner):
                        self._banner.show_msg(msg, ok=ok)
                except Exception:
                    pass
            if cw_page and hasattr(cw_page, "_reload"):
                try:
                    from PyQt6 import sip
                    if not sip.isdeleted(cw_page):
                        cw_page._reload()
                except Exception:
                    pass

        w = DashboardWorker(_do_disconnect)
        w.result_sig.connect(_on_done)
        self._workers.append(w)
        w.start()

    def _confirm_unpair(self):
        d = self._dev
        name = d.get("name") or "device"
        device_id = d.get("device_id") or ""
        meta = d.get("metadata") or {}
        endpoint = meta.get("endpoint") or meta.get("serial") or ""

        reply = QMessageBox.question(
            self,
            "Unpair Device",
            f"Permanently unpair and remove {name} from Connected World?\n\n"
            f"This will disconnect the device and delete its saved registration from PostgreSQL.\n"
            f"You will need to re-pair with a 6-digit code to use this device again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Visually hide widget immediately upon unpair confirmation
        try:
            self.setVisible(False)
        except Exception:
            pass

        cw_page = self._find_page()

        def _do_unpair():
            try:
                from ..service_adapters import get_identity
                from skills.device_management.device_controller import get_device_controller
                from skills.device_management.device_registry import get_device_registry
                from skills.device_management.adb_adapter import get_adb_adapter

                ident = get_identity() or {}
                uid = int(ident.get("user_id") or 1)

                adb = get_adb_adapter()
                if endpoint and ":" in endpoint:
                    host, port = endpoint.split(":", 1)
                    try:
                        adb.disconnect_wireless(host, int(port))
                    except Exception:
                        pass
                elif endpoint:
                    adb._run_adb_cmd(["disconnect", endpoint], timeout=4.0)

                ctrl = get_device_controller()
                if device_id:
                    try:
                        ctrl.unpair_device(uid, device_id)
                    except Exception:
                        pass

                reg = get_device_registry()
                if device_id:
                    reg.remove_device(uid, device_id)

                for r in list(reg.list_devices(uid)):
                    rmeta = r.metadata or {}
                    if (
                        r.device_id == device_id
                        or (endpoint and (rmeta.get("endpoint") == endpoint or rmeta.get("serial") == endpoint))
                        or (name and r.name.lower() == name.lower())
                    ):
                        reg.remove_device(uid, r.device_id)

                return {"success": True, "message": f"Unpaired {name}."}
            except Exception as e:
                return {"success": False, "message": str(e)}

        def _on_unpair_done(r):
            if cw_page and hasattr(cw_page, "_reload"):
                try:
                    from PyQt6 import sip
                    if not sip.isdeleted(cw_page):
                        cw_page._reload()
                except Exception:
                    pass

        w = DashboardWorker(_do_unpair)
        w.result_sig.connect(_on_unpair_done)
        self._workers.append(w)
        w.start()

    def _refresh_status(self):
        cw_page = self._find_page()
        if cw_page and hasattr(cw_page, "_reload"):
            try:
                from PyQt6 import sip
                if not sip.isdeleted(cw_page):
                    cw_page._reload()
            except Exception:
                pass


# ---------------------------------------------------------------------------

class ConnectedWorldPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._paired: List[Dict] = []
        self._smart: List[Dict] = []
        self._workers = []  # Track worker threads for cleanup
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(Spacing.LG2, Spacing.LG2, Spacing.LG2, Spacing.LG2)
        root.setSpacing(Spacing.LG)

        head = QHBoxLayout(); head.setSpacing(Spacing.MD)
        sh = SectionHeader("Connected World",
                          "Paired phones, smart home, media, audio — everything the assistant can reach.",
                          accent=C.SEC_CONNECTED)
        head.addWidget(sh, 1); head.addStretch(1)
        self._search = QLineEdit(); self._search.setPlaceholderText("Filter devices…")
        self._search.addAction(icon(ICONS.SEARCH, C.TEXT_DIM, 14), QLineEdit.ActionPosition.LeadingPosition)
        self._search.setCursor(Qt.CursorShape.IBeamCursor)
        self._search.setMinimumWidth(240)
        self._search.setMaximumWidth(360)
        self._search.returnPressed.connect(self._reload)
        head.addWidget(self._search)
        self._refresh = QPushButton(); self._refresh.setObjectName("IconBtn")
        self._refresh.setIcon(icon(ICONS.REFRESH, C.TEXT, 14)); self._refresh.setFixedSize(34, 34)
        self._refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh.clicked.connect(self._reload)
        head.addWidget(self._refresh)
        self._pair_btn = QPushButton("  Pair Mobile Device")
        self._pair_btn.setObjectName("GhostBtn"); self._pair_btn.setIcon(icon(ICONS.PHONE, C.TEXT, 14))
        self._pair_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pair_btn.clicked.connect(self._pair_device)
        head.addWidget(self._pair_btn)
        self._disc_btn = QPushButton("  Discover Smart Devices")
        self._disc_btn.setObjectName("PrimaryBtn"); self._disc_btn.setIcon(icon(ICONS.CONNECTED_WORLD, get_contrast_color(C.ACCENT), 14))
        self._disc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._disc_btn.clicked.connect(self._discover_smart)
        head.addWidget(self._disc_btn)
        hw = QWidget(); hw.setLayout(head)
        root.addWidget(hw)

        # Quick stats
        stats = QHBoxLayout(); stats.setSpacing(Spacing.MD)
        self._st_devices = self._stat("Paired Devices", "0", ICONS.PHONE, C.SEC_CONNECTED)
        self._st_smart = self._stat("Smart Home", "0", ICONS.HOME_SMART, C.SEC_CONNECTED)
        self._st_online = self._stat("Online Now", "0", ICONS.NETWORK_WIRED, C.STATUS_SUCCESS)
        self._st_media = self._stat("Media Status", "Idle", ICONS.MUSIC, C.SEC_CONNECTED)
        for s in (self._st_devices, self._st_smart, self._st_online, self._st_media):
            stats.addWidget(s, 1)
        sw = QWidget(); sw.setLayout(stats)
        root.addWidget(sw)

        scroller = QScrollArea(); scroller.setWidgetResizable(True); scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sw = QWidget(); cols = QVBoxLayout(sw); cols.setContentsMargins(0, 0, 0, 0); cols.setSpacing(Spacing.LG)

        # --- Mobile devices ---
        self._mobile_card = Card(title="Mobile Devices", accent=C.SEC_CONNECTED)
        self._mobile_loading = LoadingState("Loading paired devices…")
        self._mobile_card.body.addWidget(self._mobile_loading)
        self._mobile_empty = EmptyState(ICONS.PHONE, "No paired mobile devices",
                                        "Pair your phone to enable remote control and notifications.",
                                        accent=C.SEC_CONNECTED)
        self._mobile_empty.setVisible(False)
        self._mobile_card.body.addWidget(self._mobile_empty)
        self._mobile_grid = QGridLayout(); self._mobile_grid.setSpacing(Spacing.MD)
        self._mobile_grid_w = QWidget(); self._mobile_grid_w.setLayout(self._mobile_grid)
        self._mobile_card.body.addWidget(self._mobile_grid_w, 1)
        cols.addWidget(self._mobile_card)

        # --- Smart home ---
        self._sh_card = Card(title="Smart Home", accent=C.SEC_CONNECTED)
        self._sh_loading = LoadingState("Loading smart home devices…")
        self._sh_card.body.addWidget(self._sh_loading)
        self._sh_empty = EmptyState(ICONS.HOME_SMART, "No smart home devices",
                                    "Run discovery to find compatible smart home devices on your network.",
                                    accent=C.SEC_CONNECTED)
        self._sh_empty.setVisible(False)
        self._sh_card.body.addWidget(self._sh_empty)
        self._sh_grid = QGridLayout(); self._sh_grid.setSpacing(Spacing.MD)
        self._sh_grid_w = QWidget(); self._sh_grid_w.setLayout(self._sh_grid)
        self._sh_card.body.addWidget(self._sh_grid_w, 1)
        cols.addWidget(self._sh_card)

        # --- Media + Audio ---
        med_row = QHBoxLayout(); med_row.setSpacing(Spacing.LG)

        media_card = Card(title="Media Controls", accent=C.SEC_CONNECTED)
        mc = QGridLayout(); mc.setSpacing(Spacing.MD)
        # Now playing
        np_title = QLabel("No media playing"); np_title.setStyleSheet("font-weight: 700;")
        np_sub = QLabel("Use natural commands like 'play music'"); np_sub.setStyleSheet(f"color: {C.TEXT_DIM};")
        mc.addWidget(np_title, 0, 0, 1, 4); mc.addWidget(np_sub, 1, 0, 1, 4)
        # Buttons
        for col, (icn, tip, fn) in enumerate([
            (ICONS.CHEVRON_LEFT, "Previous", lambda: self._cmd("Previous track")),
            (ICONS.PLAY,        "Play",     lambda: self._cmd("Play music")),
            (ICONS.PAUSE,       "Pause",    lambda: self._cmd("Pause music")),
            (ICONS.CHEVRON_RIGHT, "Next",   lambda: self._cmd("Next track")),
        ]):
            b = QPushButton(); b.setObjectName("IconBtn")
            b.setIcon(icon(icn, C.TEXT, 14)); b.setFixedSize(40, 40); b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            mc.addWidget(b, 2, col)
        # Volume
        mc.addWidget(QLabel("Volume"), 3, 0)
        vol = QSlider(Qt.Orientation.Horizontal); vol.setRange(0, 100); vol.setValue(60)
        mc.addWidget(vol, 3, 1, 1, 3)
        media_card.body.addLayout(mc)
        mw = QWidget(); mw.setLayout(QVBoxLayout()); mw.layout().setContentsMargins(0,0,0,0); mw.layout().addWidget(media_card)
        med_row.addWidget(mw, 1)

        audio_card = Card(title="Audio Devices", accent=C.SEC_CONNECTED)
        ac = QVBoxLayout(); ac.setSpacing(Spacing.SM)
        # Mic / speaker
        for label, icn, acc in [
            ("Microphone", ICONS.MIC, C.SEC_CONNECTED),
            ("Speaker",    ICONS.VOLUME_UP, C.STATUS_SUCCESS),
        ]:
            row_w = QFrame(); row_w.setProperty("class", "CardInner")
            rl = QHBoxLayout(row_w); rl.setContentsMargins(Spacing.MD, 8, Spacing.MD, 8); rl.setSpacing(Spacing.MD)
            ic = QLabel(); ic.setPixmap(icon_pixmap(icn, acc, 16)); ic.setFixedWidth(22)
            rl.addWidget(ic)
            nm = QLabel(f"Default {label} Device"); nm.setStyleSheet("font-weight: 500;")
            rl.addWidget(nm, 1)
            chip = StatusChip("READY", "success")
            rl.addWidget(chip)
            ac.addWidget(row_w)
        audio_card.body.addLayout(ac)
        aw = QWidget(); aw.setLayout(QVBoxLayout()); aw.layout().setContentsMargins(0,0,0,0); aw.layout().addWidget(audio_card)
        med_row.addWidget(aw, 1)
        mrw = QWidget(); mrw.setLayout(med_row)
        cols.addWidget(mrw)

        # --- Computer / Apps ---
        comp_card = Card(title="Computer / Applications", accent=C.SEC_CONNECTED)
        self._cc_grid = QGridLayout(); self._cc_grid.setSpacing(Spacing.MD)
        self._cc_buttons = []
        for col, (name, icn, fn) in enumerate([
            ("Launcher",   ICONS.DESKTOP,  lambda: self._cmd("Open launcher")),
            ("Browser",    ICONS.SEARCH,   lambda: self._cmd("Open browser")),
            ("Terminal",   ICONS.BARS,     lambda: self._cmd("Open terminal")),
            ("Calculator", ICONS.WAND_MAGIC, lambda: self._cmd("Open calculator")),
            ("File explorer", ICONS.WORKSPACE, lambda: self._cmd("Open file manager")),
            ("Settings",   ICONS.SETTINGS, lambda: self._show_settings()),
        ]):
            b = QPushButton(f"  {name}"); b.setObjectName("GhostBtn")
            b.setIcon(icon(icn, C.TEXT, 14)); b.setMinimumHeight(42)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            self._cc_buttons.append(b)
            self._cc_grid.addWidget(b, col // 3, col % 3)
        comp_card.body.addLayout(self._cc_grid)
        cols.addWidget(comp_card)

        scroller.setWidget(sw)
        root.addWidget(scroller, 1)

        self._grid_cols = self._calc_grid_cols()
        QTimer.singleShot(0, self._reload)

    def _calc_grid_cols(self) -> int:
        w = self.width()
        if w >= 1400:
            return 4
        elif w >= 1050:
            return 3
        return 2

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_cols = self._calc_grid_cols()
        if new_cols != getattr(self, "_grid_cols", 3):
            self._grid_cols = new_cols
            self._reposition_grids()

    def _reposition_grids(self):
        from ..ds import clear_layout
        cols = getattr(self, "_grid_cols", 3)
        # Reposition mobile tiles
        if hasattr(self, "_mobile_tiles") and self._mobile_tiles:
            for w in self._mobile_tiles:
                self._mobile_grid.removeWidget(w)
            for i, w in enumerate(self._mobile_tiles):
                self._mobile_grid.addWidget(w, i // cols, i % cols)
        # Reposition smart tiles
        if hasattr(self, "_sh_tiles") and self._sh_tiles:
            for w in self._sh_tiles:
                self._sh_grid.removeWidget(w)
            for i, w in enumerate(self._sh_tiles):
                self._sh_grid.addWidget(w, i // cols, i % cols)
        # Reposition comp buttons
        if hasattr(self, "_cc_buttons") and self._cc_buttons:
            cc_cols = 6 if cols >= 4 else (3 if cols >= 3 else 2)
            for b in self._cc_buttons:
                self._cc_grid.removeWidget(b)
            for i, b in enumerate(self._cc_buttons):
                self._cc_grid.addWidget(b, i // cc_cols, i % cc_cols)

    # ------------------------------ helpers ---------------------------
    def _stat(self, title: str, value: str, icon_name: str, color: str) -> QFrame:
        w = QFrame(); w.setProperty("class", "CardPanel")
        l = QHBoxLayout(w); l.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        l.setSpacing(Spacing.MD)
        tile = QLabel(); tile.setFixedSize(38, 38)
        tile.setStyleSheet(
            f"background: {rgba_str(color, 0.14)}; "
            f"border-radius: {Radius.MD}px;"
        )
        tl = QVBoxLayout(tile); tl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel(); ic.setPixmap(icon_pixmap(icon_name, color, 16)); ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tl.addWidget(ic)
        l.addWidget(tile)
        col = QVBoxLayout(); col.setSpacing(0)
        t = QLabel(str(value)); t.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {C.TEXT};")
        s = QLabel(title); s.setStyleSheet(f"font-size: 11px; color: {C.TEXT_DIM}; letter-spacing: 0.4px;")
        col.addWidget(t); col.addWidget(s)
        l.addLayout(col, 1)
        w._val_lbl = t
        return w

    # ------------------------------ data ------------------------------
    def _reload(self):
        self._mobile_loading.setVisible(True)
        self._sh_loading.setVisible(True)
        w1 = DashboardWorker(load_paired_devices)
        w1.result_sig.connect(self._on_devices)
        self._workers.append(w1)
        w1.start()
        w2 = DashboardWorker(load_smart_home_devices)
        w2.result_sig.connect(self._on_smart)
        self._workers.append(w2)
        w2.start()

    def _on_devices(self, result):
        self._mobile_loading.setVisible(False)
        if isinstance(result, dict):
            self._paired = list(result.get("devices") or [])
        else:
            self._paired = list(result or [])
        # filter search
        q = (self._search.text() or "").lower()
        if q:
            self._paired = [d for d in self._paired if q in (str(d.get("name") or "") + " " + str(d.get("device_id") or "")).lower()]
        # Clear grid
        from ..ds import clear_layout
        clear_layout(self._mobile_grid)
        self._mobile_tiles = []
        online_count = 0
        if not self._paired:
            self._mobile_grid_w.setVisible(False)
            self._mobile_empty.setVisible(True)
        else:
            self._mobile_grid_w.setVisible(True)
            self._mobile_empty.setVisible(False)
            cols = getattr(self, "_grid_cols", 3)
            for i, d in enumerate(self._paired):
                name = str(d.get("name") or "Unknown Device")
                status = d.get("status") or ("online" if d.get("online") else "offline")
                online = bool(d.get("online") or status == "online")
                if online: online_count += 1
                battery = d.get("battery")
                info = f"{status}"
                if battery is not None: info += f" · Battery {battery}%"
                tile = MobileControlPanel(d, parent=self._mobile_grid_w)
                self._mobile_tiles.append(tile)
                self._mobile_grid.addWidget(tile, i, 0)
        # Stats
        self._st_devices._val_lbl.setText(str(len(self._paired)))
        self._st_online._val_lbl.setText(str(online_count))

    def _on_smart(self, devices):
        self._sh_loading.setVisible(False)
        self._smart = list(devices or [])
        q = (self._search.text() or "").lower()
        if q:
            self._smart = [d for d in self._smart
                           if q in (str(d.get("name") or "") + " " + str(d.get("room") or "") + " " + str(d.get("type") or "")).lower()]
        from ..ds import clear_layout
        clear_layout(self._sh_grid)
        self._sh_tiles = []
        if not self._smart:
            self._sh_grid_w.setVisible(False)
            self._sh_empty.setVisible(True)
        else:
            self._sh_grid_w.setVisible(True)
            self._sh_empty.setVisible(False)
            cols = getattr(self, "_grid_cols", 3)
            for i, d in enumerate(self._smart):
                name = str(d.get("name") or "Device")
                room = str(d.get("room") or "")
                dtype = str(d.get("type") or "").lower()
                is_on = bool(d.get("is_on") or d.get("on"))
                # Icon + accent
                icon_map = {
                    "light": ICONS.LIGHTBULB, "bulb": ICONS.LIGHTBULB,
                    "fan": ICONS.FAN,
                    "ac": ICONS.THERMOMETER, "air": ICONS.THERMOMETER, "thermostat": ICONS.THERMOMETER,
                    "tv": ICONS.DESKTOP, "switch": ICONS.POWER, "plug": ICONS.POWER,
                    "speaker": ICONS.VOLUME_UP, "camera": ICONS.CAMERA,
                }
                icn = ICONS.LIGHTBULB
                for k, v in icon_map.items():
                    if k in dtype: icn = v; break
                accent = C.SEC_CONNECTED if is_on else C.TEXT_DIM
                info = f"{room} · {dtype or 'switch'}".strip(" ·")
                tile = DeviceTile(icn, accent, name, info, is_on)
                # Power toggle
                tg = PowerToggle(is_on,
                                 on_change=lambda on, n=name: self._set_power(n, on))
                tile.action_row.addStretch(1)
                tile.action_row.addWidget(tg)
                self._sh_tiles.append(tile)
                self._sh_grid.addWidget(tile, i // cols, i % cols)
        self._st_smart._val_lbl.setText(str(len(self._smart)))

    # ---------------------------- actions -----------------------------
    def _pair_device(self):
        try:
            dlg = WirelessPairDialog(self)
            dlg.exec()
            self._reload()
        except Exception as e:
            QMessageBox.warning(self, "Pairing error", str(e))

    def _unpair(self, device):
        name = device.get("name") or "device"
        dev_id = device.get("device_id") or ""
        meta = device.get("metadata") or {}
        endpoint = meta.get("endpoint") or meta.get("serial") or ""
        if QMessageBox.question(
            self,
            "Unpair Device",
            f"Permanently unpair and remove {name} from Connected World?\n\nThis will disconnect {name} and delete its saved registration from PostgreSQL.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            from skills.device_management.device_registry import get_device_registry
            from skills.device_management.device_controller import get_device_controller
            from skills.device_management.adb_adapter import get_adb_adapter
            from ..service_adapters import get_identity
            ident = get_identity() or {}
            uid = int(ident.get("user_id") or 1)

            if endpoint and ":" in endpoint:
                h, p = endpoint.split(":", 1)
                try:
                    get_adb_adapter().disconnect_wireless(h, int(p))
                except Exception:
                    pass
            ctrl = get_device_controller()
            if dev_id:
                ctrl.disconnect_device(uid, dev_id)
            reg = get_device_registry()
            if dev_id:
                reg.remove_device(uid, dev_id)
            for r in list(reg.list_devices(uid)):
                rmeta = r.metadata or {}
                if (
                    r.device_id == dev_id
                    or (endpoint and (rmeta.get("endpoint") == endpoint or rmeta.get("serial") == endpoint))
                    or (name and r.name.lower() == name.lower())
                ):
                    reg.remove_device(uid, r.device_id)
        except Exception:
            pass
        self._reload()

    def _discover_smart(self):
        try:
            from skills.smart_home.smart_home_controller import get_smart_home_controller
            from ..service_adapters import get_identity
            ident = get_identity() or {}
            uid = ident.get("user_id") or 1
            ctrl = get_smart_home_controller()
            res = ctrl.handle_command("discover smart devices", int(uid))
            msg = (res or {}).get("message") or "Discovery complete."
            QMessageBox.information(self, "Smart Device Discovery", msg)
        except Exception as e:
            QMessageBox.warning(self, "Discovery notice", str(e))
        QTimer.singleShot(1500, self._reload)

    def _set_power(self, target: str, on: bool):
        w = DashboardWorker(set_smart_home_power, target, bool(on))
        w.result_sig.connect(lambda r: QTimer.singleShot(500, self._reload))
        self._workers.append(w)
        w.start()

    def _cmd(self, text: str):
        from ..service_adapters import send_command
        w = DashboardWorker(send_command, text)
        self._workers.append(w)
        w.start()

    def _cleanup_workers(self):
        """Clean up all worker threads when the page is destroyed."""
        for worker in self._workers:
            if worker and worker.isRunning():
                worker.quit()
                worker.wait()
        self._workers.clear()

    def _show_settings(self):
        mw = self.window()
        if hasattr(mw, "_on_nav"):
            mw._on_nav("settings")

    def on_visible(self):
        self._reload()

__all__ = ["ConnectedWorldPage", "DeviceTile", "PowerToggle", "WirelessPairDialog"]
