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

from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QComboBox, QMessageBox, QGridLayout,
    QMenu, QDialog, QDialogButtonBox, QFormLayout, QCheckBox, QSlider,
    QFileDialog,
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
                tile = DeviceTile(ICONS.PHONE, C.SEC_CONNECTED, name, info, online)
                # actions
                b1 = QPushButton("Battery"); b1.setObjectName("GhostBtn"); b1.setStyleSheet("padding: 4px 8px;")
                b1.setIcon(icon(ICONS.BATTERY, C.TEXT_MED, 11))
                b1.clicked.connect(lambda _=False, x=name: self._cmd(f"Check battery on my {x}"))
                tile.action_row.addWidget(b1)
                b2 = QPushButton("Disconnect"); b2.setObjectName("GhostBtn"); b2.setStyleSheet("padding: 4px 8px;")
                b2.setIcon(icon(ICONS.UNLOCK, C.STATUS_ERROR, 11))
                b2.clicked.connect(lambda _=False, x=d: self._unpair(x))
                tile.action_row.addWidget(b2)
                self._mobile_tiles.append(tile)
                self._mobile_grid.addWidget(tile, i // cols, i % cols)
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
            from skills.device_management.device_controller import DeviceController
            from ..service_adapters import get_identity
            ident = get_identity() or {}
            uid = ident.get("user_id") or 1
            ctrl = DeviceController()
            res = ctrl.pair_device(int(uid))
            if res and res.get("success"):
                code = res.get("code", "")
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Information)
                msg_box.setWindowTitle("Pair Mobile Device")
                if code:
                    msg_box.setText(f"Pairing code: <b style='color:{C.SEC_CONNECTED};font-size:20px;'>{code}</b>")
                    info = res.get("message") or "Enter this code on your mobile device to complete pairing.\nCode expires in 5 minutes."
                    msg_box.setInformativeText(info)
                else:
                    msg_box.setText(res.get("message") or "Pairing started successfully.")
                msg_box.exec()
            else:
                msg = (res or {}).get("message") or "Failed to start pairing."
                QMessageBox.warning(self, "Pairing", msg)
        except Exception as e:
            QMessageBox.warning(self, "Pairing error", str(e))
        QTimer.singleShot(1000, self._reload)

    def _unpair(self, device):
        name = device.get("name") or "device"
        if QMessageBox.question(self, "Unpair?", f"Unpair {name}?") != QMessageBox.StandardButton.Yes:
            return
        # Fallback: remove from registry
        try:
            from skills.device_management.device_registry import get_device_registry
            reg = get_device_registry()
            reg.remove_device(device.get("device_id"))
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
