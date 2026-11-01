"""
Home / Dashboard Page
======================
First page the user sees. Presents:
  • Animated assistant visual (orb)
  • Greeting with real username + assistant name
  • Assistant state chip
  • Main command interface (text + voice)
  • Current activity (task)
  • Recent interactions (from DB)
  • Attention required (reminders, email count)
  • Quick actions (common tasks: new chat, calendar, compose, doc generate)
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGridLayout, QScrollArea, QLineEdit, QMessageBox, QSizePolicy,
)

from ..ds import (
    C, F, Spacing, Radius, ICONS, icon, icon_pixmap,
    HLine, VLine, Card, StatusChip, SectionHeader,
    LoadingState, EmptyState, HoverLift, rgba_str, get_contrast_color,
)
from ..service_adapters import (
    get_identity, send_command, load_recent_history,
    load_reminders, load_calendar_events, load_user_preferences,
)
from ..workers import DashboardWorker
from ._assistant_orb import AssistantOrbWidget


def _time_greeting(hour: Optional[int] = None) -> str:
    h = hour if hour is not None else datetime.now().hour
    if 3 <= h < 12:
        return "Good morning"
    if 12 <= h < 17:
        return "Good afternoon"
    if 17 <= h < 21:
        return "Good evening"
    return "Good night"


class QuickActionCard(QFrame):
    """Futuristic interactive cyber quick action card with glowing accent tile."""

    def __init__(self, icon_name: str, title: str, subtitle: str, accent: str,
                 on_click, parent=None):
        super().__init__(parent)
        self.setProperty("class", "CardInner")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._accent = accent
        self._cb = on_click

        lay = QHBoxLayout(self)
        lay.setContentsMargins(Spacing.MD, Spacing.SM + 2, Spacing.MD, Spacing.SM + 2)
        lay.setSpacing(Spacing.MD)

        # Ambient accent icon tile
        tile = QLabel()
        tile.setFixedSize(40, 40)
        try:
            h = accent.lstrip("#")
            if len(h) >= 6:
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                tile.setStyleSheet(
                    f"background: rgba({r},{g},{b},0.15); "
                    f"border: 1px solid rgba({r},{g},{b},0.35); "
                    f"border-radius: {Radius.MD}px;"
                )
            else:
                tile.setStyleSheet(f"background: rgba(0,212,255,0.15); border-radius: {Radius.MD}px;")
        except Exception:
            tile.setStyleSheet(f"background: rgba(0,212,255,0.15); border-radius: {Radius.MD}px;")

        tile_l = QVBoxLayout(tile)
        tile_l.setContentsMargins(0, 0, 0, 0)
        tile_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel()
        ic.setPixmap(icon_pixmap(icon_name, accent, 20))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile_l.addWidget(ic)
        lay.addWidget(tile, 0)

        # Labels
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(title)
        t.setStyleSheet(f"font-weight: 700; font-size: 13px; color: {C.TEXT}; letter-spacing: -0.2px;")
        s = QLabel(subtitle)
        s.setStyleSheet(f"font-size: 11px; color: {C.TEXT_MED};")
        col.addWidget(t)
        col.addWidget(s)
        lay.addLayout(col, 1)

        # Futuristic indicator arrow
        ar = QLabel("›")
        ar.setStyleSheet(f"color: {rgba_str(accent, 0.70)}; font-size: 18px; font-weight: 700;")
        lay.addWidget(ar)

    def mousePressEvent(self, ev):
        super().mousePressEvent(ev)
        try:
            if self._cb:
                self._cb()
        except Exception:
            pass

    def enterEvent(self, ev):
        super().enterEvent(ev)
        try:
            h = self._accent.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            self.setStyleSheet(
                f".QuickActionCard {{ "
                f"border: 1px solid rgba({r},{g},{b},0.65); "
                f"background: rgba({r},{g},{b},0.08); "
                f"border-radius: {Radius.LG}px; "
                f"}}"
            )
        except Exception:
            self.setStyleSheet(f".QuickActionCard {{ border: 1px solid {rgba_str(C.SEC_DASHBOARD, 0.50)}; background: {C.PANEL3}; }}")

    def leaveEvent(self, ev):
        super().leaveEvent(ev)
        self.setStyleSheet("")


class HomePage(QWidget):
    """
    Advanced 3D AI Command Center Dashboard Page.
    Houses the interactive 3D Spatial Holographic Centerpiece, multimodal command console,
    quick actions deck, attention monitors, and system telemetry feeds.
    """
    navigate = None  # will be set by shell to lambda page_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._identity: Dict = {}
        self._state: Dict = {}
        self._reminders: List[Dict] = []
        self._events: List[Dict] = []
        self._history: List[Dict] = []
        self._workers = []  # Track worker threads for cleanup
        self._build_ui()

    def mouseMoveEvent(self, ev):
        super().mouseMoveEvent(ev)
        pos = ev.position() if hasattr(ev, 'position') else ev.pos()
        pt = pos.toPoint() if hasattr(pos, 'toPoint') else pos
        win = self.window()
        if win and hasattr(win, 'ambient_engine') and win.ambient_engine:
            try:
                win_pos = self.mapTo(win, pt)
                win.ambient_engine.set_mouse_pos(int(win_pos.x()), int(win_pos.y()))
            except Exception:
                pass
        if hasattr(self, "_orb") and self._orb and self._orb.isVisible() and self._orb.parent() is not None:
            try:
                orb_pos = self._orb.mapFrom(self, pt)
                w = float(self._orb.width())
                h = float(self._orb.height())
                dx = (orb_pos.x() - w / 2.0) / max(60.0, w / 2.0)
                dy = (orb_pos.y() - h / 2.0) / max(60.0, h / 2.0)
                self._orb.set_mouse_parallax(dx, dy)
            except Exception:
                pass

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        outer.setSpacing(Spacing.MD)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setMouseTracking(True)
        scroller.setStyleSheet("background: transparent;")

        sw = QWidget()
        sw.setMouseTracking(True)
        sw.setStyleSheet("background: transparent;")
        root = QVBoxLayout(sw)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.LG)

        # ── 1. Open Center Stage for 3D Intelligence Core (No Boxed Card) ───
        ident = get_identity() or {}
        self._identity = ident
        uname = (ident.get("username") or "User").capitalize()
        aname = (ident.get("assistant_name") or "").strip()
        display_asst = aname if aname else "Assistant"

        stage_box = QVBoxLayout()
        stage_box.setContentsMargins(Spacing.MD, Spacing.XS, Spacing.MD, Spacing.XS)
        stage_box.setSpacing(Spacing.XS)

        # Top Bar: Real Telemetry Line & Identity
        top_telemetry = QHBoxLayout()
        top_telemetry.setSpacing(Spacing.SM)

        self._telemetry_top = QLabel("Status: Idle  ·  Uptime: 00:00:00")
        self._telemetry_top.setStyleSheet(
            f"font-size: 11px; font-weight: 600; letter-spacing: 0.5px; color: {C.TEXT_MED};"
        )
        top_telemetry.addWidget(self._telemetry_top)
        top_telemetry.addStretch(1)

        self._state_chip = StatusChip("ONLINE", "online")
        self._state_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        top_telemetry.addWidget(self._state_chip)
        stage_box.addLayout(top_telemetry)

        # Greeting & User / Assistant Identifier
        self._greeting_lbl = QLabel(f"{_time_greeting()}, {uname}")
        self._greeting_lbl.setStyleSheet(
            f"font-size: 26px; font-weight: 800; letter-spacing: -0.6px; color: {C.TEXT};"
        )
        stage_box.addWidget(self._greeting_lbl)

        self._sub_lbl = QLabel("All background services active. Ready for input.")
        self._sub_lbl.setStyleSheet(f"font-size: 12px; color: {C.TEXT_MED}; letter-spacing: 0.2px;")
        stage_box.addWidget(self._sub_lbl)

        # Open Breathing Space for the 3D Core floating in background
        core_void = QWidget()
        core_void.setFixedHeight(120)
        core_void.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        core_void.setStyleSheet("background: transparent;")
        stage_box.addWidget(core_void)

        # Compatibility orb reference
        self._orb = AssistantOrbWidget(1, parent=self)
        self._orb.hide()

        # Breathing space for 3D Extruded Assistant Name rendered under core by engine
        name_spacer = QWidget()
        name_spacer.setFixedHeight(34)
        name_spacer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        name_spacer.setStyleSheet("background: transparent;")
        stage_box.addWidget(name_spacer)

        stage_box.addSpacing(Spacing.SM)

        # Docked Omni Command Bar (Directly below core)
        cmd_wrapper = QHBoxLayout()
        cmd_wrapper.setAlignment(Qt.AlignmentFlag.AlignCenter)

        cmd_card = QFrame()
        cmd_card.setMinimumWidth(620)
        cmd_card.setMaximumWidth(820)
        cmd_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        cmd_card.setStyleSheet(f"""
            QFrame {{
                background: rgba(10, 16, 26, 0.70);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-top: 1px solid rgba(255, 255, 255, 0.22);
                border-radius: 22px;
            }}
            QFrame:focus-within {{
                border: 1px solid {C.ACC};
                background: rgba(12, 20, 34, 0.85);
            }}
        """)
        cmd_lay = QHBoxLayout(cmd_card)
        cmd_lay.setContentsMargins(Spacing.MD, 4, 6, 4)
        cmd_lay.setSpacing(Spacing.SM)

        cmd_icon = QLabel()
        cmd_icon.setPixmap(icon_pixmap(ICONS.TERMINAL if hasattr(ICONS, "TERMINAL") else ICONS.SEARCH, C.ACC, 16))
        cmd_icon.setStyleSheet("background: transparent;")
        cmd_lay.addWidget(cmd_icon)

        self._cmd_input = QLineEdit()
        self._cmd_input.setPlaceholderText(f"Ask {display_asst} anything, query system, or issue instructions…")
        self._cmd_input.setCursor(Qt.CursorShape.IBeamCursor)
        self._cmd_input.setStyleSheet(f"""
            QLineEdit {{
                border: none;
                background: transparent;
                padding: 8px 6px;
                font-size: 13px;
                font-weight: 500;
                color: {C.TEXT};
            }}
        """)
        self._cmd_input.returnPressed.connect(self._on_send)
        cmd_lay.addWidget(self._cmd_input, 1)

        self._mic_btn = QPushButton()
        self._mic_btn.setObjectName("IconBtn")
        self._mic_btn.setIcon(icon(ICONS.MIC, C.ACC, 16))
        self._mic_btn.setToolTip("Voice Command (Push to speak)")
        self._mic_btn.setFixedSize(34, 34)
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mic_btn.clicked.connect(lambda: self._send_as_command("Toggle voice listening"))
        cmd_lay.addWidget(self._mic_btn)

        self._send_btn = QPushButton()
        self._send_btn.setObjectName("PrimaryBtn")
        self._send_btn.setIcon(icon(ICONS.SEND, get_contrast_color(C.ACC), 15))
        self._send_btn.setToolTip("Execute Command (Enter)")
        self._send_btn.setFixedSize(36, 36)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send)
        cmd_lay.addWidget(self._send_btn)

        cmd_wrapper.addWidget(cmd_card)
        stage_box.addLayout(cmd_wrapper)

        # Quick Suggestion Chips below input
        sugg_wrapper = QHBoxLayout()
        sugg_wrapper.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sugg_row = QHBoxLayout()
        sugg_row.setSpacing(Spacing.SM)
        suggestions = [
            ("⚡ Open Notepad", "Open Notepad"),
            ("📅 Schedule", "What is on my schedule today?"),
            ("📄 Create Document", "Create a new document"),
            ("🧠 Memory", "What do you remember about me?"),
        ]
        for label, cmd_text in suggestions:
            s_btn = QPushButton(label)
            s_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.04);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 11px;
                    color: {C.TEXT_MED};
                    font-size: 11px;
                    font-weight: 500;
                    padding: 3px 11px;
                }}
                QPushButton:hover {{
                    background: {rgba_str(C.ACC, 0.12)};
                    border-color: {rgba_str(C.ACC, 0.40)};
                    color: {C.ACC};
                }}
            """)
            s_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            s_btn.clicked.connect(lambda _=False, t=cmd_text: self._execute_suggestion(t))
            sugg_row.addWidget(s_btn)
        sugg_wrapper.addLayout(sugg_row)
        stage_box.addLayout(sugg_wrapper)

        stage_w = QWidget()
        stage_w.setLayout(stage_box)
        root.addWidget(stage_w)

        # ── 2. Three Open Spatial Columns (Attention / Current / Recent) ────
        cols = QHBoxLayout()
        cols.setSpacing(Spacing.LG)

        self._cols_w = QWidget(self)
        self._cols_w.setLayout(cols)
        self._cols_w.hide()

        # Column 1: Attention Required (Open column: hairline rule, monospace caption, plain rows)
        col1 = QWidget(self._cols_w)
        col1_lay = QVBoxLayout(col1)
        col1_lay.setContentsMargins(0, 0, 0, 0)
        col1_lay.setSpacing(Spacing.SM)

        hdr1 = QLabel("Attention Required")
        hdr1.setStyleSheet(f"font-size: 12px; font-weight: 700; letter-spacing: 0.5px; color: {C.TEXT}; background: transparent;")
        col1_lay.addWidget(hdr1)
        col1_lay.addWidget(HLine(rgba_str(C.TEXT_DIM, 0.18), 1))

        self._attn_stack = QVBoxLayout()
        self._attn_stack.setSpacing(Spacing.XS)
        self._attn_loading = LoadingState("Scanning reminders and events…")
        self._attn_stack.addWidget(self._attn_loading)
        col1_lay.addLayout(self._attn_stack)
        col1_lay.addStretch(1)
        cols.addWidget(col1, 1)

        # Column 2: Current Activity (Open column: hairline rule, clean typography, plain rows)
        col2 = QWidget(self._cols_w)
        col2_lay = QVBoxLayout(col2)
        col2_lay.setContentsMargins(0, 0, 0, 0)
        col2_lay.setSpacing(Spacing.SM)

        hdr2 = QLabel("Current Activity")
        hdr2.setStyleSheet(f"font-size: 12px; font-weight: 700; letter-spacing: 0.5px; color: {C.TEXT}; background: transparent;")
        col2_lay.addWidget(hdr2)
        col2_lay.addWidget(HLine(rgba_str(C.TEXT_DIM, 0.18), 1))

        self._act_stack = QVBoxLayout()
        self._act_stack.setSpacing(Spacing.SM)
        self._act_empty = self._create_plain_empty_row(ICONS.POWER, "All systems nominal", "No active background tasks running")
        self._act_stack.addWidget(self._act_empty)
        col2_lay.addLayout(self._act_stack)
        col2_lay.addStretch(1)
        cols.addWidget(col2, 1)

        # Column 3: Recent Interactions (Open column: hairline rule, clean typography, plain rows)
        col3 = QWidget(self._cols_w)
        col3_lay = QVBoxLayout(col3)
        col3_lay.setContentsMargins(0, 0, 0, 0)
        col3_lay.setSpacing(Spacing.SM)

        hdr3 = QLabel("Recent Interactions")
        hdr3.setStyleSheet(f"font-size: 12px; font-weight: 700; letter-spacing: 0.5px; color: {C.TEXT}; background: transparent;")
        col3_lay.addWidget(hdr3)
        col3_lay.addWidget(HLine(rgba_str(C.TEXT_DIM, 0.18), 1))

        self._hist_stack = QVBoxLayout()
        self._hist_stack.setSpacing(Spacing.XS)
        self._hist_loading = LoadingState("Loading conversation history…")
        self._hist_stack.addWidget(self._hist_loading)
        col3_lay.addLayout(self._hist_stack)
        col3_lay.addStretch(1)
        cols.addWidget(col3, 1)

        # ── 3. Quick Actions Deck ───────────────────────────────────────────
        root.addWidget(SectionHeader("Quick Actions", f"Instant access to core {display_asst} subsystems", accent=C.ACC))
        qa_grid = QGridLayout()
        qa_grid.setSpacing(Spacing.MD)

        actions = [
            (ICONS.ASSISTANT,     "Conversation", "Direct neural dialogue",       C.ACC, lambda: self._go("assistant")),
            (ICONS.COMMUNICATIONS, "Email",        "Inbox, compose & drafts",     C.ACC, lambda: self._go_quick("communications", "compose")),
            (ICONS.SCHEDULE,       "Schedule",     "Calendar, events & reminders", C.ACC, lambda: self._go("schedule")),
            (ICONS.FILE_PDF,     "Document",     "PDF, DOCX & sheets generator",  C.ACC, lambda: self._go("workspace")),
            (ICONS.CONNECTED_WORLD, "Devices",      "Connected devices & mobile",  C.ACC, lambda: self._go("connected_world")),
            (ICONS.INTELLIGENCE,    "Memory",       "Knowledge base & facts",      C.ACC, lambda: self._go("intelligence")),
        ]

        for idx, (icn, title, subtitle, acc_col, cb) in enumerate(actions):
            card = QuickActionCard(icn, title, subtitle, acc_col, cb)
            row = idx // 3
            col = idx % 3
            qa_grid.addWidget(card, row, col)

        qa_w = QWidget()
        qa_w.setLayout(qa_grid)
        root.addWidget(qa_w)

        scroller.setWidget(sw)
        outer.addWidget(scroller, 1)

        # Refresh timers
        QTimer.singleShot(0, self._refresh_attention)
        QTimer.singleShot(100, self._refresh_history)

    def _execute_suggestion(self, text: str):
        self._cmd_input.setText(text)
        self._on_send()

    # ---------------------- helpers --------------------------------------
    def _go(self, page_id: str):
        mw = self.window()
        if hasattr(mw, "_on_nav"):
            mw._on_nav(page_id)
        elif HomePage.navigate:
            HomePage.navigate(page_id)

    def _go_quick(self, page_id: str, action: str):
        self._go(page_id)
        if page_id == "communications" and action == "compose":
            mw = self.window()
            if hasattr(mw, "_page_map") and "communications" in mw._page_map:
                comm_page = mw._page_map["communications"]
                if hasattr(comm_page, "_open_compose"):
                    QTimer.singleShot(150, comm_page._open_compose)

    def _on_send(self):
        txt = self._cmd_input.text().strip()
        if not txt:
            return
        self._send_as_command(txt)
        self._cmd_input.clear()

    def _send_as_command(self, txt: str):
        self._cmd_input.clear()
        w = DashboardWorker(send_command, txt)
        w.result_sig.connect(lambda r: self._refresh_history())
        self._workers.append(w)
        w.start()

    def on_identity(self, ident: Dict):
        self._identity = ident
        uname = (ident.get("username") or "User").capitalize()
        aname = (ident.get("assistant_name") or "").strip()
        display_asst = aname if aname else "Assistant"
        self._greeting_lbl.setText(f"{_time_greeting()}, {uname}")
        if hasattr(self, '_cmd_input'):
            self._cmd_input.setPlaceholderText(f"Ask {display_asst} anything, query system, or issue instructions…")

    def set_audio_level(self, level: float):
        """Pass live audio amplitude into the assistant orb centerpiece."""
        if hasattr(self, '_orb') and self._orb:
            self._orb.set_audio_level(level)

    def sync_tick(self, master_time: float):
        """Synchronize with master clock."""
        if hasattr(self, '_orb') and self._orb and hasattr(self._orb, 'sync_tick'):
            self._orb.sync_tick(master_time)

    def _create_plain_empty_row(self, icon_name: str, title: str, subtitle: str) -> QWidget:
        """Render a clean, plain open-column row without boxed card containers."""
        w = QWidget()
        w.setStyleSheet("background: transparent; border: none;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, Spacing.XS, 0, Spacing.XS)
        lay.setSpacing(Spacing.MD)

        ic = QLabel()
        ic.setPixmap(icon_pixmap(icon_name, C.TEXT_DIM, 14))
        ic.setStyleSheet("background: transparent;")
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 0, 0, 0)
        t = QLabel(title)
        t.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {C.TEXT}; background: transparent;")
        st = QLabel(subtitle)
        st.setStyleSheet(f"font-size: 11px; color: {C.TEXT_DIM}; background: transparent;")
        col.addWidget(t)
        col.addWidget(st)
        lay.addLayout(col, 1)
        return w

    def on_assistant_state(self, data: Dict):
        self._state = data
        display_asst = (self._identity.get("assistant_name") or "Assistant").strip() or "Assistant"
        s = (data.get("state") or "idle").lower()
        if hasattr(self, '_orb') and self._orb:
            self._orb.on_assistant_state(data)
        self._state_chip.set_state(s)
        self._state_chip.setText(s.upper())

        # Real telemetry readouts
        uptime = int(data.get("uptime_seconds") or 0)
        uptime_str = f"{uptime // 3600:02d}:{(uptime % 3600) // 60:02d}:{uptime % 60:02d}"
        task = data.get("active_operation") or data.get("task")
        prog = data.get("progress") or 0

        if hasattr(self, '_telemetry_top'):
            if task:
                prog_str = f" ({int(prog)}%)" if prog else ""
                self._telemetry_top.setText(f"Status: {s.capitalize()}  ·  Task: {str(task)}{prog_str}  ·  Uptime: {uptime_str}")
            else:
                self._telemetry_top.setText(f"Status: {s.capitalize()}  ·  Uptime: {uptime_str}")

        if hasattr(self, '_sub_lbl'):
            if task:
                self._sub_lbl.setText(f"Active task: {task}")
            elif self._reminders or self._events:
                rc = len(self._reminders)
                ec = len(self._events)
                self._sub_lbl.setText(f"{rc} reminder{'s' if rc != 1 else ''} pending  •  {ec} calendar event{'s' if ec != 1 else ''} today")
            else:
                self._sub_lbl.setText("All background services active. Ready for input.")

        try:
            import sip
            if hasattr(self, '_act_stack') and self._act_stack is not None and not sip.isdeleted(self._act_stack):
                from ..ds import clear_layout
                clear_layout(self._act_stack)
                if task:
                    row_w = QWidget()
                    row_w.setStyleSheet("background: transparent; border: none; border-bottom: 1px solid rgba(255, 255, 255, 0.05); padding: 4px 0px;")
                    rl = QHBoxLayout(row_w)
                    rl.setContentsMargins(0, 4, 0, 4)
                    rl.setSpacing(Spacing.MD)
                    chip = StatusChip("RUNNING", "executing")
                    rl.addWidget(chip)
                    lbl = QLabel(str(task))
                    lbl.setStyleSheet(f"font-weight: 600; font-size: 12px; color: {C.TEXT}; background: transparent;")
                    rl.addWidget(lbl)
                    rl.addStretch(1)
                    if prog:
                        from PyQt6.QtWidgets import QProgressBar
                        bar = QProgressBar()
                        bar.setFixedWidth(140)
                        bar.setFixedHeight(5)
                        bar.setValue(int(prog))
                        bar.setTextVisible(False)
                        rl.addWidget(bar)
                    self._act_stack.addWidget(row_w)
                else:
                    empty = self._create_plain_empty_row(ICONS.POWER, "All systems nominal", f"{display_asst} background processes idle. Standing by.")
                    self._act_stack.addWidget(empty)
        except Exception:
            pass

    # ---------------------- attention ---------------------------------------------
    def _refresh_attention(self):
        w1 = DashboardWorker(load_reminders)
        w1.result_sig.connect(self._on_reminders)
        self._workers.append(w1)
        w1.start()
        w2 = DashboardWorker(load_calendar_events)
        w2.result_sig.connect(self._on_events)
        self._workers.append(w2)
        w2.start()

    def _on_reminders(self, rems):
        self._reminders = list(rems or [])
        self._refresh_attn_ui()

    def _on_events(self, evs):
        self._events = list(evs or [])
        self._refresh_attn_ui()

    def _refresh_attn_ui(self):
        try:
            import sip
            if not hasattr(self, '_attn_stack') or self._attn_stack is None or sip.isdeleted(self._attn_stack):
                return
        except Exception:
            return
        try:
            from ..ds import clear_layout
            clear_layout(self._attn_stack)
            items = []
            for r in self._reminders[:5]:
                if not r.get("is_notified"):
                    items.append((ICONS.BELL if hasattr(ICONS, "BELL") else ICONS.SCHEDULE,
                                  "Reminder", r.get("task_text", "")[:60],
                                  str(r.get("due_at") or "")[:16]))
            for e in self._events[:5]:
                items.append((ICONS.SCHEDULE, "Event", (e.get("title") or "")[:60],
                             f"{e.get('date') or ''} {e.get('time') or ''}".strip()))
            if not items:
                empty = self._create_plain_empty_row(ICONS.CHECK, "Nothing urgent", "No upcoming reminders or events require your attention.")
                self._attn_stack.addWidget(empty)
                return
            for icon_name, kind, text, when in items:
                w = QWidget()
                w.setStyleSheet("background: transparent; border: none; border-bottom: 1px solid rgba(255, 255, 255, 0.05); padding: 4px 0px;")
                l = QHBoxLayout(w)
                l.setContentsMargins(0, 4, 0, 4)
                l.setSpacing(Spacing.MD)
                ic = QLabel()
                ic.setPixmap(icon_pixmap(icon_name, C.ACC, 13))
                ic.setStyleSheet("background: transparent;")
                l.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
                c = QVBoxLayout()
                c.setSpacing(2)
                c.setContentsMargins(0, 0, 0, 0)
                t = QLabel(text)
                t.setStyleSheet(f"font-weight: 500; font-size: 12px; color: {C.TEXT}; background: transparent;")
                k = QLabel(f"{kind.capitalize()}  ·  {when}")
                k.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px; background: transparent;")
                c.addWidget(t)
                c.addWidget(k)
                l.addLayout(c, 1)
                self._attn_stack.addWidget(w)
        except Exception:
            pass

    # ---------------------- history -----------------------------------------
    def _refresh_history(self):
        w = DashboardWorker(load_recent_history, 8)
        w.result_sig.connect(self._on_history)
        self._workers.append(w)
        w.start()

    def _cleanup_workers(self):
        """Clean up all worker threads when the page is destroyed."""
        for worker in self._workers:
            if worker and worker.isRunning():
                worker.quit()
                worker.wait()
        self._workers.clear()

    def _on_history(self, items):
        self._history = list(items or [])
        try:
            import sip
            if not hasattr(self, '_hist_stack') or self._hist_stack is None or sip.isdeleted(self._hist_stack):
                return
        except Exception:
            return
        try:
            from ..ds import clear_layout
            clear_layout(self._hist_stack)
            msgs = [m for m in self._history if m.get("role") == "user"]
            if not msgs:
                empty = self._create_plain_empty_row(ICONS.ASSISTANT, "No conversations yet", "Start by typing above or open Assistant page.")
                self._hist_stack.addWidget(empty)
                return
            for m in msgs[-5:]:
                w = QWidget()
                w.setStyleSheet("background: transparent; border: none; border-bottom: 1px solid rgba(255, 255, 255, 0.05); padding: 4px 0px;")
                l = QHBoxLayout(w)
                l.setContentsMargins(0, 4, 0, 4)
                l.setSpacing(Spacing.MD)
                av = QLabel()
                av.setPixmap(icon_pixmap(ICONS.COMMENT if hasattr(ICONS, "COMMENT") else ICONS.ASSISTANT, C.ACC, 13))
                av.setStyleSheet("background: transparent;")
                l.addWidget(av, 0, Qt.AlignmentFlag.AlignTop)
                col = QVBoxLayout()
                col.setSpacing(2)
                col.setContentsMargins(0, 0, 0, 0)
                t = QLabel((m.get("content") or "")[:90])
                t.setStyleSheet(f"color: {C.TEXT}; font-size: 12px; background: transparent;")
                t.setWordWrap(True)
                col.addWidget(t)
                sub = QLabel(f"Query  ·  {str(m.get('created_at') or '')[:16]}")
                sub.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px; background: transparent;")
                col.addWidget(sub)
                l.addLayout(col, 1)
                self._hist_stack.addWidget(w)
        except Exception:
            pass

    def on_visible(self):
        self._refresh_attention()
        self._refresh_history()
