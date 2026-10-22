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
    Houses the interactive 3D Friday Holographic Centerpiece, multimodal command console,
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
        if hasattr(self, "_orb") and self._orb:
            pos = ev.position() if hasattr(ev, 'position') else ev.pos()
            orb_pos = self._orb.mapFrom(self, pos.toPoint() if hasattr(pos, 'toPoint') else pos)
            w = float(self._orb.width())
            h = float(self._orb.height())
            dx = (orb_pos.x() - w / 2.0) / max(60.0, w / 2.0)
            dy = (orb_pos.y() - h / 2.0) / max(60.0, h / 2.0)
            self._orb.set_mouse_parallax(dx, dy)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        outer.setSpacing(Spacing.MD)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setMouseTracking(True)

        sw = QWidget()
        sw.setMouseTracking(True)
        root = QVBoxLayout(sw)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.LG)

        # ── 1. Advanced 3D Command Deck (Hero Cockpit) ──────────────────────
        hero_card = QFrame()
        hero_card.setProperty("class", "CardInner")
        hero_card.setMouseTracking(True)
        hero_card.setStyleSheet(f"""
            QFrame[class="CardInner"] {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(8, 14, 24, 0.85),
                    stop:0.5 rgba(12, 20, 34, 0.75),
                    stop:1 rgba(6, 12, 20, 0.90));
                border: 1px solid rgba(0, 212, 255, 0.22);
                border-radius: {Radius.XL}px;
            }}
        """)

        hero_lay = QHBoxLayout(hero_card)
        hero_lay.setContentsMargins(Spacing.LG2, Spacing.LG, Spacing.LG2, Spacing.LG)
        hero_lay.setSpacing(Spacing.XL)

        # Left Column: Mission Telemetry, Identity, and Command Console
        left = QVBoxLayout()
        left.setSpacing(Spacing.SM)

        # Top breadcrumb telemetry line
        telemetry_top = QLabel("FRIDAY INTELLIGENCE SYSTEM // 3D COMMAND DECK")
        telemetry_top.setStyleSheet(
            f"font-size: 10px; font-weight: 700; letter-spacing: 2.2px; color: {C.SEC_DASHBOARD};"
        )
        left.addWidget(telemetry_top)

        # Greeting & User / Assistant Identifier
        self._greeting_lbl = QLabel("Good morning,")
        self._greeting_lbl.setStyleSheet(
            f"font-size: 26px; font-weight: 800; letter-spacing: -0.6px; color: {C.TEXT};"
        )
        left.addWidget(self._greeting_lbl)

        self._name_row = QHBoxLayout()
        self._name_row.setSpacing(Spacing.SM)
        self._user_lbl = QLabel("User")
        self._user_lbl.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {C.SEC_DASHBOARD}; letter-spacing: -0.3px;")
        self._dot = QLabel("//")
        self._dot.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 15px; font-weight: 600; padding: 0 2px;")
        self._asst_lbl = QLabel("Friday")
        self._asst_lbl.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {C.TEXT_MED}; letter-spacing: -0.1px;")
        self._name_row.addWidget(self._user_lbl)
        self._name_row.addWidget(self._dot)
        self._name_row.addWidget(self._asst_lbl)
        self._name_row.addStretch(1)

        self._state_chip = StatusChip("ONLINE", "online")
        self._state_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._name_row.addWidget(self._state_chip)
        left.addLayout(self._name_row)

        self._sub_lbl = QLabel("Primary neural core online. All subsystems operating nominally.")
        self._sub_lbl.setStyleSheet(f"font-size: 12px; color: {C.TEXT_MED}; letter-spacing: 0.1px;")
        left.addWidget(self._sub_lbl)

        left.addSpacing(Spacing.MD)

        # Futuristic Command Console Bar
        cmd_card = QFrame()
        cmd_card.setStyleSheet(f"""
            QFrame {{
                background: rgba(6, 12, 22, 0.75);
                border: 1px solid rgba(0, 212, 255, 0.32);
                border-radius: {Radius.LG}px;
            }}
            QFrame:focus-within {{
                border: 1px solid #00D4FF;
                background: rgba(0, 212, 255, 0.05);
            }}
        """)
        cmd_lay = QVBoxLayout(cmd_card)
        cmd_lay.setContentsMargins(Spacing.SM + 2, Spacing.SM, Spacing.SM + 2, Spacing.SM)
        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(Spacing.SM)

        self._cmd_input = QLineEdit()
        self._cmd_input.setPlaceholderText("Ask Friday anything, search knowledge, or issue system commands…")
        self._cmd_input.setCursor(Qt.CursorShape.IBeamCursor)
        self._cmd_input.setStyleSheet(f"""
            QLineEdit {{
                border: none;
                background: transparent;
                padding: 10px 8px;
                font-size: 14px;
                font-weight: 500;
                color: {C.TEXT};
            }}
        """)
        self._cmd_input.returnPressed.connect(self._on_send)
        cmd_row.addWidget(self._cmd_input, 1)

        self._mic_btn = QPushButton()
        self._mic_btn.setObjectName("IconBtn")
        self._mic_btn.setIcon(icon(ICONS.MIC, C.SEC_DASHBOARD, 18))
        self._mic_btn.setToolTip("Voice Command (Push to speak)")
        self._mic_btn.setFixedSize(38, 38)
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mic_btn.clicked.connect(lambda: self._send_as_command("Toggle voice listening"))
        cmd_row.addWidget(self._mic_btn)

        self._send_btn = QPushButton()
        self._send_btn.setObjectName("PrimaryBtn")
        self._send_btn.setIcon(icon(ICONS.SEND, get_contrast_color(C.SEC_DASHBOARD), 17))
        self._send_btn.setToolTip("Execute Command (Enter)")
        self._send_btn.setFixedSize(40, 40)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send)
        cmd_row.addWidget(self._send_btn)

        cmd_lay.addLayout(cmd_row)
        left.addWidget(cmd_card)

        # Quick Suggestion Chips below input
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
                    border-radius: {Radius.SM}px;
                    color: {C.TEXT_MED};
                    font-size: 11px;
                    font-weight: 500;
                    padding: 4px 10px;
                }}
                QPushButton:hover {{
                    background: rgba(0, 212, 255, 0.12);
                    border-color: rgba(0, 212, 255, 0.40);
                    color: {C.SEC_DASHBOARD};
                }}
            """)
            s_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            s_btn.clicked.connect(lambda _=False, t=cmd_text: self._execute_suggestion(t))
            sugg_row.addWidget(s_btn)
        sugg_row.addStretch(1)
        left.addLayout(sugg_row)
        left.addStretch(1)

        # Right Column: 3D Holographic AI Orb Centerpiece
        self._orb = AssistantOrbWidget(260)
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.setSpacing(Spacing.XS)

        orb_header = QLabel("HOLOGRAPHIC CORE // 3D MATRIX")
        orb_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        orb_header.setStyleSheet(
            f"color: {C.SEC_DASHBOARD}; font-size: 9px; font-weight: 700; letter-spacing: 2px;"
        )
        right.addWidget(orb_header)
        right.addWidget(self._orb)

        self._orb_sub = QLabel("READY")
        self._orb_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._orb_sub.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 11px; font-weight: 700; letter-spacing: 2.2px;")
        right.addWidget(self._orb_sub)

        right_w = QWidget()
        right_w.setMouseTracking(True)
        right_w.setLayout(right)
        right_w.setMinimumWidth(280)
        right_w.setMaximumWidth(320)

        hero_lay.addLayout(left, 1)
        hero_lay.addWidget(right_w, 0)
        root.addWidget(hero_card)

        # ── 2. Futuristic Quick Actions Command Deck ────────────────────────
        root.addWidget(SectionHeader("Quick Actions", "Instant access to core Friday subsystems", accent=C.SEC_DASHBOARD))
        qa_grid = QGridLayout()
        qa_grid.setSpacing(Spacing.MD)

        actions = [
            (ICONS.ASSISTANT,     "Conversation", "Direct neural dialogue",       C.SEC_ASSISTANT,     lambda: self._go("assistant")),
            (ICONS.COMMUNICATIONS, "Email",        "Inbox, compose & drafts",     C.SEC_COMMUNICATIONS, lambda: self._go_quick("communications", "compose")),
            (ICONS.SCHEDULE,       "Schedule",     "Calendar, events & reminders", C.SEC_SCHEDULE,       lambda: self._go("schedule")),
            (ICONS.FILE_PDF,     "Document",     "PDF, DOCX & sheets generator",  C.SEC_WORKSPACE,      lambda: self._go("workspace")),
            (ICONS.CONNECTED_WORLD, "Devices",      "Connected devices & mobile",  C.SEC_CONNECTED,      lambda: self._go("connected_world")),
            (ICONS.INTELLIGENCE,    "Memory",       "Knowledge base & facts",      C.SEC_INTELLIGENCE,   lambda: self._go("intelligence")),
        ]

        for idx, (icn, title, subtitle, acc_col, cb) in enumerate(actions):
            card = QuickActionCard(icn, title, subtitle, acc_col, cb)
            row = idx // 3
            col = idx % 3
            qa_grid.addWidget(card, row, col)

        qa_w = QWidget()
        qa_w.setLayout(qa_grid)
        root.addWidget(qa_w)

        # ── 3. Attention Required & Recent Interactions Columns ─────────────
        cols = QHBoxLayout()
        cols.setSpacing(Spacing.MD)

        # Attention column
        col_left = Card(title="Attention Required", accent=C.STATUS_WARNING)
        col_left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._attn_stack = QVBoxLayout()
        self._attn_stack.setSpacing(Spacing.SM)
        self._attn_loading = LoadingState("Scanning reminders, events, and pending tasks…")
        self._attn_stack.addWidget(self._attn_loading)
        col_left.body.addLayout(self._attn_stack)
        cols.addWidget(col_left, 1)

        # Recent column
        col_right = Card(title="Recent Interactions", accent=C.SEC_INTELLIGENCE)
        col_right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._hist_stack = QVBoxLayout()
        self._hist_stack.setSpacing(Spacing.SM)
        self._hist_loading = LoadingState("Loading neural conversation history…")
        self._hist_stack.addWidget(self._hist_loading)
        col_right.body.addLayout(self._hist_stack)
        cols.addWidget(col_right, 1)

        cols_w = QWidget()
        cols_w.setLayout(cols)
        cols_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(cols_w, 2)

        # ── 4. Current Activity & System Telemetry Strip ────────────────────
        act = Card(title="System Operations & Telemetry", accent=C.STATUS_ACTIVE)
        act.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._act_stack = QVBoxLayout()
        self._act_stack.setSpacing(Spacing.SM)
        self._act_empty = EmptyState(ICONS.POWER, "All systems nominal",
                                    "Friday background processes idle. Standing by for instructions.",
                                    accent=C.STATUS_ACTIVE)
        self._act_stack.addWidget(self._act_empty)
        act.body.addLayout(self._act_stack)
        root.addWidget(act, 1)

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

    # ---------------------- identity / state ------------------------------
    def on_identity(self, ident: Dict):
        self._identity = ident
        uname = (ident.get("username") or "User").capitalize()
        aname = ident.get("assistant_name") or "Trevon"
        self._greeting_lbl.setText(_time_greeting() + ",")
        self._user_lbl.setText(uname)
        self._asst_lbl.setText(f"I'm your assistant {aname}")

    def on_assistant_state(self, data: Dict):
        self._state = data
        s = (data.get("state") or "idle").lower()
        self._orb.on_assistant_state(data)
        self._state_chip.set_state(s)
        self._state_chip.setText(s.upper())
        labels = {
            "idle": "Ready",
            "listening": "Listening…",
            "thinking": "Thinking…",
            "speaking": "Speaking…",
            "executing": "Executing…",
            "working": "Working…",
            "processing": "Processing…",
            "error": "Error",
            "offline": "Offline",
        }
        self._orb_sub.setText(labels.get(s, "Ready"))
        try:
            # current activity
            task = data.get("active_operation") or data.get("task")
            prog = data.get("progress") or 0
            from ..ds import clear_layout
            clear_layout(self._act_stack)
            if task:
                # Build activity widget
                row_w = QWidget()
                rl = QHBoxLayout(row_w); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(Spacing.MD)
                chip = StatusChip("RUNNING", "executing")
                rl.addWidget(chip)
                lbl = QLabel(str(task))
                lbl.setStyleSheet(f"font-weight: 600; color: {C.TEXT};")
                rl.addWidget(lbl)
                rl.addStretch(1)
                if prog:
                    from PyQt6.QtWidgets import QProgressBar
                    bar = QProgressBar()
                    bar.setFixedWidth(200)
                    bar.setFixedHeight(8)
                    bar.setValue(int(prog))
                    bar.setTextVisible(False)
                    rl.addWidget(bar)
                self._act_stack.addWidget(row_w)
            else:
                empty = EmptyState(ICONS.POWER, "All systems idle",
                                   "Assistant isn't doing anything right now.",
                                   accent=C.STATUS_ACTIVE)
                self._act_stack.addWidget(empty)
        except Exception as e:
            print(f"[HOME_PAGE] Error updating activity state: {e}")

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
        from ..ds import clear_layout
        clear_layout(self._attn_stack)
        items = []
        for r in self._reminders[:5]:
            if not r.get("is_notified"):
                items.append(("⏰", "Reminder", r.get("task_text", "")[:60],
                              str(r.get("due_at") or "")[:16]))
        for e in self._events[:5]:
            items.append(("📅", "Event", (e.get("title") or "")[:60],
                         f"{e.get('date') or ''} {e.get('time') or ''}".strip()))
        if not items:
            empty = EmptyState(ICONS.CHECK, "Nothing urgent",
                              "No upcoming reminders or events require your attention.",
                              accent=C.STATUS_SUCCESS)
            self._attn_stack.addWidget(empty)
            return
        for icon_ch, kind, text, when in items:
            w = QFrame(); w.setProperty("class", "CardInner")
            l = QHBoxLayout(w); l.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
            l.setSpacing(Spacing.MD)
            ic = QLabel(icon_ch); ic.setStyleSheet("font-size: 18px; background: transparent;")
            l.addWidget(ic)
            c = QVBoxLayout(); c.setSpacing(2)
            t = QLabel(text); t.setStyleSheet(f"font-weight: 500; color: {C.TEXT}; background: transparent;")
            k = QLabel(f"{kind} · {when}"); k.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px; background: transparent;")
            c.addWidget(t); c.addWidget(k)
            l.addLayout(c, 1)
            self._attn_stack.addWidget(w)

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
        from ..ds import clear_layout
        clear_layout(self._hist_stack)
        msgs = [m for m in self._history if m.get("role") == "user"]
        if not msgs:
            empty = EmptyState(ICONS.ASSISTANT, "No conversations yet",
                          "Start by typing above or open Assistant page.",
                          accent=C.SEC_INTELLIGENCE)
            self._hist_stack.addWidget(empty)
            return
        for m in msgs[-6:]:
            w = QFrame(); w.setProperty("class", "CardInner")
            l = QHBoxLayout(w); l.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
            l.setSpacing(Spacing.MD)
            av = QLabel("U"); av.setFixedSize(28, 28)
            av.setAlignment(Qt.AlignmentFlag.AlignCenter)
            av.setStyleSheet(f"border-radius: 14px; background: {rgba_str(C.SEC_DASHBOARD, 0.15)}; color: {C.SEC_DASHBOARD}; font-weight: 700; font-size: 11px;")
            l.addWidget(av)
            col = QVBoxLayout(); col.setSpacing(0)
            t = QLabel((m.get("content") or "")[:90])
            t.setStyleSheet(f"color: {C.TEXT}; font-size: 12px; background: transparent;")
            t.setWordWrap(True)
            col.addWidget(t)
            sub = QLabel(str(m.get("created_at") or "")[:16])
            sub.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px; background: transparent;")
            col.addWidget(sub)
            l.addLayout(col, 1)
            self._hist_stack.addWidget(w)

    def on_visible(self):
        self._refresh_attention()
        self._refresh_history()
